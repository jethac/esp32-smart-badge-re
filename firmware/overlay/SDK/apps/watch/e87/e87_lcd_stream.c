#include "e87/e87_lcd_stream.h"

#include <stddef.h>
#include <stdint.h>

#include "e87/e87_types.h"

#if defined(__GNUC__)
#define E87_LCD_BUFFER_ATTRIBUTES \
    __attribute__((aligned(4), section(".e87_lcd_buffer")))
#else
#define E87_LCD_BUFFER_ATTRIBUTES
#endif

/*
 * One application-owned transfer buffer.  The target linker must map this
 * section into the separately proven 0x6000 LCD tail reservation.
 */
static uint16_t
    e87_lcd_strip_buffer[E87_STRIP_BUFFER_BYTES /
                         E87_RGB565_BYTES_PER_PIXEL]
    E87_LCD_BUFFER_ATTRIBUTES;

_Static_assert(sizeof(e87_lcd_strip_buffer) == E87_STRIP_BUFFER_BYTES,
               "serial transfer buffer must occupy exactly 0x5460 bytes");

static bool e87_has_stream_io(const struct e87_panel_io *io)
{
    return io != NULL &&
           io->set_draw_area != NULL &&
           io->draw != NULL &&
           io->wait_busy != NULL;
}

enum e87_lcd_stream_result
e87_lcd_solid_color_ladder(const struct e87_panel_io *io)
{
    static const uint32_t colors[] = {
        UINT32_C(0x000000),
        UINT32_C(0xFFFFFF),
        UINT32_C(0xFF0000),
        UINT32_C(0x00FF00),
        UINT32_C(0x0000FF)
    };
    size_t index;

    if (io == NULL || io->clear == NULL || io->wait_busy == NULL) {
        return E87_LCD_STREAM_ERROR_ARGUMENT;
    }
    for (index = 0U; index < sizeof(colors) / sizeof(colors[0]); ++index) {
        io->clear(io->context,
                  colors[index],
                  UINT16_C(0),
                  (uint16_t)(E87_DISPLAY_WIDTH - 1),
                  UINT16_C(0),
                  (uint16_t)(E87_DISPLAY_HEIGHT - 1));
        io->wait_busy(io->context);
    }
    return E87_LCD_STREAM_OK;
}

enum e87_lcd_stream_result
e87_lcd_stream_frame_serial(const struct e87_panel_io *io,
                            e87_lcd_render_strip_fn render,
                            void *render_context)
{
    uint8_t strip;

    if (!e87_has_stream_io(io) || render == NULL) {
        return E87_LCD_STREAM_ERROR_ARGUMENT;
    }

    for (strip = UINT8_C(0);
         strip < (uint8_t)E87_STRIP_COUNT;
         strip = (uint8_t)(strip + UINT8_C(1))) {
        const uint16_t y_start =
            (uint16_t)((uint16_t)strip * (uint16_t)E87_STRIP_ROWS);
        const uint16_t y_end =
            (uint16_t)(y_start + (uint16_t)E87_STRIP_ROWS - UINT16_C(1));
        enum e87_render_result render_result;

        render_result = render(
            render_context,
            strip,
            e87_lcd_strip_buffer,
            sizeof(e87_lcd_strip_buffer) / sizeof(e87_lcd_strip_buffer[0]));
        if (render_result != E87_RENDER_OK) {
            return E87_LCD_STREAM_ERROR_RENDER;
        }

        io->set_draw_area(io->context,
                          UINT16_C(0),
                          (uint16_t)(E87_DISPLAY_WIDTH - 1),
                          y_start,
                          y_end);
        io->draw(io->context,
                 e87_lcd_strip_buffer,
                 UINT16_C(0),
                 (uint16_t)(E87_DISPLAY_WIDTH - 1),
                 y_start,
                 y_end);
        /*
         * lcd_draw is nonblocking.  Waiting immediately makes this first
         * adapter deliberately serial and proves completion before the sole
         * buffer can be rendered into again.
         */
        io->wait_busy(io->context);
    }
    return E87_LCD_STREAM_OK;
}

static enum e87_render_result
e87_render_normal_adapter(void *context,
                          uint8_t strip_index,
                          uint16_t *out_pixels,
                          size_t out_pixel_count)
{
    const struct e87_metrics *metrics = context;

    return e87_render_normal_face_strip(metrics,
                                        strip_index,
                                        out_pixels,
                                        out_pixel_count);
}

enum e87_lcd_stream_result
e87_lcd_stream_normal_face_serial(const struct e87_panel_io *io,
                                  const struct e87_metrics *metrics)
{
    if (metrics == NULL) {
        return E87_LCD_STREAM_ERROR_ARGUMENT;
    }
    return e87_lcd_stream_frame_serial(io,
                                       e87_render_normal_adapter,
                                       (void *)metrics);
}
