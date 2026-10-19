# Extending Vector's native listening window

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


October 19 implementation is recorded in
[firmware/UNLOCK_AND_BUILD.md](firmware/UNLOCK_AND_BUILD.md), with pinned source
and image hashes in firmware/BUILD_MANIFEST.json. The baseline Mac cross-build
has succeeded and been staged separately. The coordinated 30-second experiment
has also compiled successfully. Vector is unlocked, running WireOS, and the test
runtime has now delivered30.0seconds of authentic native microphone PCM through
our Pi, with clean completion. See firmware/NATIVE_30S_RESULT.json. This proves
the six-second firmware limit can be changed; it does not yet implement a
continuous SDK stream. The production unlock and WireOS base images have been
downloaded and inspected. The research below
describes the assessment before this authorized implementation work began.

## What the repositories contain

The cloned `wire-pod` repository builds the server. Its `vector-cloud` directory
contains gateway/cloud code, but not the C++ engine and microphone implementation
that sets the measured six-second window.

The maintainer's [wire-pod installation guide](https://github.com/kercre123/wire-pod/wiki/Installation)
describes the production setup update as a separate DDL-compiled Escape Pod OTA,
identified by the `ep` firmware suffix. Applying that image is not equivalent to
unlocking the robot for arbitrary custom firmware.

Current community source provides a concrete alternative:

- [wire-os-victor](https://github.com/os-vector/wire-os-victor) builds the on-robot
  `/anki` software, including the engine and microphone code. Its README documents
  standalone builds on M-series macOS and Linux, and deployment over SSH onto a
  suitable WireOS base. This is a documented path, not a build validated here yet.
- [wire-os](https://github.com/os-vector/wire-os) builds the entire OS and final OTA.
  Its README documents a universal production-robot unlock route and requires an
  unlocked bot for its custom base image. Full OTA builds require Linux; the
  documented smaller application build can use this Mac after base installation.

The source/README pages were accessed through the native GitHub connector. Its
wiki fetch was unsupported, so the installation wiki and community docs were read
directly on their published websites. No installer, unlock image, robot partition
or firmware binary was changed during this research.

## First experiment: a bounded 30-second window

The initial experiment should establish longer real native capture before adding
new conversation features. These published-source locations need coordinated work:

1. `lib/micData/micDataTypes.h`: the microphone stream timeout is
   `6000 + kTriggerOverlapSize_ms`. A 30-second experiment would change its base
   duration while keeping the overlap relationship.
2. `engine/aiComponent/behaviorComponent/behaviors/robotDrivenDialog/behaviorPromptUserForVoiceCommand.cpp`:
   its10-second recording limit is statically required to exceed the mic timeout
   by about2 seconds. Raising the mic constant alone would violate that assertion.
3. `engine/aiComponent/behaviorComponent/behaviors/reactions/behaviorReactToVoiceCommand.cpp`:
   its streaming-duration default is10 seconds, with a console-variable range
   capped at20 seconds. Both require review for a30-second experiment; the code
   checks that this duration is at least the microphone duration.
4. Audit the matching gateway/behavior timeouts and memory retention. Extend the
   isolated Pi native diagnostic's20-second bound for this specific experiment,
   alongside its Python receiver's limits. Preserve short speech-end completion
   for ordinary commands.

These were the initially identified change points. The completed patch also
raises the on-robot gateway's nine-second timeout to35seconds; all four changes
are compiled and the first30-second physical transport test has passed.
The exact linked source was examined; the whole firmware and build dependency
graph have not been audited.

## Deployment and validation sequence

1. Establish the exact supported unlock/base-image route for this robot and its
   effect on userdata, authentication and recovery. The current firmware is
   `2.0.1.6076ep`; developer access has not been established. Historical read-only
   checks found no reachable SSH or development web server, which alone does not
   prove unlock status.
2. Preserve the existing Pi backup, pairing and recovery image. Determine what
   robot-resident data can be preserved before proposing the migration. A Pi
   installation backup is not a full robot backup.
3. Pin a WireOS base and compatible application source/toolchain; build a baseline
   and the coordinated30-second experiment. Keep the baseline and checksums for
   rollback. Do not assume a new hard-float application build runs on the current
   older EP base.
4. Present the exact images, deployment steps and recovery/data implications for
   review before unlocking or flashing the robot.
5. Test30 seconds of native speech capture through pauses, speaker overlap,
   cancellation, clock commands after exit, and repeated starts/stops. No OpenAI
   session is needed to establish the input transport.
6. If successful, implement an explicit live-mode-controlled longer stream with
   bounded buffers and cleanup. Merely increasing a global timeout does not prove
   an indefinitely continuous mode. A real SDK microphone feed is another possible
   firmware design, but its audio plumbing is not implemented by the placeholder
   feed examined so far.

## Existing-firmware comparison

See [NATIVE_MIC_RESULTS.md](NATIVE_MIC_RESULTS.md) for measured rearming trials.
The promising sequence is capture completion, SDK behavior-control take/release,
then a short grace interval before the next native listening request. Waiting
alone did not reproduce that state transition. Its observed capture gaps still
include roughly two seconds of robot-side startup, making it a workaround with
missing input rather than uninterrupted speech.
