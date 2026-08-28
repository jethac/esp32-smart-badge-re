#!/usr/bin/env python3
"""Offline target-command and package-policy tests for Stage 0-H S0-1."""
from __future__ import annotations

import hashlib
import importlib.util
import inspect
import argparse
import json
import os
import re
import resource
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_TOOL = ROOT / "firmware/tools/package-firmware.py"
BUILD_TOOL = ROOT / "firmware/tools/build-target.py"
VALIDATOR_TOOL = ROOT / "firmware/tools/validate-stage0.py"
REFERENCE_ROOT = Path(os.environ.get("E87_MODEL1552_REFERENCE_ROOT", "/home/jethac/.local/share/e87-dev/references/model1552-e87-11.1.0.2"))
SDK_ROOT = Path("/home/jethac/.local/share/e87-dev/sdk/e_badge_707_sdk_200")
POST_ROOT = Path("/home/jethac/.local/share/e87-dev/jieli-post-build")
ISD_ARGUMENTS = ["-tonorflash", "-dev", "br35", "-boot", "0x102600", "-div8", "-wait", "300", "-uboot", "uboot.boot", "-app", "app.bin", "-res", "cfg_tool.bin", "p11_code.bin", "stream.bin", "config.dat", "-flash-params", "flash_params_v3.bin", "-output-fw", "jl_isd.fw", "-output-ufw", "update.ufw"]
SECTIONS = [(".text", "text.bin"), (".data", "data.bin"), (".data_code", "data_code.bin"), (".overlay_aec", "aec.bin"), (".overlay_aac", "aac.bin"), (".ps_ram_data_code", "psr_data_code.bin"), (".dcache_ram_data", "d_ram_data.bin"), (".icache_ram_data_code", "i_ram_data_code.bin")]
STAGING_NAMES = {"app.bin", "uboot.boot", "cfg_tool.bin", "config.dat", "p11_code.bin", "stream.bin", "flash_params_v3.bin", "isd_config.ini", "ota.bin", "br35loader.bin"}
SOURCE_DATE_EPOCH = 1700000000
SOURCE_TREE = "2" * 40
SOURCE_COMMIT_BODY = (
    f"tree {SOURCE_TREE}\n".encode("ascii") +
    b"author Stage0 Test <stage0@example.invalid> 1700000000 +0000\n"
    b"committer Stage0 Test <stage0@example.invalid> 1700000000 +0000\n"
    b"\nSynthetic Stage0 source\n"
)
SOURCE_COMMIT = hashlib.sha1(b"commit " + str(len(SOURCE_COMMIT_BODY)).encode("ascii") + b"\0" + SOURCE_COMMIT_BODY).hexdigest()
SOURCE_COMMIT_OBJECT_SHA256 = hashlib.sha256(SOURCE_COMMIT_BODY).hexdigest().upper()
ALTERNATE_SOURCE_DATE_EPOCH = 1800000123
ALTERNATE_SOURCE_COMMIT_BODY = SOURCE_COMMIT_BODY.replace(b"1700000000", str(ALTERNATE_SOURCE_DATE_EPOCH).encode("ascii")).replace(b"Synthetic Stage0 source", b"Alternate Stage0 source")
ALTERNATE_SOURCE_COMMIT = hashlib.sha1(b"commit " + str(len(ALTERNATE_SOURCE_COMMIT_BODY)).encode("ascii") + b"\0" + ALTERNATE_SOURCE_COMMIT_BODY).hexdigest()
ALTERNATE_SOURCE_COMMIT_OBJECT_SHA256 = hashlib.sha256(ALTERNATE_SOURCE_COMMIT_BODY).hexdigest().upper()
TOOLCHAIN_ROOT = Path("/home/jethac/.local/share/e87-dev/jieli")
GOLDEN_UFW_SHA256 = "ECDFAA06377A00056ADB15D3486A4B059ACDE762C0F4A2BC8DCE43E0D120A80B"
PACKAGE_LOCK_SHA256 = "28E6C1DEF70F894F89FDC7FFB8527F204688888C58EEDC052CD8A36F3AEBC003"
MODEL_LOCK_SHA256 = "EFD3878979F029C56DA16E863EB89955E22D9B222046211A84AAC7BE1F3BA122"
TOOLCHAIN_LOCK_SHA256 = "60D72D942FC66E89303FD059AC9904F9167AAB743A21E78AB7230AA6B5B2300D"
OBJECTS = [
    "objs/apps/watch/e87/e87_stage0_adv.c.o",
    "objs/apps/watch/e87/e87_stage0_app.c.o",
    "objs/apps/watch/e87/e87_stage0_ble.c.o",
    "objs/apps/watch/board/br35/board_e87_1542/board_e87_1542.c.o",
]
COMPILE_MAKEFILE = (
    "export CFLAGS := \\\n"
    "\t-target pi32v2 \\\n"
    "\t-mcpu=r3 \\\n"
    "\t-integrated-as \\\n"
    "\t-flto \\\n"
).encode("ascii")
LINK_MAKEFILE = (
    "# link flags\n"
    "LFLAGS := \\\n"
    "\t--plugin-opt=-pi32v2-enable-simd=true \\\n"
    "\t--plugin-opt=mcpu=r3 \\\n"
    "\tcpu/br35/liba/libc.a \\\n"
    "\t-Tcpu/br35/sdk.ld \\\n"
    "\t-M=cpu/br35/tools/sdk.map \\\n"
    "\t--plugin-opt=mcpu=r3 \\\n"
    "\t--plugin-opt=-mattr=+fprev1 \\\n"
    "\n$(OUT_ELF): $(OBJS)\n"
    "\t$(LD) -o $(OUT_ELF) @$(OBJ_FILE) $(LFLAGS) $(LIBPATHS) $(LIBS)\n"
    "\n%.c.o: %.c\n"
    "\t$(CC) $(CFLAGS) $(INCLUDES) -c $< -o $@\n"
).encode("ascii")
MAKE_TOOL = {"path": "/usr/bin/make", "sha256": "92F646030615CD98490A68A94C0AEFD87B552BE3158B941C02E43B0BFDB576DB", "version": "4.3"}
GIT_TOOL = {"path": "/usr/bin/git", "sha256": "587EF21868C948B883993E23209B86A72A6DDC06AAB1545C697FFC31075ACD4A", "version": "2.34.1"}
CONTROLLED_BUILD_PATH = f"{TOOLCHAIN_ROOT}/pi32v2/bin:{POST_ROOT}:/usr/bin:/bin"
LTO_HOST_TOOLS = {
    "env": {"path": "/usr/bin/env", "sha256": "85036540673319C6C2F54233FD2B9E45A8A71246B51CC96C4E6AB8EE6C419EB0", "version": "8.32"},
    "python3": {"path": "/usr/bin/python3", "resolvedPath": "/usr/bin/python3.10", "sha256": "7D51CD6B48B521277F5CAA4610A82126E315FA2BE4DF069823A8B1EEB5BD4A86", "symlinkTarget": "python3.10", "version": "3.10.12"},
}
LTO_TOOLS = {
    "ar": {"byteLength": 744888, "installRelativePath": "pi32v2/bin/ar", "mode": "0755", "sha256": "CAD18239D47EE1439DBE1D2C2892D4C4BDB868BEF68F08242766DF7AE333A84C"},
    "linkVersion": {"byteLength": 2121360, "installRelativePath": "pi32v2/bin/link-version", "mode": "0755", "resolvedInstallRelativePath": "common/bin/link-version", "sha256": "3129FCC8FCCD70F7B229026CB9ACB324A616F5D19953E5ED5D14BEF35BF81D56", "symlinkTarget": "../../common/bin/link-version"},
    "llvmGold": {"byteLength": 17646856, "installRelativePath": "pi32v2/bin/LLVMgold.so", "mode": "0755", "resolvedInstallRelativePath": "common/bin/LLVMgold.so", "sha256": "B91F4509C885DB84B0FA09C06C6E43F773DB9E47593C86FCF92BDFB65CEF2120", "symlinkTarget": "../../common/bin/LLVMgold.so"},
    "ltoAr": {"byteLength": 524, "installRelativePath": "pi32v2/bin/lto-ar", "mode": "0755", "resolvedInstallRelativePath": "common/bin/lto-ar", "sha256": "4F8470410C9DFF9059FF595A2206257EAE505D9FE4C7EE5926C3119262E99E68", "symlinkTarget": "../../common/bin/lto-ar"},
    "ltoWrapper": {"byteLength": 2097, "installRelativePath": "pi32v2/bin/lto-wrapper", "mode": "0775", "resolvedInstallRelativePath": "common/bin/lto-wrapper", "sha256": "777F7A173E9E1B801C73945DE3D5888708F278E7B5242AFE8B277ABE1761BC0E", "symlinkTarget": "../../common/bin/lto-wrapper"},
}
LD_TOOL = {"installRelativePath": "pi32v2/bin/ld", "sha256": "FD61AFF15616BB6F6B58FD2E9EDE7AF741C7BF05FACB3E0CB3D3C9817C268FD9"}
RUNTIME_TOOLS = {**LTO_TOOLS, "ld": LD_TOOL}
ELF_INTERPRETER = {"path": "/lib64/ld-linux-x86-64.so.2", "sha256": "8D06F393F4A93BCF9B81145A259524D66A95522A646BF8D7E05B6FFDF2E63DCC"}
PRIMARY_BUILD_TOOLS = {"clang", "ld", "nm", "objcopy", "objdump", "objsizedump", "strip"}
SDK_COMMIT = "d0167685d032d745d88fe50233302edd46941622"
SDK_TREE = "854734595be49510aca5afb89f5885e8bce6a00f"
GIT_CONFIG_PREFIX = ("-c", "core.fsmonitor=false", "-c", "core.attributesFile=/dev/null", "-c", "tar.umask=0002")
BOOTSTRAP_COMMAND_ROLES = (
    "git-version",
    "source-before-head", "source-before-tree", "source-before-status", "source-before-index", "source-before-head-index-diff", "source-before-worktree-index-diff", "source-before-commit-object",
    "sdk-before-head", "sdk-before-tree", "sdk-before-status", "sdk-before-index", "sdk-before-head-index-diff", "sdk-before-worktree-index-diff",
    "sdk-archive", "sdk-archive-confirm", "patch-check", "patch-apply",
    "source-after-head", "source-after-tree", "source-after-status", "source-after-index", "source-after-head-index-diff", "source-after-worktree-index-diff", "source-after-commit-object",
    "sdk-after-head", "sdk-after-tree", "sdk-after-status", "sdk-after-index", "sdk-after-head-index-diff", "sdk-after-worktree-index-diff",
)
BOOTSTRAP_VALIDATIONS = {name: True for name in (
    "archiveInventory", "gitToolIdentity", "outputRoot", "outputTree", "overlayInputs", "patchContract", "protectedRoots",
    "sdkClean", "sdkIdentity", "sdkStable", "sourceClean", "sourceIdentity", "sourceStable",
)}
BUILD_TOOL_VERSION_STDOUT = {
    "make": b"GNU Make 4.3\n",
    "nm": b"GNU nm (GNU Binutils) 2.26.51.20160621\n",
    "objcopy": b"LLVM (http://llvm.org/):\n  LLVM version 4.0.1\n",
    "objdump": b"LLVM (http://llvm.org/):\n  LLVM version 4.0.1\n",
}
BUILD_TOOL_VERSIONS = {
    "make": "GNU Make 4.3",
    "nm": "GNU Binutils 2.26.51.20160621",
    "objcopy": "LLVM 4.0.1",
    "objdump": "LLVM 4.0.1",
}
BUILD_VALIDATIONS = {name: True for name in (
    "appConcatenation", "bootstrapReplay", "buildEnvironment", "buildInputsStable",
    "elfLayout", "mapProvenance", "nofileLimit", "objectInventory", "outputAllowlist",
    "runtimeIdentity", "sectionExtraction", "sourceSelection", "toolIdentity",
)}
BUILD_RESOURCE_LIMITS = {"nofileSoft": 8192}


def normalized_build_environment(source_date_epoch: int = SOURCE_DATE_EPOCH) -> dict[str, str]:
    return {
        "HOME": "$BUILD_CONTROL_ROOT/home",
        "TMPDIR": "$BUILD_CONTROL_ROOT/tmp",
        "LANG": "C",
        "LC_ALL": "C",
        "TZ": "UTC",
        "SOURCE_DATE_EPOCH": str(source_date_epoch),
        "PATH": CONTROLLED_BUILD_PATH,
    }


def build_raw_record(
    record: dict[str, object],
    result: subprocess.CompletedProcess,
    *,
    source_date_epoch: int = SOURCE_DATE_EPOCH,
) -> dict[str, object]:
    return {
        **record,
        "cwd": "$BUILD_ROOT",
        "environment": normalized_build_environment(source_date_epoch),
        "stderrHex": result.stderr.hex().upper(),
        "stderrSize": len(result.stderr),
        "stdoutHex": result.stdout.hex().upper(),
        "stdoutSize": len(result.stdout),
    }


def expected_lto_runtime() -> dict[str, object]:
    tools = {}
    for name in sorted(RUNTIME_TOOLS):
        pin = RUNTIME_TOOLS[name]
        resolved_relative = pin.get("resolvedInstallRelativePath", pin["installRelativePath"])
        tools[name] = {
            **pin,
            "invocationPath": str(TOOLCHAIN_ROOT / pin["installRelativePath"]),
            "resolvedPath": str(TOOLCHAIN_ROOT / resolved_relative),
        }
    return {
        "controlledPath": CONTROLLED_BUILD_PATH,
        "elfInterpreter": ELF_INTERPRETER,
        "hostTools": LTO_HOST_TOOLS,
        "tools": tools,
    }


def expected_runtime_receipt() -> dict[str, object]:
    return {
        "schema": "e87-stage0-build-runtime-v1",
        "toolchainLockSha256": TOOLCHAIN_LOCK_SHA256,
        **expected_lto_runtime(),
    }
BOOTSTRAP_OVERLAYS = (
    "SDK/apps/watch/include/e87/e87_stage0_adv.h",
    "SDK/apps/watch/include/e87/e87_stage0_app.h",
    "SDK/apps/watch/e87/e87_stage0_adv.c",
    "SDK/apps/watch/e87/e87_stage0_app.c",
    "SDK/apps/watch/e87/e87_stage0_ble.c",
    "SDK/apps/watch/board/br35/board_e87_1542/board_e87_1542.c",
    "SDK/apps/watch/board/br35/board_e87_1542/board_e87_1542_cfg.h",
)
BOOTSTRAP_PATCH_TARGETS = (
    "SDK/apps/watch/app_main.c",
    "SDK/apps/watch/board/br35/board_config.h",
    "SDK/apps/watch/include/app_config.h",
    "SDK/build/Makefile.mk",
    "SDK/build/genFileList.c",
)
BOOTSTRAP_OVERLAY_RECORDS = tuple(
    {"destination": relative, "source": "firmware/overlay/" + relative}
    for relative in BOOTSTRAP_OVERLAYS
)
BOOTSTRAP_PATCH_PATH = ROOT / "firmware/patches/stage0/0001-e87-stage0-hooks.patch"
def load_tool(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module)
    return module


def require_api(test: unittest.TestCase, module, name: str):
    value = getattr(module, name, None)
    test.assertTrue(callable(value), f"required production API is missing: {module.__name__}.{name}")
    return value


def call_contract(test: unittest.TestCase, label: str, function, /, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except TypeError as error:
        test.fail(f"{label} production contract is missing or obsolete: {error}")


def independent_tree_sha256(root: Path) -> str:
    digest = hashlib.sha256(); root = Path(root)
    for entry in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = entry.relative_to(root).as_posix().encode("utf-8")
        if entry.is_symlink(): raise AssertionError("fixture tree contains a symlink")
        if entry.is_dir(): digest.update(b"D\0" + relative + b"\0")
        elif entry.is_file():
            mode = b"100755" if entry.stat().st_mode & 0o111 else b"100644"
            digest.update(b"F\0" + relative + b"\0" + mode + b"\0" + hashlib.sha256(entry.read_bytes()).digest())
        else: raise AssertionError("fixture tree contains a special file")
    return digest.hexdigest().upper()


def synthetic_bootstrap_command_records(
    patch_record: dict[str, object],
    *,
    source_commit: str = SOURCE_COMMIT,
    source_tree: str = SOURCE_TREE,
    source_commit_body: bytes = SOURCE_COMMIT_BODY,
) -> list[dict[str, object]]:
    base_environment = {
        "GIT_ATTR_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0", "HOME": "/dev/null", "LANG": "C", "LC_ALL": "C", "TZ": "UTC", "XDG_CONFIG_HOME": "/dev/null",
    }

    def bound(root_token: str, *arguments: str) -> list[str]:
        return [GIT_TOOL["path"], *GIT_CONFIG_PREFIX, "--git-dir", f"{root_token}/.git", "--work-tree", root_token, *arguments]

    def checks(kind: str, phase: str) -> list[tuple[str, list[str], bytes]]:
        token = "${SOURCE_ROOT}" if kind == "source" else "${SDK_ROOT}"
        commit = source_commit if kind == "source" else SDK_COMMIT; tree = source_tree if kind == "source" else SDK_TREE
        values = [
            ("head", bound(token, "rev-parse", "HEAD"), (commit + "\n").encode("ascii")),
            ("tree", bound(token, "rev-parse", "HEAD^{tree}"), (tree + "\n").encode("ascii")),
            ("status", bound(token, "status", "--porcelain=v1", "--untracked-files=no"), b""),
            ("index", bound(token, "ls-files", "-v", "--stage", "-z", "--"), (f"synthetic-{kind}-index\0").encode("ascii")),
            ("head-index-diff", bound(token, "diff", "--no-ext-diff", "--no-textconv", "--exit-code", "--cached", "HEAD", "--"), b""),
            ("worktree-index-diff", bound(token, "diff", "--no-ext-diff", "--no-textconv", "--exit-code", "--"), b""),
        ]
        if kind == "source": values.append(("commit-object", bound(token, "cat-file", "commit", source_commit), source_commit_body))
        return [(f"{kind}-{phase}-{suffix}", argv, stdout) for suffix, argv, stdout in values]

    traced = [("git-version", [GIT_TOOL["path"], "--version"], b"git version 2.34.1\n", "source", None)]
    traced += [(role, argv, stdout, "source", None) for role, argv, stdout in checks("source", "before")]
    traced += [(role, argv, stdout, "sdk", None) for role, argv, stdout in checks("sdk", "before")]
    traced.append(("sdk-archive", bound("${SDK_ROOT}", "archive", "--format=tar", SDK_COMMIT), b"synthetic deterministic SDK archive\n", "sdk", None))
    traced.append(("sdk-archive-confirm", bound("${SDK_ROOT}", "archive", "--format=tar", SDK_COMMIT), b"synthetic deterministic SDK archive\n", "sdk", None))
    patch_stdin = {"sha256": patch_record["sha256"], "size": patch_record["size"]}
    apply_environment = {**base_environment, "GIT_CEILING_DIRECTORIES": "${OWNED_STAGING_ROOT}"}
    traced += [
        ("patch-check", [GIT_TOOL["path"], *GIT_CONFIG_PREFIX, "apply", "--no-index", "--check", "-"], b"", "${OWNED_STAGING_ROOT}", patch_stdin),
        ("patch-apply", [GIT_TOOL["path"], *GIT_CONFIG_PREFIX, "apply", "--no-index", "-"], b"", "${OWNED_STAGING_ROOT}", patch_stdin),
    ]
    traced += [(role, argv, stdout, "source", None) for role, argv, stdout in checks("source", "after")]
    traced += [(role, argv, stdout, "sdk", None) for role, argv, stdout in checks("sdk", "after")]
    if tuple(item[0] for item in traced) != BOOTSTRAP_COMMAND_ROLES: raise AssertionError("synthetic bootstrap command order drift")
    empty_sha = hashlib.sha256(b"").hexdigest().upper(); records = []
    for role, argv, stdout, cwd, stdin in traced:
        environment = apply_environment if role in {"patch-check", "patch-apply"} else base_environment
        records.append({
            "argv": argv, "cwd": cwd, "environment": environment, "exitCode": 0, "role": role,
            "stderrSha256": empty_sha, "stderrSize": 0, "stdin": stdin,
            "stdoutSha256": hashlib.sha256(stdout).hexdigest().upper(), "stdoutSize": len(stdout),
            "toolSha256": GIT_TOOL["sha256"], "toolVersion": GIT_TOOL["version"],
        })
    return records


def projection_sha256(value: object) -> str:
    data = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("ascii")
    return hashlib.sha256(data).hexdigest().upper()


def synthetic_bootstrap_replay_evidence(receipt: dict[str, object], receipt_bytes: bytes) -> dict[str, object]:
    validation = {
        "commandsSha256": projection_sha256(receipt["commands"]),
        "outputTreeSha256": receipt["outputTreeSha256"],
        "receiptSha256": hashlib.sha256(receipt_bytes).hexdigest().upper(),
        "schema": "e87-stage0-bootstrap-replay-validation-v1",
        "validationsSha256": projection_sha256(receipt["validations"]),
    }
    return {
        "commands": deepcopy(receipt["commands"]),
        "outputTreeSha256": receipt["outputTreeSha256"],
        "receiptSha256": validation["receiptSha256"],
        "schema": "e87-stage0-bootstrap-replay-evidence-v1",
        "validation": validation,
        "validations": deepcopy(receipt["validations"]),
    }


def synthetic_bootstrap_replay_validation(receipt: dict[str, object], receipt_bytes: bytes) -> dict[str, object]:
    """Cross-link even malformed receipt projections so schema failures are not hash failures."""
    return {
        "commandsSha256": projection_sha256(receipt.get("commands")),
        "outputTreeSha256": receipt.get("outputTreeSha256"),
        "receiptSha256": hashlib.sha256(receipt_bytes).hexdigest().upper(),
        "schema": "e87-stage0-bootstrap-replay-validation-v1",
        "validationsSha256": projection_sha256(receipt.get("validations")),
    }


def crc16_xmodem(data: bytes) -> int:
    state = 0
    for byte in data:
        state ^= byte << 8
        for _ in range(8):
            state = ((state << 1) ^ (0x1021 if state & 0x8000 else 0)) & 0xFFFF
    return state


def jl_cipher(data: bytes, key: int) -> bytes:
    output = bytearray(len(data)); state = key
    for index, byte in enumerate(data):
        output[index] = byte ^ (state & 0xFF)
        state = ((state << 1) ^ (0x1021 if state & 0x8000 else 0)) & 0xFFFF
    return bytes(output)


def sfc_transform(flash: bytes) -> bytes:
    output = bytearray(flash)
    for block in range(0x2000, len(flash), 32):
        key = (0x9847 ^ ((block - 0x2000) >> 2)) & 0xFFFF
        output[block:block + 32] = jl_cipher(flash[block:block + 32], key)
    return bytes(output)


def metadata_transform(data: bytes) -> bytes:
    return jl_cipher(data, 0xFFFF)


def member_transform(data: bytes, *, address: int, key: int = 0x9847) -> bytes:
    output = bytearray(data)
    for block in range(0, len(data), 0x20):
        state = (key ^ ((address + block) >> 2)) & 0xFFFF
        for index in range(block, min(block + 0x20, len(data))):
            output[index] ^= state & 0xFF
            state = ((state << 1) ^ (0x1021 if state & 0x8000 else 0)) & 0xFFFF
    return bytes(output)


def mutate_ufw_entry(payload: bytes, index: int, mutator) -> bytes:
    changed = bytearray(payload); start = 0x40 + index * 0x50
    decoded = bytearray(metadata_transform(changed[start:start + 0x50])); mutator(decoded)
    changed[start:start + 0x50] = metadata_transform(bytes(decoded))
    header = bytearray(metadata_transform(changed[:0x40])); count = int.from_bytes(header[8:10], "little")
    header[2:4] = crc16_xmodem(changed[0x40:0x40 + count * 0x50]).to_bytes(2, "little")
    header[:2] = crc16_xmodem(header[2:]).to_bytes(2, "little")
    changed[:0x40] = metadata_transform(bytes(header))
    return bytes(changed)


def _make_stage0_package_fixture(app_xor: int) -> dict[str, bytes]:
    """Build a valid non-vendor-app package proof fixture without native tools."""
    golden = (REFERENCE_ROOT / "container/payload.ufw").read_bytes()
    flash = golden[0x400:0xFB400]
    decoded = bytearray(sfc_transform(flash))
    decoded[0x2100] ^= app_xor
    app = bytes(decoded[0x2100:0xF5200])
    app_entry = bytearray(decoded[0x2020:0x2040])
    app_entry[2:4] = crc16_xmodem(app).to_bytes(2, "little")
    app_entry[:2] = crc16_xmodem(app_entry[2:]).to_bytes(2, "little")
    decoded[0x2020:0x2040] = app_entry
    app_head = bytearray(decoded[0x2000:0x2020])
    app_head[2:4] = crc16_xmodem(decoded[0x2020:0xF5200]).to_bytes(2, "little")
    app_head[:2] = crc16_xmodem(app_head[2:]).to_bytes(2, "little")
    decoded[0x2000:0x2020] = app_head
    flash = sfc_transform(bytes(decoded))
    changed = bytearray(golden); changed[0x400:0xFB400] = flash
    changed = bytearray(mutate_ufw_entry(bytes(changed), 0, lambda entry: entry.__setitem__(slice(4, 6), crc16_xmodem(flash).to_bytes(2, "little"))))
    jl_isd_fw = bytes(changed)

    ini_offset, ini_size, ini_allocated = 0xFBDC0, 0x679, 0x680
    ini = member_transform(changed[ini_offset:ini_offset + ini_allocated], address=ini_offset)
    old = b"RESET = PB07_08_0;"; new = b"RESET = PB07_00_0;"
    if ini[:ini_size].count(old) != 1 or len(old) != len(new):
        raise AssertionError("recovered INI fixture drift")
    ini = ini.replace(old, new, 1)
    changed[ini_offset:ini_offset + ini_allocated] = member_transform(ini, address=ini_offset)
    stage0_ufw = mutate_ufw_entry(bytes(changed), 4, lambda entry: entry.__setitem__(slice(4, 6), crc16_xmodem(ini[:ini_size]).to_bytes(2, "little")))
    return {
        "app.bin": app,
        "jl_isd.bin": flash,
        "jl_isd.fw": jl_isd_fw,
        "update.ufw": stage0_ufw,
        "independently-made.ufw": stage0_ufw,
    }


@lru_cache(maxsize=1)
def stage0_package_fixture() -> dict[str, bytes]:
    return _make_stage0_package_fixture(0x5A)


@lru_cache(maxsize=1)
def alternate_stage0_package_fixture() -> dict[str, bytes]:
    return _make_stage0_package_fixture(0xA5)


def make_elf32_fixture(section_bytes: dict[str, bytes] | None = None) -> tuple[bytes, list[dict[str, int | str]], dict[str, bytes]]:
    """Create a literal ELF32-LE ET_EXEC with one PT_LOAD per required section."""
    section_bytes = section_bytes or {name: bytes([index + 1]) * 0x10 for index, (name, _) in enumerate(SECTIONS)}
    if set(section_bytes) != {name for name, _ in SECTIONS} or any(not section_bytes[name] for name, _ in SECTIONS):
        raise AssertionError("ELF fixture requires exactly eight nonempty section payloads")
    names = b"\0"; name_offsets = {}
    for name, _ in SECTIONS:
        name_offsets[name] = len(names); names += name.encode("ascii") + b"\0"
    name_offsets[".shstrtab"] = len(names); names += b".shstrtab\0"
    phoff = 52; phentsize = 32; phnum = len(SECTIONS); data_start = 0x200
    loads = []; expected_sections = []; offset = data_start; vma = 0x0C000100
    for index, (name, _) in enumerate(SECTIONS):
        lma = vma
        data = section_bytes[name]
        flags = 5 if name == ".text" else 6
        loads.append(struct.pack("<IIIIIIII", 1, offset, vma, lma, len(data), len(data), flags, 1))
        expected_sections.append({"fileOffset": offset, "lma": lma, "name": name, "size": len(data), "vma": vma})
        offset += len(data); vma += len(data)
    image = bytearray(offset)
    for record in expected_sections:
        data = section_bytes[str(record["name"])]
        start = int(record["fileOffset"]); image[start:start + len(data)] = data
    image[phoff:phoff + phentsize * phnum] = b"".join(loads)
    shstr_offset = len(image); image.extend(names)
    while len(image) % 4: image.append(0)
    shoff = len(image); shentsize = 40; shnum = len(SECTIONS) + 2; shstrndx = shnum - 1
    image.extend(bytes(shentsize))
    for index, (name, _) in enumerate(SECTIONS):
        record = expected_sections[index]; flags = 0x6 if name == ".text" else 0x3
        image.extend(struct.pack("<IIIIIIIIII", name_offsets[name], 1, flags, int(record["vma"]), int(record["fileOffset"]), int(record["size"]), 0, 0, 1, 0))
    image.extend(struct.pack("<IIIIIIIIII", name_offsets[".shstrtab"], 3, 0, 0, shstr_offset, len(names), 0, 0, 1, 0))
    ident = b"\x7fELF" + bytes((1, 1, 1, 0, 0)) + bytes(7)
    header = struct.pack("<16sHHIIIIIHHHHHH", ident, 2, 0xF1, 1, 0x0C000100, phoff, shoff, 0, 52, phentsize, phnum, shentsize, shnum, shstrndx)
    image[:52] = header
    return bytes(image), expected_sections, section_bytes


def independent_elf32_load_end(image: bytes) -> int:
    """Return normalized max file-backed PT_LOAD LMA extent without production parsing."""
    if image[:7] != b"\x7fELF\x01\x01\x01": raise AssertionError("fixture is not ELF32 little-endian")
    phoff = int.from_bytes(image[28:32], "little"); phentsize = int.from_bytes(image[42:44], "little"); phnum = int.from_bytes(image[44:46], "little")
    extents = []
    for index in range(phnum):
        header = image[phoff + index * phentsize:phoff + (index + 1) * phentsize]
        p_type, _, _, p_paddr, p_filesz, _, _, _ = struct.unpack("<IIIIIIII", header)
        if p_type == 1 and p_filesz: extents.append(p_paddr + p_filesz)
    if not extents: raise AssertionError("fixture has no file-backed PT_LOAD")
    return max(extents) - 0x0C000000


def synthetic_objdump_stdout(section_bytes: dict[str, bytes], *, swap_final_offsets: bool = False) -> bytes:
    base_vma = 0x0C000100
    lines = ["sdk.elf: file format elf32-pi32v2", "architecture: pi32v2, flags 0x00000002: EXEC_P", f"start address 0x{base_vma:08x}", "Sections:", "Idx Name Size VMA LMA File off Algn"]
    offset = 0x200; vma = base_vma; rows = []
    for index, (name, _) in enumerate(SECTIONS):
        size = len(section_bytes[name]); rows.append([index, name, size, vma, vma, offset])
        offset += size; vma += size
    if swap_final_offsets: rows[-2][5], rows[-1][5] = rows[-1][5], rows[-2][5]
    lines += [f"{index:3d} {name:<24} {size:08x} {row_vma:08x} {lma:08x} {file_offset:08x} 2**0" for index, name, size, row_vma, lma, file_offset in rows]
    return ("\n".join(lines) + "\n").encode("ascii")


def deterministic_native_stream(label: str, size: int, multiplier: int) -> bytes:
    prefix = label.encode("ascii") + b"\x00\xff"
    if size <= len(prefix): raise AssertionError("native stream fixture size is too small")
    return prefix + bytes(((index * multiplier) + len(label)) & 0xFF for index in range(size - len(prefix)))


NATIVE_SUCCESS_STREAMS = {
    "isd_download": {
        "stdout": deterministic_native_stream("ISD-STDOUT", 4097, 17),
        "stderr": deterministic_native_stream("ISD-STDERR", 8193, 29),
    },
    "ufw_maker": {
        "stdout": deterministic_native_stream("UFW-STDOUT", 8193, 43),
        "stderr": deterministic_native_stream("UFW-STDERR", 4097, 61),
    },
}


class FakeNativeRunner:
    def __init__(self, mode="ok", fail_tool="isd_download", empty_output=None, artifacts=None, events=None, corrupt_output=None):
        self.mode = mode; self.fail_tool = fail_tool; self.empty_output = empty_output; self.artifacts = artifacts or {}; self.events = events; self.corrupt_output = corrupt_output; self.calls = []; self.results = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), dict(kwargs)))
        cwd = Path(kwargs["cwd"]); returncode = 0
        tool = Path(argv[0]).name
        stdout = NATIVE_SUCCESS_STREAMS[tool]["stdout"]
        stderr = NATIVE_SUCCESS_STREAMS[tool]["stderr"]
        if self.events is not None: self.events.append(f"runner:{tool}")
        failing = self.mode != "ok" and self.fail_tool == tool
        if tool == "isd_download":
            if failing and self.mode == "mutate-input": (cwd / "app.bin").write_bytes(b"mutated")
            for name in (() if failing and self.mode == "missing" else ("jl_isd.bin", "jl_isd.fw", "update.ufw")):
                value = self.artifacts.get(name, (name + "\n").encode("ascii"))
                (cwd / name).write_bytes(b"" if failing and self.mode == "empty" and self.empty_output == name else value)
            if failing and self.mode == "extra": (cwd / "surprise.bin").write_bytes(b"x")
            if failing and self.mode == "prompt": stdout = b"Connect USB device now?"
            if failing and self.mode == "stderr-prompt": stderr = b"Enumerating serial device"
            if failing and self.mode == "nonzero": returncode = 9
        elif tool == "ufw_maker":
            if failing and self.mode == "mutate-input": (cwd / "jl_isd.fw").write_bytes(b"mutated")
            if not (failing and self.mode == "missing"):
                value = self.artifacts.get("independently-made.ufw", (cwd / "update.ufw").read_bytes())
                (cwd / "independently-made.ufw").write_bytes(b"" if failing and self.mode == "empty" and self.empty_output == "independently-made.ufw" else value)
            if failing and self.mode == "extra": (cwd / "surprise.bin").write_bytes(b"x")
            if failing and self.mode == "prompt": stdout = b"Select a device?"
            if failing and self.mode == "stderr-prompt": stderr = b"Connect USB serial port"
            if failing and self.mode == "nonzero": returncode = 8
        corrupt_here = (tool == "isd_download" and self.corrupt_output in {"jl_isd.bin", "jl_isd.fw", "update.ufw"}) or (tool == "ufw_maker" and self.corrupt_output == "independently-made.ufw")
        if self.mode == "corrupt-output" and corrupt_here and (cwd / self.corrupt_output).exists():
            value = bytearray((cwd / self.corrupt_output).read_bytes()); corrupt_index = 0 if self.corrupt_output == "jl_isd.fw" else -1
            value[corrupt_index] ^= 1; (cwd / self.corrupt_output).write_bytes(value)
        result = subprocess.CompletedProcess(argv, returncode, stdout, stderr); self.results.append((tool, result)); return result


class FakeBuildRunner:
    def __init__(self, elf: bytes, section_bytes: dict[str, bytes], *, events=None, mode="ok", target_role=None, mutate_provenance=False):
        self.elf = elf; self.section_bytes = section_bytes; self.events = events; self.mode = mode; self.target_role = target_role; self.mutate_provenance = mutate_provenance; self.calls = []; self.results = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), dict(kwargs)))
        executable = Path(argv[0]).name
        role = executable
        if executable == "objcopy": role = f"objcopy:{argv[argv.index('-j') + 1]}"
        if self.events is not None: self.events.append(f"runner:{role}")
        if self.mode == "nonzero" and role == self.target_role:
            result = subprocess.CompletedProcess(argv, 23, b"failed\n", b"synthetic failure\n"); self.results.append((role, result)); return result
        if executable == "make":
            sdk = Path(argv[argv.index("-C") + 1])
            if self.mutate_provenance: (sdk / "build/Makefile.mk").write_bytes(LINK_MAKEFILE + b"LFLAGS += --plugin-opt=mcpu=r2\n")
            target = sdk / "cpu/br35/tools/sdk.elf"; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(self.elf)
            for index, relative in enumerate(OBJECTS):
                if self.mode == "missing-object" and index == len(OBJECTS) - 1: continue
                object_path = sdk / "build" / relative; object_path.parent.mkdir(parents=True, exist_ok=True)
                object_path.write_bytes(("object:" + relative + "\n").encode("ascii"))
            if self.mode == "extra-object":
                extra = sdk / "build/objs/apps/watch/e87/unreviewed.c.o"; extra.parent.mkdir(parents=True, exist_ok=True); extra.write_bytes(b"unreviewed object\n")
            map_path = sdk / "cpu/br35/tools/sdk.map"
            if self.mode != "missing-map":
                map_path.write_text(
                    ".text.bt_ble_init 0x0C000108 0x08 objs/apps/watch/e87/e87_stage0_ble.c.o\n                0x0C000108 bt_ble_init\n"
                    if self.mode == "map-drift"
                    else ".text.bt_ble_init 0x0C000100 0x10 objs/apps/watch/e87/e87_stage0_ble.c.o\n                0x0C000100 bt_ble_init\n",
                    encoding="ascii",
                )
            result = subprocess.CompletedProcess(argv, 0, b"linked\n", b"")
        elif executable == "objcopy":
            section = argv[argv.index("-j") + 1]
            if not (self.mode == "missing-section" and role == self.target_role):
                data = b"" if self.mode == "empty-section" and role == self.target_role else self.section_bytes[section]
                if self.mode == "wrong-section" and role == self.target_role:
                    data = bytes([data[0] ^ 0xFF]) + data[1:]
                Path(argv[-1]).write_bytes(data)
            if self.mode == "extra-section" and role == self.target_role: (Path(argv[-1]).parent / "unexpected.bin").write_bytes(b"extra")
            result = subprocess.CompletedProcess(argv, 0, b"", b"")
        elif executable == "objdump": result = subprocess.CompletedProcess(argv, 0, synthetic_objdump_stdout(self.section_bytes, swap_final_offsets=self.mode == "wrong-objdump"), b"")
        elif executable == "nm": result = subprocess.CompletedProcess(argv, 0, b"0C000108 T bt_ble_init\n" if self.mode == "wrong-nm" else b"0C000100 T bt_ble_init\n", b"")
        else: raise AssertionError(f"unexpected fake build command: {argv}")
        self.results.append((role, result)); return result


class FakeVersionRunner:
    def __init__(self, *, events=None, mode="ok", target_tool=None): self.events = events; self.mode = mode; self.target_tool = target_tool; self.calls = []; self.results = []

    def __call__(self, argv, **kwargs):
        command = list(argv); self.calls.append((command, dict(kwargs))); name = Path(command[0]).name
        if self.events is not None: self.events.append(f"version:{name}")
        if command != [command[0], "--version"] or name not in BUILD_TOOL_VERSION_STDOUT: raise AssertionError(f"unexpected version probe: {command}")
        stdout = BUILD_TOOL_VERSION_STDOUT[name]; stderr = b""; returncode = 0
        if name == self.target_tool and self.mode == "nonzero": returncode, stderr = 17, b"synthetic version failure\n"
        if name == self.target_tool and self.mode == "wrong": stdout = b"unrelated-tool 99.0\n"
        if name == self.target_tool and self.mode == "prompt": stdout += b"Select a device to continue?\n"
        if name == self.target_tool and self.mode == "stderr-prompt": stderr = b"Connect USB device now\n"
        result = subprocess.CompletedProcess(command, returncode, stdout, stderr); self.results.append((name, result)); return result


def synthetic_bootstrap_stdout(role: str, *, source_commit: str = SOURCE_COMMIT, source_tree: str = SOURCE_TREE, source_commit_body: bytes = SOURCE_COMMIT_BODY) -> bytes:
    if role == "git-version": return b"git version 2.34.1\n"
    if role in {"sdk-archive", "sdk-archive-confirm"}: return b"synthetic deterministic SDK archive\n"
    if role in {"patch-check", "patch-apply"} or role.endswith(("-status", "-head-index-diff", "-worktree-index-diff")): return b""
    if role.startswith("source-"):
        if role.endswith("-head"): return (source_commit + "\n").encode("ascii")
        if role.endswith("-tree"): return (source_tree + "\n").encode("ascii")
        if role.endswith("-index"): return b"synthetic-source-index\0"
        if role.endswith("-commit-object"): return source_commit_body
    if role.startswith("sdk-"):
        if role.endswith("-head"): return (SDK_COMMIT + "\n").encode("ascii")
        if role.endswith("-tree"): return (SDK_TREE + "\n").encode("ascii")
        if role.endswith("-index"): return b"synthetic-sdk-index\0"
    raise AssertionError(f"no synthetic bootstrap stdout for {role}")


class FakeBootstrapRawRunner:
    def __init__(
        self,
        *,
        mode: str = "ok",
        target_role: str = "source-before-head",
        source_commit: str = SOURCE_COMMIT,
        source_tree: str = SOURCE_TREE,
        source_commit_body: bytes = SOURCE_COMMIT_BODY,
    ):
        self.mode = mode; self.target_role = target_role; self.source_commit = source_commit; self.source_tree = source_tree; self.source_commit_body = source_commit_body; self.calls = []; self.results = []

    def __call__(self, argv: list[str], **kwargs):
        if len(self.calls) >= len(BOOTSTRAP_COMMAND_ROLES): raise AssertionError("bootstrap replay issued an extra command")
        role = BOOTSTRAP_COMMAND_ROLES[len(self.calls)]
        self.calls.append((role, list(argv), dict(kwargs)))
        stdout = synthetic_bootstrap_stdout(
            role,
            source_commit=self.source_commit,
            source_tree=self.source_tree,
            source_commit_body=self.source_commit_body,
        ); stderr = b""; returncode = 0
        if role == self.target_role and self.mode == "stdout-drift": stdout += b"drift"
        if role == self.target_role and self.mode == "stderr-drift": stderr = b"drift"
        if role == self.target_role and self.mode == "nonzero": returncode = 19
        result = subprocess.CompletedProcess(list(argv), returncode, stdout, stderr); self.results.append((role, result)); return result


class FakeBootstrapProducer:
    def __init__(
        self,
        template_root: Path,
        control_root: Path,
        *,
        mode: str = "ok",
        source_commit: str = SOURCE_COMMIT,
        source_tree: str = SOURCE_TREE,
        source_commit_body: bytes = SOURCE_COMMIT_BODY,
        source_commit_epoch: int = SOURCE_DATE_EPOCH,
    ):
        self.template_root = Path(template_root); self.control_root = Path(control_root); self.mode = mode
        self.source_commit = source_commit; self.source_tree = source_tree; self.source_commit_body = source_commit_body; self.source_commit_epoch = source_commit_epoch; self.calls = []

    def bootstrap_sdk(
        self,
        *,
        repository_root: Path,
        sdk_root: Path,
        output_root: Path,
        expected_source_commit: str,
        expected_source_tree: str,
        expected_sdk_commit: str,
        expected_sdk_tree: str,
        overlay_records,
        patch_path: Path,
        allowed_patch_paths,
        git_tool,
        runner,
    ):
        arguments = {
            "allowed_patch_paths": allowed_patch_paths, "expected_sdk_commit": expected_sdk_commit,
            "expected_sdk_tree": expected_sdk_tree, "expected_source_commit": expected_source_commit,
            "expected_source_tree": expected_source_tree, "git_tool": git_tool, "output_root": output_root,
            "overlay_records": overlay_records, "patch_path": patch_path, "repository_root": repository_root,
            "runner": runner, "sdk_root": sdk_root,
        }
        self.calls.append(arguments)
        repository_root = Path(repository_root); sdk_root = Path(sdk_root); output_root = Path(output_root); patch_path = Path(patch_path)
        expected_identity = (self.source_commit, self.source_tree, SDK_COMMIT, SDK_TREE)
        actual_identity = (expected_source_commit, expected_source_tree, expected_sdk_commit, expected_sdk_tree)
        if repository_root != ROOT or sdk_root != SDK_ROOT or actual_identity != expected_identity:
            raise AssertionError("bootstrap replay did not use independently fixed source and SDK identities")
        if list(overlay_records) != list(BOOTSTRAP_OVERLAY_RECORDS): raise AssertionError("bootstrap replay overlay invocation drift")
        if patch_path != BOOTSTRAP_PATCH_PATH or tuple(allowed_patch_paths) != tuple(sorted(BOOTSTRAP_PATCH_TARGETS)):
            raise AssertionError("bootstrap replay patch invocation drift")
        if git_tool != GIT_TOOL or not callable(runner): raise AssertionError("bootstrap replay tool/runner invocation drift")
        resolved_control = self.control_root.resolve(); resolved_output = output_root.resolve()
        if resolved_output == resolved_control or resolved_control not in resolved_output.parents:
            raise AssertionError("bootstrap replay output is not strictly under its control root")
        if output_root.is_symlink() or not output_root.is_dir() or list(output_root.iterdir()):
            raise AssertionError("bootstrap replay output is not a fresh empty real directory")
        patch_bytes = b"synthetic reviewed Stage0 patch\n"
        patch_record = {
            "paths": sorted(BOOTSTRAP_PATCH_TARGETS),
            "sha256": hashlib.sha256(patch_bytes).hexdigest().upper(),
            "size": len(patch_bytes),
        }
        expected_commands = synthetic_bootstrap_command_records(
            patch_record,
            source_commit=self.source_commit,
            source_tree=self.source_tree,
            source_commit_body=self.source_commit_body,
        )
        derived_commands = []
        owned_staging_root = output_root.with_name(output_root.name + "-owned-staging")
        owned_staging_root.mkdir(mode=0o700)

        def denormalize(value: str) -> str:
            return value.replace("${SOURCE_ROOT}", str(repository_root)).replace("${SDK_ROOT}", str(sdk_root)).replace("${OWNED_STAGING_ROOT}", str(owned_staging_root)).replace("${OUTPUT_ROOT}", str(output_root))

        cwd_roots = {"source": repository_root, "sdk": sdk_root, "${OWNED_STAGING_ROOT}": owned_staging_root}
        for expected in expected_commands:
            role = str(expected["role"]); argv = [denormalize(str(item)) for item in expected["argv"]]
            environment = {str(key): denormalize(str(value)) for key, value in expected["environment"].items()}
            options = {"check": False, "cwd": cwd_roots[str(expected["cwd"])], "env": environment, "shell": False, "stderr": subprocess.PIPE, "stdout": subprocess.PIPE}
            if expected["stdin"] is None: options["stdin"] = subprocess.DEVNULL
            else: options["input"] = patch_bytes
            result = runner(argv, **options)
            if not isinstance(result, subprocess.CompletedProcess) or result.returncode != 0 or not isinstance(result.stdout, bytes) or not isinstance(result.stderr, bytes): raise ValueError("synthetic bootstrap replay command failed")
            derived_commands.append({
                **deepcopy(expected), "exitCode": result.returncode,
                "stderrSha256": hashlib.sha256(result.stderr).hexdigest().upper(), "stderrSize": len(result.stderr),
                "stdoutSha256": hashlib.sha256(result.stdout).hexdigest().upper(), "stdoutSize": len(result.stdout),
            })
        owned_staging_root.rmdir()
        shutil.copytree(self.template_root, output_root, dirs_exist_ok=True, copy_function=shutil.copy2)
        baseline_tree_sha256 = independent_tree_sha256(output_root)
        if self.mode == "output-bytes": (output_root / "SDK/archive-mode-probe.sh").write_bytes(b"drift\n")
        elif self.mode == "output-mode": (output_root / "SDK/archive-mode-probe.sh").chmod(0o755)
        elif self.mode == "output-extra": (output_root / "SDK/unreviewed").write_bytes(b"extra\n")
        overlays = []
        for record in BOOTSTRAP_OVERLAY_RECORDS:
            data = (output_root / record["destination"]).read_bytes()
            overlays.append({**record, "sha256": hashlib.sha256(data).hexdigest().upper(), "size": len(data)})
        receipt = {
            "commands": derived_commands,
            "gitTool": deepcopy(GIT_TOOL),
            "locks": {"model1552-package.lock.json": MODEL_LOCK_SHA256, "packaging.lock.json": PACKAGE_LOCK_SHA256, "toolchain.lock.json": TOOLCHAIN_LOCK_SHA256},
            "outputTreeSha256": baseline_tree_sha256,
            "overlay": sorted(overlays, key=lambda record: record["source"]),
            "patch": patch_record,
            "schema": "e87-stage0-bootstrap-receipt-v1",
            "sdkCommit": SDK_COMMIT,
            "sdkTree": SDK_TREE,
            "sourceCommit": self.source_commit,
            "sourceCommitEpoch": self.source_commit_epoch,
            "sourceCommitObjectSha256": hashlib.sha256(self.source_commit_body).hexdigest().upper(),
            "sourceTree": self.source_tree,
            "validations": dict(BOOTSTRAP_VALIDATIONS),
        }
        if self.mode == "receipt-source": receipt["sourceCommit"] = "f" * 40
        elif self.mode == "receipt-sdk": receipt["sdkCommit"] = "0" * 40
        elif self.mode == "receipt-git": receipt["gitTool"]["sha256"] = "0" * 64
        elif self.mode == "receipt-validation": receipt["validations"]["sdkStable"] = False
        return receipt


class PackageTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.package = load_tool("e87_stage0_package", PACKAGE_TOOL)
        cls.build = load_tool("e87_stage0_build", BUILD_TOOL)
        cls.validator = load_tool("e87_stage0_validator", VALIDATOR_TOOL)
        cls.model_lock = json.loads((ROOT / "firmware/locks/model1552-package.lock.json").read_text())
        cls.packaging_lock = json.loads((ROOT / "firmware/locks/packaging.lock.json").read_text())
        cls.toolchain_lock = json.loads((ROOT / "firmware/locks/toolchain.lock.json").read_text())
        cls.ufw = load_tool("e87_stage0_package_test_ufw", ROOT / "firmware/tools/ufw.py")
        cls.qix = load_tool("e87_stage0_package_test_qix", ROOT / "firmware/tools/qix.py")
        cls.jlfw = load_tool("e87_stage0_package_test_jlfw", ROOT / "firmware/tools/jlfw.py")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="e87-package-test-"); self.base = Path(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def _independent_bootstrap_derivation(self, *, generated_sdk_root: Path, bootstrap_receipt_path: Path, control_root: Path, runner, event_sink=None) -> dict[str, object]:
        raw = Path(bootstrap_receipt_path).read_bytes(); receipt = json.loads(raw)
        if raw != (json.dumps(receipt, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii"): raise ValueError("bootstrap receipt is not canonical")
        source_identity = receipt.get("sourceCommit")
        if source_identity == SOURCE_COMMIT: source_body = SOURCE_COMMIT_BODY
        elif source_identity == ALTERNATE_SOURCE_COMMIT: source_body = ALTERNATE_SOURCE_COMMIT_BODY
        else: raise ValueError("unexpected synthetic source identity")
        patch_bytes = b"synthetic reviewed Stage0 patch\n"
        independent_patch = {
            "paths": sorted(BOOTSTRAP_PATCH_TARGETS),
            "sha256": hashlib.sha256(patch_bytes).hexdigest().upper(),
            "size": len(patch_bytes),
        }
        expected_commands = synthetic_bootstrap_command_records(
            independent_patch, source_commit=source_identity, source_tree=SOURCE_TREE, source_commit_body=source_body,
        )
        if Path(control_root).is_symlink() or not Path(control_root).is_dir(): raise ValueError("invalid replay control root")
        if not callable(runner): raise TypeError("bootstrap replay requires a runner")
        output_tree_sha256 = independent_tree_sha256(Path(generated_sdk_root))
        validation = {
            "commandsSha256": projection_sha256(expected_commands),
            "outputTreeSha256": output_tree_sha256,
            "receiptSha256": hashlib.sha256(raw).hexdigest().upper(),
            "schema": "e87-stage0-bootstrap-replay-validation-v1",
            "validationsSha256": projection_sha256(BOOTSTRAP_VALIDATIONS),
        }
        if event_sink is not None: event_sink("bootstrap-replay:validated")
        return {
            "commands": expected_commands,
            "outputTreeSha256": output_tree_sha256,
            "receiptSha256": validation["receiptSha256"],
            "schema": "e87-stage0-bootstrap-replay-evidence-v1",
            "validation": validation,
            "validations": dict(BOOTSTRAP_VALIDATIONS),
        }

    def _write_generated_sdk_fixture(
        self,
        generated_root: Path,
        *,
        mode_probe_executable: bool = False,
        receipt_path: Path | None = None,
        source_commit: str = SOURCE_COMMIT,
        source_commit_body: bytes = SOURCE_COMMIT_BODY,
        source_commit_epoch: int = SOURCE_DATE_EPOCH,
        source_commit_object_sha256: str = SOURCE_COMMIT_OBJECT_SHA256,
        source_tree: str = SOURCE_TREE,
    ) -> tuple[Path, dict[str, object]]:
        sdk = generated_root / "SDK"; (sdk / "build").mkdir(parents=True)
        (sdk / "Makefile").write_bytes(COMPILE_MAKEFILE); (sdk / "build/Makefile.mk").write_bytes(LINK_MAKEFILE)
        mode_probe = sdk / "archive-mode-probe.sh"; mode_probe.write_bytes(b"#!/bin/sh\nexit 0\n"); mode_probe.chmod(0o755 if mode_probe_executable else 0o644)
        overlay = []
        for relative in BOOTSTRAP_OVERLAYS:
            path = generated_root / relative; path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists(): path.write_bytes(("overlay:" + relative + "\n").encode("ascii"))
            data = path.read_bytes(); overlay.append({"destination": relative, "sha256": hashlib.sha256(data).hexdigest().upper(), "size": len(data), "source": "firmware/overlay/" + relative})
        for relative in BOOTSTRAP_PATCH_TARGETS:
            path = generated_root / relative; path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists(): path.write_bytes(("patched:" + relative + "\n").encode("ascii"))
        patch_bytes = b"synthetic reviewed Stage0 patch\n"
        patch_record = {"paths": sorted(BOOTSTRAP_PATCH_TARGETS), "sha256": hashlib.sha256(patch_bytes).hexdigest().upper(), "size": len(patch_bytes)}
        expected_commit = hashlib.sha1(b"commit " + str(len(source_commit_body)).encode("ascii") + b"\0" + source_commit_body).hexdigest()
        expected_epoch_match = re.search(rb"^committer .* ([0-9]+) [+-][0-9]{4}$", source_commit_body, re.MULTILINE)
        tree_headers = re.findall(rb"^tree ([0-9a-f]{40})$", source_commit_body, re.MULTILINE)
        if expected_epoch_match is None or tree_headers != [source_tree.encode("ascii")]: raise AssertionError("synthetic source commit identity is incoherent")
        if (source_commit, source_commit_epoch, source_commit_object_sha256) != (
            expected_commit,
            int(expected_epoch_match.group(1)),
            hashlib.sha256(source_commit_body).hexdigest().upper(),
        ):
            raise AssertionError("synthetic source commit metadata does not bind the raw object")
        receipt = {
            "commands": synthetic_bootstrap_command_records(
                patch_record,
                source_commit=source_commit,
                source_tree=source_tree,
                source_commit_body=source_commit_body,
            ),
            "gitTool": GIT_TOOL,
            "locks": {"model1552-package.lock.json": MODEL_LOCK_SHA256, "packaging.lock.json": PACKAGE_LOCK_SHA256, "toolchain.lock.json": TOOLCHAIN_LOCK_SHA256},
            "outputTreeSha256": independent_tree_sha256(generated_root),
            "overlay": sorted(overlay, key=lambda record: record["source"]),
            "patch": patch_record,
            "schema": "e87-stage0-bootstrap-receipt-v1",
            "sdkCommit": SDK_COMMIT,
            "sdkTree": SDK_TREE,
            "sourceCommit": source_commit,
            "sourceCommitEpoch": source_commit_epoch,
            "sourceCommitObjectSha256": source_commit_object_sha256,
            "sourceTree": source_tree,
            "validations": dict(BOOTSTRAP_VALIDATIONS),
        }
        receipt_path = receipt_path or generated_root.parent / f"{generated_root.name}-bootstrap-receipt.json"
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_bytes((json.dumps(receipt, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii"))
        return receipt_path, receipt

    def _copy_lock_root(self, name: str) -> Path:
        lock_root = self.base / name; lock_root.mkdir()
        for filename in ("model1552-package.lock.json", "packaging.lock.json", "toolchain.lock.json"):
            shutil.copy2(ROOT / "firmware/locks" / filename, lock_root / filename)
        return lock_root

    def _copy_reference_root(self, name: str) -> Path:
        target = self.base / name; target.mkdir()
        for relative in self.model_lock["referenceFiles"]:
            destination = target / relative; destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(REFERENCE_ROOT / relative, destination); destination.chmod(0o444)
        for directory in sorted((path for path in target.rglob("*") if path.is_dir()), key=lambda path: len(path.parts), reverse=True): directory.chmod(0o555)
        target.chmod(0o555)
        return target

    def _copy_sdk_loader_root(self, name: str) -> Path:
        target = self.base / name; loader = target / self.model_lock["sdkLoader"]["sdkRelativePath"]
        loader.parent.mkdir(parents=True); shutil.copy2(SDK_ROOT / self.model_lock["sdkLoader"]["sdkRelativePath"], loader)
        return target

    def _copy_post_root(self, name: str) -> Path:
        target = self.base / name; target.mkdir()
        for tool in self.packaging_lock["tools"].values():
            source = POST_ROOT / tool["installRelativePath"]; destination = target / tool["installRelativePath"]
            shutil.copy2(source, destination); destination.chmod(0o755)
        return target

    def _copy_invoked_build_tools(self, name: str) -> dict[str, dict[str, object]]:
        resolve_tools = require_api(self, self.build, "resolve_pinned_tools")
        resolved = resolve_tools(self.toolchain_lock, make_tool=MAKE_TOOL); target = self.base / name; target.mkdir()
        copied = deepcopy(resolved)
        for tool_name in ("make", "objcopy", "objdump", "nm"):
            source = Path(str(resolved[tool_name]["path"])); destination = target / tool_name / source.name; destination.parent.mkdir(); shutil.copy2(source, destination); destination.chmod(0o755)
            self.assertEqual(hashlib.sha256(destination.read_bytes()).hexdigest().upper(), resolved[tool_name]["sha256"])
            copied[tool_name] = {**resolved[tool_name], "path": str(destination)}
        return copied

    def _path_identity(self, path: Path) -> tuple[object, ...]:
        stat = path.lstat()
        content = os.readlink(path) if path.is_symlink() else hashlib.sha256(path.read_bytes()).hexdigest().upper()
        return (stat.st_dev, stat.st_ino, stat.st_mode, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, content)

    def _mutate_use_window_path(self, path: Path, mode: str) -> tuple[tuple[object, ...], tuple[object, ...]]:
        original = path.read_bytes(); original_mode = path.stat().st_mode & 0o777; before = self._path_identity(path)
        path.parent.chmod(path.parent.stat().st_mode | 0o700); path.chmod(original_mode | 0o600)
        if mode == "bytes-one-way": path.write_bytes(original + b"drift")
        elif mode == "bytes-aba": path.write_bytes(original + b"drift"); path.write_bytes(original); path.chmod(original_mode)
        else:
            target_root = self.base / "same-byte-symlink-targets"; target_root.mkdir(exist_ok=True)
            target = target_root / hashlib.sha256((str(path) + mode).encode("utf-8")).hexdigest(); target.write_bytes(original); target.chmod(original_mode)
            path.unlink(); path.symlink_to(target)
            if mode == "symlink-aba": path.unlink(); path.write_bytes(original); path.chmod(original_mode)
            elif mode != "symlink-one-way": raise AssertionError(f"unknown mutation mode: {mode}")
        after = self._path_identity(path)
        if mode in {"bytes-aba", "symlink-aba"} and after == before:
            temporary = path.with_name(path.name + ".bytes-aba-rebind")
            if temporary.exists() or temporary.is_symlink(): raise AssertionError("ABA fallback temporary collision")
            try:
                temporary.write_bytes(original); temporary.chmod(original_mode); os.replace(temporary, path)
            finally:
                if temporary.exists() or temporary.is_symlink(): temporary.unlink()
            after = self._path_identity(path)
        return before, after

    def _rebind_directory_for_test(self, target: Path, *, sentinel_relative: Path, mode: str) -> dict[str, Path | bytes]:
        target = Path(target)
        if not target.is_dir() or target.is_symlink(): raise AssertionError("rebind target must start as a real directory")
        original = target.with_name(target.name + "-parked-original")
        victim = target.with_name(target.name + "-victim")
        escaped = target.with_name(target.name + "-escaped-victim")
        for candidate in (original, victim, escaped):
            if candidate.exists() or candidate.is_symlink(): raise AssertionError("directory rebind fixture collision")
        sentinel_bytes = ("external-sentinel:" + target.name + ":" + mode).encode("ascii")
        sentinel = victim / sentinel_relative
        sentinel.parent.mkdir(parents=True); sentinel.write_bytes(sentinel_bytes); sentinel.chmod(0o640)
        os.replace(target, original); os.replace(victim, target)
        if mode == "one-way":
            visible_sentinel = target / sentinel_relative
        elif mode == "aba":
            os.replace(target, escaped); os.replace(original, target); visible_sentinel = escaped / sentinel_relative
        else:
            raise AssertionError(f"unknown directory-rebind mode: {mode}")
        return {"escaped": escaped, "original": original, "sentinel": visible_sentinel, "sentinelBytes": sentinel_bytes}

    def _build_version_probe_receipts(self, tools: dict[str, dict[str, object]]) -> list[dict[str, object]]:
        empty_sha = hashlib.sha256(b"").hexdigest().upper()
        records = []
        for name in ("make", "objcopy", "objdump", "nm"):
            result = subprocess.CompletedProcess(
                [str(tools[name]["path"]), "--version"], 0, BUILD_TOOL_VERSION_STDOUT[name], b"",
            )
            summary = {
                "argv": [str(tools[name]["path"]), "--version"],
                "exitCode": 0,
                "stderrSha256": empty_sha,
                "stdoutSha256": hashlib.sha256(BUILD_TOOL_VERSION_STDOUT[name]).hexdigest().upper(),
                "tool": name,
                "toolSha256": str(tools[name]["sha256"]),
                "version": BUILD_TOOL_VERSIONS[name],
            }
            records.append(build_raw_record(summary, result))
        return records

    def _build_receipt_fixture(self, build_root: Path, app: bytes) -> dict[str, object]:
        build_root.mkdir(); (build_root / "app.bin").write_bytes(app)
        generated_root = build_root.parent / f"{build_root.name}-generated"; bootstrap_path, bootstrap = self._write_generated_sdk_fixture(generated_root, receipt_path=build_root / "bootstrap-receipt.json")
        for relative in OBJECTS:
            path = generated_root / "SDK/build" / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(("object:" + relative + "\n").encode("ascii"))
        if len(app) < len(SECTIONS): raise AssertionError("build receipt fixture app is too small")
        chunks = [app[index:index + 1] for index in range(len(SECTIONS) - 1)] + [app[len(SECTIONS) - 1:]]
        map_path = generated_root / "SDK/cpu/br35/tools/sdk.map"; map_path.parent.mkdir(parents=True, exist_ok=True)
        map_path.write_text(f".text.bt_ble_init 0x0C000100 0x{len(chunks[0]):X} objs/apps/watch/e87/e87_stage0_ble.c.o\n                0x0C000100 bt_ble_init\n", encoding="ascii")
        section_records = []
        section_outputs = []
        section_payloads = {name: data for (name, _), data in zip(SECTIONS, chunks)}
        elf_data, elf_sections, _ = make_elf32_fixture(section_payloads)
        for index, ((name, filename), data) in enumerate(zip(SECTIONS, chunks)):
            digest = hashlib.sha256(data).hexdigest().upper()
            parsed = elf_sections[index]
            section_records.append({**parsed, "sha256": digest})
            section_outputs.append({"filename": filename, "section": name, "sha256": digest, "size": len(data)})
            (build_root / filename).write_bytes(data)
        (build_root / "sdk.elf").write_bytes(elf_data); authoritative_elf = generated_root / "SDK/cpu/br35/tools/sdk.elf"; authoritative_elf.write_bytes(elf_data)
        empty_sha = hashlib.sha256(b"").hexdigest().upper()
        command_specs = [
            ("make", ["/usr/bin/make", "-C", str(generated_root / "SDK"), f"TOOL_DIR={TOOLCHAIN_ROOT / 'pi32v2/bin'}", "RUN_POST_SCRIPT=true", "VERBOSE=0", "-j6"], b"linked\n", MAKE_TOOL["sha256"], BUILD_TOOL_VERSIONS["make"]),
            *((f"objcopy:{section}", [str(TOOLCHAIN_ROOT / "common/bin/objcopy"), "-O", "binary", "-j", section, str(authoritative_elf), str(build_root / filename)], b"", "A941EAB0DD62D51DA635BE7834FC34D4765DBF421D00599F3A5081D42D416502", "LLVM 4.0.1") for section, filename in SECTIONS),
            ("objdump", [str(TOOLCHAIN_ROOT / "common/bin/objdump"), "-private-headers", "-section-headers", "-mcpu=r3", str(authoritative_elf)], synthetic_objdump_stdout(section_payloads), "CFFC304E1A9BE5DAC22984A6AD48E81EF82B17166FD8864C251CF635C9663B73", "LLVM 4.0.1"),
            ("nm", [str(TOOLCHAIN_ROOT / "pi32v2/bin/nm"), "-n", "--defined-only", str(authoritative_elf)], b"0C000100 T bt_ble_init\n", "32BEE027A324BD4D561079C943D94C53FECE2BFB7F1E12B5D7CE7CC7737C6CE4", "GNU Binutils 2.26.51.20160621"),
        ]
        commands = []
        for role, argv, stdout, tool_sha, tool_version in command_specs:
            result = subprocess.CompletedProcess(argv, 0, stdout, b"")
            commands.append(build_raw_record({
                "argv": argv, "exitCode": 0, "role": role,
                "stderrSha256": empty_sha, "stdoutSha256": hashlib.sha256(stdout).hexdigest().upper(),
                "toolSha256": tool_sha, "toolVersion": tool_version,
            }, result))
        build_tools = {
            "make": MAKE_TOOL,
            "objcopy": {"path": str(TOOLCHAIN_ROOT / "common/bin/objcopy"), "sha256": "A941EAB0DD62D51DA635BE7834FC34D4765DBF421D00599F3A5081D42D416502"},
            "objdump": {"path": str(TOOLCHAIN_ROOT / "common/bin/objdump"), "sha256": "CFFC304E1A9BE5DAC22984A6AD48E81EF82B17166FD8864C251CF635C9663B73"},
            "nm": {"path": str(TOOLCHAIN_ROOT / "pi32v2/bin/nm"), "sha256": "32BEE027A324BD4D561079C943D94C53FECE2BFB7F1E12B5D7CE7CC7737C6CE4"},
        }
        bootstrap_data = bootstrap_path.read_bytes()
        bootstrap_validation = synthetic_bootstrap_replay_evidence(bootstrap, bootstrap_data)["validation"]
        receipt = {
            "app": {"filename": "app.bin", "sha256": hashlib.sha256(app).hexdigest().upper(), "size": len(app)},
            "bootstrap": bootstrap,
            "bootstrapReceipt": {"filename": bootstrap_path.name, "sha256": hashlib.sha256(bootstrap_data).hexdigest().upper(), "size": len(bootstrap_data)},
            "bootstrapValidation": bootstrap_validation,
            "buildProvenance": {
                "compileMakefile": {"cpu": "r3", "relativePath": "SDK/Makefile", "sha256": hashlib.sha256(COMPILE_MAKEFILE).hexdigest().upper(), "target": "pi32v2"},
                "linkMakefile": {"cpu": "r3", "cpuTokenCount": 2, "relativePath": "SDK/build/Makefile.mk", "sha256": hashlib.sha256(LINK_MAKEFILE).hexdigest().upper()},
            },
            "commands": commands,
            "elf": {"filename": "sdk.elf", "sha256": hashlib.sha256(elf_data).hexdigest().upper(), "size": len(elf_data)},
            "inputs": [{"filename": bootstrap_path.name, "sha256": hashlib.sha256(bootstrap_data).hexdigest().upper(), "size": len(bootstrap_data)}],
            "mapProvenance": {"bt_ble_init": {"address": "0x0C000100", "object": OBJECTS[2], "strength": "STRONG"}},
            "runtime": expected_runtime_receipt(),
            "environment": normalized_build_environment(),
            "resourceLimits": dict(BUILD_RESOURCE_LIMITS),
            "sourceCommit": bootstrap["sourceCommit"],
            "sourceDateEpoch": bootstrap["sourceCommitEpoch"],
            "schema": "e87-stage0-build-receipt-v1",
            "sectionOutputs": section_outputs,
            "sections": section_records,
            "sourceObjects": OBJECTS,
            "symbols": [{"address": "0x0C000100", "kind": "T", "name": "bt_ble_init"}],
            "target": {"architecture": "pi32v2", "codeEnd": f"0x{max(int(item['lma']) + int(item['size']) for item in section_records) - 0x0C000000:08X}", "cpu": "r3", "entryAddress": "0x0C000100", "mapSha256": hashlib.sha256((generated_root / "SDK/cpu/br35/tools/sdk.map").read_bytes()).hexdigest().upper(), "uiresStart": "0x00180000"},
            "validations": dict(BUILD_VALIDATIONS),
            "versionProbes": self._build_version_probe_receipts(build_tools),
        }
        (build_root / "build-receipt.json").write_text(json.dumps(receipt, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="ascii")
        return receipt

    def _write_exact_staging_fixture(self, staging: Path, app: bytes, *, reference_root: Path = REFERENCE_ROOT, sdk_root: Path = SDK_ROOT) -> list[dict[str, object]]:
        staging.mkdir(); staged = {"app.bin": app, "br35loader.bin": (sdk_root / self.model_lock["sdkLoader"]["sdkRelativePath"]).read_bytes()}
        mapping = {
            "uboot.boot": "canonical-jl-unpack/top/uboot.boot",
            "cfg_tool.bin": "canonical-jl-unpack/files/cfg_tool.bin",
            "config.dat": "canonical-jl-unpack/files/config.dat",
            "p11_code.bin": "canonical-jl-unpack/files/p11_code.bin",
            "stream.bin": "canonical-jl-unpack/files/stream.bin",
            "flash_params_v3.bin": "items/03_params_flash.bin",
            "isd_config.ini": "items/04_isd_config.ini",
            "ota.bin": "items/06_ota.bin",
        }
        for name, relative in mapping.items():
            data = (reference_root / relative).read_bytes()
            if name == "isd_config.ini": data = data.replace(b"RESET = PB07_08_0;", b"RESET = PB07_00_0;", 1)
            staged[name] = data
        for name, data in staged.items(): (staging / name).write_bytes(data)
        self.assertEqual(set(staged), STAGING_NAMES)
        return [{"filename": name, "role": "REVIEWED_APP" if name == "app.bin" else "PINNED_PACKAGE_INPUT", "sha256": hashlib.sha256(data).hexdigest().upper(), "size": len(data)} for name, data in sorted(staged.items())]

    def _native_command_receipts(self, *, stdout_by_role: dict[str, bytes] | None = None) -> list[dict[str, object]]:
        empty_sha = hashlib.sha256(b"").hexdigest().upper()
        stdout_by_role = stdout_by_role or {}
        isd_stdout = stdout_by_role.get("isdDownload", b"")
        ufw_stdout = stdout_by_role.get("ufwMaker", b"")
        return [
            {"argv": [str(POST_ROOT / "isd_download"), *ISD_ARGUMENTS], "exitCode": 0, "role": "isdDownload", "stderrHex": "", "stderrSha256": empty_sha, "stderrSize": 0, "stdoutHex": isd_stdout.hex().upper(), "stdoutSha256": hashlib.sha256(isd_stdout).hexdigest().upper(), "stdoutSize": len(isd_stdout), "toolSha256": "11849221C3E5E89D31E6FCEF52FE1DB28C2C5D322CDB919E954CCA2A5043EF87", "toolVersion": "4.2.79"},
            {"argv": [str(POST_ROOT / "ufw_maker"), "--fw", "jl_isd.fw", "--output", "independently-made.ufw"], "exitCode": 0, "role": "ufwMaker", "stderrHex": "", "stderrSha256": empty_sha, "stderrSize": 0, "stdoutHex": ufw_stdout.hex().upper(), "stdoutSha256": hashlib.sha256(ufw_stdout).hexdigest().upper(), "stdoutSize": len(ufw_stdout), "toolSha256": "039D761CA4170F1E5658B868C963E8D43651000368BE55E892CD0BD941B553C6", "toolVersion": "1.1.14"},
        ]

    def _native_command_summaries(self, commands: list[dict[str, object]]) -> list[dict[str, object]]:
        keys = ("argv", "exitCode", "role", "stderrSha256", "stderrSize", "stdoutSha256", "stdoutSize", "toolSha256", "toolVersion")
        return [{key: deepcopy(command[key]) for key in keys} for command in commands]

    def _real_package_proofs(self, fixture: dict[str, bytes], qix_bytes: bytes) -> dict[str, object]:
        app = fixture["app.bin"]
        bin_proof = self.jlfw.prove_embedded_app(fixture["jl_isd.bin"], app, container_kind="jl_isd.bin")
        fw_proof = self.jlfw.prove_embedded_app(fixture["jl_isd.fw"], app, container_kind="jl_isd.fw")
        pair = self.jlfw.prove_package_pair(fixture["jl_isd.bin"], fixture["jl_isd.fw"], app)

        def ufw_summary(data: bytes) -> dict[str, object]:
            parsed = self.ufw.validate_stage0_ufw(data)
            flash = next(item["data"] for item in parsed["entries"] if item["name"] == "flash.bin")
            ini = next(item["data"] for item in parsed["entries"] if item["name"] == "isd_config.ini")
            return {"flashSha256": hashlib.sha256(flash).hexdigest().upper(), "iniSha256": hashlib.sha256(ini).hexdigest().upper(), "itemCount": parsed["itemCount"], "sha256": hashlib.sha256(data).hexdigest().upper(), "size": len(data)}

        native_ufw = ufw_summary(fixture["update.ufw"])
        independent_ufw = ufw_summary(fixture["independently-made.ufw"])
        parsed_qix = self.qix.parse_qix(qix_bytes, expected_version="11.1.0.3")
        payload = parsed_qix["payload"]
        return {
            "jlfw": {
                "appSha256": pair["appSha256"], "appSize": len(app), "entryAddress": bin_proof["entryAddress"],
                "flashEqual": pair["flashEqual"], "flashSha256": bin_proof["flashSha256"], "fwEnvelopeKind": pair["fwEnvelopeKind"],
                "jlIsdBinSha256": bin_proof["containerSha256"], "jlIsdFwSha256": fw_proof["containerSha256"],
            },
            "qix": {
                "payloadFilename": "update.ufw", "payloadSha256": hashlib.sha256(fixture["update.ufw"]).hexdigest().upper(),
                "qixSha256": hashlib.sha256(qix_bytes).hexdigest().upper(), "qixSize": len(qix_bytes), "relation": "BYTE_IDENTICAL",
                "unwrappedPayloadSha256": hashlib.sha256(payload).hexdigest().upper(), "version": parsed_qix["version"],
            },
            "resetPolicy": {"recoveredSha256": "CEC1973E50FB7A3D74D04D6340C671A443D50C538C272E1B14567C71F9AED47A", "semanticDiff": {"after": "RESET = PB07_00_0;", "before": "RESET = PB07_08_0;", "occurrences": 1}, "stagedSha256": native_ufw["iniSha256"]},
            "ufw": {"independent": independent_ufw, "native": native_ufw, "relation": "BYTE_IDENTICAL"},
        }

    def _write_package_source_receipts(self, root: Path, *, commands: list[dict[str, object]], environment: dict[str, str], inputs: list[dict[str, object]], validations: dict[str, object]) -> tuple[Path, Path]:
        root.mkdir(parents=True, exist_ok=True)
        execution = {"commands": commands, "environment": environment, "inputs": inputs, "schema": "e87-stage0-native-execution-v1"}
        validation = {"schema": "e87-stage0-package-validation-v1", "validations": validations}
        execution_path = root / "native-execution.json"; validation_path = root / "validation.json"
        execution_path.write_bytes((json.dumps(execution, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii"))
        validation_path.write_bytes((json.dumps(validation, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii"))
        return execution_path, validation_path

    def test_reference_root_exactly_matches_eleven_pins_and_forbidden_binary_is_refused_not_assumed_absent(self):
        receipt = self.package.verify_reference_root(REFERENCE_ROOT, self.model_lock)
        self.assertEqual((receipt["fileCount"], receipt["manifestSha256"]), (11, "01FBB801B9C408F6BE2F885A92DDC561151FB4A70450F37F39C6C56F25222678"))
        self.assertNotIn("canonical-jl-unpack/top/isd_config.ini", receipt["packageInputs"])
        self.assertEqual(set(receipt["verifiedFiles"]), set(self.model_lock["referenceFiles"]))
        with self.assertRaises(ValueError):
            self.package.validate_package_source("canonical-jl-unpack/top/isd_config.ini", bytes(135))
        copied = self._copy_reference_root("copied-reference")
        self.assertEqual(self.package.verify_reference_root(copied, self.model_lock)["verifiedFiles"], receipt["verifiedFiles"])
        for relative in self.model_lock["referenceFiles"]:
            path = copied / relative; parent = path.parent; original = path.read_bytes()
            with self.subTest(pin=relative, mutation="bytes"):
                parent.chmod(0o755); path.chmod(0o644); path.write_bytes(bytes([original[0] ^ 1]) + original[1:]); path.chmod(0o444); parent.chmod(0o555)
                with self.assertRaises(ValueError): self.package.verify_reference_root(copied, self.model_lock)
            parent.chmod(0o755); path.chmod(0o644); path.write_bytes(original); path.chmod(0o444); parent.chmod(0o555)
            with self.subTest(pin=relative, mutation="symlink"):
                parent.chmod(0o755); path.unlink(); path.symlink_to(REFERENCE_ROOT / relative); parent.chmod(0o555)
                with self.assertRaises(ValueError): self.package.verify_reference_root(copied, self.model_lock)
            parent.chmod(0o755); path.unlink(); path.write_bytes(original); path.chmod(0o444); parent.chmod(0o555)
        copied.chmod(0o755)
        for path in copied.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)

    def test_reset_transform_is_exact_one_replacement_semantic_diff_and_source_immutable(self):
        source = REFERENCE_ROOT / "items/04_isd_config.ini"; before = source.read_bytes()
        transformed, semantic_diff = self.package.transform_reset_ini(before)
        self.assertEqual(transformed, before.replace(b"RESET = PB07_08_0;", b"RESET = PB07_00_0;", 1))
        self.assertEqual(semantic_diff, {"after": "RESET = PB07_00_0;", "before": "RESET = PB07_08_0;", "occurrences": 1})
        self.assertEqual((len(transformed), hashlib.sha256(transformed).hexdigest().upper()), (1657, "05662B8EBF6FB08A9E07611D680C293B023C7B802F82AE0A4CCC7E2ED50639F3"))
        self.assertEqual(source.read_bytes(), before)
        for invalid in (before.replace(b"PB07_08_0", b"PB07_00_0"), before + b"\nRESET = PB07_08_0;\n", before.replace(b"RESET = PB07_08_0;", b"RESET=PB07_08_0;")):
            with self.subTest():
                with self.assertRaises(ValueError): self.package.transform_reset_ini(invalid)

    def test_staging_copies_exact_ten_inputs_transforms_only_ini_and_preserves_sources(self):
        staging = self.base / "staging"; staging.mkdir(); build_root = self.base / "staging-build"; build_receipt = self._build_receipt_fixture(build_root, b"reviewed-stage0-app"); app = build_root / "app.bin"
        watched = {path: (REFERENCE_ROOT / path).read_bytes() for path in self.model_lock["referenceFiles"]}
        loader = SDK_ROOT / self.model_lock["sdkLoader"]["sdkRelativePath"]; loader_before = loader.read_bytes()
        receipt = call_contract(self, "cross-bound staging", self.package.stage_inputs, REFERENCE_ROOT, SDK_ROOT, app, staging, self.model_lock, build_receipt=build_receipt)
        self.assertEqual(set(path.name for path in staging.iterdir()), STAGING_NAMES)
        self.assertEqual(receipt["inputCount"], 10)
        self.assertEqual({item["filename"] for item in receipt["inputs"]}, STAGING_NAMES)
        self.assertTrue(all(item["size"] > 0 and re.fullmatch(r"[0-9A-F]{64}", item["sha256"]) for item in receipt["inputs"]))
        app_record = next(item for item in receipt["inputs"] if item["filename"] == "app.bin")
        self.assertEqual((app_record["size"], app_record["sha256"]), (build_receipt["app"]["size"], build_receipt["app"]["sha256"]))
        self.assertEqual((staging / "app.bin").read_bytes(), app.read_bytes())
        self.assertIn(b"RESET = PB07_00_0;", (staging / "isd_config.ini").read_bytes())
        self.assertNotIn(b"RESET = PB07_08_0;", (staging / "isd_config.ini").read_bytes())
        self.assertEqual({path: (REFERENCE_ROOT / path).read_bytes() for path in watched}, watched)
        self.assertEqual(loader.read_bytes(), loader_before)
        for label, data, mutation in (
            ("empty", b"", None),
            ("size", b"reviewed-stage0-app", {"size": 1}),
            ("sha", b"reviewed-stage0-app", {"sha256": "0" * 64}),
        ):
            candidate = self.base / f"{label}.bin"; candidate.write_bytes(data)
            target = self.base / f"staging-{label}"; target.mkdir()
            bad_receipt = deepcopy(build_receipt)
            if mutation: bad_receipt["app"].update(mutation)
            with self.subTest(label=label):
                with self.assertRaises(ValueError):
                    self.package.stage_inputs(REFERENCE_ROOT, SDK_ROOT, candidate, target, self.model_lock, build_receipt=bad_receipt)

    def test_build_package_and_evidence_roots_are_absolute_empty_real_and_outside_all_protected_roots(self):
        protected = []
        for name in ("repository", "installed-sdk", "toolchain", "post-tools"):
            path = self.base / name; path.mkdir(); protected.append(path)
        good = self.base / "good-output"; good.mkdir()
        self.assertEqual(self.validator.validate_output_root(good, tuple(protected), require_empty=True), good.resolve())
        relative = Path("relative-output")
        nonempty = self.base / "nonempty"; nonempty.mkdir(); (nonempty / "x").write_bytes(b"x")
        inside = []
        for root in protected:
            candidate = root / "nested"; candidate.mkdir(); inside.append(candidate)
        real = self.base / "real"; real.mkdir()
        link = self.base / "link"; link.symlink_to(real, target_is_directory=True)
        parent_link = self.base / "parent-link"; parent_link.symlink_to(real, target_is_directory=True)
        under_parent = parent_link / "nested"; under_parent.mkdir()
        for candidate in (relative, nonempty, *inside, link, under_parent):
            with self.subTest(candidate=str(candidate)):
                with self.assertRaises(ValueError):
                    self.validator.validate_output_root(candidate, tuple(protected), require_empty=True)

    def test_make_and_eight_objcopy_commands_are_exact_arrays(self):
        sdk = self.base / "generated-sdk"; sdk.mkdir(); tool_dir = Path("/home/jethac/.local/share/e87-dev/jieli/pi32v2/bin")
        make = self.build.make_command(sdk, tool_dir, jobs=6)
        self.assertEqual(make, ["/usr/bin/make", "-C", str(sdk / "SDK"), f"TOOL_DIR={tool_dir}", "RUN_POST_SCRIPT=true", "VERBOSE=0", "-j6"])
        elf = sdk / "SDK/cpu/br35/tools/sdk.elf"; output = self.base / "sections"; output.mkdir(); objcopy = Path("/home/jethac/.local/share/e87-dev/jieli/common/bin/objcopy")
        commands = self.build.objcopy_commands(objcopy, elf, output)
        self.assertEqual(commands, [[str(objcopy), "-O", "binary", "-j", section, str(elf), str(output / filename)] for section, filename in SECTIONS])
        build_command_specs = require_api(self, self.build, "build_command_specs")
        tools = {
            "make": MAKE_TOOL,
            "objcopy": {"path": str(objcopy), "sha256": self.toolchain_lock["tools"]["objcopy"]["sha256"]},
            "objdump": {"path": str(TOOLCHAIN_ROOT / "common/bin/objdump"), "sha256": self.toolchain_lock["tools"]["objdump"]["sha256"]},
            "nm": {"path": str(TOOLCHAIN_ROOT / "pi32v2/bin/nm"), "sha256": self.toolchain_lock["tools"]["nm"]["sha256"]},
        }
        specs = build_command_specs(generated_sdk_root=sdk, build_root=output, tools=tools)
        self.assertEqual([item["role"] for item in specs], ["make", *[f"objcopy:{section}" for section, _ in SECTIONS], "objdump", "nm"])
        self.assertTrue(all(set(item) == {"argv", "role", "tool"} for item in specs))
        self.assertEqual(specs[0]["argv"], make)
        self.assertEqual([item["argv"] for item in specs[1:9]], commands)
        self.assertEqual(specs[9]["argv"], [tools["objdump"]["path"], "-private-headers", "-section-headers", "-mcpu=r3", str(elf)])
        self.assertEqual(specs[10]["argv"], [tools["nm"]["path"], "-n", "--defined-only", str(elf)])
        realistic = [f"SDK/build/{path}" for path in OBJECTS]
        self.build.validate_source_selection(realistic)
        for forbidden in ("e87_renderer.o", "e87_assets.o", "e87_button_classifier.o", "e87_button_fsm.o", "e87_recovery.o", "board_jl707n_demo.o"):
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(ValueError): self.build.validate_source_selection([forbidden])

    def test_source_section_symbol_map_boundary_concatenation_and_build_receipt_fixtures(self):
        sources = [f"SDK/build/{path}" for path in OBJECTS]
        try:
            self.build.validate_source_selection(sources)
        except ValueError as error:
            self.fail(f"canonical realistic object inventory rejected: {error}")
        for bad in (sources[:-1], sources + [sources[0]]):
            with self.assertRaises(ValueError): self.build.validate_source_selection(bad)

        sections = []
        address = 0x0C000100
        file_offset = 0x100
        for section, _ in SECTIONS:
            sections.append({"fileOffset": file_offset, "lma": address, "name": section, "size": 0x10, "vma": address})
            address += 0x10; file_offset += 0x10
        self.build.validate_target_layout(sections, architecture="pi32v2", cpu="r3", entry_address=0x0C000100)
        for field, value in (("architecture", "arm"), ("cpu", "r2"), ("entry_address", 0x0C000104)):
            arguments = {"architecture": "pi32v2", "cpu": "r3", "entry_address": 0x0C000100}; arguments[field] = value
            with self.subTest(field=field):
                with self.assertRaises(ValueError): self.build.validate_target_layout(sections, **arguments)
        for mutation in ("missing", "extra", "overlap"):
            changed = [dict(item) for item in sections]
            if mutation == "missing": changed.pop()
            if mutation == "extra": changed.append({"fileOffset": 0, "lma": address, "name": ".unexpected", "size": 0x10, "vma": address})
            if mutation == "overlap": changed[1]["lma"] = changed[0]["lma"]
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError): self.build.validate_target_layout(changed, architecture="pi32v2", cpu="r3", entry_address=0x0C000100)
        boundary = [dict(item) for item in sections]
        boundary[-1]["size"] = 0x0C180000 - int(boundary[-1]["lma"])
        text = boundary[0]; self.assertEqual(text["name"], ".text")
        self.assertLessEqual(int(text["vma"]), 0x0C000100); self.assertLess(0x0C000100, int(text["vma"]) + int(text["size"]))
        self.assertEqual([item["name"] for item in boundary], [name for name, _ in SECTIONS])
        self.assertEqual(max(int(item["lma"]) + int(item["size"]) for item in boundary), 0x0C180000)
        self.build.validate_target_layout(boundary, architecture="pi32v2", cpu="r3", entry_address=0x0C000100)
        crossing = [dict(item) for item in boundary]; crossing[-1]["size"] += 1
        with self.assertRaises(ValueError): self.build.validate_target_layout(crossing, architecture="pi32v2", cpu="r3", entry_address=0x0C000100)

        symbols = [("bt_ble_init", "T", 0x0C000100)]
        self.build.validate_symbol_policy(symbols)
        for bad in ([], [("bt_ble_init", "W", 0x0C000100)], symbols + symbols):
            with self.assertRaises(ValueError): self.build.validate_symbol_policy(bad)
        good_map = ".text.bt_ble_init 0x0C000100 0x20 SDK/build/objs/apps/watch/e87/e87_stage0_ble.c.o\n                0x0C000100 bt_ble_init\n"
        self.build.validate_map_policy(good_map)
        for bad_map in ("", ".text.bt_ble_init 0x0C000100 0x20 SDK/build/objs/other.c.o\n                0x0C000100 bt_ble_init\n", good_map + "e87_renderer.c.o\n"):
            with self.assertRaises(ValueError): self.build.validate_map_policy(bad_map)

        section_root = self.base / "sections"; section_root.mkdir(); app_path = self.base / "app.bin"
        for index, (_, filename) in enumerate(SECTIONS): (section_root / filename).write_bytes(bytes([index + 1]))
        concatenated = self.build.concatenate_sections(section_root, app_path)
        self.assertEqual(app_path.read_bytes(), bytes(range(1, 9)))
        self.assertEqual(set(concatenated), {"appSha256", "appSize", "sections"})
        self.assertEqual([item["section"] for item in concatenated["sections"]], [section for section, _ in SECTIONS])

    def test_build_cli_dispatches_closed_fake_eleven_command_pipeline_and_never_shells(self):
        parser_factory = require_api(self, self.build, "build_parser")
        run_target_build = require_api(self, self.build, "run_target_build")
        build_command_specs = require_api(self, self.build, "build_command_specs")
        derive_bootstrap = require_api(self, self.build, "derive_expected_bootstrap_evidence")
        validate_bootstrap = require_api(self, self.build, "validate_bootstrap_receipt")
        resolve_lto_runtime = require_api(self, self.build, "resolve_lto_runtime")
        snapshot_lto_runtime = require_api(self, self.build, "snapshot_lto_runtime")
        reverify_lto_runtime = require_api(self, self.build, "reverify_lto_runtime")
        build_runtime_receipt = require_api(self, self.build, "build_runtime_receipt")
        validate_runtime_receipt = require_api(self, self.build, "validate_runtime_receipt")
        validate_wrapper_argv = require_api(self, self.build, "validate_lto_wrapper_argv")
        derive_parameters = inspect.signature(derive_bootstrap).parameters
        self.assertEqual(
            list(derive_parameters),
            ["generated_sdk_root", "bootstrap_receipt_path", "control_root", "runner", "event_sink"],
        )
        self.assertTrue(all(parameter.kind is inspect.Parameter.KEYWORD_ONLY for parameter in derive_parameters.values()))
        self.assertTrue(all(derive_parameters[name].default is inspect.Parameter.empty for name in ("generated_sdk_root", "bootstrap_receipt_path", "control_root", "runner")))
        self.assertIsNone(derive_parameters["event_sink"].default)
        elf, elf_sections, section_bytes = make_elf32_fixture()
        generated = self.base / "generated"; build_root = self.base / "target-output"; build_root.mkdir(); bootstrap_path, bootstrap = self._write_generated_sdk_fixture(generated)
        self.assertEqual(bootstrap["outputTreeSha256"], independent_tree_sha256(generated))
        self.assertEqual(list((generated / "SDK/build").rglob("*.c.o")), [])
        self.assertFalse((generated / "SDK/cpu/br35/tools/sdk.elf").exists()); self.assertFalse((generated / "SDK/cpu/br35/tools/sdk.map").exists())
        control = self.base / "build-control"; control.mkdir(); events = []

        independent_commands = synthetic_bootstrap_command_records(bootstrap["patch"])
        self.assertIsNot(independent_commands, bootstrap["commands"]); self.assertEqual(independent_commands, bootstrap["commands"])
        validated_bootstrap = validate_bootstrap(
            bootstrap_receipt_path=bootstrap_path, generated_sdk_root=generated,
            expected_source_commit=SOURCE_COMMIT, expected_commands=independent_commands,
        )
        self.assertEqual(validated_bootstrap, bootstrap)
        with self.assertRaises(TypeError):
            validate_bootstrap(bootstrap_receipt_path=bootstrap_path, generated_sdk_root=generated, expected_source_commit=SOURCE_COMMIT)
        changed_expected = deepcopy(independent_commands); changed_expected[0]["stdoutSha256"] = "0" * 64
        with self.assertRaises(ValueError):
            validate_bootstrap(
                bootstrap_receipt_path=bootstrap_path, generated_sdk_root=generated,
                expected_source_commit=SOURCE_COMMIT, expected_commands=changed_expected,
            )
        original_bootstrap_bytes = bootstrap_path.read_bytes(); changed_bootstrap = json.loads(original_bootstrap_bytes); changed_bootstrap["commands"][0]["stdoutSha256"] = "0" * 64
        bootstrap_path.write_bytes((json.dumps(changed_bootstrap, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii"))
        try:
            with self.assertRaises(ValueError):
                validate_bootstrap(
                    bootstrap_receipt_path=bootstrap_path, generated_sdk_root=generated,
                    expected_source_commit=SOURCE_COMMIT, expected_commands=independent_commands,
                )
        finally:
            bootstrap_path.write_bytes(original_bootstrap_bytes)

        replay_template = self.base / "independent-bootstrap-replay-template"; replay_template_receipt_path, _ = self._write_generated_sdk_fixture(replay_template)
        self.assertEqual(replay_template_receipt_path.read_bytes(), bootstrap_path.read_bytes()); self.assertNotEqual(replay_template.resolve(), generated.resolve())
        replay_control = self.base / "bootstrap-replay-control"; replay_control.mkdir(); replay_events = []; replay_runner = FakeBootstrapRawRunner(); replay_producer = FakeBootstrapProducer(replay_template, replay_control)
        with mock.patch.object(self.build, "_load_bootstrap_tool", return_value=replay_producer, create=True) as loader:
            replay_evidence = derive_bootstrap(
                generated_sdk_root=generated, bootstrap_receipt_path=bootstrap_path, control_root=replay_control,
                runner=replay_runner, event_sink=replay_events.append,
            )
        loader.assert_called_once_with(); self.assertEqual(len(replay_producer.calls), 1); self.assertEqual(len(replay_runner.calls), 31)
        self.assertEqual(replay_evidence, synthetic_bootstrap_replay_evidence(bootstrap, bootstrap_path.read_bytes()))
        self.assertEqual(replay_events, ["bootstrap-replay:started", "bootstrap-replay:receipt-validated", "bootstrap-replay:tree-validated", "bootstrap-replay:cleaned"])
        self.assertEqual(list(replay_control.iterdir()), [])
        producer_call = replay_producer.calls[0]
        self.assertEqual(set(producer_call), {
            "allowed_patch_paths", "expected_sdk_commit", "expected_sdk_tree", "expected_source_commit", "expected_source_tree",
            "git_tool", "output_root", "overlay_records", "patch_path", "repository_root", "runner", "sdk_root",
        })
        self.assertEqual((producer_call["repository_root"], producer_call["sdk_root"]), (ROOT, SDK_ROOT))
        self.assertEqual(
            (producer_call["expected_source_commit"], producer_call["expected_source_tree"], producer_call["expected_sdk_commit"], producer_call["expected_sdk_tree"]),
            (SOURCE_COMMIT, SOURCE_TREE, SDK_COMMIT, SDK_TREE),
        )
        self.assertEqual(list(producer_call["overlay_records"]), list(BOOTSTRAP_OVERLAY_RECORDS))
        self.assertEqual((producer_call["patch_path"], tuple(producer_call["allowed_patch_paths"])), (BOOTSTRAP_PATCH_PATH, tuple(sorted(BOOTSTRAP_PATCH_TARGETS))))
        self.assertEqual(producer_call["git_tool"], GIT_TOOL); self.assertIs(producer_call["runner"], replay_runner); self.assertTrue(callable(producer_call["runner"]))
        replay_output = Path(producer_call["output_root"]); self.assertIn(replay_control.resolve(), replay_output.resolve().parents); self.assertNotEqual(replay_output.resolve(), replay_control.resolve()); self.assertFalse(replay_output.exists())
        for expected, (role, argv, kwargs), (_, result) in zip(independent_commands, replay_runner.calls, replay_runner.results):
            self.assertEqual(role, expected["role"]); self.assertNotIn("${", json.dumps([argv, kwargs], default=str))
            self.assertEqual((result.returncode, hashlib.sha256(result.stdout).hexdigest().upper(), len(result.stdout), hashlib.sha256(result.stderr).hexdigest().upper(), len(result.stderr)), (expected["exitCode"], expected["stdoutSha256"], expected["stdoutSize"], expected["stderrSha256"], expected["stderrSize"]))
            self.assertEqual({key: kwargs[key] for key in ("check", "shell", "stdout", "stderr")}, {"check": False, "shell": False, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE})

        alternate_generated = self.base / "alternate-replay-generated"
        alternate_path, alternate = self._write_generated_sdk_fixture(
            alternate_generated,
            source_commit=ALTERNATE_SOURCE_COMMIT,
            source_commit_body=ALTERNATE_SOURCE_COMMIT_BODY,
            source_commit_epoch=ALTERNATE_SOURCE_DATE_EPOCH,
            source_commit_object_sha256=ALTERNATE_SOURCE_COMMIT_OBJECT_SHA256,
        )
        alternate_control = self.base / "alternate-replay-control"; alternate_control.mkdir()
        alternate_runner = FakeBootstrapRawRunner(
            source_commit=ALTERNATE_SOURCE_COMMIT,
            source_commit_body=ALTERNATE_SOURCE_COMMIT_BODY,
        )
        alternate_producer = FakeBootstrapProducer(
            replay_template,
            alternate_control,
            source_commit=ALTERNATE_SOURCE_COMMIT,
            source_commit_body=ALTERNATE_SOURCE_COMMIT_BODY,
            source_commit_epoch=ALTERNATE_SOURCE_DATE_EPOCH,
        )
        with mock.patch.object(self.build, "_load_bootstrap_tool", return_value=alternate_producer, create=True):
            alternate_evidence = derive_bootstrap(
                generated_sdk_root=alternate_generated, bootstrap_receipt_path=alternate_path, control_root=alternate_control,
                runner=alternate_runner,
            )
        self.assertEqual(alternate_evidence, synthetic_bootstrap_replay_evidence(alternate, alternate_path.read_bytes()))
        self.assertEqual(len(alternate_runner.calls), 31); self.assertEqual(len(alternate_producer.calls), 1); self.assertEqual(list(alternate_control.iterdir()), [])
        self.assertEqual(
            (alternate_producer.calls[0]["expected_source_commit"], alternate_producer.calls[0]["expected_source_tree"]),
            (ALTERNATE_SOURCE_COMMIT, SOURCE_TREE),
        )

        claimed_drift_path = self.base / "claimed-bootstrap-drift.json"; claimed_drift = deepcopy(bootstrap)
        claimed_drift["commands"][0]["stdoutSha256"] = "F" * 64
        claimed_drift_path.write_bytes((json.dumps(claimed_drift, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii"))
        claimed_control = self.base / "claimed-bootstrap-drift-control"; claimed_control.mkdir(); claimed_runner = FakeBootstrapRawRunner(); claimed_producer = FakeBootstrapProducer(replay_template, claimed_control)
        with mock.patch.object(self.build, "_load_bootstrap_tool", return_value=claimed_producer, create=True), self.assertRaises(ValueError):
            derive_bootstrap(
                generated_sdk_root=generated, bootstrap_receipt_path=claimed_drift_path, control_root=claimed_control,
                runner=claimed_runner,
            )
        self.assertEqual(len(claimed_runner.calls), 31); self.assertEqual(len(claimed_producer.calls), 1); self.assertEqual(list(claimed_control.iterdir()), [])
        for index, (label, producer_mode, runner_mode, target_role) in enumerate([
            *( (f"replay-{mode}", mode, "ok", "source-before-head") for mode in ("output-bytes", "output-mode", "output-extra", "receipt-source", "receipt-sdk", "receipt-git", "receipt-validation") ),
            ("runner-source-stdout", "ok", "stdout-drift", "source-before-head"),
            ("runner-sdk-stdout", "ok", "stdout-drift", "sdk-before-head"),
            ("runner-git-version", "ok", "stdout-drift", "git-version"),
            ("runner-stderr", "ok", "stderr-drift", "source-before-head"),
            ("runner-nonzero", "ok", "nonzero", "source-before-head"),
        ]):
            drift_control = self.base / f"bootstrap-replay-drift-control-{index}"; drift_control.mkdir(); drift_runner = FakeBootstrapRawRunner(mode=runner_mode, target_role=target_role); drift_producer = FakeBootstrapProducer(replay_template, drift_control, mode=producer_mode)
            with mock.patch.object(self.build, "_load_bootstrap_tool", return_value=drift_producer, create=True), self.subTest(bootstrap_replay=label), self.assertRaises(ValueError):
                derive_bootstrap(
                    generated_sdk_root=generated, bootstrap_receipt_path=bootstrap_path, control_root=drift_control,
                    runner=drift_runner, event_sink=None,
                )
            self.assertEqual(list(drift_control.iterdir()), [])
            if runner_mode in {"stdout-drift", "stderr-drift"}: self.assertEqual(len(drift_runner.calls), 31)

        self.assertEqual(getattr(self.build, "REFERENCE_ROOT", None), REFERENCE_ROOT)
        fixed_reference = self.base / "synthetic-fixed-reference"; fixed_reference.mkdir()
        fixed_reference_build = fixed_reference / "forbidden-build"; fixed_reference_build.mkdir()
        fixed_reference_generated = self.base / "fixed-reference-generated"; fixed_reference_bootstrap, _ = self._write_generated_sdk_fixture(fixed_reference_generated)
        fixed_reference_control = self.base / "fixed-reference-control"; fixed_reference_control.mkdir()
        fixed_reference_runner = FakeBuildRunner(elf, section_bytes); fixed_reference_versions = FakeVersionRunner()
        with mock.patch.object(self.build, "REFERENCE_ROOT", fixed_reference), mock.patch.object(self.build, "derive_expected_bootstrap_evidence", autospec=True) as derivation, self.assertRaises(ValueError):
            run_target_build(
                generated_sdk_root=fixed_reference_generated, bootstrap_receipt_path=fixed_reference_bootstrap,
                build_root=fixed_reference_build, control_root=fixed_reference_control,
                expected_source_commit=SOURCE_COMMIT, make_tool=MAKE_TOOL,
                runner=fixed_reference_runner, version_runner=fixed_reference_versions,
            )
        derivation.assert_not_called(); self.assertEqual(fixed_reference_versions.calls, []); self.assertEqual(fixed_reference_runner.calls, []); self.assertEqual(list(fixed_reference_build.iterdir()), [])

        replay_result_mutations = (
            ("receipt", lambda value: value.__setitem__("receiptSha256", "0" * 64)),
            ("commands", lambda value: value["commands"][0].__setitem__("stdoutSha256", "0" * 64)),
            ("tree", lambda value: value.__setitem__("outputTreeSha256", "0" * 64)),
            ("validations", lambda value: value["validations"].__setitem__("sdkStable", False)),
            ("receipt-validation-hash", lambda value: value["validation"].__setitem__("receiptSha256", "0" * 64)),
            ("commands-validation-hash", lambda value: value["validation"].__setitem__("commandsSha256", "0" * 64)),
            ("tree-validation-hash", lambda value: value["validation"].__setitem__("outputTreeSha256", "0" * 64)),
            ("validations-validation-hash", lambda value: value["validation"].__setitem__("validationsSha256", "0" * 64)),
        )
        for index, (label, mutate) in enumerate(replay_result_mutations):
            result_generated = self.base / f"replay-result-generated-{index}"; result_bootstrap_path, result_bootstrap = self._write_generated_sdk_fixture(result_generated)
            result_build = self.base / f"replay-result-build-{index}"; result_build.mkdir(); result_control = self.base / f"replay-result-control-{index}"; result_control.mkdir()
            replay_result = synthetic_bootstrap_replay_evidence(result_bootstrap, result_bootstrap_path.read_bytes()); mutate(replay_result)
            result_runner = FakeBuildRunner(elf, section_bytes); result_versions = FakeVersionRunner()
            with mock.patch.object(self.build, "derive_expected_bootstrap_evidence", autospec=True, return_value=replay_result) as derivation, self.subTest(replay_result=label), self.assertRaises(ValueError):
                run_target_build(
                    generated_sdk_root=result_generated, bootstrap_receipt_path=result_bootstrap_path, build_root=result_build,
                    control_root=result_control, expected_source_commit=SOURCE_COMMIT, make_tool=MAKE_TOOL,
                    runner=result_runner, version_runner=result_versions,
                )
            derivation.assert_called_once_with(
                generated_sdk_root=result_generated, bootstrap_receipt_path=result_bootstrap_path, control_root=result_control,
                runner=subprocess.run, event_sink=None,
            )
            self.assertEqual(result_versions.calls, []); self.assertEqual(result_runner.calls, []); self.assertEqual(list(result_build.iterdir()), [])

        def run_with_production_replay(*, replay_producer, replay_runner, **kwargs):
            with mock.patch.object(self.build, "_load_bootstrap_tool", return_value=replay_producer, create=True) as loader, mock.patch("subprocess.run", new=replay_runner):
                try:
                    return run_target_build(**kwargs)
                finally:
                    loader.assert_called_once_with()

        fake = FakeBuildRunner(elf, section_bytes, events=events); version_runner = FakeVersionRunner(events=events)
        build_replay_runner = FakeBootstrapRawRunner(); build_replay_producer = FakeBootstrapProducer(replay_template, control)
        with (
            mock.patch.object(self.build, "resolve_lto_runtime", wraps=resolve_lto_runtime) as resolve_runtime_spy,
            mock.patch.object(self.build, "snapshot_lto_runtime", wraps=snapshot_lto_runtime) as snapshot_runtime_spy,
            mock.patch.object(self.build, "reverify_lto_runtime", wraps=reverify_lto_runtime) as reverify_runtime_spy,
            mock.patch.object(self.build, "build_runtime_receipt", wraps=build_runtime_receipt) as build_runtime_spy,
            mock.patch.object(self.build, "validate_runtime_receipt", wraps=validate_runtime_receipt) as validate_runtime_spy,
            mock.patch.object(self.build, "validate_lto_wrapper_argv", wraps=validate_wrapper_argv) as validate_wrapper_spy,
        ):
            runtime_call_order = mock.Mock()
            runtime_call_order.attach_mock(resolve_runtime_spy, "resolve")
            runtime_call_order.attach_mock(snapshot_runtime_spy, "snapshot")
            runtime_call_order.attach_mock(build_runtime_spy, "build_receipt")
            runtime_call_order.attach_mock(validate_runtime_spy, "validate_receipt")
            runtime_call_order.attach_mock(validate_wrapper_spy, "validate_argv")
            runtime_call_order.attach_mock(reverify_runtime_spy, "reverify")
            receipt = run_with_production_replay(
                replay_producer=build_replay_producer, replay_runner=build_replay_runner,
                generated_sdk_root=generated, bootstrap_receipt_path=bootstrap_path, build_root=build_root, control_root=control,
                expected_source_commit=SOURCE_COMMIT, make_tool=MAKE_TOOL, runner=fake, version_runner=version_runner, event_sink=events.append,
            )
        resolve_runtime_spy.assert_called_once()
        snapshot_runtime_spy.assert_called_once()
        reverify_runtime_spy.assert_called_once()
        build_runtime_spy.assert_called_once()
        validate_runtime_spy.assert_called_once()
        validate_wrapper_spy.assert_called_once()
        runtime_names = [record[0] for record in runtime_call_order.mock_calls]
        self.assertLess(runtime_names.index("resolve"), runtime_names.index("snapshot"))
        self.assertLess(runtime_names.index("snapshot"), runtime_names.index("reverify"))
        self.assertLess(runtime_names.index("validate_argv"), runtime_names.index("reverify"))
        self.assertEqual(len(build_replay_runner.calls), 31); self.assertEqual(len(build_replay_producer.calls), 1)
        self.assertEqual(len(fake.calls), 11)
        self.assertEqual([Path(call[0][0]).name for call in fake.calls], ["make", *("objcopy" for _ in range(8)), "objdump", "nm"])
        tools = self.build.resolve_pinned_tools(self.toolchain_lock, make_tool=MAKE_TOOL)
        specs = build_command_specs(generated_sdk_root=generated, build_root=build_root, tools=tools)
        self.assertEqual([call[0] for call in fake.calls], [spec["argv"] for spec in specs])
        environment = self.build.build_environment(control, source_date_epoch=SOURCE_DATE_EPOCH, tool_root=TOOLCHAIN_ROOT)
        expected_kwargs = {"check": False, "cwd": build_root, "env": environment, "shell": False, "stderr": subprocess.PIPE, "stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE}
        for _, kwargs in fake.calls:
            self.assertEqual(kwargs, expected_kwargs)
        self.assertEqual([name for name, _ in version_runner.results], ["make", "objcopy", "objdump", "nm"])
        for _, kwargs in version_runner.calls:
            self.assertEqual(kwargs, expected_kwargs)
        roles = ["make", *[f"objcopy:{name}" for name, _ in SECTIONS], "objdump", "nm"]
        version_tools = ("make", "objcopy", "objdump", "nm")
        expected_events = [
            "roots:validated", "bootstrap-replay:started", "bootstrap-replay:receipt-validated",
            "bootstrap-replay:tree-validated", "bootstrap-replay:cleaned", "bootstrap:reopened",
            "environment:closed", "tools:resolved", "runtime:resolved", "runtime:snapshotted", "runtime:argv-validated",
            "runtime:receipt-built", "runtime:receipt-validated",
        ]
        expected_events += [f"tool:{name}:resolved-rehashed" for name in version_tools]
        for name in version_tools: expected_events += [f"tool:{name}:version-rehashed", f"version:{name}"]
        for role in roles:
            tool = role.split(":", 1)[0]
            if role == "make": expected_events += ["runtime:reverified-before-make"]
            expected_events += [f"tool:{tool}:runner-rehashed", f"inputs:{role}:rehashed", f"runner:{role}", f"outputs:{role}:validated"]
        expected_events += ["bootstrap:rehashed", "provenance:rehashed", "app:concatenated", "receipt:committed"]
        self.assertEqual(events, expected_events)
        expected_commands = []
        for spec, (role, result) in zip(specs, fake.results):
            tool = role.split(":", 1)[0]
            self.assertEqual(role, spec["role"])
            expected_commands.append(build_raw_record({
                "argv": list(result.args), "exitCode": result.returncode, "role": role,
                "stderrSha256": hashlib.sha256(result.stderr).hexdigest().upper(),
                "stdoutSha256": hashlib.sha256(result.stdout).hexdigest().upper(),
                "toolSha256": tools[tool]["sha256"], "toolVersion": BUILD_TOOL_VERSIONS[tool],
            }, result))
        expected_probes = []
        for name, result in version_runner.results:
            expected_probes.append(build_raw_record({
                "argv": list(result.args), "exitCode": result.returncode, "stderrSha256": hashlib.sha256(result.stderr).hexdigest().upper(),
                "stdoutSha256": hashlib.sha256(result.stdout).hexdigest().upper(), "tool": name,
                "toolSha256": tools[name]["sha256"], "version": BUILD_TOOL_VERSIONS[name],
            }, result))
        self.assertEqual(receipt["commands"], expected_commands); self.assertEqual(receipt["versionProbes"], expected_probes)
        self.assertEqual(receipt["environment"], normalized_build_environment())
        self.assertEqual(receipt["resourceLimits"], BUILD_RESOURCE_LIMITS)
        self.assertEqual(receipt["validations"], BUILD_VALIDATIONS)
        self.assertEqual(receipt["runtime"], expected_runtime_receipt())
        self.assertEqual(receipt["bootstrapValidation"], replay_evidence["validation"])
        expected_sections = [{**record, "sha256": hashlib.sha256(section_bytes[str(record["name"])]).hexdigest().upper()} for record in elf_sections]
        expected_section_outputs = [{"filename": filename, "section": section, "sha256": hashlib.sha256(section_bytes[section]).hexdigest().upper(), "size": len(section_bytes[section])} for section, filename in SECTIONS]
        expected_app = b"".join(section_bytes[section] for section, _ in SECTIONS)
        self.assertEqual(receipt["sections"], expected_sections); self.assertEqual(receipt["sectionOutputs"], expected_section_outputs)
        self.assertEqual(receipt["app"], {"filename": "app.bin", "sha256": hashlib.sha256(expected_app).hexdigest().upper(), "size": len(expected_app)})
        self.assertEqual(receipt["symbols"], [{"address": "0x0C000100", "kind": "T", "name": "bt_ble_init"}])
        self.assertEqual(receipt["mapProvenance"], {"bt_ble_init": {"address": "0x0C000100", "object": OBJECTS[2], "strength": "STRONG"}})
        self.assertEqual(
            sorted(path.relative_to(generated / "SDK/build").as_posix() for path in (generated / "SDK/build").rglob("*.c.o")),
            sorted(OBJECTS),
        )
        for relative in OBJECTS: self.assertEqual((generated / "SDK/build" / relative).read_bytes(), ("object:" + relative + "\n").encode("ascii"))
        self.assertEqual((generated / "SDK/cpu/br35/tools/sdk.map").read_text(encoding="ascii"), ".text.bt_ble_init 0x0C000100 0x10 objs/apps/watch/e87/e87_stage0_ble.c.o\n                0x0C000100 bt_ble_init\n")
        self.assertEqual((receipt["sourceCommit"], receipt["sourceDateEpoch"], receipt["app"]["filename"]), (SOURCE_COMMIT, bootstrap["sourceCommitEpoch"], "app.bin"))

        late_generated = self.base / "late-runtime-generated"
        late_bootstrap_path, _ = self._write_generated_sdk_fixture(late_generated)
        late_build = self.base / "late-runtime-build"; late_build.mkdir()
        late_control = self.base / "late-runtime-control"; late_control.mkdir()
        late_events = []
        late_runner = FakeBuildRunner(elf, section_bytes, events=late_events)
        late_versions = FakeVersionRunner(events=late_events)
        late_replay_runner = FakeBootstrapRawRunner()
        late_replay_producer = FakeBootstrapProducer(replay_template, late_control)
        late_runtime_armed = []

        class LateRuntimeEvents(list):
            def append(inner_self, event):
                super().append(event)
                if event == "version:nm": late_runtime_armed.append("runtime-aba-after-version-probes")

        late_events = LateRuntimeEvents()
        late_runner.events = late_events
        late_versions.events = late_events

        def reject_late_runtime(*args, **kwargs):
            self.assertEqual(late_runtime_armed, ["runtime-aba-after-version-probes"])
            raise ValueError("runtime ABA drift before Make")

        with mock.patch.object(self.build, "reverify_lto_runtime", autospec=True, side_effect=reject_late_runtime) as late_reverify, self.assertRaisesRegex(ValueError, "runtime ABA"):
            run_with_production_replay(
                replay_producer=late_replay_producer, replay_runner=late_replay_runner,
                generated_sdk_root=late_generated, bootstrap_receipt_path=late_bootstrap_path,
                build_root=late_build, control_root=late_control,
                expected_source_commit=SOURCE_COMMIT, make_tool=MAKE_TOOL,
                runner=late_runner, version_runner=late_versions, event_sink=late_events.append,
            )
        late_reverify.assert_called_once()
        self.assertEqual(len(late_versions.calls), 4)
        self.assertEqual(late_runner.calls, [])
        self.assertEqual(late_events[-1], "runtime:reverified-before-make")
        self.assertFalse((late_build / "build-receipt.json").exists())
        self.assertEqual(list(late_build.iterdir()), [])

        for index, forbidden in enumerate((
            "--extra-arguments-from-file", "--extra-arguments-from-file=attacker",
            "--output-version-info", "--output-version-info=attacker",
        )):
            forbidden_generated = self.base / f"forbidden-wrapper-generated-{index}"
            forbidden_bootstrap_path, forbidden_bootstrap = self._write_generated_sdk_fixture(forbidden_generated)
            link_makefile = forbidden_generated / "SDK/build/Makefile.mk"
            link_makefile.write_bytes(LINK_MAKEFILE + f"LFLAGS += {forbidden}\n".encode("ascii"))
            forbidden_bootstrap["outputTreeSha256"] = independent_tree_sha256(forbidden_generated)
            forbidden_bootstrap_path.write_bytes((json.dumps(forbidden_bootstrap, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii"))
            forbidden_replay = synthetic_bootstrap_replay_evidence(forbidden_bootstrap, forbidden_bootstrap_path.read_bytes())
            forbidden_build = self.base / f"forbidden-wrapper-build-{index}"; forbidden_build.mkdir()
            forbidden_control = self.base / f"forbidden-wrapper-control-{index}"; forbidden_control.mkdir()
            forbidden_runner = FakeBuildRunner(elf, section_bytes); forbidden_versions = FakeVersionRunner()
            with (
                mock.patch.object(self.build, "derive_expected_bootstrap_evidence", autospec=True, return_value=forbidden_replay),
                self.subTest(integrated_forbidden_wrapper_arg=forbidden),
                self.assertRaisesRegex(ValueError, "(?i)forbidden"),
            ):
                run_target_build(
                    generated_sdk_root=forbidden_generated, bootstrap_receipt_path=forbidden_bootstrap_path,
                    build_root=forbidden_build, control_root=forbidden_control,
                    expected_source_commit=SOURCE_COMMIT, make_tool=MAKE_TOOL,
                    runner=forbidden_runner, version_runner=forbidden_versions,
                )
            self.assertEqual(forbidden_runner.calls, [])
            self.assertEqual(forbidden_versions.calls, [])
        self.assertEqual(receipt["bootstrap"], bootstrap)
        self.assertEqual(int(receipt["target"]["codeEnd"], 16), independent_elf32_load_end(elf))
        receipt_bytes = (build_root / "build-receipt.json").read_bytes()
        self.assertEqual(receipt_bytes, (json.dumps(receipt, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii"))
        self.assertEqual(set(path.name for path in build_root.iterdir()), {"app.bin", "bootstrap-receipt.json", "build-receipt.json", "sdk.elf", *[filename for _, filename in SECTIONS]})
        self.assertEqual((build_root / "bootstrap-receipt.json").read_bytes(), bootstrap_path.read_bytes())
        self.assertEqual(receipt["bootstrapReceipt"]["filename"], "bootstrap-receipt.json")
        parser = parser_factory(); self.assertFalse(parser.allow_abbrev)
        subparser_actions = [action for action in parser._actions if isinstance(action, argparse._SubParsersAction)]
        self.assertEqual([action for action in parser._actions if action.dest != "help"], subparser_actions)
        self.assertEqual(len(subparser_actions), 1); self.assertEqual(subparser_actions[0].dest, "command"); self.assertTrue(subparser_actions[0].required); self.assertEqual(set(subparser_actions[0].choices), {"run"})
        run_parser = subparser_actions[0].choices["run"]; self.assertFalse(run_parser.allow_abbrev)
        run_actions = {action.dest: action for action in run_parser._actions if action.dest != "help"}
        self.assertEqual({dest: tuple(action.option_strings) for dest, action in run_actions.items()}, {
            "bootstrap_receipt": ("--bootstrap-receipt",), "build_root": ("--build-root",), "control_root": ("--control-root",),
            "expected_source_commit": ("--expected-source-commit",), "generated_sdk_root": ("--generated-sdk-root",),
        })
        for dest, action in run_actions.items():
            self.assertTrue(action.required); self.assertIs(action.type, str if dest == "expected_source_commit" else Path)
        parsed = parser.parse_args(["run", "--generated-sdk-root", str(generated), "--bootstrap-receipt", str(bootstrap_path), "--build-root", str(build_root), "--control-root", str(control), "--expected-source-commit", SOURCE_COMMIT])
        self.assertEqual(vars(parsed), {"bootstrap_receipt": bootstrap_path, "build_root": build_root, "command": "run", "control_root": control, "expected_source_commit": SOURCE_COMMIT, "generated_sdk_root": generated})
        for forbidden in ("--tool-dir", "--objcopy", "--cpu", "--entry", "--make", "--source-commit", "--source-date-epoch"):
            with self.subTest(forbidden=forbidden), self.assertRaises(SystemExit):
                parser.parse_args(["run", "--generated-sdk-root", str(generated), "--bootstrap-receipt", str(bootstrap_path), "--build-root", str(build_root), "--control-root", str(control), "--expected-source-commit", SOURCE_COMMIT, forbidden, "x"])
        cli_generated = self.base / "cli-generated"; cli_build = self.base / "cli-build"; (cli_generated / "SDK").mkdir(parents=True); cli_build.mkdir()
        cli_bootstrap = self.base / "cli-bootstrap-receipt.json"; cli_bootstrap.write_bytes(bootstrap_path.read_bytes()); cli_control = self.base / "cli-control"; cli_control.mkdir()
        cli_receipt = {"schema": "e87-stage0-build-receipt-v1", "sourceCommit": SOURCE_COMMIT, "sourceDateEpoch": SOURCE_DATE_EPOCH}
        cli_argv = ["run", "--generated-sdk-root", str(cli_generated), "--bootstrap-receipt", str(cli_bootstrap), "--build-root", str(cli_build), "--control-root", str(cli_control), "--expected-source-commit", SOURCE_COMMIT]
        with mock.patch.object(self.build, "build_parser", wraps=self.build.build_parser) as parser_builder, mock.patch.object(self.build, "run_target_build", autospec=True, return_value=cli_receipt) as dispatch:
            self.assertEqual(self.build.main(cli_argv), 0)
        parser_builder.assert_called_once_with()
        dispatch.assert_called_once_with(generated_sdk_root=cli_generated, bootstrap_receipt_path=cli_bootstrap, build_root=cli_build, control_root=cli_control, expected_source_commit=SOURCE_COMMIT)
        receipt_path = cli_build / "build-receipt.json"
        self.assertEqual(receipt_path.read_bytes(), (json.dumps(cli_receipt, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii"))

        failure_derivation_patch = mock.patch.object(
            self.build,
            "derive_expected_bootstrap_evidence",
            autospec=True,
            side_effect=self._independent_bootstrap_derivation,
        )
        failure_derivation_patch.start(); self.addCleanup(failure_derivation_patch.stop)
        drift_generated = self.base / "drift-generated"; drift_bootstrap, _ = self._write_generated_sdk_fixture(drift_generated); drift_build = self.base / "drift-build"; drift_build.mkdir(); drift_control = self.base / "drift-control"; drift_control.mkdir()
        with self.assertRaises(ValueError):
            run_target_build(generated_sdk_root=drift_generated, bootstrap_receipt_path=drift_bootstrap, build_root=drift_build, control_root=drift_control, expected_source_commit=SOURCE_COMMIT, make_tool=MAKE_TOOL, runner=FakeBuildRunner(elf, section_bytes, mutate_provenance=True), version_runner=FakeVersionRunner())
        with self.assertRaises(TypeError):
            run_target_build(generated_sdk_root=drift_generated, bootstrap_receipt_path=drift_bootstrap, build_root=drift_build, control_root=drift_control, expected_source_commit=SOURCE_COMMIT, source_date_epoch=SOURCE_DATE_EPOCH, make_tool=MAKE_TOOL, runner=FakeBuildRunner(elf, section_bytes), version_runner=FakeVersionRunner())

        failure_modes = [("nonzero", role) for role in roles]
        failure_modes += [(mode, f"objcopy:{section}") for mode in ("missing-section", "empty-section", "extra-section", "wrong-section") for section, _ in SECTIONS]
        failure_modes += [
            ("wrong-objdump", "objdump"), ("wrong-nm", "nm"), ("map-drift", "make"),
            ("missing-object", "make"), ("extra-object", "make"), ("missing-map", "make"),
        ]
        for index, (mode, role) in enumerate(failure_modes):
            case_generated = self.base / f"failure-generated-{index}"; case_bootstrap, _ = self._write_generated_sdk_fixture(case_generated)
            case_build = self.base / f"failure-build-{index}"; case_build.mkdir(); case_control = self.base / f"failure-control-{index}"; case_control.mkdir()
            with self.subTest(mode=mode, role=role), self.assertRaises(ValueError):
                case_runner = FakeBuildRunner(elf, section_bytes, mode=mode, target_role=role)
                run_target_build(generated_sdk_root=case_generated, bootstrap_receipt_path=case_bootstrap, build_root=case_build, control_root=case_control, expected_source_commit=SOURCE_COMMIT, make_tool=MAKE_TOOL, runner=case_runner, version_runner=FakeVersionRunner())
            if mode in {"wrong-section", "wrong-objdump", "wrong-nm", "map-drift", "missing-object", "extra-object", "missing-map"}:
                self.assertTrue(case_runner.results); self.assertTrue(all(result.returncode == 0 for _, result in case_runner.results))
            self.assertFalse((case_build / "build-receipt.json").exists())
        failure_derivation_patch.stop()
        for index, relative in enumerate((OBJECTS[0], "SDK/cpu/br35/tools/sdk.map")):
            stale_generated = self.base / f"stale-generated-{index}"; stale_bootstrap, stale_receipt = self._write_generated_sdk_fixture(stale_generated)
            stale_path = stale_generated / ((Path("SDK/build") / relative) if relative in OBJECTS else Path(relative))
            stale_path.parent.mkdir(parents=True, exist_ok=True); stale_path.write_bytes(b"stale pre-build output\n")
            self.assertNotEqual(independent_tree_sha256(stale_generated), stale_receipt["outputTreeSha256"])
            stale_build = self.base / f"stale-build-{index}"; stale_build.mkdir(); stale_control = self.base / f"stale-control-{index}"; stale_control.mkdir(); stale_runner = FakeBuildRunner(elf, section_bytes); stale_versions = FakeVersionRunner()
            stale_replay_runner = FakeBootstrapRawRunner(); stale_replay_producer = FakeBootstrapProducer(replay_template, stale_control)
            with self.subTest(stale_output=relative), self.assertRaises(ValueError):
                run_with_production_replay(
                    replay_producer=stale_replay_producer, replay_runner=stale_replay_runner,
                    generated_sdk_root=stale_generated, bootstrap_receipt_path=stale_bootstrap, build_root=stale_build,
                    control_root=stale_control, expected_source_commit=SOURCE_COMMIT, make_tool=MAKE_TOOL,
                    runner=stale_runner, version_runner=stale_versions,
                )
            self.assertEqual(len(stale_replay_runner.calls), 31); self.assertEqual(len(stale_replay_producer.calls), 1)
            self.assertEqual(stale_versions.calls, []); self.assertEqual(stale_runner.calls, []); self.assertEqual(list(stale_build.iterdir()), []); self.assertEqual(list(stale_control.iterdir()), [])
        larger_sections = dict(section_bytes); larger_sections[SECTIONS[-1][0]] = b"L" * 0x30
        larger_elf, _, larger_sections = make_elf32_fixture(larger_sections)
        larger_generated = self.base / "larger-generated"; larger_bootstrap, _ = self._write_generated_sdk_fixture(larger_generated)
        larger_build = self.base / "larger-build"; larger_build.mkdir(); larger_control = self.base / "larger-control"; larger_control.mkdir()
        larger_replay_runner = FakeBootstrapRawRunner(); larger_replay_producer = FakeBootstrapProducer(replay_template, larger_control)
        larger_receipt = run_with_production_replay(
            replay_producer=larger_replay_producer, replay_runner=larger_replay_runner,
            generated_sdk_root=larger_generated, bootstrap_receipt_path=larger_bootstrap, build_root=larger_build,
            control_root=larger_control, expected_source_commit=SOURCE_COMMIT, make_tool=MAKE_TOOL,
            runner=FakeBuildRunner(larger_elf, larger_sections), version_runner=FakeVersionRunner(),
        )
        self.assertEqual(len(larger_replay_runner.calls), 31); self.assertEqual(len(larger_replay_producer.calls), 1)
        self.assertEqual(int(larger_receipt["target"]["codeEnd"], 16), independent_elf32_load_end(larger_elf))
        self.assertNotEqual(larger_receipt["target"]["codeEnd"], receipt["target"]["codeEnd"])
        epoch_generated = self.base / "alternate-epoch-generated"
        epoch_bootstrap, alternate_bootstrap = self._write_generated_sdk_fixture(
            epoch_generated, source_commit=ALTERNATE_SOURCE_COMMIT, source_commit_body=ALTERNATE_SOURCE_COMMIT_BODY, source_commit_epoch=ALTERNATE_SOURCE_DATE_EPOCH,
            source_commit_object_sha256=ALTERNATE_SOURCE_COMMIT_OBJECT_SHA256,
        )
        epoch_build = self.base / "alternate-epoch-build"; epoch_build.mkdir(); epoch_control = self.base / "alternate-epoch-control"; epoch_control.mkdir()
        epoch_runner = FakeBuildRunner(elf, section_bytes)
        epoch_replay_runner = FakeBootstrapRawRunner(source_commit=ALTERNATE_SOURCE_COMMIT, source_commit_body=ALTERNATE_SOURCE_COMMIT_BODY)
        epoch_replay_producer = FakeBootstrapProducer(
            replay_template, epoch_control, source_commit=ALTERNATE_SOURCE_COMMIT,
            source_commit_body=ALTERNATE_SOURCE_COMMIT_BODY, source_commit_epoch=ALTERNATE_SOURCE_DATE_EPOCH,
        )
        epoch_receipt = run_with_production_replay(
            replay_producer=epoch_replay_producer, replay_runner=epoch_replay_runner,
            generated_sdk_root=epoch_generated, bootstrap_receipt_path=epoch_bootstrap, build_root=epoch_build,
            control_root=epoch_control, expected_source_commit=ALTERNATE_SOURCE_COMMIT, make_tool=MAKE_TOOL,
            runner=epoch_runner, version_runner=FakeVersionRunner(),
        )
        self.assertEqual(len(epoch_replay_runner.calls), 31); self.assertEqual(len(epoch_replay_producer.calls), 1)
        self.assertEqual((epoch_receipt["sourceCommit"], epoch_receipt["sourceDateEpoch"], epoch_receipt["bootstrap"]), (ALTERNATE_SOURCE_COMMIT, ALTERNATE_SOURCE_DATE_EPOCH, alternate_bootstrap))
        alternate_commands = {record["role"]: record for record in alternate_bootstrap["commands"]}
        for phase in ("before", "after"):
            self.assertEqual(alternate_commands[f"source-{phase}-head"]["stdoutSha256"], hashlib.sha256((ALTERNATE_SOURCE_COMMIT + "\n").encode("ascii")).hexdigest().upper())
            self.assertEqual(alternate_commands[f"source-{phase}-tree"]["stdoutSha256"], hashlib.sha256((SOURCE_TREE + "\n").encode("ascii")).hexdigest().upper())
            self.assertEqual(alternate_commands[f"source-{phase}-commit-object"]["stdoutSha256"], ALTERNATE_SOURCE_COMMIT_OBJECT_SHA256)
            self.assertEqual(alternate_commands[f"source-{phase}-commit-object"]["stdoutSize"], len(ALTERNATE_SOURCE_COMMIT_BODY))
        self.assertTrue(all(call[1]["env"]["SOURCE_DATE_EPOCH"] == str(ALTERNATE_SOURCE_DATE_EPOCH) for call in epoch_runner.calls))

        mode_variants = []
        for executable in (False, True):
            label = "executable" if executable else "regular"
            mode_generated = self.base / f"mode-{label}-generated"
            mode_bootstrap_path, mode_bootstrap = self._write_generated_sdk_fixture(mode_generated, mode_probe_executable=executable)
            mode_probe = mode_generated / "SDK/archive-mode-probe.sh"
            self.assertEqual(bool(mode_probe.stat().st_mode & 0o111), executable)
            self.assertEqual(mode_bootstrap["outputTreeSha256"], independent_tree_sha256(mode_generated))
            mode_replay_template = self.base / f"mode-{label}-replay-template"; self._write_generated_sdk_fixture(mode_replay_template, mode_probe_executable=executable)
            mode_direct_control = self.base / f"mode-{label}-direct-replay-control"; mode_direct_control.mkdir()
            mode_direct_runner = FakeBootstrapRawRunner(); mode_direct_producer = FakeBootstrapProducer(mode_replay_template, mode_direct_control)
            with mock.patch.object(self.build, "_load_bootstrap_tool", return_value=mode_direct_producer, create=True):
                mode_derived_evidence = derive_bootstrap(
                    generated_sdk_root=mode_generated, bootstrap_receipt_path=mode_bootstrap_path,
                    control_root=mode_direct_control, runner=mode_direct_runner,
                )
            self.assertEqual(len(mode_direct_runner.calls), 31); self.assertEqual(len(mode_direct_producer.calls), 1); self.assertEqual(list(mode_direct_control.iterdir()), [])
            mode_build = self.base / f"mode-{label}-build"; mode_build.mkdir(); mode_control = self.base / f"mode-{label}-control"; mode_control.mkdir()
            mode_build_replay_runner = FakeBootstrapRawRunner(); mode_build_replay_producer = FakeBootstrapProducer(mode_replay_template, mode_control)
            integration_derived_validation = []; integration_derived_snapshot = []; integration_forwarded = []
            production_derivation = self.build.derive_expected_bootstrap_evidence
            production_build_receipt = self.build.build_receipt

            def capture_integration_derivation(*args, **kwargs):
                value = production_derivation(*args, **kwargs)
                integration_derived_validation.append(value["validation"])
                integration_derived_snapshot.append(deepcopy(value["validation"]))
                return value

            def capture_integration_build_receipt(*args, **kwargs):
                validation = kwargs.get("bootstrap_validation")
                self.assertEqual((len(integration_derived_validation), len(integration_derived_snapshot)), (1, 1))
                self.assertIs(validation, integration_derived_validation[0])
                self.assertEqual(validation, integration_derived_snapshot[0])
                integration_forwarded.append(validation)
                result = production_build_receipt(*args, **kwargs)
                self.assertIs(integration_forwarded[0], integration_derived_validation[0])
                self.assertEqual(integration_derived_validation[0], integration_derived_snapshot[0])
                return result

            with mock.patch.object(self.build, "derive_expected_bootstrap_evidence", autospec=True, side_effect=capture_integration_derivation), mock.patch.object(self.build, "build_receipt", autospec=True, side_effect=capture_integration_build_receipt):
                mode_receipt = run_with_production_replay(
                    replay_producer=mode_build_replay_producer, replay_runner=mode_build_replay_runner,
                    generated_sdk_root=mode_generated, bootstrap_receipt_path=mode_bootstrap_path, build_root=mode_build,
                    control_root=mode_control, expected_source_commit=SOURCE_COMMIT, make_tool=MAKE_TOOL,
                    runner=FakeBuildRunner(elf, section_bytes), version_runner=FakeVersionRunner(),
                )
            self.assertEqual(len(mode_build_replay_runner.calls), 31); self.assertEqual(len(mode_build_replay_producer.calls), 1)
            self.assertEqual((len(integration_derived_validation), len(integration_derived_snapshot), len(integration_forwarded)), (1, 1, 1))
            self.assertIs(integration_forwarded[0], integration_derived_validation[0])
            self.assertEqual(integration_derived_validation[0], integration_derived_snapshot[0])
            self.assertEqual(integration_forwarded[0], integration_derived_snapshot[0])
            self.assertEqual(mode_receipt["bootstrapValidation"], mode_derived_evidence["validation"])
            self.assertEqual(mode_receipt["bootstrap"]["outputTreeSha256"], mode_bootstrap["outputTreeSha256"])
            mode_variants.append((executable, mode_bootstrap))
        self.assertNotEqual(mode_variants[0][1]["outputTreeSha256"], mode_variants[1][1]["outputTreeSha256"])
        for _, receipt_variant in mode_variants:
            normalized = deepcopy(receipt_variant); normalized.pop("outputTreeSha256")
            self.assertEqual(normalized, {key: value for key, value in mode_variants[0][1].items() if key != "outputTreeSha256"})
        for executable, wrong_receipt in ((False, mode_variants[1][1]), (True, mode_variants[0][1])):
            label = "executable" if executable else "regular"
            swap_generated = self.base / f"mode-swap-{label}-generated"
            swap_bootstrap_path, swap_bootstrap = self._write_generated_sdk_fixture(swap_generated, mode_probe_executable=executable)
            swap_bootstrap["outputTreeSha256"] = wrong_receipt["outputTreeSha256"]
            swap_bootstrap_path.write_bytes((json.dumps(swap_bootstrap, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii"))
            swap_build = self.base / f"mode-swap-{label}-build"; swap_build.mkdir(); swap_control = self.base / f"mode-swap-{label}-control"; swap_control.mkdir()
            swap_runner = FakeBuildRunner(elf, section_bytes); swap_versions = FakeVersionRunner()
            swap_replay_template = self.base / f"mode-swap-{label}-replay-template"; self._write_generated_sdk_fixture(swap_replay_template, mode_probe_executable=executable)
            swap_replay_runner = FakeBootstrapRawRunner(); swap_replay_producer = FakeBootstrapProducer(swap_replay_template, swap_control)
            with self.subTest(mode_receipt_swap=label), self.assertRaises(ValueError):
                run_with_production_replay(
                    replay_producer=swap_replay_producer, replay_runner=swap_replay_runner,
                    generated_sdk_root=swap_generated, bootstrap_receipt_path=swap_bootstrap_path, build_root=swap_build,
                    control_root=swap_control, expected_source_commit=SOURCE_COMMIT, make_tool=MAKE_TOOL,
                    runner=swap_runner, version_runner=swap_versions,
                )
            self.assertEqual(len(swap_replay_runner.calls), 31); self.assertEqual(len(swap_replay_producer.calls), 1)
            self.assertEqual(swap_versions.calls, []); self.assertEqual(swap_runner.calls, []); self.assertEqual(list(swap_build.iterdir()), []); self.assertEqual(list(swap_control.iterdir()), [])

    def test_target_build_rejects_bootstrap_generated_and_elf_use_window_one_way_and_aba_before_receipt(self):
        run_target_build = require_api(self, self.build, "run_target_build")
        require_api(self, self.build, "derive_expected_bootstrap_evidence")
        derive_patch = mock.patch.object(self.build, "derive_expected_bootstrap_evidence", autospec=True, side_effect=self._independent_bootstrap_derivation)
        derive_patch.start(); self.addCleanup(derive_patch.stop)
        elf, _, section_bytes = make_elf32_fixture()
        generated = self.base / "build-toctou-generated"; (generated / "SDK/cpu/br35/tools").mkdir(parents=True)
        bootstrap_path, _ = self._write_generated_sdk_fixture(generated)
        produced_elf = generated / "SDK/cpu/br35/tools/sdk.elf"
        produced_parent_mode = produced_elf.parent.stat().st_mode & 0o777

        def clean_generated_products() -> None:
            for relative in ("SDK/build/objs", "SDK/cpu"):
                target = generated / relative
                if target.exists(): shutil.rmtree(target)
            produced_elf.parent.mkdir(parents=True, exist_ok=True)
            produced_elf.parent.chmod(produced_parent_mode)

        targets = (
            ("bootstrap", bootstrap_path, "version:nm", 0),
            ("generated-input", generated / BOOTSTRAP_OVERLAYS[0], "version:nm", 0),
            ("produced-elf", produced_elf, "outputs:make:validated", 1),
        )
        for target_label, target_path, trigger, expected_calls in targets:
            for mode in ("bytes-one-way", "bytes-aba", "symlink-one-way", "symlink-aba"):
                build_root = self.base / f"build-toctou-out-{target_label}-{mode}"; build_root.mkdir()
                control_root = self.base / f"build-toctou-control-{target_label}-{mode}"; control_root.mkdir()
                if target_path.exists() or target_path.is_symlink():
                    original = target_path.read_bytes(); original_mode = target_path.stat().st_mode & 0o777
                else:
                    original = elf; original_mode = 0o644
                parent_mode = target_path.parent.stat().st_mode & 0o777
                mutation_tokens = []

                class MutatingEvents(list):
                    def append(inner_self, event):
                        super().append(event)
                        if event == trigger and not mutation_tokens:
                            mutation_tokens.extend(self._mutate_use_window_path(target_path, mode))

                events = MutatingEvents(); build_runner = FakeBuildRunner(elf, section_bytes, events=events); version_runner = FakeVersionRunner(events=events)
                try:
                    with self.subTest(target=target_label, mutation=mode), self.assertRaises(ValueError):
                        run_target_build(
                            generated_sdk_root=generated, bootstrap_receipt_path=bootstrap_path, build_root=build_root,
                            control_root=control_root, expected_source_commit=SOURCE_COMMIT, make_tool=MAKE_TOOL,
                            runner=build_runner, version_runner=version_runner, event_sink=events.append,
                        )
                    self.assertEqual(len(mutation_tokens), 2); self.assertNotEqual(mutation_tokens[0], mutation_tokens[1])
                    self.assertEqual(len(build_runner.calls), expected_calls)
                    self.assertNotIn("receipt:committed", events)
                    self.assertFalse((build_root / "build-receipt.json").exists()); self.assertEqual(list(build_root.iterdir()), [])
                    if mode.endswith("aba"):
                        self.assertFalse(target_path.is_symlink()); self.assertEqual(target_path.read_bytes(), original)
                finally:
                    target_path.parent.chmod(target_path.parent.stat().st_mode | 0o700)
                    if target_path.is_symlink(): target_path.unlink()
                    if target_label == "produced-elf":
                        if target_path.exists(): target_path.unlink()
                    else:
                        target_path.write_bytes(original); target_path.chmod(original_mode)
                    target_path.parent.chmod(parent_mode)
                    clean_generated_products()
        copied_tools = self._copy_invoked_build_tools("build-toctou-tools")
        for tool_name in ("make", "objcopy", "objdump", "nm"):
            tool_path = Path(str(copied_tools[tool_name]["path"]))
            for mode in ("bytes-one-way", "bytes-aba", "symlink-one-way", "symlink-aba"):
                build_root = self.base / f"build-resolve-probe-out-{tool_name}-{mode}"; build_root.mkdir()
                control_root = self.base / f"build-resolve-probe-control-{tool_name}-{mode}"; control_root.mkdir()
                original = tool_path.read_bytes(); original_mode = tool_path.stat().st_mode & 0o777; parent_mode = tool_path.parent.stat().st_mode & 0o777; mutation_tokens = []

                class ResolveProbeEvents(list):
                    def append(inner_self, event):
                        super().append(event)
                        if event == "tools:resolved" and not mutation_tokens:
                            mutation_tokens.extend(self._mutate_use_window_path(tool_path, mode))

                events = ResolveProbeEvents(); build_runner = FakeBuildRunner(elf, section_bytes, events=events); version_runner = FakeVersionRunner(events=events)
                try:
                    with mock.patch.object(self.build, "resolve_pinned_tools", autospec=True, return_value=copied_tools), self.subTest(resolve_to_probe=(tool_name, mode)), self.assertRaises(ValueError):
                        run_target_build(
                            generated_sdk_root=generated, bootstrap_receipt_path=bootstrap_path, build_root=build_root,
                            control_root=control_root, expected_source_commit=SOURCE_COMMIT, make_tool=copied_tools["make"],
                            runner=build_runner, version_runner=version_runner, event_sink=events.append,
                        )
                    self.assertEqual(len(mutation_tokens), 2); self.assertNotEqual(mutation_tokens[0], mutation_tokens[1])
                    self.assertEqual(version_runner.calls, []); self.assertEqual(build_runner.calls, [])
                    self.assertNotIn("receipt:committed", events); self.assertEqual(list(build_root.iterdir()), [])
                    if mode.endswith("aba"):
                        self.assertFalse(tool_path.is_symlink()); self.assertEqual(tool_path.read_bytes(), original)
                finally:
                    tool_path.parent.chmod(tool_path.parent.stat().st_mode | 0o700)
                    if tool_path.is_symlink(): tool_path.unlink()
                    tool_path.write_bytes(original); tool_path.chmod(original_mode); tool_path.parent.chmod(parent_mode)
                    clean_generated_products()
        for tool_name, expected_calls in (("make", 0), ("objcopy", 1), ("objdump", 9), ("nm", 10)):
            tool_path = Path(str(copied_tools[tool_name]["path"]))
            for mode in ("bytes-one-way", "bytes-aba", "symlink-one-way", "symlink-aba"):
                build_root = self.base / f"build-tool-toctou-out-{tool_name}-{mode}"; build_root.mkdir()
                control_root = self.base / f"build-tool-toctou-control-{tool_name}-{mode}"; control_root.mkdir()
                original = tool_path.read_bytes(); original_mode = tool_path.stat().st_mode & 0o777; parent_mode = tool_path.parent.stat().st_mode & 0o777; mutation_tokens = []

                class MutatingToolEvents(list):
                    def append(inner_self, event):
                        super().append(event)
                        if event == f"tool:{tool_name}:runner-rehashed" and not mutation_tokens:
                            mutation_tokens.extend(self._mutate_use_window_path(tool_path, mode))

                events = MutatingToolEvents(); build_runner = FakeBuildRunner(elf, section_bytes, events=events); version_runner = FakeVersionRunner(events=events)
                try:
                    with mock.patch.object(self.build, "resolve_pinned_tools", autospec=True, return_value=copied_tools), self.subTest(tool=tool_name, mutation=mode), self.assertRaises(ValueError):
                        run_target_build(
                            generated_sdk_root=generated, bootstrap_receipt_path=bootstrap_path, build_root=build_root,
                            control_root=control_root, expected_source_commit=SOURCE_COMMIT, make_tool=copied_tools["make"],
                            runner=build_runner, version_runner=version_runner, event_sink=events.append,
                        )
                    self.assertEqual(len(mutation_tokens), 2); self.assertNotEqual(mutation_tokens[0], mutation_tokens[1])
                    self.assertEqual(len(build_runner.calls), expected_calls); self.assertNotIn("receipt:committed", events)
                    self.assertFalse((build_root / "build-receipt.json").exists()); self.assertEqual(list(build_root.iterdir()), [])
                    if mode.endswith("aba"):
                        self.assertFalse(tool_path.is_symlink()); self.assertEqual(tool_path.read_bytes(), original)
                finally:
                    tool_path.parent.chmod(tool_path.parent.stat().st_mode | 0o700)
                    if tool_path.is_symlink(): tool_path.unlink()
                    tool_path.write_bytes(original); tool_path.chmod(original_mode); tool_path.parent.chmod(parent_mode)
                    clean_generated_products()

    def test_build_roots_and_environment_are_closed_absolute_empty_real_and_nonoverlapping(self):
        validate_roots = require_api(self, self.build, "validate_build_roots")
        build_environment = require_api(self, self.build, "build_environment")
        generated = self.base / "generated-root"; generated.mkdir(); (generated / "SDK").mkdir()
        output = self.base / "build-root"; output.mkdir(); control = self.base / "build-control"; control.mkdir()
        protected = self.base / "protected-root"; protected.mkdir()
        exact_protected = {}
        for field in ("generated_sdk_root", "build_root", "control_root"):
            root = self.base / f"exact-protected-{field}"; root.mkdir()
            if field == "generated_sdk_root": (root / "SDK").mkdir()
            exact_protected[field] = root
        protected_roots = (ROOT, SDK_ROOT, TOOLCHAIN_ROOT, POST_ROOT, REFERENCE_ROOT, protected, *exact_protected.values())
        roots = validate_roots(generated_sdk_root=generated, build_root=output, control_root=control, protected_roots=protected_roots)
        self.assertEqual(roots, {"buildRoot": output.resolve(), "controlRoot": control.resolve(), "generatedSdkRoot": generated.resolve()})

        def fresh(label: str) -> dict[str, Path]:
            parent = self.base / label; parent.mkdir()
            generated_root = parent / "generated"; generated_root.mkdir(); (generated_root / "SDK").mkdir()
            build = parent / "build"; build.mkdir(); control_root = parent / "control"; control_root.mkdir()
            return {"generated_sdk_root": generated_root, "build_root": build, "control_root": control_root, "protected_roots": protected_roots}

        for field in ("generated_sdk_root", "build_root", "control_root"):
            arguments = fresh(f"relative-{field}"); arguments[field] = Path("relative-root")
            with self.subTest(relative=field), self.assertRaises(ValueError): validate_roots(**arguments)
        for field in ("generated_sdk_root", "build_root", "control_root"):
            arguments = fresh(f"missing-{field}"); arguments[field] = Path(arguments[field]).parent / "does-not-exist"
            with self.subTest(missing=field), self.assertRaises(ValueError): validate_roots(**arguments)
        for field in ("generated_sdk_root", "build_root", "control_root"):
            arguments = fresh(f"file-{field}"); candidate = Path(arguments[field]).parent / f"{field}.file"; candidate.write_bytes(b"not a directory"); arguments[field] = candidate
            with self.subTest(file=field), self.assertRaises(ValueError): validate_roots(**arguments)
        for field in ("generated_sdk_root", "build_root", "control_root"):
            arguments = fresh(f"symlink-{field}"); target = arguments[field]; link = target.parent / f"{field}-alias"; link.symlink_to(target, target_is_directory=True); arguments[field] = link
            with self.subTest(symlink=field), self.assertRaises(ValueError): validate_roots(**arguments)
        for field in ("generated_sdk_root", "build_root", "control_root"):
            arguments = fresh(f"parent-symlink-{field}"); real_parent = Path(arguments[field]).parent / "real-parent"; real_parent.mkdir(); candidate = real_parent / "child"; candidate.mkdir()
            if field == "generated_sdk_root": (candidate / "SDK").mkdir()
            link_parent = real_parent.parent / "linked-parent"; link_parent.symlink_to(real_parent, target_is_directory=True); arguments[field] = link_parent / "child"
            with self.subTest(parent_symlink=field), self.assertRaises(ValueError): validate_roots(**arguments)
        for field in ("generated_sdk_root", "build_root", "control_root"):
            arguments = fresh(f"protected-{field}"); candidate = protected / f"{field}-candidate"; candidate.mkdir()
            if field == "generated_sdk_root": (candidate / "SDK").mkdir()
            arguments[field] = candidate
            with self.subTest(protected=field), self.assertRaises(ValueError): validate_roots(**arguments)
            arguments = fresh(f"exact-protected-case-{field}"); arguments[field] = exact_protected[field]
            with self.subTest(exact_protected=field), self.assertRaises(ValueError): validate_roots(**arguments)
        for field in ("generated_sdk_root", "build_root", "control_root"):
            for protected_label in ("repository", "installed-sdk", "toolchain", "reference"):
                arguments = fresh(f"contains-{protected_label}-{field}"); container = self.base / f"build-container-{protected_label}-{field}"; container.mkdir()
                if field == "generated_sdk_root": (container / "SDK").mkdir()
                protected_child = container / f"protected-{protected_label}"; protected_child.mkdir()
                arguments[field] = container; arguments["protected_roots"] = (*protected_roots, protected_child)
                with self.subTest(contains_protected=(field, protected_label)), self.assertRaisesRegex(ValueError, "(?i)(protected|overlap|ancestor)"):
                    validate_roots(**arguments)
        for first, second in (("generated_sdk_root", "build_root"), ("generated_sdk_root", "control_root"), ("build_root", "control_root")):
            arguments = fresh(f"equal-{first}-{second}"); arguments[second] = arguments[first]
            with self.subTest(equal=(first, second)), self.assertRaisesRegex(ValueError, "(?i)(distinct|overlap|same)"): validate_roots(**arguments)
            for relation in ("first-ancestor", "second-ancestor"):
                arguments = fresh(f"{relation}-{first}-{second}")
                ancestor = arguments[first] if relation == "first-ancestor" else arguments[second]
                descendant_key = second if relation == "first-ancestor" else first
                descendant = ancestor / "nested"; descendant.mkdir()
                if descendant_key == "generated_sdk_root": (descendant / "SDK").mkdir()
                arguments[descendant_key] = descendant
                with self.subTest(pair=(first, second), relation=relation), self.assertRaisesRegex(ValueError, "(?i)(distinct|overlap|ancestor)"): validate_roots(**arguments)
        missing_sdk = fresh("missing-sdk"); (missing_sdk["generated_sdk_root"] / "SDK").rmdir()
        with self.assertRaises(ValueError): validate_roots(**missing_sdk)
        for field in ("build_root", "control_root"):
            arguments = fresh(f"nonempty-{field}"); (arguments[field] / "unexpected").write_bytes(b"x")
            with self.subTest(nonempty=field), self.assertRaises(ValueError): validate_roots(**arguments)

        environment = build_environment(control, source_date_epoch=SOURCE_DATE_EPOCH, tool_root=TOOLCHAIN_ROOT)
        self.assertEqual(environment, {"HOME": str(control / "home"), "TMPDIR": str(control / "tmp"), "LANG": "C", "LC_ALL": "C", "TZ": "UTC", "SOURCE_DATE_EPOCH": str(SOURCE_DATE_EPOCH), "PATH": CONTROLLED_BUILD_PATH})
        run_target_build = require_api(self, self.build, "run_target_build"); elf, _, section_bytes = make_elf32_fixture()
        run_generated = self.base / "invalid-root-generated"; run_bootstrap, _ = self._write_generated_sdk_fixture(run_generated)
        real_build = self.base / "invalid-root-real-build"; real_build.mkdir(); linked_build = self.base / "invalid-root-linked-build"; linked_build.symlink_to(real_build, target_is_directory=True)
        run_control = self.base / "invalid-root-control"; run_control.mkdir(); runner = FakeBuildRunner(elf, section_bytes)
        with self.assertRaises(ValueError):
            run_target_build(generated_sdk_root=run_generated, bootstrap_receipt_path=run_bootstrap, build_root=linked_build, control_root=run_control, expected_source_commit=SOURCE_COMMIT, make_tool=MAKE_TOOL, runner=runner, version_runner=FakeVersionRunner())
        self.assertEqual(runner.calls, [])

    def test_build_tools_are_resolved_only_from_lock_and_hash_verified_before_runner(self):
        resolve_tools = require_api(self, self.build, "resolve_pinned_tools")
        probe_versions = require_api(self, self.build, "probe_tool_versions")
        tools = resolve_tools(self.toolchain_lock, make_tool=MAKE_TOOL)
        self.assertEqual(set(tools), PRIMARY_BUILD_TOOLS | {"make"})
        for name in PRIMARY_BUILD_TOOLS:
            record = self.toolchain_lock["tools"][name]
            self.assertEqual(tools[name], {"path": str(TOOLCHAIN_ROOT / record["installRelativePath"]), "sha256": record["sha256"]})
        self.assertEqual(tools["make"], MAKE_TOOL)
        cwd = self.base / "version-cwd"; cwd.mkdir(); control = self.base / "version-control"; control.mkdir(); environment = self.build.build_environment(control, source_date_epoch=SOURCE_DATE_EPOCH, tool_root=TOOLCHAIN_ROOT)
        selected = {name: tools[name] for name in ("make", "objcopy", "objdump", "nm")}
        version_runner = FakeVersionRunner(); versions = probe_versions(selected, cwd=cwd, environment=environment, runner=version_runner)
        self.assertEqual([call[0] for call in version_runner.calls], [[tools[name]["path"], "--version"] for name in ("make", "objcopy", "objdump", "nm")])
        for _, kwargs in version_runner.calls:
            self.assertEqual(kwargs, {"check": False, "cwd": cwd, "env": environment, "shell": False, "stderr": subprocess.PIPE, "stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE})
        expected_probes = self._build_version_probe_receipts(selected)
        self.assertEqual(versions, {record["tool"]: record for record in expected_probes})
        for tool in selected:
            for mode in ("nonzero", "wrong", "prompt", "stderr-prompt"):
                with self.subTest(tool=tool, version_probe=mode), self.assertRaises(ValueError):
                    probe_versions(selected, cwd=cwd, environment=environment, runner=FakeVersionRunner(mode=mode, target_tool=tool))
        wrong = deepcopy(self.toolchain_lock); wrong["tools"]["objcopy"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "objcopy"):
            resolve_tools(wrong, make_tool=MAKE_TOOL)
        with self.assertRaises(TypeError):
            resolve_tools(self.toolchain_lock, tool_root=self.base / "attacker-tools")

    def test_make_identity_is_cross_checked_against_the_loaded_lock(self):
        self.assertEqual(self.toolchain_lock["hostTools"]["make"], MAKE_TOOL)

    def test_runtime_literal_normalization_keeps_ld_exact_without_invented_mode_or_length_pins(self):
        runtime = expected_lto_runtime()
        sha_values = [
            runtime["elfInterpreter"]["sha256"],
            *(record["sha256"] for record in runtime["hostTools"].values()),
            *(record["sha256"] for record in runtime["tools"].values()),
        ]
        self.assertTrue(all(re.fullmatch(r"[0-9A-F]{64}", value) for value in sha_values))
        self.assertEqual(runtime["tools"]["ld"], {
            **LD_TOOL,
            "invocationPath": str(TOOLCHAIN_ROOT / "pi32v2/bin/ld"),
            "resolvedPath": str(TOOLCHAIN_ROOT / "pi32v2/bin/ld"),
        })
        self.assertEqual(self.toolchain_lock["tools"]["ld"], LD_TOOL)
        self.assertNotIn("mode", runtime["tools"]["ld"])
        self.assertNotIn("byteLength", runtime["tools"]["ld"])
        self.assertEqual(set(runtime["tools"]), set(RUNTIME_TOOLS))

    def test_lto_runtime_symlinks_targets_path_interpreter_forbidden_argv_and_receipt_are_closed(self):
        resolve_runtime = require_api(self, self.build, "resolve_lto_runtime")
        validate_wrapper_argv = require_api(self, self.build, "validate_lto_wrapper_argv")
        build_runtime_receipt = require_api(self, self.build, "build_runtime_receipt")
        validate_runtime_receipt = require_api(self, self.build, "validate_runtime_receipt")
        runtime = resolve_runtime(self.toolchain_lock, tool_root=TOOLCHAIN_ROOT)
        self.assertEqual(self.toolchain_lock["tools"]["ld"], LD_TOOL)
        self.assertEqual(set(runtime), {"controlledPath", "elfInterpreter", "hostTools", "tools"})
        self.assertEqual(runtime["controlledPath"], CONTROLLED_BUILD_PATH)
        self.assertEqual(runtime["elfInterpreter"], ELF_INTERPRETER)
        self.assertEqual(runtime["hostTools"], LTO_HOST_TOOLS)
        self.assertEqual(runtime, expected_lto_runtime())
        self.assertEqual(set(runtime["tools"]), set(RUNTIME_TOOLS))
        for name, expected in RUNTIME_TOOLS.items():
            with self.subTest(lto_tool=name):
                invocation = TOOLCHAIN_ROOT / expected["installRelativePath"]
                resolved_relative = expected.get("resolvedInstallRelativePath", expected["installRelativePath"])
                resolved = TOOLCHAIN_ROOT / resolved_relative
                actual = runtime["tools"][name]
                self.assertEqual(actual["invocationPath"], str(invocation))
                self.assertEqual(actual["resolvedPath"], str(resolved))
                self.assertEqual({key: actual[key] for key in expected}, expected)
                if "mode" in expected:
                    self.assertEqual(resolved.stat().st_mode & 0o7777, int(expected["mode"], 8))
                if "byteLength" in expected:
                    self.assertEqual(resolved.stat().st_size, expected["byteLength"])
                self.assertEqual(hashlib.sha256(resolved.read_bytes()).hexdigest().upper(), expected["sha256"])
                if "symlinkTarget" in expected:
                    self.assertTrue(invocation.is_symlink())
                    self.assertEqual(os.readlink(invocation), expected["symlinkTarget"])
                else:
                    self.assertFalse(invocation.is_symlink())
                    self.assertEqual(invocation, resolved)
        self.assertEqual((TOOLCHAIN_ROOT / "common/bin/lto-wrapper").read_bytes().splitlines()[0], b"#!/usr/bin/env python3")
        self.assertTrue(Path(LTO_HOST_TOOLS["python3"]["path"]).is_symlink())
        self.assertEqual(os.readlink(LTO_HOST_TOOLS["python3"]["path"]), "python3.10")
        self.assertEqual(Path(LTO_HOST_TOOLS["python3"]["path"]).resolve(), Path(LTO_HOST_TOOLS["python3"]["resolvedPath"]))
        resolver_mutations = []
        for name in ("ltoWrapper", "ltoAr", "llvmGold", "linkVersion"):
            for field, replacement in (
                ("symlinkTarget", "../../common/bin/attacker"), ("sha256", "0" * 64),
                ("mode", "0777"), ("byteLength", self.toolchain_lock["tools"][name]["byteLength"] + 1),
            ):
                changed = deepcopy(self.toolchain_lock); changed["tools"][name][field] = replacement
                resolver_mutations.append((f"{name}-{field}", changed))
        for name in ("ar",):
            for field, replacement in (("sha256", "0" * 64), ("mode", "0777"), ("byteLength", self.toolchain_lock["tools"][name]["byteLength"] + 1)):
                changed = deepcopy(self.toolchain_lock); changed["tools"][name][field] = replacement
                resolver_mutations.append((f"{name}-{field}", changed))
        changed = deepcopy(self.toolchain_lock); changed["tools"]["ld"]["sha256"] = "0" * 64; resolver_mutations.append(("ld-sha256", changed))
        for name in ("env", "python3"):
            for field in self.toolchain_lock["hostTools"][name]:
                changed = deepcopy(self.toolchain_lock)
                value = changed["hostTools"][name][field]
                changed["hostTools"][name][field] = "0" * 64 if field == "sha256" else str(value) + ".drift"
                resolver_mutations.append((f"{name}-{field}", changed))
        for field in ("path", "sha256"):
            changed = deepcopy(self.toolchain_lock)
            changed["runtime"]["elfInterpreter"][field] = "0" * 64 if field == "sha256" else "/lib64/attacker.so"
            resolver_mutations.append((f"elf-interpreter-{field}", changed))
        for label, changed in resolver_mutations:
            with self.subTest(resolve_runtime_pin_drift=label), self.assertRaises(ValueError):
                resolve_runtime(changed, tool_root=TOOLCHAIN_ROOT)
        for forbidden in ("--extra-arguments-from-file", "--output-version-info"):
            with self.subTest(forbidden=forbidden):
                with self.assertRaisesRegex(ValueError, "forbidden"):
                    validate_wrapper_argv(["input.o", forbidden, "output.o"])
                with self.assertRaisesRegex(ValueError, "forbidden"):
                    validate_wrapper_argv(["input.o", f"{forbidden}=attacker", "output.o"])
        self.assertIsNone(validate_wrapper_argv(["input.o", "-o", "output.o"]))
        receipt = build_runtime_receipt(runtime=runtime, toolchain_lock=self.toolchain_lock)
        self.assertEqual(receipt, expected_runtime_receipt())
        self.assertEqual(set(receipt), {"controlledPath", "elfInterpreter", "hostTools", "schema", "toolchainLockSha256", "tools"})
        self.assertEqual(validate_runtime_receipt(receipt, expected_runtime=runtime, toolchain_lock=self.toolchain_lock), receipt)
        for name, changed in (
            ("missing", {key: value for key, value in receipt.items() if key != "controlledPath"}),
            ("wrong-type", {**receipt, "tools": []}),
            ("wrong-lock", {**receipt, "toolchainLockSha256": "0" * 64}),
            ("wrong-path", {**receipt, "controlledPath": "/usr/bin:/bin"}),
            ("wrong-python", {**receipt, "hostTools": {**receipt["hostTools"], "python3": {**receipt["hostTools"]["python3"], "sha256": "0" * 64}}}),
            ("wrong-wrapper", {**receipt, "tools": {**receipt["tools"], "ltoWrapper": {**receipt["tools"]["ltoWrapper"], "sha256": "0" * 64}}}),
            ("unknown", {**receipt, "unknown": True}),
        ):
            with self.subTest(receipt_mutation=name), self.assertRaises(ValueError):
                validate_runtime_receipt(changed, expected_runtime=runtime, toolchain_lock=self.toolchain_lock)

    def test_lto_runtime_snapshot_rejects_symlink_resolved_host_interpreter_shadow_and_aba_drift_before_use(self):
        snapshot_runtime = require_api(self, self.build, "snapshot_lto_runtime")
        reverify_runtime = require_api(self, self.build, "reverify_lto_runtime")
        runtime = deepcopy(expected_lto_runtime())
        runtime_root = self.base / "runtime-copy"
        tool_root = runtime_root / "toolchain"
        post_root = runtime_root / "post"
        host_root = runtime_root / "host"
        (tool_root / "pi32v2/bin").mkdir(parents=True)
        (tool_root / "common/bin").mkdir(parents=True)
        post_root.mkdir()
        (host_root / "usr/bin").mkdir(parents=True)
        (host_root / "bin").mkdir(parents=True)
        (host_root / "lib64").mkdir(parents=True)

        for name, pin in RUNTIME_TOOLS.items():
            source_resolved = Path(expected_lto_runtime()["tools"][name]["resolvedPath"])
            resolved_relative = pin.get("resolvedInstallRelativePath", pin["installRelativePath"])
            copied_resolved = tool_root / resolved_relative
            copied_resolved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_resolved, copied_resolved)
            copied_resolved.chmod(source_resolved.stat().st_mode & 0o7777)
            copied_invocation = tool_root / pin["installRelativePath"]
            if "symlinkTarget" in pin:
                copied_invocation.symlink_to(pin["symlinkTarget"])
            runtime["tools"][name]["invocationPath"] = str(copied_invocation)
            runtime["tools"][name]["resolvedPath"] = str(copied_resolved)

        copied_env = host_root / "usr/bin/env"
        shutil.copy2(LTO_HOST_TOOLS["env"]["path"], copied_env)
        copied_env.chmod(Path(LTO_HOST_TOOLS["env"]["path"]).stat().st_mode & 0o7777)
        runtime["hostTools"]["env"]["path"] = str(copied_env)
        copied_python = host_root / "usr/bin/python3.10"
        shutil.copy2(LTO_HOST_TOOLS["python3"]["resolvedPath"], copied_python)
        copied_python.chmod(Path(LTO_HOST_TOOLS["python3"]["resolvedPath"]).stat().st_mode & 0o7777)
        copied_python_link = host_root / "usr/bin/python3"
        copied_python_link.symlink_to("python3.10")
        runtime["hostTools"]["python3"] = {
            **runtime["hostTools"]["python3"],
            "path": str(copied_python_link),
            "resolvedPath": str(copied_python),
        }
        copied_interpreter = host_root / "lib64/ld-linux-x86-64.so.2"
        shutil.copy2(ELF_INTERPRETER["path"], copied_interpreter)
        copied_interpreter.chmod(Path(ELF_INTERPRETER["path"]).stat().st_mode & 0o7777)
        runtime["elfInterpreter"] = {**runtime["elfInterpreter"], "path": str(copied_interpreter)}
        runtime["controlledPath"] = f"{tool_root}/pi32v2/bin:{post_root}:{host_root}/usr/bin:{host_root}/bin"

        def save_path(path: Path):
            if path.is_symlink(): return ("symlink", os.readlink(path), None)
            return ("regular", path.read_bytes(), path.stat().st_mode & 0o7777)

        def restore_path(path: Path, saved) -> None:
            if path.is_symlink() or path.exists():
                if path.is_dir() and not path.is_symlink(): shutil.rmtree(path)
                else: path.unlink()
            if saved[0] == "symlink": path.symlink_to(saved[1])
            else: path.write_bytes(saved[1]); path.chmod(saved[2])

        version_runner = FakeVersionRunner()
        elf, _, section_bytes = make_elf32_fixture()
        build_runner = FakeBuildRunner(elf, section_bytes)
        build_output = self.base / "runtime-mutation-output"; build_output.mkdir()
        receipt_path = build_output / "build-receipt.json"

        symlink_paths = [Path(runtime["tools"][name]["invocationPath"]) for name in ("ltoWrapper", "ltoAr", "llvmGold", "linkVersion")]
        symlink_paths.append(Path(runtime["hostTools"]["python3"]["path"]))
        for path in symlink_paths:
            saved = save_path(path)
            for mode in ("target-one-way", "target-aba", "non-symlink"):
                snapshot = snapshot_runtime(runtime=runtime)
                try:
                    path.unlink()
                    if mode == "non-symlink": path.write_bytes(b"not a symlink")
                    else:
                        path.symlink_to(saved[1] + ".drift")
                        if mode == "target-aba": path.unlink(); path.symlink_to(saved[1])
                    with self.subTest(runtime_symlink=path.name, mutation=mode), self.assertRaises(ValueError):
                        reverify_runtime(runtime=runtime, snapshot=snapshot)
                finally:
                    restore_path(path, saved)

        regular_paths = [
            *(Path(runtime["tools"][name]["resolvedPath"]) for name in RUNTIME_TOOLS),
            Path(runtime["hostTools"]["env"]["path"]),
            Path(runtime["hostTools"]["python3"]["resolvedPath"]),
            Path(runtime["elfInterpreter"]["path"]),
        ]
        for path in regular_paths:
            saved = save_path(path)
            for mode in ("bytes-one-way", "bytes-aba", "mode-one-way", "mode-aba", "symlink", "nonregular"):
                snapshot = snapshot_runtime(runtime=runtime)
                try:
                    if mode.startswith("bytes"):
                        path.write_bytes(saved[1] + b"drift")
                        if mode.endswith("aba"): path.write_bytes(saved[1]); path.chmod(saved[2])
                    elif mode.startswith("mode"):
                        path.chmod(saved[2] ^ 0o100)
                        if mode.endswith("aba"): path.chmod(saved[2])
                    else:
                        path.unlink()
                        if mode == "symlink":
                            alternate = path.parent / f"{path.name}.alternate"; alternate.write_bytes(saved[1]); alternate.chmod(saved[2]); path.symlink_to(alternate)
                        else: path.mkdir()
                    with self.subTest(runtime_regular=str(path), mutation=mode), self.assertRaises(ValueError):
                        reverify_runtime(runtime=runtime, snapshot=snapshot)
                finally:
                    restore_path(path, saved)
                    alternate = path.parent / f"{path.name}.alternate"
                    if alternate.exists(): alternate.unlink()

        for component in (tool_root / "pi32v2/bin", post_root):
            for mode in ("regular", "symlink"):
                snapshot = snapshot_runtime(runtime=runtime)
                shadow = component / "python3"
                alternate = component / "python3.shadow"
                try:
                    if mode == "regular": shadow.write_bytes(b"#!/bin/false\n")
                    else: alternate.write_bytes(b"#!/bin/false\n"); shadow.symlink_to(alternate)
                    with self.subTest(python_shadow=str(component), kind=mode), self.assertRaises(ValueError):
                        reverify_runtime(runtime=runtime, snapshot=snapshot)
                finally:
                    if shadow.is_symlink() or shadow.exists(): shadow.unlink()
                    if alternate.exists(): alternate.unlink()

        self.assertEqual(version_runner.calls, [])
        self.assertEqual(build_runner.calls, [])
        self.assertFalse(receipt_path.exists())
        self.assertEqual(list(build_output.iterdir()), [])

    def test_elf32_pi32v2_parser_enforces_exec_entry_sections_loads_and_vma_lma_bounds(self):
        parse_elf32 = require_api(self, self.build, "parse_elf32")
        elf, sections, _ = make_elf32_fixture(); parsed = parse_elf32(elf)
        self.assertEqual(set(parsed), {"elfClass", "endianness", "entryAddress", "machine", "programHeaders", "sections", "type"})
        self.assertEqual((parsed["elfClass"], parsed["endianness"], parsed["type"], parsed["machine"], parsed["entryAddress"]), ("ELF32", "little", "ET_EXEC", 0xF1, 0x0C000100))
        self.assertEqual([{key: item[key] for key in ("fileOffset", "lma", "name", "size", "vma")} for item in parsed["sections"]], sections)
        self.assertNotIn("cpu", parsed)
        mutations = {}
        for name, offset, value in (("class", 4, 2), ("endianness", 5, 2), ("version", 6, 0)):
            changed = bytearray(elf); changed[offset] = value; mutations[name] = bytes(changed)
        for name, offset, value, width in (("type", 16, 1, 2), ("machine", 18, 0x28, 2), ("non-load", 52, 0, 4), ("non-executable-text-load", 52 + 24, 4, 4), ("lma-below-base", 52 + 12, 0x0BFFFFF0, 4)):
            changed = bytearray(elf); changed[offset:offset + width] = value.to_bytes(width, "little"); mutations[name] = bytes(changed)
        shoff = int.from_bytes(elf[32:36], "little"); changed = bytearray(elf); changed[shoff + 40 + 12:shoff + 40 + 16] = (0x0D900000).to_bytes(4, "little"); mutations["vma-outside-load"] = bytes(changed)
        changed = bytearray(elf); changed[shoff + 40 + 8:shoff + 40 + 12] = (0x2).to_bytes(4, "little"); mutations["non-executable-text-section"] = bytes(changed)
        changed = bytearray(elf); changed[24:28] = (0x0C000110).to_bytes(4, "little"); changed[52 + 32 + 24:52 + 32 + 28] = (5).to_bytes(4, "little"); changed[shoff + 80 + 8:shoff + 80 + 12] = (0x6).to_bytes(4, "little"); mutations["entry-in-executable-non-text"] = bytes(changed)
        changed = bytearray(elf); phoff = int.from_bytes(elf[28:32], "little"); phentsize = int.from_bytes(elf[42:44], "little"); phnum = int.from_bytes(elf[44:46], "little"); shentsize = int.from_bytes(elf[46:48], "little"); shnum = int.from_bytes(elf[48:50], "little")
        duplicate_offset = 0x180; duplicate_vma = 0x0C000180; duplicate_size = 0x10
        changed[phoff + phnum * phentsize:phoff + (phnum + 1) * phentsize] = struct.pack("<IIIIIIII", 1, duplicate_offset, duplicate_vma, duplicate_vma, duplicate_size, duplicate_size, 5, 1)
        changed[duplicate_offset:duplicate_offset + duplicate_size] = b"duplicate text!\n"
        duplicate_header = bytearray(elf[shoff + shentsize:shoff + 2 * shentsize])
        duplicate_header[12:16] = duplicate_vma.to_bytes(4, "little"); duplicate_header[16:20] = duplicate_offset.to_bytes(4, "little"); duplicate_header[20:24] = duplicate_size.to_bytes(4, "little")
        changed.extend(duplicate_header); changed[44:46] = (phnum + 1).to_bytes(2, "little"); changed[48:50] = (shnum + 1).to_bytes(2, "little")
        duplicate_image = bytes(changed); duplicate_phnum = int.from_bytes(duplicate_image[44:46], "little"); self.assertEqual(duplicate_phnum, 9)
        loads = [struct.unpack("<IIIIIIII", duplicate_image[phoff + index * phentsize:phoff + (index + 1) * phentsize]) for index in range(duplicate_phnum)]
        self.assertTrue(all(item[0] == 1 for item in loads))
        for offset_index in (1, 3):
            ranges = sorted((item[offset_index], item[offset_index] + item[4]) for item in loads)
            self.assertTrue(all(first[1] <= second[0] for first, second in zip(ranges, ranges[1:])))
        duplicate_shnum = int.from_bytes(duplicate_image[48:50], "little"); shstrndx = int.from_bytes(duplicate_image[50:52], "little")
        shstr_header = duplicate_image[shoff + shstrndx * shentsize:shoff + (shstrndx + 1) * shentsize]
        shstr_offset = int.from_bytes(shstr_header[16:20], "little"); shstr_size = int.from_bytes(shstr_header[20:24], "little"); names = duplicate_image[shstr_offset:shstr_offset + shstr_size]
        required_names = []; text_flags = []
        for index in range(duplicate_shnum):
            header = duplicate_image[shoff + index * shentsize:shoff + (index + 1) * shentsize]; name_offset = int.from_bytes(header[:4], "little")
            name = names[name_offset:names.find(b"\0", name_offset)].decode("ascii") if name_offset else ""
            if name in {required for required, _ in SECTIONS}: required_names.append(name)
            if name == ".text": text_flags.append(int.from_bytes(header[8:12], "little"))
        self.assertEqual(required_names, [*[name for name, _ in SECTIONS], ".text"]); self.assertEqual(len(text_flags), 2); self.assertTrue(all(flags & 0x4 for flags in text_flags))
        mutations["duplicate-required-section-with-ninth-load"] = duplicate_image
        changed = bytearray(elf); overlap_vma = 0x0C000108
        changed[52 + 32 + 8:52 + 32 + 12] = overlap_vma.to_bytes(4, "little"); changed[shoff + 80 + 12:shoff + 80 + 16] = overlap_vma.to_bytes(4, "little"); mutations["vma-overlap-only"] = bytes(changed)
        changed = bytearray(elf); overlap_offset = 0x208
        changed[52 + 32 + 4:52 + 32 + 8] = overlap_offset.to_bytes(4, "little"); changed[shoff + 80 + 16:shoff + 80 + 20] = overlap_offset.to_bytes(4, "little"); mutations["file-offset-overlap"] = bytes(changed)
        mutations["truncated"] = elf[:-1]
        for name, data in mutations.items():
            with self.subTest(name=name), self.assertRaises(ValueError): parse_elf32(data)

    def test_object_inventory_and_map_provenance_canonicalize_and_reject_alias_duplicates(self):
        parse_inventory = require_api(self, self.build, "parse_object_inventory")
        parse_map = require_api(self, self.build, "parse_map_provenance")
        sdk_build = self.base / "SDK/build"; sdk_build.mkdir(parents=True)
        for relative in OBJECTS:
            path = sdk_build / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(relative.encode("ascii"))
        inventory = parse_inventory(("\n".join(OBJECTS) + "\n").encode("ascii"), sdk_build)
        self.assertEqual([item["relativePath"] for item in inventory], OBJECTS)
        alias_input = (OBJECTS[0] + "\n" + str((sdk_build / OBJECTS[0]).resolve()) + "\n" + "\n".join(OBJECTS[1:]) + "\n").encode("ascii")
        with self.assertRaises(ValueError): parse_inventory(alias_input, sdk_build)
        hardlink = sdk_build / "objs/alias.c.o"; os.link(sdk_build / OBJECTS[0], hardlink)
        with self.assertRaises(ValueError): parse_inventory((OBJECTS[0] + "\nobjs/alias.c.o\n" + "\n".join(OBJECTS[1:]) + "\n").encode("ascii"), sdk_build)
        symlink = sdk_build / "objs/symlink.c.o"; symlink.symlink_to(sdk_build / OBJECTS[0])
        with self.assertRaises(ValueError): parse_inventory(("objs/symlink.c.o\n" + "\n".join(OBJECTS[1:]) + "\n").encode("ascii"), sdk_build)
        good_map = ".text.bt_ble_init 0x0C000100 0x10 objs/apps/watch/e87/e87_stage0_ble.c.o\n                0x0C000100 bt_ble_init\n"
        proof = parse_map(good_map, inventory)
        self.assertEqual(proof["bt_ble_init"], {"address": "0x0C000100", "object": "objs/apps/watch/e87/e87_stage0_ble.c.o", "strength": "STRONG"})
        with self.assertRaises(ValueError): parse_map(good_map.replace("e87_stage0_ble.c.o", "e87_stage0_app.c.o"), inventory)

    def test_build_receipt_requires_exact_order_and_binds_source_app_sections_and_inputs(self):
        build_receipt = require_api(self, self.build, "build_receipt")
        parse_provenance = require_api(self, self.build, "parse_build_provenance")
        build_command_specs = require_api(self, self.build, "build_command_specs")
        validate_bootstrap = require_api(self, self.build, "validate_bootstrap_receipt")
        elf_bytes, sections, section_bytes = make_elf32_fixture(); build_root = self.base / "receipt-build"; build_root.mkdir(); elf = build_root / "sdk.elf"; elf.write_bytes(elf_bytes)
        generated = self.base / "receipt-generated"; bootstrap_path, bootstrap = self._write_generated_sdk_fixture(generated, receipt_path=build_root / "bootstrap-receipt.json"); sdk = generated / "SDK"
        generated_elf = sdk / "cpu/br35/tools/sdk.elf"; generated_elf.parent.mkdir(parents=True, exist_ok=True); generated_elf.write_bytes(elf_bytes)
        provenance = parse_provenance(generated)
        self.assertEqual(provenance, {
            "compileMakefile": {"cpu": "r3", "relativePath": "SDK/Makefile", "sha256": hashlib.sha256(COMPILE_MAKEFILE).hexdigest().upper(), "target": "pi32v2"},
            "linkMakefile": {"cpu": "r3", "cpuTokenCount": 2, "relativePath": "SDK/build/Makefile.mk", "sha256": hashlib.sha256(LINK_MAKEFILE).hexdigest().upper()},
        })
        section_root = build_root
        section_outputs = []
        for section, filename in SECTIONS:
            data = section_bytes[section]; (section_root / filename).write_bytes(data)
            section_outputs.append({"filename": filename, "section": section, "sha256": hashlib.sha256(data).hexdigest().upper(), "size": len(data)})
        app = b"".join(section_bytes[section] for section, _ in SECTIONS); app_path = build_root / "app.bin"; app_path.write_bytes(app)
        tools = self.build.resolve_pinned_tools(self.toolchain_lock, make_tool=MAKE_TOOL)
        specs = build_command_specs(generated_sdk_root=generated, build_root=build_root, tools=tools)
        empty_sha = hashlib.sha256(b"").hexdigest().upper(); stdout = {"make": b"linked\n", "objdump": synthetic_objdump_stdout(section_bytes), "nm": b"0C000100 T bt_ble_init\n"}
        commands = []
        command_results = []
        for spec in specs:
            tool = spec["role"].split(":", 1)[0]; output = stdout.get(tool, b"")
            result = subprocess.CompletedProcess(spec["argv"], 0, output, b"")
            commands.append(build_raw_record({"argv": spec["argv"], "exitCode": 0, "role": spec["role"], "stderrSha256": empty_sha, "stdoutSha256": hashlib.sha256(output).hexdigest().upper(), "toolSha256": tools[tool]["sha256"], "toolVersion": BUILD_TOOL_VERSIONS[tool]}, result))
            command_results.append(result)
        version_probes = self._build_version_probe_receipts({name: tools[name] for name in ("make", "objcopy", "objdump", "nm")})
        version_results = [subprocess.CompletedProcess(record["argv"], 0, BUILD_TOOL_VERSION_STDOUT[record["tool"]], b"") for record in version_probes]
        bootstrap_validation = synthetic_bootstrap_replay_evidence(bootstrap, bootstrap_path.read_bytes())["validation"]
        runtime = expected_runtime_receipt()
        arguments = {"app_path": app_path, "bootstrap_receipt_path": bootstrap_path, "bootstrap_validation": bootstrap_validation, "command_results": command_results, "commands": commands, "elf_path": elf, "environment": normalized_build_environment(), "expected_source_commit": SOURCE_COMMIT, "generated_sdk_root": generated, "map_provenance": {"bt_ble_init": {"address": "0x0C000100", "object": OBJECTS[2], "strength": "STRONG"}}, "resource_limits": BUILD_RESOURCE_LIMITS, "runtime": runtime, "section_outputs": section_outputs, "section_root": section_root, "sections": sections, "source_objects": OBJECTS, "symbols": [{"address": "0x0C000100", "kind": "T", "name": "bt_ble_init"}], "validations": BUILD_VALIDATIONS, "version_probes": version_probes, "version_results": version_results}
        receipt = call_contract(self, "cross-bound build receipt", build_receipt, **arguments)
        with self.assertRaises(TypeError): build_receipt(**arguments, source_date_epoch=SOURCE_DATE_EPOCH)
        without_replay = dict(arguments); without_replay.pop("bootstrap_validation")
        with self.assertRaises(TypeError): build_receipt(**without_replay)
        for required_argument in ("environment", "resource_limits", "validations"):
            missing_argument = dict(arguments); missing_argument.pop(required_argument)
            with self.subTest(missing_build_evidence=required_argument), self.assertRaises(TypeError): build_receipt(**missing_argument)
        self.assertEqual((receipt["sourceCommit"], receipt["sourceDateEpoch"]), (SOURCE_COMMIT, SOURCE_DATE_EPOCH))
        self.assertEqual(set(receipt), {"app", "bootstrap", "bootstrapReceipt", "bootstrapValidation", "buildProvenance", "commands", "elf", "environment", "inputs", "mapProvenance", "resourceLimits", "runtime", "schema", "sectionOutputs", "sections", "sourceCommit", "sourceDateEpoch", "sourceObjects", "symbols", "target", "validations", "versionProbes"})
        self.assertEqual(receipt["app"], {"filename": "app.bin", "sha256": hashlib.sha256(app).hexdigest().upper(), "size": len(app)})
        self.assertEqual(receipt["commands"], commands)
        self.assertEqual([item["role"] for item in receipt["commands"]], ["make", *[f"objcopy:{name}" for name, _ in SECTIONS], "objdump", "nm"])
        command_keys = {"argv", "cwd", "environment", "exitCode", "role", "stderrHex", "stderrSha256", "stderrSize", "stdoutHex", "stdoutSha256", "stdoutSize", "toolSha256", "toolVersion"}
        probe_keys = {"argv", "cwd", "environment", "exitCode", "stderrHex", "stderrSha256", "stderrSize", "stdoutHex", "stdoutSha256", "stdoutSize", "tool", "toolSha256", "version"}
        self.assertTrue(all(set(item) == command_keys for item in receipt["commands"]))
        self.assertEqual(receipt["versionProbes"], version_probes)
        self.assertTrue(all(set(item) == probe_keys for item in receipt["versionProbes"]))
        self.assertEqual(receipt["environment"], normalized_build_environment())
        self.assertEqual(receipt["resourceLimits"], BUILD_RESOURCE_LIMITS)
        self.assertEqual(receipt["validations"], BUILD_VALIDATIONS)
        for label, field, replacement in (
            ("environment-missing", "environment", {key: value for key, value in normalized_build_environment().items() if key != "HOME"}),
            ("environment-unknown", "environment", {**normalized_build_environment(), "INHERITED": "1"}),
            ("resource-soft-low", "resource_limits", {"nofileSoft": 8191}),
            ("resource-soft-type", "resource_limits", {"nofileSoft": "8192"}),
            ("resource-unknown", "resource_limits", {"nofileSoft": 8192, "hard": 16384}),
            ("validations-unknown", "validations", {**BUILD_VALIDATIONS, "callerValidated": True}),
        ):
            with self.subTest(build_execution_projection=label), self.assertRaises(ValueError):
                build_receipt(**{**arguments, field: replacement})
        for validation_name in BUILD_VALIDATIONS:
            for mutation, replacement in (("missing", None), ("false", False), ("non-bool", 1)):
                changed = dict(BUILD_VALIDATIONS)
                if mutation == "missing": changed.pop(validation_name)
                else: changed[validation_name] = replacement
                with self.subTest(build_validation=(validation_name, mutation)), self.assertRaises(ValueError):
                    build_receipt(**{**arguments, "validations": changed})
        for collection_name, records, raw_results in (
            ("commands", commands, command_results),
            ("version_probes", version_probes, version_results),
        ):
            for index, (record, raw_result) in enumerate(zip(records, raw_results, strict=True)):
                for stream in ("stdout", "stderr"):
                    self.assertEqual(bytes.fromhex(record[f"{stream}Hex"]), getattr(raw_result, stream))
                    self.assertEqual(record[f"{stream}Size"], len(getattr(raw_result, stream)))
                    self.assertEqual(record[f"{stream}Sha256"], hashlib.sha256(getattr(raw_result, stream)).hexdigest().upper())
                    for field, replacement in (
                        (f"{stream}Hex", "00" if record[f"{stream}Hex"] != "00" else "FF"),
                        (f"{stream}Size", record[f"{stream}Size"] + 1),
                        (f"{stream}Sha256", "A" * 64),
                    ):
                        changed = deepcopy(records); changed[index][field] = replacement
                        with self.subTest(raw_projection=(collection_name, index, field)), self.assertRaises(ValueError):
                            build_receipt(**{**arguments, collection_name: changed})
                for field, replacement in (
                    ("cwd", "$OTHER_ROOT"),
                    ("environment", {**normalized_build_environment(), "INHERITED": "1"}),
                ):
                    changed = deepcopy(records); changed[index][field] = replacement
                    with self.subTest(execution_context=(collection_name, index, field)), self.assertRaises(ValueError):
                        build_receipt(**{**arguments, collection_name: changed})
        self.assertEqual(receipt["runtime"], runtime)
        self.assertEqual(receipt["bootstrapValidation"], bootstrap_validation)
        self.assertEqual(receipt["bootstrapValidation"]["receiptSha256"], receipt["bootstrapReceipt"]["sha256"])
        self.assertEqual(receipt["bootstrapValidation"]["outputTreeSha256"], receipt["bootstrap"]["outputTreeSha256"])
        self.assertEqual(receipt["bootstrapValidation"]["commandsSha256"], projection_sha256(receipt["bootstrap"]["commands"]))
        self.assertEqual(receipt["bootstrapValidation"]["validationsSha256"], projection_sha256(receipt["bootstrap"]["validations"]))
        for field, replacement in (
            ("commandsSha256", "0" * 64), ("outputTreeSha256", "0" * 64), ("receiptSha256", "0" * 64),
            ("schema", "e87-stage0-bootstrap-replay-validation-v0"), ("validationsSha256", "0" * 64),
        ):
            changed_validation = deepcopy(bootstrap_validation); changed_validation[field] = replacement
            with self.subTest(bootstrap_validation=field), self.assertRaises(ValueError):
                build_receipt(**{**arguments, "bootstrap_validation": changed_validation})
        changed_validation = deepcopy(bootstrap_validation); changed_validation.pop("commandsSha256")
        with self.assertRaises(ValueError): build_receipt(**{**arguments, "bootstrap_validation": changed_validation})
        changed_validation = deepcopy(bootstrap_validation); changed_validation["trusted"] = True
        with self.assertRaises(ValueError): build_receipt(**{**arguments, "bootstrap_validation": changed_validation})
        for label, changed_runtime in (
            ("missing", {key: value for key, value in runtime.items() if key != "controlledPath"}),
            ("unknown", {**runtime, "trusted": True}),
            ("wrong-type", {**runtime, "tools": []}),
            ("wrong-lock", {**runtime, "toolchainLockSha256": "0" * 64}),
            ("wrong-interpreter", {**runtime, "elfInterpreter": {**runtime["elfInterpreter"], "sha256": "0" * 64}}),
            ("wrong-env", {**runtime, "hostTools": {**runtime["hostTools"], "env": {**runtime["hostTools"]["env"], "sha256": "0" * 64}}}),
            ("wrong-ar", {**runtime, "tools": {**runtime["tools"], "ar": {**runtime["tools"]["ar"], "sha256": "0" * 64}}}),
        ):
            with self.subTest(build_runtime=label), self.assertRaises(ValueError):
                build_receipt(**{**arguments, "runtime": changed_runtime})
        self.assertEqual({key: receipt["target"][key] for key in ("architecture", "cpu", "entryAddress")}, {"architecture": "pi32v2", "cpu": "r3", "entryAddress": "0x0C000100"})
        self.assertEqual((int(receipt["target"]["codeEnd"], 16), receipt["target"]["uiresStart"]), (independent_elf32_load_end(elf_bytes), "0x00180000")); self.assertRegex(receipt["target"]["mapSha256"], r"^[0-9A-F]{64}$")
        bootstrap_bytes = bootstrap_path.read_bytes(); inputs = [{"filename": bootstrap_path.name, "sha256": hashlib.sha256(bootstrap_bytes).hexdigest().upper(), "size": len(bootstrap_bytes)}]
        self.assertEqual(receipt["bootstrap"], bootstrap); self.assertEqual(receipt["bootstrapReceipt"], inputs[0]); self.assertEqual(receipt["sectionOutputs"], section_outputs); self.assertEqual(receipt["inputs"], inputs); self.assertEqual(receipt["buildProvenance"], provenance)
        command_mutations = []
        reordered = deepcopy(commands); reordered[1], reordered[2] = reordered[2], reordered[1]; command_mutations.append(("order", reordered))
        command_mutations.extend((("truncated", commands[:-1]), ("extra", [*commands, deepcopy(commands[-1])])))
        for index, record in enumerate(commands):
            for field, value in (("argv", ["/bin/false"]), ("cwd", "$OTHER_ROOT"), ("environment", {**normalized_build_environment(), "INHERITED": "1"}), ("exitCode", 1), ("role", f"wrong-role-{index}"), ("toolSha256", "0" * 64), ("toolVersion", "drift"), ("stdoutHex", "00"), ("stdoutSize", record["stdoutSize"] + 1), ("stdoutSha256", "0" * 64), ("stderrHex", "00"), ("stderrSize", record["stderrSize"] + 1), ("stderrSha256", "0" * 64)):
                changed = deepcopy(commands); changed[index][field] = value; command_mutations.append((f"{record['role']}:{field}", changed))
            for field in command_keys:
                changed = deepcopy(commands); changed[index].pop(field); command_mutations.append((f"{record['role']}:missing:{field}", changed))
            changed = deepcopy(commands); changed[index]["trusted"] = True; command_mutations.append((f"{record['role']}:unknown", changed))
        for label, changed in command_mutations:
            with self.subTest(command_drift=label), self.assertRaises(ValueError): build_receipt(**{**arguments, "commands": changed})
        for index, record in enumerate(version_probes):
            for field, value in (("argv", ["/bin/false"]), ("cwd", "$OTHER_ROOT"), ("environment", {**normalized_build_environment(), "INHERITED": "1"}), ("exitCode", 1), ("tool", "wrong"), ("toolSha256", "0" * 64), ("version", "drift"), ("stdoutHex", "00"), ("stdoutSize", record["stdoutSize"] + 1), ("stdoutSha256", "0" * 64), ("stderrHex", "00"), ("stderrSize", record["stderrSize"] + 1), ("stderrSha256", "0" * 64)):
                changed = deepcopy(version_probes); changed[index][field] = value
                with self.subTest(version_probe=f"{record['tool']}:{field}"), self.assertRaises(ValueError): build_receipt(**{**arguments, "version_probes": changed})
            for field in probe_keys:
                changed = deepcopy(version_probes); changed[index].pop(field)
                with self.subTest(version_probe=f"{record['tool']}:missing:{field}"), self.assertRaises(ValueError): build_receipt(**{**arguments, "version_probes": changed})
            changed = deepcopy(version_probes); changed[index]["trusted"] = True
            with self.subTest(version_probe=f"{record['tool']}:unknown"), self.assertRaises(ValueError): build_receipt(**{**arguments, "version_probes": changed})
        for label, changed in (("order", list(reversed(version_probes))), ("truncated", version_probes[:-1]), ("extra", [*version_probes, deepcopy(version_probes[-1])])):
            with self.subTest(version_probe_list=label), self.assertRaises(ValueError): build_receipt(**{**arguments, "version_probes": changed})
        for index, result in enumerate(command_results):
            raw_mutations = (
                ("args", subprocess.CompletedProcess(["/bin/false"], result.returncode, result.stdout, result.stderr)),
                ("returncode", subprocess.CompletedProcess(result.args, 1, result.stdout, result.stderr)),
                ("stdout", subprocess.CompletedProcess(result.args, result.returncode, result.stdout + b"drift", result.stderr)),
                ("stderr", subprocess.CompletedProcess(result.args, result.returncode, result.stdout, result.stderr + b"drift")),
                ("type", {"args": result.args, "returncode": result.returncode}),
            )
            for label, replacement in raw_mutations:
                changed_results = list(command_results); changed_results[index] = replacement
                with self.subTest(raw_command=f"{index}:{label}"), self.assertRaises((TypeError, ValueError)):
                    build_receipt(**{**arguments, "command_results": changed_results})
        for index, result in enumerate(version_results):
            raw_mutations = (
                ("args", subprocess.CompletedProcess(["/bin/false"], result.returncode, result.stdout, result.stderr)),
                ("returncode", subprocess.CompletedProcess(result.args, 1, result.stdout, result.stderr)),
                ("stdout", subprocess.CompletedProcess(result.args, result.returncode, result.stdout + b"drift", result.stderr)),
                ("stderr", subprocess.CompletedProcess(result.args, result.returncode, result.stdout, result.stderr + b"drift")),
                ("type", {"args": result.args, "returncode": result.returncode}),
            )
            for label, replacement in raw_mutations:
                changed_results = list(version_results); changed_results[index] = replacement
                with self.subTest(raw_version=f"{index}:{label}"), self.assertRaises((TypeError, ValueError)):
                    build_receipt(**{**arguments, "version_results": changed_results})
        self.assertEqual(set(bootstrap), {"commands", "gitTool", "locks", "outputTreeSha256", "overlay", "patch", "schema", "sdkCommit", "sdkTree", "sourceCommit", "sourceCommitEpoch", "sourceCommitObjectSha256", "sourceTree", "validations"})
        self.assertEqual(hashlib.sha1(b"commit " + str(len(SOURCE_COMMIT_BODY)).encode("ascii") + b"\0" + SOURCE_COMMIT_BODY).hexdigest(), bootstrap["sourceCommit"])
        self.assertEqual(hashlib.sha256(SOURCE_COMMIT_BODY).hexdigest().upper(), bootstrap["sourceCommitObjectSha256"])
        self.assertEqual(int(re.search(rb"^committer .* ([0-9]+) [+-][0-9]{4}$", SOURCE_COMMIT_BODY, re.MULTILINE).group(1)), bootstrap["sourceCommitEpoch"])
        tree_headers = re.findall(rb"^tree ([0-9a-f]{40})$", SOURCE_COMMIT_BODY, re.MULTILINE)
        self.assertEqual(tree_headers, [bootstrap["sourceTree"].encode("ascii")]); self.assertEqual(bootstrap["sourceTree"], SOURCE_TREE)
        self.assertEqual([record["role"] for record in bootstrap["commands"]], list(BOOTSTRAP_COMMAND_ROLES)); self.assertEqual(len(set(BOOTSTRAP_COMMAND_ROLES)), 31)
        command_keys = {"argv", "cwd", "environment", "exitCode", "role", "stderrSha256", "stderrSize", "stdin", "stdoutSha256", "stdoutSize", "toolSha256", "toolVersion"}
        self.assertTrue(all(set(record) == command_keys for record in bootstrap["commands"]))
        self.assertTrue(all(record["exitCode"] == 0 and record["toolSha256"] == bootstrap["gitTool"]["sha256"] and record["toolVersion"] == bootstrap["gitTool"]["version"] for record in bootstrap["commands"]))
        self.assertEqual({record["cwd"] for record in bootstrap["commands"]}, {"${OWNED_STAGING_ROOT}", "sdk", "source"})
        self.assertFalse(any(str(self.base) in json.dumps(record, sort_keys=True) for record in bootstrap["commands"]))
        patch_commands = [record for record in bootstrap["commands"] if record["role"] in {"patch-check", "patch-apply"}]
        self.assertEqual([record["stdin"] for record in patch_commands], [{"sha256": bootstrap["patch"]["sha256"], "size": bootstrap["patch"]["size"]}] * 2)
        self.assertTrue(all(record["stdin"] is None for record in bootstrap["commands"] if record not in patch_commands))
        self.assertEqual(bootstrap["validations"], BOOTSTRAP_VALIDATIONS); self.assertTrue(all(type(value) is bool and value for value in bootstrap["validations"].values()))
        self.assertEqual(bootstrap["sourceCommitEpoch"], SOURCE_DATE_EPOCH)
        self.assertEqual(bootstrap["overlay"], sorted(bootstrap["overlay"], key=lambda record: record["source"]))
        self.assertTrue(all(set(record) == {"destination", "sha256", "size", "source"} and record["size"] > 0 for record in bootstrap["overlay"]))
        self.assertEqual(set(bootstrap["patch"]), {"paths", "sha256", "size"}); self.assertGreater(bootstrap["patch"]["size"], 0)
        original_bootstrap = bootstrap_path.read_bytes()
        self.assertEqual(original_bootstrap, (json.dumps(bootstrap, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii"))

        def reject_bootstrap_mutation(label: str, mutate) -> None:
            changed = json.loads(original_bootstrap); mutate(changed)
            changed_bytes = (json.dumps(changed, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii")
            changed_validation = synthetic_bootstrap_replay_validation(changed, changed_bytes)
            self.assertEqual(changed_validation["receiptSha256"], hashlib.sha256(changed_bytes).hexdigest().upper())
            self.assertEqual(changed_validation["commandsSha256"], projection_sha256(changed.get("commands")))
            self.assertEqual(changed_validation["validationsSha256"], projection_sha256(changed.get("validations")))
            bootstrap_path.write_bytes(changed_bytes)
            try:
                with self.subTest(bootstrap=label), self.assertRaises(ValueError):
                    build_receipt(**{**arguments, "bootstrap_validation": changed_validation})
            finally:
                bootstrap_path.write_bytes(original_bootstrap)

        nested_control = json.loads(original_bootstrap)
        patch_check_index = next(index for index, command in enumerate(nested_control["commands"]) if command["role"] == "patch-check")
        nested_control["commands"][patch_check_index]["stdin"]["size"] = str(nested_control["commands"][patch_check_index]["stdin"]["size"])
        nested_control_bytes = (json.dumps(nested_control, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii")
        nested_control_validation = synthetic_bootstrap_replay_validation(nested_control, nested_control_bytes)
        self.assertNotEqual(bootstrap_validation["receiptSha256"], nested_control_validation["receiptSha256"])
        self.assertEqual(nested_control_validation["commandsSha256"], projection_sha256(nested_control["commands"]))
        bootstrap_path.write_bytes(nested_control_bytes)
        try:
            with self.subTest(bootstrap="nested-stale-outer-hash-control"), self.assertRaises(ValueError):
                build_receipt(**arguments)
            with self.subTest(bootstrap="nested-recomputed-outer-hash-control"), self.assertRaises(ValueError):
                build_receipt(**{**arguments, "bootstrap_validation": nested_control_validation})
            with self.subTest(bootstrap="nested-direct-validator-control"), self.assertRaises(ValueError):
                validate_bootstrap(
                    bootstrap_receipt_path=bootstrap_path,
                    generated_sdk_root=generated,
                    expected_source_commit=SOURCE_COMMIT,
                    expected_commands=nested_control["commands"],
                )
        finally:
            bootstrap_path.write_bytes(original_bootstrap)

        for label, mutate in (
            ("missing-top", lambda value: value.pop("sourceCommitEpoch")),
            ("unknown-top", lambda value: value.__setitem__("callerValidated", True)),
            ("schema", lambda value: value.__setitem__("schema", "e87-stage0-bootstrap-receipt-v0")),
            ("source-commit", lambda value: value.__setitem__("sourceCommit", "f" * 40)),
            ("source-tree", lambda value: value.__setitem__("sourceTree", "0" * 40)),
            ("sdk-commit", lambda value: value.__setitem__("sdkCommit", "0" * 40)),
            ("sdk-tree", lambda value: value.__setitem__("sdkTree", "0" * 40)),
            ("epoch-type", lambda value: value.__setitem__("sourceCommitEpoch", str(SOURCE_DATE_EPOCH))),
            ("epoch-bool", lambda value: value.__setitem__("sourceCommitEpoch", True)),
            ("epoch-negative", lambda value: value.__setitem__("sourceCommitEpoch", -1)),
            ("epoch-float", lambda value: value.__setitem__("sourceCommitEpoch", float(SOURCE_DATE_EPOCH))),
            ("commit-object", lambda value: value.__setitem__("sourceCommitObjectSha256", "0" * 64)),
            ("commit-object-length", lambda value: value.__setitem__("sourceCommitObjectSha256", "A" * 63)),
            ("commit-object-type", lambda value: value.__setitem__("sourceCommitObjectSha256", 7)),
            ("output-tree", lambda value: value.__setitem__("outputTreeSha256", "0" * 64)),
            ("git-missing", lambda value: value["gitTool"].pop("version")),
            ("git-unknown", lambda value: value["gitTool"].__setitem__("trusted", True)),
            ("git-path", lambda value: value["gitTool"].__setitem__("path", "/tmp/git")),
            ("git-version", lambda value: value["gitTool"].__setitem__("version", "drift")),
            ("overlay-order", lambda value: value["overlay"].reverse()),
            ("overlay-missing", lambda value: value["overlay"][0].pop("size")),
            ("overlay-unknown", lambda value: value["overlay"][0].__setitem__("trusted", True)),
            ("overlay-hash", lambda value: value["overlay"][0].__setitem__("sha256", "0" * 64)),
            ("overlay-source", lambda value: value["overlay"][0].__setitem__("source", "firmware/overlay/unreviewed.c")),
            ("overlay-destination", lambda value: value["overlay"][0].__setitem__("destination", "SDK/unreviewed.c")),
            ("overlay-size-zero", lambda value: value["overlay"][0].__setitem__("size", 0)),
            ("overlay-size-type", lambda value: value["overlay"][0].__setitem__("size", "1")),
            ("overlay-record-missing", lambda value: value["overlay"].pop()),
            ("overlay-record-duplicate", lambda value: value["overlay"].append(deepcopy(value["overlay"][-1]))),
            ("patch-missing", lambda value: value["patch"].pop("size")),
            ("patch-unknown", lambda value: value["patch"].__setitem__("trusted", True)),
            ("patch-hash", lambda value: value["patch"].__setitem__("sha256", "0" * 64)),
            ("patch-size-zero", lambda value: value["patch"].__setitem__("size", 0)),
            ("patch-size-type", lambda value: value["patch"].__setitem__("size", "1")),
            ("patch-path", lambda value: value["patch"]["paths"].append("SDK/unreviewed.c")),
            ("patch-path-missing", lambda value: value["patch"]["paths"].pop()),
            ("patch-path-order", lambda value: value["patch"]["paths"].reverse()),
            ("patch-path-duplicate", lambda value: value["patch"]["paths"].append(value["patch"]["paths"][-1])),
            ("lock-missing", lambda value: value["locks"].pop("packaging.lock.json")),
            ("lock-unknown", lambda value: value["locks"].__setitem__("extra.lock.json", "0" * 64)),
            ("lock-hash", lambda value: value["locks"].__setitem__("toolchain.lock.json", "0" * 64)),
            ("git-tool", lambda value: value["gitTool"].__setitem__("sha256", "0" * 64)),
        ):
            reject_bootstrap_mutation(label, mutate)
        for label, mutate in (
            ("commands-missing", lambda value: value.pop("commands")),
            ("commands-type", lambda value: value.__setitem__("commands", {})),
            ("commands-empty", lambda value: value.__setitem__("commands", [])),
            ("commands-order", lambda value: value["commands"].reverse()),
            ("commands-truncated", lambda value: value["commands"].pop()),
            ("commands-extra", lambda value: value["commands"].append(deepcopy(value["commands"][-1]))),
            ("validations-missing", lambda value: value.pop("validations")),
            ("validations-type", lambda value: value.__setitem__("validations", [])),
            ("validations-empty", lambda value: value.__setitem__("validations", {})),
            ("validations-unknown", lambda value: value["validations"].__setitem__("callerValidated", True)),
        ):
            reject_bootstrap_mutation(label, mutate)
        for index, command in enumerate(bootstrap["commands"]):
            replacements = {
                "argv": [GIT_TOOL["path"], "status"],
                "cwd": "sdk" if command["cwd"] != "sdk" else "source",
                "environment": {**command["environment"], "TZ": "GMT"},
                "exitCode": 1,
                "role": f"wrong-role-{index}",
                "stderrSha256": "0" * 64,
                "stderrSize": command["stderrSize"] + 1,
                "stdin": (
                    None
                    if command["stdin"] is not None
                    else {"sha256": bootstrap["patch"]["sha256"], "size": bootstrap["patch"]["size"]}
                ),
                "stdoutSha256": "0" * 64,
                "stdoutSize": command["stdoutSize"] + 1,
                "toolSha256": "0" * 64,
                "toolVersion": "git version drift",
            }
            for field, replacement in replacements.items():
                reject_bootstrap_mutation(
                    f"command-{index}-{command['role']}-{field}",
                    lambda value, i=index, f=field, r=deepcopy(replacement): value["commands"][i].__setitem__(f, r),
                )
            for field in command_keys:
                reject_bootstrap_mutation(
                    f"command-{index}-{command['role']}-missing-{field}",
                    lambda value, i=index, f=field: value["commands"][i].pop(f),
                )
            reject_bootstrap_mutation(
                f"command-{index}-{command['role']}-unknown",
                lambda value, i=index: value["commands"][i].__setitem__("trusted", True),
            )
            for environment_key in command["environment"]:
                reject_bootstrap_mutation(
                    f"command-{index}-{command['role']}-environment-missing-{environment_key}",
                    lambda value, i=index, key=environment_key: value["commands"][i]["environment"].pop(key),
                )
            reject_bootstrap_mutation(
                f"command-{index}-{command['role']}-environment-unknown",
                lambda value, i=index: value["commands"][i]["environment"].__setitem__("UNREVIEWED", "1"),
            )
            if command["stdin"] is not None:
                for field, replacement in (
                    ("sha256", "0" * 64), ("size", int(command["stdin"]["size"]) + 1),
                    ("sha256", 7), ("size", str(command["stdin"]["size"])),
                ):
                    reject_bootstrap_mutation(
                        f"command-{index}-{command['role']}-stdin-{field}-{type(replacement).__name__}",
                        lambda value, i=index, f=field, r=replacement: value["commands"][i]["stdin"].__setitem__(f, r),
                    )
                for field in ("sha256", "size"):
                    reject_bootstrap_mutation(
                        f"command-{index}-{command['role']}-stdin-missing-{field}",
                        lambda value, i=index, f=field: value["commands"][i]["stdin"].pop(f),
                    )
                reject_bootstrap_mutation(
                    f"command-{index}-{command['role']}-stdin-unknown",
                    lambda value, i=index: value["commands"][i]["stdin"].__setitem__("trusted", True),
                )
                reject_bootstrap_mutation(
                    f"command-{index}-{command['role']}-stdin-type",
                    lambda value, i=index: value["commands"][i].__setitem__("stdin", []),
                )
        for name in BOOTSTRAP_VALIDATIONS:
            reject_bootstrap_mutation(
                f"validation-{name}-false",
                lambda value, key=name: value["validations"].__setitem__(key, False),
            )
            reject_bootstrap_mutation(
                f"validation-{name}-non-bool",
                lambda value, key=name: value["validations"].__setitem__(key, 1),
            )
            reject_bootstrap_mutation(
                f"validation-{name}-missing",
                lambda value, key=name: value["validations"].pop(key),
            )
        bootstrap_path.write_bytes(json.dumps(bootstrap, ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("ascii"))
        with self.assertRaises(ValueError): build_receipt(**arguments)
        bootstrap_path.write_bytes(original_bootstrap)
        generated_inputs = [(f"generated-overlay:{relative}", generated / relative) for relative in BOOTSTRAP_OVERLAYS]
        generated_inputs += [(f"generated-patch:{relative}", generated / relative) for relative in BOOTSTRAP_PATCH_TARGETS]
        for label, path in (("bootstrap-file", bootstrap_path), ("elf-file", elf), ("generated-elf-file", generated_elf), ("section-file", section_root / "text.bin"), ("app-file", app_path), *generated_inputs):
            before = path.read_bytes(); path.write_bytes(before + b"drift")
            with self.subTest(file_drift=label), self.assertRaises(ValueError): build_receipt(**arguments)
            path.write_bytes(before)
        mode_path = generated / BOOTSTRAP_OVERLAYS[0]; mode_before = mode_path.stat().st_mode & 0o777; tree_before = independent_tree_sha256(generated)
        directory = mode_path.parent; directory_mode = directory.stat().st_mode & 0o777; directory.chmod(directory_mode ^ 0o200)
        self.assertEqual(independent_tree_sha256(generated), tree_before); directory.chmod(directory_mode)
        mode_path.chmod(mode_before | 0o111)
        self.assertNotEqual(independent_tree_sha256(generated), tree_before)
        with self.assertRaises(ValueError): build_receipt(**arguments)
        mode_path.chmod(mode_before)
        cross_links = []
        changed = deepcopy(sections); changed[0]["size"] += 1; cross_links.append(("elf-section-size", {"sections": changed}))
        changed = deepcopy(section_outputs); changed[0]["sha256"] = "0" * 64; cross_links.append(("section-output-hash", {"section_outputs": changed}))
        changed = deepcopy(section_outputs); changed[0], changed[1] = changed[1], changed[0]; cross_links.append(("section-output-order", {"section_outputs": changed}))
        cross_links.append(("map-address", {"map_provenance": {"bt_ble_init": {"address": "0x0C000110", "object": OBJECTS[2], "strength": "STRONG"}}}))
        cross_links.append(("map-object", {"map_provenance": {"bt_ble_init": {"address": "0x0C000100", "object": OBJECTS[1], "strength": "STRONG"}}}))
        cross_links.append(("nm-address", {"symbols": [{"address": "0x0C000110", "kind": "T", "name": "bt_ble_init"}]}))
        cross_links.append(("source-object", {"source_objects": [*OBJECTS[:-1], "objs/apps/watch/e87/unreviewed.c.o"]}))
        for label, change in cross_links:
            with self.subTest(cross_link=label), self.assertRaises(ValueError): build_receipt(**{**arguments, **change})
        (sdk / "Makefile").write_bytes(COMPILE_MAKEFILE + b"export CFLAGS += -target arm -mcpu=r2\n")
        with self.assertRaises(ValueError): parse_provenance(generated)
        (sdk / "Makefile").write_bytes(COMPILE_MAKEFILE); (sdk / "build/Makefile.mk").write_bytes(LINK_MAKEFILE + b"LFLAGS += --plugin-opt=mcpu=r2\n")
        with self.assertRaises(ValueError): parse_provenance(generated)
        (sdk / "build/Makefile.mk").write_bytes(LINK_MAKEFILE.replace(b"$(LFLAGS)", b""))
        with self.assertRaises(ValueError): parse_provenance(generated)
        (sdk / "build/Makefile.mk").write_bytes(LINK_MAKEFILE.replace(b"$(CFLAGS)", b""))
        with self.assertRaises(ValueError): parse_provenance(generated)

    def test_native_commands_runner_environment_and_no_shell_contract_are_exact(self):
        staging = self.base / "staging"; expected_inputs = self._write_exact_staging_fixture(staging, b"reviewed-app")
        control = self.base / "control"; control.mkdir()
        environment = self.package.package_environment(control, source_date_epoch=1700000000)
        expected_environment = {
            "HOME": str(control / "home"),
            "TMPDIR": str(control / "tmp"),
            "LANG": "C",
            "LC_ALL": "C",
            "TZ": "UTC",
            "SOURCE_DATE_EPOCH": "1700000000",
            "PATH": "/home/jethac/.local/share/e87-dev/jieli-post-build:/usr/bin:/bin",
        }
        self.assertEqual(environment, expected_environment)
        self.assertEqual(set(environment), {"HOME", "TMPDIR", "LANG", "LC_ALL", "TZ", "SOURCE_DATE_EPOCH", "PATH"})
        for name in ("HOME", "TMPDIR"):
            path = Path(environment[name]); self.assertTrue(path.is_absolute() and path.is_dir()); self.assertFalse(path.is_symlink())
        self.package.validate_package_environment(environment, control, source_date_epoch=1700000000)
        with self.assertRaises(ValueError): self.package.validate_package_environment({**environment, "INHERITED": "forbidden"}, control, source_date_epoch=1700000000)
        resolve_tools = require_api(self, self.package, "resolve_locked_package_tools")
        tools = resolve_tools(self.packaging_lock)
        self.assertEqual(set(tools), {"fwAdd", "isdDownload", "ufwMaker"})
        self.assertEqual((tools["isdDownload"]["path"], tools["isdDownload"]["sha256"]), (str(POST_ROOT / "isd_download"), "11849221C3E5E89D31E6FCEF52FE1DB28C2C5D322CDB919E954CCA2A5043EF87"))
        self.assertEqual(tools["fwAdd"]["invocation"], "FORBIDDEN")
        runner = FakeNativeRunner()
        outputs = self.package.run_native_packagers(staging, tools, expected_inputs=expected_inputs, control_root=control, environment=environment, runner=runner)
        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(runner.calls[0][0], [str(POST_ROOT / "isd_download"), *ISD_ARGUMENTS])
        self.assertEqual(runner.calls[1][0], [str(POST_ROOT / "ufw_maker"), "--fw", "jl_isd.fw", "--output", "independently-made.ufw"])
        self.assertEqual(set(outputs), {"jl_isd.bin", "jl_isd.fw", "update.ufw", "independently-made.ufw"})
        for argv, kwargs in runner.calls:
            self.assertIsInstance(argv, list); self.assertEqual(Path(kwargs["cwd"]), staging)
            self.assertEqual(kwargs["env"], environment); self.assertIs(kwargs["shell"], False); self.assertIs(kwargs["check"], False)
            self.assertEqual((kwargs["stdin"], kwargs["stdout"], kwargs["stderr"]), (subprocess.DEVNULL, subprocess.PIPE, subprocess.PIPE))
        flattened = " ".join(arg for call in runner.calls for arg in call[0]).lower()
        for forbidden in ("fw_add", "-format", "-tone", "-key", "efuse", "otp", "usb", "serial", "*"):
            self.assertNotIn(forbidden, flattened)

    def test_native_failures_prompt_missing_extra_input_mutation_and_dangerous_argv_are_fatal(self):
        resolve_tools = require_api(self, self.package, "resolve_locked_package_tools")
        tools = resolve_tools(self.packaging_lock)
        control = self.base / "failure-control"; control.mkdir()
        environment = self.package.package_environment(control, source_date_epoch=1700000000)
        for tool in ("isd_download", "ufw_maker"):
            for mode in ("nonzero", "prompt", "stderr-prompt", "missing", "extra", "mutate-input"):
                staging = self.base / ("staging-" + tool + "-" + mode); expected_inputs = self._write_exact_staging_fixture(staging, b"reviewed-app")
                with self.subTest(tool=tool, mode=mode):
                    with self.assertRaises(ValueError): self.package.run_native_packagers(staging, tools, expected_inputs=expected_inputs, control_root=control, environment=environment, runner=FakeNativeRunner(mode, fail_tool=tool))
        for tool, output_name in (("isd_download", "jl_isd.bin"), ("isd_download", "jl_isd.fw"), ("isd_download", "update.ufw"), ("ufw_maker", "independently-made.ufw")):
            staging = self.base / ("empty-" + output_name.replace(".", "-")); expected_inputs = self._write_exact_staging_fixture(staging, b"reviewed-app")
            with self.subTest(tool=tool, empty_output=output_name):
                with self.assertRaises(ValueError):
                    self.package.run_native_packagers(staging, tools, expected_inputs=expected_inputs, control_root=control, environment=environment, runner=FakeNativeRunner("empty", fail_tool=tool, empty_output=output_name))
        for argv in (["tool", "-format"], ["tool", "-keyfile", "x"], ["tool", "/dev/ttyUSB0"], ["tool", "COM4"], ["tool", "*.bin"]):
            with self.subTest(argv=argv):
                with self.assertRaises(ValueError): self.package.reject_dangerous_argv(argv)

    def test_independent_ufw_must_be_byte_identical_or_report_first_difference(self):
        first = self.base / "first.ufw"; second = self.base / "second.ufw"; stage0 = stage0_package_fixture()["update.ufw"]
        first.write_bytes(stage0); second.write_bytes(stage0)
        self.assertEqual(self.package.compare_ufw_or_raise(first, second)["sha256"], hashlib.sha256(stage0).hexdigest().upper())
        parsed = self.ufw.validate_stage0_ufw(stage0)
        self.assertEqual([item["name"] for item in parsed["entries"]], ["flash.bin", "info.log", "uboot.version", "params_flash.bin", "isd_config.ini", "v_ota.bin", "ota.bin", "farg.cfg", "blimit.bin", "tail.bin"])
        vendor = (REFERENCE_ROOT / "container/payload.ufw").read_bytes(); first.write_bytes(vendor); second.write_bytes(vendor)
        with self.assertRaisesRegex(ValueError, "reset policy"):
            self.package.compare_ufw_or_raise(first, second)
        first.write_bytes(stage0); changed = bytearray(stage0); changed[-1] ^= 1; second.write_bytes(changed)
        exact_message = (
            f"first difference at 0x{len(stage0) - 1:X}: {stage0[-1]:02X}!={changed[-1]:02X}; semantic difference: "
            "first=AC707N/v4/items=10/image=0x102220/postImage.bodySha256=3CA44F3A12E08FF12C26E6B87024DB6B7446B8A5A936EA999AC920DABE150FF1; "
            "second=AC707N/v4/items=10/image=0x102220/postImage.bodySha256=779914B5A50A47D7388FC2C4557CC4E88299A80E3580BB6251C637AE3836C45F"
        )
        with self.assertRaisesRegex(ValueError, "^" + re.escape(exact_message) + "$"):
            self.package.compare_ufw_or_raise(first, second)

    def test_closed_cli_dispatches_run_and_compare_without_tool_app_tag_or_validation_overrides(self):
        parser_factory = require_api(self, self.package, "package_parser")
        require_api(self, self.package, "run_stage0_package")
        require_api(self, self.package, "assert_reproducible_runs")
        parser = parser_factory()
        self.assertFalse(parser.allow_abbrev)
        subparser_actions = [action for action in parser._actions if isinstance(action, argparse._SubParsersAction)]
        self.assertEqual([action for action in parser._actions if action.dest != "help"], subparser_actions)
        self.assertEqual(len(subparser_actions), 1); self.assertEqual(subparser_actions[0].dest, "command"); self.assertTrue(subparser_actions[0].required); self.assertEqual(set(subparser_actions[0].choices), {"compare", "run"})
        run_parser = subparser_actions[0].choices["run"]; compare_parser = subparser_actions[0].choices["compare"]
        self.assertFalse(run_parser.allow_abbrev); self.assertFalse(compare_parser.allow_abbrev)
        run_actions = {action.dest: action for action in run_parser._actions if action.dest != "help"}
        self.assertEqual({dest: tuple(action.option_strings) for dest, action in run_actions.items()}, {
            "build_root": ("--build-root",), "expected_source_commit": ("--expected-source-commit",), "generated_sdk_root": ("--generated-sdk-root",),
            "reference_root": ("--reference-root",), "run_root": ("--run-root",),
        })
        for dest, action in run_actions.items(): self.assertTrue(action.required); self.assertIs(action.type, str if dest == "expected_source_commit" else Path)
        compare_actions = {action.dest: action for action in compare_parser._actions if action.dest != "help"}
        self.assertEqual({dest: tuple(action.option_strings) for dest, action in compare_actions.items()}, {"first_run_root": ("--first-run-root",), "second_run_root": ("--second-run-root",)})
        for action in compare_actions.values(): self.assertTrue(action.required); self.assertIs(action.type, Path)
        run = parser.parse_args(["run", "--generated-sdk-root", "/generated", "--build-root", "/build", "--reference-root", "/reference", "--run-root", "/run", "--expected-source-commit", SOURCE_COMMIT])
        self.assertEqual(vars(run), {"build_root": Path("/build"), "command": "run", "expected_source_commit": SOURCE_COMMIT, "generated_sdk_root": Path("/generated"), "reference_root": Path("/reference"), "run_root": Path("/run")})
        compare = parser.parse_args(["compare", "--first-run-root", "/run-1", "--second-run-root", "/run-2"])
        self.assertEqual(vars(compare), {"command": "compare", "first_run_root": Path("/run-1"), "second_run_root": Path("/run-2")})
        for forbidden in ("--tool", "--app", "--build-tag", "--validated", "--source-date-epoch", "--lock-root", "--post-root", "--sdk-root", "--qix-name", "--qix-version"):
            with self.subTest(forbidden=forbidden), self.assertRaises(SystemExit):
                parser.parse_args(["run", "--generated-sdk-root", "/generated", "--build-root", "/build", "--reference-root", "/reference", "--run-root", "/run", "--expected-source-commit", SOURCE_COMMIT, forbidden, "x"])
        cli_build = self.base / "package-cli-build"; self._build_receipt_fixture(cli_build, b"nonempty-app"); cli_generated = self.base / "package-cli-build-generated"
        cli_run = self.base / "package-cli-run"; cli_run.mkdir()
        cli_receipt = {"schema": "e87-stage0-package-receipt-v1", "sourceCommit": SOURCE_COMMIT}
        run_argv = ["run", "--generated-sdk-root", str(cli_generated), "--build-root", str(cli_build), "--reference-root", str(REFERENCE_ROOT), "--run-root", str(cli_run), "--expected-source-commit", SOURCE_COMMIT]
        with mock.patch.object(self.package, "package_parser", wraps=self.package.package_parser) as parser_builder, mock.patch.object(self.package, "run_stage0_package", autospec=True, return_value=cli_receipt) as dispatch:
            self.assertEqual(self.package.main(run_argv), 0)
        parser_builder.assert_called_once_with()
        dispatch.assert_called_once_with(generated_sdk_root=cli_generated, build_root=cli_build, reference_root=REFERENCE_ROOT, run_root=cli_run, expected_source_commit=SOURCE_COMMIT)
        receipt_path = cli_run / "evidence/package-receipt.json"
        self.assertEqual(receipt_path.read_bytes(), (json.dumps(cli_receipt, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii"))
        first = self.base / "cli-run-1"; second = self.base / "cli-run-2"; first.mkdir(); second.mkdir()
        with mock.patch.object(self.package, "package_parser", wraps=self.package.package_parser) as parser_builder, mock.patch.object(self.package, "assert_reproducible_runs", autospec=True, return_value=None) as dispatch:
            self.assertEqual(self.package.main(["compare", "--first-run-root", str(first), "--second-run-root", str(second)]), 0)
        parser_builder.assert_called_once_with()
        dispatch.assert_called_once_with(first_run_root=first, second_run_root=second)

    def test_orchestrator_resolves_and_reopens_pinned_tools_roots_environment_and_exact_ten_nonempty_inputs(self):
        validate_roots = require_api(self, self.package, "validate_package_roots")
        resolve_tools = require_api(self, self.package, "resolve_locked_package_tools")
        reverify = require_api(self, self.package, "reverify_package_inputs")
        build = self.base / "build"; receipt = self._build_receipt_fixture(build, b"nonempty-app"); generated = self.base / "build-generated"
        run = self.base / "run"; run.mkdir()
        protected = self.base / "package-protected"; protected.mkdir(); exact_protected = {}
        for field in ("generated_sdk_root", "build_root", "reference_root", "run_root"):
            root = self.base / f"package-exact-protected-{field}"; root.mkdir()
            if field == "generated_sdk_root": (root / "SDK").mkdir()
            elif field == "build_root": (root / "build-receipt.json").write_bytes(b"{}\n")
            elif field == "reference_root": (root / "manifest.json").write_bytes(b"{}\n")
            exact_protected[field] = root
        protected_roots = (ROOT, SDK_ROOT, TOOLCHAIN_ROOT, POST_ROOT, protected, *exact_protected.values())
        roots = validate_roots(generated_sdk_root=generated, build_root=build, reference_root=REFERENCE_ROOT, run_root=run, protected_roots=protected_roots)
        self.assertEqual(set(roots), {"build", "control", "delivery", "evidence", "generatedSdk", "reference", "run", "staging"})

        def fresh(label: str) -> dict[str, object]:
            parent = self.base / f"package-roots-{label}"; parent.mkdir()
            generated_root = parent / "generated"; generated_root.mkdir(); (generated_root / "SDK").mkdir()
            build_root = parent / "build"; build_root.mkdir(); (build_root / "build-receipt.json").write_bytes(b"{}\n")
            reference_root = parent / "reference"; reference_root.mkdir(); (reference_root / "manifest.json").write_bytes(b"{}\n")
            run_root = parent / "run"; run_root.mkdir()
            return {"generated_sdk_root": generated_root, "build_root": build_root, "reference_root": reference_root, "run_root": run_root, "protected_roots": protected_roots}

        package_root_fields = ("generated_sdk_root", "build_root", "reference_root", "run_root")
        for field in package_root_fields:
            arguments = fresh(f"relative-{field}"); arguments[field] = Path("relative-root")
            with self.subTest(relative=field), self.assertRaises(ValueError): validate_roots(**arguments)
        for field in package_root_fields:
            arguments = fresh(f"missing-{field}"); arguments[field] = Path(arguments[field]).parent / "does-not-exist"
            with self.subTest(missing=field), self.assertRaises(ValueError): validate_roots(**arguments)
        for field in package_root_fields:
            arguments = fresh(f"file-{field}"); candidate = Path(arguments[field]).parent / f"{field}.file"; candidate.write_bytes(b"not a directory"); arguments[field] = candidate
            with self.subTest(file=field), self.assertRaises(ValueError): validate_roots(**arguments)
        for field in package_root_fields:
            arguments = fresh(f"symlink-{field}"); target = Path(arguments[field]); link = target.parent / f"{field}-alias"; link.symlink_to(target, target_is_directory=True); arguments[field] = link
            with self.subTest(symlink=field), self.assertRaises(ValueError): validate_roots(**arguments)
        for field in package_root_fields:
            arguments = fresh(f"parent-symlink-{field}"); real_parent = Path(arguments[field]).parent / "real-parent"; real_parent.mkdir(); candidate = real_parent / "child"; candidate.mkdir()
            if field == "generated_sdk_root": (candidate / "SDK").mkdir()
            elif field == "build_root": (candidate / "build-receipt.json").write_bytes(b"{}\n")
            elif field == "reference_root": (candidate / "manifest.json").write_bytes(b"{}\n")
            link_parent = real_parent.parent / "linked-parent"; link_parent.symlink_to(real_parent, target_is_directory=True); arguments[field] = link_parent / "child"
            with self.subTest(parent_symlink=field), self.assertRaises(ValueError): validate_roots(**arguments)
        for field in package_root_fields:
            arguments = fresh(f"protected-{field}"); candidate = protected / f"package-{field}"; candidate.mkdir()
            if field == "generated_sdk_root": (candidate / "SDK").mkdir()
            elif field != "run_root": (candidate / "required-marker").write_bytes(b"x")
            arguments[field] = candidate
            with self.subTest(protected=field), self.assertRaises(ValueError): validate_roots(**arguments)
            arguments = fresh(f"exact-protected-case-{field}"); arguments[field] = exact_protected[field]
            with self.subTest(exact_protected=field), self.assertRaises(ValueError): validate_roots(**arguments)
        for field in package_root_fields:
            for protected_label in ("repository", "installed-sdk", "toolchain", "reference"):
                arguments = fresh(f"contains-{protected_label}-{field}"); container = self.base / f"package-container-{protected_label}-{field}"; container.mkdir()
                if field == "generated_sdk_root": (container / "SDK").mkdir()
                elif field == "build_root": (container / "build-receipt.json").write_bytes(b"{}\n")
                elif field == "reference_root": (container / "manifest.json").write_bytes(b"{}\n")
                protected_child = container / f"protected-{protected_label}"; protected_child.mkdir()
                arguments[field] = container; arguments["protected_roots"] = (*protected_roots, protected_child)
                with self.subTest(contains_protected=(field, protected_label)), self.assertRaisesRegex(ValueError, "(?i)(protected|overlap|ancestor)"):
                    validate_roots(**arguments)
        for first_index, first in enumerate(package_root_fields):
            for second in package_root_fields[first_index + 1:]:
                arguments = fresh(f"equal-{first}-{second}"); arguments[second] = arguments[first]
                with self.subTest(equal=(first, second)), self.assertRaisesRegex(ValueError, "(?i)(distinct|overlap|same)"): validate_roots(**arguments)
                for relation in ("first-ancestor", "second-ancestor"):
                    arguments = fresh(f"{relation}-{first}-{second}")
                    ancestor = Path(arguments[first] if relation == "first-ancestor" else arguments[second]); descendant_key = second if relation == "first-ancestor" else first
                    descendant = ancestor / "nested"; descendant.mkdir(); arguments[descendant_key] = descendant
                    with self.subTest(pair=(first, second), relation=relation), self.assertRaisesRegex(ValueError, "(?i)(distinct|overlap|ancestor)"): validate_roots(**arguments)
        nonempty = fresh("nonempty-run"); (Path(nonempty["run_root"]) / "unexpected").write_bytes(b"x")
        with self.assertRaises(ValueError): validate_roots(**nonempty)
        tools = resolve_tools(self.packaging_lock)
        self.assertEqual(tools["isdDownload"]["sha256"], "11849221C3E5E89D31E6FCEF52FE1DB28C2C5D322CDB919E954CCA2A5043EF87")
        self.assertEqual(tools["ufwMaker"]["sha256"], "039D761CA4170F1E5658B868C963E8D43651000368BE55E892CD0BD941B553C6")
        self.assertEqual(tools["fwAdd"]["invocation"], "FORBIDDEN")
        stage = Path(roots["staging"]); records = self._write_exact_staging_fixture(stage, b"nonempty-app")
        snapshot = {item["filename"]: (item["size"], item["sha256"]) for item in records}
        self.assertEqual(set(receipt), {"app", "bootstrap", "bootstrapReceipt", "bootstrapValidation", "buildProvenance", "commands", "elf", "environment", "inputs", "mapProvenance", "resourceLimits", "runtime", "schema", "sectionOutputs", "sections", "sourceCommit", "sourceDateEpoch", "sourceObjects", "symbols", "target", "validations", "versionProbes"})
        self.assertEqual(receipt["runtime"], expected_runtime_receipt())
        verified = reverify(reference_root=REFERENCE_ROOT, sdk_root=SDK_ROOT, generated_sdk_root=generated, build_root=build, staging_root=stage, expected_source_commit=SOURCE_COMMIT, tools=tools, expected_staging=snapshot)
        self.assertEqual(verified["buildReceiptSha256"], hashlib.sha256((build / "build-receipt.json").read_bytes()).hexdigest().upper())
        (stage / "app.bin").write_bytes(b"")
        with self.assertRaises(ValueError):
            reverify(reference_root=REFERENCE_ROOT, sdk_root=SDK_ROOT, generated_sdk_root=generated, build_root=build, staging_root=stage, expected_source_commit=SOURCE_COMMIT, tools=tools, expected_staging=snapshot)
        (stage / "app.bin").write_bytes(b"nonempty-app")
        bad_tools = deepcopy(tools); bad_tools["isdDownload"]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            reverify(reference_root=REFERENCE_ROOT, sdk_root=SDK_ROOT, generated_sdk_root=generated, build_root=build, staging_root=stage, expected_source_commit=SOURCE_COMMIT, tools=bad_tools, expected_staging=snapshot)
        bad_receipt = deepcopy(receipt); bad_receipt["callerValidated"] = True
        (build / "build-receipt.json").write_text(json.dumps(bad_receipt, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="ascii")
        with self.assertRaises(ValueError):
            reverify(reference_root=REFERENCE_ROOT, sdk_root=SDK_ROOT, generated_sdk_root=generated, build_root=build, staging_root=stage, expected_source_commit=SOURCE_COMMIT, tools=tools, expected_staging=snapshot)

    def test_reverify_rejects_reference_loader_tool_build_and_generated_use_window_aba_before_commit(self):
        run_stage0_package = require_api(self, self.package, "run_stage0_package")
        fixture = stage0_package_fixture(); reference_root = self._copy_reference_root("toctou-reference"); sdk_root = self._copy_sdk_loader_root("toctou-sdk"); post_root = self._copy_post_root("toctou-post")
        build_root = self.base / "toctou-build"; self._build_receipt_fixture(build_root, fixture["app.bin"]); generated_root = self.base / "toctou-build-generated"
        lock_root = self._copy_lock_root("toctou-locks")
        authority_patch = mock.patch.object(
            self.package, "_validate_build_authority", create=True,
            side_effect=lambda **_kwargs: json.loads((build_root / "build-receipt.json").read_bytes()),
        )
        authority_patch.start(); self.addCleanup(authority_patch.stop)
        targets = [(f"reference:{relative}", reference_root / relative, "before-isdDownload") for relative in self.model_lock["referenceFiles"]]
        targets += [
            ("sdk-loader", sdk_root / self.model_lock["sdkLoader"]["sdkRelativePath"], "before-isdDownload"),
            ("tool:isdDownload", post_root / self.packaging_lock["tools"]["isdDownload"]["installRelativePath"], "before-isdDownload"),
            ("tool:ufwMaker", post_root / self.packaging_lock["tools"]["ufwMaker"]["installRelativePath"], "before-ufwMaker"),
            ("bootstrap-receipt", build_root / "bootstrap-receipt.json", "before-isdDownload"),
            ("elf", build_root / "sdk.elf", "before-isdDownload"),
            ("generated-elf", generated_root / "SDK/cpu/br35/tools/sdk.elf", "before-isdDownload"),
            ("app", build_root / "app.bin", "before-isdDownload"),
            ("build-receipt", build_root / "build-receipt.json", "before-isdDownload"),
            ("map", generated_root / "SDK/cpu/br35/tools/sdk.map", "before-isdDownload"),
        ]
        targets += [(f"section:{filename}", build_root / filename, "before-isdDownload") for _, filename in SECTIONS]
        targets += [(f"generated-overlay:{relative}", generated_root / relative, "before-isdDownload") for relative in BOOTSTRAP_OVERLAYS]
        targets += [(f"generated-patch:{relative}", generated_root / relative, "before-isdDownload") for relative in BOOTSTRAP_PATCH_TARGETS]
        targets += [(f"cpu-proof:{relative}", generated_root / relative, "before-isdDownload") for relative in ("SDK/Makefile", "SDK/build/Makefile.mk")]
        targets += [(f"object:{relative}", generated_root / "SDK/build" / relative, "before-isdDownload") for relative in OBJECTS]
        targets += [(f"lock:{filename}", lock_root / filename, "before-isdDownload") for filename in ("model1552-package.lock.json", "packaging.lock.json", "toolchain.lock.json")]
        deduplicated_targets = []; seen_targets = set()
        for record in targets:
            identity = str(record[1].resolve(strict=False))
            if identity not in seen_targets: seen_targets.add(identity); deduplicated_targets.append(record)
        targets = deduplicated_targets
        expected_bound_paths = {str((reference_root / relative).resolve(strict=False)) for relative in self.model_lock["referenceFiles"]}
        expected_bound_paths |= {
            str((sdk_root / self.model_lock["sdkLoader"]["sdkRelativePath"]).resolve(strict=False)),
            *(str((post_root / self.packaging_lock["tools"][name]["installRelativePath"]).resolve(strict=False)) for name in ("isdDownload", "ufwMaker")),
            str((build_root / "bootstrap-receipt.json").resolve(strict=False)), str((build_root / "build-receipt.json").resolve(strict=False)),
            str((build_root / "app.bin").resolve(strict=False)), str((build_root / "sdk.elf").resolve(strict=False)),
            str((generated_root / "SDK/cpu/br35/tools/sdk.elf").resolve(strict=False)), str((generated_root / "SDK/cpu/br35/tools/sdk.map").resolve(strict=False)),
            *(str((build_root / filename).resolve(strict=False)) for _, filename in SECTIONS),
            *(str((generated_root / relative).resolve(strict=False)) for relative in (*BOOTSTRAP_OVERLAYS, *BOOTSTRAP_PATCH_TARGETS, "SDK/Makefile", "SDK/build/Makefile.mk")),
            *(str((generated_root / "SDK/build" / relative).resolve(strict=False)) for relative in OBJECTS),
            *(str((lock_root / filename).resolve(strict=False)) for filename in ("model1552-package.lock.json", "packaging.lock.json", "toolchain.lock.json")),
        }
        self.assertEqual({str(path.resolve(strict=False)) for _, path, _ in targets}, expected_bound_paths)
        try:
            case = 0
            for label, path, mutation_phase in targets:
                for mode in ("bytes-one-way", "bytes-aba", "symlink-one-way", "symlink-aba"):
                    case += 1; run_root = self.base / f"toctou-run-{case}"; run_root.mkdir(); events = []; mutation_tokens = []
                    original = path.read_bytes(); original_mode = path.stat().st_mode & 0o777; parent_mode = path.parent.stat().st_mode & 0o777

                    def mutate_at_boundary(phase, *, target=path, expected_phase=mutation_phase, mutation_mode=mode):
                        if phase == expected_phase and not mutation_tokens:
                            mutation_tokens.extend(self._mutate_use_window_path(target, mutation_mode))

                    runner = FakeNativeRunner(artifacts=fixture, events=events)
                    try:
                        with self.subTest(target=label, mutation=mode), self.assertRaises(ValueError):
                            run_stage0_package(
                                build_root=build_root, expected_source_commit=SOURCE_COMMIT, event_sink=events.append,
                                generated_sdk_root=generated_root, lock_root=lock_root, post_root=post_root,
                                reference_root=reference_root, run_root=run_root, runner=runner, sdk_root=sdk_root,
                                use_window_hook=mutate_at_boundary,
                            )
                        self.assertEqual(len(mutation_tokens), 2); self.assertNotEqual(mutation_tokens[0], mutation_tokens[1])
                        self.assertEqual(len(runner.calls), 1 if label == "tool:ufwMaker" else 0)
                        self.assertFalse(any(event in events for event in ("evidence:committed", "metadata:committed", "receipt:committed")))
                        self.assertEqual(list(run_root.iterdir()), []); self.assertEqual(events[-1], "workspace:cleaned")
                        if mode.endswith("aba"):
                            self.assertFalse(path.is_symlink()); self.assertEqual(path.read_bytes(), original)
                    finally:
                        path.parent.chmod(path.parent.stat().st_mode | 0o700)
                        if path.is_symlink(): path.unlink()
                        if path.exists(): path.chmod(path.stat().st_mode | 0o600)
                        path.write_bytes(original); path.chmod(original_mode); path.parent.chmod(parent_mode)
            dynamic_targets = [(f"staged-first-use:{name}", Path("staging") / name, "before-isdDownload", 0) for name in sorted(STAGING_NAMES)]
            dynamic_targets += [("second-command-input:jl_isd.fw", Path("staging/jl_isd.fw"), "before-ufwMaker", 1)]
            dynamic_targets += [(f"native-output-through-validation:{name}", Path("staging") / name, "before-validation", 2) for name in ("jl_isd.bin", "jl_isd.fw", "update.ufw", "independently-made.ufw")]
            dynamic_case = 0
            for label, relative, mutation_phase, expected_calls in dynamic_targets:
                for mode in ("bytes-one-way", "bytes-aba", "symlink-one-way", "symlink-aba"):
                    dynamic_case += 1; run_root = self.base / f"dynamic-toctou-run-{dynamic_case}"; run_root.mkdir(); events = []; mutation_tokens = []; original_bytes = []
                    target_path = run_root / relative

                    def mutate_dynamic_boundary(phase, *, target=target_path, expected_phase=mutation_phase, mutation_mode=mode):
                        if phase == expected_phase and not mutation_tokens:
                            self.assertTrue(target.is_file() and not target.is_symlink())
                            original_bytes.append(target.read_bytes())
                            mutation_tokens.extend(self._mutate_use_window_path(target, mutation_mode))
                            if mutation_mode.endswith("aba"):
                                self.assertFalse(target.is_symlink()); self.assertEqual(target.read_bytes(), original_bytes[0])

                    runner = FakeNativeRunner(artifacts=fixture, events=events)
                    with self.subTest(dynamic_target=label, mutation=mode), self.assertRaises(ValueError):
                        run_stage0_package(
                            build_root=build_root, expected_source_commit=SOURCE_COMMIT, event_sink=events.append,
                            generated_sdk_root=generated_root, lock_root=lock_root, post_root=post_root,
                            reference_root=reference_root, run_root=run_root, runner=runner, sdk_root=sdk_root,
                            use_window_hook=mutate_dynamic_boundary,
                        )
                    self.assertEqual(len(original_bytes), 1); self.assertEqual(len(mutation_tokens), 2); self.assertNotEqual(mutation_tokens[0], mutation_tokens[1])
                    self.assertEqual(len(runner.calls), expected_calls)
                    self.assertFalse(any(event in events for event in ("evidence:committed", "metadata:committed", "receipt:committed")))
                    self.assertEqual(list(run_root.iterdir()), []); self.assertEqual(events[-1], "workspace:cleaned")
        finally:
            reference_root.chmod(0o755)
            for path in reference_root.rglob("*"): path.chmod(0o755 if path.is_dir() else 0o644)

    def test_package_rejects_self_consistent_app_receipt_forgery_before_native_runner(self):
        run_stage0_package = require_api(self, self.package, "run_stage0_package")
        validate_build_for_package = require_api(self, self.build, "validate_build_for_package")
        original_fixture = stage0_package_fixture(); changed_fixture = alternate_stage0_package_fixture()
        build_root = self.base / "forged-app-build"; self._build_receipt_fixture(build_root, original_fixture["app.bin"])
        generated_root = self.base / "forged-app-build-generated"
        changed_app = changed_fixture["app.bin"]
        self.assertEqual(len(changed_app), len(original_fixture["app.bin"])); self.assertNotEqual(changed_app, original_fixture["app.bin"])
        (build_root / "app.bin").write_bytes(changed_app)
        receipt_path = build_root / "build-receipt.json"; forged = json.loads(receipt_path.read_bytes())
        forged["app"] = {"filename": "app.bin", "sha256": hashlib.sha256(changed_app).hexdigest().upper(), "size": len(changed_app)}
        receipt_path.write_bytes((json.dumps(forged, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii"))
        lock_root = self._copy_lock_root("forged-app-locks"); run_root = self.base / "forged-app-run"; run_root.mkdir()
        replay_template = self.base / "forged-app-replay-template"; self._write_generated_sdk_fixture(replay_template)
        replay_runner = FakeBootstrapRawRunner(); replay_producer = FakeBootstrapProducer(replay_template, run_root / "control")
        native_runner = FakeNativeRunner(artifacts=changed_fixture)
        with (
            mock.patch.object(self.package, "_load_build_tool", return_value=self.build, create=True),
            mock.patch.object(self.build, "_load_bootstrap_tool", return_value=replay_producer, create=True),
            mock.patch.object(self.build, "validate_build_for_package", wraps=validate_build_for_package) as authority,
            mock.patch("subprocess.run", new=replay_runner),
            self.assertRaisesRegex(ValueError, "(?i)(app|section|build)"),
        ):
            run_stage0_package(
                generated_sdk_root=generated_root, build_root=build_root, reference_root=REFERENCE_ROOT,
                run_root=run_root, expected_source_commit=SOURCE_COMMIT, lock_root=lock_root,
                runner=native_runner, sdk_root=SDK_ROOT,
            )
        authority.assert_called_once()
        self.assertEqual(len(replay_runner.calls), 31); self.assertEqual(native_runner.calls, [])
        self.assertFalse((run_root / "staging").exists()); self.assertEqual(list(run_root.iterdir()), [])

    def test_build_authority_rejects_tampered_execution_evidence_before_package_native_runner(self):
        validate_build_for_package = require_api(self, self.build, "validate_build_for_package")
        validate_package_authority = require_api(self, self.package, "_validate_build_authority")
        fixture = stage0_package_fixture(); build_root = self.base / "tampered-build-authority"
        original = self._build_receipt_fixture(build_root, fixture["app.bin"])
        receipt_path = build_root / "build-receipt.json"
        generated_root = self.base / "tampered-build-authority-generated"
        control_root = self.base / "tampered-build-authority-control"; control_root.mkdir()

        def canonical(value: dict[str, object]) -> bytes:
            return (json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii")

        def different_valid_hex(value: str) -> str:
            decoded = bytes.fromhex(value)
            if not decoded:
                return "00"
            changed = bytearray(decoded); changed[0] ^= 0xFF
            return bytes(changed).hex().upper()

        def reject(label: str, mutate) -> None:
            changed = deepcopy(original); mutate(changed); receipt_path.write_bytes(canonical(changed))
            try:
                with (
                    mock.patch.object(self.build, "derive_expected_bootstrap_evidence", autospec=True, side_effect=self._independent_bootstrap_derivation),
                    self.subTest(authority_receipt=label),
                    self.assertRaises(ValueError),
                ):
                    validate_build_for_package(
                        generated_sdk_root=generated_root,
                        build_root=build_root,
                        bootstrap_receipt_path=build_root / "bootstrap-receipt.json",
                        control_root=control_root,
                        expected_source_commit=SOURCE_COMMIT,
                        runner=mock.Mock(),
                    )
            finally:
                receipt_path.write_bytes(canonical(original))

        for key in normalized_build_environment():
            reject(
                f"environment-missing-{key}",
                lambda value, name=key: value["environment"].pop(name),
            )
            reject(
                f"environment-value-{key}",
                lambda value, name=key: value["environment"].__setitem__(name, "VALID_BUT_WRONG"),
            )
            reject(
                f"environment-type-{key}",
                lambda value, name=key: value["environment"].__setitem__(name, 7),
            )
        reject("environment-missing", lambda value: value.pop("environment"))
        reject("environment-unknown", lambda value: value["environment"].__setitem__("INHERITED", "1"))
        reject("environment-type", lambda value: value.__setitem__("environment", []))
        for label, replacement in (
            ("missing", None),
            ("empty", {}),
            ("low", {"nofileSoft": 8191}),
            ("high-drift", {"nofileSoft": 8193}),
            ("type", {"nofileSoft": "8192"}),
            ("unknown", {"nofileSoft": 8192, "hard": 16384}),
            ("whole-type", []),
        ):
            if replacement is None:
                reject(f"resource-{label}", lambda value: value.pop("resourceLimits"))
            else:
                reject(f"resource-{label}", lambda value, changed=deepcopy(replacement): value.__setitem__("resourceLimits", changed))
        for validation_name in BUILD_VALIDATIONS:
            reject(
                f"validation-missing-{validation_name}",
                lambda value, name=validation_name: value["validations"].pop(name),
            )
            reject(
                f"validation-false-{validation_name}",
                lambda value, name=validation_name: value["validations"].__setitem__(name, False),
            )
            reject(
                f"validation-type-{validation_name}",
                lambda value, name=validation_name: value["validations"].__setitem__(name, 1),
            )
        reject("validations-unknown", lambda value: value["validations"].__setitem__("callerValidated", True))
        reject("validations-missing", lambda value: value.pop("validations"))
        reject("validations-type", lambda value: value.__setitem__("validations", []))

        for collection in ("commands", "versionProbes"):
            for index, record in enumerate(original[collection]):
                reject(
                    f"{collection}-{index}-cwd-value",
                    lambda value, field=collection, position=index: value[field][position].__setitem__("cwd", "$OTHER_ROOT"),
                )
                reject(
                    f"{collection}-{index}-cwd-missing",
                    lambda value, field=collection, position=index: value[field][position].pop("cwd"),
                )
                reject(
                    f"{collection}-{index}-cwd-type",
                    lambda value, field=collection, position=index: value[field][position].__setitem__("cwd", 7),
                )
                for key in normalized_build_environment():
                    reject(
                        f"{collection}-{index}-environment-missing-{key}",
                        lambda value, field=collection, position=index, name=key: value[field][position]["environment"].pop(name),
                    )
                    reject(
                        f"{collection}-{index}-environment-value-{key}",
                        lambda value, field=collection, position=index, name=key: value[field][position]["environment"].__setitem__(name, "VALID_BUT_WRONG"),
                    )
                    reject(
                        f"{collection}-{index}-environment-type-{key}",
                        lambda value, field=collection, position=index, name=key: value[field][position]["environment"].__setitem__(name, 7),
                    )
                reject(
                    f"{collection}-{index}-environment-missing",
                    lambda value, field=collection, position=index: value[field][position].pop("environment"),
                )
                reject(
                    f"{collection}-{index}-environment-unknown",
                    lambda value, field=collection, position=index: value[field][position]["environment"].__setitem__("INHERITED", "1"),
                )
                reject(
                    f"{collection}-{index}-environment-type",
                    lambda value, field=collection, position=index: value[field][position].__setitem__("environment", []),
                )
                reject(
                    f"{collection}-{index}-record-unknown",
                    lambda value, field=collection, position=index: value[field][position].__setitem__("callerValidated", True),
                )
                for stream in ("stdout", "stderr"):
                    for suffix, replacement in (
                        ("Hex", different_valid_hex(str(record[f"{stream}Hex"]))),
                        ("Size", int(record[f"{stream}Size"]) + 1),
                        ("Sha256", "A" * 64),
                    ):
                        field_name = f"{stream}{suffix}"
                        reject(
                            f"{collection}-{index}-{field_name}-value",
                            lambda value, field=collection, position=index, name=field_name, changed=replacement: value[field][position].__setitem__(name, changed),
                        )
                        reject(
                            f"{collection}-{index}-{field_name}-missing",
                            lambda value, field=collection, position=index, name=field_name: value[field][position].pop(name),
                        )

        tampered = deepcopy(original)
        replacement_sha = "A" * 64
        if tampered["commands"][0]["stdoutSha256"] == replacement_sha: replacement_sha = "B" * 64
        tampered["commands"][0]["stdoutSha256"] = replacement_sha
        tampered_raw = canonical(tampered); receipt_path.write_bytes(tampered_raw)
        run_root = self.base / "tampered-build-package-run"; run_root.mkdir()
        native_runner = FakeNativeRunner(artifacts=fixture)
        with (
            mock.patch.object(self.package, "_load_build_tool", return_value=self.build, create=True),
            mock.patch.object(self.build, "derive_expected_bootstrap_evidence", autospec=True, side_effect=self._independent_bootstrap_derivation),
            mock.patch.object(self.package, "_read_build_receipt", autospec=True, return_value=(tampered, tampered_raw)),
            mock.patch.object(self.package, "_validate_build_authority", wraps=validate_package_authority) as authority,
            self.assertRaises(ValueError),
        ):
            self.package.run_stage0_package(
                generated_sdk_root=generated_root,
                build_root=build_root,
                reference_root=REFERENCE_ROOT,
                run_root=run_root,
                expected_source_commit=SOURCE_COMMIT,
                lock_root=self._copy_lock_root("tampered-build-authority-locks"),
                runner=native_runner,
                sdk_root=SDK_ROOT,
            )
        authority.assert_called_once(); self.assertEqual(native_runner.calls, [])
        self.assertFalse((run_root / "staging").exists()); self.assertEqual(list(run_root.iterdir()), [])

    def test_build_cleanup_preserves_rebound_root_and_parent_sentinels(self):
        run_target_build = require_api(self, self.build, "run_target_build")
        elf, _, section_bytes = make_elf32_fixture()
        for scope in ("root", "parent"):
            for mode in ("one-way", "aba"):
                case = f"build-cleanup-{scope}-{mode}"
                generated = self.base / f"{case}-generated"; bootstrap_path, _ = self._write_generated_sdk_fixture(generated)
                container = self.base / f"{case}-container"; container.mkdir(); build_root = container / "build"; build_root.mkdir()
                control = self.base / f"{case}-control"; control.mkdir(); rebound = []

                class RebindBuildEvents(list):
                    def append(inner_self, event):
                        super().append(event)
                        if event == "receipt:committed" and not rebound:
                            target = build_root if scope == "root" else container
                            sentinel_relative = Path("sentinel.bin") if scope == "root" else Path("build/sentinel.bin")
                            rebound.append(self._rebind_directory_for_test(target, sentinel_relative=sentinel_relative, mode=mode))
                            if mode == "one-way": raise RuntimeError("synthetic failure after build receipt")

                events = RebindBuildEvents()
                expected_error = RuntimeError if mode == "one-way" else ValueError
                with (
                    mock.patch.object(self.build, "derive_expected_bootstrap_evidence", autospec=True, side_effect=self._independent_bootstrap_derivation),
                    mock.patch.object(self.build, "build_receipt", autospec=True, return_value={"schema": "synthetic-cleanup-receipt"}),
                    self.subTest(build_cleanup=(scope, mode)), self.assertRaises(expected_error),
                ):
                    run_target_build(
                        generated_sdk_root=generated, bootstrap_receipt_path=bootstrap_path, build_root=build_root,
                        control_root=control, expected_source_commit=SOURCE_COMMIT, make_tool=MAKE_TOOL,
                        runner=FakeBuildRunner(elf, section_bytes), version_runner=FakeVersionRunner(), event_sink=events.append,
                    )
                evidence = rebound[0]; sentinel = Path(evidence["sentinel"])
                self.assertTrue(sentinel.is_file(), "cleanup deleted a replacement-tree sentinel it did not own")
                self.assertEqual(sentinel.read_bytes(), evidence["sentinelBytes"]); self.assertFalse(sentinel.is_symlink())
                if mode == "one-way":
                    retained = Path(evidence["original"]) / ("build/build-receipt.json" if scope == "parent" else "build-receipt.json")
                    self.assertTrue(retained.is_file(), "cleanup must not traverse a replacement root")

    def test_package_cleanup_preserves_rebound_run_root_and_parent_sentinels(self):
        run_stage0_package = require_api(self, self.package, "run_stage0_package")
        fixture = stage0_package_fixture(); build_root = self.base / "package-rebind-build"; build_receipt = self._build_receipt_fixture(build_root, fixture["app.bin"])
        generated_root = self.base / "package-rebind-build-generated"; lock_root = self._copy_lock_root("package-rebind-locks")
        for scope in ("root", "parent"):
            for mode in ("one-way", "aba"):
                container = self.base / f"package-cleanup-{scope}-{mode}-container"; container.mkdir(); run_root = container / "run"; run_root.mkdir(); rebound = []

                def rebind_before_validation(phase: str) -> None:
                    if phase == "before-validation" and not rebound:
                        target = run_root if scope == "root" else container
                        sentinel_relative = Path("sentinel.bin") if scope == "root" else Path("run/sentinel.bin")
                        rebound.append(self._rebind_directory_for_test(target, sentinel_relative=sentinel_relative, mode=mode))

                with (
                    mock.patch.object(self.package, "_validate_build_authority", create=True, return_value=build_receipt),
                    mock.patch.object(self.package, "_read_build_receipt", autospec=True, return_value=(build_receipt, (build_root / "build-receipt.json").read_bytes())),
                    self.subTest(package_cleanup=(scope, mode)), self.assertRaises(ValueError),
                ):
                    run_stage0_package(
                        generated_sdk_root=generated_root, build_root=build_root, reference_root=REFERENCE_ROOT,
                        run_root=run_root, expected_source_commit=SOURCE_COMMIT, lock_root=lock_root,
                        runner=FakeNativeRunner(artifacts=fixture), sdk_root=SDK_ROOT,
                        use_window_hook=rebind_before_validation,
                    )
                evidence = rebound[0]; sentinel = Path(evidence["sentinel"])
                self.assertTrue(sentinel.is_file(), "cleanup deleted a replacement-tree sentinel it did not own")
                self.assertEqual(sentinel.read_bytes(), evidence["sentinelBytes"]); self.assertFalse(sentinel.is_symlink())
                if mode == "one-way":
                    retained = Path(evidence["original"]) / ("run/staging/app.bin" if scope == "parent" else "staging/app.bin")
                    self.assertTrue(retained.is_file(), "package cleanup must skip a replacement root")

    def test_build_nofile_limit_is_exact_and_fails_before_any_runner(self):
        ensure_limit = require_api(self, self.build, "ensure_nofile_limit")
        setter = mock.Mock(); resource_id = object()
        result = ensure_limit(
            resource_id=resource_id,
            getrlimit=lambda requested: (4096, 16384) if requested is resource_id else (_ for _ in ()).throw(AssertionError("wrong resource")),
            setrlimit=setter,
        )
        self.assertEqual(result, BUILD_RESOURCE_LIMITS); setter.assert_called_once_with(resource_id, (8192, 16384))
        setter.reset_mock()
        self.assertEqual(ensure_limit(resource_id=resource_id, getrlimit=lambda _requested: (8192, 16384), setrlimit=setter), BUILD_RESOURCE_LIMITS)
        setter.assert_not_called()
        for hard in (0, 8191):
            with self.subTest(hard=hard), self.assertRaisesRegex(ValueError, "(?i)(nofile|8192)"):
                ensure_limit(resource_id=resource_id, getrlimit=lambda _requested, limit=hard: (4096, limit), setrlimit=setter)

        generated = self.base / "nofile-fail-generated"; bootstrap_path, _ = self._write_generated_sdk_fixture(generated)
        build_root = self.base / "nofile-fail-build"; build_root.mkdir(); control = self.base / "nofile-fail-control"; control.mkdir()
        elf, _, section_bytes = make_elf32_fixture(); runner = FakeBuildRunner(elf, section_bytes); versions = FakeVersionRunner()
        with (
            mock.patch.object(self.build, "ensure_nofile_limit", autospec=True, side_effect=ValueError("RLIMIT_NOFILE hard limit below 8192")),
            mock.patch.object(self.build, "derive_expected_bootstrap_evidence", autospec=True) as replay,
            self.assertRaisesRegex(ValueError, "RLIMIT_NOFILE"),
        ):
            self.build.run_target_build(
                generated_sdk_root=generated, bootstrap_receipt_path=bootstrap_path, build_root=build_root,
                control_root=control, expected_source_commit=SOURCE_COMMIT, make_tool=MAKE_TOOL,
                runner=runner, version_runner=versions,
            )
        replay.assert_not_called(); self.assertEqual(runner.calls, []); self.assertEqual(versions.calls, []); self.assertEqual(list(build_root.iterdir()), [])

        inherited_generated = self.base / "nofile-positive-generated"; inherited_bootstrap, _ = self._write_generated_sdk_fixture(inherited_generated)
        inherited_build = self.base / "nofile-positive-build"; inherited_build.mkdir(); inherited_control = self.base / "nofile-positive-control"; inherited_control.mkdir()
        inherited_runner = FakeBuildRunner(elf, section_bytes); inherited_versions = FakeVersionRunner(); observed_soft = []
        original_limit = resource.getrlimit(resource.RLIMIT_NOFILE)

        def observe_build(*args, **kwargs):
            observed_soft.append(resource.getrlimit(resource.RLIMIT_NOFILE)[0]); return inherited_runner(*args, **kwargs)

        def observe_version(*args, **kwargs):
            observed_soft.append(resource.getrlimit(resource.RLIMIT_NOFILE)[0]); return inherited_versions(*args, **kwargs)

        with mock.patch.object(self.build, "derive_expected_bootstrap_evidence", autospec=True, side_effect=self._independent_bootstrap_derivation):
            positive_receipt = self.build.run_target_build(
                generated_sdk_root=inherited_generated, bootstrap_receipt_path=inherited_bootstrap, build_root=inherited_build,
                control_root=inherited_control, expected_source_commit=SOURCE_COMMIT, make_tool=MAKE_TOOL,
                runner=observe_build, version_runner=observe_version,
            )
        self.assertEqual(observed_soft, [8192] * 15)
        self.assertEqual(resource.getrlimit(resource.RLIMIT_NOFILE), original_limit)
        self.assertEqual(positive_receipt["resourceLimits"], BUILD_RESOURCE_LIMITS)

    def test_orchestrator_consumes_real_jlfw_stage0_ufw_and_qix_proofs_and_cross_binds_every_payload(self):
        validate_outputs = require_api(self, self.package, "validate_package_outputs")
        fixture = stage0_package_fixture(); staging = self.base / "proof-staging"; staging.mkdir()
        for name, data in fixture.items(): (staging / name).write_bytes(data)
        qix_name = f"E87-11.1.0.3-{SOURCE_COMMIT[:8].upper()}.qix"; (staging / qix_name).write_bytes(self.qix.wrap_qix(fixture["update.ufw"], "11.1.0.3"))
        app_record = {"filename": "app.bin", "sha256": hashlib.sha256(fixture["app.bin"]).hexdigest().upper(), "size": len(fixture["app.bin"])}
        ini_sha = "05662B8EBF6FB08A9E07611D680C293B023C7B802F82AE0A4CCC7E2ED50639F3"
        proof = validate_outputs(staging, app_record=app_record, expected_source_commit=SOURCE_COMMIT, staged_ini_sha256=ini_sha, qix_name=qix_name, qix_version="11.1.0.3")
        self.assertEqual(set(proof), {"jlfw", "qix", "resetPolicy", "ufw"})
        self.assertEqual(proof["jlfw"]["appSha256"], app_record["sha256"])
        self.assertNotEqual(app_record["sha256"], "A38B77E27B1DC73CAE0FBD8A7C4E3A04C64FF393FB4F27BC92A7578336BE0147")
        self.assertEqual(proof["jlfw"]["flashSha256"], proof["ufw"]["native"]["flashSha256"])
        self.assertEqual(proof["ufw"]["native"]["sha256"], proof["ufw"]["independent"]["sha256"])
        self.assertEqual(proof["qix"]["payloadSha256"], proof["qix"]["unwrappedPayloadSha256"])
        self.assertEqual(proof["qix"]["payloadSha256"], proof["ufw"]["native"]["sha256"])
        self.assertNotIn("passed", json.dumps(proof, sort_keys=True))
        for label, changed_app, changed_ini, changed_name in (
            ("app-sha", {**app_record, "sha256": "0" * 64}, ini_sha, qix_name),
            ("app-size", {**app_record, "size": app_record["size"] - 1}, ini_sha, qix_name),
            ("ini-sha", app_record, "0" * 64, qix_name),
        ):
            with self.subTest(relation=label), self.assertRaises(ValueError):
                validate_outputs(staging, app_record=changed_app, expected_source_commit=SOURCE_COMMIT, staged_ini_sha256=changed_ini, qix_name=changed_name, qix_version="11.1.0.3")
        alternate = alternate_stage0_package_fixture()
        for filename in ("jl_isd.bin", "jl_isd.fw", "update.ufw", "independently-made.ufw"):
            path = staging / filename; original = path.read_bytes(); path.write_bytes(alternate[filename])
            with self.subTest(relation=filename), self.assertRaises(ValueError):
                validate_outputs(staging, app_record=app_record, expected_source_commit=SOURCE_COMMIT, staged_ini_sha256=ini_sha, qix_name=qix_name, qix_version="11.1.0.3")
            path.write_bytes(original)
        qix_path = staging / qix_name; original_qix = qix_path.read_bytes()
        qix_path.unlink(); wrong_qix_name = "E87-11.1.0.3-DEADBEEF.qix"; (staging / wrong_qix_name).write_bytes(original_qix)
        with self.assertRaises(ValueError): validate_outputs(staging, app_record=app_record, expected_source_commit=SOURCE_COMMIT, staged_ini_sha256=ini_sha, qix_name=wrong_qix_name, qix_version="11.1.0.3")
        (staging / wrong_qix_name).unlink(); qix_path.write_bytes(original_qix)
        with self.assertRaises(ValueError): validate_outputs(staging, app_record=app_record, expected_source_commit="f" * 40, staged_ini_sha256=ini_sha, qix_name=qix_name, qix_version="11.1.0.3")
        qix_path.write_bytes(self.qix.wrap_qix(fixture["update.ufw"], "11.1.0.2"))
        with self.assertRaises(ValueError): validate_outputs(staging, app_record=app_record, expected_source_commit=SOURCE_COMMIT, staged_ini_sha256=ini_sha, qix_name=qix_name, qix_version="11.1.0.3")
        qix_path.write_bytes(self.qix.wrap_qix(alternate["update.ufw"], "11.1.0.3"))
        with self.assertRaises(ValueError): validate_outputs(staging, app_record=app_record, expected_source_commit=SOURCE_COMMIT, staged_ini_sha256=ini_sha, qix_name=qix_name, qix_version="11.1.0.3")
        qix_path.write_bytes(original_qix)

    def test_real_target_build_output_feeds_package_without_manual_bootstrap_copy(self):
        run_target_build = require_api(self, self.build, "run_target_build")
        run_stage0_package = require_api(self, self.package, "run_stage0_package")
        require_api(self, self.build, "validate_build_for_package")
        fixture = stage0_package_fixture(); app = fixture["app.bin"]
        chunks = [app[index:index + 1] for index in range(len(SECTIONS) - 1)] + [app[len(SECTIONS) - 1:]]
        section_bytes = {section: chunk for (section, _), chunk in zip(SECTIONS, chunks, strict=True)}
        elf, _, section_bytes = make_elf32_fixture(section_bytes)
        generated = self.base / "direct-generated"
        external_bootstrap = self.base / "external-bootstrap-name.json"
        bootstrap_path, bootstrap = self._write_generated_sdk_fixture(generated, receipt_path=external_bootstrap)
        self.assertEqual(bootstrap_path, external_bootstrap); self.assertNotEqual(bootstrap_path.parent, generated)
        replay_template = self.base / "direct-replay-template"; self._write_generated_sdk_fixture(replay_template)
        build_root = self.base / "direct-build"; build_root.mkdir(); build_control = self.base / "direct-build-control"; build_control.mkdir()
        build_replay_runner = FakeBootstrapRawRunner(); build_replay_producer = FakeBootstrapProducer(replay_template, build_control)
        with mock.patch.object(self.build, "_load_bootstrap_tool", return_value=build_replay_producer, create=True), mock.patch("subprocess.run", new=build_replay_runner):
            build_receipt = run_target_build(
                generated_sdk_root=generated, bootstrap_receipt_path=bootstrap_path, build_root=build_root,
                control_root=build_control, expected_source_commit=SOURCE_COMMIT, make_tool=MAKE_TOOL,
                runner=FakeBuildRunner(elf, section_bytes), version_runner=FakeVersionRunner(),
            )
        expected_build_names = {"app.bin", "bootstrap-receipt.json", "build-receipt.json", "sdk.elf", *[filename for _, filename in SECTIONS]}
        self.assertEqual(set(path.name for path in build_root.iterdir()), expected_build_names)
        self.assertEqual((build_root / "bootstrap-receipt.json").read_bytes(), external_bootstrap.read_bytes())
        self.assertEqual(build_receipt["bootstrapReceipt"]["filename"], "bootstrap-receipt.json")
        self.assertEqual((build_root / "app.bin").read_bytes(), app)

        run_root = self.base / "direct-package-run"; run_root.mkdir(); lock_root = self._copy_lock_root("direct-package-locks")
        package_replay_runner = FakeBootstrapRawRunner(); package_replay_producer = FakeBootstrapProducer(replay_template, run_root / "control")
        native_runner = FakeNativeRunner(artifacts=fixture)
        with (
            mock.patch.object(self.package, "_load_build_tool", return_value=self.build, create=True),
            mock.patch.object(self.build, "_load_bootstrap_tool", return_value=package_replay_producer, create=True),
            mock.patch("subprocess.run", new=package_replay_runner),
        ):
            package_receipt = run_stage0_package(
                generated_sdk_root=generated, build_root=build_root, reference_root=REFERENCE_ROOT,
                run_root=run_root, expected_source_commit=SOURCE_COMMIT, lock_root=lock_root,
                runner=native_runner, sdk_root=SDK_ROOT,
            )
        self.assertEqual(len(package_replay_runner.calls), 31); self.assertEqual(len(native_runner.calls), 2)
        self.assertEqual(package_receipt["app"], build_receipt["app"])
        self.assertEqual(set(path.name for path in run_root.iterdir()), {"delivery", "evidence"})
        self.assertEqual((run_root / "delivery/app.bin").read_bytes(), app)

    def test_run_stage0_package_e2e_uses_fake_native_runner_and_cleans_workspace(self):
        run_stage0_package = require_api(self, self.package, "run_stage0_package")
        fixture = stage0_package_fixture(); build_root = self.base / "e2e-build"; build_receipt = self._build_receipt_fixture(build_root, fixture["app.bin"])
        generated_root = self.base / "e2e-build-generated"; lock_root = self._copy_lock_root("e2e-locks")
        authority_patch = mock.patch.object(
            self.package, "_validate_build_authority", create=True,
            side_effect=lambda **_kwargs: json.loads((build_root / "build-receipt.json").read_bytes()),
        )
        authority_patch.start(); self.addCleanup(authority_patch.stop)
        build_receipt_bytes = (build_root / "build-receipt.json").read_bytes()
        expected_staging = self.base / "e2e-expected-staging"; expected_inputs = self._write_exact_staging_fixture(expected_staging, fixture["app.bin"])
        run_root = self.base / "e2e-run"; run_root.mkdir(); events = []
        runner = FakeNativeRunner(artifacts=fixture, events=events)
        receipt = call_contract(
            self, "unmocked Stage0 package orchestration", run_stage0_package,
            build_root=build_root, expected_source_commit=SOURCE_COMMIT, event_sink=events.append,
            generated_sdk_root=generated_root, lock_root=lock_root, reference_root=REFERENCE_ROOT, run_root=run_root, runner=runner,
            sdk_root=SDK_ROOT,
        )
        qix_name = f"E87-11.1.0.3-{SOURCE_COMMIT[:8].upper()}.qix"
        expected_environment = {
            "HOME": str(run_root / "control/home"), "LANG": "C", "LC_ALL": "C",
            "PATH": f"{POST_ROOT}:/usr/bin:/bin", "SOURCE_DATE_EPOCH": str(SOURCE_DATE_EPOCH),
            "TMPDIR": str(run_root / "control/tmp"), "TZ": "UTC",
        }
        self.assertEqual([call[0] for call in runner.calls], [
            [str(POST_ROOT / "isd_download"), *ISD_ARGUMENTS],
            [str(POST_ROOT / "ufw_maker"), "--fw", "jl_isd.fw", "--output", "independently-made.ufw"],
        ])
        for _, kwargs in runner.calls:
            self.assertEqual(Path(kwargs["cwd"]), run_root / "staging"); self.assertEqual(kwargs["env"], expected_environment)
            self.assertIs(kwargs["shell"], False); self.assertIs(kwargs["check"], False)
            self.assertEqual((kwargs["stdin"], kwargs["stdout"], kwargs["stderr"]), (subprocess.DEVNULL, subprocess.PIPE, subprocess.PIPE))
        claimed_commands = self._native_command_receipts(); expected_commands = []
        self.assertEqual(len(runner.results), 2)
        observed_streams = []
        for claimed, (tool, result) in zip(claimed_commands, runner.results):
            self.assertEqual((tool, list(result.args), result.returncode), (Path(claimed["argv"][0]).name, claimed["argv"], 0))
            self.assertEqual(result.stdout, NATIVE_SUCCESS_STREAMS[tool]["stdout"])
            self.assertEqual(result.stderr, NATIVE_SUCCESS_STREAMS[tool]["stderr"])
            self.assertIn(b"\x00", result.stdout); self.assertIn(b"\xff", result.stdout)
            self.assertIn(b"\x00", result.stderr); self.assertIn(b"\xff", result.stderr)
            self.assertGreater(len(result.stdout), 4096); self.assertGreater(len(result.stderr), 4096)
            observed_streams.extend((result.stdout, result.stderr))
            expected_commands.append({
                **claimed,
                "exitCode": result.returncode,
                "stderrHex": result.stderr.hex().upper(),
                "stderrSha256": hashlib.sha256(result.stderr).hexdigest().upper(),
                "stderrSize": len(result.stderr),
                "stdoutHex": result.stdout.hex().upper(),
                "stdoutSha256": hashlib.sha256(result.stdout).hexdigest().upper(),
                "stdoutSize": len(result.stdout),
            })
        self.assertEqual(len({value for value in observed_streams}), 4)
        expected_summaries = self._native_command_summaries(expected_commands)
        self.assertEqual(events, [
            "roots:validated", "locks:reopened", "build-receipt:reopened", "reference:reopened", "inputs:staged",
            "tool:isdDownload:rehashed", "inputs:isdDownload:rehashed", "runner:isd_download", "outputs:isdDownload:validated",
            "tool:ufwMaker:rehashed", "inputs:ufwMaker:rehashed", "runner:ufw_maker", "outputs:ufwMaker:validated",
            "proof:jlfw", "proof:ufw", "qix:wrapped", "proof:qix", "evidence:committed", "metadata:committed",
            "receipt:committed", "workspace:cleaned",
        ])
        delivery = run_root / "delivery"; evidence = run_root / "evidence"
        self.assertEqual(set(path.name for path in run_root.iterdir()), {"delivery", "evidence"})
        self.assertEqual(set(path.name for path in delivery.iterdir()), {"app.bin", "jl_isd.fw", "update.ufw", qix_name, "manifest.json", "SHA256SUMS"})
        self.assertEqual(set(path.name for path in evidence.iterdir()), {"build-receipt.json", "independently-made.ufw", "jl_isd.bin", "native-execution.json", "package-evidence.json", "package-receipt.json", "validation.json"})
        self.assertEqual((evidence / "build-receipt.json").read_bytes(), build_receipt_bytes)

        def read_canonical_json(path: Path) -> dict[str, object]:
            raw = path.read_bytes(); value = json.loads(raw)
            self.assertEqual(raw, (json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii"))
            return value

        native_execution = read_canonical_json(evidence / "native-execution.json")
        validations = read_canonical_json(evidence / "validation.json")
        package_evidence = read_canonical_json(evidence / "package-evidence.json")
        on_disk_receipt = read_canonical_json(evidence / "package-receipt.json")
        manifest = read_canonical_json(delivery / "manifest.json")
        self.assertEqual(native_execution, {"commands": expected_commands, "environment": expected_environment, "inputs": expected_inputs, "schema": "e87-stage0-native-execution-v1"})
        for record, (tool, _) in zip(native_execution["commands"], runner.results):
            for stream in ("stdout", "stderr"):
                expected_raw = NATIVE_SUCCESS_STREAMS[tool][stream]
                self.assertEqual(bytes.fromhex(record[f"{stream}Hex"]), expected_raw)
                self.assertEqual(record[f"{stream}Size"], len(expected_raw))
                self.assertEqual(record[f"{stream}Sha256"], hashlib.sha256(expected_raw).hexdigest().upper())
        expected_validations = self._real_package_proofs(fixture, (delivery / qix_name).read_bytes())
        self.assertEqual(validations, {"schema": "e87-stage0-package-validation-v1", "validations": expected_validations})
        self.assertEqual(receipt, on_disk_receipt)
        self.assertEqual(on_disk_receipt, {**package_evidence, "schema": "e87-stage0-package-receipt-v1"})
        self.assertEqual(package_evidence["schema"], "e87-stage0-package-evidence-v1")
        self.assertEqual(receipt["commands"], expected_summaries)
        build_receipt_sha = hashlib.sha256(build_receipt_bytes).hexdigest().upper()
        self.assertEqual(receipt["buildReceiptSha256"], build_receipt_sha)
        self.assertEqual(package_evidence["buildReceiptSha256"], build_receipt_sha)
        self.assertEqual(receipt["app"], build_receipt["app"]); self.assertEqual(receipt["sourceCommit"], SOURCE_COMMIT); self.assertEqual(receipt["buildTag"], SOURCE_COMMIT[:8].upper())
        self.assertEqual(receipt["validations"], expected_validations)
        self.assertEqual((build_receipt["bootstrap"]["sourceCommitEpoch"], build_receipt["sourceDateEpoch"], int(native_execution["environment"]["SOURCE_DATE_EPOCH"]), receipt["sourceDateEpoch"]), (SOURCE_DATE_EPOCH,) * 4)
        self.assertEqual(receipt["identities"]["sourceCommitObjectSha256"], build_receipt["bootstrap"]["sourceCommitObjectSha256"])
        self.assertEqual(manifest["sourceCommit"], SOURCE_COMMIT); self.assertEqual(manifest["buildTag"], SOURCE_COMMIT[:8].upper())
        self.assertEqual(manifest["nativeCommands"], expected_summaries); self.assertEqual(manifest["identities"], receipt["identities"])
        self.assertEqual(manifest["target"], receipt["target"]); self.assertEqual(manifest["qix"], receipt["qix"]); self.assertEqual(manifest["resetPolicy"], receipt["resetPolicy"])
        artifact_paths = {
            "app.bin": delivery / "app.bin", "jl_isd.fw": delivery / "jl_isd.fw", "update.ufw": delivery / "update.ufw", qix_name: delivery / qix_name,
            "jl_isd.bin": evidence / "jl_isd.bin", "independently-made.ufw": evidence / "independently-made.ufw",
        }
        evidence_outputs = {item["filename"]: item for item in receipt["outputs"]}; self.assertEqual(set(evidence_outputs), set(artifact_paths))
        for name, path in artifact_paths.items():
            data = path.read_bytes(); self.assertEqual(evidence_outputs[name], {"filename": name, "sha256": hashlib.sha256(data).hexdigest().upper(), "size": len(data)})
        manifest_outputs = {item["filename"]: item for item in manifest["outputs"]}
        self.assertEqual(set(manifest_outputs), set(artifact_paths))
        self.assertEqual(manifest_outputs["app.bin"]["sha256"], build_receipt["app"]["sha256"])
        self.assertEqual(self.qix.parse_qix((delivery / qix_name).read_bytes(), expected_version="11.1.0.3")["payload"], (delivery / "update.ufw").read_bytes())
        self.assertEqual(self.jlfw.prove_package_pair((evidence / "jl_isd.bin").read_bytes(), (delivery / "jl_isd.fw").read_bytes(), (delivery / "app.bin").read_bytes())["appSha256"], build_receipt["app"]["sha256"])
        sums = (delivery / "SHA256SUMS").read_text(encoding="ascii").splitlines(); self.assertEqual(len(sums), 5)
        self.assertEqual([line.split("  ", 1)[1] for line in sums], sorted(line.split("  ", 1)[1] for line in sums))
        for line in sums:
            digest, filename = line.split("  ", 1); self.assertEqual(digest, hashlib.sha256((delivery / filename).read_bytes()).hexdigest().upper())
        complete = require_api(self, self.package, "validate_complete_run")(run_root)
        self.assertEqual(complete["buildReceiptSha256"], build_receipt_sha)
        self.assertNotIn("passed", json.dumps(receipt, sort_keys=True))

        failures = [(f"nonzero-{tool}", FakeNativeRunner("nonzero", fail_tool=tool, artifacts=fixture), None) for tool in ("isd_download", "ufw_maker")]
        failures += [(f"corrupt-{name}", FakeNativeRunner("corrupt-output", artifacts=fixture, corrupt_output=name), None) for name in ("jl_isd.bin", "jl_isd.fw", "update.ufw", "independently-made.ufw")]
        failures += [(f"late-{event}", FakeNativeRunner(artifacts=fixture), event) for event in ("proof:qix", "evidence:committed", "metadata:committed")]
        for index, (label, failure_runner, failing_event) in enumerate(failures):
            failure_root = self.base / f"e2e-failure-{index}"; failure_root.mkdir(); failure_events = []; failure_runner.events = failure_events

            def event_sink(event: str, *, fail_at=failing_event) -> None:
                failure_events.append(event)
                if event == fail_at: raise RuntimeError(f"synthetic late failure at {event}")

            expected_exception = RuntimeError if failing_event else ValueError
            with self.subTest(failure=label), self.assertRaises(expected_exception):
                run_stage0_package(
                    build_root=build_root, expected_source_commit=SOURCE_COMMIT, event_sink=event_sink,
                    generated_sdk_root=generated_root, lock_root=lock_root, reference_root=REFERENCE_ROOT, run_root=failure_root,
                    runner=failure_runner, sdk_root=SDK_ROOT,
                )
            if label.startswith("corrupt-"):
                self.assertTrue(failure_runner.results); self.assertTrue(all(result.returncode == 0 for _, result in failure_runner.results))
            self.assertFalse((failure_root / "evidence/package-receipt.json").exists())
            self.assertEqual(list(failure_root.iterdir()), []); self.assertEqual(failure_events[-1], "workspace:cleaned")
            self.assertFalse(any(path.name in {"delivery", "evidence"} for path in failure_root.iterdir()))

    def test_manifest_and_receipt_derive_source_tag_app_and_deep_cross_bindings_without_caller_pass_flags(self):
        assemble = require_api(self, self.package, "assemble_package_evidence")
        fixture = stage0_package_fixture(); qix_name = f"E87-11.1.0.3-{SOURCE_COMMIT[:8].upper()}.qix"; qix_bytes = self.qix.wrap_qix(fixture["update.ufw"], "11.1.0.3")
        artifacts_root = self.base / "evidence-artifacts"; artifacts_root.mkdir()
        artifacts = {name: artifacts_root / name for name in (*fixture, qix_name)}
        for name, data in fixture.items(): artifacts[name].write_bytes(data)
        artifacts[qix_name].write_bytes(qix_bytes)
        build_root = self.base / "evidence-build"; build_receipt = self._build_receipt_fixture(build_root, fixture["app.bin"]); build_receipt_path = build_root / "build-receipt.json"
        staging = self.base / "evidence-staging"; inputs = self._write_exact_staging_fixture(staging, fixture["app.bin"])
        control = self.base / "evidence-control"; control.mkdir(); environment = self.package.package_environment(control, source_date_epoch=build_receipt["sourceDateEpoch"])
        commands = self._native_command_receipts(); command_summaries = self._native_command_summaries(commands); validations = self._real_package_proofs(fixture, qix_bytes)
        for command in commands:
            self.assertEqual(set(command), {"argv", "exitCode", "role", "stderrHex", "stderrSha256", "stderrSize", "stdoutHex", "stdoutSha256", "stdoutSize", "toolSha256", "toolVersion"})
            for stream in ("stdout", "stderr"):
                raw_hex = command[f"{stream}Hex"]
                self.assertIsInstance(raw_hex, str); self.assertRegex(raw_hex, r"^(?:[0-9A-F]{2})*$")
                raw = bytes.fromhex(raw_hex)
                self.assertEqual(command[f"{stream}Sha256"], hashlib.sha256(raw).hexdigest().upper())
                self.assertEqual(command[f"{stream}Size"], len(raw))
        source_receipts = self.base / "evidence-source-receipts"
        execution_path, validation_path = self._write_package_source_receipts(source_receipts, commands=commands, environment=environment, inputs=inputs, validations=validations)
        lock_root = self._copy_lock_root("evidence-locks")
        arguments = {
            "artifacts": artifacts,
            "build_receipt_path": build_receipt_path,
            "control_root": control,
            "execution_receipt_path": execution_path,
            "lock_root": lock_root,
            "validation_receipt_path": validation_path,
        }
        evidence = call_contract(self, "path-derived package evidence", assemble, **arguments)
        app_sha = hashlib.sha256(fixture["app.bin"]).hexdigest().upper()
        self.assertEqual(set(evidence), {"app", "buildReceiptSha256", "buildTag", "commands", "environment", "identities", "inputs", "locks", "outputs", "qix", "resetPolicy", "schema", "sourceCommit", "sourceDateEpoch", "target", "validations"})
        self.assertEqual(evidence["schema"], "e87-stage0-package-evidence-v1")
        self.assertNotIn("runtime", evidence)
        self.assertEqual((evidence["sourceCommit"], evidence["buildTag"]), (SOURCE_COMMIT, SOURCE_COMMIT[:8].upper()))
        self.assertEqual(evidence["app"], build_receipt["app"]); self.assertEqual(evidence["app"]["sha256"], app_sha)
        self.assertEqual(evidence["commands"], command_summaries); self.assertEqual(evidence["validations"], validations)
        self.assertEqual(evidence["target"], build_receipt["target"])
        self.assertEqual(evidence["resetPolicy"], validations["resetPolicy"])
        self.assertEqual(evidence["qix"], validations["qix"])
        self.assertEqual(evidence["environment"], {**environment, "HOME": "$RUN_ROOT/control/home", "TMPDIR": "$RUN_ROOT/control/tmp"})
        self.assertEqual((evidence["sourceDateEpoch"], build_receipt["sourceDateEpoch"], build_receipt["bootstrap"]["sourceCommitEpoch"]), (SOURCE_DATE_EPOCH,) * 3)
        self.assertEqual(evidence["environment"]["SOURCE_DATE_EPOCH"], str(evidence["sourceDateEpoch"]))
        self.assertEqual(evidence["buildReceiptSha256"], hashlib.sha256(build_receipt_path.read_bytes()).hexdigest().upper())
        lock_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest().upper() for path in sorted(lock_root.iterdir())}
        self.assertEqual(evidence["locks"], lock_hashes)
        identities = evidence["identities"]
        self.assertEqual(set(identities), {"archives", "boardProfileSha256", "bootstrapReceiptSha256", "locks", "overlayTreeSha256", "patchSha256", "referenceManifestSha256", "sdk", "sourceCommitObjectSha256", "sourceTree", "tools"})
        self.assertEqual(identities["locks"], lock_hashes)
        self.assertEqual(identities["bootstrapReceiptSha256"], build_receipt["bootstrapReceipt"]["sha256"])
        self.assertEqual(identities["sdk"], {"commit": build_receipt["bootstrap"]["sdkCommit"], "tree": build_receipt["bootstrap"]["sdkTree"]})
        self.assertEqual(identities["sourceTree"], build_receipt["bootstrap"]["sourceTree"])
        self.assertEqual(identities["sourceCommitObjectSha256"], build_receipt["bootstrap"]["sourceCommitObjectSha256"])
        self.assertEqual(identities["patchSha256"], build_receipt["bootstrap"]["patch"]["sha256"])
        self.assertEqual(identities["archives"], {"packaging": self.packaging_lock["archive"]["sha256"], "toolchain": self.toolchain_lock["archive"]["sha256"]})
        self.assertEqual(identities["referenceManifestSha256"], self.model_lock["referenceFiles"]["manifest.json"]["sha256"])
        self.assertEqual(identities["boardProfileSha256"], next(item["sha256"] for item in build_receipt["bootstrap"]["overlay"] if item["destination"].endswith("board_e87_1542_cfg.h")))
        self.assertEqual(identities["overlayTreeSha256"], hashlib.sha256(json.dumps(build_receipt["bootstrap"]["overlay"], ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("ascii")).hexdigest().upper())
        expected_tools = {name: self.toolchain_lock["tools"][name]["sha256"] for name in PRIMARY_BUILD_TOOLS}
        expected_tools.update({"git": build_receipt["bootstrap"]["gitTool"]["sha256"], "make": build_receipt["commands"][0]["toolSha256"], "isdDownload": commands[0]["toolSha256"], "ufwMaker": commands[1]["toolSha256"]})
        self.assertEqual(identities["tools"], expected_tools)
        output_records = {item["filename"]: item for item in evidence["outputs"]}
        self.assertEqual(set(output_records), set(artifacts))
        self.assertTrue(all(set(item) == {"filename", "sha256", "size"} for item in evidence["outputs"]))
        self.assertEqual(len(evidence["commands"]), 2); self.assertTrue(all(set(item) == {"argv", "exitCode", "role", "stderrSha256", "stderrSize", "stdoutSha256", "stdoutSize", "toolSha256", "toolVersion"} for item in evidence["commands"]))
        self.assertTrue(all("stdoutHex" not in item and "stderrHex" not in item for item in evidence["commands"]))
        self.assertEqual({item["filename"] for item in evidence["inputs"]}, STAGING_NAMES); self.assertTrue(all(item["size"] > 0 for item in evidence["inputs"]))
        for name, path in artifacts.items():
            self.assertEqual((output_records[name]["sha256"], output_records[name]["size"]), (hashlib.sha256(path.read_bytes()).hexdigest().upper(), len(path.read_bytes())))
        self.assertNotIn("passed", json.dumps(evidence, sort_keys=True))

        def rewrite_json(path: Path, value: dict[str, object]) -> None:
            path.write_bytes((json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii"))

        def reject_json_mutation(path: Path, label: str, mutate) -> None:
            original = path.read_bytes(); changed = json.loads(original); mutate(changed); rewrite_json(path, changed)
            try:
                with self.subTest(receipt_mutation=label), self.assertRaises(ValueError): assemble(**arguments)
            finally:
                path.write_bytes(original)

        for label, mutate in (
            ("empty-commands", lambda value: value.__setitem__("commands", [])),
            ("command-count", lambda value: value["commands"].append(deepcopy(value["commands"][1]))),
            ("command-order", lambda value: value["commands"].reverse()),
            ("input", lambda value: value["inputs"][0].__setitem__("sha256", "0" * 64)),
            ("environment-extra", lambda value: value["environment"].__setitem__("INHERITED", "forbidden")),
            ("environment-epoch", lambda value: value["environment"].__setitem__("SOURCE_DATE_EPOCH", str(SOURCE_DATE_EPOCH + 1))),
        ):
            reject_json_mutation(execution_path, label, mutate)
        for index in range(2):
            for label, field, replacement in (
                ("argv", "argv", ["/bin/false"]), ("exit", "exitCode", 1), ("role", "role", f"wrong-{index}"),
                ("tool-sha", "toolSha256", "0" * 64), ("tool-version", "toolVersion", "drift"),
                ("stdout-sha-zero", "stdoutSha256", "0" * 64), ("stdout-sha-nonzero", "stdoutSha256", "A" * 64),
                ("stderr-sha-zero", "stderrSha256", "0" * 64), ("stderr-sha-nonzero", "stderrSha256", "A" * 64),
            ):
                reject_json_mutation(execution_path, f"command-{index}-{label}", lambda value, i=index, f=field, r=replacement: value["commands"][i].__setitem__(f, r))
            for stream in ("stdout", "stderr"):
                for label, replacement in (("nonhex", "GG"), ("odd", "A"), ("lowercase", "aa"), ("type", []), ("mismatch", "41")):
                    reject_json_mutation(execution_path, f"command-{index}-{stream}-hex-{label}", lambda value, i=index, f=f"{stream}Hex", r=replacement: value["commands"][i].__setitem__(f, r))
                for label, replacement in (("mismatch", 1), ("type", "0"), ("bool", True), ("negative", -1)):
                    reject_json_mutation(execution_path, f"command-{index}-{stream}-size-{label}", lambda value, i=index, f=f"{stream}Size", r=replacement: value["commands"][i].__setitem__(f, r))
                for field in (f"{stream}Hex", f"{stream}Sha256", f"{stream}Size"):
                    reject_json_mutation(execution_path, f"command-{index}-missing-{field}", lambda value, i=index, f=field: value["commands"][i].pop(f))
            reject_json_mutation(execution_path, f"command-{index}-unknown", lambda value, i=index: value["commands"][i].__setitem__("trusted", True))
        for label, mutate in (
            ("empty-validations", lambda value: value.__setitem__("validations", {})),
            ("caller-booleans", lambda value: value.__setitem__("validations", {"jlfw": True, "qix": True, "ufw": True})),
            ("jlfw-app", lambda value: value["validations"]["jlfw"].__setitem__("appSha256", "0" * 64)),
            ("ufw-relation", lambda value: value["validations"]["ufw"].__setitem__("relation", "DIFFERENT")),
            ("qix-payload", lambda value: value["validations"]["qix"].__setitem__("payloadSha256", "0" * 64)),
            ("reset-policy", lambda value: value["validations"]["resetPolicy"]["semanticDiff"].__setitem__("after", "RESET = PB07_08_0;")),
        ):
            reject_json_mutation(validation_path, label, mutate)
        for label, mutate in (
            ("app", lambda value: value["app"].__setitem__("sha256", "0" * 64)),
            ("source-commit", lambda value: value.__setitem__("sourceCommit", "f" * 40)),
            ("source-epoch", lambda value: value.__setitem__("sourceDateEpoch", SOURCE_DATE_EPOCH + 1)),
            ("target", lambda value: value["target"].__setitem__("cpu", "r2")),
            ("bootstrap-sdk", lambda value: value["bootstrap"].__setitem__("sdkTree", "0" * 40)),
            ("bootstrap-output-tree", lambda value: value["bootstrap"].__setitem__("outputTreeSha256", "0" * 64)),
            ("bootstrap-validation", lambda value: value["bootstrapValidation"].__setitem__("commandsSha256", "0" * 64)),
            ("bootstrap-source-object", lambda value: value["bootstrap"].__setitem__("sourceCommitObjectSha256", "0" * 64)),
            ("bootstrap-source-epoch", lambda value: value["bootstrap"].__setitem__("sourceCommitEpoch", SOURCE_DATE_EPOCH + 1)),
            ("bootstrap-patch", lambda value: value["bootstrap"]["patch"].__setitem__("sha256", "0" * 64)),
            ("bootstrap-overlay", lambda value: value["bootstrap"]["overlay"][0].__setitem__("sha256", "0" * 64)),
            ("runtime-missing", lambda value: value.pop("runtime")),
            ("runtime-unknown", lambda value: value["runtime"].__setitem__("trusted", True)),
            ("runtime-type", lambda value: value["runtime"].__setitem__("tools", [])),
            ("runtime-lock", lambda value: value["runtime"].__setitem__("toolchainLockSha256", "0" * 64)),
            ("runtime-path", lambda value: value["runtime"].__setitem__("controlledPath", "/usr/bin:/bin")),
            ("runtime-python", lambda value: value["runtime"]["hostTools"]["python3"].__setitem__("sha256", "0" * 64)),
            ("runtime-wrapper", lambda value: value["runtime"]["tools"]["ltoWrapper"].__setitem__("sha256", "0" * 64)),
        ):
            reject_json_mutation(build_receipt_path, label, mutate)
        for name, path in artifacts.items():
            original = path.read_bytes(); path.write_bytes(original + b"drift")
            try:
                with self.subTest(output_mutation=name), self.assertRaises(ValueError): assemble(**arguments)
            finally:
                path.write_bytes(original)
        for missing in artifacts:
            missing_artifacts = {name: path for name, path in artifacts.items() if name != missing}
            with self.subTest(missing_artifact=missing), self.assertRaises(ValueError): assemble(**{**arguments, "artifacts": missing_artifacts})
        for filename in ("model1552-package.lock.json", "packaging.lock.json", "toolchain.lock.json"):
            lock_path = lock_root / filename; original_lock_bytes = lock_path.read_bytes(); lock_path.write_bytes(original_lock_bytes + b" ")
            try:
                with self.subTest(lock_byte_drift=filename), self.assertRaises(ValueError): assemble(**arguments)
            finally:
                lock_path.write_bytes(original_lock_bytes)
        lock_path = lock_root / "packaging.lock.json"; original_lock = lock_path.read_bytes(); changed_lock = json.loads(original_lock); changed_lock["qix"]["version"] = "11.1.0.4"; rewrite_json(lock_path, changed_lock)
        try:
            with self.assertRaises(ValueError): assemble(**arguments)
        finally:
            lock_path.write_bytes(original_lock)
        with self.assertRaises((TypeError, ValueError)):
            assemble(**arguments, source_commit=SOURCE_COMMIT, build_tag="DEADBEEF", commands=commands, validations=validations, passed=True)

    def test_metadata_write_reopens_outputs_and_rejects_pre_and_mid_write_drift(self):
        stable_snapshot = require_api(self, self.package, "stable_output_snapshot")
        delivery = self.base / "metadata"; delivery.mkdir(); tag = SOURCE_COMMIT[:8].upper(); qix = f"E87-11.1.0.3-{tag}.qix"
        for name, data in (("app.bin", b"app"), ("jl_isd.fw", b"fw"), ("update.ufw", b"ufw"), (qix, b"qix")): (delivery / name).write_bytes(data)
        snapshot = stable_snapshot(delivery, {"app.bin", "jl_isd.fw", "update.ufw", qix})
        manifest = {"buildTag": tag, "outputs": [{"delivered": True, "filename": name, "sha256": digest, "size": size} for name, (size, digest) in sorted(snapshot.items())]}
        (delivery / "app.bin").write_bytes(b"drift")
        with self.assertRaises(ValueError): call_contract(self, "pre-write metadata snapshot", self.package.write_delivery_metadata, delivery, manifest, expected_snapshot=snapshot)
        self.assertFalse((delivery / "manifest.json").exists()); self.assertFalse((delivery / "SHA256SUMS").exists())

        (delivery / "app.bin").write_bytes(b"app")
        hook_calls = []
        def mutate_between_staging_and_commit():
            hook_calls.append("called"); (delivery / "update.ufw").write_bytes(b"mid-write-drift")
        with self.assertRaises(ValueError):
            call_contract(self, "mid-write metadata snapshot", self.package.write_delivery_metadata, delivery, manifest, expected_snapshot=snapshot, before_commit=mutate_between_staging_and_commit)
        self.assertEqual(hook_calls, ["called"])
        self.assertFalse((delivery / "manifest.json").exists()); self.assertFalse((delivery / "SHA256SUMS").exists())
        self.assertFalse(any(path.name.startswith((".manifest.json.", ".SHA256SUMS.")) for path in delivery.iterdir()))

    def test_repro_requires_two_distinct_complete_run_roots_and_all_required_files(self):
        validate_complete = require_api(self, self.package, "validate_complete_run")
        compare = require_api(self, self.package, "assert_reproducible_runs")
        incomplete = self.base / "incomplete"; (incomplete / "delivery").mkdir(parents=True); (incomplete / "delivery/app.bin").write_bytes(b"nonempty-but-incomplete")
        with self.assertRaises(ValueError): validate_complete(incomplete)
        incomplete_evidence = self.base / "incomplete-evidence"; (incomplete_evidence / "delivery").mkdir(parents=True); (incomplete_evidence / "evidence").mkdir(); (incomplete_evidence / "evidence/build-receipt.json").write_bytes(b"{}\n")
        with self.assertRaises(ValueError): validate_complete(incomplete_evidence)
        first = self.base / "complete-1"; second = self.base / "complete-2"
        _, first_evidence, _, _, _, first_build = self._delivery_fixture(first)
        _, second_evidence, _, _, _, second_build = self._delivery_fixture(second)
        self.assertNotEqual(first.resolve(), second.resolve()); self.assertNotEqual(first_build.resolve(), second_build.resolve())
        self.assertEqual(set(path.name for path in first.iterdir()), {"delivery", "evidence"})
        self.assertEqual(set(path.name for path in second.iterdir()), {"delivery", "evidence"})
        first_proof = validate_complete(first); second_proof = validate_complete(second)
        self.assertEqual(set(first_proof), {"buildReceiptSha256", "delivery", "evidence", "packageReceiptSha256"})
        self.assertEqual(first_proof["delivery"], second_proof["delivery"])
        self.assertNotEqual(first_proof["buildReceiptSha256"], second_proof["buildReceiptSha256"])
        for evidence_root, proof in ((first_evidence, first_proof), (second_evidence, second_proof)):
            build_receipt_bytes = (evidence_root / "build-receipt.json").read_bytes()
            package_receipt = json.loads((evidence_root / "package-receipt.json").read_bytes())
            self.assertEqual(proof["buildReceiptSha256"], hashlib.sha256(build_receipt_bytes).hexdigest().upper())
            self.assertEqual(package_receipt["buildReceiptSha256"], proof["buildReceiptSha256"])
        with self.assertRaises(ValueError): compare(first, first)
        alias = self.base / "complete-alias"; alias.symlink_to(first, target_is_directory=True)
        with self.assertRaises(ValueError): compare(first, alias)
        first_build_receipt = json.loads((first_evidence / "build-receipt.json").read_bytes()); second_build_receipt = json.loads((second_evidence / "build-receipt.json").read_bytes())
        self.assertNotEqual(first_build_receipt["commands"], second_build_receipt["commands"])
        self.assertIn(str(first_build), json.dumps(first_build_receipt["commands"])); self.assertIn(str(second_build), json.dumps(second_build_receipt["commands"]))
        self.assertNotEqual((first_evidence / "native-execution.json").read_bytes(), (second_evidence / "native-execution.json").read_bytes())
        root_substitutions = [
            {"first": str(first_build.resolve()), "second": str(second_build.resolve()), "token": "$BUILD_ROOT"},
            {"first": str((first_build.parent / f"{first_build.name}-generated").resolve()), "second": str((second_build.parent / f"{second_build.name}-generated").resolve()), "token": "$GENERATED_SDK_ROOT"},
            {"first": str(first.resolve()), "second": str(second.resolve()), "token": "$RUN_ROOT"},
        ]
        self.assertEqual(compare(first, second), {"relation": "BYTE_IDENTICAL", "rootSubstitutions": root_substitutions})

        evidence_files = ("build-receipt.json", "native-execution.json", "validation.json", "package-evidence.json", "package-receipt.json", "jl_isd.bin", "independently-made.ufw")

        def reject_complete_file(path: Path, label: str, replacement: bytes | None) -> None:
            original = path.read_bytes()
            if replacement is None: path.unlink()
            else: path.write_bytes(replacement)
            try:
                with self.subTest(evidence_file=path.name, mutation=label), self.assertRaises(ValueError): validate_complete(second)
                with self.subTest(repro_file=path.name, mutation=label), self.assertRaises(ValueError): compare(first, second)
            finally:
                path.write_bytes(original)

        for filename in evidence_files:
            path = second_evidence / filename; original = path.read_bytes()
            reject_complete_file(path, "missing", None); reject_complete_file(path, "empty", b"")
            if filename.endswith(".json"):
                value = json.loads(original)
                reject_complete_file(path, "noncanonical", json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("ascii"))
                changed = deepcopy(value); changed["schema"] = str(changed.get("schema", "missing")) + "-wrong"
                reject_complete_file(path, "schema", (json.dumps(changed, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii"))
                changed = deepcopy(value)
                if filename == "build-receipt.json": changed["app"]["sha256"] = "0" * 64
                elif filename == "native-execution.json": changed["commands"][0]["stdoutSha256"] = "0" * 64
                elif filename == "validation.json": changed["validations"]["qix"]["payloadSha256"] = "0" * 64
                else: changed["buildReceiptSha256"] = "0" * 64
                reject_complete_file(path, "cross-hash", (json.dumps(changed, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii"))
            else:
                changed = bytearray(original); changed[len(changed) // 2] ^= 1; reject_complete_file(path, "cross-hash", bytes(changed))
        build_receipt_path = second_evidence / "build-receipt.json"; original = build_receipt_path.read_bytes(); changed = json.loads(original)
        verbose_index = changed["commands"][0]["argv"].index("VERBOSE=0"); changed["commands"][0]["argv"][verbose_index] = "VERBOSE=1"
        reject_complete_file(build_receipt_path, "non-root-argv-token", (json.dumps(changed, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii"))
        for label, mutate in (
            ("runtime-missing", lambda value: value.pop("runtime")),
            ("runtime-unknown", lambda value: value["runtime"].__setitem__("unknown", True)),
            ("runtime-type", lambda value: value["runtime"].__setitem__("elfInterpreter", [])),
            ("runtime-lock", lambda value: value["runtime"].__setitem__("toolchainLockSha256", "0" * 64)),
            ("runtime-path", lambda value: value["runtime"].__setitem__("controlledPath", "/usr/bin:/bin")),
            ("runtime-tool", lambda value: value["runtime"]["tools"]["llvmGold"].__setitem__("sha256", "0" * 64)),
        ):
            changed = json.loads(original); mutate(changed)
            reject_complete_file(build_receipt_path, label, (json.dumps(changed, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii"))
        native_path = second_evidence / "native-execution.json"; original_native = native_path.read_bytes(); changed_native = json.loads(original_native)
        wait_index = changed_native["commands"][0]["argv"].index("300"); changed_native["commands"][0]["argv"][wait_index] = "301"
        reject_complete_file(native_path, "semantic-command-drift", (json.dumps(changed_native, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii"))
        self.assertEqual(compare(first, second), {"relation": "BYTE_IDENTICAL", "rootSubstitutions": root_substitutions})

        semantic = self.base / "complete-semantic-drift"
        _, semantic_evidence, _, _, _, semantic_build = self._delivery_fixture(
            semantic,
            native_stdout_by_role={"isdDownload": b"deterministic-but-different-command-output\n"},
        )
        semantic_proof = validate_complete(semantic)
        self.assertEqual(semantic_proof["buildReceiptSha256"], hashlib.sha256((semantic_evidence / "build-receipt.json").read_bytes()).hexdigest().upper())
        baseline_execution = json.loads((first_evidence / "native-execution.json").read_bytes()); semantic_execution = json.loads((semantic_evidence / "native-execution.json").read_bytes())
        semantic_stdout = bytes.fromhex(semantic_execution["commands"][0]["stdoutHex"])
        self.assertEqual(semantic_stdout, b"deterministic-but-different-command-output\n")
        self.assertEqual(semantic_execution["commands"][0]["stdoutSha256"], hashlib.sha256(semantic_stdout).hexdigest().upper())
        self.assertEqual(semantic_execution["commands"][0]["stdoutSize"], len(semantic_stdout))
        self.assertNotEqual(baseline_execution["commands"][0]["stdoutSha256"], semantic_execution["commands"][0]["stdoutSha256"])
        normalized_semantic_execution = deepcopy(semantic_execution)
        for field in ("stdoutHex", "stdoutSha256", "stdoutSize"):
            normalized_semantic_execution["commands"][0][field] = baseline_execution["commands"][0][field]
        normalized_semantic_execution["environment"] = baseline_execution["environment"]
        self.assertEqual(normalized_semantic_execution, baseline_execution)
        semantic_summary = self._native_command_summaries(semantic_execution["commands"])[0]
        semantic_package_evidence = json.loads((semantic_evidence / "package-evidence.json").read_bytes())
        semantic_manifest = json.loads((semantic / "delivery/manifest.json").read_bytes())
        self.assertEqual(semantic_package_evidence["commands"][0], semantic_summary)
        self.assertEqual(semantic_manifest["nativeCommands"][0], semantic_summary)
        self.assertNotIn("stdoutHex", semantic_summary); self.assertNotIn("stderrHex", semantic_summary)
        self.assertNotEqual((semantic_evidence / "package-evidence.json").read_bytes(), (first_evidence / "package-evidence.json").read_bytes())
        self.assertNotEqual((semantic / "delivery/manifest.json").read_bytes(), (first / "delivery/manifest.json").read_bytes())
        with self.assertRaisesRegex(ValueError, "(?i)(semantic|command|reproducibility|mismatch)"):
            compare(first, semantic)
        self.assertNotEqual(first_build.resolve(), semantic_build.resolve())

    def _delivery_fixture(self, run_root: Path, *, native_stdout_by_role: dict[str, bytes] | None = None):
        run_root.mkdir(); delivery = run_root / "delivery"; evidence_root = run_root / "evidence"; staging = run_root / "staging"; control = run_root / "control"
        delivery.mkdir(); evidence_root.mkdir(); control.mkdir()
        fixture = stage0_package_fixture(); tag = SOURCE_COMMIT[:8].upper(); qix_name = f"E87-11.1.0.3-{tag}.qix"; qix_bytes = self.qix.wrap_qix(fixture["update.ufw"], "11.1.0.3")
        for name in ("app.bin", "jl_isd.fw", "update.ufw"): (delivery / name).write_bytes(fixture[name])
        (delivery / qix_name).write_bytes(qix_bytes)
        for name in ("jl_isd.bin", "independently-made.ufw"): (evidence_root / name).write_bytes(fixture[name])
        inputs = self._write_exact_staging_fixture(staging, fixture["app.bin"])
        build_root = run_root.parent / f"{run_root.name}-build"; build_receipt = self._build_receipt_fixture(build_root, fixture["app.bin"])
        build_receipt_path = evidence_root / "build-receipt.json"; shutil.copy2(build_root / "build-receipt.json", build_receipt_path)
        environment = self.package.package_environment(control, source_date_epoch=build_receipt["sourceDateEpoch"])
        commands = self._native_command_receipts(stdout_by_role=native_stdout_by_role); validations = self._real_package_proofs(fixture, qix_bytes)
        execution_path, validation_path = self._write_package_source_receipts(evidence_root, commands=commands, environment=environment, inputs=inputs, validations=validations)
        lock_root = self._copy_lock_root(f"{run_root.name}-locks")
        artifacts = {name: delivery / name for name in ("app.bin", "jl_isd.fw", "update.ufw", qix_name)} | {name: evidence_root / name for name in ("jl_isd.bin", "independently-made.ufw")}
        package_evidence = call_contract(
            self, "real package evidence", require_api(self, self.package, "assemble_package_evidence"),
            artifacts=artifacts, build_receipt_path=build_receipt_path, control_root=control, execution_receipt_path=execution_path,
            lock_root=lock_root, validation_receipt_path=validation_path,
        )
        package_evidence_path = evidence_root / "package-evidence.json"
        package_evidence_path.write_bytes((json.dumps(package_evidence, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii"))
        manifest = call_contract(
            self, "path-derived manifest", self.package.build_manifest, delivery, evidence_root,
            build_receipt_path=build_receipt_path, execution_receipt_path=execution_path, lock_root=lock_root, package_evidence_path=package_evidence_path,
            validation_receipt_path=validation_path,
        )
        snapshot = require_api(self, self.package, "stable_output_snapshot")(delivery, {"app.bin", "jl_isd.fw", "update.ufw", qix_name})
        call_contract(self, "atomic delivery metadata", self.package.write_delivery_metadata, delivery, manifest, expected_snapshot=snapshot)
        package_receipt = call_contract(
            self, "path-derived package receipt", self.package.build_package_receipt,
            build_receipt_path=build_receipt_path, execution_receipt_path=execution_path, lock_root=lock_root,
            package_evidence_path=package_evidence_path, validation_receipt_path=validation_path,
            delivery_root=delivery, evidence_root=evidence_root,
        )
        (evidence_root / "package-receipt.json").write_bytes((json.dumps(package_receipt, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii"))
        shutil.rmtree(staging); shutil.rmtree(control)
        return delivery, evidence_root, qix_name, manifest, package_evidence, build_root

    def test_manifest_delivery_allowlist_sha_sums_and_exact_lab_policy(self):
        run_root = self.base / "manifest-run"; delivery, evidence, qix_name, manifest, package_evidence, _ = self._delivery_fixture(run_root)
        self.assertEqual(set(manifest), {"buildTag", "features", "identities", "labEligible", "nativeCommands", "outputs", "qix", "recovery", "releaseEligible", "resetPolicy", "schema", "sourceCommit", "target", "writeOnlyWaiver"})
        self.assertEqual(manifest["schema"], "e87-stage0-manifest-v1")
        self.assertNotIn("runtime", manifest)
        self.assertEqual((manifest["sourceCommit"], manifest["buildTag"]), (SOURCE_COMMIT, SOURCE_COMMIT[:8].upper()))
        self.assertEqual(manifest["features"], {"bleHeartbeat": True, "buttons": False, "charging": False, "display": False, "gatt": False, "maintenance": False, "sleep": False})
        self.assertEqual(manifest["recovery"], {"evidence": None, "kind": "BR35_MASKROM_EXTERNAL", "requiresPreWriteProof": True})
        self.assertEqual(manifest["writeOnlyWaiver"], "SKIPPED_WITH_REASON: WRITE_ONLY_CONFIRMED")
        self.assertIs(manifest["releaseEligible"], False); self.assertIs(manifest["labEligible"], False)
        outputs = {item["filename"]: item for item in manifest["outputs"]}
        self.assertTrue(all(set(item) == {"delivered", "filename", "role", "sha256", "size", "validation"} for item in manifest["outputs"]))
        self.assertTrue(all(re.fullmatch(r"[0-9A-F]{64}", item["sha256"]) for item in manifest["outputs"]))
        self.assertIs(outputs["jl_isd.bin"]["delivered"], False); self.assertIs(outputs["independently-made.ufw"]["delivered"], False)
        app_sha = hashlib.sha256((delivery / "app.bin").read_bytes()).hexdigest().upper()
        self.assertEqual(outputs["app.bin"]["sha256"], app_sha)
        self.assertEqual(outputs["jl_isd.bin"]["validation"]["embeddedAppSha256"], app_sha)
        self.assertEqual(outputs["jl_isd.fw"]["validation"]["embeddedAppSha256"], app_sha)
        self.assertEqual(outputs["update.ufw"]["sha256"], manifest["qix"]["payloadSha256"])
        self.assertEqual(outputs[qix_name]["validation"]["unwrappedPayloadSha256"], outputs["update.ufw"]["sha256"])
        self.assertNotIn("passed", json.dumps(manifest, sort_keys=True))
        self.assertEqual(set(manifest["identities"]), {"archives", "boardProfileSha256", "bootstrapReceiptSha256", "locks", "overlayTreeSha256", "patchSha256", "referenceManifestSha256", "sdk", "sourceCommitObjectSha256", "sourceTree", "tools"})
        self.assertEqual(set(manifest["target"]), {"architecture", "codeEnd", "cpu", "entryAddress", "mapSha256", "uiresStart"})
        self.assertEqual(set(manifest["resetPolicy"]), {"recoveredSha256", "semanticDiff", "stagedSha256"})
        self.assertEqual(set(manifest["qix"]), {"payloadFilename", "payloadSha256", "qixSha256", "qixSize", "relation", "unwrappedPayloadSha256", "version"})
        expected_native_summaries = self._native_command_summaries(self._native_command_receipts())
        self.assertEqual(manifest["nativeCommands"], expected_native_summaries)
        self.assertTrue(all(set(item) == {"argv", "exitCode", "role", "stderrSha256", "stderrSize", "stdoutSha256", "stdoutSize", "toolSha256", "toolVersion"} for item in manifest["nativeCommands"]))
        self.assertTrue(all("stdoutHex" not in item and "stderrHex" not in item for item in manifest["nativeCommands"]))
        self.assertEqual(set(path.name for path in delivery.iterdir()), {"app.bin", "jl_isd.fw", "update.ufw", qix_name, "manifest.json", "SHA256SUMS"})
        sums = (delivery / "SHA256SUMS").read_text(encoding="ascii").splitlines()
        self.assertEqual(len(sums), 5); self.assertTrue(any(line.endswith("  manifest.json") for line in sums)); self.assertFalse(any(line.endswith("  SHA256SUMS") for line in sums))
        self.assertTrue(all(re.fullmatch(r"[0-9A-F]{64}  [A-Za-z0-9._-]+", line) for line in sums))
        self.assertEqual([line.split("  ", 1)[1] for line in sums], sorted(line.split("  ", 1)[1] for line in sums))
        for line in sums:
            digest, filename = line.split("  ", 1)
            self.assertEqual(digest, hashlib.sha256((delivery / filename).read_bytes()).hexdigest().upper())
        self.assertEqual((delivery / "manifest.json").read_text(encoding="ascii"), json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n")
        receipt = json.loads((evidence / "package-receipt.json").read_bytes())
        self.assertEqual(set(receipt), {"app", "buildReceiptSha256", "buildTag", "commands", "environment", "identities", "inputs", "locks", "outputs", "qix", "resetPolicy", "schema", "sourceCommit", "sourceDateEpoch", "target", "validations"})
        self.assertEqual(receipt["schema"], "e87-stage0-package-receipt-v1")
        self.assertNotIn("runtime", receipt)
        self.assertEqual(set(receipt["environment"]), {"HOME", "TMPDIR", "LANG", "LC_ALL", "TZ", "SOURCE_DATE_EPOCH", "PATH"})
        self.assertEqual(receipt["commands"], expected_native_summaries)
        self.assertEqual(set(receipt["validations"]), {"jlfw", "qix", "resetPolicy", "ufw"}); self.assertNotIn("passed", json.dumps(receipt, sort_keys=True))
        package_evidence_path = evidence / "package-evidence.json"; original_evidence = package_evidence_path.read_bytes(); invalid = json.loads(original_evidence); invalid["validations"] = {"jlfw": True, "qix": True, "ufw": True}
        package_evidence_path.write_bytes((json.dumps(invalid, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii"))
        try:
            with self.assertRaises(ValueError): self.package.build_package_receipt(build_receipt_path=evidence / "build-receipt.json", delivery_root=delivery, evidence_root=evidence, execution_receipt_path=evidence / "native-execution.json", lock_root=self.base / "manifest-run-locks", package_evidence_path=package_evidence_path, validation_receipt_path=evidence / "validation.json")
        finally:
            package_evidence_path.write_bytes(original_evidence)

        manifest_arguments = {
            "build_receipt_path": evidence / "build-receipt.json",
            "execution_receipt_path": evidence / "native-execution.json",
            "lock_root": self.base / "manifest-run-locks",
            "package_evidence_path": package_evidence_path,
            "validation_receipt_path": evidence / "validation.json",
        }
        receipt_arguments = {**manifest_arguments, "delivery_root": delivery, "evidence_root": evidence}

        def reject_downstream_json_mutation(path: Path, label: str, mutate) -> None:
            original = path.read_bytes(); changed = json.loads(original); mutate(changed)
            path.write_bytes((json.dumps(changed, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii"))
            try:
                with self.subTest(downstream_mutation=label), self.assertRaises(ValueError):
                    self.package.build_manifest(delivery, evidence, **manifest_arguments)
                with self.subTest(receipt_mutation=label), self.assertRaises(ValueError):
                    self.package.build_package_receipt(**receipt_arguments)
            finally:
                path.write_bytes(original)

        for label, mutate in (
            ("identities", lambda value: value["identities"]["tools"].__setitem__("isdDownload", "0" * 64)),
            ("source-object", lambda value: value["identities"].__setitem__("sourceCommitObjectSha256", "0" * 64)),
            ("source-commit", lambda value: value.__setitem__("sourceCommit", "f" * 40)),
            ("build-tag", lambda value: value.__setitem__("buildTag", "DEADBEEF")),
            ("source-epoch", lambda value: value.__setitem__("sourceDateEpoch", SOURCE_DATE_EPOCH + 1)),
            ("environment-epoch", lambda value: value["environment"].__setitem__("SOURCE_DATE_EPOCH", str(SOURCE_DATE_EPOCH + 1))),
            ("target", lambda value: value["target"].__setitem__("cpu", "r2")),
            ("reset", lambda value: value["resetPolicy"]["semanticDiff"].__setitem__("after", "RESET = PB07_08_0;")),
            ("qix", lambda value: value["qix"].__setitem__("version", "11.1.0.2")),
            ("outputs", lambda value: value["outputs"][0].__setitem__("sha256", "0" * 64)),
            ("command-count", lambda value: value["commands"].pop()),
        ):
            reject_downstream_json_mutation(package_evidence_path, label, mutate)
        for index in range(2):
            for label, field, replacement in (
                ("argv", "argv", ["/bin/false"]), ("exit", "exitCode", 1), ("role", "role", f"wrong-{index}"),
                ("tool-sha", "toolSha256", "0" * 64), ("tool-version", "toolVersion", "drift"),
                ("stdout-sha-zero", "stdoutSha256", "0" * 64), ("stdout-sha-nonzero", "stdoutSha256", "A" * 64),
                ("stderr-sha-zero", "stderrSha256", "0" * 64), ("stderr-sha-nonzero", "stderrSha256", "A" * 64),
                ("stdout-size", "stdoutSize", 1), ("stderr-size", "stderrSize", 1),
            ):
                reject_downstream_json_mutation(package_evidence_path, f"command-{index}-{label}", lambda value, i=index, f=field, r=replacement: value["commands"][i].__setitem__(f, r))
            reject_downstream_json_mutation(package_evidence_path, f"command-{index}-raw-stdout", lambda value, i=index: value["commands"][i].__setitem__("stdoutHex", ""))
            reject_downstream_json_mutation(package_evidence_path, f"command-{index}-missing-size", lambda value, i=index: value["commands"][i].pop("stdoutSize"))
        reject_downstream_json_mutation(evidence / "build-receipt.json", "build-target", lambda value: value["target"].__setitem__("entryAddress", "0x0C000104"))
        reject_downstream_json_mutation(evidence / "build-receipt.json", "build-source-epoch", lambda value: value.__setitem__("sourceDateEpoch", SOURCE_DATE_EPOCH + 1))
        reject_downstream_json_mutation(evidence / "build-receipt.json", "bootstrap-source-epoch", lambda value: value["bootstrap"].__setitem__("sourceCommitEpoch", SOURCE_DATE_EPOCH + 1))
        reject_downstream_json_mutation(evidence / "build-receipt.json", "bootstrap-source-object", lambda value: value["bootstrap"].__setitem__("sourceCommitObjectSha256", "0" * 64))
        reject_downstream_json_mutation(evidence / "build-receipt.json", "bootstrap-output-tree", lambda value: value["bootstrap"].__setitem__("outputTreeSha256", "0" * 64))
        reject_downstream_json_mutation(evidence / "build-receipt.json", "bootstrap-validation", lambda value: value["bootstrapValidation"].__setitem__("commandsSha256", "0" * 64))
        reject_downstream_json_mutation(evidence / "build-receipt.json", "runtime-missing", lambda value: value.pop("runtime"))
        reject_downstream_json_mutation(evidence / "build-receipt.json", "runtime-unknown", lambda value: value["runtime"].__setitem__("trusted", True))
        reject_downstream_json_mutation(evidence / "build-receipt.json", "runtime-type", lambda value: value["runtime"].__setitem__("hostTools", []))
        reject_downstream_json_mutation(evidence / "build-receipt.json", "runtime-lock", lambda value: value["runtime"].__setitem__("toolchainLockSha256", "0" * 64))
        reject_downstream_json_mutation(evidence / "build-receipt.json", "runtime-interpreter", lambda value: value["runtime"]["elfInterpreter"].__setitem__("sha256", "0" * 64))
        reject_downstream_json_mutation(evidence / "build-receipt.json", "runtime-env", lambda value: value["runtime"]["hostTools"]["env"].__setitem__("sha256", "0" * 64))
        reject_downstream_json_mutation(evidence / "build-receipt.json", "runtime-ar", lambda value: value["runtime"]["tools"]["ar"].__setitem__("sha256", "0" * 64))
        reject_downstream_json_mutation(evidence / "validation.json", "validation-qix", lambda value: value["validations"]["qix"].__setitem__("payloadSha256", "0" * 64))
        reject_downstream_json_mutation(evidence / "native-execution.json", "execution-command", lambda value: value["commands"][1].__setitem__("toolVersion", "drift"))
        reject_downstream_json_mutation(evidence / "native-execution.json", "execution-epoch", lambda value: value["environment"].__setitem__("SOURCE_DATE_EPOCH", str(SOURCE_DATE_EPOCH + 1)))
        reject_downstream_json_mutation(self.base / "manifest-run-locks/packaging.lock.json", "lock-version", lambda value: value["qix"].__setitem__("version", "11.1.0.4"))
        for filename in ("model1552-package.lock.json", "packaging.lock.json", "toolchain.lock.json"):
            path = self.base / "manifest-run-locks" / filename; original = path.read_bytes(); path.write_bytes(original + b" ")
            try:
                with self.subTest(lock_byte_drift=filename), self.assertRaises(ValueError): self.package.build_manifest(delivery, evidence, **manifest_arguments)
                with self.subTest(receipt_lock_byte_drift=filename), self.assertRaises(ValueError): self.package.build_package_receipt(**receipt_arguments)
            finally:
                path.write_bytes(original)
        output = evidence / "jl_isd.bin"; original_output = output.read_bytes(); output.write_bytes(original_output + b"drift")
        try:
            with self.assertRaises(ValueError): self.package.build_manifest(delivery, evidence, **manifest_arguments)
            with self.assertRaises(ValueError): self.package.build_package_receipt(**receipt_arguments)
        finally:
            output.write_bytes(original_output)
        self.package.validate_delivery_allowlist(delivery, qix_name)
        (delivery / "unexpected.bin").write_bytes(b"x")
        with self.assertRaises(ValueError): self.package.validate_delivery_allowlist(delivery, qix_name)

    def test_two_independent_delivery_roots_compare_and_one_byte_drift_fails(self):
        empty_one = self.base / "repro-empty-1"; empty_two = self.base / "repro-empty-2"; empty_one.mkdir(); empty_two.mkdir()
        with self.assertRaises(ValueError): self.package.assert_deterministic_package(empty_one, empty_one, empty_one, empty_one)
        with self.assertRaises(ValueError): self.package.assert_deterministic_package(empty_one, empty_one, empty_two, empty_two)
        first = self.base / "run-1"; second = self.base / "run-2"
        first_delivery, first_evidence, _, _, _, _ = self._delivery_fixture(first); second_delivery, second_evidence, _, _, _, _ = self._delivery_fixture(second)
        with self.assertRaises(ValueError): self.package.assert_deterministic_package(first_delivery, first_evidence, first_delivery, first_evidence)
        self.package.assert_deterministic_package(first_delivery, first_evidence, second_delivery, second_evidence)
        self.assertEqual((first_evidence / "jl_isd.bin").read_bytes(), (second_evidence / "jl_isd.bin").read_bytes())
        intermediate = second_evidence / "jl_isd.bin"; intermediate.write_bytes(b"drift")
        with self.assertRaises(ValueError): self.package.assert_deterministic_package(first_delivery, first_evidence, second_delivery, second_evidence)
        intermediate.write_bytes((first_evidence / "jl_isd.bin").read_bytes())
        target = second_delivery / "app.bin"; changed = bytearray(target.read_bytes()); changed[0] ^= 1; target.write_bytes(changed)
        with self.assertRaises(ValueError): self.package.assert_deterministic_package(first_delivery, first_evidence, second_delivery, second_evidence)


if __name__ == "__main__":
    unittest.main()
