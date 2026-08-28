#include "test_support.h"

#include "e87_br35_fake.h"
#include "e87/e87_ble_target.h"

static const struct e87_ble_peer candidate = {
    1u, {0x81u, 0x72u, 0x63u, 0x54u, 0x45u, 0xf6u}
};

E87_TEST(candidate_disconnect_closes_pair_gate_before_readvertising)
{
    unsigned int index;

    e87_fake_br35_reset();
    E87_ASSERT_TRUE(e87_ble_target_init(e87_fake_br35_ingress()));
    e87_fake_br35_emit_connection(&candidate, 0x0420u);
    E87_ASSERT_TRUE(!e87_fake_br35.pair_accept);
    E87_ASSERT_TRUE(e87_ble_target_poll());
    E87_ASSERT_TRUE(e87_fake_br35.pair_accept);

    e87_fake_br35_emit_disconnection(0u, 0x13u);
    E87_ASSERT_TRUE(e87_fake_br35.pair_accept);
    E87_ASSERT_TRUE(!e87_fake_br35.advertising_enabled);
    E87_ASSERT_TRUE(e87_ble_target_poll());
    E87_ASSERT_TRUE(!e87_fake_br35.pair_accept);
    for (index = 0u; index < 8u; index += 1u) {
        (void)e87_ble_target_poll();
    }
    E87_ASSERT_TRUE(!e87_fake_br35.pair_accept);
    E87_ASSERT_TRUE(e87_fake_br35.advertising_enabled);
}

static const struct e87_test_case cases[] = {
    E87_TEST_CASE(candidate_disconnect_closes_pair_gate_before_readvertising),
};

const struct e87_test_suite e87_test_suite = {
    "ble-target-disconnect-race", cases, sizeof(cases) / sizeof(cases[0])
};
