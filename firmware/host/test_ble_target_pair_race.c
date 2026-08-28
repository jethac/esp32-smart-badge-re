#include "test_support.h"

#include "e87_br35_fake.h"
#include "e87/e87_ble_target.h"

static const struct e87_ble_peer candidate = {
    1u, {0x61u, 0x52u, 0x43u, 0x34u, 0x25u, 0xf6u}
};
static const struct e87_ble_peer racer = {
    0u, {0x71u, 0x62u, 0x53u, 0x44u, 0x35u, 0x26u}
};

E87_TEST(second_peer_race_closes_global_pair_gate_before_sm_admission)
{
    e87_fake_br35_reset();
    E87_ASSERT_TRUE(e87_ble_target_init(e87_fake_br35_ingress()));
    E87_ASSERT_TRUE(!e87_fake_br35.pair_accept);

    e87_fake_br35_emit_connection(&candidate, 0x0410u);
    E87_ASSERT_TRUE(!e87_fake_br35.pair_accept);
    E87_ASSERT_TRUE(e87_ble_target_poll());
    E87_ASSERT_TRUE(e87_fake_br35.pair_accept);

    e87_fake_br35_emit_connection(&racer, 0x0411u);
    E87_ASSERT_TRUE(!e87_fake_br35.pair_accept);
    e87_fake_br35_emit_just_works(&racer);
    E87_ASSERT_EQ_U32(0u, e87_fake_br35.just_works_confirms);
    E87_ASSERT_TRUE(!e87_fake_br35.advertising_enabled);
}

static const struct e87_test_case cases[] = {
    E87_TEST_CASE(second_peer_race_closes_global_pair_gate_before_sm_admission),
};

const struct e87_test_suite e87_test_suite = {
    "ble-target-pair-race", cases, sizeof(cases) / sizeof(cases[0])
};
