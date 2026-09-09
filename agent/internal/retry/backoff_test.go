package retry

import (
	"testing"
	"time"
)

func TestBackoffCapsAndResets(t *testing.T) {
	backoff, err := New(time.Second, 5*time.Second)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	want := []time.Duration{time.Second, 2 * time.Second, 4 * time.Second, 5 * time.Second, 5 * time.Second}
	for index, expected := range want {
		if actual := backoff.Next(); actual != expected {
			t.Fatalf("attempt %d = %s, want %s", index, actual, expected)
		}
	}
	backoff.Reset()
	if actual := backoff.Next(); actual != time.Second {
		t.Fatalf("after reset = %s, want 1s", actual)
	}
}
