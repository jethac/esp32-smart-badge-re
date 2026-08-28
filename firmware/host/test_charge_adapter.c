#include "test_support.h"
#include "e87/e87_charge_adapter.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define CAPACITY 64U

struct fixture {
    struct e87_charge_adapter adapter;
    enum e87_charge_command commands[CAPACITY];
    struct e87_charge_snapshot publications[CAPACITY];
    size_t command_count;
    size_t publication_count;
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

static bool latched(enum e87_charge_phase phase)
{
    return phase == E87_CHARGE_PHASE_FULL || phase == E87_CHARGE_PHASE_FAULT;
}

static bool raw_valid(uint8_t raw)
{
    return raw == UINT8_C(0) || raw == UINT8_C(1);
}

static bool consistent(enum e87_charge_event event, uint8_t raw)
{
    if (!raw_valid(raw)) {
        return false;
    }
    switch (event) {
    case E87_CHARGE_EVENT_CHARGE_START:
    case E87_CHARGE_EVENT_CHARGE_FULL:
    case E87_CHARGE_EVENT_LDO5V_KEEP:
    case E87_CHARGE_EVENT_LDO5V_IN:
        return raw == UINT8_C(1);
    case E87_CHARGE_EVENT_LDO5V_OFF:
        return raw == UINT8_C(0);
    case E87_CHARGE_EVENT_CHARGE_CLOSE:
    case E87_CHARGE_EVENT_UNSUPPORTED:
        return true;
    default:
        return false;
    }
}

static struct e87_charge_snapshot candidate_for(
    const struct e87_charge_snapshot *current, enum e87_charge_event event,
    uint8_t raw)
{
    struct e87_charge_snapshot candidate = *current;

    if (!raw_valid(raw)) {
        candidate.phase = E87_CHARGE_PHASE_FAULT;
    } else if (!consistent(event, raw)) {
        candidate.external_power_online = raw == UINT8_C(1);
        candidate.phase = E87_CHARGE_PHASE_FAULT;
    } else {
        switch (event) {
        case E87_CHARGE_EVENT_LDO5V_IN:
            candidate.external_power_online = true;
            break;
        case E87_CHARGE_EVENT_CHARGE_START:
            candidate.external_power_online = true;
            if (!latched(current->phase)) {
                candidate.phase = E87_CHARGE_PHASE_CHARGING;
            }
            break;
        case E87_CHARGE_EVENT_CHARGE_FULL:
            candidate.external_power_online = true;
            if (!(current->external_power_online &&
                  current->phase == E87_CHARGE_PHASE_FAULT)) {
                candidate.phase = E87_CHARGE_PHASE_FULL;
            }
            break;
        case E87_CHARGE_EVENT_CHARGE_CLOSE:
            candidate.external_power_online = raw == UINT8_C(1);
            if (!latched(current->phase)) {
                candidate.phase = E87_CHARGE_PHASE_CLOSED;
            }
            break;
        case E87_CHARGE_EVENT_LDO5V_OFF:
            candidate.external_power_online = false;
            candidate.phase = E87_CHARGE_PHASE_CLOSED;
            break;
        case E87_CHARGE_EVENT_LDO5V_KEEP:
        case E87_CHARGE_EVENT_UNSUPPORTED:
            candidate.external_power_online = raw == UINT8_C(1);
            candidate.phase = E87_CHARGE_PHASE_FAULT;
            break;
        default:
            break;
        }
    }
    return candidate;
}

static enum e87_charge_command command_for(
    const struct e87_charge_snapshot *current,
    const struct e87_charge_snapshot *candidate, enum e87_charge_event event,
    uint8_t raw, bool *has_command)
{
    *has_command = false;
    if (snapshot_equal(current, candidate)) {
        return E87_CHARGE_COMMAND_START_ELECTRICAL;
    }
    if (!raw_valid(raw) || !consistent(event, raw)) {
        *has_command = true;
        return E87_CHARGE_COMMAND_CLOSE_ELECTRICAL;
    }
    if (event == E87_CHARGE_EVENT_LDO5V_IN &&
        !current->external_power_online && !latched(current->phase)) {
        *has_command = true;
        return E87_CHARGE_COMMAND_START_ELECTRICAL;
    }
    if (event == E87_CHARGE_EVENT_CHARGE_FULL && !latched(current->phase)) {
        *has_command = true;
        return E87_CHARGE_COMMAND_CLOSE_ELECTRICAL;
    }
    if (event == E87_CHARGE_EVENT_LDO5V_OFF ||
        event == E87_CHARGE_EVENT_LDO5V_KEEP ||
        event == E87_CHARGE_EVENT_UNSUPPORTED) {
        *has_command = true;
        return E87_CHARGE_COMMAND_CLOSE_ELECTRICAL;
    }
    return E87_CHARGE_COMMAND_START_ELECTRICAL;
}

E87_TEST(init_snapshot_and_invalid_inputs_are_atomic)
{
    struct fixture fixture;
    struct e87_charge_adapter adapter;
    struct e87_charge_adapter before;
    struct e87_charge_port invalid = {NULL, NULL, fake_publish};
    struct e87_charge_snapshot snapshot;

    memset(&adapter, 0xA5, sizeof(adapter));
    before = adapter;
    E87_ASSERT_TRUE(!e87_charge_adapter_init(NULL, &invalid));
    E87_ASSERT_TRUE(!e87_charge_adapter_init(&adapter, NULL));
    E87_ASSERT_TRUE(!e87_charge_adapter_init(&adapter, &invalid));
    E87_ASSERT_TRUE(bytes_equal(&adapter, &before, sizeof(adapter)));
    E87_ASSERT_TRUE(fixture_init(&fixture));
    assert_snapshot(&fixture, false, E87_CHARGE_PHASE_UNKNOWN);
    E87_ASSERT_TRUE(!e87_charge_adapter_get_snapshot(NULL, &snapshot));
    E87_ASSERT_TRUE(!e87_charge_adapter_get_snapshot(&fixture.adapter, NULL));
    before = fixture.adapter;
    E87_ASSERT_TRUE(!e87_charge_adapter_init(&fixture.adapter,
                                              &fixture.adapter.private_port));
    E87_ASSERT_TRUE(bytes_equal(&fixture.adapter, &before, sizeof(before)));
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
                    candidate = candidate_for(&current, input.event,
                                              input.driver_online_raw);
                    command = command_for(&current, &candidate, input.event,
                                          input.driver_online_raw, &has_command);
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
        E87_ASSERT_EQ_U32(UINT32_C(1), emit_fixture.publication_count);
        assert_snapshot(&emit_fixture, true, E87_CHARGE_PHASE_FULL);

        E87_ASSERT_TRUE(fixture_init(&publish_fixture));
        publish_fixture.reenter_publish = true;
        publish_fixture.nested = observation(events[index], UINT8_C(1));
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                          e87_charge_adapter_step(&publish_fixture.adapter,
                                                  &close));
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_ERROR,
                          publish_fixture.nested_result);
        E87_ASSERT_EQ_U32(UINT32_C(1), publish_fixture.publication_count);
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
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_PENDING_CLOSE,
                          e87_charge_adapter_retry_pending_close(
                              &close_fixture.adapter));
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_PENDING_CLOSE,
                          e87_charge_adapter_step(&close_fixture.adapter, &insert));
        close_fixture.reject_close = false;
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                          e87_charge_adapter_retry_pending_close(
                              &close_fixture.adapter));
        assert_snapshot(&close_fixture, true, E87_CHARGE_PHASE_FULL);

        E87_ASSERT_TRUE(fixture_init(&start_fixture));
        start_fixture.reject_start = true;
        start_fixture.reject_before_effect = before_effect[index];
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_PENDING_CLOSE,
                          e87_charge_adapter_step(&start_fixture.adapter, &insert));
        start_fixture.reject_start = false;
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                          e87_charge_adapter_retry_pending_close(
                              &start_fixture.adapter));
        assert_snapshot(&start_fixture, true, E87_CHARGE_PHASE_FAULT);

        E87_ASSERT_TRUE(fixture_init(&publish_fixture));
        publish_fixture.reject_publish = true;
        publish_fixture.reject_before_effect = before_effect[index];
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_PENDING_CLOSE,
                          e87_charge_adapter_step(&publish_fixture.adapter,
                                                  &close));
        publish_fixture.reject_publish = false;
        E87_ASSERT_EQ_U32(E87_CHARGE_RESULT_SNAPSHOT_UPDATED,
                          e87_charge_adapter_retry_pending_close(
                              &publish_fixture.adapter));
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
    E87_TEST_CASE(init_snapshot_and_invalid_inputs_are_atomic),
    E87_TEST_CASE(exhaustive_transition_and_idempotence_matrix),
    E87_TEST_CASE(normative_latches_off_clear_and_stale_unplug_race),
    E87_TEST_CASE(reentrant_emit_and_publish_reject_every_nested_event),
    E87_TEST_CASE(rejected_close_start_and_preclose_publish_are_retryable),
    E87_TEST_CASE(accepted_close_publish_failure_is_terminal_and_pending_fault_strengthens),
    E87_TEST_CASE(corruption_and_invalid_enums_reject_without_callbacks)
};

const struct e87_test_suite e87_test_suite = {
    "charge-adapter", charge_adapter_cases,
    sizeof(charge_adapter_cases) / sizeof(charge_adapter_cases[0])
};
