#!/usr/bin/env python3
"""Compile and run explicitly allowlisted pure-C E87 host test suites."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = REPO_ROOT / "firmware" / "locks" / "sdk.lock.json"
DEFAULT_MANIFEST = "firmware/host/suites.json"
DEFAULT_BUILD_ROOT = "firmware/.host-build"
BUILD_ROOT_PATH = REPO_ROOT / DEFAULT_BUILD_ROOT
BUILD_ROOT = (REPO_ROOT / DEFAULT_BUILD_ROOT).resolve()
FIXED_FLAGS = [
    "-std=c11",
    "-O0",
    "-Wall",
    "-Wextra",
    "-Werror",
    "-pedantic",
    "-fno-common",
    "-DE87_HOST_TEST=1",
]
ALLOWED_INCLUDE_ROOTS = {
    "firmware/host",
    "firmware/overlay/SDK/apps/watch/include",
    "firmware/generated",
}
ALLOWED_SOURCE_ROOTS = (
    "firmware/overlay/SDK/apps/watch/e87/",
    "firmware/host/fakes/",
    "firmware/generated/",
)
PATH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
HEX_40_RE = re.compile(r"^[0-9a-f]{40}$")
HEX_64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
DRIVE_RE = re.compile(r"^[A-Za-z]:")
LOCAL_INCLUDE_RE = re.compile(r'^\s*#\s*include\s*"([^"]+)"')


class RunnerError(Exception):
    """A user-controlled input failed before compiler invocation."""


class DuplicateJsonKey(RunnerError):
    """A JSON object repeated a key."""


@dataclass(frozen=True)
class SuiteCase:
    suite: str
    name: str
    test: str
    sources: tuple[str, ...]


@dataclass(frozen=True)
class CompilerIdentity:
    requested: str
    resolved: Path
    sha256: str
    version: str
    dumpmachine: str
    linker: dict[str, str] | None


@dataclass(frozen=True)
class RunEvidence:
    executable: Path
    stdout: str
    stderr: str
    status: int
    receipt: dict[str, Any]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def canonical_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKey(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
        value = json.loads(raw, object_pairs_hook=reject_duplicate_keys)
    except DuplicateJsonKey as error:
        raise RunnerError(f"{label}: {error}") from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RunnerError(f"{label}: invalid UTF-8 JSON: {error}") from error
    if not isinstance(value, dict):
        raise RunnerError(f"{label}: root must be an object")
    return value


def expect_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    unknown = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    if unknown:
        raise RunnerError(f"{label}: unknown key: {unknown[0]}")
    if missing:
        raise RunnerError(f"{label}: missing key: {missing[0]}")


def validate_relative_spelling(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RunnerError(f"{label} path must be a nonempty string")
    if "\x00" in value:
        raise RunnerError(f"{label} path contains NUL")
    if DRIVE_RE.match(value) or value.startswith(("/", "\\")):
        raise RunnerError(f"{label} path must be repository-relative")
    if "\\" in value:
        raise RunnerError(f"{label} path uses a non-portable separator")
    components = value.split("/")
    if ".." in components:
        raise RunnerError(f"{label} path traversal is forbidden")
    if any(component in {"", "."} for component in components):
        raise RunnerError(f"{label} path has an empty or dot component")
    if value.startswith("@"):
        raise RunnerError(f"{label} path uses response-file syntax")
    if not PATH_RE.fullmatch(value):
        raise RunnerError(f"{label} path contains forbidden syntax")
    return value


def assert_no_symlink(path: Path, label: str) -> None:
    relative = path.relative_to(REPO_ROOT)
    cursor = REPO_ROOT
    for component in relative.parts:
        cursor = cursor / component
        if cursor.is_symlink():
            raise RunnerError(f"{label}: symlinked path is forbidden")


def existing_repo_path(value: Any, label: str, directory: bool) -> tuple[str, Path]:
    spelling = validate_relative_spelling(value, label)
    path = REPO_ROOT / spelling
    assert_no_symlink(path, label)
    try:
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, OSError) as error:
        raise RunnerError(f"{label}: missing path: {spelling}") from error
    if not resolved.is_relative_to(REPO_ROOT):
        raise RunnerError(f"{label}: resolved path escapes repository")
    if directory:
        if not resolved.is_dir():
            raise RunnerError(f"{label}: path is not a directory")
    elif not resolved.is_file() or not stat.S_ISREG(resolved.stat().st_mode):
        raise RunnerError(f"{label}: path is not a regular file")
    return spelling, resolved


def validate_sdk_lock() -> dict[str, Any]:
    assert_no_symlink(LOCK_PATH, "SDK lock")
    if not LOCK_PATH.is_file() or not stat.S_ISREG(LOCK_PATH.stat().st_mode):
        raise RunnerError("SDK lock: path is not a regular file")
    lock = load_json(LOCK_PATH, "SDK lock")
    expected = {
        "schemaVersion": 1,
        "sdk": {
            "kind": "git",
            "url": "https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200.git",
            "commit": "d0167685d032d745d88fe50233302edd46941622",
            "tree": "854734595be49510aca5afb89f5885e8bce6a00f",
            "submodules": [],
        },
        "target": {
            "chip": "AC707N",
            "family": "BR35",
            "architecture": "pi32v2",
            "cpu": "r3",
            "entryAddress": "0x0C000100",
        },
    }
    expect_keys(lock, set(expected), "SDK lock")
    sdk = lock.get("sdk")
    target = lock.get("target")
    if not isinstance(sdk, dict) or not isinstance(target, dict):
        raise RunnerError("SDK lock: sdk and target must be objects")
    expect_keys(sdk, set(expected["sdk"]), "SDK lock sdk")
    expect_keys(target, set(expected["target"]), "SDK lock target")
    if not isinstance(lock.get("schemaVersion"), int) or isinstance(
        lock.get("schemaVersion"), bool
    ):
        raise RunnerError("SDK lock: schemaVersion must be integer 1")
    if not isinstance(sdk.get("url"), str) or not sdk["url"].startswith("https://"):
        raise RunnerError("SDK lock: sdk URL must use HTTPS")
    if not isinstance(sdk.get("commit"), str) or not HEX_40_RE.fullmatch(sdk["commit"]):
        raise RunnerError("SDK lock: commit must be lowercase 40-hex")
    if not isinstance(sdk.get("tree"), str) or not HEX_40_RE.fullmatch(sdk["tree"]):
        raise RunnerError("SDK lock: tree must be lowercase 40-hex")
    if sdk.get("submodules") != []:
        raise RunnerError("SDK lock: submodules must be an empty list")
    if lock != expected:
        raise RunnerError("SDK lock: content does not match the canonical identity")
    return lock


def validate_test_path(value: Any, label: str) -> str:
    spelling = validate_relative_spelling(value, label)
    if not spelling.startswith("firmware/host/"):
        raise RunnerError(f"{label}: test path is outside the allowlist")
    path = Path(spelling)
    if path.suffix != ".c":
        raise RunnerError(f"{label}: test extension must be .c")
    if not path.name.startswith("test_"):
        raise RunnerError(f"{label}: test basename is outside the allowlist")
    existing_repo_path(spelling, label, directory=False)
    return spelling


def validate_source_path(value: Any, label: str) -> str:
    spelling = validate_relative_spelling(value, label)
    if Path(spelling).suffix != ".c":
        raise RunnerError(f"{label}: source extension must be .c")
    if not any(spelling.startswith(root) for root in ALLOWED_SOURCE_ROOTS):
        raise RunnerError(f"{label}: source path is outside the allowlist")
    existing_repo_path(spelling, label, directory=False)
    return spelling


def validate_manifest(path_value: str) -> tuple[str, Path, list[str], dict[str, list[SuiteCase]]]:
    manifest_spelling, manifest_path = existing_repo_path(
        path_value, "manifest", directory=False
    )
    if manifest_path.suffix != ".json":
        raise RunnerError("manifest: extension must be .json")
    manifest = load_json(manifest_path, "manifest")
    expect_keys(manifest, {"schemaVersion", "includeDirectories", "suites"}, "manifest")
    version = manifest["schemaVersion"]
    if not isinstance(version, int) or isinstance(version, bool) or version != 1:
        raise RunnerError("manifest: schemaVersion must be integer 1")
    includes_value = manifest["includeDirectories"]
    if not isinstance(includes_value, list):
        raise RunnerError("manifest: includeDirectories must be a list")
    includes: list[str] = []
    for index, include in enumerate(includes_value):
        spelling = validate_relative_spelling(include, f"manifest include[{index}]")
        if spelling not in ALLOWED_INCLUDE_ROOTS:
            raise RunnerError(f"manifest include[{index}]: path is outside the allowlist")
        if spelling in includes:
            raise RunnerError(f"manifest: duplicate include: {spelling}")
        existing_repo_path(spelling, f"manifest include[{index}]", directory=True)
        includes.append(spelling)
    suites_value = manifest["suites"]
    if not isinstance(suites_value, dict):
        raise RunnerError("manifest: suites must be an object")
    suites: dict[str, list[SuiteCase]] = {}
    used_tests: set[str] = set()
    for suite_name, cases_value in suites_value.items():
        if not isinstance(suite_name, str) or not suite_name:
            raise RunnerError("manifest: suite name must be nonempty")
        if not NAME_RE.fullmatch(suite_name):
            raise RunnerError("manifest: suite name contains unsafe path syntax")
        if suite_name == "all":
            raise RunnerError("manifest: declared suite name all is reserved")
        if not isinstance(cases_value, list) or not cases_value:
            raise RunnerError(f"manifest suite {suite_name}: cases must be a nonempty list")
        cases: list[SuiteCase] = []
        used_names: set[str] = set()
        for index, case_value in enumerate(cases_value):
            label = f"manifest suite {suite_name} case[{index}]"
            if not isinstance(case_value, dict):
                raise RunnerError(f"{label}: case must be an object")
            expect_keys(case_value, {"name", "test", "sources"}, label)
            name = case_value["name"]
            if not isinstance(name, str) or not name:
                raise RunnerError(f"{label}: case name must be nonempty")
            if not NAME_RE.fullmatch(name):
                raise RunnerError(f"{label}: case name contains unsafe path syntax")
            if name in used_names:
                raise RunnerError(f"{label}: duplicate case name: {name}")
            used_names.add(name)
            test = validate_test_path(case_value["test"], f"{label} test")
            if test in used_tests:
                raise RunnerError(f"{label}: duplicate test entry: {test}")
            used_tests.add(test)
            sources_value = case_value["sources"]
            if not isinstance(sources_value, list):
                raise RunnerError(f"{label}: sources must be a list")
            sources: list[str] = []
            for source_index, source_value in enumerate(sources_value):
                source = validate_source_path(
                    source_value, f"{label} source[{source_index}]"
                )
                if source in sources:
                    raise RunnerError(f"{label}: duplicate source entry: {source}")
                sources.append(source)
            cases.append(SuiteCase(suite_name, name, test, tuple(sources)))
        suites[suite_name] = cases
    return manifest_spelling, manifest_path, includes, suites


def select_cases(suite: str, suites: dict[str, list[SuiteCase]]) -> list[SuiteCase]:
    if suite == "all":
        return [case for name in sorted(suites) for case in suites[name]]
    if suite not in suites:
        raise RunnerError(f"unknown suite: {suite}")
    return list(suites[suite])


def child_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    environment["TZ"] = "UTC"
    return environment


def run_identity_command(arguments: list[str], label: str) -> str:
    try:
        result = subprocess.run(
            arguments,
            cwd=REPO_ROOT,
            env=child_environment(),
            check=False,
            shell=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise RunnerError(f"{label}: execution failed: {error}") from error
    if result.returncode != 0:
        raise RunnerError(f"{label}: command returned {result.returncode}")
    return normalize_text(result.stdout + result.stderr).rstrip("\n")


def resolve_executable(value: str, label: str) -> Path:
    if not value or "\x00" in value or "\n" in value or "\r" in value:
        raise RunnerError(f"{label}: invalid executable name")
    candidate = shutil.which(value)
    if candidate is None and ("/" in value or "\\" in value):
        path = Path(value).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            candidate = str(path)
    if candidate is None:
        raise RunnerError(f"{label}: executable not found: {value}")
    resolved = Path(candidate).resolve(strict=True)
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise RunnerError(f"{label}: path is not an executable regular file")
    return resolved


def identify_compiler(requested: str, required_sha256: str | None) -> CompilerIdentity:
    if required_sha256 is not None and not HEX_64_RE.fullmatch(required_sha256):
        raise RunnerError("required compiler SHA-256 must be exactly 64 hex characters")
    resolved = resolve_executable(requested, "compiler")
    digest = sha256_file(resolved)
    if required_sha256 is not None and digest != required_sha256.lower():
        raise RunnerError(
            f"compiler SHA-256 mismatch: required {required_sha256.lower()}, got {digest}"
        )
    version = run_identity_command([str(resolved), "--version"], "compiler version")
    dumpmachine = run_identity_command(
        [str(resolved), "-dumpmachine"], "compiler dumpmachine"
    )
    linker: dict[str, str] | None = None
    try:
        linker_name = run_identity_command(
            [str(resolved), "-print-prog-name=ld"], "compiler linker discovery"
        ).strip()
        linker_path = resolve_executable(linker_name, "linker")
        linker = {
            "resolvedPath": str(linker_path),
            "sha256": sha256_file(linker_path),
            "version": run_identity_command([str(linker_path), "--version"], "linker version"),
        }
    except RunnerError:
        linker = None
    return CompilerIdentity(requested, resolved, digest, version, dumpmachine, linker)


def validate_build_root(value: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        validate_relative_spelling(value, "build root")
        candidate = REPO_ROOT / candidate
    lexical = candidate.absolute()
    if not lexical.is_relative_to(BUILD_ROOT_PATH):
        raise RunnerError("build root must be beneath firmware/.host-build")
    cursor = REPO_ROOT
    for component in lexical.relative_to(REPO_ROOT).parts:
        cursor = cursor / component
        if cursor.is_symlink():
            raise RunnerError("build root must not contain symlinks")
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(BUILD_ROOT):
        raise RunnerError("build root must be beneath firmware/.host-build")
    if resolved.exists() and not resolved.is_dir():
        raise RunnerError("build root must be a directory")
    return resolved


def hash_record(spelling: str) -> dict[str, str]:
    return {"path": spelling, "sha256": sha256_file(REPO_ROOT / spelling)}


def scan_headers(source_spellings: Iterable[str], includes: list[str]) -> list[str]:
    include_paths = [REPO_ROOT / include for include in includes]
    allowed_paths = [path.resolve() for path in include_paths]
    result: list[str] = []
    seen: set[Path] = set()

    def visit(path: Path) -> None:
        for line in path.read_text(encoding="utf-8").splitlines():
            match = LOCAL_INCLUDE_RE.match(line)
            if match is None:
                continue
            name = match.group(1)
            candidates = [path.parent / name, *(root / name for root in include_paths)]
            header = next((item for item in candidates if item.is_file()), None)
            if header is None:
                raise RunnerError(f"compiled source references missing local header: {name}")
            assert_no_symlink(header, "compiled header")
            resolved = header.resolve(strict=True)
            if not any(resolved.is_relative_to(root) for root in allowed_paths):
                raise RunnerError(f"compiled header is outside include allowlist: {name}")
            if resolved in seen:
                continue
            seen.add(resolved)
            spelling = resolved.relative_to(REPO_ROOT).as_posix()
            result.append(spelling)
            visit(resolved)

    for spelling in source_spellings:
        visit(REPO_ROOT / spelling)
    return result


def normalize_argument(value: str, run_dir: Path) -> str:
    result = value.replace(str(run_dir), "BUILD")
    result = result.replace(str(REPO_ROOT), "REPO")
    return result


def build_case(
    case: SuiteCase,
    requested_cases: list[dict[str, str]],
    includes: list[str],
    manifest_spelling: str,
    manifest_path: Path,
    compiler: CompilerIdentity,
    run_dir: Path,
) -> RunEvidence | None:
    executable = run_dir / ("host-test.exe" if os.name == "nt" else "host-test")
    source_spellings = ["firmware/host/test_main.c", case.test, *case.sources]
    arguments = [str(compiler.resolved), *FIXED_FLAGS]
    for include in includes:
        arguments.extend(["-I", include])
    arguments.extend(source_spellings)
    arguments.extend(["-o", str(executable)])
    try:
        compile_result = subprocess.run(
            arguments,
            cwd=REPO_ROOT,
            env=child_environment(),
            check=False,
            shell=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        print(f"compiler invocation failed: {error}", file=sys.stderr)
        return None
    compile_stdout = normalize_text(compile_result.stdout)
    compile_stderr = normalize_text(compile_result.stderr)
    if compile_stdout:
        sys.stdout.write(compile_stdout)
    if compile_stderr:
        sys.stderr.write(compile_stderr)
    if compile_result.returncode != 0:
        print(
            f"compile failed for {case.suite}/{case.name}: exit {compile_result.returncode}",
            file=sys.stderr,
        )
        return None
    try:
        process = subprocess.run(
            [str(executable)],
            cwd=REPO_ROOT,
            env=child_environment(),
            check=False,
            shell=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        print(f"test executable failed to start: {error}", file=sys.stderr)
        return None
    stdout = normalize_text(process.stdout)
    stderr = normalize_text(process.stderr)
    sys.stdout.write(stdout)
    sys.stderr.write(stderr)
    try:
        headers = scan_headers(source_spellings, includes)
    except (OSError, UnicodeError, RunnerError) as error:
        print(f"receipt header scan failed: {error}", file=sys.stderr)
        return None
    receipt = {
        "case": {"name": case.name, "suite": case.suite},
        "compileArguments": [normalize_argument(item, run_dir) for item in arguments],
        "compiler": {
            "dumpmachine": compiler.dumpmachine,
            "requested": compiler.requested,
            "resolvedPath": str(compiler.resolved),
            "sha256": compiler.sha256,
            "version": compiler.version,
        },
        "executable": {"path": f"BUILD/{executable.name}", "sha256": sha256_file(executable)},
        "headers": [hash_record(path) for path in headers],
        "linker": compiler.linker,
        "manifest": {"path": manifest_spelling, "sha256": sha256_file(manifest_path)},
        "process": {
            "exitStatus": process.returncode,
            "stderrSha256": sha256_text(stderr),
            "stdoutSha256": sha256_text(stdout),
        },
        "python": {
            "executableSha256": sha256_file(Path(sys.executable).resolve(strict=True)),
            "version": platform.python_version(),
        },
        "requestedCases": requested_cases,
        "schemaVersion": 1,
        "sdkLock": {
            "path": "firmware/locks/sdk.lock.json",
            "sha256": sha256_file(LOCK_PATH),
        },
        "sources": [hash_record(path) for path in source_spellings],
    }
    (run_dir / "receipt.json").write_text(canonical_json(receipt), encoding="utf-8", newline="\n")
    return RunEvidence(executable, stdout, stderr, process.returncode, receipt)


def run_selected_cases(
    cases: list[SuiteCase],
    includes: list[str],
    manifest_spelling: str,
    manifest_path: Path,
    compiler: CompilerIdentity,
    build_root: Path,
    verify_reproducible: bool,
) -> int:
    requested = [{"suite": case.suite, "case": case.name} for case in cases]
    failed = False
    build_root.mkdir(parents=True, exist_ok=True)
    for case in cases:
        case_root = build_root / case.suite / case.name
        case_root.mkdir(parents=True, exist_ok=True)
        invocation = Path(tempfile.mkdtemp(prefix="invocation-", dir=case_root))
        first_dir = invocation / "run-1"
        first_dir.mkdir()
        first = build_case(
            case, requested, includes, manifest_spelling, manifest_path, compiler, first_dir
        )
        if first is None or first.status != 0:
            failed = True
            continue
        if verify_reproducible:
            second_dir = invocation / "run-2"
            second_dir.mkdir()
            second = build_case(
                case, requested, includes, manifest_spelling, manifest_path, compiler, second_dir
            )
            if second is None or second.status != 0:
                failed = True
                continue
            matches = (
                first.executable.read_bytes() == second.executable.read_bytes()
                and first.stdout == second.stdout
                and first.stderr == second.stderr
                and first.status == second.status
            )
            if not matches:
                print(f"reproducibility mismatch: {case.suite}/{case.name}", file=sys.stderr)
                failed = True
            else:
                print(f"REPRODUCIBLE {case.suite}/{case.name}")
    return 1 if failed else 0


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True)
    parser.add_argument("--cc")
    parser.add_argument("--require-compiler-sha256")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--build-root", default=DEFAULT_BUILD_ROOT)
    parser.add_argument("--verify-reproducible", action="store_true")
    parser.add_argument("--list", action="store_true", dest="list_suites")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        validate_sdk_lock()
        manifest_spelling, manifest_path, includes, suites = validate_manifest(
            arguments.manifest
        )
        cases = select_cases(arguments.suite, suites)
        if arguments.list_suites:
            for suite_name in sorted(suites):
                if all("/fixtures/" not in case.test for case in suites[suite_name]):
                    print(suite_name)
            return 0
        build_root = validate_build_root(arguments.build_root)
        requested_compiler = arguments.cc or os.environ.get("E87_HOST_CC") or "cc"
        compiler = identify_compiler(
            requested_compiler, arguments.require_compiler_sha256
        )
    except RunnerError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return run_selected_cases(
        cases,
        includes,
        manifest_spelling,
        manifest_path,
        compiler,
        build_root,
        arguments.verify_reproducible,
    )


if __name__ == "__main__":
    raise SystemExit(main())
