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
RAW_BYTES = 368 * 368 * 2
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
APPROVED_GOLDEN_MANIFEST_SHA256 = "d30d57d34d639d353c634b9587b1e822639b1025ed9043508aae37c673376618"
APPROVED_GOLDEN_DIGESTS = {
    "face-day-000-week-000.png": {"raw": "c299efa8ae7839933744ce5e49a063eb2f955eaf6ed3707f664328a2259cd9bb", "png": "256f9a7c300a819cc2b7018576aa0a653ec475dc52a0628d2e9f6d56d1e9bcb9"},
    "face-day-000-week-001.png": {"raw": "c8d612c8f43fd3fefc72d9b2792f2b185243a5717d1ab45967322fd5361ec74f", "png": "0bf558f007d9e83b89c4965686aacedb7e8b0e61e4729df6dbb97aa1d2c0a8e1"},
    "face-day-000-week-050.png": {"raw": "371f39562a4ae5170b358fc0600b844fbcbdb7648a61cd4461708e45f14d1a16", "png": "82bd10791fd13f83ce602edff007c393f387cb8cb8edd9e57758a63cbdb1f140"},
    "face-day-000-week-099.png": {"raw": "26873a6f5a9835c800e05b517dc15c3bc7691f6acff297bbe079a6fd9391737a", "png": "1d1222b5e8ae75b3179da77a547034adea9a925006204a5378f6c934cb869db9"},
    "face-day-000-week-100.png": {"raw": "f0b07b043ffa96f23cadc58ecb01351180a38ba9e955d67dd1b2bb19914e49f6", "png": "7f57485f7795ec57a97b0258b69893b1a206afa6f3453f3637b159e47d2336ca"},
    "face-day-001-week-000.png": {"raw": "09f69f9db8f19a40f7a5951cf42c03d7b4452de11bc2fa32d26b7c736a4db433", "png": "b92414d6d15927870a68264c9aa707a72e93cdca6c1bde886738cf1c31ab3f2e"},
    "face-day-001-week-001.png": {"raw": "5c1cb2d474706479368b46110cd155ec84fe46c9b3a8c89b2e0a7f6259034430", "png": "0e16276d4892fb1bd9958daf8baa8d7200d32903a8d7d65d0aa7f9573b000db6"},
    "face-day-001-week-050.png": {"raw": "111e81d2791e4f02db124eabbc7e5e68281e3003dbf73874d3b1f71b73c2a642", "png": "c1d76ca825021bed3ee81f046d8c0b8ceb9a2cbb79fc7eafc7d606ad4ffd6ede"},
    "face-day-001-week-099.png": {"raw": "b84d54746d111c725346c61a7b9ae3854e1aa6ad9659d1809f99f94db93b250f", "png": "f1a3b71eaa0f705968a9f2327ef4c456fbfc36d517081c3bbfb2f427acb48b03"},
    "face-day-001-week-100.png": {"raw": "a421838b55f739d22141ca16f2fa9ef081fa8daafd1b970f205e2974088eac0d", "png": "18795a1b909f18482a7e6a27023ee2b9ee72d9213c6e5a063a6be94a51666cbb"},
    "face-day-050-week-000.png": {"raw": "798ac70cb354ca3607296cd31a475486b224bc60528bf054384437e9a61333b0", "png": "c725368e8c637c3edfd0750bc84b7614f661442bd53acfe25044c3686e6d6b68"},
    "face-day-050-week-001.png": {"raw": "8c84bb323acf30a298b4ece04e82aa85579651a71ec2178a387f901b06b6079a", "png": "830bc69933eb45aec41afa8728cfb7567e301e158a5843f9628cdc354e8db307"},
    "face-day-050-week-050.png": {"raw": "39537fe7211ffa0262117f5f7edba63d014a4796452903d7c05c0cd0cb2ba365", "png": "ac89e673fd92fe38933ac9a622eee9133278e18d10cd35d83f0e5f14e4311f73"},
    "face-day-050-week-099.png": {"raw": "3430fe2accf7d97e355e67f408975e1fb930198fdf85bd152cabe7a06481844f", "png": "5d091ee1eb52c1fcb9796635c43a3996f0b47e1971d126143b92d4fc35c2098f"},
    "face-day-050-week-100.png": {"raw": "e9b3999538825914b1306b19b1c5e2f9504ced798dfe79e30cd36394a10644cb", "png": "f1ebdebbf58cde7b44830235f49d3cfae02d9fea06dc3d62b9ca841bebb4a13a"},
    "face-day-099-week-000.png": {"raw": "7eca16eee2c9e47d8f31c2f0013349995fe9918999740821c5a6f8128ee70bf9", "png": "462c764a7ce9e336fb0ca165fb1431d604030c3b523373228f288d3f75b847ff"},
    "face-day-099-week-001.png": {"raw": "ccd483a44cd1e19ef8734b672bae21437eba308ceb6296c9036a2b2aa40f069c", "png": "749ea6cb6ab82a59b95070d412853ef0a217c65d42206aeafa7e8bfcbae0f53e"},
    "face-day-099-week-050.png": {"raw": "a551c4ad99c62988b6e4b86c849619468d4eaaa4e1c7fb3db83cc64945124778", "png": "999a7ffab23eac54e4fa97b1274b162b01b57fab45de51ff1aa1b243bb4dc47b"},
    "face-day-099-week-099.png": {"raw": "7a0e828e730da7850298d87094fec6e89f91f134481ac37a1fc90fc2814f0f37", "png": "b914a0016857a42aa605f02241c3cf91f1e505c4eeb3bb7d2f58490d3f7f7988"},
    "face-day-099-week-100.png": {"raw": "d62d26d81c0a7cd24cb9979073ad7478b9e2df157ed20d517413b6d319624142", "png": "9348d71c7961e2ceef738cfc4a64ada75396ff62144bae6230186d0fb58321ae"},
    "face-day-100-week-000.png": {"raw": "04a1864a1ea7f983e5b192ba4aeb774bcf88278cbfc3a87cbcba2d5dd6ab3fa5", "png": "7e64af9f1573833a4279221f7236089444173743143356a721fa6d6abf3dcbe0"},
    "face-day-100-week-001.png": {"raw": "d8d9b13b7354a31f89a3d92478b2c3a1f60092f1beeee11a84211cdddb893898", "png": "4882b3929a0aa95e9f98b8315a78f65004f29ccb0eb24d46bbfb24bf0c02eb3f"},
    "face-day-100-week-050.png": {"raw": "b2e25af250d548de81bcb7eb94bdf80b55997ac8b0fdaca6b1e3564ed72781e8", "png": "a30d2c048c32406854bf3c96b4836a59f6b8e24fd5e97bdc37a901dea3809787"},
    "face-day-100-week-099.png": {"raw": "b5bbc6cf50a2594650fdf3a0442e3a1359fa8c779a7e95834c367bc9e4c387ae", "png": "ee219ebf7ebdc4ad55f2b946209795011d9efa498962391cbc67cc1f68cbb059"},
    "face-day-100-week-100.png": {"raw": "3007fbc2b895caf98ae980816027c6519252da7662fbe6fce3f4c0024085d1b1", "png": "e9d0647571303893f242611bea44d8a330caf8904bddc2196b2dd6816b25bc9f"},
}

LITERAL_PROBES = {
    (0, 0): (
        (344, 184, 0x2104),
        (314, 184, 0x2965),
        (179, 18, 0xBE18),
        (179, 48, 0xFFFF),
        (168, 13, 0x1082),
        (169, 43, 0x0861),
        (154, 123, 0xFFFF),
        (145, 231, 0xFFFF),
        (0, 0, 0x0000),
    ),
    (1, 1): (
        (184, 13, 0xBE18),
        (175, 24, 0xBE18),
        (203, 24, 0xBE18),
        (175, 54, 0xFFFF),
        (201, 54, 0xFFFF),
        (179, 17, 0x630C),
        (179, 47, 0x8410),
    ),
    (50, 50): (
        (344, 184, 0xBE18),
        (24, 184, 0x2104),
        (314, 184, 0xFFFF),
        (54, 184, 0x2965),
    ),
    (99, 99): (
        (184, 14, 0xBE18),
        (174, 14, 0xBE18),
        (184, 44, 0xFFFF),
        (176, 44, 0xFFFF),
    ),
    (100, 100): (
        (174, 24, 0xBE18),
        (194, 24, 0xBE18),
        (174, 54, 0xFFFF),
        (194, 54, 0xFFFF),
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

    def test_every_png_is_368_square_rgb_and_manifest_is_canonical(self):
        manifest = self.manifest()
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(manifest["dimensions"], {"height": 368, "width": 368})
        self.assertEqual(manifest["pixelFormat"], "RGB565-word-little-endian")
        self.assertEqual(manifest["fixedCreditCents"], 1727)
        for scene in manifest["scenes"]:
            path = self.need(GOLDEN_ROOT / scene["png"])
            with Image.open(path) as image:
                image.load()
                self.assertEqual(image.mode, "RGB")
                self.assertEqual(image.size, (368, 368))
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
        self.assertEqual(rgb565(day_zero.getpixel((179, 18))), 0xBE18)
        self.assertEqual(rgb565(day_zero.getpixel((179, 17))), 0x738E)
        self.assertEqual(rgb565(day_zero.getpixel((179, 48))), 0x0000)
        self.assertEqual(rgb565(day_zero.getpixel((179, 47))), 0x8410)
        self.assertEqual(rgb565(week_zero.getpixel((179, 18))), 0x0000)
        self.assertEqual(rgb565(week_zero.getpixel((179, 17))), 0x630C)
        self.assertEqual(rgb565(week_zero.getpixel((179, 48))), 0xFFFF)
        self.assertEqual(rgb565(week_zero.getpixel((179, 47))), 0x94B2)

        baseline = self.image(0, 0)
        devin = tuple(baseline.crop((136, 122, 232, 218)).get_flattened_data())
        credit = tuple(baseline.crop((138, 230, 230, 258)).get_flattened_data())
        for day in VALUES:
            for week in VALUES:
                image = self.image(day, week)
                self.assertEqual(
                    tuple(image.crop((136, 122, 232, 218)).get_flattened_data()), devin)
                self.assertEqual(
                    tuple(image.crop((138, 230, 230, 258)).get_flattened_data()), credit)

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
        for y in range(368):
            for x in range(368):
                distances = [
                    ((x - 184) * 4 + ox) ** 2 +
                    ((y - 184) * 4 + oy) ** 2
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
        self.assertEqual((136 + 96 // 2, 122 + 96 // 2), (184, 170))
        self.assertEqual((138 + 92 // 2, 230 + 28 // 2), (184, 244))
        self.assertEqual((175 + 18 // 2, 15 + 18 // 2), (184, 24))
        self.assertEqual((175 + 18 // 2, 45 + 18 // 2), (184, 54))
        for value in (1, 50, 100):
            image = self.image(value, value)
            self.assertEqual(rgb565(image.getpixel((179, 18))), 0x0000)
            self.assertEqual(rgb565(image.getpixel((179, 17))), 0x630C)
            self.assertEqual(rgb565(image.getpixel((179, 48))), 0x0000)
            self.assertEqual(rgb565(image.getpixel((179, 47))), 0x8410)
            self.assertEqual(rgb565(image.getpixel((154, 123))), 0xFFFF)
            self.assertEqual(rgb565(image.getpixel((145, 231))), 0xFFFF)

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
        self.assertNotIn("[368 * 368]", renderer)


if __name__ == "__main__":
    unittest.main(verbosity=2)
