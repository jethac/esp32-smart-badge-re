#include "e87/e87_battery_sampler.h"

#include "e87/e87_battery.h"

#include <stddef.h>

bool e87_battery_sampler_sample_full_mv(
    const struct e87_battery_sampler_port *port,
    uint32_t *out_full_mv)
{
    uint32_t full_mv_samples[E87_BATTERY_SAMPLE_COUNT];
    uint32_t filtered_full_mv;
    size_t index;

    if (port == NULL || port->read_quarter_mv == NULL ||
        out_full_mv == NULL) {
        return false;
    }
    for (index = 0U; index < E87_BATTERY_SAMPLE_COUNT; index += 1U) {
        const uint32_t quarter_mv = port->read_quarter_mv(port->context);

        if (!e87_battery_full_mv_from_quarter_mv(
                quarter_mv, &full_mv_samples[index])) {
            return false;
        }
    }
    if (!e87_battery_filter_full_mv(
            full_mv_samples, E87_BATTERY_SAMPLE_COUNT, &filtered_full_mv)) {
        return false;
    }
    *out_full_mv = filtered_full_mv;
    return true;
}
