#include "e87/e87_maintenance.h"

#include <string.h>

const char e87_rcsp_local_name[] = "E87 UPDATE";

const uint8_t e87_rcsp_profile[] = {
    0x0a, 0x00, 0x02, 0x00, 0x01, 0x00, 0x00, 0x28, 0x00, 0x18,
    0x0d, 0x00, 0x02, 0x00, 0x02, 0x00, 0x03, 0x28, 0x02, 0x03,
    0x00, 0x00, 0x2a,
    0x08, 0x00, 0x02, 0x01, 0x03, 0x00, 0x00, 0x2a,
    0x0a, 0x00, 0x02, 0x00, 0x04, 0x00, 0x00, 0x28, 0x00, 0xae,
    0x0d, 0x00, 0x02, 0x00, 0x05, 0x00, 0x03, 0x28, 0x04, 0x06,
    0x00, 0x01, 0xae,
    0x08, 0x00, 0x04, 0x01, 0x06, 0x00, 0x01, 0xae,
    0x0d, 0x00, 0x02, 0x00, 0x07, 0x00, 0x03, 0x28, 0x10, 0x08,
    0x00, 0x02, 0xae,
    0x08, 0x00, 0x10, 0x00, 0x08, 0x00, 0x02, 0xae,
    0x0a, 0x00, 0x0a, 0x01, 0x09, 0x00, 0x02, 0x29, 0x00, 0x00,
    0x00, 0x00
};

const size_t e87_rcsp_profile_size = sizeof(e87_rcsp_profile);

static const uint8_t expected_profile_id[E87_RCSP_PROFILE_ID_BYTES] = {
    'E', '8', '7', '-', 'J', 'D', '9', '8',
    '5', '5', '-', 'R', '1', 0, 0, 0
};

enum e87_maintenance_result e87_maintenance_accept_verified_loader(
    struct e87_maintenance *maintenance,
    const struct e87_rcsp_official_loader_report *report);

static bool valid_official_report(
    const struct e87_rcsp_official_loader_report *report)
{
    return report != 0 &&
           report->update_type == E87_RCSP_SDK_BLE_APP_UPDATE_TYPE &&
           report->update_state == E87_RCSP_SDK_UPDATE_SUCCESS_STATE &&
           report->loader_result == E87_RCSP_SDK_LOADER_OK &&
           report->loader_saddr != UINT32_C(0) &&
           report->chip == E87_UPDATE_CHIP_AC707N &&
           report->layout == E87_UPDATE_LAYOUT_SINGLE_BANK &&
           report->exact_layout_match &&
           memcmp(report->profile_id, expected_profile_id,
                  sizeof(expected_profile_id)) == 0;
}

static bool valid_handoff(const struct e87_maintenance_handoff *handoff)
{
    return handoff != 0 && handoff->official_loader_verified &&
           handoff->update_type == E87_RCSP_SDK_BLE_APP_UPDATE_TYPE &&
           handoff->update_state == E87_RCSP_SDK_UPDATE_SUCCESS_STATE &&
           handoff->loader_result == E87_RCSP_SDK_LOADER_OK &&
           handoff->loader_saddr != UINT32_C(0) &&
           handoff->battery_percent >=
               E87_MAINTENANCE_MIN_BATTERY_PERCENT &&
           handoff->battery_percent <= UINT8_C(100) &&
           !handoff->low_voltage_warning &&
           handoff->board_voltage_stable &&
           handoff->power_stable_for_required_window &&
           handoff->chip == E87_UPDATE_CHIP_AC707N &&
           handoff->layout == E87_UPDATE_LAYOUT_SINGLE_BANK &&
           handoff->exact_layout_match &&
           memcmp(handoff->profile_id, expected_profile_id,
                  sizeof(expected_profile_id)) == 0;
}

enum e87_maintenance_result e87_rcsp_official_loader_callback(
    struct e87_maintenance *maintenance,
    uint32_t now_ms,
    const struct e87_rcsp_official_loader_report *report)
{
    if (!valid_official_report(report)) {
        const struct e87_maintenance_event failure = {
            E87_MAINTENANCE_EVENT_FAILURE, now_ms, {0}, false
        };

        return e87_maintenance_step(maintenance, &failure);
    }
    return e87_maintenance_accept_verified_loader(maintenance, report);
}

static bool valid_target_api(
    const struct e87_rcsp_target_api *api)
{
    return api != 0 && api->bt_rcsp_interface_init != 0 &&
           api->rcsp_init != 0 && api->rcsp_bt_ble_init != 0 &&
           api->reject_commands != 0 && api->stop_advertising != 0 &&
           api->disconnect != 0 && api->rcsp_bt_ble_exit != 0 &&
           api->rcsp_handle_get != 0 &&
           api->bt_rcsp_interface_exit != 0 &&
           api->request_normal_mode != 0 &&
           api->approve_official_update_start != 0;
}

static bool e87_rcsp_target_emit(
    void *context,
    enum e87_maintenance_command command,
    const struct e87_maintenance_handoff *handoff)
{
    struct e87_rcsp_target_adapter *adapter =
        (struct e87_rcsp_target_adapter *)context;
    const struct e87_rcsp_target_api *api;

    if (adapter == 0 || !adapter->private_initialized) {
        return false;
    }
    api = &adapter->private_api;
    if (command != E87_MAINTENANCE_COMMAND_OFFICIAL_HANDOFF &&
        handoff != 0) {
        return false;
    }
    switch (command) {
    case E87_MAINTENANCE_COMMAND_RCSP_INTERFACE_INIT:
        return api->bt_rcsp_interface_init != 0 &&
               api->bt_rcsp_interface_init(
                   api->context, e87_rcsp_profile, e87_rcsp_local_name);
    case E87_MAINTENANCE_COMMAND_RCSP_INIT:
        return api->rcsp_init != 0 && api->rcsp_init(api->context);
    case E87_MAINTENANCE_COMMAND_RCSP_BLE_INIT:
        return api->rcsp_bt_ble_init != 0 &&
               api->rcsp_bt_ble_init(api->context);
    case E87_MAINTENANCE_COMMAND_REJECT_COMMANDS:
        return api->reject_commands != 0 &&
               api->reject_commands(api->context);
    case E87_MAINTENANCE_COMMAND_STOP_ADVERTISING:
        return api->stop_advertising != 0 &&
               api->stop_advertising(api->context);
    case E87_MAINTENANCE_COMMAND_DISCONNECT:
        return api->disconnect != 0 && api->disconnect(api->context);
    case E87_MAINTENANCE_COMMAND_RCSP_BLE_EXIT:
        return api->rcsp_bt_ble_exit != 0 &&
               api->rcsp_bt_ble_exit(api->context);
    case E87_MAINTENANCE_COMMAND_RCSP_INTERFACE_EXIT:
        return api->rcsp_handle_get != 0 &&
               api->rcsp_handle_get(api->context) == 0 &&
               api->bt_rcsp_interface_exit != 0 &&
               api->bt_rcsp_interface_exit(api->context);
    case E87_MAINTENANCE_COMMAND_REQUEST_NORMAL_MODE:
        return api->request_normal_mode != 0 &&
               api->request_normal_mode(api->context);
    case E87_MAINTENANCE_COMMAND_OFFICIAL_HANDOFF:
        return valid_handoff(handoff) &&
               api->approve_official_update_start(
                   api->context, handoff->loader_saddr);
    default:
        return false;
    }
}

bool e87_rcsp_target_maintenance_init(
    struct e87_rcsp_target_adapter *adapter,
    const struct e87_rcsp_target_api *api,
    struct e87_maintenance *maintenance)
{
    struct e87_rcsp_target_adapter initialized_adapter = {0};
    struct e87_maintenance initialized_maintenance;
    struct e87_maintenance_port port;

    if (adapter == 0 || maintenance == 0 ||
        (void *)adapter == (void *)maintenance ||
        !valid_target_api(api)) {
        return false;
    }
    initialized_adapter.private_api = *api;
    initialized_adapter.private_initialized = true;
    port.context = adapter;
    port.emit = e87_rcsp_target_emit;
    if (!e87_maintenance_init(&initialized_maintenance, &port)) {
        return false;
    }
    *adapter = initialized_adapter;
    *maintenance = initialized_maintenance;
    return true;
}

enum e87_maintenance_result e87_rcsp_target_poll_release(
    struct e87_rcsp_target_adapter *adapter,
    struct e87_maintenance *maintenance,
    uint32_t now_ms)
{
    struct e87_maintenance_event event = {
        E87_MAINTENANCE_EVENT_RCSP_RELEASE_STATUS,
        now_ms,
        {0},
        true
    };

    if (adapter == 0 || maintenance == 0 ||
        !adapter->private_initialized ||
        adapter->private_api.rcsp_handle_get == 0) {
        return E87_MAINTENANCE_RESULT_ERROR;
    }
    if (maintenance->private_interface_exited) {
        event.rcsp_handle_present = false;
    } else {
        event.rcsp_handle_present =
            adapter->private_api.rcsp_handle_get(
                adapter->private_api.context) != 0;
    }
    return e87_maintenance_step(maintenance, &event);
}
