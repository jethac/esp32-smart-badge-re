#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.e87_embed import ValidationError, _canonical
from scripts.e87_surface import build_surface, validate_surface


class AuthorizedSurfaceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.source = self.base / "src"
        path = self.source / "net/jethachan/factory_badges/One.java"
        path.parent.mkdir(parents=True)
        path.write_text("package net.jethachan.factory_badges; final class One {}\n",
                        encoding="ascii")
        self.dump = """Opened '/tmp/app.apk:classes.dex', DEX version '039'
Class #0            -
  Class descriptor  : 'Lnet/jethachan/factory_badges/One;'
  Superclass        : 'Ljava/lang/Object;'
"""
        self.receipt = self.base / "surface.json"
        self.receipt.write_bytes(_canonical(build_surface(self.source, self.dump)))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_closed_receipt_binds_exact_source_inventory_hashes_and_descriptors(self) -> None:
        descriptors = validate_surface(self.receipt, self.source)

        self.assertEqual(("Lnet/jethachan/factory_badges/One;",), descriptors)
        value = json.loads(self.receipt.read_bytes())
        self.assertEqual("e87-android-authorized-app-surface-v1", value["schemaId"])
        self.assertEqual(
            "net/jethachan/factory_badges/One.java",
            value["sourceFiles"][0]["path"],
        )

    def test_any_source_change_addition_or_receipt_extension_fails_closed(self) -> None:
        source = self.source / "net/jethachan/factory_badges/One.java"
        source.write_text(source.read_text(encoding="ascii") + "// changed\n",
                          encoding="ascii")
        with self.assertRaises(ValidationError):
            validate_surface(self.receipt, self.source)

        source.write_text("package net.jethachan.factory_badges; final class One {}\n",
                          encoding="ascii")
        extra = source.with_name("Two.java")
        extra.write_text("package net.jethachan.factory_badges; final class Two {}\n",
                         encoding="ascii")
        with self.assertRaises(ValidationError):
            validate_surface(self.receipt, self.source)

        extra.unlink()
        value = json.loads(self.receipt.read_bytes())
        value["unreviewed"] = True
        self.receipt.write_bytes(_canonical(value))
        with self.assertRaises(ValidationError):
            validate_surface(self.receipt, self.source)

    def test_generator_rejects_duplicate_or_non_application_descriptors(self) -> None:
        duplicate = self.dump + self.dump.split("Class #0", 1)[1]
        with self.assertRaises(ValidationError):
            build_surface(self.source, duplicate)
        with self.assertRaises(ValidationError):
            build_surface(
                self.source,
                self.dump.replace(
                    "Lnet/jethachan/factory_badges/One;", "Lexample/Hidden;"),
            )


if __name__ == "__main__":
    unittest.main()
