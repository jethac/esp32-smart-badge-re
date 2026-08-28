#include "e87/e87_sleep.h"

#include <stddef.h>
#include <stdint.h>

static bool e87_has_sleep_io(const struct e87_panel_io *io)
{
    return io != NULL &&
           io->wait_busy != NULL &&
           io->backlight_set != NULL &&
           io->write_command != NULL &&
           io->delay_ms != NULL &&
           io->clock_set != NULL;
}

enum e87_sleep_result
e87_sleep_enter(const struct e87_panel_io *io)
{
    if (!e87_has_sleep_io(io)) {
        return E87_SLEEP_ERROR_ARGUMENT;
    }

    io->wait_busy(io->context);
    io->backlight_set(io->context, false);
    io->write_command(io->context, UINT8_C(0x28), NULL, 0U);
    io->write_command(io->context, UINT8_C(0x10), NULL, 0U);
    io->delay_ms(io->context, UINT16_C(120));
    io->clock_set(io->context, E87_PANEL_CLOCK_RELEASE);
    return E87_SLEEP_OK;
}

enum e87_sleep_result
e87_sleep_wake(const struct e87_panel_io *io,
               e87_sleep_redraw_fn redraw,
               void *redraw_context)
{
    enum e87_panel_result panel_result;

    if (!e87_has_sleep_io(io) ||
        io->reset_write == NULL ||
        redraw == NULL) {
        return E87_SLEEP_ERROR_ARGUMENT;
    }

    io->backlight_set(io->context, false);
    io->clock_set(io->context, E87_PANEL_CLOCK_ACQUIRE);
    panel_result = e87_panel_jd9855_reset_and_replay(io);
    if (panel_result != E87_PANEL_OK) {
        return E87_SLEEP_ERROR_PANEL_INIT;
    }
    if (redraw(redraw_context) != E87_LCD_STREAM_OK) {
        return E87_SLEEP_ERROR_REDRAW;
    }
    io->backlight_set(io->context, true);
    return E87_SLEEP_OK;
}
