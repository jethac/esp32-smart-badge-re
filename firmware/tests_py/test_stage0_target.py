#!/usr/bin/env python3
"""Repository integration contract for the Stage 0-H heartbeat target."""

from __future__ import annotations

import json
from pathlib import Path
import re
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE = REPO_ROOT / "firmware/board-profiles/E87-1542-STAGE0-H.json"
SUITES = REPO_ROOT / "firmware/host/suites.json"
ADV_HEADER = REPO_ROOT / (
    "firmware/overlay/SDK/apps/watch/include/e87/e87_stage0_adv.h"
)


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: Path) -> dict[str, object]:
    value = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys
    )
    if not isinstance(value, dict):
        raise AssertionError(f"{path} root must be an object")
    return value


class Stage0TargetTests(unittest.TestCase):
    def test_board_profile_is_closed_and_marks_every_unmeasured_hardware_fact(self) -> None:
        profile = read_json(PROFILE)
        self.assertEqual(
            set(profile),
            {"schemaVersion", "profileId", "target", "ble", "disabled", "evidence"},
        )
        self.assertEqual(profile["schemaVersion"], 1)
        self.assertEqual(profile["profileId"], "E87-1542-STAGE0-H")
        self.assertEqual(
            profile["target"],
            {
                "chip": "AC707N",
                "family": "BR35",
                "panel": "UNMEASURED_DISABLED",
                "buttons": "UNMEASURED_DISABLED",
                "gpioAssignments": [],
            },
        )
        self.assertEqual(
            profile["ble"],
            {
                "stackModules": 2,
                "advertisementType": "ADV_NONCONN_IND",
                "intervalUnits": 1600,
                "channelMap": 7,
                "scanResponseLength": 0,
                "addressSource": "TZFLASH_UUID_FNV1A64_V1",
                "ownAddressType": 1,
                "l2capPresence": "RETAINED_BY_PINNED_BTSTACK",
                "inheritedMacroLevel": 5,
                "txPowerControl": "NOT_APPLIED",
                "txPowerEvidence": "UNMEASURED",
            },
        )
        self.assertEqual(
            profile["disabled"],
            [
                "classic",
                "emitted-connectable-advertising",
                "att",
                "gatt",
                "sm",
                "profile",
                "pairing",
                "bonding",
                "scan-response",
                "display",
                "touch",
                "key",
                "pin-reset",
                "adc",
                "filesystem-app-route",
                "data-storage",
                "audio",
                "update",
                "rcsp",
            ],
        )
        self.assertEqual(
            profile["evidence"],
            {
                "sdkCommit": "d0167685d032d745d88fe50233302edd46941622",
                "controllerRoleQualification": (
                    "controller library gates remain vendor-owned; externally exposed "
                    "behavior is non-connectable advertising only"
                ),
                "immutableBootSeam": (
                    "setup_arch retains sdfile_init and syscfg_tools_init before app_main"
                ),
                "readyTupleEvidence": (
                    "btstack.a btstack_task.c.o calls "
                    "update_bt_current_status(NULL,3,50)"
                ),
            },
        )

    def test_host_manifest_appends_only_the_exact_stage0_case(self) -> None:
        manifest = read_json(SUITES)
        suites = manifest["suites"]
        self.assertIsInstance(suites, dict)
        self.assertEqual(
            suites["stage0"],
            [
                {
                    "name": "stage0-adv",
                    "test": "firmware/host/test_stage0_adv.c",
                    "sources": [
                        "firmware/overlay/SDK/apps/watch/e87/e87_stage0_adv.c"
                    ],
                }
            ],
        )
        self.assertEqual(
            suites["renderer"],
            [
                {
                    "name": "normal-face",
                    "test": "firmware/host/test_renderer.c",
                    "sources": [
                        "firmware/overlay/SDK/apps/watch/e87/e87_renderer.c",
                        "firmware/generated/e87_assets.c",
                    ],
                }
            ],
        )
        self.assertEqual(
            suites["classifier"],
            [
                {
                    "name": "button-classifier",
                    "test": "firmware/host/test_button_classifier.c",
                    "sources": [
                        "firmware/overlay/SDK/apps/watch/e87/e87_button_classifier.c",
                        "firmware/overlay/SDK/apps/watch/e87/e87_button_fsm.c",
                    ],
                }
            ],
        )

    def test_public_constants_pin_the_wire_and_controller_contract(self) -> None:
        header = ADV_HEADER.read_text(encoding="utf-8")
        expected_defines = {
            "E87_STAGE0_BUILD_TAG_HEX_DIGITS": "8U",
            "E87_STAGE0_LOCAL_NAME_LENGTH": "15U",
            "E87_STAGE0_ADV_DATA_LENGTH": "29U",
            "E87_STAGE0_ADV_INTERVAL_UNITS": "1600U",
            "E87_STAGE0_ADV_TYPE_NONCONN_IND": "3U",
            "E87_STAGE0_ADV_CHANNEL_MAP": "0x07U",
            "E87_STAGE0_OWN_ADDRESS_TYPE_RANDOM": "1U",
            "E87_STAGE0_FLASH_UUID_LENGTH": "16U",
            "E87_STAGE0_RANDOM_ADDRESS_LENGTH": "6U",
        }
        actual = dict(
            re.findall(r"^#define\s+(E87_STAGE0_[A-Z0-9_]+)\s+([^\s/]+)", header, re.M)
        )
        for name, value in expected_defines.items():
            self.assertEqual(actual.get(name), value, name)


if __name__ == "__main__":
    unittest.main()
