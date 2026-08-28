#include "e87/e87_ble_control.h"

#include <string.h>

static bool peer_is_valid(const struct e87_ble_peer *peer)
{
    size_t index;
    bool has_nonzero_address = false;

    if (peer == NULL || peer->address_type > UINT8_C(1)) {
        return false;
    }
    for (index = 0U; index < E87_BLE_ADDRESS_SIZE; index += 1U) {
        has_nonzero_address =
            has_nonzero_address || peer->address[index] != UINT8_C(0);
    }
    return has_nonzero_address;
}

static bool link_is_current(const struct e87_ble_control *control,
                            const void *app_handle,
                            uint16_t connection_handle)
{
    return control != NULL &&
           control->private_connected &&
           control->private_normal_handle == app_handle &&
           control->private_connection_handle == connection_handle;
}

static struct e87_att_read_result read_error(uint8_t error)
{
    const struct e87_att_read_result result = {error, 0U, 0U};

    return result;
}

static struct e87_att_read_result read_value(
    struct e87_ble_control *control,
    const uint8_t *value,
    uint16_t value_length,
    uint16_t offset,
    uint8_t *buffer,
    uint16_t capacity,
    bool advances_build_gate)
{
    struct e87_att_read_result result;
    uint16_t remaining;

    result.error = E87_ATT_ERROR_NONE;
    result.value_length = value_length;
    result.copied = 0U;
    if (offset > value_length) {
        return read_error(E87_ATT_ERROR_INVALID_OFFSET);
    }
    if (buffer == NULL || capacity == 0U || offset == value_length) {
        return result;
    }

    remaining = (uint16_t)(value_length - offset);
    result.copied = capacity < remaining ? capacity : remaining;
    memcpy(buffer, &value[offset], result.copied);

    if (advances_build_gate &&
        offset <= control->private_build_read_covered) {
        const uint16_t end = (uint16_t)(offset + result.copied);

        if (end > control->private_build_read_covered) {
            control->private_build_read_covered = end;
        }
        if (control->private_build_read_covered ==
            (uint16_t)E87_BUILD_INFO_SIZE) {
            control->private_build_read_complete = true;
        }
    }
    return result;
}

bool
e87_ble_control_init(
    struct e87_ble_control *control,
    const void *normal_handle,
    struct e87_state_store *state_store,
    const struct e87_build_identity *identity,
    const struct e87_ble_control_observer *observer)
{
    struct e87_ble_control initialized;

    if (control == NULL || normal_handle == NULL ||
        state_store == NULL || identity == NULL ||
        observer == NULL ||
        observer->state_changed == NULL ||
        observer->battery_notification == NULL) {
        return false;
    }

    memset(&initialized, 0, sizeof(initialized));
    initialized.private_normal_handle = normal_handle;
    initialized.private_state_store = state_store;
    initialized.private_observer = *observer;
    initialized.private_writes_enabled = true;
    if (!e87_build_info_encode(identity,
                               initialized.private_build_info,
                               sizeof(initialized.private_build_info))) {
        return false;
    }
    *control = initialized;
    return true;
}

bool
e87_ble_control_on_connected(
    struct e87_ble_control *control,
    const void *app_handle,
    uint16_t connection_handle,
    const struct e87_ble_peer *peer,
    bool is_owner,
    uint32_t *out_connection_generation)
{
    if (control == NULL ||
        app_handle != control->private_normal_handle ||
        control->private_connected || !peer_is_valid(peer) ||
        control->private_connection_generation == UINT32_MAX) {
        return false;
    }

    control->private_connection_generation += UINT32_C(1);
    control->private_connection_handle = connection_handle;
    control->private_peer = *peer;
    control->private_connected = true;
    control->private_encrypted = false;
    control->private_owner = is_owner;
    control->private_build_read_complete = false;
    control->private_build_read_covered = 0U;
    control->private_battery_cccd = UINT16_C(0);
    if (out_connection_generation != NULL) {
        *out_connection_generation =
            control->private_connection_generation;
    }
    return true;
}

bool
e87_ble_control_on_encryption_changed(
    struct e87_ble_control *control,
    const void *app_handle,
    uint16_t connection_handle,
    bool encrypted)
{
    if (!link_is_current(control, app_handle, connection_handle)) {
        return false;
    }

    control->private_encrypted = encrypted;
    if (!encrypted) {
        control->private_build_read_complete = false;
        control->private_build_read_covered = 0U;
    }
    return true;
}

bool
e87_ble_control_on_disconnected(
    struct e87_ble_control *control,
    const void *app_handle,
    uint16_t connection_handle)
{
    if (!link_is_current(control, app_handle, connection_handle)) {
        return false;
    }

    control->private_connected = false;
    memset(&control->private_peer, 0,
           sizeof(control->private_peer));
    control->private_encrypted = false;
    control->private_owner = false;
    control->private_build_read_complete = false;
    control->private_build_read_covered = 0U;
    control->private_battery_cccd = UINT16_C(0);
    return true;
}

void
e87_ble_control_set_writes_enabled(
    struct e87_ble_control *control,
    bool enabled)
{
    if (control != NULL) {
        control->private_writes_enabled = enabled;
    }
}

bool
e87_ble_control_set_battery_percent(
    struct e87_ble_control *control,
    uint8_t percent)
{
    uint8_t clamped;

    if (control == NULL) {
        return false;
    }

    clamped = percent > UINT8_C(100) ? UINT8_C(100) : percent;
    if (clamped == control->private_battery_percent) {
        return false;
    }

    control->private_battery_percent = clamped;
    if (control->private_connected &&
        control->private_battery_cccd == UINT16_C(1)) {
        control->private_observer.battery_notification(
            control->private_observer.context,
            control->private_normal_handle,
            control->private_connection_handle,
            E87_ATT_HANDLE_BATTERY_LEVEL_VALUE,
            clamped);
    }
    return true;
}

bool
e87_ble_control_build_read_complete(
    const struct e87_ble_control *control)
{
    return control != NULL &&
           control->private_build_read_complete;
}

struct e87_att_read_result
e87_ble_control_att_read(
    struct e87_ble_control *control,
    const void *app_handle,
    uint16_t connection_handle,
    uint16_t attribute_handle,
    uint16_t offset,
    uint8_t *buffer,
    uint16_t capacity)
{
    static const uint8_t device_name[] = {'E', '8', '7'};
    uint8_t cccd[2];

    if (!link_is_current(control, app_handle, connection_handle)) {
        return read_error(E87_ATT_ERROR_UNLIKELY);
    }

    switch (attribute_handle) {
    case E87_ATT_HANDLE_DEVICE_NAME_VALUE:
        return read_value(control, device_name,
                          (uint16_t)sizeof(device_name),
                          offset, buffer, capacity, false);
    case E87_ATT_HANDLE_BUILD_VALUE:
        if (!control->private_encrypted) {
            return read_error(
                E87_ATT_ERROR_INSUFFICIENT_ENCRYPTION);
        }
        return read_value(control, control->private_build_info,
                          (uint16_t)sizeof(control->private_build_info),
                          offset, buffer, capacity, true);
    case E87_ATT_HANDLE_BATTERY_LEVEL_VALUE:
        return read_value(control, &control->private_battery_percent,
                          UINT16_C(1), offset, buffer, capacity, false);
    case E87_ATT_HANDLE_BATTERY_CCCD:
        cccd[0] = (uint8_t)control->private_battery_cccd;
        cccd[1] =
            (uint8_t)(control->private_battery_cccd >> 8U);
        return read_value(control, cccd, UINT16_C(2),
                          offset, buffer, capacity, false);
    default:
        return read_error(E87_ATT_ERROR_ATTRIBUTE_NOT_FOUND);
    }
}

static struct e87_att_write_result write_cccd(
    struct e87_ble_control *control,
    uint16_t offset,
    const uint8_t *buffer,
    uint16_t length)
{
    struct e87_att_write_result result;
    uint16_t value;

    result.error = E87_ATT_ERROR_NONE;
    result.changed = false;
    if (offset != 0U) {
        result.error = E87_ATT_ERROR_INVALID_OFFSET;
        return result;
    }
    if (length != UINT16_C(2)) {
        result.error = E87_ATT_ERROR_INVALID_ATTRIBUTE_VALUE_LENGTH;
        return result;
    }
    if (buffer == NULL) {
        result.error = E87_ATT_ERROR_CCCD_VALUE;
        return result;
    }

    value = (uint16_t)buffer[0] |
            (uint16_t)((uint16_t)buffer[1] << 8U);
    if (value != UINT16_C(0) && value != UINT16_C(1)) {
        result.error = E87_ATT_ERROR_CCCD_VALUE;
        return result;
    }

    result.changed = value != control->private_battery_cccd;
    control->private_battery_cccd = value;
    return result;
}

struct e87_att_write_result
e87_ble_control_att_write(
    struct e87_ble_control *control,
    const void *app_handle,
    uint16_t connection_handle,
    uint16_t attribute_handle,
    uint16_t offset,
    const uint8_t *buffer,
    uint16_t length)
{
    struct e87_att_write_result result;
    struct e87_metrics decoded;

    result.error = E87_ATT_ERROR_NONE;
    result.changed = false;
    if (!link_is_current(control, app_handle, connection_handle) ||
        !control->private_writes_enabled) {
        result.error = E87_ATT_ERROR_UNLIKELY;
        return result;
    }
    if (attribute_handle == E87_ATT_HANDLE_BATTERY_CCCD) {
        return write_cccd(control, offset, buffer, length);
    }
    if (attribute_handle != E87_ATT_HANDLE_STATE_VALUE) {
        result.error = E87_ATT_ERROR_ATTRIBUTE_NOT_FOUND;
        return result;
    }
    if (!control->private_encrypted) {
        result.error = E87_ATT_ERROR_INSUFFICIENT_ENCRYPTION;
        return result;
    }
    if (offset != 0U) {
        result.error = E87_ATT_ERROR_INVALID_OFFSET;
        return result;
    }
    if (length != (uint16_t)E87_STATE_PACKET_SIZE) {
        result.error = E87_ATT_ERROR_INVALID_ATTRIBUTE_VALUE_LENGTH;
        return result;
    }
    if (!control->private_owner ||
        !control->private_build_read_complete) {
        result.error = E87_ATT_ERROR_INSUFFICIENT_AUTHORIZATION;
        return result;
    }
    if (e87_state_decode(buffer, length, &decoded) != E87_STATE_OK) {
        result.error = E87_ATT_ERROR_SEMANTIC_STATE;
        return result;
    }

    result.changed =
        e87_state_commit(control->private_state_store, &decoded);
    if (result.changed) {
        struct e87_state_snapshot snapshot;

        if (e87_state_snapshot(control->private_state_store, &snapshot)) {
            control->private_observer.state_changed(
                control->private_observer.context, &snapshot);
        }
    }
    return result;
}
