"""Direct, certificate-pinned Vector access; credentials stay in memory."""
from __future__ import annotations

import asyncio
import contextlib
import json
import math
import struct
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import grpc
from cryptography import x509
from cryptography.x509.oid import NameOID
from anki_vector.messaging import protocol as p, external_interface_pb2_grpc

from pcm_stats import AudioStats

RATE = 16000
BYTES_PER_SECOND = RATE * 2


@dataclass(repr=False)
class Pairing:
    serial: str
    address: str
    name: str
    token: str
    certificate: bytes


def discover(base: str, serial: str | None = None, certificate_file=None, trust_local_certificate=False) -> Pairing:
    """Read existing wire-pod pairing without writing or printing secrets."""
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Supply a wire-pod http(s) URL.")
    base = base.rstrip("/")
    with urllib.request.urlopen(base + "/api-sdk/get_sdk_info", timeout=8) as response:
        info = json.load(response)
    robots = [r for r in info.get("robots", []) if serial is None or r["esn"] == serial]
    if len(robots) != 1:
        raise ValueError("Select exactly one paired robot with --serial.")
    robot = robots[0]
    serial = robot["esn"]
    address = robot["ip_address"].split(":")[0]
    if certificate_file:
        cert = Path(certificate_file).read_bytes()
    else:
        try:
            with urllib.request.urlopen(base + "/session-certs/" + urllib.parse.quote(serial, safe=""), timeout=8) as response:
                cert = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            if not trust_local_certificate:
                raise ValueError("Wire-pod has no saved robot certificate. Supply --certificate or explicitly enroll the local peer with --trust-local-certificate.") from None
            # First-use enrollment: no token is sent on this connection. The
            # authenticated gRPC connection below pins this exact certificate.
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            with socket.create_connection((address, 443), timeout=5) as sock:
                with context.wrap_socket(sock, server_hostname=address) as peer:
                    cert = ssl.DER_cert_to_PEM_cert(peer.getpeercert(binary_form=True)).encode()
    parsed_cert = x509.load_pem_x509_certificate(cert)
    names = parsed_cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if not names:
        names = parsed_cert.issuer.get_attributes_for_oid(NameOID.COMMON_NAME)
    if not names:
        raise ValueError("Robot certificate has no identity.")
    token = robot.get("guid") or info.get("global_guid")
    if not token:
        raise ValueError("No robot authorization token is configured.")
    return Pairing(serial, address + ":443", names[0].value, token, cert)



def tone_pcm(seconds=0.7):
    """Quiet 440 Hz tone, faded at both ends to avoid clicks."""
    count = int(seconds * RATE)
    return b"".join(struct.pack("<h", int(1800 * min(1, i / 320, (count - 1 - i) / 320)
                     * math.sin(2 * math.pi * 440 * i / RATE))) for i in range(count))


class VectorAudio:
    def __init__(self, pairing: Pairing):
        self.pairing = pairing
        self.control_error = None
        credentials = grpc.composite_channel_credentials(
            grpc.ssl_channel_credentials(root_certificates=pairing.certificate),
            grpc.access_token_call_credentials(pairing.token))
        self.channel = grpc.aio.secure_channel(pairing.address, credentials,
            options=(("grpc.ssl_target_name_override", pairing.name),))
        self.stub = external_interface_pb2_grpc.ExternalInterfaceStub(self.channel)

    async def close(self):
        await self.channel.close()

    async def status(self):
        await asyncio.wait_for(self.channel.channel_ready(), 8)
        version = await self.stub.VersionState(p.VersionStateRequest(), timeout=5)
        battery = await self.stub.BatteryState(p.BatteryStateRequest(), timeout=5)
        return {"serial": self.pairing.serial, "address": self.pairing.address,
                "name": self.pairing.name, "os_version": version.os_version,
                "engine_build_id": version.engine_build_id,
                "battery_volts": round(battery.battery_volts, 2),
                "charging": battery.is_charging, "on_charger": battery.is_on_charger_platform}

    async def listen(self, seconds, on_pcm=None):
        stats = AudioStats()
        stream = self.stub.AudioFeed(p.AudioFeedRequest())
        deadline = time.monotonic() + seconds
        try:
            while time.monotonic() < deadline:
                try:
                    frame = await asyncio.wait_for(stream.read(), min(2.0, max(.01, deadline - time.monotonic())))
                except asyncio.TimeoutError:
                    if time.monotonic() >= deadline and stats.frames:
                        break
                    raise RuntimeError("Microphone feed stalled for two seconds.") from None
                if frame is grpc.aio.EOF:
                    raise RuntimeError("Microphone feed closed unexpectedly.")
                stats.add(frame)
                if on_pcm:
                    await on_pcm(frame.signal_power)
        finally:
            stream.cancel()
        if not stats.samples:
            raise RuntimeError("No microphone audio received.")
        return stats.report()

    @contextlib.asynccontextmanager
    async def control(self):
        stream = self.stub.BehaviorControl()
        # SDKOverrideAll disables firmware stop-on-cliff. DEFAULT selects
        # SDKDefault, whose native cliff protection remains enabled.
        await stream.write(p.BehaviorControlRequest(control_request=p.ControlRequest(priority=p.ControlRequest.DEFAULT)))
        self.control_error = None
        granted = asyncio.get_running_loop().create_future()
        closing = False
        async def watch():
            try:
                async for response in stream:
                    kind = response.WhichOneof('response_type')
                    if kind == 'control_granted_response' and not granted.done():
                        granted.set_result(None)
                    elif kind == 'control_lost_event':
                        raise RuntimeError('Robot behavior control was lost.')
                raise RuntimeError('Robot behavior control stream closed.')
            except asyncio.CancelledError:
                raise
            except Exception:
                if not closing:
                    self.control_error = 'Robot behavior control was lost.'
                    if not granted.done():
                        granted.set_exception(RuntimeError(self.control_error))
        watcher = asyncio.create_task(watch())
        try:
            await asyncio.wait_for(granted, 5)
            yield
        finally:
            closing = True
            with contextlib.suppress(Exception):
                await asyncio.wait_for(stream.write(p.BehaviorControlRequest(control_release=p.ControlRelease())), 2)
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
            stream.cancel()

    async def play(self, pcm: bytes, volume=25):
        """Paced PCM playback with completion/error checking, under behavior control."""
        if len(pcm) % 2:
            raise ValueError("PCM16 audio must have complete samples.")
        async def chunks():
            yield pcm
        await self.play_stream(chunks(), volume)

    async def play_stream(self, chunks, volume=25, on_render=None, on_cancel=None):
        """Play a bounded asynchronous PCM stream; cancel robot playback on exit."""
        stream = self.stub.ExternalAudioStreamPlayback()
        completed = False
        async def responses():
            async for response in stream:
                kind = response.WhichOneof("audio_response_type")
                if kind == "audio_stream_playback_complete":
                    return
                if kind in ("audio_stream_buffer_overrun", "audio_stream_playback_failyer"):
                    raise RuntimeError("Robot playback failed: " + kind)
            raise RuntimeError("Playback stream closed without completion.")
        receiver = asyncio.create_task(responses())
        try:
            await stream.write(p.ExternalAudioStreamRequest(audio_stream_prepare=p.ExternalAudioStreamPrepare(audio_frame_rate=RATE, audio_volume=volume)))
            start = time.monotonic()
            written = 0
            async for pcm in chunks:
                if len(pcm) % 2:
                    raise ValueError('Incomplete playback sample.')
                for offset in range(0, len(pcm), 1024):
                    chunk = pcm[offset:offset + 1024]
                    await stream.write(p.ExternalAudioStreamRequest(audio_stream_chunk=p.ExternalAudioStreamChunk(audio_chunk_size_bytes=len(chunk), audio_chunk_samples=chunk)))
                    if on_render:
                        on_render(chunk)
                    written += len(chunk)
                    # Keep 80 ms of runway against network jitter.
                    await asyncio.sleep(max(0, start + written / BYTES_PER_SECOND - .08 - time.monotonic()))
                    if receiver.done():
                        await receiver
                        raise RuntimeError("Playback ended before all audio was sent.")
            await stream.write(p.ExternalAudioStreamRequest(audio_stream_complete=p.ExternalAudioStreamComplete()))
            await asyncio.wait_for(receiver, 5)
            completed = True
        finally:
            if not completed:
                if on_cancel:
                    on_cancel()
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await asyncio.wait_for(stream.write(p.ExternalAudioStreamRequest(audio_stream_cancel=p.ExternalAudioStreamCancel())), 1)
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)
            stream.cancel()
