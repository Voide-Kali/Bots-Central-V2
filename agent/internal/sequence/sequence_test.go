package sequence

import (
	"sort"
	"sync"
	"testing"

	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/storage"
)

func TestNextPersistsAcrossRestart(t *testing.T) {
	fileStore, err := storage.NewFileStore(t.TempDir())
	if err != nil {
		t.Fatalf("NewFileStore() error = %v", err)
	}
	first, err := New(fileStore)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	for want := uint64(1); want <= 2; want++ {
		if got, err := first.Next(); err != nil || got != want {
			t.Fatalf("Next() = %d, %v; want %d", got, err, want)
		}
	}
	restarted, err := New(fileStore)
	if err != nil {
		t.Fatalf("restart New() error = %v", err)
	}
	if got, err := restarted.Next(); err != nil || got != 3 {
		t.Fatalf("restarted Next() = %d, %v; want 3", got, err)
	}
}

func TestNextIsMonotonicUnderConcurrency(t *testing.T) {
	fileStore, err := storage.NewFileStore(t.TempDir())
	if err != nil {
		t.Fatalf("NewFileStore() error = %v", err)
	}
	first, err := New(fileStore)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	second, err := New(fileStore)
	if err != nil {
		t.Fatalf("second New() error = %v", err)
	}
	const count = 128
	values := make(chan uint64, count)
	errorsSeen := make(chan error, count)
	var group sync.WaitGroup
	for index := range count {
		group.Add(1)
		go func(index int) {
			defer group.Done()
			allocator := first
			if index%2 == 1 {
				allocator = second
			}
			value, err := allocator.Next()
			if err != nil {
				errorsSeen <- err
				return
			}
			values <- value
		}(index)
	}
	group.Wait()
	close(values)
	close(errorsSeen)
	for err := range errorsSeen {
		t.Fatalf("concurrent Next() error = %v", err)
	}
	got := make([]uint64, 0, count)
	for value := range values {
		got = append(got, value)
	}
	if len(got) != count {
		t.Fatalf("allocated %d sequences, want %d", len(got), count)
	}
	sort.Slice(got, func(left, right int) bool { return got[left] < got[right] })
	for index, value := range got {
		if want := uint64(index + 1); value != want {
			t.Fatalf("sequence[%d] = %d, want %d", index, value, want)
		}
	}
}
