"""Short GPT-Live test with synthetic speech; no room microphone opens."""
import argparse
import asyncio
import json
import math
import struct
import subprocess
import tempfile
import time
import wave
from pathlib import Path

from live_voice import LiveVoice, read_key


async def run(args):
    with tempfile.TemporaryDirectory(prefix='vector-live-') as directory:
        source, target = Path(directory) / 'ask.aiff', Path(directory) / 'ask.wav'
        if getattr(args, 'input_wav', None):
            target = Path(args.input_wav)
        else:
            await asyncio.to_thread(subprocess.run, ['say', '-o', str(source),
                "Hello Vector. Please say, my new voice is ready for a little adventure."], check=True)
            await asyncio.to_thread(subprocess.run, ['afconvert', '-f', 'WAVE', '-d', 'LEI16@16000', '-c', '1',
                str(source), str(target)], check=True)
        with wave.open(str(target)) as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000) or audio.getnframes() > 15*16000:
                raise ValueError('Probe requires at most15seconds of mono PCM16 WAV at16000Hz.')
        if args.audio_python:
            code = """import sys,wave
from native_audio_worker import NativeProcessor
with wave.open(sys.argv[1]) as f: data=f.readframes(f.getnframes())
p=NativeProcessor(200)
for offset in range(0,len(data),320):
 sys.stdout.buffer.write(p.process(b'C'+data[offset:offset+320].ljust(320,b'\\0')))
"""
            result = await asyncio.to_thread(subprocess.run, [args.audio_python, '-c', code, str(target)],
                env={**__import__('os').environ,'PYTHONPATH':str(Path(__file__).parent)},
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
            request=result.stdout
        else:
            with wave.open(str(target)) as audio:
                request = audio.readframes(audio.getnframes())
    output = bytearray()
    chunks = []
    started = time.monotonic()
    async def receive(pcm):
        if len(output) + len(pcm) > 16000 * 2 * 30:
            raise RuntimeError('Probe output exceeded thirty seconds.')
        output.extend(pcm)
        samples = struct.unpack('<' + 'h' * (len(pcm) // 2), pcm)
        rms = math.sqrt(sum(s*s for s in samples) / max(1, len(samples)))
        chunks.append({'at': round(time.monotonic() - started, 3), 'bytes': len(pcm),
                       'dbfs': round(20 * math.log10(max(rms, 1) / 32768), 1)})
    session = LiveVoice(read_key(args.key_file), receive, input_mode='continuous', greet=True)
    try:
        await session.start()
        print(json.dumps({'live': 'started', 'voice': session.voice, 'microphone': 'none'}), flush=True)
        deadline = time.monotonic() + args.seconds
        for offset in range(0, len(request), 320):
            session.input.append(request[offset:offset+320])
            await asyncio.sleep(.01)
        while time.monotonic() < deadline and not session.error:
            await asyncio.sleep(.1)
    finally:
        await session.close()
    print(json.dumps({'finalized': session.finalized.is_set(), 'usage': session.usage,
        'audio_seconds': round(len(output) / 32000, 3), 'max_output_dbfs': max((c['dbfs'] for c in chunks),default=-90), 'diagnostics': session.diagnostics(),
        'assistant_text': ''.join(c['text'] for c in session.captions if c['role']=='assistant'),
        'error': session.error}), flush=True)
    if session.error or not session.finalized.is_set() or not output:
        raise RuntimeError('Voice probe did not finish successfully.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key-file')
    parser.add_argument('--audio-python', help='Optionally pass synthetic speech through the native echo processor first.')
    parser.add_argument('--input-wav', help='Synthetic PCM16/16kHz mono fixture, for platforms without macOS say.')
    parser.add_argument('--seconds', type=float, default=15)
    args = parser.parse_args()
    if not 8 <= args.seconds <= 30:
        parser.error('Probe duration must be 8–30 seconds.')
    try:
        asyncio.run(run(args))
    except Exception as exc:
        parser.exit(1, f'Voice probe failed: {type(exc).__name__}\n')
