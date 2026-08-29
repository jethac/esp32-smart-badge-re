#!/usr/bin/env python3
"""Validate an E87 full-substrate ELF, map, LTO object, and provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
import sys
import tempfile
from typing import Any


DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
TOOLCHAIN_SUFFIX_RE = re.compile(r"^.*/lib/r3-large/([^/]+\.a)$")
DISCARDED_SECTIONS_MARKER = "\nDiscarded input sections\n"
LINKER_MEMORY_MAP_MARKER = "\nLinker script and memory map\n"
PRODUCTION_EVIDENCE_SHA256 = "771be3bdd47451552d37df798f09071035347e8d4504402613f6331b472f2a61"
PRODUCTION_EVIDENCE_ID = "E87-FULL-RUNTIME-NORMAL-BLE-LINK-CLOSURE"
CANDIDATE_EVIDENCE_ID = "CANDIDATE-E87-FULL-RUNTIME-NORMAL-BLE-LINK-CLOSURE"
TEST_EVIDENCE_ID = "TEST-E87-FULL-RUNTIME-NORMAL-BLE-LINK-CLOSURE"

NORMAL_BLE_SOURCE_OBJECTS = (
    "objs/apps/watch/e87/e87_ble_target.c.o",
    "objs/apps/watch/e87/e87_ble_target_journal.c.o",
    "objs/apps/watch/e87/e87_ble_target_platform_config.c.o",
    "objs/apps/watch/e87/e87_bond_policy.c.o",
    "objs/apps/watch/e87/e87_build_info.c.o",
    "objs/apps/watch/e87/e87_gatt_db.c.o",
    "objs/apps/watch/e87/e87_state.c.o",
    "objs/apps/watch/log_config/app_config.c.o",
    "objs/apps/watch/log_config/lib_btctrler_config.c.o",
    "objs/apps/watch/log_config/lib_btstack_config.c.o",
)
NORMAL_BLE_ARCHIVES = {
    "cpu/br35/liba/btstack.a",
    "cpu/br35/liba/btctrler.a",
    "cpu/br35/liba/cbuf.a",
    "cpu/br35/liba/crypto_toolbox_Osize.a",
    "cpu/br35/liba/lib_ccm_cipher.a",
}

PRODUCTION_SOURCE_OBJECTS = (
    "objs/apps/common/debug/debug.c.o",
    "objs/apps/common/debug/debug_uart_config.c.o",
    "objs/apps/common/perf_counter/perf_counter.c.o",
    "objs/apps/common/update/update.c.o",
    "objs/apps/watch/app_main.c.o",
    "objs/apps/watch/board/br35/board_e87_1542_full/board_e87_1542_full.c.o",
    "objs/apps/watch/e87/e87_app.c.o",
    "objs/apps/watch/e87/e87_app_target.c.o",
    "objs/apps/watch/e87/e87_app_runtime.c.o",
    "objs/apps/watch/e87/e87_app_core.c.o",
    "objs/apps/watch/e87/e87_ui.c.o",
    "objs/apps/watch/e87/e87_button_classifier.c.o",
    "objs/apps/watch/e87/e87_button_fsm.c.o",
    "objs/apps/watch/e87/e87_power_policy.c.o",
    "objs/apps/watch/e87/e87_recovery.c.o",
    "objs/apps/watch/e87/e87_ble_mode_fsm.c.o",
    "objs/apps/watch/e87/e87_maintenance.c.o",
    "objs/apps/watch/e87/e87_rcsp_profile.c.o",
    "objs/apps/watch/e87/e87_full_platform_config.c.o",
    "objs/apps/watch/log_config/lib_driver_config.c.o",
    "objs/apps/watch/log_config/lib_system_config.c.o",
    "objs/cpu/br35/power/power_app.c.o",
    "objs/cpu/br35/setup.c.o",
    "objs/cpu/config/lib_power_config.c.o",
    "objs/cpu/power/msg.c.o",
    "objs/apps/watch/e87/e87_ble_target.c.o",
    "objs/apps/watch/e87/e87_ble_target_journal.c.o",
    "objs/apps/watch/e87/e87_ble_target_platform_config.c.o",
    "objs/apps/watch/e87/e87_bond_policy.c.o",
    "objs/apps/watch/e87/e87_build_info.c.o",
    "objs/apps/watch/e87/e87_gatt_db.c.o",
    "objs/apps/watch/e87/e87_state.c.o",
    "objs/apps/watch/log_config/app_config.c.o",
    "objs/apps/watch/log_config/lib_btctrler_config.c.o",
    "objs/apps/watch/log_config/lib_btstack_config.c.o",
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
        "cpu/br35/liba/libc.a",
        "f7d8d0b20e688ab682864face6ddec8e6fa87bf5c8c7dfd527d4c42257e0fb64",
    ),
    (
        "cpu/br35/liba/cfg_tool.a",
        "545df929e1e05c17e978156a3a959cb07744bbecceef30b305f96606b21e2f04",
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
        "cpu/br35/liba/printf.a",
        "58cef0141f5220726a16fcd7b23d672a402ea6ce77156039404d4703d750bfef",
    ),
    (
        "cpu/br35/liba/vm.a",
        "bebc7934c785e75da2cb216a6150992126798a7abfd3936c500add6ee46f9900",
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
        "cpu/br35/liba/cbuf.a",
        "03740c7da23a02570ed618b144eca607373ae8debb374ed15e3c3840ad0e3bb8",
    ),
    (
        "cpu/br35/liba/crypto_toolbox_Osize.a",
        "b16901cea79a369ad5f8db918c7799b5965b3013be986f31f24e5cc09c607b8f",
    ),
    (
        "cpu/br35/liba/lib_ccm_cipher.a",
        "bb3accd5d94fe58e61dcfeff2fb73eeeebc7a129fbeb5f474b5eb6c9d7cb43d2",
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
    "cpu/br35/liba/libc.a",
    "cpu/br35/liba/cfg_tool.a",
    "cpu/br35/liba/device.a",
    "cpu/br35/liba/fs.a",
    "cpu/br35/liba/printf.a",
    "cpu/br35/liba/vm.a",
    "cpu/br35/liba/btstack.a",
    "cpu/br35/liba/btctrler.a",
    "cpu/br35/liba/cbuf.a",
    "cpu/br35/liba/crypto_toolbox_Osize.a",
    "cpu/br35/liba/lib_ccm_cipher.a",
    "toolchain/lib/r3-large/libm.a",
    "toolchain/lib/r3-large/libc.a",
    "toolchain/lib/r3-large/libm.a",
    "toolchain/lib/r3-large/libcompiler-rt.a",
)

PRODUCTION_PROVENANCE = (
    (
        "cpu/br35/liba/cpu.a(wdt_p33.c.o)",
        "O:objs/apps/watch/app_main.c.o",
        "wdt_init",
    ),
    (
        "cpu/br35/liba/system.a(sbrk.c.o)",
        "O:objs/cpu/br35/setup.c.o",
        "memory_init",
    ),
    (
        "cpu/br35/liba/cfg_tool.a(syscfg_api.c.o)",
        "O:objs/apps/watch/e87/e87_ble_target_journal.c.o",
        "syscfg_read",
    ),
    (
        "cpu/br35/liba/cfg_tool.a(cfg_btif.c.o)",
        "A:cpu/br35/liba/cfg_tool.a(syscfg_api.c.o)",
        "syscfg_btif_enable",
    ),
    (
        "cpu/br35/liba/fs.a(sdfile.c.o)",
        "A:cpu/br35/liba/cfg_tool.a(cfg_btif.c.o)",
        "sdfile_cpu_addr2flash_addr",
    ),
    (
        "cpu/br35/liba/fs.a(vfs.c.o)",
        "A:cpu/br35/liba/fs.a(sdfile.c.o)",
        "mount",
    ),
    (
        "cpu/br35/liba/device.a(device_api.c.o)",
        "A:cpu/br35/liba/fs.a(vfs.c.o)",
        "dev_open",
    ),
    (
        "cpu/br35/liba/vm.a(vm.c.o)",
        "A:cpu/br35/liba/fs.a(sdfile.c.o)",
        "sfc_erase_zone",
    ),
)

PRODUCTION_RESOLUTION = (
    (
        "objs/cpu/br35/setup.c.o",
        "objs/apps/watch/app_main.c.o",
        "app_main",
    ),
    (
        "objs/apps/watch/app_main.c.o",
        "objs/apps/watch/e87/e87_app.c.o",
        "e87_app_start",
    ),
    (
        "objs/apps/watch/app_main.c.o",
        "objs/apps/watch/e87/e87_app.c.o",
        "e87_app_dispatch_forever",
    ),
)

PRODUCTION_MEMORY = {
    "entry": 0xC000100,
    "ramLow": 0x10054C,
    "ramTop": 0x137000,
    "updateStart": 0x136E00,
    "heapEnd": 0x130E00,
    "reservedStart": 0x130E00,
    "bufferStart": 0x130E00,
    "bufferEnd": 0x136260,
    "reservedEnd": 0x136E00,
    "reservedBytes": 0x6000,
    "bufferBytes": 0x5460,
    "slackBytes": 0xBA0,
    "minimumHeapBytes": 0x8000,
    "psramBytes": 0,
}


class ValidationError(Exception):
    """The supplied artifacts do not satisfy the full-substrate contract."""


def fail(message: str) -> None:
    raise ValidationError(message)


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def graph_digest(rows: list[str]) -> str:
    return sha256("".join(rows).encode("ascii"))


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
        fail(
            f"{label}: keys differ; "
            f"missing={sorted(expected - actual)} "
            f"unknown={sorted(actual - expected)}"
        )
    return value


def ascii_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.isascii() or not value:
        fail(f"{label}: must be a nonempty ASCII string")
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
        result.startswith(("/", "//"))
        or "\\" in result
        or ":" in result
        or str(path) != result
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        fail(f"{label}: must be a canonical relative POSIX path")
    return result


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
        value = json.loads(
            raw.decode("ascii"), object_pairs_hook=reject_duplicate_keys
        )
    except ValidationError:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        fail(f"evidence: invalid JSON: {error}")
    root = exact_keys(
        value,
        {
            "schemaVersion",
            "qualificationIdentity",
            "qualificationState",
            "evidenceId",
            "sdkCommit",
            "clangVersion",
            "qualificationArtifact",
            "sourceObjects",
            "archives",
            "archiveLoadOrder",
            "memory",
            "mapContract",
            "policy",
        },
        "evidence",
    )
    if root["schemaVersion"] != 2:
        fail("evidence.schemaVersion: unsupported")
    if root["qualificationIdentity"] != "FULL_RUNTIME_NORMAL_BLE":
        fail("evidence.qualificationIdentity: unsupported")
    if root["qualificationState"] not in {"PRODUCTION", "CANDIDATE", "TEST"}:
        fail("evidence.qualificationState: unsupported")
    ascii_string(root["evidenceId"], "evidence.evidenceId")
    commit(root["sdkCommit"], "evidence.sdkCommit")
    ascii_string(root["clangVersion"], "evidence.clangVersion")

    artifact = exact_keys(
        root["qualificationArtifact"],
        {
            "sourceCommit",
            "elfSha256",
            "elfSize",
            "ltoObjectSha256",
            "ltoObjectSize",
            "mapSha256",
            "mapSize",
            "resolutionSha256",
            "resolutionSize",
            "objectListSha256",
            "objectListSize",
            "linkLogSha256",
            "linkLogSize",
            "buildMode",
            "postLinkStatus",
        },
        "qualificationArtifact",
    )
    commit(artifact["sourceCommit"], "sourceCommit")
    for name in (
        "elfSha256",
        "ltoObjectSha256",
        "mapSha256",
        "resolutionSha256",
        "objectListSha256",
        "linkLogSha256",
    ):
        digest(artifact[name], name)
    for name in (
        "elfSize",
        "ltoObjectSize",
        "mapSize",
        "resolutionSize",
        "objectListSize",
        "linkLogSize",
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
    if any(
        not item.startswith("objs/") or not item.endswith(".o")
        for item in source_values
    ):
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

    memory = exact_keys(root["memory"], set(PRODUCTION_MEMORY), "memory")
    for name in memory:
        integer(memory[name], f"memory.{name}")
    if memory["ramTop"] - memory["updateStart"] != 0x200:
        fail("memory: update tail differs from 0x200")
    if memory["reservedStart"] != memory["heapEnd"]:
        fail("memory: reserve must begin at heap end")
    if memory["bufferStart"] != memory["reservedStart"]:
        fail("memory: buffer must begin at reserve start")
    if memory["reservedEnd"] != memory["updateStart"]:
        fail("memory: reserve must end at update boundary")
    if memory["reservedEnd"] - memory["reservedStart"] != memory["reservedBytes"]:
        fail("memory: reserved size mismatch")
    if memory["bufferEnd"] - memory["bufferStart"] != memory["bufferBytes"]:
        fail("memory: buffer size mismatch")
    if memory["reservedEnd"] - memory["bufferEnd"] != memory["slackBytes"]:
        fail("memory: slack size mismatch")

    contract = exact_keys(
        root["mapContract"],
        {
            "archiveInclusionRowCount",
            "archiveInclusionRowsSha256",
            "requiredProvenance",
            "requiredResolution",
            "disabledUpdate",
        },
        "mapContract",
    )
    integer(contract["archiveInclusionRowCount"], "archiveInclusionRowCount", 1)
    digest(contract["archiveInclusionRowsSha256"], "archiveInclusionRowsSha256")
    for key, expected in (
        ("requiredProvenance", {"archiveMember", "referrer", "symbol"}),
        ("requiredResolution", {"requester", "provider", "symbol"}),
    ):
        rows = contract[key]
        if not isinstance(rows, list) or not rows:
            fail(f"{key}: must be a nonempty list")
        for index, item in enumerate(rows):
            row = exact_keys(item, expected, f"{key}[{index}]")
            for name in expected:
                ascii_string(row[name], f"{key}[{index}].{name}")
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
            "genericInitcalls",
            "immutableBootSeamArchives",
            "applicationFilesystemRoute",
            "forbiddenArchives",
            "forbiddenSourceObjects",
            "forbiddenSymbols",
        },
        "policy",
    )
    if policy["genericInitcalls"] != []:
        fail("generic initcall allowlist must remain empty")
    if policy["applicationFilesystemRoute"] != "IMMUTABLE_SETUP_ARCH_ONLY":
        fail("applicationFilesystemRoute: unsupported")
    for name in (
        "immutableBootSeamArchives",
        "forbiddenArchives",
        "forbiddenSourceObjects",
    ):
        values = policy[name]
        if not isinstance(values, list):
            fail(f"{name}: must be a list")
        parsed = [posix_relative(item, f"{name}[]") for item in values]
        if len(parsed) != len(set(parsed)):
            fail(f"{name}: duplicate")
    symbols = policy["forbiddenSymbols"]
    if not isinstance(symbols, list) or not symbols:
        fail("forbiddenSymbols: must be a nonempty list")
    parsed_symbols = [ascii_string(item, "forbiddenSymbols[]") for item in symbols]
    if len(parsed_symbols) != len(set(parsed_symbols)):
        fail("forbiddenSymbols: duplicate")
    return root


def production_contract_is_exact(evidence: dict[str, Any]) -> bool:
    archives = tuple(
        (item["path"], item["sha256"]) for item in evidence["archives"]
    )
    provenance = tuple(
        (item["archiveMember"], item["referrer"], item["symbol"])
        for item in evidence["mapContract"]["requiredProvenance"]
    )
    resolution = tuple(
        (item["requester"], item["provider"], item["symbol"])
        for item in evidence["mapContract"]["requiredResolution"]
    )
    return (
        evidence["evidenceId"] == PRODUCTION_EVIDENCE_ID
        and evidence["qualificationState"] == "PRODUCTION"
        and tuple(evidence["sourceObjects"]) == PRODUCTION_SOURCE_OBJECTS
        and archives == PRODUCTION_ARCHIVES
        and tuple(evidence["archiveLoadOrder"]) == PRODUCTION_ARCHIVE_LOAD_ORDER
        and provenance == PRODUCTION_PROVENANCE
        and resolution == PRODUCTION_RESOLUTION
        and evidence["memory"] == PRODUCTION_MEMORY
    )


def authorized_evidence(raw: bytes, accept_untrusted_test_evidence: bool) -> dict[str, Any]:
    if b"\r" in raw and (b"\r\n" not in raw or raw.replace(b"\r\n", b"").find(b"\r") >= 0):
        fail("evidence: noncanonical line endings")
    canonical_raw = raw.replace(b"\r\n", b"\n")
    if (
        not accept_untrusted_test_evidence
        and sha256(canonical_raw) != PRODUCTION_EVIDENCE_SHA256
    ):
        fail("evidence: bytes differ from exact committed production evidence")
    evidence = decode_evidence(raw)
    if accept_untrusted_test_evidence:
        expected_states = {
            TEST_EVIDENCE_ID: "TEST",
            CANDIDATE_EVIDENCE_ID: "CANDIDATE",
        }
        expected_state = expected_states.get(evidence["evidenceId"])
        if expected_state is None:
            fail("untrusted evidence must use the exact test or candidate evidence ID")
        if evidence["qualificationState"] != expected_state:
            fail("untrusted evidence ID/state mismatch")
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


def typed_parent(raw: str, prior_archive_nodes: dict[str, list[str]]) -> str:
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


def inclusion_entries(text: str) -> tuple[list[str], dict[str, tuple[str, str, int]]]:
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


def decode_map(raw: bytes) -> str:
    try:
        text = raw.decode("ascii")
    except UnicodeError as error:
        fail(f"map: non-ASCII bytes: {error}")
    if "\r" in text or not text.endswith("\n"):
        fail("map: noncanonical line endings")
    if text.count(DISCARDED_SECTIONS_MARKER) != 1:
        fail("map: expected exactly one discarded-sections boundary")
    after_discarded = text.split(DISCARDED_SECTIONS_MARKER, 1)[1]
    if after_discarded.count(LINKER_MEMORY_MAP_MARKER) != 1:
        fail("map: expected exactly one live linker-memory-map boundary")
    return text


def live_map(text: str) -> str:
    after_discarded = text.split(DISCARDED_SECTIONS_MARKER, 1)[1]
    return after_discarded.split(LINKER_MEMORY_MAP_MARKER, 1)[1]


def parse_loads(live: str) -> list[str]:
    result: list[str] = []
    for line_number, line in enumerate(live.splitlines(), 1):
        if re.match(r"^\s*LOAD(?:\s|$)", line) is None:
            continue
        match = re.fullmatch(r"LOAD ([^\s]+)", line)
        if match is None:
            fail(f"malformed LOAD record at live-map line {line_number}")
        result.append(match.group(1))
    return result


def symbol_value(live: str, symbol: str) -> int:
    pattern = re.compile(
        rf"^[ \t]+(0x[0-9A-Fa-f]+)[ \t]+{re.escape(symbol)}[ \t]*=",
        re.M,
    )
    matches = pattern.findall(live)
    if len(matches) != 1:
        fail(f"memory: symbol {symbol} missing or repeated")
    return int(matches[0], 16)


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


def resolve_archive(path: str, sdk_root: Path, toolchain_root: Path) -> Path:
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
    lto_object_path: Path,
    resolution_path: Path,
    object_list_path: Path,
    link_log_path: Path,
    evidence_path: Path,
    sdk_root: Path,
    toolchain_root: Path,
    accept_untrusted_test_evidence: bool = False,
) -> tuple[int, int]:
    evidence = authorized_evidence(
        read_regular(evidence_path, "evidence"), accept_untrusted_test_evidence
    )
    artifact = evidence["qualificationArtifact"]
    artifact_inputs = (
        (map_path, "map", "mapSha256", "mapSize"),
        (elf_path, "ELF", "elfSha256", "elfSize"),
        (lto_object_path, "LTO object", "ltoObjectSha256", "ltoObjectSize"),
        (resolution_path, "resolution", "resolutionSha256", "resolutionSize"),
        (object_list_path, "object list", "objectListSha256", "objectListSize"),
        (link_log_path, "link log", "linkLogSha256", "linkLogSize"),
    )
    raw_inputs: dict[str, bytes] = {}
    for path, label, digest_key, size_key in artifact_inputs:
        raw = read_regular(path, label)
        if len(raw) != artifact[size_key] or sha256(raw) != artifact[digest_key]:
            fail(f"{label} digest or size differs from qualification artifact")
        raw_inputs[label] = raw

    text = decode_map(raw_inputs["map"])
    live = live_map(text)
    loads = parse_loads(live)
    generated = "cpu/br35/tools/sdk.elf.o"
    if loads.count(generated) != 1:
        fail("generated object must be loaded exactly once")

    source_loads = [item for item in loads if item.startswith("objs/")]
    for forbidden in evidence["policy"]["forbiddenSourceObjects"]:
        if forbidden in source_loads:
            fail(f"forbidden source object loaded: {forbidden}")
    if source_loads != evidence["sourceObjects"]:
        fail("source object LOAD order differs from exact allowlist")
    expected_object_list = (" " + " ".join(evidence["sourceObjects"]) + "\n").encode(
        "ascii"
    )
    if raw_inputs["object list"] != expected_object_list:
        fail("object list bytes differ from exact source allowlist")

    archive_loads = [normalize_archive(item) for item in loads if item.endswith(".a")]
    for forbidden in evidence["policy"]["forbiddenArchives"]:
        if forbidden in archive_loads:
            fail(f"forbidden archive loaded: {forbidden}")
    if archive_loads != evidence["archiveLoadOrder"]:
        fail("archive LOAD order differs from exact allowlist")
    unknown = [
        item
        for item in loads
        if not item.startswith("objs/")
        and not item.endswith(".a")
        and item != generated
    ]
    if unknown:
        fail(f"unexpected non-archive LOAD entry: {unknown[0]}")

    for record in evidence["archives"]:
        raw = read_regular(
            resolve_archive(record["path"], sdk_root, toolchain_root),
            f"archive {record['path']}",
        )
        if sha256(raw) != record["sha256"]:
            fail(f"archive digest differs: {record['path']}")

    rows, reasons = inclusion_entries(text)
    contract = evidence["mapContract"]
    if (
        len(rows) != contract["archiveInclusionRowCount"]
        or graph_digest(rows) != contract["archiveInclusionRowsSha256"]
    ):
        fail("archive inclusion graph differs from exact qualified set")
    for edge in contract["requiredProvenance"]:
        actual = reasons.get(edge["archiveMember"])
        if actual is None or actual[:2] != (edge["referrer"], edge["symbol"]):
            fail(f"required provenance edge differs: {edge['archiveMember']}")

    try:
        resolution_text = raw_inputs["resolution"].decode("ascii")
    except UnicodeError as error:
        fail(f"resolution: non-ASCII bytes: {error}")
    modules = resolution_modules(resolution_text)
    for edge in contract["requiredResolution"]:
        requester_flags = modules.get(edge["requester"], {}).get(edge["symbol"], "")
        provider_flags = modules.get(edge["provider"], {}).get(edge["symbol"], "")
        if "l" not in requester_flags:
            fail(f"resolution requester differs: {edge['symbol']}")
        if "p" not in provider_flags:
            fail(f"resolution provider differs: {edge['symbol']}")

    update = contract["disabledUpdate"]
    section = re.escape(update["section"])
    symbol = re.escape(update["symbol"])
    matches = re.findall(
        rf"^\s*{section}\s+0x[0-9a-fA-F]+\s+0x([0-9a-fA-F]+)\s+"
        rf"cpu/br35/tools/sdk\.elf\.o\n"
        rf"\s+0x[0-9a-fA-F]+\s+{symbol}\s*$",
        live,
        re.M,
    )
    if len(matches) != 1 or int(matches[0], 16) != update["size"]:
        fail("disabled update exception differs from exact inert symbol")
    provider_flags = modules.get(update["sourceObject"], {}).get(update["symbol"], "")
    if "p" not in provider_flags:
        fail("disabled update provider differs from exact source object")

    symbol_contract = {
        "CODE_BEG": "entry",
        "RAM_LIMIT_L": "ramLow",
        "_RAM_LIMIT_H": "ramTop",
        "UPDATA_BEG": "updateStart",
        "_HEAP_END": "heapEnd",
        "_E87_LCD_RESERVED_START": "reservedStart",
        "_E87_LCD_BUFFER_START": "bufferStart",
        "_E87_LCD_BUFFER_END": "bufferEnd",
        "_E87_LCD_RESERVED_END": "reservedEnd",
        "PSRAM_SIZE": "psramBytes",
    }
    memory = evidence["memory"]
    for symbol_name, field in symbol_contract.items():
        if symbol_value(live, symbol_name) != memory[field]:
            fail(f"memory: {symbol_name} differs from evidence")
    heap_begin = symbol_value(live, "_HEAP_BEGIN")
    if memory["heapEnd"] - heap_begin < memory["minimumHeapBytes"]:
        fail("heap is below the required minimum")
    if memory["psramBytes"] != 0:
        fail("PSRAM must remain absent")

    initcall_ranges = (
        ("_initcall_begin", "_initcall_end"),
        ("_early_initcall_begin", "_early_initcall_end"),
        ("_late_initcall_begin", "_late_initcall_end"),
        ("_platform_initcall_begin", "_platform_initcall_end"),
        ("_module_initcall_begin", "_module_initcall_end"),
        ("platform_uninitcall_begin", "platform_uninitcall_end"),
    )
    for begin, end in initcall_ranges:
        if symbol_value(live, begin) != symbol_value(live, end):
            fail(f"initcall range is not empty: {begin}..{end}")

    for forbidden in evidence["policy"]["forbiddenSymbols"]:
        if re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(forbidden)}(?![A-Za-z0-9_])", live
        ):
            fail(f"forbidden symbol is live: {forbidden}")
    if "OUTPUT(cpu/br35/tools/sdk.elf elf32-pi32v2)" not in live:
        fail("map: missing exact full-substrate ELF output")
    return len(rows), len(source_loads)


def generate_candidate(arguments: argparse.Namespace) -> tuple[int, int]:
    template = decode_evidence(read_regular(arguments.evidence, "evidence template"))
    raw_inputs = {
        "map": read_regular(arguments.map, "map"),
        "ELF": read_regular(arguments.elf, "ELF"),
        "LTO object": read_regular(arguments.lto_object, "LTO object"),
        "resolution": read_regular(arguments.resolution, "resolution"),
        "object list": read_regular(arguments.object_list, "object list"),
        "link log": read_regular(arguments.link_log, "link log"),
    }
    text = decode_map(raw_inputs["map"])
    live = live_map(text)
    loads = parse_loads(live)
    sources = [item for item in loads if item.startswith("objs/")]
    if not set(NORMAL_BLE_SOURCE_OBJECTS).issubset(sources):
        fail("candidate: normal BLE source closure is incomplete")
    expected_object_list = (" " + " ".join(sources) + "\n").encode("ascii")
    if raw_inputs["object list"] != expected_object_list:
        fail("candidate: object list does not exactly match map source LOAD order")
    forbidden_sources = set(template["policy"]["forbiddenSourceObjects"])
    rejected_sources = forbidden_sources.intersection(sources)
    if rejected_sources:
        fail(f"candidate: forbidden source object loaded: {sorted(rejected_sources)[0]}")
    archive_loads = [normalize_archive(item) for item in loads if item.endswith(".a")]
    if not NORMAL_BLE_ARCHIVES.issubset(archive_loads):
        fail("candidate: normal BLE archive closure is incomplete")
    forbidden_archives = set(template["policy"]["forbiddenArchives"])
    rejected_archives = forbidden_archives.intersection(archive_loads)
    if rejected_archives:
        fail(f"candidate: forbidden archive loaded: {sorted(rejected_archives)[0]}")
    unique_archives = list(dict.fromkeys(archive_loads))
    old_roles = {item["path"]: item["role"] for item in template["archives"]}
    archives = []
    for path in unique_archives:
        raw = read_regular(
            resolve_archive(path, arguments.sdk_root, arguments.toolchain_root),
            f"archive {path}",
        )
        archives.append({
            "path": path,
            "sha256": sha256(raw),
            "role": old_roles.get(path, "PINNED_NORMAL_BLE_RUNTIME"),
        })
    rows, _ = inclusion_entries(text)
    candidate = json.loads(json.dumps(template))
    candidate["evidenceId"] = CANDIDATE_EVIDENCE_ID
    candidate["qualificationState"] = "CANDIDATE"
    candidate["qualificationArtifact"] = {
        "sourceCommit": arguments.source_commit,
        "elfSha256": sha256(raw_inputs["ELF"]),
        "elfSize": len(raw_inputs["ELF"]),
        "ltoObjectSha256": sha256(raw_inputs["LTO object"]),
        "ltoObjectSize": len(raw_inputs["LTO object"]),
        "mapSha256": sha256(raw_inputs["map"]),
        "mapSize": len(raw_inputs["map"]),
        "resolutionSha256": sha256(raw_inputs["resolution"]),
        "resolutionSize": len(raw_inputs["resolution"]),
        "objectListSha256": sha256(raw_inputs["object list"]),
        "objectListSize": len(raw_inputs["object list"]),
        "linkLogSha256": sha256(raw_inputs["link log"]),
        "linkLogSize": len(raw_inputs["link log"]),
        "buildMode": "VENDOR_MAKE_EXPLICIT_LINK_TARGET_NO_POST",
        "postLinkStatus": "NOT_INVOKED_BY_EXPLICIT_LINK_TARGET",
    }
    candidate["sourceObjects"] = sources
    candidate["archives"] = archives
    candidate["archiveLoadOrder"] = archive_loads
    candidate["mapContract"]["archiveInclusionRowCount"] = len(rows)
    candidate["mapContract"]["archiveInclusionRowsSha256"] = graph_digest(rows)
    candidate["mapContract"]["requiredProvenance"] = [
        {"archiveMember": member, "referrer": referrer, "symbol": symbol}
        for member, referrer, symbol in PRODUCTION_PROVENANCE
    ]
    candidate["mapContract"]["requiredResolution"] = [
        {"requester": requester, "provider": provider, "symbol": symbol}
        for requester, provider, symbol in PRODUCTION_RESOLUTION
    ]
    encoded = (json.dumps(candidate, indent=2, ensure_ascii=True) + "\n").encode("ascii")
    with tempfile.TemporaryDirectory(prefix="e87-full-candidate-") as directory:
        candidate_path = Path(directory) / "candidate.json"
        candidate_path.write_bytes(encoded)
        result = validate_artifacts(
            arguments.map, arguments.elf, arguments.lto_object,
            arguments.resolution, arguments.object_list, arguments.link_log,
            candidate_path, arguments.sdk_root, arguments.toolchain_root, True,
        )
    if arguments.output.exists():
        fail("candidate output already exists; refusing to overwrite")
    arguments.output.write_bytes(encoded)
    return result


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", required=True, type=Path)
    parser.add_argument("--elf", required=True, type=Path)
    parser.add_argument("--lto-object", required=True, type=Path)
    parser.add_argument("--resolution", required=True, type=Path)
    parser.add_argument("--object-list", required=True, type=Path)
    parser.add_argument("--link-log", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--sdk-root", required=True, type=Path)
    parser.add_argument("--toolchain-root", required=True, type=Path)
    parser.add_argument("--generate-candidate", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source-commit", type=lambda value: commit(value, "source commit"))
    parser.add_argument(
        "--test-only-accept-untrusted-evidence",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        if arguments.generate_candidate:
            if arguments.output is None or arguments.source_commit is None:
                fail("candidate generation requires --output and --source-commit")
            if arguments.test_only_accept_untrusted_evidence:
                fail("candidate generation cannot use test-only evidence acceptance")
            rows, sources = generate_candidate(arguments)
        else:
            if arguments.output is not None or arguments.source_commit is not None:
                fail("--output and --source-commit require --generate-candidate")
            rows, sources = validate_artifacts(
            arguments.map,
            arguments.elf,
            arguments.lto_object,
            arguments.resolution,
            arguments.object_list,
            arguments.link_log,
            arguments.evidence,
            arguments.sdk_root,
            arguments.toolchain_root,
            arguments.test_only_accept_untrusted_evidence,
        )
    except ValidationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    noun = "candidate generated" if arguments.generate_candidate else "link qualified"
    print(f"full runtime + normal BLE {noun}: {sources} sources, {rows} archive members")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
