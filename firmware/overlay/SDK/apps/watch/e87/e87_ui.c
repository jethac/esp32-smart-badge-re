#include "e87/e87_ui.h"

#include <string.h>

static bool e87_metrics_valid(const struct e87_metrics *metrics)
{
    return metrics->day <= UINT8_C(100) &&
           metrics->week <= UINT8_C(100) &&
           metrics->credit_cents == E87_STATE_FIXED_CREDIT_CENTS;
}

static bool e87_inputs_valid(const struct e87_ui_inputs *inputs,
                             uint32_t actions)
{
    const uint32_t known_actions =
        E87_ACTION_TAP_BATTERY |
        E87_ACTION_OPEN_PAIRING |
        E87_ACTION_UPDATE_WARNING |
        E87_ACTION_ENTER_MAINTENANCE |
        E87_ACTION_SLEEP_TOGGLE |
        E87_ACTION_END_UPDATE_WARNING |
        E87_ACTION_PAIRING_EXPIRED;

    if ((actions & ~known_actions) != UINT32_C(0) ||
        inputs->battery_state < E87_UI_BATTERY_VALID ||
        inputs->battery_state > E87_UI_BATTERY_UNAVAILABLE_FAULT ||
        inputs->battery_percent > UINT8_C(100) ||
        inputs->charger_phase < E87_CHARGE_PHASE_UNKNOWN ||
        inputs->charger_phase > E87_CHARGE_PHASE_FAULT ||
        inputs->maintenance_phase < E87_UI_MAINTENANCE_RELEASE_BUTTON ||
        inputs->maintenance_phase > E87_UI_MAINTENANCE_UPDATE_ERROR ||
        inputs->maintenance_progress_percent > UINT8_C(100)) {
        return false;
    }
    if (inputs->semantic.has_metrics &&
        !e87_metrics_valid(&inputs->semantic.metrics)) {
        return false;
    }
    if (inputs->button.pairing_active) {
        if (inputs->button.pairing_remaining_ms == UINT32_C(0) ||
            inputs->button.pairing_remaining_ms > E87_PAIRING_WINDOW_MS) {
            return false;
        }
    } else if (inputs->button.pairing_remaining_ms != UINT32_C(0)) {
        return false;
    }
    if (inputs->button.warning_active) {
        if (!inputs->button.pairing_active ||
            inputs->button.warning_remaining_ms == UINT32_C(0) ||
            inputs->button.warning_remaining_ms >
                E87_BUTTON_MAINTENANCE_THRESHOLD_MS -
                E87_BUTTON_WARNING_THRESHOLD_MS) {
            return false;
        }
    } else if (inputs->button.warning_remaining_ms != UINT32_C(0)) {
        return false;
    }
    return true;
}

static uint8_t e87_countdown_seconds(uint32_t remaining_ms)
{
    return (uint8_t)((remaining_ms + UINT32_C(999)) / UINT32_C(1000));
}

static enum e87_ui_charge_visual
e87_charge_visual(enum e87_charge_phase phase)
{
    if (phase == E87_CHARGE_PHASE_CHARGING) {
        return E87_UI_CHARGE_CHARGING;
    }
    if (phase == E87_CHARGE_PHASE_FULL) {
        return E87_UI_CHARGE_FULL;
    }
    return E87_UI_CHARGE_NONE;
}

static struct e87_render_model
e87_base_model(const struct e87_ui_inputs *inputs)
{
    struct e87_render_model model;

    memset(&model, 0, sizeof(model));
    if (inputs->button.pairing_active) {
        model.screen = E87_UI_SCREEN_PAIRING;
        model.countdown_seconds =
            e87_countdown_seconds(inputs->button.pairing_remaining_ms);
    } else if (!inputs->has_bond) {
        model.screen = E87_UI_SCREEN_PAIR_ME_NOW;
    } else if (!inputs->semantic.has_metrics) {
        model.screen = E87_UI_SCREEN_WAITING_FOR_PHONE;
    } else {
        model.screen = E87_UI_SCREEN_FACE;
        model.metrics = inputs->semantic.metrics;
    }
    return model;
}

static void e87_apply_battery(struct e87_render_model *model,
                              const struct e87_ui_inputs *inputs)
{
    model->battery_state = inputs->battery_state;
    model->battery_percent = inputs->battery_percent;
    model->charge_visual = e87_charge_visual(inputs->charger_phase);
}

void e87_ui_init(struct e87_ui_state *state)
{
    struct e87_ui_state initialized;

    if (state == NULL) {
        return;
    }
    memset(&initialized, 0, sizeof(initialized));
    initialized.private_initialized = true;
    *state = initialized;
}

bool e87_ui_step(struct e87_ui_state *state,
                 uint32_t now_ms,
                 uint32_t actions,
                 const struct e87_ui_inputs *inputs,
                 struct e87_render_model *out)
{
    struct e87_ui_state next;
    struct e87_render_model model;

    if (state == NULL || inputs == NULL || out == NULL ||
        !state->private_initialized ||
        !e87_inputs_valid(inputs, actions)) {
        return false;
    }

    next = *state;
    if (next.private_battery_overlay_active &&
        (uint32_t)(now_ms - next.private_battery_overlay_started_ms) >=
            E87_BATTERY_OVERLAY_MS) {
        next.private_battery_overlay_active = false;
    }

    if ((actions & E87_ACTION_TAP_BATTERY) != UINT32_C(0) &&
        inputs->panel_visible &&
        !inputs->maintenance_active &&
        !inputs->recovery_entry &&
        !inputs->button.warning_active) {
        next.private_underlay = e87_base_model(inputs);
        next.private_battery_overlay_active = true;
        next.private_battery_overlay_started_ms = now_ms;
    }

    memset(&model, 0, sizeof(model));
    if (!inputs->panel_visible) {
        model.screen = E87_UI_SCREEN_PANEL_OFF;
    } else if (inputs->maintenance_active || inputs->recovery_entry) {
        model.screen = E87_UI_SCREEN_MAINTENANCE;
        model.recovery_entry = inputs->recovery_entry;
        if (inputs->recovery_entry) {
            model.maintenance_phase =
                E87_UI_MAINTENANCE_RELEASE_BUTTON;
        } else {
            model.maintenance_phase = inputs->maintenance_phase;
            model.maintenance_progress_percent =
                inputs->maintenance_progress_percent;
        }
        e87_apply_battery(&model, inputs);
    } else if (inputs->button.warning_active) {
        model.screen = E87_UI_SCREEN_UPDATE_WARNING;
        model.countdown_seconds =
            e87_countdown_seconds(inputs->button.warning_remaining_ms);
    } else if (next.private_battery_overlay_active) {
        model = next.private_underlay;
        model.battery_overlay = true;
        e87_apply_battery(&model, inputs);
    } else {
        model = e87_base_model(inputs);
    }

    *state = next;
    *out = model;
    return true;
}
