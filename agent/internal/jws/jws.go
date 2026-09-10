// Package jws signs compact EdDSA JWT/JWS messages through go-jose.
package jws

import (
	"errors"
	"fmt"

	jose "github.com/go-jose/go-jose/v4"
	"github.com/go-jose/go-jose/v4/jwt"
)

// SignClaims creates one compact JWS using the only allowed algorithm, EdDSA.
// The signer is opaque, keeping device-local private-key bytes out of the JOSE
// framing and transport layers.
func SignClaims(signer jose.OpaqueSigner, claims any) (string, error) {
	if signer == nil {
		return "", errors.New("jws: signer is required")
	}
	joseSigner, err := jose.NewSigner(jose.SigningKey{Algorithm: jose.EdDSA, Key: signer}, nil)
	if err != nil {
		return "", fmt.Errorf("jws: create EdDSA signer: %w", err)
	}
	token, err := jwt.Signed(joseSigner).Claims(claims).Serialize()
	if err != nil {
		return "", fmt.Errorf("jws: serialize claims: %w", err)
	}
	return token, nil
}
