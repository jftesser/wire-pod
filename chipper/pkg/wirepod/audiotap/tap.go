// Package audiotap mirrors decoded voice requests to an opt-in local observer.
// It never reads the robot stream itself and cannot block normal recognition.
package audiotap

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"io"
	"net"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

type Header struct {
	Device  string `json:"device"`
	Session string `json:"session"`
	Kind    string `json:"kind"`
	Rate    int    `json:"sample_rate"`
	Format  string `json:"format"`
}

type Capture struct {
	mu     sync.Mutex
	closed bool
	failed bool
	frames chan []byte
	done   chan struct{}
}

// New is disabled unless both a Unix socket and an explicit robot are selected.
func New(device, session, kind string) *Capture {
	socket := os.Getenv("VECTOR_AUDIO_TAP_SOCKET")
	selected := os.Getenv("VECTOR_AUDIO_TAP_SERIAL")
	if socket == "" || !filepath.IsAbs(socket) || selected == "" || !strings.EqualFold(selected, device) {
		return nil
	}
	c := &Capture{frames: make(chan []byte, 64), done: make(chan struct{})}
	go c.write(socket, Header{device, session, kind, 16000, "pcm_s16le"})
	return c
}

func (c *Capture) Send(pcm []byte) {
	if c == nil || len(pcm) == 0 {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed || c.failed {
		return
	}
	if len(pcm) > 128*1024 || len(pcm)%2 != 0 {
		c.failed = true
		close(c.frames)
		c.closed = true
		return
	}
	select {
	case c.frames <- append([]byte(nil), pcm...):
	default:
		// An observer that falls behind loses the complete capture, not random
		// pieces of audio that might be mistaken for a valid utterance.
		c.failed = true
		c.closed = true
		close(c.frames)
	}
}

func (c *Capture) Close() {
	if c == nil {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if !c.closed {
		c.closed = true
		close(c.frames)
	}
}

func (c *Capture) write(socket string, header Header) {
	defer close(c.done)
	conn, err := net.DialTimeout("unix", socket, 250*time.Millisecond)
	if err != nil {
		c.disable()
		return
	}
	defer conn.Close()
	encoded, _ := json.Marshal(header)
	if err := writeFrame(conn, encoded); err != nil {
		c.disable()
		return
	}
	for frame := range c.frames {
		if err := writeFrame(conn, frame); err != nil {
			c.disable()
			return
		}
	}
	c.mu.Lock()
	failed := c.failed
	c.mu.Unlock()
	if !failed {
		_ = writeFrame(conn, nil)
	}
}

func (c *Capture) disable() {
	c.mu.Lock()
	c.failed = true
	c.mu.Unlock()
}

func writeFrame(conn net.Conn, data []byte) error {
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
