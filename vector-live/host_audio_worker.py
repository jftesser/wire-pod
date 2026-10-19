"""Private stdio PCM worker. Never connects to OpenAI, records, or plays sound."""
import argparse
import asyncio
import contextlib
import json
import queue
import signal
import sys

from host_audio import HostMicrophone
from tap_observer import read_frame


async def run(args):
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    microphone = HostMicrophone(args.device_name, args.aec_delay_ms)
    reader = asyncio.StreamReader(limit=4096)
    protocol = asyncio.StreamReaderProtocol(reader)
    transport, _ = await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)
    output_transport, output_protocol = await loop.connect_write_pipe(asyncio.streams.FlowControlMixin, sys.stdout.buffer)
    writer = asyncio.StreamWriter(output_transport, output_protocol, None, loop)
    tasks = []
    async def reference():
        try:
            while True:
                pcm = await read_frame(reader, 1024)
                microphone.rendered(pcm) if pcm else microphone.cancel_render()
        finally:
            stop.set()
    async def capture():
        try:
            while not stop.is_set():
                if microphone.error:
                    raise RuntimeError(microphone.error)
                import time
                if time.monotonic() - microphone.last_frame > 1:
                    raise RuntimeError('Microphone stalled.')
                for _ in range(50):
                    try:
                        pcm = microphone.captured.get_nowait()
                    except queue.Empty:
                        break
                    writer.write(len(pcm).to_bytes(4, 'big') + pcm)
                    await asyncio.wait_for(writer.drain(), .5)
                await asyncio.sleep(.01)
        finally:
            stop.set()
    try:
        microphone.start()
        writer.write(b'{"ready":true,"sample_rate":16000,"frame_bytes":320}\n')
        await writer.drain()
        tasks = [asyncio.create_task(reference()), asyncio.create_task(capture())]
        await stop.wait()
    finally:
        microphone.close()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        transport.close()
        writer.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device-name')
    parser.add_argument('--list-devices', action='store_true', help='List input names without opening capture.')
    parser.add_argument('--aec-delay-ms', type=int, default=200)
    args = parser.parse_args()
    if args.list_devices:
        import sounddevice
        print(json.dumps([d['name'] for d in sounddevice.query_devices() if d['max_input_channels'] > 0]))
        sys.exit(0)
    if not args.device_name:
        parser.error('Select an explicit --device-name.')
    try:
        asyncio.run(run(args))
    except Exception:
        # No device names, captured audio or stack traces enter the binary pipe.
        print(json.dumps({'ready': False, 'error': 'Host audio helper failed.'}), flush=True)
        sys.exit(1)
