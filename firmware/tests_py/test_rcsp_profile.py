from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROFILE_SOURCE = (
    ROOT / "firmware/overlay/SDK/apps/watch/e87/e87_rcsp_profile.c"
)
MAINTENANCE_SOURCE = (
    ROOT / "firmware/overlay/SDK/apps/watch/e87/e87_maintenance.c"
)
HEADER = (
    ROOT / "firmware/overlay/SDK/apps/watch/include/e87/e87_maintenance.h"
)
TARGET_HEADER = (
    ROOT / "firmware/overlay/SDK/apps/watch/include/e87/e87_rcsp_target.h"
)
TARGET_SOURCE = (
    ROOT / "firmware/overlay/SDK/apps/watch/e87/e87_rcsp_target.c"
)
E87_SOURCES = ROOT / "firmware/overlay/SDK/apps/watch/e87"
E87_HEADERS = ROOT / "firmware/overlay/SDK/apps/watch/include/e87"
E87_CODE = tuple(sorted(E87_SOURCES.rglob("*.c"))) + tuple(
    sorted(E87_HEADERS.rglob("*.h")))

EXPECTED_PROFILE = bytes(
    [
        0x0A, 0x00, 0x02, 0x00, 0x01, 0x00, 0x00, 0x28, 0x00, 0x18,
        0x0D, 0x00, 0x02, 0x00, 0x02, 0x00, 0x03, 0x28, 0x02, 0x03,
        0x00, 0x00, 0x2A,
        0x08, 0x00, 0x02, 0x01, 0x03, 0x00, 0x00, 0x2A,
        0x0A, 0x00, 0x02, 0x00, 0x04, 0x00, 0x00, 0x28, 0x00, 0xAE,
        0x0D, 0x00, 0x02, 0x00, 0x05, 0x00, 0x03, 0x28, 0x04, 0x06,
        0x00, 0x01, 0xAE,
        0x08, 0x00, 0x04, 0x01, 0x06, 0x00, 0x01, 0xAE,
        0x0D, 0x00, 0x02, 0x00, 0x07, 0x00, 0x03, 0x28, 0x10, 0x08,
        0x00, 0x02, 0xAE,
        0x08, 0x00, 0x10, 0x00, 0x08, 0x00, 0x02, 0xAE,
        0x0A, 0x00, 0x0A, 0x01, 0x09, 0x00, 0x02, 0x29, 0x00, 0x00,
        0x00, 0x00,
    ]
)


def source_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def initializer_bytes(source: str, symbol: str) -> bytes:
    match = re.search(
        rf"const\s+uint8_t\s+{re.escape(symbol)}\s*\[\s*\]\s*=\s*\{{(.*?)\}}\s*;",
        source,
        re.DOTALL,
    )
    assert match is not None, f"missing byte array {symbol}"
    body = re.sub(r"/\*.*?\*/|//[^\n]*", "", match.group(1), flags=re.DOTALL)
    tokens = re.findall(r"0[xX][0-9A-Fa-f]+|\b[0-9]+\b", body)
    values = [int(token, 0) for token in tokens]
    assert all(0 <= value <= 0xFF for value in values)
    return bytes(values)


def test_profile_is_the_exact_minimal_read_only_gap_and_ae00_database() -> None:
    profile = initializer_bytes(source_text(PROFILE_SOURCE), "e87_rcsp_profile")

    assert profile == EXPECTED_PROFILE
    assert profile[-2:] == b"\x00\x00"
    assert len(profile) == 95


def test_update_identity_and_sdk_callback_oracle_are_exact() -> None:
    source = source_text(PROFILE_SOURCE)
    header = source_text(HEADER)

    assert re.search(
        r'const\s+char\s+e87_rcsp_local_name\s*\[\s*\]\s*=\s*"E87 UPDATE"\s*;',
        source,
    )
    assert "E87_RCSP_SDK_BLE_APP_UPDATE_TYPE UINT32_C(0x5A06)" in header
    assert "E87_RCSP_SDK_UPDATE_SUCCESS_STATE UINT32_C(2)" in header
    assert "E87_RCSP_SDK_LOADER_OK UINT8_C(1)" in header
    assert "E87_MAINTENANCE_TIMEOUT_MS UINT32_C(120000)" in header
    assert "E87_MAINTENANCE_POWER_STABLE_MS UINT32_C(5000)" in header
    assert "E87_MAINTENANCE_MIN_BATTERY_PERCENT UINT8_C(50)" in header
    assert "E87_MAINTENANCE_RCSP_RELEASE_TIMEOUT_MS UINT32_C(5000)" in header
    assert "rcsp_handle_get" in source


def test_profile_sources_exclude_every_forbidden_stock_feature() -> None:
    sources = "\n".join(
        source_text(path) for path in E87_CODE).lower()
    forbidden = (
        "fee7",
        "aa00",
        "rcsp_ble_profile_init",
        "gatt_client_init",
        "ancs_client_init",
        "ams_client_init",
        "alipay_init",
        "spp_init",
        "tws_init",
        "file_browser",
        "sensor_init",
        "settings_init",
        "uires",
        "stock_ui",
    )

    for token in forbidden:
        assert token not in sources


def test_only_adapter_can_feed_the_verified_loader_core_seam() -> None:
    users: list[str] = []
    for path in E87_CODE:
        if "e87_maintenance_accept_verified_loader" in source_text(path):
            users.append(path.name)

    assert users == ["e87_maintenance.c", "e87_rcsp_profile.c"]
    assert "e87_maintenance_accept_verified_loader(" in source_text(PROFILE_SOURCE)


def test_only_target_adapter_calls_the_mode_api_once() -> None:
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in E87_CODE
        if "update_mode_api_v2" in source_text(path)
    ]

    assert offenders == [TARGET_SOURCE.relative_to(ROOT).as_posix()]
    assert len(re.findall(
        r"\bupdate_mode_api_v2\s*\(\s*BLE_APP_UPDATA\s*,",
        source_text(TARGET_SOURCE),
    )) == 1


def test_target_event_emitter_is_private_and_dispatch_contract_is_explicit() -> None:
    source = source_text(PROFILE_SOURCE)
    header = source_text(HEADER)

    assert "e87_rcsp_target_emit" not in header
    assert re.search(r"static\s+bool\s+e87_rcsp_target_emit\s*\(", source)
    assert "e87_rcsp_target_maintenance_init" in header
    assert "e87_rcsp_target_maintenance_init" in source
    assert "app_core" in header
    assert "serialized" in header.lower()
    assert "not a lock" in header.lower()


def test_target_adapter_binds_only_the_pinned_ble_rcsp_surface() -> None:
    source = source_text(TARGET_SOURCE)
    header = source_text(TARGET_HEADER)

    for api in (
        "bt_rcsp_interface_init",
        "rcsp_init",
        "rcsp_bt_ble_init",
        "rcsp_bt_ble_adv_enable",
        "ble_app_disconnect",
        "rcsp_bt_ble_exit",
        "rcsp_handle_get",
        "bt_rcsp_interface_exit",
        "update_mode_api_v2",
    ):
        assert api in source
    for public_api in (
        "e87_rcsp_target_init",
        "e87_rcsp_target_poll",
        "e87_rcsp_target_exit",
        "e87_rcsp_target_profile_handle",
        "e87_rcsp_target_commands_allowed",
        "e87_rcsp_target_normal_mode_requested",
    ):
        assert public_api in header
        assert public_api in source
    ownership_contract = header.lower()
    assert "sole actual maintenance profile creator" in ownership_contract
    assert "opaque profile handle" in ownership_contract
    assert "must not release the sdk profile" in ownership_contract
    assert "must consult e87_rcsp_target_commands_allowed" in ownership_contract

    for required_guard in (
        "RCSP_MODE",
        "RCSP_CHANNEL_SEL != RCSP_USE_BLE",
        "TCFG_USER_BLE_ENABLE",
        "TCFG_UPDATE_ENABLE",
        "TCFG_APP_UPDATE_EN",
        "RCSP_UPDATE_EN",
        "RCSP_BLE_MASTER",
        "TCFG_USER_BT_CLASSIC_ENABLE",
        "TCFG_BT_SUPPORT_SPP",
        "TCFG_USER_TWS_ENABLE",
        "TCFG_UI_ENABLE",
        "CONFIG_JL_UI_ENABLE",
        "OTA_TWS_SAME_TIME_ENABLE",
        "TCFG_RCSP_DUAL_CONN_ENABLE",
        "RCSP_BLE_CLIENT_EN",
        "RCSP_FILE_OPT",
        "TCFG_BS_DEV_PATH_EN",
        "WATCH_FILE_TO_FLASH",
        "JL_RCSP_EXTRA_FLASH_OPT",
        "JL_RCSP_SENSORS_DATA_OPT",
        "RCSP_APP_RTC_EN",
    ):
        assert required_guard in source
    assert "base ble/sm/att transport" in header.lower()
    assert "same UPDATE_CH_SUCESS_REPORT" in header


def test_target_adapter_has_no_stock_feature_or_direct_profile_escape() -> None:
    text = (source_text(TARGET_SOURCE) + "\n" +
            source_text(TARGET_HEADER)).lower()
    forbidden = (
        "rcsp_ble_profile_init",
        "spp_init",
        "tws_init",
        "file_browser",
        "sensor_init",
        "settings_init",
        "gatt_client_init",
        "ancs_client_init",
        "ams_client_init",
        "alipay_init",
        "stock_ui",
    )

    for token in forbidden:
        assert token not in text

    call_names = re.findall(r"\b([A-Za-z_]\w*)\s*\(",
                            source_text(TARGET_SOURCE))
    for name in call_names:
        assert not name.lower().startswith((
            "spp_", "tws_", "ui_", "file_", "browser_", "settings_"
        ))
