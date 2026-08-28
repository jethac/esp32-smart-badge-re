#include "app_config.h"
#include "e87/e87_app.h"
#include "e87/e87_lab_smoke.h"
#include "e87/e87_panel.h"
#include "system/includes.h"

static struct e87_lab_smoke e87_smoke;

bool e87_app_start(void)
{
    const struct e87_panel_io *io = e87_panel_jd9855_sdk_io();

    return e87_lab_smoke_start(&e87_smoke, io, sys_timer_get_ms()) ==
           E87_LAB_SMOKE_OK;
}

void e87_app_dispatch_forever(void)
{
    for (;;) {
        wdt_clear();
        (void)e87_lab_smoke_step(&e87_smoke, sys_timer_get_ms());
        os_time_dly(1);
    }
}
