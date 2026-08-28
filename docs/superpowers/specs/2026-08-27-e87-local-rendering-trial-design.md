# E87 local-rendering trial: Android controller and rewriteable badge firmware

**Status:** Approved for implementation on 2026-08-27

**Date:** 2026-08-27

**Target:** Sacrificial E87/model-1542 badge using the recovered AC707N/BR35 and
JD9855-compatible model-1552 baseline

**Companion reference:** [`docs/E87-FIRMWARE-AUTHORING-GUIDE.md`](../../E87-FIRMWARE-AUTHORING-GUIDE.md)

## 1. Objective

Build a deliberately small system in which an Android phone sends semantic
provider values over BLE and the badge renders the complete face locally. The
trial provider is Devin. The phone presents arbitrary Day and Week sliders from
0 through 100 and sends a fixed on-demand credit value of `$17.27`. The badge
renders two Apple-Watch-style progress rings, the Devin mark, and the credit
amount on its 360x360 direct-DBI round display. The stock image uploader's
368x368 JPEG target is a separate transport/storage format, not panel geometry.

The same custom firmware must remain rewriteable without showing the vendor's
receiving UI. A physical staged hold on badge button 1 opens normal pairing at
3 seconds and, if the hold continues, enters a minimal firmware-update mode at
10 seconds. A 16-second hardware reset provides a hung-runtime fallback.

External power must not replace the current face with the vendor battery gauge
or redirect the badge into a charging-only application mode. While plugged in,
the badge continues charging, keeps its normal renderer and BLE service active
indefinitely, and suppresses automatic display sleep. Button 2 remains an
explicit manual sleep/wake override.

The deliverables are:

1. a native Android controller APK for the Redmi 9T, suitable for later use on
   the user's Z Fold 7;
2. a custom AC707N/BR35 badge firmware build and reproducible package;
3. a one-time package for transition from the current vendor firmware and a
   standard custom update artifact for subsequent rewrites;
4. host-side tests and render artifacts that do not require the charging badge;
5. a documented charged-badge validation procedure, to be run later on a
   sacrificial unit.

## 2. Scope and non-goals

### Included in this trial

- Native Android BLE control and firmware-maintenance screens.
- Day and Week integer controls, each covering every value from 0 to 100.
- Fixed credit value 1727 cents, displayed as `$17.27`.
- Local badge rendering from an eight-byte semantic state packet.
- Bonding with one remembered phone and silent reconnect/update after bonding.
- Local battery overlay, pairing UI, update UI, sleep/wake behavior, and the
  staged 3/10/16-second recovery behavior.
- Charge-through operation: normal face and BLE remain available while the
  battery charges, with no stock charging screen or charger-triggered sleep.
- Assets compiled into the application image; no dependency on the stock
  `UIRES` partition.
- A physically gated, minimal BLE maintenance mode that exposes JieLi's official
  single-bank RCSP loader/update flow without the vendor receiving UI.

### Deliberately excluded

- Fetching live Factory or Devin account data. The trial uses sliders and a
  fixed credit value so transport and rendering can be proven independently.
- Rendering the badge face on Android. The production phone code sends values,
  not pixels or JPEGs. A host-only golden-image renderer is allowed as a test.
- Provider switching, account management, cloud services, notifications,
  clocks, menus, drawers, touch UI, audio, and stock badge features.
- Persisting Day, Week, credit, or the last rendered face to flash.
- Supporting every product sold as `E87`. This first image is bound to one
  verified board/panel profile and must reject other profile IDs.
- Claiming hard-brick recovery from application code. Physical MaskROM access
  remains the recovery floor if execution never reaches the early updater hook.

## 3. Evidence and constraints that drive the design

- The working reference is AC707N/BR35, not the earlier AC697/BR30 hypothesis.
- The recovered model-1552 direct-DBI descriptor is 360x360 RGB565 with a
  reported circular radius of 180 pixels. A full RGB565 framebuffer is 259,200
  bytes and does not fit in usable RAM. The stock descriptor instead uses two
  30-row buffers of `0x5460` bytes each; exact double buffering totals `0xA8C0`.
  The existing `0x6000` tail fits one stock buffer for serial hardware proof,
  not both. The Android stock path separately targets 368x368 JPEG uploads.
- The pinned generic build disables PSRAM and the model-1552 ISD has no PSRAM
  directive; the physical model-1542 package remains unverified. The custom
  image is PSRAM-independent in every case.
- The model-1552 display descriptor names a JD9855 panel and points to a
  validated 657-byte, 51-record initialization list with SHA-256
  `BB0767D3E0BF4AD982725C6A38A9168DDF9E5BA2E3D4D595B1FFBDD17E5B89FF`.
  Its direct-DBI parameters are QSPI mode/submode `0x21`, pixel type `0x21`,
  idle-low clock, unidirectional RGB565 input/output, and 90 fps. Dedicated bus
  pins are CS `PA07`, CLK `PA12`, D0-D3 `PA08`-`PA11`; reset is `PA05`, TE is
  `PA06`, and open-drain `IO_LCD_PG` is low/on and high-Z/off for backlight.
  These are proven for decoded model 1552 but inferred for physical model 1542.
  Orientation/mirroring, RGB/BGR and byte order, 360-pixel clipping, actual bus
  timing/framing, TE phase, read behavior, and sleep current remain hardware
  gates.
- Both user buttons are decoded through one PB07 ADC resistor ladder in the
  model-1552 target configuration. This is **PROVEN for the decoded model-1552
  artifact and UNVERIFIED for the physical model-1542**: the packed config-item
  header at `cfg_tool.bin +0x34` decodes to `CFG_ADKEY_ID = 0x20B`, length 20;
  `syscfg_id.h:272-276` identifies that ID and `adkey_config.c:13-28` puts
  `u16 io_uuid` first in its payload. The payload begins at `+0x38` with
  `io_uuid = 0x4F49`, and the pinned
  `gpio_file_parse.c:60-65` maps `0x4F49` to `IO_PORTB_07`; `0x4F4A` is PB08.
  The target app contains the same `{0x17, 0x4F49}` / `{0x18, 0x4F4A}` mapping,
  and the BR35 GPADC header defines the special `AD_CH_IO_PB7` channel but no
  PB08 counterpart. The pinned `adc_io2ch()` returns
  `AD_CH_PMU_PADC0` / `0x0002030D` for PB07 and `UINT32_MAX` for PB08. Board
  code requires exact equality with its allowed 32-bit channel; it never uses
  stock's stale `!= 0xFF` validity test. A two-button chord aliases button 1 in
  the stock logical decoder, so the shipping recovery gesture will not use a
  chord.
- The model-1552 artifact contains two sequential configurations of the same
  PB07 PINR0 facility: packaged `isd_config.ini` sets
  `RESET = PB07_08_0` for the boot/pre-application window; early SDK startup
  disables it; then the PB07 AD-key record makes stock key initialization arm
  an eight-second reset. The custom-package contract requires
  `RESET = PB07_00_0;` (time `00`, disabled), and the board adapter must
  directly arm PB07 PINR0 for 16 seconds at runtime. The package tool does not
  encode a 16-second value. Produced artifacts must prove both settings.
  Physical model-1542 applicability remains **UNVERIFIED** until the PB07-only
  ADC probe.
- The current vendor layout and OTA chain are single-bank. JieLi's guidance does
  not support switching a deployed image from single-bank to dual-bank through
  OTA because that changes the partition/boot contract. This trial preserves
  the current single-bank layout. A/B is a later wired-repartitioning project,
  not an implied feature of this image.
- The SDK separates electrical charger handling from charging-page presentation.
  The custom image retains charger detection, charge start/close, full-charge,
  low-voltage, and wake handling, but it does not route charger events to
  `ID_WINDOW_BATCHARGE`, `IDLE_MODE_CHARGE`, or the stock charged-screen-saver
  policy. Exact charging pins, limits, NVDC behavior, and thermal characteristics
  remain board-profile facts that must be verified on sacrificial hardware.

Every target-sensitive fact and its source is recorded in the firmware
authoring guide. Implementation must preserve its **PROVEN**, **INFERRED**, and
**UNVERIFIED** labels rather than silently treating a comparison artifact as
model-1542 fact.

## 4. System architecture

The system has three intentionally narrow components.

### 4.1 Android controller

A dependency-light native Android application owns scanning, bonding,
reconnection, slider input, semantic packet encoding, and maintenance uploads.
It uses Android's `BluetoothGatt` APIs directly. The trial has no network
permission and no Factory API code.

The normal screen contains:

- selected badge and connection/bond state;
- Day slider and exact integer value;
- Week slider and exact integer value;
- read-only credit text `$17.27`;
- a `Sync` action and the result of the most recent acknowledged write;
- a compact link to the maintenance screen.

The maintenance screen recognizes only the badge's physically selected RCSP
update-mode advertisement. It uses Android's Storage Access Framework to select
a locally built update artifact, validates its manifest before connection,
displays size/build/profile information, and drives the official RCSP
authentication, loader download, and OTA exchange. It never attempts OTA
against the ordinary metrics service.

The app keeps a foreground reconnect worker only while the user enables badge
sync. On reconnect it sends the current slider state once. Duplicate state
packets are safe and idempotent.

### 4.2 Normal badge application

The badge application contains five isolated modules:

- `board`: clocks, board-profile ADC key input (PB07 in the decoded model-1552
  profile), battery input, JD9855 display, backlight,
  sleep, watchdog, and reset-source handling;
- `renderer`: strip-based RGB565 face and transient status overlays;
- `state`: validated RAM-only provider values and visible-mode state machine;
- `ble_control`: one bonded-peer policy and the small semantic GATT service;
- `maintenance`: early entry detector and a separate update-only BLE service.

No module reads stock UI resource files. Logos, glyphs, and Material Symbols are
converted at build time into compiled, size-bounded assets.

### 4.3 Build and packaging layer

The repository stores a small overlay and deterministic scripts rather than a
second mutable copy of the whole vendor SDK. The bootstrap script obtains the
official SDK at commit `d0167685d032d745d88fe50233302edd46941622`, verifies the
pin, applies the board/application overlay, invokes the PI32v2/r3 toolchain, and
records hashes of its inputs and outputs.

The build produces:

- a linked ELF and map for inspection;
- a normal packed AC707N `update.ufw` for subsequent single-bank rewrites;
- a Qix-wrapped transition package usable by the already proven vendor OTA path
  for the first installation;
- a machine-readable manifest containing profile ID, version, payload length,
  CRC, build ID, SDK commit, and toolchain hash;
- host-rendered golden PNGs and unit-test results.

Packaging scripts regenerate every CRC and container layer. They do not patch a
vendor binary in place.

## 5. Badge face and renderer

### 5.1 Geometry and style

The coordinate system is 360x360 with center `(180, 180)`. Rendering is clipped
to the physical circle.

- Background: black (`#000000`).
- Outer Day ring: radius 160 px, 22 px stroke, light gray (`#BFC3C7`).
- Inner Week ring: radius 130 px, 22 px stroke, white (`#FFFFFF`).
- Inactive tracks: the corresponding ring color at 18 percent luminance,
  preblended into RGB565.
- Both progress arcs begin at 12 o'clock and advance clockwise.
- Progress values are clamped to 0..100. Zero shows only the inactive track;
  100 closes the ring without a visible seam.
- Active arc ends are round. V1 uses solid fills without a gradient or shadow;
  the Apple-Watch resemblance comes from the proportions, tracks, and caps.
- The Day icon is Material Symbol `today`, centered on the outer ring's fixed
  12-o'clock start point `(180, 20)` in an 18x18 px box.
- The Week icon is Material Symbol `date_range`, centered on the inner ring's
  fixed 12-o'clock start point `(180, 50)` in an 18x18 px box.
- Icons stay at the start points; they never travel with the progress heads.
- The Devin SVG already in `assets/icons/devin.svg` is converted to a compiled
  alpha asset in a 96x96 px box centered at `(180, 166)`.
- The credit string uses a compiled Roboto Medium 30 px subset, centered at
  `(180, 240)`, and is formatted from integer cents as `$17.27`; floating-point
  currency formatting is not used.

### 5.2 Rendering mechanism

The renderer operates on twelve 360x30 horizontal strips at y origins
`0,30,...,330`. The first display probe uses one aligned `0x5460` RGB565 buffer
inside the existing `0x6000` LCD tail and serially waits for DBI idle before
every reuse. After that passes, production may render into one stock buffer
while DBI sends the other, but two buffers require a linker-proven `0xA8C0`
tail; no buffer is reused before its completion callback. Rings are drawn from
fixed-point distance/angle calculations with coverage antialiasing; rounded
caps are circles at the calculated arc endpoints. Compiled alpha masks provide
the logo, symbols, and a deliberately limited text glyph set.

The face redraws only when validated semantic state changes, when a transient
overlay begins or ends, or after display wake. Receiving BLE bytes never invokes
the vendor receiving animation. The badge keeps the last face in RAM during an
ordinary BLE disconnect. A cold boot or non-retentive sleep discards it.

### 5.3 Transient screens

- No bond: `PAIR ME NOW` and a hint to hold button 1.
- Existing bond but no values since boot: `WAITING FOR PHONE`.
- Pairing window: `PAIRING` with a simple countdown; no QR code is required.
- Battery tap: dim the current background and show a large integer percentage
  for 2.5 seconds, with a compiled `bolt` glyph when the charger reports
  charging or full, then restore the prior screen.
- Update countdown: from 7 through 10 seconds show `KEEP HOLDING FOR UPDATE`
  and a visible countdown.
- Update mode: `READY TO UPDATE — RELEASE BUTTON`, battery percentage, and
  connection/progress/error state. This UI uses only compiled fallback glyphs
  and has no filesystem dependency.

## 6. Normal BLE protocol

The normal application advertises the local name `E87` and only its normal
custom service. Its service UUID is
`e87d0001-7a1b-4c62-9f0b-5d9c01a70735`; the semantic-state characteristic UUID
is `e87d0002-7a1b-4c62-9f0b-5d9c01a70735` and permits an encrypted,
non-MITM write-with-response under Just Works bonding. The badge accepts
state writes only after link encryption is established for its remembered peer.

The v1 state packet is exactly eight bytes:

| Byte(s) | Meaning |
|---|---|
| 0 | protocol version, exactly `1` |
| 1 | Day integer, `0..100` |
| 2 | Week integer, `0..100` |
| 3 | flags, exactly `0` in v1 |
| 4..7 | credit in cents, unsigned 32-bit little-endian; must be exactly `1727` in v1 |

Android always encodes the little-endian v1 credit value as `1727`
(`0xBF 0x06 0x00 0x00`); it has no dynamic-credit path in v1.

The badge rejects every other length, version, out-of-range percentage, v1
flags value, or v1 credit value other than `1727` without changing visible
state. A valid packet is copied into a
temporary structure and committed atomically before redraw. There is no normal
packet sequence number: the packet is a complete idempotent snapshot, GATT
writes are acknowledged, and stale intermediate state is not meaningful.

Future dynamic credit requires a new protocol version; v1 must never
reinterpret a non-1727 credit value.

The badge also exposes the standard Battery Service (`0x180F`) and Battery Level
characteristic (`0x2A19`) for optional read/notification. Battery reporting does
not alter the eight-byte provider packet.

A read-only build-info characteristic at
`e87d0003-7a1b-4c62-9f0b-5d9c01a70735` requires an encrypted read and returns exactly 40 bytes:
schema byte `1`; one capability byte; the NUL-padded 16-byte ASCII profile
`E87-JD9855-R1`; semantic-version major, minor, and patch bytes; one reserved
zero byte; a 16-byte raw build ID; and two reserved zero bytes.
Android checks this value after every normal connection and after an update
reboot. A successful encrypted build-info read is the Android gate before it
enables or attempts an encrypted semantic-state write.
Capability bit 0 means semantic metrics, bit 1 means Battery Service, and bit 2
means physically gated RCSP rewrite; all remaining bits are zero in v1.

Bonding uses BLE `Just Works` with one remembered peer. The bond is the only
ordinary persistent application state. A replacement peer is accepted only
during the physical pairing window; the previous bond is removed only after the
new bond succeeds. Normal advertising does not permit an unknown peer to claim
the badge.

Just Works establishes link encryption but deliberately provides no MITM
protection.

## 7. Button, pairing, sleep, and recovery behavior

### 7.1 Button 1 duration state machine

The user-facing controls are named `Sync/Pair` (button 1) and `Sleep` (button
2). Their physical left/right positions and mapping to ADC key0/key1 are a board
profile value measured before flashing the interactive build; pure state-machine
code does not hard-code a GPIO. The Sync/Pair button is timed from stable raw
samples from the measured board profile (PB07 for decoded model 1552), rather
than stock LONG/HOLD events. One monotonic timer survives the transition into
pairing mode.

- Release before 3.0 seconds: treat as a tap and show the battery overlay.
- Cross 3.0 seconds: fire pairing exactly once and continue timing while held.
- Cross 7.0 seconds: replace the pairing screen with the update warning and
  three-second countdown.
- Cross 10.0 seconds: fire maintenance entry exactly once.
- Any release between 3.0 and 10.0 seconds leaves the 60-second pairing window
  active but cancels maintenance entry.

At the 10-second event the firmware disables the pending PB07 pin-reset timer,
waits for button release while feeding the watchdog, re-arms the 16-second
fallback, and enters the application-side RCSP maintenance service. Pairing
advertisements and the normal metrics service are shut down first. This state is
not the downloaded update loader; loader handoff happens only after the host
exchange described in section 9.

### 7.2 Hardware reset and early recovery

The custom-package contract sets the generated reset time to `00`, so its
`isd_config.ini` contains disabled `RESET = PB07_00_0;` rather than an
eight-second boot/pre-application reset. Immediately after `boot_power_init()`,
firmware records the reset cause, explicitly disables PINR0, and takes the
early-recovery branch before filesystem, resource, display, or normal BLE
startup. On an ordinary boot, custom code directly arms PB07 PINR0 at 16
seconds; it does not let stock AD-key initialization install the model-1552
eight-second policy. Runtime 16 seconds is used because the PINR implementation
accepts it even though the package RESET grammar only accepts `00/01/02/04/08`.
The measured-profile board adapter uses
`gpio_longpress_pin0_reset_config(IO_PORTB_07, 0, 16, 1, 1)`; the inspected
implementation encodes active-low, `release = 1` PINR16 as `0x43`.
The adapter exact-allowlists the implementation's explicit 1/2/4/8/16-second
mappings. Time 0 disables PINR0 and `UINT32_MAX` leaves it unchanged; other
values outside the explicit set are not generally rejected and can fall through
to a raw shift.

If a healthy runtime handles the 10-second event, it enters update mode normally.
If the runtime is hung, holding button 1 reaches the 16-second PB07 hardware reset.
On the next boot, the earliest application path records and tests
`P33_PPINR_RST`; that reset cause bypasses normal resources and enters the
application-side maintenance service directly. PB07 PINR stays disarmed until
the held key is released, while the watchdog is fed, to avoid another reset.
GPIO/ADC, clocks, reset-cause recording, and watchdog feeding are the only
prerequisites for this route. The reset-source bit records a pin-reset cause;
the early application logic, not the hardware bit itself, selects maintenance.
The selected key and PB07 electrical behavior are still **UNVERIFIED for the
physical model-1542** until badge B in the hardware ladder measures them.

This is soft recovery. If the image cannot execute the early hook, or boot
metadata/bootloader code is destroyed, the buttons cannot repair it; physical
MaskROM recovery is required.

### 7.3 Button 2 and sleep

A short button-2 event drains DBI, turns the backlight off, sends display-off
(`28`) then sleep-in (`10`), waits at least 120 ms, releases the LCD clock,
disconnects BLE, and enters the lowest verified wakeable power state. Pressing
button 2 reacquires the clock, applies the recovered high-10/low-10/high-100-ms
reset, replays the exact init, redraws while dark, and enables backlight last.
The recovered stock path has no separate panel-rail callback. If the selected
state retains RAM, the last face is redrawn; otherwise the badge cold-boots to
`WAITING FOR PHONE` or `PAIR ME NOW` and the phone reconnect worker resends
current values. Metrics are never written to flash to hide this distinction.
V1 has no ordinary inactivity timeout: button 2 is the only user-level path
into sleep, although low-voltage and hardware safety logic may still force a
protected shutdown.

The power policy records whether sleep was entered explicitly by button 2.
That `manual_sleep` state remains authoritative across charger insertion and
removal: external power never wakes a manually sleeping badge, but button 2
always can.

### 7.4 Charge-through display mode

Charger presence is an input to the normal application state machine, not a UI
mode. The board adapter derives one `external_power` boolean from the SDK's
charger-online signal and separately reports `charging`, `full`, or `fault` for
the overlay and diagnostics; higher layers never read target RAM addresses
directly. Booting with external power present follows the ordinary E87 boot path,
shows `PAIR ME NOW`, `WAITING FOR PHONE`, or the current semantic face as
appropriate, and starts the normal BLE service. It does not enter
`IDLE_MODE_CHARGE`.

On charger insertion, firmware executes the board's ordinary electrical charge
start path without hiding the current screen, showing `ID_WINDOW_BATCHARGE`,
disconnecting BLE, clearing semantic state, or resetting the application. If
`manual_sleep` is set, the badge remains asleep until button 2 is pressed.

While external power remains present and `manual_sleep` is clear, stock
screen-saver, backlight-timeout, panel-sleep, and application auto-shutdown
transitions are inhibited. The display stays at its normal configured
brightness, BLE remains connectable, and semantic writes continue to redraw the
face. This does not force periodic redraws and does not change charger current
control, charge termination, full-charge detection, low-voltage protection, or
any verified hardware safety mechanism.

Button 2 sets or clears `manual_sleep` while plugged in using the same panel and
BLE sleep/wake sequence as on battery; it does not stop charging. Charger events
also never preempt pairing, countdown, or application-side maintenance UI. After
loader handoff, the persistent loader owns presentation and its plugged-power
behavior is verified separately. On unplug, the current visible/application
state is preserved and ordinary battery-powered low-voltage protection remains
active without a page change or reboot. A manually sleeping badge remains
asleep; an awake badge continues running until button 2 or a safety condition
stops it.

## 8. Battery behavior

Battery percentage is computed locally from filtered voltage, not the separate
curve present in `cfg_tool.bin`. The recovered model-1552 runtime takes eight
half-VBAT readings, doubles them, sorts them, drops the minimum and maximum, and
averages the middle six. V1 preserves the target's integer arithmetic exactly:
convert each half-VBAT reading to millivolts, sum sorted samples 1 through 6,
then compute `filtered_mv = sum / 6` with truncating integer division. It must
not round to nearest or use a ties-up rule. V1 starts with the runtime's
discharge table:

`3565:1, 3625:10, 3660:20, 3693:30, 3737:40, 3797:50, 3866:60, 3971:70,
4073:80, 4188:90, 4280:100`, with zero below the first point and interpolation
between points. For bracket `(v0, p0)..(v1, p1)`, interpolation is
`p0 + ((filtered_mv - v0) * (p1 - p0)) / (v1 - v0)`, again using truncating
integer division. Exact table points remain exact; values above the last point
clamp to 100.

The target also contains a higher-voltage charging/alternate table, but the
charger topology on the physical model-1542 is not established, so V1 uses the
discharge table both plugged and unplugged and does not pretend it has a coulomb
count or reliable charging compensation. Before release, the discharge table
and ADC scale are checked against DMM readings at several loads and adjusted in
the board profile if measured evidence requires it.

The battery overlay uses the calibrated voltage-derived integer percentage and
separately shows the hardware charging/full state with the `bolt` glyph. It does
not claim remaining time or coulomb-count accuracy. Charging-table selection is
enabled only after its relationship to the physical model-1542 has been measured.

The maintenance screen remains reachable at any battery level so it can explain
the problem, but loader handoff is refused below the calibrated 50-percent point
or during a low-voltage warning. The normal face remains functional below that
threshold.

## 9. Firmware maintenance and rewrite policy

Application-side update mode advertises the local name `E87 UPDATE`, disables
the metrics service, and starts only the Bluetooth and RCSP pieces required by
JieLi's BLE application updater. The custom build fixes this maintenance profile
to service `AE00`, host-write characteristic `AE01`, and device-notify
characteristic `AE02`, matching the already proven Android probe. The update
screen is ours; no stock UI/resource task is started.

The 10-second button handler does **not** call `update_mode_api_v2()` directly.
In the official single-bank flow the host must first authenticate and complete
the RCSP E1/E2 inquiry and loader-download exchange. Only a successful loader
download establishes a valid loader address; the subsequent update-start path
writes CRC-protected update parameters and resets into that loader. Calling the
mode API early can reset with an unset loader address and is forbidden.

The Android maintenance module therefore performs this sequence:

1. Parse the Qix wrapper when present, extract the `update.ufw`, and verify every
   declared length and CRC before connecting.
2. Compare the adjacent build manifest's board-profile ID, AC707N chip ID,
   version, payload hash, and size with the selected badge profile.
3. Connect only to a badge advertising the physically selected maintenance
   mode, enable `AE02` notifications, negotiate MTU, and complete RCSP mutual
   authentication.
4. Query target/update capability and verify it is the expected single-bank,
   bootloader-assisted path.
5. Let the ordinary RCSP host exchange download and validate the loader, then
   start the firmware transfer. The app displays acknowledged byte/progress
   state and never sends two chunks concurrently.
6. If the target has already handed off to the persistent loader, recognize its
   `*_update` or `*_LE_UPDATE` advertisement, reconnect, and resume the same
   validated artifact rather than starting a different image.
7. Accept success only after the target reports verification/update success and
   reconnects to the normal service with the expected build-info value.

Maintenance mode may advertise below 50 percent so recovery remains observable,
but it refuses loader handoff, times out after two minutes without an
authenticated host, and returns to normal boot on explicit cancel. After loader
handoff, the old application can become unavailable, but the JieLi loader is
designed to persist, advertise its update identity, and accept reconnection and
resume. The Android app shows this boundary clearly, keeps the screen awake,
and automatically follows the loader advertisement. MaskROM is required only
if the loader/update record itself fails or cannot be reached; single-bank is
still less fault-isolated than A/B.

Subsequent custom images retain the same early 3/10/16-second maintenance path,
the same RCSP profile, and the same partition contract, allowing repeated
single-bank rewrites. Moving to A/B requires a separately designed and
validated wired/programmer migration; it is outside this trial.

## 10. Failure handling

- Invalid semantic packets leave the current face unchanged and return a GATT
  application error.
- BLE disconnect during normal operation leaves the last RAM face visible.
- BLE disconnect before loader handoff returns to application-side maintenance
  advertising. A disconnect after handoff may leave the normal application
  unavailable; Android reconnects to the persistent loader and resumes the
  validated artifact.
- Display initialization failure keeps the backlight off and leaves BLE/update
  recovery reachable; it must not enter a reset loop.
- Charger insertion, charge start, full-charge, charge close, and unplug events
  preserve the current application/UI state. A charger event must never invoke
  the stock charging page or erase the RAM-only semantic face.
- A failed or unavailable charger-status input falls back to ordinary
  awake/manual-sleep presentation policy and omits the `bolt` glyph; it must not
  alter electrical charging controls or suppress low-voltage protection.
- Watchdog resets are recorded for diagnosis but do not masquerade as the
  deliberate `P33_PPINR_RST` maintenance-entry cause.
- Low voltage blocks loader handoff. If voltage fails after handoff, the next
  charged session reconnects to the persistent loader and resumes; MaskROM
  remains the fallback if that loader is not reachable.
- Android reports every manifest rejection, authentication failure, loader
  failure, transfer/CRC failure, timeout, and reconnect/version mismatch in
  plain language and retains a local diagnostic log that contains no bond keys
  or credentials.

## 11. Verification strategy

### Host-side gates, runnable while the badge charges

- Java tests for the exact eight-byte state codec, boundary values, malformed
  packets, and idempotent resend behavior.
- Firmware C tests for packet validation, atomic state commit, the 3/7/10/16
  timing state machine, reset-source routing, truncating battery average and
  interpolation, maintenance entry, every pre-loader abort path, and all
  combinations of external power and `manual_sleep`.
- Golden renders for 0, 1, 50, 99, and 100 percent on both rings, plus battery,
  pairing, countdown, and update screens. Pixel tests check fixed icons,
  clockwise geometry, round caps, clipping, and credit formatting.
- Android APK assemble, install, and launch on the connected Redmi 9T.
- Firmware compile/link, map inspection, stack/heap budget check, and proof that
  the serial `0x5460` buffer fits without PSRAM; production promotion separately
  proves the `0xA8C0` exact-stock double-buffer reservation.
- Container unpack/repack verification, hashes, profile check, Qix wrapper CRC,
  and an exact single-bank loader/update dry run using the output artifact.
- Static checks proving normal firmware has no stock UIRES dependency and the
  Android normal path cannot invoke update writes. A link/source assertion also
  proves that charger events cannot select `ID_WINDOW_BATCHARGE` or
  `IDLE_MODE_CHARGE` in the E87 application.

### Charged five-badge hardware ladder

Assign and label the five physical badges before the first write; do not reuse a
later-stage unit to make an earlier probe appear recoverable. Mark badge E as
untouched before badge A is written:

1. **Badge A — current heartbeat unit.** Flash only the nonconnectable BLE
   heartbeat image through the proven vendor transition path. It contains no
   display, key, battery, filesystem, or recovery behavior. Prove boot,
   advertisement identity/build tag, cadence, and watchdog restart.
2. **Badge B — PB07 ADC telemetry unit.** Flash a one-input lab image that
   configures only PB07 and publishes raw released/button-1/button-2/both
   samples plus the full 32-bit channel value in nonconnectable advertisements.
   Require exact `AD_CH_PMU_PADC0` equality before sampling. Measure clusters
   and noise before assigning physical buttons or enabling a long hold. Do not
   probe PB08 as an ADC substitute: the pinned model-1552 mapping and GPADC
   surface select PB07.
3. **Badge C — JD9855 display unit.** Flash the conservative panel probe only
   after badge A boots. With backlight off, compare rails, exact pins, reset,
   and current to the untouched reference, then replay only the hashed init.
   Serially issue black/white/red/green/blue `lcd_clear` operations with
   `lcd_wait_busy`, followed by twelve independently addressed 360x30 strips
   from one `0x5460` buffer, including final y=330. Validate coordinates,
   clipping, orientation, color/byte order, and tearing before enabling
   completion-callback double buffering, TE synchronization, or
   `lcd_draw_continue`. Then validate backlight, exact panel sleep/wake order,
   current, and 100 wake cycles. It does not enable buttons, normal GATT, or
   recovery gestures.
4. **Badge D — full/recovery candidate.** Build the measured PB07 board profile
   from badge B and the display profile from badge C, then validate tap,
   pairing, countdown, 10-second maintenance, direct runtime PB07 PINR16, and
   the `P33_PPINR_RST` early route. Compare battery voltage with a DMM; validate
   truncating percentage arithmetic, overlay timeout, and charging glyph. Bond
   the Redmi, send boundary metric packets, disconnect/reconnect silently, and
   verify no receiving graphic appears.
5. **Badge E — untouched reference.** Never flash it. Retain the strongest
   available vendor recovery artifacts and benign identity observations.
   Inability to read stock flash does not block host builds, but deliberate
   interruption tests still require confirmed MaskROM access or another proven
   restore route.
6. On badge D, test boot while plugged in, insertion/removal while awake and
   manually asleep, button-2 sleep/wake while charging, charge completion, and
   metric writes throughout. Run an eight-hour plugged-in display-and-BLE soak
   while logging current, battery voltage, enclosure/battery temperature,
   charger state, disconnects, and unintended page or sleep transitions. Stop
   immediately on abnormal heat, charge-current behavior, swelling, or odor.
7. On badge D, exercise every pre-loader cancel point. Only after preserving a
   recovery route, interrupt a loader transfer, rediscover its update
   advertisement, resume the same artifact, boot it, and complete a second
   single-bank rewrite to prove the staged path is reusable.
8. Repeat normal sync and update tests on the Z Fold 7 only after badge D passes
   Redmi validation. Badge E remains untouched throughout.

Any failure stops the ladder at that stage. Results, hashes, current draw,
photos, and captured BLE traces are appended to the firmware authoring guide or
the work log before advancing.

## 12. Acceptance criteria

The trial is complete when:

- the Redmi app installs and can bond with a custom badge;
- moving either slider to any integer 0..100 and tapping `Sync` changes the
  corresponding locally rendered ring without transferring an image;
- the displayed face matches the defined geometry, colors, icons, Devin mark,
  and `$17.27` credit string;
- normal metric syncs are silent and do not show vendor receiving graphics;
- a button-1 tap shows battery for 2.5 seconds, a 3-second hold opens pairing,
  and a continued 10-second hold enters update mode;
- a deliberately hung runtime reaches update mode through the 16-second reset
  and reset-source early-boot route;
- button 2 sleeps and wakes the device with the documented RAM-retention result;
- booting or inserting external power never replaces the normal face with a
  charging page; while plugged in and not manually asleep, the face and BLE
  remain active through an eight-hour soak and continue accepting metric writes;
- button 2 can manually sleep and wake the badge while it continues charging,
  and unplugging preserves the awake/manual-sleep state without rebooting or
  changing the current face;
- every pre-loader cancel returns safely to maintenance or normal mode, and an
  interrupted post-handoff transfer reconnects to the loader and resumes;
- a verified single-bank update boots, and the new image accepts another update;
- the build is reproducible from the pinned SDK/toolchain inputs and all
  hardware-sensitive unknowns are either measured or still explicitly labeled.
