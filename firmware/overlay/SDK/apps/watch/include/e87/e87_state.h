#ifndef E87_STATE_H
#define E87_STATE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define E87_STATE_PACKET_SIZE 8u
#define E87_STATE_PROTOCOL_VERSION 1u
#define E87_STATE_FIXED_CREDIT_CENTS UINT32_C(1727)

struct e87_metrics {
    uint8_t day;
    uint8_t week;
    uint32_t credit_cents;
};

enum e87_state_error {
    E87_STATE_OK = 0,
    E87_STATE_ERROR_ARGUMENT = 1,
    E87_STATE_ERROR_LENGTH = 2,
    E87_STATE_ERROR_VERSION = 3,
    E87_STATE_ERROR_DAY = 4,
    E87_STATE_ERROR_WEEK = 5,
    E87_STATE_ERROR_FLAGS = 6,
    E87_STATE_ERROR_CREDIT = 7
};

typedef uintptr_t e87_state_lock_token_t;
typedef e87_state_lock_token_t
    (*e87_state_enter_fn)(void *context);
typedef void
    (*e87_state_leave_fn)(void *context,
                          e87_state_lock_token_t token);

struct e87_state_sync {
    void *context;
    e87_state_enter_fn enter;
    e87_state_leave_fn leave;
};

struct e87_state_snapshot {
    bool has_metrics;
    struct e87_metrics metrics;
    uint32_t revision;
};

struct e87_state_store {
    struct e87_state_sync private_sync;
    struct e87_state_snapshot private_current;
};

enum e87_state_error
e87_state_decode(const uint8_t *packet,
                 size_t length,
                 struct e87_metrics *out);

bool
e87_state_store_init(struct e87_state_store *store,
                     const struct e87_state_sync *sync);

bool
e87_state_commit(struct e87_state_store *store,
                 const struct e87_metrics *next);

bool
e87_state_snapshot(const struct e87_state_store *store,
                   struct e87_state_snapshot *out);

#endif
