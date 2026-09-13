// Package heartbeat defines the internal, transport-neutral heartbeat model.
package heartbeat

import (
	"errors"
	"strings"
	"time"

	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/hostinfo"
)

// Model is an internal DTO, not an approved HTTP wire format.
type Model struct {
	DeviceID          string
	Hostname          string
	Platform          string
	AgentVersion      string
	Timestamp         time.Time
	CapabilityVersion string
}

func New(deviceID string, status hostinfo.Status, agentVersion string, timestamp time.Time, capabilityVersion string) (Model, error) {
	model := Model{DeviceID: strings.TrimSpace(deviceID), Hostname: strings.TrimSpace(status.Hostname), Platform: strings.TrimSpace(status.Platform), AgentVersion: strings.TrimSpace(agentVersion), Timestamp: timestamp.UTC(), CapabilityVersion: strings.TrimSpace(capabilityVersion)}
	if model.DeviceID == "" || model.Hostname == "" || model.Platform == "" || model.AgentVersion == "" || model.CapabilityVersion == "" || model.Timestamp.IsZero() {
		return Model{}, errors.New("heartbeat: incomplete model")
	}
	return model, nil
}
