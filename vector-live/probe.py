"""Status by default; microphone and audible tests require explicit flags."""
import argparse
import asyncio
import json
import time

import grpc
from vector_audio import discover, VectorAudio, tone_pcm


async def run(args):
    pairing = await asyncio.to_thread(discover, args.wirepod, args.serial, args.certificate, args.trust_local_certificate)
    robot = VectorAudio(pairing)
    try:
        print(json.dumps({"robot": await robot.status()}, indent=2), flush=True)
        if args.duplex:
            async with robot.control():
                arrivals = []
                async def count_frame(pcm):
                    arrivals.append(time.monotonic())
                microphone = asyncio.create_task(robot.listen(4, count_frame))
                try:
                    await asyncio.sleep(1)
                    play_start = time.monotonic()
                    await robot.play(tone_pcm(), args.volume)
                    play_end = time.monotonic()
                    report = await microphone
                    report["frames_delivered_during_playback"] = sum(play_start <= t <= play_end for t in arrivals)
                    if not report["frames_delivered_during_playback"]:
                        raise RuntimeError("No microphone frames arrived during playback.")
                    print(json.dumps({"simultaneous_capture": report}, indent=2))
                    if report["suspected_test_or_stuck_signal"]:
                        raise RuntimeError("SDK delivers repeated non-silent data; microphone authenticity test failed.")
                finally:
                    microphone.cancel()
                    await asyncio.gather(microphone, return_exceptions=True)
        else:
            if args.listen_seconds:
                report = await robot.listen(args.listen_seconds)
                print(json.dumps({"microphone": report}, indent=2))
                if report["suspected_test_or_stuck_signal"]:
                    raise RuntimeError("SDK delivers repeated non-silent data; microphone authenticity test failed.")
            if args.tone:
                async with robot.control():
                    await robot.play(tone_pcm(), args.volume)
                print(json.dumps({"playback": "robot acknowledged completion"}))
    finally:
        await robot.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wirepod", default="http://escapepod.local:8080")
    parser.add_argument("--serial")
    parser.add_argument("--certificate", help="Path to an existing trusted robot certificate.")
    parser.add_argument("--trust-local-certificate", action="store_true", help="Explicitly trust the current local robot certificate for this invocation if wire-pod has none saved.")
    parser.add_argument("--listen-seconds", type=float, default=0)
    parser.add_argument("--tone", action="store_true", help="Play a quiet 0.7 second tone.")
    parser.add_argument("--duplex", action="store_true", help="Capture four seconds while playing the tone.")
    parser.add_argument("--volume", type=int, default=25)
    args = parser.parse_args()
    if not 0 <= args.volume <= 50 or not 0 <= args.listen_seconds <= 30:
        parser.error("Volume must be 0–50; capture must be 0–30 seconds.")
    try:
        asyncio.run(run(args))
    except grpc.RpcError as exc:
        parser.exit(1, f"Robot RPC failed: {exc.code().name}\n")
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        parser.exit(1, f"Diagnostic failed: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    main()
