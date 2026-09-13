// Package enrollment persists the backend-owned device lifecycle locally.
package enrollment

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"
	"sync"
	"unicode/utf8"

	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/storage"
)

const recordName = "device-enrollment-v1.json"

var (
	ErrNotEnrolled = errors.New("enrollment: device is not enrolled")
	ErrPending     = errors.New("enrollment: device is pending activation")
	ErrStateLost   = errors.New("enrollment: local state is lost")
	ErrRevoked     = errors.New("enrollment: device is revoked")
)

// Status is a server-governed lifecycle value. The agent promotes PENDING only
// after its signed heartbeat receives the backend's accepted response.
type Status string

const (
	StatusPending   Status = "pending"
	StatusActive    Status = "active"
	StatusStateLost Status = "state_lost"
	StatusRevoked   Status = "revoked"
)

// Record contains no credential material. It is intentionally safe to inspect in
// tests and diagnostics, but it must still remain owner-only with the state store.
type Record struct {
	DeviceID string
	Status   Status
}

type diskRecord struct {
	Version  int    `json:"version"`
	DeviceID string `json:"device_id"`
	Status   Status `json:"status"`
}

// Store serializes lifecycle updates within the process and delegates durable
// atomic writes to the owner-only FileStore.
type Store struct {
	store storage.Store
	mu    sync.Mutex
}

func New(store storage.Store) (*Store, error) {
	if store == nil {
		return nil, errors.New("enrollment: store is required")
	}
	return &Store{store: store}, nil
}

func (s *Store) Load() (Record, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.loadLocked()
}

// SaveEnrollment records only the device identifier and server-returned state.
// Pairing tokens and proof material are never accepted here.
func (s *Store) SaveEnrollment(record Record) error {
	if err := validate(record); err != nil {
		return err
	}
	if record.Status != StatusPending && record.Status != StatusActive {
		return errors.New("enrollment: enrollment response must be pending or active")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.writeLocked(record)
}

// MarkActive records backend activation only after the first accepted heartbeat
// probe. It never promotes an unrelated lifecycle state.
func (s *Store) MarkActive() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	record, err := s.loadLocked()
	if err != nil {
		return err
	}
	if record.Status != StatusPending {
		return errors.New("enrollment: only pending enrollment may become active")
	}
	record.Status = StatusActive
	return s.writeLocked(record)
}

// MarkStateLost prevents retries after a stale sequence response. It does not
// alter the local Ed25519 private key, which is stored separately.
func (s *Store) MarkStateLost() error { return s.setStatus(StatusStateLost) }

// MarkRevoked prevents ordinary heartbeats after the server revokes the device.
// It intentionally leaves the local private key intact for operator-led recovery.
func (s *Store) MarkRevoked() error { return s.setStatus(StatusRevoked) }

func (s *Store) setStatus(next Status) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	record, err := s.loadLocked()
	if err != nil {
		return err
	}
	record.Status = next
	return s.writeLocked(record)
}

func (s *Store) loadLocked() (Record, error) {
	data, err := s.store.Read(recordName)
	if errors.Is(err, os.ErrNotExist) {
		return Record{}, ErrNotEnrolled
	}
	if err != nil {
		return Record{}, fmt.Errorf("enrollment: read local record: %w", err)
	}
	if len(data) > 8*1024 {
		return Record{}, errors.New("enrollment: local record exceeds maximum size")
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var disk diskRecord
	if err := decoder.Decode(&disk); err != nil {
		return Record{}, errors.New("enrollment: malformed local record")
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return Record{}, errors.New("enrollment: malformed local record")
	}
	record := Record{DeviceID: disk.DeviceID, Status: disk.Status}
	if disk.Version != 1 || validate(record) != nil {
		return Record{}, errors.New("enrollment: unsupported local record")
	}
	return record, nil
}

func (s *Store) writeLocked(record Record) error {
	data, err := json.Marshal(diskRecord{Version: 1, DeviceID: record.DeviceID, Status: record.Status})
	if err != nil {
		return fmt.Errorf("enrollment: encode local record: %w", err)
	}
	if err := s.store.WriteAtomic(recordName, data); err != nil {
		return fmt.Errorf("enrollment: write local record: %w", err)
	}
	return nil
}

func validate(record Record) error {
	if record.DeviceID == "" || record.DeviceID != strings.TrimSpace(record.DeviceID) || !utf8.ValidString(record.DeviceID) || len(record.DeviceID) > 256 {
		return errors.New("enrollment: invalid device ID")
	}
	switch record.Status {
	case StatusPending, StatusActive, StatusStateLost, StatusRevoked:
		return nil
	default:
		return errors.New("enrollment: invalid status")
	}
}
