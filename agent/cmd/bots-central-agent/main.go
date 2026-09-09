package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/app"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/config"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/hostinfo"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/identity"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/logging"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/storage"
	"github.com/Voide-Kali/Bots-Central-V2/agent/internal/transport"
)

var version = "0.1.0-dev"

func main() {
	var configPath string
	var showVersion bool
	flag.StringVar(&configPath, "config", "", "absolute path to the agent configuration file")
	flag.BoolVar(&showVersion, "version", false, "print agent version")
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
	logger.Info("local device identity is ready")
	runner, err := app.New(app.Config{HeartbeatInterval: fileConfig.HeartbeatInterval, TransportTimeout: fileConfig.TransportTimeout, BackoffInitial: fileConfig.BackoffInitial, BackoffMax: fileConfig.BackoffMax, AgentVersion: version, CapabilityVersion: app.DefaultCapabilityVersion}, app.Dependencies{Collector: hostinfo.SystemCollector(), Identity: localIdentity, Transport: transport.Unavailable{}, Logger: logger})
	if err != nil {
		logger.Error("agent startup failed", logging.ErrorField(err))
		os.Exit(2)
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := runner.Run(ctx); err != nil {
		logger.Error("agent stopped with an error", logging.ErrorField(err))
		os.Exit(1)
	}
	logger.Info("agent stopped")
}
