#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from .test_e87_embed import ReleaseFixture, ROLE_NAMES


SCRIPT = Path(__file__).resolve().parents[1] / "verify-apk.py"
PERMISSIONS = """package: net.jethachan.factory_badges
uses-permission: name='android.permission.BLUETOOTH_SCAN'
uses-permission: name='android.permission.BLUETOOTH_CONNECT'
uses-permission: name='android.permission.FOREGROUND_SERVICE'
uses-permission: name='android.permission.FOREGROUND_SERVICE_CONNECTED_DEVICE'
uses-permission: name='android.permission.POST_NOTIFICATIONS'
"""
BADGING = """package: name='net.jethachan.factory_badges' versionCode='1' versionName='1.0'
sdkVersion:'31'
targetSdkVersion:'34'
application-debuggable
"""
XMLTREE = """N: android=http://schemas.android.com/apk/res/android
  E: manifest (line=2)
    E: application (line=20)
      E: activity (line=25)
        A: android:name(0x01010003)="net.jethachan.factory_badges.ui.MainActivity"
        A: android:exported(0x01010010)=(type 0x12)0xffffffff
      E: activity (line=31)
        A: android:name(0x01010003)="net.jethachan.factory_badges.ui.MaintenanceActivity"
        A: android:exported(0x01010010)=(type 0x12)0x0
"""
SURFACE = json.loads((Path(__file__).resolve().parents[1]
                      / "e87-authorized-app-surface.json").read_bytes())
AUTHORIZED_DESCRIPTORS = tuple(SURFACE["classDescriptors"])


def make_dexdump(*, multidex: bool = False) -> str:
    opened = "Opened '/tmp/controller.apk:classes.dex', DEX version '039'\n"
    if multidex:
        opened += "Opened '/tmp/controller.apk:classes2.dex', DEX version '039'\n"
    blocks = "".join(
        f"Class #{index}            -\n"
        f"  Class descriptor  : '{descriptor}'\n"
        "  Superclass        : 'Ljava/lang/Object;'\n"
        for index, descriptor in enumerate(AUTHORIZED_DESCRIPTORS)
    )
    return opened + blocks


DEXDUMP = make_dexdump()


class VerifyApkTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.release = ReleaseFixture(self.base / "release")
        self.aapt = self.make_aapt(PERMISSIONS, BADGING, XMLTREE)
        self.dexdump = self.make_tool("dexdump", DEXDUMP)
        self.apk = self.base / "controller.apk"
        self.write_apk()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_tool(self, name: str, output: str) -> Path:
        path = self.base / name
        path.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            f"sys.stdout.write({output!r})\n",
            encoding="utf-8",
        )
        path.chmod(0o755)
        return path

    def make_aapt(self, permissions: str, badging: str, xmltree: str) -> Path:
        path = self.base / "aapt"
        path.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            f"permissions = {permissions!r}\n"
            f"badging = {badging!r}\n"
            f"xmltree = {xmltree!r}\n"
            "args = sys.argv[1:]\n"
            "if args[:2] == ['dump', 'permissions']:\n"
            "    sys.stdout.write(permissions)\n"
            "elif args[:2] == ['dump', 'badging']:\n"
            "    sys.stdout.write(badging)\n"
            "elif args[:2] == ['dump', 'xmltree']:\n"
            "    sys.stdout.write(xmltree)\n"
            "else:\n"
            "    raise SystemExit(9)\n",
            encoding="utf-8",
        )
        path.chmod(0o755)
        return path

    def write_apk(self, *, extra: dict[str, bytes] | None = None,
                  mutate: tuple[str, bytes] | None = None) -> None:
        root = self.release.receipt["releaseRoot"]
        entries = {
            "AndroidManifest.xml": b"binary manifest placeholder",
            "classes.dex": b"dex placeholder",
            "assets/e87/default-release.json":
                (self.release.root / "e87-android-embed.json").read_bytes(),
        }
        for _, name in ROLE_NAMES:
            entries[f"assets/e87/{root}/{name}"] = (self.release.root / name).read_bytes()
        if mutate is not None:
            entries[mutate[0]] = mutate[1]
        if extra:
            entries.update(extra)
        with zipfile.ZipFile(self.apk, "w", compression=zipfile.ZIP_STORED) as archive:
            for name in sorted(entries):
                archive.writestr(name, entries[name])

    def verify(self, *, aapt: Path | None = None, dexdump: Path | None = None,
               receipt: Path | None = None) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable, os.fspath(SCRIPT),
            "--apk", os.fspath(self.apk),
            "--release", os.fspath(self.release.root),
            "--aapt", os.fspath(self.aapt if aapt is None else aapt),
            "--dexdump", os.fspath(self.dexdump if dexdump is None else dexdump),
        ]
        if receipt is not None:
            command += ["--receipt", os.fspath(receipt)]
        return subprocess.run(command, cwd=self.base, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

    def test_audit_accepts_exact_bytes_and_emits_canonical_path_free_receipt(self) -> None:
        receipt = self.base / "apk-audit.json"

        result = self.verify(receipt=receipt)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        value = json.loads(receipt.read_bytes())
        self.assertEqual("e87-android-apk-audit-v1", value["schemaId"])
        self.assertEqual("net.jethachan.factory_badges", value["applicationId"])
        self.assertEqual(31, value["minSdk"])
        self.assertEqual(34, value["targetSdk"])
        self.assertEqual(self.release.receipt["buildId"], value["buildId"])
        self.assertTrue(value["labEligible"])
        self.assertFalse(value["releaseEligible"])
        self.assertEqual("11.1.0.4", value["qixVersion"])
        self.assertEqual(self.release.receipt["releaseRoot"], value["releaseRoot"])
        self.assertEqual(len(AUTHORIZED_DESCRIPTORS), value["authorizedClassCount"])
        self.assertRegex(value["authorizedSurfaceSha256"], r"^[0-9A-F]{64}$")
        self.assertNotIn(os.fspath(self.base), receipt.read_text(encoding="ascii"))
        self.assertEqual(
            json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2,
                       sort_keys=True) + "\n",
            receipt.read_text(encoding="ascii"),
        )

    def test_audit_rejects_extra_missing_mutated_or_flutter_assets(self) -> None:
        root = self.release.receipt["releaseRoot"]
        mutations = (
            {"extra": {"assets/e87/extra.bin": b"x"}},
            {"extra": {"assets/flutter_assets/kernel_blob.bin": b"x"}},
            {"extra": {"classes2.dex": b"hidden dex"}},
            {"mutate": (f"assets/e87/{root}/app.bin", b"wrong")},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.write_apk(**mutation)
                result = self.verify()
                self.assertEqual(2, result.returncode, result.stdout + result.stderr)

    def test_audit_accepts_contiguous_multidex_only_when_every_dex_is_scanned(self) -> None:
        self.write_apk(extra={"classes2.dex": b"second dex"})
        dump = make_dexdump(multidex=True)

        result = self.verify(dexdump=self.make_tool("dexdump", dump))

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_audit_rejects_network_storage_location_or_duplicate_permissions(self) -> None:
        forbidden = (
            "android.permission.INTERNET",
            "android.permission.ACCESS_FINE_LOCATION",
            "android.permission.READ_EXTERNAL_STORAGE",
            "android.permission.BLUETOOTH_CONNECT",
        )
        for permission in forbidden:
            with self.subTest(permission=permission):
                aapt = self.make_aapt(
                    PERMISSIONS + f"uses-permission: name='{permission}'\n",
                    BADGING, XMLTREE)
                result = self.verify(aapt=aapt)
                self.assertEqual(2, result.returncode, result.stdout + result.stderr)

    def test_audit_rejects_wrong_package_sdk_or_exported_maintenance(self) -> None:
        bad_outputs = (
            BADGING.replace("net.jethachan.factory_badges", "wrong.package"),
            BADGING.replace("sdkVersion:'31'", "sdkVersion:'30'"),
            BADGING.replace("targetSdkVersion:'34'", "targetSdkVersion:'35'"),
        )
        for badging in bad_outputs:
            with self.subTest(badging=badging):
                result = self.verify(aapt=self.make_aapt(PERMISSIONS, badging, XMLTREE))
                self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        exported = XMLTREE.replace(
            'A: android:exported(0x01010010)=(type 0x12)0x0',
            'A: android:exported(0x01010010)=(type 0x12)0xffffffff')
        result = self.verify(aapt=self.make_aapt(PERMISSIONS, BADGING, exported))
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)

    def test_audit_rejects_vendor_native_code_and_forbidden_app_class_references(self) -> None:
        self.write_apk(extra={"lib/arm64-v8a/libjl_ota_auth.so": b"native"})
        result = self.verify()
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)

        self.write_apk()
        forbidden_blocks = (
            DEXDUMP.replace("  Superclass", "  type          : 'Ljava/net/Socket;'\n  Superclass"),
            DEXDUMP.replace("  Superclass", "  string        : 'ACTION_OPEN_DOCUMENT'\n  Superclass"),
            DEXDUMP.replace("  Superclass", "  type          : 'Lcom/jieli/bluetooth_connect/impl/BluetoothOTAManager;'\n  Superclass"),
        )
        for dump in forbidden_blocks:
            with self.subTest(dump=dump):
                result = self.verify(dexdump=self.make_tool("dexdump", dump))
                self.assertEqual(2, result.returncode, result.stdout + result.stderr)

        unapproved_namespace = DEXDUMP + """Class #2            -
  Class descriptor  : 'Lnet/jethachan/factory_badges/hidden/TransferClient;'
  type              : 'Landroid/bluetooth/BluetoothGatt;'
  Superclass        : 'Ljava/lang/Object;'
"""
        result = self.verify(
            dexdump=self.make_tool("dexdump", unapproved_namespace))
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)

    def test_paths_and_receipt_are_create_only_and_absolute(self) -> None:
        result = subprocess.run(
            [sys.executable, os.fspath(SCRIPT), "--apk", "controller.apk",
             "--release", os.fspath(self.release.root), "--aapt", os.fspath(self.aapt),
             "--dexdump", os.fspath(self.dexdump)],
            cwd=self.base, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(2, result.returncode)
        receipt = self.base / "audit.json"
        receipt.write_text("keep", encoding="ascii")
        result = self.verify(receipt=receipt)
        self.assertEqual(2, result.returncode)
        self.assertEqual("keep", receipt.read_text(encoding="ascii"))


if __name__ == "__main__":
    unittest.main()
