import asyncio
from types import SimpleNamespace

from vector_audio import VectorAudio, p


def test_control_loss_is_observed_after_grant_and_release_is_sent():
    async def check():
        class Stream:
            def __init__(self):
                self.queue = asyncio.Queue()
                self.writes = []
                self.cancelled = False
            async def write(self, request):
                self.writes.append(request.WhichOneof('request_type'))
                if self.writes[-1] == 'control_request':
                    self.queue.put_nowait(p.BehaviorControlResponse(control_granted_response=p.ControlGrantedResponse()))
            def __aiter__(self):
                return self
            async def __anext__(self):
                return await self.queue.get()
            def cancel(self):
                self.cancelled = True
        stream = Stream()
        robot = VectorAudio.__new__(VectorAudio)
        robot.stub = SimpleNamespace(BehaviorControl=lambda: stream)
        async with robot.control():
            assert not robot.control_error
            stream.queue.put_nowait(p.BehaviorControlResponse(control_lost_event=p.ControlLostResponse()))
            for _ in range(20):
                if robot.control_error:
                    break
                await asyncio.sleep(.001)
            assert robot.control_error
        assert stream.writes == ['control_request', 'control_release']
        assert stream.cancelled
    asyncio.run(check())
