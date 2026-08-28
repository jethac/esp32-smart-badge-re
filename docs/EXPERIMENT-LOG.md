# Sanitized experiment log

## Initial observation

- **Observed:** stock receive mode displayed an E87 QR identity screen and a Bluetooth address.
- **Observed:** an OTA-style package parsed into a small wrapper and UFW payload.

## Readback attempt

- **Observed:** authenticated browse/file-command probing did not yield a firmware image.
- **Conclusion:** no original backup exists; preserve an untouched control unit.

## Transition-package handoff

- **Observed:** a stock transition package reached a transport-complete state.
- **Not observed:** a reliable healthy post-update heartbeat.
- **Rule:** transfer completion is not boot success.

## Display anomaly

- **Observed:** later testing coincided with corrupt text and drawer graphics on one unit.
- **Unknown:** target mismatch, firmware, panel setup, or another state may be responsible.
- **Action:** stop treating that unit as a baseline.

## Replacement design work

- **Designed:** local 360x360 RGB565 rings and an eight-byte phone-to-badge state packet.
- **Assembled privately:** a native candidate for a sacrificial-device test.
- **Not claimed:** validated installation, boot, recovery, or cross-device compatibility.
