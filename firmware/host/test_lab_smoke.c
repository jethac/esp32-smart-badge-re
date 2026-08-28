#include "test_support.h"

#include "e87/e87_lab_smoke.h"
#include "e87/e87_transient_renderer.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

enum {
    FRAME_PIXELS = E87_DISPLAY_WIDTH * E87_DISPLAY_HEIGHT,
    STRIP_PIXELS = E87_DISPLAY_WIDTH * E87_STRIP_ROWS
};

static uint16_t captured_frames[2][FRAME_PIXELS];
static uint16_t expected_frame[FRAME_PIXELS];

struct fake_panel {
    size_t draw_count;
    size_t wait_count;
    size_t backlight_off_count;
    size_t backlight_on_count;
    size_t first_backlight_on_draw_count;
    bool busy;
    bool backlight_on;
    bool ownership_violation;
};

static int fake_dbi_init(void *context,
                         const struct e87_jd9855_profile *profile)
{
    (void)context;
    return profile == &e87_jd9855_profile ? 0 : -1;
}

static void fake_set_align(void *context, uint8_t row, uint8_t column)
{
    (void)context;
    (void)row;
    (void)column;
}

static void fake_reset_write(void *context, bool high)
{
    (void)context;
    (void)high;
}

static void fake_delay_ms(void *context, uint16_t milliseconds)
{
    (void)context;
    (void)milliseconds;
}

static void fake_write_command(void *context,
                               uint8_t command,
                               const uint8_t *parameters,
                               size_t parameter_count)
{
    (void)context;
    (void)command;
    (void)parameters;
    (void)parameter_count;
}

static void fake_backlight_set(void *context, bool on)
{
    struct fake_panel *fake = context;

    fake->backlight_on = on;
    if (on) {
        if (fake->backlight_on_count == 0U) {
            fake->first_backlight_on_draw_count = fake->draw_count;
        }
        fake->backlight_on_count += 1U;
    } else {
        fake->backlight_off_count += 1U;
    }
}

static void fake_wait_busy(void *context)
{
    struct fake_panel *fake = context;

    fake->wait_count += 1U;
    fake->busy = false;
}

static void fake_clear(void *context,
                       uint32_t rgb888,
                       uint16_t x_start,
                       uint16_t x_end,
                       uint16_t y_start,
                       uint16_t y_end)
{
    (void)context;
    (void)rgb888;
    (void)x_start;
    (void)x_end;
    (void)y_start;
    (void)y_end;
}

static void fake_set_draw_area(void *context,
                               uint16_t x_start,
                               uint16_t x_end,
                               uint16_t y_start,
                               uint16_t y_end)
{
    (void)context;
    (void)x_start;
    (void)x_end;
    (void)y_start;
    (void)y_end;
}

static void fake_draw(void *context,
                      const uint16_t *pixels,
                      uint16_t x_start,
                      uint16_t x_end,
                      uint16_t y_start,
                      uint16_t y_end)
{
    struct fake_panel *fake = context;

    if (fake->busy || x_start != UINT16_C(0) ||
        x_end != UINT16_C(359) ||
        y_end != (uint16_t)(y_start + E87_STRIP_ROWS - 1U) ||
        y_start >= E87_DISPLAY_HEIGHT) {
        fake->ownership_violation = true;
    }
    fake->busy = true;
    memcpy(captured_frames[fake->draw_count / E87_STRIP_COUNT] +
               (size_t)y_start * E87_DISPLAY_WIDTH,
           pixels,
           STRIP_PIXELS * sizeof(uint16_t));
    fake->draw_count += 1U;
}

static void fake_clock_set(void *context,
                           enum e87_panel_clock_action action)
{
    (void)context;
    (void)action;
}

static struct e87_panel_io make_io(struct fake_panel *fake)
{
    const struct e87_panel_io io = {
        .context = fake,
        .dbi_init = fake_dbi_init,
        .set_align = fake_set_align,
        .reset_write = fake_reset_write,
        .delay_ms = fake_delay_ms,
        .write_command = fake_write_command,
        .backlight_set = fake_backlight_set,
        .wait_busy = fake_wait_busy,
        .clear = fake_clear,
        .set_draw_area = fake_set_draw_area,
        .draw = fake_draw,
        .clock_set = fake_clock_set,
    };

    return io;
}

static bool render_expected_pair_me(void)
{
    struct e87_render_model model;
    uint8_t strip;

    memset(&model, 0, sizeof(model));
    model.screen = E87_UI_SCREEN_PAIR_ME_NOW;
    for (strip = UINT8_C(0); strip < E87_STRIP_COUNT; strip += UINT8_C(1)) {
        if (e87_render_transient_strip(
                &model,
                strip,
                expected_frame + (size_t)strip * STRIP_PIXELS,
                STRIP_PIXELS) != E87_TRANSIENT_RENDER_OK) {
            return false;
        }
    }
    return true;
}

static bool render_expected_face(void)
{
    struct e87_render_model model;
    uint8_t strip;

    memset(&model, 0, sizeof(model));
    model.screen = E87_UI_SCREEN_FACE;
    model.metrics.day = UINT8_C(67);
    model.metrics.week = UINT8_C(42);
    model.metrics.credit_cents = E87_STATE_FIXED_CREDIT_CENTS;
    for (strip = UINT8_C(0); strip < E87_STRIP_COUNT; strip += UINT8_C(1)) {
        if (e87_render_transient_strip(
                &model,
                strip,
                expected_frame + (size_t)strip * STRIP_PIXELS,
                STRIP_PIXELS) != E87_TRANSIENT_RENDER_OK) {
            return false;
        }
    }
    return true;
}

E87_TEST(start_initializes_dark_renders_pair_me_then_enables_backlight)
{
    struct fake_panel fake;
    struct e87_panel_io io;
    struct e87_lab_smoke smoke;

    memset(&fake, 0, sizeof(fake));
    memset(&smoke, 0xA5, sizeof(smoke));
    memset(captured_frames, 0x5A, sizeof(captured_frames));
    memset(expected_frame, 0xC3, sizeof(expected_frame));
    io = make_io(&fake);

    E87_ASSERT_EQ_U32(
        E87_LAB_SMOKE_OK,
        e87_lab_smoke_start(&smoke, &io, UINT32_C(1234)));
    E87_ASSERT_TRUE(render_expected_pair_me());
    E87_ASSERT_EQ_U32(E87_STRIP_COUNT, fake.draw_count);
    E87_ASSERT_EQ_U32(E87_STRIP_COUNT, fake.wait_count);
    E87_ASSERT_TRUE(!fake.ownership_violation);
    E87_ASSERT_TRUE(fake.backlight_off_count >= 1U);
    E87_ASSERT_EQ_U32(UINT32_C(1), fake.backlight_on_count);
    E87_ASSERT_EQ_U32(E87_STRIP_COUNT,
                      fake.first_backlight_on_draw_count);
    E87_ASSERT_TRUE(fake.backlight_on);
    E87_ASSERT_TRUE(memcmp(captured_frames[0],
                           expected_frame,
                           sizeof(captured_frames[0])) == 0);
}

E87_TEST(step_waits_three_seconds_then_presents_fixed_devin_face_once)
{
    struct fake_panel fake;
    struct e87_panel_io io;
    struct e87_lab_smoke smoke;

    memset(&fake, 0, sizeof(fake));
    memset(&smoke, 0, sizeof(smoke));
    memset(captured_frames, 0x5A, sizeof(captured_frames));
    memset(expected_frame, 0xC3, sizeof(expected_frame));
    io = make_io(&fake);

    E87_ASSERT_EQ_U32(
        E87_LAB_SMOKE_OK,
        e87_lab_smoke_start(&smoke, &io, UINT32_C(0xfffff800)));
    E87_ASSERT_EQ_U32(
        E87_LAB_SMOKE_NO_CHANGE,
        e87_lab_smoke_step(&smoke, UINT32_C(0x000003b7)));
    E87_ASSERT_EQ_U32(E87_STRIP_COUNT, fake.draw_count);
    E87_ASSERT_EQ_U32(
        E87_LAB_SMOKE_OK,
        e87_lab_smoke_step(&smoke, UINT32_C(0x000003b8)));
    E87_ASSERT_TRUE(render_expected_face());
    E87_ASSERT_EQ_U32(E87_STRIP_COUNT * UINT32_C(2), fake.draw_count);
    E87_ASSERT_EQ_U32(E87_STRIP_COUNT * UINT32_C(2), fake.wait_count);
    E87_ASSERT_EQ_U32(UINT32_C(1), fake.backlight_on_count);
    E87_ASSERT_TRUE(!fake.ownership_violation);
    E87_ASSERT_TRUE(memcmp(captured_frames[1],
                           expected_frame,
                           sizeof(captured_frames[1])) == 0);
    E87_ASSERT_EQ_U32(
        E87_LAB_SMOKE_NO_CHANGE,
        e87_lab_smoke_step(&smoke, UINT32_C(0x00010000)));
    E87_ASSERT_EQ_U32(E87_STRIP_COUNT * UINT32_C(2), fake.draw_count);
}

static const struct e87_test_case cases[] = {
    E87_TEST_CASE(
        start_initializes_dark_renders_pair_me_then_enables_backlight),
    E87_TEST_CASE(
        step_waits_three_seconds_then_presents_fixed_devin_face_once),
};

const struct e87_test_suite e87_test_suite = {
    "lab-panel-smoke",
    cases,
    sizeof(cases) / sizeof(cases[0]),
};
