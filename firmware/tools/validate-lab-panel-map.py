#!/usr/bin/env python3
"""Validate the deliberately narrow E87 LAB_ONLY panel-smoke link projection."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import struct
import sys
from typing import Any


BASE_SOURCE_OBJECTS = (
    "objs/apps/common/debug/debug.c.o",
    "objs/apps/common/debug/debug_uart_config.c.o",
    "objs/apps/common/perf_counter/perf_counter.c.o",
    "objs/apps/common/update/update.c.o",
    "objs/apps/watch/app_main.c.o",
    "objs/apps/watch/board/br35/board_e87_1542_full/board_e87_1542_full.c.o",
    "objs/apps/watch/e87/e87_app.c.o",
    "objs/apps/watch/e87/e87_full_platform_config.c.o",
    "objs/apps/watch/log_config/lib_driver_config.c.o",
    "objs/apps/watch/log_config/lib_system_config.c.o",
    "objs/cpu/br35/power/power_app.c.o",
    "objs/cpu/br35/setup.c.o",
    "objs/cpu/config/lib_power_config.c.o",
    "objs/cpu/power/msg.c.o",
)

BASE_ARCHIVES = (
    "cpu/br35/liba/cpu.a",
    "cpu/br35/liba/system.a",
    "cpu/br35/liba/libc.a",
    "cpu/br35/liba/cfg_tool.a",
    "cpu/br35/liba/device.a",
    "cpu/br35/liba/fs.a",
    "cpu/br35/liba/printf.a",
    "cpu/br35/liba/vm.a",
)

TOOLCHAIN_ARCHIVES = (
    "toolchain/lib/r3-large/libm.a",
    "toolchain/lib/r3-large/libc.a",
    "toolchain/lib/r3-large/libm.a",
    "toolchain/lib/r3-large/libcompiler-rt.a",
)

FORBIDDEN_LIVE_SYMBOLS = (
    "btstack_init",
    "app_ble_init",
    "rcsp_init",
    "charge_init",
    "charge_start",
    "set_charge_event_flag",
    "update_mode_api_v2",
)

INITCALL_RANGES = (
    ("_initcall_begin", "_initcall_end"),
    ("_early_initcall_begin", "_early_initcall_end"),
    ("_late_initcall_begin", "_late_initcall_end"),
    ("_platform_initcall_begin", "_platform_initcall_end"),
    ("_module_initcall_begin", "_module_initcall_end"),
    ("platform_uninitcall_begin", "platform_uninitcall_end"),
)


class ValidationError(Exception):
    """The target artifacts differ from the LAB_ONLY panel contract."""


def fail(message: str) -> None:
    raise ValidationError(message)


def read_regular(path: Path, label: str) -> bytes:
    value = Path(path)
    try:
        mode = value.lstat().st_mode
        if not stat.S_ISREG(mode) or stat.S_ISLNK(mode):
            fail(f"{label}: must be a regular non-symlink file")
        return value.read_bytes()
    except OSError as error:
        fail(f"{label}: cannot read: {error}")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _profile(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail("profile must be an object")
    if value.get("profileId") != "E87-1542-LAB-PANEL-SMOKE-H" or value.get("status") != "LAB_ONLY":
        fail("wrong LAB_ONLY profile")
    if value.get("sdkCommit") != "d0167685d032d745d88fe50233302edd46941622":
        fail("SDK commit drift")
    versions = value.get("versions")
    if not isinstance(versions, dict) or versions.get("transportQix") != "11.1.0.4":
        fail("LAB transport version drift")
    boot = value.get("boot")
    if not isinstance(boot, dict) or boot.get("appCoreStackBytes") != 4096:
        fail("LAB app_core stack must be exactly 4096 bytes")
    closure = value.get("targetClosure")
    if not isinstance(closure, dict):
        fail("target closure is absent")
    sources = closure.get("additionalSources")
    if not isinstance(sources, list) or not sources or len(sources) != len(set(sources)):
        fail("additional source closure is invalid")
    archives = closure.get("additionalArchives")
    if not isinstance(archives, list) or len(archives) != 1:
        fail("additional archive closure is invalid")
    archive = archives[0]
    if not isinstance(archive, dict) or archive.get("path") != "cpu/br35/liba/gpu.a" or re.fullmatch(r"[0-9a-f]{64}", str(archive.get("sha256", ""))) is None:
        fail("GPU archive identity is invalid")
    return value


def expected_source_objects(profile: dict[str, Any]) -> list[str]:
    value = _profile(profile)
    added = value["targetClosure"]["additionalSources"]
    converted = []
    for source in added:
        if not isinstance(source, str) or not source.endswith(".c") or source.startswith("/") or ".." in Path(source).parts:
            fail("additional source spelling is invalid")
        converted.append("objs/" + source + ".o")
    return [*BASE_SOURCE_OBJECTS, *converted]


def expected_archive_loads() -> list[str]:
    return [*BASE_ARCHIVES, "cpu/br35/liba/gpu.a", *TOOLCHAIN_ARCHIVES]


def _decode(raw: bytes, label: str) -> str:
    try:
        text = raw.decode("ascii")
    except UnicodeError as error:
        fail(f"{label}: non-ASCII bytes: {error}")
    if "\r" in text or not text.endswith("\n"):
        fail(f"{label}: noncanonical line endings")
    return text


def _live_map(text: str) -> str:
    marker = "\nLinker script and memory map\n"
    if text.count(marker) != 1 or "\nDiscarded input sections\n" not in text:
        fail("map boundaries are invalid")
    return text.split(marker, 1)[1]


def _normalize_archive(path: str) -> str:
    normalized = path.replace("\\", "/")
    match = re.fullmatch(r".*/lib/r3-large/([^/]+\.a)", normalized)
    if match is not None:
        return "toolchain/lib/r3-large/" + match.group(1)
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized):
        fail(f"unknown absolute archive: {path}")
    return normalized


def _loads(live: str) -> list[str]:
    result = []
    for line in live.splitlines():
        if not line.startswith("LOAD "):
            continue
        if re.fullmatch(r"LOAD \S+", line) is None:
            fail("malformed LOAD record")
        result.append(line[5:])
    return result


def _symbol(live: str, name: str) -> int:
    matches = re.findall(
        rf"^[ \t]+(0x[0-9A-Fa-f]+)[ \t]+{re.escape(name)}[ \t]*=",
        live,
        re.M,
    )
    if len(matches) != 1:
        fail(f"memory symbol is missing or repeated: {name}")
    return int(matches[0], 16)


def _resolution_modules(text: str) -> dict[str, dict[str, str]]:
    modules: dict[str, dict[str, str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if not line:
            fail("blank resolution record")
        if not line.startswith("-r="):
            if line in modules:
                fail("duplicate resolution module")
            current = line
            modules[current] = {}
            continue
        if current is None or not line.startswith(f"-r={current},"):
            fail("resolution record/module mismatch")
        payload = line[len(current) + 4 :]
        if "," not in payload:
            fail("malformed resolution record")
        symbol, flags = payload.rsplit(",", 1)
        modules[current][symbol] = flags
    return modules


def _require_resolution(modules: dict[str, dict[str, str]], suffix: str, symbol: str) -> None:
    provider = modules.get("objs/apps/watch/log_config/app_config.c.o", {}).get(symbol, "")
    requesters = [flags.get(symbol, "") for name, flags in modules.items() if re.fullmatch(rf"cpu/br35/liba/gpu\.a\.llvm\.\d+\.{re.escape(suffix)}", name)]
    if "p" not in provider:
        fail(f"UI log provider differs for {symbol}")
    if len(requesters) != 1 or "l" not in requesters[0]:
        fail(f"GPU requester differs for {symbol}")


def validate_projection(
    map_bytes: bytes,
    object_list_bytes: bytes,
    resolution_bytes: bytes,
    profile: dict[str, Any],
) -> dict[str, int]:
    value = _profile(profile)
    expected_sources = expected_source_objects(value)
    expected_objects = (" " + " ".join(expected_sources) + "\n").encode("ascii")
    if object_list_bytes != expected_objects:
        fail("source object list differs from exact LAB allowlist")

    text = _decode(map_bytes, "map")
    live = _live_map(text)
    loads = _loads(live)
    if loads.count("cpu/br35/tools/sdk.elf.o") != 1:
        fail("generated LTO object must be loaded exactly once")
    sources = [item for item in loads if item.startswith("objs/")]
    if sources != expected_sources:
        fail("source object LOAD order differs from exact LAB allowlist")
    archives = [_normalize_archive(item) for item in loads if item.endswith(".a")]
    if archives != expected_archive_loads():
        fail("archive LOAD order differs from exact LAB allowlist")

    if not re.search(
        r"^cpu/br35/liba/gpu\.a\(dbi\.c\.o\)\s+"
        r"objs/apps/watch/e87/e87_panel_jd9855\.c\.o "
        r"\(symbol from plugin\) \(lcd_set_align\)$",
        text,
        re.M,
    ):
        fail("GPU DBI provenance differs")

    memory = value["memory"]
    expected_symbols = {
        "_RAM_LIMIT_H": 0x137000,
        "UPDATA_BEG": 0x136E00,
        "PSRAM_SIZE": 0,
        "_HEAP_END": memory["bufferStart"],
        "_E87_LCD_RESERVED_START": memory["reservedStart"],
        "_E87_LCD_BUFFER_START": memory["bufferStart"],
        "_E87_LCD_BUFFER_END": memory["bufferEnd"],
        "_E87_LCD_RESERVED_END": memory["reservedEnd"],
    }
    for name, expected in expected_symbols.items():
        if _symbol(live, name) != expected:
            fail(f"memory symbol differs: {name}")
    if memory["bufferStart"] - _symbol(live, "_HEAP_BEGIN") < memory["minimumHeapBytes"]:
        fail("heap is below the LAB minimum")
    for begin, end in INITCALL_RANGES:
        if _symbol(live, begin) != _symbol(live, end):
            fail(f"generic initcall range is live: {begin}")

    lcd = re.findall(
        r"^ \.e87_lcd_buffer\n[ \t]+0x([0-9A-Fa-f]+)[ \t]+0x([0-9A-Fa-f]+)[ \t]+"
        r"cpu/br35/tools/sdk\.elf\.o$",
        live,
        re.M,
    )
    if len(lcd) != 1 or tuple(int(item, 16) for item in lcd[0]) != (memory["bufferStart"], memory["bufferBytes"]):
        fail("LCD buffer input section differs from exact serial allocation")

    for symbol in FORBIDDEN_LIVE_SYMBOLS:
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", live):
            fail(f"forbidden symbol is live: {symbol}")
    if "OUTPUT(cpu/br35/tools/sdk.elf elf32-pi32v2)" not in live:
        fail("wrong ELF output identity")

    modules = _resolution_modules(_decode(resolution_bytes, "resolution"))
    _require_resolution(modules, "dbi.c", "log_tag_const_d_UI")
    _require_resolution(modules, "dbi_mcu.c", "log_tag_const_i_UI")
    return {
        "appCoreStackBytes": value["boot"]["appCoreStackBytes"],
        "archiveCount": len(archives),
        "lcdBufferBytes": memory["bufferBytes"],
        "sourceObjectCount": len(sources),
    }


def _decode_profile(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeError, json.JSONDecodeError) as error:
        fail(f"profile is invalid JSON: {error}")
    return _profile(value)


def _validate_elf(raw: bytes) -> None:
    if len(raw) < 52 or raw[:7] != b"\x7fELF\x01\x01\x01":
        fail("ELF is not little-endian ELF32")
    machine = struct.unpack_from("<H", raw, 18)[0]
    entry = struct.unpack_from("<I", raw, 24)[0]
    if machine != 0xF1 or entry != 0x0C000100:
        fail("ELF is not the expected PI32v2 target")


def validate_artifacts(
    *,
    map_path: Path,
    elf_path: Path,
    object_list_path: Path,
    resolution_path: Path,
    profile_path: Path,
    sdk_root: Path,
    repository_root: Path,
) -> dict[str, int]:
    profile = _decode_profile(read_regular(profile_path, "profile"))
    _validate_elf(read_regular(elf_path, "ELF"))
    root = Path(sdk_root).resolve(strict=True)
    if not root.is_dir():
        fail("SDK root must be a directory")
    archive = profile["targetClosure"]["additionalArchives"][0]
    gpu = root / archive["path"]
    if sha256(read_regular(gpu, "GPU archive")) != archive["sha256"]:
        fail("GPU archive digest differs")
    repo = Path(repository_root).resolve(strict=True)
    for mapping in profile.get("generatedOverlayMappings", []):
        if not isinstance(mapping, dict):
            fail("generated overlay mapping is invalid")
        source = repo / str(mapping.get("source", ""))
        if sha256(read_regular(source, "generated overlay")) != mapping.get("sha256"):
            fail("generated overlay digest differs")
    return validate_projection(
        read_regular(map_path, "map"),
        read_regular(object_list_path, "object list"),
        read_regular(resolution_path, "resolution"),
        profile,
    )


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--map", required=True, type=Path)
    parser.add_argument("--elf", required=True, type=Path)
    parser.add_argument("--object-list", required=True, type=Path)
    parser.add_argument("--resolution", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--sdk-root", required=True, type=Path)
    parser.add_argument("--repository-root", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_arguments(argv)
    try:
        result = validate_artifacts(
            map_path=args.map,
            elf_path=args.elf,
            object_list_path=args.object_list,
            resolution_path=args.resolution,
            profile_path=args.profile,
            sdk_root=args.sdk_root,
            repository_root=args.repository_root,
        )
    except ValidationError as error:
        print(f"LAB PANEL MAP INVALID: {error}", file=sys.stderr)
        return 1
    print(
        "LAB PANEL MAP OK: "
        f"{result['sourceObjectCount']} sources, {result['archiveCount']} archive loads, "
        f"0x{result['lcdBufferBytes']:X} serial buffer, "
        f"{result['appCoreStackBytes']} byte app_core stack"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
