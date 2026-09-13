// Package transport defines the boundary where a backend-approved protocol will attach.
package transport

import (
	"context"

	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/heartbeat"
)

// HeartbeatTransport keeps runner policy independent from the HTTP implementation.
type HeartbeatTransport interface {
	SendHeartbeat(context.Context, heartbeat.Model) error
	Close() error
}
