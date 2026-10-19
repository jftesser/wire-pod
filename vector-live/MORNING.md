# Morning handoff — October 19

## October19 native continuous SDK milestone

The custom application now exposes authentic processed microphone PCM through
SDK AudioFeed. A 75-second physical test delivered 736 consecutive groups with
zero group gaps; three fresh starts, abrupt-client cleanup/reconnect and capture
during speaker playback passed. The RAM-only replay contained recognizable
ambient room sound. This proves continuous native transport over the test
interval; OpenAI Live integration, echo cancellation and admin enablement remain
unfinished. Normal command timeout constants remain stock. See
[firmware/CONTINUOUS_MIC.md](firmware/CONTINUOUS_MIC.md) and
[metrics](firmware/CONTINUOUS_MIC_RESULTS.json). The experimental runtime is
removed after tests; the inactive candidate and all source/artifacts are kept.


**Afternoon firmware milestone:** Vector is unlocked and running WireOS35d.
The compiled application experiment delivered30.0seconds of genuine internal
microphone PCM in three successful captures. Consecutive windows still had a
3.212-second gap; always-on SDK input remains the next firmware task. Stock
runtime, normal Pi server and legacy/admin mode are restored, with live voice
off. See [firmware/UNLOCK_AND_BUILD.md](firmware/UNLOCK_AND_BUILD.md) for the verified
backup, required Pi routing override, update-timer discovery and measured results.

**Daytime update:** the owner requires Vector's own microphone. See the newer
[native microphone trials](NATIVE_MIC_RESULTS.md): software-triggered genuine
speech and capture through speaker playback work in six-second windows;
rearming now passes a short repeated trial with about2.6-second gaps, while uninterrupted input remains unresolved. The host-microphone work below is a
fallback and does not fulfill that clarified requirement.

**Prepared:** continuous host-microphone input, Vector speaker output, web-admin
start/stop and truthful source/readiness indication. **Not physically validated:**
the new continuous path, echo cancellation, natural interruption, or two-agent
acoustics. No audible tests, movement or paid sessions ran overnight.

## The important limitation

Vector's internal SDK microphone is a repeated test signal on this robot. A
primary firmware source generates exactly that signal; this is a source match,
not disassembly of the installed firmware. No continuous internal-mic path is
proven. The prepared working alternative uses a **Mac/USB microphone**, clearly
labeled in admin. Native internal mics would require another proven interface or
firmware work with an unlocked/development robot and recovery plan.

## What's implemented and checked

- Continuous capture stays open during speaker playback, with isolated LiveKit
  WebRTC echo cancellation and a bounded PCM bridge. No recordings or transcript
  logs. The estimated200 ms echo delay needs calibration in the actual room.
- The Mac controller opens no microphone or paid session until web-admin Start.
  Sessions retain the10-minute maximum,60-second idle limit, spoken end tool,
  touch stop and process stop. Control loss, microphone/transport failures and
  buffer overflow end the session and release resources.
- [Vector Voice admin](http://escapepod.local:8080/vector-live.html) is deployed.
  It distinguishes ordinary mode, wake-word prototype and continuous host input.
  Readiness requires a fresh matching child heartbeat. Start refuses competing
  modes. Stop targets both companions. Bridge loss stops the Mac child; the Pi
  keeps uncertainty across restarts until it confirms remote closure.
- 30 Python tests pass, including real AEC with a synthetic microphone, process
  pipes, control loss and session cleanup.16 native Go checks pass across admin,
  capture and recognition. The real unpaid Mac→SSH→Pi bridge and Stop were tested
  with no microphone selected and a nonexistent key file.
- Original Pi binary/source and root-only installation backup remain preserved.
  New backups include `chipper-livevoice-before-host-admin` and
  `before-host-runtime.tar` within the existing backup directory. Reactivation
  restores the marked admin assets; rollback first confirms the Mac is stopped.

## Start the morning rehearsal

1. Use [README.md](README.md)'s host-audio setup/list-devices command to choose a
   unique Mac/USB microphone. Environments are already installed on this Mac.
2. Start `host_controller.py` with that name and the existing duck key file as
   shown there. This opens only the unpaid controller; admin Start opens voice.
3. Open Vector Voice, start continuous mode, and speak directly after greeting.
   Test a second question, speaking over Vector, quiet listening, spoken stop,
   web Stop, touch stop, microphone unplug and network interruption. Confirm
   ordinary clock commands work after exit. Tune AEC delay if speaker echo leaks.
4. Rehearse both agents together before calling simultaneous operation proven.

Current final state: wire-pod active; Pi voice inactive; Mac test controller and
microphone helper stopped; admin ordinary/legacy off. Continuous start remains
disabled until the controller is configured. Speaker volume is80/100; no new
overnight audition at that volume was performed.

## Event and optional controls

Bring the working Pi, Mac and a private2.4 GHz router. Pi uses Ethernet, Vector
uses that router's Wi-Fi, Duck uses Mac USB. Provision/rehearse the same SSID
before departure and change only the uplink at the venue. Mac-only wire-pod is
not migrated or rehearsed. [EVENT_SETUP.md](EVENT_SETUP.md) has pairing, addressing,
discovery, recovery and two-agent details.

Web control is the first choice. Double tap is the preferred optional gesture
to calibrate next; an idle gesture watcher was deliberately left uninstalled.
Arm patterns remain an uncalibrated proposal. No robot firmware was changed.
