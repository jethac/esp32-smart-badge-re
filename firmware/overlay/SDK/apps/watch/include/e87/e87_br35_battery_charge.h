#ifndef E87_BR35_BATTERY_CHARGE_H
#define E87_BR35_BATTERY_CHARGE_H

#include <stdbool.h>
#include <stdint.h>

struct charge_platform_data;
struct e87_charge_adapter;

bool e87_br35_battery_init(void);
bool e87_br35_battery_sample_full_mv(uint32_t *out_full_mv);

bool e87_br35_charge_prepare(struct e87_charge_adapter *adapter);
bool e87_br35_charge_hw_init(
    const struct charge_platform_data *platform_data);

#endif
