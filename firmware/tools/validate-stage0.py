#!/usr/bin/env python3
"""Closed-schema validation helpers for the E87 Stage 0-H pipeline."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Iterable


LOCK_DIGESTS = {
    "model1552-package.lock.json": "EFD3878979F029C56DA16E863EB89955E22D9B222046211A84AAC7BE1F3BA122",
    "packaging.lock.json": "28E6C1DEF70F894F89FDC7FFB8527F204688888C58EEDC052CD8A36F3AEBC003",
    "toolchain.lock.json": "60D72D942FC66E89303FD059AC9904F9167AAB743A21E78AB7230AA6B5B2300D",
}
LOCK_SCHEMAS = {
    "model1552-package.lock.json": "e87-stage0-model1552-package-lock-v1",
    "packaging.lock.json": "e87-stage0-packaging-lock-v1",
    "toolchain.lock.json": "e87-stage0-toolchain-lock-v1",
}
HEX64 = re.compile(r"[0-9A-F]{64}\Z")
DELIVERY_FIXED = {
    "app.bin",
    "jl_isd.bin",
    "jl_isd.fw",
    "update.ufw",
    "independently-made.ufw",
    "update.qix",
    "manifest.json",
    "SHA256SUMS",
}


def canonical_json(value: object) -> bytes:
    _reject_non_json_types(value)
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("ascii")


def _reject_non_json_types(value: object, location: str = "$") -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_non_json_types(item, f"{location}[{index}]")
        return
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError(f"non-string key at {location}")
        for key, item in value.items():
            _reject_non_json_types(item, f"{location}.{key}")
        return
    raise ValueError(f"unsupported JSON type at {location}")


def _closed_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_closed_json(path: Path) -> object:
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("ascii")
        value = json.loads(
            text,
            object_pairs_hook=_closed_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"invalid JSON constant: {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid canonical JSON: {path}") from error
    if canonical_json(value) != raw:
        raise ValueError(f"noncanonical JSON: {path}")
    return value


def validate_lock_document(filename: str, value: object) -> None:
    if filename not in LOCK_SCHEMAS:
        raise ValueError(f"unknown Stage 0 lock: {filename}")
    if not isinstance(value, dict):
        raise ValueError("lock root must be an object")
    if value.get("schema") != LOCK_SCHEMAS[filename]:
        raise ValueError("wrong lock schema")
    canonical_json(value)

    def visit(item: object, location: str = "$") -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                child_location = f"{location}.{key}"
                if key == "sha256" or key.endswith("Sha256"):
                    if not isinstance(child, str) or HEX64.fullmatch(child) is None:
                        raise ValueError(f"invalid sha256 at {child_location}")
                visit(child, child_location)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{location}[{index}]")

    visit(value)


def validate_lock(filename: str, value: object) -> None:
    if filename not in LOCK_DIGESTS:
        raise ValueError(f"unknown Stage 0 lock: {filename}")
    raw = canonical_json(value)
    digest = hashlib.sha256(raw).hexdigest().upper()
    if digest != LOCK_DIGESTS[filename]:
        raise ValueError(f"lock value drift: {filename}")
    validate_lock_document(filename, value)


def load_stage0_locks(repository_root: Path) -> dict[str, object]:
    root = Path(repository_root)
    lock_root = root / "firmware/locks"
    result = {}
    for filename in sorted(LOCK_DIGESTS):
        path = lock_root / filename
        value = load_closed_json(path)
        validate_lock(filename, value)
        result[filename] = value
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest().upper()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _reject_symlink_components(path: Path) -> None:
    if not path.is_absolute():
        raise ValueError("path must be absolute")
    cursor = Path(path.anchor)
    for part in path.parts[1:]:
        cursor /= part
        if cursor.exists() or cursor.is_symlink():
            if stat.S_ISLNK(cursor.lstat().st_mode):
                raise ValueError(f"symlink path component: {cursor}")


def validate_output_root(
    root: Path,
    forbidden_roots: Iterable[Path],
    *,
    require_empty: bool = True,
) -> Path:
    path = Path(root)
    _reject_symlink_components(path)
    if not path.exists() or not path.is_dir():
        raise ValueError("output root must be an existing directory")
    resolved = path.resolve(strict=True)
    if resolved == Path(resolved.anchor):
        raise ValueError("filesystem root is forbidden")
    for forbidden in forbidden_roots:
        forbidden_path = Path(forbidden)
        if not forbidden_path.is_absolute():
            raise ValueError("forbidden roots must be absolute")
        forbidden_resolved = forbidden_path.resolve(strict=False)
        if _is_relative_to(resolved, forbidden_resolved) or _is_relative_to(
            forbidden_resolved, resolved
        ):
            raise ValueError("output root overlaps a protected root")
    if require_empty and any(resolved.iterdir()):
        raise ValueError("output root must be empty")
    return resolved


def validate_relative_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise ValueError("invalid relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("invalid relative path")
    return path


def validate_delivery_allowlist(root: Path, expected: set[str] | None = None) -> None:
    expected_names = DELIVERY_FIXED if expected is None else set(expected)
    path = Path(root)
    names = set()
    for entry in path.iterdir():
        if entry.is_symlink() or not entry.is_file():
            raise ValueError(f"non-regular delivery entry: {entry.name}")
        names.add(entry.name)
    if names != expected_names:
        raise ValueError(
            f"delivery allowlist mismatch: missing={sorted(expected_names - names)}, "
            f"extra={sorted(names - expected_names)}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--repository-root", type=Path, required=True)
    args = parser.parse_args(argv)
    load_stage0_locks(args.repository_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
