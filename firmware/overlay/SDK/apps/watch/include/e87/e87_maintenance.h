#ifndef E87_MAINTENANCE_H
#define E87_MAINTENANCE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "e87/e87_power_policy.h"

#define E87_MAINTENANCE_TIMEOUT_MS UINT32_C(120000)
#define E87_MAINTENANCE_POWER_STABLE_MS UINT32_C(5000)
#define E87_MAINTENANCE_RCSP_RELEASE_TIMEOUT_MS UINT32_C(5000)
#define E87_MAINTENANCE_MIN_BATTERY_PERCENT UINT8_C(50)
#define E87_RCSP_PROFILE_ID_BYTES 16U

#define E87_RCSP_SDK_BLE_APP_UPDATE_TYPE UINT32_C(0x5A06)
#define E87_RCSP_SDK_UPDATE_SUCCESS_STATE UINT32_C(2)
#define E87_RCSP_SDK_LOADER_OK UINT8_C(1)

extern const char e87_rcsp_local_name[];
extern const uint8_t e87_rcsp_profile[];
extern const size_t e87_rcsp_profile_size;

enum e87_update_chip {
    E87_UPDATE_CHIP_UNKNOWN = 0,
    E87_UPDATE_CHIP_AC707N = 1,
    E87_UPDATE_CHIP_OTHER = 2
};

enum e87_update_layout {
    E87_UPDATE_LAYOUT_UNKNOWN = 0,
    E87_UPDATE_LAYOUT_SINGLE_BANK = 1,
    E87_UPDATE_LAYOUT_DUAL_BANK = 2
};

struct e87_rcsp_official_loader_report {
    uint32_t update_type;
    uint32_t update_state;
    uint8_t loader_result;
    uint32_t loader_saddr;
    enum e87_update_chip chip;
    enum e87_update_layout layout;
    bool exact_layout_match;
    uint8_t profile_id[E87_RCSP_PROFILE_ID_BYTES];
};

struct e87_maintenance_power_sample {
    uint8_t percent;
    bool low_voltage_warning;
    bool board_voltage_stable;
    bool external_power_online;
    enum e87_charge_phase charger_phase;
};

struct e87_maintenance_handoff {
    bool official_loader_verified;
    uint32_t update_type;
    uint32_t update_state;
    uint8_t loader_result;
    uint32_t loader_saddr;
    uint8_t battery_percent;
    bool low_voltage_warning;
    bool board_voltage_stable;
    bool power_stable_for_required_window;
    enum e87_update_chip chip;
    enum e87_update_layout layout;
    bool exact_layout_match;
    uint8_t profile_id[E87_RCSP_PROFILE_ID_BYTES];
};

enum e87_maintenance_command {
    E87_MAINTENANCE_COMMAND_RCSP_INTERFACE_INIT = 0,
    E87_MAINTENANCE_COMMAND_RCSP_INIT = 1,
    E87_MAINTENANCE_COMMAND_RCSP_BLE_INIT = 2,
    E87_MAINTENANCE_COMMAND_REJECT_COMMANDS = 3,
    E87_MAINTENANCE_COMMAND_STOP_ADVERTISING = 4,
    E87_MAINTENANCE_COMMAND_DISCONNECT = 5,
    E87_MAINTENANCE_COMMAND_RCSP_BLE_EXIT = 6,
    E87_MAINTENANCE_COMMAND_RCSP_INTERFACE_EXIT = 7,
    E87_MAINTENANCE_COMMAND_REQUEST_NORMAL_MODE = 8,
    E87_MAINTENANCE_COMMAND_OFFICIAL_HANDOFF = 9
};

enum e87_maintenance_state {
    E87_MAINTENANCE_STATE_READY = 0,
    E87_MAINTENANCE_STATE_ACTIVE = 1,
    E87_MAINTENANCE_STATE_EXITING = 2,
    E87_MAINTENANCE_STATE_WAIT_RCSP_RELEASE = 3,
    E87_MAINTENANCE_STATE_NORMAL_REQUESTED = 4,
    E87_MAINTENANCE_STATE_HANDOFF_APPROVED = 5,
    E87_MAINTENANCE_STATE_HANDED_OFF = 6,
    E87_MAINTENANCE_STATE_ERROR = 7
};

enum e87_maintenance_event_type {
    E87_MAINTENANCE_EVENT_ENTER_AFTER_NORMAL_DISCONNECT = 0,
    E87_MAINTENANCE_EVENT_POLL = 1,
    E87_MAINTENANCE_EVENT_AUTHENTICATED = 2,
    E87_MAINTENANCE_EVENT_HOST_DISCONNECTED = 3,
    E87_MAINTENANCE_EVENT_CANCEL = 4,
    E87_MAINTENANCE_EVENT_FAILURE = 5,
    E87_MAINTENANCE_EVENT_TRANSPORT_QUIESCED = 6,
    E87_MAINTENANCE_EVENT_POWER_SAMPLE = 7,
    E87_MAINTENANCE_EVENT_RCSP_RELEASE_STATUS = 8
};

struct e87_maintenance_event {
    enum e87_maintenance_event_type type;
    uint32_t now_ms;
    struct e87_maintenance_power_sample power;
    bool rcsp_handle_present;
};

enum e87_maintenance_result {
    E87_MAINTENANCE_RESULT_ERROR = 0,
    E87_MAINTENANCE_RESULT_NO_CHANGE = 1,
    E87_MAINTENANCE_RESULT_ACTIVE = 2,
    E87_MAINTENANCE_RESULT_AUTHENTICATED = 3,
    E87_MAINTENANCE_RESULT_STATUS_UPDATED = 4,
    E87_MAINTENANCE_RESULT_EXITING = 5,
    E87_MAINTENANCE_RESULT_WAITING_FOR_RCSP_RELEASE = 6,
    E87_MAINTENANCE_RESULT_NORMAL_REQUESTED = 7,
    E87_MAINTENANCE_RESULT_HANDOFF_WAITING = 8,
    E87_MAINTENANCE_RESULT_HANDOFF_REQUESTED = 9,
    E87_MAINTENANCE_RESULT_HANDOFF_COMMITTED = 10
};

typedef bool (*e87_maintenance_emit_fn)(
    void *context,
    enum e87_maintenance_command command,
    const struct e87_maintenance_handoff *handoff);

struct e87_maintenance_port {
    void *context;
    e87_maintenance_emit_fn emit;
};

struct e87_maintenance_view {
    enum e87_maintenance_state state;
    bool authenticated;
    bool loader_verified;
    bool power_stable;
    struct e87_maintenance_power_sample power;
    uint32_t loader_saddr;
};

struct e87_maintenance {
    struct e87_maintenance_port private_port;
    enum e87_maintenance_state private_state;
    bool private_initialized;
    bool private_in_step;
    bool private_authenticated;
    bool private_loader_verified;
    bool private_power_sample_seen;
    bool private_power_window_active;
    bool private_power_stable;
    bool private_reject_commands_done;
    bool private_advertising_stopped;
    bool private_disconnected;
    bool private_interface_exited;
    uint32_t private_unauthenticated_since_ms;
    uint32_t private_power_eligible_since_ms;
    uint32_t private_rcsp_release_started_ms;
    struct e87_maintenance_power_sample private_power;
    struct e87_rcsp_official_loader_report private_loader;
};

/*
 * Execution contract: init, step, loader callbacks, release polling, and the
 * official handoff commit are serialized on JieLi app_core. ISR or worker-task
 * integrations must post into app_core. private_in_step rejects synchronous
 * callback re-entry; it is not a lock and provides no cross-task exclusion.
 */

bool e87_maintenance_init(
    struct e87_maintenance *maintenance,
    const struct e87_maintenance_port *port);

enum e87_maintenance_result e87_maintenance_step(
    struct e87_maintenance *maintenance,
    const struct e87_maintenance_event *event);

bool e87_maintenance_get_view(
    const struct e87_maintenance *maintenance,
    struct e87_maintenance_view *out);

enum e87_maintenance_result e87_rcsp_official_loader_callback(
    struct e87_maintenance *maintenance,
    uint32_t now_ms,
    const struct e87_rcsp_official_loader_report *report);

enum e87_maintenance_result e87_rcsp_commit_official_handoff(
    struct e87_maintenance *maintenance);

struct e87_rcsp_target_api {
    void *context;
    bool (*bt_rcsp_interface_init)(void *context,
                                   const uint8_t *profile,
                                   const char *local_name);
    bool (*rcsp_init)(void *context);
    bool (*rcsp_bt_ble_init)(void *context);
    bool (*reject_commands)(void *context);
    bool (*stop_advertising)(void *context);
    bool (*disconnect)(void *context);
    bool (*rcsp_bt_ble_exit)(void *context);
    void *(*rcsp_handle_get)(void *context);
    bool (*bt_rcsp_interface_exit)(void *context);
    bool (*request_normal_mode)(void *context);
    /*
     * This callback may only cache/arm the verified address and return. It
     * must not invoke or post the official update handler before returning.
     * That later handler calls e87_rcsp_commit_official_handoff immediately
     * before its irreversible stock update-mode call.
     */
    bool (*approve_official_update_start)(void *context,
                                          uint32_t loader_saddr);
};

struct e87_rcsp_target_adapter {
    struct e87_rcsp_target_api private_api;
    bool private_initialized;
};

bool e87_rcsp_target_maintenance_init(
    struct e87_rcsp_target_adapter *adapter,
    const struct e87_rcsp_target_api *api,
    struct e87_maintenance *maintenance);

enum e87_maintenance_result e87_rcsp_target_poll_release(
    struct e87_rcsp_target_adapter *adapter,
    struct e87_maintenance *maintenance,
    uint32_t now_ms);

#endif
