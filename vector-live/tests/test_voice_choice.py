import asyncio

import pytest

from live_voice import session_config
from voice_choice import choose_voice


class Reply:
    def __init__(self, body, status=200):
        self.body, self.status = body, status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self):
        return self.body


class Inventory:
    def __init__(self, *pages):
        self.pages = iter(pages)
        self.requests = []

    def get(self, url, **options):
        self.requests.append(options['params'])
        assert url == 'https://api.openai.com/v1/audio/voices'
        return next(self.pages)


def test_saved_vector_uses_id_and_original_description_across_pages():
    http = Inventory(
        Reply({'data': [{'name': 'Vector', 'id': 'voice_old', 'created_at': 1}],
               'has_more': True, 'last_id': 'voice_old'}),
        Reply({'data': [{'name': ' VECTOR ', 'id': 'voice_new', 'created_at': 2,
                         'prompt': 'A bright adult voice.'}], 'has_more': False}))
    voice, prompt, label, reason = asyncio.run(choose_voice(http, 'fake'))
    assert voice == {'id': 'voice_new'} and label == 'Vector' and reason is None
    config = session_config(voice, voice_prompt=prompt)
    assert config['audio']['output']['voice'] == voice
    assert prompt in config['instructions']
    assert http.requests[1]['after'] == 'voice_old'


@pytest.mark.parametrize('reply', [Reply({'data': [], 'has_more': False}), Reply({}, 403), Reply({}, 404)])
def test_missing_or_inaccessible_inventory_uses_stone(reply):
    voice, prompt, label, reason = asyncio.run(choose_voice(Inventory(reply), 'fake'))
    assert (voice, prompt, label) == ('stone', '', 'Stone')
    assert reason


@pytest.mark.parametrize('reply', [Reply({}, 401), Reply({}, 429), Reply({}, 500),
    Reply({}), Reply({'data': [], 'has_more': True}),
    Reply({'data': [{'name': 'Vector', 'id': 'not-an-id'}]})])
def test_auth_rate_network_and_malformed_results_are_not_mislabeled_as_missing_voice(reply):
    with pytest.raises(RuntimeError):
        asyncio.run(choose_voice(Inventory(reply), 'fake'))


def test_pagination_is_bounded():
    http = Inventory(*[Reply({'data': [], 'has_more': True, 'last_id': 'voice_cursor'}) for _ in range(5)])
    with pytest.raises(RuntimeError, match='pagination bound'):
        asyncio.run(choose_voice(http, 'fake'))
