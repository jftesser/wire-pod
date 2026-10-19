#!/bin/sh
# Temporary, on-robot application test; never writes the boot/recovery images.
set -eu
[ "$(getprop ro.serialno)" = "00a14a38" ]
[ "$(cat /etc/victor-compat-version)" = "209" ]
[ "$(cat /anki-live30-candidate/etc/victor-compat-version)" = "209" ]
[ -f /anki-live30-candidate/etc/vector-live30-experiment ]
[ ! -f /anki/etc/vector-live30-experiment ]
[ -x /data/vector-live30-test/rollback-live30.sh ]
cleanup() {
  code=$?
  if [ "$code" -ne 0 ]; then
    /bin/sh /data/vector-live30-test/rollback-live30.sh --force || true
  fi
}
trap cleanup EXIT
touch /run/vector-live30-pending
systemd-run --unit=vector-live30-rollback --on-active=5min \
  /bin/sh /data/vector-live30-test/rollback-live30.sh
systemctl stop anki-robot.target
mount --bind /anki-live30-candidate /anki
mount -o remount,ro /
systemctl start anki-robot.target
