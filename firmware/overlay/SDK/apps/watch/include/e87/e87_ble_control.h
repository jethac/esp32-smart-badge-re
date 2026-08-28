#ifndef E87_BLE_CONTROL_H
#define E87_BLE_CONTROL_H

#include "e87/e87_build_info.h"
#include "e87/e87_bond_policy.h"
#include "e87/e87_state.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define E87_NORMAL_ADVERTISING_DATA_SIZE 26u

enum e87_att_handle {
    E87_ATT_HANDLE_GAP_SERVICE = 1,
    E87_ATT_HANDLE_DEVICE_NAME_DECLARATION = 2,
    E87_ATT_HANDLE_DEVICE_NAME_VALUE = 3,
    E87_ATT_HANDLE_E87_SERVICE = 4,
    E87_ATT_HANDLE_STATE_DECLARATION = 5,
    E87_ATT_HANDLE_STATE_VALUE = 6,
    E87_ATT_HANDLE_BUILD_DECLARATION = 7,
    E87_ATT_HANDLE_BUILD_VALUE = 8,
    E87_ATT_HANDLE_BATTERY_SERVICE = 9,
    E87_ATT_HANDLE_BATTERY_LEVEL_DECLARATION = 10,
    E87_ATT_HANDLE_BATTERY_LEVEL_VALUE = 11,
    E87_ATT_HANDLE_BATTERY_CCCD = 12
};

enum e87_att_error {
    E87_ATT_ERROR_NONE = 0x00,
    E87_ATT_ERROR_REQUEST_NOT_SUPPORTED = 0x06,
    E87_ATT_ERROR_INVALID_OFFSET = 0x07,
    E87_ATT_ERROR_INSUFFICIENT_AUTHORIZATION = 0x08,
    E87_ATT_ERROR_ATTRIBUTE_NOT_FOUND = 0x0A,
    E87_ATT_ERROR_INVALID_ATTRIBUTE_VALUE_LENGTH = 0x0D,
    E87_ATT_ERROR_UNLIKELY = 0x0E,
    E87_ATT_ERROR_INSUFFICIENT_ENCRYPTION = 0x0F,
    E87_ATT_ERROR_SEMANTIC_STATE = 0x80,
    E87_ATT_ERROR_CCCD_VALUE = 0x80
};

struct e87_att_read_result {
    uint8_t error;
    uint16_t value_length;
    uint16_t copied;
};

struct e87_att_write_result {
    uint8_t error;
    bool changed;
};

typedef void
    (*e87_ble_state_changed_fn)(
        void *context,
        const struct e87_state_snapshot *snapshot);
typedef void
    (*e87_ble_battery_notification_fn)(
        void *context,
        const void *app_handle,
        uint16_t connection_handle,
        uint16_t attribute_handle,
        uint8_t percent);

struct e87_ble_control_observer {
    void *context;
    e87_ble_state_changed_fn state_changed;
    e87_ble_battery_notification_fn battery_notification;
};

struct e87_ble_control {
    const void *private_normal_handle;
    uint16_t private_connection_handle;
    uint32_t private_connection_generation;
    uint16_t private_battery_cccd;
    struct e87_ble_peer private_peer;
    bool private_connected;
    bool private_encrypted;
    bool private_owner;
    bool private_writes_enabled;
    bool private_build_read_complete;
    uint16_t private_build_read_covered;
    uint8_t private_battery_percent;
    uint8_t private_build_info[E87_BUILD_INFO_SIZE];
    struct e87_state_store *private_state_store;
    struct e87_ble_control_observer private_observer;
};

extern const uint8_t e87_normal_gatt_profile[];
extern const size_t e87_normal_gatt_profile_size;
extern const uint8_t
    e87_normal_advertising_data[E87_NORMAL_ADVERTISING_DATA_SIZE];

bool
e87_ble_control_init(
    struct e87_ble_control *control,
    const void *normal_handle,
    struct e87_state_store *state_store,
    const struct e87_build_identity *identity,
    const struct e87_ble_control_observer *observer);

/*
 * Candidate links are never promoted in place. After a durable owner commit,
 * disconnect the candidate and establish a fresh link with is_owner=true.
 * This avoids stale commit-token ABA across profile destruction/recreation.
 */
bool
e87_ble_control_on_connected(
    struct e87_ble_control *control,
    const void *app_handle,
    uint16_t connection_handle,
    const struct e87_ble_peer *peer,
    bool is_owner,
    uint32_t *out_connection_generation);

bool
e87_ble_control_on_encryption_changed(
    struct e87_ble_control *control,
    const void *app_handle,
    uint16_t connection_handle,
    bool encrypted);

bool
e87_ble_control_on_disconnected(
    struct e87_ble_control *control,
    const void *app_handle,
    uint16_t connection_handle);

void
e87_ble_control_set_writes_enabled(
    struct e87_ble_control *control,
    bool enabled);

bool
e87_ble_control_set_battery_percent(
    struct e87_ble_control *control,
    uint8_t percent);

bool
e87_ble_control_build_read_complete(
    const struct e87_ble_control *control);

struct e87_att_read_result
e87_ble_control_att_read(
    struct e87_ble_control *control,
    const void *app_handle,
    uint16_t connection_handle,
    uint16_t attribute_handle,
    uint16_t offset,
    uint8_t *buffer,
    uint16_t capacity);

struct e87_att_write_result
e87_ble_control_att_write(
    struct e87_ble_control *control,
    const void *app_handle,
    uint16_t connection_handle,
    uint16_t attribute_handle,
    uint16_t offset,
    const uint8_t *buffer,
    uint16_t length);

#endif
