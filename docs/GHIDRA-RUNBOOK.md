# Ghidra runbook

Use this only on software you are authorized to inspect. It documents interfaces; it is not an authorization-bypass guide.

## Import

1. Create a new non-shared Ghidra project.
2. Copy the target native library into a private analysis directory; never commit it.
3. Import it, selecting `AARCH64:LE:64:v8A` if Ghidra does not detect the language.
4. Run default Auto Analysis and wait for completion.
5. Record library hash and Ghidra version privately.

## First pass

- Start at exported JNI symbols and `JNI_OnLoad`.
- Search for QR, OTA, UFW, Qix, BLE, version, and result strings.
- Follow Java-native registration plus file/transport cross-references.
- Rename only evidence-backed functions; prefix hypotheses with `suspected_`.
- Keep a private table of function, inputs, outputs, side effects, and confidence.

## REST bridge

A local Ghidra REST bridge should be read-only: inventory, symbol lookup, function lists, decompilation retrieval, and cross-references. Publish conclusions and pseudocode-level descriptions only—never the proprietary library.

## Questions worth answering

- Is validation in Java, native code, or the device?
- Is a package treated as a blob or unpacked locally?
- Which fields influence target selection?
- What result proves a rebooted application rather than completed upload?

Label every answer observed or inferred. A client-side check does not prove an equivalent device-side check.
