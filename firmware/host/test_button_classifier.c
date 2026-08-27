#include "test_support.h"
#include "e87/e87_button_classifier.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define E87_UNSAFE_KEY ((enum e87_key_class)UINT8_MAX)

static bool bytes_equal(const void *left, const void *right, size_t length)
{
    return memcmp(left, right, length) == 0;
}

static struct e87_button_classifier_config base_config(void)
{
    const struct e87_button_classifier_config config = {
        UINT16_C(100),
        UINT16_C(10),
        UINT16_C(2),
        UINT16_C(2),
        UINT16_C(1),
        {UINT16_C(10), UINT16_C(19)},
        {UINT16_C(30), UINT16_C(39)},
        {UINT16_C(50), UINT16_C(59)},
        {UINT16_C(70), UINT16_C(79)}
    };

    return config;
}

static struct e87_button_classifier initialized(
    const struct e87_button_classifier_config *config)
{
    struct e87_button_classifier classifier;

    memset(&classifier, 0xA5, sizeof(classifier));
    (void)e87_button_classifier_init(&classifier, config);
    return classifier;
}

static enum e87_button_classifier_result release_startup(
    struct e87_button_classifier *classifier,
    uint32_t start_ms,
    enum e87_key_class *out_key)
{
    const uint16_t raw_none = classifier->private_config.none.minimum_inclusive;
    uint16_t index;
    enum e87_button_classifier_result result = E87_CLASSIFIER_ERROR;

    for (index = UINT16_C(0);
         index < classifier->private_config.stable_sample_count;
         index += UINT16_C(1)) {
        result = e87_button_classifier_sample(
            classifier,
            start_ms + (uint32_t)index *
                           classifier->private_config.sample_period_ms,
            raw_none,
            out_key);
    }
    return result;
}

static enum e87_button_classifier_result publish_known(
    struct e87_button_classifier *classifier,
    uint32_t first_ms,
    uint16_t raw,
    enum e87_key_class *out_key)
{
    uint16_t index;
    enum e87_button_classifier_result result = E87_CLASSIFIER_ERROR;

    for (index = UINT16_C(0);
         index < classifier->private_config.stable_sample_count;
         index += UINT16_C(1)) {
        result = e87_button_classifier_sample(
            classifier,
            first_ms + (uint32_t)index *
                           classifier->private_config.sample_period_ms,
            raw,
            out_key);
    }
    return result;
}

static uint32_t forward_classifier_sample(
    struct e87_button_classifier *classifier,
    struct e87_button_fsm *fsm,
    uint32_t now_ms,
    uint32_t raw_adc,
    enum e87_button_classifier_result *result)
{
    enum e87_key_class key = E87_KEY_AMBIGUOUS;

    *result = e87_button_classifier_sample(classifier, now_ms, raw_adc, &key);
    if (*result == E87_CLASSIFIER_ACCEPTED_UNCHANGED ||
        *result == E87_CLASSIFIER_ACCEPTED_CHANGED ||
        *result == E87_CLASSIFIER_ACCEPTED_UNSAFE) {
        return e87_button_step(fsm, now_ms, key);
    }
    return UINT32_MAX;
}

E87_TEST(config_rejects_invalid_values_without_mutation)
{
    struct e87_button_classifier_config config = base_config();
    struct e87_button_classifier_config before;
    struct e87_button_classifier classifier;
    struct e87_button_classifier classifier_before;
    unsigned int mutation;

    E87_ASSERT_TRUE(!e87_button_classifier_config_valid(NULL));
    for (mutation = 0U; mutation < 12U; mutation += 1U) {
        config = base_config();
        switch (mutation) {
        case 0U:
            config.stable_sample_count = UINT16_C(0);
            break;
        case 1U:
            config.sample_period_ms = UINT16_C(9);
            break;
        case 2U:
            config.sample_period_ms = UINT16_C(11);
            break;
        case 3U:
            config.minimum_guard_codes = UINT16_C(0);
            break;
        case 4U:
            config.none.minimum_inclusive = UINT16_C(20);
            break;
        case 5U:
            config.button1.minimum_inclusive = UINT16_C(18);
            break;
        case 6U:
            config.button1.minimum_inclusive = UINT16_C(19);
            break;
        case 7U:
            config.button1.minimum_inclusive = UINT16_C(20);
            break;
        case 8U:
            config.minimum_guard_codes = UINT16_C(11);
            break;
        case 9U:
            config.both_buttons.maximum_inclusive = UINT16_C(101);
            break;
        case 10U:
            config.adc_maximum = UINT16_C(58);
            break;
        default:
            config.button2.maximum_inclusive = UINT16_C(49);
            break;
        }
        before = config;
        E87_ASSERT_TRUE(!e87_button_classifier_config_valid(&config));
        E87_ASSERT_TRUE(bytes_equal(&config, &before, sizeof(config)));

        memset(&classifier, 0x5A, sizeof(classifier));
        classifier_before = classifier;
        E87_ASSERT_TRUE(!e87_button_classifier_init(&classifier, &config));
        E87_ASSERT_TRUE(bytes_equal(&classifier, &classifier_before,
                                    sizeof(classifier)));
        E87_ASSERT_TRUE(bytes_equal(&config, &before, sizeof(config)));
    }
    memset(&classifier, 0x3C, sizeof(classifier));
    classifier_before = classifier;
    E87_ASSERT_TRUE(!e87_button_classifier_init(&classifier, NULL));
    E87_ASSERT_TRUE(bytes_equal(&classifier, &classifier_before,
                                sizeof(classifier)));
    E87_ASSERT_TRUE(!e87_button_classifier_init(NULL, &before));
}

E87_TEST(config_sorts_all_physical_numeric_orders)
{
    static const uint8_t permutations[24][4] = {
        {0, 1, 2, 3}, {0, 1, 3, 2}, {0, 2, 1, 3}, {0, 2, 3, 1},
        {0, 3, 1, 2}, {0, 3, 2, 1}, {1, 0, 2, 3}, {1, 0, 3, 2},
        {1, 2, 0, 3}, {1, 2, 3, 0}, {1, 3, 0, 2}, {1, 3, 2, 0},
        {2, 0, 1, 3}, {2, 0, 3, 1}, {2, 1, 0, 3}, {2, 1, 3, 0},
        {2, 3, 0, 1}, {2, 3, 1, 0}, {3, 0, 1, 2}, {3, 0, 2, 1},
        {3, 1, 0, 2}, {3, 1, 2, 0}, {3, 2, 0, 1}, {3, 2, 1, 0}
    };
    static const struct e87_adc_window windows[4] = {
        {UINT16_C(10), UINT16_C(12)},
        {UINT16_C(20), UINT16_C(22)},
        {UINT16_C(30), UINT16_C(32)},
        {UINT16_C(40), UINT16_C(42)}
    };
    struct e87_button_classifier_config exact_guard = base_config();
    unsigned int index;

    exact_guard.button1.minimum_inclusive = UINT16_C(21);
    E87_ASSERT_TRUE(e87_button_classifier_config_valid(&exact_guard));
    for (index = 0U; index < 24U; index += 1U) {
        struct e87_button_classifier_config config = base_config();

        config.none = windows[permutations[index][0]];
        config.button1 = windows[permutations[index][1]];
        config.button2 = windows[permutations[index][2]];
        config.both_buttons = windows[permutations[index][3]];
        E87_ASSERT_TRUE(e87_button_classifier_config_valid(&config));
    }
}

E87_TEST(window_edges_neighbors_guards_and_outer_domains_are_exact)
{
    struct e87_button_classifier_config config = base_config();
    static const uint16_t measured[8] = {10, 19, 30, 39, 50, 59, 70, 79};
    static const enum e87_key_class mapped[8] = {
        E87_KEY_NONE, E87_KEY_NONE, E87_KEY_BUTTON1, E87_KEY_BUTTON1,
        E87_KEY_BUTTON2, E87_KEY_BUTTON2,
        E87_KEY_AMBIGUOUS, E87_KEY_AMBIGUOUS
    };
    static const uint16_t unsafe[14] = {
        0, 9, 20, 29, 40, 49, 60, 69, 80, 100,
        21, 28, 41, 68
    };
    unsigned int index;

    config.stable_sample_count = UINT16_C(1);
    for (index = 0U; index < 8U; index += 1U) {
        struct e87_button_classifier classifier = initialized(&config);
        enum e87_key_class out = E87_UNSAFE_KEY;

        E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_CHANGED,
                          release_startup(&classifier, UINT32_C(0), &out));
        if (mapped[index] == E87_KEY_NONE) {
            E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNCHANGED,
                              e87_button_classifier_sample(
                                  &classifier, UINT32_C(10), measured[index],
                                  &out));
        } else {
            E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_CHANGED,
                              e87_button_classifier_sample(
                                  &classifier, UINT32_C(10), measured[index],
                                  &out));
        }
        E87_ASSERT_EQ_U32(mapped[index], out);
    }
    for (index = 0U; index < 14U; index += 1U) {
        struct e87_button_classifier classifier = initialized(&config);
        enum e87_key_class out = E87_KEY_BUTTON2;

        E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNSAFE,
                          e87_button_classifier_sample(
                              &classifier, UINT32_C(0), unsafe[index], &out));
        E87_ASSERT_EQ_U32(E87_UNSAFE_KEY, out);
        E87_ASSERT_TRUE(classifier.private_quarantined);
    }
}

E87_TEST(both_buttons_is_immediately_ambiguous_and_quarantines)
{
    struct e87_button_classifier_config config = base_config();
    struct e87_button_classifier classifier = initialized(&config);
    enum e87_key_class out = E87_KEY_BUTTON1;

    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_CHANGED,
                      release_startup(&classifier, UINT32_C(0), &out));
    E87_ASSERT_EQ_U32(E87_KEY_NONE, out);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_CHANGED,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(20), UINT32_C(70), &out));
    E87_ASSERT_EQ_U32(E87_KEY_AMBIGUOUS, out);
    E87_ASSERT_TRUE(classifier.private_quarantined);
    E87_ASSERT_EQ_U32(UINT16_C(0), classifier.private_candidate_count);
}

E87_TEST(startup_and_every_fault_quarantine_require_stable_none)
{
    struct e87_button_classifier_config config = base_config();
    struct e87_button_classifier classifier = initialized(&config);
    enum e87_key_class out = E87_KEY_BUTTON2;

    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNCHANGED,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(0), UINT32_C(10), &out));
    E87_ASSERT_EQ_U32(E87_UNSAFE_KEY, out);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNCHANGED,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(10), UINT32_C(30), &out));
    E87_ASSERT_EQ_U32(E87_UNSAFE_KEY, out);
    E87_ASSERT_EQ_U32(UINT16_C(0), classifier.private_candidate_count);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNCHANGED,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(20), UINT32_C(10), &out));
    E87_ASSERT_EQ_U32(E87_UNSAFE_KEY, out);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_CHANGED,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(30), UINT32_C(10), &out));
    E87_ASSERT_EQ_U32(E87_KEY_NONE, out);

    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNSAFE,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(40), UINT32_C(20), &out));
    E87_ASSERT_EQ_U32(E87_UNSAFE_KEY, out);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNCHANGED,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(50), UINT32_C(10), &out));
    E87_ASSERT_EQ_U32(E87_UNSAFE_KEY, out);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_CHANGED,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(60), UINT32_C(10), &out));
    E87_ASSERT_EQ_U32(E87_KEY_NONE, out);
}

static void direct_transition_case(uint16_t first_raw,
                                   uint16_t second_raw,
                                   enum e87_key_class first_key,
                                   enum e87_key_class second_key)
{
    struct e87_button_classifier_config config = base_config();
    struct e87_button_classifier classifier = initialized(&config);
    enum e87_key_class out = E87_UNSAFE_KEY;

    (void)release_startup(&classifier, UINT32_C(0), &out);
    (void)publish_known(&classifier, UINT32_C(20), first_raw, &out);
    E87_ASSERT_EQ_U32(first_key, out);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_CHANGED,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(40), second_raw, &out));
    E87_ASSERT_EQ_U32(E87_KEY_AMBIGUOUS, out);
    E87_ASSERT_TRUE(classifier.private_quarantined);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNCHANGED,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(50), UINT32_C(10), &out));
    E87_ASSERT_EQ_U32(E87_KEY_AMBIGUOUS, out);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_CHANGED,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(60), UINT32_C(10), &out));
    E87_ASSERT_EQ_U32(E87_KEY_NONE, out);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNCHANGED,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(70), second_raw, &out));
    E87_ASSERT_EQ_U32(E87_KEY_NONE, out);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_CHANGED,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(80), second_raw, &out));
    E87_ASSERT_EQ_U32(second_key, out);
}

E87_TEST(direct_known_transitions_ambiguous_then_fresh_destination)
{
    direct_transition_case(UINT16_C(30), UINT16_C(50),
                           E87_KEY_BUTTON1, E87_KEY_BUTTON2);
    direct_transition_case(UINT16_C(50), UINT16_C(30),
                           E87_KEY_BUTTON2, E87_KEY_BUTTON1);
}

E87_TEST(cadence_edges_are_inclusive_and_early_is_immutable)
{
    struct e87_button_classifier_config config = base_config();
    struct e87_button_classifier classifier = initialized(&config);
    struct e87_button_classifier before;
    enum e87_key_class out = E87_KEY_BUTTON1;
    enum e87_key_class out_before;

    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNCHANGED,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(100), UINT32_C(10), &out));
    before = classifier;
    out = E87_KEY_BUTTON2;
    out_before = out;
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_TOO_EARLY,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(109), UINT32_C(10), &out));
    E87_ASSERT_TRUE(bytes_equal(&classifier, &before, sizeof(classifier)));
    E87_ASSERT_EQ_U32(out_before, out);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_CHANGED,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(110), UINT32_C(10), &out));

    classifier = initialized(&config);
    (void)e87_button_classifier_sample(
        &classifier, UINT32_C(200), UINT32_C(10), &out);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_CHANGED,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(212), UINT32_C(10), &out));

    classifier = initialized(&config);
    (void)e87_button_classifier_sample(
        &classifier, UINT32_C(300), UINT32_C(10), &out);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNSAFE,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(313), UINT32_C(10), &out));
    E87_ASSERT_EQ_U32(E87_UNSAFE_KEY, out);
}

E87_TEST(raw_adc_width_and_maximum_are_not_narrowed)
{
    struct e87_button_classifier_config config = base_config();
    struct e87_button_classifier classifier;
    enum e87_key_class out = E87_KEY_NONE;

    config.adc_maximum = UINT16_MAX;
    config.both_buttons.maximum_inclusive = UINT16_MAX;
    E87_ASSERT_TRUE(e87_button_classifier_config_valid(&config));
    config.stable_sample_count = UINT16_C(1);
    classifier = initialized(&config);
    (void)release_startup(&classifier, UINT32_C(0), &out);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_CHANGED,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(10), UINT32_C(65535), &out));
    E87_ASSERT_EQ_U32(E87_KEY_AMBIGUOUS, out);

    classifier = initialized(&config);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNSAFE,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(0), UINT32_C(65536), &out));
    E87_ASSERT_EQ_U32(E87_UNSAFE_KEY, out);
    classifier = initialized(&config);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNSAFE,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(0), UINT32_MAX, &out));
}

E87_TEST(candidate_bounce_and_faults_never_accumulate)
{
    struct e87_button_classifier_config config = base_config();
    struct e87_button_classifier classifier;
    enum e87_key_class out = E87_UNSAFE_KEY;

    config.stable_sample_count = UINT16_C(3);
    classifier = initialized(&config);
    (void)release_startup(&classifier, UINT32_C(0), &out);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNCHANGED,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(30), UINT32_C(30), &out));
    E87_ASSERT_EQ_U32(UINT16_C(1), classifier.private_candidate_count);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNCHANGED,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(40), UINT32_C(50), &out));
    E87_ASSERT_EQ_U32(UINT16_C(1), classifier.private_candidate_count);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNCHANGED,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(50), UINT32_C(30), &out));
    E87_ASSERT_EQ_U32(UINT16_C(1), classifier.private_candidate_count);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNSAFE,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(60), UINT32_C(20), &out));
    E87_ASSERT_EQ_U32(UINT16_C(0), classifier.private_candidate_count);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNCHANGED,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(70), UINT32_C(30), &out));
    E87_ASSERT_EQ_U32(UINT16_C(0), classifier.private_candidate_count);
}

E87_TEST(error_calls_preserve_every_nonnull_byte)
{
    struct e87_button_classifier_config config = base_config();
    struct e87_button_classifier classifier = initialized(&config);
    struct e87_button_classifier before;
    enum e87_key_class out = E87_KEY_BUTTON2;
    enum e87_key_class out_before = out;

    before = classifier;
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ERROR,
                      e87_button_classifier_sample(
                          NULL, UINT32_C(0), UINT32_C(10), &out));
    E87_ASSERT_EQ_U32(out_before, out);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ERROR,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(0), UINT32_C(10), NULL));
    E87_ASSERT_TRUE(bytes_equal(&classifier, &before, sizeof(classifier)));

    memset(&classifier, 0xA5, sizeof(classifier));
    classifier.private_initialized = false;
    before = classifier;
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ERROR,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(0), UINT32_C(10), &out));
    E87_ASSERT_TRUE(bytes_equal(&classifier, &before, sizeof(classifier)));
    E87_ASSERT_EQ_U32(out_before, out);
}

E87_TEST(cadence_and_recovery_survive_uint32_wrap)
{
    struct e87_button_classifier_config config = base_config();
    struct e87_button_classifier classifier = initialized(&config);
    struct e87_button_classifier before;
    enum e87_key_class out = E87_KEY_BUTTON2;

    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNCHANGED,
                      e87_button_classifier_sample(
                          &classifier, UINT32_MAX - UINT32_C(5),
                          UINT32_C(10), &out));
    before = classifier;
    out = E87_KEY_BUTTON1;
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_TOO_EARLY,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(3), UINT32_C(10), &out));
    E87_ASSERT_TRUE(bytes_equal(&classifier, &before, sizeof(classifier)));
    E87_ASSERT_EQ_U32(E87_KEY_BUTTON1, out);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_CHANGED,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(4), UINT32_C(10), &out));
    E87_ASSERT_EQ_U32(E87_KEY_NONE, out);

    classifier = initialized(&config);
    (void)e87_button_classifier_sample(
        &classifier, UINT32_MAX - UINT32_C(20), UINT32_C(10), &out);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNSAFE,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(0), UINT32_C(10), &out));
    E87_ASSERT_EQ_U32(UINT32_C(0), classifier.private_cadence_baseline_ms);
}

E87_TEST(too_early_never_advances_task3a_time)
{
    struct e87_button_classifier_config config = base_config();
    struct e87_button_classifier classifier = initialized(&config);
    struct e87_button_fsm fsm;
    enum e87_button_classifier_result result;
    struct e87_button_fsm before;
    uint32_t actions;

    e87_button_init(&fsm);
    (void)forward_classifier_sample(&classifier, &fsm, UINT32_C(0),
                                    UINT32_C(10), &result);
    actions = forward_classifier_sample(&classifier, &fsm, UINT32_C(9),
                                        UINT32_C(30), &result);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_TOO_EARLY, result);
    E87_ASSERT_EQ_U32(UINT32_MAX, actions);
    before = fsm;
    actions = forward_classifier_sample(&classifier, &fsm, UINT32_C(9),
                                        UINT32_C(30), &result);
    E87_ASSERT_EQ_U32(UINT32_MAX, actions);
    E87_ASSERT_TRUE(bytes_equal(&fsm, &before, sizeof(fsm)));
}

static void assert_timing_fault_cancels_at(uint32_t boundary,
                                           uint32_t offset)
{
    struct e87_button_classifier_config config = base_config();
    struct e87_button_classifier classifier;
    struct e87_button_fsm fsm;
    enum e87_button_classifier_result result;
    enum e87_key_class out = E87_UNSAFE_KEY;
    uint32_t pressed_at = UINT32_C(1000);
    uint32_t fault_at = pressed_at + boundary + offset;
    uint32_t actions;

    config.stable_sample_count = UINT16_C(1);
    classifier = initialized(&config);
    e87_button_init(&fsm);
    (void)release_startup(&classifier, pressed_at - UINT32_C(10), &out);
    actions = forward_classifier_sample(&classifier, &fsm, pressed_at,
                                        UINT32_C(30), &result);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_CHANGED, result);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE, actions);
    actions = forward_classifier_sample(&classifier, &fsm, fault_at,
                                        UINT32_C(30), &result);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNSAFE, result);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE, actions);
    E87_ASSERT_TRUE(fsm.private_rearm_required);
}

E87_TEST(overdue_faults_cancel_around_all_task3a_boundaries)
{
    static const uint32_t boundaries[3] = {3000, 7000, 10000};
    unsigned int index;

    for (index = 0U; index < 3U; index += 1U) {
        assert_timing_fault_cancels_at(boundaries[index], UINT32_MAX);
        assert_timing_fault_cancels_at(boundaries[index], UINT32_C(0));
    }
}

static void assert_raw_fault_cancels_at(uint32_t boundary,
                                        uint32_t fault_raw,
                                        uint32_t offset)
{
    struct e87_button_classifier_config config = base_config();
    struct e87_button_classifier classifier;
    struct e87_button_fsm fsm;
    enum e87_button_classifier_result result;
    enum e87_key_class out = E87_UNSAFE_KEY;
    uint32_t pressed_at = UINT32_C(500);
    uint32_t fault_at = pressed_at + boundary + offset;
    uint32_t actions;

    config.stable_sample_count = UINT16_C(1);
    config.sample_period_ms = UINT16_C(1000);
    config.sample_lateness_ms = UINT16_C(100);
    classifier = initialized(&config);
    e87_button_init(&fsm);
    (void)release_startup(&classifier, pressed_at - UINT32_C(1000), &out);
    actions = forward_classifier_sample(&classifier, &fsm, pressed_at,
                                        UINT32_C(30), &result);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE, actions);
    classifier.private_cadence_baseline_ms = fault_at - UINT32_C(1000);
    actions = forward_classifier_sample(&classifier, &fsm, fault_at,
                                        fault_raw, &result);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNSAFE, result);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE, actions);
    E87_ASSERT_TRUE(fsm.private_rearm_required);
}

E87_TEST(guard_and_range_faults_cancel_around_all_task3a_boundaries)
{
    static const uint32_t boundaries[3] = {3000, 7000, 10000};
    static const uint32_t fault_raws[2] = {20, 101};
    static const uint32_t offsets[2] = {UINT32_MAX, 0};
    unsigned int boundary_index;
    unsigned int raw_index;
    unsigned int offset_index;

    for (boundary_index = 0U; boundary_index < 3U;
         boundary_index += 1U) {
        for (raw_index = 0U; raw_index < 2U; raw_index += 1U) {
            for (offset_index = 0U; offset_index < 2U;
                 offset_index += 1U) {
                assert_raw_fault_cancels_at(
                    boundaries[boundary_index], fault_raws[raw_index],
                    offsets[offset_index]);
            }
        }
    }
}

static void assert_wrapped_fault_cancels_at(uint32_t boundary,
                                             uint32_t fault_raw,
                                             uint32_t offset,
                                             bool cadence_fault)
{
    struct e87_button_classifier_config config = base_config();
    struct e87_button_classifier classifier;
    struct e87_button_fsm fsm;
    enum e87_button_classifier_result result;
    enum e87_key_class out = E87_UNSAFE_KEY;
    const uint32_t pressed_at = UINT32_MAX - UINT32_C(1000);
    const uint32_t fault_at = pressed_at + boundary + offset;
    uint32_t actions;

    config.stable_sample_count = UINT16_C(1);
    classifier = initialized(&config);
    e87_button_init(&fsm);
    (void)release_startup(
        &classifier, pressed_at - (uint32_t)config.sample_period_ms, &out);
    actions = forward_classifier_sample(&classifier, &fsm, pressed_at,
                                        UINT32_C(30), &result);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_CHANGED, result);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE, actions);
    E87_ASSERT_TRUE(fault_at < pressed_at);
    if (!cadence_fault) {
        classifier.private_cadence_baseline_ms =
            fault_at - (uint32_t)config.sample_period_ms;
    }
    actions = forward_classifier_sample(&classifier, &fsm, fault_at,
                                        fault_raw, &result);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNSAFE, result);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE, actions);
    E87_ASSERT_TRUE(fsm.private_rearm_required);
}

E87_TEST(wrap_fault_compositions_allow_only_existing_cleanup_or_expiry)
{
    static const uint32_t boundaries[3] = {3000, 7000, 10000};
    static const uint32_t offsets[2] = {UINT32_MAX, 0};
    struct e87_button_classifier_config config = base_config();
    struct e87_button_classifier classifier;
    struct e87_button_fsm fsm;
    enum e87_button_classifier_result result;
    enum e87_key_class out = E87_UNSAFE_KEY;
    unsigned int boundary_index;
    unsigned int offset_index;
    uint32_t actions;

    for (boundary_index = 0U; boundary_index < 3U;
         boundary_index += 1U) {
        for (offset_index = 0U; offset_index < 2U;
             offset_index += 1U) {
            assert_wrapped_fault_cancels_at(
                boundaries[boundary_index], UINT32_C(30),
                offsets[offset_index], true);
            assert_wrapped_fault_cancels_at(
                boundaries[boundary_index], UINT32_C(20),
                offsets[offset_index], false);
            assert_wrapped_fault_cancels_at(
                boundaries[boundary_index], UINT32_C(101),
                offsets[offset_index], false);
        }
    }

    config.stable_sample_count = UINT16_C(1);
    classifier = initialized(&config);
    (void)release_startup(&classifier, UINT32_MAX - UINT32_C(4), &out);
    e87_button_init(&fsm);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_MAX - UINT32_C(8000),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING | E87_ACTION_UPDATE_WARNING,
                      e87_button_step(&fsm, UINT32_MAX - UINT32_C(1000),
                                      E87_KEY_BUTTON1));
    actions = forward_classifier_sample(&classifier, &fsm, UINT32_C(5),
                                        UINT32_C(20), &result);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNSAFE, result);
    E87_ASSERT_EQ_U32(E87_ACTION_END_UPDATE_WARNING, actions);

    classifier = initialized(&config);
    (void)release_startup(
        &classifier, UINT32_MAX - UINT32_C(1000), &out);
    e87_button_init(&fsm);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE,
                      e87_button_step(&fsm, UINT32_MAX - UINT32_C(4000),
                                      E87_KEY_BUTTON1));
    E87_ASSERT_EQ_U32(E87_ACTION_OPEN_PAIRING,
                      e87_button_step(&fsm, UINT32_MAX - UINT32_C(1000),
                                      E87_KEY_NONE));
    actions = forward_classifier_sample(&classifier, &fsm, UINT32_C(59000),
                                        UINT32_C(30), &result);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNSAFE, result);
    E87_ASSERT_EQ_U32(E87_ACTION_PAIRING_EXPIRED, actions);
}

E87_TEST(stable_none_rearms_task3a_before_a_fresh_press)
{
    struct e87_button_classifier_config config = base_config();
    struct e87_button_classifier classifier;
    struct e87_button_fsm fsm;
    enum e87_button_classifier_result result;
    enum e87_key_class out = E87_UNSAFE_KEY;
    uint32_t actions;

    config.stable_sample_count = UINT16_C(2);
    classifier = initialized(&config);
    e87_button_init(&fsm);
    (void)release_startup(&classifier, UINT32_C(0), &out);
    (void)forward_classifier_sample(&classifier, &fsm, UINT32_C(20),
                                    UINT32_C(30), &result);
    (void)forward_classifier_sample(&classifier, &fsm, UINT32_C(30),
                                    UINT32_C(30), &result);
    actions = forward_classifier_sample(&classifier, &fsm, UINT32_C(40),
                                        UINT32_C(20), &result);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE, actions);
    E87_ASSERT_TRUE(fsm.private_rearm_required);
    actions = forward_classifier_sample(&classifier, &fsm, UINT32_C(50),
                                        UINT32_C(10), &result);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE, actions);
    E87_ASSERT_TRUE(fsm.private_rearm_required);
    actions = forward_classifier_sample(&classifier, &fsm, UINT32_C(60),
                                        UINT32_C(10), &result);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE, actions);
    E87_ASSERT_TRUE(!fsm.private_rearm_required);
    actions = forward_classifier_sample(&classifier, &fsm, UINT32_C(70),
                                        UINT32_C(30), &result);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE, actions);
    actions = forward_classifier_sample(&classifier, &fsm, UINT32_C(80),
                                        UINT32_C(30), &result);
    E87_ASSERT_EQ_U32(E87_ACTION_NONE, actions);
    E87_ASSERT_EQ_U32(UINT32_C(80), fsm.private_button1_started_ms);
}

E87_TEST(cadence_faults_replace_baseline_and_drop_candidates)
{
    struct e87_button_classifier_config config = base_config();
    struct e87_button_classifier classifier = initialized(&config);
    struct e87_button_classifier before;
    enum e87_key_class out = E87_KEY_NONE;

    (void)e87_button_classifier_sample(
        &classifier, UINT32_C(100), UINT32_C(10), &out);
    classifier.private_candidate = E87_KEY_BUTTON1;
    classifier.private_candidate_count = UINT16_C(1);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNSAFE,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(113), UINT32_C(30), &out));
    E87_ASSERT_EQ_U32(UINT32_C(113), classifier.private_cadence_baseline_ms);
    E87_ASSERT_EQ_U32(UINT16_C(0), classifier.private_candidate_count);
    before = classifier;
    out = E87_KEY_BUTTON2;
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_TOO_EARLY,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(122), UINT32_C(10), &out));
    E87_ASSERT_TRUE(bytes_equal(&classifier, &before, sizeof(classifier)));
    E87_ASSERT_EQ_U32(E87_KEY_BUTTON2, out);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNCHANGED,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(123), UINT32_C(10), &out));

    classifier.private_candidate = E87_KEY_BUTTON2;
    classifier.private_candidate_count = UINT16_C(1);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNSAFE,
                      e87_button_classifier_sample(
                          &classifier, UINT32_C(123) + UINT32_C(0x80000000),
                          UINT32_C(10), &out));
    E87_ASSERT_EQ_U32(UINT32_C(123) + UINT32_C(0x80000000),
                      classifier.private_cadence_baseline_ms);
    E87_ASSERT_EQ_U32(UINT16_C(0), classifier.private_candidate_count);
    before = classifier;
    out = E87_KEY_BUTTON1;
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_TOO_EARLY,
                      e87_button_classifier_sample(
                          &classifier,
                          UINT32_C(123) + UINT32_C(0x80000000) + UINT32_C(9),
                          UINT32_C(10), &out));
    E87_ASSERT_TRUE(bytes_equal(&classifier, &before, sizeof(classifier)));
    out = E87_KEY_BUTTON2;
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNCHANGED,
                      e87_button_classifier_sample(
                          &classifier,
                          UINT32_C(123) + UINT32_C(0x80000000) + UINT32_C(10),
                          UINT32_C(10), &out));
    E87_ASSERT_EQ_U32(E87_UNSAFE_KEY, out);
    E87_ASSERT_EQ_U32(
        UINT32_C(123) + UINT32_C(0x80000000) + UINT32_C(10),
        classifier.private_cadence_baseline_ms);
    classifier.private_candidate = E87_KEY_BUTTON1;
    classifier.private_candidate_count = UINT16_C(1);
    E87_ASSERT_EQ_U32(E87_CLASSIFIER_ACCEPTED_UNSAFE,
                      e87_button_classifier_sample(
                          &classifier,
                          UINT32_C(123) + UINT32_C(0x80000000) + UINT32_C(23),
                          UINT32_C(10), &out));
    E87_ASSERT_EQ_U32(
        UINT32_C(123) + UINT32_C(0x80000000) + UINT32_C(23),
        classifier.private_cadence_baseline_ms);
    E87_ASSERT_EQ_U32(E87_UNSAFE_KEY, classifier.private_candidate);
    E87_ASSERT_EQ_U32(UINT16_C(0), classifier.private_candidate_count);
    E87_ASSERT_EQ_U32(E87_UNSAFE_KEY, classifier.private_published);
    E87_ASSERT_EQ_U32(E87_UNSAFE_KEY, out);
    E87_ASSERT_TRUE(classifier.private_quarantined);
}

E87_TEST(valid_init_copies_config_and_sets_exact_private_state)
{
    struct e87_button_classifier_config config = base_config();
    struct e87_button_classifier classifier;
    struct e87_button_classifier_config before = config;

    memset(&classifier, 0xA5, sizeof(classifier));
    E87_ASSERT_TRUE(e87_button_classifier_init(&classifier, &config));
    E87_ASSERT_TRUE(bytes_equal(&config, &before, sizeof(config)));
    E87_ASSERT_TRUE(bytes_equal(&classifier.private_config, &config,
                                sizeof(config)));
    E87_ASSERT_EQ_U32(E87_UNSAFE_KEY, classifier.private_published);
    E87_ASSERT_EQ_U32(E87_UNSAFE_KEY, classifier.private_candidate);
    E87_ASSERT_EQ_U32(UINT32_C(0), classifier.private_cadence_baseline_ms);
    E87_ASSERT_EQ_U32(UINT16_C(0), classifier.private_candidate_count);
    E87_ASSERT_TRUE(classifier.private_initialized);
    E87_ASSERT_TRUE(!classifier.private_have_time);
    E87_ASSERT_TRUE(classifier.private_quarantined);
}

E87_TEST(test_only_evidence_projection_is_a_valid_c_config)
{
    const struct e87_button_classifier_config projected = {
        UINT16_C(1023),
        UINT16_C(10),
        UINT16_C(0),
        UINT16_C(2),
        UINT16_C(1),
        {UINT16_C(100), UINT16_C(199)},
        {UINT16_C(300), UINT16_C(399)},
        {UINT16_C(500), UINT16_C(599)},
        {UINT16_C(700), UINT16_C(799)}
    };
    struct e87_button_classifier classifier;

    E87_ASSERT_TRUE(e87_button_classifier_config_valid(&projected));
    E87_ASSERT_TRUE(e87_button_classifier_init(&classifier, &projected));
    E87_ASSERT_TRUE(bytes_equal(&classifier.private_config, &projected,
                                sizeof(projected)));
}

static const struct e87_test_case cases[] = {
    E87_TEST_CASE(config_rejects_invalid_values_without_mutation),
    E87_TEST_CASE(config_sorts_all_physical_numeric_orders),
    E87_TEST_CASE(window_edges_neighbors_guards_and_outer_domains_are_exact),
    E87_TEST_CASE(both_buttons_is_immediately_ambiguous_and_quarantines),
    E87_TEST_CASE(startup_and_every_fault_quarantine_require_stable_none),
    E87_TEST_CASE(direct_known_transitions_ambiguous_then_fresh_destination),
    E87_TEST_CASE(cadence_edges_are_inclusive_and_early_is_immutable),
    E87_TEST_CASE(raw_adc_width_and_maximum_are_not_narrowed),
    E87_TEST_CASE(candidate_bounce_and_faults_never_accumulate),
    E87_TEST_CASE(error_calls_preserve_every_nonnull_byte),
    E87_TEST_CASE(cadence_and_recovery_survive_uint32_wrap),
    E87_TEST_CASE(too_early_never_advances_task3a_time),
    E87_TEST_CASE(overdue_faults_cancel_around_all_task3a_boundaries),
    E87_TEST_CASE(guard_and_range_faults_cancel_around_all_task3a_boundaries),
    E87_TEST_CASE(wrap_fault_compositions_allow_only_existing_cleanup_or_expiry),
    E87_TEST_CASE(stable_none_rearms_task3a_before_a_fresh_press),
    E87_TEST_CASE(cadence_faults_replace_baseline_and_drop_candidates),
    E87_TEST_CASE(valid_init_copies_config_and_sets_exact_private_state),
    E87_TEST_CASE(test_only_evidence_projection_is_a_valid_c_config)
};

const struct e87_test_suite e87_test_suite = {
    "button_classifier",
    cases,
    sizeof(cases) / sizeof(cases[0])
};
