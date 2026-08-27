#ifndef E87_RENDERER_H
#define E87_RENDERER_H

#include <stddef.h>
#include <stdint.h>

#include "e87/e87_state.h"
#include "e87/e87_types.h"

#define E87_RENDER_CREDIT_TEXT_BYTES 7u

enum e87_render_result {
    E87_RENDER_OK = 0,
    E87_RENDER_ERROR_ARGUMENT = 1,
    E87_RENDER_ERROR_STRIP = 2,
    E87_RENDER_ERROR_CAPACITY = 3,
    E87_RENDER_ERROR_METRICS = 4
};

enum e87_render_result
e87_render_credit_text(uint32_t credit_cents,
                       char *out,
                       size_t out_size);

enum e87_render_result
e87_render_normal_face_strip(const struct e87_metrics *metrics,
                             uint8_t strip_index,
                             uint16_t *out_pixels,
                             size_t out_pixel_count);

#endif
