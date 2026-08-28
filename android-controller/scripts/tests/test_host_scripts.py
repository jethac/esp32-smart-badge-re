#!/usr/bin/env python3
from __future__ import annotations

import json
import io
import os
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from scripts import e87_apk, e87_device

from .test_verify_apk import PRODUCTION_SOURCE_ROOT, VerifyApkTest


INSTALL = Path(__file__).resolve().parents[1] / "install-apk.py"
VERIFY = Path(__file__).resolve().parents[1] / "verify-installed-apk.py"
SERIAL = "b202e7b70221"


class HostScriptTest(VerifyApkTest):
    def setUp(self) -> None:
        super().setUp()
        self.adb_log = self.base / "adb.log"
        self.adb_install_capture = self.base / "adb-install-capture.apk"
        self.adb_mutation_result = self.base / "adb-mutation-result.txt"
        self.fake_adb_projection_aba = False
        self.fake_installed_apk = self.apk
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
            "    source = pathlib.Path(command[2])\n"
            "    if os.environ['FAKE_ADB_PROJECTION_ABA'] == '1':\n"
            "        original = source.read_bytes()\n"
            "        try:\n"
            "            source.chmod(0o600)\n"
            "            source.write_bytes(b'X' * len(original))\n"
            "        except OSError:\n"
            "            pathlib.Path(os.environ['FAKE_ADB_MUTATION_RESULT']).write_text('blocked')\n"
            "            shutil.copyfile(source, os.environ['FAKE_ADB_INSTALL_CAPTURE'])\n"
            "        else:\n"
            "            pathlib.Path(os.environ['FAKE_ADB_MUTATION_RESULT']).write_text('mutated')\n"
            "            shutil.copyfile(source, os.environ['FAKE_ADB_INSTALL_CAPTURE'])\n"
            "            source.write_bytes(original)\n"
            "            source.chmod(0o400)\n"
            "    else:\n"
            "        shutil.copyfile(source, os.environ['FAKE_ADB_INSTALL_CAPTURE'])\n"
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
        environment["FAKE_ADB_INSTALL_CAPTURE"] = os.fspath(self.adb_install_capture)
        environment["FAKE_ADB_MUTATION_RESULT"] = os.fspath(self.adb_mutation_result)
        environment["FAKE_ADB_PROJECTION_ABA"] = (
            "1" if self.fake_adb_projection_aba else "0")
        environment["FAKE_INSTALLED_APK"] = os.fspath(self.fake_installed_apk)
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
        output = io.StringIO()
        error = io.StringIO()
        function = e87_device.install if script == INSTALL else e87_device.verify_installed
        description = "test serial-scoped E87 host command"
        with mock.patch.object(
                e87_apk, "SURFACE_RECEIPT", self.surface_receipt), mock.patch.object(
                e87_apk, "BUILD_RECEIPT", self.build_receipt), mock.patch.object(
                e87_apk, "SOURCE_ROOT", PRODUCTION_SOURCE_ROOT), mock.patch.dict(
                os.environ, self.host_env(), clear=False), redirect_stdout(
                output), redirect_stderr(error):
            try:
                returncode = e87_device.run(function, description, arguments)
            except SystemExit as exit_status:
                returncode = int(exit_status.code)
        return subprocess.CompletedProcess(
            [os.fspath(script), *arguments],
            returncode,
            output.getvalue(),
            error.getvalue(),
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
        self.assertNotIn(os.fspath(self.apk), lines[1])
        self.assertEqual(self.apk.read_bytes(), self.adb_install_capture.read_bytes())

    def test_install_uses_the_audited_snapshot_after_source_replacement(self) -> None:
        audited = self.apk.read_bytes()
        self.write_apk(mutate=("classes.dex", b"evil impl bytes"))
        replacement = self.apk.read_bytes()
        self.apk.write_bytes(audited)
        real_audit = e87_device._audit_snapshot

        def replace_source_after_audit(*arguments, **keywords):
            result = real_audit(*arguments, **keywords)
            self.apk.write_bytes(replacement)
            return result

        with mock.patch.object(
                e87_device, "_audit_snapshot", side_effect=replace_source_after_audit):
            result = self.run_script(INSTALL, self.common())

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(replacement, self.apk.read_bytes())
        self.assertEqual(audited, self.adb_install_capture.read_bytes())
        receipt = json.loads(result.stdout)
        self.assertEqual(
            e87_apk._sha(audited),
            receipt["apkAudit"]["apkSha256"],
        )

    def test_install_projection_cannot_be_mutated_and_restored_inside_adb(self) -> None:
        audited = self.apk.read_bytes()
        self.fake_adb_projection_aba = True

        result = self.run_script(INSTALL, self.common())

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("blocked", self.adb_mutation_result.read_text())
        self.assertEqual(audited, self.adb_install_capture.read_bytes())
        receipt = json.loads(result.stdout)
        self.assertEqual(
            e87_apk._sha(self.adb_install_capture.read_bytes()),
            receipt["apkAudit"]["apkSha256"],
        )

    def test_installed_verifier_does_not_reopen_replaced_expected_path(self) -> None:
        expected = self.apk.read_bytes()
        installed = self.base / "independent-installed.apk"
        installed.write_bytes(expected)
        self.fake_installed_apk = installed
        self.write_apk(mutate=("classes.dex", b"evil impl bytes"))
        replacement = self.apk.read_bytes()
        self.apk.write_bytes(expected)
        real_audit = e87_device._audit_snapshot
        audit_count = 0

        def replace_expected_after_first_audit(*arguments, **keywords):
            nonlocal audit_count
            result = real_audit(*arguments, **keywords)
            audit_count += 1
            if audit_count == 1:
                self.apk.write_bytes(replacement)
            return result

        with mock.patch.object(
                e87_device,
                "_audit_snapshot",
                side_effect=replace_expected_after_first_audit,
        ):
            result = self.run_script(VERIFY, self.common())

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(2, audit_count)
        self.assertEqual(replacement, self.apk.read_bytes())
        receipt = json.loads(result.stdout)
        self.assertEqual(
            e87_apk._sha(expected),
            receipt["expectedApkSha256"],
        )

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
