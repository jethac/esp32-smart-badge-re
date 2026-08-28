#ifndef E87_TRANSIENT_RENDERER_H
#define E87_TRANSIENT_RENDERER_H

#include <stddef.h>
#include <stdint.h>

#include "e87/e87_renderer.h"
#include "e87/e87_ui.h"

enum e87_transient_render_result {
    E87_TRANSIENT_RENDER_OK = 0,
    E87_TRANSIENT_RENDER_PANEL_OFF = 1,
    E87_TRANSIENT_RENDER_ERROR_ARGUMENT = 2,
    E87_TRANSIENT_RENDER_ERROR_STRIP = 3,
    E87_TRANSIENT_RENDER_ERROR_CAPACITY = 4,
    E87_TRANSIENT_RENDER_ERROR_MODEL = 5,
    E87_TRANSIENT_RENDER_ERROR_BASE = 6
};

enum e87_transient_render_result
e87_render_transient_strip(const struct e87_render_model *model,
                           uint8_t strip_index,
                           uint16_t *out_pixels,
                           size_t out_pixel_count);

#endif
