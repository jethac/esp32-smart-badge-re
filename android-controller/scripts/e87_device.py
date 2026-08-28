#!/usr/bin/env python3
"""Serial-scoped Android install and installed-APK verification helpers."""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence

try:
    from .e87_apk import (
        _audit_snapshot,
        _canonical,
        _regular_absolute,
        _snapshot_apk,
        write_receipt,
    )
    from .e87_embed import ValidationError
except ImportError:
    from e87_apk import (
        _audit_snapshot,
        _canonical,
        _regular_absolute,
        _snapshot_apk,
        write_receipt,
    )
    from e87_embed import ValidationError


SERIAL = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
PACKAGE = "net.jethachan.factory_badges"
REMOTE_APK = re.compile(r"/data/app/[A-Za-z0-9._~=/+:-]+/base\.apk\Z")


def _validate_serial(value: str) -> str:
    if not isinstance(value, str) or SERIAL.fullmatch(value) is None:
        raise ValidationError("an explicit canonical adb serial is required")
    return value


def _run_adb(adb: Path, serial: str, arguments: list[str], label: str,
             *, timeout: int = 180) -> str:
    try:
        completed = subprocess.run(
            [os.fspath(adb), "-s", serial, *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValidationError(f"adb {label} failed to execute") from error
    if completed.returncode != 0:
        raise ValidationError(f"adb {label} exited {completed.returncode}")
    try:
        output = completed.stdout.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValidationError(f"adb {label} output is not UTF-8") from error
    return output


def _require_device(adb: Path, serial: str) -> None:
    if _run_adb(adb, serial, ["get-state"], "get-state", timeout=30).strip() != "device":
        raise ValidationError("the exact adb serial is not in device state")


def install(arguments: argparse.Namespace) -> dict[str, object]:
    serial = _validate_serial(arguments.serial)
    adb = _regular_absolute(arguments.adb, "adb", executable=True)
    if arguments.receipt is not None and Path(arguments.receipt).exists():
        raise ValidationError("install receipt already exists")
    with _snapshot_apk(arguments.apk) as snapshot:
        audit = _audit_snapshot(
            snapshot, arguments.release, arguments.aapt, arguments.dexdump)
        _require_device(adb, serial)
        snapshot.verify_projection()
        output = _run_adb(
            adb,
            serial,
            ["install", "-r", os.fspath(snapshot.path)],
            "install",
        )
        snapshot.verify_projection()
        if "Success" not in output.splitlines():
            raise ValidationError("adb install did not report Success")
    receipt = {
        "apkAudit": audit,
        "package": PACKAGE,
        "schemaId": "e87-android-install-v1",
        "schemaVersion": 1,
        "serial": serial,
    }
    if arguments.receipt is not None:
        write_receipt(arguments.receipt, receipt)
    return receipt


def verify_installed(arguments: argparse.Namespace) -> dict[str, object]:
    serial = _validate_serial(arguments.serial)
    adb = _regular_absolute(arguments.adb, "adb", executable=True)
    if arguments.receipt is not None and Path(arguments.receipt).exists():
        raise ValidationError("installed audit receipt already exists")
    with _snapshot_apk(arguments.apk) as expected_snapshot:
        expected = _audit_snapshot(
            expected_snapshot, arguments.release, arguments.aapt, arguments.dexdump)
        _require_device(adb, serial)
        paths = [line for line in _run_adb(
            adb, serial, ["shell", "pm", "path", PACKAGE], "package path", timeout=30
        ).splitlines() if line]
        if len(paths) != 1 or not paths[0].startswith("package:"):
            raise ValidationError("installed package does not have exactly one base APK")
        remote = paths[0][len("package:"):]
        if REMOTE_APK.fullmatch(remote) is None or any(
                segment in ("", ".", "..") for segment in remote.split("/")[1:]):
            raise ValidationError("installed package path is not a canonical base APK path")
        with tempfile.TemporaryDirectory(prefix="e87-installed-apk-") as temporary:
            pulled = Path(temporary) / "base.apk"
            _run_adb(
                adb,
                serial,
                ["pull", remote, os.fspath(pulled)],
                "pull",
                timeout=180,
            )
            if not pulled.is_file() or pulled.is_symlink():
                raise ValidationError("adb pull did not produce a regular base APK")
            with _snapshot_apk(pulled) as installed_snapshot:
                installed_sha = installed_snapshot.sha256
                if installed_sha != expected["apkSha256"]:
                    raise ValidationError("installed base APK differs from the audited APK")
                installed = _audit_snapshot(
                    installed_snapshot,
                    arguments.release,
                    arguments.aapt,
                    arguments.dexdump,
                )
    if installed != expected:
        raise ValidationError("installed APK audit differs from the pre-install audit")
    receipt = {
        "apkAudit": installed,
        "expectedApkSha256": expected["apkSha256"],
        "installedApkSha256": installed_sha,
        "package": PACKAGE,
        "schemaId": "e87-android-installed-audit-v1",
        "schemaVersion": 1,
        "serial": serial,
    }
    if arguments.receipt is not None:
        write_receipt(arguments.receipt, receipt)
    return receipt


def parser(description: str) -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=description)
    result.add_argument("--serial", required=True)
    result.add_argument("--apk", required=True, type=Path)
    result.add_argument("--release", required=True, type=Path)
    result.add_argument("--aapt", required=True, type=Path)
    result.add_argument("--dexdump", required=True, type=Path)
    result.add_argument("--adb", required=True, type=Path)
    result.add_argument("--receipt", type=Path)
    return result


def run(function, description: str, argv: Sequence[str] | None = None) -> int:
    arguments = parser(description).parse_args(argv)
    try:
        receipt = function(arguments)
    except (OSError, ValidationError) as error:
        print(f"e87-device: {error}", file=os.sys.stderr)
        return 2
    print(_canonical(receipt).decode("ascii"), end="")
    return 0
