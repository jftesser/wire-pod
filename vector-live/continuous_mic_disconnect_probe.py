"""Local crash/reconnect check. Child exits without gRPC cleanup; no paid API."""
import asyncio
import json
import os
import sys

from anki_vector.messaging import protocol as p
from continuous_mic_probe import capture
from vector_audio import discover, VectorAudio


async def main():
    if '--child' in sys.argv:
        pairing = await asyncio.to_thread(discover, 'http://10.0.0.212:8080', '00a14a38', None, True)
        robot = VectorAudio(pairing)
        stream = robot.stub.AudioFeed(p.AudioFeedRequest())
        await asyncio.wait_for(stream.read(), 5)
        os._exit(0)
    robot = None
    try:
        child = await asyncio.create_subprocess_exec(sys.executable, __file__, '--child')
        try:
            code = await asyncio.wait_for(child.wait(), 10)
        except asyncio.TimeoutError:
            child.kill()
            await child.wait()
            raise RuntimeError('Child capture never delivered a frame.')
        if code:
            raise RuntimeError('Child capture failed.')
        await asyncio.sleep(1)
        pairing = await asyncio.to_thread(discover, 'http://10.0.0.212:8080', '00a14a38', None, True)
        robot = VectorAudio(pairing)
        report = await capture(robot, 3)
        if report['first_group'] != 0:
            raise RuntimeError('Disconnected child did not release its microphone session.')
        print(json.dumps({'abrupt_client_exit_and_reconnect': report}), flush=True)
    finally:
        if robot:
            await robot.close()


if __name__ == '__main__':
    asyncio.run(main())
