# E87 PB07 Evidence Correction Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development to implement this plan task by task.

**Goal:** Correct the pure recovery vocabulary and fail-closed button-evidence contract so PB07 is the only accepted recovery/ADC pin and its pinned SDK route is accepted only by exact 32-bit equality with `0x0002030D`.

**Architecture:** Keep `e87_recovery` board-neutral by naming the SoC PINR facility rather than a GPIO. Put all PB07 hardware identity in the evidence validator and board-profile documentation. Extend both root evidence and its canonical driver projection with an exact channel value and acceptance rule, so stale PB08, sentinel-only, range-style, and void/self-asserted routing claims cannot validate. Freeze the PINR GPIO mode as `PORT_INPUT_PULLUP_100K` / `0x12`; argument 5 is a mode enum, not a boolean.

**Tech Stack:** C11 host policy tests; Python 3.11 `unittest`; canonical JSON evidence validator; Markdown qualification documentation.

---

### Task 1: Pin the corrected PB07 evidence contract with failing tests

**Files:**
- Modify: `firmware/tests_py/test_button_evidence_validator.py`

1. Change the canonical fixture identity from PB08 to PB07 and from `AD_CH_PB8` to `AD_CH_PMU_PADC0`.
2. Add root/projection fields `channelValue=0x0002030D` and `channelAcceptanceRule=EXACT_U32_EQUALITY`.
3. Add negative mutations for PB08, adjacent channel values, booleans/floats, non-exact acceptance rules, and stale PB08 paths.
4. Run the focused test and observe failure against the old validator.

### Task 2: Enforce exact PB07 route identity

**Files:**
- Modify: `firmware/tools/validate-button-evidence.py`

1. Update canonical TEST_ONLY/CONFIRMED paths and capture ID to PB07.
2. Require `gpioToken=IO_PORTB_07`, `channelToken=AD_CH_PMU_PADC0`, numeric `channelValue=0x0002030D`, and `channelAcceptanceRule=EXACT_U32_EQUALITY`.
3. Cross-link both new fields byte-for-byte into the canonical driver projection.
4. Run the focused validator suite and observe it pass.

### Task 3: Make recovery constants explicitly PINR-neutral

**Files:**
- Modify: `firmware/host/test_recovery.c`
- Modify: `firmware/overlay/SDK/apps/watch/include/e87/e87_recovery.h`
- Modify: `firmware/overlay/SDK/apps/watch/e87/e87_recovery.c`
- Verify: `firmware/tests_py/test_recovery_board_neutral.py`

1. Change tests to require PINR-named hold/arm/disarm constants and observe the recovery host compile fail.
2. Rename the pure policy constants/commands without introducing PB07/PB08 tokens.
3. Run recovery host tests plus the board-neutral architecture test and observe both pass.

### Task 4: Correct qualification documentation

**Files:**
- Modify: `docs/E87-FIRMWARE-DEVELOPER-GUIDE.md`
- Modify: `docs/superpowers/plans/2026-08-27-e87-badge-firmware.md`
- Modify: `docs/superpowers/plans/2026-08-27-e87-integration-verification.md`

1. Replace stale positive PB08 claims with the recovered PB07 ownership/ADC facts.
2. State exact `adc_io2ch(IO_PORTB_07) == 0x0002030D` acceptance and preserve model-1542 hardware qualification gates.
3. Retain PB08 only where it is explicitly identified as a rejected alternative or historical stock path.

### Task 5: Verify and review

1. Run the focused validator, recovery architecture, and host recovery suites.

### Review correction: exact PINR mode and materialized PB07 route

1. Add failing tests for every alternate input-mode token/value pair, including
   the hazardous in-range value `1` (`PORT_OUTPUT_HIGH`).
2. Require `PORT_INPUT_PULLUP_100K` / `0x12` exactly in ADC/PINR evidence.
3. Require `DRIVER_IO2CH` with returned-`u32` semantics; reject reviewed-overlay
   and void/self-asserted internal-signal routes for this PB07 profile.
4. Exercise a positive synthetic `CONFIRMED` PB07 namespace plus exact stale
   PB08 evidence, raw, driver, and overlay path negatives.
