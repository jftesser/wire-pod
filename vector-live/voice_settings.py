"""Small private operator settings; never contains credentials or speech."""
import json
import os
from pathlib import Path
import tempfile
from persona import DEFAULT_PERSONALITY, DEFAULT_TABLE_CONTEXT, validate_profile_text


def validate_volume(value):
    if type(value) is not int or not 0 <= value <= 100:
        raise ValueError('Volume must be a whole number from 0 to 100.')
    return value


def validate_options(settings):
    if not isinstance(settings, dict) or set(settings) - {'volume', 'boost_db', 'expressions', 'nod_depth', 'nod_interval', 'legacy_animations', 'autonomy', 'motion', 'personality', 'table_context'}:
        raise ValueError('Voice settings are invalid.')
    if 'volume' in settings:
        validate_volume(settings['volume'])
    if 'boost_db' in settings and (type(settings['boost_db']) is not int or settings['boost_db'] not in (0, 3, 6)):
        raise ValueError('Boost must be 0, 3 or 6 dB.')
    if 'expressions' in settings and settings['expressions'] not in ('off', 'eyes', 'head'):
        raise ValueError('Expressions must be off, eyes or head.')
    for key, low, high in (('nod_depth', 2, 20), ('nod_interval', 4, 30)):
        if key in settings and (type(settings[key]) is not int or not low <= settings[key] <= high):
            raise ValueError(f'{key} must be a whole number from {low} to {high}.')
    if 'legacy_animations' in settings and type(settings['legacy_animations']) is not bool:
        raise ValueError('Legacy animations must be on or off.')
    if 'autonomy' in settings and type(settings['autonomy']) is not bool:
        raise ValueError('Natural behavior must be on or off.')
    if 'motion' in settings and settings['motion'] not in ('off', 'arms', 'full'):
        raise ValueError('Motor actions must be off, arms or full.')
    for key in ('personality', 'table_context'):
        if key in settings:
            validate_profile_text(key, settings[key])
    return settings


def read_settings(filename, default=80):
    if not filename:
        return dict(volume=validate_volume(default), boost_db=0, expressions='off', nod_depth=8, nod_interval=12, legacy_animations=False, autonomy=False, motion='off', personality=DEFAULT_PERSONALITY, table_context=DEFAULT_TABLE_CONTEXT)
    path = Path(filename)
    if path.is_symlink():
        raise ValueError('Voice settings must be a regular private file.')
    if not path.exists():
        return dict(volume=validate_volume(default), boost_db=0, expressions='off', nod_depth=8, nod_interval=12, legacy_animations=False, autonomy=False, motion='off', personality=DEFAULT_PERSONALITY, table_context=DEFAULT_TABLE_CONTEXT)
    if not path.is_file() or path.stat().st_size > 65536:
        raise ValueError('Voice settings are invalid.')
    settings = json.loads(path.read_text())
    validate_options(settings)
    if 'volume' not in settings:
        raise ValueError('Voice settings need volume.')
    return {'boost_db': 0, 'expressions': 'off', 'nod_depth': 8, 'nod_interval': 12, 'legacy_animations': False, 'autonomy': False, 'motion': 'off', 'personality': DEFAULT_PERSONALITY, 'table_context': DEFAULT_TABLE_CONTEXT, **settings}


def read_volume(filename, default=80):
    return read_settings(filename, default)['volume']


def save_volume(filename, value):
    save_settings(filename, {'volume': validate_volume(value)})


def save_settings(filename, changes):
    validate_options(changes)
    settings = {**read_settings(filename), **changes}
    path = Path(filename)
    if path.is_symlink() or not path.parent.is_dir():
        raise ValueError('Voice settings need a regular file in an existing private directory.')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.voice-settings-', delete=False) as target:
            temporary = target.name
            json.dump(settings, target)
            target.write('\n')
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
