# Ghidra ARM64 runbook: ZRun RCSP-authentication library

This runbook is for static analysis of the Android ARM64 authentication library
used by ZRun. It is separate from badge-firmware analysis and does not
authorize contact with a badge, phone, OTA service, or firmware image.

## Scope and integrity gate

Analyze this exact input:

```text
C:\Users\jetha\AppData\Local\Temp\e87-zrun-analysis\extracted\lib\arm64-v8a\libjl_ota_auth.so
```

Required SHA-256:

```text
D65DD43FB8EB284B93FCBD85C7CE4E59168F3673E28C7637ED467667E4CC5C4B
```

Verify it before import:

```powershell
$target = 'C:\Users\jetha\AppData\Local\Temp\e87-zrun-analysis\extracted\lib\arm64-v8a\libjl_ota_auth.so'
Get-Item -LiteralPath $target | Select-Object FullName, Length, LastWriteTime
(Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash
```

Stop on a mismatch. This file is an ELF64, little-endian AArch64 shared object,
not the badge application. The archived reference copy at
`C:\Users\jetha\Downloads\e87-reversing\android-reference\libjl_ota_auth.so`
was verified byte-identical during the 2026-08-28 preflight, but the target hash
above remains the import gate.

## Import the Android ELF

Launch the local Ghidra 11.3.2 installation:

```text
C:\ghidra\ghidra_11.3.2_PUBLIC\ghidraRun.bat
```

Create a new, non-shared, disposable project. Use **File > Import File**, select
the target, and retain the detected **ELF** loader. Confirm:

| Setting | Value |
|---|---|
| Language | `AARCH64:LE:64:v8A` |
| Compiler specification | `default` |
| Image base | `0x00100000` |

Do not use **Raw Binary**, `pi32v2:LE:32:default`, or the JieLi processor
module for this file. Those are for an extracted, plaintext badge `app.bin`;
they are wrong for this Android ELF shared object.

After import, select **Analysis > Auto Analyze** and retain Ghidra's selected
defaults. The historic project did not preserve a reliable analyzer-by-analyzer
checklist, so do not invent one or claim that a special set was used. Wait for
analysis to finish and confirm functions exist at the addresses below before
annotation.

## Apply the hash-locked annotations

The canonical script tracked in this repository is:

```text
analysis\ghidra-scripts\AnnotateJlOtaAuth.java
```

Its source SHA-256 is:

```text
DFA250D0F4CF0A62E1C44C8F21856C2E82214EB39C7DC4976654D8DB4C2B77CA
```

Verify a Windows copy before adding its directory to Script Manager:

```powershell
$script = 'C:\path\to\factory-android-badges\analysis\ghidra-scripts\AnnotateJlOtaAuth.java'
(Get-FileHash -Algorithm SHA256 -LiteralPath $script).Hash
```

With `libjl_ota_auth.so` open in CodeBrowser, open **Window > Script Manager**,
add or refresh the script directory, find `AnnotateJlOtaAuth`, and run it. The
script calls `getExecutableSHA256()` itself and refuses an unexpected program;
a mismatch cannot fall through to annotation.

The script changes names, comments, labels, and bookmarks in the Ghidra project
database only. It does not patch the input ELF. Use a disposable project if
those project edits are unwanted.

## High-value review anchors

Addresses are Ghidra addresses at image base `0x00100000`.

| Address | Name | Review purpose |
|---:|---|---|
| `00102264` | `JNI_OnLoad` | JNI entry; registers native methods. |
| `00102378` | `register_RcspAuth_natives` | Finds `RcspAuth` and registers four natives. |
| `001023DC` | `jni_RcspAuth_nativeInit` | Initializes JNI/auth state. |
| `00102488` | `jni_RcspAuth_getRandomAuthData` | Produces `00 || 16 random bytes`. |
| `00102594` | `jni_RcspAuth_setLinkKey` | Installs a 16-byte link key. |
| `00102638` | `jni_RcspAuth_getEncryptedAuthData` | Produces `01 || 16-byte` E1 response. |
| `00102748` | JNI firmware metadata filter | Calls `parse_fw_info`; not an OTA-payload decoder. |
| `00100D4C` | `rcsp_auth_e1_response_thunk` | Branch thunk for the response core. |
| `00100D50` | `rcsp_auth_e1_response` | Proprietary mutual-authentication response core. |
| `001012B8` | `auth_expand_key_272` | Expands a 16-byte key into a 272-byte schedule. |
| `00101438` | `auth_block_cipher_16` | One 16-byte block transform. |
| `00105008` | `RcspAuth_JNINativeMethods` | Four AArch64 `JNINativeMethod` entries. |
| `00105068` | `g_rcsp_link_key` | Default 16-byte key storage. |
| `00105078` | `g_rcsp_magic6` | Six-byte E1 constant. |

Useful exported ELF anchors include `function_E1test`, `function_E21`,
`function_xiaomi`, `CRC16`, `cd03_crc_encode`, `decrypt`,
`parse_fw_info`, `JNI_OnLoad`, and `register_xm_bluetooth`. This library
implements BLE mutual authentication; it is not evidence that it decrypts or
unpacks the firmware streamed by a ZRun/Qix updater.

## Export decompiler and function listings

Existing read-only helpers live at `B:\esp32\analysis\ghidra-scripts`.
This repository tracks the hash-locked annotation script above; do not copy the
full helper set into a new project. The useful read-only scripts are:


| Script | Use |
|---|---|
| `DecompileAddresses.java` | Prints C-like decompiler output for supplied addresses. |
| `DumpFunctionInstructions.java` | Prints the containing function's disassembly. |
| `DumpInstructionRange.java` | Prints a selected instruction range. |
| `XrefsToAddresses.java` / `SearchAddressRefs.java` | Prints reference evidence. |
| `FindDecompilerText.java` | Searches decompiled functions for supplied text. |

In Script Manager, pass space-separated hexadecimal arguments without a `0x`
prefix, for example:

```text
00102264 00102378 001023DC 00102488 00102594 00102638 00102748 00100D50 001012B8 00101438
```

Use those arguments with `DecompileAddresses` to export decompiler text, then
with `DumpFunctionInstructions` to export disassembly. Copy Script
Manager/console output into a dated text artifact. Do not use
`CreateE87Functions.java`; it changes the project. `LinearSearchImmediates.java`
is read-only only if its optional third `linear` argument is omitted.

## Optional REST/MCP access: strict safety boundary

The local GhidraMCP extension is an embedded HTTP server, not a read-only
service. Its inspected implementation is wildcard-bound, unauthenticated, and
mutation-capable. It selects the first available port from `8080` through
`8119`. Do not expose it to a LAN or use it with a valuable project.

If a future user deliberately enables it, use a disposable project plus network
isolation/firewalling first. Discover the actual listener, then make
localhost-only (`127.0.0.1`) calls:

```powershell
$listeners = Get-NetTCPConnection -State Listen |
  Where-Object { $_.LocalPort -ge 8080 -and $_.LocalPort -le 8119 } |
  Select-Object LocalAddress, LocalPort, OwningProcess

$health = foreach ($listener in $listeners) {
  $candidate = "http://127.0.0.1:$($listener.LocalPort)"
  try {
    [pscustomobject]@{ Base = $candidate; Health = Invoke-RestMethod "$candidate/health" -ErrorAction Stop }
  } catch {}
}
$health

# Copy Base from the confirmed /health result.
$base = 'http://127.0.0.1:<confirmed-port>'
```

The endpoint whitelist is exactly:

```powershell
Invoke-WebRequest "$base/health"
Invoke-WebRequest "$base/list_functions?offset=0&limit=1000" -OutFile functions.json
Invoke-WebRequest "$base/strings?offset=0&limit=1000&filter=RcspAuth" -OutFile strings.json
Invoke-WebRequest "$base/decompile_function?address=00102638&timeout=120" -OutFile jni-auth.c
Invoke-WebRequest "$base/disassemble_function?address=00102638" -OutFile jni-auth.asm
```

Never call mutation endpoints, including any `/rename*`, `/set_*`,
`/renameData`, or `/renameVariable` route. The implementation provides no
authentication, loopback-only binding, or reliable HTTP-method barrier that
makes those routes harmless.

## Evidence sources

- `C:\Users\jetha\Downloads\e87-reversing\GHIDRA-GUIDE.md`
- `C:\Users\jetha\Downloads\e87-reversing\tools\ghidra-scripts\AnnotateJlOtaAuth.java`
- `B:\esp32\.tmp-ghidra-cfr\com\lauriewired\GhidraMCPPlugin.java`
