# Overnight work, October 18–19, 2026

**Owner clarification on October19:** use Vector's internal microphone. The host
microphone fallback does not satisfy the goal. Follow the newer
[native microphone results](NATIVE_MIC_RESULTS.md) for daytime physical trials;
the older host-microphone recommendation below is historical.

## User objective and operating limits

The user is asleep and explicitly asked for continued overnight work on:
1. Real continuous listening/talking, without a wake phrase every turn.
2. Web-admin entry/exit and clear mode display.
3. Optional touch pattern or lift gestures.
4. The simplest event network and whether Mac can run Duck and Vector together.

Keep the robot quiet overnight: no audible tests, motion, firmware flashing,
or unattended paid sessions. Offline implementation, tests and read-only diagnostics
are useful. Do not ask routine questions while the user sleeps. Do not spawn
subagents: current developer instructions prohibit delegation unless requested.

Heartbeat automation `vector-continuous-voice-overnight` was created in this chat,
every 30 minutes, for 18 runs. Work deadline: October 19 at 08:00 America/New_York.
At completion/deadline stop further overnight work, preserve the source and leave
a consolidated morning handoff. User authorization to reuse/save the duck key
persists; do not repeat the credential questions or expose the key.

## Current hardware and deployment

- Local repo `/Users/jfizel/wire-pod`; shared cwd initially Duck Tales.
- Pi `pi@10.0.0.212`, SSH `-o BatchMode=yes -o HostKeyAlias=escapepod.local`.
  Passwordless sudo. Pi4 1GB, Debian13 aarch64. Ethernet connected; **Wi-Fi is
  disconnected**. Hostname `escapepod`. Leave network configuration unchanged.
- Vector serial `00a14a38`, address `10.0.0.91`, firmware `2.0.1.6076ep`.
  Read-only TCP checks found SSH22 and developer HTTP8888 unavailable.
- Original installed executable/source are preserved at `/home/pi/wire-pod/chipper`.
  Existing staged user changes include go-openai1.41.2 and gpt-5-mini; preserve them.
- Active wire-pod binary is isolated at
  `/home/pi/vector-live-build/chipper/chipper-livevoice`.
  `/etc/systemd/system/wire-pod.service.d/90-vector-audio-tap.conf` launches
  `/home/pi/vector-live-build/vector-live/run-livevoice.sh` from the original
  runtime directory. `/home/pi/vector-live-build/chipper/chipper-livevoice-before-emptyguard`
  preserves the previous experimental binary too.
- Full root-only installation backup:
  `/home/pi/vector-live-backups/20261019T013841Z` (518-member archive verified).
- Pi companion `/home/pi/vector-live-app`, private0700, pinned Python3.13 venv.
  Approved reused key is `/home/pi/vector-live-app/.env`, OPENAI_API_KEY,0600 pi.
  Mac existing key remains `/Users/jfizel/Rubber-Duck/goth-duck/.env.local`.
- `vector-live.service` is installed, on demand, Restart=no; **currently inactive**.
  Last check wire-pod active, API `/api/is_running` true.
- Current live speaker volume default **80/100**, unit explicitly `--volume 80`;
  CLI accepts0..100. No new audible test at80 has been performed by agent overnight.

## What already works (and what does not)

This is a **wake-gated prototype**, NOT the user's required continuous mode.
`conversation.py` uses GPT-Live1/Marin, backend gpt-5.4-mini, curious warm earnest
explorer personality. Store=false, no recordings or logged user transcripts.
Existing code requires Hey Vector for every turn. Idle60s, maximum10min,
spoken stop tool, back-touch stop, host SIGINT, bounded buffers and cleanup.

Hardware verified: start phrase opened the Pi service; owner heard "Live voice
is ready" in Marin; actual spoken end invoked end_conversation; session closed
with finalized35-second usage, no error, clean socket; subsequent ordinary clock
command worked, owner confirmed no humming. Earlier direct Pi session received6
real requests and completed2 speaker segments, finalized139s on host stop.

Native adapter in `preqs/livevoice.go` accepts only selected serial, requires
companion ACK BEFORE consuming additional audio; absent companion leaves normal
STT unchanged. Socket `/home/pi/vector-live-runtime/live.sock` is private. Raw
audio tap in `audiotap` exists separately and is disabled without observer socket.

Two fixed problems: (1) Vosk heard "conversation man" / "the chat" and missed
custom startup; (2) an empty legacy KnowledgeGraph transcription led to an API400
and a stuck SDK thinking animation. Isolated `knowledgegraph.go` now completes
empty/error recognition immediately before entering SDK/LLM. Do not overwrite Pi
source files wholesale from newer local base; apply narrow patches preserving
pre-existing Pi changes.

`manage_intent.py` manages TWO lowercase-JSON intent definitions: start includes
conversation mode/man, start chat, let's/lets/let us talk; stop includes end/and
our conversation and stop conversation. The stop intent safely handles requests
when live service is already off. Installer must restart wire-pod AFTER adding
intents because Vosk builds grammar at startup. Current controls both installed.
Start greeting explicitly identifies "Live voice is ready".

Tests:16 Python passed.7 native Go tests passed, including opt-in integration
using actual installed customIntents.json and harmless substituted executable.
Go race detector unsupported by Pi kernel VMA configuration. Native commands:

```sh
cd /home/pi/vector-live-build/chipper
export CGO_CFLAGS=-I/root/.vosk/libvosk CGO_LDFLAGS=-L/root/.vosk/libvosk
export LD_LIBRARY_PATH=/root/.vosk/libvosk
export VECTOR_CONTROL_TEST_FILE=/home/pi/wire-pod/chipper/customIntents.json
/usr/local/go/bin/go test -v ./pkg/wirepod/preqs ./pkg/wirepod/audiotap
/usr/local/go/bin/go build -o chipper-livevoice-next cmd/vosk/main.go
```
Run native build/test as root (sudo bash), with source.sh if needed. Never build
over the executable while active; build `-next`, then replace after successful
checks/restart. `rollback-audiotap.sh` stops companion, removes BOTH custom intents,
removes only the experimental override, and restarts the original installation.

## Research findings from this turn

1. Direct primary source **matches the fake microphone waveform exactly**:
   https://github.com/os-vector/wire-os-victor/blob/main/engine/components/sdkComponent.cpp
   around lines260–350 generates a temporary1kHz sine at amplitude1000 and sends
   AudioChunk. AudioSendMode only toggles SDK_WANTS_AUDIO; a TODO says it needs
   real process plumbing. This matches our measured identical1600-sample blocks,
   ±1000, RMS−33.3dBFS. It is a source comparison, not a disassembly of this robot.
   Changing an SDK request enum alone is not a fix in that implementation.
2. Primary issue https://github.com/digital-dream-labs/vector-cloud/issues/6
   reports constant SDK test tone and unexposed AudioSendModeRequest. No comments.
   Gateway source actually requests VOICE_DETECT when opening AudioFeed:
   https://github.com/digital-dream-labs/vector-cloud/blob/main/gateway/message_handler.go
   around2479–2537. Fake tone originates upstream in engine implementation.
3. Original DDL rolling source is incomplete (engine/components absent), so do
   NOT claim the whole firmware was reviewed. Native connector used for source;
   code search returned no matches. Sparse checkout `/private/tmp/vector-firmware-source`
   contains DDL main engine/animProcess/clad/docs/platform config for rg searches.
   More complete WireOS files were read through native GitHub connector.
4. Native mic stream path `animProcess/.../micData/micDataSystem.cpp` has
   StartWakeWordlessStreaming plus finite CloudMic timeout/completion. Repeated
   AppIntent re-arming would still have gaps; do not present it as full duplex.
   No continuous capture path has been proven on this production firmware.
5. PyPI `wirepod-vector-sdk-audio==0.9.0` was inspected WITHOUT installing/executing:
   primary https://pypi.org/project/wirepod-vector-sdk-audio/0.9.0/
   Its wheel `anki_vector/audio_stream.py` merely consumes modified wire-pod
   websocket `/api-audio/stream` and separately calls `/api-audio/trigger_listen`.
   It does not demonstrate a continuous native microphone stream. Homepage points
   to ordinary kercre123/wirepod-vector-python-sdk, whose master lacks that module.
   Do not install this as a purported solution or adopt its unbounded recording buffer.
6. Official OpenAI continuous PCM API was refreshed:
   https://developers.openai.com/api/docs/guides/voice-websockets
   Continuous paced PCM16 16k is supported; primary socket output has no audio-done
   event or playback timestamps. Session.close -> session.closed final usage.
   Model already supports simultaneous listening/talking; local capture is blocker.
7. Duck code is at `/Users/jfizel/Rubber-Duck/goth-duck/gothduck/audio.py`.
   Uses sounddevice>=0.5,<1 plus livekit==1.1.18 APM, 10ms16k mono frames,
   explicit input device names, continuous input during output, own playback
   reference, calibrated echo delay. USB duck capture already works without Wi-Fi.
   Mac is arm64. Separate venvs avoid protobuf clashes. Two sessions can coexist
   technically, but acoustic cross-talk/agents answering each other needs rehearsal.
8. Event network primary sources:
   https://support.anki.bot/article/104-troubleshooting-vectore28099s-connection
   supports2.4GHz, rejects captive portal, disable AP/client isolation.
   https://github.com/kercre123/wire-pod/issues/335#issuecomment-2135354879
   and #issuecomment-2147942565: ep firmware hardcodes escapepod.local; mDNS or
   correct LAN DNS must point at server. Do not run Pi and Mac advertising same
   escapepod name simultaneously. Current Pi working wired is valuable.

## Recommended next implementation sequence

1. Build a **real continuous host-microphone input** path as an explicitly labeled
   option. Mac room/USB microphone ->16k PCM+AEC ->existing Live transport;
   output ->Vector speaker over existing SDK. Capture must continue during
   playback. Source label must say host microphone, not Vector's internal mics.
   Optional desktop dependencies sounddevice and livekit; do not alter Duck.
   Preflight device/format before opening paid session, no actual overnight capture.
   Feed actual rendered PCM into AEC; account for Vector's200ms playback prefill
   plus Wi-Fi delay. Acoustic/full-duplex rehearsal is still required in morning.
   Keep wake-gated prototype available but clearly labeled. Firmware modification
   for native mics remains a separate proposed path; no unlock/flash overnight.
2. Web-admin start/stop + real state. Prefer a small controller behind same-origin
   wire-pod API, private Unix IPC/loopback, fixed allowlisted service/process
   commands, POST for actions. No API keys/pairing tokens in UI or status.
   Status should include actual source, readiness, mic activity, speaking,
   elapsed time, errors, finalization. Active process alone is NOT live readiness.
   False/stale status must never show a green continuous-listening indicator.
   Stop must release mic/player/control and stop paid session. Start idempotent.
   Native Pi control can use systemd; portable Mac adapter can own subprocess.
   Keep paid companion OFF during overnight testing. Test with fakes.
3. Optional gesture detector: state-only robot_state listener, no motion commands.
   Debounced touch pattern with cooldown, disabled by default until rehearsed;
   lift gestures lower priority because normal animation can imitate them.
4. Event recommendation: likely bring known-working Pi plus Mac and a small
   private2.4GHz router: Pi Ethernet, Vector Wi-Fi, Mac same LAN, Duck USB.
   Preconfigure SSID/passphrase and DHCP reservations before departure; only
   router's Internet uplink changes at venue. A direct venue guest network risks
   captive portal and isolation. Mac-only reduces box count but needs wire-pod
   migration/cert/pairing/service/mDNS rehearsal; do not assume it works today.
   Never factory-reset Vector just to change the venue network.

## Still outstanding

### Completed since the initial research checkpoint

- **Web controls are implemented and deployed** at
  `http://10.0.0.212:8080/vector-live.html`, homepage link **Vector Voice**.
  Files: `chipper/pkg/wirepod/config-ws/livevoice.go`, its test, a five-line
  early routing addition in webserver.go, and `chipper/webroot/vector-live.html`.
  Local homepage also patched; deployed older homepage was modified narrowly,
  with backup `.../20261019T013841Z/before-voice-admin-index.html`.
- Native API `/api/vector-live/status`, POST `/start` and `/stop`. Start explicitly
  accepts `mode:wake`; continuous returns409 while its source is unconfigured.
  Fixed systemd unit, no arbitrary command arguments. Same-origin + custom header
  (`X-Vector-Control:1`) required for mutations. This route bypasses legacy
  wildcard CORS. GET mutations405, cross-site POST403. Starts idempotently;
  deactivating service refuses restart until shutdown completes.
- `runtime_status.py` writes atomic0600 process heartbeats every2s, containing
  mode, PID, readiness, source, mic/speaker activity, elapsed time and segment
  count, with no conversation text/audio/credentials. conversation.py optional
  `--status-file`; Pi unit now sets `/run/vector-live-companion/status.json`.
  Unit creates private pi-owned tmpfs runtime directory and preserves final
  status after exit. Active status requires matching PID and heartbeat<=7s old;
  stale/absent heartbeat is unverified, never green/listening.
- Current UI labels prototype honestly, shows legacy/off now, and disables
  continuous start with explanation. This is **not** completion of continuous
  mode. Verified deployed API200 legacy/off; unsupported start409, cross-origin
  wake start403, GET start405; companion still inactive, wire-pod active.
- 17 Python checks pass (new heartbeat check);4 new admin Go checks pass. Existing
  seven native checks had already passed. New server compiled successfully,
  installed and healthy. Backup before admin is
  `/home/pi/vector-live-build/chipper/chipper-livevoice-before-admin`.
- Latest config override includes VECTOR_LIVE_ADMIN=1 and status path. Updated
  config was synced to build/vector-live/wire-pod-livevoice.conf too. No private
  credentials copied beyond the already-approved .env.
- Rollback now removes only our marked homepage link/page, as well as stopping
  companion/removing both custom intents/removing override/restarting original.
  Updated rollback is installed under build/vector-live and app. **Activation
  helper does not yet reinstall removed UI assets after a rollback**; extend that
  helper or document deployment before treating install/rollback as symmetric.
- Mac bridge now has `--ssh-target` default pi@escapepod.local and --wirepod
  default http://escapepod.local:8080. Pi unit still uses127.0.0.1. New CLI was
  checked with --help, no mic/API opened, and current conversation.py synced to Pi.
- [EVENT_SETUP.md](EVENT_SETUP.md) contains the router/Pi/Mac comparison,
  network requirements, discovery notes, event runbook and remaining rehearsals.
- Browser inspection used a hidden in-app tab (iab browser2, tab1). AX and
  screenshot show correct legacy/off and unavailable continuous input; no Start
  click occurred. Marked handoff. If resuming CUA from a compacted context, load
  its documentation as instructed before interacting.
- A bounded `/usr/bin/caffeinate -i -t ...` process prevents **idle** sleep until
  Oct19 08:00 New York. PID49317 also saved in
  `/private/tmp/vector-overnight-01a15183.pid`. It does not override lid closure
  or keep Codex open. Official docs confirm local scheduled tasks need computer
  on and app running: https://developers.openai.com/codex/app/automations.

### Next

Continuous host input, correct full-duplex playback reference/AEC, portable
Mac control integration, optional gestures, and morning acoustic tests remain.
Do not present the disabled continuous button as completion. Continue from the
implementation sequence above; no need to redo research or restore the tested
prototype. Keep paid sessions and physical audio/movement off overnight.

## Latest checkpoint — supersedes the preceding Next section

See [MORNING.md](MORNING.md) for the concise handoff. The quiet offline deliverables
are prepared. Further acoustic validation needs the user awake; no audible or
paid tests should run automatically. Preserve the current tested build.
Heartbeat automation was set to PAUSED after the quiet deliverables were
prepared, following the instruction to stop when those deliverables are ready.
No further automatic overnight edits or tests are scheduled. The bounded
caffeinate process can expire at08:00 as configured.

- Implemented `host_audio.py`, `host_audio_worker.py`, `host_audio_bridge.py` and
  the isolated `host-audio` environment. Modern LiveKit requires protobuf>=5,
  incompatible with Vector's protobuf3 SDK; binary PCM pipes isolate dependencies
  rather than replacing either working environment. Main base lock/requirements
  remain unchanged; separate worker lock is checked in the source tree.
- Continuous mode now uses an explicit host microphone, keeps input flowing
  during output, feeds accepted speaker RPC PCM into AEC, fails on stalled clocks
  or bounded queue overflow, and has a separate direct-speech prompt/greeting.
  AEC200 ms is an estimate; no exact Vector playback timestamp is available.
- `conversation.py` holds behavior control across continuous sessions, drains
  duplicate wake requests without mixing/gating host input, closes on host or
  SDK-control loss, and exits nonzero on errors. `vector_audio.py` monitors the
  behavior-control stream after grant and reports loss. Cleanup tests cover
  maximum duration, mic failure, failed API startup, control loss and release.
- `host_controller.py` owns on-demand Mac child sessions and a private Unix HTTP
  control socket. SSH reverses it to
  `/home/pi/vector-live-runtime/control.sock`. No mic/key/API is opened until
  explicit Start. Losing the control tunnel closes the child. SIGINT shutdown
  gets35 seconds before a hard bound. The idle controller is currently OFF.
- Native `config-ws/livehost.go` proxies only the fixed private Unix controller.
  Admin refuses overlapping modes, serializes mutations, and reserves pending
  starts against systemd's asynchronous startup. An atomic0600 host-state marker
  preserves unconfirmed remote activity across a wire-pod restart; uncertainty
  cannot appear as green readiness or confirmed off. Status/UI show actual source.
- New isolated native binary/admin page/config are deployed. Override now also
  sets VECTOR_LIVE_HOST_SOCKET and VECTOR_LIVE_HOST_STATE_FILE. Previous binary:
  `/home/pi/vector-live-build/chipper/chipper-livevoice-before-host-admin`.
  Compatible cleanup/runtime Python files synced to Pi; original installation
  and approved private .env are preserved. App runtime backup:
  `/home/pi/vector-live-backups/20261019T013841Z/before-host-runtime.tar`.
- Activation helper now reinstalls marked UI assets after rollback, refusing an
  unrelated page. `stop_host.py` confirms remote shutdown before rollback removes
  the admin/override; invoked via sudo for the root-only state marker. Both copies
  of rollback/helper are deployed. Shell syntax checks pass; rollback itself was
  not executed against the live installation tonight.
- 30 Python tests pass, including real isolated APM and binary pipes with a
  synthetic PortAudio substitute.16 Go tests pass across admin/preqs/audiotap;
  nine admin checks include private Unix transport and restart-state persistence.
  JavaScript syntax and git diff whitespace checks pass. Tests used no paid API,
  actual microphone capture, speaker playback or movement.
- Real unpaid control bridge was exercised with **no microphone selected and a
  nonexistent key file**. Pi status correctly said configure the Mac controller;
  web-admin Stop reached it. Controller exited cleanly; final Pi status is
  legacy/off, wire-pod active and voice service inactive. An immediate health
  request during wire-pod startup initially refused connection; retry after
  startup succeeded. No service failure remained.
- `EVENT_SETUP.md` now includes optional controls assessment: prefer admin,
  double-tap next after calibration; arms lower priority. No idle gesture watcher
  was installed and no firmware was flashed. Native internal-mic capture remains
  unproven; host-mic continuous capture is implemented but awaits acoustic test.

Potential robustness follow-up: the current companion reports transport errors
in final JSON but can still exit0, so systemd may call a failed session successful.
The admin currently maps failed systemd units to error, but not a stopped session's
last JSON error. Make exit/error state truthful without disrupting cleanup.

Finish with concrete changed files, validation, remaining physical checks and
a morning recommendation; keep this handoff current for later heartbeat turns.

## October19 firmware/reopening follow-up

Read the current [native results](NATIVE_MIC_RESULTS.md) and [firmware plan](FIRMWARE_PLAN.md).
A control take/release plus350 ms grace successfully opened ten consecutive
six-second windows, with nine measured gaps2.601–2.675 seconds. Waiting alone
failed even at2 seconds; zero grace with control reset failed on the third
window. Published WireOS source and build documentation provide a concrete
custom-firmware route in separate repositories; existing EP installation is
not equivalent to an unlock. A longer input experiment needs coordinated mic
and behavior timeouts. No new firmware has been built or flashed. Temporary
probe settings were removed and the pre-test server restored; paid voice off.

## October19 authorized firmware implementation

User explicitly requested unlocking and building firmware. See
[firmware/UNLOCK_AND_BUILD.md](firmware/UNLOCK_AND_BUILD.md) and
[firmware/BUILD_MANIFEST.json](firmware/BUILD_MANIFEST.json).
Pinned wire-os-victor and EXTERNALS source cloned; baseline and coordinated
30-second native mic experiment both compiled successfully on the Mac. Separate
baseline runtime package preserved. The patch also raises the newly identified
gateway nine-second timeout to35 seconds; merely changing the mic constant is
insufficient. No runtime deployment or firmware flash yet.

Production unlock and WireOS3.0.2.34d base downloaded and inspected. Unlock's
startup runs compiled install-recovery, zeros both boot images, reboots into
recovery; immediate base OS installation is required afterward. No full robot
userdata backup is possible with current access; don't promise preservation.
Original Pi installation backup verified present; live service remains off.

User reports Vector in recovery ready to pair. Chrome Bluetooth attempt ended
in pairing failure. A physical double-press/pairing-screen question is pending;
no OTA was selected or sent. Resume existing Vector Setup tab, not the unrelated
Chrome window the user is currently working in. Staging/build logs and large
images/checkouts are ignored; source patch and checksums remain reviewable.

## October19 after owner flashed WireOS

Developer SSH confirmed WireOS3.0.2.34d, app3.0.2.0, compatibility209, expected
serial and hostname at10.0.0.91. No custom robot binaries were deployed.
Stock services ran without restart loops, but SDK TLS timed out from Mac and Pi.
Runtime backups were slow; anki-robot.target was stopped to finish a consistent
backup. Network then became unreachable, with 100% ping loss from both hosts
and FAILED Pi ARP. All attempted robot backups are incomplete and clearly named
partial. Stock /anki is extracted from the pinned local OTA, but comparison to
the robot could not complete. Original Pi installation backup is unchanged.

Owner confirmed blank face/back lights on. Requested normal5-second power-off,
release, wait10seconds, single press, ~1minute boot; response pending. On return,
restore/verify stock runtime and network before custom deployment. Last confirmed
robot services were stopped; a normal reboot should start them. See current
firmware/UNLOCK_AND_BUILD.md and BUILD_MANIFEST.json for evidence and state.
Isolated Pi ACK2-only40-second diagnostic built and existing test packages pass;
not activated. Paid service remains off; normal wire-pod service remains active.

## October19 afternoon: firmware experiment passed

This supersedes the interrupted-backup handoff above. Successful live personal-data
backup is verified (748members); core stock binaries match locally preserved OTA.
WireOS changed34d to35d across a reboot while its hourly update timer was enabled;
the old root's candidate was absent. The timer was runtime-masked during tests.
The current35d OTA and extracted runtime are now preserved and payload hashes
verified. Post-final-reboot timer reports disabled; do not silently re-enable it.

Important migration fix: WireOS's default chipper endpoint was a community server,
and no /data/data/server_config.json override existed. Copying the Pi's existing
server_config.json and public TLS certificate into /data/data restored native
input to the Pi without resetting pairing or onboarding. A cloud-only restart
could not reconnect an internal switchboard socket; full service restart worked.
SDK status succeeds, but SDK AudioFeed still emits synthetic repeated data.

Stock native baseline:50chunks/6.0seconds. Compiled test: THREE successful captures
of250chunks/30.0seconds genuine native PCM, clean EOF, no repeated test signal.
Two consecutive windows had3.212seconds gap using control reset+350ms grace.
No OpenAI, audio file or replay. See firmware/NATIVE_30S_RESULT.json and
firmware/NATIVE_30S_REPEATABILITY.json. This establishes firmware extensibility;
it does not implement continuous input. Next design: bounded processed-PCM
stream from anim process to SDK AudioChunk events, replacing fake sine generator.

Final cleanup is verified: temporary bind mount removed via helper's reboot
fallback (normal umount was busy); original stock35d hashes and active target
verified; SDK status works. Pi pre-test binary hashes match, diagnostic override
removed, no live.sock. Web admin: modelegacy, live serviceinactive, readyfalse.
Owner confirmed the final clock command works. Pi routing remains installed intentionally.
Unused candidate on robot and all builds/source/backup/images on Mac are preserved.


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

First activation left stock engine/anim running; the fake-tone diagnostic rejected
that mixed runtime. Corrected helpers explicitly stop/start all core units and
verify running executable hashes plus the mapped engine-library inode. Reboot
rollback completed after all tests. Stock core files, loaded stock mic/library,
read-only root, absent bind mount and SDK health were verified. Admin is legacy /
live inactive. The owner confirmed the final clock command works; see manifest.
