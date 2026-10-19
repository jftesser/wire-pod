import asyncio
import contextlib
import struct

from vector_audio import tone_pcm
from voice_player import VoicePlayer, volume_pcm


def test_continuous_silence_never_claims_robot_speaker():
    async def check():
        player = VoicePlayer(None)
        for _ in range(30):
            await player.feed(b'\0' * 3200)
        assert player.queue.empty()
        assert not player.speaking
        await player.feed(tone_pcm(.1))
        for _ in range(5):
            await player.feed(b'\0' * 3200)
        frames = []
        while not player.queue.empty():
            frames.append(player.queue.get_nowait())
        assert frames[-1] is None
        assert not player.speaking
    asyncio.run(check())


def test_volume_can_mute_and_change_inside_one_active_stream_with_render_reference():
    async def check():
        pcm=struct.pack('<4h',-32768,-1000,1000,32767)*400
        assert volume_pcm(pcm,100)==pcm
        assert volume_pcm(pcm,0)==bytes(len(pcm))
        assert struct.unpack('<4h',volume_pcm(pcm[:8],50))==(-16384,-500,500,16383)
        played=[]; reference=[]
        class Robot:
            async def play_stream(self,frames,volume,**options):
                assert volume==100
                async for frame in frames:
                    played.append(frame)
                    options['on_render'](frame)
                    player.volume=0
        player=VoicePlayer(Robot(),50,control_held=True,on_render=reference.append,on_cancel=lambda:None)
        player.put(pcm);player.put(pcm);player.put(None)
        player.task=asyncio.create_task(player.run())
        for _ in range(100):
            if player.segments_played:break
            await asyncio.sleep(.001)
        await player.close()
        assert len(played)==2 and played[0]==volume_pcm(pcm,50)
        assert played[1]==bytes(len(pcm))
        assert reference==played  # AEC receives the PCM actually sent, after gain.
    asyncio.run(check())


def test_shutdown_during_capture_cannot_swallow_cancellation():
    class Robot:
        controlled = False
        @contextlib.asynccontextmanager
        async def control(self):
            self.controlled = True
            try:
                yield
            finally:
                self.controlled = False
        async def play_stream(self, frames, volume):
            async for _ in frames:
                await asyncio.sleep(10)
    async def check():
        robot = Robot()
        player = VoicePlayer(robot)
        player.task = asyncio.create_task(player.run())
        await player.feed(tone_pcm(.1))
        for _ in range(20):
            if robot.controlled:
                break
            await asyncio.sleep(.01)
        assert robot.controlled
        player.input_active = True
        await asyncio.wait_for(player.close(), .5)
        assert not robot.controlled
        assert player.task.done()
    asyncio.run(check())
