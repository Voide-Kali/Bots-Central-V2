// Package identity owns the device-side private key foundation.
package identity

import (
	"bytes"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"

	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/storage"
)

const recordName = "device-identity-v1.json"

var ErrNotEnrolled = errors.New("identity: device is not enrolled")

// DeviceIdentity is the narrow view the runtime needs from a paired identity.
type DeviceIdentity interface{ DeviceID() (string, error) }

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

// DeviceID confirms that this key-only local foundation is not an enrollment protocol.
func (i *Identity) DeviceID() (string, error) { return "", ErrNotEnrolled }
