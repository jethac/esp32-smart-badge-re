#ifndef E87_LAB_SMOKE_H
#define E87_LAB_SMOKE_H

#include <stdbool.h>
#include <stdint.h>

#include "e87/e87_panel.h"

enum e87_lab_smoke_result {
    E87_LAB_SMOKE_OK = 0,
    E87_LAB_SMOKE_NO_CHANGE = 1,
    E87_LAB_SMOKE_ERROR_ARGUMENT = 2,
    E87_LAB_SMOKE_ERROR_PANEL = 3,
    E87_LAB_SMOKE_ERROR_RENDER = 4
};

struct e87_lab_smoke {
    const struct e87_panel_io *private_io;
    uint32_t private_started_ms;
    bool private_started;
    bool private_face_presented;
};

enum e87_lab_smoke_result
e87_lab_smoke_start(struct e87_lab_smoke *smoke,
                    const struct e87_panel_io *io,
                    uint32_t now_ms);

enum e87_lab_smoke_result
e87_lab_smoke_step(struct e87_lab_smoke *smoke, uint32_t now_ms);

#endif
