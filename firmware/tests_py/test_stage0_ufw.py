#!/usr/bin/env python3
"""Independent synthetic and recovered-golden UFW v4 validation tests."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import struct
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "firmware/tools/ufw.py"
REFERENCE_ROOT = Path(os.environ.get("E87_MODEL1552_REFERENCE_ROOT", "/home/jethac/.local/share/e87-dev/references/model1552-e87-11.1.0.2"))
PAYLOAD = REFERENCE_ROOT / "container/payload.ufw"
NAMES = ["flash.bin", "info.log", "uboot.version", "params_flash.bin", "isd_config.ini", "v_ota.bin", "ota.bin", "farg.cfg", "blimit.bin", "tail.bin"]
ENTRY_FACTS = [
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
]
TAIL = bytes.fromhex("203413d65997fa2e6f41768928f01eb81c4bb5da24a552869e094c5757a3f822faf713926536734200000000000000004a4c5546570000000000000000000000")
HEADER = struct.Struct("<HHIHHI16s4I4I")
ENTRY = struct.Struct("<BBHHHIIIII36s16s")


def crc16(data: bytes, seed: int = 0) -> int:
    state = seed
    for byte in data:
        state ^= byte << 8
        for _ in range(8):
            state = ((state << 1) ^ (0x1021 if state & 0x8000 else 0)) & 0xFFFF
    return state


def meta(source: bytes) -> bytes:
    state = 0xFFFF
    output = bytearray(source)
    for index, value in enumerate(source):
        output[index] = value ^ (state & 0xFF)
        state = ((state << 1) ^ (0x1021 if state & 0x8000 else 0)) & 0xFFFF
    return bytes(output)


def crypt_allocation(source: bytes, key: int, item_address: int) -> bytes:
    output = bytearray(source)
    for block in range(0, len(source), 0x20):
        state = (key ^ ((item_address + block) >> 2)) & 0xFFFF
        for index in range(block, min(block + 0x20, len(source))):
            output[index] ^= state & 0xFF
            state = ((state << 1) ^ (0x1021 if state & 0x8000 else 0)) & 0xFFFF
    return bytes(output)


def name_field(name: str) -> bytes:
    encoded = name.encode("ascii")
    if len(encoded) > 16:
        raise AssertionError(name)
    return encoded.ljust(16, b"\0")


def raw_entry(type_code: int, index: int, data_crc: int, offset: int, data_size: int, allocated: int, crypt_offset: int, crypt_size: int, name: str) -> bytes:
    decoded = ENTRY.pack(type_code, 0, index, data_crc, 0, offset, data_size, allocated, crypt_offset, crypt_size, bytes(36), name_field(name))
    return meta(decoded)


def encode_header(image_size: int, count: int, raw_table: bytes, chip: bytes = b"AC707N", format_version: int = 4, reserved: int = 0x200, reserved2=(0, 0, 0, 0), reserved3=(0, 0, 0, 0)) -> bytes:
    decoded = bytearray(HEADER.pack(0, crc16(raw_table), image_size, count, format_version, reserved, chip.ljust(16, b"\0"), *reserved2, *reserved3))
    decoded[:2] = crc16(decoded[2:]).to_bytes(2, "little")
    return meta(bytes(decoded))


def build_synthetic_ufw() -> bytes:
    flash = bytes(range(64))
    table = b"".join((
        raw_entry(0x00, 0, crc16(flash), 0x140, len(flash), len(flash), 0, 0, "flash.bin"),
        raw_entry(0x02, 1, 0, 0x180, 0, 0, 0, 0, "info.log"),
        raw_entry(0xFF, 2, crc16(TAIL), 0x180, len(TAIL), len(TAIL), 0, 0, "tail.bin"),
    ))
    image_size = 0x1C0
    return encode_header(image_size, 3, table) + table + bytes([0xFF]) * (0x140 - 0x40 - len(table)) + flash + TAIL


def mutate_header(golden: bytes, mutator) -> bytes:
    decoded = bytearray(meta(golden[:0x40])); mutator(decoded)
    count = int.from_bytes(decoded[8:10], "little")
    table_end = 0x40 + count * 0x50
    decoded[2:4] = crc16(golden[0x40:table_end]).to_bytes(2, "little")
    decoded[:2] = crc16(decoded[2:]).to_bytes(2, "little")
    return meta(bytes(decoded)) + golden[0x40:]


def mutate_entry(golden: bytes, index: int, mutator) -> bytes:
    changed = bytearray(golden); start = 0x40 + index * 0x50
    decoded = bytearray(meta(changed[start:start + 0x50])); mutator(decoded)
    changed[start:start + 0x50] = meta(bytes(decoded))
    header = bytearray(meta(changed[:0x40])); count = int.from_bytes(header[8:10], "little")
    header[2:4] = crc16(changed[0x40:0x40 + count * 0x50]).to_bytes(2, "little")
    header[:2] = crc16(header[2:]).to_bytes(2, "little")
    changed[:0x40] = meta(bytes(header))
    return bytes(changed)


def mutate_tail_semantically(golden: bytes, relative: int) -> bytes:
    changed = bytearray(golden); changed[0x1021E0 + relative] ^= 1
    new_crc = crc16(changed[0x1021E0:0x102220])
    return mutate_entry(bytes(changed), 9, lambda entry: entry.__setitem__(slice(4, 6), new_crc.to_bytes(2, "little")))


def make_stage0_output(golden: bytes) -> bytes:
    offset, logical, allocated = 0xFBDC0, 0x679, 0x680
    decoded = crypt_allocation(golden[offset:offset + allocated], 0x9847, offset)
    old = b"RESET = PB07_08_0;"; new = b"RESET = PB07_00_0;"
    if decoded[:logical].count(old) != 1 or len(old) != len(new):
        raise AssertionError("golden reset fixture drift")
    changed_decoded = decoded.replace(old, new, 1)
    changed = bytearray(golden)
    changed[offset:offset + allocated] = crypt_allocation(changed_decoded, 0x9847, offset)
    data_crc = crc16(changed_decoded[:logical])
    return mutate_entry(bytes(changed), 4, lambda entry: entry.__setitem__(slice(4, 6), data_crc.to_bytes(2, "little")))


def mutate_stage0_ini(stage0: bytes, old: bytes, new: bytes) -> bytes:
    if len(old) != len(new):
        raise AssertionError("fixture replacement must preserve length")
    offset, logical, allocated = 0xFBDC0, 0x679, 0x680
    decoded = crypt_allocation(stage0[offset:offset + allocated], 0x9847, offset)
    if decoded[:logical].count(old) != 1:
        raise AssertionError("fixture source occurrence drift")
    changed_decoded = decoded.replace(old, new, 1)
    changed = bytearray(stage0)
    changed[offset:offset + allocated] = crypt_allocation(changed_decoded, 0x9847, offset)
    data_crc = crc16(changed_decoded[:logical])
    return mutate_entry(bytes(changed), 4, lambda entry: entry.__setitem__(slice(4, 6), data_crc.to_bytes(2, "little")))


def rekey_stage0_fixture_to_9846(stage0: bytes) -> bytes:
    old_key, new_key = 0x9847, 0x9846
    changed = bytearray(stage0)
    header = bytearray(meta(stage0[:0x40]))
    count = int.from_bytes(header[8:10], "little")
    entries = [
        bytearray(meta(stage0[0x40 + index * 0x50:0x40 + (index + 1) * 0x50]))
        for index in range(count)
    ]

    encrypted_count = 0
    tail_entry = None
    for entry in entries:
        fields = ENTRY.unpack(entry)
        offset, allocated, crypt_offset, crypt_size = fields[5], fields[7], fields[8], fields[9]
        name = fields[-1].split(b"\0", 1)[0]
        if name == b"tail.bin":
            tail_entry = entry
        if not crypt_size:
            continue
        if crypt_offset != 0 or crypt_size != allocated:
            raise AssertionError("Stage 0 encrypted-allocation shape drift")
        decoded = crypt_allocation(stage0[offset:offset + allocated], old_key, offset)
        changed[offset:offset + allocated] = crypt_allocation(decoded, new_key, offset)
        encrypted_count += 1
    if encrypted_count != 6 or tail_entry is None:
        raise AssertionError("Stage 0 encrypted-member or tail fixture drift")

    tail_fields = ENTRY.unpack(tail_entry)
    tail_offset, tail_size = tail_fields[5], tail_fields[7]
    tail = bytearray(changed[tail_offset:tail_offset + tail_size])
    if len(tail) != 0x40 or tail[0x10] != 0x1C:
        raise AssertionError("Stage 0 tail key-material fixture drift")
    tail[0x10] = 0x12
    tail[0x20:0x22] = crc16(tail[:0x20]).to_bytes(2, "little")
    changed[tail_offset:tail_offset + tail_size] = tail

    raw_records = []
    for entry in entries:
        fields = ENTRY.unpack(entry)
        offset, logical, allocated, crypt_size = fields[5], fields[6], fields[7], fields[9]
        decoded = bytes(changed[offset:offset + allocated])
        if crypt_size:
            decoded = crypt_allocation(decoded, new_key, offset)
        entry[4:6] = crc16(decoded[:logical]).to_bytes(2, "little")
        raw_records.append(meta(bytes(entry)))
    raw_table = b"".join(raw_records)
    table_end = 0x40 + count * 0x50
    changed[0x40:table_end] = raw_table
    header[2:4] = crc16(raw_table).to_bytes(2, "little")
    header[:2] = crc16(header[2:]).to_bytes(2, "little")
    changed[:0x40] = meta(bytes(header))
    return bytes(changed)


def load_tool():
    spec = importlib.util.spec_from_file_location("e87_stage0_ufw", TOOL)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load UFW tool")
    module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module)
    return module


class UfwTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.ufw = load_tool(); cls.golden = PAYLOAD.read_bytes(); cls.stage0 = make_stage0_output(cls.golden)

    def test_literal_crc_metadata_and_nonzero_crypt_offset_vectors(self):
        self.assertEqual(self.ufw.crc16_xmodem(b"123456789"), 0x31C3)
        self.assertEqual(self.ufw.cd03_transform(bytes(range(16)), 0xFFFF).hex(), "ffde9d1c1b3b7afff8c8a96cc2b05598")
        allocation = bytes(5 + 40)
        transformed = self.ufw.crypt_transform(allocation, key=0x9847, item_address=0x400, crypt_offset=5, crypt_size=40)
        self.assertEqual(transformed[:5], bytes(5))
        self.assertEqual(transformed[5:].hex(), "47af5ebc59b264c8902061c2a54a9428508102042952a469f3e6edfbd7ae7dfa4fbf7efcd9b264c8")
        self.assertEqual(self.ufw.crypt_transform(transformed, key=0x9847, item_address=0x400, crypt_offset=5, crypt_size=40), allocation)

    def test_independent_synthetic_full_v4_oracle_parses_without_golden_constants(self):
        synthetic = build_synthetic_ufw()
        parsed = self.ufw.parse_ufw(synthetic, expected_chip="AC707N", expected_members=["flash.bin", "info.log", "tail.bin"])
        self.assertEqual(parsed["imageSize"], 0x1C0)
        self.assertEqual(parsed["itemCount"], 3)
        self.assertEqual(parsed["entries"][0]["data"], bytes(range(64)))
        self.assertEqual(parsed["tail"]["chipKey"], 0x9847)
        self.assertIsNone(parsed["postImage"])

    def test_tail_randomization_equivalence_is_closed_to_proven_fields(self):
        original = build_synthetic_ufw()
        original_key = self.ufw.parse_ufw(original)["tail"]["chipKey"]
        variant = None
        for relative in range(0x20):
            for value in range(256):
                changed = bytearray(original)
                if value == changed[0x180 + relative]:
                    continue
                changed[0x180 + relative] = value
                changed[0x1A0:0x1A2] = crc16(changed[0x180:0x1A0]).to_bytes(2, "little")
                candidate = mutate_entry(bytes(changed), 2, lambda entry: entry.__setitem__(slice(4, 6), crc16(changed[0x180:0x1C0]).to_bytes(2, "little")))
                if self.ufw.parse_ufw(candidate)["tail"]["chipKey"] == original_key:
                    variant = candidate
                    break
            if variant is not None:
                break
        self.assertIsNotNone(variant)
        proof = self.ufw.prove_ufw_payload_equivalence(original, variant)
        self.assertEqual(proof["relation"], "TAIL_RANDOMIZED_PAYLOAD_EQUIVALENT")
        self.assertGreater(proof["differentByteCount"], 0)

        payload_change = bytearray(variant); payload_change[0x140] ^= 1
        with self.assertRaises(ValueError):
            self.ufw.prove_ufw_payload_equivalence(original, bytes(payload_change))
        closure_escape = bytearray(variant); closure_escape[0x3F] ^= 1
        with self.assertRaises(ValueError):
            self.ufw.prove_ufw_payload_equivalence(original, bytes(closure_escape))

    def test_model1552_golden_decodes_exact_header_entries_tail_and_suffix(self):
        self.assertEqual((len(self.golden), hashlib.sha256(self.golden).hexdigest().upper()), (1_080_360, "ECDFAA06377A00056ADB15D3486A4B059ACDE762C0F4A2BC8DCE43E0D120A80B"))
        parsed = self.ufw.parse_ufw(self.golden, expected_chip="AC707N", expected_members=NAMES)
        self.assertEqual({key: parsed[key] for key in ("chip", "formatVersion", "imageSize", "itemCount", "reserved")}, {"chip": "AC707N", "formatVersion": 4, "imageSize": 0x102220, "itemCount": 10, "reserved": 0x200})
        self.assertEqual(parsed["encodedTableCrc16"], 0x9929)
        self.assertEqual(parsed["decodedTableCrc16"], 0x2A07)
        self.assertEqual([entry["name"] for entry in parsed["entries"]], NAMES)
        actual = [(entry["typeCode"], entry["offset"], entry["dataSize"], entry["allocatedSize"], entry["cryptOffset"], entry["cryptSize"]) for entry in parsed["entries"]]
        self.assertEqual(actual, ENTRY_FACTS)
        self.assertEqual(parsed["tail"], {"chipKey": 0x9847, "marker": "JLUFW", "signatureHex": "139265367342"})
        self.assertEqual(parsed["postImage"], {"magic": 0xA55AAA55, "size": 23040, "bodySha256": "3CA44F3A12E08FF12C26E6B87024DB6B7446B8A5A936EA999AC920DABE150FF1"})
        ini = next(entry["data"] for entry in parsed["entries"] if entry["name"] == "isd_config.ini")
        self.assertEqual(ini.count(b"RESET = PB07_08_0;"), 1)

    def test_crc_valid_stage0_output_requires_disabled_reset_and_recovered_single_bank_reservations(self):
        parsed = self.ufw.validate_stage0_ufw(self.stage0)
        ini = next(entry["data"] for entry in parsed["entries"] if entry["name"] == "isd_config.ini")
        self.assertEqual(ini.count(b"RESET = PB07_00_0;"), 1)
        self.assertNotIn(b"RESET = PB07_08_0;", ini)
        self.assertEqual(parsed["protectedRanges"], [
            {"address": 0x180000, "length": 0x15E000, "name": "UIRES"},
            {"address": 0x2DE000, "length": 0x28000, "name": "USER"},
            {"address": 0x306000, "length": 0x1000, "name": "WATCH"},
            {"address": 0x307000, "length": 0x4F8000, "name": "INORFS"},
        ])
        self.ufw.validate_single_bank_layout(parsed["protectedRanges"], [("CODE", 0, 0xF5200)])
        for protected in parsed["protectedRanges"]:
            with self.subTest(protected=protected["name"]):
                with self.assertRaises(ValueError):
                    self.ufw.validate_single_bank_layout(parsed["protectedRanges"], [("MOVED_ENTRY", protected["address"], 0x20)])

        moved = bytearray(ini.replace(b"UIRES_ADR = 0x180000;", b"UIRES_ADR = 0x0F0000;", 1))
        offset, logical, allocated = 0xFBDC0, 0x679, 0x680
        decoded_alloc = crypt_allocation(self.stage0[offset:offset + allocated], 0x9847, offset)
        changed_alloc = moved + decoded_alloc[logical:]
        changed = bytearray(self.stage0); changed[offset:offset + allocated] = crypt_allocation(bytes(changed_alloc), 0x9847, offset)
        changed_crc = crc16(bytes(moved))
        moved_range = mutate_entry(bytes(changed), 4, lambda entry: entry.__setitem__(slice(4, 6), changed_crc.to_bytes(2, "little")))
        with self.assertRaises(ValueError):
            self.ufw.validate_stage0_ufw(moved_range)

    def test_crc_valid_old_missing_and_duplicate_reset_policies_are_rejected_explicitly(self):
        absent = mutate_stage0_ini(self.stage0, b"RESET = PB07_00_0;", b"RESET = PB07_01_0;")
        duplicate = mutate_stage0_ini(self.stage0, b"BTIF_LEN = 0x1000;", b"RESET = PB07_00_0;")
        for name, payload in (("old", self.golden), ("absent", absent), ("duplicate", duplicate)):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "reset"):
                    self.ufw.validate_stage0_ufw(payload)

    def test_stage0_policy_pins_chip_key_and_post_image_size(self):
        rekeyed = rekey_stage0_fixture_to_9846(self.stage0)
        with self.subTest(policy="chip-key"):
            parsed = self.ufw.parse_ufw(rekeyed, expected_chip="AC707N", expected_members=NAMES)
            self.assertEqual(parsed["tail"]["chipKey"], 0x9846)
            self.assertEqual(sum(entry["cryptSize"] != 0 for entry in parsed["entries"]), 6)
            with self.assertRaisesRegex(ValueError, "chip key"):
                self.ufw.validate_stage0_ufw(rekeyed)

        shortened = bytearray(self.stage0[:-1])
        shortened[0x102224:0x102228] = (0x59FF).to_bytes(4, "little")
        with self.subTest(policy="post-image-size"):
            parsed = self.ufw.parse_ufw(bytes(shortened), expected_chip="AC707N", expected_members=NAMES)
            self.assertEqual(parsed["postImage"]["size"], 0x59FF)
            with self.assertRaisesRegex(ValueError, "post-image size"):
                self.ufw.validate_stage0_ufw(bytes(shortened))

    def test_raw_integrity_tail_suffix_padding_and_trailing_mutations_fail_closed(self):
        mutations = {}
        for name, offset in (("header-crc", 0), ("table-crc", 0x40), ("member-crc", 0xFB400), ("gap-padding", 0x360), ("protected-allocation-padding", 0xFB440 + 0x974), ("tail-key-crc", 0x1021E0 + 0x20), ("post-magic", 0x102220), ("post-size", 0x102224)):
            changed = bytearray(self.stage0); changed[offset] ^= 1; mutations[name] = bytes(changed)
        mutations["tail-signature-semantic"] = mutate_tail_semantically(self.stage0, 0x22)
        mutations["tail-marker-semantic"] = mutate_tail_semantically(self.stage0, 0x30)
        mutations["truncated-header"] = self.stage0[:0x3F]
        mutations["truncated-table"] = self.stage0[:0x35F]
        mutations["truncated-core"] = self.stage0[:0x10221F]
        mutations["truncated-suffix"] = self.stage0[:-1]
        mutations["core-only-stage0"] = self.stage0[:0x102220]
        mutations["trailing"] = self.stage0 + b"\0"
        for name, data in mutations.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.ufw.validate_stage0_ufw(data)

    def test_recomputed_crc_semantic_header_and_entry_mutations_reach_policy_checks(self):
        mutations = {
            "chip": mutate_header(self.stage0, lambda h: h.__setitem__(slice(0x10, 0x20), b"AC697N".ljust(16, b"\0"))),
            "format": mutate_header(self.stage0, lambda h: h.__setitem__(slice(0x0A, 0x0C), (3).to_bytes(2, "little"))),
            "count": mutate_header(self.stage0, lambda h: h.__setitem__(slice(8, 10), (9).to_bytes(2, "little"))),
            "reserved": mutate_header(self.stage0, lambda h: h.__setitem__(slice(0x0C, 0x10), (0).to_bytes(4, "little"))),
            "header-reserve": mutate_header(self.stage0, lambda h: h.__setitem__(0x20, 1)),
            "index": mutate_entry(self.stage0, 2, lambda e: e.__setitem__(slice(2, 4), (99).to_bytes(2, "little"))),
            "logical-gt-allocated": mutate_entry(self.stage0, 3, lambda e: e.__setitem__(slice(0x0C, 0x10), (0x981).to_bytes(4, "little"))),
            "overlap": mutate_entry(self.stage0, 2, lambda e: e.__setitem__(slice(8, 12), (0x400).to_bytes(4, "little"))),
            "path-name": mutate_entry(self.stage0, 2, lambda e: e.__setitem__(slice(0x40, 0x50), b"../bad.bin".ljust(16, b"\0"))),
            "duplicate-name": mutate_entry(self.stage0, 2, lambda e: e.__setitem__(slice(0x40, 0x50), name_field("flash.bin"))),
            "crypt-bounds": mutate_entry(self.stage0, 2, lambda e: e.__setitem__(slice(0x18, 0x1C), (0x41).to_bytes(4, "little"))),
            "entry-reserved": mutate_entry(self.stage0, 2, lambda e: e.__setitem__(0x1C, 1)),
            "wrong-type": mutate_entry(self.stage0, 2, lambda e: e.__setitem__(0, 0x38)),
        }
        for name, data in mutations.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.ufw.validate_stage0_ufw(data)

    def test_layout_helper_rejects_duplicate_overlap_path_bounds_and_crypt_ranges(self):
        valid = [
            {"name": "a.bin", "offset": 0x100, "dataSize": 4, "allocatedSize": 0x20, "cryptOffset": 0, "cryptSize": 0},
            {"name": "b.bin", "offset": 0x120, "dataSize": 3, "allocatedSize": 0x20, "cryptOffset": 0, "cryptSize": 0x20},
            {"name": "tail.bin", "offset": 0x140, "dataSize": 0x40, "allocatedSize": 0x40, "cryptOffset": 0, "cryptSize": 0},
        ]
        self.ufw.validate_entry_layout(valid, image_size=0x180, table_end=0x100)
        for field, value in (("duplicate", None), ("overlap", None), ("path", None), ("bounds", None), ("crypt", None)):
            changed = [dict(item) for item in valid]
            if field == "duplicate": changed[1]["name"] = "a.bin"
            if field == "overlap": changed[1]["offset"] = 0x110
            if field == "path": changed[0]["name"] = "../a.bin"
            if field == "bounds": changed[-1]["allocatedSize"] = 0x60
            if field == "crypt": changed[1]["cryptSize"] = 0x40
            with self.subTest(field=field):
                with self.assertRaises(ValueError): self.ufw.validate_entry_layout(changed, image_size=0x180, table_end=0x100)


if __name__ == "__main__":
    unittest.main()
