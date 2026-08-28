#ifndef E87_BATTERY_SAMPLER_H
#define E87_BATTERY_SAMPLER_H

#include <stdbool.h>
#include <stdint.h>

typedef uint32_t (*e87_battery_read_quarter_mv_fn)(void *context);

struct e87_battery_sampler_port {
    void *context;
    e87_battery_read_quarter_mv_fn read_quarter_mv;
};

bool e87_battery_sampler_sample_full_mv(
    const struct e87_battery_sampler_port *port,
    uint32_t *out_full_mv);

#endif
