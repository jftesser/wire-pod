import struct

import pytest

from native_clock import NativeClock


def test_timestamp_clock_preserves_audio_and_fills_the_measured_interval():
    clock = NativeClock()
    pcm = struct.pack('<1600h', *range(-800,800))
    assert clock.push(pcm, 500) == b''
    stretched = clock.push(pcm, 602)
    values = struct.unpack('<1632h', stretched)
    assert values[0] == -800 and values[-1] == 799
    assert all(a <= b for a,b in zip(values, values[1:]))
    assert clock.push(pcm, 702) == pcm
    assert clock.report()['output_samples'] == 3232


def test_source_clock_wraparound_and_long_run_match_wall_clock_samples():
    clock = NativeClock()
    pcm = struct.pack('<1600h', *([1234]*1600))
    timestamp = 0xfffffff0
    clock.push(pcm, timestamp)
    total = 0
    for index in range(1000):
        delta = 101 if index%2 else 102
        timestamp = (timestamp+delta)&0xffffffff
        output = clock.push(pcm, timestamp)
        total += delta*16
        assert len(output) == delta*32
        assert set(struct.unpack('<'+'h'*(len(output)//2),output)) == {1234}
    assert clock.output_samples == total  # No accumulating clock deficit/padding.


@pytest.mark.parametrize('delta',[0,79,141,2000])
def test_clock_discontinuity_fails_closed(delta):
    clock=NativeClock()
    clock.push(bytes(3200),1000)
    with pytest.raises(RuntimeError,match='clock correction bound'):
        clock.push(bytes(3200),1000+delta)
