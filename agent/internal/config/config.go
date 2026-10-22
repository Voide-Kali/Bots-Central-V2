// Package config loads the agent's intentionally small local configuration.
package config

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const maxConfigSize = 64 * 1024

const RequiredHeartbeatInterval = 30 * time.Second

// Config contains local runtime controls and one explicit backend origin. Device
// credentials and pairing data are intentionally absent.
type Config struct {
	StateDir          string
	BackendBaseURL    string
	HeartbeatInterval time.Duration
	TransportTimeout  time.Duration
	BackoffInitial    time.Duration
	BackoffMax        time.Duration
	// SharedDir enables human-approved file sending from this one folder (ADR-015).
	// Empty disables commands entirely.
	SharedDir string
}

type diskConfig struct {
	StateDir          string `json:"state_dir"`
	BackendBaseURL    string `json:"backend_base_url"`
	HeartbeatInterval string `json:"heartbeat_interval"`
	TransportTimeout  string `json:"transport_timeout"`
	BackoffInitial    string `json:"backoff_initial"`
	BackoffMax        string `json:"backoff_max"`
	SharedDir         string `json:"shared_dir,omitempty"`
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
	if heartbeatInterval != RequiredHeartbeatInterval {
		return Config{}, errors.New("config: heartbeat_interval must be 30s")
	}
	backendBaseURL, err := httpsBaseURL("backend_base_url", raw.BackendBaseURL)
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
	sharedDir := ""
	if raw.SharedDir != "" {
		if !filepath.IsAbs(raw.SharedDir) {
			return Config{}, errors.New("config: shared_dir must be an absolute path")
		}
		sharedDir = filepath.Clean(raw.SharedDir)
		if sharedDir == filepath.Clean(raw.StateDir) || sharedDir == "/" {
			return Config{}, errors.New("config: shared_dir must be a dedicated folder")
		}
	}
	return Config{StateDir: filepath.Clean(raw.StateDir), BackendBaseURL: backendBaseURL, HeartbeatInterval: heartbeatInterval, TransportTimeout: transportTimeout, BackoffInitial: backoffInitial, BackoffMax: backoffMax, SharedDir: sharedDir}, nil
}

func positiveDuration(name, raw string) (time.Duration, error) {
	value, err := time.ParseDuration(raw)
	if err != nil || value <= 0 {
		return 0, fmt.Errorf("config: %s must be a positive duration", name)
	}
	return value, nil
}

func httpsBaseURL(name, raw string) (string, error) {
	parsed, err := url.ParseRequestURI(raw)
	if err != nil || parsed.Scheme != "https" || parsed.Host == "" || parsed.User != nil || parsed.RawQuery != "" || parsed.ForceQuery || parsed.Fragment != "" || parsed.RawPath != "" || (parsed.Path != "" && parsed.Path != "/") {
		return "", fmt.Errorf("config: %s must be an HTTPS origin without credentials, path, query, or fragment", name)
	}
	return strings.TrimRight(parsed.String(), "/"), nil
}
