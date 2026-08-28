#!/usr/bin/env python3
"""Static target policy for the deliberately tiny Stage 0-H image."""

from __future__ import annotations

from pathlib import Path
import re
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
PATCH = REPO_ROOT / "firmware/patches/stage0/0001-e87-stage0-hooks.patch"
OVERLAY = REPO_ROOT / "firmware/overlay/SDK/apps/watch"

PATCH_TARGETS = {
    "SDK/apps/watch/board/br35/board_config.h",
    "SDK/apps/watch/include/app_config.h",
    "SDK/apps/watch/app_main.c",
    "SDK/build/genFileList.c",
    "SDK/build/Makefile.mk",
    "SDK/cpu/br35/sdk_ld.c",
    "SDK/cpu/br35/power/power_app.c",
}
REQUIRED_TARGET_SOURCES = {
    "apps/common/debug/debug.c",
    "apps/common/debug/debug_uart_config.c",
    "apps/common/perf_counter/perf_counter.c",
    "apps/common/update/update.c",
    "apps/watch/app_main.c",
    "apps/watch/board/br35/board_e87_1542/board_e87_1542.c",
    "apps/watch/e87/e87_stage0_adv.c",
    "apps/watch/e87/e87_stage0_app.c",
    "apps/watch/e87/e87_stage0_ble.c",
    "apps/watch/e87/e87_stage0_platform_config.c",
    "apps/watch/log_config/app_config.c",
    "apps/watch/log_config/lib_btctrler_config.c",
    "apps/watch/log_config/lib_btstack_config.c",
    "apps/watch/log_config/lib_driver_config.c",
    "apps/watch/log_config/lib_system_config.c",
    "cpu/br35/setup.c",
    "cpu/br35/power/power_app.c",
    "cpu/config/lib_power_config.c",
    "cpu/power/msg.c",
}
REQUIRED_TARGET_ARCHIVES = {
    "cpu/br35/liba/cpu.a",
    "cpu/br35/liba/system.a",
    "cpu/br35/liba/btstack.a",
    "cpu/br35/liba/btctrler.a",
    "cpu/br35/liba/libc.a",
    "cpu/br35/liba/cbuf.a",
    "cpu/br35/liba/cfg_tool.a",
    "cpu/br35/liba/crypto_toolbox_Osize.a",
    "cpu/br35/liba/fs.a",
    "cpu/br35/liba/lib_ccm_cipher.a",
    "cpu/br35/liba/vm.a",
}
FORBIDDEN_TARGET_SOURCES = {
    "apps/watch/mode/bt/bt.c",
    "apps/watch/mode/bt/bt_event_func.c",
    "apps/watch/ble/bt_ble.c",
    "apps/watch/ble/ble_adv.c",
    "apps/watch/message/adapter/btstack.c",
    "apps/common/config/bt_profile_config.c",
    "apps/watch/e87/e87_renderer.c",
    "apps/watch/e87/e87_button_classifier.c",
    "apps/watch/e87/e87_button_fsm.c",
    "apps/watch/e87/e87_recovery.c",
    "firmware/generated/e87_assets.c",
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def added_section(patch: str, target: str) -> str:
    section = patch_section(patch, target)
    return "\n".join(
        line[1:]
        for line in section.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def patch_section(patch: str, target: str) -> str:
    marker = f"diff --git a/{target} b/{target}\n"
    start = patch.index(marker) + len(marker)
    next_diff = patch.find("\ndiff --git ", start)
    return patch[start:] if next_diff < 0 else patch[start:next_diff]


def between(text: str, start: str, end: str) -> str:
    begin = text.index(start) + len(start)
    finish = text.index(end, begin)
    return text[begin:finish]


class Stage0StaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.patch = read(PATCH)

    def test_patch_touches_only_the_seven_frozen_sdk_targets(self) -> None:
        targets = set(
            re.findall(r"^diff --git a/(\S+) b/\1$", self.patch, re.M)
        )
        self.assertEqual(targets, PATCH_TARGETS)
        for target in PATCH_TARGETS:
            self.assertEqual(self.patch.count(f"diff --git a/{target} b/{target}"), 1)

    def test_makefile_requires_the_exact_external_build_tag_macro(self) -> None:
        added = added_section(self.patch, "SDK/build/Makefile.mk")
        self.assertIn("ifeq ($(strip $(E87_STAGE0_BUILD_TAG)),)", added)
        self.assertIn("$(error E87_STAGE0_BUILD_TAG must be 8 uppercase hex digits)", added)
        self.assertIn(
            "E87_STAGE0_BUILD_TAG_CANON := $(strip $(E87_STAGE0_BUILD_TAG))",
            added,
        )
        self.assertIn("ifneq ($(E87_STAGE0_BUILD_TAG_INVALID),)", added)
        self.assertIn(
            "ifneq ($(E87_STAGE0_BUILD_TAG_LENGTH),xxxxxxxx)", added
        )
        self.assertIn(
            "DEFINES += -DE87_STAGE0_BUILD_TAG_HEX=0x$(E87_STAGE0_BUILD_TAG_CANON)u",
            added,
        )
        self.assertNotIn("__DATE__", added)
        self.assertNotIn("__TIME__", added)
        self.assertNotIn("git rev-parse", added)

    def test_app_config_only_includes_lcd_configuration_when_ui_is_enabled(self) -> None:
        marker = "diff --git a/SDK/apps/watch/include/app_config.h "
        start = self.patch.index(marker)
        finish = self.patch.find("\ndiff --git ", start + 1)
        section = self.patch[start:] if finish < 0 else self.patch[start:finish]
        self.assertRegex(
            section,
            re.compile(
                r"^\+#if TCFG_UI_ENABLE\n #include \"lcd/lcd_conf\.h\"\n\+#endif$",
                re.M,
            ),
        )

    def test_makefile_final_source_list_is_the_closed_stage0_allowlist(self) -> None:
        added = added_section(self.patch, "SDK/build/Makefile.mk")
        block = between(
            added,
            "# E87_STAGE0_REQUIRED_SOURCES_BEGIN\n",
            "# E87_STAGE0_REQUIRED_SOURCES_END",
        )
        actual = set(re.findall(r"(?:^|\s)([A-Za-z0-9_./-]+\.c)(?:\s|$)", block))
        self.assertEqual(actual, REQUIRED_TARGET_SOURCES)
        self.assertIn("c_SRC_FILES := $(E87_STAGE0_REQUIRED_SOURCES)", added)
        for forbidden in FORBIDDEN_TARGET_SOURCES:
            self.assertNotIn(forbidden, block)
        assignments = dict(
            re.findall(
                r"^(c|S|s|cpp|cc|cxx)_SRC_FILES[ \t]*:=[ \t]*(.*)$",
                added, re.M,
            )
        )
        self.assertEqual(
            assignments,
            {
                "c": "$(E87_STAGE0_REQUIRED_SOURCES)",
                "S": "",
                "s": "",
                "cpp": "",
                "cc": "",
                "cxx": "",
            },
        )

    def test_stage0_link_does_not_force_the_stock_used_symbol_roots(self) -> None:
        option = "--plugin-opt=-used-symbol-file=apps/watch/sdk_used_list.used"
        self.assertIn(f"-\t{option} \\", self.patch)
        self.assertNotIn(f"+\t{option} \\", self.patch)
        added = added_section(self.patch, "SDK/build/Makefile.mk")
        self.assertNotIn(option, added)

    def test_stage0_linker_keeps_layout_but_omits_generated_extern_roots(self) -> None:
        self.assertIn(
            "diff --git a/SDK/cpu/br35/sdk_ld.c b/SDK/cpu/br35/sdk_ld.c\n",
            self.patch,
        )
        section = patch_section(self.patch, "SDK/cpu/br35/sdk_ld.c")
        self.assertRegex(
            section,
            re.compile(
                r"^ EXTERN\(\n"
                r" _start\n"
                r"\+#ifndef CONFIG_BOARD_E87_1542_STAGE0_H\n"
                r" #include \"sdk_used_list\.c\"\n"
                r"\+#endif\n"
                r" \);$",
                re.M,
            ),
        )
        self.assertEqual(section.count('#include "sdk_used_list.c"'), 1)
        for vendor_layout_token in ("ENTRY(_start)", "MEMORY", "SECTIONS"):
            self.assertNotRegex(
                section,
                re.compile(
                    rf"^[+-].*{re.escape(vendor_layout_token)}", re.M
                ),
                vendor_layout_token,
            )

    def test_stage0_final_link_flags_start_from_the_exact_core_archives(self) -> None:
        added = added_section(self.patch, "SDK/build/Makefile.mk")
        self.assertIn("# E87_STAGE0_FINAL_LFLAGS_BEGIN\n", added)
        block = between(
            added,
            "# E87_STAGE0_FINAL_LFLAGS_BEGIN\n",
            "# E87_STAGE0_FINAL_LFLAGS_END",
        )
        actual = set(
            re.findall(r"(?:^|\s)([A-Za-z0-9_./+-]+\.a)(?:\s|$)", block)
        )
        self.assertEqual(actual, REQUIRED_TARGET_ARCHIVES)
        self.assertIn("LFLAGS := \\", block)
        self.assertIn("--start-group", block)
        self.assertIn("--end-group", block)
        self.assertNotIn("--whole-archive", block)
        for forbidden in (
            "rcsp_stack.a",
            "media.a",
            "aec.a",
            "quickjs.a",
            "jlui.a",
            "lvgl_v8.a",
            "upay_t_head_v2",
            "libstdc++",
        ):
            self.assertNotIn(forbidden, block)

    def test_stage0_platform_policy_tu_is_data_only_and_owned(self) -> None:
        policy = OVERLAY / "e87/e87_stage0_platform_config.c"
        self.assertTrue(policy.is_file(), policy)
        source = read(policy)
        self.assertIn("const int CONFIG_CPU_UNMASK_IRQ_ENABLE = 0;", source)
        self.assertIn("const u8 btstack_emitter_support = 0;", source)
        self.assertIn("const u8 adt_profile_support = 0;", source)
        self.assertIn(
            "const struct btif_item btif_table[] = {{0, 0}};", source
        )
        self.assertIn(
            "const int vm_max_page_align_size_config = TCFG_VM_SIZE;", source
        )
        self.assertIn(
            "const int vm_max_sector_align_size_config = TCFG_VM_SIZE;", source
        )
        self.assertNotIn("config_stack_modules", source)
        self.assertNotRegex(source, re.compile(r"^[A-Za-z_].*\([^;]*\)\s*\{", re.M))

    def test_stage0_power_flow_does_not_program_an_unproven_longpress_pin(self) -> None:
        target = "SDK/cpu/br35/power/power_app.c"
        self.assertIn(f"diff --git a/{target} b/{target}\n", self.patch)
        section = patch_section(self.patch, target)
        self.assertRegex(
            section,
            re.compile(
                r"^\+#ifndef CONFIG_BOARD_E87_1542_STAGE0_H\n"
                r"     gpio_longpress_pin0_reset_config\(PINR_DEFAULT_IO, 0, 0, 1, 1\);\n"
                r"\+#endif$",
                re.M,
            ),
        )


    def test_generated_file_list_has_a_closed_stage0_branch(self) -> None:
        added = added_section(self.patch, "SDK/build/genFileList.c")
        block = between(
            added,
            "#define E87_STAGE0_GENERATED_LIST_BEGIN 1\n",
            "#define E87_STAGE0_GENERATED_LIST_END 1",
        )
        actual = set(re.findall(r"([A-Za-z0-9_./-]+\.c)", block))
        self.assertEqual(
            actual,
            {
                "apps/watch/e87/e87_stage0_adv.c",
                "apps/watch/e87/e87_stage0_app.c",
                "apps/watch/e87/e87_stage0_ble.c",
            },
        )
        for forbidden in FORBIDDEN_TARGET_SOURCES:
            self.assertNotIn(forbidden, block)

    def test_app_main_has_only_the_three_required_tasks_and_minimal_boot_calls(self) -> None:
        added = added_section(self.patch, "SDK/apps/watch/app_main.c")
        branch = between(
            added,
            "#define E87_STAGE0_APP_MAIN_BEGIN 1\n",
            "#define E87_STAGE0_APP_MAIN_END 1",
        )
        self.assertEqual(
            re.findall(r'\{"([A-Za-z0-9_]+)"', branch),
            ["app_core", "btctrler", "btstack"],
        )
        for required in (
            "app_var_init();",
            "board_init();",
            "wdt_init(WDT_APP_RUN_TIME);",
            "if (!e87_stage0_app_start())",
        ):
            self.assertIn(required, branch)
        for forbidden in (
            "cfg_file_parse",
            "key_driver_init",
            "dev_manager_init",
            "update_result_deal",
            "UI_INIT",
            "TP_INIT",
            "data_small_file_init",
            "sport_health_manager_init",
            "app_mode_switch_handler",
            "do_early_initcall",
            "do_platform_initcall",
            "do_initcall",
            "do_module_initcall",
            "do_late_initcall",
            "app_version_check",
        ):
            self.assertNotIn(forbidden, branch)
        self.assertRegex(
            branch,
            re.compile(
                r"int eSystemConfirmStopStatus\(void\)\n"
                r"\{\n"
                r"    return 0;\n"
                r"\}",
                re.M,
            ),
        )

    def test_app_config_disables_every_externally_visible_stock_route(self) -> None:
        added = added_section(self.patch, "SDK/apps/watch/include/app_config.h")
        expected = {
            "TCFG_APP_BT_EN": "1",
            "TCFG_USER_BLE_ENABLE": "1",
            "TCFG_USER_BT_CLASSIC_ENABLE": "0",
            "TCFG_USER_TWS_ENABLE": "0",
            "TCFG_BT_AI_ENABLE": "0",
            "BT_AI_SEL_PROTOCOL": "0",
            "RCSP_MODE": "RCSP_MODE_OFF",
            "TCFG_BT_BLE_ADV_ENABLE": "1",
            "TCFG_UI_ENABLE": "0",
            "CONFIG_JL_UI_ENABLE": "0",
            "CONFIG_LVGL_UI_ENABLE": "0",
            "TCFG_TOUCH_PANEL_ENABLE": "0",
            "TCFG_ADKEY_ENABLE": "0",
            "TCFG_IOKEY_ENABLE": "0",
            "TCFG_RDEC_KEY_ENABLE": "0",
            "TCFG_DATA_STORAGE_ENABLE": "0",
            "TCFG_SPORT_HEALTH_ENABLE": "0",
            "TCFG_DEV_MANAGER_ENABLE": "0",
            "CONFIG_FATFS_ENABLE": "0",
            "TCFG_UPDATE_ENABLE": "0",
            "TCFG_CFG_TOOL_ENABLE": "0",
            "PRODUCT_TEST_ENABLE": "0",
            "TCFG_CHARGE_ENABLE": "0",
            "TCFG_APP_RTC_EN": "0",
            "TCFG_APP_MUSIC_EN": "0",
            "TCFG_APP_PC_EN": "0",
            "TCFG_APP_FM_EN": "0",
            "TCFG_APP_LINEIN_EN": "0",
            "TCFG_APP_RECORD_EN": "0",
            "TCFG_AUDIO_DAC_ENABLE": "0",
            "TCFG_AUDIO_ADC_ENABLE": "0",
        }
        actual = dict(re.findall(r"^#define\s+([A-Z0-9_]+)\s+([^\s/]+)", added, re.M))
        for name, value in expected.items():
            self.assertEqual(actual.get(name), value, name)

    def test_board_overlay_has_no_speculative_hardware_assignment(self) -> None:
        board = read(
            OVERLAY / "board/br35/board_e87_1542/board_e87_1542.c"
        )
        config = read(
            OVERLAY / "board/br35/board_e87_1542/board_e87_1542_cfg.h"
        )
        combined = board + "\n" + config
        self.assertIn("#define WDT_APP_INIT_TIME WDT_16S", config)
        self.assertIn("#define WDT_APP_RUN_TIME WDT_LRC_4S", config)
        self.assertIn("#define TCFG_UPDATE_ENABLE 0", config)
        self.assertNotIn("#define CONFIG_UPDATE_ENABLE", config)
        for forbidden in (
            "IO_PORT",
            "PB07",
            "PB08",
            "PINR",
            "gpadc",
            "adkey",
            "iokey",
            "lcd_",
            "LCD_",
            "GC9B71",
            "JD9855",
            "320",
            "386",
            "368",
            "charge",
        ):
            self.assertNotIn(forbidden, combined)

    def test_ble_override_is_once_only_and_submits_the_exact_command_order(self) -> None:
        source = read(OVERLAY / "e87/e87_stage0_ble.c")
        self.assertEqual(len(re.findall(r"^void bt_ble_init\(void\)", source, re.M)), 1)
        self.assertNotIn("weak", source.lower())
        self.assertIn("const int config_stack_modules = BT_BTSTACK_LE_ADV;", source)
        self.assertIn("#if BT_BTSTACK_LE_ADV != 2", source)
        self.assertIn("static bool initialization_attempted;", source)
        self.assertIn("static uint8_t advertisement[29];", source)
        self.assertLess(source.index("initialization_attempted = true;"),
                        source.index("le_controller_set_random_mac"))
        body = source[source.index("void bt_ble_init(void)") :]
        commands = re.findall(
            r"ble_user_cmd_prepare\(\s*(BLE_CMD_[A-Z0-9_]+)", body
        )
        self.assertEqual(
            commands,
            [
                "BLE_CMD_SET_HCI_CFG",
                "BLE_CMD_ADV_PARAM",
                "BLE_CMD_ADV_DATA",
                "BLE_CMD_RSP_DATA",
                "BLE_CMD_ADV_ENABLE",
            ],
        )
        ordered = [
            "le_controller_set_random_mac",
            "ble_user_cmd_prepare(BLE_CMD_SET_HCI_CFG",
            "ble_user_cmd_prepare(BLE_CMD_ADV_PARAM",
            "ble_user_cmd_prepare(BLE_CMD_ADV_DATA",
            "ble_user_cmd_prepare(BLE_CMD_RSP_DATA",
            "ble_user_cmd_prepare(BLE_CMD_ADV_ENABLE",
        ]
        positions = [body.index(token) for token in ordered]
        self.assertEqual(positions, sorted(positions))
        for required in (
            "HCI_CFG_OWN_ADDRESS_TYPE",
            "E87_STAGE0_OWN_ADDRESS_TYPE_RANDOM",
            "BLE_CMD_ADV_PARAM",
            "E87_STAGE0_ADV_INTERVAL_UNITS",
            "E87_STAGE0_ADV_TYPE_NONCONN_IND",
            "E87_STAGE0_ADV_CHANNEL_MAP",
            "BLE_CMD_ADV_DATA",
            "E87_STAGE0_ADV_DATA_LENGTH",
            "BLE_CMD_RSP_DATA",
            "scan_response_length",
            "scan_response",
            "BLE_CMD_ADV_ENABLE",
        ):
            self.assertIn(required, body)
        self.assertNotIn("APP_MSG_HANDLER", source)
        self.assertNotIn("BT_STATUS_INIT_OK", source)

    def test_clock_uuid_address_and_stack_start_are_fail_closed_and_ordered(self) -> None:
        source = read(OVERLAY / "e87/e87_stage0_app.c")
        ordered = [
            'clk_get("sys")',
            "bt_pll_para(TCFG_CLOCK_OSC_HZ, system_clock, 0, 0)",
            "tzflash_get_uuid()",
            "e87_stage0_derive_static_random_address",
            "btstack_init()",
        ]
        positions = [source.index(token) for token in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("if (system_clock == 0U)", source)
        self.assertIn("if (uuid == NULL)", source)
        self.assertIn("return false;", source)
        for forbidden in (
            "syscfg",
            "vm_",
            "random32",
            "rand(",
            "cfg_file_parse",
            "key_driver",
            "PINR",
            "gpadc",
            "lcd",
            "update_mode",
            "update_result",
            "rcsp",
        ):
            self.assertNotIn(forbidden, source.lower())

    def test_stage0_owns_the_exact_archive_ready_tuple_adapter(self) -> None:
        source = read(OVERLAY / "e87/e87_stage0_app.c")
        self.assertEqual(
            len(re.findall(r"^void bt_event_update_to_user\(", source, re.M)), 1
        )
        self.assertIn("static bool stack_ready_posted;", source)
        self.assertIn("address != NULL", source)
        self.assertIn("type != UINT32_C(0x434F4E00)", source)
        self.assertIn("event != UINT8_C(3)", source)
        self.assertIn("value != UINT32_C(50)", source)
        self.assertIn("E87_STAGE0_PRIVATE_STACK_READY", source)
        self.assertLess(
            source.index("stack_ready_posted = true;"),
            source.index('os_taskq_post_type("app_core"'),
        )
        self.assertIn(
            "if (message[0] == E87_STAGE0_PRIVATE_STACK_READY && !ready_consumed)",
            source,
        )
        for forbidden in (
            "MSG_FROM_BT_STACK",
            "BT_STATUS_INIT_OK",
            "APP_MSG_HANDLER",
            "for_each_app_msg_handler",
        ):
            self.assertNotIn(forbidden, source)

    def test_tx_power_is_not_applied_by_stage0(self) -> None:
        sources = "\n".join(
            read(path)
            for path in sorted((OVERLAY / "e87").glob("e87_stage0_*.c"))
        )
        patch_added = "\n".join(
            added_section(self.patch, target)
            for target in set(
                re.findall(r"^diff --git a/(\S+) b/\1$", self.patch, re.M)
            )
        )
        for forbidden in (
            "ble_op_set_tx_power",
            "ble_op_set_adv_tx_power",
            "TCFG_BT_BLE_TX_POWER",
        ):
            self.assertNotIn(forbidden, sources)
            self.assertNotIn(forbidden, patch_added)

    def test_advertising_code_contains_no_connectable_or_profile_surface(self) -> None:
        sources = "\n".join(
            read(path)
            for path in sorted((OVERLAY / "e87").glob("e87_stage0_*.c"))
        )
        for forbidden in (
            "ADV_IND",
            "ADV_DIRECT_IND",
            "ATT_OP_",
            "GATT_",
            "SM_EVENT",
            "pairing",
            "bond",
            "profile_init",
            "update_mode",
            "RCSP",
        ):
            self.assertNotIn(forbidden, sources)


if __name__ == "__main__":
    unittest.main()
