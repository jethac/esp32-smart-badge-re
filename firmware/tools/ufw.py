#!/usr/bin/env python3
"""Strict independent parser for JieLi CD03 UFW v4 containers.

The pinned native tools remain the only UFW producers. This module only decodes
and qualifies their output; it never executes firmware or contacts a device.
"""
from __future__ import annotations

import hashlib
import re
import struct
from collections.abc import Iterable, Mapping
from typing import Any


HEADER_SIZE = 0x40
ENTRY_SIZE = 0x50
TAIL_SIZE = 0x40
CD03_METADATA_KEY = 0xFFFF
CD03_BLOCK_SIZE = 0x20
CRC_POLYNOMIAL = 0x1021
POST_IMAGE_MAGIC = 0xA55AAA55
TAIL_SIGNATURE = bytes.fromhex("13 92 65 36 73 42")
TAIL_MARKER = b"JLUFW\0"

_HEADER = struct.Struct("<HHIHHI16s4I4I")
_ENTRY = struct.Struct("<BBHHHIIIII36s16s")
_POST_IMAGE = struct.Struct("<II")

_STAGE0_NAMES = (
    "flash.bin",
    "info.log",
    "uboot.version",
    "params_flash.bin",
    "isd_config.ini",
    "v_ota.bin",
    "ota.bin",
    "farg.cfg",
    "blimit.bin",
    "tail.bin",
)
_STAGE0_ENTRY_FACTS = (
    (0x00, 0x400, 0xFB000, 0xFB000, 0, 0),
    (0x02, 0xFB400, 0, 0, 0, 0),
    (0x37, 0xFB400, 0x40, 0x40, 0, 0x40),
    (0xEE, 0xFB440, 0x974, 0x980, 0, 0x980),
    (0x34, 0xFBDC0, 0x679, 0x680, 0, 0x680),
    (0x38, 0xFC440, 0x40, 0x40, 0, 0x40),
    (0x64, 0xFC480, 0x5C88, 0x5CA0, 0, 0),
    (0xFB, 0x102120, 5, 0x20, 0, 0x20),
    (0xA1, 0x102140, 0x90, 0xA0, 0, 0xA0),
    (0xFF, 0x1021E0, 0x40, 0x40, 0, 0),
)
_STAGE0_PROTECTED_RANGES = (
    ("UIRES", 0x180000, 0x15E000),
    ("USER", 0x2DE000, 0x28000),
    ("WATCH", 0x306000, 0x1000),
    ("INORFS", 0x307000, 0x4F8000),
)
_STAGE0_CODE_RANGES = (("CODE", 0, 0xF5200),)
_RESET_DISABLED = b"RESET = PB07_00_0;"
_RESET_FACTORY = b"RESET = PB07_08_0;"
_STAGE0_CHIP_KEY = 0x9847
_STAGE0_POST_IMAGE_SIZE = 0x5A00


class UfwError(ValueError):
    """Raised when a UFW violates its structural or integrity contract."""


def _require_uint(value: object, bits: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise UfwError(f"{label} is not an integer")
    if value < 0 or value >= 1 << bits:
        raise UfwError(f"{label} is outside its unsigned {bits}-bit range")
    return value


def _as_bytes(value: object, label: str) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise UfwError(f"{label} is not bytes-like")
    return bytes(value)


def crc16_xmodem(data: bytes, seed: int = 0) -> int:
    """Return non-reflected CRC-16/XMODEM (poly 0x1021, no final XOR)."""
    source = _as_bytes(data, "CRC input")
    state = _require_uint(seed, 16, "CRC seed")
    for value in source:
        state ^= value << 8
        for _ in range(8):
            state = (
                (state << 1)
                ^ (CRC_POLYNOMIAL if state & 0x8000 else 0)
            ) & 0xFFFF
    return state


def cd03_transform(
    source: bytes, key: int = CD03_METADATA_KEY
) -> bytes:
    """Apply the self-inverse CD03 metadata stream transform."""
    data = _as_bytes(source, "CD03 input")
    state = _require_uint(key, 16, "CD03 key")
    output = bytearray(data)
    for index, value in enumerate(data):
        output[index] = value ^ (state & 0xFF)
        state = (
            (state << 1)
            ^ (CRC_POLYNOMIAL if state & 0x8000 else 0)
        ) & 0xFFFF
    return bytes(output)


def crypt_transform(
    allocation: bytes,
    *,
    key: int,
    item_address: int,
    crypt_offset: int,
    crypt_size: int,
) -> bytes:
    """Transform one member's declared protected range.

    The data pointer begins at crypt_offset, while the CD03 stream address
    begins at item_address. The stream resets every 32 bytes.
    """
    output = bytearray(_as_bytes(allocation, "member allocation"))
    key = _require_uint(key, 16, "member key")
    item_address = _require_uint(item_address, 32, "item address")
    crypt_offset = _require_uint(crypt_offset, 32, "crypt offset")
    crypt_size = _require_uint(crypt_size, 32, "crypt size")
    if crypt_offset > len(output) or crypt_size > len(output) - crypt_offset:
        raise UfwError("member protected range is outside its allocation")

    for block_offset in range(0, crypt_size, CD03_BLOCK_SIZE):
        state = (
            key ^ ((item_address + block_offset) >> 2)
        ) & 0xFFFF
        block_end = min(block_offset + CD03_BLOCK_SIZE, crypt_size)
        for relative in range(block_offset, block_end):
            position = crypt_offset + relative
            output[position] ^= state & 0xFF
            state = (
                (state << 1)
                ^ (CRC_POLYNOMIAL if state & 0x8000 else 0)
            ) & 0xFFFF
    return bytes(output)


def _validate_name(name: object, label: str) -> str:
    if not isinstance(name, str) or not name:
        raise UfwError(f"{label} is empty or not text")
    try:
        encoded = name.encode("ascii")
    except UnicodeEncodeError as exc:
        raise UfwError(f"{label} is not ASCII") from exc
    if len(encoded) > 16:
        raise UfwError(f"{label} exceeds the 16-byte field")
    if name in {".", ".."} or "/" in name or "\\" in name or "\0" in name:
        raise UfwError(f"{label} is path-like")
    if any(value < 0x20 or value > 0x7E for value in encoded):
        raise UfwError(f"{label} contains non-printable characters")
    return name


def _decode_name(field: bytes, label: str) -> str:
    nul = field.find(b"\0")
    if nul >= 0:
        if any(field[nul + 1 :]):
            raise UfwError(f"{label} has nonzero bytes after its NUL")
        field = field[:nul]
    try:
        name = field.decode("ascii")
    except UnicodeDecodeError as exc:
        raise UfwError(f"{label} is not ASCII") from exc
    return _validate_name(name, label)


def validate_entry_layout(
    entries: Iterable[Mapping[str, Any]],
    *,
    image_size: int,
    table_end: int = HEADER_SIZE,
) -> None:
    """Validate decoded names, bounds, protected ranges, and non-overlap."""
    image_size = _require_uint(image_size, 32, "image size")
    table_end = _require_uint(table_end, 32, "table end")
    if table_end > image_size:
        raise UfwError("item table extends beyond the declared image")

    materialized = list(entries)
    if not materialized:
        raise UfwError("UFW has no entries")
    names: set[str] = set()
    extents: list[tuple[int, int, str]] = []

    for position, entry in enumerate(materialized):
        if not isinstance(entry, Mapping):
            raise UfwError(f"entry {position} is not a mapping")
        name = _validate_name(entry.get("name"), f"entry {position} name")
        if name in names:
            raise UfwError(f"duplicate UFW member name: {name}")
        names.add(name)

        offset = _require_uint(entry.get("offset"), 32, f"{name} offset")
        data_size = _require_uint(
            entry.get("dataSize"), 32, f"{name} logical size"
        )
        allocated_size = _require_uint(
            entry.get("allocatedSize"), 32, f"{name} allocated size"
        )
        crypt_offset = _require_uint(
            entry.get("cryptOffset"), 32, f"{name} protected offset"
        )
        crypt_size = _require_uint(
            entry.get("cryptSize"), 32, f"{name} protected size"
        )

        if data_size > allocated_size:
            raise UfwError(f"{name} logical size exceeds its allocation")
        if offset < table_end or offset > image_size:
            raise UfwError(f"{name} offset is outside the declared image")
        if allocated_size > image_size - offset:
            raise UfwError(f"{name} allocation exceeds the declared image")
        if (
            crypt_offset > allocated_size
            or crypt_size > allocated_size - crypt_offset
        ):
            raise UfwError(f"{name} protected range exceeds its allocation")
        if allocated_size:
            extents.append((offset, offset + allocated_size, name))

    extents.sort()
    for previous, current in zip(extents, extents[1:]):
        if current[0] < previous[1]:
            raise UfwError(
                f"UFW member extents overlap: {previous[2]} and {current[2]}"
            )
    if not extents or extents[-1][1] != image_size:
        raise UfwError("last UFW member does not end at image_size")


def _derive_tail_key(tail: bytes) -> int:
    if len(tail) != TAIL_SIZE:
        raise UfwError("tail.bin is not exactly 64 bytes")
    stored_crc = struct.unpack_from("<H", tail, 0x20)[0]
    if stored_crc != crc16_xmodem(tail[:0x20]):
        raise UfwError("tail.bin key-material CRC mismatch")
    if tail[0x22:0x28] != TAIL_SIGNATURE:
        raise UfwError("tail.bin CD03 signature mismatch")
    if tail[0x28:0x30] != bytes(8):
        raise UfwError("tail.bin reserved bytes are nonzero")
    if tail[0x30:0x36] != TAIL_MARKER:
        raise UfwError("tail.bin JLUFW marker mismatch")
    if tail[0x36:0x40] != bytes(10):
        raise UfwError("tail.bin trailing reserved bytes are nonzero")

    threshold = sum(tail[:0x10]) & 0xFF
    if threshold > 0xDF:
        threshold = 0xAA
    elif threshold < 0x11:
        threshold = 0x55
    key = 0
    for bit in range(16):
        if threshold > (tail[0x10 + bit] ^ tail[0x0F - bit]):
            key |= 1 << bit
    return key


def _parse_post_image(
    payload: bytes, image_size: int
) -> dict[str, int | str] | None:
    suffix = payload[image_size:]
    if not suffix:
        return None
    if len(suffix) < _POST_IMAGE.size:
        raise UfwError("post-image suffix is truncated")
    magic, embedded_size = _POST_IMAGE.unpack_from(suffix)
    if magic != POST_IMAGE_MAGIC:
        raise UfwError("post-image magic mismatch")
    if embedded_size != len(suffix) - _POST_IMAGE.size:
        raise UfwError("post-image size mismatch or trailing bytes")
    body = suffix[_POST_IMAGE.size :]
    return {
        "magic": magic,
        "size": embedded_size,
        "bodySha256": hashlib.sha256(body).hexdigest().upper(),
    }


def _parse_ini_hex(ini: bytes, name: str, suffix: str) -> int:
    token = f"{name}_{suffix}".encode("ascii")
    pattern = re.compile(
        rb"(?m)^"
        + re.escape(token)
        + rb"[ \t]*=[ \t]*(0x[0-9A-Fa-f]+);[ \t]*\r?$"
    )
    matches = pattern.findall(ini)
    if len(matches) != 1:
        raise UfwError(
            f"Stage 0-H INI must contain exactly one {token.decode()} value"
        )
    return int(matches[0], 16)


def _parse_protected_ranges(
    ini: bytes,
) -> list[dict[str, int | str]]:
    ranges: list[dict[str, int | str]] = []
    for name, _, _ in _STAGE0_PROTECTED_RANGES:
        ranges.append(
            {
                "address": _parse_ini_hex(ini, name, "ADR"),
                "length": _parse_ini_hex(ini, name, "LEN"),
                "name": name,
            }
        )
    return ranges


def validate_single_bank_layout(
    protected_ranges: Iterable[Mapping[str, Any]],
    populated_ranges: Iterable[tuple[str, int, int]],
) -> None:
    """Reject populated flash extents intersecting protected reservations."""
    protected: list[tuple[int, int, str]] = []
    protected_names: set[str] = set()
    for position, item in enumerate(protected_ranges):
        if not isinstance(item, Mapping):
            raise UfwError(f"protected range {position} is not a mapping")
        name = _validate_name(
            item.get("name"), f"protected range {position} name"
        )
        if name in protected_names:
            raise UfwError(f"duplicate protected range: {name}")
        protected_names.add(name)
        address = _require_uint(
            item.get("address"), 32, f"{name} protected address"
        )
        length = _require_uint(
            item.get("length"), 32, f"{name} protected length"
        )
        if not length or length > 0xFFFFFFFF - address:
            raise UfwError(f"{name} protected range is empty or overflows")
        protected.append((address, address + length, name))

    protected.sort()
    for previous, current in zip(protected, protected[1:]):
        if current[0] < previous[1]:
            raise UfwError(
                f"protected ranges overlap: {previous[2]} and {current[2]}"
            )

    for position, item in enumerate(populated_ranges):
        if not isinstance(item, tuple) or len(item) != 3:
            raise UfwError(f"populated range {position} is not a 3-tuple")
        raw_name, raw_address, raw_length = item
        name = _validate_name(raw_name, f"populated range {position} name")
        address = _require_uint(
            raw_address, 32, f"{name} populated address"
        )
        length = _require_uint(
            raw_length, 32, f"{name} populated length"
        )
        if not length or length > 0xFFFFFFFF - address:
            raise UfwError(f"{name} populated range is empty or overflows")
        end = address + length
        for protected_start, protected_end, protected_name in protected:
            if address < protected_end and protected_start < end:
                raise UfwError(
                    f"{name} overlaps protected range {protected_name}"
                )


def parse_ufw(
    payload: bytes,
    *,
    expected_chip: str | None = None,
    expected_members: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Parse and strictly validate one complete CD03 UFW v4 payload."""
    source = _as_bytes(payload, "UFW payload")
    if len(source) < HEADER_SIZE:
        raise UfwError("UFW payload is shorter than its 64-byte header")

    decoded_header = cd03_transform(source[:HEADER_SIZE])
    (
        header_crc,
        table_crc,
        image_size,
        item_count,
        format_version,
        reserved,
        chip_field,
        *reserved_words,
    ) = _HEADER.unpack(decoded_header)

    if header_crc != crc16_xmodem(decoded_header[2:]):
        raise UfwError("UFW header CRC mismatch")
    chip = _decode_name(chip_field, "chip name")
    if format_version != 4:
        raise UfwError("UFW format version is not 4")
    if reserved != 0x200 or any(reserved_words):
        raise UfwError("UFW header reserved fields are invalid")
    if not item_count:
        raise UfwError("UFW item count is zero")
    if expected_chip is not None and chip != expected_chip:
        raise UfwError(f"unexpected UFW chip: {chip}")

    required_names: tuple[str, ...] | None = None
    if expected_members is not None:
        if isinstance(expected_members, (str, bytes)):
            raise UfwError("expected member list is invalid")
        required_names = tuple(
            _validate_name(name, "expected member name")
            for name in expected_members
        )
        if len(required_names) != item_count:
            raise UfwError("UFW item count does not match expected members")

    table_end = HEADER_SIZE + item_count * ENTRY_SIZE
    if table_end > image_size or table_end > len(source):
        raise UfwError("UFW item table extends beyond the payload")
    raw_table = source[HEADER_SIZE:table_end]
    if table_crc != crc16_xmodem(raw_table):
        raise UfwError("UFW encoded item-table CRC mismatch")

    entries: list[dict[str, Any]] = []
    for position in range(item_count):
        start = HEADER_SIZE + position * ENTRY_SIZE
        decoded = cd03_transform(source[start : start + ENTRY_SIZE])
        (
            type_code,
            type_reserved,
            index,
            data_crc,
            item_version,
            offset,
            data_size,
            allocated_size,
            crypt_offset,
            crypt_size,
            reserved_bytes,
            name_field,
        ) = _ENTRY.unpack(decoded)
        name = _decode_name(name_field, f"entry {position} name")
        if index != position:
            raise UfwError(f"UFW member {name} has a noncanonical index")
        if type_reserved or item_version or any(reserved_bytes):
            raise UfwError(f"UFW member {name} has nonzero reserved fields")
        entries.append(
            {
                "typeCode": type_code,
                "typeReserved": type_reserved,
                "index": index,
                "dataCrc16": data_crc,
                "itemVersion": item_version,
                "offset": offset,
                "dataSize": data_size,
                "allocatedSize": allocated_size,
                "cryptOffset": crypt_offset,
                "cryptSize": crypt_size,
                "name": name,
            }
        )

    actual_names = tuple(entry["name"] for entry in entries)
    if required_names is not None and actual_names != required_names:
        raise UfwError("UFW member order does not match expected profile")
    validate_entry_layout(entries, image_size=image_size, table_end=table_end)

    extents = sorted(
        (
            entry["offset"],
            entry["offset"] + entry["allocatedSize"],
        )
        for entry in entries
        if entry["allocatedSize"]
    )
    cursor = table_end
    for start, end in extents:
        if any(value != 0xFF for value in source[cursor:start]):
            raise UfwError("UFW inter-member padding is not erased")
        cursor = end

    tails = [entry for entry in entries if entry["name"] == "tail.bin"]
    if len(tails) != 1:
        raise UfwError("UFW must contain exactly one tail.bin")
    tail_entry = tails[0]
    if (
        tail_entry["typeCode"] != 0xFF
        or tail_entry["dataSize"] != TAIL_SIZE
        or tail_entry["allocatedSize"] != TAIL_SIZE
        or tail_entry["cryptOffset"] != 0
        or tail_entry["cryptSize"] != 0
    ):
        raise UfwError("tail.bin metadata is invalid")
    tail_raw = source[
        tail_entry["offset"] :
        tail_entry["offset"] + tail_entry["allocatedSize"]
    ]
    chip_key = _derive_tail_key(tail_raw)

    for entry in entries:
        offset = entry["offset"]
        allocated_size = entry["allocatedSize"]
        raw = source[offset : offset + allocated_size]
        decoded = crypt_transform(
            raw,
            key=chip_key,
            item_address=offset,
            crypt_offset=entry["cryptOffset"],
            crypt_size=entry["cryptSize"],
        )
        logical = decoded[: entry["dataSize"]]
        if crc16_xmodem(logical) != entry["dataCrc16"]:
            raise UfwError(f"UFW member {entry['name']} data CRC mismatch")
        if any(value != 0xFF for value in decoded[entry["dataSize"] :]):
            raise UfwError(
                f"UFW member {entry['name']} allocation padding is not erased"
            )
        entry["rawAllocation"] = raw
        entry["decodedAllocation"] = decoded
        entry["data"] = logical

    return {
        "chip": chip,
        "formatVersion": format_version,
        "imageSize": image_size,
        "itemCount": item_count,
        "reserved": reserved,
        "headerCrc16": header_crc,
        "encodedTableCrc16": table_crc,
        "decodedTableCrc16": crc16_xmodem(cd03_transform(raw_table)),
        "entries": entries,
        "tail": {
            "chipKey": chip_key,
            "marker": "JLUFW",
            "signatureHex": TAIL_SIGNATURE.hex(),
        },
        "postImage": _parse_post_image(source, image_size),
    }


def validate_stage0_ufw(payload: bytes) -> dict[str, Any]:
    """Apply the exact recovered AC707N single-bank Stage 0-H profile."""
    parsed = parse_ufw(
        payload,
        expected_chip="AC707N",
        expected_members=_STAGE0_NAMES,
    )
    if parsed["postImage"] is None:
        raise UfwError("Stage 0-H UFW is missing its declared post-image")
    if parsed["tail"]["chipKey"] != _STAGE0_CHIP_KEY:
        raise UfwError("Stage 0-H UFW has the wrong chip key")
    if parsed["postImage"]["size"] != _STAGE0_POST_IMAGE_SIZE:
        raise UfwError("Stage 0-H UFW has the wrong post-image size")

    for entry, expected in zip(parsed["entries"], _STAGE0_ENTRY_FACTS):
        actual = (
            entry["typeCode"],
            entry["offset"],
            entry["dataSize"],
            entry["allocatedSize"],
            entry["cryptOffset"],
            entry["cryptSize"],
        )
        if actual != expected:
            raise UfwError(
                f"Stage 0-H member metadata mismatch for {entry['name']}"
            )

    ini = next(
        entry["data"]
        for entry in parsed["entries"]
        if entry["name"] == "isd_config.ini"
    )
    if ini.count(_RESET_DISABLED) != 1 or _RESET_FACTORY in ini:
        raise UfwError(
            "Stage 0-H reset policy requires exactly one disabled reset value"
        )

    protected_ranges = _parse_protected_ranges(ini)
    expected_ranges = [
        {"address": address, "length": length, "name": name}
        for name, address, length in _STAGE0_PROTECTED_RANGES
    ]
    if protected_ranges != expected_ranges:
        raise UfwError("Stage 0-H protected flash reservations changed")
    validate_single_bank_layout(protected_ranges, _STAGE0_CODE_RANGES)
    parsed["protectedRanges"] = protected_ranges
    return parsed
