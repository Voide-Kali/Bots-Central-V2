// Package commands executes the few typed, human-approved actions the backend
// may hand to the agent (ADR-015, ADR-016):
//
//   - send_file: read one regular file, by bare name, from the shared folder;
//   - lock_screen, webcam_photo: run one fixed program with fixed arguments,
//     only if listed in allowed_actions.
//
// Every command carries a digest of exactly what the owner approved; the agent
// recomputes it and refuses on mismatch. There is no shell and no free text.
package commands

import (
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"unicode"
)

// DigestPrefix must match the backend (app.devices.commands.DIGEST_PREFIX).
const DigestPrefix = "aval-action-v1"

// Actions that need explicit opt-in through allowed_actions.
var KnownActions = map[string]bool{"lock_screen": true, "webcam_photo": true, "network_scan": true}

// MaxFileBytes mirrors the backend limit.
const MaxFileBytes = 10 * 1024 * 1024

// Command is what the backend dispatches after the owner approved it.
type Command struct {
	ID       string `json:"id"`
	Type     string `json:"type"`
	FileName string `json:"file_name"`
	Digest   string `json:"digest"`
	// DeviceID is set by the transport (never read from the response).
	DeviceID string `json:"-"`
}

// Digest recomputes the canonical approval digest for this command.
func Digest(kind, deviceID, argument string) string {
	sum := sha256.Sum256([]byte(DigestPrefix + "\n" + kind + "\n" + deviceID + "\n" + argument))
	return hex.EncodeToString(sum[:])
}

// Result is reported back with a signed size and SHA-256.
type Result struct {
	OK      bool
	Error   string
	Content []byte
	SHA256  string
}

// Executor runs approved commands: files from one shared folder and the
// actions the owner enabled on this computer.
type Executor struct {
	sharedDir string
	allowed   map[string]bool
	system    System
}

// NewExecutor needs at least a shared folder or one allowed action.
func NewExecutor(sharedDir string, allowedActions []string) (*Executor, error) {
	if sharedDir != "" && !filepath.IsAbs(sharedDir) {
		return nil, errors.New("commands: shared_dir must be an absolute path")
	}
	allowed := map[string]bool{}
	for _, action := range allowedActions {
		if !KnownActions[action] {
			return nil, errors.New("commands: unknown action in allowed_actions: " + action)
		}
		allowed[action] = true
	}
	if sharedDir == "" && len(allowed) == 0 {
		return nil, errors.New("commands: nothing enabled")
	}
	if sharedDir != "" {
		sharedDir = filepath.Clean(sharedDir)
	}
	return &Executor{sharedDir: sharedDir, allowed: allowed, system: hostSystem{}}, nil
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
	expected := Digest(command.Type, command.DeviceID, command.FileName)
	if len(command.Digest) != len(expected) || subtle.ConstantTimeCompare([]byte(command.Digest), []byte(expected)) != 1 {
		return Result{Error: "digest"}
	}
	switch command.Type {
	case "send_file":
		return e.sendFile(command)
	case "lock_screen", "webcam_photo":
		if command.FileName != "" {
			return Result{Error: "digest"}
		}
		if !e.allowed[command.Type] {
			return Result{Error: "disabled"}
		}
		if command.Type == "lock_screen" {
			return e.lockScreen()
		}
		return e.webcamPhoto()
	case "network_scan":
		if command.FileName != "" {
			return Result{Error: "digest"}
		}
		if !e.allowed[command.Type] {
			return Result{Error: "disabled"}
		}
		return e.networkScan()
	default:
		return Result{Error: "disabled"}
	}
}

func (e *Executor) sendFile(command Command) Result {
	if e.sharedDir == "" {
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
	if linkCount(info) > 1 { // a hard link could point at a file outside the folder
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
