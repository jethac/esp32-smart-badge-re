#!/usr/bin/env python3
"""Literal and fail-closed Stage 0-H Qix envelope tests."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "firmware/tools/qix.py"
REFERENCE_ROOT = Path(os.environ.get("E87_MODEL1552_REFERENCE_ROOT", "/home/jethac/.local/share/e87-dev/references/model1552-e87-11.1.0.2"))
PAYLOAD_PATH = REFERENCE_ROOT / "container/payload.ufw"
GOLDEN_PREFIX = bytes.fromhex("bcaf01" "31312e312e302e320000" "287c1000" "0000000000000000" "01b5")
GOLDEN_SHA256 = "14484147053903F879D0C24ACBAB6A564F5CC8F039CACCBB30821012DF645D32"


def load_tool():
    spec = importlib.util.spec_from_file_location("e87_stage0_qix", TOOL)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load qix tool")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class QixTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.qix = load_tool()
        cls.payload = PAYLOAD_PATH.read_bytes()
        cls.golden = GOLDEN_PREFIX + cls.payload

    def test_crc_and_reference_reconstruction_are_literal(self):
        self.assertEqual(self.qix.crc16_ccitt_false(b"123456789"), 0x29B1)
        self.assertEqual(self.qix.crc16_ccitt_false(self.payload), 0xB501)
        wrapped = self.qix.wrap_qix(self.payload, "11.1.0.2")
        self.assertEqual(wrapped, self.golden)
        self.assertEqual(len(wrapped), 1_080_387)
        self.assertEqual(hashlib.sha256(wrapped).hexdigest().upper(), GOLDEN_SHA256)

    def test_parse_round_trip_and_stage0_version_only_wrap_valid_ufw(self):
        parsed = self.qix.parse_qix(self.golden, expected_version="11.1.0.2")
        self.assertEqual(parsed, {"payload": self.payload, "payloadCrc16": 0xB501, "payloadSize": 1_080_360, "type": 1, "version": "11.1.0.2"})
        self.assertEqual(self.qix.unwrap_qix(self.golden), ("11.1.0.2", self.payload))
        stage0 = self.qix.wrap_qix(self.payload, "11.1.0.3")
        self.assertEqual(self.qix.unwrap_qix(stage0), ("11.1.0.3", self.payload))
        with self.assertRaises(ValueError):
            self.qix.wrap_qix(b"not-a-ufw", "11.1.0.3")

    def test_version_accepts_one_to_ten_ascii_bytes_but_not_noncanonical_input(self):
        for version in ("1", "11.1.0.3", "1234567890"):
            with self.subTest(version=version):
                parsed = self.qix.parse_qix(self.qix.wrap_qix(self.payload, version))
                self.assertEqual(parsed["version"], version)
        for version in ("", "12345678901", "1\x002", "café"):
            with self.subTest(version=repr(version)):
                with self.assertRaises((TypeError, ValueError)):
                    self.qix.wrap_qix(self.payload, version)

    def test_outer_contract_mutations_fail_before_payload_is_accepted(self):
        mutations = {}
        for offset in range(3):
            changed = bytearray(self.golden); changed[offset] ^= 1
            mutations[f"magic-{offset}"] = bytes(changed)
        changed = bytearray(self.golden); changed[3] = 0
        mutations["empty-version"] = bytes(changed)
        changed = bytearray(self.golden); changed[5] = 0; changed[6] = ord("X")
        mutations["nonzero-after-version-nul"] = bytes(changed)
        for offset in range(17, 25):
            changed = bytearray(self.golden); changed[offset] = 1
            mutations[f"reserved-{offset}"] = bytes(changed)
        for declared in (0, len(self.payload) - 1, len(self.payload) + 1, 0xFFFFFFFF):
            changed = bytearray(self.golden); changed[13:17] = declared.to_bytes(4, "little")
            mutations[f"length-{declared}"] = bytes(changed)
        for offset in (25, 26, 27 + 17):
            changed = bytearray(self.golden); changed[offset] ^= 1
            mutations[f"crc-or-payload-{offset}"] = bytes(changed)
        mutations["truncated-header"] = self.golden[:26]
        mutations["truncated-payload"] = self.golden[:-1]
        mutations["trailing"] = self.golden + b"\x00"
        for name, mutated in mutations.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.qix.parse_qix(mutated)
        with self.assertRaises(ValueError):
            self.qix.parse_qix(self.golden, expected_version="11.1.0.3")

    def test_cli_success_and_failure_paths_are_atomic_and_quiet(self):
        with tempfile.TemporaryDirectory(prefix="e87-qix-test-") as temp:
            root = Path(temp); payload = root / "input.ufw"; wrapped = root / "output.qix"; recovered = root / "recovered.ufw"
            payload.write_bytes(self.payload)
            wrap_argv = [sys.executable, str(TOOL), "wrap", "--input", str(payload), "--output", str(wrapped), "--version", "11.1.0.3"]
            wrap = subprocess.run(wrap_argv, cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertEqual((wrap.returncode, wrap.stdout, wrap.stderr), (0, "", ""))
            unwrap = subprocess.run([sys.executable, str(TOOL), "unwrap", "--input", str(wrapped), "--output", str(recovered), "--expected-version", "11.1.0.3"], cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertEqual((unwrap.returncode, unwrap.stdout, unwrap.stderr), (0, "", ""))
            self.assertEqual(recovered.read_bytes(), self.payload)
            original = wrapped.read_bytes()
            again = subprocess.run(wrap_argv, cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertNotEqual(again.returncode, 0); self.assertEqual(wrapped.read_bytes(), original)
            bad_input = root / "bad.ufw"; bad_input.write_bytes(b"bad"); absent = root / "absent.qix"
            bad = subprocess.run([sys.executable, str(TOOL), "wrap", "--input", str(bad_input), "--output", str(absent), "--version", "11.1.0.3"], cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertNotEqual(bad.returncode, 0); self.assertFalse(absent.exists())
            alias = root / "alias.qix"; alias.symlink_to(wrapped)
            aliased = subprocess.run([sys.executable, str(TOOL), "wrap", "--input", str(payload), "--output", str(alias), "--version", "11.1.0.3"], cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertNotEqual(aliased.returncode, 0); self.assertEqual(wrapped.read_bytes(), original)

    def test_cli_rejects_symlinked_input_ancestor_without_creating_output(self):
        with tempfile.TemporaryDirectory(prefix="e87-qix-input-ancestor-test-") as temp:
            root = Path(temp)
            real = root / "real"
            nested = real / "nested"
            nested.mkdir(parents=True)
            alias = root / "alias"
            alias.symlink_to(real, target_is_directory=True)
            real_input = nested / "input.ufw"
            real_input.write_bytes(self.payload)
            aliased_input = alias / "nested" / "input.ufw"
            output = root / "output.qix"
            original = real_input.read_bytes()
            self.assertTrue(alias.is_symlink())
            self.assertFalse(aliased_input.parent.is_symlink())
            self.assertFalse(aliased_input.is_symlink())
            wrapped = subprocess.run(
                [sys.executable, str(TOOL), "wrap", "--input", str(aliased_input), "--output", str(output), "--version", "11.1.0.3"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(real_input.read_bytes(), original)
            self.assertNotEqual(wrapped.returncode, 0)
            self.assertFalse(output.exists())

    def test_cli_rejects_symlinked_output_ancestor_without_creating_output(self):
        with tempfile.TemporaryDirectory(prefix="e87-qix-output-ancestor-test-") as temp:
            root = Path(temp)
            real = root / "real"
            nested = real / "nested"
            nested.mkdir(parents=True)
            alias = root / "alias"
            alias.symlink_to(real, target_is_directory=True)
            payload = root / "input.ufw"
            payload.write_bytes(self.payload)
            real_output = nested / "output.qix"
            aliased_output = alias / "nested" / "output.qix"
            original = payload.read_bytes()
            self.assertTrue(alias.is_symlink())
            self.assertFalse(aliased_output.parent.is_symlink())
            self.assertFalse(aliased_output.is_symlink())
            wrapped = subprocess.run(
                [sys.executable, str(TOOL), "wrap", "--input", str(payload), "--output", str(aliased_output), "--version", "11.1.0.3"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(payload.read_bytes(), original)
            self.assertNotEqual(wrapped.returncode, 0)
            self.assertFalse(real_output.exists())
            self.assertFalse(aliased_output.exists())


if __name__ == "__main__":
    unittest.main()
