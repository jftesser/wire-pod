#!/bin/bash
# Remove only this experiment's service override; the original binary is intact.
set -e
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
sudo python3 "$script_dir/stop_host.py"
sudo systemctl stop vector-live.service 2>/dev/null || true
if [[ -f /home/pi/vector-live-app/manage_intent.py ]]; then
    python3 /home/pi/vector-live-app/manage_intent.py remove
fi
sudo rm -f /etc/systemd/system/wire-pod.service.d/90-vector-audio-tap.conf
sudo python3 - <<'PY'
from pathlib import Path
root = Path('/home/pi/wire-pod/chipper/webroot')
index = root / 'index.html'
snippet = '        <!-- VECTOR LIVE ADMIN LINK -->\n        <div class="main-nav-child"><a href="/vector-live.html">Vector Voice</a></div>\n'
if index.exists():
    text = index.read_text()
    if snippet in text:
        index.write_text(text.replace(snippet, '', 1))
page = root / 'vector-live.html'
if page.exists() and '<!-- VECTOR LIVE ADMIN PAGE -->' in page.read_text():
    page.unlink()
PY
sudo systemctl daemon-reload
sudo systemctl restart wire-pod
sudo systemctl is-active wire-pod
