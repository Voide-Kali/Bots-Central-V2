// Package retry implements bounded reconnect backoff.
package retry

import (
	"errors"
	"time"
)

// Backoff produces 1x, 2x, 4x ... delays, capped at maximum.
type Backoff struct {
	initial time.Duration
	maximum time.Duration
	attempt uint
}

func New(initial, maximum time.Duration) (*Backoff, error) {
	if initial <= 0 || maximum <= 0 || maximum < initial {
		return nil, errors.New("retry: invalid backoff bounds")
	}
	return &Backoff{initial: initial, maximum: maximum}, nil
}
func (b *Backoff) Next() time.Duration {
	delay := b.initial
	for shift := uint(0); shift < b.attempt && delay < b.maximum; shift++ {
		if delay > b.maximum/2 {
			delay = b.maximum
			break
		}
		delay *= 2
	}
	b.attempt++
	if delay > b.maximum {
		return b.maximum
	}
	return delay
}
func (b *Backoff) Reset() { b.attempt = 0 }
