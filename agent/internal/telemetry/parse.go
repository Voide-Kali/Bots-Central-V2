package telemetry

import (
	"bufio"
	"encoding/binary"
	"errors"
	"strconv"
	"strings"
)

// cpuTimes is the aggregate "cpu" line of /proc/stat.
type cpuTimes struct{ idle, total uint64 }

func parseProcStat(content string) (cpuTimes, error) {
	scanner := bufio.NewScanner(strings.NewReader(content))
	for scanner.Scan() {
		fields := strings.Fields(scanner.Text())
		if len(fields) < 5 || fields[0] != "cpu" {
			continue
		}
		var times cpuTimes
		for i, field := range fields[1:] {
			value, err := strconv.ParseUint(field, 10, 64)
			if err != nil {
				return cpuTimes{}, err
			}
			if i >= 8 { // guest and guest_nice are already included in user/nice
				break
			}
			times.total += value
			if i == 3 || i == 4 { // idle + iowait
				times.idle += value
			}
		}
		return times, nil
	}
	return cpuTimes{}, errors.New("telemetry: no aggregate cpu line")
}

// cpuPercent returns busy percentage between two snapshots.
func cpuPercent(previous, current cpuTimes) (float64, bool) {
	if current.total <= previous.total || current.idle < previous.idle {
		return 0, false
	}
	total := current.total - previous.total
	idle := current.idle - previous.idle
	if idle > total {
		return 0, false
	}
	return float64(total-idle) * 100 / float64(total), true
}

// parseMeminfo returns total and used (total - available) bytes.
func parseMeminfo(content string) (total, used uint64, err error) {
	var totalKB, availableKB uint64
	var haveTotal, haveAvailable bool
	scanner := bufio.NewScanner(strings.NewReader(content))
	for scanner.Scan() {
		fields := strings.Fields(scanner.Text())
		if len(fields) < 2 {
			continue
		}
		value, parseErr := strconv.ParseUint(fields[1], 10, 64)
		if parseErr != nil {
			continue
		}
		switch fields[0] {
		case "MemTotal:":
			totalKB, haveTotal = value, true
		case "MemAvailable:":
			availableKB, haveAvailable = value, true
		}
	}
	if !haveTotal || !haveAvailable || availableKB > totalKB {
		return 0, 0, errors.New("telemetry: incomplete meminfo")
	}
	return totalKB * 1024, (totalKB - availableKB) * 1024, nil
}

// parseFirstFloat reads the first field of /proc/loadavg or /proc/uptime.
func parseFirstFloat(content string) (float64, error) {
	fields := strings.Fields(content)
	if len(fields) == 0 {
		return 0, errors.New("telemetry: empty")
	}
	return strconv.ParseFloat(fields[0], 64)
}

// parseMilliCelsius parses a sysfs temperature in millidegrees.
func parseMilliCelsius(content string) (float64, error) {
	value, err := strconv.ParseInt(strings.TrimSpace(content), 10, 64)
	if err != nil {
		return 0, err
	}
	return float64(value) / 1000, nil
}

// parseVMStat parses macOS `vm_stat` output and returns used bytes computed
// like Activity Monitor's "Memory Used": active + wired + compressed pages.
func parseVMStat(content string) (uint64, error) {
	scanner := bufio.NewScanner(strings.NewReader(content))
	var pageSize uint64
	pages := map[string]uint64{}
	for scanner.Scan() {
		line := scanner.Text()
		if strings.HasPrefix(line, "Mach Virtual Memory Statistics:") {
			if i := strings.Index(line, "page size of "); i >= 0 {
				rest := strings.Fields(line[i+len("page size of "):])
				if len(rest) > 0 {
					if v, err := strconv.ParseUint(rest[0], 10, 64); err == nil {
						pageSize = v
					}
				}
			}
			continue
		}
		name, value, ok := strings.Cut(line, ":")
		if !ok {
			continue
		}
		number, err := strconv.ParseUint(strings.TrimSuffix(strings.TrimSpace(value), "."), 10, 64)
		if err != nil {
			continue
		}
		pages[strings.TrimSpace(name)] = number
	}
	active, okA := pages["Pages active"]
	wired, okW := pages["Pages wired down"]
	compressed := pages["Pages occupied by compressor"]
	if pageSize == 0 || !okA || !okW {
		return 0, errors.New("telemetry: incomplete vm_stat")
	}
	return (active + wired + compressed) * pageSize, nil
}

// padSysctl restores trailing zero bytes that syscall.Sysctl strips from
// binary values on darwin.
func padSysctl(raw string, size int) []byte {
	buf := make([]byte, size)
	copy(buf, raw)
	return buf
}

// decodeLoadavg decodes darwin `struct loadavg` (3 x uint32 + long fscale).
func decodeLoadavg(raw string) (float64, bool) {
	buf := padSysctl(raw, 24)
	fscale := binary.LittleEndian.Uint64(buf[16:24])
	if fscale == 0 {
		return 0, false
	}
	return float64(binary.LittleEndian.Uint32(buf[0:4])) / float64(fscale), true
}

// decodeBoottimeSeconds decodes the tv_sec field of darwin `struct timeval`.
func decodeBoottimeSeconds(raw string) (int64, bool) {
	buf := padSysctl(raw, 16)
	sec := int64(binary.LittleEndian.Uint64(buf[0:8]))
	return sec, sec > 0
}

func decodeUint64(raw string) (uint64, bool) {
	buf := padSysctl(raw, 8)
	v := binary.LittleEndian.Uint64(buf)
	return v, v > 0
}
