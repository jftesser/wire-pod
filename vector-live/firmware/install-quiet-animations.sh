#!/bin/sh
# Run on the already-unlocked robot. Adds assets only to the custom application.
set -eu
source_dir=${1:?Supply the staged quiet animation directory}
resource_root=/anki-continuous-candidate/data/assets/cozmo_resources/assets
target=$resource_root/animations
test -f /data/vector-native-mic/mount-native.sh
test -d "$target"
test -f "$source_dir/engine-anim-manifest.json"
cd "$source_dir"
sha256sum -c SHA256SUMS
backup="$source_dir/previous"
mkdir -p "$backup"
mount -o remount,rw /
trap 'mount -o remount,ro /' EXIT HUP INT TERM
for asset in anim_vectorlive_*.json; do
    test -f "$asset"
    if test -e "$target/$asset"; then cp -p "$target/$asset" "$backup/$asset"; fi
    cp "$asset" "$target/.$asset.next"
    chown anki:anki "$target/.$asset.next"
    chmod 644 "$target/.$asset.next"
    mv "$target/.$asset.next" "$target/$asset"
done
if ! test -f "$source_dir/anim_manifest.before.json"; then
    cp -p "$resource_root/anim_manifest.json" "$source_dir/anim_manifest.before.json"
fi
cp "$source_dir/engine-anim-manifest.json" "$resource_root/.anim_manifest.next"
chown anki:anki "$resource_root/.anim_manifest.next"
chmod 644 "$resource_root/.anim_manifest.next"
mv "$resource_root/.anim_manifest.next" "$resource_root/anim_manifest.json"
mount -o remount,ro /
trap - EXIT HUP INT TERM
# Caller reloads vic-anim and vic-engine together to load clips and index. This script never plays a clip.
printf '%s\n' 'Quiet assets installed; original clips and application binaries unchanged.'
