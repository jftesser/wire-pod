"""Real isolated LiveKit APM and binary pipes, with synthetic capture only."""
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from host_audio_bridge import HostAudioBridge
from live_voice import PcmBuffer


@pytest.mark.skipif(not os.environ.get('VECTOR_AUDIO_TEST_PYTHON'), reason='isolated audio environment required')
def test_isolated_aec_worker_captures_while_rendering_and_reaps_on_close(monkeypatch):
    # Force the worker to import a synthetic PortAudio substitute. No device API
    # or microphone permission is touched, even when real sounddevice is installed.
    monkeypatch.setenv('PYTHONPATH', str(Path(__file__).parent / 'fake_audio'))
    async def check():
        destination = SimpleNamespace(sender=object(), input=PcmBuffer())
        bridge = HostAudioBridge(os.environ['VECTOR_AUDIO_TEST_PYTHON'], 'Offline synthetic mic')
        try:
            await bridge.start(destination)
            first = bridge.frames
            for _ in range(10):
                bridge.rendered(b'\x01\x00' * 160)
                await asyncio.sleep(.01)
                while destination.input.data:
                    assert len(destination.input.frame()) == 320
            assert bridge.frames >= first + 5
            assert bridge.running and not bridge.error
            bridge.cancel_render()
        finally:
            await bridge.close()
        assert bridge.process.returncode is not None
        assert all(task.done() for task in bridge.tasks)
        assert not bridge.running
    asyncio.run(check())
