"""Private, atomic process heartbeat for the operator console; no conversation text."""
import json
import os
import tempfile
import time
from pathlib import Path


class RuntimeStatus:
    def __init__(self, path, serial, mode='wake', volume=80, source=None):
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.started = time.monotonic()
        self.state = {'version': 1, 'pid': os.getpid(), 'serial': serial,
                      'mode': mode, 'source': source or 'Vector wake-word requests',
                      'volume': volume, 'phase': 'starting', 'ready': False,
                      'microphone_active': False, 'speaking': False,
                      'requires_wake_phrase': mode == 'wake'}
        self.write()

    def write(self, **changes):
        self.state.update(changes)
        self.state.update(heartbeat=time.time(), elapsed_seconds=round(time.monotonic() - self.started, 1))
        filename = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=self.path.parent,
                    prefix='.vector-status-', delete=False) as target:
                filename = target.name
                json.dump(self.state, target)
                target.write('\n')
            os.replace(filename, self.path)
        finally:
            if filename and os.path.exists(filename):
                os.unlink(filename)
