// Package jws creates compact JWS messages with the standard EdDSA algorithm.
package jws

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
)

const algorithm = "EdDSA"

// Signer keeps key ownership outside the JWS encoder.
type Signer interface {
	Sign([]byte) ([]byte, error)
}

// SignJSON serializes claims once, then signs the JWS signing input as defined by
// RFC 7515. Callers provide typed claims; private-key material is never accepted.
func SignJSON(signer Signer, claims any) (string, error) {
	if signer == nil {
		return "", errors.New("jws: signer is required")
	}
	payload, err := json.Marshal(claims)
	if err != nil {
		return "", fmt.Errorf("jws: encode claims: %w", err)
	}
	header, err := json.Marshal(struct {
		Algorithm string `json:"alg"`
		Type      string `json:"typ"`
	}{Algorithm: algorithm, Type: "JWT"})
	if err != nil {
		return "", fmt.Errorf("jws: encode header: %w", err)
	}
	protected := base64.RawURLEncoding.EncodeToString(header)
	encodedPayload := base64.RawURLEncoding.EncodeToString(payload)
	signingInput := protected + "." + encodedPayload
	signature, err := signer.Sign([]byte(signingInput))
	if err != nil {
		return "", fmt.Errorf("jws: sign: %w", err)
	}
	if len(signature) == 0 {
		return "", errors.New("jws: empty signature")
	}
	return signingInput + "." + base64.RawURLEncoding.EncodeToString(signature), nil
}
