"""Bounded PCM pipes isolate modern audio dependencies from the legacy SDK."""
import asyncio
import contextlib
import json
import os
import time
from pathlib import Path

from tap_observer import read_frame


class HostAudioBridge:
    def __init__(self, python, device_name, delay_ms=200):
        self.python, self.device_name, self.delay_ms = python, device_name, delay_ms
        self.process = None
        self.tasks = []
        self.render_queue = asyncio.Queue(maxsize=64)  # <=2 seconds of 1024-byte RPC chunks.
        self.frames = 0
        self.first_frame = asyncio.Event()
        self.last_activity = time.monotonic()
        self.error = None
        self.running = self.closing = False
        self.level = 0

    async def start(self, destination):
        self.process = await asyncio.create_subprocess_exec(str(self.python),
            str(Path(__file__).with_name('host_audio_worker.py')), '--device-name', self.device_name,
            '--aec-delay-ms', str(self.delay_ms), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=8192,
            env={key: value for key, value in os.environ.items() if not key.startswith('OPENAI_')})
        try:
            greeting = json.loads(await asyncio.wait_for(self.process.stdout.readline(), 10))
            if greeting != {'ready': True, 'sample_rate': 16000, 'frame_bytes': 320}:
                raise RuntimeError('Host microphone helper could not open the selected device.')
            self.running = True
            self.tasks = [asyncio.create_task(self.receive(destination)), asyncio.create_task(self.send())]
            await asyncio.wait_for(self.first_frame.wait(), 2)
            if self.error:
                raise RuntimeError(self.error)
        except BaseException:
            await self.close()
            raise

    async def receive(self, destination):
        try:
            while True:
                pcm = await asyncio.wait_for(read_frame(self.process.stdout, 320), getattr(self, 'receive_timeout', 1))
                if len(pcm) != 320:
                    raise RuntimeError('Invalid microphone helper frame.')
                observer = getattr(self, 'processed_frame', None)
                if observer:
                    observer(pcm)
                self.frames += 1
                self.first_frame.set()
                samples = memoryview(pcm).cast('h')
                self.level = max((abs(s) for s in samples), default=0) / 32768
                if sum(s*s for s in samples) > 160 * 500**2:
                    self.last_activity = time.monotonic()
                if destination.sender is not None:
                    destination.input.append(pcm)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self.closing:
                detail = ('processed audio stalled' if isinstance(exc, asyncio.TimeoutError) else
                    'upload input queue exceeded two seconds' if isinstance(exc, RuntimeError) and str(exc).startswith('Input audio queue exceeded') else
                    'processed audio frame or transport failed')
                self.error = self.error or getattr(self, 'source', 'Host microphone') + ': ' + detail + '.'
                self.running = False

    def rendered(self, pcm):
        try:
            if len(pcm) > 1024 or len(pcm) % 2:
                raise ValueError('Invalid render reference frame.')
            self.render_queue.put_nowait(pcm)
        except asyncio.QueueFull:
            self.error = 'Echo reference transport fell behind.'

    def cancel_render(self):
        while not self.render_queue.empty():
            self.render_queue.get_nowait()
        self.render_queue.put_nowait(b'')

    async def send(self):
        try:
            while True:
                pcm = await self.render_queue.get()
                self.process.stdin.write(len(pcm).to_bytes(4, 'big') + pcm)
                await asyncio.wait_for(self.process.stdin.drain(), .5)
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self.closing:
                self.error = 'Echo reference helper disconnected.'

    async def close(self):
        self.closing, self.running = True, False
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.process and self.process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
