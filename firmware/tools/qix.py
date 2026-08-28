#!/usr/bin/env python3
"""Strict encoder, decoder, and create-only CLI for JieLi Qix envelopes."""
from __future__ import annotations

import argparse
import importlib.util
import os
import stat
import struct
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Sequence


MAGIC = b"\xBC\xAF"
QIX_TYPE = 1
VERSION_BYTES = 10
RESERVED_BYTES = 8
HEADER_BYTES = 27
_HEADER = struct.Struct("<2sB10sI8sH")
_MAX_PAYLOAD_BYTES = 0xFFFFFFFF


def _require_bytes(value: object, name: str) -> bytes:
    if not isinstance(value, bytes):
        raise TypeError(f"{name} must be bytes")
    return value


def crc16_ccitt_false(data: bytes) -> int:
    """Return CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF)."""
    payload = _require_bytes(data, "data")
    crc = 0xFFFF
    for byte in payload:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ (0x1021 if crc & 0x8000 else 0)) & 0xFFFF
    return crc


def _encode_version(version: str) -> bytes:
    if not isinstance(version, str):
        raise TypeError("version must be a string")
    if not version or "\x00" in version:
        raise ValueError("version must be nonempty and contain no NUL")
    try:
        encoded = version.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("version must be ASCII") from exc
    if len(encoded) > VERSION_BYTES:
        raise ValueError("version is longer than ten bytes")
    return encoded.ljust(VERSION_BYTES, b"\x00")


def _decode_version(field: bytes) -> str:
    if len(field) != VERSION_BYTES:
        raise ValueError("invalid version field size")
    nul = field.find(b"\x00")
    if nul < 0:
        encoded = field
    else:
        encoded = field[:nul]
        if any(field[nul:]):
            raise ValueError("noncanonical version padding")
    if not encoded:
        raise ValueError("empty version")
    try:
        return encoded.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("version is not ASCII") from exc


@lru_cache(maxsize=1)
def _load_ufw_validator():
    tool = Path(__file__).with_name("ufw.py")
    if not tool.is_file() or tool.is_symlink():
        raise ValueError("UFW validator is unavailable")
    name = "_e87_stage0_ufw_for_qix"
    spec = importlib.util.spec_from_file_location(name, tool)
    if spec is None or spec.loader is None:
        raise ValueError("cannot load UFW validator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    validator = getattr(module, "parse_ufw", None)
    if not callable(validator):
        raise ValueError("UFW validator has no parse_ufw API")
    return validator


def _validate_ufw(payload: bytes) -> None:
    _load_ufw_validator()(payload)


def wrap_qix(ufw: bytes, version: str) -> bytes:
    """Validate *ufw* and wrap it in the canonical 27-byte Qix envelope."""
    payload = _require_bytes(ufw, "ufw")
    version_field = _encode_version(version)
    if not payload:
        raise ValueError("Qix payload must not be empty")
    if len(payload) > _MAX_PAYLOAD_BYTES:
        raise ValueError("Qix payload does not fit uint32")
    _validate_ufw(payload)
    crc = crc16_ccitt_false(payload)
    return _HEADER.pack(
        MAGIC,
        QIX_TYPE,
        version_field,
        len(payload),
        bytes(RESERVED_BYTES),
        crc,
    ) + payload


def parse_qix(data: bytes, expected_version: str | None = None) -> dict[str, object]:
    """Parse and validate a complete Qix file, including its embedded UFW."""
    encoded = _require_bytes(data, "data")
    if len(encoded) < HEADER_BYTES:
        raise ValueError("truncated Qix header")

    magic, type_code, version_field, payload_size, reserved, stored_crc = _HEADER.unpack_from(encoded)
    if magic != MAGIC:
        raise ValueError("invalid Qix magic")
    if type_code != QIX_TYPE:
        raise ValueError("invalid Qix type")
    version = _decode_version(version_field)
    if expected_version is not None:
        expected = _decode_version(_encode_version(expected_version))
        if version != expected:
            raise ValueError("unexpected Qix version")
    if reserved != bytes(RESERVED_BYTES):
        raise ValueError("nonzero Qix reserved bytes")
    if payload_size == 0:
        raise ValueError("empty Qix payload")

    actual_payload_size = len(encoded) - HEADER_BYTES
    if payload_size != actual_payload_size:
        raise ValueError("Qix payload length mismatch or trailing bytes")
    payload = encoded[HEADER_BYTES:]
    actual_crc = crc16_ccitt_false(payload)
    if stored_crc != actual_crc:
        raise ValueError("Qix payload CRC mismatch")
    _validate_ufw(payload)
    return {
        "payload": payload,
        "payloadCrc16": actual_crc,
        "payloadSize": payload_size,
        "type": type_code,
        "version": version,
    }


def unwrap_qix(data: bytes) -> tuple[str, bytes]:
    """Return ``(version, payload)`` after complete Qix/UFW validation."""
    parsed = parse_qix(data)
    return parsed["version"], parsed["payload"]  # type: ignore[return-value]


def _reject_symlink_components(path: Path) -> None:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise ValueError(f"path must be absolute: {candidate}")
    cursor = Path(candidate.anchor)
    for component in candidate.parts[1:]:
        cursor /= component
        try:
            mode = cursor.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise ValueError(f"path contains a symlink component: {cursor}")


def _read_regular_file(path: Path) -> bytes:
    _reject_symlink_components(path)
    if path.is_symlink():
        raise ValueError(f"input must not be a symlink: {path}")
    try:
        mode = path.stat().st_mode
    except OSError as exc:
        raise ValueError(f"cannot stat input: {path}") from exc
    if not stat.S_ISREG(mode):
        raise ValueError(f"input is not a regular file: {path}")
    return path.read_bytes()


def _atomic_create(path: Path, data: bytes) -> None:
    _reject_symlink_components(path)
    destination = os.fspath(path)
    if os.path.lexists(destination):
        raise ValueError(f"output already exists: {path}")
    parent = path.parent
    if parent.is_symlink() or not parent.is_dir():
        raise ValueError(f"output parent must be a real directory: {parent}")

    descriptor, temporary = tempfile.mkstemp(
        dir=os.fspath(parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    wrap = commands.add_parser("wrap")
    wrap.add_argument("--input", required=True, type=Path)
    wrap.add_argument("--output", required=True, type=Path)
    wrap.add_argument("--version", required=True)

    unwrap = commands.add_parser("unwrap")
    unwrap.add_argument("--input", required=True, type=Path)
    unwrap.add_argument("--output", required=True, type=Path)
    unwrap.add_argument("--expected-version")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        source = _read_regular_file(args.input)
        if args.command == "wrap":
            output = wrap_qix(source, args.version)
        else:
            parsed = parse_qix(source, expected_version=args.expected_version)
            output = parsed["payload"]
            if not isinstance(output, bytes):
                raise ValueError("Qix parser returned a non-byte payload")
        _atomic_create(args.output, output)
    except (OSError, TypeError, ValueError) as exc:
        print(f"qix: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
