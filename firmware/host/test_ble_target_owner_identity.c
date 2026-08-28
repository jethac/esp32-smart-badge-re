#include "test_support.h"

#include "e87_br35_fake.h"
#include "e87_br35_sdk.h"
#include "e87/e87_ble_control.h"
#include "e87/e87_ble_target.h"
#include "e87/e87_ble_target_internal.h"


static const struct e87_ble_peer owner = {
    0u, {0xa1u, 0xa2u, 0xa3u, 0xa4u, 0xa5u, 0xa6u}
};
static const struct e87_ble_peer owner_rpa = {
    1u, {0x41u, 0x32u, 0x23u, 0x14u, 0x05u, 0xf6u}
};

E87_TEST(existing_owner_rpa_waits_for_authoritative_identity_event)
{
    struct e87_owner_record stable;
    uint8_t build[E87_BUILD_INFO_SIZE];
    uint8_t state_packet[E87_STATE_PACKET_SIZE] = {
        1u, 40u, 60u, 0u, 0xbfu, 0x06u, 0u, 0u
    };
    uint32_t authorization_epoch;

    e87_fake_br35_reset();
    E87_ASSERT_TRUE(e87_owner_record_make_stable(&stable, &owner, 7u));
    E87_ASSERT_TRUE(e87_ble_target_journal_save(&stable));
    e87_fake_br35_set_bond(0u, &owner);
    E87_ASSERT_TRUE(e87_ble_target_init(e87_fake_br35_ingress()));
    E87_ASSERT_TRUE(
        e87_ble_target_set_writes_enabled(true, &authorization_epoch));

    e87_fake_br35_emit_connection(&owner_rpa, 0x0440u);
    e87_fake_br35_emit_encryption(0u, 1u);
    E87_ASSERT_EQ_U32(E87_BUILD_INFO_SIZE,
        e87_fake_br35_att_read(0x0440u, E87_ATT_HANDLE_BUILD_VALUE,
                               0u, build, sizeof(build)));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_INSUFFICIENT_AUTHORIZATION,
        e87_fake_br35_att_write(0x0440u, E87_ATT_HANDLE_STATE_VALUE,
                                ATT_TRANSACTION_MODE_NONE, 0u, state_packet,
                                (uint16_t)sizeof(state_packet)));
    E87_ASSERT_EQ_U32(0u, e87_fake_br35.disconnect_calls);

    e87_fake_br35_emit_identity_resolved(&owner_rpa, &owner);
    E87_ASSERT_TRUE(e87_ble_target_poll());
    E87_ASSERT_EQ_U32(E87_BUILD_INFO_SIZE,
        e87_fake_br35_att_read(0x0440u, E87_ATT_HANDLE_BUILD_VALUE,
                               0u, build, sizeof(build)));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_NONE,
        e87_fake_br35_att_write(0x0440u, E87_ATT_HANDLE_STATE_VALUE,
                                ATT_TRANSACTION_MODE_NONE, 0u, state_packet,
                                (uint16_t)sizeof(state_packet)));
    E87_ASSERT_EQ_U32(0u, e87_fake_br35.disconnect_calls);
}

static const struct e87_test_case cases[] = {
    E87_TEST_CASE(existing_owner_rpa_waits_for_authoritative_identity_event),
};

const struct e87_test_suite e87_test_suite = {
    "ble-target-owner-identity", cases, sizeof(cases) / sizeof(cases[0])
};
