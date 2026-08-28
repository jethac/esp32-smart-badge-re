#!/usr/bin/env python3
"""Project one sealed memfd onto a private read-only tmpfs, then exec a tool."""
from __future__ import annotations

import ctypes
import fcntl
import hashlib
import os
import stat
import sys
from pathlib import Path


MS_RDONLY = 1
MS_NOSUID = 2
MS_NODEV = 4
MS_NOEXEC = 8
MS_REMOUNT = 32
MOUNT_FLAGS = MS_NOSUID | MS_NODEV | MS_NOEXEC
SEALED_MOUNT_ROOT = Path("/mnt")
SEALED_PROJECTION = SEALED_MOUNT_ROOT / "e87-controller-snapshot.apk"
REQUIRED_SEALS = (
    fcntl.F_SEAL_SEAL
    | fcntl.F_SEAL_SHRINK
    | fcntl.F_SEAL_GROW
    | fcntl.F_SEAL_WRITE
)


def _fail(message: str) -> int:
    print(f"e87-sealed-exec: {message}", file=sys.stderr)
    return 125


def _descriptor_hash(descriptor: int, length: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while offset < length:
        chunk = os.pread(descriptor, min(1024 * 1024, length - offset), offset)
        if not chunk:
            raise OSError("sealed descriptor ended early")
        digest.update(chunk)
        offset += len(chunk)
    return digest.hexdigest().upper()


def _mount(
        source: bytes | None,
        target: Path,
        filesystem: bytes | None,
        flags: int,
        data: bytes | None,
) -> int:
    libc = ctypes.CDLL(None, use_errno=True)
    mount = libc.mount
    mount.argtypes = (
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_ulong,
        ctypes.c_char_p,
    )
    mount.restype = ctypes.c_int
    result = mount(source, os.fsencode(target), filesystem, flags, data)
    return 0 if result == 0 else ctypes.get_errno()


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) < 7 or arguments[4] != "--":
        return _fail("invalid invocation")
    try:
        descriptor = int(arguments[0], 10)
        expected_length = int(arguments[2], 10)
    except ValueError:
        return _fail("descriptor and length must be decimal integers")
    projection = Path(arguments[1])
    expected_sha = arguments[3]
    command = arguments[5:]
    if descriptor < 0 or expected_length <= 0:
        return _fail("descriptor or length is outside the closed range")
    if len(expected_sha) != 64 or any(
            character not in "0123456789ABCDEF" for character in expected_sha):
        return _fail("expected SHA-256 is not canonical")
    if not projection.is_absolute() or not command or not Path(command[0]).is_absolute():
        return _fail("projection and executable paths must be absolute")
    if os.fspath(projection) not in command[1:]:
        return _fail("tool command does not consume the sealed projection")
    parent = projection.parent
    try:
        parent_mode = parent.lstat().st_mode
        descriptor_stat = os.fstat(descriptor)
        actual_seals = fcntl.fcntl(descriptor, fcntl.F_GET_SEALS)
        actual_sha = _descriptor_hash(descriptor, expected_length)
    except OSError as error:
        return _fail(f"sealed descriptor validation failed: {error}")
    if (projection != SEALED_PROJECTION or parent != SEALED_MOUNT_ROOT
            or not stat.S_ISDIR(parent_mode) or parent.is_symlink()
            or parent_mode & 0o022
            or projection.exists() or projection.is_symlink()):
        return _fail("projection must be absent below the fixed protected mount anchor")
    if not stat.S_ISREG(descriptor_stat.st_mode):
        return _fail("sealed descriptor is not a regular file")
    if descriptor_stat.st_size != expected_length or actual_sha != expected_sha:
        return _fail("sealed descriptor bytes differ from the authorized snapshot")
    if actual_seals & REQUIRED_SEALS != REQUIRED_SEALS:
        return _fail("sealed descriptor lacks the required immutable seals")
    mount_size = max(1024 * 1024, expected_length + 1024 * 1024)
    mount_error = _mount(
        b"tmpfs",
        parent,
        b"tmpfs",
        MOUNT_FLAGS,
        f"size={mount_size},mode=0700".encode("ascii"),
    )
    if mount_error:
        return _fail(f"private tmpfs mount failed with errno {mount_error}")
    try:
        with projection.open("xb") as stream:
            offset = 0
            while offset < expected_length:
                chunk = os.pread(
                    descriptor,
                    min(1024 * 1024, expected_length - offset),
                    offset,
                )
                if not chunk:
                    raise OSError("sealed descriptor ended early during projection")
                stream.write(chunk)
                offset += len(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        projection.chmod(0o400)
        mounted_stat = projection.stat()
        with projection.open("rb") as stream:
            mounted_sha = hashlib.sha256(stream.read()).hexdigest().upper()
    except OSError as error:
        return _fail(f"sealed projection validation failed: {error}")
    if mounted_stat.st_size != expected_length or mounted_sha != expected_sha:
        return _fail("sealed projection bytes differ from the authorized snapshot")
    remount_error = _mount(
        None,
        parent,
        None,
        MS_REMOUNT | MS_RDONLY | MOUNT_FLAGS,
        None,
    )
    if remount_error:
        return _fail(f"private tmpfs read-only remount failed with errno {remount_error}")
    try:
        descriptor_to_close = os.open(projection, os.O_WRONLY)
    except OSError:
        pass
    else:
        os.close(descriptor_to_close)
        return _fail("read-only sealed projection unexpectedly accepted a writer")
    try:
        os.execv(command[0], command)
    except OSError as error:
        return _fail(f"tool exec failed: {error}")


if __name__ == "__main__":
    raise SystemExit(main())
