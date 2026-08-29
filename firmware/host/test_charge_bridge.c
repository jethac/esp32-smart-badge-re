#include "test_support.h"
#include "e87/e87_charge_adapter.h"
#include "e87/e87_charge_bridge.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>


struct bridge_fixture {
    struct e87_charge_adapter adapter;
    struct e87_charge_bridge bridge;
    int irq_state;
    int critical_depth;
    int last_saved_state;
    uint32_t critical_enter_count;
    uint32_t critical_exit_count;
    uint32_t read_online_count;
    uint32_t post_count;
    uint32_t publish_count;
    uint32_t start_count;
    uint32_t close_count;
    uint8_t driver_online_raw;
    int post_result;
    bool in_irq;
    bool irq_disabled;
    bool reject_start;
    bool reject_close;
    bool reject_publish;
    bool critical_violation;
    bool fault_during_post;
    bool defer_capture_on_exit;
    bool running_deferred_capture;
    bool synchronous_command_callbacks;
    bool endless_unsupported_callbacks;
    enum e87_charge_event deferred_event;
    uint8_t deferred_online_raw;
    uint8_t endless_callback_raw;
    uint8_t post_fault_online_raw;
    enum e87_charge_command commands[64];
    struct e87_charge_snapshot publications[64];
};


static int fake_critical_enter(void *context)
{
    struct bridge_fixture *fixture = context;
    const int saved = fixture->irq_state;

    if (fixture->critical_depth != 0) {
        fixture->critical_violation = true;
    }
    fixture->critical_depth += 1;
    fixture->irq_state = 0;
    fixture->last_saved_state = saved;
    fixture->critical_enter_count += UINT32_C(1);
    return saved;
}


static void fake_critical_exit(void *context, int saved)
{
    struct bridge_fixture *fixture = context;
    bool run_deferred;

    if (fixture->critical_depth != 1 || saved != fixture->last_saved_state) {
        fixture->critical_violation = true;
    }
    fixture->critical_depth -= 1;
    fixture->irq_state = saved;
    fixture->critical_exit_count += UINT32_C(1);
    run_deferred = fixture->defer_capture_on_exit &&
                   !fixture->running_deferred_capture;
    if (run_deferred) {
        fixture->defer_capture_on_exit = false;
        fixture->running_deferred_capture = true;
        fixture->driver_online_raw = fixture->deferred_online_raw;
        (void)e87_charge_bridge_capture(
            &fixture->bridge, fixture->deferred_event);
        fixture->running_deferred_capture = false;
    }
}


static uint8_t fake_read_driver_online(void *context)
{
    struct bridge_fixture *fixture = context;

    if (fixture->critical_depth != 1) {
        fixture->critical_violation = true;
    }
    fixture->read_online_count += UINT32_C(1);
    return fixture->driver_online_raw;
}


static int fake_post_wake(void *context)
{
    struct bridge_fixture *fixture = context;

    if (fixture->critical_depth != 0) {
        fixture->critical_violation = true;
    }
    fixture->post_count += UINT32_C(1);
    if (fixture->fault_during_post) {
        fixture->fault_during_post = false;
        fixture->driver_online_raw = fixture->post_fault_online_raw;
        (void)e87_charge_bridge_note_queue_fault(&fixture->bridge);
    }
    return fixture->post_result;
}


static bool fake_in_irq(void *context)
{
    return ((struct bridge_fixture *)context)->in_irq;
}


static bool fake_irq_disabled(void *context)
{
    return ((struct bridge_fixture *)context)->irq_disabled;
}


static bool fake_emit(void *context, enum e87_charge_command command)
{
    struct bridge_fixture *fixture = context;
    enum e87_charge_event callback_event;
    uint8_t callback_raw;

    if (fixture->critical_depth != 0) {
        fixture->critical_violation = true;
    }
    if (fixture->start_count + fixture->close_count <
        sizeof(fixture->commands) / sizeof(fixture->commands[0])) {
        fixture->commands[fixture->start_count + fixture->close_count] =
            command;
    }
    if (command == E87_CHARGE_COMMAND_START_ELECTRICAL) {
        fixture->start_count += UINT32_C(1);
        if (fixture->reject_start) {
            return false;
        }
        callback_event = E87_CHARGE_EVENT_CHARGE_START;
        callback_raw = UINT8_C(1);
    } else if (command == E87_CHARGE_COMMAND_CLOSE_ELECTRICAL) {
        fixture->close_count += UINT32_C(1);
        if (fixture->reject_close) {
            return false;
        }
        callback_event = E87_CHARGE_EVENT_CHARGE_CLOSE;
        callback_raw = fixture->driver_online_raw;
    } else {
        return false;
    }
    if (fixture->endless_unsupported_callbacks) {
        fixture->endless_callback_raw ^= UINT8_C(1);
        callback_event = E87_CHARGE_EVENT_UNSUPPORTED;
        callback_raw = fixture->endless_callback_raw;
    }
    if (fixture->synchronous_command_callbacks ||
        fixture->endless_unsupported_callbacks) {
        fixture->driver_online_raw = callback_raw;
        if (!e87_charge_bridge_capture(&fixture->bridge, callback_event) &&
            !e87_charge_bridge_is_terminal(&fixture->bridge)) {
            fixture->critical_violation = true;
        }
    }
    return true;
}


static bool fake_publish(
    void *context, const struct e87_charge_snapshot *snapshot)
{
    struct bridge_fixture *fixture = context;

    if (fixture->critical_depth != 0 || snapshot == NULL) {
        fixture->critical_violation = true;
    }
    if (fixture->publish_count <
        sizeof(fixture->publications) / sizeof(fixture->publications[0])) {
        fixture->publications[fixture->publish_count] = *snapshot;
    }
    fixture->publish_count += UINT32_C(1);
    return !fixture->reject_publish;
}


static bool fixture_init(struct bridge_fixture *fixture)
{
    const struct e87_charge_port charge_port = {
        fixture,
        fake_emit,
        fake_publish
    };
    const struct e87_charge_bridge_port bridge_port = {
        fixture,
        fake_critical_enter,
        fake_critical_exit,
        fake_read_driver_online,
        fake_post_wake,
        fake_in_irq,
        fake_irq_disabled
    };

    memset(fixture, 0, sizeof(*fixture));
    fixture->irq_state = 1;
    if (!e87_charge_adapter_init(&fixture->adapter, &charge_port)) {
        return false;
    }
    return e87_charge_bridge_init(
        &fixture->bridge, &fixture->adapter, &bridge_port);
}


static void assert_guards_balanced(
    struct bridge_fixture *fixture, int expected_prior_state)
{
    E87_ASSERT_EQ_U32(
        fixture->critical_enter_count, fixture->critical_exit_count);
    E87_ASSERT_EQ_U32(UINT32_C(0), (uint32_t)fixture->critical_depth);
    E87_ASSERT_EQ_U32((uint32_t)expected_prior_state,
                      (uint32_t)fixture->irq_state);
    E87_ASSERT_TRUE(!fixture->critical_violation);
}


E87_TEST(init_rejects_unready_adapter_and_invalid_port_without_mutation)
{
    struct bridge_fixture fixture;
    struct e87_charge_bridge before;
    struct e87_charge_bridge_port bridge_port = {
        &fixture,
        fake_critical_enter,
        fake_critical_exit,
        fake_read_driver_online,
        fake_post_wake,
        fake_in_irq,
        fake_irq_disabled
    };
    const struct e87_charge_port charge_port = {
        &fixture,
        fake_emit,
        fake_publish
    };

    memset(&fixture, 0, sizeof(fixture));
    memset(&fixture.bridge, 0xA5, sizeof(fixture.bridge));
    memcpy(&before, &fixture.bridge, sizeof(before));
    E87_ASSERT_TRUE(!e87_charge_bridge_init(
        &fixture.bridge, &fixture.adapter, &bridge_port));
    E87_ASSERT_TRUE(memcmp(&fixture.bridge, &before, sizeof(before)) == 0);
    E87_ASSERT_TRUE(!e87_charge_bridge_init(
        NULL, &fixture.adapter, &bridge_port));
    E87_ASSERT_TRUE(!e87_charge_bridge_init(
        &fixture.bridge, NULL, &bridge_port));
    E87_ASSERT_TRUE(!e87_charge_bridge_init(
        &fixture.bridge, &fixture.adapter, NULL));

    E87_ASSERT_TRUE(e87_charge_adapter_init(&fixture.adapter, &charge_port));
    bridge_port.critical_enter = NULL;
    E87_ASSERT_TRUE(!e87_charge_bridge_init(
        &fixture.bridge, &fixture.adapter, &bridge_port));
    E87_ASSERT_TRUE(memcmp(&fixture.bridge, &before, sizeof(before)) == 0);
    bridge_port.critical_enter = fake_critical_enter;

    bridge_port.critical_exit = NULL;
    E87_ASSERT_TRUE(!e87_charge_bridge_init(
        &fixture.bridge, &fixture.adapter, &bridge_port));
    E87_ASSERT_TRUE(memcmp(&fixture.bridge, &before, sizeof(before)) == 0);
    bridge_port.critical_exit = fake_critical_exit;

    bridge_port.read_driver_online = NULL;
    E87_ASSERT_TRUE(!e87_charge_bridge_init(
        &fixture.bridge, &fixture.adapter, &bridge_port));
    E87_ASSERT_TRUE(memcmp(&fixture.bridge, &before, sizeof(before)) == 0);
    bridge_port.read_driver_online = fake_read_driver_online;

    bridge_port.post_wake = NULL;
    E87_ASSERT_TRUE(!e87_charge_bridge_init(
        &fixture.bridge, &fixture.adapter, &bridge_port));
    E87_ASSERT_TRUE(memcmp(&fixture.bridge, &before, sizeof(before)) == 0);
    bridge_port.post_wake = fake_post_wake;

    bridge_port.in_irq = NULL;
    E87_ASSERT_TRUE(!e87_charge_bridge_init(
        &fixture.bridge, &fixture.adapter, &bridge_port));
    E87_ASSERT_TRUE(memcmp(&fixture.bridge, &before, sizeof(before)) == 0);
    bridge_port.in_irq = fake_in_irq;

    bridge_port.irq_disabled = NULL;
    E87_ASSERT_TRUE(!e87_charge_bridge_init(
        &fixture.bridge, &fixture.adapter, &bridge_port));
    E87_ASSERT_TRUE(memcmp(&fixture.bridge, &before, sizeof(before)) == 0);
    bridge_port.irq_disabled = fake_irq_disabled;

    E87_ASSERT_TRUE(e87_charge_bridge_init(
        &fixture.bridge, &fixture.adapter, &bridge_port));
}


E87_TEST(capture_binds_read_and_append_inside_one_saved_state_guard)
{
    struct bridge_fixture fixture;

    E87_ASSERT_TRUE(fixture_init(&fixture));
    fixture.irq_state = 0x13579BDF;
    fixture.driver_online_raw = UINT8_C(1);

    E87_ASSERT_TRUE(e87_charge_bridge_capture(
        &fixture.bridge, E87_CHARGE_EVENT_LDO5V_IN));
    E87_ASSERT_EQ_U32(UINT32_C(1), fixture.read_online_count);
    E87_ASSERT_EQ_U32(UINT32_C(1), fixture.post_count);
    E87_ASSERT_EQ_U32(UINT32_C(1), fixture.bridge.private_count);
    assert_guards_balanced(&fixture, 0x13579BDF);
}


E87_TEST(post_failure_reenters_guard_and_preserves_first_fault_provenance)
{
    struct bridge_fixture fixture;

    E87_ASSERT_TRUE(fixture_init(&fixture));
    fixture.irq_state = 0x2468ACE;
    fixture.driver_online_raw = UINT8_C(1);
    fixture.post_result = 23;

    E87_ASSERT_TRUE(!e87_charge_bridge_capture(
        &fixture.bridge, E87_CHARGE_EVENT_LDO5V_IN));
    E87_ASSERT_TRUE(e87_charge_bridge_is_terminal(&fixture.bridge));
    E87_ASSERT_EQ_U32(UINT32_C(2), fixture.critical_enter_count);
    E87_ASSERT_EQ_U32(UINT8_C(1),
                      fixture.bridge.private_fault_online_raw);
    assert_guards_balanced(&fixture, 0x2468ACE);

    fixture.driver_online_raw = UINT8_C(0);
    E87_ASSERT_TRUE(!e87_charge_bridge_capture(
        &fixture.bridge, E87_CHARGE_EVENT_LDO5V_OFF));
    E87_ASSERT_EQ_U32(UINT8_C(1),
                      fixture.bridge.private_fault_online_raw);
    assert_guards_balanced(&fixture, 0x2468ACE);
}


E87_TEST(competing_fault_between_post_and_reentry_keeps_competing_provenance)
{
    struct bridge_fixture fixture;

    E87_ASSERT_TRUE(fixture_init(&fixture));
    fixture.driver_online_raw = UINT8_C(1);
    fixture.post_result = 23;
    fixture.fault_during_post = true;
    fixture.post_fault_online_raw = UINT8_C(0);

    E87_ASSERT_TRUE(!e87_charge_bridge_capture(
        &fixture.bridge, E87_CHARGE_EVENT_LDO5V_IN));
    E87_ASSERT_EQ_U32(UINT8_C(0),
                      fixture.bridge.private_fault_online_raw);
    E87_ASSERT_EQ_U32(UINT8_C(1), fixture.bridge.private_fault_pending);
    E87_ASSERT_EQ_U32(UINT32_C(2), fixture.read_online_count);

    fixture.post_result = 0;
    E87_ASSERT_EQ_U32(E87_CHARGE_BRIDGE_POLL_TERMINAL,
                      e87_charge_bridge_poll_app(&fixture.bridge));
    E87_ASSERT_EQ_U32(UINT32_C(1), fixture.close_count);
    E87_ASSERT_EQ_U32(UINT32_C(1), fixture.publish_count);
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      fixture.publications[0].external_power_online);
    E87_ASSERT_EQ_U32(E87_CHARGE_PHASE_FAULT,
                      fixture.publications[0].phase);
    assert_guards_balanced(&fixture, UINT32_C(1));
}


E87_TEST(all_callback_error_paths_pair_guards_and_restore_prior_state)
{
    struct bridge_fixture invalid_raw;
    struct bridge_fixture overflow;
    size_t index;

    E87_ASSERT_TRUE(fixture_init(&invalid_raw));
    invalid_raw.irq_state = 0x11223344;
    invalid_raw.driver_online_raw = UINT8_C(2);
    E87_ASSERT_TRUE(!e87_charge_bridge_capture(
        &invalid_raw.bridge, E87_CHARGE_EVENT_LDO5V_IN));
    E87_ASSERT_TRUE(e87_charge_bridge_is_terminal(&invalid_raw.bridge));
    assert_guards_balanced(&invalid_raw, 0x11223344);

    E87_ASSERT_TRUE(fixture_init(&overflow));
    overflow.irq_state = 0x55667788;
    overflow.driver_online_raw = UINT8_C(1);
    for (index = 0U; index < E87_CHARGE_BRIDGE_FIFO_CAPACITY; index += 1U) {
        E87_ASSERT_TRUE(e87_charge_bridge_capture(
            &overflow.bridge, E87_CHARGE_EVENT_LDO5V_IN));
    }
    E87_ASSERT_TRUE(!e87_charge_bridge_capture(
        &overflow.bridge, E87_CHARGE_EVENT_LDO5V_IN));
    E87_ASSERT_TRUE(e87_charge_bridge_is_terminal(&overflow.bridge));
    assert_guards_balanced(&overflow, 0x55667788);
}


E87_TEST(wake_acknowledgement_pairs_guard_on_success_and_wrong_type)
{
    struct bridge_fixture accepted;
    struct bridge_fixture rejected;

    E87_ASSERT_TRUE(fixture_init(&accepted));
    accepted.irq_state = 0x13572468;
    accepted.driver_online_raw = UINT8_C(1);
    E87_ASSERT_TRUE(e87_charge_bridge_capture(
        &accepted.bridge, E87_CHARGE_EVENT_LDO5V_IN));
    E87_ASSERT_TRUE(e87_charge_bridge_ack_wake(
        &accepted.bridge, E87_CHARGE_BRIDGE_WAKE_TOKEN));
    assert_guards_balanced(&accepted, 0x13572468);

    E87_ASSERT_TRUE(fixture_init(&rejected));
    rejected.irq_state = 0x24681357;
    rejected.driver_online_raw = UINT8_C(0);
    E87_ASSERT_TRUE(!e87_charge_bridge_ack_wake(
        &rejected.bridge, E87_CHARGE_BRIDGE_WAKE_TOKEN + UINT32_C(1)));
    E87_ASSERT_TRUE(e87_charge_bridge_is_terminal(&rejected.bridge));
    assert_guards_balanced(&rejected, 0x24681357);
}


E87_TEST(poll_rejects_bad_context_without_masking_or_semantic_work)
{
    struct bridge_fixture irq;
    struct bridge_fixture masked;

    E87_ASSERT_TRUE(fixture_init(&irq));
    irq.in_irq = true;
    E87_ASSERT_EQ_U32(
        E87_CHARGE_BRIDGE_POLL_ERROR,
        e87_charge_bridge_poll_app(&irq.bridge));
    E87_ASSERT_EQ_U32(UINT32_C(0), irq.critical_enter_count);
    E87_ASSERT_EQ_U32(UINT32_C(0), irq.start_count + irq.close_count);

    E87_ASSERT_TRUE(fixture_init(&masked));
    masked.irq_disabled = true;
    E87_ASSERT_EQ_U32(
        E87_CHARGE_BRIDGE_POLL_ERROR,
        e87_charge_bridge_poll_app(&masked.bridge));
    E87_ASSERT_EQ_U32(UINT32_C(0), masked.critical_enter_count);
    E87_ASSERT_EQ_U32(UINT32_C(0), masked.start_count + masked.close_count);
}


E87_TEST(pending_close_stops_then_accepted_retry_continues_tail_same_poll)
{
    struct bridge_fixture fixture;
    struct e87_charge_snapshot snapshot;
    uint8_t count_while_pending;

    E87_ASSERT_TRUE(fixture_init(&fixture));
    fixture.driver_online_raw = UINT8_C(1);
    fixture.reject_close = true;
    E87_ASSERT_TRUE(e87_charge_bridge_capture(
        &fixture.bridge, E87_CHARGE_EVENT_CHARGE_FULL));
    E87_ASSERT_TRUE(e87_charge_bridge_ack_wake(
        &fixture.bridge, E87_CHARGE_BRIDGE_WAKE_TOKEN));
    E87_ASSERT_EQ_U32(
        E87_CHARGE_BRIDGE_POLL_PENDING_CLOSE,
        e87_charge_bridge_poll_app(&fixture.bridge));
    E87_ASSERT_TRUE(e87_charge_adapter_has_pending_close(&fixture.adapter));

    fixture.driver_online_raw = UINT8_C(0);
    E87_ASSERT_TRUE(e87_charge_bridge_capture(
        &fixture.bridge, E87_CHARGE_EVENT_LDO5V_OFF));
    count_while_pending = fixture.bridge.private_count;
    E87_ASSERT_EQ_U32(
        E87_CHARGE_BRIDGE_POLL_PENDING_CLOSE,
        e87_charge_bridge_poll_app(&fixture.bridge));
    E87_ASSERT_EQ_U32(count_while_pending, fixture.bridge.private_count);

    fixture.reject_close = false;
    E87_ASSERT_EQ_U32(
        E87_CHARGE_BRIDGE_POLL_PROGRESSED,
        e87_charge_bridge_poll_app(&fixture.bridge));
    E87_ASSERT_EQ_U32(UINT32_C(0), fixture.bridge.private_count);
    E87_ASSERT_TRUE(!e87_charge_adapter_has_pending_close(&fixture.adapter));
    E87_ASSERT_EQ_U32(UINT32_C(4), fixture.close_count);
    E87_ASSERT_EQ_U32(UINT32_C(2), fixture.publish_count);
    E87_ASSERT_TRUE(e87_charge_adapter_get_snapshot(&fixture.adapter, &snapshot));
    E87_ASSERT_EQ_U32(UINT32_C(0), snapshot.external_power_online);
    E87_ASSERT_EQ_U32(E87_CHARGE_PHASE_CLOSED, snapshot.phase);
    assert_guards_balanced(&fixture, UINT32_C(1));
}


static void run_retry_publication_failure(bool with_tail)
{
    struct bridge_fixture fixture;

    E87_ASSERT_TRUE(fixture_init(&fixture));
    fixture.driver_online_raw = UINT8_C(1);
    E87_ASSERT_TRUE(e87_charge_bridge_capture(
        &fixture.bridge, E87_CHARGE_EVENT_LDO5V_IN));
    E87_ASSERT_EQ_U32(E87_CHARGE_BRIDGE_POLL_PROGRESSED,
                      e87_charge_bridge_poll_app(&fixture.bridge));
    E87_ASSERT_TRUE(e87_charge_bridge_ack_wake(
        &fixture.bridge, E87_CHARGE_BRIDGE_WAKE_TOKEN));
    E87_ASSERT_EQ_U32(E87_CHARGE_PHASE_UNKNOWN,
                      fixture.adapter.private_snapshot.phase);
    E87_ASSERT_EQ_U32(UINT32_C(1),
                      fixture.adapter.private_snapshot.external_power_online);

    fixture.reject_close = true;
    fixture.driver_online_raw = UINT8_C(1);
    E87_ASSERT_TRUE(e87_charge_bridge_capture(
        &fixture.bridge, E87_CHARGE_EVENT_CHARGE_FULL));
    E87_ASSERT_EQ_U32(E87_CHARGE_BRIDGE_POLL_PENDING_CLOSE,
                      e87_charge_bridge_poll_app(&fixture.bridge));
    if (with_tail) {
        fixture.driver_online_raw = UINT8_C(0);
        E87_ASSERT_TRUE(e87_charge_bridge_capture(
            &fixture.bridge, E87_CHARGE_EVENT_LDO5V_OFF));
        E87_ASSERT_EQ_U32(UINT32_C(1), fixture.bridge.private_count);
    }

    fixture.reject_close = false;
    fixture.reject_publish = true;
    E87_ASSERT_EQ_U32(E87_CHARGE_BRIDGE_POLL_TERMINAL,
                      e87_charge_bridge_poll_app(&fixture.bridge));
    E87_ASSERT_TRUE(e87_charge_bridge_is_terminal(&fixture.bridge));
    E87_ASSERT_TRUE(!e87_charge_bridge_is_ready(&fixture.bridge));
    E87_ASSERT_EQ_U32(UINT32_C(0), fixture.bridge.private_count);
    E87_ASSERT_EQ_U32(UINT32_C(2), fixture.close_count);
    E87_ASSERT_EQ_U32(UINT32_C(2), fixture.publish_count);
    E87_ASSERT_EQ_U32(E87_CHARGE_PHASE_UNKNOWN,
                      fixture.adapter.private_snapshot.phase);
    E87_ASSERT_EQ_U32(UINT32_C(1),
                      fixture.adapter.private_snapshot.external_power_online);
    E87_ASSERT_TRUE(fixture.adapter.private_terminal_error);
    E87_ASSERT_TRUE(!fixture.adapter.private_has_pending_close);

    E87_ASSERT_EQ_U32(E87_CHARGE_BRIDGE_POLL_TERMINAL,
                      e87_charge_bridge_poll_app(&fixture.bridge));
    E87_ASSERT_EQ_U32(UINT32_C(2), fixture.close_count);
    E87_ASSERT_EQ_U32(UINT32_C(2), fixture.publish_count);
    assert_guards_balanced(&fixture, UINT32_C(1));
}


E87_TEST(retry_publication_failure_terminalizes_empty_and_nonempty_fifo)
{
    run_retry_publication_failure(false);
    run_retry_publication_failure(true);
}


E87_TEST(corrupt_shared_state_faults_with_balanced_prior_state_restore)
{
    struct bridge_fixture fixture;

    E87_ASSERT_TRUE(fixture_init(&fixture));
    fixture.irq_state = 0x10203040;
    fixture.bridge.private_count = E87_CHARGE_BRIDGE_FIFO_CAPACITY + UINT8_C(1);
    E87_ASSERT_EQ_U32(
        E87_CHARGE_BRIDGE_POLL_TERMINAL,
        e87_charge_bridge_poll_app(&fixture.bridge));
    E87_ASSERT_TRUE(e87_charge_bridge_is_terminal(&fixture.bridge));
    assert_guards_balanced(&fixture, 0x10203040);
}


E87_TEST(all_local_events_capture_exact_closed_observations_in_fifo_order)
{
    static const enum e87_charge_event events[] = {
        E87_CHARGE_EVENT_CHARGE_START,
        E87_CHARGE_EVENT_CHARGE_CLOSE,
        E87_CHARGE_EVENT_CHARGE_FULL,
        E87_CHARGE_EVENT_LDO5V_KEEP,
        E87_CHARGE_EVENT_LDO5V_IN,
        E87_CHARGE_EVENT_LDO5V_OFF,
        E87_CHARGE_EVENT_UNSUPPORTED
    };
    static const uint8_t raw[] = {1U, 1U, 1U, 1U, 1U, 0U, 0U};
    struct bridge_fixture fixture;
    size_t index;

    E87_ASSERT_TRUE(fixture_init(&fixture));
    for (index = 0U; index < sizeof(events) / sizeof(events[0]); index += 1U) {
        fixture.driver_online_raw = raw[index];
        E87_ASSERT_TRUE(e87_charge_bridge_capture(&fixture.bridge, events[index]));
    }
    E87_ASSERT_EQ_U32(UINT32_C(1), fixture.post_count);
    E87_ASSERT_EQ_U32(UINT32_C(7), fixture.bridge.private_count);
    for (index = 0U; index < sizeof(events) / sizeof(events[0]); index += 1U) {
        E87_ASSERT_EQ_U32(events[index],
                          fixture.bridge.private_fifo[index].event);
        E87_ASSERT_EQ_U32(raw[index],
                          fixture.bridge.private_fifo[index].driver_online_raw);
    }
    assert_guards_balanced(&fixture, UINT32_C(1));
}


E87_TEST(task_irq_and_deferred_nested_irq_linearize_without_split_slots)
{
    struct bridge_fixture before;
    struct bridge_fixture during;
    struct bridge_fixture after;

    E87_ASSERT_TRUE(fixture_init(&before));
    before.in_irq = true;
    before.driver_online_raw = UINT8_C(0);
    E87_ASSERT_TRUE(e87_charge_bridge_capture(
        &before.bridge, E87_CHARGE_EVENT_LDO5V_OFF));
    before.in_irq = false;
    before.driver_online_raw = UINT8_C(1);
    E87_ASSERT_TRUE(e87_charge_bridge_capture(
        &before.bridge, E87_CHARGE_EVENT_LDO5V_IN));
    E87_ASSERT_EQ_U32(E87_CHARGE_EVENT_LDO5V_OFF,
                      before.bridge.private_fifo[0].event);
    E87_ASSERT_EQ_U32(E87_CHARGE_EVENT_LDO5V_IN,
                      before.bridge.private_fifo[1].event);
    assert_guards_balanced(&before, UINT32_C(1));

    E87_ASSERT_TRUE(fixture_init(&during));
    during.irq_state = 0x5A5A5A5A;
    during.driver_online_raw = UINT8_C(1);
    during.defer_capture_on_exit = true;
    during.deferred_event = E87_CHARGE_EVENT_LDO5V_OFF;
    during.deferred_online_raw = UINT8_C(0);
    E87_ASSERT_TRUE(e87_charge_bridge_capture(
        &during.bridge, E87_CHARGE_EVENT_LDO5V_IN));
    E87_ASSERT_EQ_U32(E87_CHARGE_EVENT_LDO5V_IN,
                      during.bridge.private_fifo[0].event);
    E87_ASSERT_EQ_U32(UINT8_C(1),
                      during.bridge.private_fifo[0].driver_online_raw);
    E87_ASSERT_EQ_U32(E87_CHARGE_EVENT_LDO5V_OFF,
                      during.bridge.private_fifo[1].event);
    E87_ASSERT_EQ_U32(UINT8_C(0),
                      during.bridge.private_fifo[1].driver_online_raw);
    assert_guards_balanced(&during, 0x5A5A5A5A);

    E87_ASSERT_TRUE(fixture_init(&after));
    after.driver_online_raw = UINT8_C(1);
    E87_ASSERT_TRUE(e87_charge_bridge_capture(
        &after.bridge, E87_CHARGE_EVENT_LDO5V_IN));
    after.in_irq = true;
    after.driver_online_raw = UINT8_C(0);
    E87_ASSERT_TRUE(e87_charge_bridge_capture(
        &after.bridge, E87_CHARGE_EVENT_LDO5V_OFF));
    E87_ASSERT_EQ_U32(E87_CHARGE_EVENT_LDO5V_IN,
                      after.bridge.private_fifo[0].event);
    E87_ASSERT_EQ_U32(E87_CHARGE_EVENT_LDO5V_OFF,
                      after.bridge.private_fifo[1].event);
    assert_guards_balanced(&after, UINT32_C(1));
}


static void run_eight_plus_eight_schedule(bool acknowledge_before_poll,
                                          uint32_t expected_posts)
{
    struct bridge_fixture fixture;
    size_t index;

    E87_ASSERT_TRUE(fixture_init(&fixture));
    fixture.synchronous_command_callbacks = true;
    for (index = 0U; index < E87_CHARGE_BRIDGE_FIFO_CAPACITY; index += 1U) {
        const bool online = (index % 2U) == 0U;

        fixture.driver_online_raw = online ? UINT8_C(1) : UINT8_C(0);
        E87_ASSERT_TRUE(e87_charge_bridge_capture(
            &fixture.bridge,
            online ? E87_CHARGE_EVENT_LDO5V_IN :
                     E87_CHARGE_EVENT_LDO5V_OFF));
    }
    E87_ASSERT_EQ_U32(UINT32_C(1), fixture.post_count);
    if (acknowledge_before_poll) {
        E87_ASSERT_TRUE(e87_charge_bridge_ack_wake(
            &fixture.bridge, E87_CHARGE_BRIDGE_WAKE_TOKEN));
    }
    E87_ASSERT_EQ_U32(E87_CHARGE_BRIDGE_POLL_PROGRESSED,
                      e87_charge_bridge_poll_app(&fixture.bridge));
    E87_ASSERT_EQ_U32(UINT32_C(0), fixture.bridge.private_count);
    E87_ASSERT_EQ_U32(UINT32_C(4), fixture.start_count);
    E87_ASSERT_EQ_U32(UINT32_C(4), fixture.close_count);
    E87_ASSERT_EQ_U32(UINT32_C(16), fixture.publish_count);
    E87_ASSERT_EQ_U32(expected_posts, fixture.post_count);
    E87_ASSERT_TRUE(e87_charge_bridge_ack_wake(
        &fixture.bridge, E87_CHARGE_BRIDGE_WAKE_TOKEN));
    E87_ASSERT_EQ_U32(UINT32_C(0), fixture.bridge.private_wake_pending);
    E87_ASSERT_TRUE(!e87_charge_bridge_is_terminal(&fixture.bridge));
    assert_guards_balanced(&fixture, UINT32_C(1));
}


E87_TEST(eight_observations_plus_eight_callbacks_use_one_or_two_wakes)
{
    run_eight_plus_eight_schedule(false, UINT32_C(1));
    run_eight_plus_eight_schedule(true, UINT32_C(2));
}


E87_TEST(sixteen_item_budget_faults_if_a_seventeenth_observation_remains)
{
    struct bridge_fixture fixture;
    size_t index;

    E87_ASSERT_TRUE(fixture_init(&fixture));
    fixture.endless_unsupported_callbacks = true;
    for (index = 0U; index < E87_CHARGE_BRIDGE_FIFO_CAPACITY; index += 1U) {
        fixture.driver_online_raw = (uint8_t)(index % 2U);
        E87_ASSERT_TRUE(e87_charge_bridge_capture(
            &fixture.bridge, E87_CHARGE_EVENT_UNSUPPORTED));
    }
    E87_ASSERT_EQ_U32(E87_CHARGE_BRIDGE_POLL_TERMINAL,
                      e87_charge_bridge_poll_app(&fixture.bridge));
    E87_ASSERT_TRUE(e87_charge_bridge_is_terminal(&fixture.bridge));
    E87_ASSERT_EQ_U32(UINT32_C(0), fixture.bridge.private_count);
    assert_guards_balanced(&fixture, UINT32_C(1));
}


E87_TEST(terminal_fault_discards_stale_fifo_closes_once_and_never_restarts)
{
    struct bridge_fixture fixture;
    struct e87_charge_snapshot snapshot;

    E87_ASSERT_TRUE(fixture_init(&fixture));
    fixture.driver_online_raw = UINT8_C(1);
    fixture.post_result = 7;
    E87_ASSERT_TRUE(!e87_charge_bridge_capture(
        &fixture.bridge, E87_CHARGE_EVENT_LDO5V_IN));
    fixture.post_result = 0;
    E87_ASSERT_EQ_U32(E87_CHARGE_BRIDGE_POLL_TERMINAL,
                      e87_charge_bridge_poll_app(&fixture.bridge));
    E87_ASSERT_EQ_U32(UINT32_C(0), fixture.start_count);
    E87_ASSERT_EQ_U32(UINT32_C(1), fixture.close_count);
    E87_ASSERT_EQ_U32(UINT32_C(1), fixture.publish_count);
    E87_ASSERT_EQ_U32(UINT32_C(0), fixture.bridge.private_count);
    E87_ASSERT_TRUE(e87_charge_adapter_get_snapshot(&fixture.adapter, &snapshot));
    E87_ASSERT_EQ_U32(UINT32_C(1), snapshot.external_power_online);
    E87_ASSERT_EQ_U32(E87_CHARGE_PHASE_FAULT, snapshot.phase);

    fixture.driver_online_raw = UINT8_C(1);
    E87_ASSERT_TRUE(!e87_charge_bridge_capture(
        &fixture.bridge, E87_CHARGE_EVENT_LDO5V_IN));
    E87_ASSERT_EQ_U32(E87_CHARGE_BRIDGE_POLL_TERMINAL,
                      e87_charge_bridge_poll_app(&fixture.bridge));
    E87_ASSERT_EQ_U32(UINT32_C(0), fixture.start_count);
    E87_ASSERT_EQ_U32(UINT32_C(1), fixture.close_count);
    E87_ASSERT_EQ_U32(UINT32_C(1), fixture.publish_count);
    assert_guards_balanced(&fixture, UINT32_C(1));
}


E87_TEST(terminal_fault_strengthens_existing_pending_candidate_before_retry)
{
    struct bridge_fixture fixture;
    struct e87_charge_snapshot snapshot;

    E87_ASSERT_TRUE(fixture_init(&fixture));
    fixture.reject_close = true;
    fixture.driver_online_raw = UINT8_C(1);
    E87_ASSERT_TRUE(e87_charge_bridge_capture(
        &fixture.bridge, E87_CHARGE_EVENT_CHARGE_FULL));
    E87_ASSERT_EQ_U32(E87_CHARGE_BRIDGE_POLL_PENDING_CLOSE,
                      e87_charge_bridge_poll_app(&fixture.bridge));
    fixture.driver_online_raw = UINT8_C(2);
    E87_ASSERT_TRUE(!e87_charge_bridge_capture(
        &fixture.bridge, E87_CHARGE_EVENT_LDO5V_OFF));
    E87_ASSERT_EQ_U32(E87_CHARGE_BRIDGE_POLL_PENDING_CLOSE,
                      e87_charge_bridge_poll_app(&fixture.bridge));
    E87_ASSERT_EQ_U32(E87_CHARGE_PHASE_FAULT,
                      fixture.adapter.private_pending_snapshot.phase);
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      fixture.adapter.private_pending_snapshot.external_power_online);
    fixture.reject_close = false;
    E87_ASSERT_EQ_U32(E87_CHARGE_BRIDGE_POLL_TERMINAL,
                      e87_charge_bridge_poll_app(&fixture.bridge));
    E87_ASSERT_TRUE(e87_charge_adapter_get_snapshot(&fixture.adapter, &snapshot));
    E87_ASSERT_EQ_U32(E87_CHARGE_PHASE_FAULT, snapshot.phase);
    E87_ASSERT_EQ_U32(UINT32_C(0), snapshot.external_power_online);
    assert_guards_balanced(&fixture, UINT32_C(1));
}


E87_TEST(queue_receive_corruption_and_bad_head_or_tail_are_terminal)
{
    struct bridge_fixture receive;
    struct bridge_fixture head;
    struct bridge_fixture tail;

    E87_ASSERT_TRUE(fixture_init(&receive));
    receive.driver_online_raw = UINT8_C(0);
    E87_ASSERT_TRUE(!e87_charge_bridge_note_queue_fault(&receive.bridge));
    E87_ASSERT_EQ_U32(E87_CHARGE_BRIDGE_POLL_TERMINAL,
                      e87_charge_bridge_poll_app(&receive.bridge));
    assert_guards_balanced(&receive, UINT32_C(1));

    E87_ASSERT_TRUE(fixture_init(&head));
    head.bridge.private_head = E87_CHARGE_BRIDGE_FIFO_CAPACITY;
    E87_ASSERT_EQ_U32(E87_CHARGE_BRIDGE_POLL_TERMINAL,
                      e87_charge_bridge_poll_app(&head.bridge));
    assert_guards_balanced(&head, UINT32_C(1));

    E87_ASSERT_TRUE(fixture_init(&tail));
    tail.bridge.private_tail = E87_CHARGE_BRIDGE_FIFO_CAPACITY;
    E87_ASSERT_EQ_U32(E87_CHARGE_BRIDGE_POLL_TERMINAL,
                      e87_charge_bridge_poll_app(&tail.bridge));
    assert_guards_balanced(&tail, UINT32_C(1));
}


static const struct e87_test_case charge_bridge_cases[] = {
    E87_TEST_CASE(init_rejects_unready_adapter_and_invalid_port_without_mutation),
    E87_TEST_CASE(capture_binds_read_and_append_inside_one_saved_state_guard),
    E87_TEST_CASE(post_failure_reenters_guard_and_preserves_first_fault_provenance),
    E87_TEST_CASE(competing_fault_between_post_and_reentry_keeps_competing_provenance),
    E87_TEST_CASE(all_callback_error_paths_pair_guards_and_restore_prior_state),
    E87_TEST_CASE(wake_acknowledgement_pairs_guard_on_success_and_wrong_type),
    E87_TEST_CASE(poll_rejects_bad_context_without_masking_or_semantic_work),
    E87_TEST_CASE(pending_close_stops_then_accepted_retry_continues_tail_same_poll),
    E87_TEST_CASE(retry_publication_failure_terminalizes_empty_and_nonempty_fifo),
    E87_TEST_CASE(corrupt_shared_state_faults_with_balanced_prior_state_restore),
    E87_TEST_CASE(all_local_events_capture_exact_closed_observations_in_fifo_order),
    E87_TEST_CASE(task_irq_and_deferred_nested_irq_linearize_without_split_slots),
    E87_TEST_CASE(eight_observations_plus_eight_callbacks_use_one_or_two_wakes),
    E87_TEST_CASE(sixteen_item_budget_faults_if_a_seventeenth_observation_remains),
    E87_TEST_CASE(terminal_fault_discards_stale_fifo_closes_once_and_never_restarts),
    E87_TEST_CASE(terminal_fault_strengthens_existing_pending_candidate_before_retry),
    E87_TEST_CASE(queue_receive_corruption_and_bad_head_or_tail_are_terminal)
};


const struct e87_test_suite e87_test_suite = {
    "charge-bridge",
    charge_bridge_cases,
    sizeof(charge_bridge_cases) / sizeof(charge_bridge_cases[0])
};
