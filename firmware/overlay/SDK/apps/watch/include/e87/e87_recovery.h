#ifndef E87_RECOVERY_H
#define E87_RECOVERY_H

#include <stdbool.h>
#include <stdint.h>

#include "e87/e87_button_fsm.h"

#define E87_KEY_RESET_HOLD_SECONDS 16u
#define E87_NORMAL_STOP_TIMEOUT_MS UINT32_C(5000)

enum e87_recovery_reset_cause {
    E87_RESET_CAUSE_POWER_ON = 0,
    E87_RESET_CAUSE_SOFTWARE = 1,
    E87_RESET_CAUSE_WATCHDOG = 2,
    E87_RESET_CAUSE_P33_PPINR = 3,
    E87_RESET_CAUSE_OTHER = 4
};

enum e87_recovery_event_type {
    E87_RECOVERY_EVENT_BOOT = 0,
    E87_RECOVERY_EVENT_HEALTHY_MAINTENANCE = 1,
    E87_RECOVERY_EVENT_NORMAL_MODE_STOPPED = 2,
    E87_RECOVERY_EVENT_NORMAL_MODE_STOP_FAILED = 3,
    E87_RECOVERY_EVENT_POLL = 4
};

struct e87_recovery_event {
    enum e87_recovery_event_type type;
    enum e87_recovery_reset_cause reset_cause;
    enum e87_key_class key;
    uint32_t now_ms;
};

enum e87_recovery_command {
    E87_RECOVERY_COMMAND_DISARM_KEY_RESET = 0,
    E87_RECOVERY_COMMAND_ARM_KEY_RESET_16S = 1,
    E87_RECOVERY_COMMAND_REQUEST_NORMAL_STOP = 2,
    E87_RECOVERY_COMMAND_FEED_WATCHDOG = 3,
    E87_RECOVERY_COMMAND_REQUEST_MAINTENANCE = 4
};

enum e87_recovery_result {
    E87_RECOVERY_RESULT_ERROR = 0,
    E87_RECOVERY_RESULT_NO_CHANGE = 1,
    E87_RECOVERY_RESULT_NORMAL_BOOT = 2,
    E87_RECOVERY_RESULT_WAITING = 3,
    E87_RECOVERY_RESULT_MAINTENANCE_REQUESTED = 4,
    E87_RECOVERY_RESULT_FAIL_SAFE_WAITING = 5,
    E87_RECOVERY_RESULT_FAIL_SAFE_REARMED = 6
};

enum e87_recovery_state {
    E87_RECOVERY_STATE_READY = 0,
    E87_RECOVERY_STATE_NORMAL = 1,
    E87_RECOVERY_STATE_HEALTHY_STOPPING = 2,
    E87_RECOVERY_STATE_PINR_WAIT_RELEASE = 3,
    E87_RECOVERY_STATE_FAIL_SAFE_WAIT_RELEASE = 4,
    E87_RECOVERY_STATE_MAINTENANCE = 5,
    E87_RECOVERY_STATE_FAIL_SAFE_REARMED = 6,
    E87_RECOVERY_STATE_ERROR = 7
};

enum e87_reset_ownership {
    E87_RESET_OWNERSHIP_UNKNOWN = 0,
    E87_RESET_OWNERSHIP_ARMED = 1,
    E87_RESET_OWNERSHIP_DISARMED = 2
};

typedef bool (*e87_recovery_emit_fn)(
    void *context,
    enum e87_recovery_command command);

struct e87_recovery_port {
    void *context;
    e87_recovery_emit_fn emit;
};

struct e87_recovery_fsm {
    struct e87_recovery_port private_port;
    enum e87_recovery_state private_state;
    bool private_initialized;
    bool private_in_step;
    enum e87_reset_ownership private_reset_ownership;
    bool private_normal_stopped;
    bool private_release_latched;
    uint32_t private_stop_started_ms;
};

bool e87_recovery_init(struct e87_recovery_fsm *fsm,
                       const struct e87_recovery_port *port);

enum e87_recovery_result
e87_recovery_step(struct e87_recovery_fsm *fsm,
                  const struct e87_recovery_event *event);

enum e87_reset_ownership
e87_recovery_get_reset_ownership(
    const struct e87_recovery_fsm *fsm);

#endif
