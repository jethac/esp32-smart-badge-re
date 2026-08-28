#!/usr/bin/env python3
"""Closed reviewed source/class authorization receipt for the controller APK."""
from __future__ import annotations

import hashlib
import os
import re
import stat
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


SCHEMA_ID = "e87-android-authorized-app-surface-v1"
RECEIPT_NAME = "e87-authorized-app-surface.json"
ROOT_KEYS = {"classDescriptors", "schemaId", "schemaVersion", "sourceFiles"}
SOURCE_KEYS = {"path", "sha256"}
SOURCE_PATH = re.compile(r"[A-Za-z0-9_.$-]+(?:/[A-Za-z0-9_.$-]+)*\.java\Z")
DESCRIPTOR = re.compile(
    r"Lnet/jethachan/factory_badges(?:/[A-Za-z0-9_$-]+)+;\Z")
MAX_RECEIPT = 2 * 1024 * 1024
MAX_SOURCE = 1024 * 1024
MAX_CLASSES = 4096


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _source_records(source_root: Path) -> list[dict[str, str]]:
    root = Path(source_root)
    _reject_symlink_components(root, allow_missing_tail=False)
    if not root.is_dir():
        raise ValidationError("authorized source root must be a real directory")
    records: list[dict[str, str]] = []
    for directory, directories, filenames in os.walk(root, followlinks=False):
        parent = Path(directory)
        for name in directories:
            if stat.S_ISLNK((parent / name).lstat().st_mode):
                raise ValidationError("authorized source tree contains a symlink directory")
        for name in filenames:
            path = parent / name
            if path.is_symlink() or not path.is_file() or path.suffix != ".java":
                raise ValidationError("authorized source tree contains a non-Java entry")
            relative = path.relative_to(root).as_posix()
            if SOURCE_PATH.fullmatch(relative) is None:
                raise ValidationError("authorized source path is noncanonical")
            if path.stat().st_size > MAX_SOURCE:
                raise ValidationError("authorized source file exceeds cap")
            records.append({"path": relative, "sha256": _sha(path.read_bytes())})
    records.sort(key=lambda record: record["path"])
    if not records:
        raise ValidationError("authorized source inventory is empty")
    return records


def _class_descriptors(dexdump_output: str) -> tuple[str, ...]:
    if not isinstance(dexdump_output, str):
        raise ValidationError("dexdump output must be text")
    values = re.findall(r"Class descriptor\s+: '([^']+)'", dexdump_output)
    if (not values or len(values) > MAX_CLASSES or len(values) != len(set(values))
            or any(DESCRIPTOR.fullmatch(value) is None for value in values)):
        raise ValidationError("authorized class descriptor inventory is invalid")
    return tuple(sorted(values))


def build_surface(source_root: Path, dexdump_output: str) -> dict[str, object]:
    return {
        "classDescriptors": list(_class_descriptors(dexdump_output)),
        "schemaId": SCHEMA_ID,
        "schemaVersion": 1,
        "sourceFiles": _source_records(Path(source_root)),
    }


def validate_surface(receipt_path: Path, source_root: Path) -> tuple[str, ...]:
    receipt = Path(receipt_path)
    _reject_symlink_components(receipt, allow_missing_tail=False)
    if not receipt.is_file() or receipt.stat().st_size > MAX_RECEIPT:
        raise ValidationError("authorized surface receipt is missing or exceeds cap")
    value = _parse_canonical_json(receipt.read_bytes(), "authorized app surface receipt")
    if set(value) != ROOT_KEYS:
        raise ValidationError("authorized app surface receipt keys are not closed")
    if (value["schemaId"] != SCHEMA_ID
            or type(value["schemaVersion"]) is not int
            or value["schemaVersion"] != 1):
        raise ValidationError("authorized app surface receipt schema is unsupported")
    raw_sources = value["sourceFiles"]
    if not isinstance(raw_sources, list):
        raise ValidationError("authorized source files must be an array")
    sources: list[dict[str, str]] = []
    for record in raw_sources:
        if not isinstance(record, dict) or set(record) != SOURCE_KEYS:
            raise ValidationError("authorized source record keys are not closed")
        path = record["path"]
        digest = record["sha256"]
        if (not isinstance(path, str) or SOURCE_PATH.fullmatch(path) is None
                or not isinstance(digest, str)
                or re.fullmatch(r"[0-9A-F]{64}", digest) is None):
            raise ValidationError("authorized source record is invalid")
        sources.append({"path": path, "sha256": digest})
    if sources != sorted(sources, key=lambda record: record["path"]):
        raise ValidationError("authorized source records are not sorted")
    if len({record["path"] for record in sources}) != len(sources):
        raise ValidationError("authorized source records are duplicated")
    if sources != _source_records(Path(source_root)):
        raise ValidationError("reviewed source inventory or hashes changed")
    raw_descriptors = value["classDescriptors"]
    if (not isinstance(raw_descriptors, list) or not raw_descriptors
            or len(raw_descriptors) > MAX_CLASSES
            or raw_descriptors != sorted(raw_descriptors)
            or len(raw_descriptors) != len(set(raw_descriptors))
            or any(not isinstance(item, str) or DESCRIPTOR.fullmatch(item) is None
                   for item in raw_descriptors)):
        raise ValidationError("reviewed class descriptor inventory is invalid")
    return tuple(raw_descriptors)
