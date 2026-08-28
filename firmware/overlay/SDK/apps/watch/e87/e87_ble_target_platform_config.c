#include "app_config.h"
#include "btstack/btstack_typedef.h"

#if BT_BTSTACK_LE != 4
#error "The pinned SDK must define BT_BTSTACK_LE as 4"
#endif

#if !TCFG_APP_BT_EN || !TCFG_USER_BLE_ENABLE
#error "The E87 BLE target requires the BLE-only stack"
#endif

#if TCFG_USER_BT_CLASSIC_ENABLE || TCFG_USER_TWS_ENABLE || TCFG_USER_EMITTER_ENABLE
#error "The E87 BLE target excludes Classic, TWS, and emitter roles"
#endif

#if TCFG_BT_AI_ENABLE || BT_AI_SEL_PROTOCOL != 0
#error "The E87 BLE target excludes vendor AI protocols"
#endif

#if RCSP_MODE != RCSP_MODE_OFF
#error "The E87 BLE target excludes RCSP"
#endif

const int config_stack_modules = BT_BTSTACK_LE;
const u8 btstack_emitter_support = 0;
const u8 adt_profile_support = 0;
