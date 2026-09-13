// Package hostinfo collects the intentionally minimal local status used by heartbeats.
package hostinfo

import (
	"errors"
	"fmt"
	"os"
	"runtime"
	"strings"
)

type Status struct {
	Hostname string
	Platform string
}

// Collector permits deterministic tests while the system collector remains tiny.
type Collector struct {
	hostname func() (string, error)
	goos     string
	goarch   string
}

func SystemCollector() Collector {
	return Collector{hostname: os.Hostname, goos: runtime.GOOS, goarch: runtime.GOARCH}
}

// Collect returns only hostname and OS/architecture. It does not inspect files,
// processes, addresses, location, peripherals, clipboard, or shell history.
func (c Collector) Collect() (Status, error) {
	if c.hostname == nil {
		return Status{}, errors.New("hostinfo: hostname collector is required")
	}
	hostname, err := c.hostname()
	if err != nil {
		return Status{}, fmt.Errorf("hostinfo: collect hostname: %w", err)
	}
	hostname = strings.TrimSpace(hostname)
	if hostname == "" {
		return Status{}, errors.New("hostinfo: hostname is empty")
	}
	if c.goos == "" || c.goarch == "" {
		return Status{}, errors.New("hostinfo: platform is empty")
	}
	return Status{Hostname: hostname, Platform: c.goos + "/" + c.goarch}, nil
}
