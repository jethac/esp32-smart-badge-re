#ifndef E87_UI_H
#define E87_UI_H

#include <stdbool.h>
#include <stdint.h>

#include "e87/e87_button_fsm.h"
#include "e87/e87_power_policy.h"
#include "e87/e87_state.h"

#define E87_BATTERY_OVERLAY_MS UINT32_C(2500)

enum e87_ui_screen {
    E87_UI_SCREEN_PANEL_OFF = 0,
    E87_UI_SCREEN_PAIR_ME_NOW = 1,
    E87_UI_SCREEN_WAITING_FOR_PHONE = 2,
    E87_UI_SCREEN_FACE = 3,
    E87_UI_SCREEN_PAIRING = 4,
    E87_UI_SCREEN_UPDATE_WARNING = 5,
    E87_UI_SCREEN_MAINTENANCE = 6
};

enum e87_ui_battery_state {
    E87_UI_BATTERY_VALID = 0,
    E87_UI_BATTERY_INVALID_STALE = 1,
    E87_UI_BATTERY_UNAVAILABLE_FAULT = 2
};

enum e87_ui_charge_visual {
    E87_UI_CHARGE_NONE = 0,
    E87_UI_CHARGE_CHARGING = 1,
    E87_UI_CHARGE_FULL = 2
};

enum e87_ui_maintenance_phase {
    E87_UI_MAINTENANCE_RELEASE_BUTTON = 0,
    E87_UI_MAINTENANCE_WAITING_FOR_PHONE = 1,
    E87_UI_MAINTENANCE_PHONE_READY = 2,
    E87_UI_MAINTENANCE_UPDATING = 3,
    E87_UI_MAINTENANCE_UPDATE_ERROR = 4
};

struct e87_ui_inputs {
    bool panel_visible;
    bool has_bond;
    bool maintenance_active;
    bool recovery_entry;
    struct e87_button_view button;
    struct e87_state_snapshot semantic;
    enum e87_ui_battery_state battery_state;
    uint8_t battery_percent;
    enum e87_charge_phase charger_phase;
    enum e87_ui_maintenance_phase maintenance_phase;
    uint8_t maintenance_progress_percent;
};

struct e87_render_model {
    enum e87_ui_screen screen;
    struct e87_metrics metrics;
    uint8_t countdown_seconds;
    bool battery_overlay;
    enum e87_ui_battery_state battery_state;
    uint8_t battery_percent;
    enum e87_ui_charge_visual charge_visual;
    enum e87_ui_maintenance_phase maintenance_phase;
    uint8_t maintenance_progress_percent;
    bool recovery_entry;
};

struct e87_ui_state {
    bool private_initialized;
    bool private_battery_overlay_active;
    uint32_t private_battery_overlay_started_ms;
    struct e87_render_model private_underlay;
};

void e87_ui_init(struct e87_ui_state *state);

bool e87_ui_step(struct e87_ui_state *state,
                 uint32_t now_ms,
                 uint32_t actions,
                 const struct e87_ui_inputs *inputs,
                 struct e87_render_model *out);

#endif
