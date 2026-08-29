#ifndef E87_APP_RUNTIME_H
#define E87_APP_RUNTIME_H

#include <stdbool.h>
#include <stdint.h>

#include "e87/e87_app_core.h"

#define E87_APP_RUNTIME_QUEUE_CAPACITY 8u

struct e87_app_runtime_port {
    void *context;
    int (*critical_enter)(void *context);
    void (*critical_exit)(void *context, int saved);
    uint32_t (*now_ms)(void *context);
    bool (*poll_ble)(void *context);
    bool (*poll_charge)(void *context);
    bool (*emit_effect)(void *context, struct e87_app_core_effect *effect);
    bool (*authorization_epoch_is_active)(void *context, uint32_t epoch);
};

struct e87_app_runtime {
    struct e87_app_core core;
    struct e87_app_runtime_port port;
    struct e87_app_core_event queue[E87_APP_RUNTIME_QUEUE_CAPACITY];
    uint8_t head;
    uint8_t count;
    bool initialized;
    bool terminal;
};

bool e87_app_runtime_init(struct e87_app_runtime *runtime,
                          const struct e87_app_core_config *config,
                          const struct e87_app_runtime_port *port);
bool e87_app_runtime_try_enqueue(struct e87_app_runtime *runtime,
                                 const struct e87_app_core_event *event);
bool e87_app_runtime_try_enqueue_semantic(
    struct e87_app_runtime *runtime,
    uint32_t authorization_epoch,
    const uint8_t packet[E87_STATE_PACKET_SIZE]);
bool e87_app_runtime_poll(struct e87_app_runtime *runtime);
bool e87_app_runtime_is_terminal(const struct e87_app_runtime *runtime);

#endif
