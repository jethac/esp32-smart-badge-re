#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from .test_e87_embed import ReleaseFixture, ROLE_NAMES


PROJECT = Path(__file__).resolve().parents[2]
GRADLE = PROJECT / "gradlew"
VERIFY_APK = PROJECT / "scripts" / "verify-apk.py"


class GradleEmbedFunctionalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        required = ("JAVA_HOME", "ANDROID_HOME")
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise unittest.SkipTest("missing Android build environment: " + ", ".join(missing))

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.fixture = ReleaseFixture(Path(self.temp.name) / "release")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def gradle(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", os.fspath(GRADLE), "--offline", "--no-daemon", *arguments],
            cwd=PROJECT,
            env=os.environ.copy(), text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, check=False, timeout=240,
        )

    def apk_entries(self, variant: str) -> tuple[Path, set[str]]:
        apk = PROJECT / "app" / "build" / "outputs" / "apk" / variant / f"app-{variant}.apk"
        self.assertTrue(apk.is_file(), apk)
        with zipfile.ZipFile(apk) as archive:
            return apk, set(archive.namelist())

    def test_debug_is_firmware_free_and_lab_requires_then_embeds_exact_handoff(self) -> None:
        debug = self.gradle("clean", "assembleDebug")
        self.assertEqual(0, debug.returncode, debug.stdout)
        _, debug_entries = self.apk_entries("debug")
        self.assertFalse(any(name.startswith("assets/e87/") for name in debug_entries))

        missing = self.gradle("assembleLabQualified")
        self.assertNotEqual(0, missing.returncode, missing.stdout)
        self.assertIn("e87FirmwareRelease", missing.stdout)

        qualified = self.gradle(
            f"-Pe87FirmwareRelease={self.fixture.root}",
            "clean", "embedE87Firmware", "testLabQualifiedUnitTest",
            "lintLabQualified", "assembleLabQualified")
        self.assertEqual(0, qualified.returncode, qualified.stdout)
        apk, entries = self.apk_entries("labQualified")
        root = self.fixture.receipt["releaseRoot"]
        expected = {"assets/e87/default-release.json"}
        expected.update(f"assets/e87/{root}/{name}" for _, name in ROLE_NAMES)
        self.assertEqual(expected,
                         {name for name in entries if name.startswith("assets/e87/")})
        with zipfile.ZipFile(apk) as archive:
            self.assertEqual(
                (self.fixture.root / "e87-android-embed.json").read_bytes(),
                archive.read("assets/e87/default-release.json"),
            )
            for _, name in ROLE_NAMES:
                self.assertEqual((self.fixture.root / name).read_bytes(),
                                 archive.read(f"assets/e87/{root}/{name}"))
            parsed = json.loads(archive.read("assets/e87/default-release.json"))
            self.assertEqual(self.fixture.receipt["buildId"], parsed["buildId"])

        build_tools = Path(os.environ["ANDROID_HOME"]) / "build-tools" / "34.0.0"
        audit = subprocess.run(
            [
                "/usr/bin/python3.11", os.fspath(VERIFY_APK),
                "--apk", os.fspath(apk.resolve()),
                "--release", os.fspath(self.fixture.root),
                "--aapt", os.fspath((build_tools / "aapt").resolve()),
                "--dexdump", os.fspath((build_tools / "dexdump").resolve()),
            ],
            cwd=PROJECT, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False, timeout=120,
        )
        self.assertEqual(0, audit.returncode, audit.stdout + audit.stderr)

        debug_with_property = self.gradle(
            f"-Pe87FirmwareRelease={self.fixture.root}", "assembleDebug")
        self.assertEqual(0, debug_with_property.returncode, debug_with_property.stdout)
        _, debug_entries = self.apk_entries("debug")
        self.assertFalse(any(name.startswith("assets/e87/") for name in debug_entries))

    def test_invalid_changed_handoff_cannot_reuse_stale_generated_assets(self) -> None:
        valid = self.gradle(f"-Pe87FirmwareRelease={self.fixture.root}",
                            "embedE87Firmware")
        self.assertEqual(0, valid.returncode, valid.stdout)
        (self.fixture.root / "extra.bin").write_bytes(b"not allowed")

        invalid = self.gradle(f"-Pe87FirmwareRelease={self.fixture.root}",
                              "assembleLabQualified")

        self.assertNotEqual(0, invalid.returncode, invalid.stdout)
        self.assertIn("allowlist", invalid.stdout)


if __name__ == "__main__":
    unittest.main()
