#ifndef E87_BATTERY_H
#define E87_BATTERY_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define E87_BATTERY_SAMPLE_COUNT 8u
#define E87_BATTERY_FULL_MV_MIN UINT32_C(1)
#define E87_BATTERY_FULL_MV_MAX UINT32_C(5000)
#define E87_BATTERY_QUARTER_DIVISOR UINT32_C(4)

bool e87_battery_full_mv_from_quarter_mv(uint32_t quarter_mv,
                                         uint32_t *out_full_mv);

bool e87_battery_filter_full_mv(const uint32_t *samples,
                                size_t count,
                                uint32_t *out_full_mv);

bool e87_battery_percent_from_full_mv(uint32_t full_mv,
                                      uint8_t *out_percent);

#endif
