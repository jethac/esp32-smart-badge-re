# OTA packaging and transport

## Qix wrapper

**Observed from parsed samples.** A Qix container has a 27-byte wrapper followed by a UFW payload:

| Offset | Size | Meaning |
| --- | ---: | --- |
| 0 | 2 | Magic `BC AF` |
| 2 | 1 | Type (`01` in examined samples) |
| 3 | 10 | ASCII version, NUL padded |
| 13 | 4 | Little-endian payload length |
| 17 | 8 | Zero/reserved bytes in examined samples |
| 25 | 2 | CRC-16/CCITT-FALSE of the UFW payload |
| 27 | remainder | UFW payload |

This describes the outer wrapper only. It does not establish acceptance criteria, signature coverage, target selection, or bootloader behavior.

## Why transfer is not success

There are at least four independent checkpoints: discovery/connection, transfer, bootloader acceptance, and a healthy resulting application. Only the first two have partial evidence here.

## Artifact discipline

- Build with a pinned toolchain in a private, disposable workspace.
- Record source revision, configuration, tool version, semantic layout, and SHA-256 for the exact candidate.
- Never infer authorization from a merely similar-looking package.
- Keep all UFW/Qix files out of this public repository.

## Custom maintenance protocol (design only)

The proposed custom firmware would expose a normal encrypted GATT service and a maintenance channel. `AE00` carries build/device information, `AE01` is an update request/data family, and `AE02` returns a result/status family. Maintenance authorization should be short-lived and bound to the target and an epoch; that is an implementation requirement, not a demonstrated hardware capability.
