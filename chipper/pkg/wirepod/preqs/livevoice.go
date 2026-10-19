package processreqs

// Live voice is opt-in: an active, private local companion must acknowledge a
// request before this handler consumes any audio. Otherwise normal STT runs.
import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"errors"
	"io"
	"net"
	"os"
	"path/filepath"
	"strings"
	"time"

	pb "github.com/digital-dream-labs/api/go/chipperpb"
	"github.com/kercre123/wire-pod/chipper/pkg/logger"
	"github.com/kercre123/wire-pod/chipper/pkg/vtt"
	sr "github.com/kercre123/wire-pod/chipper/pkg/wirepod/speechrequest"
	ttr "github.com/kercre123/wire-pod/chipper/pkg/wirepod/ttr"
)

func liveFrame(conn net.Conn, data []byte) error {
	if err := conn.SetWriteDeadline(time.Now().Add(250 * time.Millisecond)); err != nil {
		return err
	}
	var length [4]byte
	binary.BigEndian.PutUint32(length[:], uint32(len(data)))
	if _, err := io.Copy(conn, bytes.NewReader(length[:])); err != nil {
		return err
	}
	_, err := io.Copy(conn, bytes.NewReader(data))
	return err
}

func tryLiveVoice(req interface{}, speech *sr.SpeechRequest) bool {
	socket, selected := os.Getenv("VECTOR_LIVE_SOCKET"), os.Getenv("VECTOR_AUDIO_TAP_SERIAL")
	if socket == "" || !filepath.IsAbs(socket) || selected == "" || !strings.EqualFold(selected, speech.Device) {
		return false
	}
	conn, err := net.DialTimeout("unix", socket, 150*time.Millisecond)
	if err != nil {
		return false
	}
	defer conn.Close()
	kind := "intent"
	if speech.IsIG {
		kind = "intentgraph"
	}
	if speech.IsKG {
		kind = "knowledgegraph"
	}
	allowProbeHold := os.Getenv("VECTOR_LIVE_NATIVE_PROBE") == "1"
	header, _ := json.Marshal(map[string]interface{}{"device": speech.Device, "kind": kind, "sample_rate": 16000, "format": "pcm_s16le", "probe_hold_available": allowProbeHold})
	if err = liveFrame(conn, header); err != nil {
		return false
	}
	conn.SetReadDeadline(time.Now().Add(250 * time.Millisecond))
	var accepted [1]byte
	if _, err = io.ReadFull(conn, accepted[:]); err != nil || (accepted[0] != 1 && !(accepted[0] == 2 && allowProbeHold)) {
		return false
	}
	probeHold := accepted[0] == 2
	// The companion owns this request after acknowledgment. A mid-capture
	// failure cannot fall back to STT because the stream has been consumed.
	finish := func(failed bool) {
		if kg, ok := req.(*vtt.KnowledgeGraphRequest); ok {
			_ = kg.Stream.Send(&pb.KnowledgeGraphResponse{DeviceId: kg.Device, Session: kg.Session, CommandType: "NoResultCommand", SpokenText: ""})
		} else {
			intent := "intent_greeting_hello"
			if failed {
				intent = "intent_system_noaudio"
			}
			_, _ = ttr.IntentPass(req, intent, "", map[string]string{}, false)
		}
	}
	pcm := speech.FirstReq
	if speech.IsOpus {
		pcm = speech.DecodedMicData
	}
	if len(pcm) > 0 {
		err = liveFrame(conn, pcm)
	}
	if err == nil {
		if !probeHold {
			speech.DetectEndOfSpeech()
		}
		captureLimit := 20 * time.Second
		if probeHold {
			// Only the explicit native-mic diagnostic can test the bounded
			// 30-second firmware window. Ordinary live requests keep their limit.
			captureLimit = 40 * time.Second
		}
		deadline := time.Now().Add(captureLimit)
		complete := false
		for time.Now().Before(deadline) {
			var chunk []byte
			chunk, err = speech.GetNextStreamChunk()
			if err == io.EOF {
				err = nil
				complete = true
				break
			}
			if err != nil {
				break
			}
			if len(chunk) > 0 {
				err = liveFrame(conn, chunk)
			}
			if err != nil {
				break
			}
			if !probeHold {
				done, _ := speech.DetectEndOfSpeech()
				if done {
					complete = true
					break
				}
			}
		}
		if err == nil && !complete {
			err = errors.New("live capture time limit")
		}
	}
	if err == nil {
		err = liveFrame(conn, nil)
	}
	speech.Tap.Close()
	if err != nil {
		logger.Println("Live voice capture failed; original STT resumes on the next request.")
	}
	finish(err != nil)
	return true
}
