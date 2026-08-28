#include "e87/e87_maintenance.h"

#include <string.h>

static const uint8_t expected_profile_id[E87_RCSP_PROFILE_ID_BYTES] = {
    'E', '8', '7', '-', 'J', 'D', '9', '8',
    '5', '5', '-', 'R', '1', 0, 0, 0
};

static bool valid_state(enum e87_maintenance_state state)
{
    switch (state) {
    case E87_MAINTENANCE_STATE_READY:
    case E87_MAINTENANCE_STATE_ACTIVE:
    case E87_MAINTENANCE_STATE_EXITING:
    case E87_MAINTENANCE_STATE_WAIT_RCSP_RELEASE:
    case E87_MAINTENANCE_STATE_NORMAL_REQUESTED:
    case E87_MAINTENANCE_STATE_HANDOFF_APPROVED:
    case E87_MAINTENANCE_STATE_HANDED_OFF:
    case E87_MAINTENANCE_STATE_ERROR:
        return true;
    default:
        return false;
    }
}

static bool valid_event_type(enum e87_maintenance_event_type type)
{
    switch (type) {
    case E87_MAINTENANCE_EVENT_ENTER_AFTER_NORMAL_DISCONNECT:
    case E87_MAINTENANCE_EVENT_POLL:
    case E87_MAINTENANCE_EVENT_AUTHENTICATED:
    case E87_MAINTENANCE_EVENT_HOST_DISCONNECTED:
    case E87_MAINTENANCE_EVENT_CANCEL:
    case E87_MAINTENANCE_EVENT_FAILURE:
    case E87_MAINTENANCE_EVENT_TRANSPORT_QUIESCED:
    case E87_MAINTENANCE_EVENT_POWER_SAMPLE:
    case E87_MAINTENANCE_EVENT_RCSP_RELEASE_STATUS:
        return true;
    default:
        return false;
    }
}

static bool valid_charger_phase(enum e87_charger_phase phase)
{
    switch (phase) {
    case E87_CHARGER_PHASE_UNKNOWN:
    case E87_CHARGER_PHASE_START:
    case E87_CHARGER_PHASE_FULL:
    case E87_CHARGER_PHASE_CLOSE:
        return true;
    default:
        return false;
    }
}

static bool valid_power_sample(
    const struct e87_maintenance_power_sample *power)
{
    return power != 0 && power->percent <= UINT8_C(100) &&
           valid_charger_phase(power->charger_phase);
}

static bool valid_loader_report(
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

static bool power_is_eligible(
    const struct e87_maintenance_power_sample *power)
{
    return power->percent >= E87_MAINTENANCE_MIN_BATTERY_PERCENT &&
           !power->low_voltage_warning && power->board_voltage_stable;
}

static bool elapsed_is_forward(uint32_t now_ms,
                               uint32_t since_ms,
                               uint32_t *elapsed_ms)
{
    const uint32_t elapsed = (uint32_t)(now_ms - since_ms);

    if (elapsed > UINT32_C(0x7fffffff)) {
        return false;
    }
    if (elapsed_ms != 0) {
        *elapsed_ms = elapsed;
    }
    return true;
}

static bool elapsed_reached(uint32_t now_ms,
                            uint32_t since_ms,
                            uint32_t required_ms)
{
    uint32_t elapsed_ms;

    return elapsed_is_forward(now_ms, since_ms, &elapsed_ms) &&
           elapsed_ms >= required_ms;
}

static bool emit_command(
    struct e87_maintenance *maintenance,
    enum e87_maintenance_command command,
    const struct e87_maintenance_handoff *handoff)
{
    return maintenance->private_port.emit(
        maintenance->private_port.context, command, handoff);
}

static bool emit_plain_sequence(
    struct e87_maintenance *maintenance,
    const enum e87_maintenance_command *commands,
    size_t count)
{
    size_t index;

    for (index = 0U; index < count; index += 1U) {
        if (!emit_command(maintenance, commands[index], 0)) {
            return false;
        }
    }
    return true;
}

static enum e87_maintenance_result begin_exit(
    struct e87_maintenance *maintenance)
{
    bool all_complete = true;

    if (maintenance->private_state != E87_MAINTENANCE_STATE_EXITING) {
        maintenance->private_reject_commands_done = false;
        maintenance->private_advertising_stopped = false;
        maintenance->private_disconnected = false;
        maintenance->private_interface_exited = false;
    }
    maintenance->private_state = E87_MAINTENANCE_STATE_EXITING;

    maintenance->private_authenticated = false;
    maintenance->private_loader_verified = false;
    memset(&maintenance->private_loader, 0,
           sizeof(maintenance->private_loader));
    if (!maintenance->private_reject_commands_done) {
        maintenance->private_reject_commands_done = emit_command(
            maintenance, E87_MAINTENANCE_COMMAND_REJECT_COMMANDS, 0);
        all_complete = maintenance->private_reject_commands_done;
    }
    if (!maintenance->private_advertising_stopped) {
        maintenance->private_advertising_stopped = emit_command(
            maintenance, E87_MAINTENANCE_COMMAND_STOP_ADVERTISING, 0);
        all_complete = maintenance->private_advertising_stopped &&
                       all_complete;
    }
    if (!maintenance->private_disconnected) {
        maintenance->private_disconnected = emit_command(
            maintenance, E87_MAINTENANCE_COMMAND_DISCONNECT, 0);
        all_complete = maintenance->private_disconnected && all_complete;
    }
    return all_complete ? E87_MAINTENANCE_RESULT_EXITING
                        : E87_MAINTENANCE_RESULT_ERROR;
}

static enum e87_maintenance_result enter_maintenance(
    struct e87_maintenance *maintenance,
    uint32_t now_ms)
{
    static const enum e87_maintenance_command commands[] = {
        E87_MAINTENANCE_COMMAND_RCSP_INTERFACE_INIT,
        E87_MAINTENANCE_COMMAND_RCSP_INIT,
        E87_MAINTENANCE_COMMAND_RCSP_BLE_INIT
    };

    if (!emit_plain_sequence(
            maintenance, commands, sizeof(commands) / sizeof(commands[0]))) {
        (void)begin_exit(maintenance);
        return E87_MAINTENANCE_RESULT_ERROR;
    }
    maintenance->private_state = E87_MAINTENANCE_STATE_ACTIVE;
    maintenance->private_unauthenticated_since_ms = now_ms;
    return E87_MAINTENANCE_RESULT_ACTIVE;
}

static enum e87_maintenance_result request_handoff(
    struct e87_maintenance *maintenance,
    enum e87_maintenance_result waiting_result)
{
    struct e87_maintenance_handoff handoff = {0};

    if (!maintenance->private_authenticated ||
        !maintenance->private_loader_verified ||
        !maintenance->private_power_stable) {
        return waiting_result;
    }
    handoff.official_loader_verified = true;
    handoff.update_type = maintenance->private_loader.update_type;
    handoff.update_state = maintenance->private_loader.update_state;
    handoff.loader_result = maintenance->private_loader.loader_result;
    handoff.loader_saddr = maintenance->private_loader.loader_saddr;
    handoff.battery_percent = maintenance->private_power.percent;
    handoff.low_voltage_warning =
        maintenance->private_power.low_voltage_warning;
    handoff.board_voltage_stable =
        maintenance->private_power.board_voltage_stable;
    handoff.power_stable_for_required_window =
        maintenance->private_power_stable;
    handoff.chip = maintenance->private_loader.chip;
    handoff.layout = maintenance->private_loader.layout;
    handoff.exact_layout_match =
        maintenance->private_loader.exact_layout_match;
    memcpy(handoff.profile_id, maintenance->private_loader.profile_id,
           sizeof(handoff.profile_id));

    if (!emit_command(maintenance,
                      E87_MAINTENANCE_COMMAND_OFFICIAL_HANDOFF,
                      &handoff)) {
        (void)begin_exit(maintenance);
        return E87_MAINTENANCE_RESULT_ERROR;
    }
    maintenance->private_state = E87_MAINTENANCE_STATE_HANDOFF_APPROVED;
    return E87_MAINTENANCE_RESULT_HANDOFF_REQUESTED;
}

static void refresh_power(
    struct e87_maintenance *maintenance,
    const struct e87_maintenance_event *event)
{
    uint32_t elapsed_ms;

    maintenance->private_power = event->power;
    maintenance->private_power_sample_seen = true;
    if (!power_is_eligible(&event->power)) {
        maintenance->private_power_window_active = false;
        maintenance->private_power_stable = false;
        return;
    }
    if (!maintenance->private_power_window_active) {
        maintenance->private_power_window_active = true;
        maintenance->private_power_stable = false;
        maintenance->private_power_eligible_since_ms = event->now_ms;
    } else if (!elapsed_is_forward(
                   event->now_ms,
                   maintenance->private_power_eligible_since_ms,
                   &elapsed_ms)) {
        maintenance->private_power_stable = false;
        maintenance->private_power_eligible_since_ms = event->now_ms;
    } else if (elapsed_ms >= E87_MAINTENANCE_POWER_STABLE_MS) {
        maintenance->private_power_stable = true;
    }
}

static enum e87_maintenance_result update_power(
    struct e87_maintenance *maintenance,
    const struct e87_maintenance_event *event)
{
    refresh_power(maintenance, event);
    return request_handoff(
        maintenance, E87_MAINTENANCE_RESULT_STATUS_UPDATED);
}

static enum e87_maintenance_result active_step(
    struct e87_maintenance *maintenance,
    const struct e87_maintenance_event *event)
{
    switch (event->type) {
    case E87_MAINTENANCE_EVENT_POLL:
        if (!maintenance->private_authenticated &&
            elapsed_reached(
                event->now_ms,
                maintenance->private_unauthenticated_since_ms,
                E87_MAINTENANCE_TIMEOUT_MS)) {
            return begin_exit(maintenance);
        }
        return E87_MAINTENANCE_RESULT_NO_CHANGE;
    case E87_MAINTENANCE_EVENT_AUTHENTICATED:
        if (maintenance->private_authenticated) {
            return E87_MAINTENANCE_RESULT_NO_CHANGE;
        }
        maintenance->private_authenticated = true;
        return E87_MAINTENANCE_RESULT_AUTHENTICATED;
    case E87_MAINTENANCE_EVENT_HOST_DISCONNECTED:
        maintenance->private_authenticated = false;
        maintenance->private_loader_verified = false;
        memset(&maintenance->private_loader, 0,
               sizeof(maintenance->private_loader));
        maintenance->private_unauthenticated_since_ms = event->now_ms;
        return E87_MAINTENANCE_RESULT_ACTIVE;
    case E87_MAINTENANCE_EVENT_CANCEL:
    case E87_MAINTENANCE_EVENT_FAILURE:
        return begin_exit(maintenance);
    case E87_MAINTENANCE_EVENT_POWER_SAMPLE:
        return update_power(maintenance, event);
    case E87_MAINTENANCE_EVENT_ENTER_AFTER_NORMAL_DISCONNECT:
    case E87_MAINTENANCE_EVENT_TRANSPORT_QUIESCED:
    case E87_MAINTENANCE_EVENT_RCSP_RELEASE_STATUS:
    default:
        return E87_MAINTENANCE_RESULT_NO_CHANGE;
    }
}

static enum e87_maintenance_result approved_step(
    struct e87_maintenance *maintenance,
    const struct e87_maintenance_event *event)
{
    switch (event->type) {
    case E87_MAINTENANCE_EVENT_HOST_DISCONNECTED:
        maintenance->private_authenticated = false;
        maintenance->private_loader_verified = false;
        memset(&maintenance->private_loader, 0,
               sizeof(maintenance->private_loader));
        maintenance->private_unauthenticated_since_ms = event->now_ms;
        maintenance->private_state = E87_MAINTENANCE_STATE_ACTIVE;
        return E87_MAINTENANCE_RESULT_ACTIVE;
    case E87_MAINTENANCE_EVENT_CANCEL:
    case E87_MAINTENANCE_EVENT_FAILURE:
        return begin_exit(maintenance);
    case E87_MAINTENANCE_EVENT_POWER_SAMPLE:
        refresh_power(maintenance, event);
        if (!maintenance->private_power_stable) {
            maintenance->private_state = E87_MAINTENANCE_STATE_ACTIVE;
        }
        return E87_MAINTENANCE_RESULT_STATUS_UPDATED;
    case E87_MAINTENANCE_EVENT_ENTER_AFTER_NORMAL_DISCONNECT:
    case E87_MAINTENANCE_EVENT_POLL:
    case E87_MAINTENANCE_EVENT_AUTHENTICATED:
    case E87_MAINTENANCE_EVENT_TRANSPORT_QUIESCED:
    case E87_MAINTENANCE_EVENT_RCSP_RELEASE_STATUS:
    default:
        return E87_MAINTENANCE_RESULT_NO_CHANGE;
    }
}

static enum e87_maintenance_result exiting_step(
    struct e87_maintenance *maintenance,
    const struct e87_maintenance_event *event)
{
    enum e87_maintenance_result abort_result;

    if (event->type == E87_MAINTENANCE_EVENT_CANCEL ||
        event->type == E87_MAINTENANCE_EVENT_FAILURE) {
        return begin_exit(maintenance);
    }
    if (event->type != E87_MAINTENANCE_EVENT_TRANSPORT_QUIESCED) {
        return E87_MAINTENANCE_RESULT_NO_CHANGE;
    }
    abort_result = begin_exit(maintenance);
    if (abort_result == E87_MAINTENANCE_RESULT_ERROR) {
        return abort_result;
    }
    if (!emit_command(maintenance,
                      E87_MAINTENANCE_COMMAND_RCSP_BLE_EXIT, 0)) {
        return E87_MAINTENANCE_RESULT_ERROR;
    }
    maintenance->private_rcsp_release_started_ms = event->now_ms;
    maintenance->private_state = E87_MAINTENANCE_STATE_WAIT_RCSP_RELEASE;
    return E87_MAINTENANCE_RESULT_WAITING_FOR_RCSP_RELEASE;
}

static enum e87_maintenance_result release_step(
    struct e87_maintenance *maintenance,
    const struct e87_maintenance_event *event)
{
    if (event->type != E87_MAINTENANCE_EVENT_RCSP_RELEASE_STATUS) {
        return E87_MAINTENANCE_RESULT_NO_CHANGE;
    }
    if (!event->rcsp_handle_present) {
        if (!maintenance->private_interface_exited) {
            if (!emit_command(
                    maintenance,
                    E87_MAINTENANCE_COMMAND_RCSP_INTERFACE_EXIT, 0)) {
                return E87_MAINTENANCE_RESULT_ERROR;
            }
            maintenance->private_interface_exited = true;
        }
        if (!emit_command(
                maintenance,
                E87_MAINTENANCE_COMMAND_REQUEST_NORMAL_MODE, 0)) {
            return E87_MAINTENANCE_RESULT_ERROR;
        }
        maintenance->private_state =
            E87_MAINTENANCE_STATE_NORMAL_REQUESTED;
        return E87_MAINTENANCE_RESULT_NORMAL_REQUESTED;
    }
    if (elapsed_reached(
            event->now_ms,
            maintenance->private_rcsp_release_started_ms,
            E87_MAINTENANCE_RCSP_RELEASE_TIMEOUT_MS)) {
        maintenance->private_state = E87_MAINTENANCE_STATE_ERROR;
        return E87_MAINTENANCE_RESULT_ERROR;
    }
    return E87_MAINTENANCE_RESULT_WAITING_FOR_RCSP_RELEASE;
}

bool e87_maintenance_init(
    struct e87_maintenance *maintenance,
    const struct e87_maintenance_port *port)
{
    struct e87_maintenance initialized = {0};

    if (maintenance == 0 || port == 0 || port->emit == 0) {
        return false;
    }
    initialized.private_port = *port;
    initialized.private_state = E87_MAINTENANCE_STATE_READY;
    initialized.private_initialized = true;
    *maintenance = initialized;
    return true;
}

enum e87_maintenance_result e87_maintenance_step(
    struct e87_maintenance *maintenance,
    const struct e87_maintenance_event *event)
{
    enum e87_maintenance_result result;

    if (maintenance == 0 || event == 0 ||
        !maintenance->private_initialized ||
        maintenance->private_port.emit == 0 ||
        !valid_state(maintenance->private_state) ||
        !valid_event_type(event->type) ||
        (event->type == E87_MAINTENANCE_EVENT_POWER_SAMPLE &&
         !valid_power_sample(&event->power))) {
        return E87_MAINTENANCE_RESULT_ERROR;
    }
    if (maintenance->private_in_step ||
        maintenance->private_state == E87_MAINTENANCE_STATE_ERROR) {
        return E87_MAINTENANCE_RESULT_ERROR;
    }

    maintenance->private_in_step = true;
    switch (maintenance->private_state) {
    case E87_MAINTENANCE_STATE_READY:
        result = event->type ==
                         E87_MAINTENANCE_EVENT_ENTER_AFTER_NORMAL_DISCONNECT
                     ? enter_maintenance(maintenance, event->now_ms)
                     : E87_MAINTENANCE_RESULT_NO_CHANGE;
        break;
    case E87_MAINTENANCE_STATE_ACTIVE:
        result = active_step(maintenance, event);
        break;
    case E87_MAINTENANCE_STATE_EXITING:
        result = exiting_step(maintenance, event);
        break;
    case E87_MAINTENANCE_STATE_WAIT_RCSP_RELEASE:
        result = release_step(maintenance, event);
        break;
    case E87_MAINTENANCE_STATE_HANDOFF_APPROVED:
        result = approved_step(maintenance, event);
        break;
    case E87_MAINTENANCE_STATE_NORMAL_REQUESTED:
    case E87_MAINTENANCE_STATE_HANDED_OFF:
        result = E87_MAINTENANCE_RESULT_NO_CHANGE;
        break;
    case E87_MAINTENANCE_STATE_ERROR:
    default:
        result = E87_MAINTENANCE_RESULT_ERROR;
        break;
    }
    maintenance->private_in_step = false;
    return result;
}

enum e87_maintenance_result e87_maintenance_accept_verified_loader(
    struct e87_maintenance *maintenance,
    const struct e87_rcsp_official_loader_report *report)
{
    enum e87_maintenance_result result;

    if (maintenance == 0 || !maintenance->private_initialized ||
        maintenance->private_port.emit == 0 ||
        !valid_state(maintenance->private_state) ||
        maintenance->private_in_step ||
        maintenance->private_state == E87_MAINTENANCE_STATE_ERROR) {
        return E87_MAINTENANCE_RESULT_ERROR;
    }
    if (maintenance->private_state == E87_MAINTENANCE_STATE_HANDED_OFF) {
        return E87_MAINTENANCE_RESULT_NO_CHANGE;
    }
    if (maintenance->private_state ==
        E87_MAINTENANCE_STATE_HANDOFF_APPROVED) {
        return valid_loader_report(report)
                   ? E87_MAINTENANCE_RESULT_NO_CHANGE
                   : E87_MAINTENANCE_RESULT_ERROR;
    }
    maintenance->private_in_step = true;
    if (maintenance->private_state != E87_MAINTENANCE_STATE_ACTIVE ||
        !maintenance->private_authenticated ||
        !valid_loader_report(report)) {
        result = maintenance->private_state == E87_MAINTENANCE_STATE_ACTIVE
                     ? begin_exit(maintenance)
                     : E87_MAINTENANCE_RESULT_ERROR;
    } else {
        maintenance->private_loader = *report;
        maintenance->private_loader_verified = true;
        result = request_handoff(
            maintenance, E87_MAINTENANCE_RESULT_HANDOFF_WAITING);
    }
    maintenance->private_in_step = false;
    return result;
}

enum e87_maintenance_result e87_rcsp_commit_official_handoff(
    struct e87_maintenance *maintenance)
{
    enum e87_maintenance_result result;

    if (maintenance == 0 || !maintenance->private_initialized ||
        maintenance->private_port.emit == 0 ||
        !valid_state(maintenance->private_state) ||
        maintenance->private_in_step ||
        maintenance->private_state == E87_MAINTENANCE_STATE_ERROR) {
        return E87_MAINTENANCE_RESULT_ERROR;
    }
    if (maintenance->private_state == E87_MAINTENANCE_STATE_HANDED_OFF) {
        return E87_MAINTENANCE_RESULT_NO_CHANGE;
    }
    if (maintenance->private_state !=
        E87_MAINTENANCE_STATE_HANDOFF_APPROVED) {
        return E87_MAINTENANCE_RESULT_ERROR;
    }
    if (!maintenance->private_authenticated ||
        !maintenance->private_loader_verified ||
        !maintenance->private_power_sample_seen ||
        !maintenance->private_power_stable ||
        !valid_power_sample(&maintenance->private_power) ||
        !power_is_eligible(&maintenance->private_power) ||
        !valid_loader_report(&maintenance->private_loader)) {
        maintenance->private_in_step = true;
        (void)begin_exit(maintenance);
        maintenance->private_in_step = false;
        return E87_MAINTENANCE_RESULT_ERROR;
    }

    maintenance->private_in_step = true;
    maintenance->private_state = E87_MAINTENANCE_STATE_HANDED_OFF;
    result = E87_MAINTENANCE_RESULT_HANDOFF_COMMITTED;
    maintenance->private_in_step = false;
    return result;
}

bool e87_maintenance_get_view(
    const struct e87_maintenance *maintenance,
    struct e87_maintenance_view *out)
{
    struct e87_maintenance_view view;

    if (maintenance == 0 || out == 0 ||
        !maintenance->private_initialized ||
        !valid_state(maintenance->private_state)) {
        return false;
    }
    memset(&view, 0, sizeof(view));
    view.state = maintenance->private_state;
    view.authenticated = maintenance->private_authenticated;
    view.loader_verified = maintenance->private_loader_verified;
    view.power_stable = maintenance->private_power_stable;
    view.power = maintenance->private_power;
    view.loader_saddr = maintenance->private_loader.loader_saddr;
    *out = view;
    return true;
}
