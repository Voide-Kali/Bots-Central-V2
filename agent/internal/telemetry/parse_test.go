package telemetry

import (
	"encoding/binary"
	"encoding/json"
	"math"
	"strings"
	"testing"
)

func TestParseProcStatAndCPUPercent(t *testing.T) {
	first, err := parseProcStat("cpu  100 0 100 700 100 0 0 0 0 0\ncpu0 1 2 3 4 5\n")
	if err != nil {
		t.Fatal(err)
	}
	second, err := parseProcStat("cpu  150 0 150 750 150 0 0 0 0 0\n")
	if err != nil {
		t.Fatal(err)
	}
	pct, ok := cpuPercent(first, second)
	if !ok || math.Abs(pct-50) > 0.001 {
		t.Fatalf("pct=%v ok=%v", pct, ok)
	}
	if _, ok := cpuPercent(second, first); ok {
		t.Fatal("counter rollback must not produce a value")
	}
	if _, err := parseProcStat("intr 1 2 3\n"); err == nil {
		t.Fatal("missing cpu line must fail")
	}
}

func TestParseMeminfo(t *testing.T) {
	total, used, err := parseMeminfo("MemTotal:       16000 kB\nMemFree: 1000 kB\nMemAvailable:    6000 kB\n")
	if err != nil || total != 16000*1024 || used != 10000*1024 {
		t.Fatalf("total=%d used=%d err=%v", total, used, err)
	}
	if _, _, err := parseMeminfo("MemTotal: 10 kB\n"); err == nil {
		t.Fatal("missing MemAvailable must fail")
	}
	if _, _, err := parseMeminfo("MemTotal: 10 kB\nMemAvailable: 11 kB\n"); err == nil {
		t.Fatal("available above total must fail")
	}
}

func TestParseSimpleValues(t *testing.T) {
	if v, err := parseFirstFloat("0.52 0.40 0.30 1/200 999\n"); err != nil || v != 0.52 {
		t.Fatalf("load=%v err=%v", v, err)
	}
	if v, err := parseMilliCelsius("48500\n"); err != nil || v != 48.5 {
		t.Fatalf("temp=%v err=%v", v, err)
	}
}

func TestParseVMStat(t *testing.T) {
	out := strings.Join([]string{
		"Mach Virtual Memory Statistics: (page size of 16384 bytes)",
		"Pages free:                               10000.",
		"Pages active:                            100000.",
		"Pages inactive:                           50000.",
		"Pages wired down:                         20000.",
		"Pages occupied by compressor:             30000.",
	}, "\n")
	used, err := parseVMStat(out)
	if err != nil || used != 150000*16384 {
		t.Fatalf("fallback (no anonymous line): used=%d err=%v", used, err)
	}
	modern := out + "\nAnonymous pages:                         120000.\nPages purgeable:                          5000."
	used, err = parseVMStat(modern)
	// Activity Monitor formula: (anonymous - purgeable) + wired + compressed
	if err != nil || used != (120000-5000+20000+30000)*16384 {
		t.Fatalf("modern: used=%d err=%v", used, err)
	}
	if _, err := parseVMStat("Pages active: 1."); err == nil {
		t.Fatal("missing page size must fail")
	}
}

func TestDarwinSysctlDecodingSurvivesStrippedTrailingZero(t *testing.T) {
	load := make([]byte, 24)
	binary.LittleEndian.PutUint32(load[0:4], 1024)
	binary.LittleEndian.PutUint64(load[16:24], 2048)
	stripped := strings.TrimSuffix(string(load), "\x00")
	if v, ok := decodeLoadavg(stripped); !ok || v != 0.5 {
		t.Fatalf("load=%v ok=%v", v, ok)
	}
	boot := make([]byte, 16)
	binary.LittleEndian.PutUint64(boot[0:8], 1_700_000_000)
	if v, ok := decodeBoottimeSeconds(string(boot[:15])); !ok || v != 1_700_000_000 {
		t.Fatalf("boot=%v ok=%v", v, ok)
	}
	mem := make([]byte, 8)
	binary.LittleEndian.PutUint64(mem, 16<<30)
	if v, ok := decodeUint64(strings.TrimRight(string(mem), "\x00")); !ok || v != 16<<30 {
		t.Fatalf("mem=%v ok=%v", v, ok)
	}
}

func TestSanitizeDropsValuesTheBackendRejects(t *testing.T) {
	bad := Sample{
		CPUPercent:   ptr(140.0),
		Load1:        ptr(math.NaN()),
		CPUs:         ptr(0),
		MemTotal:     ptr(uint64(10)),
		MemUsed:      ptr(uint64(11)),
		DiskTotal:    ptr(uint64(10)),
		TemperatureC: ptr(400.0),
		UptimeS:      ptr(uint64(math.MaxUint64)),
	}
	got := Sanitize(bad)
	if got.V != Version || got.CPUPercent == nil || *got.CPUPercent != 100 {
		t.Fatalf("cpu clamp failed: %+v", got)
	}
	if got.Load1 != nil || got.CPUs != nil || got.MemTotal != nil || got.MemUsed != nil ||
		got.DiskTotal != nil || got.DiskUsed != nil || got.TemperatureC != nil || got.UptimeS != nil {
		t.Fatalf("invalid values survived: %+v", got)
	}
}

func TestWireFormatUsesOnlyAllowedKeys(t *testing.T) {
	data, err := json.Marshal(Sanitize(Sample{CPUPercent: ptr(12.34), MemTotal: ptr(uint64(2)), MemUsed: ptr(uint64(1))}))
	if err != nil {
		t.Fatal(err)
	}
	var decoded map[string]any
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatal(err)
	}
	allowed := map[string]bool{"v": true, "cpu_pct": true, "load1": true, "cpus": true, "mem_total": true, "mem_used": true, "disk_total": true, "disk_used": true, "temp_c": true, "uptime_s": true}
	for key := range decoded {
		if !allowed[key] {
			t.Fatalf("unexpected key %q", key)
		}
	}
	if decoded["cpu_pct"] != 12.3 || decoded["v"] != float64(1) {
		t.Fatalf("unexpected encoding: %s", data)
	}
}

func TestParseTopCPUUsesTheLastSample(t *testing.T) {
	out := "Processes: 512 total\nCPU usage: 30.00% user, 20.00% sys, 50.00% idle\n\nProcesses: 512 total\nCPU usage: 7.12% user, 10.40% sys, 82.48% idle\nSharedLibs: 1\n"
	got, ok := parseTopCPU(out)
	if !ok || got < 17.51 || got > 17.53 {
		t.Fatalf("cpu=%v ok=%v, want 17.52", got, ok)
	}
	if _, ok := parseTopCPU("nothing here"); ok {
		t.Fatal("expected no value")
	}
}

func TestDiskUsageMatchesDf(t *testing.T) {
	// df: 100 blocks, 30 free, 25 available to users -> Use% = 70 / (70 + 25) = 73.7%
	total, used, ok := diskUsage(100, 30, 25, 1024)
	if !ok || used != 70*1024 || total != 95*1024 {
		t.Fatalf("total=%d used=%d ok=%v", total, used, ok)
	}
	if _, _, ok := diskUsage(10, 20, 5, 1); ok {
		t.Fatal("free > blocks must be rejected")
	}
}
