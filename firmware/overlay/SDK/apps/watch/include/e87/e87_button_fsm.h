#ifndef E87_BUTTON_FSM_H
#define E87_BUTTON_FSM_H

#include <stdbool.h>
#include <stdint.h>

#define E87_BUTTON_PAIRING_THRESHOLD_MS UINT32_C(3000)
#define E87_BUTTON_WARNING_THRESHOLD_MS UINT32_C(7000)
#define E87_BUTTON_MAINTENANCE_THRESHOLD_MS UINT32_C(10000)
#define E87_PAIRING_WINDOW_MS UINT32_C(60000)

enum e87_key_class {
    E87_KEY_NONE = 0,
    E87_KEY_BUTTON1 = 1,
    E87_KEY_BUTTON2 = 2,
    E87_KEY_AMBIGUOUS = 3
};

enum e87_button_action {
    E87_ACTION_NONE = 0,
    E87_ACTION_TAP_BATTERY = 1u << 0,
    E87_ACTION_OPEN_PAIRING = 1u << 1,
    E87_ACTION_UPDATE_WARNING = 1u << 2,
    E87_ACTION_ENTER_MAINTENANCE = 1u << 3,
    E87_ACTION_SLEEP_TOGGLE = 1u << 4,
    E87_ACTION_END_UPDATE_WARNING = 1u << 5,
    E87_ACTION_PAIRING_EXPIRED = 1u << 6
};

struct e87_button_view {
    bool pairing_active;
    bool warning_active;
    uint32_t pairing_remaining_ms;
    uint32_t warning_remaining_ms;
};

struct e87_button_fsm {
    bool private_initialized;
    bool private_button1_down;
    bool private_button2_down;
    bool private_pairing_fired;
    bool private_warning_fired;
    bool private_maintenance_fired;
    bool private_pairing_active;
    bool private_rearm_required;
    uint32_t private_button1_started_ms;
    uint32_t private_pairing_started_ms;
};

void e87_button_init(struct e87_button_fsm *fsm);

uint32_t e87_button_step(struct e87_button_fsm *fsm,
                         uint32_t now_ms,
                         enum e87_key_class sample);

enum e87_button_action
e87_button_action_at(uint32_t actions, uint8_t ordinal);

bool e87_button_get_view(const struct e87_button_fsm *fsm,
                         uint32_t now_ms,
                         struct e87_button_view *out);

#endif
