//go:build linux

package telemetry

import (
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
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
			if total, used, ok := diskUsage(fs.Blocks, fs.Bfree, fs.Bavail, uint64(fs.Bsize)); ok {
				s.DiskTotal, s.DiskUsed = ptr(total), ptr(used)
			}
		}
	}
	s.TemperatureC = c.temperature()
	s.BatteryPercent, s.BatteryCharging = c.battery()
	return Sanitize(s)
}

// battery returns the charge level and charging flag of the first battery power
// supply, or (nil, nil) on a machine without one. It reads only the aggregate
// capacity and status files, like every other metric here.
func (c *SystemCollector) battery() (*int, *bool) {
	dirs, _ := filepath.Glob(c.path("/sys/class/power_supply/BAT*"))
	for i, dir := range dirs {
		if i >= 8 {
			break
		}
		data, err := os.ReadFile(filepath.Join(dir, "capacity"))
		if err != nil {
			continue
		}
		level, err := strconv.Atoi(strings.TrimSpace(string(data)))
		if err != nil {
			continue
		}
		var charging *bool
		if status, err := os.ReadFile(filepath.Join(dir, "status")); err == nil {
			charging = ptr(strings.EqualFold(strings.TrimSpace(string(status)), "Charging"))
		}
		return ptr(level), charging
	}
	return nil, nil
}

// cpuSensorDrivers are hwmon drivers that report the processor itself. When one is
// present we trust only it: vendor/firmware sensors (for example Dell's dell_smm)
// sometimes expose bogus channels such as a constant 126 °C.
var cpuSensorDrivers = map[string]bool{
	"coretemp": true, "k10temp": true, "zenpower": true, "cpu_thermal": true, "soc_thermal": true,
}

// maxPlausibleC drops readings no running consumer machine reports for real.
const maxPlausibleC = 110

// temperature returns the hottest CPU sensor, or the hottest plausible zone when the
// machine exposes no recognised CPU driver.
func (c *SystemCollector) temperature() *float64 {
	hwmonDirs, _ := filepath.Glob(c.path("/sys/class/hwmon/hwmon*"))
	var cpu []string
	for i, dir := range hwmonDirs {
		if i >= 32 {
			break
		}
		name, err := os.ReadFile(filepath.Join(dir, "name"))
		if err == nil && cpuSensorDrivers[strings.TrimSpace(string(name))] {
			files, _ := filepath.Glob(filepath.Join(dir, "temp*_input"))
			cpu = append(cpu, files...)
		}
	}
	if best := hottest(cpu); best != nil {
		return best
	}
	matches, _ := filepath.Glob(c.path("/sys/class/thermal/thermal_zone*/temp"))
	hwmon, _ := filepath.Glob(c.path("/sys/class/hwmon/hwmon*/temp*_input"))
	return hottest(append(matches, hwmon...))
}

func hottest(files []string) *float64 {
	var best *float64
	for i, file := range files {
		if i >= 64 {
			break
		}
		data, err := os.ReadFile(file)
		if err != nil {
			continue
		}
		v, err := parseMilliCelsius(string(data))
		if err != nil || v <= 0 || v > maxPlausibleC {
			continue
		}
		if best == nil || v > *best {
			best = ptr(v)
		}
	}
	return best
}
