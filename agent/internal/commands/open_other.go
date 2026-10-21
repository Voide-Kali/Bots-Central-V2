//go:build !unix

package commands

import "os"

func openNoFollow(path string) (*os.File, error) {
	return os.Open(path)
}
