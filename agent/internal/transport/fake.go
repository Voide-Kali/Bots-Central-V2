package transport

import (
	"context"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/heartbeat"
	"sync"
)

// Fake is an in-memory backend substitute for lifecycle tests.
type Fake struct {
	mu                sync.Mutex
	Results           []error
	BlockUntilContext bool
	CloseError        error
	OnSend            func(heartbeat.Model)
	calls             []heartbeat.Model
	closed            bool
	deadlineSeen      bool
}

func (f *Fake) SendHeartbeat(ctx context.Context, model heartbeat.Model) error {
	f.mu.Lock()
	f.calls = append(f.calls, model)
	if _, ok := ctx.Deadline(); ok {
		f.deadlineSeen = true
	}
	index := len(f.calls) - 1
	var result error
	if index < len(f.Results) {
		result = f.Results[index]
	}
	onSend, block := f.OnSend, f.BlockUntilContext
	f.mu.Unlock()
	if onSend != nil {
		onSend(model)
	}
	if block {
		<-ctx.Done()
		return ctx.Err()
	}
	return result
}
func (f *Fake) Close() error { f.mu.Lock(); defer f.mu.Unlock(); f.closed = true; return f.CloseError }
func (f *Fake) Calls() []heartbeat.Model {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]heartbeat.Model(nil), f.calls...)
}
func (f *Fake) Closed() bool       { f.mu.Lock(); defer f.mu.Unlock(); return f.closed }
func (f *Fake) DeadlineSeen() bool { f.mu.Lock(); defer f.mu.Unlock(); return f.deadlineSeen }
