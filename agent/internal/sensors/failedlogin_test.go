package sensors

import (
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestFailedLoginRecognisesRealJournalLines(t *testing.T) {
	cases := map[string]string{
		`{"SYSLOG_IDENTIFIER":"gdm-password]","MESSAGE":"pam_unix(gdm-password:auth): authentication failure; logname= uid=0 euid=0 tty=/dev/tty1 ruser= rhost=  user=voide"}`: "gdm-password",
		`{"SYSLOG_IDENTIFIER":"sudo","MESSAGE":"pam_unix(sudo:auth): authentication failure; logname=voide uid=1000"}`:                                                         "sudo",
		`{"SYSLOG_IDENTIFIER":"sshd","MESSAGE":"Failed password for invalid user admin from 100.64.0.9 port 51544 ssh2"}`:                                                      "sshd",
		`{"SYSLOG_IDENTIFIER":"login","MESSAGE":"FAILED LOGIN 1 FROM tty2 FOR voide, Authentication failure"}`:                                                                 "login",
		`{"SYSLOG_IDENTIFIER":"sudo","MESSAGE":"voide : 3 incorrect password attempts ; TTY=pts/0 ; PWD=/home/voide"}`:                                                         "sudo",
		`{"SYSLOG_IDENTIFIER":"sudo","MESSAGE":[112,97,109,95,117,110,105,120,58,32,97,117,116,104,101,110,116,105,99,97,116,105,111,110,32,102,97,105,108,117,114,101]}`:      "sudo",
		// Not a failure, or not a watched program: ignored.
		`{"SYSLOG_IDENTIFIER":"sudo","MESSAGE":"pam_unix(sudo:session): session opened for user root"}`: "",
		`{"SYSLOG_IDENTIFIER":"cron","MESSAGE":"pam_unix(cron:auth): authentication failure"}`:          "",
		`{"SYSLOG_IDENTIFIER":"gdm-password]","MESSAGE":"gkr-pam: unlocked login keyring"}`:             "",
		`not json`: "",
	}
	for line, want := range cases {
		if got := FailedLogin([]byte(line)); got != want {
			t.Errorf("FailedLogin(%s) = %q, want %q", line[:40], got, want)
		}
	}
}

func TestWatcherReportsAtMostOncePerMinute(t *testing.T) {
	var reports atomic.Int32
	done := make(chan string, 4)
	now := time.Date(2026, 10, 22, 10, 0, 0, 0, time.UTC)
	watcher := &Watcher{Report: func(program string) { reports.Add(1); done <- program }, Now: func() time.Time { return now }}
	failure := `{"SYSLOG_IDENTIFIER":"gdm-password","MESSAGE":"pam_unix(gdm-password:auth): authentication failure"}`
	watcher.Scan(strings.NewReader(failure + "\n" + failure + "\n"))
	if program := <-done; program != "gdm-password" {
		t.Fatalf("program = %q", program)
	}
	now = now.Add(61 * time.Second)
	if !watcher.Feed([]byte(failure)) {
		t.Fatal("a failure a minute later must be reported")
	}
	<-done
	if reports.Load() != 2 {
		t.Fatalf("reports = %d, want 2", reports.Load())
	}
}
