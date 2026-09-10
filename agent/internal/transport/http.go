package transport

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/enrollment"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/heartbeat"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/jws"
)

const (
	HeartbeatAudience  = "bots-central:heartbeat:v1"
	enrollmentAudience = "bots-central:enrollment:v1"
	maxResponseSize    = 64 * 1024
	maxRetryAfterSecs  = int64((1<<63 - 1) / int64(time.Second))
)

var (
	ErrStaleSequence = errors.New("transport: stale heartbeat sequence")
	ErrDeviceRevoked = errors.New("transport: device revoked")
	ErrRejected      = errors.New("transport: request rejected")
	ErrRateLimited   = errors.New("transport: rate limited")
)

// SequenceAllocator commits a sequence before the transport uses it.
type SequenceAllocator interface {
	Next() (uint64, error)
}

// HTTPConfig is intentionally endpoint-specific instead of deriving paths. The
// backend owns path selection; production endpoints must be HTTPS.
type HTTPConfig struct {
	EnrollmentURL            string
	HeartbeatURL             string
	Signer                   jws.Signer
	Sequence                 SequenceAllocator
	Client                   *http.Client
	Now                      func() time.Time
	AllowInsecureHTTPForTest bool
}

// HTTPClient implements enrollment proof-of-possession and JWS heartbeats over
// standard net/http with normal TLS verification.
type HTTPClient struct {
	enrollmentURL *url.URL
	heartbeatURL  *url.URL
	signer        jws.Signer
	sequence      SequenceAllocator
	client        *http.Client
	now           func() time.Time
}

func NewHTTP(config HTTPConfig) (*HTTPClient, error) {
	if config.Signer == nil || config.Sequence == nil {
		return nil, errors.New("transport: signer and sequence are required")
	}
	enrollmentURL, err := parseEndpoint(config.EnrollmentURL, config.AllowInsecureHTTPForTest)
	if err != nil {
		return nil, fmt.Errorf("transport: enrollment URL: %w", err)
	}
	heartbeatURL, err := parseEndpoint(config.HeartbeatURL, config.AllowInsecureHTTPForTest)
	if err != nil {
		return nil, fmt.Errorf("transport: heartbeat URL: %w", err)
	}
	if config.Client == nil {
		config.Client = &http.Client{}
	}
	// Enrollment and heartbeat credentials are bound to the configured endpoint.
	// Do not let net/http forward either one to a redirect target, even if that
	// target is also HTTPS.
	clientCopy := *config.Client
	clientCopy.CheckRedirect = func(_ *http.Request, _ []*http.Request) error {
		return http.ErrUseLastResponse
	}
	if config.Now == nil {
		config.Now = time.Now
	}
	return &HTTPClient{enrollmentURL: enrollmentURL, heartbeatURL: heartbeatURL, signer: config.Signer, sequence: config.Sequence, client: &clientCopy, now: config.Now}, nil
}

// EnrollmentResult is the non-secret server result persisted by the caller.
type EnrollmentResult struct {
	DeviceID string
	Status   enrollment.Status
}

// Enroll sends the one-time pairing token only in this request's Authorization
// header. It is not retained by the client or written to disk.
func (c *HTTPClient) Enroll(ctx context.Context, pairingToken string, publicKey ed25519.PublicKey) (EnrollmentResult, error) {
	if strings.TrimSpace(pairingToken) == "" {
		return EnrollmentResult{}, errors.New("transport: pairing token is required")
	}
	if len(publicKey) != ed25519.PublicKeySize {
		return EnrollmentResult{}, errors.New("transport: invalid public key")
	}
	encodedPublicKey := base64.RawURLEncoding.EncodeToString(publicKey)
	proof, err := jws.SignJSON(c.signer, struct {
		Audience  string `json:"aud"`
		IssuedAt  int64  `json:"iat"`
		PublicKey string `json:"public_key"`
	}{Audience: enrollmentAudience, IssuedAt: c.now().UTC().Unix(), PublicKey: encodedPublicKey})
	if err != nil {
		return EnrollmentResult{}, err
	}
	body, err := json.Marshal(struct {
		PublicKey string `json:"public_key"`
		Proof     string `json:"proof"`
	}{PublicKey: encodedPublicKey, Proof: proof})
	if err != nil {
		return EnrollmentResult{}, fmt.Errorf("transport: encode enrollment request: %w", err)
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, c.enrollmentURL.String(), bytes.NewReader(body))
	if err != nil {
		return EnrollmentResult{}, fmt.Errorf("transport: create enrollment request: %w", err)
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Authorization", "Bearer "+pairingToken)
	response, err := c.do(request)
	if err != nil {
		return EnrollmentResult{}, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK && response.StatusCode != http.StatusCreated {
		return EnrollmentResult{}, responseError(response, c.now())
	}
	var result struct {
		DeviceID string            `json:"device_id"`
		Status   enrollment.Status `json:"status"`
	}
	if err := decodeJSON(response.Body, &result); err != nil {
		return EnrollmentResult{}, fmt.Errorf("transport: invalid enrollment response: %w", err)
	}
	if result.DeviceID == "" || (result.Status != enrollment.StatusPending && result.Status != enrollment.StatusActive) {
		return EnrollmentResult{}, errors.New("transport: invalid enrollment response")
	}
	return EnrollmentResult{DeviceID: result.DeviceID, Status: result.Status}, nil
}

// SendHeartbeat allocates and durably commits a sequence before signing or
// sending it. Agent timestamps are metadata claims, never server authority.
func (c *HTTPClient) SendHeartbeat(ctx context.Context, model heartbeat.Model) error {
	sequence, err := c.sequence.Next()
	if err != nil {
		return err
	}
	token, err := jws.SignJSON(c.signer, struct {
		Audience          string `json:"aud"`
		Subject           string `json:"sub"`
		IssuedAt          int64  `json:"iat"`
		Sequence          uint64 `json:"seq"`
		Hostname          string `json:"hostname"`
		Platform          string `json:"platform"`
		AgentVersion      string `json:"agent_version"`
		CapabilityVersion string `json:"capability_version"`
		AgentTimestamp    string `json:"agent_timestamp"`
	}{
		Audience:          HeartbeatAudience,
		Subject:           model.DeviceID,
		IssuedAt:          c.now().UTC().Unix(),
		Sequence:          sequence,
		Hostname:          model.Hostname,
		Platform:          model.Platform,
		AgentVersion:      model.AgentVersion,
		CapabilityVersion: model.CapabilityVersion,
		AgentTimestamp:    model.Timestamp.UTC().Format(time.RFC3339Nano),
	})
	if err != nil {
		return err
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, c.heartbeatURL.String(), nil)
	if err != nil {
		return fmt.Errorf("transport: create heartbeat request: %w", err)
	}
	request.Header.Set("Authorization", "Bearer "+token)
	response, err := c.do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode == http.StatusOK || response.StatusCode == http.StatusAccepted || response.StatusCode == http.StatusNoContent {
		return nil
	}
	return responseError(response, c.now())
}

func (c *HTTPClient) Close() error {
	c.client.CloseIdleConnections()
	return nil
}

func (c *HTTPClient) do(request *http.Request) (*http.Response, error) {
	response, err := c.client.Do(request)
	if err != nil {
		if request.Context().Err() != nil {
			return nil, request.Context().Err()
		}
		return nil, &TemporaryError{cause: err}
	}
	return response, nil
}

// TemporaryError is retried only through the runner's bounded backoff.
type TemporaryError struct {
	Status int
	cause  error
}

func (e *TemporaryError) Error() string {
	if e.Status != 0 {
		return fmt.Sprintf("transport: temporary HTTP status %d", e.Status)
	}
	return "transport: temporary network failure"
}
func (e *TemporaryError) Unwrap() error { return e.cause }

// RetryAfterError carries a server-selected delay. Valid distinguishes a valid
// zero-second Retry-After from an absent or malformed header.
type RetryAfterError struct {
	Delay time.Duration
	Valid bool
}

func (e *RetryAfterError) Error() string { return "transport: rate limited" }
func (e *RetryAfterError) Unwrap() error { return ErrRateLimited }

// HTTPStatusError intentionally excludes response bodies so server diagnostics do
// not become log material.
type HTTPStatusError struct{ Status int }

func (e *HTTPStatusError) Error() string { return fmt.Sprintf("transport: HTTP status %d", e.Status) }
func (e *HTTPStatusError) Unwrap() error { return ErrRejected }

func responseError(response *http.Response, now time.Time) error {
	if response.StatusCode == http.StatusConflict {
		return ErrStaleSequence
	}
	if response.StatusCode == http.StatusTooManyRequests {
		delay, valid := retryAfter(response.Header.Get("Retry-After"), now)
		return &RetryAfterError{Delay: delay, Valid: valid}
	}
	if response.StatusCode == http.StatusForbidden {
		var body struct {
			Code string `json:"code"`
		}
		if decodeJSON(response.Body, &body) == nil && body.Code == "DEVICE_REVOKED" {
			return ErrDeviceRevoked
		}
		return &HTTPStatusError{Status: response.StatusCode}
	}
	if response.StatusCode >= http.StatusInternalServerError {
		return &TemporaryError{Status: response.StatusCode}
	}
	return &HTTPStatusError{Status: response.StatusCode}
}

func retryAfter(raw string, now time.Time) (time.Duration, bool) {
	if seconds, err := strconv.ParseInt(strings.TrimSpace(raw), 10, 64); err == nil && seconds >= 0 && seconds <= maxRetryAfterSecs {
		return time.Duration(seconds) * time.Second, true
	}
	if value, err := http.ParseTime(raw); err == nil {
		delay := value.Sub(now)
		if delay < 0 {
			delay = 0
		}
		return delay, true
	}
	return 0, false
}

func decodeJSON(reader io.Reader, destination any) error {
	decoder := json.NewDecoder(io.LimitReader(reader, maxResponseSize+1))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		return err
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return errors.New("unexpected trailing response data")
	}
	return nil
}

func parseEndpoint(raw string, allowInsecureHTTPForTest bool) (*url.URL, error) {
	parsed, err := url.ParseRequestURI(raw)
	if err != nil || parsed.Host == "" || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" {
		return nil, errors.New("invalid endpoint")
	}
	if parsed.Scheme != "https" && !(allowInsecureHTTPForTest && parsed.Scheme == "http") {
		return nil, errors.New("endpoint must use HTTPS")
	}
	return parsed, nil
}
