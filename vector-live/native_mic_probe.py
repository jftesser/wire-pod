"""Bounded native-mic transport test; no OpenAI or audio files, optional RAM replay."""
import argparse
import asyncio
import contextlib
import json
import os
import time
import urllib.parse
import urllib.request
import grpc
from array import array
from pathlib import Path
from types import SimpleNamespace

from pcm_stats import AudioStats
from tap_observer import read_frame
from vector_audio import VectorAudio, discover, tone_pcm


async def run(args):
    path = Path(args.socket)
    if path.exists() or path.is_symlink():
        raise RuntimeError('Live socket already exists; refusing to replace it.')
    complete = asyncio.Event()
    tasks = set()
    result = {}
    started = time.monotonic()
    busy = False
    timing = {}
    capture_started_event = asyncio.Event()
    replay_pcm = bytearray()
    speaker = {'active': False, 'frames_received_during_rpc': 0}
    async def capture(reader, writer):
        nonlocal busy
        tasks.add(asyncio.current_task())
        accepted = False
        stats, window = AudioStats(), AudioStats()
        try:
            header = json.loads(await asyncio.wait_for(read_frame(reader, 4096), 2))
            accepted = (header.get('device', '').lower() == args.serial.lower()
                and header.get('sample_rate') == 16000 and header.get('format') == 'pcm_s16le'
                and not result and not busy)
            busy = accepted or busy
            # Older adapters still get ACK1 and a completed diagnostic request,
            # rather than rejecting it into the legacy language-model handler.
            hold = args.ack == 2 and header.get('probe_hold_available') is True
            writer.write(bytes([(2 if hold else 1) if accepted else 0]))
            await writer.drain()
            if not accepted:
                return
            print(json.dumps({'native_capture': 'started', 'kind': header.get('kind'),
                              'server_speech_cutoff_bypassed': hold,
                              'trigger_to_first_request_seconds': round(time.monotonic()-started, 3)}), flush=True)
            capture_started = time.monotonic()
            timing['first_request_at'] = capture_started
            capture_started_event.set()
            last_window = time.monotonic()
            while True:
                pcm = await asyncio.wait_for(read_frame(reader), 5)
                if not pcm:
                    timing['ended_at'] = time.monotonic()
                    result.update(stats.report(), complete=True)
                    result.pop('group_discontinuities', None)  # This transport has no source sequence numbers.
                    result.update(wall_seconds=round(time.monotonic()-capture_started, 3),
                                  server_speech_cutoff_bypassed=hold)
                    break
                frame = SimpleNamespace(signal_power=pcm, group_id=stats.frames)
                stats.add(frame)
                window.add(frame)
                if speaker['active']:
                    speaker['frames_received_during_rpc'] += 1
                if args.replay:
                    if len(replay_pcm) + len(pcm) > 32000 * 20:
                        raise RuntimeError('Diagnostic replay exceeded twenty seconds.')
                    replay_pcm.extend(pcm)
                if time.monotonic() - last_window >= .5:
                    report = window.report()
                    report.pop('group_discontinuities', None)
                    if not args.summary_only:
                        print(json.dumps({'native_window': report}), flush=True)
                    window = AudioStats()
                    last_window = time.monotonic()
        except Exception as exc:
            result.update(stats.report(), complete=False, error=type(exc).__name__)
            result.pop('group_discontinuities', None)
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            if accepted:
                complete.set()
            tasks.discard(asyncio.current_task())
    server = robot = speaker_task = None
    try:
        if args.duplex or args.replay or args.direct_trigger:
            robot = VectorAudio(await asyncio.to_thread(discover, args.wirepod, args.serial, None, True))
        async def duplex():
            await capture_started_event.wait()
            await asyncio.sleep(2)
            print(json.dumps({'speaker_probe': 'requesting_control'}), flush=True)
            try:
                async with robot.control():
                    speaker['active'] = True
                    begin = time.monotonic()
                    await robot.play(tone_pcm(.7), 25)
                    speaker.update(completed=True, rpc_seconds=round(time.monotonic()-begin, 3))
            except Exception as exc:
                speaker.update(completed=False, error=type(exc).__name__)
            finally:
                speaker['active'] = False
        if args.duplex:
            speaker_task = asyncio.create_task(duplex())
        server = await asyncio.start_unix_server(capture, str(path))
        os.chmod(path, 0o600)
        print(json.dumps({'probe': 'ready', 'trigger_in_seconds': args.delay,
                          'paid_api': False, 'audio_file': False,
                          'temporary_memory_replay': args.replay, 'speaker_probe': args.duplex}), flush=True)
        await asyncio.sleep(args.delay)
        started = time.monotonic()
        def trigger():
            body = urllib.parse.urlencode({'serial': args.serial, 'intent': 'knowledge_question'}).encode()
            request = urllib.request.Request(args.wirepod.rstrip('/') + '/api-sdk/cloud_intent', data=body)
            with urllib.request.urlopen(request, timeout=8) as response:
                if response.read(1024).strip() != b'done':
                    raise RuntimeError('Wire-pod did not accept the listening command.')
        if args.direct_trigger:
            # This SDK predates AppIntentRequest. The checked firmware schema
            # defines string intent = 1; use its protobuf encoding directly.
            intent = b'knowledge_question'
            rpc = robot.channel.unary_unary(
                '/Anki.Vector.external_interface.ExternalInterface/AppIntent',
                request_serializer=lambda data: data, response_deserializer=lambda data: data)
            try:
                await rpc(b'\x0a' + bytes([len(intent)]) + intent, timeout=8)
            except grpc.RpcError as exc:
                print(json.dumps({'trigger_failed': exc.code().name}), flush=True)
                raise
        else:
            await asyncio.to_thread(trigger)
        timing['trigger_rpc_seconds'] = round(time.monotonic()-started, 4)
        print(json.dumps({'trigger': 'knowledge_question', 'rpc_returned': True,
                          'trigger_rpc_seconds': timing['trigger_rpc_seconds'],
                          'direct_sdk_trigger': args.direct_trigger}), flush=True)
        await asyncio.wait_for(complete.wait(), args.timeout)
        print(json.dumps({'native_result': result}), flush=True)
        if speaker_task:
            await asyncio.wait_for(speaker_task, 8)
            print(json.dumps({'speaker_result': speaker}), flush=True)
        if args.replay and replay_pcm:
            samples = array('h')
            samples.frombytes(replay_pcm)
            peak = max((abs(s) for s in samples), default=0)
            gain = min(8, 12000 / max(1, peak))
            for index, sample in enumerate(samples):
                samples[index] = int(sample * gain)
            print(json.dumps({'replay': 'starting', 'audio_seconds': len(replay_pcm)/32000,
                              'volume': 80, 'gain': round(gain, 2)}), flush=True)
            async with robot.control():
                await robot.play(samples.tobytes(), 80)
            print(json.dumps({'replay': 'complete'}), flush=True)
        if not result.get('complete') or not result.get('frames') or result.get('suspected_test_or_stuck_signal'):
            raise RuntimeError('Native capture did not pass the transport check.')
        return timing
    finally:
        if server:
            server.close()
            await server.wait_closed()
            path.unlink(missing_ok=True)
        for task in list(tasks):
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if speaker_task:
            speaker_task.cancel()
            await asyncio.gather(speaker_task, return_exceptions=True)
        replay_pcm.clear()
        if robot:
            await robot.close()


async def trials(args):
    previous_end = None
    gaps = []
    initial_delay = args.delay
    control_robot = None
    try:
        if args.reset_control:
            control_robot = VectorAudio(await asyncio.to_thread(discover, args.wirepod, args.serial, None, True))
            await asyncio.wait_for(control_robot.channel.channel_ready(), 8)
        for number in range(args.attempts):
            if control_robot:
                # The existing conversation loop takes SDK control while speaking
                # and releases it before newVoiceRequest. Test that state transition
                # without speaking or issuing any movement command.
                begin = time.monotonic()
                async with control_robot.control():
                    await asyncio.sleep(.1)
                print(json.dumps({'native_control_reset_seconds': round(time.monotonic()-begin, 3)}), flush=True)
            args.delay = initial_delay if number == 0 else args.rearm_delay
            print(json.dumps({'native_trial': number + 1, 'of': args.attempts}), flush=True)
            timing = await run(args)
            if previous_end is not None:
                gaps.append(round(timing['first_request_at'] - previous_end, 3))
            previous_end = timing['ended_at']
            print(json.dumps({'native_rearm_progress': {'completed_windows': number + 1,
                'requested_delay_seconds': args.rearm_delay, 'reset_control': args.reset_control,
                'observed_gaps_seconds': gaps}}), flush=True)
        if gaps:
            print(json.dumps({'native_rearm_gaps_seconds': gaps,
                              'note': 'Observed EOF-to-next-request gaps; no source sample timestamps are exposed.'}), flush=True)
    finally:
        if control_robot:
            await control_robot.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wirepod', default='http://127.0.0.1:8080')
    parser.add_argument('--serial', default='00a14a38')
    parser.add_argument('--socket', default='/home/pi/vector-live-runtime/live.sock')
    parser.add_argument('--delay', type=float, default=8)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--ack', type=int, choices=[1, 2], default=1,
        help='ACK2 only after the isolated adapter supports holding past speech-end.')
    parser.add_argument('--duplex', action='store_true', help='Play a quiet tone during native capture.')
    parser.add_argument('--replay', action='store_true', help='Replay only this capture from bounded temporary RAM; no audio file.')
    parser.add_argument('--attempts', type=int, default=1)
    parser.add_argument('--rearm-delay', type=float, default=.35)
    parser.add_argument('--reset-control', action='store_true', help='Take/release SDK behavior control between windows, with no movement or speech.')
    parser.add_argument('--direct-trigger', action='store_true', help='Call the robot directly so an AppIntent RPC failure cannot be hidden by the web adapter.')
    parser.add_argument('--summary-only', action='store_true', help='Omit intermediate half-second level reports.')
    args = parser.parse_args()
    if not 0 <= args.delay <= 30 or not 1 <= args.timeout <= 60:
        parser.error('Delay0–30 seconds and timeout1–60 seconds required.')
    if not 1 <= args.attempts <= 10 or not 0 <= args.rearm_delay <= 15:
        parser.error('One to ten trials and rearm delay0–15 seconds required.')
    if args.attempts > 1 and (args.replay or args.duplex):
        parser.error('Rearming timing is measured without playback trials.')
    try:
        asyncio.run(trials(args))
    except Exception as exc:
        parser.exit(1, 'Native microphone test failed: ' + type(exc).__name__ + '\n')
