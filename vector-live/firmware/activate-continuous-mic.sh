#!/bin/sh
# Reversible application-only test. Reboot always restores the stock /anki.
set -eu
[ "$(getprop ro.serialno)" = "00a14a38" ]
[ "$(cat /etc/os-version)" = "3.0.2.35d" ]
[ "$(cat /etc/victor-compat-version)" = "209" ]
[ "$(cat /anki-continuous-candidate/etc/victor-compat-version)" = "209" ]
[ -f /anki-continuous-candidate/etc/vector-continuous-mic-experiment ]
[ ! -f /anki/etc/vector-continuous-mic-experiment ]
[ ! -f /anki/etc/vector-live30-experiment ]
[ -x /data/vector-continuous-mic-test/rollback-continuous-mic.sh ]
cleanup() {
 code=$?
 if [ "$code" -ne 0 ]; then
  /bin/sh /data/vector-continuous-mic-test/rollback-continuous-mic.sh --force || true
 fi
}
trap cleanup EXIT
touch /run/vector-continuous-mic-pending
systemd-run --unit=vector-continuous-mic-rollback --on-active=5min \
 /bin/sh /data/vector-continuous-mic-test/rollback-continuous-mic.sh
systemctl stop anki-robot.target
 systemctl stop vic-cloud.service vic-engine.service vic-anim.service
mount --bind /anki-continuous-candidate /anki
mount -o remount,ro /
systemctl start anki-robot.target
systemctl start vic-anim.service vic-engine.service vic-cloud.service
