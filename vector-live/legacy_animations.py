"""Allowlisted, quiet derivatives of wire-pod's original conversation clips."""
import json
from pathlib import Path

LEGACY_MAP = {
    'happy': 'anim_onboarding_reacttoface_happy_01',
    'veryHappy': 'anim_blackjack_victorwin_01',
    'sad': 'anim_feedback_meanwords_01',
    'verySad': 'anim_feedback_meanwords_01',
    'angry': 'anim_rtpickup_loop_10',
    'frustrated': 'anim_feedback_shutup_01',
    'dartingEyes': 'anim_observing_self_absorbed_01',
    'confused': 'anim_meetvictor_lookface_timeout_01',
    'thinking': 'anim_explorer_scan_short_04',
    'celebrate': 'anim_pounce_success_03',
    'love': 'anim_feedback_iloveyou_02',
}
CANCEL_ANIMATION = 'anim_vectorlive_cancel'
MANIFEST_PATH = Path(__file__).with_name('legacy_assets') / 'manifest.json'


def catalog():
    return json.loads(MANIFEST_PATH.read_text())['expressions']
