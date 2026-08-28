#include "e87/e87_charge_adapter.h"

#include <string.h>

static bool phase_valid(enum e87_charge_phase phase)
{
    return phase == E87_CHARGE_PHASE_UNKNOWN ||
           phase == E87_CHARGE_PHASE_CHARGING ||
           phase == E87_CHARGE_PHASE_FULL ||
           phase == E87_CHARGE_PHASE_CLOSED ||
           phase == E87_CHARGE_PHASE_FAULT;
}

static bool snapshot_valid(const struct e87_charge_snapshot *snapshot)
{
    return snapshot != NULL && phase_valid(snapshot->phase);
}

static bool raw_valid(uint8_t raw)
{
    return raw == UINT8_C(0) || raw == UINT8_C(1);
}

static bool event_valid(enum e87_charge_event event)
{
    return event == E87_CHARGE_EVENT_CHARGE_START ||
           event == E87_CHARGE_EVENT_CHARGE_CLOSE ||
           event == E87_CHARGE_EVENT_CHARGE_FULL ||
           event == E87_CHARGE_EVENT_LDO5V_KEEP ||
           event == E87_CHARGE_EVENT_LDO5V_IN ||
           event == E87_CHARGE_EVENT_LDO5V_OFF ||
           event == E87_CHARGE_EVENT_UNSUPPORTED;
}

static bool adapter_valid(const struct e87_charge_adapter *adapter)
{
    if (adapter == NULL || !adapter->private_initialized ||
        adapter->private_port.emit == NULL ||
        adapter->private_port.publish == NULL ||
        !snapshot_valid(&adapter->private_snapshot) ||
        !snapshot_valid(&adapter->private_pending_snapshot)) {
        return false;
    }
    if (adapter->private_has_pending_close &&
        adapter->private_terminal_error) {
        return false;
    }
    return true;
}

static bool snapshots_equal(const struct e87_charge_snapshot *left,
                            const struct e87_charge_snapshot *right)
{
    return left->external_power_online == right->external_power_online &&
           left->phase == right->phase;
}

static bool phase_latched(enum e87_charge_phase phase)
{
    return phase == E87_CHARGE_PHASE_FULL ||
           phase == E87_CHARGE_PHASE_FAULT;
}

static bool consistent(enum e87_charge_event event, uint8_t raw)
{
    if (!raw_valid(raw)) {
        return false;
    }
    switch (event) {
    case E87_CHARGE_EVENT_CHARGE_START:
    case E87_CHARGE_EVENT_CHARGE_FULL:
    case E87_CHARGE_EVENT_LDO5V_KEEP:
    case E87_CHARGE_EVENT_LDO5V_IN:
        return raw == UINT8_C(1);
    case E87_CHARGE_EVENT_LDO5V_OFF:
        return raw == UINT8_C(0);
    case E87_CHARGE_EVENT_CHARGE_CLOSE:
    case E87_CHARGE_EVENT_UNSUPPORTED:
        return true;
    default:
        return false;
    }
}

static struct e87_charge_snapshot candidate_for(
    const struct e87_charge_snapshot *current,
    const struct e87_charge_observation *observation)
{
    struct e87_charge_snapshot candidate = *current;
    const uint8_t raw = observation->driver_online_raw;

    if (!raw_valid(raw)) {
        candidate.phase = E87_CHARGE_PHASE_FAULT;
        return candidate;
    }
    if (!consistent(observation->event, raw)) {
        candidate.external_power_online = raw == UINT8_C(1);
        candidate.phase = E87_CHARGE_PHASE_FAULT;
        return candidate;
    }
    switch (observation->event) {
    case E87_CHARGE_EVENT_LDO5V_IN:
        candidate.external_power_online = true;
        break;
    case E87_CHARGE_EVENT_CHARGE_START:
        candidate.external_power_online = true;
        if (!phase_latched(current->phase)) {
            candidate.phase = E87_CHARGE_PHASE_CHARGING;
        }
        break;
    case E87_CHARGE_EVENT_CHARGE_FULL:
        candidate.external_power_online = true;
        if (!(current->external_power_online &&
              current->phase == E87_CHARGE_PHASE_FAULT)) {
            candidate.phase = E87_CHARGE_PHASE_FULL;
        }
        break;
    case E87_CHARGE_EVENT_CHARGE_CLOSE:
        candidate.external_power_online = raw == UINT8_C(1);
        if (!phase_latched(current->phase)) {
            candidate.phase = E87_CHARGE_PHASE_CLOSED;
        }
        break;
    case E87_CHARGE_EVENT_LDO5V_OFF:
        candidate.external_power_online = false;
        candidate.phase = E87_CHARGE_PHASE_CLOSED;
        break;
    case E87_CHARGE_EVENT_LDO5V_KEEP:
    case E87_CHARGE_EVENT_UNSUPPORTED:
        candidate.external_power_online = raw == UINT8_C(1);
        candidate.phase = E87_CHARGE_PHASE_FAULT;
        break;
    default:
        break;
    }
    return candidate;
}

static bool command_for(const struct e87_charge_snapshot *current,
                        const struct e87_charge_snapshot *candidate,
                        const struct e87_charge_observation *observation,
                        enum e87_charge_command *out_command)
{
    const enum e87_charge_event event = observation->event;
    const uint8_t raw = observation->driver_online_raw;

    if (snapshots_equal(current, candidate)) {
        return false;
    }
    if (!raw_valid(raw) || !consistent(event, raw)) {
        *out_command = E87_CHARGE_COMMAND_CLOSE_ELECTRICAL;
        return true;
    }
    if (event == E87_CHARGE_EVENT_LDO5V_IN &&
        !current->external_power_online && !phase_latched(current->phase)) {
        *out_command = E87_CHARGE_COMMAND_START_ELECTRICAL;
        return true;
    }
    if (event == E87_CHARGE_EVENT_CHARGE_FULL &&
        !phase_latched(current->phase)) {
        *out_command = E87_CHARGE_COMMAND_CLOSE_ELECTRICAL;
        return true;
    }
    if (event == E87_CHARGE_EVENT_LDO5V_OFF ||
        event == E87_CHARGE_EVENT_LDO5V_KEEP ||
        event == E87_CHARGE_EVENT_UNSUPPORTED) {
        *out_command = E87_CHARGE_COMMAND_CLOSE_ELECTRICAL;
        return true;
    }
    return false;
}

static void set_pending_fault(struct e87_charge_adapter *adapter, bool online)
{
    adapter->private_pending_snapshot.external_power_online = online;
    adapter->private_pending_snapshot.phase = E87_CHARGE_PHASE_FAULT;
    adapter->private_has_pending_close = true;
}

bool e87_charge_adapter_init(struct e87_charge_adapter *adapter,
                             const struct e87_charge_port *port)
{
    struct e87_charge_adapter initialized;

    if (adapter == NULL || port == NULL || port->emit == NULL ||
        port->publish == NULL || adapter->private_initialized) {
        return false;
    }
    memset(&initialized, 0, sizeof(initialized));
    initialized.private_port = *port;
    initialized.private_snapshot.external_power_online = false;
    initialized.private_snapshot.phase = E87_CHARGE_PHASE_UNKNOWN;
    initialized.private_pending_snapshot = initialized.private_snapshot;
    initialized.private_initialized = true;
    *adapter = initialized;
    return true;
}

enum e87_charge_result e87_charge_adapter_step(
    struct e87_charge_adapter *adapter,
    const struct e87_charge_observation *observation)
{
    struct e87_charge_snapshot candidate;
    enum e87_charge_command command;
    bool has_command;
    bool close_accepted = false;

    if (!adapter_valid(adapter) || observation == NULL ||
        !event_valid(observation->event)) {
        return E87_CHARGE_RESULT_ERROR;
    }
    if (adapter->private_in_step || adapter->private_terminal_error) {
        return E87_CHARGE_RESULT_ERROR;
    }
    if (adapter->private_has_pending_close) {
        return E87_CHARGE_RESULT_PENDING_CLOSE;
    }
    candidate = candidate_for(&adapter->private_snapshot, observation);
    if (snapshots_equal(&adapter->private_snapshot, &candidate)) {
        return E87_CHARGE_RESULT_NO_CHANGE;
    }
    has_command = command_for(&adapter->private_snapshot, &candidate,
                              observation, &command);
    adapter->private_in_step = true;
    if (has_command && !adapter->private_port.emit(adapter->private_port.context,
                                                   command)) {
        if (command == E87_CHARGE_COMMAND_CLOSE_ELECTRICAL) {
            adapter->private_pending_snapshot = candidate;
            adapter->private_has_pending_close = true;
        } else {
            set_pending_fault(adapter, candidate.external_power_online);
        }
        adapter->private_in_step = false;
        return E87_CHARGE_RESULT_PENDING_CLOSE;
    }
    close_accepted = has_command &&
                     command == E87_CHARGE_COMMAND_CLOSE_ELECTRICAL;
    if (!adapter->private_port.publish(adapter->private_port.context,
                                      &candidate)) {
        if (close_accepted) {
            adapter->private_terminal_error = true;
            adapter->private_in_step = false;
            return E87_CHARGE_RESULT_ERROR;
        }
        set_pending_fault(adapter, candidate.external_power_online);
        adapter->private_in_step = false;
        return E87_CHARGE_RESULT_PENDING_CLOSE;
    }
    adapter->private_snapshot = candidate;
    adapter->private_in_step = false;
    return E87_CHARGE_RESULT_SNAPSHOT_UPDATED;
}

enum e87_charge_result e87_charge_adapter_retry_pending_close(
    struct e87_charge_adapter *adapter)
{
    struct e87_charge_snapshot candidate;

    if (!adapter_valid(adapter) || adapter->private_in_step ||
        adapter->private_terminal_error) {
        return E87_CHARGE_RESULT_ERROR;
    }
    if (!adapter->private_has_pending_close) {
        return E87_CHARGE_RESULT_NO_CHANGE;
    }
    candidate = adapter->private_pending_snapshot;
    adapter->private_in_step = true;
    if (!adapter->private_port.emit(adapter->private_port.context,
                                    E87_CHARGE_COMMAND_CLOSE_ELECTRICAL)) {
        adapter->private_in_step = false;
        return E87_CHARGE_RESULT_PENDING_CLOSE;
    }
    if (!adapter->private_port.publish(adapter->private_port.context,
                                      &candidate)) {
        adapter->private_terminal_error = true;
        adapter->private_has_pending_close = false;
        adapter->private_in_step = false;
        return E87_CHARGE_RESULT_ERROR;
    }
    adapter->private_snapshot = candidate;
    adapter->private_has_pending_close = false;
    adapter->private_in_step = false;
    return E87_CHARGE_RESULT_SNAPSHOT_UPDATED;
}

bool e87_charge_adapter_has_pending_close(
    const struct e87_charge_adapter *adapter)
{
    return adapter_valid(adapter) && adapter->private_has_pending_close;
}

bool e87_charge_adapter_strengthen_pending_fault(
    struct e87_charge_adapter *adapter, uint8_t driver_online_raw)
{
    if (!adapter_valid(adapter) || adapter->private_in_step ||
        adapter->private_terminal_error || !adapter->private_has_pending_close ||
        !raw_valid(driver_online_raw)) {
        return false;
    }
    set_pending_fault(adapter, driver_online_raw == UINT8_C(1));
    return true;
}

bool e87_charge_adapter_get_snapshot(
    const struct e87_charge_adapter *adapter,
    struct e87_charge_snapshot *out_snapshot)
{
    if (!adapter_valid(adapter) || out_snapshot == NULL) {
        return false;
    }
    *out_snapshot = adapter->private_snapshot;
    return true;
}
