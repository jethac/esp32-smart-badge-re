#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from .test_verify_apk import VerifyApkTest


INSTALL = Path(__file__).resolve().parents[1] / "install-apk.py"
VERIFY = Path(__file__).resolve().parents[1] / "verify-installed-apk.py"
SERIAL = "b202e7b70221"


class HostScriptTest(VerifyApkTest):
    def setUp(self) -> None:
        super().setUp()
        self.adb_log = self.base / "adb.log"
        self.adb = self.base / "adb"
        self.adb.write_text(
            "#!/usr/bin/env python3\n"
            "import os, pathlib, shutil, sys\n"
            "args = sys.argv[1:]\n"
            "log = pathlib.Path(os.environ['FAKE_ADB_LOG'])\n"
            "with log.open('a', encoding='utf-8') as stream:\n"
            "    stream.write(repr(args) + '\\n')\n"
            "if len(args) < 3 or args[0] != '-s':\n"
            "    raise SystemExit(8)\n"
            "command = args[2:]\n"
            "if command == ['get-state']:\n"
            "    print('device')\n"
            "elif command[:2] == ['install', '-r']:\n"
            "    print('Success')\n"
            "elif command == ['shell', 'pm', 'path', 'net.jethachan.factory_badges']:\n"
            "    print('package:/data/app/qualified/base.apk')\n"
            "elif len(command) == 3 and command[0] == 'pull':\n"
            "    shutil.copyfile(os.environ['FAKE_INSTALLED_APK'], command[2])\n"
            "    print('1 file pulled')\n"
            "else:\n"
            "    raise SystemExit(7)\n",
            encoding="utf-8",
        )
        self.adb.chmod(0o755)

    def host_env(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment["FAKE_ADB_LOG"] = os.fspath(self.adb_log)
        environment["FAKE_INSTALLED_APK"] = os.fspath(self.apk)
        return environment

    def common(self) -> list[str]:
        return [
            "--serial", SERIAL,
            "--apk", os.fspath(self.apk),
            "--release", os.fspath(self.release.root),
            "--aapt", os.fspath(self.aapt),
            "--dexdump", os.fspath(self.dexdump),
            "--adb", os.fspath(self.adb),
        ]

    def run_script(self, script: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, os.fspath(script), *arguments],
            cwd=self.base, env=self.host_env(), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )

    def test_install_requires_serial_audits_first_and_passes_exact_serial_to_adb(self) -> None:
        missing = self.run_script(INSTALL, self.common()[2:])
        self.assertEqual(2, missing.returncode)
        self.assertFalse(self.adb_log.exists())

        invalid_apk = self.base / "invalid.apk"
        invalid_apk.write_bytes(b"not an APK")
        invalid_arguments = self.common()
        invalid_arguments[invalid_arguments.index("--apk") + 1] = os.fspath(invalid_apk)
        invalid = self.run_script(INSTALL, invalid_arguments)
        self.assertEqual(2, invalid.returncode)
        self.assertFalse(self.adb_log.exists())

        result = self.run_script(INSTALL, self.common())
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        lines = self.adb_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(2, len(lines))
        self.assertIn(repr(SERIAL), lines[0])
        self.assertIn(repr(SERIAL), lines[1])
        self.assertIn("get-state", lines[0])
        self.assertIn("install", lines[1])

    def test_installed_verifier_pulls_exact_package_and_reaudits_identical_apk(self) -> None:
        receipt = self.base / "installed-audit.json"
        result = self.run_script(
            VERIFY, [*self.common(), "--receipt", os.fspath(receipt)])

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        value = json.loads(receipt.read_bytes())
        self.assertEqual("e87-android-installed-audit-v1", value["schemaId"])
        self.assertEqual(SERIAL, value["serial"])
        self.assertEqual(value["expectedApkSha256"], value["installedApkSha256"])
        lines = self.adb_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(3, len(lines))
        self.assertTrue(all(repr(SERIAL) in line for line in lines))
        self.assertIn("get-state", lines[0])
        self.assertIn("'shell', 'pm', 'path'", lines[1])
        self.assertIn("'pull'", lines[2])

    def test_invalid_serial_or_existing_receipt_stops_before_adb(self) -> None:
        arguments = self.common()
        arguments[arguments.index("--serial") + 1] = "serial with spaces"
        result = self.run_script(INSTALL, arguments)
        self.assertEqual(2, result.returncode)
        self.assertFalse(self.adb_log.exists())

        receipt = self.base / "installed-audit.json"
        receipt.write_text("keep", encoding="ascii")
        result = self.run_script(
            VERIFY, [*self.common(), "--receipt", os.fspath(receipt)])
        self.assertEqual(2, result.returncode)
        self.assertFalse(self.adb_log.exists())
        self.assertEqual("keep", receipt.read_text(encoding="ascii"))


if __name__ == "__main__":
    unittest.main()
