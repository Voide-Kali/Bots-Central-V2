package app

import (
	"context"
	"errors"
	"io"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/heartbeat"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/hostinfo"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/logging"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/transport"
)

type testIdentity struct {
	deviceID string
	err      error
}

func (i testIdentity) DeviceID() (string, error) { return i.deviceID, i.err }

type testCollector struct {
	status hostinfo.Status
	err    error
}

func (c testCollector) Collect() (hostinfo.Status, error) { return c.status, c.err }

func testConfig() Config {
	return Config{HeartbeatInterval: time.Second, TransportTimeout: time.Second, BackoffInitial: time.Millisecond, BackoffMax: 4 * time.Millisecond, AgentVersion: "test", CapabilityVersion: "test-v1"}
}
func testDependencies(fake *transport.Fake) Dependencies {
	return Dependencies{Collector: testCollector{status: hostinfo.Status{Hostname: "host", Platform: "linux/amd64"}}, Identity: testIdentity{deviceID: "device-1"}, Transport: fake, Logger: logging.New(io.Discard), Wait: func(context.Context, time.Duration) error { return nil }}
}

func TestRunnerReconnectsThenReturnsOnline(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	fake := &transport.Fake{Results: []error{errors.New("first failure"), errors.New("second failure"), nil}}
	var sent atomic.Int32
	fake.OnSend = func(heartbeat.Model) {
		if sent.Add(1) == 3 {
			cancel()
		}
	}
	dependencies := testDependencies(fake)
	var statesMu sync.Mutex
	var states []State
	dependencies.OnStateChange = func(state State) { statesMu.Lock(); states = append(states, state); statesMu.Unlock() }
	runner, err := New(testConfig(), dependencies)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	if err := runner.Run(ctx); err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if len(fake.Calls()) != 3 {
		t.Fatalf("transport calls = %d, want 3", len(fake.Calls()))
	}
	statesMu.Lock()
	defer statesMu.Unlock()
	if !containsState(states, StateBackingOff) || !containsState(states, StateOnline) {
		t.Fatalf("unexpected state sequence: %v", states)
	}
	if !fake.Closed() || runner.State() != StateStopped {
		t.Fatalf("runner did not stop gracefully: closed=%v state=%s", fake.Closed(), runner.State())
	}
}

func TestRunnerAppliesTransportTimeout(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	fake := &transport.Fake{BlockUntilContext: true}
	dependencies := testDependencies(fake)
	backoffReached := make(chan struct{})
	var once sync.Once
	dependencies.Wait = func(ctx context.Context, _ time.Duration) error {
		once.Do(func() { close(backoffReached) })
		<-ctx.Done()
		return ctx.Err()
	}
	config := testConfig()
	config.TransportTimeout = 10 * time.Millisecond
	runner, err := New(config, dependencies)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	result := make(chan error, 1)
	go func() { result <- runner.Run(ctx) }()
	select {
	case <-backoffReached:
	case <-time.After(time.Second):
		t.Fatal("runner did not reach reconnect backoff")
	}
	cancel()
	select {
	case err := <-result:
		if err != nil {
			t.Fatalf("Run() error = %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("runner did not stop")
	}
	if !fake.DeadlineSeen() {
		t.Fatal("transport did not receive a deadline")
	}
}

func TestRunnerCancelsAndClosesTransportGracefully(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	fake := &transport.Fake{BlockUntilContext: true}
	sent := make(chan struct{})
	fake.OnSend = func(heartbeat.Model) { close(sent) }
	runner, err := New(testConfig(), testDependencies(fake))
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	result := make(chan error, 1)
	go func() { result <- runner.Run(ctx) }()
	select {
	case <-sent:
	case <-time.After(time.Second):
		t.Fatal("runner did not start transport")
	}
	cancel()
	select {
	case err := <-result:
		if err != nil {
			t.Fatalf("Run() error = %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("runner did not stop")
	}
	if !fake.Closed() || runner.State() != StateStopped {
		t.Fatalf("graceful shutdown failed: closed=%v state=%s", fake.Closed(), runner.State())
	}
}

func containsState(states []State, want State) bool {
	for _, state := range states {
		if state == want {
			return true
		}
	}
	return false
}
