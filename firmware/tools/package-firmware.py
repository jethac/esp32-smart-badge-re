#!/usr/bin/env python3
"""Fail-closed offline package helpers for E87 Stage 0-H."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path


POST_PATH = "/home/jethac/.local/share/e87-dev/jieli-post-build:/usr/bin:/bin"
DEFAULT_POST_ROOT = Path("/home/jethac/.local/share/e87-dev/jieli-post-build")
ENV_KEYS = {"HOME", "TMPDIR", "LANG", "LC_ALL", "TZ", "SOURCE_DATE_EPOCH", "PATH"}
BUILD_PATH = "/home/jethac/.local/share/e87-dev/jieli/pi32v2/bin:/home/jethac/.local/share/e87-dev/jieli-post-build:/usr/bin:/bin"
BUILD_VALIDATIONS = {
    name: True
    for name in (
        "appConcatenation", "bootstrapReplay", "buildEnvironment", "buildInputsStable",
        "elfLayout", "mapProvenance", "nofileLimit", "objectInventory", "outputAllowlist",
        "runtimeIdentity", "sectionExtraction", "sourceSelection", "toolIdentity",
    )
}
BUILD_RESOURCE_LIMITS = {"nofileSoft": 8192}
ISD_ARGUMENTS = ["-tonorflash", "-dev", "br35", "-boot", "0x102600", "-div8", "-wait", "300", "-uboot", "uboot.boot", "-app", "app.bin", "-res", "cfg_tool.bin", "p11_code.bin", "stream.bin", "config.dat", "-flash-params", "flash_params_v3.bin", "-output-fw", "jl_isd.fw", "-output-ufw", "update.ufw"]
UFW_ARGUMENTS = ["--fw", "jl_isd.fw", "--output", "independently-made.ufw"]
STAGING_SOURCES = {
    "uboot.boot": "canonical-jl-unpack/top/uboot.boot",
    "cfg_tool.bin": "canonical-jl-unpack/files/cfg_tool.bin",
    "config.dat": "canonical-jl-unpack/files/config.dat",
    "p11_code.bin": "canonical-jl-unpack/files/p11_code.bin",
    "stream.bin": "canonical-jl-unpack/files/stream.bin",
    "flash_params_v3.bin": "items/03_params_flash.bin",
    "isd_config.ini": "items/04_isd_config.ini",
    "ota.bin": "items/06_ota.bin",
}
FORBIDDEN_INI = "canonical-jl-unpack/top/isd_config.ini"
PROMPT_PATTERN = re.compile(rb"(?:connect|select|insert|press|device|usb|serial|com\d+|tty)", re.IGNORECASE)
STAGING_NAMES = {
    "app.bin", "uboot.boot", "cfg_tool.bin", "config.dat", "p11_code.bin",
    "stream.bin", "flash_params_v3.bin", "isd_config.ini", "ota.bin",
    "br35loader.bin",
}
LOCK_FILENAMES = (
    "model1552-package.lock.json",
    "packaging.lock.json",
    "toolchain.lock.json",
)
LOCK_SHA256 = {
    "model1552-package.lock.json": "EFD3878979F029C56DA16E863EB89955E22D9B222046211A84AAC7BE1F3BA122",
    "packaging.lock.json": "28E6C1DEF70F894F89FDC7FFB8527F204688888C58EEDC052CD8A36F3AEBC003",
    "toolchain.lock.json": "60D72D942FC66E89303FD059AC9904F9167AAB743A21E78AB7230AA6B5B2300D",
}
QIX_VERSION = "11.1.0.3"
HEX64 = re.compile(r"[0-9A-F]{64}\Z")
SOURCE40 = re.compile(r"[0-9a-f]{40}\Z")
BUILD_RECEIPT_KEYS = {
    "app", "bootstrap", "bootstrapReceipt", "bootstrapValidation",
    "buildProvenance", "commands", "elf", "environment", "inputs", "mapProvenance",
    "resourceLimits", "runtime", "schema", "sectionOutputs", "sections", "sourceCommit",
    "sourceDateEpoch", "sourceObjects", "symbols", "target", "validations", "versionProbes",
}
BUILD_COMMAND_KEYS = {
    "argv", "cwd", "environment", "exitCode", "role", "stderrHex", "stderrSha256",
    "stderrSize", "stdoutHex", "stdoutSha256", "stdoutSize", "toolSha256", "toolVersion",
}
BUILD_VERSION_PROBE_KEYS = {
    "argv", "cwd", "environment", "exitCode", "stderrHex", "stderrSha256",
    "stderrSize", "stdoutHex", "stdoutSha256", "stdoutSize", "tool", "toolSha256", "version",
}
SECTION_OUTPUTS = (
    (".text", "text.bin"),
    (".data", "data.bin"),
    (".data_code", "data_code.bin"),
    (".overlay_aec", "aec.bin"),
    (".overlay_aac", "aac.bin"),
    (".ps_ram_data_code", "psr_data_code.bin"),
    (".dcache_ram_data", "d_ram_data.bin"),
    (".icache_ram_data_code", "i_ram_data_code.bin"),
)
SOURCE_OBJECTS = (
    "objs/apps/watch/e87/e87_stage0_adv.c.o",
    "objs/apps/watch/e87/e87_stage0_app.c.o",
    "objs/apps/watch/e87/e87_stage0_ble.c.o",
    "objs/apps/watch/board/br35/board_e87_1542/board_e87_1542.c.o",
)
PRIMARY_BUILD_TOOLS = ("clang", "ld", "nm", "objcopy", "objdump", "objsizedump", "strip")
PACKAGE_EVIDENCE_KEYS = {
    "app", "buildReceiptSha256", "buildTag", "commands", "environment",
    "identities", "inputs", "locks", "outputs", "qix", "resetPolicy",
    "schema", "sourceCommit", "sourceDateEpoch", "target", "validations",
}
NATIVE_COMMAND_KEYS = {
    "argv", "exitCode", "role", "stderrHex", "stderrSha256", "stderrSize",
    "stdoutHex", "stdoutSha256", "stdoutSize", "toolSha256", "toolVersion",
}
NATIVE_COMMAND_SUMMARY_KEYS = (
    "argv", "exitCode", "role", "stderrSha256", "stderrSize",
    "stdoutSha256", "stdoutSize", "toolSha256", "toolVersion",
)
QIX_PROOF_KEYS = {
    "payloadFilename", "payloadSha256", "qixSha256", "qixSize", "relation",
    "unwrappedPayloadSha256", "version",
}


def _sha(data: bytes) -> str: return hashlib.sha256(data).hexdigest().upper()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii")


def _write_new(path: Path, data: bytes) -> None:
    if path.exists() or path.is_symlink(): raise ValueError(f"output already exists: {path.name}")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as stream: stream.write(data)


def _regular_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file(): raise ValueError(f"not a regular file: {path}")
    return path.read_bytes()


def _reject_symlink_components(path: Path) -> None:
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("path must be absolute")
    cursor = Path(path.anchor)
    for component in path.parts[1:]:
        cursor /= component
        if cursor.exists() or cursor.is_symlink():
            if stat.S_ISLNK(cursor.lstat().st_mode):
                raise ValueError(f"symlink path component: {cursor}")


def _path_token(path: Path) -> tuple[object, ...]:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"not a regular file: {path}")
    metadata = path.lstat()
    data = path.read_bytes()
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        _sha(data),
    )


def _load_canonical_json(path: Path) -> tuple[dict[str, object], bytes]:
    raw = _regular_bytes(Path(path))
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid canonical JSON: {path}") from error
    if not isinstance(value, dict) or _canonical(value) != raw:
        raise ValueError(f"invalid canonical JSON object: {path}")
    return value, raw


def _projection_sha256(value: object) -> str:
    data = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("ascii")
    return _sha(data)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_real_root(path: Path, label: str) -> Path:
    value = Path(path)
    _reject_symlink_components(value)
    if not value.is_dir():
        raise ValueError(f"{label} must be an existing real directory")
    return value.resolve(strict=True)


def validate_package_roots(
    *,
    generated_sdk_root: Path,
    build_root: Path,
    reference_root: Path,
    run_root: Path,
    protected_roots: tuple[Path, ...],
) -> dict[str, Path]:
    supplied = {
        "generatedSdk": _validate_real_root(generated_sdk_root, "generated SDK root"),
        "build": _validate_real_root(build_root, "build root"),
        "reference": _validate_real_root(reference_root, "reference root"),
        "run": _validate_real_root(run_root, "run root"),
    }
    values = list(supplied.items())
    for index, (left_name, left) in enumerate(values):
        for right_name, right in values[index + 1:]:
            if _is_relative_to(left, right) or _is_relative_to(right, left):
                raise ValueError(f"package roots must be distinct and nonoverlapping: {left_name}/{right_name}")
    if not isinstance(protected_roots, tuple) or not protected_roots:
        raise ValueError("protected roots must be a nonempty tuple")
    protected = []
    for candidate in protected_roots:
        root = Path(candidate)
        if not root.is_absolute():
            raise ValueError("protected roots must be absolute")
        protected.append(root.resolve(strict=False))
    for label, value in supplied.items():
        for root in protected:
            if _is_relative_to(value, root) or _is_relative_to(root, value):
                raise ValueError(f"{label} overlaps or is an ancestor of a protected root")
    if not (supplied["generatedSdk"] / "SDK").is_dir():
        raise ValueError("generated SDK root is missing SDK")
    if not (supplied["build"] / "build-receipt.json").is_file():
        raise ValueError("build root is missing build receipt")
    if not (supplied["reference"] / "manifest.json").is_file():
        raise ValueError("reference root is missing manifest")
    if any(supplied["run"].iterdir()):
        raise ValueError("run root must be empty")
    run = supplied["run"]
    return {
        "build": supplied["build"],
        "control": run / "control",
        "delivery": run / "delivery",
        "evidence": run / "evidence",
        "generatedSdk": supplied["generatedSdk"],
        "reference": supplied["reference"],
        "run": run,
        "staging": run / "staging",
    }


def _load_locks(lock_root: Path) -> tuple[dict[str, dict[str, object]], dict[str, str], dict[str, tuple[object, ...]]]:
    root = _validate_real_root(lock_root, "lock root")
    entries = list(root.iterdir())
    names = {entry.name for entry in entries}
    if names not in (set(LOCK_FILENAMES), set(LOCK_FILENAMES) | {"sdk.lock.json"}) or any(entry.is_symlink() or not entry.is_file() for entry in entries):
        raise ValueError("lock root projection is not closed")
    values: dict[str, dict[str, object]] = {}
    hashes: dict[str, str] = {}
    tokens: dict[str, tuple[object, ...]] = {}
    for filename in LOCK_FILENAMES:
        path = root / filename
        value, raw = _load_canonical_json(path)
        digest = _sha(raw)
        if digest != LOCK_SHA256[filename]:
            raise ValueError(f"lock identity mismatch: {filename}")
        values[filename] = value
        hashes[filename] = digest
        tokens[str(path.resolve(strict=False))] = _path_token(path)
    return values, hashes, tokens


def _expected_runtime(toolchain_lock: dict[str, object]) -> dict[str, object]:
    runtime = toolchain_lock.get("runtime")
    host = toolchain_lock.get("hostTools")
    tools = toolchain_lock.get("tools")
    if not isinstance(runtime, dict) or not isinstance(host, dict) or not isinstance(tools, dict):
        raise ValueError("toolchain runtime authority is malformed")
    tool_root = Path("/home/jethac/.local/share/e87-dev/jieli")
    post_root = DEFAULT_POST_ROOT
    selected_tools = {}
    for name in ("ar", "ld", "linkVersion", "llvmGold", "ltoAr", "ltoWrapper"):
        pin = tools.get(name)
        if not isinstance(pin, dict) or not isinstance(pin.get("installRelativePath"), str):
            raise ValueError("toolchain runtime pin is malformed")
        resolved_relative = pin.get("resolvedInstallRelativePath", pin["installRelativePath"])
        if not isinstance(resolved_relative, str):
            raise ValueError("toolchain resolved runtime path is malformed")
        selected_tools[name] = {
            **copy.deepcopy(pin),
            "invocationPath": str(tool_root / pin["installRelativePath"]),
            "resolvedPath": str(tool_root / resolved_relative),
        }
    return {
        "controlledPath": f"{tool_root / 'pi32v2/bin'}:{post_root}:/usr/bin:/bin",
        "elfInterpreter": copy.deepcopy(runtime.get("elfInterpreter")),
        "hostTools": {name: copy.deepcopy(host[name]) for name in ("env", "python3")},
        "schema": "e87-stage0-build-runtime-v1",
        "toolchainLockSha256": LOCK_SHA256["toolchain.lock.json"],
        "tools": {name: selected_tools[name] for name in sorted(selected_tools)},
    }


def _validate_file_record(record: object, *, filename: str | None = None, nonempty: bool = True) -> dict[str, object]:
    if not isinstance(record, dict) or set(record) != {"filename", "sha256", "size"}:
        raise ValueError("file record projection is not closed")
    if filename is not None and record.get("filename") != filename:
        raise ValueError("file record name mismatch")
    if not isinstance(record.get("filename"), str) or not isinstance(record.get("sha256"), str) or HEX64.fullmatch(record["sha256"]) is None:
        raise ValueError("invalid file record")
    size = record.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < (1 if nonempty else 0):
        raise ValueError("invalid file record size")
    return record


def _expected_build_environment(source_date_epoch: int) -> dict[str, str]:
    return {
        "HOME": "$BUILD_CONTROL_ROOT/home",
        "TMPDIR": "$BUILD_CONTROL_ROOT/tmp",
        "LANG": "C",
        "LC_ALL": "C",
        "TZ": "UTC",
        "SOURCE_DATE_EPOCH": str(source_date_epoch),
        "PATH": BUILD_PATH,
    }


def _validate_build_execution_record(
    record: object,
    *,
    expected_keys: set[str],
    expected_environment: dict[str, str],
    label: str,
) -> dict[str, object]:
    if not isinstance(record, dict) or set(record) != expected_keys:
        raise ValueError(f"{label} projection is not closed")
    if record.get("cwd") != "$BUILD_ROOT" or record.get("environment") != expected_environment:
        raise ValueError(f"{label} execution context mismatch")
    if record.get("exitCode") != 0 or not isinstance(record.get("argv"), list) or not all(isinstance(item, str) for item in record["argv"]):
        raise ValueError(f"{label} execution result is invalid")
    for stream in ("stdout", "stderr"):
        raw_hex = record.get(f"{stream}Hex")
        raw_size = record.get(f"{stream}Size")
        raw_sha = record.get(f"{stream}Sha256")
        if not isinstance(raw_hex, str) or re.fullmatch(r"(?:[0-9A-F]{2})*", raw_hex) is None:
            raise ValueError(f"{label} {stream} hex is invalid")
        raw = bytes.fromhex(raw_hex)
        if not isinstance(raw_size, int) or isinstance(raw_size, bool) or raw_size != len(raw):
            raise ValueError(f"{label} {stream} size mismatch")
        if not isinstance(raw_sha, str) or HEX64.fullmatch(raw_sha) is None or raw_sha != _sha(raw):
            raise ValueError(f"{label} {stream} digest mismatch")
    tool_sha = record.get("toolSha256")
    if not isinstance(tool_sha, str) or HEX64.fullmatch(tool_sha) is None:
        raise ValueError(f"{label} tool digest is invalid")
    return record


def _validate_build_receipt_value(
    receipt: dict[str, object],
    *,
    toolchain_lock: dict[str, object],
    expected_source_commit: str | None = None,
) -> None:
    if set(receipt) != BUILD_RECEIPT_KEYS or receipt.get("schema") != "e87-stage0-build-receipt-v1":
        raise ValueError("build receipt projection is not closed")
    source_commit = receipt.get("sourceCommit")
    if not isinstance(source_commit, str) or SOURCE40.fullmatch(source_commit) is None or (expected_source_commit is not None and source_commit != expected_source_commit):
        raise ValueError("build receipt source identity mismatch")
    epoch = receipt.get("sourceDateEpoch")
    if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 0:
        raise ValueError("invalid build source epoch")
    expected_build_environment = _expected_build_environment(epoch)
    if receipt.get("environment") != expected_build_environment:
        raise ValueError("build environment receipt mismatch")
    if receipt.get("resourceLimits") != BUILD_RESOURCE_LIMITS:
        raise ValueError("build resource-limit receipt mismatch")
    if receipt.get("validations") != BUILD_VALIDATIONS or not all(type(value) is bool and value for value in receipt["validations"].values()):
        raise ValueError("build validation receipt mismatch")
    _validate_file_record(receipt.get("app"), filename="app.bin")
    _validate_file_record(receipt.get("elf"), filename="sdk.elf")
    bootstrap = receipt.get("bootstrap")
    if not isinstance(bootstrap, dict) or set(bootstrap) != {"commands", "gitTool", "locks", "outputTreeSha256", "overlay", "patch", "schema", "sdkCommit", "sdkTree", "sourceCommit", "sourceCommitEpoch", "sourceCommitObjectSha256", "sourceTree", "validations"}:
        raise ValueError("bootstrap receipt projection is not closed")
    if bootstrap.get("schema") != "e87-stage0-bootstrap-receipt-v1" or bootstrap.get("sourceCommit") != source_commit or bootstrap.get("sourceCommitEpoch") != epoch:
        raise ValueError("bootstrap/build source identity mismatch")
    for key in ("outputTreeSha256", "sourceCommitObjectSha256"):
        if not isinstance(bootstrap.get(key), str) or HEX64.fullmatch(bootstrap[key]) is None:
            raise ValueError("invalid bootstrap digest")
    for key in ("sdkCommit", "sdkTree", "sourceTree"):
        if not isinstance(bootstrap.get(key), str) or SOURCE40.fullmatch(bootstrap[key]) is None:
            raise ValueError("invalid bootstrap Git identity")
    sdk_pin = toolchain_lock.get("sdk")
    if not isinstance(sdk_pin, dict) or bootstrap.get("sdkCommit") != sdk_pin.get("commit") or bootstrap.get("sdkTree") != sdk_pin.get("tree"):
        raise ValueError("bootstrap SDK identity differs from the toolchain lock")
    if bootstrap.get("locks") != LOCK_SHA256:
        raise ValueError("bootstrap lock identities drifted")
    bootstrap_bytes = _canonical(bootstrap)
    bootstrap_record = _validate_file_record(receipt.get("bootstrapReceipt"), filename="bootstrap-receipt.json")
    if bootstrap_record["size"] != len(bootstrap_bytes) or bootstrap_record["sha256"] != _sha(bootstrap_bytes):
        raise ValueError("bootstrap receipt identity mismatch")
    replay = receipt.get("bootstrapValidation")
    expected_replay = {
        "commandsSha256": _projection_sha256(bootstrap.get("commands")),
        "outputTreeSha256": bootstrap.get("outputTreeSha256"),
        "receiptSha256": bootstrap_record["sha256"],
        "schema": "e87-stage0-bootstrap-replay-validation-v1",
        "validationsSha256": _projection_sha256(bootstrap.get("validations")),
    }
    if replay != expected_replay:
        raise ValueError("bootstrap replay validation mismatch")
    patch = bootstrap.get("patch")
    if not isinstance(patch, dict) or set(patch) != {"paths", "sha256", "size"} or not isinstance(patch.get("sha256"), str) or HEX64.fullmatch(patch["sha256"]) is None:
        raise ValueError("invalid bootstrap patch proof")
    overlay = bootstrap.get("overlay")
    if not isinstance(overlay, list) or not overlay:
        raise ValueError("invalid bootstrap overlay proof")
    for record in overlay:
        if not isinstance(record, dict) or set(record) != {"destination", "sha256", "size", "source"} or not isinstance(record.get("sha256"), str) or HEX64.fullmatch(record["sha256"]) is None:
            raise ValueError("invalid bootstrap overlay record")
    if receipt.get("runtime") != _expected_runtime(toolchain_lock):
        raise ValueError("build runtime receipt mismatch")
    target = receipt.get("target")
    if not isinstance(target, dict) or set(target) != {"architecture", "codeEnd", "cpu", "entryAddress", "mapSha256", "uiresStart"} or target.get("architecture") != "pi32v2" or target.get("cpu") != "r3" or target.get("entryAddress") != "0x0C000100" or target.get("uiresStart") != "0x00180000" or not isinstance(target.get("mapSha256"), str) or HEX64.fullmatch(target["mapSha256"]) is None:
        raise ValueError("build target receipt mismatch")
    commands = receipt.get("commands")
    expected_roles = ["make", *(f"objcopy:{section}" for section, _ in SECTION_OUTPUTS), "objdump", "nm"]
    if not isinstance(commands, list) or len(commands) != 11 or [item.get("role") if isinstance(item, dict) else None for item in commands] != expected_roles:
        raise ValueError("build command receipt mismatch")
    for command in commands:
        _validate_build_execution_record(
            command,
            expected_keys=BUILD_COMMAND_KEYS,
            expected_environment=expected_build_environment,
            label="build command",
        )
        if not isinstance(command.get("role"), str) or not isinstance(command.get("toolVersion"), str) or not command["toolVersion"]:
            raise ValueError("invalid build command identity")
    make_argv = commands[0]["argv"]
    if (
        len(make_argv) != 7
        or make_argv[0] != "/usr/bin/make"
        or make_argv[1] != "-C"
        or not isinstance(make_argv[2], str)
        or not make_argv[2].endswith("/SDK")
        or make_argv[3] != "TOOL_DIR=/home/jethac/.local/share/e87-dev/jieli/pi32v2/bin"
        or make_argv[4:] != ["RUN_POST_SCRIPT=true", "VERBOSE=0", "-j6"]
    ):
        raise ValueError("build make command drift")
    generated_sdk = Path(make_argv[2]).parent
    build_root = None
    authoritative_elf = str(generated_sdk / "SDK/cpu/br35/tools/sdk.elf")
    for index, (section, filename) in enumerate(SECTION_OUTPUTS, start=1):
        argv = commands[index]["argv"]
        if len(argv) != 7 or argv[1:6] != ["-O", "binary", "-j", section, authoritative_elf]:
            raise ValueError("build objcopy command drift")
        candidate = Path(argv[-1])
        if candidate.name != filename:
            raise ValueError("build objcopy output drift")
        if build_root is None:
            build_root = candidate.parent
        elif candidate.parent != build_root:
            raise ValueError("build objcopy roots disagree")
    objdump_argv = commands[-2]["argv"]
    nm_argv = commands[-1]["argv"]
    if objdump_argv[1:] != ["-private-headers", "-section-headers", "-mcpu=r3", authoritative_elf]:
        raise ValueError("build objdump command drift")
    if nm_argv[1:] != ["-n", "--defined-only", authoritative_elf]:
        raise ValueError("build nm command drift")
    section_outputs = receipt.get("sectionOutputs")
    if not isinstance(section_outputs, list) or [(item.get("section"), item.get("filename")) if isinstance(item, dict) else None for item in section_outputs] != list(SECTION_OUTPUTS):
        raise ValueError("build section output projection mismatch")
    for record in section_outputs:
        if set(record) != {"filename", "section", "sha256", "size"} or not isinstance(record.get("sha256"), str) or HEX64.fullmatch(record["sha256"]) is None or not isinstance(record.get("size"), int) or isinstance(record.get("size"), bool) or record["size"] <= 0:
            raise ValueError("invalid build section output")
    sections = receipt.get("sections")
    if not isinstance(sections, list) or len(sections) != len(SECTION_OUTPUTS) or [item.get("name") if isinstance(item, dict) else None for item in sections] != [name for name, _ in SECTION_OUTPUTS]:
        raise ValueError("build section projection mismatch")
    if receipt.get("sourceObjects") != list(SOURCE_OBJECTS):
        raise ValueError("build source object projection mismatch")
    inputs = receipt.get("inputs")
    if not isinstance(inputs, list) or len(inputs) != 1 or inputs[0] != bootstrap_record:
        raise ValueError("build input projection mismatch")
    probes = receipt.get("versionProbes")
    if not isinstance(probes, list) or [item.get("tool") if isinstance(item, dict) else None for item in probes] != ["make", "objcopy", "objdump", "nm"]:
        raise ValueError("build version probe projection mismatch")
    commands_by_tool = {
        "make": commands[0],
        "objcopy": commands[1],
        "objdump": commands[-2],
        "nm": commands[-1],
    }
    for probe in probes:
        _validate_build_execution_record(
            probe,
            expected_keys=BUILD_VERSION_PROBE_KEYS,
            expected_environment=expected_build_environment,
            label="build version probe",
        )
        tool = probe.get("tool")
        command = commands_by_tool[tool]
        if (
            probe.get("argv") != [command["argv"][0], "--version"]
            or probe.get("toolSha256") != command.get("toolSha256")
            or probe.get("version") != command.get("toolVersion")
        ):
            raise ValueError("build version probe identity mismatch")
    provenance = receipt.get("buildProvenance")
    if not isinstance(provenance, dict) or set(provenance) != {"compileMakefile", "linkMakefile"}:
        raise ValueError("build provenance projection mismatch")


def _read_build_receipt(
    path: Path,
    *,
    toolchain_lock: dict[str, object],
    expected_source_commit: str | None = None,
) -> tuple[dict[str, object], bytes]:
    value, raw = _load_canonical_json(path)
    _validate_build_receipt_value(value, toolchain_lock=toolchain_lock, expected_source_commit=expected_source_commit)
    return value, raw


def _snapshot(root: Path) -> dict[str, tuple[int, str]]:
    result = {}
    for path in root.iterdir():
        if path.is_symlink() or not path.is_file(): raise ValueError(f"non-regular staging entry: {path.name}")
        data = path.read_bytes(); result[path.name] = (len(data), _sha(data))
    return result


def validate_package_source(relative_path: str, data: bytes) -> None:
    if relative_path == FORBIDDEN_INI: raise ValueError("135-byte binary property INI is forbidden")
    if relative_path not in STAGING_SOURCES.values(): raise ValueError("unknown package source")
    if not isinstance(data, bytes) or not data: raise ValueError("package source must be nonempty bytes")


def verify_reference_root(reference_root: Path, model_lock: dict) -> dict[str, object]:
    root = Path(reference_root)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir(): raise ValueError("reference root must be an absolute real directory")
    if root.stat().st_mode & 0o222: raise ValueError("reference root must be read-only")
    if not isinstance(model_lock, dict) or model_lock.get("schema") != "e87-stage0-model1552-package-lock-v1": raise ValueError("wrong model lock")
    records = model_lock.get("referenceFiles")
    if not isinstance(records, dict) or len(records) != 11: raise ValueError("wrong reference file projection")
    verified = {}
    for relative, record in records.items():
        if not isinstance(relative, str) or relative.startswith("/") or ".." in Path(relative).parts or "\\" in relative: raise ValueError("unsafe reference path")
        path = root / relative; data = _regular_bytes(path)
        if path.stat().st_mode & 0o222: raise ValueError("reference file must be read-only")
        if set(record) != {"byteLength", "role", "sha256"}: raise ValueError("wrong reference record schema")
        if isinstance(record["byteLength"], bool) or len(data) != record["byteLength"] or _sha(data) != record["sha256"]: raise ValueError(f"reference identity mismatch: {relative}")
        verified[relative] = {"sha256": _sha(data), "size": len(data)}
    inputs = sorted(STAGING_SOURCES.values())
    if FORBIDDEN_INI in inputs: raise ValueError("forbidden binary INI selected")
    return {"fileCount": len(verified), "manifestSha256": verified["manifest.json"]["sha256"], "packageInputs": inputs, "verifiedFiles": verified}


def transform_reset_ini(source: bytes) -> tuple[bytes, dict[str, object]]:
    if not isinstance(source, bytes): raise TypeError("INI must be bytes")
    old = b"RESET = PB07_08_0;"; new = b"RESET = PB07_00_0;"
    lines = source.splitlines(keepends=True)
    matches = [index for index, line in enumerate(lines) if line.rstrip(b"\r\n") == old]
    if len(matches) != 1 or source.count(old) != 1 or source.count(new) != 0: raise ValueError("reset policy source line must occur exactly once")
    index = matches[0]; ending = lines[index][len(lines[index].rstrip(b"\r\n")):]
    lines[index] = new + ending; transformed = b"".join(lines)
    if len(transformed) != len(source) or transformed.count(new) != 1 or old in transformed: raise ValueError("reset transformation drift")
    return transformed, {"after": new.decode("ascii"), "before": old.decode("ascii"), "occurrences": 1}


def stage_inputs(
    reference_root: Path,
    sdk_root: Path,
    app_bin: Path,
    staging_root: Path,
    model_lock: dict,
    *,
    build_receipt: dict[str, object],
) -> dict[str, object]:
    verify_reference_root(reference_root, model_lock)
    staging = Path(staging_root)
    if not staging.is_absolute() or staging.is_symlink() or not staging.is_dir() or any(staging.iterdir()): raise ValueError("staging root must be absolute, empty, and real")
    if not isinstance(build_receipt, dict):
        raise ValueError("build receipt must be an object")
    app_record = build_receipt.get("app")
    if not isinstance(app_record, dict) or set(app_record) != {"filename", "sha256", "size"}:
        raise ValueError("build receipt app projection is not closed")
    if app_record["filename"] != "app.bin" or not isinstance(app_record["size"], int) or isinstance(app_record["size"], bool) or app_record["size"] <= 0 or not isinstance(app_record["sha256"], str) or HEX64.fullmatch(app_record["sha256"]) is None:
        raise ValueError("invalid build receipt app record")
    app_data = _regular_bytes(Path(app_bin))
    if len(app_data) != app_record["size"] or _sha(app_data) != app_record["sha256"]:
        raise ValueError("app.bin does not match the canonical build receipt")
    loader_record = model_lock["sdkLoader"]
    loader_path = Path(sdk_root) / loader_record["sdkRelativePath"]; loader_data = _regular_bytes(loader_path)
    if len(loader_data) != loader_record["byteLength"] or _sha(loader_data) != loader_record["sha256"]: raise ValueError("SDK loader identity mismatch")
    sources_before = {}
    staged = {"app.bin": app_data, "br35loader.bin": loader_data}
    for destination, relative in STAGING_SOURCES.items():
        path = Path(reference_root) / relative; data = _regular_bytes(path); sources_before[str(path)] = _sha(data)
        validate_package_source(relative, data)
        if destination == "isd_config.ini": data, reset_diff = transform_reset_ini(data)
        staged[destination] = data
    for name, data in staged.items(): _write_new(staging / name, data)
    for filename, digest in sources_before.items():
        if _sha(Path(filename).read_bytes()) != digest: raise ValueError("reference source changed during staging")
    return {
        "inputCount": len(staged),
        "inputs": [
            {
                "filename": name,
                "role": "REVIEWED_APP" if name == "app.bin" else "PINNED_PACKAGE_INPUT",
                "sha256": _sha(data),
                "size": len(data),
            }
            for name, data in sorted(staged.items())
        ],
        "resetDiff": reset_diff,
    }


def package_environment(control_root: Path, *, source_date_epoch: int, post_root: Path = DEFAULT_POST_ROOT) -> dict[str, str]:
    root = Path(control_root)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir(): raise ValueError("control root must be absolute and real")
    if isinstance(source_date_epoch, bool) or not isinstance(source_date_epoch, int) or source_date_epoch < 0: raise ValueError("invalid source epoch")
    home = root / "home"; temporary = root / "tmp"
    for path in (home, temporary):
        if path.exists() or path.is_symlink(): raise ValueError("controlled environment directory preexists")
        path.mkdir(mode=0o700)
    post = Path(post_root)
    _reject_symlink_components(post)
    if not post.is_dir(): raise ValueError("post-build tool root must be a directory")
    result = {"HOME": str(home), "TMPDIR": str(temporary), "LANG": "C", "LC_ALL": "C", "TZ": "UTC", "SOURCE_DATE_EPOCH": str(source_date_epoch), "PATH": f"{post}:/usr/bin:/bin"}
    validate_package_environment(result, root, source_date_epoch=source_date_epoch, post_root=post)
    return result


def validate_package_environment(environment: dict[str, str], control_root: Path | None = None, *, source_date_epoch: int | None = None, post_root: Path = DEFAULT_POST_ROOT) -> None:
    if not isinstance(environment, dict) or set(environment) != ENV_KEYS or not all(isinstance(k, str) and isinstance(v, str) for k, v in environment.items()): raise ValueError("package environment is not closed")
    expected_path = f"{Path(post_root)}:/usr/bin:/bin"
    if (environment["LANG"], environment["LC_ALL"], environment["TZ"], environment["PATH"]) != ("C", "C", "UTC", expected_path): raise ValueError("package environment value drift")
    if not environment["SOURCE_DATE_EPOCH"].isdigit(): raise ValueError("source epoch must be decimal")
    if source_date_epoch is not None and environment["SOURCE_DATE_EPOCH"] != str(source_date_epoch): raise ValueError("source epoch mismatch")
    for key in ("HOME", "TMPDIR"):
        path = Path(environment[key])
        if not path.is_absolute() or path.is_symlink() or not path.is_dir(): raise ValueError("controlled path must be absolute and real")
    if control_root is not None:
        root = Path(control_root).resolve(strict=True)
        if Path(environment["HOME"]).resolve(strict=True) != root / "home" or Path(environment["TMPDIR"]).resolve(strict=True) != root / "tmp": raise ValueError("controlled paths escape root")


def reject_dangerous_argv(argv: list[str]) -> None:
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) and item and "\x00" not in item for item in argv): raise ValueError("argv must be a nonempty string array")
    for argument in argv[1:]:
        lowered = argument.lower()
        if any(token in lowered for token in ("-format", "-tone", "-key", "efuse", "otp", "-usb", "-serial", "-port", "-write", "-burn", "/dev/tty")) or re.fullmatch(r"com\d+", lowered) or any(char in argument for char in "*?["):
            raise ValueError(f"dangerous package argument: {argument}")


def isd_command(tool: Path) -> list[str]:
    command = [str(Path(tool)), *ISD_ARGUMENTS]; reject_dangerous_argv(command); return command


def ufw_maker_command(tool: Path) -> list[str]:
    command = [str(Path(tool)), *UFW_ARGUMENTS]; reject_dangerous_argv(command); return command


def resolve_locked_package_tools(packaging_lock: dict[str, object], *, post_root: Path = DEFAULT_POST_ROOT) -> dict[str, dict[str, object]]:
    if not isinstance(packaging_lock, dict) or set(packaging_lock) != {"archive", "isdArgv", "nativeOutputs", "qix", "schema", "tools", "ufwMakerArgv"}:
        raise ValueError("packaging lock projection is not closed")
    if packaging_lock.get("schema") != "e87-stage0-packaging-lock-v1" or packaging_lock.get("isdArgv") != ISD_ARGUMENTS or packaging_lock.get("ufwMakerArgv") != UFW_ARGUMENTS:
        raise ValueError("packaging lock command drift")
    pins = packaging_lock.get("tools")
    if not isinstance(pins, dict) or set(pins) != {"fwAdd", "isdDownload", "ufwMaker"}:
        raise ValueError("package tool projection is not closed")
    root = Path(post_root)
    _reject_symlink_components(root)
    if not root.is_dir():
        raise ValueError("post-build tool root must be an absolute real directory")
    result: dict[str, dict[str, object]] = {}
    for name in ("fwAdd", "isdDownload", "ufwMaker"):
        record = pins[name]
        if not isinstance(record, dict):
            raise ValueError(f"invalid package tool record: {name}")
        relative = record.get("installRelativePath")
        digest = record.get("sha256")
        if not isinstance(relative, str) or not relative or "/" in relative or "\\" in relative or not isinstance(digest, str) or HEX64.fullmatch(digest) is None:
            raise ValueError(f"invalid package tool pin: {name}")
        path = root / relative
        data = _regular_bytes(path)
        if _sha(data) != digest or not (path.stat().st_mode & 0o111):
            raise ValueError(f"package tool identity mismatch: {name}")
        result[name] = {**copy.deepcopy(record), "path": str(path)}
    if result["fwAdd"].get("invocation") != "FORBIDDEN":
        raise ValueError("fw_add invocation must remain forbidden")
    return result


def _invoke(runner, argv: list[str], staging: Path, environment: dict[str, str]):
    reject_dangerous_argv(argv)
    result = runner(argv, cwd=staging, env=dict(environment), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, shell=False)
    if not isinstance(result, subprocess.CompletedProcess): raise ValueError("runner returned invalid result")
    stdout = result.stdout.encode() if isinstance(result.stdout, str) else result.stdout
    stderr = result.stderr.encode() if isinstance(result.stderr, str) else result.stderr
    if not isinstance(stdout, bytes) or not isinstance(stderr, bytes) or result.returncode != 0: raise ValueError("native package command failed")
    if PROMPT_PATTERN.search(stdout + b"\n" + stderr): raise ValueError("native tool emitted prompt or device output")
    return result


def _check_transition(before: dict[str, tuple[int, str]], after: dict[str, tuple[int, str]], allowed_new: set[str]) -> None:
    if not set(before).issubset(after) or any(after[name] != value for name, value in before.items()): raise ValueError("native tool mutated or removed an input")
    new = set(after) - set(before)
    if new != allowed_new: raise ValueError(f"native output allowlist mismatch: {sorted(new)}")
    if any(after[name][0] == 0 for name in new): raise ValueError("native output is empty")


def run_native_packagers(
    staging_root: Path,
    tools: dict[str, dict[str, object]],
    *,
    expected_inputs: list[dict[str, object]],
    control_root: Path,
    environment: dict[str, str],
    runner=subprocess.run,
    event_sink=None,
    use_window_hook=None,
    command_sink: list[dict[str, object]] | None = None,
    post_root: Path = DEFAULT_POST_ROOT,
) -> dict[str, Path]:
    staging = Path(staging_root)
    if not staging.is_absolute() or staging.is_symlink() or not staging.is_dir(): raise ValueError("staging root must be absolute and real")
    if set(tools) != {"fwAdd", "isdDownload", "ufwMaker"}: raise ValueError("native tool projection is not closed")
    validate_package_environment(environment, control_root, source_date_epoch=int(environment.get("SOURCE_DATE_EPOCH", "-1")), post_root=post_root)
    if not isinstance(expected_inputs, list) or len(expected_inputs) != 10:
        raise ValueError("expected staging projection must contain ten inputs")
    expected_by_name = {}
    for record in expected_inputs:
        if not isinstance(record, dict) or set(record) != {"filename", "role", "sha256", "size"}:
            raise ValueError("invalid staging input record")
        name = record["filename"]
        if name in expected_by_name or name not in STAGING_NAMES or record["role"] not in {"REVIEWED_APP", "PINNED_PACKAGE_INPUT"} or not isinstance(record["size"], int) or isinstance(record["size"], bool) or record["size"] <= 0 or not isinstance(record["sha256"], str) or HEX64.fullmatch(record["sha256"]) is None:
            raise ValueError("invalid staging input identity")
        expected_by_name[name] = (record["size"], record["sha256"])
    if set(expected_by_name) != STAGING_NAMES or expected_by_name != _snapshot(staging):
        raise ValueError("staging inputs do not match the expected projection")
    before = _snapshot(staging)
    before_tokens = {name: _path_token(staging / name) for name in before}
    native = {"jl_isd.bin", "jl_isd.fw", "update.ufw"}

    def execute(
        role: str,
        command: list[str],
        allowed: set[str],
        prior: dict[str, tuple[int, str]],
        prior_tokens: dict[str, tuple[object, ...]],
    ) -> tuple[dict[str, tuple[int, str]], dict[str, tuple[object, ...]]]:
        if use_window_hook is not None: use_window_hook(f"before-{role}")
        for name, token in prior_tokens.items():
            if _path_token(staging / name) != token:
                raise ValueError(f"package input changed during use window: {name}")
        tool = tools[role]
        tool_path = Path(str(tool["path"]))
        if _sha(_regular_bytes(tool_path)) != tool.get("sha256"):
            raise ValueError(f"package tool changed before use: {role}")
        if event_sink is not None: event_sink(f"tool:{role}:rehashed")
        current = _snapshot(staging)
        if current != prior:
            raise ValueError(f"package inputs changed before {role}")
        if event_sink is not None: event_sink(f"inputs:{role}:rehashed")
        result = _invoke(runner, command, staging, environment)
        after = _snapshot(staging)
        _check_transition(prior, after, allowed)
        after_tokens = {name: _path_token(staging / name) for name in after}
        for name, token in prior_tokens.items():
            if after_tokens[name] != token:
                raise ValueError(f"native tool changed an existing input identity: {name}")
        if event_sink is not None: event_sink(f"outputs:{role}:validated")
        if command_sink is not None:
            stdout = result.stdout.encode() if isinstance(result.stdout, str) else result.stdout
            stderr = result.stderr.encode() if isinstance(result.stderr, str) else result.stderr
            command_sink.append({
                "argv": list(command), "exitCode": result.returncode, "role": role,
                "stderrHex": stderr.hex().upper(), "stderrSha256": _sha(stderr), "stderrSize": len(stderr),
                "stdoutHex": stdout.hex().upper(), "stdoutSha256": _sha(stdout), "stdoutSize": len(stdout),
                "toolSha256": tool["sha256"], "toolVersion": tool.get("version"),
            })
        return after, after_tokens

    after_isd, after_isd_tokens = execute("isdDownload", isd_command(Path(str(tools["isdDownload"]["path"]))), native, before, before_tokens)
    after_ufw, _ = execute("ufwMaker", ufw_maker_command(Path(str(tools["ufwMaker"]["path"]))), {"independently-made.ufw"}, after_isd, after_isd_tokens)
    names = native | {"independently-made.ufw"}
    return {name: staging / name for name in sorted(names)}


def _load_ufw():
    path = Path(__file__).with_name("ufw.py"); spec = importlib.util.spec_from_file_location("e87_stage0_package_ufw", path)
    if spec is None or spec.loader is None: raise ValueError("cannot load UFW validator")
    module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module); return module


def compare_ufw_or_raise(first: Path, second: Path) -> dict[str, object]:
    left = _regular_bytes(Path(first)); right = _regular_bytes(Path(second)); ufw = _load_ufw()
    if left != right:
        limit = min(len(left), len(right)); offset = next((index for index in range(limit) if left[index] != right[index]), limit)
        semantic = []
        for label, data in (("first", left), ("second", right)):
            try:
                parsed = ufw.parse_ufw(data)
                post_image = parsed["postImage"]
                post_summary = "none" if post_image is None else post_image["bodySha256"]
                semantic.append(
                    f"{label}={parsed['chip']}/v{parsed['formatVersion']}"
                    f"/items={parsed['itemCount']}/image=0x{parsed['imageSize']:X}"
                    f"/postImage.bodySha256={post_summary}"
                )
            except ValueError as error: semantic.append(f"{label}=INVALID:{error}")
        left_byte = left[offset] if offset < len(left) else None; right_byte = right[offset] if offset < len(right) else None
        left_hex = "EOF" if left_byte is None else f"{left_byte:02X}"; right_hex = "EOF" if right_byte is None else f"{right_byte:02X}"
        raise ValueError(f"first difference at 0x{offset:X}: {left_hex}!={right_hex}; semantic difference: {'; '.join(semantic)}")
    validator = getattr(ufw, "validate_stage0_ufw", None)
    if not callable(validator): raise ValueError("UFW validator has no validate_stage0_ufw API")
    validator(left)
    return {"sha256": _sha(left), "size": len(left)}


def _load_sibling(filename: str, module_name: str):
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_build_tool():
    return _load_sibling("build-target.py", "e87_stage0_package_build_authority")


def _validate_build_authority(
    *,
    generated_sdk_root: Path,
    build_root: Path,
    bootstrap_receipt_path: Path,
    control_root: Path,
    expected_source_commit: str,
    observed_receipt: dict[str, object],
    observed_raw: bytes,
) -> dict[str, object]:
    build = Path(build_root)
    bootstrap = Path(bootstrap_receipt_path)
    if bootstrap != build / "bootstrap-receipt.json":
        raise ValueError("build authority requires the canonical bootstrap receipt copy")
    if not isinstance(observed_receipt, dict) or not isinstance(observed_raw, bytes) or _canonical(observed_receipt) != observed_raw:
        raise ValueError("observed build receipt is not canonical")
    build_tool = _load_build_tool()
    validator = getattr(build_tool, "validate_build_for_package", None)
    if not callable(validator) or not callable(subprocess.run):
        raise ValueError("build validation authority is unavailable")
    authoritative = validator(
        generated_sdk_root=Path(generated_sdk_root),
        build_root=build,
        bootstrap_receipt_path=bootstrap,
        control_root=Path(control_root),
        expected_source_commit=expected_source_commit,
        runner=subprocess.run,
    )
    if not isinstance(authoritative, dict) or authoritative != observed_receipt or _canonical(authoritative) != observed_raw:
        raise ValueError("build receipt differs from independent build authority")
    return copy.deepcopy(authoritative)


def _snapshot_expected_inputs(records: list[dict[str, object]]) -> dict[str, tuple[int, str]]:
    if not isinstance(records, list) or len(records) != 10:
        raise ValueError("package input projection must contain ten records")
    result = {}
    for record in records:
        if not isinstance(record, dict) or set(record) != {"filename", "role", "sha256", "size"}:
            raise ValueError("package input record projection is not closed")
        name = record.get("filename")
        digest = record.get("sha256")
        size = record.get("size")
        expected_role = "REVIEWED_APP" if name == "app.bin" else "PINNED_PACKAGE_INPUT"
        if name not in STAGING_NAMES or name in result or record.get("role") != expected_role or not isinstance(size, int) or isinstance(size, bool) or size <= 0 or not isinstance(digest, str) or HEX64.fullmatch(digest) is None:
            raise ValueError("invalid package input record")
        result[name] = (size, digest)
    if set(result) != STAGING_NAMES:
        raise ValueError("package input filename projection is not closed")
    return result


def reverify_package_inputs(
    *,
    reference_root: Path,
    sdk_root: Path,
    generated_sdk_root: Path,
    build_root: Path,
    staging_root: Path,
    expected_source_commit: str,
    tools: dict[str, dict[str, object]],
    expected_staging: dict[str, tuple[int, str]],
    model_lock: dict[str, object] | None = None,
    toolchain_lock: dict[str, object] | None = None,
    expected_tokens: dict[str, tuple[object, ...]] | None = None,
) -> dict[str, object]:
    repository_root = Path(__file__).resolve().parents[2]
    if model_lock is None or toolchain_lock is None:
        locks, _, _ = _load_locks(repository_root / "firmware/locks")
        model_lock = model_lock or locks["model1552-package.lock.json"]
        toolchain_lock = toolchain_lock or locks["toolchain.lock.json"]
    if not isinstance(model_lock, dict) or not isinstance(toolchain_lock, dict):
        raise ValueError("missing lock authority")
    verify_reference_root(reference_root, model_lock)
    sdk = _validate_real_root(sdk_root, "SDK root")
    generated = _validate_real_root(generated_sdk_root, "generated SDK root")
    build = _validate_real_root(build_root, "build root")
    staging = _validate_real_root(staging_root, "staging root")
    if _snapshot(staging) != expected_staging or set(expected_staging) != STAGING_NAMES or any(size <= 0 for size, _ in expected_staging.values()):
        raise ValueError("staging identity changed")
    loader_record = model_lock.get("sdkLoader")
    if not isinstance(loader_record, dict):
        raise ValueError("SDK loader pin is missing")
    loader = sdk / str(loader_record.get("sdkRelativePath"))
    loader_data = _regular_bytes(loader)
    if len(loader_data) != loader_record.get("byteLength") or _sha(loader_data) != loader_record.get("sha256"):
        raise ValueError("SDK loader identity mismatch")
    if set(tools) != {"fwAdd", "isdDownload", "ufwMaker"}:
        raise ValueError("package tool projection is not closed")
    for name, record in tools.items():
        if not isinstance(record, dict) or not isinstance(record.get("path"), str) or not isinstance(record.get("sha256"), str):
            raise ValueError("invalid package tool projection")
        if _sha(_regular_bytes(Path(record["path"]))) != record["sha256"]:
            raise ValueError(f"package tool identity mismatch: {name}")
    receipt_path = build / "build-receipt.json"
    receipt, raw = _read_build_receipt(receipt_path, toolchain_lock=toolchain_lock, expected_source_commit=expected_source_commit)
    bootstrap_bytes = _canonical(receipt["bootstrap"])
    if _regular_bytes(build / str(receipt["bootstrapReceipt"]["filename"])) != bootstrap_bytes:
        raise ValueError("bootstrap receipt changed")
    for record in (receipt["app"], receipt["elf"], *receipt["sectionOutputs"]):
        path = build / str(record["filename"])
        data = _regular_bytes(path)
        if len(data) != record["size"] or _sha(data) != record["sha256"]:
            raise ValueError(f"build output identity mismatch: {record['filename']}")
    authoritative_elf = generated / "SDK/cpu/br35/tools/sdk.elf"
    if _regular_bytes(authoritative_elf) != _regular_bytes(build / "sdk.elf"):
        raise ValueError("authoritative ELF differs from build evidence")
    map_path = generated / "SDK/cpu/br35/tools/sdk.map"
    if _sha(_regular_bytes(map_path)) != receipt["target"]["mapSha256"]:
        raise ValueError("link map identity mismatch")
    for relative in SOURCE_OBJECTS:
        if not _regular_bytes(generated / "SDK/build" / relative):
            raise ValueError("source object is empty")
    for record in receipt["bootstrap"]["overlay"]:
        data = _regular_bytes(generated / str(record["destination"]))
        if len(data) != record["size"] or _sha(data) != record["sha256"]:
            raise ValueError("generated overlay identity mismatch")
    for record in receipt["buildProvenance"].values():
        if not isinstance(record, dict) or not isinstance(record.get("relativePath"), str) or not isinstance(record.get("sha256"), str):
            raise ValueError("invalid build provenance")
        if _sha(_regular_bytes(generated / record["relativePath"])) != record["sha256"]:
            raise ValueError("build provenance identity mismatch")
    if expected_tokens is not None:
        for raw_path, token in expected_tokens.items():
            if _path_token(Path(raw_path)) != token:
                raise ValueError(f"package input changed during use window: {raw_path}")
    return {
        "app": copy.deepcopy(receipt["app"]),
        "buildReceipt": receipt,
        "buildReceiptSha256": _sha(raw),
        "sourceCommit": receipt["sourceCommit"],
        "sourceDateEpoch": receipt["sourceDateEpoch"],
    }


def _derive_package_proofs_uncached(
    data: dict[str, bytes],
    *,
    app_record: dict[str, object],
    expected_source_commit: str,
    staged_ini_sha256: str,
    qix_name: str,
    qix_version: str,
    event_sink=None,
) -> dict[str, object]:
    required = {"app.bin", "jl_isd.bin", "jl_isd.fw", "update.ufw", "independently-made.ufw", qix_name}
    if set(data) != required or any(not isinstance(value, bytes) or not value for value in data.values()):
        raise ValueError("package proof byte projection is incomplete")
    _validate_file_record(app_record, filename="app.bin")
    if len(data["app.bin"]) != app_record["size"] or _sha(data["app.bin"]) != app_record["sha256"]:
        raise ValueError("package app does not match build receipt")
    jlfw = _load_sibling("jlfw.py", "e87_stage0_package_jlfw")
    bin_proof = jlfw.prove_embedded_app(data["jl_isd.bin"], data["app.bin"], container_kind="jl_isd.bin")
    fw_proof = jlfw.prove_embedded_app(data["jl_isd.fw"], data["app.bin"], container_kind="jl_isd.fw")
    pair = jlfw.prove_package_pair(data["jl_isd.bin"], data["jl_isd.fw"], data["app.bin"])
    if event_sink is not None:
        event_sink("proof:jlfw")
    ufw = _load_ufw()

    def ufw_summary(payload: bytes) -> dict[str, object]:
        parsed = ufw.validate_stage0_ufw(payload)
        flash = next(entry["data"] for entry in parsed["entries"] if entry["name"] == "flash.bin")
        ini = next(entry["data"] for entry in parsed["entries"] if entry["name"] == "isd_config.ini")
        return {
            "flashSha256": _sha(flash),
            "iniSha256": _sha(ini),
            "itemCount": parsed["itemCount"],
            "sha256": _sha(payload),
            "size": len(payload),
        }

    native = ufw_summary(data["update.ufw"])
    independent = ufw_summary(data["independently-made.ufw"])
    if data["update.ufw"] != data["independently-made.ufw"] or native != independent:
        raise ValueError("independent UFW is not byte-identical")
    if native["flashSha256"] != bin_proof["flashSha256"] or native["iniSha256"] != staged_ini_sha256:
        raise ValueError("UFW payload cross-binding mismatch")
    if event_sink is not None:
        event_sink("proof:ufw")
    qix = _load_sibling("qix.py", "e87_stage0_package_qix")
    parsed_qix = qix.parse_qix(data[qix_name], expected_version=qix_version)
    payload = parsed_qix["payload"]
    if payload != data["update.ufw"]:
        raise ValueError("Qix payload is not byte-identical to update.ufw")
    if event_sink is not None:
        event_sink("proof:qix")
    return {
        "jlfw": {
            "appSha256": pair["appSha256"],
            "appSize": len(data["app.bin"]),
            "entryAddress": bin_proof["entryAddress"],
            "flashEqual": pair["flashEqual"],
            "flashSha256": bin_proof["flashSha256"],
            "fwEnvelopeKind": pair["fwEnvelopeKind"],
            "jlIsdBinSha256": bin_proof["containerSha256"],
            "jlIsdFwSha256": fw_proof["containerSha256"],
        },
        "qix": {
            "payloadFilename": "update.ufw",
            "payloadSha256": _sha(data["update.ufw"]),
            "qixSha256": _sha(data[qix_name]),
            "qixSize": len(data[qix_name]),
            "relation": "BYTE_IDENTICAL",
            "unwrappedPayloadSha256": _sha(payload),
            "version": parsed_qix["version"],
        },
        "resetPolicy": {
            "recoveredSha256": "CEC1973E50FB7A3D74D04D6340C671A443D50C538C272E1B14567C71F9AED47A",
            "semanticDiff": {"after": "RESET = PB07_00_0;", "before": "RESET = PB07_08_0;", "occurrences": 1},
            "stagedSha256": native["iniSha256"],
        },
        "ufw": {"independent": independent, "native": native, "relation": "BYTE_IDENTICAL"},
    }


@lru_cache(maxsize=16)
def _cached_package_proofs(
    app: bytes,
    jl_isd_bin: bytes,
    jl_isd_fw: bytes,
    update_ufw: bytes,
    independent_ufw: bytes,
    qix_payload: bytes,
    app_sha256: str,
    app_size: int,
    expected_source_commit: str,
    staged_ini_sha256: str,
    qix_name: str,
    qix_version: str,
) -> dict[str, object]:
    return _derive_package_proofs_uncached(
        {
            "app.bin": app,
            "jl_isd.bin": jl_isd_bin,
            "jl_isd.fw": jl_isd_fw,
            "update.ufw": update_ufw,
            "independently-made.ufw": independent_ufw,
            qix_name: qix_payload,
        },
        app_record={"filename": "app.bin", "sha256": app_sha256, "size": app_size},
        expected_source_commit=expected_source_commit,
        staged_ini_sha256=staged_ini_sha256,
        qix_name=qix_name,
        qix_version=qix_version,
        event_sink=None,
    )


def _derive_package_proofs(
    data: dict[str, bytes],
    *,
    app_record: dict[str, object],
    expected_source_commit: str,
    staged_ini_sha256: str,
    qix_name: str,
    qix_version: str,
    event_sink=None,
) -> dict[str, object]:
    _validate_file_record(app_record, filename="app.bin")
    required = {"app.bin", "jl_isd.bin", "jl_isd.fw", "update.ufw", "independently-made.ufw", qix_name}
    if set(data) != required:
        raise ValueError("package proof byte projection is incomplete")
    proof = _cached_package_proofs(
        data["app.bin"],
        data["jl_isd.bin"],
        data["jl_isd.fw"],
        data["update.ufw"],
        data["independently-made.ufw"],
        data[qix_name],
        str(app_record["sha256"]),
        int(app_record["size"]),
        expected_source_commit,
        staged_ini_sha256,
        qix_name,
        qix_version,
    )
    if event_sink is not None:
        for event in ("proof:jlfw", "proof:ufw", "proof:qix"):
            event_sink(event)
    return copy.deepcopy(proof)


def validate_package_outputs(
    staging_root: Path,
    *,
    app_record: dict[str, object],
    expected_source_commit: str,
    staged_ini_sha256: str,
    qix_name: str,
    qix_version: str,
    event_sink=None,
) -> dict[str, object]:
    staging = _validate_real_root(staging_root, "staging root")
    _validate_file_record(app_record, filename="app.bin")
    if not isinstance(expected_source_commit, str) or SOURCE40.fullmatch(expected_source_commit) is None:
        raise ValueError("invalid expected source commit")
    expected_qix_name = f"E87-{QIX_VERSION}-{expected_source_commit[:8].upper()}.qix"
    if qix_version != QIX_VERSION or qix_name != expected_qix_name:
        raise ValueError("Qix name/version does not bind the source commit")
    if not isinstance(staged_ini_sha256, str) or HEX64.fullmatch(staged_ini_sha256) is None:
        raise ValueError("invalid staged INI identity")
    required = {"app.bin", "jl_isd.bin", "jl_isd.fw", "update.ufw", "independently-made.ufw", qix_name}
    actual = {path.name for path in staging.iterdir()}
    if not required.issubset(actual):
        raise ValueError("package proof inputs are incomplete")
    data = {name: _regular_bytes(staging / name) for name in required}
    return _derive_package_proofs(
        data,
        app_record=app_record,
        expected_source_commit=expected_source_commit,
        staged_ini_sha256=staged_ini_sha256,
        qix_name=qix_name,
        qix_version=qix_version,
        event_sink=event_sink,
    )


def _output_record(path: Path, role: str, delivered: bool, validation: dict[str, object]) -> dict[str, object]:
    data = _regular_bytes(path)
    if not data:
        raise ValueError(f"empty output artifact: {path.name}")
    return {
        "delivered": delivered,
        "filename": path.name,
        "role": role,
        "sha256": _sha(data),
        "size": len(data),
        "validation": copy.deepcopy(validation),
    }


def _infer_post_root(environment: dict[str, str]) -> Path:
    suffix = ":/usr/bin:/bin"
    path_value = environment.get("PATH")
    if not isinstance(path_value, str) or not path_value.endswith(suffix):
        raise ValueError("package PATH is not controlled")
    prefix = path_value[:-len(suffix)]
    root = Path(prefix)
    if not prefix or not root.is_absolute():
        raise ValueError("package PATH does not name an absolute post-build root")
    return root


def _validate_environment_receipt(
    environment: object,
    *,
    source_date_epoch: int,
    control_root: Path | None,
) -> tuple[dict[str, str], Path]:
    if not isinstance(environment, dict) or set(environment) != ENV_KEYS or not all(isinstance(key, str) and isinstance(value, str) for key, value in environment.items()):
        raise ValueError("native environment projection is not closed")
    post_root = _infer_post_root(environment)
    if (environment["LANG"], environment["LC_ALL"], environment["TZ"], environment["SOURCE_DATE_EPOCH"]) != ("C", "C", "UTC", str(source_date_epoch)):
        raise ValueError("native environment differs from build provenance")
    if control_root is not None:
        validate_package_environment(environment, control_root, source_date_epoch=source_date_epoch, post_root=post_root)
    else:
        home = Path(environment["HOME"])
        temporary = Path(environment["TMPDIR"])
        if not home.is_absolute() or not temporary.is_absolute() or home.name != "home" or temporary.name != "tmp" or home.parent != temporary.parent:
            raise ValueError("native control paths are not a closed run-root pair")
    return dict(environment), post_root


def _validate_native_commands(
    commands: object,
    *,
    packaging_lock: dict[str, object],
    post_root: Path,
    rehash_tools: bool,
) -> tuple[list[dict[str, object]], dict[str, dict[str, object]]]:
    tools = resolve_locked_package_tools(packaging_lock, post_root=post_root) if rehash_tools else {}
    pins = packaging_lock.get("tools")
    if not isinstance(pins, dict):
        raise ValueError("packaging tool authority is missing")
    if not isinstance(commands, list) or len(commands) != 2:
        raise ValueError("native command receipt must contain exactly two records")
    expected = (
        ("isdDownload", [str(post_root / str(pins["isdDownload"]["installRelativePath"])), *ISD_ARGUMENTS]),
        ("ufwMaker", [str(post_root / str(pins["ufwMaker"]["installRelativePath"])), *UFW_ARGUMENTS]),
    )
    result: list[dict[str, object]] = []
    for record, (role, argv) in zip(commands, expected):
        pin = pins[role]
        if not isinstance(record, dict) or set(record) != NATIVE_COMMAND_KEYS:
            raise ValueError("native command record projection is not closed")
        if (
            record.get("argv") != argv
            or record.get("exitCode") != 0
            or record.get("role") != role
            or record.get("toolSha256") != pin.get("sha256")
            or record.get("toolVersion") != pin.get("version")
        ):
            raise ValueError(f"native command identity mismatch: {role}")
        for key in ("stderrSha256", "stdoutSha256", "toolSha256"):
            if not isinstance(record.get(key), str) or HEX64.fullmatch(record[key]) is None:
                raise ValueError("native command digest is invalid")
        for stream in ("stdout", "stderr"):
            raw_hex = record.get(f"{stream}Hex")
            raw_size = record.get(f"{stream}Size")
            if not isinstance(raw_hex, str) or re.fullmatch(r"(?:[0-9A-F]{2})*", raw_hex) is None:
                raise ValueError(f"native command {stream} hex is invalid")
            raw = bytes.fromhex(raw_hex)
            if not isinstance(raw_size, int) or isinstance(raw_size, bool) or raw_size < 0 or raw_size != len(raw):
                raise ValueError(f"native command {stream} size is invalid")
            if record[f"{stream}Sha256"] != _sha(raw):
                raise ValueError(f"native command {stream} digest mismatch")
        reject_dangerous_argv(list(record["argv"]))
        result.append(copy.deepcopy(record))
    return result, tools


def _native_command_summaries(commands: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {key: copy.deepcopy(record[key]) for key in NATIVE_COMMAND_SUMMARY_KEYS}
        for record in commands
    ]


def _read_execution_receipt(
    path: Path,
    *,
    packaging_lock: dict[str, object],
    source_date_epoch: int,
    control_root: Path | None,
    rehash_tools: bool = True,
) -> tuple[dict[str, object], bytes, dict[str, dict[str, object]], Path]:
    value, raw = _load_canonical_json(path)
    if set(value) != {"commands", "environment", "inputs", "schema"} or value.get("schema") != "e87-stage0-native-execution-v1":
        raise ValueError("native execution receipt projection is not closed")
    environment, post_root = _validate_environment_receipt(value.get("environment"), source_date_epoch=source_date_epoch, control_root=control_root)
    commands, tools = _validate_native_commands(value.get("commands"), packaging_lock=packaging_lock, post_root=post_root, rehash_tools=rehash_tools)
    inputs = value.get("inputs")
    projection = _snapshot_expected_inputs(inputs)
    if [record["filename"] for record in inputs] != sorted(STAGING_NAMES):
        raise ValueError("native input receipt order is not canonical")
    value = {"commands": commands, "environment": environment, "inputs": copy.deepcopy(inputs), "schema": value["schema"]}
    if set(projection) != STAGING_NAMES:
        raise ValueError("native input receipt is incomplete")
    return value, raw, tools, post_root


def _expected_artifact_names(source_commit: str) -> tuple[set[str], str]:
    if not isinstance(source_commit, str) or SOURCE40.fullmatch(source_commit) is None:
        raise ValueError("invalid package source identity")
    qix_name = f"E87-{QIX_VERSION}-{source_commit[:8].upper()}.qix"
    return {"app.bin", "jl_isd.bin", "jl_isd.fw", "update.ufw", "independently-made.ufw", qix_name}, qix_name


def _read_artifacts(
    artifacts: object,
    *,
    expected_names: set[str],
) -> tuple[dict[str, bytes], dict[str, tuple[object, ...]]]:
    if not isinstance(artifacts, dict) or set(artifacts) != expected_names:
        raise ValueError("package artifact projection is not closed")
    data: dict[str, bytes] = {}
    tokens: dict[str, tuple[object, ...]] = {}
    resolved: set[str] = set()
    for name in sorted(expected_names):
        path = Path(artifacts[name])
        if not path.is_absolute():
            raise ValueError("package artifact path must be absolute")
        raw = _regular_bytes(path)
        if not raw:
            raise ValueError(f"package artifact is empty: {name}")
        identity = str(path.resolve(strict=True))
        if identity in resolved:
            raise ValueError("package artifacts must be distinct files")
        resolved.add(identity)
        data[name] = raw
        tokens[identity] = _path_token(path)
    return data, tokens


def _reverify_tokens(tokens: dict[str, tuple[object, ...]]) -> None:
    for raw_path, expected in tokens.items():
        if _path_token(Path(raw_path)) != expected:
            raise ValueError(f"bound package input changed during use window: {raw_path}")


def _build_identities(
    *,
    build_receipt: dict[str, object],
    lock_values: dict[str, dict[str, object]],
    lock_hashes: dict[str, str],
    native_commands: list[dict[str, object]],
) -> dict[str, object]:
    bootstrap = build_receipt["bootstrap"]
    overlay = bootstrap["overlay"]
    board_records = [record for record in overlay if str(record.get("destination", "")).endswith("board_e87_1542_cfg.h")]
    if len(board_records) != 1:
        raise ValueError("bootstrap receipt has no unique Stage0 board profile")
    model_lock = lock_values["model1552-package.lock.json"]
    packaging_lock = lock_values["packaging.lock.json"]
    toolchain_lock = lock_values["toolchain.lock.json"]
    tools = {name: toolchain_lock["tools"][name]["sha256"] for name in PRIMARY_BUILD_TOOLS}
    tools.update({
        "git": bootstrap["gitTool"]["sha256"],
        "make": build_receipt["commands"][0]["toolSha256"],
        "isdDownload": native_commands[0]["toolSha256"],
        "ufwMaker": native_commands[1]["toolSha256"],
    })
    identities = {
        "archives": {
            "packaging": packaging_lock["archive"]["sha256"],
            "toolchain": toolchain_lock["archive"]["sha256"],
        },
        "boardProfileSha256": board_records[0]["sha256"],
        "bootstrapReceiptSha256": build_receipt["bootstrapReceipt"]["sha256"],
        "locks": dict(lock_hashes),
        "overlayTreeSha256": _projection_sha256(overlay),
        "patchSha256": bootstrap["patch"]["sha256"],
        "referenceManifestSha256": model_lock["referenceFiles"]["manifest.json"]["sha256"],
        "sdk": {"commit": bootstrap["sdkCommit"], "tree": bootstrap["sdkTree"]},
        "sourceCommitObjectSha256": bootstrap["sourceCommitObjectSha256"],
        "sourceTree": bootstrap["sourceTree"],
        "tools": tools,
    }
    if set(identities) != {"archives", "boardProfileSha256", "bootstrapReceiptSha256", "locks", "overlayTreeSha256", "patchSha256", "referenceManifestSha256", "sdk", "sourceCommitObjectSha256", "sourceTree", "tools"}:
        raise ValueError("package identity projection is not closed")
    for digest in (
        identities["boardProfileSha256"], identities["bootstrapReceiptSha256"], identities["overlayTreeSha256"],
        identities["patchSha256"], identities["referenceManifestSha256"], identities["sourceCommitObjectSha256"],
        *identities["archives"].values(), *identities["locks"].values(), *identities["tools"].values(),
    ):
        if not isinstance(digest, str) or HEX64.fullmatch(digest) is None:
            raise ValueError("invalid package identity digest")
    return identities


def _assemble_package_evidence_impl(
    *,
    artifacts: dict[str, Path],
    build_receipt_path: Path,
    control_root: Path | None,
    execution_receipt_path: Path,
    lock_root: Path,
    validation_receipt_path: Path,
    require_live_control: bool,
) -> dict[str, object]:
    lock_values, lock_hashes, lock_tokens = _load_locks(lock_root)
    toolchain_lock = lock_values["toolchain.lock.json"]
    build_receipt, build_raw = _read_build_receipt(build_receipt_path, toolchain_lock=toolchain_lock)
    bootstrap_path = Path(build_receipt_path).with_name(str(build_receipt["bootstrapReceipt"]["filename"]))
    if bootstrap_path.exists() or bootstrap_path.is_symlink():
        if _regular_bytes(bootstrap_path) != _canonical(build_receipt["bootstrap"]):
            raise ValueError("standalone bootstrap receipt differs from build receipt")
    execution, _, _, _ = _read_execution_receipt(
        execution_receipt_path,
        packaging_lock=lock_values["packaging.lock.json"],
        source_date_epoch=build_receipt["sourceDateEpoch"],
        control_root=control_root if require_live_control else None,
    )
    expected_names, qix_name = _expected_artifact_names(build_receipt["sourceCommit"])
    artifact_data, artifact_tokens = _read_artifacts(artifacts, expected_names=expected_names)
    input_projection = _snapshot_expected_inputs(execution["inputs"])
    if input_projection["app.bin"] != (build_receipt["app"]["size"], build_receipt["app"]["sha256"]):
        raise ValueError("native input app differs from build receipt")
    if (len(artifact_data["app.bin"]), _sha(artifact_data["app.bin"])) != input_projection["app.bin"]:
        raise ValueError("packaged app differs from native input receipt")
    expected_validations = _derive_package_proofs(
        artifact_data,
        app_record=build_receipt["app"],
        expected_source_commit=build_receipt["sourceCommit"],
        staged_ini_sha256=input_projection["isd_config.ini"][1],
        qix_name=qix_name,
        qix_version=lock_values["packaging.lock.json"]["qix"]["version"],
    )
    validation, _ = _load_canonical_json(validation_receipt_path)
    if set(validation) != {"schema", "validations"} or validation.get("schema") != "e87-stage0-package-validation-v1" or validation.get("validations") != expected_validations:
        raise ValueError("package validation receipt is not independently derived")
    identities = _build_identities(
        build_receipt=build_receipt,
        lock_values=lock_values,
        lock_hashes=lock_hashes,
        native_commands=execution["commands"],
    )
    command_summaries = _native_command_summaries(execution["commands"])
    normalized_environment = dict(execution["environment"])
    normalized_environment["HOME"] = "$RUN_ROOT/control/home"
    normalized_environment["TMPDIR"] = "$RUN_ROOT/control/tmp"
    outputs = [
        {"filename": name, "sha256": _sha(artifact_data[name]), "size": len(artifact_data[name])}
        for name in sorted(expected_names)
    ]
    evidence = {
        "app": copy.deepcopy(build_receipt["app"]),
        "buildReceiptSha256": _sha(build_raw),
        "buildTag": build_receipt["sourceCommit"][:8].upper(),
        "commands": command_summaries,
        "environment": normalized_environment,
        "identities": identities,
        "inputs": copy.deepcopy(execution["inputs"]),
        "locks": dict(lock_hashes),
        "outputs": outputs,
        "qix": copy.deepcopy(expected_validations["qix"]),
        "resetPolicy": copy.deepcopy(expected_validations["resetPolicy"]),
        "schema": "e87-stage0-package-evidence-v1",
        "sourceCommit": build_receipt["sourceCommit"],
        "sourceDateEpoch": build_receipt["sourceDateEpoch"],
        "target": copy.deepcopy(build_receipt["target"]),
        "validations": expected_validations,
    }
    if set(evidence) != PACKAGE_EVIDENCE_KEYS:
        raise ValueError("package evidence projection is not closed")
    _reverify_tokens({**lock_tokens, **artifact_tokens})
    return evidence


def assemble_package_evidence(
    *,
    artifacts: dict[str, Path],
    build_receipt_path: Path,
    control_root: Path,
    execution_receipt_path: Path,
    lock_root: Path,
    validation_receipt_path: Path,
) -> dict[str, object]:
    return _assemble_package_evidence_impl(
        artifacts=artifacts,
        build_receipt_path=build_receipt_path,
        control_root=control_root,
        execution_receipt_path=execution_receipt_path,
        lock_root=lock_root,
        validation_receipt_path=validation_receipt_path,
        require_live_control=True,
    )


def _artifact_paths(delivery_root: Path, evidence_root: Path, source_commit: str) -> tuple[dict[str, Path], str]:
    names, qix_name = _expected_artifact_names(source_commit)
    delivery = Path(delivery_root)
    evidence = Path(evidence_root)
    paths = {
        "app.bin": delivery / "app.bin",
        "jl_isd.fw": delivery / "jl_isd.fw",
        "update.ufw": delivery / "update.ufw",
        qix_name: delivery / qix_name,
        "jl_isd.bin": evidence / "jl_isd.bin",
        "independently-made.ufw": evidence / "independently-made.ufw",
    }
    if set(paths) != names:
        raise ValueError("internal artifact path projection is incomplete")
    return paths, qix_name


def _derive_path_evidence(
    delivery_root: Path,
    evidence_root: Path,
    *,
    build_receipt_path: Path,
    execution_receipt_path: Path,
    lock_root: Path,
    validation_receipt_path: Path,
) -> tuple[dict[str, object], str]:
    lock_values, _, _ = _load_locks(lock_root)
    build_receipt, _ = _read_build_receipt(build_receipt_path, toolchain_lock=lock_values["toolchain.lock.json"])
    artifacts, qix_name = _artifact_paths(delivery_root, evidence_root, build_receipt["sourceCommit"])
    evidence = _assemble_package_evidence_impl(
        artifacts=artifacts,
        build_receipt_path=build_receipt_path,
        control_root=None,
        execution_receipt_path=execution_receipt_path,
        lock_root=lock_root,
        validation_receipt_path=validation_receipt_path,
        require_live_control=False,
    )
    return evidence, qix_name


def build_manifest(
    delivery_root: Path,
    evidence_root: Path,
    *,
    build_receipt_path: Path,
    execution_receipt_path: Path,
    lock_root: Path,
    package_evidence_path: Path,
    validation_receipt_path: Path,
) -> dict[str, object]:
    evidence, qix_name = _derive_path_evidence(
        delivery_root,
        evidence_root,
        build_receipt_path=build_receipt_path,
        execution_receipt_path=execution_receipt_path,
        lock_root=lock_root,
        validation_receipt_path=validation_receipt_path,
    )
    on_disk_evidence, _ = _load_canonical_json(package_evidence_path)
    if on_disk_evidence != evidence:
        raise ValueError("package evidence no longer matches its authoritative sources")
    validations = evidence["validations"]
    app_sha = evidence["app"]["sha256"]
    delivered = [
        ("app.bin", "REVIEWED_APP", {"kind": "APP_BIN", "sha256": app_sha}),
        ("jl_isd.fw", "BR35_MASKROM_CANDIDATE", {"embeddedAppSha256": app_sha, "kind": "JL_ISD_FW", "flashSha256": validations["jlfw"]["flashSha256"]}),
        ("update.ufw", "OTA_UFW", {"kind": "UFW_V4", "itemCount": validations["ufw"]["native"]["itemCount"]}),
        (qix_name, "OTA_QIX", {"kind": "QIX", "unwrappedPayloadSha256": validations["qix"]["unwrappedPayloadSha256"], "version": validations["qix"]["version"]}),
    ]
    intermediate = [
        ("jl_isd.bin", "NEW_FIRMWARE_INTERMEDIATE", {"embeddedAppSha256": app_sha, "kind": "JL_NEW_FW", "flashSha256": validations["jlfw"]["flashSha256"]}),
        ("independently-made.ufw", "INDEPENDENT_UFW_CHECK", {"kind": "UFW_V4_BYTE_IDENTICAL", "sha256": validations["ufw"]["independent"]["sha256"]}),
    ]
    delivery = Path(delivery_root)
    evidence_root = Path(evidence_root)
    outputs = [_output_record(delivery / name, role, True, proof) for name, role, proof in delivered]
    outputs.extend(_output_record(evidence_root / name, role, False, proof) for name, role, proof in intermediate)
    outputs.sort(key=lambda record: record["filename"])
    return {
        "buildTag": evidence["buildTag"],
        "features": {"bleHeartbeat": True, "buttons": False, "charging": False, "display": False, "gatt": False, "maintenance": False, "sleep": False},
        "identities": copy.deepcopy(evidence["identities"]),
        "labEligible": False,
        "nativeCommands": copy.deepcopy(evidence["commands"]),
        "outputs": outputs,
        "qix": copy.deepcopy(evidence["qix"]),
        "recovery": {"evidence": None, "kind": "BR35_MASKROM_EXTERNAL", "requiresPreWriteProof": True},
        "releaseEligible": False,
        "resetPolicy": copy.deepcopy(evidence["resetPolicy"]),
        "schema": "e87-stage0-manifest-v1",
        "sourceCommit": evidence["sourceCommit"],
        "target": copy.deepcopy(evidence["target"]),
        "writeOnlyWaiver": "SKIPPED_WITH_REASON: WRITE_ONLY_CONFIRMED",
    }


def stable_output_snapshot(root: Path, expected_names: set[str]) -> dict[str, tuple[int, str]]:
    directory = _validate_real_root(root, "output root")
    if not isinstance(expected_names, set) or not expected_names or not all(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9._-]+", name) for name in expected_names):
        raise ValueError("output allowlist is invalid")
    snapshot = _snapshot(directory)
    if set(snapshot) != expected_names or any(size <= 0 for size, _ in snapshot.values()):
        raise ValueError("output tree does not match the exact allowlist")
    return snapshot


def write_delivery_metadata(
    delivery_root: Path,
    manifest: dict[str, object],
    *,
    expected_snapshot: dict[str, tuple[int, str]],
    before_commit=None,
) -> None:
    root = _validate_real_root(delivery_root, "delivery root")
    tag = manifest.get("buildTag") if isinstance(manifest, dict) else None
    if not isinstance(tag, str) or re.fullmatch(r"[0-9A-F]{8}", tag) is None:
        raise ValueError("manifest build tag is invalid")
    qix_name = f"E87-{QIX_VERSION}-{tag}.qix"
    expected_names = {"app.bin", "jl_isd.fw", "update.ufw", qix_name}
    if set(expected_snapshot) != expected_names or stable_output_snapshot(root, expected_names) != expected_snapshot:
        raise ValueError("delivery outputs changed before metadata staging")
    initial_tokens = {name: _path_token(root / name) for name in expected_names}
    output_records = manifest.get("outputs")
    if not isinstance(output_records, list):
        raise ValueError("manifest output projection is missing")
    delivered_records = {record.get("filename"): record for record in output_records if isinstance(record, dict) and record.get("delivered") is True}
    if set(delivered_records) != expected_names:
        raise ValueError("manifest delivered-output projection is not closed")
    for name, (size, digest) in expected_snapshot.items():
        record = delivered_records[name]
        if record.get("size") != size or record.get("sha256") != digest:
            raise ValueError("manifest output identity differs from delivery bytes")
    manifest_data = _canonical(manifest)
    manifest_temp = root / ".manifest.json.stage"
    sums_temp = root / ".SHA256SUMS.stage"
    manifest_path = root / "manifest.json"
    sums_path = root / "SHA256SUMS"
    for path in (manifest_temp, sums_temp, manifest_path, sums_path):
        if path.exists() or path.is_symlink():
            raise ValueError("delivery metadata path already exists")
    lines = []
    for name in sorted(expected_names | {"manifest.json"}):
        digest = _sha(manifest_data) if name == "manifest.json" else expected_snapshot[name][1]
        lines.append(f"{digest}  {name}\n")
    sums_data = "".join(lines).encode("ascii")
    committed: list[Path] = []
    try:
        _write_new(manifest_temp, manifest_data)
        _write_new(sums_temp, sums_data)
        if before_commit is not None:
            if not callable(before_commit):
                raise TypeError("before_commit must be callable")
            before_commit()
        if stable_output_snapshot(root, expected_names | {manifest_temp.name, sums_temp.name}) != {
            **expected_snapshot,
            manifest_temp.name: (len(manifest_data), _sha(manifest_data)),
            sums_temp.name: (len(sums_data), _sha(sums_data)),
        }:
            raise ValueError("delivery metadata staging changed")
        for name, token in initial_tokens.items():
            if _path_token(root / name) != token:
                raise ValueError("delivery output changed during metadata use window")
        os.replace(manifest_temp, manifest_path)
        committed.append(manifest_path)
        os.replace(sums_temp, sums_path)
        committed.append(sums_path)
    except BaseException:
        for path in (manifest_temp, sums_temp, *reversed(committed)):
            try:
                if path.is_symlink() or path.is_file():
                    path.unlink()
            except OSError:
                pass
        raise


def validate_delivery_allowlist(delivery_root: Path, qix_name: str) -> None:
    root = _validate_real_root(delivery_root, "delivery root")
    if not isinstance(qix_name, str) or re.fullmatch(r"E87-11\.1\.0\.3-[0-9A-F]{8}\.qix", qix_name) is None:
        raise ValueError("delivery Qix name is invalid")
    expected = {"app.bin", "jl_isd.fw", "update.ufw", qix_name, "manifest.json", "SHA256SUMS"}
    actual = set()
    for path in root.iterdir():
        if path.is_symlink() or not path.is_file(): raise ValueError("non-regular delivery entry")
        if path.stat().st_size <= 0: raise ValueError("empty delivery entry")
        actual.add(path.name)
    if actual != expected: raise ValueError("delivery allowlist mismatch")


def _validate_delivery_metadata(delivery_root: Path, *, qix_name: str, expected_manifest: dict[str, object]) -> None:
    delivery = Path(delivery_root)
    validate_delivery_allowlist(delivery, qix_name)
    manifest, manifest_raw = _load_canonical_json(delivery / "manifest.json")
    if manifest != expected_manifest:
        raise ValueError("on-disk manifest differs from derived manifest")
    try:
        sums_raw = _regular_bytes(delivery / "SHA256SUMS")
        sums_text = sums_raw.decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError("SHA256SUMS is not ASCII") from error
    names = sorted({"app.bin", "jl_isd.fw", "update.ufw", qix_name, "manifest.json"})
    expected_lines = []
    for name in names:
        data = manifest_raw if name == "manifest.json" else _regular_bytes(delivery / name)
        expected_lines.append(f"{_sha(data)}  {name}\n")
    if sums_text != "".join(expected_lines):
        raise ValueError("SHA256SUMS does not bind the exact delivery allowlist")


def build_package_receipt(
    *,
    build_receipt_path: Path,
    execution_receipt_path: Path,
    lock_root: Path,
    package_evidence_path: Path,
    validation_receipt_path: Path,
    delivery_root: Path,
    evidence_root: Path,
) -> dict[str, object]:
    evidence, qix_name = _derive_path_evidence(
        delivery_root,
        evidence_root,
        build_receipt_path=build_receipt_path,
        execution_receipt_path=execution_receipt_path,
        lock_root=lock_root,
        validation_receipt_path=validation_receipt_path,
    )
    on_disk_evidence, _ = _load_canonical_json(package_evidence_path)
    if on_disk_evidence != evidence:
        raise ValueError("package evidence differs from authoritative package sources")
    manifest = build_manifest(
        delivery_root,
        evidence_root,
        build_receipt_path=build_receipt_path,
        execution_receipt_path=execution_receipt_path,
        lock_root=lock_root,
        package_evidence_path=package_evidence_path,
        validation_receipt_path=validation_receipt_path,
    )
    _validate_delivery_metadata(delivery_root, qix_name=qix_name, expected_manifest=manifest)
    receipt = copy.deepcopy(evidence)
    receipt["schema"] = "e87-stage0-package-receipt-v1"
    return receipt


def _compare_roots(first: Path, second: Path) -> None:
    left_root = _validate_real_root(first, "first comparison root")
    right_root = _validate_real_root(second, "second comparison root")
    if left_root == right_root:
        raise ValueError("reproducibility roots must be distinct")
    left = _snapshot(left_root); right = _snapshot(right_root)
    if not left or not right:
        raise ValueError("reproducibility roots must be complete and nonempty")
    if left != right: raise ValueError("reproducibility mismatch")


def assert_deterministic_delivery(first: Path, second: Path) -> None:
    _compare_roots(Path(first), Path(second))


def assert_deterministic_package(first_delivery: Path, first_evidence: Path, second_delivery: Path, second_evidence: Path) -> None:
    paths = [Path(first_delivery), Path(first_evidence), Path(second_delivery), Path(second_evidence)]
    resolved = [_validate_real_root(path, "package reproducibility root") for path in paths]
    if len(set(resolved)) != 4:
        raise ValueError("package reproducibility roots must be four distinct directories")
    if paths[0].name != "delivery" or paths[1].name != "evidence" or paths[2].name != "delivery" or paths[3].name != "evidence":
        raise ValueError("package reproducibility roots are not complete run projections")
    if paths[0].parent.resolve() != paths[1].parent.resolve() or paths[2].parent.resolve() != paths[3].parent.resolve():
        raise ValueError("delivery and evidence roots do not share their run roots")
    assert_reproducible_runs(first_run_root=paths[0].parent, second_run_root=paths[2].parent)


def validate_complete_run(run_root: Path) -> dict[str, object]:
    run = _validate_real_root(run_root, "complete run root")
    entries = list(run.iterdir())
    if {entry.name for entry in entries} != {"delivery", "evidence"} or any(entry.is_symlink() or not entry.is_dir() for entry in entries):
        raise ValueError("complete run must contain only delivery and evidence directories")
    delivery = _validate_real_root(run / "delivery", "complete delivery root")
    evidence_root = _validate_real_root(run / "evidence", "complete evidence root")
    evidence_names = {"build-receipt.json", "independently-made.ufw", "jl_isd.bin", "native-execution.json", "package-evidence.json", "package-receipt.json", "validation.json"}
    if {path.name for path in evidence_root.iterdir()} != evidence_names or any(path.is_symlink() or not path.is_file() or path.stat().st_size <= 0 for path in evidence_root.iterdir()):
        raise ValueError("complete evidence projection is not closed")
    repository_root = Path(__file__).resolve().parents[2]
    lock_root = repository_root / "firmware/locks"
    expected_evidence, qix_name = _derive_path_evidence(
        delivery,
        evidence_root,
        build_receipt_path=evidence_root / "build-receipt.json",
        execution_receipt_path=evidence_root / "native-execution.json",
        lock_root=lock_root,
        validation_receipt_path=evidence_root / "validation.json",
    )
    package_evidence, _ = _load_canonical_json(evidence_root / "package-evidence.json")
    if package_evidence != expected_evidence:
        raise ValueError("complete package evidence cross-hash mismatch")
    package_receipt, package_receipt_raw = _load_canonical_json(evidence_root / "package-receipt.json")
    expected_receipt = {**copy.deepcopy(expected_evidence), "schema": "e87-stage0-package-receipt-v1"}
    if package_receipt != expected_receipt:
        raise ValueError("complete package receipt cross-hash mismatch")
    expected_manifest = build_manifest(
        delivery,
        evidence_root,
        build_receipt_path=evidence_root / "build-receipt.json",
        execution_receipt_path=evidence_root / "native-execution.json",
        lock_root=lock_root,
        package_evidence_path=evidence_root / "package-evidence.json",
        validation_receipt_path=evidence_root / "validation.json",
    )
    _validate_delivery_metadata(delivery, qix_name=qix_name, expected_manifest=expected_manifest)
    build_raw = _regular_bytes(evidence_root / "build-receipt.json")
    return {
        "buildReceiptSha256": _sha(build_raw),
        "delivery": _snapshot(delivery),
        "evidence": _snapshot(evidence_root),
        "packageReceiptSha256": _sha(package_receipt_raw),
    }


def _replace_roots(value: object, substitutions: list[tuple[str, str]]) -> object:
    if isinstance(value, str):
        result = value
        for root, token in sorted(substitutions, key=lambda item: len(item[0]), reverse=True):
            result = result.replace(root, token)
        return result
    if isinstance(value, list):
        return [_replace_roots(item, substitutions) for item in value]
    if isinstance(value, dict):
        return {key: _replace_roots(item, substitutions) for key, item in value.items()}
    return value


def _run_semantic_roots(run_root: Path) -> tuple[Path, Path]:
    build_receipt, _ = _load_canonical_json(Path(run_root) / "evidence/build-receipt.json")
    commands = build_receipt.get("commands")
    if not isinstance(commands, list) or len(commands) != 11:
        raise ValueError("build receipt has no semantic root authority")
    make_argv = commands[0].get("argv") if isinstance(commands[0], dict) else None
    objcopy_argv = commands[1].get("argv") if isinstance(commands[1], dict) else None
    if not isinstance(make_argv, list) or len(make_argv) < 3 or not isinstance(objcopy_argv, list) or not objcopy_argv:
        raise ValueError("build receipt root commands are malformed")
    generated = Path(make_argv[2]).parent
    build = Path(objcopy_argv[-1]).parent
    if not generated.is_absolute() or not build.is_absolute() or generated == build:
        raise ValueError("build receipt semantic roots are invalid")
    return build.resolve(strict=True), generated.resolve(strict=True)


def assert_reproducible_runs(first_run_root: Path, second_run_root: Path) -> dict[str, object]:
    first = _validate_real_root(first_run_root, "first run root")
    second = _validate_real_root(second_run_root, "second run root")
    if first == second:
        raise ValueError("reproducibility requires two distinct run roots")
    first_proof = validate_complete_run(first)
    second_proof = validate_complete_run(second)
    if first_proof["delivery"] != second_proof["delivery"]:
        raise ValueError("delivery reproducibility mismatch")
    first_build, first_generated = _run_semantic_roots(first)
    second_build, second_generated = _run_semantic_roots(second)
    if first_build == second_build or first_generated == second_generated:
        raise ValueError("reproducibility requires distinct build and generated SDK roots")
    root_substitutions = [
        {"first": str(first_build), "second": str(second_build), "token": "$BUILD_ROOT"},
        {"first": str(first_generated), "second": str(second_generated), "token": "$GENERATED_SDK_ROOT"},
        {"first": str(first), "second": str(second), "token": "$RUN_ROOT"},
    ]
    first_replacements = [(item["first"], item["token"]) for item in root_substitutions]
    second_replacements = [(item["second"], item["token"]) for item in root_substitutions]
    for filename in ("jl_isd.bin", "independently-made.ufw"):
        if _regular_bytes(first / "evidence" / filename) != _regular_bytes(second / "evidence" / filename):
            raise ValueError(f"semantic reproducibility mismatch: {filename}")
    for filename in ("build-receipt.json", "native-execution.json", "validation.json", "package-evidence.json", "package-receipt.json"):
        left, _ = _load_canonical_json(first / "evidence" / filename)
        right, _ = _load_canonical_json(second / "evidence" / filename)
        left = _replace_roots(left, first_replacements)
        right = _replace_roots(right, second_replacements)
        if filename in {"package-evidence.json", "package-receipt.json"}:
            left["buildReceiptSha256"] = "$BUILD_RECEIPT_SHA256"
            right["buildReceiptSha256"] = "$BUILD_RECEIPT_SHA256"
        if left != right:
            raise ValueError(f"semantic command reproducibility mismatch: {filename}")
    return {"relation": "BYTE_IDENTICAL", "rootSubstitutions": root_substitutions}


def _collect_package_use_window_tokens(
    *,
    build_root: Path,
    generated_sdk_root: Path,
    lock_root: Path,
    lock_tokens: dict[str, tuple[object, ...]],
    model_lock: dict[str, object],
    reference_root: Path,
    sdk_root: Path,
    tools: dict[str, dict[str, object]],
    build_receipt: dict[str, object],
) -> dict[str, tuple[object, ...]]:
    paths: list[Path] = []
    paths.extend(Path(reference_root) / relative for relative in model_lock["referenceFiles"])
    paths.append(Path(sdk_root) / str(model_lock["sdkLoader"]["sdkRelativePath"]))
    paths.extend(Path(str(tools[name]["path"])) for name in ("isdDownload", "ufwMaker"))
    paths.extend((
        Path(build_root) / "build-receipt.json",
        Path(build_root) / str(build_receipt["bootstrapReceipt"]["filename"]),
        Path(build_root) / str(build_receipt["app"]["filename"]),
        Path(build_root) / str(build_receipt["elf"]["filename"]),
        Path(generated_sdk_root) / "SDK/cpu/br35/tools/sdk.elf",
        Path(generated_sdk_root) / "SDK/cpu/br35/tools/sdk.map",
    ))
    paths.extend(Path(build_root) / str(record["filename"]) for record in build_receipt["sectionOutputs"])
    paths.extend(Path(generated_sdk_root) / str(record["destination"]) for record in build_receipt["bootstrap"]["overlay"])
    paths.extend(Path(generated_sdk_root) / str(relative) for relative in build_receipt["bootstrap"]["patch"]["paths"])
    paths.extend(Path(generated_sdk_root) / str(record["relativePath"]) for record in build_receipt["buildProvenance"].values())
    paths.extend(Path(generated_sdk_root) / "SDK/build" / relative for relative in build_receipt["sourceObjects"])
    tokens = dict(lock_tokens)
    for path in paths:
        tokens[str(path.resolve(strict=False))] = _path_token(path)
    for filename in LOCK_FILENAMES:
        lock_path = Path(lock_root) / filename
        tokens[str(lock_path.resolve(strict=False))] = _path_token(lock_path)
    return tokens


def _inode_identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return metadata.st_dev, metadata.st_ino, stat.S_IFMT(metadata.st_mode)


def _parent_generation(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (*_inode_identity(metadata), metadata.st_mtime_ns, metadata.st_ctime_ns)


def _open_package_workspace_guard(run_root: Path) -> dict[str, object]:
    root = Path(run_root)
    parent = root.parent
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    parent_fd = os.open(parent, flags)
    try:
        root_fd = os.open(root.name, flags, dir_fd=parent_fd)
    except BaseException:
        os.close(parent_fd)
        raise
    try:
        parent_open = os.fstat(parent_fd)
        root_open = os.fstat(root_fd)
        parent_path = os.stat(parent, follow_symlinks=False)
        root_path = os.stat(root, follow_symlinks=False)
        if not stat.S_ISDIR(parent_open.st_mode) or not stat.S_ISDIR(root_open.st_mode):
            raise ValueError("package workspace binding is not a directory pair")
        if _inode_identity(parent_open) != _inode_identity(parent_path) or _inode_identity(root_open) != _inode_identity(root_path):
            raise ValueError("package workspace changed while its binding was opened")
        return {
            "parentFd": parent_fd,
            "parentIdentity": _inode_identity(parent_open),
            "parentPath": parent,
            "rootFd": root_fd,
            "rootIdentity": _inode_identity(root_open),
            "rootPath": root,
        }
    except BaseException:
        os.close(root_fd)
        os.close(parent_fd)
        raise


def _package_workspace_ownership_intact(guard: dict[str, object]) -> bool:
    try:
        parent_fd = int(guard["parentFd"])
        root_fd = int(guard["rootFd"])
        parent_open = os.fstat(parent_fd)
        root_open = os.fstat(root_fd)
        parent_path = os.stat(Path(guard["parentPath"]), follow_symlinks=False)
        root_path = os.stat(Path(guard["rootPath"]), follow_symlinks=False)
    except (OSError, TypeError, ValueError):
        return False
    return (
        _inode_identity(parent_open) == guard["parentIdentity"]
        and _inode_identity(parent_path) == guard["parentIdentity"]
        and _inode_identity(root_open) == guard["rootIdentity"]
        and _inode_identity(root_path) == guard["rootIdentity"]
    )


def _package_workspace_generation(guard: dict[str, object]) -> tuple[tuple[int, int, int, int, int], tuple[int, int, int, int, int]]:
    if not _package_workspace_ownership_intact(guard):
        raise ValueError("package workspace root or parent changed during use window")
    return (
        _parent_generation(os.fstat(int(guard["parentFd"]))),
        _parent_generation(os.fstat(int(guard["rootFd"]))),
    )


def _require_package_workspace_generation(
    guard: dict[str, object],
    expected: tuple[tuple[int, int, int, int, int], tuple[int, int, int, int, int]],
) -> None:
    if _package_workspace_generation(guard) != expected:
        raise ValueError("package workspace root or parent was rebound during callback")


def _open_child_directory(parent_fd: int, name: str, expected: os.stat_result) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    child_fd = os.open(name, flags, dir_fd=parent_fd)
    opened = os.fstat(child_fd)
    if _inode_identity(opened) != _inode_identity(expected):
        os.close(child_fd)
        raise ValueError(f"workspace directory changed during cleanup: {name}")
    return child_fd


def _clean_directory_fd(directory_fd: int, *, keep: set[str]) -> None:
    for name in sorted(os.listdir(directory_fd)):
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if name in keep:
            if not stat.S_ISDIR(metadata.st_mode):
                raise ValueError(f"retained workspace entry is not a directory: {name}")
            continue
        if stat.S_ISDIR(metadata.st_mode):
            child_fd = _open_child_directory(directory_fd, name, metadata)
            try:
                _clean_directory_fd(child_fd, keep=set())
                current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if _inode_identity(current) != _inode_identity(os.fstat(child_fd)):
                    raise ValueError(f"workspace directory changed before removal: {name}")
            finally:
                os.close(child_fd)
            os.rmdir(name, dir_fd=directory_fd)
        elif stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if _inode_identity(current) != _inode_identity(metadata):
                raise ValueError(f"workspace entry changed before removal: {name}")
            os.unlink(name, dir_fd=directory_fd)
        else:
            raise ValueError(f"cannot clean special workspace entry: {name}")


def _cleanup_package_workspace(guard: dict[str, object], *, keep_outputs: bool) -> None:
    _clean_directory_fd(int(guard["rootFd"]), keep={"delivery", "evidence"} if keep_outputs else set())


def run_stage0_package(
    *,
    generated_sdk_root: Path,
    build_root: Path,
    reference_root: Path,
    run_root: Path,
    expected_source_commit: str,
    runner=subprocess.run,
    event_sink=None,
    use_window_hook=None,
    lock_root: Path | None = None,
    post_root: Path = DEFAULT_POST_ROOT,
    sdk_root: Path = Path("/home/jethac/.local/share/e87-dev/sdk/e_badge_707_sdk_200"),
) -> dict[str, object]:
    if not callable(runner):
        raise TypeError("native package runner must be callable")
    if event_sink is not None and not callable(event_sink):
        raise TypeError("event sink must be callable")
    if use_window_hook is not None and not callable(use_window_hook):
        raise TypeError("use-window hook must be callable")
    if not isinstance(expected_source_commit, str) or SOURCE40.fullmatch(expected_source_commit) is None:
        raise ValueError("expected source commit must be exact lowercase Git identity")
    repository_root = Path(__file__).resolve().parents[2]
    lock_root = Path(lock_root) if lock_root is not None else repository_root / "firmware/locks"
    protected_roots = (
        repository_root,
        Path(sdk_root),
        Path("/home/jethac/.local/share/e87-dev/jieli"),
        Path(post_root),
        lock_root,
    )
    run = Path(run_root)
    roots: dict[str, Path] | None = None
    workspace_guard: dict[str, object] | None = None
    workspace_owned = False
    success = False

    def emit(event: str) -> None:
        if event_sink is not None:
            generation = _package_workspace_generation(workspace_guard) if workspace_guard is not None else None
            event_sink(event)
            if workspace_guard is not None and event != "workspace:cleaned":
                _require_package_workspace_generation(workspace_guard, generation)

    try:
        roots = validate_package_roots(
            generated_sdk_root=Path(generated_sdk_root),
            build_root=Path(build_root),
            reference_root=Path(reference_root),
            run_root=run,
            protected_roots=protected_roots,
        )
        workspace_guard = _open_package_workspace_guard(roots["run"])
        workspace_owned = True
        emit("roots:validated")
        for name in ("control", "delivery", "evidence", "staging"):
            roots[name].mkdir(mode=0o700)
        lock_values, _, lock_tokens = _load_locks(lock_root)
        emit("locks:reopened")
        build_receipt, build_raw = _read_build_receipt(
            roots["build"] / "build-receipt.json",
            toolchain_lock=lock_values["toolchain.lock.json"],
            expected_source_commit=expected_source_commit,
        )
        emit("build-receipt:reopened")
        build_receipt = _validate_build_authority(
            generated_sdk_root=roots["generatedSdk"],
            build_root=roots["build"],
            bootstrap_receipt_path=roots["build"] / "bootstrap-receipt.json",
            control_root=roots["control"],
            expected_source_commit=expected_source_commit,
            observed_receipt=build_receipt,
            observed_raw=build_raw,
        )
        verify_reference_root(roots["reference"], lock_values["model1552-package.lock.json"])
        emit("reference:reopened")
        tools = resolve_locked_package_tools(lock_values["packaging.lock.json"], post_root=post_root)
        staged = stage_inputs(
            roots["reference"],
            sdk_root,
            roots["build"] / "app.bin",
            roots["staging"],
            lock_values["model1552-package.lock.json"],
            build_receipt=build_receipt,
        )
        expected_inputs = staged["inputs"]
        expected_staging = _snapshot_expected_inputs(expected_inputs)
        emit("inputs:staged")
        environment = package_environment(roots["control"], source_date_epoch=build_receipt["sourceDateEpoch"], post_root=post_root)
        bound_tokens = _collect_package_use_window_tokens(
            build_root=roots["build"],
            generated_sdk_root=roots["generatedSdk"],
            lock_root=lock_root,
            lock_tokens=lock_tokens,
            model_lock=lock_values["model1552-package.lock.json"],
            reference_root=roots["reference"],
            sdk_root=Path(sdk_root),
            tools=tools,
            build_receipt=build_receipt,
        )
        reverify_package_inputs(
            reference_root=roots["reference"],
            sdk_root=Path(sdk_root),
            generated_sdk_root=roots["generatedSdk"],
            build_root=roots["build"],
            staging_root=roots["staging"],
            expected_source_commit=expected_source_commit,
            tools=tools,
            expected_staging=expected_staging,
            model_lock=lock_values["model1552-package.lock.json"],
            toolchain_lock=lock_values["toolchain.lock.json"],
            expected_tokens=bound_tokens,
        )
        commands: list[dict[str, object]] = []

        def boundary(phase: str) -> None:
            if use_window_hook is not None:
                generation = _package_workspace_generation(workspace_guard)
                use_window_hook(phase)
                _require_package_workspace_generation(workspace_guard, generation)
            _reverify_tokens(bound_tokens)

        native_outputs = run_native_packagers(
            roots["staging"],
            tools,
            expected_inputs=expected_inputs,
            control_root=roots["control"],
            environment=environment,
            runner=runner,
            event_sink=emit,
            use_window_hook=boundary,
            command_sink=commands,
            post_root=post_root,
        )
        qix_version = lock_values["packaging.lock.json"]["qix"]["version"]
        if qix_version != QIX_VERSION:
            raise ValueError("packaging lock Qix version drift")
        qix_name = f"E87-{qix_version}-{expected_source_commit[:8].upper()}.qix"
        qix_module = _load_sibling("qix.py", "e87_stage0_package_qix_writer")
        qix_data = qix_module.wrap_qix(_regular_bytes(native_outputs["update.ufw"]), qix_version)
        _write_new(roots["staging"] / qix_name, qix_data)
        output_tokens = {
            str(path.resolve(strict=False)): _path_token(path)
            for path in (*native_outputs.values(), roots["staging"] / qix_name)
        }
        if use_window_hook is not None:
            generation = _package_workspace_generation(workspace_guard)
            use_window_hook("before-validation")
            _require_package_workspace_generation(workspace_guard, generation)
        _reverify_tokens({**bound_tokens, **output_tokens})
        qix_event_sent = False

        def proof_event(event: str) -> None:
            nonlocal qix_event_sent
            if event == "proof:qix" and not qix_event_sent:
                emit("qix:wrapped")
                qix_event_sent = True
            emit(event)

        validations = validate_package_outputs(
            roots["staging"],
            app_record=build_receipt["app"],
            expected_source_commit=expected_source_commit,
            staged_ini_sha256=expected_staging["isd_config.ini"][1],
            qix_name=qix_name,
            qix_version=qix_version,
            event_sink=proof_event,
        )
        _reverify_tokens({**bound_tokens, **output_tokens})
        execution = {"commands": commands, "environment": environment, "inputs": expected_inputs, "schema": "e87-stage0-native-execution-v1"}
        validation = {"schema": "e87-stage0-package-validation-v1", "validations": validations}
        _write_new(roots["evidence"] / "build-receipt.json", build_raw)
        _write_new(roots["evidence"] / "native-execution.json", _canonical(execution))
        _write_new(roots["evidence"] / "validation.json", _canonical(validation))
        _write_new(roots["evidence"] / "jl_isd.bin", _regular_bytes(native_outputs["jl_isd.bin"]))
        _write_new(roots["evidence"] / "independently-made.ufw", _regular_bytes(native_outputs["independently-made.ufw"]))
        for name in ("app.bin", "jl_isd.fw", "update.ufw", qix_name):
            _write_new(roots["delivery"] / name, _regular_bytes(roots["staging"] / name))
        artifacts, _ = _artifact_paths(roots["delivery"], roots["evidence"], expected_source_commit)
        package_evidence = assemble_package_evidence(
            artifacts=artifacts,
            build_receipt_path=roots["evidence"] / "build-receipt.json",
            control_root=roots["control"],
            execution_receipt_path=roots["evidence"] / "native-execution.json",
            lock_root=lock_root,
            validation_receipt_path=roots["evidence"] / "validation.json",
        )
        _write_new(roots["evidence"] / "package-evidence.json", _canonical(package_evidence))
        emit("evidence:committed")
        manifest = build_manifest(
            roots["delivery"],
            roots["evidence"],
            build_receipt_path=roots["evidence"] / "build-receipt.json",
            execution_receipt_path=roots["evidence"] / "native-execution.json",
            lock_root=lock_root,
            package_evidence_path=roots["evidence"] / "package-evidence.json",
            validation_receipt_path=roots["evidence"] / "validation.json",
        )
        delivery_snapshot = stable_output_snapshot(roots["delivery"], {"app.bin", "jl_isd.fw", "update.ufw", qix_name})
        write_delivery_metadata(roots["delivery"], manifest, expected_snapshot=delivery_snapshot)
        emit("metadata:committed")
        receipt = build_package_receipt(
            build_receipt_path=roots["evidence"] / "build-receipt.json",
            execution_receipt_path=roots["evidence"] / "native-execution.json",
            lock_root=lock_root,
            package_evidence_path=roots["evidence"] / "package-evidence.json",
            validation_receipt_path=roots["evidence"] / "validation.json",
            delivery_root=roots["delivery"],
            evidence_root=roots["evidence"],
        )
        _write_new(roots["evidence"] / "package-receipt.json", _canonical(receipt))
        emit("receipt:committed")
        success = True
        return receipt
    finally:
        if workspace_guard is not None:
            try:
                if workspace_owned and _package_workspace_ownership_intact(workspace_guard):
                    _cleanup_package_workspace(workspace_guard, keep_outputs=success)
            finally:
                os.close(int(workspace_guard["rootFd"]))
                os.close(int(workspace_guard["parentFd"]))
                workspace_guard = None
                emit("workspace:cleaned")


def package_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", allow_abbrev=False)
    run.add_argument("--generated-sdk-root", type=Path, required=True)
    run.add_argument("--build-root", type=Path, required=True)
    run.add_argument("--reference-root", type=Path, required=True)
    run.add_argument("--run-root", type=Path, required=True)
    run.add_argument("--expected-source-commit", type=str, required=True)
    compare = subparsers.add_parser("compare", allow_abbrev=False)
    compare.add_argument("--first-run-root", type=Path, required=True)
    compare.add_argument("--second-run-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = package_parser().parse_args(argv)
    if arguments.command == "compare":
        assert_reproducible_runs(first_run_root=arguments.first_run_root, second_run_root=arguments.second_run_root)
        return 0
    receipt = run_stage0_package(
        generated_sdk_root=arguments.generated_sdk_root,
        build_root=arguments.build_root,
        reference_root=arguments.reference_root,
        run_root=arguments.run_root,
        expected_source_commit=arguments.expected_source_commit,
    )
    receipt_path = arguments.run_root / "evidence/package-receipt.json"
    expected = _canonical(receipt)
    if receipt_path.exists() or receipt_path.is_symlink():
        if _regular_bytes(receipt_path) != expected:
            raise ValueError("orchestrator receipt differs from CLI result")
    else:
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        _write_new(receipt_path, expected)
    return 0


if __name__ == "__main__": raise SystemExit(main())
