# Research record

## What the hardware showed

**Observed.** Stock receive mode displayed a QR screen, the label `E87`, and a Bluetooth address. That confirms a vendor provisioning/update UI, not the processor family or firmware revision.

**Inferred.** The E87 product name covers more than one hardware/software combination. Early stock research pointed at AC697/BR30 model 1542; later package metadata pointed at AC707N/BR35 and an `E87-JD9855-R1`-like model 1552. Do not select a payload from the label alone.

## Readback result

An authenticated file-command/browse investigation did not retrieve firmware or flash. There is no original-firmware backup from this work. Operationally, this investigation must be treated as write-only until a separate, repeatable readback method is demonstrated.

## Two distinct update concepts

1. **Stock transition OTA**: a vendor-style Qix/UFW package handed off through the stock app/update path.
2. **Custom maintenance protocol**: a later proposed RCSP-style service with request families `AE00`, `AE01`, and `AE02` for discovery, update, and result reporting.

They are related only at a high level. The custom maintenance path is a design target; it was not shown to be a compatibility replacement for the stock OTA route.

## What did and did not happen

- A stock transition package completed its transport handoff, but a later healthy application heartbeat was not confirmed. A completed transfer is not evidence of a successful boot.
- A subsequent badge showed corrupt text and drawer graphics after historical experimentation. Causality remains unknown: package, target mismatch, display state, or another condition could explain it.
- A native replacement image was assembled locally for a sacrificial-device test. It is neither published nor represented as booted.

## Packaging reproducibility finding

Official-tool outputs changed a 144-byte `blimit.bin` across runs, including dependent header/table/entry CRC fields. Raw UFW/Qix byte identity therefore cannot be assumed across independent builds. Keep a pinned toolchain and compare semantic package fields; only a recorded exact artifact hash authorizes a particular transfer.
