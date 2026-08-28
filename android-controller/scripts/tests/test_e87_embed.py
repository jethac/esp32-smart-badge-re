#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "prepare-e87-firmware.py"
BUILD_ID = "00112233445566778899AABBCCDDEEFF"
QIX_VERSION = "11.1.0.4"
QIX_NAME = "E87-11.1.0.4-00112233.qix"
ROLE_NAMES = (
    ("appBin", "app.bin"),
    ("jlIsdFw", "jl_isd.fw"),
    ("updateUfw", "update.ufw"),
    ("qix", QIX_NAME),
    ("manifest", "manifest.json"),
    ("sha256Sums", "SHA256SUMS"),
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, allow_nan=False,
                       indent=2, sort_keys=True) + "\n").encode("ascii")


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ (0x1021 if crc & 0x8000 else 0)) & 0xFFFF
    return crc


def qix(payload: bytes, *, version: str = QIX_VERSION) -> bytes:
    version_field = version.encode("ascii").ljust(10, b"\0")
    return struct.pack("<2sB10sI8sH", b"\xBC\xAF", 1, version_field,
                       len(payload), bytes(8), crc16(payload)) + payload


class ReleaseFixture:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir()
        payloads = {
            "app.bin": b"APP\0qualified-build\x01",
            "jl_isd.fw": b"JLFW\0qualified-container\x02",
            "update.ufw": b"UFW4\0qualified-update\x03",
            "manifest.json": canonical({
                "schema": "e87-firmware-manifest-v1",
                "note": "fixture bytes are not committed firmware",
            }),
        }
        payloads[QIX_NAME] = qix(payloads["update.ufw"])
        sums_names = sorted(payloads)
        payloads["SHA256SUMS"] = "".join(
            f"{sha(payloads[name])} *{name}\n" for name in sums_names
        ).encode("ascii")
        for name, data in payloads.items():
            (root / name).write_bytes(data)
        self.receipt = {
            "buildId": BUILD_ID,
            "chip": "AC707N",
            "files": [
                {
                    "filename": name,
                    "length": len(payloads[name]),
                    "role": role,
                    "sha256": sha(payloads[name]),
                }
                for role, name in ROLE_NAMES
            ],
            "labEligible": True,
            "layout": "SINGLE_BANK",
            "profile": "E87-JD9855-R1",
            "qixVersion": QIX_VERSION,
            "releaseEligible": False,
            "releaseRoot": f"E87-JD9855-R1/0.1.0/{BUILD_ID}",
            "schemaId": "e87-android-embed-v1",
            "schemaVersion": 1,
            "semver": "0.1.0",
        }
        self.write_receipt()

    def write_receipt(self) -> None:
        (self.root / "e87-android-embed.json").write_bytes(canonical(self.receipt))

    def refresh_hashes(self) -> None:
        ordinary = [record["filename"] for record in self.receipt["files"]
                    if record["role"] != "sha256Sums"]
        sums = "".join(
            f"{sha((self.root / name).read_bytes())} *{name}\n"
            for name in sorted(ordinary)
        ).encode("ascii")
        (self.root / "SHA256SUMS").write_bytes(sums)
        for record in self.receipt["files"]:
            data = (self.root / record["filename"]).read_bytes()
            record["length"] = len(data)
            record["sha256"] = sha(data)
        self.write_receipt()

    def set_qix_version(self, version: str) -> None:
        record = next(record for record in self.receipt["files"]
                      if record["role"] == "qix")
        old_path = self.root / record["filename"]
        new_name = f"E87-{version}-{BUILD_ID[:8]}.qix"
        payload = (self.root / "update.ufw").read_bytes()
        old_path.unlink()
        (self.root / new_name).write_bytes(qix(payload, version=version))
        record["filename"] = new_name
        self.receipt["qixVersion"] = version
        self.refresh_hashes()


class EmbedToolTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.release = ReleaseFixture(self.base / "release")
        self.output = self.base / "generated"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_prepare(self, release: Path | str | None = None,
                    output: Path | None = None) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, os.fspath(SCRIPT),
                   "--release", os.fspath(self.release.root if release is None else release),
                   "--output", os.fspath(self.output if output is None else output)]
        return subprocess.run(command, cwd=self.base, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

    def assert_rejected(self, message: str | None = None) -> None:
        result = self.run_prepare()
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertFalse(self.output.exists(), "invalid input published an output tree")
        if message is not None:
            self.assertIn(message, result.stderr)

    def test_prepare_copies_exact_bytes_and_emits_stable_read_only_provenance(self) -> None:
        stale = self.output / "assets" / "e87" / "stale.bin"
        stale.parent.mkdir(parents=True)
        stale.write_bytes(b"stale")

        first = self.run_prepare()

        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        self.assertFalse(stale.exists())
        index = self.output / "assets" / "e87" / "default-release.json"
        self.assertEqual((self.release.root / "e87-android-embed.json").read_bytes(),
                         index.read_bytes())
        release_root = self.output / "assets" / "e87" / self.release.receipt["releaseRoot"]
        self.assertEqual({name for _, name in ROLE_NAMES},
                         {entry.name for entry in release_root.iterdir()})
        for _, name in ROLE_NAMES:
            generated = release_root / name
            self.assertEqual((self.release.root / name).read_bytes(), generated.read_bytes())
            self.assertEqual(0, stat.S_IMODE(generated.stat().st_mode) & 0o222)
        self.assertEqual(0, stat.S_IMODE(index.stat().st_mode) & 0o222)
        provenance = (self.output / "e87-embed-provenance.json").read_bytes()
        parsed = json.loads(provenance)
        self.assertEqual("e87-android-embed-provenance-v1", parsed["schemaId"])
        self.assertTrue(parsed["labEligible"])
        self.assertFalse(parsed["releaseEligible"])
        self.assertEqual(QIX_VERSION, parsed["qixVersion"])
        self.assertEqual(self.release.receipt["releaseRoot"], parsed["releaseRoot"])
        self.assertNotIn(os.fspath(self.release.root), provenance.decode("ascii"))

        second_release = self.base / "somewhere-else" / "release"
        second_release.parent.mkdir()
        second_release.mkdir()
        for source in self.release.root.iterdir():
            (second_release / source.name).write_bytes(source.read_bytes())
        second_output = self.base / "second-output"
        second = self.run_prepare(second_release, second_output)
        self.assertEqual(0, second.returncode, second.stdout + second.stderr)
        self.assertEqual(provenance,
                         (second_output / "e87-embed-provenance.json").read_bytes())

    def test_relative_or_nested_roots_and_symlinked_inputs_are_rejected(self) -> None:
        result = self.run_prepare("release")
        self.assertEqual(2, result.returncode)
        self.assertIn("absolute", result.stderr)
        nested = self.release.root / "generated"
        result = self.run_prepare(output=nested)
        self.assertEqual(2, result.returncode)
        self.assertFalse(nested.exists())
        link = self.base / "release-link"
        try:
            link.symlink_to(self.release.root, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        result = self.run_prepare(link)
        self.assertEqual(2, result.returncode)
        self.assertIn("symlink", result.stderr)

    def test_closed_directory_rejects_s0_manifest_alone_and_extra_entries(self) -> None:
        (self.release.root / "e87-android-embed.json").unlink()
        self.assert_rejected("allowlist")
        self.release.write_receipt()
        (self.release.root / "extra.bin").write_bytes(b"extra")
        self.assert_rejected("allowlist")

    def test_receipt_is_closed_canonical_and_rejects_duplicate_keys(self) -> None:
        self.release.receipt["unexpected"] = True
        self.release.write_receipt()
        self.assert_rejected("keys")
        del self.release.receipt["unexpected"]
        raw = canonical(self.release.receipt).decode("ascii")
        raw = raw.replace('  "chip": "AC707N",',
                          '  "chip": "AC707N",\n  "chip": "AC707N",')
        (self.release.root / "e87-android-embed.json").write_text(raw, encoding="ascii")
        self.assert_rejected("duplicate")
        self.release.write_receipt()
        (self.release.root / "e87-android-embed.json").write_text(
            json.dumps(self.release.receipt), encoding="ascii")
        self.assert_rejected("canonical")

    def test_identity_and_eligibility_are_explicit_and_exact(self) -> None:
        mutations = (
            ("chip", "AC697N"),
            ("profile", "E87-1542-STAGE0-H"),
            ("layout", "DUAL_BANK"),
            ("semver", "01.0.0"),
            ("buildId", BUILD_ID.lower()),
            ("qixVersion", "11.1.0.2"),
            ("labEligible", False),
            ("releaseRoot", "../escape"),
        )
        original = dict(self.release.receipt)
        for field, value in mutations:
            with self.subTest(field=field):
                self.release.receipt = dict(original)
                self.release.receipt[field] = value
                self.release.write_receipt()
                self.assert_rejected()

    def test_receipt_supplied_future_qix_version_is_header_and_filename_bound(self) -> None:
        self.release.set_qix_version("11.1.0.5")

        result = self.run_prepare()

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_consumed_sacrificial_qix_version_is_below_the_supported_floor(self) -> None:
        self.release.set_qix_version("11.1.0.3")

        self.assert_rejected("newer than sacrificial")

    def test_file_records_reject_role_order_duplicates_names_lengths_and_hashes(self) -> None:
        original = json.loads(json.dumps(self.release.receipt))
        mutations = []
        reversed_files = list(reversed(original["files"]))
        mutations.append(reversed_files)
        duplicate = json.loads(json.dumps(original["files"]))
        duplicate[1]["role"] = duplicate[0]["role"]
        mutations.append(duplicate)
        wrong_name = json.loads(json.dumps(original["files"]))
        wrong_name[0]["filename"] = "../app.bin"
        mutations.append(wrong_name)
        wrong_length = json.loads(json.dumps(original["files"]))
        wrong_length[0]["length"] += 1
        mutations.append(wrong_length)
        wrong_hash = json.loads(json.dumps(original["files"]))
        wrong_hash[0]["sha256"] = "0" * 64
        mutations.append(wrong_hash)
        unknown_key = json.loads(json.dumps(original["files"]))
        unknown_key[0]["extra"] = 1
        mutations.append(unknown_key)
        for files in mutations:
            with self.subTest(files=files):
                self.release.receipt = json.loads(json.dumps(original))
                self.release.receipt["files"] = files
                self.release.write_receipt()
                self.assert_rejected()

    def test_hashes_and_canonical_sha256sums_bind_every_delivery_byte(self) -> None:
        path = self.release.root / "app.bin"
        path.write_bytes(path.read_bytes() + b"mutated")
        self.assert_rejected("length")
        self.release.refresh_hashes()
        sums = self.release.root / "SHA256SUMS"
        sums.write_bytes(sums.read_bytes().replace(b" *app.bin", b"  app.bin"))
        self.release.refresh_hashes()
        # refresh_hashes canonicalized the sums; mutate only its receipt-bound bytes now.
        sums.write_bytes(sums.read_bytes().replace(b" *app.bin", b"  app.bin"))
        for record in self.release.receipt["files"]:
            if record["role"] == "sha256Sums":
                record["length"] = len(sums.read_bytes())
                record["sha256"] = sha(sums.read_bytes())
        self.release.write_receipt()
        self.assert_rejected("SHA256SUMS")

    def test_referenced_file_exceeding_global_cap_is_rejected_before_read(self) -> None:
        with (self.release.root / "app.bin").open("wb") as stream:
            stream.truncate((32 * 1024 * 1024) + 1)

        self.assert_rejected("global read cap")

    def test_qix_structure_crc_version_and_payload_relation_are_rechecked(self) -> None:
        original_payload = (self.release.root / "update.ufw").read_bytes()
        mutations = (
            b"short",
            b"XX" + qix(original_payload)[2:],
            qix(original_payload, version="11.1.0.2"),
            qix(original_payload)[:21] + b"\x01" + qix(original_payload)[22:],
            qix(original_payload)[:-1] + bytes([qix(original_payload)[-1] ^ 1]),
            qix(b"different-ufw"),
        )
        for mutated in mutations:
            with self.subTest(size=len(mutated), digest=sha(mutated)):
                (self.release.root / QIX_NAME).write_bytes(mutated)
                self.release.refresh_hashes()
                self.assert_rejected("Qix")

    def test_invalid_input_never_removes_preexisting_output(self) -> None:
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_text("keep", encoding="ascii")
        (self.release.root / "extra").write_bytes(b"bad")
        result = self.run_prepare()
        self.assertEqual(2, result.returncode)
        self.assertEqual("keep", sentinel.read_text(encoding="ascii"))


if __name__ == "__main__":
    unittest.main()
