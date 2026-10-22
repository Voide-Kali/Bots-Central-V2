//go:build !unix

package commands

import "os"

func linkCount(os.FileInfo) uint64 { return 1 }

func openNoFollow(path string) (*os.File, error) {
	return os.Open(path)
}
