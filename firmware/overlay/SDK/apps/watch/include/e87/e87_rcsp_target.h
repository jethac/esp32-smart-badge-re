#ifndef E87_RCSP_TARGET_H
#define E87_RCSP_TARGET_H

#include <stdbool.h>
#include <stdint.h>

#include "e87/e87_maintenance.h"

struct e87_rcsp_target {
    struct e87_rcsp_target_adapter private_adapter;
    struct e87_maintenance *private_maintenance;
    uint32_t private_loader_saddr;
    bool private_initialized;
    bool private_commands_allowed;
    bool private_update_armed;
    bool private_update_started;
    bool private_normal_mode_requested;
};

/*
 * All calls are serialized on app_core. The caller-owned maintenance object
 * remains the only event/loader/power authority and must be the same object
 * passed to init, poll, and exit.
 * Base BLE/SM/ATT transport must already be initialized by later application
 * integration without the stock multi-protocol/profile initializers.
 *
 * This adapter is the sole actual maintenance profile creator. A later
 * e87_ble_mode_fsm initialize_profile callback must call init exactly once
 * after the normal profile has been released, then adopt the non-NULL
 * opaque profile handle returned by e87_rcsp_target_profile_handle() for
 * bookkeeping.
 * Its reverse release callback must verify that same handle and drive only
 * exit/poll to completion; it must not release the SDK profile itself. The
 * adapter owns SDK teardown, invalidates the handle after normal mode is
 * requested, and makes repeated exit calls side-effect free.
 * Every later RCSP command-ingress callback
 * must consult e87_rcsp_target_commands_allowed() before dispatch.
 * It must reject the command when that returns false; the pinned SDK has no
 * global reject switch.
 *
 * Later application integration must forward the same UPDATE_CH_SUCESS_REPORT
 * tuple received from the SDK state callback into
 * e87_rcsp_official_loader_callback(). The loader address in that report is
 * the address already retained by the SDK's update core; an independently
 * constructed report is not an admissible handoff authority.
 */
bool e87_rcsp_target_init(
    struct e87_rcsp_target *target,
    struct e87_maintenance *maintenance,
    uint32_t now_ms);

enum e87_maintenance_result e87_rcsp_target_poll(
    struct e87_rcsp_target *target,
    struct e87_maintenance *maintenance,
    uint32_t now_ms);

enum e87_maintenance_result e87_rcsp_target_exit(
    struct e87_rcsp_target *target,
    struct e87_maintenance *maintenance,
    uint32_t now_ms);

const void *e87_rcsp_target_profile_handle(
    const struct e87_rcsp_target *target);

bool e87_rcsp_target_commands_allowed(
    const struct e87_rcsp_target *target);

bool e87_rcsp_target_normal_mode_requested(
    const struct e87_rcsp_target *target);

#endif
