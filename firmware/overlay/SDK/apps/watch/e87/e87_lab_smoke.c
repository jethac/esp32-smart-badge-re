#include "e87/e87_lab_smoke.h"

#include <stddef.h>
#include <string.h>

#include "e87/e87_lcd_stream.h"
#include "e87/e87_transient_renderer.h"

static enum e87_render_result render_model_strip(
    void *context,
    uint8_t strip_index,
    uint16_t *out_pixels,
    size_t out_pixel_count)
{
    const struct e87_render_model *model = context;

    return e87_render_transient_strip(model,
                                      strip_index,
                                      out_pixels,
                                      out_pixel_count) ==
                   E87_TRANSIENT_RENDER_OK
               ? E87_RENDER_OK
               : E87_RENDER_ERROR_ARGUMENT;
}

static enum e87_lab_smoke_result present_model(
    const struct e87_panel_io *io,
    const struct e87_render_model *model)
{
    return e87_lcd_stream_frame_serial(
               io, render_model_strip, (void *)(uintptr_t)model) ==
                   E87_LCD_STREAM_OK
               ? E87_LAB_SMOKE_OK
               : E87_LAB_SMOKE_ERROR_RENDER;
}

enum e87_lab_smoke_result
e87_lab_smoke_start(struct e87_lab_smoke *smoke,
                    const struct e87_panel_io *io,
                    uint32_t now_ms)
{
    struct e87_lab_smoke initialized;
    struct e87_render_model pair_me;

    if (smoke == NULL || io == NULL || io->backlight_set == NULL) {
        return E87_LAB_SMOKE_ERROR_ARGUMENT;
    }
    memset(&initialized, 0, sizeof(initialized));
    memset(&pair_me, 0, sizeof(pair_me));
    pair_me.screen = E87_UI_SCREEN_PAIR_ME_NOW;

    if (e87_panel_jd9855_init_dark(io) != E87_PANEL_OK) {
        return E87_LAB_SMOKE_ERROR_PANEL;
    }
    if (present_model(io, &pair_me) != E87_LAB_SMOKE_OK) {
        io->backlight_set(io->context, false);
        return E87_LAB_SMOKE_ERROR_RENDER;
    }
    io->backlight_set(io->context, true);

    initialized.private_io = io;
    initialized.private_started_ms = now_ms;
    initialized.private_started = true;
    *smoke = initialized;
    return E87_LAB_SMOKE_OK;
}

enum e87_lab_smoke_result
e87_lab_smoke_step(struct e87_lab_smoke *smoke, uint32_t now_ms)
{
    struct e87_render_model face;

    if (smoke == NULL || !smoke->private_started ||
        smoke->private_io == NULL ||
        smoke->private_io->backlight_set == NULL) {
        return E87_LAB_SMOKE_ERROR_ARGUMENT;
    }
    if (smoke->private_face_presented ||
        (uint32_t)(now_ms - smoke->private_started_ms) < UINT32_C(3000)) {
        return E87_LAB_SMOKE_NO_CHANGE;
    }

    memset(&face, 0, sizeof(face));
    face.screen = E87_UI_SCREEN_FACE;
    face.metrics.day = UINT8_C(67);
    face.metrics.week = UINT8_C(42);
    face.metrics.credit_cents = E87_STATE_FIXED_CREDIT_CENTS;
    if (present_model(smoke->private_io, &face) != E87_LAB_SMOKE_OK) {
        smoke->private_io->backlight_set(
            smoke->private_io->context, false);
        return E87_LAB_SMOKE_ERROR_RENDER;
    }
    smoke->private_face_presented = true;
    return E87_LAB_SMOKE_OK;
}
