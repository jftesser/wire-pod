"""Observe real wire-pod request PCM through a private Unix socket; never record it."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import stat
import struct
import time
from pathlib import Path
from types import SimpleNamespace

from pcm_stats import AudioStats


async def read_frame(reader, maximum=128 * 1024):
    length = struct.unpack('>I', await reader.readexactly(4))[0]
    if length > maximum:
        raise ValueError('Oversized tap frame.')
    return await reader.readexactly(length)


async def serve(args):
    path = Path(args.socket)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        if not stat.S_ISSOCK(path.lstat().st_mode):
            raise ValueError('Refusing to replace a non-socket path.')
        raise ValueError('Socket already exists; check whether an observer is running.')
    complete = asyncio.Event()
    result = 0
    active = set()
    async def capture(reader, writer):
        nonlocal result
        task = asyncio.current_task()
        active.add(task)
        stats = AudioStats()
        started = time.monotonic()
        try:
            header = json.loads(await asyncio.wait_for(read_frame(reader, 4096), 3))
            if header.get('device', '').lower() != args.serial.lower():
                raise ValueError('Unexpected robot.')
            if header.get('sample_rate') != 16000 or header.get('format') != 'pcm_s16le':
                raise ValueError('Unsupported tap audio format.')
            print(json.dumps({'capture': 'started', 'device': header['device'], 'kind': header.get('kind')}), flush=True)
            while True:
                pcm = await asyncio.wait_for(read_frame(reader), 5)
                if not pcm:
                    break
                stats.add(SimpleNamespace(signal_power=pcm, group_id=stats.frames))
            report = stats.report()
            report['wall_seconds'] = round(time.monotonic() - started, 3)
            report['capture_complete'] = True
            print(json.dumps({'capture': report}), flush=True)
            if not stats.samples or report['suspected_test_or_stuck_signal']:
                result = 3
            complete.set()
        except (ValueError, asyncio.TimeoutError, asyncio.IncompleteReadError, OSError) as exc:
            print(json.dumps({'capture': 'incomplete', 'error': type(exc).__name__, 'frames': stats.frames}), flush=True)
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            active.discard(task)
    server = await asyncio.start_unix_server(capture, path=str(path))
    os.chmod(path, 0o600)
    print(json.dumps({'observer': 'ready', 'socket': str(path), 'timeout_seconds': args.timeout}), flush=True)
    try:
        async with server:
            await asyncio.wait_for(complete.wait(), args.timeout)
    except asyncio.TimeoutError:
        print(json.dumps({'observer': 'timeout', 'capture_received': False}), flush=True)
        return 2
    finally:
        for task in list(active):
            task.cancel()
        await asyncio.gather(*active, return_exceptions=True)
        path.unlink(missing_ok=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', default='/run/vector-live/audio.sock')
    parser.add_argument('--serial', required=True)
    parser.add_argument('--timeout', type=float, default=90)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 300:
        parser.error('Timeout must be 1–300 seconds.')
    raise SystemExit(asyncio.run(serve(args)))
