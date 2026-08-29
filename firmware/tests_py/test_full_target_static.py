#!/usr/bin/env python3
"""Static contract for the UI-off E87 full-target link substrate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
PATCH = REPO_ROOT / "firmware/patches/full/0001-e87-full-substrate.patch"
PROFILE = REPO_ROOT / "firmware/board-profiles/E87-1542-FULL-SUBSTRATE-H.json"
OVERLAY = REPO_ROOT / "firmware/overlay/SDK/apps/watch"

PATCH_TARGETS = {
    "SDK/apps/watch/app_main.c",
    "SDK/apps/watch/board/br35/board_config.h",
    "SDK/apps/watch/include/app_config.h",
    "SDK/build/genFileList.c",
    "SDK/build/Makefile.mk",
    "SDK/cpu/br35/power/power_app.c",
    "SDK/cpu/br35/sdk_ld.c",
    "SDK/interface/system/port/br35/system_lib.ld",
}
REQUIRED_SOURCES = {
    "apps/common/debug/debug.c",
    "apps/common/debug/debug_uart_config.c",
    "apps/common/perf_counter/perf_counter.c",
    "apps/common/update/update.c",
    "apps/watch/app_main.c",
    "apps/watch/board/br35/board_e87_1542_full/board_e87_1542_full.c",
    "apps/watch/e87/e87_app.c",
    "apps/watch/e87/e87_app_target.c",
    "apps/watch/e87/e87_app_runtime.c",
    "apps/watch/e87/e87_app_core.c",
    "apps/watch/e87/e87_ui.c",
    "apps/watch/e87/e87_button_classifier.c",
    "apps/watch/e87/e87_button_fsm.c",
    "apps/watch/e87/e87_power_policy.c",
    "apps/watch/e87/e87_recovery.c",
    "apps/watch/e87/e87_ble_mode_fsm.c",
    "apps/watch/e87/e87_maintenance.c",
    "apps/watch/e87/e87_rcsp_profile.c",
    "apps/watch/e87/e87_full_platform_config.c",
    "apps/watch/log_config/lib_driver_config.c",
    "apps/watch/log_config/lib_system_config.c",
    "cpu/br35/power/power_app.c",
    "cpu/br35/setup.c",
    "cpu/config/lib_power_config.c",
    "cpu/power/msg.c",
}
REQUIRED_ARCHIVES = {
    "cpu/br35/liba/cpu.a",
    "cpu/br35/liba/system.a",
    "cpu/br35/liba/libc.a",
    "cpu/br35/liba/cfg_tool.a",
    "cpu/br35/liba/device.a",
    "cpu/br35/liba/fs.a",
    "cpu/br35/liba/printf.a",
    "cpu/br35/liba/vm.a",
}
STAGE0_SHA256 = {
    "firmware/patches/stage0/0001-e87-stage0-hooks.patch":
        "b8eeb920c3d2862a6e5737ab8890baf45ec6c40e991ecfdf4ad1658d7b9b3a35",
    "firmware/board-profiles/E87-1542-STAGE0-H.json":
        "04b6030e0c351f89b2aa6f51d1577a0ce177bdeb3583e4b8c353a3c26f8c3c43",
    "firmware/evidence/stage0/btstack-runtime-gate.json":
        "04dd12ad77138f2bde85352fe9a6888b036790ad8f7336556e27b602e33e10aa",
    "firmware/evidence/stage0/link-closure.json":
        "b4dc989996ab016a3c37799a6913fcecfc66fe9f53d60f1f33752ce7961b2dd1",
    "firmware/overlay/SDK/apps/watch/board/br35/board_e87_1542/board_e87_1542.c":
        "6dcbbf887c70fd6dd0b440fd685e6a3eed040ee10bd2e93514f1d03f56576ebd",
    "firmware/overlay/SDK/apps/watch/board/br35/board_e87_1542/board_e87_1542_cfg.h":
        "03cc492f651fcdeaccd3495f0bdc17e535a4b1656655890f81a9c3531c40f185",
    "firmware/overlay/SDK/apps/watch/e87/e87_stage0_adv.c":
        "47499d59cbf82682b6f78317fcdfe356943b049b9a236ecda4233cee1b8842ad",
    "firmware/overlay/SDK/apps/watch/e87/e87_stage0_app.c":
        "5fe3ab22d45486bab93ba274dd15aeaa9a0cc06f2f77cf26a341fc8fe61c4808",
    "firmware/overlay/SDK/apps/watch/e87/e87_stage0_ble.c":
        "0e1af38687c2475625f845b937241ae6caaaba86595e6c506edf609b3549389f",
    "firmware/overlay/SDK/apps/watch/e87/e87_stage0_platform_config.c":
        "d3f898e7bbcb5f473c130eecd5c73937db78e6642c2635e8e19097b5e2b7ce01",
    "firmware/overlay/SDK/apps/watch/include/e87/e87_stage0_adv.h":
        "9e1737a7e1045e6f7015ca1dd0ca34ca84865ca5a9765486b9c642e82f54118c",
    "firmware/overlay/SDK/apps/watch/include/e87/e87_stage0_app.h":
        "fb65768089b97f233bad265bc8412b3363a3b0b0dca0a04b2a7d6d4333c76af6",
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def patch_section(patch: str, target: str) -> str:
    marker = f"diff --git a/{target} b/{target}\n"
    start = patch.index(marker) + len(marker)
    finish = patch.find("\ndiff --git ", start)
    return patch[start:] if finish < 0 else patch[start:finish]


def added_section(patch: str, target: str) -> str:
    return "\n".join(
        line[1:]
        for line in patch_section(patch, target).splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def between(text: str, begin: str, end: str) -> str:
    start = text.index(begin) + len(begin)
    return text[start:text.index(end, start)]


class FullTargetStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.patch = read(PATCH)

    def test_stage0_inputs_remain_at_the_approved_frozen_bytes(self) -> None:
        for relative, expected in STAGE0_SHA256.items():
            with self.subTest(path=relative):
                self.assertEqual(
                    hashlib.sha256(
                        (REPO_ROOT / relative).read_bytes().replace(b"\r\n", b"\n")
                    ).hexdigest(),
                    expected,
                )

    def test_full_patch_is_separate_and_touches_only_eight_targets(self) -> None:
        targets = set(
            re.findall(r"^diff --git a/(\S+) b/\1$", self.patch, re.M)
        )
        self.assertEqual(targets, PATCH_TARGETS)
        self.assertNotIn("CONFIG_BOARD_E87_1542_STAGE0_H", self.patch)
        for target in PATCH_TARGETS:
            self.assertEqual(
                self.patch.count(f"diff --git a/{target} b/{target}"), 1
            )

    def test_profile_closes_the_substrate_scope_and_memory_contract(self) -> None:
        profile = json.loads(read(PROFILE))
        self.assertEqual(
            profile,
            {
                "schemaVersion": 2,
                "profileId": "E87-1542-FULL-RUNTIME-NORMAL-BLE-H",
                "sdkCommit": "d0167685d032d745d88fe50233302edd46941622",
                "status": "FULL_RUNTIME_NORMAL_BLE_REPIN_REQUIRED",
                "boot": {
                    "applicationTask": "app_core",
                    "explicitCalls": [
                        "app_var_init",
                        "board_init",
                        "wdt_init",
                        "e87_app_start",
                        "e87_app_dispatch_forever",
                    ],
                    "genericInitcalls": [],
                    "normalBleRuntime": "EXPLICIT_TARGET_AND_VENDOR_STACK",
                    "immutableSetupArchSeam": (
                        "RETAINED_SDFILE_SYSCFG_UNTIL_DEDICATED_SETUP_PATCH"
                    ),
                },
                "memory": {
                    "ramTop": 0x137000,
                    "updateStart": 0x136E00,
                    "reservedStart": 0x130E00,
                    "reservedEnd": 0x136E00,
                    "reservedBytes": 0x6000,
                    "bufferStart": 0x130E00,
                    "bufferEnd": 0x136260,
                    "bufferBytes": 0x5460,
                    "slackBytes": 0xBA0,
                    "minimumHeapBytes": 0x8000,
                    "psramBytes": 0,
                },
                "excludedUntilNamedIntegration": [
                    "panel",
                    "gpu-dbi",
                    "classic-bluetooth",
                    "tws",
                    "rcsp",
                    "charger",
                    "generic-initcalls",
                    "stock-app-modes",
                    "stock-ui",
                    "audio",
                    "application-filesystem-route",
                    "update-engine",
                ],
                "evidence": {
                    "mapContract": "firmware/evidence/full/link-closure.json",
                    "validator": "firmware/tools/validate-full-map.py",
                },
            },
        )

    def test_board_config_is_ui_off_and_reserves_one_serial_buffer(self) -> None:
        config = read(
            OVERLAY
            / "board/br35/board_e87_1542_full/board_e87_1542_full_cfg.h"
        )
        required = {
            "TCFG_UI_ENABLE": "0",
            "CONFIG_JL_UI_ENABLE": "0",
            "CONFIG_LVGL_UI_ENABLE": "0",
            "TCFG_TOUCH_PANEL_ENABLE": "0",
            "TCFG_APP_BT_EN": "0",
            "TCFG_USER_BLE_ENABLE": "0",
            "TCFG_USER_BT_CLASSIC_ENABLE": "0",
            "TCFG_CHARGE_ENABLE": "0",
            "TCFG_UPDATE_ENABLE": "0",
            "TCFG_PSRAM_DEV_ENABLE": "0",
            "CONFIG_LCD_BUF_STATIC_RAM_LEN": "0x6000",
            "E87_FULL_LCD_BUFFER_BYTES": "0x5460",
        }
        for name, value in required.items():
            self.assertRegex(
                config,
                re.compile(
                    rf"^#define\s+{re.escape(name)}\s+{re.escape(value)}$", re.M
                ),
                name,
            )
        for token in ("JD9855", "PA05", "PA06", "PA07", "PA12", "IO_LCD_PG"):
            self.assertNotIn(token, config)

    def test_full_source_and_archive_lists_are_exact_and_all_other_languages_empty(self) -> None:
        added = added_section(self.patch, "SDK/build/Makefile.mk")
        source_block = between(
            added,
            "# E87_FULL_REQUIRED_SOURCES_BEGIN\n",
            "# E87_FULL_REQUIRED_SOURCES_END",
        )
        sources = set(
            re.findall(r"(?:^|\s)([A-Za-z0-9_./-]+\.c)(?:\s|$)", source_block)
        )
        self.assertEqual(sources, REQUIRED_SOURCES)
        assignments = dict(
            re.findall(
                r"^(c|S|s|cpp|cc|cxx)_SRC_FILES[ \t]*:=[ \t]*(.*)$",
                added,
                re.M,
            )
        )
        self.assertEqual(
            assignments,
            {
                "c": "$(E87_FULL_REQUIRED_SOURCES)",
                "S": "",
                "s": "",
                "cpp": "",
                "cc": "",
                "cxx": "",
            },
        )
        archive_block = between(
            added,
            "# E87_FULL_FINAL_LFLAGS_BEGIN\n",
            "# E87_FULL_FINAL_LFLAGS_END",
        )
        self.assertEqual(set(re.findall(r"cpu/br35/liba/[A-Za-z0-9_]+\.a", archive_block)), REQUIRED_ARCHIVES)
        self.assertNotIn("used-symbol-file", archive_block)
        for forbidden in ("btstack.a", "btctrler.a", "gpu.a", "media.a", "update.a", "rcsp_stack.a"):
            self.assertNotIn(forbidden, archive_block)

    def test_app_core_init_does_not_copy_a_core_on_the_task_stack(self) -> None:
        source = read(OVERLAY / "e87/e87_app_core.c")
        init = source.split("bool e87_app_core_init(", 1)[1].split(
            "static bool is_fail_closed_cleanup_event", 1
        )[0]
        self.assertNotRegex(init, r"struct\s+e87_app_core\s+[A-Za-z_]")
        validation = init.index("if (core == NULL")
        mutation = init.index("memset(core, 0, sizeof(*core));")
        self.assertLess(validation, mutation)
        self.assertIn("e87_button_classifier_config_valid", init[:mutation])

    def test_app_shell_uses_only_the_exact_explicit_boot_sequence(self) -> None:
        app = read(OVERLAY / "e87/e87_app.c")
        header = read(OVERLAY / "include/e87/e87_app.h")
        self.assertLess(
            app.index('#include "app_config.h"'),
            app.index('#include "e87/e87_app.h"'),
        )
        self.assertIn("bool e87_app_start(void);", header)
        self.assertIn("void e87_app_dispatch_forever(void);", header)
        app_main = added_section(self.patch, "SDK/apps/watch/app_main.c")
        cursor = 0
        for call in (
            "app_var_init();",
            "board_init();",
            "wdt_init(WDT_APP_RUN_TIME);",
            "e87_app_start()",
            "e87_app_dispatch_forever();",
        ):
            cursor = app_main.index(call, cursor) + len(call)
        self.assertIn('{"app_core", 20, 0, 768, 768}', app_main)
        self.assertNotIn("btstack", app_main)
        self.assertNotIn("btctrler", app_main)
        combined = app + app_main
        for forbidden in (
            "do_early_initcall",
            "do_platform_initcall",
            "do_initcall",
            "do_module_initcall",
            "do_late_initcall",
            "cfg_file_parse",
            "dev_manager_init",
            "update_result_deal",
            "app_task_init",
            "btstack_init",
            "lcd_init",
            "rcsp_init",
            "charge_start",
        ):
            self.assertNotIn(forbidden, combined)

    def test_platform_policy_contains_only_consumed_boot_data_abi(self) -> None:
        platform = read(OVERLAY / "e87/e87_full_platform_config.c")
        for required in (
            "CONFIG_CPU_UNMASK_IRQ_ENABLE",
            "btif_table",
            "vm_max_page_align_size_config",
            "vm_max_sector_align_size_config",
        ):
            self.assertIn(required, platform)
        for unconsumed_bt_abi in (
            "btstack_emitter_support",
            "adt_profile_support",
        ):
            self.assertNotIn(unconsumed_bt_abi, platform)

    def test_linker_tail_has_exact_symbols_and_build_time_assertions(self) -> None:
        section = patch_section(self.patch, "SDK/cpu/br35/sdk_ld.c")
        for token in (
            "#if CONFIG_LCD_BUF_STATIC_RAM_LEN",
            "_E87_LCD_RESERVED_START = _LCD_BUF_STATIC_START;",
            "_E87_LCD_BUFFER_START = _E87_LCD_RESERVED_START;",
            "_E87_LCD_BUFFER_END = _E87_LCD_BUFFER_START + 0x5460;",
            "_E87_LCD_RESERVED_END = _LCD_BUF_STATIC_END;",
            'ASSERT(_E87_LCD_RESERVED_START == 0x130E00,',
            'ASSERT(_E87_LCD_BUFFER_END == 0x136260,',
            'ASSERT(_E87_LCD_RESERVED_END == UPDATA_BEG,',
            'ASSERT((_E87_LCD_RESERVED_END - _E87_LCD_RESERVED_START) == 0x6000,',
            'ASSERT((_E87_LCD_BUFFER_END - _E87_LCD_BUFFER_START) == 0x5460,',
            'ASSERT((_HEAP_END - _HEAP_BEGIN) >= 0x8000,',
            "ASSERT(PSRAM_SIZE == 0,",
        ):
            self.assertIn(token, section)
        self.assertIn('#ifndef CONFIG_BOARD_E87_1542_FULL_H\n #include "sdk_used_list.c"\n+#endif', section)
        for layout in ("ENTRY(_start)", "MEMORY"):
            self.assertNotRegex(section, re.compile(rf"^[+-].*{layout}", re.M))
        self.assertEqual(re.findall(r"^[+-]SECTIONS$", section, re.M), [])

    def test_full_boot_never_programs_an_unproven_pin_reset(self) -> None:
        section = patch_section(self.patch, "SDK/cpu/br35/power/power_app.c")
        self.assertIn("#ifndef CONFIG_BOARD_E87_1542_FULL_H", section)
        added = added_section(self.patch, "SDK/cpu/br35/power/power_app.c")
        self.assertNotIn("gpio_longpress_pin0_reset_config", added)
        self.assertNotIn("gpio_longpress_pin1_reset_config", added)

    def test_generic_initcall_linker_ranges_are_empty_by_construction(self) -> None:
        power = patch_section(self.patch, "SDK/cpu/br35/power/power_app.c")
        guard = "#ifndef CONFIG_BOARD_E87_1542_FULL_H"
        registration = "late_initcall(power_later_flowing);"
        guard_position = power.index(guard)
        registration_position = power.index(registration, guard_position)
        end_position = power.index("#endif", registration_position)
        self.assertLess(guard_position, registration_position)
        self.assertGreater(end_position, registration_position)
        system_linker = patch_section(
            self.patch, "SDK/interface/system/port/br35/system_lib.ld"
        )
        self.assertIn("#ifdef CONFIG_BOARD_E87_1542_FULL_H", system_linker)
        self.assertIn(
            "#define initcall e87_full_unretained_initcall", system_linker
        )
        self.assertIn(
            "#define uninitcall e87_full_unretained_uninitcall", system_linker
        )
        self.assertLess(
            system_linker.index("#define initcall"),
            system_linker.index("SECTIONS"),
        )
        self.assertIn(
            "index 844e141c4eb8877430fbbf63eb152a22f0def65e"
            "..60fd413626ede05f20bc0eaea848179c89e878f4 100644",
            system_linker,
        )
        self.assertEqual(
            [
                line[1:]
                for line in system_linker.splitlines()
                if line.startswith("+") and not line.startswith("+++")
            ],
            [
                "#ifdef CONFIG_BOARD_E87_1542_FULL_H",
                "#define initcall e87_full_unretained_initcall",
                "#define uninitcall e87_full_unretained_uninitcall",
                "#endif",
            ],
        )
        self.assertEqual(
            [
                line
                for line in system_linker.splitlines()
                if line.startswith("-") and not line.startswith("---")
            ],
            [],
        )
        linker = patch_section(self.patch, "SDK/cpu/br35/sdk_ld.c")
        self.assertNotIn("/DISCARD/ :", linker)
        for assertion in (
            "ASSERT(_initcall_begin == _initcall_end,",
            "ASSERT(_early_initcall_begin == _early_initcall_end,",
            "ASSERT(_late_initcall_begin == _late_initcall_end,",
            "ASSERT(_platform_initcall_begin == _platform_initcall_end,",
            "ASSERT(_module_initcall_begin == _module_initcall_end,",
            "ASSERT(platform_uninitcall_begin == platform_uninitcall_end,",
        ):
            self.assertIn(assertion, linker)

    def test_filelist_and_app_config_route_only_the_full_macro(self) -> None:
        generated = added_section(self.patch, "SDK/build/genFileList.c")
        self.assertIn("#ifdef CONFIG_BOARD_E87_1542_FULL_H", generated)
        self.assertIn("apps/watch/e87/e87_app.c", generated)
        self.assertNotIn("e87_stage0", generated)
        app_config = patch_section(self.patch, "SDK/apps/watch/include/app_config.h")
        self.assertIn("#if TCFG_UI_ENABLE", app_config)
        self.assertIn('#include "lcd/lcd_conf.h"', app_config)


if __name__ == "__main__":
    unittest.main()
