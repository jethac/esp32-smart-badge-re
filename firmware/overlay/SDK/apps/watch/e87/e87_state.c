#include "e87/e87_state.h"

#include <string.h>

static bool e87_metrics_are_valid(const struct e87_metrics *metrics)
{
    return metrics->day <= UINT8_C(100) &&
           metrics->week <= UINT8_C(100) &&
           metrics->credit_cents == E87_STATE_FIXED_CREDIT_CENTS;
}

enum e87_state_error
e87_state_decode(const uint8_t *packet,
                 size_t length,
                 struct e87_metrics *out)
{
    struct e87_metrics decoded;

    if (packet == NULL || out == NULL) {
        return E87_STATE_ERROR_ARGUMENT;
    }
    if (length != E87_STATE_PACKET_SIZE) {
        return E87_STATE_ERROR_LENGTH;
    }
    if (packet[0] != E87_STATE_PROTOCOL_VERSION) {
        return E87_STATE_ERROR_VERSION;
    }
    if (packet[1] > UINT8_C(100)) {
        return E87_STATE_ERROR_DAY;
    }
    if (packet[2] > UINT8_C(100)) {
        return E87_STATE_ERROR_WEEK;
    }
    if (packet[3] != UINT8_C(0)) {
        return E87_STATE_ERROR_FLAGS;
    }

    decoded.day = packet[1];
    decoded.week = packet[2];
    decoded.credit_cents =
        (uint32_t)packet[4] |
        ((uint32_t)packet[5] << 8U) |
        ((uint32_t)packet[6] << 16U) |
        ((uint32_t)packet[7] << 24U);
    if (decoded.credit_cents != E87_STATE_FIXED_CREDIT_CENTS) {
        return E87_STATE_ERROR_CREDIT;
    }

    *out = decoded;
    return E87_STATE_OK;
}

bool
e87_state_store_init(struct e87_state_store *store,
                     const struct e87_state_sync *sync)
{
    struct e87_state_store initialized;

    if (store == NULL || sync == NULL ||
        sync->enter == NULL || sync->leave == NULL) {
        return false;
    }

    memset(&initialized, 0, sizeof(initialized));
    initialized.private_sync = *sync;
    *store = initialized;
    return true;
}

bool
e87_state_commit(struct e87_state_store *store,
                 const struct e87_metrics *next)
{
    e87_state_lock_token_t token;
    bool changed;

    if (store == NULL || next == NULL || !e87_metrics_are_valid(next)) {
        return false;
    }

    token = store->private_sync.enter(store->private_sync.context);
    changed = !store->private_current.has_metrics ||
              store->private_current.metrics.day != next->day ||
              store->private_current.metrics.week != next->week ||
              store->private_current.metrics.credit_cents != next->credit_cents;
    if (changed) {
        store->private_current.metrics.day = next->day;
        store->private_current.metrics.week = next->week;
        store->private_current.metrics.credit_cents = next->credit_cents;
        store->private_current.has_metrics = true;
        store->private_current.revision += UINT32_C(1);
    }
    store->private_sync.leave(store->private_sync.context, token);

    return changed;
}

bool
e87_state_snapshot(const struct e87_state_store *store,
                   struct e87_state_snapshot *out)
{
    struct e87_state_snapshot snapshot;
    e87_state_lock_token_t token;

    if (store == NULL || out == NULL) {
        return false;
    }

    token = store->private_sync.enter(store->private_sync.context);
    snapshot = store->private_current;
    store->private_sync.leave(store->private_sync.context, token);
    *out = snapshot;
    return true;
}
