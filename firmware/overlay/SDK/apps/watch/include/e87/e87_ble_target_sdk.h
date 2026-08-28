#ifndef E87_BLE_TARGET_SDK_H
#define E87_BLE_TARGET_SDK_H

#ifdef E87_HOST_TEST
#include "e87_br35_sdk.h"
#else
#include <app_config.h>
#include <system/includes.h>
#include <btstack/bluetooth.h>
#include <btstack/third_party/common/app_ble_spp_api.h>
#include <utils/syscfg_id.h>
#endif

#endif
