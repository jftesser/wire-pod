# Native microphone + OpenAI Live rehearsal (October19)

The owner authorized the real conversation test after continuous native input
passed. Existing authorization to reuse the duck key and save it on the Pi still
applies. No key was created, exposed or rewritten. Current Mac conversation reads
the approved `/Users/jfizel/Rubber-Duck/goth-duck/.env.local` directly. The Pi's
approved `/home/pi/vector-live-app/.env` remains unchanged. No audio/transcript of
room speech is written. Session `store` remains false.

New source: `native_audio_bridge.py` authenticates the current SDK stream using
five varying source groups before paid startup. It verifies PCM group size,
source sequence, bounded delivery and rejects the old repeating1kHz waveform.
`native_audio_worker.py` uses the existing isolated LiveKit WebRTC APM environment
and opens no host microphone. Tagged binary pipe messages carry160-sample input
blocks and accepted Vector speaker-reference chunks. Input remains open during
playback. The main legacy SDK/protobuf environment and modern APM environment
stay separated. Echo delay is an initial200ms estimate; acoustic effectiveness
is not yet proven.

`conversation.py --input-mode continuous --input-source vector-sdk` selects this
source, holds SDK control, verifies input before Live startup, feeds the existing
bounded Live buffer and performs source/control/idle/duration cleanup. Native
input now skips the old wake-audio Unix server/SSH reverse tunnel entirely.
`host_controller.py` can select the new source and expose its heartbeat to the Pi
admin. Admin HTML no longer falsely labels every continuous source a host mic.
The Pi's previous isolated HTML is backed up as
`/home/pi/vector-live-build/chipper/webroot/vector-live.html.before-native-live`.
No Pi binary, service key file or original installation was changed this turn.

Offline focused tests:21passed under the existing venv, including real isolated
APM processing with synthetic SDK frames, repeat-tone/missing-group/closed-feed
rejection, paid-start/mic/control failure cleanup, source labels, playback and
controller checks. Some host-mode test Unix binds were rejected in the sandbox;
the same suite passes with the local-socket execution permission. No product
failure is attributed to that sandbox restriction.

First paid attempt: native input passed preflight, but startup still spawned the
unnecessary wake-audio SSH tunnel. A gRPC fork warning and493ms delivery interval
coincided with a generic RuntimeError after readiness. The strict250ms Live
upload-clock guard is the likely cause; exact exception text was previously
masked. Removed the redundant native tunnel, and preserve explicit RuntimeError
messages going forward. No spoken playback completed. Final usage was unconfirmed.

Second paid attempt: admin truthfully showed continuous/native input active.
807source groups/80.7nominal seconds arrived with zero group gaps, but no spoken
playback completed. The APM pipe's inherited1s receive timeout fired after source
jitter reached823ms. It closed with confirmed final usage82seconds. Native receive
timeout is now2.5s; the SDK source itself still fails after2s without data. Added
metadata-only input/output level, event-type and frame counters for diagnosis.
The owner reported no response and said they may have spoken too late; no
conclusion about speech recognition can be drawn from that room trial.

A separate12-second synthetic-speech diagnostic passed through the native APM
and Live API without room input or audible playback: usage11seconds finalized,
input RMS-24.9dBFS, output maximum chunk RMS-16.1dBFS, generated Marin speech and
both transcript-event directions. This verifies the APM/API output path under
controlled input. Its synthetic assistant text is safe test content; no room
transcript is logged. Metadata log: `logs/native-live-synthetic-aec-api.jsonl`.

Next rehearsal has a350ms local ready tone after native input and Live are
connected, before the regular voice player starts. The tone's actual accepted
PCM is sent into AEC reference. This is enabled by default for native input
(`--no-ready-tone` disables it). The controller's existing running process need
not reload for that child default. User readiness question is pending; wait for
"Ready now" before starting another90-second room trial.

The unpaid controller is running on the Mac with a private SSH reverse socket:
`/home/pi/vector-live-runtime/control.sock`. It was started as:

```
vector-live/.venv/bin/python vector-live/host_controller.py \
  --input-source vector-sdk --wirepod http://10.0.0.212:8080 \
  --ssh-target pi@10.0.0.212 \
  --key-file /Users/jfizel/Rubber-Duck/goth-duck/.env.local \
  --seconds 90 --volume 80 \
  --session-log /Users/jfizel/wire-pod/vector-live/firmware/logs/native-live-first-conversation.jsonl
```

Its exec session is88998. Earlier32336exited because an old disconnected remote
control.sock prevented forwarding; curl confirmed it stale before unlinking it.
Controller now checks tunnel startup instead of printing readiness then exiting
silently. Subsequent session children reload current Python files on Start. The
controller itself is unpaid; its previous child is stopped. Pi voice service is
inactive. Metadata-only child log path is shown above.

Robot is on compatibility209 / WireOS3.0.2.35d. The verified candidate is
`/anki-continuous-candidate`. Loaded engine library inode43487and microphone
executable SHAa9d62293398f91279bcb20cdcca279610081e86f0e9b3099c830a902edfb4200
matched the candidate. The tested helpers explicitly stop/start cloud, engine
and animation, with a five-minute rollback timer. The timer was renewed for
bounded attended tests and may have restored stock while waiting. Check marker
`/anki/etc/vector-continuous-mic-experiment` and current SDK state before next
trial. Never infer runtime identity from the bind-mount marker alone; verify
loaded mic executable and engine mapped inode too. Stock images and candidate
hashes remain preserved in CONTINUOUS_MIC_MANIFEST.json.

On "Ready now": ensure native runtime is still active; otherwise activate the
existing helper, verify loaded binaries, renew the five-minute rollback timer.
POST `/api/vector-live/start` with `{ "mode": "continuous" }`, JSON content type
and `X-Vector-Control:1`. After the short cue, ask the person to speak immediately,
then a follow-up without wake phrase. Monitor fresh native mic, speaker segments,
API telemetry and clean spoken/admin/touch stop. Maintain90-second paid limit.
After tests, stop the child/controller, restore stock via helper/reboot fallback,
verify stock hashes/loaded processes/read-only root/admin off and owner clock.
Do not claim success until actual speech and follow-up behavior are confirmed.

Official OpenAI documentation checked through the native docs connector:
- https://developers.openai.com/api/docs/guides/live-migration#adapt-the-connection-and-audio-lifecycle
- https://developers.openai.com/api/docs/guides/live-conversations
The greeting section recommends startup developer history plus a continuous
input clock but explicitly says the greeting is not guaranteed. The local ready
cue gives a reliable start signal. No model or voice was migrated.


## Owner-present retry succeeded

The owner explicitly replied ready before the next attempt. The first immediate
Start after firmware restart failed during certificate discovery with
ConnectionRefusedError, before any paid session opened. A direct SDK status check
then succeeded. The subsequent native trial played its ready cue, reported
continuous/native source and fresh mic state, completed five speaker segments,
and the owner confirmed both direct question and follow-up worked without a
wake phrase. The spoken "end our conversation" then reached backend
`end_conversation`, logging `spoken_request` and entering Stopping at about
77seconds, before the90-second bound. Finalization was confirmed at78seconds, with no session error.

The ready cue is enabled by default in the new child CLI, so it works even with
the already-running controller parent. Native source and Live audio diagnostics
now expose only levels, durations and event-type counts, never room speech text.
The native APM receive bound is2.5seconds, while source data stalls still fail at
2seconds.21focused offline tests pass after these changes.


## Spoken exit and cleanup follow-up

The owner initially reported that spoken stop seemed stuck. The request had
reached `end_conversation` and initiated stopping before the90-second limit.
The API then confirmed session closure and78seconds final usage; admin showed
legacy/off, mic and speaker inactive, with no active child. Before any restore
or reboot, the owner explicitly confirmed the normal clock command worked.
This proves eventual behavior release without reboot, but not prompt exit.

Inspection found the microphone and player stopped before API close, but SDK
behavior control stayed held until the outer resource stack exited, after the
cloud finalization wait. The code now releases behavior control before awaiting
API close, keeping the outer stack as a failure fallback. The lifecycle test
asserts the robot is uncontrolled and the mic stopped when API close begins,
for both continuous sources and startup failures.21focused tests pass. This
cleanup timing change is offline-verified and still needs an attended physical
exit check; do not claim its latency is proven on the robot.

Native trial metadata:744groups/74.4nominal seconds, zero group gaps,
maximum delivery interval357.8ms, input raw RMS-34.2dBFS. Five speaker segments
completed. The owner confirmed both the direct question and follow-up. AEC
uses actual accepted speaker reference and input stays open while speaking,
but deliberate interruption/echo stress testing remains outstanding.

The unpaid controller was terminated after confirmed paid closure, and its
confirmed disconnected Pi control socket removed. Pi voice service inactive.
Stock restore was initiated using the tested helper. The animation service
uses a90-second stop timeout; allow the bounded stop/reboot fallback to finish.
Final restore verification is recorded separately in NATIVE_LIVE_RESULT.json.


Final verification: the restore helper returned successfully. Stock35d hashes
for all four core artifacts, loaded mic executable and mapped engine library
matched the preserved stock files. Root is read-only; no candidate mount remains.
Pi admin reports legacy/inactive/not-ready. The first verification's70-second
bound expired while the90-second animation stop was still pending; verification
repeated after helper completion passed. The earlier owner clock confirmation
was before this final restore; no subsequent clock answer was requested.

Result: native microphone conversation and follow-up proven; spoken stop reached
the tool, closed the paid session and eventually returned normal behavior without
reboot. The release-order timing fix has offline regression coverage and awaits
an attended exit check. No paid session or controller remains running.
