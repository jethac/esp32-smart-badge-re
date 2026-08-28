# Scope and publication rules

This repository records conclusions, interfaces, and failed/partial experiments. It is intentionally not a redistribution point for vendor material or an operational firmware-delivery toolkit.

## Included

- Observed UI states and their limits.
- Independently described container structure and protocol vocabulary.
- A replacement-firmware architecture and non-sensitive wire-format proposal.
- Repeatable analysis and experiment procedures.
- Clear separation of observation, inference, and design intent.

## Excluded

- Vendor SDKs, firmware images, OTA containers, native libraries, and APKs.
- BLE captures, QR payloads, MAC addresses, phone serials, local paths, or account data.
- Signing keys, credentials, tokens, authorization material, and device-specific values.
- Payloads or scripts intended to bypass authorization, integrity checks, or recovery controls.

## Evidence labels

- **Observed**: directly seen or mechanically parsed during this investigation.
- **Inferred**: the best explanation from available evidence; it may be wrong.
- **Design**: a proposed implementation, not a hardware-proven capability.

The product label is ambiguous. Early research suggested AC697/BR30-family hardware; later reference-package evidence suggested AC707N/BR35 and an `E87-JD9855-R1`-like target. Neither identifies every physical badge sold as E87. Confirm the board and untouched stock image before generalizing.
