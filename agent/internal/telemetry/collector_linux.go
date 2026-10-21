//go:build linux

package telemetry

import (
	"os"
	"path/filepath"
	"runtime"
	"sync"
	"syscall"
)

// SystemCollector reads /proc, /sys and statfs("/").
type SystemCollector struct {
	mu       sync.Mutex
	previous *cpuTimes
	root     string // test hook; empty means "/"
}

func NewSystemCollector() *SystemCollector { return &SystemCollector{} }

func (c *SystemCollector) path(p string) string {
	if c.root == "" {
		return p
	}
	return filepath.Join(c.root, p)
}

func (c *SystemCollector) read(p string) (string, bool) {
	data, err := os.ReadFile(c.path(p))
	if err != nil || len(data) > 1<<20 {
		return "", false
	}
	return string(data), true
}

func (c *SystemCollector) Collect() Sample {
	s := Sample{V: Version, CPUs: ptr(runtime.NumCPU())}
	if content, ok := c.read("/proc/stat"); ok {
		if current, err := parseProcStat(content); err == nil {
			c.mu.Lock()
			if c.previous != nil {
				if pct, ok := cpuPercent(*c.previous, current); ok {
					s.CPUPercent = ptr(pct)
				}
			}
			c.previous = &current
			c.mu.Unlock()
		}
	}
	if content, ok := c.read("/proc/loadavg"); ok {
		if v, err := parseFirstFloat(content); err == nil {
			s.Load1 = ptr(v)
		}
	}
	if content, ok := c.read("/proc/meminfo"); ok {
		if total, used, err := parseMeminfo(content); err == nil {
			s.MemTotal, s.MemUsed = ptr(total), ptr(used)
		}
	}
	if content, ok := c.read("/proc/uptime"); ok {
		if v, err := parseFirstFloat(content); err == nil && v >= 0 {
			s.UptimeS = ptr(uint64(v))
		}
	}
	if c.root == "" {
		var fs syscall.Statfs_t
		if err := syscall.Statfs("/", &fs); err == nil && fs.Bsize > 0 {
			bsize := uint64(fs.Bsize)
			total := fs.Blocks * bsize
			free := fs.Bfree * bsize
			if free <= total {
				s.DiskTotal, s.DiskUsed = ptr(total), ptr(total-free)
			}
		}
	}
	s.TemperatureC = c.temperature()
	return Sanitize(s)
}

// temperature returns the hottest thermal zone, if any is exposed.
func (c *SystemCollector) temperature() *float64 {
	matches, _ := filepath.Glob(c.path("/sys/class/thermal/thermal_zone*/temp"))
	hwmon, _ := filepath.Glob(c.path("/sys/class/hwmon/hwmon*/temp*_input"))
	matches = append(matches, hwmon...)
	var best *float64
	for i, file := range matches {
		if i >= 64 {
			break
		}
		data, err := os.ReadFile(file)
		if err != nil {
			continue
		}
		v, err := parseMilliCelsius(string(data))
		if err != nil || v <= 0 || v > 150 {
			continue
		}
		if best == nil || v > *best {
			best = ptr(v)
		}
	}
	return best
}
