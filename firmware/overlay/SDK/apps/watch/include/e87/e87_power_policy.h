#ifndef E87_POWER_POLICY_H
#define E87_POWER_POLICY_H

#include <stdbool.h>
#include "e87/e87_charge_adapter.h"

enum e87_power_wake_classification {
    E87_POWER_WAKE_NONE = 0,
    E87_POWER_WAKE_BUTTON1 = 1,
    E87_POWER_WAKE_BUTTON2 = 2,
    E87_POWER_WAKE_AMBIGUOUS = 3,
    E87_POWER_WAKE_NOISE = 4
};

enum e87_power_event_type {
    E87_POWER_EVENT_CHARGE_SNAPSHOT = 0,
    E87_POWER_EVENT_MANUAL_SLEEP = 1,
    E87_POWER_EVENT_LCD_IDLE = 2,
    E87_POWER_EVENT_GPIO_WAKE = 3,
    E87_POWER_EVENT_WAKE_CLASSIFIED = 4
};

struct e87_power_event {
    enum e87_power_event_type type;
    struct e87_charge_snapshot charge_snapshot;
    enum e87_power_wake_classification wake_classification;
};

enum e87_power_command {
    E87_POWER_COMMAND_STOP_DRAWS = 0,
    E87_POWER_COMMAND_WAIT_LCD_IDLE = 1,
    E87_POWER_COMMAND_PANEL_SLEEP = 2,
    E87_POWER_COMMAND_BACKLIGHT_OFF = 3,
    E87_POWER_COMMAND_BLE_STOP_DISCONNECT = 4,
    E87_POWER_COMMAND_ARM_SHARED_LADDER_WAKE = 5,
    E87_POWER_COMMAND_ENTER_LOW_POWER = 6,
    E87_POWER_COMMAND_RESUME_ADC = 7,
    E87_POWER_COMMAND_DISPLAY_EXIT_SLEEP = 8,
    E87_POWER_COMMAND_REDRAW = 9,
    E87_POWER_COMMAND_BACKLIGHT_ON = 10,
    E87_POWER_COMMAND_BLE_START = 11,
    E87_POWER_COMMAND_COUNT
};

enum e87_power_result {
    E87_POWER_RESULT_ERROR = 0,
    E87_POWER_RESULT_NO_CHANGE = 1,
    E87_POWER_RESULT_STATUS_UPDATED = 2,
    E87_POWER_RESULT_WAITING_FOR_LCD = 3,
    E87_POWER_RESULT_ASLEEP = 4,
    E87_POWER_RESULT_WAITING_FOR_WAKE_CLASSIFICATION = 5,
    E87_POWER_RESULT_ACTIVE = 6
};

enum e87_power_state {
    E87_POWER_STATE_ACTIVE = 0,
    E87_POWER_STATE_WAIT_LCD_IDLE = 1,
    E87_POWER_STATE_ASLEEP = 2,
    E87_POWER_STATE_WAIT_WAKE_CLASSIFICATION = 3,
    E87_POWER_STATE_ERROR = 4
};

typedef bool (*e87_power_emit_fn)(
    void *context,
    enum e87_power_command command);

struct e87_power_port {
    void *context;
    e87_power_emit_fn emit;
};

struct e87_power_view {
    enum e87_power_state state;
    struct e87_charge_snapshot charge_snapshot;
};

struct e87_power_policy {
    struct e87_power_port private_port;
    enum e87_power_state private_state;
    struct e87_charge_snapshot private_charge_snapshot;
    bool private_initialized;
    bool private_in_step;
};

bool e87_power_policy_init(struct e87_power_policy *policy,
                           const struct e87_power_port *port,
                           const struct e87_charge_snapshot *initial_snapshot);

enum e87_power_result
e87_power_policy_step(struct e87_power_policy *policy,
                      const struct e87_power_event *event);

bool e87_power_policy_get_view(const struct e87_power_policy *policy,
                               struct e87_power_view *out);

#endif
