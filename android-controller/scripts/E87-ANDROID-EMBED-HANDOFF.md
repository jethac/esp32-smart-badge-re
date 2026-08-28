# E87 Android embed handoff

The Android controller does not accept a Stage-0 package manifest by itself. The final firmware packaging gate must emit a separate canonical ASCII JSON file named `e87-android-embed.json` using schema `e87-android-embed-v1`.

The handoff directory is closed and contains exactly:

- `e87-android-embed.json`
- `app.bin`
- `jl_isd.fw`
- `update.ufw`
- one Qix named `E87-11.1.0.3-<BUILD-ID-PREFIX-OR-FULL>.qix`
- `manifest.json`
- `SHA256SUMS`

The receipt must bind chip `AC707N`, profile `E87-JD9855-R1`, layout `SINGLE_BANK`, a canonical three-part firmware semver, a 16-byte uppercase hexadecimal build ID, Qix version `11.1.0.3`, and explicit `labEligible: true`. `releaseEligible` is independent and must also be an explicit Boolean. The six `files` records appear in role order `appBin`, `jlIsdFw`, `updateUfw`, `qix`, `manifest`, `sha256Sums`; every record binds the bare filename, positive byte length, and uppercase SHA-256.

`SHA256SUMS` contains the other five delivery files, sorted by ordinal filename, as uppercase `HASH *filename` lines. The receipt itself is canonical `json.dumps(..., ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\\n"`. The committed JSON Schema documents the surface; `e87_embed.py` is the executable authority and additionally enforces field relationships, file caps, exact inventory, symlink rejection, Qix magic/type/version/reserved bytes/length/CRC, and byte-for-byte equality between the Qix payload and `update.ufw`.

Packaging integration is machine-testable with:

```sh
/usr/bin/python3.11 android-controller/scripts/prepare-e87-firmware.py \
  --release /absolute/path/to/handoff \
  --output /absolute/temporary/output
```

Exit zero plus a canonical `e87-embed-provenance.json` is the handoff acceptance signal. The output must be disposable; Android Gradle regenerates it. Do not commit either generated assets or firmware bytes.

Build the firmware-free controller normally. A debug build ignores the firmware property and never packages `assets/e87`:

```sh
cd android-controller
bash ./gradlew clean testDebugUnitTest lintDebug assembleDebug
```

Build the explicitly qualified lab variant only from an accepted absolute handoff path:

```sh
bash ./gradlew -Pe87FirmwareRelease=/absolute/path/to/handoff \
  clean testLabQualifiedUnitTest lintLabQualified assembleLabQualified
```

Before installation, audit the exact APK and create a path-independent, create-only receipt:

```sh
/usr/bin/python3.11 scripts/verify-apk.py \
  --apk /absolute/path/to/app-labQualified.apk \
  --release /absolute/path/to/handoff \
  --aapt /absolute/path/to/android-sdk/build-tools/34.0.0/aapt \
  --dexdump /absolute/path/to/android-sdk/build-tools/34.0.0/dexdump \
  --receipt /absolute/new/path/apk-audit.json
```

Installation and installed-byte verification require the Redmi's explicit `adb` serial. Both commands re-run the complete offline audit before contacting that serial, and every `adb` invocation includes `-s <serial>`:

```sh
/usr/bin/python3.11 scripts/install-apk.py --serial <redmi-serial> \
  --apk /absolute/path/to/app-labQualified.apk --release /absolute/path/to/handoff \
  --aapt /absolute/path/to/aapt --dexdump /absolute/path/to/dexdump \
  --adb /absolute/path/to/adb --receipt /absolute/new/path/install.json

/usr/bin/python3.11 scripts/verify-installed-apk.py --serial <redmi-serial> \
  --apk /absolute/path/to/app-labQualified.apk --release /absolute/path/to/handoff \
  --aapt /absolute/path/to/aapt --dexdump /absolute/path/to/dexdump \
  --adb /absolute/path/to/adb --receipt /absolute/new/path/installed-audit.json
```
