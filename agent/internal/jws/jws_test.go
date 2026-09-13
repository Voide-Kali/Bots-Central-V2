package jws

import (
	"crypto/ed25519"
	"crypto/rand"
	"testing"

	jose "github.com/go-jose/go-jose/v4"
	"github.com/go-jose/go-jose/v4/jwt"
)

type testSigner struct{ key ed25519.PrivateKey }

func (s testSigner) Public() *jose.JSONWebKey        { return &jose.JSONWebKey{Key: s.key.Public()} }
func (s testSigner) Algs() []jose.SignatureAlgorithm { return []jose.SignatureAlgorithm{jose.EdDSA} }
func (s testSigner) SignPayload(input []byte, algorithm jose.SignatureAlgorithm) ([]byte, error) {
	if algorithm != jose.EdDSA {
		return nil, jose.ErrUnsupportedAlgorithm
	}
	return ed25519.Sign(s.key, input), nil
}

func TestSignClaimsCreatesGoJOSEVerifiedEdDSAJWS(t *testing.T) {
	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("GenerateKey() error = %v", err)
	}
	token, err := SignClaims(testSigner{key: privateKey}, struct {
		Audience string `json:"aud"`
		Subject  string `json:"sub"`
		Sequence uint64 `json:"seq"`
	}{Audience: "bots-central:heartbeat:v1", Subject: "device", Sequence: 7})
	if err != nil {
		t.Fatalf("SignClaims() error = %v", err)
	}
	parsed, err := jwt.ParseSigned(token, []jose.SignatureAlgorithm{jose.EdDSA})
	if err != nil {
		t.Fatalf("ParseSigned() error = %v", err)
	}
	if len(parsed.Headers) != 1 || parsed.Headers[0].Algorithm != string(jose.EdDSA) {
		t.Fatalf("headers = %#v", parsed.Headers)
	}
	var claims struct {
		Audience string `json:"aud"`
		Subject  string `json:"sub"`
		Sequence uint64 `json:"seq"`
	}
	if err := parsed.Claims(publicKey, &claims); err != nil {
		t.Fatalf("Claims() error = %v", err)
	}
	if claims.Audience != "bots-central:heartbeat:v1" || claims.Subject != "device" || claims.Sequence != 7 {
		t.Fatalf("claims = %#v", claims)
	}
}
