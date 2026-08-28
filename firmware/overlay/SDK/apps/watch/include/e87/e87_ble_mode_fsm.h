#ifndef E87_BLE_MODE_FSM_H
#define E87_BLE_MODE_FSM_H

#include <stdbool.h>
#include <stdint.h>

enum e87_ble_mode {
    E87_BLE_MODE_NORMAL = 0,
    E87_BLE_MODE_MAINTENANCE = 1
};

enum e87_ble_mode_phase {
    E87_BLE_MODE_PHASE_STEADY = 0,
    E87_BLE_MODE_PHASE_DISABLE_ADVERTISING = 1,
    E87_BLE_MODE_PHASE_REJECT_WRITES = 2,
    E87_BLE_MODE_PHASE_REQUEST_DISCONNECT = 3,
    E87_BLE_MODE_PHASE_AWAIT_DISCONNECT = 4,
    E87_BLE_MODE_PHASE_RELEASE_PROFILE = 5,
    E87_BLE_MODE_PHASE_INITIALIZE_TARGET = 6,
    E87_BLE_MODE_PHASE_CONFIGURE_TARGET_WRITES = 7,
    E87_BLE_MODE_PHASE_ENABLE_TARGET_ADVERTISING = 8
};

enum e87_ble_mode_step_result {
    E87_BLE_MODE_STEP_WAITING = 0,
    E87_BLE_MODE_STEP_PROGRESSED = 1,
    E87_BLE_MODE_STEP_COMPLETE = 2,
    E87_BLE_MODE_STEP_FAILED = 3
};

typedef bool
    (*e87_ble_mode_advertising_fn)(
        void *context,
        enum e87_ble_mode mode,
        bool enabled);
typedef void
    (*e87_ble_mode_writes_fn)(
        void *context,
        bool enabled);
typedef bool
    (*e87_ble_mode_disconnect_fn)(
        void *context,
        enum e87_ble_mode mode,
        const void *app_handle,
        uint16_t connection_handle);
/*
 * Called while the FSM still admits exact-handle connection callbacks. The
 * adapter must perform its final no-link check before freeing the handle. If
 * a link appears, it returns false and leaves the handle owned and retryable.
 * A true result guarantees that no live link or later callback can reference
 * the released handle.
 */
typedef bool
    (*e87_ble_mode_release_fn)(
        void *context,
        enum e87_ble_mode mode,
        const void *app_handle);

/*
 * Initializes a profile without advertising it and returns its owned
 * multi-handle identity. On false, or if the returned identity is NULL,
 * the adapter must retain no live profile.
 */
typedef bool
    (*e87_ble_mode_initialize_fn)(
        void *context,
        enum e87_ble_mode mode,
        const void **out_handle);

struct e87_ble_mode_ops {
    void *context;
    e87_ble_mode_advertising_fn set_advertising;
    e87_ble_mode_writes_fn set_normal_writes_enabled;
    e87_ble_mode_disconnect_fn request_disconnect;
    e87_ble_mode_release_fn release_profile;
    e87_ble_mode_initialize_fn initialize_profile;
};

struct e87_ble_mode_fsm {
    struct e87_ble_mode_ops private_ops;
    enum e87_ble_mode private_current;
    enum e87_ble_mode private_target;
    enum e87_ble_mode_phase private_phase;
    const void *private_profile_handle;
    const void *private_connection_app_handle;
    uint16_t private_connection_handle;
    bool private_connected;
};

bool
e87_ble_mode_init(
    struct e87_ble_mode_fsm *fsm,
    enum e87_ble_mode initial_mode,
    const void *profile_handle,
    const struct e87_ble_mode_ops *ops);

bool
e87_ble_mode_set_connection(
    struct e87_ble_mode_fsm *fsm,
    const void *app_handle,
    uint16_t connection_handle);

bool
e87_ble_mode_request(
    struct e87_ble_mode_fsm *fsm,
    enum e87_ble_mode target);

enum e87_ble_mode_step_result
e87_ble_mode_step(
    struct e87_ble_mode_fsm *fsm);

bool
e87_ble_mode_on_disconnect_complete(
    struct e87_ble_mode_fsm *fsm,
    const void *app_handle,
    uint16_t connection_handle);

enum e87_ble_mode
e87_ble_mode_current(
    const struct e87_ble_mode_fsm *fsm);

enum e87_ble_mode_phase
e87_ble_mode_phase(
    const struct e87_ble_mode_fsm *fsm);

#endif
