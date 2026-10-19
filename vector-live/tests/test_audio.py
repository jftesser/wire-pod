import struct
from types import SimpleNamespace

import pytest
from vector_audio import AudioStats, tone_pcm, RATE


def test_microphone_metrics_and_wrapping_sequence():
    stats = AudioStats()
    for group, now in [(0xffffffff, 0), (0, .1), (2, .3)]:
        stats.add(SimpleNamespace(signal_power=struct.pack('<hh', -32768, 0), group_id=group), now)
    report = stats.report()
    assert report['group_discontinuities'] == 1
    assert report['peak_dbfs'] == 0
    assert report['rms_dbfs'] == -3
    assert report['max_delivery_interval_ms'] == 200


def test_rejects_corrupt_sample():
    with pytest.raises(ValueError):
        AudioStats().add(SimpleNamespace(signal_power=b'\x01', group_id=1))


def test_tone_duration_and_quiet_faded_ends():
    data = tone_pcm()
    samples = struct.unpack('<' + 'h' * (len(data) // 2), data)
    assert len(samples) == int(.7 * RATE)
    assert samples[0] == samples[-1] == 0
    assert max(abs(s) for s in samples) <= 1800


def test_repeated_test_waveform_is_not_treated_as_live_microphone():
    stats = AudioStats()
    block = tone_pcm(.1)
    for group in range(5):
        stats.add(SimpleNamespace(signal_power=block, group_id=group), group * .1)
    assert stats.report()['suspected_test_or_stuck_signal']
    assert stats.report()['longest_identical_non_silent_run'] == 5


def test_digital_silence_alone_is_not_classified_as_test_tone():
    stats = AudioStats()
    for group in range(5):
        stats.add(SimpleNamespace(signal_power=b'\x00' * 3200, group_id=group), group * .1)
    assert not stats.report()['suspected_test_or_stuck_signal']
