#ifndef E87_APP_CORE_H
#define E87_APP_CORE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "e87/e87_ble_mode_fsm.h"
#include "e87/e87_button_classifier.h"
#include "e87/e87_button_fsm.h"
#include "e87/e87_maintenance.h"
#include "e87/e87_power_policy.h"
#include "e87/e87_recovery.h"
#include "e87/e87_state.h"
#include "e87/e87_ui.h"

#define E87_APP_CORE_FAIL_CLOSED_CLEANUP_CAPACITY 4u
#define E87_APP_CORE_DEFERRED_MAINTENANCE_CAPACITY 4u

enum e87_app_core_phase {
    E87_APP_CORE_PHASE_READY = 0,
    E87_APP_CORE_PHASE_NORMAL = 1,
    E87_APP_CORE_PHASE_ENTERING_MAINTENANCE = 2,
    E87_APP_CORE_PHASE_MAINTENANCE = 3,
    E87_APP_CORE_PHASE_RETURNING_NORMAL = 4,
    E87_APP_CORE_PHASE_FAIL_CLOSED = 5
};

enum e87_app_core_result {
    E87_APP_CORE_RESULT_ERROR = 0,
    E87_APP_CORE_RESULT_NO_CHANGE = 1,
    E87_APP_CORE_RESULT_UPDATED = 2,
    E87_APP_CORE_RESULT_WAITING = 3,
    E87_APP_CORE_RESULT_REENTRANT = 4,
    E87_APP_CORE_RESULT_FAIL_CLOSED = 5
};

enum e87_app_core_event_type {
    E87_APP_CORE_EVENT_BOOT = 0,
    E87_APP_CORE_EVENT_POLL = 1,
    E87_APP_CORE_EVENT_BUTTON_ADC_SAMPLE = 2,
    E87_APP_CORE_EVENT_SEMANTIC_PACKET = 3,
    E87_APP_CORE_EVENT_POWER = 4,
    E87_APP_CORE_EVENT_MAINTENANCE = 5,
    E87_APP_CORE_EVENT_PROFILE_CONNECTED = 6,
    E87_APP_CORE_EVENT_PROFILE_DISCONNECTED = 7,
    E87_APP_CORE_EVENT_BOND_CHANGED = 8,
    E87_APP_CORE_EVENT_MAINTENANCE_LOADER_REPORT = 9,
    E87_APP_CORE_EVENT_MAINTENANCE_COMMIT_HANDOFF = 10,
    E87_APP_CORE_EVENT_BATTERY = 11,
    E87_APP_CORE_EVENT_MAINTENANCE_UI = 12
};

struct e87_app_core_boot_event {
    bool has_bond;
    enum e87_recovery_reset_cause reset_cause;
    enum e87_key_class key;
    struct e87_charge_snapshot charge_snapshot;
};

struct e87_app_core_semantic_event {
    uint32_t authorization_epoch;
    uint8_t packet[E87_STATE_PACKET_SIZE];
};

struct e87_app_core_profile_link_event {
    const void *app_handle;
    uint16_t connection_handle;
};

struct e87_app_core_battery_event {
    enum e87_ui_battery_state state;
    uint8_t percent;
};

struct e87_app_core_maintenance_ui_event {
    enum e87_ui_maintenance_phase phase;
    uint8_t progress_percent;
};

struct e87_app_core_event {
    enum e87_app_core_event_type type;
    uint32_t now_ms;
    union {
        struct e87_app_core_boot_event boot;
        uint32_t raw_adc;
        struct e87_app_core_semantic_event semantic;
        struct e87_power_event power;
        struct e87_maintenance_event maintenance;
        struct e87_app_core_profile_link_event profile_link;
        bool has_bond;
        struct e87_rcsp_official_loader_report loader_report;
        struct e87_app_core_battery_event battery;
        struct e87_app_core_maintenance_ui_event maintenance_ui;
    } data;
};

enum e87_app_core_effect_type {
    E87_APP_CORE_EFFECT_DRAW = 0,
    E87_APP_CORE_EFFECT_PAIRING = 1,
    E87_APP_CORE_EFFECT_POWER = 2,
    E87_APP_CORE_EFFECT_RECOVERY = 3,
    E87_APP_CORE_EFFECT_BLE_SET_ADVERTISING = 4,
    E87_APP_CORE_EFFECT_BLE_SET_WRITES = 5,
    E87_APP_CORE_EFFECT_BLE_REQUEST_DISCONNECT = 6,
    E87_APP_CORE_EFFECT_BLE_RELEASE_PROFILE = 7,
    E87_APP_CORE_EFFECT_BLE_INITIALIZE_NORMAL_PROFILE = 8,
    E87_APP_CORE_EFFECT_BLE_ADOPT_MAINTENANCE_PROFILE = 9,
    E87_APP_CORE_EFFECT_BLE_VERIFY_MAINTENANCE_ADVERTISING = 10,
    E87_APP_CORE_EFFECT_BLE_VERIFY_MAINTENANCE_STOPPED = 11,
    E87_APP_CORE_EFFECT_BLE_VERIFY_MAINTENANCE_RELEASED = 12,
    E87_APP_CORE_EFFECT_MAINTENANCE = 13
};

struct e87_app_core_effect {
    enum e87_app_core_effect_type type;
    uint32_t now_ms;
    union {
        struct {
            struct e87_render_model model;
        } draw;
        struct {
            bool enabled;
        } pairing;
        struct {
            enum e87_power_command command;
        } power;
        struct {
            enum e87_recovery_command command;
        } recovery;
        struct {
            enum e87_ble_mode mode;
            bool enabled;
        } advertising;
        struct {
            bool enabled;
            uint32_t authorization_epoch;
        } writes;
        struct {
            enum e87_ble_mode mode;
            const void *app_handle;
            uint16_t connection_handle;
        } disconnect;
        struct {
            enum e87_ble_mode mode;
            const void *app_handle;
        } profile;
        struct {
            enum e87_maintenance_command command;
            bool has_handoff;
            struct e87_maintenance_handoff handoff;
        } maintenance;
    } data;
};

typedef bool (*e87_app_core_emit_fn)(
    void *context,
    struct e87_app_core_effect *effect);
typedef bool (*e87_app_core_authorization_epoch_active_fn)(
    void *context,
    uint32_t authorization_epoch);

struct e87_app_core_port {
    void *context;
    e87_app_core_emit_fn emit;
    e87_app_core_authorization_epoch_active_fn
        authorization_epoch_is_active;
};

struct e87_app_core_config {
    struct e87_button_classifier_config button_classifier;
};

struct e87_app_core_view {
    enum e87_app_core_phase phase;
    struct e87_state_snapshot semantic;
    enum e87_ble_mode ble_mode;
    bool manual_sleep;
    bool drawing_enabled;
    bool external_power_online;
    struct e87_render_model render_model;
};

struct e87_app_core {
    struct e87_app_core_port private_port;
    struct e87_state_store private_state;
    struct e87_ui_state private_ui;
    struct e87_button_classifier private_classifier;
    struct e87_button_fsm private_button;
    struct e87_power_policy private_power;
    struct e87_recovery_fsm private_recovery;
    struct e87_ble_mode_fsm private_ble;
    struct e87_maintenance private_maintenance;
    struct e87_render_model private_render_model;
    struct e87_maintenance_event
        private_fail_closed_cleanup[
            E87_APP_CORE_FAIL_CLOSED_CLEANUP_CAPACITY];
    struct e87_maintenance_event
        private_deferred_maintenance[
            E87_APP_CORE_DEFERRED_MAINTENANCE_CAPACITY];
    enum e87_app_core_phase private_phase;
    enum e87_key_class private_current_key;
    enum e87_ui_battery_state private_battery_state;
    enum e87_ui_maintenance_phase private_maintenance_phase;
    uint8_t private_battery_percent;
    uint8_t private_maintenance_progress_percent;
    uint8_t private_fail_closed_cleanup_head;
    uint8_t private_fail_closed_cleanup_count;
    uint8_t private_deferred_maintenance_head;
    uint8_t private_deferred_maintenance_count;
    uint32_t private_now_ms;
    uint32_t private_effect_generation;
    uint32_t private_authorization_epoch;
    bool private_initialized;
    bool private_in_step;
    bool private_booted;
    bool private_have_time;
    bool private_has_bond;
    bool private_panel_visible;
    bool private_drawing_enabled;
    bool private_manual_sleep;
    bool private_ble_initialized;
    bool private_maintenance_active;
    bool private_pending_maintenance_exit_valid;
    bool private_recovery_entry;
    bool private_maintenance_authorized;
    bool private_normal_stop_reported;
    bool private_effect_failed;
    bool private_render_model_valid;
    bool private_authorization_epoch_known;
    bool private_normal_writes_enabled;
    bool private_shutdown_draws_stopped;
    bool private_shutdown_writes_closed;
    bool private_shutdown_advertising_stopped;
};

bool e87_app_core_init(struct e87_app_core *core,
                       const struct e87_app_core_config *config,
                       const struct e87_app_core_port *port);

enum e87_app_core_result e87_app_core_step(
    struct e87_app_core *core,
    const struct e87_app_core_event *event);

bool e87_app_core_get_view(const struct e87_app_core *core,
                           struct e87_app_core_view *out);

#endif
