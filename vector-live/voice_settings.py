"""Small private operator settings; never contains credentials or speech."""
import json
import os
from pathlib import Path
import tempfile


def validate_volume(value):
    if type(value) is not int or not 0 <= value <= 100:
        raise ValueError('Volume must be a whole number from 0 to 100.')
    return value


def read_volume(filename, default=80):
    if not filename:
        return validate_volume(default)
    path = Path(filename)
    if path.is_symlink():
        raise ValueError('Voice settings must be a regular private file.')
    if not path.exists():
        return validate_volume(default)
    if not path.is_file() or path.stat().st_size > 4096:
        raise ValueError('Voice settings are invalid.')
    settings = json.loads(path.read_text())
    if not isinstance(settings, dict) or set(settings) != {'volume'}:
        raise ValueError('Voice settings are invalid.')
    return validate_volume(settings['volume'])


def save_volume(filename, value):
    validate_volume(value)
    path = Path(filename)
    if path.is_symlink() or not path.parent.is_dir():
        raise ValueError('Voice settings need a regular file in an existing private directory.')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.voice-settings-', delete=False) as target:
            temporary = target.name
            json.dump({'volume': value}, target)
            target.write('\n')
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
