#!/usr/bin/env python3
"""Tests for the separately versioned LAB_ONLY panel package facade."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "firmware/tools/package-lab-panel-smoke.py"
LOCK = ROOT / "firmware/lab-locks/panel-smoke-packaging.lock.json"
BASE_LOCK = ROOT / "firmware/locks/packaging.lock.json"
PROFILE = ROOT / "firmware/board-profiles/E87-1542-LAB-PANEL-SMOKE-H.json"


def load_tool():
    spec = importlib.util.spec_from_file_location("e87_lab_panel_package", TOOL)
    if spec is None or spec.loader is None:
        raise AssertionError("LAB packager module is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LabPanelPackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = load_tool()

    def test_lab_lock_is_separate_and_monotonic(self) -> None:
        lock = self.tool.load_lab_lock(LOCK, BASE_LOCK)
        stage0 = json.loads(BASE_LOCK.read_text(encoding="ascii"))
        profile = json.loads(PROFILE.read_text(encoding="ascii"))
        self.assertEqual(stage0["qix"]["version"], "11.1.0.3")
        self.assertEqual(lock["qix"]["version"], "11.1.0.4")
        self.assertEqual(profile["versions"]["nextFullMinimum"], "11.1.0.5")
        self.assertEqual(lock["eligibility"], {"labEligible": True, "status": "LAB_ONLY"})
        self.assertEqual(
            lock["stagingOverrides"],
            {
                "flash_params_v3.bin": {
                    "baseSha256": "7E27AE860FFFE505813057AC481AD7AA262574718E6C50E9F4420EED0696B6F7",
                    "generatedSdkRelativePath": "SDK/cpu/br35/tools/flash_params_v3.bin",
                    "sha256": "7069536B81DF3377FDE743084302BF2DAE599BB74E98B427EDB50A35FF39CF69",
                }
            },
        )
        self.assertEqual(
            lock["basePackagingLock"]["sha256"],
            hashlib.sha256(BASE_LOCK.read_bytes()).hexdigest().upper(),
        )

    def test_qix_name_binds_version_and_commit(self) -> None:
        self.assertEqual(
            self.tool.qix_name("0123456789abcdef0123456789abcdef01234567"),
            "E87-11.1.0.4-01234567.qix",
        )
        for invalid in ("0123", "G" * 40, "A" * 40):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.tool.qix_name(invalid)

    def test_app_assembly_accepts_only_the_named_zero_length_optional_sections(self) -> None:
        with tempfile.TemporaryDirectory(prefix="e87-lab-app-") as raw:
            root = Path(raw)
            values = {
                "text.bin": b"TEXT",
                "data.bin": b"DATA",
                "data_code.bin": b"CODE",
                "aec.bin": b"",
                "aac.bin": b"",
                "psr_data_code.bin": b"",
                "d_ram_data.bin": b"",
                "i_ram_data_code.bin": b"",
            }
            for name, data in values.items():
                (root / name).write_bytes(data)
            output = root / "app.bin"
            record = self.tool.assemble_app(root, output)
            self.assertEqual(output.read_bytes(), b"TEXTDATACODE")
            self.assertEqual(record["filename"], "app.bin")
            self.assertEqual(record["size"], 12)
            self.assertEqual([item["filename"] for item in record["sections"]], list(values))

            (root / "text.bin").write_bytes(b"")
            output.unlink()
            with self.assertRaisesRegex(ValueError, "required section"):
                self.tool.assemble_app(root, output)

    def test_source_routes_through_reviewed_native_safety_primitives(self) -> None:
        source = TOOL.read_text(encoding="utf-8")
        for required in (
            "stage_inputs(",
            "resolve_locked_package_tools(",
            "_derive_package_proofs(",
            "wrap_qix(",
            "validate_artifacts(",
            "bootstrap_sdk(",
            "tree_sha256(",
        ):
            self.assertIn(required, source)
        self.assertNotIn("run_stage0_package(", source)
        self.assertNotIn("11.1.0.3", source)
        self.assertNotIn("--generated-sdk-root", source)
        self.assertNotIn("--source-date-epoch", source)
        self.assertIn('argv[verbose_index] = "VERBOSE=1"', source)
        self.assertIn('"DISCONNECTED_AFTER_ALL_OUTPUTS"', source)
        for forbidden in ("-write", "/dev/tty", "COM1", "flash_device"):
            self.assertNotIn(forbidden, source)

    def test_fresh_intake_overlay_projection_is_closed_and_includes_generated_assets(self) -> None:
        profile = json.loads(PROFILE.read_text(encoding="ascii"))
        records = list(self.tool.LAB_OVERLAY_RECORDS)
        self.assertTrue(records)
        self.assertEqual(
            len({record["destination"] for record in records}),
            len(records),
        )
        for record in records:
            self.assertEqual(set(record), {"source", "destination"})
            self.assertTrue((ROOT / record["source"]).is_file(), record["source"])
        generated = {
            record["source"]: record["destination"]
            for record in records
            if record["source"].startswith("firmware/generated/")
        }
        self.assertEqual(
            generated,
            {
                record["source"]: record["destination"]
                for record in profile["generatedOverlayMappings"]
            },
        )
        self.assertEqual(
            set(self.tool.FULL_PATCH_TARGETS),
            {
                "SDK/apps/watch/app_main.c",
                "SDK/apps/watch/board/br35/board_config.h",
                "SDK/apps/watch/include/app_config.h",
                "SDK/build/Makefile.mk",
                "SDK/build/genFileList.c",
                "SDK/cpu/br35/power/power_app.c",
                "SDK/cpu/br35/sdk_ld.c",
                "SDK/interface/system/port/br35/system_lib.ld",
            },
        )
        self.assertEqual(
            set(self.tool.LAB_PATCH_TARGETS),
            {
                "SDK/apps/watch/app_main.c",
                "SDK/build/Makefile.mk",
                "SDK/cpu/br35/sdk_ld.c",
            },
        )
        self.assertEqual(self.tool.NATIVE_DISCONNECTED_EXIT, 245)
        self.assertEqual(self.tool.NATIVE_DISCONNECTED_SUFFIX, b"Device Offline\n")

    def test_repository_identity_rejects_wrong_commit_and_dirty_same_named_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="e87-lab-git-") as raw:
            repository = Path(raw)
            subprocess.run(["/usr/bin/git", "init", "-q", str(repository)], check=True)
            subprocess.run(
                ["/usr/bin/git", "-C", str(repository), "config", "user.name", "E87 Test"],
                check=True,
            )
            subprocess.run(
                ["/usr/bin/git", "-C", str(repository), "config", "user.email", "e87@example.invalid"],
                check=True,
            )
            source = repository / "firmware/overlay/SDK/apps/watch/e87/e87_app.c"
            source.parent.mkdir(parents=True)
            source.write_text("int e87_app_start(void) { return 1; }\n", encoding="ascii")
            asset = repository / "firmware/generated/e87_assets.c"
            asset.parent.mkdir(parents=True)
            asset.write_text("const unsigned e87_asset = 1;\n", encoding="ascii")
            subprocess.run(["/usr/bin/git", "-C", str(repository), "add", "."], check=True)
            subprocess.run(
                ["/usr/bin/git", "-C", str(repository), "commit", "-q", "-m", "fixture"],
                check=True,
            )
            head = subprocess.check_output(
                ["/usr/bin/git", "-C", str(repository), "rev-parse", "HEAD"], text=True
            ).strip()
            identity = self.tool.verify_repository_identity(repository, head)
            self.assertEqual(identity["commit"], head)

            with self.assertRaisesRegex(ValueError, "HEAD"):
                self.tool.verify_repository_identity(repository, "0" * 40)

            source.write_text("int e87_app_start(void) { return 0; }\n", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "clean"):
                self.tool.verify_repository_identity(repository, head)

            source.write_text("int e87_app_start(void) { return 1; }\n", encoding="ascii")
            self.assertEqual(
                self.tool.verify_repository_identity(repository, head)["commit"],
                head,
            )
            asset.write_text("const unsigned e87_asset = 2;\n", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "clean"):
                self.tool.verify_repository_identity(repository, head)


if __name__ == "__main__":
    unittest.main()
