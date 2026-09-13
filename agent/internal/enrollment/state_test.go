package enrollment

import (
	"bytes"
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
	if _, err := state.Load(); !errors.Is(err, ErrNotEnrolled) {
		t.Fatalf("unpaired error = %v", err)
	}
	if err := state.SaveEnrollment(Record{DeviceID: "123e4567-e89b-12d3-a456-426614174000", Status: StatusPending}); err != nil {
		t.Fatalf("SaveEnrollment(pending) error = %v", err)
	}
	if record, err := state.Load(); err != nil || record.Status != StatusPending {
		t.Fatalf("Load(pending) = %#v, %v", record, err)
	}
	if err := state.MarkActive(); err != nil {
		t.Fatalf("MarkActive() error = %v", err)
	}
	restarted, err := New(store)
	if err != nil {
		t.Fatalf("restart New() error = %v", err)
	}
	if record, err := restarted.Load(); err != nil || record.Status != StatusActive {
		t.Fatalf("Load(active restart) = %#v, %v", record, err)
	}
	if err := restarted.MarkStateLost(); err != nil {
		t.Fatalf("MarkStateLost() error = %v", err)
	}
	if record, err := restarted.Load(); err != nil || record.Status != StatusStateLost {
		t.Fatalf("Load(state lost) = %#v, %v", record, err)
	}
	if err := restarted.MarkRevoked(); err != nil {
		t.Fatalf("MarkRevoked() error = %v", err)
	}
	if record, err := restarted.Load(); err != nil || record.Status != StatusRevoked {
		t.Fatalf("Load(revoked) = %#v, %v", record, err)
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

func TestEnrollmentRecordContainsNoPairingOrProofMaterial(t *testing.T) {
	store, err := storage.NewFileStore(t.TempDir())
	if err != nil {
		t.Fatalf("NewFileStore() error = %v", err)
	}
	state, err := New(store)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	if err := state.SaveEnrollment(Record{DeviceID: "123e4567-e89b-12d3-a456-426614174000", Status: StatusPending}); err != nil {
		t.Fatalf("SaveEnrollment() error = %v", err)
	}
	record, err := store.Read(recordName)
	if err != nil {
		t.Fatalf("Read() error = %v", err)
	}
	for _, forbidden := range [][]byte{[]byte("pairing_token"), []byte("proof"), []byte("private_key")} {
		if bytes.Contains(record, forbidden) {
			t.Fatalf("enrollment record contains forbidden material key %q", forbidden)
		}
	}
}
