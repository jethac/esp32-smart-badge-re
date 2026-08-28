#!/usr/bin/env python3
"""Offline SDK materialization and path-boundary tests for Stage 0-H."""
from __future__ import annotations

import ast
import importlib.util
import inspect
import io
import json
import hashlib
import os
import contextlib
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "firmware/tools/bootstrap-sdk.py"
GIT_CONFIG_PREFIX = (
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.attributesFile=/dev/null",
    "-c",
    "tar.umask=0002",
)
LOCKED_TOOLCHAIN_ROOT = Path("/home/jethac/.local/share/e87-dev/jieli")
LOCKED_POST_BUILD_ROOT = Path("/home/jethac/.local/share/e87-dev/jieli-post-build")
REAL_SUBPROCESS_POPEN = subprocess.Popen
REAL_COMPLETED_PROCESS = subprocess.CompletedProcess


def real_subprocess_run(
    *popenargs,
    input=None,
    capture_output=False,
    timeout=None,
    check=False,
    **kwargs,
):
    """Test-owned subprocess adapter immune to module-API monkeypatches."""
    if input is not None:
        if kwargs.get("stdin") is not None:
            raise ValueError("stdin and input arguments may not both be used")
        kwargs["stdin"] = subprocess.PIPE
    if capture_output:
        if kwargs.get("stdout") is not None or kwargs.get("stderr") is not None:
            raise ValueError("stdout/stderr and capture_output may not both be used")
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    with REAL_SUBPROCESS_POPEN(*popenargs, **kwargs) as process:
        try:
            stdout, stderr = process.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise
        returncode = process.poll()
    if check and returncode:
        raise subprocess.CalledProcessError(
            returncode, process.args, output=stdout, stderr=stderr
        )
    return REAL_COMPLETED_PROCESS(process.args, returncode, stdout, stderr)


REAL_SUBPROCESS_RUN = real_subprocess_run
PYTHON = Path("/usr/bin/python3.11")


def git_arguments(argv) -> list[str]:
    arguments = list(argv)[1:]
    if tuple(arguments[: len(GIT_CONFIG_PREFIX)]) == GIT_CONFIG_PREFIX:
        arguments = arguments[len(GIT_CONFIG_PREFIX) :]
    if (
        len(arguments) >= 4
        and arguments[0] == "--git-dir"
        and arguments[2] == "--work-tree"
    ):
        arguments = arguments[4:]
    return arguments


def git_verb(argv) -> str:
    arguments = git_arguments(argv)
    return arguments[0] if arguments else ""


def git_bound_root(argv) -> Path | None:
    arguments = list(argv)[1:]
    if tuple(arguments[: len(GIT_CONFIG_PREFIX)]) == GIT_CONFIG_PREFIX:
        arguments = arguments[len(GIT_CONFIG_PREFIX) :]
    if (
        len(arguments) >= 4
        and arguments[0] == "--git-dir"
        and arguments[2] == "--work-tree"
    ):
        git_dir = Path(arguments[1])
        work_tree = Path(arguments[3])
        if git_dir != work_tree / ".git":
            raise AssertionError("Git directory is not bound to its work tree")
        return work_tree
    return None


def load_tool(module_name="e87_stage0_bootstrap"):
    spec = importlib.util.spec_from_file_location(module_name, TOOL)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load bootstrap tool")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def git(*args: str, cwd: Path) -> str:
    result = REAL_SUBPROCESS_RUN(
        ["/usr/bin/git", *args], cwd=cwd, text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def git_bytes(*args: str, cwd: Path) -> bytes:
    return REAL_SUBPROCESS_RUN(
        ["/usr/bin/git", *args],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout


def local_config_entries(root: Path) -> list[tuple[str, str]]:
    output = git("config", "--local", "--list", cwd=root)
    entries = []
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if not separator:
            raise AssertionError(f"malformed git config listing: {line!r}")
        entries.append((key, value))
    return entries


def git_object_sha1(kind: str, data: bytes) -> str:
    header = f"{kind} {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def independent_commit_epoch(data: bytes) -> int:
    header, separator, _ = data.partition(b"\n\n")
    if not separator:
        raise AssertionError("commit object has no header terminator")
    lines = [line for line in header.split(b"\n") if line.startswith(b"committer ")]
    if len(lines) != 1:
        raise AssertionError("commit object must contain one committer header")
    match = re.fullmatch(rb"committer .+ ([1-9][0-9]*) ([+-][0-9]{4})", lines[0])
    if match is None:
        raise AssertionError("commit object has a noncanonical committer header")
    epoch = int(match.group(1))
    if epoch > 9223372036854775807:
        raise AssertionError("commit epoch is out of range")
    return epoch


def independent_commit_tree(data: bytes) -> str:
    header, separator, _ = data.partition(b"\n\n")
    if not separator:
        raise AssertionError("commit object has no header terminator")
    lines = [line for line in header.split(b"\n") if line.startswith(b"tree")]
    if len(lines) != 1:
        raise AssertionError("commit object must contain one tree header")
    match = re.fullmatch(rb"tree ([0-9a-f]{40})", lines[0])
    if match is None:
        raise AssertionError("commit object has a noncanonical tree header")
    return match.group(1).decode("ascii")


def repository_git_command(root: Path, *arguments: str) -> list[str]:
    return [
        "/usr/bin/git",
        *GIT_CONFIG_PREFIX,
        "--git-dir",
        str(Path(root) / ".git"),
        "--work-tree",
        str(Path(root)),
        *arguments,
    ]


def closed_git_archive(root: Path, commit: str) -> bytes:
    result = REAL_SUBPROCESS_RUN(
        repository_git_command(root, "archive", "--format=tar", commit),
        cwd=root,
        env={
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
        },
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        shell=False,
    )
    return result.stdout


def bootstrap_cli_arguments(fixture, output: Path, receipt: Path) -> list[str]:
    return [
        "--repository-root",
        str(fixture["repositoryRoot"]),
        "--sdk-root",
        str(fixture["sdkRoot"]),
        "--output-root",
        str(output),
        "--receipt-path",
        str(receipt),
    ]


def snapshot_tree(root: Path) -> list[tuple[str, str, str]]:
    result = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            result.append((relative, "symlink", os.readlink(path)))
        elif path.is_file():
            result.append((relative, "file", hashlib.sha256(path.read_bytes()).hexdigest()))
        elif path.is_dir():
            result.append((relative, "directory", ""))
        else:
            result.append((relative, "special", ""))
    return result


def independent_tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        if path.is_symlink():
            raise AssertionError("materialized output contains symlink")
        if path.is_dir():
            digest.update(b"D\0" + relative + b"\0")
        elif path.is_file():
            git_mode = (
                b"100755" if stat.S_IMODE(path.stat().st_mode) & 0o111 else b"100644"
            )
            digest.update(
                b"F\0"
                + relative
                + b"\0"
                + git_mode
                + b"\0"
                + hashlib.sha256(path.read_bytes()).digest()
            )
        else:
            raise AssertionError("materialized output contains special file")
    return digest.hexdigest().upper()


COMMAND_RECORD_KEYS = {
    "argv",
    "cwd",
    "environment",
    "exitCode",
    "role",
    "stderrSha256",
    "stderrSize",
    "stdin",
    "stdoutSha256",
    "stdoutSize",
    "toolSha256",
    "toolVersion",
}
COMMAND_ROLES = (
    "git-version",
    "source-before-head",
    "source-before-tree",
    "source-before-status",
    "source-before-index",
    "source-before-head-index-diff",
    "source-before-worktree-index-diff",
    "source-before-commit-object",
    "sdk-before-head",
    "sdk-before-tree",
    "sdk-before-status",
    "sdk-before-index",
    "sdk-before-head-index-diff",
    "sdk-before-worktree-index-diff",
    "sdk-archive",
    "sdk-archive-confirm",
    "patch-check",
    "patch-apply",
    "source-after-head",
    "source-after-tree",
    "source-after-status",
    "source-after-index",
    "source-after-head-index-diff",
    "source-after-worktree-index-diff",
    "source-after-commit-object",
    "sdk-after-head",
    "sdk-after-tree",
    "sdk-after-status",
    "sdk-after-index",
    "sdk-after-head-index-diff",
    "sdk-after-worktree-index-diff",
)
VALIDATION_RESULTS = {
    "archiveInventory": True,
    "gitToolIdentity": True,
    "outputRoot": True,
    "outputTree": True,
    "overlayInputs": True,
    "patchContract": True,
    "protectedRoots": True,
    "sdkClean": True,
    "sdkIdentity": True,
    "sdkStable": True,
    "sourceClean": True,
    "sourceIdentity": True,
    "sourceStable": True,
}


def command_receipt_records(
    runner,
    *,
    repository_root: Path,
    sdk_root: Path,
    output_root: Path,
    git_tool: dict[str, str],
) -> list[dict[str, object]]:
    if len(runner.calls) != len(COMMAND_ROLES) or len(runner.results) != len(
        COMMAND_ROLES
    ):
        raise AssertionError("runner trace does not contain the exact command sequence")
    apply_cwds = {
        Path(kwargs["cwd"])
        for argv, kwargs in runner.calls
        if git_verb(argv) == "apply"
    }
    if len(apply_cwds) != 1:
        raise AssertionError("runner trace does not identify one owned staging root")
    owned_staging_root = apply_cwds.pop()
    if (
        owned_staging_root == Path(output_root)
        or owned_staging_root.parent != Path(output_root).parent
    ):
        raise AssertionError("owned staging root is not a distinct output sibling")
    roots = (
        (str(Path(repository_root) / ".git"), "${SOURCE_ROOT}/.git"),
        (str(Path(sdk_root) / ".git"), "${SDK_ROOT}/.git"),
        (str(Path(repository_root)), "${SOURCE_ROOT}"),
        (str(Path(sdk_root)), "${SDK_ROOT}"),
        (str(owned_staging_root), "${OWNED_STAGING_ROOT}"),
        (str(Path(output_root)), "${OUTPUT_ROOT}"),
    )
    cwd_names = {
        Path(repository_root): "source",
        Path(sdk_root): "sdk",
        owned_staging_root: "${OWNED_STAGING_ROOT}",
    }

    def normalize_argument(argument: str) -> str:
        for actual, replacement in roots:
            if argument == actual:
                return replacement
            if argument.startswith(actual + os.sep):
                return replacement + argument[len(actual) :].replace(os.sep, "/")
        return argument

    def process_bytes(value, stream_name: str) -> bytes:
        if not isinstance(value, bytes):
            raise AssertionError(f"runner {stream_name} must be bytes")
        return value

    records = []
    for role, (argv, kwargs), result in zip(
        COMMAND_ROLES, runner.calls, runner.results, strict=True
    ):
        stdout = process_bytes(result.stdout, "stdout")
        stderr = process_bytes(result.stderr, "stderr")
        environment = dict(kwargs["env"])
        if environment.get("GIT_CEILING_DIRECTORIES") == str(owned_staging_root):
            environment["GIT_CEILING_DIRECTORIES"] = "${OWNED_STAGING_ROOT}"
        stdin_bytes = kwargs.get("input")
        stdin_record = None
        if stdin_bytes is not None:
            if not isinstance(stdin_bytes, bytes):
                raise AssertionError("runner input must be bytes")
            stdin_record = {
                "sha256": hashlib.sha256(stdin_bytes).hexdigest().upper(),
                "size": len(stdin_bytes),
            }
        cwd = Path(kwargs["cwd"])
        if cwd not in cwd_names:
            raise AssertionError(f"unexpected runner cwd: {cwd}")
        records.append(
            {
                "argv": [normalize_argument(str(argument)) for argument in argv],
                "cwd": cwd_names[cwd],
                "environment": environment,
                "exitCode": result.returncode,
                "role": role,
                "stderrSha256": hashlib.sha256(stderr).hexdigest().upper(),
                "stderrSize": len(stderr),
                "stdin": stdin_record,
                "stdoutSha256": hashlib.sha256(stdout).hexdigest().upper(),
                "stdoutSize": len(stdout),
                "toolSha256": git_tool["sha256"],
                "toolVersion": git_tool["version"],
            }
        )
    return records


class RecordingRunner:
    def __init__(self):
        self.calls = []
        self.results = []

    def record_result(self, result):
        self.results.append(result)
        return result

    def execute(self, command, options):
        if list(command) == ["/usr/bin/git", "--version"]:
            result = subprocess.CompletedProcess(
                list(command), 0, b"git version 2.34.1\n", b""
            )
        else:
            result = REAL_SUBPROCESS_RUN(command, **options)
        return self.record_result(result)

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), dict(kwargs)))
        return self.execute(list(argv), dict(kwargs))


class UseWindowRunner(RecordingRunner):
    def __init__(self, sdk_root, mutation, restoration=None, restore_after_apply=None):
        super().__init__()
        self.sdk_root = Path(sdk_root)
        self.mutation = mutation
        self.restoration = restoration
        self.restore_after_apply = restore_after_apply
        self.mutated = False
        self.restored = False
        self.staged_overlay = None
        self.apply_inputs = []

    def __call__(self, argv, **kwargs):
        command = list(argv)
        options = dict(kwargs)
        self.calls.append((command, options))
        verb = git_verb(command)
        cwd = Path(options["cwd"])
        if verb == "apply":
            staged = cwd / "SDK/added.txt"
            if self.staged_overlay is None and staged.is_file():
                self.staged_overlay = staged.read_bytes()
            self.apply_inputs.append(options.get("input"))
        result = self.execute(command, options)
        if verb == "archive" and cwd == self.sdk_root and result.returncode == 0 and not self.mutated:
            self.mutation()
            self.mutated = True
        if (
            verb == "apply"
            and self.restoration is not None
            and not self.restored
            and self.restore_after_apply is not None
            and len(self.apply_inputs) >= self.restore_after_apply
        ):
            self.restoration()
            self.restored = True
        return result

    def restore_now(self):
        if self.restoration is not None and self.mutated and not self.restored:
            self.restoration()
            self.restored = True


class LockedSdkRunner(RecordingRunner):
    def __init__(self, sdk_root: Path, locked_commit: str, locked_tree: str, archive_commit: str):
        super().__init__()
        self.sdk_root = sdk_root
        self.locked_commit = locked_commit
        self.locked_tree = locked_tree
        self.archive_commit = archive_commit

    def __call__(self, argv, **kwargs):
        command = list(argv)
        options = dict(kwargs)
        self.calls.append((command, options))
        cwd = Path(options["cwd"])
        arguments = git_arguments(command)
        if cwd == self.sdk_root and arguments == ["rev-parse", "HEAD"]:
            return self.record_result(
                subprocess.CompletedProcess(
                    command, 0, (self.locked_commit + "\n").encode("ascii"), b""
                )
            )
        if cwd == self.sdk_root and arguments == ["rev-parse", "HEAD^{tree}"]:
            return self.record_result(
                subprocess.CompletedProcess(
                    command, 0, (self.locked_tree + "\n").encode("ascii"), b""
                )
            )
        if cwd == self.sdk_root and arguments[:3] == ["archive", "--format=tar", self.locked_commit]:
            replacement = repository_git_command(
                self.sdk_root, "archive", "--format=tar", self.archive_commit
            )
            result = REAL_SUBPROCESS_RUN(replacement, **options)
            return self.record_result(
                subprocess.CompletedProcess(
                    command, result.returncode, result.stdout, result.stderr
                )
            )
        return self.execute(command, options)


class ReceiptAppearanceRunner(LockedSdkRunner):
    def __init__(self, *args, mutation, **kwargs):
        super().__init__(*args, **kwargs)
        self.mutation = mutation
        self.final_sdk_checks = 0
        self.mutated = False

    def __call__(self, argv, **kwargs):
        command = list(argv)
        root = git_bound_root(command) or Path(kwargs["cwd"])
        arguments = git_arguments(command)
        result = super().__call__(argv, **kwargs)
        if (
            root == self.sdk_root
            and arguments
            == [
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                "--exit-code",
                "--",
            ]
            and result.returncode == 0
        ):
            self.final_sdk_checks += 1
            if self.final_sdk_checks == 2:
                self.mutation()
                self.mutated = True
        return result


class CommitObjectRunner(RecordingRunner):
    def __init__(
        self,
        repository_root: Path,
        expected_commit: str,
        commit_objects: list[bytes],
        *,
        head_values: list[str] | None = None,
        fail_cat_file: bool = False,
    ):
        super().__init__()
        self.repository_root = Path(repository_root)
        self.expected_commit = expected_commit
        self.commit_objects = list(commit_objects)
        self.head_values = list(head_values or [expected_commit])
        self.fail_cat_file = fail_cat_file
        self.head_reads = 0
        self.object_reads = []

    def __call__(self, argv, **kwargs):
        command = list(argv)
        options = dict(kwargs)
        self.calls.append((command, options))
        cwd = Path(options["cwd"])
        root = git_bound_root(command) or cwd
        arguments = git_arguments(command)
        if root == self.repository_root and arguments == ["rev-parse", "HEAD"]:
            index = min(self.head_reads, len(self.head_values) - 1)
            self.head_reads += 1
            return self.record_result(
                subprocess.CompletedProcess(
                    command,
                    0,
                    (self.head_values[index] + "\n").encode("ascii"),
                    b"",
                )
            )
        if root == self.repository_root and arguments == [
            "cat-file",
            "commit",
            self.expected_commit,
        ]:
            if self.fail_cat_file:
                return self.record_result(
                    subprocess.CompletedProcess(
                        command, 1, b"", b"fixture failure"
                    )
                )
            index = min(len(self.object_reads), len(self.commit_objects) - 1)
            data = self.commit_objects[index]
            self.object_reads.append(data)
            return self.record_result(
                subprocess.CompletedProcess(command, 0, data, b"")
            )
        return self.execute(command, options)


class ConfigWindowRunner(RecordingRunner):
    def __init__(
        self,
        target_root: Path,
        target_arguments: list[str],
        mutation,
        restoration,
        *,
        mutate_before: bool,
        restore_after: bool,
    ):
        super().__init__()
        self.target_root = Path(target_root)
        self.target_arguments = list(target_arguments)
        self.mutation = mutation
        self.restoration = restoration
        self.mutate_before = mutate_before
        self.restore_after = restore_after
        self.mutated = False
        self.restored = False
        self.target_stdout = None

    def __call__(self, argv, **kwargs):
        command = list(argv)
        options = dict(kwargs)
        self.calls.append((command, options))
        cwd = Path(options["cwd"])
        root = git_bound_root(command) or cwd
        is_target = (
            not self.mutated
            and root == self.target_root
            and git_arguments(command) == self.target_arguments
        )
        if is_target and self.mutate_before:
            self.mutation()
            self.mutated = True
        result = self.execute(command, options)
        if is_target:
            self.target_stdout = result.stdout
            if not self.mutate_before:
                self.mutation()
                self.mutated = True
            if self.restore_after:
                self.restoration()
                self.restored = True
        return result

    def restore_now(self):
        if self.mutated and not self.restored:
            self.restoration()
            self.restored = True


class InjectedGitOutputRunner(RecordingRunner):
    def __init__(self, target_root: Path, target_arguments: list[str], stdout: bytes):
        super().__init__()
        self.target_root = Path(target_root)
        self.target_arguments = list(target_arguments)
        self.stdout = stdout
        self.injected = 0

    def __call__(self, argv, **kwargs):
        command = list(argv)
        options = dict(kwargs)
        self.calls.append((command, options))
        root = git_bound_root(command) or Path(options["cwd"])
        if root == self.target_root and git_arguments(command) == self.target_arguments:
            self.injected += 1
            return self.record_result(
                subprocess.CompletedProcess(command, 0, self.stdout, b"")
            )
        return self.execute(command, options)


class PostApplyModeMutationRunner(RecordingRunner):
    def __init__(self, output_root: Path):
        super().__init__()
        self.output_root = Path(output_root)
        self.apply_calls = 0
        self.mutated = False
        self.caller_untouched_at_mutation = False

    def __call__(self, argv, **kwargs):
        command = list(argv)
        options = dict(kwargs)
        self.calls.append((command, options))
        result = self.execute(command, options)
        if git_verb(command) == "apply" and result.returncode == 0:
            self.apply_calls += 1
            if self.apply_calls == 2:
                owned_staging = Path(options["cwd"])
                if (
                    owned_staging == self.output_root
                    or owned_staging.parent != self.output_root.parent
                    or stat.S_IMODE(owned_staging.stat(follow_symlinks=False).st_mode)
                    != 0o700
                    or list(self.output_root.iterdir())
                ):
                    raise AssertionError("apply did not use isolated owned staging")
                self.caller_untouched_at_mutation = True
                target = owned_staging / "SDK/executable.sh"
                if target.is_file() and not target.is_symlink():
                    target.chmod(0o644)
                    self.mutated = True
        return result


class OutputRebindRunner(RecordingRunner):
    def __init__(
        self,
        output_root: Path,
        symlink_target: Path,
        *,
        trigger_verb: str,
        restore_after_verb: str | None = None,
    ):
        super().__init__()
        self.output_root = Path(output_root)
        self.symlink_target = Path(symlink_target)
        self.held_root = self.output_root.with_name(self.output_root.name + "-validated-inode")
        self.trigger_verb = trigger_verb
        self.restore_after_verb = restore_after_verb
        self.validated_output_stat = self.output_root.stat(follow_symlinks=False)
        self.parent_stat = self.output_root.parent.stat(follow_symlinks=False)
        self.target_stat = self.symlink_target.stat(follow_symlinks=False)
        self.parent_after_mutation = None
        self.parent_after_restore = None
        self.mutated = False
        self.restored = False

    @staticmethod
    def identity(value):
        return value.st_dev, value.st_ino

    @staticmethod
    def write_metadata(value):
        return value.st_dev, value.st_ino, value.st_mtime_ns, value.st_ctime_ns

    def mutate(self):
        self.output_root.rename(self.held_root)
        self.output_root.symlink_to(self.symlink_target, target_is_directory=True)
        self.mutated = True
        self.parent_after_mutation = self.output_root.parent.stat(follow_symlinks=False)
        if self.identity(self.held_root.stat(follow_symlinks=False)) != self.identity(
            self.validated_output_stat
        ):
            raise AssertionError("validated output inode changed during rebind")

    def restore_now(self):
        if not self.mutated or self.restored:
            return
        if self.output_root.is_symlink():
            self.output_root.unlink()
        elif self.output_root.exists():
            if not self.held_root.exists():
                self.restored = True
                return
            raise AssertionError("rebound output pathname was unexpectedly replaced")
        if self.held_root.exists():
            self.held_root.rename(self.output_root)
        self.restored = True
        self.parent_after_restore = self.output_root.parent.stat(follow_symlinks=False)

    def __call__(self, argv, **kwargs):
        command = list(argv)
        options = dict(kwargs)
        self.calls.append((command, options))
        verb = git_verb(command)
        if not self.mutated and verb == self.trigger_verb:
            self.mutate()
        result = self.execute(command, options)
        if self.mutated and self.restore_after_verb == verb:
            self.restore_now()
        return result


class OwnedStagingObserverRunner(RecordingRunner):
    def __init__(self, caller_output: Path, *, fail_first_apply: bool = False):
        super().__init__()
        self.caller_output = Path(caller_output)
        self.caller_identity = self.caller_output.stat(follow_symlinks=False)
        self.fail_first_apply = fail_first_apply
        self.apply_cwd = None
        self.caller_untouched_at_apply = False
        self.saw_owned_staging = False

    def __call__(self, argv, **kwargs):
        command = list(argv)
        options = dict(kwargs)
        self.calls.append((command, options))
        if git_verb(command) == "apply" and self.apply_cwd is None:
            cwd = Path(options["cwd"])
            self.apply_cwd = cwd
            current = self.caller_output.stat(follow_symlinks=False)
            self.caller_untouched_at_apply = (
                (current.st_dev, current.st_ino)
                == (self.caller_identity.st_dev, self.caller_identity.st_ino)
                and list(self.caller_output.iterdir()) == []
            )
            self.saw_owned_staging = (
                cwd != self.caller_output
                and cwd.parent == self.caller_output.parent
                and cwd.is_dir()
                and not cwd.is_symlink()
                and stat.S_IMODE(cwd.stat(follow_symlinks=False).st_mode) == 0o700
            )
            if self.fail_first_apply:
                return self.record_result(
                    subprocess.CompletedProcess(
                        command, 1, b"", b"owned staging failure fixture\n"
                    )
                )
        return self.execute(command, options)


class OutputInjectionRunner(RecordingRunner):
    def __init__(self, sdk_root: Path, caller_output: Path):
        super().__init__()
        self.sdk_root = Path(sdk_root)
        self.caller_output = Path(caller_output)
        self.initial_siblings = {
            path.name for path in self.caller_output.parent.iterdir()
        }
        self.injected_target = None

    def __call__(self, argv, **kwargs):
        command = list(argv)
        options = dict(kwargs)
        self.calls.append((command, options))
        result = self.execute(command, options)
        if (
            self.injected_target is None
            and Path(options["cwd"]) == self.sdk_root
            and git_verb(command) == "archive"
            and result.returncode == 0
        ):
            new_directories = [
                path
                for path in self.caller_output.parent.iterdir()
                if path.name not in self.initial_siblings
                and path.is_dir()
                and not path.is_symlink()
            ]
            if len(new_directories) > 1:
                raise AssertionError("bootstrap created multiple candidate staging roots")
            self.injected_target = (
                new_directories[0] if new_directories else self.caller_output
            )
            injected = self.injected_target / "injected-extra.txt"
            injected.write_bytes(b"concurrent output injection\n")
            injected.chmod(0o644)
        return result


class ArchiveBytesRunner(RecordingRunner):
    def __init__(self, sdk_root: Path, caller_output: Path, archive_payloads: list[bytes]):
        super().__init__()
        self.sdk_root = Path(sdk_root)
        self.caller_output = Path(caller_output)
        self.archive_payloads = list(archive_payloads)
        self.archive_calls = 0
        self.initial_siblings = {
            path.name for path in self.caller_output.parent.iterdir()
        }
        self.second_call_saw_empty_staging = False

    def __call__(self, argv, **kwargs):
        command = list(argv)
        options = dict(kwargs)
        self.calls.append((command, options))
        if (
            Path(options["cwd"]) == self.sdk_root
            and git_verb(command) == "archive"
        ):
            if self.archive_calls == 1:
                candidates = [
                    path
                    for path in self.caller_output.parent.iterdir()
                    if path.name not in self.initial_siblings
                    and path.is_dir()
                    and not path.is_symlink()
                ]
                self.second_call_saw_empty_staging = (
                    len(candidates) == 1 and list(candidates[0].iterdir()) == []
                )
            index = min(self.archive_calls, len(self.archive_payloads) - 1)
            self.archive_calls += 1
            return self.record_result(
                subprocess.CompletedProcess(
                    command, 0, self.archive_payloads[index], b""
                )
            )
        return self.execute(command, options)


class LockedOutputRebindRunner(LockedSdkRunner):
    def __init__(self, *args, output_root: Path, symlink_target: Path, **kwargs):
        super().__init__(*args, **kwargs)
        self.output_root = Path(output_root)
        self.symlink_target = Path(symlink_target)
        self.held_root = self.output_root.with_name(
            self.output_root.name + "-validated-inode"
        )
        self.mutated = False
        self.restored = False

    def mutate(self):
        self.output_root.rename(self.held_root)
        self.output_root.symlink_to(self.symlink_target, target_is_directory=True)
        self.mutated = True

    def restore_now(self):
        if not self.mutated or self.restored:
            return
        if self.output_root.is_symlink():
            self.output_root.unlink()
        if self.held_root.exists():
            self.held_root.rename(self.output_root)
        self.restored = True

    def __call__(self, argv, **kwargs):
        command = list(argv)
        if not self.mutated and git_verb(command) == "archive":
            self.mutate()
        return super().__call__(argv, **kwargs)


class ReceiptParentRebindRunner(LockedSdkRunner):
    def __init__(
        self,
        *args,
        receipt_parent: Path,
        redirect_target: Path,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.receipt_parent = Path(receipt_parent)
        self.redirect_target = Path(redirect_target)
        self.held_parent = self.receipt_parent.with_name(
            self.receipt_parent.name + "-validated-inode"
        )
        self.final_sdk_checks = 0
        self.mutated = False
        self.restored = False

    def mutate(self):
        self.receipt_parent.rename(self.held_parent)
        self.receipt_parent.symlink_to(self.redirect_target, target_is_directory=True)
        self.mutated = True

    def restore_now(self):
        if not self.mutated or self.restored:
            return
        if self.receipt_parent.is_symlink():
            self.receipt_parent.unlink()
        if self.held_parent.exists():
            self.held_parent.rename(self.receipt_parent)
        self.restored = True

    def __call__(self, argv, **kwargs):
        command = list(argv)
        root = git_bound_root(command) or Path(kwargs["cwd"])
        arguments = git_arguments(command)
        result = super().__call__(argv, **kwargs)
        if (
            root == self.sdk_root
            and arguments
            == [
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                "--exit-code",
                "--",
            ]
            and result.returncode == 0
        ):
            self.final_sdk_checks += 1
            if self.final_sdk_checks == 2:
                self.mutate()
        return result


class BootstrapTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.bootstrap = load_tool()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="e87-bootstrap-test-")
        self.base = Path(self.temp.name)
        self.repo = self.base / "source-repository"
        self.sdk = self.base / "installed-sdk"
        self.toolchain_root = self.base / "installed-toolchain"
        self.post_build_root = self.base / "installed-post-build-tools"
        self.repo.mkdir()
        self.sdk.mkdir()
        self.toolchain_root.mkdir()
        self.post_build_root.mkdir()
        git("init", "-q", "-b", "codex/e87-local-rendering", cwd=self.repo)
        git("config", "user.email", "jethachan@gmail.com", cwd=self.repo)
        git("config", "user.name", "Jetha Chan", cwd=self.repo)
        git(
            "config",
            "remote.bootstrap.url",
            "/home/jethac/.cache/codex-transfer/factory-android-badges-e87.bundle",
            cwd=self.repo,
        )
        git(
            "config",
            "remote.bootstrap.fetch",
            "+refs/heads/*:refs/remotes/bootstrap/*",
            cwd=self.repo,
        )
        git(
            "config",
            "remote.origin.url",
            "https://github.com/jethac/factory-android-badges.git",
            cwd=self.repo,
        )
        git(
            "config",
            "remote.origin.fetch",
            "+refs/heads/*:refs/remotes/origin/*",
            cwd=self.repo,
        )
        git(
            "config",
            "branch.codex/e87-local-rendering.remote",
            "bootstrap",
            cwd=self.repo,
        )
        git(
            "config",
            "branch.codex/e87-local-rendering.merge",
            "refs/heads/codex/e87-local-rendering",
            cwd=self.repo,
        )
        git("init", "-q", "-b", "main", cwd=self.sdk)
        git("config", "user.email", "stage0@example.invalid", cwd=self.sdk)
        git("config", "user.name", "Stage0 Test", cwd=self.sdk)
        git(
            "config",
            "remote.origin.url",
            "https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200.git",
            cwd=self.sdk,
        )
        git(
            "config",
            "remote.origin.fetch",
            "+refs/heads/main:refs/remotes/origin/main",
            cwd=self.sdk,
        )
        git("config", "branch.main.remote", "origin", cwd=self.sdk)
        git("config", "branch.main.merge", "refs/heads/main", cwd=self.sdk)
        (self.sdk / "SDK").mkdir()
        (self.sdk / "SDK/base.txt").write_text("base\n", encoding="ascii")
        (self.sdk / "SDK/base.txt").chmod(0o644)
        self.sdk_executable = self.sdk / "SDK/executable.sh"
        self.sdk_executable.write_text("#!/bin/sh\nexit 0\n", encoding="ascii")
        self.sdk_executable.chmod(0o755)
        self.sdk_archive_probe = self.sdk / "SDK/archive-probe.txt"
        self.sdk_archive_probe.write_bytes(b"archive-probe:$Format:%H$\n")
        self.sdk_archive_probe.chmod(0o644)
        git(
            "add",
            "SDK/base.txt",
            "SDK/archive-probe.txt",
            cwd=self.sdk,
        )
        git("commit", "-q", "-m", "fixture base", cwd=self.sdk)
        self.sdk_parent_commit = git("rev-parse", "HEAD", cwd=self.sdk)
        git("add", "SDK/executable.sh", cwd=self.sdk)
        git("commit", "-q", "-m", "fixture executable", cwd=self.sdk)
        git("config", "--remove-section", "user", cwd=self.sdk)
        self.commit = git("rev-parse", "HEAD", cwd=self.sdk)
        self.tree = git("rev-parse", "HEAD^{tree}", cwd=self.sdk)
        (self.sdk / ".git/shallow").write_text(
            self.commit + "\n", encoding="ascii"
        )
        (self.sdk / ".git/shallow").chmod(0o644)
        self.fixture_archive_sha256 = hashlib.sha256(
            closed_git_archive(self.sdk, self.commit)
        ).hexdigest().upper()
        overlay = self.repo / "firmware/overlay/SDK/added.txt"
        overlay.parent.mkdir(parents=True)
        overlay.write_text("overlay\n", encoding="ascii")
        overlay.chmod(0o644)
        self.overlay_records = [
            {
                "destination": "SDK/added.txt",
                "source": "firmware/overlay/SDK/added.txt",
            }
        ]
        self.patch = self.repo / "firmware/patches/stage0/fixture.patch"
        self.patch.parent.mkdir(parents=True)
        self.patch.write_text(
            "diff --git a/SDK/base.txt b/SDK/base.txt\n"
            "--- a/SDK/base.txt\n"
            "+++ b/SDK/base.txt\n"
            "@@ -1 +1 @@\n"
            "-base\n"
            "+patched\n",
            encoding="ascii",
        )
        self.patch.chmod(0o644)
        self.source_executable = (
            self.repo / "firmware/tools/validate-button-evidence.py"
        )
        self.source_executable.parent.mkdir(parents=True, exist_ok=True)
        self.source_executable.write_text(
            "#!/usr/bin/env python3\nraise SystemExit(0)\n", encoding="ascii"
        )
        self.source_executable.chmod(0o755)
        self.commit_repository("source fixture")
        self.git_tool = {
            "path": "/usr/bin/git",
            "sha256": "587EF21868C948B883993E23209B86A72A6DDC06AAB1545C697FFC31075ACD4A",
            "version": "2.34.1",
        }
        self.runner = RecordingRunner()

    def tearDown(self):
        self.temp.cleanup()

    def commit_repository(self, message: str) -> None:
        git("add", "-A", cwd=self.repo)
        git("commit", "-q", "-m", message, cwd=self.repo)
        self.source_commit = git("rev-parse", "HEAD", cwd=self.repo)
        self.source_tree = git("rev-parse", "HEAD^{tree}", cwd=self.repo)
        self.source_commit_object = git_bytes(
            "cat-file", "commit", self.source_commit, cwd=self.repo
        )
        self.source_commit_epoch = independent_commit_epoch(self.source_commit_object)
        self.source_commit_tree = independent_commit_tree(self.source_commit_object)
        if self.source_commit_tree != self.source_tree:
            raise AssertionError("source fixture commit object does not bind its tree")

    def bootstrap_kwargs(self, output: Path) -> dict:
        return {
            "repository_root": self.repo,
            "sdk_root": self.sdk,
            "output_root": output,
            "expected_commit": self.commit,
            "expected_tree": self.tree,
            "overlay_records": self.overlay_records,
            "patch_path": self.patch,
            "forbidden_roots": (
                self.repo,
                self.sdk,
                self.toolchain_root,
                self.post_build_root,
            ),
            "allowed_patch_paths": ("SDK/base.txt",),
            "runner": self.runner,
        }

    def hardened_bootstrap_kwargs(self, output: Path) -> dict:
        return {
            "repository_root": self.repo,
            "sdk_root": self.sdk,
            "output_root": output,
            "expected_source_commit": self.source_commit,
            "expected_source_tree": self.source_tree,
            "expected_sdk_commit": self.commit,
            "expected_sdk_tree": self.tree,
            "overlay_records": self.overlay_records,
            "patch_path": self.patch,
            "allowed_patch_paths": ("SDK/base.txt",),
            "git_tool": self.git_tool,
            "runner": self.runner,
        }

    def call_bootstrap(self, output: Path, **overrides):
        parameters = inspect.signature(self.bootstrap.bootstrap_sdk).parameters
        fixed_tool_roots = overrides.pop(
            "_fixed_tool_roots", (self.toolchain_root, self.post_build_root)
        )
        if "expected_source_commit" in parameters:
            arguments = self.hardened_bootstrap_kwargs(output)
            translated = dict(overrides)
            if "expected_commit" in translated:
                translated["expected_sdk_commit"] = translated.pop("expected_commit")
            if "expected_tree" in translated:
                translated["expected_sdk_tree"] = translated.pop("expected_tree")
            translated.pop("forbidden_roots", None)
            arguments.update(translated)
        else:
            arguments = self.bootstrap_kwargs(output)
            arguments.update(overrides)
        fixture_archive_sha256 = self.fixture_archive_sha256
        with mock.patch.multiple(
            self.bootstrap,
            TOOLCHAIN_ROOT=Path(fixed_tool_roots[0]),
            POST_BUILD_ROOT=Path(fixed_tool_roots[1]),
            SDK_ARCHIVE_SHA256=fixture_archive_sha256,
            create=True,
        ):
            return self.bootstrap.bootstrap_sdk(**arguments)

    def call_hardened_bootstrap(self, output: Path, **overrides):
        fixed_tool_roots = overrides.pop(
            "_fixed_tool_roots", (self.toolchain_root, self.post_build_root)
        )
        arguments = self.hardened_bootstrap_kwargs(output)
        arguments.update(overrides)
        fixture_archive_sha256 = self.fixture_archive_sha256
        with mock.patch.multiple(
            self.bootstrap,
            TOOLCHAIN_ROOT=Path(fixed_tool_roots[0]),
            POST_BUILD_ROOT=Path(fixed_tool_roots[1]),
            SDK_ARCHIVE_SHA256=fixture_archive_sha256,
            create=True,
        ):
            return self.bootstrap.bootstrap_sdk(**arguments)

    def call_cli(self, arguments, runner, git_tool, fixed_tool_roots):
        fixture_archive_sha256 = getattr(self.bootstrap, "SDK_ARCHIVE_SHA256", None)
        if isinstance(runner, LockedSdkRunner):
            fixture_archive_sha256 = hashlib.sha256(
                closed_git_archive(runner.sdk_root, runner.archive_commit)
            ).hexdigest().upper()
        with mock.patch.multiple(
            self.bootstrap,
            TOOLCHAIN_ROOT=Path(fixed_tool_roots[0]),
            POST_BUILD_ROOT=Path(fixed_tool_roots[1]),
            SDK_ARCHIVE_SHA256=fixture_archive_sha256,
            create=True,
        ):
            return self.bootstrap.main(arguments, runner=runner, git_tool=git_tool)

    def run_bootstrap(self, output: Path):
        output.mkdir()
        return self.call_bootstrap(output)

    def make_cli_fixture(self, suffix="", parent=None):
        fixture_parent = Path(parent) if parent is not None else self.base
        fixture_parent.mkdir(parents=True, exist_ok=True)
        repository = fixture_parent / f"cli-repository{suffix}"
        sdk = fixture_parent / f"cli-installed-sdk{suffix}"
        toolchain = fixture_parent / f"cli-toolchain{suffix}"
        post_build = fixture_parent / f"cli-post-build{suffix}"
        for root in (repository, sdk, toolchain, post_build):
            root.mkdir()
        git("init", "-q", "-b", "codex/e87-local-rendering", cwd=repository)
        git("config", "user.email", "jethachan@gmail.com", cwd=repository)
        git("config", "user.name", "Jetha Chan", cwd=repository)
        git(
            "config",
            "remote.bootstrap.url",
            "/home/jethac/.cache/codex-transfer/factory-android-badges-e87.bundle",
            cwd=repository,
        )
        git(
            "config",
            "remote.bootstrap.fetch",
            "+refs/heads/*:refs/remotes/bootstrap/*",
            cwd=repository,
        )
        git(
            "config",
            "remote.origin.url",
            "https://github.com/jethac/factory-android-badges.git",
            cwd=repository,
        )
        git(
            "config",
            "remote.origin.fetch",
            "+refs/heads/*:refs/remotes/origin/*",
            cwd=repository,
        )
        git(
            "config",
            "branch.codex/e87-local-rendering.remote",
            "bootstrap",
            cwd=repository,
        )
        git(
            "config",
            "branch.codex/e87-local-rendering.merge",
            "refs/heads/codex/e87-local-rendering",
            cwd=repository,
        )

        git("init", "-q", "-b", "main", cwd=sdk)
        git("config", "user.email", "stage0@example.invalid", cwd=sdk)
        git("config", "user.name", "Stage0 Test", cwd=sdk)
        git(
            "config",
            "remote.origin.url",
            "https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200.git",
            cwd=sdk,
        )
        git(
            "config",
            "remote.origin.fetch",
            "+refs/heads/main:refs/remotes/origin/main",
            cwd=sdk,
        )
        git("config", "branch.main.remote", "origin", cwd=sdk)
        git("config", "branch.main.merge", "refs/heads/main", cwd=sdk)

        lock_root = repository / "firmware/locks"
        lock_root.mkdir(parents=True)
        lock_names = (
            "model1552-package.lock.json",
            "packaging.lock.json",
            "toolchain.lock.json",
        )
        for name in lock_names:
            lock_path = lock_root / name
            lock_path.write_bytes((ROOT / "firmware/locks" / name).read_bytes())
            lock_path.chmod(0o644)

        overlay_sources = (
            "firmware/overlay/SDK/apps/watch/include/e87/e87_stage0_adv.h",
            "firmware/overlay/SDK/apps/watch/include/e87/e87_stage0_app.h",
            "firmware/overlay/SDK/apps/watch/e87/e87_stage0_adv.c",
            "firmware/overlay/SDK/apps/watch/e87/e87_stage0_app.c",
            "firmware/overlay/SDK/apps/watch/e87/e87_stage0_ble.c",
            "firmware/overlay/SDK/apps/watch/board/br35/board_e87_1542/board_e87_1542.c",
            "firmware/overlay/SDK/apps/watch/board/br35/board_e87_1542/board_e87_1542_cfg.h",
        )
        for source in overlay_sources:
            path = repository / source
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"overlay:{source}\n", encoding="ascii")
            path.chmod(0o644)

        patch_targets = (
            "SDK/apps/watch/board/br35/board_config.h",
            "SDK/apps/watch/include/app_config.h",
            "SDK/apps/watch/app_main.c",
            "SDK/build/genFileList.c",
            "SDK/build/Makefile.mk",
        )
        patch_parts = []
        for target in patch_targets:
            path = sdk / target
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"base:{target}\n", encoding="ascii")
            path.chmod(0o644)
            patch_parts.append(
                f"diff --git a/{target} b/{target}\n"
                f"--- a/{target}\n"
                f"+++ b/{target}\n"
                "@@ -1 +1 @@\n"
                f"-base:{target}\n"
                f"+patched:{target}\n"
            )
        patch = repository / "firmware/patches/stage0/0001-e87-stage0-hooks.patch"
        patch.parent.mkdir(parents=True)
        patch.write_text("".join(patch_parts), encoding="ascii")
        patch.chmod(0o644)

        git("add", "-A", cwd=repository)
        git("commit", "-q", "-m", "closed CLI source fixture", cwd=repository)
        source_commit = git("rev-parse", "HEAD", cwd=repository)
        source_tree = git("rev-parse", "HEAD^{tree}", cwd=repository)
        source_commit_object = git_bytes(
            "cat-file", "commit", source_commit, cwd=repository
        )
        git("add", "-A", cwd=sdk)
        git("commit", "-q", "-m", "closed CLI SDK fixture", cwd=sdk)
        git("config", "--remove-section", "user", cwd=sdk)
        archive_commit = git("rev-parse", "HEAD", cwd=sdk)
        return {
            "archiveCommit": archive_commit,
            "overlaySources": overlay_sources,
            "patchTargets": patch_targets,
            "postBuildRoot": post_build,
            "repositoryRoot": repository,
            "sdkRoot": sdk,
            "sourceCommit": source_commit,
            "sourceCommitEpoch": independent_commit_epoch(source_commit_object),
            "sourceCommitObjectSha256": hashlib.sha256(
                source_commit_object
            ).hexdigest().upper(),
            "sourceTree": source_tree,
            "toolchainRoot": toolchain,
        }

    def test_valid_fixture_materializes_only_clean_sdk_overlay_and_patch(self):
        output = self.base / "output"
        before = snapshot_tree(self.sdk)
        receipt = self.run_bootstrap(output)
        self.assertFalse((self.repo / ".git/shallow").exists())
        self.assertEqual(
            (self.sdk / ".git/shallow").read_bytes(),
            (self.commit + "\n").encode("ascii"),
        )
        self.assertEqual((output / "SDK/base.txt").read_text(), "patched\n")
        self.assertEqual((output / "SDK/added.txt").read_text(), "overlay\n")
        self.assertEqual(
            (output / "SDK/archive-probe.txt").read_bytes(),
            self.sdk_archive_probe.read_bytes(),
        )
        self.assertEqual(
            (output / "SDK/executable.sh").read_bytes(),
            self.sdk_executable.read_bytes(),
        )
        expected_modes = {
            self.repo / self.overlay_records[0]["source"]: 0o644,
            self.source_executable: 0o755,
            self.sdk / "SDK/base.txt": 0o644,
            self.sdk_archive_probe: 0o644,
            self.sdk_executable: 0o755,
            output / "SDK/base.txt": 0o644,
            output / "SDK/added.txt": 0o644,
            output / "SDK/archive-probe.txt": 0o644,
            output / "SDK/executable.sh": 0o755,
        }
        for path, expected_mode in expected_modes.items():
            with self.subTest(exact_mode=path.relative_to(self.base).as_posix()):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), expected_mode)
        for root, path in (
            (self.repo, self.source_executable),
            (self.sdk, self.sdk_archive_probe),
            (self.sdk, self.sdk_executable),
        ):
            relative = path.relative_to(root).as_posix()
            self.assertEqual(
                git("rev-parse", f"HEAD:{relative}", cwd=root),
                git_object_sha1("blob", path.read_bytes()),
            )
        self.assertEqual(
            hashlib.sha256((output / "SDK/executable.sh").read_bytes()).digest(),
            hashlib.sha256(self.sdk_executable.read_bytes()).digest(),
        )
        self.assertFalse((output / ".git").exists())
        self.assertEqual(
            set(receipt),
            {
                "commands",
                "gitTool",
                "outputTreeSha256",
                "overlay",
                "patch",
                "schema",
                "sdkCommit",
                "sdkTree",
                "sourceCommit",
                "sourceCommitEpoch",
                "sourceCommitObjectSha256",
                "sourceTree",
                "validations",
            },
        )
        self.assertEqual(receipt["schema"], "e87-stage0-bootstrap-receipt-v1")
        self.assertEqual((receipt["sdkCommit"], receipt["sdkTree"]), (self.commit, self.tree))
        self.assertEqual(
            (receipt["sourceCommit"], receipt["sourceTree"]),
            (self.source_commit, self.source_tree),
        )
        self.assertEqual(
            git_object_sha1("commit", self.source_commit_object), self.source_commit
        )
        self.assertEqual(
            independent_commit_tree(self.source_commit_object), self.source_tree
        )
        self.assertIs(type(receipt["sourceCommitEpoch"]), int)
        self.assertEqual(receipt["sourceCommitEpoch"], self.source_commit_epoch)
        self.assertEqual(
            receipt["sourceCommitObjectSha256"],
            hashlib.sha256(self.source_commit_object).hexdigest().upper(),
        )
        self.assertEqual(receipt["gitTool"], self.git_tool)
        expected_commands = command_receipt_records(
            self.runner,
            repository_root=self.repo,
            sdk_root=self.sdk,
            output_root=output,
            git_tool=self.git_tool,
        )
        self.assertEqual(receipt["commands"], expected_commands)
        self.assertEqual(
            [record["role"] for record in receipt["commands"]],
            list(COMMAND_ROLES),
        )
        self.assertEqual(
            len({record["role"] for record in receipt["commands"]}),
            len(COMMAND_ROLES),
        )
        for record in receipt["commands"]:
            self.assertEqual(set(record), COMMAND_RECORD_KEYS)
            self.assertEqual(record["exitCode"], 0)
            self.assertEqual(record["toolSha256"], self.git_tool["sha256"])
            self.assertEqual(record["toolVersion"], self.git_tool["version"])
            self.assertNotIn(str(self.base), json.dumps(record, sort_keys=True))
        self.assertEqual(receipt["validations"], VALIDATION_RESULTS)
        self.assertIsNone(
            self.bootstrap.validate_bootstrap_receipt(
                receipt,
                require_locks=False,
                expected_commands=expected_commands,
            )
        )
        overlay_bytes = (self.repo / self.overlay_records[0]["source"]).read_bytes()
        self.assertEqual(
            receipt["overlay"],
            [
                {
                    "destination": "SDK/added.txt",
                    "sha256": hashlib.sha256(overlay_bytes).hexdigest().upper(),
                    "size": len(overlay_bytes),
                    "source": "firmware/overlay/SDK/added.txt",
                }
            ],
        )
        patch_bytes = self.patch.read_bytes()
        self.assertEqual(
            receipt["patch"],
            {
                "paths": ["SDK/base.txt"],
                "sha256": hashlib.sha256(patch_bytes).hexdigest().upper(),
                "size": len(patch_bytes),
            },
        )
        self.assertEqual(receipt["outputTreeSha256"], independent_tree_sha256(output))
        apply_evidence = [
            record
            for record in receipt["commands"]
            if record["role"] in ("patch-check", "patch-apply")
        ]
        expected_stdin = {
            "sha256": receipt["patch"]["sha256"],
            "size": receipt["patch"]["size"],
        }
        self.assertEqual(
            [record["stdin"] for record in apply_evidence],
            [expected_stdin, expected_stdin],
        )
        self.assertTrue(
            all(
                record["stdin"] is None
                for record in receipt["commands"]
                if record["role"] not in ("patch-check", "patch-apply")
            )
        )
        self.assertEqual(snapshot_tree(self.sdk), before)

        baseline_output = snapshot_tree(output)
        baseline_receipt = self.bootstrap.canonical_json(receipt)
        controller_root = self.repo / ".superpowers"
        controller_first = controller_root / "sdd/controller-first.txt"
        controller_first.parent.mkdir(parents=True)
        controller_first.write_bytes(b"first controller-only material\n")
        controller_first.chmod(0o644)
        first_controller_sha = hashlib.sha256(
            controller_first.read_bytes()
        ).hexdigest().upper().encode("ascii")
        first_controller_output = self.base / "controller-material-first-output"
        self.runner = RecordingRunner()
        first_controller_receipt = self.run_bootstrap(first_controller_output)
        controller_first.unlink()
        controller_second = controller_root / "review/nested/controller-second.txt"
        controller_second.parent.mkdir(parents=True)
        controller_second.write_bytes(
            b"different name and different controller-only bytes\n"
        )
        controller_second.chmod(0o644)
        second_controller_sha = hashlib.sha256(
            controller_second.read_bytes()
        ).hexdigest().upper().encode("ascii")
        second_controller_output = self.base / "controller-material-second-output"
        self.runner = RecordingRunner()
        second_controller_receipt = self.run_bootstrap(second_controller_output)
        for controller_receipt, controller_output in (
            (first_controller_receipt, first_controller_output),
            (second_controller_receipt, second_controller_output),
        ):
            self.assertEqual(snapshot_tree(controller_output), baseline_output)
            self.assertEqual(
                self.bootstrap.canonical_json(controller_receipt), baseline_receipt
            )
            serialized = self.bootstrap.canonical_json(controller_receipt)
            self.assertNotIn(b".superpowers", serialized)
            self.assertNotIn(first_controller_sha, serialized)
            self.assertNotIn(second_controller_sha, serialized)

    def test_git_and_apply_subprocesses_use_exact_arrays_cwd_env_and_no_shell(self):
        syntax = ast.parse(TOOL.read_text(encoding="utf-8"), filename=str(TOOL))
        parent = {}
        for owner in ast.walk(syntax):
            for child in ast.iter_child_nodes(owner):
                parent[child] = owner

        process_members = {
            "subprocess": {
                "call",
                "check_call",
                "check_output",
                "getoutput",
                "getstatusoutput",
                "Popen",
                "run",
            },
            "os": {"popen", "system"},
        }

        def is_os_process_member(name):
            return name in process_members["os"] or name.startswith(
                ("exec", "spawn", "posix_spawn")
            )

        module_aliases = {"subprocess": {"subprocess"}, "os": {"os"}}
        callable_aliases = set()
        forbidden_process_calls = []
        for node in ast.walk(syntax):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in module_aliases:
                        module_aliases[alias.name].add(alias.asname or alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module in module_aliases:
                for alias in node.names:
                    member = alias.name
                    if member == "*" or (
                        member in process_members[node.module]
                        or (node.module == "os" and is_os_process_member(member))
                    ):
                        callable_aliases.add(alias.asname or member)
                        forbidden_process_calls.append(
                            (node.lineno, f"from {node.module} import {member}")
                        )

        def attribute_identity(node):
            if not isinstance(node, ast.Attribute) or not isinstance(
                node.value, ast.Name
            ):
                return None
            for module_name, aliases in module_aliases.items():
                if node.value.id not in aliases:
                    continue
                if node.attr in process_members[module_name] or (
                    module_name == "os" and is_os_process_member(node.attr)
                ):
                    return module_name, node.attr
            return None

        changed = True
        while changed:
            changed = False
            for node in ast.walk(syntax):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                value = node.value
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                target_names = [target.id for target in targets if isinstance(target, ast.Name)]
                if isinstance(value, ast.Name):
                    for module_name, aliases in module_aliases.items():
                        if value.id in aliases:
                            before = len(aliases)
                            aliases.update(target_names)
                            changed |= len(aliases) != before
                    if value.id in callable_aliases:
                        before = len(callable_aliases)
                        callable_aliases.update(target_names)
                        changed |= len(callable_aliases) != before
                elif attribute_identity(value) is not None:
                    before = len(callable_aliases)
                    callable_aliases.update(target_names)
                    changed |= len(callable_aliases) != before

        def enclosing_function(node):
            cursor = parent.get(node)
            while cursor is not None and not isinstance(
                cursor, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
            ):
                cursor = parent.get(cursor)
            return cursor

        def is_exact_system_runner(call, identity):
            function = enclosing_function(call)
            if identity != ("subprocess", "run") or not isinstance(
                function, ast.FunctionDef
            ):
                return False
            if function.name != "_system_runner" or len(function.body) != 1:
                return False
            statement = function.body[0]
            if not isinstance(statement, ast.Return) or statement.value is not call:
                return False
            arguments = function.args
            if (
                [argument.arg for argument in arguments.args] != ["argv"]
                or arguments.vararg is not None
                or arguments.kwonlyargs
                or arguments.defaults
                or arguments.kw_defaults
                or arguments.kwarg is None
                or arguments.kwarg.arg != "kwargs"
            ):
                return False
            return (
                len(call.args) == 1
                and isinstance(call.args[0], ast.Name)
                and call.args[0].id == "argv"
                and len(call.keywords) == 1
                and call.keywords[0].arg is None
                and isinstance(call.keywords[0].value, ast.Name)
                and call.keywords[0].value.id == "kwargs"
            )

        for node in ast.walk(syntax):
            if isinstance(node, ast.Call):
                identity = attribute_identity(node.func)
                if identity is not None and not is_exact_system_runner(node, identity):
                    forbidden_process_calls.append(
                        (node.lineno, ast.unparse(node.func))
                    )
                elif isinstance(node.func, ast.Name) and node.func.id in callable_aliases:
                    forbidden_process_calls.append((node.lineno, node.func.id))
                elif (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "getattr"
                    and len(node.args) >= 2
                    and isinstance(node.args[0], ast.Name)
                    and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)
                ):
                    for module_name, aliases in module_aliases.items():
                        member = node.args[1].value
                        if node.args[0].id in aliases and (
                            member in process_members[module_name]
                            or (module_name == "os" and is_os_process_member(member))
                        ):
                            forbidden_process_calls.append(
                                (node.lineno, ast.unparse(node))
                            )
            identity = attribute_identity(node)
            if identity is None:
                continue
            owner = parent.get(node)
            if isinstance(owner, ast.Call) and owner.func is node:
                continue
            forbidden_process_calls.append(
                (node.lineno, "captured " + ast.unparse(node))
            )
        self.assertEqual(
            sorted(set(forbidden_process_calls)),
            [],
            "no import, default, assignment, getattr, or direct process bypass may "
            "exist outside the one exact system-runner adapter",
        )
        system_runner_definitions = [
            node
            for node in ast.walk(syntax)
            if isinstance(node, ast.FunctionDef) and node.name == "_system_runner"
        ]
        self.assertEqual(
            len(system_runner_definitions),
            1,
            "production must expose exactly one structurally checked system adapter",
        )
        system_runner_references = [
            node
            for node in ast.walk(syntax)
            if isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id == "_system_runner"
        ]

        def is_runner_default_selection(reference):
            cursor = parent.get(reference)
            while cursor is not None and not isinstance(
                cursor, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
            ):
                if isinstance(cursor, ast.Call) and cursor.func is reference:
                    return False
                if isinstance(cursor, ast.keyword) and cursor.arg == "runner":
                    return True
                if isinstance(cursor, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == "runner"
                    for target in cursor.targets
                ):
                    return True
                if (
                    isinstance(cursor, ast.AnnAssign)
                    and isinstance(cursor.target, ast.Name)
                    and cursor.target.id == "runner"
                ):
                    return True
                cursor = parent.get(cursor)
            if not isinstance(cursor, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return False
            positional = [*cursor.args.posonlyargs, *cursor.args.args]
            defaults = [
                *([None] * (len(positional) - len(cursor.args.defaults))),
                *cursor.args.defaults,
            ]
            for argument, default in zip(positional, defaults, strict=True):
                if argument.arg == "runner" and default is not None:
                    if any(node is reference for node in ast.walk(default)):
                        return True
            for argument, default in zip(
                cursor.args.kwonlyargs, cursor.args.kw_defaults, strict=True
            ):
                if argument.arg == "runner" and default is not None:
                    if any(node is reference for node in ast.walk(default)):
                        return True
            return False

        self.assertEqual(
            len(system_runner_references),
            1,
            "the system adapter may have only one default-selection reference",
        )
        self.assertTrue(
            is_runner_default_selection(system_runner_references[0]),
            "the system adapter must never be an additional direct launch path",
        )
        output = self.base / "command-output"
        receipt = self.run_bootstrap(output)
        commands = [call[0] for call in self.runner.calls]
        def apply_command(*arguments):
            return ["/usr/bin/git", *GIT_CONFIG_PREFIX, *arguments]

        def repository_checks(root, commit_object=None):
            checks = [
                repository_git_command(root, "rev-parse", "HEAD"),
                repository_git_command(root, "rev-parse", "HEAD^{tree}"),
                repository_git_command(
                    root, "status", "--porcelain=v1", "--untracked-files=no"
                ),
                repository_git_command(
                    root, "ls-files", "-v", "--stage", "-z", "--"
                ),
                repository_git_command(
                    root,
                    "diff",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--exit-code",
                    "--cached",
                    "HEAD",
                    "--",
                ),
                repository_git_command(
                    root,
                    "diff",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--exit-code",
                    "--",
                ),
            ]
            if commit_object is not None:
                checks.append(
                    repository_git_command(
                        root, "cat-file", "commit", commit_object
                    )
                )
            return checks

        self.assertEqual(commands, [
            ["/usr/bin/git", "--version"],
            *repository_checks(self.repo, self.source_commit),
            *repository_checks(self.sdk),
            repository_git_command(self.sdk, "archive", "--format=tar", self.commit),
            repository_git_command(self.sdk, "archive", "--format=tar", self.commit),
            apply_command("apply", "--no-index", "--check", "-"),
            apply_command("apply", "--no-index", "-"),
            *repository_checks(self.repo, self.source_commit),
            *repository_checks(self.sdk),
        ])
        self.assertEqual(
            receipt["commands"],
            command_receipt_records(
                self.runner,
                repository_root=self.repo,
                sdk_root=self.sdk,
                output_root=output,
                git_tool=self.git_tool,
            ),
        )
        self.assertFalse(any(any(word in argument.lower() for word in ("fetch", "pull", "clone", "http://", "https://")) for command in commands for argument in command))
        patch_data = self.patch.read_bytes()
        apply_cwds = {
            Path(kwargs["cwd"])
            for argv, kwargs in self.runner.calls
            if git_verb(argv) == "apply"
        }
        self.assertEqual(len(apply_cwds), 1)
        owned_staging_root = apply_cwds.pop()
        self.assertNotEqual(owned_staging_root, output)
        self.assertEqual(owned_staging_root.parent, output.parent)
        for index, (argv, kwargs) in enumerate(self.runner.calls):
            self.assertIsInstance(argv, list)
            self.assertIs(kwargs["shell"], False)
            self.assertIs(kwargs["check"], False)
            self.assertEqual(kwargs["stdout"], subprocess.PIPE)
            self.assertEqual(kwargs["stderr"], subprocess.PIPE)
            expected_env = {
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
            if git_verb(argv) == "apply":
                expected_env["GIT_CEILING_DIRECTORIES"] = str(owned_staging_root)
                self.assertIsNone(git_bound_root(argv))
                self.assertNotIn("stdin", kwargs)
                self.assertEqual(kwargs["input"], patch_data)
                self.assertEqual(Path(kwargs["cwd"]), owned_staging_root)
            elif argv == ["/usr/bin/git", "--version"]:
                self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
                self.assertNotIn("input", kwargs)
                self.assertEqual(Path(kwargs["cwd"]), self.repo)
            else:
                self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
                self.assertNotIn("input", kwargs)
                bound_root = git_bound_root(argv)
                self.assertIn(bound_root, (self.repo, self.sdk))
                self.assertEqual(Path(kwargs["cwd"]), bound_root)
            self.assertEqual(kwargs["env"], expected_env)

        derivation = self.bootstrap._derive_command_receipt_records
        derivation_parameters = inspect.signature(derivation).parameters
        self.assertEqual(
            list(derivation_parameters),
            ["trace", "repository_root", "sdk_root", "output_root", "git_tool"],
        )
        self.assertTrue(
            all(
                derivation_parameters[name].kind
                is inspect.Parameter.KEYWORD_ONLY
                for name in (
                    "repository_root",
                    "sdk_root",
                    "output_root",
                    "git_tool",
                )
            )
        )
        derivation_output = self.base / "command-derivation-output"
        derivation_output.mkdir()
        self.runner = RecordingRunner()
        with mock.patch.object(
            self.bootstrap,
            "_derive_command_receipt_records",
            wraps=derivation,
        ) as derivation_spy:
            derivation_receipt = self.call_bootstrap(derivation_output)
        derivation_spy.assert_called_once()
        derivation_args, derivation_kwargs = derivation_spy.call_args
        self.assertEqual(len(derivation_args), 1)
        raw_trace = derivation_args[0]
        self.assertEqual(len(raw_trace), len(COMMAND_ROLES))
        self.assertIsNot(raw_trace, derivation_receipt["commands"])
        self.assertFalse(
            any(
                raw is normalized
                for raw, normalized in zip(
                    raw_trace, derivation_receipt["commands"], strict=True
                )
            )
        )
        self.assertEqual(
            derivation_kwargs,
            {
                "git_tool": self.git_tool,
                "output_root": derivation_output,
                "repository_root": self.repo,
                "sdk_root": self.sdk,
            },
        )
        self.assertEqual(
            derivation_receipt["commands"],
            command_receipt_records(
                self.runner,
                repository_root=self.repo,
                sdk_root=self.sdk,
                output_root=derivation_output,
                git_tool=self.git_tool,
            ),
        )

        blocked_process = mock.Mock(
            side_effect=AssertionError("bootstrap bypassed its injected runner")
        )
        subprocess_patches = {
            name: blocked_process
            for name in (
                "Popen",
                "call",
                "check_call",
                "check_output",
                "getoutput",
                "getstatusoutput",
                "run",
            )
            if hasattr(subprocess, name)
        }
        os_patches = {
            name: blocked_process
            for name in dir(os)
            if name in {"popen", "system"}
            or name.startswith(("exec", "spawn", "posix_spawn"))
        }
        reloaded_name = "e87_stage0_bootstrap_prepatched_process_apis"
        try:
            with mock.patch.multiple(subprocess, **subprocess_patches), mock.patch.multiple(
                os, **os_patches
            ):
                reloaded = load_tool(reloaded_name)
                bypass_output = self.base / "direct-process-bypass-output"
                bypass_output.mkdir()
                bypass_runner = RecordingRunner()
                original_bootstrap = self.bootstrap
                self.bootstrap = reloaded
                try:
                    self.call_bootstrap(bypass_output, runner=bypass_runner)
                finally:
                    self.bootstrap = original_bootstrap
            blocked_process.assert_not_called()
            self.assertEqual(
                len(bypass_runner.calls),
                len(COMMAND_ROLES),
                "every child process must traverse the injected runner exactly once",
            )
        finally:
            sys.modules.pop(reloaded_name, None)

        installed_bytes = (self.sdk / "SDK/base.txt").read_bytes()
        (self.sdk / "SDK/base.txt").write_text(
            "replacement-object-content\n", encoding="ascii"
        )
        git("add", "SDK/base.txt", cwd=self.sdk)
        git(
            "-c",
            "user.email=stage0@example.invalid",
            "-c",
            "user.name=Stage0 Test",
            "commit",
            "-q",
            "-m",
            "replacement object fixture",
            cwd=self.sdk,
        )
        replacement_commit = git("rev-parse", "HEAD", cwd=self.sdk)
        git("reset", "--hard", "-q", self.commit, cwd=self.sdk)
        git("replace", self.commit, replacement_commit, cwd=self.sdk)
        replacement_output = self.base / "replacement-object-output"
        self.runner = RecordingRunner()
        try:
            self.run_bootstrap(replacement_output)
        finally:
            git("replace", "-d", self.commit, cwd=self.sdk)
        self.assertEqual((self.sdk / "SDK/base.txt").read_bytes(), installed_bytes)
        self.assertEqual(git("rev-parse", "HEAD", cwd=self.sdk), self.commit)
        self.assertEqual(git("status", "--porcelain=v1", cwd=self.sdk), "")
        self.assertEqual(
            (replacement_output / "SDK/base.txt").read_bytes(), b"patched\n"
        )

    def test_two_empty_roots_produce_byte_identical_trees_and_receipts(self):
        first = self.base / "first"
        second = self.base / "second"
        original_umask = os.umask(0o022)
        try:
            self.runner = RecordingRunner()
            first_receipt = self.run_bootstrap(first)
        finally:
            os.umask(original_umask)
        original_umask = os.umask(0o077)
        try:
            self.runner = RecordingRunner()
            second_receipt = self.run_bootstrap(second)
        finally:
            os.umask(original_umask)
        self.assertEqual(first_receipt, second_receipt)
        self.assertEqual(
            self.bootstrap.tree_sha256(first), self.bootstrap.tree_sha256(second)
        )
        self.assertEqual(
            self.bootstrap.canonical_json(first_receipt),
            self.bootstrap.canonical_json(second_receipt),
        )
        expected_output_modes = {
            "SDK/added.txt": 0o644,
            "SDK/archive-probe.txt": 0o644,
            "SDK/base.txt": 0o644,
            "SDK/executable.sh": 0o755,
        }
        for root in (first, second):
            for relative, expected_mode in expected_output_modes.items():
                with self.subTest(
                    umask_output_mode=f"{root.name}:{relative}"
                ):
                    self.assertEqual(
                        stat.S_IMODE((root / relative).stat().st_mode),
                        expected_mode,
                    )
        mode_target = first / "SDK/executable.sh"
        independent_before = independent_tree_sha256(first)
        tool_before = self.bootstrap.tree_sha256(first)
        mode_target.chmod(0o644)
        try:
            with self.subTest(tree_digest="binds-file-mode"):
                self.assertNotEqual(independent_tree_sha256(first), independent_before)
                self.assertNotEqual(self.bootstrap.tree_sha256(first), tool_before)
        finally:
            mode_target.chmod(0o755)
        self.assertEqual(independent_tree_sha256(first), independent_before)
        directory_target = first / "SDK"
        tool_before = self.bootstrap.tree_sha256(first)
        directory_target.chmod(0o700)
        try:
            with self.subTest(tree_digest="ignores-host-directory-mode"):
                self.assertEqual(independent_tree_sha256(first), independent_before)
                self.assertEqual(self.bootstrap.tree_sha256(first), tool_before)
        finally:
            directory_target.chmod(0o755)
        self.assertEqual(independent_tree_sha256(first), independent_before)

        unrelated = self.base / "unrelated-git-ancestor"
        unrelated.mkdir()
        git("init", "-q", cwd=unrelated)
        git("config", "user.email", "unrelated@example.invalid", cwd=unrelated)
        git("config", "user.name", "Unrelated Repository", cwd=unrelated)
        sentinel = unrelated / "ancestor-sentinel"
        sentinel.write_bytes(b"unrelated repository must remain untouched\n")
        git("add", "ancestor-sentinel", cwd=unrelated)
        git("commit", "-q", "-m", "unrelated ancestor", cwd=unrelated)
        config_path = unrelated / ".git/config"
        index_path = unrelated / ".git/index"
        info_attributes = unrelated / ".git/info/attributes"
        config_before = config_path.read_bytes()
        index_before = index_path.read_bytes()
        sentinel_before = sentinel.read_bytes()
        git_metadata_before = snapshot_tree(unrelated / ".git")

        ancestor_cases = (
            (
                "malformed-local-config",
                lambda: config_path.write_bytes(config_before + b"\n[broken\n"),
                lambda: config_path.write_bytes(config_before),
            ),
            (
                "malformed-index",
                lambda: index_path.write_bytes(b"hostile unrelated index\n"),
                lambda: index_path.write_bytes(index_before),
            ),
            (
                "hostile-info-attributes",
                lambda: info_attributes.write_bytes(b"SDK/base.txt export-ignore\n"),
                lambda: info_attributes.unlink(),
            ),
        )
        for index, (name, mutation, restoration) in enumerate(ancestor_cases):
            output = unrelated / "generated" / f"output-{index}"
            output.mkdir(parents=True)
            runner = RecordingRunner()
            mutation()
            try:
                with self.subTest(unrelated_git_ancestor=name):
                    try:
                        receipt = self.call_bootstrap(output, runner=runner)
                    except ValueError as error:
                        self.fail(
                            f"git apply discovered unrelated ancestor state: {error}"
                        )
                    self.assertEqual(
                        (output / "SDK/base.txt").read_bytes(), b"patched\n"
                    )
                    self.assertEqual(
                        receipt["outputTreeSha256"],
                        independent_tree_sha256(output),
                    )
                    apply_calls = [
                        call for call in runner.calls if git_verb(call[0]) == "apply"
                    ]
                    self.assertEqual(
                        [git_arguments(call[0]) for call in apply_calls],
                        [
                            ["apply", "--no-index", "--check", "-"],
                            ["apply", "--no-index", "-"],
                        ],
                    )
                    apply_cwds = {Path(call[1]["cwd"]) for call in apply_calls}
                    self.assertEqual(len(apply_cwds), 1)
                    owned_staging_root = apply_cwds.pop()
                    self.assertNotEqual(owned_staging_root, output)
                    self.assertEqual(owned_staging_root.parent, output.parent)
                    self.assertTrue(
                        all(
                            call[1]["env"].get("GIT_CEILING_DIRECTORIES")
                            == str(owned_staging_root)
                            for call in apply_calls
                        )
                    )
            finally:
                restoration()
            self.assertEqual(config_path.read_bytes(), config_before)
            self.assertEqual(index_path.read_bytes(), index_before)
            self.assertEqual(sentinel.read_bytes(), sentinel_before)
            self.assertFalse(info_attributes.exists() or info_attributes.is_symlink())
            self.assertEqual(snapshot_tree(unrelated / ".git"), git_metadata_before)
            self.assertFalse((unrelated / "SDK").exists())

    def test_wrong_commit_tree_or_dirty_installed_sdk_is_rejected_before_output_write(self):
        cases = []
        cases.append(("commit", "0" * 40, self.tree))
        cases.append(("tree", self.commit, "0" * 40))
        for name, commit, tree in cases:
            output = self.base / ("bad-" + name)
            output.mkdir()
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.call_bootstrap(
                        output,
                        expected_commit=commit,
                        expected_tree=tree,
                    )
                self.assertEqual(list(output.iterdir()), [])
        (self.sdk / "SDK/base.txt").write_text("dirty\n", encoding="ascii")
        output = self.base / "dirty-output"
        output.mkdir()
        with self.assertRaises(ValueError):
            self.call_bootstrap(output)
        self.assertEqual(list(output.iterdir()), [])

    def test_output_root_must_be_absolute_empty_real_and_outside_every_forbidden_root(self):
        relative_absolute = self.base / "relative-output"
        relative_absolute.mkdir()
        nonempty = self.base / "nonempty"
        nonempty.mkdir()
        (nonempty / "sentinel").write_text("keep", encoding="ascii")
        inside_repo = self.repo / "generated"
        inside_repo.mkdir()
        inside_sdk = self.sdk / "generated"
        inside_sdk.mkdir()
        inside_tools = self.toolchain_root / "generated"
        inside_tools.mkdir()
        real = self.base / "real"
        real.mkdir()
        symlink = self.base / "linked"
        symlink.symlink_to(real, target_is_directory=True)
        alias_parent = self.base / "alias-parent"
        alias_parent.symlink_to(real, target_is_directory=True)
        under_alias_parent = alias_parent / "nested"
        under_alias_parent.mkdir()
        for name, candidate in (
            ("nonempty", nonempty),
            ("inside-repository", inside_repo),
            ("inside-installed-sdk", inside_sdk),
            ("inside-installed-tools", inside_tools),
            ("symlink", symlink),
            ("parent-symlink", under_alias_parent),
        ):
            with self.subTest(name=name):
                self.runner = RecordingRunner()
                with self.assertRaises(ValueError):
                    self.call_bootstrap(candidate)
                self.assertEqual(self.runner.calls, [])

        original_cwd = Path.cwd()
        self.runner = RecordingRunner()
        try:
            os.chdir(self.base)
            with self.subTest(name="existing-relative"):
                with self.assertRaisesRegex(ValueError, "absolute"):
                    self.call_bootstrap(Path("relative-output"))
        finally:
            os.chdir(original_cwd)
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(list(relative_absolute.iterdir()), [])

        def repository_checks(root, commit_object=None):
            checks = [
                repository_git_command(root, "rev-parse", "HEAD"),
                repository_git_command(root, "rev-parse", "HEAD^{tree}"),
                repository_git_command(
                    root, "status", "--porcelain=v1", "--untracked-files=no"
                ),
                repository_git_command(
                    root, "ls-files", "-v", "--stage", "-z", "--"
                ),
                repository_git_command(
                    root,
                    "diff",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--exit-code",
                    "--cached",
                    "HEAD",
                    "--",
                ),
                repository_git_command(
                    root,
                    "diff",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--exit-code",
                    "--",
                ),
            ]
            if commit_object is not None:
                checks.append(
                    repository_git_command(root, "cat-file", "commit", commit_object)
                )
            return checks

        expected_through_archive = [
            ["/usr/bin/git", "--version"],
            *repository_checks(self.repo, self.source_commit),
            *repository_checks(self.sdk),
            repository_git_command(self.sdk, "archive", "--format=tar", self.commit),
        ]

        for index, target_kind in enumerate(("sentinel-target", "empty-target")):
            with self.subTest(output_rebind=f"one-way-{target_kind}"):
                attacker = self.base / f"output-rebind-attacker-{index}"
                attacker.mkdir()
                if target_kind == "sentinel-target":
                    attacker_sentinel = attacker / "sentinel.txt"
                    attacker_sentinel.write_bytes(
                        b"outside output sentinel must survive exactly\n"
                    )
                    attacker_sentinel.chmod(0o644)
                attacker_before = snapshot_tree(attacker)
                attacker_stat = attacker.stat(follow_symlinks=False)
                one_way_output = self.base / f"output-rebind-one-way-{index}"
                one_way_output.mkdir()
                one_way_runner = OutputRebindRunner(
                    one_way_output,
                    attacker,
                    trigger_verb="archive",
                )
                try:
                    with self.assertRaises(ValueError):
                        self.call_bootstrap(one_way_output, runner=one_way_runner)
                    self.assertTrue(one_way_runner.mutated)
                    self.assertEqual(
                        [call[0] for call in one_way_runner.calls],
                        expected_through_archive,
                        "output rebinding must be rejected immediately after archive",
                    )
                    self.assertEqual(snapshot_tree(attacker), attacker_before)
                    self.assertEqual(
                        OutputRebindRunner.write_metadata(
                            attacker.stat(follow_symlinks=False)
                        ),
                        OutputRebindRunner.write_metadata(attacker_stat),
                        "the rebound target was written and then cleaned",
                    )
                    self.assertEqual(snapshot_tree(one_way_runner.held_root), [])
                    self.assertEqual(
                        OutputRebindRunner.identity(
                            one_way_runner.held_root.stat(follow_symlinks=False)
                        ),
                        OutputRebindRunner.identity(
                            one_way_runner.validated_output_stat
                        ),
                    )
                    self.assertEqual(
                        OutputRebindRunner.identity(
                            one_way_output.parent.stat(follow_symlinks=False)
                        ),
                        OutputRebindRunner.identity(one_way_runner.parent_stat),
                    )
                finally:
                    one_way_runner.restore_now()
                self.assertTrue(
                    one_way_output.is_dir() and not one_way_output.is_symlink()
                )
                self.assertEqual(list(one_way_output.iterdir()), [])
                self.assertFalse(one_way_runner.held_root.exists())

        aba_output = self.base / "output-rebind-aba"
        aba_output.mkdir()
        aba_initial_stat = aba_output.stat(follow_symlinks=False)
        aba_runner = OutputRebindRunner(
            aba_output,
            aba_output,
            trigger_verb="archive",
            restore_after_verb="archive",
        )
        aba_runner.symlink_target = aba_runner.held_root
        with self.subTest(output_rebind="rename-symlink-aba-during-archive"):
            try:
                with self.assertRaises(ValueError):
                    self.call_bootstrap(aba_output, runner=aba_runner)
                self.assertTrue(aba_runner.mutated)
                self.assertTrue(aba_runner.restored)
                self.assertEqual(
                    [call[0] for call in aba_runner.calls],
                    expected_through_archive,
                    "an archive-window ABA must stop before extraction or apply",
                )
                self.assertEqual(snapshot_tree(aba_output), [])
                final_stat = aba_output.stat(follow_symlinks=False)
                self.assertEqual(
                    (final_stat.st_dev, final_stat.st_ino, final_stat.st_mtime_ns),
                    (
                        aba_initial_stat.st_dev,
                        aba_initial_stat.st_ino,
                        aba_initial_stat.st_mtime_ns,
                    ),
                    "validated output inode was materialized and later cleaned",
                )
                self.assertEqual(
                    OutputRebindRunner.identity(
                        aba_output.parent.stat(follow_symlinks=False)
                    ),
                    OutputRebindRunner.identity(aba_runner.parent_stat),
                )
                self.assertIsNotNone(aba_runner.parent_after_mutation)
                self.assertIsNotNone(aba_runner.parent_after_restore)
            finally:
                aba_runner.restore_now()
            self.assertTrue(aba_output.is_dir() and not aba_output.is_symlink())
            self.assertEqual(list(aba_output.iterdir()), [])
            self.assertFalse(aba_runner.held_root.exists())

    def test_overlay_and_patch_paths_reject_traversal_absolute_symlink_and_undeclared_destination(self):
        outside = self.base / "outside.txt"
        outside.write_text("outside\n", encoding="ascii")
        linked = self.repo / "firmware/overlay/SDK/link.txt"
        linked.symlink_to(outside)
        self.commit_repository("tracked overlay symlink")
        bad_records = [
            [{"source": "../outside.txt", "destination": "SDK/x"}],
            [{"source": str(outside), "destination": "SDK/x"}],
            [{"source": "firmware/overlay/SDK/link.txt", "destination": "SDK/x"}],
            [{"source": "firmware/overlay/SDK/added.txt", "destination": "../x"}],
            [{"source": "firmware/overlay/SDK/added.txt", "destination": "/tmp/x"}],
        ]
        for index, records in enumerate(bad_records):
            output = self.base / ("bad-path-" + str(index))
            output.mkdir()
            with self.subTest(records=records):
                with self.assertRaises(ValueError):
                    self.call_bootstrap(output, overlay_records=records)
                self.assertEqual(list(output.iterdir()), [])

    def test_materialized_sdk_symlink_cannot_redirect_an_overlay_destination(self):
        outside = self.base / "outside-directory"
        outside.mkdir()
        link = self.sdk / "SDK/escape"
        link.symlink_to(outside, target_is_directory=True)
        git("add", "SDK/escape", cwd=self.sdk)
        git(
            "-c",
            "user.email=stage0@example.invalid",
            "-c",
            "user.name=Stage0 Test",
            "commit",
            "-q",
            "-m",
            "tracked symlink fixture",
            cwd=self.sdk,
        )
        self.commit = git("rev-parse", "HEAD", cwd=self.sdk)
        self.tree = git("rev-parse", "HEAD^{tree}", cwd=self.sdk)
        (self.sdk / ".git/shallow").write_text(
            self.commit + "\n", encoding="ascii"
        )
        records = [{"source": "firmware/overlay/SDK/added.txt", "destination": "SDK/escape/added.txt"}]
        output = self.base / "symlink-materialization-output"
        output.mkdir()
        with self.assertRaises(ValueError):
            self.call_bootstrap(output, overlay_records=records)
        self.assertEqual(list(output.iterdir()), [])
        self.assertEqual(list(outside.iterdir()), [])

    def test_patch_check_failure_is_atomic_and_source_sdk_remains_byte_identical(self):
        before = (self.sdk / "SDK/base.txt").read_bytes()
        self.patch.write_text(
            "diff --git a/SDK/base.txt b/SDK/base.txt\n"
            "--- a/SDK/base.txt\n"
            "+++ b/SDK/base.txt\n"
            "@@ -1 +1 @@\n"
            "-wrong-context\n"
            "+patched\n",
            encoding="ascii",
        )
        self.commit_repository("valid patch with a failing hunk")
        output = self.base / "bad-patch"
        output.mkdir()
        with self.assertRaises(ValueError):
            self.call_bootstrap(output)
        self.assertEqual((self.sdk / "SDK/base.txt").read_bytes(), before)
        self.assertEqual(list(output.iterdir()), [])

    def test_staged_and_untracked_sdk_dirt_and_duplicate_destinations_are_rejected_atomically(self):
        for kind in ("staged", "untracked"):
            with self.subTest(kind=kind):
                if kind == "staged":
                    (self.sdk / "SDK/base.txt").write_text("staged\n", encoding="ascii")
                    git("add", "SDK/base.txt", cwd=self.sdk)
                else:
                    (self.sdk / "SDK/untracked.txt").write_text("untracked\n", encoding="ascii")
                    (self.sdk / "SDK/untracked.txt").chmod(0o644)
                output = self.base / (kind + "-output")
                output.mkdir()
                before = snapshot_tree(self.sdk)
                with self.assertRaises(ValueError):
                    self.call_bootstrap(output)
                self.assertEqual(list(output.iterdir()), [])
                self.assertEqual(snapshot_tree(self.sdk), before)
                git("reset", "--hard", "-q", "HEAD", cwd=self.sdk)
                untracked = self.sdk / "SDK/untracked.txt"
                if untracked.exists():
                    untracked.unlink()
        duplicate = [self.overlay_records[0], dict(self.overlay_records[0])]
        output = self.base / "duplicate-output"
        output.mkdir()
        with self.assertRaises(ValueError):
            self.call_bootstrap(output, overlay_records=duplicate)
        self.assertEqual(list(output.iterdir()), [])

        outside_controller = self.base / "outside-controller-material"
        outside_controller.mkdir()
        outside_sentinel = outside_controller / "sentinel.txt"
        outside_sentinel.write_bytes(b"controller escape sentinel\n")
        outside_sentinel.chmod(0o644)
        for index, kind in enumerate(
            (
                "root-symlink",
                "content-symlink",
                "root-special",
                "content-special",
                "regular-root",
                "evil-prefix",
            )
        ):
            with self.subTest(superpowers=kind):
                controller_root = self.repo / (
                    ".superpowers-evil" if kind == "evil-prefix" else ".superpowers"
                )
                if kind == "root-symlink":
                    controller_root.symlink_to(
                        outside_controller, target_is_directory=True
                    )
                elif kind == "content-symlink":
                    controller_root.mkdir()
                    (controller_root / "escape").symlink_to(outside_sentinel)
                elif kind == "root-special":
                    os.mkfifo(controller_root, 0o600)
                elif kind == "content-special":
                    controller_root.mkdir()
                    os.mkfifo(controller_root / "controller.fifo", 0o600)
                elif kind == "regular-root":
                    controller_root.write_bytes(b"not a controller directory\n")
                    controller_root.chmod(0o644)
                else:
                    controller_root.mkdir()
                    evil_content = controller_root / "controller.txt"
                    evil_content.write_bytes(
                        b"prefix lookalike is ordinary untracked content\n"
                    )
                    evil_content.chmod(0o644)
                output = self.base / f"bad-superpowers-{index}"
                output.mkdir()
                self.runner = RecordingRunner()
                try:
                    with self.assertRaises(ValueError):
                        self.call_bootstrap(output)
                    self.assertFalse(
                        any(
                            git_verb(call[0]) in ("archive", "apply")
                            for call in self.runner.calls
                        )
                    )
                    self.assertEqual(list(output.iterdir()), [])
                    self.assertEqual(
                        outside_sentinel.read_bytes(), b"controller escape sentinel\n"
                    )
                finally:
                    if controller_root.is_symlink() or (
                        controller_root.exists() and not controller_root.is_dir()
                    ):
                        controller_root.unlink()
                    elif controller_root.is_dir():
                        child_name = {
                            "content-symlink": "escape",
                            "content-special": "controller.fifo",
                            "evil-prefix": "controller.txt",
                        }.get(kind)
                        self.assertIsNotNone(child_name)
                        child = controller_root / child_name
                        if child.is_symlink() or child.exists():
                            child.unlink()
                        controller_root.rmdir()

    def test_patch_path_and_declared_headers_reject_outside_symlink_absolute_and_traversal(self):
        outside = self.base / "outside.patch"
        outside.write_text(self.patch.read_text(encoding="ascii"), encoding="ascii")
        linked = self.repo / "firmware/patches/stage0/linked.patch"
        linked.symlink_to(outside)
        bad_headers = []
        for destination in ("../escape", "/tmp/escape", "SDK/not-allowed.txt"):
            candidate = self.repo / "firmware/patches/stage0" / (str(len(bad_headers)) + ".patch")
            candidate.write_text(
                f"diff --git a/{destination} b/{destination}\n--- a/{destination}\n+++ b/{destination}\n@@ -1 +1 @@\n-a\n+b\n",
                encoding="ascii",
            )
            bad_headers.append(candidate)
        self.commit_repository("tracked patch path fixtures")
        for index, patch in enumerate((outside, linked, *bad_headers)):
            output = self.base / f"bad-patch-path-{index}"
            output.mkdir()
            with self.subTest(patch=str(patch)):
                with self.assertRaises(ValueError):
                    self.call_bootstrap(output, patch_path=patch)
                self.assertEqual(list(output.iterdir()), [])

    def test_patch_blocks_bind_one_old_and_new_header_to_each_unique_allowlisted_path_before_archive(self):
        redirect = (
            "diff --git a/SDK/base.txt b/SDK/base.txt\n"
            "--- a/SDK/base.txt\n"
            "+++ b/SDK/not-allowlisted.txt\n"
            "@@ -1 +1 @@\n-base\n+patched\n"
        )
        redirect_old = (
            "diff --git a/SDK/base.txt b/SDK/base.txt\n"
            "--- a/SDK/not-allowlisted.txt\n"
            "+++ b/SDK/base.txt\n"
            "@@ -1 +1 @@\n-base\n+patched\n"
        )
        redirect_diff_old = (
            "diff --git a/SDK/not-allowlisted.txt b/SDK/base.txt\n"
            "--- a/SDK/base.txt\n"
            "+++ b/SDK/base.txt\n"
            "@@ -1 +1 @@\n-base\n+patched\n"
        )
        redirect_diff_new = (
            "diff --git a/SDK/base.txt b/SDK/not-allowlisted.txt\n"
            "--- a/SDK/base.txt\n"
            "+++ b/SDK/base.txt\n"
            "@@ -1 +1 @@\n-base\n+patched\n"
        )
        missing_new = (
            "diff --git a/SDK/base.txt b/SDK/base.txt\n"
            "--- a/SDK/base.txt\n"
            "@@ -1 +1 @@\n-base\n+patched\n"
        )
        missing_old = (
            "diff --git a/SDK/base.txt b/SDK/base.txt\n"
            "+++ b/SDK/base.txt\n"
            "@@ -1 +1 @@\n-base\n+patched\n"
        )
        duplicate_old = (
            "diff --git a/SDK/base.txt b/SDK/base.txt\n"
            "--- a/SDK/base.txt\n"
            "--- a/SDK/base.txt\n"
            "+++ b/SDK/base.txt\n"
            "@@ -1 +1 @@\n-base\n+patched\n"
        )
        duplicate_new = (
            "diff --git a/SDK/base.txt b/SDK/base.txt\n"
            "--- a/SDK/base.txt\n"
            "+++ b/SDK/base.txt\n"
            "+++ b/SDK/base.txt\n"
            "@@ -1 +1 @@\n-base\n+patched\n"
        )
        dev_null = (
            "diff --git a/SDK/base.txt b/SDK/base.txt\n"
            "--- /dev/null\n"
            "+++ b/SDK/base.txt\n"
            "@@ -0,0 +1 @@\n+patched\n"
        )
        dev_null_new = (
            "diff --git a/SDK/base.txt b/SDK/base.txt\n"
            "--- a/SDK/base.txt\n"
            "+++ /dev/null\n"
            "@@ -1 +0,0 @@\n-base\n"
        )
        valid_block = (
            "diff --git a/SDK/base.txt b/SDK/base.txt\n"
            "--- a/SDK/base.txt\n"
            "+++ b/SDK/base.txt\n"
            "@@ -1 +1 @@\n-base\n+patched\n"
        )
        def with_directive(directive):
            return valid_block.replace("--- a/SDK/base.txt\n", directive + "\n--- a/SDK/base.txt\n", 1)

        cases = {
            "redirected-new-path": redirect,
            "redirected-old-path": redirect_old,
            "redirected-diff-old-operand": redirect_diff_old,
            "redirected-diff-new-operand": redirect_diff_new,
            "missing-old-header": missing_old,
            "missing-new-header": missing_new,
            "duplicate-old-header": duplicate_old,
            "duplicate-new-header": duplicate_new,
            "dev-null-old": dev_null,
            "dev-null-new": dev_null_new,
            "duplicate-diff-block": valid_block + valid_block,
            "rename-from": with_directive("rename from SDK/base.txt"),
            "rename-to": with_directive("rename to SDK/renamed.txt"),
            "copy-from": with_directive("copy from SDK/base.txt"),
            "copy-to": with_directive("copy to SDK/copied.txt"),
            "new-file-mode": with_directive("new file mode 100644"),
            "deleted-file-mode": with_directive("deleted file mode 100644"),
            "old-mode": with_directive("old mode 100644"),
            "new-mode": with_directive("new mode 100755"),
            "git-binary-patch": with_directive("GIT binary patch"),
            "binary-marker": with_directive(
                "Binary files a/SDK/base.txt and b/SDK/base.txt differ"
            ),
        }
        for index, (name, patch_text) in enumerate(cases.items()):
            with self.subTest(name=name):
                self.patch.write_text(patch_text, encoding="ascii")
                self.commit_repository(f"malicious patch fixture {index}")
                self.runner = RecordingRunner()
                output = self.base / f"malicious-patch-{index}"
                output.mkdir()
                with self.assertRaises(ValueError):
                    self.call_bootstrap(output)
                self.assertFalse(
                    any(git_verb(call[0]) in ("archive", "apply") for call in self.runner.calls),
                    "malformed patch reached SDK materialization",
                )
                self.assertEqual(list(output.iterdir()), [])

    def test_hardened_orchestration_mandates_source_git_and_disjoint_real_roots_before_output(self):
        with self.subTest(contract="fixed-production-tool-roots"):
            self.assertEqual(
                getattr(self.bootstrap, "TOOLCHAIN_ROOT", None), LOCKED_TOOLCHAIN_ROOT
            )
            self.assertEqual(
                getattr(self.bootstrap, "POST_BUILD_ROOT", None), LOCKED_POST_BUILD_ROOT
            )
        with self.subTest(contract="exact-public-signature"):
            parameters = inspect.signature(self.bootstrap.bootstrap_sdk).parameters
            self.assertEqual(
                list(parameters),
                [
                    "repository_root",
                    "sdk_root",
                    "output_root",
                    "expected_source_commit",
                    "expected_source_tree",
                    "expected_sdk_commit",
                    "expected_sdk_tree",
                    "overlay_records",
                    "patch_path",
                    "allowed_patch_paths",
                    "git_tool",
                    "runner",
                ],
            )
            self.assertTrue(
                all(
                    parameter.kind is inspect.Parameter.KEYWORD_ONLY
                    for parameter in parameters.values()
                )
            )
            self.assertTrue(
                all(
                    parameters[name].default is inspect.Parameter.empty
                    for name in parameters
                    if name != "runner"
                )
            )
            self.assertNotIn("forbidden_roots", parameters)
            self.assertNotIn("tool_roots", parameters)

        if "expected_source_commit" in parameters:
            for name, source_commit, source_tree in (
                ("source-commit", "0" * 40, self.source_tree),
                ("source-tree", self.source_commit, "0" * 40),
            ):
                with self.subTest(name=name):
                    self.runner = RecordingRunner()
                    output = self.base / name
                    output.mkdir()
                    with self.assertRaises(ValueError):
                        self.call_hardened_bootstrap(
                            output,
                            expected_source_commit=source_commit,
                            expected_source_tree=source_tree,
                        )
                    self.assertFalse(
                        any(
                            git_verb(call[0]) == "archive"
                            for call in self.runner.calls
                        )
                    )
                    self.assertEqual(list(output.iterdir()), [])

        source_overlay = self.repo / "firmware/overlay/SDK/added.txt"
        source_overlay.write_text("dirty\n", encoding="ascii")
        dirty_output = self.base / "dirty-source"
        dirty_output.mkdir()
        self.runner = RecordingRunner()
        try:
            with self.subTest(name="dirty-source"):
                with self.assertRaises(ValueError):
                    self.call_bootstrap(dirty_output)
                self.assertFalse(
                    any(
                        git_verb(call[0]) == "archive" for call in self.runner.calls
                    )
                )
                self.assertEqual(list(dirty_output.iterdir()), [])
        finally:
            git("reset", "--hard", "-q", "HEAD", cwd=self.repo)

        expected_source_config = [
            ("core.repositoryformatversion", "0"),
            ("core.filemode", "true"),
            ("core.bare", "false"),
            ("core.logallrefupdates", "true"),
            ("user.email", "jethachan@gmail.com"),
            ("user.name", "Jetha Chan"),
            (
                "remote.bootstrap.url",
                "/home/jethac/.cache/codex-transfer/factory-android-badges-e87.bundle",
            ),
            (
                "remote.bootstrap.fetch",
                "+refs/heads/*:refs/remotes/bootstrap/*",
            ),
            (
                "remote.origin.url",
                "https://github.com/jethac/factory-android-badges.git",
            ),
            ("remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"),
            ("branch.codex/e87-local-rendering.remote", "bootstrap"),
            (
                "branch.codex/e87-local-rendering.merge",
                "refs/heads/codex/e87-local-rendering",
            ),
        ]
        expected_sdk_config = [
            ("core.repositoryformatversion", "0"),
            ("core.filemode", "true"),
            ("core.bare", "false"),
            ("core.logallrefupdates", "true"),
            (
                "remote.origin.url",
                "https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200.git",
            ),
            (
                "remote.origin.fetch",
                "+refs/heads/main:refs/remotes/origin/main",
            ),
            ("branch.main.remote", "origin"),
            ("branch.main.merge", "refs/heads/main"),
        ]
        self.assertCountEqual(local_config_entries(self.repo), expected_source_config)
        self.assertCountEqual(local_config_entries(self.sdk), expected_sdk_config)
        self.assertEqual(len(local_config_entries(self.repo)), len(expected_source_config))
        self.assertEqual(len(local_config_entries(self.sdk)), len(expected_sdk_config))

        if "expected_source_commit" in parameters:
            raw_commit = self.source_commit_object
            raw_header, separator, raw_message = raw_commit.partition(b"\n\n")
            self.assertEqual(separator, b"\n\n")
            header_lines = raw_header.split(b"\n")
            committer_lines = [
                line for line in header_lines if line.startswith(b"committer ")
            ]
            tree_lines = [
                line for line in header_lines if line.startswith(b"tree")
            ]
            self.assertEqual(len(committer_lines), 1)
            self.assertEqual(tree_lines, [b"tree " + self.source_tree.encode("ascii")])
            committer = committer_lines[0]
            tree_header = tree_lines[0]
            committer_identity = committer.rsplit(b" ", 2)[0]
            committer_timezone = committer.rsplit(b" ", 1)[1]

            def commit_with_committers(lines, *, after_header=b""):
                replaced_header = b"\n".join(
                    line
                    for line in header_lines
                    if not line.startswith(b"committer ")
                )
                if lines:
                    replaced_header += b"\n" + b"\n".join(lines)
                return replaced_header + b"\n\n" + after_header + raw_message

            def commit_with_trees(lines, *, after_header=b""):
                replaced_header = b"\n".join(
                    line for line in header_lines if not line.startswith(b"tree")
                )
                if lines:
                    replaced_header = b"\n".join(lines) + b"\n" + replaced_header
                return replaced_header + b"\n\n" + after_header + raw_message

            malformed_objects = {
                "missing": commit_with_committers([]),
                "duplicate": commit_with_committers([committer, committer]),
                "malformed": commit_with_committers([b"committer malformed"]),
                "leading-zero": commit_with_committers(
                    [committer_identity + b" 0" + str(self.source_commit_epoch).encode("ascii") + b" " + committer_timezone]
                ),
                "explicit-plus": commit_with_committers(
                    [committer_identity + b" +" + str(self.source_commit_epoch).encode("ascii") + b" " + committer_timezone]
                ),
                "zero": commit_with_committers(
                    [committer_identity + b" 0 " + committer_timezone]
                ),
                "negative": commit_with_committers(
                    [committer_identity + b" -1 " + committer_timezone]
                ),
                "out-of-range": commit_with_committers(
                    [committer_identity + b" 9223372036854775808 " + committer_timezone]
                ),
                "timezone-no-sign": commit_with_committers(
                    [committer_identity + b" 1 0000"]
                ),
                "timezone-short": commit_with_committers(
                    [committer_identity + b" 1 +000"]
                ),
                "timezone-nondigit": commit_with_committers(
                    [committer_identity + b" 1 +00A0"]
                ),
                "after-header-terminator": commit_with_committers(
                    [], after_header=committer + b"\n"
                ),
                "invalid-utf8": commit_with_committers(
                    [committer_identity + b"\xff 1 +0000"]
                ),
                "nul": commit_with_committers(
                    [committer_identity + b"\x00 1 +0000"]
                ),
                "tree-missing": commit_with_trees([]),
                "tree-duplicate": commit_with_trees([tree_header, tree_header]),
                "tree-uppercase": commit_with_trees(
                    [b"tree " + self.source_tree.upper().encode("ascii")]
                ),
                "tree-short": commit_with_trees(
                    [b"tree " + self.source_tree[:-1].encode("ascii")]
                ),
                "tree-nonhex": commit_with_trees([b"tree " + b"g" * 40]),
                "tree-empty": commit_with_trees([b"tree "]),
                "tree-extra-token": commit_with_trees(
                    [tree_header + b" trailing"]
                ),
                "tree-after-header-terminator": commit_with_trees(
                    [], after_header=tree_header + b"\n"
                ),
                "tree-nul": commit_with_trees(
                    [b"tree " + self.source_tree.encode("ascii") + b"\x00"]
                ),
            }
            for index, (name, commit_object) in enumerate(
                malformed_objects.items()
            ):
                with self.subTest(source_commit_object=name):
                    object_id = git_object_sha1("commit", commit_object)
                    runner = CommitObjectRunner(
                        self.repo, object_id, [commit_object]
                    )
                    output = self.base / f"bad-source-commit-object-{index}"
                    output.mkdir()
                    with self.assertRaises(ValueError):
                        self.call_hardened_bootstrap(
                            output,
                            expected_source_commit=object_id,
                            runner=runner,
                        )
                    self.assertEqual(runner.object_reads, [commit_object])
                    self.assertFalse(
                        any(
                            git_verb(call[0]) in ("archive", "apply")
                            for call in runner.calls
                        )
                    )
                    self.assertEqual(list(output.iterdir()), [])

            alternate_tree = self.tree
            self.assertRegex(alternate_tree, r"^[0-9a-f]{40}$")
            self.assertNotEqual(alternate_tree, self.source_tree)
            alternate_tree_commit_object = commit_with_trees(
                [b"tree " + alternate_tree.encode("ascii")]
            )
            alternate_tree_commit = git_object_sha1(
                "commit", alternate_tree_commit_object
            )
            self.assertEqual(
                independent_commit_tree(alternate_tree_commit_object), alternate_tree
            )
            self.assertEqual(
                independent_commit_epoch(alternate_tree_commit_object),
                self.source_commit_epoch,
            )
            self.assertEqual(
                git_object_sha1("commit", alternate_tree_commit_object),
                alternate_tree_commit,
            )
            alternate_tree_runner = CommitObjectRunner(
                self.repo,
                alternate_tree_commit,
                [alternate_tree_commit_object, alternate_tree_commit_object],
            )
            alternate_tree_output = self.base / "bad-source-commit-tree-binding"
            alternate_tree_output.mkdir()
            with self.subTest(source_commit_flow="self-consistent-different-tree"):
                with self.assertRaises(ValueError):
                    self.call_hardened_bootstrap(
                        alternate_tree_output,
                        expected_source_commit=alternate_tree_commit,
                        runner=alternate_tree_runner,
                    )
                self.assertTrue(alternate_tree_runner.object_reads)
                self.assertTrue(
                    all(
                        value == alternate_tree_commit_object
                        for value in alternate_tree_runner.object_reads
                    )
                )
                self.assertFalse(
                    any(
                        git_verb(call[0]) in ("archive", "apply")
                        for call in alternate_tree_runner.calls
                    )
                )
                self.assertEqual(list(alternate_tree_output.iterdir()), [])

            alternate_commit_object = commit_with_committers(
                [
                    committer_identity
                    + b" "
                    + str(self.source_commit_epoch + 1).encode("ascii")
                    + b" "
                    + committer_timezone
                ]
            )
            mismatch_cases = (
                (
                    "object-does-not-hash-to-requested-commit",
                    CommitObjectRunner(
                        self.repo,
                        self.source_commit,
                        [alternate_commit_object],
                    ),
                ),
                (
                    "head-changes-between-validation-and-recheck",
                    CommitObjectRunner(
                        self.repo,
                        self.source_commit,
                        [raw_commit, raw_commit],
                        head_values=[
                            self.source_commit,
                            git_object_sha1("commit", alternate_commit_object),
                        ],
                    ),
                ),
                (
                    "commit-object-changes-between-stable-reads",
                    CommitObjectRunner(
                        self.repo,
                        self.source_commit,
                        [raw_commit, alternate_commit_object],
                    ),
                ),
                (
                    "cat-file-fails",
                    CommitObjectRunner(
                        self.repo,
                        self.source_commit,
                        [raw_commit],
                        fail_cat_file=True,
                    ),
                ),
            )
            for index, (name, runner) in enumerate(mismatch_cases):
                with self.subTest(source_commit_flow=name):
                    output = self.base / f"bad-source-commit-flow-{index}"
                    output.mkdir()
                    with self.assertRaises(ValueError):
                        self.call_hardened_bootstrap(output, runner=runner)
                    self.assertEqual(list(output.iterdir()), [])
                    if name != "head-changes-between-validation-and-recheck":
                        self.assertFalse(
                            any(
                                git_verb(call[0]) == "apply"
                                for call in runner.calls
                            )
                            and name
                            in (
                                "object-does-not-hash-to-requested-commit",
                                "cat-file-fails",
                            )
                        )

        def exact_repository_checks(root, commit_object=None):
            checks = [
                repository_git_command(root, "rev-parse", "HEAD"),
                repository_git_command(root, "rev-parse", "HEAD^{tree}"),
                repository_git_command(
                    root, "status", "--porcelain=v1", "--untracked-files=no"
                ),
                repository_git_command(
                    root, "ls-files", "-v", "--stage", "-z", "--"
                ),
                repository_git_command(
                    root,
                    "diff",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--exit-code",
                    "--cached",
                    "HEAD",
                    "--",
                ),
                repository_git_command(
                    root,
                    "diff",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--exit-code",
                    "--",
                ),
            ]
            if commit_object is not None:
                checks.append(
                    repository_git_command(root, "cat-file", "commit", commit_object)
                )
            return checks

        for root_name, root in (("source", self.repo), ("sdk", self.sdk)):
            root_overrides = (
                {"repository_root": root}
                if root_name == "source"
                else {"sdk_root": root}
            )
            admin = root / ".git"
            relocated_parent = self.base / f"relocated-admin-{root_name}"
            relocated_parent.mkdir()
            relocated_admin = relocated_parent / "admin"
            external_sentinel = relocated_parent / "sentinel.txt"
            external_sentinel.write_bytes(b"external admin sentinel\n")
            external_sentinel.chmod(0o644)
            admin.rename(relocated_admin)
            try:
                for index, kind in enumerate(("symlink", "gitfile")):
                    with self.subTest(git_admin=f"{root_name}:{kind}"):
                        if kind == "symlink":
                            admin.symlink_to(relocated_admin, target_is_directory=True)
                        else:
                            admin.write_text(
                                f"gitdir: {relocated_admin}\n", encoding="utf-8"
                            )
                            admin.chmod(0o644)
                        self.runner = RecordingRunner()
                        output = self.base / f"bad-git-admin-{root_name}-{index}"
                        output.mkdir()
                        try:
                            with self.assertRaises(ValueError):
                                self.call_bootstrap(output, **root_overrides)
                            self.assertEqual(
                                self.runner.calls,
                                [],
                                "indirected Git admin state reached a subprocess",
                            )
                            self.assertEqual(list(output.iterdir()), [])
                            self.assertEqual(
                                external_sentinel.read_bytes(),
                                b"external admin sentinel\n",
                            )
                        finally:
                            if admin.is_symlink() or admin.is_file():
                                admin.unlink()
            finally:
                if admin.is_symlink() or admin.is_file():
                    admin.unlink()
                relocated_admin.rename(admin)

            admin_info = admin / "info"
            admin_info.mkdir(exist_ok=True)
            common_root = self.base / f"external-common-{root_name}"
            common_root.mkdir()
            common_sentinel = common_root / "sentinel.txt"
            common_sentinel.write_bytes(b"external common sentinel\n")
            common_sentinel.chmod(0o644)
            alternates_root = self.base / f"external-objects-{root_name}"
            alternates_root.mkdir()
            alternates_sentinel = alternates_root / "sentinel.txt"
            alternates_sentinel.write_bytes(b"external object sentinel\n")
            alternates_sentinel.chmod(0o644)
            admin_cases = (
                ("commondir-regular", admin / "commondir", "regular", common_root),
                ("commondir-symlink", admin / "commondir", "symlink", common_root),
                ("commondir-directory", admin / "commondir", "directory", common_root),
                (
                    "alternates-regular",
                    admin / "objects/info/alternates",
                    "regular",
                    alternates_root,
                ),
                (
                    "alternates-symlink",
                    admin / "objects/info/alternates",
                    "symlink",
                    alternates_root,
                ),
                (
                    "alternates-directory",
                    admin / "objects/info/alternates",
                    "directory",
                    alternates_root,
                ),
            )
            for index, (name, target, kind, external_root) in enumerate(admin_cases):
                with self.subTest(git_admin=f"{root_name}:{name}"):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if kind == "regular":
                        target.write_text(str(external_root) + "\n", encoding="utf-8")
                        target.chmod(0o644)
                    elif kind == "symlink":
                        external_file = external_root / f"{name}.txt"
                        external_file.write_text(
                            str(external_root) + "\n", encoding="utf-8"
                        )
                        external_file.chmod(0o644)
                        target.symlink_to(external_file)
                    else:
                        target.mkdir()
                    self.runner = RecordingRunner()
                    output = self.base / f"bad-git-local-state-{root_name}-{index}"
                    output.mkdir()
                    try:
                        with self.assertRaises(ValueError):
                            self.call_bootstrap(output, **root_overrides)
                        self.assertEqual(
                            self.runner.calls,
                            [],
                            "Git-local indirection reached a subprocess",
                        )
                        self.assertEqual(list(output.iterdir()), [])
                        self.assertEqual(
                            common_sentinel.read_bytes(), b"external common sentinel\n"
                        )
                        self.assertEqual(
                            alternates_sentinel.read_bytes(),
                            b"external object sentinel\n",
                        )
                    finally:
                        if target.is_symlink() or target.is_file():
                            target.unlink()
                        elif target.is_dir():
                            target.rmdir()

            for index, kind in enumerate(
                ("admin-symlink", "admin-gitfile", "commondir", "alternates")
            ):
                with self.subTest(git_admin_mutation=f"{root_name}:{kind}"):
                    race_parent = self.base / f"race-admin-{root_name}-{index}"
                    race_parent.mkdir()
                    race_sentinel = race_parent / "sentinel.txt"
                    race_sentinel.write_bytes(b"race admin sentinel\n")
                    race_sentinel.chmod(0o644)
                    relocated = race_parent / "admin"
                    target = None

                    def mutate_admin():
                        nonlocal target
                        if kind in ("admin-symlink", "admin-gitfile"):
                            admin.rename(relocated)
                            if kind == "admin-symlink":
                                admin.symlink_to(relocated, target_is_directory=True)
                            else:
                                admin.write_text(
                                    f"gitdir: {relocated}\n", encoding="utf-8"
                                )
                                admin.chmod(0o644)
                        elif kind == "commondir":
                            target = admin / "commondir"
                            target.write_text(str(common_root) + "\n", encoding="utf-8")
                            target.chmod(0o644)
                        else:
                            target = admin / "objects/info/alternates"
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_text(
                                str(alternates_root) + "\n", encoding="utf-8"
                            )
                            target.chmod(0o644)

                    def restore_admin():
                        if kind in ("admin-symlink", "admin-gitfile"):
                            if admin.is_symlink() or admin.is_file():
                                admin.unlink()
                            relocated.rename(admin)
                        elif target is not None and (
                            target.is_symlink() or target.is_file()
                        ):
                            target.unlink()

                    race_runner = ConfigWindowRunner(
                        root,
                        ["rev-parse", "HEAD"],
                        mutate_admin,
                        restore_admin,
                        mutate_before=False,
                        restore_after=False,
                    )
                    output = self.base / f"git-admin-race-{root_name}-{index}"
                    output.mkdir()
                    try:
                        with self.assertRaises(ValueError):
                            self.call_bootstrap(
                                output, runner=race_runner, **root_overrides
                            )
                        self.assertTrue(race_runner.mutated)
                        expected_race_prefix = [
                            ["/usr/bin/git", "--version"],
                            *(
                                []
                                if root_name == "source"
                                else exact_repository_checks(
                                    self.repo, self.source_commit
                                )
                            ),
                            repository_git_command(root, "rev-parse", "HEAD"),
                        ]
                        self.assertEqual(
                            [call[0] for call in race_runner.calls],
                            expected_race_prefix,
                            "Git-admin rebinding after HEAD must stop before any "
                            "subsequent Git read",
                        )
                        self.assertEqual(list(output.iterdir()), [])
                        self.assertEqual(
                            race_sentinel.read_bytes(), b"race admin sentinel\n"
                        )
                    finally:
                        race_runner.restore_now()

        for root_name, root in (("source", self.repo), ("sdk", self.sdk)):
            config_path = root / ".git/config"
            original_config = config_path.read_bytes()
            self.assertIn(b"\trepositoryformatversion = 0\n", original_config)
            self.assertIn(b"\tfilemode = true\n", original_config)
            self.assertIn(b"\tbare = false\n", original_config)
            self.assertIn(b"\tlogallrefupdates = true\n", original_config)

            def append_to_existing_line(anchor: bytes, addition: bytes) -> bytes:
                self.assertIn(anchor, original_config)
                return original_config.replace(anchor, anchor + addition, 1)

            config_bytes_cases = {
                "invalid-utf8": original_config + b"\xff",
                "nul": original_config + b"\x00",
                "control": original_config + b"\x01",
                "carriage-control": original_config + b"[user]\n\tname = A\rB\n",
                "multiline": original_config
                + b'[remote "continued"]\n\turl = local\\\ncontinued\n'
                + b"\tfetch = +refs/heads/*:refs/remotes/continued/*\n",
                "malformed-section": original_config + b"[broken\n",
                "include": original_config
                + b"[include]\n\tpath = /tmp/host-config\n",
                "include-if": original_config
                + b'[includeIf "gitdir:/tmp/"]\n\tpath = /tmp/host-config\n',
                "duplicate-core": original_config + b"[core]\n\tfilemode = true\n",
                "duplicate-user": original_config
                + b"[user]\n\tname = duplicate\n",
                "duplicate-remote": original_config
                + b'[remote "origin"]\n\turl = duplicate\n',
                "missing-core-repositoryformatversion": original_config.replace(
                    b"\trepositoryformatversion = 0\n", b"", 1
                ),
                "missing-core-filemode": original_config.replace(
                    b"\tfilemode = true\n", b"", 1
                ),
                "missing-core-bare": original_config.replace(
                    b"\tbare = false\n", b"", 1
                ),
                "missing-core-logallrefupdates": original_config.replace(
                    b"\tlogallrefupdates = true\n", b"", 1
                ),
                "wrong-repository-format": original_config.replace(
                    b"\trepositoryformatversion = 0\n",
                    b"\trepositoryformatversion = 1\n",
                    1,
                ),
                "wrong-filemode": original_config.replace(
                    b"\tfilemode = true\n", b"\tfilemode = false\n", 1
                ),
                "wrong-bare": original_config.replace(
                    b"\tbare = false\n", b"\tbare = true\n", 1
                ),
                "wrong-logallrefupdates": original_config.replace(
                    b"\tlogallrefupdates = true\n",
                    b"\tlogallrefupdates = false\n",
                    1,
                ),
                "wrong-type-repository-format": original_config.replace(
                    b"\trepositoryformatversion = 0\n",
                    b"\trepositoryformatversion = zero\n",
                    1,
                ),
                "wrong-type-filemode": original_config.replace(
                    b"\tfilemode = true\n", b"\tfilemode = maybe\n", 1
                ),
                "wrong-type-bare": original_config.replace(
                    b"\tbare = false\n", b"\tbare = maybe\n", 1
                ),
                "wrong-type-logallrefupdates": original_config.replace(
                    b"\tlogallrefupdates = true\n",
                    b"\tlogallrefupdates = maybe\n",
                    1,
                ),
                "unsafe-core-worktree": append_to_existing_line(
                    b"\tlogallrefupdates = true\n",
                    b"\tworktree = /tmp/redirected-worktree\n",
                ),
                "unsafe-core-fsmonitor": append_to_existing_line(
                    b"\tlogallrefupdates = true\n",
                    b"\tfsmonitor = /tmp/host-hook\n",
                ),
                "unsafe-core-attributes": append_to_existing_line(
                    b"\tlogallrefupdates = true\n",
                    b"\tattributesfile = /tmp/host-attributes\n",
                ),
                "unsafe-tar": original_config + b"[tar]\n\tumask = 0077\n",
                "unknown-section": original_config + b"[status]\n\tshowUntrackedFiles = no\n",
                "unknown-remote-key": append_to_existing_line(
                    b"\turl = "
                    + (
                        b"https://github.com/jethac/factory-android-badges.git\n"
                        if root_name == "source"
                        else b"https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200.git\n"
                    ),
                    b"\tproxy = host\n",
                ),
                "unknown-branch-key": append_to_existing_line(
                    (
                        b"\tmerge = refs/heads/codex/e87-local-rendering\n"
                        if root_name == "source"
                        else b"\tmerge = refs/heads/main\n"
                    ),
                    b"\trebase = true\n",
                ),
                "empty-remote-name": original_config
                + b'[remote ""]\n\turl = local\n\tfetch = refs/*:refs/*\n',
                "empty-branch-name": original_config
                + b'[branch ""]\n\tremote = origin\n\tmerge = refs/heads/main\n',
                "incomplete-remote": original_config
                + b'[remote "incomplete"]\n\turl = local\n',
                "incomplete-branch": original_config
                + b'[branch "incomplete"]\n\tremote = origin\n',
            }

            def replace_config_line(old: bytes, new: bytes) -> bytes:
                self.assertIn(old, original_config)
                return original_config.replace(old, new, 1)

            if root_name == "source":
                bootstrap_url = (
                    "\turl = /home/jethac/.cache/codex-transfer/"
                    "factory-android-badges-e87.bundle\n"
                ).encode("utf-8")
                bootstrap_fetch = (
                    b"\tfetch = +refs/heads/*:refs/remotes/bootstrap/*\n"
                )
                origin_url = (
                    b"\turl = https://github.com/jethac/"
                    b"factory-android-badges.git\n"
                )
                origin_fetch = b"\tfetch = +refs/heads/*:refs/remotes/origin/*\n"
                branch_remote = b"\tremote = bootstrap\n"
                branch_merge = (
                    b"\tmerge = refs/heads/codex/e87-local-rendering\n"
                )
                config_bytes_cases.update(
                    {
                        "source-empty-bootstrap-url": replace_config_line(
                            bootstrap_url, b"\turl =\n"
                        ),
                        "source-missing-bootstrap-url": replace_config_line(
                            bootstrap_url, b""
                        ),
                        "source-duplicate-bootstrap-url": replace_config_line(
                            bootstrap_url, bootstrap_url + bootstrap_url
                        ),
                        "source-wrong-class-bootstrap-url": replace_config_line(
                            bootstrap_url, b"\turl = relative-bootstrap.git\n"
                        ),
                        "source-wrong-target-bootstrap-url": replace_config_line(
                            bootstrap_url,
                            (
                                "\turl = "
                                + str(self.base / "different-bootstrap-source.git")
                                + "\n"
                            ).encode("utf-8"),
                        ),
                        "source-missing-bootstrap-fetch": replace_config_line(
                            bootstrap_fetch, b""
                        ),
                        "source-duplicate-bootstrap-fetch": replace_config_line(
                            bootstrap_fetch, bootstrap_fetch + bootstrap_fetch
                        ),
                        "source-wrong-bootstrap-fetch": replace_config_line(
                            bootstrap_fetch,
                            b"\tfetch = +refs/heads/main:refs/remotes/bootstrap/main\n",
                        ),
                        "source-empty-origin-url": replace_config_line(
                            origin_url, b"\turl =\n"
                        ),
                        "source-missing-origin-url": replace_config_line(
                            origin_url, b""
                        ),
                        "source-duplicate-origin-url": replace_config_line(
                            origin_url, origin_url + origin_url
                        ),
                        "source-wrong-class-origin-url": replace_config_line(
                            origin_url,
                            b"\turl = http://example.invalid/"
                            b"factory-android-badges-e87.git\n",
                        ),
                        "source-wrong-target-origin-url": replace_config_line(
                            origin_url,
                            b"\turl = https://github.com/jethac/other-source.git\n",
                        ),
                        "source-missing-origin-fetch": replace_config_line(
                            origin_fetch, b""
                        ),
                        "source-duplicate-origin-fetch": replace_config_line(
                            origin_fetch, origin_fetch + origin_fetch
                        ),
                        "source-wrong-origin-fetch": replace_config_line(
                            origin_fetch,
                            b"\tfetch = +refs/heads/main:refs/remotes/origin/main\n",
                        ),
                        "source-missing-branch-remote": replace_config_line(
                            branch_remote, b""
                        ),
                        "source-duplicate-branch-remote": replace_config_line(
                            branch_remote, branch_remote + branch_remote
                        ),
                        "source-wrong-branch-remote": replace_config_line(
                            branch_remote, b"\tremote = origin\n"
                        ),
                        "source-missing-branch-merge": replace_config_line(
                            branch_merge, b""
                        ),
                        "source-duplicate-branch-merge": replace_config_line(
                            branch_merge, branch_merge + branch_merge
                        ),
                        "source-wrong-branch-merge": replace_config_line(
                            branch_merge,
                            b"\tmerge = refs/heads/main\n",
                        ),
                        "source-missing-user-email": replace_config_line(
                            b"\temail = jethachan@gmail.com\n", b""
                        ),
                        "source-missing-user-name": replace_config_line(
                            b"\tname = Jetha Chan\n", b""
                        ),
                        "source-unknown-user-key": append_to_existing_line(
                            b"\temail = jethachan@gmail.com\n",
                            b"\tsigningkey = host-key\n",
                        ),
                    }
                )
            else:
                origin_url = (
                    b"\turl = https://gitlab.zh-jieli.com/e_badge/"
                    b"e_badge_707_sdk_200.git\n"
                )
                origin_fetch = (
                    b"\tfetch = +refs/heads/main:refs/remotes/origin/main\n"
                )
                branch_remote = b"\tremote = origin\n"
                branch_merge = b"\tmerge = refs/heads/main\n"
                config_bytes_cases.update(
                    {
                        "sdk-empty-origin-url": replace_config_line(
                            origin_url, b"\turl =\n"
                        ),
                        "sdk-missing-origin-url": replace_config_line(
                            origin_url, b""
                        ),
                        "sdk-duplicate-origin-url": replace_config_line(
                            origin_url, origin_url + origin_url
                        ),
                        "sdk-wrong-class-origin-url": replace_config_line(
                            origin_url,
                            b"\turl = http://example.invalid/e_badge_707_sdk_200.git\n",
                        ),
                        "sdk-wrong-target-origin-url": replace_config_line(
                            origin_url,
                            b"\turl = https://gitlab.zh-jieli.com/e_badge/other-sdk.git\n",
                        ),
                        "sdk-missing-origin-fetch": replace_config_line(
                            origin_fetch, b""
                        ),
                        "sdk-duplicate-origin-fetch": replace_config_line(
                            origin_fetch, origin_fetch + origin_fetch
                        ),
                        "sdk-wrong-origin-fetch": replace_config_line(
                            origin_fetch,
                            b"\tfetch = +refs/heads/*:refs/remotes/origin/*\n",
                        ),
                        "sdk-missing-branch-remote": replace_config_line(
                            branch_remote, b""
                        ),
                        "sdk-duplicate-branch-remote": replace_config_line(
                            branch_remote, branch_remote + branch_remote
                        ),
                        "sdk-wrong-branch-remote": replace_config_line(
                            branch_remote, b"\tremote = bootstrap\n"
                        ),
                        "sdk-missing-branch-merge": replace_config_line(
                            branch_merge, b""
                        ),
                        "sdk-duplicate-branch-merge": replace_config_line(
                            branch_merge, branch_merge + branch_merge
                        ),
                        "sdk-wrong-branch-merge": replace_config_line(
                            branch_merge, b"\tmerge = refs/heads/other\n"
                        ),
                        "sdk-forbidden-user-section": original_config
                        + b"[user]\n\tname = Local Operator\n"
                        + b"\temail = local@example.invalid\n",
                    }
                )
            config_cases = [
                ("missing", "missing", None),
                ("symlink", "symlink", None),
                ("directory", "directory", None),
                *(
                    (name, "bytes", data)
                    for name, data in config_bytes_cases.items()
                ),
            ]
            for index, (name, kind, data) in enumerate(config_cases):
                with self.subTest(git_config=f"{root_name}:{name}"):
                    config_path.unlink()
                    outside_config = None
                    if kind == "symlink":
                        outside_config = self.base / f"outside-config-{root_name}-{index}"
                        outside_config.write_bytes(original_config)
                        config_path.symlink_to(outside_config)
                    elif kind == "directory":
                        config_path.mkdir()
                    elif kind == "bytes":
                        config_path.write_bytes(data)
                    self.runner = RecordingRunner()
                    output = self.base / f"bad-config-{root_name}-{index}"
                    output.mkdir()
                    try:
                        with self.assertRaises(ValueError):
                            self.call_bootstrap(output)
                        self.assertEqual(
                            self.runner.calls,
                            [],
                            "untrusted local config reached a Git subprocess",
                        )
                        self.assertEqual(list(output.iterdir()), [])
                    finally:
                        if config_path.is_symlink() or config_path.is_file():
                            config_path.unlink()
                        elif config_path.is_dir():
                            config_path.rmdir()
                        config_path.write_bytes(original_config)
                        if outside_config is not None:
                            outside_config.unlink()

            index_path = root / ".git/index"
            original_index = index_path.read_bytes()
            for index, kind in enumerate(("missing", "symlink", "directory")):
                with self.subTest(git_index=f"{root_name}:{kind}"):
                    index_path.unlink()
                    outside_index = None
                    if kind == "symlink":
                        outside_index = self.base / f"outside-index-{root_name}-{index}"
                        outside_index.write_bytes(original_index)
                        index_path.symlink_to(outside_index)
                    elif kind == "directory":
                        index_path.mkdir()
                    self.runner = RecordingRunner()
                    output = self.base / f"bad-index-{root_name}-{index}"
                    output.mkdir()
                    try:
                        with self.assertRaises(ValueError):
                            self.call_bootstrap(output)
                        self.assertEqual(self.runner.calls, [])
                        self.assertEqual(list(output.iterdir()), [])
                    finally:
                        if index_path.is_symlink() or index_path.is_file():
                            index_path.unlink()
                        elif index_path.is_dir():
                            index_path.rmdir()
                        index_path.write_bytes(original_index)
                        if outside_index is not None:
                            outside_index.unlink()

            sparse_path = root / ".git/info/sparse-checkout"
            for index, kind in enumerate(("regular", "symlink", "directory")):
                with self.subTest(sparse_checkout=f"{root_name}:{kind}"):
                    outside_sparse = None
                    if kind == "regular":
                        sparse_path.write_bytes(b"/*\n")
                    elif kind == "symlink":
                        outside_sparse = self.base / f"outside-sparse-{root_name}-{index}"
                        outside_sparse.write_bytes(b"/*\n")
                        sparse_path.symlink_to(outside_sparse)
                    else:
                        sparse_path.mkdir()
                    self.runner = RecordingRunner()
                    output = self.base / f"bad-sparse-{root_name}-{index}"
                    output.mkdir()
                    try:
                        with self.assertRaises(ValueError):
                            self.call_bootstrap(output)
                        self.assertFalse(
                            any(
                                git_verb(call[0]) in ("archive", "apply")
                                for call in self.runner.calls
                            )
                        )
                        self.assertEqual(list(output.iterdir()), [])
                    finally:
                        if sparse_path.is_symlink() or sparse_path.is_file():
                            sparse_path.unlink()
                        else:
                            sparse_path.rmdir()
                        if outside_sparse is not None:
                            outside_sparse.unlink()

            shallow_path = root / ".git/shallow"
            if root_name == "source":
                self.assertFalse(shallow_path.exists() or shallow_path.is_symlink())
                shallow_cases = (
                    ("regular", (self.source_commit + "\n").encode("ascii")),
                    ("invalid-utf8", b"\xff\n"),
                    ("symlink", None),
                    ("directory", None),
                )
                original_shallow = None
            else:
                original_shallow = shallow_path.read_bytes()
                self.assertEqual(
                    original_shallow, (self.commit + "\n").encode("ascii")
                )
                shallow_cases = (
                    (
                        "wrong-valid-commit",
                        (self.sdk_parent_commit + "\n").encode("ascii"),
                    ),
                    ("unknown-commit", ("0" * 40 + "\n").encode("ascii")),
                    ("multiple-lines", original_shallow + original_shallow),
                    ("missing-newline", original_shallow.rstrip(b"\n")),
                    ("blank-line", original_shallow + b"\n"),
                    ("invalid-utf8", b"\xff\n"),
                    ("nul", original_shallow[:-1] + b"\x00\n"),
                    ("symlink", None),
                    ("directory", None),
                )
            for index, (kind, data) in enumerate(shallow_cases):
                with self.subTest(shallow_state=f"{root_name}:{kind}"):
                    if original_shallow is not None:
                        shallow_path.unlink()
                    outside_shallow = None
                    if kind == "symlink":
                        outside_shallow = self.base / (
                            f"outside-shallow-{root_name}-{index}"
                        )
                        outside_shallow.write_bytes(
                            original_shallow
                            or (self.source_commit + "\n").encode("ascii")
                        )
                        shallow_path.symlink_to(outside_shallow)
                    elif kind == "directory":
                        shallow_path.mkdir()
                    else:
                        shallow_path.write_bytes(data)
                    self.runner = RecordingRunner()
                    output = self.base / f"bad-shallow-{root_name}-{index}"
                    output.mkdir()
                    try:
                        with self.assertRaises(ValueError):
                            self.call_bootstrap(output)
                        self.assertEqual(self.runner.calls, [])
                        self.assertEqual(list(output.iterdir()), [])
                    finally:
                        if shallow_path.is_symlink() or shallow_path.is_file():
                            shallow_path.unlink()
                        elif shallow_path.is_dir():
                            shallow_path.rmdir()
                        if original_shallow is not None:
                            shallow_path.write_bytes(original_shallow)
                        if outside_shallow is not None:
                            outside_shallow.unlink()

        for root_name, root, tracked, executable in (
            (
                "source",
                self.repo,
                self.repo / self.overlay_records[0]["source"],
                self.source_executable,
            ),
            ("sdk", self.sdk, self.sdk / "SDK/base.txt", self.sdk_executable),
        ):
            exclude = root / ".git/info/exclude"
            exclude_before = exclude.read_bytes()
            with self.subTest(clean_state=f"{root_name}:exclude-metadata-is-inert"):
                exclude.write_bytes(exclude_before + b"\n# operator-local ignore metadata\n")
                self.runner = RecordingRunner()
                exclude_control_output = self.base / f"exclude-control-{root_name}"
                exclude_control_output.mkdir()
                try:
                    self.call_bootstrap(exclude_control_output)
                    self.assertEqual(
                        (exclude_control_output / "SDK/base.txt").read_bytes(),
                        b"patched\n",
                    )
                finally:
                    exclude.write_bytes(exclude_before)
            for ignored_kind in ("file", "symlink"):
                ignored_name = f"stage0-ignored-{ignored_kind}"
                ignored = root / ignored_name
                outside_ignored = self.base / f"outside-ignored-{root_name}"
                try:
                    exclude.write_bytes(
                        exclude_before + b"\n" + ignored_name.encode("ascii") + b"\n"
                    )
                    if ignored_kind == "file":
                        ignored.write_bytes(b"must be independently detected\n")
                    else:
                        outside_ignored.write_bytes(b"symlink target\n")
                        ignored.symlink_to(outside_ignored)
                    self.assertEqual(git("status", "--porcelain=v1", cwd=root), "")
                    self.runner = RecordingRunner()
                    output = self.base / f"ignored-{ignored_kind}-{root_name}"
                    output.mkdir()
                    with self.subTest(
                        clean_state=f"{root_name}:ignored-untracked-{ignored_kind}"
                    ):
                        with self.assertRaises(ValueError):
                            self.call_bootstrap(output)
                        self.assertFalse(
                            any(
                                git_verb(call[0]) in ("archive", "apply")
                                for call in self.runner.calls
                            )
                        )
                        self.assertEqual(list(output.iterdir()), [])
                finally:
                    if ignored.is_symlink() or ignored.is_file():
                        ignored.unlink()
                    if outside_ignored.exists():
                        outside_ignored.unlink()
                    exclude.write_bytes(exclude_before)

            for drift_name, drift_path, drift_mode, restored_mode in (
                ("regular-0644-to-0755", tracked, 0o755, 0o644),
                ("executable-0755-to-0644", executable, 0o644, 0o755),
            ):
                with self.subTest(mode_drift=f"{root_name}:{drift_name}"):
                    before_hash = hashlib.sha256(drift_path.read_bytes()).digest()
                    drift_path.chmod(drift_mode)
                    self.assertNotEqual(git("status", "--porcelain=v1", cwd=root), "")
                    self.runner = RecordingRunner()
                    output = self.base / f"mode-drift-{root_name}-{drift_name}"
                    output.mkdir()
                    try:
                        with self.assertRaises(ValueError):
                            self.call_bootstrap(output)
                        self.assertFalse(
                            any(
                                git_verb(call[0]) in ("archive", "apply")
                                for call in self.runner.calls
                            )
                        )
                        self.assertEqual(list(output.iterdir()), [])
                    finally:
                        drift_path.chmod(restored_mode)
                    self.assertEqual(
                        hashlib.sha256(drift_path.read_bytes()).digest(), before_hash
                    )

            tracked_before = tracked.read_bytes()
            tracked_relative = tracked.relative_to(root).as_posix()
            for flag, enable, disable in (
                (
                    "assume-unchanged",
                    "--assume-unchanged",
                    "--no-assume-unchanged",
                ),
                ("skip-worktree", "--skip-worktree", "--no-skip-worktree"),
            ):
                with self.subTest(clean_state=f"{root_name}:{flag}"):
                    git("update-index", enable, "--", tracked_relative, cwd=root)
                    tracked.write_bytes(b"hidden tracked-byte mutation\n")
                    self.assertEqual(git("status", "--porcelain=v1", cwd=root), "")
                    self.runner = RecordingRunner()
                    output = self.base / f"hidden-{root_name}-{flag}"
                    output.mkdir()
                    try:
                        with self.assertRaises(ValueError):
                            self.call_bootstrap(output)
                        self.assertFalse(
                            any(
                                git_verb(call[0]) in ("archive", "apply")
                                for call in self.runner.calls
                            )
                        )
                        self.assertEqual(list(output.iterdir()), [])
                    finally:
                        tracked.write_bytes(tracked_before)
                        git("update-index", disable, "--", tracked_relative, cwd=root)
                        git("reset", "--hard", "-q", "HEAD", cwd=root)

            ls_arguments = ["ls-files", "-v", "--stage", "-z", "--"]
            normal_ls_files = git_bytes(*ls_arguments, cwd=root)
            records = normal_ls_files.split(b"\x00")
            self.assertEqual(records[-1], b"")
            self.assertTrue(records[0].startswith(b"H 100644 "))
            self.assertTrue(
                any(record.startswith(b"H 100755 ") for record in records[:-1])
            )
            first_record = records[0]
            parsed_regular = []
            for record in records[:-1]:
                match = re.fullmatch(
                    rb"H (100644|100755) ([0-9a-f]{40}) 0\t(.+)", record
                )
                self.assertIsNotNone(match)
                if match.group(1) == b"100644":
                    parsed_regular.append(
                        (record, match.group(2), match.group(3))
                    )
            self.assertGreaterEqual(len(parsed_regular), 2)
            original_record, original_blob, _ = parsed_regular[0]
            alternate_blob = next(
                blob for _, blob, _ in parsed_regular[1:] if blob != original_blob
            )
            self.assertNotEqual(alternate_blob, b"0" * 40)
            self.assertEqual(
                git("cat-file", "-t", alternate_blob.decode("ascii"), cwd=root),
                "blob",
            )
            git("cat-file", "-e", alternate_blob.decode("ascii"), cwd=root)
            wrong_blob_record = original_record.replace(
                original_blob, alternate_blob, 1
            )
            wrong_blob_listing = normal_ls_files.replace(
                original_record + b"\x00", wrong_blob_record + b"\x00", 1
            )
            malformed_ls_files = {
                "assume-unchanged-flag": b"h" + normal_ls_files[1:],
                "skip-worktree-flag": b"S" + normal_ls_files[1:],
                "nonzero-stage": normal_ls_files.replace(b" 0\t", b" 1\t", 1),
                "duplicate-path": normal_ls_files + first_record + b"\x00",
                "valid-but-wrong-existing-blob-id": wrong_blob_listing,
                "valid-but-wrong-regular-mode": normal_ls_files.replace(
                    b"H 100644 ", b"H 100755 ", 1
                ),
                "symlink-mode": normal_ls_files.replace(
                    b"H 100644 ", b"H 120000 ", 1
                ),
                "submodule-mode": normal_ls_files.replace(
                    b"H 100644 ", b"H 160000 ", 1
                ),
                "missing-nul": normal_ls_files[:-1],
                "invalid-utf8-path": normal_ls_files.replace(
                    b"\x00", b"\xff\x00", 1
                ),
                "malformed-record": b"H malformed\x00",
            }
            for index, (name, injected_stdout) in enumerate(
                malformed_ls_files.items()
            ):
                with self.subTest(ls_files=f"{root_name}:{name}"):
                    runner = InjectedGitOutputRunner(
                        root, ls_arguments, injected_stdout
                    )
                    output = self.base / f"bad-ls-files-{root_name}-{index}"
                    output.mkdir()
                    with self.assertRaises(ValueError):
                        self.call_bootstrap(output, runner=runner)
                    self.assertEqual(runner.injected, 1)
                    self.assertFalse(
                        any(
                            git_verb(call[0]) in ("archive", "apply")
                            for call in runner.calls
                        )
                    )
                    self.assertEqual(list(output.iterdir()), [])

        for root_name, root in (("source", self.repo), ("sdk", self.sdk)):
            for filename in ("attributes", "grafts"):
                for kind in ("regular", "symlink", "directory"):
                    with self.subTest(
                        git_local_override=f"{root_name}:{filename}:{kind}"
                    ):
                        target = root / ".git/info" / filename
                        if kind == "regular":
                            if filename == "attributes":
                                target.write_text("* export-ignore\n", encoding="ascii")
                            else:
                                target.write_text(
                                    git("rev-parse", "HEAD", cwd=root) + "\n",
                                    encoding="ascii",
                                )
                        elif kind == "symlink":
                            outside_info_override = self.base / (
                                f"outside-{root_name}-{filename}"
                            )
                            if filename == "attributes":
                                outside_info_override.write_text(
                                    "* export-ignore\n", encoding="ascii"
                                )
                            else:
                                outside_info_override.write_text(
                                    git("rev-parse", "HEAD", cwd=root) + "\n",
                                    encoding="ascii",
                                )
                            target.symlink_to(outside_info_override)
                        else:
                            target.mkdir()
                        if kind == "regular":
                            override_before = ("regular", target.read_bytes())
                        elif kind == "symlink":
                            override_before = ("symlink", os.readlink(target))
                        else:
                            override_before = ("directory", None)
                        try:
                            self.assertEqual(
                                git("status", "--porcelain=v1", cwd=root), ""
                            )
                            self.runner = RecordingRunner()
                            output = self.base / (
                                f"git-info-{root_name}-{filename}-{kind}"
                            )
                            output.mkdir()
                            with self.assertRaises(ValueError):
                                self.call_bootstrap(output)
                            self.assertFalse(
                                any(
                                    git_verb(call[0]) in ("archive", "apply")
                                    for call in self.runner.calls
                                )
                            )
                            self.assertEqual(list(output.iterdir()), [])
                            if override_before[0] == "regular":
                                self.assertTrue(target.is_file() and not target.is_symlink())
                                self.assertEqual(target.read_bytes(), override_before[1])
                            elif override_before[0] == "symlink":
                                self.assertTrue(target.is_symlink())
                                self.assertEqual(os.readlink(target), override_before[1])
                            else:
                                self.assertTrue(target.is_dir() and not target.is_symlink())
                        finally:
                            if target.is_symlink() or target.is_file():
                                target.unlink()
                            elif target.is_dir():
                                target.rmdir()

        if "git_tool" in parameters:
            for name, git_tool in (
                ("wrong-git-digest", {**self.git_tool, "sha256": "0" * 64}),
                ("relative-git", {**self.git_tool, "path": "git"}),
                ("unknown-git-key", {**self.git_tool, "unknown": "x"}),
            ):
                with self.subTest(name=name):
                    self.runner = RecordingRunner()
                    output = self.base / name
                    output.mkdir()
                    with self.assertRaises(ValueError):
                        self.call_hardened_bootstrap(output, git_tool=git_tool)
                    self.assertEqual(self.runner.calls, [])
                    self.assertEqual(list(output.iterdir()), [])

        alias = self.base / "root-alias"
        alias.symlink_to(self.base, target_is_directory=True)
        linked_repository = self.base / "linked-repository"
        linked_repository.symlink_to(self.repo, target_is_directory=True)
        linked_sdk = self.base / "linked-sdk"
        linked_sdk.symlink_to(self.sdk, target_is_directory=True)
        linked_toolchain = self.base / "linked-toolchain"
        linked_toolchain.symlink_to(self.toolchain_root, target_is_directory=True)
        linked_post_build = self.base / "linked-post-build"
        linked_post_build.symlink_to(self.post_build_root, target_is_directory=True)
        not_directory = self.base / "not-a-directory"
        not_directory.write_text("not a root\n", encoding="ascii")
        missing = self.base / "missing-root"

        def clone_git_root(source, destination):
            git("clone", "-q", str(source), str(destination), cwd=self.base)
            git("config", "user.email", "stage0@example.invalid", cwd=destination)
            git("config", "user.name", "Stage0 Test", cwd=destination)
            return destination

        def nested_git_roots(name, parent_source, child_source):
            parent = self.base / name
            child = parent / "child"
            clone_git_root(parent_source, parent)
            clone_git_root(child_source, child)
            git("add", "child", cwd=parent)
            git("commit", "-q", "-m", "nested Git root fixture", cwd=parent)
            return parent, child

        def git_contains_tool(name, git_source):
            parent = clone_git_root(git_source, self.base / name)
            child = parent / "child"
            child.mkdir()
            (child / "tool-marker").write_text("tool root\n", encoding="ascii")
            git("add", "child/tool-marker", cwd=parent)
            git("commit", "-q", "-m", "nested tool root fixture", cwd=parent)
            return parent, child

        def tool_contains_git(name, git_source):
            parent = self.base / name
            parent.mkdir()
            child = clone_git_root(git_source, parent / "child")
            return parent, child

        def nested_tools(name):
            parent = self.base / name
            child = parent / "child"
            child.mkdir(parents=True)
            return parent, child

        repo_parent, sdk_child = nested_git_roots(
            "repository-contains-sdk", self.repo, self.sdk
        )
        sdk_parent, repo_child = nested_git_roots(
            "sdk-contains-repository", self.sdk, self.repo
        )
        repo_tool_parent, repo_tool_child = git_contains_tool(
            "repository-contains-tool", self.repo
        )
        tool_repo_parent, tool_repo_child = tool_contains_git(
            "tool-contains-repository", self.repo
        )
        sdk_tool_parent, sdk_tool_child = git_contains_tool(
            "sdk-contains-tool", self.sdk
        )
        tool_sdk_parent, tool_sdk_child = tool_contains_git(
            "tool-contains-sdk", self.sdk
        )
        tools_parent, tools_child = nested_tools("tool-contains-tool")
        cases = (
            ("duplicate-tools", {}, (self.toolchain_root, self.toolchain_root)),
            ("repository-equals-sdk", {"sdk_root": self.repo}, None),
            ("repository-equals-tool", {}, (self.repo, self.post_build_root)),
            ("repository-equals-second-tool", {}, (self.toolchain_root, self.repo)),
            ("sdk-equals-tool", {}, (self.sdk, self.post_build_root)),
            ("sdk-equals-second-tool", {}, (self.toolchain_root, self.sdk)),
            ("repository-contains-sdk", {"repository_root": repo_parent, "sdk_root": sdk_child}, None),
            ("sdk-contains-repository", {"repository_root": repo_child, "sdk_root": sdk_parent}, None),
            ("repository-contains-tool", {"repository_root": repo_tool_parent}, (repo_tool_child, self.post_build_root)),
            ("tool-contains-repository", {"repository_root": tool_repo_child}, (tool_repo_parent, self.post_build_root)),
            ("repository-contains-second-tool", {"repository_root": repo_tool_parent}, (self.toolchain_root, repo_tool_child)),
            ("second-tool-contains-repository", {"repository_root": tool_repo_child}, (self.toolchain_root, tool_repo_parent)),
            ("sdk-contains-tool", {"sdk_root": sdk_tool_parent}, (sdk_tool_child, self.post_build_root)),
            ("tool-contains-sdk", {"sdk_root": tool_sdk_child}, (tool_sdk_parent, self.post_build_root)),
            ("sdk-contains-second-tool", {"sdk_root": sdk_tool_parent}, (self.toolchain_root, sdk_tool_child)),
            ("second-tool-contains-sdk", {"sdk_root": tool_sdk_child}, (self.toolchain_root, tool_sdk_parent)),
            ("tool-contains-tool", {}, (tools_parent, tools_child)),
            ("tool-contains-tool-reversed", {}, (tools_child, tools_parent)),
            ("relative-repository", {"repository_root": Path(self.repo.name)}, None),
            ("relative-sdk", {"sdk_root": Path(self.sdk.name)}, None),
            (
                "relative-tool",
                {},
                (Path(self.toolchain_root.name), self.post_build_root),
            ),
            (
                "relative-second-tool",
                {},
                (self.toolchain_root, Path(self.post_build_root.name)),
            ),
            ("missing-repository", {"repository_root": missing}, None),
            ("missing-sdk", {"sdk_root": missing}, None),
            ("missing-tool", {}, (missing, self.post_build_root)),
            ("missing-second-tool", {}, (self.toolchain_root, missing)),
            ("file-repository", {"repository_root": not_directory}, None),
            ("file-sdk", {"sdk_root": not_directory}, None),
            ("file-tool", {}, (not_directory, self.post_build_root)),
            ("file-second-tool", {}, (self.toolchain_root, not_directory)),
            ("symlinked-repository", {"repository_root": linked_repository}, None),
            ("symlinked-sdk", {"sdk_root": linked_sdk}, None),
            ("symlinked-tool", {}, (linked_toolchain, self.post_build_root)),
            ("symlinked-second-tool", {}, (self.toolchain_root, linked_post_build)),
            ("symlinked-repository-parent", {"repository_root": alias / self.repo.name}, None),
            ("symlinked-sdk-parent", {"sdk_root": alias / self.sdk.name}, None),
            ("symlinked-tool-parent", {}, (alias / self.toolchain_root.name, self.post_build_root)),
            ("symlinked-second-tool-parent", {}, (self.toolchain_root, alias / self.post_build_root.name)),
        )
        for index, (name, overrides, fixed_tool_roots) in enumerate(cases):
            with self.subTest(name=name):
                output = self.base / f"bad-public-root-{index}"
                output.mkdir()
                self.runner = RecordingRunner()
                original_cwd = Path.cwd()
                try:
                    if name.startswith("relative-"):
                        os.chdir(self.base)
                    error = (
                        self.assertRaisesRegex(ValueError, "absolute")
                        if name.startswith("relative-")
                        else self.assertRaises(ValueError)
                    )
                    with error:
                        self.call_bootstrap(
                            output,
                            _fixed_tool_roots=fixed_tool_roots
                            or (self.toolchain_root, self.post_build_root),
                            **overrides,
                        )
                finally:
                    os.chdir(original_cwd)
                self.assertEqual(self.runner.calls, [])
                self.assertEqual(list(output.iterdir()), [])

        second_tool_output = self.post_build_root / "nested-output"
        second_tool_output.mkdir()
        output_parent = self.base / "output-contains-second-tool"
        nested_second_tool = output_parent / "post-build"
        nested_second_tool.mkdir(parents=True)
        for index, (name, candidate, fixed_tool_roots) in enumerate(
            (
                ("output-equals-second-tool", self.post_build_root, (self.toolchain_root, self.post_build_root)),
                ("output-inside-second-tool", second_tool_output, (self.toolchain_root, self.post_build_root)),
                ("output-contains-second-tool", output_parent, (self.toolchain_root, nested_second_tool)),
            )
        ):
            with self.subTest(name=name):
                self.runner = RecordingRunner()
                with self.assertRaises(ValueError):
                    self.call_bootstrap(
                        candidate, _fixed_tool_roots=fixed_tool_roots
                    )
                self.assertEqual(self.runner.calls, [])

    def test_overlay_patch_and_source_identities_are_stable_read_and_rechecked_atomically(self):
        overlay = self.repo / self.overlay_records[0]["source"]
        original_overlay = overlay.read_bytes()
        original_patch = self.patch.read_bytes()
        original_source_commit = self.source_commit
        original_source_tree = self.source_tree
        marker = self.repo / "aba-source-marker"
        marker.write_text("alternate source identity\n", encoding="ascii")
        git("add", marker.name, cwd=self.repo)
        git("commit", "-q", "-m", "alternate source identity", cwd=self.repo)
        alternate_source_commit = git("rev-parse", "HEAD", cwd=self.repo)
        git("reset", "--hard", "-q", original_source_commit, cwd=self.repo)
        self.source_commit = original_source_commit
        self.source_tree = original_source_tree

        cases = (
            (
                "overlay",
                lambda: overlay.write_bytes(b"mutated overlay\n"),
                lambda: overlay.write_bytes(original_overlay),
                1,
            ),
            (
                "patch",
                lambda: self.patch.write_bytes(
                    original_patch.replace(b"+patched\n", b"+mutated-patch\n")
                ),
                lambda: self.patch.write_bytes(original_patch),
                2,
            ),
            (
                "source-identity",
                lambda: git("reset", "--hard", "-q", alternate_source_commit, cwd=self.repo),
                lambda: git("reset", "--hard", "-q", original_source_commit, cwd=self.repo),
                2,
            ),
        )
        for index, (name, mutation, restoration, restore_after_apply) in enumerate(cases):
            with self.subTest(window=name):
                runner = UseWindowRunner(
                    self.sdk, mutation, restoration, restore_after_apply
                )
                output = self.base / f"aba-window-{index}"
                output.mkdir()
                sdk_before = snapshot_tree(self.sdk)
                rejected = False
                returned_receipt = None
                try:
                    try:
                        returned_receipt = self.call_bootstrap(output, runner=runner)
                    except ValueError:
                        rejected = True
                finally:
                    runner.restore_now()
                self.assertTrue(runner.mutated)
                self.assertTrue(runner.restored)
                self.assertEqual(overlay.read_bytes(), original_overlay)
                self.assertEqual(self.patch.read_bytes(), original_patch)
                self.assertEqual(git("rev-parse", "HEAD", cwd=self.repo), original_source_commit)
                self.assertEqual(git("status", "--porcelain=v1", cwd=self.repo), "")
                if runner.apply_inputs:
                    self.assertEqual(runner.staged_overlay, original_overlay)
                    self.assertTrue(
                        all(value == original_patch for value in runner.apply_inputs)
                    )
                if rejected:
                    self.assertEqual(list(output.iterdir()), [])
                else:
                    self.assertEqual((output / "SDK/added.txt").read_bytes(), original_overlay)
                    self.assertEqual((output / "SDK/base.txt").read_bytes(), b"patched\n")
                    self.assertEqual(runner.apply_inputs, [original_patch, original_patch])
                    self.assertEqual(
                        returned_receipt["overlay"],
                        [
                            {
                                "destination": "SDK/added.txt",
                                "sha256": hashlib.sha256(original_overlay).hexdigest().upper(),
                                "size": len(original_overlay),
                                "source": "firmware/overlay/SDK/added.txt",
                            }
                        ],
                    )
                    self.assertEqual(
                        returned_receipt["patch"],
                        {
                            "paths": ["SDK/base.txt"],
                            "sha256": hashlib.sha256(original_patch).hexdigest().upper(),
                            "size": len(original_patch),
                        },
                    )
                    self.assertEqual(
                        returned_receipt["sourceCommitEpoch"],
                        self.source_commit_epoch,
                    )
                    self.assertEqual(
                        returned_receipt["sourceCommitObjectSha256"],
                        hashlib.sha256(self.source_commit_object).hexdigest().upper(),
                    )
                self.assertEqual(snapshot_tree(self.sdk), sdk_before)

        for index, (name, mutation, restoration, _) in enumerate(cases):
            with self.subTest(one_way=name):
                runner = UseWindowRunner(self.sdk, mutation)
                output = self.base / f"one-way-window-{index}"
                output.mkdir()
                sdk_before = snapshot_tree(self.sdk)
                try:
                    with self.assertRaises(ValueError):
                        self.call_bootstrap(output, runner=runner)
                finally:
                    restoration()
                self.assertTrue(runner.mutated)
                self.assertEqual(overlay.read_bytes(), original_overlay)
                self.assertEqual(self.patch.read_bytes(), original_patch)
                self.assertEqual(git("rev-parse", "HEAD", cwd=self.repo), original_source_commit)
                self.assertEqual(git("status", "--porcelain=v1", cwd=self.repo), "")
                if runner.apply_inputs:
                    self.assertEqual(runner.staged_overlay, original_overlay)
                    self.assertTrue(
                        all(value == original_patch for value in runner.apply_inputs)
                    )
                self.assertEqual(list(output.iterdir()), [])
                self.assertEqual(snapshot_tree(self.sdk), sdk_before)

        redirected_worktree = self.base / "redirected-worktree"
        redirected_worktree.mkdir()
        malicious_attributes = self.base / "malicious-archive-attributes"
        malicious_attributes.write_bytes(b"SDK/base.txt export-ignore\n")
        for root_name, root in (("source", self.repo), ("sdk", self.sdk)):
            config_path = root / ".git/config"
            original_config = config_path.read_bytes()
            one_way_config = original_config + b"[tar]\n\tumask = 0077\n"
            runner = ConfigWindowRunner(
                root,
                ["status", "--porcelain=v1", "--untracked-files=no"],
                lambda path=config_path, data=one_way_config: path.write_bytes(data),
                lambda path=config_path, data=original_config: path.write_bytes(data),
                mutate_before=False,
                restore_after=False,
            )
            output = self.base / f"config-one-way-{root_name}"
            output.mkdir()
            try:
                with self.subTest(config_window=f"{root_name}:one-way"):
                    with self.assertRaises(ValueError):
                        self.call_bootstrap(output, runner=runner)
                    self.assertTrue(runner.mutated)
                    self.assertFalse(
                        any(
                            git_verb(call[0]) in ("archive", "apply")
                            for call in runner.calls
                        )
                    )
                    self.assertEqual(list(output.iterdir()), [])
            finally:
                runner.restore_now()
            self.assertEqual(config_path.read_bytes(), original_config)

            status_aba_config = original_config + (
                f"[core]\n\tworktree = {redirected_worktree}\n"
            ).encode("utf-8")
            runner = ConfigWindowRunner(
                root,
                ["status", "--porcelain=v1", "--untracked-files=no"],
                lambda path=config_path, data=status_aba_config: path.write_bytes(data),
                lambda path=config_path, data=original_config: path.write_bytes(data),
                mutate_before=True,
                restore_after=True,
            )
            output = self.base / f"config-status-aba-{root_name}"
            output.mkdir()
            with self.subTest(config_window=f"{root_name}:status-aba"):
                try:
                    receipt = self.call_bootstrap(output, runner=runner)
                except ValueError as error:
                    self.fail(
                        f"explicit Git binding did not neutralize status ABA: {error}"
                    )
                self.assertTrue(runner.mutated and runner.restored)
                self.assertEqual(runner.target_stdout, b"")
                self.assertEqual((output / "SDK/base.txt").read_bytes(), b"patched\n")
                self.assertIn("sourceCommitObjectSha256", receipt)
                self.assertEqual(
                    receipt["sourceCommitObjectSha256"],
                    hashlib.sha256(self.source_commit_object).hexdigest().upper(),
                )
            self.assertEqual(config_path.read_bytes(), original_config)

        sdk_config = self.sdk / ".git/config"
        original_sdk_config = sdk_config.read_bytes()
        archive_aba_config = original_sdk_config + (
            f"[core]\n\tattributesFile = {malicious_attributes}\n"
            "[tar]\n\tumask = 0077\n"
        ).encode("utf-8")
        archive_runner = ConfigWindowRunner(
            self.sdk,
            ["archive", "--format=tar", self.commit],
            lambda: sdk_config.write_bytes(archive_aba_config),
            lambda: sdk_config.write_bytes(original_sdk_config),
            mutate_before=True,
            restore_after=True,
        )
        archive_output = self.base / "config-archive-aba"
        archive_output.mkdir()
        with self.subTest(config_window="sdk:archive-aba"):
            try:
                receipt = self.call_bootstrap(
                    archive_output, runner=archive_runner
                )
            except ValueError as error:
                self.fail(
                    f"closed archive overrides did not neutralize config ABA: {error}"
                )
            self.assertTrue(archive_runner.mutated and archive_runner.restored)
            self.assertEqual(
                (archive_output / "SDK/base.txt").read_bytes(), b"patched\n"
            )
            self.assertIn("sourceCommitEpoch", receipt)
            self.assertEqual(receipt["sourceCommitEpoch"], self.source_commit_epoch)
        self.assertEqual(sdk_config.read_bytes(), original_sdk_config)

        post_apply_mode_output = self.base / "post-apply-mode-mutation"
        post_apply_mode_output.mkdir()
        post_apply_mode_runner = PostApplyModeMutationRunner(post_apply_mode_output)
        with self.subTest(output_use_window="chmod-after-apply"):
            with self.assertRaises(ValueError):
                self.call_bootstrap(
                    post_apply_mode_output, runner=post_apply_mode_runner
                )
            self.assertTrue(post_apply_mode_runner.mutated)
            self.assertTrue(
                post_apply_mode_runner.caller_untouched_at_mutation
            )
            self.assertEqual(post_apply_mode_runner.apply_calls, 2)
            self.assertEqual(list(post_apply_mode_output.iterdir()), [])

        sdk_info = self.sdk / ".git/info"
        info_cases = (
            (
                "attributes",
                sdk_info / "attributes",
                b"SDK/executable.sh export-ignore\n"
                b"SDK/archive-probe.txt export-subst\n",
            ),
            (
                "grafts",
                sdk_info / "grafts",
                (self.commit + "\n").encode("ascii"),
            ),
        )
        for index, (name, target, hostile_bytes) in enumerate(info_cases):
            runner = ConfigWindowRunner(
                self.sdk,
                ["archive", "--format=tar", self.commit],
                lambda path=target, data=hostile_bytes: path.write_bytes(data),
                lambda path=target: path.unlink(),
                mutate_before=True,
                restore_after=True,
            )
            output = self.base / f"git-info-archive-aba-{index}"
            output.mkdir()
            with self.subTest(git_info_archive_window=name):
                with self.assertRaises(ValueError):
                    self.call_bootstrap(output, runner=runner)
                self.assertTrue(runner.mutated and runner.restored)
                self.assertFalse(target.exists() or target.is_symlink())
                self.assertFalse(
                    any(git_verb(call[0]) == "apply" for call in runner.calls)
                )
                self.assertEqual(list(output.iterdir()), [])
                self.assertIsInstance(runner.target_stdout, bytes)
                with tarfile.open(
                    fileobj=io.BytesIO(runner.target_stdout), mode="r:"
                ) as archive:
                    names = set(archive.getnames())
                    if name == "attributes":
                        self.assertNotIn("SDK/executable.sh", names)
                        probe = archive.extractfile("SDK/archive-probe.txt")
                        self.assertIsNotNone(probe)
                        self.assertEqual(
                            probe.read(),
                            f"archive-probe:{self.commit}\n".encode("ascii"),
                        )
                    else:
                        self.assertIn("SDK/executable.sh", names)

        exclude_path = sdk_info / "exclude"
        exclude_before = exclude_path.read_bytes()
        exclude_runner = ConfigWindowRunner(
            self.sdk,
            ["archive", "--format=tar", self.commit],
            lambda: exclude_path.write_bytes(
                exclude_before + b"\n# transient operator metadata\n"
            ),
            lambda: exclude_path.write_bytes(exclude_before),
            mutate_before=True,
            restore_after=True,
        )
        exclude_output = self.base / "git-info-exclude-archive-aba"
        exclude_output.mkdir()
        with self.subTest(git_info_archive_window="exclude-is-inert"):
            try:
                self.call_bootstrap(exclude_output, runner=exclude_runner)
            except ValueError as error:
                self.fail(f"operator-local info/exclude affected bootstrap: {error}")
            self.assertTrue(exclude_runner.mutated and exclude_runner.restored)
            self.assertEqual(
                (exclude_output / "SDK/archive-probe.txt").read_bytes(),
                self.sdk_archive_probe.read_bytes(),
            )
        self.assertEqual(exclude_path.read_bytes(), exclude_before)

        shallow_path = self.sdk / ".git/shallow"
        shallow_before = shallow_path.read_bytes()
        shallow_alternate = (self.sdk_parent_commit + "\n").encode("ascii")
        shallow_one_way_runner = ConfigWindowRunner(
            self.sdk,
            ["status", "--porcelain=v1", "--untracked-files=no"],
            lambda: shallow_path.write_bytes(shallow_alternate),
            lambda: shallow_path.write_bytes(shallow_before),
            mutate_before=False,
            restore_after=False,
        )
        shallow_one_way_output = self.base / "shallow-one-way"
        shallow_one_way_output.mkdir()
        try:
            with self.subTest(shallow_window="one-way"):
                with self.assertRaises(ValueError):
                    self.call_bootstrap(
                        shallow_one_way_output, runner=shallow_one_way_runner
                    )
                self.assertTrue(shallow_one_way_runner.mutated)
                self.assertFalse(
                    any(
                        git_verb(call[0]) in ("archive", "apply")
                        for call in shallow_one_way_runner.calls
                    )
                )
                self.assertEqual(list(shallow_one_way_output.iterdir()), [])
        finally:
            shallow_one_way_runner.restore_now()
        self.assertEqual(shallow_path.read_bytes(), shallow_before)

        shallow_aba_runner = ConfigWindowRunner(
            self.sdk,
            ["archive", "--format=tar", self.commit],
            lambda: shallow_path.write_bytes(shallow_alternate),
            lambda: shallow_path.write_bytes(shallow_before),
            mutate_before=True,
            restore_after=True,
        )
        shallow_aba_output = self.base / "shallow-archive-aba"
        shallow_aba_output.mkdir()
        with self.subTest(shallow_window="archive-aba"):
            with self.assertRaises(ValueError):
                self.call_bootstrap(shallow_aba_output, runner=shallow_aba_runner)
            self.assertTrue(shallow_aba_runner.mutated and shallow_aba_runner.restored)
            self.assertFalse(
                any(
                    git_verb(call[0]) == "apply"
                    for call in shallow_aba_runner.calls
                )
            )
            self.assertEqual(list(shallow_aba_output.iterdir()), [])
        self.assertEqual(shallow_path.read_bytes(), shallow_before)

        for root_name, root, tracked in (
            ("source", self.repo, self.repo / self.overlay_records[0]["source"]),
            ("sdk", self.sdk, self.sdk / "SDK/base.txt"),
        ):
            index_path = root / ".git/index"
            original_index = index_path.read_bytes()
            relative = tracked.relative_to(root).as_posix()
            git("update-index", "--assume-unchanged", "--", relative, cwd=root)
            flagged_index = index_path.read_bytes()
            git("update-index", "--no-assume-unchanged", "--", relative, cwd=root)
            index_path.write_bytes(original_index)
            self.assertNotEqual(flagged_index, original_index)

            one_way_runner = ConfigWindowRunner(
                root,
                ["status", "--porcelain=v1", "--untracked-files=no"],
                lambda path=index_path, data=flagged_index: path.write_bytes(data),
                lambda path=index_path, data=original_index: path.write_bytes(data),
                mutate_before=False,
                restore_after=False,
            )
            one_way_output = self.base / f"index-one-way-{root_name}"
            one_way_output.mkdir()
            try:
                with self.subTest(index_window=f"{root_name}:one-way"):
                    with self.assertRaises(ValueError):
                        self.call_bootstrap(one_way_output, runner=one_way_runner)
                    self.assertTrue(one_way_runner.mutated)
                    self.assertFalse(
                        any(
                            git_verb(call[0]) in ("archive", "apply")
                            for call in one_way_runner.calls
                        )
                    )
                    self.assertEqual(list(one_way_output.iterdir()), [])
            finally:
                one_way_runner.restore_now()
            self.assertEqual(index_path.read_bytes(), original_index)

            aba_runner = ConfigWindowRunner(
                root,
                ["ls-files", "-v", "--stage", "-z", "--"],
                lambda path=index_path, data=flagged_index: path.write_bytes(data),
                lambda path=index_path, data=original_index: path.write_bytes(data),
                mutate_before=True,
                restore_after=True,
            )
            aba_output = self.base / f"index-aba-{root_name}"
            aba_output.mkdir()
            with self.subTest(index_window=f"{root_name}:aba"):
                with self.assertRaises(ValueError):
                    self.call_bootstrap(aba_output, runner=aba_runner)
                self.assertTrue(aba_runner.mutated and aba_runner.restored)
                self.assertFalse(
                    any(
                        git_verb(call[0]) in ("archive", "apply")
                        for call in aba_runner.calls
                    )
                )
                self.assertEqual(list(aba_output.iterdir()), [])
            self.assertEqual(index_path.read_bytes(), original_index)

    def test_cli_git_identity_is_cross_checked_against_the_loaded_lock(self):
        fixture = self.make_cli_fixture()
        toolchain_lock = json.loads(
            (fixture["repositoryRoot"] / "firmware/locks/toolchain.lock.json").read_bytes()
        )
        self.assertEqual(toolchain_lock["hostTools"]["git"], self.git_tool)
        output = self.base / "git-cross-check-output"
        output.mkdir()
        receipt_root = self.base / "git-cross-check-receipts"
        receipt_root.mkdir()
        receipt = receipt_root / "receipt.json"
        arguments = [
            "--repository-root", str(fixture["repositoryRoot"]),
            "--sdk-root", str(fixture["sdkRoot"]),
            "--output-root", str(output),
            "--receipt-path", str(receipt),
        ]
        with self.assertRaises(ValueError):
            self.call_cli(
                arguments,
                LockedSdkRunner(
                    fixture["sdkRoot"],
                    "d0167685d032d745d88fe50233302edd46941622",
                    "854734595be49510aca5afb89f5885e8bce6a00f",
                    fixture["archiveCommit"],
                ),
                {**self.git_tool, "sha256": "0" * 64},
                (fixture["toolchainRoot"], fixture["postBuildRoot"]),
            )
        self.assertEqual(list(output.iterdir()), [])
        self.assertFalse(receipt.exists())

        actual_output = self.base / "actual-cli-output"
        actual_output.mkdir()
        actual_receipt_root = self.base / "actual-cli-receipts"
        actual_receipt_root.mkdir()
        actual_receipt = actual_receipt_root / "receipt.json"
        actual_arguments = [
            "--repository-root",
            str(fixture["repositoryRoot"]),
            "--sdk-root",
            str(fixture["sdkRoot"]),
            "--output-root",
            str(actual_output),
            "--receipt-path",
            str(actual_receipt),
        ]
        actual_result = REAL_SUBPROCESS_RUN(
            [str(PYTHON), "-B", str(TOOL), *actual_arguments],
            cwd=ROOT,
            env={
                "LANG": "C",
                "LC_ALL": "C",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": "0",
                "TZ": "UTC",
            },
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            shell=False,
        )
        self.assertNotEqual(actual_result.returncode, 0)
        self.assertEqual(actual_result.stdout, b"")
        self.assertTrue(actual_result.stderr)
        self.assertIn(b"Git identity mismatch", actual_result.stderr)
        self.assertEqual(list(actual_output.iterdir()), [])
        self.assertFalse(actual_receipt.exists() or actual_receipt.is_symlink())

    def test_closed_cli_loads_exact_locks_and_fixed_contract_then_writes_create_only_receipt(self):
        syntax = ast.parse(TOOL.read_text(encoding="utf-8"), filename=str(TOOL))
        self.assertEqual(
            ast.unparse(syntax.body[-1]),
            "if __name__ == '__main__':\n    raise SystemExit(main())",
        )
        actual_failure_output = self.base / "actual-cli-failure-output"
        actual_failure_output.mkdir()
        actual_failure_receipt_parent = self.base / "actual-cli-failure-receipts"
        actual_failure_receipt_parent.mkdir()
        actual_failure_receipt = actual_failure_receipt_parent / "receipt.json"
        actual_failure = REAL_SUBPROCESS_RUN(
            [
                str(PYTHON),
                "-B",
                str(TOOL),
                "--repository-root",
                str(self.repo),
                "--sdk-root",
                str(self.sdk),
                "--output-root",
                str(actual_failure_output),
                "--receipt-path",
                str(actual_failure_receipt),
                "--forbidden-identity-override",
                "x",
            ],
            cwd=ROOT,
            env={
                "LANG": "C",
                "LC_ALL": "C",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": "0",
                "TZ": "UTC",
            },
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            shell=False,
        )
        self.assertNotEqual(actual_failure.returncode, 0)
        self.assertEqual(actual_failure.stdout, b"")
        self.assertNotEqual(actual_failure.stderr, b"")
        self.assertEqual(list(actual_failure_output.iterdir()), [])
        self.assertFalse(
            actual_failure_receipt.exists() or actual_failure_receipt.is_symlink()
        )
        parser = self.bootstrap.build_cli_parser()
        self.assertFalse(parser.allow_abbrev)
        actions = {
            action.dest: tuple(action.option_strings)
            for action in parser._actions
            if action.dest != "help"
        }
        self.assertEqual(
            actions,
            {
                "output_root": ("--output-root",),
                "receipt_path": ("--receipt-path",),
                "repository_root": ("--repository-root",),
                "sdk_root": ("--sdk-root",),
            },
        )
        for action in parser._actions:
            if action.dest != "help":
                self.assertTrue(action.required)
                self.assertIs(action.type, Path)

        def cli_arguments(fixture, output, receipt):
            return [
                "--repository-root", str(fixture["repositoryRoot"]),
                "--sdk-root", str(fixture["sdkRoot"]),
                "--output-root", str(output),
                "--receipt-path", str(receipt),
            ]

        fixture = self.make_cli_fixture()
        locked_sdk_commit = "d0167685d032d745d88fe50233302edd46941622"
        locked_sdk_tree = "854734595be49510aca5afb89f5885e8bce6a00f"
        runner = LockedSdkRunner(
            fixture["sdkRoot"],
            locked_sdk_commit,
            locked_sdk_tree,
            fixture["archiveCommit"],
        )
        output = self.base / "cli-output"
        output.mkdir()
        receipt_root = self.base / "cli-receipts"
        receipt_root.mkdir()
        receipt_path = receipt_root / "bootstrap-receipt.json"
        arguments = cli_arguments(fixture, output, receipt_path)
        with mock.patch.object(
            self.bootstrap,
            "build_cli_parser",
            wraps=self.bootstrap.build_cli_parser,
        ) as parser_builder:
            self.assertEqual(
                self.call_cli(
                    arguments,
                    runner,
                    self.git_tool,
                    (fixture["toolchainRoot"], fixture["postBuildRoot"]),
                ),
                0,
            )
        parser_builder.assert_called_once_with()
        raw_receipt = receipt_path.read_bytes()
        receipt = json.loads(raw_receipt)
        self.assertEqual(raw_receipt, self.bootstrap.canonical_json(receipt))
        self.assertEqual(
            set(receipt),
            {
                "commands",
                "gitTool",
                "locks",
                "outputTreeSha256",
                "overlay",
                "patch",
                "schema",
                "sdkCommit",
                "sdkTree",
                "sourceCommit",
                "sourceCommitEpoch",
                "sourceCommitObjectSha256",
                "sourceTree",
                "validations",
            },
        )
        self.assertEqual(receipt["schema"], "e87-stage0-bootstrap-receipt-v1")
        self.assertEqual(
            (receipt["sourceCommit"], receipt["sourceTree"]),
            (fixture["sourceCommit"], fixture["sourceTree"]),
        )
        self.assertIs(type(receipt["sourceCommitEpoch"]), int)
        self.assertEqual(
            receipt["sourceCommitEpoch"], fixture["sourceCommitEpoch"]
        )
        self.assertEqual(
            receipt["sourceCommitObjectSha256"],
            fixture["sourceCommitObjectSha256"],
        )
        self.assertEqual((receipt["sdkCommit"], receipt["sdkTree"]), (locked_sdk_commit, locked_sdk_tree))
        self.assertEqual(receipt["gitTool"], self.git_tool)
        expected_cli_commands = command_receipt_records(
            runner,
            repository_root=fixture["repositoryRoot"],
            sdk_root=fixture["sdkRoot"],
            output_root=output,
            git_tool=self.git_tool,
        )
        self.assertEqual(receipt["commands"], expected_cli_commands)
        self.assertEqual(receipt["validations"], VALIDATION_RESULTS)
        patch_bytes = (
            fixture["repositoryRoot"]
            / "firmware/patches/stage0/0001-e87-stage0-hooks.patch"
        ).read_bytes()
        self.assertEqual(
            receipt["patch"],
            {
                "paths": sorted(fixture["patchTargets"]),
                "sha256": hashlib.sha256(patch_bytes).hexdigest().upper(),
                "size": len(patch_bytes),
            },
        )
        expected_overlay = []
        for source in fixture["overlaySources"]:
            data = (fixture["repositoryRoot"] / source).read_bytes()
            expected_overlay.append(
                {
                    "destination": source.removeprefix("firmware/overlay/"),
                    "sha256": hashlib.sha256(data).hexdigest().upper(),
                    "size": len(data),
                    "source": source,
                }
            )
        self.assertEqual(
            receipt["overlay"], sorted(expected_overlay, key=lambda record: record["source"])
        )
        self.assertEqual(
            receipt["locks"],
            {
                "model1552-package.lock.json": "EFD3878979F029C56DA16E863EB89955E22D9B222046211A84AAC7BE1F3BA122",
                "packaging.lock.json": "28E6C1DEF70F894F89FDC7FFB8527F204688888C58EEDC052CD8A36F3AEBC003",
                    "toolchain.lock.json": "60D72D942FC66E89303FD059AC9904F9167AAB743A21E78AB7230AA6B5B2300D",
            },
        )
        self.assertEqual(receipt["outputTreeSha256"], independent_tree_sha256(output))
        for target in fixture["patchTargets"]:
            self.assertEqual((output / target).read_text(encoding="ascii"), f"patched:{target}\n")
        for source in fixture["overlaySources"]:
            destination = source.removeprefix("firmware/overlay/")
            self.assertEqual((output / destination).read_text(encoding="ascii"), f"overlay:{source}\n")
        apply_calls = [call for call in runner.calls if git_verb(call[0]) == "apply"]
        self.assertEqual(
            [git_arguments(call[0]) for call in apply_calls],
            [
                ["apply", "--no-index", "--check", "-"],
                ["apply", "--no-index", "-"],
            ],
        )
        self.assertEqual(apply_calls[0][1]["input"], apply_calls[1][1]["input"])
        self.assertEqual(apply_calls[0][1]["input"], patch_bytes)
        self.assertEqual(
            [
                record["stdin"]
                for record in receipt["commands"]
                if record["role"] in ("patch-check", "patch-apply")
            ],
            [
                {"sha256": receipt["patch"]["sha256"], "size": len(patch_bytes)},
                {"sha256": receipt["patch"]["sha256"], "size": len(patch_bytes)},
            ],
        )
        validator = self.bootstrap.validate_bootstrap_receipt
        validator_parameters = inspect.signature(validator).parameters
        self.assertEqual(
            list(validator_parameters),
            ["receipt", "require_locks", "expected_commands"],
        )
        self.assertIs(
            validator_parameters["require_locks"].kind,
            inspect.Parameter.KEYWORD_ONLY,
        )
        self.assertIs(
            validator_parameters["expected_commands"].kind,
            inspect.Parameter.KEYWORD_ONLY,
        )
        self.assertIs(
            validator_parameters["expected_commands"].default,
            inspect.Parameter.empty,
        )
        self.assertIsNone(
            validator(
                receipt,
                require_locks=True,
                expected_commands=expected_cli_commands,
            )
        )

        def clone_receipt():
            return json.loads(self.bootstrap.canonical_json(receipt))

        def reject_receipt(name, candidate, *, expected=expected_cli_commands):
            with self.subTest(receipt_validation=name):
                with self.assertRaises(ValueError):
                    validator(
                        candidate,
                        require_locks=True,
                        expected_commands=expected,
                    )

        candidate = clone_receipt()
        candidate.pop("commands")
        reject_receipt("missing-commands", candidate)
        candidate = clone_receipt()
        candidate["unknown"] = True
        reject_receipt("unknown-top-level", candidate)
        candidate = clone_receipt()
        candidate["commands"] = None
        reject_receipt("wrong-commands-type", candidate)
        candidate = clone_receipt()
        candidate["commands"][:2] = reversed(candidate["commands"][:2])
        reject_receipt("command-order", candidate)

        alternate_sha = lambda label: hashlib.sha256(
            ("semantic-drift:" + label).encode("utf-8")
        ).hexdigest().upper()

        def wrong_record_value(index, key, record):
            if key == "argv":
                return [*record[key], "--semantic-drift"]
            if key == "cwd":
                return {"source": "sdk", "sdk": "${OWNED_STAGING_ROOT}", "${OWNED_STAGING_ROOT}": "source"}[
                    record[key]
                ]
            if key == "environment":
                value = dict(record[key])
                value["LANG"] = "C.UTF-8"
                return value
            if key == "exitCode":
                return 1
            if key == "role":
                return COMMAND_ROLES[(index + 1) % len(COMMAND_ROLES)]
            if key in ("stderrSha256", "stdoutSha256", "toolSha256"):
                return alternate_sha(f"{index}:{key}")
            if key in ("stderrSize", "stdoutSize"):
                return record[key] + 1
            if key == "stdin":
                if record[key] is None:
                    return {"sha256": alternate_sha(f"{index}:stdin"), "size": 1}
                return None
            if key == "toolVersion":
                return "2.34.2"
            raise AssertionError(f"unhandled command key: {key}")

        for index, original_record in enumerate(receipt["commands"]):
            candidate = clone_receipt()
            candidate["commands"].pop(index)
            reject_receipt(f"command-{index}:missing-record", candidate)
            candidate = clone_receipt()
            candidate["commands"].insert(
                index, dict(candidate["commands"][index])
            )
            reject_receipt(f"command-{index}:duplicate-record", candidate)
            candidate = clone_receipt()
            candidate["commands"][index]["unknown"] = True
            reject_receipt(f"command-{index}:unknown-field", candidate)
            for key in sorted(COMMAND_RECORD_KEYS):
                candidate = clone_receipt()
                candidate["commands"][index].pop(key)
                reject_receipt(f"command-{index}:{key}:missing", candidate)
                candidate = clone_receipt()
                candidate["commands"][index][key] = wrong_record_value(
                    index, key, original_record
                )
                reject_receipt(f"command-{index}:{key}:wrong", candidate)

        for index in range(len(receipt["commands"])):
            if index in (16, 17):
                continue
            for nonnull in (
                False,
                "null",
                {"sha256": alternate_sha(f"nonnull:{index}"), "size": 1},
            ):
                candidate = clone_receipt()
                candidate["commands"][index]["stdin"] = nonnull
                reject_receipt(
                    f"command-{index}:nonpatch-stdin:{type(nonnull).__name__}",
                    candidate,
                )

        for index in (16, 17):
            for whole_object in (None, False, "stdin", {}, []):
                candidate = clone_receipt()
                candidate["commands"][index]["stdin"] = whole_object
                reject_receipt(
                    f"command-{index}:patch-stdin-whole:{type(whole_object).__name__}",
                    candidate,
                )
            candidate = clone_receipt()
            candidate["commands"][index]["stdin"]["unknown"] = True
            reject_receipt(f"command-{index}:patch-stdin-unknown", candidate)
            for nested_key in ("sha256", "size"):
                candidate = clone_receipt()
                candidate["commands"][index]["stdin"].pop(nested_key)
                reject_receipt(
                    f"command-{index}:patch-stdin-{nested_key}:missing",
                    candidate,
                )
                candidate = clone_receipt()
                candidate["commands"][index]["stdin"][nested_key] = (
                    1 if nested_key == "sha256" else "1"
                )
                reject_receipt(
                    f"command-{index}:patch-stdin-{nested_key}:wrong-type",
                    candidate,
                )
                candidate = clone_receipt()
                candidate["commands"][index]["stdin"][nested_key] = (
                    alternate_sha(f"patch:{index}")
                    if nested_key == "sha256"
                    else receipt["patch"]["size"] + 1
                )
                reject_receipt(
                    f"command-{index}:patch-stdin-{nested_key}:wrong-value",
                    candidate,
                )

        for validation_name in sorted(VALIDATION_RESULTS):
            candidate = clone_receipt()
            candidate["validations"].pop(validation_name)
            reject_receipt(f"validation-{validation_name}:missing", candidate)
            candidate = clone_receipt()
            candidate["validations"][validation_name] = False
            reject_receipt(f"validation-{validation_name}:false", candidate)
            candidate = clone_receipt()
            candidate["validations"][validation_name] = "true"
            reject_receipt(f"validation-{validation_name}:nonbool", candidate)
        candidate = clone_receipt()
        candidate["validations"]["unknown"] = True
        reject_receipt("validation-unknown", candidate)

        independently_mutated_expected = json.loads(
            self.bootstrap.canonical_json(expected_cli_commands)
        )
        independently_mutated_expected[1]["stdoutSha256"] = alternate_sha(
            "expected-only"
        )
        reject_receipt(
            "independent-expected-trace-drift",
            clone_receipt(),
            expected=independently_mutated_expected,
        )
        with self.subTest(receipt_validation="receipt-commands-not-independent"):
            with self.assertRaises(ValueError):
                validator(
                    receipt,
                    require_locks=True,
                    expected_commands=receipt["commands"],
                )

        receipt_before = receipt_path.read_bytes()
        second_output = self.base / "cli-second-output"
        second_output.mkdir()
        second_arguments = list(arguments)
        second_arguments[second_arguments.index(str(output))] = str(second_output)
        with self.assertRaises(ValueError):
            self.call_cli(
                second_arguments,
                LockedSdkRunner(
                    fixture["sdkRoot"], locked_sdk_commit, locked_sdk_tree, fixture["archiveCommit"]
                ),
                self.git_tool,
                (fixture["toolchainRoot"], fixture["postBuildRoot"]),
            )
        self.assertEqual(list(second_output.iterdir()), [])
        self.assertEqual(receipt_path.read_bytes(), receipt_before)

        for index, kind in enumerate(("regular", "symlink")):
            with self.subTest(receipt_appearance_race=kind):
                race_fixture = self.make_cli_fixture(f"-receipt-race-{index}")
                race_output = self.base / f"receipt-race-output-{index}"
                race_output.mkdir()
                race_receipt_parent = self.base / f"receipt-race-parent-{index}"
                race_receipt_parent.mkdir()
                race_receipt = race_receipt_parent / "receipt.json"
                sentinel_bytes = b"late receipt sentinel must survive exactly\n"
                sentinel_target = None
                if kind == "regular":
                    mutation = lambda path=race_receipt: path.write_bytes(
                        sentinel_bytes
                    )
                else:
                    sentinel_target = race_receipt_parent / "symlink-target.json"
                    sentinel_target.write_bytes(sentinel_bytes)
                    mutation = lambda path=race_receipt, target=sentinel_target: path.symlink_to(
                        target
                    )
                race_runner = ReceiptAppearanceRunner(
                    race_fixture["sdkRoot"],
                    locked_sdk_commit,
                    locked_sdk_tree,
                    race_fixture["archiveCommit"],
                    mutation=mutation,
                )
                with self.assertRaises(ValueError):
                    self.call_cli(
                        cli_arguments(race_fixture, race_output, race_receipt),
                        race_runner,
                        self.git_tool,
                        (
                            race_fixture["toolchainRoot"],
                            race_fixture["postBuildRoot"],
                        ),
                    )
                self.assertTrue(race_runner.mutated)
                self.assertEqual(race_runner.final_sdk_checks, 2)
                self.assertEqual(list(race_output.iterdir()), [])
                if kind == "regular":
                    self.assertTrue(
                        race_receipt.is_file() and not race_receipt.is_symlink()
                    )
                    self.assertEqual(race_receipt.read_bytes(), sentinel_bytes)
                else:
                    self.assertTrue(race_receipt.is_symlink())
                    self.assertEqual(os.readlink(race_receipt), str(sentinel_target))
                    self.assertEqual(sentinel_target.read_bytes(), sentinel_bytes)

        forbidden_flags = (
            "--toolchain-root",
            "--post-build-root",
            "--source-commit",
            "--source-commit-epoch",
            "--source-commit-object-sha256",
            "--expected-source-commit",
            "--expected-source-tree",
            "--expected-sdk-commit",
            "--expected-sdk-tree",
            "--overlay",
            "--allowed-patch-path",
            "--patch",
            "--git-path",
            "--git-sha256",
        )
        for index, flag in enumerate(forbidden_flags):
            with self.subTest(main_forbidden_override=flag):
                rejected_runner = RecordingRunner()
                rejected_output = self.base / f"forbidden-cli-output-{index}"
                rejected_output.mkdir()
                rejected_receipt_root = self.base / f"forbidden-cli-receipts-{index}"
                rejected_receipt_root.mkdir()
                rejected_receipt = rejected_receipt_root / "receipt.json"
                rejected = cli_arguments(
                    fixture,
                    rejected_output,
                    rejected_receipt,
                ) + [flag, "forbidden"]
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as rejected_exit:
                        self.call_cli(
                            rejected,
                            rejected_runner,
                            self.git_tool,
                            (fixture["toolchainRoot"], fixture["postBuildRoot"]),
                        )
                self.assertNotIn(rejected_exit.exception.code, (None, 0))
                self.assertEqual(rejected_runner.calls, [])
                self.assertEqual(list(rejected_output.iterdir()), [])
                self.assertFalse(rejected_receipt.exists() or rejected_receipt.is_symlink())

        receipt_cases = (
            "relative",
            "missing-parent",
            "file-parent",
            "symlink-parent",
            "symlink-target",
            "preexisting",
            "inside-repository",
            "inside-sdk",
            "inside-toolchain",
            "inside-post-build",
            "inside-output",
            "parent-contains-output",
            "parent-contains-protected-roots",
        )
        for index, kind in enumerate(receipt_cases):
            with self.subTest(receipt_path=kind):
                protected_container = None
                if kind == "parent-contains-protected-roots":
                    protected_container = self.base / f"protected-container-{index}"
                    protected_container.mkdir()
                receipt_fixture = self.make_cli_fixture(
                    f"-receipt-{index}", parent=protected_container
                )
                rejected_output = self.base / f"receipt-output-{index}"
                rejected_output.mkdir()
                safe_parent = self.base / f"receipt-safe-parent-{index}"
                safe_parent.mkdir()
                sentinel_path = None
                sentinel_bytes = None
                if kind == "relative":
                    absolute_candidate = safe_parent / "relative-receipt.json"
                    candidate = Path(os.path.relpath(absolute_candidate, Path.cwd()))
                elif kind == "missing-parent":
                    candidate = self.base / f"missing-receipt-parent-{index}" / "receipt.json"
                elif kind == "file-parent":
                    parent_file = self.base / f"receipt-parent-file-{index}"
                    parent_file.write_bytes(b"parent sentinel")
                    candidate = parent_file / "receipt.json"
                elif kind == "symlink-parent":
                    real_parent = self.base / f"real-receipt-parent-{index}"
                    real_parent.mkdir()
                    linked_parent = self.base / f"linked-receipt-parent-{index}"
                    linked_parent.symlink_to(real_parent, target_is_directory=True)
                    candidate = linked_parent / "receipt.json"
                elif kind == "symlink-target":
                    sentinel_path = safe_parent / "target.json"
                    sentinel_bytes = b"symlink target sentinel"
                    sentinel_path.write_bytes(sentinel_bytes)
                    candidate = safe_parent / "receipt.json"
                    candidate.symlink_to(sentinel_path)
                elif kind == "preexisting":
                    candidate = safe_parent / "receipt.json"
                    sentinel_path = candidate
                    sentinel_bytes = b"preexisting receipt sentinel"
                    candidate.write_bytes(sentinel_bytes)
                elif kind == "inside-repository":
                    candidate = receipt_fixture["repositoryRoot"] / "receipt.json"
                elif kind == "inside-sdk":
                    candidate = receipt_fixture["sdkRoot"] / "receipt.json"
                elif kind == "inside-toolchain":
                    candidate = receipt_fixture["toolchainRoot"] / "receipt.json"
                elif kind == "inside-post-build":
                    candidate = receipt_fixture["postBuildRoot"] / "receipt.json"
                elif kind == "inside-output":
                    candidate = rejected_output / "receipt.json"
                elif kind == "parent-contains-output":
                    containing_parent = self.base / f"receipt-contains-output-{index}"
                    containing_parent.mkdir()
                    rejected_output.rmdir()
                    rejected_output = containing_parent / "output"
                    rejected_output.mkdir()
                    candidate = containing_parent / "receipt.json"
                else:
                    candidate = protected_container / "receipt.json"
                initially_exists = candidate.exists() or candidate.is_symlink()
                rejected_runner = LockedSdkRunner(
                    receipt_fixture["sdkRoot"],
                    locked_sdk_commit,
                    locked_sdk_tree,
                    receipt_fixture["archiveCommit"],
                )
                with self.assertRaises(ValueError):
                    self.call_cli(
                        cli_arguments(receipt_fixture, rejected_output, candidate),
                        rejected_runner,
                        self.git_tool,
                        (
                            receipt_fixture["toolchainRoot"],
                            receipt_fixture["postBuildRoot"],
                        ),
                    )
                self.assertFalse(
                    any(
                        git_verb(call[0]) in ("archive", "apply")
                        for call in rejected_runner.calls
                    )
                )
                self.assertEqual(list(rejected_output.iterdir()), [])
                if sentinel_path is not None:
                    self.assertEqual(sentinel_path.read_bytes(), sentinel_bytes)
                if not initially_exists:
                    self.assertFalse(candidate.exists() or candidate.is_symlink())

        for index, mutation in enumerate(("missing", "mutated", "unknown")):
            with self.subTest(lock_contract=mutation):
                rejected_fixture = self.make_cli_fixture(f"-{mutation}")
                lock_root = rejected_fixture["repositoryRoot"] / "firmware/locks"
                if mutation == "missing":
                    (lock_root / "model1552-package.lock.json").unlink()
                elif mutation == "mutated":
                    lock_path = lock_root / "toolchain.lock.json"
                    value = json.loads(lock_path.read_bytes())
                    value["sdk"]["commit"] = "0" * 40
                    lock_path.write_bytes(
                        (json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii")
                    )
                else:
                    lock_path = lock_root / "packaging.lock.json"
                    value = json.loads(lock_path.read_bytes())
                    value["unknown"] = True
                    lock_path.write_bytes(
                        (json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("ascii")
                    )
                git("add", "-A", cwd=rejected_fixture["repositoryRoot"])
                git("commit", "-q", "-m", f"{mutation} lock fixture", cwd=rejected_fixture["repositoryRoot"])
                rejected_output = self.base / f"cli-rejected-{index}"
                rejected_output.mkdir()
                rejected_receipt_root = self.base / f"cli-rejected-receipts-{index}"
                rejected_receipt_root.mkdir()
                rejected_receipt = rejected_receipt_root / "receipt.json"
                rejected_runner = LockedSdkRunner(
                    rejected_fixture["sdkRoot"],
                    locked_sdk_commit,
                    locked_sdk_tree,
                    rejected_fixture["archiveCommit"],
                )
                with self.assertRaises(ValueError):
                    self.call_cli(
                        cli_arguments(rejected_fixture, rejected_output, rejected_receipt),
                        rejected_runner,
                        self.git_tool,
                        (
                            rejected_fixture["toolchainRoot"],
                            rejected_fixture["postBuildRoot"],
                        ),
                    )
                self.assertFalse(
                    any(git_verb(call[0]) in ("archive", "apply") for call in rejected_runner.calls)
                )
                self.assertEqual(list(rejected_output.iterdir()), [])
                self.assertFalse(rejected_receipt.exists())

    def test_cli_rejects_nonempty_output_without_changing_caller_bytes_mode_or_inode(self):
        fixture = self.make_cli_fixture("-nonempty-caller")
        output = self.base / "nonempty-caller-output"
        output.mkdir(mode=0o750)
        sentinel = output / "caller-sentinel.bin"
        sentinel_bytes = b"caller-owned output must survive rejection exactly\n"
        sentinel.write_bytes(sentinel_bytes)
        sentinel.chmod(0o640)
        output_before = output.stat(follow_symlinks=False)
        sentinel_before = sentinel.stat(follow_symlinks=False)
        receipt_parent = self.base / "nonempty-caller-receipts"
        receipt_parent.mkdir()
        receipt = receipt_parent / "receipt.json"
        runner = LockedSdkRunner(
            fixture["sdkRoot"],
            "d0167685d032d745d88fe50233302edd46941622",
            "854734595be49510aca5afb89f5885e8bce6a00f",
            fixture["archiveCommit"],
        )

        with self.assertRaises(ValueError):
            self.call_cli(
                bootstrap_cli_arguments(fixture, output, receipt),
                runner,
                self.git_tool,
                (fixture["toolchainRoot"], fixture["postBuildRoot"]),
            )

        self.assertTrue(sentinel.is_file() and not sentinel.is_symlink())
        self.assertEqual(sentinel.read_bytes(), sentinel_bytes)
        output_after = output.stat(follow_symlinks=False)
        sentinel_after = sentinel.stat(follow_symlinks=False)
        self.assertEqual(
            (output_after.st_dev, output_after.st_ino, stat.S_IMODE(output_after.st_mode)),
            (output_before.st_dev, output_before.st_ino, stat.S_IMODE(output_before.st_mode)),
        )
        self.assertEqual(
            (
                sentinel_after.st_dev,
                sentinel_after.st_ino,
                stat.S_IMODE(sentinel_after.st_mode),
            ),
            (
                sentinel_before.st_dev,
                sentinel_before.st_ino,
                stat.S_IMODE(sentinel_before.st_mode),
            ),
        )
        self.assertEqual(runner.calls, [])
        self.assertFalse(receipt.exists() or receipt.is_symlink())

    def test_precreated_empty_output_is_committed_from_owned_same_parent_staging(self):
        output = self.base / "precreated-empty-output"
        output.mkdir(mode=0o750)
        output_before = output.stat(follow_symlinks=False)
        sibling = self.base / "caller-sibling.txt"
        sibling_bytes = b"caller sibling must remain untouched\n"
        sibling.write_bytes(sibling_bytes)
        sibling.chmod(0o640)
        sibling_before = sibling.stat(follow_symlinks=False)
        initial_siblings = {path.name for path in self.base.iterdir()}
        runner = OwnedStagingObserverRunner(output)
        archive = closed_git_archive(self.sdk, self.commit)

        with mock.patch.object(
            self.bootstrap,
            "SDK_ARCHIVE_SHA256",
            hashlib.sha256(archive).hexdigest().upper(),
            create=True,
        ):
            self.call_bootstrap(output, runner=runner)

        output_after = output.stat(follow_symlinks=False)
        sibling_after = sibling.stat(follow_symlinks=False)
        self.assertEqual(
            (output_after.st_dev, output_after.st_ino, stat.S_IMODE(output_after.st_mode)),
            (output_before.st_dev, output_before.st_ino, stat.S_IMODE(output_before.st_mode)),
        )
        self.assertEqual(sibling.read_bytes(), sibling_bytes)
        self.assertEqual(
            (
                sibling_after.st_dev,
                sibling_after.st_ino,
                stat.S_IMODE(sibling_after.st_mode),
            ),
            (
                sibling_before.st_dev,
                sibling_before.st_ino,
                stat.S_IMODE(sibling_before.st_mode),
            ),
        )
        self.assertEqual({path.name for path in self.base.iterdir()}, initial_siblings)
        self.assertTrue(runner.saw_owned_staging)
        self.assertTrue(runner.caller_untouched_at_apply)

    def test_failed_materialization_removes_only_owned_0700_staging(self):
        output = self.base / "failed-staging-output"
        output.mkdir(mode=0o750)
        output_before = output.stat(follow_symlinks=False)
        sibling = self.base / "failed-staging-sibling.txt"
        sibling_bytes = b"failure must not touch caller siblings\n"
        sibling.write_bytes(sibling_bytes)
        sibling.chmod(0o640)
        sibling_before = sibling.stat(follow_symlinks=False)
        initial_siblings = {path.name for path in self.base.iterdir()}
        runner = OwnedStagingObserverRunner(output, fail_first_apply=True)
        archive = closed_git_archive(self.sdk, self.commit)

        with mock.patch.object(
            self.bootstrap,
            "SDK_ARCHIVE_SHA256",
            hashlib.sha256(archive).hexdigest().upper(),
            create=True,
        ):
            with self.assertRaises(ValueError):
                self.call_bootstrap(output, runner=runner)

        output_after = output.stat(follow_symlinks=False)
        sibling_after = sibling.stat(follow_symlinks=False)
        self.assertEqual(
            (output_after.st_dev, output_after.st_ino, stat.S_IMODE(output_after.st_mode)),
            (output_before.st_dev, output_before.st_ino, stat.S_IMODE(output_before.st_mode)),
        )
        self.assertEqual(list(output.iterdir()), [])
        self.assertEqual(sibling.read_bytes(), sibling_bytes)
        self.assertEqual(
            (
                sibling_after.st_dev,
                sibling_after.st_ino,
                stat.S_IMODE(sibling_after.st_mode),
            ),
            (
                sibling_before.st_dev,
                sibling_before.st_ino,
                stat.S_IMODE(sibling_before.st_mode),
            ),
        )
        self.assertEqual({path.name for path in self.base.iterdir()}, initial_siblings)
        self.assertTrue(runner.saw_owned_staging)
        self.assertTrue(runner.caller_untouched_at_apply)

    def test_cli_lexical_output_symlink_rejection_preserves_target(self):
        fixture = self.make_cli_fixture("-lexical-output-link")
        target = self.base / "lexical-output-target"
        target.mkdir()
        sentinel = target / "sentinel.bin"
        sentinel_bytes = b"lexical output target sentinel\n"
        sentinel.write_bytes(sentinel_bytes)
        sentinel.chmod(0o640)
        sentinel_before = sentinel.stat(follow_symlinks=False)
        output = self.base / "lexical-output-link"
        output.symlink_to(target, target_is_directory=True)
        receipt_parent = self.base / "lexical-output-receipts"
        receipt_parent.mkdir()
        receipt = receipt_parent / "receipt.json"
        runner = RecordingRunner()

        with self.assertRaises(ValueError):
            self.call_cli(
                bootstrap_cli_arguments(fixture, output, receipt),
                runner,
                self.git_tool,
                (fixture["toolchainRoot"], fixture["postBuildRoot"]),
            )

        self.assertEqual(runner.calls, [])
        self.assertTrue(output.is_symlink())
        self.assertEqual(sentinel.read_bytes(), sentinel_bytes)
        sentinel_after = sentinel.stat(follow_symlinks=False)
        self.assertEqual(
            (
                sentinel_after.st_dev,
                sentinel_after.st_ino,
                stat.S_IMODE(sentinel_after.st_mode),
            ),
            (
                sentinel_before.st_dev,
                sentinel_before.st_ino,
                stat.S_IMODE(sentinel_before.st_mode),
            ),
        )
        self.assertFalse(receipt.exists() or receipt.is_symlink())

    def test_cli_postcheck_output_rebind_never_clears_redirect_target(self):
        fixture = self.make_cli_fixture("-postcheck-output-rebind")
        output = self.base / "postcheck-output"
        output.mkdir()
        redirect_target = self.base / "postcheck-redirect-target"
        redirect_target.mkdir()
        sentinel = redirect_target / "sentinel.bin"
        sentinel_bytes = b"post-check redirect target sentinel\n"
        sentinel.write_bytes(sentinel_bytes)
        sentinel.chmod(0o640)
        sentinel_before = sentinel.stat(follow_symlinks=False)
        receipt_parent = self.base / "postcheck-output-receipts"
        receipt_parent.mkdir()
        receipt = receipt_parent / "receipt.json"
        runner = LockedOutputRebindRunner(
            fixture["sdkRoot"],
            "d0167685d032d745d88fe50233302edd46941622",
            "854734595be49510aca5afb89f5885e8bce6a00f",
            fixture["archiveCommit"],
            output_root=output,
            symlink_target=redirect_target,
        )

        try:
            with self.assertRaises(ValueError):
                self.call_cli(
                    bootstrap_cli_arguments(fixture, output, receipt),
                    runner,
                    self.git_tool,
                    (fixture["toolchainRoot"], fixture["postBuildRoot"]),
                )
            self.assertTrue(runner.mutated)
            self.assertTrue(sentinel.is_file() and not sentinel.is_symlink())
            self.assertEqual(sentinel.read_bytes(), sentinel_bytes)
            sentinel_after = sentinel.stat(follow_symlinks=False)
            self.assertEqual(
                (
                    sentinel_after.st_dev,
                    sentinel_after.st_ino,
                    stat.S_IMODE(sentinel_after.st_mode),
                ),
                (
                    sentinel_before.st_dev,
                    sentinel_before.st_ino,
                    stat.S_IMODE(sentinel_before.st_mode),
                ),
            )
            self.assertFalse(receipt.exists() or receipt.is_symlink())
        finally:
            runner.restore_now()

    def test_actual_source_git_config_profile_is_exact_and_closed(self):
        actual = (
            b"[core]\n"
            b"\trepositoryformatversion = 0\n"
            b"\tfilemode = true\n"
            b"\tbare = false\n"
            b"\tlogallrefupdates = true\n"
            b'[remote "bootstrap"]\n'
            b"\turl = /home/jethac/.cache/codex-transfer/factory-android-badges-e87.bundle\n"
            b"\tfetch = +refs/heads/*:refs/remotes/bootstrap/*\n"
            b'[branch "codex/e87-local-rendering"]\n'
            b"\tremote = bootstrap\n"
            b"\tmerge = refs/heads/codex/e87-local-rendering\n"
            b'[remote "origin"]\n'
            b"\turl = https://github.com/jethac/factory-android-badges.git\n"
            b"\tfetch = +refs/heads/*:refs/remotes/origin/*\n"
            b"[user]\n"
            b"\tname = Jetha Chan\n"
            b"\temail = jethachan@gmail.com\n"
        )
        self.assertEqual(
            hashlib.sha256(actual).hexdigest(),
            "8e6b29461f33a284ab8cfa925a88c0651ccf9159802dc00a06f5505881d0108b",
        )
        config = self.repo / ".git/config"
        config.write_bytes(actual)
        self.bootstrap._parse_local_config(self.repo, "source")

        mutations = {
            "bootstrap-bundle": actual.replace(
                b"factory-android-badges-e87.bundle",
                b"different.bundle",
                1,
            ),
            "origin": actual.replace(
                b"https://github.com/jethac/factory-android-badges.git",
                b"https://github.com/jethac/different.git",
                1,
            ),
            "branch": actual.replace(
                b"refs/heads/codex/e87-local-rendering",
                b"refs/heads/main",
                1,
            ),
            "user": actual.replace(b"jethachan@gmail.com", b"other@example.com", 1),
            "include": actual + b"[include]\n\tpath = /tmp/host-config\n",
        }
        for name, data in mutations.items():
            with self.subTest(source_config_mutation=name):
                config.write_bytes(data)
                with self.assertRaises(ValueError):
                    self.bootstrap._parse_local_config(self.repo, "source")

    def test_actual_sdk_git_config_profile_is_exact_and_closed(self):
        actual = (
            b"[core]\n"
            b"\trepositoryformatversion = 0\n"
            b"\tfilemode = true\n"
            b"\tbare = false\n"
            b"\tlogallrefupdates = true\n"
            b'[remote "origin"]\n'
            b"\turl = https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200.git\n"
            b"\tfetch = +refs/heads/main:refs/remotes/origin/main\n"
            b'[branch "main"]\n'
            b"\tremote = origin\n"
            b"\tmerge = refs/heads/main\n"
        )
        self.assertEqual(
            hashlib.sha256(actual).hexdigest(),
            "a426dcc7ae525bd6ae1b60fce58c9747b83bbfc96dac2ac8ee4888f2f2582f96",
        )
        config = self.sdk / ".git/config"
        config.write_bytes(actual)
        self.bootstrap._parse_local_config(self.sdk, "sdk")

        mutations = {
            "origin": actual.replace(
                b"https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200.git",
                b"https://gitlab.zh-jieli.com/e_badge/different.git",
                1,
            ),
            "fetch": actual.replace(
                b"+refs/heads/main:refs/remotes/origin/main",
                b"+refs/heads/*:refs/remotes/origin/*",
                1,
            ),
            "branch": actual.replace(b"refs/heads/main", b"refs/heads/other", 1),
            "user": actual + b"[user]\n\tname = unexpected\n",
            "fsmonitor": actual + b"[core]\n\tfsmonitor = /tmp/host-hook\n",
        }
        for name, data in mutations.items():
            with self.subTest(sdk_config_mutation=name):
                config.write_bytes(data)
                with self.assertRaises(ValueError):
                    self.bootstrap._parse_local_config(self.sdk, "sdk")

    def test_overlay_first_read_is_bound_to_token_and_confirmation_read(self):
        output = self.base / "overlay-read-token-read-output"
        output.mkdir()
        overlay = self.repo / self.overlay_records[0]["source"]
        original = overlay.read_bytes()
        malicious = b"transient overlay bytes\n"
        original_read_bytes = Path.read_bytes
        first_overlay_read = False

        def read_bytes_with_transient_overlay(path):
            nonlocal first_overlay_read
            if Path(path) == overlay and not first_overlay_read:
                first_overlay_read = True
                return malicious
            return original_read_bytes(path)

        archive = closed_git_archive(self.sdk, self.commit)
        with mock.patch.object(
            self.bootstrap,
            "SDK_ARCHIVE_SHA256",
            hashlib.sha256(archive).hexdigest().upper(),
            create=True,
        ), mock.patch.object(Path, "read_bytes", new=read_bytes_with_transient_overlay):
            with self.assertRaises(ValueError):
                self.call_bootstrap(output)

        self.assertTrue(first_overlay_read)
        self.assertEqual(overlay.read_bytes(), original)
        self.assertEqual(list(output.iterdir()), [])

    def test_output_injected_after_preflight_is_not_added_to_expected_inventory(self):
        output = self.base / "injected-output"
        output.mkdir()
        runner = OutputInjectionRunner(self.sdk, output)
        archive = closed_git_archive(self.sdk, self.commit)

        with mock.patch.object(
            self.bootstrap,
            "SDK_ARCHIVE_SHA256",
            hashlib.sha256(archive).hexdigest().upper(),
            create=True,
        ):
            with self.assertRaises(ValueError):
                self.call_bootstrap(output, runner=runner)

        self.assertIsNotNone(runner.injected_target)
        self.assertEqual(list(output.iterdir()), [])

    def test_reviewed_sdk_archive_digest_is_the_exact_production_pin(self):
        self.assertEqual(
            getattr(self.bootstrap, "SDK_ARCHIVE_SHA256", None),
            "63FC570329AECE5032C3968B2C7EEA636E16F6322990E9578F330CD5A8DA8A35",
        )

    def test_sdk_archive_is_generated_twice_before_extraction(self):
        output = self.base / "two-archive-output"
        output.mkdir()
        archive = closed_git_archive(self.sdk, self.commit)
        runner = ArchiveBytesRunner(self.sdk, output, [archive, archive])

        with mock.patch.object(
            self.bootstrap,
            "SDK_ARCHIVE_SHA256",
            hashlib.sha256(archive).hexdigest().upper(),
            create=True,
        ):
            self.call_bootstrap(output, runner=runner)

        self.assertEqual(runner.archive_calls, 2)
        self.assertTrue(runner.second_call_saw_empty_staging)
        self.assertEqual((output / "SDK/base.txt").read_bytes(), b"patched\n")

    def test_wrong_sdk_archive_bytes_are_rejected_before_extraction(self):
        output = self.base / "wrong-archive-output"
        output.mkdir()
        expected_archive = closed_git_archive(self.sdk, self.commit)
        wrong_archive = closed_git_archive(self.sdk, self.sdk_parent_commit)
        self.assertNotEqual(
            hashlib.sha256(wrong_archive).digest(),
            hashlib.sha256(expected_archive).digest(),
        )
        for index, archive_pair in enumerate(
            (
                [wrong_archive, wrong_archive],
                [expected_archive, wrong_archive],
                [wrong_archive, expected_archive],
            )
        ):
            candidate_output = output if index == 0 else self.base / f"wrong-archive-output-{index}"
            if index:
                candidate_output.mkdir()
            runner = ArchiveBytesRunner(self.sdk, candidate_output, archive_pair)
            with mock.patch.object(
                self.bootstrap,
                "SDK_ARCHIVE_SHA256",
                hashlib.sha256(expected_archive).hexdigest().upper(),
                create=True,
            ):
                with self.subTest(pair=index), self.assertRaises(ValueError):
                    self.call_bootstrap(candidate_output, runner=runner)
            self.assertEqual(runner.archive_calls, 2)
            self.assertTrue(runner.second_call_saw_empty_staging)
            self.assertEqual(list(candidate_output.iterdir()), [])

    def test_receipt_parent_rebind_is_rejected_without_writing_anywhere(self):
        fixture = self.make_cli_fixture("-receipt-parent-rebind")
        output = self.base / "receipt-parent-rebind-output"
        output.mkdir()
        receipt_parent = self.base / "receipt-parent-rebind"
        receipt_parent.mkdir()
        receipt = receipt_parent / "receipt.json"
        redirect_target = fixture["toolchainRoot"]
        sentinel = redirect_target / "protected-sentinel.bin"
        sentinel_bytes = b"protected receipt redirect sentinel\n"
        sentinel.write_bytes(sentinel_bytes)
        sentinel.chmod(0o640)
        sentinel_before = sentinel.stat(follow_symlinks=False)
        redirected_receipt = redirect_target / receipt.name
        runner = ReceiptParentRebindRunner(
            fixture["sdkRoot"],
            "d0167685d032d745d88fe50233302edd46941622",
            "854734595be49510aca5afb89f5885e8bce6a00f",
            fixture["archiveCommit"],
            receipt_parent=receipt_parent,
            redirect_target=redirect_target,
        )
        rejected = False

        try:
            try:
                self.call_cli(
                    bootstrap_cli_arguments(fixture, output, receipt),
                    runner,
                    self.git_tool,
                    (fixture["toolchainRoot"], fixture["postBuildRoot"]),
                )
            except ValueError:
                rejected = True
        finally:
            runner.restore_now()

        self.assertTrue(runner.mutated)
        self.assertEqual(sentinel.read_bytes(), sentinel_bytes)
        sentinel_after = sentinel.stat(follow_symlinks=False)
        self.assertEqual(
            (
                sentinel_after.st_dev,
                sentinel_after.st_ino,
                stat.S_IMODE(sentinel_after.st_mode),
            ),
            (
                sentinel_before.st_dev,
                sentinel_before.st_ino,
                stat.S_IMODE(sentinel_before.st_mode),
            ),
        )
        self.assertFalse(receipt.exists() or receipt.is_symlink())
        self.assertFalse(redirected_receipt.exists() or redirected_receipt.is_symlink())
        self.assertTrue(rejected)
        self.assertEqual(list(output.iterdir()), [])

    def test_self_derived_mutated_command_copy_is_not_an_independent_oracle(self):
        output = self.base / "independent-command-oracle-output"
        output.mkdir()
        archive = closed_git_archive(self.sdk, self.commit)
        with mock.patch.object(
            self.bootstrap,
            "SDK_ARCHIVE_SHA256",
            hashlib.sha256(archive).hexdigest().upper(),
            create=True,
        ):
            receipt = self.call_bootstrap(output)

        def mutate_argv(candidate):
            candidate["commands"][0]["argv"].append("--forged")

        def mutate_environment(candidate):
            candidate["commands"][0]["environment"]["PATH"] = "/tmp/forged"

        def mutate_order(candidate):
            first = candidate["commands"][0]["argv"]
            second = candidate["commands"][1]["argv"]
            candidate["commands"][0]["argv"] = second
            candidate["commands"][1]["argv"] = first

        for name, mutation in (
            ("argv", mutate_argv),
            ("environment", mutate_environment),
            ("order", mutate_order),
        ):
            with self.subTest(command_contract=name):
                candidate = json.loads(self.bootstrap.canonical_json(receipt))
                mutation(candidate)
                self_derived_copy = json.loads(
                    self.bootstrap.canonical_json(candidate["commands"])
                )
                with self.assertRaises(ValueError):
                    self.bootstrap.validate_bootstrap_receipt(
                        candidate,
                        require_locks=False,
                        expected_commands=self_derived_copy,
                    )

    def test_receipt_writer_is_canonical_and_rejects_preexisting_target(self):
        receipt = {"z": 1, "a": [2]}
        path = self.base / "receipt.json"
        self.bootstrap.write_new_file(path, self.bootstrap.canonical_json(receipt))
        self.assertEqual(path.read_bytes(), b'{\n  "a": [\n    2\n  ],\n  "z": 1\n}\n')
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            self.bootstrap.write_new_file(path, b"replacement")
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
