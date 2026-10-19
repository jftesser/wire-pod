package processreqs

import (
	"encoding/json"
	"os"
	"testing"

	"github.com/kercre123/wire-pod/chipper/pkg/vars"
	"github.com/kercre123/wire-pod/chipper/pkg/vtt"
	ttr "github.com/kercre123/wire-pod/chipper/pkg/wirepod/ttr"
)

// This integration check reads the actually installed control definitions, but
// substitutes a harmless executable so no paid session or hardware is started.
func TestInstalledLiveControlsMatchObservedTranscripts(t *testing.T) {
	path := os.Getenv("VECTOR_CONTROL_TEST_FILE")
	if path == "" {
		t.Skip("set VECTOR_CONTROL_TEST_FILE to the installed customIntents.json")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var installed []vars.CustomIntent
	if err = json.Unmarshal(data, &installed); err != nil {
		t.Fatal(err)
	}
	previous, existed := vars.CustomIntents, vars.CustomIntentsExist
	defer func() { vars.CustomIntents, vars.CustomIntentsExist = previous, existed }()
	vars.CustomIntents = nil
	for _, intent := range installed {
		if intent.Name == "Vector live conversation" || intent.Name == "End Vector live conversation" {
			intent.Exec, intent.ExecArgs = "/usr/bin/true", nil
			vars.CustomIntents = append(vars.CustomIntents, intent)
		}
	}
	if len(vars.CustomIntents) != 2 {
		t.Fatal("both live controls must be installed")
	}
	vars.CustomIntentsExist = true
	for _, text := range []string{"conversation mode", "conversation man", "end our conversation", "and our conversation"} {
		stream := &liveTestStream{}
		req := &vtt.IntentRequest{Device: "robot", Stream: stream}
		if !ttr.ProcessTextAll(req, text, nil, false) || stream.response == nil || stream.response.IntentResult.Action != "intent_greeting_hello" {
			t.Fatalf("%q did not complete through a custom control", text)
		}
	}
}
