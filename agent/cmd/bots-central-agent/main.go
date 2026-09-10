package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"syscall"

	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/app"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/config"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/enrollment"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/hostinfo"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/identity"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/logging"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/sequence"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/storage"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/transport"
)

var version = "0.1.0-dev"

const maxPairingTokenSize = 8 * 1024

func main() {
	var configPath string
	var showVersion bool
	var pairingTokenStdin bool
	flag.StringVar(&configPath, "config", "", "absolute path to the agent configuration file")
	flag.BoolVar(&showVersion, "version", false, "print agent version")
	flag.BoolVar(&pairingTokenStdin, "pairing-token-stdin", false, "read one-time pairing token from standard input")
	flag.Parse()
	if showVersion {
		fmt.Println(version)
		return
	}
	logger := logging.New(os.Stderr)
	if configPath == "" {
		logger.Error("agent startup failed", logging.ErrorField(fmt.Errorf("config is required")))
		os.Exit(2)
	}
	fileConfig, err := config.Load(configPath)
	if err != nil {
		logger.Error("agent startup failed", logging.ErrorField(err))
		os.Exit(2)
	}
	store, err := storage.NewFileStore(fileConfig.StateDir)
	if err != nil {
		logger.Error("agent startup failed", logging.ErrorField(err))
		os.Exit(2)
	}
	if err := store.Prepare(); err != nil {
		logger.Error("agent startup failed", logging.ErrorField(err))
		os.Exit(2)
	}
	localIdentity, err := identity.LoadOrCreate(store)
	if err != nil {
		logger.Error("agent startup failed", logging.ErrorField(err))
		os.Exit(2)
	}
	logger.Info("local device identity is ready", logging.Field{Key: "fingerprint", Value: localIdentity.Fingerprint()})
	enrollmentState, err := enrollment.New(store)
	if err != nil {
		logger.Error("agent startup failed", logging.ErrorField(err))
		os.Exit(2)
	}
	sequences, err := sequence.New(store)
	if err != nil {
		logger.Error("agent startup failed", logging.ErrorField(err))
		os.Exit(2)
	}
	httpTransport, err := transport.NewHTTP(transport.HTTPConfig{BackendBaseURL: fileConfig.BackendBaseURL, Signer: localIdentity, Sequence: sequences})
	if err != nil {
		logger.Error("agent startup failed", logging.ErrorField(err))
		os.Exit(2)
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if pairingTokenStdin {
		record, loadErr := enrollmentState.Load()
		if !pairingAllowed(record, loadErr) {
			logger.Error("agent startup failed", logging.ErrorField(errors.New("pairing input is allowed only before enrollment or after state loss")))
			os.Exit(2)
		}
		pairingToken, err := readPairingToken(os.Stdin)
		if err != nil {
			logger.Error("agent startup failed", logging.ErrorField(err))
			os.Exit(2)
		}
		enrollmentHost, err := hostinfo.SystemCollector().Collect()
		if err != nil {
			logger.Error("agent enrollment failed", logging.ErrorField(err))
			os.Exit(1)
		}
		agentVersion := version
		result, err := httpTransport.Enroll(ctx, pairingToken, transport.EnrollmentMetadata{Name: enrollmentHost.Hostname, Platform: enrollmentHost.Platform, AgentVersion: &agentVersion})
		pairingToken = ""
		if err != nil {
			logger.Error("agent enrollment failed", logging.ErrorField(err))
			os.Exit(1)
		}
		if err := enrollmentState.SaveEnrollment(enrollment.Record{DeviceID: result.DeviceID, Status: result.LifecycleStatus}); err != nil {
			logger.Error("agent enrollment failed", logging.ErrorField(err))
			os.Exit(1)
		}
		logger.Info("enrollment state persisted", logging.Field{Key: "device_id", Value: result.DeviceID}, logging.Field{Key: "status", Value: result.LifecycleStatus})
	}
	runner, err := app.New(app.Config{HeartbeatInterval: fileConfig.HeartbeatInterval, TransportTimeout: fileConfig.TransportTimeout, BackoffInitial: fileConfig.BackoffInitial, BackoffMax: fileConfig.BackoffMax, AgentVersion: version, CapabilityVersion: app.DefaultCapabilityVersion}, app.Dependencies{Collector: hostinfo.SystemCollector(), Enrollment: enrollmentState, Transport: httpTransport, Logger: logger})
	if err != nil {
		logger.Error("agent startup failed", logging.ErrorField(err))
		os.Exit(2)
	}
	if err := runner.Run(ctx); err != nil {
		logger.Error("agent stopped with an error", logging.ErrorField(err))
		os.Exit(1)
	}
	logger.Info("agent stopped")
}

func pairingAllowed(record enrollment.Record, err error) bool {
	return errors.Is(err, enrollment.ErrNotEnrolled) || (err == nil && record.Status == enrollment.StatusStateLost)
}

// readPairingToken retains the one-time token only in process memory. The CLI
// deliberately has no token-valued flag or config field, avoiding argv/config
// persistence and accidental logging.
func readPairingToken(reader io.Reader) (string, error) {
	data, err := io.ReadAll(io.LimitReader(reader, maxPairingTokenSize+1))
	if err != nil {
		return "", errors.New("pairing token input could not be read")
	}
	if len(data) > maxPairingTokenSize {
		return "", errors.New("pairing token input exceeds maximum size")
	}
	for len(data) > 0 && (data[len(data)-1] == '\n' || data[len(data)-1] == '\r') {
		data = data[:len(data)-1]
	}
	if len(data) == 0 {
		return "", errors.New("pairing token input is empty")
	}
	return string(data), nil
}
