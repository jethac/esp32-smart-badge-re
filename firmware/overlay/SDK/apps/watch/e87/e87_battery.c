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

bool e87_battery_full_mv_from_quarter_mv(uint32_t quarter_mv,
                                         uint32_t *out_full_mv)
{
    uint32_t full_mv;

    if (out_full_mv == NULL || quarter_mv < E87_BATTERY_FULL_MV_MIN ||
        quarter_mv > E87_BATTERY_FULL_MV_MAX /
            E87_BATTERY_QUARTER_DIVISOR) {
        return false;
    }

    full_mv = quarter_mv * E87_BATTERY_QUARTER_DIVISOR;
    if (full_mv < E87_BATTERY_FULL_MV_MIN ||
        full_mv > E87_BATTERY_FULL_MV_MAX) {
        return false;
    }
    *out_full_mv = full_mv;
    return true;
}

bool e87_battery_filter_full_mv(const uint32_t *samples,
                                size_t count,
                                uint32_t *out_full_mv)
{
    uint32_t sorted[E87_BATTERY_SAMPLE_COUNT];
    uint32_t sum = UINT32_C(0);
    uint32_t average;
    size_t index;

    if (samples == NULL || out_full_mv == NULL ||
        count != E87_BATTERY_SAMPLE_COUNT) {
        return false;
    }

    for (index = 0U; index < E87_BATTERY_SAMPLE_COUNT; index += 1U) {
        if (samples[index] < E87_BATTERY_FULL_MV_MIN ||
            samples[index] > E87_BATTERY_FULL_MV_MAX) {
            return false;
        }
    }
    for (index = 0U; index < E87_BATTERY_SAMPLE_COUNT; index += 1U) {
        sorted[index] = samples[index];
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
        if (sum > UINT32_MAX - sorted[index]) {
            return false;
        }
        sum += sorted[index];
    }

    average = sum / E87_BATTERY_TRIMMED_SAMPLE_COUNT;
    *out_full_mv = average;
    return true;
}

bool e87_battery_percent_from_full_mv(uint32_t full_mv,
                                      uint8_t *out_percent)
{
    uint8_t percent;
    size_t index;

    if (out_percent == NULL || full_mv < E87_BATTERY_FULL_MV_MIN ||
        full_mv > E87_BATTERY_FULL_MV_MAX) {
        return false;
    }

    if (full_mv < discharge_curve[0].millivolts) {
        percent = UINT8_C(0);
        *out_percent = percent;
        return true;
    }
    for (index = 1U;
         index < sizeof(discharge_curve) / sizeof(discharge_curve[0]);
         index += 1U) {
        if (full_mv <= discharge_curve[index].millivolts) {
            const struct e87_battery_knot *lower =
                &discharge_curve[index - 1U];
            const struct e87_battery_knot *upper =
                &discharge_curve[index];
            const uint32_t voltage_offset =
                full_mv - lower->millivolts;
            const uint32_t voltage_span =
                upper->millivolts - lower->millivolts;
            const uint32_t percent_span =
                (uint32_t)upper->percent - (uint32_t)lower->percent;
            percent = (uint8_t)((uint32_t)lower->percent +
                voltage_offset * percent_span / voltage_span);

            if (percent > UINT8_C(100)) {
                percent = UINT8_C(100);
            }
            *out_percent = percent;
            return true;
        }
    }
    percent = UINT8_C(100);
    *out_percent = percent;
    return true;
}
