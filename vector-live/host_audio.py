"""Optional continuous host microphone, with bounded WebRTC echo reference.

No audio device is touched at import. Vector supplies no playback timestamp:
the AEC delay is an estimate that must be rehearsed with the actual room/mic.
"""
from __future__ import annotations

import queue
import threading
import time

RATE, SAMPLES, FRAME_BYTES = 16000, 160, 320
SILENCE = bytes(FRAME_BYTES)


class HostMicrophone:
    def __init__(self, device_name, delay_ms=200, *, audio=None, rtc=None):
        if not device_name or not 0 <= delay_ms <= 1000:
            raise ValueError('Select a microphone name and an AEC delay from 0–1000 ms.')
        if audio is None or rtc is None:
            try:
                import sounddevice as audio
                from livekit import rtc
            except ImportError:
                raise RuntimeError('Install the isolated host-audio environment before selecting host input.') from None
        matches = [(i, d) for i, d in enumerate(audio.query_devices())
                   if d['name'] == device_name and d['max_input_channels'] > 0]
        if len(matches) != 1:
            raise ValueError('Select one uniquely named, currently connected input device.')
        self.device, self.device_name = matches[0][0], device_name
        audio.check_input_settings(device=self.device, channels=1, samplerate=RATE, dtype='int16')
        self.audio, self.rtc, self.delay_ms = audio, rtc, delay_ms
        self.apm = rtc.AudioProcessingModule(echo_cancellation=True, noise_suppression=True,
                                            high_pass_filter=True, auto_gain_control=False)
        self.lock = threading.Lock()
        self.reference = bytearray()
        self.captured = queue.Queue(maxsize=50)  # 500 ms; no unbounded thread-to-loop callbacks.
        self.stream = None
        self.error = None
        self.running = False
        self.frames = 0
        self.last_frame = self.last_activity = time.monotonic()
        self.level = 0.0

    def frame(self, pcm):
        return self.rtc.AudioFrame(data=pcm, sample_rate=RATE, num_channels=1,
                                   samples_per_channel=SAMPLES)

    def rendered(self, pcm):
        """Only PCM actually accepted by Vector's playback RPC enters the AEC."""
        if len(pcm) % 2:
            raise ValueError('Incomplete playback reference sample.')
        with self.lock:
            if len(self.reference) + len(pcm) > RATE * 2:
                self.error = 'Playback reference exceeded one second.'
                return
            self.reference.extend(pcm)

    def cancel_render(self):
        with self.lock:
            self.reference.clear()

    def callback(self, data, frames, timing, status):
        if self.error or not self.running:
            return
        try:
            if status or frames != SAMPLES or len(data) != FRAME_BYTES:
                raise RuntimeError('Microphone lost its continuous 10 ms clock.')
            with self.lock:
                reverse = bytes(self.reference[:FRAME_BYTES]).ljust(FRAME_BYTES, b'\0')
                del self.reference[:FRAME_BYTES]
            self.apm.process_reverse_stream(self.frame(reverse))
            frame = self.frame(bytes(data))
            input_delay = max(0, timing.currentTime - timing.inputBufferAdcTime) * 1000
            self.apm.set_stream_delay_ms(min(1000, int(self.delay_ms + input_delay)))
            self.apm.process_stream(frame)
            pcm = bytes(frame.data)
            # Activity is for the idle timeout, never a gate on input transmission.
            samples = memoryview(pcm).cast('h')
            self.level = max((abs(s) for s in samples), default=0) / 32768
            now = time.monotonic()
            if sum(s*s for s in samples) > SAMPLES * 500**2:
                self.last_activity = now
            self.captured.put_nowait(pcm)
            self.frames += 1
            self.last_frame = now
        except queue.Full:
            self.error = 'Microphone processing fell more than 500 ms behind.'
        except Exception as exc:
            self.error = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__

    def start(self):
        """Open locally before opening a paid session. Never selects the default mic."""
        self.last_frame = self.last_activity = time.monotonic()
        self.stream = self.audio.RawInputStream(device=self.device, samplerate=RATE,
            blocksize=SAMPLES, channels=1, dtype='int16', callback=self.callback)
        self.running = True
        try:
            self.stream.start()
        except BaseException:
            self.close()
            raise

    def close(self):
        self.running = False
        if self.stream:
            try:
                self.stream.stop()
            finally:
                self.stream.close()
                self.stream = None
        self.cancel_render()
        while not self.captured.empty():
            self.captured.get_nowait()
