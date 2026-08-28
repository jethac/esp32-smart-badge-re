#include "test_support.h"

#include "e87/e87_lcd_stream.h"
#include "e87/e87_panel.h"
#include "e87/e87_renderer.h"
#include "e87/e87_sleep.h"
#include "e87/e87_types.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

enum event_kind {
    EVENT_BACKLIGHT,
    EVENT_ALIGN,
    EVENT_DBI_INIT,
    EVENT_RESET,
    EVENT_DELAY,
    EVENT_COMMAND,
    EVENT_CLEAR,
    EVENT_AREA,
    EVENT_DRAW,
    EVENT_WAIT,
    EVENT_CLOCK,
    EVENT_RENDER,
    EVENT_REDRAW
};

struct event {
    enum event_kind kind;
    uint32_t a;
    uint32_t b;
    uint32_t c;
    uint32_t d;
    const void *pointer;
    size_t size;
};

enum { MAX_EVENTS = 256 };

struct fake_panel {
    struct event events[MAX_EVENTS];
    size_t event_count;
    int init_result;
    bool busy;
    bool backlight_on;
    bool ownership_violation;
    uint8_t render_failure_strip;
    enum e87_lcd_stream_result redraw_result;
};

static struct event *record_event(struct fake_panel *fake,
                                  enum event_kind kind)
{
    struct event *event;

    if (fake->event_count >= MAX_EVENTS) {
        fake->ownership_violation = true;
        return &fake->events[MAX_EVENTS - 1U];
    }
    event = &fake->events[fake->event_count];
    fake->event_count += 1U;
    memset(event, 0, sizeof(*event));
    event->kind = kind;
    return event;
}

static void reset_fake(struct fake_panel *fake)
{
    memset(fake, 0, sizeof(*fake));
    fake->render_failure_strip = UINT8_MAX;
    fake->redraw_result = E87_LCD_STREAM_OK;
}

static int fake_dbi_init(void *context,
                         const struct e87_jd9855_profile *profile)
{
    struct fake_panel *fake = context;
    struct event *event = record_event(fake, EVENT_DBI_INIT);

    event->pointer = profile;
    return fake->init_result;
}

static void fake_set_align(void *context, uint8_t row, uint8_t column)
{
    struct event *event = record_event(context, EVENT_ALIGN);
    event->a = row;
    event->b = column;
}

static void fake_reset_write(void *context, bool high)
{
    struct event *event = record_event(context, EVENT_RESET);
    event->a = high ? 1U : 0U;
}

static void fake_delay(void *context, uint16_t milliseconds)
{
    struct event *event = record_event(context, EVENT_DELAY);
    event->a = milliseconds;
}

static void fake_write_command(void *context,
                               uint8_t command,
                               const uint8_t *parameters,
                               size_t parameter_count)
{
    struct event *event = record_event(context, EVENT_COMMAND);
    event->a = command;
    event->b = (uint32_t)parameter_count;
    event->c = parameter_count == 0U ? 0U : parameters[0];
    event->pointer = parameters;
}

static void fake_backlight(void *context, bool on)
{
    struct fake_panel *fake = context;
    struct event *event = record_event(fake, EVENT_BACKLIGHT);
    event->a = on ? 1U : 0U;
    fake->backlight_on = on;
}

static void fake_wait(void *context)
{
    struct fake_panel *fake = context;
    (void)record_event(fake, EVENT_WAIT);
    fake->busy = false;
}

static void fake_clear(void *context,
                       uint32_t rgb888,
                       uint16_t x_start,
                       uint16_t x_end,
                       uint16_t y_start,
                       uint16_t y_end)
{
    struct fake_panel *fake = context;
    struct event *event = record_event(fake, EVENT_CLEAR);
    if (fake->busy) {
        fake->ownership_violation = true;
    }
    fake->busy = true;
    event->a = rgb888;
    event->b = ((uint32_t)x_start << 16) | x_end;
    event->c = ((uint32_t)y_start << 16) | y_end;
}

static void fake_set_area(void *context,
                          uint16_t x_start,
                          uint16_t x_end,
                          uint16_t y_start,
                          uint16_t y_end)
{
    struct event *event = record_event(context, EVENT_AREA);
    event->a = x_start;
    event->b = x_end;
    event->c = y_start;
    event->d = y_end;
}

static void fake_draw(void *context,
                      const uint16_t *pixels,
                      uint16_t x_start,
                      uint16_t x_end,
                      uint16_t y_start,
                      uint16_t y_end)
{
    struct fake_panel *fake = context;
    struct event *event = record_event(fake, EVENT_DRAW);
    if (fake->busy) {
        fake->ownership_violation = true;
    }
    fake->busy = true;
    event->pointer = pixels;
    event->a = x_start;
    event->b = x_end;
    event->c = y_start;
    event->d = y_end;
}

static void fake_clock(void *context, enum e87_panel_clock_action action)
{
    struct event *event = record_event(context, EVENT_CLOCK);
    event->a = (uint32_t)action;
}

static const struct e87_panel_io *make_io(struct fake_panel *fake)
{
    static struct e87_panel_io io;

    io.context = fake;
    io.dbi_init = fake_dbi_init;
    io.set_align = fake_set_align;
    io.reset_write = fake_reset_write;
    io.delay_ms = fake_delay;
    io.write_command = fake_write_command;
    io.backlight_set = fake_backlight;
    io.wait_busy = fake_wait;
    io.clear = fake_clear;
    io.set_draw_area = fake_set_area;
    io.draw = fake_draw;
    io.clock_set = fake_clock;
    return &io;
}

static enum e87_render_result fake_render(void *context,
                                          uint8_t strip_index,
                                          uint16_t *out_pixels,
                                          size_t out_pixel_count)
{
    struct fake_panel *fake = context;
    struct event *event = record_event(fake, EVENT_RENDER);
    if (fake->busy) {
        fake->ownership_violation = true;
    }
    event->a = strip_index;
    event->pointer = out_pixels;
    event->size = out_pixel_count;
    if (strip_index == fake->render_failure_strip) {
        return E87_RENDER_ERROR_STRIP;
    }
    out_pixels[0] = (uint16_t)strip_index;
    out_pixels[out_pixel_count - 1U] = (uint16_t)(strip_index + 1U);
    return E87_RENDER_OK;
}

static enum e87_lcd_stream_result fake_redraw(void *context)
{
    struct fake_panel *fake = context;
    struct event *event = record_event(fake, EVENT_REDRAW);
    if (fake->backlight_on) {
        fake->ownership_violation = true;
    }
    event->a = (uint32_t)fake->redraw_result;
    return fake->redraw_result;
}

E87_TEST(recovered_profile_keeps_descriptor_and_application_buffers_distinct)
{
    const struct e87_jd9855_profile *profile = &e87_jd9855_profile;

    E87_ASSERT_EQ_U32(UINT32_C(360), profile->width);
    E87_ASSERT_EQ_U32(UINT32_C(360), profile->height);
    E87_ASSERT_EQ_U32(UINT32_C(360), profile->input_width);
    E87_ASSERT_EQ_U32(UINT32_C(360), profile->input_height);
    E87_ASSERT_EQ_U32(UINT32_C(1), profile->input_format_rgb565);
    E87_ASSERT_EQ_U32(UINT32_C(1), profile->output_format_rgb565);
    E87_ASSERT_EQ_U32(UINT32_C(0), profile->lcd_type_spi);
    E87_ASSERT_EQ_U32(UINT32_C(0x21), profile->qspi_mode);
    E87_ASSERT_EQ_U32(UINT32_C(0x21), profile->pixel_type);
    E87_ASSERT_EQ_U32(UINT32_C(0), profile->spi_unidirectional);
    E87_ASSERT_EQ_U32(UINT32_C(0), profile->clock_idle_low);
    E87_ASSERT_EQ_U32(UINT32_C(90), profile->fps);
    E87_ASSERT_EQ_U32(UINT32_C(2), profile->row_alignment);
    E87_ASSERT_EQ_U32(UINT32_C(2), profile->column_alignment);
    E87_ASSERT_EQ_U32(UINT32_C(180), profile->radius);
    E87_ASSERT_EQ_U32(UINT32_C(2), profile->recovered_descriptor_buffer_count);
    E87_ASSERT_EQ_U32(UINT32_C(0x5460), profile->recovered_descriptor_buffer_size);
    E87_ASSERT_EQ_U32(UINT32_C(1), profile->application_transfer_buffer_count);
    E87_ASSERT_EQ_U32(UINT32_C(5), profile->reset_pa_pin);
    E87_ASSERT_EQ_U32(UINT32_C(6), profile->te_pa_pin);
    E87_ASSERT_EQ_U32(UINT32_C(7), profile->cs_pa_pin);
    E87_ASSERT_EQ_U32(UINT32_C(12), profile->clock_pa_pin);
    E87_ASSERT_EQ_U32(UINT32_C(8), profile->data0_pa_pin);
    E87_ASSERT_EQ_U32(UINT32_C(11), profile->data3_pa_pin);
    E87_ASSERT_EQ_U32(UINT32_C(8), profile->read_pa_pin);
    E87_ASSERT_EQ_U32(UINT32_C(0xE7), profile->backlight_selector);
    E87_ASSERT_TRUE(!profile->has_dc);
    E87_ASSERT_TRUE(!profile->has_panel_power_hook);
    E87_ASSERT_TRUE(!profile->orientation_confirmed);
    E87_ASSERT_TRUE(profile->model_1542_inferred);
}

E87_TEST(cold_init_is_dark_dbi_first_then_exact_reset_and_program)
{
    struct fake_panel fake;
    const struct e87_panel_io *io;
    size_t tail;

    reset_fake(&fake);
    io = make_io(&fake);
    E87_ASSERT_EQ_U32(E87_PANEL_OK, e87_panel_jd9855_init_dark(io));
    E87_ASSERT_EQ_U32(UINT32_C(60), fake.event_count);
    E87_ASSERT_EQ_U32(EVENT_BACKLIGHT, fake.events[0].kind);
    E87_ASSERT_EQ_U32(UINT32_C(0), fake.events[0].a);
    E87_ASSERT_EQ_U32(EVENT_ALIGN, fake.events[1].kind);
    E87_ASSERT_EQ_U32(UINT32_C(2), fake.events[1].a);
    E87_ASSERT_EQ_U32(UINT32_C(2), fake.events[1].b);
    E87_ASSERT_EQ_U32(EVENT_DBI_INIT, fake.events[2].kind);
    E87_ASSERT_TRUE(fake.events[2].pointer == &e87_jd9855_profile);
    E87_ASSERT_EQ_U32(EVENT_RESET, fake.events[3].kind);
    E87_ASSERT_EQ_U32(UINT32_C(1), fake.events[3].a);
    E87_ASSERT_EQ_U32(EVENT_DELAY, fake.events[4].kind);
    E87_ASSERT_EQ_U32(UINT32_C(10), fake.events[4].a);
    E87_ASSERT_EQ_U32(EVENT_RESET, fake.events[5].kind);
    E87_ASSERT_EQ_U32(UINT32_C(0), fake.events[5].a);
    E87_ASSERT_EQ_U32(UINT32_C(10), fake.events[6].a);
    E87_ASSERT_EQ_U32(UINT32_C(1), fake.events[7].a);
    E87_ASSERT_EQ_U32(UINT32_C(100), fake.events[8].a);
    E87_ASSERT_EQ_U32(EVENT_COMMAND, fake.events[9].kind);
    E87_ASSERT_EQ_U32(UINT32_C(0xDE), fake.events[9].a);
    E87_ASSERT_EQ_U32(UINT32_C(1), fake.events[9].b);
    E87_ASSERT_EQ_U32(UINT32_C(0), fake.events[9].c);
    tail = fake.event_count - 8U;
    E87_ASSERT_EQ_U32(EVENT_DELAY, fake.events[tail].kind);
    E87_ASSERT_EQ_U32(UINT32_C(10), fake.events[tail].a);
    E87_ASSERT_EQ_U32(UINT32_C(0x4C), fake.events[tail + 1U].a);
    E87_ASSERT_EQ_U32(UINT32_C(0x35), fake.events[tail + 2U].a);
    E87_ASSERT_EQ_U32(UINT32_C(0x3A), fake.events[tail + 3U].a);
    E87_ASSERT_EQ_U32(UINT32_C(0x55), fake.events[tail + 3U].c);
    E87_ASSERT_EQ_U32(UINT32_C(0x11), fake.events[tail + 4U].a);
    E87_ASSERT_EQ_U32(UINT32_C(120), fake.events[tail + 5U].a);
    E87_ASSERT_EQ_U32(UINT32_C(0x29), fake.events[tail + 6U].a);
    E87_ASSERT_EQ_U32(UINT32_C(20), fake.events[tail + 7U].a);
    E87_ASSERT_TRUE(!fake.backlight_on);
}

E87_TEST(init_failure_stops_before_reset_and_keeps_backlight_dark)
{
    struct fake_panel fake;
    const struct e87_panel_io *io;

    reset_fake(&fake);
    fake.init_result = -1;
    io = make_io(&fake);
    E87_ASSERT_EQ_U32(E87_PANEL_ERROR_DBI_INIT,
                      e87_panel_jd9855_init_dark(io));
    E87_ASSERT_EQ_U32(UINT32_C(3), fake.event_count);
    E87_ASSERT_EQ_U32(EVENT_BACKLIGHT, fake.events[0].kind);
    E87_ASSERT_EQ_U32(EVENT_ALIGN, fake.events[1].kind);
    E87_ASSERT_EQ_U32(EVENT_DBI_INIT, fake.events[2].kind);
    E87_ASSERT_TRUE(!fake.backlight_on);
}

E87_TEST(init_parser_rejects_truncation_without_emitting_partial_tail)
{
    struct fake_panel fake;
    const struct e87_panel_io *io;

    reset_fake(&fake);
    io = make_io(&fake);
    E87_ASSERT_EQ_U32(
        E87_PANEL_ERROR_INIT_PROGRAM,
        e87_panel_jd9855_replay(io,
                                e87_jd9855_init_program,
                                E87_JD9855_INIT_PROGRAM_BYTES - 1U));
    E87_ASSERT_TRUE(fake.event_count < UINT32_C(51));
}

E87_TEST(solid_ladder_is_five_full_screen_fills_each_followed_by_wait)
{
    static const uint32_t colors[] = {
        UINT32_C(0x000000), UINT32_C(0xFFFFFF), UINT32_C(0xFF0000),
        UINT32_C(0x00FF00), UINT32_C(0x0000FF)
    };
    struct fake_panel fake;
    const struct e87_panel_io *io;
    size_t index;

    reset_fake(&fake);
    io = make_io(&fake);
    E87_ASSERT_EQ_U32(E87_LCD_STREAM_OK,
                      e87_lcd_solid_color_ladder(io));
    E87_ASSERT_EQ_U32(UINT32_C(10), fake.event_count);
    for (index = 0U; index < 5U; index += 1U) {
        const struct event *clear = &fake.events[index * 2U];
        E87_ASSERT_EQ_U32(EVENT_CLEAR, clear->kind);
        E87_ASSERT_EQ_U32(colors[index], clear->a);
        E87_ASSERT_EQ_U32(UINT32_C(0x00000167), clear->b);
        E87_ASSERT_EQ_U32(UINT32_C(0x00000167), clear->c);
        E87_ASSERT_EQ_U32(EVENT_WAIT, fake.events[index * 2U + 1U].kind);
    }
    E87_ASSERT_TRUE(!fake.busy);
    E87_ASSERT_TRUE(!fake.ownership_violation);
}

E87_TEST(serial_frame_reuses_one_aligned_buffer_only_after_twelve_waits)
{
    struct fake_panel fake;
    const struct e87_panel_io *io;
    const void *buffer = NULL;
    size_t strip;

    reset_fake(&fake);
    io = make_io(&fake);
    E87_ASSERT_EQ_U32(E87_LCD_STREAM_OK,
                      e87_lcd_stream_frame_serial(io, fake_render, &fake));
    E87_ASSERT_EQ_U32(UINT32_C(48), fake.event_count);
    for (strip = 0U; strip < E87_STRIP_COUNT; strip += 1U) {
        const size_t base = strip * 4U;
        const uint32_t y = (uint32_t)strip * E87_STRIP_ROWS;
        const struct event *render = &fake.events[base];
        const struct event *area = &fake.events[base + 1U];
        const struct event *draw = &fake.events[base + 2U];
        E87_ASSERT_EQ_U32(EVENT_RENDER, render->kind);
        E87_ASSERT_EQ_U32(strip, render->a);
        E87_ASSERT_EQ_U32(UINT32_C(10800), render->size);
        E87_ASSERT_EQ_U32(EVENT_AREA, area->kind);
        E87_ASSERT_EQ_U32(UINT32_C(0), area->a);
        E87_ASSERT_EQ_U32(UINT32_C(359), area->b);
        E87_ASSERT_EQ_U32(y, area->c);
        E87_ASSERT_EQ_U32(y + UINT32_C(29), area->d);
        E87_ASSERT_EQ_U32(EVENT_DRAW, draw->kind);
        E87_ASSERT_TRUE(draw->pointer == render->pointer);
        E87_ASSERT_EQ_U32(y, draw->c);
        E87_ASSERT_EQ_U32(y + UINT32_C(29), draw->d);
        E87_ASSERT_EQ_U32(EVENT_WAIT, fake.events[base + 3U].kind);
        if (strip == 0U) {
            buffer = draw->pointer;
        } else {
            E87_ASSERT_TRUE(draw->pointer == buffer);
        }
    }
    E87_ASSERT_TRUE(((uintptr_t)buffer & UINT32_C(3)) == 0U);
    E87_ASSERT_TRUE(!fake.busy);
    E87_ASSERT_TRUE(!fake.ownership_violation);
}

E87_TEST(render_failure_stops_before_failed_strip_draw_and_returns_idle)
{
    struct fake_panel fake;
    const struct e87_panel_io *io;

    reset_fake(&fake);
    fake.render_failure_strip = UINT8_C(3);
    io = make_io(&fake);
    E87_ASSERT_EQ_U32(E87_LCD_STREAM_ERROR_RENDER,
                      e87_lcd_stream_frame_serial(io, fake_render, &fake));
    E87_ASSERT_EQ_U32(UINT32_C(13), fake.event_count);
    E87_ASSERT_EQ_U32(EVENT_RENDER, fake.events[12].kind);
    E87_ASSERT_EQ_U32(UINT32_C(3), fake.events[12].a);
    E87_ASSERT_TRUE(!fake.busy);
    E87_ASSERT_TRUE(!fake.ownership_violation);
}

E87_TEST(normal_face_adapter_streams_the_production_renderer_serially)
{
    const struct e87_metrics metrics = {50U, 99U, UINT32_C(1727)};
    struct fake_panel fake;
    const struct e87_panel_io *io;

    reset_fake(&fake);
    io = make_io(&fake);
    E87_ASSERT_EQ_U32(E87_LCD_STREAM_OK,
                      e87_lcd_stream_normal_face_serial(io, &metrics));
    E87_ASSERT_EQ_U32(UINT32_C(36), fake.event_count);
    E87_ASSERT_EQ_U32(EVENT_AREA, fake.events[0].kind);
    E87_ASSERT_EQ_U32(EVENT_DRAW, fake.events[1].kind);
    E87_ASSERT_EQ_U32(EVENT_WAIT, fake.events[2].kind);
    E87_ASSERT_EQ_U32(UINT32_C(330), fake.events[33].c);
    E87_ASSERT_EQ_U32(UINT32_C(359), fake.events[33].d);
    E87_ASSERT_TRUE(!fake.busy);
    E87_ASSERT_TRUE(!fake.ownership_violation);
}

E87_TEST(sleep_entry_drains_darkens_commands_delays_then_releases_clock)
{
    struct fake_panel fake;
    const struct e87_panel_io *io;

    reset_fake(&fake);
    fake.busy = true;
    fake.backlight_on = true;
    io = make_io(&fake);
    E87_ASSERT_EQ_U32(E87_SLEEP_OK, e87_sleep_enter(io));
    E87_ASSERT_EQ_U32(UINT32_C(6), fake.event_count);
    E87_ASSERT_EQ_U32(EVENT_WAIT, fake.events[0].kind);
    E87_ASSERT_EQ_U32(EVENT_BACKLIGHT, fake.events[1].kind);
    E87_ASSERT_EQ_U32(UINT32_C(0), fake.events[1].a);
    E87_ASSERT_EQ_U32(EVENT_COMMAND, fake.events[2].kind);
    E87_ASSERT_EQ_U32(UINT32_C(0x28), fake.events[2].a);
    E87_ASSERT_EQ_U32(EVENT_COMMAND, fake.events[3].kind);
    E87_ASSERT_EQ_U32(UINT32_C(0x10), fake.events[3].a);
    E87_ASSERT_EQ_U32(EVENT_DELAY, fake.events[4].kind);
    E87_ASSERT_EQ_U32(UINT32_C(120), fake.events[4].a);
    E87_ASSERT_EQ_U32(EVENT_CLOCK, fake.events[5].kind);
    E87_ASSERT_EQ_U32(E87_PANEL_CLOCK_RELEASE, fake.events[5].a);
    E87_ASSERT_TRUE(!fake.backlight_on);
    E87_ASSERT_TRUE(!fake.busy);
}

E87_TEST(wake_acquires_resets_replays_redraws_dark_and_enables_last)
{
    struct fake_panel fake;
    const struct e87_panel_io *io;

    reset_fake(&fake);
    io = make_io(&fake);
    E87_ASSERT_EQ_U32(E87_SLEEP_OK,
                      e87_sleep_wake(io, fake_redraw, &fake));
    E87_ASSERT_EQ_U32(UINT32_C(61), fake.event_count);
    E87_ASSERT_EQ_U32(EVENT_BACKLIGHT, fake.events[0].kind);
    E87_ASSERT_EQ_U32(UINT32_C(0), fake.events[0].a);
    E87_ASSERT_EQ_U32(EVENT_CLOCK, fake.events[1].kind);
    E87_ASSERT_EQ_U32(E87_PANEL_CLOCK_ACQUIRE, fake.events[1].a);
    E87_ASSERT_EQ_U32(EVENT_RESET, fake.events[2].kind);
    E87_ASSERT_EQ_U32(UINT32_C(1), fake.events[2].a);
    E87_ASSERT_EQ_U32(UINT32_C(10), fake.events[3].a);
    E87_ASSERT_EQ_U32(UINT32_C(0), fake.events[4].a);
    E87_ASSERT_EQ_U32(UINT32_C(10), fake.events[5].a);
    E87_ASSERT_EQ_U32(UINT32_C(1), fake.events[6].a);
    E87_ASSERT_EQ_U32(UINT32_C(100), fake.events[7].a);
    E87_ASSERT_EQ_U32(EVENT_COMMAND, fake.events[8].kind);
    E87_ASSERT_EQ_U32(UINT32_C(0xDE), fake.events[8].a);
    E87_ASSERT_EQ_U32(EVENT_REDRAW, fake.events[59].kind);
    E87_ASSERT_EQ_U32(EVENT_BACKLIGHT, fake.events[60].kind);
    E87_ASSERT_EQ_U32(UINT32_C(1), fake.events[60].a);
    E87_ASSERT_TRUE(fake.backlight_on);
    E87_ASSERT_TRUE(!fake.ownership_violation);
}

E87_TEST(wake_redraw_failure_never_enables_backlight)
{
    struct fake_panel fake;
    const struct e87_panel_io *io;

    reset_fake(&fake);
    fake.redraw_result = E87_LCD_STREAM_ERROR_RENDER;
    io = make_io(&fake);
    E87_ASSERT_EQ_U32(E87_SLEEP_ERROR_REDRAW,
                      e87_sleep_wake(io, fake_redraw, &fake));
    E87_ASSERT_EQ_U32(UINT32_C(60), fake.event_count);
    E87_ASSERT_EQ_U32(EVENT_REDRAW, fake.events[59].kind);
    E87_ASSERT_TRUE(!fake.backlight_on);
    E87_ASSERT_TRUE(!fake.ownership_violation);
}

static const struct e87_test_case lcd_cases[] = {
    E87_TEST_CASE(recovered_profile_keeps_descriptor_and_application_buffers_distinct),
    E87_TEST_CASE(cold_init_is_dark_dbi_first_then_exact_reset_and_program),
    E87_TEST_CASE(init_failure_stops_before_reset_and_keeps_backlight_dark),
    E87_TEST_CASE(init_parser_rejects_truncation_without_emitting_partial_tail),
    E87_TEST_CASE(solid_ladder_is_five_full_screen_fills_each_followed_by_wait),
    E87_TEST_CASE(serial_frame_reuses_one_aligned_buffer_only_after_twelve_waits),
    E87_TEST_CASE(render_failure_stops_before_failed_strip_draw_and_returns_idle),
    E87_TEST_CASE(normal_face_adapter_streams_the_production_renderer_serially),
    E87_TEST_CASE(sleep_entry_drains_darkens_commands_delays_then_releases_clock),
    E87_TEST_CASE(wake_acquires_resets_replays_redraws_dark_and_enables_last),
    E87_TEST_CASE(wake_redraw_failure_never_enables_backlight),
};

const struct e87_test_suite e87_test_suite = {
    "lcd-serial-panel",
    lcd_cases,
    sizeof(lcd_cases) / sizeof(lcd_cases[0]),
};
