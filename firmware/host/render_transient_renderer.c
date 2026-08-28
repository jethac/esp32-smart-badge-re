#include "e87/e87_transient_renderer.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

enum {
    E87_HELPER_STRIP_PIXELS = E87_DISPLAY_WIDTH * E87_STRIP_ROWS,
    E87_HELPER_STRIP_BYTES =
        E87_HELPER_STRIP_PIXELS * E87_RGB565_BYTES_PER_PIXEL
};

static void initialize_model(struct e87_render_model *model)
{
    memset(model, 0, sizeof(*model));
    model->screen = E87_UI_SCREEN_FACE;
    model->metrics.day = UINT8_C(50);
    model->metrics.week = UINT8_C(50);
    model->metrics.credit_cents = E87_STATE_FIXED_CREDIT_CENTS;
    model->battery_state = E87_UI_BATTERY_VALID;
    model->battery_percent = UINT8_C(50);
    model->charge_visual = E87_UI_CHARGE_NONE;
    model->maintenance_phase = E87_UI_MAINTENANCE_WAITING_FOR_PHONE;
}

static bool scene_model(const char *name, struct e87_render_model *model)
{
    initialize_model(model);
    if (strcmp(name, "unpaired") == 0) {
        model->screen = E87_UI_SCREEN_PAIR_ME_NOW;
    } else if (strcmp(name, "waiting") == 0) {
        model->screen = E87_UI_SCREEN_WAITING_FOR_PHONE;
    } else if (strcmp(name, "pairing-060") == 0) {
        model->screen = E87_UI_SCREEN_PAIRING;
        model->countdown_seconds = UINT8_C(60);
    } else if (strcmp(name, "pairing-001") == 0) {
        model->screen = E87_UI_SCREEN_PAIRING;
        model->countdown_seconds = UINT8_C(1);
    } else if (strcmp(name, "warning-003") == 0) {
        model->screen = E87_UI_SCREEN_UPDATE_WARNING;
        model->countdown_seconds = UINT8_C(3);
    } else if (strcmp(name, "warning-002") == 0) {
        model->screen = E87_UI_SCREEN_UPDATE_WARNING;
        model->countdown_seconds = UINT8_C(2);
    } else if (strcmp(name, "warning-001") == 0) {
        model->screen = E87_UI_SCREEN_UPDATE_WARNING;
        model->countdown_seconds = UINT8_C(1);
    } else if (strcmp(name, "battery-face-000") == 0) {
        model->battery_overlay = true;
        model->battery_percent = UINT8_C(0);
    } else if (strcmp(name, "battery-face-001") == 0) {
        model->battery_overlay = true;
        model->battery_percent = UINT8_C(1);
    } else if (strcmp(name, "battery-face-050") == 0) {
        model->battery_overlay = true;
    } else if (strcmp(name, "battery-face-099") == 0) {
        model->battery_overlay = true;
        model->battery_percent = UINT8_C(99);
    } else if (strcmp(name, "battery-face-100") == 0) {
        model->battery_overlay = true;
        model->battery_percent = UINT8_C(100);
    } else if (strcmp(name, "battery-face-050-charging") == 0) {
        model->battery_overlay = true;
        model->charge_visual = E87_UI_CHARGE_CHARGING;
    } else if (strcmp(name, "battery-face-100-full") == 0) {
        model->battery_overlay = true;
        model->battery_percent = UINT8_C(100);
        model->charge_visual = E87_UI_CHARGE_FULL;
    } else if (strcmp(name, "battery-stale-037") == 0) {
        model->screen = E87_UI_SCREEN_WAITING_FOR_PHONE;
        model->battery_overlay = true;
        model->battery_state = E87_UI_BATTERY_INVALID_STALE;
        model->battery_percent = UINT8_C(37);
    } else if (strcmp(name, "battery-fault") == 0) {
        model->screen = E87_UI_SCREEN_PAIR_ME_NOW;
        model->battery_overlay = true;
        model->battery_state = E87_UI_BATTERY_UNAVAILABLE_FAULT;
        model->battery_percent = UINT8_C(0);
    } else if (strcmp(name, "maintenance-release-valid-050") == 0) {
        model->screen = E87_UI_SCREEN_MAINTENANCE;
        model->maintenance_phase = E87_UI_MAINTENANCE_RELEASE_BUTTON;
    } else if (strcmp(name, "maintenance-waiting-valid-050") == 0) {
        model->screen = E87_UI_SCREEN_MAINTENANCE;
        model->maintenance_phase = E87_UI_MAINTENANCE_WAITING_FOR_PHONE;
    } else if (strcmp(name, "maintenance-ready-valid-050") == 0) {
        model->screen = E87_UI_SCREEN_MAINTENANCE;
        model->maintenance_phase = E87_UI_MAINTENANCE_PHONE_READY;
    } else if (strcmp(name, "maintenance-update-000") == 0) {
        model->screen = E87_UI_SCREEN_MAINTENANCE;
        model->maintenance_phase = E87_UI_MAINTENANCE_UPDATING;
        model->maintenance_progress_percent = UINT8_C(0);
    } else if (strcmp(name, "maintenance-update-001") == 0) {
        model->screen = E87_UI_SCREEN_MAINTENANCE;
        model->maintenance_phase = E87_UI_MAINTENANCE_UPDATING;
        model->maintenance_progress_percent = UINT8_C(1);
    } else if (strcmp(name, "maintenance-update-050") == 0) {
        model->screen = E87_UI_SCREEN_MAINTENANCE;
        model->maintenance_phase = E87_UI_MAINTENANCE_UPDATING;
        model->maintenance_progress_percent = UINT8_C(50);
    } else if (strcmp(name, "maintenance-update-099") == 0) {
        model->screen = E87_UI_SCREEN_MAINTENANCE;
        model->maintenance_phase = E87_UI_MAINTENANCE_UPDATING;
        model->maintenance_progress_percent = UINT8_C(99);
    } else if (strcmp(name, "maintenance-update-100") == 0) {
        model->screen = E87_UI_SCREEN_MAINTENANCE;
        model->maintenance_phase = E87_UI_MAINTENANCE_UPDATING;
        model->maintenance_progress_percent = UINT8_C(100);
    } else if (strcmp(name, "maintenance-error") == 0) {
        model->screen = E87_UI_SCREEN_MAINTENANCE;
        model->maintenance_phase = E87_UI_MAINTENANCE_UPDATE_ERROR;
    } else if (strcmp(name, "maintenance-stale-037") == 0) {
        model->screen = E87_UI_SCREEN_MAINTENANCE;
        model->battery_state = E87_UI_BATTERY_INVALID_STALE;
        model->battery_percent = UINT8_C(37);
    } else if (strcmp(name, "maintenance-fault") == 0) {
        model->screen = E87_UI_SCREEN_MAINTENANCE;
        model->battery_state = E87_UI_BATTERY_UNAVAILABLE_FAULT;
        model->battery_percent = UINT8_C(0);
    } else if (strcmp(name, "recovery-release-valid-050") == 0) {
        model->screen = E87_UI_SCREEN_MAINTENANCE;
        model->maintenance_phase = E87_UI_MAINTENANCE_RELEASE_BUTTON;
        model->recovery_entry = true;
    } else {
        return false;
    }
    return true;
}

int main(int argc, char **argv)
{
    struct e87_render_model model;
    uint16_t pixels[E87_HELPER_STRIP_PIXELS];
    uint8_t encoded[E87_HELPER_STRIP_BYTES];
    unsigned int strip_index;

    if (argc != 2 ||
        !scene_model(argc > 1 ? argv[1] : NULL, &model)) {
        fputs("usage: render_transient_renderer SCENE\n", stderr);
        return 2;
    }
    for (strip_index = 0u; strip_index < E87_STRIP_COUNT; ++strip_index) {
        size_t pixel_index;

        if (e87_render_transient_strip(
                &model,
                (uint8_t)strip_index,
                pixels,
                E87_HELPER_STRIP_PIXELS) != E87_TRANSIENT_RENDER_OK) {
            fputs("transient renderer rejected a golden scene\n", stderr);
            return 3;
        }
        for (pixel_index = 0u;
             pixel_index < E87_HELPER_STRIP_PIXELS;
             ++pixel_index) {
            const uint16_t word = pixels[pixel_index];

            encoded[pixel_index * 2u] =
                (uint8_t)(word & UINT16_C(0x00FF));
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
