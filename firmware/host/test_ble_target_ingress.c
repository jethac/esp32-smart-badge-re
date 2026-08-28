#include "test_support.h"

#include "e87_br35_fake.h"
#include "e87_br35_sdk.h"
#include "e87/e87_ble_control.h"
#include "e87/e87_ble_target.h"
#include "e87/e87_ble_target_internal.h"

#include <string.h>

static const struct e87_ble_peer owner = {
    0u, {0xb1u, 0xb2u, 0xb3u, 0xb4u, 0xb5u, 0xb6u}
};

static const struct e87_ble_peer intruder = {
    1u, {0xc1u, 0xc2u, 0xc3u, 0xc4u, 0xc5u, 0xc6u}
};

struct ingress_capture {
    unsigned int calls;
    bool accept;
    bool close_during_enqueue;
    bool close_result;
    uint32_t epoch;
    uint32_t close_epoch;
    uint8_t packet[E87_BLE_TARGET_STATE_PACKET_SIZE];
};

static bool try_enqueue_state(
    void *context,
    uint32_t epoch,
    const uint8_t packet[E87_BLE_TARGET_STATE_PACKET_SIZE])
{
    struct ingress_capture *capture = context;
    capture->calls += 1u;
    capture->epoch = epoch;
    memcpy(capture->packet, packet, sizeof(capture->packet));
    if (capture->close_during_enqueue) {
        capture->close_result =
            e87_ble_target_set_writes_enabled(false,
                                               &capture->close_epoch);
    }
    return capture->accept;
}

static bool close_writes(uint32_t *out_epoch)
{
    return e87_ble_target_set_writes_enabled(false, out_epoch);
}

E87_TEST(epoch_advance_exhausts_without_wrap_or_aba)
{
    uint32_t epoch = UINT32_MAX - 1u;
    bool exhausted = false;

    E87_ASSERT_TRUE(e87_ble_target_epoch_advance(&epoch, &exhausted));
    E87_ASSERT_EQ_U32(UINT32_MAX, epoch);
    E87_ASSERT_TRUE(!exhausted);
    E87_ASSERT_TRUE(!e87_ble_target_epoch_advance(&epoch, &exhausted));
    E87_ASSERT_EQ_U32(UINT32_MAX, epoch);
    E87_ASSERT_TRUE(exhausted);
    E87_ASSERT_TRUE(!e87_ble_target_epoch_advance(&epoch, &exhausted));
    E87_ASSERT_EQ_U32(UINT32_MAX, epoch);
    E87_ASSERT_TRUE(exhausted);
    E87_ASSERT_TRUE(!e87_ble_target_epoch_advance(NULL, &exhausted));
    E87_ASSERT_TRUE(!e87_ble_target_epoch_advance(&epoch, NULL));
}

E87_TEST(target_validates_transport_then_copies_to_core_ingress_only)
{
    struct e87_owner_record stable;
    struct ingress_capture capture = {
        0u, true, false, false, 0u, 0u, {0u}
    };
    const struct e87_ble_target_ingress ingress = {
        &capture, try_enqueue_state
    };
    uint8_t build[E87_BUILD_INFO_SIZE];
    uint8_t valid_packet[E87_BLE_TARGET_STATE_PACKET_SIZE] = {
        1u, 40u, 60u, 0u, 0xbfu, 0x06u, 0u, 0u
    };
    uint8_t invalid_packet[E87_BLE_TARGET_STATE_PACKET_SIZE] = {
        0xffu, 0xfeu, 0xfdu, 0xfcu, 0xfbu, 0xfau, 0xf9u, 0xf8u
    };
    uint32_t enabled_epoch;
    uint32_t closed_epoch;
    uint32_t repeated_close_epoch;
    uint32_t post_encryption_epoch;
    uint32_t reconnect_epoch;
    uint32_t reopened_epoch;
    uint32_t owner_restored_epoch;
    uint32_t post_recheck_epoch;

    e87_fake_br35_reset();
    E87_ASSERT_TRUE(!e87_ble_target_init(NULL));
    E87_ASSERT_EQ_U32(0u, e87_fake_br35.operation_count);
    E87_ASSERT_TRUE(e87_owner_record_make_stable(&stable, &owner, 3u));
    E87_ASSERT_TRUE(e87_ble_target_journal_save(&stable));
    e87_fake_br35_set_bond(0u, &owner);
    E87_ASSERT_TRUE(e87_ble_target_init(&ingress));
    e87_fake_br35_emit_connection(&owner, 0x0550u);
    e87_fake_br35_emit_encryption(0u, 1u);

    E87_ASSERT_EQ_U32(E87_BUILD_INFO_SIZE,
        e87_fake_br35_att_read(0x0550u, E87_ATT_HANDLE_BUILD_VALUE,
                               0u, build, sizeof(build)));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_UNLIKELY,
        e87_fake_br35_att_write(0x0550u, E87_ATT_HANDLE_STATE_VALUE,
                                ATT_TRANSACTION_MODE_NONE, 0u, valid_packet,
                                (uint16_t)sizeof(valid_packet)));
    E87_ASSERT_EQ_U32(0u, capture.calls);
    E87_ASSERT_TRUE(e87_ble_target_set_writes_enabled(true, &enabled_epoch));
    E87_ASSERT_TRUE(enabled_epoch != 0u);
    E87_ASSERT_TRUE(
        e87_ble_target_authorization_epoch_is_active(enabled_epoch));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_REQUEST_NOT_SUPPORTED,
        e87_fake_br35_att_write(0x0550u, E87_ATT_HANDLE_STATE_VALUE,
                                1u, 0u, valid_packet,
                                (uint16_t)sizeof(valid_packet)));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_INVALID_OFFSET,
        e87_fake_br35_att_write(0x0550u, E87_ATT_HANDLE_STATE_VALUE,
                                ATT_TRANSACTION_MODE_NONE, 1u, valid_packet,
                                (uint16_t)sizeof(valid_packet)));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_INVALID_ATTRIBUTE_VALUE_LENGTH,
        e87_fake_br35_att_write(0x0550u, E87_ATT_HANDLE_STATE_VALUE,
                                ATT_TRANSACTION_MODE_NONE, 0u, valid_packet,
                                (uint16_t)(sizeof(valid_packet) - 1u)));
    E87_ASSERT_EQ_U32(0u, capture.calls);

    E87_ASSERT_EQ_U32(E87_ATT_ERROR_SEMANTIC_STATE,
        e87_fake_br35_att_write(0x0550u, E87_ATT_HANDLE_STATE_VALUE,
                                ATT_TRANSACTION_MODE_NONE, 0u, invalid_packet,
                                (uint16_t)sizeof(invalid_packet)));
    E87_ASSERT_EQ_U32(0u, capture.calls);

    capture.accept = false;
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_UNLIKELY,
        e87_fake_br35_att_write(0x0550u, E87_ATT_HANDLE_STATE_VALUE,
                                ATT_TRANSACTION_MODE_NONE, 0u, valid_packet,
                                (uint16_t)sizeof(valid_packet)));
    E87_ASSERT_EQ_U32(1u, capture.calls);
    E87_ASSERT_TRUE(memcmp(capture.packet, valid_packet,
                           sizeof(valid_packet)) == 0);

    memset(capture.packet, 0u, sizeof(capture.packet));
    capture.accept = true;
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_NONE,
        e87_fake_br35_att_write(0x0550u, E87_ATT_HANDLE_STATE_VALUE,
                                ATT_TRANSACTION_MODE_NONE, 0u, valid_packet,
                                (uint16_t)sizeof(valid_packet)));
    E87_ASSERT_EQ_U32(2u, capture.calls);
    E87_ASSERT_EQ_U32(enabled_epoch, capture.epoch);
    E87_ASSERT_TRUE(memcmp(capture.packet, valid_packet,
                           sizeof(valid_packet)) == 0);

    /* Encryption loss closes the epoch without revoking lifecycle writes. */
    e87_fake_br35_emit_encryption(0u, 0u);
    E87_ASSERT_TRUE(
        !e87_ble_target_authorization_epoch_is_active(enabled_epoch));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_INSUFFICIENT_ENCRYPTION,
        e87_fake_br35_att_write(0x0550u, E87_ATT_HANDLE_STATE_VALUE,
                                ATT_TRANSACTION_MODE_NONE, 0u, valid_packet,
                                (uint16_t)sizeof(valid_packet)));
    E87_ASSERT_EQ_U32(2u, capture.calls);

    /* Re-encryption alone is insufficient: BuildInfo must be read contiguously. */
    e87_fake_br35_emit_encryption(0u, 1u);
    E87_ASSERT_EQ_U32(E87_BUILD_INFO_SIZE - 4u,
        e87_fake_br35_att_read(0x0550u, E87_ATT_HANDLE_BUILD_VALUE,
                               4u, build, sizeof(build)));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_INSUFFICIENT_AUTHORIZATION,
        e87_fake_br35_att_write(0x0550u, E87_ATT_HANDLE_STATE_VALUE,
                                ATT_TRANSACTION_MODE_NONE, 0u, valid_packet,
                                (uint16_t)sizeof(valid_packet)));
    E87_ASSERT_EQ_U32(4u,
        e87_fake_br35_att_read(0x0550u, E87_ATT_HANDLE_BUILD_VALUE,
                               0u, build, 4u));
    E87_ASSERT_EQ_U32(E87_BUILD_INFO_SIZE - 4u,
        e87_fake_br35_att_read(0x0550u, E87_ATT_HANDLE_BUILD_VALUE,
                               4u, build, sizeof(build)));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_NONE,
        e87_fake_br35_att_write(0x0550u, E87_ATT_HANDLE_STATE_VALUE,
                                ATT_TRANSACTION_MODE_NONE, 0u, valid_packet,
                                (uint16_t)sizeof(valid_packet)));
    E87_ASSERT_EQ_U32(3u, capture.calls);
    post_encryption_epoch = capture.epoch;
    E87_ASSERT_TRUE(post_encryption_epoch > enabled_epoch);
    E87_ASSERT_TRUE(e87_ble_target_authorization_epoch_is_active(
        post_encryption_epoch));

    /* A replacement link must not inherit the prior link's epoch. */
    e87_fake_br35_emit_disconnection(0u, 0x13u);
    E87_ASSERT_TRUE(!e87_ble_target_authorization_epoch_is_active(
        post_encryption_epoch));
    E87_ASSERT_TRUE(e87_ble_target_poll());
    e87_fake_br35_emit_connection(&owner, 0x0551u);
    e87_fake_br35_emit_encryption(0u, 1u);
    E87_ASSERT_EQ_U32(E87_BUILD_INFO_SIZE,
        e87_fake_br35_att_read(0x0551u, E87_ATT_HANDLE_BUILD_VALUE,
                               0u, build, sizeof(build)));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_NONE,
        e87_fake_br35_att_write(0x0551u, E87_ATT_HANDLE_STATE_VALUE,
                                ATT_TRANSACTION_MODE_NONE, 0u, valid_packet,
                                (uint16_t)sizeof(valid_packet)));
    E87_ASSERT_EQ_U32(4u, capture.calls);
    reconnect_epoch = capture.epoch;
    E87_ASSERT_TRUE(reconnect_epoch > post_encryption_epoch);
    E87_ASSERT_TRUE(e87_ble_target_authorization_epoch_is_active(
        reconnect_epoch));

    /* Maintenance closes first, even if the callback was already entered. */
    capture.close_during_enqueue = true;
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_NONE,
        e87_fake_br35_att_write(0x0551u, E87_ATT_HANDLE_STATE_VALUE,
                                ATT_TRANSACTION_MODE_NONE, 0u, valid_packet,
                                (uint16_t)sizeof(valid_packet)));
    E87_ASSERT_EQ_U32(5u, capture.calls);
    E87_ASSERT_TRUE(capture.close_result);
    E87_ASSERT_EQ_U32(reconnect_epoch, capture.epoch);
    closed_epoch = capture.close_epoch;
    E87_ASSERT_TRUE(closed_epoch > reconnect_epoch);
    E87_ASSERT_TRUE(!e87_ble_target_authorization_epoch_is_active(
        reconnect_epoch));
    E87_ASSERT_TRUE(!e87_ble_target_authorization_epoch_is_active(
        closed_epoch));

    /* The close barrier is state-idempotent but invalidates on every call. */
    capture.close_during_enqueue = false;
    E87_ASSERT_TRUE(e87_ble_target_set_writes_enabled(
        false, &repeated_close_epoch));
    E87_ASSERT_TRUE(repeated_close_epoch > closed_epoch);
    E87_ASSERT_TRUE(!e87_ble_target_authorization_epoch_is_active(
        repeated_close_epoch));
    E87_ASSERT_TRUE(e87_ble_target_set_writes_enabled(true, &reopened_epoch));
    E87_ASSERT_TRUE(reopened_epoch > repeated_close_epoch);
    E87_ASSERT_TRUE(e87_ble_target_authorization_epoch_is_active(
        reopened_epoch));

    /* Durable-owner loss advances once; restoring the slot cannot revive ABA. */
    e87_fake_br35.bond_count = 0u;
    E87_ASSERT_TRUE(!e87_ble_target_authorization_epoch_is_active(
        reopened_epoch));
    e87_fake_br35_set_bond(0u, &owner);
    E87_ASSERT_TRUE(!e87_ble_target_authorization_epoch_is_active(
        reopened_epoch));
    E87_ASSERT_TRUE(e87_ble_target_set_writes_enabled(
        true, &owner_restored_epoch));
    E87_ASSERT_TRUE(owner_restored_epoch > reopened_epoch);
    E87_ASSERT_TRUE(e87_ble_target_authorization_epoch_is_active(
        owner_restored_epoch));

    /* A gate close inside the final owner check is caught before enqueue. */
    e87_fake_br35.close_writes = close_writes;
    e87_fake_br35.close_writes_on_bond_exists_call =
        e87_fake_br35.bond_exists_calls + 2u;
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_UNLIKELY,
        e87_fake_br35_att_write(0x0551u, E87_ATT_HANDLE_STATE_VALUE,
                                ATT_TRANSACTION_MODE_NONE, 0u, valid_packet,
                                (uint16_t)sizeof(valid_packet)));
    E87_ASSERT_TRUE(e87_fake_br35.close_writes_result);
    E87_ASSERT_EQ_U32(5u, capture.calls);
    E87_ASSERT_TRUE(!e87_ble_target_authorization_epoch_is_active(
        owner_restored_epoch));
    E87_ASSERT_TRUE(e87_ble_target_set_writes_enabled(
        true, &post_recheck_epoch));
    E87_ASSERT_TRUE(post_recheck_epoch > owner_restored_epoch);
    E87_ASSERT_TRUE(e87_ble_target_authorization_epoch_is_active(
        post_recheck_epoch));

    /* A distinct synchronous connection fact closes authorization immediately. */
    e87_fake_br35_emit_connection(&intruder, 0x0552u);
    E87_ASSERT_TRUE(!e87_ble_target_authorization_epoch_is_active(
        post_recheck_epoch));
}

static const struct e87_test_case cases[] = {
    E87_TEST_CASE(epoch_advance_exhausts_without_wrap_or_aba),
    E87_TEST_CASE(target_validates_transport_then_copies_to_core_ingress_only),
};

const struct e87_test_suite e87_test_suite = {
    "ble-target-ingress", cases, sizeof(cases) / sizeof(cases[0])
};
