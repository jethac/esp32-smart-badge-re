#include "test_support.h"
#include "e87/e87_recovery.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define FAKE_COMMAND_CAPACITY 256U

struct fake_sink {
    struct e87_recovery_fsm *fsm;
    enum e87_recovery_command commands[FAKE_COMMAND_CAPACITY];
    enum e87_reset_ownership ownership_before[FAKE_COMMAND_CAPACITY];
    size_t count;
    size_t step_start;
    size_t reject_index;
    bool false_returned;
    size_t calls_after_false;
    bool forbid_emits;
    size_t post_terminal_calls;
    bool reenter;
    size_t reentry_index;
    bool reentry_attempted;
    bool inside_reentry;
    struct e87_recovery_event reentry_event;
    enum e87_recovery_result reentry_result;
    size_t nested_emit_count;
    bool overflow;
};

static bool bytes_equal(const void *left, const void *right, size_t length)
{
    return memcmp(left, right, length) == 0;
}

static void reset_sink(struct fake_sink *sink)
{
    memset(sink, 0, sizeof(*sink));
    sink->reject_index = SIZE_MAX;
    sink->reentry_index = SIZE_MAX;
    sink->reentry_result = E87_RECOVERY_RESULT_NO_CHANGE;
}

static bool fake_emit(void *context, enum e87_recovery_command command)
{
    struct fake_sink *sink = (struct fake_sink *)context;
    size_t index;

    if (sink->forbid_emits) {
        sink->post_terminal_calls += 1U;
    }
    if (sink->false_returned) {
        sink->calls_after_false += 1U;
    }
    if (sink->count >= FAKE_COMMAND_CAPACITY) {
        sink->overflow = true;
        return false;
    }

    index = sink->count;
    sink->commands[index] = command;
    sink->ownership_before[index] =
        e87_recovery_get_reset_ownership(sink->fsm);
    sink->count += 1U;
    if (sink->inside_reentry) {
        sink->nested_emit_count += 1U;
    }
    if (sink->reenter && !sink->reentry_attempted &&
        index == sink->reentry_index) {
        sink->reentry_attempted = true;
        sink->inside_reentry = true;
        sink->reentry_result =
            e87_recovery_step(sink->fsm, &sink->reentry_event);
        sink->inside_reentry = false;
    }

    if (index == sink->reject_index) {
        sink->false_returned = true;
        return false;
    }
    return true;
}

static bool init_recovery(struct e87_recovery_fsm *fsm,
                          struct fake_sink *sink)
{
    struct e87_recovery_port port;

    reset_sink(sink);
    sink->fsm = fsm;
    port.context = sink;
    port.emit = fake_emit;
    memset(fsm, 0xA5, sizeof(*fsm));
    return e87_recovery_init(fsm, &port);
}

static void begin_fake_step(struct fake_sink *sink, size_t reject_ordinal)
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

static struct e87_recovery_event recovery_event(
    enum e87_recovery_event_type type,
    enum e87_recovery_reset_cause cause,
    enum e87_key_class key,
    uint32_t now_ms)
{
    const struct e87_recovery_event event = {type, cause, key, now_ms};

    return event;
}

static size_t command_occurrences(const struct fake_sink *sink,
                                  enum e87_recovery_command command)
{
    size_t count = 0U;
    size_t index;

    for (index = 0U; index < sink->count; index += 1U) {
        if (sink->commands[index] == command) {
            count += 1U;
        }
    }
    return count;
}

static enum e87_recovery_result boot_normal(
    struct e87_recovery_fsm *fsm,
    struct fake_sink *sink)
{
    const struct e87_recovery_event boot =
        recovery_event(E87_RECOVERY_EVENT_BOOT,
                       E87_RESET_CAUSE_POWER_ON,
                       E87_KEY_BUTTON1,
                       UINT32_C(0));

    begin_fake_step(sink, SIZE_MAX);
    return e87_recovery_step(fsm, &boot);
}

static enum e87_recovery_result begin_healthy(
    struct e87_recovery_fsm *fsm,
    struct fake_sink *sink,
    enum e87_key_class key,
    uint32_t now_ms)
{
    const struct e87_recovery_event event =
        recovery_event(E87_RECOVERY_EVENT_HEALTHY_MAINTENANCE,
                       E87_RESET_CAUSE_SOFTWARE, key, now_ms);

    begin_fake_step(sink, SIZE_MAX);
    return e87_recovery_step(fsm, &event);
}

static enum e87_recovery_result begin_pinr_held(
    struct e87_recovery_fsm *fsm,
    struct fake_sink *sink,
    enum e87_key_class key)
{
    const struct e87_recovery_event boot =
        recovery_event(E87_RECOVERY_EVENT_BOOT,
                       E87_RESET_CAUSE_P33_PPINR,
                       key,
                       UINT32_C(0));

    begin_fake_step(sink, SIZE_MAX);
    return e87_recovery_step(fsm, &boot);
}

E87_TEST(recovery_init_rejects_invalid_port_without_mutation)
{
    struct e87_recovery_fsm fsm;
    struct e87_recovery_fsm before;
    struct e87_recovery_port invalid_port;
    struct e87_recovery_port null_context_port;
    struct fake_sink sink;

    reset_sink(&sink);
    memset(&fsm, 0xA5, sizeof(fsm));
    memcpy(&before, &fsm, sizeof(before));
    E87_ASSERT_TRUE(!e87_recovery_init(NULL, NULL));
    E87_ASSERT_TRUE(!e87_recovery_init(&fsm, NULL));
    E87_ASSERT_TRUE(bytes_equal(&before, &fsm, sizeof(fsm)));
    invalid_port.context = &sink;
    invalid_port.emit = NULL;
    E87_ASSERT_TRUE(!e87_recovery_init(&fsm, &invalid_port));
    E87_ASSERT_TRUE(bytes_equal(&before, &fsm, sizeof(fsm)));
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.count);

    null_context_port.context = NULL;
    null_context_port.emit = fake_emit;
    E87_ASSERT_TRUE(e87_recovery_init(&fsm, &null_context_port));
    E87_ASSERT_TRUE(fsm.private_initialized);
    E87_ASSERT_TRUE(!fsm.private_in_step);
    E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_READY, fsm.private_state);
    E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_UNKNOWN,
                      fsm.private_reset_ownership);
    E87_ASSERT_TRUE(!fsm.private_normal_stopped);
    E87_ASSERT_TRUE(!fsm.private_release_latched);
    E87_ASSERT_EQ_U32(UINT32_C(0), fsm.private_stop_started_ms);
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.count);
}

E87_TEST(normal_boot_disarms_then_arms_exactly_16_not_8)
{
    struct e87_recovery_fsm fsm;
    struct fake_sink sink;

    E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
    E87_ASSERT_EQ_U32(UINT32_C(16), E87_PINR_RESET_HOLD_SECONDS);
    E87_ASSERT_EQ_U32(UINT32_C(5000), E87_NORMAL_STOP_TIMEOUT_MS);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_NORMAL_BOOT,
                      boot_normal(&fsm, &sink));
    E87_ASSERT_EQ_U32(UINT32_C(2), step_command_count(&sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_DISARM_PINR_RESET,
                      sink.commands[sink.step_start]);
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_ARM_PINR_RESET_16S,
                      sink.commands[sink.step_start + 1U]);
    E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_UNKNOWN,
                      sink.ownership_before[sink.step_start]);
    E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_DISARMED,
                      sink.ownership_before[sink.step_start + 1U]);
    E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_NORMAL, fsm.private_state);
    E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_ARMED,
                      e87_recovery_get_reset_ownership(&fsm));
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      command_occurrences(
                          &sink, E87_RECOVERY_COMMAND_FEED_WATCHDOG));
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      command_occurrences(
                          &sink, E87_RECOVERY_COMMAND_REQUEST_MAINTENANCE));
}

E87_TEST(only_exact_pinr_cause_takes_early_route)
{
    static const enum e87_recovery_reset_cause causes[] = {
        E87_RESET_CAUSE_POWER_ON,
        E87_RESET_CAUSE_SOFTWARE,
        E87_RESET_CAUSE_WATCHDOG,
        E87_RESET_CAUSE_P33_PPINR,
        E87_RESET_CAUSE_OTHER
    };
    size_t index;

    for (index = 0U; index < sizeof(causes) / sizeof(causes[0]);
         index += 1U) {
        struct e87_recovery_fsm fsm;
        struct fake_sink sink;
        struct e87_recovery_event boot;

        E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
        boot = recovery_event(E87_RECOVERY_EVENT_BOOT, causes[index],
                              E87_KEY_BUTTON1, UINT32_C(55));
        begin_fake_step(&sink, SIZE_MAX);
        if (causes[index] == E87_RESET_CAUSE_P33_PPINR) {
            E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                              e87_recovery_step(&fsm, &boot));
            E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_DISARM_PINR_RESET,
                              sink.commands[sink.step_start]);
            E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                              sink.commands[sink.step_start + 1U]);
            E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_PINR_WAIT_RELEASE,
                              fsm.private_state);
            E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_DISARMED,
                              fsm.private_reset_ownership);
        } else {
            E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_NORMAL_BOOT,
                              e87_recovery_step(&fsm, &boot));
            E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_DISARM_PINR_RESET,
                              sink.commands[sink.step_start]);
            E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_ARM_PINR_RESET_16S,
                              sink.commands[sink.step_start + 1U]);
            E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_NORMAL,
                              fsm.private_state);
            E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_ARMED,
                              fsm.private_reset_ownership);
        }
        E87_ASSERT_EQ_U32(UINT32_C(2), step_command_count(&sink));
    }

    {
        struct e87_recovery_fsm fsm;
        struct fake_sink sink;
        const struct e87_recovery_event released =
            recovery_event(E87_RECOVERY_EVENT_BOOT,
                           E87_RESET_CAUSE_P33_PPINR,
                           E87_KEY_NONE,
                           UINT32_C(99));

        E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
        begin_fake_step(&sink, SIZE_MAX);
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_MAINTENANCE_REQUESTED,
                          e87_recovery_step(&fsm, &released));
        E87_ASSERT_EQ_U32(UINT32_C(3), step_command_count(&sink));
        E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_DISARM_PINR_RESET,
                          sink.commands[sink.step_start]);
        E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_ARM_PINR_RESET_16S,
                          sink.commands[sink.step_start + 1U]);
        E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_REQUEST_MAINTENANCE,
                          sink.commands[sink.step_start + 2U]);
    }
}

E87_TEST(pinr_held_disarms_and_feeds_without_rearming)
{
    struct e87_recovery_fsm fsm;
    struct fake_sink sink;
    struct e87_recovery_event poll;
    size_t iteration;

    E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                      begin_pinr_held(&fsm, &sink, E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(UINT32_C(2), step_command_count(&sink));
    for (iteration = 0U; iteration < 4U; iteration += 1U) {
        poll = recovery_event(E87_RECOVERY_EVENT_POLL,
                              E87_RESET_CAUSE_P33_PPINR,
                              E87_KEY_BUTTON1,
                              UINT32_C(100) + (uint32_t)iteration);
        begin_fake_step(&sink, SIZE_MAX);
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                          e87_recovery_step(&fsm, &poll));
        E87_ASSERT_EQ_U32(UINT32_C(1), step_command_count(&sink));
        E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                          sink.commands[sink.step_start]);
        E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_PINR_WAIT_RELEASE,
                          fsm.private_state);
        E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_DISARMED,
                          fsm.private_reset_ownership);
    }
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      command_occurrences(
                          &sink, E87_RECOVERY_COMMAND_REQUEST_MAINTENANCE));
}

E87_TEST(pinr_requires_valid_none_for_release)
{
    struct e87_recovery_fsm fsm;
    struct fake_sink sink;
    static const enum e87_key_class unsafe_keys[] = {
        E87_KEY_BUTTON1,
        E87_KEY_BUTTON2,
        E87_KEY_AMBIGUOUS,
        (enum e87_key_class)99
    };
    size_t index;

    E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                      begin_pinr_held(&fsm, &sink, E87_KEY_BUTTON1));
    for (index = 0U; index < sizeof(unsafe_keys) / sizeof(unsafe_keys[0]);
         index += 1U) {
        const struct e87_recovery_event poll =
            recovery_event(E87_RECOVERY_EVENT_POLL,
                           E87_RESET_CAUSE_P33_PPINR,
                           unsafe_keys[index],
                           UINT32_C(100) + (uint32_t)index);

        begin_fake_step(&sink, SIZE_MAX);
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                          e87_recovery_step(&fsm, &poll));
        E87_ASSERT_EQ_U32(UINT32_C(1), step_command_count(&sink));
        E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                          sink.commands[sink.step_start]);
        E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_DISARMED,
                          fsm.private_reset_ownership);
    }
    {
        const struct e87_recovery_event release =
            recovery_event(E87_RECOVERY_EVENT_POLL,
                           E87_RESET_CAUSE_P33_PPINR,
                           E87_KEY_NONE,
                           UINT32_C(200));

        begin_fake_step(&sink, SIZE_MAX);
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_MAINTENANCE_REQUESTED,
                          e87_recovery_step(&fsm, &release));
        E87_ASSERT_EQ_U32(UINT32_C(2), step_command_count(&sink));
        E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_ARM_PINR_RESET_16S,
                          sink.commands[sink.step_start]);
        E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_REQUEST_MAINTENANCE,
                          sink.commands[sink.step_start + 1U]);
    }
}

E87_TEST(pinr_release_arms_then_requests_maintenance)
{
    struct e87_recovery_fsm fsm;
    struct fake_sink sink;
    const struct e87_recovery_event release =
        recovery_event(E87_RECOVERY_EVENT_POLL,
                       E87_RESET_CAUSE_P33_PPINR,
                       E87_KEY_NONE,
                       UINT32_C(500));
    const struct e87_recovery_event later =
        recovery_event(E87_RECOVERY_EVENT_BOOT,
                       E87_RESET_CAUSE_OTHER,
                       E87_KEY_BUTTON1,
                       UINT32_C(501));

    E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                      begin_pinr_held(&fsm, &sink, E87_KEY_BUTTON1));
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_MAINTENANCE_REQUESTED,
                      e87_recovery_step(&fsm, &release));
    E87_ASSERT_EQ_U32(UINT32_C(2), step_command_count(&sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_ARM_PINR_RESET_16S,
                      sink.commands[sink.step_start]);
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_REQUEST_MAINTENANCE,
                      sink.commands[sink.step_start + 1U]);
    E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_DISARMED,
                      sink.ownership_before[sink.step_start]);
    E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_ARMED,
                      sink.ownership_before[sink.step_start + 1U]);
    E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_MAINTENANCE, fsm.private_state);
    E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_ARMED,
                      fsm.private_reset_ownership);
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_NO_CHANGE,
                      e87_recovery_step(&fsm, &later));
    E87_ASSERT_EQ_U32(UINT32_C(0), step_command_count(&sink));
}

E87_TEST(healthy_entry_disarms_requests_stop_then_feeds)
{
    struct e87_recovery_fsm fsm;
    struct fake_sink sink;

    E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_NORMAL_BOOT,
                      boot_normal(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                      begin_healthy(&fsm, &sink, E87_KEY_BUTTON1,
                                    UINT32_C(12345)));
    E87_ASSERT_EQ_U32(UINT32_C(3), step_command_count(&sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_DISARM_PINR_RESET,
                      sink.commands[sink.step_start]);
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_REQUEST_NORMAL_STOP,
                      sink.commands[sink.step_start + 1U]);
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                      sink.commands[sink.step_start + 2U]);
    E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_ARMED,
                      sink.ownership_before[sink.step_start]);
    E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_DISARMED,
                      sink.ownership_before[sink.step_start + 1U]);
    E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_DISARMED,
                      sink.ownership_before[sink.step_start + 2U]);
    E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_HEALTHY_STOPPING,
                      fsm.private_state);
    E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_DISARMED,
                      fsm.private_reset_ownership);
    E87_ASSERT_EQ_U32(UINT32_C(12345), fsm.private_stop_started_ms);
    E87_ASSERT_TRUE(!fsm.private_normal_stopped);
    E87_ASSERT_TRUE(!fsm.private_release_latched);

    E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_NORMAL_BOOT,
                      boot_normal(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                      begin_healthy(&fsm, &sink, E87_KEY_NONE,
                                    UINT32_C(77)));
    E87_ASSERT_TRUE(fsm.private_release_latched);
}

E87_TEST(healthy_stop_at_or_before_timeout_allows_late_release)
{
    static const uint32_t stopped_ages[] = {
        UINT32_C(4999), UINT32_C(5000)
    };
    size_t index;

    for (index = 0U; index < sizeof(stopped_ages) / sizeof(stopped_ages[0]);
         index += 1U) {
        struct e87_recovery_fsm fsm;
        struct fake_sink sink;
        struct e87_recovery_event event;

        E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_NORMAL_BOOT,
                          boot_normal(&fsm, &sink));
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                          begin_healthy(&fsm, &sink, E87_KEY_BUTTON1,
                                        UINT32_C(1000)));

        event = recovery_event(E87_RECOVERY_EVENT_NORMAL_MODE_STOPPED,
                               E87_RESET_CAUSE_SOFTWARE,
                               E87_KEY_BUTTON1,
                               UINT32_C(1000) + stopped_ages[index]);
        begin_fake_step(&sink, SIZE_MAX);
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                          e87_recovery_step(&fsm, &event));
        E87_ASSERT_TRUE(fsm.private_normal_stopped);
        E87_ASSERT_EQ_U32(UINT32_C(1), step_command_count(&sink));
        E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                          sink.commands[sink.step_start]);

        event = recovery_event(E87_RECOVERY_EVENT_NORMAL_MODE_STOP_FAILED,
                               E87_RESET_CAUSE_OTHER,
                               E87_KEY_BUTTON1,
                               UINT32_C(500000));
        begin_fake_step(&sink, SIZE_MAX);
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                          e87_recovery_step(&fsm, &event));
        E87_ASSERT_TRUE(fsm.private_normal_stopped);
        E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                          sink.commands[sink.step_start]);

        event = recovery_event(E87_RECOVERY_EVENT_POLL,
                               E87_RESET_CAUSE_WATCHDOG,
                               E87_KEY_NONE,
                               UINT32_C(700000));
        begin_fake_step(&sink, SIZE_MAX);
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_MAINTENANCE_REQUESTED,
                          e87_recovery_step(&fsm, &event));
        E87_ASSERT_EQ_U32(UINT32_C(2), step_command_count(&sink));
        E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_ARM_PINR_RESET_16S,
                          sink.commands[sink.step_start]);
        E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_REQUEST_MAINTENANCE,
                          sink.commands[sink.step_start + 1U]);
    }
}

E87_TEST(healthy_release_before_stop_waits)
{
    struct e87_recovery_fsm fsm;
    struct fake_sink sink;
    struct e87_recovery_event event;

    E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_NORMAL_BOOT,
                      boot_normal(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                      begin_healthy(&fsm, &sink, E87_KEY_BUTTON1,
                                    UINT32_C(1000)));

    event = recovery_event(E87_RECOVERY_EVENT_POLL,
                           E87_RESET_CAUSE_SOFTWARE,
                           E87_KEY_NONE,
                           UINT32_C(1001));
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_TRUE(fsm.private_release_latched);
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                      sink.commands[sink.step_start]);

    event.now_ms = UINT32_C(2000);
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                      sink.commands[sink.step_start]);

    event.type = E87_RECOVERY_EVENT_NORMAL_MODE_STOPPED;
    event.now_ms = UINT32_C(5000);
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_MAINTENANCE_REQUESTED,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(UINT32_C(2), step_command_count(&sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_ARM_PINR_RESET_16S,
                      sink.commands[sink.step_start]);
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_REQUEST_MAINTENANCE,
                      sink.commands[sink.step_start + 1U]);
}

E87_TEST(healthy_release_latch_is_revoked_by_all_repress_classes)
{
    static const enum e87_key_class repress_keys[] = {
        E87_KEY_BUTTON1,
        E87_KEY_BUTTON2,
        E87_KEY_AMBIGUOUS,
        (enum e87_key_class)123
    };
    size_t index;

    for (index = 0U;
         index < sizeof(repress_keys) / sizeof(repress_keys[0]);
         index += 1U) {
        struct e87_recovery_fsm fsm;
        struct fake_sink sink;
        struct e87_recovery_event event;

        E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_NORMAL_BOOT,
                          boot_normal(&fsm, &sink));
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                          begin_healthy(&fsm, &sink, E87_KEY_BUTTON1,
                                        UINT32_C(0)));
        event = recovery_event(E87_RECOVERY_EVENT_POLL,
                               E87_RESET_CAUSE_SOFTWARE,
                               E87_KEY_NONE,
                               UINT32_C(1));
        begin_fake_step(&sink, SIZE_MAX);
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                          e87_recovery_step(&fsm, &event));
        E87_ASSERT_TRUE(fsm.private_release_latched);

        event.type = E87_RECOVERY_EVENT_NORMAL_MODE_STOPPED;
        event.key = repress_keys[index];
        event.now_ms = UINT32_C(2);
        begin_fake_step(&sink, SIZE_MAX);
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                          e87_recovery_step(&fsm, &event));
        E87_ASSERT_TRUE(fsm.private_normal_stopped);
        E87_ASSERT_TRUE(!fsm.private_release_latched);
        E87_ASSERT_EQ_U32(UINT32_C(1), step_command_count(&sink));
        E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                          sink.commands[sink.step_start]);

        event.type = E87_RECOVERY_EVENT_POLL;
        event.key = E87_KEY_NONE;
        event.now_ms = UINT32_C(9000);
        begin_fake_step(&sink, SIZE_MAX);
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_MAINTENANCE_REQUESTED,
                          e87_recovery_step(&fsm, &event));
        E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_ARM_PINR_RESET_16S,
                          sink.commands[sink.step_start]);
        E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_REQUEST_MAINTENANCE,
                          sink.commands[sink.step_start + 1U]);
    }
}

E87_TEST(healthy_completion_arms_then_requests_maintenance_once)
{
    struct e87_recovery_fsm fsm;
    struct fake_sink sink;
    struct e87_recovery_event event;
    unsigned int type;

    E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_NORMAL_BOOT,
                      boot_normal(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                      begin_healthy(&fsm, &sink, E87_KEY_NONE,
                                    UINT32_C(100)));
    event = recovery_event(E87_RECOVERY_EVENT_NORMAL_MODE_STOPPED,
                           E87_RESET_CAUSE_SOFTWARE,
                           E87_KEY_NONE,
                           UINT32_C(101));
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_MAINTENANCE_REQUESTED,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(UINT32_C(2), step_command_count(&sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_ARM_PINR_RESET_16S,
                      sink.commands[sink.step_start]);
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_REQUEST_MAINTENANCE,
                      sink.commands[sink.step_start + 1U]);
    E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_MAINTENANCE, fsm.private_state);

    for (type = E87_RECOVERY_EVENT_BOOT;
         type <= E87_RECOVERY_EVENT_POLL; type += 1U) {
        event.type = (enum e87_recovery_event_type)type;
        event.key = E87_KEY_BUTTON1;
        event.now_ms += UINT32_C(1);
        begin_fake_step(&sink, SIZE_MAX);
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_NO_CHANGE,
                          e87_recovery_step(&fsm, &event));
        E87_ASSERT_EQ_U32(UINT32_C(0), step_command_count(&sink));
    }
    E87_ASSERT_EQ_U32(UINT32_C(1),
                      command_occurrences(
                          &sink, E87_RECOVERY_COMMAND_REQUEST_MAINTENANCE));
}

E87_TEST(normal_stop_immediate_rejection_enters_fail_safe)
{
    static const size_t rejected_ordinals[] = {1U, 2U};
    size_t index;

    for (index = 0U;
         index < sizeof(rejected_ordinals) / sizeof(rejected_ordinals[0]);
         index += 1U) {
        struct e87_recovery_fsm fsm;
        struct fake_sink sink;
        struct e87_recovery_event healthy;
        struct e87_recovery_event release;

        E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_NORMAL_BOOT,
                          boot_normal(&fsm, &sink));
        healthy = recovery_event(E87_RECOVERY_EVENT_HEALTHY_MAINTENANCE,
                                 E87_RESET_CAUSE_SOFTWARE,
                                 E87_KEY_BUTTON1,
                                 UINT32_C(100));
        begin_fake_step(&sink, rejected_ordinals[index]);
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
                          e87_recovery_step(&fsm, &healthy));
        E87_ASSERT_EQ_U32(rejected_ordinals[index] + 1U,
                          step_command_count(&sink));
        E87_ASSERT_EQ_U32(UINT32_C(0), sink.calls_after_false);
        E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_FAIL_SAFE_WAIT_RELEASE,
                          fsm.private_state);
        E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_DISARMED,
                          fsm.private_reset_ownership);
        E87_ASSERT_EQ_U32(UINT32_C(0),
                          command_occurrences(
                              &sink,
                              E87_RECOVERY_COMMAND_REQUEST_MAINTENANCE));

        release = recovery_event(E87_RECOVERY_EVENT_POLL,
                                 E87_RESET_CAUSE_SOFTWARE,
                                 E87_KEY_NONE,
                                 UINT32_C(101));
        begin_fake_step(&sink, SIZE_MAX);
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_REARMED,
                          e87_recovery_step(&fsm, &release));
        E87_ASSERT_EQ_U32(UINT32_C(1), step_command_count(&sink));
        E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_ARM_PINR_RESET_16S,
                          sink.commands[sink.step_start]);
        E87_ASSERT_EQ_U32(UINT32_C(0),
                          command_occurrences(
                              &sink,
                              E87_RECOVERY_COMMAND_REQUEST_MAINTENANCE));
    }
}

E87_TEST(normal_stop_async_failure_rearms_only_after_release)
{
    struct e87_recovery_fsm fsm;
    struct fake_sink sink;
    struct e87_recovery_event event;
    static const enum e87_key_class held[] = {
        E87_KEY_BUTTON2, E87_KEY_AMBIGUOUS, (enum e87_key_class)77
    };
    size_t index;

    E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_NORMAL_BOOT,
                      boot_normal(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                      begin_healthy(&fsm, &sink, E87_KEY_BUTTON1,
                                    UINT32_C(1000)));
    event = recovery_event(E87_RECOVERY_EVENT_NORMAL_MODE_STOP_FAILED,
                           E87_RESET_CAUSE_OTHER,
                           E87_KEY_BUTTON1,
                           UINT32_C(1001));
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_FAIL_SAFE_WAIT_RELEASE,
                      fsm.private_state);
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                      sink.commands[sink.step_start]);

    for (index = 0U; index < sizeof(held) / sizeof(held[0]); index += 1U) {
        event.type = E87_RECOVERY_EVENT_POLL;
        event.key = held[index];
        event.now_ms += UINT32_C(1);
        begin_fake_step(&sink, SIZE_MAX);
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
                          e87_recovery_step(&fsm, &event));
        E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                          sink.commands[sink.step_start]);
    }
    event.key = E87_KEY_NONE;
    event.now_ms += UINT32_C(1);
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_REARMED,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_ARM_PINR_RESET_16S,
                      sink.commands[sink.step_start]);
    E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_FAIL_SAFE_REARMED,
                      fsm.private_state);
    E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_ARMED,
                      fsm.private_reset_ownership);
    event.type = E87_RECOVERY_EVENT_NORMAL_MODE_STOPPED;
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_NO_CHANGE,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(UINT32_C(0), step_command_count(&sink));
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      command_occurrences(
                          &sink, E87_RECOVERY_COMMAND_REQUEST_MAINTENANCE));

    E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_NORMAL_BOOT,
                      boot_normal(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                      begin_healthy(&fsm, &sink, E87_KEY_BUTTON1,
                                    UINT32_C(0)));
    event = recovery_event(E87_RECOVERY_EVENT_NORMAL_MODE_STOP_FAILED,
                           E87_RESET_CAUSE_SOFTWARE,
                           E87_KEY_NONE,
                           UINT32_C(1));
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_REARMED,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(UINT32_C(1), step_command_count(&sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_ARM_PINR_RESET_16S,
                      sink.commands[sink.step_start]);
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      command_occurrences(
                          &sink, E87_RECOVERY_COMMAND_REQUEST_MAINTENANCE));
}

E87_TEST(normal_stop_timeout_requires_unstopped_and_is_wrap_safe)
{
    static const uint32_t starts[] = {
        UINT32_C(1000), UINT32_MAX - UINT32_C(1999)
    };
    size_t index;

    for (index = 0U; index < sizeof(starts) / sizeof(starts[0]);
         index += 1U) {
        struct e87_recovery_fsm fsm;
        struct fake_sink sink;
        struct e87_recovery_event event;

        E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_NORMAL_BOOT,
                          boot_normal(&fsm, &sink));
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                          begin_healthy(&fsm, &sink, E87_KEY_BUTTON1,
                                        starts[index]));
        event = recovery_event(E87_RECOVERY_EVENT_POLL,
                               E87_RESET_CAUSE_SOFTWARE,
                               E87_KEY_BUTTON1,
                               starts[index] + UINT32_C(4999));
        begin_fake_step(&sink, SIZE_MAX);
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                          e87_recovery_step(&fsm, &event));
        E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_HEALTHY_STOPPING,
                          fsm.private_state);
        E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                          sink.commands[sink.step_start]);

        event.now_ms = starts[index] + UINT32_C(5000);
        begin_fake_step(&sink, SIZE_MAX);
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
                          e87_recovery_step(&fsm, &event));
        E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_FAIL_SAFE_WAIT_RELEASE,
                          fsm.private_state);
        E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                          sink.commands[sink.step_start]);

        event.type = E87_RECOVERY_EVENT_NORMAL_MODE_STOPPED;
        event.key = E87_KEY_NONE;
        event.now_ms += UINT32_C(1);
        begin_fake_step(&sink, SIZE_MAX);
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_REARMED,
                          e87_recovery_step(&fsm, &event));
        E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_ARM_PINR_RESET_16S,
                          sink.commands[sink.step_start]);
        E87_ASSERT_EQ_U32(UINT32_C(0),
                          command_occurrences(
                              &sink,
                              E87_RECOVERY_COMMAND_REQUEST_MAINTENANCE));
    }
}

E87_TEST(fail_safe_never_requests_maintenance)
{
    size_t path;

    for (path = 0U; path < 5U; path += 1U) {
        struct e87_recovery_fsm fsm;
        struct fake_sink sink;
        struct e87_recovery_event event;

        E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
        if (path == 0U) {
            event = recovery_event(E87_RECOVERY_EVENT_BOOT,
                                   E87_RESET_CAUSE_POWER_ON,
                                   E87_KEY_BUTTON1,
                                   UINT32_C(0));
            begin_fake_step(&sink, 1U);
            E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
                              e87_recovery_step(&fsm, &event));
        } else if (path == 2U) {
            event = recovery_event(E87_RECOVERY_EVENT_BOOT,
                                   E87_RESET_CAUSE_P33_PPINR,
                                   E87_KEY_BUTTON1,
                                   UINT32_C(0));
            begin_fake_step(&sink, 1U);
            E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
                              e87_recovery_step(&fsm, &event));
        } else {
            E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_NORMAL_BOOT,
                              boot_normal(&fsm, &sink));
            E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                              begin_healthy(&fsm, &sink,
                                            E87_KEY_BUTTON1,
                                            UINT32_C(0)));
            if (path == 1U) {
                event = recovery_event(
                    E87_RECOVERY_EVENT_NORMAL_MODE_STOP_FAILED,
                    E87_RESET_CAUSE_SOFTWARE,
                    E87_KEY_BUTTON1,
                    UINT32_C(1));
                begin_fake_step(&sink, SIZE_MAX);
                E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
                                  e87_recovery_step(&fsm, &event));
            } else if (path == 3U) {
                event = recovery_event(E87_RECOVERY_EVENT_POLL,
                                       E87_RESET_CAUSE_SOFTWARE,
                                       E87_KEY_BUTTON1,
                                       UINT32_C(5000));
                begin_fake_step(&sink, SIZE_MAX);
                E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
                                  e87_recovery_step(&fsm, &event));
            } else {
                event = recovery_event(
                    E87_RECOVERY_EVENT_HEALTHY_MAINTENANCE,
                    E87_RESET_CAUSE_SOFTWARE,
                    E87_KEY_BUTTON1,
                    UINT32_C(10));
                begin_fake_step(&sink, 1U);
                fsm.private_state = E87_RECOVERY_STATE_NORMAL;
                fsm.private_reset_ownership = E87_RESET_OWNERSHIP_ARMED;
                E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
                                  e87_recovery_step(&fsm, &event));
            }
        }

        E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_FAIL_SAFE_WAIT_RELEASE,
                          fsm.private_state);
        E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_DISARMED,
                          fsm.private_reset_ownership);
        event = recovery_event(E87_RECOVERY_EVENT_POLL,
                               E87_RESET_CAUSE_OTHER,
                               E87_KEY_BUTTON1,
                               UINT32_C(6000));
        begin_fake_step(&sink, SIZE_MAX);
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
                          e87_recovery_step(&fsm, &event));
        E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                          sink.commands[sink.step_start]);
        event.key = E87_KEY_NONE;
        event.now_ms += UINT32_C(1);
        begin_fake_step(&sink, SIZE_MAX);
        E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_REARMED,
                          e87_recovery_step(&fsm, &event));
        E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_ARM_PINR_RESET_16S,
                          sink.commands[sink.step_start]);
        E87_ASSERT_EQ_U32(UINT32_C(0),
                          command_occurrences(
                              &sink,
                              E87_RECOVERY_COMMAND_REQUEST_MAINTENANCE));
    }
}

E87_TEST(rearm_rejection_retries_without_false_success)
{
    struct e87_recovery_fsm fsm;
    struct fake_sink sink;
    struct e87_recovery_event event;

    E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
    event = recovery_event(E87_RECOVERY_EVENT_BOOT,
                           E87_RESET_CAUSE_POWER_ON,
                           E87_KEY_BUTTON1,
                           UINT32_C(0));
    begin_fake_step(&sink, 1U);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_FAIL_SAFE_WAIT_RELEASE,
                      fsm.private_state);
    E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_DISARMED,
                      fsm.private_reset_ownership);

    event.type = E87_RECOVERY_EVENT_POLL;
    event.key = E87_KEY_NONE;
    event.now_ms = UINT32_C(1);
    begin_fake_step(&sink, 0U);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(UINT32_C(1), step_command_count(&sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_ARM_PINR_RESET_16S,
                      sink.commands[sink.step_start]);
    E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_FAIL_SAFE_WAIT_RELEASE,
                      fsm.private_state);
    E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_DISARMED,
                      fsm.private_reset_ownership);
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.calls_after_false);

    event.key = E87_KEY_BUTTON1;
    event.now_ms = UINT32_C(2);
    begin_fake_step(&sink, 0U);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                      sink.commands[sink.step_start]);
    E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_FAIL_SAFE_WAIT_RELEASE,
                      fsm.private_state);
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.calls_after_false);

    event.key = E87_KEY_NONE;
    event.now_ms = UINT32_C(3);
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_REARMED,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_ARM_PINR_RESET_16S,
                      sink.commands[sink.step_start]);
    E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_FAIL_SAFE_REARMED,
                      fsm.private_state);
    E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_ARMED,
                      fsm.private_reset_ownership);
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      command_occurrences(
                          &sink, E87_RECOVERY_COMMAND_REQUEST_MAINTENANCE));
}

E87_TEST(command_rejections_preserve_exact_reset_ownership)
{
    struct e87_recovery_fsm fsm;
    struct fake_sink sink;
    struct e87_recovery_event event;

    E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
    event = recovery_event(E87_RECOVERY_EVENT_BOOT,
                           E87_RESET_CAUSE_POWER_ON,
                           E87_KEY_BUTTON1,
                           UINT32_C(0));
    begin_fake_step(&sink, 0U);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_ERROR,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_ERROR, fsm.private_state);
    E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_UNKNOWN,
                      fsm.private_reset_ownership);
    E87_ASSERT_EQ_U32(UINT32_C(1), step_command_count(&sink));
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.calls_after_false);
    sink.forbid_emits = true;
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_ERROR,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(UINT32_C(0), step_command_count(&sink));
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.post_terminal_calls);

    E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_NORMAL_BOOT,
                      boot_normal(&fsm, &sink));
    event = recovery_event(E87_RECOVERY_EVENT_HEALTHY_MAINTENANCE,
                           E87_RESET_CAUSE_SOFTWARE,
                           E87_KEY_BUTTON1,
                           UINT32_C(10));
    begin_fake_step(&sink, 0U);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_ERROR,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_ERROR, fsm.private_state);
    E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_ARMED,
                      fsm.private_reset_ownership);
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.calls_after_false);
    sink.forbid_emits = true;
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_ERROR,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.post_terminal_calls);

    E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
    event = recovery_event(E87_RECOVERY_EVENT_BOOT,
                           E87_RESET_CAUSE_POWER_ON,
                           E87_KEY_BUTTON1,
                           UINT32_C(0));
    begin_fake_step(&sink, 1U);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_DISARMED,
                      fsm.private_reset_ownership);
    E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_FAIL_SAFE_WAIT_RELEASE,
                      fsm.private_state);
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.calls_after_false);

    E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
    event = recovery_event(E87_RECOVERY_EVENT_BOOT,
                           E87_RESET_CAUSE_P33_PPINR,
                           E87_KEY_NONE,
                           UINT32_C(0));
    begin_fake_step(&sink, 1U);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_DISARMED,
                      fsm.private_reset_ownership);
    E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_FAIL_SAFE_WAIT_RELEASE,
                      fsm.private_state);
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.calls_after_false);

    E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_NORMAL_BOOT,
                      boot_normal(&fsm, &sink));
    event = recovery_event(E87_RECOVERY_EVENT_HEALTHY_MAINTENANCE,
                           E87_RESET_CAUSE_SOFTWARE,
                           E87_KEY_BUTTON1,
                           UINT32_C(10));
    begin_fake_step(&sink, 1U);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_DISARMED,
                      fsm.private_reset_ownership);
    E87_ASSERT_EQ_U32(UINT32_C(2), step_command_count(&sink));
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.calls_after_false);

    E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_NORMAL_BOOT,
                      boot_normal(&fsm, &sink));
    begin_fake_step(&sink, 2U);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_DISARMED,
                      fsm.private_reset_ownership);
    E87_ASSERT_EQ_U32(UINT32_C(3), step_command_count(&sink));
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.calls_after_false);

    E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                      begin_pinr_held(&fsm, &sink, E87_KEY_BUTTON1));
    event = recovery_event(E87_RECOVERY_EVENT_POLL,
                           E87_RESET_CAUSE_P33_PPINR,
                           E87_KEY_BUTTON1,
                           UINT32_C(1));
    begin_fake_step(&sink, 0U);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_FAIL_SAFE_WAIT_RELEASE,
                      fsm.private_state);
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.calls_after_false);

    E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_NORMAL_BOOT,
                      boot_normal(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                      begin_healthy(&fsm, &sink, E87_KEY_BUTTON1,
                                    UINT32_C(0)));
    event = recovery_event(E87_RECOVERY_EVENT_POLL,
                           E87_RESET_CAUSE_SOFTWARE,
                           E87_KEY_BUTTON1,
                           UINT32_C(1));
    begin_fake_step(&sink, 0U);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_FAIL_SAFE_WAIT_RELEASE,
                      fsm.private_state);
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.calls_after_false);

    event.now_ms = UINT32_C(2);
    begin_fake_step(&sink, 0U);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_FAIL_SAFE_WAIT_RELEASE,
                      fsm.private_state);
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.calls_after_false);

    E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
    event = recovery_event(E87_RECOVERY_EVENT_BOOT,
                           E87_RESET_CAUSE_P33_PPINR,
                           E87_KEY_NONE,
                           UINT32_C(0));
    begin_fake_step(&sink, 2U);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_ERROR,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(E87_RECOVERY_STATE_ERROR, fsm.private_state);
    E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_ARMED,
                      fsm.private_reset_ownership);
    E87_ASSERT_EQ_U32(UINT32_C(3), step_command_count(&sink));
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.calls_after_false);
    sink.forbid_emits = true;
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_ERROR,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.post_terminal_calls);
}

E87_TEST(all_state_event_cells_match_transition_table)
{
    static const enum e87_recovery_result expected_result[8][5] = {
        {
            E87_RECOVERY_RESULT_NORMAL_BOOT,
            E87_RECOVERY_RESULT_NO_CHANGE,
            E87_RECOVERY_RESULT_NO_CHANGE,
            E87_RECOVERY_RESULT_NO_CHANGE,
            E87_RECOVERY_RESULT_NO_CHANGE
        },
        {
            E87_RECOVERY_RESULT_NO_CHANGE,
            E87_RECOVERY_RESULT_WAITING,
            E87_RECOVERY_RESULT_NO_CHANGE,
            E87_RECOVERY_RESULT_NO_CHANGE,
            E87_RECOVERY_RESULT_NO_CHANGE
        },
        {
            E87_RECOVERY_RESULT_WAITING,
            E87_RECOVERY_RESULT_WAITING,
            E87_RECOVERY_RESULT_WAITING,
            E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
            E87_RECOVERY_RESULT_WAITING
        },
        {
            E87_RECOVERY_RESULT_WAITING,
            E87_RECOVERY_RESULT_WAITING,
            E87_RECOVERY_RESULT_WAITING,
            E87_RECOVERY_RESULT_WAITING,
            E87_RECOVERY_RESULT_WAITING
        },
        {
            E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
            E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
            E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
            E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
            E87_RECOVERY_RESULT_FAIL_SAFE_WAITING
        },
        {
            E87_RECOVERY_RESULT_NO_CHANGE,
            E87_RECOVERY_RESULT_NO_CHANGE,
            E87_RECOVERY_RESULT_NO_CHANGE,
            E87_RECOVERY_RESULT_NO_CHANGE,
            E87_RECOVERY_RESULT_NO_CHANGE
        },
        {
            E87_RECOVERY_RESULT_NO_CHANGE,
            E87_RECOVERY_RESULT_NO_CHANGE,
            E87_RECOVERY_RESULT_NO_CHANGE,
            E87_RECOVERY_RESULT_NO_CHANGE,
            E87_RECOVERY_RESULT_NO_CHANGE
        },
        {
            E87_RECOVERY_RESULT_ERROR,
            E87_RECOVERY_RESULT_ERROR,
            E87_RECOVERY_RESULT_ERROR,
            E87_RECOVERY_RESULT_ERROR,
            E87_RECOVERY_RESULT_ERROR
        }
    };
    static const enum e87_recovery_state expected_state[8][5] = {
        {
            E87_RECOVERY_STATE_NORMAL,
            E87_RECOVERY_STATE_READY,
            E87_RECOVERY_STATE_READY,
            E87_RECOVERY_STATE_READY,
            E87_RECOVERY_STATE_READY
        },
        {
            E87_RECOVERY_STATE_NORMAL,
            E87_RECOVERY_STATE_HEALTHY_STOPPING,
            E87_RECOVERY_STATE_NORMAL,
            E87_RECOVERY_STATE_NORMAL,
            E87_RECOVERY_STATE_NORMAL
        },
        {
            E87_RECOVERY_STATE_HEALTHY_STOPPING,
            E87_RECOVERY_STATE_HEALTHY_STOPPING,
            E87_RECOVERY_STATE_HEALTHY_STOPPING,
            E87_RECOVERY_STATE_FAIL_SAFE_WAIT_RELEASE,
            E87_RECOVERY_STATE_HEALTHY_STOPPING
        },
        {
            E87_RECOVERY_STATE_PINR_WAIT_RELEASE,
            E87_RECOVERY_STATE_PINR_WAIT_RELEASE,
            E87_RECOVERY_STATE_PINR_WAIT_RELEASE,
            E87_RECOVERY_STATE_PINR_WAIT_RELEASE,
            E87_RECOVERY_STATE_PINR_WAIT_RELEASE
        },
        {
            E87_RECOVERY_STATE_FAIL_SAFE_WAIT_RELEASE,
            E87_RECOVERY_STATE_FAIL_SAFE_WAIT_RELEASE,
            E87_RECOVERY_STATE_FAIL_SAFE_WAIT_RELEASE,
            E87_RECOVERY_STATE_FAIL_SAFE_WAIT_RELEASE,
            E87_RECOVERY_STATE_FAIL_SAFE_WAIT_RELEASE
        },
        {
            E87_RECOVERY_STATE_MAINTENANCE,
            E87_RECOVERY_STATE_MAINTENANCE,
            E87_RECOVERY_STATE_MAINTENANCE,
            E87_RECOVERY_STATE_MAINTENANCE,
            E87_RECOVERY_STATE_MAINTENANCE
        },
        {
            E87_RECOVERY_STATE_FAIL_SAFE_REARMED,
            E87_RECOVERY_STATE_FAIL_SAFE_REARMED,
            E87_RECOVERY_STATE_FAIL_SAFE_REARMED,
            E87_RECOVERY_STATE_FAIL_SAFE_REARMED,
            E87_RECOVERY_STATE_FAIL_SAFE_REARMED
        },
        {
            E87_RECOVERY_STATE_ERROR,
            E87_RECOVERY_STATE_ERROR,
            E87_RECOVERY_STATE_ERROR,
            E87_RECOVERY_STATE_ERROR,
            E87_RECOVERY_STATE_ERROR
        }
    };
    unsigned int state;
    unsigned int type;

    for (state = E87_RECOVERY_STATE_READY;
         state <= E87_RECOVERY_STATE_ERROR; state += 1U) {
        for (type = E87_RECOVERY_EVENT_BOOT;
             type <= E87_RECOVERY_EVENT_POLL; type += 1U) {
            struct e87_recovery_fsm fsm;
            struct fake_sink sink;
            struct e87_recovery_event event;
            size_t expected_count = 0U;

            E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
            fsm.private_state = (enum e87_recovery_state)state;
            if (state == E87_RECOVERY_STATE_NORMAL) {
                fsm.private_reset_ownership = E87_RESET_OWNERSHIP_ARMED;
            } else if (state == E87_RECOVERY_STATE_HEALTHY_STOPPING ||
                       state == E87_RECOVERY_STATE_PINR_WAIT_RELEASE ||
                       state == E87_RECOVERY_STATE_FAIL_SAFE_WAIT_RELEASE) {
                fsm.private_reset_ownership = E87_RESET_OWNERSHIP_DISARMED;
            } else if (state == E87_RECOVERY_STATE_MAINTENANCE ||
                       state == E87_RECOVERY_STATE_FAIL_SAFE_REARMED) {
                fsm.private_reset_ownership = E87_RESET_OWNERSHIP_ARMED;
            }
            fsm.private_stop_started_ms = UINT32_C(0);
            fsm.private_normal_stopped = false;
            fsm.private_release_latched = false;
            event = recovery_event((enum e87_recovery_event_type)type,
                                   E87_RESET_CAUSE_SOFTWARE,
                                   E87_KEY_BUTTON1,
                                   UINT32_C(1));
            begin_fake_step(&sink, SIZE_MAX);
            E87_ASSERT_EQ_U32(expected_result[state][type],
                              e87_recovery_step(&fsm, &event));
            E87_ASSERT_EQ_U32(expected_state[state][type],
                              fsm.private_state);

            if (state == E87_RECOVERY_STATE_READY &&
                type == E87_RECOVERY_EVENT_BOOT) {
                expected_count = 2U;
                E87_ASSERT_EQ_U32(
                    E87_RECOVERY_COMMAND_DISARM_PINR_RESET,
                    sink.commands[sink.step_start]);
                E87_ASSERT_EQ_U32(
                    E87_RECOVERY_COMMAND_ARM_PINR_RESET_16S,
                    sink.commands[sink.step_start + 1U]);
                E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_ARMED,
                                  fsm.private_reset_ownership);
            } else if (state == E87_RECOVERY_STATE_NORMAL &&
                       type == E87_RECOVERY_EVENT_HEALTHY_MAINTENANCE) {
                expected_count = 3U;
                E87_ASSERT_EQ_U32(
                    E87_RECOVERY_COMMAND_DISARM_PINR_RESET,
                    sink.commands[sink.step_start]);
                E87_ASSERT_EQ_U32(
                    E87_RECOVERY_COMMAND_REQUEST_NORMAL_STOP,
                    sink.commands[sink.step_start + 1U]);
                E87_ASSERT_EQ_U32(
                    E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                    sink.commands[sink.step_start + 2U]);
                E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_DISARMED,
                                  fsm.private_reset_ownership);
            } else if (state == E87_RECOVERY_STATE_HEALTHY_STOPPING ||
                       state == E87_RECOVERY_STATE_PINR_WAIT_RELEASE ||
                       state == E87_RECOVERY_STATE_FAIL_SAFE_WAIT_RELEASE) {
                expected_count = 1U;
                E87_ASSERT_EQ_U32(
                    E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                    sink.commands[sink.step_start]);
                E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_DISARMED,
                                  fsm.private_reset_ownership);
            }
            E87_ASSERT_EQ_U32(expected_count, step_command_count(&sink));
            if (state == E87_RECOVERY_STATE_HEALTHY_STOPPING) {
                E87_ASSERT_EQ_U32(
                    type == E87_RECOVERY_EVENT_NORMAL_MODE_STOPPED,
                    fsm.private_normal_stopped);
            }
            E87_ASSERT_TRUE(!sink.overflow);
            E87_ASSERT_EQ_U32(UINT32_C(0), sink.calls_after_false);
        }
    }
}

E87_TEST(emit_reentry_is_rejected_without_nested_command)
{
    size_t phase;
    size_t ordinal;

    for (phase = 0U; phase < 2U; phase += 1U) {
        for (ordinal = 0U; ordinal < 3U; ordinal += 1U) {
            struct e87_recovery_fsm fsm;
            struct fake_sink sink;
            struct e87_recovery_event outer;
            enum e87_recovery_result expected_result;
            enum e87_recovery_state expected_state;

            E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
            if (phase == 0U) {
                outer = recovery_event(E87_RECOVERY_EVENT_BOOT,
                                       E87_RESET_CAUSE_P33_PPINR,
                                       E87_KEY_NONE,
                                       UINT32_C(0));
                expected_result =
                    E87_RECOVERY_RESULT_MAINTENANCE_REQUESTED;
                expected_state = E87_RECOVERY_STATE_MAINTENANCE;
            } else {
                E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_NORMAL_BOOT,
                                  boot_normal(&fsm, &sink));
                outer = recovery_event(
                    E87_RECOVERY_EVENT_HEALTHY_MAINTENANCE,
                    E87_RESET_CAUSE_SOFTWARE,
                    E87_KEY_BUTTON1,
                    UINT32_C(10));
                expected_result = E87_RECOVERY_RESULT_WAITING;
                expected_state = E87_RECOVERY_STATE_HEALTHY_STOPPING;
            }
            sink.reenter = true;
            sink.reentry_attempted = false;
            sink.reentry_index = sink.count + ordinal;
            sink.reentry_event =
                recovery_event(E87_RECOVERY_EVENT_POLL,
                               E87_RESET_CAUSE_OTHER,
                               E87_KEY_BUTTON1,
                               UINT32_C(11));
            begin_fake_step(&sink, SIZE_MAX);
            E87_ASSERT_EQ_U32(expected_result,
                              e87_recovery_step(&fsm, &outer));
            E87_ASSERT_TRUE(sink.reentry_attempted);
            E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_ERROR,
                              sink.reentry_result);
            E87_ASSERT_EQ_U32(UINT32_C(0), sink.nested_emit_count);
            E87_ASSERT_EQ_U32(UINT32_C(3), step_command_count(&sink));
            E87_ASSERT_EQ_U32(expected_state, fsm.private_state);
            E87_ASSERT_TRUE(!fsm.private_in_step);
            if (phase == 0U) {
                E87_ASSERT_EQ_U32(
                    E87_RECOVERY_COMMAND_DISARM_PINR_RESET,
                    sink.commands[sink.step_start]);
                E87_ASSERT_EQ_U32(
                    E87_RECOVERY_COMMAND_ARM_PINR_RESET_16S,
                    sink.commands[sink.step_start + 1U]);
                E87_ASSERT_EQ_U32(
                    E87_RECOVERY_COMMAND_REQUEST_MAINTENANCE,
                    sink.commands[sink.step_start + 2U]);
                E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_UNKNOWN,
                                  sink.ownership_before[sink.step_start]);
                E87_ASSERT_EQ_U32(
                    E87_RESET_OWNERSHIP_DISARMED,
                    sink.ownership_before[sink.step_start + 1U]);
                E87_ASSERT_EQ_U32(
                    E87_RESET_OWNERSHIP_ARMED,
                    sink.ownership_before[sink.step_start + 2U]);
            } else {
                E87_ASSERT_EQ_U32(
                    E87_RECOVERY_COMMAND_DISARM_PINR_RESET,
                    sink.commands[sink.step_start]);
                E87_ASSERT_EQ_U32(
                    E87_RECOVERY_COMMAND_REQUEST_NORMAL_STOP,
                    sink.commands[sink.step_start + 1U]);
                E87_ASSERT_EQ_U32(
                    E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                    sink.commands[sink.step_start + 2U]);
                E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_ARMED,
                                  sink.ownership_before[sink.step_start]);
                E87_ASSERT_EQ_U32(
                    E87_RESET_OWNERSHIP_DISARMED,
                    sink.ownership_before[sink.step_start + 1U]);
                E87_ASSERT_EQ_U32(
                    E87_RESET_OWNERSHIP_DISARMED,
                    sink.ownership_before[sink.step_start + 2U]);
            }
        }
    }
}

E87_TEST(null_zeroed_invalid_inputs_and_undefined_keys_fail_safe)
{
    struct e87_recovery_fsm fsm;
    struct e87_recovery_fsm fsm_before;
    struct e87_recovery_fsm zeroed;
    struct e87_recovery_fsm zeroed_before;
    struct fake_sink sink;
    struct e87_recovery_event event;
    struct e87_recovery_event event_before;
    const enum e87_key_class undefined_key = (enum e87_key_class)99;

    E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
    event = recovery_event(E87_RECOVERY_EVENT_POLL,
                           E87_RESET_CAUSE_SOFTWARE,
                           E87_KEY_NONE,
                           UINT32_C(1));
    memcpy(&fsm_before, &fsm, sizeof(fsm_before));
    memcpy(&event_before, &event, sizeof(event_before));
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_ERROR,
                      e87_recovery_step(NULL, &event));
    E87_ASSERT_TRUE(bytes_equal(&event_before, &event, sizeof(event)));
    E87_ASSERT_EQ_U32(UINT32_C(0), step_command_count(&sink));
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_ERROR,
                      e87_recovery_step(&fsm, NULL));
    E87_ASSERT_TRUE(bytes_equal(&fsm_before, &fsm, sizeof(fsm)));
    E87_ASSERT_EQ_U32(UINT32_C(0), step_command_count(&sink));

    memset(&zeroed, 0, sizeof(zeroed));
    memcpy(&zeroed_before, &zeroed, sizeof(zeroed_before));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_ERROR,
                      e87_recovery_step(&zeroed, &event));
    E87_ASSERT_TRUE(bytes_equal(&zeroed_before, &zeroed, sizeof(zeroed)));
    E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_UNKNOWN,
                      e87_recovery_get_reset_ownership(NULL));
    E87_ASSERT_EQ_U32(E87_RESET_OWNERSHIP_UNKNOWN,
                      e87_recovery_get_reset_ownership(&zeroed));

    event.type = (enum e87_recovery_event_type)99;
    memcpy(&fsm_before, &fsm, sizeof(fsm_before));
    memcpy(&event_before, &event, sizeof(event_before));
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_ERROR,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_TRUE(bytes_equal(&fsm_before, &fsm, sizeof(fsm)));
    E87_ASSERT_TRUE(bytes_equal(&event_before, &event, sizeof(event)));
    E87_ASSERT_EQ_U32(UINT32_C(0), step_command_count(&sink));

    event = recovery_event(E87_RECOVERY_EVENT_POLL,
                           (enum e87_recovery_reset_cause)99,
                           E87_KEY_NONE,
                           UINT32_C(2));
    memcpy(&fsm_before, &fsm, sizeof(fsm_before));
    memcpy(&event_before, &event, sizeof(event_before));
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_ERROR,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_TRUE(bytes_equal(&fsm_before, &fsm, sizeof(fsm)));
    E87_ASSERT_TRUE(bytes_equal(&event_before, &event, sizeof(event)));
    E87_ASSERT_EQ_U32(UINT32_C(0), step_command_count(&sink));

    E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                      begin_pinr_held(&fsm, &sink, undefined_key));
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                      sink.commands[sink.step_start + 1U]);
    event = recovery_event(E87_RECOVERY_EVENT_POLL,
                           E87_RESET_CAUSE_P33_PPINR,
                           undefined_key,
                           UINT32_C(10));
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                      sink.commands[sink.step_start]);
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      command_occurrences(
                          &sink, E87_RECOVERY_COMMAND_REQUEST_MAINTENANCE));
    event.key = E87_KEY_NONE;
    event.now_ms = UINT32_C(11);
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_MAINTENANCE_REQUESTED,
                      e87_recovery_step(&fsm, &event));

    E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_NORMAL_BOOT,
                      boot_normal(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                      begin_healthy(&fsm, &sink, E87_KEY_NONE,
                                    UINT32_C(100)));
    E87_ASSERT_TRUE(fsm.private_release_latched);
    event = recovery_event(E87_RECOVERY_EVENT_POLL,
                           E87_RESET_CAUSE_SOFTWARE,
                           undefined_key,
                           UINT32_C(101));
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_TRUE(!fsm.private_release_latched);
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                      sink.commands[sink.step_start]);
    event.type = E87_RECOVERY_EVENT_NORMAL_MODE_STOPPED;
    event.now_ms = UINT32_C(102);
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_TRUE(fsm.private_normal_stopped);
    E87_ASSERT_TRUE(!fsm.private_release_latched);
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                      sink.commands[sink.step_start]);
    event.type = E87_RECOVERY_EVENT_POLL;
    event.key = E87_KEY_NONE;
    event.now_ms = UINT32_C(9000);
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_MAINTENANCE_REQUESTED,
                      e87_recovery_step(&fsm, &event));

    E87_ASSERT_TRUE(init_recovery(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_NORMAL_BOOT,
                      boot_normal(&fsm, &sink));
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_WAITING,
                      begin_healthy(&fsm, &sink, E87_KEY_BUTTON1,
                                    UINT32_C(0)));
    event = recovery_event(E87_RECOVERY_EVENT_NORMAL_MODE_STOP_FAILED,
                           E87_RESET_CAUSE_OTHER,
                           undefined_key,
                           UINT32_C(1));
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                      sink.commands[sink.step_start]);
    event.type = E87_RECOVERY_EVENT_POLL;
    event.now_ms = UINT32_C(2);
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_WAITING,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                      sink.commands[sink.step_start]);
    event.key = E87_KEY_NONE;
    event.now_ms = UINT32_C(3);
    begin_fake_step(&sink, SIZE_MAX);
    E87_ASSERT_EQ_U32(E87_RECOVERY_RESULT_FAIL_SAFE_REARMED,
                      e87_recovery_step(&fsm, &event));
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_ARM_PINR_RESET_16S,
                      sink.commands[sink.step_start]);
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      command_occurrences(
                          &sink, E87_RECOVERY_COMMAND_REQUEST_MAINTENANCE));
}

static const struct e87_test_case recovery_cases[] = {
    E87_TEST_CASE(recovery_init_rejects_invalid_port_without_mutation),
    E87_TEST_CASE(normal_boot_disarms_then_arms_exactly_16_not_8),
    E87_TEST_CASE(only_exact_pinr_cause_takes_early_route),
    E87_TEST_CASE(pinr_held_disarms_and_feeds_without_rearming),
    E87_TEST_CASE(pinr_requires_valid_none_for_release),
    E87_TEST_CASE(pinr_release_arms_then_requests_maintenance),
    E87_TEST_CASE(healthy_entry_disarms_requests_stop_then_feeds),
    E87_TEST_CASE(healthy_stop_at_or_before_timeout_allows_late_release),
    E87_TEST_CASE(healthy_release_before_stop_waits),
    E87_TEST_CASE(healthy_release_latch_is_revoked_by_all_repress_classes),
    E87_TEST_CASE(healthy_completion_arms_then_requests_maintenance_once),
    E87_TEST_CASE(normal_stop_immediate_rejection_enters_fail_safe),
    E87_TEST_CASE(normal_stop_async_failure_rearms_only_after_release),
    E87_TEST_CASE(normal_stop_timeout_requires_unstopped_and_is_wrap_safe),
    E87_TEST_CASE(fail_safe_never_requests_maintenance),
    E87_TEST_CASE(rearm_rejection_retries_without_false_success),
    E87_TEST_CASE(command_rejections_preserve_exact_reset_ownership),
    E87_TEST_CASE(all_state_event_cells_match_transition_table),
    E87_TEST_CASE(emit_reentry_is_rejected_without_nested_command),
    E87_TEST_CASE(null_zeroed_invalid_inputs_and_undefined_keys_fail_safe),
};

const struct e87_test_suite e87_test_suite = {
    "recovery-policy",
    recovery_cases,
    sizeof(recovery_cases) / sizeof(recovery_cases[0]),
};
