package commands

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"
	"testing"
)

const testDevice = "11111111-1111-4111-8111-111111111111"

// approved builds a command exactly as the backend would after approval.
func approved(kind, argument string) Command {
	return Command{Type: kind, FileName: argument, DeviceID: testDevice, Digest: Digest(kind, testDevice, argument)}
}

func TestValidFileName(t *testing.T) {
	good := []string{"relatorio.pdf", "foto 01.jpg", "notas-2026.txt"}
	bad := []string{"", "../x", "a/b", `a\b`, ".ssh", " x", "x ", "..", "nul\x00", string(make([]byte, 256))}
	for _, name := range good {
		if !ValidFileName(name) {
			t.Fatalf("%q should be valid", name)
		}
	}
	for _, name := range bad {
		if ValidFileName(name) {
			t.Fatalf("%q should be invalid", name)
		}
	}
}

func TestExecuteReadsOnlyRegularFilesInsideSharedDir(t *testing.T) {
	root := t.TempDir()
	shared := filepath.Join(root, "shared")
	if err := os.Mkdir(shared, 0o700); err != nil {
		t.Fatal(err)
	}
	secret := filepath.Join(root, "secret.txt")
	if err := os.WriteFile(secret, []byte("segredo"), 0o600); err != nil {
		t.Fatal(err)
	}
	content := []byte("relatorio")
	if err := os.WriteFile(filepath.Join(shared, "ok.txt"), content, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(secret, filepath.Join(shared, "link.txt")); err != nil {
		t.Fatal(err)
	}
	if err := os.Link(secret, filepath.Join(shared, "hard.txt")); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(shared, "pasta"), 0o700); err != nil {
		t.Fatal(err)
	}
	big, err := os.Create(filepath.Join(shared, "big.bin"))
	if err != nil {
		t.Fatal(err)
	}
	if err := big.Truncate(MaxFileBytes + 1); err != nil {
		t.Fatal(err)
	}
	big.Close()

	executor, err := NewExecutor(shared, nil)
	if err != nil {
		t.Fatal(err)
	}
	result := executor.Execute(approved("send_file", "ok.txt"))
	sum := sha256.Sum256(content)
	if !result.OK || string(result.Content) != "relatorio" || result.SHA256 != hex.EncodeToString(sum[:]) {
		t.Fatalf("ok.txt result = %+v", result)
	}
	cases := map[string]string{
		"link.txt":      "not_regular",
		"hard.txt":      "not_regular",
		"pasta":         "not_regular",
		"big.bin":       "too_large",
		"missing.txt":   "not_found",
		"../secret.txt": "not_found",
	}
	for name, want := range cases {
		if got := executor.Execute(approved("send_file", name)); got.OK || got.Error != want {
			t.Fatalf("%s: got %+v, want %s", name, got, want)
		}
	}
	if got := executor.Execute(approved("run_shell", "ok.txt")); got.OK || got.Error != "disabled" {
		t.Fatalf("unknown type must be refused: %+v", got)
	}
	if _, err := NewExecutor("relative/path", nil); err == nil {
		t.Fatal("relative shared dir must be rejected")
	}
}

type fakeSystem struct {
	locked  int
	photo   []byte
	scanRaw []byte
	scanned int
	err     error
}

func (f *fakeSystem) LockScreen(context.Context) error {
	f.locked++
	return f.err
}

func (f *fakeSystem) TakePhoto(_ context.Context, path string) error {
	if f.err != nil {
		return f.err
	}
	return os.WriteFile(path, f.photo, 0o600)
}

func (f *fakeSystem) NetworkScan(context.Context) ([]byte, error) {
	f.scanned++
	if f.err != nil {
		return nil, f.err
	}
	return f.scanRaw, nil
}

func TestDigestMismatchIsRefusedBeforeAnything(t *testing.T) {
	system := &fakeSystem{}
	executor, err := NewExecutor("", []string{"lock_screen"})
	if err != nil {
		t.Fatal(err)
	}
	executor.system = system
	tampered := approved("lock_screen", "")
	tampered.Type = "webcam_photo" // a compromised channel swaps the action
	if got := executor.Execute(tampered); got.OK || got.Error != "digest" {
		t.Fatalf("swapped action: %+v", got)
	}
	other := approved("lock_screen", "")
	other.DeviceID = "22222222-2222-4222-8222-222222222222" // approved for another computer
	if got := executor.Execute(other); got.OK || got.Error != "digest" {
		t.Fatalf("other device: %+v", got)
	}
	if got := executor.Execute(approved("lock_screen", "x")); got.OK || got.Error != "digest" {
		t.Fatalf("lock_screen takes no argument: %+v", got)
	}
	if system.locked != 0 {
		t.Fatal("nothing may run when the digest does not match")
	}
}

func TestActionsRunOnlyWhenAllowed(t *testing.T) {
	system := &fakeSystem{photo: []byte("\xff\xd8jpeg")}
	executor, err := NewExecutor("", []string{"lock_screen"})
	if err != nil {
		t.Fatal(err)
	}
	executor.system = system
	if got := executor.Execute(approved("lock_screen", "")); !got.OK || len(got.Content) != 0 || system.locked != 1 {
		t.Fatalf("lock: %+v", got)
	}
	if got := executor.Execute(approved("webcam_photo", "")); got.OK || got.Error != "disabled" {
		t.Fatalf("photo not allowed: %+v", got)
	}
	if got := executor.Execute(approved("send_file", "a.txt")); got.OK || got.Error != "disabled" {
		t.Fatalf("no shared folder: %+v", got)
	}
	executor.allowed["webcam_photo"] = true
	got := executor.Execute(approved("webcam_photo", ""))
	sum := sha256.Sum256(system.photo)
	if !got.OK || string(got.Content) != string(system.photo) || got.SHA256 != hex.EncodeToString(sum[:]) {
		t.Fatalf("photo: %+v", got)
	}
	system.err = errUnsupported
	if got := executor.Execute(approved("lock_screen", "")); got.OK || got.Error != "unsupported" {
		t.Fatalf("unsupported: %+v", got)
	}
	system.err = errors.New("boom")
	if got := executor.Execute(approved("webcam_photo", "")); got.OK || got.Error != "failed" {
		t.Fatalf("failed: %+v", got)
	}
}

func TestExecutorConfiguration(t *testing.T) {
	if _, err := NewExecutor("", nil); err == nil {
		t.Fatal("nothing enabled must be rejected")
	}
	if _, err := NewExecutor("", []string{"run_shell"}); err == nil {
		t.Fatal("unknown action must be rejected")
	}
}

func TestDigestMatchesBackendFormat(t *testing.T) {
	// Same vector as backend tests/test_device_actions.py.
	got := Digest("lock_screen", testDevice, "")
	sum := sha256.Sum256([]byte("aval-action-v1\nlock_screen\n" + testDevice + "\n"))
	if got != hex.EncodeToString(sum[:]) {
		t.Fatal("digest format changed")
	}
}
