#include "e87/e87_transient_renderer.h"
#include "e87_assets.h"
#include "e87_transient_assets.h"

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
    E87_ALPHA_FULL = 255,
    E87_BACKGROUND_RED = 0,
    E87_BACKGROUND_GREEN = 0,
    E87_BACKGROUND_BLUE = 0,
    E87_OVERLAY_ALPHA = 191,
    E87_PRIMARY_RED = 255,
    E87_PRIMARY_GREEN = 255,
    E87_PRIMARY_BLUE = 255,
    E87_SECONDARY_RED = 191,
    E87_SECONDARY_GREEN = 195,
    E87_SECONDARY_BLUE = 199,
    E87_BIG_GLYPH_SCALE = 2,
    E87_BOLT_GAP = 8,
    E87_BOLT_TOP_OFFSET_Y = -31,
    E87_BATTERY_BIG_BASELINE_Y = 195,
    E87_BATTERY_STATUS_BASELINE_Y = 245,
    E87_MAINTENANCE_TITLE_BASELINE_Y = 105,
    E87_MAINTENANCE_PHASE_BASELINE_Y = 145,
    E87_MAINTENANCE_BATTERY_BASELINE_Y = 210,
    E87_MAINTENANCE_BATTERY_STATUS_BASELINE_Y = 255,
    E87_MAINTENANCE_PROGRESS_BASELINE_Y = 300,
    E87_PAIR_ME_PRIMARY_BASELINE_Y = 170,
    E87_PAIR_ME_HINT_BASELINE_Y = 215,
    E87_PAIRING_PRIMARY_BASELINE_Y = 165,
    E87_PAIRING_COUNTDOWN_BASELINE_Y = 220,
    E87_PAIRING_COUNTDOWN_GLYPH_SCALE = 2,
    E87_UPDATE_WARNING_LINE1_BASELINE_Y = 145,
    E87_UPDATE_WARNING_LINE2_BASELINE_Y = 185,
    E87_UPDATE_WARNING_COUNTDOWN_BASELINE_Y = 240,
    E87_UPDATE_WARNING_COUNTDOWN_GLYPH_SCALE = 2,
    E87_WAITING_PRIMARY_BASELINE_Y = 190,
    E87_TEXT_RUN_MAX_GLYPHS = 20,
    E87_DRAW_PLAN_MAX_ITEMS = 64
};

struct e87_rgb888 {
    uint16_t red;
    uint16_t green;
    uint16_t blue;
};

enum e87_draw_item_kind {
    E87_DRAW_ITEM_GLYPH = 0,
    E87_DRAW_ITEM_ASSET = 1
};

struct e87_draw_item {
    enum e87_draw_item_kind kind;
    union {
        const struct e87_bitmap_glyph *glyph;
        const struct e87_alpha_asset *asset;
    } source;
    int32_t left;
    int32_t top;
    uint8_t scale;
    uint8_t red;
    uint8_t green;
    uint8_t blue;
};

struct e87_draw_plan {
    struct e87_draw_item items[E87_DRAW_PLAN_MAX_ITEMS];
    size_t item_count;
    int32_t strip_top;
    int32_t strip_bottom;
};

struct e87_text_run {
    const struct e87_bitmap_glyph *glyphs[E87_TEXT_RUN_MAX_GLYPHS];
    size_t glyph_count;
    uint32_t width_q3;
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
    bool in_body = false;
    int32_t start_x_q16;
    int32_t start_y_q16;
    int32_t end_x_q16;
    int32_t end_y_q16;

    if (!e87_sample_in_physical_circle_q2(dx_q2, dy_q2) ||
        percent == UINT8_C(0)) {
        return false;
    }
    if (percent == UINT8_C(100)) {
        return e87_sample_in_annulus_after_clip_q2(
            dx_q2, dy_q2, inner_radius, outer_radius);
    }

    endpoint_cos_q16 = e87_ring_cos_q16[percent];
    endpoint_sin_q16 = e87_ring_sin_q16[percent];
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
    return in_body ||
           e87_sample_in_cap_q16(
               absolute_x_q2, absolute_y_q2, start_x_q16, start_y_q16) ||
           e87_sample_in_cap_q16(
               absolute_x_q2, absolute_y_q2, end_x_q16, end_y_q16);
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

    if (x < left || y < top ||
        x >= left + asset->width || y >= top + asset->height) {
        return;
    }
    local_x = x - left;
    local_y = y - top;
    e87_blend(
        destination,
        source_red,
        source_green,
        source_blue,
        asset->alpha[(size_t)local_y * asset->width + local_x]);
}

static uint16_t e87_quantize_rgb565(const struct e87_rgb888 *color)
{
    return (uint16_t)(((color->red >> 3) << 11) |
                      ((color->green >> 2) << 5) |
                      (color->blue >> 3));
}

static struct e87_rgb888 e87_normal_face_color(unsigned int x,
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
        x, y, day, E87_DAY_RADIUS,
        E87_DAY_INNER_RADIUS, E87_DAY_OUTER_RADIUS);
    e87_blend(&color, UINT8_C(191), UINT8_C(195), UINT8_C(199), alpha);
    alpha = e87_active_alpha(
        x, y, week, E87_WEEK_RADIUS,
        E87_WEEK_INNER_RADIUS, E87_WEEK_OUTER_RADIUS);
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
        &color, x, y, 171u, 11u, &e87_asset_today,
        icon_red, icon_green, icon_blue);
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
        &color, x, y, 171u, 41u, &e87_asset_date_range,
        icon_red, icon_green, icon_blue);
    e87_blend_asset(
        &color, x, y, 132u, 118u, &e87_asset_devin,
        UINT8_C(255), UINT8_C(255), UINT8_C(255));
    credit_left = E87_FACE_CENTER - e87_asset_credit_1727.width / 2u;
    credit_top = 240u - e87_asset_credit_1727.height / 2u;
    e87_blend_asset(
        &color, x, y, credit_left, credit_top,
        &e87_asset_credit_1727,
        UINT8_C(255), UINT8_C(255), UINT8_C(255));
    return color;
}

static const struct e87_bitmap_glyph *e87_glyph_for(char character)
{
    size_t index;

    for (index = 0u; index < E87_TRANSIENT_GLYPH_COUNT; ++index) {
        if (e87_transient_glyphs[index].ascii ==
            (uint8_t)(unsigned char)character) {
            return &e87_transient_glyphs[index];
        }
    }
    return NULL;
}

static void e87_draw_plan_init(struct e87_draw_plan *plan,
                               uint8_t strip_index)
{
    plan->item_count = 0u;
    plan->strip_top = (int32_t)strip_index * E87_STRIP_ROWS;
    plan->strip_bottom = plan->strip_top + E87_STRIP_ROWS;
}

static bool e87_prepare_text_run(const char *text,
                                 uint8_t scale,
                                 struct e87_text_run *run)
{
    size_t index = 0u;

    run->glyph_count = 0u;
    run->width_q3 = UINT32_C(0);
    while (text[index] != '\0') {
        const struct e87_bitmap_glyph *glyph;

        if (run->glyph_count >= E87_TEXT_RUN_MAX_GLYPHS) {
            return false;
        }
        glyph = e87_glyph_for(text[index]);
        if (glyph == NULL) {
            return false;
        }
        run->glyphs[run->glyph_count++] = glyph;
        run->width_q3 += (uint32_t)glyph->advance_q3 * scale;
        ++index;
    }
    return true;
}

static bool e87_draw_plan_add_item(struct e87_draw_plan *plan,
                                   const struct e87_draw_item *item,
                                   int32_t height)
{
    if (item->top >= plan->strip_bottom ||
        item->top + height <= plan->strip_top) {
        return true;
    }
    if (plan->item_count >= E87_DRAW_PLAN_MAX_ITEMS) {
        return false;
    }
    plan->items[plan->item_count++] = *item;
    return true;
}

static bool e87_draw_plan_add_run(struct e87_draw_plan *plan,
                                  const struct e87_text_run *run,
                                  int32_t left_q3,
                                  int32_t baseline_y,
                                  uint8_t scale,
                                  uint8_t red,
                                  uint8_t green,
                                  uint8_t blue)
{
    int32_t pen_q3 = left_q3;
    size_t index;

    for (index = 0u; index < run->glyph_count; ++index) {
        const struct e87_bitmap_glyph *glyph = run->glyphs[index];
        struct e87_draw_item item;

        item.kind = E87_DRAW_ITEM_GLYPH;
        item.source.glyph = glyph;
        item.left = pen_q3 / 8 + (int32_t)glyph->bearing_x * scale;
        item.top = baseline_y + (int32_t)glyph->bearing_y * scale;
        item.scale = scale;
        item.red = red;
        item.green = green;
        item.blue = blue;
        if (glyph->width != UINT16_C(0) &&
            glyph->height != UINT16_C(0) &&
            !e87_draw_plan_add_item(
                plan, &item, (int32_t)glyph->height * scale)) {
            return false;
        }
        pen_q3 += (int32_t)glyph->advance_q3 * scale;
    }
    return true;
}

static bool e87_draw_plan_add_centered_text(struct e87_draw_plan *plan,
                                            const char *text,
                                            int32_t baseline_y,
                                            uint8_t scale,
                                            uint8_t red,
                                            uint8_t green,
                                            uint8_t blue)
{
    struct e87_text_run run;
    int32_t left_q3;

    if (!e87_prepare_text_run(text, scale, &run)) {
        return false;
    }
    left_q3 = E87_FACE_CENTER * 8 - (int32_t)run.width_q3 / 2;
    return e87_draw_plan_add_run(
        plan, &run, left_q3, baseline_y, scale, red, green, blue);
}

static bool e87_draw_plan_add_asset(struct e87_draw_plan *plan,
                                    const struct e87_alpha_asset *asset,
                                    int32_t left,
                                    int32_t top,
                                    uint8_t red,
                                    uint8_t green,
                                    uint8_t blue)
{
    struct e87_draw_item item;

    item.kind = E87_DRAW_ITEM_ASSET;
    item.source.asset = asset;
    item.left = left;
    item.top = top;
    item.scale = UINT8_C(1);
    item.red = red;
    item.green = green;
    item.blue = blue;
    return e87_draw_plan_add_item(plan, &item, asset->height);
}

static void e87_blend_plan_pixel(struct e87_rgb888 *color,
                                 unsigned int x,
                                 unsigned int y,
                                 const struct e87_draw_plan *plan)
{
    size_t index;

    for (index = 0u; index < plan->item_count; ++index) {
        const struct e87_draw_item *item = &plan->items[index];

        if (item->kind == E87_DRAW_ITEM_ASSET) {
            e87_blend_asset(
                color,
                x,
                y,
                (unsigned int)item->left,
                (unsigned int)item->top,
                item->source.asset,
                item->red,
                item->green,
                item->blue);
        } else {
            const struct e87_bitmap_glyph *glyph = item->source.glyph;
            const int32_t right =
                item->left + (int32_t)glyph->width * item->scale;
            const int32_t bottom =
                item->top + (int32_t)glyph->height * item->scale;

            if ((int32_t)x >= item->left && (int32_t)x < right &&
                (int32_t)y >= item->top && (int32_t)y < bottom) {
                const size_t local_x =
                    (size_t)((int32_t)x - item->left) / item->scale;
                const size_t local_y =
                    (size_t)((int32_t)y - item->top) / item->scale;
                const size_t alpha_index =
                    glyph->alpha_offset + local_y * glyph->width + local_x;

                e87_blend(
                    color,
                    item->red,
                    item->green,
                    item->blue,
                    e87_transient_glyph_alpha[alpha_index]);
            }
        }
    }
}

static void e87_format_number(uint8_t value,
                              bool percent,
                              char out[5])
{
    size_t index = 0u;

    if (value >= UINT8_C(100)) {
        out[index++] = '1';
        out[index++] = '0';
        out[index++] = '0';
    } else if (value >= UINT8_C(10)) {
        out[index++] = (char)('0' + value / UINT8_C(10));
        out[index++] = (char)('0' + value % UINT8_C(10));
    } else {
        out[index++] = (char)('0' + value);
    }
    if (percent) {
        out[index++] = '%';
    }
    out[index] = '\0';
}

static bool e87_draw_plan_add_battery_value(
    struct e87_draw_plan *plan,
    uint8_t percent,
    enum e87_ui_charge_visual charge,
    int32_t baseline_y)
{
    char text[5];
    const bool show_bolt = charge == E87_UI_CHARGE_CHARGING ||
                           charge == E87_UI_CHARGE_FULL;
    struct e87_text_run run;
    uint32_t total_q3;
    int32_t left_q3;

    e87_format_number(percent, true, text);
    if (!e87_prepare_text_run(text, E87_BIG_GLYPH_SCALE, &run)) {
        return false;
    }
    total_q3 = run.width_q3;
    if (show_bolt) {
        total_q3 += (E87_BOLT_GAP + e87_transient_asset_bolt.width) * 8u;
    }
    left_q3 = E87_FACE_CENTER * 8 - (int32_t)total_q3 / 2;
    if (!e87_draw_plan_add_run(
        plan,
        &run,
        left_q3,
        baseline_y,
        E87_BIG_GLYPH_SCALE,
        UINT8_C(E87_PRIMARY_RED),
        UINT8_C(E87_PRIMARY_GREEN),
        UINT8_C(E87_PRIMARY_BLUE))) {
        return false;
    }
    if (show_bolt) {
        const int32_t bolt_left =
            (left_q3 + (int32_t)run.width_q3 + 7) / 8 +
            E87_BOLT_GAP;
        const int32_t bolt_top = baseline_y + E87_BOLT_TOP_OFFSET_Y;

        if (!e87_draw_plan_add_asset(
            plan,
            &e87_transient_asset_bolt,
            bolt_left,
            bolt_top,
            UINT8_C(E87_PRIMARY_RED),
            UINT8_C(E87_PRIMARY_GREEN),
            UINT8_C(E87_PRIMARY_BLUE))) {
            return false;
        }
    }
    return true;
}

static bool e87_draw_plan_add_base_scene(
    struct e87_draw_plan *plan,
    const struct e87_render_model *model)
{
    char countdown[5];
    bool ok = true;

    switch (model->screen) {
    case E87_UI_SCREEN_PAIR_ME_NOW:
        ok = e87_draw_plan_add_centered_text(
            plan,
            "PAIR ME NOW",
            E87_PAIR_ME_PRIMARY_BASELINE_Y,
            UINT8_C(1),
            UINT8_C(E87_PRIMARY_RED),
            UINT8_C(E87_PRIMARY_GREEN),
            UINT8_C(E87_PRIMARY_BLUE)) &&
             e87_draw_plan_add_centered_text(
            plan,
            "HOLD BUTTON 1",
            E87_PAIR_ME_HINT_BASELINE_Y,
            UINT8_C(1),
            UINT8_C(E87_SECONDARY_RED),
            UINT8_C(E87_SECONDARY_GREEN),
            UINT8_C(E87_SECONDARY_BLUE));
        break;
    case E87_UI_SCREEN_WAITING_FOR_PHONE:
        ok = e87_draw_plan_add_centered_text(
            plan,
            "WAITING FOR PHONE",
            E87_WAITING_PRIMARY_BASELINE_Y,
            UINT8_C(1),
            UINT8_C(E87_PRIMARY_RED),
            UINT8_C(E87_PRIMARY_GREEN),
            UINT8_C(E87_PRIMARY_BLUE));
        break;
    case E87_UI_SCREEN_PAIRING:
        e87_format_number(model->countdown_seconds, false, countdown);
        ok = e87_draw_plan_add_centered_text(
            plan,
            "PAIRING",
            E87_PAIRING_PRIMARY_BASELINE_Y,
            UINT8_C(1),
            UINT8_C(E87_PRIMARY_RED),
            UINT8_C(E87_PRIMARY_GREEN),
            UINT8_C(E87_PRIMARY_BLUE)) &&
             e87_draw_plan_add_centered_text(
            plan,
            countdown,
            E87_PAIRING_COUNTDOWN_BASELINE_Y,
            E87_PAIRING_COUNTDOWN_GLYPH_SCALE,
            UINT8_C(E87_SECONDARY_RED),
            UINT8_C(E87_SECONDARY_GREEN),
            UINT8_C(E87_SECONDARY_BLUE));
        break;
    case E87_UI_SCREEN_UPDATE_WARNING:
        e87_format_number(model->countdown_seconds, false, countdown);
        ok = e87_draw_plan_add_centered_text(
            plan,
            "KEEP HOLDING",
            E87_UPDATE_WARNING_LINE1_BASELINE_Y,
            UINT8_C(1),
            UINT8_C(E87_PRIMARY_RED),
            UINT8_C(E87_PRIMARY_GREEN),
            UINT8_C(E87_PRIMARY_BLUE)) &&
             e87_draw_plan_add_centered_text(
            plan,
            "FOR UPDATE",
            E87_UPDATE_WARNING_LINE2_BASELINE_Y,
            UINT8_C(1),
            UINT8_C(E87_PRIMARY_RED),
            UINT8_C(E87_PRIMARY_GREEN),
            UINT8_C(E87_PRIMARY_BLUE)) &&
             e87_draw_plan_add_centered_text(
            plan,
            countdown,
            E87_UPDATE_WARNING_COUNTDOWN_BASELINE_Y,
            E87_UPDATE_WARNING_COUNTDOWN_GLYPH_SCALE,
            UINT8_C(E87_SECONDARY_RED),
            UINT8_C(E87_SECONDARY_GREEN),
            UINT8_C(E87_SECONDARY_BLUE));
        break;
    default:
        break;
    }
    return ok;
}

static const char *e87_maintenance_phase_text(
    enum e87_ui_maintenance_phase phase)
{
    switch (phase) {
    case E87_UI_MAINTENANCE_RELEASE_BUTTON:
        return "RELEASE BUTTON";
    case E87_UI_MAINTENANCE_WAITING_FOR_PHONE:
        return "WAITING FOR PHONE";
    case E87_UI_MAINTENANCE_PHONE_READY:
        return "PHONE READY";
    case E87_UI_MAINTENANCE_UPDATING:
        return "UPDATE";
    case E87_UI_MAINTENANCE_UPDATE_ERROR:
        return "UPDATE ERROR";
    default:
        return "";
    }
}

static bool e87_draw_plan_add_battery_status(
    struct e87_draw_plan *plan,
    const struct e87_render_model *model,
    int32_t value_baseline,
    int32_t status_baseline)
{
    if (model->battery_state == E87_UI_BATTERY_UNAVAILABLE_FAULT) {
        return e87_draw_plan_add_centered_text(
            plan,
            "BATTERY ERROR",
            value_baseline,
            UINT8_C(1),
            UINT8_C(E87_PRIMARY_RED),
            UINT8_C(E87_PRIMARY_GREEN),
            UINT8_C(E87_PRIMARY_BLUE));
    }
    if (!e87_draw_plan_add_battery_value(
            plan,
            model->battery_percent,
            model->charge_visual,
            value_baseline)) {
        return false;
    }
    if (model->battery_state == E87_UI_BATTERY_INVALID_STALE) {
        return e87_draw_plan_add_centered_text(
            plan,
            "BATTERY OLD",
            status_baseline,
            UINT8_C(1),
            UINT8_C(E87_SECONDARY_RED),
            UINT8_C(E87_SECONDARY_GREEN),
            UINT8_C(E87_SECONDARY_BLUE));
    }
    return true;
}

static bool e87_build_battery_plan(struct e87_draw_plan *plan,
                                   const struct e87_render_model *model,
                                   uint8_t strip_index)
{
    e87_draw_plan_init(plan, strip_index);
    if (!model->battery_overlay) {
        return true;
    }
    return e87_draw_plan_add_battery_status(
        plan,
        model,
        E87_BATTERY_BIG_BASELINE_Y,
        E87_BATTERY_STATUS_BASELINE_Y);
}

static bool e87_draw_plan_add_maintenance(
    struct e87_draw_plan *plan,
    const struct e87_render_model *model)
{
    char progress[5];
    const char *phase = e87_maintenance_phase_text(model->maintenance_phase);
    const bool error =
        model->maintenance_phase == E87_UI_MAINTENANCE_UPDATE_ERROR;

    if (!e87_draw_plan_add_centered_text(
            plan,
            "READY TO UPDATE",
            E87_MAINTENANCE_TITLE_BASELINE_Y,
            UINT8_C(1),
            UINT8_C(E87_PRIMARY_RED),
            UINT8_C(E87_PRIMARY_GREEN),
            UINT8_C(E87_PRIMARY_BLUE)) ||
        !e87_draw_plan_add_centered_text(
            plan,
            phase,
            E87_MAINTENANCE_PHASE_BASELINE_Y,
            UINT8_C(1),
            error ? UINT8_C(E87_PRIMARY_RED) :
                    UINT8_C(E87_SECONDARY_RED),
            error ? UINT8_C(E87_PRIMARY_GREEN) :
                    UINT8_C(E87_SECONDARY_GREEN),
            error ? UINT8_C(E87_PRIMARY_BLUE) :
                    UINT8_C(E87_SECONDARY_BLUE)) ||
        !e87_draw_plan_add_battery_status(
            plan,
            model,
            E87_MAINTENANCE_BATTERY_BASELINE_Y,
            E87_MAINTENANCE_BATTERY_STATUS_BASELINE_Y)) {
        return false;
    }
    if (model->maintenance_phase == E87_UI_MAINTENANCE_UPDATING) {
        e87_format_number(
            model->maintenance_progress_percent, true, progress);
        return e87_draw_plan_add_centered_text(
            plan,
            progress,
            E87_MAINTENANCE_PROGRESS_BASELINE_Y,
            UINT8_C(1),
            UINT8_C(E87_SECONDARY_RED),
            UINT8_C(E87_SECONDARY_GREEN),
            UINT8_C(E87_SECONDARY_BLUE));
    }
    return true;
}

static bool e87_build_scene_plan(struct e87_draw_plan *plan,
                                 const struct e87_render_model *model,
                                 uint8_t strip_index)
{
    e87_draw_plan_init(plan, strip_index);
    if (model->screen == E87_UI_SCREEN_MAINTENANCE) {
        return e87_draw_plan_add_maintenance(plan, model);
    }
    return e87_draw_plan_add_base_scene(plan, model);
}

static bool e87_metrics_valid(const struct e87_metrics *metrics)
{
    return metrics->day <= UINT8_C(100) &&
           metrics->week <= UINT8_C(100) &&
           metrics->credit_cents == E87_STATE_FIXED_CREDIT_CENTS;
}

static bool e87_model_valid(const struct e87_render_model *model)
{
    if (model->screen < E87_UI_SCREEN_PANEL_OFF ||
        model->screen > E87_UI_SCREEN_MAINTENANCE ||
        model->battery_state < E87_UI_BATTERY_VALID ||
        model->battery_state > E87_UI_BATTERY_UNAVAILABLE_FAULT ||
        model->battery_percent > UINT8_C(100) ||
        model->charge_visual < E87_UI_CHARGE_NONE ||
        model->charge_visual > E87_UI_CHARGE_FULL ||
        model->maintenance_phase < E87_UI_MAINTENANCE_RELEASE_BUTTON ||
        model->maintenance_phase > E87_UI_MAINTENANCE_UPDATE_ERROR ||
        model->maintenance_progress_percent > UINT8_C(100)) {
        return false;
    }
    if (model->screen == E87_UI_SCREEN_FACE &&
        !e87_metrics_valid(&model->metrics)) {
        return false;
    }
    if (model->screen == E87_UI_SCREEN_PAIRING &&
        (model->countdown_seconds == UINT8_C(0) ||
         model->countdown_seconds > UINT8_C(60))) {
        return false;
    }
    if (model->screen == E87_UI_SCREEN_UPDATE_WARNING &&
        (model->countdown_seconds == UINT8_C(0) ||
         model->countdown_seconds > UINT8_C(3))) {
        return false;
    }
    if (model->battery_overlay &&
        (model->screen == E87_UI_SCREEN_PANEL_OFF ||
         model->screen == E87_UI_SCREEN_UPDATE_WARNING ||
         model->screen == E87_UI_SCREEN_MAINTENANCE)) {
        return false;
    }
    if (model->recovery_entry &&
        (model->screen != E87_UI_SCREEN_MAINTENANCE ||
         model->maintenance_phase != E87_UI_MAINTENANCE_RELEASE_BUTTON ||
         model->maintenance_progress_percent != UINT8_C(0))) {
        return false;
    }
    return true;
}

enum e87_transient_render_result
e87_render_transient_strip(const struct e87_render_model *model,
                           uint8_t strip_index,
                           uint16_t *out_pixels,
                           size_t out_pixel_count)
{
    struct e87_draw_plan scene_plan;
    struct e87_draw_plan battery_plan;
    unsigned int local_y;
    unsigned int x;

    if (model == NULL || out_pixels == NULL) {
        return E87_TRANSIENT_RENDER_ERROR_ARGUMENT;
    }
    if (strip_index >= E87_STRIP_COUNT) {
        return E87_TRANSIENT_RENDER_ERROR_STRIP;
    }
    if (out_pixel_count < (size_t)E87_DISPLAY_WIDTH * E87_STRIP_ROWS) {
        return E87_TRANSIENT_RENDER_ERROR_CAPACITY;
    }
    if (!e87_model_valid(model)) {
        return E87_TRANSIENT_RENDER_ERROR_MODEL;
    }
    if (model->screen == E87_UI_SCREEN_PANEL_OFF) {
        return E87_TRANSIENT_RENDER_PANEL_OFF;
    }
    if (model->screen == E87_UI_SCREEN_FACE && !model->battery_overlay) {
        return e87_render_normal_face_strip(
                   &model->metrics,
                   strip_index,
                   out_pixels,
                   out_pixel_count) == E87_RENDER_OK
                   ? E87_TRANSIENT_RENDER_OK
                   : E87_TRANSIENT_RENDER_ERROR_BASE;
    }
    if (!e87_build_scene_plan(&scene_plan, model, strip_index) ||
        !e87_build_battery_plan(&battery_plan, model, strip_index)) {
        return E87_TRANSIENT_RENDER_ERROR_MODEL;
    }

    for (local_y = 0u; local_y < E87_STRIP_ROWS; ++local_y) {
        const unsigned int y =
            (unsigned int)strip_index * E87_STRIP_ROWS + local_y;

        for (x = 0u; x < E87_DISPLAY_WIDTH; ++x) {
            struct e87_rgb888 color = {
                E87_BACKGROUND_RED,
                E87_BACKGROUND_GREEN,
                E87_BACKGROUND_BLUE
            };

            if (model->screen == E87_UI_SCREEN_FACE) {
                color = e87_normal_face_color(
                    x, y, model->metrics.day, model->metrics.week);
            }
            e87_blend_plan_pixel(&color, x, y, &scene_plan);
            if (model->battery_overlay) {
                e87_blend(
                    &color,
                    UINT8_C(E87_BACKGROUND_RED),
                    UINT8_C(E87_BACKGROUND_GREEN),
                    UINT8_C(E87_BACKGROUND_BLUE),
                    UINT8_C(E87_OVERLAY_ALPHA));
                e87_blend_plan_pixel(&color, x, y, &battery_plan);
            }
            out_pixels[(size_t)local_y * E87_DISPLAY_WIDTH + x] =
                e87_quantize_rgb565(&color);
        }
    }
    return E87_TRANSIENT_RENDER_OK;
}
