#ifndef E87_CHARGE_ADAPTER_H
#define E87_CHARGE_ADAPTER_H

#include <stdbool.h>
#include <stdint.h>

enum e87_charge_event {
    E87_CHARGE_EVENT_CHARGE_START = 0,
    E87_CHARGE_EVENT_CHARGE_CLOSE = 1,
    E87_CHARGE_EVENT_CHARGE_FULL = 2,
    E87_CHARGE_EVENT_LDO5V_KEEP = 3,
    E87_CHARGE_EVENT_LDO5V_IN = 4,
    E87_CHARGE_EVENT_LDO5V_OFF = 5,
    E87_CHARGE_EVENT_UNSUPPORTED = 6
};

enum e87_charge_phase {
    E87_CHARGE_PHASE_UNKNOWN = 0,
    E87_CHARGE_PHASE_CHARGING = 1,
    E87_CHARGE_PHASE_FULL = 2,
    E87_CHARGE_PHASE_CLOSED = 3,
    E87_CHARGE_PHASE_FAULT = 4
};

enum e87_charge_command {
    E87_CHARGE_COMMAND_START_ELECTRICAL = 0,
    E87_CHARGE_COMMAND_CLOSE_ELECTRICAL = 1
};

struct e87_charge_observation {
    enum e87_charge_event event;
    uint8_t driver_online_raw;
};

struct e87_charge_snapshot {
    bool external_power_online;
    enum e87_charge_phase phase;
};

enum e87_charge_result {
    E87_CHARGE_RESULT_ERROR = 0,
    E87_CHARGE_RESULT_NO_CHANGE = 1,
    E87_CHARGE_RESULT_SNAPSHOT_UPDATED = 2,
    E87_CHARGE_RESULT_PENDING_CLOSE = 3
};

typedef bool (*e87_charge_emit_fn)(void *context,
                                   enum e87_charge_command command);
typedef bool (*e87_charge_publish_fn)(
    void *context, const struct e87_charge_snapshot *snapshot);

struct e87_charge_port {
    void *context;
    e87_charge_emit_fn emit;
    e87_charge_publish_fn publish;
};

struct e87_charge_adapter {
    struct e87_charge_port private_port;
    struct e87_charge_snapshot private_snapshot;
    struct e87_charge_snapshot private_pending_snapshot;
    bool private_initialized;
    bool private_in_step;
    bool private_has_pending_close;
    bool private_terminal_error;
};

bool e87_charge_adapter_init(struct e87_charge_adapter *adapter,
                             const struct e87_charge_port *port);

enum e87_charge_result e87_charge_adapter_step(
    struct e87_charge_adapter *adapter,
    const struct e87_charge_observation *observation);

enum e87_charge_result e87_charge_adapter_retry_pending_close(
    struct e87_charge_adapter *adapter);

bool e87_charge_adapter_has_pending_close(
    const struct e87_charge_adapter *adapter);

bool e87_charge_adapter_strengthen_pending_fault(
    struct e87_charge_adapter *adapter, uint8_t driver_online_raw);

bool e87_charge_adapter_get_snapshot(
    const struct e87_charge_adapter *adapter,
    struct e87_charge_snapshot *out_snapshot);

#endif
