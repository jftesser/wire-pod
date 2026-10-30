#!/bin/sh
# Stage against the exact installed stock application, then activate reversibly.
# No boot image, Wi-Fi, pairing, personal settings or API key is replaced.
set -eu
action=${1:?Use --stage or --activate}
payload=${2:?Supply the verified extracted payload directory}
base=/data/vector-native-mic
app=$base/application-36d
backup=$base/backups/20261030-before-36d
[ "$(getprop ro.serialno)" = 00a14a38 ]
[ "$(cat /etc/os-version)" = 3.0.2.36d ]
[ "$(cat /etc/victor-compat-version)" = 209 ]
cd "$payload"
sha256sum -c SHA256SUMS
case "$action" in
 --stage)
  [ ! -f /anki/etc/vector-continuous-mic-experiment ]
  cd /anki
  sha256sum -c "$payload/STOCK_SHA256SUMS"
  [ ! -e "$app" ]
  [ ! -e "$app.next" ]
  available=$(df -Pk /data | awk 'NR==2 {print $4}')
  [ "$available" -gt 280000 ]
  mkdir -p "$backup"
  cp -p "$base/mount-native.sh" "$backup/mount-native.sh"
  cp /anki/etc/revision "$backup/stock-revision"
  cp "$payload/STOCK_SHA256SUMS" "$backup/stock.sha256"
  cp -a /anki "$app.next"
  cd "$payload"
  while read -r hash relative; do
   case "$relative" in
    app/*)
     destination="$app.next/${relative#app/}"
     mkdir -p "$(dirname "$destination")"
     cp "$relative" "$destination"
     chown root:anki "$destination"
     case "$relative" in app/bin/*|app/lib/*) chmod 555 "$destination";; *) chmod 444 "$destination";; esac
     ;;
   esac
  done < SHA256SUMS
  # The Go gateway is statically linked (and UPX packed); invoking ld.so on
  # that file crashes the loader. Only the two dynamic C++ executables use it.
  for executable in vic-anim vic-engine; do
   LD_LIBRARY_PATH="$app.next/lib" /lib/ld-linux-armhf.so.3 --list "$app.next/bin/$executable" > "$backup/loader-$executable.txt"
  done
  mv "$app.next" "$app"
  sync
  echo '36d application staged in /data; running stock application unchanged.'
  ;;
 --activate)
  [ -d "$app" ]
  [ ! -f /anki/etc/vector-continuous-mic-experiment ]
  update_state=$(systemctl is-active update-engine.service || true)
  printf '%s\n' "$update_state" > "$backup/update-service-before.txt"
  case "$update_state" in
   active|activating)
    # A scheduled checker can spend an hour in ExecStartPre's random sleep.
    # It is safe to pause that delay; never interrupt an actual OTA operation.
    if [ "$(cat /run/update-engine/phase 2>/dev/null || true)" = sleeping ]; then
     systemctl stop update-engine.service
    else
     echo 'An OS update is in progress; refusing application activation.' >&2
     exit 1
    fi
    ;;
  esac
  systemctl is-active update-engine.timer > "$backup/update-timer-before.txt" || true
  systemctl stop update-engine.timer
  cp "$payload/recover-native-36d.sh" "$base/recover-native-36d.sh"
  chmod 755 "$base/recover-native-36d.sh"
  touch /run/vector-native-36d-pending
  systemd-run --unit=vector-native-36d-rollback --on-active=5min /bin/sh "$base/recover-native-36d.sh"
  rollback_on_error() {
   code=$?
   if [ "$code" -ne 0 ]; then /bin/sh "$base/recover-native-36d.sh" --force || true; fi
   exit "$code"
  }
  trap rollback_on_error EXIT
  mount -o remount,rw /
  cp "$payload/mount-native.sh" "$base/mount-native.sh"
  chmod 755 "$base/mount-native.sh"
  cp "$payload/vector-native-mic.service" /etc/systemd/system/vector-native-mic.service
  chmod 644 /etc/systemd/system/vector-native-mic.service
  systemctl daemon-reload
  systemctl enable vector-native-mic.service
  sync
  mount -o remount,ro /
  systemctl stop vic-cloud.service vic-switchboard.service vic-engine.service vic-anim.service
  systemctl start vector-native-mic.service
  systemctl daemon-reload
  systemctl start vic-anim.service vic-engine.service
  systemctl start vic-switchboard.service
  systemctl start vic-cloud.service
  trap - EXIT
  echo '36d native microphone application active; rollback timer awaits validation.'
  ;;
 *) echo 'Use --stage or --activate' >&2; exit 2;;
esac
