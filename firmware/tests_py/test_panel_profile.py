#!/usr/bin/env python3
"""Exact, host-only oracles for the recovered JD9855 panel profile."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import struct
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "firmware/tools/extract-panel-init.py"
RAW = ROOT / "firmware/assets/sources/jd9855-init.raw.bin"
PANEL_SOURCE = ROOT / "firmware/overlay/SDK/apps/watch/e87/e87_panel_jd9855.c"

SOURCE_SIZE = 995_584
SOURCE_SHA256 = "a38b77e27b1dc73cae0fbd8a7c4e3a04c64ff393fb4f27bc92a7578336be0147"
IMAGE_BASE = 0x0C000100
DESCRIPTOR_FILE_OFFSET = 0xEF688
DESCRIPTOR_RUNTIME_ADDRESS = 0x00106E08
INIT_ADDRESS = 0x0C0E59E0
INIT_FILE_OFFSET = 0xE58E0
INIT_SIZE = 657
INIT_SHA256 = "bb0767d3e0bf4ad982725c6a38a9168ddf9e5ba2e3d4d595b1ffbdd17e5b89ff"
PARAM_FILE_OFFSET = 0xEF8A4
PARAM_RUNTIME_ADDRESS = 0x00107024
PARAM_SIZE = 196
PARAM_SHA256 = "bff9d90b248ecfb370877a1cf9677d67e66e4bc1e79e07962cc59e1a87a43a3b"
START = bytes.fromhex("12 34 56 78")
END = bytes.fromhex("87 65 43 21")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_tool():
    spec = importlib.util.spec_from_file_location("e87_panel_extractor", TOOL)
    if spec is None or spec.loader is None:
        raise AssertionError("unable to load panel extractor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_parameter_image() -> bytes:
    result = bytearray(PARAM_SIZE)
    values = (
        0, 0, 360, 360,
        360, 360, 0,
        2, 0x5460,
        360, 360, 1, 0,
        0, 0x00FF0000,
        90,
        0x21, 0x21, 1, 0,
    )
    struct.pack_into("<20I", result, 0, *values)
    return bytes(result)


def make_synthetic_app(raw: bytes) -> bytes:
    result = bytearray(SOURCE_SIZE)
    name_address = 0x0C0E3E22
    name_offset = name_address - IMAGE_BASE
    result[name_offset:name_offset + 7] = b"jd9855\0"
    descriptor = bytearray(56)
    struct.pack_into("<I", descriptor, 0, name_address)
    descriptor[4:6] = bytes((2, 2))
    struct.pack_into("<I", descriptor, 8, INIT_ADDRESS)
    struct.pack_into("<I", descriptor, 12, INIT_SIZE)
    struct.pack_into("<I", descriptor, 16, 180)
    struct.pack_into("<I", descriptor, 20, 0xFFFFFFFF)
    struct.pack_into("<I", descriptor, 24, PARAM_RUNTIME_ADDRESS)
    struct.pack_into("<I", descriptor, 32, 0x0C03CAE0)
    struct.pack_into("<I", descriptor, 40, 0x0C03CB40)
    struct.pack_into("<I", descriptor, 44, 0x0C03CB5C)
    result[DESCRIPTOR_FILE_OFFSET:DESCRIPTOR_FILE_OFFSET + len(descriptor)] = descriptor
    result[INIT_FILE_OFFSET:INIT_FILE_OFFSET + len(raw)] = raw
    result[PARAM_FILE_OFFSET:PARAM_FILE_OFFSET + PARAM_SIZE] = make_parameter_image()
    return bytes(result)


def c_init_bytes(source: str) -> bytes:
    match = re.search(
        r"const\s+uint8_t\s+e87_jd9855_init_program\s*\[[^\]]*\]\s*=\s*\{(.*?)\};",
        source,
        re.S,
    )
    if not match:
        raise AssertionError("missing e87_jd9855_init_program")
    values = [int(item, 0) for item in re.findall(r"0x[0-9a-fA-F]+|\d+", match.group(1))]
    if any(value > 255 for value in values):
        raise AssertionError("out-of-range initializer byte")
    return bytes(values)


class PanelProfileTests(unittest.TestCase):
    maxDiff = None

    def need(self, path: Path) -> Path:
        self.assertTrue(path.is_file(), "missing exact required file: " + str(path))
        return path

    def test_extractor_constants_pin_the_recovered_addresses_and_hashes(self):
        module = load_tool()
        self.assertEqual(module.SOURCE_SIZE, SOURCE_SIZE)
        self.assertEqual(module.SOURCE_SHA256.lower(), SOURCE_SHA256)
        self.assertEqual(module.IMAGE_BASE, IMAGE_BASE)
        self.assertEqual(module.DESCRIPTOR_FILE_OFFSET, DESCRIPTOR_FILE_OFFSET)
        self.assertEqual(module.DESCRIPTOR_RUNTIME_ADDRESS, DESCRIPTOR_RUNTIME_ADDRESS)
        self.assertEqual(module.INIT_ADDRESS, INIT_ADDRESS)
        self.assertEqual(module.INIT_FILE_OFFSET, INIT_FILE_OFFSET)
        self.assertEqual(module.INIT_SIZE, INIT_SIZE)
        self.assertEqual(module.INIT_SHA256.lower(), INIT_SHA256)
        self.assertEqual(module.PARAM_FILE_OFFSET, PARAM_FILE_OFFSET)
        self.assertEqual(module.PARAM_RUNTIME_ADDRESS, PARAM_RUNTIME_ADDRESS)
        self.assertEqual(module.PARAM_SIZE, PARAM_SIZE)
        self.assertEqual(module.PARAM_SHA256.lower(), PARAM_SHA256)
        self.assertEqual(module.INIT_ADDRESS - module.IMAGE_BASE, module.INIT_FILE_OFFSET)

    def test_vendored_program_is_exact_and_matches_the_compiled_program(self):
        raw = self.need(RAW).read_bytes()
        self.assertEqual((len(raw), sha(raw)), (INIT_SIZE, INIT_SHA256))
        compiled = c_init_bytes(self.need(PANEL_SOURCE).read_text(encoding="utf-8"))
        self.assertEqual(compiled, raw)

    def test_program_has_exact_framing_record_count_and_tail(self):
        module = load_tool()
        records = module.parse_records(self.need(RAW).read_bytes())
        self.assertEqual(len(records), 51)
        self.assertEqual(records[:5], [
            bytes.fromhex("de 00"),
            bytes.fromhex("df 98 55"),
            bytes.fromhex("b2 2c"),
            bytes.fromhex("b7 01 29 01 51"),
            bytes.fromhex("bb 1b 64 c4 0e 3e f5"),
        ])
        self.assertEqual(records[-8:], [
            bytes.fromhex("ff 5a a5 ff 0a"),
            bytes.fromhex("4c 00"),
            bytes.fromhex("35 00"),
            bytes.fromhex("3a 55"),
            bytes.fromhex("11"),
            bytes.fromhex("ff 5a a5 ff 78"),
            bytes.fromhex("29"),
            bytes.fromhex("ff 5a a5 ff 14"),
        ])
        commands = [record[0] for record in records if not record.startswith(bytes.fromhex("ff 5a a5 ff"))]
        self.assertTrue(all(command not in {0x36, 0x2A, 0x2B} for command in commands))
        rebuilt = b"".join(START + record + END for record in records)
        self.assertEqual(rebuilt, self.need(RAW).read_bytes())

    def test_parameter_source_decodes_to_exact_recovered_profile(self):
        module = load_tool()
        params = make_parameter_image()
        self.assertEqual(sha(params), PARAM_SHA256)
        self.assertEqual(module.decode_parameter_image(params), {
            "bufferNum": 2,
            "bufferSize": 0x5460,
            "clockPolarity": 0,
            "debugColor": 0x00FF0000,
            "debugEnabled": 0,
            "fps": 90,
            "inFormat": 1,
            "inHeight": 360,
            "inStride": 0,
            "inWidth": 360,
            "lcdHeight": 360,
            "lcdType": 0,
            "lcdWidth": 360,
            "outFormat": 1,
            "pixelType": 0x21,
            "scrHeight": 360,
            "scrWidth": 360,
            "scrX": 0,
            "scrY": 0,
            "spiDataMode": 0,
            "spiMode": 0x21,
        })

    def test_parser_rejects_unframed_empty_nested_and_trailing_data(self):
        module = load_tool()
        raw = self.need(RAW).read_bytes()
        invalid = (
            raw[1:],
            START + END,
            START + b"\x11" + START + END,
            raw + b"\x00",
            raw[:-1],
        )
        for candidate in invalid:
            with self.subTest(length=len(candidate)):
                with self.assertRaises(ValueError):
                    module.parse_records(candidate)

    def test_cli_writes_only_with_explicit_output_and_is_offset_exact(self):
        module = load_tool()
        raw = self.need(RAW).read_bytes()
        app = make_synthetic_app(raw)
        with tempfile.TemporaryDirectory(prefix="e87-panel-") as temp:
            root = Path(temp)
            source = root / "app.bin"
            output = root / "init.bin"
            source.write_bytes(app)
            with mock.patch.object(module, "SOURCE_SHA256", sha(app)):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    self.assertEqual(module.main(["--input", str(source)]), 0)
                self.assertFalse(output.exists())
                report = json.loads(stdout.getvalue())
                self.assertEqual(report["init"]["fileOffset"], INIT_FILE_OFFSET)
                self.assertEqual(report["init"]["recordCount"], 51)
                self.assertEqual(report["descriptor"]["runtimeAddress"], DESCRIPTOR_RUNTIME_ADDRESS)
                self.assertEqual(report["parameter"]["runtimeAddress"], PARAM_RUNTIME_ADDRESS)
                self.assertEqual(
                    module.main(["--input", str(source), "--output", str(output)]),
                    0,
                )
            self.assertEqual(output.read_bytes(), raw)

    def test_cli_rejects_wrong_source_before_creating_output(self):
        module = load_tool()
        with tempfile.TemporaryDirectory(prefix="e87-panel-bad-") as temp:
            root = Path(temp)
            source = root / "wrong.bin"
            output = root / "must-not-exist.bin"
            source.write_bytes(b"wrong")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.assertEqual(
                    module.main(["--input", str(source), "--output", str(output)]),
                    2,
                )
            self.assertFalse(output.exists())
            self.assertIn("source size", stderr.getvalue())

    def test_target_bridge_is_serial_and_uses_only_approved_sdk_surface(self):
        source = self.need(PANEL_SOURCE).read_text(encoding="utf-8")
        for symbol in (
            "lcd_init(",
            "lcd_write_cmd(",
            "lcd_set_draw_area(",
            "lcd_clear(",
            "lcd_draw(",
            "lcd_wait_busy(",
            "lcd_set_align(",
            "lcd_enter_sleep(",
            "lcd_exit_sleep(",
            "power_gate_open_drain_output(",
            "IO_PORTA_05",
            "IO_LCD_PG",
        ):
            self.assertIn(symbol, source)
        for forbidden in (
            "lcd_draw_continue(",
            "lcd_draw_set_callback(",
            "lcd_set_te_wait_cb(",
            "malloc(",
        ):
            self.assertNotIn(forbidden, source)

    def test_target_sdk_headers_precede_the_portable_bool_api(self):
        source = self.need(PANEL_SOURCE).read_text(encoding="utf-8")
        self.assertLess(
            source.index("#include <stdint.h>"),
            source.index("#include <dbi.h>"),
            "the pinned DBI header exposes uint8_t without including stdint",
        )
        self.assertLess(
            source.index("#include <dbi.h>"),
            source.index('#include "e87/e87_panel.h"'),
            "the pinned SDK typedefs bool, so its headers must be parsed first",
        )
        self.assertNotIn("#include <stdbool.h>", source)


if __name__ == "__main__":
    unittest.main()
