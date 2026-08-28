#ifndef E87_SLEEP_H
#define E87_SLEEP_H

#include "e87/e87_lcd_stream.h"
#include "e87/e87_panel.h"

enum e87_sleep_result {
    E87_SLEEP_OK = 0,
    E87_SLEEP_ERROR_ARGUMENT = 1,
    E87_SLEEP_ERROR_PANEL_INIT = 2,
    E87_SLEEP_ERROR_REDRAW = 3
};

typedef enum e87_lcd_stream_result
    (*e87_sleep_redraw_fn)(void *context);

enum e87_sleep_result
e87_sleep_enter(const struct e87_panel_io *io);

enum e87_sleep_result
e87_sleep_wake(const struct e87_panel_io *io,
               e87_sleep_redraw_fn redraw,
               void *redraw_context);

#endif
