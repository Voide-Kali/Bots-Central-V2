//go:build !linux && !darwin

package telemetry

import "runtime"

// SystemCollector reports only the CPU count on unsupported platforms.
type SystemCollector struct{}

func NewSystemCollector() *SystemCollector { return &SystemCollector{} }

func (c *SystemCollector) Collect() Sample {
	return Sanitize(Sample{V: Version, CPUs: ptr(runtime.NumCPU())})
}
