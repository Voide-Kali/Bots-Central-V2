package transport

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode/utf8"

	jose "github.com/go-jose/go-jose/v4"

	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/commands"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/enrollment"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/heartbeat"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/identity"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/jws"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/telemetry"
)

const (
	HeartbeatAudience  = "bots-central:heartbeat:v1"
	enrollmentAudience = "bots-central:enrollment:v1"
	enrollmentPath     = "/api/v1/devices/enrollments"
	maxResponseSize    = 64 * 1024
	maxRetryAfterSecs  = int64((1<<63 - 1) / int64(time.Second))
)

var (
	ErrStaleSequence = errors.New("transport: stale heartbeat sequence")
	ErrDevicePending = errors.New("transport: device pending")
	ErrDeviceRevoked = errors.New("transport: device revoked")
	ErrRejected      = errors.New("transport: request rejected")
	ErrRateLimited   = errors.New("transport: rate limited")
)

// SequenceAllocator commits a sequence before the transport uses it.
type SequenceAllocator interface {
	Next() (uint64, error)
}

// HTTPConfig binds the agent to the backend's frozen V0.1 routes. Production
// uses one HTTPS origin; device-specific URLs are built from persisted UUIDs.
type HTTPConfig struct {
	BackendBaseURL           string
	Signer                   jose.OpaqueSigner
	Sequence                 SequenceAllocator
	Client                   *http.Client
	Now                      func() time.Time
	AllowInsecureHTTPForTest bool
}

// HTTPClient implements the final Device Online V0.1 wire protocol.
type HTTPClient struct {
	// signed serialises every sequence-signed request from allocation to response, so
	// two requests can never reach the server out of order (a late lower sequence is
	// "stale" and would mark the device state as lost). ADR-019 adds a second goroutine.
	signed         sync.Mutex
	backendBaseURL *url.URL
	signer         jose.OpaqueSigner
	sequence       SequenceAllocator
	client         *http.Client
	now            func() time.Time
}

func NewHTTP(config HTTPConfig) (*HTTPClient, error) {
	if config.Signer == nil || config.Sequence == nil {
		return nil, errors.New("transport: signer and sequence are required")
	}
	backendBaseURL, err := parseBackendBaseURL(config.BackendBaseURL, config.AllowInsecureHTTPForTest)
	if err != nil {
		return nil, fmt.Errorf("transport: backend base URL: %w", err)
	}
	if _, err := signerPublicKey(config.Signer); err != nil {
		return nil, err
	}
	if config.Client == nil {
		config.Client = &http.Client{}
	}
	// Pairing tokens and JWS values are bound to this backend origin. Never
	// forward either one to a redirect target, even one using HTTPS.
	clientCopy := *config.Client
	clientCopy.CheckRedirect = func(_ *http.Request, _ []*http.Request) error {
		return http.ErrUseLastResponse
	}
	if config.Now == nil {
		config.Now = time.Now
	}
	return &HTTPClient{backendBaseURL: backendBaseURL, signer: config.Signer, sequence: config.Sequence, client: &clientCopy, now: config.Now}, nil
}

// EnrollmentMetadata is the intentionally minimal backend-approved device
// metadata. It is not identity proof.
type EnrollmentMetadata struct {
	Name         string
	Platform     string
	AgentVersion *string
}

// EnrollmentResult is the non-secret, verified server result persisted by the caller.
type EnrollmentResult struct {
	DeviceID        string
	LifecycleStatus enrollment.Status
}

// Enroll sends the ephemeral pairing token in the backend-required JSON body.
// It verifies the returned fingerprint against the same local public key before
// allowing any enrollment state to be persisted.
func (c *HTTPClient) Enroll(ctx context.Context, pairingToken string, metadata EnrollmentMetadata) (EnrollmentResult, error) {
	if strings.TrimSpace(pairingToken) == "" {
		return EnrollmentResult{}, errors.New("transport: pairing token is required")
	}
	if err := validateEnrollmentMetadata(metadata); err != nil {
		return EnrollmentResult{}, err
	}
	publicKey, err := signerPublicKey(c.signer)
	if err != nil {
		return EnrollmentResult{}, err
	}
	encodedPublicKey := base64RawURL(publicKey)
	localFingerprint, err := identity.FingerprintForPublicKey(publicKey)
	if err != nil {
		return EnrollmentResult{}, err
	}
	proof, err := jws.SignClaims(c.signer, struct {
		Audience     string `json:"aud"`
		Subject      string `json:"sub"`
		PairingToken string `json:"pairing_token"`
	}{
		Audience:     enrollmentAudience,
		Subject:      "enrollment",
		PairingToken: pairingToken,
	})
	if err != nil {
		return EnrollmentResult{}, err
	}
	body, err := json.Marshal(struct {
		PairingToken string  `json:"pairing_token"`
		PublicKey    string  `json:"public_key"`
		Proof        string  `json:"proof"`
		Name         string  `json:"name"`
		Platform     string  `json:"platform"`
		AgentVersion *string `json:"agent_version"`
	}{
		PairingToken: pairingToken,
		PublicKey:    encodedPublicKey,
		Proof:        proof,
		Name:         metadata.Name,
		Platform:     metadata.Platform,
		AgentVersion: metadata.AgentVersion,
	})
	if err != nil {
		return EnrollmentResult{}, fmt.Errorf("transport: encode enrollment request: %w", err)
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, c.endpoint(enrollmentPath), bytes.NewReader(body))
	if err != nil {
		return EnrollmentResult{}, fmt.Errorf("transport: create enrollment request: %w", err)
	}
	request.Header.Set("Content-Type", "application/json")
	response, err := c.do(request)
	if err != nil {
		return EnrollmentResult{}, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusCreated {
		return EnrollmentResult{}, responseError(response, c.now())
	}
	var result struct {
		DeviceID        string            `json:"device_id"`
		LifecycleStatus enrollment.Status `json:"lifecycle_status"`
		Fingerprint     string            `json:"fingerprint"`
	}
	if err := decodeJSON(response.Body, &result); err != nil {
		return EnrollmentResult{}, fmt.Errorf("transport: invalid enrollment response: %w", err)
	}
	if !isCanonicalUUID(result.DeviceID) || result.LifecycleStatus != enrollment.StatusPending {
		return EnrollmentResult{}, errors.New("transport: invalid enrollment response")
	}
	if result.Fingerprint != localFingerprint {
		return EnrollmentResult{}, errors.New("transport: enrollment fingerprint mismatch")
	}
	return EnrollmentResult{DeviceID: result.DeviceID, LifecycleStatus: result.LifecycleStatus}, nil
}

// SendHeartbeat allocates and durably commits a sequence before signing or
// sending it. Server time, not agent metadata, is the presence authority.
func (c *HTTPClient) SendHeartbeat(ctx context.Context, model heartbeat.Model) error {
	c.signed.Lock()
	defer c.signed.Unlock()
	if !isCanonicalUUID(model.DeviceID) {
		return errors.New("transport: invalid device ID")
	}
	sequence, err := c.sequence.Next()
	if err != nil {
		return err
	}
	token, err := jws.SignClaims(c.signer, struct {
		Audience  string            `json:"aud"`
		Subject   string            `json:"sub"`
		Sequence  uint64            `json:"seq"`
		Telemetry *telemetry.Sample `json:"tel,omitempty"`
	}{
		Audience:  HeartbeatAudience,
		Subject:   model.DeviceID,
		Sequence:  sequence,
		Telemetry: model.Telemetry,
	})
	if err != nil {
		return err
	}
	body, err := json.Marshal(struct {
		JWS string `json:"jws"`
	}{JWS: token})
	if err != nil {
		return fmt.Errorf("transport: encode heartbeat request: %w", err)
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, c.heartbeatURL(model.DeviceID), bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("transport: create heartbeat request: %w", err)
	}
	request.Header.Set("Content-Type", "application/json")
	response, err := c.do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return responseError(response, c.now())
	}
	var result struct {
		Accepted bool `json:"accepted"`
	}
	if err := decodeJSON(response.Body, &result); err != nil || !result.Accepted {
		return errors.New("transport: invalid heartbeat response")
	}
	return nil
}

func (c *HTTPClient) Close() error {
	c.client.CloseIdleConnections()
	return nil
}

func (c *HTTPClient) endpoint(path string) string {
	endpoint := *c.backendBaseURL
	endpoint.Path = path
	endpoint.RawPath = ""
	endpoint.RawQuery = ""
	endpoint.ForceQuery = false
	endpoint.Fragment = ""
	return endpoint.String()
}

func (c *HTTPClient) heartbeatURL(deviceID string) string {
	return c.endpoint("/api/v1/devices/" + deviceID + "/heartbeat")
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
	if response.StatusCode >= http.StatusInternalServerError {
		return &TemporaryError{Status: response.StatusCode}
	}
	if response.StatusCode != http.StatusForbidden && response.StatusCode != http.StatusConflict && response.StatusCode != http.StatusTooManyRequests {
		return &HTTPStatusError{Status: response.StatusCode}
	}
	code, ok := responseCode(response.Body)
	if !ok {
		return &HTTPStatusError{Status: response.StatusCode}
	}
	switch {
	case response.StatusCode == http.StatusForbidden && code == "DEVICE_PENDING":
		return ErrDevicePending
	case response.StatusCode == http.StatusForbidden && code == "DEVICE_REVOKED":
		return ErrDeviceRevoked
	case response.StatusCode == http.StatusConflict && code == "STALE_HEARTBEAT":
		return ErrStaleSequence
	case response.StatusCode == http.StatusTooManyRequests && code == "HEARTBEAT_RATE_LIMITED":
		delay, valid := retryAfter(response.Header.Get("Retry-After"), now)
		return &RetryAfterError{Delay: delay, Valid: valid}
	default:
		return &HTTPStatusError{Status: response.StatusCode}
	}
}

func responseCode(reader io.Reader) (string, bool) {
	var body struct {
		Code string `json:"code"`
	}
	if err := decodeJSON(reader, &body); err != nil || body.Code == "" {
		return "", false
	}
	return body.Code, true
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

func parseBackendBaseURL(raw string, allowInsecureHTTPForTest bool) (*url.URL, error) {
	parsed, err := url.ParseRequestURI(raw)
	if err != nil || parsed.Host == "" || parsed.User != nil || parsed.RawQuery != "" || parsed.ForceQuery || parsed.Fragment != "" || parsed.RawPath != "" || (parsed.Path != "" && parsed.Path != "/") {
		return nil, errors.New("invalid backend base URL")
	}
	if parsed.Scheme != "https" && !(allowInsecureHTTPForTest && parsed.Scheme == "http") {
		return nil, errors.New("backend base URL must use HTTPS")
	}
	return parsed, nil
}

func validateEnrollmentMetadata(metadata EnrollmentMetadata) error {
	if !validMetadataValue(metadata.Name, 120) || !validMetadataValue(metadata.Platform, 64) {
		return errors.New("transport: invalid enrollment metadata")
	}
	if metadata.AgentVersion != nil && (!utf8.ValidString(*metadata.AgentVersion) || len(*metadata.AgentVersion) > 64) {
		return errors.New("transport: invalid agent version")
	}
	return nil
}

func validMetadataValue(value string, maximum int) bool {
	return value != "" && value == strings.TrimSpace(value) && utf8.ValidString(value) && len(value) <= maximum
}

func signerPublicKey(signer jose.OpaqueSigner) (ed25519.PublicKey, error) {
	jwk := signer.Public()
	if jwk == nil {
		return nil, errors.New("transport: signer public key is unavailable")
	}
	publicKey, ok := jwk.Key.(ed25519.PublicKey)
	if !ok || len(publicKey) != ed25519.PublicKeySize {
		return nil, errors.New("transport: signer must use an Ed25519 public key")
	}
	return append(ed25519.PublicKey(nil), publicKey...), nil
}

func base64RawURL(value []byte) string {
	return base64.RawURLEncoding.EncodeToString(value)
}

func isCanonicalUUID(value string) bool {
	if len(value) != 36 {
		return false
	}
	for index := 0; index < len(value); index++ {
		if index == 8 || index == 13 || index == 18 || index == 23 {
			if value[index] != '-' {
				return false
			}
			continue
		}
		if !(value[index] >= '0' && value[index] <= '9') && !(value[index] >= 'a' && value[index] <= 'f') {
			return false
		}
	}
	return true
}

const (
	commandsAudience      = "bots-central:commands:v1"
	commandResultAudience = "bots-central:command-result:v1"
	maxUploadBytes        = commands.MaxFileBytes
)

// PollCommand asks for one approved command. The request is signed and
// consumes a sequence number like a heartbeat, so it cannot be replayed.
func (c *HTTPClient) PollCommand(ctx context.Context, deviceID string) (*commands.Command, error) {
	c.signed.Lock()
	defer c.signed.Unlock()
	if !isCanonicalUUID(deviceID) {
		return nil, errors.New("transport: invalid device ID")
	}
	token, err := c.signNext(map[string]any{"aud": commandsAudience, "sub": deviceID})
	if err != nil {
		return nil, err
	}
	response, err := c.postJSON(ctx, "/api/v1/devices/"+deviceID+"/commands/next", map[string]any{"jws": token})
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, responseError(response, c.now())
	}
	var result struct {
		Command *commands.Command `json:"command"`
	}
	if err := decodeJSON(response.Body, &result); err != nil {
		return nil, errors.New("transport: invalid command response")
	}
	if result.Command != nil && (!isCanonicalUUID(result.Command.ID) || result.Command.Type == "") {
		return nil, errors.New("transport: invalid command response")
	}
	if result.Command != nil {
		result.Command.DeviceID = deviceID // the digest binds the command to this device
	}
	return result.Command, nil
}

// SubmitResult reports a command outcome. File bytes travel next to the JWS;
// their size and SHA-256 are inside the signed claims.
func (c *HTTPClient) SubmitResult(ctx context.Context, deviceID string, command commands.Command, result commands.Result) error {
	c.signed.Lock()
	defer c.signed.Unlock()
	if !isCanonicalUUID(deviceID) || !isCanonicalUUID(command.ID) {
		return errors.New("transport: invalid IDs")
	}
	claims := map[string]any{"aud": commandResultAudience, "sub": deviceID, "cid": command.ID}
	body := map[string]any{}
	if result.OK {
		if len(result.Content) > maxUploadBytes {
			return errors.New("transport: file too large")
		}
		claims["status"] = "ok"
		claims["size"] = len(result.Content)
		claims["sha256"] = result.SHA256
		body["content_b64"] = base64.StdEncoding.EncodeToString(result.Content)
	} else {
		claims["status"] = "error"
		claims["error"] = result.Error
	}
	token, err := c.signNext(claims)
	if err != nil {
		return err
	}
	body["jws"] = token
	response, err := c.postJSON(ctx, "/api/v1/devices/"+deviceID+"/commands/"+command.ID+"/result", body)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return responseError(response, c.now())
	}
	return nil
}

// LiveAudience separates live samples (ADR-018) from heartbeats: a heartbeat token is
// never accepted on the live route and vice versa.
const LiveAudience = "bots-central:live:v1"

// SendLive delivers one signed telemetry sample and returns whether the owner is
// still watching. It shares the heartbeat sequence, so it cannot be replayed.
func (c *HTTPClient) SendLive(ctx context.Context, deviceID string, sample telemetry.Sample) (bool, error) {
	c.signed.Lock()
	defer c.signed.Unlock()
	if !isCanonicalUUID(deviceID) {
		return false, errors.New("transport: invalid device ID")
	}
	token, err := c.signNext(map[string]any{"aud": LiveAudience, "sub": deviceID, "tel": sample})
	if err != nil {
		return false, err
	}
	response, err := c.postJSON(ctx, "/api/v1/devices/"+deviceID+"/live", map[string]any{"jws": token})
	if err != nil {
		return false, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return false, responseError(response, c.now())
	}
	var result struct {
		Live bool `json:"live"`
	}
	if err := decodeJSON(response.Body, &result); err != nil {
		return false, errors.New("transport: invalid live response")
	}
	return result.Live, nil
}

// EventAudience marks events the computer reports by itself (ADR-019).
const EventAudience = "bots-central:event:v1"

// SendEvent reports a wrong password; the photo (optional) travels next to the JWS and
// its size and SHA-256 are signed.
func (c *HTTPClient) SendEvent(ctx context.Context, deviceID, kind, source string, photo []byte) error {
	c.signed.Lock()
	defer c.signed.Unlock()
	if !isCanonicalUUID(deviceID) {
		return errors.New("transport: invalid device ID")
	}
	claims := map[string]any{"aud": EventAudience, "sub": deviceID, "kind": kind, "source": source}
	body := map[string]any{}
	if len(photo) > 0 {
		sum := sha256.Sum256(photo)
		claims["size"] = len(photo)
		claims["sha256"] = hex.EncodeToString(sum[:])
		body["photo_b64"] = base64.StdEncoding.EncodeToString(photo)
	}
	token, err := c.signNext(claims)
	if err != nil {
		return err
	}
	body["jws"] = token
	response, err := c.postJSON(ctx, "/api/v1/devices/"+deviceID+"/events", body)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return responseError(response, c.now())
	}
	return nil
}

func (c *HTTPClient) signNext(claims map[string]any) (string, error) {
	sequence, err := c.sequence.Next()
	if err != nil {
		return "", err
	}
	claims["seq"] = sequence
	return jws.SignClaims(c.signer, claims)
}

func (c *HTTPClient) postJSON(ctx context.Context, path string, payload any) (*http.Response, error) {
	body, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("transport: encode request: %w", err)
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, c.endpoint(path), bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("transport: create request: %w", err)
	}
	request.Header.Set("Content-Type", "application/json")
	return c.do(request)
}
