import pytest
import asyncio
from live_voice import LiveVoice, PcmBuffer, read_key, session_config


def test_input_clock_preserves_samples_and_fills_silence():
    buffer = PcmBuffer()
    buffer.append(b'\x01\x00' * 200)
    assert buffer.frame() == b'\x01\x00' * 160
    assert buffer.frame() == b'\x01\x00' * 40 + b'\0' * 240
    assert buffer.frame() == b'\0' * 320


def test_overflow_is_explicit_and_keeps_existing_input():
    buffer = PcmBuffer(maximum=320)
    buffer.append(b'\x01\x00' * 160)
    with pytest.raises(RuntimeError):
        buffer.append(b'\x02\x00')
    assert buffer.frame() == b'\x01\x00' * 160
    with pytest.raises(ValueError):
        buffer.append(b'\x01')


def test_reads_only_the_explicit_key_from_shared_file(tmp_path):
    path = tmp_path / 'env'
    path.write_text('OPENAI_LIVE_VOICE=gleam\nOPENAI_API_KEY="test-key" # comment\n')
    assert read_key(path) == 'test-key'
    assert session_config()['audio']['output']['voice'] == 'marin'
    assert session_config()['audio']['format']['rate'] == 16000


def test_tool_results_use_live_item_protocol_and_are_deduplicated():
    async def check():
        events = []
        executions = []
        class Socket:
            async def send_json(self, event):
                events.append(event)
        async def handler(name, args):
            executions.append(name)
            return {'time': '2026-10-18T22:00:00-04:00'}
        voice = LiveVoice('fake-key', None, tool_handler=handler)
        voice.ws = Socket()
        calls = [{'call_id': 'one', 'name': 'get_time', 'arguments': '{}'}]
        await voice.complete_tools('delegation', calls)
        await voice.complete_tools('delegation', calls)
        assert executions == ['get_time']
        assert [e['type'] for e in events] == ['response.item.create', 'response.create']
        assert events[0]['item']['call_id'] == 'one'
    asyncio.run(check())
