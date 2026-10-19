import asyncio
import json
import struct
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from tap_observer import read_frame, serve


def test_rejects_oversized_frame_before_reading_payload():
    async def check():
        reader = asyncio.StreamReader()
        reader.feed_data(struct.pack('>I', 200000))
        with pytest.raises(ValueError, match='Oversized'):
            await read_frame(reader)
    asyncio.run(check())


def test_private_socket_capture_completes_without_recording(capsys):
    async def check(tmp_path):
        path = tmp_path / 'audio.sock'
        args = SimpleNamespace(socket=str(path), serial='robot', timeout=3)
        observer = asyncio.create_task(serve(args))
        try:
            for _ in range(100):
                if observer.done():
                    await observer
                if path.exists():
                    break
                await asyncio.sleep(.01)
            assert path.stat().st_mode & 0o777 == 0o600
            _, writer = await asyncio.open_unix_connection(str(path))
            for data in [json.dumps({'device': 'robot', 'sample_rate': 16000,
                    'format': 'pcm_s16le', 'kind': 'intentgraph'}).encode(),
                    b'\x01\x00' * 1600, b'']:
                writer.write(struct.pack('>I', len(data)) + data)
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            assert await observer == 0
            assert not path.exists()
            assert list(tmp_path.iterdir()) == []
        finally:
            observer.cancel()
            await asyncio.gather(observer, return_exceptions=True)
    with tempfile.TemporaryDirectory(prefix='vt-', dir='/tmp') as directory:
        asyncio.run(check(Path(directory)))
    results = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    report = results[-1]['capture']
    assert report['capture_complete']
    assert report['audio_seconds'] == .1
