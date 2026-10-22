package commands

import (
	"net"
	"strings"
	"testing"
)

func TestFormatScanParsesAndSortsHosts(t *testing.T) {
	raw := []byte(strings.Join([]string{
		"# Nmap 7.94 scan initiated",
		"Host: 192.168.1.10 (macmaker.local)\tStatus: Up",
		"Host: 192.168.1.1 (router.local)\tStatus: Up",
		"Host: 192.168.1.5 ()\tStatus: Up",
		"Host: 192.168.1.9 ()\tStatus: Down",
		"# Nmap done",
	}, "\n"))
	out := formatScan(raw)
	if !strings.HasPrefix(out, "3 aparelhos ligados na sua rede local:") {
		t.Fatalf("header/count wrong: %q", out)
	}
	if strings.Contains(out, "192.168.1.9") {
		t.Fatal("down hosts must not be listed")
	}
	// Sorted by IP: .1 before .5 before .10
	if i, j := strings.Index(out, "192.168.1.1 "), strings.Index(out, "192.168.1.10 "); i == -1 || j == -1 || i > j {
		t.Fatalf("not sorted by IP: %q", out)
	}
	if !strings.Contains(out, "192.168.1.1 - router.local") {
		t.Fatalf("name missing: %q", out)
	}
}

func TestFormatScanEmpty(t *testing.T) {
	if out := formatScan([]byte("# nothing up\n")); !strings.Contains(out, "Nenhum aparelho") {
		t.Fatalf("empty scan: %q", out)
	}
}

func mustCIDR(t *testing.T, cidr string) net.Addr {
	t.Helper()
	ip, inet, err := net.ParseCIDR(cidr)
	if err != nil {
		t.Fatal(err)
	}
	// ParseCIDR masks the IP; keep the host IP so To4()/IsPrivate see the address.
	inet.IP = ip
	return inet
}

func TestScanTargetsSkipsPublicLoopbackAndWide(t *testing.T) {
	addrs := []net.Addr{
		mustCIDR(t, "192.168.1.5/24"),  // kept
		mustCIDR(t, "10.0.0.3/8"),      // too wide: skipped
		mustCIDR(t, "127.0.0.1/8"),     // loopback: skipped
		mustCIDR(t, "8.8.8.8/24"),      // public: skipped
		mustCIDR(t, "192.168.1.6/24"),  // same network, deduped
	}
	targets := scanTargets(addrs)
	if len(targets) != 1 || targets[0] != "192.168.1.0/24" {
		t.Fatalf("targets = %v, want [192.168.1.0/24]", targets)
	}
}

func TestNetworkScanRunsOnlyWhenAllowed(t *testing.T) {
	raw := []byte("Host: 192.168.1.1 (gw)\tStatus: Up\n")

	disabled, err := NewExecutor("", []string{"lock_screen"})
	if err != nil {
		t.Fatal(err)
	}
	disabled.system = &fakeSystem{scanRaw: raw}
	if got := disabled.Execute(approved("network_scan", "")); got.OK || got.Error != "disabled" {
		t.Fatalf("scan without opt-in: %+v", got)
	}

	enabled, err := NewExecutor("", []string{"network_scan"})
	if err != nil {
		t.Fatal(err)
	}
	sys := &fakeSystem{scanRaw: raw}
	enabled.system = sys
	got := enabled.Execute(approved("network_scan", ""))
	if !got.OK || sys.scanned != 1 || !strings.Contains(string(got.Content), "192.168.1.1 - gw") {
		t.Fatalf("scan when enabled: %+v", got)
	}
	if got := enabled.Execute(approved("network_scan", "x")); got.OK || got.Error != "digest" {
		t.Fatalf("network_scan takes no argument: %+v", got)
	}
}
