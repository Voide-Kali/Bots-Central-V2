package jws

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"strings"
	"testing"
)

type testSigner struct{ key ed25519.PrivateKey }

func (s testSigner) Sign(input []byte) ([]byte, error) { return ed25519.Sign(s.key, input), nil }

func TestSignJSONCreatesVerifiableEdDSAJWS(t *testing.T) {
	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("GenerateKey() error = %v", err)
	}
	token, err := SignJSON(testSigner{key: privateKey}, map[string]any{"aud": "bots-central:heartbeat:v1", "seq": 7})
	if err != nil {
		t.Fatalf("SignJSON() error = %v", err)
	}
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		t.Fatalf("parts = %d, want 3", len(parts))
	}
	headerData, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		t.Fatalf("decode header: %v", err)
	}
	var header map[string]string
	if err := json.Unmarshal(headerData, &header); err != nil {
		t.Fatalf("decode header JSON: %v", err)
	}
	if header["alg"] != "EdDSA" || header["typ"] != "JWT" {
		t.Fatalf("header = %#v", header)
	}
	signature, err := base64.RawURLEncoding.DecodeString(parts[2])
	if err != nil {
		t.Fatalf("decode signature: %v", err)
	}
	if !ed25519.Verify(publicKey, []byte(parts[0]+"."+parts[1]), signature) {
		t.Fatal("JWS signature does not verify")
	}
}
