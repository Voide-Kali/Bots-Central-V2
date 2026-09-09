package identity

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/storage"
)

func TestIdentityPersistsWithOwnerOnlyPermissions(t *testing.T) {
	root := t.TempDir()
	store, err := storage.NewFileStore(root)
	if err != nil {
		t.Fatalf("NewFileStore() error = %v", err)
	}
	first, err := LoadOrCreate(store)
	if err != nil {
		t.Fatalf("LoadOrCreate() error = %v", err)
	}
	recordPath := filepath.Join(root, recordName)
	info, err := os.Stat(recordPath)
	if err != nil {
		t.Fatalf("Stat() error = %v", err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("identity mode = %o, want 600", info.Mode().Perm())
	}
	second, err := LoadOrCreate(store)
	if err != nil {
		t.Fatalf("second LoadOrCreate() error = %v", err)
	}
	if !bytes.Equal(first.PublicKey(), second.PublicKey()) {
		t.Fatal("identity keypair was not persisted")
	}
	if err := os.Chmod(recordPath, 0o644); err != nil {
		t.Fatalf("Chmod() error = %v", err)
	}
	if _, err := LoadOrCreate(store); !errors.Is(err, storage.ErrInsecurePermissions) {
		t.Fatalf("insecure record error = %v", err)
	}
}
