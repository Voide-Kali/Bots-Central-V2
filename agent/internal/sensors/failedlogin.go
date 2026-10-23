// Package sensors watches the computer for things worth telling its owner (ADR-019).
package sensors

import (
	"bufio"
	"context"
	"encoding/json"
	"io"
	"os/exec"
	"regexp"
	"strings"
	"sync"
	"time"
)

// Programs whose authentication failures count. Anything else is ignored.
var watchedPrograms = map[string]bool{
	"gdm-password": true, "gdm-autologin": true, "lightdm": true, "sddm": true,
	"gnome-screensaver": true, "xfce4-screensaver": true, "kscreenlocker": true,
	"cinnamon-screensaver": true, "login": true, "sudo": true, "su": true, "sshd": true,
	"polkit-agent-helper-1": true,
}

// What a failure looks like in PAM, login, su, sudo and sshd messages.
var failurePatterns = regexp.MustCompile(`(?i)(authentication failure|failed login|failed password|incorrect password attempt|failed su )`)

var programName = regexp.MustCompile(`^[a-z0-9][a-z0-9_.@-]{0,63}`)

// Throttle is the shortest gap between two reports (one photo a minute at most).
const Throttle = time.Minute

// FailedLogin returns the program name when a journal entry (journalctl -o json) is a
// wrong password in a watched program, or "" otherwise. Only the program name ever
// leaves the computer, never the journal text.
func FailedLogin(line []byte) string {
	var entry map[string]any
	if err := json.Unmarshal(line, &entry); err != nil {
		return ""
	}
	identifier, _ := entry["SYSLOG_IDENTIFIER"].(string)
	message := journalText(entry["MESSAGE"])
	program := programName.FindString(strings.ToLower(strings.TrimSpace(identifier)))
	if !watchedPrograms[program] || !failurePatterns.MatchString(message) {
		return ""
	}
	return program
}

// journalText handles MESSAGE as a string or, for non-UTF-8 entries, as a byte array.
func journalText(value any) string {
	switch typed := value.(type) {
	case string:
		return typed
	case []any:
		bytes := make([]byte, 0, len(typed))
		for _, item := range typed {
			if number, ok := item.(float64); ok && number >= 0 && number <= 255 {
				bytes = append(bytes, byte(number))
			}
		}
		return string(bytes)
	default:
		return ""
	}
}

// Report is called (in its own goroutine) with the program name of a wrong password.
type Report func(program string)

// Watcher reads journal lines and calls Report at most once per Throttle.
type Watcher struct {
	Report Report
	Now    func() time.Time

	mu   sync.Mutex
	last time.Time
}

// Feed handles one journal line; exported for tests.
func (w *Watcher) Feed(line []byte) bool {
	program := FailedLogin(line)
	if program == "" {
		return false
	}
	now := time.Now
	if w.Now != nil {
		now = w.Now
	}
	w.mu.Lock()
	if !w.last.IsZero() && now().Sub(w.last) < Throttle {
		w.mu.Unlock()
		return false
	}
	w.last = now()
	w.mu.Unlock()
	go w.Report(program)
	return true
}

// Scan feeds every line of a reader until it ends.
func (w *Watcher) Scan(reader io.Reader) {
	scanner := bufio.NewScanner(reader)
	scanner.Buffer(make([]byte, 64*1024), 1024*1024)
	for scanner.Scan() {
		w.Feed(scanner.Bytes())
	}
}

// Run follows the system journal (fixed program and arguments, no shell) until ctx ends,
// restarting journalctl if it stops.
func (w *Watcher) Run(ctx context.Context) {
	for ctx.Err() == nil {
		command := exec.CommandContext(ctx, "journalctl", "-f", "-n", "0", "-o", "json")
		stdout, err := command.StdoutPipe()
		if err == nil && command.Start() == nil {
			w.Scan(stdout)
			_ = command.Wait()
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(10 * time.Second):
		}
	}
}
