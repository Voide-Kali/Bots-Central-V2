package heartbeat

import (
	"testing"
	"time"

	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/hostinfo"
)

func TestModelContainsOnlyRequiredHeartbeatFields(t *testing.T) {
	timestamp := time.Date(2026, 9, 9, 10, 0, 0, 0, time.FixedZone("test", -3*60*60))
	model, err := New("device-123", hostinfo.Status{Hostname: "workstation", Platform: "linux/amd64"}, "0.1.0", timestamp, "mvp1-heartbeat-model-v1")
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	if model.DeviceID != "device-123" || model.Hostname != "workstation" || model.Platform != "linux/amd64" || model.AgentVersion != "0.1.0" || model.CapabilityVersion != "mvp1-heartbeat-model-v1" {
		t.Fatalf("unexpected model: %#v", model)
	}
	if model.Timestamp.Location() != time.UTC {
		t.Fatalf("timestamp location = %v, want UTC", model.Timestamp.Location())
	}
}

func TestModelRejectsMissingDeviceID(t *testing.T) {
	if _, err := New("", hostinfo.Status{Hostname: "workstation", Platform: "linux/amd64"}, "0.1.0", time.Now(), "v1"); err == nil {
		t.Fatal("New() succeeded")
	}
}
