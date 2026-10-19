package audiotap

import (
	"encoding/binary"
	"encoding/json"
	"io"
	"net"
	"path/filepath"
	"testing"
	"time"
)

func readFrame(t *testing.T, c net.Conn) []byte {
	t.Helper()
	c.SetReadDeadline(time.Now().Add(time.Second))
	var n uint32
	if err := binary.Read(c, binary.BigEndian, &n); err != nil {
		t.Fatal(err)
	}
	if n > 128*1024 {
		t.Fatal("oversized frame")
	}
	b := make([]byte, n)
	if _, err := io.ReadFull(c, b); err != nil {
		t.Fatal(err)
	}
	return b
}

func TestDisabledWithoutExplicitRobot(t *testing.T) {
	t.Setenv("VECTOR_AUDIO_TAP_SOCKET", "/tmp/missing.sock")
	t.Setenv("VECTOR_AUDIO_TAP_SERIAL", "")
	if New("robot", "session", "intent") != nil {
		t.Fatal("capture enabled without robot selection")
	}
	t.Setenv("VECTOR_AUDIO_TAP_SERIAL", "another-robot")
	if New("robot", "session", "intent") != nil {
		t.Fatal("captured a different robot")
	}
}

func TestFramingCopiesAudioAndTerminates(t *testing.T) {
	path := filepath.Join(t.TempDir(), "tap.sock")
	l, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	t.Setenv("VECTOR_AUDIO_TAP_SOCKET", path)
	t.Setenv("VECTOR_AUDIO_TAP_SERIAL", "robot")
	c := New("robot", "session", "intentgraph")
	pcm := []byte{1, 0, 2, 0}
	c.Send(pcm)
	pcm[0] = 99
	c.Close()
	c.Close()
	conn, err := l.Accept()
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	var h Header
	if err := json.Unmarshal(readFrame(t, conn), &h); err != nil {
		t.Fatal(err)
	}
	if h.Rate != 16000 || h.Device != "robot" {
		t.Fatalf("invalid header: %+v", h)
	}
	if got := readFrame(t, conn); len(got) != 4 || got[0] != 1 {
		t.Fatal("audio was not copied correctly")
	}
	if len(readFrame(t, conn)) != 0 {
		t.Fatal("missing end marker")
	}
	select {
	case <-c.done:
	case <-time.After(time.Second):
		t.Fatal("capture did not finish")
	}
}

func TestMissingObserverNeverBlocksRecognition(t *testing.T) {
	t.Setenv("VECTOR_AUDIO_TAP_SOCKET", filepath.Join(t.TempDir(), "missing.sock"))
	t.Setenv("VECTOR_AUDIO_TAP_SERIAL", "robot")
	c := New("robot", "session", "intent")
	start := time.Now()
	for i := 0; i < 1000; i++ {
		c.Send(make([]byte, 320))
	}
	c.Close()
	if time.Since(start) > time.Second {
		t.Fatal("missing observer blocked capture")
	}
	select {
	case <-c.done:
	case <-time.After(time.Second):
		t.Fatal("writer remained running")
	}
}
