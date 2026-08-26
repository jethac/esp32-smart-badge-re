# Worklog — B-431 e-badge / factory-android-badges

Chronological log. Newest entries at the bottom. Times are loose; this is a
session narrative, not a git history.

## 2026-08-26 — Session 1

### Identifying the badge
- Starting point: a **B-431 e-badge**, manufacturer **Shenzhen Qiushi IoT
  Technology Co. Ltd**, initially assumed ESP32-based.
- Web searches for "B-431", the manufacturer, and the model turned up **nothing
  indexed** — no product page, manual, FCC filing, or teardown.
- The badge pairs with the **ZRun** app (`com.zijun.zrun`, dev "Zijun";
  iOS App Store id 6739612986). This is the tell: ZRun drives the E87/L8 family
  of circular LCD "smart badge" pins.
- **Correction to the ESP32 assumption:** these are **JieLi (Zhuhai Jieli)**
  SoCs, specifically the **AC697 family** (confirmed by others via the
  `jl_sdk_ac697_publish` string in a badge notification). Not ESP32.
- Reverse-engineering prior art found:
  - `jumpingmushroom/e87_badge` — Python client + Home Assistant integration.
  - `hybridherbst/web-bluetooth-e87` — Web Bluetooth (browser) client, MIT.
  - Both target the same JieLi RCSP + image-upload protocol.

### Hardware reality check
- The badge exposes **only two pads** on the back (charging = power + ground).
  No exposed UART/USB data lines. Reaching the JieLi chip's debug/download mode
  would require opening the case and probing the board.
- Consequence: **BLE is the entire practical attack surface.** Which is fine —
  it's the part already reverse-engineered.

### This PC's Bluetooth — dead end
- Found an "Intel Wireless Bluetooth" + "Intel Wi-Fi 6E AX210" in the registry,
  both flagged **`CM_PROB_PHANTOM`** — the AX210 card is physically gone.
  `Get-PnpDevice -PresentOnly` shows **zero** live Bluetooth. So no host radio.
- Plugged in a **TP-Link Archer TXE70UH** USB dongle. It's **Wi-Fi only**
  (RTL8852CU-based, no Bluetooth exposed by TP-Link on this model). Dead end for
  BLE. Its virtual CD (drive I:) only holds the Wi-Fi driver installer.

### Pivot: Android phone as the BLE bridge
- Connected a **Samsung Galaxy Z Fold7** (`SM-F966Z`, model `q7q`) over USB.
  adb already authorized (`RFCY806QRWA`).
- Drove **Chrome on the phone** via the DevTools protocol (adb forward
  `tcp:9222 -> localabstract:chrome_devtools_remote`), talking CDP from a tiny
  Python `websocket-client` script (`scratchpad/cdp.py`). Had to pass
  `suppress_origin=True` to dodge Chrome's 403 origin check, and force UTF-8
  stdout for emoji.
- Loaded `https://hybridherbst.github.io/web-bluetooth-e87/` (tab id 5700).
  **Only touched that one tab** — the phone has ~70 other tabs, left alone.
- User paired the badge in the native Chrome chooser.

### Protocol validated — the important result
- On our B-431: **JieLi auth handshake PASSED, GATT connected, badge identified.**
  The B-431 speaks the **E87/JieLi RCSP protocol**. This is the load-bearing
  finding: the reverse-engineered stack works against this badge.
- **BUT** every upload stalls. Root cause: this **web client always builds
  517-byte BLE frames**, and **Chrome on Android caps `writeValueWithoutResponse`
  at 512 bytes**. Even a 62 KB static QR hit it; the 992 KB animated patterns
  hit it harder. After one 8-chunk window the badge stops acking and it times
  out.
  - Tried monkey-patching the GATT write to split >512-byte writes — **wrong
    fix**: one `writeValueWithoutResponse` == one ATT Write Command; the badge
    does not concatenate two writes into one logical frame, so a split delivers
    two malformed frames. Flow control desynced after the first window. Reverted
    in spirit (abandoned the web-app path).
- **Conclusion:** the 512-byte cap is a limitation of *this web client under
  Chrome-Android*, not the badge or the protocol. A **native Android app** using
  `BluetoothGatt` at MTU 517 writes full 517-byte frames with no such cap. That
  is the path forward.

### Questions raised (answers in NOTES.md)
- Silent update? Badge shows an animated "receiving" image during transfer.
- Has anyone disassembled / reflashed one without opening it?

### The actual task (given mid-session)
Build **`factory-android-badges`**, a new repo based on
`github.com/jethac/factory-smartscreen`:
- Android (Flutter) app driving **multiple synced E87 badges** as BLE clients.
- Push an **Apple-Watch-inspired circular usage graph** per inference provider,
  **starting with Devin**:
  - **Devin logo in the middle.**
  - **On-demand usage in small grey text below it.**
  - **Two radial graphs: one for day, one for week.**

### Studied the reference repo (factory-smartscreen)
- Flutter/Dart. Key reusable file: **`lib/factory_client.dart`** — fetches a
  `Board` of `Tile`s from factory's `/api/display` (Bearer token). The README
  *explicitly* anticipates our use case: "a phone acting as a BLE gateway for
  ESP32 round displays calls `fetch(ids: [...])`". Tiles are pre-formatted
  (`text`="$17.34", `pct`=0..100, `colour`=hex, `band`), so devices never
  format or pick colours themselves.
- `lib/provider_marks.dart` — maps owner → SVG mark + brand colour. Devin's mark
  is vendored at `assets/icons/devin.svg`. Devin has **no brand colour** in the
  set (draws in foreground).
- `lib/tile_groups.dart` — `ownerOf(tile)` = 2nd `:`-segment of the id
  (`sub:devin:week` → `devin`).

### Read the full E87 protocol implementation (to port to Dart)
- Local Python package `e87_badge/src/e87_badge/` is a complete implementation:
  `const.py`, `frame.py`, `crc.py`, `jieli_cipher.py`, `auth.py`, `notify.py`,
  `protocol.py` (9-phase upload state machine), `client.py`, plus media encoders.
  Full protocol details captured in NOTES.md.

### Deliverables requested
- WORKLOG.md + NOTES.md (this + companion). ← you are here.

### Design derisk — watch-face mock (confirmed)
- Rendered the Devin face as an HTML/canvas mock, injected into a fresh Chrome
  tab on the phone via CDP, and screenshotted it. It matches the brief exactly:
  Devin mark centred (its interior negative space renders correctly via the
  SVG's evenodd fill), "$17.34" on-demand in grey below, outer green **day**
  ring + inner amber **week** ring over faint tracks. Saved to
  `docs/design-mock-devin.png`. This fixed the exact geometry to port to Flutter
  (368 canvas, r=158/120, stroke 26, arcs from −90° clockwise, rounded caps).

### Build — first scaffold pushed
Created **github.com/jethac/factory-android-badges** (private) and pushed the
initial scaffold (45 files):
- Vendored verbatim from factory: `factory_client.dart`, `provider_marks.dart`,
  `tile_groups.dart`, `assets/icons/devin.svg`, plus Android scaffolding +
  launcher icons.
- Ported the E87/JieLi protocol to Dart under `lib/e87/`: framing, CRC-16/XMODEM,
  the byte-exact JieLi auth cipher (with the captured test vector in
  `test/jieli_cipher_test.dart`), the 6-step handshake, and the 9-phase windowed
  upload state machine. `e87_client.dart` uses `flutter_blue_plus` (MTU 517,
  490-byte chunks → 503-byte frames, under the ATT limit that broke the web app).
- `render/provider_face.dart` paints the watch face → 368×368 JPEG;
  `render/devin_face.dart` maps a factory `Board` → the Devin `FaceModel`.
- `badge_sync.dart` fetches once, renders once, pushes to every badge on a timer.
- `main.dart` control-surface UI: preview, E87 scan, per-badge status, Sync now.

### Honest status
- **Unbuilt.** No Flutter toolchain in this environment, so nothing here has been
  compiled or run. The protocol is a faithful transcription of the working Python
  reference; the cipher/CRC ports are pinned by test vectors that a
  `flutter test` will confirm.

### Next steps
- [ ] On a Flutter machine: `flutter pub get && flutter test` (cipher/CRC vectors).
- [ ] Fill `lib/config.dart`: factory baseUrl/token, real Devin tile ids, badge ids.
- [ ] `flutter run`; scan for the B-431, add its id, Sync now; watch a push land.
- [ ] Verify the badge auto-displays the newest gallery image (watch-face behaviour).
- [ ] Tune ring semantics / colours against the real numbers if needed.
