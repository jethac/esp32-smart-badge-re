#include "test_support.h"
#include "e87/e87_renderer.h"

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
static uint16_t frame_c[E87_TEST_FRAME_PIXELS];
static uint16_t frame_d[E87_TEST_FRAME_PIXELS];

static struct e87_metrics metrics(uint8_t day,
                                  uint8_t week,
                                  uint32_t credit_cents)
{
    struct e87_metrics result;

    result.day = day;
    result.week = week;
    result.credit_cents = credit_cents;
    return result;
}

static bool render_in_order(const struct e87_metrics *model,
                            uint16_t *out,
                            bool reverse,
                            unsigned int repetitions)
{
    unsigned int step;

    for (step = 0u; step < E87_STRIP_COUNT; ++step) {
        const uint8_t strip_index =
            (uint8_t)(reverse ? (E87_STRIP_COUNT - 1u - step) : step);
        unsigned int repetition;

        for (repetition = 0u; repetition < repetitions; ++repetition) {
            if (e87_render_normal_face_strip(
                    model,
                    strip_index,
                    out + (size_t)strip_index * E87_TEST_STRIP_PIXELS,
                    E87_TEST_STRIP_PIXELS) != E87_RENDER_OK) {
                return false;
            }
        }
    }
    return true;
}

static uint16_t frame_pixel(const uint16_t *frame,
                            unsigned int x,
                            unsigned int y)
{
    return frame[(size_t)y * E87_DISPLAY_WIDTH + x];
}

static void fill_words(uint16_t *words, size_t count, uint16_t value)
{
    size_t index;

    for (index = 0u; index < count; ++index) {
        words[index] = value;
    }
}

E87_TEST(credit_formats_1727_as_exact_ascii_without_float_or_locale)
{
    static const char expected[E87_RENDER_CREDIT_TEXT_BYTES] = {
        '$', '1', '7', '.', '2', '7', '\0'
    };
    char output[9];

    memset(output, 0xA5, sizeof(output));
    E87_ASSERT_EQ_U32(E87_RENDER_OK,
                      e87_render_credit_text(
                          E87_STATE_FIXED_CREDIT_CENTS,
                          output,
                          sizeof(output)));
    E87_ASSERT_TRUE(memcmp(output, expected, sizeof(expected)) == 0);
    E87_ASSERT_EQ_U32(UINT8_C(0xA5), (uint8_t)output[7]);
    E87_ASSERT_EQ_U32(UINT8_C(0xA5), (uint8_t)output[8]);
}

E87_TEST(credit_rejects_wrong_value_and_short_or_null_output_without_mutation)
{
    char output[9];
    char before[9];

    memset(output, 0x5A, sizeof(output));
    memcpy(before, output, sizeof(output));
    E87_ASSERT_EQ_U32(
        E87_RENDER_ERROR_METRICS,
        e87_render_credit_text(UINT32_C(1728), output, sizeof(output)));
    E87_ASSERT_TRUE(memcmp(output, before, sizeof(output)) == 0);
    E87_ASSERT_EQ_U32(
        E87_RENDER_ERROR_CAPACITY,
        e87_render_credit_text(E87_STATE_FIXED_CREDIT_CENTS,
                               output,
                               E87_RENDER_CREDIT_TEXT_BYTES - 1u));
    E87_ASSERT_TRUE(memcmp(output, before, sizeof(output)) == 0);
    E87_ASSERT_EQ_U32(
        E87_RENDER_ERROR_ARGUMENT,
        e87_render_credit_text(E87_STATE_FIXED_CREDIT_CENTS,
                               NULL,
                               E87_RENDER_CREDIT_TEXT_BYTES));
    E87_ASSERT_TRUE(memcmp(output, before, sizeof(output)) == 0);
}

E87_TEST(renderer_rejects_null_bad_strip_short_capacity_and_credit_without_mutation)
{
    struct e87_metrics valid =
        metrics(UINT8_C(50), UINT8_C(50), E87_STATE_FIXED_CREDIT_CENTS);
    struct e87_metrics wrong_credit =
        metrics(UINT8_C(50), UINT8_C(50), UINT32_C(1728));
    uint16_t output[E87_TEST_STRIP_PIXELS + 2u];
    uint16_t before[E87_TEST_STRIP_PIXELS + 2u];

    fill_words(output, E87_TEST_STRIP_PIXELS + 2u, UINT16_C(0xA55A));
    memcpy(before, output, sizeof(output));

    E87_ASSERT_EQ_U32(
        E87_RENDER_ERROR_ARGUMENT,
        e87_render_normal_face_strip(
            NULL, UINT8_C(0), &output[1], E87_TEST_STRIP_PIXELS));
    E87_ASSERT_TRUE(memcmp(output, before, sizeof(output)) == 0);
    E87_ASSERT_EQ_U32(
        E87_RENDER_ERROR_ARGUMENT,
        e87_render_normal_face_strip(
            &valid, UINT8_C(0), NULL, E87_TEST_STRIP_PIXELS));
    E87_ASSERT_TRUE(memcmp(output, before, sizeof(output)) == 0);
    E87_ASSERT_EQ_U32(
        E87_RENDER_ERROR_STRIP,
        e87_render_normal_face_strip(
            &valid, UINT8_C(12), &output[1], E87_TEST_STRIP_PIXELS));
    E87_ASSERT_TRUE(memcmp(output, before, sizeof(output)) == 0);
    E87_ASSERT_EQ_U32(
        E87_RENDER_ERROR_CAPACITY,
        e87_render_normal_face_strip(
            &valid, UINT8_C(0), &output[1], E87_TEST_STRIP_PIXELS - 1u));
    E87_ASSERT_TRUE(memcmp(output, before, sizeof(output)) == 0);
    E87_ASSERT_EQ_U32(
        E87_RENDER_ERROR_METRICS,
        e87_render_normal_face_strip(
            &wrong_credit, UINT8_C(0), &output[1], E87_TEST_STRIP_PIXELS));
    E87_ASSERT_TRUE(memcmp(output, before, sizeof(output)) == 0);
}

E87_TEST(renderer_writes_exactly_10800_words_and_preserves_both_canaries)
{
    struct e87_metrics model =
        metrics(UINT8_C(50), UINT8_C(50), E87_STATE_FIXED_CREDIT_CENTS);
    uint16_t guarded[E87_TEST_STRIP_PIXELS + 2u];

    E87_ASSERT_EQ_U32(UINT32_C(10800), E87_TEST_STRIP_PIXELS);
    fill_words(guarded, E87_TEST_STRIP_PIXELS + 2u, UINT16_C(0xD39C));
    E87_ASSERT_EQ_U32(
        E87_RENDER_OK,
        e87_render_normal_face_strip(
            &model, UINT8_C(0), &guarded[1], E87_TEST_STRIP_PIXELS + 1u));
    E87_ASSERT_EQ_U32(UINT16_C(0xD39C), guarded[0]);
    E87_ASSERT_EQ_U32(UINT16_C(0xD39C),
                      guarded[E87_TEST_STRIP_PIXELS + 1u]);
    E87_ASSERT_TRUE(guarded[1] != UINT16_C(0xD39C));
}

E87_TEST(strip_indices_cover_rows_0_through_359_once_in_thirty_row_tiles)
{
    struct e87_metrics model =
        metrics(UINT8_C(0), UINT8_C(0), E87_STATE_FIXED_CREDIT_CENTS);
    uint16_t strip[E87_TEST_STRIP_PIXELS];
    uint8_t rows[E87_DISPLAY_HEIGHT] = {0};
    unsigned int strip_index;
    unsigned int row;

    E87_ASSERT_EQ_U32(UINT32_C(12), E87_STRIP_COUNT);
    E87_ASSERT_EQ_U32(
        UINT32_C(330), (E87_STRIP_COUNT - 1u) * E87_STRIP_ROWS);
    E87_ASSERT_EQ_U32(
        UINT32_C(359),
        (E87_STRIP_COUNT - 1u) * E87_STRIP_ROWS + E87_STRIP_ROWS - 1u);
    for (strip_index = 0u; strip_index < E87_STRIP_COUNT; ++strip_index) {
        E87_ASSERT_EQ_U32(
            E87_RENDER_OK,
            e87_render_normal_face_strip(
                &model, (uint8_t)strip_index, strip, E87_TEST_STRIP_PIXELS));
        for (row = 0u; row < E87_STRIP_ROWS; ++row) {
            rows[strip_index * E87_STRIP_ROWS + row] += UINT8_C(1);
        }
    }
    for (row = 0u; row < E87_DISPLAY_HEIGHT; ++row) {
        E87_ASSERT_EQ_U32(UINT8_C(1), rows[row]);
    }
    E87_ASSERT_EQ_U32(UINT16_C(0x0000), strip[29u * E87_DISPLAY_WIDTH]);
}

E87_TEST(out_of_range_percentages_clamp_independently_to_100)
{
    struct e87_metrics day_255 =
        metrics(UINT8_C(255), UINT8_C(50), E87_STATE_FIXED_CREDIT_CENTS);
    struct e87_metrics day_100 =
        metrics(UINT8_C(100), UINT8_C(50), E87_STATE_FIXED_CREDIT_CENTS);
    struct e87_metrics week_255 =
        metrics(UINT8_C(50), UINT8_C(255), E87_STATE_FIXED_CREDIT_CENTS);
    struct e87_metrics week_100 =
        metrics(UINT8_C(50), UINT8_C(100), E87_STATE_FIXED_CREDIT_CENTS);

    E87_ASSERT_TRUE(render_in_order(&day_255, frame_a, false, 1u));
    E87_ASSERT_TRUE(render_in_order(&day_100, frame_b, false, 1u));
    E87_ASSERT_TRUE(memcmp(frame_a, frame_b, sizeof(frame_a)) == 0);
    E87_ASSERT_TRUE(render_in_order(&week_255, frame_a, false, 1u));
    E87_ASSERT_TRUE(render_in_order(&week_100, frame_b, false, 1u));
    E87_ASSERT_TRUE(memcmp(frame_a, frame_b, sizeof(frame_a)) == 0);
}

E87_TEST(zero_percent_has_no_active_arc_or_cap_and_has_active_colored_fixed_icons)
{
    struct e87_metrics model =
        metrics(UINT8_C(0), UINT8_C(0), E87_STATE_FIXED_CREDIT_CENTS);

    E87_ASSERT_TRUE(render_in_order(&model, frame_a, false, 1u));
    E87_ASSERT_EQ_U32(UINT16_C(0x2104), frame_pixel(frame_a, 340u, 180u));
    E87_ASSERT_EQ_U32(UINT16_C(0x2965), frame_pixel(frame_a, 310u, 180u));
    E87_ASSERT_EQ_U32(UINT16_C(0x2104), frame_pixel(frame_a, 180u, 11u));
    E87_ASSERT_EQ_U32(UINT16_C(0x2965), frame_pixel(frame_a, 180u, 41u));
    E87_ASSERT_EQ_U32(UINT16_C(0xBE18), frame_pixel(frame_a, 175u, 14u));
    E87_ASSERT_EQ_U32(UINT16_C(0xFFFF), frame_pixel(frame_a, 175u, 44u));
}

E87_TEST(fifty_percent_advances_clockwise_on_the_right_half)
{
    struct e87_metrics model =
        metrics(UINT8_C(50), UINT8_C(50), E87_STATE_FIXED_CREDIT_CENTS);

    E87_ASSERT_TRUE(render_in_order(&model, frame_a, false, 1u));
    E87_ASSERT_EQ_U32(UINT16_C(0xBE18), frame_pixel(frame_a, 340u, 180u));
    E87_ASSERT_EQ_U32(UINT16_C(0x2104), frame_pixel(frame_a, 20u, 180u));
    E87_ASSERT_EQ_U32(UINT16_C(0xFFFF), frame_pixel(frame_a, 310u, 180u));
    E87_ASSERT_EQ_U32(UINT16_C(0x2965), frame_pixel(frame_a, 50u, 180u));
}

E87_TEST(one_percent_has_round_start_and_endpoint_caps)
{
    struct e87_metrics model =
        metrics(UINT8_C(1), UINT8_C(1), E87_STATE_FIXED_CREDIT_CENTS);

    E87_ASSERT_TRUE(render_in_order(&model, frame_a, false, 1u));
    E87_ASSERT_EQ_U32(UINT16_C(0xBE18), frame_pixel(frame_a, 180u, 9u));
    E87_ASSERT_EQ_U32(UINT16_C(0xBE18), frame_pixel(frame_a, 171u, 20u));
    E87_ASSERT_EQ_U32(UINT16_C(0xBE18), frame_pixel(frame_a, 199u, 20u));
    E87_ASSERT_EQ_U32(UINT16_C(0xFFFF), frame_pixel(frame_a, 171u, 50u));
    E87_ASSERT_EQ_U32(UINT16_C(0xFFFF), frame_pixel(frame_a, 197u, 50u));
}

E87_TEST(ninety_nine_percent_pins_near_seam_cap_overlap_and_edge_wedge)
{
    struct e87_metrics model =
        metrics(UINT8_C(99), UINT8_C(99), E87_STATE_FIXED_CREDIT_CENTS);

    E87_ASSERT_TRUE(render_in_order(&model, frame_a, false, 1u));
    E87_ASSERT_EQ_U32(UINT16_C(0xBE18), frame_pixel(frame_a, 180u, 10u));
    E87_ASSERT_EQ_U32(UINT16_C(0xBE18), frame_pixel(frame_a, 170u, 10u));
    E87_ASSERT_EQ_U32(UINT16_C(0xBE18), frame_pixel(frame_a, 170u, 20u));
    E87_ASSERT_EQ_U32(UINT16_C(0xFFFF), frame_pixel(frame_a, 180u, 40u));
    E87_ASSERT_EQ_U32(UINT16_C(0xFFFF), frame_pixel(frame_a, 172u, 40u));
}

E87_TEST(one_hundred_percent_is_a_seamless_full_annulus)
{
    struct e87_metrics model =
        metrics(UINT8_C(100), UINT8_C(100), E87_STATE_FIXED_CREDIT_CENTS);

    E87_ASSERT_TRUE(render_in_order(&model, frame_a, false, 1u));
    E87_ASSERT_EQ_U32(UINT16_C(0xBE18), frame_pixel(frame_a, 170u, 20u));
    E87_ASSERT_EQ_U32(UINT16_C(0xBE18), frame_pixel(frame_a, 190u, 20u));
    E87_ASSERT_EQ_U32(UINT16_C(0xFFFF), frame_pixel(frame_a, 170u, 50u));
    E87_ASSERT_EQ_U32(UINT16_C(0xFFFF), frame_pixel(frame_a, 190u, 50u));
    E87_ASSERT_EQ_U32(UINT16_C(0xBE18), frame_pixel(frame_a, 340u, 180u));
    E87_ASSERT_EQ_U32(UINT16_C(0xFFFF), frame_pixel(frame_a, 310u, 180u));
}

E87_TEST(physical_circle_and_storage_corners_are_black)
{
    struct e87_metrics model =
        metrics(UINT8_C(100), UINT8_C(100), E87_STATE_FIXED_CREDIT_CENTS);

    E87_ASSERT_TRUE(render_in_order(&model, frame_a, false, 1u));
    E87_ASSERT_EQ_U32(UINT16_C(0x0000), frame_pixel(frame_a, 0u, 0u));
    E87_ASSERT_EQ_U32(UINT16_C(0x0000), frame_pixel(frame_a, 359u, 0u));
    E87_ASSERT_EQ_U32(UINT16_C(0x0000), frame_pixel(frame_a, 0u, 359u));
    E87_ASSERT_EQ_U32(UINT16_C(0x0000), frame_pixel(frame_a, 359u, 359u));
    E87_ASSERT_EQ_U32(UINT16_C(0x0000), frame_pixel(frame_a, 180u, 0u));
    E87_ASSERT_EQ_U32(UINT16_C(0x0000), frame_pixel(frame_a, 180u, 4u));
}

E87_TEST(four_sample_coverage_and_rgb565_truncation_match_literal_pixels)
{
    struct e87_metrics model =
        metrics(UINT8_C(0), UINT8_C(0), E87_STATE_FIXED_CREDIT_CENTS);

    E87_ASSERT_TRUE(render_in_order(&model, frame_a, false, 1u));
    E87_ASSERT_EQ_U32(UINT16_C(0x1082), frame_pixel(frame_a, 164u, 9u));
    E87_ASSERT_EQ_U32(UINT16_C(0x0861), frame_pixel(frame_a, 165u, 39u));
    E87_ASSERT_EQ_U32(UINT16_C(0x2104), frame_pixel(frame_a, 340u, 180u));
    E87_ASSERT_EQ_U32(UINT16_C(0x2965), frame_pixel(frame_a, 310u, 180u));
}

E87_TEST(icons_switch_independently_from_active_color_at_zero_to_black_at_one_and_stay_fixed)
{
    struct e87_metrics day_zero =
        metrics(UINT8_C(0), UINT8_C(1), E87_STATE_FIXED_CREDIT_CENTS);
    struct e87_metrics week_zero =
        metrics(UINT8_C(1), UINT8_C(0), E87_STATE_FIXED_CREDIT_CENTS);
    struct e87_metrics middle =
        metrics(UINT8_C(50), UINT8_C(50), E87_STATE_FIXED_CREDIT_CENTS);
    struct e87_metrics full =
        metrics(UINT8_C(100), UINT8_C(100), E87_STATE_FIXED_CREDIT_CENTS);

    E87_ASSERT_TRUE(render_in_order(&day_zero, frame_a, false, 1u));
    E87_ASSERT_EQ_U32(UINT16_C(0xBE18), frame_pixel(frame_a, 175u, 14u));
    E87_ASSERT_EQ_U32(UINT16_C(0x738E), frame_pixel(frame_a, 175u, 13u));
    E87_ASSERT_EQ_U32(UINT16_C(0x0000), frame_pixel(frame_a, 175u, 44u));
    E87_ASSERT_EQ_U32(UINT16_C(0x8410), frame_pixel(frame_a, 175u, 43u));

    E87_ASSERT_TRUE(render_in_order(&week_zero, frame_a, false, 1u));
    E87_ASSERT_EQ_U32(UINT16_C(0x0000), frame_pixel(frame_a, 175u, 14u));
    E87_ASSERT_EQ_U32(UINT16_C(0x630C), frame_pixel(frame_a, 175u, 13u));
    E87_ASSERT_EQ_U32(UINT16_C(0xFFFF), frame_pixel(frame_a, 175u, 44u));
    E87_ASSERT_EQ_U32(UINT16_C(0x94B2), frame_pixel(frame_a, 175u, 43u));

    E87_ASSERT_TRUE(render_in_order(&middle, frame_a, false, 1u));
    E87_ASSERT_EQ_U32(UINT16_C(0x0000), frame_pixel(frame_a, 175u, 14u));
    E87_ASSERT_EQ_U32(UINT16_C(0x630C), frame_pixel(frame_a, 175u, 13u));
    E87_ASSERT_EQ_U32(UINT16_C(0x0000), frame_pixel(frame_a, 175u, 44u));
    E87_ASSERT_EQ_U32(UINT16_C(0x8410), frame_pixel(frame_a, 175u, 43u));

    E87_ASSERT_TRUE(render_in_order(&full, frame_a, false, 1u));
    E87_ASSERT_EQ_U32(UINT16_C(0x0000), frame_pixel(frame_a, 175u, 14u));
    E87_ASSERT_EQ_U32(UINT16_C(0x630C), frame_pixel(frame_a, 175u, 13u));
    E87_ASSERT_EQ_U32(UINT16_C(0x0000), frame_pixel(frame_a, 175u, 44u));
    E87_ASSERT_EQ_U32(UINT16_C(0x8410), frame_pixel(frame_a, 175u, 43u));
}

E87_TEST(devin_mask_is_white_and_centered_at_180_166)
{
    struct e87_metrics model =
        metrics(UINT8_C(0), UINT8_C(0), E87_STATE_FIXED_CREDIT_CENTS);

    E87_ASSERT_TRUE(render_in_order(&model, frame_a, false, 1u));
    E87_ASSERT_EQ_U32(UINT16_C(0xFFFF), frame_pixel(frame_a, 150u, 119u));
    E87_ASSERT_EQ_U32(UINT16_C(0x0841), frame_pixel(frame_a, 149u, 118u));
    E87_ASSERT_EQ_U32(UINT16_C(0x0000), frame_pixel(frame_a, 228u, 166u));
    E87_ASSERT_EQ_U32(UINT16_C(0x0000), frame_pixel(frame_a, 180u, 214u));
}

E87_TEST(credit_mask_is_white_and_centered_at_180_240)
{
    struct e87_metrics model =
        metrics(UINT8_C(0), UINT8_C(0), E87_STATE_FIXED_CREDIT_CENTS);

    E87_ASSERT_TRUE(render_in_order(&model, frame_a, false, 1u));
    E87_ASSERT_EQ_U32(UINT16_C(0xFFFF), frame_pixel(frame_a, 141u, 227u));
    E87_ASSERT_EQ_U32(UINT16_C(0x2124), frame_pixel(frame_a, 140u, 226u));
    E87_ASSERT_EQ_U32(UINT16_C(0x0000), frame_pixel(frame_a, 133u, 240u));
    E87_ASSERT_EQ_U32(UINT16_C(0x0000), frame_pixel(frame_a, 226u, 240u));
}

E87_TEST(layer_order_is_track_arc_icons_devin_credit)
{
    struct e87_metrics model =
        metrics(UINT8_C(1), UINT8_C(1), E87_STATE_FIXED_CREDIT_CENTS);

    E87_ASSERT_TRUE(render_in_order(&model, frame_a, false, 1u));
    E87_ASSERT_EQ_U32(UINT16_C(0x630C), frame_pixel(frame_a, 175u, 13u));
    E87_ASSERT_EQ_U32(UINT16_C(0x8410), frame_pixel(frame_a, 175u, 43u));
    E87_ASSERT_EQ_U32(UINT16_C(0xFFFF), frame_pixel(frame_a, 150u, 119u));
    E87_ASSERT_EQ_U32(UINT16_C(0xFFFF), frame_pixel(frame_a, 141u, 227u));
}

E87_TEST(strip_rendering_is_repeatable_reentrant_and_order_independent)
{
    struct e87_metrics first =
        metrics(UINT8_C(1), UINT8_C(99), E87_STATE_FIXED_CREDIT_CENTS);
    struct e87_metrics second =
        metrics(UINT8_C(99), UINT8_C(1), E87_STATE_FIXED_CREDIT_CENTS);
    unsigned int step;

    E87_ASSERT_TRUE(render_in_order(&first, frame_a, false, 1u));
    E87_ASSERT_TRUE(render_in_order(&second, frame_b, true, 1u));

    for (step = 0u; step < E87_STRIP_COUNT; ++step) {
        const uint8_t first_index = (uint8_t)step;
        const uint8_t second_index =
            (uint8_t)(E87_STRIP_COUNT - 1u - step);

        E87_ASSERT_EQ_U32(
            E87_RENDER_OK,
            e87_render_normal_face_strip(
                &first,
                first_index,
                frame_c + (size_t)first_index * E87_TEST_STRIP_PIXELS,
                E87_TEST_STRIP_PIXELS));
        E87_ASSERT_EQ_U32(
            E87_RENDER_OK,
            e87_render_normal_face_strip(
                &second,
                second_index,
                frame_d + (size_t)second_index * E87_TEST_STRIP_PIXELS,
                E87_TEST_STRIP_PIXELS));
        E87_ASSERT_EQ_U32(
            E87_RENDER_OK,
            e87_render_normal_face_strip(
                &first,
                first_index,
                frame_c + (size_t)first_index * E87_TEST_STRIP_PIXELS,
                E87_TEST_STRIP_PIXELS));
    }

    E87_ASSERT_TRUE(memcmp(frame_a, frame_c, sizeof(frame_a)) == 0);
    E87_ASSERT_TRUE(memcmp(frame_b, frame_d, sizeof(frame_b)) == 0);
}

static const struct e87_test_case renderer_cases[] = {
    E87_TEST_CASE(credit_formats_1727_as_exact_ascii_without_float_or_locale),
    E87_TEST_CASE(credit_rejects_wrong_value_and_short_or_null_output_without_mutation),
    E87_TEST_CASE(renderer_rejects_null_bad_strip_short_capacity_and_credit_without_mutation),
    E87_TEST_CASE(renderer_writes_exactly_10800_words_and_preserves_both_canaries),
    E87_TEST_CASE(strip_indices_cover_rows_0_through_359_once_in_thirty_row_tiles),
    E87_TEST_CASE(out_of_range_percentages_clamp_independently_to_100),
    E87_TEST_CASE(zero_percent_has_no_active_arc_or_cap_and_has_active_colored_fixed_icons),
    E87_TEST_CASE(fifty_percent_advances_clockwise_on_the_right_half),
    E87_TEST_CASE(one_percent_has_round_start_and_endpoint_caps),
    E87_TEST_CASE(ninety_nine_percent_pins_near_seam_cap_overlap_and_edge_wedge),
    E87_TEST_CASE(one_hundred_percent_is_a_seamless_full_annulus),
    E87_TEST_CASE(physical_circle_and_storage_corners_are_black),
    E87_TEST_CASE(four_sample_coverage_and_rgb565_truncation_match_literal_pixels),
    E87_TEST_CASE(icons_switch_independently_from_active_color_at_zero_to_black_at_one_and_stay_fixed),
    E87_TEST_CASE(devin_mask_is_white_and_centered_at_180_166),
    E87_TEST_CASE(credit_mask_is_white_and_centered_at_180_240),
    E87_TEST_CASE(layer_order_is_track_arc_icons_devin_credit),
    E87_TEST_CASE(strip_rendering_is_repeatable_reentrant_and_order_independent),
};

const struct e87_test_suite e87_test_suite = {
    "normal-face",
    renderer_cases,
    sizeof(renderer_cases) / sizeof(renderer_cases[0]),
};
