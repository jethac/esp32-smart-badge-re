#include "test_support.h"
#include "e87/e87_battery.h"
#include "e87/e87_battery_sampler.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>


struct sampler_fake {
    uint32_t samples[E87_BATTERY_SAMPLE_COUNT];
    size_t read_count;
};


static uint32_t fake_read_quarter_mv(void *context)
{
    struct sampler_fake *fake = context;
    const size_t index = fake->read_count;

    fake->read_count += 1U;
    if (index >= E87_BATTERY_SAMPLE_COUNT) {
        return UINT32_MAX;
    }
    return fake->samples[index];
}


E87_TEST(valid_update_reads_and_converts_exactly_eight_distinct_epochs)
{
    struct sampler_fake fake = {
        {
            UINT32_C(900), UINT32_C(925), UINT32_C(950), UINT32_C(975),
            UINT32_C(1000), UINT32_C(1025), UINT32_C(1050), UINT32_C(1075)
        },
        0U
    };
    const struct e87_battery_sampler_port port = {
        &fake,
        fake_read_quarter_mv
    };
    struct e87_battery_sampler_port before;
    uint32_t output = UINT32_C(0xA5A5A5A5);

    memcpy(&before, &port, sizeof(before));
    E87_ASSERT_TRUE(e87_battery_sampler_sample_full_mv(&port, &output));
    E87_ASSERT_EQ_U32(E87_BATTERY_SAMPLE_COUNT, fake.read_count);
    E87_ASSERT_EQ_U32(UINT32_C(3950), output);
    E87_ASSERT_TRUE(memcmp(&port, &before, sizeof(port)) == 0);
}


E87_TEST(each_invalid_epoch_stops_before_filter_and_preserves_output)
{
    static const uint32_t invalid_values[] = {
        UINT32_C(0), UINT32_C(1251),
        UINT32_MAX / UINT32_C(4),
        UINT32_MAX / UINT32_C(4) + UINT32_C(1),
        UINT32_MAX
    };
    size_t invalid_index;
    size_t slot;

    for (invalid_index = 0U;
         invalid_index < sizeof(invalid_values) / sizeof(invalid_values[0]);
         invalid_index += 1U) {
        for (slot = 0U; slot < E87_BATTERY_SAMPLE_COUNT; slot += 1U) {
            struct sampler_fake fake;
            struct e87_battery_sampler_port port;
            uint32_t output = UINT32_C(0xA5A5A5A5);
            size_t index;

            for (index = 0U; index < E87_BATTERY_SAMPLE_COUNT; index += 1U) {
                fake.samples[index] = UINT32_C(1000);
            }
            fake.samples[slot] = invalid_values[invalid_index];
            fake.read_count = 0U;
            port.context = &fake;
            port.read_quarter_mv = fake_read_quarter_mv;

            E87_ASSERT_TRUE(!e87_battery_sampler_sample_full_mv(&port, &output));
            E87_ASSERT_EQ_U32(slot + 1U, fake.read_count);
            E87_ASSERT_EQ_U32(UINT32_C(0xA5A5A5A5), output);
        }
    }
}


E87_TEST(invalid_arguments_do_not_read_or_mutate_output)
{
    struct sampler_fake fake = {
        {
            UINT32_C(1000), UINT32_C(1000), UINT32_C(1000), UINT32_C(1000),
            UINT32_C(1000), UINT32_C(1000), UINT32_C(1000), UINT32_C(1000)
        },
        0U
    };
    struct e87_battery_sampler_port port = {
        &fake,
        fake_read_quarter_mv
    };
    uint32_t output = UINT32_C(0xA5A5A5A5);

    E87_ASSERT_TRUE(!e87_battery_sampler_sample_full_mv(NULL, &output));
    E87_ASSERT_EQ_U32(UINT32_C(0), fake.read_count);
    E87_ASSERT_EQ_U32(UINT32_C(0xA5A5A5A5), output);

    port.read_quarter_mv = NULL;
    E87_ASSERT_TRUE(!e87_battery_sampler_sample_full_mv(&port, &output));
    E87_ASSERT_EQ_U32(UINT32_C(0), fake.read_count);
    E87_ASSERT_EQ_U32(UINT32_C(0xA5A5A5A5), output);

    port.read_quarter_mv = fake_read_quarter_mv;
    E87_ASSERT_TRUE(!e87_battery_sampler_sample_full_mv(&port, NULL));
    E87_ASSERT_EQ_U32(UINT32_C(0), fake.read_count);
}


static const struct e87_test_case battery_sampler_cases[] = {
    E87_TEST_CASE(valid_update_reads_and_converts_exactly_eight_distinct_epochs),
    E87_TEST_CASE(each_invalid_epoch_stops_before_filter_and_preserves_output),
    E87_TEST_CASE(invalid_arguments_do_not_read_or_mutate_output)
};


const struct e87_test_suite e87_test_suite = {
    "battery-sampler",
    battery_sampler_cases,
    sizeof(battery_sampler_cases) / sizeof(battery_sampler_cases[0])
};
