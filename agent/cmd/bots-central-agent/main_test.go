package main

import (
	"bytes"
	"errors"
	"io"
	"os"
	"strings"
	"testing"

	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/enrollment"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/logging"
)

func TestReadPairingToken(t *testing.T) {
	token, err := readPairingToken(strings.NewReader("one-time-token\r\n"))
	if err != nil {
		t.Fatalf("readPairingToken() error = %v", err)
	}
	if token != "one-time-token" {
		t.Fatalf("token = %q", token)
	}
}

func TestReadPairingTokenRejectsEmptyAndOversizedInput(t *testing.T) {
	for _, input := range []string{"\n", strings.Repeat("x", maxPairingTokenSize+1)} {
		if _, err := readPairingToken(strings.NewReader(input)); err == nil {
			t.Fatalf("readPairingToken(%d bytes) succeeded", len(input))
		}
	}
}

func TestReadPairingTokenReadsOneInteractiveLineWithoutEOF(t *testing.T) {
	reader, writer, err := os.Pipe()
	if err != nil {
		t.Fatalf("os.Pipe() error = %v", err)
	}
	defer reader.Close()
	defer writer.Close()
	if _, err := io.WriteString(writer, "token-from-terminal\ntrailing-input"); err != nil {
		t.Fatalf("write pairing input: %v", err)
	}
	token, err := readPairingToken(reader)
	if err != nil {
		t.Fatalf("readPairingToken() error = %v", err)
	}
	if token != "token-from-terminal" {
		t.Fatalf("token = %q", token)
	}
}

func TestReadPairingTokenDoesNotLeakInputInErrors(t *testing.T) {
	secret := "must-not-appear-in-an-error"
	_, err := readPairingToken(strings.NewReader(strings.Repeat(secret, maxPairingTokenSize)))
	if err == nil {
		t.Fatal("oversized input succeeded")
	}
	if strings.Contains(err.Error(), secret) {
		t.Fatalf("error leaked pairing token: %v", err)
	}
	var output bytes.Buffer
	logging.New(&output).Error("agent startup failed", logging.ErrorField(err))
	if strings.Contains(output.String(), secret) {
		t.Fatalf("log leaked pairing token: %s", output.String())
	}
}

func TestPairingAllowedOnlyBeforeEnrollmentOrAfterStateLoss(t *testing.T) {
	if !pairingAllowed(enrollment.Record{}, enrollment.ErrNotEnrolled) {
		t.Fatal("unpaired agent must allow pairing")
	}
	if !pairingAllowed(enrollment.Record{Status: enrollment.StatusStateLost}, nil) {
		t.Fatal("state-lost agent must allow explicit re-pairing")
	}
	for _, status := range []enrollment.Status{enrollment.StatusPending, enrollment.StatusActive, enrollment.StatusRevoked} {
		if pairingAllowed(enrollment.Record{Status: status}, nil) {
			t.Fatalf("status %q unexpectedly allows pairing", status)
		}
	}
	if pairingAllowed(enrollment.Record{}, errors.New("corrupt state")) {
		t.Fatal("corrupt local state must fail closed")
	}
}
