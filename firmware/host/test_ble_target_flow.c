#include "test_support.h"

#include "e87_br35_fake.h"
#include "e87_br35_sdk.h"
#include "e87/e87_ble_control.h"
#include "e87/e87_ble_target.h"
#include "e87/e87_ble_target_internal.h"

#include <string.h>

static const struct e87_ble_peer candidate = {
    1u, {0x42u, 0x31u, 0x22u, 0x13u, 0x04u, 0xf5u}
};
static const struct e87_ble_peer other_peer = {
    0u, {0x11u, 0x12u, 0x13u, 0x14u, 0x15u, 0x16u}
};
static const struct e87_ble_peer identity = {
    0u, {0xa1u, 0xa2u, 0xa3u, 0xa4u, 0xa5u, 0xa6u}
};

static bool operation_precedes(enum e87_fake_br35_operation first,
                               enum e87_fake_br35_operation second)
{
    size_t index;
    size_t first_index = E87_FAKE_OPERATION_CAPACITY;
    size_t second_index = E87_FAKE_OPERATION_CAPACITY;
    for (index = 0u; index < e87_fake_br35.operation_count; index += 1u) {
        if (e87_fake_br35.operations[index] == first &&
            first_index == E87_FAKE_OPERATION_CAPACITY) {
            first_index = index;
        }
        if (e87_fake_br35.operations[index] == second &&
            second_index == E87_FAKE_OPERATION_CAPACITY) {
            second_index = index;
        }
    }
    return first_index < second_index;
}

E87_TEST(target_binds_exact_profile_and_enforces_candidate_reconnect)
{
    uint8_t build[E87_BUILD_INFO_SIZE];
    uint8_t state_packet[E87_STATE_PACKET_SIZE] = {
        1u, 40u, 60u, 0u, 0xbfu, 0x06u, 0u, 0u
    };
    struct e87_owner_record journal;
    unsigned int index;
    uint32_t authorization_epoch;

    e87_fake_br35_reset();
    E87_ASSERT_TRUE(e87_ble_target_init(e87_fake_br35_ingress()));
    E87_ASSERT_TRUE(
        e87_ble_target_set_writes_enabled(true, &authorization_epoch));
    E87_ASSERT_EQ_U32(2u, e87_fake_br35.configured_slots);
    E87_ASSERT_TRUE(!e87_fake_br35.configured_allow_cover);
    E87_ASSERT_TRUE(!e87_fake_br35.pair_accept);
    E87_ASSERT_TRUE(e87_fake_br35.advertising_enabled);
    E87_ASSERT_TRUE(e87_fake_br35.profile == e87_normal_gatt_profile);
    E87_ASSERT_TRUE(e87_fake_br35.advertising_data ==
                    e87_normal_advertising_data);
    E87_ASSERT_EQ_U32(E87_NORMAL_ADVERTISING_DATA_SIZE,
                      e87_fake_br35.advertising_length);
    E87_ASSERT_EQ_U32(APP_ADV_IND, e87_fake_br35.advertising_type);
    E87_ASSERT_EQ_U32(APP_ADV_CHANNEL_ALL,
                      e87_fake_br35.advertising_channels);
    E87_ASSERT_TRUE(operation_precedes(E87_FAKE_OP_SM_INIT,
                                       E87_FAKE_OP_APP_BLE_INIT));
    E87_ASSERT_TRUE(operation_precedes(E87_FAKE_OP_PROFILE_SET,
                                       E87_FAKE_OP_ADV_ENABLE));
    E87_ASSERT_TRUE(operation_precedes(E87_FAKE_OP_PAIR_ACCEPT_DISABLE,
                                       E87_FAKE_OP_ADV_ENABLE));

    e87_fake_br35_emit_connection(&candidate, 0x0234u);
    E87_ASSERT_TRUE(!e87_ble_target_journal_load(&journal));
    E87_ASSERT_TRUE(!e87_fake_br35.pair_accept);
    E87_ASSERT_TRUE(e87_ble_target_poll());
    E87_ASSERT_TRUE(e87_ble_target_journal_load(&journal));
    E87_ASSERT_EQ_U32(E87_OWNER_RECORD_REPLACING, journal.phase);
    E87_ASSERT_TRUE(memcmp(&candidate, &journal.candidate,
                           sizeof(candidate)) == 0);
    E87_ASSERT_TRUE(e87_fake_br35.pair_accept);
    E87_ASSERT_TRUE(operation_precedes(E87_FAKE_OP_SYSCFG_WRITE,
                                       E87_FAKE_OP_PAIR_ACCEPT_ENABLE));

    e87_fake_br35_emit_just_works(&other_peer);
    E87_ASSERT_EQ_U32(0u, e87_fake_br35.just_works_confirms);
    e87_fake_br35_emit_just_works(&candidate);
    E87_ASSERT_EQ_U32(1u, e87_fake_br35.just_works_confirms);
    E87_ASSERT_EQ_U32(0x0234u, e87_fake_br35.just_works_handle);

    E87_ASSERT_EQ_U32(0xfe0fu,
        e87_fake_br35_att_read(0x0234u, E87_ATT_HANDLE_BUILD_VALUE,
                               0u, build, sizeof(build)));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_REQUEST_NOT_SUPPORTED,
        e87_fake_br35_att_write(0x0234u, E87_ATT_HANDLE_STATE_VALUE,
                                1u, 0u, state_packet,
                                (uint16_t)sizeof(state_packet)));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_INSUFFICIENT_ENCRYPTION,
        e87_fake_br35_att_write(0x0234u, E87_ATT_HANDLE_STATE_VALUE,
                                ATT_TRANSACTION_MODE_NONE, 0u, state_packet,
                                (uint16_t)sizeof(state_packet)));

    e87_fake_br35_set_identity_mapping(&candidate, &identity);
    e87_fake_br35_set_bond(0u, &identity);
    e87_fake_br35_emit_pair_process_sized(
        SM_EVENT_PAIR_SUB_ADD_LIST_SUCCESS, 15u);
    E87_ASSERT_TRUE(e87_fake_br35.pair_accept);
    e87_fake_br35_emit_pair_process(SM_EVENT_PAIR_SUB_ADD_LIST_SUCCESS);
    e87_fake_br35_emit_encryption(0u, 1u);
    E87_ASSERT_TRUE(e87_fake_br35.pair_accept);
    E87_ASSERT_TRUE(e87_ble_target_journal_load(&journal));
    E87_ASSERT_EQ_U32(E87_OWNER_RECORD_REPLACING, journal.phase);
    for (index = 0u; index < 8u; index += 1u) {
        (void)e87_ble_target_poll();
    }
    E87_ASSERT_TRUE(!e87_fake_br35.pair_accept);
    E87_ASSERT_EQ_U32(1u, e87_fake_br35.disconnect_calls);
    E87_ASSERT_TRUE(e87_ble_target_journal_load(&journal));
    E87_ASSERT_EQ_U32(E87_OWNER_RECORD_RETIRING, journal.phase);
    E87_ASSERT_TRUE(memcmp(&identity, &journal.owner,
                           sizeof(identity)) == 0);

    E87_ASSERT_EQ_U32(E87_ATT_ERROR_UNLIKELY,
        e87_fake_br35_att_write(0x0234u, E87_ATT_HANDLE_STATE_VALUE,
                                ATT_TRANSACTION_MODE_NONE, 0u, state_packet,
                                (uint16_t)sizeof(state_packet)));
    /* Build-info is encryption-gated, not owner-gated by the v1 contract. */
    E87_ASSERT_EQ_U32(E87_BUILD_INFO_SIZE,
        e87_fake_br35_att_read(0x0234u, E87_ATT_HANDLE_BUILD_VALUE,
                               0u, build, sizeof(build)));
    e87_fake_br35_emit_disconnection(0u, 0x13u);
    (void)e87_ble_target_poll();
    e87_fake_br35_emit_connection(&identity, 0x0235u);
    e87_fake_br35_emit_encryption(0u, 1u);
    E87_ASSERT_TRUE(
        e87_ble_target_set_writes_enabled(true, &authorization_epoch));
    E87_ASSERT_EQ_U32(E87_BUILD_INFO_SIZE,
        e87_fake_br35_att_read(0x0235u, E87_ATT_HANDLE_BUILD_VALUE,
                               0u, NULL, 0u));
    E87_ASSERT_EQ_U32(E87_BUILD_INFO_SIZE,
        e87_fake_br35_att_read(0x0235u, E87_ATT_HANDLE_BUILD_VALUE,
                               0u, build, sizeof(build)));
    E87_ASSERT_EQ_U32(0xfe07u,
        e87_fake_br35_att_read(0x0235u, E87_ATT_HANDLE_BUILD_VALUE,
                               E87_BUILD_INFO_SIZE + 1u,
                               build, sizeof(build)));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_NONE,
        e87_fake_br35_att_write(0x0235u, E87_ATT_HANDLE_STATE_VALUE,
                                ATT_TRANSACTION_MODE_NONE, 0u, state_packet,
                                (uint16_t)sizeof(state_packet)));
    E87_ASSERT_EQ_U32(0xfe0eu,
        e87_fake_br35_att_read(0x9999u, E87_ATT_HANDLE_BUILD_VALUE,
                               0u, build, sizeof(build)));
}

static const struct e87_test_case cases[] = {
    E87_TEST_CASE(target_binds_exact_profile_and_enforces_candidate_reconnect),
};

const struct e87_test_suite e87_test_suite = {
    "ble-target-flow", cases, sizeof(cases) / sizeof(cases[0])
};
