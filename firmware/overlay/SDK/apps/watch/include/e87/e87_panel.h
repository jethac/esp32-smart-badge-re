#ifndef E87_PANEL_H
#define E87_PANEL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "e87/e87_types.h"

#define E87_JD9855_INIT_PROGRAM_BYTES 657u
#define E87_JD9855_INIT_RECORDS 51u

enum e87_panel_result {
    E87_PANEL_OK = 0,
    E87_PANEL_ERROR_ARGUMENT = 1,
    E87_PANEL_ERROR_DBI_INIT = 2,
    E87_PANEL_ERROR_INIT_PROGRAM = 3
};

enum e87_panel_clock_action {
    E87_PANEL_CLOCK_RELEASE = 0,
    E87_PANEL_CLOCK_ACQUIRE = 1
};

/*
 * The recovered descriptor metadata and the application transfer allocation
 * are intentionally separate.  A descriptor count of two is evidence from
 * model 1552; this serial adapter owns exactly one 0x5460 transfer buffer.
 */
struct e87_jd9855_profile {
    uint16_t width;
    uint16_t height;
    uint16_t input_width;
    uint16_t input_height;
    uint8_t input_format_rgb565;
    uint8_t output_format_rgb565;
    uint8_t lcd_type_spi;
    uint8_t qspi_mode;
    uint8_t pixel_type;
    uint8_t spi_unidirectional;
    uint8_t clock_idle_low;
    uint8_t fps;
    uint8_t row_alignment;
    uint8_t column_alignment;
    uint16_t radius;
    uint8_t recovered_descriptor_buffer_count;
    uint16_t recovered_descriptor_buffer_size;
    uint8_t application_transfer_buffer_count;
    uint8_t reset_pa_pin;
    uint8_t te_pa_pin;
    uint8_t cs_pa_pin;
    uint8_t clock_pa_pin;
    uint8_t data0_pa_pin;
    uint8_t data1_pa_pin;
    uint8_t data2_pa_pin;
    uint8_t data3_pa_pin;
    uint8_t read_pa_pin;
    uint8_t backlight_selector;
    bool has_dc;
    bool has_panel_power_hook;
    bool orientation_confirmed;
    bool model_1542_inferred;
};

struct e87_panel_io {
    void *context;
    int (*dbi_init)(void *context,
                    const struct e87_jd9855_profile *profile);
    void (*set_align)(void *context, uint8_t row, uint8_t column);
    void (*reset_write)(void *context, bool high);
    void (*delay_ms)(void *context, uint16_t milliseconds);
    void (*write_command)(void *context,
                          uint8_t command,
                          const uint8_t *parameters,
                          size_t parameter_count);
    void (*backlight_set)(void *context, bool on);
    void (*wait_busy)(void *context);
    void (*clear)(void *context,
                  uint32_t rgb888,
                  uint16_t x_start,
                  uint16_t x_end,
                  uint16_t y_start,
                  uint16_t y_end);
    void (*set_draw_area)(void *context,
                          uint16_t x_start,
                          uint16_t x_end,
                          uint16_t y_start,
                          uint16_t y_end);
    void (*draw)(void *context,
                 const uint16_t *pixels,
                 uint16_t x_start,
                 uint16_t x_end,
                 uint16_t y_start,
                 uint16_t y_end);
    void (*clock_set)(void *context,
                      enum e87_panel_clock_action action);
};

extern const struct e87_jd9855_profile e87_jd9855_profile;
extern const uint8_t
    e87_jd9855_init_program[E87_JD9855_INIT_PROGRAM_BYTES];

enum e87_panel_result
e87_panel_jd9855_replay(const struct e87_panel_io *io,
                        const uint8_t *program,
                        size_t program_size);

enum e87_panel_result
e87_panel_jd9855_reset_and_replay(const struct e87_panel_io *io);

enum e87_panel_result
e87_panel_jd9855_init_dark(const struct e87_panel_io *io);

#if !defined(E87_HOST_TEST)
const struct e87_panel_io *e87_panel_jd9855_sdk_io(void);
#endif

#endif
