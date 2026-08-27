#ifndef E87_TYPES_H
#define E87_TYPES_H

#include <stdint.h>

enum e87_display_constants {
    E87_DISPLAY_WIDTH = 368,
    E87_DISPLAY_HEIGHT = 368,
    E87_STRIP_ROWS = 16,
    E87_STRIP_COUNT = E87_DISPLAY_HEIGHT / E87_STRIP_ROWS,
    E87_RGB565_BYTES_PER_PIXEL = 2,
    E87_STRIP_BUFFER_BYTES =
        E87_DISPLAY_WIDTH * E87_STRIP_ROWS * E87_RGB565_BYTES_PER_PIXEL,
    E87_TWO_STRIP_BUFFERS_BYTES = 2 * E87_STRIP_BUFFER_BYTES,
    E87_LCD_TAIL_RESERVATION_BYTES = 24576,
    E87_LCD_TAIL_SLACK_BYTES =
        E87_LCD_TAIL_RESERVATION_BYTES - E87_TWO_STRIP_BUFFERS_BYTES,
};

_Static_assert(E87_DISPLAY_WIDTH == 368, "display width must remain 368");
_Static_assert(E87_DISPLAY_HEIGHT == 368, "display height must remain 368");
_Static_assert(E87_STRIP_ROWS == 16, "strip height must remain 16 rows");
_Static_assert(E87_DISPLAY_HEIGHT % E87_STRIP_ROWS == 0,
               "strip rows must divide display height");
_Static_assert(E87_STRIP_COUNT == 23, "368 rows must produce 23 strips");
_Static_assert(E87_RGB565_BYTES_PER_PIXEL == 2,
               "RGB565 must use two bytes per pixel");
_Static_assert(E87_STRIP_BUFFER_BYTES == 11776,
               "one strip buffer must occupy 0x2E00 bytes");
_Static_assert(E87_STRIP_BUFFER_BYTES == 0x2E00,
               "one strip hexadecimal budget changed");
_Static_assert(E87_TWO_STRIP_BUFFERS_BYTES == 23552,
               "two strip buffers must occupy 0x5C00 bytes");
_Static_assert(E87_TWO_STRIP_BUFFERS_BYTES == 0x5C00,
               "two-strip hexadecimal budget changed");
_Static_assert(E87_LCD_TAIL_RESERVATION_BYTES == 24576,
               "LCD tail reservation must occupy 0x6000 bytes");
_Static_assert(E87_LCD_TAIL_RESERVATION_BYTES == 0x6000,
               "LCD tail hexadecimal budget changed");
_Static_assert(E87_LCD_TAIL_SLACK_BYTES == 1024,
               "LCD tail slack must remain 0x0400 bytes");
_Static_assert(E87_LCD_TAIL_SLACK_BYTES == 0x0400,
               "LCD tail slack hexadecimal budget changed");

#endif
