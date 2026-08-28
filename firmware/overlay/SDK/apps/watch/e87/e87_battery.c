#include "e87/e87_battery.h"

#define E87_BATTERY_TRIMMED_SAMPLE_COUNT 6u

struct e87_battery_knot {
    uint32_t millivolts;
    uint8_t percent;
};

static const struct e87_battery_knot discharge_curve[] = {
    {UINT32_C(3565), UINT8_C(1)},
    {UINT32_C(3625), UINT8_C(10)},
    {UINT32_C(3660), UINT8_C(20)},
    {UINT32_C(3693), UINT8_C(30)},
    {UINT32_C(3737), UINT8_C(40)},
    {UINT32_C(3797), UINT8_C(50)},
    {UINT32_C(3866), UINT8_C(60)},
    {UINT32_C(3971), UINT8_C(70)},
    {UINT32_C(4073), UINT8_C(80)},
    {UINT32_C(4188), UINT8_C(90)},
    {UINT32_C(4280), UINT8_C(100)}
};

bool e87_battery_filter_mv(const uint16_t *half_vbat_samples,
                           size_t sample_count,
                           uint32_t *out_stable_mv)
{
    uint32_t sorted[E87_BATTERY_SAMPLE_COUNT];
    uint32_t sum = UINT32_C(0);
    size_t index;

    if (half_vbat_samples == NULL || out_stable_mv == NULL ||
        sample_count != E87_BATTERY_SAMPLE_COUNT) {
        return false;
    }

    for (index = 0U; index < E87_BATTERY_SAMPLE_COUNT; index += 1U) {
        sorted[index] =
            (uint32_t)half_vbat_samples[index] * UINT32_C(2);
    }
    for (index = 1U; index < E87_BATTERY_SAMPLE_COUNT; index += 1U) {
        const uint32_t value = sorted[index];
        size_t position = index;

        while (position > 0U && sorted[position - 1U] > value) {
            sorted[position] = sorted[position - 1U];
            position -= 1U;
        }
        sorted[position] = value;
    }
    for (index = 1U; index <= E87_BATTERY_TRIMMED_SAMPLE_COUNT;
         index += 1U) {
        sum += sorted[index];
    }

    *out_stable_mv = sum / E87_BATTERY_TRIMMED_SAMPLE_COUNT;
    return true;
}

uint8_t e87_battery_percent_from_mv(uint32_t stable_mv)
{
    size_t index;

    if (stable_mv < discharge_curve[0].millivolts) {
        return UINT8_C(0);
    }
    for (index = 1U;
         index < sizeof(discharge_curve) / sizeof(discharge_curve[0]);
         index += 1U) {
        if (stable_mv <= discharge_curve[index].millivolts) {
            const struct e87_battery_knot *lower =
                &discharge_curve[index - 1U];
            const struct e87_battery_knot *upper =
                &discharge_curve[index];
            const uint32_t voltage_offset =
                stable_mv - lower->millivolts;
            const uint32_t voltage_span =
                upper->millivolts - lower->millivolts;
            const uint32_t percent_span =
                (uint32_t)upper->percent - (uint32_t)lower->percent;
            uint32_t percent = (uint32_t)lower->percent +
                voltage_offset * percent_span / voltage_span;

            if (percent > UINT32_C(100)) {
                percent = UINT32_C(100);
            }
            return (uint8_t)percent;
        }
    }
    return UINT8_C(100);
}
