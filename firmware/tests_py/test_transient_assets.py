#!/usr/bin/env python3
"""Independent oracles for the isolated transient-screen asset corpus."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "firmware/assets/transient-asset-lock.json"
SPEC = ROOT / "firmware/assets/transient-ui.json"
BOLT = ROOT / "firmware/assets/sources/bolt.svg"
GEN = ROOT / "firmware/tools/gen-transient-assets.py"
FETCH = ROOT / "firmware/tools/fetch-transient-assets.py"
HEADER = ROOT / "firmware/generated/e87_transient_assets.h"
CFILE = ROOT / "firmware/generated/e87_transient_assets.c"
MANIFEST = ROOT / "firmware/generated/transient-assets-manifest.json"

BOLT_SHA = "13195a03d22906ca3c7a78fc6e104cb269b98ddac7dca96c424fadc623c33f3c"
ROBOTO_SHA = "d7598e12c5dbef095ff8272cfc55da0250bd07fbdecbac8a530b9b277872a134"
BASE_LOCK_SHA = "7832996bc29c95c2a4374280cc4014af322d840b98b97fb29006399a6a774b2b"
NORMAL_DIGESTS = {
    "firmware/generated/e87_assets.c":
        "8c7ca8fc4b0d0db260e109d31b218d08c7ecc480bfe7fa202701344d3f34c664",
    "firmware/generated/e87_assets.h":
        "3932c79d65a78c8bfea74427d3f92e535d2bef55876a990f6aa136e674039979",
    "firmware/generated/assets-manifest.json":
        "3638bcf489178010579dbec423ef37343a600d62397b6f9d116c13c55241ef16",
    "firmware/generated/goldens/goldens-manifest.json":
        "05dbe18a1ce292f51d7afbc2d511f536801b4ce1ed054814d8823bf75745a8e5",
}
TRANSIENT_DIGESTS = {
    "lock": "bf28b7cc21fc3154a3c90dc29027fb44ef212b0cc5980c86046eedd8f203f420",
    "spec": "ff389bbc002c4aa4bde4bd980836fb85e65aa39c22212a73acef96cc8c6ce7af",
    "header": "92080a640ea2f3dbb8376848b7759fb47d9253c8386ae31fe2c5001ddc251134",
    "c": "ba23e72ca2fbb473234ab0f7f88ac00b78f755e3cfd8d335a29445897583e32a",
    "manifest": "13bd2ebc4ab1308e9af00354ed4cc15681b1dcc4f1f78335bbaf205d66901efc",
    "glyphAlpha": "eff1d93b8d46844b78d4b6ec07287492292a19f74ce5876877eb7785cfffa044",
    "boltAlpha": "f12a1745739a5cbfe2d57f057e9cf77186b5c06dacabedd81f1bf54ff085a6cb",
}
GLYPHS = " %0123456789ABDEFGHIKLMNOPRSTUWY"
STRINGS = {
    "batteryError": "BATTERY ERROR",
    "batteryStale": "BATTERY OLD",
    "holdHint": "HOLD BUTTON 1",
    "maintenanceReady": "READY TO UPDATE",
    "pairMe": "PAIR ME NOW",
    "pairing": "PAIRING",
    "phoneReady": "PHONE READY",
    "releaseButton": "RELEASE BUTTON",
    "update": "UPDATE",
    "updateError": "UPDATE ERROR",
    "updateWarningLine1": "KEEP HOLDING",
    "updateWarningLine2": "FOR UPDATE",
    "waitingForPhone": "WAITING FOR PHONE",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) +
            "\n").encode()


def load_canonical(test: unittest.TestCase, path: Path) -> dict:
    test.assertTrue(path.is_file(), "missing exact required file: " + str(path))
    raw = path.read_bytes()
    value = json.loads(raw)
    test.assertEqual(raw, canonical(value))
    test.assertIsInstance(value, dict)
    return value


def array(source: str, c_type: str, name: str) -> list[int]:
    match = re.search(
        r"(?:static\s+)?const\s+" + re.escape(c_type) + r"\s+" +
        re.escape(name) + r"(?:\[[^\]]*\])?\s*=\s*\{(.*?)\};",
        source,
        re.S,
    )
    if match is None:
        raise AssertionError("missing generated array: " + name)
    return [int(token, 0) for token in
            re.findall(r"(?<![A-Za-z_])(?:0x[0-9a-fA-F]+|\d+)", match.group(1))]


class TransientAssetTests(unittest.TestCase):
    maxDiff = None

    def test_reviewed_normal_asset_and_golden_bytes_are_unchanged(self):
        for relative, expected in NORMAL_DIGESTS.items():
            path = ROOT / relative
            self.assertTrue(path.is_file(), "missing reviewed normal artifact")
            self.assertEqual(sha(path.read_bytes()), expected, relative)

    def test_transient_lock_is_canonical_and_pins_only_reused_font_and_bolt(self):
        lock = load_canonical(self, LOCK)
        self.assertEqual(lock["schemaVersion"], 1)
        self.assertEqual(lock["baseAssetLockSha256"], BASE_LOCK_SHA)
        self.assertEqual(set(lock["sources"]), {"bolt", "roboto"})
        self.assertEqual(lock["sources"]["bolt"], {
            "byteLength": 335,
            "destination": "firmware/assets/sources/bolt.svg",
            "license": "Apache-2.0",
            "repository": "google/material-design-icons",
            "sha256": BOLT_SHA,
            "upstreamCommit": "e083cc60a0828fdd3b404cea0cb8a5b900e9c23e",
            "upstreamPath":
                "symbols/web/bolt/materialsymbolsrounded/bolt_24px.svg",
        })
        self.assertEqual(lock["sources"]["roboto"], {
            "byteLength": 488584,
            "destination": "firmware/assets/sources/Roboto[wdth,wght].ttf",
            "license": "OFL-1.1",
            "sha256": ROBOTO_SHA,
        })

    def test_downloaded_bolt_has_exact_primary_source_identity(self):
        self.assertTrue(BOLT.is_file(), "missing pinned rounded bolt source")
        raw = BOLT.read_bytes()
        self.assertEqual((len(raw), sha(raw)), (335, BOLT_SHA))
        self.assertIn(b'viewBox="0 -960 960 960"', raw)
        self.assertNotIn(b"<script", raw.lower())
        self.assertNotRegex(raw.decode("ascii"), r"(?:href|url\s*\()")

    def test_ui_lock_freezes_strings_layout_font_and_glyph_closure(self):
        spec = load_canonical(self, SPEC)
        self.assertEqual(spec["schemaVersion"], 1)
        self.assertEqual(spec["display"], {"height": 360, "stripRows": 30,
                                           "width": 360})
        self.assertEqual(spec["font"], {
            "advanceScale": 8,
            "family": "Roboto",
            "filter": "BOX",
            "pixelSize": 30,
            "rasterScale": 8,
            "weight": 500,
            "width": 100,
        })
        self.assertEqual(spec["glyphs"], GLYPHS)
        self.assertEqual(spec["strings"], STRINGS)
        used = set("".join(STRINGS.values()) + "%0123456789")
        self.assertEqual(set(GLYPHS), used)
        self.assertEqual(len(GLYPHS), len(set(GLYPHS)))
        self.assertEqual(spec["batteryOverlay"], {
            "bigGlyphScale": 2,
            "blackAlpha": 191,
            "durationMs": 2500,
        })
        self.assertEqual(spec["bolt"], {
            "height": 18,
            "topOffsetFromBaselineY": -31,
            "width": 18,
        })

    def test_generated_interface_is_packed_bitmap_data_without_font_runtime(self):
        self.assertEqual(sha(LOCK.read_bytes()), TRANSIENT_DIGESTS["lock"])
        self.assertEqual(sha(SPEC.read_bytes()), TRANSIENT_DIGESTS["spec"])
        self.assertEqual(sha(HEADER.read_bytes()), TRANSIENT_DIGESTS["header"])
        self.assertEqual(sha(CFILE.read_bytes()), TRANSIENT_DIGESTS["c"])
        self.assertEqual(
            sha(MANIFEST.read_bytes()), TRANSIENT_DIGESTS["manifest"])
        header = HEADER.read_text()
        source = CFILE.read_text()
        self.assertIn("#define E87_TRANSIENT_GLYPH_COUNT 32u", header)
        self.assertIn("struct e87_bitmap_glyph", header)
        self.assertIn("e87_transient_glyph_alpha", header)
        self.assertIn("e87_transient_asset_bolt", header)
        self.assertNotRegex(source, r"\b(?:malloc|calloc|realloc|free)\s*\(")
        self.assertNotIn("Roboto", source)
        self.assertNotIn("Pillow", source)

        manifest = load_canonical(self, MANIFEST)
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(manifest["glyphOrder"], list(GLYPHS))
        self.assertEqual(manifest["font"], {
            "advanceScale": 8,
            "family": "Roboto",
            "filter": "BOX",
            "pixelSize": 30,
            "rasterScale": 8,
            "weight": 500,
            "width": 100,
        })
        self.assertEqual(manifest["bolt"]["width"], 18)
        self.assertEqual(manifest["bolt"]["height"], 18)
        self.assertEqual(manifest["bolt"]["byteCount"], 324)
        self.assertEqual(manifest["sources"]["bolt"]["sha256"], BOLT_SHA)
        self.assertEqual(manifest["sources"]["roboto"]["sha256"], ROBOTO_SHA)
        self.assertEqual(manifest["uiSpec"]["sha256"], sha(SPEC.read_bytes()))

        alpha = array(source, "uint8_t", "e87_transient_glyph_alpha")
        self.assertEqual(len(alpha), manifest["glyphAlphaByteCount"])
        self.assertEqual(
            sha(bytes(alpha)),
            manifest["glyphAlphaSha256"],
        )
        self.assertEqual(sha(bytes(alpha)), TRANSIENT_DIGESTS["glyphAlpha"])
        bolt = array(source, "uint8_t", "e87_transient_bolt_alpha")
        self.assertEqual(sha(bytes(bolt)), TRANSIENT_DIGESTS["boltAlpha"])
        offsets = [entry["alphaOffset"] for entry in manifest["glyphs"]]
        self.assertEqual(offsets, sorted(offsets))
        for index, entry in enumerate(manifest["glyphs"]):
            self.assertEqual(entry["ascii"], ord(GLYPHS[index]))
            self.assertEqual(entry["character"], GLYPHS[index])
            self.assertGreater(entry["advanceQ3"], 0)
            self.assertEqual(entry["byteCount"],
                             entry["width"] * entry["height"])
            if index + 1 < len(manifest["glyphs"]):
                self.assertEqual(offsets[index + 1],
                                 offsets[index] + entry["byteCount"])
        self.assertEqual(manifest["glyphs"][0]["byteCount"], 0)
        self.assertEqual(manifest["glyphs"][0]["character"], " ")

    def test_fetcher_offline_check_and_generator_replay_succeed(self):
        for path in (FETCH, GEN):
            self.assertTrue(path.is_file(), "missing deterministic tool")
        fetch = subprocess.run(
            [sys.executable, str(FETCH), "--check"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(fetch.returncode, 0, fetch.stdout + fetch.stderr)
        generated = subprocess.run(
            [sys.executable, str(GEN), "--check-reproducible"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(generated.returncode, 0,
                         generated.stdout + generated.stderr)


if __name__ == "__main__":
    unittest.main()
