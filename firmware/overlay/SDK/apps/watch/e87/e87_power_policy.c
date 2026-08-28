#include "e87/e87_power_policy.h"

#include <stddef.h>

static bool valid_state(enum e87_power_state state)
{
    switch (state) {
    case E87_POWER_STATE_ACTIVE:
    case E87_POWER_STATE_WAIT_LCD_IDLE:
    case E87_POWER_STATE_ASLEEP:
    case E87_POWER_STATE_WAIT_WAKE_CLASSIFICATION:
    case E87_POWER_STATE_ERROR:
        return true;
    default:
        return false;
    }
}

static bool valid_charge_phase(enum e87_charge_phase phase)
{
    switch (phase) {
    case E87_CHARGE_PHASE_UNKNOWN:
    case E87_CHARGE_PHASE_CHARGING:
    case E87_CHARGE_PHASE_FULL:
    case E87_CHARGE_PHASE_CLOSED:
    case E87_CHARGE_PHASE_FAULT:
        return true;
    default:
        return false;
    }
}

static bool valid_event_type(enum e87_power_event_type type)
{
    switch (type) {
    case E87_POWER_EVENT_CHARGE_SNAPSHOT:
    case E87_POWER_EVENT_MANUAL_SLEEP:
    case E87_POWER_EVENT_LCD_IDLE:
    case E87_POWER_EVENT_GPIO_WAKE:
    case E87_POWER_EVENT_WAKE_CLASSIFIED:
        return true;
    default:
        return false;
    }
}

static bool valid_wake_classification(
    enum e87_power_wake_classification classification)
{
    switch (classification) {
    case E87_POWER_WAKE_NONE:
    case E87_POWER_WAKE_BUTTON1:
    case E87_POWER_WAKE_BUTTON2:
    case E87_POWER_WAKE_AMBIGUOUS:
    case E87_POWER_WAKE_NOISE:
        return true;
    default:
        return false;
    }
}

static enum e87_power_result emit_sequence(
    struct e87_power_policy *policy,
    const enum e87_power_command *commands,
    size_t command_count,
    enum e87_power_state completed_state,
    enum e87_power_result completed_result)
{
    size_t index;

    for (index = 0U; index < command_count; index += 1U) {
        if (!policy->private_port.emit(
                policy->private_port.context, commands[index])) {
            policy->private_state = E87_POWER_STATE_ERROR;
            return E87_POWER_RESULT_ERROR;
        }
    }
    policy->private_state = completed_state;
    return completed_result;
}

static enum e87_power_result active_step(
    struct e87_power_policy *policy,
    const struct e87_power_event *event)
{
    static const enum e87_power_command sleep_start[] = {
        E87_POWER_COMMAND_STOP_DRAWS,
        E87_POWER_COMMAND_WAIT_LCD_IDLE
    };

    if (event->type != E87_POWER_EVENT_MANUAL_SLEEP) {
        return E87_POWER_RESULT_NO_CHANGE;
    }
    return emit_sequence(
        policy, sleep_start, sizeof(sleep_start) / sizeof(sleep_start[0]),
        E87_POWER_STATE_WAIT_LCD_IDLE,
        E87_POWER_RESULT_WAITING_FOR_LCD);
}

static enum e87_power_result wait_lcd_step(
    struct e87_power_policy *policy,
    const struct e87_power_event *event)
{
    static const enum e87_power_command sleep_finish[] = {
        E87_POWER_COMMAND_BACKLIGHT_OFF,
        E87_POWER_COMMAND_PANEL_SLEEP,
        E87_POWER_COMMAND_BLE_STOP_DISCONNECT,
        E87_POWER_COMMAND_ARM_SHARED_LADDER_WAKE,
        E87_POWER_COMMAND_ENTER_LOW_POWER
    };

    if (event->type != E87_POWER_EVENT_LCD_IDLE) {
        return E87_POWER_RESULT_NO_CHANGE;
    }
    return emit_sequence(
        policy, sleep_finish,
        sizeof(sleep_finish) / sizeof(sleep_finish[0]),
        E87_POWER_STATE_ASLEEP, E87_POWER_RESULT_ASLEEP);
}

static enum e87_power_result asleep_step(
    struct e87_power_policy *policy,
    const struct e87_power_event *event)
{
    static const enum e87_power_command resume_adc[] = {
        E87_POWER_COMMAND_RESUME_ADC
    };

    if (event->type != E87_POWER_EVENT_GPIO_WAKE) {
        return E87_POWER_RESULT_NO_CHANGE;
    }
    return emit_sequence(
        policy, resume_adc, sizeof(resume_adc) / sizeof(resume_adc[0]),
        E87_POWER_STATE_WAIT_WAKE_CLASSIFICATION,
        E87_POWER_RESULT_WAITING_FOR_WAKE_CLASSIFICATION);
}

static enum e87_power_result wait_classification_step(
    struct e87_power_policy *policy,
    const struct e87_power_event *event)
{
    static const enum e87_power_command resume_active[] = {
        E87_POWER_COMMAND_DISPLAY_EXIT_SLEEP,
        E87_POWER_COMMAND_REDRAW,
        E87_POWER_COMMAND_BACKLIGHT_ON,
        E87_POWER_COMMAND_BLE_START
    };
    static const enum e87_power_command return_to_sleep[] = {
        E87_POWER_COMMAND_ARM_SHARED_LADDER_WAKE,
        E87_POWER_COMMAND_ENTER_LOW_POWER
    };

    if (event->type != E87_POWER_EVENT_WAKE_CLASSIFIED) {
        return E87_POWER_RESULT_NO_CHANGE;
    }
    if (event->wake_classification == E87_POWER_WAKE_BUTTON2) {
        return emit_sequence(
            policy, resume_active,
            sizeof(resume_active) / sizeof(resume_active[0]),
            E87_POWER_STATE_ACTIVE, E87_POWER_RESULT_ACTIVE);
    }
    return emit_sequence(
        policy, return_to_sleep,
        sizeof(return_to_sleep) / sizeof(return_to_sleep[0]),
        E87_POWER_STATE_ASLEEP, E87_POWER_RESULT_ASLEEP);
}

static bool valid_charge_snapshot(
    const struct e87_charge_snapshot *snapshot)
{
    uint8_t online_byte;

    if (snapshot == 0) {
        return false;
    }
    online_byte = *((const uint8_t *)&snapshot->external_power_online);
    return online_byte <= UINT8_C(1) && valid_charge_phase(snapshot->phase);
}

static bool equal_charge_snapshot(
    const struct e87_charge_snapshot *left,
    const struct e87_charge_snapshot *right)
{
    return left->external_power_online == right->external_power_online &&
           left->phase == right->phase;
}

bool e87_power_policy_init(struct e87_power_policy *policy,
                           const struct e87_power_port *port,
                           const struct e87_charge_snapshot *initial_snapshot)
{
    struct e87_power_policy initialized = {0};

    if (policy == 0 || port == 0 || port->emit == 0 ||
        !valid_charge_snapshot(initial_snapshot)) {
        return false;
    }
    initialized.private_port = *port;
    initialized.private_state = E87_POWER_STATE_ACTIVE;
    initialized.private_charge_snapshot = *initial_snapshot;
    initialized.private_initialized = true;
    *policy = initialized;
    return true;
}

enum e87_power_result
e87_power_policy_step(struct e87_power_policy *policy,
                      const struct e87_power_event *event)
{
    enum e87_power_result result;

    if (policy == 0 || event == 0 || !policy->private_initialized ||
        policy->private_port.emit == 0 ||
        !valid_state(policy->private_state) ||
        !valid_charge_snapshot(&policy->private_charge_snapshot) ||
        !valid_event_type(event->type) ||
        (event->type == E87_POWER_EVENT_WAKE_CLASSIFIED &&
         !valid_wake_classification(event->wake_classification))) {
        return E87_POWER_RESULT_ERROR;
    }
    if (policy->private_in_step ||
        policy->private_state == E87_POWER_STATE_ERROR) {
        return E87_POWER_RESULT_ERROR;
    }

    policy->private_in_step = true;
    if (event->type == E87_POWER_EVENT_CHARGE_SNAPSHOT) {
        if (!valid_charge_snapshot(&event->charge_snapshot)) {
            policy->private_in_step = false;
            return E87_POWER_RESULT_ERROR;
        }
        if (equal_charge_snapshot(&policy->private_charge_snapshot,
                                  &event->charge_snapshot)) {
            result = E87_POWER_RESULT_NO_CHANGE;
        } else {
            policy->private_charge_snapshot = event->charge_snapshot;
            result = E87_POWER_RESULT_STATUS_UPDATED;
        }
    } else {
        switch (policy->private_state) {
        case E87_POWER_STATE_ACTIVE:
            result = active_step(policy, event);
            break;
        case E87_POWER_STATE_WAIT_LCD_IDLE:
            result = wait_lcd_step(policy, event);
            break;
        case E87_POWER_STATE_ASLEEP:
            result = asleep_step(policy, event);
            break;
        case E87_POWER_STATE_WAIT_WAKE_CLASSIFICATION:
            result = wait_classification_step(policy, event);
            break;
        case E87_POWER_STATE_ERROR:
        default:
            result = E87_POWER_RESULT_ERROR;
            break;
        }
    }
    policy->private_in_step = false;
    return result;
}

bool e87_power_policy_get_view(const struct e87_power_policy *policy,
                               struct e87_power_view *out)
{
    struct e87_power_view view;

    if (policy == 0 || out == 0 || !policy->private_initialized ||
        !valid_state(policy->private_state) ||
        !valid_charge_snapshot(&policy->private_charge_snapshot)) {
        return false;
    }
    view.state = policy->private_state;
    view.charge_snapshot = policy->private_charge_snapshot;
    *out = view;
    return true;
}
