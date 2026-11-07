package netloc

import (
	"context"
	"encoding/json"
	"errors"
	"net"
	"strings"
	"testing"
	"time"
)

func addr(cidr string) net.Addr {
	ip, ipnet, _ := net.ParseCIDR(cidr)
	ipnet.IP = ip
	return ipnet
}

func TestLocalIPsFiltersLoopbackLinkLocalAndDedupes(t *testing.T) {
	c := &Collector{
		localAddrs: func() ([]net.Addr, error) {
			return []net.Addr{
				addr("127.0.0.1/8"),
				addr("::1/128"),
				addr("169.254.1.2/16"),
				addr("192.168.1.5/24"),
				addr("192.168.1.5/24"),
				addr("10.0.0.2/8"),
			}, nil
		},
		fetchPublicIP: func(context.Context) (string, error) { return "", errors.New("off") },
		now:           time.Now,
	}
	info := c.Collect(context.Background())
	if info == nil {
		t.Fatal("expected info")
	}
	if got := strings.Join(info.LocalIPs, ","); got != "192.168.1.5,10.0.0.2" {
		t.Fatalf("local ips = %q", got)
	}
	if info.PublicIP != nil {
		t.Fatalf("expected no public ip, got %v", *info.PublicIP)
	}
	if info.V != Version {
		t.Fatalf("version = %d", info.V)
	}
}

func TestPublicIPCachedWithinTTLThenRefetches(t *testing.T) {
	calls := 0
	nowT := time.Unix(1000, 0)
	c := &Collector{
		localAddrs: func() ([]net.Addr, error) { return nil, nil },
		fetchPublicIP: func(context.Context) (string, error) {
			calls++
			return "203.0.113.7", nil
		},
		now: func() time.Time { return nowT },
	}
	for i := 0; i < 3; i++ {
		info := c.Collect(context.Background())
		if info == nil || info.PublicIP == nil || *info.PublicIP != "203.0.113.7" {
			t.Fatalf("iteration %d: %+v", i, info)
		}
	}
	if calls != 1 {
		t.Fatalf("expected 1 fetch (cached), got %d", calls)
	}
	nowT = nowT.Add(publicIPTTL + time.Second)
	c.Collect(context.Background())
	if calls != 2 {
		t.Fatalf("expected a refetch after the TTL, got %d", calls)
	}
}

func TestCollectReturnsNilWhenNothingKnown(t *testing.T) {
	c := &Collector{
		localAddrs:    func() ([]net.Addr, error) { return nil, nil },
		fetchPublicIP: func(context.Context) (string, error) { return "", errors.New("off") },
		now:           time.Now,
	}
	if c.Collect(context.Background()) != nil {
		t.Fatal("expected nil when nothing is known")
	}
}

func TestPublicIPRejectsGarbage(t *testing.T) {
	c := &Collector{
		localAddrs:    func() ([]net.Addr, error) { return nil, nil },
		fetchPublicIP: func(context.Context) (string, error) { return "not-an-ip", nil },
		now:           time.Now,
	}
	if c.Collect(context.Background()) != nil {
		t.Fatal("garbage public ip should yield nil")
	}
}

func TestInfoJSONShapeMatchesBackend(t *testing.T) {
	ip := "203.0.113.7"
	data, err := json.Marshal(&Info{V: 1, PublicIP: &ip, LocalIPs: []string{"192.168.0.2"}})
	if err != nil {
		t.Fatal(err)
	}
	var decoded map[string]any
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatal(err)
	}
	if decoded["v"] != float64(1) || decoded["public_ip"] != "203.0.113.7" {
		t.Fatalf("shape: %s", data)
	}
	data2, _ := json.Marshal(&Info{V: 1, LocalIPs: []string{"10.0.0.1"}})
	if strings.Contains(string(data2), "public_ip") {
		t.Fatalf("expected public_ip omitted when nil: %s", data2)
	}
}
