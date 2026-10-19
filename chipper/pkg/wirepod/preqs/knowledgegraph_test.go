package processreqs

import (
	"errors"
	"io"
	"testing"

	pb "github.com/digital-dream-labs/api/go/chipperpb"
	"github.com/kercre123/wire-pod/chipper/pkg/vtt"
	sr "github.com/kercre123/wire-pod/chipper/pkg/wirepod/speechrequest"
)

type emptyKGStream struct {
	liveTestStream
	response *pb.KnowledgeGraphResponse
}

func (s *emptyKGStream) Recv() (*pb.StreamingKnowledgeGraphRequest, error) { return nil, io.EOF }
func (s *emptyKGStream) Send(r *pb.KnowledgeGraphResponse) error           { s.response = r; return nil }

func TestEmptyKnowledgeRequestCompletesWithoutRobotOrProvider(t *testing.T) {
	previous := sttHandler
	defer func() { sttHandler = previous }()
	for _, failed := range []bool{false, true} {
		sttHandler = func(sr.SpeechRequest) (string, error) {
			if failed {
				return "", errors.New("recognition failed")
			}
			return " \n", nil
		}
		stream := &emptyKGStream{}
		req := &vtt.KnowledgeGraphRequest{Session: "session", Device: "robot", Stream: stream}
		streamingKG(req, sr.SpeechRequest{})
		if stream.response == nil || stream.response.CommandType != NoResult || stream.response.SpokenText != "" {
			t.Fatal("empty request was not completed without entering the SDK/LLM path")
		}
	}
}
