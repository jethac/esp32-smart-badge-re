#!/usr/bin/env python3
"""Architecture check for the board-neutral pure recovery policy."""

from __future__ import annotations

from pathlib import Path
import re
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
PURE_RECOVERY_FILES = (
    "firmware/overlay/SDK/apps/watch/include/e87/e87_recovery.h",
    "firmware/overlay/SDK/apps/watch/e87/e87_recovery.c",
    "firmware/host/test_recovery.c",
)
BOARD_PIN_TOKEN = re.compile(r"pb0[78]", re.IGNORECASE)


class RecoveryBoardNeutralTest(unittest.TestCase):
    def test_pure_recovery_layer_contains_no_board_pin_tokens(self) -> None:
        violations: dict[str, list[str]] = {}

        for relative in PURE_RECOVERY_FILES:
            text = (REPO_ROOT / relative).read_text(encoding="utf-8")
            matches = sorted(set(BOARD_PIN_TOKEN.findall(text)))
            if matches:
                violations[relative] = matches

        self.assertEqual({}, violations)


if __name__ == "__main__":
    unittest.main()
