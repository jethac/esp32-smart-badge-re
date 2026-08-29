#ifndef E87_APP_H
#define E87_APP_H

#include <stdbool.h>

#include "e87/e87_app_target.h"

bool e87_app_configure_boot_port(
    const struct e87_app_target_boot_port *port);
bool e87_app_start(void);
void e87_app_dispatch_forever(void);

#endif
