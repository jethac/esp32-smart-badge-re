#include "test_support.h"
#include "e87/e87_button_fsm.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

static bool bytes_equal(const void *left, const void *right, size_t length)
{
    return memcmp(left, right, length) == 0;
}

static struct e87_button_fsm fresh_button(void)
{
    struct e87_button_fsm fsm;

    memset(&fsm, 0xA5, sizeof(fsm));
    e87_button_init(&fsm);
    return fsm;
}

static uint32_t step_button1_to(struct e87_button_fsm *fsm,
                                uint32_t started_ms,
                                uint32_t elapsed_ms)
{
    uint32_t actions;

    actions = e87_button_step(fsm, started_ms, E87_KEY_BUTTON1);
    if (actions != E87_ACTION_NONE) {
        return UINT32_MAX;
    }
    return e87_button_step(fsm, started_ms + elapsed_ms,
                           E87_KEY_BUTTON1);
}

E87_TEST(button_constants_pin_exact_thresholds)
{
    E87_ASSERT_EQ_U32(UINT32_C(3000), E87_BUTTON_PAIRING_THRESHOLD_MS);
    E87_ASSERT_EQ_U32(UINT32_C(7000), E87_BUTTON_WARNING_THRESHOLD_MS);
    E87_ASSERT_EQ_U32(UINT32_C(10000), E87_BUTTON_MAINTENANCE_THRESHOLD_MS);
    E87_ASSERT_EQ_U32(UINT32_C(60000), E87_PAIRING_WINDOW_MS);
    E87_ASSERT_EQ_U32(UINT32_C(0), E87_KEY_NONE);
    E87_ASSERT_EQ_U32(UINT32_C(1), E87_KEY_BUTTON1);
    E87_ASSERT_EQ_U32(UINT32_C(2), E87_KEY_BUTTON2);
    E87_ASSERT_EQ_U32(UINT32_C(3), E87_KEY_AMBIGUOUS);
    E87_ASSERT_EQ_U32(UINT32_C(1), E87_ACTION_TAP_BATTERY);
    E87_ASSERT_EQ_U32(UINT32_C(2), E87_ACTION_OPEN_PAIRING);
    E87_ASSERT_EQ_U32(UINT32_C(4), E87_ACTION_UPDATE_WARNING);
    E87_ASSERT_EQ_U32(UINT32_C(8), E87_ACTION_ENTER_MAINTENANCE);
    E87_ASSERT_EQ_U32(UINT32_C(16), E87_ACTION_SLEEP_TOGGLE);
    E87_ASSERT_EQ_U32(UINT32_C(32), E87_ACTION_END_UPDATE_WARNING);
    E87_ASSERT_EQ_U32(UINT32_C(64), E87_ACTION_PAIRING_EXPIRED);
}

E87_TEST(button1_release_2999_is_tap_and_3000_is_pairing)
{
    struct e87_button_fsm fsm = fresh_button();

    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(100), E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_TAP_BATTERY,
                      e87_button_step(&fsm, UINT32_C(3099), E87_KEY_NONE));

    fsm = fresh_button();
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(100), E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING,
                      e87_button_step(&fsm, UINT32_C(3100), E87_KEY_NONE));
    E87_ASSERT_TRUE(fsm.private_pairing_active);
    E87_ASSERT_TRUE(!fsm.private_button1_down);
}

E87_TEST(button1_6999_and_7000_pin_warning_boundary)
{
    struct e87_button_fsm fsm = fresh_button();

    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING,
                      step_button1_to(&fsm, UINT32_C(50), UINT32_C(6999)));
    E87_ASSERT_TRUE(!fsm.private_warning_fired);

    fsm = fresh_button();
    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING |
                          E87_ACTION_UPDATE_WARNING,
                      step_button1_to(&fsm, UINT32_C(50), UINT32_C(7000)));
    E87_ASSERT_TRUE(fsm.private_warning_fired);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(7051),
                                      E87_KEY_BUTTON1));

    fsm = fresh_button();
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(50), E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING,
                      e87_button_step(&fsm, UINT32_C(7049), E87_KEY_NONE));
    E87_ASSERT_TRUE(fsm.private_pairing_active);

    fsm = fresh_button();
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(50), E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING |
                          E87_ACTION_UPDATE_WARNING |
                          E87_ACTION_END_UPDATE_WARNING,
                      e87_button_step(&fsm, UINT32_C(7050), E87_KEY_NONE));
    E87_ASSERT_TRUE(fsm.private_pairing_active);
}

E87_TEST(button1_9999_and_10000_pin_maintenance_boundary)
{
    struct e87_button_fsm fsm = fresh_button();
    const uint32_t crossed_before =
        E87_ACTION_OPEN_PAIRING | E87_ACTION_UPDATE_WARNING;
    const uint32_t crossed_at =
        crossed_before | E87_ACTION_ENTER_MAINTENANCE;

    E87_ASSERT_EQ_U32(crossed_before,
                      step_button1_to(&fsm, UINT32_C(1000),
                                      UINT32_C(9999)));
    E87_ASSERT_TRUE(!fsm.private_maintenance_fired);
    E87_ASSERT_TRUE(fsm.private_pairing_active);

    fsm = fresh_button();
    E87_ASSERT_EQ_U32(crossed_at,
                      step_button1_to(&fsm, UINT32_C(1000),
                                      UINT32_C(10000)));
    E87_ASSERT_TRUE(fsm.private_maintenance_fired);
    E87_ASSERT_TRUE(!fsm.private_pairing_active);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(11000), E87_KEY_NONE));

    fsm = fresh_button();
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(1000), E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(crossed_before | E87_ACTION_END_UPDATE_WARNING,
                      e87_button_step(&fsm, UINT32_C(10999), E87_KEY_NONE));
    E87_ASSERT_TRUE(fsm.private_pairing_active);

    fsm = fresh_button();
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(1000), E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(crossed_at,
                      e87_button_step(&fsm, UINT32_C(11000), E87_KEY_NONE));
    E87_ASSERT_TRUE(!fsm.private_pairing_active);
}

E87_TEST(button1_release_between_pairing_and_warning_keeps_window)
{
    struct e87_button_fsm fsm = fresh_button();
    struct e87_button_view view;

    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(200), E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING,
                      e87_button_step(&fsm, UINT32_C(6700), E87_KEY_NONE));
    memset(&view, 0, sizeof(view));
    E87_ASSERT_TRUE(e87_button_get_view(&fsm, UINT32_C(6700), &view));
    E87_ASSERT_TRUE(view.pairing_active);
    E87_ASSERT_TRUE(!view.warning_active);
    E87_ASSERT_EQ_U32(UINT32_C(56500), view.pairing_remaining_ms);
    E87_ASSERT_EQ_U32(UINT32_C(0), view.warning_remaining_ms);
}

E87_TEST(button1_release_after_warning_ends_warning_and_keeps_window)
{
    struct e87_button_fsm fsm = fresh_button();
    struct e87_button_view view;
    const uint32_t expected = E87_ACTION_OPEN_PAIRING |
                              E87_ACTION_UPDATE_WARNING |
                              E87_ACTION_END_UPDATE_WARNING;

    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(500), E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(expected,
                      e87_button_step(&fsm, UINT32_C(9500), E87_KEY_NONE));
    memset(&view, 0xA5, sizeof(view));
    E87_ASSERT_TRUE(e87_button_get_view(&fsm, UINT32_C(9500), &view));
    E87_ASSERT_TRUE(view.pairing_active);
    E87_ASSERT_TRUE(!view.warning_active);
    E87_ASSERT_EQ_U32(UINT32_C(54000), view.pairing_remaining_ms);
    E87_ASSERT_EQ_U32(UINT32_C(0), view.warning_remaining_ms);
}

E87_TEST(button1_jump_emits_pair_warning_maintenance_once)
{
    struct e87_button_fsm fsm = fresh_button();
    const uint32_t expected = E87_ACTION_OPEN_PAIRING |
                              E87_ACTION_UPDATE_WARNING |
                              E87_ACTION_ENTER_MAINTENANCE;

    E87_ASSERT_EQ_U32(expected,
                      step_button1_to(&fsm, UINT32_C(1234),
                                      UINT32_C(10000)));
    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING,
                      e87_button_action_at(expected, UINT8_C(0)));
    E87_ASSERT_EQ_U32(E87_ACTION_UPDATE_WARNING,
                      e87_button_action_at(expected, UINT8_C(1)));
    E87_ASSERT_EQ_U32(E87_ACTION_ENTER_MAINTENANCE,
                      e87_button_action_at(expected, UINT8_C(2)));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_action_at(expected, UINT8_C(3)));
    E87_ASSERT_TRUE(!fsm.private_pairing_active);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(11235),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(20000), E87_KEY_NONE));
}

E87_TEST(button1_repeated_steps_never_refire_actions)
{
    struct e87_button_fsm fsm = fresh_button();

    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(0), E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(2999), E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING,
                      e87_button_step(&fsm, UINT32_C(3000), E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(6999), E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_UPDATE_WARNING,
                      e87_button_step(&fsm, UINT32_C(7000), E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(9999), E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_ENTER_MAINTENANCE,
                      e87_button_step(&fsm, UINT32_C(10000),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(16000),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(20000), E87_KEY_NONE));
}

E87_TEST(button1_new_hold_restarts_per_hold_events)
{
    struct e87_button_fsm fsm = fresh_button();

    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(100), E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_TAP_BATTERY,
                      e87_button_step(&fsm, UINT32_C(200), E87_KEY_NONE));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(1000), E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(3999), E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING,
                      e87_button_step(&fsm, UINT32_C(4000), E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(4001), E87_KEY_NONE));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(5000), E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_TAP_BATTERY,
                      e87_button_step(&fsm, UINT32_C(5001), E87_KEY_NONE));

    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(10000), E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING |
                          E87_ACTION_UPDATE_WARNING |
                          E87_ACTION_ENTER_MAINTENANCE,
                      e87_button_step(&fsm, UINT32_C(20000), E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(20001), E87_KEY_NONE));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(30000), E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING |
                          E87_ACTION_UPDATE_WARNING |
                          E87_ACTION_ENTER_MAINTENANCE,
                      e87_button_step(&fsm, UINT32_C(40000), E87_KEY_BUTTON1));
}

E87_TEST(pairing_window_expires_at_exactly_60000_ms)
{
    struct e87_button_fsm fsm = fresh_button();
    struct e87_button_view view;

    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING,
                      step_button1_to(&fsm, UINT32_C(0), UINT32_C(3000)));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(3001), E87_KEY_NONE));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(62999), E87_KEY_NONE));
    memset(&view, 0, sizeof(view));
    E87_ASSERT_TRUE(e87_button_get_view(&fsm, UINT32_C(62999), &view));
    E87_ASSERT_TRUE(view.pairing_active);
    E87_ASSERT_EQ_U32(UINT32_C(1), view.pairing_remaining_ms);
    E87_ASSERT_EQ_U32(E87_ACTION_PAIRING_EXPIRED,
                      e87_button_step(&fsm, UINT32_C(63000), E87_KEY_NONE));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(63001), E87_KEY_NONE));
    E87_ASSERT_TRUE(!fsm.private_pairing_active);
}

E87_TEST(pairing_expiry_and_same_step_reopen_order_and_restart)
{
    struct e87_button_fsm fsm = fresh_button();
    struct e87_button_view view;
    const uint32_t both = E87_ACTION_PAIRING_EXPIRED |
                          E87_ACTION_OPEN_PAIRING;

    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING,
                      step_button1_to(&fsm, UINT32_C(1000), UINT32_C(3000)));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(4001), E87_KEY_NONE));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(61000),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(both,
                      e87_button_step(&fsm, UINT32_C(64000),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_PAIRING_EXPIRED,
                      e87_button_action_at(both, UINT8_C(0)));
    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING,
                      e87_button_action_at(both, UINT8_C(1)));
    E87_ASSERT_TRUE(e87_button_get_view(&fsm, UINT32_C(64000), &view));
    E87_ASSERT_TRUE(view.pairing_active);
    E87_ASSERT_EQ_U32(UINT32_C(60000), view.pairing_remaining_ms);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(64001),
                                      E87_KEY_BUTTON1));
}

E87_TEST(button_thresholds_survive_uint32_wrap)
{
    struct e87_button_fsm fsm = fresh_button();
    const uint32_t started = UINT32_MAX - UINT32_C(1999);

    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, started, E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, started + UINT32_C(2999),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING,
                      e87_button_step(&fsm, started + UINT32_C(3000),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_UPDATE_WARNING,
                      e87_button_step(&fsm, started + UINT32_C(7000),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_ENTER_MAINTENANCE,
                      e87_button_step(&fsm, started + UINT32_C(10000),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, started + UINT32_C(10001),
                                      E87_KEY_NONE));
}

E87_TEST(pairing_expiry_survives_uint32_wrap)
{
    struct e87_button_fsm fsm = fresh_button();
    struct e87_button_view view;
    const uint32_t started = UINT32_MAX - UINT32_C(3999);
    const uint32_t opened = started + UINT32_C(3000);

    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING,
                      step_button1_to(&fsm, started, UINT32_C(3000)));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, opened + UINT32_C(1),
                                      E87_KEY_NONE));
    E87_ASSERT_TRUE(e87_button_get_view(
        &fsm, opened + UINT32_C(59999), &view));
    E87_ASSERT_TRUE(view.pairing_active);
    E87_ASSERT_EQ_U32(UINT32_C(1), view.pairing_remaining_ms);
    E87_ASSERT_EQ_U32(E87_ACTION_PAIRING_EXPIRED,
                      e87_button_step(&fsm,
                                      opened + UINT32_C(60000),
                                      E87_KEY_NONE));
}

E87_TEST(ambiguous_requires_stable_none_rearm)
{
    struct e87_button_fsm fsm = fresh_button();
    static const enum e87_key_class quarantined[] = {
        E87_KEY_BUTTON1, E87_KEY_BUTTON2, E87_KEY_AMBIGUOUS,
        (enum e87_key_class)99
    };
    static const uint32_t ambiguous_ages[] = {
        UINT32_C(2999), UINT32_C(7000), UINT32_C(10000)
    };
    static const uint32_t ambiguous_actions[] = {
        E87_ACTION_NONE,
        E87_ACTION_OPEN_PAIRING | E87_ACTION_UPDATE_WARNING |
            E87_ACTION_END_UPDATE_WARNING,
        E87_ACTION_OPEN_PAIRING | E87_ACTION_UPDATE_WARNING |
            E87_ACTION_ENTER_MAINTENANCE
    };
    size_t index;

    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(10),
                                      E87_KEY_AMBIGUOUS));
    E87_ASSERT_TRUE(fsm.private_rearm_required);
    for (index = 0U; index < sizeof(quarantined) / sizeof(quarantined[0]);
         index += 1U) {
        E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                          e87_button_step(&fsm,
                                          UINT32_C(20) + (uint32_t)index,
                                          quarantined[index]));
        E87_ASSERT_TRUE(fsm.private_rearm_required);
        E87_ASSERT_TRUE(!fsm.private_button1_down);
        E87_ASSERT_TRUE(!fsm.private_button2_down);
    }
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(30), E87_KEY_NONE));
    E87_ASSERT_TRUE(!fsm.private_rearm_required);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(40), E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_TAP_BATTERY,
                      e87_button_step(&fsm, UINT32_C(41), E87_KEY_NONE));

    for (index = 0U;
         index < sizeof(ambiguous_ages) / sizeof(ambiguous_ages[0]);
         index += 1U) {
        uint32_t actions;

        fsm = fresh_button();
        E87_ASSERT_EQ_U32(
            E87_ACTION_NONE,
            e87_button_step(&fsm, UINT32_C(1000), E87_KEY_BUTTON1));
        actions = e87_button_step(
            &fsm, UINT32_C(1000) + ambiguous_ages[index],
            E87_KEY_AMBIGUOUS);
        E87_ASSERT_EQ_U32(ambiguous_actions[index], actions);
        E87_ASSERT_EQ_U32(UINT32_C(0),
                          actions & E87_ACTION_SLEEP_TOGGLE);
        E87_ASSERT_TRUE(fsm.private_rearm_required);
        E87_ASSERT_TRUE(!fsm.private_button1_down);
        E87_ASSERT_TRUE(!fsm.private_button2_down);
        E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                          e87_button_step(&fsm, UINT32_C(12000),
                                          E87_KEY_NONE));
    }

    fsm = fresh_button();
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(100), E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING,
                      e87_button_step(&fsm, UINT32_C(3100),
                                      E87_KEY_AMBIGUOUS));
    E87_ASSERT_TRUE(fsm.private_rearm_required);
    E87_ASSERT_TRUE(!fsm.private_button1_down);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(4000),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(4001), E87_KEY_NONE));

    fsm = fresh_button();
    E87_ASSERT_EQ_U32(E87_ACTION_SLEEP_TOGGLE,
                      e87_button_step(&fsm, UINT32_C(500),
                                      E87_KEY_BUTTON2));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(501),
                                      E87_KEY_AMBIGUOUS));
    E87_ASSERT_TRUE(fsm.private_rearm_required);
    E87_ASSERT_TRUE(!fsm.private_button2_down);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(502),
                                      E87_KEY_BUTTON2));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(503), E87_KEY_NONE));
    E87_ASSERT_EQ_U32(E87_ACTION_SLEEP_TOGGLE,
                      e87_button_step(&fsm, UINT32_C(504),
                                      E87_KEY_BUTTON2));

    fsm = fresh_button();
    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING,
                      step_button1_to(&fsm, UINT32_C(0), UINT32_C(3000)));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(3001), E87_KEY_NONE));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(3002),
                                      E87_KEY_AMBIGUOUS));
    E87_ASSERT_TRUE(fsm.private_rearm_required);
    E87_ASSERT_EQ_U32(E87_ACTION_PAIRING_EXPIRED,
                      e87_button_step(&fsm, UINT32_C(63000),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_TRUE(fsm.private_rearm_required);
}

E87_TEST(button1_prethreshold_ambiguous_aborts_without_tap_and_rearms)
{
    struct e87_button_fsm fsm = fresh_button();

    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(100),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(3099),
                                      E87_KEY_AMBIGUOUS));
    E87_ASSERT_TRUE(!fsm.private_button1_down);
    E87_ASSERT_TRUE(!fsm.private_pairing_active);
    E87_ASSERT_TRUE(fsm.private_rearm_required);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(3100),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(3101),
                                      E87_KEY_BUTTON2));
    E87_ASSERT_TRUE(fsm.private_rearm_required);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(3102),
                                      E87_KEY_NONE));
    E87_ASSERT_TRUE(!fsm.private_rearm_required);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(3103),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_TAP_BATTERY,
                      e87_button_step(&fsm, UINT32_C(3104),
                                      E87_KEY_NONE));
}

E87_TEST(direct_button_changes_abort_at_2999_preserve_3000_and_rearm)
{
    struct e87_button_fsm fsm = fresh_button();

    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(1000),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(3999),
                                      E87_KEY_BUTTON2));
    E87_ASSERT_TRUE(fsm.private_rearm_required);
    E87_ASSERT_TRUE(!fsm.private_button1_down);
    E87_ASSERT_TRUE(!fsm.private_button2_down);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(4000),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(4001),
                                      E87_KEY_NONE));
    E87_ASSERT_EQ_U32(E87_ACTION_SLEEP_TOGGLE,
                      e87_button_step(&fsm, UINT32_C(4002),
                                      E87_KEY_BUTTON2));

    fsm = fresh_button();
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(5000),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING,
                      e87_button_step(&fsm, UINT32_C(8000),
                                      E87_KEY_BUTTON2));
    E87_ASSERT_TRUE(fsm.private_pairing_active);
    E87_ASSERT_TRUE(fsm.private_rearm_required);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(8001),
                                      E87_KEY_NONE));

    fsm = fresh_button();
    E87_ASSERT_EQ_U32(E87_ACTION_SLEEP_TOGGLE,
                      e87_button_step(&fsm, UINT32_C(9000),
                                      E87_KEY_BUTTON2));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(9001),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_TRUE(fsm.private_rearm_required);
    E87_ASSERT_TRUE(!fsm.private_button1_down);
    E87_ASSERT_TRUE(!fsm.private_button2_down);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(9002),
                                      E87_KEY_NONE));
    E87_ASSERT_TRUE(!fsm.private_rearm_required);
}

E87_TEST(button2_emits_one_semantic_toggle_per_press)
{
    struct e87_button_fsm fsm = fresh_button();

    E87_ASSERT_EQ_U32(E87_ACTION_SLEEP_TOGGLE,
                      e87_button_step(&fsm, UINT32_C(100),
                                      E87_KEY_BUTTON2));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(101),
                                      E87_KEY_BUTTON2));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(10000),
                                      E87_KEY_BUTTON2));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(10001), E87_KEY_NONE));
    E87_ASSERT_EQ_U32(E87_ACTION_SLEEP_TOGGLE,
                      e87_button_step(&fsm, UINT32_C(10002),
                                      E87_KEY_BUTTON2));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(10003),
                                      E87_KEY_BUTTON2));
}

E87_TEST(button_has_no_software_16_second_action_and_handles_nulls)
{
    struct e87_button_fsm actual;
    struct e87_button_fsm expected;
    struct e87_button_fsm zeroed;
    struct e87_button_view output;
    struct e87_button_view before;

    memset(&actual, 0xA5, sizeof(actual));
    e87_button_init(&actual);
    memset(&expected, 0, sizeof(expected));
    expected.private_initialized = true;
    E87_ASSERT_TRUE(bytes_equal(&expected, &actual, sizeof(actual)));
    e87_button_init(NULL);

    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING |
                          E87_ACTION_UPDATE_WARNING |
                          E87_ACTION_ENTER_MAINTENANCE,
                      step_button1_to(&actual, UINT32_C(0),
                                      UINT32_C(10000)));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&actual, UINT32_C(16000),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&actual, UINT32_C(16001),
                                      E87_KEY_NONE));

    memset(&zeroed, 0, sizeof(zeroed));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(NULL, UINT32_C(0), E87_KEY_NONE));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&zeroed, UINT32_C(0), E87_KEY_BUTTON1));
    memset(&output, 0xA5, sizeof(output));
    memcpy(&before, &output, sizeof(before));
    E87_ASSERT_TRUE(!e87_button_get_view(NULL, UINT32_C(0), &output));
    E87_ASSERT_TRUE(bytes_equal(&before, &output, sizeof(output)));
    E87_ASSERT_TRUE(!e87_button_get_view(&zeroed, UINT32_C(0), &output));
    E87_ASSERT_TRUE(bytes_equal(&before, &output, sizeof(output)));
    E87_ASSERT_TRUE(!e87_button_get_view(&actual, UINT32_C(0), NULL));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_action_at(UINT32_C(0x80), UINT8_C(0)));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_action_at(E87_ACTION_TAP_BATTERY,
                                           UINT8_MAX));
}

E87_TEST(button_view_reports_exact_pairing_countdown_without_mutation)
{
    struct e87_button_fsm fsm = fresh_button();
    struct e87_button_fsm before;
    struct e87_button_view view;
    struct e87_button_view invalid_before;
    struct e87_button_fsm zeroed;
    static const uint32_t ages[] = {
        UINT32_C(0), UINT32_C(1), UINT32_C(59999), UINT32_C(60000)
    };
    static const uint32_t remaining[] = {
        UINT32_C(60000), UINT32_C(59999), UINT32_C(1), UINT32_C(0)
    };
    static const bool active[] = {true, true, true, false};
    size_t index;

    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING,
                      step_button1_to(&fsm, UINT32_C(1000), UINT32_C(3000)));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(4000), E87_KEY_NONE));
    for (index = 0U; index < sizeof(ages) / sizeof(ages[0]); index += 1U) {
        memcpy(&before, &fsm, sizeof(before));
        memset(&view, 0xA5, sizeof(view));
        E87_ASSERT_TRUE(e87_button_get_view(
            &fsm, UINT32_C(4000) + ages[index], &view));
        E87_ASSERT_EQ_U32(active[index], view.pairing_active);
        E87_ASSERT_EQ_U32(remaining[index], view.pairing_remaining_ms);
        E87_ASSERT_EQ_U32(UINT32_C(0), view.warning_remaining_ms);
        E87_ASSERT_TRUE(bytes_equal(&before, &fsm, sizeof(fsm)));
        memset(&view, 0x5A, sizeof(view));
        E87_ASSERT_TRUE(e87_button_get_view(
            &fsm, UINT32_C(4000) + ages[index], &view));
        E87_ASSERT_EQ_U32(active[index], view.pairing_active);
        E87_ASSERT_EQ_U32(remaining[index], view.pairing_remaining_ms);
    }
    E87_ASSERT_TRUE(fsm.private_pairing_active);
    E87_ASSERT_EQ_U32(E87_ACTION_PAIRING_EXPIRED,
                      e87_button_step(&fsm, UINT32_C(64000),
                                      E87_KEY_NONE));

    memset(&zeroed, 0, sizeof(zeroed));
    memset(&view, 0xA5, sizeof(view));
    memcpy(&invalid_before, &view, sizeof(invalid_before));
    E87_ASSERT_TRUE(!e87_button_get_view(&zeroed, UINT32_C(0), &view));
    E87_ASSERT_TRUE(bytes_equal(&invalid_before, &view, sizeof(view)));
}

E87_TEST(button_view_reports_warning_countdown_and_wrap)
{
    struct e87_button_fsm fsm = fresh_button();
    struct e87_button_fsm before;
    struct e87_button_view view;
    const uint32_t started = UINT32_MAX - UINT32_C(4999);
    static const uint32_t ages[] = {
        UINT32_C(7000), UINT32_C(7001),
        UINT32_C(9999), UINT32_C(10000)
    };
    static const uint32_t remaining[] = {
        UINT32_C(3000), UINT32_C(2999), UINT32_C(1), UINT32_C(0)
    };
    static const bool active[] = {true, true, true, false};
    size_t index;

    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING |
                          E87_ACTION_UPDATE_WARNING,
                      step_button1_to(&fsm, started, UINT32_C(7000)));
    for (index = 0U; index < sizeof(ages) / sizeof(ages[0]); index += 1U) {
        memcpy(&before, &fsm, sizeof(before));
        memset(&view, 0xA5, sizeof(view));
        E87_ASSERT_TRUE(e87_button_get_view(
            &fsm, started + ages[index], &view));
        E87_ASSERT_EQ_U32(active[index], view.warning_active);
        E87_ASSERT_EQ_U32(remaining[index], view.warning_remaining_ms);
        E87_ASSERT_TRUE(bytes_equal(&before, &fsm, sizeof(fsm)));
    }
    E87_ASSERT_EQ_U32(E87_ACTION_ENTER_MAINTENANCE,
                      e87_button_step(&fsm, started + UINT32_C(10000),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_TRUE(e87_button_get_view(
        &fsm, started + UINT32_C(10000), &view));
    E87_ASSERT_TRUE(!view.warning_active);
    E87_ASSERT_EQ_U32(UINT32_C(0), view.warning_remaining_ms);

    fsm = fresh_button();
    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING |
                          E87_ACTION_UPDATE_WARNING,
                      step_button1_to(&fsm, UINT32_C(0), UINT32_C(7000)));
    E87_ASSERT_EQ_U32(E87_ACTION_END_UPDATE_WARNING,
                      e87_button_step(&fsm, UINT32_C(7001), E87_KEY_NONE));
    E87_ASSERT_TRUE(e87_button_get_view(&fsm, UINT32_C(7001), &view));
    E87_ASSERT_TRUE(!view.warning_active);
}

E87_TEST(button_action_order_is_total_and_b1_to_b2_requires_rearm)
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
    static const uint32_t ages[] = {
        UINT32_C(2999), UINT32_C(7000), UINT32_C(10000)
    };
    static const uint32_t transition_masks[] = {
        E87_ACTION_NONE,
        E87_ACTION_OPEN_PAIRING | E87_ACTION_UPDATE_WARNING |
            E87_ACTION_END_UPDATE_WARNING,
        E87_ACTION_OPEN_PAIRING | E87_ACTION_UPDATE_WARNING |
            E87_ACTION_ENTER_MAINTENANCE
    };
    uint32_t mask;
    size_t index;

    for (mask = UINT32_C(0); mask <= UINT32_C(127); mask += UINT32_C(1)) {
        uint8_t ordinal = UINT8_C(0);

        for (index = 0U; index < sizeof(priority) / sizeof(priority[0]);
             index += 1U) {
            if ((mask & (uint32_t)priority[index]) != UINT32_C(0)) {
                E87_ASSERT_EQ_U32(priority[index],
                                  e87_button_action_at(mask, ordinal));
                ordinal = (uint8_t)(ordinal + UINT8_C(1));
            }
        }
        E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                          e87_button_action_at(mask, ordinal));
        E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                          e87_button_action_at(mask, UINT8_MAX));
        E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                          e87_button_action_at(mask | UINT32_C(0x80),
                                               UINT8_C(0)));
    }
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_action_at(UINT32_MAX, UINT8_C(0)));

    for (index = 0U; index < sizeof(ages) / sizeof(ages[0]); index += 1U) {
        struct e87_button_fsm fsm = fresh_button();
        uint32_t actions;

        E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                          e87_button_step(&fsm, UINT32_C(1000),
                                          E87_KEY_BUTTON1));
        actions = e87_button_step(&fsm, UINT32_C(1000) + ages[index],
                                  E87_KEY_BUTTON2);
        E87_ASSERT_EQ_U32(transition_masks[index], actions);
        E87_ASSERT_EQ_U32(UINT32_C(0),
                          actions & E87_ACTION_SLEEP_TOGGLE);
        E87_ASSERT_TRUE(fsm.private_rearm_required);
        E87_ASSERT_TRUE(!fsm.private_button1_down);
        E87_ASSERT_TRUE(!fsm.private_button2_down);
        E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                          e87_button_step(&fsm,
                                          UINT32_C(12000) + (uint32_t)index,
                                          E87_KEY_BUTTON2));
        E87_ASSERT_TRUE(fsm.private_rearm_required);
        E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                          e87_button_step(&fsm,
                                          UINT32_C(13000) + (uint32_t)index,
                                          E87_KEY_NONE));
        E87_ASSERT_TRUE(!fsm.private_rearm_required);
        E87_ASSERT_EQ_U32(E87_ACTION_SLEEP_TOGGLE,
                          e87_button_step(&fsm,
                                          UINT32_C(14000) + (uint32_t)index,
                                          E87_KEY_BUTTON2));
    }
}

E87_TEST(b2_to_b1_and_undefined_require_rearm_without_inheritance)
{
    struct e87_button_fsm fsm = fresh_button();
    struct e87_button_view view;
    static const uint32_t invalid_ages[] = {
        UINT32_C(2999), UINT32_C(3000),
        UINT32_C(6999), UINT32_C(7000),
        UINT32_C(9999), UINT32_C(10000)
    };
    const enum e87_key_class undefined_key = (enum e87_key_class)99;
    size_t index;

    E87_ASSERT_EQ_U32(E87_ACTION_SLEEP_TOGGLE,
                      e87_button_step(&fsm, UINT32_C(100),
                                      E87_KEY_BUTTON2));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(101),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_TRUE(fsm.private_rearm_required);
    E87_ASSERT_TRUE(!fsm.private_button1_down);
    E87_ASSERT_TRUE(!fsm.private_button2_down);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(20000),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_TRUE(!fsm.private_button1_down);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(20001), E87_KEY_NONE));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(30000),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(32999),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING,
                      e87_button_step(&fsm, UINT32_C(33000),
                                      E87_KEY_BUTTON1));

    for (index = 0U;
         index < sizeof(invalid_ages) / sizeof(invalid_ages[0]);
         index += 1U) {
        fsm = fresh_button();
        E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                          e87_button_step(&fsm, UINT32_C(1000),
                                          E87_KEY_BUTTON1));
        E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                          e87_button_step(&fsm,
                                          UINT32_C(1000) +
                                              invalid_ages[index],
                                          undefined_key));
        E87_ASSERT_TRUE(fsm.private_rearm_required);
        E87_ASSERT_TRUE(!fsm.private_button1_down);
        E87_ASSERT_TRUE(!fsm.private_pairing_active);
        E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                          e87_button_step(&fsm, UINT32_C(20000),
                                          E87_KEY_BUTTON1));
        E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                          e87_button_step(&fsm, UINT32_C(20001),
                                          E87_KEY_NONE));
    }

    fsm = fresh_button();
    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING |
                          E87_ACTION_UPDATE_WARNING,
                      step_button1_to(&fsm, UINT32_C(0), UINT32_C(7000)));
    E87_ASSERT_EQ_U32(E87_ACTION_END_UPDATE_WARNING,
                      e87_button_step(&fsm, UINT32_C(7001),
                                      undefined_key));
    E87_ASSERT_TRUE(fsm.private_pairing_active);
    E87_ASSERT_TRUE(fsm.private_rearm_required);
    E87_ASSERT_TRUE(e87_button_get_view(&fsm, UINT32_C(7001), &view));
    E87_ASSERT_TRUE(view.pairing_active);
    E87_ASSERT_EQ_U32(UINT32_C(55999),
                      view.pairing_remaining_ms);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(7002),
                                      undefined_key));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(7003),
                                      E87_KEY_NONE));
    E87_ASSERT_TRUE(!fsm.private_rearm_required);

    fsm = fresh_button();
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(1), undefined_key));
    E87_ASSERT_TRUE(fsm.private_rearm_required);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(2), E87_KEY_BUTTON2));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(3), E87_KEY_NONE));
    E87_ASSERT_TRUE(!fsm.private_rearm_required);
    E87_ASSERT_EQ_U32(E87_ACTION_SLEEP_TOGGLE,
                      e87_button_step(&fsm, UINT32_C(4),
                                      E87_KEY_BUTTON2));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(5), E87_KEY_NONE));

    fsm = fresh_button();
    E87_ASSERT_EQ_U32(E87_ACTION_SLEEP_TOGGLE,
                      e87_button_step(&fsm, UINT32_C(10),
                                      E87_KEY_BUTTON2));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(11), undefined_key));
    E87_ASSERT_TRUE(fsm.private_rearm_required);
    E87_ASSERT_TRUE(!fsm.private_button2_down);

    fsm = fresh_button();
    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING,
                      step_button1_to(&fsm, UINT32_C(0), UINT32_C(3000)));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(3001), E87_KEY_NONE));
    E87_ASSERT_EQ_U32(E87_ACTION_PAIRING_EXPIRED,
                      e87_button_step(&fsm, UINT32_C(63000),
                                      undefined_key));
    E87_ASSERT_TRUE(fsm.private_rearm_required);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(63001),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_C(63002),
                                      E87_KEY_NONE));
}

static const struct e87_test_case button_cases[] = {
    E87_TEST_CASE(button_constants_pin_exact_thresholds),
    E87_TEST_CASE(button1_release_2999_is_tap_and_3000_is_pairing),
    E87_TEST_CASE(button1_6999_and_7000_pin_warning_boundary),
    E87_TEST_CASE(button1_9999_and_10000_pin_maintenance_boundary),
    E87_TEST_CASE(button1_release_between_pairing_and_warning_keeps_window),
    E87_TEST_CASE(button1_release_after_warning_ends_warning_and_keeps_window),
    E87_TEST_CASE(button1_jump_emits_pair_warning_maintenance_once),
    E87_TEST_CASE(button1_repeated_steps_never_refire_actions),
    E87_TEST_CASE(button1_new_hold_restarts_per_hold_events),
    E87_TEST_CASE(pairing_window_expires_at_exactly_60000_ms),
    E87_TEST_CASE(pairing_expiry_and_same_step_reopen_order_and_restart),
    E87_TEST_CASE(button_thresholds_survive_uint32_wrap),
    E87_TEST_CASE(pairing_expiry_survives_uint32_wrap),
    E87_TEST_CASE(ambiguous_requires_stable_none_rearm),
    E87_TEST_CASE(button1_prethreshold_ambiguous_aborts_without_tap_and_rearms),
    E87_TEST_CASE(direct_button_changes_abort_at_2999_preserve_3000_and_rearm),
    E87_TEST_CASE(button2_emits_one_semantic_toggle_per_press),
    E87_TEST_CASE(button_has_no_software_16_second_action_and_handles_nulls),
    E87_TEST_CASE(button_view_reports_exact_pairing_countdown_without_mutation),
    E87_TEST_CASE(button_view_reports_warning_countdown_and_wrap),
    E87_TEST_CASE(button_action_order_is_total_and_b1_to_b2_requires_rearm),
    E87_TEST_CASE(b2_to_b1_and_undefined_require_rearm_without_inheritance),
};

const struct e87_test_suite e87_test_suite = {
    "button-fsm",
    button_cases,
    sizeof(button_cases) / sizeof(button_cases[0]),
};
