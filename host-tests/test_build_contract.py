import hashlib
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "scripts" / "build-one-shot-apk.sh"
KEYSTORE = ROOT / "signing" / "debug.keystore"
ARM64_AUTH = ROOT / "vendor-lib" / "arm64-v8a" / "libjl_ota_auth.so"
ARMV7_AUTH = ROOT / "vendor-lib" / "armeabi-v7a" / "libjl_ota_auth.so"
BUILD_TOOLS = Path("/home/jethac/.local/share/e87-dev/android-sdk/build-tools/34.0.0")
AAPT2 = BUILD_TOOLS / "aapt2"
APKSIGNER = BUILD_TOOLS / "apksigner"
JAVA_HOME = Path("/home/jethac/.local/share/e87-dev/jdk-17/usr/lib/jvm/java-17-openjdk-amd64")
EXPECTED_CERT = "c1492dba623bb541187d6db26b0559d4d0dbcf0ff2ce829317c73dab521b2ce5"
SYNTHETIC_SHA256 = "190f32b094719e9587cce687243f062c7e967b09a5362113aee79a2e90cf250a"
SYNTHETIC_HEADER = "bcaf01312e30000000000000000800000000000000000000001234"


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

    def test_full_signed_apk_smoke_audits_android_compile_and_contents(self):
        with tempfile.TemporaryDirectory(prefix="e87-signed-smoke-") as directory:
            output = Path(directory) / "smoke.apk"
            result = subprocess.run(
                [
                    "/bin/bash",
                    str(BUILD_SCRIPT),
                    "--package-size",
                    "35",
                    "--package-sha256",
                    SYNTHETIC_SHA256,
                    "--package-header",
                    SYNTHETIC_HEADER,
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
                check=False,
            )
            self.assertEqual(
                0,
                result.returncode,
                msg=f"builder stdout:\n{result.stdout}\nbuilder stderr:\n{result.stderr}",
            )
            self.assertTrue(output.is_file())
            self.assertIn(f"APK={output}", result.stdout)
            self.assertIn(f"SIGNER_CERT_SHA256={EXPECTED_CERT}", result.stdout)

            audit_env = os.environ.copy()
            audit_env["JAVA_HOME"] = str(JAVA_HOME)
            audit_env["PATH"] = f"{JAVA_HOME / 'bin'}:{audit_env.get('PATH', '')}"
            verified = subprocess.run(
                [str(APKSIGNER), "verify", "--verbose", "--print-certs", str(output)],
                cwd=ROOT,
                env=audit_env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
            self.assertEqual(
                0,
                verified.returncode,
                msg=f"apksigner stdout:\n{verified.stdout}\nstderr:\n{verified.stderr}",
            )
            normalized_certificate_output = verified.stdout.lower().replace(":", "")
            self.assertIn(EXPECTED_CERT, normalized_certificate_output)

            badging = subprocess.check_output(
                [str(AAPT2), "dump", "badging", str(output)],
                cwd=ROOT,
                text=True,
                timeout=30,
            )
            self.assertIn("package: name='com.openai.e87probe'", badging)
            self.assertIn(
                "launchable-activity: name='com.openai.e87probe.ProbeActivity'",
                badging,
            )
            manifest_tree = subprocess.check_output(
                [
                    str(AAPT2),
                    "dump",
                    "xmltree",
                    str(output),
                    "--file",
                    "AndroidManifest.xml",
                ],
                cwd=ROOT,
                text=True,
                timeout=30,
            )
            self.assertIn(
                'android:label(0x01010001)="E87 One-Shot Lab Uploader"',
                manifest_tree,
            )

            expected_native_hashes = {
                "lib/arm64-v8a/libjl_ota_auth.so":
                    "d65dd43fb8eb284b93fcbd85c7ce4e59168f3673e28c7637ed467667e4cc5c4b",
                "lib/armeabi-v7a/libjl_ota_auth.so":
                    "5e629e0e0190f745fade919bcca53a7638915b1f856537352977c8b5e0d214ce",
            }
            with zipfile.ZipFile(output) as apk:
                names = set(apk.namelist())
                self.assertIn("classes.dex", names)
                for name, expected_hash in expected_native_hashes.items():
                    with self.subTest(name=name):
                        self.assertIn(name, names)
                        self.assertEqual(
                            expected_hash,
                            hashlib.sha256(apk.read(name)).hexdigest(),
                        )
                for name in names:
                    lower_name = name.lower()
                    self.assertFalse(lower_name.startswith("assets/"))
                    self.assertNotIn(Path(lower_name).name, {"update.bin", "debug.keystore"})
                    self.assertFalse(lower_name.endswith((".qix", ".fw")))

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
