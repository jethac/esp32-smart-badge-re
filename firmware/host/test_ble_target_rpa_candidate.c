#include "test_support.h"

#include "e87_br35_fake.h"
#include "e87_br35_sdk.h"
#include "e87/e87_ble_target.h"
#include "e87/e87_ble_target_internal.h"

#include <string.h>

static const struct e87_ble_peer candidate_rpa = {
    1u, {0x41u, 0x32u, 0x23u, 0x14u, 0x05u, 0xf6u}
};

E87_TEST(new_owner_rpa_is_not_persisted_without_authoritative_identity)
{
    struct e87_owner_record journal;
    unsigned int index;

    e87_fake_br35_reset();
    E87_ASSERT_TRUE(e87_ble_target_init(e87_fake_br35_ingress()));
    e87_fake_br35_emit_connection(&candidate_rpa, 0x0441u);
    E87_ASSERT_TRUE(e87_ble_target_poll());
    E87_ASSERT_TRUE(e87_fake_br35.pair_accept);

    /* A vendor slot containing only the transient RPA is not an identity. */
    e87_fake_br35_set_bond(0u, &candidate_rpa);
    e87_fake_br35_emit_pair_process(SM_EVENT_PAIR_SUB_ADD_LIST_SUCCESS);
    e87_fake_br35_emit_encryption(0u, 1u);
    for (index = 0u; index < 8u; index += 1u) {
        (void)e87_ble_target_poll();
    }

    E87_ASSERT_TRUE(!e87_fake_br35.pair_accept);
    E87_ASSERT_EQ_U32(1u, e87_fake_br35.disconnect_calls);
    E87_ASSERT_TRUE(e87_ble_target_journal_load(&journal));
    E87_ASSERT_TRUE(!journal.has_owner ||
                    memcmp(&journal.owner, &candidate_rpa,
                           sizeof(candidate_rpa)) != 0);
}

static const struct e87_test_case cases[] = {
    E87_TEST_CASE(new_owner_rpa_is_not_persisted_without_authoritative_identity),
};

const struct e87_test_suite e87_test_suite = {
    "ble-target-rpa-candidate", cases, sizeof(cases) / sizeof(cases[0])
};
