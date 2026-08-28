#include "test_support.h"
#include "e87/e87_ble_control.h"
#include "e87/e87_bond_policy.h"
#include "e87/e87_build_info.h"
#include "e87/e87_state.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

static int normal_handle_cookie;
static const struct e87_ble_peer owner_peer = {
    UINT8_C(0), {UINT8_C(1), UINT8_C(2), UINT8_C(3),
                 UINT8_C(4), UINT8_C(5), UINT8_C(6)}
};
static const struct e87_ble_peer candidate_peer = {
    UINT8_C(1), {UINT8_C(6), UINT8_C(5), UINT8_C(4),
                 UINT8_C(3), UINT8_C(2), UINT8_C(1)}
};
struct fixture {
    struct e87_state_store store;
    struct e87_ble_control control;
    uint32_t redraws;
    e87_state_lock_token_t token;
    uint32_t notifications;
    const void *notified_app_handle;
    uint16_t notified_connection_handle;
    uint16_t notified_attribute_handle;
    uint8_t notified_percent;
};

static e87_state_lock_token_t lock_enter(void *context)
{
    struct fixture *fixture = (struct fixture *)context;

    fixture->token += (e87_state_lock_token_t)1U;
    return fixture->token;
}

static void lock_leave(void *context, e87_state_lock_token_t token)
{
    struct fixture *fixture = (struct fixture *)context;

    (void)fixture;
    (void)token;
}

static void state_changed(void *context,
                          const struct e87_state_snapshot *snapshot)
{
    struct fixture *fixture = (struct fixture *)context;

    (void)snapshot;
    fixture->redraws += UINT32_C(1);
}

static void battery_notification(void *context,
                                 const void *app_handle,
                                 uint16_t connection_handle,
                                 uint16_t attribute_handle,
                                 uint8_t percent)
{
    struct fixture *fixture = (struct fixture *)context;

    fixture->notifications += UINT32_C(1);
    fixture->notified_app_handle = app_handle;
    fixture->notified_connection_handle = connection_handle;
    fixture->notified_attribute_handle = attribute_handle;
    fixture->notified_percent = percent;
}

static bool fixture_init(struct fixture *fixture)
{
    struct e87_state_sync sync;
    struct e87_build_identity identity;
    struct e87_ble_control_observer observer;
    size_t index;

    memset(fixture, 0, sizeof(*fixture));
    sync.context = fixture;
    sync.enter = lock_enter;
    sync.leave = lock_leave;
    if (!e87_state_store_init(&fixture->store, &sync)) {
        return false;
    }
    memset(&identity, 0, sizeof(identity));
    identity.semver_major = UINT8_C(1);
    identity.semver_minor = UINT8_C(2);
    identity.semver_patch = UINT8_C(3);
    for (index = 0U; index < sizeof(identity.build_id); index += 1U) {
        identity.build_id[index] = (uint8_t)(index + 1U);
    }
    observer.context = fixture;
    observer.state_changed = state_changed;
    observer.battery_notification = battery_notification;
    return e87_ble_control_init(&fixture->control, &normal_handle_cookie,
                                &fixture->store, &identity, &observer);
}

static void establish_gate(struct fixture *fixture,
                           uint16_t connection_handle)
{
    uint8_t build[E87_BUILD_INFO_SIZE];

    (void)e87_ble_control_on_encryption_changed(
        &fixture->control, &normal_handle_cookie, connection_handle, true);
    (void)e87_ble_control_att_read(
        &fixture->control, &normal_handle_cookie, connection_handle,
        E87_ATT_HANDLE_BUILD_VALUE, 0U, build, sizeof(build));
}

static const uint8_t valid_state[E87_STATE_PACKET_SIZE] = {
    UINT8_C(1), UINT8_C(64), UINT8_C(21), UINT8_C(0),
    UINT8_C(0xBF), UINT8_C(0x06), UINT8_C(0), UINT8_C(0),
};

E87_TEST(build_read_requires_encryption_and_contiguous_full_read)
{
    struct fixture fixture;
    struct e87_att_read_result result;
    uint8_t build[E87_BUILD_INFO_SIZE];

    E87_ASSERT_TRUE(fixture_init(&fixture));
    E87_ASSERT_TRUE(e87_ble_control_on_connected(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x42),
        &owner_peer, true, NULL));
    result = e87_ble_control_att_read(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x42),
        E87_ATT_HANDLE_BUILD_VALUE, 0U, build, sizeof(build));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_INSUFFICIENT_ENCRYPTION, result.error);
    E87_ASSERT_EQ_U32(0U, result.copied);

    E87_ASSERT_TRUE(e87_ble_control_on_encryption_changed(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x42), true));
    result = e87_ble_control_att_read(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x42),
        E87_ATT_HANDLE_BUILD_VALUE, 0U, NULL, 0U);
    E87_ASSERT_EQ_U32(E87_BUILD_INFO_SIZE, result.value_length);
    E87_ASSERT_TRUE(!e87_ble_control_build_read_complete(&fixture.control));

    result = e87_ble_control_att_read(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x42),
        E87_ATT_HANDLE_BUILD_VALUE, 32U, build, 8U);
    E87_ASSERT_EQ_U32(8U, result.copied);
    E87_ASSERT_TRUE(!e87_ble_control_build_read_complete(&fixture.control));

    result = e87_ble_control_att_read(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x42),
        E87_ATT_HANDLE_BUILD_VALUE, 0U, build, 17U);
    E87_ASSERT_EQ_U32(17U, result.copied);
    E87_ASSERT_TRUE(!e87_ble_control_build_read_complete(&fixture.control));
    result = e87_ble_control_att_read(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x42),
        E87_ATT_HANDLE_BUILD_VALUE, 17U, &build[17], sizeof(build) - 17U);
    E87_ASSERT_EQ_U32(23U, result.copied);
    E87_ASSERT_TRUE(e87_ble_control_build_read_complete(&fixture.control));
    E87_ASSERT_EQ_U32(E87_BUILD_INFO_SCHEMA_V1, build[0]);
    E87_ASSERT_EQ_U32(E87_BUILD_INFO_CAPABILITIES_V1, build[1]);
    E87_ASSERT_EQ_U32(1U, build[22]);
    E87_ASSERT_EQ_U32(16U, build[37]);
}

E87_TEST(state_write_rejects_gate_offset_length_and_semantic_errors)
{
    struct fixture fixture;
    struct e87_att_write_result result;
    uint8_t invalid[sizeof(valid_state)];

    E87_ASSERT_TRUE(fixture_init(&fixture));
    E87_ASSERT_TRUE(e87_ble_control_on_connected(
        &fixture.control, &normal_handle_cookie, UINT16_C(9),
        &owner_peer, true, NULL));
    result = e87_ble_control_att_write(
        &fixture.control, &normal_handle_cookie, UINT16_C(9),
        E87_ATT_HANDLE_STATE_VALUE, 0U, valid_state, sizeof(valid_state));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_INSUFFICIENT_ENCRYPTION, result.error);

    E87_ASSERT_TRUE(e87_ble_control_on_encryption_changed(
        &fixture.control, &normal_handle_cookie, UINT16_C(9), true));
    result = e87_ble_control_att_write(
        &fixture.control, &normal_handle_cookie, UINT16_C(9),
        E87_ATT_HANDLE_STATE_VALUE, 0U, valid_state, sizeof(valid_state));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_INSUFFICIENT_AUTHORIZATION, result.error);
    establish_gate(&fixture, UINT16_C(9));

    result = e87_ble_control_att_write(
        &fixture.control, &normal_handle_cookie, UINT16_C(9),
        E87_ATT_HANDLE_STATE_VALUE, 1U, valid_state, sizeof(valid_state));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_INVALID_OFFSET, result.error);
    result = e87_ble_control_att_write(
        &fixture.control, &normal_handle_cookie, UINT16_C(9),
        E87_ATT_HANDLE_STATE_VALUE, 0U, valid_state, sizeof(valid_state) - 1U);
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_INVALID_ATTRIBUTE_VALUE_LENGTH, result.error);

    memcpy(invalid, valid_state, sizeof(invalid));
    invalid[4] = UINT8_C(0xC0);
    result = e87_ble_control_att_write(
        &fixture.control, &normal_handle_cookie, UINT16_C(9),
        E87_ATT_HANDLE_STATE_VALUE, 0U, invalid, sizeof(invalid));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_SEMANTIC_STATE, result.error);
    E87_ASSERT_EQ_U32(0U, fixture.redraws);
}

E87_TEST(valid_state_is_atomic_and_duplicate_acks_without_redraw)
{
    struct fixture fixture;
    struct e87_att_write_result result;
    struct e87_state_snapshot snapshot;

    E87_ASSERT_TRUE(fixture_init(&fixture));
    E87_ASSERT_TRUE(e87_ble_control_on_connected(
        &fixture.control, &normal_handle_cookie, UINT16_C(3),
        &owner_peer, true, NULL));
    establish_gate(&fixture, UINT16_C(3));
    result = e87_ble_control_att_write(
        &fixture.control, &normal_handle_cookie, UINT16_C(3),
        E87_ATT_HANDLE_STATE_VALUE, 0U, valid_state, sizeof(valid_state));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_NONE, result.error);
    E87_ASSERT_TRUE(result.changed);
    E87_ASSERT_EQ_U32(1U, fixture.redraws);
    E87_ASSERT_TRUE(e87_state_snapshot(&fixture.store, &snapshot));
    E87_ASSERT_EQ_U32(1U, snapshot.revision);
    E87_ASSERT_EQ_U32(64U, snapshot.metrics.day);
    E87_ASSERT_EQ_U32(21U, snapshot.metrics.week);

    result = e87_ble_control_att_write(
        &fixture.control, &normal_handle_cookie, UINT16_C(3),
        E87_ATT_HANDLE_STATE_VALUE, 0U, valid_state, sizeof(valid_state));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_NONE, result.error);
    E87_ASSERT_TRUE(!result.changed);
    E87_ASSERT_EQ_U32(1U, fixture.redraws);
}

E87_TEST(non_owner_stale_and_switching_callbacks_never_commit)
{
    struct fixture fixture;
    struct e87_att_write_result result;
    int stale_handle_cookie;

    E87_ASSERT_TRUE(fixture_init(&fixture));
    E87_ASSERT_TRUE(e87_ble_control_on_connected(
        &fixture.control, &normal_handle_cookie, UINT16_C(11),
        &candidate_peer, false, NULL));
    establish_gate(&fixture, UINT16_C(11));
    result = e87_ble_control_att_write(
        &fixture.control, &normal_handle_cookie, UINT16_C(11),
        E87_ATT_HANDLE_STATE_VALUE, 0U, valid_state, sizeof(valid_state));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_INSUFFICIENT_AUTHORIZATION, result.error);

    result = e87_ble_control_att_write(
        &fixture.control, &stale_handle_cookie, UINT16_C(11),
        E87_ATT_HANDLE_STATE_VALUE, 0U, valid_state, sizeof(valid_state));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_UNLIKELY, result.error);
    result = e87_ble_control_att_write(
        &fixture.control, &normal_handle_cookie, UINT16_C(12),
        E87_ATT_HANDLE_STATE_VALUE, 0U, valid_state, sizeof(valid_state));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_UNLIKELY, result.error);

    e87_ble_control_set_writes_enabled(&fixture.control, false);
    result = e87_ble_control_att_write(
        &fixture.control, &normal_handle_cookie, UINT16_C(11),
        E87_ATT_HANDLE_STATE_VALUE, 0U, valid_state, sizeof(valid_state));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_UNLIKELY, result.error);
    E87_ASSERT_EQ_U32(0U, fixture.redraws);
}

E87_TEST(connection_callbacks_do_not_reopen_a_closed_lifecycle_write_gate)
{
    struct fixture fixture;
    struct e87_att_write_result result;

    E87_ASSERT_TRUE(fixture_init(&fixture));
    e87_ble_control_set_writes_enabled(&fixture.control, false);
    E87_ASSERT_TRUE(e87_ble_control_on_connected(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x61),
        &owner_peer, true, NULL));
    establish_gate(&fixture, UINT16_C(0x61));
    result = e87_ble_control_att_write(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x61),
        E87_ATT_HANDLE_STATE_VALUE, 0U, valid_state, sizeof(valid_state));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_UNLIKELY, result.error);

    E87_ASSERT_TRUE(e87_ble_control_on_disconnected(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x61)));
    E87_ASSERT_TRUE(e87_ble_control_on_connected(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x62),
        &owner_peer, true, NULL));
    establish_gate(&fixture, UINT16_C(0x62));
    result = e87_ble_control_att_write(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x62),
        E87_ATT_HANDLE_STATE_VALUE, 0U, valid_state, sizeof(valid_state));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_UNLIKELY, result.error);

    e87_ble_control_set_writes_enabled(&fixture.control, true);
    result = e87_ble_control_att_write(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x62),
        E87_ATT_HANDLE_STATE_VALUE, 0U, valid_state, sizeof(valid_state));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_NONE, result.error);
    E87_ASSERT_TRUE(result.changed);
}

E87_TEST(steady_normal_disconnect_reconnect_preserves_enabled_write_gate)
{
    struct fixture fixture;
    struct e87_att_write_result result;

    E87_ASSERT_TRUE(fixture_init(&fixture));
    E87_ASSERT_TRUE(e87_ble_control_on_connected(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x63),
        &owner_peer, true, NULL));
    E87_ASSERT_TRUE(e87_ble_control_on_disconnected(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x63)));
    E87_ASSERT_TRUE(e87_ble_control_on_connected(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x64),
        &owner_peer, true, NULL));
    establish_gate(&fixture, UINT16_C(0x64));
    result = e87_ble_control_att_write(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x64),
        E87_ATT_HANDLE_STATE_VALUE, 0U, valid_state, sizeof(valid_state));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_NONE, result.error);
    E87_ASSERT_TRUE(result.changed);
}

E87_TEST(candidate_link_requires_disconnect_and_fresh_owner_reconnect)
{
    struct fixture fixture;
    struct e87_att_write_result result;

    E87_ASSERT_TRUE(fixture_init(&fixture));
    E87_ASSERT_TRUE(e87_ble_control_on_connected(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x71),
        &candidate_peer, false, NULL));
    E87_ASSERT_TRUE(e87_ble_control_on_encryption_changed(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x71), true));
    establish_gate(&fixture, UINT16_C(0x71));
    result = e87_ble_control_att_write(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x71),
        E87_ATT_HANDLE_STATE_VALUE, 0U, valid_state, sizeof(valid_state));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_INSUFFICIENT_AUTHORIZATION,
                      result.error);

    /* A durable bond commit cannot mutate the current non-owner link. */
    result = e87_ble_control_att_write(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x71),
        E87_ATT_HANDLE_STATE_VALUE, 0U, valid_state, sizeof(valid_state));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_INSUFFICIENT_AUTHORIZATION,
                      result.error);

    E87_ASSERT_TRUE(e87_ble_control_on_disconnected(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x71)));
    E87_ASSERT_TRUE(e87_ble_control_on_connected(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x71),
        &candidate_peer, true, NULL));
    E87_ASSERT_TRUE(e87_ble_control_on_encryption_changed(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x71), true));
    establish_gate(&fixture, UINT16_C(0x71));
    result = e87_ble_control_att_write(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x71),
        E87_ATT_HANDLE_STATE_VALUE, 0U, valid_state, sizeof(valid_state));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_NONE, result.error);
    E87_ASSERT_TRUE(result.changed);
}

E87_TEST(device_name_battery_and_unknown_reads_are_bounded)
{
    struct fixture fixture;
    struct e87_att_read_result result;
    uint8_t bytes[4];

    E87_ASSERT_TRUE(fixture_init(&fixture));
    E87_ASSERT_TRUE(e87_ble_control_on_connected(
        &fixture.control, &normal_handle_cookie, UINT16_C(5),
        &owner_peer, true, NULL));
    e87_ble_control_set_battery_percent(&fixture.control, UINT8_C(87));
    result = e87_ble_control_att_read(
        &fixture.control, &normal_handle_cookie, UINT16_C(5),
        E87_ATT_HANDLE_DEVICE_NAME_VALUE, 1U, bytes, 2U);
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_NONE, result.error);
    E87_ASSERT_EQ_U32(3U, result.value_length);
    E87_ASSERT_EQ_U32(2U, result.copied);
    E87_ASSERT_EQ_U32((uint8_t)'8', bytes[0]);
    E87_ASSERT_EQ_U32((uint8_t)'7', bytes[1]);

    result = e87_ble_control_att_read(
        &fixture.control, &normal_handle_cookie, UINT16_C(5),
        E87_ATT_HANDLE_BATTERY_LEVEL_VALUE, 0U, bytes, sizeof(bytes));
    E87_ASSERT_EQ_U32(1U, result.copied);
    E87_ASSERT_EQ_U32(87U, bytes[0]);
    result = e87_ble_control_att_read(
        &fixture.control, &normal_handle_cookie, UINT16_C(5),
        UINT16_C(99), 0U, bytes, sizeof(bytes));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_ATTRIBUTE_NOT_FOUND, result.error);
}

E87_TEST(battery_cccd_is_per_link_and_notifies_only_subscribed_changes)
{
    struct fixture fixture;
    struct e87_att_read_result read_result;
    struct e87_att_write_result write_result;
    uint8_t bytes[2];
    static const uint8_t disabled[2] = {UINT8_C(0), UINT8_C(0)};
    static const uint8_t notify[2] = {UINT8_C(1), UINT8_C(0)};
    static const uint8_t indicate[2] = {UINT8_C(2), UINT8_C(0)};

    E87_ASSERT_TRUE(fixture_init(&fixture));
    E87_ASSERT_TRUE(e87_ble_control_on_connected(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x31),
        &owner_peer, true, NULL));
    read_result = e87_ble_control_att_read(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x31),
        E87_ATT_HANDLE_BATTERY_CCCD, 0U, bytes, sizeof(bytes));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_NONE, read_result.error);
    E87_ASSERT_EQ_U32(2U, read_result.value_length);
    E87_ASSERT_EQ_U32(2U, read_result.copied);
    E87_ASSERT_EQ_U32(0U, bytes[0]);
    E87_ASSERT_EQ_U32(0U, bytes[1]);

    write_result = e87_ble_control_att_write(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x31),
        E87_ATT_HANDLE_BATTERY_CCCD, 1U, notify, sizeof(notify));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_INVALID_OFFSET, write_result.error);
    write_result = e87_ble_control_att_write(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x31),
        E87_ATT_HANDLE_BATTERY_CCCD, 0U, notify, 1U);
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_INVALID_ATTRIBUTE_VALUE_LENGTH,
                      write_result.error);
    write_result = e87_ble_control_att_write(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x31),
        E87_ATT_HANDLE_BATTERY_CCCD, 0U, indicate, sizeof(indicate));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_CCCD_VALUE, write_result.error);

    write_result = e87_ble_control_att_write(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x31),
        E87_ATT_HANDLE_BATTERY_CCCD, 0U, notify, sizeof(notify));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_NONE, write_result.error);
    E87_ASSERT_TRUE(write_result.changed);
    E87_ASSERT_TRUE(e87_ble_control_set_battery_percent(
        &fixture.control, UINT8_C(41)));
    E87_ASSERT_EQ_U32(1U, fixture.notifications);
    E87_ASSERT_TRUE(fixture.notified_app_handle == &normal_handle_cookie);
    E87_ASSERT_EQ_U32(0x31U, fixture.notified_connection_handle);
    E87_ASSERT_EQ_U32(E87_ATT_HANDLE_BATTERY_LEVEL_VALUE,
                      fixture.notified_attribute_handle);
    E87_ASSERT_EQ_U32(41U, fixture.notified_percent);
    E87_ASSERT_TRUE(!e87_ble_control_set_battery_percent(
        &fixture.control, UINT8_C(41)));
    E87_ASSERT_EQ_U32(1U, fixture.notifications);
    E87_ASSERT_TRUE(e87_ble_control_set_battery_percent(
        &fixture.control, UINT8_C(255)));
    E87_ASSERT_EQ_U32(2U, fixture.notifications);
    E87_ASSERT_EQ_U32(100U, fixture.notified_percent);

    write_result = e87_ble_control_att_write(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x31),
        E87_ATT_HANDLE_BATTERY_CCCD, 0U, disabled, sizeof(disabled));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_NONE, write_result.error);
    E87_ASSERT_TRUE(e87_ble_control_set_battery_percent(
        &fixture.control, UINT8_C(42)));
    E87_ASSERT_EQ_U32(2U, fixture.notifications);

    write_result = e87_ble_control_att_write(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x31),
        E87_ATT_HANDLE_BATTERY_CCCD, 0U, notify, sizeof(notify));
    E87_ASSERT_EQ_U32(E87_ATT_ERROR_NONE, write_result.error);
    E87_ASSERT_TRUE(e87_ble_control_on_disconnected(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x31)));
    E87_ASSERT_TRUE(e87_ble_control_on_connected(
        &fixture.control, &normal_handle_cookie, UINT16_C(0x32),
        &owner_peer, true, NULL));
    E87_ASSERT_TRUE(e87_ble_control_set_battery_percent(
        &fixture.control, UINT8_C(43)));
    E87_ASSERT_EQ_U32(2U, fixture.notifications);
}

static const struct e87_test_case cases[] = {
    E87_TEST_CASE(build_read_requires_encryption_and_contiguous_full_read),
    E87_TEST_CASE(state_write_rejects_gate_offset_length_and_semantic_errors),
    E87_TEST_CASE(valid_state_is_atomic_and_duplicate_acks_without_redraw),
    E87_TEST_CASE(non_owner_stale_and_switching_callbacks_never_commit),
    E87_TEST_CASE(connection_callbacks_do_not_reopen_a_closed_lifecycle_write_gate),
    E87_TEST_CASE(steady_normal_disconnect_reconnect_preserves_enabled_write_gate),
    E87_TEST_CASE(candidate_link_requires_disconnect_and_fresh_owner_reconnect),
    E87_TEST_CASE(device_name_battery_and_unknown_reads_are_bounded),
    E87_TEST_CASE(battery_cccd_is_per_link_and_notifies_only_subscribed_changes),
};

const struct e87_test_suite e87_test_suite = {
    "ble-control", cases, sizeof(cases) / sizeof(cases[0]),
};
