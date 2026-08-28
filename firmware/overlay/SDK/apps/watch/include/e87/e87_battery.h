#ifndef E87_BATTERY_H
#define E87_BATTERY_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define E87_BATTERY_SAMPLE_COUNT 8u

bool e87_battery_filter_mv(const uint16_t *half_vbat_samples,
                           size_t sample_count,
                           uint32_t *out_stable_mv);

uint8_t e87_battery_percent_from_mv(uint32_t stable_mv);

#endif
