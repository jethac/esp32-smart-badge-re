#!/usr/bin/env python3
"""Offline APK audit for one exact E87 Android firmware handoff."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

try:
    from .e87_build import (
        DEX_CANDIDATE,
        DEX_NAME,
        RECEIPT_NAME as BUILD_RECEIPT_NAME,
        validate_build_authorization,
    )
    from .e87_embed import (
        ValidationError,
        _canonical,
        _sha,
        validate_release,
    )
    from .e87_surface import (
        RECEIPT_NAME as SURFACE_RECEIPT_NAME,
        validate_surface,
    )
except ImportError:
    from e87_build import (
        DEX_CANDIDATE,
        DEX_NAME,
        RECEIPT_NAME as BUILD_RECEIPT_NAME,
        validate_build_authorization,
    )
    from e87_embed import (
        ValidationError,
        _canonical,
        _sha,
        validate_release,
    )
    from e87_surface import (
        RECEIPT_NAME as SURFACE_RECEIPT_NAME,
        validate_surface,
    )


APPLICATION_ID = "net.jethachan.factory_badges"
MIN_SDK = 31
TARGET_SDK = 34
ALLOWED_PERMISSIONS = (
    "android.permission.BLUETOOTH_CONNECT",
    "android.permission.BLUETOOTH_SCAN",
    "android.permission.FOREGROUND_SERVICE",
    "android.permission.FOREGROUND_SERVICE_CONNECTED_DEVICE",
    "android.permission.POST_NOTIFICATIONS",
)
APP_DESCRIPTOR_PREFIX = "Lnet/jethachan/factory_badges/"
FORBIDDEN_APP_REFERENCES = (
    "Ljava/net/",
    "Ljavax/net/",
    "Lokhttp",
    "Landroid/provider/MediaStore",
    "Landroid/content/ContentResolver",
    "ACTION_OPEN_DOCUMENT",
    "ACTION_OPEN_DOCUMENT_TREE",
    "ACTION_GET_CONTENT",
    "MANAGE_EXTERNAL_STORAGE",
    "READ_EXTERNAL_STORAGE",
    "WRITE_EXTERNAL_STORAGE",
    "Ldalvik/system/DexClassLoader",
    "Ldalvik/system/PathClassLoader",
    "BluetoothOTAManager",
)
SURFACE_RECEIPT = Path(__file__).resolve().with_name(SURFACE_RECEIPT_NAME)
BUILD_RECEIPT = Path(__file__).resolve().with_name(BUILD_RECEIPT_NAME)
SOURCE_ROOT = Path(__file__).resolve().parents[1] / "app/src/main/java"
MAX_APK_SNAPSHOT = 512 * 1024 * 1024
SEALED_EXEC = Path(__file__).resolve().with_name("e87_sealed_exec.py")
UNSHARE = Path("/usr/bin/unshare")
SEALED_MOUNT_ROOT = Path("/mnt")
SEALED_PROJECTION = SEALED_MOUNT_ROOT / "e87-controller-snapshot.apk"


@dataclass(frozen=True)
class _ApkSnapshot:
    data: bytes
    path: Path
    pass_fds: tuple[int, ...]
    sealed_path: Path
    sha256: str

    def verify_projection(self) -> None:
        try:
            projected = self.sealed_path.read_bytes()
        except OSError as error:
            raise ValidationError("sealed APK snapshot is unavailable") from error
        if projected != self.data:
            raise ValidationError("sealed APK projection changed during audit")


@contextmanager
def _sealed_linux_projection(data: bytes) -> Iterator[_ApkSnapshot]:
    if not sys.platform.startswith("linux") or not hasattr(os, "memfd_create"):
        raise ValidationError("kernel-sealed APK snapshots require a Linux host")
    _validate_sealed_anchor()
    try:
        import fcntl
        add_seals = fcntl.F_ADD_SEALS
        seals = (
            fcntl.F_SEAL_SEAL
            | fcntl.F_SEAL_SHRINK
            | fcntl.F_SEAL_GROW
            | fcntl.F_SEAL_WRITE
        )
        flags = os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING
    except (AttributeError, ImportError) as error:
        raise ValidationError("Linux sealed-memory support is unavailable") from error
    try:
        descriptor = os.memfd_create("e87-controller.apk", flags=flags)
    except OSError as error:
        raise ValidationError("sealed APK snapshot creation failed") from error
    try:
        try:
            remaining = memoryview(data)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError("short APK snapshot write")
                remaining = remaining[written:]
            os.fsync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            fcntl.fcntl(descriptor, add_seals, seals)
        except OSError as error:
            raise ValidationError("sealed APK snapshot initialization failed") from error
        snapshot = _ApkSnapshot(
            data=data,
            path=SEALED_PROJECTION,
            pass_fds=(descriptor,),
            sealed_path=Path(f"/proc/self/fd/{descriptor}"),
            sha256=_sha(data),
        )
        snapshot.verify_projection()
        yield snapshot
        snapshot.verify_projection()
    finally:
        os.close(descriptor)


@contextmanager
def _snapshot_apk(apk: Path) -> Iterator[_ApkSnapshot]:
    source = _regular_absolute(Path(apk), "APK")
    if source.stat().st_size > MAX_APK_SNAPSHOT:
        raise ValidationError("APK exceeds snapshot cap")
    try:
        data = source.read_bytes()
    except OSError as error:
        raise ValidationError("APK snapshot read failed") from error
    if not data or len(data) > MAX_APK_SNAPSHOT:
        raise ValidationError("APK snapshot is empty or exceeds cap")
    with _sealed_linux_projection(data) as snapshot:
        yield snapshot


def _regular_absolute(path: Path, label: str, *, executable: bool = False) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise ValidationError(f"{label} path must be absolute")
    cursor = Path(candidate.anchor)
    for component in candidate.parts[1:]:
        cursor /= component
        try:
            mode = cursor.lstat().st_mode
        except FileNotFoundError as error:
            raise ValidationError(f"{label} does not exist") from error
        if stat.S_ISLNK(mode):
            raise ValidationError(f"{label} path contains a symlink")
    if not candidate.is_file():
        raise ValidationError(f"{label} must be a regular file")
    if executable and not os.access(candidate, os.X_OK):
        raise ValidationError(f"{label} must be executable")
    return candidate


def _validate_sealed_anchor() -> None:
    if os.geteuid() == 0:
        raise ValidationError("sealed APK execution requires an unprivileged host user")
    for candidate, label in ((Path("/"), "root"), (SEALED_MOUNT_ROOT, "mount")):
        try:
            metadata = candidate.lstat()
        except OSError as error:
            raise ValidationError(f"sealed APK {label} anchor is unavailable") from error
        if (not stat.S_ISDIR(metadata.st_mode)
                or candidate.is_symlink()
                or metadata.st_uid != 0
                or metadata.st_mode & 0o022):
            raise ValidationError(
                f"sealed APK {label} anchor must be a root-owned non-writable directory")
    if SEALED_PROJECTION.exists() or SEALED_PROJECTION.is_symlink():
        raise ValidationError("sealed APK projection name already exists on the host")


def _sealed_command(
        executable: Path,
        arguments: list[str],
        snapshot: _ApkSnapshot,
) -> tuple[list[str], tuple[int, ...]]:
    _validate_sealed_anchor()
    unshare = _regular_absolute(UNSHARE, "unshare", executable=True)
    interpreter = _regular_absolute(Path(sys.executable), "Python", executable=True)
    runner = _regular_absolute(SEALED_EXEC, "sealed exec helper")
    if len(snapshot.pass_fds) != 1:
        raise ValidationError("sealed APK snapshot has an invalid descriptor set")
    projection = os.fspath(snapshot.path)
    if projection not in arguments:
        raise ValidationError("subprocess does not consume the sealed APK projection")
    descriptor = snapshot.pass_fds[0]
    return ([
        os.fspath(unshare),
        "--user",
        "--map-root-user",
        "--mount",
        "--",
        os.fspath(interpreter),
        os.fspath(runner),
        str(descriptor),
        projection,
        str(len(snapshot.data)),
        snapshot.sha256,
        "--",
        os.fspath(executable),
        *arguments,
    ], snapshot.pass_fds)


def _run(
        tool: Path,
        arguments: list[str],
        label: str,
        *,
        snapshot: _ApkSnapshot | None = None,
) -> str:
    command = [os.fspath(tool), *arguments]
    options: dict[str, object] = {}
    if snapshot is not None:
        if os.name != "posix":
            raise ValidationError(f"{label} cannot inherit the sealed APK snapshot")
        command, pass_fds = _sealed_command(tool, arguments, snapshot)
        options["pass_fds"] = pass_fds
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=90,
            **options,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValidationError(f"{label} execution failed") from error
    if completed.returncode != 0:
        raise ValidationError(f"{label} exited {completed.returncode}")
    if len(completed.stdout) > 64 * 1024 * 1024:
        raise ValidationError(f"{label} output exceeds cap")
    try:
        return completed.stdout.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValidationError(f"{label} output is not UTF-8") from error


def _dex_rank(name: str) -> int:
    suffix = name[len("classes"):-len(".dex")]
    return 1 if suffix == "" else int(suffix)


def _audit_zip(
        apk_bytes: bytes, release,
) -> tuple[list[dict[str, object]], str, tuple[str, ...]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(apk_bytes))
    except (OSError, zipfile.BadZipFile) as error:
        raise ValidationError("APK is not a valid ZIP container") from error
    with archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ValidationError("APK has duplicate ZIP entries")
        for name in names:
            if (not name or name.startswith(("/", "\\")) or "\\" in name
                    or any(segment in ("", ".", "..") for segment in name.split("/"))):
                if not name.endswith("/"):
                    raise ValidationError("APK has a noncanonical ZIP path")
        dex_candidates = tuple(name for name in names if DEX_CANDIDATE.fullmatch(name))
        if any(DEX_NAME.fullmatch(name) is None for name in dex_candidates):
            raise ValidationError("APK contains a noncanonical DEX entry name")
        if "AndroidManifest.xml" not in names or not dex_candidates:
            raise ValidationError("APK lacks its manifest or DEX")
        dex_entries = tuple(sorted(
            dex_candidates,
            key=_dex_rank,
        ))
        canonical_dex_entries = tuple(
            "classes.dex" if index == 1 else f"classes{index}.dex"
            for index in range(1, len(dex_entries) + 1)
        )
        if dex_entries != canonical_dex_entries:
            raise ValidationError("APK DEX inventory is not closed")
        if any(name.startswith("assets/flutter_assets/") for name in names):
            raise ValidationError("APK contains a Flutter asset surface")
        if any(name.startswith("lib/") for name in names):
            raise ValidationError("APK contains unapproved native code")

        root = str(release.receipt["releaseRoot"])
        expected = {"assets/e87/default-release.json"}
        expected.update(
            f"assets/e87/{root}/{record['filename']}" for record in release.records)
        actual = {name for name in names if name.startswith("assets/e87/")}
        if actual != expected:
            raise ValidationError("APK E87 asset inventory is not closed")
        index = archive.read("assets/e87/default-release.json")
        if index != release.receipt_bytes:
            raise ValidationError("APK embedded receipt differs from reviewed handoff")
        projection: list[dict[str, object]] = [
            {"path": "e87/default-release.json", "sha256": _sha(index)}
        ]
        for record in release.records:
            filename = str(record["filename"])
            entry = f"assets/e87/{root}/{filename}"
            info = archive.getinfo(entry)
            if info.file_size != record["length"]:
                raise ValidationError("APK embedded file length differs from handoff")
            data = archive.read(entry)
            if data != release.files[filename]:
                raise ValidationError("APK embedded bytes differ from reviewed handoff")
            projection.append({
                "path": f"e87/{root}/{filename}",
                "sha256": _sha(data),
            })
        return projection, _sha(_canonical(projection)), dex_entries


def _audit_badging(output: str) -> tuple[int, int]:
    package = re.search(r"(?m)^package: name='([^']+)'", output)
    minimum = re.search(r"(?m)^sdkVersion:'([0-9]+)'$", output)
    target = re.search(r"(?m)^targetSdkVersion:'([0-9]+)'$", output)
    if package is None or package.group(1) != APPLICATION_ID:
        raise ValidationError("APK application ID is invalid")
    if minimum is None or int(minimum.group(1)) != MIN_SDK:
        raise ValidationError("APK minimum SDK is invalid")
    if target is None or int(target.group(1)) != TARGET_SDK:
        raise ValidationError("APK target SDK is invalid")
    return int(minimum.group(1)), int(target.group(1))


def _audit_permissions(output: str) -> tuple[str, ...]:
    values = re.findall(r"(?m)^uses-permission: name='([^']+)'$", output)
    if len(values) != len(set(values)) or tuple(sorted(values)) != ALLOWED_PERMISSIONS:
        raise ValidationError("APK effective permissions differ from the closed allowlist")
    return tuple(sorted(values))


def _audit_manifest_tree(output: str) -> None:
    lines = output.splitlines()
    name = '"net.jethachan.factory_badges.ui.MaintenanceActivity"'
    indices = [index for index, line in enumerate(lines)
               if "android:name" in line and name in line]
    if len(indices) != 1:
        raise ValidationError("APK must contain exactly one maintenance activity")
    name_index = indices[0]
    activity_index = -1
    activity_indent = -1
    for index in range(name_index - 1, -1, -1):
        stripped = lines[index].lstrip()
        if stripped.startswith("E: activity "):
            activity_index = index
            activity_indent = len(lines[index]) - len(stripped)
            break
    if activity_index < 0:
        raise ValidationError("maintenance activity XML block is malformed")
    block = []
    for index in range(activity_index, len(lines)):
        line = lines[index]
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if index > activity_index and stripped.startswith("E: ") and indent <= activity_indent:
            break
        block.append(line)
    text = "\n".join(block)
    if "android:exported" not in text or "(type 0x12)0x0" not in text:
        raise ValidationError("maintenance activity is not explicitly private")
    if "E: intent-filter" in text:
        raise ValidationError("maintenance activity has an intent filter")


def _audit_dex(output: str, dex_entries: tuple[str, ...],
               authorized_descriptors: tuple[str, ...]) -> None:
    opened = tuple(re.findall(
        r"(?m)^Opened '.*:([^/:']+\.dex)', DEX version '[0-9]+'$", output))
    if opened != dex_entries:
        raise ValidationError("dexdump did not inspect the complete closed DEX inventory")
    blocks = re.split(r"(?m)(?=^Class #[0-9]+\s+-)", output)
    app_classes = 0
    descriptors: list[str] = []
    for block in blocks:
        descriptor = re.search(r"Class descriptor\s+: '([^']+)'", block)
        if descriptor is None:
            continue
        name = descriptor.group(1)
        if name.startswith("Lcom/jieli/"):
            raise ValidationError("APK contains the unused vendor OTA class surface")
        if not name.startswith(APP_DESCRIPTOR_PREFIX):
            raise ValidationError("APK contains a class outside the closed controller namespace")
        app_classes += 1
        descriptors.append(name)
        for token in FORBIDDEN_APP_REFERENCES:
            if token in block:
                raise ValidationError(
                    f"application class {name} references forbidden surface {token}")
    if app_classes == 0:
        raise ValidationError("DEX audit found no controller application classes")
    if (len(descriptors) != len(set(descriptors))
            or tuple(sorted(descriptors)) != authorized_descriptors):
        raise ValidationError("APK class descriptors differ from the reviewed closed surface")


def _run_apk_tool(
        snapshot: _ApkSnapshot,
        tool: Path,
        arguments: list[str],
        label: str,
) -> str:
    snapshot.verify_projection()
    output = _run(tool, arguments, label, snapshot=snapshot)
    snapshot.verify_projection()
    return output


def _audit_snapshot(
        snapshot: _ApkSnapshot,
        release_root: Path,
        aapt: Path,
        dexdump: Path,
) -> dict[str, object]:
    aapt = _regular_absolute(aapt, "aapt", executable=True)
    dexdump = _regular_absolute(dexdump, "dexdump", executable=True)
    release = validate_release(Path(release_root))
    authorized_descriptors = validate_surface(SURFACE_RECEIPT, SOURCE_ROOT)
    authorized_dex = validate_build_authorization(
        BUILD_RECEIPT,
        snapshot.data,
        SURFACE_RECEIPT,
    )
    projection, tree_digest, dex_entries = _audit_zip(snapshot.data, release)
    apk_path = os.fspath(snapshot.path)
    min_sdk, target_sdk = _audit_badging(
        _run_apk_tool(snapshot, aapt, ["dump", "badging", apk_path], "aapt badging"))
    permissions = _audit_permissions(
        _run_apk_tool(
            snapshot, aapt, ["dump", "permissions", apk_path], "aapt permissions"))
    _audit_manifest_tree(_run_apk_tool(
        snapshot, aapt, ["dump", "xmltree", apk_path, "AndroidManifest.xml"],
        "aapt manifest"))
    _audit_dex(
        _run_apk_tool(snapshot, dexdump, ["-d", apk_path], "dexdump"),
        dex_entries,
        authorized_descriptors,
    )
    return {
        "applicationId": APPLICATION_ID,
        "apkSha256": snapshot.sha256,
        "authorizedBuildSha256": _sha(BUILD_RECEIPT.read_bytes()),
        "authorizedClassCount": len(authorized_descriptors),
        "authorizedDex": list(authorized_dex),
        "authorizedSurfaceSha256": _sha(SURFACE_RECEIPT.read_bytes()),
        "buildId": release.receipt["buildId"],
        "chip": release.receipt["chip"],
        "embeddedContent": projection,
        "embeddedIndexSha256": _sha(release.receipt_bytes),
        "embeddedTreeSha256": tree_digest,
        "labEligible": release.receipt["labEligible"],
        "layout": release.receipt["layout"],
        "minSdk": min_sdk,
        "permissions": list(permissions),
        "profile": release.receipt["profile"],
        "qixVersion": release.receipt["qixVersion"],
        "releaseEligible": release.receipt["releaseEligible"],
        "releaseRoot": release.receipt["releaseRoot"],
        "schemaId": "e87-android-apk-audit-v2",
        "schemaVersion": 2,
        "semver": release.receipt["semver"],
        "targetSdk": target_sdk,
    }


def audit_apk(apk: Path, release_root: Path, aapt: Path, dexdump: Path) -> dict[str, object]:
    with _snapshot_apk(apk) as snapshot:
        return _audit_snapshot(snapshot, release_root, aapt, dexdump)


def write_receipt(path: Path, value: dict[str, object]) -> None:
    destination = Path(path)
    if not destination.is_absolute():
        raise ValidationError("audit receipt path must be absolute")
    parent = destination.parent
    if parent.is_symlink() or not parent.is_dir():
        raise ValidationError("audit receipt parent must be a real directory")
    try:
        with destination.open("xb") as stream:
            stream.write(_canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ValidationError("audit receipt already exists") from error
    destination.chmod(0o444)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", required=True, type=Path)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--aapt", required=True, type=Path)
    parser.add_argument("--dexdump", required=True, type=Path)
    parser.add_argument("--receipt", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        receipt = audit_apk(
            arguments.apk, arguments.release, arguments.aapt, arguments.dexdump)
        if arguments.receipt is not None:
            write_receipt(arguments.receipt, receipt)
    except (OSError, ValidationError, zipfile.BadZipFile) as error:
        print(f"verify-apk: {error}", file=os.sys.stderr)
        return 2
    print(_canonical(receipt).decode("ascii"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
