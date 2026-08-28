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
    size_t step_start;
    size_t reject_index;
    bool false_returned;
    size_t calls_after_false;
    bool reenter;
    size_t reentry_index;
    bool reentry_attempted;
    bool inside_reentry;
    struct e87_power_event reentry_event;
    enum e87_power_result reentry_result;
    size_t nested_emit_count;
    bool overflow;
};

static bool bytes_equal(const void *left, const void *right, size_t length)
{
    return memcmp(left, right, length) == 0;
}

static struct e87_power_event power_event(
    enum e87_power_event_type type,
    bool external_power_online,
    enum e87_power_wake_classification wake_classification)
{
    const struct e87_power_event event = {
        type, external_power_online, wake_classification
    };

    return event;
}

static void reset_sink(struct fake_sink *sink)
{
    memset(sink, 0, sizeof(*sink));
    sink->reject_index = SIZE_MAX;
    sink->reentry_index = SIZE_MAX;
    sink->reentry_result = E87_POWER_RESULT_NO_CHANGE;
}

static bool fake_emit(void *context, enum e87_power_command command)
{
    struct fake_sink *sink = (struct fake_sink *)context;
    size_t index;

    if (sink->false_returned) {
        sink->calls_after_false += 1U;
    }
    if (sink->count >= FAKE_COMMAND_CAPACITY) {
        sink->overflow = true;
        return false;
    }
    index = sink->count;
    sink->commands[index] = command;
    sink->count += 1U;
    if (sink->inside_reentry) {
        sink->nested_emit_count += 1U;
    }
    if (sink->reenter && !sink->reentry_attempted &&
        index == sink->reentry_index) {
        sink->reentry_attempted = true;
        sink->inside_reentry = true;
        sink->reentry_result =
            e87_power_policy_step(sink->policy, &sink->reentry_event);
        sink->inside_reentry = false;
    }
    if (index == sink->reject_index) {
        sink->false_returned = true;
        return false;
    }
    return true;
}

static bool init_policy(struct e87_power_policy *policy,
                        struct fake_sink *sink,
                        bool external_power_online)
{
    struct e87_power_port port;

    reset_sink(sink);
    sink->policy = policy;
    port.context = sink;
    port.emit = fake_emit;
    memset(policy, 0xA5, sizeof(*policy));
    return e87_power_policy_init(policy, &port, external_power_online);
}

static void begin_step(struct fake_sink *sink, size_t reject_ordinal)
{
    sink->step_start = sink->count;
    sink->false_returned = false;
    sink->calls_after_false = 0U;
    sink->reject_index = reject_ordinal == SIZE_MAX
                             ? SIZE_MAX
                             : sink->count + reject_ordinal;
}

static size_t step_command_count(const struct fake_sink *sink)
{
    return sink->count - sink->step_start;
}

static enum e87_power_result accept_step(
    struct e87_power_policy *policy,
    struct fake_sink *sink,
    const struct e87_power_event *event)
{
    begin_step(sink, SIZE_MAX);
    return e87_power_policy_step(policy, event);
}

static bool enter_asleep(struct e87_power_policy *policy,
                         struct fake_sink *sink)
{
    const struct e87_power_event manual_sleep =
        power_event(E87_POWER_EVENT_MANUAL_SLEEP, false,
                    E87_POWER_WAKE_NONE);
    const struct e87_power_event lcd_idle =
        power_event(E87_POWER_EVENT_LCD_IDLE, false,
                    E87_POWER_WAKE_NONE);

    return accept_step(policy, sink, &manual_sleep) ==
               E87_POWER_RESULT_WAITING_FOR_LCD &&
           accept_step(policy, sink, &lcd_idle) ==
               E87_POWER_RESULT_ASLEEP &&
           policy->private_state == E87_POWER_STATE_ASLEEP;
}

static bool begin_gpio_wake(struct e87_power_policy *policy,
                            struct fake_sink *sink)
{
    const struct e87_power_event gpio_wake =
        power_event(E87_POWER_EVENT_GPIO_WAKE, false,
                    E87_POWER_WAKE_NONE);

    return accept_step(policy, sink, &gpio_wake) ==
               E87_POWER_RESULT_WAITING_FOR_WAKE_CLASSIFICATION &&
           policy->private_state ==
               E87_POWER_STATE_WAIT_WAKE_CLASSIFICATION;
}

E87_TEST(init_rejects_invalid_port_without_mutation)
{
    struct e87_power_policy policy;
    struct e87_power_policy before;
    struct e87_power_port invalid_port;
    struct e87_power_port null_context_port;
    struct e87_power_view view;
    struct fake_sink sink;

    reset_sink(&sink);
    memset(&policy, 0xA5, sizeof(policy));
    before = policy;
    E87_ASSERT_TRUE(!e87_power_policy_init(NULL, NULL, false));
    E87_ASSERT_TRUE(!e87_power_policy_init(&policy, NULL, false));
    E87_ASSERT_TRUE(bytes_equal(&policy, &before, sizeof(policy)));
    invalid_port.context = &sink;
    invalid_port.emit = NULL;
    E87_ASSERT_TRUE(!e87_power_policy_init(&policy, &invalid_port, false));
    E87_ASSERT_TRUE(bytes_equal(&policy, &before, sizeof(policy)));

    null_context_port.context = NULL;
    null_context_port.emit = fake_emit;
    E87_ASSERT_TRUE(e87_power_policy_init(
        &policy, &null_context_port, true));
    E87_ASSERT_TRUE(policy.private_initialized);
    E87_ASSERT_TRUE(!policy.private_in_step);
    E87_ASSERT_EQ_U32(E87_POWER_STATE_ACTIVE, policy.private_state);
    E87_ASSERT_TRUE(policy.private_external_power_online);
    E87_ASSERT_EQ_U32(E87_CHARGER_PHASE_UNKNOWN,
                      policy.private_charger_phase);
    E87_ASSERT_TRUE(!e87_power_policy_get_view(NULL, &view));
    E87_ASSERT_TRUE(!e87_power_policy_get_view(&policy, NULL));
    E87_ASSERT_TRUE(e87_power_policy_get_view(&policy, &view));
    E87_ASSERT_EQ_U32(E87_POWER_STATE_ACTIVE, view.state);
    E87_ASSERT_TRUE(view.external_power_online);
    E87_ASSERT_EQ_U32(E87_CHARGER_PHASE_UNKNOWN, view.charger_phase);
}

E87_TEST(external_power_is_independent_from_charger_phase)
{
    struct e87_power_policy policy;
    struct fake_sink sink;
    struct e87_power_view view;
    struct e87_power_event event;

    E87_ASSERT_TRUE(init_policy(&policy, &sink, false));
    event = power_event(E87_POWER_EVENT_CHARGER_START, true,
                        E87_POWER_WAKE_BUTTON2);
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_STATUS_UPDATED,
                      accept_step(&policy, &sink, &event));
    E87_ASSERT_TRUE(e87_power_policy_get_view(&policy, &view));
    E87_ASSERT_TRUE(!view.external_power_online);
    E87_ASSERT_EQ_U32(E87_CHARGER_PHASE_START, view.charger_phase);
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.count);

    event = power_event(E87_POWER_EVENT_EXTERNAL_POWER_CHANGED, true,
                        E87_POWER_WAKE_NOISE);
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_STATUS_UPDATED,
                      accept_step(&policy, &sink, &event));
    E87_ASSERT_TRUE(e87_power_policy_get_view(&policy, &view));
    E87_ASSERT_TRUE(view.external_power_online);
    E87_ASSERT_EQ_U32(E87_CHARGER_PHASE_START, view.charger_phase);

    event = power_event(E87_POWER_EVENT_CHARGER_CLOSE, false,
                        E87_POWER_WAKE_NONE);
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_STATUS_UPDATED,
                      accept_step(&policy, &sink, &event));
    E87_ASSERT_TRUE(e87_power_policy_get_view(&policy, &view));
    E87_ASSERT_TRUE(view.external_power_online);
    E87_ASSERT_EQ_U32(E87_CHARGER_PHASE_CLOSE, view.charger_phase);

    event = power_event(E87_POWER_EVENT_EXTERNAL_POWER_CHANGED, false,
                        E87_POWER_WAKE_BUTTON1);
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_STATUS_UPDATED,
                      accept_step(&policy, &sink, &event));
    event = power_event(E87_POWER_EVENT_CHARGER_FULL, true,
                        E87_POWER_WAKE_BUTTON2);
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_STATUS_UPDATED,
                      accept_step(&policy, &sink, &event));
    E87_ASSERT_TRUE(e87_power_policy_get_view(&policy, &view));
    E87_ASSERT_TRUE(!view.external_power_online);
    E87_ASSERT_EQ_U32(E87_CHARGER_PHASE_FULL, view.charger_phase);
    E87_ASSERT_EQ_U32(E87_POWER_STATE_ACTIVE, view.state);
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.count);
}

E87_TEST(plugged_boot_and_charger_events_stay_active)
{
    static const enum e87_power_event_type types[] = {
        E87_POWER_EVENT_CHARGER_START,
        E87_POWER_EVENT_CHARGER_FULL,
        E87_POWER_EVENT_CHARGER_CLOSE,
        E87_POWER_EVENT_CHARGER_CLOSE
    };
    struct e87_power_policy policy;
    struct fake_sink sink;
    struct e87_power_view view;
    size_t index;

    E87_ASSERT_TRUE(init_policy(&policy, &sink, true));
    for (index = 0U; index < sizeof(types) / sizeof(types[0]);
         index += 1U) {
        const struct e87_power_event event =
            power_event(types[index], false, E87_POWER_WAKE_NOISE);
        const enum e87_power_result expected =
            index == 3U ? E87_POWER_RESULT_NO_CHANGE
                        : E87_POWER_RESULT_STATUS_UPDATED;

        E87_ASSERT_EQ_U32(expected,
                          accept_step(&policy, &sink, &event));
        E87_ASSERT_EQ_U32(E87_POWER_STATE_ACTIVE,
                          policy.private_state);
        E87_ASSERT_TRUE(policy.private_external_power_online);
        E87_ASSERT_EQ_U32(UINT32_C(0), step_command_count(&sink));
    }
    E87_ASSERT_TRUE(e87_power_policy_get_view(&policy, &view));
    E87_ASSERT_TRUE(view.external_power_online);
    E87_ASSERT_EQ_U32(E87_CHARGER_PHASE_CLOSE, view.charger_phase);
}

E87_TEST(charger_events_never_preempt_any_ui_phase)
{
    struct e87_power_policy policy;
    struct fake_sink sink;
    struct e87_power_event event;
    size_t before_count;

    E87_ASSERT_TRUE(init_policy(&policy, &sink, false));
    event = power_event(E87_POWER_EVENT_CHARGER_START, false,
                        E87_POWER_WAKE_NONE);
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_STATUS_UPDATED,
                      accept_step(&policy, &sink, &event));
    E87_ASSERT_EQ_U32(E87_POWER_STATE_ACTIVE, policy.private_state);

    event = power_event(E87_POWER_EVENT_MANUAL_SLEEP, false,
                        E87_POWER_WAKE_NONE);
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_WAITING_FOR_LCD,
                      accept_step(&policy, &sink, &event));
    before_count = sink.count;
    event = power_event(E87_POWER_EVENT_CHARGER_FULL, false,
                        E87_POWER_WAKE_NONE);
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_STATUS_UPDATED,
                      accept_step(&policy, &sink, &event));
    E87_ASSERT_EQ_U32(E87_POWER_STATE_WAIT_LCD_IDLE,
                      policy.private_state);
    E87_ASSERT_EQ_U32(before_count, sink.count);

    event = power_event(E87_POWER_EVENT_LCD_IDLE, false,
                        E87_POWER_WAKE_NONE);
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_ASLEEP,
                      accept_step(&policy, &sink, &event));
    before_count = sink.count;
    event = power_event(E87_POWER_EVENT_CHARGER_CLOSE, false,
                        E87_POWER_WAKE_NONE);
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_STATUS_UPDATED,
                      accept_step(&policy, &sink, &event));
    E87_ASSERT_EQ_U32(E87_POWER_STATE_ASLEEP, policy.private_state);
    E87_ASSERT_EQ_U32(before_count, sink.count);

    E87_ASSERT_TRUE(begin_gpio_wake(&policy, &sink));
    before_count = sink.count;
    event = power_event(E87_POWER_EVENT_CHARGER_START, false,
                        E87_POWER_WAKE_NONE);
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_STATUS_UPDATED,
                      accept_step(&policy, &sink, &event));
    E87_ASSERT_EQ_U32(E87_POWER_STATE_WAIT_WAKE_CLASSIFICATION,
                      policy.private_state);
    E87_ASSERT_EQ_U32(before_count, sink.count);
}

E87_TEST(manual_sleep_emits_exact_two_phase_order)
{
    static const enum e87_power_command first_phase[] = {
        E87_POWER_COMMAND_STOP_DRAWS,
        E87_POWER_COMMAND_WAIT_LCD_IDLE
    };
    static const enum e87_power_command second_phase[] = {
        E87_POWER_COMMAND_PANEL_SLEEP,
        E87_POWER_COMMAND_BACKLIGHT_OFF,
        E87_POWER_COMMAND_BLE_STOP_DISCONNECT,
        E87_POWER_COMMAND_ARM_SHARED_LADDER_WAKE,
        E87_POWER_COMMAND_ENTER_LOW_POWER
    };
    struct e87_power_policy policy;
    struct fake_sink sink;
    struct e87_power_event event;
    size_t index;

    E87_ASSERT_TRUE(init_policy(&policy, &sink, true));
    event = power_event(E87_POWER_EVENT_MANUAL_SLEEP, false,
                        E87_POWER_WAKE_BUTTON2);
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_WAITING_FOR_LCD,
                      accept_step(&policy, &sink, &event));
    E87_ASSERT_EQ_U32(sizeof(first_phase) / sizeof(first_phase[0]),
                      step_command_count(&sink));
    for (index = 0U; index < sizeof(first_phase) / sizeof(first_phase[0]);
         index += 1U) {
        E87_ASSERT_EQ_U32(first_phase[index],
                          sink.commands[sink.step_start + index]);
    }
    E87_ASSERT_EQ_U32(E87_POWER_STATE_WAIT_LCD_IDLE,
                      policy.private_state);
    E87_ASSERT_TRUE(policy.private_external_power_online);

    event = power_event(E87_POWER_EVENT_LCD_IDLE, true,
                        E87_POWER_WAKE_NOISE);
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_ASLEEP,
                      accept_step(&policy, &sink, &event));
    E87_ASSERT_EQ_U32(sizeof(second_phase) / sizeof(second_phase[0]),
                      step_command_count(&sink));
    for (index = 0U;
         index < sizeof(second_phase) / sizeof(second_phase[0]);
         index += 1U) {
        E87_ASSERT_EQ_U32(second_phase[index],
                          sink.commands[sink.step_start + index]);
    }
    E87_ASSERT_EQ_U32(E87_POWER_STATE_ASLEEP, policy.private_state);
    E87_ASSERT_TRUE(policy.private_external_power_online);
}

E87_TEST(gpio_wake_waits_and_only_b2_restores_ui_then_ble)
{
    static const enum e87_power_command resume_order[] = {
        E87_POWER_COMMAND_DISPLAY_EXIT_SLEEP,
        E87_POWER_COMMAND_REDRAW,
        E87_POWER_COMMAND_BACKLIGHT_ON,
        E87_POWER_COMMAND_BLE_START
    };
    struct e87_power_policy policy;
    struct fake_sink sink;
    struct e87_power_event event;
    size_t index;

    E87_ASSERT_TRUE(init_policy(&policy, &sink, false));
    E87_ASSERT_TRUE(enter_asleep(&policy, &sink));
    E87_ASSERT_TRUE(begin_gpio_wake(&policy, &sink));
    E87_ASSERT_EQ_U32(UINT32_C(1), step_command_count(&sink));
    E87_ASSERT_EQ_U32(E87_POWER_COMMAND_RESUME_ADC,
                      sink.commands[sink.step_start]);

    event = power_event(E87_POWER_EVENT_WAKE_CLASSIFIED, true,
                        E87_POWER_WAKE_BUTTON2);
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_ACTIVE,
                      accept_step(&policy, &sink, &event));
    E87_ASSERT_EQ_U32(sizeof(resume_order) / sizeof(resume_order[0]),
                      step_command_count(&sink));
    for (index = 0U; index < sizeof(resume_order) / sizeof(resume_order[0]);
         index += 1U) {
        E87_ASSERT_EQ_U32(resume_order[index],
                          sink.commands[sink.step_start + index]);
    }
    E87_ASSERT_EQ_U32(E87_POWER_STATE_ACTIVE, policy.private_state);
    E87_ASSERT_TRUE(!policy.private_external_power_online);
    E87_ASSERT_EQ_U32(E87_CHARGER_PHASE_UNKNOWN,
                      policy.private_charger_phase);
}

E87_TEST(non_b2_and_noise_rearm_without_display_backlight_or_ble)
{
    static const enum e87_power_wake_classification classifications[] = {
        E87_POWER_WAKE_NONE,
        E87_POWER_WAKE_BUTTON1,
        E87_POWER_WAKE_AMBIGUOUS,
        E87_POWER_WAKE_NOISE
    };
    size_t index;

    for (index = 0U;
         index < sizeof(classifications) / sizeof(classifications[0]);
         index += 1U) {
        struct e87_power_policy policy;
        struct fake_sink sink;
        const struct e87_power_event classified =
            power_event(E87_POWER_EVENT_WAKE_CLASSIFIED, false,
                        classifications[index]);

        E87_ASSERT_TRUE(init_policy(&policy, &sink, false));
        E87_ASSERT_TRUE(enter_asleep(&policy, &sink));
        E87_ASSERT_TRUE(begin_gpio_wake(&policy, &sink));
        E87_ASSERT_EQ_U32(E87_POWER_RESULT_ASLEEP,
                          accept_step(&policy, &sink, &classified));
        E87_ASSERT_EQ_U32(UINT32_C(2), step_command_count(&sink));
        E87_ASSERT_EQ_U32(E87_POWER_COMMAND_ARM_SHARED_LADDER_WAKE,
                          sink.commands[sink.step_start]);
        E87_ASSERT_EQ_U32(E87_POWER_COMMAND_ENTER_LOW_POWER,
                          sink.commands[sink.step_start + 1U]);
        E87_ASSERT_EQ_U32(E87_POWER_STATE_ASLEEP,
                          policy.private_state);
    }
}

E87_TEST(duplicate_and_inapplicable_events_are_idempotent)
{
    struct e87_power_policy policy;
    struct fake_sink sink;
    struct e87_power_event event;

    E87_ASSERT_TRUE(init_policy(&policy, &sink, false));
    event = power_event(E87_POWER_EVENT_LCD_IDLE, false,
                        E87_POWER_WAKE_NONE);
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_NO_CHANGE,
                      accept_step(&policy, &sink, &event));
    event.type = E87_POWER_EVENT_GPIO_WAKE;
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_NO_CHANGE,
                      accept_step(&policy, &sink, &event));
    event.type = E87_POWER_EVENT_WAKE_CLASSIFIED;
    event.wake_classification = E87_POWER_WAKE_BUTTON2;
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_NO_CHANGE,
                      accept_step(&policy, &sink, &event));
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.count);

    event.type = E87_POWER_EVENT_MANUAL_SLEEP;
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_WAITING_FOR_LCD,
                      accept_step(&policy, &sink, &event));
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_NO_CHANGE,
                      accept_step(&policy, &sink, &event));
    E87_ASSERT_EQ_U32(UINT32_C(0), step_command_count(&sink));
    event.type = E87_POWER_EVENT_LCD_IDLE;
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_ASLEEP,
                      accept_step(&policy, &sink, &event));
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_NO_CHANGE,
                      accept_step(&policy, &sink, &event));
    E87_ASSERT_EQ_U32(UINT32_C(0), step_command_count(&sink));
    event.type = E87_POWER_EVENT_MANUAL_SLEEP;
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_NO_CHANGE,
                      accept_step(&policy, &sink, &event));
    event.type = E87_POWER_EVENT_GPIO_WAKE;
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_WAITING_FOR_WAKE_CLASSIFICATION,
                      accept_step(&policy, &sink, &event));
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_NO_CHANGE,
                      accept_step(&policy, &sink, &event));
    E87_ASSERT_EQ_U32(UINT32_C(0), step_command_count(&sink));
    event.type = E87_POWER_EVENT_WAKE_CLASSIFIED;
    event.wake_classification = E87_POWER_WAKE_BUTTON2;
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_ACTIVE,
                      accept_step(&policy, &sink, &event));
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_NO_CHANGE,
                      accept_step(&policy, &sink, &event));
    E87_ASSERT_EQ_U32(UINT32_C(0), step_command_count(&sink));
}

E87_TEST(every_sleep_command_failure_stops_and_latches_error)
{
    size_t reject;

    for (reject = 0U; reject < 2U; reject += 1U) {
        struct e87_power_policy policy;
        struct fake_sink sink;
        const struct e87_power_event event =
            power_event(E87_POWER_EVENT_MANUAL_SLEEP, false,
                        E87_POWER_WAKE_NONE);

        E87_ASSERT_TRUE(init_policy(&policy, &sink, false));
        begin_step(&sink, reject);
        E87_ASSERT_EQ_U32(E87_POWER_RESULT_ERROR,
                          e87_power_policy_step(&policy, &event));
        E87_ASSERT_EQ_U32(reject + 1U, step_command_count(&sink));
        E87_ASSERT_EQ_U32(UINT32_C(0), sink.calls_after_false);
        E87_ASSERT_EQ_U32(E87_POWER_STATE_ERROR, policy.private_state);
        begin_step(&sink, SIZE_MAX);
        E87_ASSERT_EQ_U32(E87_POWER_RESULT_ERROR,
                          e87_power_policy_step(&policy, &event));
        E87_ASSERT_EQ_U32(UINT32_C(0), step_command_count(&sink));
    }
    for (reject = 0U; reject < 5U; reject += 1U) {
        struct e87_power_policy policy;
        struct fake_sink sink;
        struct e87_power_event event;

        E87_ASSERT_TRUE(init_policy(&policy, &sink, false));
        event = power_event(E87_POWER_EVENT_MANUAL_SLEEP, false,
                            E87_POWER_WAKE_NONE);
        E87_ASSERT_EQ_U32(E87_POWER_RESULT_WAITING_FOR_LCD,
                          accept_step(&policy, &sink, &event));
        event.type = E87_POWER_EVENT_LCD_IDLE;
        begin_step(&sink, reject);
        E87_ASSERT_EQ_U32(E87_POWER_RESULT_ERROR,
                          e87_power_policy_step(&policy, &event));
        E87_ASSERT_EQ_U32(reject + 1U, step_command_count(&sink));
        E87_ASSERT_EQ_U32(UINT32_C(0), sink.calls_after_false);
        E87_ASSERT_EQ_U32(E87_POWER_STATE_ERROR, policy.private_state);
        begin_step(&sink, SIZE_MAX);
        E87_ASSERT_EQ_U32(E87_POWER_RESULT_ERROR,
                          e87_power_policy_step(&policy, &event));
        E87_ASSERT_EQ_U32(UINT32_C(0), step_command_count(&sink));
    }
}

E87_TEST(every_wake_command_failure_stops_and_latches_error)
{
    size_t reject;

    {
        struct e87_power_policy policy;
        struct fake_sink sink;
        const struct e87_power_event gpio =
            power_event(E87_POWER_EVENT_GPIO_WAKE, false,
                        E87_POWER_WAKE_NONE);

        E87_ASSERT_TRUE(init_policy(&policy, &sink, false));
        E87_ASSERT_TRUE(enter_asleep(&policy, &sink));
        begin_step(&sink, 0U);
        E87_ASSERT_EQ_U32(E87_POWER_RESULT_ERROR,
                          e87_power_policy_step(&policy, &gpio));
        E87_ASSERT_EQ_U32(UINT32_C(1), step_command_count(&sink));
        E87_ASSERT_EQ_U32(UINT32_C(0), sink.calls_after_false);
        E87_ASSERT_EQ_U32(E87_POWER_STATE_ERROR, policy.private_state);
    }
    for (reject = 0U; reject < 4U; reject += 1U) {
        struct e87_power_policy policy;
        struct fake_sink sink;
        const struct e87_power_event classified =
            power_event(E87_POWER_EVENT_WAKE_CLASSIFIED, false,
                        E87_POWER_WAKE_BUTTON2);

        E87_ASSERT_TRUE(init_policy(&policy, &sink, false));
        E87_ASSERT_TRUE(enter_asleep(&policy, &sink));
        E87_ASSERT_TRUE(begin_gpio_wake(&policy, &sink));
        begin_step(&sink, reject);
        E87_ASSERT_EQ_U32(E87_POWER_RESULT_ERROR,
                          e87_power_policy_step(&policy, &classified));
        E87_ASSERT_EQ_U32(reject + 1U, step_command_count(&sink));
        E87_ASSERT_EQ_U32(UINT32_C(0), sink.calls_after_false);
        E87_ASSERT_EQ_U32(E87_POWER_STATE_ERROR, policy.private_state);
    }
    for (reject = 0U; reject < 2U; reject += 1U) {
        struct e87_power_policy policy;
        struct fake_sink sink;
        const struct e87_power_event classified =
            power_event(E87_POWER_EVENT_WAKE_CLASSIFIED, false,
                        E87_POWER_WAKE_NOISE);

        E87_ASSERT_TRUE(init_policy(&policy, &sink, false));
        E87_ASSERT_TRUE(enter_asleep(&policy, &sink));
        E87_ASSERT_TRUE(begin_gpio_wake(&policy, &sink));
        begin_step(&sink, reject);
        E87_ASSERT_EQ_U32(E87_POWER_RESULT_ERROR,
                          e87_power_policy_step(&policy, &classified));
        E87_ASSERT_EQ_U32(reject + 1U, step_command_count(&sink));
        E87_ASSERT_EQ_U32(UINT32_C(0), sink.calls_after_false);
        E87_ASSERT_EQ_U32(E87_POWER_STATE_ERROR, policy.private_state);
    }
}

E87_TEST(reentrant_step_is_rejected_without_nested_emits_or_mutation)
{
    struct e87_power_policy policy;
    struct fake_sink sink;
    struct e87_power_event manual_sleep;

    E87_ASSERT_TRUE(init_policy(&policy, &sink, true));
    sink.reenter = true;
    sink.reentry_index = sink.count;
    sink.reentry_event =
        power_event(E87_POWER_EVENT_CHARGER_CLOSE, false,
                    E87_POWER_WAKE_NOISE);
    manual_sleep = power_event(E87_POWER_EVENT_MANUAL_SLEEP, false,
                               E87_POWER_WAKE_NONE);
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_WAITING_FOR_LCD,
                      accept_step(&policy, &sink, &manual_sleep));
    E87_ASSERT_TRUE(sink.reentry_attempted);
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_ERROR, sink.reentry_result);
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.nested_emit_count);
    E87_ASSERT_EQ_U32(E87_CHARGER_PHASE_UNKNOWN,
                      policy.private_charger_phase);
    E87_ASSERT_EQ_U32(E87_POWER_STATE_WAIT_LCD_IDLE,
                      policy.private_state);
    E87_ASSERT_EQ_U32(UINT32_C(2), step_command_count(&sink));
}

E87_TEST(repeated_sleep_wake_cycles_have_no_hidden_counter_or_wrap)
{
    struct e87_power_policy policy;
    struct fake_sink sink;
    size_t cycle;

    E87_ASSERT_TRUE(init_policy(&policy, &sink, true));
    for (cycle = 0U; cycle < 256U; cycle += 1U) {
        const struct e87_power_event classified =
            power_event(E87_POWER_EVENT_WAKE_CLASSIFIED, false,
                        E87_POWER_WAKE_BUTTON2);

        E87_ASSERT_TRUE(enter_asleep(&policy, &sink));
        E87_ASSERT_TRUE(begin_gpio_wake(&policy, &sink));
        E87_ASSERT_EQ_U32(E87_POWER_RESULT_ACTIVE,
                          accept_step(&policy, &sink, &classified));
        E87_ASSERT_EQ_U32(E87_POWER_STATE_ACTIVE, policy.private_state);
        E87_ASSERT_TRUE(policy.private_external_power_online);
        E87_ASSERT_TRUE(!sink.overflow);
    }
    E87_ASSERT_EQ_U32(UINT32_C(3072), sink.count);
}

E87_TEST(invalid_input_is_rejected_without_latching_or_emitting)
{
    struct e87_power_policy policy;
    struct fake_sink sink;
    struct e87_power_event event;
    struct e87_power_view view;

    E87_ASSERT_TRUE(init_policy(&policy, &sink, false));
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_ERROR,
                      e87_power_policy_step(NULL, NULL));
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_ERROR,
                      e87_power_policy_step(&policy, NULL));
    event = power_event((enum e87_power_event_type)UINT8_MAX, false,
                        E87_POWER_WAKE_NONE);
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_ERROR,
                      accept_step(&policy, &sink, &event));
    E87_ASSERT_EQ_U32(E87_POWER_STATE_ACTIVE, policy.private_state);
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.count);
    event = power_event(E87_POWER_EVENT_WAKE_CLASSIFIED, false,
                        (enum e87_power_wake_classification)UINT8_MAX);
    E87_ASSERT_EQ_U32(E87_POWER_RESULT_ERROR,
                      accept_step(&policy, &sink, &event));
    E87_ASSERT_EQ_U32(E87_POWER_STATE_ACTIVE, policy.private_state);
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.count);

    policy.private_initialized = false;
    memset(&view, 0xA5, sizeof(view));
    E87_ASSERT_TRUE(!e87_power_policy_get_view(&policy, &view));
}

static const struct e87_test_case power_policy_cases[] = {
    E87_TEST_CASE(init_rejects_invalid_port_without_mutation),
    E87_TEST_CASE(external_power_is_independent_from_charger_phase),
    E87_TEST_CASE(plugged_boot_and_charger_events_stay_active),
    E87_TEST_CASE(charger_events_never_preempt_any_ui_phase),
    E87_TEST_CASE(manual_sleep_emits_exact_two_phase_order),
    E87_TEST_CASE(gpio_wake_waits_and_only_b2_restores_ui_then_ble),
    E87_TEST_CASE(non_b2_and_noise_rearm_without_display_backlight_or_ble),
    E87_TEST_CASE(duplicate_and_inapplicable_events_are_idempotent),
    E87_TEST_CASE(every_sleep_command_failure_stops_and_latches_error),
    E87_TEST_CASE(every_wake_command_failure_stops_and_latches_error),
    E87_TEST_CASE(reentrant_step_is_rejected_without_nested_emits_or_mutation),
    E87_TEST_CASE(repeated_sleep_wake_cycles_have_no_hidden_counter_or_wrap),
    E87_TEST_CASE(invalid_input_is_rejected_without_latching_or_emitting)
};

const struct e87_test_suite e87_test_suite = {
    "power-policy",
    power_policy_cases,
    sizeof(power_policy_cases) / sizeof(power_policy_cases[0])
};
