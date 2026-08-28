#ifndef E87_STAGE0_APP_H
#define E87_STAGE0_APP_H

#include <stdbool.h>
#include <stdint.h>

bool e87_stage0_app_start(void);
const uint8_t *e87_stage0_app_random_address(void);
void e87_stage0_app_dispatch_forever(void);

#endif
