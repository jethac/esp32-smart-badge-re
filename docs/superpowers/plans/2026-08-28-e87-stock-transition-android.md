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

**Execution prerequisite:** Do not implement this task until this amended Task 3 plan has an independent review and a regenerated Task 3 brief. It remains isolated from the normal/sync/UI path, the JieLi AAR, firmware embedding, and all physical-device work.

**Files:**
- Modify: `android-controller/app/src/main/java/net/jethachan/factory_badges/transition/StockQixUuids.java` — add `CCCD` with the standard UUID.
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/transition/StockGattDriver.java` — fakeable asynchronous FD00 GATT boundary.
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/transition/StockQixGattTransport.java` — the sole Android Bluetooth framework adapter.
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/transition/StockTransitionController.java` — FIFO-confined stateful driver of `StockQixTransferMachine` actions.
- Modify: `android-controller/app/src/test/java/net/jethachan/factory_badges/transition/StockQixUuidsTest.java` — pin `CCCD`.
- Create: `android-controller/app/src/test/java/net/jethachan/factory_badges/transition/FakeStockGattDriver.java` — deterministic command log and generation/token-tagged callback injector.
- Create: `android-controller/app/src/test/java/net/jethachan/factory_badges/transition/FakeScheduler.java` — deterministic positive-deadline scheduler with cancellable handles.
- Create: `android-controller/app/src/test/java/net/jethachan/factory_badges/transition/FifoExecutor.java` — manually drained FIFO `Executor` that proves confinement and asynchronous callback dispatch.
- Create: `android-controller/app/src/test/java/net/jethachan/factory_badges/transition/FakeBleHandlerQueue.java` — separately drained BLE-handler queue that proves command acceptance, handler ordering, platform-start failures, and post-stop scan callback behavior.
- Create: `android-controller/app/src/test/java/net/jethachan/factory_badges/transition/StockGattDriverTest.java` — closed constants, immutable value objects, defensive copies, and listener signature coverage.
- Create: `android-controller/app/src/test/java/net/jethachan/factory_badges/transition/StockTransitionControllerTest.java` — controller/reducer ordering, lifetime, and rejection coverage.
- Create: `android-controller/app/src/test/java/net/jethachan/factory_badges/transition/StockQixGattTransportTest.java` — Android adapter source-branch, callback-copy, and listener-asynchrony coverage.

**Interfaces:**

- Consumes: a validated immutable `TransitionArtifact`, the Task 2 `StockQixTransferMachine`, one fakeable `StockGattDriver`, one explicitly serial FIFO `Executor`, deterministic `Scheduler`, positive-millisecond `Timeouts`, and an immutable-snapshot controller `Listener`.
- Produces: one strictly sequenced stock-FD00 session whose controller state is exactly `IDLE → SCANNING → CONNECTING → DISCOVERING → SUB_FD01 → SUB_FD03 → REQUESTING_MTU → DRIVING → TERMINAL`. The controller constructs and owns the Task 2 machine before it starts a connection, so every setup/transport failure retains the artifact identity and snapshot metadata.
- `StockGattDriver` is the following closed Java 8 API. `Peer`, `Service`, and `Characteristic` reject null constructor inputs; `Service` stores an unmodifiable defensive copy of its characteristic list; `Characteristic` stores a defensive descriptor-UUID set/list and exposes membership only through `hasDescriptor`.

```java
public interface StockGattDriver {
    int STATUS_SUCCESS = 0;
    int PROPERTY_WRITE = 0x08;
    int NOTIFY = 0x10;
    int INDICATE = 0x20;
    int WRITE_TYPE_DEFAULT = 2;

    final class Peer {
        public Peer(String address, String displayName, int rssi);
        public String address();
        public String displayName();
        public int rssi();
        @Override public boolean equals(Object other);
        @Override public int hashCode();
    }
    final class Service {
        public Service(UUID uuid, List<Characteristic> characteristics);
        public UUID uuid();
        public List<Characteristic> characteristics();
    }
    final class Characteristic {
        public Characteristic(UUID uuid, int properties, List<UUID> descriptorUuids);
        public UUID uuid();
        public int properties();
        public boolean hasDescriptor(UUID descriptorUuid);
    }
    interface Listener {
        void onScanResult(long generation, long token, Peer peer);
        void onScanFailed(long generation, long token, int status);
        void onConnectionResult(long generation, long token, int status);
        void onDisconnected(long generation, int status);
        void onServicesResult(long generation, long token, List<Service> services, int status);
        void onSubscriptionResult(long generation, long token, Characteristic characteristic,
                                  UUID descriptorUuid, int status);
        void onMtuResult(long generation, long token, int mtu, int status);
        void onCharacteristicWrite(long generation, long token,
                                   Characteristic characteristic, int status);
        void onNotification(long generation, Characteristic characteristic, byte[] value);
    }

    void setListener(Listener listener);
    boolean startScan(long generation, long token);
    void stopScan(long generation);
    boolean connect(long generation, long token, Peer peer);
    boolean discoverServices(long generation, long token);
    boolean subscribe(long generation, long token, Characteristic characteristic,
                      UUID descriptorUuid, byte[] value);
    boolean requestMtu(long generation, long token, int mtu);
    boolean writeCharacteristic(long generation, long token, Characteristic characteristic,
                                byte[] value, int writeType);
    void disconnect(long generation);
    void close();
}
```

- `Peer` canonicalizes a six-octet Bluetooth address to uppercase colon form (`XX:XX:XX:XX:XX:XX`); `address()` returns that canonical value, and `equals`/`hashCode` use that canonical address only. `displayName` and `rssi` never affect peer identity. A `connect` peer is current only when it is canonically equal to an already surfaced candidate in the current generation.
- All `StockGattDriver.Listener` callbacks are asynchronous: no command invokes a listener inline. Scan, scan-fail, connection, services, subscription, MTU, and characteristic-write callbacks carry `generation` and the unique async-command `token`; disconnect and notification callbacks carry `generation` only. Every async command has a unique token and an exact expected callback kind. A callback must match the current generation, token, and kind before it can mutate state; stale callbacks and stale timers are no-ops. Notifications have no token and are accepted only for the current generation.
- Each boolean `StockGattDriver` command result is **only** acceptance of one tagged command onto `bleHandler`; `true` never means that the Android platform operation has started or succeeded, while `false` means the handler did not accept it. For every accepted command, the handler performs the platform start exactly once. A false/null/non-success platform-start result posts exactly one tagged listener failure for that same generation/token/kind onto `callbackExecutor`; a per-command completion guard suppresses duplicate failure posts. Controller handling of a returned `false` runs on its current FIFO event and likewise enters exactly one tagged setup/write failure. The void `stopScan`, `disconnect`, and `close` commands are also one-way `bleHandler` postings; handler posting order is preserved, so controller-issued stop precedes later connect/disconnect/close platform work.
- `StockTransitionController` nests the following complete Java 8 API. `Timeouts` rejects zero/negative durations, all values are milliseconds, and every reference argument shown rejects null synchronously. The controller is the public lifecycle boundary; it owns a private no-op driver listener for detach instead of ever passing null to `setListener`.

```java
public final class StockTransitionController {
    public interface Scheduler {
        interface Handle { void cancel(); }
        Handle schedule(long delayMillis, Runnable runnable);
    }
    public static final class Timeouts {
        public Timeouts(long setupMillis, long writeMillis, long responseMillis);
        public long setupMillis();
        public long writeMillis();
        public long responseMillis();
    }
    public interface Listener {
        void onCandidate(StockGattDriver.Peer candidate);
        void onSnapshot(StockQixTransferMachine.Snapshot snapshot);
        void onComplete(StockQixTransferMachine.Snapshot snapshot);
        void onFailed(StockQixTransferMachine.FailureCode failureCode,
                      StockQixTransferMachine.Snapshot snapshot);
    }

    public StockTransitionController(TransitionArtifact artifact, StockGattDriver driver,
                                     Executor fifoExecutor, Scheduler scheduler,
                                     Timeouts timeouts, Listener listener);
    public void startScan();
    public void connect(StockGattDriver.Peer peer, int settings, int hostId);
    public void cancel();
    public void close();
    public StockQixTransferMachine.Snapshot snapshot();
}
```

- `StockQixGattTransport` is `public final class StockQixGattTransport implements StockGattDriver` with constructor `public StockQixGattTransport(Context applicationContext, Handler bleHandler, Executor callbackExecutor)`. It is the sole production importer of `android.bluetooth.*`. The caller supplies the same explicitly serial FIFO executor as `callbackExecutor` and the controller’s `fifoExecutor`; transport callback delivery and every controller mutation use that one executor.
- `StockTransitionController` owns a closed internal state enum with exactly `IDLE`, `SCANNING`, `CONNECTING`, `DISCOVERING`, `SUB_FD01`, `SUB_FD03`, `REQUESTING_MTU`, `DRIVING`, and `TERMINAL`; no public transition bypasses this sequence.

**Connection, setup, and validation contract:**

- Scanning is unfiltered and only surfaces candidates. It never claims that a candidate is in stock receive mode and never auto-connects. There is deliberately no scan deadline while a human selects a candidate; no setup timer is armed by `startScan`. In the FIFO `connect(peer, settings, hostId)` event, validate the current-generation candidate, retire the current scan token/expected scan callback kind, then post `stopScan(currentGeneration)` and the tagged GATT connect command to the same `bleHandler`; handler FIFO order stops the current scan before `connectGatt`, and same-generation scan callbacks arriving after that retirement are no-ops. The setup deadline begins only with that accepted connect command.
- Add `StockQixUuids.CCCD = 00002902-0000-1000-8000-00805f9b34fb`. Discovery requires exactly one stock FD00 service and exactly one each of FD01, FD02, and FD03 with the exact captured masks `FD01 = 0x10`, `FD02 = 0x0C`, and `FD03 = 0x1A`. Reject a missing/duplicate service or characteristic, any property subset/superset/wrong mask, and specifically an indication-only FD01/FD03. FD02 is still emitted only with `WRITE_TYPE_DEFAULT`; its captured `0x0C` mask is not permission to use write-without-response.
- Require `FD01.hasDescriptor(CCCD)` and `FD03.hasDescriptor(CCCD)`, then subscribe FD01 first and FD03 second with exact bytes `02 00`. This is a capture-pinned vendor quirk: accepted `ProbeActivity.java:420-449` deliberately uses `BluetoothGattDescriptor.ENABLE_INDICATION_VALUE` even though FD01/FD03 advertise notify masks. Never replace it with `01 00`/`ENABLE_NOTIFICATION_VALUE` and do not relax the captured masks because of that write.
- On `bleHandler`, each subscribe operation is exactly `setCharacteristicNotification(characteristic, true)` → CCCD lookup → descriptor write. A false local-enable result, null descriptor, `SecurityException`, false legacy write start, or non-`BluetoothStatusCodes.SUCCESS` modern write start is a tagged setup failure. A successful request remains pending until its matching `onDescriptorWrite` callback; only then issue the next FD03 subscription or MTU request.
- Request MTU 512 only after both descriptor callbacks succeed; accept only a successful negotiated MTU of at least 23. A lower/failed MTU or any scan/connect/discover/subscription/MTU setup error calls `onTransportFailed(TRANSPORT_SETUP_FAILED)`.
- A matching non-success `onDescriptorWrite` callback, or any matching non-success scan/connect/services/MTU callback, is also `TRANSPORT_SETUP_FAILED`; a matching non-success `onCharacteristicWrite` callback is `TRANSPORT_WRITE_FAILED`. The current callback kind must match before either result is acted on.
- Increment the generation for each new session and terminal teardown. Clear current-generation candidate identities/lists on every generation change. Teardown and `close()` first retire the current expected callback kind and post `stopScan(oldGeneration)` whenever scan could be active, then detach the driver listener with the private no-op listener before posting best-effort `disconnect`/`close`. Same-generation scan callbacks after connect-stop are rejected by the retired scan token/kind; after teardown they carry the old generation and are no-ops. Teardown callbacks and timers from the old generation are also ignored.

**Threading and lifecycle contract:**

- The one explicitly serial FIFO event executor is shared by transport callback delivery and controller processing. After synchronous null/primitive argument validation, every public controller command (`startScan`, `connect`, `cancel`, `close`) first enqueues onto that FIFO before any state, generation, token, or candidate check; each driver callback also first enqueues before those checks. `snapshot()` is the sole read-only exception: it returns the volatile safely-published immutable latest `StockQixTransferMachine.Snapshot` without mutating state.
- A `Scheduler.schedule(delayMillis, runnable)` callback may run on any thread, but its runnable only enqueues a FIFO event; it never invokes controller/reducer state logic directly. Inside that FIFO event, verify the scheduled handle is still current, then verify generation, token, expected state, and expected callback kind before applying timeout failure. Cancellation, replacement, stale generation, stale token, wrong state/kind, and a timer that races teardown are no-ops. The tests must invoke a timer from a separate thread and prove all mutation/publication occurs only after FIFO drain.
- `startScan()` is legal exactly once from `IDLE`. A repeated or out-of-state `startScan()` or `connect(...)`, including `connect` with a peer not surfaced in the current generation, transitions the nonterminal session once to sticky `INVALID_STATE`; the controller applies `machine.onProtocolFailed(INVALID_STATE)`, publishes the resulting failed snapshot once, and tears down. `connect(peer, settings, hostId)` is legal only in `SCANNING` and only when `peer` is one of the current-generation candidates already delivered to `Listener.onCandidate`.
- All constructor inputs, `setListener` inputs, public reference arguments, callback reference arguments, and byte arrays reject null synchronously at their own boundary; inbound/outbound byte arrays and returned lists are defensive. The controller does not use `setListener(null)` for teardown.
- Before valid C1 acceptance, `cancel()` enters `TERMINAL` through `onTransportFailed(CANCELLED)`. After valid C1, `cancel()` is a no-op with no controller/reducer snapshot mutation and `mayCancel` remains false. `close()` is idempotent and always tears down: before C1 it publishes terminal `CANCELLED`, after C1 it publishes terminal `FAILED_RECONNECT_REQUIRED` while retaining artifact identity and acknowledged offset, and once terminal it makes no new state/listener mutation. All later public calls after terminal are no-ops.
- Disconnect during `SCANNING`, `CONNECTING`, `DISCOVERING`, `SUB_FD01`, `SUB_FD03`, or `REQUESTING_MTU` calls `onTransportFailed(TRANSPORT_SETUP_FAILED)`. In `DRIVING` before valid C1 it calls `onTransportFailed(TRANSPORT_DISCONNECTED)`; after valid C1 it calls `onTransportFailed(FAILED_RECONNECT_REQUIRED)`, retaining the artifact identity and acknowledged offset in the terminal snapshot.

**Reducer/action, write, notification, and timeout contract:**

- `applyAction` is exact and single-threaded: `SendFd02` starts FD02 fragmentation; `AwaitFd01` and `AwaitFd03` arm the corresponding response deadline; `Complete` and `Failed` publish the immutable snapshot and perform terminal teardown. The controller never creates a second logical C2 while the prior C2 is pending.
- Fragment every logical frame to `max(20, negotiatedMtu - 6)` bytes and issue `writeCharacteristic` with `WRITE_TYPE_DEFAULT`. Store the exact discovered FD02 `Characteristic` object as the current write target and permit exactly one physical characteristic-write callback to be outstanding. Only a final successful callback matching the current generation, token, expected write kind, `characteristic == currentFd02`, and `characteristic.uuid().equals(StockQixUuids.FD02)` invokes exactly one `machine.onFd02WriteAcknowledged()`; never invoke it for a nonfinal fragment or a duplicate callback. A stale generation/token/kind callback is a no-op. A current-generation/token/kind callback with a different object or UUID fails closed as `onProtocolFailed(WRONG_CHANNEL)` and never logically acknowledges. A failed physical write or write deadline calls `onTransportFailed(TRANSPORT_WRITE_FAILED)`.
- Keep independent `QixFrameAssembler` instances for FD01 and FD03. A notification from an unknown current UUID calls `onProtocolFailed(WRONG_CHANNEL)`. A notification during any reducer `WRITE_*` phase reaches the reducer and therefore fails closed. Route synchronous wrong magic at a frame start and a complete-frame codec/decode/checksum failure to `onProtocolFailed(MALFORMED_PAYLOAD)`.
- Incomplete or truncated otherwise-valid notification fragments remain pending in their channel assembler. They are neither rejected nor allowed to cancel or refresh the response deadline. Only a complete accepted frame consumes the response deadline. Response timeout calls `onTransportFailed(TRANSPORT_TIMEOUT)`; detectable complete-frame exact-length/codec rejection is protocol failure.
- Each active setup command owns the setup deadline; a setup timeout calls `onTransportFailed(TRANSPORT_SETUP_FAILED)`. Each logical write owns the write deadline; a write timeout calls `onTransportFailed(TRANSPORT_WRITE_FAILED)`. Each `AwaitFd01`/`AwaitFd03` action owns the response deadline; expiry calls `onTransportFailed(TRANSPORT_TIMEOUT)`. A generation/token mismatch or cancelled handle is a no-op.
- A direct final C5 is passed through the Task 2 machine exactly as a current FD03 completion; controller completion means only that stock transport accepted the payload, never that custom firmware booted.

**Android transport branch contract:**

- `StockQixGattTransport` alone imports `android.bluetooth.*`; `StockGattDriver`, `StockTransitionController`, and all fakes remain Android-free and must not import `ble.normal`, `sync`, `BluetoothOTAManager`, or any JieLi AAR type.
- Use exactly `connectGatt(..., TRANSPORT_LE, PHY_LE_1M_MASK, bleHandler)` and empty/unfiltered scanner filters. The driver’s boolean result is `bleHandler.post(...)` acceptance only; platform work then runs in that handler task. Listener callbacks are copied and posted to the separate shared FIFO `callbackExecutor`, never delivered inline. Tests use independently drained handler and FIFO queues to prove a controller event cannot observe a platform-start result before the handler task runs.
- For descriptor subscription on API 31/32, perform the already-required local-enable/CCCD-lookup order, then defensively copy `02 00`, require `descriptor.setValue(copy)` to return true, and require `gatt.writeDescriptor(descriptor)` to return true. A false `setValue` or write start emits exactly one tagged setup-failure callback. On API 33+, route through a private `@TargetApi` thunk and require `gatt.writeDescriptor(descriptor, copy) == BluetoothStatusCodes.SUCCESS`, otherwise emit exactly one tagged setup-failure callback. In both branches, wait for the matching `onDescriptorWrite` before emitting the tagged `onSubscriptionResult`; do not advance FD01 → FD03 → MTU on the immediate start result alone.
- For physical FD02 writes on API 31/32, defensively copy each fragment, set `WRITE_TYPE_DEFAULT`, require `characteristic.setValue(copy)` to return true, and require `gatt.writeCharacteristic(characteristic)` to return true. A false `setValue` or write start emits exactly one tagged write-failure callback. On API 33+, use a private `@TargetApi` thunk and require `gatt.writeCharacteristic(characteristic, copy, WRITE_TYPE_DEFAULT) == BluetoothStatusCodes.SUCCESS`, otherwise emit exactly one tagged write-failure callback. In both branches, only matching `onCharacteristicWrite` callbacks complete physical fragments. Support both Android characteristic-notification callback shapes and defensively copy their values before FIFO delivery.
- After accepted handler posting, every platform-start false/null/non-`BluetoothStatusCodes.SUCCESS` result is reported exactly once through its tagged listener callback and therefore enters the shared controller FIFO before any later controller event: scanner failure, null/failed `connectGatt`, `discoverServices`, local notification enable/CCCD lookup/legacy `setValue`/descriptor write, `requestMtu`, and all physical writes map to `TRANSPORT_SETUP_FAILED` or `TRANSPORT_WRITE_FAILED` as applicable. A `SecurityException` at scan/connect/discover/subscribe/MTU/write takes the same exactly-once tagged path; it never escapes the controller boundary.

- [ ] **Step 1: Write the fake boundary and exact profile/order tests before production classes**

Create `FakeStockGattDriver`, `FakeScheduler`, `FifoExecutor`, and a separately drained `FakeBleHandlerQueue` first. Make the driver record command order, supplied generation/token, subscription characteristic/descriptor/value, MTU, write type, and individual copied fragments; make the scheduler expose only explicit due callbacks and cancellable handles; make the FIFO executor prove that neither driver nor controller listener delivery is inline; make the BLE queue prove handler posting is distinct from FIFO consumption. Add failing API/ordering tests that pin all of the following:

- The complete closed Java 8 signatures above compile; `Peer(address, displayName, rssi)` canonicalizes address identity, equality, and hash code while leaving name/RSSI out of equality; `Service.uuid()/characteristics()` returns an unmodifiable defensive list; and `Characteristic.uuid()/properties()/hasDescriptor(UUID)` is immutable. Null construction/public/callback data rejects synchronously and array/list mutation cannot alter stored values.
- `StockQixUuids.CCCD` equals `00002902-0000-1000-8000-00805f9b34fb`; discovery accepts only exact FD01 `0x10`, FD02 `0x0C`, and FD03 `0x1A`. Reject indication-only, missing, duplicate, subset, superset, and all other wrong masks.
- The only valid profile order is unfiltered scan candidate → user `connect` → exactly-one FD00/FD01/FD02/FD03 validation → FD01 local-notification enable then CCCD `02 00` → matching FD01 descriptor callback → FD03 local-notification enable then CCCD `02 00` → matching FD03 descriptor callback → MTU request 512 → `machine.start`/bind write. Pin the vendor `02 00` indication value despite FD01/FD03 notify masks; never accept `01 00` as the planned default.
- Local notification enable happens before CCCD lookup and descriptor write. A false enable, null CCCD, false/non-success descriptor start, descriptor status failure, or descriptor callback with stale generation/token/characteristic/descriptor prevents the next setup command and fails setup.
- Each driver boolean first proves only BLE-handler acceptance, not Android platform success. Test the separate handler/FIFO ordering, a driver returned false, and every handler-side immediate start failure: scanner failure/`SecurityException`, null/failed `connectGatt`, discover false/`SecurityException`, local notification enable false, null CCCD, legacy descriptor `setValue` false, descriptor write false/non-success/`SecurityException`, MTU false/`SecurityException`, legacy characteristic `setValue` false, and physical-write false/non-success/`SecurityException`. Each produces exactly one tagged callback/FIFO failure as `TRANSPORT_SETUP_FAILED` or `TRANSPORT_WRITE_FAILED`, never an inline mutation or duplicate callback.
- `startScan` has no human-selection timeout. A valid current-generation `connect` retires the scan token/kind, records handler-ordered `stopScan` before `connectGatt`, starts setup timeout only at connect, clears candidates on generation rollover, and treats same-generation post-stop plus old-generation post-teardown scan callbacks as no-ops.
- MTU 256 yields 250-byte physical fragments and MTU 23 yields 20-byte fragments. No physical write overlaps another; no logical acknowledgement occurs until the final fragment callback; a duplicate callback cannot create a second C2.
- FD01 and FD03 fragment and concatenate independently. Wrong starting magic and complete checksum/codec/length rejection are `MALFORMED_PAYLOAD`; incomplete/truncated valid bytes stay pending and do not refresh the response timer; only a complete valid response consumes it.

- [ ] **Step 2: Run and record intended RED**

Run the new focused `StockQixUuidsTest`, `StockGattDriverTest`, `StockTransitionControllerTest`, and `StockQixGattTransportTest` with the pinned offline JDK/SDK command. Record the expected compile failure solely for absent Task 3 types/API and test fakes; do not alter Task 1/Task 2 production behavior to make the tests compile.

- [ ] **Step 3: Implement the Android-free driver contract and FIFO controller**

Implement immutable `StockGattDriver.Peer`, `.Service`, and `.Characteristic`; the closed constants; non-null listener registration; and the controller constructor/public methods exactly as listed above. Create the Task 2 machine before connection. Confine all controller state, action application, snapshot publication, timers, generation/token checks, expected callback kind, candidate identity/list, and terminal teardown to the shared FIFO executor. Ignore stale callbacks/timers with no state or listener mutation. Safely publish the immutable latest reducer snapshot through one `volatile` field for cross-thread `snapshot()` reads.

Add lifecycle tests: `startScan` is legal once only in `IDLE`; repeated/out-of-state `startScan` or `connect` sticks `INVALID_STATE`; `connect` accepts only canonical-address-equal current-generation candidates; generation changes clear candidates; valid connect stops scan first; teardown/close stops scan; post-stop callbacks are ignored; pre-C1 `cancel` is `CANCELLED`; post-C1 cancel is a no-op; pre-C1/after-C1 disconnect has the required split; `close` is idempotent with `CANCELLED` pre-C1 and `FAILED_RECONNECT_REQUIRED` post-C1; terminal calls add no mutation/callback. Exercise a reader thread observing `snapshot()` while FIFO work publishes snapshots and a separate scheduler thread fires a timer; prove both see/use valid immutable snapshots and all mutation occurs only after FIFO drain.

- [ ] **Step 4: Implement exact write, receive, and timeout pacing**

Implement `applyAction`, one-physical-write-at-a-time fragmentation, `WRITE_TYPE_DEFAULT`, final-fragment-only logical acknowledgement, independent FD01/FD03 assemblers, complete-frame failure ingress, and setup/write/response timer routing exactly as specified above. Test every timeout category, timer callback on a non-FIFO thread, cancelled/stale timer handle, stale generation/token/kind callback, wrong/stale notification UUID, notification during `WRITE_*`, direct final C5, aligned/partial response reassembly, and the no-overlap/no-second-C2 invariant. For FD02, pin that a logical acknowledgement occurs only after exact generation/token/kind plus `characteristic == currentFd02` and the FD02 UUID; a current tagged callback with a same-UUID different object or wrong UUID fails closed, while stale callback data is a no-op. Verify partial notification bytes neither cancel nor refresh a response deadline and that only a complete accepted frame consumes it.

- [ ] **Step 5: Implement the Android transport adapter and source-branch tests**

Implement only `StockQixGattTransport` with the exact `bleHandler` local-enable → CCCD lookup → descriptor-write order, API 31/32 legacy descriptor `setValue(copy)`/`writeDescriptor` branch, API 33+ private `@TargetApi` `writeDescriptor(descriptor, copy)` branch requiring `BluetoothStatusCodes.SUCCESS`, and matching `onDescriptorWrite` completion ordering. Implement equivalent legacy/API33 physical-characteristic write branches and matching `onCharacteristicWrite` completion. Use exact LE/1M/handler `connectGatt`, empty scanner filters, copied notification callback payloads for both Android callback shapes, asynchronous FIFO listener posting, and immediate failure conversion.

Add source/adapter tests for both descriptor branches, descriptor callback ordering, both characteristic-write branches, both notification callback shapes, local enable/CCCD failure, legacy `setValue` false handling, copied values, separate handler/FIFO ordering, serial FIFO confinement, exactly-once tagged failure delivery for every false/null/non-success path, and sole `android.bluetooth.*` import ownership. Assert Task 3 code has no normal/sync/JieLi-AAR imports.

- [ ] **Step 6: Run focused/full gates and commit**

Run all Task 3-focused tests, then the complete offline `testDebugUnitTest lintDebug` gate with the pinned JDK/SDK. Self-review the captured masks/vendor CCCD quirk, generation/token no-ops, FIFO-only state mutation, volatile snapshot publication, timer cancellation, immutable copies, lifecycle terminal rules, state/phase boundaries, and the exact source-import boundary before committing only Task 3 files:

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
