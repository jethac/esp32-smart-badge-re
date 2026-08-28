#ifndef E87_CHARGE_BRIDGE_H
#define E87_CHARGE_BRIDGE_H

#include "e87/e87_charge_adapter.h"

#include <stdbool.h>
#include <stdint.h>

#ifndef E87_CHARGE_BRIDGE_FIFO_CAPACITY
#define E87_CHARGE_BRIDGE_FIFO_CAPACITY 8
#endif

#ifndef E87_CHARGE_BRIDGE_DRAIN_BUDGET
#define E87_CHARGE_BRIDGE_DRAIN_BUDGET 16
#endif

#define E87_CHARGE_BRIDGE_WAKE_TOKEN UINT32_C(0x45383743)

typedef int (*e87_charge_critical_enter_fn)(void *context);
typedef void (*e87_charge_critical_exit_fn)(void *context, int saved);
typedef uint8_t (*e87_charge_read_driver_online_fn)(void *context);
typedef int (*e87_charge_post_wake_fn)(void *context);
typedef bool (*e87_charge_context_query_fn)(void *context);

struct e87_charge_bridge_port {
    void *context;
    e87_charge_critical_enter_fn critical_enter;
    e87_charge_critical_exit_fn critical_exit;
    e87_charge_read_driver_online_fn read_driver_online;
    e87_charge_post_wake_fn post_wake;
    e87_charge_context_query_fn in_irq;
    e87_charge_context_query_fn irq_disabled;
};

struct e87_charge_bridge {
    struct e87_charge_bridge_port private_port;
    struct e87_charge_adapter *private_adapter;
    volatile struct e87_charge_observation
        private_fifo[E87_CHARGE_BRIDGE_FIFO_CAPACITY];
    volatile uint8_t private_head;
    volatile uint8_t private_tail;
    volatile uint8_t private_count;
    volatile uint8_t private_wake_pending;
    volatile uint8_t private_fault_online_raw;
    volatile uint8_t private_fault_pending;
    volatile uint8_t private_terminal;
    volatile uint8_t private_terminal_handled;
    bool private_initialized;
};

enum e87_charge_bridge_poll_result {
    E87_CHARGE_BRIDGE_POLL_ERROR = 0,
    E87_CHARGE_BRIDGE_POLL_IDLE = 1,
    E87_CHARGE_BRIDGE_POLL_PROGRESSED = 2,
    E87_CHARGE_BRIDGE_POLL_PENDING_CLOSE = 3,
    E87_CHARGE_BRIDGE_POLL_TERMINAL = 4
};

bool e87_charge_bridge_init(struct e87_charge_bridge *bridge,
                            struct e87_charge_adapter *adapter,
                            const struct e87_charge_bridge_port *port);

bool e87_charge_bridge_capture(struct e87_charge_bridge *bridge,
                               enum e87_charge_event event);

bool e87_charge_bridge_ack_wake(struct e87_charge_bridge *bridge,
                                uint32_t wake_token);

bool e87_charge_bridge_note_queue_fault(struct e87_charge_bridge *bridge);

enum e87_charge_bridge_poll_result e87_charge_bridge_poll_app(
    struct e87_charge_bridge *bridge);

bool e87_charge_bridge_is_ready(const struct e87_charge_bridge *bridge);
bool e87_charge_bridge_is_terminal(const struct e87_charge_bridge *bridge);

#endif
