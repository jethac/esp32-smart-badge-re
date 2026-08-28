# E87 Badge Firmware Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a UIRES-free AC707N/BR35 firmware overlay that renders the Devin rings locally, accepts the exact semantic BLE packet, supports staged pairing/rewrite recovery, and keeps the face/BLE active while charging.

**Architecture:** Pure C state, timing, battery, power, and rendering modules are host-tested independently, then compiled through a small overlay against a pinned JieLi SDK. The display uses direct BR35 DBI APIs and twelve 360x30 strips: the hardware ladder starts serially with one stock-size buffer, while exact-stock callback double buffering is a separately map-proven promotion. Normal BLE and application-side RCSP maintenance are mutually exclusive modes controlled by one application state machine.

**Tech Stack:** C11 host tests with Clang, Python 3.11 asset/golden/static tests, JieLi AC707N SDK commit `d0167685d032d745d88fe50233302edd46941622`, PI32v2/r3 target compiler, direct `app_ble_*` and BR35 DBI APIs.

**Spec:** `docs/superpowers/specs/2026-08-27-e87-local-rendering-trial-design.md`

## Global Constraints

- Target chip is AC707N/BR35, entry `0x0C000100`, profile `E87-JD9855-R1`, direct-DBI display 360x360 RGB565, physical radius 180. The stock phone path's 368x368 JPEG upload target is not panel geometry.
- Normal BLE accepts only the exact eight-byte no-sequence v1 snapshot and acknowledges duplicates without redrawing.
- Renderer uses no full framebuffer, heap allocation, floating point, `libm`, PSRAM, filesystem, stock UI, JLUI, LVGL, touch, audio, or stock `UIRES`.
- One aligned stock strip buffer is `360*30*2 = 0x5460` and fits the existing `0x6000` linker tail for serial bring-up. Exact stock double buffering is `2*0x5460 = 0xA8C0`; enabling callback streaming requires a larger, independently map-proven reservation.
- Button 1 fires tap, pairing, warning, and maintenance at release-before-3s, 3s, 7s, and 10s; PB08/16s pin-reset recovery is an early-boot fallback. Button 2 is the only ordinary sleep control.
- Charger electrical detection/start/full/close and safety remain enabled. The E87 application never selects `ID_WINDOW_BATCHARGE`, `ID_WINDOW_BEDSIDE_WATCH`, `IDLE_MODE_CHARGE`, or charger-triggered soft-off; Button 2 never calls `charge_close()`.
- V1 is single-bank only. A physical gesture never calls `update_mode_api_v2()`; only the official verified-loader handler may call it after a nonzero loader address and power/profile gates pass.
- Only bond ownership and its crash-safe owner record persist. Day, Week, credit, face pixels, visible state, and `manual_sleep` remain RAM-only.
- Hardware facts recovered from model 1552 remain labeled `INFERRED` for model 1542 until the sacrificial ladder confirms them. The user accepts a sacrificial write without stock readback; preserve an untouched badge and confirm MaskROM access before custom transfer.
- The trial spec's eight-byte no-sequence protocol is normative. The authoring guide's generic proposed sequence protocol is not used for v1.

---

## File Map and Stable Interfaces

```text
firmware/
  sdk.lock.json
  board-profiles/E87-JD9855-R1.json
  assets/sources/{devin.svg,Roboto[wdth,wght].ttf,today.svg,date_range.svg,bolt.svg,jd9855-init.raw.bin}
  assets/licenses/*
  assets/asset-lock.json
  generated/{e87_assets.c,e87_assets.h,assets-manifest.json,goldens/*.png}
  overlay/SDK/apps/watch/include/e87/*.h
  overlay/SDK/apps/watch/e87/*.c
  overlay/SDK/apps/watch/board/br35/board_e87_1542/*
  patches/0001-e87-board-build.patch
  patches/0002-e87-app-charge-recovery.patch
  patches/0003-e87-ble-maintenance.patch
  patches/0004-e87-linker-dbi.patch
  host/{test_main.c,test_support.h,test_*.c,fakes/*}
  tests_py/test_*.py
  tools/{test-host.ps1,fetch-assets.ps1,extract-panel-init.py,gen-assets.py,render-goldens.py,source-audit.py,check-map.py}
```

Stable pure-C interfaces:

```c
struct e87_metrics { uint8_t day; uint8_t week; uint32_t credit_cents; };
enum e87_state_error e87_state_decode(const uint8_t *packet, size_t length,
                                      struct e87_metrics *out);
bool e87_state_commit(struct e87_state_store *store,
                      const struct e87_metrics *next);

uint32_t e87_button_step(struct e87_button_fsm *fsm, uint32_t now_ms,
                         enum e87_key_class sample);
uint16_t e87_battery_filter_half_mv(const uint16_t samples[8]);
uint8_t e87_battery_percent_from_mv(uint16_t millivolts);
uint32_t e87_power_step(struct e87_power_state *state,
                        const struct e87_power_event *event);

int e87_render_strip(const struct e87_render_model *model, uint16_t y,
                     uint8_t rows, uint16_t pixels[360 * 30]);
int e87_render_frame(const struct e87_render_model *model,
                     struct e87_strip_sink *sink);
```

### Task 1: Create the firmware overlay and host-test harness

**Files:**
- Create: `firmware/sdk.lock.json`
- Create: `firmware/tools/test-host.ps1`
- Create: `firmware/host/test_support.h`
- Create: `firmware/host/test_main.c`
- Create: `firmware/overlay/SDK/apps/watch/include/e87/e87_types.h`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: host Clang and pinned SDK identity.
- Produces: one command that compiles selected pure firmware sources with `-std=c11 -Wall -Wextra -Werror -pedantic` and runs named/all suites.

- [ ] **Step 1: Write a failing harness self-test**

```c
E87_TEST(harness_reports_assertions) {
    E87_ASSERT_EQ_U32(0x5460u, 360u * 30u * 2u);
}
```

- [ ] **Step 2: Run before scaffolding**

Run: `.\firmware\tools\test-host.ps1 -Suite harness`

Expected: FAIL because the script and harness do not exist.

- [ ] **Step 3: Implement the minimal runner**

The PowerShell script resolves Clang, creates `build/firmware-host`, compiles only allowlisted sources with `-DE87_HOST_TEST=1`, runs the executable, and propagates a nonzero exit code. It never compiles SDK proprietary objects in host tests.

- [ ] **Step 4: Pin SDK identity**

`sdk.lock.json` contains URL `https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200.git`, commit `d0167685d032d745d88fe50233302edd46941622`, tree `854734595be49510aca5afb89f5885e8bce6a00f`, chip `AC707N`, architecture `pi32v2`, CPU `r3`.

- [ ] **Step 5: Run and commit**

```powershell
.\firmware\tools\test-host.ps1 -Suite harness
git add .gitignore firmware
git commit -m "build(firmware): add E87 host-test overlay"
```

### Task 2: Implement semantic state and exact build info

**Files:**
- Create: `firmware/overlay/SDK/apps/watch/include/e87/e87_state.h`
- Create: `firmware/overlay/SDK/apps/watch/e87/e87_state.c`
- Create: `firmware/overlay/SDK/apps/watch/include/e87/e87_build_info.h`
- Create: `firmware/overlay/SDK/apps/watch/e87/e87_build_info.c`
- Test: `firmware/host/test_state.c`

**Interfaces:**
- Consumes: eight-byte packet and compile-time semver/build ID.
- Produces: atomic metrics commit and exact 40-byte GATT build record.

- [ ] **Step 1: Write valid and malformed decode tests**

```c
static void exact_vector(void) {
    const uint8_t p[8] = {1, 100, 0, 0, 0xbf, 0x06, 0, 0};
    struct e87_metrics m = {0};
    E87_ASSERT_EQ_INT(E87_STATE_OK, e87_state_decode(p, sizeof p, &m));
    E87_ASSERT_EQ_U32(100, m.day);
    E87_ASSERT_EQ_U32(1727, m.credit_cents);
}
```

V1 accepts only `credit_cents == 1727`, encoded as
`0xBF 0x06 0x00 0x00`. Dynamic credit requires a protocol-version change.
For every invalid length, version, percentage, flag, and credit encoding other
than `0xBF 0x06 0x00 0x00`, initialize `out` with `0xA5`, and assert it
remains byte-identical.

- [ ] **Step 2: Implement decode-then-copy and commit semantics**

Decode into a local temporary; copy to `out` only after all checks, including
the fixed v1 credit. `e87_state_commit` returns false for an identical state,
true for a changed state, and uses the target spinlock adapter for
commit/snapshot.
A packet with any other credit value is rejected without copying to `out` or
committing visible state; only a fully valid `1727`-cent packet commits
atomically.

- [ ] **Step 3: Write 40-byte record tests**

Assert schema 1, capabilities `0x07`, exact 16-byte NUL-padded `E87-JD9855-R1`, semver, reserved zeros, and the raw 16-byte content-derived build ID.

- [ ] **Step 4: Implement build-info serialization and run**

Run: `.\firmware\tools\test-host.ps1 -Suite state`

Expected: PASS, including duplicate commit without redraw request.

- [ ] **Step 5: Commit**

```powershell
git add firmware/overlay/SDK/apps/watch/include/e87/e87_state.h firmware/overlay/SDK/apps/watch/include/e87/e87_build_info.h firmware/overlay/SDK/apps/watch/e87/e87_state.c firmware/overlay/SDK/apps/watch/e87/e87_build_info.c firmware/host/test_state.c
git commit -m "feat(firmware): add semantic state contract"
```

### Task 3: Implement button timing, pairing window, and recovery policy

**Files:**
- Create: `firmware/overlay/SDK/apps/watch/include/e87/e87_button_fsm.h`
- Create: `firmware/overlay/SDK/apps/watch/e87/e87_button_fsm.c`
- Create: `firmware/overlay/SDK/apps/watch/include/e87/e87_recovery.h`
- Create: `firmware/overlay/SDK/apps/watch/e87/e87_recovery.c`
- Test: `firmware/host/test_button_fsm.c`
- Test: `firmware/host/test_recovery.c`

**Interfaces:**
- Consumes: stable raw PB08 key class and unsigned monotonic milliseconds.
- Produces: one-shot action bits and an early PINR recovery route independent of filesystem/UI.

- [ ] **Step 1: Write exact boundary and release tests**

Cover 2999/3000, 6999/7000, 9999/10000 ms, releases below 3s and between 3-10s, missed scheduler jumps, key bounce, ambiguous ADC samples, repeated calls, and `uint32_t` timer wrap. A jump across multiple thresholds emits actions in pairing→warning→maintenance order once.

- [ ] **Step 2: Implement the pure FSM**

```c
enum e87_button_action {
    E87_ACTION_TAP_BATTERY       = 1u << 0,
    E87_ACTION_OPEN_PAIRING      = 1u << 1,
    E87_ACTION_UPDATE_WARNING    = 1u << 2,
    E87_ACTION_ENTER_MAINTENANCE = 1u << 3,
    E87_ACTION_SLEEP_TOGGLE      = 1u << 4,
};
```

Treat `NONE`/`AMBIGUOUS` as release; button 2 emits one toggle on stable press and has no hold action.

- [ ] **Step 3: Write recovery call-order tests**

Inject reset causes and fake GPIO/WDT calls. `P33_PPINR_RST` must latch after `boot_power_init`, disarm PINR, initialize only clock/GPIO/ADC/WDT, feed WDT until button release, arm PB08/16, then request maintenance. Other reset causes take normal boot.

- [ ] **Step 4: Implement recovery adapter**

Healthy 10s handling disarms PINR with time zero, closes normal BLE asynchronously, waits for release while feeding WDT, calls `gpio_longpress_pin0_reset_config(IO_PORTB_08, 0, 16, 1, 1)`, then starts maintenance.

- [ ] **Step 5: Run and commit**

```powershell
.\firmware\tools\test-host.ps1 -Suite button
.\firmware\tools\test-host.ps1 -Suite recovery
git add firmware/overlay/SDK/apps/watch firmware/host/test_button_fsm.c firmware/host/test_recovery.c
git commit -m "feat(firmware): add staged button recovery"
```

### Task 4: Implement battery filtering and charge-through power policy

**Files:**
- Create: `firmware/overlay/SDK/apps/watch/include/e87/e87_battery.h`
- Create: `firmware/overlay/SDK/apps/watch/e87/e87_battery.c`
- Create: `firmware/overlay/SDK/apps/watch/include/e87/e87_power_policy.h`
- Create: `firmware/overlay/SDK/apps/watch/e87/e87_power_policy.c`
- Create: `firmware/overlay/SDK/apps/watch/e87/e87_charge_adapter.c`
- Test: `firmware/host/test_battery.c`
- Test: `firmware/host/test_power_policy.c`
- Test: `firmware/host/test_charge_adapter.c`

**Interfaces:**
- Consumes: eight half-VBAT samples, charger-online boolean, charge status events, button-2 action.
- Produces: local percentage and panel/BLE sleep/wake actions without charger-control actions.

- [ ] **Step 1: Write battery tests**

Test every permutation of representative samples, duplicate extrema, overflow-safe doubling, all discharge knots, below-minimum zero, above-maximum 100, and every interpolation interval. Freeze rounding to nearest integer with ties upward.

- [ ] **Step 2: Implement the recovered filter/table**

Sort eight doubled `uint16_t` values, drop index 0 and 7, sum six in `uint32_t`, and round `sum/6`. Use exact knots:

```c
{3565,1},{3625,10},{3660,20},{3693,30},{3737,40},{3797,50},
{3866,60},{3971,70},{4073,80},{4188,90},{4280,100}
```

- [ ] **Step 3: Write the full power reducer matrix**

State fields are `external_power`, `charge_status`, `manual_sleep`, `awake`, and visible mode. Test plugged boot, insert/remove awake/manual-sleep, START→FULL→CLOSE while online, KEEP/fault, pairing/countdown/maintenance preservation, and Button 2 while plugged. The action mask contains display/BLE sleep, wake, redraw, and diagnostic only; no electrical charge action exists.

- [ ] **Step 4: Implement `e87_power_step`**

Derive `external_power` from `get_charge_online_flag()`, not from CLOSE/FULL event names. Button 2 toggles `manual_sleep` and awake state; unplug never reboots or changes the face/sleep latch. V1 has no inactivity timer.

- [ ] **Step 5: Implement and statically test the SDK charge adapter**

Retain `charge_start_deal`, full/close, LDO5V IN/OFF/KEEP electrical paths. Under `CONFIG_E87_BADGE`, replace stock UI/mode calls with an `e87_power_event` post. A source test rejects E87-reachable `ID_WINDOW_BATCHARGE`, `ID_WINDOW_BEDSIDE_WATCH`, `IDLE_MODE_CHARGE`, ordinary-unplug softoff, and button-2 `charge_close`.

- [ ] **Step 6: Run and commit**

```powershell
.\firmware\tools\test-host.ps1 -Suite battery
.\firmware\tools\test-host.ps1 -Suite power
git add firmware/overlay/SDK/apps/watch firmware/host/test_battery.c firmware/host/test_power_policy.c firmware/host/test_charge_adapter.c
git commit -m "feat(firmware): add battery and charge-through policy"
```

### Task 5: Pin, fetch, and generate visual assets

**Files:**
- Create: `firmware/assets/asset-lock.json`
- Create: `firmware/tools/fetch-assets.ps1`
- Create: `firmware/tools/gen-assets.py`
- Create: `firmware/assets/sources/*`
- Create: `firmware/assets/licenses/*`
- Generate: `firmware/generated/e87_assets.c`
- Generate: `firmware/generated/e87_assets.h`
- Generate: `firmware/generated/assets-manifest.json`
- Test: `firmware/tests_py/test_assets.py`

**Interfaces:**
- Consumes: pinned SVG/font sources.
- Produces: 8-bit alpha masks and bitmap glyph metrics used byte-for-byte by firmware and golden renderer.

- [ ] **Step 1: Write source-lock tests**

Pin these exact inputs:

| Asset | Repository commit/path | SHA-256 |
|---|---|---|
| Devin | See source lock below | See source lock below |
| Roboto variable | `google/fonts` `6a003b5eb672dc8bf5bff5937cf5863f8b175445`, `ofl/roboto/Roboto[wdth,wght].ttf` | `D7598E12C5DBEF095FF8272CFC55DA0250BD07FBDECBAC8A530B9B277872A134` |
| today rounded | `google/material-design-icons` `e083cc60a0828fdd3b404cea0cb8a5b900e9c23e`, `symbols/web/today/materialsymbolsrounded/today_24px.svg` | `C2AA056CC2353CE349BEA6657053370DFBBD38DD96C0E52217615AAF02A1FA04` |
| date_range rounded | same commit, `symbols/web/date_range/materialsymbolsrounded/date_range_24px.svg` | `342EF493B1D94132215AB4F25D90CBAB34B448A39F50DB1E929317CE8F28AB04` |
| bolt rounded | same commit, `symbols/web/bolt/materialsymbolsrounded/bolt_24px.svg` | `13195A03D22906CA3C7A78FC6E104CB269B98DDAC7DCA96C424FADC623C33F3C` |

The Devin source is `jethac/factory-smartscreen` commit
`3feec00b8a9aa8c6874ca92477e4ed43098e3b84`, path
`assets/icons/devin.svg`. It is traced to the `app.devin.ai` PWA icon in
`jethac/factory` commit `2720aaf58a9d86a5142fd86dfb05ecb39d31364d`.

Its SHA-256 is `0B77AF4A730199892F15D99E9B812A39452554089811E46D925E62C09E09A4A9`.
Its Git blob is `0a11af513a7d208c2c49f33ab2d2d38fd4aefe90`.

Test requires that SHA-256 and Git blob; no alternate Devin mark is accepted.

- [ ] **Step 2: Implement deterministic fetching**

Clone each repository to a unique temporary directory, checkout detached commit, copy only named sources/licenses, verify hashes, normalize text to UTF-8/LF, and refuse a mismatched existing destination.

- [ ] **Step 3: Write generation tests**

Require Devin alpha `96x96`, each icon `18x18`, Roboto at weight 500/width 100 and 30 px, exact glyph subset derived from every compiled UI string, no dynamic allocation metadata, and byte-identical double generation.

- [ ] **Step 4: Implement asset generation**

Pin Python packages in `firmware/assets/requirements.txt`: CairoSVG 2.9.0, fontTools 4.63.0, Pillow 12.2.0. Render SVG at 8x then area-downsample, instantiate Roboto axes `{wght:500,wdth:100}`, rasterize monochrome glyphs, emit `const uint8_t` masks/metrics and source/license hashes.

- [ ] **Step 5: Generate twice and compare**

Run:

```powershell
py -3.11 -m pytest firmware/tests_py/test_assets.py -q
py -3.11 firmware/tools/gen-assets.py --check-reproducible
```

Expected: PASS and firmware locks record this repository's
`assets/icons/devin.svg` with the listed source hash and blob.

- [ ] **Step 6: Commit**

```powershell
git add firmware/assets firmware/generated firmware/tools/fetch-assets.ps1 firmware/tools/gen-assets.py firmware/tests_py/test_assets.py
git commit -m "feat(firmware): pin and compile display assets"
```

### Task 6: Implement the fixed-point strip renderer and goldens

**Files:**
- Create: `firmware/overlay/SDK/apps/watch/include/e87/e87_renderer.h`
- Create: `firmware/overlay/SDK/apps/watch/e87/e87_renderer.c`
- Create: `firmware/host/test_renderer.c`
- Create: `firmware/tools/render-goldens.py`
- Create: `firmware/tests_py/test_renderer_goldens.py`
- Generate: `firmware/generated/goldens/*.png`

**Interfaces:**
- Consumes: immutable render model plus generated alpha/glyph arrays.
- Produces: exactly 12 bounded 360x30 RGB565 strips and independently decoded PNG goldens.

- [ ] **Step 1: Write geometry/color tests**

Test 360x360 geometry with center `(180,180)`, outer radius/stroke/color `160/22/#BFC3C7`, inner `130/22/#FFFFFF`, black background, 18%-luminance tracks, start at 12 o'clock, clockwise progress at `0,1,50,99,100`, seamless 100, circular caps, physical-circle clipping, fixed icon centers `(180,20)` and `(180,50)`, Devin center `(180,166)`, and credit center `(180,240)`.

- [ ] **Step 2: Implement deterministic integer primitives**

Use Q16 CORDIC angle, squared-distance annulus/cap tests, four fixed subpixel coverage samples, RGB888 coverage blend with `(value+127)/255`, and RGB565 truncation. No `float`, `double`, `sin`, `cos`, `atan`, `malloc`, or variable-length arrays.

- [ ] **Step 3: Write strip and formatting tests**

Assert the twelve y origins `0,30,...,330`, final rows 30, no write outside `360*30`, sink failure stops immediately, and currency formatting uses integer cents only. Test battery, Pair, Waiting, countdown, and maintenance overlays, including bolt only for charging/full.

- [ ] **Step 4: Implement `e87_render_strip`/`e87_render_frame`**

Render track before active arc, then icons/logo/text. A duplicate semantic commit does not invoke the renderer; overlay begin/end and display wake do.

- [ ] **Step 5: Generate and compare goldens**

The Python reader imports the emitted C arrays rather than rerasterizing SVG/font inputs. Produce face combinations at `0,1,50,99,100` and every transient screen; compare exact PNG hashes in tests.

- [ ] **Step 6: Run and commit**

```powershell
.\firmware\tools\test-host.ps1 -Suite renderer
py -3.11 -m pytest firmware/tests_py/test_renderer_goldens.py -q
git add firmware/overlay/SDK/apps/watch firmware/host/test_renderer.c firmware/tools/render-goldens.py firmware/tests_py/test_renderer_goldens.py firmware/generated/goldens
git commit -m "feat(firmware): render Devin rings in RGB565 strips"
```

### Task 7: Recover the JD9855 initializer and implement direct DBI streaming

**Files:**
- Create: `firmware/tools/extract-panel-init.py`
- Create: `firmware/assets/sources/jd9855-init.raw.bin`
- Create: `firmware/overlay/SDK/apps/watch/include/e87/e87_panel.h`
- Create: `firmware/overlay/SDK/apps/watch/e87/e87_panel_jd9855.c`
- Create: `firmware/overlay/SDK/apps/watch/include/e87/e87_lcd_stream.h`
- Create: `firmware/overlay/SDK/apps/watch/e87/e87_lcd_stream.c`
- Create: `firmware/overlay/SDK/apps/watch/include/e87/e87_sleep.h`
- Create: `firmware/overlay/SDK/apps/watch/e87/e87_sleep.c`
- Create: `firmware/tests_py/test_panel_profile.py`
- Create: `firmware/host/test_lcd_stream.c`

**Interfaces:**
- Consumes: recovered model-1552 plaintext app and public BR35 `dbi.h` APIs.
- Produces: validated 657-byte init program, panel lifecycle, a serial strip
  sink for the first hardware gate, and a separately gated callback-streaming
  promotion.

- [ ] **Step 1: Write extraction/parser tests**

Input app SHA-256 must be `A38B77E27B1DC73CAE0FBD8A7C4E3A04C64FF393FB4F27BC92A7578336BE0147`, base `0x0C000100`, descriptor file offset `0xEF688`, actual runtime descriptor `0x00106E08`, init address `0x0C0E59E0`, and init length 657. Extracted init SHA-256 must be `BB0767D3E0BF4AD982725C6A38A9168DDF9E5BA2E3D4D595B1FFBDD17E5B89FF`. The 196-byte parameter source at file offset `0xEF8A4`, loaded through RAM pointer `0x00107024`, must hash to `BFF9D90B248ECFB370877A1CF9677D67E66E4BC1E79E07962CC59E1A87A43A3B`.

Parse exactly 51 records bounded by `12 34 56 78` and `87 65 43 21`; a body beginning `FF 5A A5 FF` is a one-byte millisecond delay. Assert the final records are delay 10 ms, `4C 00`, TE `35 00`, RGB565 `3A 55`, sleep-out `11`, delay 120 ms, display-on `29`, and delay 20 ms, with no MADCTL `36` or address-window `2A`/`2B` in the init blob.

- [ ] **Step 2: Implement extraction and vendor the exact raw blob**

`extract-panel-init.py` reads a user-supplied reference app, checks the input hash/address range/output hash, and writes only when `--output` is explicitly supplied. The build consumes the vendored hashed result, not a local Downloads path.

- [ ] **Step 3: Implement the raw DBI panel driver**

Use `lcd_init`, `lcd_write_cmd`, `lcd_set_draw_area`, `lcd_clear`, `lcd_draw`, `lcd_wait_busy`, and, only after serial proof, `lcd_draw_set_callback`. Leave JLUI/LVGL/UI/touch macros zero. Preserve the recovered 360x360 RGB565 `LCD_TYPE_SPI` descriptor facts: QSPI mode/submode `0x21` (`QSPI_MODE | QSPI_SUBMODE1`), pixel type `0x21` (`PIXEL_1P2T | PIXEL_1T2B`), idle-low clock, unidirectional operation, 90 fps, declared buffer count 2 and size `0x5460`, alignment 2/2, and radius 180. The serial adapter deliberately supplies only one `0x5460` application transfer buffer and waits before reuse; it must not misreport that staged allocation as the stock descriptor's two-buffer memory layout. Model-1552 pins are reset `PA05`, TE `PA06`, CS `PA07`, CLK `PA12`, D0-D3 `PA08`-`PA11`, and open-drain `IO_LCD_PG` backlight low/on, high-Z/off. There is no DC or separate recovered rail hook. Keep every such model-1552 value `INFERRED` for model 1542 and keep backlight off on any init failure.

- [ ] **Step 4: Write and implement streaming tests**

First test `lcd_clear` black/white/red/green/blue serially, waiting after every call. Then use one `0x5460` buffer for exactly twelve independently addressed 360x30 windows at y `0,30,...,330`, with `lcd_wait_busy` before reuse. Only after that hardware stage passes may a linker-proven `0xA8C0` configuration alternate two buffers; a buffer cannot be reused before its completion callback. Do not use `lcd_draw_continue` or gate rendering on TE until logic-analyzer evidence proves framing and phase.

Sleep calls `lcd_wait_busy`, disables backlight, writes display-off `28` then sleep-in `10`, waits at least 120 ms, and releases the LCD clock. Wake reacquires the clock, applies reset high 10 ms/low 10 ms/high 100 ms, replays the exact init, redraws while dark, and enables backlight last. Do not invent a panel-rail toggle.

- [ ] **Step 5: Run and commit**

```powershell
py -3.11 -m pytest firmware/tests_py/test_panel_profile.py -q
.\firmware\tools\test-host.ps1 -Suite lcd
git add firmware/assets/sources/jd9855-init.raw.bin firmware/tools/extract-panel-init.py firmware/tests_py/test_panel_profile.py firmware/overlay/SDK/apps/watch firmware/host/test_lcd_stream.c
git commit -m "feat(firmware): add recovered JD9855 DBI path"
```

### Task 8: Implement normal GATT, bond ownership, and BLE mode switching

**Files:**
- Create: `firmware/overlay/SDK/apps/watch/include/e87/e87_ble_control.h`
- Create: `firmware/overlay/SDK/apps/watch/e87/e87_gatt_db.c`
- Create: `firmware/overlay/SDK/apps/watch/e87/e87_ble_control.c`
- Create: `firmware/overlay/SDK/apps/watch/include/e87/e87_bond_policy.h`
- Create: `firmware/overlay/SDK/apps/watch/e87/e87_bond_policy.c`
- Create: `firmware/overlay/SDK/apps/watch/include/e87/e87_ble_mode_fsm.h`
- Create: `firmware/overlay/SDK/apps/watch/e87/e87_ble_mode_fsm.c`
- Test: `firmware/tests_py/test_att_db.py`
- Test: `firmware/host/test_ble_control.c`
- Test: `firmware/host/test_bond_policy.c`
- Test: `firmware/host/test_ble_mode_fsm.c`

**Interfaces:**
- Consumes: JieLi multi-handle `app_ble_*` API, state/store/build/battery modules, 60-second physical pairing state.
- Produces: exact normal profile, one-owner encrypted non-MITM state writes,
  and safe asynchronous profile switching.

- [ ] **Step 1: Define and test the exact normal profile**

Handles 1-12 are GAP name, 128-bit service, state write, build-info read,
Battery Service, Battery Level read/notify, and Battery CCCD. The state
characteristic is encrypted, non-MITM write-with-response under `Just Works`;
build-info is encrypted read.

Test the exact 26-byte advertisement containing flags, service UUID, and `E87`
name. A successful encrypted build-info read is the Android gate before it
enables a state write. Wrong handle/UUID/property/security/terminator fails.

- [ ] **Step 2: Implement ATT read/write callbacks**

Support chunked reads. Require link encryption for build-info reads and state
writes; reject either unencrypted request with `0x0F`.

For state writes, reject nonzero write offset `0x07`, wrong length `0x0D`,
non-owner `0x08`, and an invalid semantic packet, including any non-`1727`
credit, with `0x80`. Commit a valid state atomically; duplicates ACK without
redraw.

- [ ] **Step 3: Implement crash-safe owner replacement**

Initialize `ble_list_config_reset(2,0)` but expose one owner. Outside pairing call `ble_list_pair_accept(0)`. During the physical window stage the candidate as slot two; after pair-add and encryption success persist the E87 owner transaction record, call `ble_list_bonding_remote(candidate)`, close pairing, and normalize on boot. Fault-inject power loss before/after each step; failed replacement preserves the prior owner.

- [ ] **Step 4: Implement asynchronous mode switching**

Normal advertising off → reject new writes → request disconnect → await disconnect completion → release normal handle → initialize maintenance. Reverse in the same order. Never call `app_ble_exit()` during hot switch and never free a handle while a connection callback can reference it.

- [ ] **Step 5: Run and commit**

```powershell
py -3.11 -m pytest firmware/tests_py/test_att_db.py -q
.\firmware\tools\test-host.ps1 -Suite ble
git add firmware/overlay/SDK/apps/watch firmware/host/test_ble_control.c firmware/host/test_bond_policy.c firmware/host/test_ble_mode_fsm.c firmware/tests_py/test_att_db.py
git commit -m "feat(firmware): add bonded semantic GATT service"
```

### Task 9: Implement application-side RCSP maintenance and loader gate

**Files:**
- Create: `firmware/overlay/SDK/apps/watch/include/e87/e87_maintenance.h`
- Create: `firmware/overlay/SDK/apps/watch/e87/e87_rcsp_profile.c`
- Create: `firmware/overlay/SDK/apps/watch/e87/e87_maintenance.c`
- Create: `firmware/tests_py/test_rcsp_profile.py`
- Create: `firmware/host/test_maintenance.c`

**Interfaces:**
- Consumes: physical 10s action/early recovery, battery/power gate, official RCSP callbacks.
- Produces: `E87 UPDATE` AE00/AE01/AE02 service and official single-bank loader handoff only after verification.

- [ ] **Step 1: Test the minimal maintenance profile**

Handles are GAP name, read-only `E87 UPDATE`, AE00, AE01 write-without-response, AE02 notify, AE02 CCCD. Reject FEE7, AA00, normal metrics UUIDs, SPP/TWS/client/file/browser/settings/sensor features, and stock UI dependencies.

- [ ] **Step 2: Implement maintenance lifecycle**

After normal disconnect completion call `bt_rcsp_interface_init(e87_rcsp_profile)`, `rcsp_init()`, `rcsp_bt_ble_init()`. Skip `rcsp_ble_profile_init()`. Exit by rejecting commands, stopping RCSP advertising, disconnecting/awaiting, `rcsp_bt_ble_exit()`, `bt_rcsp_interface_exit()`, then normal mode.

- [ ] **Step 3: Write timeout/power/loader tests**

Test unauthenticated 119999/120000 ms, authentication cancellation of timeout, every pre-handoff cancel/failure, 49/50 battery boundary, low-voltage warning, five seconds of stable eligible voltage, zero loader address, wrong single-bank profile/layout, and CLOSE/FULL charger events. Charging does not bypass the gate.

- [ ] **Step 4: Implement the double loader gate**

Only the official handler may eventually call `update_mode_api_v2()`. Require loader-download verified, `loader_saddr != 0`, percent at least 50 for five seconds, no low-voltage warning, stable board voltage, AC707N/single-bank/profile/layout match. Gesture and maintenance UI modules do not import or reference the mode API.

- [ ] **Step 5: Run and commit**

```powershell
py -3.11 -m pytest firmware/tests_py/test_rcsp_profile.py -q
.\firmware\tools\test-host.ps1 -Suite maintenance
git add firmware/overlay/SDK/apps/watch firmware/host/test_maintenance.c firmware/tests_py/test_rcsp_profile.py
git commit -m "feat(firmware): add physically gated RCSP maintenance"
```

### Task 10: Integrate the E87 board/application overlay into the pinned SDK

**Files:**
- Create: `firmware/board-profiles/E87-JD9855-R1.json`
- Create: `firmware/overlay/SDK/apps/watch/e87/e87_app.c`
- Create: `firmware/overlay/SDK/apps/watch/include/e87/e87_app.h`
- Create: `firmware/overlay/SDK/apps/watch/board/br35/board_e87_1542/*`
- Create: `firmware/patches/0001-e87-board-build.patch`
- Create: `firmware/patches/0002-e87-app-charge-recovery.patch`
- Create: `firmware/patches/0003-e87-ble-maintenance.patch`
- Create: `firmware/patches/0004-e87-linker-dbi.patch`
- Create: `firmware/tests_py/test_board_config.py`
- Create: `firmware/tests_py/test_build_graph.py`

**Interfaces:**
- Consumes: all pure E87 modules and a fresh pinned SDK checkout.
- Produces: a minimal BLE/DBI application selected by `CONFIG_BOARD_E87_1542`.

- [ ] **Step 1: Write board/config negative tests**

Require BLE-only stack, no Classic/SPP/TWS/UI/LVGL/touch/PSRAM/audio/storage/demos, charge enabled/power-on enabled, no automatic shutdown, single-bank, packaged reset disabled, runtime PB08/16, and a serial-probe `CONFIG_LCD_BUF_STATIC_RAM_LEN=0x6000` containing one `0x5460` buffer despite UI macros being zero. A build enabling exact-stock callback double buffering must instead prove at least `0xA8C0` without overlapping heap, stacks, or update scratch.

The board profile must identify the recovered model-1552 JD9855 descriptor and callbacks as `INFERRED` for model 1542, include every rail/reset/backlight/DBI field used by target compilation, and set `labEligible: true` but `releaseEligible: false`. No inferred electrical field may silently acquire a `CONFIRMED` status; only the hardware ladder can make that transition.

- [ ] **Step 2: Add the board/build graph**

Patch `board_config.h`, `app_config.h`, `genFileList.c`, and `Makefile.mk` to select/enumerate E87 sources exactly once. Fix prebuild ordering so generated `fileList.mk` is never source-controlled or consumed after being clobbered.

- [ ] **Step 3: Add minimal early boot/application routing**

Latch PINR after `boot_power_init`, skip filesystem/resource initialization, retain platform initcalls required by power/charger/update, start watchdog/message dispatch, bypass stock application modes even when plugged, and run `e87_app`.

- [ ] **Step 4: Patch charge/BT/RCSP seams**

At BT stack ready initialize E87 BLE and bypass Classic/TWS reconnect. Add E87 charge-event dispatch preserving electrical helpers. Configure RCSP BLE update without SPP and ensure loader address failure is fatal.

- [ ] **Step 5: Patch linker tail with assertions**

Correct the guard to `CONFIG_LCD_BUF_STATIC_RAM_LEN`. For the serial ladder reserve the existing `[0x130E00,0x136E00)` tail, define one buffer `[0x130E00,0x136260)`, retain `[0x136260,0x136E00)` slack, and assert the tail ends at update scratch start. Do not enable callback double buffering until a new reservation of at least `0xA8C0` has fresh link-map, heap, stack, update-scratch, and region-boundary proofs; do not guess its start address in the patch.

- [ ] **Step 6: Run overlay tests and commit**

```powershell
py -3.11 -m pytest firmware/tests_py/test_board_config.py firmware/tests_py/test_build_graph.py -q
git add firmware/overlay firmware/patches firmware/tests_py
git commit -m "feat(firmware): integrate minimal AC707N E87 application"
```

### Task 11: Add source/map gates and produce the host-verifiable firmware state

**Files:**
- Create: `firmware/tools/source-audit.py`
- Create: `firmware/tools/check-map.py`
- Create: `firmware/tests_py/test_source_routes.py`
- Create: `firmware/tests_py/test_map_checker.py`
- Create: `firmware/README.md`

**Interfaces:**
- Consumes: overlay sources, fixture maps, later real `sdk.map`.
- Produces: auditable proof of forbidden-route absence and exact memory bounds before packaging.

- [ ] **Step 1: Write source-route failure fixtures**

Reject normal-to-maintenance calls, gesture-to-update API, stock UIRES/UI window references, Button2-to-charge-close, filesystem metric persistence, full-framebuffer arrays, PSRAM, floats/libm, and wrong board/profile identifiers.

- [ ] **Step 2: Implement `source-audit.py`**

Parse preprocessed call references where available and conservatively scan source/linker symbol reports. Emit canonical JSON containing every rule, evidence path/line/symbol, and pass/fail; unknown is failure.

- [ ] **Step 3: Write map fixtures and checker**

For the serial ladder require entry `0x0C000100`, RAM lower bound `0x10054C`, top `0x137000`, update start `0x136E00`, tail start `0x130E00`, used `0x5460`, reserved `0x6000`, PSRAM zero, heap at least `0x8000`, and no `360*360*2` object. Add a negative fixture proving exact-stock callback double buffering fails unless its reservation is at least `0xA8C0` and every adjacent boundary is re-proven.

- [ ] **Step 4: Run the complete host firmware gate**

```powershell
.\firmware\tools\test-host.ps1 -Suite all
py -3.11 -m pytest firmware/tests_py -q
py -3.11 firmware/tools/source-audit.py --root firmware
```

Expected: all pure logic, render, profile, build-graph, and fixture gates pass without PI32v2 or badge hardware.

- [ ] **Step 5: Document target-build prerequisites and commit**

Document exact toolchain pin/install path and commands from the packaging plan, plus the fact that host success is not a target-binary claim.

```powershell
git add firmware
git commit -m "test(firmware): gate E87 routes and memory layout"
```

## Plan Completion Gate

The firmware-core plan is complete when all host C/Python tests and source gates pass, correct assets/panel initializer are vendored by hash, the SDK overlay is deterministic, and no claim of target compilation or hardware behavior is made until the packaging and integration plans supply their separate evidence.
