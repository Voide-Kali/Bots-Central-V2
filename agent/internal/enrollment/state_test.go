package enrollment

import (
	"errors"
	"testing"

	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/storage"
)

func TestLifecyclePersistsAndGatesHeartbeat(t *testing.T) {
	store, err := storage.NewFileStore(t.TempDir())
	if err != nil {
		t.Fatalf("NewFileStore() error = %v", err)
	}
	state, err := New(store)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	if _, err := state.ActiveDeviceID(); !errors.Is(err, ErrNotEnrolled) {
		t.Fatalf("unpaired error = %v", err)
	}
	if err := state.SaveEnrollment(Record{DeviceID: "device-1", Status: StatusPending}); err != nil {
		t.Fatalf("SaveEnrollment(pending) error = %v", err)
	}
	if _, err := state.ActiveDeviceID(); !errors.Is(err, ErrPending) {
		t.Fatalf("pending error = %v", err)
	}
	if err := state.SaveEnrollment(Record{DeviceID: "device-1", Status: StatusActive}); err != nil {
		t.Fatalf("SaveEnrollment(active) error = %v", err)
	}
	restarted, err := New(store)
	if err != nil {
		t.Fatalf("restart New() error = %v", err)
	}
	if deviceID, err := restarted.ActiveDeviceID(); err != nil || deviceID != "device-1" {
		t.Fatalf("ActiveDeviceID() = %q, %v", deviceID, err)
	}
	if err := restarted.MarkStateLost(); err != nil {
		t.Fatalf("MarkStateLost() error = %v", err)
	}
	if _, err := restarted.ActiveDeviceID(); !errors.Is(err, ErrStateLost) {
		t.Fatalf("state loss error = %v", err)
	}
	if err := restarted.MarkRevoked(); err != nil {
		t.Fatalf("MarkRevoked() error = %v", err)
	}
	if _, err := restarted.ActiveDeviceID(); !errors.Is(err, ErrRevoked) {
		t.Fatalf("revocation error = %v", err)
	}
}

func TestEnrollmentRejectsInvalidRecords(t *testing.T) {
	store, err := storage.NewFileStore(t.TempDir())
	if err != nil {
		t.Fatalf("NewFileStore() error = %v", err)
	}
	state, err := New(store)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	for _, record := range []Record{{}, {DeviceID: " device", Status: StatusPending}, {DeviceID: "device", Status: StatusStateLost}} {
		if err := state.SaveEnrollment(record); err == nil {
			t.Fatalf("SaveEnrollment(%#v) succeeded", record)
		}
	}
}
