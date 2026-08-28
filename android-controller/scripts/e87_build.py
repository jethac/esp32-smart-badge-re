#!/usr/bin/env python3
"""Reviewed byte identity for every DEX entry in the qualified controller APK."""
from __future__ import annotations

import hashlib
import re
import stat
import zipfile
from pathlib import Path

try:
    from .e87_embed import (
        ValidationError,
        _parse_canonical_json,
        _reject_symlink_components,
    )
except ImportError:
    from e87_embed import (
        ValidationError,
        _parse_canonical_json,
        _reject_symlink_components,
    )


SCHEMA_ID = "e87-android-authorized-build-v1"
RECEIPT_NAME = "e87-authorized-app-build.json"
VARIANT = "labQualified"
ROOT_KEYS = {
    "dexFiles",
    "schemaId",
    "schemaVersion",
    "surfaceReceiptSha256",
    "variant",
}
DEX_KEYS = {"length", "name", "sha256"}
DEX_CANDIDATE = re.compile(r"classes[0-9]*\.dex\Z")
DEX_NAME = re.compile(r"classes(?:[2-9]|[1-5][0-9]|6[0-4])?\.dex\Z")
SHA256 = re.compile(r"[0-9A-F]{64}\Z")
MAX_RECEIPT = 64 * 1024
MAX_APK = 512 * 1024 * 1024
MAX_DEX = 64 * 1024 * 1024
MAX_DEX_FILES = 64


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _canonical_names(count: int) -> tuple[str, ...]:
    return tuple(
        "classes.dex" if index == 1 else f"classes{index}.dex"
        for index in range(1, count + 1)
    )


def _dex_rank(name: str) -> int:
    suffix = name[len("classes"):-len(".dex")]
    return 1 if suffix == "" else int(suffix)


def _regular_absolute(path: Path, label: str, *, size_cap: int) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise ValidationError(f"{label} path must be absolute")
    _reject_symlink_components(candidate, allow_missing_tail=False)
    if (not candidate.is_file()
            or stat.S_ISLNK(candidate.lstat().st_mode)
            or candidate.stat().st_size > size_cap):
        raise ValidationError(f"{label} must be a capped regular file")
    return candidate


def _surface_digest(surface_receipt: Path) -> str:
    receipt = _regular_absolute(
        Path(surface_receipt),
        "authorized surface receipt",
        size_cap=2 * 1024 * 1024,
    )
    return _sha(receipt.read_bytes())


def dex_records(apk: Path) -> tuple[dict[str, object], ...]:
    candidate = _regular_absolute(Path(apk), "APK", size_cap=MAX_APK)
    try:
        archive = zipfile.ZipFile(candidate)
    except (OSError, zipfile.BadZipFile) as error:
        raise ValidationError("APK is not a valid ZIP container") from error
    with archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ValidationError("APK has duplicate ZIP entries")
        dex_candidates = tuple(
            info for info in infos if DEX_CANDIDATE.fullmatch(info.filename))
        if any(DEX_NAME.fullmatch(info.filename) is None for info in dex_candidates):
            raise ValidationError("APK contains a noncanonical DEX entry name")
        dex_infos = sorted(
            dex_candidates,
            key=lambda info: _dex_rank(info.filename),
        )
        dex_names = tuple(info.filename for info in dex_infos)
        if (not dex_infos
                or len(dex_infos) > MAX_DEX_FILES
                or dex_names != _canonical_names(len(dex_infos))):
            raise ValidationError("APK DEX inventory is not closed and contiguous")
        records: list[dict[str, object]] = []
        for info in dex_infos:
            if (info.flag_bits & 1) != 0 or not 0 < info.file_size <= MAX_DEX:
                raise ValidationError("APK DEX entry is encrypted, empty, or exceeds cap")
            digest = hashlib.sha256()
            length = 0
            try:
                with archive.open(info, "r") as stream:
                    while True:
                        chunk = stream.read(1024 * 1024)
                        if not chunk:
                            break
                        length += len(chunk)
                        if length > MAX_DEX:
                            raise ValidationError("APK DEX entry exceeds cap")
                        digest.update(chunk)
            except (OSError, RuntimeError, zipfile.BadZipFile) as error:
                raise ValidationError("APK DEX entry could not be read") from error
            if length != info.file_size:
                raise ValidationError("APK DEX entry length is inconsistent")
            records.append({
                "length": length,
                "name": info.filename,
                "sha256": digest.hexdigest().upper(),
            })
        return tuple(records)


def build_authorization(
        apk: Path,
        surface_receipt: Path,
) -> dict[str, object]:
    return {
        "dexFiles": list(dex_records(Path(apk))),
        "schemaId": SCHEMA_ID,
        "schemaVersion": 1,
        "surfaceReceiptSha256": _surface_digest(Path(surface_receipt)),
        "variant": VARIANT,
    }


def validate_build_authorization(
        receipt_path: Path,
        apk: Path,
        surface_receipt: Path,
) -> tuple[dict[str, object], ...]:
    receipt = _regular_absolute(
        Path(receipt_path),
        "authorized build receipt",
        size_cap=MAX_RECEIPT,
    )
    value = _parse_canonical_json(receipt.read_bytes(), "authorized build receipt")
    if not isinstance(value, dict) or set(value) != ROOT_KEYS:
        raise ValidationError("authorized build receipt keys are not closed")
    if (value["schemaId"] != SCHEMA_ID
            or type(value["schemaVersion"]) is not int
            or value["schemaVersion"] != 1
            or value["variant"] != VARIANT
            or not isinstance(value["surfaceReceiptSha256"], str)
            or SHA256.fullmatch(value["surfaceReceiptSha256"]) is None):
        raise ValidationError("authorized build receipt identity is invalid")
    if value["surfaceReceiptSha256"] != _surface_digest(Path(surface_receipt)):
        raise ValidationError("authorized build does not bind the reviewed surface receipt")
    raw_records = value["dexFiles"]
    if (not isinstance(raw_records, list)
            or not raw_records
            or len(raw_records) > MAX_DEX_FILES):
        raise ValidationError("authorized DEX inventory is invalid")
    records: list[dict[str, object]] = []
    for record in raw_records:
        if not isinstance(record, dict) or set(record) != DEX_KEYS:
            raise ValidationError("authorized DEX record keys are not closed")
        name = record["name"]
        length = record["length"]
        digest = record["sha256"]
        if (not isinstance(name, str)
                or DEX_NAME.fullmatch(name) is None
                or type(length) is not int
                or not 0 < length <= MAX_DEX
                or not isinstance(digest, str)
                or SHA256.fullmatch(digest) is None):
            raise ValidationError("authorized DEX record is invalid")
        records.append({"length": length, "name": name, "sha256": digest})
    if tuple(record["name"] for record in records) != _canonical_names(len(records)):
        raise ValidationError("authorized DEX records are not closed and contiguous")
    expected = tuple(records)
    if expected != dex_records(Path(apk)):
        raise ValidationError("APK DEX names, lengths, or implementation hashes changed")
    return expected
