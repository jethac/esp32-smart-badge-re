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
    marker = "\nDiscarded input sections\n"
    if marker not in text:
        fail("map: missing inclusion-table terminator")
    block = text.split(marker, 1)[0]
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
) -> tuple[int, int]:
    evidence = decode_evidence(read_regular(evidence_path, "evidence"))
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
    loads = re.findall(r"^LOAD (.+)$", text, re.M)
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
        rf"^\s*{section}\s+0x[0-9a-fA-F]+\s+0x([0-9a-fA-F]+)\s+\S+\n"
        rf"\s+0x[0-9a-fA-F]+\s+{symbol}\s*$",
        text,
        re.M,
    )
    if len(matches) != 1 or int(matches[0], 16) != update["size"]:
        fail("disabled update exception differs from exact inert symbol")
    if "OUTPUT(cpu/br35/tools/sdk.elf elf32-pi32v2)" not in text:
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
        )
    except ValidationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"stage0 link map qualified: {sources} sources, {rows} archive members")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
