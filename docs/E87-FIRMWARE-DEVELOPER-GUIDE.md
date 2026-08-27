# E87 / AC707N-BR35 firmware developer guide

**Status:** practical implementation guide for the approved local-rendering v1 trial

**Evidence date:** 2026-08-27

**Primary target:** the sacrificial badge reported as model `1542` (`0x0606`),
using the recovered model-1552 AC707N/BR35 and JD9855 profile only as a labeled
starting point.

This is the handoff for an engineer or coding agent reproducing, porting,
reviewing, packaging, or recovering firmware for this badge family. Read it
with:

- `docs/superpowers/specs/2026-08-27-e87-local-rendering-trial-design.md` —
  approved v1 behavior and acceptance;
- `docs/E87-FIRMWARE-AUTHORING-GUIDE.md` — reverse-engineering evidence and
  primary-source pointers;
- the four implementation plans under `docs/superpowers/plans/` for firmware,
  target packaging, Android, and hardware integration.

### Contract and command reconciliation

The approved specification remains normative for v1 behavior. The plans remain
normative for their file, format, test, and gate contracts except for the exact
surfaces reconciled below. The verified `.superpowers/remote-dev-environment.md`
and later direct project decisions control those replacements.

| Plan surface superseded | Canonical current surface | Consequence |
|---|---|---|
| Badge-firmware Tasks 1–11 `firmware/sdk.lock.json`, PowerShell `.ps1` host surfaces, and Clang harness | `firmware/locks/sdk.lock.json`, Linux `firmware/tools/test-host.py`, `/usr/bin/python3.11`, `/usr/bin/gcc-11`, and the phased Linux commands in sections 11/13 | Preserve the behavioral/test contracts, but never create the stale root lock or treat a `.ps1` command as canonical. |
| Packaging Tasks 1–7 Windows installer, `C:\JL`, PowerShell bootstrap/build/reproducibility commands, and SDK-bundled Windows packaging tools | The pinned native Linux SDK, compiler, linker, and post-tools in sections 3–4, plus the future native CLI/receipt contract in section 11.3 | The old commands are historical design input, not a fallback. The native wrapper is an open release blocker. |
| Packaging plan file map places `build-report.json` in the delivered directory | Deliver exactly the six files in section 11.2; keep reports, receipts, ELF/map/listing, and transcripts in external evidence | This latest decision resolves the plan's own reproducibility conflict: only nondelivered diagnostics may vary. |
| Android plan's local Corretto/Windows command surface and direct execution of mode-0644 `gradlew` | Digest-pinned Java 21 container and `bash ./android-controller/gradlew` | Use the command in sections 3 and 13. |
| Android plan's SAF-selected adjacent Qix/UFW and validation “before any BLE connection” | Exact six-file firmware release embedded byte-for-byte in the APK; artifact validation only before maintenance scan/connect; normal Sync has no artifact dependency | The APK-only route and its current open sender blocker are defined in section 12.1. |
| Authoring-guide asset warning at its lines 339–341 and older firmware Task 5 Devin wording/digest | The current `assets/icons/devin.svg` commit/blob/SHA-256 pin in section 7.3 | The corrected asset is the source; do not resurrect the removed cog. |
| Windows-only generic USB evidence capture | Linux-native remote evidence capture, whose exact CLI remains **UNVERIFIED**; Windows is restricted to final verified-APK/ADB evidence | Do not make `capture-usb.ps1` a canonical firmware or recovery dependency. |

Do not mix a superseded command or path with a current contract. If a future
implementation changes one of these surfaces, update the plans, locks, schemas,
and this table together before calling the result reproducible.

`README.md`, `NOTES.md`, and `docs/OTA-RESEARCH.md` preserve useful chronology,
but their AC697/BR30 and stock JPEG-transfer conclusions predate the recovered
AC707N/BR35 evidence. Preserve them; do not use them as the v1 contract.

## 1. Evidence and decision discipline

Use these labels in comments, board profiles, manifests, and reports:

- **PROVEN** — repeatably measured on the target, decoded from a validated exact
  artifact, or stated by pinned official source.
- **INFERRED** — supported by neighboring-model evidence or compatibility
  testing, but not measured directly on untouched model-1542 hardware.
- **UNVERIFIED** — unresolved electrical, timing, layout, or behavioral value;
  it cannot become release-eligible without the named bench test.
- **V1 DECISION** — required by the approved trial even if its hardware path is
  not yet proven. A decision is not evidence that the board supports it.

For facts, prefer repeatable target measurement, exact-model artifact,
validated neighboring-model artifact, pinned official generic SDK, community
implementation, then inference. For behavior, the approved trial spec controls
v1; later plans may make an explicit fail-closed choice where it is silent.

Never promote a board field because an image booted. BLE transfer success proves
transport, not panel, calibration, partition, power, or resource compatibility.

### 1.1 Non-negotiable boundaries

- Keep one badge untouched and write only the explicitly sacrificial unit.
- Do not assume products sold as `E87`, `L8`, or `B-431` share a PCB.
- Never substitute generic GC9B71 or dormant JD5858 panel profiles.
- Never expose erase, format, arbitrary write, or permanent-key operations in a
  general recovery tool.
- Keep bond keys, provisioning secrets, signing material, and device keys out of
  source, packages, and logs.
- V1 stays single-bank; A/B requires a later wired full-repartitioning design.
- A physical gesture exposes maintenance; it never jumps directly to an
  uninitialized loader.
- Host tests, a cross-build, and hardware proof are three separate claims.

## 2. Exact v1 contract

| Surface | Exact decision |
|---|---|
| Chip/profile | AC707N/BR35, `E87-JD9855-R1`, entry `0x0C000100` |
| Display | 368x368 RGB565, center `(184,184)`, radius 180; two 16-row buffers; no framebuffer/PSRAM dependency |
| Normal BLE | Name `E87`; service `e87d0001-7a1b-4c62-9f0b-5d9c01a70735` |
| State write | `e87d0002-7a1b-4c62-9f0b-5d9c01a70735`, encrypted non-MITM write-with-response, exactly 8 bytes |
| Build info | `e87d0003-7a1b-4c62-9f0b-5d9c01a70735`, exactly 40 bytes |
| State | Day/Week `0..100`, credit exactly 1727 cents, complete idempotent snapshot; no sequence/CRC |
| Pairing | Just Works; one owner; new peer only in physical 60-second window |
| Button 1 | tap battery; 3 s pair; 7 s warning; 10 s app maintenance; hung runtime PB08 reset at 16 s |
| Button 2 | only ordinary sleep/wake control; no inactivity timeout |
| Charging | electrical charge/safety retained; no stock charge page/mode or charger-triggered sleep |
| Maintenance | `E87 UPDATE`; AE00; AE01 write-without-response; AE02 notify plus CCCD; physical/RCSP-authenticated gate |
| Rewrite | verified loader before `update_mode_api_v2()`; same-hash resume after handoff |
| Assets | compiled deterministic masks/glyphs; no UIRES/filesystem UI/JLUI/LVGL/touch/audio/phone-rendered pixels |

### 2.1 Semantic packet

```text
offset size meaning
0      1    version = 1
1      1    Day = 0..100
2      1    Week = 0..100
3      1    flags = 0
4      4    uint32 little-endian credit = 1727 (BF 06 00 00)
```

Android always emits `01 DD WW 00 BF 06 00 00`. Firmware v1 accepts only
`credit_cents == 1727`; any other credit is rejected atomically. Dynamic credit
requires a future protocol version. Decode to a temporary, validate every field,
then commit once. Invalid data leaves caller output and visible state untouched.
A duplicate valid snapshot is acknowledged without redraw.

Do not copy the older generic proposal that added length, sequence, and CRC.

### 2.2 Build-info record and encrypted-read gate

```text
offset size meaning
0      1    schema = 1
1      1    capabilities = 0x07
2      16   ASCII `E87-JD9855-R1`, NUL padded
18     3    semver major/minor/patch
21     1    reserved = 0
22     16   raw content-derived build ID
38     2    reserved = 0
```

Capability bits 0, 1, and 2 mean semantic metrics, Battery Service, and physical
RCSP rewrite. All others are zero. The gate is Android-owned: after every
connection and update reboot, Android connects, obtains link encryption, reads
and reconstructs exactly 40 bytes, validates every field, and only then enables
or attempts Sync.

Firmware does not remember a prior read and does not treat that read as an
authorization transition. Its build-info callback independently requires an
encrypted read. Its state-write callback independently requires an encrypted
owner connection, offset zero, exactly eight bytes, and valid v1 semantics, then
commits atomically. Thus a client that skips build-info violates the Android
workflow, while firmware still rejects or accepts the write solely from the
write transaction's own security and validation inputs.

## 3. Minimum viable clone workflow

```sh
git clone https://github.com/jethac/factory-android-badges.git
cd factory-android-badges
git checkout <reviewed-e87-commit>
git rev-parse HEAD
git status --short
```

Bind a lab manifest to a reviewed commit, not a floating branch. Never reuse a
dirty SDK or another agent's generated build tree.

Run the accepted native host gate with all executable identities enforced:

```sh
/usr/bin/python3.11 firmware/tools/test-host.py \
  --suite all \
  --cc /usr/bin/gcc-11 \
  --require-compiler-sha256 821AF3C74506283C179CA413BB33E6B528805A4DD8A5C09DF125E5AD560A9E89 \
  --verify-reproducible
```

The canonical target host is Linux-native `stadia-testbed`. Verify the clean SDK
identity, raise the descriptor limit, and expose the pinned post-build tools.
The custom generated-SDK root is deliberately guarded because its native
bootstrap/receipt command is not yet approved:

```sh
git -C /home/jethac/.local/share/e87-dev/sdk/e_badge_707_sdk_200 \
  rev-parse HEAD 'HEAD^{tree}'
ulimit -n 8192
export PATH=/home/jethac/.local/share/e87-dev/jieli-post-build:$PATH
: "${E87_GENERATED_SDK_ROOT:?native bootstrap receipt required}"
make -C "$E87_GENERATED_SDK_ROOT/SDK" \
  TOOL_DIR=/home/jethac/.local/share/e87-dev/jieli/pi32v2/bin \
  RUN_POST_SCRIPT=true VERBOSE=0 -j6
```

`RUN_POST_SCRIPT=true` is only a compiler/linker smoke route; it is not release
packaging. Release packaging must call the pinned native `isd_download`,
`fw_add`, and `ufw_maker` offline through repository tooling, validate every
output independently, and never perform a direct USB download.

**OPEN RELEASE BLOCKER — native bootstrap/package CLI:** no approved executable
yet implements the Linux-native workflow. Its required input contract is:

- reviewed repository commit and scoped source-tree hash;
- `firmware/locks/{sdk,toolchain,packaging}.lock.json`;
- validated board profile and both schemas in `firmware/schemas/`;
- semver, build configuration, overlay, ordered patches, asset manifest, and an
  empty explicit output root.

The CLI must verify every executable/archive/SDK identity, refuse a dirty SDK,
materialize an isolated generated SDK, collision-check the overlay, apply
patches in ordinal order, and emit a receipt containing the SDK commit/tree,
lock hashes, tool hashes, source/overlay hashes, patch order, and generated-root
diagnostic. It must then build the loader/application, run source/map/package
gates, invoke the three pinned post-tools only in offline file-output mode, and
atomically emit the exact release directory from section 11.2. Diagnostics and
the generated-root path are evidence, never build-identity inputs.

The CLI's outputs are the six deterministic release files in section 11.2 plus
an external receipt, ELF/map/listing, command transcript, and validation report.
It must exit nonzero before publishing on an identity, build, map, package,
schema, or reproducibility failure. Its final command name and argument syntax
are an explicit implementation choice that must be frozen in tests and this
guide. Until it exists and succeeds, `releaseEligible=false`; the historical
Windows scripts are not a fallback.

Build Android in the verified Java 21 container. The wrapper is mode 0644, so
invoke it through `bash`:

```sh
docker run --rm --user 1000:1000 \
  -e HOME=/e87/home \
  -e ANDROID_HOME=/e87/android-sdk \
  -e ANDROID_SDK_ROOT=/e87/android-sdk \
  -v /home/jethac/.local/share/e87-dev:/e87 \
  -v /home/jethac/workspaces/factory-android-badges-e87:/workspace \
  -w /workspace eclipse-temurin@sha256:ce5767b7222312d42395f5bab033cd91f09e44032a2f21bdfd7b5b912dbe1e77 \
  bash ./android-controller/gradlew -p ./android-controller --no-daemon \
  clean testDebugUnitTest lintDebug assembleDebug
```

The Java image resolves to
`eclipse-temurin@sha256:ce5767b7222312d42395f5bab033cd91f09e44032a2f21bdfd7b5b912dbe1e77`.

The command above is only the current diagnostic project gate. After its tasks
exist, the first strict embedding build uses:

```sh
bash ./android-controller/gradlew -p ./android-controller --no-daemon \
  --dependency-verification=strict \
  -Pe87FirmwareRelease=/workspace/out/firmware/E87-JD9855-R1/<semver>/<build-id> \
  clean embedE87Firmware testDebugUnitTest lintDebug assembleDebug
```

`embedE87Firmware` must run after `clean`, consume the exact validated six-file
release directory, and register its generated assets as an input to
`assembleDebug`. It must not fetch or rewrite firmware. The task, its backing
`android-controller/scripts/embed-firmware.py`, and the sender in section 12.1
are not implemented in the current tree. Therefore this command is a frozen
future interface, not a present success claim, and an APK-only first transition
remains blocked. Even after it succeeds, section 12.2's second network-disabled
offline build and both APK audits are mandatory before handoff.

The canonical locks are `firmware/locks/sdk.lock.json`,
`firmware/locks/toolchain.lock.json`, and
`firmware/locks/packaging.lock.json`. No package is presently lab-eligible while
the native wrapper and schemas are absent. `labEligible=true` is a possible
validator result only after exact `Q87/11.1.0.2` recovery-source identity and all
host, container, real-map, and package gates pass. `releaseEligible` remains
false while the wrapper is missing/failing and throughout the sacrificial
write-only exception; a later release also needs every required hardware gate.

Windows is only the final verified-APK/ADB handoff host. Do not use Wine or the
Windows `2.5.2.exe` for firmware development. Copy only the final audited APK.
Do not copy SDKs, source trees, loose Qix/UFW/release files, build caches, logs,
or intermediate APKs to Windows; firmware carriage is inside that APK.

## 4. Pinned remote SDK and Linux toolchain

| Input | Required identity |
|---|---|
| SDK URL | `https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200.git` |
| SDK path | `/home/jethac/.local/share/e87-dev/sdk/e_badge_707_sdk_200` |
| SDK commit | `d0167685d032d745d88fe50233302edd46941622` |
| SDK tree | `854734595be49510aca5afb89f5885e8bce6a00f` |
| Target | `pi32v2`, CPU `r3`, entry `0x0C000100` |
| Linux toolchain URL | `https://jl-update.oss-cn-shenzhen.aliyuncs.com/jieli-linux-toolchains-20250805.1.tar.xz` |
| Linux toolchain bytes | `26,009,040` |
| Linux toolchain SHA-256 | `F686586BCFB45E0F0BB27FD2B39C7A7F313CB4F0E88A66A14DA621FFA8225958` |
| Linux toolchain ETag | `22A619513462ABFC4D86ED50B2922EF7` |
| Linux toolchain path | `/home/jethac/.local/share/e87-dev/jieli` |
| Post-tools URL | `https://jl-update.oss-cn-shenzhen.aliyuncs.com/jieli-linux-post-build-tools-20260728.1.tar.xz` |
| Post-tools bytes | `41,151,180` |
| Post-tools SHA-256 | `F4A458738C5EEC32E78377C76B346BCAC1CD515B03EDA2B7EB11AB183298A858` |
| Post-tools ETag | `C66A27CA807D57B7760DCBE0544C5092` |
| Post-tools path | `/home/jethac/.local/share/e87-dev/jieli-post-build` |

Verify archive size and SHA-256 before extraction; ETag is corroboration only.
The toolchain archive name says 2025-08-05 while its internal directory says
`jieli-linux-toolchains-20250324.1`; the payload digest is authoritative.
Observed installed identities include Clang 4.0.1, ELF32-pi32v2 tools,
`isd_download 4.2.79` build `c45787bd64f17e6756779a37cf5266b940f9d175`,
and `ufw_maker 1.1.14`.

Every link runs after `ulimit -n 8192` and passes
`TOOL_DIR=/home/jethac/.local/share/e87-dev/jieli/pi32v2/bin`. Put the pinned
post-build directory first on `PATH`. The native compiler smoke produced an
`ELF32-pi32v2` object, and the pinned pristine stock SDK compiled and linked;
that proves the remote target toolchain path, not the custom E87 image.

The generated stock `download.sh` is not a release packager: it references
missing helpers and Windows names. Repository release tooling invokes native
`isd_download`, `fw_add`, and `ufw_maker` only in offline file-output mode,
then validates outputs. It must never address a live badge. Retain the ELF, map,
generated linker script, object inventory, stripped app, rebuilt loader,
transcripts, tool hashes, and validation report.

The Windows `2.5.2.exe` and `C:\JL\pi32` path are historical inspection
inputs only. Do not use them, Wine, or Windows as the E87 firmware build path.

## 5. Hardware and board-profile facts

### 5.1 Product boundary

These three identities must remain separate in the build manifest and lab
evidence. The logical record names below are requirements; the as-yet-unwritten
`build-manifest.schema.json` must freeze their exact JSON property names.

| Manifest-facing identity | Exact value and scope | Required treatment |
|---|---|---|
| `physical-target` | Sacrificial badge reports model `1542`, model ID `0x0606`, original version `11.1.0.3` | Record the unit role and observed identity. Exact untouched flash/board remain unavailable; do not promote the target from the package evidence below. |
| `reference-package` | Model `1552`, model ID `0x0610`, project `QX7413_E87_EN`, outer version `11.1.0.2`; it booted on the test unit as `Q87` and bound with wrong resources | Record provenance of the neighboring package and every inferred profile field. This is not model-1542 identity or a bit-perfect target backup. |
| `lab-recovery-source` | Exact eligibility token `Q87/11.1.0.2` from the accepted Lab packaging rule | Use only as the recovery-source gate for `labEligible=true`; it does not rename the physical badge or prove the 1542 layout. |

None of those records is interchangeable or collapsible. A manifest that copies
the 1552/Q87 package identity into the physical-target record, or treats the Lab
token as exact-board evidence, is invalid. Model 1558 / `0x0616` is a
**PROVEN** comparison package only and is never a model-1542 recovery image.

`jl_sdk_ac697_publish` is lineage text, not chip identification. The validated
AC707N boot supersedes the earlier BR30 hypothesis. Exact package marking and
dormant PSRAM remain **UNVERIFIED** until the board is read.

### 5.2 BR35 memory

The generic rows below are **PROVEN for the pinned generic link**. The custom
E87 reservation that follows is a **V1 DECISION** and must be proved in its map.

| Region | End-exclusive range | Size |
|---|---:|---:|
| Main SRAM | `0x100000..0x137000` | 220 KiB |
| Mask/IRQ | `0x100000..0x10054C` | `0x54C` |
| Application RAM | `0x10054C..0x136E00` | 223,412 B |
| Generic LCD tail | `0x131E00..0x136E00` | `0x5000` |
| Update scratch | `0x136E00..0x137000` | `0x200` |
| Reclaimed D/I-cache | `0x372000..0x378000`, `0x3C4000..0x3C8000` | not generic heap |
| PSRAM | origin `0x08000000`, selected length zero | firmware must not depend on it |
| XIP application | `0x0C000100` | required entry |

Required custom E87 tail (**V1 DECISION**, not an observed generic placement):
the linker expands the generic tail downward and must prove it does not overlap.

```text
buffer A  0x130E00..0x133C00  0x2E00
buffer B  0x133C00..0x136A00  0x2E00
slack     0x136A00..0x136E00  0x0400
scratch   0x136E00..0x137000  0x0200
```

Fail unless PSRAM use is zero, entry/bounds match, heap is at least the declared
`0x8000`, measured task stacks pass, and no `368*368*2` object exists. Account
for Bluetooth/GPU users of reclaimed cache RAM section by section.

### 5.3 Flash boundary

The decoded model-1552 map is UIRES `0x180000..0x2DE000`, user/config
`0x2DE000..0x306000`, watch `0x306000..0x307000`, and internal NOR filesystem
`0x307000..0x7FF000`. It is **PROVEN for 1552 and UNVERIFIED for untouched
1542**. Do not preserve/overwrite a friendly region name until exact capacity,
partition metadata, and bounds are measured. The generic template overruns
8 MiB and is not a product map.

V1 preserves the observed single-bank contract. A/B is a separate wired
repartitioning project; single- and dual-bank layouts cannot OTA-migrate safely.

### 5.4 Display

The qualifying model-1552 plaintext `app.bin` is 995,584 bytes with SHA-256
`A38B77E27B1DC73CAE0FBD8A7C4E3A04C64FF393FB4F27BC92A7578336BE0147`.
**PROVEN in that exact app:** geometry 368x368, RGB565, two-pixel alignment,
radius 180; descriptor `jd9855` at `0x0C0EF788`; init at
`0x0C0E59E0`, length 657, SHA-256
`BB0767D3E0BF4AD982725C6A38A9168DDF9E5BA2E3D4D595B1FFBDD17E5B89FF`.
Its tail has TE `35 00`, RGB565 `3A 55`, sleep-out `11` + 120 ms, display-on
`29` + 20 ms.

For model 1542, controller identity is **INFERRED** and these remain
**UNVERIFIED**: bus submode/framing, clock/fps/polarity, all pins/levels/rails,
MADCTL/orientation, RGB/BGR/byte order, window commands/offsets, TE behavior,
and actual reset/sleep/wake timing. Keep each field labeled in
`E87-JD9855-R1.json`; do not flash a display build while a required pin/rail is
an unreviewed guess. Start with display-off heartbeat, then conservative
color bars under current limiting and logic capture.

### 5.5 Buttons and PINR

Model-1552 configuration uses one PB08 ADC ladder: pull-up 1000, scale 4096,
nominal resistors 100/330, predicted keys near 372/1016 and both near 292.
Configuration is **PROVEN for 1552**; model-1542 electrical clusters and physical
labels are **UNVERIFIED**. Measure released, each key, and both keys across
units, voltage, and temperature. Stock aliases the chord to key 0; custom E87
maps the measured both-buttons cluster to `AMBIGUOUS` and has no `CHORD` enum.

PB07 and PB08 are sequential PINR0 owners: packaged PB07/8 s, early disable,
then stock PB08/8 s. E87 disables inherited PB07 and stock PB08/8 s, then custom
code owns PB08/16 s. Verify generated INI, packed `cfg_tool.bin`, runtime API
argument, and physical behavior.


## 6. Firmware architecture and source layout

Treat the vendor SDK as a pinned, external build input. Product code is an overlay
whose paths match the clean SDK:

```text
firmware/
  overlay/SDK/apps/watch/
    e87/
      e87_app.c
      e87_state.c
      e87_button_fsm.c
      e87_recovery.c
      e87_build_info.c
      e87_battery.c
      e87_power_policy.c
      e87_charge_adapter.c
      e87_renderer.c
      e87_panel_jd9855.c
      e87_lcd_stream.c
      e87_sleep.c
      e87_gatt_db.c
      e87_ble_control.c
      e87_bond_policy.c
      e87_ble_mode_fsm.c
      e87_rcsp_profile.c
      e87_maintenance.c
    include/e87/
      *.h
    board/br35/board_e87_1542/
      board files, linker overlay, and generated build configuration
  assets/
    sources/
    licenses/
    asset-lock.json
    requirements.in
    requirements.lock
  board-profiles/
    E87-JD9855-R1.json
  generated/
  locks/
    sdk.lock.json
    toolchain.lock.json
    packaging.lock.json
  schemas/
    build-manifest.schema.json
    board-profile.schema.json
  tools/
    test-host.py and deterministic build/asset/map/package tools
  host/
    suites.json, test harness, cases, and fakes
  tests_py/
  patches/
```

Keep the external SDK checkout clean and generate an isolated SDK worktree by
applying the pinned overlay and patches. Application state transitions remain
pure enough to host-test. SDK callbacks translate into narrow events; application
modules do not reach into arbitrary SDK globals. Adapters normalize stack return
codes, connection handles, charger callbacks, display DMA callbacks, and sleep APIs.

The normal firmware image should omit unused stock subsystems such as Classic
Bluetooth/SPP, TWS, media playback, stock UI pages, stock inactivity policy, and
the stock charge gauge. Remove them through configuration or tightly scoped
patches and confirm the linker map; do not assume dead stripping removed them.

Recommended ownership:

| Module | Owns | Must not own |
|---|---|---|
| `e87_state` | semantic decode/validation, synchronized atomic commit, metrics, revision | presentation policy, ATT/security/owner transport checks, or hardware calls |
| `e87_renderer` | deterministic scene and dirty/redraw policy | BLE connection policy |
| `e87_gatt_db` / `e87_ble_control` | GATT schema plus ATT/security/owner/transport validation; dispatch to `e87_state_commit` | semantic partial mutation, revision ownership, or screen geometry |
| `e87_bond_policy` | owner bond and reconnect advertising | semantic state |
| `e87_button_fsm` | debouncing and tap/hold classification | stock reset callbacks |
| `e87_power_policy` | active/manual-sleep transitions | charger UI |
| `e87_charge_adapter` | external-power and charge-state inputs | an automatic charge page |
| `e87_recovery` | PB08 16-second pin-reset and reset-source route | normal semantic writes |
| `e87_maintenance` | separately gated update service | normal-mode reachability |
| platform adapters | vendor SDK calls and ISR/callback translation | business policy |

Event handlers must be short and non-blocking. Queue or coalesce display work
outside BLE, charger, ADC, and DMA interrupt context. One state owner serializes
semantic updates, button actions, and power events.

## 7. Display and rendering pipeline

### 7.1 Strip-buffer discipline

The target is a 368 x 368 RGB565 scene. A full framebuffer consumes 270,848
bytes and does not fit the proven free tail. V1 therefore uses 16-row strips:

- 368 x 16 x 2 = `0x2E00` bytes per strip;
- two `0x2E00` buffers occupy `0x5C00` bytes;
- 23 strips cover 368 rows exactly;
- buffer A: `0x130E00..0x133C00`;
- buffer B: `0x133C00..0x136A00`;
- reserved slack: `0x136A00..0x136E00`;
- vendor scratch remains `0x136E00..0x137000`.

Render strip N while DMA transfers strip N-1. Do not reuse a buffer until its
exact transfer-complete callback fires. Record transfer ownership explicitly; a
timed delay is not proof. On timeout or callback-order violation, stop the
pipeline and expose a diagnostic instead of writing into an in-flight buffer.

The LCD adapter sets each strip's inclusive window and streams exactly
`368 * rows * 2` bytes in the confirmed byte order. Do not assume stock
`lcd_draw` continues a window across calls; qualify it with a scope trace or use
explicit window/RAM-write commands. Use TE only after polarity/timing measurement.

Sleep entry stops new frames, waits for or aborts active transfer through the
qualified SDK path, issues panel sleep/display-off in confirmed order, then gates
rails/clocks. Wake reverses that sequence and redraws fully. Never cut power in DMA.

### 7.2 Exact v1 face

The 368 x 368 coordinate system is clipped to the physical circle and uses:

- black `#000000` background;
- Day ring radius 160, stroke 22, `#BFC3C7` (`RGB565 0xBE18`);
- Week ring radius 130, stroke 22, `#FFFFFF` (`RGB565 0xFFFF`);
- inactive Day track `#222324` (`RGB565 0x2104`) and inactive Week track
  `#2E2E2E` (`RGB565 0x2965`); each channel is
  `floor((active_channel * 18 + 50) / 100)`;
- clockwise arcs starting at 12 o'clock, round caps, clamped 0..100 values, and
  a seamless 100-percent closure;
- fixed 18 x 18 `today` and `date_range` icons centered at `(184,24)` and
  `(184,54)`;
- a 96 x 96 Devin alpha mask centered at `(184,170)`;
- Roboto Medium, weight 500, width 100, 30 px, with `$17.27` centered at
  `(184,244)`.

The badge-renderer foreground palette is closed. At exactly zero percent, the
Day `today` icon uses `#BFC3C7` over its inactive track and the Week
`date_range` icon uses `#FFFFFF` over its inactive track. For each ring
independently, progress from 1 through 100 percent changes its fixed-position
icon to `#000000` inside the active round start cap. Devin, credit, battery
percentage, and the charging/full bolt use `#FFFFFF`. Primary
status/warning/error text uses `#FFFFFF`; hints, countdowns, progress detail,
and secondary status use `#BFC3C7`. There are no implicit `currentColor`, theme,
red/green/yellow semantic colors, or source-SVG fills at runtime. Asset alpha
masks receive only the listed tint. Golden scenes cover each icon independently
at 0, 1, and 100 percent and prove that positions never move.

All compositing occurs per RGB888 channel in a `uint32_t` accumulator before one
final RGB565 truncation (`R >> 3`, `G >> 2`, `B >> 3`). For source channel `s`,
destination `d`, and mask/coverage `a` in `0..255`, use exactly:

```text
blend(s, d, a) = floor((s*a + d*(255-a) + 127) / 255)
```

No gamma conversion, dithering, premultiplied-alpha shortcut, or intermediate
RGB565 round-trip is allowed. Render the underlying scene completely, then a
Button 1 tap applies a black overlay with alpha 191 to every pixel
(`blend(0, d, 191)`) and draws the full-brightness overlay foreground on top.
The overlay lasts exactly 2,500 ms. It shows the current integer percentage only
for a valid battery sample, or the stale/fault or unavailable/fault state from
section 9.2; a bolt appears only for charging/full. It then restores the prior
scene. Golden tests cover opaque, zero-alpha, edge-coverage, dimmed-edge, and
channel-rounding vectors.

Geometry, palette, compositing, and UI strings belong in machine-readable locks
and golden vectors.

Freeze the transient strings exactly:

- no bond: `PAIR ME NOW` plus the Button 1 hold hint;
- bonded but no values since boot: `WAITING FOR PHONE`;
- pairing window: `PAIRING` plus its countdown;
- seven-to-ten-second warning: `KEEP HOLDING FOR UPDATE` plus its countdown;
- maintenance: `READY TO UPDATE — RELEASE BUTTON` plus battery,
  connection/progress, and error state.


No floating-point rendering is required. Use fixed-point/integer arithmetic,
pre-rasterized glyph coverage where appropriate, and deterministic RGB565
conversion. Clip every primitive to strip/screen bounds. Host tests render
sentinel states, hash raw RGB565, and emit PNG previews for review.

### 7.3 Deterministic assets and provenance

All generated assets must reproduce from committed source plus pinned tooling.
Store the command, source/output digests, dimensions, format, and provenance.
Generated C arrays have stable order and no timestamp or absolute path.

The pinned `assets/icons/devin.svg` source is exact:

- source: `jethac/factory-smartscreen@3feec00b8a9aa8c6874ca92477e4ed43098e3b84`,
  path `assets/icons/devin.svg`;
- Git blob: `0a11af513a7d208c2c49f33ab2d2d38fd4aefe90`;
- SHA-256: `0B77AF4A730199892F15D99E9B812A39452554089811E46D925E62C09E09A4A9`;
- provenance: traced from `app.devin.ai/assets/pwa/pwa-icon-512.png` and checked
  against the original in `jethac/factory@2720aaf58a9d86a5142fd86dfb05ecb39d31364d`.

The repository's `assets/icons/README.md` and current firmware plan pin this same
corrected source, digest, and blob. The pathname alone is insufficient.

### 7.4 Panel facts versus open qualification

The model-1552 firmware has a `jd9855` descriptor at `0x0C0EF788`. Its 657-byte
init table starts at `0x0C0E59E0` and has SHA-256
`BB0767D3E0BF4AD982725C6A38A9168DDF9E5BA2E3D4D595B1FFBDD17E5B89FF`.
The tail has TE `35 00`, RGB565 `3A 55`, sleep-out `11` plus 120 ms, and
display-on `29` plus 20 ms.

This stock-model evidence does not prove the exact 1542 board. Panel pins, bus
mode, clock ceiling, reset delays, polarity, orientation, RGB/BGR order, window
offsets, TE wiring/polarity, backlight behavior, and 1552-table electrical safety
are **UNVERIFIED**. Do not encode guesses in a production profile. Qualify under
current limiting against an untouched reference with logic captures and staged
low-rate patterns before enabling the full renderer.

### 7.5 Remaining asset and tool locks

Pin every other source just as strictly:

| Asset | Source commit | SHA-256 |
|---|---|---|
| Roboto variable font | `google/fonts@6a003b5eb672dc8bf5bff5937cf5863f8b175445`, `ofl/roboto/Roboto[wdth,wght].ttf` | `D7598E12C5DBEF095FF8272CFC55DA0250BD07FBDECBAC8A530B9B277872A134` |
| `today` rounded | `google/material-design-icons@e083cc60a0828fdd3b404cea0cb8a5b900e9c23e`, `symbols/web/today/materialsymbolsrounded/today_24px.svg` | `C2AA056CC2353CE349BEA6657053370DFBBD38DD96C0E52217615AAF02A1FA04` |
| `date_range` rounded | same commit, `symbols/web/date_range/materialsymbolsrounded/date_range_24px.svg` | `342EF493B1D94132215AB4F25D90CBAB34B448A39F50DB1E929317CE8F28AB04` |
| `bolt` rounded | same commit, `symbols/web/bolt/materialsymbolsrounded/bolt_24px.svg` | `13195A03D22906CA3C7A78FC6E104CB269B98DDAC7DCA96C424FADC623C33F3C` |

`firmware/assets/requirements.in` declares CairoSVG 2.9.0, fontTools 4.63.0, and
Pillow 12.2.0 as direct inputs. It is not an install lock.
`firmware/assets/requirements.lock` must pin the complete transitive closure to
exact versions and attach one or more reviewed `--hash=sha256:...` entries to
every distribution. A dependency present only transitively is still mandatory.
Reject an unhashed line, range, environment-dependent extra, VCS/local/editable
reference, sdist, or wheel with the wrong Python/ABI/platform tag.

The externally populated wheelhouse lives under
`/home/jethac/.local/share/e87-dev/asset-wheelhouse` and is a read-only root in
`firmware/locks/toolchain.lock.json`. The lock records every wheel filename,
length, SHA-256, and the complete ordinal tree digest. Installation uses both
`--require-hashes` and `--no-index`; no release command may generate/update the
lock or fetch a missing wheel.

The asset container is the pinned base
`python@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b`
(Python 3.11.16). The toolchain lock must additionally record architecture,
Python executable hash, every imported native extension hash, and the resolved
`ldd` closure and hashes for Cairo, FreeType, libpng, zlib, libjpeg, libc, and
their actual dependencies. A missing library, unrecorded soname, changed target
behind a symlink, or hash mismatch fails before rendering. The image digest alone
does not replace this native-identity inventory.

The frozen network-disabled execution shape is:

```sh
docker run --rm --pull=never --network=none --read-only --user 1000:1000 \
  -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONHASHSEED=0 \
  -e PIP_NO_INDEX=1 -e PIP_DISABLE_PIP_VERSION_CHECK=1 \
  -e LC_ALL=C.UTF-8 -e TZ=UTC \
  --tmpfs /tmp:rw,nosuid,nodev,size=512m \
  -v /home/jethac/workspaces/factory-android-badges-e87:/src:ro \
  -v /home/jethac/.local/share/e87-dev/asset-wheelhouse:/wheelhouse:ro \
  -v /home/jethac/workspaces/factory-android-badges-e87/firmware/generated/assets:/out \
  -w /src \
  python@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b \
  sh -euc 'python -m pip install --require-hashes --no-index \
    --only-binary=:all: --find-links=/wheelhouse --target=/tmp/site \
    -r firmware/assets/requirements.lock; \
    PYTHONPATH=/tmp/site python firmware/tools/generate-assets.py \
    --native-lock firmware/locks/toolchain.lock.json --output /out'
```

`generate-assets.py` verifies the wheel/native receipt before importing a
renderer. It renders SVG at 8x then area-downsamples, instantiates Roboto axes
`{wght:500,wdth:100}`, emits deterministic alpha masks/metrics, and must produce
byte-identical output in two fresh containers. The transitive wheel hashes and
native library identities do not yet exist in the current tree, so asset output
is an explicit reproducibility/release blocker until they are frozen and pass.


## 8. Normal-mode BLE, bonding, and reconnect policy

Normal mode exposes only the semantic service and minimal standard services
required by the pinned stack. It must not expose raw framebuffer writes,
arbitrary memory access, OTA/update characteristics, a command shell, or stock
vendor control services.
The firmware emitter's exact 26-byte advertisement is a **V1 DECISION** and must
be committed as a golden vector. It contains only flags, the 128-bit E87 service
UUID, and complete name `E87`:

```text
02 01 06 11 07 35 07 A7 01 9C 5D 0B 9F 62 4C 1B 7A 01 00 7D E8 04 09 45 38 37
```

`02 01 06` is a two-byte Flags AD structure: type `0x01`, value `0x06`
(general discoverable and BR/EDR not supported). `11 07` declares 17 following
bytes with type `0x07`, a complete list of 128-bit Service Class UUIDs. Its
16-byte payload is the custom service UUID in Bluetooth little-endian wire order;
reversing it yields `e87d0001-7a1b-4c62-9f0b-5d9c01a70735`. `04 09` declares
four following bytes with type `0x09`, complete local name; ASCII
`45 38 37` is `E87`.

The firmware emitter test rejects any byte change in that vector. Android's scan
parser intentionally accepts permitted short/complete-name and UUID-list
type/position variants plus unknown well-formed AD structures; it still requires
the resolved name to be exactly `E87` and the exact service UUID. Parser
flexibility does not change the emitter golden.

The attribute table uses handles 1 through 12 for GAP name, the E87 service,
state write, build-info read,
Battery Service `0x180F`, Battery Level `0x2A19` read/notify, and its CCCD.
Any handle, UUID, property, security flag, terminator, or attribute-order change
fails the GATT profile test. Battery reporting is outside the semantic packet.

Just Works establishes link encryption but provides no MITM protection. Configure
the normal characteristic for encrypted access, not an “authenticated” ATT
permission. Android must successfully read and validate encrypted build-info
before it enables or attempts Sync. Firmware does not track that client-side
milestone; it independently authorizes and validates each state write.

The semantic write path is transactional:

1. reject a nonzero offset;
2. require exactly eight bytes;
3. require an encrypted link;
4. require the owner bond, once an owner exists;
5. decode into a temporary structure;
6. validate protocol version, reserved bytes, field ranges, and `credit_cents == 1727`;
7. commit the entire semantic state and increment its local revision once;
8. schedule one coalesced redraw;
9. return success.

Any failure leaves semantic state, revision, and rendered scene unchanged. Verify
the planned ATT mappings over air: invalid offset `0x07`, invalid length `0x0D`,
insufficient encryption `0x0F`, non-owner authorization `0x08`, and semantic
rejection `0x80`. They are **INFERRED** until exact SDK/wire capture.

First ownership requires the physical pairing window and encrypted bonding;
later control is restricted to that bond. Button 1 opens the 60-second window at
three seconds. Accept a replacement only within it, and remove the old bond only
after the replacement succeeds. Advertising is bounded and deterministic, with
no silent takeover. The 16-second PB08 reset is hung-runtime recovery, not bond
deletion. BLE loss preserves the last metrics/face and changes only connectivity.

Build-info is readable only after encryption. Test every stack-supported fragment
and offset, including boundaries/overruns, while confirming an exact 40-byte
logical value. Manifest, package, firmware, and evidence use the same `buildId`.

## 9. Buttons, battery, sleep, and charge-through

### 9.1 One ADC ladder, explicit classifiers

Model-1552 evidence places the two-button ladder on PB08 with pull-up 1000 and
ADC scale 4096. Stock values imply 100/330-ohm legs, single-button samples near
372/1016, and both buttons near 292. These are starting evidence, not calibrated
1542 thresholds. Measure idle, each/both buttons, temperature, battery voltage,
and charging distributions before freezing guarded windows.

Stock uses PB07/eight-second then PB08/eight-second paths. Custom firmware
disables both and owns PB08 with a 16-second fallback keyed to measured Button 1.
Healthy runtime handles ten seconds, disarms pin reset, waits for release, then
re-arms it; hung runtime reaches reset at 16 seconds.

The debounced public classifier outputs exactly `NONE`, `B1`, `B2`,
or `AMBIGUOUS`. The calibrated both-buttons cluster maps to `AMBIGUOUS`; there is
no public `CHORD` state and it may not inherit the stock Button 1 alias. Stable
`NONE` or `AMBIGUOUS`, or a direct stable change between `B1` and `B2`,
terminates the old hold immediately and never pauses/preserves its
elapsed time. `AMBIGUOUS` and a direct class change merely terminate the hold;
neither ever proves the safe release needed for maintenance.

After `AMBIGUOUS` or any direct change between the two known button classes,
lock out all new actions until stable `NONE`. In particular, direct
`B1`→`B2` terminates the Button 1 hold but cannot emit `SLEEP_TOGGLE`; only a
fresh stable `B2` press after stable `NONE` toggles
sleep once. Button 2 has no hold action, and `AMBIGUOUS` begins no action.

Maintain a separate maintenance-release latch. A maintenance request may occur
only after the normal-mode stop operation succeeds, debouncing observes stable
`NONE`, and the PB08 16-second fallback re-arm succeeds. `B1`, `B2`,
`AMBIGUOUS`, any undefined/out-of-window classifier result, and any direct
known-class change revoke that latch. Neither `AMBIGUOUS` nor a direct-change
termination can recover it; recovery requires a new stable `NONE` observation
and successful PB08 re-arm after the normal-mode stop.

V1 gestures:

- release Button 1 before three seconds: show the temporary battery overlay,
  including charging/full/fault when applicable, then return to the face;
- cross three seconds: open the one 60-second pairing window and keep timing;
- terminate the hold from 3,000 through 6,999 ms: stop hold timing but leave the
  original pairing window active with its remaining time;
- cross seven seconds: replace pairing UI with the update warning and exact
  three-second countdown;
- terminate the hold from 7,000 through 9,999 ms: cancel the warning/countdown,
  do not enter maintenance, and restore the same still-running pairing window;
- cross ten seconds in a healthy runtime: latch maintenance intent once, disarm
  PB08 reset, and show `READY TO UPDATE — RELEASE BUTTON`; request application
  maintenance only after normal-mode stop succeeds, stable `NONE` qualifies the
  release, and PB08 fallback re-arm succeeds;
- continue holding Button 1 to 16 seconds only when runtime is hung: PB08 resets,
  and the early reset-source path enters maintenance;
- Button 2 tap: enter manual sleep from active operation, or wake and redraw
  from manual sleep.

Threshold comparisons are inclusive at 3,000, 7,000, 10,000, and 16,000 ms.
Actions already emitted at a crossed threshold remain emitted after termination;
only the warning is explicitly dismissed. A new Button 1 hold starts from zero.

Record debounce, cutoffs, ADC windows, cadence, and recovery behavior as named
constants with host boundary tests.

### 9.2 Battery measurement

Acquire the eight half-VBAT ADC inputs into a temporary batch without changing
published battery state. Each raw input must be an integer in `0..4095`. If any
input is greater than 4095 or otherwise outside that domain, reject all eight
samples atomically before casting, sorting, or interpolation. Never clamp an
invalid input or partially update the prior result.

The battery measurement output states are exactly:

```text
VALID | INVALID_STALE | UNAVAILABLE_FAULT
```

A complete valid batch sets `VALID`, publishes its percentage, and updates the
RAM-only last-valid percentage. A faulty batch after a valid one sets
`INVALID_STALE`: preserve that RAM percentage only as explicitly stale data,
mark the current sample invalid, and fail the maintenance battery gate. Initialize
boot state to `UNAVAILABLE_FAULT` before the first valid batch. It reports battery
unavailable/fault without a percentage and fails the maintenance gate; a faulty
batch with no valid history leaves that state unchanged. Only a later complete
valid batch returns to `VALID`.

For a valid batch, cast before multiplying and compute each full-scale sample as
`uint32_t full = (uint32_t)raw * 2u`, whose domain is `0..8190`. Sort eight
`uint32_t` values, drop indices 0 and 7, and sum indices 1..6 in `uint32_t`
(maximum 49,140). The filtered voltage is exactly:

```text
v = floor((sum + 3) / 6)
```

The `+3` freezes nearest-integer rounding with a remainder of three rounding
upward. Interpolate with the exact discharge knots:

```text
3565:1  3625:10  3660:20  3693:30  3737:40  3797:50
3866:60 3971:70  4073:80  4188:90  4280:100
```

Below 3565 is zero and 4280 or above is 100. For adjacent knots `(v0,p0)` and
`(v1,p1)` with `v0 <= v < v1`, use only `uint32_t` intermediates:

```text
dv = v1 - v0
num = (v - v0) * (p1 - p0)
p = p0 + floor((num + floor(dv / 2)) / dv)
```

This is nearest-integer interpolation; the even-denominator half case rounds
upward. Assert `dv > 0`, monotonic knots, `num` bounds, and final `p` in
`0..100`. Do not add an unapproved jump filter or display hysteresis. Charging
indication comes from qualified charger state, not voltage alone; the alternate
charge table is not selected in v1. A tap may
show battery/charging information but never the stock charge gauge.

Battery ADC channel, divider, calibration error, endpoints, and load-dependent
accuracy on the exact board are **UNVERIFIED** until measured. Do not use an
unverified percentage for a destructive cutoff; qualified protection controls.

### 9.3 Power-state model

Use explicit orthogonal state:

```text
presentation = ACTIVE | MANUAL_SLEEP
external_power = ABSENT | PRESENT
charge_state = UNKNOWN | NOT_CHARGING | CHARGING | FULL | FAULT
safety_state = NORMAL | SAFETY_FAULT
```

There is no ordinary inactivity timeout in v1, on battery or external power.
While plugged in and `presentation == ACTIVE`, keep the normal face and BLE
available indefinitely as software policy. The eight-hour soak is finite
acceptance evidence; it does not redefine “indefinitely.”

`MANUAL_SLEEP` is authoritative across ordinary charger insertion/removal. A
charger edge may wake the CPU to service the electrical path but must not
presentation-wake the badge. Button 2 still sleeps/wakes while plugged in.
Unplugging active preserves face, BLE policy, and semantic state without starting
a timeout. Unplugging manual sleep leaves it asleep.

The `manual_sleep` latch is RAM-only and never persisted. It must survive the
selected retentive sleep path and ordinary charger callbacks. If sleep or a
charger-induced reset loses it, acceptance fails and requires an always-on
retention mechanism or a different qualified sleep mode. Do not add flash writes
as a workaround.

An ordinary charger event must not:

- navigate to a charge page;
- reset, zero, or replace accepted metrics;
- clear the owner bond;
- reset the presentation latch;
- enter sleep automatically;
- enable a stock inactivity timer.

Safety faults are the exception: qualified protection may blank the panel,
reduce load, stop radio, or shut down. This override is explicit, logged where
safe, and distinct from ordinary charge-through behavior.

Charger debounce/hysteresis are **UNVERIFIED**. Test bounced insertion/removal,
source renegotiation, brownout, full/not-charging transitions, and noisy cables.
Repeated callbacks are idempotent and preserve semantic/presentation state.

### 9.4 Cold boot, retained wake, and state lifetime

Semantic metrics are RAM-only. A retained wake may redraw the last face. A cold
boot/reset cannot restore metrics: show `PAIR ME NOW` when unbonded or
`WAITING FOR PHONE` when bonded until a valid encrypted packet arrives. Do not
persist metrics to hide a charger-induced reboot; prove and fix the reset.

Owner bond material uses qualified SDK persistence. Build identity and immutable
configuration are artifacts. Presentation/metrics are not persistent records.

### 9.5 Charge-through hardware acceptance and stop conditions

Before a long soak, capture an untouched stock reference under matched supply,
cable, ambient, starting charge, display, and radio workload. Instrument USB
voltage/current, cell voltage/temperature, PCB hot spots, reboot/brownout,
charger state, BLE availability, and periodic face photographs/hashes.

Stop the test immediately for any of:

- cell temperature at or above 45 degrees C;
- any PCB hot spot at or above 60 degrees C;
- temperature rise more than 10 degrees C above the matched untouched reference;
- charge current more than 20 percent above the matched reference;
- cell terminal voltage above the printed cell limit or more than 50 mV above the reference full voltage;
- swelling, odor, unstable USB behavior, repeated brownout/reboot, or display-rail overcurrent.

The eight-hour soak requires continuous normal face/BLE under external power,
with no stock gauge or inactivity sleep. Exercise Button 1 charging display,
Button 2 sleep/wake, writes before/after sleep, reconnect, charger transitions,
and unplug/replug. Evidence shows unplug resumes battery policy without losing
face, bond, or accepted metrics.

## 10. Maintenance mode and anti-brick recovery

Normal and maintenance modes are separate security surfaces. Healthy runtime
enters application maintenance only after Button 1 crosses three-second pairing,
seven-second warning, and ten-second entry. Hung runtime may reach the 16-second
PB08 reset; the earliest application checks `P33_PPINR_RST` and enters
maintenance before normal resources. Both routes use the same held Button 1, not
a chord. Maintenance has a distinct identity/service and times out or reboots if
no authorized operation begins. No normal GATT write may enter maintenance, and
normal mode never registers the update service.

The manifest records `antiRollbackPolicy: none-v1-physical-gate`. V1 has no
cryptographic monotonic counter; the physical gate and artifact validation are
the controls. A future policy needs a deliberate protocol/package version.

The planned maintenance identity rule requires complete name `E87 UPDATE`, AE00,
and a JieLi manufacturer marker. Its minimal handles are GAP name, AE00, AE01
write-without-response, AE02 notify, and the AE02 CCCD. It must not expose FEE7,
AA00, normal metrics, SPP/TWS, browser/file/settings/sensor, or stock UI features.
An unauthenticated session exits at 120,000 ms. Successful RCSP authentication
cancels that timeout.

The exact marker predicate and golden advertisement fixture are **UNVERIFIED**:
no approved evidence currently defines the AD type, manufacturer/service-data
bytes, byte mask, or matching rule. The required source is a raw advertisement
captured from the exact pinned native RCSP maintenance configuration, or an
official SDK-generated packet for that exact AC707N configuration, recorded with
its tool/configuration identity and committed as a parser fixture. Do not infer
the marker from a neighboring product or generic JieLi convention. Maintenance
advertisement implementation, Android scanning, and transfer acceptance remain
blocked until that predicate and fixture are pinned; matching only name or AE00
must fail closed.

This unresolved initial-maintenance marker is distinct from the documented
post-handoff loader-reconnect record. Only after the JieLi AAR calls
`onNeedReconnect(addr, isNewReconnectWay)` with `isNewReconnectWay == true` may
Android apply the new-format parser. Its complete variable-address fixture is:

```text
0F FF D6 05 41 54 4F 4C 4A 00 <six raw address bytes>
```

`0F` says that 15 bytes follow, `FF` is manufacturer AD type `0xFF`, and raw VID
bytes `D6 05` are little-endian `0x05D6` (decimal 1494). Bytes `41 54 4F 4C 4A`
are raw ASCII `ATOLJ`, the wire representation of logical marker `JLOTA`; `00`
is the format version. If the final raw bytes are `a0 a1 a2 a3 a4 a5`, compare
canonical address `a5:a4:a3:a2:a1:a0` with the six normalized octets from
`onNeedReconnect.addr`. Reversal is mandatory; do not compare the raw sequence.

The checked-in
`.superpowers/sdd/2026-08-27-e87-android-controller/jieli-aar-api-report.md`
line 425 labels the same `D6 05` bytes as little-endian `0xD605`; that value is a
typo. This fixture, `0x05D6`, and decimal 1494 supersede that line for E87 work.
The report itself remains historical evidence and needs a separate correction.

When `isNewReconnectWay == false`, the old reconnect advertisement format is
unspecified for this project. Reject it as unsupported; never feed it to the
new-format parser or infer it from a name/current MAC. Never accept a loader by
name or current connectable MAC alone, and do not reuse this loader record as
evidence for the initial `E87 UPDATE` marker predicate.

Only the official application-side RCSP `MSG_JL_UPDATE_START` handler may call
`update_mode_api_v2()`. Handoff requires a verified loader download, nonzero
`loader_saddr`, at least 50 percent battery for five stable seconds, no
low-voltage warning, stable voltage, and an exact AC707N single-bank
profile/layout match. Charging never bypasses this gate. Below 50 percent,
maintenance may advertise and authenticate but must refuse loader handoff.
Explicit cancel before handoff returns safely to normal mode. After handoff, the
persistent loader owns presentation and transport; Android reconnects and resumes
only the same manifest-selected artifact. Its charge-through behavior is a
separate plugged-power verification gate.

Normal discovery, encrypted build-info validation, and semantic Sync never
depend on a firmware artifact. Only a user-started maintenance operation needs
one. Before its maintenance scan or connect, Android's package layer must:

1. for the first vendor transition, require the manifest-selected Qix, validate
   its envelope/length/CRC, and extract its byte-identical UFW payload;
2. for a later custom maintenance rewrite, require the manifest-selected
   standalone `update.ufw` and do not route it through the Qix sender;
3. in either case validate the selected UFW header, entry bounds, internal CRCs,
   tail, target/profile, and exact manifest/build/package relation; and
4. reject overlapping, overflowing, protected-range, bootloader, calibration,
   identity, or out-of-profile entries before scanning.

Artifact matching is a maintenance and post-update-verification requirement. It
must not disable, delay, or alter ordinary normal-mode Sync.

Separately, the integration/operator `trial-manifest.json` preflight binds the
operation to a known recovery route and evidence ID before Android begins a
maintenance scan or connection; it is not a normal-Sync prerequisite.
Independently, the official application-side RCSP `MSG_JL_UPDATE_START` handler
enforces the verified loader download, nonzero address, profile/layout, battery,
voltage, and qualified hardware-signal gates. Only after its accepted
`update_mode_api_v2()` handoff/reset does the persistent loader own execution,
transport, and resume.

Never infer write permission from an address merely because it appears in a
package. The validator owns a proven-profile allowlist. Overflow-check all
integer additions and reject duplicate/ambiguous entries.

Power loss, malformed metadata, disconnect, or failed post-write verification
must land in a documented recoverable state. A success screen is not proof:
reboot, encrypted-read build-info, test face/buttons, and record build ID.

## 11. Reproducible build and release packaging

### 11.1 Canonical build identity

Compute `buildId` as the first 16 bytes of SHA-256 over:

```text
E87-BUILD-ID-V1\0 || canonical_build_descriptor
```

The canonical descriptor is the manifest's `buildDescriptor` object with exactly
these keys and value encodings:

| Key | Canonical value |
|---|---|
| `applicationSourceCommit` | lowercase 40-hex reviewed Git commit |
| `assetManifestSha256` | uppercase 64-hex digest of exact manifest bytes |
| `boardProfileSha256` | uppercase 64-hex digest of exact validated profile bytes |
| `linkerLayoutIdentity` | uppercase 64-hex digest of the exact generated linker-layout bytes |
| `sdkCommit` / `sdkTree` | lowercase 40-hex pinned Git identities |
| `semver` | canonical ASCII `major.minor.patch`; each component is `0..255` with no leading zero except `0`, and no prerelease/build suffix; total length at most ten bytes |
| `sourceTreeSha256` | uppercase 64-hex scoped source-tree digest |
| `targetFlags` | object with `compiler` and `linker` arrays preserving exact effective invocation order after response-file expansion and approved path-token normalization |
| `toolchainTreeSha256` | uppercase 64-hex installed pinned-toolchain tree digest |

The semver string maps directly to the three build-info `uint8` fields and to the
Qix version bytes; reject every alternate spelling. Preserve compiler/linker flag
order because repeated options and library order are semantic. Normalize path
separators to `/` and replace only the three approved absolute prefixes with
literal `@REPO@`, `@SDK@`, and `@TOOLCHAIN@`; reject another absolute path.

Serialize the descriptor as sorted-key, compact UTF-8 JSON with `:` and `,`
separators and no spaces. Descriptor strings are ASCII without control bytes;
escape only quote and reverse solidus as `\"` and `\\`, and never escape `/`.
Append exactly one LF and include that LF after the literal ASCII domain
separator plus one NUL byte. No timestamp, hostname, or environment-only
diagnostic is permitted. The manifest contains that same object and a sibling
`buildId` encoded as exactly 32 uppercase hex characters. The validator
reserializes the object and recomputes the ID. Firmware/build-info stores and
returns the same first 16 digest bytes raw.

`sourceTreeSha256` and `toolchainTreeSha256` are not archive hashes. The three
locks must freeze each root and include/exclude scope. `hash-tree.py` must use
slash-normalized ordinal relative paths, raw file bytes, executable-bit metadata,
empty and Unicode filenames, preserve CRLF versus LF, and ignore only explicitly
locked outputs.

Source and overlay scopes reject every symlink. Installed toolchains may contain
required symlinks, so their canonical tree records must distinguish `regular`
from `symlink`. A symlink record includes its slash-normalized relative path and
slash-normalized relative `readlink` target as bytes; it never substitutes the
target file's bytes for the link record. The resolved target must also be an
included entry under the same locked toolchain root. Reject an absolute target,
empty target, undecodable target, dangling link, cycle, excluded target, or any
chain that escapes the root after lexical and filesystem resolution. Hashing on
a host that materializes a symlink as a copied file must therefore fail rather
than silently produce another valid identity.

The locks must state the allowed record kinds and symlink policy independently
for every root. `hash-tree.py` binary record framing, regular/link fixtures,
escape/cycle cases, and golden vectors must be committed before either digest
can be called canonical.

The full manifest schema must additionally freeze `schemaVersion`, all root
keys, the three identity roles in section 5.1, chip/profile/layout, capability
bits, anti-rollback policy, artifact type literals and ordinal array order,
digest casing, evidence states, eligibility booleans, and rejection of unknown
properties. The serializer, schema, golden descriptor/manifest bytes, expected
build ID, tree-hash vectors, and cross-language reserialization tests are absent
from the current tree. Their absence is an explicit packaging/release blocker,
not permission to select a convenient encoding during a build.

Reproducibility means two clean builds from independently populated work
directories produce byte-identical delivered files. A permissive payload-only
comparison is never sufficient.

### 11.2 Qix and UFW checks

The Qix envelope is 27 bytes:

- magic `BC AF 01`;
- ASCII semantic version padded with NUL to ten bytes;
- 32-bit little-endian payload length;
- eight reserved zero bytes;
- little-endian CRC-16/CCITT-FALSE of the UFW payload, polynomial `0x1021`,
  seed `0xFFFF`, non-reflected, no final XOR;
- UFW payload.

Reject an empty, non-ASCII, over-ten-byte, or embedded-NUL version, plus length
mismatch, trailing bytes, and CRC mismatch. The UFW validator implements the
recovered 64-byte header, 80-byte entries, CD03 transform, seed-zero internal CRC,
protected-range, payload-boundary, and tail-signature rules. Reject truncation,
table overflow, duplicate/overlapping entries, path-like names, bad internal CRC,
wrong chip/role/bank/profile/build ID, or forbidden ranges before hardware contact.

The delivered release directory contains exactly six files:

```text
out/firmware/E87-JD9855-R1/<semver>/<build-id>/
  app.bin
  loader.bin
  update.ufw
  E87-<semver>-<build-id>.qix
  manifest.json
  SHA256SUMS
```

The two update artifacts have different lifecycle roles. The Qix file is the
one-time vendor-transition package for the first installation through the proven
vendor OTA path; its payload must be byte-identical to the delivered
`update.ufw`. The standalone `update.ufw` is the normal custom single-bank
artifact for all later application-maintenance rewrites. The manifest records
both roles and their exact byte/hash relation. Do not feed Qix to the later RCSP
rewrite path or silently collapse these roles.

Here and in the Qix filename, `<build-id>` is the same 32-character uppercase
hex representation stored in `manifest.json`; no lowercase or shortened alias.

Build receipts, ELF/map/listing files, logs, transcripts, and
`build-report.json` are nondelivered evidence and must live outside that
directory, for example under the build-ID evidence tree. Reject any extra file
in the delivered directory.

`manifest.json` lists filename, type, byte length, and SHA-256 for the four
binary/container artifacts; it never hashes itself or `SHA256SUMS`.
`SHA256SUMS` covers `app.bin`, `loader.bin`, `update.ufw`, the Qix file, and
`manifest.json`, but never itself. Each line is an uppercase 64-hex digest, one
space, binary marker `*`, and a bare filename; sort by ordinal filename and end
the file with exactly one LF. Paths, duplicate names, CRLF, blank lines, and
extra entries fail validation.

Write artifacts in a staging directory, compute and record their hashes, write
canonical `manifest.json`, then write `SHA256SUMS`. Validate the complete
staging directory, atomically rename it to the final path, and validate again
from a clean copy. Across two independent builds, `app.bin`, `loader.bin`, UFW,
Qix, `manifest.json`, and `SHA256SUMS` must all match byte-for-byte or package/lab
validation fails. Only nondelivered diagnostics outside this directory may
vary, and every allowed diagnostic difference must be declared.


### 11.3 Remote target contract and open wrapper blocker

Once the native bootstrap emits `E87_GENERATED_SDK_ROOT`, the guarded build is:

```sh
git -C /home/jethac/.local/share/e87-dev/sdk/e_badge_707_sdk_200 \
  rev-parse HEAD 'HEAD^{tree}'
ulimit -n 8192
export PATH=/home/jethac/.local/share/e87-dev/jieli-post-build:$PATH
: "${E87_GENERATED_SDK_ROOT:?native bootstrap receipt required}"
make -C "$E87_GENERATED_SDK_ROOT/SDK" \
  TOOL_DIR=/home/jethac/.local/share/e87-dev/jieli/pi32v2/bin \
  RUN_POST_SCRIPT=true VERBOSE=0 -j6
```

The expected Git output is the SDK commit and tree in section 4.
`RUN_POST_SCRIPT=true` is only a smoke path. The release packager separately
calls native `isd_download`, `fw_add`, and `ufw_maker` offline, validates the
release directory, and never opens a live USB target. Capture its exact commands,
exit codes, versions, maps, and artifact hashes in the evidence bundle.

Until the CLI/receipt contract in section 3 is implemented, integration-tested,
and recorded, this is a compiler invocation contract, not an end-to-end release
command. Release validation must fail closed rather than guess wrapper arguments
or reuse historical Windows scripts, and `releaseEligible` remains false.

### 11.4 Native host harness and container boundary

Run an exact executable/SDK preflight before any firmware gate:

```sh
test -x /usr/bin/python3.11
test -x /usr/bin/gcc-11
test -x /usr/bin/x86_64-linux-gnu-ld.bfd
test "$(/usr/bin/python3.11 --version 2>&1)" = "Python 3.11.15"
test "$(/usr/bin/gcc-11 -dumpfullversion -dumpversion)" = "11.4.0"
printf '%s  %s\n' \
  C4B3F4386C93758043A4E772574BFBD6B0E5E4CE8D50AF17F6FFEEB4B1A6BE5B /usr/bin/python3.11 \
  821AF3C74506283C179CA413BB33E6B528805A4DD8A5C09DF125E5AD560A9E89 /usr/bin/gcc-11 \
  58937FC20C21E147883B4FDAA0FC7438A8E8F2BB886CFCAA4896100CA91139E7 /usr/bin/x86_64-linux-gnu-ld.bfd \
  | sha256sum --check --strict -
test "$(git -C /home/jethac/.local/share/e87-dev/sdk/e_badge_707_sdk_200 rev-parse HEAD)" = \
  d0167685d032d745d88fe50233302edd46941622
test "$(git -C /home/jethac/.local/share/e87-dev/sdk/e_badge_707_sdk_200 rev-parse 'HEAD^{tree}')" = \
  854734595be49510aca5afb89f5885e8bce6a00f
test -z "$(git -C /home/jethac/.local/share/e87-dev/sdk/e_badge_707_sdk_200 status --porcelain)"
```

Expected identities are Python 3.11.15, GCC 11.4.0, and GNU ld 2.38 with the
three executable SHA-256 values embedded above. A version match without a hash
match fails. The three lock files in section 3 own the SDK, toolchain, and
packaging pins.

After firmware Task 1 exists, run its runner integration test before the runner:

```sh
/usr/bin/python3.11 -m unittest discover \
  -s firmware/tests_py -p 'test_host_runner.py' -v
/usr/bin/python3.11 firmware/tools/test-host.py \
  --suite all \
  --cc /usr/bin/gcc-11 \
  --require-compiler-sha256 821AF3C74506283C179CA413BB33E6B528805A4DD8A5C09DF125E5AD560A9E89 \
  --verify-reproducible
```

When `firmware/tests_py` and its pinned pytest dependency exist, run the entire
Python suite; an absent test dependency is a gate failure, not a skip:

```sh
/usr/bin/python3.11 -m pytest firmware/tests_py -q
```

When source-audit Task 11 exists, run it both before the target build and against
the final generated source inventory:

```sh
/usr/bin/python3.11 firmware/tools/source-audit.py --root firmware
```

After a custom target compile/link, the native wrapper must export
`E87_REAL_MAP` from its receipt and run the real map, not a fixture, through the
following frozen checker surface:

```sh
test -f "$E87_REAL_MAP"
/usr/bin/python3.11 firmware/tools/check-map.py \
  --map "$E87_REAL_MAP" \
  --profile firmware/board-profiles/E87-JD9855-R1.json \
  --report "$E87_MAP_REPORT"
```

The checker must reject a path under `firmware/tests_py` or any fixture tree and
must bind the map hash, build receipt, entry, memory limits, forbidden symbols,
and build-info bytes in its report. The current branch did not yet contain the
`firmware/` implementation files when this guide was audited. Therefore these
runner, pytest, source-audit, and real-map commands are required phase gates, not
claims of present success. The exact native wrapper must implement and
integration-test the exported map/report paths; until then this remains part of
the open release blocker in sections 3 and 11.3.

Use the digest-pinned Java container command in section 3 for Android; always
invoke the mode-0644 Gradle wrapper through `bash`. The separately pinned Python
container is reserved for later asset tooling:

```sh
docker run --rm python@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b python --version
```

Expected container output is `Python 3.11.16`. It is not the C host harness and
does not establish target-build equivalence. Section 7.5's fully transitive
hash-locked, `--require-hashes`, `--no-index`, `--network=none` execution and
native-library identity checks are mandatory. Never mount signing keys or the
entire home directory.

## 12. Android controller compatibility

The controller is a native Android application in `android-controller`, with
application ID `net.jethachan.factory_badges`; it is not Flutter. It targets
Java 8 bytecode and builds in the digest-pinned Eclipse Temurin/OpenJDK 21.0.12
container with Android Gradle Plugin 8.5.2, Gradle 8.7, compile/target SDK 34,
minimum SDK 31, and JUnit 4.13.2.

The one active `JieliOtaEngine` instance uses exactly this reconnect/auth
configuration before `startOTA`:

```java
BluetoothOTAConfigure option = BluetoothOTAConfigure.createDefault()
        .setUseReconnect(true)
        .setBleConnectParam(null)
        .setUseAuthDevice(true);
engine.configure(option);
```

Here `setUseReconnect(true)` means application-owned loader scanning and
reconnection; it does not remove the mandatory single-bank reconnect. Feed each
connection result through `onBtDeviceConnection`, each AE02 notification through
`onReceiveDeviceData`, and each MTU result through `onMtuChanged` on that same
manager instance. Do not create a second manager at handoff or bypass its
integrated authentication state.

The manager exposes no documented custom-link-key setter. A standalone
`RcspAuth` composition may be API-possible, but interoperability with this OTA
manager/firmware is **UNVERIFIED**. V1 keeps `setUseAuthDevice(true)` and blocks
handoff if the pinned firmware requires a custom key that this path cannot prove.

The remote Android SDK inputs are also pinned:

- `commandlinetools-linux-15859902_latest.zip`, SHA-256
  `4E4C464F145A7512B57D088AC6C278C03C9EEA610886B35A5E0804E74EEDF583`;
- `platform-tools` 37.0.1;
- `platforms;android-34` revision 3; and
- `build-tools;34.0.0`.

An unpinned SDK package revision is a build-gate failure.

The Jieli AAR is version 1.11.0 from
`https://github.com/Jieli-Tech/Android-JL_OTA.git` commit
`4bf054e1ae6e549b617e266cea733576c80c55d5`;
`libs/jl_bt_ota_V1.11.0_11015-release.aar` has SHA-256
`6F8DEC58C53C33DC9B1189D6AA1ECC4A0FE6A43ECF44BB4C79BBEE723E0D2550`,
and the repository is Apache-2.0.

The effective manifest permits only:

- `BLUETOOTH_SCAN` with `neverForLocation`;
- `BLUETOOTH_CONNECT`;
- `FOREGROUND_SERVICE` and `FOREGROUND_SERVICE_CONNECTED_DEVICE`; and
- `POST_NOTIFICATIONS`.

It requires BLE hardware. `MainActivity` is exported; `MaintenanceActivity` and
`BadgeSyncService` are nonexported; the service type is `connectedDevice`.
Manifest-merger removal nodes must strip every extra permission contributed by
the AAR. Ban INTERNET, location, broad storage, cleartext
transport/configuration, Flutter, Factory-client code, Retrofit, and generic BLE
wrappers.

Android platform BLE APIs own normal semantic BLE. The `ble/normal`, `sync`, and
`MainActivity` packages must contain no AE00/AE01/AE02,
`BluetoothOTAManager`, Qix, `update.ufw`, JPEG/pixel transport, or maintenance
write calls. The pinned JieLi AAR and package codecs stay behind the maintenance
boundary. Normal code cannot import the embedded-firmware repository or either
sender. The older SAF-selected adjacent-artifact plan is not the canonical lab
route and normal operation has no document-tree permission or artifact state.

### 12.1 Single-APK firmware carriage and sender boundary

The requested handoff copies exactly one audited APK to Windows and the phone.
To make that route complete, `embedE87Firmware` consumes one validated release
directory from section 11.2 and embeds all six files byte-for-byte under:

```text
assets/e87/releases/E87-JD9855-R1/<semver>/<build-id>/
```

It also emits `assets/e87/default-release.json`, containing only profile,
semver, build ID, six relative filenames, lengths, and SHA-256 values. The index
is canonical generated metadata; it neither replaces nor weakens the embedded
`manifest.json` and `SHA256SUMS`. Duplicate profiles/build IDs, an extra firmware
file, a filename escape, or any byte mismatch fails the Gradle task.

`EmbeddedFirmwareRepository` must reopen APK assets, cap every length, validate
the index and all six files, reparse Qix/UFW/manifest, and return an immutable
`ValidatedArtifact` before a maintenance scan starts. The Linux APK auditor adds
the original release directory as a required input:

```sh
/usr/bin/python3.11 android-controller/scripts/verify-apk.py \
  --apk android-controller/app/build/outputs/apk/debug/app-debug.apk \
  --sdk-root /home/jethac/.local/share/e87-dev/android-sdk \
  --firmware-release-dir \
    out/firmware/E87-JD9855-R1/<semver>/<build-id> \
  --report artifacts/verification/android-host/apk-verify.json
```

The auditor extracts the asset entries without executing the APK and requires
their bytes to equal the six source-release files. Only the audited APK crosses
to Windows; no separate Qix, UFW, manifest, checksum, or firmware file does.

Sender ownership is lifecycle-specific:

- `VendorQixTransitionSender.start(ValidatedArtifact)` alone owns the proven
  first-install C0/C1/C2/C3/C5 route. It consumes the embedded Qix, transmits its
  exact embedded UFW payload, journals acknowledged offsets, and accepts success
  only after reboot/build-info verification.
- `JieliOtaEngine.start(ValidatedArtifact)` alone owns later custom
  application/loader RCSP rewrites and consumes the embedded standalone UFW. It
  must never receive Qix bytes.

`VendorQixTransitionSender`, `embedE87Firmware`, and their exact captured
protocol fixtures do not exist in the current tree. The factory transfer proves
the device route, not this sender. Therefore APK embedding is the chosen design,
but APK-only first transition is an **OPEN ANDROID TRANSITION BLOCKER** until the
sender, build task, parsers, APK comparison, fake tests, and sacrificial-device
transfer all pass. Do not substitute the JieLi RCSP AAR for the Qix sender or
claim that installing the current APK supplies a transition route.

### 12.2 Android dependency integrity and offline replay

`android-controller/gradle/wrapper/gradle-wrapper.properties` must retain the
8.7 binary URL and add the official distribution checksum exactly:

```properties
distributionSha256Sum=544c35d6bd849ae8a5ed0bcea39ba677dc40f49df7d1835561582da2009b961d
```

Dependency verification is strict. Commit reviewed SHA-256 entries for every
plugin, AAR/JAR, POM, module metadata file, and transitive artifact in
`android-controller/gradle/verification-metadata.xml`. Enable
`lockAllConfigurations()` and commit `android-controller/gradle.lockfile` and
`android-controller/app/gradle.lockfile`, covering every resolvable
configuration. Ban dynamic versions, changing modules,
snapshots, `mavenLocal()`, dependency substitution, and repositories declared by
subprojects. A release gate never runs `--write-locks` or
`--write-verification-metadata`; those are reviewed provisioning operations.

The first build may populate an empty Gradle cache only from the declared
repositories while strict verification and locks are active. Preserve its APK,
reports, dependency-verification output, and resolved-component inventory. Then
run a second `clean` build with the same source, embedded release, SDK, Java image,
locks, verification metadata, and cache, but with Docker
`--pull=never --network=none` and Gradle
`--offline --dependency-verification=strict`. It must execute tests, lint,
embedding, and assembly again; a cache miss or attempted resolution fails. Run
the APK auditor on both outputs and require their embedded six firmware files,
manifest surface, dependency inventory, and package/component policy to match.

The release form of each Gradle invocation includes:

```text
--offline --dependency-verification=strict \
-Pe87FirmwareRelease=/workspace/out/firmware/E87-JD9855-R1/<semver>/<build-id> \
clean embedE87Firmware testDebugUnitTest lintDebug assembleDebug
```

The current tree lacks `distributionSha256Sum`, verification metadata, dependency
locks, embedded-firmware tasks, and an offline replay report. These are an
explicit Android build/handoff blocker. A successful unlocked online build is
diagnostic only and cannot produce the APK copied to Windows.

### 12.3 Normal semantic Sync

The Android codec always emits exactly:

```text
01 DD WW 00 BF 06 00 00
```

It never emits a sequence byte. Credit is always 1727 cents, and UI behavior must
not imply another value can be sent. Tests compare all eight bytes and reject
construction outside v1 ranges. Firmware remains authoritative and atomically
rejects different credit. Dynamic credit requires a future protocol version on
both sides.

Android scans for the expected profile, connects, discovers, pairs/bonds through
the physical ceremony, obtains encryption, reads and validates the exact 40-byte
build-info value, and only then enables or attempts Sync. This is Android state;
firmware does not store a “build-info was read” authorization bit. A wrong
profile, unsupported schema, missing capability, or unencrypted build-info
response fails closed. Normal Sync does not compare a firmware artifact.

On Redmi `M2010J19SG`, validate first pairing, permission denial/retry, reconnect
after app/radio restarts, encrypted build-info, rejection, bond persistence,
owner rejection, maintenance selection, rotation/background, and useful errors.
Capture `adb logcat`, screenshots, app/OS versions, Bluetooth address policy, and
firmware build ID.

## 13. Verification strategy

### 13.1 Host-side tests before touching hardware

Host tests should use pure modules or fakes for SDK adapters. At minimum:

| Requirement or risk | Host test | Pass condition | Evidence |
|---|---|---|---|
| eight-byte codec | exhaustive valid ranges plus golden `01 DD WW 00 BF 06 00 00` | exact length/order; no sequence/CRC | `host/codec-junit.xml`, vectors JSON |
| fixed v1 credit | mutate each of packet bytes 4, 5, 6, and 7 independently; include uint32 values `0`, `1`, `1726`, `1727`, `1728`, and `0xFFFFFFFF`, plus byte-order traps | only little-endian 1727 is accepted; every rejection leaves semantic state, revision, and rendered output unchanged | `host/semantic-negative.json` |
| atomic validation | inject bad protocol version, reserved byte, offset, length, range, encryption, and owner | no partial commit, revision change, or redraw on error | `host/gatt-state-machine.xml` |
| build-info | golden 40-byte encode/decode, padded profile, raw build ID, offsets; model Android gate and firmware callbacks separately | byte-for-byte match; reserved bytes zero; Android never enables Sync before a valid encrypted read; firmware stores no prior-read state and independently gates read/write security | `host/build-info-vectors.bin`, report JSON |
| state/event ordering | permute semantic, disconnect, button, charger, and DMA events | deterministic final state; no torn render | `host/event-traces.json` |
| no inactivity timeout | advance fake time for battery and external-power modes | no automatic presentation transition | `host/power-policy.xml` |
| manual sleep | charger insert/remove and reconnect permutations in both presentation states | only Button 2 or safety policy changes presentation | `host/power-matrix.json` |
| charger bounce | rapid duplicate/bounced edge sequences | idempotent, metrics/bond/latch unchanged | `host/charger-fuzz.json` |
| button state machine | calibrated windows including both-buttons→`AMBIGUOUS`; stable `NONE`/`AMBIGUOUS` and direct B1↔B2 terminations; inject B1/B2/AMBIGUOUS/undefined after candidate release; normal-stop and PB08 re-arm failures; 2999/3000, 6999/7000, 9999/10000, and 15999/16000 ms | `AMBIGUOUS`/direct change only terminate; maintenance requires successful normal stop, stable NONE, and successful re-arm; B1/B2/AMBIGUOUS/undefined revoke release latch; direct B1→B2 cannot toggle sleep until stable NONE then fresh B2; hung reset requires uninterrupted B1 | `host/button-vectors.csv` |
| battery filter | put 4095 then >4095 in each of all eight positions; test boot/no-history, valid→invalid→valid state transitions, permutations, duplicate extrema, maximum sum, all 11 knots, every interval, and half-rounding | out-of-domain rejects the whole batch without clamping; `UNAVAILABLE_FAULT` and `INVALID_STALE` block maintenance; the latter preserves only the last valid RAM percentage; exact uint32 formulas and rounding otherwise | `host/battery-vectors.csv` |
| strip renderer | sentinel scenes; independent Day/Week values 0, 1, and 100; exact icon/palette/track words; alpha/dim vectors; strip bounds, clipping, callback reorder | fixed icon positions; exact zero-progress tints and black inside active caps at 1..100; 23 strips; exact source-over then RGB565 truncation; stable hashes | `host/renders/*.rgb565`, `host/renders/*.png`, hashes |
| asset generation | lock parser rejects every unhashed/transitive/wrong-tag wheel and native mismatch; two network-disabled clean generations | `--require-hashes`, `--no-index`, `--network=none`; exact wheel/native receipt and byte-identical assets | `host/assets.sha256`, provenance/native receipt JSON |
| memory budget | parse linker map and symbols | buffers at approved ranges, scratch untouched, heap target at least `0x8000`, no full framebuffer/PSRAM dependency | `host/memory-report.json`, map file |
| Qix/UFW parser | golden and malformed corpus, truncation/overflow/overlap/protected ranges | fail closed before any write; all CRC conventions match vectors | `host/package-parser.xml`, corpus results |
| loader reconnect parser | exact `0F FF D6 05 41 54 4F 4C 4A 00 <addr>` plus every byte/length/VID/marker/version/address mutation and both callback-format flags | only new-format true accepts; raw address reverses to callback anchor; false/old format, name-only, and current-MAC-only reject | `android/loader-advertisement.xml`, raw fixtures |
| APK firmware embedding | embed one six-file release, mutate/omit/add each entry, inspect APK ZIP, and cross-call both senders | APK bytes equal release; normal Sync imports none; Qix only reaches `VendorQixTransitionSender`, standalone UFW only reaches `JieliOtaEngine` | `android/apk-firmware.json`, unit XML |
| reproducibility | two clean independent builds | all six delivered files match byte-for-byte; only external diagnostics may vary | `host/reproducibility.json`, SHA files |
| Android permissions | merged-manifest assertion | no forbidden permissions/components | `android/merged-manifest.xml`, lint report |
| Android dependency replay | wrapper checksum, strict verification metadata, all locks, first resolved build, then clean `--offline` build under `--network=none` | no dynamic/unverified dependency, cache miss, resolution attempt, or APK-audit mismatch | dependency inventory, both Gradle logs/APK reports |
| Android native flow | unit/instrumented fake GATT tests | normal encryption/build gate and fixed codec fail closed without artifact state; maintenance validates artifact before scan | JUnit and instrumentation XML |

Run the exact identity preflight in section 11.4 first. Then run every gate whose
implementation phase exists; once a phase exists, a missing tool/test is failure:

```sh
/usr/bin/python3.11 -m unittest discover \
  -s firmware/tests_py -p 'test_host_runner.py' -v
/usr/bin/python3.11 firmware/tools/test-host.py \
  --suite all \
  --cc /usr/bin/gcc-11 \
  --require-compiler-sha256 821AF3C74506283C179CA413BB33E6B528805A4DD8A5C09DF125E5AD560A9E89 \
  --verify-reproducible
/usr/bin/python3.11 -m pytest firmware/tests_py -q
/usr/bin/python3.11 firmware/tools/source-audit.py --root firmware
test -f "$E87_REAL_MAP"
/usr/bin/python3.11 firmware/tools/check-map.py \
  --map "$E87_REAL_MAP" \
  --profile firmware/board-profiles/E87-JD9855-R1.json \
  --report "$E87_MAP_REPORT"
```

The real-map command applies only after the native custom target build has
exported those receipt-bound paths; a fixture-map pass cannot replace it.

After section 12.2's locks and embedding task exist, run the first strict Linux
build/test/lint/embedding gate independently:

```sh
docker run --rm --user 1000:1000 \
  -e HOME=/e87/home -e ANDROID_HOME=/e87/android-sdk \
  -e ANDROID_SDK_ROOT=/e87/android-sdk \
  -v /home/jethac/.local/share/e87-dev:/e87 \
  -v /home/jethac/workspaces/factory-android-badges-e87:/workspace \
  -w /workspace \
  eclipse-temurin@sha256:ce5767b7222312d42395f5bab033cd91f09e44032a2f21bdfd7b5b912dbe1e77 \
  bash ./android-controller/gradlew -p ./android-controller --no-daemon \
  --dependency-verification=strict \
  -Pe87FirmwareRelease=/workspace/out/firmware/E87-JD9855-R1/<semver>/<build-id> \
  clean embedE87Firmware testDebugUnitTest lintDebug assembleDebug
```

Repeat it using section 12.2's `--pull=never --network=none` container and Gradle `--offline`
form; both outputs require audit. The Gradle commands are necessary but not the
completion gate. A Linux-native APK auditor is still absent and is an
**OPEN ANDROID HANDOFF BLOCKER**. Its required interface is:

```sh
/usr/bin/python3.11 android-controller/scripts/verify-apk.py \
  --apk android-controller/app/build/outputs/apk/debug/app-debug.apk \
  --sdk-root /home/jethac/.local/share/e87-dev/android-sdk \
  --firmware-release-dir \
    out/firmware/E87-JD9855-R1/<semver>/<build-id> \
  --report artifacts/verification/android-host/apk-verify.json
git diff --check
```

That auditor must use the pinned `apkanalyzer`, `aapt2`, and `apksigner` to
assert package ID, min/target SDK, valid signature, the exact permission and
component surface in section 12, no cleartext or Flutter payload, and required
`arm64-v8a` OTA native code. It records tool/APK hashes and exits nonzero on any
unknown or mismatch. Freeze its implementation, tests, and exact report schema
before copying an APK to Windows.

Only after that report passes may the single final APK be copied to a dedicated
Windows artifact directory, rehashed, and installed/launched on the Redmi 9T.
The final-ADB-only handoff is:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath .\app-debug.apk
adb -s b202e7b70221 get-state
adb -s b202e7b70221 shell getprop ro.product.model
adb -s b202e7b70221 install -r .\app-debug.apk
adb -s b202e7b70221 shell am start -W -n net.jethachan.factory_badges/.ui.MainActivity
```

Require model `M2010J19SG`, recheck any installed package/signature first, and
never auto-uninstall a differently signed package. Capture install output,
`am start -W`, package dump, and filtered logcat. No source, SDK, build cache,
intermediate APK, loose firmware/release file, or firmware evidence moves to
Windows; the single audited APK contains the exact embedded release assets.

The current firmware implementation files were absent when this guide was
audited, so none of the firmware commands above is claimed to pass today.
Implement the runner/tests first, source audit in its planned phase, and map gate
only once a real custom linker map exists. The future native package CLI then
runs the UFW/Qix/manifest/SHA validators and two-build six-file byte comparison
before lab eligibility. Missing firmware phases keep `releaseEligible=false`;
the missing Linux APK auditor independently blocks Android handoff.

The pinned native JieLi compiler/linker path and successful pristine stock-SDK
compile/link are **PROVEN**. Custom E87 overlay integration, target bytes, native
offline packaging, and hardware behavior remain **UNVERIFIED** until their gates
run and their evidence is bound to the build ID.

### 13.2 Charged-hardware matrix

Each row needs timestamped observation, firmware build ID, unit ID, fixture/supply details, and raw captures:

| Hardware case | Method/tool | Required observation | Stop/fail condition |
|---|---|---|---|
| heartbeat and recovery | first write with panel rails disabled; logic/current/BLE heartbeat capture for 10 minutes; then qualified recovery re-entry | stable heartbeat/build ID for full interval and repeatable recovery before any panel-rail test | reset, current anomaly, lost heartbeat/build identity, or failed recovery; stop with panel rails disabled |
| panel identity | current-limited bench supply, logic analyzer, microscope/reference photos | confirmed pins/bus/reset/init/orientation/order/offset/TE | any electrical limit, unexpected heating, or disagreement with untouched reference |
| strip transport | logic analyzer plus color bars/checkerboard/edge markers | exact windows/byte counts; no tear or stale strip | bus contention, buffer reuse, rail anomaly |
| BLE packet/errors | Android/nRF Connect-class client plus air/log capture | encrypted 8-byte accept; exact negative cases; atomic scene | any unencrypted success, wrong-credit success, or partial mutation |
| build-info | encrypted reads at valid/invalid offsets | exact 40 bytes and package build ID | readable before encryption or inconsistent identity |
| owner bond | two phones, power cycle, radio/app restart | original owner reconnects; second controller rejected | silent owner replacement or bond loss |
| buttons | ADC logging across voltage/temperature; healthy and deliberately hung Button 1 holds; Button 2 repetitions | separated windows; both-buttons maps to AMBIGUOUS; exact 3/7/10 behavior; hung runtime resets at 16 seconds; correct manual sleep/wake | early/accidental maintenance or reset, chord treated as a known key, or missed/extra manual wake |
| battery | calibrated DMM/supply/reference load | table/filter tracks measured voltage within approved error | overvoltage, heating, or unsafe discharge |
| 100 sleep/wake cycles | scripted Button 2 cycles split across battery/external power with display/current/BLE logging | exactly 100 complete sleeps, wakes, full redraws, and preserved bond/policy | missed/extra transition, rail/DMA fault, state loss, or growing current/thermal trend |
| manual sleep | Button 2 before/during charging; insert/remove cable | latch survives ordinary charger events; button wakes; full redraw | presentation wakes on charger edge or latch is lost |
| charge display | Button 1 during charging/full/not-charging/fault | temporary state is truthful; face returns | stock gauge/page appears or state is fabricated |
| charge-through soak | eight hours, instrumented USB/cell/thermal logging, BLE heartbeat | normal face/BLE continuous, no inactivity sleep, no resets | any numeric or qualitative stop in section 9.5 |
| unplug/replug | perform during active and manual sleep | active keeps face/BLE/state; sleeping remains asleep; no timeout starts | metrics/bond/latch loss or charge page |
| cold boot | remove/restore power under controlled conditions | waiting state, not stale semantic metrics | fabricated restoration or boot loop |
| recovery entry | healthy 10-second Button 1 flow, deliberately hung 16-second PB08 flow, reset-cause capture, and near-miss releases | both documented routes enter application maintenance and re-entry is repeatable | wrong reset cause, ordinary gesture entry, or failure to disarm/re-arm PB08 safely |
| malformed package | use non-writing validator path or sacrificial fixture | all corrupt/forbidden cases rejected before erase | any flash mutation |
| recovery package | sacrificial unit, current-limited fixture, validated package | repeatable restore/re-entry and post-boot build identity | uncertain target/range, power instability, loss of recovery |
| post-handoff resume | interrupt Bluetooth, app process, and phone power one at a time only at protocol-defined resumable phases | immutable same-hash resume, correct loader record, final build-info match | badge power cut at unproved commit, wrong-hash resume, lost record, or false success |
| second rewrite/recovery | distinct semver/build ID with obvious non-electrical face change, then recovery re-entry | second application-side rewrite, exact new build-info, and repeatable recovery | reused build ID/artifact, nonrecoverable state, or identity mismatch |
| Android Redmi | Redmi `M2010J19SG`, ADB/logcat/screenshots | pairing, encrypted normal Sync, embedded-artifact validation, transition/rewrite, and reconnect pass | permission bypass, wrong device/profile/artifact acceptance |
| Android Z Fold 7 | final repeat after every Redmi gate | normal Sync and physically gated maintenance/rewrite both pass with captured build ID | any behavior/security/identity divergence from accepted Redmi flow |

Do not continue after a safety stop, identity mismatch, unexpected write, or loss
of the qualified recovery route.

### 13.3 Lab ladder

Advance one gate at a time:

1. **Static only:** source/profile review, package parsing, linker map,
   deterministic host tests, two firmware builds, and both Android strict builds.
2. **Untouched reference:** capture stock boot, panel traffic, buttons, charging,
   current, temperature, and recovery behavior without modifying it.
3. **Recovery before first write:** positively identify MaskROM/recovery, prove
   non-writing re-entry, validate the recovery package, and record USB/tool
   identity. Failure blocks every write.
4. **Heartbeat first:** transition only the heartbeat build with panel rails
   disabled, observe it for 10 uninterrupted minutes, then prove recovery re-entry
   again. Any heartbeat, identity, current, or recovery failure stops the ladder;
   do not enable panel rails.
5. **Panel qualification:** under current limit, enable conservative reset/init,
   solid colors, partial windows, orientation/order/TE/backlight, and strip
   transport only after gate 4 passes.
6. **Sleep/wake endurance:** complete exactly 100 Button 2/panel sleep-and-wake
   cycles across battery and external power with full redraw and state checks.
7. **Normal firmware:** on Redmi, prove BLE/build-info, semantic face, all packet
   errors, exact button boundaries, owner bond, reconnect, and cold boot.
8. **Power and charge:** run staged insertion/removal and manual-sleep cases,
   then the instrumented eight-hour soak under section 9.5 stops.
9. **Maintenance before handoff:** validate the embedded artifact before scan,
   reject spoofs/malformed packages, and exercise every safe pre-handoff cancel.
10. **Post-handoff resume:** on the first installed custom build, interrupt
    Bluetooth, app process, and phone power separately at defined resumable phases;
    never cut badge power at an unproved flash-commit phase. Resume only the same
    hash and require normal-mode build-info verification.
11. **Second distinct rewrite and recovery:** install a different semver/build ID
    with an obvious non-electrical face change through application maintenance,
    verify it, then re-enter and prove the qualified recovery route again.
12. **Z Fold 7 final:** only after every Redmi rung passes, repeat both normal
    Sync and the physically gated maintenance/rewrite flow on the Z Fold 7.

Every gate records operator, unit ID, prerequisites, stops, and pass/fail. A later
success does not erase an earlier unexplained anomaly.

## 14. Recovery and restore cautions

Historical `docs/OTA-RESEARCH.md` and AC697/BR30 material are research context,
not the E87 v1 contract. Preserve them, but do not import addresses, transport,
UUIDs, or restore claims without target-specific evidence.

The older authoring baseline required two matching full stock reads before
destructive work. The sacrificial-trial decision is narrower:

- attempt stock readback and preserve every byte obtained;
- if the confirmed interface is write-only, record exactly `SKIPPED_WITH_REASON: WRITE_ONLY_CONFIRMED`;
- this exception is allowed only for the designated sacrificial lab unit;
- an untouched reference unit, positive MaskROM identity/re-entry evidence, and
  a locally validated recovery package remain mandatory;
- `releaseEligible` remains `false`.

This is not permission to skip recovery preparation, treat a vendor package as a
backup, or ship a write-only process. Production/release must revisit full
read/restore and obtain explicit risk approval. Never overwrite unique
calibration, identity, keys, or boot data from a model-family assumption.

Before destructive action, resolve unit/artifact paths, hash inputs, photograph
labels/wiring, record power limits, close auto-connect software, and rehearse
non-writing/recovery commands. Stop on ambiguity in identity, protected ranges,
package target, boot/recovery mode, or supply state.

## 15. Evidence bundle and audit trail

Use the stable append-only evidence layout:

```text
artifacts/verification/<build-id>/
  trial-manifest.json
  host/{pytest.txt,android-tests.txt,apk-verify.json,firmware-validate.json,reproducibility.json}
  host/{bootstrap-receipt.json,build-report.json,elf,map,listing,transcripts}/
  recovery/{maskrom-id.json,stock-readback.json,recovery-dry-run.json}
  hardware/{heartbeat,solid-colors,panel,buttons,battery,normal-ble,charge-through,maintenance,rewrite,zfold}/
    evidence.json
    logs/*
    captures/*
docs/verification/e87/<build-id>-summary.md
tools/verification/{new-trial.py,record-step.py,validate-evidence.py}
tools/verification/windows-final-adb/capture-redmi.ps1  # optional final APK/ADB only
```


The exact Linux-native USB/recovery capture CLI and fixture contract are
**UNVERIFIED** and block remote recovery evidence until implemented and checked
against a known non-writing capture. It must record raw bytes, device identity,
executable hash, arguments, exit status, and monotonic timing without exposing a
write/erase path. Do not substitute the removed Windows `capture-usb.ps1`.
`capture-redmi.ps1`, if retained, is confined to final verified-APK/ADB evidence
on Windows and is never a firmware build, package, or badge-USB dependency.
`trial-manifest.json` binds the build/artifact hashes, unit role, phone alias,
ordered gates, and stop policy. Evidence states are `NOT_RUN`, `PASS`, `FAIL`,
and `SKIPPED_WITH_REASON`; only `PASS` satisfies a prerequisite. Records append
atomically with hash-chain links and exact commands, versions, exit codes,
monotonic durations, fixtures, instruments, and calibration facts. Corrections
append a superseding record and never rewrite the prior observation.

Reference evidence filenames from the release manifest or lab report, not only
chat. A screenshot is weak for byte behavior; pair it with raw BLE, logic,
current, or thermal data. A passing log from an unknown build is not acceptance
evidence.

## 16. Evidence register

The labels below separate decisions, stock-family facts, and target validation.
“PROVEN” includes its stated scope; it never transfers automatically from model
1552 to the exact 1542 board.

| Claim | Label and scope | Evidence / implication |
|---|---|---|
| v1 semantic write is eight bytes with no sequence or CRC | **PROVEN — normative v1** | spec and completed strict codec; golden vector required |
| Android sends, and firmware accepts, only 1727 cents | **PROVEN — normative v1** | all other values reject atomically; dynamic credit is a future protocol version |
| build-info schema is exactly 40 bytes and encryption-gated | **PROVEN — normative v1** | Android validates it before Sync; firmware stores no prior-read authorization state and validates each read/write independently |
| normal mode excludes maintenance/update/raw framebuffer surfaces | **PROVEN — normative v1** | linker/GATT discovery must demonstrate the implementation |
| main/app/tail/scratch addresses and 16-row double-buffer budget | **PROVEN — analyzed stock image/profile**; **INFERRED — custom placement** | linker assertions and exact-target runtime tests required |
| no full framebuffer and no PSRAM dependency | **PROVEN — v1 design constraint** | map parser and runtime high-water evidence required |
| model-1552 contains the recorded JD9855 descriptor/init blob | **PROVEN — that stock image only** | blob address, length, digest, and tail were observed |
| exact 1542 panel pins, mode, timings, offsets, orientation, order, and TE | **UNVERIFIED** | qualify electrically; never fill with guessed values |
| PB08 stock ladder and predicted ADC centers | **PROVEN/INFERRED — model-1552 electrical model** | calibrate distributions on exact target before thresholds |
| PB07/PB08 stock hold paths exist as described | **PROVEN — analyzed stock package** | confirm custom disables both and owns 16-second recovery |
| battery conversion/filter behavior | **PROVEN — normative v1 algorithm**; exact analog calibration **UNVERIFIED** | host vectors plus DMM/reference-load measurements |
| no inactivity timeout, active charge-through, Button 2 manual sleep, no stock gauge | **PROVEN — normative v1** | host event matrix and eight-hour hardware soak required |
| charger callbacks, debounce/hysteresis, retention behavior, thermal/current envelope | **UNVERIFIED — exact target** | staged instrumented tests and section 9.5 stop limits |
| ordinary charger events preserve face, metrics, bond, and manual-sleep latch | **PROVEN — acceptance requirement** | any charger-induced reset/latch loss fails; safety override remains allowed |
| metrics are RAM-only and cold boot shows waiting state | **PROVEN — normative v1** | retained-wake and cold-boot tests distinguish paths |
| SDK URL/commit/tree plus Linux toolchain/post-tools size, SHA, ETag, and roots are pinned | **PROVEN — declared and checked remote inputs** | recheck archive and installed identities; custom E87 output still needs its gates |
| Qix/UFW structures and CRC conventions | **PROVEN — current packaging contract** | malformed corpus and golden vendor artifacts gate use |
| physical 1542, reference-package 1552/Q87, and Lab recovery-source identities | **PROVEN — distinct manifest roles** | schema and evidence must never substitute one for another |
| exact JieLi maintenance marker predicate and raw advertisement fixture | **UNVERIFIED** | block maintenance advertisement, Android scanning, and transfer acceptance until exact-config capture or official generated bytes are pinned |
| post-handoff new reconnect record | **PROVEN — approved parser contract** | require `isNewReconnectWay=true`, `0F FF D6 05 41 54 4F 4C 4A 00`, and reversed six-byte address; `0xD605` at AAR report line 425 is a superseded typo |
| old reconnect format and custom RCSP link key | **UNVERIFIED / unsupported in v1** | reject `isNewReconnectWay=false`; use integrated auth and block if a custom key is required |
| normal Sync has no firmware-artifact dependency | **PROVEN — normative separation** | artifact selection/validation begins only for maintenance and post-update verification |
| APK-embedded release and `VendorQixTransitionSender` | **UNVERIFIED / OPEN ANDROID TRANSITION BLOCKER** | only one APK may cross hosts, but first transition is blocked until embedding, sender fixtures, APK audit, and sacrificial transfer pass |
| transitive asset wheels/native renderer identity | **UNVERIFIED / OPEN REPRODUCIBILITY BLOCKER** | require fully hashed offline wheel closure and native `ldd`/file identities before asset generation |
| Gradle wrapper/dependency locks and offline replay | **UNVERIFIED / OPEN ANDROID HANDOFF BLOCKER** | current tree is diagnostic-only until checksum, strict metadata, all locks, embedding, and second offline build pass |
| native Linux bootstrap/package CLI, receipt, schemas, and golden manifests | **UNVERIFIED / OPEN RELEASE BLOCKER** | compiler smoke is not packaging; keep `releaseEligible=false` until implemented and passing |
| v1 rollback policy is physical-gate only | **PROVEN — declared v1 limitation** | do not claim cryptographic anti-rollback |
| current Devin SVG blob/digest and factory provenance | **PROVEN — current repositories** | icon README and firmware plan carry the corrected pin; older warnings are superseded |
| Jieli AAR source/version/digest | **PROVEN — declared exact dependency** | release validation must match the full commit and SHA-256 in section 12 |
| Redmi `M2010J19SG` behavior | **UNVERIFIED until the end-to-end lab run** | retain logs, screenshots, OS/app version, and build ID |
| stock full read/bit-perfect restore | **UNVERIFIED if interface is write-only** | sacrificial exception only; never promote to release capability |
| positive MaskROM identity/re-entry and local recovery package | **REQUIRED, not presumed** | block destructive work until evidence exists |

Update a register entry only with an immutable source/evidence file and explicit
scope change. “Builds,” “looks similar,” and “worked once” are not evidence
labels.

## 17. Derivative implementation checklist

For an agent starting a similar E87/AC707N BR35 firmware:

1. Read the current spec, authoring guide, and all four plans—badge firmware,
   packaging/target build, Android, and integration verification—plus this guide
   and evidence register; treat older OTA research as historical.
2. Freeze exact target identity and v1 wire/package contracts. Copy neither a
   sequence-field proposal nor dynamic-credit behavior.
3. Fetch/verify pinned SDK/toolchain without editing the clean SDK; create a small
   overlay with platform adapters and linker assertions.
4. Implement pure host-tested state machines first: semantic codec, atomic state,
   buttons, power/charge, build-info, renderer, and package parser.
5. Generate assets with the fully hashed offline wheel/native lock from the
   current Devin SVG; record its SHA-256 and Git blob.
6. Build twice cleanly, inspect the map, validate Qix/UFW, embed/audit the exact
   APK assets, and assemble evidence before hardware.
7. Capture the untouched reference and prove recovery identity/re-entry. Use the
   write-only exception only on the named unit; keep `releaseEligible=false`.
8. Qualify unknown panel and ADC facts under current limit; update the profile only from measurements.
9. Run normal BLE/display/button/sleep tests, then staged charge-through tests and
   the eight-hour soak with numeric stops.
10. Validate two maintenance rewrites and recovery entries, complete Android end
    to end on Redmi, then repeat normal and maintenance flow on Z Fold 7 and
    audit every evidence link.

Before declaring a clone ready, ask: Are profile/build IDs exact? Are all normal
GATT surfaces enumerated? Is every invalid packet demonstrably atomic and every
display byte bounded? Do charger edges preserve manual sleep without flash? Can
the unit recover after interrupted maintenance? Are target electrical unknowns
still honestly labeled?

## 18. Common plan omissions

Implementation plans often miss:

- ATT error translation differences in the exact vendor stack;
- long-read/offset semantics for a 40-byte encrypted characteristic;
- concurrency between BLE commit, charger callbacks, Button 2, and DMA completion;
- reset-cause handling that distinguishes cold boot from retained wake;
- charger-edge debounce and presentation-latch retention;
- rail sequencing and DMA quiescence at sleep;
- framebuffer byte order, circular clipping, last-strip length, and TE polarity;
- linker overlap with vendor scratch, interrupt stacks, hidden DMA alignment, or heap high-water;
- bond-store exhaustion, owner deletion atomicity, and a second phone racing first ownership;
- package integer overflow, overlapping entries, protected calibration/identity sectors, and partial-write recovery;
- canonical-build descriptor encoding and nondeterministic vendor metadata;
- asset provenance drifting out of sync across source, lock, README, and plan;
- evidence tying a physical unit and observed firmware build ID to every capture;
- the difference between an eight-hour acceptance soak and an indefinite software policy;
- safety override precedence over presentation preservation;
- the sacrificial write-only exception being accidentally promoted to production.

Resolve each item in code, tests, or an explicitly scoped **UNVERIFIED** entry.
Silence in a plan is not a safe default.
