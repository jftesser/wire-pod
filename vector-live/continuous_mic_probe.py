"""Bounded local test of native continuous SDK input. No audio files or paid API."""
import argparse
import asyncio
import collections
import contextlib
import json
import struct
import time

import grpc
from anki_vector.messaging import protocol as p
from pcm_stats import AudioStats
from vector_audio import discover, VectorAudio


async def capture(robot, seconds, replay_pcm=None):
    stats = AudioStats()
    source_deltas = collections.Counter()
    first_group = first_timestamp = last_timestamp = None
    next_progress = 15
    stream = robot.stub.AudioFeed(p.AudioFeedRequest())
    started = time.monotonic()
    deadline = started + seconds
    try:
        while time.monotonic() < deadline:
            try:
                frame = await asyncio.wait_for(stream.read(), min(3, max(.01, deadline-time.monotonic())))
            except asyncio.TimeoutError:
                if time.monotonic() >= deadline and stats.frames:
                    break
                raise RuntimeError('Native audio stalled for three seconds.') from None
            if frame is grpc.aio.EOF:
                raise RuntimeError('Native audio ended unexpectedly.')
            if len(frame.signal_power) != 3200:
                raise RuntimeError('Unexpected native PCM group size.')
            if first_group is None:
                first_group = frame.group_id
                first_timestamp = frame.robot_time_stamp
            if last_timestamp is not None:
                source_deltas[(frame.robot_time_stamp-last_timestamp) & 0xffffffff] += 1
            last_timestamp = frame.robot_time_stamp
            stats.add(frame)
            elapsed = time.monotonic()-started
            if replay_pcm is not None and 40 <= elapsed < 48:
                if len(replay_pcm)+len(frame.signal_power) <= 8*32000:
                    replay_pcm.extend(frame.signal_power)
            if elapsed >= next_progress:
                print(json.dumps({'progress_seconds': round(elapsed, 1), 'frames': stats.frames,
                                  'source_group_discontinuities': stats.gaps}), flush=True)
                next_progress += 15
    except (grpc.RpcError, RuntimeError) as exc:
        failure = stats.report()
        failure.update(wall_seconds=round(time.monotonic()-started, 3), first_group=first_group,
                       source_timestamp_deltas_ms=dict(source_deltas))
        if isinstance(exc, grpc.RpcError):
            details = exc.details()
            if details in ('Native microphone feed stalled', 'Microphone engine stream closed', 'Microphone already in use'):
                failure['gateway_error'] = details
        print(json.dumps({'capture_failed': failure}), flush=True)
        raise
    finally:
        stream.cancel()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stream.code(), 2)
    result = stats.report()
    result.update(wall_seconds=round(time.monotonic()-started, 3), first_group=first_group,
                  source_timestamp_deltas_ms=dict(source_deltas),
                  source_span_ms=((last_timestamp-first_timestamp)&0xffffffff) if first_timestamp is not None else 0,
                  pcm_file=False, paid_api=False)
    if stats.frames == 0 or result['suspected_test_or_stuck_signal'] or stats.gaps:
        raise RuntimeError('Native input authenticity or source group continuity failed: '+json.dumps(result))
    if result['audio_seconds'] < .94*(seconds-.5):
        raise RuntimeError('Too little source audio for the requested continuous interval: '+json.dumps(result))
    return result


async def run(args):
    pairing = await asyncio.to_thread(discover, args.wirepod, args.serial, args.certificate, args.trust_local_certificate)
    robot = VectorAudio(pairing)
    try:
        print(json.dumps({'robot': await robot.status()}), flush=True)
        async with robot.control():
            print(json.dumps({'test': 'native_continuous_sdk', 'seconds': args.seconds,
                              'note': 'Capture only; no listening sound or spoken answer.'}), flush=True)
            ram = bytearray() if args.replay else None
            print(json.dumps({'continuous': await capture(robot, args.seconds, ram)}), flush=True)
            if ram:
                samples = struct.unpack('<'+'h'*(len(ram)//2), ram)
                peak = max(abs(x) for x in samples)
                gain = min(8, .7*32767/max(1, peak))
                replay = struct.pack('<'+'h'*len(samples), *(int(x*gain) for x in samples))
                print(json.dumps({'replay': 'eight seconds from after forty seconds; RAM only',
                                  'seconds': round(len(ram)/32000, 2)}), flush=True)
                await robot.play(replay, 80)
                ram.clear()
            # Check clean repeated start/stop; successful fresh source group zero confirms a new session.
            for attempt in range(args.restarts):
                await asyncio.sleep(.5)
                result = await capture(robot, 3)
                if result['first_group'] != 0:
                    raise RuntimeError('Capture did not begin with a fresh source session.')
                print(json.dumps({'restart': attempt+1, 'capture': result}), flush=True)
    finally:
        await robot.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wirepod', default='http://10.0.0.212:8080')
    parser.add_argument('--serial', default='00a14a38')
    parser.add_argument('--certificate')
    parser.add_argument('--trust-local-certificate', action='store_true')
    parser.add_argument('--seconds', type=float, default=75)
    parser.add_argument('--restarts', type=int, default=3)
    parser.add_argument('--replay', action='store_true', help='Replay at most eight seconds from after forty seconds; RAM only.')
    args = parser.parse_args()
    if not 5 <= args.seconds <= 120 or not 0 <= args.restarts <= 5 or (args.replay and args.seconds < 50):
        parser.error('Capture must be 5–120 seconds; restarts 0–5.')
    try:
        asyncio.run(run(args))
    except grpc.RpcError as exc:
        parser.exit(1, f'Robot RPC failed: {exc.code().name}\n')
    except (RuntimeError, ValueError, OSError, TimeoutError) as exc:
        parser.exit(1, f'Continuous mic test failed: {exc}\n')


if __name__ == '__main__':
    main()
