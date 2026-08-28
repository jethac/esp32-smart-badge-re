"""Exact byte-level tests for the E87 normal ATT database and advertisement."""

from __future__ import annotations

import re
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "firmware/overlay/SDK/apps/watch/e87/e87_gatt_db.c"


def _array(name: str) -> bytes:
    text = SOURCE.read_text(encoding="utf-8")
    match = re.search(
        rf"const\s+uint8_t\s+{re.escape(name)}(?:\[[^\]]*\])?\s*=\s*\{{(.*?)\}}\s*;",
        text,
        re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"missing byte array: {name}")
    body = re.sub(r"/\*.*?\*/", "", match.group(1), flags=re.DOTALL)
    body = re.sub(r"//[^\n]*", "", body)
    tokens = re.findall(r"0[xX][0-9a-fA-F]+|\b[0-9]+\b", body)
    return bytes(int(token, 0) for token in tokens)


def _record(flags: int, handle: int, uuid: bytes, value: bytes = b"") -> bytes:
    size = 6 + len(uuid) + len(value)
    return (
        size.to_bytes(2, "little")
        + flags.to_bytes(2, "little")
        + handle.to_bytes(2, "little")
        + uuid
        + value
    )


UUID_PRIMARY_SERVICE = bytes.fromhex("0028")
UUID_CHARACTERISTIC = bytes.fromhex("0328")
UUID_DEVICE_NAME = bytes.fromhex("002a")
UUID_CCCD = bytes.fromhex("0229")
UUID_BATTERY_SERVICE = bytes.fromhex("0f18")
UUID_BATTERY_LEVEL = bytes.fromhex("192a")
UUID_SERVICE = bytes.fromhex("3507a7019c5d0b9f624c1b7a01007de8")
UUID_STATE = bytes.fromhex("3507a7019c5d0b9f624c1b7a02007de8")
UUID_BUILD = bytes.fromhex("3507a7019c5d0b9f624c1b7a03007de8")


EXPECTED_PROFILE = b"".join(
    (
        _record(0x0002, 1, UUID_PRIMARY_SERVICE, bytes.fromhex("0018")),
        _record(0x0002, 2, UUID_CHARACTERISTIC, bytes((0x02, 0x03, 0x00)) + UUID_DEVICE_NAME),
        _record(0x0102, 3, UUID_DEVICE_NAME),
        _record(0x0002, 4, UUID_PRIMARY_SERVICE, UUID_SERVICE),
        _record(0x0002, 5, UUID_CHARACTERISTIC, bytes((0x08, 0x06, 0x00)) + UUID_STATE),
        _record(0x1308, 6, UUID_STATE),
        _record(0x0002, 7, UUID_CHARACTERISTIC, bytes((0x02, 0x08, 0x00)) + UUID_BUILD),
        _record(0x1302, 8, UUID_BUILD),
        _record(0x0002, 9, UUID_PRIMARY_SERVICE, UUID_BATTERY_SERVICE),
        _record(0x0002, 10, UUID_CHARACTERISTIC, bytes((0x12, 0x0B, 0x00)) + UUID_BATTERY_LEVEL),
        _record(0x0112, 11, UUID_BATTERY_LEVEL),
        _record(0x010A, 12, UUID_CCCD, b"\x00\x00"),
        b"\x00\x00",
    )
)

EXPECTED_ADVERTISEMENT = bytes.fromhex(
    "020106"
    "11073507a7019c5d0b9f624c1b7a01007de8"
    "0409453837"
)


class ExactAttDatabaseTests(unittest.TestCase):
    def test_profile_is_exact_and_terminated(self) -> None:
        profile = _array("e87_normal_gatt_profile")
        self.assertEqual(EXPECTED_PROFILE, profile)
        self.assertEqual(b"\x00\x00", profile[-2:])

    def test_handles_properties_and_encrypted_non_mitm_permissions_are_exact(self) -> None:
        profile = _array("e87_normal_gatt_profile")
        self.assertIn(_record(0x1308, 6, UUID_STATE), profile)
        self.assertIn(_record(0x1302, 8, UUID_BUILD), profile)
        self.assertNotIn(_record(0x0702, 8, UUID_BUILD), profile)
        self.assertNotIn(_record(0x0304, 6, UUID_STATE), profile)
        self.assertNotIn((0x2308).to_bytes(2, "little"), profile)
        self.assertNotIn((0x0B02).to_bytes(2, "little"), profile)

    def test_advertisement_is_exactly_26_bytes(self) -> None:
        advertisement = _array("e87_normal_advertising_data")
        self.assertEqual(26, len(advertisement))
        self.assertEqual(EXPECTED_ADVERTISEMENT, advertisement)
        self.assertEqual(b"E87", advertisement[-3:])


if __name__ == "__main__":
    unittest.main()
