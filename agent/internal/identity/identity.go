// Package identity owns the device-side private key foundation.
package identity

import (
	"bytes"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"

	jose "github.com/go-jose/go-jose/v4"

	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/storage"
)

const recordName = "device-identity-v1.json"

// Identity holds a local device keypair. The private key has no accessor and is never
// supplied to heartbeat or transport code.
type Identity struct{ privateKey ed25519.PrivateKey }

type diskRecord struct {
	Version    int    `json:"version"`
	PrivateKey string `json:"private_key"`
}

// LoadOrCreate retrieves the local keypair or creates it with crypto/rand. A malformed
// existing record is rejected rather than silently replaced.
func LoadOrCreate(store storage.Store) (*Identity, error) {
	data, err := store.Read(recordName)
	if errors.Is(err, os.ErrNotExist) {
		return create(store)
	}
	if err != nil {
		return nil, fmt.Errorf("identity: read local record: %w", err)
	}
	return decode(data)
}

func create(store storage.Store) (*Identity, error) {
	_, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		return nil, fmt.Errorf("identity: generate keypair: %w", err)
	}
	data, err := json.Marshal(diskRecord{Version: 1, PrivateKey: base64.RawStdEncoding.EncodeToString(privateKey)})
	if err != nil {
		return nil, fmt.Errorf("identity: encode local record: %w", err)
	}
	if err := store.WriteAtomic(recordName, data); err != nil {
		return nil, fmt.Errorf("identity: write local record: %w", err)
	}
	return &Identity{privateKey: privateKey}, nil
}

func decode(data []byte) (*Identity, error) {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var record diskRecord
	if err := decoder.Decode(&record); err != nil {
		return nil, errors.New("identity: malformed local record")
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return nil, errors.New("identity: malformed local record")
	}
	if record.Version != 1 || record.PrivateKey == "" {
		return nil, errors.New("identity: unsupported local record")
	}
	privateKey, err := base64.RawStdEncoding.DecodeString(record.PrivateKey)
	if err != nil || len(privateKey) != ed25519.PrivateKeySize {
		return nil, errors.New("identity: malformed local record")
	}
	return &Identity{privateKey: ed25519.PrivateKey(privateKey)}, nil
}

// PublicKey returns a copy for a future backend-governed enrollment flow.
func (i *Identity) PublicKey() ed25519.PublicKey {
	publicKey := i.privateKey.Public().(ed25519.PublicKey)
	return append(ed25519.PublicKey(nil), publicKey...)
}

// Public exposes only the public half through go-jose's opaque-signer boundary.
// It lets the JOSE library build compact framing without exposing private-key bytes.
func (i *Identity) Public() *jose.JSONWebKey {
	return &jose.JSONWebKey{Key: i.PublicKey()}
}

// Algs fixes this identity to EdDSA. Callers cannot negotiate an alternate
// signing algorithm or request an unsigned token.
func (i *Identity) Algs() []jose.SignatureAlgorithm { return []jose.SignatureAlgorithm{jose.EdDSA} }

// SignPayload implements jose.OpaqueSigner. The private key remains device-local
// while go-jose owns compact JWS framing and protected-header serialization.
func (i *Identity) SignPayload(message []byte, algorithm jose.SignatureAlgorithm) ([]byte, error) {
	if i == nil || len(i.privateKey) != ed25519.PrivateKeySize {
		return nil, errors.New("identity: private key is unavailable")
	}
	if algorithm != jose.EdDSA {
		return nil, errors.New("identity: unsupported signing algorithm")
	}
	return ed25519.Sign(i.privateKey, message), nil
}

// Fingerprint is a stable local display value, derived only from the public key.
func (i *Identity) Fingerprint() string {
	fingerprint, err := FingerprintForPublicKey(i.PublicKey())
	if err != nil {
		return ""
	}
	return fingerprint
}

// FingerprintForPublicKey returns the exact backend-approved public display
// format. It accepts only a raw 32-byte Ed25519 public key.
func FingerprintForPublicKey(publicKey ed25519.PublicKey) (string, error) {
	if len(publicKey) != ed25519.PublicKeySize {
		return "", errors.New("identity: invalid public key")
	}
	digest := sha256.Sum256(publicKey)
	return "SHA256:" + base64.RawURLEncoding.EncodeToString(digest[:]), nil
}
