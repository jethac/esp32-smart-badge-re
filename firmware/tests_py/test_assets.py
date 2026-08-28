#!/usr/bin/env python3
"""Independent, literal qualification oracles for Task 4 assets."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "firmware/assets/asset-lock.json"
REQ = ROOT / "firmware/assets/requirements.txt"
GEN = ROOT / "firmware/tools/gen-assets.py"
FETCH = ROOT / "firmware/tools/fetch-assets.py"
HEADER = ROOT / "firmware/generated/e87_assets.h"
CFILE = ROOT / "firmware/generated/e87_assets.c"
MANIFEST = ROOT / "firmware/generated/assets-manifest.json"
RENDERER = ROOT / "firmware/overlay/SDK/apps/watch/e87/e87_renderer.c"
RECEIPT = Path("/tmp/e87-final-qualification.json")
RUNTIME = "127.0.0.1:5001/e87/asset-runtime@sha256:859689ef25f6940e22a5ea2427471596b42bb628bc8d308b5d3334721784d0ea"
QUALIFIER = Path("/opt/e87/qualify-runtime.py")
QUALIFIER_SIZE = 25064
QUALIFIER_SHA = "53feb64e32cb1d69f8c2a7bd30ab00f7a1859f46926dbc4f4fd657c28bb76855"
RECEIPT_SHA = "41d577c0ab31fbbc8903bfcf845d7619052548da38c6d762c9f877925e5b2cec"
ENDPOINT_SHA = "7ecb1c6da7063e52ba854231c8162da1b4ad45a9ac6cec3cafd93cd571883bb9"
WHEEL_TREE_SHA = "63ec949440b97db33b2c22e6f29b86bd8e2bd6fcbdbf6b11f3adbc1d3e32dc89"

SOURCES = {
    "date_range": (694, "firmware/assets/sources/date_range.svg", "342ef493b1d94132215ab4f25d90cbab34b448a39f50db1e929317ce8f28ab04"),
    "devin": (9266, "firmware/assets/sources/devin.svg", "0b77af4a730199892f15d99e9b812a39452554089811e46d925e62c09e09a4a9"),
    "material_license": (11357, "firmware/assets/licenses/material-design-icons-LICENSE", "58d1e17ffe5109a7ae296caafcadfdbe6a7d176f0bc4ab01e12a689b0499d8bd"),
    "roboto": (488584, "firmware/assets/sources/Roboto[wdth,wght].ttf", "d7598e12c5dbef095ff8272cfc55da0250bd07fbdecbac8a530b9b277872a134"),
    "roboto_license": (4394, "firmware/assets/licenses/Roboto-OFL.txt", "061402327a96aadb0bfb694a960ed289ecd38d383e396243831ab81feb109c41"),
    "today": (472, "firmware/assets/sources/today.svg", "c2aa056cc2353ce349bea6657053370dfbbd38dd96c0e52217615aaf02a1fa04"),
}
WHEELS = {
    "cairocffi-1.7.1-py3-none-any.whl": (75611, "9803a0e11f6c962f3b0ae2ec8ba6ae45e957a146a004697a1ac1bbf16b073b3f"),
    "cairosvg-2.9.0-py3-none-any.whl": (45962, "4b82d07d145377dffdfc19d9791bd5fb65539bb4da0adecf0bdbd9cd4ffd7c68"),
    "cffi-1.17.1-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl": (467242, "610faea79c43e44c71e1ec53a554553fa22321b65fae24889706c0a84d4ad86d"),
    "cssselect2-0.8.0-py3-none-any.whl": (15454, "46fc70ebc41ced7a32cd42d58b1884d72ade23d21e5a4eaaf022401c13f0e76e"),
    "defusedxml-0.7.1-py2.py3-none-any.whl": (25604, "a352e7e428770286cc899e2542b6cdaedb2b4953ff269a210103ec58f6198a61"),
    "fonttools-4.63.0-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl": (5082308, "d76ac49f929aecaf82d83250b8347e099d7aecba0f4726c1d9b6df3b8bb5fe18"),
    "pillow-12.2.0-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl": (7079655, "e74473c875d78b8e9d5da2a70f7099549f9eb37ded4e2f6a463e60125bccd176"),
    "pycparser-2.22-py3-none-any.whl": (117552, "c3702b6d3dd8c7abc1afa565d7e63d53a1d0bd86cdc24edd75470f4de499cfcc"),
    "tinycss2-1.4.0-py3-none-any.whl": (26610, "3a49cf47b7675da0b15d0c6e1df8df4ebd96e9394bb905a5775adb0d884c5289"),
    "webencodings-0.5.1-py2.py3-none-any.whl": (11774, "a0af1213f3c2226497a97e2b3aa01a7e4bee4f403f95be16fc9acd2947514a78"),
}

APPROVED_GENERATED_DIGESTS = {
    "e87_assets_h": "3932c79d65a78c8bfea74427d3f92e535d2bef55876a990f6aa136e674039979",
    "e87_assets_c": "8c7ca8fc4b0d0db260e109d31b218d08c7ecc480bfe7fa202701344d3f34c664",
    "assets_manifest": "3638bcf489178010579dbec423ef37343a600d62397b6f9d116c13c55241ef16",
    "devin_alpha": "78192204b1c4dd6d8f7ff151d43767b03c8dfdf15ab41892781652a98dc35566",
    "today_alpha": "84c97458173da570403da3805f21ada6545728ac8f95f4939d54667825ef3041",
    "date_range_alpha": "116b209262bc4a27924c1676e1ddcccb49b975243a07fe7c7a15e62089f4f489",
    "credit_1727_alpha": "04318759044a95b2fa4608e7835a5ee585a7baa8f20fbd42968bc3b9732deead",
}
APPROVED_ASSET_BOUNDS = {
    "devin": (0, 0, 83, 95),
    "today": (2, 1, 15, 16),
    "date_range": (2, 1, 15, 16),
    "credit_1727": (0, 0, 91, 27),
}
APPROVED_ICON_BOUNDARY_PROBES = {
    "today": (
        {"x": 4, "y": 3, "alpha": 255, "global_x": 175, "global_y": 14,
         "zero_rgb565": 0xBE18, "active_rgb565": 0x0000},
        {"x": 4, "y": 2, "alpha": 127, "global_x": 175, "global_y": 13,
         "zero_rgb565": 0x738E, "active_rgb565": 0x630C},
    ),
    "date_range": (
        {"x": 4, "y": 3, "alpha": 255, "global_x": 175, "global_y": 44,
         "zero_rgb565": 0xFFFF, "active_rgb565": 0x0000},
        {"x": 4, "y": 2, "alpha": 127, "global_x": 175, "global_y": 43,
         "zero_rgb565": 0x94B2, "active_rgb565": 0x8410},
    ),
}

ASSET_DIMENSIONS = {
    "devin": (96, 96),
    "today": (18, 18),
    "date_range": (18, 18),
    "credit_1727": (92, 28),
}

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def canonical(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()

def need(case: unittest.TestCase, path: Path) -> Path:
    label = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    case.assertTrue(path.is_file(), "missing exact required file: " + str(label))
    return path

def load(case: unittest.TestCase, path: Path) -> dict:
    raw = need(case, path).read_bytes()
    value = json.loads(raw)
    case.assertEqual(raw, canonical(value))
    return value

def blob(data: bytes) -> str:
    return hashlib.sha1(("blob %d\0" % len(data)).encode() + data).hexdigest()

def tree_digest(records: dict) -> str:
    out = bytearray()
    for name in sorted(records):
        size, digest = records[name]
        name_bytes = name.encode()
        out += struct.pack(">I", len(name_bytes)) + name_bytes
        out += struct.pack(">Q", size) + bytes.fromhex(digest)
    return sha(out)

def array(text: str, ctype: str, name: str) -> list[int]:
    match = re.search(r"(?:static\s+)?const\s+" + ctype + r"\s+" + name + r"\s*\[[^\]]*\]\s*=\s*\{(.*?)\};", text, re.S)
    if not match:
        raise AssertionError("missing C array " + name)
    return [int(x, 0) for x in re.findall(r"-?0x[0-9a-fA-F]+|-?\d+", match.group(1))]

class AssetTests(unittest.TestCase):
    maxDiff = None

    def test_asset_lock_has_only_exact_immutable_sources(self):
        lock = load(self, LOCK)
        self.assertEqual(lock["schemaVersion"], 1)
        self.assertEqual(set(lock["sources"]), set(SOURCES))
        self.assertEqual(lock["runtime"]["finalReference"], RUNTIME)
        self.assertEqual(lock["runtime"]["finalQualificationSha256"], RECEIPT_SHA)
        self.assertNotIn("/home/jethac", LOCK.read_text())

    def test_canonical_and_compiled_devin_match_blob_size_and_sha256(self):
        canonical_devin = need(self, ROOT / "assets/icons/devin.svg").read_bytes()
        compiled = need(self, ROOT / SOURCES["devin"][1]).read_bytes()
        self.assertEqual(compiled, canonical_devin)
        self.assertEqual((len(compiled), sha(compiled), blob(compiled)),
                         (9266, SOURCES["devin"][2], "0a11af513a7d208c2c49f33ab2d2d38fd4aefe90"))

    def test_font_icons_notices_and_devin_permission_status_match_literal_evidence(self):
        lock = load(self, LOCK)
        for name, (size, path, digest) in SOURCES.items():
            raw = need(self, ROOT / path).read_bytes()
            self.assertEqual((len(raw), sha(raw)), (size, digest), name)
            self.assertEqual((lock["sources"][name]["byteLength"], lock["sources"][name]["destination"], lock["sources"][name]["sha256"]),
                             (size, path, digest))
        devin = lock["sources"]["devin"]
        self.assertEqual(devin["permissionStatus"], "unverified")
        self.assertEqual(devin["canonicalSource"], "assets/icons/devin.svg")
        self.assertEqual(
            devin["tracedFrom"],
            "jethac/factory@2720aaf58a9d86a5142fd86dfb05ecb39d31364d",
        )
        self.assertNotIn("license", devin)

    def test_requirements_are_complete_exact_wheels_with_hashes(self):
        raw = need(self, REQ).read_bytes()
        self.assertEqual((len(raw), sha(raw), raw.endswith(b"\n")),
                         (976, "964dba45fb1b91a0591c4fecf0295b9e203d817d6c88388654c19a8972c66efb", False))
        actual = {p.name: (p.stat().st_size, sha(p.read_bytes())) for p in Path("/wheelhouse").iterdir() if p.is_file()}
        self.assertEqual(actual, WHEELS)
        self.assertEqual(tree_digest(actual), WHEEL_TREE_SHA)
        lock = load(self, LOCK)
        self.assertEqual(lock["wheelhouse"]["treeSha256"], WHEEL_TREE_SHA)

    def test_container_python_wheelhouse_dynamic_linker_compiler_and_full_native_closure_match_lock(self):
        lock = load(self, LOCK)
        receipt_raw = need(self, RECEIPT).read_bytes()
        self.assertEqual(sha(receipt_raw), RECEIPT_SHA)
        receipt = json.loads(receipt_raw)
        self.assertEqual(lock["runtime"]["qualification"], receipt)
        self.assertEqual(receipt["oci"]["runtimeReference"], RUNTIME)
        self.assertEqual(receipt["python"]["sha256"], "22e747b1e8a04719d4af2094133a0479b33728d2e4d03ab01539064dc6f45cfb")
        self.assertEqual(receipt["compilerAndLinkerProbe"]["compiler"]["sha256"], "75e997ec62297a6484f491bae28ab0ccb489daba23e398fd10fe68e9e6f0def8")
        self.assertEqual(receipt["nativeClosure"]["treeSha256"], "31562f9b0287db247aba1c46186cc9aea8272d06dd5e2370f51c38527e19e6de")
        self.assertEqual(len(receipt["nativeClosure"]["members"]), 126)
        qualifier_raw = need(self, QUALIFIER).read_bytes()
        self.assertEqual((len(qualifier_raw), sha(qualifier_raw)),
                         (QUALIFIER_SIZE, QUALIFIER_SHA))

        spec = importlib.util.spec_from_file_location("e87_gen_assets_live", GEN)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(callable(module.begin_generation_qualification))
        self.assertTrue(callable(module.finish_generation_qualification))

        probe = r"""
import importlib.util
from pathlib import Path
import sys
import tempfile

spec = importlib.util.spec_from_file_location("e87_actual_raster_process", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
lock, lock_raw = module._lock()
state = module.begin_generation_qualification(lock)
with tempfile.TemporaryDirectory(prefix="e87-live-raster-", dir="/tmp") as temp:
    module.generate(Path(temp), lock, lock_raw)
module.finish_generation_qualification(lock, state)
print("CLEAN_QUALIFICATION_OK", flush=True)

import ctypes
ctypes.CDLL("/usr/lib/x86_64-linux-gnu/libuuid.so.1")
try:
    module.finish_generation_qualification(lock, state)
except ValueError as error:
    if "mapped file inventory differs" not in str(error):
        raise
    print("LATE_NATIVE_REJECTED", flush=True)
else:
    raise RuntimeError("late-loaded native member was accepted")
"""
        result = subprocess.run(
            [sys.executable, "-c", probe, str(GEN)],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            result.stdout + result.stderr,
        )
        self.assertEqual(
            result.stdout.splitlines(),
            ["CLEAN_QUALIFICATION_OK", "LATE_NATIVE_REJECTED"],
        )

    def test_generated_assets_have_exact_symbols_dimensions_and_byte_counts(self):
        manifest = load(self, MANIFEST)
        for name, expected in {"devin": (96,96,9216), "today": (18,18,324), "date_range": (18,18,324)}.items():
            item = manifest["assets"][name]
            self.assertEqual((item["width"], item["height"], item["byteCount"]), expected)
            self.assertEqual(item["symbol"], "e87_asset_" + name)
        credit = manifest["assets"]["credit_1727"]
        self.assertLessEqual(credit["width"], 128)
        self.assertLessEqual(credit["height"], 40)
        self.assertEqual(credit["byteCount"], credit["width"] * credit["height"])

    def test_generated_masks_and_endpoint_tables_match_literal_approved_hashes(self):
        manifest = load(self, MANIFEST)
        actual = {"e87_assets_h": sha(need(self, HEADER).read_bytes()),
                  "e87_assets_c": sha(need(self, CFILE).read_bytes()),
                  "assets_manifest": sha(need(self, MANIFEST).read_bytes())}
        source = CFILE.read_text()
        masks = {}
        for name, (width, height) in ASSET_DIMENSIONS.items():
            values = array(source, "uint8_t", "e87_asset_" + name + "_alpha")
            self.assertEqual(len(values), width * height)
            masks[name] = bytes(values)
            actual[name + "_alpha"] = sha(masks[name])
            self.assertEqual(manifest["assets"][name]["alphaSha256"], actual[name + "_alpha"])
            nonzero = [(i % width, i // width) for i, value in enumerate(values) if value]
            bounds = (min(x for x, _ in nonzero), min(y for _, y in nonzero),
                      max(x for x, _ in nonzero), max(y for _, y in nonzero))
            self.assertEqual(bounds, APPROVED_ASSET_BOUNDS[name])
            self.assertEqual(manifest["assets"][name]["nonzeroBounds"], list(bounds))
        self.assertEqual(actual, APPROVED_GENERATED_DIGESTS)

        ring_geometry = {
            "today": {"top": 11, "inner": 149, "outer": 171,
                      "active": (191, 195, 199), "track": (34, 35, 36)},
            "date_range": {"top": 41, "inner": 119, "outer": 141,
                           "active": (255, 255, 255), "track": (46, 46, 46)},
        }

        def blend(source_rgb, destination_rgb, alpha):
            return tuple((s * alpha + d * (255 - alpha) + 127) // 255
                         for s, d in zip(source_rgb, destination_rgb))

        def rgb565(rgb):
            return ((rgb[0] >> 3) << 11) | ((rgb[1] >> 2) << 5) | (rgb[2] >> 3)

        for name in ("today", "date_range"):
            values = masks[name]
            geometry = ring_geometry[name]
            for index, alpha in enumerate(values):
                if not alpha:
                    continue
                x, y = index % 18, index // 18
                for ox, oy in ((1, 1), (3, 1), (1, 3), (3, 3)):
                    cap_x = (x - 9) * 4 + ox
                    cap_y = (y - 9) * 4 + oy
                    self.assertLessEqual(cap_x * cap_x + cap_y * cap_y, (11 * 4) ** 2)
            for probe in APPROVED_ICON_BOUNDARY_PROBES[name]:
                self.assertEqual(values[18 * probe["y"] + probe["x"]], probe["alpha"])
                self.assertEqual((171 + probe["x"], geometry["top"] + probe["y"]),
                                 (probe["global_x"], probe["global_y"]))
                for ox, oy in ((1, 1), (3, 1), (1, 3), (3, 3)):
                    dx = (probe["global_x"] - 180) * 4 + ox
                    dy = (probe["global_y"] - 180) * 4 + oy
                    distance = dx * dx + dy * dy
                    self.assertGreaterEqual(distance, (geometry["inner"] * 4) ** 2)
                    self.assertLessEqual(distance, (geometry["outer"] * 4) ** 2)
                self.assertEqual(
                    probe["zero_rgb565"],
                    rgb565(blend(geometry["active"], geometry["track"], probe["alpha"])))
                self.assertEqual(
                    probe["active_rgb565"],
                    rgb565(blend((0, 0, 0), geometry["active"], probe["alpha"])))

    def test_renderer_uses_exact_translated_asset_placements(self):
        renderer = need(self, RENDERER).read_text()

        def literal_placement(asset: str) -> tuple[int, int]:
            match = re.search(
                r"e87_blend_asset\(\s*&color,\s*x,\s*y,\s*"
                r"(\d+)u,\s*(\d+)u,\s*&e87_asset_" + asset,
                renderer,
            )
            self.assertIsNotNone(match, "missing literal placement for " + asset)
            return int(match.group(1)), int(match.group(2))

        self.assertEqual(literal_placement("today"), (171, 11))
        self.assertEqual(literal_placement("date_range"), (171, 41))
        self.assertEqual(literal_placement("devin"), (132, 118))
        self.assertRegex(renderer, r"\bE87_FACE_CENTER\s*=\s*180\b")
        self.assertIn(
            "credit_left = E87_FACE_CENTER - e87_asset_credit_1727.width / 2u;",
            renderer,
        )
        self.assertIn(
            "credit_top = 240u - e87_asset_credit_1727.height / 2u;",
            renderer,
        )

    def test_endpoint_table_pins_cardinals_symmetry_and_all_101_bounds(self):
        source = need(self, CFILE).read_text()
        cos = array(source, "int32_t", "e87_ring_cos_q16")
        sin = array(source, "int32_t", "e87_ring_sin_q16")
        self.assertEqual((len(cos), len(sin)), (101, 101))
        packed = b"".join(struct.pack("<i", v) for pair in zip(cos, sin) for v in pair)
        self.assertEqual(sha(packed), ENDPOINT_SHA)
        self.assertEqual([(cos[p], sin[p]) for p in (0,25,50,75,100)],
                         [(65536,0),(0,65536),(-65536,0),(0,-65536),(65536,0)])
        self.assertEqual((cos[1], sin[1], cos[99], sin[99]), (65407,4115,65407,-4115))

    def test_manifest_is_canonical_complete_and_host_path_free(self):
        manifest = load(self, MANIFEST)
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(manifest["lockSha256"], sha(need(self, LOCK).read_bytes()))
        self.assertEqual(manifest["requirementsSha256"], sha(need(self, REQ).read_bytes()))
        self.assertEqual(manifest["generatorSha256"], sha(need(self, GEN).read_bytes()))
        self.assertEqual(manifest["generation"]["fontAxes"], {"wdth":100,"wght":500})
        self.assertEqual(manifest["generation"]["glyphs"], ["$",".","1","2","7"])
        self.assertEqual(
            manifest["sources"]["devin"]["canonicalSource"],
            "assets/icons/devin.svg",
        )
        self.assertEqual(
            manifest["sources"]["devin"]["tracedFrom"],
            "jethac/factory@2720aaf58a9d86a5142fd86dfb05ecb39d31364d",
        )
        for forbidden in ("/home/", "C:\\", "/tmp/site", "timestamp", "generatedAt"):
            self.assertNotIn(forbidden, MANIFEST.read_text())

    def test_clean_double_generation_is_byte_identical_and_offline(self):
        need(self, GEN)
        result = subprocess.run([sys.executable, str(GEN), "--check-reproducible"], cwd=ROOT,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_generated_c_is_immutable_data_only_and_has_no_sdk_or_runtime_rasterizer(self):
        text = need(self, CFILE).read_text()
        self.assertEqual(text.count("#include"), 1)
        self.assertIn('#include "e87_assets.h"', text)
        for token in ("malloc(", "free(", "dbi", "lcd_", "cairo", "PIL", "static uint8_t", "E87_HOST_TEST"):
            self.assertNotIn(token, text)

    def test_wrong_devin_font_axis_scale_filter_or_source_fails_closed(self):
        need(self, GEN)
        spec = importlib.util.spec_from_file_location("e87_gen_assets", GEN)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        devin = need(self, ROOT / SOURCES["devin"][1]).read_bytes()
        with self.assertRaises(ValueError):
            module.validate_source_bytes("devin", devin + b"x")
        for args in ((499,100,8,"BOX"),(500,99,8,"BOX"),(500,100,7,"BOX"),(500,100,8,"LANCZOS")):
            with self.assertRaises(ValueError):
                module.validate_generation_settings(*args)
        with tempfile.TemporaryDirectory(
            prefix="e87-unexpected-output-", dir="/tmp"
        ) as temp:
            output_root = Path(temp)
            unexpected = output_root / "not-an-approved-output"
            unexpected.write_bytes(b"preserve me")
            outputs = {name: b"new output" for name in (
                "e87_assets.h", "e87_assets.c", "assets-manifest.json"
            )}
            with self.assertRaisesRegex(ValueError, "unexpected generated output"):
                module.write_files(output_root, outputs)
            self.assertEqual(unexpected.read_bytes(), b"preserve me")
            for name in outputs:
                self.assertFalse((output_root / name).exists())

if __name__ == "__main__":
    unittest.main(verbosity=2)
