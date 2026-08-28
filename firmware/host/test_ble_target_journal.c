#include "test_support.h"

#include "e87_br35_fake.h"
#include "e87/e87_ble_target_internal.h"

#include <string.h>

static const struct e87_ble_peer owner_a = {
    0u, {0x10u, 0x20u, 0x30u, 0x40u, 0x50u, 0x60u}
};
static const struct e87_ble_peer owner_b = {
    1u, {0xc1u, 0x21u, 0x31u, 0x41u, 0x51u, 0x61u}
};

static bool records_equal(const struct e87_owner_record *left,
                          const struct e87_owner_record *right)
{
    return left->magic == right->magic &&
           left->version == right->version &&
           left->phase == right->phase &&
           left->generation == right->generation &&
           left->has_owner == right->has_owner &&
           memcmp(&left->owner, &right->owner, sizeof(left->owner)) == 0 &&
           memcmp(&left->candidate, &right->candidate,
                  sizeof(left->candidate)) == 0 &&
           left->checksum == right->checksum;
}

E87_TEST(double_slot_crc_journal_survives_short_io_and_corruption)
{
    struct e87_owner_record first;
    struct e87_owner_record second;
    struct e87_owner_record loaded;

    e87_fake_br35_reset();
    E87_ASSERT_TRUE(!e87_ble_target_journal_load(&loaded));
    E87_ASSERT_EQ_U32(E87_BLE_OWNER_JOURNAL_SLOT_B_ID,
                      e87_fake_br35.last_syscfg_read_id);
    E87_ASSERT_EQ_U32(E87_BLE_OWNER_JOURNAL_WIRE_SIZE,
                      e87_fake_br35.last_syscfg_read_length);

    E87_ASSERT_TRUE(e87_owner_record_make_stable(&first, &owner_a, 7u));
    E87_ASSERT_TRUE(e87_ble_target_journal_save(&first));
    E87_ASSERT_EQ_U32(E87_BLE_OWNER_JOURNAL_SLOT_A_ID,
                      e87_fake_br35.last_syscfg_write_id);
    E87_ASSERT_EQ_U32(E87_BLE_OWNER_JOURNAL_WIRE_SIZE,
                      e87_fake_br35.last_syscfg_write_length);
    E87_ASSERT_EQ_U32(E87_BLE_OWNER_JOURNAL_WIRE_SIZE,
                      e87_fake_br35.syscfg_48_length);
    E87_ASSERT_TRUE(e87_ble_target_journal_load(&loaded));
    E87_ASSERT_TRUE(records_equal(&first, &loaded));

    E87_ASSERT_TRUE(e87_owner_record_make_stable(&second, &owner_b, 8u));
    e87_fake_br35.short_next_write = true;
    E87_ASSERT_TRUE(!e87_ble_target_journal_save(&second));
    E87_ASSERT_EQ_U32(E87_BLE_OWNER_JOURNAL_SLOT_B_ID,
                      e87_fake_br35.last_syscfg_write_id);
    E87_ASSERT_TRUE(e87_ble_target_journal_load(&loaded));
    E87_ASSERT_TRUE(records_equal(&first, &loaded));

    E87_ASSERT_TRUE(e87_ble_target_journal_save(&second));
    E87_ASSERT_EQ_U32(E87_BLE_OWNER_JOURNAL_SLOT_B_ID,
                      e87_fake_br35.last_syscfg_write_id);
    E87_ASSERT_TRUE(e87_ble_target_journal_load(&loaded));
    E87_ASSERT_TRUE(records_equal(&second, &loaded));

    e87_fake_br35.short_next_read = true;
    E87_ASSERT_TRUE(e87_ble_target_journal_load(&loaded));
    E87_ASSERT_TRUE(records_equal(&second, &loaded));

    e87_fake_br35.syscfg_49[17] ^= 0x80u;
    E87_ASSERT_TRUE(e87_ble_target_journal_load(&loaded));
    E87_ASSERT_TRUE(records_equal(&first, &loaded));
}

static const struct e87_test_case cases[] = {
    E87_TEST_CASE(double_slot_crc_journal_survives_short_io_and_corruption),
};

const struct e87_test_suite e87_test_suite = {
    "ble-target-journal", cases, sizeof(cases) / sizeof(cases[0])
};
