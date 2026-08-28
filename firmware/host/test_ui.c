#include "test_support.h"
#include "e87/e87_ui.h"

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

static struct e87_ui_inputs inputs(void)
{
    struct e87_ui_inputs value;

    memset(&value, 0, sizeof(value));
    value.panel_visible = true;
    value.battery_state = E87_UI_BATTERY_VALID;
    value.battery_percent = UINT8_C(50);
    value.charger_phase = E87_CHARGER_PHASE_UNKNOWN;
    value.maintenance_phase = E87_UI_MAINTENANCE_WAITING_FOR_PHONE;
    return value;
}

static struct e87_metrics metrics(uint8_t day, uint8_t week)
{
    struct e87_metrics value;

    value.day = day;
    value.week = week;
    value.credit_cents = E87_STATE_FIXED_CREDIT_CENTS;
    return value;
}

static bool same_model(const struct e87_render_model *left,
                       const struct e87_render_model *right)
{
    return memcmp(left, right, sizeof(*left)) == 0;
}

E87_TEST(default_screen_follows_bond_then_boot_metrics)
{
    struct e87_ui_state state;
    struct e87_ui_inputs in = inputs();
    struct e87_render_model out;

    e87_ui_init(&state);
    E87_ASSERT_TRUE(e87_ui_step(
        &state, UINT32_C(0), E87_ACTION_NONE, &in, &out));
    E87_ASSERT_EQ_U32(E87_UI_SCREEN_PAIR_ME_NOW, out.screen);
    E87_ASSERT_TRUE(!out.battery_overlay);

    in.has_bond = true;
    E87_ASSERT_TRUE(e87_ui_step(
        &state, UINT32_C(1), E87_ACTION_NONE, &in, &out));
    E87_ASSERT_EQ_U32(E87_UI_SCREEN_WAITING_FOR_PHONE, out.screen);

    in.semantic.has_metrics = true;
    in.semantic.metrics = metrics(UINT8_C(17), UINT8_C(27));
    in.semantic.revision = UINT32_C(1);
    E87_ASSERT_TRUE(e87_ui_step(
        &state, UINT32_C(2), E87_ACTION_NONE, &in, &out));
    E87_ASSERT_EQ_U32(E87_UI_SCREEN_FACE, out.screen);
    E87_ASSERT_EQ_U32(UINT8_C(17), out.metrics.day);
    E87_ASSERT_EQ_U32(UINT8_C(27), out.metrics.week);

    in.has_bond = false;
    E87_ASSERT_TRUE(e87_ui_step(
        &state, UINT32_C(3), E87_ACTION_NONE, &in, &out));
    E87_ASSERT_EQ_U32(E87_UI_SCREEN_PAIR_ME_NOW, out.screen);
}

E87_TEST(pairing_uses_ceiling_seconds_and_warning_replaces_it)
{
    struct e87_ui_state state;
    struct e87_ui_inputs in = inputs();
    struct e87_render_model out;

    e87_ui_init(&state);
    in.button.pairing_active = true;
    in.button.pairing_remaining_ms = UINT32_C(60000);
    E87_ASSERT_TRUE(e87_ui_step(
        &state, UINT32_C(10), E87_ACTION_NONE, &in, &out));
    E87_ASSERT_EQ_U32(E87_UI_SCREEN_PAIRING, out.screen);
    E87_ASSERT_EQ_U32(UINT8_C(60), out.countdown_seconds);

    in.button.pairing_remaining_ms = UINT32_C(59001);
    E87_ASSERT_TRUE(e87_ui_step(
        &state, UINT32_C(11), E87_ACTION_NONE, &in, &out));
    E87_ASSERT_EQ_U32(UINT8_C(60), out.countdown_seconds);

    in.button.pairing_remaining_ms = UINT32_C(59000);
    E87_ASSERT_TRUE(e87_ui_step(
        &state, UINT32_C(12), E87_ACTION_NONE, &in, &out));
    E87_ASSERT_EQ_U32(UINT8_C(59), out.countdown_seconds);

    in.button.warning_active = true;
    in.button.warning_remaining_ms = UINT32_C(3000);
    E87_ASSERT_TRUE(e87_ui_step(
        &state, UINT32_C(13), E87_ACTION_NONE, &in, &out));
    E87_ASSERT_EQ_U32(E87_UI_SCREEN_UPDATE_WARNING, out.screen);
    E87_ASSERT_EQ_U32(UINT8_C(3), out.countdown_seconds);

    in.button.warning_remaining_ms = UINT32_C(1001);
    E87_ASSERT_TRUE(e87_ui_step(
        &state, UINT32_C(14), E87_ACTION_NONE, &in, &out));
    E87_ASSERT_EQ_U32(UINT8_C(2), out.countdown_seconds);

    in.button.warning_remaining_ms = UINT32_C(1);
    E87_ASSERT_TRUE(e87_ui_step(
        &state, UINT32_C(15), E87_ACTION_NONE, &in, &out));
    E87_ASSERT_EQ_U32(UINT8_C(1), out.countdown_seconds);
}

E87_TEST(battery_overlay_snapshots_model_not_pixels_and_expires_at_2500)
{
    struct e87_ui_state state;
    struct e87_ui_inputs in = inputs();
    struct e87_render_model out;
    uint32_t start = UINT32_MAX - UINT32_C(1000);

    e87_ui_init(&state);
    in.has_bond = true;
    in.semantic.has_metrics = true;
    in.semantic.metrics = metrics(UINT8_C(10), UINT8_C(20));
    in.semantic.revision = UINT32_C(7);
    in.battery_percent = UINT8_C(81);
    in.charger_phase = E87_CHARGER_PHASE_START;

    E87_ASSERT_TRUE(e87_ui_step(
        &state, start, E87_ACTION_TAP_BATTERY, &in, &out));
    E87_ASSERT_EQ_U32(E87_UI_SCREEN_FACE, out.screen);
    E87_ASSERT_TRUE(out.battery_overlay);
    E87_ASSERT_EQ_U32(UINT8_C(10), out.metrics.day);
    E87_ASSERT_EQ_U32(UINT8_C(20), out.metrics.week);
    E87_ASSERT_EQ_U32(UINT8_C(81), out.battery_percent);
    E87_ASSERT_EQ_U32(E87_UI_CHARGE_CHARGING, out.charge_visual);

    in.semantic.metrics = metrics(UINT8_C(90), UINT8_C(99));
    in.semantic.revision = UINT32_C(8);
    in.button.pairing_active = true;
    in.button.pairing_remaining_ms = UINT32_C(60000);
    E87_ASSERT_TRUE(e87_ui_step(
        &state, start + UINT32_C(2499), E87_ACTION_NONE, &in, &out));
    E87_ASSERT_EQ_U32(E87_UI_SCREEN_FACE, out.screen);
    E87_ASSERT_TRUE(out.battery_overlay);
    E87_ASSERT_EQ_U32(UINT8_C(10), out.metrics.day);
    E87_ASSERT_EQ_U32(UINT8_C(20), out.metrics.week);

    E87_ASSERT_TRUE(e87_ui_step(
        &state, start + UINT32_C(2500), E87_ACTION_NONE, &in, &out));
    E87_ASSERT_EQ_U32(E87_UI_SCREEN_PAIRING, out.screen);
    E87_ASSERT_TRUE(!out.battery_overlay);
    E87_ASSERT_EQ_U32(UINT8_C(60), out.countdown_seconds);
}

E87_TEST(maintenance_recovery_and_warning_have_total_precedence)
{
    struct e87_ui_state state;
    struct e87_ui_inputs in = inputs();
    struct e87_render_model out;

    e87_ui_init(&state);
    in.button.pairing_active = true;
    in.button.pairing_remaining_ms = UINT32_C(42000);
    in.button.warning_active = true;
    in.button.warning_remaining_ms = UINT32_C(2000);
    E87_ASSERT_TRUE(e87_ui_step(
        &state, UINT32_C(1), E87_ACTION_NONE, &in, &out));
    E87_ASSERT_EQ_U32(E87_UI_SCREEN_UPDATE_WARNING, out.screen);

    in.maintenance_active = true;
    in.recovery_entry = true;
    in.maintenance_phase = E87_UI_MAINTENANCE_RELEASE_BUTTON;
    in.battery_percent = UINT8_C(49);
    in.charger_phase = E87_CHARGER_PHASE_FULL;
    E87_ASSERT_TRUE(e87_ui_step(
        &state, UINT32_C(2), E87_ACTION_NONE, &in, &out));
    E87_ASSERT_EQ_U32(E87_UI_SCREEN_MAINTENANCE, out.screen);
    E87_ASSERT_TRUE(out.recovery_entry);
    E87_ASSERT_EQ_U32(E87_UI_MAINTENANCE_RELEASE_BUTTON,
                      out.maintenance_phase);
    E87_ASSERT_EQ_U32(UINT8_C(49), out.battery_percent);
    E87_ASSERT_EQ_U32(E87_UI_CHARGE_FULL, out.charge_visual);

    in.maintenance_phase = E87_UI_MAINTENANCE_UPDATING;
    in.maintenance_progress_percent = UINT8_C(77);
    E87_ASSERT_TRUE(e87_ui_step(
        &state, UINT32_C(3), E87_ACTION_NONE, &in, &out));
    E87_ASSERT_EQ_U32(E87_UI_MAINTENANCE_RELEASE_BUTTON,
                      out.maintenance_phase);
    E87_ASSERT_EQ_U32(UINT8_C(0), out.maintenance_progress_percent);

    in.recovery_entry = false;
    E87_ASSERT_TRUE(e87_ui_step(
        &state, UINT32_C(4), E87_ACTION_NONE, &in, &out));
    E87_ASSERT_EQ_U32(E87_UI_MAINTENANCE_UPDATING,
                      out.maintenance_phase);
    E87_ASSERT_EQ_U32(UINT8_C(77), out.maintenance_progress_percent);

    in.panel_visible = false;
    E87_ASSERT_TRUE(e87_ui_step(
        &state, UINT32_C(5), E87_ACTION_NONE, &in, &out));
    E87_ASSERT_EQ_U32(E87_UI_SCREEN_PANEL_OFF, out.screen);
}

E87_TEST(battery_state_and_charge_visual_are_explicit)
{
    struct e87_ui_state state;
    struct e87_ui_inputs in = inputs();
    struct e87_render_model out;

    e87_ui_init(&state);
    in.battery_state = E87_UI_BATTERY_INVALID_STALE;
    in.battery_percent = UINT8_C(37);
    in.charger_phase = E87_CHARGER_PHASE_CLOSE;
    E87_ASSERT_TRUE(e87_ui_step(
        &state, UINT32_C(1), E87_ACTION_TAP_BATTERY, &in, &out));
    E87_ASSERT_EQ_U32(E87_UI_BATTERY_INVALID_STALE, out.battery_state);
    E87_ASSERT_EQ_U32(UINT8_C(37), out.battery_percent);
    E87_ASSERT_EQ_U32(E87_UI_CHARGE_NONE, out.charge_visual);

    e87_ui_init(&state);
    in.battery_state = E87_UI_BATTERY_UNAVAILABLE_FAULT;
    in.battery_percent = UINT8_C(0);
    in.charger_phase = E87_CHARGER_PHASE_UNKNOWN;
    E87_ASSERT_TRUE(e87_ui_step(
        &state, UINT32_C(2), E87_ACTION_TAP_BATTERY, &in, &out));
    E87_ASSERT_EQ_U32(E87_UI_BATTERY_UNAVAILABLE_FAULT,
                      out.battery_state);
    E87_ASSERT_EQ_U32(E87_UI_CHARGE_NONE, out.charge_visual);
}

E87_TEST(invalid_inputs_fail_without_state_or_output_mutation)
{
    struct e87_ui_state state;
    struct e87_ui_state before_state;
    struct e87_ui_inputs in = inputs();
    struct e87_render_model out;
    struct e87_render_model before_out;

    memset(&state, 0xA5, sizeof(state));
    memset(&out, 0x5A, sizeof(out));
    before_state = state;
    before_out = out;
    E87_ASSERT_TRUE(!e87_ui_step(
        &state, UINT32_C(0), E87_ACTION_NONE, &in, &out));
    E87_ASSERT_TRUE(memcmp(&state, &before_state, sizeof(state)) == 0);
    E87_ASSERT_TRUE(same_model(&out, &before_out));

    e87_ui_init(&state);
    before_state = state;
    in.battery_percent = UINT8_C(101);
    E87_ASSERT_TRUE(!e87_ui_step(
        &state, UINT32_C(0), E87_ACTION_NONE, &in, &out));
    E87_ASSERT_TRUE(memcmp(&state, &before_state, sizeof(state)) == 0);
    E87_ASSERT_TRUE(same_model(&out, &before_out));

    in = inputs();
    in.button.pairing_active = true;
    in.button.pairing_remaining_ms = UINT32_C(0);
    E87_ASSERT_TRUE(!e87_ui_step(
        &state, UINT32_C(0), E87_ACTION_NONE, &in, &out));
    E87_ASSERT_TRUE(memcmp(&state, &before_state, sizeof(state)) == 0);
    E87_ASSERT_TRUE(same_model(&out, &before_out));

    in = inputs();
    E87_ASSERT_TRUE(!e87_ui_step(
        NULL, UINT32_C(0), E87_ACTION_NONE, &in, &out));
    E87_ASSERT_TRUE(!e87_ui_step(
        &state, UINT32_C(0), E87_ACTION_NONE, NULL, &out));
    E87_ASSERT_TRUE(!e87_ui_step(
        &state, UINT32_C(0), E87_ACTION_NONE, &in, NULL));
}

static const struct e87_test_case ui_cases[] = {
    E87_TEST_CASE(default_screen_follows_bond_then_boot_metrics),
    E87_TEST_CASE(pairing_uses_ceiling_seconds_and_warning_replaces_it),
    E87_TEST_CASE(battery_overlay_snapshots_model_not_pixels_and_expires_at_2500),
    E87_TEST_CASE(maintenance_recovery_and_warning_have_total_precedence),
    E87_TEST_CASE(battery_state_and_charge_visual_are_explicit),
    E87_TEST_CASE(invalid_inputs_fail_without_state_or_output_mutation),
};

const struct e87_test_suite e87_test_suite = {
    "transient-ui-policy",
    ui_cases,
    sizeof(ui_cases) / sizeof(ui_cases[0]),
};
