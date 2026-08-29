#include "test_support.h"
#include "e87/e87_app_core.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define EFFECT_CAPACITY 512U

static int normal_profile_cookie;
static int maintenance_profile_cookie;

struct fake_port {
    struct e87_app_core_effect effects[EFFECT_CAPACITY];
    size_t count;
    size_t reject_index;
    size_t reject_writes_remaining;
    size_t reject_advertising_remaining;
    size_t reject_stop_draws_remaining;
    bool overflow;
    bool reenter_on_draw;
    bool reentered;
    struct e87_app_core *core;
    enum e87_app_core_result reentry_result;
    uint32_t authorization_epoch;
    size_t authorization_query_count;
    size_t release_close_count;
    size_t fail_release_after_close_remaining;
    bool writes_enabled;
    bool authorization_active;
    bool advertising_enabled;
};

static bool bytes_equal(const void *left, const void *right, size_t length)
{
    return memcmp(left, right, length) == 0;
}

static void fake_reset(struct fake_port *fake)
{
    memset(fake, 0, sizeof(*fake));
    fake->reject_index = SIZE_MAX;
    fake->reentry_result = E87_APP_CORE_RESULT_NO_CHANGE;
}

static bool fake_set_writes_enabled(struct fake_port *fake,
                                    bool enabled,
                                    uint32_t *out_epoch)
{
    if (fake == NULL || out_epoch == NULL) {
        return false;
    }
    if (!enabled) {
        if (fake->authorization_epoch == UINT32_MAX) {
            fake->writes_enabled = false;
            fake->authorization_active = false;
            return false;
        }
        fake->authorization_epoch += UINT32_C(1);
        fake->writes_enabled = false;
        fake->authorization_active = false;
    } else if (!fake->writes_enabled) {
        if (fake->authorization_epoch == UINT32_MAX) {
            return false;
        }
        fake->authorization_epoch += UINT32_C(1);
        fake->writes_enabled = true;
        fake->authorization_active = false;
    }
    *out_epoch = fake->authorization_epoch;
    return true;
}

static bool fake_authorization_epoch_is_active(void *context,
                                               uint32_t epoch)
{
    struct fake_port *fake = (struct fake_port *)context;

    fake->authorization_query_count += 1U;
    return fake->writes_enabled && fake->authorization_active &&
           epoch == fake->authorization_epoch;
}

static bool fake_authorize(struct fake_port *fake)
{
    if (fake == NULL || !fake->writes_enabled ||
        fake->authorization_epoch == UINT32_MAX) {
        return false;
    }
    fake->authorization_epoch += UINT32_C(1);
    fake->authorization_active = true;
    return true;
}

static bool fake_invalidate_authorization(struct fake_port *fake)
{
    if (fake == NULL || fake->authorization_epoch == UINT32_MAX) {
        if (fake != NULL) {
            fake->authorization_active = false;
        }
        return false;
    }
    fake->authorization_epoch += UINT32_C(1);
    fake->authorization_active = false;
    return true;
}

static bool fake_emit(void *context, struct e87_app_core_effect *effect)
{
    struct fake_port *fake = (struct fake_port *)context;
    const size_t index = fake->count;
    bool accepted = index != fake->reject_index;

    if (fake->count >= EFFECT_CAPACITY) {
        fake->overflow = true;
        return false;
    }
    if (effect->type == E87_APP_CORE_EFFECT_BLE_INITIALIZE_NORMAL_PROFILE) {
        effect->data.profile.app_handle = &normal_profile_cookie;
    } else if (effect->type ==
               E87_APP_CORE_EFFECT_BLE_ADOPT_MAINTENANCE_PROFILE) {
        effect->data.profile.app_handle = &maintenance_profile_cookie;
    }
    if (accepted && effect->type == E87_APP_CORE_EFFECT_BLE_SET_WRITES &&
        fake->reject_writes_remaining > 0U) {
        fake->reject_writes_remaining -= 1U;
        accepted = false;
    }
    if (accepted &&
        (effect->type == E87_APP_CORE_EFFECT_BLE_SET_ADVERTISING ||
         effect->type ==
             E87_APP_CORE_EFFECT_BLE_VERIFY_MAINTENANCE_STOPPED) &&
        fake->reject_advertising_remaining > 0U) {
        fake->reject_advertising_remaining -= 1U;
        accepted = false;
    }
    if (accepted && effect->type == E87_APP_CORE_EFFECT_POWER &&
        effect->data.power.command == E87_POWER_COMMAND_STOP_DRAWS &&
        fake->reject_stop_draws_remaining > 0U) {
        fake->reject_stop_draws_remaining -= 1U;
        accepted = false;
    }
    if (effect->type == E87_APP_CORE_EFFECT_BLE_SET_WRITES && accepted) {
        accepted = fake_set_writes_enabled(
            fake, effect->data.writes.enabled,
            &effect->data.writes.authorization_epoch);
    } else if (effect->type == E87_APP_CORE_EFFECT_BLE_RELEASE_PROFILE &&
               accepted) {
        fake->release_close_count += 1U;
        if (fake->fail_release_after_close_remaining > 0U) {
            fake->fail_release_after_close_remaining -= 1U;
            accepted = false;
        }
    } else if (effect->type == E87_APP_CORE_EFFECT_BLE_SET_ADVERTISING &&
               accepted) {
        fake->advertising_enabled = effect->data.advertising.enabled;
    } else if (effect->type ==
                   E87_APP_CORE_EFFECT_BLE_VERIFY_MAINTENANCE_ADVERTISING &&
               accepted) {
        fake->advertising_enabled = true;
    } else if (effect->type ==
                   E87_APP_CORE_EFFECT_BLE_VERIFY_MAINTENANCE_STOPPED &&
               accepted) {
        fake->advertising_enabled = false;
    }
    fake->effects[fake->count] = *effect;
    fake->count += 1U;

    if (fake->reenter_on_draw && !fake->reentered &&
        effect->type == E87_APP_CORE_EFFECT_DRAW) {
        const struct e87_app_core_event nested = {
            E87_APP_CORE_EVENT_POLL, effect->now_ms, {{0}}
        };

        fake->reentered = true;
        fake->reentry_result = e87_app_core_step(fake->core, &nested);
    }
    return accepted;
}

static struct e87_button_classifier_config classifier_config(void)
{
    const struct e87_button_classifier_config config = {
        UINT16_C(100),
        UINT16_C(10),
        UINT16_C(20000),
        UINT16_C(1),
        UINT16_C(1),
        {UINT16_C(10), UINT16_C(19)},
        {UINT16_C(30), UINT16_C(39)},
        {UINT16_C(50), UINT16_C(59)},
        {UINT16_C(70), UINT16_C(79)}
    };

    return config;
}

static bool init_core(struct e87_app_core *core, struct fake_port *fake)
{
    const struct e87_app_core_config config = {
        classifier_config()
    };
    const struct e87_app_core_port port = {
        fake, fake_emit, fake_authorization_epoch_is_active
    };

    fake_reset(fake);
    fake->core = core;
    memset(core, 0xA5, sizeof(*core));
    return e87_app_core_init(core, &config, &port);
}

static struct e87_app_core_event boot_event(uint32_t now_ms, bool has_bond,
                                            enum e87_recovery_reset_cause cause,
                                            enum e87_key_class key,
                                            bool external_power)
{
    struct e87_app_core_event event = {
        E87_APP_CORE_EVENT_BOOT, now_ms, {{0}}
    };

    event.data.boot.has_bond = has_bond;
    event.data.boot.reset_cause = cause;
    event.data.boot.key = key;
    event.data.boot.charge_snapshot.external_power_online = external_power;
    event.data.boot.charge_snapshot.phase = E87_CHARGE_PHASE_UNKNOWN;
    return event;
}

static bool boot_normal(struct e87_app_core *core, struct fake_port *fake,
                        bool has_bond, uint32_t now_ms)
{
    const struct e87_app_core_event event =
        boot_event(now_ms, has_bond, E87_RESET_CAUSE_POWER_ON,
                   E87_KEY_NONE, false);

    return init_core(core, fake) &&
           e87_app_core_step(core, &event) == E87_APP_CORE_RESULT_UPDATED;
}

static struct e87_app_core_event adc_event(uint32_t now_ms, uint32_t raw_adc)
{
    struct e87_app_core_event event = {
        E87_APP_CORE_EVENT_BUTTON_ADC_SAMPLE, now_ms, {{0}}
    };

    event.data.raw_adc = raw_adc;
    return event;
}

static struct e87_app_core_event poll_event(uint32_t now_ms)
{
    const struct e87_app_core_event event = {
        E87_APP_CORE_EVENT_POLL, now_ms, {{0}}
    };

    return event;
}

static struct e87_app_core_event semantic_event(
                                                 const struct fake_port *fake,
                                                 uint32_t now_ms,
                                                 uint8_t day,
                                                 uint8_t week)
{
    struct e87_app_core_event event = {
        E87_APP_CORE_EVENT_SEMANTIC_PACKET, now_ms, {{0}}
    };
    static const uint8_t suffix[5] = {0, 0xBF, 0x06, 0, 0};

    event.data.semantic.authorization_epoch =
        fake->authorization_epoch;
    event.data.semantic.packet[0] = E87_STATE_PROTOCOL_VERSION;
    event.data.semantic.packet[1] = day;
    event.data.semantic.packet[2] = week;
    memcpy(&event.data.semantic.packet[3], suffix, sizeof(suffix));
    return event;
}

static bool authorize_semantic_session(struct fake_port *fake)
{
    return fake_authorize(fake);
}

static struct e87_app_core_event profile_link_event(uint32_t now_ms,
                                                    bool connected)
{
    struct e87_app_core_event event = {
        connected ? E87_APP_CORE_EVENT_PROFILE_CONNECTED
                  : E87_APP_CORE_EVENT_PROFILE_DISCONNECTED,
        now_ms,
        {{0}}
    };

    event.data.profile_link.app_handle = &normal_profile_cookie;
    event.data.profile_link.connection_handle = UINT16_C(0x42);
    return event;
}

static struct e87_app_core_event power_event(
    uint32_t now_ms, enum e87_power_event_type type,
    bool external_power_online,
    enum e87_power_wake_classification wake)
{
    struct e87_app_core_event event = {
        E87_APP_CORE_EVENT_POWER, now_ms, {{0}}
    };

    event.data.power.type = type;
    event.data.power.charge_snapshot.external_power_online =
        external_power_online;
    event.data.power.charge_snapshot.phase = E87_CHARGE_PHASE_UNKNOWN;
    event.data.power.wake_classification = wake;
    return event;
}

static struct e87_app_core_event maintenance_event(
    uint32_t now_ms, enum e87_maintenance_event_type type)
{
    struct e87_app_core_event event = {
        E87_APP_CORE_EVENT_MAINTENANCE, now_ms, {{0}}
    };

    event.data.maintenance.type = type;
    event.data.maintenance.now_ms = now_ms;
    event.data.maintenance.power.charger_phase =
        E87_CHARGE_PHASE_UNKNOWN;
    return event;
}

static size_t effect_count(const struct fake_port *fake,
                           enum e87_app_core_effect_type type)
{
    size_t count = 0U;
    size_t index;

    for (index = 0U; index < fake->count; index += 1U) {
        if (fake->effects[index].type == type) {
            count += 1U;
        }
    }
    return count;
}

static size_t maintenance_command_count(
    const struct fake_port *fake,
    enum e87_maintenance_command command)
{
    size_t count = 0U;
    size_t index;

    for (index = 0U; index < fake->count; index += 1U) {
        if (fake->effects[index].type ==
                E87_APP_CORE_EFFECT_MAINTENANCE &&
            fake->effects[index].data.maintenance.command == command) {
            count += 1U;
        }
    }
    return count;
}

static bool drive_button1_to_maintenance_request(
    struct e87_app_core *core, uint32_t base_ms)
{
    struct e87_app_core_event event;

    event = adc_event(base_ms + UINT32_C(10), UINT32_C(10));
    if (e87_app_core_step(core, &event) == E87_APP_CORE_RESULT_ERROR) {
        return false;
    }
    event = adc_event(base_ms + UINT32_C(20), UINT32_C(30));
    if (e87_app_core_step(core, &event) == E87_APP_CORE_RESULT_ERROR) {
        return false;
    }
    event = adc_event(base_ms + UINT32_C(3020), UINT32_C(30));
    if (e87_app_core_step(core, &event) == E87_APP_CORE_RESULT_ERROR) {
        return false;
    }
    event = adc_event(base_ms + UINT32_C(7020), UINT32_C(30));
    if (e87_app_core_step(core, &event) == E87_APP_CORE_RESULT_ERROR) {
        return false;
    }
    event = adc_event(base_ms + UINT32_C(10020), UINT32_C(30));
    return e87_app_core_step(core, &event) != E87_APP_CORE_RESULT_ERROR;
}

static bool finish_maintenance_entry(struct e87_app_core *core,
                                     uint32_t base_ms)
{
    struct e87_app_core_event event;

    event = poll_event(base_ms + UINT32_C(10030));
    if (e87_app_core_step(core, &event) == E87_APP_CORE_RESULT_ERROR) {
        return false;
    }
    event = poll_event(base_ms + UINT32_C(10040));
    if (e87_app_core_step(core, &event) == E87_APP_CORE_RESULT_ERROR) {
        return false;
    }
    event = poll_event(base_ms + UINT32_C(10050));
    if (e87_app_core_step(core, &event) == E87_APP_CORE_RESULT_ERROR) {
        return false;
    }
    event = adc_event(base_ms + UINT32_C(10060), UINT32_C(10));
    if (e87_app_core_step(core, &event) == E87_APP_CORE_RESULT_ERROR) {
        return false;
    }
    event = poll_event(base_ms + UINT32_C(10070));
    if (e87_app_core_step(core, &event) == E87_APP_CORE_RESULT_ERROR) {
        return false;
    }
    event = poll_event(base_ms + UINT32_C(10080));
    if (e87_app_core_step(core, &event) == E87_APP_CORE_RESULT_ERROR) {
        return false;
    }
    event = poll_event(base_ms + UINT32_C(10090));
    return e87_app_core_step(core, &event) != E87_APP_CORE_RESULT_ERROR;
}

static bool enter_maintenance(struct e87_app_core *core,
                              struct fake_port *fake,
                              uint32_t base_ms)
{
    struct e87_app_core_view view;

    return boot_normal(core, fake, true, base_ms) &&
           drive_button1_to_maintenance_request(core, base_ms) &&
           finish_maintenance_entry(core, base_ms) &&
           e87_app_core_get_view(core, &view) &&
           view.phase == E87_APP_CORE_PHASE_MAINTENANCE;
}

E87_TEST(init_is_atomic_side_effect_free_and_rejects_bad_contracts)
{
    struct e87_app_core core;
    struct e87_app_core before;
    struct e87_app_core_config config = {
        classifier_config()
    };
    struct e87_app_core_port port;
    struct fake_port fake;

    fake_reset(&fake);
    port.context = &fake;
    port.emit = fake_emit;
    port.authorization_epoch_is_active =
        fake_authorization_epoch_is_active;
    memset(&core, 0x5A, sizeof(core));
    before = core;
    E87_ASSERT_TRUE(!e87_app_core_init(NULL, &config, &port));
    E87_ASSERT_TRUE(!e87_app_core_init(&core, NULL, &port));
    E87_ASSERT_TRUE(bytes_equal(&core, &before, sizeof(core)));
    E87_ASSERT_TRUE(!e87_app_core_init(&core, &config, NULL));
    E87_ASSERT_TRUE(bytes_equal(&core, &before, sizeof(core)));
    port.emit = NULL;
    E87_ASSERT_TRUE(!e87_app_core_init(&core, &config, &port));
    E87_ASSERT_TRUE(bytes_equal(&core, &before, sizeof(core)));
    port.emit = fake_emit;
    port.authorization_epoch_is_active = NULL;
    E87_ASSERT_TRUE(!e87_app_core_init(&core, &config, &port));
    E87_ASSERT_TRUE(bytes_equal(&core, &before, sizeof(core)));
    config.button_classifier.stable_sample_count = UINT16_C(0);
    port.authorization_epoch_is_active =
        fake_authorization_epoch_is_active;
    E87_ASSERT_TRUE(!e87_app_core_init(&core, &config, &port));
    E87_ASSERT_TRUE(bytes_equal(&core, &before, sizeof(core)));

    E87_ASSERT_TRUE(init_core(&core, &fake));
    E87_ASSERT_EQ_U32(UINT32_C(0), fake.count);
}

E87_TEST(cold_boot_selects_pair_or_wait_and_never_restores_metrics)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_view view;
    struct e87_app_core_event event;

    E87_ASSERT_TRUE(boot_normal(&core, &fake, false, UINT32_C(100)));
    E87_ASSERT_EQ_U32(UINT32_C(6), fake.count);
    E87_ASSERT_EQ_U32(E87_APP_CORE_EFFECT_RECOVERY, fake.effects[0].type);
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_DISARM_PINR_RESET,
                      fake.effects[0].data.recovery.command);
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_ARM_PINR_RESET_16S,
                      fake.effects[1].data.recovery.command);
    E87_ASSERT_EQ_U32(E87_APP_CORE_EFFECT_BLE_INITIALIZE_NORMAL_PROFILE,
                      fake.effects[2].type);
    E87_ASSERT_EQ_U32(E87_APP_CORE_EFFECT_BLE_SET_WRITES,
                      fake.effects[3].type);
    E87_ASSERT_TRUE(fake.effects[3].data.writes.enabled);
    E87_ASSERT_TRUE(
        fake.effects[3].data.writes.authorization_epoch > UINT32_C(0));
    E87_ASSERT_EQ_U32(E87_APP_CORE_EFFECT_BLE_SET_ADVERTISING,
                      fake.effects[4].type);
    E87_ASSERT_TRUE(fake.effects[4].data.advertising.enabled);
    E87_ASSERT_EQ_U32(E87_APP_CORE_EFFECT_DRAW, fake.effects[5].type);
    E87_ASSERT_EQ_U32(E87_UI_SCREEN_PAIR_ME_NOW,
                      fake.effects[5].data.draw.model.screen);
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(E87_APP_CORE_PHASE_NORMAL, view.phase);
    E87_ASSERT_TRUE(!view.semantic.has_metrics);

    E87_ASSERT_TRUE(boot_normal(&core, &fake, true, UINT32_C(200)));
    E87_ASSERT_EQ_U32(E87_UI_SCREEN_WAITING_FOR_PHONE,
                      fake.effects[5].data.draw.model.screen);
    event = boot_event(UINT32_C(201), true, E87_RESET_CAUSE_POWER_ON,
                       E87_KEY_NONE, false);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_ERROR,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(UINT32_C(6), fake.count);
}

E87_TEST(changed_semantics_redraw_once_and_duplicate_is_silent)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_view view;
    struct e87_app_core_event event;
    size_t before;

    E87_ASSERT_TRUE(boot_normal(&core, &fake, true, UINT32_C(0)));
    E87_ASSERT_TRUE(authorize_semantic_session(&fake));
    before = fake.count;
    event = semantic_event(&fake, UINT32_C(1),
                           UINT8_C(25), UINT8_C(75));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_UPDATED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(before + UINT32_C(1), fake.count);
    E87_ASSERT_EQ_U32(E87_APP_CORE_EFFECT_DRAW,
                      fake.effects[before].type);
    E87_ASSERT_EQ_U32(E87_UI_SCREEN_FACE,
                      fake.effects[before].data.draw.model.screen);
    E87_ASSERT_EQ_U32(UINT32_C(25),
                      fake.effects[before].data.draw.model.metrics.day);
    E87_ASSERT_EQ_U32(UINT32_C(75),
                      fake.effects[before].data.draw.model.metrics.week);

    before = fake.count;
    event.now_ms = UINT32_C(2);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_NO_CHANGE,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(before, fake.count);
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_TRUE(view.semantic.has_metrics);
    E87_ASSERT_EQ_U32(UINT32_C(1), view.semantic.revision);

    before = fake.count;
    event.data.semantic.packet[1] = UINT8_C(101);
    event.now_ms = UINT32_C(3);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_ERROR,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(before, fake.count);
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(UINT32_C(25), view.semantic.metrics.day);
    E87_ASSERT_EQ_U32(UINT32_C(1), view.semantic.revision);
}

E87_TEST(semantic_ingress_requires_active_target_authorization)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_view view;
    struct e87_app_core_event event;
    size_t before;

    E87_ASSERT_TRUE(boot_normal(&core, &fake, true, UINT32_C(0)));
    before = fake.count;
    event = semantic_event(&fake, UINT32_C(1),
                           UINT8_C(12), UINT8_C(34));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_NO_CHANGE,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(before, fake.count);
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_TRUE(!view.semantic.has_metrics);

    E87_ASSERT_TRUE(authorize_semantic_session(&fake));
    before = fake.count;
    event = semantic_event(&fake, UINT32_C(2),
                           UINT8_C(12), UINT8_C(34));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_UPDATED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(before + UINT32_C(1), fake.count);
    E87_ASSERT_EQ_U32(E87_APP_CORE_EFFECT_DRAW,
                      fake.effects[before].type);
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(UINT32_C(1), view.semantic.revision);
}

E87_TEST(bond_change_reveals_a_committed_face_without_recommit)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_view view;
    struct e87_app_core_event event;
    size_t before;

    E87_ASSERT_TRUE(boot_normal(&core, &fake, false, UINT32_C(0)));
    E87_ASSERT_TRUE(authorize_semantic_session(&fake));
    before = fake.count;
    event = semantic_event(&fake, UINT32_C(1),
                           UINT8_C(13), UINT8_C(35));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_UPDATED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(before, fake.count);
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(E87_UI_SCREEN_PAIR_ME_NOW,
                      view.render_model.screen);
    E87_ASSERT_EQ_U32(UINT32_C(1), view.semantic.revision);

    memset(&event, 0, sizeof(event));
    event.type = E87_APP_CORE_EVENT_BOND_CHANGED;
    event.now_ms = UINT32_C(2);
    event.data.has_bond = true;
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_UPDATED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(before + UINT32_C(1), fake.count);
    E87_ASSERT_EQ_U32(E87_APP_CORE_EFFECT_DRAW,
                      fake.effects[before].type);
    E87_ASSERT_EQ_U32(E87_UI_SCREEN_FACE,
                      fake.effects[before].data.draw.model.screen);
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(UINT32_C(1), view.semantic.revision);

    before = fake.count;
    event.now_ms = UINT32_C(3);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_NO_CHANGE,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(before, fake.count);
}

E87_TEST(queued_semantics_are_dropped_after_every_write_gate_close)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_view view;
    struct e87_app_core_event stale;
    struct e87_app_core_event event;
    size_t before;
    size_t queries_before;
    unsigned int loss;

    E87_ASSERT_TRUE(boot_normal(&core, &fake, true, UINT32_C(0)));
    E87_ASSERT_TRUE(authorize_semantic_session(&fake));
    event = adc_event(UINT32_C(10), UINT32_C(10));
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    event = adc_event(UINT32_C(20), UINT32_C(50));
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    stale = semantic_event(&fake, UINT32_C(31),
                           UINT8_C(20), UINT8_C(30));
    event = power_event(UINT32_C(30), E87_POWER_EVENT_LCD_IDLE,
                        false, E87_POWER_WAKE_NONE);
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    E87_ASSERT_TRUE(!fake.writes_enabled);
    before = fake.count;
    queries_before = fake.authorization_query_count;
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_NO_CHANGE,
                      e87_app_core_step(&core, &stale));
    E87_ASSERT_EQ_U32(before, fake.count);
    E87_ASSERT_EQ_U32(queries_before, fake.authorization_query_count);
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_TRUE(!view.semantic.has_metrics);

    E87_ASSERT_TRUE(boot_normal(&core, &fake, true, UINT32_C(0)));
    E87_ASSERT_TRUE(authorize_semantic_session(&fake));
    stale = semantic_event(&fake, UINT32_C(10091),
                           UINT8_C(21), UINT8_C(31));
    E87_ASSERT_TRUE(drive_button1_to_maintenance_request(
        &core, UINT32_C(0)));
    E87_ASSERT_TRUE(finish_maintenance_entry(&core, UINT32_C(0)));
    E87_ASSERT_TRUE(!fake.writes_enabled);
    before = fake.count;
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_NO_CHANGE,
                      e87_app_core_step(&core, &stale));
    E87_ASSERT_EQ_U32(before, fake.count);
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(E87_APP_CORE_PHASE_MAINTENANCE, view.phase);
    E87_ASSERT_TRUE(!view.semantic.has_metrics);

    E87_ASSERT_TRUE(boot_normal(&core, &fake, true, UINT32_C(0)));
    /* Disconnect, encryption, durable-owner, and link replacement losses. */
    for (loss = 0U; loss < 4U; loss += 1U) {
        E87_ASSERT_TRUE(authorize_semantic_session(&fake));
        stale = semantic_event(&fake, UINT32_C(1) + loss,
                               (uint8_t)(UINT8_C(22) + loss),
                               UINT8_C(32));
        E87_ASSERT_TRUE(fake_invalidate_authorization(&fake));
        before = fake.count;
        E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_NO_CHANGE,
                          e87_app_core_step(&core, &stale));
        E87_ASSERT_EQ_U32(before, fake.count);
    }
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_TRUE(!view.semantic.has_metrics);
}

E87_TEST(reconnect_requires_a_new_epoch_and_rejects_the_old_epoch)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_view view;
    struct e87_app_core_event old_event;
    struct e87_app_core_event new_event;
    uint32_t old_epoch;
    uint32_t invalid_epoch;

    E87_ASSERT_TRUE(boot_normal(&core, &fake, true, UINT32_C(0)));
    E87_ASSERT_TRUE(authorize_semantic_session(&fake));
    old_event = semantic_event(&fake, UINT32_C(1),
                               UINT8_C(40), UINT8_C(50));
    old_epoch = old_event.data.semantic.authorization_epoch;
    E87_ASSERT_TRUE(fake_invalidate_authorization(&fake));
    invalid_epoch = fake.authorization_epoch;
    E87_ASSERT_TRUE(invalid_epoch > old_epoch);

    E87_ASSERT_TRUE(authorize_semantic_session(&fake));
    E87_ASSERT_TRUE(fake.writes_enabled);
    E87_ASSERT_TRUE(fake.authorization_epoch > invalid_epoch);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_NO_CHANGE,
                      e87_app_core_step(&core, &old_event));
    new_event = semantic_event(&fake, UINT32_C(2),
                               UINT8_C(40), UINT8_C(50));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_UPDATED,
                      e87_app_core_step(&core, &new_event));
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_TRUE(view.semantic.has_metrics);
    E87_ASSERT_EQ_U32(UINT32_C(1), view.semantic.revision);
}

E87_TEST(authorization_epoch_wrap_and_aba_fail_closed)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_view view;
    struct e87_app_core_event event;

    E87_ASSERT_TRUE(boot_normal(&core, &fake, true, UINT32_C(0)));
    event = adc_event(UINT32_C(10), UINT32_C(10));
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    event = adc_event(UINT32_C(20), UINT32_C(50));
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    fake.authorization_epoch = UINT32_MAX;
    fake.authorization_active = false;
    event = power_event(UINT32_C(30), E87_POWER_EVENT_LCD_IDLE,
                        false, E87_POWER_WAKE_NONE);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_FAIL_CLOSED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(E87_APP_CORE_PHASE_FAIL_CLOSED, view.phase);
    E87_ASSERT_TRUE(!fake.writes_enabled);

    E87_ASSERT_TRUE(boot_normal(&core, &fake, true, UINT32_C(100)));
    E87_ASSERT_TRUE(authorize_semantic_session(&fake));
    event = semantic_event(&fake, UINT32_C(101),
                           UINT8_C(70), UINT8_C(80));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_UPDATED,
                      e87_app_core_step(&core, &event));
    fake.authorization_epoch = UINT32_C(1);
    fake.authorization_active = true;
    event = semantic_event(&fake, UINT32_C(102),
                           UINT8_C(71), UINT8_C(81));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_FAIL_CLOSED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(E87_APP_CORE_PHASE_FAIL_CLOSED, view.phase);
    E87_ASSERT_TRUE(!fake.writes_enabled);

    E87_ASSERT_TRUE(boot_normal(&core, &fake, true, UINT32_C(200)));
    fake.authorization_epoch = UINT32_MAX;
    fake.writes_enabled = true;
    fake.authorization_active = true;
    event = semantic_event(&fake, UINT32_C(201),
                           UINT8_C(72), UINT8_C(82));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_FAIL_CLOSED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(E87_APP_CORE_PHASE_FAIL_CLOSED, view.phase);
    E87_ASSERT_TRUE(!fake.writes_enabled);
}

E87_TEST(button_tap_overlay_expires_and_threshold_screens_are_ordered)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_event event;
    size_t before;

    E87_ASSERT_TRUE(boot_normal(&core, &fake, false, UINT32_C(0)));
    event = adc_event(UINT32_C(10), UINT32_C(10));
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    event = adc_event(UINT32_C(20), UINT32_C(30));
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    before = fake.count;
    event = adc_event(UINT32_C(30), UINT32_C(10));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_UPDATED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(before + UINT32_C(1), fake.count);
    E87_ASSERT_TRUE(fake.effects[before].data.draw.model.battery_overlay);
    event = poll_event(UINT32_C(2529));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_NO_CHANGE,
                      e87_app_core_step(&core, &event));
    event = poll_event(UINT32_C(2530));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_UPDATED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_TRUE(!fake.effects[fake.count - 1U].data.draw.model.battery_overlay);

    E87_ASSERT_TRUE(boot_normal(&core, &fake, false, UINT32_C(10000)));
    event = adc_event(UINT32_C(10010), UINT32_C(10));
    (void)e87_app_core_step(&core, &event);
    event = adc_event(UINT32_C(10020), UINT32_C(30));
    (void)e87_app_core_step(&core, &event);
    before = fake.count;
    event = adc_event(UINT32_C(13020), UINT32_C(30));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_UPDATED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(E87_APP_CORE_EFFECT_PAIRING,
                      fake.effects[before].type);
    E87_ASSERT_TRUE(fake.effects[before].data.pairing.enabled);
    E87_ASSERT_EQ_U32(E87_UI_SCREEN_PAIRING,
                      fake.effects[before + 1U].data.draw.model.screen);
    before = fake.count;
    event = adc_event(UINT32_C(17020), UINT32_C(30));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_UPDATED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(before + UINT32_C(1), fake.count);
    E87_ASSERT_EQ_U32(E87_UI_SCREEN_UPDATE_WARNING,
                      fake.effects[before].data.draw.model.screen);
}

E87_TEST(poll_never_synthesizes_missing_button_samples)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_event event;
    size_t before;

    E87_ASSERT_TRUE(boot_normal(&core, &fake, false, UINT32_C(0)));
    event = adc_event(UINT32_C(10), UINT32_C(10));
    (void)e87_app_core_step(&core, &event);
    event = adc_event(UINT32_C(20), UINT32_C(30));
    (void)e87_app_core_step(&core, &event);
    before = fake.count;
    event = poll_event(UINT32_C(10020));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_NO_CHANGE,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(before, fake.count);
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      effect_count(&fake,
                                   E87_APP_CORE_EFFECT_BLE_RELEASE_PROFILE));
}

E87_TEST(profile_callbacks_never_reopen_closed_authorization)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_event event;
    size_t before;

    E87_ASSERT_TRUE(boot_normal(&core, &fake, true, UINT32_C(0)));
    event = profile_link_event(UINT32_C(1), true);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_UPDATED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_TRUE(drive_button1_to_maintenance_request(
        &core, UINT32_C(0)));
    E87_ASSERT_TRUE(!fake.writes_enabled);
    before = fake.count;
    event = profile_link_event(UINT32_C(10021), true);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_NO_CHANGE,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(before, fake.count);
    E87_ASSERT_TRUE(!fake.writes_enabled);

    event = poll_event(UINT32_C(10030));
    (void)e87_app_core_step(&core, &event);
    event = poll_event(UINT32_C(10040));
    (void)e87_app_core_step(&core, &event);
    event = poll_event(UINT32_C(10050));
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    E87_ASSERT_EQ_U32(
        UINT32_C(1),
        effect_count(&fake,
                     E87_APP_CORE_EFFECT_BLE_REQUEST_DISCONNECT));
    event = profile_link_event(UINT32_C(10060), false);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_UPDATED,
                      e87_app_core_step(&core, &event));
    before = fake.count;
    event = profile_link_event(UINT32_C(10061), false);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_NO_CHANGE,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(before, fake.count);
    E87_ASSERT_TRUE(!fake.writes_enabled);

    E87_ASSERT_TRUE(boot_normal(&core, &fake, true, UINT32_C(20000)));
    event = adc_event(UINT32_C(20010), UINT32_C(10));
    (void)e87_app_core_step(&core, &event);
    event = adc_event(UINT32_C(20020), UINT32_C(50));
    (void)e87_app_core_step(&core, &event);
    event = power_event(UINT32_C(20030), E87_POWER_EVENT_LCD_IDLE,
                        false, E87_POWER_WAKE_NONE);
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    E87_ASSERT_TRUE(!fake.writes_enabled);
    before = fake.count;
    event = profile_link_event(UINT32_C(20031), true);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_UPDATED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(before, fake.count);
    E87_ASSERT_TRUE(!fake.writes_enabled);
}

E87_TEST(stale_profile_callbacks_are_silent_in_maintenance)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_view view;
    struct e87_app_core_event event;
    size_t before;

    E87_ASSERT_TRUE(enter_maintenance(&core, &fake, UINT32_C(0)));
    before = fake.count;
    event = profile_link_event(UINT32_C(10100), true);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_NO_CHANGE,
                      e87_app_core_step(&core, &event));
    event = profile_link_event(UINT32_C(10110), false);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_NO_CHANGE,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(before, fake.count);
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(E87_APP_CORE_PHASE_MAINTENANCE, view.phase);
    E87_ASSERT_TRUE(!fake.writes_enabled);
}

E87_TEST(non_normal_phases_ignore_user_sleep_and_hold_actions)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_view view;
    struct e87_app_core_event event;
    size_t before;

    E87_ASSERT_TRUE(enter_maintenance(&core, &fake, UINT32_C(0)));
    before = fake.count;
    event = adc_event(UINT32_C(10100), UINT32_C(10));
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_FAIL_CLOSED);
    event = adc_event(UINT32_C(10110), UINT32_C(50));
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_FAIL_CLOSED);
    event = power_event(UINT32_C(10120), E87_POWER_EVENT_MANUAL_SLEEP,
                        false, E87_POWER_WAKE_NONE);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_NO_CHANGE,
                      e87_app_core_step(&core, &event));
    event = power_event(UINT32_C(10130), E87_POWER_EVENT_LCD_IDLE,
                        false, E87_POWER_WAKE_NONE);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_NO_CHANGE,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(before, fake.count);
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(E87_APP_CORE_PHASE_MAINTENANCE, view.phase);
    E87_ASSERT_TRUE(!view.manual_sleep);

    event = maintenance_event(UINT32_C(10140),
                              E87_MAINTENANCE_EVENT_CANCEL);
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    event = maintenance_event(UINT32_C(10150),
                              E87_MAINTENANCE_EVENT_TRANSPORT_QUIESCED);
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    event = maintenance_event(UINT32_C(10160),
                              E87_MAINTENANCE_EVENT_RCSP_RELEASE_STATUS);
    event.data.maintenance.rcsp_handle_present = false;
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(E87_APP_CORE_PHASE_RETURNING_NORMAL, view.phase);
    before = fake.count;
    event = power_event(UINT32_C(10170), E87_POWER_EVENT_MANUAL_SLEEP,
                        false, E87_POWER_WAKE_NONE);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_NO_CHANGE,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(before, fake.count);

    E87_ASSERT_TRUE(boot_normal(&core, &fake, true, UINT32_C(20000)));
    E87_ASSERT_TRUE(drive_button1_to_maintenance_request(
        &core, UINT32_C(20000)));
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(E87_APP_CORE_PHASE_ENTERING_MAINTENANCE,
                      view.phase);
    before = fake.count;
    event = power_event(UINT32_C(30021), E87_POWER_EVENT_MANUAL_SLEEP,
                        false, E87_POWER_WAKE_NONE);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_NO_CHANGE,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(before, fake.count);
}

E87_TEST(maintenance_entry_waits_for_release_barrier_and_initializes_rcsp_once)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_view view;
    struct e87_app_core_event event;
    size_t before;

    E87_ASSERT_TRUE(boot_normal(&core, &fake, true, UINT32_C(0)));
    E87_ASSERT_TRUE(drive_button1_to_maintenance_request(&core,
                                                        UINT32_C(0)));
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(E87_APP_CORE_PHASE_ENTERING_MAINTENANCE,
                      view.phase);
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      effect_count(&fake,
                                   E87_APP_CORE_EFFECT_BLE_ADOPT_MAINTENANCE_PROFILE));
    E87_ASSERT_EQ_U32(E87_UI_SCREEN_MAINTENANCE,
                      fake.effects[fake.count - 1U].data.draw.model.screen);

    event = poll_event(UINT32_C(10030));
    (void)e87_app_core_step(&core, &event);
    event = poll_event(UINT32_C(10040));
    (void)e87_app_core_step(&core, &event);
    before = fake.count;
    event = poll_event(UINT32_C(10050));
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    E87_ASSERT_EQ_U32(E87_APP_CORE_EFFECT_BLE_RELEASE_PROFILE,
                      fake.effects[before].type);
    E87_ASSERT_EQ_U32(E87_BLE_MODE_NORMAL,
                      fake.effects[before].data.profile.mode);
    E87_ASSERT_EQ_U32(UINT32_C(1), fake.release_close_count);
    E87_ASSERT_EQ_U32(E87_APP_CORE_EFFECT_RECOVERY,
                      fake.effects[before + 1U].type);
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                      fake.effects[before + 1U].data.recovery.command);
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      effect_count(&fake,
                                   E87_APP_CORE_EFFECT_BLE_ADOPT_MAINTENANCE_PROFILE));

    event = adc_event(UINT32_C(10060), UINT32_C(10));
    before = fake.count;
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    E87_ASSERT_EQ_U32(E87_APP_CORE_EFFECT_RECOVERY,
                      fake.effects[before].type);
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_ARM_PINR_RESET_16S,
                      fake.effects[before].data.recovery.command);
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      effect_count(&fake,
                                   E87_APP_CORE_EFFECT_BLE_ADOPT_MAINTENANCE_PROFILE));

    event = poll_event(UINT32_C(10070));
    before = fake.count;
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    E87_ASSERT_EQ_U32(E87_APP_CORE_EFFECT_MAINTENANCE,
                      fake.effects[before].type);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_RCSP_INTERFACE_INIT,
                      fake.effects[before].data.maintenance.command);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_RCSP_INIT,
                      fake.effects[before + 1U].data.maintenance.command);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_RCSP_BLE_INIT,
                      fake.effects[before + 2U].data.maintenance.command);
    E87_ASSERT_EQ_U32(E87_APP_CORE_EFFECT_BLE_ADOPT_MAINTENANCE_PROFILE,
                      fake.effects[before + 3U].type);
    E87_ASSERT_EQ_U32(UINT32_C(1),
                      effect_count(&fake,
                                   E87_APP_CORE_EFFECT_BLE_ADOPT_MAINTENANCE_PROFILE));

    event = poll_event(UINT32_C(10080));
    (void)e87_app_core_step(&core, &event);
    event = poll_event(UINT32_C(10090));
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(E87_APP_CORE_PHASE_MAINTENANCE, view.phase);
    E87_ASSERT_EQ_U32(E87_BLE_MODE_MAINTENANCE, view.ble_mode);
    E87_ASSERT_EQ_U32(UINT32_C(1),
                      effect_count(&fake,
                                   E87_APP_CORE_EFFECT_BLE_VERIFY_MAINTENANCE_ADVERTISING));
}

E87_TEST(early_maintenance_cancel_is_deferred_and_never_opens_advertising)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_view view;
    struct e87_app_core_event event;
    size_t before;
    unsigned int step;

    E87_ASSERT_TRUE(boot_normal(&core, &fake, true, UINT32_C(0)));
    E87_ASSERT_TRUE(drive_button1_to_maintenance_request(
        &core, UINT32_C(0)));
    event = poll_event(UINT32_C(10030));
    (void)e87_app_core_step(&core, &event);
    event = poll_event(UINT32_C(10040));
    (void)e87_app_core_step(&core, &event);
    event = poll_event(UINT32_C(10050));
    (void)e87_app_core_step(&core, &event);
    event = adc_event(UINT32_C(10060), UINT32_C(10));
    (void)e87_app_core_step(&core, &event);
    event = poll_event(UINT32_C(10070));
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    E87_ASSERT_EQ_U32(
        UINT32_C(1),
        effect_count(&fake,
                     E87_APP_CORE_EFFECT_BLE_ADOPT_MAINTENANCE_PROFILE));
    E87_ASSERT_EQ_U32(
        UINT32_C(0),
        effect_count(&fake,
                     E87_APP_CORE_EFFECT_BLE_VERIFY_MAINTENANCE_ADVERTISING));

    before = fake.count;
    event = maintenance_event(UINT32_C(10071),
                              E87_MAINTENANCE_EVENT_CANCEL);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_WAITING,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(before, fake.count);
    event = maintenance_event(UINT32_C(10072),
                              E87_MAINTENANCE_EVENT_TRANSPORT_QUIESCED);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_WAITING,
                      e87_app_core_step(&core, &event));
    event = maintenance_event(UINT32_C(10073),
                              E87_MAINTENANCE_EVENT_RCSP_RELEASE_STATUS);
    event.data.maintenance.rcsp_handle_present = false;
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_WAITING,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(before, fake.count);
    event = poll_event(UINT32_C(10080));
    (void)e87_app_core_step(&core, &event);
    event = poll_event(UINT32_C(10090));
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    E87_ASSERT_EQ_U32(
        UINT32_C(0),
        effect_count(&fake,
                     E87_APP_CORE_EFFECT_BLE_VERIFY_MAINTENANCE_ADVERTISING));
    E87_ASSERT_TRUE(
        effect_count(&fake, E87_APP_CORE_EFFECT_MAINTENANCE) >= 6U);
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(E87_APP_CORE_PHASE_RETURNING_NORMAL, view.phase);

    for (step = 0U; step < 6U; step += 1U) {
        event = poll_event(UINT32_C(10100) +
                           (uint32_t)step * UINT32_C(10));
        E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                        E87_APP_CORE_RESULT_ERROR);
    }
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(E87_APP_CORE_PHASE_NORMAL, view.phase);
}

E87_TEST(maintenance_cancel_fully_tears_down_before_normal_profile_and_redraw)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_view view;
    struct e87_app_core_event event;
    size_t before;
    unsigned int step;

    E87_ASSERT_TRUE(enter_maintenance(&core, &fake, UINT32_C(0)));
    event = maintenance_event(UINT32_C(10100),
                              E87_MAINTENANCE_EVENT_CANCEL);
    before = fake.count;
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_REJECT_COMMANDS,
                      fake.effects[before].data.maintenance.command);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_STOP_ADVERTISING,
                      fake.effects[before + 1U].data.maintenance.command);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_DISCONNECT,
                      fake.effects[before + 2U].data.maintenance.command);

    event = maintenance_event(UINT32_C(10110),
                              E87_MAINTENANCE_EVENT_TRANSPORT_QUIESCED);
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_RCSP_BLE_EXIT,
                      fake.effects[fake.count - 1U].data.maintenance.command);
    event = maintenance_event(UINT32_C(10120),
                              E87_MAINTENANCE_EVENT_RCSP_RELEASE_STATUS);
    event.data.maintenance.rcsp_handle_present = false;
    before = fake.count;
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_RCSP_INTERFACE_EXIT,
                      fake.effects[before].data.maintenance.command);
    E87_ASSERT_EQ_U32(E87_APP_CORE_EFFECT_BLE_SET_WRITES,
                      fake.effects[before + 1U].type);
    E87_ASSERT_TRUE(!fake.effects[before + 1U].data.writes.enabled);
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(E87_APP_CORE_PHASE_RETURNING_NORMAL, view.phase);

    for (step = 0U; step < 6U; step += 1U) {
        event = poll_event(UINT32_C(10130) + (uint32_t)step * UINT32_C(10));
        E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                        E87_APP_CORE_RESULT_ERROR);
    }
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(E87_APP_CORE_PHASE_NORMAL, view.phase);
    E87_ASSERT_EQ_U32(E87_BLE_MODE_NORMAL, view.ble_mode);
    E87_ASSERT_EQ_U32(E87_APP_CORE_EFFECT_BLE_VERIFY_MAINTENANCE_STOPPED,
                      fake.effects[before + 2U].type);
    E87_ASSERT_EQ_U32(UINT32_C(1),
                      effect_count(&fake,
                                   E87_APP_CORE_EFFECT_BLE_VERIFY_MAINTENANCE_RELEASED));
    E87_ASSERT_EQ_U32(UINT32_C(2),
                      effect_count(&fake,
                                   E87_APP_CORE_EFFECT_BLE_INITIALIZE_NORMAL_PROFILE));
    E87_ASSERT_EQ_U32(E87_UI_SCREEN_WAITING_FOR_PHONE,
                      fake.effects[fake.count - 1U].data.draw.model.screen);
}

E87_TEST(manual_sleep_preserves_semantics_and_charge_then_wake_redraws_before_ble)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_view view;
    struct e87_app_core_event event;
    size_t before;
    uint32_t sleep_epoch;

    E87_ASSERT_TRUE(boot_normal(&core, &fake, true, UINT32_C(0)));
    E87_ASSERT_TRUE(authorize_semantic_session(&fake));
    event = semantic_event(&fake, UINT32_C(4),
                           UINT8_C(10), UINT8_C(20));
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    event = adc_event(UINT32_C(10), UINT32_C(10));
    (void)e87_app_core_step(&core, &event);
    event = adc_event(UINT32_C(20), UINT32_C(50));
    before = fake.count;
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    E87_ASSERT_EQ_U32(E87_POWER_COMMAND_STOP_DRAWS,
                      fake.effects[before].data.power.command);
    E87_ASSERT_EQ_U32(E87_POWER_COMMAND_WAIT_LCD_IDLE,
                      fake.effects[before + 1U].data.power.command);

    event = power_event(UINT32_C(30), E87_POWER_EVENT_LCD_IDLE, false,
                        E87_POWER_WAKE_NONE);
    before = fake.count;
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    E87_ASSERT_EQ_U32(UINT32_C(6), fake.count - before);
    E87_ASSERT_EQ_U32(E87_APP_CORE_EFFECT_BLE_SET_WRITES,
                      fake.effects[before + 2U].type);
    E87_ASSERT_TRUE(!fake.effects[before + 2U].data.writes.enabled);
    E87_ASSERT_EQ_U32(E87_POWER_COMMAND_BLE_STOP_DISCONNECT,
                      fake.effects[before + 3U].data.power.command);
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_TRUE(view.manual_sleep);
    E87_ASSERT_TRUE(!view.drawing_enabled);
    sleep_epoch = fake.authorization_epoch;

    before = fake.count;
    event = power_event(UINT32_C(40),
                        E87_POWER_EVENT_CHARGE_SNAPSHOT, true,
                        E87_POWER_WAKE_NONE);
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    event = power_event(UINT32_C(50), E87_POWER_EVENT_CHARGE_SNAPSHOT, true,
                        E87_POWER_WAKE_NONE);
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    E87_ASSERT_EQ_U32(before, fake.count);
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_TRUE(view.manual_sleep);
    E87_ASSERT_TRUE(view.external_power_online);
    E87_ASSERT_EQ_U32(UINT32_C(10), view.semantic.metrics.day);

    event = power_event(UINT32_C(60), E87_POWER_EVENT_GPIO_WAKE, true,
                        E87_POWER_WAKE_NONE);
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    before = fake.count;
    event = power_event(UINT32_C(70), E87_POWER_EVENT_WAKE_CLASSIFIED, true,
                        E87_POWER_WAKE_BUTTON2);
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    E87_ASSERT_EQ_U32(E87_POWER_COMMAND_DISPLAY_EXIT_SLEEP,
                      fake.effects[before].data.power.command);
    E87_ASSERT_EQ_U32(E87_APP_CORE_EFFECT_DRAW,
                      fake.effects[before + 1U].type);
    E87_ASSERT_EQ_U32(E87_UI_SCREEN_FACE,
                      fake.effects[before + 1U].data.draw.model.screen);
    E87_ASSERT_EQ_U32(UINT32_C(10),
                      fake.effects[before + 1U].data.draw.model.metrics.day);
    E87_ASSERT_EQ_U32(E87_POWER_COMMAND_BACKLIGHT_ON,
                      fake.effects[before + 2U].data.power.command);
    E87_ASSERT_EQ_U32(E87_POWER_COMMAND_BLE_START,
                      fake.effects[before + 3U].data.power.command);
    E87_ASSERT_EQ_U32(E87_APP_CORE_EFFECT_BLE_SET_WRITES,
                      fake.effects[before + 4U].type);
    E87_ASSERT_TRUE(fake.effects[before + 4U].data.writes.enabled);
    E87_ASSERT_TRUE(
        fake.effects[before + 4U].data.writes.authorization_epoch >
        sleep_epoch);
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_TRUE(!view.manual_sleep);
    E87_ASSERT_TRUE(view.drawing_enabled);
}

E87_TEST(charger_edges_preserve_active_face_without_redraw)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_view view;
    struct e87_app_core_event event;
    size_t before;

    E87_ASSERT_TRUE(boot_normal(&core, &fake, true, UINT32_C(0)));
    E87_ASSERT_TRUE(authorize_semantic_session(&fake));
    event = semantic_event(&fake, UINT32_C(4),
                           UINT8_C(55), UINT8_C(66));
    (void)e87_app_core_step(&core, &event);
    before = fake.count;
    event = power_event(UINT32_C(5),
                        E87_POWER_EVENT_CHARGE_SNAPSHOT, true,
                        E87_POWER_WAKE_NONE);
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    event = power_event(UINT32_C(6), E87_POWER_EVENT_CHARGE_SNAPSHOT, true,
                        E87_POWER_WAKE_NONE);
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    event = power_event(UINT32_C(7), E87_POWER_EVENT_CHARGE_SNAPSHOT, true,
                        E87_POWER_WAKE_NONE);
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    event = power_event(UINT32_C(8), E87_POWER_EVENT_CHARGE_SNAPSHOT, false,
                        E87_POWER_WAKE_NONE);
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    event = power_event(UINT32_C(9),
                        E87_POWER_EVENT_CHARGE_SNAPSHOT, false,
                        E87_POWER_WAKE_NONE);
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    E87_ASSERT_EQ_U32(before, fake.count);
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(E87_UI_SCREEN_FACE, view.render_model.screen);
    E87_ASSERT_EQ_U32(UINT32_C(55), view.semantic.metrics.day);
    E87_ASSERT_TRUE(!view.external_power_online);
}

E87_TEST(profile_step_failure_retries_without_double_initialization)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_view view;
    struct e87_app_core_event event;
    size_t release_count;

    E87_ASSERT_TRUE(boot_normal(&core, &fake, true, UINT32_C(0)));
    E87_ASSERT_TRUE(drive_button1_to_maintenance_request(&core,
                                                        UINT32_C(0)));
    event = poll_event(UINT32_C(10030));
    (void)e87_app_core_step(&core, &event);
    event = poll_event(UINT32_C(10040));
    (void)e87_app_core_step(&core, &event);
    fake.fail_release_after_close_remaining = 1U;
    event = poll_event(UINT32_C(10050));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_WAITING,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(E87_APP_CORE_PHASE_ENTERING_MAINTENANCE,
                      view.phase);
    release_count = effect_count(&fake,
                                  E87_APP_CORE_EFFECT_BLE_RELEASE_PROFILE);
    E87_ASSERT_EQ_U32(UINT32_C(1), fake.release_close_count);
    event = poll_event(UINT32_C(10060));
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    E87_ASSERT_EQ_U32(release_count + UINT32_C(1),
                      effect_count(&fake,
                                   E87_APP_CORE_EFFECT_BLE_RELEASE_PROFILE));
    E87_ASSERT_EQ_U32(UINT32_C(2), fake.release_close_count);
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      effect_count(&fake,
                                   E87_APP_CORE_EFFECT_BLE_ADOPT_MAINTENANCE_PROFILE));
}

E87_TEST(rejected_write_gate_latches_fail_closed_before_profile_release)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_view view;
    struct e87_app_core_event event;
    size_t before;

    E87_ASSERT_TRUE(boot_normal(&core, &fake, true, UINT32_C(0)));
    event = adc_event(UINT32_C(10), UINT32_C(10));
    (void)e87_app_core_step(&core, &event);
    event = adc_event(UINT32_C(20), UINT32_C(30));
    (void)e87_app_core_step(&core, &event);
    event = adc_event(UINT32_C(3020), UINT32_C(30));
    (void)e87_app_core_step(&core, &event);
    event = adc_event(UINT32_C(7020), UINT32_C(30));
    (void)e87_app_core_step(&core, &event);

    before = fake.count;
    fake.reject_index = before + 2U;
    event = adc_event(UINT32_C(10020), UINT32_C(30));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_FAIL_CLOSED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(E87_APP_CORE_EFFECT_PAIRING,
                      fake.effects[before].type);
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_DISARM_PINR_RESET,
                      fake.effects[before + 1U].data.recovery.command);
    E87_ASSERT_EQ_U32(E87_APP_CORE_EFFECT_BLE_SET_WRITES,
                      fake.effects[before + 2U].type);
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(E87_APP_CORE_PHASE_FAIL_CLOSED, view.phase);
    event = poll_event(UINT32_C(10030));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_FAIL_CLOSED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      effect_count(&fake,
                                   E87_APP_CORE_EFFECT_BLE_RELEASE_PROFILE));
}

E87_TEST(recovery_stop_timeout_latches_fail_closed_without_initializing_target)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_view view;
    struct e87_app_core_event event;

    E87_ASSERT_TRUE(boot_normal(&core, &fake, true, UINT32_C(0)));
    E87_ASSERT_TRUE(drive_button1_to_maintenance_request(&core,
                                                        UINT32_C(0)));
    event = poll_event(UINT32_C(10030));
    (void)e87_app_core_step(&core, &event);
    event = poll_event(UINT32_C(10040));
    (void)e87_app_core_step(&core, &event);
    fake.reject_index = fake.count;
    event = poll_event(UINT32_C(10050));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_WAITING,
                      e87_app_core_step(&core, &event));
    fake.reject_index = fake.count;
    event = poll_event(UINT32_C(15020));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_FAIL_CLOSED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(E87_APP_CORE_PHASE_FAIL_CLOSED, view.phase);
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      effect_count(&fake,
                                   E87_APP_CORE_EFFECT_BLE_ADOPT_MAINTENANCE_PROFILE));
}

E87_TEST(pinr_boot_waits_for_stable_release_before_creating_rcsp)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_view view;
    struct e87_app_core_event event;
    size_t before;

    E87_ASSERT_TRUE(init_core(&core, &fake));
    event = boot_event(UINT32_C(0), true,
                       E87_RESET_CAUSE_P33_PPINR,
                       E87_KEY_BUTTON1, false);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_UPDATED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_DISARM_PINR_RESET,
                      fake.effects[0].data.recovery.command);
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                      fake.effects[1].data.recovery.command);
    E87_ASSERT_EQ_U32(E87_APP_CORE_EFFECT_DRAW,
                      fake.effects[2].type);
    E87_ASSERT_EQ_U32(E87_UI_SCREEN_MAINTENANCE,
                      fake.effects[2].data.draw.model.screen);
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      effect_count(&fake,
                                   E87_APP_CORE_EFFECT_BLE_INITIALIZE_NORMAL_PROFILE));
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      effect_count(&fake,
                                   E87_APP_CORE_EFFECT_BLE_ADOPT_MAINTENANCE_PROFILE));

    before = fake.count;
    event = poll_event(UINT32_C(10));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_WAITING,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_FEED_WATCHDOG,
                      fake.effects[before].data.recovery.command);
    event = adc_event(UINT32_C(20), UINT32_C(10));
    before = fake.count;
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    E87_ASSERT_EQ_U32(E87_RECOVERY_COMMAND_ARM_PINR_RESET_16S,
                      fake.effects[before].data.recovery.command);
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      effect_count(&fake,
                                   E87_APP_CORE_EFFECT_BLE_ADOPT_MAINTENANCE_PROFILE));

    event = poll_event(UINT32_C(30));
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(E87_APP_CORE_PHASE_MAINTENANCE, view.phase);
    E87_ASSERT_EQ_U32(UINT32_C(1),
                      effect_count(&fake,
                                   E87_APP_CORE_EFFECT_BLE_ADOPT_MAINTENANCE_PROFILE));
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      effect_count(&fake,
                                   E87_APP_CORE_EFFECT_BLE_INITIALIZE_NORMAL_PROFILE));
}

E87_TEST(partial_rcsp_initialization_cleans_up_and_latches_fail_closed)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_view view;
    struct e87_app_core_event event;
    size_t before;

    E87_ASSERT_TRUE(boot_normal(&core, &fake, true, UINT32_C(0)));
    E87_ASSERT_TRUE(drive_button1_to_maintenance_request(&core,
                                                        UINT32_C(0)));
    event = poll_event(UINT32_C(10030));
    (void)e87_app_core_step(&core, &event);
    event = poll_event(UINT32_C(10040));
    (void)e87_app_core_step(&core, &event);
    event = poll_event(UINT32_C(10050));
    (void)e87_app_core_step(&core, &event);
    event = adc_event(UINT32_C(10060), UINT32_C(10));
    (void)e87_app_core_step(&core, &event);

    before = fake.count;
    fake.reject_index = before + 1U;
    event = poll_event(UINT32_C(10070));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_FAIL_CLOSED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_RCSP_INTERFACE_INIT,
                      fake.effects[before].data.maintenance.command);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_RCSP_INIT,
                      fake.effects[before + 1U].data.maintenance.command);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_REJECT_COMMANDS,
                      fake.effects[before + 2U].data.maintenance.command);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_STOP_ADVERTISING,
                      fake.effects[before + 3U].data.maintenance.command);
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_DISCONNECT,
                      fake.effects[before + 4U].data.maintenance.command);
    E87_ASSERT_EQ_U32(UINT32_C(0),
                      effect_count(&fake,
                                   E87_APP_CORE_EFFECT_BLE_ADOPT_MAINTENANCE_PROFILE));
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(E87_APP_CORE_PHASE_FAIL_CLOSED, view.phase);
    E87_ASSERT_TRUE(!view.drawing_enabled);

    fake.reject_index = SIZE_MAX;
    event = maintenance_event(UINT32_C(10080),
                              E87_MAINTENANCE_EVENT_TRANSPORT_QUIESCED);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_FAIL_CLOSED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_RCSP_BLE_EXIT,
                      fake.effects[fake.count - 1U].data.maintenance.command);
    event = maintenance_event(UINT32_C(10090),
                              E87_MAINTENANCE_EVENT_RCSP_RELEASE_STATUS);
    event.data.maintenance.rcsp_handle_present = false;
    before = fake.count;
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_FAIL_CLOSED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(E87_MAINTENANCE_COMMAND_RCSP_INTERFACE_EXIT,
                      fake.effects[before].data.maintenance.command);
    E87_ASSERT_EQ_U32(UINT32_C(1),
                      effect_count(&fake,
                                   E87_APP_CORE_EFFECT_BLE_INITIALIZE_NORMAL_PROFILE));
}

E87_TEST(invalid_backward_and_reentrant_events_never_mutate_or_render)
{
    struct e87_app_core core;
    struct e87_app_core before;
    struct fake_port fake;
    struct e87_app_core_event event;
    size_t before_count;

    E87_ASSERT_TRUE(init_core(&core, &fake));
    event = poll_event(UINT32_C(0));
    before = core;
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_ERROR,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_TRUE(bytes_equal(&core, &before, sizeof(core)));
    E87_ASSERT_EQ_U32(UINT32_C(0), fake.count);

    fake.reenter_on_draw = true;
    event = boot_event(UINT32_C(100), false, E87_RESET_CAUSE_POWER_ON,
                       E87_KEY_NONE, false);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_UPDATED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_TRUE(fake.reentered);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_REENTRANT,
                      fake.reentry_result);
    before_count = fake.count;
    event = poll_event(UINT32_C(99));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_ERROR,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(before_count, fake.count);
}

E87_TEST(wrap_safe_overlay_and_transition_time_are_accepted)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_event event;
    const uint32_t start = UINT32_MAX - UINT32_C(100);

    E87_ASSERT_TRUE(boot_normal(&core, &fake, false, start));
    event = adc_event(start + UINT32_C(10), UINT32_C(10));
    (void)e87_app_core_step(&core, &event);
    event = adc_event(start + UINT32_C(20), UINT32_C(30));
    (void)e87_app_core_step(&core, &event);
    event = adc_event(start + UINT32_C(30), UINT32_C(10));
    E87_ASSERT_TRUE(e87_app_core_step(&core, &event) !=
                    E87_APP_CORE_RESULT_ERROR);
    event = poll_event(start + UINT32_C(2529));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_NO_CHANGE,
                      e87_app_core_step(&core, &event));
    event = poll_event(start + UINT32_C(2530));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_UPDATED,
                      e87_app_core_step(&core, &event));
}

E87_TEST(draw_failure_preserves_atomic_semantics_but_closes_all_activity)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_view view;
    struct e87_app_core_event event;

    E87_ASSERT_TRUE(boot_normal(&core, &fake, true, UINT32_C(0)));
    E87_ASSERT_TRUE(authorize_semantic_session(&fake));
    fake.reject_index = fake.count;
    event = semantic_event(&fake, UINT32_C(4),
                           UINT8_C(88), UINT8_C(99));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_FAIL_CLOSED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(E87_APP_CORE_PHASE_FAIL_CLOSED, view.phase);
    E87_ASSERT_TRUE(view.semantic.has_metrics);
    E87_ASSERT_EQ_U32(UINT32_C(88), view.semantic.metrics.day);
    E87_ASSERT_TRUE(!view.drawing_enabled);
    E87_ASSERT_TRUE(effect_count(&fake,
                                 E87_APP_CORE_EFFECT_BLE_SET_WRITES) >= 2U);
    E87_ASSERT_TRUE(effect_count(&fake,
                                 E87_APP_CORE_EFFECT_BLE_SET_ADVERTISING) >= 2U);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_FAIL_CLOSED,
                      e87_app_core_step(&core, &event));
}

E87_TEST(fail_closed_shutdown_retries_until_every_barrier_is_closed)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_view view;
    struct e87_app_core_event event;
    size_t settled_count;

    E87_ASSERT_TRUE(boot_normal(&core, &fake, true, UINT32_C(0)));
    E87_ASSERT_TRUE(authorize_semantic_session(&fake));
    fake.reject_index = fake.count;
    fake.reject_stop_draws_remaining = 2U;
    fake.reject_writes_remaining = 2U;
    fake.reject_advertising_remaining = 2U;
    event = semantic_event(&fake, UINT32_C(1),
                           UINT8_C(90), UINT8_C(91));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_FAIL_CLOSED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_TRUE(fake.writes_enabled);
    E87_ASSERT_TRUE(fake.advertising_enabled);

    event = poll_event(UINT32_C(2));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_FAIL_CLOSED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_TRUE(fake.writes_enabled);
    E87_ASSERT_TRUE(fake.advertising_enabled);
    event = poll_event(UINT32_C(3));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_FAIL_CLOSED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_TRUE(!fake.writes_enabled);
    E87_ASSERT_TRUE(!fake.advertising_enabled);
    E87_ASSERT_TRUE(e87_app_core_get_view(&core, &view));
    E87_ASSERT_EQ_U32(E87_APP_CORE_PHASE_FAIL_CLOSED, view.phase);
    E87_ASSERT_TRUE(!view.drawing_enabled);
    E87_ASSERT_EQ_U32(UINT32_C(1), view.semantic.revision);
    E87_ASSERT_EQ_U32(
        UINT32_C(0),
        effect_count(&fake, E87_APP_CORE_EFFECT_BLE_RELEASE_PROFILE));

    settled_count = fake.count;
    event = poll_event(UINT32_C(4));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_FAIL_CLOSED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(settled_count, fake.count);
}

E87_TEST(fail_closed_defers_rcsp_release_until_shutdown_barriers_close)
{
    struct e87_app_core core;
    struct fake_port fake;
    struct e87_app_core_event event;
    size_t interface_exit_before;

    E87_ASSERT_TRUE(enter_maintenance(&core, &fake, UINT32_C(0)));
    E87_ASSERT_TRUE(fake.advertising_enabled);
    interface_exit_before = maintenance_command_count(
        &fake, E87_MAINTENANCE_COMMAND_RCSP_INTERFACE_EXIT);
    fake.reject_index = fake.count;
    fake.reject_stop_draws_remaining = 3U;
    fake.reject_writes_remaining = 3U;
    fake.reject_advertising_remaining = 3U;
    memset(&event, 0, sizeof(event));
    event.type = E87_APP_CORE_EVENT_MAINTENANCE_UI;
    event.now_ms = UINT32_C(10100);
    event.data.maintenance_ui.phase = E87_UI_MAINTENANCE_UPDATE_ERROR;
    event.data.maintenance_ui.progress_percent = UINT8_C(50);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_FAIL_CLOSED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_TRUE(fake.advertising_enabled);

    event = maintenance_event(UINT32_C(10110),
                              E87_MAINTENANCE_EVENT_TRANSPORT_QUIESCED);
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_FAIL_CLOSED,
                      e87_app_core_step(&core, &event));
    event = maintenance_event(UINT32_C(10120),
                              E87_MAINTENANCE_EVENT_RCSP_RELEASE_STATUS);
    event.data.maintenance.rcsp_handle_present = false;
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_FAIL_CLOSED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_EQ_U32(
        interface_exit_before,
        maintenance_command_count(
            &fake, E87_MAINTENANCE_COMMAND_RCSP_INTERFACE_EXIT));
    E87_ASSERT_TRUE(fake.advertising_enabled);

    event = poll_event(UINT32_C(10130));
    E87_ASSERT_EQ_U32(E87_APP_CORE_RESULT_FAIL_CLOSED,
                      e87_app_core_step(&core, &event));
    E87_ASSERT_TRUE(!fake.writes_enabled);
    E87_ASSERT_TRUE(!fake.advertising_enabled);
    E87_ASSERT_EQ_U32(
        interface_exit_before + UINT32_C(1),
        maintenance_command_count(
            &fake, E87_MAINTENANCE_COMMAND_RCSP_INTERFACE_EXIT));
    E87_ASSERT_EQ_U32(
        UINT32_C(1),
        effect_count(&fake,
                     E87_APP_CORE_EFFECT_BLE_INITIALIZE_NORMAL_PROFILE));
}

static const struct e87_test_case app_core_cases[] = {
    E87_TEST_CASE(init_is_atomic_side_effect_free_and_rejects_bad_contracts),
    E87_TEST_CASE(cold_boot_selects_pair_or_wait_and_never_restores_metrics),
    E87_TEST_CASE(changed_semantics_redraw_once_and_duplicate_is_silent),
    E87_TEST_CASE(semantic_ingress_requires_active_target_authorization),
    E87_TEST_CASE(bond_change_reveals_a_committed_face_without_recommit),
    E87_TEST_CASE(queued_semantics_are_dropped_after_every_write_gate_close),
    E87_TEST_CASE(reconnect_requires_a_new_epoch_and_rejects_the_old_epoch),
    E87_TEST_CASE(authorization_epoch_wrap_and_aba_fail_closed),
    E87_TEST_CASE(button_tap_overlay_expires_and_threshold_screens_are_ordered),
    E87_TEST_CASE(poll_never_synthesizes_missing_button_samples),
    E87_TEST_CASE(profile_callbacks_never_reopen_closed_authorization),
    E87_TEST_CASE(stale_profile_callbacks_are_silent_in_maintenance),
    E87_TEST_CASE(non_normal_phases_ignore_user_sleep_and_hold_actions),
    E87_TEST_CASE(maintenance_entry_waits_for_release_barrier_and_initializes_rcsp_once),
    E87_TEST_CASE(early_maintenance_cancel_is_deferred_and_never_opens_advertising),
    E87_TEST_CASE(maintenance_cancel_fully_tears_down_before_normal_profile_and_redraw),
    E87_TEST_CASE(manual_sleep_preserves_semantics_and_charge_then_wake_redraws_before_ble),
    E87_TEST_CASE(charger_edges_preserve_active_face_without_redraw),
    E87_TEST_CASE(profile_step_failure_retries_without_double_initialization),
    E87_TEST_CASE(rejected_write_gate_latches_fail_closed_before_profile_release),
    E87_TEST_CASE(recovery_stop_timeout_latches_fail_closed_without_initializing_target),
    E87_TEST_CASE(pinr_boot_waits_for_stable_release_before_creating_rcsp),
    E87_TEST_CASE(partial_rcsp_initialization_cleans_up_and_latches_fail_closed),
    E87_TEST_CASE(invalid_backward_and_reentrant_events_never_mutate_or_render),
    E87_TEST_CASE(wrap_safe_overlay_and_transition_time_are_accepted),
    E87_TEST_CASE(draw_failure_preserves_atomic_semantics_but_closes_all_activity),
    E87_TEST_CASE(fail_closed_shutdown_retries_until_every_barrier_is_closed),
    E87_TEST_CASE(fail_closed_defers_rcsp_release_until_shutdown_barriers_close),
};

const struct e87_test_suite e87_test_suite = {
    "full-lifecycle-coordinator",
    app_core_cases,
    sizeof(app_core_cases) / sizeof(app_core_cases[0])
};
