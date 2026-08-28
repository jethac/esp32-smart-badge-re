#include "test_support.h"
#include "e87/e87_stage0_adv.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

static bool bytes_equal(const void *left, const void *right, size_t length)
{
    return memcmp(left, right, length) == 0;
}

E87_TEST(advertisement_matches_the_exact_golden_vector)
{
    static const uint8_t expected[E87_STAGE0_ADV_DATA_LENGTH] = {
        UINT8_C(0x02), UINT8_C(0x01), UINT8_C(0x06),
        UINT8_C(0x10), UINT8_C(0x09),
        UINT8_C('E'), UINT8_C('8'), UINT8_C('7'), UINT8_C('-'),
        UINT8_C('S'), UINT8_C('0'), UINT8_C('-'),
        UINT8_C('1'), UINT8_C('A'), UINT8_C('2'), UINT8_C('B'),
        UINT8_C('3'), UINT8_C('C'), UINT8_C('4'), UINT8_C('D'),
        UINT8_C(0x08), UINT8_C(0xFF), UINT8_C(0xFF), UINT8_C(0xFF),
        UINT8_C(0x00), UINT8_C(0x4D), UINT8_C(0x3C), UINT8_C(0x2B),
        UINT8_C(0x1A),
    };
    uint8_t actual[E87_STAGE0_ADV_DATA_LENGTH];
    size_t actual_length = 0U;

    memset(actual, 0xA5, sizeof(actual));
    E87_ASSERT_TRUE(e87_stage0_adv_build(UINT64_C(0x1A2B3C4D),
                                         actual, sizeof(actual),
                                         &actual_length));
    E87_ASSERT_EQ_U32(E87_STAGE0_ADV_DATA_LENGTH, actual_length);
    E87_ASSERT_TRUE(bytes_equal(expected, actual, sizeof(expected)));
}

E87_TEST(tag_text_is_always_eight_uppercase_hex_digits_and_numeric_tag_is_le)
{
    static const uint8_t expected_name[E87_STAGE0_LOCAL_NAME_LENGTH] = {
        UINT8_C('E'), UINT8_C('8'), UINT8_C('7'), UINT8_C('-'),
        UINT8_C('S'), UINT8_C('0'), UINT8_C('-'),
        UINT8_C('A'), UINT8_C('B'), UINT8_C('C'), UINT8_C('D'),
        UINT8_C('E'), UINT8_C('F'), UINT8_C('0'), UINT8_C('9'),
    };
    static const uint8_t expected_le[4] = {
        UINT8_C(0x09), UINT8_C(0xEF), UINT8_C(0xCD), UINT8_C(0xAB),
    };
    uint8_t actual[E87_STAGE0_ADV_DATA_LENGTH];
    size_t actual_length = 0U;

    E87_ASSERT_TRUE(e87_stage0_adv_build(UINT64_C(0xABCDEF09),
                                         actual, sizeof(actual),
                                         &actual_length));
    E87_ASSERT_EQ_U32(E87_STAGE0_ADV_DATA_LENGTH, actual_length);
    E87_ASSERT_TRUE(bytes_equal(expected_name, &actual[5],
                                sizeof(expected_name)));
    E87_ASSERT_TRUE(bytes_equal(expected_le, &actual[25],
                                sizeof(expected_le)));
}

E87_TEST(advertisement_rejects_bad_arguments_without_partial_output)
{
    uint8_t actual[E87_STAGE0_ADV_DATA_LENGTH];
    uint8_t before[E87_STAGE0_ADV_DATA_LENGTH];
    size_t actual_length = 0xA5A5U;

    memset(actual, 0x5A, sizeof(actual));
    memcpy(before, actual, sizeof(before));
    E87_ASSERT_TRUE(!e87_stage0_adv_build(UINT64_C(0x100000000),
                                          actual, sizeof(actual),
                                          &actual_length));
    E87_ASSERT_TRUE(bytes_equal(before, actual, sizeof(before)));
    E87_ASSERT_EQ_U32(UINT32_C(0xA5A5), actual_length);
    E87_ASSERT_TRUE(!e87_stage0_adv_build(UINT64_C(0), NULL,
                                          sizeof(actual), &actual_length));
    E87_ASSERT_TRUE(!e87_stage0_adv_build(UINT64_C(0), actual,
                                          sizeof(actual) - 1U,
                                          &actual_length));
    E87_ASSERT_TRUE(!e87_stage0_adv_build(UINT64_C(0), actual,
                                          sizeof(actual), NULL));
    E87_ASSERT_TRUE(bytes_equal(before, actual, sizeof(before)));
    E87_ASSERT_EQ_U32(UINT32_C(0xA5A5), actual_length);
}

E87_TEST(scan_response_is_zero_length_with_a_stable_non_null_pointer)
{
    size_t first_length = SIZE_MAX;
    size_t second_length = SIZE_MAX;
    const uint8_t *first = e87_stage0_scan_response(&first_length);
    const uint8_t *second = e87_stage0_scan_response(&second_length);

    E87_ASSERT_TRUE(first != NULL);
    E87_ASSERT_TRUE(first == second);
    E87_ASSERT_EQ_U32(UINT32_C(0), first_length);
    E87_ASSERT_EQ_U32(UINT32_C(0), second_length);
    E87_ASSERT_TRUE(e87_stage0_scan_response(NULL) == NULL);
}

E87_TEST(static_random_address_matches_the_frozen_uuid_vector)
{
    static const uint8_t uuid[E87_STAGE0_FLASH_UUID_LENGTH] = {
        UINT8_C(0x00), UINT8_C(0x01), UINT8_C(0x02), UINT8_C(0x03),
        UINT8_C(0x04), UINT8_C(0x05), UINT8_C(0x06), UINT8_C(0x07),
        UINT8_C(0x08), UINT8_C(0x09), UINT8_C(0x0A), UINT8_C(0x0B),
        UINT8_C(0x0C), UINT8_C(0x0D), UINT8_C(0x0E), UINT8_C(0x0F),
    };
    static const uint8_t expected[E87_STAGE0_RANDOM_ADDRESS_LENGTH] = {
        UINT8_C(0xE5), UINT8_C(0xB4), UINT8_C(0x40),
        UINT8_C(0xD6), UINT8_C(0x0C), UINT8_C(0xCD),
    };
    uint8_t actual[E87_STAGE0_RANDOM_ADDRESS_LENGTH];

    memset(actual, 0, sizeof(actual));
    E87_ASSERT_TRUE(e87_stage0_derive_static_random_address(uuid, actual));
    E87_ASSERT_TRUE(bytes_equal(expected, actual, sizeof(expected)));
    E87_ASSERT_TRUE(e87_stage0_static_random_address_is_valid(actual));
}

E87_TEST(static_random_address_uses_every_uuid_byte)
{
    uint8_t baseline_uuid[E87_STAGE0_FLASH_UUID_LENGTH];
    uint8_t changed_uuid[E87_STAGE0_FLASH_UUID_LENGTH];
    uint8_t baseline_address[E87_STAGE0_RANDOM_ADDRESS_LENGTH];
    uint8_t changed_address[E87_STAGE0_RANDOM_ADDRESS_LENGTH];
    size_t index;

    for (index = 0U; index < sizeof(baseline_uuid); index += 1U) {
        baseline_uuid[index] = (uint8_t)index;
    }
    E87_ASSERT_TRUE(e87_stage0_derive_static_random_address(
        baseline_uuid, baseline_address));
    for (index = 0U; index < sizeof(baseline_uuid); index += 1U) {
        memcpy(changed_uuid, baseline_uuid, sizeof(changed_uuid));
        changed_uuid[index] ^= UINT8_C(0x80);
        E87_ASSERT_TRUE(e87_stage0_derive_static_random_address(
            changed_uuid, changed_address));
        E87_ASSERT_TRUE(!bytes_equal(baseline_address, changed_address,
                                     sizeof(baseline_address)));
    }
}

E87_TEST(static_random_address_rejects_degenerate_inputs_atomically)
{
    static const uint8_t zero_uuid[E87_STAGE0_FLASH_UUID_LENGTH] = {0};
    uint8_t ones_uuid[E87_STAGE0_FLASH_UUID_LENGTH];
    uint8_t actual[E87_STAGE0_RANDOM_ADDRESS_LENGTH];
    uint8_t before[E87_STAGE0_RANDOM_ADDRESS_LENGTH];

    memset(ones_uuid, 0xFF, sizeof(ones_uuid));
    memset(actual, 0xA5, sizeof(actual));
    memcpy(before, actual, sizeof(before));
    E87_ASSERT_TRUE(!e87_stage0_derive_static_random_address(NULL, actual));
    E87_ASSERT_TRUE(!e87_stage0_derive_static_random_address(zero_uuid, actual));
    E87_ASSERT_TRUE(!e87_stage0_derive_static_random_address(ones_uuid, actual));
    E87_ASSERT_TRUE(!e87_stage0_derive_static_random_address(zero_uuid, NULL));
    E87_ASSERT_TRUE(bytes_equal(before, actual, sizeof(before)));
}

E87_TEST(static_random_address_validity_rejects_reserved_and_wrong_type_values)
{
    static const uint8_t all_zero_random_part[6] = {
        0, 0, 0, 0, 0, UINT8_C(0xC0),
    };
    static const uint8_t all_one_random_part[6] = {
        UINT8_C(0xFF), UINT8_C(0xFF), UINT8_C(0xFF),
        UINT8_C(0xFF), UINT8_C(0xFF), UINT8_C(0xFF),
    };
    static const uint8_t wrong_address_type[6] = {
        1, 0, 0, 0, 0, UINT8_C(0x80),
    };
    static const uint8_t valid[6] = {
        1, 0, 0, 0, 0, UINT8_C(0xC0),
    };

    E87_ASSERT_TRUE(!e87_stage0_static_random_address_is_valid(NULL));
    E87_ASSERT_TRUE(!e87_stage0_static_random_address_is_valid(
        all_zero_random_part));
    E87_ASSERT_TRUE(!e87_stage0_static_random_address_is_valid(
        all_one_random_part));
    E87_ASSERT_TRUE(!e87_stage0_static_random_address_is_valid(
        wrong_address_type));
    E87_ASSERT_TRUE(e87_stage0_static_random_address_is_valid(valid));
}

static const struct e87_test_case stage0_adv_cases[] = {
    E87_TEST_CASE(advertisement_matches_the_exact_golden_vector),
    E87_TEST_CASE(tag_text_is_always_eight_uppercase_hex_digits_and_numeric_tag_is_le),
    E87_TEST_CASE(advertisement_rejects_bad_arguments_without_partial_output),
    E87_TEST_CASE(scan_response_is_zero_length_with_a_stable_non_null_pointer),
    E87_TEST_CASE(static_random_address_matches_the_frozen_uuid_vector),
    E87_TEST_CASE(static_random_address_uses_every_uuid_byte),
    E87_TEST_CASE(static_random_address_rejects_degenerate_inputs_atomically),
    E87_TEST_CASE(static_random_address_validity_rejects_reserved_and_wrong_type_values),
};

const struct e87_test_suite e87_test_suite = {
    "stage0-adv",
    stage0_adv_cases,
    sizeof(stage0_adv_cases) / sizeof(stage0_adv_cases[0]),
};
