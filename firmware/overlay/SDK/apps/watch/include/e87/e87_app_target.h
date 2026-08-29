#ifndef E87_APP_TARGET_H
#define E87_APP_TARGET_H

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "e87/e87_app_core.h"

struct e87_app_target_boot_port {
    void *context;
    bool (*read_now_ms)(void *context, uint32_t *out_now_ms);
    bool (*read_has_bond)(void *context, bool *out_has_bond);
    bool (*read_reset_cause)(void *context,
                             enum e87_recovery_reset_cause *out_reset_cause);
    bool (*read_key)(void *context, enum e87_key_class *out_key);
    bool (*read_charge)(void *context,
                        struct e87_charge_snapshot *out_charge);
};

static inline bool e87_app_target_build_boot(
    const struct e87_app_target_boot_port *port,
    struct e87_app_core_event *out_event)
{
    struct e87_app_core_event event;
    if (port == NULL || out_event == NULL || port->read_now_ms == NULL ||
        port->read_has_bond == NULL || port->read_reset_cause == NULL ||
        port->read_key == NULL || port->read_charge == NULL) {
        return false;
    }
    memset(&event, 0, sizeof(event));
    event.type = E87_APP_CORE_EVENT_BOOT;
    if (!port->read_now_ms(port->context, &event.now_ms) ||
        !port->read_has_bond(port->context, &event.data.boot.has_bond) ||
        !port->read_reset_cause(port->context,
                                &event.data.boot.reset_cause) ||
        !port->read_key(port->context, &event.data.boot.key) ||
        !port->read_charge(port->context,
                           &event.data.boot.charge_snapshot)) {
        return false;
    }
    *out_event = event;
    return true;
}

#endif
