// Package app coordinates local collection, heartbeat delivery, and shutdown.
package app

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"

	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/heartbeat"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/hostinfo"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/identity"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/logging"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/retry"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/transport"
)

const DefaultCapabilityVersion = "mvp1-heartbeat-model-v1"

// State describes the runtime reconnect state machine.
type State string

const (
	StateStarting             State = "starting"
	StateWaitingForEnrollment State = "waiting_for_enrollment"
	StateCollecting           State = "collecting"
	StateConnecting           State = "connecting"
	StateOnline               State = "online"
	StateBackingOff           State = "backing_off"
	StateStopping             State = "stopping"
	StateStopped              State = "stopped"
)

// Config controls the runtime only; backend endpoints and credentials are deliberately excluded.
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
type waitFunc func(context.Context, time.Duration) error

// Dependencies make side effects explicit and enable a fake transport in tests.
type Dependencies struct {
	Collector     HostCollector
	Identity      identity.DeviceIdentity
	Transport     transport.HeartbeatTransport
	Logger        *logging.Logger
	Now           func() time.Time
	Wait          waitFunc
	OnStateChange func(State)
}

// Runner sends a heartbeat immediately after successful enrollment, then on its regular
// interval. Failures transition to capped exponential reconnect backoff.
type Runner struct {
	config    Config
	collector HostCollector
	identity  identity.DeviceIdentity
	transport transport.HeartbeatTransport
	logger    *logging.Logger
	now       func() time.Time
	wait      waitFunc
	onState   func(State)
	mu        sync.RWMutex
	state     State
}

func New(config Config, dependencies Dependencies) (*Runner, error) {
	if err := validateConfig(config); err != nil {
		return nil, err
	}
	if dependencies.Collector == nil || dependencies.Identity == nil || dependencies.Transport == nil || dependencies.Logger == nil {
		return nil, errors.New("app: collector, identity, transport, and logger are required")
	}
	if dependencies.Now == nil {
		dependencies.Now = time.Now
	}
	if dependencies.Wait == nil {
		dependencies.Wait = waitFor
	}
	return &Runner{config: config, collector: dependencies.Collector, identity: dependencies.Identity, transport: dependencies.Transport, logger: dependencies.Logger, now: dependencies.Now, wait: dependencies.Wait, onState: dependencies.OnStateChange, state: StateStarting}, nil
}

func validateConfig(config Config) error {
	if config.HeartbeatInterval <= 0 || config.TransportTimeout <= 0 || config.BackoffInitial <= 0 || config.BackoffMax < config.BackoffInitial || config.AgentVersion == "" || config.CapabilityVersion == "" {
		return errors.New("app: invalid runtime configuration")
	}
	return nil
}

func (r *Runner) State() State { r.mu.RLock(); defer r.mu.RUnlock(); return r.state }

// Run blocks until cancellation. Context cancellation is a clean shutdown; local
// collection and transport-close errors are returned to the caller.
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
	deviceID, err := r.identity.DeviceID()
	if errors.Is(err, identity.ErrNotEnrolled) {
		r.setState(StateWaitingForEnrollment)
		r.logger.Info("agent is waiting for backend-governed enrollment")
		<-ctx.Done()
		return nil
	}
	if err != nil {
		return fmt.Errorf("app: resolve device identity: %w", err)
	}
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
			backoff.Reset()
			r.setState(StateOnline)
			r.logger.Info("heartbeat accepted by transport")
			if err := r.wait(ctx, r.config.HeartbeatInterval); err != nil {
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
