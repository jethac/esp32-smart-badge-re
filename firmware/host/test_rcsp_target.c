#include "test_support.h"
#include "e87/e87_maintenance.h"
#include "e87/e87_rcsp_target.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define SDK_CALL_CAPACITY 64U

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

struct RcspModel {
    uint32_t sentinel;
};

enum fake_sdk_call {
    SDK_CALL_INTERFACE_INIT = 0,
    SDK_CALL_RCSP_INIT = 1,
    SDK_CALL_BLE_INIT = 2,
    SDK_CALL_STOP_ADV = 3,
    SDK_CALL_DISCONNECT = 4,
    SDK_CALL_BLE_EXIT = 5,
    SDK_CALL_HANDLE_GET = 6,
    SDK_CALL_INTERFACE_EXIT = 7,
    SDK_CALL_UPDATE_MODE = 8,
    SDK_CALL_CPU_RESET = 9,
};

struct fake_sdk {
    enum fake_sdk_call calls[SDK_CALL_CAPACITY];
    size_t count;
    const char *local_name;
    const uint8_t *profile;
    u8 adv_enable;
    struct RcspModel *handle;
    struct e87_rcsp_target *active_target;
    UPDATA_TYPE update_type;
    void (*param_fill)(UPDATA_PARM *p);
    void (*before_jump)(int type);
    UPDATA_PARM filled_param;
    bool commands_allowed_at_update;
    bool rcsp_init_has_handle;
};

static struct fake_sdk sdk;
static struct RcspModel present_handle = {UINT32_C(0xE8700001)};

static void record_call(enum fake_sdk_call call)
{
    if (sdk.count < SDK_CALL_CAPACITY) {
        sdk.calls[sdk.count] = call;
        sdk.count += 1U;
    }
}

static void reset_sdk(void)
{
    memset(&sdk, 0, sizeof(sdk));
    sdk.local_name = "E87 UPDATE";
    sdk.rcsp_init_has_handle = true;
}

const char *bt_get_local_name(void)
{
    return sdk.local_name;
}

void bt_rcsp_interface_init(const uint8_t *profile)
{
    sdk.profile = profile;
    record_call(SDK_CALL_INTERFACE_INIT);
}

void bt_rcsp_interface_exit(void)
{
    record_call(SDK_CALL_INTERFACE_EXIT);
}

void rcsp_init(void)
{
    record_call(SDK_CALL_RCSP_INIT);
    sdk.handle = sdk.rcsp_init_has_handle ? &present_handle : NULL;
}

void rcsp_bt_ble_init(void)
{
    record_call(SDK_CALL_BLE_INIT);
}

void rcsp_bt_ble_adv_enable(u8 enable)
{
    sdk.adv_enable = enable;
    record_call(SDK_CALL_STOP_ADV);
}

void ble_app_disconnect(void)
{
    record_call(SDK_CALL_DISCONNECT);
}

void rcsp_bt_ble_exit(void)
{
    record_call(SDK_CALL_BLE_EXIT);
}

struct RcspModel *rcsp_handle_get(void)
{
    record_call(SDK_CALL_HANDLE_GET);
    return sdk.handle;
}

u32 ex_cfg_fill_content_api(void)
{
    return UINT32_C(0x1234ABCD);
}

void cpu_reset(void)
{
    record_call(SDK_CALL_CPU_RESET);
}

void update_mode_api_v2(
    UPDATA_TYPE type,
    void (*priv_param_fill_hdl)(UPDATA_PARM *p),
    void (*priv_update_jump_handle)(int type))
{
    memset(&sdk.filled_param, 0, sizeof(sdk.filled_param));
    sdk.update_type = type;
    sdk.param_fill = priv_param_fill_hdl;
    sdk.before_jump = priv_update_jump_handle;
    sdk.commands_allowed_at_update =
        e87_rcsp_target_commands_allowed(sdk.active_target);
    record_call(SDK_CALL_UPDATE_MODE);
    if (priv_param_fill_hdl != NULL) {
        priv_param_fill_hdl(&sdk.filled_param);
    }
    if (priv_update_jump_handle != NULL) {
        priv_update_jump_handle((int)type);
    }
}

static bool bytes_equal(const void *left, const void *right, size_t length)
{
    return memcmp(left, right, length) == 0;
}

static size_t call_occurrences(enum fake_sdk_call call)
{
    size_t count = 0U;
    size_t index;

    for (index = 0U; index < sdk.count; index += 1U) {
        if (sdk.calls[index] == call) {
            count += 1U;
        }
    }
    return count;
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
    bool board_voltage_stable)
{
    struct e87_maintenance_event event =
        event_at(E87_MAINTENANCE_EVENT_POWER_SAMPLE, now_ms);

    event.power.percent = percent;
    event.power.low_voltage_warning = low_voltage_warning;
    event.power.board_voltage_stable = board_voltage_stable;
    event.power.external_power_online = false;
    event.power.charger_phase = E87_CHARGER_PHASE_CLOSE;
    return event;
}

static struct e87_rcsp_official_loader_report valid_loader_report(void)
{
    static const uint8_t profile_id[E87_RCSP_PROFILE_ID_BYTES] = {
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
    memcpy(report.profile_id, profile_id, sizeof(profile_id));
    return report;
}

static bool initialize_target(
    struct e87_rcsp_target *target,
    struct e87_maintenance *maintenance,
    uint32_t now_ms)
{
    reset_sdk();
    sdk.active_target = target;
    return e87_rcsp_target_init(target, maintenance, now_ms);
}

E87_TEST(init_binds_exact_minimal_profile_and_sdk_lifecycle)
{
    struct e87_rcsp_target target;
    struct e87_rcsp_target target_before;
    struct e87_maintenance maintenance;
    struct e87_maintenance maintenance_before;

    memset(&target, 0xA5, sizeof(target));
    memset(&maintenance, 0x5A, sizeof(maintenance));
    target_before = target;
    maintenance_before = maintenance;
    reset_sdk();
    E87_ASSERT_TRUE(!e87_rcsp_target_init(NULL, &maintenance, UINT32_C(0)));
    E87_ASSERT_TRUE(!e87_rcsp_target_init(&target, NULL, UINT32_C(0)));
    E87_ASSERT_TRUE(bytes_equal(&target, &target_before, sizeof(target)));
    E87_ASSERT_TRUE(bytes_equal(
        &maintenance, &maintenance_before, sizeof(maintenance)));
    E87_ASSERT_EQ_U32(UINT32_C(0), sdk.count);

    sdk.local_name = "WRONG";
    E87_ASSERT_TRUE(!e87_rcsp_target_init(
        &target, &maintenance, UINT32_C(0)));
    E87_ASSERT_TRUE(bytes_equal(&target, &target_before, sizeof(target)));
    E87_ASSERT_TRUE(bytes_equal(
        &maintenance, &maintenance_before, sizeof(maintenance)));
    E87_ASSERT_EQ_U32(UINT32_C(0), sdk.count);

    reset_sdk();
    sdk.active_target = &target;
    E87_ASSERT_TRUE(e87_rcsp_target_init(
        &target, &maintenance, UINT32_C(77)));
    E87_ASSERT_EQ_U32(UINT32_C(4), sdk.count);
    E87_ASSERT_EQ_U32(SDK_CALL_INTERFACE_INIT, sdk.calls[0]);
    E87_ASSERT_EQ_U32(SDK_CALL_RCSP_INIT, sdk.calls[1]);
    E87_ASSERT_EQ_U32(SDK_CALL_HANDLE_GET, sdk.calls[2]);
    E87_ASSERT_EQ_U32(SDK_CALL_BLE_INIT, sdk.calls[3]);
    E87_ASSERT_TRUE(sdk.profile == e87_rcsp_profile);
    E87_ASSERT_TRUE(e87_rcsp_target_commands_allowed(&target));
    E87_ASSERT_TRUE(!e87_rcsp_target_normal_mode_requested(&target));

    {
        struct e87_rcsp_target failed_target;
        struct e87_maintenance failed_maintenance;

        reset_sdk();
        sdk.active_target = &failed_target;
        sdk.rcsp_init_has_handle = false;
        E87_ASSERT_TRUE(!e87_rcsp_target_init(
            &failed_target, &failed_maintenance, UINT32_C(88)));
        E87_ASSERT_EQ_U32(UINT32_C(0),
                          call_occurrences(SDK_CALL_BLE_INIT));
        E87_ASSERT_EQ_U32(UINT32_C(1),
                          call_occurrences(SDK_CALL_STOP_ADV));
        E87_ASSERT_EQ_U32(UINT32_C(1),
                          call_occurrences(SDK_CALL_DISCONNECT));
        E87_ASSERT_EQ_U32(UINT32_C(1),
                          call_occurrences(SDK_CALL_BLE_EXIT));
        E87_ASSERT_EQ_U32(UINT32_C(1),
                          call_occurrences(SDK_CALL_INTERFACE_EXIT));
        E87_ASSERT_TRUE(e87_rcsp_target_normal_mode_requested(
            &failed_target));
    }
}

E87_TEST(poll_enforces_exact_120_second_timeout_and_ordered_release)
{
    struct e87_rcsp_target target;
    struct e87_maintenance maintenance;

    E87_ASSERT_TRUE(initialize_target(
        &target, &maintenance, UINT32_C(1000)));
    E87_ASSERT_EQ_U32(
        E87_MAINTENANCE_RESULT_NO_CHANGE,
        e87_rcsp_target_poll(
            &target, &maintenance, UINT32_C(120999)));
    E87_ASSERT_EQ_U32(UINT32_C(4), sdk.count);

    sdk.handle = &present_handle;
    E87_ASSERT_EQ_U32(
        E87_MAINTENANCE_RESULT_WAITING_FOR_RCSP_RELEASE,
        e87_rcsp_target_poll(
            &target, &maintenance, UINT32_C(121000)));
    E87_ASSERT_TRUE(!e87_rcsp_target_commands_allowed(&target));
    E87_ASSERT_EQ_U32(SDK_CALL_STOP_ADV, sdk.calls[4]);
    E87_ASSERT_EQ_U32(UINT32_C(0), sdk.adv_enable);
    E87_ASSERT_EQ_U32(SDK_CALL_DISCONNECT, sdk.calls[5]);
    E87_ASSERT_EQ_U32(SDK_CALL_BLE_EXIT, sdk.calls[6]);
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      call_occurrences(SDK_CALL_INTERFACE_EXIT));

    E87_ASSERT_EQ_U32(
        E87_MAINTENANCE_RESULT_WAITING_FOR_RCSP_RELEASE,
        e87_rcsp_target_poll(
            &target, &maintenance, UINT32_C(121001)));
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      call_occurrences(SDK_CALL_INTERFACE_EXIT));
    sdk.handle = NULL;
    E87_ASSERT_EQ_U32(
        E87_MAINTENANCE_RESULT_NORMAL_REQUESTED,
        e87_rcsp_target_poll(
            &target, &maintenance, UINT32_C(121002)));
    E87_ASSERT_EQ_U32(UINT32_C(1),
                      call_occurrences(SDK_CALL_INTERFACE_EXIT));
    E87_ASSERT_TRUE(e87_rcsp_target_normal_mode_requested(&target));
}

E87_TEST(explicit_exit_rejects_commands_before_transport_teardown)
{
    struct e87_rcsp_target target;
    struct e87_maintenance maintenance;
    const void *profile_handle;
    size_t call_count;

    E87_ASSERT_TRUE(initialize_target(
        &target, &maintenance, UINT32_C(0)));
    profile_handle = e87_rcsp_target_profile_handle(&target);
    E87_ASSERT_TRUE(profile_handle != NULL);
    E87_ASSERT_TRUE(profile_handle ==
                    e87_rcsp_target_profile_handle(&target));
    sdk.handle = &present_handle;
    E87_ASSERT_EQ_U32(
        E87_MAINTENANCE_RESULT_WAITING_FOR_RCSP_RELEASE,
        e87_rcsp_target_exit(
            &target, &maintenance, UINT32_C(1)));
    E87_ASSERT_TRUE(!e87_rcsp_target_commands_allowed(&target));
    E87_ASSERT_EQ_U32(SDK_CALL_STOP_ADV, sdk.calls[4]);
    E87_ASSERT_EQ_U32(SDK_CALL_DISCONNECT, sdk.calls[5]);
    E87_ASSERT_EQ_U32(SDK_CALL_BLE_EXIT, sdk.calls[6]);
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      call_occurrences(SDK_CALL_UPDATE_MODE));

    sdk.handle = NULL;
    E87_ASSERT_EQ_U32(
        E87_MAINTENANCE_RESULT_NORMAL_REQUESTED,
        e87_rcsp_target_exit(
            &target, &maintenance, UINT32_C(2)));
    E87_ASSERT_TRUE(e87_rcsp_target_profile_handle(&target) == NULL);
    E87_ASSERT_EQ_U32(UINT32_C(1),
                      call_occurrences(SDK_CALL_INTERFACE_EXIT));
    call_count = sdk.count;
    E87_ASSERT_EQ_U32(
        E87_MAINTENANCE_RESULT_NO_CHANGE,
        e87_rcsp_target_exit(
            &target, &maintenance, UINT32_C(3)));
    E87_ASSERT_EQ_U32(call_count, sdk.count);
}

E87_TEST(official_handoff_revalidates_gates_then_calls_mode_api_once)
{
    struct e87_rcsp_target target;
    struct e87_maintenance maintenance;
    struct e87_maintenance_event event;
    struct e87_rcsp_official_loader_report report = valid_loader_report();
    const uint32_t expected_private = UINT32_C(0x1234ABCD);
    uint32_t actual_private = 0U;

    E87_ASSERT_TRUE(initialize_target(
        &target, &maintenance, UINT32_C(0)));
    event = event_at(E87_MAINTENANCE_EVENT_AUTHENTICATED, UINT32_C(1));
    E87_ASSERT_EQ_U32(
        E87_MAINTENANCE_RESULT_AUTHENTICATED,
        e87_maintenance_step(&maintenance, &event));
    E87_ASSERT_EQ_U32(
        E87_MAINTENANCE_RESULT_HANDOFF_WAITING,
        e87_rcsp_official_loader_callback(
            &maintenance, UINT32_C(2), &report));
    event = power_at(UINT32_C(2), UINT8_C(50), false, true);
    E87_ASSERT_EQ_U32(
        E87_MAINTENANCE_RESULT_STATUS_UPDATED,
        e87_maintenance_step(&maintenance, &event));
    event.now_ms = UINT32_C(5002);
    E87_ASSERT_EQ_U32(
        E87_MAINTENANCE_RESULT_HANDOFF_REQUESTED,
        e87_maintenance_step(&maintenance, &event));
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      call_occurrences(SDK_CALL_UPDATE_MODE));

    E87_ASSERT_EQ_U32(
        E87_MAINTENANCE_RESULT_HANDOFF_COMMITTED,
        e87_rcsp_target_poll(
            &target, &maintenance, UINT32_C(5002)));
    E87_ASSERT_EQ_U32(UINT32_C(1),
                      call_occurrences(SDK_CALL_UPDATE_MODE));
    E87_ASSERT_EQ_U32(BLE_APP_UPDATA, sdk.update_type);
    E87_ASSERT_TRUE(sdk.param_fill != NULL);
    E87_ASSERT_TRUE(sdk.before_jump != NULL);
    E87_ASSERT_TRUE(!sdk.commands_allowed_at_update);
    memcpy(&actual_private, sdk.filled_param.parm_priv,
           sizeof(actual_private));
    E87_ASSERT_EQ_U32(expected_private, actual_private);
    E87_ASSERT_EQ_U32(UINT32_C(1),
                      call_occurrences(SDK_CALL_CPU_RESET));
    E87_ASSERT_EQ_U32(
        E87_MAINTENANCE_RESULT_NO_CHANGE,
        e87_rcsp_target_poll(
            &target, &maintenance, UINT32_C(5003)));
    E87_ASSERT_EQ_U32(UINT32_C(1),
                      call_occurrences(SDK_CALL_UPDATE_MODE));
}

E87_TEST(zero_loader_or_revalidation_failure_never_calls_mode_api)
{
    {
        struct e87_rcsp_target target;
        struct e87_maintenance maintenance;
        struct e87_maintenance_event event;
        struct e87_rcsp_official_loader_report report = valid_loader_report();

        E87_ASSERT_TRUE(initialize_target(
            &target, &maintenance, UINT32_C(0)));
        event = event_at(
            E87_MAINTENANCE_EVENT_AUTHENTICATED, UINT32_C(1));
        E87_ASSERT_EQ_U32(
            E87_MAINTENANCE_RESULT_AUTHENTICATED,
            e87_maintenance_step(&maintenance, &event));
        report.loader_saddr = UINT32_C(0);
        E87_ASSERT_EQ_U32(
            E87_MAINTENANCE_RESULT_EXITING,
            e87_rcsp_official_loader_callback(
                &maintenance, UINT32_C(2), &report));
        E87_ASSERT_EQ_U32(UINT32_C(0),
                          call_occurrences(SDK_CALL_UPDATE_MODE));
    }

    {
        struct e87_rcsp_target target;
        struct e87_maintenance maintenance;
        struct e87_maintenance_event event;
        struct e87_rcsp_official_loader_report report = valid_loader_report();

        E87_ASSERT_TRUE(initialize_target(
            &target, &maintenance, UINT32_C(0)));
        event = event_at(
            E87_MAINTENANCE_EVENT_AUTHENTICATED, UINT32_C(1));
        E87_ASSERT_EQ_U32(
            E87_MAINTENANCE_RESULT_AUTHENTICATED,
            e87_maintenance_step(&maintenance, &event));
        E87_ASSERT_EQ_U32(
            E87_MAINTENANCE_RESULT_HANDOFF_WAITING,
            e87_rcsp_official_loader_callback(
                &maintenance, UINT32_C(2), &report));
        event = power_at(UINT32_C(2), UINT8_C(50), false, true);
        E87_ASSERT_EQ_U32(
            E87_MAINTENANCE_RESULT_STATUS_UPDATED,
            e87_maintenance_step(&maintenance, &event));
        event.now_ms = UINT32_C(5002);
        E87_ASSERT_EQ_U32(
            E87_MAINTENANCE_RESULT_HANDOFF_REQUESTED,
            e87_maintenance_step(&maintenance, &event));
        maintenance.private_power.percent = UINT8_C(49);
        E87_ASSERT_EQ_U32(
            E87_MAINTENANCE_RESULT_ERROR,
            e87_rcsp_target_poll(
                &target, &maintenance, UINT32_C(5002)));
        E87_ASSERT_EQ_U32(UINT32_C(0),
                          call_occurrences(SDK_CALL_UPDATE_MODE));
        E87_ASSERT_TRUE(!e87_rcsp_target_commands_allowed(&target));
        sdk.handle = &present_handle;
        E87_ASSERT_EQ_U32(
            E87_MAINTENANCE_RESULT_WAITING_FOR_RCSP_RELEASE,
            e87_rcsp_target_poll(
                &target, &maintenance, UINT32_C(5003)));
        E87_ASSERT_EQ_U32(UINT32_C(1),
                          call_occurrences(SDK_CALL_STOP_ADV));
        E87_ASSERT_EQ_U32(UINT32_C(1),
                          call_occurrences(SDK_CALL_DISCONNECT));
        E87_ASSERT_EQ_U32(UINT32_C(1),
                          call_occurrences(SDK_CALL_BLE_EXIT));
        sdk.handle = NULL;
        E87_ASSERT_EQ_U32(
            E87_MAINTENANCE_RESULT_NORMAL_REQUESTED,
            e87_rcsp_target_poll(
                &target, &maintenance, UINT32_C(5004)));
        E87_ASSERT_EQ_U32(UINT32_C(1),
                          call_occurrences(SDK_CALL_INTERFACE_EXIT));
    }
}

static const struct e87_test_case target_cases[] = {
    E87_TEST_CASE(init_binds_exact_minimal_profile_and_sdk_lifecycle),
    E87_TEST_CASE(poll_enforces_exact_120_second_timeout_and_ordered_release),
    E87_TEST_CASE(explicit_exit_rejects_commands_before_transport_teardown),
    E87_TEST_CASE(official_handoff_revalidates_gates_then_calls_mode_api_once),
    E87_TEST_CASE(zero_loader_or_revalidation_failure_never_calls_mode_api),
};

const struct e87_test_suite e87_test_suite = {
    "rcsp-target-binding",
    target_cases,
    sizeof(target_cases) / sizeof(target_cases[0])
};
