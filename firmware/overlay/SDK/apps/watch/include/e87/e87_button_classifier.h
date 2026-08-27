#ifndef E87_BUTTON_CLASSIFIER_H
#define E87_BUTTON_CLASSIFIER_H

#include <stdbool.h>
#include <stdint.h>

#include "e87/e87_button_fsm.h"

struct e87_adc_window {
    uint16_t minimum_inclusive;
    uint16_t maximum_inclusive;
};

struct e87_button_classifier_config {
    uint16_t adc_maximum;
    uint16_t sample_period_ms;
    uint16_t sample_lateness_ms;
    uint16_t stable_sample_count;
    uint16_t minimum_guard_codes;
    struct e87_adc_window none;
    struct e87_adc_window button1;
    struct e87_adc_window button2;
    struct e87_adc_window both_buttons;
};

enum e87_button_classifier_result {
    E87_CLASSIFIER_ERROR = 0,
    E87_CLASSIFIER_TOO_EARLY = 1,
    E87_CLASSIFIER_ACCEPTED_UNCHANGED = 2,
    E87_CLASSIFIER_ACCEPTED_CHANGED = 3,
    E87_CLASSIFIER_ACCEPTED_UNSAFE = 4
};

struct e87_button_classifier {
    struct e87_button_classifier_config private_config;
    enum e87_key_class private_published;
    enum e87_key_class private_candidate;
    uint32_t private_cadence_baseline_ms;
    uint16_t private_candidate_count;
    bool private_initialized;
    bool private_have_time;
    bool private_quarantined;
};

bool e87_button_classifier_config_valid(
    const struct e87_button_classifier_config *config);

bool e87_button_classifier_init(
    struct e87_button_classifier *classifier,
    const struct e87_button_classifier_config *config);

enum e87_button_classifier_result e87_button_classifier_sample(
    struct e87_button_classifier *classifier,
    uint32_t now_ms,
    uint32_t raw_adc,
    enum e87_key_class *out_key);

#endif
