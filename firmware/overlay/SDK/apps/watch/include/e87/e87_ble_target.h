#ifndef E87_BLE_TARGET_H
#define E87_BLE_TARGET_H

#include <stdbool.h>
#include <stdint.h>

#define E87_BLE_TARGET_STATE_PACKET_SIZE 8u

typedef bool (*e87_ble_target_try_enqueue_state_fn)(
    void *context,
    uint32_t authorization_epoch,
    const uint8_t packet[E87_BLE_TARGET_STATE_PACKET_SIZE]);

/*
 * Runs in the vendor ATT callback context. The implementation must copy the
 * packet into app-core-owned storage before returning. The target may call the
 * pure decoder only to preserve synchronous ATT semantic errors; it discards
 * that output and must never commit. App core decodes again and is the sole
 * state owner/committer when it drains ingress from its serialized poll.
 * true acknowledges ingress admission, not semantic commit; false rejects the
 * synchronous ATT request with E87_ATT_ERROR_UNLIKELY. Core must retain the
 * epoch and call e87_ble_target_authorization_epoch_is_active() before
 * committing a queued packet. The epoch is active only for the exact current
 * encrypted durable-owner link after a contiguous full BuildInfo read while
 * lifecycle writes remain enabled. Write-close, disconnect, encryption loss,
 * owner/link replacement, and teardown invalidate old epochs synchronously.
 */
struct e87_ble_target_ingress {
    void *context;
    e87_ble_target_try_enqueue_state_fn try_enqueue_state;
};

/* BR35 normal-GATT target seam. No display, charge, update, or RCSP hooks. */
bool e87_ble_target_init(const struct e87_ble_target_ingress *ingress);
bool e87_ble_target_poll(void);
bool e87_ble_target_set_writes_enabled(
    bool enabled, uint32_t *out_authorization_epoch);
bool e87_ble_target_authorization_epoch_is_active(
    uint32_t authorization_epoch);

#endif
