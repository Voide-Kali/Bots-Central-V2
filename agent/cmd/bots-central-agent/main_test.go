package main

import (
	"strings"
	"testing"
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
