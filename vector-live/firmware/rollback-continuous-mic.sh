#!/bin/sh
set -eu
[ "$(getprop ro.serialno)" = "00a14a38" ]
if [ "${1:-}" != "--force" ] && [ ! -f /run/vector-continuous-mic-pending ]; then exit 0; fi
if [ -f /anki/etc/vector-continuous-mic-experiment ]; then
 systemctl stop anki-robot.target
 systemctl stop vic-cloud.service vic-engine.service vic-anim.service
 if ! umount /anki; then
  reboot
  exit 1
 fi
fi
systemctl start anki-robot.target
systemctl start vic-anim.service vic-engine.service vic-cloud.service
rm -f /run/vector-continuous-mic-pending
mount -o remount,ro /
