#include "e87/e87_ble_mode_fsm.h"

#include <string.h>

static bool mode_is_valid(enum e87_ble_mode mode)
{
    return mode == E87_BLE_MODE_NORMAL ||
           mode == E87_BLE_MODE_MAINTENANCE;
}

bool
e87_ble_mode_init(
    struct e87_ble_mode_fsm *fsm,
    enum e87_ble_mode initial_mode,
    const void *profile_handle,
    const struct e87_ble_mode_ops *ops)
{
    struct e87_ble_mode_fsm initialized;

    if (fsm == NULL || !mode_is_valid(initial_mode) ||
        profile_handle == NULL || ops == NULL ||
        ops->set_advertising == NULL ||
        ops->set_normal_writes_enabled == NULL ||
        ops->request_disconnect == NULL ||
        ops->release_profile == NULL ||
        ops->initialize_profile == NULL) {
        return false;
    }

    memset(&initialized, 0, sizeof(initialized));
    initialized.private_ops = *ops;
    initialized.private_current = initial_mode;
    initialized.private_target = initial_mode;
    initialized.private_phase = E87_BLE_MODE_PHASE_STEADY;
    initialized.private_profile_handle = profile_handle;
    *fsm = initialized;
    return true;
}

bool
e87_ble_mode_set_connection(
    struct e87_ble_mode_fsm *fsm,
    const void *app_handle,
    uint16_t connection_handle)
{
    bool profile_is_live;

    profile_is_live = fsm != NULL &&
        (fsm->private_phase == E87_BLE_MODE_PHASE_STEADY ||
         fsm->private_phase == E87_BLE_MODE_PHASE_DISABLE_ADVERTISING ||
         fsm->private_phase == E87_BLE_MODE_PHASE_REJECT_WRITES ||
         fsm->private_phase == E87_BLE_MODE_PHASE_REQUEST_DISCONNECT ||
         fsm->private_phase == E87_BLE_MODE_PHASE_AWAIT_DISCONNECT ||
         fsm->private_phase == E87_BLE_MODE_PHASE_RELEASE_PROFILE);
    if (!profile_is_live || app_handle == NULL ||
        fsm->private_connected ||
        app_handle != fsm->private_profile_handle) {
        return false;
    }

    fsm->private_connection_app_handle = app_handle;
    fsm->private_connection_handle = connection_handle;
    fsm->private_connected = true;
    if (fsm->private_phase == E87_BLE_MODE_PHASE_RELEASE_PROFILE) {
        fsm->private_phase =
            E87_BLE_MODE_PHASE_REQUEST_DISCONNECT;
    }
    return true;
}

bool
e87_ble_mode_request(
    struct e87_ble_mode_fsm *fsm,
    enum e87_ble_mode target)
{
    if (fsm == NULL || !mode_is_valid(target) ||
        fsm->private_phase != E87_BLE_MODE_PHASE_STEADY ||
        fsm->private_profile_handle == NULL ||
        target == fsm->private_current) {
        return false;
    }

    fsm->private_target = target;
    /*
     * Close the lifecycle write gate before advertising disable can admit a
     * connection callback. It remains closed until the target profile has
     * been installed and explicitly configured.
     */
    fsm->private_ops.set_normal_writes_enabled(
        fsm->private_ops.context, false);
    fsm->private_phase =
        E87_BLE_MODE_PHASE_DISABLE_ADVERTISING;
    return true;
}

static enum e87_ble_mode_step_result
release_active_profile(struct e87_ble_mode_fsm *fsm)
{
    bool released;

    if (fsm->private_connected) {
        fsm->private_phase =
            E87_BLE_MODE_PHASE_REQUEST_DISCONNECT;
        return E87_BLE_MODE_STEP_PROGRESSED;
    }

    /*
     * Keep exact-handle callback admission open through the adapter's final
     * no-link check. A connection admitted reentrantly cancels release and
     * must be drained before the adapter retries profile destruction.
     */
    released = fsm->private_ops.release_profile(
        fsm->private_ops.context,
        fsm->private_current,
        fsm->private_profile_handle);
    if (fsm->private_connected) {
        fsm->private_phase = E87_BLE_MODE_PHASE_REQUEST_DISCONNECT;
        return E87_BLE_MODE_STEP_PROGRESSED;
    }
    if (!released) {
        fsm->private_phase =
            E87_BLE_MODE_PHASE_RELEASE_PROFILE;
        return E87_BLE_MODE_STEP_FAILED;
    }

    fsm->private_profile_handle = NULL;
    fsm->private_phase = E87_BLE_MODE_PHASE_INITIALIZE_TARGET;
    return E87_BLE_MODE_STEP_PROGRESSED;
}

enum e87_ble_mode_step_result
e87_ble_mode_step(
    struct e87_ble_mode_fsm *fsm)
{
    if (fsm == NULL) {
        return E87_BLE_MODE_STEP_FAILED;
    }

    switch (fsm->private_phase) {
    case E87_BLE_MODE_PHASE_STEADY:
        return E87_BLE_MODE_STEP_WAITING;

    case E87_BLE_MODE_PHASE_DISABLE_ADVERTISING:
        if (!fsm->private_ops.set_advertising(
                fsm->private_ops.context,
                fsm->private_current, false)) {
            return E87_BLE_MODE_STEP_FAILED;
        }
        fsm->private_phase =
            E87_BLE_MODE_PHASE_REJECT_WRITES;
        return E87_BLE_MODE_STEP_PROGRESSED;

    case E87_BLE_MODE_PHASE_REJECT_WRITES:
        fsm->private_phase =
            E87_BLE_MODE_PHASE_REQUEST_DISCONNECT;
        return E87_BLE_MODE_STEP_PROGRESSED;

    case E87_BLE_MODE_PHASE_REQUEST_DISCONNECT: {
        bool request_accepted;

        if (!fsm->private_connected) {
            return release_active_profile(fsm);
        }

        fsm->private_phase =
            E87_BLE_MODE_PHASE_AWAIT_DISCONNECT;
        request_accepted = fsm->private_ops.request_disconnect(
            fsm->private_ops.context,
            fsm->private_current,
            fsm->private_connection_app_handle,
            fsm->private_connection_handle);
        if (fsm->private_phase ==
            E87_BLE_MODE_PHASE_RELEASE_PROFILE) {
            return E87_BLE_MODE_STEP_PROGRESSED;
        }
        if (!request_accepted) {
            fsm->private_phase =
                E87_BLE_MODE_PHASE_REQUEST_DISCONNECT;
            return E87_BLE_MODE_STEP_FAILED;
        }
        return E87_BLE_MODE_STEP_WAITING;
    }

    case E87_BLE_MODE_PHASE_AWAIT_DISCONNECT:
        return E87_BLE_MODE_STEP_WAITING;

    case E87_BLE_MODE_PHASE_RELEASE_PROFILE:
        return release_active_profile(fsm);

    case E87_BLE_MODE_PHASE_INITIALIZE_TARGET: {
        const void *new_handle = NULL;

        if (!fsm->private_ops.initialize_profile(
                fsm->private_ops.context,
                fsm->private_target,
                &new_handle) ||
            new_handle == NULL) {
            return E87_BLE_MODE_STEP_FAILED;
        }
        fsm->private_profile_handle = new_handle;
        fsm->private_current = fsm->private_target;
        fsm->private_phase =
            E87_BLE_MODE_PHASE_CONFIGURE_TARGET_WRITES;
        return E87_BLE_MODE_STEP_PROGRESSED;
    }

    case E87_BLE_MODE_PHASE_CONFIGURE_TARGET_WRITES:
        fsm->private_ops.set_normal_writes_enabled(
            fsm->private_ops.context,
            fsm->private_current == E87_BLE_MODE_NORMAL);
        fsm->private_phase =
            E87_BLE_MODE_PHASE_ENABLE_TARGET_ADVERTISING;
        return E87_BLE_MODE_STEP_PROGRESSED;

    case E87_BLE_MODE_PHASE_ENABLE_TARGET_ADVERTISING: {
        bool advertising_enabled;

        fsm->private_phase = E87_BLE_MODE_PHASE_STEADY;
        advertising_enabled = fsm->private_ops.set_advertising(
            fsm->private_ops.context,
            fsm->private_current, true);
        if (!advertising_enabled && !fsm->private_connected) {
            fsm->private_phase =
                E87_BLE_MODE_PHASE_ENABLE_TARGET_ADVERTISING;
            return E87_BLE_MODE_STEP_FAILED;
        }
        return E87_BLE_MODE_STEP_COMPLETE;
    }

    default:
        return E87_BLE_MODE_STEP_FAILED;
    }
}

bool
e87_ble_mode_on_disconnect_complete(
    struct e87_ble_mode_fsm *fsm,
    const void *app_handle,
    uint16_t connection_handle)
{
    if (fsm == NULL || !fsm->private_connected ||
        app_handle != fsm->private_connection_app_handle ||
        connection_handle != fsm->private_connection_handle) {
        return false;
    }

    fsm->private_connected = false;
    fsm->private_connection_app_handle = NULL;
    fsm->private_connection_handle = 0U;
    if (fsm->private_phase ==
        E87_BLE_MODE_PHASE_AWAIT_DISCONNECT) {
        fsm->private_phase =
            E87_BLE_MODE_PHASE_RELEASE_PROFILE;
    }
    return true;
}

enum e87_ble_mode
e87_ble_mode_current(
    const struct e87_ble_mode_fsm *fsm)
{
    return fsm == NULL
               ? E87_BLE_MODE_NORMAL
               : fsm->private_current;
}

enum e87_ble_mode_phase
e87_ble_mode_phase(
    const struct e87_ble_mode_fsm *fsm)
{
    return fsm == NULL
               ? E87_BLE_MODE_PHASE_STEADY
               : fsm->private_phase;
}
