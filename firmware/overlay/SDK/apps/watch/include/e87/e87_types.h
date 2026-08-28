#ifndef E87_TYPES_H
#define E87_TYPES_H

#include <stdint.h>

enum e87_display_constants {
    E87_DISPLAY_WIDTH = 360,
    E87_DISPLAY_HEIGHT = 360,
    E87_STRIP_ROWS = 30,
    E87_STRIP_COUNT = E87_DISPLAY_HEIGHT / E87_STRIP_ROWS,
    E87_RGB565_BYTES_PER_PIXEL = 2,
    E87_STRIP_BUFFER_BYTES =
        E87_DISPLAY_WIDTH * E87_STRIP_ROWS * E87_RGB565_BYTES_PER_PIXEL,
    E87_TWO_STRIP_BUFFERS_BYTES = 2 * E87_STRIP_BUFFER_BYTES,
    E87_LCD_TAIL_RESERVATION_BYTES = 24576,
    E87_LCD_TAIL_SLACK_BYTES =
        E87_LCD_TAIL_RESERVATION_BYTES - E87_STRIP_BUFFER_BYTES,
};

_Static_assert(E87_DISPLAY_WIDTH == 360, "display width must remain 360");
_Static_assert(E87_DISPLAY_HEIGHT == 360, "display height must remain 360");
_Static_assert(E87_STRIP_ROWS == 30, "strip height must remain 30 rows");
_Static_assert(E87_DISPLAY_HEIGHT % E87_STRIP_ROWS == 0,
               "strip rows must divide display height");
_Static_assert(E87_STRIP_COUNT == 12, "360 rows must produce 12 strips");
_Static_assert(E87_RGB565_BYTES_PER_PIXEL == 2,
               "RGB565 must use two bytes per pixel");
_Static_assert(E87_STRIP_BUFFER_BYTES == 21600,
               "one strip buffer must occupy 0x5460 bytes");
_Static_assert(E87_STRIP_BUFFER_BYTES == 0x5460,
               "one strip hexadecimal budget changed");
_Static_assert(E87_TWO_STRIP_BUFFERS_BYTES == 43200,
               "two strip buffers would occupy 0xA8C0 bytes");
_Static_assert(E87_TWO_STRIP_BUFFERS_BYTES == 0xA8C0,
               "two-strip hexadecimal budget changed");
_Static_assert(E87_LCD_TAIL_RESERVATION_BYTES == 24576,
               "LCD tail reservation must occupy 0x6000 bytes");
_Static_assert(E87_LCD_TAIL_RESERVATION_BYTES == 0x6000,
               "LCD tail hexadecimal budget changed");
_Static_assert(E87_LCD_TAIL_SLACK_BYTES == 2976,
               "single-strip LCD tail slack must remain 0x0BA0 bytes");
_Static_assert(E87_LCD_TAIL_SLACK_BYTES == 0x0BA0,
               "LCD tail slack hexadecimal budget changed");
_Static_assert(E87_TWO_STRIP_BUFFERS_BYTES > E87_LCD_TAIL_RESERVATION_BYTES,
               "two stock strip buffers must not use the LCD tail alone");

#endif
