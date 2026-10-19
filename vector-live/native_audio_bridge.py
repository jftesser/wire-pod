"""Authentic, continuous Vector SDK input with bounded WebRTC echo processing."""
import asyncio
import json
import os
import time
from pathlib import Path

import grpc
from anki_vector.messaging import protocol as p
from host_audio_bridge import HostAudioBridge
from pcm_stats import AudioStats
from native_clock import NativeClock


class NativeAudioBridge(HostAudioBridge):
    def __init__(self,robot,python,delay_ms=200):
        super().__init__(python,'Vector internal microphones',delay_ms)
        self.robot=robot
        self.stream=None
        self.native_stats=AudioStats()
        self.validated=asyncio.Event()
        self.messages=asyncio.Queue(maxsize=64)
        self.source='Vector internal microphones (continuous SDK)'
        self.last_native_frame=None
        self.receive_timeout=2.5
        self.worker_error=None
        self.clock=NativeClock()
        self.clock_pcm=bytearray()
        self.processed_samples=self.processed_squares=self.processed_peak=0

    async def start(self,destination):
        self.process=await asyncio.create_subprocess_exec(str(self.python),
            str(Path(__file__).with_name('native_audio_worker.py')),'--aec-delay-ms',str(self.delay_ms),
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,limit=8192,
            env={k:v for k,v in os.environ.items() if not k.startswith('OPENAI_')})
        try:
            greeting=json.loads(await asyncio.wait_for(self.process.stdout.readline(),10))
            if greeting!={'ready':True,'sample_rate':16000,'frame_bytes':320}:
                raise RuntimeError('Native echo processor failed to start.')
            self.running=True
            self.tasks=[asyncio.create_task(self.receive(destination)),
                        asyncio.create_task(self.send()),asyncio.create_task(self.capture()),
                        asyncio.create_task(self.watch_worker())]
            await asyncio.wait_for(self.validated.wait(),4)
            await asyncio.wait_for(self.first_frame.wait(),2)
            if self.error:raise RuntimeError(self.error)
        except BaseException:
            await self.close()
            raise

    def processed_frame(self,pcm):
        samples=memoryview(pcm).cast('h')
        self.processed_samples+=len(samples)
        self.processed_squares+=sum(s*s for s in samples)
        self.processed_peak=max(self.processed_peak,max((abs(s) for s in samples),default=0))

    async def capture(self):
        try:
            self.stream=self.robot.stub.AudioFeed(p.AudioFeedRequest())
            previous=None
            while True:
                frame=await asyncio.wait_for(self.stream.read(),2)
                if frame is grpc.aio.EOF:raise RuntimeError('Native SDK microphone closed.')
                if len(frame.signal_power)!=3200:raise RuntimeError('Invalid native PCM frame.')
                if previous is not None and ((frame.group_id-previous)&0xffffffff)!=1:
                    raise RuntimeError('Native microphone source sequence broke.')
                previous=frame.group_id
                self.native_stats.add(frame)
                self.last_native_frame=time.monotonic()
                if self.native_stats.max_duplicate_run>=3:
                    raise RuntimeError('SDK returned repeated test audio, not authentic mic input.')
                self.clock_pcm.extend(self.clock.push(frame.signal_power,frame.robot_time_stamp))
                while len(self.clock_pcm)>=320:
                    self.messages.put_nowait(b'C'+bytes(self.clock_pcm[:320]))
                    del self.clock_pcm[:320]
                if self.native_stats.frames>=5:
                    if self.native_stats.peak==0:
                        raise RuntimeError('Cannot verify an all-zero SDK microphone feed.')
                    self.validated.set()
        except asyncio.CancelledError:raise
        except Exception as exc:
            if not self.closing:
                self.error=str(exc) if isinstance(exc,RuntimeError) else 'Native microphone transport failed.'
                self.running=False
                self.validated.set()
                self.first_frame.set()
        finally:
            if self.stream:self.stream.cancel()

    def rendered(self,pcm):
        if not pcm or len(pcm)>1024 or len(pcm)%2:
            self.error='Invalid native speaker reference.'
            return
        try:self.messages.put_nowait(b'R'+pcm)
        except asyncio.QueueFull:self.error='Native audio pipe exceeded its bounded queue.'

    def cancel_render(self):
        # Preserve captured input while discarding only stale queued speaker reference.
        keep=[]
        while not self.messages.empty():
            message=self.messages.get_nowait()
            if message[:1]==b'C':keep.append(message)
        for message in keep:self.messages.put_nowait(message)
        try:self.messages.put_nowait(b'X')
        except asyncio.QueueFull:self.error='Native echo reset queue overflowed.'

    async def send(self):
        try:
            while True:
                message=await self.messages.get()
                self.process.stdin.write(len(message).to_bytes(4,'big')+message)
                await asyncio.wait_for(self.process.stdin.drain(),.5)
        except asyncio.CancelledError:raise
        except asyncio.TimeoutError:
            if not self.closing:self.error=self.error or 'Native echo processor input pipe stalled for500ms.'
        except Exception:
            if not self.closing:self.error=self.error or 'Native echo processor disconnected.'

    async def watch_worker(self):
        try:
            line=await self.process.stderr.readline()
            reason=json.loads(line).get('processor_error') if line else None
            self.worker_error=reason
            if reason and not self.closing:
                self.error='Native echo processor: '+str(reason)
            code=await self.process.wait()
            if not self.closing:
                self.error=self.error or 'Native echo processor exited ('+str(code)+').'
                self.running=False
        except asyncio.CancelledError:raise
        except Exception:
            if not self.closing:self.error=self.error or 'Native echo processor status pipe failed.'

    async def close(self):
        if self.stream:self.stream.cancel()
        await super().close()
