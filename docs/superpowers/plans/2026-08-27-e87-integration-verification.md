# E87 Integration and Hardware Verification Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove recovery, display, input, power, semantic BLE, maintenance rewrite, charge-through, and Android interoperability on a sacrificial E87 before promoting any inferred hardware fact or using the daily-driver phone.

**Architecture:** A build-ID-scoped evidence bundle drives a one-way risk ladder. Each rung has explicit prerequisites, captures machine-readable observations plus photos/logs, and stops before the next destructive action on failure. The untouched badge is the recovery reference; the Redmi 9T is the first BLE host and the Z Fold 7 is admitted only after repeatable recovery and rewrite.

**Tech Stack:** Python 3.11/pytest, PowerShell, Android Debug Bridge, Android Bluetooth HCI snoop logs, JieLi MaskROM/downloader tooling, USB current/voltage meter, DMM/temperature probes, JSON evidence manifests, PNG/MP4 capture.

**Spec:** `docs/superpowers/specs/2026-08-27-e87-local-rendering-trial-design.md`

## Global Constraints

- No badge write begins until the exact firmware directory passes disconnected validation as `labEligible: true`, the APK passes its verification script, and both identities are copied into an immutable trial manifest.
- The first target is the explicitly sacrificial badge. At least one stock badge remains untouched for comparison and recovery evidence.
- Stock firmware readback is opportunistic, not a gate: record the attempt and any write-only limitation, but do not block the accepted sacrificial ladder. MaskROM device identity and a locally validated recovery loader/package are mandatory before the custom transfer.
- Never retry a failing transfer blindly. Capture stage, byte offset, power, host log, badge behavior, and loader state first; resume only if the protocol proves it is the same immutable artifact.
- Each rung consumes only artifacts whose SHA-256 values appear in `trial-manifest.json`. Rebuilds create a new build-ID directory and restart hardware evidence at the appropriate rung.
- Promotion from `INFERRED` to `CONFIRMED` is field-specific. A working panel does not confirm charge safety, button polarity, sleep current, loader recovery, or long-duration stability.
- The charging/display soak is finite: eight continuous hours with normal face and BLE available. Button 2 manual sleep remains authoritative while plugged in; plugging/unplugging does not wake it.
- Stop immediately on swelling, odor, unstable USB input, repeated brownout/reboot, display rail overcurrent, cell-surface temperature at or above 45 C, PCB hotspot at or above 60 C, a rise more than 10 C above the untouched reference under matched conditions, charging current more than 20% above the untouched reference, or measured cell-terminal voltage exceeding the printed cell limit or untouched-reference full voltage by 50 mV.
- Evidence captures may contain local USB/Bluetooth addresses; keep them under ignored `artifacts/verification` and redact them from committed summaries.
- Hardware tools may write only when the operator has placed the sacrificial badge into the specifically named receiving/MaskROM/update state and the script confirms chip/profile/build. No wildcard USB target is accepted.

---

## Evidence Layout and Stable Interfaces

```text
artifacts/verification/<build-id>/
  trial-manifest.json
  host/{pytest.txt,android-tests.txt,apk-verify.json,firmware-validate.json,reproducibility.json}
  recovery/{maskrom-id.json,stock-readback.json,recovery-dry-run.json}
  hardware/{heartbeat,solid-colors,panel,buttons,battery,normal-ble,charge-through,maintenance,rewrite,zfold}/
    evidence.json
    logs/*
    captures/*
docs/verification/e87/<build-id>-summary.md
tools/verification/{new-trial.py,record-step.py,validate-evidence.py,capture-redmi.ps1,capture-usb.ps1}
```

Stable evidence states are `NOT_RUN`, `PASS`, `FAIL`, and `SKIPPED_WITH_REASON`. Only `PASS` satisfies a prerequisite. `record-step.py` appends observations atomically, binds them to build/artifact hashes, and never rewrites an earlier observation; corrections append a superseding record.

### Task 1: Create the immutable trial and host evidence bundle

**Files:**
- Create: `tools/verification/new-trial.py`
- Create: `tools/verification/record-step.py`
- Create: `tools/verification/validate-evidence.py`
- Create: `tests/verification/test_evidence.py`
- Create: `.gitignore` entries for `artifacts/verification/`

**Interfaces:**
- Consumes: one validated firmware package and one verified APK.
- Produces: a trial manifest binding build ID, hashes, phone serial alias, target role, test order, and stop policy.

- [ ] **Step 1: Write state-transition tests**

Reject unknown builds, mutable artifact paths, hash mismatch, missing prerequisite, PASS without observations, later-step timestamps preceding prerequisites, overwritten evidence, and promotion from failed/skipped evidence. Accept append-only supersession that names the prior record hash.

- [ ] **Step 2: Implement the evidence tools**

Use canonical JSON records and SHA-256 chain links. Record tool versions and monotonic elapsed durations; wall-clock time is evidence, not identity. Redact Bluetooth MAC/USB serial values in generated committed summaries.

- [ ] **Step 3: Capture disconnected verification**

Run the complete Python/host/Android test suites, firmware release validator in lab mode, APK verifier, and two-root reproducibility check. Copy raw outputs and exit codes into `host`; all must PASS before Task 2.

### Task 2: Prove MaskROM identity and recovery readiness

**Files:**
- Create: `tools/verification/capture-usb.ps1`
- Create: `docs/verification/e87/recovery-procedure.md`
- Evidence: `artifacts/verification/<build-id>/recovery/*`

**Interfaces:**
- Consumes: sacrificial badge in receiving/MaskROM state, untouched reference badge, verified loader/recovery package.
- Produces: positive AC707N identity, reversible loader dry-run evidence, and a documented stock-readback result.

- [ ] **Step 1: Record physical identities without writing**

Photograph/label sacrificial and untouched units; record printed model, observed stock version `Q87/11.1.0.2`, USB VID/PID/device response, chip ID, flash geometry, battery condition, and tool command transcript.

- [ ] **Step 2: Attempt bounded stock readback**

Request boot/config/application ranges only through documented read commands. If the ROM/device rejects reads, record the exact command/status as `SKIPPED_WITH_REASON: WRITE_ONLY_CONFIRMED`; do not synthesize a dump and do not make it a gate.

- [ ] **Step 3: Dry-run recovery loader validation**

Verify target identity and parse the recovery package without committing application flash. If the tool cannot separate loader handshake from write, stop before sending the write command and record the successful handshake. Task 3 requires confirmed MaskROM identity, valid package bytes, stable power, and a documented re-entry gesture.

### Task 3: Flash a heartbeat-only image

**Files:**
- Evidence: `artifacts/verification/<build-id>/hardware/heartbeat/*`

**Interfaces:**
- Consumes: a separately packaged heartbeat variant using the same board/linker/update layout.
- Produces: proof of application boot, watchdog stability, and repeatable recovery entry without energizing the inferred display path.

- [ ] **Step 1: Reconfirm exact target and package**

The write script displays badge label, chip ID, package/build ID, battery/power state, byte ranges, and SHA-256, then requires the operator's explicit physical-state confirmation. It refuses multiple matching USB devices.

- [ ] **Step 2: Transfer once and capture the full transcript**

Verify target-side status/CRC where available. Observe a low-risk heartbeat using the known button/backlight indicator path defined by the heartbeat build; record reset cause and ten minutes of watchdog operation.

- [ ] **Step 3: Re-enter recovery**

Exercise PB08/16-second early recovery from the heartbeat build and confirm MaskROM identity again. Failure stops the ladder before display power is enabled.

### Task 4: Validate rails, solid colors, windows, and full renderer

**Files:**
- Evidence: `artifacts/verification/<build-id>/hardware/{solid-colors,panel}/*`

**Interfaces:**
- Consumes: display-test variants with bounded commands and the final renderer build.
- Produces: confirmed rail/reset/backlight polarity, DBI profile, orientation, RGB565 order, clipping, and face geometry.

- [ ] **Step 1: Measure the display electrical sequence**

With backlight initially disabled, confirm rail voltages/current and continuity against the untouched reference for the recovered model-1552 mapping: reset `PA05`, TE `PA06`, CS `PA07`, CLK `PA12`, D0-D3 `PA08`-`PA11`, and open-drain `IO_LCD_PG` backlight low/on and high-Z/off. Confirm there is no separate DC or recovered panel-rail hook. Configure only `LCD_TYPE_SPI`, QSPI mode/submode `0x21`, pixel type `0x21`, idle-low clock, unidirectional RGB565 input/output, and no more than the recovered 90-fps request; measure the actual derived clock. Apply reset high 10 ms, low 10 ms, high 100 ms, then send only the 657-byte/51-record init whose SHA-256 is `BB0767D3E0BF4AD982725C6A38A9168DDF9E5BA2E3D4D595B1FFBDD17E5B89FF`. Stop on any pin, current, temperature, reset, or model-1542 transferability mismatch.

- [ ] **Step 2: Render solid-color and address-window patterns**

Confirm the direct-DBI target is 360x360 RGB565; keep the stock uploader's 368x368 JPEG target out of this measurement. Serially verify black, white, red, green, and blue `lcd_clear` calls with `lcd_wait_busy`. Then use one `0x5460` buffer for twelve independently addressed 360x30 strips at y `0,30,...,330`, waiting before every reuse. Verify corners, axes, physical circular clipping/radius 180, orientation/mirroring, RGB/BGR and byte order, active-area offsets, actual QSPI timing/framing, and tearing. Only after the serial path passes may a linker-proven `0xA8C0` build test two-buffer completion callbacks, TE synchronization, and then `lcd_draw_continue`. Photographs and logic-analyzer captures must include a color/coordinate legend.

- [ ] **Step 3: Render semantic goldens**

Compare on-device 0/1/50/99/100 percent rings, icons, Devin mark, `$17.27`, battery overlay, pairing text, warning countdown, and maintenance screen against generated goldens. Record tolerances only for photographed color/camera rendition; geometry and pixels from any captured framebuffer/test tap are exact.

- [ ] **Step 4: Promote only confirmed profile fields**

Append hardware evidence for each rail/pin/polarity/timing/DBI field. Create a new build if a profile source value changes; do not relabel the old package release-eligible.

### Task 5: Validate buttons, reset recovery, battery, sleep, and charging semantics

**Files:**
- Evidence: `artifacts/verification/<build-id>/hardware/{buttons,battery,charge-through}/*`

**Interfaces:**
- Consumes: final application image and measurement instruments.
- Produces: exact gesture boundaries, calibrated battery display, manual sleep behavior, and eight-hour charge-through evidence.

- [ ] **Step 1: Exercise Button 1 boundaries**

Test debounce and release before 3 seconds, 3-second pairing entry, 7-second destructive-warning onset, 10-second maintenance entry, cancellation at every earlier release point, 60-second pairing timeout, 120-second unauthenticated maintenance timeout, and 16-second PB08 reset/recovery.

- [ ] **Step 2: Exercise Button 2 and persistence**

Tap Button 2 awake/unplugged, awake/plugged, asleep/unplugged, and asleep/plugged. Confirm it is the sole ordinary sleep control, does not stop charger electrical control, and plugging/unplugging preserves awake/manual-sleep state and last RAM face while power remains. Capture the panel order: drain DBI; backlight off; display-off `28`; sleep-in `10`; wait at least 120 ms; release LCD clock. Wake must reacquire the clock, repeat the high-10/low-10/high-100-ms reset and exact init, redraw while dark, and enable backlight last, with no invented rail toggle. Measure sleep current and repeat at least 100 cycles.

- [ ] **Step 3: Calibrate battery reporting**

At multiple charge/discharge points compare badge samples/percentage to DMM cell voltage and untouched behavior. Confirm a Button 1 tap shows the large battery percentage, charging/full bolt is correct, and no stock charging window or mode appears.

- [ ] **Step 4: Run the eight-hour charge-through soak**

Keep the face displayed and normal BLE available while charging. Log USB voltage/current, cell and PCB temperature, badge battery/charger state, resets, display errors, and periodic semantic sync. Exercise one plugged manual-sleep/wake cycle. Apply every Global Constraints stop threshold.

### Task 6: Validate normal bonded semantic BLE with the Redmi 9T

**Files:**
- Create: `tools/verification/capture-redmi.ps1`
- Evidence: `artifacts/verification/<build-id>/hardware/normal-ble/*`

**Interfaces:**
- Consumes: verified debug/release APK installed on Redmi serial `b202e7b70221` and final badge build.
- Produces: encrypted owner bond, exact packet/ack behavior, reconnect behavior, and absence of image/network traffic.

- [ ] **Step 1: Install and capture a clean first pairing**

Use ADB to record installed package/signing hash/permissions, clear prior app state only on the sacrificial test install, enable Bluetooth HCI snoop, and pair solely during the physical 60-second window. Confirm app has no network/location/storage permission and badge rejects writes outside the window/unbonded/unencrypted.

- [ ] **Step 2: Exercise exact state packets**

Send all boundary combinations and representative intermediate Day/Week values with credit fixed at 1727 cents. Confirm exactly eight bytes, write-with-response, ACK error mapping, duplicate ACK without redraw, coalesced rapid slider updates, and no sequence number/pixel/JPEG traffic.

- [ ] **Step 3: Exercise reconnect and ownership**

Cover badge reboot, phone Bluetooth toggle, app process death, phone reboot, out-of-range return, wrong bonded phone, owner replacement with injected interruption, pairing timeout, plugged/unplugged awake behavior, and manual sleep. Prior owner must survive any incomplete replacement.

### Task 7: Validate maintenance transfer, loader reconnect, and a second rewrite

**Files:**
- Evidence: `artifacts/verification/<build-id>/hardware/{maintenance,rewrite}/*`

**Interfaces:**
- Consumes: a second semver/build-ID package that changes an obvious non-electrical face detail and the Android maintenance screen.
- Produces: proof that application-side RCSP, loader handoff, resume rules, post-update identity, and future recovery actually work.

- [ ] **Step 1: Prove maintenance is physically gated**

The app must ignore normal-name spoofing and AE00 without the JieLi marker. Enter maintenance only after the 10-second gesture/early recovery, validate package before scanning, and reject wrong chip/profile/layout/hash/battery gates.

- [ ] **Step 2: Test every safe pre-handoff cancel**

Cancel before connect, during validation, before authenticated transfer, and before loader commitment. Confirm return to normal service and unchanged build ID. Once `onNeedReconnect` fires, confirm Cancel is disabled and the exact artifact resume record is immutable.

- [ ] **Step 3: Complete the update across loader reconnect**

Capture application AE01/AE02 traffic, loader advertisement matching, disconnect/reconnect, transfer verification, reboot, normal-service reconnect, and exact 40-byte build-info match. Transfer completion without that match is failure.

- [ ] **Step 4: Repeat with intentional interruptions**

At protocol-defined resumable phases interrupt Bluetooth/app process/phone power one at a time. Never cut badge power at an unproven flash-commit phase. Resume only the same artifact hash; wrong artifact must fail closed.

- [ ] **Step 5: Perform a second full rewrite and recover again**

Update back to a newly built package, verify its distinct ID, then re-enter MaskROM recovery. This rung promotes `rewrite` only after two application-side maintenance transfers and two recovery entries have passed.

### Task 8: Validate the Z Fold 7 and publish the evidence summary

**Files:**
- Create: `docs/verification/e87/<build-id>-summary.md`
- Evidence: `artifacts/verification/<build-id>/hardware/zfold/*`

**Interfaces:**
- Consumes: all prior PASS evidence and the same verified APK build.
- Produces: daily-driver phone compatibility result and a redacted, committed hardware-fact summary.

- [ ] **Step 1: Repeat normal pairing/sync/reconnect on the Z Fold 7**

Do not run maintenance first. Confirm Android version/permission differences, background reconnect, sliders, battery overlay trigger, sleep, and charge-through operation.

- [ ] **Step 2: Perform one physically gated maintenance update**

Use a fresh semver/build ID and the exact validated artifact tree. Capture the same post-update build-info proof as Redmi.

- [ ] **Step 3: Generate and review the summary**

List every requirement with PASS/FAIL/SKIPPED state, artifact hashes, confirmed versus inferred hardware fields, thermal/current extrema, recovery/readback outcome, known limitations, and the exact build IDs safe for continued lab use. Omit device identifiers and raw private logs.

- [ ] **Step 4: Promote eligibility only after independent validation**

Run `validate-evidence.py` followed by `validate_release.py --require-release`. Any missing mandatory evidence keeps `releaseEligible: false`; the lab firmware remains usable on sacrificial units without misrepresenting its status.
