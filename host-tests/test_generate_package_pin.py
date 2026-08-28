import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "generate-package-pin.py"
VALID_SIZE = "35"
VALID_SHA256_LOWER = (
    "190f32b094719e9587cce687243f062c7e967b09a5362113aee79a2e90cf250a"
)
VALID_SHA256_UPPER = VALID_SHA256_LOWER.upper()
VALID_HEADER_LOWER = (
    "bcaf01312e30000000000000000800000000000000000000001234"
)
VALID_HEADER_UPPER = VALID_HEADER_LOWER.upper()


class GeneratePackagePinTest(unittest.TestCase):
    def run_generator(self, output, *, size=VALID_SIZE,
                      sha256=VALID_SHA256_LOWER, header=VALID_HEADER_LOWER):
        return subprocess.run(
            [
                "/usr/bin/python3",
                str(GENERATOR),
                "--size",
                size,
                "--sha256",
                sha256,
                "--header",
                header,
                "--output",
                str(output),
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_normalizes_once_and_is_deterministic(self):
        with tempfile.TemporaryDirectory(prefix="e87-pin-generator-") as directory:
            first = Path(directory) / "one" / "GeneratedPackagePin.java"
            second = Path(directory) / "two" / "GeneratedPackagePin.java"

            first_run = self.run_generator(first)
            second_run = self.run_generator(second)

            self.assertEqual(0, first_run.returncode, first_run.stderr)
            self.assertEqual(0, second_run.returncode, second_run.stderr)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            source = first.read_text(encoding="utf-8")
            self.assertIn("package com.openai.e87probe;", source)
            self.assertIn(
                'new PackagePin(35, "' + VALID_SHA256_UPPER + '",',
                source,
            )
            self.assertIn('Hex.decode("' + VALID_HEADER_UPPER + '")', source)
            self.assertNotIn(VALID_SHA256_LOWER, source)
            self.assertNotIn(VALID_HEADER_LOWER, source)

    def test_invalid_inputs_fail_closed_without_output(self):
        bad_cases = [
            {"size": "33554433"},
            {"size": "27"},
            {"size": "not-a-number"},
            {"sha256": VALID_SHA256_LOWER[:-2]},
            {"sha256": VALID_SHA256_LOWER[:-1] + "g"},
            {"header": VALID_HEADER_LOWER[:-2]},
            {"header": "00" * 27},
        ]
        with tempfile.TemporaryDirectory(prefix="e87-pin-generator-bad-") as directory:
            for index, overrides in enumerate(bad_cases):
                with self.subTest(overrides=overrides):
                    output = Path(directory) / str(index) / "GeneratedPackagePin.java"
                    result = self.run_generator(output, **overrides)
                    self.assertNotEqual(0, result.returncode)
                    self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
