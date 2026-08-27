#!/usr/bin/env python3
"""Build and verify the pinned Task 4 renderer golden corpus."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
GOLDEN_ROOT = ROOT / "firmware/generated/goldens"
RECEIPT = Path("/tmp/e87-final-qualification.json")
ASSET_LOCK = ROOT / "firmware/assets/asset-lock.json"
VALUES = (0, 1, 50, 99, 100)
WIDTH = 368
HEIGHT = 368
RAW_BYTES = WIDTH * HEIGHT * 2
RUNTIME = "127.0.0.1:5001/e87/asset-runtime@sha256:859689ef25f6940e22a5ea2427471596b42bb628bc8d308b5d3334721784d0ea"
RECEIPT_SHA = "41d577c0ab31fbbc8903bfcf845d7619052548da38c6d762c9f877925e5b2cec"
CC = "/usr/bin/x86_64-linux-gnu-gcc-12"
CC_SIZE = 1301496
CC_SHA = "75e997ec62297a6484f491bae28ab0ccb489daba23e398fd10fe68e9e6f0def8"
LD_PROBE = [
    "/usr/bin/x86_64-linux-gnu-gcc-12",
    "-B/usr/bin/",
    "-fuse-ld=bfd",
    "-print-prog-name=ld",
]
LD_PROBE_STDOUT = "/usr/bin/ld.bfd\n"
LD_RESOLVED = "/usr/bin/x86_64-linux-gnu-ld.bfd"
LD_SIZE = 1336592
LD_SHA = "f6d71a1bcd45764550a42dfaa179bc43b63ee879ec6f875bfd39fca013515da7"
PILLOW_WHEEL_SHA = "e74473c875d78b8e9d5da2a70f7099549f9eb37ded4e2f6a463e60125bccd176"
INPUT_PATHS = (
    "firmware/host/render_renderer.c",
    "firmware/overlay/SDK/apps/watch/e87/e87_renderer.c",
    "firmware/overlay/SDK/apps/watch/include/e87/e87_renderer.h",
    "firmware/overlay/SDK/apps/watch/include/e87/e87_state.h",
    "firmware/overlay/SDK/apps/watch/include/e87/e87_types.h",
    "firmware/generated/e87_assets.c",
    "firmware/generated/e87_assets.h",
    "firmware/tools/render-goldens.py",
)


class GoldenError(Exception):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def load_canonical(path: Path) -> dict:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise GoldenError(f"invalid JSON input {path}: {error}") from error
    if raw != canonical(value) or not isinstance(value, dict):
        raise GoldenError(f"noncanonical JSON input: {path}")
    return value


def stable_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update({
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "PYTHONHASHSEED": "0",
        "SOURCE_DATE_EPOCH": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    return environment


def verify_regular(path: Path, expected_size: int, expected_sha: str) -> None:
    try:
        metadata = path.stat()
    except OSError as error:
        raise GoldenError(f"missing pinned executable: {path}") from error
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != expected_size:
        raise GoldenError(f"pinned executable size mismatch: {path}")
    if sha_file(path) != expected_sha:
        raise GoldenError(f"pinned executable digest mismatch: {path}")


def verify_environment() -> None:
    if sha_file(RECEIPT) != RECEIPT_SHA:
        raise GoldenError("final qualification receipt digest mismatch")
    receipt = load_canonical(RECEIPT)
    if receipt["oci"]["runtimeReference"] != RUNTIME:
        raise GoldenError("final runtime reference mismatch")
    lock = load_canonical(ASSET_LOCK)
    if (lock["runtime"]["finalReference"] != RUNTIME or
            lock["runtime"]["finalQualificationSha256"] != RECEIPT_SHA):
        raise GoldenError("asset lock runtime identity mismatch")
    try:
        pillow = importlib.metadata.distribution("Pillow")
    except importlib.metadata.PackageNotFoundError as error:
        raise GoldenError("locked Pillow distribution is missing") from error
    if pillow.version != "12.2.0":
        raise GoldenError("locked Pillow version mismatch")


def verify_toolchain() -> dict:
    verify_regular(Path(CC), CC_SIZE, CC_SHA)
    probe = subprocess.run(
        LD_PROBE,
        cwd=ROOT,
        env=stable_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        shell=False,
    )
    if (probe.returncode != 0 or probe.stdout != LD_PROBE_STDOUT or
            probe.stderr != ""):
        raise GoldenError(
            "linker-selection probe mismatch: " + probe.stdout + probe.stderr)
    linker = Path(probe.stdout.rstrip("\n")).resolve(strict=True)
    if str(linker) != LD_RESOLVED:
        raise GoldenError("resolved linker target mismatch")
    verify_regular(linker, LD_SIZE, LD_SHA)
    return {
        "byteLength": LD_SIZE,
        "probeArguments": LD_PROBE,
        "probeStdout": LD_PROBE_STDOUT,
        "resolved": LD_RESOLVED,
        "sha256": LD_SHA,
    }


def compile_arguments(executable: Path) -> list[str]:
    return [
        CC,
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
        "firmware/host/render_renderer.c",
        "firmware/overlay/SDK/apps/watch/e87/e87_renderer.c",
        "firmware/generated/e87_assets.c",
        "-o",
        str(executable),
    ]


def compile_helper(root: Path) -> tuple[Path, list[str]]:
    executable = root / "render_renderer"
    arguments = compile_arguments(executable)
    result = subprocess.run(
        arguments,
        cwd=ROOT,
        env=stable_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        shell=False,
    )
    if result.returncode != 0:
        raise GoldenError(
            "golden helper compile failed: " + result.stdout + result.stderr)
    if result.stdout or result.stderr:
        raise GoldenError(
            "golden helper compile emitted output: " +
            result.stdout + result.stderr)
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise GoldenError("golden helper executable missing")
    normalized = list(arguments)
    normalized[-1] = "$TMP/render_renderer"
    return executable, normalized


def encode_png(raw: bytes) -> bytes:
    from PIL import Image

    rgb = bytearray(WIDTH * HEIGHT * 3)
    for pixel_index in range(WIDTH * HEIGHT):
        word = raw[pixel_index * 2] | (raw[pixel_index * 2 + 1] << 8)
        red = (word >> 11) & 0x1F
        green = (word >> 5) & 0x3F
        blue = word & 0x1F
        rgb[pixel_index * 3] = (red << 3) | (red >> 2)
        rgb[pixel_index * 3 + 1] = (green << 2) | (green >> 4)
        rgb[pixel_index * 3 + 2] = (blue << 3) | (blue >> 2)
    image = Image.frombytes("RGB", (WIDTH, HEIGHT), bytes(rgb))
    stream = io.BytesIO()
    image.save(stream, format="PNG", compress_level=9, optimize=False)
    image.close()
    return stream.getvalue()


def render_scene(executable: Path, day: int, week: int) -> bytes:
    result = subprocess.run(
        [str(executable), str(day), str(week)],
        cwd=ROOT,
        env=stable_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
    )
    if result.returncode != 0:
        raise GoldenError(
            f"golden helper failed for {day}/{week}: " +
            result.stderr.decode("utf-8", "replace"))
    if result.stderr:
        raise GoldenError(f"golden helper wrote stderr for {day}/{week}")
    if len(result.stdout) != RAW_BYTES:
        raise GoldenError(f"golden raw byte count mismatch for {day}/{week}")
    return result.stdout


def unique_root() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory(prefix="e87-task4-goldens-", dir="/tmp")


def generate_outputs() -> dict[str, bytes]:
    linker = verify_toolchain()
    with unique_root() as temporary:
        temporary_root = Path(temporary).resolve(strict=True)
        if temporary_root.parent != Path("/tmp"):
            raise GoldenError("temporary generation root escaped /tmp")
        executable, normalized_arguments = compile_helper(temporary_root)
        scenes = []
        outputs: dict[str, bytes] = {}
        for day in VALUES:
            for week in VALUES:
                name = f"face-day-{day:03d}-week-{week:03d}.png"
                raw = render_scene(executable, day, week)
                png = encode_png(raw)
                outputs[name] = png
                scenes.append({
                    "day": day,
                    "png": name,
                    "pngSha256": sha(png),
                    "rawByteCount": len(raw),
                    "rawSha256": sha(raw),
                    "week": week,
                })

    input_hashes = {
        path: sha_file(ROOT / path)
        for path in INPUT_PATHS
    }
    manifest = {
        "compileArguments": normalized_arguments,
        "compiler": {
            "byteLength": CC_SIZE,
            "executable": CC,
            "sha256": CC_SHA,
        },
        "dimensions": {"height": HEIGHT, "width": WIDTH},
        "fixedCreditCents": 1727,
        "inputs": input_hashes,
        "linker": linker,
        "pillow": {
            "distribution": "Pillow",
            "version": "12.2.0",
            "wheelSha256": PILLOW_WHEEL_SHA,
        },
        "pixelFormat": "RGB565-word-little-endian",
        "runtimeReference": RUNTIME,
        "scenes": scenes,
        "schemaVersion": 1,
    }
    outputs["goldens-manifest.json"] = canonical(manifest)
    return outputs


def expected_names() -> set[str]:
    return {
        "goldens-manifest.json",
        *(
            f"face-day-{day:03d}-week-{week:03d}.png"
            for day in VALUES
            for week in VALUES
        ),
    }


def verify_destination_root(create: bool) -> None:
    parent = GOLDEN_ROOT.parent.resolve(strict=True)
    if parent != Path("/src/firmware/generated"):
        raise GoldenError("golden destination parent is not the allowlisted root")
    if create:
        GOLDEN_ROOT.mkdir(exist_ok=True)
    if GOLDEN_ROOT.resolve(strict=True) != Path(
            "/src/firmware/generated/goldens"):
        raise GoldenError("golden destination is not the fixed path")


def compare_committed(outputs: dict[str, bytes]) -> None:
    verify_destination_root(create=False)
    entries = list(GOLDEN_ROOT.iterdir())
    if any(not entry.is_file() for entry in entries):
        raise GoldenError("golden destination contains a non-file entry")
    if {entry.name for entry in entries} != expected_names():
        raise GoldenError("golden destination file set mismatch")
    for name, expected in outputs.items():
        if (GOLDEN_ROOT / name).read_bytes() != expected:
            raise GoldenError(f"golden output mismatch: {name}")


def write_committed(outputs: dict[str, bytes]) -> None:
    verify_destination_root(create=True)
    existing = list(GOLDEN_ROOT.iterdir())
    unexpected = [entry for entry in existing if entry.name not in expected_names()]
    if unexpected:
        raise GoldenError(
            "unexpected existing golden path: " + unexpected[0].name)
    for name in sorted(outputs):
        (GOLDEN_ROOT / name).write_bytes(outputs[name])
    compare_committed(outputs)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--write", action="store_const", const="write", dest="mode")
    modes.add_argument("--check", action="store_const", const="check", dest="mode")
    modes.add_argument(
        "--check-reproducible",
        action="store_const",
        const="check-reproducible",
        dest="mode",
    )
    parser.add_argument("--cc", required=True)
    parser.add_argument("--require-compiler-sha256", required=True)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        if arguments.cc != CC:
            raise GoldenError("compiler path is not the pinned in-container executable")
        if arguments.require_compiler_sha256.lower() != CC_SHA:
            raise GoldenError("required compiler digest mismatch")
        verify_environment()
        first = generate_outputs()
        if arguments.mode == "write":
            write_committed(first)
        elif arguments.mode == "check":
            compare_committed(first)
        else:
            second = generate_outputs()
            if first != second:
                raise GoldenError("two clean golden generations differ")
            compare_committed(first)
    except (GoldenError, OSError, KeyError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
