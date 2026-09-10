package transport

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"sync"
	"testing"
	"time"

	jose "github.com/go-jose/go-jose/v4"
	"github.com/go-jose/go-jose/v4/jwt"

	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/enrollment"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/heartbeat"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/hostinfo"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/identity"
)

const testDeviceID = "123e4567-e89b-12d3-a456-426614174000"

type httpTestSigner struct{ key ed25519.PrivateKey }

func (s httpTestSigner) Public() *jose.JSONWebKey { return &jose.JSONWebKey{Key: s.key.Public()} }
func (s httpTestSigner) Algs() []jose.SignatureAlgorithm {
	return []jose.SignatureAlgorithm{jose.EdDSA}
}
func (s httpTestSigner) SignPayload(input []byte, algorithm jose.SignatureAlgorithm) ([]byte, error) {
	if algorithm != jose.EdDSA {
		return nil, jose.ErrUnsupportedAlgorithm
	}
	return ed25519.Sign(s.key, input), nil
}

type testSequence struct {
	mu   sync.Mutex
	next uint64
}

func (s *testSequence) Next() (uint64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.next++
	return s.next, nil
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) { return f(request) }

func newTestHTTP(t *testing.T, signer httpTestSigner, sequence SequenceAllocator, now time.Time, roundTripper http.RoundTripper) *HTTPClient {
	t.Helper()
	client, err := NewHTTP(HTTPConfig{BackendBaseURL: "http://backend.test", Signer: signer, Sequence: sequence, Client: &http.Client{Transport: roundTripper}, Now: func() time.Time { return now }, AllowInsecureHTTPForTest: true})
	if err != nil {
		t.Fatalf("NewHTTP() error = %v", err)
	}
	return client
}

func testResponse(status int, header http.Header, body string) *http.Response {
	return &http.Response{StatusCode: status, Header: header, Body: io.NopCloser(strings.NewReader(body))}
}

func TestEnrollUsesFrozenBackendSchemaAndProof(t *testing.T) {
	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("GenerateKey() error = %v", err)
	}
	now := time.Date(2026, 9, 10, 12, 0, 0, 0, time.UTC)
	fingerprint, err := identity.FingerprintForPublicKey(publicKey)
	if err != nil {
		t.Fatalf("FingerprintForPublicKey() error = %v", err)
	}
	version := "0.1.0"
	client := newTestHTTP(t, httpTestSigner{key: privateKey}, &testSequence{}, now, roundTripFunc(func(request *http.Request) (*http.Response, error) {
		if request.URL.Path != enrollmentPath || request.Method != http.MethodPost {
			t.Fatalf("unexpected enrollment request %s %s", request.Method, request.URL.Path)
		}
		if request.Header.Get("Authorization") != "" {
			t.Fatal("pairing token must not be sent as Authorization")
		}
		if request.Header.Get("Content-Type") != "application/json" {
			t.Fatalf("Content-Type = %q", request.Header.Get("Content-Type"))
		}
		var body map[string]json.RawMessage
		if err := json.NewDecoder(request.Body).Decode(&body); err != nil {
			t.Fatalf("decode enrollment body: %v", err)
		}
		if len(body) != 6 {
			t.Fatalf("enrollment schema fields = %d, want 6", len(body))
		}
		var decoded struct {
			PairingToken string  `json:"pairing_token"`
			PublicKey    string  `json:"public_key"`
			Proof        string  `json:"proof"`
			Name         string  `json:"name"`
			Platform     string  `json:"platform"`
			AgentVersion *string `json:"agent_version"`
		}
		encoded, _ := json.Marshal(body)
		if err := json.Unmarshal(encoded, &decoded); err != nil {
			t.Fatalf("decode typed enrollment body: %v", err)
		}
		if decoded.PairingToken != "one-time-pairing" || decoded.PublicKey != base64.RawURLEncoding.EncodeToString(publicKey) || decoded.Name != "host" || decoded.Platform != "linux/amd64" || decoded.AgentVersion == nil || *decoded.AgentVersion != version {
			t.Fatalf("unexpected enrollment body: %#v", decoded)
		}
		claims := verifyBackendClaims(t, decoded.Proof, publicKey)
		if claims.Audience != enrollmentAudience || claims.Subject != "enrollment" || claims.PairingToken != decoded.PairingToken {
			t.Fatalf("unexpected enrollment proof claims: %#v", claims)
		}
		return testResponse(http.StatusCreated, make(http.Header), `{"device_id":"`+testDeviceID+`","lifecycle_status":"pending","fingerprint":"`+fingerprint+`"}`), nil
	}))
	result, err := client.Enroll(context.Background(), "one-time-pairing", EnrollmentMetadata{Name: "host", Platform: "linux/amd64", AgentVersion: &version})
	if err != nil {
		t.Fatalf("Enroll() error = %v", err)
	}
	if result != (EnrollmentResult{DeviceID: testDeviceID, LifecycleStatus: enrollment.StatusPending}) {
		t.Fatalf("result = %#v", result)
	}
}

func TestEnrollFailsClosedOnFingerprintMismatch(t *testing.T) {
	_, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("GenerateKey() error = %v", err)
	}
	client := newTestHTTP(t, httpTestSigner{key: privateKey}, &testSequence{}, time.Now(), roundTripFunc(func(_ *http.Request) (*http.Response, error) {
		return testResponse(http.StatusCreated, make(http.Header), `{"device_id":"`+testDeviceID+`","lifecycle_status":"pending","fingerprint":"SHA256:not-the-local-key"}`), nil
	}))
	if _, err := client.Enroll(context.Background(), "one-time-pairing", EnrollmentMetadata{Name: "host", Platform: "linux/amd64"}); err == nil {
		t.Fatal("Enroll() accepted mismatched fingerprint")
	}
}

func TestHeartbeatUsesFrozenBackendBodyAndClaims(t *testing.T) {
	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("GenerateKey() error = %v", err)
	}
	now := time.Date(2026, 9, 10, 12, 0, 0, 0, time.UTC)
	client := newTestHTTP(t, httpTestSigner{key: privateKey}, &testSequence{}, now, roundTripFunc(func(request *http.Request) (*http.Response, error) {
		if request.URL.Path != "/api/v1/devices/"+testDeviceID+"/heartbeat" || request.Method != http.MethodPost {
			t.Fatalf("unexpected heartbeat request %s %s", request.Method, request.URL.Path)
		}
		if request.Header.Get("Authorization") != "" {
			t.Fatal("heartbeat JWS must not be sent as Authorization")
		}
		if request.Header.Get("Content-Type") != "application/json" {
			t.Fatalf("Content-Type = %q", request.Header.Get("Content-Type"))
		}
		var body map[string]json.RawMessage
		if err := json.NewDecoder(request.Body).Decode(&body); err != nil {
			t.Fatalf("decode heartbeat body: %v", err)
		}
		if len(body) != 1 || body["jws"] == nil {
			t.Fatalf("heartbeat body = %#v, want only jws", body)
		}
		var token string
		if err := json.Unmarshal(body["jws"], &token); err != nil {
			t.Fatalf("decode JWS body value: %v", err)
		}
		claims := verifyBackendClaims(t, token, publicKey)
		if claims.Audience != HeartbeatAudience || claims.Subject != testDeviceID || claims.Sequence != 1 || claims.PairingToken != "" {
			t.Fatalf("unexpected heartbeat claims: %#v", claims)
		}
		return testResponse(http.StatusOK, make(http.Header), `{"accepted":true}`), nil
	}))
	model, err := heartbeat.New(testDeviceID, hostinfo.Status{Hostname: "host", Platform: "linux/amd64"}, "test", now, "cap-v1")
	if err != nil {
		t.Fatalf("heartbeat.New() error = %v", err)
	}
	if err := client.SendHeartbeat(context.Background(), model); err != nil {
		t.Fatalf("SendHeartbeat() error = %v", err)
	}
}

func TestHeartbeatClassifiesFrozenSecurityAndRetryResponses(t *testing.T) {
	_, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("GenerateKey() error = %v", err)
	}
	now := time.Date(2026, 9, 10, 12, 0, 0, 0, time.UTC)
	model, err := heartbeat.New(testDeviceID, hostinfo.Status{Hostname: "host", Platform: "linux/amd64"}, "test", now, "cap-v1")
	if err != nil {
		t.Fatalf("heartbeat.New() error = %v", err)
	}
	cases := []struct {
		name      string
		status    int
		header    string
		body      string
		matches   error
		temporary bool
		delay     time.Duration
	}{
		{name: "pending", status: http.StatusForbidden, body: `{"code":"DEVICE_PENDING"}`, matches: ErrDevicePending},
		{name: "revoked", status: http.StatusForbidden, body: `{"code":"DEVICE_REVOKED"}`, matches: ErrDeviceRevoked},
		{name: "stale heartbeat", status: http.StatusConflict, body: `{"code":"STALE_HEARTBEAT"}`, matches: ErrStaleSequence},
		{name: "rate limited", status: http.StatusTooManyRequests, header: "7", body: `{"code":"HEARTBEAT_RATE_LIMITED"}`, matches: ErrRateLimited, delay: 7 * time.Second},
		{name: "generic forbidden", status: http.StatusForbidden, body: `{"code":"OTHER"}`, matches: ErrRejected},
		{name: "server failure", status: http.StatusServiceUnavailable, temporary: true},
	}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			client := newTestHTTP(t, httpTestSigner{key: privateKey}, &testSequence{}, now, roundTripFunc(func(_ *http.Request) (*http.Response, error) {
				header := make(http.Header)
				if test.header != "" {
					header.Set("Retry-After", test.header)
				}
				return testResponse(test.status, header, test.body), nil
			}))
			err := client.SendHeartbeat(context.Background(), model)
			if test.matches != nil && !errors.Is(err, test.matches) {
				t.Fatalf("SendHeartbeat() error = %v, want %v", err, test.matches)
			}
			if test.temporary {
				var temporary *TemporaryError
				if !errors.As(err, &temporary) || temporary.Status != http.StatusServiceUnavailable {
					t.Fatalf("temporary error = %#v", temporary)
				}
			}
			if test.delay > 0 {
				var rate *RetryAfterError
				if !errors.As(err, &rate) || !rate.Valid || rate.Delay != test.delay {
					t.Fatalf("RetryAfterError = %#v, want %s", rate, test.delay)
				}
			}
		})
	}
}

func TestRetryAfterKeepsValidZeroSeparateFromInvalidValue(t *testing.T) {
	now := time.Date(2026, 9, 10, 12, 0, 0, 0, time.UTC)
	if delay, valid := retryAfter("0", now); !valid || delay != 0 {
		t.Fatalf("retryAfter(0) = %s, %v; want 0, true", delay, valid)
	}
	if delay, valid := retryAfter("not-a-delay", now); valid || delay != 0 {
		t.Fatalf("retryAfter(invalid) = %s, %v; want 0, false", delay, valid)
	}
}

func TestProductionBaseURLRequiresHTTPS(t *testing.T) {
	_, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("GenerateKey() error = %v", err)
	}
	if _, err := NewHTTP(HTTPConfig{BackendBaseURL: "http://backend.example", Signer: httpTestSigner{key: privateKey}, Sequence: &testSequence{}}); err == nil {
		t.Fatal("NewHTTP() accepted HTTP backend origin")
	}
}

func TestHTTPClientRejectsRedirects(t *testing.T) {
	_, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("GenerateKey() error = %v", err)
	}
	client, err := NewHTTP(HTTPConfig{BackendBaseURL: "https://backend.example", Signer: httpTestSigner{key: privateKey}, Sequence: &testSequence{}, Client: &http.Client{}})
	if err != nil {
		t.Fatalf("NewHTTP() error = %v", err)
	}
	if err := client.client.CheckRedirect(nil, nil); !errors.Is(err, http.ErrUseLastResponse) {
		t.Fatalf("CheckRedirect() error = %v, want ErrUseLastResponse", err)
	}
}

type backendClaims struct {
	Audience     string `json:"aud"`
	Subject      string `json:"sub"`
	Sequence     uint64 `json:"seq"`
	PairingToken string `json:"pairing_token"`
}

func verifyBackendClaims(t *testing.T, token string, publicKey ed25519.PublicKey) backendClaims {
	t.Helper()
	parsed, err := jwt.ParseSigned(token, []jose.SignatureAlgorithm{jose.EdDSA})
	if err != nil {
		t.Fatalf("ParseSigned() error = %v", err)
	}
	if len(parsed.Headers) != 1 || parsed.Headers[0].Algorithm != string(jose.EdDSA) {
		t.Fatalf("JWS headers = %#v", parsed.Headers)
	}
	var claims backendClaims
	if err := parsed.Claims(publicKey, &claims); err != nil {
		t.Fatalf("Claims() error = %v", err)
	}
	return claims
}
