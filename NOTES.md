# Notes — B-431 / E87 / JieLi reference

Durable reference facts (not a narrative — see WORKLOG.md for that).

## Device identity

| Fact | Value |
|---|---|
| Badge | B-431 e-badge, mfr Shenzhen Qiushi IoT Technology Co. Ltd |
| Family | E87 / L8 circular-LCD "smart badge" pin |
| SoC | **JieLi (Zhuhai Jieli) AC697 family** — NOT ESP32 |
| Companion app | ZRun — Android `com.zijun.zrun` (dev "Zijun"), iOS id 6739612986 |
| Screen | round panel, image target **368 × 368** JPEG |
| Charging | 2 pads only (power + gnd). No exposed data lines. |

## Prior art
- `jumpingmushroom/e87_badge` — Python client + Home Assistant. Local copy at
  `B:\esp32\e87_badge`. Best implementation reference.
- `hybridherbst/web-bluetooth-e87` — Web Bluetooth client (MIT). Hosted:
  https://hybridherbst.github.io/web-bluetooth-e87/ . Origin of the JieLi cipher
  tables + AVI builder.
- `kagaimiq/jielie` — general JieLi RE knowledge base.
- `Jieli-Tech/fw-Bootloader`, `Jieli-Tech/fw-AC63_BT_SDK` — official SDK/boot.

## BLE / GATT map

Advertising:
- GAP local name `E87` (scan-response only; passive scanners miss it).
- Primary advert: 16-bit service `0xFD00`; manufacturer company id `28083`
  (0x6DB3) — opaque E87-family fingerprint.
- MAC is static-random / locally administered (our capture reference:
  `46:8D:00:01:2C:25`; OUI fingerprint `46:8D:00:…`).

Services / characteristics:
| Service | UUID | Role |
|---|---|---|
| Image upload + control (`AE00`) | `0000ae00-…` | the upload path |
| — write (`AE01`) | `0000ae01-…` | client→badge control + image data (write-without-response) |
| — notify (`AE02`) | `0000ae02-…` | badge→client acks / completion |
| JieLi RCSP (`FD00`) | `c2e6fd00-e966-1000-8000-bef9c223df6a` | device info, bootstrap, side-channel |
| — write (`FD02`) | `c2e6fd02-…` | RCSP commands |
| — notify | `c2e6fd01-…`, `c2e6fd03-…`, `c2e6fd05-…` | RCSP responses / ready signals |
| Battery | `0x180F` | standard battery level |

- Handle `0x0011` (`c2e6fd03-…`) is flagged in the RE notes as *possibly the
  OTA / firmware-upgrade channel*. Unconfirmed. See "Firmware" below.
- **MTU negotiated 517.** Not bonded/encrypted — an app-layer auth handshake
  gates uploads instead.

## FE wire framing (AE01/AE02)
```
FE DC BA | flag(1) | cmd(1) | len(2, big-endian) | body(N) | EF
```
- flags: `0xC0` command (req), `0x00` response/ack, `0x80` data/notify.
- total frame = 8 + len bytes.
- CRC everywhere is **CRC-16/XMODEM** (poly 0x1021, init 0x0000, no reflect,
  no final xor). `CRC16("123456789") == 0x31C3`.

## Auth handshake (6 steps, raw writes to AE01, NOT FE-framed)
1. phone→ `00` + 16 random bytes
2. badge→ `01` + 16 encrypted bytes
3. phone→ `02` + `"pass"`
4. badge→ `00` + 16-byte challenge
5. phone→ `01` + `enc(challenge)`  (JieLi cipher, below)
6. badge→ `02` + `"pass"`  (success)

### JieLi auth cipher (from `jieli_cipher.py` / upstream `jl-auth.ts`)
- Three 256-byte tables `KS_TABLE`, `SBOX`, `ISBOX` (RE'd from `libjl_auth.so`
  at offsets 0x1B4C / 0x1C4C / 0x1D4C). Full tables are in
  `e87_badge/src/e87_badge/jieli_cipher.py` — copy verbatim when porting.
- Static key `06 77 5F 87 91 8D D4 23 00 5D F1 D8 CF 0C 14 2B`.
- Magic `11 22 33 33 22 11` (repeated-pattern 2nd key).
- 16 rounds: rotate-3-left, SBOX/ISBOX swap, Fibonacci-butterfly mix, `0x9999`
  mask. Likely universal for this SDK rev (same key across multiple devices).
- Test vector: challenge `70B759 92E05EA7 8FEC533B A12979B5 90` →
  response `FFE9E6C8 0CE1F40F 5CCEAE20 831C5879`.

## 9-phase upload state machine (from `protocol.py`)
Seq byte is a shared monotonic counter across control+data frames.
1. **cmd 0x06** reset auth flag (`C0 06`, body `02 00 01`); also FD02
   `9EBD0B600D0003`.
2. **FD02 control** — time sync (`9E 45 08 02 07 00 <yr lo,hi> <mon> <day> 00
   <hr> <min>`), then `9E200816010001`, `9EB50B29010080`.
3. **cmd 0x03** device info (best-effort) + FD02 pokes.
4. **cmd 0x07** device config (best-effort).
5. **FD02 bootstrap** — wait for FD01 `C7` device-info, then FD03 `9EE6…` ready.
6. **cmd 0x21** begin upload — must be acked (else abort).
7. **cmd 0x27** transfer params (`… 00 00 00 00 02 01`) — negotiates CRC16.
8. **cmd 0x1B** file metadata: body = seq, size(4B BE), fileCRC16(2B BE),
   2 random bytes, ASCII temp name `<6hex>.<ext>`, `00`. Ack may hint chunk
   size (default **490**).
9. **cmd 0x01 / xmOpCode 0x1D** windowed data transfer:
   - data frame body: `seq, 0x1D, slot(0..7), crc16Hi, crc16Lo, <chunk>`.
   - badge sends `0x1D` window acks: `seq, status, winSize(2B), nextOffset(4B)`.
     Send exactly `winSize` bytes from `nextOffset`, then wait for next ack.
   - completion: badge `C0 20` FILE_COMPLETE → phone replies `00 20` +
     UTF-16LE path (`\u555C` + `YYYYMMDDHHMMSS` + `.ext`); badge `C0 1C`
     session close → phone acks `00 1C`. Non-zero status on close = failure.
   - ext `jpg` = static image, `avi` = animated (MJPG AVI).

## Image encoding
- Resize to **368×368** (LANCZOS), JPEG **quality ~88**, target ≤ ~16 KB.
  The raw JPEG bytes are what the badge stores/displays. No wrapper.
- Animated = MJPG frames in an AVI container (upstream `avi-builder`).

## Open questions — answers

### Q: Silent update (no "receiving" animation)?
**No silent path is exposed by the reverse-engineered protocol.** Every upload
(static jpg or animated avi) goes through the same cmd-0x1B/0x1D large-file
transfer, which writes into the badge's gallery ("BAG" folder) and drives the
firmware's on-screen receiving animation. There is no documented framebuffer /
live-mirror mode in the AE00 path, and the FD00 RCSP side-channel is used here
only for bootstrap. So: expect the receiving animation during each push; it is
firmware-driven. (Worth a real-device check: whether a *direct* push — vs. the
manual share→receive mode — shows a less intrusive indicator, and whether the
badge auto-displays the newest gallery entry afterward, which matters for a
"watch face" that updates every few minutes.)

### Q: Has anyone disassembled / reflashed one without opening it?
- No public teardown or custom firmware for **this specific badge** (B-431 /
  E87) was found.
- Generic JieLi custom-firmware IS a thing (kagaimiq/jielie; Jieli-Tech SDKs;
  people have reflashed AC690x speakers — e.g. changing BT name/sounds). But the
  documented flashing paths need **flashing mode**, normally entered over
  **USB/UART** — which this badge does not expose (2 pads only). So the standard
  route means **opening the case** and probing the board.
- The only no-teardown possibility is JieLi's **uboot OTA upgrade protocol**,
  potentially reachable over the FD00 RCSP channel (handle 0x0011 is a suspected
  OTA characteristic). Nobody has demonstrated this on these badges, we don't
  have the stock firmware image to recover to, and a bad OTA **bricks** the
  device with no USB recovery. **High risk, unproven.** Recommended stance:
  drive the stock firmware over BLE (the app we're building); treat reflashing
  as a separate, brick-risky research project only worth it with a spare unit
  and a wired recovery plan.
- **A full no-teardown runbook** for another agent to attempt the BLE OTA path
  is in [`docs/OTA-RESEARCH.md`](docs/OTA-RESEARCH.md): recon → obtain recovery
  image → prove the path with a benign reflash → only then a custom image, with
  the brick analysis and the JieLi RCSP-OTA references (`Jieli-Tech/Android-JL_OTA`
  et al.).

## Environment gotchas
- This PC has **no working Bluetooth** (phantom AX210). Use the phone as bridge.
- Phone = Galaxy Z Fold7, dual display. `adb ... screencap -p -d <id>`:
  cover display id `4630946872173396372`; inner `4630946449689556883`. The
  inner one reads black when folded/asleep.
- CDP from Windows: `websocket.create_connection(..., suppress_origin=True)`
  or Chrome returns 403 on the DevTools WebSocket.
