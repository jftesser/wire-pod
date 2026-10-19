# Vector live voice companion

## Pi deployment

Vector's companion and native echo processor are deployed on the Pi alongside
wire-pod. The local controller uses a private Unix socket; the Mac SSH bridge is
optional development tooling. The controller is enabled at boot but opens no
mic, robot control or paid session until web-admin Start. See
[PI_MIGRATION.md](PI_MIGRATION.md) for deployment, validation and recovery.

The custom robot application is now mounted by `vector-native-mic.service` on
normal boot. The original stock application remains underneath the reversible
overlay. Automatic five-minute rollback is no longer used for this installation;
Live remains off between explicit starts. Earlier bounded-test restore records
below describe the development history.

## Speech boost and expressions

The continuous admin has saved **0 / +3 / +6 dB speech boost** and expression
choices **off / animated eyes / eyes with gentle head nods**. These apply during
an active session. The existing volume slider still controls mute and attenuation.
A soft-knee peak limiter caps boosted speech at -1 dBFS. It does not normalize
all speech to the same loudness. Accepted post-gain speaker samples feed AEC.

The separate behavior coordinator renews short-lived face images at 2.5 fps and
can nod eight degrees relative to the observed head angle, at most once every
12 seconds when a speaker segment begins. It requires fresh, stationary robot
state and suppresses/cancels nods during pickup, falling, cliff detection, pathing,
wheel movement, control loss, or disabling head gestures. Optional expression
failures are visible in admin and do not tear down otherwise working voice.
Stop cancels head actions before releasing SDK control; face images expire.

**Roaming during conversation is an intended next capability.** This coordinator
currently owns face/head only. A navigation policy can issue bounded wheel
commands under the same SDK control while native capture continues, with
collision/cliff/pickup checks, a travel boundary, emergency stop, and motor-noise
AEC tests. Releasing SDK control to ordinary autonomy is not a proven way to
combine roaming with this speaker path. No wheel/lift commands are implemented.

## Configurable gestures and legacy expressions

The Live admin saves **nod depth2–20°**, **automatic nod interval4–30seconds**,
and a separate legacy-expression switch. Nod depth is an excursion from the
observed head angle and is clipped to physical head travel. Head mode permits
head movement; eyes mode keeps native animations face-only. Wheels and lift
remain disabled. `Try expression` works only during a ready continuous session;
it never starts paid voice. Actual completion, cancellation or refusal appears
in the admin status.

The voice backend has a real `perform_expression` function for nod, blink,
happy, veryHappy, sad, verySad, angry, frustrated, dartingEyes, confused,
thinking, celebrate and love. A nod can use the saved depth or a requested
2–20° depth. Spoken performance claims depend on the returned result. Requests
are serialized without an unbounded queue; pickup, stale state, mode changes,
control loss and session Stop cancel head-bearing expressions.

Legacy variants retain the original procedural face/head keyframes from the
same clips mapped by `chipper/pkg/wirepod/ttr/kgsim_cmds.go`. The deterministic
`build_legacy_assets.py` script strips every other keyframe type, including
sounds, wheel/lift motions, nested events and backpack lights. It clamps head
angles to-22°..45°. [The manifest](legacy_assets/manifest.json) records source
archive/member identities and SHA256values for both original members and quiet
outputs. These are modified legacy animations, rather than unrestricted playback
of the original full-body/audio clips.

Only new `anim_vectorlive_*.json` assets are added to the persistent custom
application tree; original clips and the four native-mic binaries stay intact.
`firmware/install-quiet-animations.sh` checks hashes and restores root read-only.
The engine also reads a separate `assets/anim_manifest.json` index. Build with
`--engine-manifest` pointing to a saved copy of that index; the merge preserves
all original entries and adds the new names/lengths. Both the animation process
and engine need reloading after installation. The installer saves the original
index under `/data/vector-live-assets/20261019/anim_manifest.before.json`; restore
it and remove only the new prefixed clip files to undo the addition.
The installer itself never reloads services or plays anything.

The running firmware times out on SDK `ListAnimations`, including with behavior
control granted. It also returns a completed SDK result for an unknown animation
name, as confirmed by engine `AnimNotFound` messages during installation. Live
therefore probes the known quiet happy clip with all motor tracks ignored and
requires a plausible playback duration (at least70%of the authored length), then
uses the versioned allowlist. The first probe waits800msafter control grant to reduce stale-completion races.
Turning expressions off suppresses the probe; enabling legacy during a session
prepares it when the speaker/gesture slot is quiet.
Every expression checks the SDK result, reported animation name and duration;
this rejects immediate false completions and is not a substitute for room testing. A failed clip is removed from the current session's
available choices. Auto-generated RGB eyes pause while a native clip owns the
face, then resume. Cancelling a native animation queues the face-only cancellation
clip NOW; head-bearing cancellation also sends StopAllMotors. No raw legacy-name
fallback is allowed. Simultaneous native animation and Live speech still needs
an owner-present acoustic/gesture trial; silent face-only playback can be checked
without a microphone or cloud session.

## October19 native Live conversation milestone

The owner confirmed a direct question and follow-up both worked through
**Vector's internal microphones**, without “Hey Vector” between turns. The
90-second bounded rehearsal used Marin at volume80, completed five speaker
segments, and closed through the spoken `end_conversation` tool before the time
limit. Final usage was78seconds, confirmed by the API, with no session error.
The native feed delivered744consecutive groups with zero group gaps. No room
audio or transcript was saved.

The owner initially saw Vector appear stuck after spoken stop, then confirmed
that the ordinary clock command worked without a reboot. Cleanup held SDK
behavior control through cloud finalization. It now releases microphone,
speaker and behavior control before that wait;21focused offline tests pass,
including release ordering. This last timing improvement still needs an
attended physical exit check. Echo suppression and speaking over Vector also
need dedicated acoustic tests. See
[rehearsal evidence](firmware/NATIVE_LIVE_REHEARSAL.md) and
[result metadata](firmware/NATIVE_LIVE_RESULT.json).

The native source requires the tested custom WireOS application; stock firmware
still returns the repeated SDK test waveform. The original rehearsals used a temporary mount and restored stock afterward.
The current Pi migration uses the persistent overlay described above. The preserved candidate,
source patch and transport tests are documented in
[firmware/CONTINUOUS_MIC.md](firmware/CONTINUOUS_MIC.md).
Normal wake-command listening limits remain stock. The earlier
[six-second native capture/rearming tests](NATIVE_MIC_RESULTS.md) are historical;
the custom continuous feed overcomes those gaps for the SDK path.

This companion adds bounded OpenAI voice conversations to wire-pod. Continuous
sessions prefer the saved custom voice named Vector, with Stone as the fallback,
and use a curious, warm, playfully earnest personality. Available input paths
are Vector's wake-word request stream, the custom native continuous SDK feed,
and an optional explicitly selected host microphone. The native SDK and wake
paths have passed owner-present spoken rehearsals. The host path remains an
optional fallback with acoustic rehearsal pending.

The operator panel at `/vector-live.html` is linked as **Vector Voice** on the
wire-pod homepage. It has explicit prototype start/stop controls and reports
service state, a private readiness heartbeat, input activity, speaker activity,
source and elapsed time. A saved0–100continuous voice slider also updates active
playback; zero mutes speech without ending the session. An active process or stale heartbeat does not count
as verified listening. Continuous start is unavailable until a real continuous
microphone source and controller are configured. See [OVERNIGHT.md](OVERNIGHT.md) for research and
[EVENT_SETUP.md](EVENT_SETUP.md) for the event plan.

**Hardware verified:** “Hey Vector, conversation mode” started the standalone Pi
companion and the owner heard “Live voice is ready” in Marin's voice. “Hey
Vector, end our conversation” invoked the stop tool, finalized a 35-second
session without errors, removed its socket, and stopped the companion. The next
clock request routed to `intent_clock_time`, and the owner confirmed normal
operation without humming. The companion is currently off; the isolated
wire-pod build remains active, with the original executable preserved.

`conversation.py` opens a paid GPT-Live session (`gpt-live-1`, delegating to
`gpt-5.4-mini`). It streams PCM without saving recordings or logging conversation
transcripts, requests `store: false`, and closes after 60 seconds idle or at the
configured maximum (at most ten minutes). A spoken goodbye, holding Vector's
back touch sensor, or stopping the process also ends the session. Output queues
are bounded; playback releases behavior control on completion or cancellation.
Actual robot status and New York time are available through tools; movement and
camera tools are not implemented.

The separate `probe.py` and `tap_observer.py` diagnostics do not open OpenAI
sessions. The Pi service and trigger intent are installed. The service runs on
demand and remains stopped between conversations.

## Conversation

### Continuous host microphone (prepared, acoustic rehearsal pending)

On stock firmware, Vector's SDK feed returns a repeated test tone. This optional
host source uses a Mac/USB microphone. The tested native source instead uses
`--input-source vector-sdk` with the temporary custom application; see the
rehearsal evidence above.
`host_controller.py` stays idle until web-admin Start; it owns a bounded child
session and bridges a private control socket to the Pi over SSH. Stop addresses
both the Mac child and Pi prototype. A lost controller bridge stops the Mac child;
the Pi preserves an unconfirmed active state across restarts and reports unknown
until it can confirm closure. The two modes cannot start together through admin.

Set up two isolated environments on the Mac:

```sh
cd /Users/jfizel/wire-pod/vector-live
uv sync --locked
cd host-audio
uv sync --locked
cd ..
host-audio/.venv/bin/python host_audio_worker.py --list-devices
```

When awake and ready to rehearse, choose an exact unique microphone name:

```sh
.venv/bin/python host_controller.py \
  --key-file /Users/jfizel/Rubber-Duck/goth-duck/.env.local \
  --microphone-name 'EXACT INPUT NAME' --seconds 600 --volume 80
```

The command opens the unpaid controller/SSH bridge only. The enabled continuous
button in `/vector-live.html` opens the microphone and session explicitly.
Do not run a separate Pi conversation concurrently. Run continuous sessions
through this controller so the web admin owns and accurately reports them.

The helper environment has LiveKit1.1.18/WebRTC AEC and sounddevice; the legacy
Vector SDK stays in its protobuf3 environment. Binary pipes have bounded buffers
and no audio files. Input continues during robot speech. AEC receives PCM actually
written to the speaker RPC, plus silence during quiet intervals. Vector exposes
no exact playback clock: `--aec-delay-ms 200` is an initial estimate, **not measured
echo cancellation performance**. Adjust it during a close-range rehearsal. Test
speaking over Vector, quiet listening, stopping, microphone unplug, and network
loss before using it at the event. The new Mac/bridge code was not used for an
audible or paid overnight test.

Offline verification, including real AEC with a synthetic microphone:

```sh
VECTOR_AUDIO_TEST_PYTHON="$PWD/host-audio/.venv/bin/python" .venv/bin/python -m pytest -q
```

### Wake-word prototype (physically verified)

The prepared Pi service runs from `/home/pi/vector-live-app`, with a private
socket at `/home/pi/vector-live-runtime/live.sock`. Its ignored credential file
is `/home/pi/vector-live-app/.env`, containing `OPENAI_API_KEY`, with mode 0600
and owner `pi`. The owner approved reusing and saving the duck key there.
The custom phrase “Hey Vector, conversation mode” starts the service; “let's talk”
and “start conversation” are also registered. The observed Vosk transcription
“conversation man” and the alternative “start chat” are accepted too. Repeat
“Hey Vector” before each conversation turn.
An independent stop intent handles “end our conversation,” including Vosk's
observed “and our conversation,” when the live service is already off. It stops
the service rather than opening the legacy question/answer path.
Outside an active session, the adapter falls back to ordinary wire-pod commands.
During a session, requests from this robot go to the voice companion.

The Mac development bridge can use the existing duck key file without copying it:

```sh
uv run python conversation.py \
  --key-file /Users/jfizel/Rubber-Duck/goth-duck/.env.local \
  --greet --seconds 180
```

`--audition` supplies a temporary synthetic introduction request on macOS.
`--volume` accepts 0–100; its default is 80, also explicitly set in the Pi service.
This was increased from 35 to 50, then to 80 at the owner's request because the
live voice was quieter than legacy speech. The bridge uses a private Unix socket
forwarded over the existing SSH connection. The standalone Pi service uses
`--local-socket` and needs neither the Mac nor an SSH tunnel.

## Run

```sh
cd /Users/jfizel/wire-pod/vector-live
uv sync --group dev
uv run python probe.py --wirepod http://escapepod.local:8080
```

Status is the default: no microphone, speaker, or behavior control opens.
The diagnostic reads the existing pairing from wire-pod and uses a
certificate-pinned TLS connection directly to Vector. Pairing tokens remain in
memory and are omitted from diagnostic output.

If wire-pod has no saved robot certificate, provide `--certificate /path/to/cert`.
Alternatively, on your trusted local network, explicitly add
`--trust-local-certificate` to enroll the current robot certificate for this run.
Enrollment fetches the certificate without credentials; subsequent gRPC calls
pin that certificate. This is first-use trust, not independent proof of identity.
The certificate and token are not saved.

Explicit audio tests:

```sh
# Four seconds of signal statistics; no audio recording or cloud upload.
uv run python probe.py --trust-local-certificate --listen-seconds 4
# Quiet 0.7 second, 440 Hz tone. Temporarily acquires behavior control.
uv run python probe.py --trust-local-certificate --tone
# Four seconds of input with the tone played during capture.
uv run python probe.py --trust-local-certificate --duplex
```

Playback uses 16 kHz mono PCM16, a maximum 1024 bytes per chunk, pacing based on
the actual sample count, robot completion/error responses, and control release.
Default playback volume is 25/100. Capture is limited to 30 seconds per run.
Repeated non-silent input blocks cause an unsuccessful diagnostic, even when
transport and playback otherwise work. Digital silence alone is not classified
as a test signal, but also does not prove microphone intelligibility.

## Observed on this robot, October 18, 2026

- Server: `escapepod.local`, `10.0.0.212`, wire-pod commit `1310644`.
- Robot: `Vector-B3N8`, serial `00a14a38`, `10.0.0.91`.
- Robot firmware: `2.0.1.6076ep`; engine build `00001.00006.00000`.
- Status and behavior control worked. Speaker acknowledged tone completion.
  An observer still needs to confirm actual audibility and suitable volume.
- SDK AudioFeed delivered 16 frames (1.6 seconds of samples) in a four-second
  standalone window, and 29 frames (2.9 seconds) with behavior control.
- Seven microphone messages arrived during the tone playback. This establishes
  simultaneous message delivery, **not** usable full-duplex microphone capture.
- Input blocks were byte-identical across successive groups, including across
  the speaker test, with peaks of exactly -1000 and +1000 and approximately
  -33.3 dBFS RMS. A follow-up examined four consecutive blocks and confirmed all
  were identical. Treat this API as a suspected test/stuck signal on this firmware.
- The Pi initially rejected `pi` / `raspberry`; the owner subsequently authorized
  this Mac's existing SSH key.

## Pi access and backup

SSH as `pi@escapepod.local` now works. The machine is a Raspberry Pi 4 Model B,
64-bit Debian 13.2, with approximately 906 MB RAM and 49 GB free storage. At
inspection, about 543 MB RAM was available. Go 1.22.4 and Vosk libraries are
already installed.

The installed tree has staged local changes selecting `gpt-5-mini`, updating
the OpenAI client, and adjusting animation/punctuation instructions. The
isolated build at `/home/pi/vector-live-build` preserves those changes.

A complete private backup is at
`/home/pi/vector-live-backups/20261019T013841Z`. It contains the installation
archive (including the original executable, credentials, and repository),
the systemd service definition, and staged/unstaged patches. The directory is
root-only and files have mode 0600. The archive was opened and its 518 members
enumerated after creation.

## Request audio tap

The Go patch is in `chipper/pkg/wirepod/audiotap`. It observes decoded PCM
at the existing request reader; it never creates a second reader on the
robot stream. It covers Intent, IntentGraph, and KnowledgeGraph requests,
including consumers that request Opus rather than decoded PCM.

It is disabled unless **both** environment variables are set:

```sh
VECTOR_AUDIO_TAP_SOCKET=/run/vector-live/audio.sock
VECTOR_AUDIO_TAP_SERIAL=00a14a38
```

Writes use a bounded queue and short deadlines. Missing or stalled observers
cannot block speech recognition. An overflow aborts the capture rather than
silently dropping audio. The observer receives one connection per request:
big-endian uint32 length plus JSON header; then length-prefixed PCM16 frames;
then a zero-length completion marker. An EOF without the marker is incomplete.

The dependency-free observer runs on the Pi:

```sh
sudo python3 /home/pi/vector-live-build/vector-live/tap_observer.py \
  --serial 00a14a38 --timeout 90
```

It accepts one complete request and prints signal statistics, without saving
samples or a transcript. Its socket has mode 0600 inside a private runtime
directory. Use a normal spoken command to test actual capture. Transport
success alone does not prove real speech or continuous full duplex.

The test launcher uses the original runtime directory and speech configuration,
and executes the new binary in the isolated build directory. The original
`/home/pi/wire-pod/chipper/chipper` executable is never replaced. The experiment's
systemd override is `90-vector-audio-tap.conf`; to return to the original service:

```sh
bash /home/pi/vector-live-build/vector-live/rollback-audiotap.sh
```

To re-enable the prepared isolated build, run
`bash /home/pi/vector-live-build/vector-live/activate-livevoice.sh`. This installs
the trigger before restarting wire-pod: Vosk builds its custom-word grammar at
startup, so adding an intent without restarting does not refresh that vocabulary.
Activation does not open a paid session.

The native test build compiled successfully and is now active through that
override. Its localhost `/api/is_running` check returned `true` after restart,
and systemd reported `active`. No OpenAI key has been added to the test build.
The original executable's SHA-256 matches the backed-up copy. The original
source tree has no new unstaged changes; its pre-existing staged changes remain.
The process executable points to the isolated `chipper-livevoice` binary and
Vosk is still configured for English.

A physical test succeeded: an IntentGraph request delivered seven varying
PCM blocks, totalling 0.84 seconds, at -48.3 dBFS RMS and -22.8 dBFS peak. There
were no duplicate non-silent blocks and the request ended with a valid completion
marker. The first attempt was recognized by Vosk as “what name is a” and routed
to name learning. A second attempt was recognized as “what time is it” and routed
to `intent_clock_time`; the owner confirmed it worked. This establishes a real
wake-gated request audio path, rather than continuous capture or full duplex.

The three Go tap tests, two live-adapter tests, empty knowledge request
regression test, and installed-control dispatcher check pass on the Pi. The
dispatcher check uses `VECTOR_CONTROL_TEST_FILE` to read the actual installed
intent definitions, substitutes `/usr/bin/true` for their commands, and verifies
both intended phrases and both observed Vosk variants complete through custom
controls. It does not open a paid session or access the robot.
The Pi kernel cannot run Go's race
detector (unsupported VMA range), so race instrumentation remains unverified.
The seventeen Python tests pass on the Mac, covering signal diagnostics, private
socket framing and cleanup, bounded input, tool result messages and deduplication,
silence gating, playback cancellation, and existing intent recognition/removal.

## Live adapter and deployment status

`VECTOR_LIVE_SOCKET` enables a separate, acknowledged input route. The companion
must acknowledge the request before the adapter consumes further audio; an
absent or unavailable companion leaves the original recognizer in control.
Accepted requests use the existing stream reader, observe end-of-speech, and
have a twenty-second capture limit. Incomplete capture stops the conversation.
The passive diagnostic tap remains independent of this route.

GPT-Live emits continuous output, including digital silence. `voice_player.py`
gates audible output into finite speaker segments. The wake-word prototype
keeps the speaker quiet during captured input; continuous host input remains open
through playback. A segment ending is a playback decision, not evidence of
a model turn ending. Natural interruption and echo cancellation need a physical rehearsal with the
new host-input path.

The owner authorized reuse of the goth duck key. Mac-driven synthetic auditions
have received GPT-Live audio and completed robot speaker playback, with finalized
API usage and no reported playback errors. The owner confirmed a spoken answer
in Marin's voice during the standalone Pi test. Six complete requests reached
the companion through Vector's microphone; two speaker segments completed.
The initial spoken stop request did not close the session. Host stop worked,
with finalized usage of 139 seconds and a clean socket. Explicit frontend and
backend instructions now route ending requests to `end_conversation`; the
corrected spoken stop and natural start phrase were subsequently verified on
hardware as recorded above.
A synthetic stop test with the corrected instructions invoked the actual stop
tool and finalized successfully after five seconds.

The first natural-start test was transcribed as “the chat,” so the companion
never started. A subsequent request entered the older LLM handler, which returned
HTTP 400 for null message content. The owner reported a network display and
humming. Rolling back to the original executable restored the ordinary clock
command, confirmed by the owner. The isolated build was re-enabled with the
trigger installed before the Vosk restart. Final successful verification is
recorded above.

A second start test loaded the custom intent correctly but Vosk heard
“conversation man”; no live session started. That exact variant is now accepted.
The empty knowledge request now returns an empty `NoResultCommand` immediately,
before acquiring SDK behavior control or opening an LLM request. The regression
test covers both empty recognition and recognition errors without a robot or
provider. Original source and executable remain preserved; this guard belongs
only to the isolated build. The corrected executable is active and healthy;
the paid companion is off between conversations. Its greeting now explicitly
says “Live voice is ready.” Final hardware confirmation passed: the original
phrase was recognized correctly, the actual stop tool ran, final usage arrived,
the socket was removed, and the ordinary clock command worked afterward.

The Pi's isolated native build is active and healthy. The companion's Python 3.13
environment and pinned dependencies are installed; import validation peaked at
approximately 75 MB RAM. The systemd unit verifies successfully, is inactive,
and has no automatic restart. `manage_intent.py check` recognizes the installed
intent without duplicating it. Ordinary wire-pod remains active after host stop.
The installed key is excluded from repository tracking and never included in
diagnostic output.

Tests: `uv run pytest -q`.
