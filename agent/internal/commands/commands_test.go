package commands

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"testing"
)

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

	executor, err := NewExecutor(shared)
	if err != nil {
		t.Fatal(err)
	}
	result := executor.Execute(Command{Type: "send_file", FileName: "ok.txt"})
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
		if got := executor.Execute(Command{Type: "send_file", FileName: name}); got.OK || got.Error != want {
			t.Fatalf("%s: got %+v, want %s", name, got, want)
		}
	}
	if got := executor.Execute(Command{Type: "run_shell", FileName: "ok.txt"}); got.OK || got.Error != "disabled" {
		t.Fatalf("unknown type must be refused: %+v", got)
	}
	if _, err := NewExecutor("relative/path"); err == nil {
		t.Fatal("relative shared dir must be rejected")
	}
}
