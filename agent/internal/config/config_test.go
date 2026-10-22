package config

import "testing"

func TestParseValidConfig(t *testing.T) {
	config, err := Parse([]byte(`{"state_dir":"/var/lib/bots-central-agent","backend_base_url":"https://backend.example","heartbeat_interval":"30s","transport_timeout":"10s","backoff_initial":"1s","backoff_max":"1m"}`))
	if err != nil {
		t.Fatalf("Parse() error = %v", err)
	}
	if config.StateDir != "/var/lib/bots-central-agent" || config.BackendBaseURL != "https://backend.example" || config.HeartbeatInterval.String() != "30s" || config.BackoffMax.String() != "1m0s" {
		t.Fatalf("unexpected config: %#v", config)
	}
}

func TestParseFailsClosedForMalformedConfig(t *testing.T) {
	inputs := [][]byte{
		[]byte(`{"state_dir":"relative","backend_base_url":"https://backend.example","heartbeat_interval":"30s","transport_timeout":"10s","backoff_initial":"1s","backoff_max":"1m"}`),
		[]byte(`{"state_dir":"/state","backend_base_url":"https://backend.example","heartbeat_interval":"0s","transport_timeout":"10s","backoff_initial":"1s","backoff_max":"1m"}`),
		[]byte(`{"state_dir":"/state","backend_base_url":"https://backend.example","heartbeat_interval":"25s","transport_timeout":"10s","backoff_initial":"1s","backoff_max":"1m"}`),
		[]byte(`{"state_dir":"/state","backend_base_url":"http://backend.example","heartbeat_interval":"30s","transport_timeout":"10s","backoff_initial":"1s","backoff_max":"1m"}`),
		[]byte(`{"state_dir":"/state","backend_base_url":"https://backend.example/api/v1","heartbeat_interval":"30s","transport_timeout":"10s","backoff_initial":"1s","backoff_max":"1m"}`),
		[]byte(`{"state_dir":"/state","backend_base_url":"https://backend.example","heartbeat_interval":"30s","transport_timeout":"10s","backoff_initial":"2m","backoff_max":"1m"}`),
		[]byte(`{"state_dir":"/state","backend_base_url":"https://backend.example","heartbeat_interval":"30s","transport_timeout":"10s","backoff_initial":"1s","backoff_max":"1m","pairing_token":"must-not-be-accepted"}`),
		[]byte(`{"state_dir":`),
	}
	for _, input := range inputs {
		if _, err := Parse(input); err == nil {
			t.Fatalf("Parse(%s) succeeded", input)
		}
	}
}

func TestSensorsAreValidated(t *testing.T) {
	base := `{"state_dir":"/state","backend_base_url":"https://backend.example","heartbeat_interval":"30s","transport_timeout":"10s","backoff_initial":"1s","backoff_max":"1m",`
	config, err := Parse([]byte(base + `"sensors":["failed_login_photo"]}`))
	if err != nil || len(config.Sensors) != 1 || config.Sensors[0] != "failed_login_photo" {
		t.Fatalf("config=%+v err=%v", config, err)
	}
	for _, bad := range []string{`"sensors":["keylogger"]}`, `"sensors":["failed_login_photo","failed_login_photo"]}`} {
		if _, err := Parse([]byte(base + bad)); err == nil {
			t.Fatalf("expected rejection for %s", bad)
		}
	}
}
