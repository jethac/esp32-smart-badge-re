# E87 app-core coordinator contract

This contract applies to `e87_app_core` at integration base
`1e793dd76d2ee194f89e4d9db34b933c2d409799`. It refines the approved
[local-rendering trial design](superpowers/specs/2026-08-27-e87-local-rendering-trial-design.md)
and the normative `E87-FIRMWARE-DEVELOPER-GUIDE.md`; it does not bind any
target SDK callback or task.

## Ownership and serialization

One app-core task owns one statically allocated `struct e87_app_core`.
`e87_app_core_init`, `e87_app_core_step`, and `e87_app_core_get_view` are the
only coordinator entry points. BLE, ADC, charger, LCD-idle, GPIO-wake, RCSP,
and semantic callbacks must copy their fixed-size payload into an
`e87_app_core_event` and queue it. They must not call the coordinator from an
ISR, retain event pointers, render, or synchronously re-enter app-core.

The single mutable `e87_app_core_effect` port is the target boundary. The port
must finish or reject an effect before returning and must copy a maintenance
handoff before returning. Normal-profile initialization and maintenance-profile
adoption return their opaque app handle by filling `effect.data.profile`.
Successful initialization/adoption always returns a non-null handle; failure
must leave no unowned live profile.

All semantic metrics, UI overlays, button deadlines, mode state, and session
state are RAM-only. Cold boot always starts with an empty semantic store.

## Visible behavior

- A normal cold boot emits reset disarm/arm, initializes the normal BLE
  profile, opens normal writes and advertising, then draws exactly once.
  Unbonded boots draw **Pair Me Now**; bonded boots draw **Waiting for Phone**.
  **Face** is possible only after a valid semantic commit in the current boot.
- A changed valid semantic packet commits before drawing. A duplicate packet
  neither increments the revision nor draws. An invalid packet changes
  nothing.
- Button 1 tap opens the 2500 ms battery overlay. At 3 s it opens the pairing
  window, at 7 s it draws the update warning, and at 10 s it closes pairing
  and requests the serialized maintenance transition.
- Button 2 requests manual sleep. Sleep first stops new draws and waits for LCD
  idle. Completion turns the backlight off before panel sleep, stops BLE, arms
  shared-ladder wake, and enters low power. Charge snapshots and semantic
  events may update RAM while asleep but do not wake or draw. A separately
  classified Button 2 wake exits panel sleep, redraws the latest model, turns on the
  backlight, and only then starts BLE.
- Atomic charge snapshots are orthogonal status. They do not replace a Face,
  clear metrics, or cancel manual sleep.
- UI models are compared by value. A state transition draws once; a duplicate
  state does not draw. Rendering is never performed by a callback.
- Time is modulo `uint32_t`. Forward intervals up to `0x7fffffff` are valid,
  including wrap; a backward timestamp is rejected before mutation.

## Profile transition barriers

Normal to maintenance is one transaction owned by the coordinator:

1. close normal writes;
2. disable normal advertising, drain an exact-handle connection, and release
   the normal profile through `e87_ble_mode_fsm`;
3. report the completed normal-release barrier to `e87_recovery`;
4. wait for stable Button 1 release and recovery authorization;
5. let `e87_maintenance` alone perform RCSP interface init, RCSP init, and
   RCSP BLE init;
6. use `BLE_ADOPT_MAINTENANCE_PROFILE` to query/adopt that already-created
   opaque handle into BLE-mode bookkeeping—this operation must not initialize
   RCSP again;
7. verify maintenance writes are closed and maintenance advertising is live.

Maintenance to normal is the reverse ownership boundary:

1. `e87_maintenance` rejects commands, stops advertising, disconnects,
   performs RCSP BLE exit, observes the handle released, and exits the RCSP
   interface;
2. BLE-mode bookkeeping verifies that maintenance is stopped/released;
3. initialize the normal profile once, configure writes, enable normal
   advertising, re-arm recovery ownership, and redraw the retained RAM model.

An operation failure before profile release is retryable with writes and
advertising closed. After old-profile release, the current BLE-mode API has no
cancel/rollback operation, so target initialization remains retryable in a
no-profile fail-closed state. Rejected non-retryable effects, terminal module
errors, draw failures, or impossible composition states latch
`E87_APP_CORE_PHASE_FAIL_CLOSED`, stop draws, close writes, and stop/verify
advertising. Semantic data already committed before a draw failure remains
committed.

## Required integration dependencies

This coordinator deliberately does not hide contradictions in the exact base:

1. `e87_button_fsm` must be corrected upstream so Button 1 to Button 2,
   AMBIGUOUS, or unsafe input aborts with no tap or threshold action (except
   `END_UPDATE_WARNING` if already shown) and requires stable NONE re-arm.
   The coordinator forwards classifier results without normalizing this bug.
2. `e87_power_policy` must be corrected upstream to emit
   `BACKLIGHT_OFF` before `PANEL_SLEEP`. The coordinator preserves module
   command order; a target adapter must not depend on hidden panel side
   effects.
3. The target port must implement explicit, non-creating maintenance-handle
   adoption/query as described above. The current maintenance API has no
   public handle getter; treating profile initialization as idempotent or
   initializing RCSP twice violates this contract.
4. Wake classification is a distinct queued target event. Reusing the normal
   ADC classifier after ADC suspension would quarantine the held wake button;
   the target must classify/rebase wake input before posting
   `E87_POWER_EVENT_WAKE_CLASSIFIED`.
5. The current `e87_ble_control` write path commits synchronously through a
   caller-supplied state-store pointer, while its observer exposes only a
   callback-owned snapshot. It cannot directly feed this coordinator's queued
   raw semantic event without duplicate state ownership. Target integration
   therefore requires an upstream validate/queue/commit seam (or an equivalent
   single-owner event API); reconstructing packets from snapshots, exposing the
   coordinator's private store, or committing from an ISR violates this
   contract.

The target `e87_app.c`, platform adapters, source lists, packaging, and SDK
patches are intentionally outside this contract and this coordinator change.
