#!/usr/bin/env python3
"""Black-box projection tests for the LAB_ONLY panel link validator."""

from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "firmware/tools/validate-lab-panel-map.py"
PROFILE = ROOT / "firmware/board-profiles/E87-1542-LAB-PANEL-SMOKE-H.json"


def load_tool():
    spec = importlib.util.spec_from_file_location("e87_lab_panel_map", TOOL)
    if spec is None or spec.loader is None:
        raise AssertionError("validator module is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LabPanelMapValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = load_tool()
        self.profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        self.sources = self.tool.expected_source_objects(self.profile)
        self.archives = self.tool.expected_archive_loads()
        rows = [
            "cpu/br35/liba/gpu.a(dbi.c.o)  "
            "objs/apps/watch/e87/e87_panel_jd9855.c.o "
            "(symbol from plugin) (lcd_set_align)",
            "cpu/br35/liba/gpu.a(dbi_mcu.c.o)  "
            "dbi.c.o (symbol from plugin) (dbi_pap_io)",
        ]
        loads = [self.sources[0], "cpu/br35/tools/sdk.elf.o"]
        loads.extend(self.sources[1:])
        loads.extend(self.archives)
        self.map_text = (
            "Archive member included to satisfy reference by file (symbol)\n\n"
            + "\n".join(rows)
            + "\n\nDiscarded input sections\n\n"
            + "Linker script and memory map\n"
            + "                0x0000000000137000 _RAM_LIMIT_H = 0x137000\n"
            + "                0x0000000000136e00 UPDATA_BEG = 0x136e00\n"
            + "                0x0000000000000000 PSRAM_SIZE = 0x0\n"
            + "                0x0000000000105280 _HEAP_BEGIN = .\n"
            + "                0x0000000000130e00 _HEAP_END = .\n"
            + "                0x0000000000130e00 _E87_LCD_RESERVED_START = .\n"
            + "                0x0000000000130e00 _E87_LCD_BUFFER_START = .\n"
            + "                0x0000000000136260 _E87_LCD_BUFFER_END = .\n"
            + "                0x0000000000136e00 _E87_LCD_RESERVED_END = .\n"
            + "                0x000000000c000100 _initcall_begin = .\n"
            + "                0x000000000c000100 _initcall_end = .\n"
            + "                0x000000000c000100 _early_initcall_begin = .\n"
            + "                0x000000000c000100 _early_initcall_end = .\n"
            + "                0x000000000c000100 _late_initcall_begin = .\n"
            + "                0x000000000c000100 _late_initcall_end = .\n"
            + "                0x000000000c000100 _platform_initcall_begin = .\n"
            + "                0x000000000c000100 _platform_initcall_end = .\n"
            + "                0x000000000c000100 _module_initcall_begin = .\n"
            + "                0x000000000c000100 _module_initcall_end = .\n"
            + "                0x000000000c000100 platform_uninitcall_begin = .\n"
            + "                0x000000000c000100 platform_uninitcall_end = .\n"
            + " .e87_lcd_buffer\n"
            + "                0x0000000000130e00     0x5460 "
            + "cpu/br35/tools/sdk.elf.o\n"
            + "\n".join(f"LOAD {item}" for item in loads)
            + "\nOUTPUT(cpu/br35/tools/sdk.elf elf32-pi32v2)\n"
        )
        self.object_list = (" " + " ".join(self.sources) + "\n").encode("ascii")
        self.resolution = (
            "objs/apps/watch/log_config/app_config.c.o\n"
            "-r=objs/apps/watch/log_config/app_config.c.o,log_tag_const_d_UI,pl\n"
            "-r=objs/apps/watch/log_config/app_config.c.o,log_tag_const_i_UI,pl\n"
            "cpu/br35/liba/gpu.a.llvm.1.dbi.c\n"
            "-r=cpu/br35/liba/gpu.a.llvm.1.dbi.c,log_tag_const_d_UI,l\n"
            "cpu/br35/liba/gpu.a.llvm.2.dbi_mcu.c\n"
            "-r=cpu/br35/liba/gpu.a.llvm.2.dbi_mcu.c,log_tag_const_i_UI,l\n"
        ).encode("ascii")

    def validate(self, *, map_text: str | None = None, object_list: bytes | None = None,
                 resolution: bytes | None = None, profile: dict | None = None):
        return self.tool.validate_projection(
            (self.map_text if map_text is None else map_text).encode("ascii"),
            self.object_list if object_list is None else object_list,
            self.resolution if resolution is None else resolution,
            self.profile if profile is None else profile,
        )

    def test_accepts_exact_lab_projection(self) -> None:
        result = self.validate()
        self.assertEqual(result["sourceObjectCount"], 23)
        self.assertEqual(result["appCoreStackBytes"], 4096)
        self.assertEqual(result["lcdBufferBytes"], 0x5460)

    def test_rejects_ambient_missing_ui_log_provider(self) -> None:
        objects = self.object_list.replace(
            b" objs/apps/watch/log_config/app_config.c.o", b"", 1
        )
        with self.assertRaisesRegex(self.tool.ValidationError, "source object"):
            self.validate(object_list=objects)

    def test_rejects_gpu_resolution_without_exact_provider(self) -> None:
        resolution = self.resolution.replace(b",log_tag_const_d_UI,pl", b",log_tag_const_d_UI,l", 1)
        with self.assertRaisesRegex(self.tool.ValidationError, "provider"):
            self.validate(resolution=resolution)

    def test_rejects_wrong_lcd_buffer_size(self) -> None:
        changed = self.map_text.replace("0x5460 cpu/br35/tools", "0x545e cpu/br35/tools", 1)
        with self.assertRaisesRegex(self.tool.ValidationError, "LCD buffer"):
            self.validate(map_text=changed)

    def test_rejects_live_connectivity_symbol(self) -> None:
        changed = self.map_text.replace(
            "OUTPUT(cpu/br35/tools/sdk.elf elf32-pi32v2)",
            "                0x000000000c001234 btstack_init\n"
            "OUTPUT(cpu/br35/tools/sdk.elf elf32-pi32v2)",
        )
        with self.assertRaisesRegex(self.tool.ValidationError, "forbidden symbol"):
            self.validate(map_text=changed)

    def test_rejects_stack_regression_in_profile(self) -> None:
        profile = deepcopy(self.profile)
        profile["boot"]["appCoreStackBytes"] = 768
        with self.assertRaisesRegex(self.tool.ValidationError, "stack"):
            self.validate(profile=profile)


if __name__ == "__main__":
    unittest.main()
