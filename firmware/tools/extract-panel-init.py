#!/usr/bin/env python3
"""Validate a recovered E87 app image and extract its JD9855 init program."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
from typing import Sequence


SOURCE_SIZE = 995_584
SOURCE_SHA256 = "a38b77e27b1dc73cae0fbd8a7c4e3a04c64ff393fb4f27bc92a7578336be0147"
IMAGE_BASE = 0x0C000100

DESCRIPTOR_FILE_OFFSET = 0xEF688
DESCRIPTOR_RUNTIME_ADDRESS = 0x00106E08
DESCRIPTOR_SIZE = 56
PANEL_NAME_ADDRESS = 0x0C0E3E22

INIT_ADDRESS = 0x0C0E59E0
INIT_FILE_OFFSET = 0xE58E0
INIT_SIZE = 657
INIT_SHA256 = "bb0767d3e0bf4ad982725c6a38a9168ddf9e5ba2e3d4d595b1ffbdd17e5b89ff"

PARAM_FILE_OFFSET = 0xEF8A4
PARAM_RUNTIME_ADDRESS = 0x00107024
PARAM_SIZE = 196
PARAM_SHA256 = "bff9d90b248ecfb370877a1cf9677d67e66e4bc1e79e07962cc59e1a87a43a3b"

START = bytes.fromhex("12 34 56 78")
END = bytes.fromhex("87 65 43 21")
DELAY_PREFIX = bytes.fromhex("ff 5a a5 ff")

EXPECTED_PROFILE = {
    "bufferNum": 2,
    "bufferSize": 0x5460,
    "clockPolarity": 0,
    "debugColor": 0x00FF0000,
    "debugEnabled": 0,
    "fps": 90,
    "inFormat": 1,
    "inHeight": 360,
    "inStride": 0,
    "inWidth": 360,
    "lcdHeight": 360,
    "lcdType": 0,
    "lcdWidth": 360,
    "outFormat": 1,
    "pixelType": 0x21,
    "scrHeight": 360,
    "scrWidth": 360,
    "scrX": 0,
    "scrY": 0,
    "spiDataMode": 0,
    "spiMode": 0x21,
}


class ExtractionError(ValueError):
    """The input image does not match the recovered panel evidence."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checked_slice(data: bytes, offset: int, size: int, label: str) -> bytes:
    if offset < 0 or size < 0 or offset > len(data) - size:
        raise ExtractionError(f"{label} range is outside the source image")
    return data[offset:offset + size]


def parse_records(raw: bytes) -> list[bytes]:
    """Parse strictly adjacent marker-delimited JD9855 records."""
    if not raw:
        raise ValueError("init program is empty")

    records: list[bytes] = []
    cursor = 0
    while cursor < len(raw):
        if raw[cursor:cursor + len(START)] != START:
            raise ValueError(f"missing start marker at byte {cursor}")

        body_start = cursor + len(START)
        body_end = raw.find(END, body_start)
        nested_start = raw.find(START, body_start)
        if body_end < 0:
            raise ValueError(f"missing end marker for record {len(records)}")
        if 0 <= nested_start < body_end:
            raise ValueError(f"nested start marker in record {len(records)}")

        body = raw[body_start:body_end]
        if not body:
            raise ValueError(f"empty record {len(records)}")
        if body.startswith(DELAY_PREFIX) and len(body) != len(DELAY_PREFIX) + 1:
            raise ValueError(f"delay record {len(records)} must contain one millisecond byte")

        records.append(body)
        cursor = body_end + len(END)

    return records


def decode_parameter_image(raw: bytes) -> dict[str, int]:
    """Decode the recovered 196-byte dbi_param source image."""
    if len(raw) != PARAM_SIZE:
        raise ValueError(f"parameter image size is {len(raw)}, expected {PARAM_SIZE}")

    values = struct.unpack_from("<20I", raw)
    clock_polarity = struct.unpack_from("<I", raw, 144)[0]
    return {
        "bufferNum": values[7],
        "bufferSize": values[8],
        "clockPolarity": clock_polarity,
        "debugColor": values[14],
        "debugEnabled": values[13],
        "fps": values[15],
        "inFormat": values[11],
        "inHeight": values[10],
        "inStride": values[12],
        "inWidth": values[9],
        "lcdHeight": values[5],
        "lcdType": values[6],
        "lcdWidth": values[4],
        "outFormat": values[18],
        "pixelType": values[17],
        "scrHeight": values[3],
        "scrWidth": values[2],
        "scrX": values[0],
        "scrY": values[1],
        "spiDataMode": values[19],
        "spiMode": values[16],
    }


def validate_descriptor(source: bytes) -> dict[str, int | str]:
    descriptor = checked_slice(
        source,
        DESCRIPTOR_FILE_OFFSET,
        DESCRIPTOR_SIZE,
        "panel descriptor",
    )
    name_address = struct.unpack_from("<I", descriptor, 0)[0]
    row_alignment, column_alignment = descriptor[4:6]
    init_address, init_size, radius, clear_color, parameter_address = (
        struct.unpack_from("<5I", descriptor, 8)
    )

    expected = (
        PANEL_NAME_ADDRESS,
        2,
        2,
        INIT_ADDRESS,
        INIT_SIZE,
        180,
        0xFFFFFFFF,
        PARAM_RUNTIME_ADDRESS,
    )
    actual = (
        name_address,
        row_alignment,
        column_alignment,
        init_address,
        init_size,
        radius,
        clear_color,
        parameter_address,
    )
    if actual != expected:
        raise ExtractionError("panel descriptor differs from recovered JD9855 values")

    name_offset = name_address - IMAGE_BASE
    name = checked_slice(source, name_offset, len(b"jd9855\0"), "panel name")
    if name != b"jd9855\0":
        raise ExtractionError("panel descriptor name is not jd9855")

    return {
        "columnAlignment": column_alignment,
        "fileOffset": DESCRIPTOR_FILE_OFFSET,
        "initAddress": init_address,
        "initSize": init_size,
        "name": "jd9855",
        "nameAddress": name_address,
        "parameterAddress": parameter_address,
        "radius": radius,
        "rowAlignment": row_alignment,
        "runtimeAddress": DESCRIPTOR_RUNTIME_ADDRESS,
    }


def validate_program(raw: bytes) -> list[bytes]:
    if sha256(raw) != INIT_SHA256.lower():
        raise ExtractionError("init program SHA-256 differs from recovered value")
    records = parse_records(raw)
    if len(records) != 51:
        raise ExtractionError(f"init program has {len(records)} records, expected 51")

    expected_tail = [
        bytes.fromhex("ff 5a a5 ff 0a"),
        bytes.fromhex("4c 00"),
        bytes.fromhex("35 00"),
        bytes.fromhex("3a 55"),
        bytes.fromhex("11"),
        bytes.fromhex("ff 5a a5 ff 78"),
        bytes.fromhex("29"),
        bytes.fromhex("ff 5a a5 ff 14"),
    ]
    if records[-len(expected_tail):] != expected_tail:
        raise ExtractionError("init program tail differs from recovered sequence")

    commands = [record[0] for record in records if not record.startswith(DELAY_PREFIX)]
    if any(command in {0x36, 0x2A, 0x2B} for command in commands):
        raise ExtractionError("init program contains a forbidden address or MADCTL command")
    return records


def validate_source(source: bytes, source_path: Path) -> tuple[bytes, dict[str, object]]:
    if len(source) != SOURCE_SIZE:
        raise ExtractionError(f"source size is {len(source)}, expected {SOURCE_SIZE}")

    source_digest = sha256(source)
    if source_digest != SOURCE_SHA256.lower():
        raise ExtractionError("source SHA-256 differs from the recovered app")
    if INIT_ADDRESS - IMAGE_BASE != INIT_FILE_OFFSET:
        raise ExtractionError("init address does not map to the pinned file offset")

    descriptor = validate_descriptor(source)
    raw = checked_slice(source, INIT_FILE_OFFSET, INIT_SIZE, "init program")
    records = validate_program(raw)

    parameter = checked_slice(source, PARAM_FILE_OFFSET, PARAM_SIZE, "parameter image")
    parameter_digest = sha256(parameter)
    if parameter_digest != PARAM_SHA256.lower():
        raise ExtractionError("parameter image SHA-256 differs from recovered value")
    profile = decode_parameter_image(parameter)
    if profile != EXPECTED_PROFILE:
        raise ExtractionError("parameter image differs from the recovered DBI profile")

    report: dict[str, object] = {
        "descriptor": descriptor,
        "init": {
            "address": INIT_ADDRESS,
            "fileOffset": INIT_FILE_OFFSET,
            "recordCount": len(records),
            "sha256": sha256(raw),
            "size": len(raw),
        },
        "parameter": {
            "fileOffset": PARAM_FILE_OFFSET,
            "profile": profile,
            "runtimeAddress": PARAM_RUNTIME_ADDRESS,
            "sha256": parameter_digest,
            "size": len(parameter),
        },
        "source": {
            "imageBase": IMAGE_BASE,
            "path": str(source_path),
            "sha256": source_digest,
            "size": len(source),
        },
    }
    return raw, report


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Validate a recovered E87 app and extract its JD9855 init program.",
    )
    result.add_argument("--input", required=True, type=Path, help="recovered plaintext app.bin")
    result.add_argument(
        "--output",
        type=Path,
        help="optional destination for the exact 657-byte init program",
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        source_path = arguments.input
        source = source_path.read_bytes()
        raw, report = validate_source(source, source_path)
        if arguments.output is not None:
            if arguments.output.resolve() == source_path.resolve():
                raise ExtractionError("output path must differ from input path")
            atomic_write(arguments.output, raw)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
