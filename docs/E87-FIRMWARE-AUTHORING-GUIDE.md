# E87 firmware authoring guide

**Audience:** an agent implementing, reviewing, packaging, or recovering custom
firmware for the E87 badge family.

**Purpose:** preserve the current evidence so future work starts from the known
AC707N/BR35 baseline instead of repeating the earlier AC697/BR30 hypothesis.
This is an engineering guide, not a claim that every badge sold as E87 has the
same PCB.

**Evidence date:** 2026-08-27. The exact stock model-1542 image has not been
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
GC9B71 QSPI display. Copying that profile explains neither the captured
368x368 JPEG nor the stock descriptor.

### 5.1 Stock descriptor and command list

The following is **PROVEN from the validated model-1552 plaintext app**:

- Displayed/captured image geometry is 368x368.
- A registered LCD descriptor is at app file offset `0xEF688`, flat address
  `0x0C0EF788` when imported at `0x0C000100`.
- Its name pointer resolves to ASCII `jd9855`.
- Column alignment is 2; row alignment is 2; radius is 180.
- Init pointer is `0x0C0E59E0`; its file offset is `0xE58E0`.
- Init length is `0x291` / 657 bytes.
- Init SHA-256 is
  `BB0767D3E0BF4AD982725C6A38A9168DDF9E5BA2E3D4D595B1FFBDD17E5B89FF`.
- The same command blob is present in the decoded 1558 and 1606 variants.

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

Its tail enables TE (`35 00`), selects RGB565 (`3A 55`), sends sleep-out
(`11`), delays 120 ms, sends display-on (`29`), and delays 20 ms.

`jd9855` is therefore a strong embedded identity, but no matching public driver
or datasheet has been validated. Treat the controller name as **INFERRED** until
read-ID or package/logic-analyzer evidence confirms it.

### 5.2 What is still missing

The descriptor's parameter pointer targets RAM, so the flash descriptor does
not by itself reveal the complete bus setup. These remain **UNVERIFIED**:

- exact QSPI/SPI submode and write framing;
- DBI clock/fps and clock polarity;
- CS/DC/read/TE/reset/backlight pins and active levels;
- orientation/MADCTL and RGB/BGR byte order;
- column/page/RAM-write commands and any 368x368 window offsets;
- whether TE is edge- or level-driven in the target board code.

Reconstruct them systematically:

1. Define `struct lcd_drive` at `0x0C0EF788` in Ghidra and name every function
   pointer above.
2. Find all references to RAM `0x00107024`, especially writes before `lcd_init`.
3. Apply the official [`struct dbi_param`](https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200/-/blob/d0167685d032d745d88fe50233302edd46941622/SDK/interface/ui/cpu/br35/dbi.h#L189-285)
   layout and recover dimensions, buffer count/size, fps, SPI mode, pixel type,
   format, pin selectors, QSPI opcodes, DCS window commands, and polarity.
4. Trace the backlight/sleep functions and board GPIO initialization; do not
   infer pins from the generic GC9B71 profile.
5. Confirm on a sacrificial badge with a logic analyzer, starting at or below
   the recovered clock. Capture reset, init, TE, one solid fill, and one small
   aligned window.
6. First render red/green/blue/white/black bars. A swapped color, mirrored
   image, wrap at an edge, or intermittent first line is a bus/window bug, not
   an asset bug.

Do not substitute the SDK's dormant JD5858 360x360 MCU driver. Its geometry,
8-bit bus, init prefix, and timing differ from the stock evidence.

## 6. Rendering without a framebuffer

A 368x368 RGB565 framebuffer is 270,848 bytes, larger than the generic app RAM
budget before stacks, Bluetooth, and application state. The firmware should be
strip-buffered and PSRAM-independent.

Recommended design (**INFERRED/PROPOSED**):

- Two 16-line buffers require `368 * 16 * 2 * 2 = 23,552 = 0x5C00` bytes. The
  generic linker reserves only `0x5000`, so this configuration does **not** fit
  unchanged. Expand the aligned LCD tail to at least `0x6000` and re-prove heap
  and region boundaries, or use two 8-line buffers (`11,776 = 0x2E00` bytes).
- Statically allocate and align both buffers. Do not allocate in the draw loop.
- At each frame, wait for TE at the defined boundary, render strip N while DBI
  transmits strip N-1, and swap on the completion callback.
- Use `lcd_draw` for the first window and `lcd_draw_continue` only when the
  recovered target bus mode supports it. These are nonblocking APIs in
  `SDK/interface/ui/cpu/br35/dbi.h:346-368,449-459`.
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

The decoded target configuration uses one PB08 ADC ladder (**PROVEN for the
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
- The AD-key record header is `CFG_ADKEY_ID = 0x0142` at `cfg_tool.bin +0x36`;
  this is **not** the pin UUID. Its actual `io_uuid = 0x4F49` is at `+0x38`.
  The target `uuid2gpio` table maps that value to GPIO `0x18`, PB08. The record
  also carries pull-up 1000, ADC maximum 4096, `long_press_enable = 1`,
  `long_press_time = 8`, and resistors 100/330.
- The pinned official
  [`adkey_config.c:148-161`](https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200/-/blob/d0167685d032d745d88fe50233302edd46941622/SDK/apps/watch/board/adkey_config.c#L148-161)
  reads the target record, maps `io_uuid` through `uuid2gpio()`, and copies its
  reset enable/time into `platform_data`. Official threshold construction is at
  [`adkey_config.c:204-216`](https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200/-/blob/d0167685d032d745d88fe50233302edd46941622/SDK/apps/watch/board/adkey_config.c#L204-216).
- The pinned official
  [`adkey.c:80-82`](https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200/-/blob/d0167685d032d745d88fe50233302edd46941622/SDK/apps/common/device/key/adkey.c#L80-82)
  passes `__this->adkey_pin` to
  `gpio_longpress_pin0_reset_config()`. For this decoded target record, that is
  PB08, active low, 8 seconds, immediate release, with a 100 kOhm pull-up mode.
- Stock app AD scan parameter block at raw app offset `0xEFEFC`, flat address
  `0x0C0EFFFC`, pointing to RAM `0x0010767C`.

Expected ADC values are resistor-network calculations and remain **INFERRED
until measured on the physical board**.

`key 0` and `key 1` in this guide are electrical/logical identities. Which one
is the upper/lower or otherwise labeled physical button is **UNVERIFIED** and
must be recorded during the raw-ADC bench test before assigning user gestures.

### 8.2 Reset-layer reconciliation: PB07 is not the AD ladder

There are two reset configuration surfaces in the decoded model-1552 image.
They must be reviewed independently:

| Layer | Exact artifact evidence | Conclusion |
|---|---|---|
| Package/post-build | `C:\Users\jetha\Downloads\e87-reversing\firmware-catalog\extracted\e87-11.1.0.2\items\04_isd_config.ini`, SHA-256 `CEC1973E50FB7A3D74D04D6340C671A443D50C538C272E1B14567C71F9AED47A`, line 101: `RESET = PB07_08_0;`; no `RESET1` entry is present. | **PROVEN for model 1552:** the packed image requests PINR0 on PB07, 8 seconds, active low, during boot/pre-application setup. This is not evidence that the buttons use PB07. |
| Early power code | [`power_app.c:136-151`](https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200/-/blob/d0167685d032d745d88fe50233302edd46941622/SDK/cpu/br35/power/power_app.c#L136-151) calls PINR0 with time 0 before key setup. | **PROVEN source fact:** early application power setup disables the package-established PINR0 owner; it does not create a second concurrent PB07/PB08 reset channel. |
| Application AD-key record | The `cfg_tool.bin` record above selects PB08 and enables 8-second long press; active SDK code maps that record into `platform_data.adkey_pin`. | **PROVEN for model 1552:** later `adkey_init()` reprograms PINR0 for runtime use on PB08. |
| Official demo fallback | [`adkey_config.c:77-90`](https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200/-/blob/d0167685d032d745d88fe50233302edd46941622/SDK/apps/watch/board/adkey_config.c#L77-90) contains a hard-coded PB07 example. | **PROVEN source fact, not target behavior:** it is inside `#if 0`; the compiled path reads `CFG_ADKEY_ID`. Citing this fallback as the target runtime pin caused the earlier PB07/PB08 conflation. |

PB07 and PB08 are therefore **sequential owners of PINR0, not concurrent reset
channels**: the package owns PB07 in the boot/pre-app window, early power code
disables PINR0, and key initialization reprograms it for PB08 at runtime. The
pinned board defaults are
[`CONFIG_RESET_PIN=PB07`, `TIME=08`, `LEVEL=0`](https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200/-/blob/d0167685d032d745d88fe50233302edd46941622/SDK/apps/watch/board/br35/board_ac707n_demo/board_ac707n_demo_global_build_cfg.h#L53-56),
while
[`isd_config_rule.c:262`](https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200/-/blob/d0167685d032d745d88fe50233302edd46941622/SDK/cpu/br35/tools/isd_config_rule.c#L262)
states that time `00` disables the packaged policy. Audit both owners because a
runtime PB08 change does not alter what the next cold boot package requests.
Corresponding model-1542 values remain **UNVERIFIED**.

For a custom image, choose and verify one of these policies:

- **No hardware long-press reset:** set the package producer's
  `CONFIG_RESET_TIME=00` (or its tool-version equivalent), set the AD-key
  `long_press_enable=0`, and inspect both the generated `isd_config.ini` and
  packed `cfg_tool.bin`. Disabling only one layer is incomplete.
- **Proposed staged 3/10/16-second design:** disable the inherited PB07 package
  reset with `CONFIG_RESET_TIME=00`; prevent the stock 8-second AD-key setup
  (`long_press_enable=0`) unless the generated record itself is deliberately
  changed to 16 seconds; then have custom code explicitly own PB08 PINR at 16
  seconds. Confirm the final INI, config record, call argument, and physical
  behavior before enabling updates.
- **Intentional PB07 reset:** retain it only after identifying what drives PB07
  on the actual PCB and proving that it cannot interrupt the PB08 maintenance
  gesture. Document it as a separate recovery input.

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

Both resistor-coded buttons share the PB08 ladder, so software cannot move a
long-press fallback from one of those buttons to the other: electrically they
are values on the same pin. PB07 is the separate package reset setting described
above, not a second ADC button.

The official API accepts 0 (disable), 1, 2, 4, 8, or 16 seconds, with the
release flag causing reset at the threshold. After removing the packaged PB07
reset, configure PB08 for 16 seconds as the normal liveness fallback. When the
software FSM reaches its 10-second recovery threshold, immediately call the
same API for **PB08** with time 0 before the user can reach 16 seconds. Wait for
release, re-arm PB08 at 16 seconds, and only then enter maintenance. If recovery
aborts, leave the fallback armed. Calling time 0 for the current PINR0 owner does
not change a retained PB07 policy in the next packaged boot.

If a hung runtime never services the software FSM, the 16-second PB08 hardware
reset remains useful. At the earliest next application startup, record the reset
source and, after the minimum clock/GPIO/ADC/watchdog initialization, test
`is_reset_source(P33_PPINR_RST)`. Route that reset directly to the minimal
recovery loop without relying on a flash flag. The reset-source bit does not
encode which sequential PINR0 owner caused the reset, so log boot phase and raw
button state as well. The official reset API and
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

Before sleep: finish/abort DBI transfer, put the panel into sleep, turn off the
backlight, quiesce BLE or enter the intended connection mode, and arm the raw
button wake source. On wake: restore clocks and DBI state, exit panel sleep with
the recovered delays, then redraw. Measure current in every state; successful
API calls are not a power measurement.

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

- `lib/e87/e87_const.dart` — current stock AE00/FD00 UUIDs and 368x368 target.
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
- the LCD tail is at least `0x6000` for two 16-row 368-wide RGB565 buffers, or
  the build deliberately selects the `0x2E00` two-8-row alternative;
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

Run on a sacrificial unit in this order:

1. Boot heartbeat and watchdog recovery, no display.
2. Panel reset/init and static color bars at conservative clock.
3. Aligned partial windows, then double-buffered full refresh.
4. Backlight, panel sleep, wake, and 100-cycle repeat.
5. Raw ADC capture and button gestures, including release/noise cases; scope
   PB07 and PB08 separately and verify the generated package/runtime reset
   policy before any deliberately long hold.
6. DMM-calibrated battery read and low-voltage behavior on a current-limited
   supply.
7. BLE advertising, bond, reconnect, replay rejection, and semantic update.
8. Overnight connection/sleep/current test.
9. Exercise every pre-loader cancel plus the loader's reconnect/resume path;
   deliberately interrupt destructive programming only after a verified restore
   exists.
10. Restore the preserved stock dump and verify that restoration itself is
    repeatable.

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

- **Reference:** untouched, read-only except benign identity queries.
- **Sacrificial development:** custom builds and fault injection.
- **Recovery proof:** used to demonstrate that the preserved dump restores.
- **Control:** known model-1552 firmware when comparing transport behavior.

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
- JD9855 bus mode, clock/fps, pin mapping, polarity, orientation, byte order,
  address-window offsets, and TE electrical behavior.
- Exact model-1542 touch controller and touch pins, if touch is populated.
- Measured PB08 ADC clusters across units, temperature, voltage, and tolerance,
  the physical key-0/key-1 label mapping, and the purpose/drive conditions of
  PB07 on each board variant.
- Hardware verification that the proposed 16-second fallback, 10-second
  software handoff, temporary PB08 reset disable, and absence of an unintended
  package PB07 reset work across every boot phase and abort path.
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
