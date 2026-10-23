//go:build darwin

package telemetry

import (
	"context"
	"os/exec"
	"runtime"
	"syscall"
	"time"
)

// SystemCollector uses sysctl, statfs and the fixed system binaries
// /usr/bin/vm_stat and /usr/bin/top (no shell, fixed arguments). The CPU
// percentage comes from top's second one-second sample. macOS only exposes the
// CPU temperature to root (powermetrics), so it is omitted.
type SystemCollector struct{}

func NewSystemCollector() *SystemCollector { return &SystemCollector{} }

func (c *SystemCollector) Collect() Sample {
	s := Sample{V: Version, CPUs: ptr(runtime.NumCPU())}
	if raw, err := syscall.Sysctl("vm.loadavg"); err == nil {
		if v, ok := decodeLoadavg(raw); ok {
			s.Load1 = ptr(v)
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	if out, err := exec.CommandContext(ctx, "/usr/bin/top", "-l", "2", "-n", "0", "-s", "1").Output(); err == nil {
		if pct, ok := parseTopCPU(string(out)); ok {
			s.CPUPercent = ptr(pct)
		}
	}
	cancel()
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
