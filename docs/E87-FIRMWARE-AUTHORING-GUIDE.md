# E87 firmware authoring guide

**Audience:** an agent implementing, reviewing, packaging, or recovering custom
firmware for the E87 badge family.

**Purpose:** preserve the current evidence so future work starts from the known
AC707N/BR35 baseline instead of repeating the earlier AC697/BR30 hypothesis.
This is an engineering guide, not a claim that every badge sold as E87 has the
same PCB.

**Evidence date:** 2026-08-27, with the PB07/PINR and integer battery-arithmetic
correction recorded 2026-08-28. The exact stock model-1542 image has not been
recovered. The model-1552 reference image has been decoded and has booted on the
test badge, but its product resources are visibly wrong for that unit.

## Evidence labels

Every hardware-sensitive assertion in this document uses one of these labels:

- **PROVEN** — observed on the physical badge, decoded from a validated vendor
  artifact, or stated by the pinned official JieLi source.
- **INFERRED** — strongly supported by multiple observations, but not yet
  measured directly on the untouched model-1542 hardware.
- **UNVERIFIED** — a design choice or unresolved value that must not be copied
  into a production image without a bench test.

Do not silently promote an inference to a fact. Add the capture, hash, source
line, or measurement when changing a label.

## Non-negotiable rules

1. Preserve at least one untouched badge as the reference unit.
2. Never flash a package merely because it says `E87` or uses AC707N/BR35.
   Product model, panel, resources, partition map, and calibration all matter.
3. Before the first custom write, obtain two identical physical flash reads
   from an untouched unit and prove a restore on a sacrificial unit.
4. Do not expose erase, format, flash-write, or permanent-key-burn operations in
   a general-purpose recovery script. Use an explicit command allowlist.
5. Keep credentials, BLE provisioning secrets, signing material, and device
   keys outside source control and outside build logs. This guide intentionally
   records no secret values.
6. A successful BLE transfer proves transport integrity, not hardware or
   resource compatibility.

## 1. Product identity and variant boundary

| Model | Hex | Observed/catalog identity | What is established |
|---|---:|---|---|
| `1542` | `0x0606` | Physical badge originally advertised `E87` and reported firmware `11.1.0.3` | **PROVEN:** live model/version. **UNVERIFIED:** exact untouched flash contents and exact board configuration. No current vendor-catalog image was found. |
| `1552` | `0x0610` | `QX7413_E87_EN`, outer version `11.1.0.2` | **PROVEN:** validated AC707N/BR35 package. It transferred completely to the model-1542 test badge, booted, advertised `Q87`, and bound successfully. Text and drawer graphics were wrong, proving a product/resource mismatch. |
| `1558` | `0x0616` | `QX7613_E87_C32`, outer version `1.0.3` | **PROVEN:** validated AC707N/BR35 comparison package. It is not a model-1542 recovery image. |

The clean model-1552 boot is strong operational evidence that the test hardware
is AC707N/BR35-compatible. It does **not** prove that the untouched model-1542
was built with the model-1552 board definition, partition contents, fonts, UI,
touch controller, or battery calibration.

The string `jl_sdk_ac697_publish` is shared lineage text and is not proof of an
AC697/BR30 chip. Older notes that inferred BR30 solely from that string are
superseded by the decoded AC707N artifacts and the successful AC707N boot.

Primary local chronology:

- `C:\Users\jetha\Downloads\e87-reversing\LAB-LOG-2026-08-26.md`, especially
  lines 43-87 and 326-413.
- Full accepted update capture:
  `C:\Users\jetha\Downloads\e87-reversing\captures\qix-live-runs-2026-08-26\run-20260826-234136-881-pid23725`.
- Post-update bind verification:
  `C:\Users\jetha\Downloads\e87-reversing\captures\qix-live-runs-2026-08-26\run-20260826-234557-679-pid24450`.

## 2. Pin the source and tools

Use the official e-badge SDK at commit
`d0167685d032d745d88fe50233302edd46941622`:

- Repository: [e_badge_707_sdk_200](https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200)
- Project identity: [`project.jlproj`](https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200/-/blob/d0167685d032d745d88fe50233302edd46941622/project.jlproj#L2-8)
  selects watch/AC707N, SDK version 2.0.0, pack `AC707N-demo`.
- Windows compiler paths: [`SDK/Makefile:15-32`](https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200/-/blob/d0167685d032d745d88fe50233302edd46941622/SDK/Makefile#L15-32)
  expects `C:/JL/pi32/bin`, `pi32v2-lib/r3-large`, and the PI32v2 headers.
- Target flags: `-target pi32v2 -mcpu=r3` at `SDK/Makefile:68-75`.
- Link/post-build flow: `SDK/build/Makefile.mk:1053-1108` creates `sdk.map`,
  `sdk.elf`, the generated linker script, download script, and ISD config.

Record hashes of the whole compiler/tool directory. A path named `C:/JL/pi32`
is not a version pin.

Known reference hashes:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| Official `SDK/cpu/br35/tools/br35loader.bin` | 27,328 | `1295A01D5A89AD42E9EDA6B87ACFE7D543AB68293D4087C3DDA9BF9AB472DAE1` |
| Official `SDK/cpu/br35/tools/isd_download.exe` | 4,959,032 | `D581CB0E8EF3EEFBCE1F02F1B02AAE637A239D8713E81D1CD5321339FCEC7A55` |
| Model-1552 outer OTA package | 1,080,387 | `14484147053903F879D0C24ACBAB6A564F5CC8F039CACCBB30821012DF645D32` |
| Model-1552 plaintext `app.bin` | 995,584 | `A38B77E27B1DC73CAE0FBD8A7C4E3A04C64FF393FB4F27BC92A7578336BE0147` |

`isd_download.exe` is a burner, not an inspection tool. Never run its normal
download path merely to identify a connected device.

## 3. AC707N/BR35 memory and execution model

The following is **PROVEN for the pinned generic JL707N build**, not yet for an
untouched model-1542 link map:

| Region | Range, end-exclusive | Size |
|---|---:|---:|
| Main SRAM window | `0x100000-0x137000` | 220 KiB |
| Mask/IRQ reservation | `0x100000-0x10054C` | `0x54C` |
| Application `ram0` | `0x10054C-0x136E00` | `0x368B4` / 223,412 bytes |
| Static LCD-buffer tail | `0x131E00-0x136E00` | `0x5000` / 20 KiB in the generic 320-wide build |
| Update scratch | `0x136E00-0x137000` | `0x200` |
| Reclaimed D-cache RAM | `0x372000-0x378000` | 24 KiB |
| Reclaimed I-cache RAM | `0x3C4000-0x3C8000` | 16 KiB |
| PSRAM origin | `0x08000000` | zero length in the selected build |
| SFC/XIP base | `0x0C000000` | — |
| Application code origin | `0x0C000100` | — |

Evidence:

- `SDK/cpu/br35/maskrom_stubs.ld:196-205`
- `SDK/cpu/br35/sdk_ld.c:40-95,294-327,664-678`
- `SDK/apps/watch/board/br35/sdk_config.h:34,39-43`
- `SDK/apps/watch/include/app_config.h:1012-1030`

`_HEAP_BEGIN` depends on the final `.data`, `.bss`, RAM code, and overlays. The
linker only asserts a minimum 32 KiB heap. Treat the generated `sdk.map` as a
required build artifact and fail CI if the agreed heap headroom is missed.

The reclaimed cache regions are not 40 KiB of free general heap: Bluetooth
static state and GPU buffers can occupy them. Account for each section in the
map.

**PROVEN for the generic build:** PSRAM is disabled. **UNVERIFIED for the
physical package:** whether dormant in-package PSRAM exists. Read the full chip
marking; the vendor-authored AC7074A datasheet distinguishes no-PSRAM and PSRAM
package suffixes. Custom firmware described here must work without PSRAM.

## 4. Flash layout and image layers

### 4.1 Capacity and model-1552 layout

The generic SDK selects 8 MiB internal/in-package flash and disables external
NOR and NAND. Its checked-in generic partition template overruns 8 MiB by
`0x26000`, so it is not a trustworthy product layout.

The decoded model-1552 ISD configuration is a better reference:

| Region | Start | Length | End |
|---|---:|---:|---:|
| UI resources | `0x180000` | `0x15E000` | `0x2DE000` |
| User/config | `0x2DE000` | `0x28000` | `0x306000` |
| Watch | `0x306000` | `0x1000` | `0x307000` |
| Internal NOR filesystem | `0x307000` | `0x4F8000` | `0x7FF000` |

Source:
`C:\Users\jetha\Downloads\e87-reversing\firmware-catalog\extracted\e87-11.1.0.2\items\04_isd_config.ini`.

This map is **PROVEN for model 1552** and **UNVERIFIED for untouched model
1542**. Do not preserve or overwrite a region by name until the untouched dump
confirms its address and content.

### 4.2 Do not confuse the layers

The model-1552 update has four distinct layers:

1. A 27-byte Qix wrapper: magic/type, ten-byte version field, little-endian
   payload length, reserved bytes, and CRC-16/CCITT-FALSE over the payload.
2. A JieLi CD03 UFW v4 container with a validated header, item table, and ten
   members including `flash.bin`, loader/config members, and `tail.bin`.
3. `flash.bin`, which is a JieLi new-flash-filesystem/burner image and has a
   separate OEM code-encryption layer.
4. The extracted PI32v2 application `app.bin`, imported at `0x0C000100`.

The phone sends the UFW payload after negotiating with the Qix wrapper header;
it does not send a flat application binary. A correctly decrypted UFW table is
not proof that `flash.bin` code is plaintext. Do not reuse a container-derived
value as a device key.

Validated extraction inventory:

- `C:\Users\jetha\Downloads\e87-reversing\firmware-catalog\extracted\e87-11.1.0.2\manifest.json`
- `...\container\payload.ufw`
- `...\items\00_flash.bin`
- `...\canonical-jl-unpack\files\app.bin`
- Pinned extractor: `C:\Users\jetha\Downloads\e87-reversing\tools\ufw-extractor`

### 4.3 BLE update path

**PROVEN on the spare:** the factory Qix C0/C1/C2/C3/C5 update path accepted the
complete 1,080,360-byte UFW payload, acknowledged monotonically increasing
offsets, returned final result zero, rebooted, and reported the new version.
The subsequent wrong name/resources were a variant mismatch, not a torn BLE
transfer.

Safeguards for any future update client:

- Require an explicit receiving/maintenance mode and physical presence.
- Pin full-file size and SHA-256 before sending the header.
- Validate outer payload length/CRC and every UFW/item CRC offline.
- Resume only from an offset requested by the device and already covered by the
  same pinned input hash.
- Journal every request, acknowledgement, offset, retry, MTU, disconnect, and
  final result.
- Disable screen timeout, radio coexistence experiments, and battery-intensive
  work during transfer; begin only on stable power.
- Never offer a nearby model as an automatic fallback.

## 5. JD9855 panel reconstruction

The official SDK default is **not** the target panel. It selects a 320x386
GC9B71 QSPI display. Copying that profile explains neither the stock
368x368 JPEG upload target nor the recovered direct-DBI descriptor.

### 5.1 Stock descriptor and command list

The following is **PROVEN from the validated model-1552 plaintext app**:

- The plaintext app SHA-256 is
  `A38B77E27B1DC73CAE0FBD8A7C4E3A04C64FF393FB4F27BC92A7578336BE0147`.
- The direct-DBI active, input, and output geometry is 360x360 RGB565. A full
  RGB565 frame is 259,200 bytes. The stock Android image path independently
  resizes JPEG uploads to 368x368; that transport/storage size is not the DBI
  scanout geometry.
- A registered LCD descriptor is at app file offset `0xEF688`, flat address
  `0x0C0EF788` when imported at `0x0C000100`, and actual runtime RAM address
  `0x00106E08`.
- Its name pointer resolves to ASCII `jd9855`.
- Column alignment is 2; row alignment is 2; radius is 180.
- Init pointer is `0x0C0E59E0`; its file offset is `0xE58E0`.
- Init length is `0x291` / 657 bytes.
- Init SHA-256 is
  `BB0767D3E0BF4AD982725C6A38A9168DDF9E5BA2E3D4D595B1FFBDD17E5B89FF`.
- The same command blob is present in the decoded 1558 and 1606 variants.
- The RAM `dbi_param` pointer is `0x00107024`. Its recovered 196-byte source
  image begins at app file offset `0xEF8A4`; the raw parameter SHA-256 is
  `BFF9D90B248ECFB370877A1CF9677D67E66E4BC1E79E07962CC59E1A87A43A3B`.
- The stock profile is `LCD_TYPE_SPI`, QSPI mode/submode `0x21`
  (`QSPI_MODE | QSPI_SUBMODE1`), pixel type `0x21`
  (`PIXEL_1P2T | PIXEL_1T2B`), idle-low clock, unidirectional RGB565
  input/output, 90 fps, two buffers, and `0x5460` / 21,600 bytes per buffer.
  Each buffer is exactly `360 * 30 * 2`, so a stock frame is twelve 30-row
  transfers.

The descriptor follows the official `struct lcd_drive` layout at
[`SDK/apps/watch/include/ui/lcd/lcd_drive.h:115-143`](https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200/-/blob/d0167685d032d745d88fe50233302edd46941622/SDK/apps/watch/include/ui/lcd/lcd_drive.h#L115-143):

| Offset | Model-1552 value | Interpretation |
|---:|---:|---|
| `+0x00` | `0x0C0E3E22` | `"jd9855"` |
| `+0x04` | `02 02` | column/row alignment |
| `+0x08` | `0x0C0E59E0` | init list |
| `+0x0C` | `0x291` | init length |
| `+0x10` | `180` | radius |
| `+0x14` | `0xFFFFFFFF` | fill ARGB |
| `+0x18` | `0x00107024` | RAM `dbi_param` pointer |
| `+0x1C` | `NULL` | special reset handler |
| `+0x20` | `0x0C03CAE0` | backlight handler |
| `+0x24` | `NULL` | special power handler |
| `+0x28` | `0x0C03CB40` | enter-sleep handler |
| `+0x2C` | `0x0C03CB5C` | exit-sleep handler |
| `+0x30` | `NULL` | read-ID handler |
| `+0x34` | `0` | LCD ID |

The command-list framing is confirmed by the official macros at
`lcd_drive.h:95-112`: `12 34 56 78` begins a command and `87 65 43 21` ends it;
`FF 5A A5 FF <ms>` encodes a delay.

The stock list begins with:

```text
DE 00
DF 98 55
B2 2C
B7 01 29 01 51
BB 1B 64 C4 0E 3E F5
```

Its final records are delay 10 ms, `4C 00`, TE enable (`35 00`), RGB565
selection (`3A 55`), sleep-out (`11`), delay 120 ms, display-on (`29`), and
delay 20 ms. The exact 657-byte blob contains 51 framed records and does not
send MADCTL (`36`) or address-window commands (`2A`/`2B`). The pinned DBI
library supplies `2A`/`2B` plus RAM write/continue (`2C`/`3C`) for draw
operations.

`jd9855` is therefore a strong embedded identity, but no matching public driver
or datasheet has been validated. Treat the controller name as **INFERRED** until
read-ID or package/logic-analyzer evidence confirms it.

### 5.2 Recovered pins and remaining hardware gates

The stock model-1552 path fixes the dedicated QSPI pins to CS `PA07`, CLK
`PA12`, D0 `PA08`, D1 `PA09`, D2 `PA10`, and D3 `PA11`; reset is `PA05` and TE
is `PA06`. `PA08` is also the read selector if a read transaction is used.
There is no separate DC pin in this QSPI profile. Backlight is `IO_LCD_PG`
(`0xE7`) through an open-drain hook: drive low for on and release high-Z for
off. The descriptor has no panel-power callback and its `pin_en`/`pin_en_ex`
selectors are absent, so the recovered application does not toggle a separate
panel rail.

Those values are **PROVEN for the decoded model-1552 artifact and INFERRED for
the physical model-1542**. Before a model-1542 display build, confirm the rails,
pin continuity, backlight polarity, reset waveform, QSPI framing/actual clock,
and current against the untouched reference. A logic analyzer must also settle
orientation and mirroring (the init has no `36` command), RGB/BGR and byte
order, the 360-pixel active-area/clipping behavior, TE edge/phase, and whether
the read path works. Do not infer any of these from the generic GC9B71 profile.

The recovered reset sequence is high 10 ms, low 10 ms, high 100 ms before the
exact init program. Request no more than the recovered 90 fps for the first
probe; the DBI clock is derived from fps and its actual wire frequency must be
measured. First render black/white/red/green/blue with a serial
`lcd_clear`/`lcd_wait_busy` sequence; then send independently addressed 360x30
strips. A swapped color, mirrored image, wrap at an edge, or intermittent first
line is a bus/window bug, not an asset bug.

Do not substitute the SDK's dormant JD5858 360x360 MCU driver. Its geometry,
8-bit bus, init prefix, and timing differ from the stock evidence.

## 6. Rendering without a framebuffer

A 360x360 RGB565 framebuffer is 259,200 bytes, larger than the generic app RAM
budget before stacks, Bluetooth, and application state. The firmware should be
strip-buffered and PSRAM-independent.

Recovered constraints and staged design:

- One stock 30-row buffer is `360 * 30 * 2 = 21,600 = 0x5460` bytes and fits
  the existing aligned `0x6000` LCD tail. Use that single buffer for the first
  serial hardware ladder, always calling `lcd_wait_busy` before reuse.
- Exact stock double buffering consumes `2 * 0x5460 = 43,200 = 0xA8C0` bytes.
  It does not fit a `0x6000` reservation. Production callback-driven streaming
  therefore requires a linker-tail expansion to at least `0xA8C0` plus fresh
  map, heap, stack, update-scratch, and region-boundary proofs.
- Statically allocate and align selected buffers. Do not allocate in the draw
  loop. Emit twelve windows at y origins `0,30,...,330`, each 360x30.
- Keep the first ladder serial. Only after every independently addressed strip
  passes may two buffers alternate; a buffer is reusable only after the draw
  completion callback or an explicit `lcd_wait_busy`.
- Use `lcd_draw` for the first window and `lcd_draw_continue` only when the
  logic analyzer proves `3C` framing and tearing behavior. These are
  nonblocking APIs in `SDK/interface/ui/cpu/br35/dbi.h:346-368,449-459`.
- Clip every primitive to the active strip and round dirty rectangles to the
  proven two-pixel row/column alignment.
- Render static background, rings, icon masks, and glyphs locally. Android
  should send semantic values, not screen-sized bitmaps.
- Hardware JPEG can decode MCU strips/regions into a line buffer; see
  `SDK/interface/ui/cpu/br35/jljpeg_decode.h:14-33,169-218,224-317` and
  `SDK/apps/watch/ui/jlgpu_demo/jpeg_demo.c:98-125`. Baseline JPEG is the safe
  target; progressive JPEG support is **UNVERIFIED**.

### Assets and fonts

Prefer deterministic compile-time assets over the stock JL UI resource tree:

- Convert SVGs on the build host to 1-bit/8-bit alpha masks or RGB565/RLE.
- Subset fonts to the glyphs actually rendered; fixed-width digits and a small
  punctuation set are ideal for the factory display.
- Record source path, license/provenance, dimensions, conversion command, pixel
  format, and SHA-256 for every generated asset.
- Golden-test the converted pixels on the host and render a PNG preview from
  the same generated arrays used by firmware.
- Do not embed `assets/icons/devin.svg` from this repository as-is. Its adjacent
  `assets/icons/README.md` explicitly records that the vendored cog-and-circle
  is not Cognition's Devin mark.

If the JL UI packer is retained, make resource generation clean-room
deterministic. The generic `download_jlui.bat:59-68` has a commented sidebar
generation command while later concatenating sidebar/font artifacts, creating
a stale-output hazard.

## 7. BLE service and bonding

The pinned stack supports MTU 23-517, DLE, 251-byte ACL packets, 2M PHY under
RCSP, connection-parameter updates, notifications, write-without-response,
send-buffer accounting, and `CAN_SEND_NOW` flow control:

- `SDK/interface/btstack/le/ble_api.h:323-330,530-727,795-810,1314-1343`
- `SDK/interface/btstack/le/att.h:46-52,143-147`
- `SDK/apps/common/third_party_profile/jieli/gatt_common/le_gatt_common.h:44-49,189-223`
- `SDK/apps/watch/log_config/lib_btctrler_config.c:335-363,420-422`

For custom firmware, create a new 128-bit service. Do not overload the stock
AE00 image channel or FD00/Qix update/factory service.

Suggested service contract (**PROPOSED**):

- `state-write`: phone to badge, write or write-without-response.
- `status-notify`: badge to phone, applied sequence, battery, error/status.
- `control-indicate`: low-rate acknowledged operations such as time sync,
  pairing policy, or maintenance entry.
- Every state message contains protocol version, monotonic sequence, payload
  length, fixed-point numeric values, and CRC. Ignore duplicate/older sequences
  and ACK only after committing the new render state.
- Keep individual semantic updates small enough to fit conservative MTUs even
  though 517 is available. Use DLE/2M for bursts, not as a correctness
  dependency.

Bonding policy (**PROPOSED**):

- Accept provisioning only during a physical, time-limited pairing state.
- Require an encrypted/bonded link before state-changing writes.
- A display-only `Just Works` bond has no MITM protection. For stronger local
  control, display a one-time code/QR or provision a per-device application
  credential; never ship one fleet-wide source-code secret.
- Store peer identity/IRK and CCCD state in an explicitly allocated persistent
  record. Version it and include a physical bond-clear path.
- Resolve private addresses by scanning for the service/product identity; do
  not treat a BLE MAC as a permanent database key.
- Keep OTA authorization separate from normal data authorization and require a
  second physical-presence gate for firmware writes.

## 8. Buttons, raw ADC, and maintenance entry

### 8.1 Model-1552 AD-key evidence

The decoded target configuration uses one PB07 ADC ladder (**PROVEN for the
model-1552 artifact, UNVERIFIED for an untouched model-1542**):

- pull-up setting: 1000 schema units;
- ADC full scale: 4096;
- button 0 resistor: 100 schema units;
- button 1 resistor: 330 schema units;
- expected single-button ADC values: approximately 372 and 1016;
- stock quantizer: `<=694` is key 0; `695..2556` is key 1;
- scan interval 10 ms, filter count 2, LONG at 200 scans (2.00 s), first HOLD
  at 215 scans (2.15 s), repeat about 150 ms, click window 200 ms;
- the AD-key record enables its runtime long-press reset with an 8-second
  threshold.

Evidence:

- `C:\Users\jetha\Downloads\e87-reversing\firmware-catalog\jl-misctools-runs\1552\unpacked\files\cfg_tool.bin`,
  SHA-256 `CEC4551FA08F3ED70225095ACBD6CD5584E5EAB9CA418ED37F27102F66CD6833`.
- The packed four-byte config-item header begins at `cfg_tool.bin +0x34` as
  `53 0B 42 01`. Decoding its bitfields yields CRC `0x53`, item ID `0x20B`
  (`CFG_ADKEY_ID`), and payload length 20. The tempting little-endian `0x0142`
  at `+0x36` straddles the packed ID/length fields and is **not** the item ID.
  The 8/12/12-bit layout is recovered from DWARF for
  `cfg_tool.a(cfg_bin.c.o)` (`cfg_common.h:14-18`), member SHA-256
  `DA5CEBB2B82A3CA1FD90FE8048D9BA0226FCD5916AE65D3B4EFB104689D4E25A`.
  `SDK/interface/utils/syscfg_id.h:272-276` identifies decimal 523/`0x20B` as
  `CFG_ADKEY_ID`; `SDK/apps/watch/board/adkey_config.c:13-28` defines
  `struct adkey_info` with `u16 io_uuid` first. The payload begins at `+0x38`;
  its first `u16` is therefore `io_uuid = 0x4F49`.
  The pinned `SDK/cpu/config/gpio_file_parse.c:60-65` maps `0x4F49` to
  `IO_PORTB_07`; `0x4F4A`, not `0x4F49`, maps to `IO_PORTB_08`.
  `SDK/interface/driver/cpu/br35/asm/gpio_hw.h:8,32-33` evaluates those GPIOs
  to `0x17` and `0x18`, respectively. The record also carries pull-up 1000,
  ADC maximum 4096, `long_press_enable = 1`, `long_press_time = 8`, and
  resistors 100/330. The pinned `gpio_file_parse.c` SHA-256 is
  `7A57FC99B81C7904EFB2803A1A8F917DF6DBDAEC879F0CE8DE9A63E22E6CB661`.
- Model-1552 `app.bin`, SHA-256
  `A38B77E27B1DC73CAE0FBD8A7C4E3A04C64FF393FB4F27BC92A7578336BE0147`,
  contains the compiled adjacent mapping pairs
  `{0x0017, 0x4F49}, {0x0018, 0x4F4A}` at file offset `0xD2778`.
- `SDK/interface/driver/cpu/br35/asm/gpadc_hw.h:151-159` defines the BR35
  special ADC alias `AD_CH_IO_PB7 = AD_CH_PMU_PADC0`; the pinned interface has
  no `AD_CH_IO_PB8` counterpart. In the pinned `adc_io2ch()` implementation,
  PB07 returns `AD_CH_PMU_PADC0` / `0x0002030D`, while PB08 falls through to
  `UINT32_MAX`. The implementation is `cpu.a(gpadc_hw.c.o)`, member SHA-256
  `F30D89BDF4198CC0BC2E3F545E01490F0FF7F6F21E605E486AA738C4BD804EB9`.
  This independently rejects the old PB08 ADC interpretation.
  Because the API returns `u32` and stock code contains a stale `0xFF`
  comparison, custom code must require equality with the board profile's exact
  allowed channel; neither `!= 0xFF` nor merely `!= UINT32_MAX` is a valid
  acceptance test. Keep diagnostic channel fields 32-bit.
- The pinned official
  [`adkey_config.c:148-161`](https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200/-/blob/d0167685d032d745d88fe50233302edd46941622/SDK/apps/watch/board/adkey_config.c#L148-161)
  reads the target record, maps `io_uuid` through `uuid2gpio()`, and copies its
  reset enable/time into `platform_data`. Official threshold construction is at
  [`adkey_config.c:204-216`](https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200/-/blob/d0167685d032d745d88fe50233302edd46941622/SDK/apps/watch/board/adkey_config.c#L204-216).
- The pinned official
  [`adkey.c:80-82`](https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200/-/blob/d0167685d032d745d88fe50233302edd46941622/SDK/apps/common/device/key/adkey.c#L80-82)
  passes `__this->adkey_pin` to
  `gpio_longpress_pin0_reset_config()`. For this decoded target record, that is
  PB07, active low, 8 seconds, immediate release, with a 100 kOhm pull-up mode.
- Stock app AD scan parameter block at raw app offset `0xEFEFC`, flat address
  `0x0C0EFFFC`, pointing to RAM `0x0010767C`.

Expected ADC values are resistor-network calculations and remain **INFERRED
until measured on the physical board**.

`key 0` and `key 1` in this guide are electrical/logical identities. Which one
is the upper/lower or otherwise labeled physical button is **UNVERIFIED** and
must be recorded during the raw-ADC bench test before assigning user gestures.

### 8.2 Reset-layer reconciliation: PB07 owns both decoded phases

There are two reset configuration surfaces in the decoded model-1552 image.
They must be reviewed independently:

| Layer | Exact artifact evidence | Conclusion |
|---|---|---|
| Package/post-build | `C:\Users\jetha\Downloads\e87-reversing\firmware-catalog\extracted\e87-11.1.0.2\items\04_isd_config.ini`, SHA-256 `CEC1973E50FB7A3D74D04D6340C671A443D50C538C272E1B14567C71F9AED47A`, line 101: `RESET = PB07_08_0;`; no `RESET1` entry is present. | **PROVEN for model 1552:** the packed image requests PINR0 on PB07, 8 seconds, active low, during boot/pre-application setup. This line alone does not establish the AD ladder; the independent `cfg_tool.bin` plus UUID mapping above does. |
| Early power code | [`power_app.c:136-151`](https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200/-/blob/d0167685d032d745d88fe50233302edd46941622/SDK/cpu/br35/power/power_app.c#L136-151) calls PINR0 with time 0 before key setup. | **PROVEN source fact:** early application power setup disables the package-established PINR0 owner; it does not create a second concurrent reset channel. |
| Application AD-key record | The `cfg_tool.bin` record above selects UUID `0x4F49`, which the pinned target mapping resolves to PB07, and enables 8-second long press; active SDK code maps that record into `platform_data.adkey_pin`. | **PROVEN for model 1552:** later `adkey_init()` reprograms PINR0 for runtime use on PB07. |
| Official demo fallback | [`adkey_config.c:77-90`](https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200/-/blob/d0167685d032d745d88fe50233302edd46941622/SDK/apps/watch/board/adkey_config.c#L77-90) contains a hard-coded PB07 example. | **PROVEN source fact, not target behavior:** it is inside `#if 0`; the compiled path reads `CFG_ADKEY_ID`. Its PB07 value happens to agree, but it is not the target proof. |

PB07 is therefore the **sequential owner of PINR0 in both decoded phases**, not
one half of a PB07/PB08 handoff: the package owns PB07 in the boot/pre-app
window, early power code disables PINR0, and key initialization reprograms PB07
at runtime. The earlier PB08 conclusion came from assigning UUID `0x4F49` the
numeric GPIO value `0x18`; the pinned mapping proves that UUID is PB07/`0x17`.
The pinned board defaults are
[`CONFIG_RESET_PIN=PB07`, `TIME=08`, `LEVEL=0`](https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200/-/blob/d0167685d032d745d88fe50233302edd46941622/SDK/apps/watch/board/br35/board_ac707n_demo/board_ac707n_demo_global_build_cfg.h#L53-56),
while
[`isd_config_rule.c:262`](https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200/-/blob/d0167685d032d745d88fe50233302edd46941622/SDK/cpu/br35/tools/isd_config_rule.c#L262)
states that time `00` disables the packaged policy. Audit both owners because a
runtime PB07 change does not alter what the next cold boot package requests.
Corresponding model-1542 values remain **UNVERIFIED**.

For a custom image, choose and verify one of these policies:

- **No hardware long-press reset:** set the package producer's
  `CONFIG_RESET_TIME=00` (or its tool-version equivalent), set the AD-key
  `long_press_enable=0`, and inspect both the generated `isd_config.ini` and
  packed `cfg_tool.bin`. Disabling only one layer is incomplete.
- **Proposed staged 3/10/16-second design:** set the package producer's
  `CONFIG_RESET_TIME=00` and verify the generated line
  `RESET = PB07_00_0;`. Prevent the stock 8-second AD-key setup
  (`long_press_enable=0`); then have custom code
  directly own PB07 PINR0 at 16 seconds. The package grammar accepts only
  `00/01/02/04/08`, while the runtime implementation in
  `cpu.a(p33_io_pinr_v3.c.o)`, SHA-256
  `9DE940859A03F91B2552932A17107A136916AD587B5C7035F23B3952FBD74142`,
  explicitly maps 1, 2, 4, 8, and 16 seconds to codes 0 through 4. Other
  values outside that set are not generally rejected: apart from time 0
  (disable) and `UINT32_MAX` (leave unchanged), they can fall through to a raw
  shift. The board adapter must therefore exact-allowlist those five mappings.
  Do not try to encode runtime 16 as a package RESET token. The
  measured-profile board adapter call is
  `gpio_longpress_pin0_reset_config(IO_PORTB_07, 0, 16, 1, 1)`; the inspected
  implementation encodes active-low, `release = 1` PINR16 as `0x43`.
  Confirm the final INI, config record, runtime call argument, reset cause, and
  physical behavior before enabling updates.
- **Any alternate reset pin:** treat it as a new board-profile hypothesis. PB08
  is not an alternate model-1552 ADC ladder and must not be substituted for
  PB07 without direct model-1542 measurements.

### 8.3 Chord caveat and staged maintenance gesture

Pressing both buttons places the nominal resistors in parallel: about 76.744
schema units and a predicted ADC near 292. The stock logical key quantizer sees
that as key 0. `combination_key_translate()` is a stub, so stock logical events
cannot report a distinct two-button chord.

A custom early boot gate could sample raw ADC, calibrate a both-button band,
and require five continuous seconds. This is **PROPOSED**, not proven. The
electrical margin can become small with resistor tolerance and ADC noise;
measure released, each button, and both buttons across multiple badges,
temperatures, and battery voltages. Give one second of visible recognition
feedback before beginning the destructive maintenance action.

Preferred user-facing design (**PROPOSED**) is a staged hold on the maintenance
button, using logical raw key 0 only after its physical label has been measured:

- tap: show battery;
- hold 3 seconds: pairing;
- continue holding: visible countdown;
- hold 10 seconds: maintenance/update mode.

Both resistor-coded buttons share the PB07 ladder in the decoded model-1552
profile, so software cannot move a long-press fallback from one of those buttons
to the other: electrically they are values on the same pin. PB08 is a distinct
GPIO mapping and has no BR35
`AD_CH_IO_PB8` alias; it is not a second ADC button. Which pin and value bands
apply to the physical model-1542 remains **UNVERIFIED** until badge B telemetry.

The runtime implementation explicitly maps 1, 2, 4, 8, and 16 seconds; time 0
disables PINR0 and `UINT32_MAX` leaves it unchanged. Other values outside the
explicit set are not generally rejected and can fall through to a raw shift,
so the board adapter must reject them. The package RESET grammar is narrower
and accepts only `00/01/02/04/08`; it cannot express 16 seconds. After emitting
package `RESET = PB07_00_0;` (disabled despite the syntactically retained pin
token), configure PB07 directly through the runtime API for 16 seconds as the
normal liveness fallback. When the software FSM reaches its 10-second recovery
threshold, immediately call the
same API for **PB07** with time 0 before the user can reach 16 seconds. Wait for
release, re-arm PB07 at 16 seconds, and only then enter maintenance. If recovery
aborts, leave the fallback armed. Runtime calls never change the RESET token in
the next packaged boot, which is why the package must independently remain at
time `00`.

If a hung runtime never services the software FSM, the 16-second PB07 hardware
reset remains useful. At the earliest next application startup, record the reset
source immediately after `boot_power_init()`, explicitly disable PINR0, and test
`is_reset_source(P33_PPINR_RST)` before filesystem/resource/display/normal-BLE
startup. On that cause, wait for a valid released sample while feeding the
watchdog, re-arm PB07 at 16 seconds, and route directly to the minimal recovery
loop without relying on a flash flag. The reset-source bit does not encode the
pin or boot phase, so log boot phase and raw button state as well. The official
reset API and
time values are documented in JieLi's
[PINR reset documentation](https://doc.zh-jieli.com/AD24/zh-cn/master/PMU/softoff_powerdown/reset.html).

The FSM must time one stable, continuous selected-button press: release before 3
seconds shows battery; crossing 3 seconds starts pairing exactly once but must
not cancel the timer; crossing 10 seconds starts recovery exactly once. Until
this behavior is verified on hardware, the raw-ADC five-second chord remains a
guarded lab alternative, not a shipping shortcut.

Run the maintenance detector immediately after GPIO/GPADC, timer, and watchdog
setup, before mounting filesystems, parsing resources, starting the full UI, or
enabling ordinary BLE services. A boot-held path must use the same early raw
sampling and feed the watchdog. Its updater loop should have no dependency on
the main resource pack. This is soft recovery only: corruption before that hook
still requires physical MaskROM recovery. A PINR reset selects recovery only
because the new early startup code checks its reset source; neither stock
8-second reset configuration selects OTA mode by itself.

The 10-second action enters a minimal maintenance screen and starts only the
Bluetooth/RCSP services needed by the updater. It **must not call
`update_mode_api_v2()`**. Loader handoff is a later, authenticated protocol
transition described in section 12.

## 9. Battery curve and power policy

The curve at `cfg_tool.bin +0x50` (`3300:0` through `4120:100`) is **PROVEN
present but not proven consumed** by the target runtime. Do not use it as the
shipping curve merely because it is easy to decode.

Target model-1552 application analysis instead finds the runtime sampler at
`0x0C0177E6`: it takes eight readings, sorts them, discards the minimum and
maximum, and averages the middle six (**PROVEN by target disassembly/Ghidra**).
Preserve its integer semantics: double each half-VBAT reading into millivolts,
sort, sum indices 1 through 6, and compute `filtered_mv = sum / 6` using
truncating integer division. Do not round to nearest and do not add a ties-up
bias.
The runtime references these two piecewise tables (**PROVEN for model 1552;
selection policy and model-1542 applicability remain UNVERIFIED**):

| Percent | Discharge mV (`0x0C0E7F9A`) | Alternate/charge mV (`0x0C0E7FC6`) |
|---:|---:|---:|
| 100 | 4280 | 4370 |
| 90 | 4188 | 4300 |
| 80 | 4073 | 4194 |
| 70 | 3971 | 4085 |
| 60 | 3866 | 4015 |
| 50 | 3797 | 3956 |
| 40 | 3737 | 3916 |
| 30 | 3693 | 3890 |
| 20 | 3660 | 3856 |
| 10 | 3625 | 3795 |
| 1 | 3565 | 3565 |
| 0 | below 3565 | below 3565 |

For an ascending bracket `(v0, p0)..(v1, p1)`, calculate
`p0 + ((filtered_mv - v0) * (p1 - p0)) / (v1 - v0)` with truncating integer
division. Clamp below the first point to 0 and above the last point to 100;
exact table voltages return their exact table percentages. The alternate table
is present, but its selection policy is not established for the physical
model-1542. V1 therefore uses the discharge table both plugged and unplugged
until DMM/charger measurements justify a board-profile change.

Validate the divider and ADC scale with a DMM before enabling low-battery
shutdown. Log raw ADC, calculated millivolts, DMM voltage, radio state,
backlight level, and load. Add filtering and hysteresis; never permit firmware
update based solely on a noisy displayed percentage. Require a measured
voltage margin and stable power throughout an update.

The generic SDK provides DCDC/LRC deep-sleep configuration, low-power target
registration, light/sleep/deep/soft-off states, and GPIO/analog/RTC wake APIs:

- `SDK/apps/watch/board/br35/sdk_config.h:163-199`
- `SDK/interface/driver/power/power_manage.h:16-54,76-119`
- `SDK/interface/driver/power/power_wakeup.h:5-59,85-133`
- `SDK/cpu/br35/power/key_wakeup.c:12-24`

Before sleep: drain the DBI transfer with `lcd_wait_busy`, turn the backlight
off, send display-off (`28`) followed by sleep-in (`10`), wait at least 120 ms,
then release the LCD clock and quiesce BLE or enter the intended connection
mode. Arm the raw button wake source. On wake: acquire the LCD clock, apply the
recovered reset timing, replay the full exact init program, and repaint while
the backlight remains off; enable the backlight last. The recovered stock path
has no separate panel-rail callback, so do not invent a rail toggle. Measure
current and repeat at least 100 cycles; successful API calls are not a power
measurement.

### 9.1 Charge-through display operation

The stock badge's full-screen battery gauge on USB insertion proves that the
physical unit detects external power and executes a charge path. It does not by
itself prove charger pins, current limits, NVDC mode, or thermal limits. The
model-1552 target disassembly provides stronger application-level evidence
(**PROVEN for model 1552; model-1542 applicability remains UNVERIFIED**):

- charge-state byte `0x00103151` uses 0 offline, 1 low, 2 charging, and 3 full;
- charger dispatcher `0x0C03C848`, state derivation `0x0C03C990`, and full-state
  logic `0x0C03C920` are separate from charging-page function `0x0C011B52`;
- code at `0x0C014A58` treats states greater than 1 as charger-online.

The pinned official SDK exposes the same separation (**PROVEN SDK seam; exact
target configuration remains UNVERIFIED**):

- `SDK/cpu/br35/charge/charge_config.c:10-81` owns charger wake sources,
  `charge_data`, `charge_init`, and the online power rail selection;
- `SDK/apps/watch/battery/charge.c:74-81,188-337` owns electrical charge
  start/close and insertion/removal handling;
- `SDK/apps/watch/battery/charge.c:339-452` separately hides the current window
  and selects `ID_WINDOW_BATCHARGE` for charge events;
- `SDK/apps/watch/app_main.c:375-411` may route a plugged boot to
  `APP_MODE_IDLE/IDLE_MODE_CHARGE`, depending on board configuration;
- `SDK/apps/watch/mode/power_on/power_on.c:33-60` avoids the normal dial while a
  charger is online, and `SDK/apps/watch/ui/jlui_app/ui_screen_saver.c:140-149`
  applies a separate charged-screen policy.

For the local-rendering trial, charge-through operation is **REQUIRED BY THE
APPROVED DESIGN but hardware-unverified until the sacrificial-badge ladder**.
Keep the electrical charge and wake path, but replace the stock mode/UI routing
with one explicit policy:

| Event/state | Required application result |
|---|---|
| Boot with charger online | Enter normal E87 face and BLE service; never `IDLE_MODE_CHARGE` |
| Insert while awake | Continue the current face/BLE state and start charging; never show `ID_WINDOW_BATCHARGE` |
| Insert while button-2 `manual_sleep` is set | Continue charging but remain asleep until button 2 |
| Stay plugged and awake | Inhibit stock panel/backlight/application timeouts; continue BLE writes |
| Button 2 while plugged | Sleep/wake panel and BLE without closing the charger |
| Unplug while awake | Preserve the face and continue until button 2 or a safety condition stops it |
| Unplug during `manual_sleep` | Remain asleep until button 2 |

Do not rely only on global timeout macros. Make charger presence and
`manual_sleep` inputs to a small testable power-policy function, and ensure all
charger events bypass stock charging-page actions. The trial has no ordinary
inactivity timeout; button 2 is its user-level sleep control. Do not disable
charge termination, full detection, low-voltage protection, or any measured
current/thermal safeguard to obtain an always-on screen.

Hardware validation must include boot-plugged, insert/remove in every awake and
manual-sleep state, metric writes and reconnection while charging, button-2
sleep/wake without stopping charge current, full-charge termination, and an
eight-hour display-plus-BLE soak. Log supply current, battery voltage, charger
state, disconnects, unintended UI/power transitions, and enclosure/battery
temperature; stop immediately on abnormal heat, current behavior, swelling, or
odor.

## 10. Android host role

For the custom firmware, Android is the network/provisioning host, not the
renderer:

1. Fetch factory values and normalize them to versioned semantic fields.
2. Scan by custom service/product identity, connect, bond/encrypt, and discover
   characteristics.
3. Negotiate MTU/DLE/2M opportunistically.
4. Send the sequence and semantic values; await the badge's applied-sequence
   status.
5. Retry idempotently and persist the last confirmed sequence per badge.
6. Surface battery, firmware build ID, panel profile ID, and failure reason.
7. Enter pairing or maintenance only after the physical gate is observed.

The existing Flutter code is evidence for current stock connectivity and a
useful transport reference:

- `lib/e87/e87_const.dart` — current stock AE00/FD00 UUIDs and 368x368 JPEG
  upload target; it is not the direct-DBI panel geometry.
- `lib/e87/e87_client.dart` — Android BLE connection, MTU, notifications, and
  authentication order.
- `lib/e87/upload_session.dart` — stock image-transfer state machine.
- `lib/badge_sync.dart` — sequential per-badge orchestration.

Do not copy the stock image uploader into the normal custom-service path.
Quarantine maintenance/update code behind a separate interface and build flag.

## 11. Build, package, and verify

### 11.1 Board port

Create a distinct `CONFIG_BOARD_E87_1542` profile. Do not edit the generic
JL707N demo until it accidentally resembles the target.

Minimum porting order:

1. Clock, watchdog, debug output, GPADC, and raw maintenance gesture.
2. Flash capacity/partition assertions and persistent build/crash record.
3. Reconstructed JD9855 DBI driver and color-bar self-test.
4. Buttons and measured ADC bands.
5. Battery voltage and safe shutdown.
6. Custom BLE service and bonding.
7. Strip renderer, assets, and fonts.
8. Sleep/wake and current optimization.
9. OTA/maintenance last.

Disable unused audio, classic Bluetooth, sensors, USB classes, filesystem/UI
features, and demos deliberately. Rebuild from a clean tree after every config
change.

### 11.2 Required build outputs

Archive for every build:

- source commit and dirty-tree patch;
- toolchain and post-build-tool hashes;
- generated `sdk.ld`, `sdk.map`, and `sdk.elf`;
- section/heap/cache-RAM report;
- board configuration and partition map;
- panel init hash and panel-profile ID;
- asset/font manifest and golden preview;
- raw packaged firmware, UFW, and Qix wrapper hashes;
- machine-readable validation report.

### 11.3 Offline package gates

Before a badge sees the file, verify:

- PI32v2 entry is `0x0C000100` for this build;
- every load/runtime section fits its declared region;
- heap and task stacks meet the measured headroom target;
- the serial panel-probe build reserves and uses one aligned `0x5460` 360x30
  RGB565 buffer inside the current `0x6000` LCD tail, or the production build
  reserves at least `0xA8C0` for two exact stock buffers and re-proves all
  adjacent RAM/update boundaries;
- every partition is aligned, non-overlapping, and below the measured flash
  capacity;
- outer Qix length and CRC validate;
- UFW header, table, member lengths, and member CRCs validate;
- product/model, minimum bootloader, panel profile, partition-layout version,
  and anti-rollback policy match the intended badge;
- the v1 image preserves the existing single-bank contract, emits no dual-bank
  data artifact, and does not set a dual-bank layout flag;
- unpacking the generated package reproduces the expected app and resources;
- no key, token, local path credential, or uninitialized build data leaked into
  the package.

Never hand-edit a packaged image and then repair only the outer CRC. Regenerate
all layers from the pinned build inputs.

### 11.4 Hardware verification ladder

Use five explicitly labeled units so a failed low-level probe cannot consume
the only route to the next stage. Mark badge E untouched before writing badge A:

1. **Badge A — heartbeat:** boot only the nonconnectable BLE heartbeat and
   watchdog restart path; include no display, key, battery, filesystem, or
   recovery code.
2. **Badge B — PB07 ADC telemetry:** configure only PB07 and publish raw
   released/button-1/button-2/both samples. Measure clusters, noise, and physical
   key mapping before enabling any long hold. Require
   `adc_io2ch(IO_PORTB_07) == AD_CH_PMU_PADC0` from the exact board-profile
   allowlist and carry the channel as 32 bits in telemetry. PB08 is not the
   decoded model-1552 ADC input.
3. **Badge C — JD9855 fills:** keep the backlight off while comparing rails,
   pins, current, and reset timing with the untouched reference. Replay only
   the exact hashed init, then serially run black/white/red/green/blue
   `lcd_clear` calls with `lcd_wait_busy`. With one `0x5460` buffer, send twelve
   independently addressed 360x30 windows at y `0,30,...,330`, waiting after
   every draw. Validate corners, axes, clipping, orientation, byte/color order,
   and TE with captures. Only then test completion-callback double buffering
   with a linker-proven `0xA8C0` tail; prove `lcd_draw_continue` separately.
   Test backlight, the exact sleep/wake order, current, and 100 cycles. Do not
   enable button or update behavior in this image.
4. **Badge D — full/recovery:** only after B and C establish their profiles,
   integrate normal GATT/rendering, DMM-calibrated battery behavior, charging,
   buttons, package `RESET = PB07_00_0;`, direct runtime PB07 PINR16, and the
   reset-source early-maintenance route. Exercise every pre-loader cancel plus
   the loader reconnect/resume path; interrupt destructive programming only
   after a verified restore exists. Complete the plugged soak and a second
   custom rewrite here.
5. **Badge E — untouched reference:** keep it unflashed and read-only except
   benign identity queries.

Badge E remains untouched throughout. Stop the ladder on any mismatch; do not
move a failed image onto the next role merely because another badge is
available.

## 12. Anti-brick architecture

The current product layout and update chain are single-bank (**PROVEN for the
decoded model-1552 artifacts**). Firmware v1 must preserve that contract and
expose a minimal Bluetooth/RCSP maintenance profile; it must not silently turn
on dual-bank layout or the passive dual-bank API.

### 12.1 Required single-bank loader gate

The 10-second button path only advertises maintenance and makes the RCSP endpoint
available. The authenticated host, not the button handler, advances this flow:

1. Authenticate RCSP and complete the captured E1/E2 update inquiry. The device
   rejects wrong product/layout, low power, or an already-running update.
2. Download and verify the single-bank loader. In the pinned source, a successful
   inquiry schedules loader download when dual bank is off
   ([`rcsp_update.c:380-436`](https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200/-/blob/d0167685d032d745d88fe50233302edd46941622/SDK/apps/common/third_party_profile/jieli/rcsp/server/functions/rcsp_update/rcsp_update.c#L380-436)).
3. Only after loader success may RCSP issue update-start. The normal event path
   initializes loader download, waits for completion, and calls
   `update_mode_api_v2()` from `MSG_JL_UPDATE_START`
   ([`rcsp_update.c:793-826`](https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200/-/blob/d0167685d032d745d88fe50233302edd46941622/SDK/apps/common/third_party_profile/jieli/rcsp/server/functions/rcsp_update/rcsp_update.c#L793-826)).
4. That call copies the validated `loader_saddr` into `ota_addr`, constructs the
   CRC-protected update parameters, writes them, and performs the jump/reset
   preparation
   ([`update.c:440-466`](https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200/-/blob/d0167685d032d745d88fe50233302edd46941622/SDK/apps/common/update/update.c#L440-466),
   [`update.c:525-563`](https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200/-/blob/d0167685d032d745d88fe50233302edd46941622/SDK/apps/common/update/update.c#L525-563)).

Calling `update_mode_api_v2()` directly from the physical gesture is
**FORBIDDEN**: before loader download, `loader_saddr` can be zero, so the mode
call can prepare an invalid handoff. The Android host must drive ordinary RCSP
authentication, E1/E2 inquiry, loader transfer/verification, and only then
update-start.

Once the loader has entered destructive single-bank programming, the ordinary
application can become unavailable. That is not automatically a permanent
brick: the single-bank loader persists, re-advertises its update identity
(`xxx_update`/`xxx_LE_UPDATE` in official terminology), and supports host
reconnect/resume. Nevertheless, loss of the loader or its metadata still drops
to physical MaskROM recovery, so do not cross loader handoff without stable
power and a restore route.

Layer the v1 defenses:

1. **Early maintenance gate:** raw/staged physical gesture before UI/resources.
2. **Authenticated minimal RCSP:** no flash transition from the normal metrics
   service and safe timeout/cancel before loader handoff.
3. **Validated loader and image:** product/layout/panel IDs, lengths, hashes,
   CRCs, single-bank capability, and stable-power check.
4. **Reconnect/resume:** retain the loader advertisement and test interruption
   recovery at its documented boundary.
5. **Watchdog/boot counter:** return to maintenance after failed app starts when
   the application still executes.
6. **Physical MaskROM:** recovery floor when neither app nor loader can run.

### 12.2 Future A/B is a wired migration

Dual bank may fit only after a new layout. Usable space in the model-1552 map
ends at `0x7FF000`; the stock application member is about `0xFB000`, so two app
copies need about `0x1F6000`. Preserving the existing UIRES/USER/INORFS
allocation as well would exceed capacity by roughly `0xA7000`. A stripped app
and reduced resources may fit, but that sizing does not make migration safe.

JieLi's
[official update-structure guidance](https://doc.zh-jieli.com/AW31/zh-cn/master/update/update_structure/update_ota_strcuture.html)
warns that single- and dual-bank layouts cannot update one another. Therefore
A/B is a future, separately validated **wired/programmer full-repartitioning**
project on a sacrificial unit, never a v1 OTA feature. Only after that migration
is proven may the A/B design use inactive-bank write, full CRC verification, and
boot-info commit last. `dual_bank_update_allow_check()` and real rollback tests
remain mandatory for that future layout. Corruption before the early hook still
requires MaskROM.

### Physical recovery baseline

**PROVEN official facts:** BR35 MaskROM uses loader RAM at `0x102600`; the
official ROM enumerates as USB MSC `4C4A:2942`, inquiry `BR35 / UBOOT1.00`.
JieLi's forced-upgrade tool can repeatedly send `usbkey` while the target is
reset. The generic board uses internal/in-package flash.

Conservative recovery procedure:

1. Photograph the PCB and read the full chip marking.
2. Identify D+/D-/GND by continuity; use the badge's battery and a VBUS-cut USB
   breakout unless the rail topology has been measured.
3. Enter MaskROM and confirm both USB and inquiry identity.
4. Use a host with a strict read-only opcode allowlist. Read the first 4 KiB
   twice, then the JEDEC-reported capacity twice, and compare hashes.
5. Preserve the raw encrypted dump, chip/JEDEC identity, loader/tool hashes,
   timestamps, and wiring photos.
6. Prove restoration on a sacrificial badge before depending on it.

The open [`jl-uboot-tool` BR35 pull request](https://github.com/kagaimiq/jl-uboot-tool/pull/12)
reports hardware-tested AC707N read/write support and uses the official loader
core/address. It is community evidence, not an official guarantee. Starting a
proprietary loader has not been bus-traced, so a forensic zero-write guarantee
is unavailable.

Never permit erase/format or permanent key programming in the dump utility.
Use the vendor burner for a restore only after target, capacity, range, and
input hash are reviewed explicitly.

Official forced-upgrade references:

- [Upgrade/download procedure](https://doc.zh-jieli.com/Tools/zh-cn/dev_tools/forced_upgrade/upgrade_and_download.html)
- [Switch and USB/JTAG/external-flash behavior](https://doc.zh-jieli.com/Tools/zh-cn/dev_tools/forced_upgrade/toggle_switch.html)
- [Burner voltage guidance](https://doc.zh-jieli.com/Tools/zh-cn/mass_prod_tools/burner_1tuo8/burn_vol.html)

## 13. Lab workflow for agents

Maintain explicit unit roles:

- **Badge A / heartbeat:** advertisement-only first-write evidence.
- **Badge B / PB07 ADC:** one-pin raw telemetry and button-cluster evidence.
- **Badge C / JD9855:** display reset/init, solid fills, windows, and wake
  evidence.
- **Badge D / full-recovery:** integrated firmware, charge-through, RCSP, and
  controlled fault injection.
- **Badge E / reference:** untouched and read-only except benign identity
  queries.

If a separate known-model-1552 control or recovery-proof unit is later added,
record it as an additional role; do not silently repurpose badge E.

For every session:

1. Photograph unit label, screen, wiring, and supply setting.
2. Record badge role, advertised name/address, model/version, battery/DMM
   voltage, build hash, Android APK hash, and operator time.
3. Start serial, BLE HCI, USB, logic-analyzer, and current traces before the
   action.
4. Perform one bounded hypothesis test.
5. Hash and pull captures immediately.
6. Record observation separately from interpretation.
7. Update the evidence label only after independent reproduction.

Stop when a partition, panel parameter, power rail, updater result, or image
identity differs from expectation. Do not “try the nearest value” during a
write.

## 14. Known unknowns

- Exact untouched model-1542 flash image, stock partition metadata, and device
  calibration.
- Full physical package marking and whether dormant PSRAM is present.
- Whether the model-1552 360x360 QSPI descriptor, `PA05` reset, `PA06` TE,
  dedicated `PA07`/`PA12`/`PA08`-`PA11` bus, and `IO_LCD_PG` open-drain
  backlight mapping transfer unchanged to model 1542.
- Measured QSPI clock/framing, orientation/mirroring, RGB/BGR and byte order,
  360-pixel active-area/clipping behavior, TE edge/phase, optional read
  behavior, and sleep current on the physical model-1542 board.
- Exact model-1542 touch controller and touch pins, if touch is populated.
- Measured PB07 ADC clusters across units, temperature, voltage, and tolerance,
  the physical key-0/key-1 label mapping, and confirmation of the actual ADC pin
  on untouched model-1542 hardware. PB07 is proven only for decoded model 1552;
  PB08 is not its substitute.
- Hardware verification that the proposed 16-second fallback, 10-second
  software handoff, temporary PB07 reset disable, direct runtime PB07 re-arm,
  and package `RESET = PB07_00_0;` work across every boot phase and abort path.
- Actual deep-sleep current and every wake source on the target PCB.
- Exact boot-ROM/application boundary that survives every partial-write fault.
- Whether a stripped A/B package passes the target bootloader's dual-bank
  eligibility and rollback rules.
- Production bonding/privacy requirements and per-device provisioning process.

## 15. Evidence and primary-source index

Local evidence:

- `C:\Users\jetha\Downloads\e87-reversing\LAB-LOG-2026-08-26.md`
- `C:\Users\jetha\Downloads\e87-reversing\firmware-catalog\URLS.tsv`
- `C:\Users\jetha\Downloads\e87-reversing\firmware-catalog\download-manifest.json`
- `C:\Users\jetha\Downloads\e87-reversing\firmware-catalog\extracted\e87-11.1.0.2\manifest.json`
- `C:\Users\jetha\Downloads\e87-reversing\firmware-catalog\extracted\e87-11.1.0.2\items\04_isd_config.ini`
- `C:\Users\jetha\Downloads\e87-reversing\firmware-catalog\jl-misctools-runs\1552\unpacked\files\cfg_tool.bin`
- `C:\Users\jetha\Downloads\e87-reversing\firmware-catalog\extracted\e87-11.1.0.2\ghidra\app.bin`
- `C:\Users\jetha\Downloads\e87-reversing\ghidra-projects\e87-11.1.0.2-ac707.gpr`
- `C:\Users\jetha\AppData\Local\Temp\e87-android-probe`
- This repository's `lib/e87/` and `assets/icons/README.md`

Primary vendor sources:

- [Pinned e-badge SDK tree](https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200/-/tree/d0167685d032d745d88fe50233302edd46941622)
- [JieLi Android OTA SDK](https://github.com/Jieli-Tech/Android-JL_OTA)
- [JieLi iOS OTA SDK](https://github.com/Jieli-Tech/iOS-JL_OTA)
- [JieLi iOS Bluetooth SDK](https://github.com/Jieli-Tech/iOS-JL_Bluetooth)
- [JieLi bootloader source](https://github.com/Jieli-Tech/fw-Bootloader)
- [JieLi flash-parameter documentation](https://doc.zh-jieli.com/Tools/zh-cn/dev_tools/post_build/flash_params/index.html)
- [AC7074A vendor-authored datasheet mirror](https://www.yunthinker.com/static/upload/file/20260112/1768212696789849.pdf)

When evidence conflicts, prefer in this order: repeatable measurement on the
untouched target; validated exact-model artifact; validated neighboring-model
artifact; pinned official generic SDK; community implementation; inference.
