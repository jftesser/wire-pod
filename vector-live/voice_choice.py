"""Resolve the operator's saved voice by name without creating voices or sessions."""
import re

PREFERRED_VOICE = 'Vector'
FALLBACK_VOICE = 'stone'
VOICE_POLICY = 'Vector if available; otherwise Stone (checked on Start).'


async def choose_voice(http, key, name=PREFERRED_VOICE, fallback=FALLBACK_VOICE):
    matches = []
    after = None
    # The organization currently supports at most 100 prompt voices and 20
    # recorded voices. Bound pagination even if the service changes its limit.
    for _ in range(5):
        params = {'limit': '100'}
        if after:
            params['after'] = after
        async with http.get('https://api.openai.com/v1/audio/voices',
                            headers={'Authorization': 'Bearer ' + key}, params=params,
                            timeout=20) as response:
            if response.status in (403, 404):
                return fallback, '', fallback.title(), 'Saved voice inventory is unavailable to this key.'
            if response.status != 200:
                raise RuntimeError(f'Voice inventory HTTP {response.status}.')
            page = await response.json()
        if not isinstance(page, dict) or not isinstance(page.get('data'), list):
            raise RuntimeError('Invalid saved voice inventory.')
        for voice in page['data']:
            if not isinstance(voice, dict):
                raise RuntimeError('Invalid saved voice metadata.')
            if str(voice.get('name', '')).strip().casefold() == name.casefold():
                identity, prompt = voice.get('id'), voice.get('prompt', '')
                if not isinstance(identity, str) or not re.fullmatch(r'voice_[A-Za-z0-9_-]{1,200}', identity):
                    raise RuntimeError('Invalid saved voice ID.')
                if not isinstance(prompt, str) or len(prompt) > 16000:
                    raise RuntimeError('Invalid saved voice description.')
                matches.append((voice.get('created_at', 0), identity, prompt))
        if not page.get('has_more'):
            if matches:
                _, identity, prompt = max(matches)
                return {'id': identity}, prompt, name, None
            return fallback, '', fallback.title(), f'No saved voice named {name} is visible to this API key.'
        after = page.get('last_id')
        if not isinstance(after, str) or not after:
            raise RuntimeError('Invalid voice inventory pagination.')
    raise RuntimeError('Voice inventory exceeded its pagination bound.')
