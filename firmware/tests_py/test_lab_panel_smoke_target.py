#!/usr/bin/env python3
"""Static target contract for the deliberately limited panel smoke image."""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import re
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
APP = REPO_ROOT / "firmware/overlay/SDK/apps/watch/e87/e87_app.c"
PANEL = REPO_ROOT / "firmware/overlay/SDK/apps/watch/e87/e87_panel_jd9855.c"
PROFILE = (
    REPO_ROOT / "firmware/board-profiles/E87-1542-LAB-PANEL-SMOKE-H.json"
)
PATCH = (
    REPO_ROOT
    / "firmware/patches/lab-panel-smoke/0001-e87-lab-panel-smoke.patch"
)
NOTES = REPO_ROOT / "firmware/LAB-PANEL-SMOKE.md"


class LabPanelSmokeTargetTests(unittest.TestCase):
    def test_app_runs_only_the_timed_local_smoke_and_services_watchdog(self) -> None:
        app = APP.read_text(encoding="utf-8")

        for required in (
            "e87_panel_jd9855_sdk_io()",
            "e87_lab_smoke_start(",
            "wdt_clear();",
            "e87_lab_smoke_step(",
        ):
            self.assertIn(required, app)
        self.assertLess(
            app.find("e87_panel_jd9855_sdk_io()"),
            app.find("e87_lab_smoke_start("),
        )
        self.assertLess(app.find("wdt_clear();"), app.find("e87_lab_smoke_step("))
        self.assertIn("sys_timer_get_ms()", app)
        self.assertIn("os_time_dly(1);", app)
        for forbidden in (
            "btstack_init",
            "app_ble_init",
            "rcsp_init",
            "charge_init",
            "set_charge_event_flag",
            "update_mode_api_v2",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, app)

    def test_recovered_two_buffer_evidence_is_distinct_from_lab_serial_runtime(self) -> None:
        panel = PANEL.read_text(encoding="utf-8")

        self.assertRegex(panel, r"\.recovered_descriptor_buffer_count\s*=\s*2U")
        self.assertRegex(panel, r"\.application_transfer_buffer_count\s*=\s*1U")
        runtime = re.search(
            r"static struct dbi_param e87_lab_smoke_dbi_param = \{(?P<body>.*?)\n\};",
            panel,
            re.S,
        )
        self.assertIsNotNone(runtime)
        self.assertRegex(runtime.group("body"), r"\.buffer_num\s*=\s*1,")
        self.assertRegex(runtime.group("body"), r"\.buffer_size\s*=\s*0x5460,")
        self.assertIn("LAB_ONLY", panel)

    def test_profile_and_delta_patch_close_the_lab_only_scope(self) -> None:
        for path in (PROFILE, PATCH, NOTES):
            self.assertTrue(path.is_file(), path)

        profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        self.assertEqual(profile["profileId"], "E87-1542-LAB-PANEL-SMOKE-H")
        self.assertEqual(profile["status"], "LAB_ONLY")
        self.assertEqual(profile["versions"]["transportQix"], "11.1.0.4")
        self.assertEqual(profile["versions"]["firmwareBuildInfoSemver"], "0.1.0")
        self.assertTrue(profile["versions"]["domainsIndependent"])
        self.assertEqual(profile["versions"]["nextFullMinimum"], "11.1.0.5")
        self.assertEqual(
            profile["behavior"],
            {
                "initialScreen": "PAIR_ME_NOW",
                "faceAfterMs": 3000,
                "dayPercent": 67,
                "weekPercent": 42,
                "creditCents": 1727,
            },
        )
        self.assertEqual(
            profile["capabilities"],
            {
                "panel": True,
                "localRendering": True,
                "bluetooth": False,
                "rcsp": False,
                "charger": False,
                "update": False,
                "recoveryClaim": False,
            },
        )
        self.assertEqual(
            profile["panel"]["recoveredDescriptorBufferCount"], 2
        )
        self.assertEqual(profile["panel"]["runtimeSerialBufferCount"], 1)
        self.assertEqual(profile["panel"]["runtimeSerialBufferBytes"], 0x5460)
        self.assertEqual(profile["panel"]["model1542Status"], "INFERRED")

        patch = PATCH.read_text(encoding="utf-8")
        targets = set(re.findall(r"^diff --git a/(\S+) b/\1$", patch, re.M))
        self.assertEqual(
            targets,
            {
                "SDK/apps/watch/app_main.c",
                "SDK/build/Makefile.mk",
                "SDK/cpu/br35/sdk_ld.c",
            },
        )
        for source in (
            "apps/watch/log_config/app_config.c",
            "apps/watch/e87/e87_lab_smoke.c",
            "apps/watch/e87/e87_lcd_stream.c",
            "apps/watch/e87/e87_panel_jd9855.c",
            "apps/watch/e87/e87_renderer.c",
            "apps/watch/e87/e87_transient_renderer.c",
            "apps/watch/e87/e87_assets.c",
            "apps/watch/e87/e87_transient_assets.c",
            "cpu/br35/power/power_gate.c",
        ):
            self.assertIn(source, patch)
        self.assertIn("cpu/br35/liba/gpu.a", patch)
        self.assertRegex(
            patch,
            r'\{"app_core",\s*1,\s*0,\s*4096,\s*128\s*\}',
        )
        self.assertIn("KEEP(*(.e87_lcd_buffer))", patch)
        self.assertIn("SIZEOF(.e87_lcd_buffer) == 0x5460", patch)

        expected_generated = {
            "firmware/generated/e87_assets.c": "SDK/apps/watch/e87/e87_assets.c",
            "firmware/generated/e87_assets.h": "SDK/apps/watch/include/e87_assets.h",
            "firmware/generated/e87_transient_assets.c": "SDK/apps/watch/e87/e87_transient_assets.c",
            "firmware/generated/e87_transient_assets.h": "SDK/apps/watch/include/e87_transient_assets.h",
        }
        mappings = profile["generatedOverlayMappings"]
        self.assertEqual(
            {record["source"]: record["destination"] for record in mappings},
            expected_generated,
        )
        for record in mappings:
            source = REPO_ROOT / record["source"]
            self.assertTrue(source.is_file(), source)
            self.assertEqual(
                hashlib.sha256(source.read_bytes()).hexdigest(),
                record["sha256"],
            )
        self.assertEqual(profile["boot"]["appCoreStackBytes"], 4096)
        self.assertEqual(
            profile["targetClosure"]["additionalSources"],
            [
                "apps/watch/log_config/app_config.c",
                "apps/watch/e87/e87_lab_smoke.c",
                "apps/watch/e87/e87_lcd_stream.c",
                "apps/watch/e87/e87_panel_jd9855.c",
                "apps/watch/e87/e87_renderer.c",
                "apps/watch/e87/e87_transient_renderer.c",
                "apps/watch/e87/e87_assets.c",
                "apps/watch/e87/e87_transient_assets.c",
                "cpu/br35/power/power_gate.c",
            ],
        )
        self.assertEqual(
            profile["targetClosure"]["additionalArchives"],
            [
                {
                    "path": "cpu/br35/liba/gpu.a",
                    "sha256": "71dcf8be68f79760cb1cbc612abc58cb17019ec95ec2cde33f62a1f8937ecf32",
                }
            ],
        )
        self.assertEqual(
            profile["targetClosure"]["requiredResolution"],
            [
                {
                    "provider": "objs/apps/watch/log_config/app_config.c.o",
                    "requester": "cpu/br35/liba/gpu.a(dbi.c.o)",
                    "symbol": "log_tag_const_d_UI",
                },
                {
                    "provider": "objs/apps/watch/log_config/app_config.c.o",
                    "requester": "cpu/br35/liba/gpu.a(dbi_mcu.c.o)",
                    "symbol": "log_tag_const_i_UI",
                },
            ],
        )

        notes = NOTES.read_text(encoding="utf-8")
        self.assertIn("11.1.0.4", notes)
        self.assertIn("0.1.0", notes)
        self.assertIn("11.1.0.5", notes)
        self.assertIn("does not claim a recovery route", notes)


if __name__ == "__main__":
    unittest.main()
