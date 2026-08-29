#!/usr/bin/env python3
"""Static contract for the E87-owned BR35 battery/charge boundary."""

from __future__ import annotations

import json
from pathlib import Path
import re
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SDK_LOCK = REPO_ROOT / "firmware/locks/sdk.lock.json"
GPADC_EVIDENCE = REPO_ROOT / "firmware/evidence/charge/gpadc-init.json"
TARGET = REPO_ROOT / (
    "firmware/overlay/SDK/apps/watch/e87/e87_br35_battery_charge.c"
)
TARGET_HEADER = REPO_ROOT / (
    "firmware/overlay/SDK/apps/watch/include/e87/e87_br35_battery_charge.h"
)
BRIDGE = REPO_ROOT / "firmware/overlay/SDK/apps/watch/e87/e87_charge_bridge.c"
BATTERY_SAMPLER = REPO_ROOT / (
    "firmware/overlay/SDK/apps/watch/e87/e87_battery_sampler.c"
)
POLICY = REPO_ROOT / "firmware/target/e87-full-source-policy.json"
OVERLAY = REPO_ROOT / "firmware/overlay/SDK/apps/watch/e87"

PINNED_SDK_COMMIT = "d0167685d032d745d88fe50233302edd46941622"
PINNED_SDK_TREE = "854734595be49510aca5afb89f5885e8bce6a00f"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: Path) -> dict[str, object]:
    value = json.loads(read(path), object_pairs_hook=reject_duplicate_keys)
    if not isinstance(value, dict):
        raise AssertionError(f"{path} root must be an object")
    return value


def function_body(source: str, name: str) -> str:
    """Return a simple C function body; target functions must not nest braces."""
    match = re.search(rf"\b{re.escape(name)}\s*\([^;]*?\)\s*\{{", source, re.S)
    if match is None:
        raise AssertionError(f"missing function: {name}")
    start = match.end()
    depth = 1
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index]
    raise AssertionError(f"unterminated function: {name}")


def braced_block_after(source: str, pattern: str) -> str:
    match = re.search(pattern, source, re.S)
    if match is None:
        raise AssertionError(f"missing block: {pattern}")
    brace = source.find("{", match.end())
    if brace < 0:
        raise AssertionError(f"missing opening brace: {pattern}")
    depth = 1
    for index in range(brace + 1, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1:index]
    raise AssertionError(f"unterminated block: {pattern}")


def assert_in_order(test: unittest.TestCase, text: str, *tokens: str) -> None:
    position = -1
    for token in tokens:
        next_position = text.find(token, position + 1)
        test.assertGreater(next_position, position, token)
        position = next_position


class BatteryChargeTargetStaticTests(unittest.TestCase):
    def test_pinned_sdk_identity_is_exact(self) -> None:
        lock = read_json(SDK_LOCK)
        sdk = lock["sdk"]
        self.assertEqual(sdk["commit"], PINNED_SDK_COMMIT)
        self.assertEqual(sdk["tree"], PINNED_SDK_TREE)

    def test_required_target_boundaries_exist(self) -> None:
        self.assertTrue(TARGET.is_file(), TARGET)
        self.assertTrue(TARGET_HEADER.is_file(), TARGET_HEADER)
        self.assertTrue(BRIDGE.is_file(), BRIDGE)
        self.assertTrue(BATTERY_SAMPLER.is_file(), BATTERY_SAMPLER)
        self.assertTrue(POLICY.is_file(), POLICY)
        self.assertTrue(GPADC_EVIDENCE.is_file(), GPADC_EVIDENCE)

    def test_adc_init_registration_evidence_is_exact_and_hash_pinned(self) -> None:
        self.assertEqual(
            read_json(GPADC_EVIDENCE),
            {
                "schemaVersion": 1,
                "evidenceId": "E87-BR35-GPADC-INIT",
                "sdkCommit": PINNED_SDK_COMMIT,
                "sdkTree": PINNED_SDK_TREE,
                "archive": {
                    "path": "SDK/cpu/br35/liba/cpu.a",
                    "sha256": (
                        "787b6fc0913a0a8a634ee8c7606d5e4a68dc5604d8feacf806fd60dc1e2fc8ca"
                    ),
                },
                "member": {
                    "name": "gpadc.c.o",
                    "sha256": (
                        "82502b6dfb7c74c8261c9b640b6d11603ee084e1d895734c02bd857e0384be3b"
                    ),
                },
                "ir": {
                    "command": "clang -x ir -S -emit-llvm <member> -o <output>",
                    "clangVersion": "4.0.1",
                    "clangSha256": (
                        "42b94f9e11140b0fcab8f807b2872ad245b8eeca03a2d792f8706c5a3a35d34c"
                    ),
                    "sha256": (
                        "497e7cbb4ee0cfc955245ed5bf993f6febec07218cd31a528ee8d995a7b85ccf"
                    ),
                },
                "registration": {
                    "owner": "adc_init",
                    "call": "adc_add_sample_ch(i32 131846)",
                    "voltageModeCall": "adc_set_voltage_mode(i32 131846, i32 1)",
                    "channelToken": "AD_CH_PMU_VBAT",
                    "channelValue": "0x00020306",
                },
            },
        )

    def test_irq_guards_have_hardware_masks_and_compiler_barriers(self) -> None:
        source = read(TARGET)
        self.assertIn("_Static_assert(CPU_CORE_NUM == 1", source)
        self.assertIn("_Static_assert(CPU_INT_NESTING == 2", source)
        self.assertRegex(
            source,
            re.compile(
                r"#define\s+E87_COMPILER_BARRIER\(\)\s+"
                r"__asm__\s+volatile\s*\(\s*\"\"\s*:::"
                r"\s*\"memory\"\s*\)",
                re.S,
            ),
        )

        save = function_body(source, "e87_irq_save")
        self.assertEqual(save.count("E87_COMPILER_BARRIER()"), 2)
        self.assertEqual(save.count("int_cli()"), 1)
        assert_in_order(
            self,
            save,
            "E87_COMPILER_BARRIER()",
            "int_cli()",
            "E87_COMPILER_BARRIER()",
        )

        restore = function_body(source, "e87_irq_restore")
        self.assertEqual(restore.count("E87_COMPILER_BARRIER()"), 2)
        self.assertEqual(restore.count("int_sti(saved)"), 1)
        assert_in_order(
            self,
            restore,
            "E87_COMPILER_BARRIER()",
            "int_sti(saved)",
            "E87_COMPILER_BARRIER()",
        )

        bridge = read(BRIDGE)
        self.assertNotIn("int_cli()", bridge)
        self.assertNotIn("int_sti(", bridge)
        for function in (
            "e87_charge_bridge_capture",
            "e87_charge_bridge_ack_wake",
            "e87_charge_bridge_poll_app",
        ):
            body = function_body(bridge, function)
            assert_in_order(self, body, "critical_enter", "critical_exit")

        binding = braced_block_after(
            source,
            r"static\s+const\s+struct\s+e87_charge_bridge_port\s+"
            r"e87_br35_charge_bridge_port\s*=",
        )
        self.assertIn(".critical_enter = e87_irq_save", binding)
        self.assertIn(".critical_exit = e87_irq_restore", binding)
        self.assertIn(".read_driver_online = e87_read_driver_online", binding)
        self.assertIn(".post_wake = e87_post_wake", binding)
        for private_field in (
            "private_fifo",
            "private_head",
            "private_tail",
            "private_count",
            "private_wake_pending",
            "private_fault_online_raw",
            "private_fault_pending",
        ):
            self.assertNotIn(private_field, source)

    def test_online_capture_is_inside_the_append_transaction(self) -> None:
        bridge = read(BRIDGE)
        body = function_body(bridge, "e87_charge_bridge_capture")
        assert_in_order(
            self,
            body,
            "critical_enter",
            "read_driver_online",
            "private_fifo",
            "critical_exit",
        )
        self.assertNotRegex(body, re.compile(r"driver_online_raw\s*=\s*event"))

    def test_battery_sampler_uses_init_owner_then_eight_blocking_epochs(self) -> None:
        source = read(TARGET)
        init = function_body(source, "e87_br35_battery_init")
        self.assertEqual(init.count("adc_init()"), 1)
        self.assertNotIn("adc_add_sample_ch", source)

        target_reader = function_body(source, "e87_read_quarter_mv")
        self.assertEqual(
            target_reader.count("adc_get_voltage_blocking(AD_CH_PMU_VBAT)"), 1
        )
        self.assertNotRegex(target_reader, re.compile(r"\badc_get_voltage\s*\("))

        target_sample = function_body(source, "e87_br35_battery_sample_full_mv")
        self.assertEqual(
            target_sample.count("e87_battery_sampler_sample_full_mv"), 1
        )

        sample = function_body(
            read(BATTERY_SAMPLER), "e87_battery_sampler_sample_full_mv"
        )
        loop = braced_block_after(
            sample,
            r"for\s*\([^;]*;\s*index\s*<\s*E87_BATTERY_SAMPLE_COUNT\s*;"
            r"[^)]*index[^)]*\)",
        )
        self.assertEqual(loop.count("read_quarter_mv"), 1)
        self.assertEqual(loop.count("e87_battery_full_mv_from_quarter_mv"), 1)
        self.assertIn("full_mv_samples[index]", loop)
        assert_in_order(self, loop,
            "read_quarter_mv",
            "e87_battery_full_mv_from_quarter_mv",
        )
        self.assertGreater(
            sample.find("e87_battery_filter_full_mv"), sample.find(loop)
        )
        self.assertIn(
            "_Static_assert(AD_CH_PMU_VBAT_DIV == E87_BATTERY_QUARTER_DIVISOR",
            source,
        )

    def test_sdk_event_hook_is_one_exact_mapping_owner(self) -> None:
        definitions = []
        for path in OVERLAY.glob("*.c"):
            source = read(path)
            if re.search(r"\bvoid\s+charge_event_to_user\s*\(\s*u8\s+event\s*\)\s*\{", source):
                definitions.append(path.relative_to(REPO_ROOT).as_posix())
        self.assertEqual(
            definitions,
            ["firmware/overlay/SDK/apps/watch/e87/e87_br35_battery_charge.c"],
        )

        body = function_body(read(TARGET), "charge_event_to_user")
        for event in (
            "CHARGE_EVENT_CHARGE_START",
            "CHARGE_EVENT_CHARGE_CLOSE",
            "CHARGE_EVENT_CHARGE_FULL",
            "CHARGE_EVENT_LDO5V_KEEP",
            "CHARGE_EVENT_LDO5V_IN",
            "CHARGE_EVENT_LDO5V_OFF",
        ):
            self.assertEqual(body.count(f"case {event}:"), 1)
        self.assertIn("default:", body)
        self.assertIn("E87_CHARGE_EVENT_UNSUPPORTED", body)
        self.assertNotRegex(body, re.compile(r"event\s*[<>]=?"))
        self.assertEqual(body.count("e87_charge_bridge_capture"), 1)
        for forbidden in (
            "charge_start(",
            "charge_close(",
            "e87_charge_adapter_step(",
            "publish",
            "malloc(",
            "printf(",
            "cpu_reset(",
            "power_set_soft_poweroff(",
            "os_taskq_",
            "ldoin_wakeup_isr(",
            "adc_",
        ):
            self.assertNotIn(forbidden, body)

    def test_dispatcher_has_coalesced_capacity_one_wake_and_bounded_polling(self) -> None:
        source = read(TARGET)
        self.assertIn("_Static_assert(sizeof(int) == 4", source)
        self.assertRegex(
            source,
            re.compile(
                r"#define\s+E87_CHARGE_WAKE_QUEUE_BYTES\s+"
                r"\(\(int\)sizeof\(int\)\)"
            ),
        )
        self.assertIn("E87_CHARGE_POLL_MAX_TICKS 10", source)
        wake = function_body(source, "e87_post_wake")
        post_pattern = re.compile(
            r"os_taskq_post_type\s*\(\s*E87_CHARGE_DISPATCHER_TASK\s*,\s*"
            r"E87_CHARGE_WAKE_TYPE\s*,\s*0\s*,\s*NULL\s*\)"
        )
        self.assertEqual(len(post_pattern.findall(wake)), 1)
        self.assertRegex(wake, re.compile(r"return\s+" + post_pattern.pattern))
        loop = function_body(source, "e87_br35_charge_dispatcher_run")
        self.assertRegex(loop, re.compile(r"\bint\s+wake_words\s*\[\s*1\s*\]"))
        self.assertRegex(loop, re.compile(r"\bwhile\s*\(\s*1\s*\)"))
        self.assertEqual(loop.count("e87_charge_bridge_poll_app"), 2)
        assert_in_order(
            self,
            loop,
            "e87_charge_bridge_poll_app",
            "os_taskq_pend_timeout(NULL, wake_words, 1, E87_CHARGE_POLL_MAX_TICKS)",
            "e87_charge_bridge_ack_wake",
            "e87_charge_bridge_poll_app",
        )
        self.assertIn("E87_CHARGE_WAKE_TYPE", loop)
        self.assertIn("OS_TASKQ", loop)
        self.assertIn("OS_TIMEOUT", loop)
        self.assertIn("e87_charge_bridge_note_queue_fault", loop)

        create = function_body(source, "e87_br35_charge_dispatcher_start")
        self.assertRegex(
            create,
            re.compile(
                r"os_task_create\s*\(\s*e87_br35_charge_dispatcher_run\s*,\s*"
                r"NULL\s*,\s*E87_CHARGE_DISPATCHER_PRIORITY\s*,\s*"
                r"E87_CHARGE_DISPATCHER_STACK_WORDS\s*,\s*"
                r"E87_CHARGE_WAKE_QUEUE_BYTES\s*,\s*"
                r"E87_CHARGE_DISPATCHER_TASK\s*\)"
            ),
        )

        bridge = read(BRIDGE)
        self.assertIn("E87_CHARGE_BRIDGE_FIFO_CAPACITY 8", bridge)
        self.assertIn("E87_CHARGE_BRIDGE_DRAIN_BUDGET 16", bridge)
        self.assertIn("private_wake_pending", bridge)
        self.assertIn("private_fault_online_raw", bridge)
        self.assertIn("private_fault_pending", bridge)

    def test_initialization_is_e87_owned_and_events_enable_last(self) -> None:
        source = read(TARGET)
        self.assertRegex(
            source,
            re.compile(
                r"static\s+struct\s+charge_platform_data\s+"
                r"e87_charge_platform_data\s*;"
            ),
        )
        body = function_body(source, "e87_br35_charge_hw_init")
        assert_in_order(
            self,
            body,
            "e87_battery_initialized",
            "e87_charge_bridge_is_ready",
            "e87_charge_dispatcher_started",
            "e87_charge_wakeup_init",
            "e87_charge_platform_data = *platform_data",
            "charge_init(&e87_charge_platform_data)",
            "set_charge_event_flag(1)",
        )
        self.assertIn("e87_charge_initialized", body)
        self.assertEqual(body.count("charge_init("), 1)
        self.assertNotIn("power_set_mode", source)
        self.assertNotIn("platform_initcall", source)
        self.assertNotIn("board_charge_init", source)

        prepare = function_body(source, "e87_br35_charge_prepare")
        assert_in_order(
            self,
            prepare,
            "e87_charge_bridge_init",
            "e87_charge_bridge_poll_app",
            "e87_br35_charge_dispatcher_start",
        )
        self.assertEqual(source.count("charge_init(&e87_charge_platform_data)"), 1)
        self.assertEqual(source.count("set_charge_event_flag(1)"), 1)

        header = read(TARGET_HEADER)
        self.assertRegex(
            header,
            re.compile(
                r"e87_br35_charge_hw_init\s*\(\s*"
                r"const\s+struct\s+charge_platform_data\s*\*\s*platform_data"
            ),
        )

    def test_wake_detection_is_explicit_and_sdk_low_level_only(self) -> None:
        source = read(TARGET)
        for name in ("e87_vbat_wakeup", "e87_ldoin_wakeup"):
            config = braced_block_after(
                source,
                rf"static\s+const\s+struct\s+_p33_io_wakeup_config\s+{name}\s*=",
            )
            self.assertNotIn("pullup_down_mode", config)
            self.assertIn(".filter = PORT_FLT_16ms", config)
            self.assertIn(".edge = BOTH_EDGE", config)
            self.assertIn(".callback = e87_charge_wakeup_callback", config)
        wake_init = function_body(source, "e87_charge_wakeup_init")
        for name in ("e87_vbat_wakeup", "e87_ldoin_wakeup"):
            self.assertIn(f"p33_io_wakeup_port_init(&{name})", wake_init)
        self.assertIn("p33_io_wakeup_enable(IO_VBTCH_DET, 1)", wake_init)
        self.assertIn("p33_io_wakeup_enable(IO_LDOIN_DET, 1)", wake_init)
        wake_callback = function_body(source, "e87_charge_wakeup_callback")
        self.assertEqual(wake_callback.count("ldoin_wakeup_isr()"), 1)
        for forbidden in (
            "charge_start(",
            "charge_close(",
            "e87_charge_adapter_step(",
            "e87_charge_bridge_poll_app(",
            "os_taskq_",
            "set_charge_event_flag(",
        ):
            self.assertNotIn(forbidden, wake_callback)

    def test_target_bridge_binding_reads_online_only_through_serialized_port(self) -> None:
        source = read(TARGET)
        reader = function_body(source, "e87_read_driver_online")
        self.assertEqual(reader.count("get_charge_online_flag()"), 1)
        self.assertNotIn("get_charge_online_flag()", function_body(
            source, "charge_event_to_user"
        ))
        self.assertNotIn("get_charge_online_flag()", function_body(
            source, "e87_br35_charge_dispatcher_run"
        ))

    def test_battery_init_is_required_before_sampling(self) -> None:
        source = read(TARGET)
        init = function_body(source, "e87_br35_battery_init")
        sample = function_body(source, "e87_br35_battery_sample_full_mv")
        self.assertIn("e87_battery_initialized", init)
        self.assertIn("e87_battery_initialized", sample)
        assert_in_order(
            self,
            sample,
            "e87_battery_initialized",
            "e87_battery_sampler_sample_full_mv",
        )

    def test_source_policy_excludes_stock_charge_routes_exactly(self) -> None:
        policy = read_json(POLICY)
        self.assertEqual(
            set(policy),
            {
                "schemaVersion",
                "requiredE87Sources",
                "retainedLowLevelSources",
                "forbiddenSdkSources",
            },
        )
        self.assertEqual(policy["schemaVersion"], 1)
        self.assertEqual(
            policy["requiredE87Sources"],
            [
                "SDK/apps/watch/e87/e87_battery.c",
                "SDK/apps/watch/e87/e87_battery_sampler.c",
                "SDK/apps/watch/e87/e87_br35_battery_charge.c",
                "SDK/apps/watch/e87/e87_charge_adapter.c",
                "SDK/apps/watch/e87/e87_charge_bridge.c",
                "SDK/apps/watch/e87/e87_power_policy.c",
            ],
        )
        self.assertEqual(
            policy["retainedLowLevelSources"],
            ["SDK/cpu/br35/charge/charge.c"],
        )
        self.assertEqual(
            policy["forbiddenSdkSources"],
            [
                "SDK/cpu/br35/charge/charge_config.c",
                "SDK/apps/watch/battery/charge.c",
                "SDK/apps/watch/message/adapter/battery.c",
            ],
        )

        all_source = "\n".join(
            read(REPO_ROOT / "firmware/overlay" / source)
            for source in policy["requiredE87Sources"]
        )
        for forbidden_symbol in (
            "charge_module_stop(",
            "cpu_reset(",
            "power_set_soft_poweroff(",
            "app_task_switch(",
            "IDLE_MODE_CHARGE",
            "UI_WINDOW",
        ):
            self.assertNotIn(forbidden_symbol, all_source)


if __name__ == "__main__":
    unittest.main()
