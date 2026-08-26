# E87 Android Controller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and install a native Android app that sends the exact eight-byte Devin state packet during normal operation and performs physically gated, validated JieLi single-bank maintenance updates.

**Architecture:** A new `android-controller` project replaces the old Flutter/JPEG application for this trial. Plain Java UI and `BluetoothGatt` code are split into normal-sync and maintenance packages with a static dependency gate between them; the official pinned JieLi OTA AAR is used only behind the maintenance boundary.

**Tech Stack:** Java 8 bytecode on Corretto JDK 21, Android Gradle Plugin 8.5.2, Gradle 8.7, compile/target SDK 34, minimum SDK 31, Android framework Views/BLE/SAF APIs, JUnit 4.13.2, JieLi OTA AAR 1.11.0.

**Spec:** `docs/superpowers/specs/2026-08-27-e87-local-rendering-trial-design.md`

## Global Constraints

- Application ID is `net.jethachan.factory_badges`; the native APK intentionally replaces the trial's old Flutter APK.
- Normal operation writes only `e87d0002-7a1b-4c62-9f0b-5d9c01a70735`; it never sends pixels, JPEGs, Qix C0-C5 frames, or RCSP data.
- The normal packet is exactly `01 DD WW 00 BF 06 00 00`; Day and Week are integers `0..100`, credit is fixed at 1727 cents, and there is no sequence number.
- Normal state writes require GATT write-with-response over an encrypted link owned by the remembered bond.
- The app has no `INTERNET`, location, storage, cleartext, Flutter, Factory-client, Retrofit, or generic BLE-wrapper capability.
- Firmware selection uses `ACTION_OPEN_DOCUMENT_TREE`; `manifest.json` names exactly one adjacent Qix or UFW artifact and both are validated before any BLE connection.
- The maintenance path accepts only a physically opened `E87 UPDATE` window advertising AE00 plus the JieLi manufacturer marker; a name alone is never identity.
- After JieLi reports `onNeedReconnect`, Cancel is disabled, the exact artifact hash is retained, loader reconnect is automatic, and success requires normal-service reconnection plus exact build-info match.
- The official AAR source is `https://github.com/Jieli-Tech/Android-JL_OTA.git` commit `4bf054e1ae6e549b617e266cea733576c80c55d5`; `libs/jl_bt_ota_V1.11.0_11015-release.aar` SHA-256 is `6F8DEC58C53C33DC9B1189D6AA1ECC4A0FE6A43ECF44BB4C79BBEE723E0D2550` and its repository license is Apache-2.0.
- V1 has no anti-rollback rule beyond exact chip/profile/layout validation and the physical maintenance gate; the manifest records `antiRollbackPolicy: none-v1-physical-gate`.
- All commands run from repository root unless the task says otherwise; use `C:\Program Files\Amazon Corretto\jdk21.0.9_10` and the Android SDK under `%LOCALAPPDATA%\Android\Sdk`.

---

## File Map and Stable Interfaces

Create the independent project below; do not modify `android/`, `lib/`, or `pubspec.yaml`.

```text
android-controller/
  settings.gradle.kts
  build.gradle.kts
  gradle.properties
  gradlew
  gradlew.bat
  gradle/wrapper/gradle-wrapper.jar
  gradle/wrapper/gradle-wrapper.properties
  app/build.gradle.kts
  app/libs/jl_bt_ota_V1.11.0_11015-release.aar
  app/libs/JL_OTA_LICENSE.txt
  app/libs/JL_OTA_SHA256.txt
  app/src/main/AndroidManifest.xml
  app/src/main/java/net/jethachan/factory_badges/
    model/{BadgeState,BuildInfo,ConnectionSnapshot}.java
    protocol/{StatePacketCodec,BuildInfoCodec}.java
    ble/normal/{NormalUuids,NormalAdvertisementParser,GattOperationQueue,BondCoordinator,NormalGattClient}.java
    sync/{ReconnectPolicy,BadgeSyncService}.java
    maintenance/{FirmwareManifest,QixPackage,QixPackageParser,JieliUfwValidator,ArtifactValidator,ValidatedArtifact,ResumeRecord,ResumeStore,MaintenanceUuids,MaintenanceGattTransport,JieliOtaEngine,MaintenanceStateMachine,LoaderAdvertisementParser,LoaderReconnectCoordinator,PostUpdateVerifier}.java
    diagnostic/{DiagnosticLog,UserVisibleError}.java
    ui/{MainActivity,MainViewModel,MaintenanceActivity}.java
  app/src/main/res/layout/{activity_main,activity_maintenance}.xml
  app/src/main/res/values/{strings,styles}.xml
  app/src/test/java/net/jethachan/factory_badges/**
  scripts/{fetch-jieli-ota.ps1,verify-apk.ps1,install-redmi.ps1}
```

Stable cross-task APIs:

```java
public final class BadgeState {
    public BadgeState(int dayPercent, int weekPercent, long creditCents);
    public int dayPercent();
    public int weekPercent();
    public long creditCents();
    // Value equality/hashCode are required for tests and state restoration.
}

public final class StatePacketCodec {
    public static final int PACKET_LENGTH = 8;
    public static byte[] encode(BadgeState state);
    public static BadgeState decode(byte[] packet);
}

public final class BuildInfo {
    public BuildInfo(int capabilities, String hardwareProfile,
                     int major, int minor, int patch, byte[] buildId);
    public int capabilities();
    public String hardwareProfile();
    public int major();
    public int minor();
    public int patch();
    public byte[] buildId(); // defensive copy
    // Value equality/hashCode are required; byte-array equality is by contents.
}

public final class BuildInfoCodec {
    public static final int RECORD_LENGTH = 40;
    public static BuildInfo decode(byte[] bytes);
    public static boolean matchesExpected(BuildInfo actual,
                                          FirmwareManifest expected);
}
```

`NormalGattClient` is the only normal GATT owner; `JieliOtaEngine` is the only class allowed to extend `BluetoothOTAManager`. `MainActivity`, `sync`, and `ble.normal` may launch `MaintenanceActivity` by explicit Intent but may not import any other maintenance type.

### Task 1: Bootstrap the isolated native project and dependency quarantine

**Files:**
- Create: `android-controller/settings.gradle.kts`
- Create: `android-controller/build.gradle.kts`
- Create: `android-controller/gradle.properties`
- Create: `android-controller/gradle/wrapper/gradle-wrapper.properties`
- Create: `android-controller/app/build.gradle.kts`
- Create: `android-controller/app/src/main/AndroidManifest.xml`
- Create: `android-controller/app/src/test/java/net/jethachan/factory_badges/architecture/ManifestSourceTest.java`
- Create: `android-controller/scripts/fetch-jieli-ota.ps1`

**Interfaces:**
- Consumes: Corretto 21, Android SDK 34, official JieLi repository pin above.
- Produces: `:app` debug APK build, local verified AAR, and a manifest with only BLE/foreground permissions.

- [ ] **Step 1: Write the failing manifest quarantine test**

```java
@Test public void manifestHasNoNetworkLocationOrStoragePermission() throws Exception {
    String xml = Files.readString(Path.of("app/src/main/AndroidManifest.xml"));
    for (String forbidden : List.of("INTERNET", "ACCESS_FINE_LOCATION",
            "ACCESS_COARSE_LOCATION", "READ_EXTERNAL_STORAGE",
            "WRITE_EXTERNAL_STORAGE", "MANAGE_EXTERNAL_STORAGE",
            "usesCleartextTraffic")) {
        assertFalse(forbidden, xml.contains(forbidden));
    }
    assertTrue(xml.contains("BLUETOOTH_SCAN"));
    assertTrue(xml.contains("BLUETOOTH_CONNECT"));
}
```

- [ ] **Step 2: Create Gradle configuration and verify the test initially fails because the project is absent**

Run:

```powershell
$env:JAVA_HOME='C:\Program Files\Amazon Corretto\jdk21.0.9_10'
.\android-controller\gradlew.bat -p .\android-controller testDebugUnitTest
```

Expected: FAIL before the wrapper/project exists, then compile the test after scaffolding and observe failure until the manifest is created.

- [ ] **Step 3: Implement the project skeleton and exact manifest**

Use AGP `8.5.2`, Gradle distribution `gradle-8.7-bin.zip`, `compileSdk=34`, `targetSdk=34`, `minSdk=31`, Java 8 compatibility, and these permissions only:

```xml
<uses-permission android:name="android.permission.BLUETOOTH_SCAN"
    android:usesPermissionFlags="neverForLocation"/>
<uses-permission android:name="android.permission.BLUETOOTH_CONNECT"/>
<uses-permission android:name="android.permission.FOREGROUND_SERVICE"/>
<uses-permission android:name="android.permission.FOREGROUND_SERVICE_CONNECTED_DEVICE"/>
<uses-permission android:name="android.permission.POST_NOTIFICATIONS"/>
<uses-feature android:name="android.hardware.bluetooth_le" android:required="true"/>
```

Declare `MainActivity` exported, `MaintenanceActivity` and `BadgeSyncService` non-exported, and the service as `foregroundServiceType="connectedDevice"`. Add manifest-merger removal nodes for every unwanted AAR permission.

- [ ] **Step 4: Pin and fetch the JieLi AAR**

`fetch-jieli-ota.ps1` clones commit `4bf054e1ae6e549b617e266cea733576c80c55d5`, copies only the AAR and `LICENSE`, checks the AAR hash above, and refuses to overwrite a mismatched existing file.

- [ ] **Step 5: Run the unit test and assemble an empty APK**

Run: `.\android-controller\gradlew.bat -p .\android-controller --no-daemon testDebugUnitTest assembleDebug`

Expected: PASS and `android-controller/app/build/outputs/apk/debug/app-debug.apk` exists.

- [ ] **Step 6: Commit**

```powershell
git add android-controller
git commit -m "build(android): bootstrap native E87 controller"
```

### Task 2: Implement semantic-state and build-info codecs

**Files:**
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/model/BadgeState.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/model/BuildInfo.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/protocol/StatePacketCodec.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/protocol/BuildInfoCodec.java`
- Test: `android-controller/app/src/test/java/net/jethachan/factory_badges/protocol/StatePacketCodecTest.java`
- Test: `android-controller/app/src/test/java/net/jethachan/factory_badges/protocol/BuildInfoCodecTest.java`

**Interfaces:**
- Consumes: Exact v1 packet and 40-byte build-info layouts from the spec.
- Produces: Pure immutable model objects and strict codecs used by normal BLE and post-update verification.

- [ ] **Step 1: Write exhaustive packet tests**

```java
@Test public void encodesBoundaryVector() {
    assertArrayEquals(new byte[]{1, 100, 0, 0, (byte)0xBF, 6, 0, 0},
        StatePacketCodec.encode(new BadgeState(100, 0, 1727)));
}

@Test public void acceptsEverySliderInteger() {
    for (int day=0; day<=100; day++) for (int week=0; week<=100; week++) {
        BadgeState expected = new BadgeState(day, week, 1727);
        assertEquals(expected, StatePacketCodec.decode(StatePacketCodec.encode(expected)));
    }
}
```

Add rejection tests for lengths `0..7` and `9..16`, schema not 1, percentages `101..255`, nonzero flags, and credit not 1727.

- [ ] **Step 2: Run codec tests and verify failure**

Run: `.\android-controller\gradlew.bat -p .\android-controller testDebugUnitTest --tests '*StatePacketCodecTest'`

Expected: FAIL because the model and codec do not exist.

- [ ] **Step 3: Implement strict encoding and decoding**

```java
public static byte[] encode(BadgeState s) {
    requirePercent(s.dayPercent());
    requirePercent(s.weekPercent());
    if (s.creditCents() != 1727L) throw new IllegalArgumentException("credit");
    return new byte[]{1, (byte)s.dayPercent(), (byte)s.weekPercent(), 0,
                      (byte)0xBF, 0x06, 0, 0};
}
```

Decode only after validating all eight bytes; never return a partial/default object.

- [ ] **Step 4: Write and run 40-byte build-info tests**

Cover schema 1, capability `0x07`, exact NUL padding of `E87-JD9855-R1`, semver bytes, reserved zeros, 16-byte build ID, malformed UTF-8/embedded NUL, and every wrong length/reserved bit.

- [ ] **Step 5: Implement `BuildInfoCodec` and rerun all protocol tests**

Expected: PASS with no Android framework dependency in either codec.

- [ ] **Step 6: Commit**

```powershell
git add android-controller/app/src/main/java/net/jethachan/factory_badges/model android-controller/app/src/main/java/net/jethachan/factory_badges/protocol android-controller/app/src/test/java/net/jethachan/factory_badges/protocol
git commit -m "feat(android): add exact E87 semantic codecs"
```

### Task 3: Build normal advertisement parsing and serialized GATT operations

**Files:**
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/ble/normal/NormalUuids.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/ble/normal/NormalAdvertisementParser.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/ble/normal/GattOperationQueue.java`
- Test: `android-controller/app/src/test/java/net/jethachan/factory_badges/ble/normal/NormalAdvertisementParserTest.java`
- Test: `android-controller/app/src/test/java/net/jethachan/factory_badges/ble/normal/GattOperationQueueTest.java`

**Interfaces:**
- Consumes: Android scan records through small byte-array adapters.
- Produces: Exact normal-device classification and a one-operation-at-a-time queue.

- [ ] **Step 1: Write parser tests**

Accept only local name `E87` plus the exact 128-bit service UUID. Reject `E87 UPDATE`, `*_update`, `*_LE_UPDATE`, name-only matches, AE00-only records, truncated AD structures, and unrelated E87 products.

- [ ] **Step 2: Implement `NormalUuids` and the pure parser**

```java
public final class Match {
    public Match(boolean normalService, String localName);
    public boolean normalService();
    public String localName();
}
public static Optional<Match> parse(byte[] scanRecord) { /* bounded AD walk */ }
```

The AD walk must reject a length byte that extends past the scan record and compare UUID bytes in BLE little-endian order.

- [ ] **Step 3: Write queue ordering/timeout tests**

Use a fake `GattDriver` to prove one active operation, CCCD-before-read/write ordering, callback completion by operation token, timeout failure, stale callback rejection, and deterministic `failAll`.

- [ ] **Step 4: Implement the framework-independent queue core**

```java
interface GattOperation {
    long token();
    long timeoutMs();
    boolean start(GattDriver driver);
}

final class GattOperationQueue {
    void enqueue(GattOperation op);
    void complete(long token, int status);
    void failAll(Throwable cause);
}
```

- [ ] **Step 5: Run tests**

Run: `.\android-controller\gradlew.bat -p .\android-controller testDebugUnitTest --tests '*NormalAdvertisementParserTest' --tests '*GattOperationQueueTest'`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add android-controller/app/src/main/java/net/jethachan/factory_badges/ble/normal android-controller/app/src/test/java/net/jethachan/factory_badges/ble/normal
git commit -m "feat(android): classify E87 advertisements and serialize GATT"
```

### Task 4: Implement bonding, the normal GATT client, and reconnect policy

**Files:**
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/ble/normal/BondCoordinator.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/ble/normal/NormalGattClient.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/sync/ReconnectPolicy.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/sync/BadgeSyncService.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/model/ConnectionSnapshot.java`
- Test: corresponding fake-driver tests under `app/src/test/.../ble/normal` and `.../sync`.

**Interfaces:**
- Consumes: `BadgeState`, strict codecs, queue, Android BLE callbacks.
- Produces: bonded connection lifecycle, acknowledged state writes, one resend per reconnect, and service snapshots for UI.

- [ ] **Step 1: Write fake-GATT lifecycle tests**

Test unbonded/bonded flow, `GATT_INSUFFICIENT_AUTHENTICATION`, malformed/mismatched build info, optional missing Battery Service, duplicate callbacks, disconnect, and stale `BluetoothGatt` generations. Assert no state write occurs before encryption and build-info validation.

- [ ] **Step 2: Implement `BondCoordinator` and `NormalGattClient`**

```java
interface Listener {
    void onConnected(BuildInfo info, Integer batteryPercent);
    void onStateWriteAcknowledged(BadgeState state, long elapsedRealtimeMs);
    void onDisconnected(int status);
    void onError(UserVisibleError error);
}
```

Discover only the normal custom service plus optional Battery Service; use `WRITE_TYPE_DEFAULT` and treat the characteristic callback as the acknowledgement.

- [ ] **Step 3: Write reconnect/coalescing tests**

Prove capped delays `0, 1000, 2000, 4000, 8000, 15000` ms, one latest-state write after each successful reconnect, explicit Sync writes once, slider changes coalesce while disconnected, and disabling sync cancels reconnect/foreground lifetime.

- [ ] **Step 4: Implement `BadgeSyncService`**

Expose a local binder with `selectDevice`, `setCurrentState`, `setSyncEnabled`, `syncNow`, and `snapshot`. Start foreground operation only while sync is enabled; never remove bonds automatically.

- [ ] **Step 5: Run all normal-path tests**

Expected: PASS; source search in `ble/normal` and `sync` finds no `AE00`, `AE01`, `AE02`, `BluetoothOTAManager`, Qix, or firmware write code.

- [ ] **Step 6: Commit**

```powershell
git add android-controller/app/src/main/java/net/jethachan/factory_badges/ble/normal android-controller/app/src/main/java/net/jethachan/factory_badges/sync android-controller/app/src/main/java/net/jethachan/factory_badges/model android-controller/app/src/test
git commit -m "feat(android): add bonded semantic sync service"
```

### Task 5: Build the Day/Week controller UI

**Files:**
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/ui/MainActivity.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/ui/MainViewModel.java`
- Create: `android-controller/app/src/main/res/layout/activity_main.xml`
- Create: `android-controller/app/src/main/res/values/strings.xml`
- Create: `android-controller/app/src/main/res/values/styles.xml`
- Test: `android-controller/app/src/test/java/net/jethachan/factory_badges/ui/MainViewModelTest.java`

**Interfaces:**
- Consumes: `BadgeSyncService.LocalBinder` and immutable `ConnectionSnapshot`.
- Produces: device picker, two integer sliders, fixed credit display, Sync action/result, and maintenance link.

- [ ] **Step 1: Write pure UI-state tests**

Assert initial Day/Week are 0, each `SeekBar` maps exactly to every integer `0..100`, credit is exactly `$17.27`, Sync passes the current pair once, rotation restores slider values, and maintenance navigation carries no artifact/device secret.

- [ ] **Step 2: Implement a small `MainViewModel` and XML layout**

The layout contains connection text, selected-device button, Day label/value/slider, Week label/value/slider, read-only credit, Sync button, last-ack text, and Maintenance button. Use platform widgets and no Material dependency.

- [ ] **Step 3: Implement runtime permission and service binding**

Request `BLUETOOTH_SCAN` and `BLUETOOTH_CONNECT`; request notifications only on API 33+. Explain denial in plain language and keep the maintenance screen inaccessible until scan/connect is granted.

- [ ] **Step 4: Run UI-state tests and assemble**

Run: `.\android-controller\gradlew.bat -p .\android-controller testDebugUnitTest assembleDebug`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add android-controller/app/src/main/java/net/jethachan/factory_badges/ui android-controller/app/src/main/res android-controller/app/src/test/java/net/jethachan/factory_badges/ui
git commit -m "feat(android): add Devin slider controller UI"
```

### Task 6: Validate manifests, Qix wrappers, UFW containers, and SAF trees

**Files:**
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/maintenance/FirmwareManifest.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/maintenance/QixPackage.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/maintenance/QixPackageParser.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/maintenance/JieliUfwValidator.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/maintenance/ArtifactValidator.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/maintenance/ValidatedArtifact.java`
- Test: `android-controller/app/src/test/java/net/jethachan/factory_badges/maintenance/*ValidatorTest.java`
- Test fixtures: `android-controller/app/src/test/resources/firmware/*`

**Interfaces:**
- Consumes: A persisted SAF tree URI containing canonical `manifest.json` and the exact filename named by it.
- Produces: immutable `ValidatedArtifact(byte[] ufwBytes, byte[] sha256, FirmwareManifest manifest, Uri treeUri)`.

- [ ] **Step 1: Add valid reference and corruption fixtures**

Use the known Qix reference header and create deterministic tiny structural fixtures. Include wrong magic/type, embedded-NUL version, length off by one, outer CRC error, malformed UFW header/table CRC, overlapping entries, path-like names, wrong `AC707N`, wrong profile, dual-bank marker, and manifest hash/size mismatch.

- [ ] **Step 2: Write Qix tests**

```java
@Test public void unwrapsExactHeader() {
    QixPackage p = QixPackageParser.parse(bytes);
    assertEquals(27, p.headerLength());
    assertEquals("11.1.0.2", p.version());
    assertArrayEquals(Arrays.copyOfRange(bytes, 27, bytes.length), p.payload());
}
```

The two-byte little-endian CRC at header offsets 25-26 covers the UFW payload only; it uses polynomial `0x1021`, seed `0xFFFF`, non-reflected, no final XOR.

- [ ] **Step 3: Implement bounded Qix and UFW parsing**

Use checked `long` arithmetic before array slicing. UFW validation decodes the 64-byte header and 80-byte entries with the CD03 transform, validates seed-zero CRCs, entry bounds/non-overlap, tail signature, protected-range decoding, chip `AC707N`, and single-bank member policy.

- [ ] **Step 4: Write SAF tree tests through a fake document provider adapter**

Reject missing/duplicate manifests, missing/ambiguous payloads, manifest filenames containing `/`, `\`, or `..`, unreadable grants, and any validation failure before the BLE scanner is created.

- [ ] **Step 5: Implement tree loading**

Use `DocumentsContract.buildChildDocumentsUriUsingTree`, persist read permission, cap manifest at 256 KiB and payload at 32 MiB, read the named immediate child only, unwrap Qix when declared, and hash the immutable UFW bytes.

- [ ] **Step 6: Run maintenance-parser tests**

Expected: every corruption case fails closed with a stable `UserVisibleError` code.

- [ ] **Step 7: Commit**

```powershell
git add android-controller/app/src/main/java/net/jethachan/factory_badges/maintenance android-controller/app/src/test/java/net/jethachan/factory_badges/maintenance android-controller/app/src/test/resources/firmware
git commit -m "feat(android): validate E87 firmware before BLE"
```

### Task 7: Integrate the physically gated JieLi maintenance transport

**Files:**
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/maintenance/MaintenanceUuids.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/maintenance/MaintenanceGattTransport.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/maintenance/JieliOtaEngine.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/maintenance/MaintenanceStateMachine.java`
- Test: `android-controller/app/src/test/java/net/jethachan/factory_badges/maintenance/MaintenanceGattTransportTest.java`
- Test: `android-controller/app/src/test/java/net/jethachan/factory_badges/maintenance/MaintenanceStateMachineTest.java`

**Interfaces:**
- Consumes: validated artifact and scan result matching AE00 plus JieLi marker within a user-started two-minute window.
- Produces: ordered AE01 writes/AE02 notifications and normalized OTA phase events.

- [ ] **Step 1: Write transport-order tests**

Prove AE02 CCCD enable completes before MTU request, MTU is capped at 500, each outgoing frame is fragmented to `mtu-3`, only one write is outstanding, stale callbacks fail, and no characteristic outside AE01/AE02 is touched.

- [ ] **Step 2: Implement the transport adapter**

```java
interface RcspDataSink { void onBytes(byte[] bytes); }
interface RcspWriteResult { void complete(boolean ok); }
void send(byte[] frame, RcspWriteResult result);
```

Select notify/indicate CCCD value from actual properties and reject a profile with unexpected handles/properties.

- [ ] **Step 3: Write phase/cancel tests**

Use phases `VALIDATING`, `READY`, `AUTHENTICATING`, `LOADER_DOWNLOAD`, `WAITING_FOR_LOADER`, `FIRMWARE_TRANSFER`, `WAITING_FOR_NORMAL`, `VERIFYING_BUILD`, `SUCCEEDED`, `FAILED`. `mayCancel()` is true only before `WAITING_FOR_LOADER`.

- [ ] **Step 4: Implement the official OTA adapter**

`JieliOtaEngine` extends `BluetoothOTAManager`, configures BLE/auth/MTU 500, disables library-managed reconnect, forwards connection/data/MTU callbacks, and maps `IUpgradeCallback.onNeedReconnect` to the irreversible handoff event. It never logs auth packet bodies or keys.

- [ ] **Step 5: Run fake-transport tests**

Expected: gesture/name alone never starts OTA, pre-handoff errors stay cancellable, and no concurrent write occurs.

- [ ] **Step 6: Commit**

```powershell
git add android-controller/app/src/main/java/net/jethachan/factory_badges/maintenance android-controller/app/src/test/java/net/jethachan/factory_badges/maintenance
git commit -m "feat(android): integrate physically gated JieLi OTA"
```

### Task 8: Implement loader reconnect, resume, diagnostics, and maintenance UI

**Files:**
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/maintenance/ResumeRecord.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/maintenance/ResumeStore.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/maintenance/LoaderAdvertisementParser.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/maintenance/LoaderReconnectCoordinator.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/maintenance/PostUpdateVerifier.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/diagnostic/DiagnosticLog.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/ui/MaintenanceActivity.java`
- Create: `android-controller/app/src/main/res/layout/activity_maintenance.xml`
- Test: matching maintenance, diagnostics, and post-verification tests.

**Interfaces:**
- Consumes: `onNeedReconnect`, persisted SAF grant, artifact SHA-256/build ID, loader advertisement, final normal BuildInfo.
- Produces: same-artifact resume and success only after exact normal build verification.

- [ ] **Step 1: Write resume and loader-identity tests**

Persist only tree URI, payload filename, 32-byte SHA-256, 16-byte build ID, prior address, reconnect format, and phase. On process restart reload through `ArtifactValidator` and reject any hash/manifest change. Accept loader names only with the official marker and old-address association; reject name-only matches.

- [ ] **Step 2: Implement resume storage and reconnect coordinator**

Use private `SharedPreferences` for the small record, keep the screen awake post-handoff, and use bounded exponential scan/connect retry. Clear the record only after verified success or an explicit pre-handoff cancel.

- [ ] **Step 3: Write post-update verification tests**

Transfer-complete alone is not success. Test normal-service timeout, malformed record, wrong profile, wrong semver, wrong build ID, and exact success.

- [ ] **Step 4: Implement redacted diagnostics**

Keep at most 512 timestamped lines and 128 KiB. Redact MAC addresses except final two octets, content URIs after authority, every 16/32-byte hex token, auth payloads, bond data, and local filesystem paths.

- [ ] **Step 5: Implement `MaintenanceActivity`**

Show selected folder, artifact filename/size/profile/build, validation result, physically detected maintenance device, phase, acknowledged bytes/progress, plain-language error, and Cancel only while `mayCancel()` is true.

- [ ] **Step 6: Run tests and assemble**

Expected: all unit tests pass and rotation/process recreation cannot substitute an artifact.

- [ ] **Step 7: Commit**

```powershell
git add android-controller/app/src/main android-controller/app/src/test
git commit -m "feat(android): resume OTA and verify post-update build"
```

### Task 9: Enforce the normal/maintenance boundary and install on Redmi

**Files:**
- Create: `android-controller/app/src/test/java/net/jethachan/factory_badges/architecture/ProtocolBoundaryTest.java`
- Create: `android-controller/scripts/verify-apk.ps1`
- Create: `android-controller/scripts/install-redmi.ps1`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: complete native project and connected Redmi serial `b202e7b70221`.
- Produces: audited debug APK installed/launched on Redmi plus captured host verification output.

- [ ] **Step 1: Write static dependency and string-boundary tests**

Fail if `ble/normal`, `sync`, or `MainActivity` contains `AE00`, `AE01`, `AE02`, `BluetoothOTAManager`, `update.ufw`, Qix, JPEG, or maintenance write calls. Fail if the APK contains Flutter engine classes or the old Dart asset tree.

- [ ] **Step 2: Implement `verify-apk.ps1`**

Locate `apkanalyzer.bat`, `aapt2.exe`, and `apksigner.bat` under the Android SDK. Assert package ID, min/target SDK, signature verification, exactly allowed permissions, no cleartext flag, no Flutter native libraries/assets, and presence of arm64-v8a OTA native code when the AAR requires it.

- [ ] **Step 3: Run the full Android gate**

```powershell
$env:JAVA_HOME='C:\Program Files\Amazon Corretto\jdk21.0.9_10'
.\android-controller\gradlew.bat -p .\android-controller --no-daemon clean testDebugUnitTest lintDebug assembleDebug
.\android-controller\scripts\verify-apk.ps1 -Apk .\android-controller\app\build\outputs\apk\debug\app-debug.apk
```

Expected: PASS; permission list contains only Bluetooth, connected-device foreground service, and notifications.

- [ ] **Step 4: Install and launch on Redmi**

`install-redmi.ps1` verifies model `M2010J19SG`, installs with `adb -s b202e7b70221 install -r`, grants scan/connect, launches `.ui.MainActivity`, and saves `am start -W`, package dump, and filtered logcat under `artifacts/verification/android-host/`.

- [ ] **Step 5: Verify offline UI behavior**

Without the badge in receiving/pairing mode, confirm the app launches, both sliders cover `0..100`, `$17.27` is fixed, no crash occurs, and maintenance file selection rejects a deliberately corrupt fixture before scanning.

- [ ] **Step 6: Commit**

```powershell
git add .gitignore android-controller
git commit -m "test(android): audit and install E87 controller"
```

## Plan Completion Gate

The Android plan is complete when all JVM/lint/APK gates pass, the APK installs and launches on Redmi, manifest inspection proves no network/location/storage capability, and hardware-dependent actions remain dormant until the custom badge exposes the exact normal or physically gated maintenance profile.
