#define E87_CHARGE_BRIDGE_FIFO_CAPACITY 8
#define E87_CHARGE_BRIDGE_DRAIN_BUDGET 16

#include "e87/e87_charge_bridge.h"

#include <stddef.h>
#include <string.h>

struct e87_terminal_transition {
    bool started;
    bool terminal;
    uint8_t online_raw;
};

enum e87_pop_result {
    E87_POP_EMPTY = 0,
    E87_POP_OBSERVATION = 1,
    E87_POP_TERMINAL = 2
};

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

static bool raw_valid(uint8_t raw)
{
    return raw == UINT8_C(0) || raw == UINT8_C(1);
}

static bool bridge_base_valid(const struct e87_charge_bridge *bridge)
{
    return bridge != NULL && bridge->private_initialized &&
           bridge->private_adapter != NULL &&
           bridge->private_port.critical_enter != NULL &&
           bridge->private_port.critical_exit != NULL &&
           bridge->private_port.read_driver_online != NULL &&
           bridge->private_port.post_wake != NULL &&
           bridge->private_port.in_irq != NULL &&
           bridge->private_port.irq_disabled != NULL;
}

static bool shared_valid_locked(const struct e87_charge_bridge *bridge)
{
    const uint8_t expected_tail = (uint8_t)(
        (bridge->private_head + bridge->private_count) %
        E87_CHARGE_BRIDGE_FIFO_CAPACITY);

    return bridge->private_head < E87_CHARGE_BRIDGE_FIFO_CAPACITY &&
           bridge->private_tail < E87_CHARGE_BRIDGE_FIFO_CAPACITY &&
           bridge->private_count <= E87_CHARGE_BRIDGE_FIFO_CAPACITY &&
           bridge->private_tail == expected_tail &&
           bridge->private_wake_pending <= UINT8_C(1) &&
           bridge->private_fault_pending <= UINT8_C(1) &&
           bridge->private_terminal <= UINT8_C(1) &&
           bridge->private_terminal_handled <= UINT8_C(1);
}

static void fault_first_wins_locked(struct e87_charge_bridge *bridge,
                                    uint8_t online_raw)
{
    if (bridge->private_fault_pending == UINT8_C(0) &&
        bridge->private_terminal == UINT8_C(0)) {
        bridge->private_fault_online_raw = online_raw;
        bridge->private_fault_pending = UINT8_C(1);
    }
}

static bool claim_wake_locked(struct e87_charge_bridge *bridge)
{
    if (bridge->private_wake_pending == UINT8_C(0)) {
        bridge->private_wake_pending = UINT8_C(1);
        return true;
    }
    return false;
}

static struct e87_terminal_transition take_terminal_transition(
    struct e87_charge_bridge *bridge)
{
    struct e87_terminal_transition transition = {false, false, UINT8_C(0)};
    int saved = bridge->private_port.critical_enter(
        bridge->private_port.context);

    if (!shared_valid_locked(bridge)) {
        const uint8_t online_raw = bridge->private_port.read_driver_online(
            bridge->private_port.context);

        fault_first_wins_locked(bridge, online_raw);
    }
    if (bridge->private_fault_pending != UINT8_C(0)) {
        transition.online_raw = bridge->private_fault_online_raw;
        bridge->private_terminal = UINT8_C(1);
        bridge->private_fault_pending = UINT8_C(0);
        bridge->private_head = UINT8_C(0);
        bridge->private_tail = UINT8_C(0);
        bridge->private_count = UINT8_C(0);
    }
    transition.terminal = bridge->private_terminal != UINT8_C(0);
    if (transition.terminal &&
        bridge->private_terminal_handled == UINT8_C(0)) {
        bridge->private_terminal_handled = UINT8_C(1);
        transition.started = true;
        transition.online_raw = bridge->private_fault_online_raw;
    }
    bridge->private_port.critical_exit(
        bridge->private_port.context, saved);
    return transition;
}

static uint8_t normalized_fault_online(
    struct e87_charge_bridge *bridge, uint8_t online_raw)
{
    struct e87_charge_snapshot snapshot;

    if (raw_valid(online_raw)) {
        return online_raw;
    }
    if (e87_charge_adapter_get_snapshot(
            bridge->private_adapter, &snapshot)) {
        return snapshot.external_power_online ? UINT8_C(1) : UINT8_C(0);
    }
    return UINT8_C(0);
}

static enum e87_charge_bridge_poll_result retry_close_or_terminal(
    struct e87_charge_bridge *bridge, bool terminal)
{
    enum e87_charge_result result =
        e87_charge_adapter_retry_pending_close(bridge->private_adapter);

    if (result == E87_CHARGE_RESULT_PENDING_CLOSE) {
        return E87_CHARGE_BRIDGE_POLL_PENDING_CLOSE;
    }
    if (result == E87_CHARGE_RESULT_ERROR) {
        return terminal ? E87_CHARGE_BRIDGE_POLL_TERMINAL :
                          E87_CHARGE_BRIDGE_POLL_ERROR;
    }
    return terminal ? E87_CHARGE_BRIDGE_POLL_TERMINAL :
                      E87_CHARGE_BRIDGE_POLL_PROGRESSED;
}

static enum e87_charge_bridge_poll_result handle_terminal_transition(
    struct e87_charge_bridge *bridge,
    const struct e87_terminal_transition *transition)
{
    const uint8_t online_raw = normalized_fault_online(
        bridge, transition->online_raw);
    enum e87_charge_result result;

    if (!transition->started) {
        if (e87_charge_adapter_has_pending_close(bridge->private_adapter)) {
            return retry_close_or_terminal(bridge, true);
        }
        return E87_CHARGE_BRIDGE_POLL_TERMINAL;
    }
    if (e87_charge_adapter_has_pending_close(bridge->private_adapter)) {
        if (!e87_charge_adapter_strengthen_pending_fault(
                bridge->private_adapter, online_raw)) {
            return E87_CHARGE_BRIDGE_POLL_TERMINAL;
        }
        return retry_close_or_terminal(bridge, true);
    }
    {
        const struct e87_charge_observation fault_observation = {
            E87_CHARGE_EVENT_UNSUPPORTED,
            online_raw
        };

        result = e87_charge_adapter_step(
            bridge->private_adapter, &fault_observation);
    }
    if (result == E87_CHARGE_RESULT_PENDING_CLOSE) {
        return E87_CHARGE_BRIDGE_POLL_PENDING_CLOSE;
    }
    return E87_CHARGE_BRIDGE_POLL_TERMINAL;
}

static enum e87_pop_result pop_one(struct e87_charge_bridge *bridge,
                                   struct e87_charge_observation *observation,
                                   struct e87_terminal_transition *transition)
{
    int saved = bridge->private_port.critical_enter(
        bridge->private_port.context);

    memset(transition, 0, sizeof(*transition));
    if (!shared_valid_locked(bridge)) {
        const uint8_t online_raw = bridge->private_port.read_driver_online(
            bridge->private_port.context);

        fault_first_wins_locked(bridge, online_raw);
    }
    if (bridge->private_fault_pending != UINT8_C(0)) {
        transition->online_raw = bridge->private_fault_online_raw;
        bridge->private_terminal = UINT8_C(1);
        bridge->private_fault_pending = UINT8_C(0);
        bridge->private_head = UINT8_C(0);
        bridge->private_tail = UINT8_C(0);
        bridge->private_count = UINT8_C(0);
    }
    if (bridge->private_terminal != UINT8_C(0)) {
        transition->terminal = true;
        if (bridge->private_terminal_handled == UINT8_C(0)) {
            bridge->private_terminal_handled = UINT8_C(1);
            transition->started = true;
            transition->online_raw = bridge->private_fault_online_raw;
        }
        bridge->private_port.critical_exit(
            bridge->private_port.context, saved);
        return E87_POP_TERMINAL;
    }
    if (bridge->private_count == UINT8_C(0)) {
        bridge->private_port.critical_exit(
            bridge->private_port.context, saved);
        return E87_POP_EMPTY;
    }
    observation->event = bridge->private_fifo[bridge->private_head].event;
    observation->driver_online_raw =
        bridge->private_fifo[bridge->private_head].driver_online_raw;
    bridge->private_head = (uint8_t)(
        (bridge->private_head + UINT8_C(1)) %
        E87_CHARGE_BRIDGE_FIFO_CAPACITY);
    bridge->private_count -= UINT8_C(1);
    bridge->private_port.critical_exit(
        bridge->private_port.context, saved);
    return E87_POP_OBSERVATION;
}

bool e87_charge_bridge_init(struct e87_charge_bridge *bridge,
                            struct e87_charge_adapter *adapter,
                            const struct e87_charge_bridge_port *port)
{
    struct e87_charge_bridge initialized;
    struct e87_charge_snapshot adapter_snapshot;

    if (bridge == NULL || adapter == NULL || port == NULL ||
        port->critical_enter == NULL || port->critical_exit == NULL ||
        port->read_driver_online == NULL || port->post_wake == NULL ||
        port->in_irq == NULL || port->irq_disabled == NULL ||
        !e87_charge_adapter_get_snapshot(adapter, &adapter_snapshot)) {
        return false;
    }
    memset(&initialized, 0, sizeof(initialized));
    initialized.private_port = *port;
    initialized.private_adapter = adapter;
    initialized.private_initialized = true;
    *bridge = initialized;
    return true;
}

bool e87_charge_bridge_capture(struct e87_charge_bridge *bridge,
                               enum e87_charge_event event)
{
    bool post_wake = false;
    bool accepted = false;
    uint8_t online_raw;
    int saved;

    if (!bridge_base_valid(bridge)) {
        return false;
    }
    saved = bridge->private_port.critical_enter(
        bridge->private_port.context);
    if (bridge->private_terminal != UINT8_C(0) ||
        bridge->private_fault_pending != UINT8_C(0)) {
        bridge->private_port.critical_exit(
            bridge->private_port.context, saved);
        return false;
    }
    online_raw = bridge->private_port.read_driver_online(
        bridge->private_port.context);
    if (!shared_valid_locked(bridge) || !raw_valid(online_raw) ||
        !event_valid(event) ||
        bridge->private_count == E87_CHARGE_BRIDGE_FIFO_CAPACITY) {
        fault_first_wins_locked(bridge, online_raw);
        if (bridge->private_wake_pending <= UINT8_C(1)) {
            post_wake = claim_wake_locked(bridge);
        }
    } else {
        bridge->private_fifo[bridge->private_tail].event = event;
        bridge->private_fifo[bridge->private_tail].driver_online_raw =
            online_raw;
        bridge->private_tail = (uint8_t)(
            (bridge->private_tail + UINT8_C(1)) %
            E87_CHARGE_BRIDGE_FIFO_CAPACITY);
        bridge->private_count += UINT8_C(1);
        post_wake = claim_wake_locked(bridge);
        accepted = true;
    }
    bridge->private_port.critical_exit(
        bridge->private_port.context, saved);
    if (post_wake &&
        bridge->private_port.post_wake(bridge->private_port.context) != 0) {
        saved = bridge->private_port.critical_enter(
            bridge->private_port.context);
        fault_first_wins_locked(bridge, online_raw);
        bridge->private_port.critical_exit(
            bridge->private_port.context, saved);
        return false;
    }
    return accepted;
}

bool e87_charge_bridge_ack_wake(struct e87_charge_bridge *bridge,
                                uint32_t wake_token)
{
    bool accepted = false;
    int saved;

    if (!bridge_base_valid(bridge)) {
        return false;
    }
    saved = bridge->private_port.critical_enter(
        bridge->private_port.context);
    if (wake_token == E87_CHARGE_BRIDGE_WAKE_TOKEN &&
        shared_valid_locked(bridge) &&
        bridge->private_wake_pending == UINT8_C(1)) {
        bridge->private_wake_pending = UINT8_C(0);
        accepted = true;
    } else {
        const uint8_t online_raw = bridge->private_port.read_driver_online(
            bridge->private_port.context);

        fault_first_wins_locked(bridge, online_raw);
    }
    bridge->private_port.critical_exit(
        bridge->private_port.context, saved);
    return accepted;
}

bool e87_charge_bridge_note_queue_fault(struct e87_charge_bridge *bridge)
{
    int saved;

    if (!bridge_base_valid(bridge)) {
        return false;
    }
    saved = bridge->private_port.critical_enter(
        bridge->private_port.context);
    fault_first_wins_locked(
        bridge,
        bridge->private_port.read_driver_online(bridge->private_port.context));
    bridge->private_port.critical_exit(
        bridge->private_port.context, saved);
    return false;
}

enum e87_charge_bridge_poll_result e87_charge_bridge_poll_app(
    struct e87_charge_bridge *bridge)
{
    struct e87_terminal_transition transition;
    bool progressed = false;
    size_t processed;

    if (!bridge_base_valid(bridge) ||
        bridge->private_port.in_irq(bridge->private_port.context) ||
        bridge->private_port.irq_disabled(bridge->private_port.context)) {
        return E87_CHARGE_BRIDGE_POLL_ERROR;
    }
    transition = take_terminal_transition(bridge);
    if (transition.terminal) {
        return handle_terminal_transition(bridge, &transition);
    }
    if (e87_charge_adapter_has_pending_close(bridge->private_adapter)) {
        const enum e87_charge_result retry =
            e87_charge_adapter_retry_pending_close(bridge->private_adapter);

        if (retry == E87_CHARGE_RESULT_PENDING_CLOSE) {
            return E87_CHARGE_BRIDGE_POLL_PENDING_CLOSE;
        }
        if (retry == E87_CHARGE_RESULT_ERROR) {
            int saved = bridge->private_port.critical_enter(
                bridge->private_port.context);

            bridge->private_terminal = UINT8_C(1);
            bridge->private_terminal_handled = UINT8_C(1);
            bridge->private_head = UINT8_C(0);
            bridge->private_tail = UINT8_C(0);
            bridge->private_count = UINT8_C(0);
            bridge->private_port.critical_exit(
                bridge->private_port.context, saved);
            return E87_CHARGE_BRIDGE_POLL_TERMINAL;
        }
        progressed = retry == E87_CHARGE_RESULT_SNAPSHOT_UPDATED;
    }
    for (processed = 0U; processed < E87_CHARGE_BRIDGE_DRAIN_BUDGET;
         processed += 1U) {
        struct e87_charge_observation observation;
        enum e87_charge_result result;
        const enum e87_pop_result pop = pop_one(
            bridge, &observation, &transition);

        if (pop == E87_POP_TERMINAL) {
            return handle_terminal_transition(bridge, &transition);
        }
        if (pop == E87_POP_EMPTY) {
            return processed == 0U && !progressed ?
                E87_CHARGE_BRIDGE_POLL_IDLE :
                E87_CHARGE_BRIDGE_POLL_PROGRESSED;
        }
        result = e87_charge_adapter_step(
            bridge->private_adapter, &observation);
        if (result == E87_CHARGE_RESULT_PENDING_CLOSE) {
            return E87_CHARGE_BRIDGE_POLL_PENDING_CLOSE;
        }
        if (result == E87_CHARGE_RESULT_ERROR) {
            int saved = bridge->private_port.critical_enter(
                bridge->private_port.context);

            fault_first_wins_locked(
                bridge, observation.driver_online_raw);
            bridge->private_port.critical_exit(
                bridge->private_port.context, saved);
        }
    }
    {
        int saved = bridge->private_port.critical_enter(
            bridge->private_port.context);

        memset(&transition, 0, sizeof(transition));
        if (!shared_valid_locked(bridge) ||
            bridge->private_count != UINT8_C(0) ||
            bridge->private_fault_pending != UINT8_C(0)) {
            const uint8_t online_raw =
                bridge->private_fault_pending != UINT8_C(0) ?
                bridge->private_fault_online_raw :
                bridge->private_port.read_driver_online(
                    bridge->private_port.context);

            fault_first_wins_locked(bridge, online_raw);
            transition.online_raw = bridge->private_fault_online_raw;
            bridge->private_terminal = UINT8_C(1);
            bridge->private_fault_pending = UINT8_C(0);
            bridge->private_head = UINT8_C(0);
            bridge->private_tail = UINT8_C(0);
            bridge->private_count = UINT8_C(0);
            transition.terminal = true;
            if (bridge->private_terminal_handled == UINT8_C(0)) {
                bridge->private_terminal_handled = UINT8_C(1);
                transition.started = true;
            }
        }
        bridge->private_port.critical_exit(
            bridge->private_port.context, saved);
    }
    if (transition.terminal) {
        return handle_terminal_transition(bridge, &transition);
    }
    return E87_CHARGE_BRIDGE_POLL_PROGRESSED;
}

bool e87_charge_bridge_is_ready(const struct e87_charge_bridge *bridge)
{
    return bridge_base_valid(bridge) &&
           bridge->private_terminal == UINT8_C(0) &&
           bridge->private_fault_pending == UINT8_C(0);
}

bool e87_charge_bridge_is_terminal(const struct e87_charge_bridge *bridge)
{
    return bridge_base_valid(bridge) &&
           (bridge->private_terminal != UINT8_C(0) ||
            bridge->private_fault_pending != UINT8_C(0));
}
