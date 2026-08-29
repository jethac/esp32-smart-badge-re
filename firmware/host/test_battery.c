#include "test_support.h"
#include "e87/e87_battery.h"

#include <stddef.h>
#include <stdint.h>
#include <string.h>


static bool bytes_equal(const void *left, const void *right, size_t length)
{
    return memcmp(left, right, length) == 0;
}


E87_TEST(constants_pin_canonical_full_cell_domain)
{
    E87_ASSERT_EQ_U32(UINT32_C(8), E87_BATTERY_SAMPLE_COUNT);
    E87_ASSERT_EQ_U32(UINT32_C(1), E87_BATTERY_FULL_MV_MIN);
    E87_ASSERT_EQ_U32(UINT32_C(5000), E87_BATTERY_FULL_MV_MAX);
    E87_ASSERT_EQ_U32(UINT32_C(4), E87_BATTERY_QUARTER_DIVISOR);
}


E87_TEST(quarter_conversion_is_checked_and_output_atomic)
{
    static const struct {
        uint32_t quarter_mv;
        bool accepted;
        uint32_t expected_full_mv;
    } vectors[] = {
        {UINT32_C(0), false, UINT32_C(0)},
        {UINT32_C(1), true, UINT32_C(4)},
        {UINT32_C(1250), true, UINT32_C(5000)},
        {UINT32_C(1251), false, UINT32_C(0)},
        {UINT32_MAX / UINT32_C(4), false, UINT32_C(0)},
        {UINT32_MAX / UINT32_C(4) + UINT32_C(1), false, UINT32_C(0)},
        {UINT32_MAX, false, UINT32_C(0)}
    };
    size_t index;

    for (index = 0U; index < sizeof(vectors) / sizeof(vectors[0]); index += 1U) {
        uint32_t output = UINT32_C(0xA5A5A5A5);
        const bool result = e87_battery_full_mv_from_quarter_mv(
            vectors[index].quarter_mv, &output);

        E87_ASSERT_EQ_U32(vectors[index].accepted, result);
        if (vectors[index].accepted) {
            E87_ASSERT_EQ_U32(vectors[index].expected_full_mv, output);
        } else {
            E87_ASSERT_EQ_U32(UINT32_C(0xA5A5A5A5), output);
        }
    }

    E87_ASSERT_TRUE(!e87_battery_full_mv_from_quarter_mv(
        UINT32_C(1000), NULL));
}


E87_TEST(filter_rejects_arguments_without_input_or_output_mutation)
{
    static const uint32_t baseline[E87_BATTERY_SAMPLE_COUNT] = {
        UINT32_C(3800), UINT32_C(3810), UINT32_C(3820), UINT32_C(3830),
        UINT32_C(3840), UINT32_C(3850), UINT32_C(3860), UINT32_C(3870)
    };
    static const uint32_t invalid_values[] = {
        UINT32_C(0), UINT32_C(5001), UINT32_MAX
    };
    size_t invalid_index;
    size_t slot;
    uint32_t output = UINT32_C(0xA5A5A5A5);

    E87_ASSERT_TRUE(!e87_battery_filter_full_mv(
        NULL, E87_BATTERY_SAMPLE_COUNT, &output));
    E87_ASSERT_EQ_U32(UINT32_C(0xA5A5A5A5), output);
    E87_ASSERT_TRUE(!e87_battery_filter_full_mv(
        baseline, E87_BATTERY_SAMPLE_COUNT - 1U, &output));
    E87_ASSERT_EQ_U32(UINT32_C(0xA5A5A5A5), output);
    E87_ASSERT_TRUE(!e87_battery_filter_full_mv(
        baseline, E87_BATTERY_SAMPLE_COUNT + 1U, &output));
    E87_ASSERT_EQ_U32(UINT32_C(0xA5A5A5A5), output);
    E87_ASSERT_TRUE(!e87_battery_filter_full_mv(
        baseline, E87_BATTERY_SAMPLE_COUNT, NULL));

    for (invalid_index = 0U;
         invalid_index < sizeof(invalid_values) / sizeof(invalid_values[0]);
         invalid_index += 1U) {
        for (slot = 0U; slot < E87_BATTERY_SAMPLE_COUNT; slot += 1U) {
            uint32_t samples[E87_BATTERY_SAMPLE_COUNT];
            uint32_t before[E87_BATTERY_SAMPLE_COUNT];

            memcpy(samples, baseline, sizeof(samples));
            samples[slot] = invalid_values[invalid_index];
            memcpy(before, samples, sizeof(before));
            output = UINT32_C(0xA5A5A5A5);

            E87_ASSERT_TRUE(!e87_battery_filter_full_mv(
                samples, E87_BATTERY_SAMPLE_COUNT, &output));
            E87_ASSERT_TRUE(bytes_equal(samples, before, sizeof(samples)));
            E87_ASSERT_EQ_U32(UINT32_C(0xA5A5A5A5), output);
        }
    }
}


E87_TEST(filter_checks_every_domain_boundary_in_every_slot)
{
    static const struct {
        uint32_t value;
        bool accepted;
    } boundaries[] = {
        {UINT32_C(0), false},
        {UINT32_C(1), true},
        {UINT32_C(5000), true},
        {UINT32_C(5001), false},
        {UINT32_MAX, false}
    };
    size_t boundary_index;
    size_t slot;

    for (boundary_index = 0U;
         boundary_index < sizeof(boundaries) / sizeof(boundaries[0]);
         boundary_index += 1U) {
        for (slot = 0U; slot < E87_BATTERY_SAMPLE_COUNT; slot += 1U) {
            uint32_t samples[E87_BATTERY_SAMPLE_COUNT] = {
                UINT32_C(2500), UINT32_C(2500), UINT32_C(2500),
                UINT32_C(2500), UINT32_C(2500), UINT32_C(2500),
                UINT32_C(2500), UINT32_C(2500)
            };
            uint32_t before[E87_BATTERY_SAMPLE_COUNT];
            uint32_t output = UINT32_C(0xA5A5A5A5);

            samples[slot] = boundaries[boundary_index].value;
            memcpy(before, samples, sizeof(before));
            E87_ASSERT_EQ_U32(
                boundaries[boundary_index].accepted,
                e87_battery_filter_full_mv(
                    samples, E87_BATTERY_SAMPLE_COUNT, &output));
            E87_ASSERT_TRUE(bytes_equal(samples, before, sizeof(samples)));
            if (boundaries[boundary_index].accepted) {
                E87_ASSERT_EQ_U32(UINT32_C(2500), output);
            } else {
                E87_ASSERT_EQ_U32(UINT32_C(0xA5A5A5A5), output);
            }
        }
    }
}


E87_TEST(filter_sorts_trims_duplicates_and_preserves_input)
{
    uint32_t samples[E87_BATTERY_SAMPLE_COUNT] = {
        UINT32_C(100), UINT32_C(300), UINT32_C(200), UINT32_C(200),
        UINT32_C(300), UINT32_C(200), UINT32_C(100), UINT32_C(200)
    };
    uint32_t before[E87_BATTERY_SAMPLE_COUNT];
    uint32_t output = UINT32_C(0);

    memcpy(before, samples, sizeof(before));
    E87_ASSERT_TRUE(e87_battery_filter_full_mv(
        samples, E87_BATTERY_SAMPLE_COUNT, &output));
    E87_ASSERT_EQ_U32(UINT32_C(200), output);
    E87_ASSERT_TRUE(bytes_equal(samples, before, sizeof(samples)));
}


E87_TEST(filter_middle_six_average_truncates)
{
    static const uint32_t samples[E87_BATTERY_SAMPLE_COUNT] = {
        UINT32_C(1), UINT32_C(500), UINT32_C(500), UINT32_C(500),
        UINT32_C(500), UINT32_C(500), UINT32_C(501), UINT32_C(5000)
    };
    uint32_t output = UINT32_C(0);

    E87_ASSERT_TRUE(e87_battery_filter_full_mv(
        samples, E87_BATTERY_SAMPLE_COUNT, &output));
    E87_ASSERT_EQ_U32(UINT32_C(500), output);
}


E87_TEST(filter_maximum_valid_accumulation_does_not_wrap)
{
    static const uint32_t samples[E87_BATTERY_SAMPLE_COUNT] = {
        UINT32_C(5000), UINT32_C(5000), UINT32_C(5000), UINT32_C(5000),
        UINT32_C(5000), UINT32_C(5000), UINT32_C(5000), UINT32_C(5000)
    };
    uint32_t output = UINT32_C(0);

    E87_ASSERT_TRUE(e87_battery_filter_full_mv(
        samples, E87_BATTERY_SAMPLE_COUNT, &output));
    E87_ASSERT_EQ_U32(UINT32_C(5000), output);
}


E87_TEST(percent_rejects_invalid_domain_without_output_mutation)
{
    static const uint32_t invalid_values[] = {
        UINT32_C(0), UINT32_C(5001), UINT32_MAX
    };
    size_t index;

    for (index = 0U;
         index < sizeof(invalid_values) / sizeof(invalid_values[0]);
         index += 1U) {
        uint8_t output = UINT8_C(0xA5);

        E87_ASSERT_TRUE(!e87_battery_percent_from_full_mv(
            invalid_values[index], &output));
        E87_ASSERT_EQ_U32(UINT8_C(0xA5), output);
    }
    E87_ASSERT_TRUE(!e87_battery_percent_from_full_mv(
        UINT32_C(3800), NULL));
}


E87_TEST(percent_matches_every_discharge_knot)
{
    static const uint32_t millivolts[] = {
        UINT32_C(3565), UINT32_C(3625), UINT32_C(3660),
        UINT32_C(3693), UINT32_C(3737), UINT32_C(3797),
        UINT32_C(3866), UINT32_C(3971), UINT32_C(4073),
        UINT32_C(4188), UINT32_C(4280)
    };
    static const uint8_t percentages[] = {
        UINT8_C(1), UINT8_C(10), UINT8_C(20), UINT8_C(30),
        UINT8_C(40), UINT8_C(50), UINT8_C(60), UINT8_C(70),
        UINT8_C(80), UINT8_C(90), UINT8_C(100)
    };
    size_t index;

    for (index = 0U; index < sizeof(millivolts) / sizeof(millivolts[0]);
         index += 1U) {
        uint8_t output = UINT8_C(0);

        E87_ASSERT_TRUE(e87_battery_percent_from_full_mv(
            millivolts[index], &output));
        E87_ASSERT_EQ_U32(percentages[index], output);
    }
}


E87_TEST(percent_clamps_only_inside_canonical_domain)
{
    static const struct {
        uint32_t millivolts;
        uint8_t expected;
    } vectors[] = {
        {UINT32_C(1), UINT8_C(0)},
        {UINT32_C(3564), UINT8_C(0)},
        {UINT32_C(4281), UINT8_C(100)},
        {UINT32_C(5000), UINT8_C(100)}
    };
    size_t index;

    for (index = 0U; index < sizeof(vectors) / sizeof(vectors[0]); index += 1U) {
        uint8_t output = UINT8_C(0xA5);

        E87_ASSERT_TRUE(e87_battery_percent_from_full_mv(
            vectors[index].millivolts, &output));
        E87_ASSERT_EQ_U32(vectors[index].expected, output);
    }
}


E87_TEST(percent_interpolation_uses_positive_integer_truncation)
{
    static const struct {
        uint32_t millivolts;
        uint8_t expected;
    } vectors[] = {
        {UINT32_C(3566), UINT8_C(1)},
        {UINT32_C(3571), UINT8_C(1)},
        {UINT32_C(3572), UINT8_C(2)},
        {UINT32_C(3624), UINT8_C(9)},
        {UINT32_C(3642), UINT8_C(14)},
        {UINT32_C(3659), UINT8_C(19)}
    };
    size_t index;

    for (index = 0U; index < sizeof(vectors) / sizeof(vectors[0]); index += 1U) {
        uint8_t output = UINT8_C(0);

        E87_ASSERT_TRUE(e87_battery_percent_from_full_mv(
            vectors[index].millivolts, &output));
        E87_ASSERT_EQ_U32(vectors[index].expected, output);
    }
}


E87_TEST(percent_is_monotonic_and_bounded_across_valid_domain)
{
    uint8_t previous = UINT8_C(0);
    uint32_t millivolts;

    for (millivolts = E87_BATTERY_FULL_MV_MIN;
         millivolts <= E87_BATTERY_FULL_MV_MAX;
         millivolts += UINT32_C(1)) {
        uint8_t current = UINT8_C(0xA5);

        E87_ASSERT_TRUE(e87_battery_percent_from_full_mv(
            millivolts, &current));
        E87_ASSERT_TRUE(current >= previous);
        E87_ASSERT_TRUE(current <= UINT8_C(100));
        previous = current;
    }
}


static const struct e87_test_case battery_cases[] = {
    E87_TEST_CASE(constants_pin_canonical_full_cell_domain),
    E87_TEST_CASE(quarter_conversion_is_checked_and_output_atomic),
    E87_TEST_CASE(filter_rejects_arguments_without_input_or_output_mutation),
    E87_TEST_CASE(filter_checks_every_domain_boundary_in_every_slot),
    E87_TEST_CASE(filter_sorts_trims_duplicates_and_preserves_input),
    E87_TEST_CASE(filter_middle_six_average_truncates),
    E87_TEST_CASE(filter_maximum_valid_accumulation_does_not_wrap),
    E87_TEST_CASE(percent_rejects_invalid_domain_without_output_mutation),
    E87_TEST_CASE(percent_matches_every_discharge_knot),
    E87_TEST_CASE(percent_clamps_only_inside_canonical_domain),
    E87_TEST_CASE(percent_interpolation_uses_positive_integer_truncation),
    E87_TEST_CASE(percent_is_monotonic_and_bounded_across_valid_domain)
};


const struct e87_test_suite e87_test_suite = {
    "battery",
    battery_cases,
    sizeof(battery_cases) / sizeof(battery_cases[0])
};
