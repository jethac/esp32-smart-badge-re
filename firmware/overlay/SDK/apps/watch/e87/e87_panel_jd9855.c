#include <stdint.h>

#if !defined(E87_HOST_TEST)
#include <asm/power/power_gate.h>
#include <dbi.h>
#include <gpio.h>
#include <system/os/os_compat.h>
#endif

#include "e87/e87_panel.h"

#include <stddef.h>
#include <string.h>

enum {
    E87_INIT_MARKER_BYTES = 4,
    E87_DELAY_RECORD_BYTES = 5,
    E87_RESET_HIGH_FIRST_MS = 10,
    E87_RESET_LOW_MS = 10,
    E87_RESET_HIGH_FINAL_MS = 100
};

static const uint8_t e87_init_start[E87_INIT_MARKER_BYTES] = {
    UINT8_C(0x12), UINT8_C(0x34), UINT8_C(0x56), UINT8_C(0x78)
};
static const uint8_t e87_init_end[E87_INIT_MARKER_BYTES] = {
    UINT8_C(0x87), UINT8_C(0x65), UINT8_C(0x43), UINT8_C(0x21)
};
static const uint8_t e87_delay_prefix[E87_INIT_MARKER_BYTES] = {
    UINT8_C(0xFF), UINT8_C(0x5A), UINT8_C(0xA5), UINT8_C(0xFF)
};

const struct e87_jd9855_profile e87_jd9855_profile = {
    .width = 360U,
    .height = 360U,
    .input_width = 360U,
    .input_height = 360U,
    .input_format_rgb565 = 1U,
    .output_format_rgb565 = 1U,
    .lcd_type_spi = 0U,
    .qspi_mode = 0x21U,
    .pixel_type = 0x21U,
    .spi_unidirectional = 0U,
    .clock_idle_low = 0U,
    .fps = 90U,
    .row_alignment = 2U,
    .column_alignment = 2U,
    .radius = 180U,
    .recovered_descriptor_buffer_count = 2U,
    .recovered_descriptor_buffer_size = 0x5460U,
    .application_transfer_buffer_count = 1U,
    .reset_pa_pin = 5U,
    .te_pa_pin = 6U,
    .cs_pa_pin = 7U,
    .clock_pa_pin = 12U,
    .data0_pa_pin = 8U,
    .data1_pa_pin = 9U,
    .data2_pa_pin = 10U,
    .data3_pa_pin = 11U,
    .read_pa_pin = 8U,
    .backlight_selector = 0xE7U,
    .has_dc = false,
    .has_panel_power_hook = false,
    .orientation_confirmed = false,
    .model_1542_inferred = true,
};

const uint8_t
e87_jd9855_init_program[E87_JD9855_INIT_PROGRAM_BYTES] = {
    0x12, 0x34, 0x56, 0x78, 0xde, 0x00, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34,
    0x56, 0x78, 0xdf, 0x98, 0x55, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56,
    0x78, 0xb2, 0x2c, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78, 0xb7,
    0x01, 0x29, 0x01, 0x51, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78,
    0xbb, 0x1b, 0x64, 0xc4, 0x0e, 0x3e, 0xf5, 0x87, 0x65, 0x43, 0x21, 0x12,
    0x34, 0x56, 0x78, 0xbc, 0x03, 0x27, 0xf3, 0xc0, 0x87, 0x65, 0x43, 0x21,
    0x12, 0x34, 0x56, 0x78, 0xc0, 0x22, 0xa1, 0x87, 0x65, 0x43, 0x21, 0x12,
    0x34, 0x56, 0x78, 0xc3, 0x00, 0x02, 0x2a, 0x0b, 0x08, 0x48, 0x08, 0x04,
    0x62, 0x30, 0x30, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78, 0xc4,
    0x40, 0x00, 0xad, 0x68, 0x4b, 0x20, 0x04, 0x16, 0x3f, 0x07, 0x04, 0x87,
    0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78, 0xc8, 0x3f, 0x37, 0x30, 0x2e,
    0x30, 0x34, 0x30, 0x2f, 0x2f, 0x2c, 0x28, 0x1a, 0x15, 0x0e, 0x08, 0x01,
    0x3f, 0x37, 0x30, 0x2e, 0x30, 0x34, 0x30, 0x2f, 0x2f, 0x2c, 0x28, 0x1a,
    0x15, 0x0e, 0x08, 0x01, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78,
    0xd3, 0x28, 0x13, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78, 0xd7,
    0x18, 0x30, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78, 0xde, 0x01,
    0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78, 0xb7, 0x17, 0xa7, 0x64,
    0x3b, 0x06, 0x36, 0x19, 0x15, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56,
    0x78, 0xbe, 0x00, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78, 0xc1,
    0x00, 0x4a, 0x80, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78, 0xc2,
    0x00, 0x16, 0xda, 0xe7, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78,
    0xc4, 0x72, 0x12, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78, 0xc7,
    0x00, 0x00, 0x00, 0x38, 0x08, 0x08, 0x00, 0x01, 0x87, 0x65, 0x43, 0x21,
    0x12, 0x34, 0x56, 0x78, 0xc8, 0x00, 0x00, 0x00, 0x00, 0x16, 0x36, 0x87,
    0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78, 0xc9, 0xc6, 0xc4, 0xca, 0xc8,
    0xde, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78, 0xca, 0xc0, 0xf5,
    0xd6, 0xdf, 0xdf, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78, 0xcb,
    0xc7, 0xc5, 0xcb, 0xc9, 0xd6, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56,
    0x78, 0xcc, 0xc1, 0xf5, 0xd6, 0xdf, 0xdf, 0x87, 0x65, 0x43, 0x21, 0x12,
    0x34, 0x56, 0x78, 0xcd, 0x29, 0x2b, 0x25, 0x27, 0xf6, 0x87, 0x65, 0x43,
    0x21, 0x12, 0x34, 0x56, 0x78, 0xce, 0x21, 0xf5, 0x3f, 0x36, 0x3f, 0x87,
    0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78, 0xcf, 0x28, 0x2a, 0x24, 0x26,
    0xf6, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78, 0xd0, 0x20, 0xf5,
    0x3f, 0x36, 0x3f, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78, 0xd1,
    0x02, 0x30, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78, 0xd2, 0x02,
    0x03, 0x5b, 0x11, 0x0f, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78,
    0xd3, 0x3b, 0x04, 0x48, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78,
    0xd5, 0x10, 0x10, 0x07, 0x07, 0x0f, 0x94, 0x26, 0x87, 0x65, 0x43, 0x21,
    0x12, 0x34, 0x56, 0x78, 0xd6, 0x00, 0x02, 0x40, 0x87, 0x65, 0x43, 0x21,
    0x12, 0x34, 0x56, 0x78, 0xd7, 0x01, 0x85, 0x20, 0x87, 0x65, 0x43, 0x21,
    0x12, 0x34, 0x56, 0x78, 0xde, 0x02, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34,
    0x56, 0x78, 0xb6, 0x1c, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78,
    0xde, 0x03, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78, 0xd2, 0x22,
    0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78, 0xde, 0x00, 0x87, 0x65,
    0x43, 0x21, 0x12, 0x34, 0x56, 0x78, 0x4d, 0x00, 0x87, 0x65, 0x43, 0x21,
    0x12, 0x34, 0x56, 0x78, 0x4e, 0x00, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34,
    0x56, 0x78, 0x4f, 0x00, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78,
    0x4c, 0x01, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78, 0xff, 0x5a,
    0xa5, 0xff, 0x0a, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78, 0x4c,
    0x00, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78, 0x35, 0x00, 0x87,
    0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78, 0x3a, 0x55, 0x87, 0x65, 0x43,
    0x21, 0x12, 0x34, 0x56, 0x78, 0x11, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34,
    0x56, 0x78, 0xff, 0x5a, 0xa5, 0xff, 0x78, 0x87, 0x65, 0x43, 0x21, 0x12,
    0x34, 0x56, 0x78, 0x29, 0x87, 0x65, 0x43, 0x21, 0x12, 0x34, 0x56, 0x78,
    0xff, 0x5a, 0xa5, 0xff, 0x14, 0x87, 0x65, 0x43, 0x21
};

_Static_assert(sizeof(e87_jd9855_init_program) ==
                   E87_JD9855_INIT_PROGRAM_BYTES,
               "JD9855 init byte count changed");
_Static_assert(E87_STRIP_BUFFER_BYTES == 0x5460,
               "recovered descriptor buffer size changed");

struct e87_init_record {
    const uint8_t *body;
    size_t length;
};

static bool e87_marker_at(const uint8_t *program,
                          size_t program_size,
                          size_t position,
                          const uint8_t marker[E87_INIT_MARKER_BYTES])
{
    return position <= program_size &&
           program_size - position >= E87_INIT_MARKER_BYTES &&
           memcmp(program + position, marker, E87_INIT_MARKER_BYTES) == 0;
}

static bool e87_next_record(const uint8_t *program,
                            size_t program_size,
                            size_t *cursor,
                            struct e87_init_record *record)
{
    size_t body_start;
    size_t index;

    if (!e87_marker_at(program, program_size, *cursor, e87_init_start)) {
        return false;
    }
    body_start = *cursor + E87_INIT_MARKER_BYTES;
    index = body_start;
    while (index < program_size) {
        if (e87_marker_at(program, program_size, index, e87_init_start)) {
            return false;
        }
        if (e87_marker_at(program, program_size, index, e87_init_end)) {
            record->body = program + body_start;
            record->length = index - body_start;
            if (record->length == 0U) {
                return false;
            }
            *cursor = index + E87_INIT_MARKER_BYTES;
            return true;
        }
        ++index;
    }
    return false;
}

static bool e87_is_delay(const struct e87_init_record *record)
{
    return record->length >= E87_INIT_MARKER_BYTES &&
           memcmp(record->body,
                  e87_delay_prefix,
                  E87_INIT_MARKER_BYTES) == 0;
}

static bool e87_validate_exact_program(const uint8_t *program,
                                       size_t program_size)
{
    size_t cursor = 0U;
    size_t record_count = 0U;
    struct e87_init_record record;

    if (program == NULL ||
        program_size != E87_JD9855_INIT_PROGRAM_BYTES ||
        memcmp(program,
               e87_jd9855_init_program,
               E87_JD9855_INIT_PROGRAM_BYTES) != 0) {
        return false;
    }
    while (cursor < program_size) {
        if (!e87_next_record(program, program_size, &cursor, &record)) {
            return false;
        }
        if (e87_is_delay(&record) &&
            record.length != E87_DELAY_RECORD_BYTES) {
            return false;
        }
        ++record_count;
    }
    return cursor == program_size &&
           record_count == E87_JD9855_INIT_RECORDS;
}

static bool e87_has_replay_io(const struct e87_panel_io *io)
{
    return io != NULL &&
           io->delay_ms != NULL &&
           io->write_command != NULL;
}

enum e87_panel_result
e87_panel_jd9855_replay(const struct e87_panel_io *io,
                        const uint8_t *program,
                        size_t program_size)
{
    size_t cursor = 0U;
    struct e87_init_record record;

    if (!e87_has_replay_io(io)) {
        return E87_PANEL_ERROR_ARGUMENT;
    }
    if (!e87_validate_exact_program(program, program_size)) {
        return E87_PANEL_ERROR_INIT_PROGRAM;
    }

    while (cursor < program_size) {
        (void)e87_next_record(program, program_size, &cursor, &record);
        if (e87_is_delay(&record)) {
            io->delay_ms(io->context, record.body[4]);
        } else {
            io->write_command(io->context,
                              record.body[0],
                              record.length == 1U ? NULL : record.body + 1U,
                              record.length - 1U);
        }
    }
    return E87_PANEL_OK;
}

enum e87_panel_result
e87_panel_jd9855_reset_and_replay(const struct e87_panel_io *io)
{
    if (!e87_has_replay_io(io) || io->reset_write == NULL) {
        return E87_PANEL_ERROR_ARGUMENT;
    }

    io->reset_write(io->context, true);
    io->delay_ms(io->context, E87_RESET_HIGH_FIRST_MS);
    io->reset_write(io->context, false);
    io->delay_ms(io->context, E87_RESET_LOW_MS);
    io->reset_write(io->context, true);
    io->delay_ms(io->context, E87_RESET_HIGH_FINAL_MS);
    return e87_panel_jd9855_replay(io,
                                   e87_jd9855_init_program,
                                   sizeof(e87_jd9855_init_program));
}

enum e87_panel_result
e87_panel_jd9855_init_dark(const struct e87_panel_io *io)
{
    if (io == NULL || io->backlight_set == NULL) {
        return E87_PANEL_ERROR_ARGUMENT;
    }
    io->backlight_set(io->context, false);
    if (io->set_align == NULL ||
        io->dbi_init == NULL ||
        io->reset_write == NULL ||
        !e87_has_replay_io(io)) {
        return E87_PANEL_ERROR_ARGUMENT;
    }

    io->set_align(io->context,
                  e87_jd9855_profile.row_alignment,
                  e87_jd9855_profile.column_alignment);
    if (io->dbi_init(io->context, &e87_jd9855_profile) != 0) {
        return E87_PANEL_ERROR_DBI_INIT;
    }
    return e87_panel_jd9855_reset_and_replay(io);
}

#if !defined(E87_HOST_TEST)

_Static_assert(LCD_TYPE_SPI == 0, "recovered LCD type encoding changed");
_Static_assert((QSPI_MODE | QSPI_SUBMODE1) == 0x21,
               "recovered QSPI mode encoding changed");
_Static_assert((PIXEL_1P2T | PIXEL_1T2B) == 0x21,
               "recovered pixel encoding changed");
_Static_assert(OUTPUT_FORMAT_RGB565 == 1,
               "recovered input RGB565 encoding changed");
_Static_assert(FORMAT_RGB565 == 1,
               "recovered output RGB565 encoding changed");
_Static_assert(SPI_MODE_UNIDIR == 0,
               "recovered unidirectional encoding changed");
_Static_assert(CLOCK_POLARITY_IDLE_LOW == 0,
               "recovered clock polarity encoding changed");
_Static_assert(DBI_CSX_VSYNC == IO_PORTA_07,
               "dedicated DBI CS pin changed");
_Static_assert(DBI_SCL_WRX == IO_PORTA_12,
               "dedicated DBI clock pin changed");
_Static_assert(DBI_D0 == IO_PORTA_08 &&
               DBI_D1 == IO_PORTA_09 &&
               DBI_D2 == IO_PORTA_10 &&
               DBI_D3 == IO_PORTA_11,
               "dedicated DBI QSPI data pins changed");

/*
 * Zero-valued unused SPI fields preserve the recovered 196-byte parameter
 * image.  In QSPI submode 1 there is no DC wire; the zero DC selector is not
 * a claim that PA09 is connected as DC.
 */
static struct dbi_param e87_jd9855_dbi_param = {
    .scr_x = 0,
    .scr_y = 0,
    .scr_w = 360,
    .scr_h = 360,
    .lcd_width = 360,
    .lcd_height = 360,
    .lcd_type = LCD_TYPE_SPI,
    .buffer_num = 2,
    .buffer_size = 0x5460,
    .in_width = 360,
    .in_height = 360,
    .in_format = OUTPUT_FORMAT_RGB565,
    .in_stride = 0,
    .debug_mode_en = 0,
    .debug_mode_color = 0x00FF0000,
    .fps = 90,
    .spi = {
        .spi_mode = QSPI_MODE | QSPI_SUBMODE1,
        .pixel_type = PIXEL_1P2T | PIXEL_1T2B,
        .out_format = FORMAT_RGB565,
        .spi_dat_mode = SPI_MODE_UNIDIR,
        .cs_pin_select = CS_PIN_SEL_PA7,
        .read_pin_select = READ_PIN_SEL_PA8,
        .clk_pol = CLOCK_POLARITY_IDLE_LOW,
    },
};

static int e87_sdk_dbi_init(
    void *context,
    const struct e87_jd9855_profile *profile)
{
    (void)context;
    if (profile != &e87_jd9855_profile) {
        return -1;
    }
    return lcd_init(&e87_jd9855_dbi_param);
}

static void e87_sdk_set_align(void *context, uint8_t row, uint8_t column)
{
    (void)context;
    lcd_set_align(row, column);
}

static void e87_sdk_reset_write(void *context, bool high)
{
    (void)context;
    gpio_set_mode(IO_PORT_SPILT(IO_PORTA_05),
                  high ? PORT_OUTPUT_HIGH : PORT_OUTPUT_LOW);
}

static void e87_sdk_delay_ms(void *context, uint16_t milliseconds)
{
    (void)context;
    mdelay(milliseconds);
}

static void e87_sdk_write_command(void *context,
                                  uint8_t command,
                                  const uint8_t *parameters,
                                  size_t parameter_count)
{
    (void)context;
    lcd_write_cmd(command,
                  (u8 *)(uintptr_t)parameters,
                  (u32)parameter_count);
}

static void e87_sdk_backlight_set(void *context, bool on)
{
    (void)context;
    power_gate_open_drain_output(IO_LCD_PG, on ? 0U : 1U);
}

static void e87_sdk_wait_busy(void *context)
{
    (void)context;
    lcd_wait_busy();
}

static void e87_sdk_clear(void *context,
                          uint32_t rgb888,
                          uint16_t x_start,
                          uint16_t x_end,
                          uint16_t y_start,
                          uint16_t y_end)
{
    (void)context;
    lcd_clear(rgb888, x_start, x_end, y_start, y_end);
}

static void e87_sdk_set_draw_area(void *context,
                                  uint16_t x_start,
                                  uint16_t x_end,
                                  uint16_t y_start,
                                  uint16_t y_end)
{
    (void)context;
    lcd_set_draw_area(x_start, x_end, y_start, y_end);
}

static void e87_sdk_draw(void *context,
                         const uint16_t *pixels,
                         uint16_t x_start,
                         uint16_t x_end,
                         uint16_t y_start,
                         uint16_t y_end)
{
    (void)context;
    lcd_draw((u8 *)(uintptr_t)pixels,
             x_start,
             x_end,
             y_start,
             y_end);
}

static void e87_sdk_clock_set(void *context,
                              enum e87_panel_clock_action action)
{
    (void)context;
    if (action == E87_PANEL_CLOCK_ACQUIRE) {
        lcd_exit_sleep();
    } else {
        lcd_enter_sleep();
    }
}

const struct e87_panel_io *e87_panel_jd9855_sdk_io(void)
{
    static const struct e87_panel_io io = {
        .context = NULL,
        .dbi_init = e87_sdk_dbi_init,
        .set_align = e87_sdk_set_align,
        .reset_write = e87_sdk_reset_write,
        .delay_ms = e87_sdk_delay_ms,
        .write_command = e87_sdk_write_command,
        .backlight_set = e87_sdk_backlight_set,
        .wait_busy = e87_sdk_wait_busy,
        .clear = e87_sdk_clear,
        .set_draw_area = e87_sdk_set_draw_area,
        .draw = e87_sdk_draw,
        .clock_set = e87_sdk_clock_set,
    };

    return &io;
}

#endif
