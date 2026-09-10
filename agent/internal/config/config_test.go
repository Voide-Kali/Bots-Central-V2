package config

import "testing"

func TestParseValidConfig(t *testing.T) {
	config, err := Parse([]byte(`{"state_dir":"/var/lib/bots-central-agent","enrollment_url":"https://backend.example/enroll","heartbeat_url":"https://backend.example/heartbeat","heartbeat_interval":"30s","transport_timeout":"10s","backoff_initial":"1s","backoff_max":"1m"}`))
	if err != nil {
		t.Fatalf("Parse() error = %v", err)
	}
	if config.StateDir != "/var/lib/bots-central-agent" || config.EnrollmentURL != "https://backend.example/enroll" || config.HeartbeatURL != "https://backend.example/heartbeat" || config.HeartbeatInterval.String() != "30s" || config.BackoffMax.String() != "1m0s" {
		t.Fatalf("unexpected config: %#v", config)
	}
}

func TestParseFailsClosedForMalformedConfig(t *testing.T) {
	inputs := [][]byte{
		[]byte(`{"state_dir":"relative","enrollment_url":"https://backend.example/enroll","heartbeat_url":"https://backend.example/heartbeat","heartbeat_interval":"30s","transport_timeout":"10s","backoff_initial":"1s","backoff_max":"1m"}`),
		[]byte(`{"state_dir":"/state","enrollment_url":"https://backend.example/enroll","heartbeat_url":"https://backend.example/heartbeat","heartbeat_interval":"0s","transport_timeout":"10s","backoff_initial":"1s","backoff_max":"1m"}`),
		[]byte(`{"state_dir":"/state","enrollment_url":"https://backend.example/enroll","heartbeat_url":"https://backend.example/heartbeat","heartbeat_interval":"25s","transport_timeout":"10s","backoff_initial":"1s","backoff_max":"1m"}`),
		[]byte(`{"state_dir":"/state","enrollment_url":"http://backend.example/enroll","heartbeat_url":"https://backend.example/heartbeat","heartbeat_interval":"30s","transport_timeout":"10s","backoff_initial":"1s","backoff_max":"1m"}`),
		[]byte(`{"state_dir":"/state","enrollment_url":"https://backend.example/enroll","heartbeat_url":"https://backend.example/heartbeat","heartbeat_interval":"30s","transport_timeout":"10s","backoff_initial":"2m","backoff_max":"1m"}`),
		[]byte(`{"state_dir":"/state","enrollment_url":"https://backend.example/enroll","heartbeat_url":"https://backend.example/heartbeat","heartbeat_interval":"30s","transport_timeout":"10s","backoff_initial":"1s","backoff_max":"1m","pairing_token":"must-not-be-accepted"}`),
		[]byte(`{"state_dir":`),
	}
	for _, input := range inputs {
		if _, err := Parse(input); err == nil {
			t.Fatalf("Parse(%s) succeeded", input)
		}
	}
}
