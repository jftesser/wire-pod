# Vector unlock and firmware build

Latest result: Vector is unlocked, personal-data/settings backup is verified,
and the corrected test build delivered30.0seconds of authentic native mic PCM
in three successful captures. See NATIVE_30S_RESULT.json and
NATIVE_30S_REPEATABILITY.json. Stock35d runtime hashes, SDK access and active robot
services are now verified restored; the Pi pre-test binary matches its backup,
diagnostic override/socket are absent, and admin status is legacy/live off. The
owner confirmed that the ordinary clock command works after restoration. The source/history below
records earlier failed attempts and their fixes, including Pi routing and an
unexpected stock update from34d to35d.

Robot: Vector-B3N8, serial 00a14a38, previously 2.0.1.6076ep.

Source and EXTERNALS revisions, image URLs and local SHA-256 checksums are pinned
in BUILD_MANIFEST.json. The checkout, image files and build logs are ignored in
the parent wire-pod repository; the patch and this record remain reviewable.

## Image inspection

The published production unlock instructions are at
https://unlock-prod.skittle.dev/ and installer at https://websetup.skittle.dev/.
These were accessed on their published sites. Repository source was first read
through the native GitHub connector, then cloned directly for compilation.

The downloaded Unlock-Prod.ota reports 5.0.0.0-unlocker and ankidev=0. Its
manifest signature verifies with the repository ota.pub. Its decoded system
image matches its embedded size and SHA-256. This verifies internal consistency
and signature against that repository key; it is not an independent security
audit of the publisher or image.

Inspection of that image's /etc/initscripts/ankiinit shows it runs
/usr/bin/install-recovery, zeroes boot_a and boot_b, then reboots into recovery.
The payload contains ankidev-signed.img.gz, recovery.img.gz and recoveryfs.img.gz.
install-recovery is a compiled Go executable, not an audited shell script.
Thus unlock is a migration requiring immediate installation of a new base OS;
the previous EP image will no longer boot after that script completes.

The locally preserved WireOS base reports 3.0.2.34d, ankidev=1. BOOT and SYSTEM
decode successfully and match both sizes and hashes from its embedded manifest.
That OTA has no manifest signature file. Local hashes pin these exact downloads
but do not independently authenticate the unsigned WireOS image.

There is no full robot backup: developer SSH is not yet available. Robot userdata
preservation and pairing across this migration have not been proven here. Do not
clear userdata deliberately. The original Pi installation and pairing backup
remain at /home/pi/vector-live-backups/20261019T013841Z/installation.tar.gz;
root ownership and mode 0600 confirmed. Paid vector-live.service remains off.

## Build and experiment

Mac prerequisites installed from Homebrew: ccache, gcc, upx, wget; ninja and
pkg-config were already installed. e2fsprogs supplies read-only debugfs image
inspection. The upstream build downloads its tools into ~/.anki. Baseline build
command from the checkout is ./build/build-v.sh, logging to
../logs/baseline-build.log. Build and installation completion must be verified
before calling that build successful. The baseline build completed successfully
with exit 0 on October 19. vic-anim and vic-engine are ARM EABI5 hard-float ELF
binaries with interpreter /lib/ld-linux-armhf.so.3. That loader is present in
the preserved WireOS base, and both application and base report compatibility
number 209. This checks architecture and declared compatibility, not runtime
functionality on the robot. A staged baseline package is preserved at
images/baseline/anki. Current rsync was also installed for upstream staging.

long-listening-30s.patch coordinates four limits: native microphone 30 seconds,
prompt behavior 35 seconds, reaction behavior 35 seconds (console max 40), and
the gateway voice request timeout 35 seconds (previously 9). It has been checked
for clean application against the pinned source and applied after the successful
baseline compilation. The first experiment is a
bounded transport test, not a completed always-on SDK microphone implementation.
The modified build also completed successfully with exit 0. Checksums of the
baseline and modified vic-anim, vic-cloud and libcozmo_engine.so are distinct
and recorded in BUILD_MANIFEST.json. No build has been run on Vector yet.
Both staged packages completed with exit 0. The modified package at
images/long-listening-30s/anki matches the recorded compiled-artifact hashes.
The processed-audio job retains chunks, so indefinite operation needs a ring
buffer or another streaming design; merely raising this constant indefinitely
is unsuitable. Ordinary server speech-end VAD should still end short commands.

## On-device sequence

1. Charger throughout. Hold back button ~15 seconds to dark blue lights; release,
   wait for setup URL, then double-press to advertise Bluetooth.
2. Chrome websetup: Utility stack, pair, keep auto setup checked, configure Wi-Fi,
   select exactly Unlock-Prod.ota (not OSKR/PVT variants).
3. Wait for the complete recovery migration; do not power-cycle during flashing.
4. Reconnect in recovery, Custom firmware stack, choose WireOS. The downloaded
   pinned base is available locally if the upstream catalog changes or fails.
5. Establish SSH, save robot-resident data and stock WireOS /anki before app
   deployment. Verify the new OS, network and wire-pod pairing first.
6. Preserve the compiled baseline, then deploy the coordinated experiment.
   Validate native capture beyond 6 and 9 seconds without a paid API session.
   Test stop/cancel, ordinary commands after exit, and repeated sessions.

If web Bluetooth fails, the setup page's generic green check/disconnect screen
does not prove a firmware update succeeded. No firmware has been sent merely by
selecting Utility and opening the Bluetooth chooser.

## Pairing attempt before the flash

The user put Vector in recovery and reported ready to pair. Chrome's first
background request closed immediately; retry with the window raised opened a
Bluetooth chooser. It eventually returned to the generic disconnect screen
with "Pairing failed. Double press robot button and try again. You may need
to do 'ble-clear'." No OTA selection or upload was performed. A question asking
the user to double-press and confirm Vector-B3N8's pairing screen is pending.
The user is using another Chrome window, so do not redirect that active tab.
Resume the existing Vector Setup tab in the original Chrome window when ready.

## WireOS confirmed on robot; network interruption

The user subsequently completed the production unlock and WireOS flash. Developer
SSH verified serial00a14a38, hostnameVector-B3N8, OS3.0.2.34d, application3.0.2.0,
compatibility209 and kernel4.9.277-wrynose-perf at10.0.0.91. Robot services were
active with zero engine/cloud restarts. The existing personal face/photo/token
directories were still present; this is evidence of retained files, not complete
validation of their contents or pairing. SDK TCP connected, but TLS timed out
from both Mac and Pi. No custom robot binaries have been deployed.

Compressed runtime backup was very slow. It was stopped and retained as a
partial archive. A replacement uncompressed transfer also progressed slowly.
anki-robot.target was stopped for a consistent backup; target, engine and cloud
were confirmed inactive. The connection then became unreachable from both Mac
and Pi (six ping attempts from each, no replies; Pi ARP entry FAILED). SSH and
backup attempts could no longer complete. Do not call any of these robot
archives complete. The stock runtime is also extracted locally from the pinned
OTA at images/stock-runtime/anki, but an attempted per-file comparison could not
complete before the network loss. The original Pi backup is unchanged.

The user reports a blank face with back lights on, consistent with stopped robot
services. A normal five-second power-off, release, then single press to boot has
been requested; response pending. Once reachable, restart stock services first,
verify stable network and SDK, then finish personal-data backup before deployment.
Do not reflash, clear userdata, or deploy experimental binaries to resolve this
unproven baseline network problem.

The isolated Pi diagnostic now allows40 seconds only for explicitly enabled
ACK2 native probes, retaining20 seconds for normal live requests. Its three
existing Go test packages pass, and corrected binary
chipper-livevoice-native-probe-40s-next was compiled successfully. The initial
direct source copy lacked permissions; a user-writable staging copy followed by
sudo installation fixed it, and source hashes match. This binary has not been
activated. Paid live voice remains off.

## Recovery, backup, and first temporary deployment

After the owner's reboot, SDK status worked with the existing pairing. The first
reading was3.55V; a later response reported full at3.9717V. Owner reseated Vector
on the powered charger. One additional restart occurred during these checks;
its cause is unproven. Subsequent uptime exceeded8minutes and ping tests had no
loss. CPU maximum was533333kHz with the interactive governor, not an overclock.

The successful backup is images/robot-backup-20261019/personal-settings-stable.tar.gz:
748members, 7240192uncompressed bytes; gzip checksum, all member payloads and the
two-block tar trailer verify. SSH exited0. Its SHA-256 is recorded in
BUILD_MANIFEST.json. This is a live settings/personal-data backup, not a quiescent
filesystem image. Four installed core binaries match the preserved stock OTA.

The separate candidate at /anki-live30-candidate was cloned from the active
runtime, then synchronized with the complete compiled package. A second checksum
dry run reported no differences. Core hashes match BUILD_MANIFEST.json. The new
files needed their group corrected to anki and group read/execute access before
activation; this was done only in the candidate. Loader checks passed.

activate-live30.sh temporarily bind-mounted the candidate at /anki, leaving the
original runtime intact underneath. A five-minute rollback timer was armed.
Services and SDK status worked, but two HTTP-triggered probes and one direct SDK
probe opened no audio connection. Therefore the longer mic window is not yet
validated. The timer was renewed once during diagnosis, never for a paid session.
Manual rollback found the bind mount busy, so its fallback issued a normal reboot;
stock runtime and active robot target were subsequently verified. A reboot always
drops this test mount; it is not a persistent firmware replacement.

## Required WireOS-to-wire-pod migration step

The preserved WireOS image's server_config.json points chipper/tms/jdocs at
vicapi.pvic.xyz:8081. The verified robot backup had no
/data/data/server_config.json override. SDK pairing working did not establish
that voice traffic was reaching the Pi. This was missed before the first probes.

The actual Pi-generated server_config.json was retrieved from its existing
installation, plus the public certificate presented by its TLS listener.
Vector resolves escapepod.local to10.0.0.212. These were installed atomically as
/data/data/server_config.json and /data/data/wirepod-cert.crt, using the CFW
override paths verified in the source. Prior versions, if any, were preserved in
/data/vector-live30-test/routing-backup. No pairing/token/onboarding reset or key
regeneration was performed; the upstream full onboarding-reset script was not run.

A cloud-only restart hit an internal switchboard Unix-datagram reconnect error
(connect: operation not permitted). Robot services were then restarted together.
SDK readiness and stock microphone behavior still need verification after that
restart. native_mic_probe.py now has --direct-trigger: it sends the source-verified
AppIntent protobuf request over the certificate-pinned SDK channel and reports
gRPC failures, avoiding wire-pod's existing HTTP handler that ignores RPC errors
and returns done unconditionally. The request was accepted by the test runtime,
but that alone does not prove behavior activation or capture.

## Corrected stock baseline and 35d update

Stock SDK access returned after the complete service restart. It then reported
OS3.0.2.35d; SSH confirmed the changed /etc/os-version and unchanged compatibility209.
The old root's candidate directory was absent. The hourly update-engine.timer
was enabled (every hour on the hour); update-engine.env enables updates and even
downgrades from ota.pvic.xyz. The version/root change is consistent with an
automatic A/B update, but the writer of that update was not independently traced.
The timer was stopped and masked at runtime for this boot; reboot removes that
mask. No in-progress update service was stopped.

The current published dev OTA was preserved as images/WireOS-current35.ota; its
manifest reports3.0.2.35d. BOOT/SYSTEM decoded sizes and SHA-256 verify. The
extracted stock35-runtime core binaries match the actual active35d runtime.
SDK AudioFeed still produced29identical non-silent frames (2.9seconds), failing
the microphone-authenticity check. That route remains a placeholder.

With the Pi routing fixed, stock native capture via the direct AppIntent request
succeeded:50chunks,6.0seconds audio,5.966seconds wall duration, max168ms delivery
interval, no identical non-silent run, clean completion. This establishes native
input and the adapter on the new base before testing the changed firmware.

A new candidate was cloned on35d, synchronized with the compiled package using
compressed SSH rsync, given correct anki group access, and checked against all
four core hashes. Loader checks passed. It was temporarily activated with a new
five-minute rollback guard. SDK readiness took26.6seconds. The corrected native
30-second transport experiment is now running. Routing and personal data remain
under /data and survive both stock/test runtime switches.

## First successful 30-second native capture

The corrected test produced250chunks,30.0seconds PCM,30.466seconds wall duration,
RMS-39.4dBFS, peak-8.0dBFS, max delivery interval256.1ms, no identical non-silent
run, and clean completion. Server speech-end cutoff was explicitly bypassed by
the ACK2 diagnostic. AppIntent was sent directly over the certificate-pinned SDK
channel. No paid API, audio file or replay was used. These metrics prove a longer
real native transport window, not transcription of every spoken word or a
gapless indefinite SDK feed. User hearing/speech feedback is still pending.

The two additional trials use the same reset-control plus350ms rearm sequence
and thirty-second firmware; results will be recorded after completion. The
standard SDK feed remains synthetic in stock35d. The next firmware design must
plumb real processed PCM from the anim process into SDK AudioChunk events with
bounded buffering and explicit start/stop, replacing SDKComponent's sine-wave
generator. Simply making a global cloud capture timeout enormous would retain
audio jobs and would not supply that lifecycle or buffer design.

## Repeatability and final cleanup

Two additional windows both delivered250chunks/30.0seconds, with clean completion
and no repeated test signal. Their wall times were30.468and30.447seconds; maximum
delivery intervals192.5and263.1ms. The measured EOF-to-next-request gap was3.212s
with SDK control take/release and350ms added grace. These are three successful
windows total, not evidence of indefinite listening or zero lost speech between
windows. No samples were saved and no paid API was used.

The temporary test was stopped after completion. Its normal unmount was busy
again, so the helper's designed fallback rebooted to stock. Stock35d vic-anim and
libcozmo_engine hashes match the preserved35d OTA; no test marker is mounted at
/anki. anki-robot.target is active and SDK status succeeds. The unused staged
candidate remains available, but does not run on reboot. Root is restored to
read-only by the normal boot. The post-reboot update timer reports disabled;
the earlier runtime mask is gone. Its prior activation history is not fully
traced, so do not silently re-enable updates during further firmware work.

Pi wire-pod is active with exactly the pre-test binary hash
1935cd4bc800e19a612d9fa56c4139269216009309f9f8eb4490d8bac36bd442.
The ACK2 diagnostic override was removed and live.sock is absent. Paid
vector-live.service is inactive; /api/vector-live/status reports modelegacy,
service_stateinactive, readyfalse. The owner confirmed the ordinary clock command works after restoration.
The Pi routing override and public certificate intentionally remain installed
on Vector so stock WireOS continues to use this Pi. No pairing reset was needed.
