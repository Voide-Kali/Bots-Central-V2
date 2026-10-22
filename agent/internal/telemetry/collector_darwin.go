//go:build darwin

package telemetry

import (
	"bufio"
	"context"
	"os/exec"
	"runtime"
	"sync"
	"syscall"
	"time"
)

// SystemCollector uses sysctl, statfs and the fixed system binaries
// /usr/bin/vm_stat and /usr/bin/top (no shell, fixed arguments). One
// `top -l 0 -s 1 -n 0` keeps running and reports the CPU share every second
// (ADR-018), so each sample is instant. macOS only exposes the CPU temperature
// to root (powermetrics), so it is omitted.
type SystemCollector struct {
	mu      sync.Mutex
	cpu     *float64
	cpuAt   time.Time
	started sync.Once
}

func NewSystemCollector() *SystemCollector { return &SystemCollector{} }

// cpuFreshness is how old the last top reading may be before it is not reported.
const cpuFreshness = 5 * time.Second

func (c *SystemCollector) watchCPU() {
	for {
		command := exec.Command("/usr/bin/top", "-l", "0", "-s", "1", "-n", "0")
		stdout, err := command.StdoutPipe()
		if err == nil && command.Start() == nil {
			scanner := bufio.NewScanner(stdout)
			for scanner.Scan() {
				if pct, ok := parseTopCPU(scanner.Text()); ok {
					c.mu.Lock()
					c.cpu, c.cpuAt = ptr(pct), time.Now()
					c.mu.Unlock()
				}
			}
			_ = command.Wait()
		}
		time.Sleep(5 * time.Second) // top ended or could not start: try again later
	}
}

func (c *SystemCollector) currentCPU() *float64 {
	c.started.Do(func() { go c.watchCPU() })
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.cpu == nil || time.Since(c.cpuAt) > cpuFreshness {
		return nil
	}
	value := *c.cpu
	return &value
}

func (c *SystemCollector) Collect() Sample {
	s := Sample{V: Version, CPUs: ptr(runtime.NumCPU()), CPUPercent: c.currentCPU()}
	if raw, err := syscall.Sysctl("vm.loadavg"); err == nil {
		if v, ok := decodeLoadavg(raw); ok {
			s.Load1 = ptr(v)
		}
	}
	if raw, err := syscall.Sysctl("hw.memsize"); err == nil {
		if total, ok := decodeUint64(raw); ok {
			ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
			out, err := exec.CommandContext(ctx, "/usr/bin/vm_stat").Output()
			cancel()
			if err == nil {
				if used, err := parseVMStat(string(out)); err == nil && used <= total {
					s.MemTotal, s.MemUsed = ptr(total), ptr(used)
				}
			}
		}
	}
	if raw, err := syscall.Sysctl("kern.boottime"); err == nil {
		if boot, ok := decodeBoottimeSeconds(raw); ok {
			if up := time.Now().Unix() - boot; up >= 0 {
				s.UptimeS = ptr(uint64(up))
			}
		}
	}
	var fs syscall.Statfs_t
	path := "/System/Volumes/Data"
	if err := syscall.Statfs(path, &fs); err != nil {
		path = "/"
		_ = syscall.Statfs(path, &fs)
	}
	if fs.Bsize > 0 {
		if total, used, ok := diskUsage(fs.Blocks, fs.Bfree, fs.Bavail, uint64(fs.Bsize)); ok {
			s.DiskTotal, s.DiskUsed = ptr(total), ptr(used)
		}
	}
	return Sanitize(s)
}
