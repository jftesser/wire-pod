#!/bin/sh
# Targeted reversible application update; no boot/recovery image or userdata erase.
set -eu
new=3081771cfbea6c1b8b306d60fdd5cdae70682b0ab1b79775811fbf39089ba567
old=727b1c6e22808b87ff2f22ce356b57787affc911ef0ca97fa0f5dcd6186c8b6a
base=/data/vector-native-mic
backup=$base/backups/20261022-before-speech-gain
target=/anki-continuous-candidate/bin/vic-anim
[ "$(getprop ro.serialno)" = 00a14a38 ]
[ "$(cat /etc/os-version)" = 3.0.2.35d ]
[ "$(cat /etc/victor-compat-version)" = 209 ]
echo "$old  $target" | sha256sum -c -
echo "$new  $base/vic-anim.speech-next" | sha256sum -c -
grep -q "$new" "$base/mount-native.speech-next.sh"
[ ! -e "$backup/vic-anim" ]
mkdir -p "$backup"
cp -p "$target" "$backup/vic-anim"
cp -p "$base/mount-native.sh" "$backup/mount-native.sh"
cleanup() {
 code=$?
 if [ "$code" -ne 0 ]; then
  systemctl stop vic-cloud.service vic-switchboard.service vic-engine.service vic-anim.service || true
  mount -o remount,rw / || true
  cp -p "$backup/vic-anim" "$target.restore" && mv "$target.restore" "$target" || true
  cp -p "$backup/mount-native.sh" "$base/mount-native.sh" || true
 fi
 sync
 mount -o remount,ro / || true
 systemctl start vic-anim.service vic-engine.service || true
 systemctl start vic-switchboard.service || true
 systemctl start vic-cloud.service || true
 exit "$code"
}
trap cleanup EXIT
systemctl stop vic-cloud.service vic-switchboard.service vic-engine.service vic-anim.service
mount -o remount,rw /
cp "$base/vic-anim.speech-next" "$target.next"
chmod 755 "$target.next"
mv "$target.next" "$target"
cp "$base/mount-native.speech-next.sh" "$base/mount-native.sh"
chmod 755 "$base/mount-native.sh"
sync
mount -o remount,ro /
systemctl daemon-reload
systemctl start vic-anim.service vic-engine.service
systemctl start vic-switchboard.service
systemctl start vic-cloud.service
echo "$new  $target" | sha256sum -c -
trap - EXIT
echo 'Native speech mixer gain installed; SDK and running-process checks still required.'
