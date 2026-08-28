#include "test_support.h"
#include "e87/e87_charge_adapter.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define CAPACITY 64U

enum trace_kind {
    TRACE_EMIT_START = 0,
    TRACE_EMIT_CLOSE = 1,
    TRACE_PUBLISH = 2
};

struct fixture {
    struct e87_charge_adapter adapter;
    enum e87_charge_command commands[CAPACITY];
    struct e87_charge_snapshot publications[CAPACITY];
    size_t command_count;
    size_t publication_count;
    size_t command_attempt_count;
    size_t publish_attempt_count;
    enum trace_kind trace[CAPACITY];
    size_t trace_count;
    bool reject_start;
    bool reject_close;
    bool reject_publish;
    bool reject_before_effect;
    bool reenter_emit;
    bool reenter_publish;
    bool reentered;
    struct e87_charge_observation nested;
    enum e87_charge_result nested_result;
};

static void trace(struct fixture *fixture, enum trace_kind kind)
{
    if (fixture->trace_count < CAPACITY) {
        fixture->trace[fixture->trace_count] = kind;
        fixture->trace_count += 1U;
    }
}

static bool bytes_equal(const void *left, const void *right, size_t count)
{
    return memcmp(left, right, count) == 0;
}

static bool snapshot_equal(const struct e87_charge_snapshot *left,
                           const struct e87_charge_snapshot *right)
{
    return left->external_power_online == right->external_power_online &&
           left->phase == right->phase;
}

static bool fake_emit(void *context, enum e87_charge_command command)
{
    struct fixture *fixture = context;
    const bool reject = command == E87_CHARGE_COMMAND_START_ELECTRICAL
                            ? fixture->reject_start
                            : fixture->reject_close;

    fixture->command_attempt_count += 1U;
    trace(fixture, command == E87_CHARGE_COMMAND_START_ELECTRICAL
                       ? TRACE_EMIT_START
                       : TRACE_EMIT_CLOSE);
    if (reject && fixture->reject_before_effect) {
        return false;
    }
    if (fixture->command_count >= CAPACITY) {
        return false;
    }
    fixture->commands[fixture->command_count] = command;
    fixture->command_count += 1U;
    if (fixture->reenter_emit && !fixture->reentered) {
        fixture->reentered = true;
        fixture->nested_result = e87_charge_adapter_step(&fixture->adapter,
                                                          &fixture->nested);
    }
    return !reject;
}

static bool fake_publish(void *context,
                         const struct e87_charge_snapshot *snapshot)
{
    struct fixture *fixture = context;

    fixture->publish_attempt_count += 1U;
    trace(fixture, TRACE_PUBLISH);
    if (snapshot == NULL ||
        (fixture->reject_publish && fixture->reject_before_effect)) {
        return false;
    }
    if (fixture->publication_count >= CAPACITY) {
        return false;
    }
    fixture->publications[fixture->publication_count] = *snapshot;
    fixture->publication_count += 1U;
    if (fixture->reenter_publish && !fixture->reentered) {
        fixture->reentered = true;
        fixture->nested_result = e87_charge_adapter_step(&fixture->adapter,
                                                          &fixture->nested);
    }
    return !fixture->reject_publish;
}

static void assert_trace(const struct fixture *fixture, size_t count,
                         enum trace_kind first, enum trace_kind second)
{
    E87_ASSERT_EQ_U32((uint32_t)count, (uint32_t)fixture->trace_count);
    if (count > 0U) {
        E87_ASSERT_EQ_U32(first, fixture->trace[0]);
    }
    if (count > 1U) {
        E87_ASSERT_EQ_U32(second, fixture->trace[1]);
    }
}

static bool fixture_init(struct fixture *fixture)
{
    const struct e87_charge_port port = {fixture, fake_emit, fake_publish};

    memset(fixture, 0, sizeof(*fixture));
    return e87_charge_adapter_init(&fixture->adapter, &port);
}

static struct e87_charge_observation observation(enum e87_charge_event event,
                                                  uint8_t raw)
{
    const struct e87_charge_observation value = {event, raw};

    return value;
}

static void assert_snapshot(const struct fixture *fixture, bool online,
                            enum e87_charge_phase phase)
{
    struct e87_charge_snapshot snapshot;

    E87_ASSERT_TRUE(e87_charge_adapter_get_snapshot(&fixture->adapter,
                                                     &snapshot));
    E87_ASSERT_EQ_U32(online ? UINT32_C(1) : UINT32_C(0),
                      snapshot.external_power_online ? UINT32_C(1) : UINT32_C(0));
    E87_ASSERT_EQ_U32(phase, snapshot.phase);
}

static void assert_pending_candidate(const struct fixture *fixture, bool online,
                                     enum e87_charge_phase phase)
{
    E87_ASSERT_TRUE(e87_charge_adapter_has_pending_close(&fixture->adapter));
    E87_ASSERT_EQ_U32(online ? UINT32_C(1) : UINT32_C(0),
                      fixture->adapter.private_pending_snapshot.external_power_online
                          ? UINT32_C(1) : UINT32_C(0));
    E87_ASSERT_EQ_U32(phase, fixture->adapter.private_pending_snapshot.phase);
}

static void assert_callback_counts(const struct fixture *fixture,
                                   size_t command_attempts, size_t commands,
                                   size_t publish_attempts, size_t publications)
{
    E87_ASSERT_EQ_U32((uint32_t)command_attempts,
                      (uint32_t)fixture->command_attempt_count);
    E87_ASSERT_EQ_U32((uint32_t)commands, (uint32_t)fixture->command_count);
    E87_ASSERT_EQ_U32((uint32_t)publish_attempts,
                      (uint32_t)fixture->publish_attempt_count);
    E87_ASSERT_EQ_U32((uint32_t)publications,
                      (uint32_t)fixture->publication_count);
}

static void set_committed(struct fixture *fixture, bool online,
                          enum e87_charge_phase phase)
{
    fixture->adapter.private_snapshot.external_power_online = online;
    fixture->adapter.private_snapshot.phase = phase;
    fixture->adapter.private_pending_snapshot = fixture->adapter.private_snapshot;
    fixture->adapter.private_has_pending_close = false;
    fixture->adapter.private_terminal_error = false;
    fixture->adapter.private_in_step = false;
}

/* These literal anchors deliberately do not share transition code with the
 * adapter: a changed adapter branch must make the matrix disagree. */
static enum e87_charge_phase full_phase_anchor[] = {
    E87_CHARGE_PHASE_FULL, E87_CHARGE_PHASE_FULL,
    E87_CHARGE_PHASE_FULL, E87_CHARGE_PHASE_FULL,
    E87_CHARGE_PHASE_FAULT
};

static enum e87_charge_phase start_phase_anchor[] = {
    E87_CHARGE_PHASE_CHARGING, E87_CHARGE_PHASE_CHARGING,
    E87_CHARGE_PHASE_FULL, E87_CHARGE_PHASE_CHARGING,
    E87_CHARGE_PHASE_FAULT
};

static enum e87_charge_phase close_phase_anchor[] = {
    E87_CHARGE_PHASE_CLOSED, E87_CHARGE_PHASE_CLOSED,
    E87_CHARGE_PHASE_FULL, E87_CHARGE_PHASE_CLOSED,
    E87_CHARGE_PHASE_FAULT
};

static bool anchor_consistent(enum e87_charge_event event, uint8_t raw)
{
    static const uint8_t required_raw[] = {
        UINT8_C(1), UINT8_C(2), UINT8_C(1), UINT8_C(1),
        UINT8_C(1), UINT8_C(0), UINT8_C(2)
    };

    if (raw != UINT8_C(0) && raw != UINT8_C(1)) {
        return false;
    }
    if ((unsigned int)event >= sizeof(required_raw) / sizeof(required_raw[0])) {
        return false;
    }
    return required_raw[event] == UINT8_C(2) || required_raw[event] == raw;
}

static void matrix_anchor(const struct e87_charge_snapshot *current,
                          enum e87_charge_event event, uint8_t raw,
                          struct e87_charge_snapshot *want_snapshot,
                          bool *want_command,
                          enum e87_charge_command *want_effect)
{
    const unsigned int phase = (unsigned int)current->phase;

    *want_snapshot = *current;
    *want_command = false;
    *want_effect = E87_CHARGE_COMMAND_START_ELECTRICAL;
    if (raw != UINT8_C(0) && raw != UINT8_C(1)) {
        want_snapshot->phase = E87_CHARGE_PHASE_FAULT;
    } else if (!anchor_consistent(event, raw)) {
        want_snapshot->external_power_online = raw == UINT8_C(1);
        want_snapshot->phase = E87_CHARGE_PHASE_FAULT;
    } else if (event == E87_CHARGE_EVENT_LDO5V_IN) {
        want_snapshot->external_power_online = true;
    } else if (event == E87_CHARGE_EVENT_CHARGE_START) {
        want_snapshot->external_power_online = true;
        want_snapshot->phase = start_phase_anchor[phase];
    } else if (event == E87_CHARGE_EVENT_CHARGE_FULL) {
        want_snapshot->external_power_online = true;
        want_snapshot->phase = full_phase_anchor[phase];
    } else if (event == E87_CHARGE_EVENT_CHARGE_CLOSE) {
        want_snapshot->external_power_online = raw == UINT8_C(1);
        want_snapshot->phase = close_phase_anchor[phase];
    } else if (event == E87_CHARGE_EVENT_LDO5V_OFF) {
        want_snapshot->external_power_online = false;
        want_snapshot->phase = E87_CHARGE_PHASE_CLOSED;
    } else {
        want_snapshot->external_power_online = raw == UINT8_C(1);
        want_snapshot->phase = E87_CHARGE_PHASE_FAULT;
    }

    if (snapshot_equal(current, want_snapshot)) {
        return;
    }
    if (raw != UINT8_C(0) && raw != UINT8_C(1)) {
        *want_command = true;
        *want_effect = E87_CHARGE_COMMAND_CLOSE_ELECTRICAL;
    } else if (!anchor_consistent(event, raw)) {
        *want_command = true;
        *want_effect = E87_CHARGE_COMMAND_CLOSE_ELECTRICAL;
    } else if (event == E87_CHARGE_EVENT_LDO5V_IN &&
               !current->external_power_online &&
               current->phase != E87_CHARGE_PHASE_FULL &&
               current->phase != E87_CHARGE_PHASE_FAULT) {
        *want_command = true;
        *want_effect = E87_CHARGE_COMMAND_START_ELECTRICAL;
    } else if (event == E87_CHARGE_EVENT_CHARGE_FULL &&
               current->phase != E87_CHARGE_PHASE_FULL &&
               current->phase != E87_CHARGE_PHASE_FAULT) {
        *want_command = true;
        *want_effect = E87_CHARGE_COMMAND_CLOSE_ELECTRICAL;
    } else if (event == E87_CHARGE_EVENT_LDO5V_OFF ||
               event == E87_CHARGE_EVENT_LDO5V_KEEP ||
               event == E87_CHARGE_EVENT_UNSUPPORTED) {
        *want_command = true;
        *want_effect = E87_CHARGE_COMMAND_CLOSE_ELECTRICAL;
    }
}

E87_TEST(init_overwrites_poisoned_destination_and_safely_resets)
{
    struct fixture fixture;
    struct e87_charge_adapter adapter;
    struct e87_charge_adapter before;
    struct e87_charge_port invalid = {NULL, NULL, fake_publish};
    struct e87_charge_port valid = {&fixture, fake_emit, fake_publish};
    struct e87_charge_snapshot snapshot;

    memset(&adapter, 0xA5, sizeof(adapter));
    before = adapter;
    E87_ASSERT_TRUE(!e87_charge_adapter_init(NULL, &invalid));
    E87_ASSERT_TRUE(!e87_charge_adapter_init(&adapter, NULL));
    E87_ASSERT_TRUE(!e87_charge_adapter_init(&adapter, &invalid));
    E87_ASSERT_TRUE(bytes_equal(&adapter, &before, sizeof(adapter)));
    E87_ASSERT_TRUE(e87_charge_adapter_init(&adapter, &valid));
    E87_ASSERT_TRUE(e87_charge_adapter_get_snapshot(&adapter, &snapshot));
    E87_ASSERT_EQ_U32(UINT32_C(0), snapshot.external_power_online ? UINT32_C(1)
                                                                   : UINT32_C(0));
    E87_ASSERT_EQ_U32(E87_CHARGE_PHASE_UNKNOWN, snapshot.phase);
    E87_ASSERT_TRUE(fixture_init(&fixture));
    assert_snapshot(&fixture, false, E87_CHARGE_PHASE_UNKNOWN);
    E87_ASSERT_TRUE(!e87_charge_adapter_get_snapshot(NULL, &snapshot));
    E87_ASSERT_TRUE(!e87_charge_adapter_get_snapshot(&fixture.adapter, NULL));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                      e87_charge_adapter_step(
                          &fixture.adapter,
                          &(const struct e87_charge_observation) {
                              E87_CHARGE_EVENT_LDO5V_IN, UINT8_C(1)
                          }));
    E87_ASSERT_TRUE(e87_charge_adapter_init(&fixture.adapter,
                                             &fixture.adapter.private_port));
    assert_snapshot(&fixture, false, E87_CHARGE_PHASE_UNKNOWN);
    E87_ASSERT_TRUE(!e87_charge_adapter_has_pending_close(&fixture.adapter));
}

E87_TEST(exhaustive_transition_and_idempotence_matrix)
{
    static const enum e87_charge_phase phases[] = {
        E87_CHARGE_PHASE_UNKNOWN, E87_CHARGE_PHASE_CHARGING,
        E87_CHARGE_PHASE_FULL, E87_CHARGE_PHASE_CLOSED, E87_CHARGE_PHASE_FAULT
    };
    static const enum e87_charge_event events[] = {
        E87_CHARGE_EVENT_CHARGE_START, E87_CHARGE_EVENT_CHARGE_CLOSE,
        E87_CHARGE_EVENT_CHARGE_FULL, E87_CHARGE_EVENT_LDO5V_KEEP,
        E87_CHARGE_EVENT_LDO5V_IN, E87_CHARGE_EVENT_LDO5V_OFF,
        E87_CHARGE_EVENT_UNSUPPORTED
    };
    static const uint8_t raws[] = {UINT8_C(0), UINT8_C(1), UINT8_C(2), UINT8_MAX};
    size_t p;
    size_t online;
    size_t e;
    size_t r;

    for (p = 0U; p < sizeof(phases) / sizeof(phases[0]); p += 1U) {
        for (online = 0U; online < 2U; online += 1U) {
            for (e = 0U; e < sizeof(events) / sizeof(events[0]); e += 1U) {
                for (r = 0U; r < sizeof(raws) / sizeof(raws[0]); r += 1U) {
                    struct fixture fixture;
                    struct e87_charge_snapshot current;
                    struct e87_charge_snapshot candidate;
                    struct e87_charge_observation input;
                    bool has_command;
                    enum e87_charge_command command;

                    E87_ASSERT_TRUE(fixture_init(&fixture));
                    set_committed(&fixture, online != 0U, phases[p]);
                    current = fixture.adapter.private_snapshot;
                    input = observation(events[e], raws[r]);
                    matrix_anchor(&current, input.event, input.driver_online_raw,
                                  &candidate, &has_command, &command);
                    E87_ASSERT_EQ_U32(snapshot_equal(&current, &candidate)
                                          ? E87_CHARGE_RESULT_NO_CHANGE
                                          : E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                                      e87_charge_adapter_step(&fixture.adapter,
                                                              &input));
                    E87_ASSERT_EQ_U32(has_command ? UINT32_C(1) : UINT32_C(0),
                                      (uint32_t)fixture.command_count);
                    E87_ASSERT_EQ_U32(snapshot_equal(&current, &candidate)
                                          ? UINT32_C(0) : UINT32_C(1),
                                      (uint32_t)fixture.publication_count);
                    if (has_command) {
                        E87_ASSERT_EQ_U32(command, fixture.commands[0]);
                        assert_trace(&fixture, UINT32_C(2),
                                     command == E87_CHARGE_COMMAND_START_ELECTRICAL
                                         ? TRACE_EMIT_START : TRACE_EMIT_CLOSE,
                                     TRACE_PUBLISH);
                    } else if (!snapshot_equal(&current, &candidate)) {
                        assert_trace(&fixture, UINT32_C(1), TRACE_PUBLISH,
                                     TRACE_PUBLISH);
                    }
                    if (!snapshot_equal(&current, &candidate)) {
                        E87_ASSERT_TRUE(snapshot_equal(&candidate,
                                                       &fixture.publications[0]));
                    }
                    assert_snapshot(&fixture, candidate.external_power_online,
                                    candidate.phase);
                    E87_ASSERT_TRUE(!e87_charge_adapter_has_pending_close(
                        &fixture.adapter));
                }
            }
        }
    }
}

E87_TEST(normative_latches_off_clear_and_stale_unplug_race)
{
    struct fixture fixture;
    struct e87_charge_observation input;

    E87_ASSERT_TRUE(fixture_init(&fixture));
    input = observation(E87_CHARGE_EVENT_LDO5V_IN, UINT8_C(1));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                      e87_charge_adapter_step(&fixture.adapter, &input));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_NO_CHANGE,
                      e87_charge_adapter_step(&fixture.adapter, &input));
    input = observation(E87_CHARGE_EVENT_CHARGE_START, UINT8_C(1));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                      e87_charge_adapter_step(&fixture.adapter, &input));
    input = observation(E87_CHARGE_EVENT_CHARGE_FULL, UINT8_C(1));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                      e87_charge_adapter_step(&fixture.adapter, &input));
    input = observation(E87_CHARGE_EVENT_LDO5V_IN, UINT8_C(1));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_NO_CHANGE,
                      e87_charge_adapter_step(&fixture.adapter, &input));
    input = observation(E87_CHARGE_EVENT_CHARGE_CLOSE, UINT8_C(0));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                      e87_charge_adapter_step(&fixture.adapter, &input));
    assert_snapshot(&fixture, false, E87_CHARGE_PHASE_FULL);

    E87_ASSERT_TRUE(fixture_init(&fixture));
    input = observation(E87_CHARGE_EVENT_LDO5V_IN, UINT8_C(1));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                      e87_charge_adapter_step(&fixture.adapter, &input));
    input = observation(E87_CHARGE_EVENT_LDO5V_OFF, UINT8_C(0));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                      e87_charge_adapter_step(&fixture.adapter, &input));
    input = observation(E87_CHARGE_EVENT_CHARGE_START, UINT8_C(0));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                      e87_charge_adapter_step(&fixture.adapter, &input));
    input = observation(E87_CHARGE_EVENT_CHARGE_FULL, UINT8_C(0));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_NO_CHANGE,
                      e87_charge_adapter_step(&fixture.adapter, &input));
    input = observation(E87_CHARGE_EVENT_CHARGE_CLOSE, UINT8_C(0));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_NO_CHANGE,
                      e87_charge_adapter_step(&fixture.adapter, &input));
    assert_snapshot(&fixture, false, E87_CHARGE_PHASE_FAULT);
    input = observation(E87_CHARGE_EVENT_LDO5V_OFF, UINT8_C(0));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                      e87_charge_adapter_step(&fixture.adapter, &input));
    assert_snapshot(&fixture, false, E87_CHARGE_PHASE_CLOSED);
}

E87_TEST(full_observation_keeps_an_offline_fault_latch)
{
    struct fixture fixture;
    const struct e87_charge_observation full =
        {E87_CHARGE_EVENT_CHARGE_FULL, UINT8_C(1)};

    E87_ASSERT_TRUE(fixture_init(&fixture));
    set_committed(&fixture, false, E87_CHARGE_PHASE_FAULT);
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                      e87_charge_adapter_step(&fixture.adapter, &full));
    E87_ASSERT_EQ_U32(UINT32_C(0), (uint32_t)fixture.command_count);
    E87_ASSERT_EQ_U32(UINT32_C(1), (uint32_t)fixture.publication_count);
    E87_ASSERT_TRUE(snapshot_equal(
        &(const struct e87_charge_snapshot) {true, E87_CHARGE_PHASE_FAULT},
        &fixture.publications[0]));
    assert_trace(&fixture, UINT32_C(1), TRACE_PUBLISH, TRACE_PUBLISH);
    assert_snapshot(&fixture, true, E87_CHARGE_PHASE_FAULT);
}

E87_TEST(normative_sequences_preserve_latches_and_suppress_duplicates)
{
    struct fixture full;
    struct fixture keep;
    struct fixture off;
    struct fixture unsupported;
    struct fixture opposite;
    const struct e87_charge_observation in =
        {E87_CHARGE_EVENT_LDO5V_IN, UINT8_C(1)};
    const struct e87_charge_observation start =
        {E87_CHARGE_EVENT_CHARGE_START, UINT8_C(1)};
    const struct e87_charge_observation full_event =
        {E87_CHARGE_EVENT_CHARGE_FULL, UINT8_C(1)};
    const struct e87_charge_observation close_online =
        {E87_CHARGE_EVENT_CHARGE_CLOSE, UINT8_C(1)};
    const struct e87_charge_observation off_event =
        {E87_CHARGE_EVENT_LDO5V_OFF, UINT8_C(0)};
    const struct e87_charge_observation keep_event =
        {E87_CHARGE_EVENT_LDO5V_KEEP, UINT8_C(1)};
    const struct e87_charge_observation unsupported_event =
        {E87_CHARGE_EVENT_UNSUPPORTED, UINT8_C(0)};

    E87_ASSERT_TRUE(fixture_init(&full));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                      e87_charge_adapter_step(&full.adapter, &in));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                      e87_charge_adapter_step(&full.adapter, &start));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                      e87_charge_adapter_step(&full.adapter, &full_event));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_NO_CHANGE,
                      e87_charge_adapter_step(&full.adapter, &in));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_NO_CHANGE,
                      e87_charge_adapter_step(&full.adapter, &full_event));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_NO_CHANGE,
                      e87_charge_adapter_step(&full.adapter, &close_online));
    assert_callback_counts(&full, 2U, 2U, 3U, 3U);
    assert_snapshot(&full, true, E87_CHARGE_PHASE_FULL);

    E87_ASSERT_TRUE(fixture_init(&keep));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                      e87_charge_adapter_step(&keep.adapter, &in));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                      e87_charge_adapter_step(&keep.adapter, &keep_event));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_NO_CHANGE,
                      e87_charge_adapter_step(&keep.adapter, &in));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_NO_CHANGE,
                      e87_charge_adapter_step(&keep.adapter, &keep_event));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_NO_CHANGE,
                      e87_charge_adapter_step(&keep.adapter, &close_online));
    assert_callback_counts(&keep, 2U, 2U, 2U, 2U);
    assert_snapshot(&keep, true, E87_CHARGE_PHASE_FAULT);

    E87_ASSERT_TRUE(fixture_init(&off));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                      e87_charge_adapter_step(&off.adapter, &off_event));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_NO_CHANGE,
                      e87_charge_adapter_step(&off.adapter, &off_event));
    assert_callback_counts(&off, 1U, 1U, 1U, 1U);
    assert_snapshot(&off, false, E87_CHARGE_PHASE_CLOSED);

    E87_ASSERT_TRUE(fixture_init(&unsupported));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                      e87_charge_adapter_step(&unsupported.adapter,
                                              &unsupported_event));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_NO_CHANGE,
                      e87_charge_adapter_step(&unsupported.adapter,
                                              &unsupported_event));
    assert_callback_counts(&unsupported, 1U, 1U, 1U, 1U);
    assert_snapshot(&unsupported, false, E87_CHARGE_PHASE_FAULT);

    E87_ASSERT_TRUE(fixture_init(&opposite));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                      e87_charge_adapter_step(&opposite.adapter, &in));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                      e87_charge_adapter_step(&opposite.adapter, &start));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                      e87_charge_adapter_step(&opposite.adapter, &full_event));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                      e87_charge_adapter_step(&opposite.adapter, &off_event));
    assert_callback_counts(&opposite, 3U, 3U, 4U, 4U);
    assert_snapshot(&opposite, false, E87_CHARGE_PHASE_CLOSED);
}

E87_TEST(impossible_pending_candidates_reject_without_callback_or_mutation)
{
    static const enum e87_charge_phase impossible[] = {
        E87_CHARGE_PHASE_UNKNOWN, E87_CHARGE_PHASE_CHARGING,
        (enum e87_charge_phase)99
    };
    const struct e87_charge_observation input =
        {E87_CHARGE_EVENT_LDO5V_IN, UINT8_C(1)};
    size_t index;

    for (index = 0U; index < sizeof(impossible) / sizeof(impossible[0]);
         index += 1U) {
        struct fixture fixture;
        struct e87_charge_adapter before;

        E87_ASSERT_TRUE(fixture_init(&fixture));
        fixture.adapter.private_has_pending_close = true;
        fixture.adapter.private_pending_snapshot.phase = impossible[index];
        before = fixture.adapter;
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_ERROR,
                          e87_charge_adapter_step(&fixture.adapter, &input));
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_ERROR,
                          e87_charge_adapter_retry_pending_close(
                              &fixture.adapter));
        E87_ASSERT_EQ_U32(UINT32_C(0), (uint32_t)fixture.command_attempt_count);
        E87_ASSERT_EQ_U32(UINT32_C(0), (uint32_t)fixture.publish_attempt_count);
        E87_ASSERT_EQ_U32(UINT32_C(0), (uint32_t)fixture.trace_count);
        E87_ASSERT_TRUE(bytes_equal(&fixture.adapter, &before, sizeof(before)));
    }
}

E87_TEST(reentrant_emit_and_publish_reject_every_nested_event)
{
    static const enum e87_charge_event events[] = {
        E87_CHARGE_EVENT_CHARGE_START, E87_CHARGE_EVENT_CHARGE_CLOSE,
        E87_CHARGE_EVENT_CHARGE_FULL, E87_CHARGE_EVENT_LDO5V_KEEP,
        E87_CHARGE_EVENT_LDO5V_IN, E87_CHARGE_EVENT_LDO5V_OFF,
        E87_CHARGE_EVENT_UNSUPPORTED
    };
    size_t index;

    for (index = 0U; index < sizeof(events) / sizeof(events[0]); index += 1U) {
        struct fixture emit_fixture;
        struct fixture publish_fixture;
        const struct e87_charge_observation full =
            {E87_CHARGE_EVENT_CHARGE_FULL, UINT8_C(1)};
        const struct e87_charge_observation close =
            {E87_CHARGE_EVENT_CHARGE_CLOSE, UINT8_C(0)};

        E87_ASSERT_TRUE(fixture_init(&emit_fixture));
        emit_fixture.reenter_emit = true;
        emit_fixture.nested = observation(events[index], UINT8_C(1));
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                          e87_charge_adapter_step(&emit_fixture.adapter, &full));
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_ERROR, emit_fixture.nested_result);
        assert_callback_counts(&emit_fixture, 1U, 1U, 1U, 1U);
        assert_trace(&emit_fixture, 2U, TRACE_EMIT_CLOSE, TRACE_PUBLISH);
        assert_snapshot(&emit_fixture, true, E87_CHARGE_PHASE_FULL);

        E87_ASSERT_TRUE(fixture_init(&publish_fixture));
        publish_fixture.reenter_publish = true;
        publish_fixture.nested = observation(events[index], UINT8_C(1));
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                          e87_charge_adapter_step(&publish_fixture.adapter,
                                                  &close));
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_ERROR,
                          publish_fixture.nested_result);
        assert_callback_counts(&publish_fixture, 0U, 0U, 1U, 1U);
        assert_trace(&publish_fixture, 1U, TRACE_PUBLISH, TRACE_PUBLISH);
        assert_snapshot(&publish_fixture, false, E87_CHARGE_PHASE_CLOSED);
    }
}

E87_TEST(rejected_close_start_and_preclose_publish_are_retryable)
{
    static const bool before_effect[] = {false, true};
    size_t index;

    for (index = 0U; index < sizeof(before_effect) / sizeof(before_effect[0]);
         index += 1U) {
        struct fixture close_fixture;
        struct fixture start_fixture;
        struct fixture publish_fixture;
        const struct e87_charge_observation full =
            {E87_CHARGE_EVENT_CHARGE_FULL, UINT8_C(1)};
        const struct e87_charge_observation insert =
            {E87_CHARGE_EVENT_LDO5V_IN, UINT8_C(1)};
        const struct e87_charge_observation close =
            {E87_CHARGE_EVENT_CHARGE_CLOSE, UINT8_C(0)};

        E87_ASSERT_TRUE(fixture_init(&close_fixture));
        close_fixture.reject_close = true;
        close_fixture.reject_before_effect = before_effect[index];
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_PENDING_CLOSE,
                          e87_charge_adapter_step(&close_fixture.adapter, &full));
        assert_callback_counts(&close_fixture, 1U,
                               before_effect[index] ? 0U : 1U, 0U, 0U);
        assert_trace(&close_fixture, 1U, TRACE_EMIT_CLOSE, TRACE_EMIT_CLOSE);
        assert_snapshot(&close_fixture, false, E87_CHARGE_PHASE_UNKNOWN);
        assert_pending_candidate(&close_fixture, true, E87_CHARGE_PHASE_FULL);
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_PENDING_CLOSE,
                          e87_charge_adapter_retry_pending_close(
                              &close_fixture.adapter));
        assert_callback_counts(&close_fixture, 2U,
                               before_effect[index] ? 0U : 2U, 0U, 0U);
        assert_pending_candidate(&close_fixture, true, E87_CHARGE_PHASE_FULL);
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_PENDING_CLOSE,
                          e87_charge_adapter_step(&close_fixture.adapter, &insert));
        assert_callback_counts(&close_fixture, 2U,
                               before_effect[index] ? 0U : 2U, 0U, 0U);
        close_fixture.reject_close = false;
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                          e87_charge_adapter_retry_pending_close(
                              &close_fixture.adapter));
        assert_callback_counts(&close_fixture, 3U,
                               before_effect[index] ? 1U : 3U, 1U, 1U);
        assert_trace(&close_fixture, 4U, TRACE_EMIT_CLOSE, TRACE_EMIT_CLOSE);
        E87_ASSERT_EQ_U32(TRACE_EMIT_CLOSE, close_fixture.trace[2]);
        E87_ASSERT_EQ_U32(TRACE_PUBLISH, close_fixture.trace[3]);
        E87_ASSERT_TRUE(!e87_charge_adapter_has_pending_close(
            &close_fixture.adapter));
        assert_snapshot(&close_fixture, true, E87_CHARGE_PHASE_FULL);

        E87_ASSERT_TRUE(fixture_init(&start_fixture));
        start_fixture.reject_start = true;
        start_fixture.reject_before_effect = before_effect[index];
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_PENDING_CLOSE,
                          e87_charge_adapter_step(&start_fixture.adapter, &insert));
        assert_callback_counts(&start_fixture, 1U,
                               before_effect[index] ? 0U : 1U, 0U, 0U);
        assert_pending_candidate(&start_fixture, true, E87_CHARGE_PHASE_FAULT);
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_PENDING_CLOSE,
                          e87_charge_adapter_step(&start_fixture.adapter, &insert));
        assert_callback_counts(&start_fixture, 1U,
                               before_effect[index] ? 0U : 1U, 0U, 0U);
        start_fixture.reject_start = false;
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                          e87_charge_adapter_retry_pending_close(
                              &start_fixture.adapter));
        assert_callback_counts(&start_fixture, 2U,
                               before_effect[index] ? 1U : 2U, 1U, 1U);
        assert_trace(&start_fixture, 3U, TRACE_EMIT_START, TRACE_EMIT_CLOSE);
        E87_ASSERT_EQ_U32(TRACE_PUBLISH, start_fixture.trace[2]);
        assert_snapshot(&start_fixture, true, E87_CHARGE_PHASE_FAULT);

        E87_ASSERT_TRUE(fixture_init(&publish_fixture));
        publish_fixture.reject_publish = true;
        publish_fixture.reject_before_effect = before_effect[index];
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_PENDING_CLOSE,
                          e87_charge_adapter_step(&publish_fixture.adapter,
                                                  &close));
        assert_callback_counts(&publish_fixture, 0U, 0U, 1U,
                               before_effect[index] ? 0U : 1U);
        assert_snapshot(&publish_fixture, false, E87_CHARGE_PHASE_UNKNOWN);
        assert_pending_candidate(&publish_fixture, false,
                                 E87_CHARGE_PHASE_FAULT);
        publish_fixture.reject_publish = false;
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                          e87_charge_adapter_retry_pending_close(
                              &publish_fixture.adapter));
        assert_callback_counts(&publish_fixture, 1U, 1U, 2U,
                               before_effect[index] ? 1U : 2U);
        assert_trace(&publish_fixture, 3U, TRACE_PUBLISH, TRACE_EMIT_CLOSE);
        E87_ASSERT_EQ_U32(TRACE_PUBLISH, publish_fixture.trace[2]);
        assert_snapshot(&publish_fixture, false, E87_CHARGE_PHASE_FAULT);
    }
}

E87_TEST(accepted_close_publish_failure_is_terminal_and_pending_fault_strengthens)
{
    struct fixture terminal;
    struct fixture pending;
    const struct e87_charge_observation full =
        {E87_CHARGE_EVENT_CHARGE_FULL, UINT8_C(1)};

    E87_ASSERT_TRUE(fixture_init(&terminal));
    terminal.reject_publish = true;
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_ERROR,
                      e87_charge_adapter_step(&terminal.adapter, &full));
    E87_ASSERT_TRUE(!e87_charge_adapter_has_pending_close(&terminal.adapter));
    assert_snapshot(&terminal, false, E87_CHARGE_PHASE_UNKNOWN);
    terminal.reject_publish = false;
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_ERROR,
                      e87_charge_adapter_retry_pending_close(&terminal.adapter));

    E87_ASSERT_TRUE(fixture_init(&pending));
    pending.reject_close = true;
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_PENDING_CLOSE,
                      e87_charge_adapter_step(&pending.adapter, &full));
    E87_ASSERT_TRUE(e87_charge_adapter_strengthen_pending_fault(
        &pending.adapter, UINT8_C(0)));
    E87_ASSERT_TRUE(!e87_charge_adapter_strengthen_pending_fault(
        &pending.adapter, UINT8_C(2)));
    pending.reject_close = false;
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                      e87_charge_adapter_retry_pending_close(&pending.adapter));
    assert_snapshot(&pending, false, E87_CHARGE_PHASE_FAULT);
}

E87_TEST(publish_failures_and_retry_reentry_preserve_the_fail_closed_contract)
{
    static const bool before_effect[] = {false, true};
    const struct e87_charge_observation full =
        {E87_CHARGE_EVENT_CHARGE_FULL, UINT8_C(1)};
    const struct e87_charge_observation insert =
        {E87_CHARGE_EVENT_LDO5V_IN, UINT8_C(1)};
    const struct e87_charge_observation start =
        {E87_CHARGE_EVENT_CHARGE_START, UINT8_C(1)};
    size_t index;

    for (index = 0U; index < sizeof(before_effect) / sizeof(before_effect[0]);
         index += 1U) {
        struct fixture close_publish;
        struct fixture started_publish;
        struct fixture online_publish;

        E87_ASSERT_TRUE(fixture_init(&close_publish));
        close_publish.reject_publish = true;
        close_publish.reject_before_effect = before_effect[index];
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_ERROR,
                          e87_charge_adapter_step(&close_publish.adapter,
                                                  &full));
        assert_callback_counts(&close_publish, 1U, 1U, 1U,
                               before_effect[index] ? 0U : 1U);
        assert_trace(&close_publish, 2U, TRACE_EMIT_CLOSE, TRACE_PUBLISH);
        E87_ASSERT_TRUE(!e87_charge_adapter_has_pending_close(
            &close_publish.adapter));
        assert_snapshot(&close_publish, false, E87_CHARGE_PHASE_UNKNOWN);
        close_publish.reject_publish = false;
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_ERROR,
                          e87_charge_adapter_retry_pending_close(
                              &close_publish.adapter));
        assert_callback_counts(&close_publish, 1U, 1U, 1U,
                               before_effect[index] ? 0U : 1U);

        E87_ASSERT_TRUE(fixture_init(&started_publish));
        started_publish.reject_publish = true;
        started_publish.reject_before_effect = before_effect[index];
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_PENDING_CLOSE,
                          e87_charge_adapter_step(&started_publish.adapter,
                                                  &insert));
        assert_callback_counts(&started_publish, 1U, 1U, 1U,
                               before_effect[index] ? 0U : 1U);
        assert_pending_candidate(&started_publish, true,
                                 E87_CHARGE_PHASE_FAULT);
        assert_snapshot(&started_publish, false, E87_CHARGE_PHASE_UNKNOWN);
        started_publish.reject_publish = false;
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                          e87_charge_adapter_retry_pending_close(
                              &started_publish.adapter));
        assert_callback_counts(&started_publish, 2U, 2U, 2U,
                               before_effect[index] ? 1U : 2U);
        assert_trace(&started_publish, 4U, TRACE_EMIT_START, TRACE_PUBLISH);
        E87_ASSERT_EQ_U32(TRACE_EMIT_CLOSE, started_publish.trace[2]);
        /* The retry emits before it publishes; the rejected first publication
         * is necessarily earlier in the complete invocation trace. */
        E87_ASSERT_EQ_U32(TRACE_PUBLISH, started_publish.trace[3]);
        assert_snapshot(&started_publish, true, E87_CHARGE_PHASE_FAULT);

        E87_ASSERT_TRUE(fixture_init(&online_publish));
        set_committed(&online_publish, true, E87_CHARGE_PHASE_UNKNOWN);
        online_publish.reject_publish = true;
        online_publish.reject_before_effect = before_effect[index];
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_PENDING_CLOSE,
                          e87_charge_adapter_step(&online_publish.adapter,
                                                  &start));
        assert_callback_counts(&online_publish, 0U, 0U, 1U,
                               before_effect[index] ? 0U : 1U);
        assert_pending_candidate(&online_publish, true,
                                 E87_CHARGE_PHASE_FAULT);
        online_publish.reject_publish = false;
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                          e87_charge_adapter_retry_pending_close(
                              &online_publish.adapter));
        assert_callback_counts(&online_publish, 1U, 1U, 2U,
                               before_effect[index] ? 1U : 2U);
        assert_snapshot(&online_publish, true, E87_CHARGE_PHASE_FAULT);
    }
}

E87_TEST(retry_publish_failure_reentry_and_pending_strengthening_are_exact)
{
    static const struct e87_charge_observation observations[] = {
        {E87_CHARGE_EVENT_CHARGE_FULL, UINT8_C(1)},
        {E87_CHARGE_EVENT_LDO5V_OFF, UINT8_C(0)}
    };
    static const bool before_effect[] = {false, true};
    static const uint8_t strengthen_raw[] = {UINT8_C(0), UINT8_C(1)};
    struct fixture reentry;
    size_t index;

    for (index = 0U; index < sizeof(before_effect) / sizeof(before_effect[0]);
         index += 1U) {
        struct fixture retry_publish;

        E87_ASSERT_TRUE(fixture_init(&retry_publish));
        retry_publish.reject_close = true;
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_PENDING_CLOSE,
                          e87_charge_adapter_step(&retry_publish.adapter,
                                                  &observations[0]));
        assert_pending_candidate(&retry_publish, true, E87_CHARGE_PHASE_FULL);
        assert_snapshot(&retry_publish, false, E87_CHARGE_PHASE_UNKNOWN);
        retry_publish.reject_close = false;
        retry_publish.reject_publish = true;
        retry_publish.reject_before_effect = before_effect[index];
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_ERROR,
                          e87_charge_adapter_retry_pending_close(
                              &retry_publish.adapter));
        assert_callback_counts(&retry_publish, 2U, 2U, 1U,
                               before_effect[index] ? 0U : 1U);
        assert_trace(&retry_publish, 3U, TRACE_EMIT_CLOSE, TRACE_EMIT_CLOSE);
        E87_ASSERT_EQ_U32(TRACE_PUBLISH, retry_publish.trace[2]);
        E87_ASSERT_TRUE(!e87_charge_adapter_has_pending_close(
            &retry_publish.adapter));
        assert_snapshot(&retry_publish, false, E87_CHARGE_PHASE_UNKNOWN);
        retry_publish.reject_publish = false;
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_ERROR,
                          e87_charge_adapter_retry_pending_close(
                              &retry_publish.adapter));
        assert_callback_counts(&retry_publish, 2U, 2U, 1U,
                               before_effect[index] ? 0U : 1U);
    }

    E87_ASSERT_TRUE(fixture_init(&reentry));
    reentry.reject_close = true;
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_PENDING_CLOSE,
                      e87_charge_adapter_step(&reentry.adapter,
                                              &observations[0]));
    reentry.reject_close = false;
    reentry.reenter_publish = true;
    reentry.nested = observations[1];
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                      e87_charge_adapter_retry_pending_close(&reentry.adapter));
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_ERROR, reentry.nested_result);
    assert_callback_counts(&reentry, 2U, 2U, 1U, 1U);
    assert_trace(&reentry, 3U, TRACE_EMIT_CLOSE, TRACE_EMIT_CLOSE);
    E87_ASSERT_EQ_U32(TRACE_PUBLISH, reentry.trace[2]);
    E87_ASSERT_TRUE(snapshot_equal(
        &(const struct e87_charge_snapshot) {true, E87_CHARGE_PHASE_FULL},
        &reentry.publications[0]));
    E87_ASSERT_TRUE(!e87_charge_adapter_has_pending_close(&reentry.adapter));
    assert_snapshot(&reentry, true, E87_CHARGE_PHASE_FULL);

    for (index = 0U; index < sizeof(observations) / sizeof(observations[0]);
         index += 1U) {
        struct fixture pending;

        E87_ASSERT_TRUE(fixture_init(&pending));
        pending.reject_close = true;
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_PENDING_CLOSE,
                          e87_charge_adapter_step(&pending.adapter,
                                                  &observations[index]));
        E87_ASSERT_TRUE(e87_charge_adapter_strengthen_pending_fault(
            &pending.adapter, strengthen_raw[index]));
        assert_pending_candidate(&pending, strengthen_raw[index] == UINT8_C(1),
                                 E87_CHARGE_PHASE_FAULT);
        pending.reject_close = false;
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                          e87_charge_adapter_retry_pending_close(
                              &pending.adapter));
        assert_callback_counts(&pending, 2U, 2U, 1U, 1U);
        assert_trace(&pending, 3U, TRACE_EMIT_CLOSE, TRACE_EMIT_CLOSE);
        E87_ASSERT_EQ_U32(TRACE_PUBLISH, pending.trace[2]);
        E87_ASSERT_TRUE(snapshot_equal(
            &(const struct e87_charge_snapshot) {
                strengthen_raw[index] == UINT8_C(1), E87_CHARGE_PHASE_FAULT
            }, &pending.publications[0]));
        E87_ASSERT_TRUE(!e87_charge_adapter_has_pending_close(
            &pending.adapter));
        assert_snapshot(&pending, strengthen_raw[index] == UINT8_C(1),
                        E87_CHARGE_PHASE_FAULT);
    }
}

E87_TEST(corruption_and_invalid_enums_reject_without_callbacks)
{
    struct fixture fixture;
    struct e87_charge_adapter before;
    struct e87_charge_snapshot snapshot;
    const struct e87_charge_observation invalid =
        {(enum e87_charge_event)99, UINT8_C(1)};

    E87_ASSERT_TRUE(fixture_init(&fixture));
    before = fixture.adapter;
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_ERROR,
                      e87_charge_adapter_step(&fixture.adapter, &invalid));
    E87_ASSERT_TRUE(bytes_equal(&fixture.adapter, &before, sizeof(before)));
    fixture.adapter.private_snapshot.phase = (enum e87_charge_phase)99;
    before = fixture.adapter;
    E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_ERROR,
                      e87_charge_adapter_step(
                          &fixture.adapter,
                          &(const struct e87_charge_observation) {
                              E87_CHARGE_EVENT_LDO5V_IN, UINT8_C(1)
                          }));
    E87_ASSERT_TRUE(bytes_equal(&fixture.adapter, &before, sizeof(before)));
    E87_ASSERT_TRUE(!e87_charge_adapter_get_snapshot(&fixture.adapter,
                                                      &snapshot));
}

static const struct e87_test_case charge_adapter_cases[] = {
    E87_TEST_CASE(init_overwrites_poisoned_destination_and_safely_resets),
    E87_TEST_CASE(exhaustive_transition_and_idempotence_matrix),
    E87_TEST_CASE(normative_latches_off_clear_and_stale_unplug_race),
    E87_TEST_CASE(full_observation_keeps_an_offline_fault_latch),
    E87_TEST_CASE(normative_sequences_preserve_latches_and_suppress_duplicates),
    E87_TEST_CASE(impossible_pending_candidates_reject_without_callback_or_mutation),
    E87_TEST_CASE(reentrant_emit_and_publish_reject_every_nested_event),
    E87_TEST_CASE(rejected_close_start_and_preclose_publish_are_retryable),
    E87_TEST_CASE(accepted_close_publish_failure_is_terminal_and_pending_fault_strengthens),
    E87_TEST_CASE(publish_failures_and_retry_reentry_preserve_the_fail_closed_contract),
    E87_TEST_CASE(retry_publish_failure_reentry_and_pending_strengthening_are_exact),
    E87_TEST_CASE(corruption_and_invalid_enums_reject_without_callbacks)
};

const struct e87_test_suite e87_test_suite = {
    "charge-adapter", charge_adapter_cases,
    sizeof(charge_adapter_cases) / sizeof(charge_adapter_cases[0])
};
