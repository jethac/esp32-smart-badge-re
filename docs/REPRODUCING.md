# Safe reproduction checklist

## Before a write-capable experiment

1. Keep one badge untouched as a control.
2. Use a private alias, not an address or QR payload, to identify a test unit.
3. Record initial screen, battery, charge state, and button behavior.
4. Use a sacrificial unit for any package handoff.
5. Verify the exact candidate hash in private records before transfer.

## During

- Begin with discovery and read-only GATT inventory.
- Use synthetic fixtures before physical hardware.
- Observe transfer, reboot, advertising, screen, and reconnect separately.
- Stop at unexpected display corruption.

## Afterward

Preserve private logs/binaries with access control. Publish only sanitized conclusions, schemas, and procedures. No public artifact here should be sufficient to reflash a badge.
