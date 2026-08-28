#include "test_support.h"

#include "e87_br35_fake.h"
#include "e87/e87_ble_target.h"

static const struct e87_ble_peer candidate = {
    1u, {0x91u, 0x82u, 0x73u, 0x64u, 0x55u, 0xf6u}
};

E87_TEST(pair_gate_enable_failure_disconnects_and_stays_closed)
{
    e87_fake_br35_reset();
    E87_ASSERT_TRUE(e87_ble_target_init(e87_fake_br35_ingress()));
    e87_fake_br35.fail_operation = E87_FAKE_OP_PAIR_ACCEPT_ENABLE;
    e87_fake_br35.fail_count = 1;

    e87_fake_br35_emit_connection(&candidate, 0x0430u);
    E87_ASSERT_TRUE(!e87_fake_br35.pair_accept);
    E87_ASSERT_TRUE(!e87_ble_target_poll());
    E87_ASSERT_TRUE(!e87_fake_br35.pair_accept);
    e87_fake_br35_emit_just_works(&candidate);
    E87_ASSERT_EQ_U32(0u, e87_fake_br35.just_works_confirms);
    E87_ASSERT_TRUE(e87_ble_target_poll());
    E87_ASSERT_EQ_U32(1u, e87_fake_br35.disconnect_calls);
    E87_ASSERT_TRUE(!e87_fake_br35.advertising_enabled);
}

static const struct e87_test_case cases[] = {
    E87_TEST_CASE(pair_gate_enable_failure_disconnects_and_stays_closed),
};

const struct e87_test_suite e87_test_suite = {
    "ble-target-pair-failure", cases, sizeof(cases) / sizeof(cases[0])
};
