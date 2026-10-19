#!/bin/bash
# Enable the isolated build; the paid companion remains on demand.
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
test -x /home/pi/vector-live-build/chipper/chipper-livevoice
test -f /home/pi/vector-live-app/.env
page="$script_dir/../chipper/webroot/vector-live.html"
test -f "$page"
# Restore the marked admin assets after rollback, preserving unrelated HTML.
sudo python3 - "$page" <<'PY'
import sys
from pathlib import Path
root = Path('/home/pi/wire-pod/chipper/webroot')
page = root / 'vector-live.html'
source = Path(sys.argv[1]).read_text()
if '<!-- VECTOR LIVE ADMIN PAGE -->' not in source:
    raise SystemExit('The prepared voice admin page is missing its ownership marker.')
if page.exists() and '<!-- VECTOR LIVE ADMIN PAGE -->' not in page.read_text():
    raise SystemExit('An unrelated vector-live.html exists; refusing to replace it.')
index = root / 'index.html'
text = index.read_text()
snippet = '        <!-- VECTOR LIVE ADMIN LINK -->\n        <div class="main-nav-child"><a href="/vector-live.html">Vector Voice</a></div>\n'
if '<!-- VECTOR LIVE ADMIN LINK -->' not in text:
    anchor = '<div class="main-nav-parent">'
    if anchor not in text:
        raise SystemExit('Cannot locate the wire-pod navigation; no page changed.')
    text = text.replace(anchor, anchor + '\n' + snippet.rstrip('\n'), 1)
page.write_text(source)
index.write_text(text)
PY
python3 /home/pi/vector-live-app/manage_intent.py install
sudo install -d -m 0755 /etc/systemd/system/wire-pod.service.d
sudo install -m 0644 "$script_dir/wire-pod-livevoice.conf" /etc/systemd/system/wire-pod.service.d/90-vector-audio-tap.conf
sudo systemctl daemon-reload
# Vosk builds its custom-word grammar at startup, so refresh after intent install.
sudo systemctl restart wire-pod.service
sudo systemctl is-active wire-pod.service
