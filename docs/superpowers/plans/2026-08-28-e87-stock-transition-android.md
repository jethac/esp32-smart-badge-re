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
- C0 sends the exact flags-`0x05`, opcode-`0xC0`, 27-byte header frame. C1 payload is `state:u8 | allowedLength:u32le | resumeOffset:u32le`; parse both u32 values as unsigned `long`, require state 1, allowed length `1..65,527` (the 65,535-byte Qix payload maximum less 8 C2 metadata bytes), and require offset `0..payloadLength` with `offset % window == 0` unless it is exactly final. Resume alignment is a compatibility policy, not a capture-proven fact.
- C2 payload is `chunkLength:u32le | absoluteOffset:u32le | chunk`, where checked arithmetic chooses `min(window, remaining)`. Its flags are exactly `0x01 | (serial << 3) | ((14 + chunkLength) > 20 ? 0x04 : 0)`. The bind stream has an independent retained-probe `nextSerial=1`; an optional, uncaptured bind ACK uses bind-stream serial 1. C2 has a separate serial beginning at 1 and wrapping 15 to 0. Never share or infer either serial from response flags; the captured bind response flags are `0x04` and request no ACK.
- Permit only one logical C2 and one Android characteristic write callback in flight. Fragment outgoing logical frames into `max(20, negotiatedMtu - 6)`-byte writes using `WRITE_TYPE_DEFAULT`; the reducer receives exactly one `onFd02WriteAcknowledged()` only after all fragments of that logical frame have acknowledged, never once per fragment. Notification before that logical acknowledgement or a duplicate logical acknowledgement fails closed.
- C3 payload is exactly `result:u8 | nextOffset:u32le` (five bytes): require result zero and the exact expected monotonic next offset. A valid nonfinal C3 atomically advances the immutable snapshot and immediately emits the next C2 `SendFd02`; there is no standalone `Progress` action. On a fully write-acknowledged final C2, accept either final C3 followed by C5 or direct C5; a full-resume C1 waits C5. C5 payload is exactly one zero result byte. FD01 accepts only bind response traffic; FD03 accepts only C1/C3/C5 traffic, with every channel/opcode mismatch rejected.
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
- Consumes: a synthetic immutable artifact containing exactly 27 header bytes and UFW payload bytes, decoded FD01/FD03 frames, logical FD02 acknowledgements, and explicit protocol- and transport-failure inputs. A real packaged release is not required for this task.
- Produces: one explicit action at a time: `SendFd02`, `AwaitFd01`, `AwaitFd03`, `Complete`, or `Failed`. Progress is represented atomically in immutable snapshots, never as a standalone action.
- `StockQixTransferMachine` is constructed with its immutable `TransitionArtifact`, owns that artifact for its lifetime, and is single-use/nonrestartable. Its constructor rejects null immediately. A `start` invocation outside `NEW` returns and sticks `Failed(INVALID_STATE)`; a new transfer requires a new machine.

```java
public final class TransitionArtifact {
    public TransitionArtifact(byte[] qixHeader, byte[] ufwPayload,
                              byte[] qixSha256, byte[] expectedBuildId);
    public byte[] qixHeader();
    public byte[] ufwPayload();
    public byte[] qixSha256();
    public byte[] expectedBuildId();
}
public final class StockQixTransferMachine {
    public StockQixTransferMachine(TransitionArtifact artifact);

    public enum Phase {
        NEW, WRITE_BIND, WAIT_BIND, WRITE_BIND_ACK, WRITE_C0, WAIT_C1,
        WRITE_C2, WAIT_C3, WAIT_FINAL, WAIT_C5, COMPLETE, FAILED
    }
    public enum FailureCode {
        NONE, INVALID_STATE, WRONG_CHANNEL, WRONG_OPCODE, MALFORMED_PAYLOAD,
        PROTOCOL_REJECTED, OFFSET_MISMATCH, TRANSPORT_SETUP_FAILED,
        TRANSPORT_WRITE_FAILED,
        TRANSPORT_DISCONNECTED, TRANSPORT_TIMEOUT, CANCELLED,
        FAILED_RECONNECT_REQUIRED
    }
    public abstract static class Action {
        public enum Kind { SEND_FD02, AWAIT_FD01, AWAIT_FD03, COMPLETE, FAILED }
        public abstract Kind kind();
    }
    public static final class SendFd02 extends Action {
        public byte[] frame();
        public int opcode();
    }
    public static final class AwaitFd01 extends Action {
        public int expectedOpcode();
    }
    public static final class AwaitFd03 extends Action {
        public int[] expectedOpcodes();
    }
    public static final class Complete extends Action {
    }
    public static final class Failed extends Action {
        public FailureCode failureCode();
    }
    public static final class Snapshot {
        public Phase phase();
        public long totalBytes();
        public long acknowledgedOffset();
        public long pendingOffset();
        public int pendingLength();
        public boolean mayCancel();
        public boolean terminal();
        public FailureCode failureCode();
        public byte[] qixSha256();
        public byte[] expectedBuildId();
    }

    public Action start(int settings, int hostId);
    public Action onFd01(QixFrame frame);
    public Action onFd03(QixFrame frame);
    public Action onFd02WriteAcknowledged();
    public Action onProtocolFailed(FailureCode failureCode);
    public Action onTransportFailed(FailureCode failureCode);
    public Snapshot snapshot();
}
```

The nested API above is the complete Java 8 action/state surface; no extra Task 2 production file is needed. `Action.Kind` is closed, every action subtype's `kind()` agrees with its subtype, and all action objects and array-valued accessors are immutable/defensive. `SendFd02` exposes a non-null, defensively copied complete frame and a non-sentinel opcode. `AwaitFd01.expectedOpcode()` is exactly `0x61`. `AwaitFd03.expectedOpcodes()` is a defensively copied, canonical sorted unique array: `[0xC1]` in `WAIT_C1`, `[0xC3]` in `WAIT_C3`, `[0xC3, 0xC5]` in `WAIT_FINAL`, and `[0xC5]` in `WAIT_C5`. `Complete` has no mutable payload; `Failed.failureCode()` is non-null and never `NONE`. No action exposes a nullable or sentinel frame/opcode API.

Internal reducer failures select the exact protocol `FailureCode` (`INVALID_STATE`, `WRONG_CHANNEL`, `WRONG_OPCODE`, `MALFORMED_PAYLOAD`, `PROTOCOL_REJECTED`, or `OFFSET_MISMATCH`). The two externally callable failure ingress methods have closed, disjoint domains. In every nonterminal phase, `onProtocolFailed` accepts only `INVALID_STATE`, `WRONG_CHANNEL`, `WRONG_OPCODE`, `MALFORMED_PAYLOAD`, `PROTOCOL_REJECTED`, and `OFFSET_MISMATCH`. In every nonterminal phase, `onTransportFailed` accepts only `TRANSPORT_SETUP_FAILED`, `TRANSPORT_WRITE_FAILED`, `TRANSPORT_DISCONNECTED`, `TRANSPORT_TIMEOUT`, `CANCELLED`, and `FAILED_RECONNECT_REQUIRED`. For either method in a nonterminal phase, `null`, `NONE`, or any wrong-domain code throws `IllegalArgumentException` with zero phase, action, or snapshot mutation. For either method in a terminal phase, return the existing terminal action before validating the supplied code. A valid externally supplied code moves the nonterminal machine to its corresponding sticky `Failed` action.

**Closed phase table:** The no-restart `start` rule is evaluated first: `start` outside `NEW` returns and sticks `Failed(INVALID_STATE)`. Every other input not shown below, including a notification while a `WRITE_*` logical acknowledgement is pending or a duplicate `onFd02WriteAcknowledged()`, moves the nonterminal machine to `FAILED` and returns its sticky `Failed` action. Each correctly domain-typed `onProtocolFailed(FailureCode)` and `onTransportFailed(FailureCode)` is legal in every nonterminal phase and does the same; a null, `NONE`, or out-of-domain external failure input throws `IllegalArgumentException` without mutating the nonterminal machine. Apart from the invalid-restart rule, `COMPLETE` and `FAILED` keep returning their respective terminal action for every later input without mutation, including external failure calls before their code domains are validated.

| Phase | Legal input | Output and next phase |
|---|---|---|
| `NEW` | `start(settings, hostId)` | `SendFd02(bind)` → `WRITE_BIND` |
| `WRITE_BIND` | one logical `onFd02WriteAcknowledged()` | `AwaitFd01` → `WAIT_BIND` |
| `WAIT_BIND` | valid FD01 bind response, flags `0x04` (captured no-ACK) | `SendFd02(C0)` → `WRITE_C0` |
| `WAIT_BIND` | valid FD01 bind response requesting reply (compatibility) | `SendFd02(opcode-FF bind ACK, bind-stream serial 1)` → `WRITE_BIND_ACK` |
| `WRITE_BIND_ACK` | one logical `onFd02WriteAcknowledged()` | `SendFd02(C0)` → `WRITE_C0` |
| `WRITE_C0` | one logical `onFd02WriteAcknowledged()` | `AwaitFd03` → `WAIT_C1` |
| `WAIT_C1` | valid FD03 C1 with nonfinal aligned resume | `SendFd02(C2)` → `WRITE_C2` |
| `WAIT_C1` | valid FD03 C1 with full resume (`offset == total`) | `AwaitFd03` → `WAIT_C5` |
| `WRITE_C2` | one logical acknowledgement for a nonfinal C2 | `AwaitFd03` → `WAIT_C3` |
| `WRITE_C2` | one logical acknowledgement for the final C2 | `AwaitFd03` → `WAIT_FINAL` |
| `WAIT_C3` | valid FD03 nonfinal C3 | atomically update snapshot and immediately `SendFd02(next C2)` → `WRITE_C2` |
| `WAIT_FINAL` | valid FD03 final C3 | `AwaitFd03` → `WAIT_C5` |
| `WAIT_FINAL` | valid FD03 direct final C5 | `Complete` → `COMPLETE` |
| `WAIT_C5` | valid FD03 zero-result C5 | `Complete` → `COMPLETE` |
| `COMPLETE` | any non-`start` input | existing `Complete` action, stay `COMPLETE` |
| `COMPLETE` | `start(...)` | `Failed(INVALID_STATE)` → `FAILED` |
| `FAILED` | any non-`start` input | existing `Failed` action, stay `FAILED` |
| `FAILED` | `start(...)` | `Failed(INVALID_STATE)`, stay `FAILED` |

`Complete` means the stock transport accepted the payload; it does not mean that custom firmware booted or passed post-C5 build verification. Optional bind ACK, nonzero resume, and final-C3-before-C5 are compatibility behaviors, not capture-proven facts.

**Immutable artifact and snapshot contract:** `TransitionArtifact` rejects null inputs; a header length other than 27; a Qix SHA length other than 32; an expected build ID length other than 16; an empty payload or one larger than `32 MiB - 27`; a declared unsigned-u32 Qix payload length that does not equal the UFW payload length; or a whole-Qix SHA mismatch. It defensively copies every constructor input and every getter result, including `qixSha256()` and `expectedBuildId()`.

`Snapshot` is immutable and carries phase, total bytes, acknowledged offset, pending offset/length, `mayCancel`, terminal state, failure code, Qix SHA, and expected build ID. Its accessors are the nested API shown above; its byte arrays are defensively copied and `failureCode()` is `NONE` unless phase is `FAILED`. `mayCancel` is true from `NEW` through `WAIT_C1` and flips false atomically only when a valid C1 is accepted; no other input, including a pre-C1 failure, flips it. The acknowledged offset advances only on C1 resume, accepted C3, or direct-final C5. A final C3 may report 100% while phase remains `WAIT_C5`.

- [ ] **Step 1: Write capture-vector and phase-table tests**

Pin capture counts/vectors: 1,080,360 UFW bytes, captured window 1024, 1,056 C2 blocks, 1,055 C3 responses, and final `9EC701C5010000`. Prove capture no-ACK bind flow; separately label optional ACK serial 1, nonzero aligned resume, and final-C3-before-C5 as compatibility cases. Cover aligned and full resume, both final paths, independent bind/C2 serial distribution and 15→0 wrap, and no response-serial inference. Pin C0 as flags `05`, opcode `C0`, header length 27; C2 length/offset u32le fields, checked `min(window, remaining)` chunks, and long-frame flag boundary chunks 6 and 7. Include a maximum window of 65,527 and unsigned-u32 high-bit C1 values. Test constructor artifact injection/null rejection, single-use second `start`, and the exact nested action subtype/`Kind`/accessor contract, including canonical `AwaitFd03.expectedOpcodes()` arrays by phase.

- [ ] **Step 2: Record RED and implement the smallest deterministic reducer**

The machine owns only phase, negotiated window, offsets, expected logical acknowledgement, independent bind/C2 serial state, and immutable snapshots. It never calls Android APIs, reads files, or performs writes itself. `onFd02WriteAcknowledged()` is invoked only once after all GATT fragment callbacks for one logical frame; it is never a fragment callback. A valid nonfinal C3 updates the snapshot and immediately returns the next `SendFd02`, so the reducer cannot stall waiting for a progress action.

Encode exact frames: C0 uses flags `05`, opcode `C0`, and the 27-byte header. C2 uses `chunkLength:u32le | absoluteOffset:u32le | chunk`, checked arithmetic, `min(window, remaining)`, and flags `01 | (serial << 3) | ((14 + chunkLength) > 20 ? 04 : 00)`. C3 is exactly five bytes with zero result and the expected monotonic offset. C5 is exactly one zero byte and is legal only after a fully write-acknowledged final C2, a final C3, or full resume. Enforce FD01/FD03 channel and opcode ownership strictly.

- [ ] **Step 3: Add exhaustive rejection and immutability tests**

Reject every wrong phase, channel, opcode, payload size, result, and offset; duplicate C1; state other than 1; zero/oversized windows; unsigned-u32 high-bit values; unaligned/out-of-range resume; C3 before C2; nonmonotonic C3; premature C5; notification before logical write acknowledgement; duplicate logical acknowledgement; and any attempt to emit two C2 frames concurrently. Test both closed external failure domains: `onProtocolFailed` accepts only `INVALID_STATE` plus protocol codes and `onTransportFailed` accepts only `TRANSPORT_SETUP_FAILED` plus transport/cancel/reconnect codes. In every nonterminal phase, null, `NONE`, and every cross-domain code must throw `IllegalArgumentException` with zero state/snapshot mutation; in either terminal phase, either external method must return the existing terminal action before code-domain validation. Pin `mayCancel=true` in `NEW` through `WAIT_C1` and its sole atomic false transition on valid C1. Prove terminal stickiness with the documented invalid-restart exception. Attempt mutation of every constructor input, getter result, action payload/frame, expected-opcode array, and snapshot byte-array result, including artifact Qix SHA and expected build ID.

- [ ] **Step 4: Run focused/full gates and commit**

```sh
git add android-controller/app/src/main/java/net/jethachan/factory_badges/transition \
        android-controller/app/src/test/java/net/jethachan/factory_badges/transition
git commit -m 'feat(android): pace acknowledged stock Qix transfer'
```

### Task 3: Add the isolated Android FD00 transport and controller

**Files:**
- Modify: `android-controller/app/src/main/java/net/jethachan/factory_badges/transition/StockQixUuids.java` (add the standard CCCD UUID).
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/transition/StockGattDriver.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/transition/StockQixGattTransport.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/transition/StockTransitionController.java`
- Modify: `android-controller/app/src/test/java/net/jethachan/factory_badges/transition/StockQixUuidsTest.java` (pin the standard CCCD UUID).
- Test: matching tests under `android-controller/app/src/test/java/net/jethachan/factory_badges/transition/`

**Interfaces:**
- Consumes: Android GATT callbacks through generation/token-tagged adapter methods and actions from Task 2.
- Produces: normalized connection, subscription, MTU, write, receive, progress, failure, and completion callbacks.
- Constructs the Task 2 machine from a validated immutable artifact before connection. When a per-channel `QixFrameAssembler` synchronously rejects wrong magic at a frame start or a complete-frame codec/decode failure (including checksum after the frame is complete), the controller calls `onProtocolFailed(MALFORMED_PAYLOAD)`. An incomplete or truncated otherwise-valid notification fragment remains pending reassembly: it is neither rejected nor allowed to refresh the response timeout. Complete-frame exact-length/codec rejection remains a protocol failure wherever it is detectable. If the expected response does not complete before its deadline, response-timeout expiry calls `onTransportFailed(TRANSPORT_TIMEOUT)`. Scan, connect, discovery, service/characteristic/property validation, CCCD subscription, and MTU setup failures call `onTransportFailed(TRANSPORT_SETUP_FAILED)`; the controller preserves the same artifact identity and immutable snapshot metadata across those setup failures.

- [ ] **Step 1: Write fake-driver ordering tests**

Pin `StockQixUuids.CCCD` as `00002902-0000-1000-8000-00805f9b34fb`, service/characteristic discovery, FD01 CCCD then FD03 CCCD with `02 00`, MTU 512 after both descriptors acknowledge, FD02 `WRITE_TYPE_DEFAULT`, `max(20, mtu-6)` fragmentation, exactly one write callback outstanding, and per-channel assembler behavior: wrong magic at a frame start plus complete-frame checksum/codec failure route `onProtocolFailed(MALFORMED_PAYLOAD)`; incomplete/truncated valid fragments remain pending and do not refresh the response deadline; deadline expiry routes `onTransportFailed(TRANSPORT_TIMEOUT)`; complete-frame exact-length rejection is tested only where detectable. Also pin stale GATT generation rejection, setup failure routing, disconnect failure, timeout failure, and direct-final-C5.

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
