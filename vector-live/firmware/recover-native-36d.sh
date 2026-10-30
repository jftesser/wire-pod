#!/bin/sh
# Restore stock 36d on failed validation. Preserves the staged application/data.
set -eu
[ "$(getprop ro.serialno)" = 00a14a38 ]
if [ "${1:-}" != --force ] && [ ! -f /run/vector-native-36d-pending ]; then exit 0; fi
mount -o remount,rw /
systemctl disable vector-native-mic.service || true
sync
mount -o remount,ro /
systemctl stop vic-cloud.service vic-switchboard.service vic-engine.service vic-anim.service
systemctl stop vector-native-mic.service
if [ -f /anki/etc/vector-continuous-mic-experiment ]; then
 if ! umount /anki; then
  reboot
  exit 1
 fi
fi
systemctl daemon-reload
systemctl start vic-anim.service vic-engine.service
systemctl start vic-switchboard.service
systemctl start vic-cloud.service
if grep -qx active /data/vector-native-mic/backups/20261030-before-36d/update-timer-before.txt; then
 systemctl start update-engine.timer
fi
if [ -f /data/vector-native-mic/backups/20261030-before-36d/update-service-before.txt ] &&
   grep -Eq '^(active|activating)$' /data/vector-native-mic/backups/20261030-before-36d/update-service-before.txt; then
 systemctl start --no-block update-engine.service
fi
rm -f /run/vector-native-36d-pending
echo 'Stock 36d application restored; staged custom application preserved.'
