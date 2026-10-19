package webserver

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

// The controller uses a private local Unix socket or an operator-created SSH
// Unix-socket forward. No arbitrary URLs or commands.
var liveHostCall = func(ctx context.Context, method, action string, body []byte) (map[string]interface{}, error) {
	path := os.Getenv("VECTOR_LIVE_HOST_SOCKET")
	if !strings.HasPrefix(path, "/") {
		return nil, errors.New("host controller is not configured")
	}
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	transport := &http.Transport{DisableKeepAlives: true,
		DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
			return (&net.Dialer{}).DialContext(ctx, "unix", path)
		}}
	defer transport.CloseIdleConnections()
	request, err := http.NewRequestWithContext(ctx, method, "http://local/"+action, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	request.Header.Set("Content-Type", "application/json")
	response, err := (&http.Client{Transport: transport}).Do(request)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return nil, errors.New("host control was refused")
	}
	var result map[string]interface{}
	err = json.NewDecoder(io.LimitReader(response.Body, 65536)).Decode(&result)
	return result, err
}

var liveHostMemory struct {
	sync.Mutex
	active bool
}

var liveMutationLock sync.Mutex
var liveWakePendingUntil time.Time // protected by liveMutationLock

func rememberHost(active bool) {
	_ = storeHostState(active)
}

func storeHostState(active bool) error {
	liveHostMemory.Lock()
	defer liveHostMemory.Unlock()
	liveHostMemory.active = active
	path := os.Getenv("VECTOR_LIVE_HOST_STATE_FILE")
	if path == "" {
		return nil
	}
	if !filepath.IsAbs(path) {
		return errors.New("host state path must be absolute")
	}
	value := "off\n"
	if active {
		value = "active\n"
	}
	if previous, err := os.ReadFile(path); err == nil && string(previous) == value {
		return nil
	}
	file, err := os.CreateTemp(filepath.Dir(path), ".host-state-")
	if err != nil {
		return err
	}
	defer os.Remove(file.Name())
	_, err = file.WriteString(value)
	if closeErr := file.Close(); err == nil {
		err = closeErr
	}
	if err != nil {
		return err
	}
	return os.Rename(file.Name(), path)
}

func hostMayBeActive() bool {
	liveHostMemory.Lock()
	defer liveHostMemory.Unlock()
	if path := os.Getenv("VECTOR_LIVE_HOST_STATE_FILE"); path != "" {
		value, err := os.ReadFile(path)
		if err == nil {
			return string(value) != "off\n"
		}
		if !os.IsNotExist(err) {
			return true // An unreadable state cannot establish that a session is off.
		}
	}
	return liveHostMemory.active
}

func liveCombinedStatus(ctx context.Context) (map[string]interface{}, error) {
	local, err := liveStatus(ctx)
	if err != nil {
		return nil, err
	}
	host, hostErr := liveHostCall(ctx, http.MethodGet, "status", nil)
	if hostErr != nil {
		if hostMayBeActive() {
			local["mode"], local["phase"] = "continuous", "unverified"
			local["ready"], local["microphone_active"], local["speaking"] = false, false, false
			local["host_active"], local["requires_wake_phrase"] = true, false
			local["error"] = "Voice controller is unreachable. Session closure cannot yet be confirmed."
		}
		return local, nil
	}
	active, _ := host["active"].(bool)
	rememberHost(active)
	local["continuous_available"], local["continuous_reason"] = host["continuous_available"], host["continuous_reason"]
	local["host_active"] = active
	for _, key := range []string{"configured_volume", "volume_available", "volume_pending", "controller_location", "boost_db", "expressions", "configured_options", "expressions_state", "expressions_error", "nod_depth", "nod_interval", "legacy_animations", "animation_catalog", "animation_error", "last_expression", "voice_policy", "voice_name", "voice_fallback_reason", "autonomy", "autonomy_pending", "motion", "motor_action", "motor_actions_completed"} {
		if value, ok := host[key]; ok {
			local[key] = value
		}
	}
	if !active && local["mode"] == "legacy" {
		local["volume"] = host["volume"]
	}
	if active {
		delete(local, "error")
		for _, key := range []string{"mode", "phase", "ready", "source", "requires_wake_phrase", "microphone_active", "speaking", "volume", "elapsed_seconds", "speaker_segments_completed", "error"} {
			if value, ok := host[key]; ok {
				local[key] = value
			}
		}
		if state := local["service_state"]; state == "active" || state == "activating" || state == "deactivating" {
			local["phase"], local["ready"] = "conflict", false
			local["error"] = "Both voice companions are running. Stop conversation before restarting one mode."
		}
	} else if host["phase"] == "error" && local["service_state"] != "active" && local["service_state"] != "activating" {
		local["phase"], local["error"] = "error", host["error"]
	}
	return local, nil
}

func liveHostStart(w http.ResponseWriter, r *http.Request, ctx context.Context) {
	if time.Now().Before(liveWakePendingUntil) {
		liveJSON(w, http.StatusConflict, map[string]string{"error": "The wake-word companion is starting. Stop it before changing mode."})
		return
	}
	host, err := liveHostCall(ctx, http.MethodGet, "status", nil)
	if err != nil || host["continuous_available"] != true {
		liveJSON(w, http.StatusConflict, map[string]string{"error": "Continuous microphone input is not configured or the voice controller is unavailable."})
		return
	}
	local, err := liveStatus(ctx)
	if err != nil {
		liveJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "Cannot verify the Pi voice companion is off."})
		return
	}
	if local["service_state"] != "inactive" && local["service_state"] != "failed" {
		liveJSON(w, http.StatusConflict, map[string]string{"error": "Stop the wake-word prototype before starting continuous mode."})
		return
	}
	// Preserve uncertain remote state across a wire-pod restart. Reserve before
	// sending Start: a timed-out POST may still have reached the controller.
	if err := storeHostState(true); err != nil {
		liveJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "Cannot preserve host session state; no start was sent."})
		return
	}
	if _, err := liveHostCall(ctx, http.MethodPost, "start", []byte(`{"mode":"continuous"}`)); err != nil {
		liveJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "Voice start failed. Check the local controller."})
		return
	}
	rememberHost(true)
	liveJSON(w, http.StatusAccepted, map[string]string{"action": "start", "state": "pending"})
}
