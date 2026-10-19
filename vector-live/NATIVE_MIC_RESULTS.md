# Native microphone trials — October 19, 2026

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


The owner clarified that **Vector's internal microphone is the requirement**.
Host input is a fallback and does not fulfill that requirement. These trials use
only the internal microphone and the existing Pi. No OpenAI session or audio
file was opened. One explicitly announced trial replayed bounded temporary RAM.

## Software-opened native capture

The first harness attempt failed before sending any command because the older
Python SDK lacks AppIntent. The harness now uses wire-pod's existing
`POST /api-sdk/cloud_intent` with `intent=knowledge_question`, which already calls
the robot's AppIntent RPC. Pairing credentials are neither copied nor printed
by this harness.

- Ordinary adapter:11 PCM chunks,1.32 seconds, varying audio, RMS−45.4 dBFS,
  peak−30.1 dBFS. Trigger to first request3.427 seconds. The owner spoke both
  groups separated by a pause, but only this short capture arrived. Filtered
  server diagnostics reported end-of-speech detection. No spoken reply expected.
- Temporary diagnostic bypass:50 chunks,6.000 audio seconds across5.947 wall
  seconds. RMS−36.6 dBFS, peak−16.3 dBFS, longest arrival interval171.6 ms.
  Trigger to first request2.748 seconds. The owner reported a falling-dot
  animation after “one two three” and was unsure later words arrived. Level-only
  measurements do not establish which words were captured.

The isolated adapter accepts diagnostic ACK2 **only** with
`VECTOR_LIVE_NATIVE_PROBE=1`; its normal ACK1 path retains existing end-of-speech
behavior. Diagnostic ACK2 bypasses server VAD, with the existing20-second cap.
The native request ended at6 seconds, substantially before that server cap.
The new native Go regression check passes, alongside the existing checks.

## Capture while the speaker plays; direct replay

Another held native request yielded50 chunks and6.000 audio seconds across6.006
wall seconds. Trigger to first request2.132 seconds. A quiet0.7-second tone was
sent under SDK behavior control, beginning about2 seconds into capture.

The speaker acknowledged completion; its playback RPC lasted1.003 seconds,
during which8 native PCM chunks arrived. The six-second stream survived the
speaker-control acquisition and playback. This proves delivery continued through
the RPC, not sample-accurate acoustic alignment or echo cancellation quality.

The captured six seconds were replayed through Vector at volume80, then discarded
from memory. The owner heard the count **through seven**. This establishes genuine
speech through the native microphone path; it does not establish capture of every
word spoken during the tone or beyond the six-second window. No transcription or
permanent audio recording was used.

## Source comparison

Direct native GitHub access found an explicit constant in
[micDataTypes.h](https://github.com/os-vector/wire-os-victor/blob/8fc055ac5c7538601a319149fb62275207719140/lib/micData/micDataTypes.h):
`kStreamingTimeout_ms = 6000 + kTriggerOverlapSize_ms`, with50 ms overlap.
The mic data system ends its stream when that chunk limit is reached.
This matches the observed roughly six-second window. It remains a comparison
with published source, not disassembly of the installed2.0.1.6076ep binary.

The earlier SDK AudioFeed test-tone finding concerns a **different** input path.
Real internal-mic speech is now verified without a wake phrase via AppIntent.

## Automatic rearming

The harness attempted three windows with350 ms between completion and the next
software trigger. Trial1 delivered50 chunks and6.000 seconds across6.040 wall
seconds; trigger-to-first-request latency was2.158 seconds. Trial2's command
returned but produced **no next capture within the20-second timeout**. The
harness stopped there; trial3 was not sent.

This immediate rearm pattern is not reliable. The cause is not yet established:
the robot may still be transitioning out of its previous behavior, or another
state/response detail may be required. Do not claim the timeout proves that all
rearming methods fail or assign it a measured gap duration. Receiver timestamps
also do not expose source sample timestamps or compensate for buffering.

## Cleanup and next work

The temporary `91-vector-native-probe.conf` override was removed, and the active
binary restored from `chipper-livevoice-before-native-probe`. The diagnostic build
is retained as `chipper-livevoice-native-probe-tested`; source remains local and
in the isolated Pi build. Paid voice is inactive, the probe socket is absent,
and wire-pod reports healthy legacy/off. The owner subsequently confirmed the ordinary clock command works normally.

The internal microphone remains the goal. We need to investigate whether a more
direct native input interface exists or whether the on-robot six-second stream
limit can be changed, along with supported deployment/recovery for this exact
robot. No firmware was flashed. The measured short window is not a completed
continuous conversation implementation, and the host-mic fallback is not a
substitute for the clarified requirement.

## Existing conversation mode

Read the actual installed Pi `kgsim_cmds.go` on October19. Its model prompt
requests `newVoiceRequest` when asking a follow-up in conversation mode. That
action calls `DoNewRequest`, waits one third of a second and sends AppIntent
`knowledge_question`. It opens another finite listening request after the
response/action flow; it does not extend the original microphone stream.
The diagnostic immediate empty-completion rearm was a different timing/state
sequence, so its failure does not prove the installed after-reply rearming fails.
The reason for the diagnostic rearm failure is not yet established.

## Reopening-delay follow-up

The owner asked whether firmware could be rebuilt, and otherwise what reopening
gap is required. [FIRMWARE_PLAN.md](FIRMWARE_PLAN.md) records the newly verified
separate WireOS build/deployment route; no unlock or firmware installation was
performed. The existing firmware was also benchmarked as follows:

| Sequence after capture | Planned windows | Completed before failure | Observed request gaps |
|---|---:|---:|---|
| Wait350 ms only |3|1|Next capture timed out |
| Wait2 seconds only |3|1|Next capture timed out within12 seconds |
| SDK control take/release, then350 ms wait |3|3|2.644,2.648 seconds |
| SDK control take/release, no added wait |5|2|2.384 seconds; third capture timed out |
| SDK control take/release, then350 ms wait, repeatability run |10|10|2.643,2.675,2.606,2.627,2.601,2.632,2.634,2.669,2.615 seconds |

Each completed window delivered50 chunks and6.000 seconds of native PCM. The
ten-window run had nine successful reopens, with gaps2.601–2.675 seconds and a
mean2.634 seconds. This is a short hardware repeatability test, not a guarantee
across all robot/network states or a proof that350 ms is the absolute minimum.

The handoff takes SDK behavior control, holds it for100 ms, and releases it,
without issuing movement or speech commands. Actual handoffs typically cost
about140–190 ms. This mirrors the control transition in the installed conversation
loop, which uses SDK control while speaking before starting a newVoiceRequest.
The result supports a state-transition explanation for earlier failed immediate
reopens; the precise engine state responsible has not been instrumented.

Timed trigger HTTP requests in successful later windows generally took16–63 ms;
the first request of the long run took111 ms. From issuing the trigger to receipt
of the next microphone request remained about2.1 seconds. Most of the gap is
therefore downstream of the Pi trigger request. No source sample timestamps are
available, so these measurements describe request/PCM delivery gaps rather than
sample-accurate microphone enable/disable times.

The zero-added-wait run also had a1.262-second maximum delivery interval in its
second window, despite receiving the full6 seconds across about6 wall seconds.
That buffering/jitter result is another reason not to treat that faster run as
a reliable live-input configuration.

At the end of the follow-up, the temporary probe override and diagnostic active
binary were again removed in favor of the pre-test server. Test code and the
diagnostic binary remain preserved; the paid voice service stays off.

## Unlocked WireOS firmware experiment — October19 afternoon

Vector is now developer-unlocked and running WireOS3.0.2.35d. After installing
the Pi server-config override and public certificate under /data/data, a stock
native capture delivered50chunks/6.0seconds again. The stock SDK AudioFeed still
returned a repeating synthetic signal, so it remains unsuitable for real input.

The independently compiled application test changes the mic timeout to30seconds,
both relevant behavior limits to35seconds, and the gateway's9-second request
timeout to35seconds. It ran through a temporary bind mount over /anki, preserving
the stock runtime underneath. Three hardware captures each delivered250chunks
and30.0seconds of varying native PCM, with clean EOF and no repeated test signal.
The first had30.466seconds wall duration, RMS-39.4dBFS and peak-8.0dBFS.

Two consecutive windows also passed, with a3.212-second observed rearm gap using
SDK control take/release plus350ms grace. This proves that firmware can extend
the real microphone window. It does not prove a gapless continuous conversation,
recognition of every word, or long-session memory and echo-cancellation behavior.
No paid API or audio files were used. Metrics and pinned source/image hashes are
in [firmware/NATIVE_30S_RESULT.json](firmware/NATIVE_30S_RESULT.json),
[firmware/NATIVE_30S_REPEATABILITY.json](firmware/NATIVE_30S_REPEATABILITY.json)
and [firmware/BUILD_MANIFEST.json](firmware/BUILD_MANIFEST.json).

Stock35d runtime hashes and SDK access were verified after final rollback/reboot.
The Pi pre-test binary was restored by matching checksum; the diagnostic override
and socket are gone. Admin reports legacy mode, live voice inactive. The owner
confirmed the ordinary clock command works after restoration. Pi routing remains installed so stock
WireOS uses wire-pod. The full migration/backup/recovery record is in
[firmware/UNLOCK_AND_BUILD.md](firmware/UNLOCK_AND_BUILD.md).
