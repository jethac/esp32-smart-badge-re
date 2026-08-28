#include "test_support.h"
#include "e87/e87_transient_renderer.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

enum {
    E87_TEST_STRIP_PIXELS = E87_DISPLAY_WIDTH * E87_STRIP_ROWS,
    E87_TEST_FRAME_PIXELS = E87_DISPLAY_WIDTH * E87_DISPLAY_HEIGHT
};

static uint16_t frame_a[E87_TEST_FRAME_PIXELS];
static uint16_t frame_b[E87_TEST_FRAME_PIXELS];

static struct e87_render_model model(enum e87_ui_screen screen)
{
    struct e87_render_model value;

    memset(&value, 0, sizeof(value));
    value.screen = screen;
    value.metrics.day = UINT8_C(17);
    value.metrics.week = UINT8_C(27);
    value.metrics.credit_cents = E87_STATE_FIXED_CREDIT_CENTS;
    value.battery_state = E87_UI_BATTERY_VALID;
    value.battery_percent = UINT8_C(50);
    value.maintenance_phase = E87_UI_MAINTENANCE_WAITING_FOR_PHONE;
    return value;
}

static void fill_words(uint16_t *words, size_t count, uint16_t value)
{
    size_t index;

    for (index = 0u; index < count; ++index) {
        words[index] = value;
    }
}

static bool render_frame(const struct e87_render_model *scene,
                         uint16_t *out,
                         bool reverse,
                         unsigned int repetitions)
{
    unsigned int step;

    for (step = 0u; step < E87_STRIP_COUNT; ++step) {
        const uint8_t strip_index =
            (uint8_t)(reverse ? E87_STRIP_COUNT - 1u - step : step);
        unsigned int repetition;

        for (repetition = 0u; repetition < repetitions; ++repetition) {
            if (e87_render_transient_strip(
                    scene,
                    strip_index,
                    out + (size_t)strip_index * E87_TEST_STRIP_PIXELS,
                    E87_TEST_STRIP_PIXELS) != E87_TRANSIENT_RENDER_OK) {
                return false;
            }
        }
    }
    return true;
}

static size_t nonblack_pixels(const uint16_t *frame)
{
    size_t count = 0u;
    size_t index;

    for (index = 0u; index < E87_TEST_FRAME_PIXELS; ++index) {
        if (frame[index] != UINT16_C(0)) {
            ++count;
        }
    }
    return count;
}

E87_TEST(rejects_invalid_arguments_and_models_without_mutating_output)
{
    struct e87_render_model valid = model(E87_UI_SCREEN_PAIR_ME_NOW);
    struct e87_render_model invalid;
    uint16_t guarded[E87_TEST_STRIP_PIXELS + 2u];
    uint16_t before[E87_TEST_STRIP_PIXELS + 2u];

    fill_words(guarded, E87_TEST_STRIP_PIXELS + 2u, UINT16_C(0xA55A));
    memcpy(before, guarded, sizeof(guarded));
    E87_ASSERT_EQ_U32(
        E87_TRANSIENT_RENDER_ERROR_ARGUMENT,
        e87_render_transient_strip(
            NULL, UINT8_C(0), &guarded[1], E87_TEST_STRIP_PIXELS));
    E87_ASSERT_TRUE(memcmp(guarded, before, sizeof(guarded)) == 0);
    E87_ASSERT_EQ_U32(
        E87_TRANSIENT_RENDER_ERROR_ARGUMENT,
        e87_render_transient_strip(
            &valid, UINT8_C(0), NULL, E87_TEST_STRIP_PIXELS));
    E87_ASSERT_TRUE(memcmp(guarded, before, sizeof(guarded)) == 0);
    E87_ASSERT_EQ_U32(
        E87_TRANSIENT_RENDER_ERROR_STRIP,
        e87_render_transient_strip(
            &valid, UINT8_C(12), &guarded[1], E87_TEST_STRIP_PIXELS));
    E87_ASSERT_TRUE(memcmp(guarded, before, sizeof(guarded)) == 0);
    E87_ASSERT_EQ_U32(
        E87_TRANSIENT_RENDER_ERROR_CAPACITY,
        e87_render_transient_strip(
            &valid,
            UINT8_C(0),
            &guarded[1],
            E87_TEST_STRIP_PIXELS - 1u));
    E87_ASSERT_TRUE(memcmp(guarded, before, sizeof(guarded)) == 0);

    invalid = valid;
    invalid.screen = (enum e87_ui_screen)99;
    E87_ASSERT_EQ_U32(
        E87_TRANSIENT_RENDER_ERROR_MODEL,
        e87_render_transient_strip(
            &invalid, UINT8_C(0), &guarded[1], E87_TEST_STRIP_PIXELS));
    E87_ASSERT_TRUE(memcmp(guarded, before, sizeof(guarded)) == 0);

    invalid = model(E87_UI_SCREEN_PAIRING);
    invalid.countdown_seconds = UINT8_C(0);
    E87_ASSERT_EQ_U32(
        E87_TRANSIENT_RENDER_ERROR_MODEL,
        e87_render_transient_strip(
            &invalid, UINT8_C(0), &guarded[1], E87_TEST_STRIP_PIXELS));
    E87_ASSERT_TRUE(memcmp(guarded, before, sizeof(guarded)) == 0);

    invalid = model(E87_UI_SCREEN_FACE);
    invalid.metrics.credit_cents = UINT32_C(1728);
    E87_ASSERT_EQ_U32(
        E87_TRANSIENT_RENDER_ERROR_MODEL,
        e87_render_transient_strip(
            &invalid, UINT8_C(0), &guarded[1], E87_TEST_STRIP_PIXELS));
    E87_ASSERT_TRUE(memcmp(guarded, before, sizeof(guarded)) == 0);

    invalid = model(E87_UI_SCREEN_MAINTENANCE);
    invalid.maintenance_progress_percent = UINT8_C(101);
    E87_ASSERT_EQ_U32(
        E87_TRANSIENT_RENDER_ERROR_MODEL,
        e87_render_transient_strip(
            &invalid, UINT8_C(0), &guarded[1], E87_TEST_STRIP_PIXELS));
    E87_ASSERT_TRUE(memcmp(guarded, before, sizeof(guarded)) == 0);

    invalid = model(E87_UI_SCREEN_MAINTENANCE);
    invalid.recovery_entry = true;
    invalid.maintenance_phase = E87_UI_MAINTENANCE_UPDATING;
    E87_ASSERT_EQ_U32(
        E87_TRANSIENT_RENDER_ERROR_MODEL,
        e87_render_transient_strip(
            &invalid, UINT8_C(0), &guarded[1], E87_TEST_STRIP_PIXELS));
    E87_ASSERT_TRUE(memcmp(guarded, before, sizeof(guarded)) == 0);

    invalid.maintenance_phase = E87_UI_MAINTENANCE_RELEASE_BUTTON;
    invalid.maintenance_progress_percent = UINT8_C(1);
    E87_ASSERT_EQ_U32(
        E87_TRANSIENT_RENDER_ERROR_MODEL,
        e87_render_transient_strip(
            &invalid, UINT8_C(0), &guarded[1], E87_TEST_STRIP_PIXELS));
    E87_ASSERT_TRUE(memcmp(guarded, before, sizeof(guarded)) == 0);
}

E87_TEST(panel_off_is_a_distinct_no_draw_result)
{
    struct e87_render_model off = model(E87_UI_SCREEN_PANEL_OFF);
    uint16_t guarded[E87_TEST_STRIP_PIXELS + 2u];
    uint16_t before[E87_TEST_STRIP_PIXELS + 2u];

    fill_words(guarded, E87_TEST_STRIP_PIXELS + 2u, UINT16_C(0x7BEF));
    memcpy(before, guarded, sizeof(guarded));
    E87_ASSERT_EQ_U32(
        E87_TRANSIENT_RENDER_PANEL_OFF,
        e87_render_transient_strip(
            &off, UINT8_C(0), &guarded[1], E87_TEST_STRIP_PIXELS));
    E87_ASSERT_TRUE(memcmp(guarded, before, sizeof(guarded)) == 0);
}

E87_TEST(face_without_overlay_is_byte_exact_to_reviewed_normal_renderer)
{
    struct e87_render_model face = model(E87_UI_SCREEN_FACE);
    uint16_t transient[E87_TEST_STRIP_PIXELS];
    uint16_t normal[E87_TEST_STRIP_PIXELS];
    unsigned int strip;

    for (strip = 0u; strip < E87_STRIP_COUNT; ++strip) {
        E87_ASSERT_EQ_U32(
            E87_TRANSIENT_RENDER_OK,
            e87_render_transient_strip(
                &face,
                (uint8_t)strip,
                transient,
                E87_TEST_STRIP_PIXELS));
        E87_ASSERT_EQ_U32(
            E87_RENDER_OK,
            e87_render_normal_face_strip(
                &face.metrics,
                (uint8_t)strip,
                normal,
                E87_TEST_STRIP_PIXELS));
        E87_ASSERT_TRUE(memcmp(transient, normal, sizeof(normal)) == 0);
    }
}

E87_TEST(every_visible_mode_is_strip_deterministic_and_writes_only_one_strip)
{
    struct e87_render_model scenes[13];
    size_t scene_index;

    scenes[0] = model(E87_UI_SCREEN_PAIR_ME_NOW);
    scenes[1] = model(E87_UI_SCREEN_WAITING_FOR_PHONE);
    scenes[2] = model(E87_UI_SCREEN_PAIRING);
    scenes[2].countdown_seconds = UINT8_C(60);
    scenes[3] = model(E87_UI_SCREEN_UPDATE_WARNING);
    scenes[3].countdown_seconds = UINT8_C(3);
    scenes[4] = model(E87_UI_SCREEN_MAINTENANCE);
    scenes[4].maintenance_phase = E87_UI_MAINTENANCE_RELEASE_BUTTON;
    scenes[5] = model(E87_UI_SCREEN_MAINTENANCE);
    scenes[5].maintenance_phase = E87_UI_MAINTENANCE_WAITING_FOR_PHONE;
    scenes[6] = model(E87_UI_SCREEN_MAINTENANCE);
    scenes[6].maintenance_phase = E87_UI_MAINTENANCE_PHONE_READY;
    scenes[7] = model(E87_UI_SCREEN_MAINTENANCE);
    scenes[7].maintenance_phase = E87_UI_MAINTENANCE_UPDATING;
    scenes[7].maintenance_progress_percent = UINT8_C(77);
    scenes[8] = model(E87_UI_SCREEN_MAINTENANCE);
    scenes[8].maintenance_phase = E87_UI_MAINTENANCE_UPDATE_ERROR;
    scenes[9] = model(E87_UI_SCREEN_FACE);
    scenes[9].battery_overlay = true;
    scenes[9].battery_percent = UINT8_C(0);
    scenes[10] = model(E87_UI_SCREEN_PAIR_ME_NOW);
    scenes[10].battery_overlay = true;
    scenes[10].battery_percent = UINT8_C(100);
    scenes[10].charge_visual = E87_UI_CHARGE_FULL;
    scenes[11] = model(E87_UI_SCREEN_WAITING_FOR_PHONE);
    scenes[11].battery_overlay = true;
    scenes[11].battery_state = E87_UI_BATTERY_INVALID_STALE;
    scenes[11].battery_percent = UINT8_C(37);
    scenes[12] = model(E87_UI_SCREEN_PAIRING);
    scenes[12].countdown_seconds = UINT8_C(1);
    scenes[12].battery_overlay = true;
    scenes[12].battery_state = E87_UI_BATTERY_UNAVAILABLE_FAULT;

    for (scene_index = 0u;
         scene_index < sizeof(scenes) / sizeof(scenes[0]);
         ++scene_index) {
        uint16_t guarded[E87_TEST_STRIP_PIXELS + 2u];
        unsigned int strip;

        E87_ASSERT_TRUE(render_frame(&scenes[scene_index], frame_a, false, 1u));
        E87_ASSERT_TRUE(render_frame(&scenes[scene_index], frame_b, true, 2u));
        E87_ASSERT_TRUE(memcmp(frame_a, frame_b, sizeof(frame_a)) == 0);
        E87_ASSERT_TRUE(nonblack_pixels(frame_a) > 0u);
        for (strip = 0u; strip < E87_STRIP_COUNT; ++strip) {
            fill_words(
                guarded,
                E87_TEST_STRIP_PIXELS + 2u,
                UINT16_C(0xD39C));
            E87_ASSERT_EQ_U32(
                E87_TRANSIENT_RENDER_OK,
                e87_render_transient_strip(
                    &scenes[scene_index],
                    (uint8_t)strip,
                    &guarded[1],
                    E87_TEST_STRIP_PIXELS + 1u));
            E87_ASSERT_EQ_U32(UINT16_C(0xD39C), guarded[0]);
            E87_ASSERT_EQ_U32(
                UINT16_C(0xD39C), guarded[E87_TEST_STRIP_PIXELS + 1u]);
        }
    }
}

E87_TEST(countdowns_battery_faults_and_bolt_are_visibly_distinct)
{
    struct e87_render_model pairing_60 = model(E87_UI_SCREEN_PAIRING);
    struct e87_render_model pairing_1 = model(E87_UI_SCREEN_PAIRING);
    struct e87_render_model warning_3 = model(E87_UI_SCREEN_UPDATE_WARNING);
    struct e87_render_model warning_1 = model(E87_UI_SCREEN_UPDATE_WARNING);
    struct e87_render_model battery = model(E87_UI_SCREEN_WAITING_FOR_PHONE);

    pairing_60.countdown_seconds = UINT8_C(60);
    pairing_1.countdown_seconds = UINT8_C(1);
    warning_3.countdown_seconds = UINT8_C(3);
    warning_1.countdown_seconds = UINT8_C(1);
    E87_ASSERT_TRUE(render_frame(&pairing_60, frame_a, false, 1u));
    E87_ASSERT_TRUE(render_frame(&pairing_1, frame_b, false, 1u));
    E87_ASSERT_TRUE(memcmp(frame_a, frame_b, sizeof(frame_a)) != 0);
    E87_ASSERT_TRUE(render_frame(&warning_3, frame_a, false, 1u));
    E87_ASSERT_TRUE(render_frame(&warning_1, frame_b, false, 1u));
    E87_ASSERT_TRUE(memcmp(frame_a, frame_b, sizeof(frame_a)) != 0);

    battery.battery_overlay = true;
    battery.battery_state = E87_UI_BATTERY_VALID;
    battery.battery_percent = UINT8_C(50);
    battery.charge_visual = E87_UI_CHARGE_NONE;
    E87_ASSERT_TRUE(render_frame(&battery, frame_a, false, 1u));
    battery.charge_visual = E87_UI_CHARGE_CHARGING;
    E87_ASSERT_TRUE(render_frame(&battery, frame_b, false, 1u));
    E87_ASSERT_TRUE(memcmp(frame_a, frame_b, sizeof(frame_a)) != 0);
    battery.charge_visual = E87_UI_CHARGE_FULL;
    E87_ASSERT_TRUE(render_frame(&battery, frame_a, false, 1u));
    E87_ASSERT_TRUE(memcmp(frame_a, frame_b, sizeof(frame_a)) == 0);

    battery.charge_visual = E87_UI_CHARGE_NONE;
    battery.battery_state = E87_UI_BATTERY_INVALID_STALE;
    battery.battery_percent = UINT8_C(37);
    E87_ASSERT_TRUE(render_frame(&battery, frame_a, false, 1u));
    battery.battery_state = E87_UI_BATTERY_UNAVAILABLE_FAULT;
    battery.battery_percent = UINT8_C(0);
    E87_ASSERT_TRUE(render_frame(&battery, frame_b, false, 1u));
    E87_ASSERT_TRUE(memcmp(frame_a, frame_b, sizeof(frame_a)) != 0);
}

static const struct e87_test_case transient_renderer_cases[] = {
    E87_TEST_CASE(rejects_invalid_arguments_and_models_without_mutating_output),
    E87_TEST_CASE(panel_off_is_a_distinct_no_draw_result),
    E87_TEST_CASE(face_without_overlay_is_byte_exact_to_reviewed_normal_renderer),
    E87_TEST_CASE(every_visible_mode_is_strip_deterministic_and_writes_only_one_strip),
    E87_TEST_CASE(countdowns_battery_faults_and_bolt_are_visibly_distinct),
};

const struct e87_test_suite e87_test_suite = {
    "transient-screens",
    transient_renderer_cases,
    sizeof(transient_renderer_cases) / sizeof(transient_renderer_cases[0]),
};
