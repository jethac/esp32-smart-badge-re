#include "app_config.h"
#include "e87/e87_app.h"
#include "system/includes.h"

bool e87_app_start(void)
{
    return true;
}

void e87_app_dispatch_forever(void)
{
    for (;;) {
        os_time_dly(10);
    }
}
