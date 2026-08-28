#!/usr/bin/env python3
"""Independent golden and production-boundary oracles for transient UI."""
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
TOOL = ROOT / "firmware/tools/render-transient-goldens.py"
HELPER = ROOT / "firmware/host/render_transient_renderer.c"
RENDERER = ROOT / "firmware/overlay/SDK/apps/watch/e87/e87_transient_renderer.c"
UI_HEADER = ROOT / "firmware/overlay/SDK/apps/watch/include/e87/e87_ui.h"
SPEC = ROOT / "firmware/assets/transient-ui.json"
GOLDEN_ROOT = ROOT / "firmware/generated/transient-goldens"
MANIFEST = GOLDEN_ROOT / "transient-goldens-manifest.json"
CC = "/usr/bin/x86_64-linux-gnu-gcc-12"
CC_SHA = "75e997ec62297a6484f491bae28ab0ccb489daba23e398fd10fe68e9e6f0def8"
RAW_BYTES = 360 * 360 * 2
APPROVED_MANIFEST_SHA256 = \
    "b7bdbe0258b9e420dcbbe48df4b7935635757482f6874df0c95e1197f6a10cff"
SCENES = (
    "unpaired",
    "waiting",
    "pairing-060",
    "pairing-001",
    "warning-003",
    "warning-002",
    "warning-001",
    "battery-face-000",
    "battery-face-001",
    "battery-face-050",
    "battery-face-099",
    "battery-face-100",
    "battery-face-050-charging",
    "battery-face-100-full",
    "battery-stale-037",
    "battery-fault",
    "maintenance-release-valid-050",
    "maintenance-waiting-valid-050",
    "maintenance-ready-valid-050",
    "maintenance-update-000",
    "maintenance-update-001",
    "maintenance-update-050",
    "maintenance-update-099",
    "maintenance-update-100",
    "maintenance-error",
    "maintenance-stale-037",
    "maintenance-fault",
    "recovery-release-valid-050",
)
PNG_NAMES = tuple(name + ".png" for name in SCENES)
EXACT_STRINGS = (
    "PAIR ME NOW",
    "HOLD BUTTON 1",
    "WAITING FOR PHONE",
    "PAIRING",
    "KEEP HOLDING",
    "FOR UPDATE",
    "READY TO UPDATE",
    "RELEASE BUTTON",
    "PHONE READY",
    "UPDATE",
    "UPDATE ERROR",
    "BATTERY OLD",
    "BATTERY ERROR",
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) +
            "\n").encode()


class TransientGoldenTests(unittest.TestCase):
    maxDiff = None

    def need(self, path: Path) -> Path:
        self.assertTrue(path.is_file(), "missing exact golden prerequisite: " +
                        str(path))
        return path

    def manifest(self) -> dict:
        raw = self.need(MANIFEST).read_bytes()
        value = json.loads(raw)
        self.assertEqual(sha(raw), APPROVED_MANIFEST_SHA256)
        self.assertEqual(raw, canonical(value))
        return value

    def image(self, name: str) -> Image.Image:
        image = Image.open(self.need(GOLDEN_ROOT / (name + ".png")))
        image.load()
        self.addCleanup(image.close)
        return image

    def run_tool(self, mode: str) -> subprocess.CompletedProcess[str]:
        self.need(TOOL)
        return subprocess.run(
            [sys.executable, str(TOOL), mode, "--cc", CC,
             "--require-compiler-sha256", CC_SHA],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

    def test_golden_set_is_exact_and_panel_off_has_no_image(self):
        manifest = self.manifest()
        self.assertEqual(
            tuple(scene["name"] for scene in manifest["scenes"]), SCENES)
        self.assertEqual(
            tuple(scene["png"] for scene in manifest["scenes"]), PNG_NAMES)
        actual = tuple(sorted(path.name for path in GOLDEN_ROOT.glob("*.png")))
        self.assertEqual(actual, tuple(sorted(PNG_NAMES)))
        self.assertNotIn("panel-off.png", actual)
        self.assertEqual(len(manifest["scenes"]), 28)

    def test_pngs_are_exact_360_square_rgb_with_canonical_hash_manifest(self):
        manifest = self.manifest()
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(manifest["dimensions"], {"height": 360, "width": 360})
        self.assertEqual(manifest["pixelFormat"], "RGB565-word-little-endian")
        for scene in manifest["scenes"]:
            path = self.need(GOLDEN_ROOT / scene["png"])
            with Image.open(path) as image:
                image.load()
                self.assertEqual(image.mode, "RGB")
                self.assertEqual(image.size, (360, 360))
                self.assertEqual(image.info, {})
            self.assertEqual(scene["rawByteCount"], RAW_BYTES)
            self.assertEqual(scene["pngSha256"], sha(path.read_bytes()))
            self.assertRegex(scene["rawSha256"], r"^[0-9a-f]{64}$")

    def test_every_scene_replays_and_two_clean_runs_are_byte_identical(self):
        for mode in ("--check", "--check-reproducible"):
            result = self.run_tool(mode)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_default_unpaired_and_all_required_modes_are_visibly_nonblack(self):
        digests = set()
        for name in SCENES:
            image = self.image(name)
            colors = image.getcolors(maxcolors=360 * 360)
            self.assertIsNotNone(colors)
            self.assertGreater(len(colors), 1, name)
            self.assertTrue(any(color != (0, 0, 0) for _, color in colors), name)
            digests.add(sha(image.tobytes()))
        self.assertGreaterEqual(len(digests), 26)
        self.assertNotEqual(self.image("unpaired").tobytes(),
                            self.image("waiting").tobytes())
        self.assertNotEqual(self.image("pairing-060").tobytes(),
                            self.image("pairing-001").tobytes())
        self.assertNotEqual(self.image("warning-003").tobytes(),
                            self.image("warning-001").tobytes())

    def test_rgb888_overlay_rounding_and_charge_bolt_have_literal_probes(self):
        dimmed = self.image("battery-face-050")
        self.assertEqual(dimmed.getpixel((340, 180)), (49, 48, 49))
        self.assertEqual(dimmed.getpixel((310, 180)), (66, 65, 66))
        plain = self.image("battery-face-050")
        charging = self.image("battery-face-050-charging")
        self.assertNotEqual(
            self.image("battery-face-100").tobytes(),
            self.image("battery-face-100-full").tobytes())
        self.assertNotEqual(plain.tobytes(), charging.tobytes())
        self.assertGreater(
            sum(1 for y in range(150, 205) for x in range(180, 280)
                if charging.getpixel((x, y)) != plain.getpixel((x, y))),
            20,
        )

    def test_maintenance_edges_and_recovery_share_the_same_renderer(self):
        self.assertEqual(
            self.image("maintenance-release-valid-050").tobytes(),
            self.image("recovery-release-valid-050").tobytes(),
        )
        self.assertNotEqual(self.image("maintenance-update-000").tobytes(),
                            self.image("maintenance-update-001").tobytes())
        self.assertNotEqual(self.image("maintenance-update-099").tobytes(),
                            self.image("maintenance-update-100").tobytes())
        self.assertNotEqual(self.image("maintenance-stale-037").tobytes(),
                            self.image("maintenance-fault").tobytes())

    def test_ui_spec_maps_directly_to_named_renderer_constants(self):
        source = self.need(RENDERER).read_text()
        ui_header = self.need(UI_HEADER).read_text()
        spec = json.loads(self.need(SPEC).read_bytes())

        def value(name: str) -> int:
            match = re.search(r"\b" + re.escape(name) +
                              r"\s*=\s*(-?\d+)\b", source)
            self.assertIsNotNone(match, "missing renderer constant " + name)
            return int(match.group(1))

        layout = spec["layout"]
        expected = {
            "E87_BATTERY_BIG_BASELINE_Y":
                layout["battery"]["bigBaselineY"],
            "E87_BATTERY_STATUS_BASELINE_Y":
                layout["battery"]["statusBaselineY"],
            "E87_BOLT_GAP": layout["battery"]["boltGap"],
            "E87_BOLT_TOP_OFFSET_Y":
                spec["bolt"]["topOffsetFromBaselineY"],
            "E87_MAINTENANCE_BATTERY_BASELINE_Y":
                layout["maintenance"]["batteryBaselineY"],
            "E87_MAINTENANCE_BATTERY_STATUS_BASELINE_Y":
                layout["maintenance"]["batteryStatusBaselineY"],
            "E87_MAINTENANCE_PHASE_BASELINE_Y":
                layout["maintenance"]["phaseBaselineY"],
            "E87_MAINTENANCE_PROGRESS_BASELINE_Y":
                layout["maintenance"]["progressBaselineY"],
            "E87_MAINTENANCE_TITLE_BASELINE_Y":
                layout["maintenance"]["titleBaselineY"],
            "E87_PAIR_ME_HINT_BASELINE_Y":
                layout["pairMe"]["hintBaselineY"],
            "E87_PAIR_ME_PRIMARY_BASELINE_Y":
                layout["pairMe"]["primaryBaselineY"],
            "E87_PAIRING_COUNTDOWN_BASELINE_Y":
                layout["pairing"]["countdownBaselineY"],
            "E87_PAIRING_COUNTDOWN_GLYPH_SCALE":
                layout["pairing"]["countdownGlyphScale"],
            "E87_PAIRING_PRIMARY_BASELINE_Y":
                layout["pairing"]["primaryBaselineY"],
            "E87_UPDATE_WARNING_COUNTDOWN_BASELINE_Y":
                layout["updateWarning"]["countdownBaselineY"],
            "E87_UPDATE_WARNING_COUNTDOWN_GLYPH_SCALE":
                layout["updateWarning"]["countdownGlyphScale"],
            "E87_UPDATE_WARNING_LINE1_BASELINE_Y":
                layout["updateWarning"]["line1BaselineY"],
            "E87_UPDATE_WARNING_LINE2_BASELINE_Y":
                layout["updateWarning"]["line2BaselineY"],
            "E87_WAITING_PRIMARY_BASELINE_Y":
                layout["waiting"]["primaryBaselineY"],
            "E87_BIG_GLYPH_SCALE":
                spec["batteryOverlay"]["bigGlyphScale"],
            "E87_OVERLAY_ALPHA": spec["batteryOverlay"]["blackAlpha"],
        }
        for name, expected_value in expected.items():
            self.assertEqual(value(name), expected_value, name)

        for role, prefix in (("background", "BACKGROUND"),
                             ("primary", "PRIMARY"),
                             ("secondary", "SECONDARY")):
            rgb = bytes.fromhex(spec["palette"][role][1:])
            self.assertEqual(value("E87_" + prefix + "_RED"), rgb[0])
            self.assertEqual(value("E87_" + prefix + "_GREEN"), rgb[1])
            self.assertEqual(value("E87_" + prefix + "_BLUE"), rgb[2])
        duration = spec["batteryOverlay"]["durationMs"]
        self.assertRegex(
            ui_header,
            r"#define E87_BATTERY_OVERLAY_MS UINT32_C\(" +
            str(duration) + r"\)",
        )

    def test_production_renderer_is_integer_strip_only_and_embeds_frozen_text(self):
        source = self.need(RENDERER).read_text()
        for text in EXACT_STRINGS:
            self.assertIn('"' + text + '"', source)
        self.assertIn("E87_OVERLAY_ALPHA = 191", source)
        self.assertRegex(source, r"for \(local_y = 0u; local_y < E87_STRIP_ROWS;")
        self.assertNotRegex(source, r"\b(?:float|double)\b")
        self.assertNotRegex(source, r"\b(?:malloc|calloc|realloc|free)\s*\(")
        self.assertNotRegex(source, r"\b(?:fopen|fread|open|read|printf|sprintf)\s*\(")
        self.assertNotIn("E87_TEST_FRAME_PIXELS", source)
        self.assertIn("struct e87_draw_plan", source)
        entry = source.split("e87_render_transient_strip(", 1)[1]
        self.assertLess(entry.index("e87_build_scene_plan("),
                        entry.index("for (local_y ="))
        pixel_loop = entry.split("for (local_y =", 1)[1]
        self.assertIn("e87_blend_plan_pixel", pixel_loop)
        self.assertNotIn("e87_glyph_for(", pixel_loop)
        self.assertNotIn("e87_text_advance_q3(", pixel_loop)
        self.assertNotIn("e87_blend_centered_text(", pixel_loop)
        self.assertNotRegex(
            source,
            r"\[[^\]]*E87_DISPLAY_WIDTH[^\]]*E87_DISPLAY_HEIGHT[^\]]*\]",
        )
        self.assertNotIn("e87_render_normal_face_strip(\n"
                         "                   &model->metrics", source.split(
                             "if (model->battery_overlay)", 1)[-1])


if __name__ == "__main__":
    unittest.main()
