package logging

import (
	"bytes"
	"errors"
	"strings"
	"testing"
)

func TestLoggerNeverEmitsCredentialValues(t *testing.T) {
	const token = "super-secret-device-token"
	const password = "private-key-material"
	var output bytes.Buffer
	logger := New(&output)
	logger.Info("transport diagnostic", Field{Key: "authorization", Value: "Bearer " + token}, Field{Key: "endpoint", Value: "https://alice:" + password + "@backend.example/heartbeat?token=" + token}, Field{Key: "metadata", Value: map[string]any{"api_key": token}})
	logger.Warn("transport failure", ErrorField(errors.New("password="+password)))
	logged := output.String()
	for _, secret := range []string{token, password} {
		if strings.Contains(logged, secret) {
			t.Fatalf("log leaked secret %q: %s", secret, logged)
		}
	}
	if !strings.Contains(logged, Redacted) {
		t.Fatalf("expected redaction marker in %s", logged)
	}
}
