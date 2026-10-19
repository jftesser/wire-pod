"""Confirm the optional host companion is stopped before rolling back wire-pod."""
import http.client
import json
import socket
import time
from pathlib import Path

ROOT = Path('/home/pi/vector-live-runtime')


class ControllerConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(2)
        self.sock.connect(str(ROOT / 'control.sock'))


def request(method, action, body=None):
    connection = ControllerConnection('local', timeout=2)
    try:
        connection.request(method, '/' + action, body=json.dumps(body) if body is not None else None,
                           headers={'Content-Type': 'application/json'})
        response = connection.getresponse()
        if response.status >= 300:
            raise RuntimeError('Host stop was refused.')
        return json.loads(response.read(65536))
    finally:
        connection.close()


def stop():
    path = ROOT / 'host-state'
    required = path.exists() and path.read_text() != 'off\n'
    try:
        state = request('GET', 'status')
    except (OSError, ValueError, http.client.HTTPException):
        if required:
            raise SystemExit('Cannot confirm Mac voice is off. Stop its controller and reconnect it before rollback.')
        return
    if state.get('active'):
        request('POST', 'stop', {})
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if not request('GET', 'status').get('active'):
                break
            time.sleep(.25)
        else:
            raise SystemExit('Mac companion has not finished closing; rollback left unchanged.')
    if path.exists():
        path.write_text('off\n')


if __name__ == '__main__':
    stop()
