#!/usr/bin/env python3
"""Pure command and target-policy helpers for the E87 Stage 0-H build."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import resource
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path


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
REQUIRED_E87_OBJECTS = set(SOURCE_OBJECTS)
FORBIDDEN_FRAGMENTS = (
    "e87_renderer",
    "e87_assets",
    "e87_button_classifier",
    "e87_button_fsm",
    "e87_recovery",
    "board_jl707n_demo",
)
TOOLCHAIN_ROOT = Path("/home/jethac/.local/share/e87-dev/jieli")
POST_ROOT = Path("/home/jethac/.local/share/e87-dev/jieli-post-build")
SDK_ROOT = Path("/home/jethac/.local/share/e87-dev/sdk/e_badge_707_sdk_200")
REFERENCE_ROOT = Path("/home/jethac/.local/share/e87-dev/references/model1552-e87-11.1.0.2")
ROOT = Path(__file__).resolve().parents[2]
TOOLCHAIN_LOCK_SHA256 = "60D72D942FC66E89303FD059AC9904F9167AAB743A21E78AB7230AA6B5B2300D"
LOCK_DIGESTS = {
    "model1552-package.lock.json": "EFD3878979F029C56DA16E863EB89955E22D9B222046211A84AAC7BE1F3BA122",
    "packaging.lock.json": "28E6C1DEF70F894F89FDC7FFB8527F204688888C58EEDC052CD8A36F3AEBC003",
    "toolchain.lock.json": TOOLCHAIN_LOCK_SHA256,
}
BUILD_TOOL_VERSIONS = {
    "make": (b"GNU Make 4.3\n", "GNU Make 4.3"),
    "objcopy": (b"LLVM (http://llvm.org/):\n  LLVM version 4.0.1\n", "LLVM 4.0.1"),
    "objdump": (b"LLVM (http://llvm.org/):\n  LLVM version 4.0.1\n", "LLVM 4.0.1"),
    "nm": (b"GNU nm (GNU Binutils) 2.26.51.20160621\n", "GNU Binutils 2.26.51.20160621"),
}
BUILD_RESOURCE_LIMITS = {"nofileSoft": 8192}
BUILD_VALIDATIONS = {
    name: True
    for name in (
        "appConcatenation", "bootstrapReplay", "buildEnvironment", "buildInputsStable",
        "elfLayout", "mapProvenance", "nofileLimit", "objectInventory", "outputAllowlist",
        "runtimeIdentity", "sectionExtraction", "sourceSelection", "toolIdentity",
    )
}
PRIMARY_BUILD_TOOLS = {"clang", "ld", "nm", "objcopy", "objdump", "objsizedump", "strip"}
RUNTIME_TOOL_NAMES = ("ar", "ld", "linkVersion", "llvmGold", "ltoAr", "ltoWrapper")
FORBIDDEN_WRAPPER_OPTIONS = ("--extra-arguments-from-file", "--output-version-info")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9A-F]{64}\Z")
SDK_COMMIT = "d0167685d032d745d88fe50233302edd46941622"
SDK_TREE = "854734595be49510aca5afb89f5885e8bce6a00f"
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
BOOTSTRAP_VALIDATIONS = {
    name: True
    for name in (
        "archiveInventory", "gitToolIdentity", "outputRoot", "outputTree",
        "overlayInputs", "patchContract", "protectedRoots", "sdkClean",
        "sdkIdentity", "sdkStable", "sourceClean", "sourceIdentity",
        "sourceStable",
    )
}
BOOTSTRAP_COMMAND_ROLES = (
    "git-version",
    "source-before-head", "source-before-tree", "source-before-status",
    "source-before-index", "source-before-head-index-diff",
    "source-before-worktree-index-diff", "source-before-commit-object",
    "sdk-before-head", "sdk-before-tree", "sdk-before-status",
    "sdk-before-index", "sdk-before-head-index-diff",
    "sdk-before-worktree-index-diff", "sdk-archive", "sdk-archive-confirm", "patch-check",
    "patch-apply", "source-after-head", "source-after-tree",
    "source-after-status", "source-after-index", "source-after-head-index-diff",
    "source-after-worktree-index-diff", "source-after-commit-object",
    "sdk-after-head", "sdk-after-tree", "sdk-after-status", "sdk-after-index",
    "sdk-after-head-index-diff", "sdk-after-worktree-index-diff",
)
GIT_CONFIG_PREFIX = (
    "-c", "core.fsmonitor=false", "-c", "core.attributesFile=/dev/null",
    "-c", "tar.umask=0002",
)


def _absolute(path: Path, name: str) -> Path:
    result = Path(path)
    if not result.is_absolute():
        raise ValueError(f"{name} must be absolute")
    return result


def make_command(generated_sdk_root: Path, tool_dir: Path, *, jobs: int = 6) -> list[str]:
    root = _absolute(generated_sdk_root, "generated SDK root")
    tools = _absolute(tool_dir, "tool directory")
    if isinstance(jobs, bool) or not isinstance(jobs, int) or jobs != 6:
        raise ValueError("Stage 0-H build requires exactly six jobs")
    return [
        "/usr/bin/make",
        "-C",
        str(root / "SDK"),
        f"TOOL_DIR={tools}",
        "RUN_POST_SCRIPT=true",
        "VERBOSE=0",
        "-j6",
    ]


def objcopy_commands(objcopy: Path, elf: Path, output_root: Path) -> list[list[str]]:
    tool = _absolute(objcopy, "objcopy")
    source = _absolute(elf, "ELF")
    output = _absolute(output_root, "section output root")
    return [
        [str(tool), "-O", "binary", "-j", section, str(source), str(output / filename)]
        for section, filename in SECTION_OUTPUTS
    ]


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _write_new(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    value = Path(path)
    if value.exists() or value.is_symlink():
        raise ValueError(f"output already exists: {value.name}")
    descriptor = os.open(
        value,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        mode,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(data)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _regular_identity(path: Path) -> tuple[object, ...]:
    value = Path(path)
    info = value.lstat()
    if not stat.S_ISREG(info.st_mode) or value.is_symlink():
        raise ValueError(f"not a regular file: {value}")
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns, _sha(value.read_bytes()))


def _reject_symlink_components(path: Path) -> None:
    value = Path(path)
    if not value.is_absolute():
        raise ValueError("path must be absolute")
    cursor = Path(value.anchor)
    for part in value.parts[1:]:
        cursor /= part
        if cursor.exists() or cursor.is_symlink():
            if cursor.is_symlink():
                raise ValueError("symlink path component")


def build_command_specs(*, generated_sdk_root: Path, build_root: Path, tools: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    generated = _absolute(generated_sdk_root, "generated SDK root")
    output = _absolute(build_root, "build root")
    if set(tools) < {"make", "objcopy", "objdump", "nm"}:
        raise ValueError("missing invoked build tool")
    elf = generated / "SDK/cpu/br35/tools/sdk.elf"
    specs = [{"argv": make_command(generated, TOOLCHAIN_ROOT / "pi32v2/bin"), "role": "make", "tool": "make"}]
    specs.extend(
        {"argv": argv, "role": f"objcopy:{section}", "tool": "objcopy"}
        for (section, _), argv in zip(SECTION_OUTPUTS, objcopy_commands(Path(str(tools["objcopy"]["path"])), elf, output), strict=True)
    )
    specs.append({"argv": [str(tools["objdump"]["path"]), "-private-headers", "-section-headers", "-mcpu=r3", str(elf)], "role": "objdump", "tool": "objdump"})
    specs.append({"argv": [str(tools["nm"]["path"]), "-n", "--defined-only", str(elf)], "role": "nm", "tool": "nm"})
    return specs


def _real_directory(path: Path, label: str) -> Path:
    value = Path(path)
    _reject_symlink_components(value)
    if not value.is_dir():
        raise ValueError(f"{label} must be a real directory")
    return value.resolve(strict=True)


def _overlap(first: Path, second: Path) -> bool:
    try:
        first.relative_to(second)
        return True
    except ValueError:
        try:
            second.relative_to(first)
            return True
        except ValueError:
            return False


def validate_build_roots(*, generated_sdk_root: Path, build_root: Path, control_root: Path, protected_roots) -> dict[str, Path]:
    generated = _real_directory(generated_sdk_root, "generated SDK root")
    build = _real_directory(build_root, "build root")
    control = _real_directory(control_root, "control root")
    if not (generated / "SDK").is_dir() or (generated / "SDK").is_symlink():
        raise ValueError("generated SDK root lacks SDK")
    selected = (generated, build, control)
    if any(_overlap(a, b) for index, a in enumerate(selected) for b in selected[index + 1:]):
        raise ValueError("build roots must be distinct and nonoverlapping")
    protected = tuple(_real_directory(Path(item), "protected root") for item in protected_roots)
    if any(_overlap(value, item) for value in selected for item in protected):
        raise ValueError("build root overlaps protected root")
    if any(build.iterdir()) or any(control.iterdir()):
        raise ValueError("build and control roots must be empty")
    return {"buildRoot": build, "controlRoot": control, "generatedSdkRoot": generated}


def build_environment(control_root: Path, *, source_date_epoch: int, tool_root: Path) -> dict[str, str]:
    control = _real_directory(control_root, "control root")
    if type(source_date_epoch) is not int or source_date_epoch < 0 or Path(tool_root) != TOOLCHAIN_ROOT:
        raise ValueError("invalid build environment authority")
    home, temporary = control / "home", control / "tmp"
    for path in (home, temporary):
        if path.exists() or path.is_symlink():
            raise ValueError("controlled environment path preexists")
        path.mkdir(mode=0o700)
    return {
        "HOME": str(home), "TMPDIR": str(temporary), "LANG": "C", "LC_ALL": "C",
        "TZ": "UTC", "SOURCE_DATE_EPOCH": str(source_date_epoch),
        "PATH": f"{TOOLCHAIN_ROOT}/pi32v2/bin:{POST_ROOT}:/usr/bin:/bin",
    }


def _receipt_environment(*, source_date_epoch: int) -> dict[str, str]:
    if type(source_date_epoch) is not int or source_date_epoch < 0:
        raise ValueError("invalid build receipt epoch")
    return {
        "HOME": "$BUILD_CONTROL_ROOT/home",
        "TMPDIR": "$BUILD_CONTROL_ROOT/tmp",
        "LANG": "C",
        "LC_ALL": "C",
        "TZ": "UTC",
        "SOURCE_DATE_EPOCH": str(source_date_epoch),
        "PATH": f"{TOOLCHAIN_ROOT}/pi32v2/bin:{POST_ROOT}:/usr/bin:/bin",
    }


def _normalize_environment(environment: dict[str, str], *, control_root: Path, source_date_epoch: int) -> dict[str, str]:
    expected = {
        **_receipt_environment(source_date_epoch=source_date_epoch),
        "HOME": str(Path(control_root) / "home"),
        "TMPDIR": str(Path(control_root) / "tmp"),
    }
    if not isinstance(environment, dict) or environment != expected:
        raise ValueError("build environment drift")
    return _receipt_environment(source_date_epoch=source_date_epoch)


def ensure_nofile_limit(*, resource_id, getrlimit, setrlimit) -> dict[str, int]:
    if not callable(getrlimit) or not callable(setrlimit):
        raise TypeError("RLIMIT_NOFILE accessors must be callable")
    limits = getrlimit(resource_id)
    if (
        not isinstance(limits, tuple)
        or len(limits) != 2
        or any(type(value) is not int for value in limits)
    ):
        raise ValueError("invalid RLIMIT_NOFILE projection")
    soft, hard = limits
    if hard != resource.RLIM_INFINITY and hard < 8192:
        raise ValueError("RLIMIT_NOFILE hard limit below 8192")
    if soft != 8192:
        setrlimit(resource_id, (8192, hard))
    return dict(BUILD_RESOURCE_LIMITS)


def resolve_pinned_tools(toolchain_lock: dict[str, object], *, make_tool: dict[str, str]) -> dict[str, dict[str, object]]:
    if make_tool != toolchain_lock.get("hostTools", {}).get("make"):
        raise ValueError("make identity does not match lock")
    result = {}
    for name in sorted(PRIMARY_BUILD_TOOLS):
        record = toolchain_lock.get("tools", {}).get(name)
        if not isinstance(record, dict) or set(record) != {"installRelativePath", "sha256"}:
            raise ValueError(f"invalid {name} pin")
        path = TOOLCHAIN_ROOT / str(record["installRelativePath"])
        if _regular_identity(path)[-1] != record["sha256"]:
            raise ValueError(f"{name} identity mismatch")
        result[name] = {"path": str(path), "sha256": record["sha256"]}
    make_path = Path(make_tool["path"])
    if _regular_identity(make_path)[-1] != make_tool["sha256"]:
        raise ValueError("make identity mismatch")
    result["make"] = dict(make_tool)
    return result


def probe_tool_versions(tools: dict[str, dict[str, object]], *, cwd: Path, environment: dict[str, str], runner=subprocess.run) -> dict[str, dict[str, object]]:
    if list(tools) != ["make", "objcopy", "objdump", "nm"]:
        raise ValueError("version probe projection/order is closed")
    try:
        epoch = int(environment["SOURCE_DATE_EPOCH"])
        control = Path(environment["HOME"]).parent
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid version-probe environment") from error
    receipt_environment = _normalize_environment(environment, control_root=control, source_date_epoch=epoch)
    receipts = {}
    prompt = re.compile(rb"(?:connect|select|device|usb|serial)", re.I)
    for name, tool in tools.items():
        path = Path(str(tool["path"]))
        if _regular_identity(path)[-1] != tool["sha256"]:
            raise ValueError(f"{name} identity drift")
        argv = [str(path), "--version"]
        result = runner(argv, check=False, cwd=cwd, env=environment, shell=False, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
        expected_stdout, normalized = BUILD_TOOL_VERSIONS[name]
        if (not isinstance(result, subprocess.CompletedProcess) or
                result.args != argv or result.returncode != 0 or
                not result.stdout.startswith(expected_stdout) or
                result.stderr != b"" or prompt.search(result.stdout + result.stderr)):
            raise ValueError(f"{name} version probe failed")
        receipts[name] = {
            "argv": argv, "cwd": "$BUILD_ROOT", "environment": receipt_environment,
            "exitCode": 0,
            "stderrHex": result.stderr.hex().upper(), "stderrSha256": _sha(result.stderr), "stderrSize": len(result.stderr),
            "stdoutHex": result.stdout.hex().upper(), "stdoutSha256": _sha(result.stdout), "stdoutSize": len(result.stdout),
            "tool": name, "toolSha256": tool["sha256"], "version": normalized,
        }
    return receipts


def _validate_runtime_lock(toolchain_lock: dict[str, object]) -> None:
    if _sha(_canonical(toolchain_lock)) != TOOLCHAIN_LOCK_SHA256:
        raise ValueError("toolchain lock identity drift")


def resolve_lto_runtime(toolchain_lock: dict[str, object], *, tool_root: Path) -> dict[str, object]:
    if Path(tool_root) != TOOLCHAIN_ROOT:
        raise ValueError("unreviewed LTO tool root")
    _validate_runtime_lock(toolchain_lock)
    tools = {}
    for name in RUNTIME_TOOL_NAMES:
        pin = toolchain_lock["tools"][name]
        invocation = TOOLCHAIN_ROOT / pin["installRelativePath"]
        resolved = TOOLCHAIN_ROOT / pin.get("resolvedInstallRelativePath", pin["installRelativePath"])
        if "symlinkTarget" in pin:
            if not invocation.is_symlink() or os.readlink(invocation) != pin["symlinkTarget"]:
                raise ValueError(f"{name} invocation symlink drift")
        elif invocation.is_symlink() or invocation != resolved:
            raise ValueError(f"{name} invocation drift")
        identity = _regular_identity(resolved)
        if identity[-1] != pin["sha256"]:
            raise ValueError(f"{name} bytes drift")
        if "byteLength" in pin and identity[3] != pin["byteLength"]:
            raise ValueError(f"{name} size drift")
        if "mode" in pin and stat.S_IMODE(identity[2]) != int(pin["mode"], 8):
            raise ValueError(f"{name} mode drift")
        tools[name] = {**pin, "invocationPath": str(invocation), "resolvedPath": str(resolved)}
    env_pin = toolchain_lock["hostTools"]["env"]
    if _regular_identity(Path(env_pin["path"]))[-1] != env_pin["sha256"]:
        raise ValueError("env identity drift")
    python_pin = toolchain_lock["hostTools"]["python3"]
    python_path = Path(python_pin["path"])
    if not python_path.is_symlink() or os.readlink(python_path) != python_pin["symlinkTarget"] or str(python_path.resolve(strict=True)) != python_pin["resolvedPath"]:
        raise ValueError("python3 route drift")
    if _regular_identity(Path(python_pin["resolvedPath"]))[-1] != python_pin["sha256"]:
        raise ValueError("python3 bytes drift")
    interpreter = toolchain_lock["runtime"]["elfInterpreter"]
    interpreter_path = Path(interpreter["path"])
    if not interpreter_path.is_file() or _sha(interpreter_path.read_bytes()) != interpreter["sha256"]:
        raise ValueError("ELF interpreter drift")
    controlled = toolchain_lock["runtime"]["controlledPathTemplate"].replace("${TOOL_ROOT}", str(TOOLCHAIN_ROOT))
    expected_controlled = f"{TOOLCHAIN_ROOT}/pi32v2/bin:{POST_ROOT}:/usr/bin:/bin"
    if controlled != expected_controlled:
        raise ValueError("controlled PATH drift")
    for component in controlled.split(":")[:2]:
        shadow = Path(component) / "python3"
        if shadow.exists() or shadow.is_symlink():
            raise ValueError("python3 shadow precedes pinned interpreter")
    return {
        "controlledPath": controlled,
        "elfInterpreter": dict(interpreter),
        "hostTools": {"env": dict(env_pin), "python3": dict(python_pin)},
        "tools": {name: tools[name] for name in sorted(tools)},
    }


def validate_lto_wrapper_argv(argv: list[str]) -> None:
    if not isinstance(argv, list) or not all(isinstance(item, str) and "\0" not in item for item in argv):
        raise ValueError("invalid LTO wrapper argv")
    for argument in argv:
        if any(argument == option or argument.startswith(option + "=") for option in FORBIDDEN_WRAPPER_OPTIONS):
            raise ValueError("forbidden LTO wrapper option")


def build_runtime_receipt(*, runtime: dict[str, object], toolchain_lock: dict[str, object]) -> dict[str, object]:
    _validate_runtime_lock(toolchain_lock)
    expected = _runtime_projection(toolchain_lock)
    if runtime != expected:
        raise ValueError("runtime evidence drift")
    return {"schema": "e87-stage0-build-runtime-v1", "toolchainLockSha256": TOOLCHAIN_LOCK_SHA256, **json.loads(_canonical(runtime))}


def _validate_runtime_receipt_impl(receipt: dict[str, object], *, expected_runtime: dict[str, object], toolchain_lock: dict[str, object]) -> dict[str, object]:
    expected = {"schema": "e87-stage0-build-runtime-v1", "toolchainLockSha256": TOOLCHAIN_LOCK_SHA256, **json.loads(_canonical(expected_runtime))}
    _validate_runtime_lock(toolchain_lock)
    if not isinstance(receipt, dict) or receipt != expected:
        raise ValueError("runtime receipt is not the closed expected projection")
    return receipt


def validate_runtime_receipt(receipt: dict[str, object], *, expected_runtime: dict[str, object], toolchain_lock: dict[str, object]) -> dict[str, object]:
    return _validate_runtime_receipt_impl(receipt, expected_runtime=expected_runtime, toolchain_lock=toolchain_lock)


def _runtime_projection(toolchain_lock: dict[str, object]) -> dict[str, object]:
    """Return the closed runtime projection without touching the host again."""
    _validate_runtime_lock(toolchain_lock)
    tools = {}
    for name in RUNTIME_TOOL_NAMES:
        pin = toolchain_lock["tools"][name]
        resolved = pin.get("resolvedInstallRelativePath", pin["installRelativePath"])
        tools[name] = {
            **deepcopy(pin),
            "invocationPath": str(TOOLCHAIN_ROOT / pin["installRelativePath"]),
            "resolvedPath": str(TOOLCHAIN_ROOT / resolved),
        }
    template = toolchain_lock["runtime"]["controlledPathTemplate"]
    return {
        "controlledPath": template.replace("${TOOL_ROOT}", str(TOOLCHAIN_ROOT)),
        "elfInterpreter": deepcopy(toolchain_lock["runtime"]["elfInterpreter"]),
        "hostTools": {
            "env": deepcopy(toolchain_lock["hostTools"]["env"]),
            "python3": deepcopy(toolchain_lock["hostTools"]["python3"]),
        },
        "tools": {name: tools[name] for name in sorted(tools)},
    }


def _lstat_token(path: Path, *, content: bool) -> tuple[object, ...]:
    value = Path(path)
    info = value.lstat()
    if value.is_symlink():
        payload = ("L", os.readlink(value))
    elif value.is_file():
        payload = ("F", _sha(value.read_bytes())) if content else ("F",)
    elif value.is_dir():
        payload = ("D",)
    else:
        payload = ("S",)
    return (str(value), info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns, *payload)


def _snapshot_lto_runtime_impl(*, runtime: dict[str, object]) -> tuple[tuple[object, ...], ...]:
    if not isinstance(runtime, dict) or set(runtime) != {"controlledPath", "elfInterpreter", "hostTools", "tools"}:
        raise ValueError("invalid runtime projection")
    records = []
    for name in sorted(runtime["tools"]):
        record = runtime["tools"][name]
        invocation, resolved = Path(record["invocationPath"]), Path(record["resolvedPath"])
        if "symlinkTarget" in record:
            if not invocation.is_symlink() or os.readlink(invocation) != record["symlinkTarget"]:
                raise ValueError("runtime invocation drift")
            records.append(_lstat_token(invocation, content=False))
        elif invocation.is_symlink() or invocation != resolved:
            raise ValueError("runtime direct invocation drift")
        identity = _regular_identity(resolved)
        if identity[-1] != record["sha256"] or ("mode" in record and stat.S_IMODE(identity[2]) != int(record["mode"], 8)) or ("byteLength" in record and identity[3] != record["byteLength"]):
            raise ValueError("runtime resolved tool drift")
        records.append(_lstat_token(resolved, content=True))
    env_path = Path(runtime["hostTools"]["env"]["path"])
    if _regular_identity(env_path)[-1] != runtime["hostTools"]["env"]["sha256"]:
        raise ValueError("env runtime drift")
    records.append(_lstat_token(env_path, content=True))
    python = runtime["hostTools"]["python3"]
    python_path, resolved_python = Path(python["path"]), Path(python["resolvedPath"])
    if not python_path.is_symlink() or os.readlink(python_path) != python["symlinkTarget"] or python_path.resolve(strict=True) != resolved_python:
        raise ValueError("python runtime route drift")
    if _regular_identity(resolved_python)[-1] != python["sha256"]:
        raise ValueError("python runtime bytes drift")
    records.extend((_lstat_token(python_path, content=False), _lstat_token(resolved_python, content=True)))
    interpreter = Path(runtime["elfInterpreter"]["path"])
    if not interpreter.is_file() or _sha(interpreter.read_bytes()) != runtime["elfInterpreter"]["sha256"]:
        raise ValueError("interpreter runtime drift")
    records.append(_lstat_token(interpreter, content=True))
    components = runtime["controlledPath"].split(":")
    if len(components) != 4:
        raise ValueError("controlled PATH structure drift")
    for component in components[:2]:
        directory = Path(component)
        shadow = directory / "python3"
        if shadow.exists() or shadow.is_symlink():
            raise ValueError("python3 shadow in controlled PATH")
        records.append(_lstat_token(directory, content=False))
        records.append((str(shadow), "absent"))
    return tuple(records)


def snapshot_lto_runtime(*, runtime: dict[str, object]) -> tuple[tuple[object, ...], ...]:
    return _snapshot_lto_runtime_impl(runtime=runtime)


def reverify_lto_runtime(*, runtime: dict[str, object], snapshot) -> None:
    if _snapshot_lto_runtime_impl(runtime=runtime) != snapshot:
        raise ValueError("LTO runtime changed during use")


def _load_bootstrap_tool():
    path = ROOT / "firmware/tools/bootstrap-sdk.py"
    spec = importlib.util.spec_from_file_location("e87_stage0_build_bootstrap", path)
    if spec is None or spec.loader is None:
        raise ValueError("cannot load bootstrap tool")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_BOOTSTRAP_VALIDATOR = None


def _load_bootstrap_validator():
    global _BOOTSTRAP_VALIDATOR
    if _BOOTSTRAP_VALIDATOR is None:
        path = ROOT / "firmware/tools/bootstrap-sdk.py"
        spec = importlib.util.spec_from_file_location("e87_stage0_build_bootstrap_validator", path)
        if spec is None or spec.loader is None:
            raise ValueError("cannot load bootstrap validator")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _BOOTSTRAP_VALIDATOR = module
    return _BOOTSTRAP_VALIDATOR


def _load_toolchain_lock() -> dict[str, object]:
    path = ROOT / "firmware/locks/toolchain.lock.json"
    data = path.read_bytes()
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid toolchain lock") from error
    if data != _canonical(value) or _sha(data) != TOOLCHAIN_LOCK_SHA256:
        raise ValueError("toolchain lock bytes drift")
    return value


def _read_canonical_json(path: Path, label: str) -> tuple[bytes, dict[str, object]]:
    value = Path(path)
    _reject_symlink_components(value)
    if value.is_symlink() or not value.is_file():
        raise ValueError(f"{label} must be a regular file")
    data = value.read_bytes()
    try:
        document = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {label}") from error
    if not isinstance(document, dict) or data != _canonical(document):
        raise ValueError(f"{label} is not canonical")
    return data, document


def _projection_sha(value: object) -> str:
    data = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("ascii")
    return _sha(data)


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    base = Path(root)
    for entry in sorted(base.rglob("*"), key=lambda item: item.relative_to(base).as_posix()):
        relative = entry.relative_to(base).as_posix().encode("utf-8")
        mode = entry.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError("tree contains symlink")
        if stat.S_ISDIR(mode):
            digest.update(b"D\0" + relative + b"\0")
        elif stat.S_ISREG(mode):
            git_mode = b"100755" if stat.S_IMODE(mode) & 0o111 else b"100644"
            digest.update(b"F\0" + relative + b"\0" + git_mode + b"\0" + hashlib.sha256(entry.read_bytes()).digest())
        else:
            raise ValueError("tree contains special file")
    return digest.hexdigest().upper()


def _tree_sha256_without_build_products(root: Path) -> str:
    """Reconstruct the materialized-input tree after exact build products exist."""
    base = Path(root)
    entries = sorted(base.rglob("*"), key=lambda item: item.relative_to(base).as_posix())

    def dynamic_file(relative: str) -> bool:
        return relative in {"SDK/cpu/br35/tools/sdk.elf", "SDK/cpu/br35/tools/sdk.map"} or (
            relative.startswith("SDK/build/") and relative.endswith(".c.o")
        )

    retained_files = {
        entry.relative_to(base).as_posix()
        for entry in entries
        if entry.is_file() and not entry.is_symlink() and not dynamic_file(entry.relative_to(base).as_posix())
    }
    dynamic_paths = {
        entry.relative_to(base).as_posix()
        for entry in entries
        if (entry.is_file() or entry.is_symlink()) and dynamic_file(entry.relative_to(base).as_posix())
    }
    digest = hashlib.sha256()
    for entry in entries:
        relative_text = entry.relative_to(base).as_posix()
        mode = entry.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError("tree contains symlink")
        if stat.S_ISREG(mode) and dynamic_file(relative_text):
            continue
        if stat.S_ISDIR(mode):
            prefix = relative_text + "/"
            is_dynamic_ancestor = any(path.startswith(prefix) for path in dynamic_paths)
            has_retained_descendant = any(path.startswith(prefix) for path in retained_files)
            if is_dynamic_ancestor and not has_retained_descendant:
                continue
        relative = relative_text.encode("utf-8")
        if stat.S_ISDIR(mode):
            digest.update(b"D\0" + relative + b"\0")
        elif stat.S_ISREG(mode):
            git_mode = b"100755" if stat.S_IMODE(mode) & 0o111 else b"100644"
            digest.update(b"F\0" + relative + b"\0" + git_mode + b"\0" + hashlib.sha256(entry.read_bytes()).digest())
        else:
            raise ValueError("tree contains special file")
    return digest.hexdigest().upper()


def _bootstrap_git_argv(root_token: str, *arguments: str) -> list[str]:
    return ["/usr/bin/git", *GIT_CONFIG_PREFIX, "--git-dir", f"{root_token}/.git", "--work-tree", root_token, *arguments]


def _expected_bootstrap_argv(receipt: dict[str, object]) -> dict[str, list[str]]:
    result = {"git-version": ["/usr/bin/git", "--version"]}
    for kind, token, commit, tree, with_commit in (
        ("source", "${SOURCE_ROOT}", receipt["sourceCommit"], receipt["sourceTree"], True),
        ("sdk", "${SDK_ROOT}", SDK_COMMIT, SDK_TREE, False),
    ):
        for phase in ("before", "after"):
            result[f"{kind}-{phase}-head"] = _bootstrap_git_argv(token, "rev-parse", "HEAD")
            result[f"{kind}-{phase}-tree"] = _bootstrap_git_argv(token, "rev-parse", "HEAD^{tree}")
            result[f"{kind}-{phase}-status"] = _bootstrap_git_argv(token, "status", "--porcelain=v1", "--untracked-files=no")
            result[f"{kind}-{phase}-index"] = _bootstrap_git_argv(token, "ls-files", "-v", "--stage", "-z", "--")
            result[f"{kind}-{phase}-head-index-diff"] = _bootstrap_git_argv(token, "diff", "--no-ext-diff", "--no-textconv", "--exit-code", "--cached", "HEAD", "--")
            result[f"{kind}-{phase}-worktree-index-diff"] = _bootstrap_git_argv(token, "diff", "--no-ext-diff", "--no-textconv", "--exit-code", "--")
            if with_commit:
                result[f"{kind}-{phase}-commit-object"] = _bootstrap_git_argv(token, "cat-file", "commit", str(commit))
    result["sdk-archive"] = _bootstrap_git_argv("${SDK_ROOT}", "archive", "--format=tar", SDK_COMMIT)
    result["sdk-archive-confirm"] = _bootstrap_git_argv("${SDK_ROOT}", "archive", "--format=tar", SDK_COMMIT)
    result["patch-check"] = ["/usr/bin/git", *GIT_CONFIG_PREFIX, "apply", "--no-index", "--check", "-"]
    result["patch-apply"] = ["/usr/bin/git", *GIT_CONFIG_PREFIX, "apply", "--no-index", "-"]
    return result


def _validate_bootstrap_document(receipt: dict[str, object], expected_commands: list[dict[str, object]]) -> None:
    top_keys = {
        "commands", "gitTool", "locks", "outputTreeSha256", "overlay", "patch", "schema",
        "sdkCommit", "sdkTree", "sourceCommit", "sourceCommitEpoch", "sourceCommitObjectSha256",
        "sourceTree", "validations",
    }
    if not isinstance(receipt, dict) or set(receipt) != top_keys:
        raise ValueError("closed bootstrap receipt schema drift")
    if not isinstance(receipt.get("commands"), list) or not isinstance(expected_commands, list):
        raise ValueError("invalid bootstrap command projection")
    patch = receipt.get("patch")
    if not isinstance(patch, dict) or set(patch) != {"paths", "sha256", "size"}:
        raise ValueError("invalid bootstrap patch projection")
    if receipt.get("validations") != BOOTSTRAP_VALIDATIONS or not all(type(value) is bool and value for value in receipt["validations"].values()):
        raise ValueError("bootstrap validation projection drift")
    if HEX64.fullmatch(str(receipt.get("outputTreeSha256"))) is None or receipt["outputTreeSha256"] == "0" * 64:
        raise ValueError("bootstrap output tree digest drift")
    if receipt["commands"] != expected_commands:
        raise ValueError("bootstrap command evidence drift")
    if receipt["schema"] != "e87-stage0-bootstrap-receipt-v1":
        raise ValueError("bootstrap schema drift")
    if receipt["locks"] != LOCK_DIGESTS or receipt["gitTool"] != {"path": "/usr/bin/git", "sha256": "587EF21868C948B883993E23209B86A72A6DDC06AAB1545C697FFC31075ACD4A", "version": "2.34.1"}:
        raise ValueError("bootstrap pin projection drift")
    if receipt["sdkCommit"] != SDK_COMMIT or receipt["sdkTree"] != SDK_TREE or receipt["validations"] != BOOTSTRAP_VALIDATIONS:
        raise ValueError("bootstrap fixed identity drift")
    if HEX40.fullmatch(str(receipt["sourceCommit"])) is None or HEX40.fullmatch(str(receipt["sourceTree"])) is None:
        raise ValueError("invalid source identity")
    if HEX64.fullmatch(str(receipt["sourceCommitObjectSha256"])) is None or type(receipt["sourceCommitEpoch"]) is not int or receipt["sourceCommitEpoch"] <= 0:
        raise ValueError("invalid source commit evidence")
    overlay = receipt["overlay"]
    expected_pairs = sorted((record["source"], record["destination"]) for record in BOOTSTRAP_OVERLAY_RECORDS)
    if not isinstance(overlay, list) or [(item.get("source"), item.get("destination")) for item in overlay] != expected_pairs:
        raise ValueError("bootstrap overlay allowlist drift")
    for item in overlay:
        if set(item) != {"destination", "sha256", "size", "source"} or HEX64.fullmatch(str(item["sha256"])) is None or type(item["size"]) is not int or item["size"] <= 0:
            raise ValueError("invalid bootstrap overlay receipt")
    if set(patch) != {"paths", "sha256", "size"} or patch["paths"] != sorted(BOOTSTRAP_PATCH_TARGETS) or HEX64.fullmatch(str(patch["sha256"])) is None or type(patch["size"]) is not int or patch["size"] <= 0:
        raise ValueError("bootstrap patch projection drift")
    expected_argv = _expected_bootstrap_argv(receipt)
    base_environment = {
        "GIT_ATTR_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1", "GIT_OPTIONAL_LOCKS": "0", "HOME": "/dev/null",
        "LANG": "C", "LC_ALL": "C", "TZ": "UTC", "XDG_CONFIG_HOME": "/dev/null",
    }
    by_role = {}
    empty_sha = _sha(b"")
    command_keys = {"argv", "cwd", "environment", "exitCode", "role", "stderrSha256", "stderrSize", "stdin", "stdoutSha256", "stdoutSize", "toolSha256", "toolVersion"}
    for expected_role, record in zip(BOOTSTRAP_COMMAND_ROLES, receipt["commands"], strict=True):
        if not isinstance(record, dict) or set(record) != command_keys or record["role"] != expected_role or record["argv"] != expected_argv[expected_role]:
            raise ValueError("bootstrap command argv/order drift")
        expected_cwd = "${OWNED_STAGING_ROOT}" if expected_role.startswith("patch-") else ("sdk" if expected_role.startswith("sdk-") else "source")
        expected_environment = dict(base_environment)
        if expected_cwd == "${OWNED_STAGING_ROOT}":
            expected_environment["GIT_CEILING_DIRECTORIES"] = "${OWNED_STAGING_ROOT}"
        if record["cwd"] != expected_cwd or record["environment"] != expected_environment or record["toolSha256"] != receipt["gitTool"]["sha256"] or record["toolVersion"] != receipt["gitTool"]["version"]:
            raise ValueError("bootstrap command context drift")
        if type(record["exitCode"]) is not int or record["exitCode"] != 0:
            raise ValueError("bootstrap command failed")
        for field in ("stdoutSha256", "stderrSha256"):
            if HEX64.fullmatch(str(record[field])) is None:
                raise ValueError("bootstrap command digest invalid")
        for field in ("stdoutSize", "stderrSize"):
            if type(record[field]) is not int or record[field] < 0:
                raise ValueError("bootstrap command size invalid")
        if record["stderrSha256"] != empty_sha or record["stderrSize"] != 0:
            raise ValueError("bootstrap command stderr is not empty")
        stdin = {"sha256": patch["sha256"], "size": patch["size"]} if expected_role in {"patch-check", "patch-apply"} else None
        if record["stdin"] != stdin:
            raise ValueError("bootstrap command stdin drift")
        by_role[expected_role] = record
    exact_stdout = {
        "git-version": b"git version 2.34.1\n",
        **{f"source-{phase}-head": (receipt["sourceCommit"] + "\n").encode("ascii") for phase in ("before", "after")},
        **{f"source-{phase}-tree": (receipt["sourceTree"] + "\n").encode("ascii") for phase in ("before", "after")},
        **{f"sdk-{phase}-head": (SDK_COMMIT + "\n").encode("ascii") for phase in ("before", "after")},
        **{f"sdk-{phase}-tree": (SDK_TREE + "\n").encode("ascii") for phase in ("before", "after")},
    }
    for role, payload in exact_stdout.items():
        if (by_role[role]["stdoutSha256"], by_role[role]["stdoutSize"]) != (_sha(payload), len(payload)):
            raise ValueError("bootstrap identity output drift")
    for role, record in by_role.items():
        if any(token in role for token in ("status", "head-index-diff", "worktree-index-diff")) or role.startswith("patch-"):
            if (record["stdoutSha256"], record["stdoutSize"]) != (empty_sha, 0):
                raise ValueError("bootstrap clean output drift")
    for kind in ("source", "sdk"):
        before, after = by_role[f"{kind}-before-index"], by_role[f"{kind}-after-index"]
        if (before["stdoutSha256"], before["stdoutSize"]) != (after["stdoutSha256"], after["stdoutSize"]) or before["stdoutSize"] <= 0:
            raise ValueError("bootstrap index stability drift")
    before = by_role["source-before-commit-object"]
    after = by_role["source-after-commit-object"]
    if (before["stdoutSha256"], before["stdoutSize"]) != (after["stdoutSha256"], after["stdoutSize"]) or before["stdoutSha256"] != receipt["sourceCommitObjectSha256"] or before["stdoutSize"] <= 0:
        raise ValueError("source commit object evidence drift")
    archive = by_role["sdk-archive"]
    archive_confirm = by_role["sdk-archive-confirm"]
    if (archive["stdoutSha256"], archive["stdoutSize"]) != (archive_confirm["stdoutSha256"], archive_confirm["stdoutSize"]):
        raise ValueError("SDK archive confirmation drift")
    if archive["stdoutSize"] <= 0 or archive["stdoutSha256"] in {empty_sha, "0" * 64} or (archive["stdoutSize"] != 36 and archive["stdoutSize"] % 512 != 0):
        raise ValueError("SDK archive evidence drift")


def _validate_bootstrap_files(receipt: dict[str, object], generated_sdk_root: Path) -> None:
    root = _real_directory(generated_sdk_root, "generated SDK root")
    for record in receipt["overlay"]:
        path = root / record["destination"]
        if _regular_identity(path)[-1] != record["sha256"] or path.stat().st_size != record["size"]:
            raise ValueError("generated overlay identity drift")
    for relative in receipt["patch"]["paths"]:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError("generated patch target missing")


def validate_bootstrap_receipt(*, bootstrap_receipt_path: Path, generated_sdk_root: Path, expected_source_commit: str, expected_commands: list[dict[str, object]]) -> dict[str, object]:
    data, receipt = _read_canonical_json(bootstrap_receipt_path, "bootstrap receipt")
    if receipt.get("sourceCommit") != expected_source_commit:
        raise ValueError("unexpected bootstrap source commit")
    _validate_bootstrap_document(receipt, expected_commands)
    _validate_bootstrap_files(receipt, generated_sdk_root)
    if _tree_sha256(generated_sdk_root) != receipt["outputTreeSha256"]:
        raise ValueError("generated SDK tree drift")
    if _sha(data) == _sha(b""):
        raise ValueError("empty bootstrap receipt")
    return receipt


def derive_expected_bootstrap_evidence(*, generated_sdk_root: Path, bootstrap_receipt_path: Path, control_root: Path, runner, event_sink=None) -> dict[str, object]:
    emit = event_sink if event_sink is not None else (lambda _event: None)
    control = _real_directory(control_root, "bootstrap replay control root")
    if any(control.iterdir()):
        raise ValueError("bootstrap replay control root must be empty")
    original_data, original = _read_canonical_json(bootstrap_receipt_path, "bootstrap receipt")
    replay_root = Path(tempfile.mkdtemp(prefix="bootstrap-replay-", dir=control))
    owned_staging_root = replay_root.with_name(replay_root.name + "-owned-staging")
    try:
        emit("bootstrap-replay:started")
        replay = _load_bootstrap_tool().bootstrap_sdk(
            repository_root=ROOT,
            sdk_root=SDK_ROOT,
            output_root=replay_root,
            expected_source_commit=original["sourceCommit"],
            expected_source_tree=original["sourceTree"],
            expected_sdk_commit=SDK_COMMIT,
            expected_sdk_tree=SDK_TREE,
            overlay_records=list(BOOTSTRAP_OVERLAY_RECORDS),
            patch_path=BOOTSTRAP_PATCH_PATH,
            allowed_patch_paths=tuple(sorted(BOOTSTRAP_PATCH_TARGETS)),
            git_tool=deepcopy(original["gitTool"]),
            runner=runner,
        )
        _validate_bootstrap_document(replay, original["commands"])
        _validate_bootstrap_document(original, replay["commands"])
        if replay != original:
            raise ValueError("bootstrap replay receipt drift")
        emit("bootstrap-replay:receipt-validated")
        generated_tree = _tree_sha256(generated_sdk_root)
        replay_tree = _tree_sha256(replay_root)
        if generated_tree != original["outputTreeSha256"] or replay_tree != original["outputTreeSha256"]:
            raise ValueError("bootstrap replay tree drift")
        emit("bootstrap-replay:tree-validated")
        validation = {
            "commandsSha256": _projection_sha(original["commands"]),
            "outputTreeSha256": original["outputTreeSha256"],
            "receiptSha256": _sha(original_data),
            "schema": "e87-stage0-bootstrap-replay-validation-v1",
            "validationsSha256": _projection_sha(original["validations"]),
        }
        return {
            "commands": deepcopy(original["commands"]),
            "outputTreeSha256": original["outputTreeSha256"],
            "receiptSha256": _sha(original_data),
            "schema": "e87-stage0-bootstrap-replay-evidence-v1",
            "validation": validation,
            "validations": deepcopy(original["validations"]),
        }
    finally:
        if owned_staging_root.exists() or owned_staging_root.is_symlink():
            if owned_staging_root.parent.resolve(strict=True) != control or owned_staging_root.name != replay_root.name + "-owned-staging":
                raise ValueError("owned replay staging cleanup authority drift")
            if owned_staging_root.is_symlink() or owned_staging_root.is_file():
                owned_staging_root.unlink()
            elif owned_staging_root.is_dir():
                shutil.rmtree(owned_staging_root)
            else:
                raise ValueError("special owned replay staging entry")
        if replay_root.exists() or replay_root.is_symlink():
            if replay_root.is_symlink():
                replay_root.unlink()
            else:
                shutil.rmtree(replay_root)
        emit("bootstrap-replay:cleaned")


def parse_object_response(data: bytes | str) -> list[str]:
    text = data.decode("utf-8") if isinstance(data, bytes) else data
    if not isinstance(text, str) or "\x00" in text:
        raise ValueError("invalid object response")
    objects = []
    for token in re.findall(r"(?:'[^']*'|\"[^\"]*\"|\S+)", text):
        token = token.strip("'\"")
        if token.endswith(".o"):
            objects.append(token.replace("\\", "/"))
    if not objects:
        raise ValueError("empty object response")
    return objects


def validate_source_selection(objects: list[str]) -> None:
    if not isinstance(objects, list) or not all(isinstance(item, str) for item in objects):
        raise ValueError("object list must contain strings")
    normalized = [item.replace("\\", "/") for item in objects]
    if len(normalized) != len(set(normalized)):
        raise ValueError("duplicate target object")
    lowered = "\n".join(normalized).lower()
    if any(fragment in lowered for fragment in FORBIDDEN_FRAGMENTS):
        raise ValueError("forbidden inherited or generic target source")
    selected_e87 = set()
    for item in normalized:
        canonical = item.split("SDK/build/", 1)[-1]
        if "/e87_" in canonical or canonical.startswith("objs/apps/watch/e87/") or "board_e87_1542" in canonical:
            selected_e87.add(canonical)
    if selected_e87 != REQUIRED_E87_OBJECTS:
        raise ValueError(
            f"wrong E87 target selection: {sorted(selected_e87)}"
        )
    other_boards = [
        item for item in normalized
        if "/board/br35/" in item and "board_e87_1542" not in item
    ]
    if other_boards:
        raise ValueError("generic BR35 board object selected")


def parse_objdump_sections(text: str) -> list[dict[str, int | str]]:
    if not isinstance(text, str):
        raise ValueError("objdump output must be text")
    sections = []
    pattern = re.compile(
        r"^\s*\d+\s+(\.[^\s]+)\s+([0-9A-Fa-f]+)\s+([0-9A-Fa-f]+)\s+([0-9A-Fa-f]+)\s+([0-9A-Fa-f]+)",
        re.MULTILINE,
    )
    for match in pattern.finditer(text):
        name, size, vma, lma, offset = match.groups()
        sections.append({"name": name, "size": int(size, 16), "vma": int(vma, 16), "lma": int(lma, 16), "fileOffset": int(offset, 16)})
    if not sections:
        raise ValueError("no ELF sections parsed")
    return sections


def parse_elf32(image: bytes) -> dict[str, object]:
    if not isinstance(image, bytes) or len(image) < 52:
        raise ValueError("truncated ELF")
    try:
        header = struct.unpack("<16sHHIIIIIHHHHHH", image[:52])
    except struct.error as error:
        raise ValueError("invalid ELF header") from error
    ident, e_type, machine, version, entry, phoff, shoff, _, ehsize, phentsize, phnum, shentsize, shnum, shstrndx = header
    if ident[:7] != b"\x7fELF\x01\x01\x01" or e_type != 2 or machine != 0xF1 or version != 1 or entry != 0x0C000100:
        raise ValueError("wrong ELF32 PI32v2 identity")
    if (ehsize, phentsize, phnum, shentsize, shnum) != (52, 32, len(SECTION_OUTPUTS), 40, len(SECTION_OUTPUTS) + 2) or not (0 <= shstrndx < shnum):
        raise ValueError("unexpected ELF table geometry")
    if phoff + phentsize * phnum > len(image) or shoff + shentsize * shnum > len(image):
        raise ValueError("truncated ELF tables")
    programs = []
    for index in range(phnum):
        values = struct.unpack("<IIIIIIII", image[phoff + index * phentsize:phoff + (index + 1) * phentsize])
        p_type, offset, vma, lma, file_size, memory_size, flags, alignment = values
        if p_type != 1 or file_size <= 0 or memory_size < file_size or offset + file_size > len(image) or lma < 0x0C000000:
            raise ValueError("invalid PT_LOAD")
        programs.append({"fileOffset": offset, "fileSize": file_size, "flags": flags, "lma": lma, "memorySize": memory_size, "type": "PT_LOAD", "vma": vma})
    for field in ("fileOffset", "lma", "vma"):
        ranges = sorted((int(item[field]), int(item[field]) + int(item["fileSize"])) for item in programs)
        if any(first[1] > second[0] for first, second in zip(ranges, ranges[1:])):
            raise ValueError("overlapping ELF load ranges")
    shstr = image[shoff + shstrndx * shentsize:shoff + (shstrndx + 1) * shentsize]
    shstr_values = struct.unpack("<IIIIIIIIII", shstr)
    names_offset, names_size = shstr_values[4], shstr_values[5]
    if names_offset + names_size > len(image):
        raise ValueError("invalid ELF section-name table")
    names = image[names_offset:names_offset + names_size]
    required = {name for name, _ in SECTION_OUTPUTS}
    sections = []
    seen = set()
    for index in range(1, shnum):
        values = struct.unpack("<IIIIIIIIII", image[shoff + index * shentsize:shoff + (index + 1) * shentsize])
        name_offset, section_type, flags, vma, offset, size, _, _, _, _ = values
        if name_offset >= len(names):
            raise ValueError("invalid ELF section name")
        end = names.find(b"\0", name_offset)
        if end < 0:
            raise ValueError("unterminated ELF section name")
        try:
            name = names[name_offset:end].decode("ascii")
        except UnicodeDecodeError as error:
            raise ValueError("non-ASCII ELF section name") from error
        if name not in required:
            continue
        if name in seen or section_type != 1 or size <= 0 or offset + size > len(image):
            raise ValueError("invalid or duplicate required ELF section")
        if name == ".text" and not (flags & 0x4):
            raise ValueError(".text is not executable")
        matches = [item for item in programs if item["fileOffset"] == offset and item["vma"] == vma and item["fileSize"] == size]
        if len(matches) != 1:
            raise ValueError("ELF section is not bound to one PT_LOAD")
        program = matches[0]
        if name == ".text" and not (int(program["flags"]) & 1):
            raise ValueError(".text PT_LOAD is not executable")
        seen.add(name)
        sections.append({"fileOffset": offset, "lma": int(program["lma"]), "name": name, "size": size, "vma": vma})
    if seen != required or [item["name"] for item in sections] != [name for name, _ in SECTION_OUTPUTS]:
        raise ValueError("required ELF section projection drift")
    text = sections[0]
    if not (int(text["vma"]) <= entry < int(text["vma"]) + int(text["size"])):
        raise ValueError("entry point is outside executable .text")
    validate_target_layout(sections, architecture="pi32v2", cpu="r3", entry_address=entry)
    return {"elfClass": "ELF32", "endianness": "little", "entryAddress": entry, "machine": machine, "programHeaders": programs, "sections": sections, "type": "ET_EXEC"}


def parse_object_inventory(data: bytes, sdk_build_root: Path) -> list[dict[str, object]]:
    if not isinstance(data, bytes) or b"\0" in data:
        raise ValueError("invalid object inventory")
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ValueError("object inventory is not UTF-8") from error
    root = _real_directory(sdk_build_root, "SDK build root")
    records, paths, inodes = [], set(), set()
    for line in lines:
        if not line:
            raise ValueError("blank object inventory record")
        candidate = Path(line)
        path = candidate if candidate.is_absolute() else root / candidate
        _reject_symlink_components(path)
        if path.is_symlink() or not path.is_file():
            raise ValueError("object inventory entry is not regular")
        resolved = path.resolve(strict=True)
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError as error:
            raise ValueError("object escapes SDK build root") from error
        info = path.stat()
        inode = (info.st_dev, info.st_ino)
        if relative in paths or inode in inodes:
            raise ValueError("duplicate or aliased object")
        paths.add(relative); inodes.add(inode)
        payload = path.read_bytes()
        records.append({"relativePath": relative, "sha256": _sha(payload), "size": len(payload)})
    validate_source_selection([record["relativePath"] for record in records])
    return records


def parse_map_provenance(text: str, inventory: list[dict[str, object]]) -> dict[str, object]:
    validate_map_policy(text)
    match = re.search(r"^\.text\.bt_ble_init\s+(0x[0-9A-Fa-f]+)\s+0x[0-9A-Fa-f]+\s+(\S+)\s*$", text, re.MULTILINE)
    symbol = re.search(r"^\s*(0x[0-9A-Fa-f]+)\s+bt_ble_init\s*$", text, re.MULTILINE)
    if match is None or symbol is None or int(match.group(1), 16) != int(symbol.group(1), 16):
        raise ValueError("map symbol provenance mismatch")
    known = {record["relativePath"] for record in inventory}
    object_name = match.group(2).replace("\\", "/")
    if object_name not in known or object_name != "objs/apps/watch/e87/e87_stage0_ble.c.o":
        raise ValueError("bt_ble_init came from the wrong object")
    return {"bt_ble_init": {"address": f"0x{int(symbol.group(1), 16):08X}", "object": object_name, "strength": "STRONG"}}


def parse_build_provenance(generated_sdk_root: Path) -> dict[str, object]:
    root = _real_directory(generated_sdk_root, "generated SDK root")
    compile_path, link_path = root / "SDK/Makefile", root / "SDK/build/Makefile.mk"
    compile_data, link_data = compile_path.read_bytes(), link_path.read_bytes()
    try:
        compile_text, link_text = compile_data.decode("ascii"), link_data.decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError("Makefile provenance is not ASCII") from error
    targets = re.findall(r"(?:^|\s)-target\s+(\S+)", compile_text)
    compile_cpus = re.findall(r"(?:^|\s)-mcpu=(\S+)", compile_text)
    link_cpus = re.findall(r"--plugin-opt=mcpu=(\S+)", link_text)
    if targets != ["pi32v2"] or compile_cpus != ["r3"] or link_cpus != ["r3", "r3"]:
        raise ValueError("CPU/target Makefile provenance drift")
    if any(token not in compile_text for token in ("-integrated-as", "-flto")):
        raise ValueError("compile flags provenance drift")
    if any(token not in link_text for token in ("--plugin-opt=-pi32v2-enable-simd=true", "--plugin-opt=-mattr=+fprev1", "-Tcpu/br35/sdk.ld", "-M=cpu/br35/tools/sdk.map", "$(LFLAGS)", "$(CFLAGS)")):
        raise ValueError("link flags/recipes provenance drift")
    return {
        "compileMakefile": {"cpu": "r3", "relativePath": "SDK/Makefile", "sha256": _sha(compile_data), "target": "pi32v2"},
        "linkMakefile": {"cpu": "r3", "cpuTokenCount": 2, "relativePath": "SDK/build/Makefile.mk", "sha256": _sha(link_data)},
    }


def validate_target_layout(
    sections: list[dict[str, int | str]],
    *,
    architecture: str,
    cpu: str,
    entry_address: int,
    code_limit: int = 0x180000,
) -> None:
    if (architecture, cpu, entry_address) != ("pi32v2", "r3", 0x0C000100):
        raise ValueError("wrong ELF target identity")
    by_name = {str(item["name"]): item for item in sections}
    if set(by_name) != {name for name, _ in SECTION_OUTPUTS}:
        raise ValueError("wrong load-section set")
    extents = []
    file_extents = []
    for name, _ in SECTION_OUTPUTS:
        item = by_name[name]
        size = int(item["size"])
        if size <= 0:
            raise ValueError(f"empty required section: {name}")
        start = int(item["lma"])
        extents.append((start, start + size, name))
        file_start = int(item["fileOffset"])
        file_extents.append((file_start, file_start + size, name))
    extents.sort()
    for previous, current in zip(extents, extents[1:]):
        if previous[1] != current[0]:
            raise ValueError("load sections overlap or contain a gap")
    file_extents.sort()
    for previous, current in zip(file_extents, file_extents[1:]):
        if previous[1] > current[0]:
            raise ValueError("ELF section file ranges overlap")
    normalized_end = extents[-1][1] - 0x0C000000
    if normalized_end > code_limit:
        raise ValueError("target image overlaps UIRES reservation")


def parse_nm_symbols(text: str) -> list[tuple[str, str, int]]:
    result = []
    for line in text.splitlines():
        match = re.fullmatch(r"\s*([0-9A-Fa-f]+)\s+([A-Za-z])\s+(\S+)\s*", line)
        if match:
            address, kind, name = match.groups()
            result.append((name, kind, int(address, 16)))
    return result


def validate_symbol_policy(symbols: list[tuple[str, str, int]]) -> None:
    definitions = [(name, kind) for name, kind, _ in symbols if name == "bt_ble_init" and kind == "T"]
    if definitions != [("bt_ble_init", "T")]:
        raise ValueError("requires exactly one strong bt_ble_init")


def validate_map_policy(text: str) -> None:
    if not isinstance(text, str) or "\x00" in text:
        raise ValueError("map must be text")
    lowered = text.lower()
    section = re.findall(
        r"^\.text\.bt_ble_init\s+0x[0-9a-f]+\s+0x[0-9a-f]+\s+(\S+)\s*$",
        lowered,
        re.MULTILINE,
    )
    symbol = re.findall(r"^\s*0x[0-9a-f]+\s+bt_ble_init\s*$", lowered, re.MULTILINE)
    if (
        section != ["objs/apps/watch/e87/e87_stage0_ble.c.o"]
        and section != ["sdk/build/objs/apps/watch/e87/e87_stage0_ble.c.o"]
    ) or len(symbol) != 1 or lowered.count("bt_ble_init") != 2:
        raise ValueError("bt_ble_init map provenance mismatch")
    if any(fragment in lowered for fragment in FORBIDDEN_FRAGMENTS):
        raise ValueError("forbidden target object in map")


def build_receipt(
    *,
    app_path: Path,
    bootstrap_receipt_path: Path,
    bootstrap_validation: dict[str, object],
    command_results: list[subprocess.CompletedProcess],
    commands: list[dict[str, object]],
    elf_path: Path,
    environment: dict[str, str],
    expected_source_commit: str,
    generated_sdk_root: Path,
    map_provenance: dict[str, object],
    resource_limits: dict[str, int],
    runtime: dict[str, object],
    section_outputs: list[dict[str, object]],
    section_root: Path,
    sections: list[dict[str, int | str]],
    source_objects: list[str],
    symbols: list[dict[str, str]],
    validations: dict[str, bool],
    version_probes: list[dict[str, object]],
    version_results: list[subprocess.CompletedProcess],
) -> dict[str, object]:
    generated = _real_directory(generated_sdk_root, "generated SDK root")
    section_base = _real_directory(section_root, "section root")
    bootstrap_data, bootstrap = _read_canonical_json(bootstrap_receipt_path, "bootstrap receipt")
    if bootstrap.get("sourceCommit") != expected_source_commit:
        raise ValueError("bootstrap source commit drift")
    _validate_bootstrap_document(bootstrap, deepcopy(bootstrap.get("commands", [])))
    _validate_bootstrap_files(bootstrap, generated)
    if _tree_sha256_without_build_products(generated) != bootstrap["outputTreeSha256"]:
        raise ValueError("materialized bootstrap tree drift")
    expected_validation = {
        "commandsSha256": _projection_sha(bootstrap["commands"]),
        "outputTreeSha256": bootstrap["outputTreeSha256"],
        "receiptSha256": _sha(bootstrap_data),
        "schema": "e87-stage0-bootstrap-replay-validation-v1",
        "validationsSha256": _projection_sha(bootstrap["validations"]),
    }
    if not isinstance(bootstrap_validation, dict) or bootstrap_validation != expected_validation:
        raise ValueError("bootstrap replay validation drift")
    expected_environment = _receipt_environment(source_date_epoch=bootstrap["sourceCommitEpoch"])
    if not isinstance(environment, dict) or environment != expected_environment:
        raise ValueError("build execution environment drift")
    if not isinstance(resource_limits, dict) or resource_limits != BUILD_RESOURCE_LIMITS:
        raise ValueError("build resource-limit evidence drift")
    if not isinstance(validations, dict) or validations != BUILD_VALIDATIONS or any(type(value) is not bool for value in validations.values()):
        raise ValueError("build validation evidence drift")
    lock = _load_toolchain_lock()
    expected_runtime = _runtime_projection(lock)
    _validate_runtime_receipt_impl(runtime, expected_runtime=expected_runtime, toolchain_lock=lock)
    if source_objects != list(SOURCE_OBJECTS):
        raise ValueError("source-object projection drift")
    validate_source_selection(source_objects)
    if not isinstance(sections, list):
        raise ValueError("invalid section projection")
    elf_value = Path(elf_path)
    generated_elf = generated / "SDK/cpu/br35/tools/sdk.elf"
    elf_data = elf_value.read_bytes() if not elf_value.is_symlink() and elf_value.is_file() else b""
    if not elf_data or generated_elf.is_symlink() or not generated_elf.is_file() or generated_elf.read_bytes() != elf_data:
        raise ValueError("ELF identity drift")
    parsed_elf = parse_elf32(elf_data)
    if parsed_elf["sections"] != sections:
        raise ValueError("ELF section evidence drift")
    validate_target_layout(sections, architecture="pi32v2", cpu="r3", entry_address=0x0C000100)
    expected_symbols = [{"address": "0x0C000100", "kind": "T", "name": "bt_ble_init"}]
    if symbols != expected_symbols:
        raise ValueError("symbol evidence drift")
    expected_map = {"bt_ble_init": {"address": "0x0C000100", "object": SOURCE_OBJECTS[2], "strength": "STRONG"}}
    if map_provenance != expected_map:
        raise ValueError("map provenance drift")
    if not isinstance(section_outputs, list) or len(section_outputs) != len(SECTION_OUTPUTS):
        raise ValueError("wrong section-output count")
    enriched_sections = []
    for expected, record, parsed in zip(SECTION_OUTPUTS, section_outputs, sections, strict=True):
        if not isinstance(record, dict) or set(record) != {"filename", "section", "sha256", "size"} or (record["section"], record["filename"]) != expected:
            raise ValueError("section-output record drift")
        path = section_base / expected[1]
        data = path.read_bytes() if not path.is_symlink() and path.is_file() else b""
        if not data or record != {"filename": expected[1], "section": expected[0], "sha256": _sha(data), "size": len(data)}:
            raise ValueError("section-output identity drift")
        start, size = int(parsed["fileOffset"]), int(parsed["size"])
        if elf_data[start:start + size] != data:
            raise ValueError("section output is not derived from ELF")
        enriched_sections.append({**parsed, "sha256": _sha(data)})
    app_value = Path(app_path)
    app_data = app_value.read_bytes() if not app_value.is_symlink() and app_value.is_file() else b""
    if not app_data or app_data != b"".join((section_base / filename).read_bytes() for _, filename in SECTION_OUTPUTS):
        raise ValueError("app concatenation drift")
    if not isinstance(commands, list) or len(commands) != 11 or not isinstance(command_results, list) or len(command_results) != 11:
        raise ValueError("build command/result count drift")
    command_keys = {
        "argv", "cwd", "environment", "exitCode", "role",
        "stderrHex", "stderrSha256", "stderrSize",
        "stdoutHex", "stdoutSha256", "stdoutSize",
        "toolSha256", "toolVersion",
    }
    expected_roles = ["make", *[f"objcopy:{name}" for name, _ in SECTION_OUTPUTS], "objdump", "nm"]
    tool_pins = {
        "make": lock["hostTools"]["make"],
        "objcopy": lock["tools"]["objcopy"],
        "objdump": lock["tools"]["objdump"],
        "nm": lock["tools"]["nm"],
    }
    projected_tools = {}
    for name, index in (("make", 0), ("objcopy", 1), ("objdump", 9), ("nm", 10)):
        path = commands[index].get("argv", [None])[0] if isinstance(commands[index], dict) else None
        projected_tools[name] = {"path": path, "sha256": tool_pins[name]["sha256"]}
    expected_specs = build_command_specs(generated_sdk_root=generated, build_root=section_base, tools=projected_tools)
    for index, (role, command, result, spec) in enumerate(zip(expected_roles, commands, command_results, expected_specs, strict=True)):
        tool = role.split(":", 1)[0]
        if not isinstance(command, dict) or set(command) != command_keys:
            raise ValueError("closed build command schema drift")
        stdout = result.stdout if isinstance(result, subprocess.CompletedProcess) and isinstance(result.stdout, bytes) else None
        stderr = result.stderr if isinstance(result, subprocess.CompletedProcess) and isinstance(result.stderr, bytes) else None
        if command != {
            "argv": spec["argv"], "cwd": "$BUILD_ROOT", "environment": expected_environment,
            "exitCode": 0, "role": role,
            "stderrHex": stderr.hex().upper() if stderr is not None else "",
            "stderrSha256": _sha(stderr) if stderr is not None else "",
            "stderrSize": len(stderr) if stderr is not None else -1,
            "stdoutHex": stdout.hex().upper() if stdout is not None else "",
            "stdoutSha256": _sha(stdout) if stdout is not None else "",
            "stdoutSize": len(stdout) if stdout is not None else -1,
            "toolSha256": tool_pins[tool]["sha256"], "toolVersion": BUILD_TOOL_VERSIONS[tool][1],
        }:
            raise ValueError(f"build command evidence drift at {index}")
        if not isinstance(result, subprocess.CompletedProcess) or list(result.args) != spec["argv"] or result.returncode != 0 or not isinstance(result.stdout, bytes) or not isinstance(result.stderr, bytes):
            raise ValueError("raw build command result drift")
    if not isinstance(version_probes, list) or not isinstance(version_results, list) or len(version_probes) != 4 or len(version_results) != 4:
        raise ValueError("version probe count drift")
    version_keys = {
        "argv", "cwd", "environment", "exitCode",
        "stderrHex", "stderrSha256", "stderrSize",
        "stdoutHex", "stdoutSha256", "stdoutSize",
        "tool", "toolSha256", "version",
    }
    for name, record, result in zip(("make", "objcopy", "objdump", "nm"), version_probes, version_results, strict=True):
        expected_argv = [str(projected_tools[name]["path"]), "--version"]
        if not isinstance(result, subprocess.CompletedProcess) or list(result.args) != expected_argv or result.returncode != 0 or not isinstance(result.stdout, bytes) or not isinstance(result.stderr, bytes):
            raise ValueError("raw version probe result drift")
        expected_record = {
            "argv": expected_argv, "cwd": "$BUILD_ROOT", "environment": expected_environment,
            "exitCode": 0,
            "stderrHex": result.stderr.hex().upper(), "stderrSha256": _sha(result.stderr), "stderrSize": len(result.stderr),
            "stdoutHex": result.stdout.hex().upper(), "stdoutSha256": _sha(result.stdout), "stdoutSize": len(result.stdout),
            "tool": name, "toolSha256": tool_pins[name]["sha256"],
            "version": BUILD_TOOL_VERSIONS[name][1],
        }
        if not isinstance(record, dict) or set(record) != version_keys or record != expected_record:
            raise ValueError("version probe evidence drift")
    provenance = parse_build_provenance(generated)
    map_path = generated / "SDK/cpu/br35/tools/sdk.map"
    map_sha = _sha(map_path.read_bytes()) if not map_path.is_symlink() and map_path.is_file() else _projection_sha(map_provenance)
    bootstrap_record = {"filename": Path(bootstrap_receipt_path).name, "sha256": _sha(bootstrap_data), "size": len(bootstrap_data)}
    code_end = max(int(item["lma"]) + int(item["size"]) for item in sections) - 0x0C000000
    return {
        "app": {"filename": "app.bin", "sha256": _sha(app_data), "size": len(app_data)},
        "bootstrap": bootstrap,
        "bootstrapReceipt": bootstrap_record,
        "bootstrapValidation": bootstrap_validation,
        "buildProvenance": provenance,
        "commands": commands,
        "elf": {"filename": "sdk.elf", "sha256": _sha(elf_data), "size": len(elf_data)},
        "environment": environment,
        "inputs": [bootstrap_record],
        "mapProvenance": map_provenance,
        "resourceLimits": resource_limits,
        "runtime": runtime,
        "schema": "e87-stage0-build-receipt-v1",
        "sectionOutputs": section_outputs,
        "sections": enriched_sections,
        "sourceCommit": bootstrap["sourceCommit"],
        "sourceDateEpoch": bootstrap["sourceCommitEpoch"],
        "sourceObjects": source_objects,
        "symbols": symbols,
        "target": {
            "architecture": "pi32v2", "codeEnd": f"0x{code_end:08X}", "cpu": "r3",
            "entryAddress": "0x0C000100", "mapSha256": map_sha, "uiresStart": "0x00180000",
        },
        "validations": validations,
        "versionProbes": version_probes,
    }


def _execution_result_from_record(record: object) -> subprocess.CompletedProcess:
    if not isinstance(record, dict):
        raise ValueError("execution record is not an object")
    try:
        argv = record["argv"]
        exit_code = record["exitCode"]
        stdout_hex = record["stdoutHex"]
        stderr_hex = record["stderrHex"]
    except KeyError as error:
        raise ValueError("execution record is incomplete") from error
    if (
        not isinstance(argv, list)
        or not all(isinstance(item, str) for item in argv)
        or type(exit_code) is not int
        or not isinstance(stdout_hex, str)
        or not isinstance(stderr_hex, str)
    ):
        raise ValueError("execution record has invalid types")
    try:
        stdout = bytes.fromhex(stdout_hex)
        stderr = bytes.fromhex(stderr_hex)
    except ValueError as error:
        raise ValueError("execution record contains invalid hex") from error
    return subprocess.CompletedProcess(list(argv), exit_code, stdout, stderr)


def _materialize_bootstrap_projection(source: Path, destination: Path) -> None:
    source_root = _real_directory(source, "built generated SDK root")
    target = Path(destination)
    if target.exists() or target.is_symlink():
        raise ValueError("bootstrap projection destination must not exist")
    for entry in source_root.rglob("*"):
        if entry.is_symlink():
            raise ValueError("built generated SDK contains a symlink")
    shutil.copytree(source_root, target, copy_function=shutil.copy2)
    dynamic = [
        target / "SDK/cpu/br35/tools/sdk.elf",
        target / "SDK/cpu/br35/tools/sdk.map",
        *(target / "SDK/build" / relative for relative in SOURCE_OBJECTS),
    ]
    for path in dynamic:
        if path.is_symlink() or not path.is_file():
            raise ValueError("built generated SDK is missing an expected build product")
        path.unlink()
    for directory in sorted(
        (entry for entry in target.rglob("*") if entry.is_dir()),
        key=lambda entry: len(entry.parts),
        reverse=True,
    ):
        if not any(directory.iterdir()):
            directory.rmdir()
    if _tree_sha256(target) != _tree_sha256_without_build_products(source_root):
        raise ValueError("bootstrap projection reconstruction drift")


def validate_build_for_package(
    *,
    generated_sdk_root: Path,
    build_root: Path,
    bootstrap_receipt_path: Path,
    control_root: Path,
    expected_source_commit: str,
    runner,
) -> dict[str, object]:
    if not callable(runner):
        raise TypeError("bootstrap replay runner must be callable")
    generated = _real_directory(generated_sdk_root, "generated SDK root")
    build = _real_directory(build_root, "build root")
    control = _real_directory(control_root, "build validation control root")
    receipt_path = build / "build-receipt.json"
    claimed_data, claimed = _read_canonical_json(receipt_path, "build receipt")
    canonical_bootstrap = Path(bootstrap_receipt_path)
    if canonical_bootstrap != build / "bootstrap-receipt.json":
        raise ValueError("package validation requires canonical bootstrap receipt")
    authority_root = Path(tempfile.mkdtemp(prefix="build-authority-", dir=control))
    projection_root = authority_root / "generated-sdk"
    replay_control = authority_root / "control"
    replay_control.mkdir(mode=0o700)
    try:
        _materialize_bootstrap_projection(generated, projection_root)
        replay = derive_expected_bootstrap_evidence(
            generated_sdk_root=projection_root,
            bootstrap_receipt_path=canonical_bootstrap,
            control_root=replay_control,
            runner=runner,
        )
        bootstrap_data, bootstrap = _read_canonical_json(canonical_bootstrap, "bootstrap receipt")
        bootstrap_validation = _validate_replay_evidence(replay, bootstrap, bootstrap_data)
    finally:
        shutil.rmtree(authority_root)
    try:
        command_records = claimed["commands"]
        version_records = claimed["versionProbes"]
        command_results = [_execution_result_from_record(record) for record in command_records]
        version_results = [_execution_result_from_record(record) for record in version_records]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("build execution evidence is malformed") from error
    elf_path = build / "sdk.elf"
    elf_data = elf_path.read_bytes() if not elf_path.is_symlink() and elf_path.is_file() else b""
    if not elf_data:
        raise ValueError("build ELF is missing")
    parsed_elf = parse_elf32(elf_data)
    section_outputs = []
    for section, filename in SECTION_OUTPUTS:
        path = build / filename
        data = path.read_bytes() if not path.is_symlink() and path.is_file() else b""
        if not data:
            raise ValueError("build section output is missing")
        section_outputs.append({"filename": filename, "section": section, "sha256": _sha(data), "size": len(data)})
    object_root = generated / "SDK/build"
    object_paths = sorted(object_root.rglob("*.c.o"), key=lambda path: path.relative_to(object_root).as_posix())
    if {path.relative_to(object_root).as_posix() for path in object_paths} != set(SOURCE_OBJECTS):
        raise ValueError("object inventory content drift")
    inventory_data = b"".join((relative + "\n").encode("utf-8") for relative in SOURCE_OBJECTS)
    inventory = parse_object_inventory(inventory_data, object_root)
    source_objects = [record["relativePath"] for record in inventory]
    map_path = generated / "SDK/cpu/br35/tools/sdk.map"
    if map_path.is_symlink() or not map_path.is_file():
        raise ValueError("build map is missing")
    map_provenance = parse_map_provenance(map_path.read_text(encoding="ascii"), inventory)
    if len(command_results) != 11:
        raise ValueError("build command count drift")
    objdump_text = command_results[-2].stdout.decode("ascii")
    if (
        "file format elf32-pi32v2" not in objdump_text
        or "architecture: pi32v2" not in objdump_text
        or "start address 0x0c000100" not in objdump_text.lower()
        or parse_objdump_sections(objdump_text) != parsed_elf["sections"]
    ):
        raise ValueError("objdump execution evidence drift")
    parsed_symbols = parse_nm_symbols(command_results[-1].stdout.decode("ascii"))
    validate_symbol_policy(parsed_symbols)
    symbols = [
        {"address": f"0x{address:08X}", "kind": kind, "name": name}
        for name, kind, address in parsed_symbols
        if name == "bt_ble_init"
    ]
    lock = _load_toolchain_lock()
    runtime = build_runtime_receipt(runtime=_runtime_projection(lock), toolchain_lock=lock)
    try:
        derived = build_receipt(
            app_path=build / "app.bin",
            bootstrap_receipt_path=canonical_bootstrap,
            bootstrap_validation=bootstrap_validation,
            command_results=command_results,
            commands=command_records,
            elf_path=elf_path,
            environment=claimed["environment"],
            expected_source_commit=expected_source_commit,
            generated_sdk_root=generated,
            map_provenance=map_provenance,
            resource_limits=claimed["resourceLimits"],
            runtime=runtime,
            section_outputs=section_outputs,
            section_root=build,
            sections=parsed_elf["sections"],
            source_objects=source_objects,
            symbols=symbols,
            validations=claimed["validations"],
            version_probes=version_records,
            version_results=version_results,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("build receipt failed independent package validation") from error
    if _canonical(derived) != claimed_data:
        raise ValueError("build receipt is not the independently derived authority")
    return derived


def concatenate_sections(output_root: Path, app_path: Path) -> dict[str, object]:
    root = _absolute(output_root, "section output root")
    target = _absolute(app_path, "app output")
    if target.exists() or target.is_symlink():
        raise ValueError("app output must not preexist")
    chunks = []
    records = []
    for section, filename in SECTION_OUTPUTS:
        path = root / filename
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"missing section output: {filename}")
        data = path.read_bytes()
        if not data:
            raise ValueError(f"empty section output: {filename}")
        chunks.append(data)
        records.append({"filename": filename, "section": section, "sha256": hashlib.sha256(data).hexdigest().upper(), "size": len(data)})
    app = b"".join(chunks)
    target.write_bytes(app)
    return {"appSha256": hashlib.sha256(app).hexdigest().upper(), "appSize": len(app), "sections": records}


def _tree_snapshot(root: Path) -> tuple[tuple[object, ...], ...]:
    base = Path(root)
    records = []
    for entry in sorted(base.rglob("*"), key=lambda item: item.relative_to(base).as_posix()):
        records.append(_lstat_token(entry, content=True))
    return tuple(records)


def _directory_token(path: Path) -> tuple[int, int, int, int, int]:
    metadata = Path(path).lstat()
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ValueError("directory lease path changed type")
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _capture_directory_lease(path: Path) -> dict[str, object]:
    value = Path(path)
    parent = value.parent
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    parent_fd = os.open(parent, flags)
    try:
        root_fd = os.open(value, flags)
    except BaseException:
        os.close(parent_fd)
        raise
    parent_stat = os.fstat(parent_fd)
    root_stat = os.fstat(root_fd)
    lease = {
        "name": value.name,
        "parentFd": parent_fd,
        "parentPath": parent,
        "parentIdentity": (parent_stat.st_dev, parent_stat.st_ino),
        "path": value,
        "rootFd": root_fd,
        "rootIdentity": (root_stat.st_dev, root_stat.st_ino),
    }
    if not _directory_lease_matches(lease):
        _close_directory_lease(lease)
        raise ValueError("directory changed while acquiring lease")
    return lease


def _close_directory_lease(lease: dict[str, object] | None) -> None:
    if lease is None:
        return
    for key in ("rootFd", "parentFd"):
        descriptor = lease.get(key)
        if isinstance(descriptor, int) and descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
            lease[key] = -1


def _directory_lease_matches(lease: dict[str, object]) -> bool:
    try:
        parent = Path(lease["parentPath"]).lstat()
        root = Path(lease["path"]).lstat()
    except (FileNotFoundError, OSError):
        return False
    return (
        stat.S_ISDIR(parent.st_mode)
        and not stat.S_ISLNK(parent.st_mode)
        and stat.S_ISDIR(root.st_mode)
        and not stat.S_ISLNK(root.st_mode)
        and (parent.st_dev, parent.st_ino) == lease["parentIdentity"]
        and (root.st_dev, root.st_ino) == lease["rootIdentity"]
    )


def _directory_callback_token(lease: dict[str, object]) -> tuple[object, ...]:
    if not _directory_lease_matches(lease):
        return ("REBOUND",)
    return (_directory_token(Path(lease["parentPath"])), _directory_token(Path(lease["path"])))


def _clear_directory_fd(descriptor: int, *, keep: set[str] | None = None) -> None:
    retained = set() if keep is None else set(keep)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    for name in os.listdir(descriptor):
        if name in retained:
            continue
        metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if stat.S_ISDIR(metadata.st_mode):
            child_fd = os.open(name, flags, dir_fd=descriptor)
            try:
                opened = os.fstat(child_fd)
                if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
                    raise ValueError("cleanup directory changed before open")
                _clear_directory_fd(child_fd)
            finally:
                os.close(child_fd)
            os.rmdir(name, dir_fd=descriptor)
        elif stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            os.unlink(name, dir_fd=descriptor)
        else:
            raise ValueError("special cleanup entry")


def _cleanup_directory_lease(lease: dict[str, object] | None, *, keep: set[str] | None = None) -> bool:
    if lease is None or not _directory_lease_matches(lease):
        return False
    _clear_directory_fd(int(lease["rootFd"]), keep=keep)
    return True


def _validate_replay_evidence(evidence: dict[str, object], receipt: dict[str, object], receipt_data: bytes) -> dict[str, object]:
    validation = {
        "commandsSha256": _projection_sha(receipt["commands"]),
        "outputTreeSha256": receipt["outputTreeSha256"],
        "receiptSha256": _sha(receipt_data),
        "schema": "e87-stage0-bootstrap-replay-validation-v1",
        "validationsSha256": _projection_sha(receipt["validations"]),
    }
    expected = {
        "commands": deepcopy(receipt["commands"]),
        "outputTreeSha256": receipt["outputTreeSha256"],
        "receiptSha256": _sha(receipt_data),
        "schema": "e87-stage0-bootstrap-replay-evidence-v1",
        "validation": validation,
        "validations": deepcopy(receipt["validations"]),
    }
    if not isinstance(evidence, dict) or evidence != expected:
        raise ValueError("bootstrap replay evidence drift")
    return evidence["validation"]


def _command_result(
    result,
    argv: list[str],
    role: str,
    tool: dict[str, object],
    *,
    environment: dict[str, str],
) -> dict[str, object]:
    prompt = re.compile(rb"(?:connect|select|device|usb|serial)", re.I)
    if (
        not isinstance(result, subprocess.CompletedProcess)
        or list(result.args) != argv
        or result.returncode != 0
        or not isinstance(result.stdout, bytes)
        or not isinstance(result.stderr, bytes)
        or result.stderr
        or prompt.search(result.stdout + result.stderr)
    ):
        raise ValueError(f"build command failed: {role}")
    name = role.split(":", 1)[0]
    return {
        "argv": list(argv), "cwd": "$BUILD_ROOT", "environment": dict(environment),
        "exitCode": 0, "role": role,
        "stderrHex": result.stderr.hex().upper(), "stderrSha256": _sha(result.stderr), "stderrSize": len(result.stderr),
        "stdoutHex": result.stdout.hex().upper(), "stdoutSha256": _sha(result.stdout), "stdoutSize": len(result.stdout),
        "toolSha256": tool["sha256"], "toolVersion": BUILD_TOOL_VERSIONS[name][1],
    }


def _run_version_probes(
    tools: dict[str, dict[str, object]],
    *,
    cwd: Path,
    environment: dict[str, str],
    receipt_environment: dict[str, str],
    runner,
    emit,
):
    records, results = [], []
    expected_kwargs = {
        "check": False, "cwd": cwd, "env": environment, "shell": False,
        "stderr": subprocess.PIPE, "stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE,
    }
    prompt = re.compile(rb"(?:connect|select|device|usb|serial)", re.I)
    for name in ("make", "objcopy", "objdump", "nm"):
        emit(f"tool:{name}:version-rehashed")
        if _regular_identity(Path(str(tools[name]["path"]))) != tools[name]["snapshot"]:
            raise ValueError(f"{name} identity drift before version probe")
        argv = [str(tools[name]["path"]), "--version"]
        result = runner(argv, **expected_kwargs)
        expected_stdout, normalized = BUILD_TOOL_VERSIONS[name]
        if (not isinstance(result, subprocess.CompletedProcess) or
                list(result.args) != argv or result.returncode != 0 or
                not result.stdout.startswith(expected_stdout) or
                result.stderr != b"" or prompt.search(result.stdout + result.stderr)):
            raise ValueError(f"{name} version probe failed")
        records.append({
            "argv": argv, "cwd": "$BUILD_ROOT", "environment": dict(receipt_environment),
            "exitCode": 0,
            "stderrHex": result.stderr.hex().upper(), "stderrSha256": _sha(result.stderr), "stderrSize": len(result.stderr),
            "stdoutHex": result.stdout.hex().upper(), "stdoutSha256": _sha(result.stdout), "stdoutSize": len(result.stdout),
            "tool": name, "toolSha256": tools[name]["sha256"],
            "version": normalized,
        })
        results.append(result)
    return records, results


def run_target_build(
    *, generated_sdk_root: Path, bootstrap_receipt_path: Path, build_root: Path,
    control_root: Path, expected_source_commit: str, make_tool=None,
    runner=subprocess.run, version_runner=subprocess.run, event_sink=None,
) -> dict[str, object]:
    if event_sink is not None and not callable(event_sink):
        raise TypeError("event sink must be callable")
    external_emit = event_sink if event_sink is not None else (lambda _event: None)
    build_value = Path(build_root)
    control_value = Path(control_root)
    roots = None
    leases: list[dict[str, object]] = []
    build_lease = None
    control_lease = None
    original_nofile = None
    succeeded = False

    def emit(event: str) -> None:
        before = tuple(_directory_callback_token(lease) for lease in leases)
        external_emit(event)
        after = tuple(_directory_callback_token(lease) for lease in leases)
        if before != after:
            raise ValueError("build root binding changed during event callback")

    try:
        roots = validate_build_roots(
            generated_sdk_root=generated_sdk_root,
            build_root=build_value,
            control_root=control_value,
            protected_roots=(ROOT, SDK_ROOT, TOOLCHAIN_ROOT, POST_ROOT, REFERENCE_ROOT),
        )
        generated, build_value, control_value = roots["generatedSdkRoot"], roots["buildRoot"], roots["controlRoot"]
        build_lease = _capture_directory_lease(build_value)
        control_lease = _capture_directory_lease(control_value)
        leases.extend((build_lease, control_lease))
        emit("roots:validated")
        original_nofile = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource_limits = ensure_nofile_limit(
            resource_id=resource.RLIMIT_NOFILE,
            getrlimit=resource.getrlimit,
            setrlimit=resource.setrlimit,
        )
        initial_tree = _tree_snapshot(generated)
        bootstrap_snapshot = _regular_identity(Path(bootstrap_receipt_path))
        replay = derive_expected_bootstrap_evidence(
            generated_sdk_root=generated,
            bootstrap_receipt_path=Path(bootstrap_receipt_path),
            control_root=control_value,
            runner=subprocess.run,
            event_sink=event_sink,
        )
        bootstrap_data, bootstrap = _read_canonical_json(bootstrap_receipt_path, "bootstrap receipt")
        emit("bootstrap:reopened")
        if _regular_identity(Path(bootstrap_receipt_path)) != bootstrap_snapshot or _tree_snapshot(generated) != initial_tree:
            raise ValueError("bootstrap inputs changed during replay")
        bootstrap_validation = _validate_replay_evidence(replay, bootstrap, bootstrap_data)
        if bootstrap["sourceCommit"] != expected_source_commit:
            raise ValueError("unexpected source commit")
        canonical_bootstrap_path = build_value / "bootstrap-receipt.json"
        _write_new(canonical_bootstrap_path, bootstrap_data)
        canonical_bootstrap_snapshot = _regular_identity(canonical_bootstrap_path)
        environment = build_environment(control_value, source_date_epoch=bootstrap["sourceCommitEpoch"], tool_root=TOOLCHAIN_ROOT)
        receipt_environment = _normalize_environment(
            environment,
            control_root=control_value,
            source_date_epoch=bootstrap["sourceCommitEpoch"],
        )
        emit("environment:closed")
        lock = _load_toolchain_lock()
        selected_make = deepcopy(lock["hostTools"]["make"]) if make_tool is None else make_tool
        resolved = resolve_pinned_tools(lock, make_tool=selected_make)
        tools = {}
        for name in ("make", "objcopy", "objdump", "nm"):
            tools[name] = {**resolved[name], "snapshot": _regular_identity(Path(str(resolved[name]["path"])))}
        emit("tools:resolved")
        runtime_projection = resolve_lto_runtime(lock, tool_root=TOOLCHAIN_ROOT)
        emit("runtime:resolved")
        runtime_snapshot = snapshot_lto_runtime(runtime=runtime_projection)
        emit("runtime:snapshotted")
        link_tokens = (generated / "SDK/build/Makefile.mk").read_text(encoding="ascii").split()
        validate_lto_wrapper_argv(link_tokens)
        emit("runtime:argv-validated")
        runtime_receipt = build_runtime_receipt(runtime=runtime_projection, toolchain_lock=lock)
        emit("runtime:receipt-built")
        validate_runtime_receipt(runtime_receipt, expected_runtime=runtime_projection, toolchain_lock=lock)
        emit("runtime:receipt-validated")
        for name in ("make", "objcopy", "objdump", "nm"):
            emit(f"tool:{name}:resolved-rehashed")
            if _regular_identity(Path(str(tools[name]["path"]))) != tools[name]["snapshot"]:
                raise ValueError(f"{name} changed after resolution")
        version_probes, version_results = _run_version_probes(
            tools,
            cwd=build_value,
            environment=environment,
            receipt_environment=receipt_environment,
            runner=version_runner,
            emit=emit,
        )
        specs = build_command_specs(generated_sdk_root=generated, build_root=build_value, tools=tools)
        expected_kwargs = {
            "check": False, "cwd": build_value, "env": environment, "shell": False,
            "stderr": subprocess.PIPE, "stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE,
        }
        command_records, command_results = [], []
        parsed_elf = None
        source_objects = None
        map_provenance = None
        source_symbols = None
        output_sections = []
        provenance_before = parse_build_provenance(generated)
        produced_snapshots = None
        allowed_build_names = {"bootstrap-receipt.json", "sdk.elf", *[filename for _, filename in SECTION_OUTPUTS]}
        for spec in specs:
            role, name, argv = spec["role"], spec["tool"], spec["argv"]
            if role == "make":
                emit("runtime:reverified-before-make")
                reverify_lto_runtime(runtime=runtime_projection, snapshot=runtime_snapshot)
            emit(f"tool:{name}:runner-rehashed")
            if _regular_identity(Path(str(tools[name]["path"]))) != tools[name]["snapshot"]:
                raise ValueError(f"{name} changed before runner")
            emit(f"inputs:{role}:rehashed")
            if role == "make":
                if _regular_identity(Path(bootstrap_receipt_path)) != bootstrap_snapshot or _tree_snapshot(generated) != initial_tree or parse_build_provenance(generated) != provenance_before:
                    raise ValueError("build inputs changed before Make")
            elif produced_snapshots is None or _regular_identity(generated / "SDK/cpu/br35/tools/sdk.elf") != produced_snapshots["elf"]:
                raise ValueError("authoritative ELF changed before consumer")
            result = runner(argv, **expected_kwargs)
            command_results.append(result)
            command_records.append(
                _command_result(
                    result,
                    argv,
                    role,
                    tools[name],
                    environment=receipt_environment,
                )
            )
            make_output_data = None
            make_output_identity = None
            if role == "make":
                make_output_path = generated / "SDK/cpu/br35/tools/sdk.elf"
                if make_output_path.is_symlink() or not make_output_path.is_file():
                    raise ValueError("Make did not produce a regular ELF")
                make_output_data = make_output_path.read_bytes()
                make_output_identity = _regular_identity(make_output_path)
            emit(f"outputs:{role}:validated")
            if role == "make" and (
                _regular_identity(make_output_path) != make_output_identity
                or make_output_path.read_bytes() != make_output_data
            ):
                raise ValueError("Make ELF changed before validation")
            unknown = {path.name for path in build_value.iterdir()} - allowed_build_names
            if unknown:
                raise ValueError("unexpected build output")
            if role == "make":
                elf_path = generated / "SDK/cpu/br35/tools/sdk.elf"
                elf_data = elf_path.read_bytes() if not elf_path.is_symlink() and elf_path.is_file() else b""
                parsed_elf = parse_elf32(elf_data)
                object_root = generated / "SDK/build"
                object_paths = sorted(object_root.rglob("*.c.o"), key=lambda path: path.relative_to(object_root).as_posix())
                actual_object_names = {path.relative_to(object_root).as_posix() for path in object_paths}
                if actual_object_names != set(SOURCE_OBJECTS):
                    raise ValueError("object inventory content drift")
                ordered_object_paths = [object_root / relative for relative in SOURCE_OBJECTS]
                inventory_data = b"".join((relative + "\n").encode("utf-8") for relative in SOURCE_OBJECTS)
                inventory = parse_object_inventory(inventory_data, object_root)
                source_objects = [item["relativePath"] for item in inventory]
                if source_objects != list(SOURCE_OBJECTS):
                    raise ValueError("object inventory order/content drift")
                map_path = generated / "SDK/cpu/br35/tools/sdk.map"
                if map_path.is_symlink() or not map_path.is_file():
                    raise ValueError("map output missing")
                map_text = map_path.read_text(encoding="ascii")
                map_provenance = parse_map_provenance(map_text, inventory)
                if parse_build_provenance(generated) != provenance_before:
                    raise ValueError("Makefile provenance changed during build")
                produced_snapshots = {
                    "elf": _regular_identity(elf_path),
                    "map": _regular_identity(map_path),
                    "objects": tuple(_regular_identity(path) for path in ordered_object_paths),
                }
                (build_value / "sdk.elf").write_bytes(elf_data)
            elif role.startswith("objcopy:"):
                section = role.split(":", 1)[1]
                filename = dict(SECTION_OUTPUTS)[section]
                path = build_value / filename
                data = path.read_bytes() if not path.is_symlink() and path.is_file() else b""
                parsed = next(item for item in parsed_elf["sections"] if item["name"] == section)
                elf_data = (generated / "SDK/cpu/br35/tools/sdk.elf").read_bytes()
                expected_data = elf_data[int(parsed["fileOffset"]):int(parsed["fileOffset"]) + int(parsed["size"])]
                if not data or data != expected_data:
                    raise ValueError("objcopy section output drift")
                output_sections.append({"filename": filename, "section": section, "sha256": _sha(data), "size": len(data)})
            elif role == "objdump":
                text = result.stdout.decode("ascii")
                if "file format elf32-pi32v2" not in text or "architecture: pi32v2" not in text or "start address 0x0c000100" not in text.lower() or parse_objdump_sections(text) != parsed_elf["sections"]:
                    raise ValueError("objdump target evidence drift")
            elif role == "nm":
                parsed_symbols = parse_nm_symbols(result.stdout.decode("ascii"))
                validate_symbol_policy(parsed_symbols)
                source_symbols = [{"address": f"0x{address:08X}", "kind": kind, "name": symbol} for symbol, kind, address in parsed_symbols if symbol == "bt_ble_init"]
        emit("bootstrap:rehashed")
        if _regular_identity(Path(bootstrap_receipt_path)) != bootstrap_snapshot:
            raise ValueError("bootstrap receipt changed during build")
        if _regular_identity(canonical_bootstrap_path) != canonical_bootstrap_snapshot:
            raise ValueError("canonical bootstrap receipt changed during build")
        _validate_bootstrap_files(bootstrap, generated)
        emit("provenance:rehashed")
        if parse_build_provenance(generated) != provenance_before:
            raise ValueError("build provenance changed during build")
        concatenate_sections(build_value, build_value / "app.bin")
        emit("app:concatenated")
        receipt = build_receipt(
            app_path=build_value / "app.bin",
            bootstrap_receipt_path=canonical_bootstrap_path,
            bootstrap_validation=bootstrap_validation,
            command_results=command_results,
            commands=command_records,
            elf_path=build_value / "sdk.elf",
            environment=receipt_environment,
            expected_source_commit=expected_source_commit,
            generated_sdk_root=generated,
            map_provenance=map_provenance,
            resource_limits=resource_limits,
            runtime=runtime_receipt,
            section_outputs=output_sections,
            section_root=build_value,
            sections=parsed_elf["sections"],
            source_objects=source_objects,
            symbols=source_symbols,
            validations=dict(BUILD_VALIDATIONS),
            version_probes=version_probes,
            version_results=version_results,
        )
        receipt_path = build_value / "build-receipt.json"
        _write_new(receipt_path, _canonical(receipt))
        emit("receipt:committed")
        succeeded = True
        return receipt
    finally:
        try:
            if control_lease is not None:
                _cleanup_directory_lease(control_lease)
        finally:
            try:
                if not succeeded and build_lease is not None:
                    _cleanup_directory_lease(build_lease)
            finally:
                try:
                    if original_nofile is not None:
                        resource.setrlimit(resource.RLIMIT_NOFILE, original_nofile)
                finally:
                    _close_directory_lease(control_lease)
                    _close_directory_lease(build_lease)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", allow_abbrev=False)
    run.add_argument("--bootstrap-receipt", type=Path, required=True)
    run.add_argument("--build-root", type=Path, required=True)
    run.add_argument("--control-root", type=Path, required=True)
    run.add_argument("--expected-source-commit", type=str, required=True)
    run.add_argument("--generated-sdk-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "run":
        raise ValueError("unknown build command")
    receipt = run_target_build(
        generated_sdk_root=args.generated_sdk_root,
        bootstrap_receipt_path=args.bootstrap_receipt,
        build_root=args.build_root,
        control_root=args.control_root,
        expected_source_commit=args.expected_source_commit,
    )
    path = args.build_root / "build-receipt.json"
    data = _canonical(receipt)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or path.read_bytes() != data:
            raise ValueError("build receipt dispatch drift")
    else:
        path.write_bytes(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
