#!/bin/sh
# Run on Vector. The experimental /anki bind mount disappears on every reboot.
set -eu
[ "$(getprop ro.serialno)" = "00a14a38" ]
if [ "${1:-}" != "--force" ] && [ ! -f /run/vector-live30-pending ]; then
  exit 0
fi
if [ -f /anki/etc/vector-live30-experiment ]; then
  systemctl stop anki-robot.target
  if ! umount /anki; then
    # A reboot drops this temporary mount and starts the preserved stock runtime.
    reboot
    exit 1
  fi
fi
systemctl start anki-robot.target
rm -f /run/vector-live30-pending
mount -o remount,ro /
