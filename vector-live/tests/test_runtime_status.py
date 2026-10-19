import json
import os
import stat

from runtime_status import RuntimeStatus


def test_heartbeat_is_private_and_shutdown_clears_live_flags(tmp_path):
    path = tmp_path / 'private' / 'status.json'
    writer = RuntimeStatus(path, 'robot')
    writer.write(ready=True, microphone_active=True, speaking=True, phase='ready')
    first = json.loads(path.read_text())
    assert first['pid'] == os.getpid()
    assert first['requires_wake_phrase'] is True
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    writer.write(ready=False, microphone_active=False, speaking=False, phase='closed')
    last = json.loads(path.read_text())
    assert last['ready'] is last['microphone_active'] is last['speaking'] is False
    assert list(path.parent.iterdir()) == [path]
