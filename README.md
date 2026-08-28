# E87 Smart Badge: reverse-engineering notes

Public, documentation-first notes from an investigation of an inexpensive round Bluetooth smart badge sold as **E87**. This is not a firmware release and does not contain vendor firmware, SDKs, captures, application packages, device identifiers, or credentials.

The practical result so far is a map of a write-oriented update path and a deliberately small replacement-firmware design. A safe recovery/readback path and a verified custom boot remain unproven.

## Status

| Area | Current evidence |
| --- | --- |
| Stock receive mode | Confirmed visually: QR screen identifies as E87 and shows a device address. |
| Stock update wrapper | Parsed and documented. |
| Firmware readback | Not achieved. Treat the device as write-only for this work. |
| Stock update transport | A handoff completed at transport level; a successful resulting boot was not established. |
| Custom firmware | Designed and built locally for a sacrificial-device experiment; not distributed or claimed working. |
| Android maintenance client | Protocol/design work exists, but the complete reconnect, update, and verification loop is unfinished. |

## Read in this order

1. [Project scope and publication rules](docs/PROJECT-SCOPE.md)
2. [Research record](docs/RESEARCH.md)
3. [OTA packaging and transport](docs/OTA-AND-PACKAGING.md)
4. [Minimal firmware design](docs/FIRMWARE-DESIGN.md)
5. [Ghidra runbook](docs/GHIDRA-RUNBOOK.md)
6. [Experiment log](docs/EXPERIMENT-LOG.md)
7. [Known unknowns](docs/KNOWN-UNKNOWNS.md)
8. [Safe reproduction checklist](docs/REPRODUCING.md)

## Safety posture

Use an expendable unit. Preserve at least one untouched unit. Do not assume a package that transfers can boot, and do not assume a device with a QR receive screen can recover firmware. These notes intentionally stop short of shipping a flashable payload or automation.

## License

Documentation is licensed under [CC BY 4.0](LICENSE).
