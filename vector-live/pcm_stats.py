"""Signal statistics without recording or external dependencies."""
import math
import struct
import time

RATE = 16000


class AudioStats:
    def __init__(self):
        self.frames = self.samples = self.squares = self.peak = self.gaps = 0
        self.first = self.last = self.previous_group = None
        self.max_interval = 0.0
        self.previous_audio = None
        self.duplicate_run = self.max_duplicate_run = 0

    def add(self, frame, now=None):
        data = frame.signal_power
        if len(data) % 2:
            raise ValueError("Incomplete PCM16 sample in microphone feed.")
        samples = struct.unpack("<" + "h" * (len(data) // 2), data)
        # Several identical non-silent 100 ms blocks are not credible speech
        # capture: some firmware returns a test waveform through this API.
        if data == self.previous_audio and any(samples):
            self.duplicate_run += 1
            self.max_duplicate_run = max(self.max_duplicate_run, self.duplicate_run)
        else:
            self.duplicate_run = 0
        self.previous_audio = data
        now = time.monotonic() if now is None else now
        if self.first is None:
            self.first = now
        if self.last is not None:
            self.max_interval = max(self.max_interval, now - self.last)
        if self.previous_group is not None and ((frame.group_id - self.previous_group) & 0xffffffff) != 1:
            self.gaps += 1
        self.previous_group, self.last = frame.group_id, now
        self.frames += 1
        self.samples += len(samples)
        self.squares += sum(s * s for s in samples)
        self.peak = max(self.peak, max((abs(s) for s in samples), default=0))

    def report(self):
        rms = math.sqrt(self.squares / self.samples) if self.samples else 0
        return {"frames": self.frames, "audio_seconds": round(self.samples / RATE, 3),
                "source_wall_seconds": round(self.last-self.first,3) if self.first is not None and self.last is not None else 0,
                "rms_dbfs": round(20 * math.log10(max(rms, 1) / 32768), 1),
                "peak_dbfs": round(20 * math.log10(max(self.peak, 1) / 32768), 1),
                "group_discontinuities": self.gaps, "max_delivery_interval_ms": round(self.max_interval * 1000, 1),
                "longest_identical_non_silent_run": self.max_duplicate_run + 1 if self.max_duplicate_run else 0,
                "suspected_test_or_stuck_signal": self.max_duplicate_run >= 3}
