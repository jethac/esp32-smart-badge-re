# E87 Packaging and Target Build Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reproduce the pinned AC707N SDK/toolchain environment, compile the E87 application and loader, and emit self-describing lab packages whose bytes, source inputs, and hardware eligibility can be independently verified before a badge is touched.

**Architecture:** PowerShell bootstrap scripts acquire and hash the Windows-only PI32 toolchain while Python owns canonical manifests, package parsing, deterministic identifiers, and validation. Every target build happens in a fresh generated SDK checkout assembled from one immutable upstream commit plus the repository overlay/patch set; generated build trees and outputs never become source inputs.

**Tech Stack:** PowerShell 7/Windows PowerShell 5.1, Python 3.11/pytest, Git, JieLi PI32v2/r3 tools, pinned JieLi AC707N SDK, SHA-256, canonical UTF-8 JSON, Qix CRC16-CCITT, JieLi UFW container validation.

**Spec:** `docs/superpowers/specs/2026-08-27-e87-local-rendering-trial-design.md`

## Global Constraints

- SDK source is exactly `https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200.git` commit `d0167685d032d745d88fe50233302edd46941622`, tree `854734595be49510aca5afb89f5885e8bce6a00f`. Never build from the damaged `.tmp-jieli-e-badge-707-sdk` checkout.
- The official PI32 installer is `https://jl-update.oss-cn-shenzhen.aliyuncs.com/2.5.2.exe`, size `52840808`, SHA-256 `1EC78E3315A5987D4E82ECD002536C84240E5C832B1875BEFF7CE55450124EE5`, ETag `316CB0AC05FCF3F1156CEFDD005C018F`.
- A downloaded executable is never launched until length, SHA-256, PE signature status, and installer type checks pass. A log records the signer and signature timestamp. If unattended capability cannot be proved from the installer metadata, the script stops after download/verification and never guesses switches.
- The default compiler root is `C:\JL\pi32`; callers may supply another explicit absolute root. The scripts never search or mutate a home directory.
- SDK checkout, compiler cache, and all outputs live under ignored repository-local `.build`, `.cache`, and `out` paths. Source lockfiles and validators live under `firmware`.
- Target packaging is byte-for-byte deterministic for identical inputs. UTC timestamps in human reports are excluded from canonical build identity and package bytes.
- `buildId` is the first 16 bytes of SHA-256 over `E87-BUILD-ID-V1\0` followed by canonical UTF-8 JSON containing semver, application source commit, scoped source-tree hash, SDK commit/tree, toolchain-tree hash, board-profile hash, asset-manifest hash, linker-layout identity, and target flags.
- The manifest never hashes itself. `SHA256SUMS` covers the manifest and every emitted artifact except `SHA256SUMS` itself and uses uppercase hashes with binary-mode `*filename` lines sorted by ordinal filename.
- The first sacrificial package may be `labEligible: true`; it remains `releaseEligible: false` until the complete hardware ladder has confirmed model-1542 display/power facts. Unknown, inferred, failed, or skipped evidence can never produce a release-eligible manifest.
- The v1 anti-rollback declaration is exactly `none-v1-physical-gate`; chip is `AC707N`, hardware profile is `E87-JD9855-R1`, layout is single-bank, and the normal build-info record contains the same semver/build ID.
- Packaging commands never open a serial port, enumerate a live badge for writing, or invoke `isd_download.exe` against hardware. A disconnected build is the only operation in this plan.

---

## File Map and Stable Interfaces

```text
firmware/
  locks/{sdk.lock.json,toolchain.lock.json,packaging.lock.json}
  schemas/{build-manifest.schema.json,board-profile.schema.json}
  tools/{bootstrap-sdk.ps1,fetch-toolchain.ps1,install-toolchain.ps1,hash-tree.py,build-target.ps1,build-loader.ps1,package_firmware.py,qix.py,ufw.py,validate_release.py,verify-reproducible.ps1}
  tests_py/{test_locks.py,test_hash_tree.py,test_qix.py,test_ufw.py,test_manifest.py,test_target_build_scripts.py,test_reproducibility.py}
out/firmware/E87-JD9855-R1/<semver>/<build-id>/
  app.bin
  loader.bin
  update.ufw
  E87-<semver>-<build-id>.qix
  manifest.json
  SHA256SUMS
  build-report.json
```

Stable command surfaces:

```powershell
.\firmware\tools\fetch-toolchain.ps1 -Destination .\.cache\jieli\2.5.2
.\firmware\tools\install-toolchain.ps1 -Installer .\.cache\jieli\2.5.2\2.5.2.exe -InstallRoot C:\JL
.\firmware\tools\bootstrap-sdk.ps1 -Destination .\.build\e87-sdk
.\firmware\tools\build-target.ps1 -SemVer 0.1.0 -Configuration Lab
.\firmware\tools\verify-reproducible.ps1 -SemVer 0.1.0
```

Stable Python APIs:

```python
def canonical_tree_hash(root: Path, includes: tuple[str, ...]) -> str: ...
def build_id(descriptor: dict[str, object]) -> bytes: ...
def wrap_qix(ufw: bytes, version: str) -> bytes: ...
def unwrap_qix(data: bytes) -> tuple[str, bytes]: ...
def parse_ufw(data: bytes) -> UfwImage: ...
def validate_release(directory: Path, require_release: bool) -> dict[str, object]: ...
```

### Task 1: Pin and verify every external build input

**Files:**
- Create: `firmware/locks/sdk.lock.json`
- Create: `firmware/locks/toolchain.lock.json`
- Create: `firmware/locks/packaging.lock.json`
- Create: `firmware/tests_py/test_locks.py`
- Reconcile: `firmware/sdk.lock.json` into `firmware/locks/sdk.lock.json`

**Interfaces:**
- Consumes: the immutable identities in Global Constraints and hashes of SDK-bundled packaging tools.
- Produces: schema-versioned lockfiles with no mutable branches, latest URLs, or unverified binary entries.

- [ ] **Step 1: Write failing lockfile tests**

Require lowercase 40-hex commits/tree IDs, uppercase 64-hex SHA-256 values, HTTPS origins, exact expected size/ETag, unique logical tool names, and no path outside the repository or `C:\JL`. Assert the SDK lock's commit resolves to the expected tree in a clean checkout.

- [ ] **Step 2: Record the bundled tool identities**

Pin these upstream SDK file hashes:

```text
make.exe                 CD6734001D62DAA472B4CD1284F685213027A35F458E86C04EA3320A3A455225
fixbat.exe               0198A31EF58909A5689440EEF9200EA29185A248A26152ED4FDA13326A1F8931
mkdir_win.exe            6914A50F48C1503411BEFBDABC74D28BDB5D48548B3941B090745E96B16DF5F2
rm.exe                   FEB9517D0B478E62CF6F487BF947956293125B35EF1AA300761A21C2B686832F
isd_download.exe         D581CB0E8EF3EEFBCE1F02F1B02AAE637A239D8713E81D1CD5321339FCEC7A55
json_to_res.exe          FC0CA21F0921074C04FCAEC0E27E5E577845B020AECCD7B9A576ED08086A031C
br35loader.bin           1295A01D5A89AD42E9EDA6B87ACFE7D543AB68293D4087C3DDA9BF9AB472DAE1
ota.bin                  65E57D5197C613EDD1DCC3FFF1C8D0240B2BBFAF57DAD6E8337E33879F776AF3
flash_params_v3.bin      7069536B81DF3377FDE743084302BF2DAE599BB74E98B427EDB50A35FF39CF69
```

- [ ] **Step 3: Implement and run validation**

Run: `py -3.11 -m pytest firmware/tests_py/test_locks.py -q`

Expected: PASS against the committed lockfiles and a clean fetched SDK.

### Task 2: Download and install the verified PI32 toolchain

**Files:**
- Create: `firmware/tools/fetch-toolchain.ps1`
- Create: `firmware/tools/install-toolchain.ps1`
- Create: `firmware/tests_py/test_target_build_scripts.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `toolchain.lock.json` and an explicit destination/install root.
- Produces: a verified cached installer, `toolchain-install-report.json`, and a usable `C:\JL\pi32` or a precise nonzero failure before execution.

- [ ] **Step 1: Write static and negative-path tests**

Assert TLS-only download, exact content-length/hash checks, `Get-AuthenticodeSignature` with `Status -eq 'Valid'`, no `Invoke-Expression`, no shell-built command line, no wildcard deletion, and an explicit `-WhatIf` mode. Corrupt/truncated test installers must fail before `Start-Process` is reachable.

- [ ] **Step 2: Implement resumable download and verification**

Download to a `.partial` file, atomically rename only after exact verification, and reuse a verified cache. Capture URL, ETag, length, digest, signer subject, signature status, and retrieval UTC in the report. Retrieval time is evidence only, not a build-identity input.

- [ ] **Step 3: Implement guarded installation**

Read the PE version resources and binary marker strings. Permit `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=C:\JL` only when the binary identifies itself as Inno Setup; otherwise return exit code 12 with the verified installer path for an interactive launch. Use `Start-Process -Wait -PassThru` with an argument array and a visible window only for the user-required interactive fallback. After installation, require the expected compiler executables and hash the entire compiler root.

- [ ] **Step 4: Fetch/install and prove compiler execution**

Run the fetch script, then the guarded installer. Compile and link a minimal AC707N object through the same executables that the SDK Makefile resolves. Store stdout/stderr and compiler versions in the install report.

### Task 3: Materialize a pristine, scoped SDK build tree

**Files:**
- Create: `firmware/tools/bootstrap-sdk.ps1`
- Create: `firmware/tools/hash-tree.py`
- Create: `firmware/tests_py/test_hash_tree.py`

**Interfaces:**
- Consumes: SDK lock, repository patches/overlay, and an empty explicit destination.
- Produces: a detached clean SDK at the pinned commit plus an `e87-overlay-report.json` proving every changed path.

- [ ] **Step 1: Write canonical tree-hash tests**

Test ordinal slash-normalized paths, raw file bytes, executable-bit metadata, empty files, Unicode paths, CRLF/LF distinction, symlink rejection, ignored output directories, and permutation independence.

- [ ] **Step 2: Implement clean bootstrap**

Fetch by exact commit, verify commit/tree, detach, verify upstream bundled-tool hashes, apply numbered patches in lexical order, copy the overlay with path collision checks, then list the final diff against upstream. Refuse a nonempty destination unless it contains a matching generated-tree marker and `-Recreate` was supplied.

- [ ] **Step 3: Enforce patch scope**

Allow changes only under the explicit E87 overlay destinations and the named SDK integration/linker/charge/BT files. Fail on generated `fileList.mk`, binaries, object files, unrelated apps, or a dirty upstream worktree before overlay.

- [ ] **Step 4: Run bootstrap twice**

Require identical scoped tree hashes and overlay reports apart from absolute build-root fields, which are excluded from identity.

### Task 4: Build the loader and application with map gates

**Files:**
- Create: `firmware/tools/build-loader.ps1`
- Create: `firmware/tools/build-target.ps1`
- Extend: `firmware/tests_py/test_target_build_scripts.py`

**Interfaces:**
- Consumes: verified compiler root and materialized SDK tree.
- Produces: `app.bin`, freshly rebuilt `loader.bin`, ELF/map/listing evidence, command transcript, and no package yet.

- [ ] **Step 1: Write command-graph tests**

Assert prebuild generators execute sequentially before source enumeration, the E87 board define is present exactly once, the loader is rebuilt before application packaging, all subprocess exit codes are checked, stdout/stderr are captured, and no command contains a serial/USB write target.

- [ ] **Step 2: Build the verified loader**

Invoke the SDK's loader target in a pristine tree with the pinned toolchain. Do not copy the stock loader blindly. Record the loader source/tree/compiler inputs and output SHA-256.

- [ ] **Step 3: Build the E87 application**

Use the SDK-bundled `make.exe` and its normal PI32 resolution. Retain ELF, map, listing, and binary. Run `source-audit.py` and `check-map.py`; reject missing entry `0x0C000100`, tail reservation mismatch, update-scratch overlap, heap/stack regression outside the declared budget, forbidden feature symbol, or absent build-info bytes.

- [ ] **Step 4: Prove output stability**

Build in two different absolute directories. ELF debugging paths may differ and are evidence-only; stripped `app.bin` and `loader.bin` must match exactly.

### Task 5: Implement strict UFW and Qix codecs

**Files:**
- Create: `firmware/tools/ufw.py`
- Create: `firmware/tools/qix.py`
- Create: `firmware/tests_py/test_ufw.py`
- Create: `firmware/tests_py/test_qix.py`

**Interfaces:**
- Consumes: target binaries and known-good/corrupt format fixtures.
- Produces: a strictly parsed official-packager single-bank UFW and the exact Qix wrapper accepted by the Android validator.

- [ ] **Step 1: Write corruption-first tests**

Cover every header/table/tail CRC bit, truncated/oversized tables, integer overflow, duplicate/overlapping entries, path-like names, protected-range decoding, wrong chip, wrong loader/application role, dual-bank indicators, embedded-NUL Qix version, length mismatch, trailing bytes, and Qix CRC mismatch.

- [ ] **Step 2: Generate with the official offline packager and implement strict independent parsing**

Invoke the pinned SDK `isd_download.exe` only in its file-output mode corresponding to `-output-fw jl_isd.fw -output-ufw update.ufw`, with no connected badge and no live-device option. Supply the freshly built application/loader/config inputs from the E87 build tree. Follow the recovered 64-byte header, 80-byte entry, CD03 transform, seed-zero CRC, protected-range, and tail-signature rules in the independent Python parser. Reparse the official tool's output and require only the minimal AC707N single-bank members selected by the E87 packaging profile.

- [ ] **Step 3: Implement Qix wrapping**

Emit `BC AF 01`, ASCII semver padded with NUL to ten bytes, little-endian payload length, eight zero reserved bytes, and the little-endian CRC16-CCITT of the UFW payload using polynomial `0x1021`, seed `0xFFFF`, non-reflected, no final XOR; append the UFW only after that 27-byte header. Reject version strings that are empty, non-ASCII, longer than ten bytes, or contain NUL.

- [ ] **Step 4: Cross-check Android fixtures**

Copy generated fixtures through the Android validators and Python parsers; every valid artifact must agree byte-for-byte and every one-bit corruption must fail in both implementations.

### Task 6: Emit a canonical manifest and lab package

**Files:**
- Create: `firmware/schemas/build-manifest.schema.json`
- Create: `firmware/schemas/board-profile.schema.json`
- Create: `firmware/tools/package_firmware.py`
- Create: `firmware/tools/validate_release.py`
- Create: `firmware/tests_py/test_manifest.py`

**Interfaces:**
- Consumes: passed build/map/source results, board and asset manifests, UFW/Qix bytes, and hardware-evidence state.
- Produces: the output directory described in the file map.

- [ ] **Step 1: Write schema and identity tests**

Require exact semver, 16-byte uppercase build ID, chip/profile/layout, artifact filename/type/length/hash, source/toolchain/SDK identities, map budgets, capability bits, anti-rollback policy, evidence states, and eligibility booleans. Reject unknown schema properties, absolute paths, timestamps in identity, self-hashes, and contradictions such as release eligibility with inferred panel wiring.

- [ ] **Step 2: Implement canonical packaging**

Compute the build descriptor and ID before compiling the final build-info record; rebuild the application once with that ID, confirm that all other identity inputs remain unchanged, then package. Use sorted-key compact JSON with UTF-8 and a final LF. Use atomic output-directory rename so a partial package never looks valid.

- [ ] **Step 3: Implement eligibility evaluation**

`Lab` accepts the exact Q87/11.1.0.2 recovery source identity, passed host/container/map tests, and `INFERRED` model-1552 panel profile; it sets `labEligible: true`, `releaseEligible: false`. `Release` additionally requires every mandatory model-1542 hardware evidence item to be `PASS` for the same build ID and otherwise exits nonzero.

- [ ] **Step 4: Validate the complete directory**

Rehash every artifact, reparse UFW/Qix, compare embedded build-info identity, validate JSON schemas, verify `SHA256SUMS`, and reject extra executable/container files not named by the manifest.

### Task 7: Prove reproducibility and deliver the disconnected lab bundle

**Files:**
- Create: `firmware/tools/verify-reproducible.ps1`
- Create: `firmware/tests_py/test_reproducibility.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: two clean build roots and one semver.
- Produces: a byte comparison report and the only firmware directory eligible for the later hardware ladder.

- [ ] **Step 1: Build twice from clean roots**

Run: `.\firmware\tools\verify-reproducible.ps1 -SemVer 0.1.0`

Expected: app, loader, UFW, Qix, manifest, and checksum bytes match; diagnostic logs may differ only in declared environment/evidence fields outside the delivered directory.

- [ ] **Step 2: Run all disconnected gates**

```powershell
py -3.11 -m pytest firmware/tests_py -q
.\firmware\tools\build-target.ps1 -SemVer 0.1.0 -Configuration Lab
py -3.11 firmware/tools/validate_release.py out/firmware/E87-JD9855-R1/0.1.0/<build-id>
```

Replace `<build-id>` in the final command with the directory name emitted by `build-target.ps1`; the script also prints and records the resolved absolute path. Expected: validation reports `labEligible=true`, `releaseEligible=false`, and performs no device I/O.

- [ ] **Step 3: Commit source, locks, tests, and documentation only**

```powershell
git add firmware/locks firmware/schemas firmware/tools firmware/tests_py .gitignore README.md
git commit -m "build(firmware): add reproducible E87 lab packaging"
```

Do not commit `.cache`, `.build`, `out`, compiler files, SDK checkouts, user evidence, or generated files that the source manifest does not explicitly designate.
