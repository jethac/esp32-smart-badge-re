#include "e87/e87_app_runtime.h"

#include <string.h>

static bool runtime_emit(void *context, struct e87_app_core_effect *effect)
{
    struct e87_app_runtime *runtime = context;
    if (runtime == NULL || runtime->terminal || runtime->port.emit_effect == NULL ||
        !runtime->port.emit_effect(runtime->port.context, effect)) {
        if (runtime != NULL) {
            runtime->terminal = true;
        }
        return false;
    }
    return true;
}

static bool runtime_epoch_active(void *context, uint32_t epoch)
{
    struct e87_app_runtime *runtime = context;
    return runtime != NULL && !runtime->terminal &&
           runtime->port.authorization_epoch_is_active != NULL &&
           runtime->port.authorization_epoch_is_active(runtime->port.context, epoch);
}

bool e87_app_runtime_init(struct e87_app_runtime *runtime,
                          const struct e87_app_core_config *config,
                          const struct e87_app_runtime_port *port)
{
    struct e87_app_core_port core_port;
    if (runtime == NULL || config == NULL || port == NULL ||
        port->critical_enter == NULL || port->critical_exit == NULL ||
        port->now_ms == NULL || port->emit_effect == NULL ||
        port->authorization_epoch_is_active == NULL) {
        return false;
    }
    memset(runtime, 0, sizeof(*runtime));
    runtime->port = *port;
    core_port.context = runtime;
    core_port.emit = runtime_emit;
    core_port.authorization_epoch_is_active = runtime_epoch_active;
    if (!e87_app_core_init(&runtime->core, config, &core_port)) {
        memset(runtime, 0, sizeof(*runtime));
        return false;
    }
    runtime->initialized = true;
    return true;
}

bool e87_app_runtime_try_enqueue(struct e87_app_runtime *runtime,
                                 const struct e87_app_core_event *event)
{
    uint8_t tail;
    int saved;
    if (runtime == NULL || event == NULL || !runtime->initialized) {
        return false;
    }
    saved = runtime->port.critical_enter(runtime->port.context);
    if (runtime->terminal || runtime->count >= E87_APP_RUNTIME_QUEUE_CAPACITY) {
        runtime->terminal = true;
        runtime->port.critical_exit(runtime->port.context, saved);
        return false;
    }
    tail = (uint8_t)((runtime->head + runtime->count) % E87_APP_RUNTIME_QUEUE_CAPACITY);
    runtime->queue[tail] = *event;
    runtime->count++;
    runtime->port.critical_exit(runtime->port.context, saved);
    return true;
}

bool e87_app_runtime_try_enqueue_semantic(
    struct e87_app_runtime *runtime,
    uint32_t authorization_epoch,
    const uint8_t packet[E87_STATE_PACKET_SIZE])
{
    struct e87_app_core_event event;
    if (runtime == NULL || packet == NULL || !runtime->initialized) {
        return false;
    }
    memset(&event, 0, sizeof(event));
    event.type = E87_APP_CORE_EVENT_SEMANTIC_PACKET;
    event.now_ms = runtime->port.now_ms(runtime->port.context);
    event.data.semantic.authorization_epoch = authorization_epoch;
    memcpy(event.data.semantic.packet, packet, E87_STATE_PACKET_SIZE);
    return e87_app_runtime_try_enqueue(runtime, &event);
}

bool e87_app_runtime_poll(struct e87_app_runtime *runtime)
{
    struct e87_app_core_event event;
    enum e87_app_core_result result;
    int saved;
    if (runtime == NULL || !runtime->initialized || runtime->terminal) {
        return false;
    }
    if ((runtime->port.poll_ble != NULL && !runtime->port.poll_ble(runtime->port.context)) ||
        (runtime->port.poll_charge != NULL && !runtime->port.poll_charge(runtime->port.context))) {
        runtime->terminal = true;
        return false;
    }
    for (;;) {
        saved = runtime->port.critical_enter(runtime->port.context);
        if (runtime->count == 0u) {
            runtime->port.critical_exit(runtime->port.context, saved);
            break;
        }
        event = runtime->queue[runtime->head];
        runtime->head = (uint8_t)((runtime->head + 1u) % E87_APP_RUNTIME_QUEUE_CAPACITY);
        runtime->count--;
        runtime->port.critical_exit(runtime->port.context, saved);
        result = e87_app_core_step(&runtime->core, &event);
        if (result == E87_APP_CORE_RESULT_ERROR ||
            result == E87_APP_CORE_RESULT_REENTRANT ||
            result == E87_APP_CORE_RESULT_FAIL_CLOSED) {
            runtime->terminal = true;
            return false;
        }
    }
    memset(&event, 0, sizeof(event));
    event.type = E87_APP_CORE_EVENT_POLL;
    event.now_ms = runtime->port.now_ms(runtime->port.context);
    result = e87_app_core_step(&runtime->core, &event);
    if (result == E87_APP_CORE_RESULT_ERROR || result == E87_APP_CORE_RESULT_REENTRANT ||
        result == E87_APP_CORE_RESULT_FAIL_CLOSED) {
        runtime->terminal = true;
        return false;
    }
    return true;
}

bool e87_app_runtime_is_terminal(const struct e87_app_runtime *runtime)
{
    return runtime == NULL || runtime->terminal;
}
