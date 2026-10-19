"""Bounded native capture/APM/upload-clock rehearsal; no cloud or playback."""
import argparse
import asyncio
import json
import resource
import time
from pathlib import Path
from types import SimpleNamespace

from live_voice import PcmBuffer
from native_audio_bridge import NativeAudioBridge
from vector_audio import VectorAudio, discover


def process_memory(pid):
    try:
        lines = Path(f'/proc/{pid}/status').read_text().splitlines()
        return {line.split(':')[0]: int(line.split()[1]) for line in lines
                if line.startswith(('VmRSS:', 'VmHWM:'))}
    except OSError:
        return {}


async def run(args):
    pairing = await asyncio.to_thread(discover, args.wirepod, args.serial, None, True)
    robot = VectorAudio(pairing)
    bridge = NativeAudioBridge(robot, args.audio_python, 200)
    destination = SimpleNamespace(sender=None, input=PcmBuffer())
    started = time.monotonic()
    cpu = time.process_time()
    late_max = queue_max = padding_frames = frames = 0
    worker_memory = {}
    failure = None
    try:
        async with robot.control():
            await bridge.start(destination)
            destination.sender = object()
            deadline = time.monotonic() + args.seconds
            target = time.monotonic()
            while time.monotonic() < deadline:
                await asyncio.sleep(max(0, target-time.monotonic()))
                late = time.monotonic()-target
                late_max = max(late_max, late)
                if late > .25:
                    raise RuntimeError('Simulated upload clock exceeded250ms deadline.')
                if bridge.error or not bridge.running or robot.control_error:
                    raise RuntimeError(bridge.error or robot.control_error or 'Native source stopped.')
                queue_max = max(queue_max, len(destination.input.data))
                padding_frames += len(destination.input.data) < 320
                destination.input.frame()
                if args.render_reference:
                    bridge.rendered(b'\x01\x00'*160)
                frames += 1
                if frames % 100 == 0:
                    worker_memory = process_memory(bridge.process.pid)
                target += .01
    except Exception as exc:
        failure = str(exc)
    finally:
        await bridge.close()
        await robot.close()
    elapsed = time.monotonic()-started
    report = dict(native_microphone=bridge.native_stats.report(),
        processed_frames=bridge.frames, simulated_upload_frames=frames,
        simulated_upload_max_lateness_ms=round(late_max*1000,2),
        max_input_queue_ms=round(queue_max/32,2), padded_upload_frames=padding_frames,
        wall_seconds=round(elapsed,2), main_cpu_percent=round(100*(time.process_time()-cpu)/elapsed,2),
        main_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        worker_memory_kib=worker_memory, paid_api=False, audible_playback=False,
        room_audio_recorded=False, synthetic_render_reference=args.render_reference,
        worker_error=bridge.worker_error, source_clock=bridge.clock.report(), error=failure)
    print(json.dumps(report), flush=True)
    if failure:
        raise RuntimeError(failure)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wirepod', default='http://127.0.0.1:8080')
    parser.add_argument('--serial', default='00a14a38')
    parser.add_argument('--audio-python', default='/home/pi/vector-native-audio/bin/python')
    parser.add_argument('--seconds', type=int, default=60)
    parser.add_argument('--render-reference', action='store_true', help='Simulate continuous speaker reference silently.')
    args = parser.parse_args()
    if not 5 <= args.seconds <= 120:
        parser.error('Probe duration must be5–120 seconds.')
    asyncio.run(run(args))
