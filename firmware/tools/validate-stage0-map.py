#!/usr/bin/env python3
"""Validate an E87 Stage 0 ELF, map, archive bytes, and link provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
import sys
from typing import Any


DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
BUILD_TAG_RE = re.compile(r"^[0-9A-F]{8}$")
TOOLCHAIN_SUFFIX_RE = re.compile(r"^.*/lib/r3-large/([^/]+\.a)$")
DISCARDED_SECTIONS_MARKER = "\nDiscarded input sections\n"
LINKER_MEMORY_MAP_MARKER = "\nLinker script and memory map\n"
PRODUCTION_EVIDENCE_SHA256 = (
    "b4dc989996ab016a3c37799a6913fcecfc66fe9f53d60f1f33752ce7961b2dd1"
)
PRODUCTION_EVIDENCE_ID = "E87-S0-LINK-CLOSURE"
TEST_EVIDENCE_ID = "TEST-E87-S0-LINK-CLOSURE"
PRODUCTION_SOURCE_OBJECTS = (
    "objs/apps/common/debug/debug.c.o",
    "objs/apps/common/debug/debug_uart_config.c.o",
    "objs/apps/common/perf_counter/perf_counter.c.o",
    "objs/apps/common/update/update.c.o",
    "objs/apps/watch/app_main.c.o",
    "objs/apps/watch/board/br35/board_e87_1542/board_e87_1542.c.o",
    "objs/apps/watch/e87/e87_stage0_adv.c.o",
    "objs/apps/watch/e87/e87_stage0_app.c.o",
    "objs/apps/watch/e87/e87_stage0_ble.c.o",
    "objs/apps/watch/e87/e87_stage0_platform_config.c.o",
    "objs/apps/watch/log_config/app_config.c.o",
    "objs/apps/watch/log_config/lib_btctrler_config.c.o",
    "objs/apps/watch/log_config/lib_btstack_config.c.o",
    "objs/apps/watch/log_config/lib_driver_config.c.o",
    "objs/apps/watch/log_config/lib_system_config.c.o",
    "objs/cpu/br35/power/power_app.c.o",
    "objs/cpu/br35/setup.c.o",
    "objs/cpu/config/lib_power_config.c.o",
    "objs/cpu/power/msg.c.o",
)
PRODUCTION_ARCHIVES = (
    (
        "cpu/br35/liba/cpu.a",
        "787b6fc0913a0a8a634ee8c7606d5e4a68dc5604d8feacf806fd60dc1e2fc8ca",
    ),
    (
        "cpu/br35/liba/system.a",
        "3b00ce29bf38c11707554449f6a4d9afaebc267ca9cba3dde8f7f8d0f4f09141",
    ),
    (
        "cpu/br35/liba/btstack.a",
        "4a5c48ba0658647ecde1a59c7032448eeda1bdfe4a3899dd14903b5d75e8347d",
    ),
    (
        "cpu/br35/liba/btctrler.a",
        "7b6d18d9589aa5990731cd7a92124b2ba1d9330b71359938eb9a711da15b1f2e",
    ),
    (
        "cpu/br35/liba/libc.a",
        "f7d8d0b20e688ab682864face6ddec8e6fa87bf5c8c7dfd527d4c42257e0fb64",
    ),
    (
        "cpu/br35/liba/cbuf.a",
        "03740c7da23a02570ed618b144eca607373ae8debb374ed15e3c3840ad0e3bb8",
    ),
    (
        "cpu/br35/liba/cfg_tool.a",
        "545df929e1e05c17e978156a3a959cb07744bbecceef30b305f96606b21e2f04",
    ),
    (
        "cpu/br35/liba/crypto_toolbox_Osize.a",
        "b16901cea79a369ad5f8db918c7799b5965b3013be986f31f24e5cc09c607b8f",
    ),
    (
        "cpu/br35/liba/device.a",
        "e6cad5ce44970000c1631275f6b2175a7c68a0f191a2c66af8dee4c0d9f8fb3e",
    ),
    (
        "cpu/br35/liba/fs.a",
        "61251cf9ba9e654247004be2af7debf555779ea3021eac464802c197864dbe53",
    ),
    (
        "cpu/br35/liba/lib_ccm_cipher.a",
        "bb3accd5d94fe58e61dcfeff2fb73eeeebc7a129fbeb5f474b5eb6c9d7cb43d2",
    ),
    (
        "cpu/br35/liba/printf.a",
        "58cef0141f5220726a16fcd7b23d672a402ea6ce77156039404d4703d750bfef",
    ),
    (
        "cpu/br35/liba/vm.a",
        "bebc7934c785e75da2cb216a6150992126798a7abfd3936c500add6ee46f9900",
    ),
    (
        "toolchain/lib/r3-large/libm.a",
        "96bc6239ab76d5f7186781bc5612534c05dc1b49a2bb4ec4b1c2a160447d3816",
    ),
    (
        "toolchain/lib/r3-large/libc.a",
        "9421760d0e9e8fdc283d8a2bbb9754aa3a846cafe98974b91d14b30f4d2a23a3",
    ),
    (
        "toolchain/lib/r3-large/libcompiler-rt.a",
        "d91de93147d28e47deb9537c7b7b8d9d01ce7d1640eee955e2ae344d7107a6b0",
    ),
)
PRODUCTION_ARCHIVE_LOAD_ORDER = (
    "cpu/br35/liba/cpu.a",
    "cpu/br35/liba/system.a",
    "cpu/br35/liba/btstack.a",
    "cpu/br35/liba/btctrler.a",
    "cpu/br35/liba/libc.a",
    "cpu/br35/liba/cbuf.a",
    "cpu/br35/liba/cfg_tool.a",
    "cpu/br35/liba/crypto_toolbox_Osize.a",
    "cpu/br35/liba/device.a",
    "cpu/br35/liba/fs.a",
    "cpu/br35/liba/lib_ccm_cipher.a",
    "cpu/br35/liba/printf.a",
    "cpu/br35/liba/vm.a",
    "toolchain/lib/r3-large/libm.a",
    "toolchain/lib/r3-large/libc.a",
    "toolchain/lib/r3-large/libm.a",
    "toolchain/lib/r3-large/libcompiler-rt.a",
)
PRODUCTION_REQUIRED_PROVENANCE = (
    (
        "cpu/br35/liba/btstack.a(btstack_task.c.o)",
        "O:objs/apps/watch/e87/e87_stage0_app.c.o",
        "btstack_init",
    ),
    (
        "cpu/br35/liba/btstack.a(btstack_main.c.o)",
        "A:cpu/br35/liba/btstack.a(btstack_task.c.o)",
        "btstack_mem_init",
    ),
    (
        "cpu/br35/liba/btctrler.a(RF.c.o)",
        "O:objs/apps/watch/e87/e87_stage0_app.c.o",
        "bt_pll_para",
    ),
)


class ValidationError(Exception):
    """The supplied artifact does not satisfy the closed Stage 0 contract."""


def fail(message: str) -> None:
    raise ValidationError(message)


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def exact_keys(value: object, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{label}: must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        fail(f"{label}: keys differ; missing={missing} unknown={unknown}")
    return value


def ascii_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.isascii():
        fail(f"{label}: must be an ASCII string")
    return value


def integer(value: object, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        fail(f"{label}: invalid integer")
    return value


def digest(value: object, label: str) -> str:
    result = ascii_string(value, label)
    if DIGEST_RE.fullmatch(result) is None:
        fail(f"{label}: must be lowercase 64-hex")
    return result


def commit(value: object, label: str) -> str:
    result = ascii_string(value, label)
    if COMMIT_RE.fullmatch(result) is None:
        fail(f"{label}: must be lowercase 40-hex")
    return result


def posix_relative(value: object, label: str) -> str:
    result = ascii_string(value, label)
    path = PurePosixPath(result)
    if (
        not result
        or result.startswith(("/", "//"))
        or "\\" in result
        or ":" in result
        or str(path) != result
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        fail(f"{label}: must be a canonical relative POSIX path")
    return result


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def graph_digest(rows: list[str]) -> str:
    return sha256("".join(rows).encode("ascii"))


def read_regular(path: Path, label: str) -> bytes:
    try:
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode) or stat.S_ISLNK(mode):
            fail(f"{label}: must be a regular non-symlink file")
        return path.read_bytes()
    except OSError as error:
        fail(f"{label}: cannot read: {error}")


def decode_evidence(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=reject_duplicate_keys)
    except ValidationError:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        fail(f"evidence: invalid JSON: {error}")
    root = exact_keys(
        value,
        {
            "schemaVersion",
            "evidenceId",
            "sdkCommit",
            "clangVersion",
            "qualificationArtifact",
            "sourceObjects",
            "archives",
            "archiveLoadOrder",
            "mapContract",
            "policy",
        },
        "evidence",
    )
    if root["schemaVersion"] != 1:
        fail("evidence.schemaVersion: unsupported")
    ascii_string(root["evidenceId"], "evidence.evidenceId")
    commit(root["sdkCommit"], "evidence.sdkCommit")
    ascii_string(root["clangVersion"], "evidence.clangVersion")

    artifact = exact_keys(
        root["qualificationArtifact"],
        {
            "sourceCommit",
            "buildTag",
            "elfSha256",
            "elfSize",
            "mapSha256",
            "mapSize",
            "resolutionSha256",
            "resolutionSize",
            "objectListSha256",
            "objectListSize",
            "appBinSha256",
            "appBinSize",
            "linkLogSha256",
            "buildMode",
            "postLinkStatus",
        },
        "qualificationArtifact",
    )
    source_commit = commit(artifact["sourceCommit"], "sourceCommit")
    build_tag = ascii_string(artifact["buildTag"], "buildTag")
    if BUILD_TAG_RE.fullmatch(build_tag) is None:
        fail("buildTag: must be 8 uppercase hex")
    if build_tag != source_commit[:8].upper():
        fail("buildTag: does not match sourceCommit")
    for name in (
        "elfSha256",
        "mapSha256",
        "resolutionSha256",
        "objectListSha256",
        "appBinSha256",
        "linkLogSha256",
    ):
        digest(artifact[name], name)
    for name in (
        "elfSize",
        "mapSize",
        "resolutionSize",
        "objectListSize",
        "appBinSize",
    ):
        integer(artifact[name], name, 1)
    if artifact["buildMode"] != "VENDOR_MAKE_EXPLICIT_LINK_TARGET_NO_POST":
        fail("buildMode: unsupported qualification mode")
    if artifact["postLinkStatus"] != "NOT_INVOKED_BY_EXPLICIT_LINK_TARGET":
        fail("postLinkStatus: unsupported qualification state")

    sources = root["sourceObjects"]
    if not isinstance(sources, list) or not sources:
        fail("sourceObjects: must be a nonempty list")
    source_values = [posix_relative(item, "sourceObjects[]") for item in sources]
    if len(source_values) != len(set(source_values)):
        fail("sourceObjects: duplicate")
    if any(not item.startswith("objs/") or not item.endswith(".o") for item in source_values):
        fail("sourceObjects: invalid object spelling")

    archives = root["archives"]
    if not isinstance(archives, list) or not archives:
        fail("archives: must be a nonempty list")
    archive_paths: list[str] = []
    for index, item in enumerate(archives):
        archive = exact_keys(item, {"path", "sha256", "role"}, f"archives[{index}]")
        path = posix_relative(archive["path"], f"archives[{index}].path")
        if not path.endswith(".a"):
            fail(f"archives[{index}].path: must name an archive")
        digest(archive["sha256"], f"archives[{index}].sha256")
        ascii_string(archive["role"], f"archives[{index}].role")
        archive_paths.append(path)
    if len(archive_paths) != len(set(archive_paths)):
        fail("archives: duplicate path")

    order = root["archiveLoadOrder"]
    if not isinstance(order, list) or not order:
        fail("archiveLoadOrder: must be a nonempty list")
    order_values = [posix_relative(item, "archiveLoadOrder[]") for item in order]
    if set(order_values) != set(archive_paths):
        fail("archiveLoadOrder: does not cover exact archive set")

    contract = exact_keys(
        root["mapContract"],
        {
            "archiveInclusionRowCount",
            "archiveInclusionRowsSha256",
            "btstackObjectCount",
            "btstackObjectsSha256",
            "btctrlerObjectCount",
            "btctrlerObjectsSha256",
            "requiredProvenance",
            "disabledUpdate",
        },
        "mapContract",
    )
    for name in (
        "archiveInclusionRowCount",
        "btstackObjectCount",
        "btctrlerObjectCount",
    ):
        integer(contract[name], name)
    for name in (
        "archiveInclusionRowsSha256",
        "btstackObjectsSha256",
        "btctrlerObjectsSha256",
    ):
        digest(contract[name], name)
    provenance = contract["requiredProvenance"]
    if not isinstance(provenance, list) or not provenance:
        fail("requiredProvenance: must be a nonempty list")
    for index, item in enumerate(provenance):
        edge = exact_keys(
            item,
            {"archiveMember", "referrer", "symbol"},
            f"requiredProvenance[{index}]",
        )
        ascii_string(edge["archiveMember"], "archiveMember")
        ascii_string(edge["referrer"], "referrer")
        ascii_string(edge["symbol"], "symbol")
    update = exact_keys(
        contract["disabledUpdate"],
        {"sourceObject", "section", "size", "symbol"},
        "disabledUpdate",
    )
    if update["sourceObject"] not in source_values:
        fail("disabledUpdate.sourceObject: not an exact source object")
    ascii_string(update["section"], "disabledUpdate.section")
    integer(update["size"], "disabledUpdate.size", 1)
    ascii_string(update["symbol"], "disabledUpdate.symbol")

    policy = exact_keys(
        root["policy"],
        {
            "runtimeGatedVendorObjects",
            "immutableBootSeamArchives",
            "applicationFilesystemRoute",
            "forbiddenArchives",
            "forbiddenSourceObjects",
        },
        "policy",
    )
    if policy["runtimeGatedVendorObjects"] != (
        "ALLOWED_ONLY_FROM_EXACT_PINNED_BTSTACK_AND_BTCTRLR_ARCHIVES"
    ):
        fail("runtimeGatedVendorObjects: unsupported")
    if policy["applicationFilesystemRoute"] != "FORBIDDEN":
        fail("applicationFilesystemRoute: must be FORBIDDEN")
    for name in (
        "immutableBootSeamArchives",
        "forbiddenArchives",
        "forbiddenSourceObjects",
    ):
        items = policy[name]
        if not isinstance(items, list):
            fail(f"{name}: must be a list")
        values = [posix_relative(item, f"{name}[]") for item in items]
        if len(values) != len(set(values)):
            fail(f"{name}: duplicate")
    return root


def production_contract_is_exact(evidence: dict[str, Any]) -> bool:
    archives = tuple(
        (item["path"], item["sha256"]) for item in evidence["archives"]
    )
    provenance = tuple(
        (item["archiveMember"], item["referrer"], item["symbol"])
        for item in evidence["mapContract"]["requiredProvenance"]
    )
    return (
        evidence["evidenceId"] == PRODUCTION_EVIDENCE_ID
        and tuple(evidence["sourceObjects"]) == PRODUCTION_SOURCE_OBJECTS
        and archives == PRODUCTION_ARCHIVES
        and tuple(evidence["archiveLoadOrder"])
        == PRODUCTION_ARCHIVE_LOAD_ORDER
        and provenance == PRODUCTION_REQUIRED_PROVENANCE
        and len(PRODUCTION_SOURCE_OBJECTS) == 19
        and len(PRODUCTION_ARCHIVES) == 16
        and len(PRODUCTION_REQUIRED_PROVENANCE) == 3
    )


def authorized_evidence(
    raw: bytes,
    accept_untrusted_test_evidence: bool,
) -> dict[str, Any]:
    if (
        not accept_untrusted_test_evidence
        and sha256(raw) != PRODUCTION_EVIDENCE_SHA256
    ):
        fail("evidence: bytes differ from exact committed production evidence")
    evidence = decode_evidence(raw)
    if accept_untrusted_test_evidence:
        if evidence["evidenceId"] != TEST_EVIDENCE_ID:
            fail("test-only untrusted evidence must use the exact test evidence ID")
    elif not production_contract_is_exact(evidence):
        fail("evidence: contract differs from exact committed production evidence")
    return evidence


def normalize_archive(path: str) -> str:
    is_absolute = path.startswith("/") or re.match(r"^[A-Za-z]:/", path) is not None
    if not is_absolute:
        return posix_relative(path, "map archive")
    match = TOOLCHAIN_SUFFIX_RE.fullmatch(path)
    if match is None:
        fail(f"map archive: unrecognized absolute path {path}")
    return f"toolchain/lib/r3-large/{match.group(1)}"


def inclusion_archive(path: str) -> str:
    normalized = path.replace("\\", "/")
    match = TOOLCHAIN_SUFFIX_RE.fullmatch(normalized)
    if match is not None and (
        normalized.startswith("/")
        or re.match(r"^[A-Za-z]:/", normalized) is not None
    ):
        return f"TOOLCHAIN/lib/r3-large/{match.group(1)}"
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized):
        fail(f"map inclusion graph: unrecognized absolute archive {path}")
    result = posixpath.normpath(normalized)
    if result != normalized or result.startswith("../") or result == "..":
        fail(f"map inclusion graph: noncanonical archive {path}")
    return result


def typed_parent(
    raw: str,
    prior_archive_nodes: dict[str, list[str]],
) -> str:
    archive_match = re.fullmatch(r"(\S+\.a)\(([^()]+)\)", raw)
    if archive_match is not None:
        return (
            f"A:{inclusion_archive(archive_match.group(1))}"
            f"({archive_match.group(2)})"
        )
    if "/" in raw or "\\" in raw or re.match(r"^[A-Za-z]:", raw):
        normalized = raw.replace("\\", "/")
        if normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized):
            fail(f"map inclusion graph: unrecognized direct object {raw}")
        result = posixpath.normpath(normalized)
        if result != normalized or result.startswith("../") or result == "..":
            fail(f"map inclusion graph: noncanonical direct object {raw}")
        return f"O:{result}"
    candidates = prior_archive_nodes.get(raw, [])
    if len(candidates) != 1:
        fail(
            "map inclusion graph: bare requester is not one exact prior "
            f"archive member: {raw}"
        )
    return f"A:{candidates[0]}"


def inclusion_entries(
    text: str,
) -> tuple[list[str], dict[str, tuple[str, str, int]]]:
    if DISCARDED_SECTIONS_MARKER not in text:
        fail("map: missing inclusion-table terminator")
    block = text.split(DISCARDED_SECTIONS_MARKER, 1)[0]
    lines = block.splitlines()
    if not lines or lines[0] != "Archive member included to satisfy reference by file (symbol)":
        fail("map inclusion graph: missing exact heading")
    rows: list[str] = []
    reasons: dict[str, tuple[str, str, int]] = {}
    prior_archive_nodes: dict[str, list[str]] = {}
    index = 1
    while index < len(lines):
        line = lines[index]
        if not line:
            index += 1
            continue
        match = re.match(r"^(\S+\.a)\(([^)]+)\)(?:\s+(.*))?$", line)
        if match is None:
            fail(f"map inclusion graph: unknown record at line {index + 1}")
        archive = inclusion_archive(match.group(1))
        row = f"{archive}({match.group(2)})"
        if row in reasons:
            fail(f"map inclusion graph: duplicate {row}")
        reason = (match.group(3) or "").strip()
        if not reason:
            if index + 1 >= len(lines) or not lines[index + 1].startswith((" ", "\t")):
                fail(f"map inclusion graph: missing cause for {row}")
            index += 1
            reason = lines[index].strip()
        reason_match = re.fullmatch(
            r"(.+?)(\s+\(symbol from plugin\))?\s+\(([^()]*)\)", reason
        )
        if reason_match is None:
            fail(f"map provenance: malformed reason for {row}")
        parent = typed_parent(reason_match.group(1), prior_archive_nodes)
        plugin = 1 if reason_match.group(2) is not None else 0
        symbol = reason_match.group(3)
        rows.append(f"{row}\t{parent}\t{symbol}\t{plugin}\n")
        reasons[row] = (parent, symbol, plugin)
        prior_archive_nodes.setdefault(match.group(2), []).append(row)
        index += 1
    if not rows:
        fail("map inclusion graph: empty")
    return rows, reasons


def live_linker_memory_map(text: str) -> str:
    if text.count(DISCARDED_SECTIONS_MARKER) != 1:
        fail("map: expected exactly one discarded-sections boundary")
    after_discarded = text.split(DISCARDED_SECTIONS_MARKER, 1)[1]
    if after_discarded.count(LINKER_MEMORY_MAP_MARKER) != 1:
        fail("map: expected exactly one live linker-memory-map boundary")
    return after_discarded.split(LINKER_MEMORY_MAP_MARKER, 1)[1]


def load_entries(live_map: str) -> list[str]:
    loads: list[str] = []
    for line_number, line in enumerate(live_map.splitlines(), 1):
        if re.match(r"^\s*LOAD(?:\s|$)", line) is None:
            continue
        match = re.fullmatch(r"LOAD ([^\s]+)", line)
        if match is None:
            fail(f"map: malformed LOAD record at live-map line {line_number}")
        loads.append(match.group(1))
    return loads


def resolution_modules(text: str) -> dict[str, dict[str, str]]:
    if "\r" in text or not text.endswith("\n"):
        fail("resolution: noncanonical line endings")
    modules: dict[str, dict[str, str]] = {}
    current: str | None = None
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line:
            fail(f"resolution: blank line at {line_number}")
        if not line.startswith("-r="):
            if line in modules:
                fail(f"resolution: duplicate module {line}")
            current = line
            modules[current] = {}
            continue
        if current is None:
            fail("resolution: record before module")
        prefix = f"-r={current},"
        if not line.startswith(prefix):
            fail(f"resolution: record/module mismatch at {line_number}")
        payload = line[len(prefix):]
        if "," not in payload:
            fail(f"resolution: malformed record at {line_number}")
        symbol, flags = payload.rsplit(",", 1)
        if not symbol or symbol in modules[current] or not flags.isascii():
            fail(f"resolution: duplicate or malformed symbol at {line_number}")
        modules[current][symbol] = flags
    return modules


def archive_resolution_module(
    archive_member: str,
    modules: dict[str, dict[str, str]],
) -> str:
    match = re.fullmatch(r"(.+\.a)\(([^()]+)\.o\)", archive_member)
    if match is None or archive_member.startswith("TOOLCHAIN/"):
        fail(f"resolution: unsupported required archive member {archive_member}")
    pattern = re.compile(
        rf"^{re.escape(match.group(1))}\.llvm\.\d+\."
        rf"{re.escape(match.group(2))}$"
    )
    candidates = [name for name in modules if pattern.fullmatch(name)]
    if len(candidates) != 1:
        fail(f"resolution: required archive module is ambiguous: {archive_member}")
    return candidates[0]


def resolve_archive(
    path: str,
    sdk_root: Path,
    toolchain_root: Path,
) -> Path:
    if path.startswith("toolchain/"):
        root = toolchain_root.resolve(strict=True)
        relative = path.removeprefix("toolchain/")
    else:
        root = sdk_root.resolve(strict=True)
        relative = path
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        fail(f"archive path escapes or is missing: {path}: {error}")
    return resolved


def validate_artifacts(
    map_path: Path,
    elf_path: Path,
    resolution_path: Path,
    object_list_path: Path,
    app_bin_path: Path,
    evidence_path: Path,
    sdk_root: Path,
    toolchain_root: Path,
    accept_untrusted_test_evidence: bool = False,
) -> tuple[int, int]:
    evidence = authorized_evidence(
        read_regular(evidence_path, "evidence"),
        accept_untrusted_test_evidence,
    )
    artifact = evidence["qualificationArtifact"]
    map_raw = read_regular(map_path, "map")
    if len(map_raw) != artifact["mapSize"] or sha256(map_raw) != artifact["mapSha256"]:
        fail("map digest or size differs from qualification artifact")
    elf_raw = read_regular(elf_path, "ELF")
    if len(elf_raw) != artifact["elfSize"] or sha256(elf_raw) != artifact["elfSha256"]:
        fail("ELF digest or size differs from qualification artifact")
    resolution_raw = read_regular(resolution_path, "resolution")
    if (
        len(resolution_raw) != artifact["resolutionSize"]
        or sha256(resolution_raw) != artifact["resolutionSha256"]
    ):
        fail("resolution digest or size differs from qualification artifact")
    object_list_raw = read_regular(object_list_path, "object list")
    if (
        len(object_list_raw) != artifact["objectListSize"]
        or sha256(object_list_raw) != artifact["objectListSha256"]
    ):
        fail("object list digest or size differs from qualification artifact")
    app_bin_raw = read_regular(app_bin_path, "app.bin")
    if (
        len(app_bin_raw) != artifact["appBinSize"]
        or sha256(app_bin_raw) != artifact["appBinSha256"]
    ):
        fail("app.bin digest or size differs from qualification artifact")
    try:
        text = map_raw.decode("ascii")
    except UnicodeError as error:
        fail(f"map: non-ASCII bytes: {error}")
    if "\r" in text or not text.endswith("\n"):
        fail("map: noncanonical line endings")

    policy = evidence["policy"]
    live_map = live_linker_memory_map(text)
    loads = load_entries(live_map)
    if loads.count("cpu/br35/tools/sdk.elf.o") != 1:
        fail("map: generated LTO object LOAD must appear exactly once")
    source_loads = [item for item in loads if item.startswith("objs/")]
    for forbidden in policy["forbiddenSourceObjects"]:
        if forbidden in source_loads:
            fail(f"forbidden source object loaded: {forbidden}")
    if source_loads != evidence["sourceObjects"]:
        fail("source object LOAD order differs from exact allowlist")
    expected_object_list = (
        " " + " ".join(evidence["sourceObjects"]) + "\n"
    ).encode("ascii")
    if object_list_raw != expected_object_list:
        fail("object list bytes differ from exact source allowlist")

    archive_loads = [normalize_archive(item) for item in loads if item.endswith(".a")]
    for forbidden in policy["forbiddenArchives"]:
        if forbidden in archive_loads:
            fail(f"forbidden archive loaded: {forbidden}")
    if archive_loads != evidence["archiveLoadOrder"]:
        fail("archive LOAD order differs from exact allowlist")
    other_loads = [
        item
        for item in loads
        if not item.startswith("objs/")
        and not item.endswith(".a")
        and item != "cpu/br35/tools/sdk.elf.o"
    ]
    if other_loads:
        fail(f"unexpected non-archive LOAD entry: {other_loads[0]}")

    archive_records = {item["path"]: item for item in evidence["archives"]}
    for path, record in archive_records.items():
        raw = read_regular(
            resolve_archive(path, sdk_root, toolchain_root),
            f"archive {path}",
        )
        if sha256(raw) != record["sha256"]:
            fail(f"archive digest differs: {path}")

    rows, reasons = inclusion_entries(text)
    contract = evidence["mapContract"]
    if (
        len(rows) != contract["archiveInclusionRowCount"]
        or graph_digest(rows) != contract["archiveInclusionRowsSha256"]
    ):
        fail("archive inclusion graph differs from exact qualified set")
    btstack_rows = [
        row for row in rows if row.startswith("cpu/br35/liba/btstack.a(")
    ]
    if (
        len(btstack_rows) != contract["btstackObjectCount"]
        or graph_digest(btstack_rows) != contract["btstackObjectsSha256"]
    ):
        fail("btstack inclusion graph differs from pinned runtime-gated set")
    btctrler_rows = [
        row for row in rows if row.startswith("cpu/br35/liba/btctrler.a(")
    ]
    if (
        len(btctrler_rows) != contract["btctrlerObjectCount"]
        or graph_digest(btctrler_rows) != contract["btctrlerObjectsSha256"]
    ):
        fail("btctrler inclusion graph differs from pinned controller set")
    try:
        resolution_text = resolution_raw.decode("ascii")
    except UnicodeError as error:
        fail(f"resolution: non-ASCII bytes: {error}")
    modules = resolution_modules(resolution_text)
    for edge in contract["requiredProvenance"]:
        actual = reasons.get(edge["archiveMember"])
        if actual is None or actual[:2] != (edge["referrer"], edge["symbol"]):
            fail(f"required provenance edge differs: {edge['archiveMember']}")
        parent = edge["referrer"]
        if parent.startswith("O:"):
            parent_module = parent.removeprefix("O:")
        elif parent.startswith("A:"):
            parent_module = archive_resolution_module(
                parent.removeprefix("A:"), modules
            )
        else:
            fail(f"required provenance referrer is untyped: {parent}")
        child_module = archive_resolution_module(edge["archiveMember"], modules)
        if "l" not in modules.get(parent_module, {}).get(edge["symbol"], ""):
            fail(f"resolution: required reference is absent: {edge['symbol']}")
        if "p" not in modules.get(child_module, {}).get(edge["symbol"], ""):
            fail(f"resolution: required provider is absent: {edge['symbol']}")

    update = contract["disabledUpdate"]
    section = re.escape(update["section"])
    symbol = re.escape(update["symbol"])
    matches = re.findall(
        rf"^\s*{section}\s+0x[0-9a-fA-F]+\s+0x([0-9a-fA-F]+)\s+"
        rf"cpu/br35/tools/sdk\.elf\.o\n"
        rf"\s+0x[0-9a-fA-F]+\s+{symbol}\s*$",
        live_map,
        re.M,
    )
    if len(matches) != 1 or int(matches[0], 16) != update["size"]:
        fail("disabled update exception differs from exact inert symbol")
    provider_flags = modules.get(update["sourceObject"], {}).get(
        update["symbol"], ""
    )
    if "p" not in provider_flags:
        fail("disabled update provider differs from exact source object")
    if "OUTPUT(cpu/br35/tools/sdk.elf elf32-pi32v2)" not in live_map:
        fail("map: missing exact Stage 0 ELF output")
    return len(rows), len(source_loads)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", required=True, type=Path)
    parser.add_argument("--elf", required=True, type=Path)
    parser.add_argument("--resolution", required=True, type=Path)
    parser.add_argument("--object-list", required=True, type=Path)
    parser.add_argument("--app-bin", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--sdk-root", required=True, type=Path)
    parser.add_argument("--toolchain-root", required=True, type=Path)
    parser.add_argument(
        "--test-only-accept-untrusted-evidence",
        action="store_true",
        help=(
            "TESTS ONLY: accept self-authored evidence with the exact test "
            "evidence ID; never use for production qualification"
        ),
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        rows, sources = validate_artifacts(
            arguments.map,
            arguments.elf,
            arguments.resolution,
            arguments.object_list,
            arguments.app_bin,
            arguments.evidence,
            arguments.sdk_root,
            arguments.toolchain_root,
            arguments.test_only_accept_untrusted_evidence,
        )
    except ValidationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"stage0 link map qualified: {sources} sources, {rows} archive members")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
