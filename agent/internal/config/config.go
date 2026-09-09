// Package config loads the agent's intentionally small local configuration.
package config

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"
)

const maxConfigSize = 64 * 1024

// Config contains only local runtime controls. Device credentials and pairing data are
// intentionally absent until their backend contract is defined.
type Config struct {
	StateDir          string
	HeartbeatInterval time.Duration
	TransportTimeout  time.Duration
	BackoffInitial    time.Duration
	BackoffMax        time.Duration
}

type diskConfig struct {
	StateDir          string `json:"state_dir"`
	HeartbeatInterval string `json:"heartbeat_interval"`
	TransportTimeout  string `json:"transport_timeout"`
	BackoffInitial    string `json:"backoff_initial"`
	BackoffMax        string `json:"backoff_max"`
}

// Load reads one bounded configuration file. It does not fall back to defaults: a
// missing or malformed configuration is a startup failure.
func Load(path string) (Config, error) {
	if path == "" {
		return Config{}, errors.New("config: path is required")
	}
	file, err := os.Open(path)
	if err != nil {
		return Config{}, fmt.Errorf("config: cannot read file")
	}
	defer file.Close()
	data, err := io.ReadAll(io.LimitReader(file, maxConfigSize+1))
	if err != nil {
		return Config{}, fmt.Errorf("config: cannot read file")
	}
	if len(data) > maxConfigSize {
		return Config{}, errors.New("config: file exceeds maximum size")
	}
	return Parse(data)
}

// Parse decodes a strict JSON document and validates every required setting.
func Parse(data []byte) (Config, error) {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var raw diskConfig
	if err := decoder.Decode(&raw); err != nil {
		return Config{}, errors.New("config: invalid JSON")
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return Config{}, errors.New("config: invalid JSON")
	}
	if raw.StateDir == "" || !filepath.IsAbs(raw.StateDir) {
		return Config{}, errors.New("config: state_dir must be an absolute path")
	}
	heartbeatInterval, err := positiveDuration("heartbeat_interval", raw.HeartbeatInterval)
	if err != nil {
		return Config{}, err
	}
	transportTimeout, err := positiveDuration("transport_timeout", raw.TransportTimeout)
	if err != nil {
		return Config{}, err
	}
	backoffInitial, err := positiveDuration("backoff_initial", raw.BackoffInitial)
	if err != nil {
		return Config{}, err
	}
	backoffMax, err := positiveDuration("backoff_max", raw.BackoffMax)
	if err != nil {
		return Config{}, err
	}
	if backoffMax < backoffInitial {
		return Config{}, errors.New("config: backoff_max must be greater than or equal to backoff_initial")
	}
	return Config{StateDir: filepath.Clean(raw.StateDir), HeartbeatInterval: heartbeatInterval, TransportTimeout: transportTimeout, BackoffInitial: backoffInitial, BackoffMax: backoffMax}, nil
}

func positiveDuration(name, raw string) (time.Duration, error) {
	value, err := time.ParseDuration(raw)
	if err != nil || value <= 0 {
		return 0, fmt.Errorf("config: %s must be a positive duration", name)
	}
	return value, nil
}
