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

	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/enrollment"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/heartbeat"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/hostinfo"
)

type httpTestSigner struct{ key ed25519.PrivateKey }

func (s httpTestSigner) Sign(input []byte) ([]byte, error) { return ed25519.Sign(s.key, input), nil }

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
	client, err := NewHTTP(HTTPConfig{EnrollmentURL: "http://backend.test/enroll", HeartbeatURL: "http://backend.test/heartbeat", Signer: signer, Sequence: sequence, Client: &http.Client{Transport: roundTripper}, Now: func() time.Time { return now }, AllowInsecureHTTPForTest: true})
	if err != nil {
		t.Fatalf("NewHTTP() error = %v", err)
	}
	return client
}

func testResponse(status int, header http.Header, body string) *http.Response {
	return &http.Response{StatusCode: status, Header: header, Body: io.NopCloser(strings.NewReader(body))}
}

func TestEnrollSendsPublicKeyAndVerifiableProof(t *testing.T) {
	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("GenerateKey() error = %v", err)
	}
	now := time.Date(2026, 9, 10, 12, 0, 0, 0, time.UTC)
	client := newTestHTTP(t, httpTestSigner{key: privateKey}, &testSequence{}, now, roundTripFunc(func(request *http.Request) (*http.Response, error) {
		if request.URL.Path != "/enroll" || request.Method != http.MethodPost {
			t.Fatalf("unexpected enrollment request %s %s", request.Method, request.URL.Path)
		}
		if request.Header.Get("Authorization") != "Bearer one-time-pairing" {
			t.Fatal("pairing token header was not sent")
		}
		var body struct {
			PublicKey string `json:"public_key"`
			Proof     string `json:"proof"`
		}
		if err := json.NewDecoder(request.Body).Decode(&body); err != nil {
			t.Fatalf("decode enrollment body: %v", err)
		}
		if body.PublicKey != base64.RawURLEncoding.EncodeToString(publicKey) {
			t.Fatalf("public key = %q", body.PublicKey)
		}
		claims := verifyToken(t, body.Proof, publicKey)
		if claims["aud"] != enrollmentAudience || claims["public_key"] != body.PublicKey {
			t.Fatalf("unexpected proof claims: %#v", claims)
		}
		return testResponse(http.StatusCreated, http.Header{"Content-Type": []string{"application/json"}}, `{"device_id":"device-1","status":"pending"}`), nil
	}))
	result, err := client.Enroll(context.Background(), "one-time-pairing", publicKey)
	if err != nil {
		t.Fatalf("Enroll() error = %v", err)
	}
	if result != (EnrollmentResult{DeviceID: "device-1", Status: enrollment.StatusPending}) {
		t.Fatalf("result = %#v", result)
	}
}

func TestHeartbeatUsesExactAudienceAndPersistentSequence(t *testing.T) {
	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("GenerateKey() error = %v", err)
	}
	now := time.Date(2026, 9, 10, 12, 0, 0, 0, time.UTC)
	client := newTestHTTP(t, httpTestSigner{key: privateKey}, &testSequence{}, now, roundTripFunc(func(request *http.Request) (*http.Response, error) {
		if request.URL.Path != "/heartbeat" || request.Method != http.MethodPost {
			t.Fatalf("unexpected heartbeat request %s %s", request.Method, request.URL.Path)
		}
		token := strings.TrimPrefix(request.Header.Get("Authorization"), "Bearer ")
		claims := verifyToken(t, token, publicKey)
		if claims["aud"] != HeartbeatAudience || claims["sub"] != "device-1" || claims["seq"].(float64) != 1 {
			t.Fatalf("unexpected heartbeat claims: %#v", claims)
		}
		if _, ok := claims["agent_timestamp"].(string); !ok {
			t.Fatalf("agent timestamp metadata is missing: %#v", claims)
		}
		return testResponse(http.StatusAccepted, make(http.Header), ""), nil
	}))
	model, err := heartbeat.New("device-1", hostinfo.Status{Hostname: "host", Platform: "linux/amd64"}, "test", now, "cap-v1")
	if err != nil {
		t.Fatalf("heartbeat.New() error = %v", err)
	}
	if err := client.SendHeartbeat(context.Background(), model); err != nil {
		t.Fatalf("SendHeartbeat() error = %v", err)
	}
}

func TestHeartbeatClassifiesSecurityAndRetryResponses(t *testing.T) {
	_, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("GenerateKey() error = %v", err)
	}
	now := time.Date(2026, 9, 10, 12, 0, 0, 0, time.UTC)
	model, err := heartbeat.New("device-1", hostinfo.Status{Hostname: "host", Platform: "linux/amd64"}, "test", now, "cap-v1")
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
		{name: "stale sequence", status: http.StatusConflict, matches: ErrStaleSequence},
		{name: "revoked", status: http.StatusForbidden, body: `{"code":"DEVICE_REVOKED"}`, matches: ErrDeviceRevoked},
		{name: "rate limited", status: http.StatusTooManyRequests, header: "7", matches: ErrRateLimited, delay: 7 * time.Second},
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
	if delay, valid := retryAfter("9223372036854775807", now); valid || delay != 0 {
		t.Fatalf("retryAfter(overflow) = %s, %v; want 0, false", delay, valid)
	}
}

func TestProductionEndpointsRequireHTTPS(t *testing.T) {
	_, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("GenerateKey() error = %v", err)
	}
	if _, err := NewHTTP(HTTPConfig{EnrollmentURL: "http://backend.example/enroll", HeartbeatURL: "https://backend.example/heartbeat", Signer: httpTestSigner{key: privateKey}, Sequence: &testSequence{}}); err == nil {
		t.Fatal("NewHTTP() accepted HTTP endpoint")
	}
}

func TestHTTPClientRejectsRedirects(t *testing.T) {
	_, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("GenerateKey() error = %v", err)
	}
	client, err := NewHTTP(HTTPConfig{
		EnrollmentURL:            "https://backend.example/enroll",
		HeartbeatURL:             "https://backend.example/heartbeat",
		Signer:                   httpTestSigner{key: privateKey},
		Sequence:                 &testSequence{},
		Client:                   &http.Client{},
		AllowInsecureHTTPForTest: false,
	})
	if err != nil {
		t.Fatalf("NewHTTP() error = %v", err)
	}
	if err := client.client.CheckRedirect(nil, nil); !errors.Is(err, http.ErrUseLastResponse) {
		t.Fatalf("CheckRedirect() error = %v, want ErrUseLastResponse", err)
	}
}

func verifyToken(t *testing.T, token string, publicKey ed25519.PublicKey) map[string]any {
	t.Helper()
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		t.Fatalf("JWS parts = %d", len(parts))
	}
	signature, err := base64.RawURLEncoding.DecodeString(parts[2])
	if err != nil || !ed25519.Verify(publicKey, []byte(parts[0]+"."+parts[1]), signature) {
		t.Fatalf("JWS signature invalid: %v", err)
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		t.Fatalf("decode JWS payload: %v", err)
	}
	var claims map[string]any
	if err := json.Unmarshal(payload, &claims); err != nil {
		t.Fatalf("decode JWS claims: %v", err)
	}
	return claims
}
