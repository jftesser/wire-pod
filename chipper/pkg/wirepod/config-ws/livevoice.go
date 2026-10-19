package webserver

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"
)

const liveUnit = "vector-live.service"

var liveSystemctl = func(ctx context.Context, args ...string) ([]byte, error) {
	return exec.CommandContext(ctx, "/usr/bin/systemctl", args...).Output()
}

type liveHeartbeat struct {
	PID              int     `json:"pid"`
	Heartbeat        float64 `json:"heartbeat"`
	Ready            bool    `json:"ready"`
	Phase            string  `json:"phase"`
	Mode             string  `json:"mode"`
	Source           string  `json:"source"`
	Volume           int     `json:"volume"`
	MicrophoneActive bool    `json:"microphone_active"`
	Speaking         bool    `json:"speaking"`
	Elapsed          float64 `json:"elapsed_seconds"`
	Segments         int     `json:"speaker_segments_completed"`
}

func liveJSON(w http.ResponseWriter, code int, value interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(value)
}

func liveStatus(ctx context.Context) (map[string]interface{}, error) {
	raw, err := liveSystemctl(ctx, "show", liveUnit, "--property=ActiveState,SubState,MainPID,Result")
	if err != nil {
		return nil, err
	}
	properties := map[string]string{}
	for _, line := range strings.Split(string(raw), "\n") {
		pair := strings.SplitN(line, "=", 2)
		if len(pair) == 2 {
			properties[pair[0]] = pair[1]
		}
	}
	state := properties["ActiveState"]
	result := map[string]interface{}{
		"mode": "legacy", "phase": "off", "service_state": state,
		"ready": false, "microphone_active": false, "speaking": false,
		"source": "Vector wake-word requests", "requires_wake_phrase": true,
		"continuous_available": false,
		"continuous_reason":    "Continuous listening needs a working continuous microphone source. This robot's SDK feed currently returns a test signal.",
	}
	if state == "failed" || (properties["Result"] != "" && properties["Result"] != "success" && state == "inactive") {
		result["phase"] = "error"
		result["error"] = "Voice companion stopped with an error."
		return result, nil
	}
	if state != "active" && state != "activating" && state != "deactivating" {
		return result, nil
	}
	result["mode"], result["phase"] = "wake", "starting"
	if state == "deactivating" {
		result["phase"] = "stopping"
		return result, nil
	}
	filename := os.Getenv("VECTOR_LIVE_STATUS_FILE")
	if filename == "" {
		filename = "/run/vector-live-companion/status.json"
	}
	file, err := os.Open(filename)
	if err != nil {
		result["phase"] = "unverified"
		return result, nil
	}
	defer file.Close()
	var heartbeat liveHeartbeat
	err = json.NewDecoder(io.LimitReader(file, 65536)).Decode(&heartbeat)
	pid, _ := strconv.Atoi(properties["MainPID"])
	age := float64(time.Now().UnixNano())/1e9 - heartbeat.Heartbeat
	if err != nil || heartbeat.PID != pid || pid == 0 || age < -1 || age > 7 {
		result["phase"] = "unverified"
		return result, nil
	}
	result["phase"], result["ready"] = heartbeat.Phase, heartbeat.Ready
	result["microphone_active"], result["speaking"] = heartbeat.MicrophoneActive, heartbeat.Speaking
	result["volume"], result["elapsed_seconds"] = heartbeat.Volume, heartbeat.Elapsed
	result["speaker_segments_completed"] = heartbeat.Segments
	return result, nil
}

func liveMutationAllowed(r *http.Request) bool {
	if r.Method != http.MethodPost || r.Header.Get("X-Vector-Control") != "1" {
		return false
	}
	if r.Header.Get("Sec-Fetch-Site") == "cross-site" {
		return false
	}
	if origin := r.Header.Get("Origin"); origin != "" {
		parsed, err := url.Parse(origin)
		if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.Host != r.Host {
			return false
		}
	}
	return true
}

func handleLiveAdmin(w http.ResponseWriter, r *http.Request) {
	// These endpoints deliberately do not inherit the legacy API's wildcard CORS.
	if os.Getenv("VECTOR_LIVE_ADMIN") != "1" {
		liveJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "Voice controls are not enabled on this server."})
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 4*time.Second)
	defer cancel()
	endpoint := strings.TrimPrefix(r.URL.Path, "/api/vector-live/")
	if endpoint == "status" {
		if r.Method != http.MethodGet {
			w.Header().Set("Allow", "GET")
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		status, err := liveCombinedStatus(ctx)
		if err != nil {
			liveJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "Cannot read voice service status."})
			return
		}
		liveJSON(w, http.StatusOK, status)
		return
	}
	if endpoint != "start" && endpoint != "stop" && endpoint != "volume" && endpoint != "options" && endpoint != "expression" {
		http.NotFound(w, r)
		return
	}
	if r.Method != http.MethodPost {
		w.Header().Set("Allow", "POST")
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	if !liveMutationAllowed(r) {
		liveJSON(w, http.StatusForbidden, map[string]string{"error": "Use the voice controls on this server."})
		return
	}
	if !strings.HasPrefix(r.Header.Get("Content-Type"), "application/json") {
		liveJSON(w, http.StatusUnsupportedMediaType, map[string]string{"error": "Expected JSON."})
		return
	}
	if endpoint == "options" {
		var body struct {
			Boost            *int    `json:"boost_db"`
			Expressions      *string `json:"expressions"`
			NodDepth         *int    `json:"nod_depth"`
			NodInterval      *int    `json:"nod_interval"`
			LegacyAnimations *bool   `json:"legacy_animations"`
		}
		decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1024))
		decoder.DisallowUnknownFields()
		if err := decoder.Decode(&body); err != nil || (body.Boost == nil && body.Expressions == nil && body.NodDepth == nil && body.NodInterval == nil && body.LegacyAnimations == nil) ||
			(body.Boost != nil && *body.Boost != 0 && *body.Boost != 3 && *body.Boost != 6) ||
			(body.Expressions != nil && *body.Expressions != "off" && *body.Expressions != "eyes" && *body.Expressions != "head") ||
			(body.NodDepth != nil && (*body.NodDepth < 2 || *body.NodDepth > 20)) ||
			(body.NodInterval != nil && (*body.NodInterval < 4 || *body.NodInterval > 30)) || decoder.Decode(&struct{}{}) != io.EOF {
			liveJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid voice options. Nod depth2–20degrees; interval4–30seconds."})
			return
		}
		payload := map[string]interface{}{}
		if body.Boost != nil {
			payload["boost_db"] = *body.Boost
		}
		if body.Expressions != nil {
			payload["expressions"] = *body.Expressions
		}
		if body.NodDepth != nil {
			payload["nod_depth"] = *body.NodDepth
		}
		if body.NodInterval != nil {
			payload["nod_interval"] = *body.NodInterval
		}
		if body.LegacyAnimations != nil {
			payload["legacy_animations"] = *body.LegacyAnimations
		}
		raw, _ := json.Marshal(payload)
		liveMutationLock.Lock()
		defer liveMutationLock.Unlock()
		result, err := liveHostCall(ctx, http.MethodPost, "options", raw)
		if err != nil {
			liveJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "Voice options could not be saved."})
			return
		}
		liveJSON(w, http.StatusOK, result)
		return
	}
	if endpoint == "expression" {
		var body struct {
			Expression string `json:"expression"`
			Depth      *int   `json:"depth_degrees"`
		}
		decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1024))
		decoder.DisallowUnknownFields()
		allowed := map[string]bool{"nod": true, "blink": true, "happy": true, "veryHappy": true, "sad": true, "verySad": true, "angry": true, "frustrated": true, "dartingEyes": true, "confused": true, "thinking": true, "celebrate": true, "love": true}
		if err := decoder.Decode(&body); err != nil || !allowed[body.Expression] || body.Depth == nil || *body.Depth < 0 || *body.Depth > 20 || *body.Depth == 1 || (body.Expression != "nod" && *body.Depth != 0) || decoder.Decode(&struct{}{}) != io.EOF {
			liveJSON(w, http.StatusBadRequest, map[string]string{"error": "Choose a listed expression and valid nod depth."})
			return
		}
		raw, _ := json.Marshal(body)
		liveMutationLock.Lock()
		defer liveMutationLock.Unlock()
		result, err := liveHostCall(ctx, http.MethodPost, "expression", raw)
		if err != nil {
			liveJSON(w, http.StatusConflict, map[string]string{"error": "Expression unavailable or busy. Check Live readiness, enabled expressions, and robot state."})
			return
		}
		liveJSON(w, http.StatusAccepted, result)
		return
	}
	if endpoint == "volume" {
		var body struct {
			Volume *int `json:"volume"`
		}
		decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1024))
		decoder.DisallowUnknownFields()
		if err := decoder.Decode(&body); err != nil || body.Volume == nil || *body.Volume < 0 || *body.Volume > 100 {
			liveJSON(w, http.StatusBadRequest, map[string]string{"error": "Volume must be a whole number from 0 to 100."})
			return
		}
		if decoder.Decode(&struct{}{}) != io.EOF {
			liveJSON(w, http.StatusBadRequest, map[string]string{"error": "Expected one volume setting."})
			return
		}
		payload, _ := json.Marshal(body)
		liveMutationLock.Lock()
		defer liveMutationLock.Unlock()
		result, err := liveHostCall(ctx, http.MethodPost, "volume", payload)
		if err != nil {
			liveJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "Volume could not be saved. Check the voice controller."})
			return
		}
		liveJSON(w, http.StatusOK, result)
		return
	}
	var body struct {
		Mode string `json:"mode"`
	}
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1024))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&body); err != nil {
		liveJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid control request."})
		return
	}
	liveMutationLock.Lock()
	defer liveMutationLock.Unlock()
	if endpoint == "start" && body.Mode == "continuous" {
		liveHostStart(w, r, ctx)
		return
	}
	if endpoint == "start" && body.Mode != "wake" {
		liveJSON(w, http.StatusConflict, map[string]string{"error": "Continuous microphone input has not been configured. Choose the wake-word prototype explicitly."})
		return
	}
	if endpoint == "start" {
		if time.Now().Before(liveWakePendingUntil) {
			liveJSON(w, http.StatusAccepted, map[string]string{"action": "start", "state": "pending"})
			return
		}
		host, hostErr := liveHostCall(ctx, http.MethodGet, "status", nil)
		if hostErr == nil {
			active, _ := host["active"].(bool)
			rememberHost(active)
		}
		if hostMayBeActive() {
			liveJSON(w, http.StatusConflict, map[string]string{"error": "Stop the continuous voice session before starting another mode."})
			return
		}
		status, err := liveStatus(ctx)
		if err != nil {
			liveJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "Cannot read voice service status."})
			return
		}
		state := fmt.Sprint(status["service_state"])
		if state == "active" || state == "activating" {
			liveJSON(w, http.StatusOK, status)
			return
		}
		if state == "deactivating" {
			liveJSON(w, http.StatusConflict, map[string]string{"error": "Wait for the current session to finish closing."})
			return
		}
	}
	if _, err := liveSystemctl(ctx, endpoint, "--no-block", liveUnit); err != nil {
		liveJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "Voice control failed. Check the service log."})
		return
	}
	if endpoint == "stop" {
		liveWakePendingUntil = time.Time{}
		if _, err := liveHostCall(ctx, http.MethodPost, "stop", []byte(`{}`)); err != nil && hostMayBeActive() {
			liveJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "Wake-word voice stopped; the continuous controller is unreachable. Closure cannot yet be confirmed."})
			return
		}
	} else {
		// systemd --no-block can return before ActiveState changes. Reserve this
		// mode briefly so simultaneous browser requests cannot start both hosts.
		liveWakePendingUntil = time.Now().Add(15 * time.Second)
	}
	liveJSON(w, http.StatusAccepted, map[string]string{"action": endpoint, "state": "pending"})
}
