#!/usr/bin/env python3
"""JieLi new-firmware and observed FWSC membership proof tests."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
import unittest
import struct
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "firmware/tools/jlfw.py"
REFERENCE_ROOT = Path(os.environ.get("E87_MODEL1552_REFERENCE_ROOT", "/home/jethac/.local/share/e87-dev/references/model1552-e87-11.1.0.2"))
UFW = REFERENCE_ROOT / "container/payload.ufw"
GOLDEN_APP = REFERENCE_ROOT / "canonical-jl-unpack/files/app.bin"
GOLDEN_APP_SHA256 = "A38B77E27B1DC73CAE0FBD8A7C4E3A04C64FF393FB4F27BC92A7578336BE0147"
FLASH_OFFSET = 0x400
FLASH_SIZE = 0xFB000
APP_ENTRY = 0x0C000100
GUARDS = bytes(range(0xA0, 0xB4))
LAB_ARTIFACT_ROOT = Path(os.environ.get("E87_GENERATED_LAB_ARTIFACT_ROOT", r"B:\esp32\artifacts\panel-package-8ecf5c4"))
LAB_FLASH_SHA256 = "F3AC889391F57C693FCD7BA98CE4294CD20D61310C3479431BA21409E48D39D3"
LAB_APP_SHA256 = "D4EEEB268D5E36E1B874F106E5F5F64628E5531D44DDF6B37B5B67D785AC73D9"


def fwsc_wrap(logical_ufw: bytes, guards: bytes = GUARDS) -> bytes:
    if len(logical_ufw) < 940 or len(guards) != 20:
        raise AssertionError("bad FWSC fixture")
    return b"".join(logical_ufw[index * 47:(index + 1) * 47] + guards[index:index + 1] for index in range(20)) + logical_ufw[940:]


def crc16(data: bytes) -> int:
    state = 0
    for byte in data:
        state ^= byte << 8
        for _ in range(8):
            state = ((state << 1) ^ (0x1021 if state & 0x8000 else 0)) & 0xFFFF
    return state


def cipher(data: bytes, key: int) -> bytes:
    output = bytearray(len(data)); state = key
    for index, byte in enumerate(data):
        output[index] = byte ^ (state & 0xFF)
        state = ((state << 1) ^ (0x1021 if state & 0x8000 else 0)) & 0xFFFF
    return bytes(output)


def sfc_transform(flash: bytes) -> bytes:
    output = bytearray(flash)
    for block in range(0x2000, len(flash), 32):
        output[block:block + 32] = cipher(flash[block:block + 32], (0x9847 ^ ((block - 0x2000) >> 2)) & 0xFFFF)
    return bytes(output)


def jlfs_header(name: str, offset: int, size: int, flags: int, index: int, data: bytes, *, reserved: int = 0) -> bytes:
    tail = struct.pack("<HIIBBH16s", crc16(data), offset, size, flags, reserved, index, name.encode("ascii").ljust(16, b"\0"))
    return crc16(tail).to_bytes(2, "little") + tail


def generated_lab_fixture(reference: bytes, app: bytes) -> bytes:
    entry = jlfs_header("app.bin", 0x40, len(app), 0x82, 1, app)
    area_body = entry + app
    head = jlfs_header("app_area_head", APP_ENTRY, 32 + len(area_body), 0x83, 0, area_body)
    decoded = bytearray(reference[:0x2000]) + head + area_body
    return sfc_transform(bytes(decoded))


def duplicate_app_fixture(flash: bytes) -> bytes:
    decoded = bytearray(sfc_transform(flash))
    duplicate = bytearray(decoded[0x2040:0x2060])
    duplicate[16:32] = b"app.bin\0".ljust(16, b"\0")
    duplicate[0:2] = crc16(duplicate[2:]).to_bytes(2, "little")
    decoded[0x2040:0x2060] = duplicate
    app_head = bytearray(decoded[0x2000:0x2020])
    app_head[2:4] = crc16(decoded[0x2020:0xF5200]).to_bytes(2, "little")
    app_head[0:2] = crc16(app_head[2:]).to_bytes(2, "little")
    decoded[0x2000:0x2020] = app_head
    return sfc_transform(bytes(decoded))


def load_tool():
    spec = importlib.util.spec_from_file_location("e87_stage0_jlfw", TOOL)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load JLFw tool")
    module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module)
    return module


class JlFwTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.jlfw = load_tool(); cls.payload = UFW.read_bytes()
        cls.flash = cls.payload[FLASH_OFFSET:FLASH_OFFSET + FLASH_SIZE]
        cls.app = GOLDEN_APP.read_bytes(); cls.fwsc = fwsc_wrap(cls.payload)
        cls.lab_flash = (LAB_ARTIFACT_ROOT / "jl_isd.bin").read_bytes()
        cls.lab_app = (LAB_ARTIFACT_ROOT / "app.bin").read_bytes()

    def test_crc_and_encryption_literal_vectors(self):
        self.assertEqual(self.jlfw.crc16_xmodem(b"123456789"), 0x31C3)
        self.assertEqual(self.jlfw.jl_enc(bytes(range(8)), 0x9847).hex(), "47ae5cbf5db762cf")
        encrypted = self.jlfw.jl_enc(b"stage0-jlfw", 0x9847)
        self.assertEqual(self.jlfw.jl_enc(encrypted, 0x9847), b"stage0-jlfw")

    def test_reference_raw_flash_structurally_proves_exact_unique_app(self):
        self.assertEqual(self.jlfw.classify_container(self.flash), "RAW_JL_NEW_FW")
        result = self.jlfw.extract_embedded_app(self.flash, expected_entry_address=APP_ENTRY)
        self.assertEqual((len(self.flash), result.offset, result.size), (FLASH_SIZE, 0x2100, 0xF3100))
        self.assertEqual((result.entry_address, result.chip_key), (APP_ENTRY, 0x9847))
        self.assertEqual((result.data, result.sha256), (self.app, GOLDEN_APP_SHA256))
        self.assertEqual(hashlib.sha256(result.data).hexdigest().upper(), result.sha256)
        self.assertEqual(result.app_entry_count, 1)
        with self.assertRaisesRegex(ValueError, "unique"):
            self.jlfw.extract_embedded_app(duplicate_app_fixture(self.flash), expected_entry_address=APP_ENTRY)

    def test_positive_fwsc_fixture_recovers_exact_ufw_flash_guards_and_app(self):
        envelope = self.jlfw.extract_flash_from_jl_isd_fw(self.fwsc)
        self.assertEqual(envelope.kind, "FWSC_20X48")
        self.assertEqual(envelope.logical_ufw, self.payload)
        self.assertEqual(envelope.flash, self.flash)
        self.assertEqual(envelope.opaque_guards, GUARDS)
        self.assertEqual(envelope.flash_physical_offset, 0x414)
        proof = self.jlfw.prove_embedded_app(
            self.fwsc, self.app, container_kind="jl_isd.fw", expected_entry_address=APP_ENTRY
        )
        self.assertEqual(proof["appSha256"], GOLDEN_APP_SHA256)
        self.assertEqual(proof["containerKind"], "FWSC_20X48")
        self.assertEqual(proof["flashSha256"], hashlib.sha256(self.flash).hexdigest().upper())

    def test_direct_ufw_is_an_explicit_unique_envelope_form(self):
        envelope = self.jlfw.extract_flash_from_jl_isd_fw(self.payload)
        self.assertEqual(envelope.kind, "DIRECT_UFW")
        self.assertEqual(envelope.logical_ufw, self.payload)
        self.assertEqual(envelope.flash, self.flash)
        self.assertEqual(envelope.opaque_guards, b"")

    def test_zero_soles_pairs_and_three_way_interpretations_fail_closed(self):
        raw = self.jlfw.extract_embedded_app(self.flash, expected_entry_address=APP_ENTRY)
        direct = self.jlfw.extract_flash_from_jl_isd_fw(self.payload)
        fwsc = self.jlfw.extract_flash_from_jl_isd_fw(self.fwsc)
        for name, arguments, expected in (
            ("raw", (raw, None, None), raw),
            ("direct", (None, direct, None), direct),
            ("fwsc", (None, None, fwsc), fwsc),
        ):
            with self.subTest(name=name):
                self.assertIs(self.jlfw.select_unique_fw_interpretation(*arguments), expected)
        with self.assertRaisesRegex(ValueError, "zero"):
            self.jlfw.select_unique_fw_interpretation(None, None, None)
        for name, arguments in (
            ("raw-direct", (raw, direct, None)),
            ("raw-fwsc", (raw, None, fwsc)),
            ("direct-fwsc", (None, direct, fwsc)),
            ("raw-direct-fwsc", (raw, direct, fwsc)),
        ):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "ambiguous"):
                    self.jlfw.select_unique_fw_interpretation(*arguments)

    def test_candidate_collector_runs_raw_direct_and_fwsc_probes_before_pair_ambiguity(self):
        probe_container = bytes((index * 17 + 3) & 0xFF for index in range(960))
        expected_fwsc_logical = b"".join(
            probe_container[index * 48:index * 48 + 47] for index in range(20)
        ) + probe_container[960:]
        raw_proof = self.jlfw.extract_embedded_app(self.flash, expected_entry_address=APP_ENTRY)
        direct_flash = b"direct-probe-flash"
        parsed_direct = {
            "entries": [
                {"name": "flash.bin", "typeCode": 0, "offset": 0x123, "data": direct_flash}
            ]
        }
        parse_ufw = mock.Mock(side_effect=(parsed_direct, ValueError("not FWSC")))
        ufw_module = mock.Mock(parse_ufw=parse_ufw)
        with mock.patch.object(
            self.jlfw,
            "extract_embedded_app",
            return_value=raw_proof,
        ) as raw_probe, mock.patch.object(
            self.jlfw,
            "_load_ufw_module",
            return_value=ufw_module,
        ):
            candidates = self.jlfw.collect_container_candidates(probe_container)
        self.assertEqual(raw_probe.call_count, 1)
        self.assertEqual(raw_probe.call_args.args[0], probe_container)
        self.assertEqual(parse_ufw.call_count, 2)
        self.assertEqual(parse_ufw.call_args_list[0].args[0], probe_container)
        self.assertEqual(parse_ufw.call_args_list[1].args[0], expected_fwsc_logical)
        raw, direct, fwsc = candidates
        self.assertEqual((raw.kind, raw.flash), ("RAW_JL_NEW_FW", probe_container))
        self.assertEqual((direct.kind, direct.flash), ("DIRECT_UFW", direct_flash))
        self.assertIsNone(fwsc)
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.jlfw.select_unique_fw_interpretation(*candidates)

    def test_classifier_collects_all_three_candidates_before_selecting_one(self):
        raw = self.jlfw.extract_embedded_app(self.flash, expected_entry_address=APP_ENTRY)
        direct = self.jlfw.extract_flash_from_jl_isd_fw(self.payload)
        fwsc = self.jlfw.extract_flash_from_jl_isd_fw(self.fwsc)
        for name, candidates, expected_kind in (
            ("raw", (raw, None, None), "RAW_JL_NEW_FW"),
            ("direct", (None, direct, None), "DIRECT_UFW"),
            ("fwsc", (None, None, fwsc), "FWSC_20X48"),
        ):
            with self.subTest(name=name):
                with mock.patch.object(
                    self.jlfw,
                    "collect_container_candidates",
                    create=True,
                    return_value=candidates,
                ) as collect, mock.patch.object(
                    self.jlfw,
                    "select_unique_fw_interpretation",
                    wraps=self.jlfw.select_unique_fw_interpretation,
                ) as select:
                    self.assertEqual(self.jlfw.classify_container(self.flash), expected_kind)
                    collect.assert_called_once_with(self.flash)
                    select.assert_called_once_with(*candidates)

    def test_package_pair_requires_exact_flash_equality_and_both_app_proofs(self):
        receipt = self.jlfw.prove_package_pair(self.flash, self.fwsc, self.app, expected_entry_address=APP_ENTRY)
        self.assertEqual(receipt["flashEqual"], True)
        self.assertEqual(receipt["appSha256"], GOLDEN_APP_SHA256)
        selected = self.jlfw.extract_flash_from_jl_isd_fw(self.fwsc)
        with mock.patch.object(
            self.jlfw,
            "extract_flash_from_jl_isd_fw",
            return_value=selected,
        ) as select_fw_candidate:
            selected_receipt = self.jlfw.prove_package_pair(
                selected.flash,
                self.fwsc,
                self.app,
                expected_entry_address=APP_ENTRY,
            )
        self.assertEqual(select_fw_candidate.call_count, 1)
        selected_argument = select_fw_candidate.call_args.args[0]
        self.assertEqual(hashlib.sha256(selected_argument).digest(), hashlib.sha256(self.fwsc).digest())
        self.assertEqual(selected_receipt["fwEnvelopeKind"], selected.kind)
        self.assertEqual(selected_receipt["flashEqual"], True)
        changed = bytearray(self.flash); changed[0x2100 + 7] ^= 1
        with self.assertRaises(ValueError):
            self.jlfw.prove_package_pair(bytes(changed), self.fwsc, self.app, expected_entry_address=APP_ENTRY)

    def test_public_prove_embedded_app_accepts_sole_structural_raw_new_fw(self):
        proof = self.jlfw.prove_embedded_app(
            self.flash,
            self.app,
            container_kind="jl_isd.fw",
            expected_entry_address=APP_ENTRY,
        )
        self.assertEqual(proof["containerKind"], "RAW_JL_NEW_FW")
        self.assertEqual(proof["appSha256"], GOLDEN_APP_SHA256)
        self.assertEqual(proof["flashSha256"], hashlib.sha256(self.flash).hexdigest().upper())

    def test_public_prove_package_pair_accepts_sole_structural_raw_new_fw(self):
        receipt = self.jlfw.prove_package_pair(
            self.flash,
            self.flash,
            self.app,
            expected_entry_address=APP_ENTRY,
        )
        self.assertEqual(receipt["fwEnvelopeKind"], "RAW_JL_NEW_FW")
        self.assertEqual(receipt["flashEqual"], True)
        self.assertEqual(receipt["appSha256"], GOLDEN_APP_SHA256)

    def test_public_fw_proofs_reject_ambiguous_raw_and_direct_candidates(self):
        ambiguous_fw = b"synthetic-ambiguous-fw"
        raw = self.jlfw.FwEnvelope("RAW_JL_NEW_FW", b"", self.flash, b"", 0)
        direct = self.jlfw.extract_flash_from_jl_isd_fw(self.payload)
        for name, prove in (
            (
                "embedded-app",
                lambda: self.jlfw.prove_embedded_app(
                    ambiguous_fw,
                    self.app,
                    container_kind="jl_isd.fw",
                    expected_entry_address=APP_ENTRY,
                ),
            ),
            (
                "package-pair",
                lambda: self.jlfw.prove_package_pair(
                    self.flash,
                    ambiguous_fw,
                    self.app,
                    expected_entry_address=APP_ENTRY,
                ),
            ),
        ):
            with self.subTest(name=name), mock.patch.object(
                self.jlfw,
                "collect_container_candidates",
                create=True,
                return_value=(raw, direct, None),
            ):
                with self.assertRaisesRegex(ValueError, "ambiguous"):
                    prove()

    def test_generated_lab_profile_proves_real_compact_filesystem_and_separates_reference(self):
        proof = self.jlfw.prove_embedded_app(
            self.lab_flash, self.lab_app, container_kind="jl_isd.bin", proof_profile="generated-lab"
        )
        self.assertEqual((len(self.lab_flash), proof["appOffset"], proof["appSize"]), (0x1B000, 0x2100, 82272))
        self.assertEqual((proof["flashSha256"], proof["appSha256"]), (LAB_FLASH_SHA256, LAB_APP_SHA256))
        extracted = self.jlfw.extract_embedded_app(self.lab_flash, proof_profile="generated-lab")
        self.assertEqual((extracted.chip_key, extracted.entry_address), (0xFFFF, APP_ENTRY))
        with self.assertRaisesRegex(ValueError, "exactly 0xFB000"):
            self.jlfw.prove_embedded_app(self.lab_flash, self.lab_app, container_kind="jl_isd.bin")
        with self.assertRaises(ValueError):
            self.jlfw.prove_embedded_app(
                self.flash, self.app, container_kind="jl_isd.bin", proof_profile="generated-lab"
            )

    def test_generated_lab_truncation_bounds_wrong_app_and_malformed_header_fail_closed(self):
        cases = {
            "truncated": self.lab_flash[:0x162FF],
            "malformed-flash-header": bytes([self.lab_flash[0] ^ 1]) + self.lab_flash[1:],
        }
        decoded = bytearray(self.jlfw._decode_sfc(self.lab_flash, 0xFFFF))
        app_entry = self.jlfw._parse_header(decoded[0x2020:0x2040], location=0x2020)
        bad_entry = jlfs_header("app.bin", 0x14260, int(app_entry["size"]), 0x82, 0, self.lab_app, reserved=0xFF)
        decoded[0x2020:0x2040] = bad_entry
        area_end = 0x2000 + self.jlfw._parse_header(decoded[0x2000:0x2020], location=0x2000)["size"]
        area = bytes(decoded[0x2020:area_end])
        decoded[0x2000:0x2020] = jlfs_header("app_area_head", APP_ENTRY, area_end - 0x2000, 0x83, 0, area, reserved=2)
        cases["app-bounds"] = self.jlfw._decode_sfc(bytes(decoded), 0xFFFF)
        for name, changed in cases.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.jlfw.prove_embedded_app(
                    changed, self.lab_app, container_kind="jl_isd.bin", proof_profile="generated-lab"
                )
        with self.assertRaisesRegex(ValueError, "does not equal"):
            self.jlfw.prove_embedded_app(
                self.lab_flash, self.lab_app[:-1] + bytes([self.lab_app[-1] ^ 1]), container_kind="jl_isd.bin", proof_profile="generated-lab"
            )

    def test_new_firmware_crc_bounds_identity_and_membership_mutations_fail_closed(self):
        mutations = {}
        for name, offset in (("flash-header", 0), ("top-jlfs", 0x20), ("app-area", 0x2000), ("app-entry", 0x2020), ("app-data", 0x2100 + 31)):
            changed = bytearray(self.flash); changed[offset] ^= 1; mutations[name] = bytes(changed)
        mutations["truncated-before-app"] = self.flash[:0x2100]
        mutations["truncated-model-image"] = self.flash[:-1]
        mutations["trailing-model-image"] = self.flash + b"\0"
        for name, changed in mutations.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.jlfw.extract_embedded_app(changed, expected_entry_address=APP_ENTRY)
        with self.assertRaises(ValueError):
            self.jlfw.extract_embedded_app(self.flash, expected_entry_address=APP_ENTRY + 4)
        with self.assertRaises(ValueError):
            self.jlfw.prove_embedded_app(self.flash, self.app[:-1] + bytes([self.app[-1] ^ 1]), container_kind="jl_isd.bin", expected_entry_address=APP_ENTRY)

    def test_fwsc_structure_retained_bytes_and_ufw_trailing_fail_but_guards_are_opaque(self):
        guard_changed = bytearray(self.fwsc); guard_changed[47] ^= 1
        accepted = self.jlfw.extract_flash_from_jl_isd_fw(bytes(guard_changed))
        self.assertEqual(accepted.flash, self.flash)
        self.assertNotEqual(accepted.opaque_guards, GUARDS)
        mutations = {
            "short": self.fwsc[:959],
            "delete-prefix-byte": self.fwsc[:48] + self.fwsc[49:],
            "insert-prefix-byte": self.fwsc[:48] + b"\0" + self.fwsc[48:],
            "retained-header": bytes([self.fwsc[0] ^ 1]) + self.fwsc[1:],
            "retained-flash": self.fwsc[:0x414] + bytes([self.fwsc[0x414] ^ 1]) + self.fwsc[0x415:],
            "extra-after-suffix": self.fwsc + b"\0",
        }
        for name, changed in mutations.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError): self.jlfw.extract_flash_from_jl_isd_fw(changed)
        fake = b"untrusted-prefix" + self.flash + b"untrusted-suffix"
        with self.assertRaises(ValueError):
            self.jlfw.prove_embedded_app(fake, self.app, container_kind="jl_isd.fw", expected_entry_address=APP_ENTRY)


if __name__ == "__main__":
    unittest.main()
