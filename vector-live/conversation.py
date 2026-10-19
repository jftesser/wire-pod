"""Explicit, bounded Vector conversation on the Pi or through a private SSH bridge."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import subprocess
import tempfile
import time
import wave
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from live_voice import LiveVoice, read_key
from tap_observer import read_frame
from vector_audio import discover, VectorAudio, p, tone_pcm
from voice_player import VoicePlayer
from runtime_status import RuntimeStatus
from host_audio_bridge import HostAudioBridge
from native_audio_bridge import NativeAudioBridge
from voice_settings import read_settings
from conversation_behaviors import ConversationBehaviors


async def conversation(args):
    continuous = args.input_mode == 'continuous'
    native = continuous and getattr(args, 'input_source', 'host') == 'vector-sdk'
    source = 'Vector internal microphones (continuous SDK)' if native else ('Host microphone: ' + args.microphone_name if continuous else 'Vector wake-word requests')
    status = RuntimeStatus(args.status_file, args.serial, mode=args.input_mode,
                           volume=args.volume, source=source) if args.status_file else None
    try:
        async with contextlib.AsyncExitStack() as resources:
            robot = VectorAudio(await asyncio.to_thread(discover, args.wirepod, args.serial, None, True))
            resources.push_async_callback(robot.close)
            await _conversation(args, robot, status, resources)
    except Exception as exc:
        if status:
            status.write(phase='error', ready=False, microphone_active=False, speaking=False,
                         error=status.state.get('error') or type(exc).__name__)
        raise


async def _conversation(args, robot, status, resources):
    controls = await resources.enter_async_context(contextlib.AsyncExitStack())
    continuous = args.input_mode == 'continuous'
    native = continuous and getattr(args, 'input_source', 'host') == 'vector-sdk'
    host = (NativeAudioBridge(robot, args.audio_python, args.aec_delay_ms) if native else HostAudioBridge(args.audio_python, args.microphone_name, args.aec_delay_ms)) if continuous else None
    player = VoicePlayer(robot, args.volume, control_held=continuous,
                         on_render=host.rendered if host else None,
                         on_cancel=host.cancel_render if host else None)
    stop = asyncio.Event()
    async def tool_handler(name, arguments):
        if not isinstance(arguments, dict) or arguments:
            raise ValueError('This tool takes no arguments.')
        if name == 'get_robot_status':
            return {**await robot.status(), 'conversation_gestures': {
                'profile': behaviors.mode, 'error': behaviors.error,
                'animated_eyes_and_blinks_enabled': behaviors.mode != 'off' and not behaviors.error,
                'head_enabled': behaviors.mode == 'head' and not behaviors.error,
                'head_currently_permitted': behaviors.safe_head(),
                'completed_head_nods': behaviors.nods_completed,
                'driving_available': False}}
        if name == 'get_time':
            return {'time': datetime.now(ZoneInfo('America/New_York')).isoformat(), 'timezone': 'America/New_York'}
        if name == 'end_conversation':
            print(json.dumps({'stop': 'spoken_request'}), flush=True)
            stop.set()
            return {'status': 'ending'}
        raise ValueError('Unknown tool.')
    tools = [{'type': 'function', 'name': name, 'description': description,
              'parameters': {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False},
              'strict': True} for name, description in [
        ('get_robot_status', 'Read the actual robot battery, firmware and charger state.'),
        ('get_time', 'Get the current local date and time in New York.'),
        ('end_conversation', 'End this paid voice session when the person clearly asks to stop, end the conversation or says goodbye.')]]
    session = LiveVoice(read_key(args.key_file), player.feed, greet=args.greet, tools=tools, tool_handler=tool_handler, input_mode=args.input_mode)
    behaviors = ConversationBehaviors(robot, player, session)
    active = set()
    capture_lock = asyncio.Lock()
    last_input = time.monotonic()
    tunnel = touch = server = heartbeat = volume_watch = None
    ready = False
    failure = None
    async def watch_volume():
        nonlocal failure
        while True:
            try:
                settings = read_settings(args.settings_file, player.volume)
                player.volume, player.boost_db = settings['volume'], settings['boost_db']
                behaviors.mode = settings['expressions'] if continuous else 'off'
            except (OSError, ValueError):
                failure = 'Live volume settings are unavailable or invalid.'
                stop.set()
                return
            await asyncio.sleep(.2)
    async def publish_status():
        while True:
            status.write(phase='ready' if ready else 'starting', ready=ready,
                microphone_active=(host.running and host.frames > 0 and not host.error and (not native or (host.last_native_frame is not None and time.monotonic()-host.last_native_frame < 1))) if host else capture_lock.locked(), speaking=player.clip is not None,
                input_idle_seconds=round(time.monotonic() - (host.last_activity if host else last_input), 1),
                speaker_segments_completed=player.segments_played, volume=player.volume,
                boost_db=player.boost_db, expressions=behaviors.mode,
                expressions_state=behaviors.state, expressions_error=behaviors.error)
            await asyncio.sleep(2)
    async def capture(reader, writer):
        nonlocal last_input, failure
        task = asyncio.current_task()
        active.add(task)
        accepted = False
        claimed = False
        try:
            header = json.loads(await asyncio.wait_for(read_frame(reader, 4096), 2))
            allowed = (header.get('device', '').lower() == args.serial.lower()
                       and header.get('sample_rate') == 16000 and header.get('format') == 'pcm_s16le'
                       and not capture_lock.locked() and not stop.is_set() and not session.error)
            if allowed:
                await capture_lock.acquire()
                claimed = True
            writer.write(b'\x01' if allowed else b'\x00')
            await writer.drain()
            if not allowed:
                return
            accepted = True
            if accepted:
                if not continuous:
                    await player.interrupt()
                last_input = time.monotonic()
                count = 0
                while True:
                    pcm = await asyncio.wait_for(read_frame(reader), 5)
                    if not pcm:
                        break
                    if not continuous:
                        session.input.append(pcm)
                    count += len(pcm)
                    if count > 32000 * 20:
                        raise RuntimeError('Capture exceeded twenty seconds.')
                # Keep the speaker quiet until queued input has reached Live.
                while not continuous and session.input.data and not session.error:
                    await asyncio.sleep(.01)
                if not count:
                    raise RuntimeError('Empty live capture.')
                print(json.dumps({'input': 'drained' if continuous else 'delivered', 'audio_seconds': round(count/32000, 2)}), flush=True)
        except (OSError, ValueError, RuntimeError, asyncio.TimeoutError, asyncio.IncompleteReadError):
            if accepted:
                print(json.dumps({'input': 'failed', 'session': 'stopping'}), flush=True)
                failure = 'Native request capture failed.'
                stop.set()
        finally:
            if claimed:
                capture_lock.release()
            if accepted and not continuous:
                player.input_active = False
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            active.discard(task)

    async def touch_stop():
        nonlocal failure
        stream = robot.stub.EventStream(p.EventRequest(white_list=p.FilterList(list=['robot_state'])))
        baseline = None
        count = 0
        try:
            async for event in stream:
                if event.event.WhichOneof('event_type') != 'robot_state':
                    continue
                behaviors.observe(event.event.robot_state)
                value = event.event.robot_state.touch_data.raw_touch_value
                if baseline is None:
                    baseline = value
                count = count + 1 if value > baseline + 50 else 0
                if count >= 5:
                    print(json.dumps({'stop': 'touch'}), flush=True)
                    stop.set()
                    return
        except Exception:
            failure = 'Touch stop event stream failed.'
            print(json.dumps({'stop_control': 'event_stream_failed', 'session': 'stopping'}), flush=True)
            stop.set()
        finally:
            stream.cancel()

    try:
        print(json.dumps({'robot': await robot.status()}), flush=True)
        if getattr(args, 'settings_file', None):
            settings = read_settings(args.settings_file, args.volume)
            player.volume, player.boost_db = settings['volume'], settings['boost_db']
            behaviors.mode = settings['expressions'] if continuous else 'off'
            volume_watch = asyncio.create_task(watch_volume())
        if host:
            # Verify local input and control before opening a paid session.
            await controls.enter_async_context(robot.control())
            await host.start(session)
            resources.push_async_callback(host.close)
            if host.error or not host.running:
                raise RuntimeError(host.error or 'Continuous input failed preflight.')
        await session.start()
        if status:
            heartbeat = asyncio.create_task(publish_status())
        if native and getattr(args, 'ready_tone', False):
            async def cue():
                yield tone_pcm(.35)
            await robot.play_stream(cue(), min(25, player.volume), on_render=host.rendered, on_cancel=host.cancel_render)
        player.task = asyncio.create_task(player.run())
        touch = asyncio.create_task(touch_stop())
        if continuous:
            behaviors.task = asyncio.create_task(behaviors.run())
        manager = contextlib.nullcontext(None) if (native or args.local_socket) else tempfile.TemporaryDirectory(prefix='vl-', dir='/private/tmp')
        with manager as directory:
            if not native:
                path = Path(args.local_socket) if args.local_socket else Path(directory) / 'live.sock'
                path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
                server = await asyncio.start_unix_server(capture, path=str(path))
                os.chmod(path, 0o600)
                if not args.local_socket:
                    tunnel = await asyncio.create_subprocess_exec('ssh', '-NT', '-o', 'BatchMode=yes',
                        '-o', 'HostKeyAlias=escapepod.local', '-o', 'ExitOnForwardFailure=yes',
                        '-o', 'StreamLocalBindUnlink=yes', '-o', 'ServerAliveInterval=15',
                        '-R', args.remote_socket + ':' + str(path), args.ssh_target,
                        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
                    await asyncio.sleep(.5)
                    if tunnel.returncode is not None:
                        raise RuntimeError('SSH audio tunnel failed to start.')
            ready = True
            print(json.dumps({'conversation': 'ready', 'voice': session.voice,
                'wake_phrase_each_turn': not continuous, 'input_source': ('Vector internal microphones' if native else 'host microphone') if continuous else 'Vector wake-word requests', 'max_seconds': args.seconds,
                'stop': 'hold Vector back touch sensor or Ctrl-C'}), flush=True)
            if args.audition:
                with tempfile.TemporaryDirectory(prefix='va-', dir='/private/tmp') as audition_dir:
                    source, wav = Path(audition_dir)/'ask.aiff', Path(audition_dir)/'ask.wav'
                    await asyncio.to_thread(subprocess.run, ['say','-o',str(source),
                        'Hello Vector. Introduce yourself in one short sentence.'],check=True)
                    await asyncio.to_thread(subprocess.run,['afconvert','-f','WAVE','-d','LEI16@16000','-c','1',str(source),str(wav)],check=True)
                    with wave.open(str(wav)) as audio:
                        pcm=audio.readframes(audio.getnframes())
                for offset in range(0,len(pcm),320):
                    session.input.append(pcm[offset:offset+320])
                    await asyncio.sleep(.01)
            deadline = time.monotonic() + args.seconds
            while time.monotonic() < deadline:
                if stop.is_set():
                    break
                failure = failure or session.error or player.error or getattr(robot, 'control_error', None) or (host.error if host else None) or ('SSH bridge disconnected.' if tunnel and tunnel.returncode is not None else None)
                if failure:
                    break
                if time.monotonic() - (host.last_activity if host else last_input) >= 60 and not player.clip and player.queue.empty() and not capture_lock.locked() and not session.backend_pending:
                    print(json.dumps({'stop': 'idle_timeout'}), flush=True)
                    break
                await asyncio.sleep(.1)
            if time.monotonic() >= deadline:
                print(json.dumps({'stop': 'maximum_duration'}), flush=True)
            stop.set()
    except Exception as exc:
        failure = failure or (str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__)
        raise
    finally:
        if volume_watch:
            volume_watch.cancel()
            await asyncio.gather(volume_watch, return_exceptions=True)
        if heartbeat:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        if status:
            status.write(phase='stopping', ready=False, microphone_active=False, speaking=False)
        if server:
            server.close()
            await server.wait_closed()
            if args.local_socket:
                Path(args.local_socket).unlink(missing_ok=True)
        for task in list(active):
            task.cancel()
        await asyncio.gather(*active, return_exceptions=True)
        if touch:
            touch.cancel()
            await asyncio.gather(touch, return_exceptions=True)
        if tunnel and tunnel.returncode is None:
            tunnel.terminate()
            try:
                await asyncio.wait_for(tunnel.wait(), 5)
            except asyncio.TimeoutError:
                tunnel.kill()
                await tunnel.wait()
        await behaviors.close()
        await player.close()
        if host:
            await host.close()
        # Return normal robot behavior before waiting for cloud usage finalization.
        # The outer stack remains a fallback for startup/cleanup failures.
        try:
            await controls.aclose()
        finally:
            await session.close()
        failure = failure or session.error or player.error or getattr(robot, 'control_error', None) or (host.error if host else None)
        if status:
            status.write(phase='error' if failure else 'closed',
                ready=False, microphone_active=False, speaking=False,
                error=failure, finalized=session.finalized.is_set(),
                usage=session.usage, speaker_segments_completed=player.segments_played,
                boost_db=player.boost_db, expressions=behaviors.mode,
                expressions_state=behaviors.state, expressions_error=behaviors.error,
                expression_frames=behaviors.frames_sent, head_nods=behaviors.nods_completed)
        if native:
            print(json.dumps({'native_microphone': host.native_stats.report(),
                'source_clock': host.clock.report() if hasattr(host,'clock') else None,
                'worker_error': getattr(host,'worker_error',None),
                'aec': 'WebRTC; acoustic effectiveness requires the room test'}), flush=True)
        if hasattr(session, 'diagnostics'):
            print(json.dumps({'live_audio_diagnostics': session.diagnostics()}), flush=True)
        print(json.dumps({'conversation': 'closed', 'final_usage': session.usage,
            'finalized': session.finalized.is_set(), 'speaker_segments_completed': player.segments_played,
            'error': failure}), flush=True)

    if failure:
        raise RuntimeError('Voice session failed; see its private runtime status.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key-file')
    parser.add_argument('--input-mode', choices=['wake', 'continuous'], default='wake')
    parser.add_argument('--input-source', choices=['host', 'vector-sdk'], default='host')
    parser.add_argument('--microphone-name', help='Exact unique host device name, required for continuous mode.')
    parser.add_argument('--audio-python', default=str(Path(__file__).with_name('host-audio') / '.venv/bin/python'), help='Isolated host-audio worker interpreter.')
    parser.add_argument('--aec-delay-ms', type=int, default=200, help='Estimated Vector playback/transport delay; needs an acoustic rehearsal.')
    parser.add_argument('--wirepod', default='http://escapepod.local:8080')
    parser.add_argument('--serial', default='00a14a38')
    parser.add_argument('--remote-socket', default='/home/pi/vector-live-runtime/live.sock')
    parser.add_argument('--ssh-target', default='pi@escapepod.local', help='Mac bridge SSH destination; configurable when the network changes.')
    parser.add_argument('--local-socket', help='Run directly on the Pi without an SSH bridge.')
    parser.add_argument('--seconds', type=int, default=180)
    parser.add_argument('--volume', type=int, default=80)
    parser.add_argument('--settings-file', help='Private live operator settings; volume is updated without reopening the session.')
    parser.add_argument('--status-file', help='Private operator-console heartbeat, containing no audio or transcript.')
    parser.add_argument('--audition', action='store_true', help='Use synthetic speech to request a short introduction.')
    parser.add_argument('--ready-tone', action=argparse.BooleanOptionalAction, default=True, help='Play a short local cue after native input and Live are ready.')
    parser.add_argument('--greet', action='store_true', help='Ask GPT-Live to greet the person when ready.')
    args = parser.parse_args()
    if not 10 <= args.seconds <= 600 or not 0 <= args.volume <= 100:
        parser.error('Duration must be 10–600 seconds and volume 0–100.')
    if args.input_mode == 'continuous' and ((args.input_source == 'host' and not args.microphone_name) or not Path(args.audio_python).is_file() or not 0 <= args.aec_delay_ms <= 1000):
        parser.error('Continuous mode requires its selected source, isolated audio worker, and AEC delay 0–1000 ms.')
    if args.audition and args.input_mode == 'continuous':
        parser.error('Synthetic audition cannot be mixed into continuous host input.')
    if args.audition and sys.platform != 'darwin':
        parser.error('Synthetic audition uses macOS say; use --greet on the Pi.')
    try:
        asyncio.run(conversation(args))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        parser.exit(1, f'Conversation failed: {type(exc).__name__}\n')
