#include "test_support.h"
#include "e87/e87_power_policy.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define FAKE_COMMAND_CAPACITY 4096U

struct fake_sink {
    struct e87_power_policy *policy;
    enum e87_power_command commands[FAKE_COMMAND_CAPACITY];
    size_t count;
    bool reenter;
    bool reentry_attempted;
    bool inside_reentry;
    struct e87_power_event reentry_event;
    enum e87_power_result reentry_result;
    size_t nested_emit_count;
};

static struct e87_charge_snapshot snapshot(
    bool online, enum e87_charge_phase phase)
{
    const struct e87_charge_snapshot value = { online, phase };
    return value;
}

static struct e87_power_event charge_event(
    struct e87_charge_snapshot value)
{
    const struct e87_power_event event = {
        E87_POWER_EVENT_CHARGE_SNAPSHOT,
        value,
        E87_POWER_WAKE_NONE
    };
    return event;
}

static struct e87_power_event ordinary_event(
    enum e87_power_event_type type,
    enum e87_power_wake_classification classification)
{
    const struct e87_power_event event = {
        type,
        { false, E87_CHARGE_PHASE_UNKNOWN },
        classification
    };
    return event;
}

static bool bytes_equal(const void *left, const void *right, size_t length)
{
    return memcmp(left, right, length) == 0;
}

static void reset_sink(struct fake_sink *sink)
{
    memset(sink, 0, sizeof(*sink));
    sink->reentry_result = E87_POWER_RESULT_NO_CHANGE;
}

static bool fake_emit(void *context, enum e87_power_command command)
{
    struct fake_sink *sink = (struct fake_sink *)context;
    size_t index = sink->count;

    if (index >= FAKE_COMMAND_CAPACITY) {
        return false;
    }
    sink->commands[index] = command;
    sink->count = index + 1U;
    if (sink->reenter && !sink->reentry_attempted) {
        sink->reentry_attempted = true;
        sink->inside_reentry = true;
        sink->reentry_result = e87_power_policy_step(
            sink->policy, &sink->reentry_event);
        sink->inside_reentry = false;
    }
    if (sink->inside_reentry) {
        sink->nested_emit_count += 1U;
    }
    return true;
}

static bool init_policy(struct e87_power_policy *policy,
                        struct fake_sink *sink,
                        struct e87_charge_snapshot initial)
{
    const struct e87_power_port port = { sink, fake_emit };

    reset_sink(sink);
    sink->policy = policy;
    memset(policy, 0xA5, sizeof(*policy));
    return e87_power_policy_init(policy, &port, &initial);
}

static enum e87_power_result step(
    struct e87_power_policy *policy,
    struct fake_sink *sink,
    const struct e87_power_event *event)
{
    (void)sink;
    return e87_power_policy_step(policy, event);
}

static bool enter_asleep(struct e87_power_policy *policy,
                         struct fake_sink *sink)
{
    const struct e87_power_event manual = ordinary_event(
        E87_POWER_EVENT_MANUAL_SLEEP, E87_POWER_WAKE_NONE);
    const struct e87_power_event idle = ordinary_event(
        E87_POWER_EVENT_LCD_IDLE, E87_POWER_WAKE_NONE);

    return step(policy, sink, &manual) == E87_POWER_RESULT_WAITING_FOR_LCD &&
           step(policy, sink, &idle) == E87_POWER_RESULT_ASLEEP;
}

static bool begin_wake(struct e87_power_policy *policy,
                       struct fake_sink *sink)
{
    const struct e87_power_event wake = ordinary_event(
        E87_POWER_EVENT_GPIO_WAKE, E87_POWER_WAKE_NONE);

    return step(policy, sink, &wake) ==
               E87_POWER_RESULT_WAITING_FOR_WAKE_CLASSIFICATION;
}

E87_TEST(snapshot_init_uses_one_complete_task2_value)
{
    struct e87_power_policy policy;
    struct e87_power_policy before;
    struct e87_power_port invalid;
    struct fake_sink sink;
    struct e87_power_view view;
    const struct e87_charge_snapshot initial =
        snapshot(true, E87_CHARGE_PHASE_FAULT);

    reset_sink(&sink);
    memset(&policy, 0xA5, sizeof(policy));
    before = policy;
    invalid.context = &sink;
    invalid.emit = NULL;
    E87_ASSERT_TRUE(!e87_power_policy_init(NULL, &invalid, &initial));
    E87_ASSERT_TRUE(!e87_power_policy_init(&policy, NULL, &initial));
    E87_ASSERT_TRUE(!e87_power_policy_init(&policy, &invalid, &initial));
    E87_ASSERT_TRUE(!e87_power_policy_init(&policy, &invalid, NULL));
    E87_ASSERT_TRUE(bytes_equal(&policy, &before, sizeof(policy)));

    E87_ASSERT_TRUE(init_policy(&policy, &sink, initial));
    E87_ASSERT_TRUE(e87_power_policy_get_view(&policy, &view));
    E87_ASSERT_EQ_U32(E87_POWER_STATE_ACTIVE, view.state);
    E87_ASSERT_TRUE(view.charge_snapshot.external_power_online);
    E87_ASSERT_EQ_U32(E87_CHARGE_PHASE_FAULT, view.charge_snapshot.phase);
}

E87_TEST(all_states_phases_and_online_bits_update_atomically_without_commands)
{
    static const enum e87_power_state states[] = {
        E87_POWER_STATE_ACTIVE,
        E87_POWER_STATE_WAIT_LCD_IDLE,
        E87_POWER_STATE_ASLEEP,
        E87_POWER_STATE_WAIT_WAKE_CLASSIFICATION
    };
    static const enum e87_charge_phase phases[] = {
        E87_CHARGE_PHASE_UNKNOWN,
        E87_CHARGE_PHASE_CHARGING,
        E87_CHARGE_PHASE_FULL,
        E87_CHARGE_PHASE_CLOSED,
        E87_CHARGE_PHASE_FAULT
    };
    struct e87_power_policy policy;
    struct fake_sink sink;
    struct e87_power_view view;
    size_t state_index;
    size_t phase_index;
    unsigned int online;

    E87_ASSERT_TRUE(init_policy(
        &policy, &sink, snapshot(false, E87_CHARGE_PHASE_UNKNOWN)));
    for (state_index = 0U; state_index < sizeof(states) / sizeof(states[0]);
         state_index += 1U) {
        policy.private_state = states[state_index];
        for (phase_index = 0U;
             phase_index < sizeof(phases) / sizeof(phases[0]);
             phase_index += 1U) {
            for (online = 0U; online < 2U; online += 1U) {
                const struct e87_charge_snapshot next = snapshot(
                    online != 0U, phases[phase_index]);
                const struct e87_power_event event = charge_event(next);
                const enum e87_power_result expected =
                    (next.external_power_online ==
                         policy.private_charge_snapshot.external_power_online &&
                     next.phase == policy.private_charge_snapshot.phase)
                        ? E87_POWER_RESULT_NO_CHANGE
                        : E87_POWER_RESULT_STATUS_UPDATED;
                const size_t before_commands = sink.count;

                E87_ASSERT_EQ_U32(expected, step(&policy, &sink, &event));
                E87_ASSERT_EQ_U32(before_commands, sink.count);
                E87_ASSERT_TRUE(e87_power_policy_get_view(&policy, &view));
                E87_ASSERT_TRUE(view.charge_snapshot.external_power_online ==
                                next.external_power_online);
                E87_ASSERT_EQ_U32(next.phase, view.charge_snapshot.phase);
                E87_ASSERT_EQ_U32(states[state_index], view.state);
            }
        }
    }

    policy.private_state = E87_POWER_STATE_ERROR;
    {
        static const enum e87_charge_phase error_phases[] = {
            E87_CHARGE_PHASE_UNKNOWN,
            E87_CHARGE_PHASE_CHARGING,
            E87_CHARGE_PHASE_FULL,
            E87_CHARGE_PHASE_CLOSED,
            E87_CHARGE_PHASE_FAULT
        };
        size_t error_index;

        for (error_index = 0U;
             error_index < sizeof(error_phases) / sizeof(error_phases[0]);
             error_index += 1U) {
            const struct e87_power_policy before = policy;
            const struct e87_power_event event = charge_event(snapshot(
                error_index % 2U != 0U, error_phases[error_index]));
            const size_t before_commands = sink.count;
            E87_ASSERT_EQ_U32(E87_POWER_RESULT_ERROR,
                              step(&policy, &sink, &event));
            E87_ASSERT_EQ_U32(before_commands, sink.count);
            E87_ASSERT_TRUE(bytes_equal(&policy, &before, sizeof(policy)));
        }
    }
}

E87_TEST(invalid_snapshot_phase_is_rejected_without_any_mutation)
{
    static const enum e87_power_state states[] = {
        E87_POWER_STATE_ACTIVE,
        E87_POWER_STATE_WAIT_LCD_IDLE,
        E87_POWER_STATE_ASLEEP,
        E87_POWER_STATE_WAIT_WAKE_CLASSIFICATION
    };
    struct e87_power_policy policy;
    struct fake_sink sink;
    struct e87_power_view view_before;
    struct e87_power_view view_after;
    size_t index;

    E87_ASSERT_TRUE(init_policy(
        &policy, &sink, snapshot(true, E87_CHARGE_PHASE_CHARGING)));
    for (index = 0U; index < sizeof(states) / sizeof(states[0]);
         index += 1U) {
        const struct e87_power_event event = charge_event(
            snapshot(false, (enum e87_charge_phase)UINT8_MAX));

        policy.private_state = states[index];
        E87_ASSERT_TRUE(e87_power_policy_get_view(&policy, &view_before));
        {
            const struct e87_power_policy state_before = policy;
            E87_ASSERT_EQ_U32(E87_POWER_RESULT_ERROR,
                              step(&policy, &sink, &event));
            E87_ASSERT_EQ_U32(UINT32_C(0), sink.count);
            E87_ASSERT_TRUE(bytes_equal(&policy, &state_before,
                                         sizeof(policy)));
            E87_ASSERT_TRUE(e87_power_policy_get_view(&policy, &view_after));
            E87_ASSERT_TRUE(bytes_equal(&view_before, &view_after,
                                         sizeof(view_before)));
        }
    }
}

E87_TEST(charge_snapshots_preserve_manual_sleep_through_every_phase)
{
    static const enum e87_charge_phase phases[] = {
        E87_CHARGE_PHASE_UNKNOWN,
        E87_CHARGE_PHASE_CHARGING,
        E87_CHARGE_PHASE_FULL,
        E87_CHARGE_PHASE_CLOSED,
        E87_CHARGE_PHASE_FAULT
    };
    struct e87_power_policy policy;
    struct fake_sink sink;
    struct e87_power_view view;
    size_t index;
    const size_t presentation_commands = 2U + 5U + 1U + 4U;

    E87_ASSERT_TRUE(init_policy(
        &policy, &sink, snapshot(false, E87_CHARGE_PHASE_UNKNOWN)));
    E87_ASSERT_TRUE(enter_asleep(&policy, &sink));
    for (index = 0U; index < sizeof(phases) / sizeof(phases[0]);
         index += 1U) {
        const struct e87_power_event event = charge_event(
            snapshot(index % 2U != 0U, phases[index]));
        const size_t before_commands = sink.count;

        E87_ASSERT_EQ_U32(index == 0U ? E87_POWER_RESULT_NO_CHANGE
                                      : E87_POWER_RESULT_STATUS_UPDATED,
                          step(&policy, &sink, &event));
        E87_ASSERT_EQ_U32(before_commands, sink.count);
        E87_ASSERT_EQ_U32(E87_POWER_STATE_ASLEEP, policy.private_state);
    }
    E87_ASSERT_TRUE(begin_wake(&policy, &sink));
    for (index = 0U; index < sizeof(phases) / sizeof(phases[0]);
         index += 1U) {
        const struct e87_power_event event = charge_event(
            snapshot(index % 2U == 0U, phases[index]));
        const size_t before_commands = sink.count;

        E87_ASSERT_EQ_U32(E87_POWER_RESULT_STATUS_UPDATED,
                          step(&policy, &sink, &event));
        E87_ASSERT_EQ_U32(before_commands, sink.count);
        E87_ASSERT_EQ_U32(E87_POWER_STATE_WAIT_WAKE_CLASSIFICATION,
                          policy.private_state);
    }
    {
        const struct e87_power_event classified = ordinary_event(
            E87_POWER_EVENT_WAKE_CLASSIFIED, E87_POWER_WAKE_BUTTON2);
        E87_ASSERT_EQ_U32(E87_POWER_RESULT_ACTIVE,
                          step(&policy, &sink, &classified));
    }
    E87_ASSERT_TRUE(e87_power_policy_get_view(&policy, &view));
    E87_ASSERT_EQ_U32(E87_POWER_STATE_ACTIVE, view.state);
    E87_ASSERT_EQ_U32(presentation_commands, sink.count);
}

E87_TEST(presentation_sequences_remain_exact_and_charge_has_no_commands)
{
    static const enum e87_power_command sleep_start[] = {
        E87_POWER_COMMAND_STOP_DRAWS,
        E87_POWER_COMMAND_WAIT_LCD_IDLE,
        E87_POWER_COMMAND_PANEL_SLEEP,
        E87_POWER_COMMAND_BACKLIGHT_OFF,
        E87_POWER_COMMAND_BLE_STOP_DISCONNECT,
        E87_POWER_COMMAND_ARM_SHARED_LADDER_WAKE,
        E87_POWER_COMMAND_ENTER_LOW_POWER
    };
    static const enum e87_power_command wake[] = {
        E87_POWER_COMMAND_RESUME_ADC,
        E87_POWER_COMMAND_DISPLAY_EXIT_SLEEP,
        E87_POWER_COMMAND_REDRAW,
        E87_POWER_COMMAND_BACKLIGHT_ON,
        E87_POWER_COMMAND_BLE_START
    };
    struct e87_power_policy policy;
    struct fake_sink sink;
    size_t index;

    E87_ASSERT_TRUE(init_policy(
        &policy, &sink, snapshot(true, E87_CHARGE_PHASE_CHARGING)));
    {
        const struct e87_power_event manual = ordinary_event(
            E87_POWER_EVENT_MANUAL_SLEEP, E87_POWER_WAKE_NONE);
        const struct e87_power_event idle = ordinary_event(
            E87_POWER_EVENT_LCD_IDLE, E87_POWER_WAKE_NONE);
        E87_ASSERT_EQ_U32(E87_POWER_RESULT_WAITING_FOR_LCD,
                          step(&policy, &sink, &manual));
        E87_ASSERT_EQ_U32(E87_POWER_RESULT_ASLEEP,
                          step(&policy, &sink, &idle));
    }
    E87_ASSERT_TRUE(begin_wake(&policy, &sink));
    {
        const struct e87_power_event classified = ordinary_event(
            E87_POWER_EVENT_WAKE_CLASSIFIED, E87_POWER_WAKE_BUTTON2);
        E87_ASSERT_EQ_U32(E87_POWER_RESULT_ACTIVE,
                          step(&policy, &sink, &classified));
    }
    E87_ASSERT_EQ_U32(sizeof(sleep_start) / sizeof(sleep_start[0]) +
                          sizeof(wake) / sizeof(wake[0]),
                      sink.count);
    for (index = 0U; index < sizeof(sleep_start) / sizeof(sleep_start[0]);
         index += 1U) {
        E87_ASSERT_EQ_U32(sleep_start[index], sink.commands[index]);
    }
    for (index = 0U; index < sizeof(wake) / sizeof(wake[0]); index += 1U) {
        E87_ASSERT_EQ_U32(wake[index], sink.commands[
            sizeof(sleep_start) / sizeof(sleep_start[0]) + index]);
    }
}

E87_TEST(invalid_input_and_reentry_are_rejected_without_latching)
{
    struct e87_power_policy policy;
    struct fake_sink sink;
    struct e87_power_event event;
    struct e87_power_view view;

    E87_ASSERT_TRUE(init_policy(
        &policy, &sink, snapshot(false, E87_CHARGE_PHASE_UNKNOWN)));
    event = ordinary_event((enum e87_power_event_type)UINT8_MAX,
                           E87_POWER_WAKE_NONE);
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_ERROR,
                      step(&policy, &sink, &event));
    event = ordinary_event(E87_POWER_EVENT_WAKE_CLASSIFIED,
                           (enum e87_power_wake_classification)UINT8_MAX);
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_ERROR,
                      step(&policy, &sink, &event));
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.count);

    sink.reenter = true;
    sink.reentry_event = charge_event(
        snapshot(true, E87_CHARGE_PHASE_FAULT));
    event = ordinary_event(E87_POWER_EVENT_MANUAL_SLEEP,
                           E87_POWER_WAKE_NONE);
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_WAITING_FOR_LCD,
                      step(&policy, &sink, &event));
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_ERROR, sink.reentry_result);
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.nested_emit_count);
    E87_ASSERT_TRUE(e87_power_policy_get_view(&policy, &view));
    E87_ASSERT_EQ_U32(E87_CHARGE_PHASE_UNKNOWN, view.charge_snapshot.phase);
}

E87_TEST(charge_command_enum_contains_only_presentation_commands)
{
    _Static_assert(E87_POWER_COMMAND_STOP_DRAWS == 0, "command anchor");
    _Static_assert(E87_POWER_COMMAND_WAIT_LCD_IDLE == 1, "command anchor");
    _Static_assert(E87_POWER_COMMAND_PANEL_SLEEP == 2, "command anchor");
    _Static_assert(E87_POWER_COMMAND_BLE_START == 11, "command anchor");
    _Static_assert(E87_POWER_COMMAND_COUNT == 12, "no electrical command");
    E87_ASSERT_TRUE(E87_POWER_COMMAND_BLE_START < 12);
}

static const struct e87_test_case power_policy_cases[] = {
    E87_TEST_CASE(snapshot_init_uses_one_complete_task2_value),
    E87_TEST_CASE(all_states_phases_and_online_bits_update_atomically_without_commands),
    E87_TEST_CASE(invalid_snapshot_phase_is_rejected_without_any_mutation),
    E87_TEST_CASE(charge_snapshots_preserve_manual_sleep_through_every_phase),
    E87_TEST_CASE(presentation_sequences_remain_exact_and_charge_has_no_commands),
    E87_TEST_CASE(invalid_input_and_reentry_are_rejected_without_latching),
    E87_TEST_CASE(charge_command_enum_contains_only_presentation_commands)
};

const struct e87_test_suite e87_test_suite = {
    "power-policy",
    power_policy_cases,
    sizeof(power_policy_cases) / sizeof(power_policy_cases[0])
};
