import json

import pytest

import manage_intent


def test_install_recognizes_wirepod_serialized_intent_and_removes_by_position(monkeypatch):
    # wire-pod serializes CustomIntent with lowercase JSON field names.
    existing = json.loads('''{"name":"Vector live conversation",
        "exec":"/usr/bin/systemctl","execargs":["start","vector-live.service"],
        "utterances":["let's talk"],"intent":"intent_greeting_hello"}''')
    intents = [{'name': 'Existing user intent'}, existing]
    writes = []
    monkeypatch.setattr(manage_intent, 'current', lambda base: intents)
    monkeypatch.setattr(manage_intent, 'post', lambda *args: writes.append(args))
    manage_intent.manage_one('http://wirepod', 'install', manage_intent.INTENT)
    assert writes == []
    manage_intent.manage_one('http://wirepod', 'remove', manage_intent.INTENT)
    assert writes == [('http://wirepod', '/api/remove_custom_intent', {'number': 2})]


def test_install_rejects_existing_lowercase_phrase_conflict(monkeypatch):
    monkeypatch.setattr(manage_intent, 'current', lambda base: [
        {'name': 'Other conversation', 'utterances': ['Conversation Mode']}])
    with pytest.raises(ValueError, match='conflicts'):
        manage_intent.manage_one('http://wirepod', 'install', manage_intent.INTENT)


def test_both_controls_install_idempotently_and_remove_without_touching_other_intents(monkeypatch):
    saved = [{'name': 'Existing user intent'}]
    monkeypatch.setattr(manage_intent, 'current', lambda base: json.loads(json.dumps(saved)))
    def post(base, path, data):
        if path == '/api/add_custom_intent':
            saved.append(json.loads(json.dumps(data)))
        else:
            saved.pop(data['number'] - 1)
    monkeypatch.setattr(manage_intent, 'post', post)
    manage_intent.manage('http://wirepod', 'install')
    manage_intent.manage('http://wirepod', 'install')
    assert len(saved) == 3
    manage_intent.manage('http://wirepod', 'remove')
    assert saved == [{'name': 'Existing user intent'}]
