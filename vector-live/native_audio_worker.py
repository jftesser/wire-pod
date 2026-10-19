"""Process Vector PCM and speaker reference over private pipes; opens no devices."""
import argparse
import asyncio
import contextlib
import json
import signal
import sys
from livekit import rtc
from tap_observer import read_frame


class NativeProcessor:
    def __init__(self, delay_ms):
        self.apm = rtc.AudioProcessingModule(echo_cancellation=True, noise_suppression=True,
                                            high_pass_filter=True, auto_gain_control=False)
        self.delay_ms = delay_ms
        self.reference = bytearray()

    def frame(self, pcm):
        return rtc.AudioFrame(data=pcm, sample_rate=16000, num_channels=1, samples_per_channel=160)

    def process(self, message):
        kind, pcm = message[:1], message[1:]
        if kind == b'R':
            if not pcm or len(pcm)>1024 or len(pcm)%2 or len(self.reference)+len(pcm)>32000:
                raise RuntimeError('Invalid or excessive speaker reference.')
            self.reference.extend(pcm)
        elif kind == b'X' and not pcm:
            self.reference.clear()
        elif kind == b'C' and len(pcm)==320:
            reverse=bytes(self.reference[:320]).ljust(320,b'\0')
            del self.reference[:320]
            self.apm.process_reverse_stream(self.frame(reverse))
            frame=self.frame(pcm)
            self.apm.set_stream_delay_ms(self.delay_ms)
            self.apm.process_stream(frame)
            return bytes(frame.data)
        else:
            raise RuntimeError('Invalid native audio message.')
        return None


async def run(args):
    processor=NativeProcessor(args.aec_delay_ms)
    loop=asyncio.get_running_loop()
    reader=asyncio.StreamReader(limit=8192)
    transport,_=await loop.connect_read_pipe(lambda:asyncio.StreamReaderProtocol(reader),sys.stdin.buffer)
    output_transport,output_protocol=await loop.connect_write_pipe(asyncio.streams.FlowControlMixin,sys.stdout.buffer)
    writer=asyncio.StreamWriter(output_transport,output_protocol,None,loop)
    try:
        writer.write(b'{"ready":true,"sample_rate":16000,"frame_bytes":320}\n')
        await writer.drain()
        while True:
            message=await read_frame(reader,1025)
            if not message: return
            pcm=processor.process(message)
            if pcm is not None:
                writer.write(len(pcm).to_bytes(4,'big')+pcm)
                await asyncio.wait_for(writer.drain(),.5)
    finally:
        transport.close()
        writer.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--aec-delay-ms',type=int,default=200)
    args=parser.parse_args()
    if not 0<=args.aec_delay_ms<=1000:parser.error('Delay must be0–1000ms.')
    try:asyncio.run(run(args))
    except (KeyboardInterrupt,BrokenPipeError):pass
    except Exception as exc:
        # Internal fixed messages only: never include PCM or room speech.
        reasons = {'Invalid or excessive speaker reference.', 'Invalid native audio message.'}
        reason = str(exc) if isinstance(exc, RuntimeError) and str(exc) in reasons else type(exc).__name__
        print(json.dumps({'processor_error': reason}), file=sys.stderr, flush=True)
        sys.exit(1)
