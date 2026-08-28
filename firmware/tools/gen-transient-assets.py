#!/usr/bin/env python3
"""Generate the qualified bitmap-only transient-screen asset corpus."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GENERATED = ROOT / "firmware/generated"
LOCK_PATH = ROOT / "firmware/assets/transient-asset-lock.json"
SPEC_PATH = ROOT / "firmware/assets/transient-ui.json"
BASE_GENERATOR = ROOT / "firmware/tools/gen-assets.py"
OUTPUT_NAMES = (
    "e87_transient_assets.h",
    "e87_transient_assets.c",
    "transient-assets-manifest.json",
)
GLYPHS = " %0123456789ABDEFGHIKLMNOPRSTUWY"
EXPECTED_FONT = {
    "advanceScale": 8,
    "family": "Roboto",
    "filter": "BOX",
    "pixelSize": 30,
    "rasterScale": 8,
    "weight": 500,
    "width": 100,
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) +
            "\n").encode()


def load_canonical(path: Path) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if raw != canonical(value) or not isinstance(value, dict):
        raise ValueError("noncanonical JSON: " + str(path))
    return value, raw


def load_base_generator():
    specification = importlib.util.spec_from_file_location(
        "e87_reviewed_asset_generator", BASE_GENERATOR)
    if specification is None or specification.loader is None:
        raise ValueError("reviewed asset generator cannot be imported")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def validate_inputs(base, base_lock: dict) -> tuple[dict, bytes, dict, bytes]:
    lock, lock_raw = load_canonical(LOCK_PATH)
    spec, spec_raw = load_canonical(SPEC_PATH)
    if lock.get("schemaVersion") != 1 or spec.get("schemaVersion") != 1:
        raise ValueError("wrong transient lock schema")
    if sha(base.LOCK_PATH.read_bytes()) != lock["baseAssetLockSha256"]:
        raise ValueError("reviewed base asset lock identity differs")
    if lock["runtimeReference"] != base.RUNTIME:
        raise ValueError("transient runtime identity differs")
    if spec["glyphs"] != GLYPHS or spec["font"] != EXPECTED_FONT:
        raise ValueError("transient glyph or font contract differs")
    if spec["display"] != {"height": 360, "stripRows": 30, "width": 360}:
        raise ValueError("transient display geometry differs")
    for name, record in lock["sources"].items():
        raw = (ROOT / record["destination"]).read_bytes()
        if (len(raw), sha(raw)) != (record["byteLength"], record["sha256"]):
            raise ValueError("transient source bytes differ: " + name)
    if base_lock["sources"]["roboto"]["sha256"] != \
            lock["sources"]["roboto"]["sha256"]:
        raise ValueError("Roboto identity differs between locks")
    return lock, lock_raw, spec, spec_raw


def render_glyphs(font_bytes: bytes) -> tuple[list[dict], bytes]:
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont
    from PIL import Image, ImageDraw, ImageFont

    glyphs = []
    packed = bytearray()
    with tempfile.TemporaryDirectory(prefix="e87-transient-font-") as temp:
        variable_path = Path(temp) / "variable.ttf"
        static_path = Path(temp) / "static.ttf"
        variable_path.write_bytes(font_bytes)
        variable = TTFont(variable_path, recalcTimestamp=False)
        static = instantiateVariableFont(
            variable, {"wght": 500, "wdth": 100}, inplace=False)
        static.recalcTimestamp = False
        static.save(static_path, reorderTables=True)
        font = ImageFont.truetype(
            static_path,
            size=240,
            layout_engine=ImageFont.Layout.BASIC,
        )
        for character in GLYPHS:
            high = Image.new("L", (512, 512), 0)
            ImageDraw.Draw(high).text(
                (128, 320),
                character,
                font=font,
                fill=255,
                stroke_width=0,
                anchor="ls",
            )
            low = high.resize((64, 64), resample=Image.Resampling.BOX)
            box = low.getbbox()
            advance = font.getlength(character)
            if advance != int(advance):
                raise ValueError("BASIC glyph advance is not integral")
            record = {
                "advanceQ3": int(advance),
                "alphaOffset": len(packed),
                "ascii": ord(character),
                "bearingX": 0,
                "bearingY": 0,
                "byteCount": 0,
                "character": character,
                "height": 0,
                "width": 0,
            }
            if box is not None:
                cropped = low.crop(box)
                raw = cropped.tobytes()
                record.update({
                    "bearingX": box[0] - 16,
                    "bearingY": box[1] - 40,
                    "byteCount": len(raw),
                    "height": cropped.height,
                    "width": cropped.width,
                })
                packed.extend(raw)
            glyphs.append(record)
    if len(glyphs) != 32 or glyphs[0]["character"] != " ":
        raise ValueError("transient glyph closure differs")
    return glyphs, bytes(packed)


def emit_values(values: bytes, per_line: int = 12) -> str:
    lines = []
    for start in range(0, len(values), per_line):
        lines.append(
            "    " + ", ".join(
                "0x%02x" % value for value in values[start:start + per_line]
            ) + ","
        )
    return "\n".join(lines)


def emit_header() -> bytes:
    return """#ifndef E87_TRANSIENT_ASSETS_H
#define E87_TRANSIENT_ASSETS_H

#include <stdint.h>

#include "e87_assets.h"

#define E87_TRANSIENT_GLYPH_COUNT 32u

struct e87_bitmap_glyph {
    uint32_t alpha_offset;
    uint16_t width;
    uint16_t height;
    int16_t bearing_x;
    int16_t bearing_y;
    uint16_t advance_q3;
    uint8_t ascii;
    uint8_t reserved;
};

extern const uint8_t e87_transient_glyph_alpha[];
extern const uint32_t e87_transient_glyph_alpha_byte_count;
extern const struct e87_bitmap_glyph
    e87_transient_glyphs[E87_TRANSIENT_GLYPH_COUNT];
extern const struct e87_alpha_asset e87_transient_asset_bolt;

#endif
""".encode()


def emit_c(glyphs: list[dict], glyph_alpha: bytes, bolt_alpha: bytes) -> bytes:
    chunks = [
        '#include "e87_transient_assets.h"\n',
        "const uint8_t e87_transient_glyph_alpha[] = {\n" +
        emit_values(glyph_alpha) + "\n};\n",
        "const uint32_t e87_transient_glyph_alpha_byte_count = %uu;\n" %
        len(glyph_alpha),
        "const struct e87_bitmap_glyph "
        "e87_transient_glyphs[E87_TRANSIENT_GLYPH_COUNT] = {\n",
    ]
    for glyph in glyphs:
        chunks.append(
            "    {%uu, %uu, %uu, %d, %d, %uu, %uu, 0u},\n" % (
                glyph["alphaOffset"], glyph["width"], glyph["height"],
                glyph["bearingX"], glyph["bearingY"], glyph["advanceQ3"],
                glyph["ascii"],
            )
        )
    chunks.extend([
        "};\n",
        "static const uint8_t e87_transient_bolt_alpha[] = {\n" +
        emit_values(bolt_alpha) + "\n};\n",
        "const struct e87_alpha_asset e87_transient_asset_bolt = {\n"
        "    18u, 18u, 324u, e87_transient_bolt_alpha\n};\n",
    ])
    return "\n".join(chunks).encode()


def generate(base, base_lock: dict) -> dict[str, bytes]:
    lock, lock_raw, spec, spec_raw = validate_inputs(base, base_lock)
    roboto = (ROOT / lock["sources"]["roboto"]["destination"]).read_bytes()
    bolt = (ROOT / lock["sources"]["bolt"]["destination"]).read_bytes()
    glyphs, glyph_alpha = render_glyphs(roboto)
    bolt_image, bolt_alpha = base.render_svg_mask(bolt, 18, 18)
    del bolt_image
    header = emit_header()
    source = emit_c(glyphs, glyph_alpha, bolt_alpha)
    manifest = {
        "bolt": {
            "alphaSha256": sha(bolt_alpha),
            "byteCount": len(bolt_alpha),
            "height": 18,
            "nonzeroBounds": base.mask_bounds(bolt_alpha, 18, 18),
            "symbol": "e87_transient_asset_bolt",
            "width": 18,
        },
        "font": spec["font"],
        "generatorSha256": sha(Path(__file__).read_bytes()),
        "glyphAlphaByteCount": len(glyph_alpha),
        "glyphAlphaSha256": sha(glyph_alpha),
        "glyphOrder": list(GLYPHS),
        "glyphs": glyphs,
        "lockSha256": sha(lock_raw),
        "outputs": {
            "c": {"sha256": sha(source)},
            "header": {"sha256": sha(header)},
        },
        "runtimeReference": base.RUNTIME,
        "schemaVersion": 1,
        "sources": lock["sources"],
        "uiSpec": {
            "sha256": sha(spec_raw),
            "strings": spec["strings"],
        },
    }
    return {
        "e87_transient_assets.h": header,
        "e87_transient_assets.c": source,
        "transient-assets-manifest.json": canonical(manifest),
    }


def compare(outputs: dict[str, bytes]) -> None:
    for name in OUTPUT_NAMES:
        path = GENERATED / name
        if not path.is_file() or path.read_bytes() != outputs[name]:
            raise ValueError("generated transient output differs: " + name)


def write_files(outputs: dict[str, bytes]) -> None:
    GENERATED.mkdir(parents=True, exist_ok=True)
    for name in OUTPUT_NAMES:
        destination = GENERATED / name
        temporary = GENERATED / ("." + name + ".tmp")
        temporary.write_bytes(outputs[name])
        os.replace(temporary, destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--write", action="store_true")
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--check-reproducible", action="store_true")
    arguments = parser.parse_args()
    if arguments.write and GENERATED.resolve() != Path("/src/firmware/generated"):
        raise ValueError("write destination is not exact generated root")

    base = load_base_generator()
    base_lock, _ = base._lock()
    state = base.begin_generation_qualification(base_lock)
    first = generate(base, base_lock)
    if arguments.check_reproducible:
        second = generate(base, base_lock)
        for name in OUTPUT_NAMES:
            if first[name] != second[name]:
                raise ValueError("clean transient generations differ: " + name)
    base.finish_generation_qualification(base_lock, state)
    if arguments.write:
        write_files(first)
    else:
        compare(first)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
