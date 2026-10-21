// Package telemetry collects bounded system metrics for the signed heartbeat
// (ADR-012). It reads only aggregate counters: no processes, files, users,
// network addresses, or peripherals. Collection is best-effort: a metric that
// cannot be read is omitted rather than guessed.
package telemetry

import "math"

// Version is the wire version of the heartbeat "tel" claim.
const Version = 1

// Sample is the wire form of the heartbeat "tel" claim. Pointer fields are
// omitted when the platform does not expose the metric.
type Sample struct {
	V            int      `json:"v"`
	CPUPercent   *float64 `json:"cpu_pct,omitempty"`
	Load1        *float64 `json:"load1,omitempty"`
	CPUs         *int     `json:"cpus,omitempty"`
	MemTotal     *uint64  `json:"mem_total,omitempty"`
	MemUsed      *uint64  `json:"mem_used,omitempty"`
	DiskTotal    *uint64  `json:"disk_total,omitempty"`
	DiskUsed     *uint64  `json:"disk_used,omitempty"`
	TemperatureC *float64 `json:"temp_c,omitempty"`
	UptimeS      *uint64  `json:"uptime_s,omitempty"`
}

// Collector returns one sample. Implementations must not block for long.
type Collector interface {
	Collect() Sample
}

const maxSigned64 = uint64(math.MaxInt64)

// Sanitize drops values the backend would reject, so a single odd sensor
// reading never blocks presence heartbeats.
func Sanitize(s Sample) Sample {
	s.V = Version
	s.CPUPercent = clampFloat(s.CPUPercent, 0, 100)
	if s.Load1 != nil && (math.IsNaN(*s.Load1) || math.IsInf(*s.Load1, 0) || *s.Load1 < 0 || *s.Load1 > 1e6) {
		s.Load1 = nil
	}
	if s.CPUs != nil && (*s.CPUs < 1 || *s.CPUs > 65536) {
		s.CPUs = nil
	}
	s.MemTotal, s.MemUsed = pair(s.MemTotal, s.MemUsed)
	s.DiskTotal, s.DiskUsed = pair(s.DiskTotal, s.DiskUsed)
	if s.TemperatureC != nil && (math.IsNaN(*s.TemperatureC) || *s.TemperatureC < -50 || *s.TemperatureC > 150) {
		s.TemperatureC = nil
	}
	if s.UptimeS != nil && *s.UptimeS > maxSigned64 {
		s.UptimeS = nil
	}
	return s
}

func clampFloat(v *float64, low, high float64) *float64 {
	if v == nil || math.IsNaN(*v) || math.IsInf(*v, 0) {
		return nil
	}
	c := math.Min(math.Max(*v, low), high)
	c = math.Round(c*10) / 10
	return &c
}

func pair(total, used *uint64) (*uint64, *uint64) {
	if total == nil || used == nil || *total > maxSigned64 || *used > *total {
		return nil, nil
	}
	return total, used
}

func ptr[T any](v T) *T { return &v }
