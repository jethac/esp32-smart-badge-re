# E87 one-shot lab uploader

This is a non-release Android 12 lab uploader for one reviewed Qix package and
one explicitly displayed Bluetooth address. It deliberately retains package
identity `com.openai.e87probe` so `adb install -r` preserves the app-specific
external directory containing:

```text
/sdcard/Android/data/com.openai.e87probe/files/update.bin
```

The label is `E87 One-Shot Lab Uploader`; the launcher activity is
`com.openai.e87probe.ProbeActivity`.

## Safety contract

Launching the Activity is inert. It displays the exact target MAC, a destructive
lab warning, an unchecked hardware receive/update-mode confirmation, and a
disabled Start button. Launch does not touch external files, create evidence,
log, request permissions, scan, connect, or upload.

Checking the confirmation only enables Start. The first Start click consumes
the attempt and disables both controls. It then:

1. loads only the exact app-specific `update.bin`;
2. rejects missing, directory, or symlink inputs;
3. enforces a 32 MiB hard cap before allocation;
4. enforces the build-generated exact size, uppercase SHA-256, exact 27-byte
   header, and little-endian declared payload length;
5. creates the evidence directory;
6. checks or requests Bluetooth permissions;
7. scans only the displayed address and rejects every name-only match;
8. runs the proven bind and C0/C1/C2/C3/C5 transfer.

There is no asset, embedded package, fallback package, automatic start,
verification-only mode, or retry button. A validation or permission failure
consumes the attempt; relaunching and reconfirming is required.

## Pinned offline prerequisites on `stadia-testbed`

```text
JDK 17:
/home/jethac/.local/share/e87-dev/jdk-17/usr/lib/jvm/java-17-openjdk-amd64

Android API 34:
/home/jethac/.local/share/e87-dev/android-sdk/platforms/android-34/android.jar

Android build tools 34.0.0:
/home/jethac/.local/share/e87-dev/android-sdk/build-tools/34.0.0
```

The ignored signing input is `signing/debug.keystore`, alias
`androiddebugkey`, with file SHA-256
`80af017b00ff31f89f96a08f8f5066363d017b6396e8424e4caf2e7901620556`.
The builder refuses any other file or signer and audits the final certificate
SHA-256 as
`c1492dba623bb541187d6db26b0559d4d0dbcf0ff2ce829317c73dab521b2ce5`.

The two required JNI inputs and SHA-256 values are:

```text
vendor-lib/arm64-v8a/libjl_ota_auth.so
d65dd43fb8eb284b93fcbd85c7ce4e59168f3673e28c7637ed467667e4cc5c4b

vendor-lib/armeabi-v7a/libjl_ota_auth.so
5e629e0e0190f745fade919bcca53a7638915b1f856537352977c8b5e0d214ce
```

No network access or dependency download is used.

## Tests

Run all host tests:

```bash
cd /home/jethac/.local/share/e87-dev/lab/e87-one-shot-uploader
scripts/run-host-tests.sh
```

The suite covers the one-shot state gate, permission ordering, exact-address
source wiring, pin generation, pre-allocation bounds, size/hash/header/declared
length checks, path policy, defensive copies, binary hashes, and build
fail-closed behavior.

## Build after the reviewed Qix is available

Supply all three independently reviewed identity values. The build has no
defaults:

```bash
cd /home/jethac/.local/share/e87-dev/lab/e87-one-shot-uploader
scripts/build-one-shot-apk.sh \
  --package-size REVIEWED_DECIMAL_BYTES \
  --package-sha256 REVIEWED_64_HEX_SHA256 \
  --package-header REVIEWED_54_HEX_HEADER
```

The output is:

```text
build/e87-one-shot-lab-uploader.apk
```

The builder generates the Java pin in a temporary directory, compiles against
API 34, runs D8, packages both JNI libraries, zip-aligns, signs with the pinned
key, and then fails unless the APK has the expected package, launcher Activity,
label, signer certificate, native hashes, and no payload/key/fallback asset.

## Redmi/MIUI operator runbook (not executed by this build)

Only after separate approval, stage the reviewed file and replace the existing
same-package probe:

```bash
adb -s SERIAL push REVIEWED_QIX \
  /sdcard/Android/data/com.openai.e87probe/files/update.bin
adb -s SERIAL install -r build/e87-one-shot-lab-uploader.apk
adb -s SERIAL shell am start -n \
  com.openai.e87probe/com.openai.e87probe.ProbeActivity \
  --es mac 46:83:00:01:8A:E9
```

The launch itself remains inert. On the phone:

1. confirm the large displayed exact MAC;
2. physically place that badge in hardware receive/update mode;
3. check the receive-mode box;
4. tap `START ONE-SHOT UPLOAD`;
5. when Android/MIUI asks for Nearby devices, choose Allow.

If MIUI denies or suppresses the prompt, use **Settings > Apps > Manage apps >
E87 One-Shot Lab Uploader > App permissions > Nearby devices > Allow**, then
relaunch and reconfirm because the denied attempt is consumed. Bluetooth must
already be enabled. No background/autostart permission is required for this
foreground one-shot operation.

Run evidence is written only after Start under a unique directory below the
same app-specific external files directory.
