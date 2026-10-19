"""Bounded GPT-Live transport; no audio device or recording opens here."""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import math
import struct
from collections import Counter
import shlex
import time
from pathlib import Path

import aiohttp

RATE = 16000
FRAME = 320  # 10 ms, mono PCM16
PERSONALITY = (
    "You are Vector, a tiny, expressive desktop robot. Be bright, curious, warm, "
    "and playfully earnest, with a small explorer's delight in ordinary things. "
    "Use short natural replies, usually one or two sentences. Do not claim to see, remember, move, "
    "or control anything unless a provided tool actually establishes that ability. "
    "The host can animate your eyes, blinks and small head nods automatically. These are not voice-commanded driving. "
    "When asked about physical movement, delegate and use get_robot_status to check the current gesture profile. "
    "When the status tool reports enabled eye/blink or head gestures, acknowledge those abilities rather than denying them; you have no driving or navigation tool. "
    "Wait for the complete request before answering; avoid overlapping acknowledgments. "
    "Delegate factual questions and requests needing reasoning to the backend. "
    "Always delegate requests for the current time, robot battery or charger status, "
    "and any request to stop, end the conversation, or say goodbye. "
    "The backend has get_time, get_robot_status and end_conversation tools. "
    "You cannot end the paid session by speaking; never claim it has ended without the tool."
)

BACKEND_INSTRUCTIONS = PERSONALITY + (
    " When the person asks to end or stop the conversation, or says goodbye, "
    "call end_conversation immediately. A verbal acknowledgment alone does not stop it. "
    "Use get_time for the actual current time and get_robot_status for actual robot state."
)


def read_key(filename=None):
    if filename:
        for line in Path(filename).read_text().splitlines():
            left, sep, right = line.removeprefix('export ').partition('=')
            if sep and left.strip() == 'OPENAI_API_KEY':
                parts = shlex.split(right, comments=True)
                if len(parts) == 1 and parts[0]:
                    return parts[0]
        raise ValueError('The selected env file has no configured OpenAI key.')
    key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not key:
        raise ValueError('Choose an existing key file or set OPENAI_API_KEY.')
    return key


def session_config(voice='marin', greet=False, tools=(), input_mode='wake'):
    if input_mode not in ('wake', 'continuous'):
        raise ValueError('Unknown input mode.')
    listening = (
        ' The robot supplies microphone audio only after its wake phrase. Quiet input between requests is expected.'
        if input_mode == 'wake' else
        ' A microphone supplies continuous room audio, including while you speak. The person can speak directly without a wake phrase.'
    ) + ' Do not repeatedly prompt or speak uninvited. Ignore your own speaker echo.'
    config = {
        'model': 'gpt-live-1', 'instructions': PERSONALITY + listening, 'store': False,
        'audio': {'format': {'type': 'audio/pcm', 'rate': RATE}, 'output': {'voice': voice}},
        'delegation': {'type': 'responses', 'responses': {
            'model': 'gpt-5.4-mini', 'instructions': BACKEND_INSTRUCTIONS,
            'tools': list(tools), 'tool_choice': 'auto'}},
    }
    if greet:
        config['input'] = [{'role': 'developer', 'type': 'message', 'content': [{
            'type': 'input_text', 'text': 'Greet now in English. In one brief sentence, say "Live voice is ready". ' + ('Remind the person to say Hey Vector before each turn.' if input_mode == 'wake' else 'Say they can speak directly now.') + ' Then wait and listen.'}]}]
    return config


class PcmBuffer:
    def __init__(self, maximum=RATE * 2 * 2):
        self.data = bytearray()
        self.maximum = maximum

    def append(self, pcm):
        if len(pcm) % 2:
            raise ValueError('Incomplete PCM16 input sample.')
        if len(self.data) + len(pcm) > self.maximum:
            raise RuntimeError('Input audio queue exceeded two seconds; stopping instead of losing speech.')
        self.data.extend(pcm)

    def frame(self):
        pcm = bytes(self.data[:FRAME])
        del self.data[:FRAME]
        return pcm.ljust(FRAME, b'\0')


class LiveVoice:
    def __init__(self, key, on_audio, voice='marin', greet=False, tools=(), tool_handler=None, input_mode='wake'):
        self.key, self.on_audio, self.voice = key, on_audio, voice
        self.input = PcmBuffer()
        self.input_mode = input_mode
        self.http = self.ws = self.receiver = self.sender = None
        self.started = asyncio.Event()
        self.finalized = asyncio.Event()
        self.error = None
        self.usage = None
        self.backend_usage = {}
        self.captions = []
        self.created_at = None
        self.greet, self.tools, self.tool_handler = greet, tools, tool_handler
        self.backend_pending = set()
        self.responses, self.calls, self.tool_results = {}, {}, {}
        self.work = set()
        self.tool_lock = asyncio.Lock()
        self.sent_tool_results = set()
        self.events = Counter()
        self.input_samples = self.input_squares = self.input_peak = 0
        self.output_samples = self.output_squares = self.output_peak = 0

    async def start(self):
        self.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=15))
        try:
            self.ws = await self.http.ws_connect('wss://api.openai.com/v1/live/sessions',
                headers={'Authorization': 'Bearer ' + self.key, 'User-Agent': 'Vector Live/0.1'},
                heartbeat=20, max_msg_size=4 * 1024 * 1024)
            self.key = None
            self.receiver = asyncio.create_task(self.receive())
            await self.ws.send_json({'type': 'session.start', 'session': session_config(self.voice, self.greet, self.tools, self.input_mode)})
            await asyncio.wait_for(self.started.wait(), 25)
            if self.error:
                raise RuntimeError(self.error)
            self.created_at = time.monotonic()
            self.sender = asyncio.create_task(self.send_clock())
        except BaseException:
            await self.close()
            raise

    async def send_clock(self):
        deadline = time.monotonic()
        try:
            while True:
                # Supply the live clock, including silence between wake-gated
                # robot requests. Do not burst a complete utterance at the API.
                pcm = self.input.frame()
                samples = struct.unpack('<'+'h'*(len(pcm)//2), pcm)
                self.input_samples += len(samples)
                self.input_squares += sum(x*x for x in samples)
                self.input_peak = max(self.input_peak, max((abs(x) for x in samples), default=0))
                await self.ws.send_json({'type': 'session.input_audio.append',
                    'audio': base64.b64encode(pcm).decode('ascii')})
                deadline += .01
                now = time.monotonic()
                if now - deadline > .25:
                    raise RuntimeError('Input audio clock fell behind.')
                await asyncio.sleep(max(0, deadline - now))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
            await self.ws.close()

    async def receive(self):
        try:
            async for message in self.ws:
                if message.type != aiohttp.WSMsgType.TEXT:
                    if message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
                    continue
                event = json.loads(message.data)
                kind = event.get('type')
                self.events[kind] += 1
                if kind == 'session.started':
                    self.started.set()
                elif kind == 'session.output_audio.delta':
                    pcm = base64.b64decode(event['delta'], validate=True)
                    samples = struct.unpack('<'+'h'*(len(pcm)//2), pcm)
                    self.output_samples += len(samples)
                    self.output_squares += sum(x*x for x in samples)
                    self.output_peak = max(self.output_peak, max((abs(x) for x in samples), default=0))
                    await self.on_audio(pcm)
                elif kind in ('session.input_transcript.delta', 'session.output_transcript.delta'):
                    self.captions.append({'role': 'user' if kind.startswith('session.input') else 'assistant',
                                          'text': event.get('delta', '')})
                    self.captions = self.captions[-300:]
                elif kind in ('session.usage.updated', 'session.closed'):
                    self.usage = event.get('usage', self.usage)
                    if kind == 'session.closed':
                        self.finalized.set()
                        break
                elif kind == 'response.event':
                    nested = event.get('event', {})
                    response = nested.get('response', {})
                    delegation = event.get('delegation_id')
                    if nested.get('type') == 'response.created':
                        print(json.dumps({'backend': 'started'}), flush=True)
                        self.responses[delegation] = response['id']
                        self.backend_pending.add(response['id'])
                    response_id = response.get('id') or self.responses.get(delegation)
                    if nested.get('type') == 'response.output_item.done' and nested.get('item', {}).get('type') == 'function_call':
                        items = self.calls.setdefault(response_id, [])
                        if not any(item['call_id'] == nested['item']['call_id'] for item in items):
                            items.append(nested['item'])
                    if nested.get('type') == 'response.completed':
                        self.backend_pending.discard(response['id'])
                        self.backend_usage[response['id']] = response.get('usage', {})
                        calls = self.calls.pop(response_id, [])
                        if calls:
                            task = asyncio.create_task(self.complete_tools(delegation, calls))
                            self.work.add(task)
                            task.add_done_callback(self.work.discard)
                    elif nested.get('type') == 'response.failed':
                        raise RuntimeError('backend_failed')
                elif kind == 'error':
                    # Only an API error code is safe to include in logs.
                    raise RuntimeError('API error: ' + str(event.get('error', {}).get('code', 'unknown')))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        finally:
            if not self.finalized.is_set() and not self.error:
                self.error = 'Connection closed without final usage.'
            self.started.set()

    def diagnostics(self):
        def level(squares,samples):
            return round(20*math.log10(max(1,math.sqrt(squares/max(1,samples)))/32768),1)
        return {'input_seconds':round(self.input_samples/16000,2),
                'input_rms_dbfs':level(self.input_squares,self.input_samples),
                'input_peak':self.input_peak,'output_seconds':round(self.output_samples/16000,2),
                'output_rms_dbfs':level(self.output_squares,self.output_samples),
                'output_peak':self.output_peak,'events':dict(self.events)}

    async def complete_tools(self, delegation, calls):
        try:
            async with self.tool_lock:
                sent = False
                for item in calls:
                    call_id = item['call_id']
                    if call_id in self.sent_tool_results:
                        continue
                    if call_id not in self.tool_results:
                        if not self.tool_handler:
                            raise RuntimeError('No tool handler is configured.')
                        print(json.dumps({'tool': item['name']}), flush=True)
                        self.tool_results[call_id] = await self.tool_handler(item['name'], json.loads(item.get('arguments', '{}')))
                    await self.ws.send_json({'type': 'response.item.create', 'item': {
                        'type': 'function_call_output', 'call_id': call_id,
                        'output': json.dumps(self.tool_results[call_id])}})
                    self.sent_tool_results.add(call_id)
                    sent = True
                if sent:
                    await self.ws.send_json({'type': 'response.create'})
        except asyncio.CancelledError:
            raise
        except Exception:
            self.error = 'Tool handling failed.'

    async def close(self):
        for task in list(self.work):
            task.cancel()
        await asyncio.gather(*self.work, return_exceptions=True)
        if self.sender:
            self.sender.cancel()
            await asyncio.gather(self.sender, return_exceptions=True)
        try:
            if self.ws and not self.ws.closed and self.receiver and not self.receiver.done():
                await self.ws.send_json({'type': 'session.close'})
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self.finalized.wait(), 15)
        finally:
            if self.receiver:
                self.receiver.cancel()
                await asyncio.gather(self.receiver, return_exceptions=True)
            if self.ws:
                await self.ws.close()
            if self.http:
                await self.http.close()
