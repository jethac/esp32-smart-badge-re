#!/usr/bin/env python3
"""Build and verify the isolated transient-screen golden corpus."""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BASE_TOOL = ROOT / "firmware/tools/render-goldens.py"
GOLDEN_ROOT = ROOT / "firmware/generated/transient-goldens"
MANIFEST_NAME = "transient-goldens-manifest.json"
SCENES = (
    "unpaired",
    "waiting",
    "pairing-060",
    "pairing-001",
    "warning-003",
    "warning-002",
    "warning-001",
    "battery-face-000",
    "battery-face-001",
    "battery-face-050",
    "battery-face-099",
    "battery-face-100",
    "battery-face-050-charging",
    "battery-face-100-full",
    "battery-stale-037",
    "battery-fault",
    "maintenance-release-valid-050",
    "maintenance-waiting-valid-050",
    "maintenance-ready-valid-050",
    "maintenance-update-000",
    "maintenance-update-001",
    "maintenance-update-050",
    "maintenance-update-099",
    "maintenance-update-100",
    "maintenance-error",
    "maintenance-stale-037",
    "maintenance-fault",
    "recovery-release-valid-050",
)
INPUT_PATHS = (
    "firmware/host/render_transient_renderer.c",
    "firmware/overlay/SDK/apps/watch/e87/e87_transient_renderer.c",
    "firmware/overlay/SDK/apps/watch/include/e87/e87_transient_renderer.h",
    "firmware/overlay/SDK/apps/watch/include/e87/e87_ui.h",
    "firmware/overlay/SDK/apps/watch/include/e87/e87_renderer.h",
    "firmware/overlay/SDK/apps/watch/include/e87/e87_state.h",
    "firmware/overlay/SDK/apps/watch/include/e87/e87_types.h",
    "firmware/overlay/SDK/apps/watch/e87/e87_renderer.c",
    "firmware/generated/e87_transient_assets.c",
    "firmware/generated/e87_transient_assets.h",
    "firmware/generated/e87_assets.c",
    "firmware/generated/e87_assets.h",
    "firmware/assets/transient-ui.json",
    "firmware/generated/transient-assets-manifest.json",
    "firmware/tools/render-transient-goldens.py",
)


class GoldenError(Exception):
    pass


def load_base_tool():
    specification = importlib.util.spec_from_file_location(
        "e87_reviewed_normal_golden_tool", BASE_TOOL)
    if specification is None or specification.loader is None:
        raise GoldenError("reviewed normal golden tool cannot be imported")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def compile_arguments(base, executable: Path) -> list[str]:
    return [
        base.CC,
        "-B/usr/bin/",
        "-fuse-ld=bfd",
        "-std=c11",
        "-O0",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic",
        "-fno-common",
        "-DE87_HOST_TEST=1",
        "-Wl,--build-id=none",
        "-I",
        "firmware/host",
        "-I",
        "firmware/overlay/SDK/apps/watch/include",
        "-I",
        "firmware/generated",
        "firmware/host/render_transient_renderer.c",
        "firmware/overlay/SDK/apps/watch/e87/e87_transient_renderer.c",
        "firmware/overlay/SDK/apps/watch/e87/e87_renderer.c",
        "firmware/generated/e87_transient_assets.c",
        "firmware/generated/e87_assets.c",
        "-o",
        str(executable),
    ]


def compile_helper(base, root: Path) -> tuple[Path, list[str]]:
    executable = root / "render_transient_renderer"
    arguments = compile_arguments(base, executable)
    result = subprocess.run(
        arguments,
        cwd=ROOT,
        env=base.stable_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        shell=False,
    )
    if result.returncode != 0 or result.stdout or result.stderr:
        raise GoldenError(
            "transient golden helper compile failed: " +
            result.stdout + result.stderr)
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise GoldenError("transient golden helper executable missing")
    normalized = list(arguments)
    normalized[-1] = "$TMP/render_transient_renderer"
    return executable, normalized


def render_scene(base, executable: Path, name: str) -> bytes:
    result = subprocess.run(
        [str(executable), name],
        cwd=ROOT,
        env=base.stable_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
    )
    if result.returncode != 0:
        raise GoldenError(
            "transient helper failed for " + name + ": " +
            result.stderr.decode("utf-8", "replace"))
    if result.stderr or len(result.stdout) != base.RAW_BYTES:
        raise GoldenError("transient helper output differs for " + name)
    return result.stdout


def generate_outputs(base) -> dict[str, bytes]:
    linker = base.verify_toolchain()
    with tempfile.TemporaryDirectory(
            prefix="e87-transient-goldens-", dir="/tmp") as temporary:
        temporary_root = Path(temporary).resolve(strict=True)
        if temporary_root.parent != Path("/tmp"):
            raise GoldenError("temporary generation root escaped /tmp")
        executable, normalized_arguments = compile_helper(base, temporary_root)
        scenes = []
        outputs: dict[str, bytes] = {}
        for name in SCENES:
            raw = render_scene(base, executable, name)
            png = base.encode_png(raw)
            filename = name + ".png"
            outputs[filename] = png
            scenes.append({
                "name": name,
                "png": filename,
                "pngSha256": base.sha(png),
                "rawByteCount": len(raw),
                "rawSha256": base.sha(raw),
            })
    manifest = {
        "compileArguments": normalized_arguments,
        "compiler": {
            "byteLength": base.CC_SIZE,
            "executable": base.CC,
            "sha256": base.CC_SHA,
        },
        "dimensions": {"height": base.HEIGHT, "width": base.WIDTH},
        "inputs": {path: base.sha_file(ROOT / path) for path in INPUT_PATHS},
        "linker": linker,
        "pillow": {
            "distribution": "Pillow",
            "version": "12.2.0",
            "wheelSha256": base.PILLOW_WHEEL_SHA,
        },
        "pixelFormat": "RGB565-word-little-endian",
        "runtimeReference": base.RUNTIME,
        "scenes": scenes,
        "schemaVersion": 1,
    }
    outputs[MANIFEST_NAME] = base.canonical(manifest)
    return outputs


def compare_outputs(candidate: dict[str, bytes]) -> None:
    expected = set(candidate)
    if not GOLDEN_ROOT.is_dir():
        raise GoldenError("transient golden root is missing")
    actual = {path.name for path in GOLDEN_ROOT.iterdir() if path.is_file()}
    if actual != expected:
        raise GoldenError("transient golden output set differs")
    for name, data in candidate.items():
        if (GOLDEN_ROOT / name).read_bytes() != data:
            raise GoldenError("transient golden output differs: " + name)


def write_outputs(candidate: dict[str, bytes]) -> None:
    GOLDEN_ROOT.mkdir(parents=True, exist_ok=True)
    expected = set(candidate)
    actual = {path.name for path in GOLDEN_ROOT.iterdir() if path.is_file()}
    if actual - expected:
        raise GoldenError("unexpected transient golden output")
    staging = Path(tempfile.mkdtemp(
        prefix=".transient-goldens-stage-", dir=GOLDEN_ROOT))
    try:
        for name, data in candidate.items():
            (staging / name).write_bytes(data)
        for name in sorted(candidate):
            os.replace(staging / name, GOLDEN_ROOT / name)
    finally:
        shutil.rmtree(staging)


def main() -> int:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--write", action="store_true")
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--check-reproducible", action="store_true")
    parser.add_argument("--cc", required=True)
    parser.add_argument("--require-compiler-sha256", required=True)
    arguments = parser.parse_args()

    base = load_base_tool()
    if arguments.cc != base.CC or \
            arguments.require_compiler_sha256.lower() != base.CC_SHA:
        raise GoldenError("transient golden compiler identity differs")
    base.verify_environment()
    first = generate_outputs(base)
    if arguments.check_reproducible:
        second = generate_outputs(base)
        if first != second:
            raise GoldenError("two transient golden generations differ")
    if arguments.write:
        if ROOT != Path("/src"):
            raise GoldenError("transient golden write root is not /src")
        write_outputs(first)
    else:
        compare_outputs(first)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
