import json

import pytest

from voice_settings import read_volume, save_volume, validate_volume


def test_volume_persists_with_private_permissions_and_preserves_valid_settings(tmp_path):
    path=tmp_path/'settings.json'
    assert read_volume(path,80)==80
    save_volume(path,0)
    assert read_volume(path)==0
    assert path.stat().st_mode & 0o777 == 0o600
    save_volume(path,100)
    assert read_volume(path)==100
    with pytest.raises(ValueError):save_volume(path,101)
    assert read_volume(path)==100


@pytest.mark.parametrize('value',[-1,101,True,False,3.5,'80',None])
def test_invalid_volume_never_becomes_audio_gain(value):
    with pytest.raises(ValueError):validate_volume(value)


def test_settings_reject_unknown_fields_and_symlink_targets(tmp_path):
    path=tmp_path/'settings.json'
    path.write_text(json.dumps({'volume':80,'command':'not allowed'}))
    with pytest.raises(ValueError):read_volume(path)
    link=tmp_path/'link.json';link.symlink_to(path)
    with pytest.raises(ValueError):save_volume(link,40)
    assert 'command' in path.read_text()
