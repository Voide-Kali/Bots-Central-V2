// Package transport defines the boundary where a backend-approved protocol will attach.
package transport

import (
	"context"
	"errors"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/heartbeat"
)

// HeartbeatTransport deliberately exposes an internal model instead of an HTTP request.
type HeartbeatTransport interface {
	SendHeartbeat(context.Context, heartbeat.Model) error
	Close() error
}

var ErrBackendContractUnavailable = errors.New("transport: backend contract is not configured")

// Unavailable is the production placeholder until the shared backend contract exists. It makes no network calls.
type Unavailable struct{}

func (Unavailable) SendHeartbeat(ctx context.Context, _ heartbeat.Model) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	return ErrBackendContractUnavailable
}
func (Unavailable) Close() error { return nil }
