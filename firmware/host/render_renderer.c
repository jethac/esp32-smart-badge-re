#include "e87/e87_renderer.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

enum {
    E87_HELPER_STRIP_PIXELS = E87_DISPLAY_WIDTH * E87_STRIP_ROWS,
    E87_HELPER_STRIP_BYTES =
        E87_HELPER_STRIP_PIXELS * E87_RGB565_BYTES_PER_PIXEL
};

static bool parse_percentage(const char *text, uint8_t *out)
{
    unsigned int value = 0u;
    size_t index = 0u;

    if (text == NULL || out == NULL || text[0] == '\0') {
        return false;
    }
    while (text[index] != '\0') {
        const unsigned char character = (unsigned char)text[index];

        if (character < (unsigned char)'0' ||
            character > (unsigned char)'9') {
            return false;
        }
        value = value * 10u + (unsigned int)(character - (unsigned char)'0');
        if (value > 255u) {
            return false;
        }
        ++index;
    }
    *out = (uint8_t)value;
    return true;
}

int main(int argc, char **argv)
{
    struct e87_metrics model;
    uint16_t pixels[E87_HELPER_STRIP_PIXELS];
    uint8_t encoded[E87_HELPER_STRIP_BYTES];
    unsigned int strip_index;

    if (argc != 3 ||
        !parse_percentage(argc > 1 ? argv[1] : NULL, &model.day) ||
        !parse_percentage(argc > 2 ? argv[2] : NULL, &model.week)) {
        fputs("usage: render_renderer DAY WEEK (each 0..255)\n", stderr);
        return 2;
    }
    model.credit_cents = E87_STATE_FIXED_CREDIT_CENTS;

    for (strip_index = 0u; strip_index < E87_STRIP_COUNT; ++strip_index) {
        size_t pixel_index;

        if (e87_render_normal_face_strip(
                &model,
                (uint8_t)strip_index,
                pixels,
                E87_HELPER_STRIP_PIXELS) != E87_RENDER_OK) {
            fputs("renderer rejected a valid golden scene\n", stderr);
            return 3;
        }
        for (pixel_index = 0u;
             pixel_index < E87_HELPER_STRIP_PIXELS;
             ++pixel_index) {
            const uint16_t word = pixels[pixel_index];

            encoded[pixel_index * 2u] = (uint8_t)(word & UINT16_C(0x00FF));
            encoded[pixel_index * 2u + 1u] = (uint8_t)(word >> 8);
        }
        if (fwrite(encoded, 1u, sizeof(encoded), stdout) != sizeof(encoded)) {
            fputs("short raw-frame write\n", stderr);
            return 4;
        }
    }
    if (fflush(stdout) != 0 || ferror(stdout)) {
        fputs("raw-frame stream failure\n", stderr);
        return 5;
    }
    return 0;
}
