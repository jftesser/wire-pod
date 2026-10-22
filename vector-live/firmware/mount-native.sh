#!/bin/sh
# Persistent application overlay; the original stock /anki remains underneath.
# Disable vector-native-mic.service and reboot to return to stock explicitly.
set -eu
[ "$(getprop ro.serialno)" = "00a14a38" ]
[ "$(cat /etc/os-version)" = "3.0.2.35d" ]
[ "$(cat /etc/victor-compat-version)" = "209" ]
[ -f /anki-continuous-candidate/etc/vector-continuous-mic-experiment ]
cd /anki-continuous-candidate
sha256sum -c <<'HASHES'
727b1c6e22808b87ff2f22ce356b57787affc911ef0ca97fa0f5dcd6186c8b6a  bin/vic-anim
fed193ce8c96c142c73393874894f8ba777ec8544aed7f283b74d50faeb58a50  bin/vic-engine
5d2323a1df22ac82a65d92b4d7099d20ec6b9def6146427038b7c4b7ea3687e9  bin/vic-cloud
1e779c915118216eb79f08900e1ecfa2424f594b9a6165f8a061bd87ba2f6835  lib/libcozmo_engine.so
HASHES
if [ ! -f /anki/etc/vector-continuous-mic-experiment ]; then
 mount --bind /anki-continuous-candidate /anki
fi
