#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.e87_build import build_authorization, validate_build_authorization
from scripts.e87_embed import ValidationError, _canonical


class AuthorizedBuildTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.apk = self.base / "app.apk"
        self.surface = self.base / "surface.json"
        self.surface.write_bytes(b"reviewed surface\n")
        self.write_apk({"classes.dex": b"first", "classes2.dex": b"second"})
        self.receipt = self.base / "build.json"
        self.write_receipt()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_apk(self, entries: dict[str, bytes]) -> None:
        with zipfile.ZipFile(self.apk, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, data in entries.items():
                archive.writestr(name, data)

    def write_receipt(self) -> None:
        self.receipt.write_bytes(_canonical(
            build_authorization(self.apk, self.surface)))

    def test_closed_receipt_binds_surface_and_every_contiguous_dex_byte(self) -> None:
        records = validate_build_authorization(
            self.receipt,
            self.apk,
            self.surface,
        )

        self.assertEqual(("classes.dex", "classes2.dex"), tuple(
            record["name"] for record in records))
        self.assertEqual((5, 6), tuple(record["length"] for record in records))
        self.assertTrue(all(len(record["sha256"]) == 64 for record in records))
        value = json.loads(self.receipt.read_bytes())
        self.assertEqual("e87-android-authorized-build-v1", value["schemaId"])
        self.assertEqual("labQualified", value["variant"])

    def test_existing_dex_implementation_or_surface_change_fails_closed(self) -> None:
        self.write_apk({
            "classes.dex": b"first with android.bluetooth.BluetoothGatt",
            "classes2.dex": b"second",
        })
        with self.assertRaises(ValidationError):
            validate_build_authorization(self.receipt, self.apk, self.surface)

        self.write_apk({"classes.dex": b"first", "classes2.dex": b"second"})
        self.surface.write_bytes(b"different reviewed surface\n")
        with self.assertRaises(ValidationError):
            validate_build_authorization(self.receipt, self.apk, self.surface)

    def test_noncontiguous_dex_or_extended_receipt_fails_closed(self) -> None:
        self.write_apk({"classes.dex": b"first", "classes3.dex": b"third"})
        with self.assertRaises(ValidationError):
            build_authorization(self.apk, self.surface)

        for name in ("classes1.dex", "classes65.dex", "classes" + "9" * 5000 + ".dex"):
            with self.subTest(name=name):
                self.write_apk({
                    "classes.dex": b"valid",
                    name: b"noncanonical",
                })
                with self.assertRaises(ValidationError):
                    build_authorization(self.apk, self.surface)

        self.write_apk({"classes.dex": b"first", "classes2.dex": b"second"})
        value = json.loads(self.receipt.read_bytes())
        value["unreviewed"] = True
        self.receipt.write_bytes(_canonical(value))
        with self.assertRaises(ValidationError):
            validate_build_authorization(self.receipt, self.apk, self.surface)

        self.receipt.write_bytes(_canonical([]))
        with self.assertRaises(ValidationError):
            validate_build_authorization(self.receipt, self.apk, self.surface)


if __name__ == "__main__":
    unittest.main()
