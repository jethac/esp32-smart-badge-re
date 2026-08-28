#!/usr/bin/env python3
"""Independent golden and production-boundary oracles for Task 4."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "firmware/tools/render-goldens.py"
HELPER = ROOT / "firmware/host/render_renderer.c"
GOLDEN_ROOT = ROOT / "firmware/generated/goldens"
MANIFEST = GOLDEN_ROOT / "goldens-manifest.json"
CC = "/usr/bin/x86_64-linux-gnu-gcc-12"
CC_SHA = "75e997ec62297a6484f491bae28ab0ccb489daba23e398fd10fe68e9e6f0def8"
LD_SHA = "f6d71a1bcd45764550a42dfaa179bc43b63ee879ec6f875bfd39fca013515da7"
RUNTIME = "127.0.0.1:5001/e87/asset-runtime@sha256:859689ef25f6940e22a5ea2427471596b42bb628bc8d308b5d3334721784d0ea"
VALUES = (0, 1, 50, 99, 100)
RAW_BYTES = 360 * 360 * 2
PNG_NAMES = tuple(
    f"face-day-{day:03d}-week-{week:03d}.png"
    for day in VALUES
    for week in VALUES
)
INPUT_PATHS = (
    "firmware/host/render_renderer.c",
    "firmware/overlay/SDK/apps/watch/e87/e87_renderer.c",
    "firmware/overlay/SDK/apps/watch/include/e87/e87_renderer.h",
    "firmware/overlay/SDK/apps/watch/include/e87/e87_state.h",
    "firmware/overlay/SDK/apps/watch/include/e87/e87_types.h",
    "firmware/generated/e87_assets.c",
    "firmware/generated/e87_assets.h",
)
LINKER_PROBE = (
    "/usr/bin/x86_64-linux-gnu-gcc-12",
    "-B/usr/bin/",
    "-fuse-ld=bfd",
    "-print-prog-name=ld",
)
COMPILE_ARGUMENTS = (
    "/usr/bin/x86_64-linux-gnu-gcc-12",
    "-B/usr/bin/",
    "-fuse-ld=bfd",
    "-std=c11",
    "-O0",
    "-Wall",
    "-Wextra",
    "-Werror",
    "-pedantic",
    "-fno-common",
    "-DE87_HOST_TEST=1",
    "-Wl,--build-id=none",
    "-I",
    "firmware/host",
    "-I",
    "firmware/overlay/SDK/apps/watch/include",
    "-I",
    "firmware/generated",
    "firmware/host/render_renderer.c",
    "firmware/overlay/SDK/apps/watch/e87/e87_renderer.c",
    "firmware/generated/e87_assets.c",
    "-o",
    "$TMP/render_renderer",
)

# Controller-approved characterization registry.
APPROVED_GOLDEN_MANIFEST_SHA256 = "05dbe18a1ce292f51d7afbc2d511f536801b4ce1ed054814d8823bf75745a8e5"
APPROVED_GOLDEN_DIGESTS = {
    "face-day-000-week-000.png": {"raw": "901c3d3c1b7622f16cf1cd95e6ee2127979df16420a7e23acc6cdbd63ea30cc7", "png": "9e325c1e89af0e1c9e0ea7d08cb5672a94054d9459b570f55756f1f94fcd2980"},
    "face-day-000-week-001.png": {"raw": "2b32fe454fd2741a747029dfc0c6d471dafbf78ec18879b0e80e7695e7e2008b", "png": "ca29e5c19d79070eb6d7412ddf417b5e25864ffb2015b5f2e9681c8ffa3767f9"},
    "face-day-000-week-050.png": {"raw": "e67329e742e1e9eb2cc1d77f4f56affd93a4ff7cbd45dffafd2fa71d40617d55", "png": "305eb695b864cf413bcb26fbd2e34d1ad0c9bfeb1dd050e57749c11b4e867426"},
    "face-day-000-week-099.png": {"raw": "0c79f9790c5ca7f0838001951a2cdfa3539cbef6aa61182d545fed0df244944a", "png": "8acec6bba408f6a9ebf6bf779fd2403a089ac7ea7d3ea5e9cdf9a39b3cb5fd3f"},
    "face-day-000-week-100.png": {"raw": "5895ec8896ed2b400728ea8a04193a6f6943150d7a891c4af5bc69da76bac4f4", "png": "066bfc7f444567aab9b7bb1252f46f45733ee70395193f8c00f083e9c66f1017"},
    "face-day-001-week-000.png": {"raw": "b39f5a516b41196137b05aa265e32b0016ab967d3dc72cbf60f952363dd0549a", "png": "5d32f68cc80b7558e25fe83a80e17f32e68d11ec42823661ab51f0ad38d31bb3"},
    "face-day-001-week-001.png": {"raw": "b38a84048647adf76703ec7194d4f9f9b4819d050da8dba6f351f6a685a9ad8b", "png": "a27170f22044ce67e66ed9f27b98c209635d37e618aac87e79408dd38ee9b554"},
    "face-day-001-week-050.png": {"raw": "9441de8f792a92d1abc0de6165b8ec64aa1451b90008c1cd22a214401457e4a4", "png": "5b6cd30ae94de68b7031bd006fa607ff79ab08cffaef6bfaa328609127dc5c1a"},
    "face-day-001-week-099.png": {"raw": "fbb600e1fd7394e645e10109a592ac9a58c7cf6978478481f862454d38ac8bc0", "png": "676d97aa0b37fdc4f3a2ae501c24d79e5a1d925c74a3aa0ee5744f61521c54c5"},
    "face-day-001-week-100.png": {"raw": "e6d7b593853d9cdd48319d1ae5a34635e7fa25f830693b71c2821bc8d4a1f265", "png": "c5ad3e789b008260fa240953debeecaa1003c279b06caba23ec12c114f56aec6"},
    "face-day-050-week-000.png": {"raw": "a662f101b82a2d4b3f370e58a465c5c4f7ece4f9fd46f4f6e105584f65ed05fe", "png": "89973df4cbd46ef60c28732c036762489f5da673b1c3bd89fb81d808b6b728e6"},
    "face-day-050-week-001.png": {"raw": "619113c25343ae28201c8de6f6496ad2567fb4317c95197e326bd839397d18d3", "png": "9a1165bb72e11074c8cdf332819c7039b31f8ce6b09b1289f234f65da784f946"},
    "face-day-050-week-050.png": {"raw": "7140747cd7330279966bf1bc9bc4df192b57be05b91b2b8dfc8e9deadfb02509", "png": "98eebf64a5901ef155f6fee9c8869b27cac1acc9832b981267246d84ba5155f4"},
    "face-day-050-week-099.png": {"raw": "9afee595dd3e2a8e3f8e9c75c088a6fb69880ebdcf97aa2bf25b9936eb7cba74", "png": "a2edd0cd7543c59a5d1ea6ed5c9ed3f1f8981d911bf5df6aca820b8f086560c5"},
    "face-day-050-week-100.png": {"raw": "95f8fc9fd4caeee10dc68a44c0b2fe7e4a0d0da4dae154f0b395bc6b9aa1b432", "png": "8eaadfb6385af39f7060e660c2e992ff7954f749d9d741eadc57b7c510b11e39"},
    "face-day-099-week-000.png": {"raw": "3221333b1f63536ffd94c99fbb05103812f4fe0128eec204bf33b2cebd5d9a79", "png": "2fd47e6418314f5cc8a2abc921a5e7ae6b452d39d9cee901b5d1bbeb17961285"},
    "face-day-099-week-001.png": {"raw": "7881421646cf98a75ef74b07aaf9573a7347c5984dc428fca980bd8923d200f5", "png": "23c6fbb7e787d389c430446d89f94a88850d590a2efce6ef07f32120bd94e023"},
    "face-day-099-week-050.png": {"raw": "189e7282b67e420bfc98cfeff24cc6ffedc1041bd0286a7fb07fe869827e5c1a", "png": "31c15fdcc58e635eadc432f067916bc92d727937347044560a5c837663f7734b"},
    "face-day-099-week-099.png": {"raw": "64829d5db498f94e9539c7333aedd615f5a2d4825272c0cdd209894aa586946d", "png": "d52b80a9ae926d9680d97700842b51fe7a29d09161721e85717ed8c694fc2120"},
    "face-day-099-week-100.png": {"raw": "4affa7c9fa5243f7fcd00c16a2a4e7fcf2c9e0406c929cc14b9fe0e7c3e10c8e", "png": "a120abb031254a73f02ae921b9b1cf19c346bf19797b98bf5379a1cac9aa3159"},
    "face-day-100-week-000.png": {"raw": "cfdaa67ce00f715a29467dcd540848d65461ec7dec423e0ab7cd220511231f39", "png": "7d8135a59e7d69ae2cc4c706463372c0192c44df2217942dcb274966b680de59"},
    "face-day-100-week-001.png": {"raw": "2daf195d54b0054e6ea92a35857f3b4423b40385799c12999ce9a92e1f211c52", "png": "ff042cf362fadd9ea96af5696da590eac4f94d766714790fa8fef615d3bd8669"},
    "face-day-100-week-050.png": {"raw": "2a87c5dc5adc0438d2916d0d7666af94a2ef7f9fec882ab6f791442bae5bc667", "png": "21ad909fb1710d653291e8c71b42b7bc1427e27b2c82668672f8c257d4f58ad8"},
    "face-day-100-week-099.png": {"raw": "8c094ceaf03bee6b6d6b7dce3b4494780f4fa39a0636b7c8e9e0545fd0c7802c", "png": "2a453a22dc17f56b11c6e20760351d2ad9c3318807ccd0038f0073106969bc80"},
    "face-day-100-week-100.png": {"raw": "7ee0c97798d20080ee73134ec0432cb62c028dbb8683c109a63d79c5ea4a6450", "png": "350297537231c3dacee35be562ce4583c7832f251e5a603a440d006c62e06b2c"},
}

LITERAL_PROBES = {
    (0, 0): (
        (340, 180, 0x2104),
        (310, 180, 0x2965),
        (175, 14, 0xBE18),
        (175, 44, 0xFFFF),
        (164, 9, 0x1082),
        (165, 39, 0x0861),
        (150, 119, 0xFFFF),
        (141, 227, 0xFFFF),
        (0, 0, 0x0000),
    ),
    (1, 1): (
        (180, 9, 0xBE18),
        (171, 20, 0xBE18),
        (199, 20, 0xBE18),
        (171, 50, 0xFFFF),
        (197, 50, 0xFFFF),
        (175, 13, 0x630C),
        (175, 43, 0x8410),
    ),
    (50, 50): (
        (340, 180, 0xBE18),
        (20, 180, 0x2104),
        (310, 180, 0xFFFF),
        (50, 180, 0x2965),
    ),
    (99, 99): (
        (180, 10, 0xBE18),
        (170, 10, 0xBE18),
        (180, 40, 0xFFFF),
        (172, 40, 0xFFFF),
    ),
    (100, 100): (
        (170, 20, 0xBE18),
        (190, 20, 0xBE18),
        (170, 50, 0xFFFF),
        (190, 50, 0xFFFF),
    ),
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def scene_name(day: int, week: int) -> str:
    return f"face-day-{day:03d}-week-{week:03d}.png"


def rgb565(pixel: tuple[int, int, int]) -> int:
    red, green, blue = pixel
    return ((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3)


class GoldenTests(unittest.TestCase):
    maxDiff = None

    def need(self, path: Path) -> Path:
        self.assertTrue(path.is_file(), "missing exact required file: " + str(path))
        return path

    def manifest(self) -> dict:
        raw = self.need(MANIFEST).read_bytes()
        self.assertEqual(sha(raw), APPROVED_GOLDEN_MANIFEST_SHA256)
        value = json.loads(raw)
        self.assertEqual(raw, canonical(value))
        return value

    def image(self, day: int, week: int) -> Image.Image:
        path = self.need(GOLDEN_ROOT / scene_name(day, week))
        image = Image.open(path)
        image.load()
        self.addCleanup(image.close)
        return image

    def run_tool(self, mode: str) -> subprocess.CompletedProcess[str]:
        self.need(TOOL)
        return subprocess.run(
            [
                sys.executable,
                str(TOOL),
                mode,
                "--cc",
                CC,
                "--require-compiler-sha256",
                CC_SHA,
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

    def test_golden_set_is_exact_cartesian_0_1_50_99_100(self):
        manifest = self.manifest()
        scenes = manifest["scenes"]
        self.assertEqual(
            [(scene["day"], scene["week"]) for scene in scenes],
            [(day, week) for day in VALUES for week in VALUES],
        )
        self.assertEqual(
            tuple(scene["png"] for scene in scenes),
            PNG_NAMES,
        )
        actual = tuple(sorted(path.name for path in GOLDEN_ROOT.glob("*.png")))
        self.assertEqual(actual, tuple(sorted(PNG_NAMES)))
        self.assertEqual(len(scenes), 25)

    def test_every_png_is_360_square_rgb_and_manifest_is_canonical(self):
        manifest = self.manifest()
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(manifest["dimensions"], {"height": 360, "width": 360})
        self.assertEqual(manifest["pixelFormat"], "RGB565-word-little-endian")
        self.assertEqual(manifest["fixedCreditCents"], 1727)
        for scene in manifest["scenes"]:
            path = self.need(GOLDEN_ROOT / scene["png"])
            with Image.open(path) as image:
                image.load()
                self.assertEqual(image.mode, "RGB")
                self.assertEqual(image.size, (360, 360))
                self.assertEqual(image.info, {})
            self.assertEqual(scene["rawByteCount"], RAW_BYTES)
            self.assertEqual(scene["pngSha256"], sha(path.read_bytes()))

    def test_every_scene_replays_to_literal_raw_and_png_hashes(self):
        prerequisites = [TOOL, HELPER, MANIFEST]
        prerequisites.extend(GOLDEN_ROOT / name for name in PNG_NAMES)
        missing = False
        for path in prerequisites:
            with self.subTest(path=str(path)):
                exists = path.is_file()
                self.assertTrue(exists, "missing exact golden prerequisite")
                missing = missing or not exists
        if not missing:
            result = self.run_tool("--check")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if missing:
            return
        manifest = self.manifest()
        actual = {
            scene["png"]: {
                "raw": scene["rawSha256"],
                "png": sha((GOLDEN_ROOT / scene["png"]).read_bytes()),
            }
            for scene in manifest["scenes"]
        }
        self.assertEqual(actual, APPROVED_GOLDEN_DIGESTS)

    def test_golden_writer_is_byte_identical_across_two_clean_runs(self):
        result = self.run_tool("--check-reproducible")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_zero_fifty_ninety_nine_and_hundred_have_literal_pixel_probes(self):
        for model, probes in LITERAL_PROBES.items():
            with self.subTest(model=model):
                image = self.image(*model)
                for x, y, expected in probes:
                    self.assertEqual(rgb565(image.getpixel((x, y))), expected)

    def test_day_and_week_change_independently_without_moving_fixed_assets(self):
        day_zero = self.image(0, 1)
        week_zero = self.image(1, 0)
        self.assertEqual(rgb565(day_zero.getpixel((175, 14))), 0xBE18)
        self.assertEqual(rgb565(day_zero.getpixel((175, 13))), 0x738E)
        self.assertEqual(rgb565(day_zero.getpixel((175, 44))), 0x0000)
        self.assertEqual(rgb565(day_zero.getpixel((175, 43))), 0x8410)
        self.assertEqual(rgb565(week_zero.getpixel((175, 14))), 0x0000)
        self.assertEqual(rgb565(week_zero.getpixel((175, 13))), 0x630C)
        self.assertEqual(rgb565(week_zero.getpixel((175, 44))), 0xFFFF)
        self.assertEqual(rgb565(week_zero.getpixel((175, 43))), 0x94B2)

        baseline = self.image(0, 0)
        devin = tuple(baseline.crop((132, 118, 228, 214)).get_flattened_data())
        credit = tuple(baseline.crop((134, 226, 226, 254)).get_flattened_data())
        for day in VALUES:
            for week in VALUES:
                image = self.image(day, week)
                self.assertEqual(
                    tuple(image.crop((132, 118, 228, 214)).get_flattened_data()), devin)
                self.assertEqual(
                    tuple(image.crop((134, 226, 226, 254)).get_flattened_data()), credit)

    def test_one_percent_and_hundred_percent_pin_round_caps_and_seam(self):
        one = self.image(1, 1)
        for x, y, expected in LITERAL_PROBES[(1, 1)][:4]:
            self.assertEqual(rgb565(one.getpixel((x, y))), expected)
        full = self.image(100, 100)
        for x, y, expected in LITERAL_PROBES[(100, 100)]:
            self.assertEqual(rgb565(full.getpixel((x, y))), expected)
        near = self.image(99, 99)
        for x, y, expected in LITERAL_PROBES[(99, 99)]:
            self.assertEqual(rgb565(near.getpixel((x, y))), expected)

    def test_all_pixels_outside_the_physical_circle_are_black(self):
        limit = (180 * 4) ** 2
        outside = []
        for y in range(360):
            for x in range(360):
                distances = [
                    ((x - 180) * 4 + ox) ** 2 +
                    ((y - 180) * 4 + oy) ** 2
                    for ox, oy in ((1, 1), (3, 1), (1, 3), (3, 3))
                ]
                if min(distances) > limit:
                    outside.append((x, y))
        self.assertGreater(len(outside), 1)
        for day, week in ((0, 0), (1, 1), (50, 50), (99, 99), (100, 100)):
            image = self.image(day, week)
            with self.subTest(day=day, week=week):
                self.assertTrue(
                    all(image.getpixel(point) == (0, 0, 0) for point in outside))

    def test_asset_boxes_have_exact_centers_and_no_playhead_motion(self):
        self.assertEqual((132 + 96 // 2, 118 + 96 // 2), (180, 166))
        self.assertEqual((134 + 92 // 2, 226 + 28 // 2), (180, 240))
        self.assertEqual((171 + 18 // 2, 11 + 18 // 2), (180, 20))
        self.assertEqual((171 + 18 // 2, 41 + 18 // 2), (180, 50))
        for value in (1, 50, 100):
            image = self.image(value, value)
            self.assertEqual(rgb565(image.getpixel((175, 14))), 0x0000)
            self.assertEqual(rgb565(image.getpixel((175, 13))), 0x630C)
            self.assertEqual(rgb565(image.getpixel((175, 44))), 0x0000)
            self.assertEqual(rgb565(image.getpixel((175, 43))), 0x8410)
            self.assertEqual(rgb565(image.getpixel((150, 119))), 0xFFFF)
            self.assertEqual(rgb565(image.getpixel((141, 227))), 0xFFFF)

    def test_production_sources_have_no_target_io_float_heap_or_full_frame(self):
        renderer = self.need(
            ROOT / "firmware/overlay/SDK/apps/watch/e87/e87_renderer.c"
        ).read_text()

        physical_predicate = "e87_sample_in_physical_circle_q2"
        self.assertEqual(
            len(re.findall(
                r"static\s+bool\s+" + physical_predicate + r"\s*\(",
                renderer,
            )),
            1,
        )
        track_path = re.search(
            r"static bool e87_sample_in_track_q2\(.*?\n\}\n\n"
            r"static bool e87_sample_in_cap_q16",
            renderer,
            re.DOTALL,
        )
        active_path = re.search(
            r"static bool e87_sample_in_active_q2\(.*?\n\}\n\n"
            r"static uint8_t e87_coverage_alpha",
            renderer,
            re.DOTALL,
        )
        self.assertIsNotNone(track_path)
        self.assertIsNotNone(active_path)
        self.assertEqual(
            track_path.group(0).count(physical_predicate + "("),
            1,
            "common track path must call the physical-circle predicate once",
        )
        self.assertEqual(
            active_path.group(0).count(physical_predicate + "("),
            1,
            "active path must call the physical-circle predicate once",
        )
        self.assertEqual(renderer.count(physical_predicate + "("), 3)

        manifest = self.manifest()
        self.assertEqual(manifest["runtimeReference"], RUNTIME)
        self.assertEqual(manifest["pillow"], {
            "distribution": "Pillow",
            "version": "12.2.0",
            "wheelSha256": "e74473c875d78b8e9d5da2a70f7099549f9eb37ded4e2f6a463e60125bccd176",
        })
        self.assertEqual(manifest["compiler"], {
            "byteLength": 1301496,
            "executable": CC,
            "sha256": CC_SHA,
        })
        self.assertEqual(manifest["linker"], {
            "byteLength": 1336592,
            "probeArguments": list(LINKER_PROBE),
            "probeStdout": "/usr/bin/ld.bfd\n",
            "resolved": "/usr/bin/x86_64-linux-gnu-ld.bfd",
            "sha256": LD_SHA,
        })
        self.assertEqual(manifest["compileArguments"], list(COMPILE_ARGUMENTS))
        self.assertEqual(set(manifest["inputs"]), set(INPUT_PATHS) | {
            "firmware/tools/render-goldens.py"
        })
        for path, digest in manifest["inputs"].items():
            self.assertEqual(sha(self.need(ROOT / path).read_bytes()), digest)

        generated = self.need(
            ROOT / "firmware/generated/e87_assets.c"
        ).read_text()
        includes = re.findall(r'^\s*#\s*include\s*([<"][^>"]+[>"])',
                              renderer, re.MULTILINE)
        self.assertEqual(includes, [
            '"e87/e87_renderer.h"',
            '"e87_assets.h"',
            "<stdbool.h>",
            "<stddef.h>",
            "<stdint.h>",
        ])
        for token in (
            "dbi.h", "lcd_drive.h", "lcd_draw", "lcd_wait_busy",
            "lcd_draw_set_callback", "uires", "lvgl", "malloc", "calloc",
            "realloc", "free", "E87_HOST_TEST",
        ):
            self.assertNotIn(token, renderer)
            self.assertNotIn(token, generated)
        for pattern in (
            r"\bfloat\b", r"\bdouble\b", r"\bsin\s*\(",
            r"\bcos\s*\(", r"\batan\s*\(", r"\bsqrt\s*\(",
            r"\bpow\s*\(", r"\be87_render_strip\b",
            r"\be87_render_frame\b",
        ):
            self.assertIsNone(re.search(pattern, renderer))
            self.assertIsNone(re.search(pattern, generated))


        self.assertNotIn("E87_DISPLAY_WIDTH * E87_DISPLAY_HEIGHT", renderer)
        self.assertNotIn("[360 * 360]", renderer)
        self.assertNotIn("[368 * 368]", renderer)


if __name__ == "__main__":
    unittest.main(verbosity=2)
