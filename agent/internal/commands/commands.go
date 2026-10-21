// Package commands executes the few typed, human-approved actions the backend
// may hand to the agent (ADR-015). v0.1 supports only "send_file": read one
// regular file, by bare name, from the configured shared folder. There is no
// shell, no path traversal and no access outside that folder.
package commands

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"unicode"
)

// MaxFileBytes mirrors the backend limit.
const MaxFileBytes = 10 * 1024 * 1024

// Command is what the backend dispatches after the owner approved it.
type Command struct {
	ID       string `json:"id"`
	Type     string `json:"type"`
	FileName string `json:"file_name"`
}

// Result is reported back with a signed size and SHA-256.
type Result struct {
	OK      bool
	Error   string
	Content []byte
	SHA256  string
}

// Executor runs commands inside one shared folder.
type Executor struct {
	sharedDir string
}

func NewExecutor(sharedDir string) (*Executor, error) {
	if sharedDir == "" || !filepath.IsAbs(sharedDir) {
		return nil, errors.New("commands: shared_dir must be an absolute path")
	}
	return &Executor{sharedDir: filepath.Clean(sharedDir)}, nil
}

// ValidFileName accepts a bare file name only (same rules as the backend).
func ValidFileName(name string) bool {
	if len(name) == 0 || len(name) > 255 || name != strings.TrimSpace(name) || strings.HasPrefix(name, ".") {
		return false
	}
	for _, r := range name {
		if r == '/' || r == '\\' || r == 0 || !unicode.IsPrint(r) {
			return false
		}
	}
	return filepath.Base(name) == name
}

func (e *Executor) Execute(command Command) Result {
	if command.Type != "send_file" {
		return Result{Error: "disabled"}
	}
	if !ValidFileName(command.FileName) {
		return Result{Error: "not_found"}
	}
	path := filepath.Join(e.sharedDir, command.FileName)
	if filepath.Dir(path) != e.sharedDir {
		return Result{Error: "not_found"}
	}
	info, err := os.Lstat(path)
	if err != nil {
		return Result{Error: "not_found"}
	}
	if !info.Mode().IsRegular() { // rejects symlinks, folders, devices, sockets
		return Result{Error: "not_regular"}
	}
	if info.Size() > MaxFileBytes {
		return Result{Error: "too_large"}
	}
	file, err := openNoFollow(path)
	if err != nil {
		return Result{Error: "read_error"}
	}
	defer file.Close()
	opened, err := file.Stat()
	if err != nil || !opened.Mode().IsRegular() || !os.SameFile(info, opened) {
		return Result{Error: "not_regular"}
	}
	content, err := io.ReadAll(io.LimitReader(file, MaxFileBytes+1))
	if err != nil {
		return Result{Error: "read_error"}
	}
	if len(content) > MaxFileBytes {
		return Result{Error: "too_large"}
	}
	sum := sha256.Sum256(content)
	return Result{OK: true, Content: content, SHA256: hex.EncodeToString(sum[:])}
}
