//go:build darwin

package telemetry

import (
	"context"
	"os/exec"
	"runtime"
	"syscall"
	"time"
)

// SystemCollector uses sysctl, statfs and the fixed system binary
// /usr/bin/vm_stat (no shell, no arguments). macOS does not expose CPU
// temperature or a cheap instantaneous CPU percentage without cgo, so those
// are omitted and load average is reported instead.
type SystemCollector struct{}

func NewSystemCollector() *SystemCollector { return &SystemCollector{} }

func (c *SystemCollector) Collect() Sample {
	s := Sample{V: Version, CPUs: ptr(runtime.NumCPU())}
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
		bsize := uint64(fs.Bsize)
		total := fs.Blocks * bsize
		free := fs.Bfree * bsize
		if free <= total {
			s.DiskTotal, s.DiskUsed = ptr(total), ptr(total-free)
		}
	}
	return Sanitize(s)
}
