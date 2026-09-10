// Package sequence allocates durable, strictly increasing heartbeat sequences.
package sequence

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"os"
	"sync"

	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/storage"
)

const (
	recordName = "heartbeat-sequence-v1.json"
	lockName   = "heartbeat-sequence-v1.lock"
)

var ErrExhausted = errors.New("sequence: uint64 sequence exhausted")

type diskRecord struct {
	Version int    `json:"version"`
	Last    uint64 `json:"last_sequence"`
}

// Store commits each value before returning it. It combines an in-process mutex
// with an owner-only advisory file lock, so concurrent agent processes sharing a
// state directory reload and advance one authoritative value at a time.
type Store struct {
	store storage.LockingStore
	mu    sync.Mutex
}

func New(store storage.Store) (*Store, error) {
	if store == nil {
		return nil, errors.New("sequence: store is required")
	}
	lockingStore, ok := store.(storage.LockingStore)
	if !ok {
		return nil, errors.New("sequence: store does not support exclusive locking")
	}
	return &Store{store: lockingStore}, nil
}

func (s *Store) Next() (uint64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var next uint64
	err := s.store.WithExclusiveLock(lockName, func() error {
		last, err := s.readLocked()
		if err != nil {
			return err
		}
		if last == math.MaxUint64 {
			return ErrExhausted
		}
		next = last + 1
		data, err := json.Marshal(diskRecord{Version: 1, Last: next})
		if err != nil {
			return fmt.Errorf("sequence: encode record: %w", err)
		}
		if err := s.store.WriteAtomic(recordName, data); err != nil {
			return fmt.Errorf("sequence: persist next sequence: %w", err)
		}
		return nil
	})
	if err != nil {
		return 0, err
	}
	return next, nil
}

func (s *Store) readLocked() (uint64, error) {
	data, err := s.store.Read(recordName)
	if errors.Is(err, os.ErrNotExist) {
		return 0, nil
	}
	if err != nil {
		return 0, fmt.Errorf("sequence: read record: %w", err)
	}
	if len(data) > 4*1024 {
		return 0, errors.New("sequence: record exceeds maximum size")
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var record diskRecord
	if err := decoder.Decode(&record); err != nil {
		return 0, errors.New("sequence: malformed record")
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) || record.Version != 1 {
		return 0, errors.New("sequence: malformed record")
	}
	return record.Last, nil
}
