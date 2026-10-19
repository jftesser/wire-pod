"""Native SDK-to-AEC pipes; no hardware, host mic or paid API."""
import asyncio
import os
import struct
from types import SimpleNamespace

import pytest
from native_audio_bridge import NativeAudioBridge
from live_voice import PcmBuffer


@pytest.mark.skipif(not os.environ.get('VECTOR_AUDIO_TEST_PYTHON'), reason='isolated APM environment required')
@pytest.mark.parametrize('kind',['real','repeated','gap','closed'])
def test_native_source_preflight_and_cleanup(kind):
    class Stream:
        def __init__(self):self.index=0;self.cancelled=False
        async def read(self):
            import grpc
            await asyncio.sleep(.05)
            self.index+=1
            if kind=='closed':return grpc.aio.EOF
            group=self.index-1+(1 if kind=='gap' and self.index>3 else 0)
            value=1000 if kind=='repeated' else 300+self.index
            return SimpleNamespace(signal_power=struct.pack('<h',value)*1600,group_id=group,robot_time_stamp=self.index*102)
        def cancel(self):self.cancelled=True
    async def check():
        stream=Stream()
        robot=SimpleNamespace(stub=SimpleNamespace(AudioFeed=lambda request:stream))
        dest=SimpleNamespace(sender=None,input=PcmBuffer())
        bridge=NativeAudioBridge(robot,os.environ['VECTOR_AUDIO_TEST_PYTHON'])
        try:
            if kind!='real':
                with pytest.raises(RuntimeError):await bridge.start(dest)
            else:
                await bridge.start(dest)
                assert bridge.running and bridge.native_stats.frames>=5
                assert not dest.input.data # Preflight audio never gets queued for the paid session.
                dest.sender=object()
                bridge.rendered(b'\x01\x00'*160)
                await asyncio.sleep(.1)
                assert dest.input.data
                bridge.cancel_render()
        finally:await bridge.close()
        assert stream.cancelled and not bridge.running
        assert bridge.process.returncode is not None
        assert all(task.done() for task in bridge.tasks)
    asyncio.run(check())
