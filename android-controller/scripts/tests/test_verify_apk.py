#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from scripts import e87_apk
from scripts.e87_build import build_authorization
from scripts.e87_embed import ValidationError, _canonical
from scripts.e87_surface import build_surface

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
PRODUCTION_SOURCE_ROOT = (
    Path(__file__).resolve().parents[2] / "app/src/main/java"
)


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
        self.surface_receipt = self.base / "authorized-surface.json"
        self.surface_receipt.write_bytes(_canonical(
            build_surface(PRODUCTION_SOURCE_ROOT, DEXDUMP)))
        self.build_receipt = self.base / "authorized-build.json"
        self.authorize_current_apk()

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

    def authorize_current_apk(self) -> None:
        self.build_receipt.write_bytes(_canonical(build_authorization(
            self.apk,
            self.surface_receipt,
        )))

    def verify(self, *, aapt: Path | None = None, dexdump: Path | None = None,
               receipt: Path | None = None) -> subprocess.CompletedProcess[str]:
        try:
            with mock.patch.object(
                    e87_apk, "SURFACE_RECEIPT", self.surface_receipt), mock.patch.object(
                    e87_apk, "BUILD_RECEIPT", self.build_receipt), mock.patch.object(
                    e87_apk, "SOURCE_ROOT", PRODUCTION_SOURCE_ROOT):
                value = e87_apk.audit_apk(
                    self.apk,
                    self.release.root,
                    self.aapt if aapt is None else aapt,
                    self.dexdump if dexdump is None else dexdump,
                )
            if receipt is not None:
                e87_apk.write_receipt(receipt, value)
            return subprocess.CompletedProcess(
                [], 0, _canonical(value).decode("ascii"), "")
        except (OSError, ValidationError, zipfile.BadZipFile) as error:
            return subprocess.CompletedProcess([], 2, "", str(error))

    def test_audit_accepts_exact_bytes_and_emits_canonical_path_free_receipt(self) -> None:
        receipt = self.base / "apk-audit.json"

        result = self.verify(receipt=receipt)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        value = json.loads(receipt.read_bytes())
        self.assertEqual("e87-android-apk-audit-v2", value["schemaId"])
        self.assertEqual(2, value["schemaVersion"])
        self.assertEqual("net.jethachan.factory_badges", value["applicationId"])
        self.assertEqual(31, value["minSdk"])
        self.assertEqual(34, value["targetSdk"])
        self.assertEqual(self.release.receipt["buildId"], value["buildId"])
        self.assertTrue(value["labEligible"])
        self.assertFalse(value["releaseEligible"])
        self.assertEqual("11.1.0.4", value["qixVersion"])
        self.assertEqual(self.release.receipt["releaseRoot"], value["releaseRoot"])
        self.assertEqual(len(AUTHORIZED_DESCRIPTORS), value["authorizedClassCount"])
        self.assertEqual(["classes.dex"], [
            record["name"] for record in value["authorizedDex"]])
        self.assertRegex(value["authorizedBuildSha256"], r"^[0-9A-F]{64}$")
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
        self.authorize_current_apk()
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

    def test_audit_rejects_changed_code_inside_an_authorized_descriptor(self) -> None:
        self.write_apk(mutate=(
            "classes.dex",
            b"changed implementation referencing android.bluetooth.BluetoothGatt",
        ))
        changed_dump = DEXDUMP.replace(
            "  Superclass",
            "  type              : 'Landroid/bluetooth/BluetoothGatt;'\n"
            "  Superclass",
            1,
        )

        result = self.verify(dexdump=self.make_tool("dexdump", changed_dump))

        self.assertEqual(2, result.returncode, result.stdout + result.stderr)

    def test_audit_uses_one_snapshot_across_original_path_replacement_and_aba(self) -> None:
        original = self.apk.read_bytes()
        self.write_apk(mutate=("classes.dex", b"evil impl bytes"))
        replacement = self.apk.read_bytes()
        replacement_path = self.base / "replacement.apk"
        self.apk.replace(replacement_path)
        self.apk.write_bytes(original)
        original_stat = self.apk.stat()
        original_away = self.base / "original-away.apk"
        replacement_away = self.base / "replacement-away.apk"
        self.assertEqual(len(original), len(replacement))
        real_run = e87_apk._run
        tool_apk_paths: list[Path] = []

        def swap_original_during_tool_audit(
                tool: Path, arguments: list[str], label: str, *,
                snapshot=None) -> str:
            candidates = [Path(argument) for argument in arguments
                          if argument.endswith(".apk")
                          or argument.startswith("/proc/self/fd/")]
            tool_apk_paths.extend(candidates)
            if len(tool_apk_paths) == 1:
                self.apk.replace(original_away)
                replacement_path.replace(self.apk)
            elif len(tool_apk_paths) == 2:
                self.apk.replace(replacement_away)
                original_away.replace(self.apk)
            return real_run(tool, arguments, label, snapshot=snapshot)

        with mock.patch.object(
                e87_apk, "_run", side_effect=swap_original_during_tool_audit):
            result = self.verify()

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(hashlib.sha256(original).hexdigest().upper(), value["apkSha256"])
        self.assertEqual(original, self.apk.read_bytes())
        self.assertEqual(original_stat.st_ino, self.apk.stat().st_ino)
        self.assertEqual(original_stat.st_size, self.apk.stat().st_size)
        self.assertEqual(original_stat.st_mtime_ns, self.apk.stat().st_mtime_ns)
        self.assertTrue(tool_apk_paths)
        self.assertEqual(1, len(set(tool_apk_paths)))
        self.assertNotEqual(self.apk, tool_apk_paths[0])

    def test_audit_projection_cannot_be_mutated_and_restored_during_tool_run(self) -> None:
        audited = self.apk.read_bytes()
        marker = self.base / "projection-mutation.txt"
        malicious = self.base / "mutating-dexdump"
        malicious.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib, sys\n"
            f"marker = pathlib.Path({os.fspath(marker)!r})\n"
            "projection = pathlib.Path(sys.argv[-1])\n"
            "original = projection.read_bytes()\n"
            "try:\n"
            "    projection.chmod(0o600)\n"
            "    projection.write_bytes(b'X' * len(original))\n"
            "except OSError:\n"
            "    marker.write_text('blocked')\n"
            "else:\n"
            "    marker.write_text('mutated')\n"
            "    projection.write_bytes(original)\n"
            f"sys.stdout.write({DEXDUMP!r})\n",
            encoding="utf-8",
        )
        malicious.chmod(0o755)

        result = self.verify(dexdump=malicious)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("blocked", marker.read_text())
        self.assertEqual(e87_apk._sha(audited), json.loads(result.stdout)["apkSha256"])

    def test_namespace_projection_path_cannot_be_renamed_from_parent_namespace(self) -> None:
        audited = self.apk.read_bytes()
        self.write_apk(mutate=("classes.dex", b"evil impl bytes"))
        replacement = self.apk.read_bytes()
        self.apk.write_bytes(audited)
        ready = self.base / "projection-ready"
        proceed = self.base / "projection-proceed"
        observed = self.base / "projection-observed-sha256"
        done = self.base / "projection-done"
        malicious = self.base / "delayed-dexdump"
        malicious.write_text(
            "#!/usr/bin/env python3\n"
            "import hashlib, pathlib, sys, time\n"
            f"ready = pathlib.Path({os.fspath(ready)!r})\n"
            f"proceed = pathlib.Path({os.fspath(proceed)!r})\n"
            f"observed = pathlib.Path({os.fspath(observed)!r})\n"
            f"done = pathlib.Path({os.fspath(done)!r})\n"
            "ready.write_text('ready')\n"
            "for _ in range(1000):\n"
            "    if proceed.exists():\n"
            "        break\n"
            "    time.sleep(0.005)\n"
            "else:\n"
            "    raise SystemExit(41)\n"
            "payload = pathlib.Path(sys.argv[-1]).read_bytes()\n"
            "observed.write_text(hashlib.sha256(payload).hexdigest().upper())\n"
            "done.write_text('done')\n"
            f"sys.stdout.write({DEXDUMP!r})\n",
            encoding="utf-8",
        )
        malicious.chmod(0o755)
        real_run = e87_apk._run
        rename_blocked = False
        attacker_errors: list[BaseException] = []

        def wait_for(path: Path) -> None:
            deadline = time.monotonic() + 10
            while not path.exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for {path.name}")
                time.sleep(0.005)

        def delayed_parent_rename(snapshot) -> None:
            nonlocal rename_blocked
            parent = snapshot.path.parent
            moved = self.base / "projection-mountpoint-away"
            replaced = False
            try:
                wait_for(ready)
                try:
                    parent.replace(moved)
                except OSError:
                    rename_blocked = True
                else:
                    replaced = True
                    parent.mkdir(mode=0o700)
                    snapshot.path.write_bytes(replacement)
                proceed.write_text("proceed")
                wait_for(done)
            except BaseException as error:
                attacker_errors.append(error)
                proceed.write_text("proceed")
            finally:
                if replaced:
                    snapshot.path.unlink(missing_ok=True)
                    parent.rmdir()
                    moved.replace(parent)

        def run_with_parent_rename(
                tool: Path, arguments: list[str], label: str, *, snapshot=None) -> str:
            if label != "dexdump":
                return real_run(tool, arguments, label, snapshot=snapshot)
            attacker = threading.Thread(
                target=delayed_parent_rename,
                args=(snapshot,),
                daemon=True,
            )
            attacker.start()
            output = real_run(tool, arguments, label, snapshot=snapshot)
            attacker.join(timeout=15)
            if attacker.is_alive():
                raise AssertionError("parent-namespace rename thread did not exit")
            return output

        with mock.patch.object(
                e87_apk, "_run", side_effect=run_with_parent_rename):
            result = self.verify(dexdump=malicious)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertFalse(attacker_errors, attacker_errors)
        self.assertTrue(rename_blocked)
        self.assertEqual(e87_apk._sha(audited), observed.read_text())

    def test_audit_fails_closed_without_linux_sealed_memory(self) -> None:
        with mock.patch.object(e87_apk.sys, "platform", "unsupported-host"):
            result = self.verify()

        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("kernel-sealed APK snapshots require a Linux host", result.stderr)

    def test_audit_rejects_a_caller_owned_mount_anchor(self) -> None:
        caller_anchor = self.base / "caller-owned-anchor"
        caller_anchor.mkdir()
        with mock.patch.object(
                e87_apk, "SEALED_MOUNT_ROOT", caller_anchor), mock.patch.object(
                e87_apk,
                "SEALED_PROJECTION",
                caller_anchor / "e87-controller-snapshot.apk",
        ):
            result = self.verify()

        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("root-owned non-writable directory", result.stderr)

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
