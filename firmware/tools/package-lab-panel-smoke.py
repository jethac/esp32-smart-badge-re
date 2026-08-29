#!/usr/bin/env python3
"""Build a separately qualified 11.1.0.4 Qix for the LAB_ONLY panel smoke."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import shutil
import stat
import subprocess
import sys
from typing import Any


LAB_QIX_VERSION = "11.1.0.4"
SOURCE_COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
HEX64_RE = re.compile(r"[0-9A-F]{64}\Z")
SECTION_OUTPUTS = (
    (".text", "text.bin", True),
    (".data", "data.bin", True),
    (".data_code", "data_code.bin", True),
    (".overlay_aec", "aec.bin", False),
    (".overlay_aac", "aac.bin", False),
    (".ps_ram_data_code", "psr_data_code.bin", False),
    (".dcache_ram_data", "d_ram_data.bin", False),
    (".icache_ram_data_code", "i_ram_data_code.bin", False),
)

SDK_COMMIT = "d0167685d032d745d88fe50233302edd46941622"
SDK_TREE = "854734595be49510aca5afb89f5885e8bce6a00f"
FULL_PATCH_RELATIVE = "firmware/patches/full/0001-e87-full-substrate.patch"
LAB_PATCH_RELATIVE = "firmware/patches/lab-panel-smoke/0001-e87-lab-panel-smoke.patch"
FULL_PATCH_TARGETS = (
    "SDK/apps/watch/app_main.c",
    "SDK/apps/watch/board/br35/board_config.h",
    "SDK/apps/watch/include/app_config.h",
    "SDK/build/Makefile.mk",
    "SDK/build/genFileList.c",
    "SDK/cpu/br35/power/power_app.c",
    "SDK/cpu/br35/sdk_ld.c",
    "SDK/interface/system/port/br35/system_lib.ld",
)
LAB_PATCH_TARGETS = (
    "SDK/apps/watch/app_main.c",
    "SDK/build/Makefile.mk",
    "SDK/cpu/br35/sdk_ld.c",
)
LAB_OVERLAY_RECORDS = (
    {
        "source": "firmware/overlay/SDK/apps/watch/board/br35/board_e87_1542_full/board_e87_1542_full.c",
        "destination": "SDK/apps/watch/board/br35/board_e87_1542_full/board_e87_1542_full.c",
    },
    {
        "source": "firmware/overlay/SDK/apps/watch/board/br35/board_e87_1542_full/board_e87_1542_full_cfg.h",
        "destination": "SDK/apps/watch/board/br35/board_e87_1542_full/board_e87_1542_full_cfg.h",
    },
    *(
        {
            "source": f"firmware/overlay/SDK/apps/watch/e87/{name}",
            "destination": f"SDK/apps/watch/e87/{name}",
        }
        for name in (
            "e87_app.c",
            "e87_full_platform_config.c",
            "e87_lab_smoke.c",
            "e87_lcd_stream.c",
            "e87_panel_jd9855.c",
            "e87_renderer.c",
            "e87_transient_renderer.c",
        )
    ),
    *(
        {
            "source": f"firmware/overlay/SDK/apps/watch/include/e87/{name}",
            "destination": f"SDK/apps/watch/include/e87/{name}",
        }
        for name in (
            "e87_app.h",
            "e87_button_fsm.h",
            "e87_lab_smoke.h",
            "e87_lcd_stream.h",
            "e87_panel.h",
            "e87_power_policy.h",
            "e87_renderer.h",
            "e87_state.h",
            "e87_transient_renderer.h",
            "e87_types.h",
            "e87_ui.h",
        )
    ),
    {
        "source": "firmware/generated/e87_assets.c",
        "destination": "SDK/apps/watch/e87/e87_assets.c",
    },
    {
        "source": "firmware/generated/e87_assets.h",
        "destination": "SDK/apps/watch/include/e87_assets.h",
    },
    {
        "source": "firmware/generated/e87_transient_assets.c",
        "destination": "SDK/apps/watch/e87/e87_transient_assets.c",
    },
    {
        "source": "firmware/generated/e87_transient_assets.h",
        "destination": "SDK/apps/watch/include/e87_transient_assets.h",
    },
)
SOURCE_CLONE_CONFIG = b"""[core]
\trepositoryformatversion = 0
\tfilemode = true
\tbare = false
\tlogallrefupdates = true
[user]
\temail = jethachan@gmail.com
\tname = Jetha Chan
[remote \"bootstrap\"]
\turl = /home/jethac/.cache/codex-transfer/factory-android-badges-e87.bundle
\tfetch = +refs/heads/*:refs/remotes/bootstrap/*
[remote \"origin\"]
\turl = https://github.com/jethac/factory-android-badges.git
\tfetch = +refs/heads/*:refs/remotes/origin/*
[branch \"codex/e87-local-rendering\"]
\tremote = bootstrap
\tmerge = refs/heads/codex/e87-local-rendering
"""
SDK_CLONE_CONFIG = b"""[core]
\trepositoryformatversion = 0
\tfilemode = true
\tbare = false
\tlogallrefupdates = true
[remote \"origin\"]
\turl = https://gitlab.zh-jieli.com/e_badge/e_badge_707_sdk_200.git
\tfetch = +refs/heads/main:refs/remotes/origin/main
[branch \"main\"]
\tremote = origin
\tmerge = refs/heads/main
"""
NATIVE_DISCONNECTED_EXIT = 245
NATIVE_DISCONNECTED_SUFFIX = b"Device Offline\n"


def _load_sibling(filename: str, module_name: str):
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


STAGE0_PACKAGE = _load_sibling("package-firmware.py", "e87_lab_reviewed_package_core")
QIX = _load_sibling("qix.py", "e87_lab_qix")
MAP_VALIDATOR = _load_sibling("validate-lab-panel-map.py", "e87_lab_panel_map")
BOOTSTRAP = _load_sibling("bootstrap-sdk.py", "e87_lab_bootstrap")
BUILD_TARGET = _load_sibling("build-target.py", "e87_lab_build_core")


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("ascii")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _regular(path: Path, label: str, *, allow_empty: bool = True) -> bytes:
    value = Path(path)
    mode = value.lstat().st_mode
    if not stat.S_ISREG(mode) or stat.S_ISLNK(mode):
        raise ValueError(f"{label} must be a regular non-symlink file")
    data = value.read_bytes()
    if not allow_empty and not data:
        raise ValueError(f"{label} is empty")
    return data


def _directory(path: Path, label: str, *, empty: bool = False) -> Path:
    value = Path(path)
    if not value.is_absolute() or value.is_symlink() or not value.is_dir():
        raise ValueError(f"{label} must be an absolute real directory")
    if empty and any(value.iterdir()):
        raise ValueError(f"{label} must be empty")
    return value


def _command_record(
    *,
    role: str,
    argv: list[str],
    cwd: Path,
    result: subprocess.CompletedProcess,
    tool_sha256: str,
) -> dict[str, Any]:
    stdout = result.stdout.encode() if isinstance(result.stdout, str) else result.stdout
    stderr = result.stderr.encode() if isinstance(result.stderr, str) else result.stderr
    if not isinstance(stdout, bytes) or not isinstance(stderr, bytes):
        raise ValueError("command streams must be bytes")
    return {
        "argv": list(argv),
        "cwd": str(cwd),
        "exitCode": result.returncode,
        "role": role,
        "stderrSha256": _sha(stderr),
        "stderrSize": len(stderr),
        "stdoutSha256": _sha(stdout),
        "stdoutSize": len(stdout),
        "toolSha256": tool_sha256,
    }


def _run_command(
    *,
    role: str,
    argv: list[str],
    cwd: Path,
    environment: dict[str, str],
    tool_sha256: str,
    expected_exit: int = 0,
    input_bytes: bytes | None = None,
) -> tuple[subprocess.CompletedProcess, dict[str, Any]]:
    options: dict[str, Any] = {
        "check": False,
        "cwd": cwd,
        "env": dict(environment),
        "shell": False,
        "stderr": subprocess.PIPE,
        "stdout": subprocess.PIPE,
    }
    if input_bytes is None:
        options["stdin"] = subprocess.DEVNULL
    else:
        options["input"] = input_bytes
    result = subprocess.run(list(argv), **options)
    if not isinstance(result, subprocess.CompletedProcess) or result.returncode != expected_exit:
        raise ValueError(f"command failed: {role}")
    record = _command_record(
        role=role,
        argv=argv,
        cwd=cwd,
        result=result,
        tool_sha256=tool_sha256,
    )
    return result, record


def verify_repository_identity(repository: Path, expected_commit: str) -> dict[str, Any]:
    """Bind a clean checkout, including untracked files, to its exact commit."""
    root = _directory(Path(repository), "source repository")
    if not isinstance(expected_commit, str) or SOURCE_COMMIT_RE.fullmatch(expected_commit) is None:
        raise ValueError("expected source commit is invalid")
    git_path = Path("/usr/bin/git")
    git_data = _regular(git_path, "Git", allow_empty=False)
    environment = dict(BOOTSTRAP.GIT_ENV)

    def git(*arguments: str) -> bytes:
        argv = [str(git_path), *BOOTSTRAP.GIT_CONFIG_PREFIX, "-C", str(root), *arguments]
        result = subprocess.run(
            argv,
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            shell=False,
        )
        if result.returncode != 0 or result.stderr:
            raise ValueError(f"source Git query failed: {arguments[0]}")
        return result.stdout

    head = git("rev-parse", "HEAD").decode("ascii").strip()
    tree = git("rev-parse", "HEAD^{tree}").decode("ascii").strip()
    if head != expected_commit:
        raise ValueError(f"source HEAD differs: got {head}, expected {expected_commit}")
    if re.fullmatch(r"[0-9a-f]{40}", tree) is None:
        raise ValueError("source tree identity is invalid")
    status = git("status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise ValueError("source repository must be clean, including untracked files")
    commit_object = git("cat-file", "commit", head)
    epoch = BOOTSTRAP._parse_commit(commit_object, head, tree)
    return {
        "cleanIncludingUntracked": True,
        "commit": head,
        "commitObjectSha256": _sha(commit_object),
        "gitToolSha256": _sha(git_data),
        "sourceDateEpoch": epoch,
        "tree": tree,
    }


def _fresh_source_intake(
    *,
    repository: Path,
    destination: Path,
    expected_commit: str,
    git_tool: dict[str, str],
) -> tuple[Path, dict[str, Any]]:
    caller = verify_repository_identity(repository, expected_commit)
    target = Path(destination)
    if not target.is_absolute() or target.exists() or target.is_symlink():
        raise ValueError("source intake destination must be a new absolute path")
    environment = dict(BOOTSTRAP.GIT_ENV)
    clone_argv = [
        git_tool["path"],
        *BOOTSTRAP.GIT_CONFIG_PREFIX,
        "clone",
        "--no-local",
        "--no-hardlinks",
        "--no-checkout",
        "--quiet",
        str(repository),
        str(target),
    ]
    _, clone_record = _run_command(
        role="source-clone",
        argv=clone_argv,
        cwd=target.parent,
        environment=environment,
        tool_sha256=git_tool["sha256"],
    )
    checkout_argv = [
        git_tool["path"],
        *BOOTSTRAP.GIT_CONFIG_PREFIX,
        "-C",
        str(target),
        "checkout",
        "--quiet",
        "--detach",
        expected_commit,
    ]
    _, checkout_record = _run_command(
        role="source-checkout",
        argv=checkout_argv,
        cwd=target,
        environment=environment,
        tool_sha256=git_tool["sha256"],
    )
    config_path = target / ".git/config"
    _regular(config_path, "cloned source Git config", allow_empty=False)
    config_path.unlink()
    STAGE0_PACKAGE._write_new(config_path, SOURCE_CLONE_CONFIG)
    materialized = verify_repository_identity(target, expected_commit)
    if caller["tree"] != materialized["tree"] or caller["commitObjectSha256"] != materialized["commitObjectSha256"]:
        raise ValueError("fresh source intake differs from caller repository")
    return target, {
        "caller": caller,
        "commands": [clone_record, checkout_record],
        "configSha256": _sha(SOURCE_CLONE_CONFIG),
        "materialized": materialized,
        "schema": "e87-lab-source-intake-v1",
    }


def _fresh_sdk_intake(
    *,
    sdk_repository: Path,
    destination: Path,
    git_tool: dict[str, str],
) -> tuple[Path, dict[str, Any]]:
    """Clone only the pinned SDK commit; never consume its ambient worktree."""
    source = _directory(sdk_repository, "SDK object repository")
    target = Path(destination)
    if not target.is_absolute() or target.exists() or target.is_symlink():
        raise ValueError("SDK intake destination must be a new absolute path")
    environment = dict(BOOTSTRAP.GIT_ENV)
    clone_argv = [
        git_tool["path"],
        *BOOTSTRAP.GIT_CONFIG_PREFIX,
        "clone",
        "--no-local",
        "--no-hardlinks",
        "--no-checkout",
        "--quiet",
        str(source),
        str(target),
    ]
    _, clone_record = _run_command(
        role="sdk-clone",
        argv=clone_argv,
        cwd=target.parent,
        environment=environment,
        tool_sha256=git_tool["sha256"],
    )
    checkout_argv = [
        git_tool["path"],
        *BOOTSTRAP.GIT_CONFIG_PREFIX,
        "-C",
        str(target),
        "checkout",
        "--quiet",
        "--detach",
        SDK_COMMIT,
    ]
    _, checkout_record = _run_command(
        role="sdk-checkout",
        argv=checkout_argv,
        cwd=target,
        environment=environment,
        tool_sha256=git_tool["sha256"],
    )
    config_path = target / ".git/config"
    _regular(config_path, "cloned SDK Git config", allow_empty=False)
    config_path.unlink()
    STAGE0_PACKAGE._write_new(config_path, SDK_CLONE_CONFIG)
    materialized = verify_repository_identity(target, SDK_COMMIT)
    if materialized["tree"] != SDK_TREE:
        raise ValueError("fresh SDK intake tree differs from the reviewed pin")
    return target, {
        "ambientWorktreeConsumed": False,
        "commands": [clone_record, checkout_record],
        "configSha256": _sha(SDK_CLONE_CONFIG),
        "materialized": materialized,
        "schema": "e87-lab-sdk-intake-v1",
    }


def _decode_json(raw: bytes, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has a duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=reject_duplicates)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is invalid JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _tree_file_snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    base = Path(root)
    result: dict[str, tuple[int, int, str]] = {}
    for path in sorted(base.rglob("*"), key=lambda item: item.relative_to(base).as_posix()):
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError("materialized SDK contains a symlink")
        if stat.S_ISREG(mode):
            data = path.read_bytes()
            result[path.relative_to(base).as_posix()] = (
                stat.S_IMODE(mode),
                len(data),
                _sha(data),
            )
        elif not stat.S_ISDIR(mode):
            raise ValueError("materialized SDK contains a special file")
    return result


def _apply_lab_delta(
    *,
    generated_sdk_root: Path,
    patch_path: Path,
    git_tool: dict[str, str],
) -> dict[str, Any]:
    generated = _directory(generated_sdk_root, "generated SDK root")
    patch_data = _regular(patch_path, "LAB delta patch", allow_empty=False)
    paths = BOOTSTRAP._patch_paths(patch_data)
    if paths != set(LAB_PATCH_TARGETS):
        raise ValueError("LAB delta patch path allowlist differs")
    before_tree = BOOTSTRAP.tree_sha256(generated)
    before = _tree_file_snapshot(generated)
    boundary = BOOTSTRAP._create_apply_boundary(generated)
    environment = dict(BOOTSTRAP.GIT_ENV)
    environment["GIT_CEILING_DIRECTORIES"] = str(generated)
    commands: list[dict[str, Any]] = []
    prefix = [git_tool["path"], *BOOTSTRAP.GIT_CONFIG_PREFIX, "apply", "--no-index"]
    try:
        for role, suffix in (("lab-patch-check", ["--check", "-"]), ("lab-patch-apply", ["-"])):
            result, record = _run_command(
                role=role,
                argv=[*prefix, *suffix],
                cwd=generated,
                environment=environment,
                tool_sha256=git_tool["sha256"],
                input_bytes=patch_data,
            )
            if result.stdout or result.stderr:
                raise ValueError(f"{role} emitted output")
            record["stdin"] = {"sha256": _sha(patch_data), "size": len(patch_data)}
            commands.append(record)
    finally:
        shutil.rmtree(boundary)
    for relative in LAB_PATCH_TARGETS:
        os.chmod(generated / relative, before[relative][0])
    after = _tree_file_snapshot(generated)
    if set(after) != set(before):
        raise ValueError("LAB delta changed the generated SDK inventory")
    changed = {
        relative
        for relative in before
        if before[relative] != after[relative]
    }
    if changed != set(LAB_PATCH_TARGETS):
        raise ValueError("LAB delta changed files outside its exact allowlist")
    for relative in before:
        if before[relative][0] != after[relative][0]:
            raise ValueError("LAB delta changed a file mode")
    after_tree = BOOTSTRAP.tree_sha256(generated)
    return {
        "commands": commands,
        "inputTreeSha256": before_tree,
        "outputTreeSha256": after_tree,
        "patch": {
            "paths": sorted(paths),
            "sha256": _sha(patch_data),
            "size": len(patch_data),
        },
        "schema": "e87-lab-delta-receipt-v1",
        "targets": [
            {
                "afterSha256": after[relative][2],
                "beforeSha256": before[relative][2],
                "path": relative,
                "size": after[relative][1],
            }
            for relative in sorted(paths)
        ],
    }


def load_lab_lock(path: Path, base_lock_path: Path) -> dict[str, Any]:
    raw = _regular(path, "LAB packaging lock", allow_empty=False)
    value = _decode_json(raw, "LAB packaging lock")
    expected_keys = {
        "basePackagingLock",
        "delivery",
        "eligibility",
        "profileId",
        "qix",
        "schema",
        "stagingOverrides",
    }
    if set(value) != expected_keys or value.get("schema") != "e87-lab-panel-smoke-packaging-lock-v1" or value.get("profileId") != "E87-1542-LAB-PANEL-SMOKE-H":
        raise ValueError("LAB packaging lock projection differs")
    base = value.get("basePackagingLock")
    if not isinstance(base, dict) or set(base) != {"filename", "sha256"} or base.get("filename") != "packaging.lock.json":
        raise ValueError("LAB base packaging lock reference differs")
    base_raw = _regular(base_lock_path, "base packaging lock", allow_empty=False)
    if base.get("sha256") != _sha(base_raw):
        raise ValueError("base packaging lock digest differs")
    base_value = _decode_json(base_raw, "base packaging lock")
    base_qix = base_value.get("qix")
    qix = value.get("qix")
    if not isinstance(base_qix, dict) or not isinstance(qix, dict):
        raise ValueError("Qix lock projection is absent")
    expected_qix = dict(base_qix)
    expected_qix["version"] = LAB_QIX_VERSION
    if qix != expected_qix:
        raise ValueError("LAB Qix contract differs from base except version")
    if value.get("eligibility") != {"labEligible": True, "status": "LAB_ONLY"}:
        raise ValueError("LAB eligibility projection differs")
    overrides = value.get("stagingOverrides")
    expected_override_keys = {
        "baseSha256",
        "generatedSdkRelativePath",
        "sha256",
    }
    if not isinstance(overrides, dict) or set(overrides) != {"flash_params_v3.bin"}:
        raise ValueError("LAB staging override projection differs")
    override = overrides["flash_params_v3.bin"]
    if (
        not isinstance(override, dict)
        or set(override) != expected_override_keys
        or override.get("generatedSdkRelativePath")
        != "SDK/cpu/br35/tools/flash_params_v3.bin"
        or any(
            not isinstance(override.get(key), str)
            or HEX64_RE.fullmatch(override[key]) is None
            for key in ("baseSha256", "sha256")
        )
    ):
        raise ValueError("LAB flash parameter override differs")
    if value.get("delivery") != [
        "app.bin",
        "jl_isd.fw",
        "update.ufw",
        "qix",
        "manifest.json",
        "SHA256SUMS",
    ]:
        raise ValueError("LAB delivery allowlist differs")
    return value


def qix_name(source_commit: str) -> str:
    if not isinstance(source_commit, str) or SOURCE_COMMIT_RE.fullmatch(source_commit) is None:
        raise ValueError("source commit must be lowercase 40-hex")
    return f"E87-{LAB_QIX_VERSION}-{source_commit[:8].upper()}.qix"


def assemble_app(section_root: Path, output_path: Path) -> dict[str, Any]:
    root = _directory(section_root, "section root")
    output = Path(output_path)
    if not output.is_absolute() or output.exists() or output.is_symlink():
        raise ValueError("app output must be a new absolute path")
    chunks = []
    records = []
    for section, filename, required in SECTION_OUTPUTS:
        data = _regular(root / filename, f"section output {filename}")
        if required and not data:
            raise ValueError(f"required section is empty: {section}")
        chunks.append(data)
        records.append(
            {
                "filename": filename,
                "requiredNonempty": required,
                "section": section,
                "sha256": _sha(data),
                "size": len(data),
            }
        )
    app = b"".join(chunks)
    if not app:
        raise ValueError("assembled app is empty")
    STAGE0_PACKAGE._write_new(output, app)
    return {
        "filename": "app.bin",
        "sections": records,
        "sha256": _sha(app),
        "size": len(app),
    }


def _extract_sections(
    *,
    elf_path: Path,
    build_root: Path,
    objcopy: Path,
    environment: dict[str, str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    elf = Path(elf_path)
    commands = []
    for section, filename, _ in SECTION_OUTPUTS:
        output = build_root / filename
        argv = [str(objcopy), "-O", "binary", "-j", section, str(elf), str(output)]
        result = subprocess.run(
            argv,
            cwd=build_root,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            shell=False,
        )
        if result.returncode != 0 or output.is_symlink() or not output.is_file():
            raise ValueError(f"objcopy failed for {section}")
        commands.append(
            {
                "argv": argv,
                "exitCode": result.returncode,
                "role": f"objcopy:{section}",
                "stderrSha256": _sha(result.stderr),
                "stderrSize": len(result.stderr),
                "stdoutSha256": _sha(result.stdout),
                "stdoutSize": len(result.stdout),
                "toolSha256": _sha(_regular(objcopy, "objcopy", allow_empty=False)),
            }
        )
    return assemble_app(build_root, build_root / "app.bin"), commands


def _build_lab_target(
    *,
    generated_sdk_root: Path,
    control_root: Path,
    evidence_root: Path,
    source_date_epoch: int,
    toolchain_lock: dict[str, Any],
    toolchain_lock_sha256: str,
    bootstrap_receipt: dict[str, Any],
    lab_delta_receipt: dict[str, Any],
    toolchain_root: Path,
) -> tuple[dict[str, Any], dict[str, str], dict[str, dict[str, Any]]]:
    generated = _directory(generated_sdk_root, "generated SDK root")
    control = _directory(control_root, "build control root", empty=True)
    evidence = _directory(evidence_root, "evidence root")
    if Path(toolchain_root) != BUILD_TARGET.TOOLCHAIN_ROOT:
        raise ValueError("LAB build requires the reviewed toolchain root")
    if BOOTSTRAP.tree_sha256(generated) != lab_delta_receipt["outputTreeSha256"]:
        raise ValueError("generated SDK changed before the LAB build")

    make_tool = toolchain_lock.get("hostTools", {}).get("make")
    if not isinstance(make_tool, dict):
        raise ValueError("make tool pin is absent")
    tools = BUILD_TARGET.resolve_pinned_tools(toolchain_lock, make_tool=make_tool)
    runtime = BUILD_TARGET.resolve_lto_runtime(toolchain_lock, tool_root=toolchain_root)
    runtime_snapshot = BUILD_TARGET.snapshot_lto_runtime(runtime=runtime)
    environment = BUILD_TARGET.build_environment(
        control,
        source_date_epoch=source_date_epoch,
        tool_root=toolchain_root,
    )
    resource_limits = BUILD_TARGET.ensure_nofile_limit(
        resource_id=resource.RLIMIT_NOFILE,
        getrlimit=resource.getrlimit,
        setrlimit=resource.setrlimit,
    )
    version_tools = {
        name: tools[name]
        for name in ("make", "objcopy", "objdump", "nm")
    }
    version_probes = BUILD_TARGET.probe_tool_versions(
        version_tools,
        cwd=control,
        environment=environment,
    )
    argv = BUILD_TARGET.make_command(
        generated,
        toolchain_root / "pi32v2/bin",
        jobs=6,
    )
    try:
        verbose_index = argv.index("VERBOSE=0")
    except ValueError as error:
        raise ValueError("reviewed make command lost its verbosity control") from error
    argv[verbose_index] = "VERBOSE=1"
    result = subprocess.run(
        argv,
        cwd=generated,
        env=dict(environment),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
    )
    if result.returncode != 0:
        raise ValueError("LAB target build failed")
    combined = result.stdout + b"\n" + result.stderr
    if re.search(rb"(?:password|username|connect usb|select a device)", combined, re.I):
        raise ValueError("LAB build emitted interactive output")
    try:
        lines = combined.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ValueError("LAB build output is not UTF-8") from error
    link_lines = [
        line
        for line in lines
        if "sdk.elf" in line and "/pi32v2/bin/lto-wrapper" in line
    ]
    if len(link_lines) != 1:
        raise ValueError("LAB build did not expose one exact linker command")
    STAGE0_PACKAGE._write_new(evidence / "build.stdout", result.stdout)
    STAGE0_PACKAGE._write_new(evidence / "build.stderr", result.stderr)
    BUILD_TARGET.reverify_lto_runtime(runtime=runtime, snapshot=runtime_snapshot)
    confirmed_tools = BUILD_TARGET.resolve_pinned_tools(
        toolchain_lock,
        make_tool=make_tool,
    )
    if confirmed_tools != tools:
        raise ValueError("build tool identities changed during use")
    for record in bootstrap_receipt["overlay"]:
        data = _regular(
            generated / record["destination"],
            f"generated overlay {record['destination']}",
            allow_empty=False,
        )
        if len(data) != record["size"] or _sha(data) != record["sha256"]:
            raise ValueError("generated overlay changed during build")
    for record in lab_delta_receipt["targets"]:
        data = _regular(
            generated / record["path"],
            f"LAB patch target {record['path']}",
            allow_empty=False,
        )
        if len(data) != record["size"] or _sha(data) != record["afterSha256"]:
            raise ValueError("LAB patch target changed during build")
    outputs = {}
    for name, relative in (
        ("elf", "SDK/cpu/br35/tools/sdk.elf"),
        ("map", "SDK/cpu/br35/tools/sdk.map"),
        ("objectList", "SDK/cpu/br35/tools/sdk.elf.objs.txt"),
        ("resolution", "SDK/cpu/br35/tools/sdk.elf.resolution.txt"),
    ):
        data = _regular(generated / relative, f"LAB build {name}", allow_empty=False)
        outputs[name] = {
            "relativePath": relative,
            "sha256": _sha(data),
            "size": len(data),
        }
    command = _command_record(
        role="make",
        argv=argv,
        cwd=generated,
        result=result,
        tool_sha256=tools["make"]["sha256"],
    )
    command["environment"] = {
        **environment,
        "HOME": "$BUILD_CONTROL_ROOT/home",
        "TMPDIR": "$BUILD_CONTROL_ROOT/tmp",
    }
    command["linkCommand"] = link_lines[0]
    command["linkCommandSha256"] = _sha(link_lines[0].encode("utf-8"))
    command["stderrEvidence"] = "build.stderr"
    command["stdoutEvidence"] = "build.stdout"
    receipt = {
        "bootstrapOutputTreeSha256": bootstrap_receipt["outputTreeSha256"],
        "command": command,
        "inputTreeSha256": lab_delta_receipt["outputTreeSha256"],
        "outputs": outputs,
        "resourceLimits": resource_limits,
        "runtime": runtime,
        "schema": "e87-lab-target-build-receipt-v1",
        "sourceDateEpoch": source_date_epoch,
        "toolchainLockSha256": toolchain_lock_sha256,
        "verifiedTools": confirmed_tools,
        "versionProbes": version_probes,
    }
    return receipt, environment, tools


def _record(path: Path, role: str) -> dict[str, Any]:
    data = _regular(path, role, allow_empty=False)
    return {"filename": path.name, "role": role, "sha256": _sha(data), "size": len(data)}


def _apply_staging_override(
    *,
    staged: dict[str, Any],
    staging_root: Path,
    generated_sdk_root: Path,
    lab_lock: dict[str, Any],
) -> dict[str, Any]:
    filename = "flash_params_v3.bin"
    override = lab_lock["stagingOverrides"][filename]
    target = staging_root / filename
    original = _regular(target, "base flash parameters", allow_empty=False)
    if _sha(original) != override["baseSha256"]:
        raise ValueError("base flash parameter input differs")
    replacement_path = generated_sdk_root / override["generatedSdkRelativePath"]
    replacement = _regular(replacement_path, "generated SDK flash parameters", allow_empty=False)
    if _sha(replacement) != override["sha256"]:
        raise ValueError("generated SDK flash parameter identity differs")
    target.unlink()
    STAGE0_PACKAGE._write_new(target, replacement)
    records = staged.get("inputs")
    if not isinstance(records, list):
        raise ValueError("staged input projection is absent")
    matches = [record for record in records if record.get("filename") == filename]
    if len(matches) != 1 or matches[0].get("sha256") != override["baseSha256"]:
        raise ValueError("base flash parameter receipt differs")
    matches[0]["sha256"] = override["sha256"]
    matches[0]["size"] = len(replacement)
    return {
        "afterSha256": override["sha256"],
        "beforeSha256": override["baseSha256"],
        "filename": filename,
        "source": override["generatedSdkRelativePath"],
    }


def _native_command_record(
    *,
    role: str,
    argv: list[str],
    result: subprocess.CompletedProcess,
    tool: dict[str, Any],
    terminal_status: str,
) -> dict[str, Any]:
    stdout = result.stdout.encode() if isinstance(result.stdout, str) else result.stdout
    stderr = result.stderr.encode() if isinstance(result.stderr, str) else result.stderr
    if not isinstance(stdout, bytes) or not isinstance(stderr, bytes):
        raise ValueError("native command streams must be bytes")
    return {
        "argv": list(argv),
        "exitCode": result.returncode,
        "role": role,
        "stderrHex": stderr.hex().upper(),
        "stderrSha256": _sha(stderr),
        "stderrSize": len(stderr),
        "stdoutHex": stdout.hex().upper(),
        "stdoutSha256": _sha(stdout),
        "stdoutSize": len(stdout),
        "terminalStatus": terminal_status,
        "toolSha256": tool["sha256"],
        "toolVersion": tool.get("version"),
    }


def run_lab_native_packagers(
    staging_root: Path,
    tools: dict[str, dict[str, Any]],
    *,
    expected_inputs: list[dict[str, Any]],
    control_root: Path,
    environment: dict[str, str],
    post_root: Path,
) -> tuple[dict[str, Path], list[dict[str, Any]]]:
    """Accept only the reviewed LAB disconnected-after-output terminal state."""
    staging = _directory(staging_root, "native staging root")
    if set(tools) != {"fwAdd", "isdDownload", "ufwMaker"}:
        raise ValueError("native package tool projection is not closed")
    STAGE0_PACKAGE.validate_package_environment(
        environment,
        control_root,
        source_date_epoch=int(environment["SOURCE_DATE_EPOCH"]),
        post_root=post_root,
    )
    expected = {}
    for record in expected_inputs:
        if not isinstance(record, dict) or set(record) != {"filename", "role", "sha256", "size"}:
            raise ValueError("invalid native staging input receipt")
        expected[record["filename"]] = (record["size"], record["sha256"])
    if set(expected) != STAGE0_PACKAGE.STAGING_NAMES or expected != STAGE0_PACKAGE._snapshot(staging):
        raise ValueError("native staging differs from its closed receipt")
    before = STAGE0_PACKAGE._snapshot(staging)
    before_tokens = {
        name: STAGE0_PACKAGE._path_token(staging / name)
        for name in before
    }
    isd_tool = tools["isdDownload"]
    isd_path = Path(str(isd_tool["path"]))
    if _sha(_regular(isd_path, "isd_download", allow_empty=False)) != isd_tool["sha256"]:
        raise ValueError("isd_download identity changed")
    isd_argv = STAGE0_PACKAGE.isd_command(isd_path)
    isd_result = subprocess.run(
        isd_argv,
        cwd=staging,
        env=dict(environment),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
    )
    if (
        isd_result.returncode != NATIVE_DISCONNECTED_EXIT
        or isd_result.stderr != b""
        or not isd_result.stdout.endswith(NATIVE_DISCONNECTED_SUFFIX)
        or isd_result.stdout.count(NATIVE_DISCONNECTED_SUFFIX) != 1
    ):
        raise ValueError("isd_download did not end in the exact LAB disconnected state")
    preceding = isd_result.stdout[: -len(NATIVE_DISCONNECTED_SUFFIX)]
    if STAGE0_PACKAGE.PROMPT_PATTERN.search(preceding):
        raise ValueError("isd_download emitted an interactive prompt before disconnect")
    after_isd = STAGE0_PACKAGE._snapshot(staging)
    STAGE0_PACKAGE._check_transition(
        before,
        after_isd,
        {"jl_isd.bin", "jl_isd.fw", "update.ufw"},
    )
    for name, token in before_tokens.items():
        if STAGE0_PACKAGE._path_token(staging / name) != token:
            raise ValueError("isd_download changed an existing input identity")
    commands = [
        _native_command_record(
            role="isdDownload",
            argv=isd_argv,
            result=isd_result,
            tool=isd_tool,
            terminal_status="DISCONNECTED_AFTER_ALL_OUTPUTS",
        )
    ]

    after_isd_tokens = {
        name: STAGE0_PACKAGE._path_token(staging / name)
        for name in after_isd
    }
    ufw_tool = tools["ufwMaker"]
    ufw_path = Path(str(ufw_tool["path"]))
    if _sha(_regular(ufw_path, "ufw_maker", allow_empty=False)) != ufw_tool["sha256"]:
        raise ValueError("ufw_maker identity changed")
    ufw_argv = STAGE0_PACKAGE.ufw_maker_command(ufw_path)
    ufw_result = STAGE0_PACKAGE._invoke(
        subprocess.run,
        ufw_argv,
        staging,
        environment,
    )
    after_ufw = STAGE0_PACKAGE._snapshot(staging)
    STAGE0_PACKAGE._check_transition(after_isd, after_ufw, {"independently-made.ufw"})
    for name, token in after_isd_tokens.items():
        if STAGE0_PACKAGE._path_token(staging / name) != token:
            raise ValueError("ufw_maker changed an existing input identity")
    commands.append(
        _native_command_record(
            role="ufwMaker",
            argv=ufw_argv,
            result=ufw_result,
            tool=ufw_tool,
            terminal_status="SUCCESS",
        )
    )
    comparison = STAGE0_PACKAGE.compare_ufw_or_raise(
        staging / "update.ufw",
        staging / "independently-made.ufw",
    )
    outputs = {
        name: staging / name
        for name in (
            "independently-made.ufw",
            "jl_isd.bin",
            "jl_isd.fw",
            "update.ufw",
        )
    }
    commands.append(
        {
            "role": "independentUfwComparison",
            "relation": "BYTE_IDENTICAL",
            **comparison,
        }
    )
    return outputs, commands


def _write_delivery_metadata(delivery: Path, manifest: dict[str, Any]) -> None:
    STAGE0_PACKAGE._write_new(delivery / "manifest.json", _canonical(manifest))
    names = sorted(path.name for path in delivery.iterdir() if path.is_file())
    if names != sorted(["app.bin", "jl_isd.fw", "manifest.json", "update.ufw", manifest["qix"]["filename"]]):
        raise ValueError("delivery projection differs before checksums")
    lines = []
    for name in names:
        lines.append(f"{_sha(_regular(delivery / name, name, allow_empty=False))}  {name}\n")
    STAGE0_PACKAGE._write_new(delivery / "SHA256SUMS", "".join(lines).encode("ascii"))


def run_lab_package(
    *,
    reference_root: Path,
    run_root: Path,
    expected_source_commit: str,
    repository_root: Path | None = None,
    sdk_root: Path = Path("/home/jethac/.local/share/e87-dev/sdk/e_badge_707_sdk_200"),
    toolchain_root: Path = Path("/home/jethac/.local/share/e87-dev/jieli"),
    post_root: Path = Path("/home/jethac/.local/share/e87-dev/jieli-post-build"),
) -> dict[str, Any]:
    if SOURCE_COMMIT_RE.fullmatch(expected_source_commit) is None:
        raise ValueError("expected source commit must be lowercase 40-hex")
    repository = _directory(
        Path(__file__).resolve().parents[2]
        if repository_root is None
        else Path(repository_root),
        "repository root",
    )
    reference = _directory(reference_root, "reference root")
    run = _directory(run_root, "run root", empty=True)
    sdk_repository = _directory(sdk_root, "SDK object repository")
    tools_root = _directory(toolchain_root, "toolchain root")
    post = _directory(post_root, "post-build root")
    protected = [
        path.resolve(strict=True)
        for path in (repository, reference, sdk_repository, tools_root, post)
    ]
    resolved_run = run.resolve(strict=True)
    for path in protected:
        try:
            resolved_run.relative_to(path)
            overlaps = True
        except ValueError:
            try:
                path.relative_to(resolved_run)
                overlaps = True
            except ValueError:
                overlaps = False
        if overlaps:
            raise ValueError("run root must be disjoint from all protected inputs")
    roots = {
        name: run / name
        for name in (
            "build",
            "build-control",
            "delivery",
            "evidence",
            "generated-sdk",
            "package-control",
            "staging",
        )
    }
    for path in roots.values():
        path.mkdir(mode=0o700)

    lock_root = repository / "firmware/locks"
    lab_lock_path = repository / "firmware/lab-locks/panel-smoke-packaging.lock.json"
    base_lock_path = lock_root / "packaging.lock.json"
    load_lab_lock(lab_lock_path, base_lock_path)
    lock_values, lock_hashes, _ = STAGE0_PACKAGE._load_locks(lock_root)
    toolchain_lock = lock_values["toolchain.lock.json"]
    git_tool = toolchain_lock["hostTools"]["git"]
    source_clone, source_intake = _fresh_source_intake(
        repository=repository,
        destination=run / "source-intake",
        expected_commit=expected_source_commit,
        git_tool=git_tool,
    )
    sdk, sdk_intake = _fresh_sdk_intake(
        sdk_repository=sdk_repository,
        destination=run / "sdk-intake",
        git_tool=git_tool,
    )
    clone_lock_root = source_clone / "firmware/locks"
    clone_lab_lock_path = source_clone / "firmware/lab-locks/panel-smoke-packaging.lock.json"
    clone_base_lock_path = clone_lock_root / "packaging.lock.json"
    lab_lock = load_lab_lock(clone_lab_lock_path, clone_base_lock_path)
    clone_lock_values, clone_lock_hashes, _ = STAGE0_PACKAGE._load_locks(clone_lock_root)
    if clone_lock_values != lock_values or clone_lock_hashes != lock_hashes:
        raise ValueError("fresh source lock projection differs")
    profile_path = source_clone / "firmware/board-profiles/E87-1542-LAB-PANEL-SMOKE-H.json"

    bootstrap_receipt = BOOTSTRAP.bootstrap_sdk(
        repository_root=source_clone,
        sdk_root=sdk,
        output_root=roots["generated-sdk"],
        expected_source_commit=expected_source_commit,
        expected_source_tree=source_intake["materialized"]["tree"],
        expected_sdk_commit=SDK_COMMIT,
        expected_sdk_tree=SDK_TREE,
        overlay_records=[dict(record) for record in LAB_OVERLAY_RECORDS],
        patch_path=source_clone / FULL_PATCH_RELATIVE,
        allowed_patch_paths=FULL_PATCH_TARGETS,
        git_tool=git_tool,
    )
    lab_delta_receipt = _apply_lab_delta(
        generated_sdk_root=roots["generated-sdk"],
        patch_path=source_clone / LAB_PATCH_RELATIVE,
        git_tool=git_tool,
    )
    source_date_epoch = int(bootstrap_receipt["sourceCommitEpoch"])
    build_receipt, build_environment, build_tools = _build_lab_target(
        generated_sdk_root=roots["generated-sdk"],
        control_root=roots["build-control"],
        evidence_root=roots["evidence"],
        source_date_epoch=source_date_epoch,
        toolchain_lock=clone_lock_values["toolchain.lock.json"],
        toolchain_lock_sha256=clone_lock_hashes["toolchain.lock.json"],
        bootstrap_receipt=bootstrap_receipt,
        lab_delta_receipt=lab_delta_receipt,
        toolchain_root=tools_root,
    )
    package_tools = STAGE0_PACKAGE.resolve_locked_package_tools(
        clone_lock_values["packaging.lock.json"], post_root=post
    )

    generated = roots["generated-sdk"]
    elf = generated / "SDK/cpu/br35/tools/sdk.elf"
    map_path = generated / "SDK/cpu/br35/tools/sdk.map"
    object_list = generated / "SDK/cpu/br35/tools/sdk.elf.objs.txt"
    resolution = generated / "SDK/cpu/br35/tools/sdk.elf.resolution.txt"
    qualification = MAP_VALIDATOR.validate_artifacts(
        map_path=map_path,
        elf_path=elf,
        object_list_path=object_list,
        resolution_path=resolution,
        profile_path=profile_path,
        sdk_root=generated / "SDK",
        repository_root=source_clone,
    )

    objcopy = Path(str(build_tools["objcopy"]["path"]))
    app, extract_commands = _extract_sections(
        elf_path=elf,
        build_root=roots["build"],
        objcopy=objcopy,
        environment=build_environment,
    )

    staged = STAGE0_PACKAGE.stage_inputs(
        reference,
        sdk,
        roots["build"] / "app.bin",
        roots["staging"],
        clone_lock_values["model1552-package.lock.json"],
        build_receipt={"app": {key: app[key] for key in ("filename", "sha256", "size")}},
    )
    staging_override = _apply_staging_override(
        staged=staged,
        staging_root=roots["staging"],
        generated_sdk_root=generated,
        lab_lock=lab_lock,
    )
    package_environment = STAGE0_PACKAGE.package_environment(
        roots["package-control"], source_date_epoch=source_date_epoch, post_root=post
    )
    native, native_commands = run_lab_native_packagers(
        roots["staging"],
        package_tools,
        expected_inputs=staged["inputs"],
        control_root=roots["package-control"],
        environment=package_environment,
        post_root=post,
    )
    name = qix_name(expected_source_commit)
    qix_data = QIX.wrap_qix(_regular(native["update.ufw"], "update UFW", allow_empty=False), LAB_QIX_VERSION)
    STAGE0_PACKAGE._write_new(roots["staging"] / name, qix_data)
    proof_data = {
        "app.bin": _regular(roots["build"] / "app.bin", "app", allow_empty=False),
        "jl_isd.bin": _regular(native["jl_isd.bin"], "JL ISD binary", allow_empty=False),
        "jl_isd.fw": _regular(native["jl_isd.fw"], "JL ISD firmware", allow_empty=False),
        "update.ufw": _regular(native["update.ufw"], "update UFW", allow_empty=False),
        "independently-made.ufw": _regular(native["independently-made.ufw"], "independent UFW", allow_empty=False),
        name: qix_data,
    }
    proofs = STAGE0_PACKAGE._derive_package_proofs(
        proof_data,
        app_record={key: app[key] for key in ("filename", "sha256", "size")},
        expected_source_commit=expected_source_commit,
        staged_ini_sha256=next(item["sha256"] for item in staged["inputs"] if item["filename"] == "isd_config.ini"),
        qix_name=name,
        qix_version=LAB_QIX_VERSION,
    )

    delivery_sources = {
        "app.bin": roots["build"] / "app.bin",
        "jl_isd.fw": native["jl_isd.fw"],
        "update.ufw": native["update.ufw"],
        name: roots["staging"] / name,
    }
    for filename, source in delivery_sources.items():
        STAGE0_PACKAGE._write_new(roots["delivery"] / filename, _regular(source, filename, allow_empty=False))
    artifact_records = [
        _record(roots["delivery"] / filename, role)
        for filename, role in (
            ("app.bin", "LAB_APP"),
            ("jl_isd.fw", "FULL_FLASH_CONTAINER"),
            ("update.ufw", "OTA_UFW"),
            (name, "OTA_QIX"),
        )
    ]
    manifest = {
        "artifacts": artifact_records,
        "labEligible": True,
        "profileId": lab_lock["profileId"],
        "qix": {
            "filename": name,
            "payloadSha256": proofs["qix"]["payloadSha256"],
            "sha256": _sha(qix_data),
            "version": LAB_QIX_VERSION,
        },
        "qualification": {
            **qualification,
            "elfSha256": _sha(_regular(elf, "ELF", allow_empty=False)),
            "mapSha256": _sha(_regular(map_path, "map", allow_empty=False)),
            "objectListSha256": _sha(_regular(object_list, "object list", allow_empty=False)),
            "profileSha256": _sha(_regular(profile_path, "profile", allow_empty=False)),
            "resolutionSha256": _sha(_regular(resolution, "resolution", allow_empty=False)),
        },
        "provenance": {
            "bootstrapReceiptSha256": _sha(_canonical(bootstrap_receipt)),
            "buildReceiptSha256": _sha(_canonical(build_receipt)),
            "fullPatchSha256": bootstrap_receipt["patch"]["sha256"],
            "generatedOverlayProjectionSha256": _sha(_canonical(bootstrap_receipt["overlay"])),
            "labDeltaReceiptSha256": _sha(_canonical(lab_delta_receipt)),
            "labPatchSha256": lab_delta_receipt["patch"]["sha256"],
            "nativeTerminalStatus": "DISCONNECTED_AFTER_ALL_OUTPUTS",
            "sdkCommit": bootstrap_receipt["sdkCommit"],
            "sdkIntakeReceiptSha256": _sha(_canonical(sdk_intake)),
            "sdkTree": bootstrap_receipt["sdkTree"],
            "sourceIntakeReceiptSha256": _sha(_canonical(source_intake)),
            "sourceTree": bootstrap_receipt["sourceTree"],
            "toolchainLockSha256": clone_lock_hashes["toolchain.lock.json"],
        },
        "schema": "e87-lab-panel-smoke-manifest-v2",
        "sourceCommit": expected_source_commit,
        "sourceDateEpoch": source_date_epoch,
        "status": "LAB_ONLY",
        "versions": {
            "firmwareBuildInfoSemver": "0.1.0",
            "transportQix": LAB_QIX_VERSION,
        },
    }
    _write_delivery_metadata(roots["delivery"], manifest)

    execution = {
        "buildCommand": build_receipt["command"],
        "extractCommands": extract_commands,
        "nativeCommands": native_commands,
        "schema": "e87-lab-panel-smoke-execution-v2",
        "stagingOverride": staging_override,
    }
    validation = {
        "bootstrap": bootstrap_receipt,
        "build": build_receipt,
        "labDelta": lab_delta_receipt,
        "proofs": proofs,
        "qualification": qualification,
        "schema": "e87-lab-panel-smoke-validation-v2",
        "sourceIntake": source_intake,
        "sdkIntake": sdk_intake,
    }
    receipt = {
        "app": {key: app[key] for key in ("filename", "sha256", "size")},
        "artifacts": artifact_records,
        "baseLocks": clone_lock_hashes,
        "bootstrapReceiptSha256": manifest["provenance"]["bootstrapReceiptSha256"],
        "buildReceiptSha256": manifest["provenance"]["buildReceiptSha256"],
        "eligibility": lab_lock["eligibility"],
        "labDeltaReceiptSha256": manifest["provenance"]["labDeltaReceiptSha256"],
        "labLockSha256": _sha(_regular(clone_lab_lock_path, "LAB lock", allow_empty=False)),
        "manifestSha256": _sha(_regular(roots["delivery"] / "manifest.json", "manifest", allow_empty=False)),
        "nativeTerminalStatus": "DISCONNECTED_AFTER_ALL_OUTPUTS",
        "qix": manifest["qix"],
        "schema": "e87-lab-panel-smoke-package-receipt-v2",
        "sourceCommit": expected_source_commit,
        "sourceDateEpoch": source_date_epoch,
        "sourceTree": bootstrap_receipt["sourceTree"],
    }
    STAGE0_PACKAGE._write_new(roots["evidence"] / "source-intake.json", _canonical(source_intake))
    STAGE0_PACKAGE._write_new(roots["evidence"] / "sdk-intake.json", _canonical(sdk_intake))
    STAGE0_PACKAGE._write_new(roots["evidence"] / "bootstrap-receipt.json", _canonical(bootstrap_receipt))
    STAGE0_PACKAGE._write_new(roots["evidence"] / "lab-delta-receipt.json", _canonical(lab_delta_receipt))
    STAGE0_PACKAGE._write_new(roots["evidence"] / "build-receipt.json", _canonical(build_receipt))
    STAGE0_PACKAGE._write_new(roots["evidence"] / "native-execution.json", _canonical(execution))
    STAGE0_PACKAGE._write_new(roots["evidence"] / "validation.json", _canonical(validation))
    STAGE0_PACKAGE._write_new(roots["evidence"] / "package-receipt.json", _canonical(receipt))
    STAGE0_PACKAGE._write_new(roots["evidence"] / "jl_isd.bin", proof_data["jl_isd.bin"])
    STAGE0_PACKAGE._write_new(roots["evidence"] / "independently-made.ufw", proof_data["independently-made.ufw"])
    if verify_repository_identity(repository, expected_source_commit) != source_intake["caller"]:
        raise ValueError("source repository identity changed during packaging")
    if verify_repository_identity(source_clone, expected_source_commit) != source_intake["materialized"]:
        raise ValueError("fresh source intake changed during packaging")
    sdk_identity = verify_repository_identity(sdk, SDK_COMMIT)
    if sdk_identity != sdk_intake["materialized"]:
        raise ValueError("SDK tree identity differs after packaging")
    return receipt


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--repository-root", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_arguments(argv)
    receipt = run_lab_package(
        reference_root=args.reference_root,
        run_root=args.run_root,
        expected_source_commit=args.expected_source_commit,
        repository_root=args.repository_root,
    )
    print(
        f"LAB PACKAGE OK: {receipt['qix']['filename']} "
        f"{receipt['qix']['sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
