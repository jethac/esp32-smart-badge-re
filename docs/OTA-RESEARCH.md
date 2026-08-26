# No-teardown firmware replacement on the B-431 / E87 badge — research brief

**Audience:** an agent picking this up cold, with no prior session context.
**Goal:** determine whether the badge's firmware can be modified or replaced
**over BLE, without opening the case**, and if so, do it safely.
**Status:** unattempted. This is a plan, not a result. Read the whole
"Brick risk" section before you write a single byte to the device.

> **One-line summary:** In theory yes, via JieLi's RCSP-over-BLE OTA path — the
> same protocol JieLi's own `Android-JL_OTA` / `iOS-JL_OTA` libraries speak. In
> practice it is unproven on this badge, the AC697 is poorly supported by the
> open tooling, and there is **no USB/UART recovery** if it bricks. Do not do
> this on the only unit.

---

## 1. Why the usual routes are closed

- **Chip:** JieLi (Zhuhai Jieli) **AC697 family**, JieLi's **br30** target.
  Confirmed by the `jl_sdk_ac697_publish` string in a badge notification.
- **Physical access:** the badge exposes **two pads only** on the back — power
  and ground. **No USB D+/D−, no UART.** JieLi's normal flashing tools
  (`isd_download`, the USB "UBOOT" download protocol, the JL USB updater) all
  need the chip in **download mode over USB/UART**, which those two pads cannot
  provide. Reaching them means opening the case and soldering to the board —
  which is exactly what "no-teardown" rules out.
- **Open-source wired flasher gap:** `kagaimiq/jl-uboot-tool` (USB UBOOT
  protocol dumper/flasher) realistically supports only **BR17–BR25 (AC690–
  AC696)**. **br30/AC697 has protocol quirks it does not handle.** So even if
  you opened the case, that tool is not turnkey for this chip.

**Therefore the only no-teardown path is JieLi's RCSP OTA over BLE.**

---

## 2. What is already known / already working

This repo (`factory-android-badges`) and its sibling notes contain a **working,
authenticated RCSP BLE session** with this badge. Reuse it — do not re-derive.

- **GATT map, framing, and the JieLi auth cipher** are documented in
  [`../NOTES.md`](../NOTES.md). Auth is a 6-step handshake; the cipher is ported
  byte-exact in [`../lib/e87/jieli_cipher.dart`](../lib/e87/jieli_cipher.dart)
  (and in the Python reference `jumpingmushroom/e87_badge`). **RCSP auth must
  succeed before any OTA command — all JieLi ops fail without it.** We have auth
  working on hardware.
- **The suspected OTA channel:** in the JieLi RCSP 128-bit service
  `c2e6fd00-e966-1000-8000-bef9c223df6a`, characteristic **handle `0x0011`
  (`c2e6fd03-e966-1000-8000-bef9c223df6a`, Notify+Write+Read)** was flagged
  during reverse engineering as *"possibly OTA / firmware upgrade channel."*
  This is the first thing to probe.
- **Existing clients you can drive:** the Dart client here, the Python
  `e87_badge` package (`B:\esp32\e87_badge`, has a live BLE stack), and
  `hybridherbst/web-bluetooth-e87`. Any of them gets you an authenticated
  session to send raw RCSP frames from.

---

## 3. How JieLi RCSP OTA works (from JieLi's own SDKs)

Ground everything below in JieLi's **official, open-source** OTA implementations
— they are the authoritative spec:

- **`Jieli-Tech/Android-JL_OTA`** — RCSP OTA process wrapped in a library
  (`jl_bt_ota.aar`), plus a **demo APK** and **OTA SDK development docs**.
  Apache-2.0. This is the primary reference.
- **`Jieli-Tech/iOS-JL_OTA`** + **`iOS-JL_Bluetooth`** — same protocol; the iOS
  READMEs spell out the BLE flow in English (RCSP write/read characteristics,
  notify setup, MTU-after-notify, auth-first).
- **`Jieli-Tech/fw-Bootloader`** — the **uboot** source for **br30/AC697N**;
  contains the "uboot upgrade instructions" and "uboot upgrade protocol flow"
  docs, and defines how an upgrade image is consumed.
- **`Jieli-Tech/fw-AC63_BT_SDK`** — an SDK whose OTA code is close to the AC69
  series (no audio); useful for the update-file format and OTA command set.

Known operational facts from these sources:

1. **Auth first.** RCSP authentication must complete before OTA. (Done.)
2. **MTU after notify.** Enable notifications on the RCSP read characteristic,
   then negotiate MTU (the JL demo waits ~1000 ms). Order matters.
3. **Upgrade file.** The JL OTA SDK consumes a JieLi **upgrade file**
   (`.ufw`/`.bfu`-style container: header + file table + per-file CRC). The JL
   Android demo expects it at
   `/Android/data/com.jieli.otasdk/files/upgrade/`. The binary layout is in the
   OTA SDK docs / produced by JieLi's PC-side "upgrade file production tool".
4. **DFU reboot changes the BLE address.** Entering upgrade mode, the device
   **reboots and re-advertises on a different BLE address**; the JL SDK exposes
   `onNeedReconnect(originalAddr, dfuAddr)`. Your client must rescan and
   reconnect to the DFU address to finish the transfer.
5. **Dual-bank (maybe).** JieLi supports dual-bank ("双备份") OTA: write the
   passive bank, then a switchover command boots it — brick-safe. **But small-
   flash badges are often single-bank**, which is *not* brick-safe. Determine
   which this badge is before trusting recovery (see §5).

---

## 4. Runbook (in order; each step gates the next)

**Phase A — Non-destructive recon (safe, do all of this first).**
1. Get an authenticated RCSP session (reuse this repo's client / the Python
   `e87_badge`). Confirm auth succeeds.
2. On the RCSP service, subscribe to `c2e6fd01/03/05` and enumerate. Send the
   RCSP **device-info / version** queries (the `e87_badge` protocol notes and
   the JL OTA SDK list the opcodes) and record: firmware version string, chip
   id, and any **OTA-capability / dual-bank flags** the device reports.
3. **Capture ground truth.** Does **ZRun** (or any vendor app) offer a firmware
   update for this badge? If yes, this is the single most valuable artifact:
   - Sniff the BLE while ZRun performs the update (Android **HCI snoop log**:
     enable in Developer Options, reproduce, pull `btsnoop_hci.log`, open in
     Wireshark). This gives you the exact OTA opcodes, file framing, DFU-reboot
     sequence, and reconnect behaviour **for this specific device**.
   - Also pull ZRun's update asset if it downloads one — that *is* a stock
     upgrade file for this badge (see §5, recovery).
4. **Static-analyze the app.** `jadx` on the ZRun APK (`com.zijun.zrun`) and, for
   comparison, the JL OTA demo. Search for: `ota`, `upgrade`, `Rcsp*Ota`,
   `dualBank`/`doubleBank`, `.ufw`, `bootInfo`, `reconnect`, `dfu`. Confirm
   whether ZRun even links the JL OTA library and what image it feeds it.

**Phase B — Obtain a recovery image (do NOT skip).**
5. Acquire a **known-good stock upgrade file** for this exact badge before
   writing anything. Candidates, best first:
   - ZRun's own downloaded update asset (from step 3).
   - An OTA **read/dump** path if the RCSP protocol exposes one.
   - JieLi tools / a matching br30 stock image (least certain to match).
   Without a recovery image, a bad flash on a single-bank device is a permanent
   brick with no wired recovery. **No recovery image → stop here.**

**Phase C — Prove the OTA path with a benign image.**
6. Re-flash the **stock image** over your own RCSP-OTA client (ported from the
   JL OTA library's flow, or by replaying/parametrizing the captured ZRun
   session). Success here proves you control the OTA path end-to-end *without
   changing behaviour* — the safe milestone.
7. Only after step 6 works reliably: build a **minimal modified firmware** from
   the JieLi SDK (`fw-Bootloader` br30 + the matching BT SDK), packaged with
   JieLi's upgrade-file tool, and OTA it. Start with the smallest possible
   change (e.g. a string), not a rewrite.

---

## 5. Brick risk — read before writing

- **No USB/UART recovery exists on this hardware.** A failed flash that the
  bootloader won't recover from is a **permanent brick**. This is the dominant
  risk and it is not reversible.
- **Determine bank mode first.** If the device is **dual-bank**, a bad image
  lands in the passive bank and the switchover/rollback protects you. If
  **single-bank**, there is no safety net — any interruption or bad image mid-
  write can brick it. Establish this in Phase A before Phase C.
- **DFU-reboot reconnect is a failure point.** The address changes on reboot; if
  your client doesn't rescan/reconnect to the DFU address in time, the transfer
  can abort mid-upgrade. Handle `onNeedReconnect` semantics explicitly.
- **Test on a spare.** Buy a second identical badge and be willing to brick it.
  Do not do first attempts on the only unit.
- **Keep power stable.** Charge fully; a badge that sleeps or browns out mid-
  write is the classic brick cause.

**Stop conditions:** stop and report if — (a) no recovery image can be obtained;
(b) the device reports single-bank and you have no spare; (c) the RCSP OTA
opcodes can't be confirmed against either a ZRun capture or the JL OTA SDK; (d)
the DFU device won't re-advertise after the reboot command in testing.

---

## 6. Tools & references

**Local (this machine):**
- This repo's Dart RCSP client: `lib/e87/` (auth + framing + notify bus).
- Python reference with a live BLE stack: `B:\esp32\e87_badge`.
- Protocol facts + auth cipher + GATT map: `../NOTES.md`.

**JieLi official (authoritative):**
- `Jieli-Tech/Android-JL_OTA` — RCSP OTA lib + demo + docs (primary).
- `Jieli-Tech/iOS-JL_OTA`, `Jieli-Tech/iOS-JL_Bluetooth` — English BLE flow.
- `Jieli-Tech/fw-Bootloader` — br30/AC697 uboot + upgrade-protocol docs.
- `Jieli-Tech/fw-AC63_BT_SDK` — OTA code close to the AC69 series.

**Community RE:**
- `kagaimiq/jielie` — JieLi internals knowledge base.
- `kagaimiq/jl-uboot-tool` — USB UBOOT flasher (BR17–25 only; **AC697 quirks
  unhandled**) — relevant only if the no-teardown path fails and you open the
  case anyway.

**Capture method:** Android Developer Options → enable Bluetooth HCI snoop log →
reproduce a ZRun firmware update → `adb pull` the `btsnoop_hci.log` →
Wireshark. This is the highest-signal artifact available and costs nothing.

---

## 7. Open questions to answer (fill these in as you learn)

- [ ] Does ZRun expose a firmware-update feature for this badge at all?
- [ ] Is the badge single-bank or dual-bank?
- [ ] Exact RCSP OTA opcodes + upgrade-file container layout for this device.
- [ ] Does handle `0x0011` (`c2e6fd03`) carry the OTA channel, or is OTA on the
      same `FD02`/`FD01` pair used for other RCSP commands?
- [ ] Can the current firmware be *read out* over RCSP (for a recovery image)?
- [ ] DFU-mode BLE address behaviour on this badge (does it re-advertise, and as
      what?).
