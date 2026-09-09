// Package logging writes structured logs while redacting credential-shaped values.
package logging

import (
	"encoding/json"
	"fmt"
	"io"
	"net/url"
	"regexp"
	"strings"
	"sync"
	"time"
)

const Redacted = "[REDACTED]"

var sensitiveAssignment = regexp.MustCompile(`(?i)\b(authorization|token|secret|password|api[_-]?key|credential|private[_-]?key)\b\s*([:=])\s*("[^"]*"|'[^']*'|[^,\s]+)`)

type Field struct {
	Key   string
	Value any
}
type Logger struct {
	out io.Writer
	now func() time.Time
	mu  sync.Mutex
}

func New(out io.Writer) *Logger                         { return &Logger{out: out, now: time.Now} }
func (l *Logger) Info(message string, fields ...Field)  { l.log("info", message, fields...) }
func (l *Logger) Warn(message string, fields ...Field)  { l.log("warn", message, fields...) }
func (l *Logger) Error(message string, fields ...Field) { l.log("error", message, fields...) }
func ErrorField(err error) Field                        { return Field{Key: "error", Value: err} }

func (l *Logger) log(level, message string, fields ...Field) {
	record := map[string]any{"timestamp": l.now().UTC().Format(time.RFC3339Nano), "level": level, "message": sanitizeString(message)}
	for _, field := range fields {
		record[field.Key] = sanitizeValue(field.Key, field.Value)
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	_ = json.NewEncoder(l.out).Encode(record)
}

func sanitizeValue(key string, value any) any {
	if isSensitiveKey(key) {
		return Redacted
	}
	switch typed := value.(type) {
	case nil:
		return nil
	case string:
		return sanitizeString(typed)
	case error:
		return sanitizeString(typed.Error())
	case []byte:
		return Redacted
	case map[string]string:
		copy := make(map[string]string, len(typed))
		for childKey, childValue := range typed {
			copy[childKey] = fmt.Sprint(sanitizeValue(childKey, childValue))
		}
		return copy
	case map[string]any:
		copy := make(map[string]any, len(typed))
		for childKey, childValue := range typed {
			copy[childKey] = sanitizeValue(childKey, childValue)
		}
		return copy
	case []any:
		copy := make([]any, len(typed))
		for index, item := range typed {
			copy[index] = sanitizeValue("", item)
		}
		return copy
	case fmt.Stringer:
		return sanitizeString(typed.String())
	default:
		return value
	}
}

func isSensitiveKey(key string) bool {
	normalized := strings.ToLower(strings.NewReplacer("-", "_", " ", "_").Replace(key))
	for _, marker := range []string{"authorization", "token", "secret", "password", "api_key", "credential", "private_key"} {
		if strings.Contains(normalized, marker) {
			return true
		}
	}
	return false
}

func sanitizeString(value string) string {
	if parsed, err := url.Parse(value); err == nil && parsed.Scheme != "" && parsed.Host != "" {
		parsed.User = nil
		parsed.RawQuery = ""
		parsed.ForceQuery = false
		parsed.Fragment = ""
		return parsed.String()
	}
	return sensitiveAssignment.ReplaceAllString(value, "${1}${2}"+Redacted)
}
