#include "e87/e87_button_classifier.h"

static enum e87_key_class unsafe_key(void)
{
    return (enum e87_key_class)UINT8_MAX;
}

static void sort_windows(struct e87_adc_window windows[4])
{
    unsigned int outer;

    for (outer = 1U; outer < 4U; outer += 1U) {
        const struct e87_adc_window selected = windows[outer];
        unsigned int inner = outer;

        while (inner > 0U &&
               windows[inner - 1U].minimum_inclusive >
                   selected.minimum_inclusive) {
            windows[inner] = windows[inner - 1U];
            inner -= 1U;
        }
        windows[inner] = selected;
    }
}

bool e87_button_classifier_config_valid(
    const struct e87_button_classifier_config *config)
{
    struct e87_adc_window windows[4];
    unsigned int index;

    if (config == 0 || config->stable_sample_count == UINT16_C(0) ||
        config->sample_period_ms < UINT16_C(10) ||
        config->sample_period_ms % UINT16_C(10) != UINT16_C(0) ||
        (uint32_t)config->sample_period_ms +
                (uint32_t)config->sample_lateness_ms >=
            UINT32_C(0x80000000) ||
        config->minimum_guard_codes < UINT16_C(1)) {
        return false;
    }

    windows[0] = config->none;
    windows[1] = config->button1;
    windows[2] = config->button2;
    windows[3] = config->both_buttons;
    for (index = 0U; index < 4U; index += 1U) {
        if (windows[index].minimum_inclusive >
                windows[index].maximum_inclusive ||
            windows[index].maximum_inclusive > config->adc_maximum) {
            return false;
        }
    }

    sort_windows(windows);
    for (index = 1U; index < 4U; index += 1U) {
        const uint32_t previous_maximum =
            (uint32_t)windows[index - 1U].maximum_inclusive;
        const uint32_t next_minimum =
            (uint32_t)windows[index].minimum_inclusive;

        if (previous_maximum + UINT32_C(1) >= next_minimum ||
            next_minimum - previous_maximum - UINT32_C(1) <
                (uint32_t)config->minimum_guard_codes) {
            return false;
        }
    }
    return true;
}

bool e87_button_classifier_init(
    struct e87_button_classifier *classifier,
    const struct e87_button_classifier_config *config)
{
    struct e87_button_classifier_config copied_config;

    if (classifier == 0 || !e87_button_classifier_config_valid(config)) {
        return false;
    }
    copied_config = *config;
    *classifier = (struct e87_button_classifier){0};
    classifier->private_config = copied_config;
    classifier->private_published = unsafe_key();
    classifier->private_candidate = unsafe_key();
    classifier->private_initialized = true;
    classifier->private_quarantined = true;
    return true;
}

static enum e87_button_classifier_result publish(
    struct e87_button_classifier *classifier,
    enum e87_key_class key,
    enum e87_key_class *out_key)
{
    const bool changed = classifier->private_published != key;

    classifier->private_published = key;
    *out_key = key;
    return changed ? E87_CLASSIFIER_ACCEPTED_CHANGED
                   : E87_CLASSIFIER_ACCEPTED_UNCHANGED;
}

static enum e87_button_classifier_result enter_unsafe(
    struct e87_button_classifier *classifier,
    uint32_t now_ms,
    enum e87_key_class *out_key)
{
    classifier->private_cadence_baseline_ms = now_ms;
    classifier->private_candidate = unsafe_key();
    classifier->private_candidate_count = UINT16_C(0);
    classifier->private_published = unsafe_key();
    classifier->private_quarantined = true;
    *out_key = unsafe_key();
    return E87_CLASSIFIER_ACCEPTED_UNSAFE;
}

static bool raw_key(const struct e87_button_classifier_config *config,
                    uint32_t raw_adc,
                    enum e87_key_class *key)
{
    if (raw_adc > (uint32_t)config->adc_maximum) {
        return false;
    }
    if (raw_adc >= (uint32_t)config->none.minimum_inclusive &&
        raw_adc <= (uint32_t)config->none.maximum_inclusive) {
        *key = E87_KEY_NONE;
        return true;
    }
    if (raw_adc >= (uint32_t)config->button1.minimum_inclusive &&
        raw_adc <= (uint32_t)config->button1.maximum_inclusive) {
        *key = E87_KEY_BUTTON1;
        return true;
    }
    if (raw_adc >= (uint32_t)config->button2.minimum_inclusive &&
        raw_adc <= (uint32_t)config->button2.maximum_inclusive) {
        *key = E87_KEY_BUTTON2;
        return true;
    }
    if (raw_adc >= (uint32_t)config->both_buttons.minimum_inclusive &&
        raw_adc <= (uint32_t)config->both_buttons.maximum_inclusive) {
        *key = E87_KEY_AMBIGUOUS;
        return true;
    }
    return false;
}

static bool is_direct_known_transition(enum e87_key_class published,
                                       enum e87_key_class measured)
{
    return (published == E87_KEY_BUTTON1 && measured == E87_KEY_BUTTON2) ||
           (published == E87_KEY_BUTTON2 && measured == E87_KEY_BUTTON1);
}

enum e87_button_classifier_result e87_button_classifier_sample(
    struct e87_button_classifier *classifier,
    uint32_t now_ms,
    uint32_t raw_adc,
    enum e87_key_class *out_key)
{
    enum e87_key_class measured;

    if (classifier == 0 || out_key == 0 ||
        !classifier->private_initialized) {
        return E87_CLASSIFIER_ERROR;
    }

    if (!classifier->private_have_time) {
        classifier->private_have_time = true;
        classifier->private_cadence_baseline_ms = now_ms;
    } else {
        const uint32_t elapsed =
            now_ms - classifier->private_cadence_baseline_ms;
        const uint32_t latest =
            (uint32_t)classifier->private_config.sample_period_ms +
            (uint32_t)classifier->private_config.sample_lateness_ms;

        if (elapsed <
            (uint32_t)classifier->private_config.sample_period_ms) {
            return E87_CLASSIFIER_TOO_EARLY;
        }
        if (elapsed > latest) {
            return enter_unsafe(classifier, now_ms, out_key);
        }
        classifier->private_cadence_baseline_ms = now_ms;
    }

    if (!raw_key(&classifier->private_config, raw_adc, &measured)) {
        return enter_unsafe(classifier, now_ms, out_key);
    }

    if (measured == E87_KEY_AMBIGUOUS ||
        (!classifier->private_quarantined &&
         is_direct_known_transition(classifier->private_published,
                                    measured))) {
        classifier->private_candidate = unsafe_key();
        classifier->private_candidate_count = UINT16_C(0);
        classifier->private_quarantined = true;
        return publish(classifier, E87_KEY_AMBIGUOUS, out_key);
    }

    if (classifier->private_quarantined) {
        if (measured != E87_KEY_NONE) {
            classifier->private_candidate = unsafe_key();
            classifier->private_candidate_count = UINT16_C(0);
            return publish(classifier, unsafe_key(), out_key);
        }
        if (classifier->private_candidate != E87_KEY_NONE) {
            classifier->private_candidate = E87_KEY_NONE;
            classifier->private_candidate_count = UINT16_C(1);
        } else {
            classifier->private_candidate_count += UINT16_C(1);
        }
        if (classifier->private_candidate_count >=
            classifier->private_config.stable_sample_count) {
            classifier->private_candidate = unsafe_key();
            classifier->private_candidate_count = UINT16_C(0);
            classifier->private_quarantined = false;
            return publish(classifier, E87_KEY_NONE, out_key);
        }
        *out_key = classifier->private_published;
        return E87_CLASSIFIER_ACCEPTED_UNCHANGED;
    }

    if (measured == classifier->private_published) {
        classifier->private_candidate = unsafe_key();
        classifier->private_candidate_count = UINT16_C(0);
        *out_key = classifier->private_published;
        return E87_CLASSIFIER_ACCEPTED_UNCHANGED;
    }
    if (classifier->private_candidate != measured) {
        classifier->private_candidate = measured;
        classifier->private_candidate_count = UINT16_C(1);
    } else {
        classifier->private_candidate_count += UINT16_C(1);
    }
    if (classifier->private_candidate_count >=
        classifier->private_config.stable_sample_count) {
        classifier->private_candidate = unsafe_key();
        classifier->private_candidate_count = UINT16_C(0);
        return publish(classifier, measured, out_key);
    }
    *out_key = classifier->private_published;
    return E87_CLASSIFIER_ACCEPTED_UNCHANGED;
}
