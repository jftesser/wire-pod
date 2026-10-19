"""On-demand voice controller, served only over a private Unix socket.

No microphone, robot control, or paid session opens until an explicit start.
Serve directly on the Pi, or forward a remote controller through SSH.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import signal
import stat
import sys
import tempfile
import time
from pathlib import Path

from aiohttp import web
from voice_settings import read_settings, save_settings, validate_options


class Controller:
    def __init__(self, args, directory):
        self.args, self.directory = args, Path(directory)
        self.process = None
        self.stopping = False
        self.stop_task = self.log_task = None
        self.lock = asyncio.Lock()
        self.status_path = self.directory / 'session.json'
        self.last_error = None
        self.closing = False
        self.spawned_at = None
        self.settings_file = getattr(args, 'settings_file', None)
        self.settings = read_settings(self.settings_file, args.volume)
        self.volume = self.settings['volume']

    def status(self):
        native = getattr(self.args, 'input_source', 'host') == 'vector-sdk'
        configured = bool((native or self.args.microphone_name) and Path(self.args.audio_python).is_file())
        result = dict(mode='legacy', phase='off', ready=False, active=False,
            continuous_available=configured, requires_wake_phrase=False,
            continuous_reason=('Uses Vector’s own microphones. Start checks the running firmware and fresh audio before opening Live.' if native and configured else '') if configured else 'Configure the controller input source and its isolated audio environment.',
            controller_location='Pi' if getattr(self.args, 'local_control_socket', None) else 'remote computer',
            source='Vector internal microphones (continuous SDK)' if native else 'Host microphone: ' + (self.args.microphone_name or 'not selected'),
            microphone_active=False, speaking=False, volume=self.volume,
            configured_volume=self.volume, volume_available=bool(self.settings_file), volume_pending=False)
        result.update(boost_db=self.settings['boost_db'], expressions=self.settings['expressions'],
                      configured_options=dict(self.settings), expressions_state='off', expressions_error=None)
        if not self.process:
            return result
        active = self.process.returncode is None
        result.update(active=active)
        try:
            # Ignore another process's or an earlier session's heartbeat.
            if self.status_path.stat().st_size > 65536:
                raise ValueError('Oversized status.')
            heartbeat = json.loads(self.status_path.read_text())
            if heartbeat.get('pid') != self.process.pid:
                raise ValueError('PID mismatch.')
            age = time.time() - heartbeat['heartbeat']
            if active and not -1 <= age <= 7:
                raise ValueError('Stale status.')
        except (OSError, ValueError, KeyError, TypeError):
            heartbeat = {}
        if active:
            starting = self.spawned_at is not None and time.monotonic() - self.spawned_at < 7
            result.update(mode='continuous', phase=('starting' if starting else 'unverified') if not heartbeat else heartbeat.get('phase', 'unverified'))
            if heartbeat:
                for key in ('ready', 'microphone_active', 'speaking', 'elapsed_seconds', 'volume', 'speaker_segments_completed', 'boost_db', 'expressions', 'expressions_state', 'expressions_error'):
                    if key in heartbeat:
                        result[key] = heartbeat[key]
            if self.stopping or self.closing:
                result.update(phase='stopping', ready=False, microphone_active=False)
            result['volume_pending'] = result['volume'] != self.volume
        else:
            for key in ('finalized', 'usage', 'elapsed_seconds', 'speaker_segments_completed'):
                if key in heartbeat:
                    result[key] = heartbeat[key]
            if self.process.returncode != 0 or heartbeat.get('error') or self.last_error:
                result.update(phase='error', error='Voice session stopped with an error; inspect the local console.')
        return result

    async def start(self):
        async with self.lock:
            if self.stopping or self.closing:
                raise ValueError('Wait for the current session to finish closing.')
            if self.process and self.process.returncode is None:
                return
            if not self.status()['continuous_available']:
                raise ValueError('Configure the selected input and its audio environment first.')
            self.status_path.unlink(missing_ok=True)
            self.last_error = None
            command = [sys.executable, str(Path(__file__).with_name('conversation.py')),
                '--input-mode', 'continuous', '--input-source', getattr(self.args, 'input_source', 'host'),
                '--audio-python', str(self.args.audio_python), '--aec-delay-ms', str(self.args.aec_delay_ms),
                '--wirepod', self.args.wirepod, '--serial', self.args.serial,
                '--ssh-target', self.args.ssh_target, '--remote-socket', self.args.remote_audio_socket,
                '--key-file', self.args.key_file, '--seconds', str(self.args.seconds),
                '--volume', str(self.volume), '--status-file', str(self.status_path), '--greet']
            if self.settings_file:
                command += ['--settings-file', self.settings_file]
            if getattr(self.args, 'input_source', 'host') == 'host':
                command += ['--microphone-name', self.args.microphone_name]
            else:
                command += ['--ready-tone']
            self.process = await asyncio.create_subprocess_exec(*command,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, limit=8192)
            self.spawned_at = time.monotonic()
            self.log_task = asyncio.create_task(self.drain_log(self.process))

    async def drain_log(self, process):
        # No transcript/audio is logged by the companion. Drain pipes so an
        # operator's closed terminal cannot strand the child on a full pipe.
        try:
            while chunk := await process.stdout.read(4096):
                if getattr(self.args, 'session_log', None):
                    fd = os.open(self.args.session_log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                    with os.fdopen(fd, 'ab') as output:
                        output.write(chunk)
        except Exception:
            self.last_error = 'Companion log pipe failed.'
            self.request_stop()

    def request_stop(self):
        if not self.stop_task or self.stop_task.done():
            self.stopping = True
            self.stop_task = asyncio.create_task(self.stop())

    async def stop(self):
        async with self.lock:
            try:
                if self.process and self.process.returncode is None:
                    with contextlib.suppress(ProcessLookupError):
                        self.process.send_signal(signal.SIGINT)
                    try:
                        await asyncio.wait_for(self.process.wait(), 35)
                    except asyncio.TimeoutError:
                        self.last_error = 'Companion exceeded shutdown deadline.'
                        self.process.kill()
                        await self.process.wait()
                if self.log_task:
                    await asyncio.gather(self.log_task, return_exceptions=True)
            finally:
                self.stopping = False

    async def close(self):
        self.closing = True
        if self.stop_task and not self.stop_task.done():
            await self.stop_task
        else:
            await self.stop()

    async def handle(self, request):
        if request.path == '/status' and request.method == 'GET':
            return web.json_response(self.status(), headers={'Cache-Control': 'no-store'})
        if request.path not in ('/start', '/stop', '/volume', '/options') or request.method != 'POST':
            raise web.HTTPMethodNotAllowed(request.method, ['POST'])
        if request.content_type != 'application/json':
            raise web.HTTPUnsupportedMediaType()
        try:
            body = await request.json()
            if request.path in ('/volume', '/options'):
                if not self.settings_file:
                    raise ValueError('Persistent voice settings are not configured.')
                validate_options(body)
                if (request.path == '/volume' and set(body) != {'volume'}) or not body:
                    raise ValueError('Supply the requested voice setting.')
                save_settings(self.settings_file, body)
                self.settings = read_settings(self.settings_file)
                self.volume = self.settings['volume']
                return web.json_response({**self.settings, 'saved': True})
            if body != (dict(mode='continuous') if request.path == '/start' else {}):
                raise ValueError('Invalid fixed control request.')
            if request.path == '/start':
                await self.start()
            else:
                self.request_stop()
        except (ValueError, json.JSONDecodeError) as exc:
            return web.json_response({'error': str(exc)}, status=409)
        except OSError:
            return web.json_response({'error': 'Cannot save voice settings.'}, status=503)
        return web.json_response({'action': request.path[1:], 'state': 'pending'}, status=202)


async def serve(args):
    quit_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, quit_event.set)
    with tempfile.TemporaryDirectory(prefix='vector-control-') as directory:
        os.chmod(directory, 0o700)
        controller = Controller(args, directory)
        app = web.Application(client_max_size=1024)
        app.router.add_route('*', '/{action}', controller.handle)
        runner = web.AppRunner(app)
        tunnel = watcher = None
        local_socket = getattr(args, 'local_control_socket', None)
        socket_bound = False
        try:
            await runner.setup()
            socket = str(Path(local_socket) if local_socket else Path(directory) / 'control.sock')
            if local_socket:
                path = Path(socket)
                if not path.is_absolute() or not path.parent.is_dir():
                    raise ValueError('Local control socket needs an absolute path in an existing private directory.')
                if path.parent.stat().st_mode & 0o077:
                    raise ValueError('Local control socket directory must be private (0700).')
                if path.exists() or path.is_symlink():
                    if not stat.S_ISSOCK(path.lstat().st_mode):
                        raise ValueError('Refusing to replace a non-socket control path.')
                    try:
                        reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(socket), 1)
                    except (ConnectionRefusedError, FileNotFoundError):
                        path.unlink(missing_ok=True)
                    else:
                        writer.close()
                        await writer.wait_closed()
                        raise ValueError('Another controller is already listening.')
            await web.UnixSite(runner, socket).start()
            socket_bound = True
            os.chmod(socket, 0o600)
            if not local_socket:
                tunnel = await asyncio.create_subprocess_exec('ssh', '-NT', '-o', 'BatchMode=yes',
                    '-o', 'HostKeyAlias=escapepod.local', '-o', 'ExitOnForwardFailure=yes',
                    '-o', 'StreamLocalBindUnlink=yes', '-o', 'ServerAliveInterval=5',
                    '-o', 'ServerAliveCountMax=2', '-R', args.remote_control_socket + ':' + socket,
                    args.ssh_target, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                await asyncio.sleep(.5)
                if tunnel.returncode is not None:
                    raise RuntimeError('Private controller tunnel failed to start.')
                async def watch_tunnel():
                    await tunnel.wait()
                    quit_event.set()
                watcher = asyncio.create_task(watch_tunnel())
            print('Vector voice controller ready; voice remains off until web-admin Start.', flush=True)
            await quit_event.wait()
        finally:
            # The cloud child closes even when the admin SSH bridge disconnects.
            await controller.close()
            if tunnel and tunnel.returncode is None:
                tunnel.terminate()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(tunnel.wait(), 5)
                if tunnel.returncode is None:
                    tunnel.kill()
                    await tunnel.wait()
            if watcher:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
            await runner.cleanup()
            if local_socket and socket_bound:
                Path(socket).unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key-file', required=True)
    parser.add_argument('--microphone-name')
    parser.add_argument('--input-source', choices=['host', 'vector-sdk'], default='host')
    parser.add_argument('--session-log', help='Private metadata-only child log; no audio or transcripts.')
    parser.add_argument('--audio-python', default=str(Path(__file__).with_name('host-audio') / '.venv/bin/python'))
    parser.add_argument('--aec-delay-ms', type=int, default=200)
    parser.add_argument('--seconds', type=int, default=600)
    parser.add_argument('--volume', type=int, default=80)
    parser.add_argument('--settings-file', help='Private persistent operator settings shared with the active child.')
    parser.add_argument('--wirepod', default='http://escapepod.local:8080')
    parser.add_argument('--serial', default='00a14a38')
    parser.add_argument('--ssh-target', default='pi@escapepod.local')
    parser.add_argument('--remote-control-socket', default='/home/pi/vector-live-runtime/control.sock')
    parser.add_argument('--local-control-socket', help='Serve directly on this machine; no SSH tunnel is opened.')
    parser.add_argument('--remote-audio-socket', default='/home/pi/vector-live-runtime/live.sock')
    args = parser.parse_args()
    if not 10 <= args.seconds <= 600 or not 0 <= args.volume <= 100 or not 0 <= args.aec_delay_ms <= 1000:
        parser.error('Duration10–600 seconds, volume0–100, and AEC delay0–1000 ms required.')
    try:
        asyncio.run(serve(args))
    except Exception as exc:
        parser.exit(1, 'Controller failed: ' + type(exc).__name__ + '\n')
