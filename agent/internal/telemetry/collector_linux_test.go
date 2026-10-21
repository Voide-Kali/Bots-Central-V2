//go:build linux

package telemetry

import (
	"os"
	"path/filepath"
	"testing"
)

func write(t *testing.T, root, path, content string) {
	t.Helper()
	full := filepath.Join(root, path)
	if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(full, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestLinuxCollectorFromFixtureTree(t *testing.T) {
	root := t.TempDir()
	write(t, root, "/proc/stat", "cpu  100 0 100 700 100 0 0 0 0 0\n")
	write(t, root, "/proc/loadavg", "0.25 0.2 0.1 1/100 42\n")
	write(t, root, "/proc/meminfo", "MemTotal: 2000 kB\nMemAvailable: 500 kB\n")
	write(t, root, "/proc/uptime", "123.45 99.0\n")
	write(t, root, "/sys/class/thermal/thermal_zone0/temp", "41000\n")
	write(t, root, "/sys/class/hwmon/hwmon1/temp1_input", "55500\n")
	c := &SystemCollector{root: root}
	first := c.Collect()
	if first.CPUPercent != nil {
		t.Fatal("first sample has no CPU delta")
	}
	write(t, root, "/proc/stat", "cpu  150 0 150 750 150 0 0 0 0 0\n")
	s := c.Collect()
	if s.CPUPercent == nil || *s.CPUPercent != 50 {
		t.Fatalf("cpu=%v", s.CPUPercent)
	}
	if s.Load1 == nil || *s.Load1 != 0.25 || *s.MemTotal != 2000*1024 || *s.MemUsed != 1500*1024 || *s.UptimeS != 123 {
		t.Fatalf("sample=%+v", s)
	}
	if s.TemperatureC == nil || *s.TemperatureC != 55.5 {
		t.Fatalf("temp=%v", s.TemperatureC)
	}
}

func TestLinuxCollectorRealSystemNeverPanics(t *testing.T) {
	s := NewSystemCollector().Collect()
	if s.V != Version || s.CPUs == nil {
		t.Fatalf("sample=%+v", s)
	}
}
