# Native continuous microphone application


Current deployment: `vector-native-mic.service` verifies the pinned candidate
hashes and bind-mounts it before robot application services on each boot. The
original stock `/anki` is preserved underneath; root remains read-only. There is
no automatic test rollback timer. To recover manually, remount root writable,
disable this service, restore root read-only and reboot. Do not unmount the
application underneath running robot services. The Pi owns continuous input,
WebRTC processing and Live sessions; see [../PI_MIGRATION.md](../PI_MIGRATION.md).

## Original experiment and evidence

Source: os-vector/wire-os-victor at 8fc055ac5c7538601a319149fb62275207719140,
compatibility 209; WireOS 3.0.2.35d. The separate 30-second application and original
stock images remain preserved locally. This application restores the four normal
command timeout constants to stock and removes the SDK's generated 1 kHz tone.

The real processed 160-sample/10 ms blocks in MicDataProcessor::ProcessTriggerLoop
enter a mutex-protected bounded queue. Animation's main thread drains the queue
into a new SDKMicData IPC message; the engine forwards sample-derived sequence
numbers and little-endian PCM to the existing gateway AudioFeed endpoint. The
Python SDK can receive normal 1600-sample/100 ms groups without a wake phrase.
No cloud listening job, recording file, listening animation or earcon is created.
Audio uses the robot's existing processing policy; this patch does not implement
separate selectable fast/directional/voice-detect processing algorithms. Direction
metadata is explicitly unknown. Native speaker echo handling is not yet proven.

The queue holds at most 50 blocks / 500 ms (16000 PCM bytes, plus bounded metadata).
Overflow, invalid block size and expired lease fail closed; late heartbeats cannot
revive a failed session. A new session clears old samples and sequence state.
Microphone mute clears the queue. Engine and animation leases expire after three
seconds without renewal; the gateway renews every second only while its stream
loop runs. One concurrent client is allowed. Context cancellation, stalled source,
engine channel closure and a fifteen-minute absolute limit close the gateway
session and send AUDIO_OFF. The engine only accepts the active session's blocks.

Offline verification: host C++ queue tests pass under AddressSanitizer and
UndefinedBehaviorSanitizer, including stale renewal, FIFO, start/stop, overflow and
recovery. Gateway tests pass with Go race detection, checking malformed frames,
missing blocks, cancellation with no samples, repeated release/reacquisition and
exclusive ownership. The upstream macOS gateway platform file is commented out;
a Darwin-only test fixture supplies platform constants only during tests. No
robot auth changes are included. The Mac needed opusfile to compile host tests.
The ARM release cross-build and separate staging both completed successfully.
See CONTINUOUS_MIC_MANIFEST.json and continuous-mic.patch.

Deployment uses only an inactive /anki-continuous-candidate, then a temporary
/anki bind mount. The original stock /anki remains underneath. A five-minute
systemd rollback timer is armed before activation. Reboot removes the mount;
rollback falls back to reboot if normal unmount is busy. No boot/recovery image,
SDK credentials or Pi installation is replaced. The previous30-second candidate
was reused as inactive staging; its complete Mac build artifacts remain intact.

The first activation exposed a deployment issue: stopping the aggregate target
restarted only the gateway, leaving the stock engine and microphone process
running. The diagnostic correctly rejected the repeated 1 kHz tone. No native
continuous success is attributed to that mixed runtime. The activation/rollback
helpers now explicitly stop/start vic-cloud, vic-engine and vic-anim. New process
start times, the engine shared-library mapped inode, and the running microphone
executable hash were checked against the candidate. A corrected five-second
test delivered 48 groups / 4.8 nominal seconds, zero group gaps and no repeated
non-silent frames. The corrected 75-second test then delivered 736 consecutive
groups, zero group gaps, no repeated non-silent frames, and 74.780 seconds between
the first/last source-group timestamps. It contained 73.6 nominal seconds at the
API's declared 16000 Hz. Observed source groups span about 101–102 ms; this clock
relationship needs handling in the eventual Live adapter rather than treating
it as missing groups. Maximum receive interval was 250.2 ms; packets can arrive
in batches even with complete source continuity.

All three subsequent start/stop trials began at source group 0, with no gaps or
repeated non-silent data. A separate child exited after receiving a frame without
running its gRPC cleanup, and a new client subsequently acquired a fresh group 0
session. During the speaker test, nine microphone groups arrived during the
brief tone; the complete four-second test had 38 groups and no gaps. This proves
simultaneous transport, not echo cancellation or reliable conversational barge-in.

An eight-second maximum clip from 40–48 seconds into the long test was retained
only in RAM and replayed once; the actual segment held 7.9 nominal seconds. The
owner recognized accurate ambient room noise. No particular words or speech
recognition accuracy is claimed. No audio files, transcripts or paid API calls
were used. Metrics are in CONTINUOUS_MIC_RESULTS.json.

Rollback's explicit service stop still left /anki busy, so the helper invoked
its reboot fallback. After reboot, all four stock core hashes matched the preserved 35d OTA.
The running microphone executable hash and mapped engine-library inode also
matched stock, SDK status succeeded, root was read-only and /anki had no test
bind mount. Admin reported legacy/inactive/not-ready. The owner confirmed that the ordinary clock command works after restoration. The candidate directory remains inactive
for another controlled test; normal boot does not mount it. OpenAI Live input,
web-admin enablement, long-duration stability and echo handling remain separate
follow-up work. The existing admin stays legacy/live off on stock firmware.

## Next integration work

1. Add a Vector SDK input source to the existing conversation/controller path.
   Current `continuous` input is explicitly wired to HostAudioBridge; it must not
   be relabeled as Vector input. Open and validate fresh native PCM before
   starting a paid session, then feed the bounded Live input buffer without a
   wake phrase. Check source sequence, frame age and timestamp/nominal-rate
   behavior; stop on stalls, source loss, missing groups or repeated test data.
2. Reuse the existing rendered-speaker reference/AEC machinery with SDK input,
   while keeping the mic stream open during output. Test actual speech overlap,
   self-echo and interruption; the tone test established simultaneous transport
   only. Maintain explicit touch/admin/spoken stop and the session duration bound.
3. Expose the new source and fresh-frame state in the admin. Enable it only when
   a compatible native stream is actually available on the running firmware.
   Report starting/listening/speaking/stopping/error truthfully; clear readiness
   immediately when input or controller heartbeat becomes stale. The stock
   runtime currently remains a synthetic SDK source and must stay unavailable.
4. After a longer stability/voice rehearsal, deploy the tested application through
   a documented reversible installation that survives reboot, with the stock
   application/settings backups kept. The current candidate mount is deliberately
   transient and is not part of normal boot. Keep Pi voice off between tests.
