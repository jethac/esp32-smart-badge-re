#include "test_support.h"

#include "e87_br35_fake.h"
#include "e87/e87_ble_target.h"

static const struct e87_ble_peer candidate = {
    1u, {0x51u, 0x42u, 0x33u, 0x24u, 0x15u, 0xf6u}
};

E87_TEST(vendor_and_persistence_failures_stay_closed_and_retry)
{
    e87_fake_br35_reset();
    e87_fake_br35.fail_operation = E87_FAKE_OP_PROFILE_SET;
    e87_fake_br35.fail_count = 1;
    E87_ASSERT_TRUE(!e87_ble_target_init(e87_fake_br35_ingress()));
    E87_ASSERT_EQ_U32(1u, e87_fake_br35.free_calls);
    E87_ASSERT_TRUE(!e87_fake_br35.advertising_enabled);

    e87_fake_br35_reset();
    e87_fake_br35.fail_operation = E87_FAKE_OP_PAIR_ACCEPT_DISABLE;
    e87_fake_br35.fail_count = 1;
    E87_ASSERT_TRUE(e87_ble_target_init(e87_fake_br35_ingress()));
    E87_ASSERT_TRUE(!e87_fake_br35.advertising_enabled);
    E87_ASSERT_TRUE(!e87_fake_br35.pair_accept);

    e87_fake_br35.fail_operation = E87_FAKE_OP_ADV_ENABLE;
    e87_fake_br35.fail_count = 1;
    E87_ASSERT_TRUE(!e87_ble_target_poll());
    E87_ASSERT_TRUE(!e87_fake_br35.pair_accept);
    E87_ASSERT_TRUE(!e87_fake_br35.advertising_enabled);

    e87_fake_br35.fail_operation = E87_FAKE_OP_HANDLE_FREE;
    e87_fake_br35.fail_count = 0;
    E87_ASSERT_TRUE(e87_ble_target_poll());
    E87_ASSERT_TRUE(!e87_fake_br35.pair_accept);
    E87_ASSERT_TRUE(e87_fake_br35.advertising_enabled);

    e87_fake_br35.short_next_write = true;
    e87_fake_br35_emit_connection(&candidate, 0x0310u);
    E87_ASSERT_TRUE(!e87_fake_br35.advertising_enabled);
    E87_ASSERT_EQ_U32(0u, e87_fake_br35.syscfg_48_length);
    E87_ASSERT_TRUE(!e87_ble_target_poll());
    E87_ASSERT_EQ_U32(47u, e87_fake_br35.syscfg_48_length);
    E87_ASSERT_TRUE(!e87_fake_br35.pair_accept);
    e87_fake_br35_emit_just_works(&candidate);
    E87_ASSERT_EQ_U32(0u, e87_fake_br35.just_works_confirms);

    E87_ASSERT_TRUE(e87_ble_target_poll());
    E87_ASSERT_EQ_U32(1u, e87_fake_br35.disconnect_calls);
    E87_ASSERT_TRUE(e87_ble_target_poll());
    e87_fake_br35_emit_just_works(&candidate);
    E87_ASSERT_EQ_U32(0u, e87_fake_br35.just_works_confirms);
}

static const struct e87_test_case cases[] = {
    E87_TEST_CASE(vendor_and_persistence_failures_stay_closed_and_retry),
};

const struct e87_test_suite e87_test_suite = {
    "ble-target-fail-closed", cases, sizeof(cases) / sizeof(cases[0])
};
