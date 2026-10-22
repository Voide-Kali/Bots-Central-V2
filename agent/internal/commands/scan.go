package commands

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"net"
	"os/exec"
	"sort"
	"strings"
	"time"
)

// network_scan (ADR-020): list the devices on the owner's own local network. The agent
// never gets a target from the server; it scans only the private IPv4 subnets of its own
// interfaces, with a fixed program and fixed arguments (no shell). Read-only: nmap -sn does
// host discovery only, it changes nothing.

const (
	scanTimeout   = 60 * time.Second
	maxScanBytes  = 512 * 1024 // raw nmap output cap
	maxScanResult = 8 * 1024   // friendly text returned to the owner
	maxScanHosts  = 256        // never scan a subnet wider than this many addresses
)

func (e *Executor) networkScan() Result {
	ctx, cancel := context.WithTimeout(context.Background(), scanTimeout)
	defer cancel()
	raw, err := e.system.NetworkScan(ctx)
	if err != nil {
		return Result{Error: failure(err)}
	}
	text := formatScan(raw)
	content := []byte(text)
	sum := sha256.Sum256(content)
	return Result{OK: true, Content: content, SHA256: hex.EncodeToString(sum[:])}
}

// scanTargets returns the private IPv4 networks of the host's up, non-loopback interfaces,
// skipping subnets wider than maxScanHosts so a scan can never blow up.
func scanTargets(addrs []net.Addr) []string {
	seen := map[string]bool{}
	var targets []string
	for _, addr := range addrs {
		ipnet, ok := addr.(*net.IPNet)
		if !ok {
			continue
		}
		ip4 := ipnet.IP.To4()
		if ip4 == nil || !ip4.IsPrivate() {
			continue
		}
		ones, bits := ipnet.Mask.Size()
		if bits != 32 || ones == 0 {
			continue
		}
		if (1 << (bits - ones)) > maxScanHosts {
			continue // too wide to scan quickly; skip
		}
		network := (&net.IPNet{IP: ip4.Mask(ipnet.Mask), Mask: ipnet.Mask}).String()
		if !seen[network] {
			seen[network] = true
			targets = append(targets, network)
		}
	}
	sort.Strings(targets)
	return targets
}

// formatScan turns nmap's greppable output ("Host: <ip> (<name>) Status: Up") into a short,
// readable list for the owner, newest-style plain text, bounded in size.
func formatScan(raw []byte) string {
	type host struct{ ip, name string }
	var hosts []host
	scanner := bufio.NewScanner(bytes.NewReader(raw))
	scanner.Buffer(make([]byte, 64*1024), 256*1024)
	for scanner.Scan() {
		line := scanner.Text()
		if !strings.HasPrefix(line, "Host:") || !strings.Contains(line, "Status: Up") {
			continue
		}
		fields := strings.Fields(line)
		if len(fields) < 2 {
			continue
		}
		ip := fields[1]
		name := ""
		if open := strings.Index(line, "("); open != -1 {
			if close := strings.Index(line[open:], ")"); close > 1 {
				name = line[open+1 : open+close]
			}
		}
		hosts = append(hosts, host{ip: ip, name: name})
	}
	if len(hosts) == 0 {
		return "Nenhum aparelho respondeu na sua rede local."
	}
	sort.Slice(hosts, func(i, j int) bool { return lessIP(hosts[i].ip, hosts[j].ip) })
	var builder strings.Builder
	fmt.Fprintf(&builder, "%d aparelhos ligados na sua rede local:\n", len(hosts))
	for _, h := range hosts {
		line := h.ip
		if h.name != "" {
			line += " - " + h.name
		}
		if builder.Len()+len(line)+1 > maxScanResult {
			builder.WriteString("(lista truncada)")
			break
		}
		builder.WriteString("\n")
		builder.WriteString(line)
	}
	return builder.String()
}

func lessIP(a, b string) bool {
	ipA, ipB := net.ParseIP(a), net.ParseIP(b)
	if ipA == nil || ipB == nil {
		return a < b
	}
	return bytes.Compare(ipA.To16(), ipB.To16()) < 0
}

func (hostSystem) NetworkScan(ctx context.Context) ([]byte, error) {
	addrs, err := net.InterfaceAddrs()
	if err != nil {
		return nil, err
	}
	targets := scanTargets(addrs)
	if len(targets) == 0 {
		return nil, errUnsupported
	}
	path, err := exec.LookPath("nmap")
	if err != nil {
		return nil, err
	}
	args := append([]string{"-sn", "-oG", "-"}, targets...)
	command := exec.CommandContext(ctx, path, args...)
	var out bytes.Buffer
	command.Stdin = nil
	command.Stdout = &limitedWriter{buffer: &out, limit: maxScanBytes}
	command.Stderr = nil
	if err := command.Run(); err != nil {
		return nil, err
	}
	return out.Bytes(), nil
}

// limitedWriter stops nmap from flooding memory if its output is ever unexpectedly large.
type limitedWriter struct {
	buffer *bytes.Buffer
	limit  int
}

func (w *limitedWriter) Write(p []byte) (int, error) {
	if remaining := w.limit - w.buffer.Len(); remaining > 0 {
		if len(p) > remaining {
			w.buffer.Write(p[:remaining])
		} else {
			w.buffer.Write(p)
		}
	}
	return len(p), nil // always report full consumption so nmap is not interrupted
}
