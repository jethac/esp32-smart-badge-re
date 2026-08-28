#if !defined(E87_HOST_TEST)
#include <app_config.h>
#include <system/includes.h>
#endif

#include "e87/e87_rcsp_target.h"

#include <string.h>

#if defined(E87_HOST_TEST)
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;

typedef enum {
    USB_UPDATA = 0x5A00,
    SD0_UPDATA,
    SD1_UPDATA,
    PC_UPDATA,
    UART_UPDATA,
    BT_UPDATA,
    BLE_APP_UPDATA,
} UPDATA_TYPE;

typedef struct _UPDATA_PARM {
    u16 parm_crc;
    u16 parm_type;
    u16 parm_result;
    u16 magic;
    union {
        u8 file_path[32];
        u8 file_patch[32];
        u8 nand_param[32];
    };
    u8 parm_priv[32];
    u32 ota_addr;
    u16 ext_arg_len;
    u16 ext_arg_crc;
} UPDATA_PARM;

struct RcspModel;

extern const char *bt_get_local_name(void);
extern void bt_rcsp_interface_init(const uint8_t *profile);
extern void bt_rcsp_interface_exit(void);
extern void rcsp_init(void);
extern void rcsp_bt_ble_init(void);
extern void rcsp_bt_ble_adv_enable(u8 enable);
extern void ble_app_disconnect(void);
extern void rcsp_bt_ble_exit(void);
extern struct RcspModel *rcsp_handle_get(void);
extern u32 ex_cfg_fill_content_api(void);
extern void cpu_reset(void);
extern void update_mode_api_v2(
    UPDATA_TYPE type,
    void (*priv_param_fill_hdl)(UPDATA_PARM *p),
    void (*priv_update_jump_handle)(int type));
#else
#include <asm/cpu.h>
#include <ble_rcsp_server.h>
#include <btstack_rcsp_user.h>
#include <custom_cfg.h>
#include <rcsp.h>
#include <rcsp_config.h>
#include <update.h>

#if !defined(BT_AI_SEL_PROTOCOL) || !defined(RCSP_MODE_EN) || \
    !(BT_AI_SEL_PROTOCOL & RCSP_MODE_EN)
#error "E87 RCSP target needs the pinned RCSP protocol module"
#endif
#if !defined(RCSP_MODE) || !RCSP_MODE
#error "E87 RCSP target needs an enabled RCSP device mode"
#endif
#if !defined(RCSP_CHANNEL_SEL) || !defined(RCSP_USE_BLE) || \
    RCSP_CHANNEL_SEL != RCSP_USE_BLE
#error "E87 RCSP target needs the BLE-only RCSP channel"
#endif
#if !defined(TCFG_USER_BLE_ENABLE) || !TCFG_USER_BLE_ENABLE
#error "E87 RCSP target needs the BLE controller/host transport"
#endif
#if !defined(TCFG_UPDATE_ENABLE) || !TCFG_UPDATE_ENABLE || \
    !defined(TCFG_APP_UPDATE_EN) || !TCFG_APP_UPDATE_EN
#error "E87 RCSP target needs the application update module"
#endif
#if !defined(RCSP_UPDATE_EN) || !RCSP_UPDATE_EN
#error "E87 RCSP target needs the RCSP update command path"
#endif
#if !defined(RCSP_BLE_MASTER) || RCSP_BLE_MASTER
#error "E87 RCSP target needs the peripheral/server RCSP role"
#endif
#if (defined(TCFG_USER_BT_CLASSIC_ENABLE) && \
     TCFG_USER_BT_CLASSIC_ENABLE) || \
    (defined(TCFG_USER_TWS_ENABLE) && TCFG_USER_TWS_ENABLE)
#error "E87 RCSP target forbids classic Bluetooth and TWS"
#endif
#if !defined(TCFG_BT_SUPPORT_SPP) || TCFG_BT_SUPPORT_SPP
#error "E87 RCSP target needs SPP support disabled"
#endif
#if !defined(OTA_TWS_SAME_TIME_ENABLE) || OTA_TWS_SAME_TIME_ENABLE || \
    !defined(TCFG_RCSP_DUAL_CONN_ENABLE) || \
    TCFG_RCSP_DUAL_CONN_ENABLE || \
    !defined(RCSP_BLE_CLIENT_EN) || RCSP_BLE_CLIENT_EN
#error "E87 RCSP target forbids TWS update, dual connection, and BLE client"
#endif
#if !defined(TCFG_UI_ENABLE) || TCFG_UI_ENABLE || \
    !defined(CONFIG_JL_UI_ENABLE) || CONFIG_JL_UI_ENABLE
#error "E87 RCSP target forbids stock UI"
#endif
#if !defined(RCSP_FILE_OPT) || RCSP_FILE_OPT || \
    !defined(TCFG_BS_DEV_PATH_EN) || TCFG_BS_DEV_PATH_EN || \
    !defined(WATCH_FILE_TO_FLASH) || WATCH_FILE_TO_FLASH || \
    !defined(JL_RCSP_EXTRA_FLASH_OPT) || JL_RCSP_EXTRA_FLASH_OPT
#error "E87 RCSP target forbids file, browser, and extra-flash features"
#endif
#if !defined(JL_RCSP_SENSORS_DATA_OPT) || \
    JL_RCSP_SENSORS_DATA_OPT || \
    !defined(RCSP_APP_RTC_EN) || RCSP_APP_RTC_EN
#error "E87 RCSP target forbids sensor and RTC features"
#endif
#endif

static bool target_is_bound(
    const struct e87_rcsp_target *target,
    const struct e87_maintenance *maintenance)
{
    return target != NULL && maintenance != NULL &&
           target->private_initialized &&
           target->private_maintenance == maintenance &&
           target->private_adapter.private_initialized;
}

static bool target_interface_init(
    void *context,
    const uint8_t *profile,
    const char *local_name)
{
    struct e87_rcsp_target *target =
        (struct e87_rcsp_target *)context;
    const char *configured_name;

    if (target == NULL || !target->private_initialized ||
        profile != e87_rcsp_profile || local_name == NULL ||
        strcmp(local_name, e87_rcsp_local_name) != 0) {
        return false;
    }
    configured_name = bt_get_local_name();
    if (configured_name == NULL ||
        strcmp(configured_name, e87_rcsp_local_name) != 0) {
        return false;
    }
    bt_rcsp_interface_init(profile);
    return true;
}

static bool target_rcsp_init(void *context)
{
    const struct e87_rcsp_target *target =
        (const struct e87_rcsp_target *)context;

    if (target == NULL || !target->private_initialized) {
        return false;
    }
    rcsp_init();
    return rcsp_handle_get() != NULL;
}

static bool target_ble_init(void *context)
{
    const struct e87_rcsp_target *target =
        (const struct e87_rcsp_target *)context;

    if (target == NULL || !target->private_initialized) {
        return false;
    }
    rcsp_bt_ble_init();
    return true;
}

static bool target_reject_commands(void *context)
{
    struct e87_rcsp_target *target =
        (struct e87_rcsp_target *)context;

    if (target == NULL || !target->private_initialized) {
        return false;
    }
    target->private_commands_allowed = false;
    return true;
}

static bool target_stop_advertising(void *context)
{
    const struct e87_rcsp_target *target =
        (const struct e87_rcsp_target *)context;

    if (target == NULL || !target->private_initialized ||
        target->private_commands_allowed) {
        return false;
    }
    rcsp_bt_ble_adv_enable((u8)0);
    return true;
}

static bool target_disconnect(void *context)
{
    const struct e87_rcsp_target *target =
        (const struct e87_rcsp_target *)context;

    if (target == NULL || !target->private_initialized ||
        target->private_commands_allowed) {
        return false;
    }
    ble_app_disconnect();
    return true;
}

static bool target_ble_exit(void *context)
{
    const struct e87_rcsp_target *target =
        (const struct e87_rcsp_target *)context;

    if (target == NULL || !target->private_initialized ||
        target->private_commands_allowed) {
        return false;
    }
    rcsp_bt_ble_exit();
    return true;
}

static void *target_handle_get(void *context)
{
    const struct e87_rcsp_target *target =
        (const struct e87_rcsp_target *)context;

    if (target == NULL || !target->private_initialized) {
        return (void *)1;
    }
    return (void *)rcsp_handle_get();
}

static bool target_interface_exit(void *context)
{
    const struct e87_rcsp_target *target =
        (const struct e87_rcsp_target *)context;

    if (target == NULL || !target->private_initialized ||
        target->private_commands_allowed || rcsp_handle_get() != NULL) {
        return false;
    }
    bt_rcsp_interface_exit();
    return true;
}

static bool target_request_normal_mode(void *context)
{
    struct e87_rcsp_target *target =
        (struct e87_rcsp_target *)context;

    if (target == NULL || !target->private_initialized ||
        target->private_commands_allowed) {
        return false;
    }
    target->private_normal_mode_requested = true;
    return true;
}

static bool target_approve_update_start(
    void *context,
    uint32_t loader_saddr)
{
    struct e87_rcsp_target *target =
        (struct e87_rcsp_target *)context;

    if (target == NULL || !target->private_initialized ||
        !target->private_commands_allowed ||
        target->private_update_armed || target->private_update_started ||
        loader_saddr == UINT32_C(0)) {
        return false;
    }
    target->private_loader_saddr = loader_saddr;
    target->private_update_armed = true;
    return true;
}

static struct e87_rcsp_target_api target_api(
    struct e87_rcsp_target *target)
{
    const struct e87_rcsp_target_api api = {
        target,
        target_interface_init,
        target_rcsp_init,
        target_ble_init,
        target_reject_commands,
        target_stop_advertising,
        target_disconnect,
        target_ble_exit,
        target_handle_get,
        target_interface_exit,
        target_request_normal_mode,
        target_approve_update_start
    };

    return api;
}

static enum e87_maintenance_result step_event(
    struct e87_maintenance *maintenance,
    enum e87_maintenance_event_type type,
    uint32_t now_ms)
{
    const struct e87_maintenance_event event = {
        type, now_ms, {0}, false
    };

    return e87_maintenance_step(maintenance, &event);
}

static enum e87_maintenance_result finish_exit_start(
    struct e87_maintenance *maintenance,
    enum e87_maintenance_result result,
    uint32_t now_ms)
{
    if (result != E87_MAINTENANCE_RESULT_EXITING) {
        return result;
    }
    return step_event(maintenance,
                      E87_MAINTENANCE_EVENT_TRANSPORT_QUIESCED,
                      now_ms);
}

static void target_private_param_fill(UPDATA_PARM *parameter)
{
    const u32 exif_address = ex_cfg_fill_content_api();

    if (parameter != NULL) {
        memcpy(parameter->parm_priv, &exif_address,
               sizeof(exif_address));
    }
}

static void target_before_update_jump(int type)
{
    (void)type;
#if !defined(E87_HOST_TEST) && defined(CONFIG_UPDATE_JUMP_TO_MASK) && \
    CONFIG_UPDATE_JUMP_TO_MASK
    extern void latch_reset(void);
    latch_reset();
#else
    cpu_reset();
#endif
}

bool e87_rcsp_target_init(
    struct e87_rcsp_target *target,
    struct e87_maintenance *maintenance,
    uint32_t now_ms)
{
    struct e87_rcsp_target initialized = {0};
    struct e87_rcsp_target_api api;
    const char *configured_name;
    enum e87_maintenance_result result;

    if (target == NULL || maintenance == NULL ||
        (void *)target == (void *)maintenance) {
        return false;
    }
    configured_name = bt_get_local_name();
    if (configured_name == NULL ||
        strcmp(configured_name, e87_rcsp_local_name) != 0) {
        return false;
    }
    initialized.private_maintenance = maintenance;
    initialized.private_initialized = true;
    initialized.private_commands_allowed = true;
    *target = initialized;
    api = target_api(target);
    if (!e87_rcsp_target_maintenance_init(
            &target->private_adapter, &api, maintenance)) {
        memset(target, 0, sizeof(*target));
        return false;
    }
    result = step_event(
        maintenance,
        E87_MAINTENANCE_EVENT_ENTER_AFTER_NORMAL_DISCONNECT,
        now_ms);
    if (result == E87_MAINTENANCE_RESULT_ACTIVE) {
        return true;
    }
    result = e87_rcsp_target_exit(target, maintenance, now_ms);
    if (result == E87_MAINTENANCE_RESULT_WAITING_FOR_RCSP_RELEASE) {
        (void)e87_rcsp_target_poll_release(
            &target->private_adapter, maintenance, now_ms);
    }
    return false;
}

enum e87_maintenance_result e87_rcsp_target_poll(
    struct e87_rcsp_target *target,
    struct e87_maintenance *maintenance,
    uint32_t now_ms)
{
    struct e87_maintenance_view view;
    enum e87_maintenance_result result;

    if (!target_is_bound(target, maintenance) ||
        !e87_maintenance_get_view(maintenance, &view)) {
        return E87_MAINTENANCE_RESULT_ERROR;
    }
    if (target->private_update_armed && !target->private_update_started) {
        target->private_commands_allowed = false;
        if (target->private_loader_saddr == UINT32_C(0)) {
            return E87_MAINTENANCE_RESULT_ERROR;
        }
        result = e87_rcsp_commit_official_handoff(maintenance);
        if (result != E87_MAINTENANCE_RESULT_HANDOFF_COMMITTED) {
            target->private_update_armed = false;
            return result;
        }
        target->private_update_started = true;
        update_mode_api_v2(BLE_APP_UPDATA,
                           target_private_param_fill,
                           target_before_update_jump);
        return result;
    }
    switch (view.state) {
    case E87_MAINTENANCE_STATE_ACTIVE:
    case E87_MAINTENANCE_STATE_HANDOFF_APPROVED:
        result = step_event(
            maintenance, E87_MAINTENANCE_EVENT_POLL, now_ms);
        return finish_exit_start(maintenance, result, now_ms);
    case E87_MAINTENANCE_STATE_EXITING:
        return finish_exit_start(
            maintenance, E87_MAINTENANCE_RESULT_EXITING, now_ms);
    case E87_MAINTENANCE_STATE_WAIT_RCSP_RELEASE:
        return e87_rcsp_target_poll_release(
            &target->private_adapter, maintenance, now_ms);
    case E87_MAINTENANCE_STATE_READY:
    case E87_MAINTENANCE_STATE_NORMAL_REQUESTED:
    case E87_MAINTENANCE_STATE_HANDED_OFF:
        return E87_MAINTENANCE_RESULT_NO_CHANGE;
    case E87_MAINTENANCE_STATE_ERROR:
    default:
        return E87_MAINTENANCE_RESULT_ERROR;
    }
}

enum e87_maintenance_result e87_rcsp_target_exit(
    struct e87_rcsp_target *target,
    struct e87_maintenance *maintenance,
    uint32_t now_ms)
{
    struct e87_maintenance_view view;
    enum e87_maintenance_result result;

    if (!target_is_bound(target, maintenance) ||
        !e87_maintenance_get_view(maintenance, &view)) {
        return E87_MAINTENANCE_RESULT_ERROR;
    }
    if (view.state == E87_MAINTENANCE_STATE_WAIT_RCSP_RELEASE) {
        return e87_rcsp_target_poll_release(
            &target->private_adapter, maintenance, now_ms);
    }
    if (view.state == E87_MAINTENANCE_STATE_NORMAL_REQUESTED ||
        view.state == E87_MAINTENANCE_STATE_HANDED_OFF) {
        return E87_MAINTENANCE_RESULT_NO_CHANGE;
    }
    result = step_event(
        maintenance, E87_MAINTENANCE_EVENT_CANCEL, now_ms);
    return finish_exit_start(maintenance, result, now_ms);
}

const void *e87_rcsp_target_profile_handle(
    const struct e87_rcsp_target *target)
{
    if (target == NULL || !target->private_initialized ||
        target->private_normal_mode_requested ||
        target->private_update_started) {
        return NULL;
    }
    return (const void *)target;
}

bool e87_rcsp_target_commands_allowed(
    const struct e87_rcsp_target *target)
{
    return target != NULL && target->private_initialized &&
           target->private_commands_allowed &&
           !target->private_update_started;
}

bool e87_rcsp_target_normal_mode_requested(
    const struct e87_rcsp_target *target)
{
    return target != NULL && target->private_initialized &&
           target->private_normal_mode_requested;
}
