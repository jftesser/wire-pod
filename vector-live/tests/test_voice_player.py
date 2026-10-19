import asyncio
import contextlib

from vector_audio import tone_pcm
from voice_player import VoicePlayer


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
