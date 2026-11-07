// Package netloc collects the computer's network location for the opt-in `net`
// heartbeat claim (ADR-036): its non-loopback local IPs and a best-effort public
// IP. It is wired in only when the network_location sensor is enabled, so nothing
// here runs and no address is collected unless the owner opted in.
package netloc

import (
	"context"
	"errors"
	"io"
	"net"
	"net/http"
	"strings"
	"sync"
	"time"
)

// Version is the wire version of the heartbeat `net` claim.
const Version = 1

// Info is the wire form of the heartbeat `net` claim. It must match the backend
// parser (app/devices/network.py): v, optional public_ip, optional local_ips.
type Info struct {
	V        int      `json:"v"`
	PublicIP *string  `json:"public_ip,omitempty"`
	LocalIPs []string `json:"local_ips,omitempty"`
}

const (
	defaultPublicIPURL = "https://api.ipify.org"
	publicIPTTL        = 15 * time.Minute
	maxLocalIPs        = 16
	maxBodyBytes       = 64
)

// Collector gathers local and public addresses. Dependencies are injectable for tests.
type Collector struct {
	localAddrs    func() ([]net.Addr, error)
	fetchPublicIP func(ctx context.Context) (string, error)
	now           func() time.Time

	mu        sync.Mutex
	publicIP  string
	fetchedAt time.Time
}

// NewCollector builds the production collector. The HTTP client should carry a short
// timeout so a slow public-IP lookup never stalls heartbeats.
func NewCollector(client *http.Client) *Collector {
	return &Collector{
		localAddrs: net.InterfaceAddrs,
		fetchPublicIP: func(ctx context.Context) (string, error) {
			return fetchPublicIP(ctx, client, defaultPublicIPURL)
		},
		now: time.Now,
	}
}

// Collect returns the current network location, or nil when nothing is known.
func (c *Collector) Collect(ctx context.Context) *Info {
	locals := c.localIPs()
	public := c.cachedPublicIP(ctx)
	if public == "" && len(locals) == 0 {
		return nil
	}
	info := &Info{V: Version, LocalIPs: locals}
	if public != "" {
		info.PublicIP = &public
	}
	return info
}

func (c *Collector) localIPs() []string {
	addrs, err := c.localAddrs()
	if err != nil {
		return nil
	}
	seen := map[string]bool{}
	out := []string{}
	for _, addr := range addrs {
		ipnet, ok := addr.(*net.IPNet)
		if !ok {
			continue
		}
		ip := ipnet.IP
		if ip == nil || ip.IsLoopback() || ip.IsLinkLocalUnicast() || ip.IsLinkLocalMulticast() {
			continue
		}
		s := ip.String()
		if !seen[s] {
			seen[s] = true
			out = append(out, s)
			if len(out) >= maxLocalIPs {
				break
			}
		}
	}
	return out
}

func (c *Collector) cachedPublicIP(ctx context.Context) string {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.publicIP != "" && c.now().Sub(c.fetchedAt) < publicIPTTL {
		return c.publicIP
	}
	ip, err := c.fetchPublicIP(ctx)
	if err != nil {
		return c.publicIP // keep the last good value (maybe empty) on failure
	}
	ip = strings.TrimSpace(ip)
	if net.ParseIP(ip) == nil {
		return c.publicIP
	}
	c.publicIP = ip
	c.fetchedAt = c.now()
	return c.publicIP
}

func fetchPublicIP(ctx context.Context, client *http.Client, url string) (string, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return "", err
	}
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", errors.New("netloc: public IP service returned a non-200 status")
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxBodyBytes))
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(body)), nil
}
