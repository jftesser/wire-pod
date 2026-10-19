"""Synthetic PortAudio substitute used ONLY by the isolated worker integration test."""
import threading
import time
from types import SimpleNamespace


def query_devices():
    return [{'name': 'Offline synthetic mic', 'max_input_channels': 1}]


def check_input_settings(**kwargs):
    pass


class RawInputStream:
    def __init__(self, callback, **kwargs):
        self.callback = callback
        self.stop_event = threading.Event()
    def start(self):
        def clock():
            while not self.stop_event.wait(.01):
                now = time.monotonic()
                self.callback(b'\0' * 320, 160,
                    SimpleNamespace(currentTime=now, inputBufferAdcTime=now), False)
        self.thread = threading.Thread(target=clock, daemon=True)
        self.thread.start()
    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=1)
    def close(self):
        self.stop()
