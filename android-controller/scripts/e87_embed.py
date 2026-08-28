#!/usr/bin/env python3
"""Closed, offline intake for an explicitly qualified E87 Android handoff."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


RECEIPT_NAME = "e87-android-embed.json"
INDEX_NAME = "default-release.json"
SCHEMA_ID = "e87-android-embed-v1"
PROVENANCE_SCHEMA_ID = "e87-android-embed-provenance-v1"
CHIP = "AC707N"
PROFILE = "E87-JD9855-R1"
LAYOUT = "SINGLE_BANK"
MIN_QIX_VERSION = (11, 1, 0, 4)
RECEIPT_KEYS = {
    "buildId", "chip", "files", "labEligible", "layout", "profile",
    "qixVersion", "releaseEligible", "releaseRoot", "schemaId",
    "schemaVersion", "semver",
}
FILE_KEYS = {"filename", "length", "role", "sha256"}
ROLE_ORDER = ("appBin", "jlIsdFw", "updateUfw", "qix", "manifest", "sha256Sums")
FIXED_FILENAMES = {
    "appBin": "app.bin",
    "jlIsdFw": "jl_isd.fw",
    "updateUfw": "update.ufw",
    "manifest": "manifest.json",
    "sha256Sums": "SHA256SUMS",
}
HEX32 = re.compile(r"[0-9A-F]{32}\Z")
HEX64 = re.compile(r"[0-9A-F]{64}\Z")
SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
QIX_VERSION_PATTERN = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
BARE_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
MAX_RECEIPT = 256 * 1024
MAX_MANIFEST = 256 * 1024
MAX_SHA256SUMS = 16 * 1024
MAX_ARTIFACT = 32 * 1024 * 1024
QIX_HEADER_LENGTH = 27


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedRelease:
    receipt: dict[str, object]
    receipt_bytes: bytes
    files: dict[str, bytes]
    records: tuple[dict[str, object], ...]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, allow_nan=False,
                       indent=2, sort_keys=True) + "\n").encode("ascii")


def _closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_canonical_json(data: bytes, label: str) -> dict[str, object]:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as error:
        raise ValidationError(f"{label} must be ASCII JSON") from error
    try:
        value = json.loads(text, object_pairs_hook=_closed_object,
                           parse_constant=lambda token: (_ for _ in ()).throw(
                               ValidationError(f"non-finite JSON value: {token}")))
    except (json.JSONDecodeError, TypeError) as error:
        raise ValidationError(f"invalid {label} JSON") from error
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a JSON object")
    if data != _canonical(value):
        raise ValidationError(f"{label} must use canonical JSON")
    return value


def _reject_symlink_components(path: Path, *, allow_missing_tail: bool) -> None:
    if not path.is_absolute():
        raise ValidationError(f"path must be absolute: {path}")
    cursor = Path(path.anchor)
    for index, component in enumerate(path.parts[1:]):
        cursor /= component
        try:
            mode = cursor.lstat().st_mode
        except FileNotFoundError:
            if allow_missing_tail:
                return
            raise ValidationError(f"path does not exist: {cursor}")
        if stat.S_ISLNK(mode):
            raise ValidationError(f"path contains a symlink component: {cursor}")
        if index < len(path.parts[1:]) - 1 and not stat.S_ISDIR(mode):
            raise ValidationError(f"path component is not a directory: {cursor}")


def _read_release_files(root: Path) -> dict[str, bytes]:
    _reject_symlink_components(root, allow_missing_tail=False)
    if not root.is_dir():
        raise ValidationError("release root must be a real directory")
    entries = list(os.scandir(root))
    for entry in entries:
        if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
            raise ValidationError(f"release entry is not a regular file: {entry.name}")
    names = {entry.name for entry in entries}
    if RECEIPT_NAME not in names:
        raise ValidationError("release allowlist requires e87-android-embed.json")
    receipt_path = root / RECEIPT_NAME
    receipt_bytes = receipt_path.read_bytes()
    if not receipt_bytes or len(receipt_bytes) > MAX_RECEIPT:
        raise ValidationError("handoff receipt size is invalid")
    receipt = _parse_canonical_json(receipt_bytes, "handoff receipt")
    records = receipt.get("files")
    if not isinstance(records, list):
        raise ValidationError("handoff receipt files must be an array")
    filenames = []
    for record in records:
        if isinstance(record, dict) and isinstance(record.get("filename"), str):
            filenames.append(record["filename"])
    expected = {RECEIPT_NAME, *filenames}
    if names != expected or len(entries) != len(expected):
        raise ValidationError("release directory allowlist mismatch")
    result = {RECEIPT_NAME: receipt_bytes}
    for filename in filenames:
        path = root / filename
        if path.parent != root or path.is_symlink() or not path.is_file():
            raise ValidationError(f"invalid release file: {filename}")
        if path.stat().st_size > MAX_ARTIFACT:
            raise ValidationError(f"handoff file exceeds global read cap: {filename}")
        result[filename] = path.read_bytes()
    return result


def _require_bool(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ValidationError(f"{field} must be boolean")
    return value


def _validate_receipt(files: dict[str, bytes]) -> ValidatedRelease:
    receipt_bytes = files[RECEIPT_NAME]
    receipt = _parse_canonical_json(receipt_bytes, "handoff receipt")
    if set(receipt) != RECEIPT_KEYS:
        raise ValidationError("handoff receipt keys are not closed")
    if receipt["schemaId"] != SCHEMA_ID or receipt["schemaVersion"] != 1:
        raise ValidationError("unsupported handoff receipt schema")
    if receipt["chip"] != CHIP:
        raise ValidationError("handoff chip is not AC707N")
    if receipt["profile"] != PROFILE:
        raise ValidationError("handoff profile is not E87-JD9855-R1")
    if receipt["layout"] != LAYOUT:
        raise ValidationError("handoff layout is not SINGLE_BANK")
    qix_version = receipt["qixVersion"]
    qix_match = (QIX_VERSION_PATTERN.fullmatch(qix_version)
                 if isinstance(qix_version, str) else None)
    qix_parts = tuple(int(part) for part in qix_match.groups()) if qix_match else ()
    if (qix_match is None or len(qix_version.encode("ascii")) > 10
            or any(part > 255 for part in qix_parts)
            or qix_parts < MIN_QIX_VERSION):
        raise ValidationError(
            "handoff Qix version must be canonical, fit the header, and be newer than "
            "sacrificial 11.1.0.3")
    if _require_bool(receipt["labEligible"], "labEligible") is not True:
        raise ValidationError("handoff is not explicitly lab eligible")
    _require_bool(receipt["releaseEligible"], "releaseEligible")
    semver = receipt["semver"]
    match = SEMVER.fullmatch(semver) if isinstance(semver, str) else None
    if match is None or any(int(part) > 255 for part in match.groups()):
        raise ValidationError("handoff semver must be canonical and fit build-info bytes")
    build_id = receipt["buildId"]
    if not isinstance(build_id, str) or HEX32.fullmatch(build_id) is None:
        raise ValidationError("handoff buildId must be 32 uppercase hex characters")
    expected_root = f"{PROFILE}/{semver}/{build_id}"
    if receipt["releaseRoot"] != expected_root:
        raise ValidationError("handoff releaseRoot does not match its identity")

    raw_records = receipt["files"]
    if not isinstance(raw_records, list) or len(raw_records) != len(ROLE_ORDER):
        raise ValidationError("handoff must contain exactly six file records")
    records: list[dict[str, object]] = []
    for index, role in enumerate(ROLE_ORDER):
        record = raw_records[index]
        if not isinstance(record, dict) or set(record) != FILE_KEYS:
            raise ValidationError("handoff file record keys are not closed")
        if record["role"] != role:
            raise ValidationError("handoff file roles are missing, duplicate, or out of order")
        filename = record["filename"]
        if not isinstance(filename, str) or BARE_FILENAME.fullmatch(filename) is None:
            raise ValidationError("handoff filename is not a bare relative filename")
        if role in FIXED_FILENAMES and filename != FIXED_FILENAMES[role]:
            raise ValidationError(f"unexpected filename for role {role}")
        if role == "qix":
            expected_names = {
                f"E87-{qix_version}-{build_id[:8]}.qix",
                f"E87-{qix_version}-{build_id}.qix",
            }
            if filename not in expected_names:
                raise ValidationError("Qix filename does not bind the expected build ID")
        length = record["length"]
        if not isinstance(length, int) or isinstance(length, bool) or length <= 0:
            raise ValidationError("handoff file length must be a positive integer")
        cap = MAX_MANIFEST if role == "manifest" else (
            MAX_SHA256SUMS if role == "sha256Sums" else MAX_ARTIFACT)
        if length > cap:
            raise ValidationError(f"handoff {role} exceeds its size cap")
        digest = record["sha256"]
        if not isinstance(digest, str) or HEX64.fullmatch(digest) is None:
            raise ValidationError("handoff file SHA-256 must be canonical uppercase hex")
        data = files.get(filename)
        if data is None:
            raise ValidationError(f"handoff file is missing: {filename}")
        if len(data) != length:
            raise ValidationError(f"handoff file length mismatch: {filename}")
        if _sha(data) != digest:
            raise ValidationError(f"handoff file hash mismatch: {filename}")
        records.append(record)

    by_role = {record["role"]: record for record in records}
    _validate_sha256sums(files, by_role)
    _validate_source_manifest(files[by_role["manifest"]["filename"]])
    _validate_qix(files[by_role["qix"]["filename"]],
                  files[by_role["updateUfw"]["filename"]], receipt)
    return ValidatedRelease(receipt, receipt_bytes, files, tuple(records))


def _validate_sha256sums(files: dict[str, bytes], by_role: dict[str, dict[str, object]]) -> None:
    names = sorted(record["filename"] for role, record in by_role.items()
                   if role != "sha256Sums")
    expected = "".join(f"{_sha(files[name])} *{name}\n" for name in names).encode("ascii")
    actual = files[by_role["sha256Sums"]["filename"]]
    if actual != expected:
        raise ValidationError("SHA256SUMS is not the canonical exact delivery receipt")


def _validate_source_manifest(data: bytes) -> None:
    manifest = _parse_canonical_json(data, "firmware manifest")
    if not isinstance(manifest.get("schema"), str) or not manifest["schema"]:
        raise ValidationError("firmware manifest has no schema identity")
    if "labEligible" in manifest and manifest["labEligible"] is not True:
        raise ValidationError("firmware manifest contradicts lab eligibility")


def _crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ (0x1021 if crc & 0x8000 else 0)) & 0xFFFF
    return crc


def _validate_qix(data: bytes, update_ufw: bytes, receipt: dict[str, object]) -> None:
    if len(data) < QIX_HEADER_LENGTH:
        raise ValidationError("Qix header is truncated")
    magic, type_code, version_field, payload_length, reserved, stored_crc = struct.unpack_from(
        "<2sB10sI8sH", data)
    if magic != b"\xBC\xAF" or type_code != 1:
        raise ValidationError("Qix magic or type is invalid")
    nul = version_field.find(b"\0")
    encoded = version_field if nul < 0 else version_field[:nul]
    if not encoded or (nul >= 0 and any(version_field[nul:])):
        raise ValidationError("Qix version field is noncanonical")
    try:
        version = encoded.decode("ascii")
    except UnicodeDecodeError as error:
        raise ValidationError("Qix version is not ASCII") from error
    if version != receipt["qixVersion"]:
        raise ValidationError("Qix version differs from the handoff receipt")
    if reserved != bytes(8):
        raise ValidationError("Qix reserved bytes are nonzero")
    payload = data[QIX_HEADER_LENGTH:]
    if not payload or payload_length != len(payload):
        raise ValidationError("Qix payload length is invalid")
    if stored_crc != _crc16(payload):
        raise ValidationError("Qix payload CRC is invalid")
    if payload != update_ufw:
        raise ValidationError("Qix payload does not equal update.ufw")


def validate_release(root: Path) -> ValidatedRelease:
    root = Path(root)
    files = _read_release_files(root)
    return _validate_receipt(files)


def _tree_digest(index: bytes, records: tuple[dict[str, object], ...],
                 files: dict[str, bytes]) -> str:
    projection = [{"path": f"e87/default-release.json", "sha256": _sha(index)}]
    release_root = json.loads(index.decode("ascii"))["releaseRoot"]
    projection.extend({
        "path": f"e87/{release_root}/{record['filename']}",
        "sha256": _sha(files[record["filename"]]),
    } for record in records)
    return _sha(_canonical(projection))


def _write_read_only(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o444)


def prepare_release(source: Path, output: Path) -> dict[str, object]:
    source = Path(source)
    output = Path(output)
    validated = validate_release(source)
    _reject_symlink_components(output, allow_missing_tail=True)
    try:
        common = Path(os.path.commonpath((source, output)))
    except ValueError as error:
        raise ValidationError("release and output paths are incompatible") from error
    if common == source or common == output:
        raise ValidationError("release and output roots must not contain one another")
    if output.exists() and (output.is_symlink() or not output.is_dir()):
        raise ValidationError("output must be a real directory or absent")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        assets = temporary / "assets" / "e87"
        _write_read_only(assets / INDEX_NAME, validated.receipt_bytes)
        release_root = assets / str(validated.receipt["releaseRoot"])
        for record in validated.records:
            name = str(record["filename"])
            _write_read_only(release_root / name, validated.files[name])
        provenance = {
            "buildId": validated.receipt["buildId"],
            "chip": validated.receipt["chip"],
            "embeddedIndexSha256": _sha(validated.receipt_bytes),
            "embeddedTreeSha256": _tree_digest(
                validated.receipt_bytes, validated.records, validated.files),
            "files": [dict(record) for record in validated.records],
            "inputReceiptSha256": _sha(validated.receipt_bytes),
            "labEligible": validated.receipt["labEligible"],
            "layout": validated.receipt["layout"],
            "profile": validated.receipt["profile"],
            "qixVersion": validated.receipt["qixVersion"],
            "releaseEligible": validated.receipt["releaseEligible"],
            "releaseRoot": validated.receipt["releaseRoot"],
            "schemaId": PROVENANCE_SCHEMA_ID,
            "schemaVersion": 1,
            "semver": validated.receipt["semver"],
        }
        _write_read_only(temporary / "e87-embed-provenance.json", _canonical(provenance))
        if output.exists():
            shutil.rmtree(output)
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return provenance


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        provenance = prepare_release(arguments.release, arguments.output)
    except (OSError, ValidationError) as error:
        print(f"e87-embed: {error}", file=os.sys.stderr)
        return 2
    print(_canonical(provenance).decode("ascii"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
