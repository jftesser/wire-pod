package webserver

import (
	"context"
	"errors"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func fakeHost(t *testing.T, active bool) *[]string {
	t.Helper()
	previous := liveHostCall
	calls := []string{}
	liveHostCall = func(ctx context.Context, method, action string, body []byte) (map[string]interface{}, error) {
		calls = append(calls, method+" "+action)
		return map[string]interface{}{"active": active, "continuous_available": true,
			"mode": "continuous", "phase": "ready", "ready": active,
			"microphone_active": active, "requires_wake_phrase": false, "source": "Host microphone: offline test"}, nil
	}
	t.Cleanup(func() { liveHostCall = previous; rememberHost(false) })
	return &calls
}

func TestHostAdminReflectsContinuousAndRefusesParallelWake(t *testing.T) {
	calls := fakeLiveService(t, "inactive")
	fakeHost(t, true)
	status, err := liveCombinedStatus(context.Background())
	if err != nil || status["mode"] != "continuous" || status["ready"] != true || status["requires_wake_phrase"] != false {
		t.Fatal(status, err)
	}
	w := httptest.NewRecorder()
	handleLiveAdmin(w, controlRequest("POST", "start", `{"mode":"wake"}`))
	if w.Code != http.StatusConflict || len(*calls) != 1 {
		t.Fatal("parallel wake session was not refused", w.Code, *calls)
	}
}

func TestHostAdminOnlyStartsWhenPiOffAndStopTargetsBoth(t *testing.T) {
	calls := fakeLiveService(t, "inactive")
	hostCalls := fakeHost(t, false)
	w := httptest.NewRecorder()
	handleLiveAdmin(w, controlRequest("POST", "start", `{"mode":"continuous"}`))
	if w.Code != http.StatusAccepted || (*hostCalls)[1] != "POST start" || len(*calls) != 1 {
		t.Fatal(w.Code, *calls, *hostCalls)
	}
	w = httptest.NewRecorder()
	handleLiveAdmin(w, controlRequest("POST", "stop", `{}`))
	if w.Code != http.StatusAccepted || (*calls)[1] != "stop --no-block vector-live.service" || (*hostCalls)[2] != "POST stop" {
		t.Fatal(w.Code, *calls, *hostCalls)
	}
}

func TestLostHostBridgeNeverClaimsOffOrReady(t *testing.T) {
	fakeLiveService(t, "inactive")
	fakeHost(t, true)
	_, _ = liveCombinedStatus(context.Background())
	liveHostCall = func(context.Context, string, string, []byte) (map[string]interface{}, error) {
		return nil, errors.New("offline bridge failure")
	}
	status, err := liveCombinedStatus(context.Background())
	if err != nil || status["phase"] != "unverified" || status["mode"] != "continuous" || status["ready"] != false {
		t.Fatal(status, err)
	}
	w := httptest.NewRecorder()
	handleLiveAdmin(w, controlRequest("POST", "stop", `{}`))
	if w.Code != http.StatusServiceUnavailable {
		t.Fatal("unconfirmed remote stop was reported as success", w.Code)
	}
}

func TestUnconfirmedHostStateSurvivesServerRestart(t *testing.T) {
	fakeLiveService(t, "inactive")
	path := filepath.Join(t.TempDir(), "host-state")
	t.Setenv("VECTOR_LIVE_HOST_STATE_FILE", path)
	if err := storeHostState(true); err != nil {
		t.Fatal(err)
	}
	liveHostMemory.active = false // Simulate a fresh wire-pod process.
	if !hostMayBeActive() {
		t.Fatal("restart lost uncertainty about the remote paid session")
	}
	info, err := os.Stat(path)
	if err != nil || info.Mode().Perm() != 0600 {
		t.Fatal(info, err)
	}
	rememberHost(false)
	if hostMayBeActive() {
		t.Fatal("confirmed remote off did not clear state")
	}
}

func TestHostTransportUsesPrivateUnixSocket(t *testing.T) {
	path := filepath.Join(t.TempDir(), "control.sock")
	listener, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" || r.URL.Path != "/stop" {
			t.Error("unexpected controller request", r.Method, r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"action":"stop","state":"pending"}`))
	})}
	go server.Serve(listener)
	t.Cleanup(func() { _ = server.Close() })
	t.Setenv("VECTOR_LIVE_HOST_SOCKET", path)
	result, err := liveHostCall(context.Background(), "POST", "stop", []byte(`{}`))
	if err != nil || result["action"] != "stop" {
		t.Fatal(result, err)
	}
}
