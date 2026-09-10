// Package app coordinates local enrollment state, heartbeat delivery, and shutdown.
package app

import (
	"context"
	"errors"
	"fmt"
	"math/rand"
	"sync"
	"time"

	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/enrollment"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/heartbeat"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/hostinfo"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/logging"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/retry"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/transport"
)

const (
	DefaultCapabilityVersion  = "mvp1-heartbeat-model-v1"
	RequiredHeartbeatInterval = 30 * time.Second
	maxHeartbeatJitter        = 5 * time.Second
)

// State describes the runtime reconnect state machine.
type State string

const (
	StateStarting             State = "starting"
	StateWaitingForEnrollment State = "waiting_for_enrollment"
	StatePending              State = "pending"
	StateCollecting           State = "collecting"
	StateConnecting           State = "connecting"
	StateOnline               State = "online"
	StateRateLimited          State = "rate_limited"
	StateBackingOff           State = "backing_off"
	StateStateLost            State = "state_lost"
	StateRevoked              State = "revoked"
	StateBlocked              State = "blocked"
	StateStopping             State = "stopping"
	StateStopped              State = "stopped"
)

// Config controls the local heartbeat runtime.
type Config struct {
	HeartbeatInterval time.Duration
	TransportTimeout  time.Duration
	BackoffInitial    time.Duration
	BackoffMax        time.Duration
	AgentVersion      string
	CapabilityVersion string
}

type HostCollector interface {
	Collect() (hostinfo.Status, error)
}

// EnrollmentState is deliberately narrow: only an accepted signed heartbeat
// probe may promote PENDING, and terminal server responses become durable locally.
type EnrollmentState interface {
	Load() (enrollment.Record, error)
	MarkActive() error
	MarkStateLost() error
	MarkRevoked() error
}

type waitFunc func(context.Context, time.Duration) error

// Dependencies make side effects explicit and enable deterministic tests.
type Dependencies struct {
	Collector     HostCollector
	Enrollment    EnrollmentState
	Transport     transport.HeartbeatTransport
	Logger        *logging.Logger
	Now           func() time.Time
	Wait          waitFunc
	Jitter        func() time.Duration
	OnStateChange func(State)
}

// Runner sends a heartbeat immediately for a persisted PENDING or ACTIVE device,
// then every 30 seconds with bounded ±5 second jitter. PENDING probes are signed
// and sequenced but do not establish presence until the backend accepts one.
type Runner struct {
	config     Config
	collector  HostCollector
	enrollment EnrollmentState
	transport  transport.HeartbeatTransport
	logger     *logging.Logger
	now        func() time.Time
	wait       waitFunc
	jitter     func() time.Duration
	onState    func(State)
	mu         sync.RWMutex
	state      State
}

func New(config Config, dependencies Dependencies) (*Runner, error) {
	if err := validateConfig(config); err != nil {
		return nil, err
	}
	if dependencies.Collector == nil || dependencies.Enrollment == nil || dependencies.Transport == nil || dependencies.Logger == nil {
		return nil, errors.New("app: collector, enrollment, transport, and logger are required")
	}
	if dependencies.Now == nil {
		dependencies.Now = time.Now
	}
	if dependencies.Wait == nil {
		dependencies.Wait = waitFor
	}
	if dependencies.Jitter == nil {
		dependencies.Jitter = defaultJitter
	}
	return &Runner{config: config, collector: dependencies.Collector, enrollment: dependencies.Enrollment, transport: dependencies.Transport, logger: dependencies.Logger, now: dependencies.Now, wait: dependencies.Wait, jitter: dependencies.Jitter, onState: dependencies.OnStateChange, state: StateStarting}, nil
}

func validateConfig(config Config) error {
	if config.HeartbeatInterval != RequiredHeartbeatInterval || config.TransportTimeout <= 0 || config.BackoffInitial <= 0 || config.BackoffMax < config.BackoffInitial || config.AgentVersion == "" || config.CapabilityVersion == "" {
		return errors.New("app: invalid runtime configuration")
	}
	return nil
}

func (r *Runner) State() State {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.state
}

// Run blocks until cancellation. Terminal security states remain idle rather
// than retrying; their persisted state prevents a restart from resuming traffic.
func (r *Runner) Run(ctx context.Context) (runErr error) {
	if ctx == nil {
		return errors.New("app: context is required")
	}
	defer func() {
		r.setState(StateStopping)
		if closeErr := r.transport.Close(); closeErr != nil && runErr == nil {
			runErr = fmt.Errorf("app: close transport: %w", closeErr)
		}
		r.setState(StateStopped)
	}()
	r.setState(StateStarting)
	record, err := r.enrollment.Load()
	if err != nil {
		return r.waitForEnrollmentState(ctx, err)
	}
	if record.Status == enrollment.StatusStateLost {
		return r.waitTerminal(ctx, StateStateLost, "local device state is lost; heartbeat is disabled")
	}
	if record.Status == enrollment.StatusRevoked {
		return r.waitTerminal(ctx, StateRevoked, "device is revoked; heartbeat is disabled")
	}
	if record.Status != enrollment.StatusPending && record.Status != enrollment.StatusActive {
		return fmt.Errorf("app: unsupported enrollment status")
	}
	deviceID := record.DeviceID
	lifecycle := record.Status
	backoff, err := retry.New(r.config.BackoffInitial, r.config.BackoffMax)
	if err != nil {
		return err
	}
	for {
		if ctx.Err() != nil {
			return nil
		}
		r.setState(StateCollecting)
		status, err := r.collector.Collect()
		if err == nil {
			var model heartbeat.Model
			model, err = heartbeat.New(deviceID, status, r.config.AgentVersion, r.now(), r.config.CapabilityVersion)
			if err == nil {
				r.setState(StateConnecting)
				deliveryContext, cancel := context.WithTimeout(ctx, r.config.TransportTimeout)
				err = r.transport.SendHeartbeat(deliveryContext, model)
				cancel()
			}
		}
		if err == nil {
			if lifecycle == enrollment.StatusPending {
				if markErr := r.enrollment.MarkActive(); markErr != nil {
					return fmt.Errorf("app: persist activation: %w", markErr)
				}
				lifecycle = enrollment.StatusActive
			}
			backoff.Reset()
			r.setState(StateOnline)
			r.logger.Info("heartbeat accepted by transport")
			if err := r.wait(ctx, r.heartbeatDelay()); err != nil {
				if ctx.Err() != nil {
					return nil
				}
				return fmt.Errorf("app: wait heartbeat interval: %w", err)
			}
			continue
		}
		if ctx.Err() != nil {
			return nil
		}
		if errors.Is(err, transport.ErrStaleSequence) {
			if markErr := r.enrollment.MarkStateLost(); markErr != nil {
				return fmt.Errorf("app: persist state loss: %w", markErr)
			}
			return r.waitTerminal(ctx, StateStateLost, "heartbeat sequence is stale; recovery requires explicit re-enrollment")
		}
		if errors.Is(err, transport.ErrDeviceRevoked) {
			if markErr := r.enrollment.MarkRevoked(); markErr != nil {
				return fmt.Errorf("app: persist revocation: %w", markErr)
			}
			return r.waitTerminal(ctx, StateRevoked, "device was revoked; normal heartbeats are stopped")
		}
		if errors.Is(err, transport.ErrDevicePending) {
			if lifecycle != enrollment.StatusPending {
				return r.waitTerminal(ctx, StateBlocked, "backend reported pending for an active device; normal retries are stopped")
			}
			r.setState(StatePending)
			if err := r.wait(ctx, r.heartbeatDelay()); err != nil {
				if ctx.Err() != nil {
					return nil
				}
				return fmt.Errorf("app: wait pending heartbeat interval: %w", err)
			}
			continue
		}
		var retryAfter *transport.RetryAfterError
		if errors.As(err, &retryAfter) && retryAfter.Valid {
			r.setState(StateRateLimited)
			r.logger.Warn("heartbeat rate limited; honoring Retry-After")
			if err := r.wait(ctx, retryAfter.Delay); err != nil {
				if ctx.Err() != nil {
					return nil
				}
				return fmt.Errorf("app: wait Retry-After: %w", err)
			}
			continue
		}
		if errors.Is(err, transport.ErrRejected) {
			return r.waitTerminal(ctx, StateBlocked, "heartbeat rejected; normal retries are stopped")
		}
		r.setState(StateBackingOff)
		r.logger.Warn("heartbeat attempt failed", logging.ErrorField(err))
		if err := r.wait(ctx, backoff.Next()); err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return fmt.Errorf("app: wait reconnect backoff: %w", err)
		}
	}
}

func (r *Runner) waitForEnrollmentState(ctx context.Context, err error) error {
	switch {
	case errors.Is(err, enrollment.ErrNotEnrolled):
		return r.waitTerminal(ctx, StateWaitingForEnrollment, "agent is waiting for pairing enrollment")
	default:
		return fmt.Errorf("app: resolve enrollment state: %w", err)
	}
}

func (r *Runner) waitTerminal(ctx context.Context, state State, message string) error {
	r.setState(state)
	r.logger.Warn(message)
	<-ctx.Done()
	return nil
}

func (r *Runner) heartbeatDelay() time.Duration {
	jitter := r.jitter()
	if jitter > maxHeartbeatJitter {
		jitter = maxHeartbeatJitter
	}
	if jitter < -maxHeartbeatJitter {
		jitter = -maxHeartbeatJitter
	}
	return r.config.HeartbeatInterval + jitter
}

func defaultJitter() time.Duration {
	return time.Duration(rand.Intn(11)-5) * time.Second
}

func (r *Runner) setState(next State) {
	r.mu.Lock()
	r.state = next
	r.mu.Unlock()
	if r.onState != nil {
		r.onState(next)
	}
}

func waitFor(ctx context.Context, duration time.Duration) error {
	timer := time.NewTimer(duration)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}
