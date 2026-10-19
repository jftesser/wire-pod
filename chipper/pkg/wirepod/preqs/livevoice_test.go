package processreqs

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"io"
	"net"
	"path/filepath"
	"testing"
	"time"

	pb "github.com/digital-dream-labs/api/go/chipperpb"
	"github.com/kercre123/wire-pod/chipper/pkg/vtt"
	sr "github.com/kercre123/wire-pod/chipper/pkg/wirepod/speechrequest"
	"google.golang.org/grpc/metadata"
)

type liveTestStream struct {
	received int
	response *pb.IntentResponse
	chunks   [][]byte
}

func (s *liveTestStream) Recv() (*pb.StreamingIntentRequest, error) {
	s.received++
	if len(s.chunks) == 0 {
		return nil, io.EOF
	}
	chunk := s.chunks[0]
	s.chunks = s.chunks[1:]
	return &pb.StreamingIntentRequest{InputAudio: chunk}, nil
}
func (s *liveTestStream) Send(r *pb.IntentResponse) error { s.response = r; return nil }
func (s *liveTestStream) SetHeader(metadata.MD) error     { return nil }
func (s *liveTestStream) SendHeader(metadata.MD) error    { return nil }
func (s *liveTestStream) SetTrailer(metadata.MD)          {}
func (s *liveTestStream) Context() context.Context        { return context.Background() }
func (s *liveTestStream) SendMsg(interface{}) error       { return nil }
func (s *liveTestStream) RecvMsg(interface{}) error       { return nil }

func TestLiveCompanionAbsentLeavesRequestUnread(t *testing.T) {
	t.Setenv("VECTOR_LIVE_SOCKET", filepath.Join(t.TempDir(), "missing.sock"))
	t.Setenv("VECTOR_AUDIO_TAP_SERIAL", "robot")
	stream := &liveTestStream{}
	speech := sr.SpeechRequest{Device: "robot", Stream: stream}
	if tryLiveVoice(nil, &speech) {
		t.Fatal("handled request without companion")
	}
	if stream.received != 0 {
		t.Fatal("consumed request before companion accepted")
	}
}

func TestLiveCompanionReceivesFirstPCMAndCompletion(t *testing.T) {
	path := filepath.Join(t.TempDir(), "live.sock")
	listener, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	t.Setenv("VECTOR_LIVE_SOCKET", path)
	t.Setenv("VECTOR_AUDIO_TAP_SERIAL", "robot")
	done := make(chan error, 1)
	go func() {
		conn, err := listener.Accept()
		if err != nil {
			done <- err
			return
		}
		defer conn.Close()
		conn.SetDeadline(time.Now().Add(2 * time.Second))
		read := func() ([]byte, error) {
			var n uint32
			if err := binary.Read(conn, binary.BigEndian, &n); err != nil {
				return nil, err
			}
			b := make([]byte, n)
			_, err := io.ReadFull(conn, b)
			return b, err
		}
		if _, err = read(); err != nil {
			done <- err
			return
		}
		if _, err = conn.Write([]byte{1}); err != nil {
			done <- err
			return
		}
		pcm, err := read()
		if err == nil && (len(pcm) != 2 || pcm[0] != 1) {
			err = io.ErrUnexpectedEOF
		}
		if err == nil {
			var end []byte
			end, err = read()
			if len(end) != 0 {
				err = io.ErrUnexpectedEOF
			}
		}
		done <- err
	}()
	stream := &liveTestStream{}
	speech := sr.SpeechRequest{Device: "robot", FirstReq: []byte{1, 0}, Stream: stream}
	request := &vtt.IntentRequest{Device: "robot", Stream: stream}
	if !tryLiveVoice(request, &speech) {
		t.Fatal("companion did not accept")
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	if stream.response == nil || !stream.response.IsFinal {
		t.Fatal("native request was not completed")
	}
}

func TestNativeProbeCanReadPastServerSpeechCutoffOnlyWhenEnabled(t *testing.T) {
	path := filepath.Join(t.TempDir(), "native.sock")
	listener, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	t.Setenv("VECTOR_LIVE_SOCKET", path)
	t.Setenv("VECTOR_AUDIO_TAP_SERIAL", "robot")
	t.Setenv("VECTOR_LIVE_NATIVE_PROBE", "1")
	done := make(chan error, 1)
	go func() {
		conn, err := listener.Accept()
		if err != nil {
			done <- err
			return
		}
		defer conn.Close()
		conn.SetDeadline(time.Now().Add(2 * time.Second))
		read := func() ([]byte, error) {
			var size uint32
			if err := binary.Read(conn, binary.BigEndian, &size); err != nil {
				return nil, err
			}
			data := make([]byte, size)
			_, err := io.ReadFull(conn, data)
			return data, err
		}
		header, err := read()
		var info map[string]interface{}
		if err == nil {
			err = json.Unmarshal(header, &info)
		}
		if err == nil && info["probe_hold_available"] != true {
			err = io.ErrUnexpectedEOF
		}
		if err != nil {
			done <- err
			return
		}
		_, err = conn.Write([]byte{2})
		total := 0
		for err == nil {
			var pcm []byte
			pcm, err = read()
			if len(pcm) == 0 {
				break
			}
			total += len(pcm)
		}
		if err == nil && total != 640 {
			err = io.ErrUnexpectedEOF
		}
		done <- err
	}()
	stream := &liveTestStream{chunks: [][]byte{make([]byte, 320), make([]byte, 320)}}
	// A nil VAD deliberately proves the probe never invokes speech-end detection.
	speech := sr.SpeechRequest{Device: "robot", Stream: stream}
	request := &vtt.IntentRequest{Device: "robot", Stream: stream}
	if !tryLiveVoice(request, &speech) {
		t.Fatal("diagnostic was not accepted")
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	if stream.received != 3 || stream.response == nil || !stream.response.IsFinal {
		t.Fatal("capture did not reach source EOF and complete normally")
	}
}
