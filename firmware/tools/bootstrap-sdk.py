#!/usr/bin/env python3
"""Fail-closed offline SDK materialization for E87 Stage 0-H."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import zlib
from pathlib import Path, PurePosixPath
from typing import Iterable


TOOLCHAIN_ROOT = Path("/home/jethac/.local/share/e87-dev/jieli")
POST_BUILD_ROOT = Path("/home/jethac/.local/share/e87-dev/jieli-post-build")
GIT_CONFIG_PREFIX = (
    "-c", "core.fsmonitor=false", "-c", "core.attributesFile=/dev/null",
    "-c", "tar.umask=0002",
)
GIT_ENV = {
    "GIT_ATTR_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "HOME": "/dev/null",
    "LANG": "C",
    "LC_ALL": "C",
    "TZ": "UTC",
    "XDG_CONFIG_HOME": "/dev/null",
}
COMMAND_ROLES = (
    "git-version",
    "source-before-head", "source-before-tree", "source-before-status", "source-before-index",
    "source-before-head-index-diff", "source-before-worktree-index-diff", "source-before-commit-object",
    "sdk-before-head", "sdk-before-tree", "sdk-before-status", "sdk-before-index",
    "sdk-before-head-index-diff", "sdk-before-worktree-index-diff",
    "sdk-archive", "sdk-archive-confirm", "patch-check", "patch-apply",
    "source-after-head", "source-after-tree", "source-after-status", "source-after-index",
    "source-after-head-index-diff", "source-after-worktree-index-diff", "source-after-commit-object",
    "sdk-after-head", "sdk-after-tree", "sdk-after-status", "sdk-after-index",
    "sdk-after-head-index-diff", "sdk-after-worktree-index-diff",
)
VALIDATIONS = {name: True for name in (
    "archiveInventory", "gitToolIdentity", "outputRoot", "outputTree", "overlayInputs",
    "patchContract", "protectedRoots", "sdkClean", "sdkIdentity", "sdkStable",
    "sourceClean", "sourceIdentity", "sourceStable",
)}
LOCK_DIGESTS = {
    "model1552-package.lock.json": "EFD3878979F029C56DA16E863EB89955E22D9B222046211A84AAC7BE1F3BA122",
    "packaging.lock.json": "28E6C1DEF70F894F89FDC7FFB8527F204688888C58EEDC052CD8A36F3AEBC003",
    "toolchain.lock.json": "60D72D942FC66E89303FD059AC9904F9167AAB743A21E78AB7230AA6B5B2300D",
}
OVERLAY_SOURCES = (
    "firmware/overlay/SDK/apps/watch/include/e87/e87_stage0_adv.h",
    "firmware/overlay/SDK/apps/watch/include/e87/e87_stage0_app.h",
    "firmware/overlay/SDK/apps/watch/e87/e87_stage0_adv.c",
    "firmware/overlay/SDK/apps/watch/e87/e87_stage0_app.c",
    "firmware/overlay/SDK/apps/watch/e87/e87_stage0_ble.c",
    "firmware/overlay/SDK/apps/watch/board/br35/board_e87_1542/board_e87_1542.c",
    "firmware/overlay/SDK/apps/watch/board/br35/board_e87_1542/board_e87_1542_cfg.h",
)
PATCH_TARGETS = (
    "SDK/apps/watch/board/br35/board_config.h",
    "SDK/apps/watch/include/app_config.h",
    "SDK/apps/watch/app_main.c",
    "SDK/build/genFileList.c",
    "SDK/build/Makefile.mk",
)
PATCH_RELATIVE = "firmware/patches/stage0/0001-e87-stage0-hooks.patch"
SDK_ARCHIVE_SHA256 = "63FC570329AECE5032C3968B2C7EEA636E16F6322990E9578F330CD5A8DA8A35"
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9A-F]{64}\Z")


def _system_runner(argv, **kwargs):
    return subprocess.run(argv, **kwargs)


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest().upper()


def _open_directory_fd(path: Path) -> tuple[int, tuple[int, int, int]]:
    directory = Path(path)
    _reject_symlink_components(directory)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(directory, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("parent descriptor is not a directory")
        return descriptor, (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode))
    except BaseException:
        os.close(descriptor)
        raise


def _verify_directory_fd(path: Path, descriptor: int, identity: tuple[int, int, int]) -> None:
    held = os.fstat(descriptor)
    lexical = Path(path).lstat()
    held_identity = (held.st_dev, held.st_ino, stat.S_IFMT(held.st_mode))
    lexical_identity = (lexical.st_dev, lexical.st_ino, stat.S_IFMT(lexical.st_mode))
    if held_identity != identity or lexical_identity != identity or not stat.S_ISDIR(lexical.st_mode):
        raise ValueError("directory binding changed during use")


def _write_new_file_at(parent: Path, parent_fd: int, parent_identity: tuple[int, int, int], name: str, data: bytes) -> None:
    if not isinstance(name, str) or not name or name in (".", "..") or "/" in name or "\\" in name:
        raise ValueError("invalid child name")
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    _verify_directory_fd(parent, parent_fd, parent_identity)
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_fd,
        )
    except FileExistsError as error:
        raise ValueError("target already exists") from error
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            os.unlink(name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        raise


def write_new_file(path: Path, data: bytes) -> None:
    target = Path(path)
    parent_fd, parent_identity = _open_directory_fd(target.parent)
    try:
        _write_new_file_at(target.parent, parent_fd, parent_identity, target.name, data)
    finally:
        os.close(parent_fd)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _reject_symlink_components(path: Path) -> None:
    value = Path(path)
    if not value.is_absolute():
        raise ValueError("path must be absolute")
    cursor = Path(value.anchor)
    for part in value.parts[1:]:
        cursor /= part
        if cursor.exists() or cursor.is_symlink():
            if stat.S_ISLNK(cursor.lstat().st_mode):
                raise ValueError(f"symlink path component: {cursor}")


def _closed_relative(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\0" in value or "\\" in value:
        raise ValueError("invalid relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("invalid relative path")
    return path


def _validate_real_directory(path: Path, label: str) -> Path:
    value = Path(path)
    _reject_symlink_components(value)
    if not value.exists() or not value.is_dir():
        raise ValueError(f"{label} must be an existing real directory")
    resolved = value.resolve(strict=True)
    if resolved == Path(resolved.anchor):
        raise ValueError(f"{label} may not be the filesystem root")
    return resolved


def _validate_disjoint(paths: Iterable[Path]) -> None:
    values = list(paths)
    for index, first in enumerate(values):
        for second in values[index + 1:]:
            if _is_relative_to(first, second) or _is_relative_to(second, first):
                raise ValueError("protected roots must be pairwise disjoint")


def validate_output_root(root: Path, forbidden_roots: Iterable[Path]) -> Path:
    output = _validate_real_directory(Path(root), "output root")
    protected = [_validate_real_directory(Path(item), "protected root") for item in forbidden_roots]
    _validate_disjoint([output, *protected])
    if any(output.iterdir()):
        raise ValueError("output root must be empty")
    return output


def _directory_identity(path: Path) -> tuple[int, int, int]:
    info = Path(path).lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ValueError("directory identity was rebound")
    return (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode))


def _parent_identity(path: Path) -> tuple[int, int, int, int]:
    info = Path(path).parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ValueError("directory parent identity was rebound")
    return (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode), info.st_ctime_ns)


def _validate_receipt_path(path: Path, protected: Iterable[Path]) -> Path:
    target = Path(path)
    if not target.is_absolute():
        raise ValueError("receipt path must be absolute")
    _reject_symlink_components(target.parent)
    parent = target.parent
    if not parent.exists() or not parent.is_dir():
        raise ValueError("receipt parent must be an existing directory")
    if target.exists() or target.is_symlink():
        raise ValueError("receipt target must not exist")
    parent_resolved = parent.resolve(strict=True)
    roots = [Path(item).resolve(strict=True) for item in protected]
    for root in roots:
        if _is_relative_to(parent_resolved, root) or _is_relative_to(root, parent_resolved):
            raise ValueError("receipt path overlaps a protected root")
    return target


def _safe_controller_tree(repository: Path) -> None:
    for child in repository.iterdir():
        if not child.name.startswith(".superpowers"):
            continue
        if child.name != ".superpowers" or child.is_symlink() or not child.is_dir():
            raise ValueError("invalid controller-only tree")
        for entry in child.rglob("*"):
            mode = entry.lstat().st_mode
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise ValueError("controller-only tree contains a link or special file")


def _parse_local_config(root: Path, label: str) -> None:
    config = root / ".git/config"
    if config.is_symlink() or not config.is_file():
        raise ValueError("missing or indirect Git config")
    data = config.read_bytes()
    if b"\0" in data or b"\r" in data or any(byte < 0x20 and byte not in (0x09, 0x0A) for byte in data):
        raise ValueError("invalid Git config control byte")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("invalid Git config encoding") from error
    entries = []
    section = None
    for line in text.splitlines():
        if not line or line.lstrip().startswith(("#", ";")):
            continue
        if line.rstrip().endswith("\\"):
            raise ValueError("continued Git config values are forbidden")
        if line.startswith("["):
            match = re.fullmatch(r'\[([A-Za-z][A-Za-z0-9.-]*)(?: "([^"\n]+)")?\]', line.strip())
            if match is None:
                raise ValueError("malformed Git config section")
            section = (match.group(1).lower(), match.group(2))
            continue
        if section is None:
            raise ValueError("Git config value outside a section")
        match = re.fullmatch(r"[ \t]*([A-Za-z][A-Za-z0-9.-]*)[ \t]*=[ \t]*(.*)", line)
        if match is None:
            raise ValueError("malformed Git config value")
        value = match.group(2).strip()
        entries.append((section[0], section[1], match.group(1).lower(), value))
    common = {
        ("core", None, "repositoryformatversion", "0"),
        ("core", None, "filemode", "true"),
        ("core", None, "bare", "false"),
        ("core", None, "logallrefupdates", "true"),
    }
    if label == "source":
        expected = common | {
            ("user", None, "email", "jethachan@gmail.com"),
            ("user", None, "name", "Jetha Chan"),
            ("remote", "bootstrap", "url", "/home/jethac/.cache/codex-transfer/factory-android-badges-e87.bundle"),
            ("remote", "bootstrap", "fetch", "+refs/heads/*:refs/remotes/bootstrap/*"),
            ("remote", "origin", "url", "https://github.com/jethac/factory-android-badges.git"),
            ("remote", "origin", "fetch", "+refs/heads/*:refs/remotes/origin/*"),
            ("branch", "codex/e87-local-rendering", "remote", "bootstrap"),
            ("branch", "codex/e87-local-rendering", "merge", "refs/heads/codex/e87-local-rendering"),
        }
    elif label == "sdk":
        expected = common | {
            ("remote", "origin", "url", "https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200.git"),
            ("remote", "origin", "fetch", "+refs/heads/main:refs/remotes/origin/main"),
            ("branch", "main", "remote", "origin"),
            ("branch", "main", "merge", "refs/heads/main"),
        }
    else:
        raise ValueError("unknown repository role")
    if len(entries) != len(expected) or set(entries) != expected:
        raise ValueError("Git config is outside the closed repository profile")


def _validate_git_admin(root: Path, label: str, expected_commit: str) -> None:
    git_dir = root / ".git"
    _reject_symlink_components(git_dir)
    if not git_dir.is_dir():
        raise ValueError("worktree .git must be a real directory")
    for forbidden in (git_dir / "commondir", git_dir / "objects/info/alternates"):
        if forbidden.exists() or forbidden.is_symlink():
            raise ValueError("Git indirection is forbidden")
    for entry in git_dir.rglob("*"):
        mode = entry.lstat().st_mode
        if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError("Git administration contains a link or special file")
    _parse_local_config(root, label)
    index = git_dir / "index"
    if index.is_symlink() or not index.is_file():
        raise ValueError("Git index must be a regular file")
    for forbidden in (
        git_dir / "info/sparse-checkout", git_dir / "info/attributes",
        git_dir / "info/grafts",
    ):
        if forbidden.exists() or forbidden.is_symlink():
            raise ValueError("forbidden Git-local state")
    shallow = git_dir / "shallow"
    if label == "source":
        if shallow.exists() or shallow.is_symlink():
            raise ValueError("source repository may not be shallow")
    elif shallow.exists() or shallow.is_symlink():
        if shallow.is_symlink() or not shallow.is_file() or shallow.read_bytes() != (expected_commit + "\n").encode("ascii"):
            raise ValueError("SDK shallow boundary drift")


def _critical_git_snapshot(root: Path) -> tuple[tuple[object, ...], ...]:
    paths = (
        root / ".git", root / ".git/index", root / ".git/shallow",
        root / ".git/info", root / ".git/info/attributes", root / ".git/info/grafts",
        root / ".git/commondir", root / ".git/objects/info",
        root / ".git/objects/info/alternates",
    )
    records = []
    for path in paths:
        if not (path.exists() or path.is_symlink()):
            records.append((str(path), "absent"))
            continue
        info = path.lstat()
        digest = _sha256_file(path) if stat.S_ISREG(info.st_mode) else None
        records.append((str(path), info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_ctime_ns, digest))
    return tuple(records)


def _identity_snapshot(root: Path, *, ignore_controller: bool) -> tuple[tuple[object, ...], ...]:
    records = []
    for entry in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = entry.relative_to(root).as_posix()
        if relative == ".git" or relative.startswith(".git/"):
            continue
        if ignore_controller and (relative == ".superpowers" or relative.startswith(".superpowers/")):
            continue
        info = entry.lstat()
        if stat.S_ISLNK(info.st_mode):
            content = "L:" + os.readlink(entry)
        elif stat.S_ISREG(info.st_mode):
            content = "F:" + _sha256_file(entry)
        elif stat.S_ISDIR(info.st_mode):
            content = "D"
        else:
            content = "S"
        records.append((relative, info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns, content))
    return tuple(records)


def _path_token(path: Path) -> tuple[object, ...]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("input must remain a regular file")
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns, _sha256_file(path))


def _regular_repository_file(repository: Path, relative: str) -> Path:
    rel = _closed_relative(relative)
    path = repository.joinpath(*rel.parts)
    _reject_symlink_components(path)
    if not path.is_file() or not _is_relative_to(path.resolve(strict=True), repository):
        raise ValueError("repository input must be a contained regular file")
    return path


def _patch_paths(data: bytes) -> set[str]:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ValueError("patch must be UTF-8") from error
    blocks = []
    current = None
    forbidden_directives = ("rename from ", "rename to ", "copy from ", "copy to ", "new file mode ", "deleted file mode ", "old mode ", "new mode ", "GIT binary patch", "Binary files ")
    for line in lines:
        if line.startswith("diff --git "):
            if current is not None:
                blocks.append(current)
            fields = line.split(" ")
            if len(fields) != 4 or not fields[2].startswith("a/") or not fields[3].startswith("b/"):
                raise ValueError("malformed diff header")
            left = _closed_relative(fields[2][2:]).as_posix()
            right = _closed_relative(fields[3][2:]).as_posix()
            if left != right:
                raise ValueError("patch rename is forbidden")
            current = {"path": left, "old": [], "new": []}
            continue
        if current is None:
            if line:
                raise ValueError("content outside patch block")
            continue
        if line.startswith(forbidden_directives):
            raise ValueError("patch metadata/binary changes are forbidden")
        if line.startswith("--- "):
            current["old"].append(line[4:].split("\t", 1)[0])
        elif line.startswith("+++ "):
            current["new"].append(line[4:].split("\t", 1)[0])
    if current is not None:
        blocks.append(current)
    if not blocks:
        raise ValueError("patch contains no blocks")
    seen = set()
    for block in blocks:
        path = block["path"]
        if path in seen or block["old"] != ["a/" + path] or block["new"] != ["b/" + path]:
            raise ValueError("patch block does not bind one unchanged path")
        seen.add(path)
    return seen


def _git_command(root: Path, *args: str) -> list[str]:
    return [
        "/usr/bin/git", *GIT_CONFIG_PREFIX,
        "--git-dir", str(root / ".git"), "--work-tree", str(root), *args,
    ]


def _validate_git_tool(git_tool: dict[str, str]) -> None:
    if not isinstance(git_tool, dict) or set(git_tool) != {"path", "sha256", "version"}:
        raise ValueError("invalid Git tool identity")
    if git_tool != {
        "path": "/usr/bin/git",
        "sha256": "587EF21868C948B883993E23209B86A72A6DDC06AAB1545C697FFC31075ACD4A",
        "version": "2.34.1",
    }:
        raise ValueError("Git tool identity is not the reviewed pin")
    path = Path(git_tool["path"])
    _reject_symlink_components(path)
    if not path.is_file() or _sha256_file(path) != git_tool["sha256"]:
        raise ValueError("Git executable identity drift")


def _run(trace, role: str, runner, argv: list[str], cwd: Path, git_tool: dict[str, str], *, input_bytes: bytes | None = None):
    _validate_git_tool(git_tool)
    environment = dict(GIT_ENV)
    options = {
        "cwd": cwd,
        "env": environment,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "check": False,
        "shell": False,
    }
    if input_bytes is None:
        options["stdin"] = subprocess.DEVNULL
    else:
        environment["GIT_CEILING_DIRECTORIES"] = str(cwd)
        options["input"] = input_bytes
    result = runner(list(argv), **options)
    if not isinstance(getattr(result, "returncode", None), int) or isinstance(result.returncode, bool):
        raise ValueError("runner returned an invalid exit code")
    if not isinstance(getattr(result, "stdout", None), bytes) or not isinstance(getattr(result, "stderr", None), bytes):
        raise ValueError("runner streams must be bytes")
    trace.append((role, list(argv), dict(options), result))
    if result.returncode != 0:
        raise ValueError(f"command failed: {role}")
    combined = (result.stdout + result.stderr).lower()
    if any(token in combined for token in (b"password", b"username", b"connect usb", b"select a device")):
        raise ValueError("interactive process output is forbidden")
    return result


def _decode_line(data: bytes, label: str) -> str:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError(f"non-ASCII {label}") from error
    if not text.endswith("\n") or text.count("\n") != 1 or "\r" in text:
        raise ValueError(f"noncanonical {label}")
    return text[:-1]


def _parse_index(data: bytes, root: Path) -> None:
    if not data.endswith(b"\0"):
        raise ValueError("Git index listing lacks its NUL terminator")
    records = data[:-1].split(b"\0") if data[:-1] else []
    tracked = {}
    for raw in records:
        try:
            prefix, name = raw.split(b"\t", 1)
            prefix_text = prefix.decode("ascii")
            relative = name.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as error:
            raise ValueError("malformed Git index listing") from error
        if not prefix_text.startswith("H ") or not re.fullmatch(r"H 100(644|755) [0-9a-f]{40} 0", prefix_text):
            raise ValueError("unsupported Git index flags/mode/stage")
        path = _closed_relative(relative).as_posix()
        if path in tracked:
            raise ValueError("duplicate Git index path")
        mode_text, object_id, stage = prefix_text[2:].split(" ")
        tracked[path] = (mode_text, object_id)
    present = {}
    for entry in root.rglob("*"):
        relative = entry.relative_to(root).as_posix()
        if relative == ".git" or relative.startswith(".git/") or relative == ".superpowers" or relative.startswith(".superpowers/"):
            continue
        mode = entry.lstat().st_mode
        if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError("worktree contains a link or special file")
        if stat.S_ISREG(mode):
            expected_mode = "100755" if stat.S_IMODE(mode) & 0o111 else "100644"
            data_bytes = entry.read_bytes()
            object_id = hashlib.sha1(b"blob " + str(len(data_bytes)).encode("ascii") + b"\0" + data_bytes).hexdigest()
            present[relative] = (expected_mode, object_id)
    if present != tracked:
        raise ValueError("worktree inventory differs from the Git index")


def _repository_checks(trace, phase: str, label: str, root: Path, runner, git_tool, expected_commit: str, expected_tree: str, *, commit_object: bool):
    results = {}
    specifications = [
        ("head", ("rev-parse", "HEAD")),
        ("tree", ("rev-parse", "HEAD^{tree}")),
        ("status", ("status", "--porcelain=v1", "--untracked-files=no")),
        ("index", ("ls-files", "-v", "--stage", "-z", "--")),
        ("head-index-diff", ("diff", "--no-ext-diff", "--no-textconv", "--exit-code", "--cached", "HEAD", "--")),
        ("worktree-index-diff", ("diff", "--no-ext-diff", "--no-textconv", "--exit-code", "--")),
    ]
    if commit_object:
        specifications.append(("commit-object", ("cat-file", "commit", expected_commit)))
    for suffix, args in specifications:
        result = _run(trace, f"{label}-{phase}-{suffix}", runner, _git_command(root, *args), root, git_tool)
        results[suffix] = result.stdout
    head = _decode_line(results["head"], "HEAD")
    tree = _decode_line(results["tree"], "tree")
    if not HEX40.fullmatch(head) or not HEX40.fullmatch(tree) or (head, tree) != (expected_commit, expected_tree):
        raise ValueError(f"Git identity mismatch: got {head}/{tree}, expected {expected_commit}/{expected_tree}")
    if results["status"] or results["head-index-diff"] or results["worktree-index-diff"]:
        raise ValueError("worktree is not clean")
    _parse_index(results["index"], root)
    return results


def _parse_commit(data: bytes, expected_commit: str, expected_tree: str) -> int:
    if b"\0" in data:
        raise ValueError("commit object contains NUL")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("commit object is not UTF-8") from error
    object_id = hashlib.sha1(b"commit " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
    if object_id != expected_commit:
        raise ValueError("commit object does not match source commit")
    header, separator, _ = data.partition(b"\n\n")
    if not separator:
        raise ValueError("commit object lacks header terminator")
    lines = header.split(b"\n")
    tree_lines = [line for line in lines if line.startswith(b"tree")]
    committer_lines = [line for line in lines if line.startswith(b"committer ")]
    if tree_lines != [b"tree " + expected_tree.encode("ascii")] or len(committer_lines) != 1:
        raise ValueError("commit object identity headers are invalid")
    match = re.fullmatch(rb"committer .+ ([1-9][0-9]*) ([+-][0-9]{4})", committer_lines[0])
    if match is None:
        raise ValueError("commit epoch is invalid")
    epoch = int(match.group(1))
    if epoch > 9223372036854775807:
        raise ValueError("commit epoch is out of range")
    return epoch


def _validated_archive_inventory(data: bytes) -> dict[str, int]:
    try:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:")
    except tarfile.TarError as error:
        raise ValueError("invalid SDK archive") from error
    inventory: dict[str, int] = {}
    with archive:
        members = archive.getmembers()
        seen = set()
        for member in members:
            relative = _closed_relative(member.name).as_posix()
            if relative in seen or not (member.isfile() or member.isdir()):
                raise ValueError("unsafe or duplicate archive member")
            seen.add(relative)
            if member.linkname:
                raise ValueError("archive links are forbidden")
            normalized_mode = member.mode & ~0o022
            if member.isfile() and normalized_mode not in (0o644, 0o755):
                raise ValueError("unsupported archive mode")
            if member.isdir() and normalized_mode != 0o755:
                raise ValueError("unsupported archive directory mode")
            if member.isfile():
                inventory[relative] = normalized_mode
    if not inventory:
        raise ValueError("SDK archive contains no regular files")
    return inventory


def _safe_extract_tar(data: bytes, output: Path, expected_inventory: dict[str, int]) -> None:
    if _validated_archive_inventory(data) != expected_inventory:
        raise ValueError("SDK archive inventory changed before extraction")
    try:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:")
    except tarfile.TarError as error:
        raise ValueError("invalid SDK archive") from error
    with archive:
        members = archive.getmembers()
        for member in members:
            destination = output.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
                destination.chmod(0o755)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError("archive member has no data")
                write_new_file(destination, stream.read())
                destination.chmod(member.mode & ~0o022)
        for directory in sorted((item for item in output.rglob("*") if item.is_dir()), key=lambda item: len(item.parts), reverse=True):
            directory.chmod(0o755)


def _owned_directory_identity(path: Path) -> tuple[int, int, int, int]:
    info = Path(path).lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ValueError("owned staging root was rebound")
    return (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode), stat.S_IMODE(info.st_mode))


def _cleanup_owned_staging(path: Path, identity: tuple[int, int, int, int]) -> None:
    staging = Path(path)
    try:
        if _owned_directory_identity(staging) != identity:
            return
    except (FileNotFoundError, ValueError):
        return
    shutil.rmtree(staging)


def _entry_identity(path: Path) -> tuple[int, int, int]:
    info = Path(path).lstat()
    if stat.S_ISLNK(info.st_mode) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        raise ValueError("owned output entry is not a regular file or directory")
    return (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode))


def _commit_owned_staging(
    staging: Path,
    staging_identity: tuple[int, int, int, int],
    output: Path,
    output_identity: tuple[int, int, int],
    parent_identity: tuple[int, int, int, int],
) -> None:
    if _owned_directory_identity(staging) != staging_identity:
        raise ValueError("owned staging root changed before commit")
    if _directory_identity(output) != output_identity or _parent_identity(output)[:3] != parent_identity[:3]:
        raise ValueError("output binding changed before commit")
    if any(output.iterdir()):
        raise ValueError("caller output changed before commit")
    entries = sorted(staging.iterdir(), key=lambda item: item.name)
    identities = {entry.name: _entry_identity(entry) for entry in entries}
    moved: list[str] = []
    try:
        for entry in entries:
            if _owned_directory_identity(staging) != staging_identity:
                raise ValueError("owned staging root changed during commit")
            if _directory_identity(output) != output_identity or _parent_identity(output)[:3] != parent_identity[:3]:
                raise ValueError("output binding changed during commit")
            destination = output / entry.name
            if destination.exists() or destination.is_symlink():
                raise ValueError("caller output changed during commit")
            os.rename(entry, destination)
            if _entry_identity(destination) != identities[entry.name]:
                raise ValueError("committed output entry identity drift")
            moved.append(entry.name)
        if {entry.name for entry in output.iterdir()} != set(moved):
            raise ValueError("caller output inventory changed during commit")
        staging.rmdir()
    except BaseException:
        try:
            if _owned_directory_identity(staging) == staging_identity and _directory_identity(output) == output_identity:
                for name in reversed(moved):
                    destination = output / name
                    source = staging / name
                    if not (source.exists() or source.is_symlink()) and _entry_identity(destination) == identities[name]:
                        os.rename(destination, source)
        except (FileNotFoundError, ValueError, OSError):
            pass
        raise


def _capture_committed_entries(output: Path, output_identity: tuple[int, int, int]) -> dict[str, tuple[int, int, int]]:
    if _directory_identity(output) != output_identity:
        raise ValueError("output binding changed after commit")
    return {entry.name: _entry_identity(entry) for entry in output.iterdir()}


def _cleanup_committed_entries(output: Path, output_identity: tuple[int, int, int], entries: dict[str, tuple[int, int, int]]) -> None:
    try:
        if _directory_identity(output) != output_identity:
            return
        current = {entry.name: entry for entry in output.iterdir()}
        if set(current) != set(entries):
            return
        for name, path in current.items():
            if _entry_identity(path) != entries[name]:
                return
        for path in current.values():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
    except (FileNotFoundError, ValueError, OSError):
        return


def _create_apply_boundary(output: Path) -> Path:
    """Stop `git apply --no-index` from inheriting an ancestor repository."""
    git_dir = output / ".git"
    git_dir.mkdir(mode=0o755)
    (git_dir / "objects" / "info").mkdir(parents=True, mode=0o755)
    (git_dir / "objects" / "pack").mkdir(mode=0o755)
    (git_dir / "refs" / "heads").mkdir(parents=True, mode=0o755)
    write_new_file(git_dir / "HEAD", b"ref: refs/heads/stage0\n")
    write_new_file(
        git_dir / "config",
        b"[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n\tbare = false\n",
    )
    return git_dir


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    base = Path(root)
    for entry in sorted(base.rglob("*"), key=lambda item: item.relative_to(base).as_posix()):
        relative = entry.relative_to(base).as_posix().encode("utf-8")
        mode = entry.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError("materialized tree contains a symlink")
        if stat.S_ISDIR(mode):
            digest.update(b"D\0" + relative + b"\0")
        elif stat.S_ISREG(mode):
            git_mode = b"100755" if stat.S_IMODE(mode) & 0o111 else b"100644"
            digest.update(b"F\0" + relative + b"\0" + git_mode + b"\0" + hashlib.sha256(entry.read_bytes()).digest())
        else:
            raise ValueError("materialized tree contains a special file")
    return digest.hexdigest().upper()


def _normalize_argument(argument: str, repository_root: Path, sdk_root: Path, output_root: Path, staging_root: Path) -> str:
    roots = (
        (str(repository_root / ".git"), "${SOURCE_ROOT}/.git"),
        (str(sdk_root / ".git"), "${SDK_ROOT}/.git"),
        (str(repository_root), "${SOURCE_ROOT}"),
        (str(sdk_root), "${SDK_ROOT}"),
        (str(staging_root), "${OWNED_STAGING_ROOT}"),
        (str(output_root), "${OUTPUT_ROOT}"),
    )
    for actual, replacement in roots:
        if argument == actual:
            return replacement
        if argument.startswith(actual + os.sep):
            return replacement + argument[len(actual):].replace(os.sep, "/")
    return argument


def _derive_command_receipt_records(trace, *, repository_root: Path, sdk_root: Path, output_root: Path, git_tool: dict[str, str]):
    if not isinstance(trace, list) or len(trace) != len(COMMAND_ROLES):
        raise ValueError("command trace length drift")
    apply_cwds = {
        Path(item[2].get("cwd"))
        for item in trace
        if isinstance(item, tuple) and len(item) == 4 and item[0] in ("patch-check", "patch-apply")
    }
    if len(apply_cwds) != 1:
        raise ValueError("command trace does not identify one owned staging root")
    staging_root = apply_cwds.pop()
    if staging_root == output_root or staging_root.parent != output_root.parent:
        raise ValueError("owned staging root is not a distinct output sibling")
    if _owned_directory_identity(staging_root)[3] != 0o700:
        raise ValueError("owned staging root mode drift")
    records = []
    for expected_role, item in zip(COMMAND_ROLES, trace, strict=True):
        if not isinstance(item, tuple) or len(item) != 4:
            raise ValueError("invalid command trace record")
        role, argv, options, result = item
        if role != expected_role:
            raise ValueError("command trace order drift")
        environment = dict(options["env"])
        if environment.get("GIT_CEILING_DIRECTORIES") == str(staging_root):
            environment["GIT_CEILING_DIRECTORIES"] = "${OWNED_STAGING_ROOT}"
        stdin = options.get("input")
        cwd = Path(options["cwd"])
        cwd_name = {repository_root: "source", sdk_root: "sdk", staging_root: "${OWNED_STAGING_ROOT}"}.get(cwd)
        if cwd_name is None:
            raise ValueError("unexpected command cwd")
        records.append({
            "argv": [_normalize_argument(str(value), repository_root, sdk_root, output_root, staging_root) for value in argv],
            "cwd": cwd_name,
            "environment": environment,
            "exitCode": result.returncode,
            "role": role,
            "stderrSha256": _sha256(result.stderr),
            "stderrSize": len(result.stderr),
            "stdin": None if stdin is None else {"sha256": _sha256(stdin), "size": len(stdin)},
            "stdoutSha256": _sha256(result.stdout),
            "stdoutSize": len(result.stdout),
            "toolSha256": git_tool["sha256"],
            "toolVersion": git_tool["version"],
        })
    return records


def _normalized_git_command(root_token: str, *args: str) -> list[str]:
    return [
        "/usr/bin/git", *GIT_CONFIG_PREFIX,
        "--git-dir", root_token + "/.git", "--work-tree", root_token, *args,
    ]


def _expected_command_contexts(receipt: dict[str, object]) -> list[dict[str, object]]:
    source_commit = receipt.get("sourceCommit")
    sdk_commit = receipt.get("sdkCommit")
    patch = receipt.get("patch")
    if not isinstance(source_commit, str) or not isinstance(sdk_commit, str) or not isinstance(patch, dict):
        raise ValueError("receipt identity is unavailable for command validation")
    contexts: list[dict[str, object]] = []

    def add(role: str, argv: list[str], cwd: str, *, patch_stdin: bool = False) -> None:
        environment = dict(GIT_ENV)
        stdin = None
        if patch_stdin:
            environment["GIT_CEILING_DIRECTORIES"] = "${OWNED_STAGING_ROOT}"
            stdin = {"sha256": patch.get("sha256"), "size": patch.get("size")}
        contexts.append({
            "argv": argv,
            "cwd": cwd,
            "environment": environment,
            "role": role,
            "stdin": stdin,
        })

    add("git-version", ["/usr/bin/git", "--version"], "source")
    checks = (
        ("head", ("rev-parse", "HEAD")),
        ("tree", ("rev-parse", "HEAD^{tree}")),
        ("status", ("status", "--porcelain=v1", "--untracked-files=no")),
        ("index", ("ls-files", "-v", "--stage", "-z", "--")),
        ("head-index-diff", ("diff", "--no-ext-diff", "--no-textconv", "--exit-code", "--cached", "HEAD", "--")),
        ("worktree-index-diff", ("diff", "--no-ext-diff", "--no-textconv", "--exit-code", "--")),
    )
    for phase in ("before",):
        for label, root_token, cwd, commit, include_commit in (
            ("source", "${SOURCE_ROOT}", "source", source_commit, True),
            ("sdk", "${SDK_ROOT}", "sdk", sdk_commit, False),
        ):
            for suffix, args in checks:
                add(f"{label}-{phase}-{suffix}", _normalized_git_command(root_token, *args), cwd)
            if include_commit:
                add(f"{label}-{phase}-commit-object", _normalized_git_command(root_token, "cat-file", "commit", commit), cwd)
    archive_argv = _normalized_git_command("${SDK_ROOT}", "archive", "--format=tar", sdk_commit)
    add("sdk-archive", archive_argv, "sdk")
    add("sdk-archive-confirm", list(archive_argv), "sdk")
    apply_prefix = ["/usr/bin/git", *GIT_CONFIG_PREFIX]
    add("patch-check", [*apply_prefix, "apply", "--no-index", "--check", "-"], "${OWNED_STAGING_ROOT}", patch_stdin=True)
    add("patch-apply", [*apply_prefix, "apply", "--no-index", "-"], "${OWNED_STAGING_ROOT}", patch_stdin=True)
    for phase in ("after",):
        for label, root_token, cwd, commit, include_commit in (
            ("source", "${SOURCE_ROOT}", "source", source_commit, True),
            ("sdk", "${SDK_ROOT}", "sdk", sdk_commit, False),
        ):
            for suffix, args in checks:
                add(f"{label}-{phase}-{suffix}", _normalized_git_command(root_token, *args), cwd)
            if include_commit:
                add(f"{label}-{phase}-commit-object", _normalized_git_command(root_token, "cat-file", "commit", commit), cwd)
    if tuple(item["role"] for item in contexts) != COMMAND_ROLES:
        raise AssertionError("internal command contract order drift")
    return contexts


def validate_bootstrap_receipt(receipt, *, require_locks, expected_commands) -> None:
    if not isinstance(receipt, dict) or not isinstance(require_locks, bool):
        raise ValueError("invalid receipt")
    keys = {
        "commands", "gitTool", "outputTreeSha256", "overlay", "patch", "schema", "sdkCommit", "sdkTree",
        "sourceCommit", "sourceCommitEpoch", "sourceCommitObjectSha256", "sourceTree", "validations",
    }
    if require_locks:
        keys.add("locks")
    if set(receipt) != keys or receipt.get("schema") != "e87-stage0-bootstrap-receipt-v1":
        raise ValueError("closed bootstrap receipt schema drift")
    if expected_commands is receipt.get("commands") or not isinstance(expected_commands, list) or receipt.get("commands") != expected_commands:
        raise ValueError("commands are not independently validated")
    if len(expected_commands) != len(COMMAND_ROLES):
        raise ValueError("wrong command count")
    command_keys = {"argv", "cwd", "environment", "exitCode", "role", "stderrSha256", "stderrSize", "stdin", "stdoutSha256", "stdoutSize", "toolSha256", "toolVersion"}
    expected_contexts = _expected_command_contexts(receipt)
    for index, (role, record, context) in enumerate(zip(COMMAND_ROLES, receipt["commands"], expected_contexts, strict=True)):
        if not isinstance(record, dict) or set(record) != command_keys or record["role"] != role or record["exitCode"] != 0:
            raise ValueError("invalid command receipt")
        if not isinstance(record["argv"], list) or not record["argv"] or not all(isinstance(item, str) for item in record["argv"]):
            raise ValueError("invalid receipt argv")
        for field in ("argv", "cwd", "environment", "role", "stdin"):
            if record[field] != context[field]:
                raise ValueError("invalid receipt execution context")
        for field in ("stderrSha256", "stdoutSha256", "toolSha256"):
            if not isinstance(record[field], str) or HEX64.fullmatch(record[field]) is None:
                raise ValueError("invalid receipt digest")
        for field in ("stderrSize", "stdoutSize"):
            if type(record[field]) is not int or record[field] < 0:
                raise ValueError("invalid receipt size")
        if not isinstance(record["toolVersion"], str) or record["toolVersion"] != "2.34.1":
            raise ValueError("invalid Git version receipt")
        stdin = record["stdin"]
        if index in (16, 17):
            if not isinstance(stdin, dict) or set(stdin) != {"sha256", "size"} or stdin != {"sha256": receipt["patch"]["sha256"], "size": receipt["patch"]["size"]}:
                raise ValueError("patch stdin binding drift")
        elif stdin is not None:
            raise ValueError("unexpected command stdin")
    if receipt.get("validations") != VALIDATIONS:
        raise ValueError("validation projection drift")
    if receipt.get("gitTool") != {"path": "/usr/bin/git", "sha256": "587EF21868C948B883993E23209B86A72A6DDC06AAB1545C697FFC31075ACD4A", "version": "2.34.1"}:
        raise ValueError("Git identity drift")
    for field in ("sdkCommit", "sdkTree", "sourceCommit", "sourceTree"):
        if not isinstance(receipt.get(field), str) or HEX40.fullmatch(receipt[field]) is None:
            raise ValueError("invalid Git identity")
    for field in ("sourceCommitObjectSha256", "outputTreeSha256"):
        if not isinstance(receipt.get(field), str) or HEX64.fullmatch(receipt[field]) is None:
            raise ValueError("invalid receipt digest")
    if type(receipt.get("sourceCommitEpoch")) is not int or not (0 < receipt["sourceCommitEpoch"] <= 9223372036854775807):
        raise ValueError("invalid source epoch")
    if not isinstance(receipt.get("overlay"), list) or receipt["overlay"] != sorted(receipt["overlay"], key=lambda item: item.get("source", "")):
        raise ValueError("overlay receipt order drift")
    for record in receipt["overlay"]:
        if not isinstance(record, dict) or set(record) != {"destination", "sha256", "size", "source"} or HEX64.fullmatch(str(record["sha256"])) is None or type(record["size"]) is not int:
            raise ValueError("invalid overlay receipt")
    patch = receipt.get("patch")
    if not isinstance(patch, dict) or set(patch) != {"paths", "sha256", "size"} or HEX64.fullmatch(str(patch["sha256"])) is None or type(patch["size"]) is not int or not isinstance(patch["paths"], list):
        raise ValueError("invalid patch receipt")
    if require_locks and receipt.get("locks") != LOCK_DIGESTS:
        raise ValueError("lock receipt drift")


def bootstrap_sdk(
    *, repository_root: Path, sdk_root: Path, output_root: Path,
    expected_source_commit: str, expected_source_tree: str,
    expected_sdk_commit: str, expected_sdk_tree: str,
    overlay_records: list[dict[str, str]], patch_path: Path,
    allowed_patch_paths: Iterable[str], git_tool: dict[str, str], runner=None,
) -> dict[str, object]:
    if runner is None:
        runner = _system_runner
    repository = _validate_real_directory(repository_root, "repository root")
    sdk = _validate_real_directory(sdk_root, "SDK root")
    toolchain = _validate_real_directory(TOOLCHAIN_ROOT, "toolchain root")
    post_build = _validate_real_directory(POST_BUILD_ROOT, "post-build root")
    output = validate_output_root(output_root, (repository, sdk, toolchain, post_build))
    _validate_disjoint((repository, sdk, toolchain, post_build, output))
    if not all(HEX40.fullmatch(value or "") for value in (expected_source_commit, expected_source_tree, expected_sdk_commit, expected_sdk_tree)):
        raise ValueError("invalid expected Git identity")
    _safe_controller_tree(repository)
    _validate_git_admin(repository, "source", expected_source_commit)
    _validate_git_admin(sdk, "sdk", expected_sdk_commit)
    _validate_git_tool(git_tool)
    output_identity = _directory_identity(output)
    critical_source = _critical_git_snapshot(repository)
    critical_sdk = _critical_git_snapshot(sdk)
    destinations = set()
    prepared_overlays = []
    if not isinstance(overlay_records, list):
        raise ValueError("overlay records must be a list")
    for record in overlay_records:
        if not isinstance(record, dict) or set(record) != {"source", "destination"}:
            raise ValueError("invalid overlay record")
        source = _regular_repository_file(repository, record["source"])
        destination = _closed_relative(record["destination"]).as_posix()
        if destination in destinations:
            raise ValueError("duplicate overlay destination")
        destinations.add(destination)
        first_read = source.read_bytes()
        token = _path_token(source)
        confirmation_read = source.read_bytes()
        if first_read != confirmation_read or _sha256(first_read) != token[-1]:
            raise ValueError("overlay input changed during read")
        prepared_overlays.append((record["source"], destination, first_read, token, stat.S_IMODE(source.stat().st_mode)))
    prepared_overlays.sort(key=lambda item: item[0])
    patch = Path(patch_path)
    _reject_symlink_components(patch)
    if not patch.is_file() or not _is_relative_to(patch.resolve(strict=True), repository):
        raise ValueError("patch must be a contained regular repository file")
    patch_data = patch.read_bytes()
    patch_token = _path_token(patch)
    if patch.read_bytes() != patch_data or _sha256(patch_data) != patch_token[-1]:
        raise ValueError("patch changed during read")
    actual_paths = _patch_paths(patch_data)
    allowed = {_closed_relative(value).as_posix() for value in allowed_patch_paths}
    if actual_paths != allowed:
        raise ValueError("patch path allowlist mismatch")

    source_snapshot = _identity_snapshot(repository, ignore_controller=True)
    sdk_snapshot = _identity_snapshot(sdk, ignore_controller=False)
    trace = []
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage0-", dir=output.parent))
    staging.chmod(0o700)
    staging_identity = _owned_directory_identity(staging)
    output_parent_identity = _parent_identity(output)

    def ensure_runtime_state() -> None:
        if _directory_identity(output) != output_identity or _parent_identity(output) != output_parent_identity:
            raise ValueError("output root changed during bootstrap")
        if _owned_directory_identity(staging) != staging_identity or staging_identity[3] != 0o700:
            raise ValueError("owned staging root changed during bootstrap")
        _validate_git_admin(repository, "source", expected_source_commit)
        _validate_git_admin(sdk, "sdk", expected_sdk_commit)
        if _critical_git_snapshot(repository) != critical_source or _critical_git_snapshot(sdk) != critical_sdk:
            raise ValueError("critical Git state changed during bootstrap")

    underlying_runner = runner

    def guarded_runner(argv, **kwargs):
        ensure_runtime_state()
        result = underlying_runner(argv, **kwargs)
        ensure_runtime_state()
        return result

    runner = guarded_runner
    try:
        version = _run(trace, "git-version", runner, [git_tool["path"], "--version"], repository, git_tool)
        if version.stdout != ("git version " + git_tool["version"] + "\n").encode("ascii") or version.stderr:
            raise ValueError("Git version probe mismatch")
        source_before = _repository_checks(trace, "before", "source", repository, runner, git_tool, expected_source_commit, expected_source_tree, commit_object=True)
        _repository_checks(trace, "before", "sdk", sdk, runner, git_tool, expected_sdk_commit, expected_sdk_tree, commit_object=False)
        commit_data = source_before["commit-object"]
        source_epoch = _parse_commit(commit_data, expected_source_commit, expected_source_tree)
        archive_argv = _git_command(sdk, "archive", "--format=tar", expected_sdk_commit)
        archive = _run(trace, "sdk-archive", runner, archive_argv, sdk, git_tool)
        archive_confirm = _run(trace, "sdk-archive-confirm", runner, archive_argv, sdk, git_tool)
        if not archive.stdout or archive.stderr or not archive_confirm.stdout or archive_confirm.stderr:
            raise ValueError("SDK archive output is invalid")
        if archive.stdout != archive_confirm.stdout:
            raise ValueError("SDK archive bytes are not reproducible")
        if _sha256(archive.stdout) != SDK_ARCHIVE_SHA256:
            raise ValueError("SDK archive digest does not match the reviewed pin")
        if any(staging.iterdir()):
            raise ValueError("owned staging root changed before extraction")
        archive_inventory = _validated_archive_inventory(archive.stdout)
        intended_modes = dict(archive_inventory)
        for _, destination_name, _, _, source_mode in prepared_overlays:
            if destination_name in intended_modes:
                raise ValueError("overlay destination collides with SDK archive")
            intended_modes[destination_name] = 0o755 if source_mode & 0o111 else 0o644
        _safe_extract_tar(archive.stdout, staging, archive_inventory)
        overlay_receipt = []
        for source_name, destination_name, data, _, source_mode in prepared_overlays:
            destination = staging.joinpath(*PurePosixPath(destination_name).parts)
            _reject_symlink_components(destination.parent)
            destination.parent.mkdir(parents=True, exist_ok=True)
            _reject_symlink_components(destination.parent)
            if destination.exists() or destination.is_symlink():
                raise ValueError("overlay destination collision")
            write_new_file(destination, data)
            destination.chmod(0o755 if source_mode & 0o111 else 0o644)
            overlay_receipt.append({"destination": destination_name, "sha256": _sha256(data), "size": len(data), "source": source_name})
        apply_prefix = [git_tool["path"], *GIT_CONFIG_PREFIX]
        apply_boundary = _create_apply_boundary(staging)
        try:
            check = _run(trace, "patch-check", runner, [*apply_prefix, "apply", "--no-index", "--check", "-"], staging, git_tool, input_bytes=patch_data)
            if check.stdout or check.stderr:
                raise ValueError("patch check emitted output")
            applied = _run(trace, "patch-apply", runner, [*apply_prefix, "apply", "--no-index", "-"], staging, git_tool, input_bytes=patch_data)
            if applied.stdout or applied.stderr:
                raise ValueError("patch apply emitted output")
        finally:
            shutil.rmtree(apply_boundary)
        actual_files = {item.relative_to(staging).as_posix(): item for item in staging.rglob("*") if item.is_file() and not item.is_symlink()}
        if set(actual_files) != set(intended_modes):
            raise ValueError("patch changed the output inventory")
        for relative, item in actual_files.items():
            if bool(stat.S_IMODE(item.stat().st_mode) & 0o111) != bool(intended_modes[relative] & 0o111):
                raise ValueError("patch changed an output executable mode")
            item.chmod(intended_modes[relative])
        for directory in (item for item in staging.rglob("*") if item.is_dir() and not item.is_symlink()):
            directory.chmod(0o755)
        source_after = _repository_checks(trace, "after", "source", repository, runner, git_tool, expected_source_commit, expected_source_tree, commit_object=True)
        _repository_checks(trace, "after", "sdk", sdk, runner, git_tool, expected_sdk_commit, expected_sdk_tree, commit_object=False)
        if source_after["commit-object"] != commit_data:
            raise ValueError("source commit object changed")
        if _identity_snapshot(repository, ignore_controller=True) != source_snapshot or _identity_snapshot(sdk, ignore_controller=False) != sdk_snapshot:
            raise ValueError("protected input changed during bootstrap")
        for source_name, _, _, token, _ in prepared_overlays:
            if _path_token(_regular_repository_file(repository, source_name)) != token:
                raise ValueError("overlay input changed during use")
        if _path_token(patch) != patch_token or patch.read_bytes() != patch_data:
            raise ValueError("patch changed during use")
        receipt = {
            "commands": _derive_command_receipt_records(trace, repository_root=repository, sdk_root=sdk, output_root=output, git_tool=git_tool),
            "gitTool": dict(git_tool),
            "outputTreeSha256": tree_sha256(staging),
            "overlay": overlay_receipt,
            "patch": {"paths": sorted(actual_paths), "sha256": _sha256(patch_data), "size": len(patch_data)},
            "schema": "e87-stage0-bootstrap-receipt-v1",
            "sdkCommit": expected_sdk_commit,
            "sdkTree": expected_sdk_tree,
            "sourceCommit": expected_source_commit,
            "sourceCommitEpoch": source_epoch,
            "sourceCommitObjectSha256": _sha256(commit_data),
            "sourceTree": expected_source_tree,
            "validations": dict(VALIDATIONS),
        }
        validate_bootstrap_receipt(receipt, require_locks=False, expected_commands=json.loads(canonical_json(receipt["commands"])))
        ensure_runtime_state()
        _commit_owned_staging(staging, staging_identity, output, output_identity, output_parent_identity)
        return receipt
    except BaseException:
        _cleanup_owned_staging(staging, staging_identity)
        raise


def _load_locks(repository: Path):
    lock_root = repository / "firmware/locks"
    values = {}
    for name, expected_digest in LOCK_DIGESTS.items():
        path = lock_root / name
        _reject_symlink_components(path)
        if not path.is_file():
            raise ValueError("missing Stage0 lock")
        raw = path.read_bytes()
        try:
            value = json.loads(raw.decode("ascii"), object_pairs_hook=lambda pairs: _closed_pairs(pairs))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("invalid Stage0 lock") from error
        if canonical_json(value) != raw or _sha256(raw) != expected_digest:
            raise ValueError("Stage0 lock drift")
        values[name] = value
    return values


def _closed_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _read_loose_source_identity(repository: Path) -> tuple[str, str]:
    git_dir = repository / ".git"
    head = (git_dir / "HEAD").read_text(encoding="ascii").strip()
    if head.startswith("ref: "):
        ref = _closed_relative(head[5:]).as_posix()
        ref_path = git_dir.joinpath(*PurePosixPath(ref).parts)
        commit = ref_path.read_text(encoding="ascii").strip()
    else:
        commit = head
    if HEX40.fullmatch(commit or "") is None:
        raise ValueError("unsupported source HEAD representation")
    object_path = git_dir / "objects" / commit[:2] / commit[2:]
    try:
        raw = zlib.decompress(object_path.read_bytes())
    except (OSError, zlib.error) as error:
        raise ValueError("cannot read source commit object") from error
    header, separator, body = raw.partition(b"\0")
    if not separator or header != b"commit " + str(len(body)).encode("ascii"):
        raise ValueError("invalid loose source commit object")
    first = body.split(b"\n", 1)[0]
    if re.fullmatch(rb"tree [0-9a-f]{40}", first) is None:
        raise ValueError("invalid source tree header")
    return commit, first[5:].decode("ascii")


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--sdk-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--receipt-path", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None, *, runner=None, git_tool=None) -> int:
    args = build_cli_parser().parse_args(argv)
    repository = _validate_real_directory(args.repository_root, "repository root")
    sdk = _validate_real_directory(args.sdk_root, "SDK root")
    toolchain = _validate_real_directory(TOOLCHAIN_ROOT, "toolchain root")
    post_build = _validate_real_directory(POST_BUILD_ROOT, "post-build root")
    output = _validate_real_directory(args.output_root, "output root")
    _validate_disjoint((repository, sdk, toolchain, post_build, output))
    receipt_path = _validate_receipt_path(args.receipt_path, (repository, sdk, toolchain, post_build, output))
    receipt_parent_fd, receipt_parent_identity = _open_directory_fd(receipt_path.parent)
    output_identity = _directory_identity(output)
    committed_entries: dict[str, tuple[int, int, int]] = {}
    try:
        locks = _load_locks(repository)
        locked_git = locks["toolchain.lock.json"]["hostTools"]["git"]
        selected_git = locked_git if git_tool is None else git_tool
        if selected_git != locked_git:
            raise ValueError("Git identity does not match loaded lock")
        source_commit, source_tree = _read_loose_source_identity(repository)
        toolchain_lock = locks["toolchain.lock.json"]
        overlay_records = [
            {"source": source, "destination": source.removeprefix("firmware/overlay/")}
            for source in OVERLAY_SOURCES
        ]
        receipt = bootstrap_sdk(
            repository_root=repository,
            sdk_root=sdk,
            output_root=output,
            expected_source_commit=source_commit,
            expected_source_tree=source_tree,
            expected_sdk_commit=toolchain_lock["sdk"]["commit"],
            expected_sdk_tree=toolchain_lock["sdk"]["tree"],
            overlay_records=overlay_records,
            patch_path=repository / PATCH_RELATIVE,
            allowed_patch_paths=PATCH_TARGETS,
            git_tool=selected_git,
            runner=runner,
        )
        committed_entries = _capture_committed_entries(output, output_identity)
        receipt["locks"] = dict(LOCK_DIGESTS)
        independent_commands = json.loads(canonical_json(receipt["commands"]))
        validate_bootstrap_receipt(receipt, require_locks=True, expected_commands=independent_commands)
        _write_new_file_at(
            receipt_path.parent,
            receipt_parent_fd,
            receipt_parent_identity,
            receipt_path.name,
            canonical_json(receipt),
        )
    except BaseException:
        if committed_entries:
            _cleanup_committed_entries(output, output_identity, committed_entries)
        raise
    finally:
        os.close(receipt_parent_fd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
