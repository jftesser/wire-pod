import pytest

from persona import profile_revision
from voice_settings import read_settings, save_settings
from live_voice import session_config


def test_custom_profile_reaches_both_models_without_removing_operational_rules():
    personality='You are a sarcastic robot; use exactly one short sentence.'
    context='Jenna, Russell, Kēru and the goth duck are at the table.'
    config=session_config(personality=personality,table_context=context)
    for prompt in (config['instructions'],config['delegation']['responses']['instructions']):
        assert personality in prompt and context in prompt
        assert 'never repeat or chain movements to bypass its limits' in prompt
        assert 'end_conversation' in prompt and 'perform_motion' in prompt
        assert 'playfully earnest' not in prompt
    default=session_config()['instructions']
    assert 'getting crunk' in default and 'one short sentence' in default


def test_multiline_unicode_profile_persists_without_clobbering_other_controls(tmp_path):
    path=tmp_path/'settings.json'
    save_settings(path,{'volume':100,'boost_db':6,'motion':'full','autonomy':True})
    before=read_settings(path)
    character='Tiny menace.\nOne sentence, please.'
    context='Kēru, NFC stones, and Jenna & Russell.\n'+'🦆'*1500
    save_settings(path,{'personality':character,'table_context':context})
    assert path.stat().st_size>4096
    after=read_settings(path)
    assert after['personality']==character and after['table_context']==context
    assert profile_revision(after)!=profile_revision(before)
    assert {k:v for k,v in after.items() if k not in ('personality','table_context')}=={k:v for k,v in before.items() if k not in ('personality','table_context')}
    assert path.stat().st_mode&0o777==0o600
    save_settings(path,{'volume':80})
    assert read_settings(path)['table_context']==context
    save_settings(path,{'table_context':''})
    assert read_settings(path)['table_context']==''


@pytest.mark.parametrize('changes',[
    {'personality':''},{'personality':' \n '},{'personality':None},
    {'personality':'x'*2001},{'table_context':'x'*2001},
    {'table_context':False},{'personality':'bad\0text'},
    {'table_context':'bad\ud800text'}])
def test_invalid_profile_never_overwrites_saved_settings(tmp_path,changes):
    path=tmp_path/'settings.json';save_settings(path,{'volume':90})
    before=path.read_bytes()
    with pytest.raises(ValueError):save_settings(path,changes)
    assert path.read_bytes()==before
