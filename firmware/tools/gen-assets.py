#!/usr/bin/env python3
"""Deterministic, qualification-checked Task 4 asset generator."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / "firmware/assets/asset-lock.json"
REQ_PATH = ROOT / "firmware/assets/requirements.txt"
GENERATED = ROOT / "firmware/generated"
OUTPUT_NAMES = ("e87_assets.h", "e87_assets.c", "assets-manifest.json")
SOURCE_IDS = ("date_range", "devin", "material_license", "roboto", "roboto_license", "today")
EXPECTED_SETTINGS = (500, 100, 8, "BOX")
CORDIC_GAIN = 652032874
CORDIC_TABLE = (134217728,79233351,41864727,21251189,10666833,5338616,2669960,1335061,667541,333772,166886,83443,41722,20861,10430,5215,2608,1304,652,326,163,81,41,20)
RUNTIME = "127.0.0.1:5001/e87/asset-runtime@sha256:859689ef25f6940e22a5ea2427471596b42bb628bc8d308b5d3334721784d0ea"
RECEIPT_SHA = "41d577c0ab31fbbc8903bfcf845d7619052548da38c6d762c9f877925e5b2cec"
ENDPOINT_SHA = "7ecb1c6da7063e52ba854231c8162da1b4ad45a9ac6cec3cafd93cd571883bb9"
QUALIFIER_PATH = Path("/opt/e87/qualify-runtime.py")
QUALIFIER_SIZE = 25064
QUALIFIER_SHA = "53feb64e32cb1d69f8c2a7bd30ab00f7a1859f46926dbc4f4fd657c28bb76855"
EMBEDDED_RECEIPT_PATH = Path("/opt/e87/qualification-receipt.json")
EMBEDDED_RECEIPT_SHA = "d7740ab65ba5a9a1137877a57c93b27e0cd1c3803e723a065e72dfbfc647f174"
BASIS_RUNTIME = "127.0.0.1:5001/e87/asset-runtime@sha256:46773ee2b8c25e36300ad6ae03b5175ad34d20e8ae40976f9ba85edc9d98cdd1"
RECEIPT_PROJECTION_SHA = "99ed080d4fbead189c0f7a4926f46aedd2241b29dd971f23041ab05c16ed0efe"
FINAL_RECEIPT_PATH = Path("/tmp/e87-final-qualification.json")

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def canonical(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()

def load_canonical(path: Path) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if raw != canonical(value):
        raise ValueError("noncanonical JSON: " + str(path))
    return value, raw

def validate_generation_settings(wght: int, wdth: int, scale: int, filter_name: str) -> None:
    if (wght, wdth, scale, filter_name) != EXPECTED_SETTINGS:
        raise ValueError("generation settings differ from reviewed contract")

def _lock() -> tuple[dict, bytes]:
    lock, raw = load_canonical(LOCK_PATH)
    if lock.get("schemaVersion") != 1:
        raise ValueError("wrong asset lock schema")
    if lock["runtime"]["finalReference"] != RUNTIME:
        raise ValueError("wrong final runtime")
    if lock["runtime"]["finalQualificationSha256"] != RECEIPT_SHA:
        raise ValueError("wrong qualification receipt digest")
    if sha(REQ_PATH.read_bytes()) != "964dba45fb1b91a0591c4fecf0295b9e203d817d6c88388654c19a8972c66efb":
        raise ValueError("requirements identity mismatch")
    return lock, raw

def validate_source_bytes(source_id: str, data: bytes) -> None:
    lock, _ = _lock()
    if source_id not in SOURCE_IDS:
        raise ValueError("source not allowlisted")
    record = lock["sources"][source_id]
    if len(data) != record["byteLength"] or sha(data) != record["sha256"]:
        raise ValueError("source bytes differ: " + source_id)
    if source_id == "devin":
        header = ("blob %d\0" % len(data)).encode()
        if hashlib.sha1(header + data).hexdigest() != record["gitBlob"]:
            raise ValueError("Devin Git blob mismatch")

def _require_equal(label: str, actual: object, expected: object) -> None:
    if actual != expected:
        raise ValueError(label + " differs from locked qualification")


def _compact_receipt_projection(receipt: dict) -> str:
    projected = json.loads(json.dumps(receipt))
    del projected["oci"]["runtimeReference"]
    raw = json.dumps(
        projected, separators=(",", ":"), sort_keys=True, ensure_ascii=False
    ).encode()
    return sha(raw)


def _validate_receipt_chain(lock: dict) -> dict:
    runtime = lock["runtime"]
    if runtime.get("embeddedQualificationSha256") != EMBEDDED_RECEIPT_SHA:
        raise ValueError("embedded receipt digest is not pinned")
    if runtime.get("embeddedBasisProjectionSha256") != RECEIPT_PROJECTION_SHA:
        raise ValueError("embedded receipt projection is not pinned")
    for path, label in (
        (EMBEDDED_RECEIPT_PATH, "embedded qualification receipt"),
        (FINAL_RECEIPT_PATH, "live qualification receipt"),
    ):
        if path.is_symlink() or not path.is_file():
            raise ValueError(label + " is not a regular file")

    basis_raw = EMBEDDED_RECEIPT_PATH.read_bytes()
    if sha(basis_raw) != EMBEDDED_RECEIPT_SHA:
        raise ValueError("embedded qualification receipt identity differs")
    basis = json.loads(basis_raw)
    if basis_raw != canonical(basis):
        raise ValueError("embedded qualification receipt is noncanonical")
    if basis["oci"]["runtimeReference"] != BASIS_RUNTIME:
        raise ValueError("embedded qualification basis reference differs")

    final_raw = FINAL_RECEIPT_PATH.read_bytes()
    if sha(final_raw) != RECEIPT_SHA:
        raise ValueError("live qualification receipt identity differs")
    final = json.loads(final_raw)
    if final_raw != canonical(final):
        raise ValueError("live qualification receipt is noncanonical")
    _require_equal("live qualification receipt", final, runtime["qualification"])
    if final["oci"]["runtimeReference"] != RUNTIME:
        raise ValueError("live qualification runtime reference differs")

    promoted = json.loads(json.dumps(basis))
    promoted["oci"]["runtimeReference"] = RUNTIME
    if canonical(promoted) != final_raw:
        raise ValueError("embedded and final receipts differ beyond runtime reference")
    if (
        _compact_receipt_projection(basis) != RECEIPT_PROJECTION_SHA
        or _compact_receipt_projection(final) != RECEIPT_PROJECTION_SHA
    ):
        raise ValueError("qualification receipt projection differs")
    return final


def _load_pinned_qualifier():
    if QUALIFIER_PATH.is_symlink() or not QUALIFIER_PATH.is_file():
        raise ValueError("runtime qualifier is not a regular file")
    raw = QUALIFIER_PATH.read_bytes()
    if (len(raw), sha(raw)) != (QUALIFIER_SIZE, QUALIFIER_SHA):
        raise ValueError("runtime qualifier identity differs")
    spec = importlib.util.spec_from_file_location(
        "e87_pinned_runtime_qualifier", QUALIFIER_PATH
    )
    if spec is None or spec.loader is None:
        raise ValueError("runtime qualifier cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def begin_generation_qualification(lock: dict) -> dict:
    receipt = _validate_receipt_chain(lock)
    qualifier = _load_pinned_qualifier()

    _require_equal(
        "runtime shape", qualifier.runtime_shape(), receipt["runtimeShape"]
    )
    wheels, wheel_tree = qualifier.wheelhouse_inventory()
    _require_equal("wheel inventory", wheels, receipt["wheels"])
    _require_equal("wheelhouse tree", wheel_tree, receipt["wheelTreeSha256"])
    _require_equal("locked wheelhouse tree", wheel_tree, lock["wheelhouse"]["treeSha256"])

    embedded_requirements = qualifier.validate_requirements(
        Path("/opt/e87/requirements.txt")
    )
    repository_requirements = qualifier.validate_requirements(REQ_PATH)
    _require_equal(
        "embedded requirements", embedded_requirements, receipt["requirements"]
    )
    _require_equal(
        "repository requirements", repository_requirements, receipt["requirements"]
    )

    distributions, installed_tree = qualifier.installed_distributions()
    _require_equal(
        "installed distribution RECORD inventory",
        distributions,
        receipt["installedDistributions"],
    )
    _require_equal(
        "installed distribution tree", installed_tree, receipt["installedTreeSha256"]
    )

    python = {
        **qualifier.identity(qualifier.PYTHON),
        "version": qualifier.command_output(
            [qualifier.PYTHON.as_posix(), "--version"]
        ),
    }
    dynamic_linker = {
        **qualifier.identity(qualifier.LOADER),
        "dependencyListOperation": f"{qualifier.LOADER} --list <ELF>",
    }
    _require_equal("Python identity", python, receipt["python"])
    _require_equal("dynamic linker identity", dynamic_linker, receipt["dynamicLinker"])

    toolchain = qualifier.toolchain_probe()
    _require_equal(
        "compiler and linker toolchain",
        toolchain,
        receipt["compilerAndLinkerProbe"],
    )
    dpkg_inventory = sorted(
        qualifier.command_output(["/usr/bin/dpkg-query", "-W"]).splitlines()
    )
    _require_equal("dpkg inventory", dpkg_inventory, receipt["dpkgInventory"])
    pip = {
        "version": qualifier.command_output(
            [qualifier.PYTHON.as_posix(), "-m", "pip", "--version"]
        )
    }
    _require_equal("pip identity", pip, receipt["pip"])

    render = qualifier.render_probe(
        ROOT / "assets/icons/devin.svg",
        ROOT / lock["sources"]["roboto"]["destination"],
    )
    _require_equal(
        "qualification raster exercise", render, receipt["qualificationExercise"]
    )
    return {
        "qualifier": qualifier,
        "receipt": receipt,
        "toolchain": toolchain,
    }


def finish_generation_qualification(lock: dict, state: dict) -> None:
    _require_equal(
        "qualification state receipt",
        state["receipt"],
        lock["runtime"]["qualification"],
    )
    mapped, mapped_elf_paths = state["qualifier"].mapped_files()
    if (
        mapped != state["receipt"]["mappedFiles"]
        or mapped_elf_paths != state["receipt"]["mappedElfPaths"]
    ):
        raise ValueError("mapped file inventory differs from locked qualification")
    closure = state["qualifier"].native_closure(
        mapped_elf_paths, state["toolchain"]
    )
    _require_equal("native closure", closure, state["receipt"]["nativeClosure"])

def source_bytes(lock: dict, source_id: str) -> bytes:
    data = (ROOT / lock["sources"][source_id]["destination"]).read_bytes()
    validate_source_bytes(source_id, data)
    return data

def reject_external_svg(data: bytes) -> None:
    root = ET.fromstring(data)
    for element in root.iter():
        for key, value in element.attrib.items():
            if key.endswith("href") and not (value.startswith("#") or value.startswith("data:")):
                raise ValueError("external SVG reference rejected")

def mask_bounds(data: bytes, width: int, height: int) -> list[int]:
    points = [(i % width, i // width) for i, value in enumerate(data) if value]
    if not points:
        raise ValueError("empty mask")
    xs, ys = zip(*points)
    return [min(xs), min(ys), max(xs), max(ys)]

def render_svg_mask(data: bytes, width: int, height: int):
    reject_external_svg(data)
    import cairosvg
    from PIL import Image
    png = cairosvg.svg2png(bytestring=data, output_width=width * 8, output_height=height * 8,
                           unsafe=False, background_color=None)
    image = Image.open(io.BytesIO(png)).convert("RGBA").getchannel("A")
    result = image.resize((width, height), resample=Image.Resampling.BOX)
    raw = result.tobytes()
    if len(raw) != width * height:
        raise ValueError("SVG mask size mismatch")
    return result, raw

def render_credit_mask(font_bytes: bytes):
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont
    from PIL import Image, ImageDraw, ImageFont
    with tempfile.TemporaryDirectory(prefix="e87-font-") as temp:
        variable_path = Path(temp) / "variable.ttf"
        static_path = Path(temp) / "static.ttf"
        variable_path.write_bytes(font_bytes)
        variable = TTFont(variable_path, recalcTimestamp=False)
        static = instantiateVariableFont(variable, {"wght": 500, "wdth": 100}, inplace=False)
        static.recalcTimestamp = False
        static.save(static_path, reorderTables=True)
        font = ImageFont.truetype(static_path, size=240, layout_engine=ImageFont.Layout.BASIC)
        high = Image.new("L", (2048, 512), 0)
        ImageDraw.Draw(high).text((0, 0), "$17.27", font=font, fill=255, stroke_width=0, anchor="lt")
        low = high.resize((256, 64), resample=Image.Resampling.BOX)
        box = low.getbbox()
        if box is None:
            raise ValueError("credit mask empty")
        result = low.crop(box)
    if result.width > 128 or result.height > 40:
        raise ValueError("credit mask exceeds budget")
    return result, result.tobytes(), list(box)

def endpoint_table() -> tuple[list[int], list[int], bytes]:
    cos_values, sin_values = [], []
    for percent in range(101):
        angle = (percent * (1 << 30) + 50) // 100
        quadrant = (angle >> 28) & 3
        residual = angle & ((1 << 28) - 1)
        x, y, z = CORDIC_GAIN, 0, residual
        for i, table_value in enumerate(CORDIC_TABLE):
            old_x, old_y = x, y
            if z >= 0:
                x, y, z = old_x - (old_y >> i), old_y + (old_x >> i), z - table_value
            else:
                x, y, z = old_x + (old_y >> i), old_y - (old_x >> i), z + table_value
        x, y = ((x,y),(-y,x),(-x,-y),(y,-x))[quadrant]
        def q16(value: int) -> int:
            return (value + 8192) >> 14 if value >= 0 else -(((-value) + 8192) >> 14)
        pair = (q16(x), q16(y))
        if percent in (0,25,50,75,100):
            pair = {0:(65536,0),25:(0,65536),50:(-65536,0),75:(0,-65536),100:(65536,0)}[percent]
        cos_values.append(pair[0])
        sin_values.append(pair[1])
    packed = b"".join(struct.pack("<ii", c, s) for c, s in zip(cos_values, sin_values))
    if sha(packed) != ENDPOINT_SHA:
        raise ValueError("endpoint table digest mismatch: " + sha(packed))
    return cos_values, sin_values, packed

def emit_values(values: list[int], formatter, per_line: int) -> str:
    lines = []
    for start in range(0, len(values), per_line):
        lines.append("    " + ", ".join(formatter(v) for v in values[start:start + per_line]) + ",")
    return "\n".join(lines)

def emit_header() -> bytes:
    return ("""#ifndef E87_ASSETS_H
#define E87_ASSETS_H

#include <stdint.h>

#define E87_RING_ENDPOINT_COUNT 101u

struct e87_alpha_asset {
    uint16_t width;
    uint16_t height;
    uint32_t byte_count;
    const uint8_t *alpha;
};

extern const struct e87_alpha_asset e87_asset_devin;
extern const struct e87_alpha_asset e87_asset_today;
extern const struct e87_alpha_asset e87_asset_date_range;
extern const struct e87_alpha_asset e87_asset_credit_1727;
extern const int32_t e87_ring_cos_q16[E87_RING_ENDPOINT_COUNT];
extern const int32_t e87_ring_sin_q16[E87_RING_ENDPOINT_COUNT];

#endif
""").encode()

def emit_c(assets: dict, cos_values: list[int], sin_values: list[int]) -> bytes:
    chunks = ['#include "e87_assets.h"\n']
    for name in ("devin","today","date_range","credit_1727"):
        raw = assets[name]["raw"]
        chunks.append("static const uint8_t e87_asset_%s_alpha[] = {\n%s\n};\n" %
                      (name, emit_values(list(raw), lambda v: "0x%02x" % v, 12)))
    for name, values in (("cos",cos_values),("sin",sin_values)):
        chunks.append("const int32_t e87_ring_%s_q16[E87_RING_ENDPOINT_COUNT] = {\n%s\n};\n" %
                      (name, emit_values(values, str, 8)))
    for name in ("devin","today","date_range","credit_1727"):
        item = assets[name]
        chunks.append("const struct e87_alpha_asset e87_asset_%s = {\n"
                      "    %du, %du, %uu, e87_asset_%s_alpha\n};\n" %
                      (name, item["width"], item["height"], len(item["raw"]), name))
    return ("\n".join(chunks)).encode()

def generate(output_root: Path, lock: dict, lock_raw: bytes) -> dict[str, bytes]:
    del output_root
    validate_generation_settings(*EXPECTED_SETTINGS)
    for source_id in SOURCE_IDS:
        source_bytes(lock, source_id)
    assets = {}
    for name, width, height in (("devin",96,96),("today",18,18),("date_range",18,18)):
        image, raw = render_svg_mask(source_bytes(lock, name), width, height)
        assets[name] = {"image": image, "raw": raw, "width": width, "height": height}
    credit_image, credit_raw, pre_crop = render_credit_mask(source_bytes(lock, "roboto"))
    assets["credit_1727"] = {"image": credit_image, "raw": credit_raw,
                             "width": credit_image.width, "height": credit_image.height}
    cos_values, sin_values, packed = endpoint_table()
    header = emit_header()
    c_source = emit_c(assets, cos_values, sin_values)
    manifest_assets = {}
    for name, item in assets.items():
        manifest_assets[name] = {
            "alphaSha256": sha(item["raw"]),
            "byteCount": len(item["raw"]),
            "nonzeroBounds": mask_bounds(item["raw"], item["width"], item["height"]),
            "symbol": "e87_asset_" + name,
            "width": item["width"],
            "height": item["height"],
        }
    qualification = lock["runtime"]["qualification"]
    manifest = {
        "assets": manifest_assets,
        "endpoints": {
            "cardinals": {"0":[65536,0],"25":[0,65536],"50":[-65536,0],"75":[0,-65536],"100":[65536,0]},
            "count": 101,
            "format": "cos-then-sin-signed-le32-q16",
            "sha256": sha(packed),
        },
        "generation": {
            "creditPreCropBox": pre_crop,
            "filter": "BOX",
            "fontAxes": {"wdth":100,"wght":500},
            "fontPixelSize": 240,
            "glyphs": ["$",".","1","2","7"],
            "scale": 8,
        },
        "generatorSha256": sha(Path(__file__).read_bytes()),
        "lockSha256": sha(lock_raw),
        "outputs": {
            "c": {"sha256": sha(c_source)},
            "header": {"sha256": sha(header)},
        },
        "requirementsSha256": sha(REQ_PATH.read_bytes()),
        "schemaVersion": 1,
        "sources": lock["sources"],
        "tools": {
            "compilerSha256": qualification["compilerAndLinkerProbe"]["compiler"]["sha256"],
            "linkerSha256": qualification["compilerAndLinkerProbe"]["gnuLinker"]["sha256"],
            "nativeClosureTreeSha256": qualification["nativeClosure"]["treeSha256"],
            "pythonSha256": qualification["python"]["sha256"],
            "runtimeReference": RUNTIME,
            "wheelhouseTreeSha256": lock["wheelhouse"]["treeSha256"],
        },
    }
    return {"e87_assets.h": header, "e87_assets.c": c_source,
            "assets-manifest.json": canonical(manifest), "_assets": assets}

def write_files(root: Path, outputs: dict[str, bytes]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    expected = set(OUTPUT_NAMES)
    existing = {p.name for p in root.iterdir() if p.is_file()}
    if existing - expected:
        raise ValueError("unexpected generated output")
    for name in OUTPUT_NAMES:
        destination = root / name
        temp = root / ("." + name + ".tmp")
        temp.write_bytes(outputs[name])
        os.replace(temp, destination)

def compare(root: Path, outputs: dict[str, bytes]) -> None:
    for name in OUTPUT_NAMES:
        path = root / name
        if not path.is_file() or path.read_bytes() != outputs[name]:
            raise ValueError("generated output differs: " + name)

def encode_review_previews(outputs: dict) -> dict[str, bytes]:
    from PIL import PngImagePlugin
    del PngImagePlugin
    previews = {}
    for source_name, filename in (("devin","devin-alpha.png"),("today","today-alpha.png"),("date_range","date-range-alpha.png")):
        stream = io.BytesIO()
        outputs["_assets"][source_name]["image"].save(
            stream, format="PNG", compress_level=9, optimize=False
        )
        previews[filename] = stream.getvalue()
    return previews


def write_review_previews(previews: dict[str, bytes]) -> None:
    review = GENERATED / ".task4-review-previews"
    allowed = {"devin-alpha.png","today-alpha.png","date-range-alpha.png"}
    if set(previews) != allowed:
        raise ValueError("review preview output set differs")
    if review.exists():
        extras = {p.name for p in review.iterdir()} - allowed
        if extras:
            raise ValueError("unexpected review preview path")
    review.mkdir(parents=True, exist_ok=True)
    for filename in sorted(previews):
        temp = review / ("." + filename + ".tmp")
        temp.write_bytes(previews[filename])
        os.replace(temp, review / filename)

def main() -> int:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--write", action="store_true")
    modes.add_argument("--write-review-previews", action="store_true")
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--check-reproducible", action="store_true")
    args = parser.parse_args()
    if args.write or args.write_review_previews:
        if GENERATED.resolve() != Path("/src/firmware/generated"):
            raise ValueError("write destination is not exact generated root")

    lock, lock_raw = _lock()
    state = begin_generation_qualification(lock)
    if args.write:
        candidate = generate(GENERATED, lock, lock_raw)
    elif args.write_review_previews:
        candidate = generate(GENERATED, lock, lock_raw)
        compare(GENERATED, candidate)
        previews = encode_review_previews(candidate)
    elif args.check:
        with tempfile.TemporaryDirectory(prefix="e87-assets-") as temp:
            candidate = generate(Path(temp), lock, lock_raw)
        compare(GENERATED, candidate)
    else:
        with tempfile.TemporaryDirectory(prefix="e87-assets-a-") as first, tempfile.TemporaryDirectory(prefix="e87-assets-b-") as second:
            candidate = generate(Path(first), lock, lock_raw)
            second_candidate = generate(Path(second), lock, lock_raw)
        for name in OUTPUT_NAMES:
            if candidate[name] != second_candidate[name]:
                raise ValueError("clean generations differ: " + name)
        compare(GENERATED, candidate)

    finish_generation_qualification(lock, state)
    if args.write:
        write_files(GENERATED, candidate)
    elif args.write_review_previews:
        write_review_previews(previews)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
