#ifndef E87_ASSETS_H
#define E87_ASSETS_H

#include <stdint.h>

#define E87_RING_ENDPOINT_COUNT 101u

struct e87_alpha_asset {
    uint16_t width;
    uint16_t height;
    uint32_t byte_count;
    const uint8_t *alpha;
};

extern const struct e87_alpha_asset e87_asset_devin;
extern const struct e87_alpha_asset e87_asset_today;
extern const struct e87_alpha_asset e87_asset_date_range;
extern const struct e87_alpha_asset e87_asset_credit_1727;
extern const int32_t e87_ring_cos_q16[E87_RING_ENDPOINT_COUNT];
extern const int32_t e87_ring_sin_q16[E87_RING_ENDPOINT_COUNT];

#endif
