// Package storage provides the owner-only local persistence boundary used by the agent.
package storage

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
)

var (
	ErrInvalidName         = errors.New("storage: invalid record name")
	ErrInsecurePermissions = errors.New("storage: record permissions are not owner-only")
)

// Store makes a platform keyring or another hardened store substitutable without
// changing identity code.
type Store interface {
	Read(name string) ([]byte, error)
	WriteAtomic(name string, data []byte) error
}

// FileStore persists records in one local state directory, restricted to its owner.
type FileStore struct{ root string }

func NewFileStore(root string) (*FileStore, error) {
	if root == "" || !filepath.IsAbs(root) {
		return nil, errors.New("storage: root must be an absolute path")
	}
	return &FileStore{root: filepath.Clean(root)}, nil
}

func (s *FileStore) Prepare() error { return s.ensureRoot() }

// Read returns a record only if it is a regular owner-only file.
func (s *FileStore) Read(name string) ([]byte, error) {
	path, err := s.recordPath(name)
	if err != nil {
		return nil, err
	}
	if err := s.ensureRoot(); err != nil {
		return nil, err
	}
	if err := validateExistingRecord(path); err != nil {
		return nil, err
	}
	return os.ReadFile(path)
}

// WriteAtomic writes an owner-only record through a same-directory atomic rename.
func (s *FileStore) WriteAtomic(name string, data []byte) (err error) {
	path, err := s.recordPath(name)
	if err != nil {
		return err
	}
	if err := s.ensureRoot(); err != nil {
		return err
	}
	if _, err := os.Lstat(path); err == nil {
		if err := validateExistingRecord(path); err != nil {
			return err
		}
	} else if !errors.Is(err, fs.ErrNotExist) {
		return err
	}
	temporary, err := os.CreateTemp(s.root, "."+name+".tmp-*")
	if err != nil {
		return err
	}
	temporaryPath := temporary.Name()
	committed := false
	defer func() {
		if !committed {
			_ = os.Remove(temporaryPath)
		}
	}()
	if err := temporary.Chmod(0o600); err != nil {
		_ = temporary.Close()
		return err
	}
	if _, err := temporary.Write(data); err != nil {
		_ = temporary.Close()
		return err
	}
	if err := temporary.Sync(); err != nil {
		_ = temporary.Close()
		return err
	}
	if err := temporary.Close(); err != nil {
		return err
	}
	if err := os.Rename(temporaryPath, path); err != nil {
		return err
	}
	if err := syncDirectory(s.root); err != nil {
		return err
	}
	committed = true
	return nil
}

func (s *FileStore) recordPath(name string) (string, error) {
	if name == "" || filepath.Base(name) != name || name == "." {
		return "", ErrInvalidName
	}
	return filepath.Join(s.root, name), nil
}

func (s *FileStore) ensureRoot() error {
	if err := os.MkdirAll(s.root, 0o700); err != nil {
		return err
	}
	info, err := os.Lstat(s.root)
	if err != nil {
		return err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return errors.New("storage: root is not a directory")
	}
	return os.Chmod(s.root, 0o700)
}

func validateExistingRecord(path string) error {
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if !info.Mode().IsRegular() {
		return fmt.Errorf("storage: record is not a regular file")
	}
	if info.Mode().Perm()&0o077 != 0 {
		return ErrInsecurePermissions
	}
	return nil
}

func syncDirectory(path string) error {
	directory, err := os.Open(path)
	if err != nil {
		return err
	}
	defer directory.Close()
	return directory.Sync()
}
