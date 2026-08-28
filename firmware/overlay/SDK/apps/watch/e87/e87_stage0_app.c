#include "app_config.h"
#include "app_msg.h"
#include "e87/e87_stage0_adv.h"
#include "e87/e87_stage0_app.h"
#include "system/includes.h"

#include "btstack/btstack_task.h"
#include "btctrler/btcontroller_modules.h"
#include "driver/clock.h"
#include "driver/device/tzflash_api.h"

#include <stddef.h>
#include <stdint.h>

enum {
    E87_STAGE0_PRIVATE_STACK_READY = Q_MSG + 0x3E,
};

static uint8_t random_address[E87_STAGE0_RANDOM_ADDRESS_LENGTH];
static bool random_address_ready;
static bool stack_ready_posted;

extern void bt_ble_init(void);

bool e87_stage0_app_start(void)
{
    uint32_t system_clock = clk_get("sys");
    uint8_t *uuid;

    if (system_clock == 0U) {
        return false;
    }
    bt_pll_para(TCFG_CLOCK_OSC_HZ, system_clock, 0, 0);
    uuid = tzflash_get_uuid();
    if (uuid == NULL) {
        return false;
    }
    if (!e87_stage0_derive_static_random_address(uuid, random_address)) {
        return false;
    }
    random_address_ready = true;
    btstack_init();
    return true;
}

const uint8_t *e87_stage0_app_random_address(void)
{
    return random_address_ready ? random_address : NULL;
}

void bt_event_update_to_user(uint8_t *address,
                             uint32_t type,
                             uint8_t event,
                             uint32_t value)
{
    if (stack_ready_posted || address != NULL ||
        type != UINT32_C(0x434F4E00) || event != UINT8_C(3) ||
        value != UINT32_C(50)) {
        return;
    }
    stack_ready_posted = true;
    (void)os_taskq_post_type("app_core", E87_STAGE0_PRIVATE_STACK_READY,
                             0, NULL);
}

void e87_stage0_app_dispatch_forever(void)
{
    int message[8];
    bool ready_consumed = false;

    for (;;) {
        int result = os_taskq_pend(NULL, message,
                                   sizeof(message) / sizeof(message[0]));

        if (result != OS_TASKQ || !(message[0] & Q_MSG)) {
            continue;
        }
        if (message[0] == E87_STAGE0_PRIVATE_STACK_READY && !ready_consumed) {
            ready_consumed = true;
            bt_ble_init();
        }
    }
}
