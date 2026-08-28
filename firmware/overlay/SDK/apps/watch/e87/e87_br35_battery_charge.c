#include "e87/e87_br35_battery_charge.h"

#include "e87/e87_battery.h"
#include "e87/e87_battery_sampler.h"
#include "e87/e87_charge_adapter.h"
#include "e87/e87_charge_bridge.h"

#include "app_config.h"
#include "asm/charge.h"
#include "asm/cpu.h"
#include "asm/hwi.h"
#include "gpadc.h"
#include "gpio.h"
#include "power/power_wakeup.h"
#include "system/os/os_api.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define E87_COMPILER_BARRIER() __asm__ volatile("" ::: "memory")
#define E87_CHARGE_DISPATCHER_TASK "e87_charge"
#define E87_CHARGE_WAKE_TYPE ((int)E87_CHARGE_BRIDGE_WAKE_TOKEN)
#define E87_CHARGE_WAKE_QUEUE_BYTES ((int)sizeof(int))
#define E87_CHARGE_POLL_MAX_TICKS 10
#define E87_CHARGE_DISPATCHER_PRIORITY 15
#define E87_CHARGE_DISPATCHER_STACK_WORDS 512

_Static_assert(CPU_CORE_NUM == 1, "E87 bridge requires one BR35 core");
_Static_assert(CPU_INT_NESTING == 2,
               "E87 bridge requires the pinned BR35 nesting model");
_Static_assert(sizeof(int) == 4, "E87 wake queue stores one 32-bit int");
_Static_assert(AD_CH_PMU_VBAT_DIV == E87_BATTERY_QUARTER_DIVISOR,
               "E87 battery sampler requires the quarter-VBAT alias");

static struct e87_charge_bridge e87_br35_charge_bridge;
static struct charge_platform_data e87_charge_platform_data;
static bool e87_battery_initialized;
static bool e87_charge_prepared;
static bool e87_charge_dispatcher_started;
static bool e87_charge_initialized;

static int e87_irq_save(void *context)
{
    int saved;

    (void)context;
    E87_COMPILER_BARRIER();
    saved = int_cli();
    E87_COMPILER_BARRIER();
    return saved;
}

static void e87_irq_restore(void *context, int saved)
{
    (void)context;
    E87_COMPILER_BARRIER();
    int_sti(saved);
    E87_COMPILER_BARRIER();
}

static uint8_t e87_read_driver_online(void *context)
{
    (void)context;
    return get_charge_online_flag();
}

static int e87_post_wake(void *context)
{
    (void)context;
    return os_taskq_post_type(E87_CHARGE_DISPATCHER_TASK,
                              E87_CHARGE_WAKE_TYPE, 0, NULL);
}

static bool e87_in_irq(void *context)
{
    (void)context;
    return cpu_in_irq() != 0;
}

static bool e87_irq_disabled(void *context)
{
    (void)context;
    return cpu_irq_disabled() != 0;
}

static const struct e87_charge_bridge_port e87_br35_charge_bridge_port = {
    .context = NULL,
    .critical_enter = e87_irq_save,
    .critical_exit = e87_irq_restore,
    .read_driver_online = e87_read_driver_online,
    .post_wake = e87_post_wake,
    .in_irq = e87_in_irq,
    .irq_disabled = e87_irq_disabled,
};

static uint32_t e87_read_quarter_mv(void *context)
{
    (void)context;
    return adc_get_voltage_blocking(AD_CH_PMU_VBAT);
}

static const struct e87_battery_sampler_port e87_br35_battery_port = {
    .context = NULL,
    .read_quarter_mv = e87_read_quarter_mv,
};

static void e87_charge_wakeup_callback(P33_IO_WKUP_EDGE edge)
{
    (void)edge;
    ldoin_wakeup_isr();
}

static const struct _p33_io_wakeup_config e87_vbat_wakeup = {
    .gpio = IO_VBTCH_DET,
    .filter = PORT_FLT_16ms,
    .edge = BOTH_EDGE,
    .callback = e87_charge_wakeup_callback,
};

static const struct _p33_io_wakeup_config e87_ldoin_wakeup = {
    .gpio = IO_LDOIN_DET,
    .filter = PORT_FLT_16ms,
    .edge = BOTH_EDGE,
    .callback = e87_charge_wakeup_callback,
};

static void e87_charge_wakeup_init(void)
{
    p33_io_wakeup_port_init(&e87_vbat_wakeup);
    p33_io_wakeup_enable(IO_VBTCH_DET, 1);
    p33_io_wakeup_port_init(&e87_ldoin_wakeup);
    p33_io_wakeup_enable(IO_LDOIN_DET, 1);
}

static void e87_br35_charge_dispatcher_run(void *argument)
{
    int wake_words[1] = {0};

    (void)argument;
    while (1) {
        int wait_result;

        (void)e87_charge_bridge_poll_app(&e87_br35_charge_bridge);
        wait_result = os_taskq_pend_timeout(NULL, wake_words, 1, E87_CHARGE_POLL_MAX_TICKS);
        if (wait_result == OS_TASKQ) {
            if (wake_words[0] == E87_CHARGE_WAKE_TYPE) {
                (void)e87_charge_bridge_ack_wake(
                    &e87_br35_charge_bridge,
                    E87_CHARGE_BRIDGE_WAKE_TOKEN);
            } else {
                (void)e87_charge_bridge_note_queue_fault(
                    &e87_br35_charge_bridge);
            }
        } else if (wait_result != OS_TIMEOUT) {
            (void)e87_charge_bridge_note_queue_fault(
                &e87_br35_charge_bridge);
        }
        (void)e87_charge_bridge_poll_app(&e87_br35_charge_bridge);
    }
}

static bool e87_br35_charge_dispatcher_start(void)
{
    const int result = os_task_create(
        e87_br35_charge_dispatcher_run,
        NULL,
        E87_CHARGE_DISPATCHER_PRIORITY,
        E87_CHARGE_DISPATCHER_STACK_WORDS,
        E87_CHARGE_WAKE_QUEUE_BYTES,
        E87_CHARGE_DISPATCHER_TASK);

    if (result != OS_NO_ERR) {
        return false;
    }
    e87_charge_dispatcher_started = true;
    return true;
}

bool e87_br35_battery_init(void)
{
    if (e87_battery_initialized) {
        return false;
    }
    adc_init();
    e87_battery_initialized = true;
    return true;
}

bool e87_br35_battery_sample_full_mv(uint32_t *out_full_mv)
{
    if (!e87_battery_initialized) {
        return false;
    }
    return e87_battery_sampler_sample_full_mv(
        &e87_br35_battery_port, out_full_mv);
}

bool e87_br35_charge_prepare(struct e87_charge_adapter *adapter)
{
    enum e87_charge_bridge_poll_result poll_result;

    if (adapter == NULL || e87_charge_prepared ||
        e87_charge_dispatcher_started) {
        return false;
    }
    if (!e87_charge_bridge_init(&e87_br35_charge_bridge,
                                adapter,
                                &e87_br35_charge_bridge_port)) {
        return false;
    }
    poll_result = e87_charge_bridge_poll_app(&e87_br35_charge_bridge);
    if (poll_result == E87_CHARGE_BRIDGE_POLL_ERROR ||
        poll_result == E87_CHARGE_BRIDGE_POLL_TERMINAL) {
        return false;
    }
    if (!e87_br35_charge_dispatcher_start()) {
        return false;
    }
    e87_charge_prepared = true;
    return true;
}

bool e87_br35_charge_hw_init(
    const struct charge_platform_data *platform_data)
{
    int result;

    if (platform_data == NULL || e87_charge_initialized ||
        !e87_charge_prepared || !e87_battery_initialized ||
        !e87_charge_bridge_is_ready(&e87_br35_charge_bridge) ||
        !e87_charge_dispatcher_started) {
        return false;
    }
    e87_charge_wakeup_init();
    e87_charge_platform_data = *platform_data;
    e87_charge_initialized = true;
    result = charge_init(&e87_charge_platform_data);
    if (result != 0) {
        return false;
    }
    set_charge_event_flag(1);
    return true;
}

void charge_event_to_user(u8 event)
{
    enum e87_charge_event local_event;

    switch (event) {
    case CHARGE_EVENT_CHARGE_START:
        local_event = E87_CHARGE_EVENT_CHARGE_START;
        break;
    case CHARGE_EVENT_CHARGE_CLOSE:
        local_event = E87_CHARGE_EVENT_CHARGE_CLOSE;
        break;
    case CHARGE_EVENT_CHARGE_FULL:
        local_event = E87_CHARGE_EVENT_CHARGE_FULL;
        break;
    case CHARGE_EVENT_LDO5V_KEEP:
        local_event = E87_CHARGE_EVENT_LDO5V_KEEP;
        break;
    case CHARGE_EVENT_LDO5V_IN:
        local_event = E87_CHARGE_EVENT_LDO5V_IN;
        break;
    case CHARGE_EVENT_LDO5V_OFF:
        local_event = E87_CHARGE_EVENT_LDO5V_OFF;
        break;
    default:
        local_event = E87_CHARGE_EVENT_UNSUPPORTED;
        break;
    }
    (void)e87_charge_bridge_capture(&e87_br35_charge_bridge, local_event);
}
