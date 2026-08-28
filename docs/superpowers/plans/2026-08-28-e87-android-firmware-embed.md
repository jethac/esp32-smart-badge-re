# E87 Android Firmware Embedding Seam Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fail-closed Android build and runtime seam that embeds only an explicitly lab-qualified AC707N/E87-JD9855-R1 single-bank package, while leaving ordinary debug builds unable to transfer firmware.

**Architecture:** A standard-library Python intake validator consumes an absolute, symlink-free release directory containing a closed `e87-android-embed-v1` receipt plus exactly six hash-bound files. Only the `labQualified` Android build type runs that validator and adds its generated, read-only asset tree; the normal `debug` build has no generated firmware source. Java reopens the closed embedded inventory, rechecks lengths, hashes, canonical receipts, SHA256SUMS, Qix structure/CRC, and Qix/UFW equality before producing `TransitionArtifact`. Independent APK tooling audits permissions, component exposure, embedded bytes, and app-class transfer boundaries.

**Tech Stack:** Python 3.11 standard library, Gradle 8.7/Kotlin DSL, Android Gradle Plugin 8.5.2, Java 8/JUnit 4, Android SDK 34 build tools.

**Spec:** Approved parent-agent brief for `/root/android_firmware_embed` plus `docs/superpowers/plans/2026-08-28-e87-stock-transition-android.md` Task 4, with the explicit approved override that the new seam is implemented before final firmware bytes exist and requires a separate closed handoff receipt.

## Global Constraints

- The handoff receipt is `e87-android-embed-v1`; S0-1 manifests or inferred eligibility never qualify.
- The accepted target is exactly chip `AC707N`, profile `E87-JD9855-R1`, layout `SINGLE_BANK`, with explicit `labEligible: true`.
- No committed placeholder firmware and no filesystem-picker path exist in the APK.
- `assembleDebug` remains firmware-free and `EmbeddedFirmwareRepository` returns `NOT_PACKAGED`.
- Only `labQualified` consumes `-Pe87FirmwareRelease=<absolute-directory>` and fails if it is absent or invalid.
- No task or script contacts a badge; install/verification helpers require an explicit Redmi serial and are not run during implementation.

---

### Task 1: Closed handoff validator and deterministic generated tree

**Files:**
- Create: `android-controller/scripts/e87_embed.py`
- Create: `android-controller/scripts/prepare-e87-firmware.py`
- Create: `android-controller/scripts/e87-android-embed-v1.schema.json`
- Create: `android-controller/scripts/E87-ANDROID-EMBED-HANDOFF.md`
- Test: `android-controller/scripts/tests/test_e87_embed.py`

**Interfaces:**
- Consumes: `prepare --release <absolute-dir> --output <absolute-dir>`.
- Produces: `assets/e87/default-release.json`, six read-only files below the receipt's canonical `releaseRoot`, and `e87-embed-provenance.json` outside the APK asset root.

- [x] Write tests that construct a temporary valid handoff with literal identities and independently computed hashes, then assert exact copied bytes, closed inventory, canonical receipt, stable provenance, and read-only outputs.
- [x] Run the tests and confirm failure because the validator/CLI do not exist.
- [x] Add negative tests for relative/symlinked roots, unknown/duplicate/missing receipt keys or roles, wrong chip/profile/layout, non-true lab eligibility, malformed semver/build ID/path/hash/length, extra files, noncanonical SHA256SUMS, Qix header/version/length/reserved/CRC errors, and Qix/UFW inequality.
- [x] Implement the minimum standard-library validator and atomic clean-output generator; re-read source bytes only once, validate before publication, and emit canonical path-independent provenance.
- [x] Run the focused Python tests green.

### Task 2: Variant-isolated Gradle wiring

**Files:**
- Modify: `android-controller/app/build.gradle.kts`
- Test: `android-controller/scripts/tests/test_gradle_embed.py`

**Interfaces:**
- Consumes: optional Gradle property `e87FirmwareRelease`; it is required only by `embedE87Firmware` and `labQualified` asset/package tasks.
- Produces: `assembleDebug` with no `assets/e87`, and `assembleLabQualified` with only the generated qualified tree.

- [x] Write a functional test that runs clean debug assembly without the property, confirms no E87 assets, confirms lab assembly fails without the property, and builds/audits lab with a temporary qualified fixture.
- [x] Run it RED against the existing one-build-type project.
- [x] Add a `labQualified` build type, generated asset source, and an `embedE87Firmware` Exec task with declared input/output and explicit Python 3.11 selection.
- [x] Wire only lab-qualified asset/package/assemble tasks to the embed task and keep debug independent.
- [x] Run the functional test green.

### Task 3: Runtime revalidation and immutable artifact exposure

**Files:**
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/transition/CanonicalJson.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/transition/TransitionManifest.java`
- Create: `android-controller/app/src/main/java/net/jethachan/factory_badges/transition/TransitionArtifactValidator.java`
- Modify: `android-controller/app/src/main/java/net/jethachan/factory_badges/transition/EmbeddedFirmwareRepository.java`
- Test: `android-controller/app/src/test/java/net/jethachan/factory_badges/transition/TransitionManifestTest.java`
- Test: `android-controller/app/src/test/java/net/jethachan/factory_badges/transition/TransitionArtifactValidatorTest.java`
- Modify/Test: `android-controller/app/src/test/java/net/jethachan/factory_badges/transition/EmbeddedFirmwareRepositoryTest.java`

**Interfaces:**
- Consumes: an `AssetSource` that lists/opens the packaged `e87` namespace.
- Produces: `NOT_PACKAGED` for an absent index, `INVALID_PACKAGE` for every validation or inventory failure, or `READY` with a defensive `TransitionArtifact` carrying exact Qix bytes and 16-byte expected build ID.

- [x] Write tests for a valid in-memory asset tree and every realistic identity/inventory/hash/Qix mutation; assert no artifact and no scanning side effect before complete validation.
- [x] Run the focused JVM tests RED because parser/validator interfaces are absent.
- [x] Implement duplicate-key-rejecting canonical JSON parsing, closed manifest validation, bounded reads, exact recursive inventory checks, SHA256SUMS checks, SHA-256 checks, Qix CRC/structure validation, and immutable artifact construction.
- [x] Update the Android `AssetManager` adapter and retain the existing fail-closed status contract.
- [x] Run focused and complete JVM tests green.

### Task 4: APK audit and serial-required host scripts

**Files:**
- Create: `android-controller/scripts/verify-apk.py`
- Create: `android-controller/scripts/install-apk.py`
- Create: `android-controller/scripts/verify-installed-apk.py`
- Test: `android-controller/scripts/tests/test_verify_apk.py`
- Test: existing Android architecture and maintenance boundary suites

**Interfaces:**
- Consumes: exact APK, exact handoff directory, Android build-tools path, and optional receipt output; install/installed verification additionally require `--serial`.
- Produces: canonical APK audit receipt proving identity/content equality, exact five effective permissions, SDK/application identity, private maintenance activity, no network/location/storage/file-picker references from application classes, and no unapproved transition dependency on the vendor OTA manager.

- [x] Write fabricated-APK and source-boundary RED tests covering extra/mutated assets, forbidden permissions/APIs, exported maintenance, wrong SDK/package, and missing serial arguments.
- [x] Implement offline APK inspection using ZIP plus pinned `aapt`/`dexdump`; implement install/verify wrappers that audit before install and always pass the exact serial to every `adb` command.
- [x] Run script and JVM boundary tests green without invoking either host script against a device.

### Task 5: Full release-seam verification and review

**Files:**
- Verify all files above; do not add firmware bytes.

**Interfaces:**
- Produces: clean commit and independent reviewer verdict.

- [x] Run Python tooling tests.
- [x] Run `testDebugUnitTest lintDebug assembleDebug` offline and prove the debug APK has no `assets/e87`.
- [x] Generate a temporary structurally valid fixture, run `clean embedE87Firmware testLabQualifiedUnitTest lintLabQualified assembleLabQualified`, and audit its APK byte-for-byte.
- [x] Re-run the complete debug/lab gates fresh, inspect `git diff --check` and status, and commit.
- [ ] Dispatch an independent read-only reviewer over `23afc3c..HEAD`; fix every Critical/Important issue and reverify before reporting.
