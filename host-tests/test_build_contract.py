import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "scripts" / "build-one-shot-apk.sh"
KEYSTORE = ROOT / "signing" / "debug.keystore"
ARM64_AUTH = ROOT / "vendor-lib" / "arm64-v8a" / "libjl_ota_auth.so"
ARMV7_AUTH = ROOT / "vendor-lib" / "armeabi-v7a" / "libjl_ota_auth.so"


class BuildContractTest(unittest.TestCase):
    def test_builder_pins_tools_inputs_signer_and_identity(self):
        source = BUILD_SCRIPT.read_text(encoding="utf-8")
        required_literals = [
            "/home/jethac/.local/share/e87-dev/jdk-17/usr/lib/jvm/"
            "java-17-openjdk-amd64",
            "/home/jethac/.local/share/e87-dev/android-sdk/platforms/"
            "android-34/android.jar",
            "/home/jethac/.local/share/e87-dev/android-sdk/build-tools/34.0.0",
            "80af017b00ff31f89f96a08f8f5066363d017b6396e8424e4caf2e7901620556",
            "d65dd43fb8eb284b93fcbd85c7ce4e59168f3673e28c7637ed467667e4cc5c4b",
            "5e629e0e0190f745fade919bcca53a7638915b1f856537352977c8b5e0d214ce",
            "c1492dba623bb541187d6db26b0559d4d0dbcf0ff2ce829317c73dab521b2ce5",
            "com.openai.e87probe",
            "com.openai.e87probe.ProbeActivity",
            "E87 One-Shot Lab Uploader",
        ]
        for literal in required_literals:
            with self.subTest(literal=literal):
                self.assertIn(literal, source)
        self.assertIn("--package-size", source)
        self.assertIn("--package-sha256", source)
        self.assertIn("--package-header", source)
        self.assertIn("generate-package-pin.py", source)
        self.assertIn("apksigner", source)
        self.assertIn("zipalign", source)
        self.assertNotIn("190F32B094719E", source)

    def test_staged_binary_hashes_match_reviewed_inputs(self):
        expected = {
            KEYSTORE:
                "80af017b00ff31f89f96a08f8f5066363d017b6396e8424e4caf2e7901620556",
            ARM64_AUTH:
                "d65dd43fb8eb284b93fcbd85c7ce4e59168f3673e28c7637ed467667e4cc5c4b",
            ARMV7_AUTH:
                "5e629e0e0190f745fade919bcca53a7638915b1f856537352977c8b5e0d214ce",
        }
        for path, digest in expected.items():
            with self.subTest(path=path):
                self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_missing_required_pins_fails_without_an_apk(self):
        with tempfile.TemporaryDirectory(prefix="e87-no-pins-") as directory:
            output = Path(directory) / "must-not-exist.apk"
            result = subprocess.run(
                ["/bin/bash", str(BUILD_SCRIPT), "--output", str(output)],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("required", result.stderr.lower())
            self.assertFalse(output.exists())

    def test_no_firmware_payload_is_present_in_the_lab_tree(self):
        forbidden_names = {"update.bin"}
        forbidden_suffixes = {".qix", ".fw"}
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(ROOT)
            self.assertNotIn(relative.name.lower(), forbidden_names)
            self.assertNotIn(relative.suffix.lower(), forbidden_suffixes)


if __name__ == "__main__":
    unittest.main()
