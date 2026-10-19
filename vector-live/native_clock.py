"""Map timestamped robot PCM onto the nominal16kHz conversation clock."""
from array import array
import sys


class NativeClock:
    def __init__(self):
        self.previous = None
        self.input_samples = self.output_samples = self.groups = 0
        self.min_delta_ms = self.max_delta_ms = None

    def push(self, pcm, timestamp):
        if len(pcm) != 3200 or not isinstance(timestamp, int):
            raise RuntimeError('Invalid timestamped native PCM group.')
        current = (pcm, timestamp)
        self.input_samples += 1600
        self.groups += 1
        if self.previous is None:
            self.previous = current
            return b''
        previous, then = self.previous
        delta = (timestamp-then) & 0xffffffff
        if not 80 <= delta <= 140:
            raise RuntimeError('Native microphone timestamps exceeded the clock correction bound.')
        self.previous = current
        self.min_delta_ms = min(self.min_delta_ms or delta, delta)
        self.max_delta_ms = max(self.max_delta_ms or delta, delta)
        count = delta*16
        self.output_samples += count
        if count == 1600:
            return previous
        samples = array('h')
        samples.frombytes(previous)
        if sys.byteorder != 'little':
            samples.byteswap()
        output = array('h')
        denominator = count-1
        for index in range(count):
            left, fraction = divmod(index*1599, denominator)
            right = min(left+1, 1599)
            output.append((samples[left]*(denominator-fraction)+samples[right]*fraction)//denominator)
        if sys.byteorder != 'little':
            output.byteswap()
        return output.tobytes()

    def report(self):
        return dict(groups=self.groups, input_samples=self.input_samples,
            output_samples=self.output_samples, min_group_delta_ms=self.min_delta_ms,
            max_group_delta_ms=self.max_delta_ms, lookahead_groups=1)
