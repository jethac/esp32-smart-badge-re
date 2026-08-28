#ifndef E87_TRANSIENT_ASSETS_H
#define E87_TRANSIENT_ASSETS_H

#include <stdint.h>

#include "e87_assets.h"

#define E87_TRANSIENT_GLYPH_COUNT 32u

struct e87_bitmap_glyph {
    uint32_t alpha_offset;
    uint16_t width;
    uint16_t height;
    int16_t bearing_x;
    int16_t bearing_y;
    uint16_t advance_q3;
    uint8_t ascii;
    uint8_t reserved;
};

extern const uint8_t e87_transient_glyph_alpha[];
extern const uint32_t e87_transient_glyph_alpha_byte_count;
extern const struct e87_bitmap_glyph
    e87_transient_glyphs[E87_TRANSIENT_GLYPH_COUNT];
extern const struct e87_alpha_asset e87_transient_asset_bolt;

#endif
