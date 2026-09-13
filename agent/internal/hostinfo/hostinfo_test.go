package hostinfo

import (
	"errors"
	"testing"
)

func TestCollectHostnameAndPlatform(t *testing.T) {
	collector := Collector{hostname: func() (string, error) { return "  workstation-01  ", nil }, goos: "linux", goarch: "amd64"}
	status, err := collector.Collect()
	if err != nil {
		t.Fatalf("Collect() error = %v", err)
	}
	if status.Hostname != "workstation-01" || status.Platform != "linux/amd64" {
		t.Fatalf("unexpected status: %#v", status)
	}
}

func TestCollectRejectsInvalidHostname(t *testing.T) {
	collector := Collector{hostname: func() (string, error) { return "", errors.New("unavailable") }, goos: "linux", goarch: "amd64"}
	if _, err := collector.Collect(); err == nil {
		t.Fatal("Collect() succeeded")
	}
}
