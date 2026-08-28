#include "test_support.h"
#include "e87/e87_battery.h"

#include <stddef.h>
#include <stdint.h>
#include <string.h>

static bool bytes_equal(const void *left, const void *right, size_t length)
{
    return memcmp(left, right, length) == 0;
}

E87_TEST(filter_rejects_invalid_arguments_without_mutation)
{
    static const uint16_t samples[E87_BATTERY_SAMPLE_COUNT] = {
        UINT16_C(1900), UINT16_C(1910), UINT16_C(1920), UINT16_C(1930),
        UINT16_C(1940), UINT16_C(1950), UINT16_C(1960), UINT16_C(1970)
    };
    uint32_t output = UINT32_C(0xA5A5A5A5);

    E87_ASSERT_TRUE(!e87_battery_filter_mv(
        NULL, E87_BATTERY_SAMPLE_COUNT, &output));
    E87_ASSERT_EQ_U32(UINT32_C(0xA5A5A5A5), output);
    E87_ASSERT_TRUE(!e87_battery_filter_mv(
        samples, E87_BATTERY_SAMPLE_COUNT - 1U, &output));
    E87_ASSERT_EQ_U32(UINT32_C(0xA5A5A5A5), output);
    E87_ASSERT_TRUE(!e87_battery_filter_mv(
        samples, E87_BATTERY_SAMPLE_COUNT + 1U, &output));
    E87_ASSERT_EQ_U32(UINT32_C(0xA5A5A5A5), output);
    E87_ASSERT_TRUE(!e87_battery_filter_mv(
        samples, E87_BATTERY_SAMPLE_COUNT, NULL));
    E87_ASSERT_EQ_U32(UINT32_C(0xA5A5A5A5), output);
}

E87_TEST(filter_doubles_sorts_trims_and_preserves_input)
{
    uint16_t samples[E87_BATTERY_SAMPLE_COUNT] = {
        UINT16_C(1900), UINT16_C(2000), UINT16_C(1990), UINT16_C(2010),
        UINT16_C(1980), UINT16_MAX, UINT16_C(0), UINT16_C(1970)
    };
    uint16_t before[E87_BATTERY_SAMPLE_COUNT];
    uint32_t output = UINT32_MAX;

    memcpy(before, samples, sizeof(before));
    E87_ASSERT_TRUE(e87_battery_filter_mv(
        samples, E87_BATTERY_SAMPLE_COUNT, &output));
    E87_ASSERT_EQ_U32(UINT32_C(3950), output);
    E87_ASSERT_TRUE(bytes_equal(samples, before, sizeof(samples)));
}

E87_TEST(filter_discards_exactly_one_minimum_and_one_maximum)
{
    static const uint16_t samples[E87_BATTERY_SAMPLE_COUNT] = {
        UINT16_C(100), UINT16_C(100), UINT16_C(200), UINT16_C(200),
        UINT16_C(200), UINT16_C(200), UINT16_C(300), UINT16_C(300)
    };
    uint32_t output = UINT32_C(0);

    E87_ASSERT_TRUE(e87_battery_filter_mv(
        samples, E87_BATTERY_SAMPLE_COUNT, &output));
    E87_ASSERT_EQ_U32(UINT32_C(400), output);
}

E87_TEST(filter_average_uses_integer_truncation)
{
    static const uint16_t samples[E87_BATTERY_SAMPLE_COUNT] = {
        UINT16_C(0), UINT16_C(500), UINT16_C(500), UINT16_C(500),
        UINT16_C(500), UINT16_C(500), UINT16_C(501), UINT16_MAX
    };
    uint32_t output = UINT32_C(0);

    E87_ASSERT_TRUE(e87_battery_filter_mv(
        samples, E87_BATTERY_SAMPLE_COUNT, &output));
    E87_ASSERT_EQ_U32(UINT32_C(1000), output);
}

E87_TEST(filter_maximum_input_uses_wide_arithmetic_without_wrap)
{
    static const uint16_t samples[E87_BATTERY_SAMPLE_COUNT] = {
        UINT16_MAX, UINT16_MAX, UINT16_MAX, UINT16_MAX,
        UINT16_MAX, UINT16_MAX, UINT16_MAX, UINT16_MAX
    };
    uint32_t output = UINT32_C(0);

    E87_ASSERT_TRUE(e87_battery_filter_mv(
        samples, E87_BATTERY_SAMPLE_COUNT, &output));
    E87_ASSERT_EQ_U32(UINT32_C(131070), output);
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
        E87_ASSERT_EQ_U32(
            percentages[index],
            e87_battery_percent_from_mv(millivolts[index]));
    }
}

E87_TEST(percent_clamps_below_and_above_table)
{
    E87_ASSERT_EQ_U32(UINT8_C(0),
                      e87_battery_percent_from_mv(UINT32_C(0)));
    E87_ASSERT_EQ_U32(UINT8_C(0),
                      e87_battery_percent_from_mv(UINT32_C(3564)));
    E87_ASSERT_EQ_U32(UINT8_C(100),
                      e87_battery_percent_from_mv(UINT32_C(4281)));
    E87_ASSERT_EQ_U32(UINT8_C(100),
                      e87_battery_percent_from_mv(UINT32_MAX));
}

E87_TEST(percent_interpolation_uses_positive_integer_truncation)
{
    E87_ASSERT_EQ_U32(UINT8_C(1),
                      e87_battery_percent_from_mv(UINT32_C(3566)));
    E87_ASSERT_EQ_U32(UINT8_C(1),
                      e87_battery_percent_from_mv(UINT32_C(3571)));
    E87_ASSERT_EQ_U32(UINT8_C(2),
                      e87_battery_percent_from_mv(UINT32_C(3572)));
    E87_ASSERT_EQ_U32(UINT8_C(9),
                      e87_battery_percent_from_mv(UINT32_C(3624)));
    E87_ASSERT_EQ_U32(UINT8_C(14),
                      e87_battery_percent_from_mv(UINT32_C(3642)));
    E87_ASSERT_EQ_U32(UINT8_C(19),
                      e87_battery_percent_from_mv(UINT32_C(3659)));
}

E87_TEST(percent_is_monotonic_and_bounded)
{
    uint8_t previous = UINT8_C(0);
    uint32_t millivolts;

    for (millivolts = UINT32_C(0); millivolts <= UINT32_C(5000);
         millivolts += UINT32_C(1)) {
        const uint8_t current = e87_battery_percent_from_mv(millivolts);

        E87_ASSERT_TRUE(current >= previous);
        E87_ASSERT_TRUE(current <= UINT8_C(100));
        previous = current;
    }
}

static const struct e87_test_case battery_cases[] = {
    E87_TEST_CASE(filter_rejects_invalid_arguments_without_mutation),
    E87_TEST_CASE(filter_doubles_sorts_trims_and_preserves_input),
    E87_TEST_CASE(filter_discards_exactly_one_minimum_and_one_maximum),
    E87_TEST_CASE(filter_average_uses_integer_truncation),
    E87_TEST_CASE(filter_maximum_input_uses_wide_arithmetic_without_wrap),
    E87_TEST_CASE(percent_matches_every_discharge_knot),
    E87_TEST_CASE(percent_clamps_below_and_above_table),
    E87_TEST_CASE(percent_interpolation_uses_positive_integer_truncation),
    E87_TEST_CASE(percent_is_monotonic_and_bounded)
};

const struct e87_test_suite e87_test_suite = {
    "battery",
    battery_cases,
    sizeof(battery_cases) / sizeof(battery_cases[0])
};
