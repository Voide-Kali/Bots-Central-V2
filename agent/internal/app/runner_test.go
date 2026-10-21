package app

import (
	"context"
	"errors"
	"io"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/enrollment"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/heartbeat"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/hostinfo"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/logging"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/storage"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/telemetry"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/transport"
)

type testEnrollment struct {
	mu        sync.Mutex
	record    enrollment.Record
	err       error
	activated bool
	stateLost bool
	revoked   bool
}

func (s *testEnrollment) Load() (enrollment.Record, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.record, s.err
}
func (s *testEnrollment) MarkActive() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.record.Status != enrollment.StatusPending {
		return errors.New("not pending")
	}
	s.record.Status = enrollment.StatusActive
	s.activated = true
	return nil
}
func (s *testEnrollment) MarkStateLost() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.stateLost = true
	return nil
}
func (s *testEnrollment) MarkRevoked() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.revoked = true
	return nil
}
func (s *testEnrollment) StateLost() bool { s.mu.Lock(); defer s.mu.Unlock(); return s.stateLost }
func (s *testEnrollment) Revoked() bool   { s.mu.Lock(); defer s.mu.Unlock(); return s.revoked }
func (s *testEnrollment) Activated() bool { s.mu.Lock(); defer s.mu.Unlock(); return s.activated }

type testCollector struct {
	status hostinfo.Status
	err    error
}

func (c testCollector) Collect() (hostinfo.Status, error) { return c.status, c.err }

func testConfig() Config {
	return Config{HeartbeatInterval: RequiredHeartbeatInterval, TransportTimeout: time.Second, BackoffInitial: time.Millisecond, BackoffMax: 4 * time.Millisecond, AgentVersion: "test", CapabilityVersion: "test-v1"}
}

func testDependencies(fake *transport.Fake, state *testEnrollment) Dependencies {
	return Dependencies{Collector: testCollector{status: hostinfo.Status{Hostname: "host", Platform: "linux/amd64"}}, Enrollment: state, Transport: fake, Logger: logging.New(io.Discard), Wait: func(context.Context, time.Duration) error { return nil }, Jitter: func() time.Duration { return 0 }}
}

func TestRunnerReconnectsThenReturnsOnline(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	fake := &transport.Fake{Results: []error{errors.New("first failure"), errors.New("second failure"), nil}}
	state := &testEnrollment{record: enrollment.Record{DeviceID: "device-1", Status: enrollment.StatusActive}}
	var sent atomic.Int32
	fake.OnSend = func(heartbeat.Model) {
		if sent.Add(1) == 3 {
			cancel()
		}
	}
	dependencies := testDependencies(fake, state)
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

func TestRunnerPendingProbeActivatesOnFirstAcceptedHeartbeat(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	fake := &transport.Fake{Results: []error{transport.ErrDevicePending, nil}}
	state := &testEnrollment{record: enrollment.Record{DeviceID: "device-1", Status: enrollment.StatusPending}}
	dependencies := testDependencies(fake, state)
	var waits []time.Duration
	dependencies.Wait = func(_ context.Context, duration time.Duration) error {
		waits = append(waits, duration)
		return nil
	}
	fake.OnSend = func(_ heartbeat.Model) {
		if len(fake.Calls()) == 2 {
			cancel()
		}
	}
	runner, err := New(testConfig(), dependencies)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	if err := runner.Run(ctx); err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if calls := fake.Calls(); len(calls) != 2 || !state.Activated() {
		t.Fatalf("pending probes/activation = %d, %v", len(calls), state.Activated())
	}
	if len(waits) == 0 || waits[0] != RequiredHeartbeatInterval {
		t.Fatalf("pending waits = %v", waits)
	}
}

func TestRunnerPendingAcceptancePersistsActiveAcrossRestart(t *testing.T) {
	fileStore, err := storage.NewFileStore(t.TempDir())
	if err != nil {
		t.Fatalf("NewFileStore() error = %v", err)
	}
	state, err := enrollment.New(fileStore)
	if err != nil {
		t.Fatalf("enrollment.New() error = %v", err)
	}
	if err := state.SaveEnrollment(enrollment.Record{DeviceID: "device-1", Status: enrollment.StatusPending}); err != nil {
		t.Fatalf("SaveEnrollment() error = %v", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	fake := &transport.Fake{Results: []error{nil}}
	fake.OnSend = func(_ heartbeat.Model) { cancel() }
	runner, err := New(testConfig(), Dependencies{Collector: testCollector{status: hostinfo.Status{Hostname: "host", Platform: "linux/amd64"}}, Enrollment: state, Transport: fake, Logger: logging.New(io.Discard), Wait: func(context.Context, time.Duration) error { return nil }, Jitter: func() time.Duration { return 0 }})
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	if err := runner.Run(ctx); err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	restarted, err := enrollment.New(fileStore)
	if err != nil {
		t.Fatalf("restart enrollment.New() error = %v", err)
	}
	record, err := restarted.Load()
	if err != nil || record.Status != enrollment.StatusActive {
		t.Fatalf("restarted Load() = %#v, %v", record, err)
	}
}

func TestRunnerStaleSequencePersistsStateLossAndStops(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	fake := &transport.Fake{Results: []error{transport.ErrStaleSequence}}
	state := &testEnrollment{record: enrollment.Record{DeviceID: "device-1", Status: enrollment.StatusActive}}
	dependencies := testDependencies(fake, state)
	dependencies.OnStateChange = func(next State) {
		if next == StateStateLost {
			cancel()
		}
	}
	runner, err := New(testConfig(), dependencies)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	if err := runner.Run(ctx); err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if !state.StateLost() || len(fake.Calls()) != 1 {
		t.Fatalf("stale sequence was retried or not persisted: stateLost=%v calls=%d", state.StateLost(), len(fake.Calls()))
	}
}

func TestRunnerRevocationPersistsAndStops(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	fake := &transport.Fake{Results: []error{transport.ErrDeviceRevoked}}
	state := &testEnrollment{record: enrollment.Record{DeviceID: "device-1", Status: enrollment.StatusActive}}
	dependencies := testDependencies(fake, state)
	dependencies.OnStateChange = func(next State) {
		if next == StateRevoked {
			cancel()
		}
	}
	runner, err := New(testConfig(), dependencies)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	if err := runner.Run(ctx); err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if !state.Revoked() || len(fake.Calls()) != 1 {
		t.Fatalf("revocation was retried or not persisted: revoked=%v calls=%d", state.Revoked(), len(fake.Calls()))
	}
}

func TestRunnerHonorsRetryAfter(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	fake := &transport.Fake{Results: []error{&transport.RetryAfterError{Delay: 7 * time.Second, Valid: true}, nil}}
	state := &testEnrollment{record: enrollment.Record{DeviceID: "device-1", Status: enrollment.StatusActive}}
	dependencies := testDependencies(fake, state)
	var waits []time.Duration
	dependencies.Wait = func(_ context.Context, duration time.Duration) error {
		waits = append(waits, duration)
		return nil
	}
	fake.OnSend = func(_ heartbeat.Model) {
		if len(fake.Calls()) == 2 {
			cancel()
		}
	}
	runner, err := New(testConfig(), dependencies)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	if err := runner.Run(ctx); err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if len(waits) == 0 || waits[0] != 7*time.Second {
		t.Fatalf("waits = %v, want Retry-After first", waits)
	}
}

func TestRunnerHonorsZeroRetryAfter(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	fake := &transport.Fake{Results: []error{&transport.RetryAfterError{Delay: 0, Valid: true}, nil}}
	state := &testEnrollment{record: enrollment.Record{DeviceID: "device-1", Status: enrollment.StatusActive}}
	dependencies := testDependencies(fake, state)
	var waits []time.Duration
	dependencies.Wait = func(_ context.Context, duration time.Duration) error {
		waits = append(waits, duration)
		return nil
	}
	fake.OnSend = func(_ heartbeat.Model) {
		if len(fake.Calls()) == 2 {
			cancel()
		}
	}
	runner, err := New(testConfig(), dependencies)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	if err := runner.Run(ctx); err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if len(waits) == 0 || waits[0] != 0 {
		t.Fatalf("waits = %v, want zero Retry-After first", waits)
	}
}

func TestRunnerUsesBoundedBackoffForTemporaryFailures(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	fake := &transport.Fake{Results: []error{&transport.TemporaryError{Status: 503}, &transport.TemporaryError{Status: 503}, nil}}
	state := &testEnrollment{record: enrollment.Record{DeviceID: "device-1", Status: enrollment.StatusActive}}
	dependencies := testDependencies(fake, state)
	var waits []time.Duration
	dependencies.Wait = func(_ context.Context, duration time.Duration) error {
		waits = append(waits, duration)
		return nil
	}
	fake.OnSend = func(_ heartbeat.Model) {
		if len(fake.Calls()) == 3 {
			cancel()
		}
	}
	runner, err := New(testConfig(), dependencies)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	if err := runner.Run(ctx); err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if len(waits) < 2 || waits[0] != time.Millisecond || waits[1] != 2*time.Millisecond {
		t.Fatalf("waits = %v, want bounded backoff", waits)
	}
}

func TestHeartbeatJitterIsBounded(t *testing.T) {
	state := &testEnrollment{record: enrollment.Record{DeviceID: "device-1", Status: enrollment.StatusActive}}
	runner, err := New(testConfig(), Dependencies{Collector: testCollector{status: hostinfo.Status{Hostname: "host", Platform: "linux/amd64"}}, Enrollment: state, Transport: &transport.Fake{}, Logger: logging.New(io.Discard), Jitter: func() time.Duration { return 99 * time.Second }})
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	if delay := runner.heartbeatDelay(); delay != 35*time.Second {
		t.Fatalf("positive jitter delay = %s, want 35s", delay)
	}
	runner.jitter = func() time.Duration { return -99 * time.Second }
	if delay := runner.heartbeatDelay(); delay != 25*time.Second {
		t.Fatalf("negative jitter delay = %s, want 25s", delay)
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

type testTelemetry struct{ calls atomic.Int32 }

func (c *testTelemetry) Collect() telemetry.Sample {
	c.calls.Add(1)
	cpus := 4
	return telemetry.Sample{V: telemetry.Version, CPUs: &cpus}
}

func TestRunnerAttachesTelemetryOnlyAfterActivation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	fake := &transport.Fake{Results: []error{transport.ErrDevicePending, nil, nil}}
	state := &testEnrollment{record: enrollment.Record{DeviceID: "device-1", Status: enrollment.StatusPending}}
	dependencies := testDependencies(fake, state)
	collector := &testTelemetry{}
	dependencies.Telemetry = collector
	fake.OnSend = func(_ heartbeat.Model) {
		if len(fake.Calls()) == 3 {
			cancel()
		}
	}
	runner, err := New(testConfig(), dependencies)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	if err := runner.Run(ctx); err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	calls := fake.Calls()
	if len(calls) != 3 {
		t.Fatalf("calls = %d", len(calls))
	}
	if calls[0].Telemetry != nil || calls[1].Telemetry != nil {
		t.Fatal("pending probes must not carry telemetry")
	}
	if calls[2].Telemetry == nil || calls[2].Telemetry.CPUs == nil || *calls[2].Telemetry.CPUs != 4 {
		t.Fatalf("active heartbeat telemetry = %#v", calls[2].Telemetry)
	}
	if collector.calls.Load() != 1 {
		t.Fatalf("collector calls = %d", collector.calls.Load())
	}
}
