"""Install/remove only this companion's wire-pod entry phrase."""
import argparse
import json
import urllib.error
import urllib.request

INTENT = {
    'name': 'Vector live conversation',
    'description': 'Start an on-demand GPT-Live conversation with Vector.',
    'utterances': ["let's talk", 'lets talk', 'let us talk', 'start live voice', 'start conversation', 'conversation mode', 'conversation man', 'start chat'],
    'intent': 'intent_greeting_hello',
    'exec': '/usr/bin/systemctl', 'execargs': ['start', 'vector-live.service'],
    'issystem': False,
}

STOP_INTENT = {
    'name': 'End Vector live conversation',
    'description': 'Safely end conversation mode, including when it is already stopped.',
    'utterances': ['end our conversation', 'and our conversation', 'end conversation',
                   'stop conversation', 'end live voice'],
    'intent': 'intent_greeting_hello',
    'exec': '/usr/bin/systemctl', 'execargs': ['stop', 'vector-live.service'],
    'issystem': False,
}


def current(base):
    try:
        with urllib.request.urlopen(base + '/api/get_custom_intents_json', timeout=5) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 400 and b'must create an intent first' in exc.read():
            return []
        raise
    if result is None:
        return []
    if not isinstance(result, list):
        raise ValueError('Unexpected custom-intent format.')
    return result


def post(base, path, data):
    request = urllib.request.Request(base + path, data=json.dumps(data).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(request, timeout=5) as response:
        if response.status != 200:
            raise RuntimeError('Intent update failed.')


def manage_one(base, action, definition):
    intents = current(base.rstrip('/'))
    ours = [i for i, intent in enumerate(intents) if intent.get('name') == definition['name']]
    if len(ours) > 1:
        raise ValueError('Multiple matching intents; inspect before modifying.')
    if ours:
        existing = intents[ours[0]]
        if existing.get('exec') != definition['exec'] or existing.get('execargs') != definition['execargs']:
            raise ValueError('The matching intent has different behavior; inspect before modifying.')
        if action == 'remove':
            post(base, '/api/remove_custom_intent', {'number': ours[0] + 1})
            print('LIVE_INTENT_REMOVED')
        else:
            print('LIVE_INTENT_ALREADY_INSTALLED')
        return
    if action == 'remove':
        print('LIVE_INTENT_NOT_INSTALLED')
        return
    selected = {phrase.lower() for phrase in definition['utterances']}
    for intent in intents:
        if selected.intersection(phrase.lower() for phrase in intent.get('utterances', [])):
            raise ValueError('A voice phrase conflicts with an existing custom intent.')
    if action == 'install':
        post(base, '/api/add_custom_intent', definition)
        print('LIVE_INTENT_INSTALLED')
    else:
        print('LIVE_INTENT_READY_NO_CONFLICTS')


def manage(base, action):
    for definition in (INTENT, STOP_INTENT):
        manage_one(base.rstrip('/'), action, definition)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'install', 'remove'])
    parser.add_argument('--wirepod', default='http://127.0.0.1:8080')
    args = parser.parse_args()
    manage(args.wirepod, args.action)
