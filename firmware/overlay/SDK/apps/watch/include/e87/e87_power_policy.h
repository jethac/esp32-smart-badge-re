#ifndef E87_POWER_POLICY_H
#define E87_POWER_POLICY_H

#include <stdbool.h>

enum e87_charger_phase {
    E87_CHARGER_PHASE_UNKNOWN = 0,
    E87_CHARGER_PHASE_START = 1,
    E87_CHARGER_PHASE_FULL = 2,
    E87_CHARGER_PHASE_CLOSE = 3
};

enum e87_power_wake_classification {
    E87_POWER_WAKE_NONE = 0,
    E87_POWER_WAKE_BUTTON1 = 1,
    E87_POWER_WAKE_BUTTON2 = 2,
    E87_POWER_WAKE_AMBIGUOUS = 3,
    E87_POWER_WAKE_NOISE = 4
};

enum e87_power_event_type {
    E87_POWER_EVENT_EXTERNAL_POWER_CHANGED = 0,
    E87_POWER_EVENT_CHARGER_START = 1,
    E87_POWER_EVENT_CHARGER_FULL = 2,
    E87_POWER_EVENT_CHARGER_CLOSE = 3,
    E87_POWER_EVENT_MANUAL_SLEEP = 4,
    E87_POWER_EVENT_LCD_IDLE = 5,
    E87_POWER_EVENT_GPIO_WAKE = 6,
    E87_POWER_EVENT_WAKE_CLASSIFIED = 7
};

struct e87_power_event {
    enum e87_power_event_type type;
    bool external_power_online;
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
    E87_POWER_COMMAND_BLE_START = 11
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
    bool external_power_online;
    enum e87_charger_phase charger_phase;
};

struct e87_power_policy {
    struct e87_power_port private_port;
    enum e87_power_state private_state;
    enum e87_charger_phase private_charger_phase;
    bool private_external_power_online;
    bool private_initialized;
    bool private_in_step;
};

bool e87_power_policy_init(struct e87_power_policy *policy,
                           const struct e87_power_port *port,
                           bool external_power_online);

enum e87_power_result
e87_power_policy_step(struct e87_power_policy *policy,
                      const struct e87_power_event *event);

bool e87_power_policy_get_view(const struct e87_power_policy *policy,
                               struct e87_power_view *out);

#endif
