#ifndef E87_LCD_STREAM_H
#define E87_LCD_STREAM_H

#include <stddef.h>
#include <stdint.h>

#include "e87/e87_panel.h"
#include "e87/e87_renderer.h"

enum e87_lcd_stream_result {
    E87_LCD_STREAM_OK = 0,
    E87_LCD_STREAM_ERROR_ARGUMENT = 1,
    E87_LCD_STREAM_ERROR_RENDER = 2
};

typedef enum e87_render_result
    (*e87_lcd_render_strip_fn)(void *context,
                               uint8_t strip_index,
                               uint16_t *out_pixels,
                               size_t out_pixel_count);

enum e87_lcd_stream_result
e87_lcd_solid_color_ladder(const struct e87_panel_io *io);

enum e87_lcd_stream_result
e87_lcd_stream_frame_serial(const struct e87_panel_io *io,
                            e87_lcd_render_strip_fn render,
                            void *render_context);

enum e87_lcd_stream_result
e87_lcd_stream_normal_face_serial(const struct e87_panel_io *io,
                                  const struct e87_metrics *metrics);

#endif
