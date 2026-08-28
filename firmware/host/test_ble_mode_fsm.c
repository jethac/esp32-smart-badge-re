#include "test_support.h"
#include "e87/e87_ble_mode_fsm.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

static int normal_handle_cookie;
static int maintenance_handle_cookie;

struct fake_adapter {
    char log[32];
    size_t length;
    enum e87_ble_mode initialized;
    bool return_null_handle;
    bool complete_disconnect_synchronously;
    bool connect_on_advertising_disable;
    bool connect_on_advertising_enable;
    bool connect_during_release;
    bool reject_disconnect;
    bool reject_advertising_enable;
    bool disconnect_completion_accepted;
    bool connection_accepted;
    struct e87_ble_mode_fsm *fsm;
};

static void append(struct fake_adapter *fake, char action)
{
    if (fake->length < sizeof(fake->log)) {
        fake->log[fake->length++] = action;
    }
}

static bool advertising(void *context, enum e87_ble_mode mode, bool enabled)
{
    struct fake_adapter *fake = (struct fake_adapter *)context;

    append(fake, enabled ? 'a' : 'A');
    if ((!enabled && fake->connect_on_advertising_disable) ||
        (enabled && fake->connect_on_advertising_enable)) {
        const void *handle =
            mode == E87_BLE_MODE_NORMAL
                ? (const void *)&normal_handle_cookie
                : (const void *)&maintenance_handle_cookie;

        fake->connection_accepted = e87_ble_mode_set_connection(
            fake->fsm, handle, UINT16_C(0x55));
    }
    return !(enabled && fake->reject_advertising_enable);
}

static void writes(void *context, bool enabled)
{
    append((struct fake_adapter *)context, enabled ? 'w' : 'W');
}

static bool disconnect(void *context, enum e87_ble_mode mode,
                       const void *app_handle, uint16_t connection_handle)
{
    struct fake_adapter *fake = (struct fake_adapter *)context;

    (void)mode;
    append(fake, 'D');
    if (fake->complete_disconnect_synchronously) {
        fake->disconnect_completion_accepted =
            e87_ble_mode_on_disconnect_complete(
                fake->fsm, app_handle, connection_handle);
    }
    return !fake->reject_disconnect;
}

static bool release(void *context, enum e87_ble_mode mode,
                    const void *app_handle)
{
    struct fake_adapter *fake = (struct fake_adapter *)context;

    append(fake, 'R');
    if (fake->connect_during_release) {
        fake->connection_accepted = e87_ble_mode_set_connection(
            fake->fsm, app_handle, UINT16_C(0x58));
        if (fake->connection_accepted) {
            return false;
        }
    }
    (void)mode;
    return true;
}

static bool initialize(void *context, enum e87_ble_mode mode,
                       const void **out_handle)
{
    struct fake_adapter *fake = (struct fake_adapter *)context;

    append(fake, 'I');
    fake->initialized = mode;
    *out_handle = fake->return_null_handle
                      ? NULL
                      : (mode == E87_BLE_MODE_NORMAL
                             ? (const void *)&normal_handle_cookie
                             : (const void *)&maintenance_handle_cookie);
    return true;
}

static struct e87_ble_mode_ops fake_ops(struct fake_adapter *fake)
{
    const struct e87_ble_mode_ops ops = {
        fake, advertising, writes, disconnect, release, initialize,
    };

    return ops;
}

static bool log_is(const struct fake_adapter *fake, const char *expected)
{
    const size_t length = strlen(expected);

    return fake->length == length &&
           memcmp(fake->log, expected, length) == 0;
}

E87_TEST(connected_switch_waits_then_installs_handle_writes_and_advertising)
{
    struct fake_adapter fake;
    struct e87_ble_mode_fsm fsm;
    struct e87_ble_mode_ops ops;

    memset(&fake, 0, sizeof(fake));
    ops = fake_ops(&fake);
    E87_ASSERT_TRUE(e87_ble_mode_init(
        &fsm, E87_BLE_MODE_NORMAL, &normal_handle_cookie, &ops));
    E87_ASSERT_TRUE(e87_ble_mode_set_connection(
        &fsm, &normal_handle_cookie, UINT16_C(0x44)));
    E87_ASSERT_TRUE(e87_ble_mode_request(
        &fsm, E87_BLE_MODE_MAINTENANCE));

    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED, e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED, e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_WAITING, e87_ble_mode_step(&fsm));
    E87_ASSERT_TRUE(log_is(&fake, "WAD"));
    E87_ASSERT_TRUE(!e87_ble_mode_on_disconnect_complete(
        &fsm, &maintenance_handle_cookie, UINT16_C(0x44)));
    E87_ASSERT_TRUE(!e87_ble_mode_on_disconnect_complete(
        &fsm, &normal_handle_cookie, UINT16_C(0x45)));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_WAITING, e87_ble_mode_step(&fsm));
    E87_ASSERT_TRUE(log_is(&fake, "WAD"));

    E87_ASSERT_TRUE(e87_ble_mode_on_disconnect_complete(
        &fsm, &normal_handle_cookie, UINT16_C(0x44)));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED, e87_ble_mode_step(&fsm));
    E87_ASSERT_TRUE(log_is(&fake, "WADR"));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED, e87_ble_mode_step(&fsm));
    E87_ASSERT_TRUE(log_is(&fake, "WADRI"));
    E87_ASSERT_TRUE(!e87_ble_mode_set_connection(
        &fsm, &maintenance_handle_cookie, UINT16_C(7)));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED, e87_ble_mode_step(&fsm));
    E87_ASSERT_TRUE(log_is(&fake, "WADRIW"));
    E87_ASSERT_TRUE(!e87_ble_mode_set_connection(
        &fsm, &maintenance_handle_cookie, UINT16_C(7)));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_COMPLETE, e87_ble_mode_step(&fsm));
    E87_ASSERT_TRUE(log_is(&fake, "WADRIWa"));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_MAINTENANCE, e87_ble_mode_current(&fsm));
    E87_ASSERT_TRUE(!e87_ble_mode_set_connection(
        &fsm, &normal_handle_cookie, UINT16_C(7)));
    E87_ASSERT_TRUE(e87_ble_mode_set_connection(
        &fsm, &maintenance_handle_cookie, UINT16_C(7)));
}

E87_TEST(disconnected_reverse_switch_reenables_normal_writes_before_advertising)
{
    struct fake_adapter fake;
    struct e87_ble_mode_fsm fsm;
    struct e87_ble_mode_ops ops;

    memset(&fake, 0, sizeof(fake));
    ops = fake_ops(&fake);
    E87_ASSERT_TRUE(e87_ble_mode_init(
        &fsm, E87_BLE_MODE_MAINTENANCE,
        &maintenance_handle_cookie, &ops));
    E87_ASSERT_TRUE(e87_ble_mode_request(&fsm, E87_BLE_MODE_NORMAL));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED, e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED, e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED, e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED, e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED, e87_ble_mode_step(&fsm));
    E87_ASSERT_TRUE(log_is(&fake, "WARIw"));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_COMPLETE, e87_ble_mode_step(&fsm));
    E87_ASSERT_TRUE(log_is(&fake, "WARIwa"));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_NORMAL, e87_ble_mode_current(&fsm));
}

E87_TEST(null_initialized_handle_fails_closed_before_writes_or_advertising)
{
    struct fake_adapter fake;
    struct e87_ble_mode_fsm fsm;
    struct e87_ble_mode_ops ops;

    memset(&fake, 0, sizeof(fake));
    fake.return_null_handle = true;
    ops = fake_ops(&fake);
    E87_ASSERT_TRUE(e87_ble_mode_init(
        &fsm, E87_BLE_MODE_NORMAL, &normal_handle_cookie, &ops));
    E87_ASSERT_TRUE(e87_ble_mode_request(
        &fsm, E87_BLE_MODE_MAINTENANCE));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED, e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED, e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED, e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_FAILED, e87_ble_mode_step(&fsm));
    E87_ASSERT_TRUE(log_is(&fake, "WARI"));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_PHASE_INITIALIZE_TARGET,
                      e87_ble_mode_phase(&fsm));
}

E87_TEST(rejected_mode_requests_have_no_additional_side_effects)
{
    struct fake_adapter fake;
    struct e87_ble_mode_fsm fsm;
    struct e87_ble_mode_ops ops;

    memset(&fake, 0, sizeof(fake));
    ops = fake_ops(&fake);
    E87_ASSERT_TRUE(e87_ble_mode_init(
        &fsm, E87_BLE_MODE_NORMAL, &normal_handle_cookie, &ops));
    E87_ASSERT_TRUE(!e87_ble_mode_request(&fsm, E87_BLE_MODE_NORMAL));
    E87_ASSERT_TRUE(e87_ble_mode_request(
        &fsm, E87_BLE_MODE_MAINTENANCE));
    E87_ASSERT_TRUE(log_is(&fake, "W"));
    E87_ASSERT_TRUE(!e87_ble_mode_request(&fsm, E87_BLE_MODE_NORMAL));
    E87_ASSERT_TRUE(log_is(&fake, "W"));
}

E87_TEST(synchronous_disconnect_completion_is_preserved_and_rejection_retries)
{
    struct fake_adapter fake;
    struct e87_ble_mode_fsm fsm;
    struct e87_ble_mode_ops ops;

    memset(&fake, 0, sizeof(fake));
    fake.fsm = &fsm;
    fake.complete_disconnect_synchronously = true;
    ops = fake_ops(&fake);
    E87_ASSERT_TRUE(e87_ble_mode_init(
        &fsm, E87_BLE_MODE_NORMAL, &normal_handle_cookie, &ops));
    E87_ASSERT_TRUE(e87_ble_mode_set_connection(
        &fsm, &normal_handle_cookie, UINT16_C(0x44)));
    E87_ASSERT_TRUE(e87_ble_mode_request(
        &fsm, E87_BLE_MODE_MAINTENANCE));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_TRUE(fake.disconnect_completion_accepted);
    E87_ASSERT_EQ_U32(E87_BLE_MODE_PHASE_RELEASE_PROFILE,
                      e87_ble_mode_phase(&fsm));

    memset(&fake, 0, sizeof(fake));
    fake.fsm = &fsm;
    fake.reject_disconnect = true;
    ops = fake_ops(&fake);
    E87_ASSERT_TRUE(e87_ble_mode_init(
        &fsm, E87_BLE_MODE_NORMAL, &normal_handle_cookie, &ops));
    E87_ASSERT_TRUE(e87_ble_mode_set_connection(
        &fsm, &normal_handle_cookie, UINT16_C(0x44)));
    E87_ASSERT_TRUE(e87_ble_mode_request(
        &fsm, E87_BLE_MODE_MAINTENANCE));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_FAILED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_PHASE_REQUEST_DISCONNECT,
                      e87_ble_mode_phase(&fsm));
}

E87_TEST(synchronous_connection_on_advertising_enable_is_accepted)
{
    struct fake_adapter fake;
    struct e87_ble_mode_fsm fsm;
    struct e87_ble_mode_ops ops;

    memset(&fake, 0, sizeof(fake));
    fake.fsm = &fsm;
    fake.connect_on_advertising_enable = true;
    ops = fake_ops(&fake);
    E87_ASSERT_TRUE(e87_ble_mode_init(
        &fsm, E87_BLE_MODE_NORMAL, &normal_handle_cookie, &ops));
    E87_ASSERT_TRUE(e87_ble_mode_request(
        &fsm, E87_BLE_MODE_MAINTENANCE));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_COMPLETE,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_TRUE(fake.connection_accepted);

    E87_ASSERT_TRUE(e87_ble_mode_request(&fsm, E87_BLE_MODE_NORMAL));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_WAITING,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_TRUE(log_is(&fake, "WARIWaWAD"));
}

E87_TEST(connection_during_advertising_disable_is_drained_before_release)
{
    struct fake_adapter fake;
    struct e87_ble_mode_fsm fsm;
    struct e87_ble_mode_ops ops;

    memset(&fake, 0, sizeof(fake));
    fake.fsm = &fsm;
    fake.connect_on_advertising_disable = true;
    ops = fake_ops(&fake);
    E87_ASSERT_TRUE(e87_ble_mode_init(
        &fsm, E87_BLE_MODE_NORMAL, &normal_handle_cookie, &ops));
    E87_ASSERT_TRUE(e87_ble_mode_request(
        &fsm, E87_BLE_MODE_MAINTENANCE));
    E87_ASSERT_TRUE(log_is(&fake, "W"));

    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_TRUE(fake.connection_accepted);
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_WAITING,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_TRUE(log_is(&fake, "WAD"));

    E87_ASSERT_TRUE(e87_ble_mode_on_disconnect_complete(
        &fsm, &normal_handle_cookie, UINT16_C(0x55)));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_TRUE(log_is(&fake, "WADR"));
}

E87_TEST(connection_after_write_rejection_is_drained_before_release)
{
    struct fake_adapter fake;
    struct e87_ble_mode_fsm fsm;
    struct e87_ble_mode_ops ops;

    memset(&fake, 0, sizeof(fake));
    ops = fake_ops(&fake);
    E87_ASSERT_TRUE(e87_ble_mode_init(
        &fsm, E87_BLE_MODE_NORMAL, &normal_handle_cookie, &ops));
    E87_ASSERT_TRUE(e87_ble_mode_request(
        &fsm, E87_BLE_MODE_MAINTENANCE));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));

    E87_ASSERT_TRUE(!e87_ble_mode_set_connection(
        &fsm, &maintenance_handle_cookie, UINT16_C(0x56)));
    E87_ASSERT_TRUE(e87_ble_mode_set_connection(
        &fsm, &normal_handle_cookie, UINT16_C(0x56)));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_WAITING,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_TRUE(log_is(&fake, "WAD"));
}

E87_TEST(connection_before_profile_release_rewinds_to_disconnect)
{
    struct fake_adapter fake;
    struct e87_ble_mode_fsm fsm;
    struct e87_ble_mode_ops ops;

    memset(&fake, 0, sizeof(fake));
    ops = fake_ops(&fake);
    E87_ASSERT_TRUE(e87_ble_mode_init(
        &fsm, E87_BLE_MODE_NORMAL, &normal_handle_cookie, &ops));
    E87_ASSERT_TRUE(e87_ble_mode_set_connection(
        &fsm, &normal_handle_cookie, UINT16_C(0x44)));
    E87_ASSERT_TRUE(e87_ble_mode_request(
        &fsm, E87_BLE_MODE_MAINTENANCE));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_WAITING,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_TRUE(e87_ble_mode_on_disconnect_complete(
        &fsm, &normal_handle_cookie, UINT16_C(0x44)));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_PHASE_RELEASE_PROFILE,
                      e87_ble_mode_phase(&fsm));

    E87_ASSERT_TRUE(!e87_ble_mode_set_connection(
        &fsm, &maintenance_handle_cookie, UINT16_C(0x57)));
    E87_ASSERT_TRUE(e87_ble_mode_set_connection(
        &fsm, &normal_handle_cookie, UINT16_C(0x57)));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_PHASE_REQUEST_DISCONNECT,
                      e87_ble_mode_phase(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_WAITING,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_TRUE(log_is(&fake, "WADD"));
}

E87_TEST(connection_during_profile_release_is_admitted_and_drained)
{
    struct fake_adapter fake;
    struct e87_ble_mode_fsm fsm;
    struct e87_ble_mode_ops ops;

    memset(&fake, 0, sizeof(fake));
    fake.fsm = &fsm;
    fake.connect_during_release = true;
    ops = fake_ops(&fake);
    E87_ASSERT_TRUE(e87_ble_mode_init(
        &fsm, E87_BLE_MODE_NORMAL, &normal_handle_cookie, &ops));
    E87_ASSERT_TRUE(e87_ble_mode_request(
        &fsm, E87_BLE_MODE_MAINTENANCE));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_TRUE(fake.connection_accepted);
    E87_ASSERT_TRUE(log_is(&fake, "WAR"));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_PHASE_REQUEST_DISCONNECT,
                      e87_ble_mode_phase(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_WAITING,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_TRUE(log_is(&fake, "WARD"));
    E87_ASSERT_TRUE(e87_ble_mode_on_disconnect_complete(
        &fsm, &normal_handle_cookie, UINT16_C(0x58)));
    fake.connect_during_release = false;
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_TRUE(log_is(&fake, "WARDR"));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_PHASE_INITIALIZE_TARGET,
                      e87_ble_mode_phase(&fsm));
}

E87_TEST(advertising_enable_rejection_restores_retryable_phase)
{
    struct fake_adapter fake;
    struct e87_ble_mode_fsm fsm;
    struct e87_ble_mode_ops ops;

    memset(&fake, 0, sizeof(fake));
    fake.fsm = &fsm;
    fake.reject_advertising_enable = true;
    ops = fake_ops(&fake);
    E87_ASSERT_TRUE(e87_ble_mode_init(
        &fsm, E87_BLE_MODE_NORMAL, &normal_handle_cookie, &ops));
    E87_ASSERT_TRUE(e87_ble_mode_request(
        &fsm, E87_BLE_MODE_MAINTENANCE));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_PROGRESSED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_FAILED,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_EQ_U32(E87_BLE_MODE_PHASE_ENABLE_TARGET_ADVERTISING,
                      e87_ble_mode_phase(&fsm));

    fake.reject_advertising_enable = false;
    E87_ASSERT_EQ_U32(E87_BLE_MODE_STEP_COMPLETE,
                      e87_ble_mode_step(&fsm));
    E87_ASSERT_TRUE(log_is(&fake, "WARIWaa"));
}

static const struct e87_test_case cases[] = {
    E87_TEST_CASE(connected_switch_waits_then_installs_handle_writes_and_advertising),
    E87_TEST_CASE(disconnected_reverse_switch_reenables_normal_writes_before_advertising),
    E87_TEST_CASE(null_initialized_handle_fails_closed_before_writes_or_advertising),
    E87_TEST_CASE(rejected_mode_requests_have_no_additional_side_effects),
    E87_TEST_CASE(synchronous_disconnect_completion_is_preserved_and_rejection_retries),
    E87_TEST_CASE(synchronous_connection_on_advertising_enable_is_accepted),
    E87_TEST_CASE(connection_during_advertising_disable_is_drained_before_release),
    E87_TEST_CASE(connection_after_write_rejection_is_drained_before_release),
    E87_TEST_CASE(connection_before_profile_release_rewinds_to_disconnect),
    E87_TEST_CASE(connection_during_profile_release_is_admitted_and_drained),
    E87_TEST_CASE(advertising_enable_rejection_restores_retryable_phase),
};

const struct e87_test_suite e87_test_suite = {
    "ble-mode-fsm", cases, sizeof(cases) / sizeof(cases[0]),
};
