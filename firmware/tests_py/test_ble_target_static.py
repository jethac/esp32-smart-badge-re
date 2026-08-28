#!/usr/bin/env python3
"""Static BR35 boundary contract for the normal-profile BLE target seam."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import re
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
PATCH = REPO_ROOT / "firmware/patches/ble-target/0001-e87-ble-target.patch"
PROFILE = REPO_ROOT / "firmware/board-profiles/E87-1542-BLE-TARGET-H.json"
EVIDENCE = REPO_ROOT / "firmware/evidence/ble-target/vendor-contract.json"
OVERLAY = REPO_ROOT / "firmware/overlay/SDK/apps/watch"

PATCH_TARGETS = {
    "SDK/apps/watch/board/br35/board_e87_1542_full/board_e87_1542_full_cfg.h",
    "SDK/apps/watch/include/app_config.h",
    "SDK/build/Makefile.mk",
}
PATCH_PREIMAGES = {
    "SDK/apps/watch/board/br35/board_e87_1542_full/board_e87_1542_full_cfg.h":
        "da0a293",
    "SDK/apps/watch/include/app_config.h": "a561f7a",
    "SDK/build/Makefile.mk": "3709ada",
}
FROZEN_FULL_SHA256 = {
    "firmware/board-profiles/E87-1542-FULL-SUBSTRATE-H.json":
        "65b3dcc2218135d4575249566f700fed8083769497f3eb2f72b67591e2199769",
    "firmware/patches/full/0001-e87-full-substrate.patch":
        "18e650a8b992784e5f5bf09ba6c7137533dffa32d98a1d4b176995fe99528056",
    "firmware/evidence/full/link-closure.json":
        "6747b6d3207af01beeb19cfd82bfb0ee6dd05e8a718f80969fc19fab9f9f9cd4",
}
REQUIRED_SOURCES = {
    "apps/watch/e87/e87_ble_target.c",
    "apps/watch/e87/e87_ble_target_journal.c",
    "apps/watch/e87/e87_ble_target_platform_config.c",
    "apps/watch/e87/e87_bond_policy.c",
    "apps/watch/e87/e87_build_info.c",
    "apps/watch/e87/e87_gatt_db.c",
    "apps/watch/e87/e87_state.c",
    "apps/watch/log_config/app_config.c",
    "apps/watch/log_config/lib_btctrler_config.c",
    "apps/watch/log_config/lib_btstack_config.c",
}
REQUIRED_ARCHIVES = {
    "cpu/br35/liba/btstack.a",
    "cpu/br35/liba/btctrler.a",
    "cpu/br35/liba/cbuf.a",
    "cpu/br35/liba/crypto_toolbox_Osize.a",
    "cpu/br35/liba/lib_ccm_cipher.a",
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


class BleTargetStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.patch = read(PATCH)

    def test_patch_is_ordered_after_full_and_never_owns_app_or_rcsp(self) -> None:
        targets = set(re.findall(r"^diff --git a/(\S+) b/\1$", self.patch, re.M))
        self.assertEqual(PATCH_TARGETS, targets)
        profile = json.loads(read(PROFILE))
        self.assertEqual(
            [
                "firmware/patches/full/0001-e87-full-substrate.patch",
                "firmware/patches/ble-target/0001-e87-ble-target.patch",
            ],
            profile["orderedPatches"],
        )
        self.assertEqual("TARGET_LINK_BLOCKED", profile["status"])
        self.assertEqual(
            [
                "e87_ble_target_init",
                "e87_ble_target_poll",
                "e87_ble_target_set_writes_enabled",
                "e87_ble_target_authorization_epoch_is_active",
            ],
            profile["publicApi"],
        )
        for forbidden in ("e87_app.c", "panel", "charge", "rcsp"):
            self.assertNotIn(forbidden, "\n".join(sorted(targets)).lower())
        for target, preimage in PATCH_PREIMAGES.items():
            section = patch_section(self.patch, target)
            self.assertRegex(section, rf"^index {preimage}\.\.", target)

    def test_qualified_full_inputs_remain_byte_frozen(self) -> None:
        for relative, expected in FROZEN_FULL_SHA256.items():
            with self.subTest(path=relative):
                normalized = (REPO_ROOT / relative).read_bytes().replace(
                    b"\r\n", b"\n"
                )
                self.assertEqual(hashlib.sha256(normalized).hexdigest(), expected)

    def test_patch_enables_ble_but_keeps_classic_tws_and_rcsp_out(self) -> None:
        board = added_section(
            self.patch,
            "SDK/apps/watch/board/br35/board_e87_1542_full/board_e87_1542_full_cfg.h",
        )
        app_config = added_section(self.patch, "SDK/apps/watch/include/app_config.h")
        for section in (board, app_config):
            self.assertIn("#define TCFG_APP_BT_EN 1", section)
            self.assertIn("#define TCFG_USER_BLE_ENABLE 1", section)
        self.assertIn("#define TCFG_BT_BLE_ADV_ENABLE 1", app_config)
        self.assertIn("#define TCFG_USER_EMITTER_ENABLE 0", app_config)
        self.assertIn("#define TCFG_BLE_BRIDGE_EDR_ENALBE 0", app_config)
        untouched = read(
            OVERLAY
            / "board/br35/board_e87_1542_full/board_e87_1542_full_cfg.h"
        )
        for name in ("TCFG_USER_BT_CLASSIC_ENABLE", "TCFG_USER_TWS_ENABLE"):
            self.assertRegex(untouched, rf"#define\s+{name}\s+0")

    def test_compile_and_archive_boundaries_are_exact(self) -> None:
        added = added_section(self.patch, "SDK/build/Makefile.mk")
        source_block = between(
            added,
            "# E87_BLE_TARGET_REQUIRED_SOURCES_BEGIN\n",
            "# E87_BLE_TARGET_REQUIRED_SOURCES_END",
        )
        archive_block = between(
            added,
            "# E87_BLE_TARGET_REQUIRED_ARCHIVES_BEGIN\n",
            "# E87_BLE_TARGET_REQUIRED_ARCHIVES_END",
        )
        self.assertEqual(
            REQUIRED_SOURCES,
            set(re.findall(r"[A-Za-z0-9_./-]+\.c", source_block)),
        )
        self.assertEqual(
            REQUIRED_ARCHIVES,
            set(re.findall(r"[A-Za-z0-9_./+-]+\.a", archive_block)),
        )
        self.assertIn(
            "E87_FULL_REQUIRED_SOURCES += $(E87_BLE_TARGET_REQUIRED_SOURCES)",
            added,
        )
        self.assertIn("c_SRC_FILES := $(E87_FULL_REQUIRED_SOURCES)", added)
        self.assertIn(
            "E87_FULL_REQUIRED_ARCHIVES += $(E87_BLE_TARGET_REQUIRED_ARCHIVES)",
            added,
        )
        for forbidden in (
            "e87_app.c",
            "e87_ble_control.c",
            "panel",
            "charge",
            "rcsp",
        ):
            self.assertNotIn(forbidden, source_block.lower())
        for forbidden in ("rcsp_stack.a", "media.a", "gpu.a", "jlui.a"):
            self.assertNotIn(forbidden, archive_block)

    def test_platform_and_adapter_pin_the_reviewed_vendor_abi(self) -> None:
        platform = read(OVERLAY / "e87/e87_ble_target_platform_config.c")
        target = read(OVERLAY / "e87/e87_ble_target.c")
        self.assertIn("const int config_stack_modules = BT_BTSTACK_LE;", platform)
        self.assertIn("const u8 btstack_emitter_support = 0;", platform)
        self.assertIn("const u8 adt_profile_support = 0;", platform)
        for full_owned_symbol in (
            "CONFIG_CPU_UNMASK_IRQ_ENABLE",
            "btif_table",
            "vm_max_page_align_size_config",
            "vm_max_sector_align_size_config",
        ):
            self.assertNotIn(full_owned_symbol, platform)
        for guard in (
            "!TCFG_APP_BT_EN || !TCFG_USER_BLE_ENABLE",
            "TCFG_USER_BT_CLASSIC_ENABLE || TCFG_USER_TWS_ENABLE",
            "TCFG_USER_EMITTER_ENABLE",
            "TCFG_BT_AI_ENABLE || BT_AI_SEL_PROTOCOL != 0",
            "RCSP_MODE != RCSP_MODE_OFF",
        ):
            self.assertIn(guard, platform)
        self.assertIn("UINT16_C(0xfe00)", target)
        self.assertIn("size >= 16u", target)
        self.assertNotIn("sm_just_works_confirm(", target)
        self.assertIn("sm_event_identity_resolving_succeeded_get_identity_address", target)
        self.assertIn("sm_event_identity_created_get_identity_address", target)
        self.assertNotIn("get_index_internal", target)
        zero = target.index("memset(identity_address, 0")
        lookup = target.index("ble_list_get_id_addr(", zero)
        self.assertLess(zero, lookup)
        self.assertIn("app_ble_profile_set(target.handle, e87_normal_gatt_profile)", target)
        header = read(OVERLAY / "include/e87/e87_ble_target.h")
        self.assertIn("E87_BLE_TARGET_STATE_PACKET_SIZE 8u", header)
        self.assertIn("e87_ble_target_try_enqueue_state_fn", header)
        self.assertIn("uint32_t authorization_epoch", header)
        self.assertIn(
            "e87_ble_target_init(const struct e87_ble_target_ingress *ingress)",
            header,
        )
        self.assertIn("target.ingress.try_enqueue_state", target)
        self.assertIn("static volatile uint32_t authorization_epoch;", target)
        self.assertIn("authorization_epoch_exhausted", target)
        self.assertIn("target.writes_enabled && target.connected", target)
        self.assertIn(
            "e87_ble_target_authorization_epoch_is_active", target
        )
        self.assertIn("current_owner_is_durable()", target)
        self.assertIn("target.link_encrypted", target)
        self.assertIn("target.build_read_complete", target)
        self.assertNotIn("write_session_epoch", header + target)
        self.assertEqual(1, target.count("target.disconnect_required = true;"))
        self.assertIn("e87_state_decode(packet, sizeof(packet), &validated)", target)
        self.assertIn("Validation output is intentionally discarded", target)
        for forbidden in (
            "struct e87_state_store",
            "struct e87_ble_control",
            "e87_state_store_init",
            "e87_state_commit",
            "e87_ble_control_",
        ):
            self.assertNotIn(forbidden, target)

    def test_journal_and_single_link_security_boundary_are_pinned(self) -> None:
        internal = read(OVERLAY / "include/e87/e87_ble_target_internal.h")
        profile = json.loads(read(PROFILE))
        self.assertIn("E87_BLE_OWNER_JOURNAL_SLOT_A_ID UINT16_C(48)", internal)
        self.assertIn("E87_BLE_OWNER_JOURNAL_SLOT_B_ID UINT16_C(49)", internal)
        self.assertIn("E87_BLE_OWNER_JOURNAL_WIRE_SIZE UINT16_C(48)", internal)
        self.assertEqual(2, profile["limits"]["bondSlots"])
        self.assertEqual(1, profile["limits"]["maxHciConnections"])
        self.assertTrue(profile["limits"]["normalProfileOnly"])

    def test_vendor_evidence_names_exact_providers_and_link_blocker(self) -> None:
        evidence = json.loads(read(EVIDENCE))
        self.assertEqual(
            "d0167685d032d745d88fe50233302edd46941622",
            evidence["sdkCommit"],
        )
        self.assertEqual("btstack.a(app_ble_module_manage.c.o)",
                         evidence["providers"]["appBle"])
        self.assertEqual("btstack.a(remote_device_list.c.o)",
                         evidence["providers"]["bondList"])
        self.assertEqual("btstack.a(att_db.c.o)",
                         evidence["providers"]["attDatabase"])
        self.assertEqual(
            "REPLACING_DURABLE_THEN_GLOBAL_GATE_THEN_VENDOR_AUTO_CONFIRM",
                         evidence["pairing"]["ordering"])
        self.assertEqual("MISSING_APP_BTSTACK_LIFECYCLE_OWNER",
                         evidence["linkBoundary"]["blockerCode"])
        future = evidence["linkBoundary"]["futureComposition"]
        self.assertEqual("COORDINATOR_APP_CORE",
                         future["policyAndLifecycleOwner"])
        self.assertEqual("E87_BLE_TARGET",
                         future["sdkProfileAndAuthorizationOwner"])
        self.assertFalse(future["initMayAutoOpenPairing"])
        self.assertEqual(5, len(future["binderRequiredMethods"]))
        self.assertIn("immediately before external profile release",
                      evidence["coordinatorBoundary"]
                              ["profileReleasePrecondition"])


if __name__ == "__main__":
    unittest.main()
