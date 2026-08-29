#include "app_config.h"
#include "e87/e87_app.h"
#include "e87/e87_app_runtime.h"
#include "e87/e87_ble_target.h"
#include "system/includes.h"

static struct e87_app_runtime e87_runtime;
static volatile uint32_t e87_runtime_now_ms;

static int e87_critical_enter(void *context)
{
    (void)context;
    local_irq_disable();
    return 0;
}

static void e87_critical_exit(void *context, int saved)
{
    (void)context;
    (void)saved;
    local_irq_enable();
}

static uint32_t e87_now_ms(void *context)
{
    (void)context;
    return e87_runtime_now_ms;
}

static bool e87_poll_ble(void *context)
{
    (void)context;
    return e87_ble_target_poll();
}

static bool e87_epoch_active(void *context, uint32_t epoch)
{
    (void)context;
    return e87_ble_target_authorization_epoch_is_active(epoch);
}

static bool e87_emit_effect(void *context, struct e87_app_core_effect *effect)
{
    uint32_t ignored_epoch;
    (void)context;
    if (effect == NULL) {
        return false;
    }
    if (effect->type == E87_APP_CORE_EFFECT_BLE_SET_WRITES) {
        return e87_ble_target_set_writes_enabled(
            effect->data.writes.enabled, &ignored_epoch);
    }
    return false;
}

static bool e87_try_enqueue_state(
    void *context, uint32_t epoch,
    const uint8_t packet[E87_BLE_TARGET_STATE_PACKET_SIZE])
{
    return e87_app_runtime_try_enqueue_semantic(context, epoch, packet);
}

bool e87_app_start(void)
{
    const struct e87_app_core_config config = {
        {UINT16_C(100), UINT16_C(10), UINT16_C(20000), UINT16_C(1), UINT16_C(1),
         {UINT16_C(10), UINT16_C(19)}, {UINT16_C(30), UINT16_C(39)},
         {UINT16_C(50), UINT16_C(59)}, {UINT16_C(70), UINT16_C(79)}}
    };
    const struct e87_app_runtime_port port = {
        NULL, e87_critical_enter, e87_critical_exit, e87_now_ms,
        e87_poll_ble, NULL, e87_emit_effect, e87_epoch_active
    };
    const struct e87_ble_target_ingress ingress = {
        &e87_runtime, e87_try_enqueue_state
    };

    if (!e87_app_runtime_init(&e87_runtime, &config, &port) ||
        !e87_ble_target_init(&ingress)) {
        return false;
    }

    return false;
}

void e87_app_dispatch_forever(void)
{
    for (;;) {
        if (!e87_app_runtime_poll(&e87_runtime)) {
            for (;;) {
                os_time_dly(10);
            }
        }
        os_time_dly(1);
        e87_runtime_now_ms += UINT32_C(10);
    }
}
