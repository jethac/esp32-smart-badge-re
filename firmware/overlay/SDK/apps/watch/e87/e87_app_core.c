#include "e87/e87_app_core.h"

#include <string.h>

static e87_state_lock_token_t state_enter(void *context)
{
    (void)context;
    return (e87_state_lock_token_t)0;
}

static void state_leave(void *context, e87_state_lock_token_t token)
{
    (void)context;
    (void)token;
}

static bool key_is_valid(enum e87_key_class key)
{
    return key == E87_KEY_NONE || key == E87_KEY_BUTTON1 ||
           key == E87_KEY_BUTTON2 || key == E87_KEY_AMBIGUOUS;
}

static bool reset_cause_is_valid(enum e87_recovery_reset_cause cause)
{
    return cause == E87_RESET_CAUSE_POWER_ON ||
           cause == E87_RESET_CAUSE_SOFTWARE ||
           cause == E87_RESET_CAUSE_WATCHDOG ||
           cause == E87_RESET_CAUSE_P33_PPINR ||
           cause == E87_RESET_CAUSE_OTHER;
}

static bool power_event_type_is_valid(enum e87_power_event_type type)
{
    return type == E87_POWER_EVENT_CHARGE_SNAPSHOT ||
           type == E87_POWER_EVENT_MANUAL_SLEEP ||
           type == E87_POWER_EVENT_LCD_IDLE ||
           type == E87_POWER_EVENT_GPIO_WAKE ||
           type == E87_POWER_EVENT_WAKE_CLASSIFIED;
}

static bool wake_classification_is_valid(
    enum e87_power_wake_classification classification)
{
    return classification == E87_POWER_WAKE_NONE ||
           classification == E87_POWER_WAKE_BUTTON1 ||
           classification == E87_POWER_WAKE_BUTTON2 ||
           classification == E87_POWER_WAKE_AMBIGUOUS ||
           classification == E87_POWER_WAKE_NOISE;
}

static bool maintenance_event_type_is_valid(
    enum e87_maintenance_event_type type)
{
    return type == E87_MAINTENANCE_EVENT_ENTER_AFTER_NORMAL_DISCONNECT ||
           type == E87_MAINTENANCE_EVENT_POLL ||
           type == E87_MAINTENANCE_EVENT_AUTHENTICATED ||
           type == E87_MAINTENANCE_EVENT_HOST_DISCONNECTED ||
           type == E87_MAINTENANCE_EVENT_CANCEL ||
           type == E87_MAINTENANCE_EVENT_FAILURE ||
           type == E87_MAINTENANCE_EVENT_TRANSPORT_QUIESCED ||
           type == E87_MAINTENANCE_EVENT_POWER_SAMPLE ||
           type == E87_MAINTENANCE_EVENT_RCSP_RELEASE_STATUS;
}

static bool charger_phase_is_valid(enum e87_charge_phase phase)
{
    return phase == E87_CHARGE_PHASE_UNKNOWN ||
           phase == E87_CHARGE_PHASE_CHARGING ||
           phase == E87_CHARGE_PHASE_FULL ||
           phase == E87_CHARGE_PHASE_CLOSED ||
           phase == E87_CHARGE_PHASE_FAULT;
}

static bool battery_state_is_valid(enum e87_ui_battery_state state)
{
    return state == E87_UI_BATTERY_VALID ||
           state == E87_UI_BATTERY_INVALID_STALE ||
           state == E87_UI_BATTERY_UNAVAILABLE_FAULT;
}

static bool maintenance_ui_phase_is_valid(
    enum e87_ui_maintenance_phase phase)
{
    return phase == E87_UI_MAINTENANCE_RELEASE_BUTTON ||
           phase == E87_UI_MAINTENANCE_WAITING_FOR_PHONE ||
           phase == E87_UI_MAINTENANCE_PHONE_READY ||
           phase == E87_UI_MAINTENANCE_UPDATING ||
           phase == E87_UI_MAINTENANCE_UPDATE_ERROR;
}

static bool event_type_is_valid(enum e87_app_core_event_type type)
{
    return type == E87_APP_CORE_EVENT_BOOT ||
           type == E87_APP_CORE_EVENT_POLL ||
           type == E87_APP_CORE_EVENT_BUTTON_ADC_SAMPLE ||
           type == E87_APP_CORE_EVENT_SEMANTIC_PACKET ||
           type == E87_APP_CORE_EVENT_POWER ||
           type == E87_APP_CORE_EVENT_MAINTENANCE ||
           type == E87_APP_CORE_EVENT_PROFILE_CONNECTED ||
           type == E87_APP_CORE_EVENT_PROFILE_DISCONNECTED ||
           type == E87_APP_CORE_EVENT_BOND_CHANGED ||
           type == E87_APP_CORE_EVENT_MAINTENANCE_LOADER_REPORT ||
           type == E87_APP_CORE_EVENT_MAINTENANCE_COMMIT_HANDOFF ||
           type == E87_APP_CORE_EVENT_BATTERY ||
           type == E87_APP_CORE_EVENT_MAINTENANCE_UI;
}

static bool event_payload_is_valid(const struct e87_app_core_event *event)
{
    if (event == NULL || !event_type_is_valid(event->type)) {
        return false;
    }
    switch (event->type) {
    case E87_APP_CORE_EVENT_BOOT:
        return reset_cause_is_valid(event->data.boot.reset_cause) &&
               key_is_valid(event->data.boot.key);
    case E87_APP_CORE_EVENT_POWER:
        return power_event_type_is_valid(event->data.power.type) &&
               (event->data.power.type !=
                    E87_POWER_EVENT_WAKE_CLASSIFIED ||
                wake_classification_is_valid(
                    event->data.power.wake_classification));
    case E87_APP_CORE_EVENT_MAINTENANCE:
        return maintenance_event_type_is_valid(
                   event->data.maintenance.type) &&
               event->data.maintenance.now_ms == event->now_ms &&
               (event->data.maintenance.type !=
                    E87_MAINTENANCE_EVENT_POWER_SAMPLE ||
                (event->data.maintenance.power.percent <= UINT8_C(100) &&
                 charger_phase_is_valid(
                     event->data.maintenance.power.charger_phase)));
    case E87_APP_CORE_EVENT_PROFILE_CONNECTED:
    case E87_APP_CORE_EVENT_PROFILE_DISCONNECTED:
        return event->data.profile_link.app_handle != NULL;
    case E87_APP_CORE_EVENT_BATTERY:
        return battery_state_is_valid(event->data.battery.state) &&
               event->data.battery.percent <= UINT8_C(100);
    case E87_APP_CORE_EVENT_MAINTENANCE_UI:
        return maintenance_ui_phase_is_valid(
                   event->data.maintenance_ui.phase) &&
               event->data.maintenance_ui.progress_percent <=
                   UINT8_C(100);
    case E87_APP_CORE_EVENT_POLL:
    case E87_APP_CORE_EVENT_BUTTON_ADC_SAMPLE:
    case E87_APP_CORE_EVENT_BOND_CHANGED:
        return true;
    case E87_APP_CORE_EVENT_SEMANTIC_PACKET:
        return true;
    case E87_APP_CORE_EVENT_MAINTENANCE_LOADER_REPORT:
    case E87_APP_CORE_EVENT_MAINTENANCE_COMMIT_HANDOFF:
        return true;
    default:
        return false;
    }
}

static bool render_model_equal(const struct e87_render_model *left,
                               const struct e87_render_model *right)
{
    return left->screen == right->screen &&
           left->metrics.day == right->metrics.day &&
           left->metrics.week == right->metrics.week &&
           left->metrics.credit_cents == right->metrics.credit_cents &&
           left->countdown_seconds == right->countdown_seconds &&
           left->battery_overlay == right->battery_overlay &&
           left->battery_state == right->battery_state &&
           left->battery_percent == right->battery_percent &&
           left->charge_visual == right->charge_visual &&
           left->maintenance_phase == right->maintenance_phase &&
           left->maintenance_progress_percent ==
               right->maintenance_progress_percent &&
           left->recovery_entry == right->recovery_entry;
}

static bool emit_effect(struct e87_app_core *core,
                        struct e87_app_core_effect *effect)
{
    effect->now_ms = core->private_now_ms;
    core->private_effect_generation += UINT32_C(1);
    return core->private_port.emit(core->private_port.context, effect);
}

static bool configure_normal_writes(struct e87_app_core *core,
                                    bool enabled)
{
    struct e87_app_core_effect effect;
    uint32_t returned_epoch;
    const bool was_enabled = core->private_normal_writes_enabled;

    if (!enabled) {
        core->private_normal_writes_enabled = false;
    }

    memset(&effect, 0, sizeof(effect));
    effect.type = E87_APP_CORE_EFFECT_BLE_SET_WRITES;
    effect.data.writes.enabled = enabled;
    effect.data.writes.authorization_epoch =
        core->private_authorization_epoch;
    if (!emit_effect(core, &effect)) {
        core->private_normal_writes_enabled = false;
        return false;
    }

    returned_epoch = effect.data.writes.authorization_epoch;
    if ((!core->private_authorization_epoch_known &&
         enabled && returned_epoch == UINT32_C(0)) ||
        (core->private_authorization_epoch_known &&
         (returned_epoch < core->private_authorization_epoch ||
          (returned_epoch == core->private_authorization_epoch &&
           enabled != was_enabled)))) {
        core->private_normal_writes_enabled = false;
        return false;
    }

    core->private_authorization_epoch = returned_epoch;
    core->private_authorization_epoch_known = true;
    core->private_normal_writes_enabled = enabled;
    return true;
}

static bool refresh_ui(struct e87_app_core *core,
                       uint32_t actions,
                       bool force,
                       bool *out_changed)
{
    struct e87_ui_inputs inputs;
    struct e87_render_model next;
    struct e87_power_view power_view;
    bool changed;

    memset(&inputs, 0, sizeof(inputs));
    if (!e87_state_snapshot(&core->private_state, &inputs.semantic) ||
        !e87_button_get_view(&core->private_button,
                             core->private_now_ms,
                             &inputs.button) ||
        !e87_power_policy_get_view(&core->private_power, &power_view)) {
        return false;
    }
    inputs.panel_visible = core->private_panel_visible;
    inputs.has_bond = core->private_has_bond;
    inputs.maintenance_active =
        core->private_phase ==
            E87_APP_CORE_PHASE_ENTERING_MAINTENANCE ||
        core->private_phase == E87_APP_CORE_PHASE_MAINTENANCE ||
        core->private_phase == E87_APP_CORE_PHASE_RETURNING_NORMAL;
    inputs.recovery_entry = core->private_recovery_entry;
    inputs.battery_state = core->private_battery_state;
    inputs.battery_percent = core->private_battery_percent;
    inputs.charger_phase = power_view.charge_snapshot.phase;
    inputs.maintenance_phase = core->private_maintenance_phase;
    inputs.maintenance_progress_percent =
        core->private_maintenance_progress_percent;
    if (!e87_ui_step(&core->private_ui, core->private_now_ms, actions,
                     &inputs, &next)) {
        return false;
    }

    changed = !core->private_render_model_valid ||
              !render_model_equal(&core->private_render_model, &next);
    core->private_render_model = next;
    core->private_render_model_valid = true;
    if (out_changed != NULL) {
        *out_changed = changed;
    }
    if (core->private_drawing_enabled &&
        core->private_panel_visible && (force || changed)) {
        struct e87_app_core_effect effect;

        memset(&effect, 0, sizeof(effect));
        effect.type = E87_APP_CORE_EFFECT_DRAW;
        effect.data.draw.model = next;
        if (!emit_effect(core, &effect)) {
            core->private_effect_failed = true;
            return false;
        }
    }
    return true;
}

static bool power_emit(void *context, enum e87_power_command command)
{
    struct e87_app_core *core = (struct e87_app_core *)context;
    struct e87_app_core_effect effect;
    bool changed = false;
    bool gate_accepted = true;

    if (command == E87_POWER_COMMAND_REDRAW) {
        if (!refresh_ui(core, E87_ACTION_NONE, true, &changed)) {
            core->private_effect_failed = true;
            return false;
        }
        return true;
    }

    if (command == E87_POWER_COMMAND_BLE_STOP_DISCONNECT) {
        gate_accepted = configure_normal_writes(core, false);
    }
    memset(&effect, 0, sizeof(effect));
    effect.type = E87_APP_CORE_EFFECT_POWER;
    effect.data.power.command = command;
    if (!emit_effect(core, &effect)) {
        core->private_effect_failed = true;
        return false;
    }
    if (command == E87_POWER_COMMAND_STOP_DRAWS) {
        core->private_drawing_enabled = false;
    } else if (command == E87_POWER_COMMAND_PANEL_SLEEP) {
        core->private_panel_visible = false;
    } else if (command == E87_POWER_COMMAND_DISPLAY_EXIT_SLEEP) {
        core->private_panel_visible = true;
        core->private_drawing_enabled = true;
    } else if (command == E87_POWER_COMMAND_BLE_START &&
               core->private_phase == E87_APP_CORE_PHASE_NORMAL) {
        gate_accepted = configure_normal_writes(core, true);
    }
    if (!gate_accepted) {
        core->private_effect_failed = true;
        return false;
    }
    return true;
}

static bool ble_set_advertising(void *context,
                                enum e87_ble_mode mode,
                                bool enabled)
{
    struct e87_app_core *core = (struct e87_app_core *)context;
    struct e87_app_core_effect effect;

    if (mode == E87_BLE_MODE_MAINTENANCE && enabled &&
        core->private_pending_maintenance_exit_valid) {
        return true;
    }
    memset(&effect, 0, sizeof(effect));
    if (mode == E87_BLE_MODE_MAINTENANCE) {
        effect.type = enabled
                          ? E87_APP_CORE_EFFECT_BLE_VERIFY_MAINTENANCE_ADVERTISING
                          : E87_APP_CORE_EFFECT_BLE_VERIFY_MAINTENANCE_STOPPED;
    } else {
        effect.type = E87_APP_CORE_EFFECT_BLE_SET_ADVERTISING;
    }
    effect.data.advertising.mode = mode;
    effect.data.advertising.enabled = enabled;
    return emit_effect(core, &effect);
}

static void ble_set_writes(void *context, bool enabled)
{
    struct e87_app_core *core = (struct e87_app_core *)context;

    if (!configure_normal_writes(core, enabled)) {
        core->private_effect_failed = true;
    }
}

static bool ble_request_disconnect(void *context,
                                   enum e87_ble_mode mode,
                                   const void *app_handle,
                                   uint16_t connection_handle)
{
    struct e87_app_core *core = (struct e87_app_core *)context;
    struct e87_app_core_effect effect;

    memset(&effect, 0, sizeof(effect));
    effect.type = E87_APP_CORE_EFFECT_BLE_REQUEST_DISCONNECT;
    effect.data.disconnect.mode = mode;
    effect.data.disconnect.app_handle = app_handle;
    effect.data.disconnect.connection_handle = connection_handle;
    return emit_effect(core, &effect);
}

static bool ble_release_profile(void *context,
                                enum e87_ble_mode mode,
                                const void *app_handle)
{
    struct e87_app_core *core = (struct e87_app_core *)context;
    struct e87_app_core_effect effect;

    if (core->private_normal_writes_enabled ||
        (core->private_authorization_epoch_known &&
         core->private_port.authorization_epoch_is_active(
             core->private_port.context,
             core->private_authorization_epoch))) {
        return false;
    }

    memset(&effect, 0, sizeof(effect));
    effect.type = mode == E87_BLE_MODE_MAINTENANCE
                      ? E87_APP_CORE_EFFECT_BLE_VERIFY_MAINTENANCE_RELEASED
                      : E87_APP_CORE_EFFECT_BLE_RELEASE_PROFILE;
    effect.data.profile.mode = mode;
    effect.data.profile.app_handle = app_handle;
    return emit_effect(core, &effect);
}

static bool maintenance_emit(
    void *context,
    enum e87_maintenance_command command,
    const struct e87_maintenance_handoff *handoff);

static bool initialize_maintenance_profile(struct e87_app_core *core,
                                           const void **out_handle)
{
    struct e87_maintenance_event event;
    struct e87_app_core_effect effect;
    enum e87_maintenance_result result;

    if (!core->private_maintenance_authorized || out_handle == NULL) {
        return false;
    }
    memset(&event, 0, sizeof(event));
    event.type = E87_MAINTENANCE_EVENT_ENTER_AFTER_NORMAL_DISCONNECT;
    event.now_ms = core->private_now_ms;
    result = e87_maintenance_step(&core->private_maintenance, &event);
    if (result != E87_MAINTENANCE_RESULT_ACTIVE) {
        core->private_effect_failed = true;
        return false;
    }

    memset(&effect, 0, sizeof(effect));
    effect.type = E87_APP_CORE_EFFECT_BLE_ADOPT_MAINTENANCE_PROFILE;
    effect.data.profile.mode = E87_BLE_MODE_MAINTENANCE;
    if (!emit_effect(core, &effect) ||
        effect.data.profile.app_handle == NULL) {
        core->private_effect_failed = true;
        return false;
    }
    *out_handle = effect.data.profile.app_handle;
    core->private_maintenance_active = true;
    core->private_maintenance_phase =
        E87_UI_MAINTENANCE_WAITING_FOR_PHONE;
    return true;
}

static bool ble_initialize_profile(void *context,
                                   enum e87_ble_mode mode,
                                   const void **out_handle)
{
    struct e87_app_core *core = (struct e87_app_core *)context;
    struct e87_app_core_effect effect;

    if (out_handle == NULL) {
        return false;
    }
    if (mode == E87_BLE_MODE_MAINTENANCE) {
        return initialize_maintenance_profile(core, out_handle);
    }

    memset(&effect, 0, sizeof(effect));
    effect.type = E87_APP_CORE_EFFECT_BLE_INITIALIZE_NORMAL_PROFILE;
    effect.data.profile.mode = E87_BLE_MODE_NORMAL;
    if (!emit_effect(core, &effect) ||
        effect.data.profile.app_handle == NULL) {
        return false;
    }
    *out_handle = effect.data.profile.app_handle;
    return true;
}

static struct e87_ble_mode_ops ble_ops(struct e87_app_core *core)
{
    const struct e87_ble_mode_ops ops = {
        core,
        ble_set_advertising,
        ble_set_writes,
        ble_request_disconnect,
        ble_release_profile,
        ble_initialize_profile
    };

    return ops;
}

static bool recovery_emit(void *context,
                          enum e87_recovery_command command)
{
    struct e87_app_core *core = (struct e87_app_core *)context;
    struct e87_app_core_effect effect;

    if (command == E87_RECOVERY_COMMAND_REQUEST_NORMAL_STOP) {
        if (!core->private_ble_initialized ||
            e87_ble_mode_current(&core->private_ble) !=
                E87_BLE_MODE_NORMAL ||
            e87_ble_mode_phase(&core->private_ble) !=
                E87_BLE_MODE_PHASE_STEADY ||
            !e87_ble_mode_request(&core->private_ble,
                                  E87_BLE_MODE_MAINTENANCE) ||
            core->private_effect_failed) {
            return false;
        }
        core->private_phase =
            E87_APP_CORE_PHASE_ENTERING_MAINTENANCE;
        core->private_recovery_entry = true;
        core->private_normal_stop_reported = false;
        return true;
    }
    if (command == E87_RECOVERY_COMMAND_REQUEST_MAINTENANCE) {
        core->private_maintenance_authorized = true;
        return true;
    }

    memset(&effect, 0, sizeof(effect));
    effect.type = E87_APP_CORE_EFFECT_RECOVERY;
    effect.data.recovery.command = command;
    if (!emit_effect(core, &effect)) {
        core->private_effect_failed = true;
        return false;
    }
    return true;
}

static bool maintenance_emit(
    void *context,
    enum e87_maintenance_command command,
    const struct e87_maintenance_handoff *handoff)
{
    struct e87_app_core *core = (struct e87_app_core *)context;
    struct e87_app_core_effect effect;

    if (command == E87_MAINTENANCE_COMMAND_REQUEST_NORMAL_MODE) {
        if (core->private_phase == E87_APP_CORE_PHASE_FAIL_CLOSED) {
            return true;
        }
        if (!core->private_ble_initialized ||
            e87_ble_mode_current(&core->private_ble) !=
                E87_BLE_MODE_MAINTENANCE ||
            e87_ble_mode_phase(&core->private_ble) !=
                E87_BLE_MODE_PHASE_STEADY ||
            !e87_ble_mode_request(&core->private_ble,
                                  E87_BLE_MODE_NORMAL) ||
            core->private_effect_failed) {
            return false;
        }
        core->private_phase = E87_APP_CORE_PHASE_RETURNING_NORMAL;
        return true;
    }

    memset(&effect, 0, sizeof(effect));
    effect.type = E87_APP_CORE_EFFECT_MAINTENANCE;
    effect.data.maintenance.command = command;
    effect.data.maintenance.has_handoff = handoff != NULL;
    if (handoff != NULL) {
        effect.data.maintenance.handoff = *handoff;
    }
    return emit_effect(core, &effect);
}

static bool bootstrap_normal(struct e87_app_core *core)
{
    const void *profile_handle = NULL;
    const struct e87_ble_mode_ops ops = ble_ops(core);

    if (!ble_initialize_profile(core, E87_BLE_MODE_NORMAL,
                                &profile_handle) ||
        !e87_ble_mode_init(&core->private_ble, E87_BLE_MODE_NORMAL,
                           profile_handle, &ops)) {
        return false;
    }
    core->private_ble_initialized = true;
    ble_set_writes(core, true);
    if (core->private_effect_failed ||
        !ble_set_advertising(core, E87_BLE_MODE_NORMAL, true)) {
        return false;
    }
    core->private_phase = E87_APP_CORE_PHASE_NORMAL;
    return true;
}

static bool bootstrap_maintenance(struct e87_app_core *core)
{
    const void *profile_handle = NULL;
    const struct e87_ble_mode_ops ops = ble_ops(core);

    if (!initialize_maintenance_profile(core, &profile_handle) ||
        !e87_ble_mode_init(&core->private_ble,
                           E87_BLE_MODE_MAINTENANCE,
                           profile_handle, &ops)) {
        return false;
    }
    core->private_ble_initialized = true;
    ble_set_writes(core, false);
    if (core->private_effect_failed ||
        !ble_set_advertising(core, E87_BLE_MODE_MAINTENANCE, true)) {
        return false;
    }
    core->private_phase = E87_APP_CORE_PHASE_MAINTENANCE;
    core->private_recovery_entry = false;
    return true;
}

static bool enqueue_fail_closed_cleanup(
    struct e87_app_core *core,
    const struct e87_maintenance_event *event)
{
    uint8_t index;

    if (core->private_fail_closed_cleanup_count >=
            E87_APP_CORE_FAIL_CLOSED_CLEANUP_CAPACITY ||
        event == NULL) {
        return false;
    }
    index = (uint8_t)(
        (core->private_fail_closed_cleanup_head +
         core->private_fail_closed_cleanup_count) %
        E87_APP_CORE_FAIL_CLOSED_CLEANUP_CAPACITY);
    core->private_fail_closed_cleanup[index] = *event;
    core->private_fail_closed_cleanup_count += UINT8_C(1);
    return true;
}

static bool fail_closed_shutdown_complete(
    const struct e87_app_core *core)
{
    return core->private_shutdown_draws_stopped &&
           core->private_shutdown_writes_closed &&
           core->private_shutdown_advertising_stopped;
}

static void drain_fail_closed_cleanup(struct e87_app_core *core)
{
    while (fail_closed_shutdown_complete(core) &&
           core->private_fail_closed_cleanup_count > UINT8_C(0)) {
        const struct e87_maintenance_event *event =
            &core->private_fail_closed_cleanup[
                core->private_fail_closed_cleanup_head];
        const enum e87_maintenance_result result =
            e87_maintenance_step(&core->private_maintenance, event);

        if (result == E87_MAINTENANCE_RESULT_ERROR) {
            return;
        }
        core->private_fail_closed_cleanup_head = (uint8_t)(
            (core->private_fail_closed_cleanup_head + UINT8_C(1)) %
            E87_APP_CORE_FAIL_CLOSED_CLEANUP_CAPACITY);
        core->private_fail_closed_cleanup_count -= UINT8_C(1);
    }
}

static void retry_fail_closed_effects(struct e87_app_core *core)
{
    struct e87_app_core_effect effect;
    enum e87_ble_mode mode = E87_BLE_MODE_NORMAL;

    if (!core->private_shutdown_draws_stopped) {
        memset(&effect, 0, sizeof(effect));
        effect.type = E87_APP_CORE_EFFECT_POWER;
        effect.data.power.command = E87_POWER_COMMAND_STOP_DRAWS;
        core->private_shutdown_draws_stopped =
            emit_effect(core, &effect);
    }

    if (!core->private_shutdown_writes_closed) {
        core->private_shutdown_writes_closed =
            configure_normal_writes(core, false);
    }

    if (core->private_ble_initialized) {
        mode = e87_ble_mode_current(&core->private_ble);
    }
    if (!core->private_shutdown_advertising_stopped) {
        memset(&effect, 0, sizeof(effect));
        effect.type = mode == E87_BLE_MODE_MAINTENANCE
                          ? E87_APP_CORE_EFFECT_BLE_VERIFY_MAINTENANCE_STOPPED
                          : E87_APP_CORE_EFFECT_BLE_SET_ADVERTISING;
        effect.data.advertising.mode = mode;
        effect.data.advertising.enabled = false;
        core->private_shutdown_advertising_stopped =
            emit_effect(core, &effect);
    }
}

static enum e87_app_core_result fail_closed(struct e87_app_core *core)
{
    struct e87_maintenance_view maintenance_view;

    core->private_phase = E87_APP_CORE_PHASE_FAIL_CLOSED;
    core->private_drawing_enabled = false;
    core->private_recovery_entry = false;
    if (e87_maintenance_get_view(&core->private_maintenance,
                                 &maintenance_view) &&
        (maintenance_view.state == E87_MAINTENANCE_STATE_ACTIVE ||
         maintenance_view.state ==
             E87_MAINTENANCE_STATE_HANDOFF_APPROVED)) {
        struct e87_maintenance_event cancel;

        memset(&cancel, 0, sizeof(cancel));
        cancel.type = E87_MAINTENANCE_EVENT_CANCEL;
        cancel.now_ms = core->private_now_ms;
        (void)enqueue_fail_closed_cleanup(core, &cancel);
    }
    retry_fail_closed_effects(core);
    drain_fail_closed_cleanup(core);
    return E87_APP_CORE_RESULT_FAIL_CLOSED;
}

static enum e87_app_core_result result_from_activity(
    const struct e87_app_core *core,
    uint32_t generation_before,
    bool changed)
{
    return changed || core->private_effect_generation != generation_before
               ? E87_APP_CORE_RESULT_UPDATED
               : E87_APP_CORE_RESULT_NO_CHANGE;
}

static bool reinitialize_normal_session(struct e87_app_core *core)
{
    const struct e87_maintenance_port maintenance_port = {
        core, maintenance_emit
    };
    const struct e87_recovery_port recovery_port = {
        core, recovery_emit
    };
    const struct e87_recovery_event boot = {
        E87_RECOVERY_EVENT_BOOT,
        E87_RESET_CAUSE_SOFTWARE,
        E87_KEY_NONE,
        core->private_now_ms
    };
    enum e87_recovery_result result;
    bool changed = false;

    if (!e87_maintenance_init(&core->private_maintenance,
                              &maintenance_port) ||
        !e87_recovery_init(&core->private_recovery, &recovery_port)) {
        return false;
    }
    result = e87_recovery_step(&core->private_recovery, &boot);
    if (result != E87_RECOVERY_RESULT_NORMAL_BOOT) {
        return false;
    }
    core->private_phase = E87_APP_CORE_PHASE_NORMAL;
    core->private_maintenance_active = false;
    core->private_pending_maintenance_exit_valid = false;
    core->private_deferred_maintenance_head = UINT8_C(0);
    core->private_deferred_maintenance_count = UINT8_C(0);
    core->private_recovery_entry = false;
    core->private_maintenance_authorized = false;
    core->private_normal_stop_reported = false;
    core->private_maintenance_phase =
        E87_UI_MAINTENANCE_WAITING_FOR_PHONE;
    core->private_maintenance_progress_percent = UINT8_C(0);
    return refresh_ui(core, E87_ACTION_NONE, true, &changed);
}

static bool pump_ble(struct e87_app_core *core,
                     bool *out_waiting,
                     bool *out_recovery_notified)
{
    enum e87_ble_mode_step_result result;
    enum e87_ble_mode_phase phase;

    *out_waiting = false;
    *out_recovery_notified = false;
    if (!core->private_ble_initialized) {
        if (core->private_maintenance_authorized) {
            return bootstrap_maintenance(core);
        }
        *out_waiting = true;
        return true;
    }

    phase = e87_ble_mode_phase(&core->private_ble);
    if (phase == E87_BLE_MODE_PHASE_INITIALIZE_TARGET &&
        e87_ble_mode_current(&core->private_ble) == E87_BLE_MODE_NORMAL &&
        !core->private_maintenance_authorized) {
        *out_waiting = true;
        return true;
    }
    result = e87_ble_mode_step(&core->private_ble);
    if (core->private_effect_failed) {
        return false;
    }
    if (result == E87_BLE_MODE_STEP_FAILED) {
        *out_waiting = true;
        return true;
    }

    phase = e87_ble_mode_phase(&core->private_ble);
    if (core->private_phase ==
            E87_APP_CORE_PHASE_ENTERING_MAINTENANCE &&
        phase == E87_BLE_MODE_PHASE_INITIALIZE_TARGET &&
        !core->private_normal_stop_reported) {
        const struct e87_recovery_event stopped = {
            E87_RECOVERY_EVENT_NORMAL_MODE_STOPPED,
            E87_RESET_CAUSE_SOFTWARE,
            core->private_current_key,
            core->private_now_ms
        };
        const enum e87_recovery_result recovery_result =
            e87_recovery_step(&core->private_recovery, &stopped);

        core->private_normal_stop_reported = true;
        *out_recovery_notified = true;
        if (core->private_effect_failed ||
            (recovery_result != E87_RECOVERY_RESULT_WAITING &&
             recovery_result !=
                 E87_RECOVERY_RESULT_MAINTENANCE_REQUESTED)) {
            return false;
        }
    }

    if (result == E87_BLE_MODE_STEP_COMPLETE) {
        if (e87_ble_mode_current(&core->private_ble) ==
            E87_BLE_MODE_MAINTENANCE) {
            core->private_phase = E87_APP_CORE_PHASE_MAINTENANCE;
            core->private_maintenance_active = true;
            core->private_recovery_entry = false;
            core->private_maintenance_phase =
                E87_UI_MAINTENANCE_WAITING_FOR_PHONE;
        } else if (!reinitialize_normal_session(core)) {
            return false;
        }
    } else if (result == E87_BLE_MODE_STEP_WAITING &&
               phase != E87_BLE_MODE_PHASE_STEADY) {
        *out_waiting = true;
    }
    return true;
}

static bool step_recovery_poll(struct e87_app_core *core)
{
    const struct e87_recovery_event event = {
        E87_RECOVERY_EVENT_POLL,
        E87_RESET_CAUSE_SOFTWARE,
        core->private_current_key,
        core->private_now_ms
    };

    const enum e87_recovery_result result =
        e87_recovery_step(&core->private_recovery, &event);

    return !core->private_effect_failed &&
           (result == E87_RECOVERY_RESULT_NO_CHANGE ||
            result == E87_RECOVERY_RESULT_WAITING ||
            result == E87_RECOVERY_RESULT_MAINTENANCE_REQUESTED);
}

static bool begin_healthy_maintenance(struct e87_app_core *core)
{
    const struct e87_recovery_event event = {
        E87_RECOVERY_EVENT_HEALTHY_MAINTENANCE,
        E87_RESET_CAUSE_SOFTWARE,
        core->private_current_key,
        core->private_now_ms
    };
    const enum e87_recovery_result result =
        e87_recovery_step(&core->private_recovery, &event);

    return !core->private_effect_failed &&
           result == E87_RECOVERY_RESULT_WAITING;
}

static bool emit_pairing(struct e87_app_core *core, bool enabled)
{
    struct e87_app_core_effect effect;

    memset(&effect, 0, sizeof(effect));
    effect.type = E87_APP_CORE_EFFECT_PAIRING;
    effect.data.pairing.enabled = enabled;
    if (!emit_effect(core, &effect)) {
        core->private_effect_failed = true;
        return false;
    }
    return true;
}

static bool process_button_actions(struct e87_app_core *core,
                                   uint32_t actions,
                                   bool *out_started_recovery)
{
    uint8_t ordinal = UINT8_C(0);
    enum e87_button_action action;

    *out_started_recovery = false;
    while ((action = e87_button_action_at(actions, ordinal)) !=
           E87_ACTION_NONE) {
        ordinal = (uint8_t)(ordinal + UINT8_C(1));
        switch (action) {
        case E87_ACTION_PAIRING_EXPIRED:
            if (!emit_pairing(core, false)) {
                return false;
            }
            break;
        case E87_ACTION_TAP_BATTERY:
        case E87_ACTION_UPDATE_WARNING:
        case E87_ACTION_END_UPDATE_WARNING:
            break;
        case E87_ACTION_OPEN_PAIRING:
            if (!emit_pairing(core, true)) {
                return false;
            }
            break;
        case E87_ACTION_SLEEP_TOGGLE: {
            const struct e87_power_event event = {
                E87_POWER_EVENT_MANUAL_SLEEP,
                {false, E87_CHARGE_PHASE_UNKNOWN},
                E87_POWER_WAKE_NONE
            };
            const enum e87_power_result result =
                e87_power_policy_step(&core->private_power, &event);

            if (result == E87_POWER_RESULT_ERROR) {
                return false;
            }
            if (result == E87_POWER_RESULT_WAITING_FOR_LCD ||
                result == E87_POWER_RESULT_ASLEEP ||
                result ==
                    E87_POWER_RESULT_WAITING_FOR_WAKE_CLASSIFICATION) {
                core->private_manual_sleep = true;
            }
            break;
        }
        case E87_ACTION_ENTER_MAINTENANCE:
            if (!emit_pairing(core, false) ||
                !begin_healthy_maintenance(core)) {
                return false;
            }
            *out_started_recovery = true;
            break;
        case E87_ACTION_NONE:
        default:
            return false;
        }
    }
    return true;
}

static enum e87_app_core_result handle_boot(
    struct e87_app_core *core,
    const struct e87_app_core_event *event,
    uint32_t generation_before)
{
    const struct e87_power_port power_port = {core, power_emit};
    const struct e87_recovery_event recovery_event = {
        E87_RECOVERY_EVENT_BOOT,
        event->data.boot.reset_cause,
        event->data.boot.key,
        event->now_ms
    };
    enum e87_recovery_result recovery_result;
    bool changed = false;

    core->private_booted = true;
    core->private_has_bond = event->data.boot.has_bond;
    core->private_current_key = event->data.boot.key;
    core->private_panel_visible = true;
    core->private_drawing_enabled = true;
    if (!e87_power_policy_init(&core->private_power, &power_port,
                               &event->data.boot.charge_snapshot)) {
        return fail_closed(core);
    }

    recovery_result = e87_recovery_step(&core->private_recovery,
                                        &recovery_event);
    if (core->private_effect_failed ||
        (recovery_result != E87_RECOVERY_RESULT_NORMAL_BOOT &&
         recovery_result != E87_RECOVERY_RESULT_WAITING &&
         recovery_result !=
             E87_RECOVERY_RESULT_MAINTENANCE_REQUESTED)) {
        return fail_closed(core);
    }
    if (recovery_result == E87_RECOVERY_RESULT_NORMAL_BOOT) {
        if (!bootstrap_normal(core)) {
            return fail_closed(core);
        }
    } else if (recovery_result ==
               E87_RECOVERY_RESULT_MAINTENANCE_REQUESTED) {
        core->private_phase =
            E87_APP_CORE_PHASE_ENTERING_MAINTENANCE;
        core->private_recovery_entry = true;
        if (!bootstrap_maintenance(core)) {
            return fail_closed(core);
        }
    } else {
        core->private_phase =
            E87_APP_CORE_PHASE_ENTERING_MAINTENANCE;
        core->private_recovery_entry = true;
    }
    if (!refresh_ui(core, E87_ACTION_NONE, true, &changed)) {
        return fail_closed(core);
    }
    return result_from_activity(core, generation_before, true);
}

static enum e87_app_core_result handle_semantic(
    struct e87_app_core *core,
    const struct e87_app_core_event *event,
    uint32_t generation_before)
{
    struct e87_metrics decoded;
    uint32_t epoch;
    bool changed = false;

    (void)generation_before;
    if (core->private_phase != E87_APP_CORE_PHASE_NORMAL ||
        !core->private_normal_writes_enabled) {
        return E87_APP_CORE_RESULT_NO_CHANGE;
    }
    epoch = event->data.semantic.authorization_epoch;
    if (!core->private_port.authorization_epoch_is_active(
            core->private_port.context, epoch)) {
        return E87_APP_CORE_RESULT_NO_CHANGE;
    }
    if (epoch == UINT32_C(0) || epoch == UINT32_MAX ||
        (core->private_authorization_epoch_known &&
         epoch < core->private_authorization_epoch)) {
        return fail_closed(core);
    }
    if (!core->private_authorization_epoch_known ||
        epoch > core->private_authorization_epoch) {
        core->private_authorization_epoch = epoch;
        core->private_authorization_epoch_known = true;
    }
    if (e87_state_decode(event->data.semantic.packet,
                         E87_STATE_PACKET_SIZE,
                         &decoded) != E87_STATE_OK) {
        return E87_APP_CORE_RESULT_ERROR;
    }
    if (!e87_state_commit(&core->private_state, &decoded)) {
        return E87_APP_CORE_RESULT_NO_CHANGE;
    }
    if (!refresh_ui(core, E87_ACTION_NONE, false, &changed)) {
        return fail_closed(core);
    }
    return E87_APP_CORE_RESULT_UPDATED;
}

static enum e87_app_core_result handle_button_sample(
    struct e87_app_core *core,
    const struct e87_app_core_event *event,
    uint32_t generation_before)
{
    enum e87_key_class key;
    enum e87_button_classifier_result classifier_result;
    uint32_t actions;
    bool started_recovery = false;
    bool changed = false;

    classifier_result = e87_button_classifier_sample(
        &core->private_classifier, event->now_ms,
        event->data.raw_adc, &key);
    if (classifier_result == E87_CLASSIFIER_ERROR) {
        return E87_APP_CORE_RESULT_ERROR;
    }
    if (classifier_result == E87_CLASSIFIER_TOO_EARLY) {
        return E87_APP_CORE_RESULT_NO_CHANGE;
    }
    core->private_current_key = key;
    actions = e87_button_step(&core->private_button, event->now_ms, key);
    if (core->private_phase != E87_APP_CORE_PHASE_NORMAL ||
        core->private_manual_sleep) {
        actions = E87_ACTION_NONE;
    } else {
        if (!process_button_actions(core, actions, &started_recovery)) {
            return fail_closed(core);
        }
    }
    if (!started_recovery &&
        core->private_phase ==
            E87_APP_CORE_PHASE_ENTERING_MAINTENANCE &&
        !step_recovery_poll(core)) {
        return fail_closed(core);
    }
    if (!refresh_ui(core, actions, false, &changed)) {
        return fail_closed(core);
    }
    return result_from_activity(
        core, generation_before,
        changed || actions != E87_ACTION_NONE ||
            classifier_result == E87_CLASSIFIER_ACCEPTED_CHANGED ||
            classifier_result == E87_CLASSIFIER_ACCEPTED_UNSAFE);
}

static bool enqueue_deferred_maintenance(
    struct e87_app_core *core,
    const struct e87_maintenance_event *event)
{
    uint8_t index;

    if (core->private_deferred_maintenance_count >=
            E87_APP_CORE_DEFERRED_MAINTENANCE_CAPACITY ||
        event == NULL) {
        return false;
    }
    index = (uint8_t)(
        (core->private_deferred_maintenance_head +
         core->private_deferred_maintenance_count) %
        E87_APP_CORE_DEFERRED_MAINTENANCE_CAPACITY);
    core->private_deferred_maintenance[index] = *event;
    core->private_deferred_maintenance_count += UINT8_C(1);
    return true;
}

static bool drain_deferred_maintenance(
    struct e87_app_core *core,
    enum e87_maintenance_result *out_result,
    bool *out_waiting)
{
    while (core->private_phase == E87_APP_CORE_PHASE_MAINTENANCE &&
           core->private_deferred_maintenance_count > UINT8_C(0)) {
        const struct e87_maintenance_event *event =
            &core->private_deferred_maintenance[
                core->private_deferred_maintenance_head];
        const enum e87_maintenance_result result =
            e87_maintenance_step(&core->private_maintenance, event);

        if (core->private_effect_failed) {
            return false;
        }
        if (result == E87_MAINTENANCE_RESULT_ERROR) {
            struct e87_maintenance_view view;

            if (!e87_maintenance_get_view(&core->private_maintenance,
                                          &view) ||
                view.state == E87_MAINTENANCE_STATE_ERROR) {
                return false;
            }
            *out_waiting = true;
            return true;
        }
        if (event->type == E87_MAINTENANCE_EVENT_CANCEL ||
            event->type == E87_MAINTENANCE_EVENT_FAILURE) {
            core->private_pending_maintenance_exit_valid = false;
        }
        core->private_deferred_maintenance_head = (uint8_t)(
            (core->private_deferred_maintenance_head + UINT8_C(1)) %
            E87_APP_CORE_DEFERRED_MAINTENANCE_CAPACITY);
        core->private_deferred_maintenance_count -= UINT8_C(1);
        *out_result = result;
    }
    return true;
}

static enum e87_app_core_result handle_poll(
    struct e87_app_core *core,
    uint32_t generation_before)
{
    struct e87_maintenance_event maintenance_event;
    enum e87_maintenance_result maintenance_result =
        E87_MAINTENANCE_RESULT_NO_CHANGE;
    uint32_t actions;
    bool started_recovery = false;
    bool waiting = false;
    bool ble_waiting = false;
    bool recovery_notified = false;
    bool changed = false;

    actions = E87_ACTION_NONE;
    if (core->private_phase == E87_APP_CORE_PHASE_NORMAL &&
        !core->private_manual_sleep &&
        core->private_current_key == E87_KEY_NONE) {
        actions = e87_button_step(&core->private_button,
                                  core->private_now_ms,
                                  E87_KEY_NONE);
    }
    if (actions != E87_ACTION_NONE &&
        !process_button_actions(core, actions, &started_recovery)) {
        return fail_closed(core);
    }

    if (core->private_maintenance_active) {
        memset(&maintenance_event, 0, sizeof(maintenance_event));
        maintenance_event.type = E87_MAINTENANCE_EVENT_POLL;
        maintenance_event.now_ms = core->private_now_ms;
        maintenance_result = e87_maintenance_step(
            &core->private_maintenance, &maintenance_event);
        if (maintenance_result == E87_MAINTENANCE_RESULT_ERROR) {
            struct e87_maintenance_view view;

            if (!e87_maintenance_get_view(&core->private_maintenance,
                                          &view) ||
                view.state == E87_MAINTENANCE_STATE_ERROR) {
                return fail_closed(core);
            }
            waiting = true;
        }
    }

    if (!pump_ble(core, &ble_waiting, &recovery_notified)) {
        return fail_closed(core);
    }
    if (!drain_deferred_maintenance(
            core, &maintenance_result, &waiting)) {
        return fail_closed(core);
    }
    waiting = waiting || ble_waiting;
    if (!started_recovery && !recovery_notified &&
        core->private_phase ==
            E87_APP_CORE_PHASE_ENTERING_MAINTENANCE &&
        !step_recovery_poll(core)) {
        return fail_closed(core);
    }
    if (!refresh_ui(core, actions, false, &changed)) {
        return fail_closed(core);
    }
    if (waiting) {
        return E87_APP_CORE_RESULT_WAITING;
    }
    return result_from_activity(
        core, generation_before,
        changed || actions != E87_ACTION_NONE ||
            maintenance_result != E87_MAINTENANCE_RESULT_NO_CHANGE);
}

static enum e87_app_core_result handle_power(
    struct e87_app_core *core,
    const struct e87_power_event *event,
    uint32_t generation_before)
{
    enum e87_power_result result;
    bool changed = false;

    if (core->private_phase != E87_APP_CORE_PHASE_NORMAL &&
        event->type != E87_POWER_EVENT_CHARGE_SNAPSHOT) {
        return E87_APP_CORE_RESULT_NO_CHANGE;
    }

    result = e87_power_policy_step(&core->private_power, event);
    if (result == E87_POWER_RESULT_ERROR) {
        return fail_closed(core);
    }
    if (result == E87_POWER_RESULT_WAITING_FOR_LCD ||
        result == E87_POWER_RESULT_ASLEEP ||
        result == E87_POWER_RESULT_WAITING_FOR_WAKE_CLASSIFICATION) {
        core->private_manual_sleep = true;
    } else if (result == E87_POWER_RESULT_ACTIVE) {
        core->private_manual_sleep = false;
    }
    if (!refresh_ui(core, E87_ACTION_NONE, false, &changed)) {
        return fail_closed(core);
    }
    return result_from_activity(
        core, generation_before,
        changed || result != E87_POWER_RESULT_NO_CHANGE);
}

static enum e87_app_core_result maintenance_result_to_app(
    struct e87_app_core *core,
    enum e87_maintenance_result result,
    uint32_t generation_before)
{
    struct e87_maintenance_view view;
    bool changed = false;

    if (!e87_maintenance_get_view(&core->private_maintenance, &view)) {
        return fail_closed(core);
    }
    if (result == E87_MAINTENANCE_RESULT_ERROR) {
        if (view.state == E87_MAINTENANCE_STATE_ERROR) {
            return fail_closed(core);
        }
        return E87_APP_CORE_RESULT_WAITING;
    }
    if (view.state == E87_MAINTENANCE_STATE_ACTIVE) {
        core->private_maintenance_phase = view.authenticated
            ? E87_UI_MAINTENANCE_PHONE_READY
            : E87_UI_MAINTENANCE_WAITING_FOR_PHONE;
    } else if (view.state == E87_MAINTENANCE_STATE_HANDOFF_APPROVED ||
               view.state == E87_MAINTENANCE_STATE_HANDED_OFF) {
        core->private_maintenance_phase =
            E87_UI_MAINTENANCE_UPDATING;
    }
    if (!refresh_ui(core, E87_ACTION_NONE, false, &changed)) {
        return fail_closed(core);
    }
    return result_from_activity(
        core, generation_before,
        changed || result != E87_MAINTENANCE_RESULT_NO_CHANGE);
}

static enum e87_app_core_result handle_maintenance(
    struct e87_app_core *core,
    const struct e87_maintenance_event *event,
    uint32_t generation_before)
{
    enum e87_maintenance_result result;

    if (core->private_phase ==
            E87_APP_CORE_PHASE_ENTERING_MAINTENANCE) {
        if (!enqueue_deferred_maintenance(core, event)) {
            return fail_closed(core);
        }
        if (event->type == E87_MAINTENANCE_EVENT_CANCEL ||
            event->type == E87_MAINTENANCE_EVENT_FAILURE) {
            core->private_pending_maintenance_exit_valid = true;
        }
        return E87_APP_CORE_RESULT_WAITING;
    }
    if (core->private_phase != E87_APP_CORE_PHASE_MAINTENANCE) {
        return E87_APP_CORE_RESULT_NO_CHANGE;
    }
    if (!core->private_maintenance_active) {
        return E87_APP_CORE_RESULT_ERROR;
    }
    result = e87_maintenance_step(&core->private_maintenance, event);
    if (core->private_effect_failed) {
        return fail_closed(core);
    }
    return maintenance_result_to_app(core, result, generation_before);
}

static enum e87_app_core_result handle_loader_report(
    struct e87_app_core *core,
    const struct e87_rcsp_official_loader_report *report,
    uint32_t generation_before)
{
    enum e87_maintenance_result result;

    if (core->private_phase ==
            E87_APP_CORE_PHASE_ENTERING_MAINTENANCE) {
        return E87_APP_CORE_RESULT_WAITING;
    }
    if (core->private_phase != E87_APP_CORE_PHASE_MAINTENANCE) {
        return E87_APP_CORE_RESULT_NO_CHANGE;
    }
    if (!core->private_maintenance_active) {
        return E87_APP_CORE_RESULT_ERROR;
    }
    result = e87_rcsp_official_loader_callback(
        &core->private_maintenance, core->private_now_ms, report);
    return maintenance_result_to_app(core, result, generation_before);
}

static enum e87_app_core_result handle_handoff_commit(
    struct e87_app_core *core,
    uint32_t generation_before)
{
    enum e87_maintenance_result result;

    if (core->private_phase ==
            E87_APP_CORE_PHASE_ENTERING_MAINTENANCE) {
        return E87_APP_CORE_RESULT_WAITING;
    }
    if (core->private_phase != E87_APP_CORE_PHASE_MAINTENANCE) {
        return E87_APP_CORE_RESULT_NO_CHANGE;
    }
    if (!core->private_maintenance_active) {
        return E87_APP_CORE_RESULT_ERROR;
    }
    result = e87_rcsp_commit_official_handoff(
        &core->private_maintenance);
    return maintenance_result_to_app(core, result, generation_before);
}

static enum e87_app_core_result handle_profile_link(
    struct e87_app_core *core,
    const struct e87_app_core_profile_link_event *link,
    bool connected)
{
    struct e87_ble_mode_fsm next_mode;
    bool accepted;

    if (!core->private_ble_initialized) {
        return E87_APP_CORE_RESULT_NO_CHANGE;
    }

    next_mode = core->private_ble;
    if (connected) {
        accepted = e87_ble_mode_set_connection(
            &next_mode, link->app_handle, link->connection_handle);
    } else {
        accepted = e87_ble_mode_on_disconnect_complete(
            &next_mode, link->app_handle, link->connection_handle);
    }
    if (!accepted) {
        return E87_APP_CORE_RESULT_NO_CHANGE;
    }
    core->private_ble = next_mode;
    return E87_APP_CORE_RESULT_UPDATED;
}

bool e87_app_core_init(struct e87_app_core *core,
                       const struct e87_app_core_config *config,
                       const struct e87_app_core_port *port)
{
    const struct e87_state_sync state_sync = {
        NULL, state_enter, state_leave
    };
    const struct e87_recovery_port recovery_port = {
        NULL, recovery_emit
    };
    const struct e87_maintenance_port maintenance_port = {
        NULL, maintenance_emit
    };

    if (core == NULL || config == NULL || port == NULL ||
        port->emit == NULL ||
        port->authorization_epoch_is_active == NULL ||
        !e87_button_classifier_config_valid(
            &config->button_classifier)) {
        return false;
    }

    /*
     * All fallible contract checks are complete before core is touched.  The
     * component initializers below can only reject the pointers/callbacks and
     * classifier configuration already checked above.  Initializing in place
     * therefore preserves failure atomicity without putting a complete app
     * core (hundreds of bytes) on the app_core task stack.
     */
    memset(core, 0, sizeof(*core));
    core->private_port = *port;
    core->private_phase = E87_APP_CORE_PHASE_READY;
    core->private_current_key = E87_KEY_NONE;
    core->private_battery_state = E87_UI_BATTERY_UNAVAILABLE_FAULT;
    core->private_maintenance_phase =
        E87_UI_MAINTENANCE_WAITING_FOR_PHONE;
    (void)e87_state_store_init(&core->private_state, &state_sync);
    (void)e87_button_classifier_init(&core->private_classifier,
                                     &config->button_classifier);
    (void)e87_recovery_init(&core->private_recovery, &recovery_port);
    (void)e87_maintenance_init(&core->private_maintenance,
                               &maintenance_port);
    e87_ui_init(&core->private_ui);
    e87_button_init(&core->private_button);
    core->private_recovery.private_port.context = core;
    core->private_maintenance.private_port.context = core;
    core->private_initialized = true;
    return true;
}

static bool is_fail_closed_cleanup_event(
    const struct e87_app_core_event *event)
{
    enum e87_maintenance_event_type type;

    if (event == NULL || event->type != E87_APP_CORE_EVENT_MAINTENANCE ||
        !event_payload_is_valid(event)) {
        return false;
    }
    type = event->data.maintenance.type;
    return type == E87_MAINTENANCE_EVENT_CANCEL ||
           type == E87_MAINTENANCE_EVENT_FAILURE ||
           type == E87_MAINTENANCE_EVENT_TRANSPORT_QUIESCED ||
           type == E87_MAINTENANCE_EVENT_RCSP_RELEASE_STATUS;
}

static enum e87_app_core_result handle_fail_closed_cleanup(
    struct e87_app_core *core,
    const struct e87_app_core_event *event)
{
    const bool cleanup = is_fail_closed_cleanup_event(event);
    const bool retry_poll =
        event != NULL && event->type == E87_APP_CORE_EVENT_POLL &&
        event_payload_is_valid(event);

    if ((!cleanup && !retry_poll) ||
        (core->private_have_time &&
         (uint32_t)(event->now_ms - core->private_now_ms) >
             UINT32_C(0x7fffffff))) {
        return E87_APP_CORE_RESULT_FAIL_CLOSED;
    }
    core->private_in_step = true;
    core->private_now_ms = event->now_ms;
    core->private_have_time = true;
    if (cleanup) {
        (void)enqueue_fail_closed_cleanup(
            core, &event->data.maintenance);
    }
    retry_fail_closed_effects(core);
    drain_fail_closed_cleanup(core);
    core->private_in_step = false;
    return E87_APP_CORE_RESULT_FAIL_CLOSED;
}

enum e87_app_core_result e87_app_core_step(
    struct e87_app_core *core,
    const struct e87_app_core_event *event)
{
    enum e87_app_core_result result;
    uint32_t generation_before;

    if (core == NULL || event == NULL || !core->private_initialized ||
        core->private_port.emit == NULL ||
        core->private_port.authorization_epoch_is_active == NULL) {
        return E87_APP_CORE_RESULT_ERROR;
    }
    if (core->private_in_step) {
        return E87_APP_CORE_RESULT_REENTRANT;
    }
    if (core->private_phase == E87_APP_CORE_PHASE_FAIL_CLOSED) {
        return handle_fail_closed_cleanup(core, event);
    }
    if (!event_payload_is_valid(event) ||
        (!core->private_booted &&
         event->type != E87_APP_CORE_EVENT_BOOT) ||
        (core->private_booted &&
         event->type == E87_APP_CORE_EVENT_BOOT) ||
        (core->private_have_time &&
         (uint32_t)(event->now_ms - core->private_now_ms) >
             UINT32_C(0x7fffffff))) {
        return E87_APP_CORE_RESULT_ERROR;
    }
    core->private_in_step = true;
    core->private_now_ms = event->now_ms;
    core->private_have_time = true;
    core->private_effect_failed = false;
    generation_before = core->private_effect_generation;
    switch (event->type) {
    case E87_APP_CORE_EVENT_BOOT:
        result = handle_boot(core, event, generation_before);
        break;
    case E87_APP_CORE_EVENT_POLL:
        result = handle_poll(core, generation_before);
        break;
    case E87_APP_CORE_EVENT_BUTTON_ADC_SAMPLE:
        result = handle_button_sample(core, event, generation_before);
        break;
    case E87_APP_CORE_EVENT_SEMANTIC_PACKET:
        result = handle_semantic(core, event, generation_before);
        break;
    case E87_APP_CORE_EVENT_POWER:
        result = handle_power(core, &event->data.power,
                              generation_before);
        break;
    case E87_APP_CORE_EVENT_MAINTENANCE:
        result = handle_maintenance(core, &event->data.maintenance,
                                    generation_before);
        break;
    case E87_APP_CORE_EVENT_PROFILE_CONNECTED:
        result = handle_profile_link(
            core, &event->data.profile_link, true);
        break;
    case E87_APP_CORE_EVENT_PROFILE_DISCONNECTED:
        result = handle_profile_link(
            core, &event->data.profile_link, false);
        break;
    case E87_APP_CORE_EVENT_BOND_CHANGED: {
        bool changed = false;

        if (core->private_has_bond == event->data.has_bond) {
            result = E87_APP_CORE_RESULT_NO_CHANGE;
            break;
        }
        core->private_has_bond = event->data.has_bond;
        if (!refresh_ui(core, E87_ACTION_NONE, false, &changed)) {
            result = fail_closed(core);
        } else {
            result = result_from_activity(
                core, generation_before, true);
        }
        break;
    }
    case E87_APP_CORE_EVENT_MAINTENANCE_LOADER_REPORT:
        result = handle_loader_report(core, &event->data.loader_report,
                                      generation_before);
        break;
    case E87_APP_CORE_EVENT_MAINTENANCE_COMMIT_HANDOFF:
        result = handle_handoff_commit(core, generation_before);
        break;
    case E87_APP_CORE_EVENT_BATTERY: {
        bool changed = false;

        core->private_battery_state = event->data.battery.state;
        core->private_battery_percent = event->data.battery.percent;
        if (core->private_effect_failed ||
            !refresh_ui(core, E87_ACTION_NONE, false, &changed)) {
            result = fail_closed(core);
        } else {
            result = result_from_activity(core, generation_before, true);
        }
        break;
    }
    case E87_APP_CORE_EVENT_MAINTENANCE_UI: {
        bool changed = false;

        core->private_maintenance_phase =
            event->data.maintenance_ui.phase;
        core->private_maintenance_progress_percent =
            event->data.maintenance_ui.progress_percent;
        if (!refresh_ui(core, E87_ACTION_NONE, false, &changed)) {
            result = fail_closed(core);
        } else {
            result = result_from_activity(core, generation_before, true);
        }
        break;
    }
    default:
        result = E87_APP_CORE_RESULT_ERROR;
        break;
    }
    core->private_in_step = false;
    return result;
}

bool e87_app_core_get_view(const struct e87_app_core *core,
                           struct e87_app_core_view *out)
{
    struct e87_app_core_view view;
    struct e87_power_view power_view;

    if (core == NULL || out == NULL || !core->private_initialized) {
        return false;
    }
    memset(&view, 0, sizeof(view));
    if (!e87_state_snapshot(&core->private_state, &view.semantic)) {
        return false;
    }
    view.phase = core->private_phase;
    view.ble_mode = core->private_ble_initialized
                        ? e87_ble_mode_current(&core->private_ble)
                        : E87_BLE_MODE_NORMAL;
    view.manual_sleep = core->private_manual_sleep;
    view.drawing_enabled = core->private_drawing_enabled;
    view.render_model = core->private_render_model;
    if (core->private_booted) {
        if (!e87_power_policy_get_view(&core->private_power,
                                       &power_view)) {
            return false;
        }
        view.external_power_online =
            power_view.charge_snapshot.external_power_online;
    }
    *out = view;
    return true;
}
