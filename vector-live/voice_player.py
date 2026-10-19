"""Speak continuous Live output through finite robot audio streams.

Silence gates are playback segments, not claims that a model response is done.
The model's continuous silent output is not played into the robot microphone.
"""
import asyncio
import contextlib
import math
import struct
import numpy as np
from collections import deque
from voice_settings import validate_volume


def volume_pcm(pcm, volume):
    validate_volume(volume)
    if volume == 100:
        return pcm
    if volume == 0:
        return bytes(len(pcm))
    samples = struct.unpack('<' + 'h'*(len(pcm)//2), pcm)
    return struct.pack('<' + 'h'*len(samples), *(int(sample*volume/100) for sample in samples))


def boosted_pcm(pcm, volume, boost_db=0):
    """Gain followed by a continuous soft knee with a -1 dBFS ceiling.

    No extra buffering. Only peaks above 85% of the ceiling are compressed;
    ordinary speech below the knee keeps the full requested gain. This is a
    peak limiter, not loudness normalization or an automatic gain controller.
    """
    if boost_db not in (0, 3, 6):
        raise ValueError('Invalid boost.')
    if not boost_db or not volume:
        return volume_pcm(pcm, volume)
    validate_volume(volume)
    samples = np.frombuffer(pcm, dtype='<i2').astype(np.float64)
    samples *= volume / 100 * 10 ** (boost_db / 20)
    ceiling = 32767 * 10 ** (-1 / 20)
    knee = ceiling * .85
    magnitude = np.abs(samples)
    mask = magnitude > knee
    magnitude[mask] = knee + (ceiling-knee) * np.tanh((magnitude[mask]-knee)/(ceiling-knee))
    return (np.sign(samples) * magnitude).astype('<i2').tobytes()


def audible(pcm):
    samples = struct.unpack('<' + 'h' * (len(pcm) // 2), pcm)
    return bool(samples) and math.sqrt(sum(s*s for s in samples) / len(samples)) >= 50


class VoicePlayer:
    def __init__(self, robot, volume=35, *, control_held=False, on_render=None, on_cancel=None):
        self.robot, self.volume = robot, volume
        self.boost_db = 0
        self.control_held = control_held
        self.render_options = {} if on_render is None else {'on_render': on_render, 'on_cancel': on_cancel}
        self.queue = asyncio.Queue(maxsize=40)
        self.preroll = deque(maxlen=2)
        self.speaking = False
        self.quiet_bytes = 0
        self.input_active = False
        self.task = self.clip = None
        self.error = None
        self.segments_played = 0

    async def feed(self, pcm):
        if self.input_active:
            return
        for offset in range(0, len(pcm), 3200):
            frame = pcm[offset:offset+3200]
            if not self.speaking:
                self.preroll.append(frame)
                if audible(frame):
                    self.speaking = True
                    for previous in self.preroll:
                        self.put(previous)
                    self.preroll.clear()
            else:
                self.put(frame)
            if self.speaking:
                self.quiet_bytes = 0 if audible(frame) else self.quiet_bytes + len(frame)
                if self.quiet_bytes >= 16000:  # 500 ms of output silence
                    self.put(None)
                    self.speaking = False
                    self.quiet_bytes = 0

    def put(self, frame):
        try:
            self.queue.put_nowait(frame)
        except asyncio.QueueFull:
            raise RuntimeError('Robot playback queue overflowed; stopping session.') from None

    async def interrupt(self):
        self.input_active = True
        if self.clip:
            self.clip.cancel()
            await asyncio.gather(self.clip, return_exceptions=True)
        while not self.queue.empty():
            self.queue.get_nowait()
        self.preroll.clear()
        self.speaking = False
        self.quiet_bytes = 0

    async def run(self):
        try:
            while True:
                first = await self.queue.get()
                if first is None:
                    continue
                async def frames():
                    yield boosted_pcm(first, self.volume, self.boost_db)
                    while True:
                        frame = await asyncio.wait_for(self.queue.get(), 3)
                        if frame is None:
                            return
                        yield boosted_pcm(frame, self.volume, self.boost_db)
                async def play():
                    async with (contextlib.nullcontext() if self.control_held else self.robot.control()):
                        # Fixed stream gain lets each queued PCM frame use the
                        # newest setting without interrupting robot playback.
                        await self.robot.play_stream(frames(), 100, **self.render_options)
                self.clip = asyncio.create_task(play())
                try:
                    await self.clip
                    self.segments_played += 1
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling() or not self.input_active:
                        raise
                finally:
                    self.clip = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = type(exc).__name__

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.clip:
            self.clip.cancel()
            await asyncio.gather(self.clip, return_exceptions=True)
