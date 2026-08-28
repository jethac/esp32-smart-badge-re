# E87 Stock-to-Custom Android Transition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing native E87 controller with a capture-proven, offline FD00/Qix sender for the one-time transition from stock firmware to the reviewed custom image.

**Architecture:** Keep normal semantic sync unchanged. Add a separate `transition` package whose pure codecs and transfer machine are driven by a narrow Android GATT adapter. The sole canonical firmware input is a reviewed release embedded at APK build time; the APK revalidates its packaged bytes before exposing an immutable transition artifact. The UI still requires an explicit human confirmation that the badge is in its stock receive screen. The future custom-firmware rewrite path remains visibly unavailable until its AE00/RCSP loader behavior is proven.

**Tech Stack:** Java 8 bytecode, Android framework BLE APIs, Gradle/APK assets, JUnit 4.13.2, AGP 8.5.2, Gradle 8.7, compile/target SDK 34, minimum SDK 31.

**Spec:** `docs/superpowers/specs/2026-08-27-e87-local-rendering-trial-design.md`

## Global Constraints

- Work only in `/home/jethac/.local/share/e87-dev/worktrees/e87-android-transition` on branch `codex/e87-android-transition`, whose base is `f7eb885117df2f86aaf895b8317f0301e29d15d4`.
- The existing normal path remains byte-for-byte and dependency-boundary compatible: it writes only `e87d0002-7a1b-4c62-9f0b-5d9c01a70735` and never imports `transition` or maintenance transport code.
- The first-install transport is the observed stock service `c2e6fd00-e966-1000-8000-bef9c223df6a`; FD01 notifies, FD02 is write-with-response, and FD03 notifies/indicates.
- Subscribe FD01 and then FD03 with exact CCCD bytes `02 00`; request MTU 512 only after both subscriptions complete. The accepted trace negotiated MTU 256.
- Qix frames are `9E | checksum | flags | opcode | payloadLengthLE16 | payload`; checksum is the low byte of the sum of bytes from `flags` through the end of payload. Reject wrong magic, length, checksum, channel, or opcode.
- C0 sends the exact 27-byte outer Qix header. C1 payload is `state:u8 | allowedLength:u32le | resumeOffset:u32le`; require state 1, allowed length `1..1,048,576`, and resume offset within and aligned to the artifact unless it equals the final length.
- C2 payload is `chunkLength:u32le | absoluteOffset:u32le | chunk`; flags are `0x01 | (serial << 3) | (logicalFrameLength > 20 ? 0x04 : 0)`. Serial starts at 1 and wraps modulo 16.
- Permit only one logical C2 and one Android characteristic write callback in flight. Fragment outgoing logical frames into `max(20, negotiatedMtu - 6)`-byte writes using `WRITE_TYPE_DEFAULT`.
- C3 payload is `result:u8 | nextOffset:u32le`; require result zero and the exact expected monotonic next offset. On the final C2, accept either final C3 followed by C5 or direct C5. C5 payload is exactly one zero result byte.
- Use the retained accepted capture only as protocol evidence, never as a flash candidate. Evidence root: `/home/jethac/.local/share/e87-dev/reference/qix-stock-accepted`; the captured `11.1.0.2` package produced the wrong Q87 resource variant and is never embedded.
- The Stage0-H binding release source must contain exactly six delivered files and no extras: `app.bin`, `jl_isd.fw`, `update.ufw`, one `E87-<semver>-<build-id>.qix`, `manifest.json`, and `SHA256SUMS`. `jl_isd.fw` is recovery/burner evidence; do not rename it to `loader.bin`. The Qix file alone is sent by the stock transition transport. `update.ufw` is reserved for the future custom rewrite path.
- The build task accepts only `-Pe87FirmwareRelease=<absolute reviewed release dir>` and embeds the verified release under a profile/semver/build-id asset path. The APK retains no filesystem-selection path for firmware.
- Because ordinary-vs-receive advertisement evidence is absent, the UI must say that receive mode is human-confirmed and require a fresh explicit checkbox/confirmation immediately before Connect. It must not claim automatic physical-gate verification.
- No `BluetoothOTAManager` or JieLi AAR is used by `transition`. The AAR stays quarantined for the later custom AE00/RCSP rewrite path.
- The app keeps its existing permission boundary: no Internet, location, storage, or cleartext capability.
- Run with `JAVA_HOME=/home/jethac/.local/share/e87-dev/jdk-17/usr/lib/jvm/java-17-openjdk-amd64` and `ANDROID_SDK_ROOT=/home/jethac/.local/share/e87-dev/android-sdk`.
- Follow RED-GREEN-REFACTOR. Every task ends in a commit and an independent task review before the next task begins.

---

### Task 1: Implement the capture-pinned Qix wire layer

**Files:**
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/transition/StockQixUuids.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/transition/QixFrame.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/transition/QixFrameCodec.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/transition/QixFrameAssembler.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/transition/StockQixBindCodec.java`
- Test: matching `*Test.java` files under `android-controller/app/src/test/java/net/jethachan/factory_badges/transition/`

**Interfaces:**
- Consumes: byte fragments from FD01 or FD03 and immutable byte arrays to encode.
- Produces: immutable `QixFrame(int flags, int opcode, byte[] payload)`, bounded per-channel reassembly, and strict bind response data.

```java
public final class QixFrame {
    public int flags();
    public int opcode();
    public byte[] payload();
}
public final class QixFrameCodec {
    public static byte[] encode(int flags, int opcode, byte[] payload);
    public static QixFrame decode(byte[] encoded);
}
public final class QixFrameAssembler {
    public List<QixFrame> accept(byte[] fragment);
    public void reset();
}
public final class StockQixBindCodec {
    public static byte[] request(int settings, int hostId);
    public static BindResponse parseResponse(QixFrame frame);
    public static byte[] successAck(int receivedOpcode, int serial);
}
```

- [x] **Step 1: Write capture-vector tests before production classes**

Load literal fixtures from the evidence root in test setup and pin their SHA-256 values: bind request `8C79A1003503843C2AAFE16C5EBA22DD83D00139C00DDE5B48AACB1E7F44B608`, reassembled bind response `4762B7EABBFDF4293BA1A362C1D3DB84F85849DDF140660BAF91C54F0D78DC26`, C0 `FEF8138346C609E7982842DE3CE5CB351704CD46475166962DD21BB96D03FC8E`, first C2 `FD24BEE44DB57B0C90FE62622709570BF836610EF403AE9666DAD32F72804EF3`, and last C2 `6F57560661B6C0FE94B15A9DD96CBCAE8D3CFCE86443F36E9C4E2C775B3C58BF`. Copy only the small bind-response/C0/C2 fixtures into `app/src/test/resources/transition/`; do not copy the wrong-product firmware payload.

- [x] **Step 2: Run the focused tests and record intended RED**

```sh
cd android-controller
JAVA_HOME=/home/jethac/.local/share/e87-dev/jdk-17/usr/lib/jvm/java-17-openjdk-amd64 \
ANDROID_SDK_ROOT=/home/jethac/.local/share/e87-dev/android-sdk \
bash ./gradlew testDebugUnitTest --tests 'net.jethachan.factory_badges.transition.*' --console=plain
```

Recorded result: compile failure only because the five production types were absent.

- [x] **Step 3: Implement strict immutable codecs**

`QixFrameCodec.encode(int flags, int opcode, byte[] payload)` rejects values outside `0..255` and payloads over 65535 bytes. `decode(byte[])` requires exact length `6 + payloadLength`, verifies magic and checksum, and returns defensive copies. `QixFrameAssembler.accept(byte[])` buffers no more than 65,541 bytes, emits every complete frame in input order, retains only a bounded incomplete suffix, supports fragmented and concatenated input, and has a deterministic `reset()`.

- [x] **Step 4: Add negative and fragmentation tests**

Cover truncation at every header length, declared length shorter/longer than bytes, checksum mutation, oversized assembly, empty fragments, two concatenated frames, split at every byte boundary, FD01 bind fragmentation, and state reset after an error. `StockQixBindCodec.request(settings, hostId)` reproduces the 13-byte payload used by the proven probe: settings byte followed by the low six little-endian bytes of the signed host ID twice. `parseResponse` accepts only opcode `0x61`, result zero, a complete bounded ASCII firmware version, and a valid frame; when flag bit `0x02` requests a reply, `successAck(0x61, serial)` emits opcode `0xFF` with payload `61 00`. Pin the accepted request for settings `0x06` and captured Redmi-derived host ID `-1168149652`, but do not hard-code that host ID in production.

- [x] **Step 5: Run focused and full gates**

Focused transition tests passed (18 tests). `testDebugUnitTest lintDebug` passed 356 tests total (338 baseline plus 18 new) with zero lint issues.

- [x] **Step 6: Commit**

Committed as `da63a0d22af6e57448aafa50c08db7102f4dfbfb` with message `feat(android): add capture-pinned stock Qix codec`.

Independent review: approved with no findings. This records the reported verification evidence and review outcome; it does not claim a separate independent test rerun.

### Task 2: Implement the acknowledged stock transfer machine

**Files:**
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/transition/TransitionArtifact.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/transition/StockQixTransferMachine.java`
- Test: `android-controller/app/src/test/java/net/jethachan/factory_badges/transition/StockQixTransferMachineTest.java`

**Interfaces:**
- Consumes: a synthetic immutable artifact containing exactly 27 header bytes and UFW payload bytes, plus decoded FD01/FD03 frames. A real packaged release is not required for this task.
- Produces: one explicit action at a time: `SendFd02`, `AwaitFd01`, `AwaitFd03`, `Progress`, `Complete`, or `Failed`.

```java
public final class TransitionArtifact {
    public TransitionArtifact(byte[] qixHeader, byte[] ufwPayload,
                              byte[] qixSha256, byte[] expectedBuildId);
    public byte[] qixHeader();
    public byte[] ufwPayload();
}
public final class StockQixTransferMachine {
    public Action start(int settings, int hostId);
    public Action onFd01(QixFrame frame);
    public Action onFd03(QixFrame frame);
    public Action onFd02WriteAcknowledged();
    public Snapshot snapshot();
}
```

- [ ] **Step 1: Write the transcript-driven state tests**

Prove `bind -> bind response -> optional opcode-FF success ACK -> C0 -> C1 -> one C2 -> matching C3 -> next C2`, serial wrap across the bind ACK and C2 stream, a resumed aligned C1 offset, final-C3-then-C5, and direct-final-C5. The accepted trace is 1,080,360 UFW bytes, allowed length 1024, 1,056 C2 blocks, 1,055 C3 responses, and final `9EC701C5010000`.

- [ ] **Step 2: Record RED and implement the smallest deterministic reducer**

The machine owns phase, negotiated chunk length, next offset, expected acknowledgement, and serial. It never calls Android APIs, reads files, or performs writes itself. Each input method returns one immutable action; a second event while an acknowledgement is pending fails closed.

- [ ] **Step 3: Add exhaustive rejection tests**

Reject duplicate C1, state other than 1, zero/oversized allowed length, unaligned or out-of-range resume, C3 before C2, nonzero C3/C5, nonmonotonic C3, premature C5, unexpected channel/opcode, payload length mismatch, a second C2 request while pending, and any event after terminal success/failure.

- [ ] **Step 4: Run focused/full gates and commit**

```sh
git add android-controller/app/src/main/java/net/jethachan/factory_badges/transition \
        android-controller/app/src/test/java/net/jethachan/factory_badges/transition
git commit -m 'feat(android): pace acknowledged stock Qix transfer'
```

### Task 3: Add the isolated Android FD00 transport and controller

**Files:**
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/transition/StockGattDriver.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/transition/StockQixGattTransport.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/transition/StockTransitionController.java`
- Test: matching tests under `android-controller/app/src/test/java/net/jethachan/factory_badges/transition/`

**Interfaces:**
- Consumes: Android GATT callbacks through generation/token-tagged adapter methods and actions from Task 2.
- Produces: normalized connection, subscription, MTU, write, receive, progress, failure, and completion callbacks.

- [ ] **Step 1: Write fake-driver ordering tests**

Pin service/characteristic discovery, FD01 CCCD then FD03 CCCD with `02 00`, MTU 512 after both descriptors acknowledge, FD02 `WRITE_TYPE_DEFAULT`, `max(20, mtu-6)` fragmentation, exactly one write callback outstanding, per-channel assemblers, stale GATT generation rejection, disconnect failure, timeout failure, and direct-final-C5.

- [ ] **Step 2: Record RED and implement the fakeable driver/controller boundary**

Only `StockQixGattTransport` imports `android.bluetooth.*`. `StockTransitionController` composes the pure machine, validates callback tokens/generations, sequences fragments, and exposes immutable UI snapshots. It must not import `ble.normal`, `sync`, or `BluetoothOTAManager`.

- [ ] **Step 3: Add lifecycle and cancellation tests**

Cancellation is allowed until C0 is acknowledged by a valid C1. After C1, expose `mayCancel=false`; a disconnect becomes `FAILED_RECONNECT_REQUIRED`, preserving artifact identity and acknowledged offset in the snapshot. Never report transfer-complete as installed-custom-firmware success.

- [ ] **Step 4: Run focused/full gates and commit**

```sh
git add android-controller/app/src/main/java/net/jethachan/factory_badges/transition \
        android-controller/app/src/test/java/net/jethachan/factory_badges/transition
git commit -m 'feat(android): drive stock FD00 transition transport'
```

### Task 4: Embed, validate, and expose the reviewed transition release

**Execution prerequisite:** Do not start Task 4 until a reviewed real S0-2 release exists and the authoritative firmware validators and manifest schema have been integrated and reviewed. Tasks 2 and 3 may use synthetic immutable `TransitionArtifact` values; no captured wrong-product package is embedded at any stage.

**Files:**
- Modify: `android-controller/build.gradle.kts` and `android-controller/app/build.gradle.kts` build logic for firmware embedding.
- Create: generated `android-controller/app/build/generated/e87Firmware/assets/e87/default-release.json` and generated profile/semver/build-id asset content during the build; generated assets must not be hand-authored.
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/transition/TransitionManifest.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/transition/TransitionArtifactValidator.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/transition/EmbeddedFirmwareRepository.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/ui/MaintenanceActivity.java`
- Create: `android-controller/app/src/main/res/layout/activity_maintenance.xml`
- Modify: `android-controller/app/src/main/AndroidManifest.xml`
- Modify: `android-controller/app/src/main/java/net/jethachan/factory_badges/ui/MainActivity.java`
- Modify: `android-controller/app/src/main/res/values/strings.xml`
- Create: `android-controller/app/src/test/java/net/jethachan/factory_badges/architecture/ProtocolBoundaryTest.java`
- Create: transition validator/repository/UI tests under `android-controller/app/src/test/java/net/jethachan/factory_badges/`
- Create: `android-controller/scripts/verify-apk.py`

**Interfaces:**
- Consumes: a Gradle-embedded, reviewed release packaged as APK assets.
- Produces: an `EmbeddedFirmwareRepository` that reopens, caps, hash-checks, and reparses every packaged release byte before returning an immutable validated `TransitionArtifact`; explicit human receive-mode confirmation; transfer progress; and post-reboot custom-service/build-info verification.

- [ ] **Step 1: Write strict embedded-release tests**

Define `assets/e87/default-release.json` as a closed object with exactly `schemaId`, `schemaVersion`, `profile`, `semver`, `buildId`, `releaseRoot`, and `files`. Require `schemaId` `e87.embedded-release`, `schemaVersion` `1`, a valid profile and semver, a 32-hex-character `buildId`, and a relative `releaseRoot`. Require exactly six `files` records; each closed record has only `role`, `filename`, `length`, and `sha256`. The six unique roles are `appBin`, `jlIsdFw`, `updateUfw`, `qix`, `manifest`, and `sha256Sums`; each filename is a bare relative filename, each length is nonnegative, and each SHA-256 is canonical 64-hex. The Qix record is the sole `E87-<semver>-<build-id>.qix` record.

The APK inventory is closed: exactly one `assets/e87/default-release.json`, exactly one indexed release root, and exactly the six indexed files beneath it. Reject unknown keys; duplicate, missing, or extra records; extra index files, roots, assets, releases, or Qix files; absolute, traversal, empty-segment, or backslash paths; and identity, path, manifest, or hash mismatches. Require manifest schema 1, chip `AC707N`, profile `E87-1542-STAGE0-H` or the final reviewed successor profile, `singleBank:true`, exact Qix size/SHA-256, outer version/header/CRC, exact UFW length, expected output build ID, and `releaseEligible:false`. Cap manifest at 256 KiB and Qix at 32 MiB. Test that there is no scanner before validation or repository enumeration before full byte-level validation. Both `EmbeddedFirmwareRepository` and `verify-apk.py` enforce this exact APK asset inventory, including no unreferenced extras.

- [ ] **Step 2: Implement Gradle embedding and bounded in-APK validation**

Implement `embedE87Firmware`, requiring `-Pe87FirmwareRelease=<absolute reviewed release dir>`, declaring that release directory as its input, and using `android-controller/app/build/generated/e87Firmware/assets` as a clean output directory. The task must delete/clean its output before generation, verify the exact six delivered files with integrated reviewed validators, write `assets/e87/default-release.json`, and embed the exact six files under `assets/e87/<profile>/<semver>/<build-id>/`. Wire that generated output through the AGP variant/source-set API as a main/debug assets source. Every relevant merge-assets, package, and assemble task must depend on `embedE87Firmware`; stale, omitted, or unwired assets fail the build rather than falling back to a prior output.

The validation authority and fail-closed order are identical at build time and runtime: (1) closed index structure; (2) exact APK/release inventory; (3) canonical `SHA256SUMS` parsing and index receipt agreement; (4) manifest schema and cross-links; (5) Qix outer structure/CRC and Qix payload equality to `update.ufw`; (6) UFW policy; (7) JLFw proof that `jl_isd.fw` embeds `app.bin`; (8) `app.bin` hash and size from manifest/receipts. The Gradle task calls the integrated reviewed authoritative validators. Runtime Java ports the equivalent checks and fails closed; it does not trust generated metadata alone. `EmbeddedFirmwareRepository` reopens every asset, applies caps, hash-checks it, reparses it in that order, and returns only an immutable validated artifact. The stock sender receives only the embedded Qix; `jl_isd.fw` remains recovery/burner evidence and standalone `update.ufw` remains unavailable to the stock sender.

Before this task is a release gate, verify Gradle 8.7's wrapper distribution SHA-256 is `544c35d6bd849ae8a5ed0bcea39ba677dc40f49df7d1835561582da2009b961d`; require committed strict dependency-verification metadata, committed dependency locks with `lockAllConfigurations()`, and fixed dependencies. Ban dynamic, changing, and snapshot dependencies, `mavenLocal`, and subproject repositories. A reviewed, non-release provisioning workflow may update locks; release gates never write locks and only verify the committed metadata and locks.

- [ ] **Step 3: Write UI and protocol-boundary RED tests, then implement UI**

Protocol-boundary tests prove no storage permission, no firmware-selection UI, no `BluetoothOTAManager` reference from transition classes, and no unvalidated asset reaches the sender. The maintenance screen shows embedded release identity and validation state, a mandatory unchecked `I put the badge in its stock receiving screen` confirmation, Connect, phase/progress, and plain-language errors. A separate `Rewrite custom firmware` section is present but disabled with `Not available until custom RCSP recovery is hardware-proven`. MainActivity may launch MaintenanceActivity only by explicit Intent class name and must not import transition types.

- [ ] **Step 4: Verify post-reboot success semantics**

After C5, show `Waiting for custom firmware`; scan only the normal `e87d0001-...` service, connect through the existing normal client, and require the embedded release's exact profile/build ID. A timeout, wrong profile, or wrong build ID is a failed transition even if C5 was zero.

- [ ] **Step 5: Add and run APK/source-release audit and offline reproducibility procedure**

`verify-apk.py` compares every embedded release byte in the APK exactly against the reviewed source release, enforces the closed index/inventory above, and asserts application ID, min/target SDK, exactly the five existing permissions, no cleartext/network/location/storage permission, no Flutter assets/classes, and no `BluetoothOTAManager` reference from transition classes.

For the final release gate, create two distinct clean copied source, build, and output roots. Give both roots the same reviewed release directory, pinned SDK, pinned JDK, and approved dependency caches; do not share either root's project/build/output state and make no network access available. In each root run:

```sh
JAVA_HOME=/home/jethac/.local/share/e87-dev/jdk-17/usr/lib/jvm/java-17-openjdk-amd64 \
ANDROID_SDK_ROOT=/home/jethac/.local/share/e87-dev/android-sdk \
bash ./gradlew -Pe87FirmwareRelease=<absolute reviewed release dir> \
  clean embedE87Firmware testDebugUnitTest lintDebug assembleDebug \
  --offline --dependency-verification=strict
```

Audit each resulting APK against the original reviewed release, record both APK SHA-256 values, and require exact embedded inventory/content and validation-policy equality in both audit records. The gate does not claim full APK byte identity unless a separate reproducibility contract requires it; the required evidence is the audited embedded content, validator/policy results, and both recorded APK hashes.

- [ ] **Step 6: Commit**

```sh
git add android-controller
git commit -m 'feat(android): embed validated stock transition release'
```

## Completion Gate

After Task 4's reviewed-release prerequisite is met, complete the two-root pinned/offline procedure above. Both builds must pass JVM tests, lint, assembly, exact embedded-release inventory/content audit, and validation-policy audit against the reviewed source release. Copy only an audited APK to Windows and then to the Redmi. Installation may proceed only after the user approves MIUI's install prompt. No transfer begins until the custom artifact review is complete and the human receive-mode confirmation is freshly checked.
