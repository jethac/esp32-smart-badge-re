#include "test_support.h"
#include "e87/e87_maintenance.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define COMMAND_CAPACITY 64U
#define TARGET_CALL_CAPACITY 64U

struct fake_sink {
    struct e87_maintenance *maintenance;
    enum e87_maintenance_command commands[COMMAND_CAPACITY];
    struct e87_maintenance_handoff handoffs[COMMAND_CAPACITY];
    bool has_handoff[COMMAND_CAPACITY];
    size_t count;
    size_t reject_index;
    bool reenter;
    bool reentered;
    enum e87_maintenance_result reentry_result;
};

static bool bytes_equal(const void *left, const void *right, size_t length)
{
    return memcmp(left, right, length) == 0;
}

static bool fake_emit(
    void *context,
    enum e87_maintenance_command command,
    const struct e87_maintenance_handoff *handoff)
{
    struct fake_sink *sink = (struct fake_sink *)context;
    const size_t index = sink->count;

    if (index >= COMMAND_CAPACITY) {
        return false;
    }
    sink->commands[index] = command;
    sink->has_handoff[index] = handoff != NULL;
    if (handoff != NULL) {
        sink->handoffs[index] = *handoff;
    }
    sink->count += 1U;
    if (sink->reenter && !sink->reentered) {
        const struct e87_maintenance_event event = {
            E87_MAINTENANCE_EVENT_CANCEL, UINT32_C(9), {0}, false
        };

        sink->reentered = true;
        sink->reentry_result =
            e87_maintenance_step(sink->maintenance, &event);
    }
    return index != sink->reject_index;
}

static bool init_maintenance(struct e87_maintenance *maintenance,
                             struct fake_sink *sink)
{
    const struct e87_maintenance_port port = {sink, fake_emit};

    memset(sink, 0, sizeof(*sink));
    sink->maintenance = maintenance;
    sink->reject_index = SIZE_MAX;
    sink->reentry_result = E87_MAINTENANCE_RESULT_NO_CHANGE;
    memset(maintenance, 0xA5, sizeof(*maintenance));
    return e87_maintenance_init(maintenance, &port);
}

static struct e87_maintenance_event event_at(
    enum e87_maintenance_event_type type,
    uint32_t now_ms)
{
    const struct e87_maintenance_event event = {
        type, now_ms, {0}, false
    };

    return event;
}

static struct e87_maintenance_event power_at(
    uint32_t now_ms,
    uint8_t percent,
    bool low_voltage_warning,
    bool board_voltage_stable,
    bool external_power_online,
    enum e87_charger_phase charger_phase)
{
    struct e87_maintenance_event event =
        event_at(E87_MAINTENANCE_EVENT_POWER_SAMPLE, now_ms);

    event.power.percent = percent;
    event.power.low_voltage_warning = low_voltage_warning;
    event.power.board_voltage_stable = board_voltage_stable;
    event.power.external_power_online = external_power_online;
    event.power.charger_phase = charger_phase;
    return event;
}

static struct e87_rcsp_official_loader_report valid_loader_report(void)
{
    static const uint8_t expected_profile[E87_RCSP_PROFILE_ID_BYTES] = {
        'E', '8', '7', '-', 'J', 'D', '9', '8',
        '5', '5', '-', 'R', '1', 0, 0, 0
    };
    struct e87_rcsp_official_loader_report report = {0};

    report.update_type = E87_RCSP_SDK_BLE_APP_UPDATE_TYPE;
    report.update_state = E87_RCSP_SDK_UPDATE_SUCCESS_STATE;
    report.loader_result = E87_RCSP_SDK_LOADER_OK;
    report.loader_saddr = UINT32_C(0x00123456);
    report.chip = E87_UPDATE_CHIP_AC707N;
    report.layout = E87_UPDATE_LAYOUT_SINGLE_BANK;
    report.exact_layout_match = true;
    memcpy(report.profile_id, expected_profile, sizeof(expected_profile));
    return report;
}

static bool enter_at(struct e87_maintenance *maintenance, uint32_t now_ms)
{
    const struct e87_maintenance_event event =
        event_at(E87_MAINTENANCE_EVENT_ENTER_AFTER_NORMAL_DISCONNECT,
                 now_ms);

    return e87_maintenance_step(maintenance, &event) ==
           E87_MAINTENANCE_RESULT_ACTIVE;
}

static bool authenticate_at(struct e87_maintenance *maintenance,
                            uint32_t now_ms)
{
    const struct e87_maintenance_event event =
        event_at(E87_MAINTENANCE_EVENT_AUTHENTICATED, now_ms);

    return e87_maintenance_step(maintenance, &event) ==
           E87_MAINTENANCE_RESULT_AUTHENTICATED;
}

static bool finish_exit(struct e87_maintenance *maintenance)
{
    struct e87_maintenance_event event =
        event_at(E87_MAINTENANCE_EVENT_TRANSPORT_QUIESCED,
                 UINT32_C(500000));

    if (e87_maintenance_step(maintenance, &event) !=
        E87_MAINTENANCE_RESULT_WAITING_FOR_RCSP_RELEASE) {
        return false;
    }
    event = event_at(E87_MAINTENANCE_EVENT_RCSP_RELEASE_STATUS,
                     UINT32_C(500000));
    event.rcsp_handle_present = false;
    return e87_maintenance_step(maintenance, &event) ==
               E87_MAINTENANCE_RESULT_NORMAL_REQUESTED;
}

static size_t command_occurrences(
    const struct fake_sink *sink,
    enum e87_maintenance_command command)
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

E87_TEST(init_is_side_effect_free_and_entry_uses_exact_rcsp_order)
{
    struct e87_maintenance maintenance;
    struct e87_maintenance before;
    struct e87_maintenance_port invalid_port = {0};
    struct e87_maintenance_view view;
    struct fake_sink sink;

    memset(&maintenance, 0xA5, sizeof(maintenance));
    before = maintenance;
    E87_ASSERT_TRUE(!e87_maintenance_init(NULL, NULL));
    E87_ASSERT_TRUE(!e87_maintenance_init(&maintenance, NULL));
    E87_ASSERT_TRUE(bytes_equal(&maintenance, &before, sizeof(maintenance)));
    E87_ASSERT_TRUE(!e87_maintenance_init(&maintenance, &invalid_port));
    E87_ASSERT_TRUE(bytes_equal(&maintenance, &before, sizeof(maintenance)));

    E87_ASSERT_TRUE(init_maintenance(&maintenance, &sink));
    E87_ASSERT_EQ_U32(UINT32_C(0), sink.count);
    E87_ASSERT_TRUE(e87_maintenance_get_view(&maintenance, &view));
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_STATE_READY, view.state);
    E87_ASSERT_TRUE(enter_at(&maintenance, UINT32_C(77)));
    E87_ASSERT_EQ_U32(UINT32_C(3), sink.count);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_RCSP_INTERFACE_INIT,
                      sink.commands[0]);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_RCSP_INIT,
                      sink.commands[1]);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_RCSP_BLE_INIT,
                      sink.commands[2]);
    E87_ASSERT_TRUE(!sink.has_handoff[0]);
    E87_ASSERT_TRUE(!sink.has_handoff[1]);
    E87_ASSERT_TRUE(!sink.has_handoff[2]);
    E87_ASSERT_TRUE(e87_maintenance_get_view(&maintenance, &view));
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_STATE_ACTIVE, view.state);
    E87_ASSERT_TRUE(!view.authenticated);
}

E87_TEST(unauthenticated_timeout_has_exact_boundary_and_orderly_exit)
{
    struct e87_maintenance maintenance;
    struct fake_sink sink;
    struct e87_maintenance_event event;

    E87_ASSERT_TRUE(init_maintenance(&maintenance, &sink));
    E87_ASSERT_TRUE(enter_at(&maintenance, UINT32_C(1000)));
    event = event_at(E87_MAINTENANCE_EVENT_POLL, UINT32_C(120999));
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_NO_CHANGE,
                      e87_maintenance_step(&maintenance, &event));
    E87_ASSERT_EQ_U32(UINT32_C(3), sink.count);

    event.now_ms = UINT32_C(121000);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_EXITING,
                      e87_maintenance_step(&maintenance, &event));
    E87_ASSERT_EQ_U32(UINT32_C(6), sink.count);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_REJECT_COMMANDS,
                      sink.commands[3]);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_STOP_ADVERTISING,
                      sink.commands[4]);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_DISCONNECT,
                      sink.commands[5]);
    E87_ASSERT_TRUE(finish_exit(&maintenance));
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_RCSP_BLE_EXIT,
                      sink.commands[6]);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_RCSP_INTERFACE_EXIT,
                      sink.commands[7]);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_REQUEST_NORMAL_MODE,
                      sink.commands[8]);
}

E87_TEST(rcsp_interface_exit_waits_for_null_handle_and_times_out_fail_safe)
{
    struct e87_maintenance maintenance;
    struct fake_sink sink;
    struct e87_maintenance_event event;

    E87_ASSERT_TRUE(init_maintenance(&maintenance, &sink));
    E87_ASSERT_TRUE(enter_at(&maintenance, UINT32_C(0)));
    event = event_at(E87_MAINTENANCE_EVENT_CANCEL, UINT32_C(1));
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_EXITING,
                      e87_maintenance_step(&maintenance, &event));
    event = event_at(E87_MAINTENANCE_EVENT_TRANSPORT_QUIESCED,
                     UINT32_C(100));
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_WAITING_FOR_RCSP_RELEASE,
                      e87_maintenance_step(&maintenance, &event));
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_RCSP_BLE_EXIT,
                      sink.commands[6]);
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      command_occurrences(
                          &sink,
                          E87_MAINTENANCE_COMMAND_RCSP_INTERFACE_EXIT));
    event = event_at(E87_MAINTENANCE_EVENT_RCSP_RELEASE_STATUS,
                     UINT32_C(5099));
    event.rcsp_handle_present = true;
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_WAITING_FOR_RCSP_RELEASE,
                      e87_maintenance_step(&maintenance, &event));
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      command_occurrences(
                          &sink,
                          E87_MAINTENANCE_COMMAND_RCSP_INTERFACE_EXIT));
    event.now_ms = UINT32_C(5100);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_ERROR,
                      e87_maintenance_step(&maintenance, &event));
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      command_occurrences(
                          &sink,
                          E87_MAINTENANCE_COMMAND_RCSP_INTERFACE_EXIT));
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      command_occurrences(
                          &sink,
                          E87_MAINTENANCE_COMMAND_REQUEST_NORMAL_MODE));
}

E87_TEST(authentication_cancels_timeout_and_disconnect_restarts_it)
{
    struct e87_maintenance maintenance;
    struct fake_sink sink;
    struct e87_maintenance_event event;

    E87_ASSERT_TRUE(init_maintenance(&maintenance, &sink));
    E87_ASSERT_TRUE(enter_at(&maintenance, UINT32_MAX - UINT32_C(1000)));
    E87_ASSERT_TRUE(authenticate_at(&maintenance, UINT32_MAX - UINT32_C(1)));
    event = event_at(E87_MAINTENANCE_EVENT_POLL, UINT32_C(500000));
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_NO_CHANGE,
                      e87_maintenance_step(&maintenance, &event));
    E87_ASSERT_EQ_U32(UINT32_C(3), sink.count);

    event = event_at(E87_MAINTENANCE_EVENT_HOST_DISCONNECTED,
                     UINT32_MAX - UINT32_C(50));
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_ACTIVE,
                      e87_maintenance_step(&maintenance, &event));
    event = event_at(E87_MAINTENANCE_EVENT_POLL, UINT32_C(119948));
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_NO_CHANGE,
                      e87_maintenance_step(&maintenance, &event));
    event.now_ms = UINT32_C(119949);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_EXITING,
                      e87_maintenance_step(&maintenance, &event));
}

static bool prepare_abort_case(struct e87_maintenance *maintenance,
                               struct fake_sink *sink,
                               unsigned int phase)
{
    struct e87_maintenance_event sample;
    struct e87_rcsp_official_loader_report report;

    if (!init_maintenance(maintenance, sink) ||
        !enter_at(maintenance, UINT32_C(0))) {
        return false;
    }
    if (phase >= 1U && !authenticate_at(maintenance, UINT32_C(1))) {
        return false;
    }
    if (phase == 2U) {
        report = valid_loader_report();
        if (e87_rcsp_official_loader_callback(
                maintenance, UINT32_C(2), &report) !=
            E87_MAINTENANCE_RESULT_HANDOFF_WAITING) {
            return false;
        }
    }
    if (phase == 3U) {
        sample = power_at(UINT32_C(2), 50U, false, true, false,
                          E87_CHARGER_PHASE_CLOSE);
        if (e87_maintenance_step(maintenance, &sample) !=
            E87_MAINTENANCE_RESULT_STATUS_UPDATED) {
            return false;
        }
        sample.now_ms = UINT32_C(5002);
        if (e87_maintenance_step(maintenance, &sample) !=
            E87_MAINTENANCE_RESULT_STATUS_UPDATED) {
            return false;
        }
    }
    return true;
}

E87_TEST(cancel_and_failure_abort_every_pre_handoff_phase)
{
    unsigned int phase;
    unsigned int failure;

    for (phase = 0U; phase < 4U; phase += 1U) {
        for (failure = 0U; failure < 2U; failure += 1U) {
            struct e87_maintenance maintenance;
            struct fake_sink sink;
            struct e87_maintenance_event event;

            E87_ASSERT_TRUE(prepare_abort_case(&maintenance, &sink, phase));
            event = event_at(
                failure == 0U ? E87_MAINTENANCE_EVENT_CANCEL
                              : E87_MAINTENANCE_EVENT_FAILURE,
                UINT32_C(6000));
            E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_EXITING,
                              e87_maintenance_step(&maintenance, &event));
            E87_ASSERT_EQ_U32(UINT32_C(1),
                              command_occurrences(
                                  &sink,
                                  E87_MAINTENANCE_COMMAND_REJECT_COMMANDS));
            E87_ASSERT_EQ_U32(UINT32_C(1),
                              command_occurrences(
                                  &sink,
                                  E87_MAINTENANCE_COMMAND_STOP_ADVERTISING));
            E87_ASSERT_EQ_U32(UINT32_C(1),
                              command_occurrences(
                                  &sink,
                                  E87_MAINTENANCE_COMMAND_DISCONNECT));
            E87_ASSERT_EQ_U32(UINT32_C(0),
                              command_occurrences(
                                  &sink,
                                  E87_MAINTENANCE_COMMAND_OFFICIAL_HANDOFF));
            E87_ASSERT_TRUE(finish_exit(&maintenance));
        }
    }
}

E87_TEST(charging_never_bypasses_49_percent_and_50_is_inclusive)
{
    struct e87_maintenance maintenance;
    struct fake_sink sink;
    struct e87_maintenance_event sample;
    struct e87_rcsp_official_loader_report report = valid_loader_report();

    E87_ASSERT_TRUE(init_maintenance(&maintenance, &sink));
    E87_ASSERT_TRUE(enter_at(&maintenance, UINT32_C(0)));
    E87_ASSERT_TRUE(authenticate_at(&maintenance, UINT32_C(0)));
    E87_ASSERT_EQ_U32(
        E87_MAINTENANCE_RESULT_HANDOFF_WAITING,
        e87_rcsp_official_loader_callback(
            &maintenance, UINT32_C(0), &report));

    sample = power_at(UINT32_C(0), 49U, false, true, true,
                      E87_CHARGER_PHASE_START);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_STATUS_UPDATED,
                      e87_maintenance_step(&maintenance, &sample));
    sample.now_ms = UINT32_C(5000);
    sample.power.charger_phase = E87_CHARGER_PHASE_FULL;
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_STATUS_UPDATED,
                      e87_maintenance_step(&maintenance, &sample));
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      command_occurrences(
                          &sink,
                          E87_MAINTENANCE_COMMAND_OFFICIAL_HANDOFF));

    sample = power_at(UINT32_C(6000), 50U, false, true, false,
                      E87_CHARGER_PHASE_CLOSE);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_STATUS_UPDATED,
                      e87_maintenance_step(&maintenance, &sample));
    sample.now_ms = UINT32_C(10999);
    sample.power.external_power_online = true;
    sample.power.charger_phase = E87_CHARGER_PHASE_FULL;
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_STATUS_UPDATED,
                      e87_maintenance_step(&maintenance, &sample));
    sample.now_ms = UINT32_C(11000);
    sample.power.charger_phase = E87_CHARGER_PHASE_CLOSE;
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_HANDOFF_REQUESTED,
                      e87_maintenance_step(&maintenance, &sample));
    E87_ASSERT_EQ_U32(UINT32_C(1),
                      command_occurrences(
                          &sink,
                          E87_MAINTENANCE_COMMAND_OFFICIAL_HANDOFF));
}

E87_TEST(low_voltage_or_unstable_voltage_resets_five_second_window)
{
    struct e87_maintenance maintenance;
    struct fake_sink sink;
    struct e87_maintenance_event sample;
    struct e87_rcsp_official_loader_report report = valid_loader_report();

    E87_ASSERT_TRUE(init_maintenance(&maintenance, &sink));
    E87_ASSERT_TRUE(enter_at(&maintenance, UINT32_C(0)));
    E87_ASSERT_TRUE(authenticate_at(&maintenance, UINT32_C(0)));
    E87_ASSERT_EQ_U32(
        E87_MAINTENANCE_RESULT_HANDOFF_WAITING,
        e87_rcsp_official_loader_callback(
            &maintenance, UINT32_C(0), &report));
    sample = power_at(UINT32_C(0), 50U, false, true, false,
                      E87_CHARGER_PHASE_CLOSE);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_STATUS_UPDATED,
                      e87_maintenance_step(&maintenance, &sample));
    sample = power_at(UINT32_C(5000), 100U, true, true, true,
                      E87_CHARGER_PHASE_FULL);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_STATUS_UPDATED,
                      e87_maintenance_step(&maintenance, &sample));
    sample = power_at(UINT32_C(6000), 100U, false, false, true,
                      E87_CHARGER_PHASE_FULL);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_STATUS_UPDATED,
                      e87_maintenance_step(&maintenance, &sample));
    sample = power_at(UINT32_C(7000), 100U, false, true, true,
                      E87_CHARGER_PHASE_FULL);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_STATUS_UPDATED,
                      e87_maintenance_step(&maintenance, &sample));
    sample.now_ms = UINT32_C(11999);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_STATUS_UPDATED,
                      e87_maintenance_step(&maintenance, &sample));
    sample.now_ms = UINT32_C(12000);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_HANDOFF_REQUESTED,
                      e87_maintenance_step(&maintenance, &sample));
}

E87_TEST(power_window_handles_wrap_and_restarts_on_backward_sample)
{
    {
        struct e87_maintenance maintenance;
        struct fake_sink sink;
        struct e87_maintenance_event sample;
        struct e87_rcsp_official_loader_report report =
            valid_loader_report();

        E87_ASSERT_TRUE(init_maintenance(&maintenance, &sink));
        E87_ASSERT_TRUE(enter_at(&maintenance, UINT32_C(0)));
        E87_ASSERT_TRUE(authenticate_at(&maintenance, UINT32_C(0)));
        E87_ASSERT_EQ_U32(
            E87_MAINTENANCE_RESULT_HANDOFF_WAITING,
            e87_rcsp_official_loader_callback(
                &maintenance, UINT32_C(0), &report));
        sample = power_at(UINT32_MAX - UINT32_C(2500), 50U, false,
                          true, false, E87_CHARGER_PHASE_CLOSE);
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_STATUS_UPDATED,
                          e87_maintenance_step(&maintenance, &sample));
        sample.now_ms = UINT32_C(2498);
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_STATUS_UPDATED,
                          e87_maintenance_step(&maintenance, &sample));
        sample.now_ms = UINT32_C(2499);
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_HANDOFF_REQUESTED,
                          e87_maintenance_step(&maintenance, &sample));
    }

    {
        struct e87_maintenance maintenance;
        struct fake_sink sink;
        struct e87_maintenance_event sample;
        struct e87_rcsp_official_loader_report report =
            valid_loader_report();

        E87_ASSERT_TRUE(init_maintenance(&maintenance, &sink));
        E87_ASSERT_TRUE(enter_at(&maintenance, UINT32_C(0)));
        E87_ASSERT_TRUE(authenticate_at(&maintenance, UINT32_C(0)));
        E87_ASSERT_EQ_U32(
            E87_MAINTENANCE_RESULT_HANDOFF_WAITING,
            e87_rcsp_official_loader_callback(
                &maintenance, UINT32_C(0), &report));
        sample = power_at(UINT32_C(10000), 50U, false, true, false,
                          E87_CHARGER_PHASE_CLOSE);
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_STATUS_UPDATED,
                          e87_maintenance_step(&maintenance, &sample));
        sample.now_ms = UINT32_C(9999);
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_STATUS_UPDATED,
                          e87_maintenance_step(&maintenance, &sample));
        sample.now_ms = UINT32_C(14998);
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_STATUS_UPDATED,
                          e87_maintenance_step(&maintenance, &sample));
        sample.now_ms = UINT32_C(14999);
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_HANDOFF_REQUESTED,
                          e87_maintenance_step(&maintenance, &sample));
    }
}

E87_TEST(official_callback_rejects_every_loader_identity_mismatch)
{
    unsigned int variant;

    for (variant = 0U; variant < 9U; variant += 1U) {
        struct e87_maintenance maintenance;
        struct fake_sink sink;
        struct e87_rcsp_official_loader_report report =
            valid_loader_report();

        E87_ASSERT_TRUE(init_maintenance(&maintenance, &sink));
        E87_ASSERT_TRUE(enter_at(&maintenance, UINT32_C(0)));
        if (variant != 8U) {
            E87_ASSERT_TRUE(authenticate_at(&maintenance, UINT32_C(0)));
        }
        switch (variant) {
        case 0U:
            report.update_type += UINT32_C(1);
            break;
        case 1U:
            report.update_state += UINT32_C(1);
            break;
        case 2U:
            report.loader_result = UINT8_C(2);
            break;
        case 3U:
            report.loader_saddr = UINT32_C(0);
            break;
        case 4U:
            report.chip = E87_UPDATE_CHIP_OTHER;
            break;
        case 5U:
            report.layout = E87_UPDATE_LAYOUT_DUAL_BANK;
            break;
        case 6U:
            report.exact_layout_match = false;
            break;
        case 7U:
            report.profile_id[12] = '2';
            break;
        case 8U:
            break;
        default:
            E87_ASSERT_TRUE(false);
            return;
        }
        E87_ASSERT_EQ_U32(
            E87_MAINTENANCE_RESULT_EXITING,
            e87_rcsp_official_loader_callback(
                &maintenance, UINT32_C(1), &report));
        E87_ASSERT_EQ_U32(UINT32_C(0),
                          command_occurrences(
                              &sink,
                              E87_MAINTENANCE_COMMAND_OFFICIAL_HANDOFF));
    }
}

E87_TEST(valid_official_callback_approves_then_commits_at_official_boundary)
{
    static const uint8_t expected_profile[E87_RCSP_PROFILE_ID_BYTES] = {
        'E', '8', '7', '-', 'J', 'D', '9', '8',
        '5', '5', '-', 'R', '1', 0, 0, 0
    };
    struct e87_maintenance maintenance;
    struct fake_sink sink;
    struct e87_maintenance_event sample;
    struct e87_maintenance_event cancel;
    struct e87_rcsp_official_loader_report report = valid_loader_report();
    const struct e87_maintenance_handoff *handoff;
    struct e87_maintenance_view view;

    E87_ASSERT_TRUE(init_maintenance(&maintenance, &sink));
    E87_ASSERT_TRUE(enter_at(&maintenance, UINT32_C(100)));
    E87_ASSERT_TRUE(authenticate_at(&maintenance, UINT32_C(100)));
    sample = power_at(UINT32_C(100), 50U, false, true, true,
                      E87_CHARGER_PHASE_FULL);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_STATUS_UPDATED,
                      e87_maintenance_step(&maintenance, &sample));
    sample.now_ms = UINT32_C(5100);
    sample.power.charger_phase = E87_CHARGER_PHASE_CLOSE;
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_STATUS_UPDATED,
                      e87_maintenance_step(&maintenance, &sample));
    E87_ASSERT_EQ_U32(
        E87_MAINTENANCE_RESULT_HANDOFF_REQUESTED,
        e87_rcsp_official_loader_callback(
            &maintenance, UINT32_C(5100), &report));
    E87_ASSERT_EQ_U32(UINT32_C(1),
                      command_occurrences(
                          &sink,
                          E87_MAINTENANCE_COMMAND_OFFICIAL_HANDOFF));
    E87_ASSERT_TRUE(sink.has_handoff[sink.count - 1U]);
    handoff = &sink.handoffs[sink.count - 1U];
    E87_ASSERT_TRUE(handoff->official_loader_verified);
    E87_ASSERT_EQ_U32(UINT32_C(0x00123456), handoff->loader_saddr);
    E87_ASSERT_EQ_U32(UINT32_C(50), handoff->battery_percent);
    E87_ASSERT_TRUE(!handoff->low_voltage_warning);
    E87_ASSERT_TRUE(handoff->board_voltage_stable);
    E87_ASSERT_TRUE(handoff->power_stable_for_required_window);
    E87_ASSERT_EQ_U32(E87_UPDATE_CHIP_AC707N, handoff->chip);
    E87_ASSERT_EQ_U32(E87_UPDATE_LAYOUT_SINGLE_BANK, handoff->layout);
    E87_ASSERT_TRUE(handoff->exact_layout_match);
    E87_ASSERT_TRUE(bytes_equal(expected_profile, handoff->profile_id,
                                sizeof(expected_profile)));
    E87_ASSERT_TRUE(e87_maintenance_get_view(&maintenance, &view));
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_STATE_HANDOFF_APPROVED, view.state);

    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_HANDOFF_COMMITTED,
                      e87_rcsp_commit_official_handoff(&maintenance));
    E87_ASSERT_TRUE(e87_maintenance_get_view(&maintenance, &view));
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_STATE_HANDED_OFF, view.state);

    cancel = event_at(E87_MAINTENANCE_EVENT_CANCEL, UINT32_C(5101));
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_NO_CHANGE,
                      e87_maintenance_step(&maintenance, &cancel));
    E87_ASSERT_EQ_U32(UINT32_C(1),
                      command_occurrences(
                          &sink,
                          E87_MAINTENANCE_COMMAND_OFFICIAL_HANDOFF));
}

E87_TEST(approved_handoff_remains_cancelable_until_official_commit)
{
    unsigned int variant;

    for (variant = 0U; variant < 4U; variant += 1U) {
        struct e87_maintenance maintenance;
        struct fake_sink sink;
        struct e87_maintenance_event event;
        struct e87_rcsp_official_loader_report report =
            valid_loader_report();
        struct e87_maintenance_view view;

        E87_ASSERT_TRUE(init_maintenance(&maintenance, &sink));
        E87_ASSERT_TRUE(enter_at(&maintenance, UINT32_C(0)));
        E87_ASSERT_TRUE(authenticate_at(&maintenance, UINT32_C(0)));
        event = power_at(UINT32_C(0), 50U, false, true, false,
                         E87_CHARGER_PHASE_CLOSE);
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_STATUS_UPDATED,
                          e87_maintenance_step(&maintenance, &event));
        event.now_ms = UINT32_C(5000);
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_STATUS_UPDATED,
                          e87_maintenance_step(&maintenance, &event));
        E87_ASSERT_EQ_U32(
            E87_MAINTENANCE_RESULT_HANDOFF_REQUESTED,
            e87_rcsp_official_loader_callback(
                &maintenance, UINT32_C(5000), &report));
        E87_ASSERT_TRUE(e87_maintenance_get_view(&maintenance, &view));
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_STATE_HANDOFF_APPROVED,
                          view.state);

        if (variant < 2U) {
            event = event_at(
                variant == 0U ? E87_MAINTENANCE_EVENT_CANCEL
                              : E87_MAINTENANCE_EVENT_FAILURE,
                UINT32_C(5001));
            E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_EXITING,
                              e87_maintenance_step(&maintenance, &event));
        } else if (variant == 2U) {
            event = event_at(E87_MAINTENANCE_EVENT_HOST_DISCONNECTED,
                             UINT32_C(5001));
            E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_ACTIVE,
                              e87_maintenance_step(&maintenance, &event));
        } else {
            event = power_at(UINT32_C(5001), 100U, true, true, true,
                             E87_CHARGER_PHASE_FULL);
            E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_STATUS_UPDATED,
                              e87_maintenance_step(&maintenance, &event));
        }
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_ERROR,
                          e87_rcsp_commit_official_handoff(&maintenance));
        E87_ASSERT_TRUE(e87_maintenance_get_view(&maintenance, &view));
        E87_ASSERT_TRUE(view.state != E87_MAINTENANCE_STATE_HANDED_OFF);
        E87_ASSERT_EQ_U32(UINT32_C(1),
                          command_occurrences(
                              &sink,
                              E87_MAINTENANCE_COMMAND_OFFICIAL_HANDOFF));
    }
}

E87_TEST(command_failure_and_reentry_fail_closed_without_handoff)
{
    size_t rejected_entry_command;

    for (rejected_entry_command = 0U; rejected_entry_command < 3U;
         rejected_entry_command += 1U) {
        struct e87_maintenance maintenance;
        struct fake_sink sink;
        struct e87_maintenance_event enter =
            event_at(E87_MAINTENANCE_EVENT_ENTER_AFTER_NORMAL_DISCONNECT,
                     UINT32_C(0));

        E87_ASSERT_TRUE(init_maintenance(&maintenance, &sink));
        sink.reject_index = rejected_entry_command;
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_ERROR,
                          e87_maintenance_step(&maintenance, &enter));
        E87_ASSERT_EQ_U32(UINT32_C(1),
                          command_occurrences(
                              &sink,
                              E87_MAINTENANCE_COMMAND_REJECT_COMMANDS));
        E87_ASSERT_EQ_U32(UINT32_C(1),
                          command_occurrences(
                              &sink,
                              E87_MAINTENANCE_COMMAND_STOP_ADVERTISING));
        E87_ASSERT_EQ_U32(UINT32_C(1),
                          command_occurrences(
                              &sink,
                              E87_MAINTENANCE_COMMAND_DISCONNECT));
        E87_ASSERT_EQ_U32(UINT32_C(0),
                          command_occurrences(
                              &sink,
                              E87_MAINTENANCE_COMMAND_OFFICIAL_HANDOFF));
        sink.reject_index = SIZE_MAX;
        E87_ASSERT_TRUE(finish_exit(&maintenance));
    }

    {
        struct e87_maintenance maintenance;
        struct fake_sink sink;
        struct e87_maintenance_event enter =
            event_at(E87_MAINTENANCE_EVENT_ENTER_AFTER_NORMAL_DISCONNECT,
                     UINT32_C(0));

        E87_ASSERT_TRUE(init_maintenance(&maintenance, &sink));
        sink.reenter = true;
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_ACTIVE,
                          e87_maintenance_step(&maintenance, &enter));
        E87_ASSERT_TRUE(sink.reentered);
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_ERROR,
                          sink.reentry_result);
        E87_ASSERT_EQ_U32(UINT32_C(3), sink.count);
    }
}

E87_TEST(every_teardown_callback_failure_is_retryable_and_order_safe)
{
    size_t ordinal;

    for (ordinal = 0U; ordinal < 3U; ordinal += 1U) {
        struct e87_maintenance maintenance;
        struct fake_sink sink;
        struct e87_maintenance_event event;

        E87_ASSERT_TRUE(init_maintenance(&maintenance, &sink));
        E87_ASSERT_TRUE(enter_at(&maintenance, UINT32_C(0)));
        sink.reject_index = sink.count + ordinal;
        event = event_at(E87_MAINTENANCE_EVENT_CANCEL, UINT32_C(1));
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_ERROR,
                          e87_maintenance_step(&maintenance, &event));
        E87_ASSERT_EQ_U32(UINT32_C(6), sink.count);
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_REJECT_COMMANDS,
                          sink.commands[3]);
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_STOP_ADVERTISING,
                          sink.commands[4]);
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_DISCONNECT,
                          sink.commands[5]);
        sink.reject_index = SIZE_MAX;
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_EXITING,
                          e87_maintenance_step(&maintenance, &event));
        E87_ASSERT_TRUE(finish_exit(&maintenance));
    }

    {
        struct e87_maintenance maintenance;
        struct fake_sink sink;
        struct e87_maintenance_event event;

        E87_ASSERT_TRUE(init_maintenance(&maintenance, &sink));
        E87_ASSERT_TRUE(enter_at(&maintenance, UINT32_C(0)));
        event = event_at(E87_MAINTENANCE_EVENT_CANCEL, UINT32_C(1));
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_EXITING,
                          e87_maintenance_step(&maintenance, &event));
        sink.reject_index = sink.count;
        event = event_at(E87_MAINTENANCE_EVENT_TRANSPORT_QUIESCED,
                         UINT32_C(2));
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_ERROR,
                          e87_maintenance_step(&maintenance, &event));
        sink.reject_index = SIZE_MAX;
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_WAITING_FOR_RCSP_RELEASE,
                          e87_maintenance_step(&maintenance, &event));
        event = event_at(E87_MAINTENANCE_EVENT_RCSP_RELEASE_STATUS,
                         UINT32_C(3));
        event.rcsp_handle_present = false;
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_NORMAL_REQUESTED,
                          e87_maintenance_step(&maintenance, &event));
    }

    for (ordinal = 0U; ordinal < 2U; ordinal += 1U) {
        struct e87_maintenance maintenance;
        struct fake_sink sink;
        struct e87_maintenance_event event;

        E87_ASSERT_TRUE(init_maintenance(&maintenance, &sink));
        E87_ASSERT_TRUE(enter_at(&maintenance, UINT32_C(0)));
        event = event_at(E87_MAINTENANCE_EVENT_CANCEL, UINT32_C(1));
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_EXITING,
                          e87_maintenance_step(&maintenance, &event));
        event = event_at(E87_MAINTENANCE_EVENT_TRANSPORT_QUIESCED,
                         UINT32_C(2));
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_WAITING_FOR_RCSP_RELEASE,
                          e87_maintenance_step(&maintenance, &event));
        sink.reject_index = sink.count + ordinal;
        event = event_at(E87_MAINTENANCE_EVENT_RCSP_RELEASE_STATUS,
                         UINT32_C(3));
        event.rcsp_handle_present = false;
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_ERROR,
                          e87_maintenance_step(&maintenance, &event));
        sink.reject_index = SIZE_MAX;
        E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_NORMAL_REQUESTED,
                          e87_maintenance_step(&maintenance, &event));
        E87_ASSERT_EQ_U32(ordinal == 0U ? UINT32_C(2)
                                        : UINT32_C(1),
                          command_occurrences(
                              &sink,
                              E87_MAINTENANCE_COMMAND_RCSP_INTERFACE_EXIT));
    }
}

enum fake_target_call {
    TARGET_CALL_INTERFACE_INIT = 0,
    TARGET_CALL_RCSP_INIT = 1,
    TARGET_CALL_BLE_INIT = 2,
    TARGET_CALL_REJECT = 3,
    TARGET_CALL_STOP_ADV = 4,
    TARGET_CALL_DISCONNECT = 5,
    TARGET_CALL_BLE_EXIT = 6,
    TARGET_CALL_INTERFACE_EXIT = 7,
    TARGET_CALL_NORMAL = 8,
    TARGET_CALL_HANDOFF = 9
};

struct fake_target {
    enum fake_target_call calls[TARGET_CALL_CAPACITY];
    size_t count;
    const uint8_t *profile;
    const char *local_name;
    uint32_t loader_saddr;
    void *rcsp_handle;
};

static bool target_record(struct fake_target *target,
                          enum fake_target_call call)
{
    if (target->count >= TARGET_CALL_CAPACITY) {
        return false;
    }
    target->calls[target->count] = call;
    target->count += 1U;
    return true;
}

static bool target_interface_init(void *context,
                                  const uint8_t *profile,
                                  const char *local_name)
{
    struct fake_target *target = (struct fake_target *)context;

    target->profile = profile;
    target->local_name = local_name;
    return target_record(target, TARGET_CALL_INTERFACE_INIT);
}

static bool target_rcsp_init(void *context)
{
    return target_record((struct fake_target *)context,
                         TARGET_CALL_RCSP_INIT);
}

static bool target_ble_init(void *context)
{
    return target_record((struct fake_target *)context,
                         TARGET_CALL_BLE_INIT);
}

static bool target_reject(void *context)
{
    return target_record((struct fake_target *)context,
                         TARGET_CALL_REJECT);
}

static bool target_stop_adv(void *context)
{
    return target_record((struct fake_target *)context,
                         TARGET_CALL_STOP_ADV);
}

static bool target_disconnect(void *context)
{
    return target_record((struct fake_target *)context,
                         TARGET_CALL_DISCONNECT);
}

static bool target_ble_exit(void *context)
{
    return target_record((struct fake_target *)context,
                         TARGET_CALL_BLE_EXIT);
}

static void *target_rcsp_handle_get(void *context)
{
    const struct fake_target *target = (const struct fake_target *)context;

    return target->rcsp_handle;
}

static bool target_interface_exit(void *context)
{
    return target_record((struct fake_target *)context,
                         TARGET_CALL_INTERFACE_EXIT);
}

static bool target_normal(void *context)
{
    return target_record((struct fake_target *)context,
                         TARGET_CALL_NORMAL);
}

static bool target_handoff(void *context, uint32_t loader_saddr)
{
    struct fake_target *target = (struct fake_target *)context;

    target->loader_saddr = loader_saddr;
    return target_record(target, TARGET_CALL_HANDOFF);
}

static struct e87_rcsp_target_api target_api(struct fake_target *target)
{
    const struct e87_rcsp_target_api api = {
        target,
        target_interface_init,
        target_rcsp_init,
        target_ble_init,
        target_reject,
        target_stop_adv,
        target_disconnect,
        target_ble_exit,
        target_rcsp_handle_get,
        target_interface_exit,
        target_normal,
        target_handoff
    };

    return api;
}

static void remove_target_binding(struct e87_rcsp_target_api *api,
                                  size_t binding)
{
    switch (binding) {
    case 0U:
        api->bt_rcsp_interface_init = NULL;
        break;
    case 1U:
        api->rcsp_init = NULL;
        break;
    case 2U:
        api->rcsp_bt_ble_init = NULL;
        break;
    case 3U:
        api->reject_commands = NULL;
        break;
    case 4U:
        api->stop_advertising = NULL;
        break;
    case 5U:
        api->disconnect = NULL;
        break;
    case 6U:
        api->rcsp_bt_ble_exit = NULL;
        break;
    case 7U:
        api->rcsp_handle_get = NULL;
        break;
    case 8U:
        api->bt_rcsp_interface_exit = NULL;
        break;
    case 9U:
        api->request_normal_mode = NULL;
        break;
    default:
        api->approve_official_update_start = NULL;
        break;
    }
}

E87_TEST(target_adapter_maps_lifecycle_and_supplies_only_minimal_profile)
{
    struct e87_rcsp_target_adapter adapter;
    struct e87_rcsp_target_api api;
    struct e87_maintenance maintenance;
    struct e87_maintenance_event event;
    struct fake_target target = {0};

    api = target_api(&target);
    E87_ASSERT_TRUE(!e87_rcsp_target_maintenance_init(
        NULL, &api, &maintenance));
    E87_ASSERT_TRUE(!e87_rcsp_target_maintenance_init(
        &adapter, NULL, &maintenance));
    E87_ASSERT_TRUE(!e87_rcsp_target_maintenance_init(
        &adapter, &api, NULL));
    E87_ASSERT_TRUE(e87_rcsp_target_maintenance_init(
        &adapter, &api, &maintenance));
    E87_ASSERT_TRUE(enter_at(&maintenance, UINT32_C(0)));
    E87_ASSERT_EQ_U32(UINT32_C(3), target.count);
    E87_ASSERT_EQ_U32(TARGET_CALL_INTERFACE_INIT, target.calls[0]);
    E87_ASSERT_EQ_U32(TARGET_CALL_RCSP_INIT, target.calls[1]);
    E87_ASSERT_EQ_U32(TARGET_CALL_BLE_INIT, target.calls[2]);
    E87_ASSERT_TRUE(target.profile == e87_rcsp_profile);
    E87_ASSERT_TRUE(target.local_name == e87_rcsp_local_name);
    E87_ASSERT_TRUE(strcmp(target.local_name, "E87 UPDATE") == 0);

    event = event_at(E87_MAINTENANCE_EVENT_CANCEL, UINT32_C(1));
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_EXITING,
                      e87_maintenance_step(&maintenance, &event));
    E87_ASSERT_EQ_U32(TARGET_CALL_REJECT, target.calls[3]);
    E87_ASSERT_EQ_U32(TARGET_CALL_STOP_ADV, target.calls[4]);
    E87_ASSERT_EQ_U32(TARGET_CALL_DISCONNECT, target.calls[5]);
    event = event_at(E87_MAINTENANCE_EVENT_TRANSPORT_QUIESCED,
                     UINT32_C(2));
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_WAITING_FOR_RCSP_RELEASE,
                      e87_maintenance_step(&maintenance, &event));
    E87_ASSERT_EQ_U32(TARGET_CALL_BLE_EXIT, target.calls[6]);
    target.rcsp_handle = &target;
    E87_ASSERT_EQ_U32(
        E87_MAINTENANCE_RESULT_WAITING_FOR_RCSP_RELEASE,
        e87_rcsp_target_poll_release(
            &adapter, &maintenance, UINT32_C(5001)));
    E87_ASSERT_EQ_U32(UINT32_C(7), target.count);
    target.rcsp_handle = NULL;
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_NORMAL_REQUESTED,
                      e87_rcsp_target_poll_release(
                          &adapter, &maintenance, UINT32_C(5002)));
    E87_ASSERT_EQ_U32(TARGET_CALL_INTERFACE_EXIT, target.calls[7]);
    E87_ASSERT_EQ_U32(TARGET_CALL_NORMAL, target.calls[8]);
}

E87_TEST(target_adapter_revalidates_internal_attestation_fail_closed)
{
    struct e87_rcsp_target_adapter adapter;
    struct e87_rcsp_target_api api;
    struct e87_maintenance maintenance;
    struct e87_maintenance_event sample;
    struct e87_maintenance_view view;
    struct fake_target target = {0};
    struct e87_rcsp_official_loader_report report = valid_loader_report();

    api = target_api(&target);
    E87_ASSERT_TRUE(e87_rcsp_target_maintenance_init(
        &adapter, &api, &maintenance));
    E87_ASSERT_TRUE(enter_at(&maintenance, UINT32_C(0)));
    E87_ASSERT_TRUE(authenticate_at(&maintenance, UINT32_C(0)));
    sample = power_at(UINT32_C(0), 50U, false, true, false,
                      E87_CHARGER_PHASE_CLOSE);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_STATUS_UPDATED,
                      e87_maintenance_step(&maintenance, &sample));
    sample.now_ms = UINT32_C(5000);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_STATUS_UPDATED,
                      e87_maintenance_step(&maintenance, &sample));

    maintenance.private_power.percent = UINT8_C(101);
    E87_ASSERT_EQ_U32(
        E87_MAINTENANCE_RESULT_ERROR,
        e87_rcsp_official_loader_callback(
            &maintenance, UINT32_C(5000), &report));
    E87_ASSERT_TRUE(e87_maintenance_get_view(&maintenance, &view));
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_STATE_EXITING, view.state);
    E87_ASSERT_EQ_U32(UINT32_C(0), target.loader_saddr);
    E87_ASSERT_EQ_U32(UINT32_C(6), target.count);
    E87_ASSERT_EQ_U32(TARGET_CALL_REJECT, target.calls[3]);
    E87_ASSERT_EQ_U32(TARGET_CALL_STOP_ADV, target.calls[4]);
    E87_ASSERT_EQ_U32(TARGET_CALL_DISCONNECT, target.calls[5]);
}

E87_TEST(target_init_rejects_every_missing_binding_without_side_effects)
{
    size_t binding;

    for (binding = 0U; binding < 11U; binding += 1U) {
        struct e87_rcsp_target_adapter adapter;
        struct e87_rcsp_target_adapter adapter_before;
        struct e87_maintenance maintenance;
        struct e87_maintenance maintenance_before;
        struct fake_target target = {0};
        struct e87_rcsp_target_api api = target_api(&target);

        memset(&adapter, 0xa5, sizeof(adapter));
        memset(&maintenance, 0x5a, sizeof(maintenance));
        adapter_before = adapter;
        maintenance_before = maintenance;
        remove_target_binding(&api, binding);
        E87_ASSERT_TRUE(!e87_rcsp_target_maintenance_init(
            &adapter, &api, &maintenance));
        E87_ASSERT_TRUE(bytes_equal(
            &adapter, &adapter_before, sizeof(adapter)));
        E87_ASSERT_TRUE(bytes_equal(
            &maintenance, &maintenance_before, sizeof(maintenance)));
        E87_ASSERT_EQ_U32(UINT32_C(0), target.count);
    }
}

E87_TEST(invalid_events_and_power_samples_do_not_mutate_or_emit)
{
    struct e87_maintenance maintenance;
    struct e87_maintenance before;
    struct fake_sink sink;
    struct e87_maintenance_event event;

    E87_ASSERT_TRUE(init_maintenance(&maintenance, &sink));
    E87_ASSERT_TRUE(enter_at(&maintenance, UINT32_C(0)));
    before = maintenance;
    event = event_at((enum e87_maintenance_event_type)UINT8_MAX,
                     UINT32_C(1));
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_ERROR,
                      e87_maintenance_step(&maintenance, &event));
    E87_ASSERT_TRUE(bytes_equal(&maintenance, &before, sizeof(maintenance)));
    event = power_at(UINT32_C(1), 101U, false, true, false,
                     E87_CHARGER_PHASE_UNKNOWN);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_ERROR,
                      e87_maintenance_step(&maintenance, &event));
    E87_ASSERT_TRUE(bytes_equal(&maintenance, &before, sizeof(maintenance)));
    event = power_at(UINT32_C(1), 50U, false, true, false,
                     (enum e87_charger_phase)UINT8_MAX);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_RESULT_ERROR,
                      e87_maintenance_step(&maintenance, &event));
    E87_ASSERT_TRUE(bytes_equal(&maintenance, &before, sizeof(maintenance)));
    E87_ASSERT_EQ_U32(UINT32_C(3), sink.count);
}

static const struct e87_test_case maintenance_cases[] = {
    E87_TEST_CASE(init_is_side_effect_free_and_entry_uses_exact_rcsp_order),
    E87_TEST_CASE(unauthenticated_timeout_has_exact_boundary_and_orderly_exit),
    E87_TEST_CASE(rcsp_interface_exit_waits_for_null_handle_and_times_out_fail_safe),
    E87_TEST_CASE(authentication_cancels_timeout_and_disconnect_restarts_it),
    E87_TEST_CASE(cancel_and_failure_abort_every_pre_handoff_phase),
    E87_TEST_CASE(charging_never_bypasses_49_percent_and_50_is_inclusive),
    E87_TEST_CASE(low_voltage_or_unstable_voltage_resets_five_second_window),
    E87_TEST_CASE(power_window_handles_wrap_and_restarts_on_backward_sample),
    E87_TEST_CASE(official_callback_rejects_every_loader_identity_mismatch),
    E87_TEST_CASE(valid_official_callback_approves_then_commits_at_official_boundary),
    E87_TEST_CASE(approved_handoff_remains_cancelable_until_official_commit),
    E87_TEST_CASE(command_failure_and_reentry_fail_closed_without_handoff),
    E87_TEST_CASE(every_teardown_callback_failure_is_retryable_and_order_safe),
    E87_TEST_CASE(target_adapter_maps_lifecycle_and_supplies_only_minimal_profile),
    E87_TEST_CASE(target_adapter_revalidates_internal_attestation_fail_closed),
    E87_TEST_CASE(target_init_rejects_every_missing_binding_without_side_effects),
    E87_TEST_CASE(invalid_events_and_power_samples_do_not_mutate_or_emit)
};

const struct e87_test_suite e87_test_suite = {
    "rcsp-maintenance",
    maintenance_cases,
    sizeof(maintenance_cases) / sizeof(maintenance_cases[0])
};
