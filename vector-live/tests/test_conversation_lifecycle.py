import asyncio
import contextlib
import json
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import conversation as app
from live_voice import PcmBuffer
from voice_settings import save_volume


@pytest.mark.parametrize('input_source', ['host', 'vector-sdk'])
@pytest.mark.parametrize('failure', [None, 'microphone', 'paid_start', 'control', 'ready_cue'])
def test_continuous_session_releases_every_resource(monkeypatch, failure, input_source):
    instances = {}
    class Events:
        def __aiter__(self):
            return self
        async def __anext__(self):
            await asyncio.sleep(10)
        def cancel(self):
            instances['events_cancelled'] = True
    class Robot:
        def __init__(self, pairing):
            self.stub = SimpleNamespace(EventStream=lambda request: Events())
            self.controlled = self.closed = False
            self.control_error = 'synthetic control loss' if failure == 'control' else None
            instances['robot'] = self
        async def status(self):
            return {'serial': 'test'}
        async def close(self):
            self.closed = True
        async def play_stream(self, frames, volume, **options):
            assert instances['session'].sender is not None
            assert instances['host'].running and self.controlled
            assert volume == (0 if instances.get('settings') else 25)
            if failure == 'ready_cue':
                raise RuntimeError('Synthetic ready cue failure.')
            async for pcm in frames:
                options['on_render'](pcm[:320])
        @contextlib.asynccontextmanager
        async def control(self):
            self.controlled = True
            try:
                yield
            finally:
                self.controlled = False
    class Session:
        def __init__(self, key, on_audio, **options):
            self.input = PcmBuffer()
            self.sender = None
            self.error = None
            self.finalized = asyncio.Event()
            self.usage = None
            self.backend_pending = set()
            self.voice = 'marin'
            self.closed = False
            assert options['input_mode'] == 'continuous'
            instances['session'] = self
        async def start(self):
            assert instances['host'].running
            assert instances['robot'].controlled
            if failure == 'paid_start':
                raise RuntimeError('offline simulated connection failure')
            self.sender = object()
            if instances.get('settings'):
                save_volume(instances['settings'],0)
                await asyncio.sleep(.25)
        async def close(self):
            assert not instances['robot'].controlled
            assert not instances['host'].running
            self.closed = True
            self.finalized.set()
    class Host:
        def __init__(self, *args):
            self.running = self.closed = False
            self.frames = 3
            self.last_activity = time.monotonic()
            self.error = None
            self.last_native_frame = time.monotonic()
            self.native_stats = SimpleNamespace(report=lambda: {})
            instances['host'] = self
        async def start(self, destination):
            assert destination.sender is None
            self.running = True
            if failure == 'microphone':
                self.error = 'synthetic disconnected mic'
        async def close(self):
            self.running = False
            self.closed = True
        def rendered(self, pcm):
            pass
        def cancel_render(self):
            pass
    monkeypatch.setattr(app, 'VectorAudio', Robot)
    monkeypatch.setattr(app, 'LiveVoice', Session)
    monkeypatch.setattr(app, 'HostAudioBridge', Host)
    monkeypatch.setattr(app, 'NativeAudioBridge', Host)
    monkeypatch.setattr(app, 'discover', lambda *args: object())
    monkeypatch.setattr(app, 'read_key', lambda filename: 'offline fake key')
    async def check():
        # macOS Unix socket path limit excludes pytest's long fixture paths.
        with tempfile.TemporaryDirectory(prefix='vc-', dir='/tmp') as directory:
            path = Path(directory)
            args = SimpleNamespace(input_mode='continuous', input_source=input_source, microphone_name='offline fake mic',
                audio_python='unused', aec_delay_ms=200, status_file=str(path/'status.json'),
                serial='test', volume=80, wirepod='unused', key_file=None,
                greet=False, ready_tone=input_source == 'vector-sdk', seconds=.15, local_socket=str(path/'voice.sock'), audition=False)
            if failure is None and input_source=='vector-sdk':
                instances['settings']=str(path/'settings.json')
                save_volume(instances['settings'],80)
                args.settings_file=instances['settings']
            if failure:
                if failure=='ready_cue' and input_source=='host':
                    await app.conversation(args)
                else:
                    with pytest.raises(RuntimeError):
                        await app.conversation(args)
            else:
                await app.conversation(args)
            state = json.loads((path/'status.json').read_text())
            expected_failure=bool(failure and not (failure=='ready_cue' and input_source=='host'))
            assert state['phase'] == ('error' if expected_failure else 'closed')
            if failure=='ready_cue' and input_source=='vector-sdk':
                assert state['error']=='Synthetic ready cue failure.'
            assert not state['ready'] and not state['microphone_active']
            assert state['mode'] == 'continuous' and not state['requires_wake_phrase']
            if instances.get('settings'):
                assert state['volume']==0
            assert state['source'] == ('Vector internal microphones (continuous SDK)' if input_source == 'vector-sdk' else 'Host microphone: offline fake mic')
            assert not (path/'voice.sock').exists()
            assert instances['session'].closed and instances['host'].closed
            assert instances['robot'].closed and not instances['robot'].controlled
    asyncio.run(check())
