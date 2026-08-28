#include "app_config.h"
#include "e87/e87_stage0_adv.h"
#include "e87/e87_stage0_app.h"

#include "btstack/btstack_typedef.h"
#include "btstack/le/ble_api.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifndef E87_STAGE0_BUILD_TAG_HEX
#error "E87_STAGE0_BUILD_TAG_HEX is required"
#endif

#if E87_STAGE0_BUILD_TAG_HEX > 0xFFFFFFFFu
#error "E87_STAGE0_BUILD_TAG_HEX must fit in 32 bits"
#endif

#if BT_BTSTACK_LE_ADV != 2
#error "The pinned SDK must define BT_BTSTACK_LE_ADV as 2"
#endif

const int config_stack_modules = BT_BTSTACK_LE_ADV;

static bool initialization_attempted;
static uint8_t advertisement[29];

void bt_ble_init(void)
{
    const uint8_t *random_address;
    size_t advertisement_length = 0U;
    size_t scan_response_length = 0U;
    const uint8_t *scan_response;

    if (initialization_attempted) {
        return;
    }
    initialization_attempted = true;
    random_address = e87_stage0_app_random_address();
    if (random_address == NULL ||
        le_controller_set_random_mac((void *)random_address) != 0) {
        return;
    }
    if (!e87_stage0_adv_build((uint64_t)E87_STAGE0_BUILD_TAG_HEX,
                              advertisement, sizeof(advertisement),
                              &advertisement_length) ||
        advertisement_length != E87_STAGE0_ADV_DATA_LENGTH) {
        return;
    }
    scan_response = e87_stage0_scan_response(&scan_response_length);
    if (scan_response == NULL || scan_response_length != 0U) {
        return;
    }
    if (ble_user_cmd_prepare(BLE_CMD_SET_HCI_CFG, 2,
                             HCI_CFG_OWN_ADDRESS_TYPE,
                             E87_STAGE0_OWN_ADDRESS_TYPE_RANDOM) !=
        BLE_CMD_RET_SUCESS) {
        return;
    }
    if (ble_user_cmd_prepare(BLE_CMD_ADV_PARAM, 3,
                             E87_STAGE0_ADV_INTERVAL_UNITS,
                             E87_STAGE0_ADV_TYPE_NONCONN_IND,
                             E87_STAGE0_ADV_CHANNEL_MAP) !=
        BLE_CMD_RET_SUCESS) {
        return;
    }
    if (ble_user_cmd_prepare(BLE_CMD_ADV_DATA, 2,
                             E87_STAGE0_ADV_DATA_LENGTH,
                             advertisement) != BLE_CMD_RET_SUCESS) {
        return;
    }
    if (ble_user_cmd_prepare(BLE_CMD_RSP_DATA, 2,
                             scan_response_length,
                             scan_response) != BLE_CMD_RET_SUCESS) {
        return;
    }
    if (ble_user_cmd_prepare(BLE_CMD_ADV_ENABLE, 1, 1) !=
        BLE_CMD_RET_SUCESS) {
        return;
    }
}
