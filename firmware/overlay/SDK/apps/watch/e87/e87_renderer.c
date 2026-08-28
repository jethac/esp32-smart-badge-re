#include "e87/e87_renderer.h"
#include "e87_assets.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

enum {
    E87_FACE_CENTER = 180,
    E87_PHYSICAL_RADIUS = 180,
    E87_DAY_RADIUS = 160,
    E87_DAY_INNER_RADIUS = 149,
    E87_DAY_OUTER_RADIUS = 171,
    E87_WEEK_RADIUS = 130,
    E87_WEEK_INNER_RADIUS = 119,
    E87_WEEK_OUTER_RADIUS = 141,
    E87_CAP_RADIUS = 11,
    E87_Q2_SCALE = 4,
    E87_Q16_FROM_Q2_SHIFT = 14,
    E87_ALPHA_FULL = 255
};

struct e87_rgb888 {
    uint16_t red;
    uint16_t green;
    uint16_t blue;
};

static bool e87_sample_in_physical_circle_q2(int32_t dx_q2,
                                              int32_t dy_q2)
{
    const int64_t distance =
        (int64_t)dx_q2 * dx_q2 + (int64_t)dy_q2 * dy_q2;
    const int64_t limit =
        (int64_t)(E87_PHYSICAL_RADIUS * E87_Q2_SCALE) *
        (E87_PHYSICAL_RADIUS * E87_Q2_SCALE);

    return distance <= limit;
}

static bool e87_sample_in_annulus_after_clip_q2(int32_t dx_q2,
                                                int32_t dy_q2,
                                                int32_t inner_radius,
                                                int32_t outer_radius)
{
    const int64_t distance =
        (int64_t)dx_q2 * dx_q2 + (int64_t)dy_q2 * dy_q2;
    const int64_t inner =
        (int64_t)(inner_radius * E87_Q2_SCALE) *
        (inner_radius * E87_Q2_SCALE);
    const int64_t outer =
        (int64_t)(outer_radius * E87_Q2_SCALE) *
        (outer_radius * E87_Q2_SCALE);

    return distance >= inner && distance <= outer;
}

static bool e87_sample_in_track_q2(int32_t dx_q2,
                                   int32_t dy_q2,
                                   int32_t inner_radius,
                                   int32_t outer_radius)
{
    if (!e87_sample_in_physical_circle_q2(dx_q2, dy_q2)) {
        return false;
    }
    return e87_sample_in_annulus_after_clip_q2(
        dx_q2, dy_q2, inner_radius, outer_radius);
}

static bool e87_sample_in_cap_q16(int32_t absolute_x_q2,
                                  int32_t absolute_y_q2,
                                  int32_t center_x_q16,
                                  int32_t center_y_q16)
{
    const int64_t sample_x_q16 =
        (int64_t)absolute_x_q2 << E87_Q16_FROM_Q2_SHIFT;
    const int64_t sample_y_q16 =
        (int64_t)absolute_y_q2 << E87_Q16_FROM_Q2_SHIFT;
    const int64_t dx_q16 = sample_x_q16 - center_x_q16;
    const int64_t dy_q16 = sample_y_q16 - center_y_q16;
    const int64_t limit =
        (int64_t)(E87_CAP_RADIUS << 16) * (E87_CAP_RADIUS << 16);

    return dx_q16 * dx_q16 + dy_q16 * dy_q16 <= limit;
}

static bool e87_sample_in_active_q2(int32_t absolute_x_q2,
                                    int32_t absolute_y_q2,
                                    int32_t dx_q2,
                                    int32_t dy_q2,
                                    uint8_t percent,
                                    int32_t radius,
                                    int32_t inner_radius,
                                    int32_t outer_radius)
{
    int32_t endpoint_cos_q16;
    int32_t endpoint_sin_q16;
    bool in_body;
    bool in_start_cap;
    bool in_end_cap;
    int32_t start_x_q16;
    int32_t start_y_q16;
    int32_t end_x_q16;
    int32_t end_y_q16;

    if (!e87_sample_in_physical_circle_q2(dx_q2, dy_q2)) {
        return false;
    }
    if (percent == UINT8_C(0)) {
        return false;
    }
    if (percent == UINT8_C(100)) {
        return e87_sample_in_annulus_after_clip_q2(
            dx_q2, dy_q2, inner_radius, outer_radius);
    }

    endpoint_cos_q16 = e87_ring_cos_q16[percent];
    endpoint_sin_q16 = e87_ring_sin_q16[percent];
    in_body = false;
    if (e87_sample_in_annulus_after_clip_q2(
            dx_q2, dy_q2, inner_radius, outer_radius)) {
        const int32_t a = -dy_q2;
        const int32_t b = dx_q2;
        const bool sample_half = b < 0;
        const bool endpoint_half = endpoint_sin_q16 < 0;
        const int64_t cross =
            (int64_t)a * endpoint_sin_q16 -
            (int64_t)b * endpoint_cos_q16;

        in_body = sample_half < endpoint_half ||
                  (sample_half == endpoint_half && cross >= 0);
    }

    start_x_q16 = E87_FACE_CENTER << 16;
    start_y_q16 = (E87_FACE_CENTER - radius) << 16;
    end_x_q16 =
        (E87_FACE_CENTER << 16) + radius * endpoint_sin_q16;
    end_y_q16 =
        (E87_FACE_CENTER << 16) - radius * endpoint_cos_q16;

    in_start_cap = e87_sample_in_cap_q16(
        absolute_x_q2, absolute_y_q2, start_x_q16, start_y_q16);
    in_end_cap = e87_sample_in_cap_q16(
        absolute_x_q2, absolute_y_q2, end_x_q16, end_y_q16);
    return in_body || in_start_cap || in_end_cap;
}

static uint8_t e87_coverage_alpha(unsigned int count)
{
    return (uint8_t)((count * E87_ALPHA_FULL + 2u) / 4u);
}

static uint8_t e87_track_alpha(unsigned int x,
                               unsigned int y,
                               int32_t inner_radius,
                               int32_t outer_radius)
{
    static const uint8_t offsets[2] = {UINT8_C(1), UINT8_C(3)};
    unsigned int inside = 0u;
    unsigned int x_sample;
    unsigned int y_sample;

    for (y_sample = 0u; y_sample < 2u; ++y_sample) {
        for (x_sample = 0u; x_sample < 2u; ++x_sample) {
            const int32_t dx_q2 =
                ((int32_t)x - E87_FACE_CENTER) * E87_Q2_SCALE +
                offsets[x_sample];
            const int32_t dy_q2 =
                ((int32_t)y - E87_FACE_CENTER) * E87_Q2_SCALE +
                offsets[y_sample];

            if (e87_sample_in_track_q2(
                    dx_q2, dy_q2, inner_radius, outer_radius)) {
                ++inside;
            }
        }
    }
    return e87_coverage_alpha(inside);
}

static uint8_t e87_active_alpha(unsigned int x,
                                unsigned int y,
                                uint8_t percent,
                                int32_t radius,
                                int32_t inner_radius,
                                int32_t outer_radius)
{
    static const uint8_t offsets[2] = {UINT8_C(1), UINT8_C(3)};
    unsigned int inside = 0u;
    unsigned int x_sample;
    unsigned int y_sample;

    for (y_sample = 0u; y_sample < 2u; ++y_sample) {
        for (x_sample = 0u; x_sample < 2u; ++x_sample) {
            const int32_t absolute_x_q2 =
                (int32_t)x * E87_Q2_SCALE + offsets[x_sample];
            const int32_t absolute_y_q2 =
                (int32_t)y * E87_Q2_SCALE + offsets[y_sample];
            const int32_t dx_q2 =
                absolute_x_q2 - E87_FACE_CENTER * E87_Q2_SCALE;
            const int32_t dy_q2 =
                absolute_y_q2 - E87_FACE_CENTER * E87_Q2_SCALE;

            if (e87_sample_in_active_q2(
                    absolute_x_q2,
                    absolute_y_q2,
                    dx_q2,
                    dy_q2,
                    percent,
                    radius,
                    inner_radius,
                    outer_radius)) {
                ++inside;
            }
        }
    }
    return e87_coverage_alpha(inside);
}

static void e87_blend(struct e87_rgb888 *destination,
                      uint8_t source_red,
                      uint8_t source_green,
                      uint8_t source_blue,
                      uint8_t alpha)
{
    destination->red =
        (uint16_t)((source_red * alpha +
                    destination->red * (E87_ALPHA_FULL - alpha) +
                    127u) /
                   E87_ALPHA_FULL);
    destination->green =
        (uint16_t)((source_green * alpha +
                    destination->green * (E87_ALPHA_FULL - alpha) +
                    127u) /
                   E87_ALPHA_FULL);
    destination->blue =
        (uint16_t)((source_blue * alpha +
                    destination->blue * (E87_ALPHA_FULL - alpha) +
                    127u) /
                   E87_ALPHA_FULL);
}

static void e87_blend_asset(struct e87_rgb888 *destination,
                            unsigned int x,
                            unsigned int y,
                            unsigned int left,
                            unsigned int top,
                            const struct e87_alpha_asset *asset,
                            uint8_t source_red,
                            uint8_t source_green,
                            uint8_t source_blue)
{
    unsigned int local_x;
    unsigned int local_y;
    uint8_t alpha;

    if (x < left || y < top ||
        x >= left + asset->width || y >= top + asset->height) {
        return;
    }
    local_x = x - left;
    local_y = y - top;
    alpha = asset->alpha[(size_t)local_y * asset->width + local_x];
    e87_blend(
        destination, source_red, source_green, source_blue, alpha);
}

static uint16_t e87_quantize_rgb565(const struct e87_rgb888 *color)
{
    return (uint16_t)(((color->red >> 3) << 11) |
                      ((color->green >> 2) << 5) |
                      (color->blue >> 3));
}

static uint8_t e87_clamp_percent(uint8_t percent)
{
    return percent > UINT8_C(100) ? UINT8_C(100) : percent;
}

static uint16_t e87_render_pixel(unsigned int x,
                                 unsigned int y,
                                 uint8_t day,
                                 uint8_t week)
{
    struct e87_rgb888 color = {UINT16_C(0), UINT16_C(0), UINT16_C(0)};
    uint8_t alpha;
    uint8_t icon_red;
    uint8_t icon_green;
    uint8_t icon_blue;
    unsigned int credit_left;
    unsigned int credit_top;

    alpha = e87_track_alpha(
        x, y, E87_DAY_INNER_RADIUS, E87_DAY_OUTER_RADIUS);
    e87_blend(&color, UINT8_C(34), UINT8_C(35), UINT8_C(36), alpha);

    alpha = e87_track_alpha(
        x, y, E87_WEEK_INNER_RADIUS, E87_WEEK_OUTER_RADIUS);
    e87_blend(&color, UINT8_C(46), UINT8_C(46), UINT8_C(46), alpha);

    alpha = e87_active_alpha(
        x,
        y,
        day,
        E87_DAY_RADIUS,
        E87_DAY_INNER_RADIUS,
        E87_DAY_OUTER_RADIUS);
    e87_blend(&color, UINT8_C(191), UINT8_C(195), UINT8_C(199), alpha);

    alpha = e87_active_alpha(
        x,
        y,
        week,
        E87_WEEK_RADIUS,
        E87_WEEK_INNER_RADIUS,
        E87_WEEK_OUTER_RADIUS);
    e87_blend(&color, UINT8_C(255), UINT8_C(255), UINT8_C(255), alpha);

    if (day == UINT8_C(0)) {
        icon_red = UINT8_C(191);
        icon_green = UINT8_C(195);
        icon_blue = UINT8_C(199);
    } else {
        icon_red = UINT8_C(0);
        icon_green = UINT8_C(0);
        icon_blue = UINT8_C(0);
    }
    e87_blend_asset(
        &color,
        x,
        y,
        171u,
        11u,
        &e87_asset_today,
        icon_red,
        icon_green,
        icon_blue);

    if (week == UINT8_C(0)) {
        icon_red = UINT8_C(255);
        icon_green = UINT8_C(255);
        icon_blue = UINT8_C(255);
    } else {
        icon_red = UINT8_C(0);
        icon_green = UINT8_C(0);
        icon_blue = UINT8_C(0);
    }
    e87_blend_asset(
        &color,
        x,
        y,
        171u,
        41u,
        &e87_asset_date_range,
        icon_red,
        icon_green,
        icon_blue);

    e87_blend_asset(
        &color,
        x,
        y,
        132u,
        118u,
        &e87_asset_devin,
        UINT8_C(255),
        UINT8_C(255),
        UINT8_C(255));

    credit_left = E87_FACE_CENTER - e87_asset_credit_1727.width / 2u;
    credit_top = 240u - e87_asset_credit_1727.height / 2u;
    e87_blend_asset(
        &color,
        x,
        y,
        credit_left,
        credit_top,
        &e87_asset_credit_1727,
        UINT8_C(255),
        UINT8_C(255),
        UINT8_C(255));

    return e87_quantize_rgb565(&color);
}

enum e87_render_result
e87_render_credit_text(uint32_t credit_cents,
                       char *out,
                       size_t out_size)
{
    uint32_t dollars;
    uint32_t cents;

    if (out == NULL) {
        return E87_RENDER_ERROR_ARGUMENT;
    }
    if (credit_cents != E87_STATE_FIXED_CREDIT_CENTS) {
        return E87_RENDER_ERROR_METRICS;
    }
    if (out_size < E87_RENDER_CREDIT_TEXT_BYTES) {
        return E87_RENDER_ERROR_CAPACITY;
    }

    dollars = credit_cents / UINT32_C(100);
    cents = credit_cents % UINT32_C(100);
    out[0] = '$';
    out[1] = (char)('0' + dollars / UINT32_C(10));
    out[2] = (char)('0' + dollars % UINT32_C(10));
    out[3] = '.';
    out[4] = (char)('0' + cents / UINT32_C(10));
    out[5] = (char)('0' + cents % UINT32_C(10));
    out[6] = '\0';
    return E87_RENDER_OK;
}

enum e87_render_result
e87_render_normal_face_strip(const struct e87_metrics *metrics,
                             uint8_t strip_index,
                             uint16_t *out_pixels,
                             size_t out_pixel_count)
{
    char credit_text[E87_RENDER_CREDIT_TEXT_BYTES];
    uint8_t day;
    uint8_t week;
    unsigned int local_y;
    unsigned int x;

    if (metrics == NULL || out_pixels == NULL) {
        return E87_RENDER_ERROR_ARGUMENT;
    }
    if (strip_index >= E87_STRIP_COUNT) {
        return E87_RENDER_ERROR_STRIP;
    }
    if (out_pixel_count < (size_t)E87_DISPLAY_WIDTH * E87_STRIP_ROWS) {
        return E87_RENDER_ERROR_CAPACITY;
    }
    if (e87_render_credit_text(
            metrics->credit_cents,
            credit_text,
            sizeof(credit_text)) != E87_RENDER_OK) {
        return E87_RENDER_ERROR_METRICS;
    }

    day = e87_clamp_percent(metrics->day);
    week = e87_clamp_percent(metrics->week);
    for (local_y = 0u; local_y < E87_STRIP_ROWS; ++local_y) {
        const unsigned int y =
            (unsigned int)strip_index * E87_STRIP_ROWS + local_y;

        for (x = 0u; x < E87_DISPLAY_WIDTH; ++x) {
            out_pixels[(size_t)local_y * E87_DISPLAY_WIDTH + x] =
                e87_render_pixel(x, y, day, week);
        }
    }
    return E87_RENDER_OK;
}
