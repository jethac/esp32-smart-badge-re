#!/usr/bin/env python3
"""Independent model-1552 JieLi new-firmware membership verifier."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import struct
import sys
from dataclasses import dataclass
from pathlib import Path


JLFS_HEADER = struct.Struct("<HHIIBBH16s")
FLASH_SIZE = 0xFB000
APP_BASE = 0x2000
APP_END = 0xF5200
EXPECTED_ENTRY = 0x0C000100
EXPECTED_KEY = 0x9847
REFERENCE_PROFILE = "model-1552-reference"
GENERATED_LAB_PROFILE = "generated-lab"
PROOF_PROFILES = (REFERENCE_PROFILE, GENERATED_LAB_PROFILE)


class JlFwError(ValueError):
    pass


@dataclass(frozen=True)
class EmbeddedApp:
    data: bytes
    offset: int
    size: int
    entry_address: int
    chip_key: int
    sha256: str
    app_entry_count: int


@dataclass(frozen=True)
class FwEnvelope:
    kind: str
    logical_ufw: bytes
    flash: bytes
    opaque_guards: bytes
    flash_physical_offset: int


def select_unique_fw_interpretation(
    raw: FwEnvelope | None,
    direct: FwEnvelope | None,
    fwsc: FwEnvelope | None,
) -> FwEnvelope:
    """Return the sole valid explicit envelope interpretation."""
    candidates = [candidate for candidate in (raw, direct, fwsc) if candidate is not None]
    if not candidates:
        raise JlFwError("container has zero valid UFW interpretations")
    if len(candidates) != 1:
        raise JlFwError("container has ambiguous UFW interpretations")
    return candidates[0]


def crc16_xmodem(data: bytes, seed: int = 0) -> int:
    if not isinstance(data, bytes) or isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 0xFFFF:
        raise TypeError("invalid CRC input")
    state = seed
    for byte in data:
        state ^= byte << 8
        for _ in range(8):
            state = ((state << 1) ^ (0x1021 if state & 0x8000 else 0)) & 0xFFFF
    return state


def jl_enc(data: bytes, key: int) -> bytes:
    if not isinstance(data, bytes) or isinstance(key, bool) or not isinstance(key, int) or not 0 <= key <= 0xFFFF:
        raise TypeError("invalid JieLi cipher input")
    state = key
    output = bytearray(len(data))
    for index, byte in enumerate(data):
        output[index] = byte ^ (state & 0xFF)
        state = ((state << 1) ^ (0x1021 if state & 0x8000 else 0)) & 0xFFFF
    return bytes(output)


def _decode_name(field: bytes) -> str:
    prefix = field.split(b"\0", 1)[0]
    if not prefix:
        raise JlFwError("empty JLFS name")
    try: name = prefix.decode("ascii")
    except UnicodeDecodeError as error: raise JlFwError("non-ASCII JLFS name") from error
    if "/" in name or "\\" in name or name in (".", ".."):
        raise JlFwError("path-like JLFS name")
    return name


def _parse_header(decoded: bytes, *, location: int) -> dict[str, int | str | bytes]:
    if len(decoded) != JLFS_HEADER.size:
        raise JlFwError("truncated JLFS header")
    hcrc, dcrc, offset, size, flags, reserved, index, name_field = JLFS_HEADER.unpack(decoded)
    if crc16_xmodem(decoded[2:]) != hcrc:
        raise JlFwError(f"JLFS header CRC mismatch at 0x{location:X}")
    return {"dataCrc": dcrc, "flags": flags, "index": index, "name": _decode_name(name_field), "nameField": name_field, "offset": offset, "reserved": reserved, "size": size}


def _parse_top_header(flash: bytes, offset: int) -> dict[str, int | str | bytes]:
    return _parse_header(jl_enc(flash[offset:offset + 32], 0xFFFF), location=offset)


def _derive_chip_key(blob: bytes) -> int:
    if len(blob) < 34:
        raise JlFwError("truncated chip-key blob")
    material = blob[:32]
    if int.from_bytes(blob[32:34], "little") != crc16_xmodem(material):
        raise JlFwError("chip-key material CRC mismatch")
    threshold = sum(material[:16]) & 0xFF
    if threshold > 0xDF: threshold = 0xAA
    elif threshold < 0x11: threshold = 0x55
    key = 0
    for bit in range(16):
        if threshold > (material[16 + bit] ^ material[15 - bit]): key |= 1 << bit
    return key


def _decode_sfc(flash: bytes, key: int) -> bytes:
    decoded = bytearray(flash)
    for block in range(APP_BASE, len(flash), 32):
        end = min(block + 32, len(flash))
        block_key = key ^ ((block - APP_BASE) >> 2)
        decoded[block:end] = jl_enc(flash[block:end], block_key & 0xFFFF)
    return bytes(decoded)


def _validate_flash_header(flash: bytes) -> None:
    if len(flash) != FLASH_SIZE:
        raise JlFwError("model-1552 flash image must be exactly 0xFB000 bytes")
    decoded = jl_enc(flash[:32], 0xFFFF)
    if int.from_bytes(decoded[:2], "little") != crc16_xmodem(decoded[2:]):
        raise JlFwError("flash header CRC mismatch")
    if flash[16:22] != b"AC707N":
        raise JlFwError("wrong flash PID")


def _validate_top_chain(flash: bytes) -> tuple[int, int]:
    headers = [_parse_top_header(flash, offset) for offset in (0x20, 0x40, 0x60, 0x80, 0xA0)]
    if [item["name"] for item in headers[:4]] != ["uboot.boot", "isd_config.ini", "app_dir_head", "key_mac"]:
        raise JlFwError("unexpected top-level JLFS chain")
    config = headers[1]
    config_offset, config_size = int(config["offset"]), int(config["size"])
    if config_offset > len(flash) or config_size > len(flash) - config_offset:
        raise JlFwError("configuration bounds overflow")
    config_data = flash[config_offset:config_offset + config_size]
    if crc16_xmodem(config_data) != int(config["dataCrc"]):
        raise JlFwError("configuration data CRC mismatch")
    key = _derive_chip_key(config_data)
    app_dir = headers[2]
    if (int(app_dir["offset"]), int(app_dir["size"]), int(app_dir["flags"]), int(app_dir["index"])) != (APP_BASE, 0xFFFFFFFF, 0x81, 0):
        raise JlFwError("unexpected app directory descriptor")
    return key, int(app_dir["offset"])


def _validate_reservations(decoded: bytes) -> None:
    ext = _parse_header(decoded[0xF5200:0xF5220], location=0xF5200)
    if (ext["name"], int(ext["size"]), int(ext["flags"])) != ("EXT_RESERVED", 0xA0, 0x93):
        raise JlFwError("missing reserved-range directory")
    if crc16_xmodem(decoded[0xF5220:0xF52A0]) != int(ext["dataCrc"]):
        raise JlFwError("reserved-range directory CRC mismatch")
    expected = [("UIRES", 0x180000, 0x15E000, 0), ("USER", 0x2DE000, 0x28000, 0), ("WATCH", 0x306000, 0x1000, 0), ("INORFS", 0x307000, 0x4F8000, 1)]
    actual = []
    for index in range(4):
        location = 0xF5220 + index * 32
        item = _parse_header(decoded[location:location + 32], location=location)
        actual.append((item["name"], int(item["offset"]), int(item["size"]), int(item["index"])))
    if actual != expected:
        raise JlFwError("reserved-range table drift")


def extract_embedded_app(
    flash: bytes,
    *,
    expected_entry_address: int = EXPECTED_ENTRY,
    proof_profile: str = REFERENCE_PROFILE,
) -> EmbeddedApp:
    if not isinstance(flash, bytes): raise TypeError("flash must be bytes")
    if proof_profile not in PROOF_PROFILES: raise JlFwError("unknown new-flash proof profile")
    if proof_profile == REFERENCE_PROFILE:
        _validate_flash_header(flash)
    else:
        if len(flash) < APP_BASE + 64:
            raise JlFwError("generated LAB flash image is truncated")
        decoded_header = jl_enc(flash[:32], 0xFFFF)
        if int.from_bytes(decoded_header[:2], "little") != crc16_xmodem(decoded_header[2:]):
            raise JlFwError("flash header CRC mismatch")
        if flash[16:22] != b"AC707N":
            raise JlFwError("wrong flash PID")
    key, app_base = _validate_top_chain(flash)
    if key != EXPECTED_KEY or app_base != APP_BASE:
        raise JlFwError("wrong chip key or app base")
    decoded = _decode_sfc(flash, key)
    app_head = _parse_header(decoded[APP_BASE:APP_BASE + 32], location=APP_BASE)
    expected_size = 0xF3200 if proof_profile == REFERENCE_PROFILE else len(decoded) - APP_BASE
    if (app_head["name"], int(app_head["offset"]), int(app_head["size"]), int(app_head["flags"])) != ("app_area_head", expected_entry_address, expected_size, 0x83):
        raise JlFwError("application-area identity mismatch")
    app_area_end = APP_BASE + int(app_head["size"])
    expected_end = APP_END if proof_profile == REFERENCE_PROFILE else len(decoded)
    if app_area_end != expected_end or app_area_end > len(decoded):
        raise JlFwError("application-area bounds mismatch")
    if crc16_xmodem(decoded[APP_BASE + 32:app_area_end]) != int(app_head["dataCrc"]):
        raise JlFwError("application-area CRC mismatch")
    entries = []
    for index in range(64):
        location = APP_BASE + 32 + index * 32
        if location + 32 > app_area_end: raise JlFwError("unterminated app directory")
        item = _parse_header(decoded[location:location + 32], location=location)
        entries.append(item)
        if int(item["index"]) != 0: break
    else: raise JlFwError("unterminated app directory")
    apps = [item for item in entries if item["name"] == "app.bin"]
    if len(apps) != 1: raise JlFwError("application entry must be unique")
    app = apps[0]
    offset = APP_BASE + int(app["offset"]); size = int(app["size"])
    if offset < APP_BASE + 32 or offset > app_area_end or size > app_area_end - offset:
        raise JlFwError("application data bounds mismatch")
    data = decoded[offset:offset + size]
    if crc16_xmodem(data) != int(app["dataCrc"]):
        raise JlFwError("application data CRC mismatch")
    if proof_profile == REFERENCE_PROFILE:
        _validate_reservations(decoded)
    return EmbeddedApp(data=data, offset=offset, size=size, entry_address=int(app_head["offset"]), chip_key=key, sha256=hashlib.sha256(data).hexdigest().upper(), app_entry_count=len(apps))


def _load_ufw_module():
    path = Path(__file__).with_name("ufw.py")
    if not path.is_file():
        raise JlFwError("UFW validator is unavailable")
    spec = importlib.util.spec_from_file_location("e87_stage0_jlfw_ufw", path)
    if spec is None or spec.loader is None: raise JlFwError("cannot load UFW validator")
    module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module)
    return module


def _flash_from_parsed(parsed) -> bytes:
    matches = [entry for entry in parsed["entries"] if entry["name"] == "flash.bin" and entry["typeCode"] == 0]
    if len(matches) != 1: raise JlFwError("UFW must contain one flash.bin")
    data = matches[0]["data"]
    if not isinstance(data, bytes): raise JlFwError("invalid flash member")
    return data


def collect_container_candidates(
    data: bytes,
    *,
    proof_profile: str = REFERENCE_PROFILE,
) -> tuple[FwEnvelope | None, FwEnvelope | None, FwEnvelope | None]:
    if not isinstance(data, bytes): raise TypeError("container must be bytes")
    if proof_profile not in PROOF_PROFILES: raise JlFwError("unknown new-flash proof profile")
    raw = None
    try:
        extract_embedded_app(data, proof_profile=proof_profile)
        raw = FwEnvelope("RAW_JL_NEW_FW", b"", data, b"", 0)
    except (ValueError, KeyError, TypeError):
        pass

    ufw = _load_ufw_module(); direct = None; fwsc = None
    try:
        parsed = ufw.parse_ufw(data)
        flash = _flash_from_parsed(parsed)
        logical_offset = next(entry["offset"] for entry in parsed["entries"] if entry["name"] == "flash.bin")
        direct = FwEnvelope("DIRECT_UFW", data, flash, b"", int(logical_offset))
    except (ValueError, KeyError, TypeError): pass
    if len(data) >= 960:
        logical = b"".join(data[index * 48:index * 48 + 47] for index in range(20)) + data[960:]
        guards = bytes(data[index * 48 + 47] for index in range(20))
        try:
            parsed = ufw.parse_ufw(logical)
            flash = _flash_from_parsed(parsed)
            logical_offset = next(entry["offset"] for entry in parsed["entries"] if entry["name"] == "flash.bin")
            physical_offset = int(logical_offset) + (20 if int(logical_offset) >= 940 else int(logical_offset) // 47 + 1)
            fwsc = FwEnvelope("FWSC_20X48", logical, flash, guards, physical_offset)
        except (ValueError, KeyError, TypeError): pass
    return raw, direct, fwsc


def extract_flash_from_jl_isd_fw(data: bytes, *, proof_profile: str = REFERENCE_PROFILE) -> FwEnvelope:
    return select_unique_fw_interpretation(*collect_container_candidates(data, proof_profile=proof_profile))


def classify_container(data: bytes) -> str:
    """Classify one fully validated raw or explicitly wrapped firmware image."""
    if not isinstance(data, bytes):
        raise TypeError("container must be bytes")
    candidates = collect_container_candidates(data)
    selected = select_unique_fw_interpretation(*candidates)
    if selected is candidates[0]:
        return "RAW_JL_NEW_FW"
    return selected.kind


def prove_embedded_app(container: bytes, expected_app: bytes, *, container_kind: str, expected_entry_address: int = EXPECTED_ENTRY, proof_profile: str = REFERENCE_PROFILE) -> dict[str, object]:
    if not isinstance(expected_app, bytes): raise TypeError("expected app must be bytes")
    if proof_profile not in PROOF_PROFILES: raise JlFwError("unknown new-flash proof profile")
    if container_kind == "jl_isd.bin":
        flash = container; kind = "JL_ISD_BIN"; container_sha = hashlib.sha256(container).hexdigest().upper()
    elif container_kind == "jl_isd.fw":
        envelope = extract_flash_from_jl_isd_fw(container, proof_profile=proof_profile); flash = envelope.flash; kind = envelope.kind; container_sha = hashlib.sha256(container).hexdigest().upper()
    else: raise JlFwError("unknown container kind")
    app = extract_embedded_app(flash, expected_entry_address=expected_entry_address, proof_profile=proof_profile)
    if app.data != expected_app:
        raise JlFwError("embedded app does not equal reviewed app")
    return {"appOffset": app.offset, "appSha256": app.sha256, "appSize": app.size, "containerKind": kind, "containerSha256": container_sha, "entryAddress": f"0x{app.entry_address:08X}", "flashSha256": hashlib.sha256(flash).hexdigest().upper()}


def prove_package_pair(jl_isd_bin: bytes, jl_isd_fw: bytes, expected_app: bytes, *, expected_entry_address: int = EXPECTED_ENTRY, proof_profile: str = REFERENCE_PROFILE) -> dict[str, object]:
    if proof_profile not in PROOF_PROFILES: raise JlFwError("unknown new-flash proof profile")
    envelope = extract_flash_from_jl_isd_fw(jl_isd_fw, proof_profile=proof_profile)
    if jl_isd_bin != envelope.flash: raise JlFwError("jl_isd.bin and jl_isd.fw flash bytes differ")
    bin_proof = prove_embedded_app(jl_isd_bin, expected_app, container_kind="jl_isd.bin", expected_entry_address=expected_entry_address, proof_profile=proof_profile)
    fw_app = extract_embedded_app(envelope.flash, expected_entry_address=expected_entry_address, proof_profile=proof_profile)
    if fw_app.data != expected_app: raise JlFwError("embedded app does not equal reviewed app")
    if bin_proof["appSha256"] != fw_app.sha256: raise JlFwError("package app proofs differ")
    return {"appSha256": bin_proof["appSha256"], "flashEqual": True, "fwEnvelopeKind": envelope.kind}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--container", type=Path, required=True)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--kind", choices=("jl_isd.bin", "jl_isd.fw"), required=True)
    args = parser.parse_args(argv)
    prove_embedded_app(args.container.read_bytes(), args.app.read_bytes(), container_kind=args.kind)
    return 0


if __name__ == "__main__": raise SystemExit(main())
