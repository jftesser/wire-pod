package webserver

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func fakeLiveService(t *testing.T, state string) *[]string {
	t.Helper()
	previous := liveSystemctl
	calls := []string{}
	liveSystemctl = func(ctx context.Context, args ...string) ([]byte, error) {
		calls = append(calls, strings.Join(args, " "))
		return []byte("ActiveState=" + state + "\nMainPID=123\nResult=success\n"), nil
	}
	t.Cleanup(func() { liveSystemctl = previous })
	t.Setenv("VECTOR_LIVE_ADMIN", "1")
	t.Setenv("VECTOR_LIVE_HOST_SOCKET", "")
	t.Setenv("VECTOR_LIVE_HOST_STATE_FILE", "")
	rememberHost(false)
	liveWakePendingUntil = time.Time{}
	t.Setenv("VECTOR_LIVE_STATUS_FILE", filepath.Join(t.TempDir(), "status.json"))
	return &calls
}

func controlRequest(method, endpoint, body string) *http.Request {
	r := httptest.NewRequest(method, "http://pi:8080/api/vector-live/"+endpoint, strings.NewReader(body))
	r.Header.Set("Content-Type", "application/json")
	r.Header.Set("X-Vector-Control", "1")
	r.Header.Set("Origin", "http://pi:8080")
	return r
}

func TestLiveAdminRejectsCrossOriginAndGETMutations(t *testing.T) {
	calls := fakeLiveService(t, "inactive")
	for _, method := range []string{"POST", "GET"} {
		r := controlRequest(method, "start", `{"mode":"wake"}`)
		r.Header.Set("Origin", "https://unrelated.example")
		w := httptest.NewRecorder()
		handleLiveAdmin(w, r)
		if w.Code != http.StatusForbidden && w.Code != http.StatusMethodNotAllowed {
			t.Fatal(w.Code)
		}
	}
	if len(*calls) != 0 {
		t.Fatal("rejected request touched the service")
	}
}

func TestLiveAdminNeverStartsUnavailableContinuousMode(t *testing.T) {
	calls := fakeLiveService(t, "inactive")
	w := httptest.NewRecorder()
	handleLiveAdmin(w, controlRequest("POST", "start", `{"mode":"continuous"}`))
	if w.Code != http.StatusConflict || len(*calls) != 0 {
		t.Fatal("continuous start was not refused")
	}
}

func TestLiveAdminStartIsIdempotentAndStopUsesFixedUnit(t *testing.T) {
	calls := fakeLiveService(t, "active")
	w := httptest.NewRecorder()
	handleLiveAdmin(w, controlRequest("POST", "start", `{"mode":"wake"}`))
	if w.Code != http.StatusOK || len(*calls) != 1 || !strings.HasPrefix((*calls)[0], "show ") {
		t.Fatal("duplicate start")
	}
	w = httptest.NewRecorder()
	handleLiveAdmin(w, controlRequest("POST", "stop", `{}`))
	if w.Code != http.StatusAccepted || (*calls)[1] != "stop --no-block vector-live.service" {
		t.Fatal("unexpected stop command")
	}
}

func TestLiveAdminRequiresFreshMatchingHeartbeatBeforeReady(t *testing.T) {
	fakeLiveService(t, "active")
	path := os.Getenv("VECTOR_LIVE_STATUS_FILE")
	for _, test := range []struct {
		pid   int
		age   float64
		ready bool
	}{{122, 0, false}, {123, 30, false}, {123, 0, true}} {
		heartbeat := liveHeartbeat{PID: test.pid, Heartbeat: float64(time.Now().UnixNano())/1e9 - test.age, Ready: true, Phase: "ready", MicrophoneActive: true}
		data, _ := json.Marshal(heartbeat)
		if err := os.WriteFile(path, data, 0600); err != nil {
			t.Fatal(err)
		}
		result, err := liveStatus(context.Background())
		if err != nil || result["ready"] != test.ready || result["microphone_active"] != test.ready {
			t.Fatal(result, err)
		}
	}
}

func TestLiveVolumeValidatesAndForwardsWithoutStartingVoice(t *testing.T) {
	calls := fakeLiveService(t, "inactive")
	previous := liveHostCall
	t.Cleanup(func() { liveHostCall = previous })
	forwarded := 0
	liveHostCall = func(ctx context.Context, method, action string, body []byte) (map[string]interface{}, error) {
		if method != "POST" || action != "volume" {
			t.Fatal(method, action)
		}
		var settings struct {
			Volume int `json:"volume"`
		}
		if err := json.Unmarshal(body, &settings); err != nil {
			t.Fatal(err)
		}
		forwarded++
		return map[string]interface{}{"volume": settings.Volume, "saved": true}, nil
	}
	for _, body := range []string{`{"volume":0}`, `{"volume":100}`, `{"volume":80}`} {
		w := httptest.NewRecorder()
		handleLiveAdmin(w, controlRequest("POST", "volume", body))
		if w.Code != http.StatusOK {
			t.Fatal(w.Code, w.Body.String())
		}
	}
	if forwarded != 3 || len(*calls) != 0 {
		t.Fatal("volume opened voice or missed forwarding")
	}
	for _, body := range []string{`{}`, `{"volume":null}`, `{"volume":true}`, `{"volume":2.5}`, `{"volume":-1}`, `{"volume":101}`, `{"volume":80,"mode":"continuous"}`, `{"volume":80} {}`} {
		w := httptest.NewRecorder()
		handleLiveAdmin(w, controlRequest("POST", "volume", body))
		if w.Code != http.StatusBadRequest {
			t.Fatal(body, w.Code)
		}
	}
	r := controlRequest("POST", "volume", `{"volume":80}`)
	r.Header.Set("Origin", "https://elsewhere.example")
	w := httptest.NewRecorder()
	handleLiveAdmin(w, r)
	if w.Code != http.StatusForbidden || forwarded != 3 {
		t.Fatal("invalid volume request reached controller")
	}
}

func TestLiveOptionsAreBoundedAndDoNotStartVoice(t *testing.T) {
	calls := fakeLiveService(t, "inactive")
	previous := liveHostCall
	t.Cleanup(func() { liveHostCall = previous })
	forwarded := 0
	liveHostCall = func(ctx context.Context, method, action string, body []byte) (map[string]interface{}, error) {
		if action != "options" || method != "POST" {
			t.Fatal(action, method)
		}
		forwarded++
		return map[string]interface{}{"saved": true}, nil
	}
	for _, body := range []string{`{"boost_db":0}`, `{"boost_db":6,"expressions":"head"}`, `{"expressions":"off"}`} {
		w := httptest.NewRecorder()
		handleLiveAdmin(w, controlRequest("POST", "options", body))
		if w.Code != http.StatusOK {
			t.Fatal(body, w.Code, w.Body.String())
		}
	}
	for _, body := range []string{`{}`, `{"boost_db":9}`, `{"boost_db":true}`, `{"expressions":"roam"}`, `{"volume":100}`, `{"boost_db":6} {}`} {
		w := httptest.NewRecorder()
		handleLiveAdmin(w, controlRequest("POST", "options", body))
		if w.Code != http.StatusBadRequest {
			t.Fatal(body, w.Code)
		}
	}
	r := controlRequest("POST", "options", `{"boost_db":6}`)
	r.Header.Set("Origin", "http://elsewhere.example")
	w := httptest.NewRecorder()
	handleLiveAdmin(w, r)
	if w.Code != http.StatusForbidden || forwarded != 3 || len(*calls) != 0 {
		t.Fatal("options bypassed validation or started voice")
	}
}

func TestGestureOptionsAndPreviewValidateWithoutStartingSession(t *testing.T) {
	calls := fakeLiveService(t, "inactive")
	previous := liveHostCall
	t.Cleanup(func() { liveHostCall = previous })
	forwarded := 0
	liveHostCall = func(ctx context.Context, method, action string, body []byte) (map[string]interface{}, error) {
		if method != "POST" || (action != "options" && action != "expression") {
			t.Fatal(method, action)
		}
		forwarded++
		return map[string]interface{}{"status": "accepted"}, nil
	}
	for _, test := range []struct {
		endpoint, body string
		code           int
	}{
		{"options", `{"nod_depth":2,"nod_interval":30,"legacy_animations":false}`, 200},
		{"options", `{"nod_depth":20,"nod_interval":4,"legacy_animations":true}`, 200},
		{"options", `{"nod_depth":21}`, 400}, {"options", `{"nod_depth":true}`, 400},
		{"options", `{"nod_interval":3}`, 400}, {"options", `{"legacy_animations":"true"}`, 400},
		{"expression", `{"expression":"happy","depth_degrees":0}`, 202},
		{"expression", `{"expression":"nod","depth_degrees":20}`, 202},
		{"expression", `{"expression":"nod","depth_degrees":21}`, 400},
		{"expression", `{"expression":"blink","depth_degrees":8}`, 400},
		{"expression", `{"expression":"arbitrary","depth_degrees":0}`, 400},
		{"expression", `{"expression":"happy","depth_degrees":0,"loops":100}`, 400},
	} {
		w := httptest.NewRecorder()
		handleLiveAdmin(w, controlRequest("POST", test.endpoint, test.body))
		if w.Code != test.code {
			t.Fatal(test.body, w.Code, w.Body.String())
		}
	}
	r := controlRequest("POST", "expression", `{"expression":"happy","depth_degrees":0}`)
	r.Header.Set("Origin", "http://elsewhere.example")
	w := httptest.NewRecorder()
	handleLiveAdmin(w, r)
	if w.Code != 403 || forwarded != 4 || len(*calls) != 0 {
		t.Fatal("gesture mutation bypassed validation or started voice")
	}
}
