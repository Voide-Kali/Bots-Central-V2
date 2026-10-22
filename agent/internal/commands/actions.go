package commands

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"time"
)

// MaxPhotoBytes bounds the webcam picture sent back.
const MaxPhotoBytes = 5 * 1024 * 1024

const actionTimeout = 20 * time.Second

// errUnsupported marks a platform without a supported way to do the action.
var errUnsupported = errors.New("unsupported")

// System runs the fixed programs behind each action. Tests replace it.
type System interface {
	LockScreen(ctx context.Context) error
	TakePhoto(ctx context.Context, path string) error
}

func (e *Executor) lockScreen() Result {
	ctx, cancel := context.WithTimeout(context.Background(), actionTimeout)
	defer cancel()
	if err := e.system.LockScreen(ctx); err != nil {
		return Result{Error: failure(err)}
	}
	return okEmpty()
}

func (e *Executor) webcamPhoto() Result {
	dir, err := os.MkdirTemp("", "aval-photo-")
	if err != nil {
		return Result{Error: "failed"}
	}
	defer os.RemoveAll(dir)
	path := filepath.Join(dir, "photo.jpg")
	ctx, cancel := context.WithTimeout(context.Background(), actionTimeout)
	defer cancel()
	if err := e.system.TakePhoto(ctx, path); err != nil {
		return Result{Error: failure(err)}
	}
	file, err := os.Open(path)
	if err != nil {
		return Result{Error: "failed"}
	}
	defer file.Close()
	content, err := io.ReadAll(io.LimitReader(file, MaxPhotoBytes+1))
	if err != nil || len(content) == 0 {
		return Result{Error: "failed"}
	}
	if len(content) > MaxPhotoBytes {
		return Result{Error: "too_large"}
	}
	sum := sha256.Sum256(content)
	return Result{OK: true, Content: content, SHA256: hex.EncodeToString(sum[:])}
}

func okEmpty() Result {
	sum := sha256.Sum256(nil)
	return Result{OK: true, Content: []byte{}, SHA256: hex.EncodeToString(sum[:])}
}

func failure(err error) string {
	if errors.Is(err, errUnsupported) || errors.Is(err, exec.ErrNotFound) {
		return "unsupported"
	}
	return "failed"
}

// hostSystem calls fixed programs with fixed arguments (no shell).
type hostSystem struct{}

func (hostSystem) LockScreen(ctx context.Context) error {
	switch runtime.GOOS {
	case "linux":
		return run(ctx, "loginctl", "lock-sessions")
	case "darwin":
		return run(ctx, "/usr/bin/pmset", "displaysleepnow")
	default:
		return errUnsupported
	}
}

func (hostSystem) TakePhoto(ctx context.Context, path string) error {
	switch runtime.GOOS {
	case "linux":
		return run(ctx, "fswebcam", "-q", "--no-banner", "-r", "1280x720", "--jpeg", "85", path)
	case "darwin":
		// LaunchAgents get a minimal PATH; Homebrew lives outside it.
		return run(ctx, firstExisting("/opt/homebrew/bin/imagesnap", "/usr/local/bin/imagesnap", "imagesnap"), "-q", "-w", "1", path)
	default:
		return errUnsupported
	}
}

func run(ctx context.Context, name string, args ...string) error {
	path, err := exec.LookPath(name)
	if err != nil {
		return err
	}
	command := exec.CommandContext(ctx, path, args...)
	command.Stdin, command.Stdout, command.Stderr = nil, io.Discard, io.Discard
	return command.Run()
}

func firstExisting(candidates ...string) string {
	for _, candidate := range candidates[:len(candidates)-1] {
		if info, err := os.Stat(candidate); err == nil && info.Mode().IsRegular() {
			return candidate
		}
	}
	return candidates[len(candidates)-1]
}

// CapturePhoto takes one webcam picture for the wrong-password sensor (ADR-019), with the
// same fixed programs and size limit as the approved webcam_photo action.
func CapturePhoto() ([]byte, error) {
	executor := &Executor{system: hostSystem{}}
	result := executor.webcamPhoto()
	if !result.OK {
		return nil, errors.New("commands: photo failed: " + result.Error)
	}
	return result.Content, nil
}
