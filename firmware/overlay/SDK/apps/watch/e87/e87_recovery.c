#include "e87/e87_recovery.h"

static bool valid_event_type(enum e87_recovery_event_type type)
{
    switch (type) {
    case E87_RECOVERY_EVENT_BOOT:
    case E87_RECOVERY_EVENT_HEALTHY_MAINTENANCE:
    case E87_RECOVERY_EVENT_NORMAL_MODE_STOPPED:
    case E87_RECOVERY_EVENT_NORMAL_MODE_STOP_FAILED:
    case E87_RECOVERY_EVENT_POLL:
        return true;
    default:
        return false;
    }
}

static bool valid_reset_cause(enum e87_recovery_reset_cause cause)
{
    switch (cause) {
    case E87_RESET_CAUSE_POWER_ON:
    case E87_RESET_CAUSE_SOFTWARE:
    case E87_RESET_CAUSE_WATCHDOG:
    case E87_RESET_CAUSE_P33_PPINR:
    case E87_RESET_CAUSE_OTHER:
        return true;
    default:
        return false;
    }
}

static bool valid_state(enum e87_recovery_state state)
{
    switch (state) {
    case E87_RECOVERY_STATE_READY:
    case E87_RECOVERY_STATE_NORMAL:
    case E87_RECOVERY_STATE_HEALTHY_STOPPING:
    case E87_RECOVERY_STATE_PINR_WAIT_RELEASE:
    case E87_RECOVERY_STATE_FAIL_SAFE_WAIT_RELEASE:
    case E87_RECOVERY_STATE_MAINTENANCE:
    case E87_RECOVERY_STATE_FAIL_SAFE_REARMED:
    case E87_RECOVERY_STATE_ERROR:
        return true;
    default:
        return false;
    }
}

static bool is_released(enum e87_key_class key)
{
    return key == E87_KEY_NONE;
}

static bool emit_command(struct e87_recovery_fsm *fsm,
                         enum e87_recovery_command command)
{
    const bool accepted =
        fsm->private_port.emit(fsm->private_port.context, command);

    if (accepted) {
        if (command == E87_RECOVERY_COMMAND_DISARM_PB08_RESET) {
            fsm->private_reset_ownership =
                E87_RESET_OWNERSHIP_DISARMED;
        } else if (command ==
                   E87_RECOVERY_COMMAND_ARM_PB08_RESET_16S) {
            fsm->private_reset_ownership =
                E87_RESET_OWNERSHIP_ARMED;
        }
    }
    return accepted;
}

static enum e87_recovery_result enter_fail_safe(
    struct e87_recovery_fsm *fsm)
{
    fsm->private_state = E87_RECOVERY_STATE_FAIL_SAFE_WAIT_RELEASE;
    return E87_RECOVERY_RESULT_FAIL_SAFE_WAITING;
}

static enum e87_recovery_result arm_then_maintenance(
    struct e87_recovery_fsm *fsm)
{
    if (!emit_command(fsm,
                      E87_RECOVERY_COMMAND_ARM_PB08_RESET_16S)) {
        return enter_fail_safe(fsm);
    }
    if (!emit_command(fsm,
                      E87_RECOVERY_COMMAND_REQUEST_MAINTENANCE)) {
        fsm->private_state = E87_RECOVERY_STATE_ERROR;
        return E87_RECOVERY_RESULT_ERROR;
    }

    fsm->private_state = E87_RECOVERY_STATE_MAINTENANCE;
    return E87_RECOVERY_RESULT_MAINTENANCE_REQUESTED;
}

static enum e87_recovery_result feed_while_waiting(
    struct e87_recovery_fsm *fsm,
    enum e87_recovery_state intended_state)
{
    fsm->private_state = intended_state;
    if (!emit_command(fsm, E87_RECOVERY_COMMAND_FEED_WATCHDOG)) {
        return enter_fail_safe(fsm);
    }
    return E87_RECOVERY_RESULT_WAITING;
}

static enum e87_recovery_result fail_safe_step(
    struct e87_recovery_fsm *fsm,
    const struct e87_recovery_event *event)
{
    fsm->private_state = E87_RECOVERY_STATE_FAIL_SAFE_WAIT_RELEASE;
    if (is_released(event->key)) {
        if (!emit_command(fsm,
                          E87_RECOVERY_COMMAND_ARM_PB08_RESET_16S)) {
            return E87_RECOVERY_RESULT_FAIL_SAFE_WAITING;
        }
        fsm->private_state = E87_RECOVERY_STATE_FAIL_SAFE_REARMED;
        return E87_RECOVERY_RESULT_FAIL_SAFE_REARMED;
    }

    (void)emit_command(fsm, E87_RECOVERY_COMMAND_FEED_WATCHDOG);
    return E87_RECOVERY_RESULT_FAIL_SAFE_WAITING;
}

static enum e87_recovery_result boot_step(
    struct e87_recovery_fsm *fsm,
    const struct e87_recovery_event *event)
{
    fsm->private_reset_ownership = E87_RESET_OWNERSHIP_UNKNOWN;
    if (!emit_command(fsm,
                      E87_RECOVERY_COMMAND_DISARM_PB08_RESET)) {
        fsm->private_state = E87_RECOVERY_STATE_ERROR;
        return E87_RECOVERY_RESULT_ERROR;
    }

    if (event->reset_cause != E87_RESET_CAUSE_P33_PPINR) {
        if (!emit_command(fsm,
                          E87_RECOVERY_COMMAND_ARM_PB08_RESET_16S)) {
            return enter_fail_safe(fsm);
        }
        fsm->private_state = E87_RECOVERY_STATE_NORMAL;
        return E87_RECOVERY_RESULT_NORMAL_BOOT;
    }
    if (is_released(event->key)) {
        return arm_then_maintenance(fsm);
    }
    return feed_while_waiting(
        fsm, E87_RECOVERY_STATE_PINR_WAIT_RELEASE);
}

static enum e87_recovery_result healthy_step(
    struct e87_recovery_fsm *fsm,
    const struct e87_recovery_event *event)
{
    fsm->private_state = E87_RECOVERY_STATE_HEALTHY_STOPPING;
    fsm->private_stop_started_ms = event->now_ms;
    fsm->private_normal_stopped = false;
    fsm->private_release_latched = is_released(event->key);

    if (!emit_command(fsm,
                      E87_RECOVERY_COMMAND_DISARM_PB08_RESET)) {
        fsm->private_state = E87_RECOVERY_STATE_ERROR;
        return E87_RECOVERY_RESULT_ERROR;
    }
    if (!emit_command(fsm,
                      E87_RECOVERY_COMMAND_REQUEST_NORMAL_STOP)) {
        return enter_fail_safe(fsm);
    }
    if (!emit_command(fsm,
                      E87_RECOVERY_COMMAND_FEED_WATCHDOG)) {
        return enter_fail_safe(fsm);
    }
    return E87_RECOVERY_RESULT_WAITING;
}

static enum e87_recovery_result stopping_step(
    struct e87_recovery_fsm *fsm,
    const struct e87_recovery_event *event)
{
    const uint32_t elapsed =
        (uint32_t)(event->now_ms - fsm->private_stop_started_ms);

    fsm->private_release_latched = is_released(event->key);
    if (event->type == E87_RECOVERY_EVENT_NORMAL_MODE_STOPPED &&
        elapsed <= E87_NORMAL_STOP_TIMEOUT_MS) {
        fsm->private_normal_stopped = true;
    }

    if (fsm->private_normal_stopped) {
        if (fsm->private_release_latched) {
            return arm_then_maintenance(fsm);
        }
        return feed_while_waiting(
            fsm, E87_RECOVERY_STATE_HEALTHY_STOPPING);
    }
    if (event->type == E87_RECOVERY_EVENT_NORMAL_MODE_STOP_FAILED ||
        elapsed >= E87_NORMAL_STOP_TIMEOUT_MS) {
        return fail_safe_step(fsm, event);
    }
    return feed_while_waiting(
        fsm, E87_RECOVERY_STATE_HEALTHY_STOPPING);
}

static enum e87_recovery_result pinr_step(
    struct e87_recovery_fsm *fsm,
    const struct e87_recovery_event *event)
{
    if (is_released(event->key)) {
        return arm_then_maintenance(fsm);
    }
    return feed_while_waiting(
        fsm, E87_RECOVERY_STATE_PINR_WAIT_RELEASE);
}

bool e87_recovery_init(struct e87_recovery_fsm *fsm,
                       const struct e87_recovery_port *port)
{
    struct e87_recovery_fsm initialized = {0};

    if (fsm == 0 || port == 0 || port->emit == 0) {
        return false;
    }

    initialized.private_port = *port;
    initialized.private_state = E87_RECOVERY_STATE_READY;
    initialized.private_initialized = true;
    initialized.private_reset_ownership =
        E87_RESET_OWNERSHIP_UNKNOWN;
    *fsm = initialized;
    return true;
}

enum e87_recovery_result
e87_recovery_step(struct e87_recovery_fsm *fsm,
                  const struct e87_recovery_event *event)
{
    enum e87_recovery_result result;

    if (fsm == 0 || event == 0 ||
        !fsm->private_initialized ||
        fsm->private_port.emit == 0 ||
        !valid_event_type(event->type) ||
        !valid_reset_cause(event->reset_cause) ||
        !valid_state(fsm->private_state)) {
        return E87_RECOVERY_RESULT_ERROR;
    }
    if (fsm->private_in_step) {
        return E87_RECOVERY_RESULT_ERROR;
    }

    fsm->private_in_step = true;
    switch (fsm->private_state) {
    case E87_RECOVERY_STATE_READY:
        result = event->type == E87_RECOVERY_EVENT_BOOT
                     ? boot_step(fsm, event)
                     : E87_RECOVERY_RESULT_NO_CHANGE;
        break;
    case E87_RECOVERY_STATE_NORMAL:
        result =
            event->type == E87_RECOVERY_EVENT_HEALTHY_MAINTENANCE
                ? healthy_step(fsm, event)
                : E87_RECOVERY_RESULT_NO_CHANGE;
        break;
    case E87_RECOVERY_STATE_HEALTHY_STOPPING:
        result = stopping_step(fsm, event);
        break;
    case E87_RECOVERY_STATE_PINR_WAIT_RELEASE:
        result = pinr_step(fsm, event);
        break;
    case E87_RECOVERY_STATE_FAIL_SAFE_WAIT_RELEASE:
        result = fail_safe_step(fsm, event);
        break;
    case E87_RECOVERY_STATE_MAINTENANCE:
    case E87_RECOVERY_STATE_FAIL_SAFE_REARMED:
        result = E87_RECOVERY_RESULT_NO_CHANGE;
        break;
    case E87_RECOVERY_STATE_ERROR:
    default:
        result = E87_RECOVERY_RESULT_ERROR;
        break;
    }
    fsm->private_in_step = false;
    return result;
}

enum e87_reset_ownership
e87_recovery_get_reset_ownership(
    const struct e87_recovery_fsm *fsm)
{
    if (fsm == 0 || !fsm->private_initialized) {
        return E87_RESET_OWNERSHIP_UNKNOWN;
    }
    return fsm->private_reset_ownership;
}
