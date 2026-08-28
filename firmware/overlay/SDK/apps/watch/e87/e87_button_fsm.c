#include "e87/e87_button_fsm.h"

static uint32_t elapsed_ms(uint32_t now_ms, uint32_t started_ms)
{
    return (uint32_t)(now_ms - started_ms);
}

static uint32_t expire_pairing(struct e87_button_fsm *fsm,
                               uint32_t now_ms)
{
    if (fsm->private_pairing_active &&
        elapsed_ms(now_ms, fsm->private_pairing_started_ms) >=
            E87_PAIRING_WINDOW_MS) {
        fsm->private_pairing_active = false;
        return E87_ACTION_PAIRING_EXPIRED;
    }
    return E87_ACTION_NONE;
}

static void start_button1(struct e87_button_fsm *fsm, uint32_t now_ms)
{
    fsm->private_button1_down = true;
    fsm->private_pairing_fired = false;
    fsm->private_warning_fired = false;
    fsm->private_maintenance_fired = false;
    fsm->private_button1_started_ms = now_ms;
}

static uint32_t advance_button1(struct e87_button_fsm *fsm,
                                uint32_t now_ms)
{
    const uint32_t age =
        elapsed_ms(now_ms, fsm->private_button1_started_ms);
    uint32_t actions = E87_ACTION_NONE;

    if (!fsm->private_pairing_fired &&
        age >= E87_BUTTON_PAIRING_THRESHOLD_MS) {
        fsm->private_pairing_fired = true;
        fsm->private_pairing_active = true;
        fsm->private_pairing_started_ms =
            fsm->private_button1_started_ms +
            E87_BUTTON_PAIRING_THRESHOLD_MS;
        actions |= E87_ACTION_OPEN_PAIRING;
    }
    if (!fsm->private_warning_fired &&
        age >= E87_BUTTON_WARNING_THRESHOLD_MS) {
        fsm->private_warning_fired = true;
        actions |= E87_ACTION_UPDATE_WARNING;
    }
    if (!fsm->private_maintenance_fired &&
        age >= E87_BUTTON_MAINTENANCE_THRESHOLD_MS) {
        fsm->private_maintenance_fired = true;
        fsm->private_pairing_active = false;
        actions |= E87_ACTION_ENTER_MAINTENANCE;
    }

    return actions;
}

static uint32_t finish_button1(struct e87_button_fsm *fsm,
                               uint32_t now_ms)
{
    const uint32_t age =
        elapsed_ms(now_ms, fsm->private_button1_started_ms);
    uint32_t actions = advance_button1(fsm, now_ms);

    if (age < E87_BUTTON_PAIRING_THRESHOLD_MS) {
        actions |= E87_ACTION_TAP_BATTERY;
    } else if (age >= E87_BUTTON_WARNING_THRESHOLD_MS &&
               age < E87_BUTTON_MAINTENANCE_THRESHOLD_MS) {
        actions |= E87_ACTION_END_UPDATE_WARNING;
    }
    fsm->private_button1_down = false;
    return actions;
}

static uint32_t abort_button1(struct e87_button_fsm *fsm)
{
    uint32_t actions = E87_ACTION_NONE;

    if (fsm->private_warning_fired &&
        !fsm->private_maintenance_fired) {
        actions |= E87_ACTION_END_UPDATE_WARNING;
    }
    fsm->private_button1_down = false;
    return actions;
}

void e87_button_init(struct e87_button_fsm *fsm)
{
    struct e87_button_fsm initialized = {0};

    if (fsm == 0) {
        return;
    }
    initialized.private_initialized = true;
    *fsm = initialized;
}

uint32_t e87_button_step(struct e87_button_fsm *fsm,
                         uint32_t now_ms,
                         enum e87_key_class sample)
{
    uint32_t actions;

    if (fsm == 0 || !fsm->private_initialized) {
        return E87_ACTION_NONE;
    }

    actions = expire_pairing(fsm, now_ms);
    if (fsm->private_rearm_required) {
        if (sample == E87_KEY_NONE) {
            fsm->private_rearm_required = false;
        }
        return actions;
    }

    if (fsm->private_button1_down) {
        if (sample == E87_KEY_BUTTON1) {
            actions |= advance_button1(fsm, now_ms);
        } else if (sample == E87_KEY_NONE) {
            actions |= finish_button1(fsm, now_ms);
        } else if (sample == E87_KEY_BUTTON2 ||
                   sample == E87_KEY_AMBIGUOUS) {
            actions |= advance_button1(fsm, now_ms);
            actions |= abort_button1(fsm);
            fsm->private_rearm_required = true;
        } else {
            actions |= abort_button1(fsm);
            fsm->private_rearm_required = true;
        }
        return actions;
    }

    if (fsm->private_button2_down) {
        if (sample == E87_KEY_NONE) {
            fsm->private_button2_down = false;
        } else if (sample != E87_KEY_BUTTON2) {
            fsm->private_button2_down = false;
            fsm->private_rearm_required = true;
        }
        return actions;
    }

    if (sample == E87_KEY_BUTTON1) {
        start_button1(fsm, now_ms);
    } else if (sample == E87_KEY_BUTTON2) {
        fsm->private_button2_down = true;
        actions |= E87_ACTION_SLEEP_TOGGLE;
    } else if (sample != E87_KEY_NONE) {
        fsm->private_rearm_required = true;
    }

    return actions;
}

enum e87_button_action
e87_button_action_at(uint32_t actions, uint8_t ordinal)
{
    static const enum e87_button_action priority[] = {
        E87_ACTION_PAIRING_EXPIRED,
        E87_ACTION_TAP_BATTERY,
        E87_ACTION_OPEN_PAIRING,
        E87_ACTION_UPDATE_WARNING,
        E87_ACTION_END_UPDATE_WARNING,
        E87_ACTION_SLEEP_TOGGLE,
        E87_ACTION_ENTER_MAINTENANCE
    };
    uint8_t index;
    uint8_t seen = UINT8_C(0);

    if ((actions & ~UINT32_C(127)) != UINT32_C(0)) {
        return E87_ACTION_NONE;
    }

    for (index = UINT8_C(0); index < UINT8_C(7);
         index = (uint8_t)(index + UINT8_C(1))) {
        if ((actions & (uint32_t)priority[index]) != UINT32_C(0)) {
            if (seen == ordinal) {
                return priority[index];
            }
            seen = (uint8_t)(seen + UINT8_C(1));
        }
    }
    return E87_ACTION_NONE;
}

bool e87_button_get_view(const struct e87_button_fsm *fsm,
                         uint32_t now_ms,
                         struct e87_button_view *out)
{
    struct e87_button_view view = {false, false, UINT32_C(0), UINT32_C(0)};
    uint32_t age;

    if (fsm == 0 || !fsm->private_initialized || out == 0) {
        return false;
    }

    if (fsm->private_pairing_active) {
        age = elapsed_ms(now_ms, fsm->private_pairing_started_ms);
        if (age < E87_PAIRING_WINDOW_MS) {
            view.pairing_active = true;
            view.pairing_remaining_ms =
                E87_PAIRING_WINDOW_MS - age;
        }
    }
    if (fsm->private_button1_down &&
        fsm->private_warning_fired &&
        !fsm->private_maintenance_fired) {
        age = elapsed_ms(now_ms, fsm->private_button1_started_ms);
        if (age >= E87_BUTTON_WARNING_THRESHOLD_MS &&
            age < E87_BUTTON_MAINTENANCE_THRESHOLD_MS) {
            view.warning_active = true;
            view.warning_remaining_ms =
                E87_BUTTON_MAINTENANCE_THRESHOLD_MS - age;
        }
    }

    *out = view;
    return true;
}
