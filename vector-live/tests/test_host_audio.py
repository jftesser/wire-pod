import asyncio
import contextlib
from types import SimpleNamespace

import pytest

from host_audio import HostMicrophone, SILENCE
from host_audio_bridge import HostAudioBridge
from live_voice import PcmBuffer, session_config


class Frame:
    def __init__(self, data, **_):
        self.data = data


class Processor:
    def __init__(self, **_):
        self.reverse = []
        self.processed = 0
    def process_reverse_stream(self, frame):
        self.reverse.append(bytes(frame.data))
    def set_stream_delay_ms(self, value):
        self.delay = value
    def process_stream(self, frame):
        self.processed += 1


class Devices:
    def query_devices(self):
        return [{'name': 'Selected mic', 'max_input_channels': 1}]
    def check_input_settings(self, **settings):
        assert settings['samplerate'] == 16000 and settings['channels'] == 1


def microphone():
    mic = HostMicrophone('Selected mic', audio=Devices(),
        rtc=SimpleNamespace(AudioFrame=Frame, AudioProcessingModule=Processor))
    mic.running = True
    return mic


def tick(mic, pcm=SILENCE):
    mic.callback(pcm, 160, SimpleNamespace(currentTime=1.01, inputBufferAdcTime=1), False)


def test_capture_remains_continuous_during_render_and_quiet():
    mic = microphone()
    spoken = b'\x01\x02' * 160
    mic.rendered(spoken * 2)
    for _ in range(3):
        tick(mic, spoken)
    assert mic.apm.reverse == [spoken, spoken, SILENCE]
    assert mic.apm.processed == mic.frames == 3
    assert [mic.captured.get_nowait() for _ in range(3)] == [spoken] * 3
    assert 209 <= mic.apm.delay <= 210
    mic.rendered(spoken)
    mic.cancel_render()
    tick(mic)
    assert mic.apm.reverse[-1] == SILENCE


def test_capture_and_reference_backlogs_fail_closed():
    mic = microphone()
    for _ in range(51):
        tick(mic)
    assert '500 ms' in mic.error
    assert mic.captured.qsize() == 50
    mic = microphone()
    mic.rendered(bytes(32002))
    assert 'one second' in mic.error
    assert not mic.reference
    with pytest.raises(ValueError):
        HostMicrophone('missing', audio=Devices(), rtc=object())


def test_continuous_prompt_never_requests_a_wake_phrase():
    config = session_config(greet=True, input_mode='continuous')
    assert 'continuous room audio' in config['instructions']
    greeting = config['input'][0]['content'][0]['text']
    assert 'speak directly' in greeting and 'Hey Vector' not in greeting
    assert 'only after its wake phrase' not in config['instructions']


def test_bridge_drops_pre_session_audio_and_detects_disconnect():
    async def check():
        bridge = HostAudioBridge('unused', 'Selected mic')
        reader = asyncio.StreamReader()
        bridge.process = SimpleNamespace(stdout=reader)
        destination = SimpleNamespace(sender=None, input=PcmBuffer())
        receiver = asyncio.create_task(bridge.receive(destination))
        pcm = b'\x01\x02' * 160
        reader.feed_data((320).to_bytes(4, 'big') + pcm)
        await asyncio.wait_for(bridge.first_frame.wait(), .2)
        assert not destination.input.data
        destination.sender = object()
        reader.feed_data((320).to_bytes(4, 'big') + pcm)
        for _ in range(20):
            if destination.input.data:
                break
            await asyncio.sleep(.001)
        assert destination.input.frame() == pcm
        reader.feed_eof()
        await asyncio.wait_for(receiver, .2)
        assert bridge.error and not bridge.running
    asyncio.run(check())


def test_helper_start_failure_terminates_process(monkeypatch):
    async def check():
        class Process:
            returncode = None
            def __init__(self):
                self.stdout = asyncio.StreamReader()
                self.stdout.feed_data(b'{"ready":false}\n')
            def terminate(self):
                self.returncode = 1
            async def wait(self):
                return self.returncode
        process = Process()
        async def create(*args, **kwargs):
            return process
        monkeypatch.setattr(asyncio, 'create_subprocess_exec', create)
        bridge = HostAudioBridge('unused', 'Selected mic')
        with pytest.raises(RuntimeError):
            await bridge.start(None)
        assert process.returncode == 1
        assert not bridge.running
    asyncio.run(check())
