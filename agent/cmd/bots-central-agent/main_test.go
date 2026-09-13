package main

import (
	"errors"
	"strings"
	"testing"

	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/enrollment"
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
