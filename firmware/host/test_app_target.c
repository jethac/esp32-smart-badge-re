#include "test_support.h"
#include "e87/e87_app_target.h"

#include <string.h>

struct fake_boot {
    unsigned fail_at;
    unsigned calls;
};

static bool allowed(struct fake_boot *fake)
{
    fake->calls++;
    return fake->fail_at == 0u || fake->calls != fake->fail_at;
}

static bool read_now(void *context, uint32_t *out)
{
    struct fake_boot *fake = context;
    *out = 1234u;
    return allowed(fake);
}

static bool read_bond(void *context, bool *out)
{
    struct fake_boot *fake = context;
    *out = true;
    return allowed(fake);
}

static bool read_reset(void *context, enum e87_recovery_reset_cause *out)
{
    struct fake_boot *fake = context;
    *out = E87_RESET_CAUSE_WATCHDOG;
    return allowed(fake);
}

static bool read_key(void *context, enum e87_key_class *out)
{
    struct fake_boot *fake = context;
    *out = E87_KEY_BUTTON2;
    return allowed(fake);
}

static bool read_charge(void *context, struct e87_charge_snapshot *out)
{
    struct fake_boot *fake = context;
    out->phase = E87_CHARGE_PHASE_CLOSED;
    out->external_power_online = false;
    return allowed(fake);
}

static struct e87_app_target_boot_port port(struct fake_boot *fake)
{
    const struct e87_app_target_boot_port value = {
        fake, read_now, read_bond, read_reset, read_key, read_charge
    };
    return value;
}

E87_TEST(boot_uses_every_authoritative_reader)
{
    struct fake_boot fake = {0};
    struct e87_app_core_event event;
    const struct e87_app_target_boot_port target = port(&fake);
    memset(&event, 0xa5, sizeof(event));
    E87_ASSERT_TRUE(e87_app_target_build_boot(&target, &event));
    E87_ASSERT_EQ_U32(5u, fake.calls);
    E87_ASSERT_EQ_U32(E87_APP_CORE_EVENT_BOOT, event.type);
    E87_ASSERT_EQ_U32(1234u, event.now_ms);
    E87_ASSERT_TRUE(event.data.boot.has_bond);
    E87_ASSERT_EQ_U32(E87_RESET_CAUSE_WATCHDOG, event.data.boot.reset_cause);
    E87_ASSERT_EQ_U32(E87_KEY_BUTTON2, event.data.boot.key);
    E87_ASSERT_EQ_U32(E87_CHARGE_PHASE_CLOSED, event.data.boot.charge_snapshot.phase);
    E87_ASSERT_TRUE(!event.data.boot.charge_snapshot.external_power_online);
}

E87_TEST(any_unavailable_boot_fact_fails_without_output)
{
    unsigned fail_at;
    for (fail_at = 1u; fail_at <= 5u; fail_at++) {
        struct fake_boot fake = {fail_at, 0u};
        struct e87_app_core_event event;
        struct e87_app_core_event before;
        const struct e87_app_target_boot_port target = port(&fake);
        memset(&event, 0x5a, sizeof(event));
        before = event;
        E87_ASSERT_TRUE(!e87_app_target_build_boot(&target, &event));
        E87_ASSERT_TRUE(memcmp(&before, &event, sizeof(event)) == 0);
        E87_ASSERT_EQ_U32(fail_at, fake.calls);
    }
}

E87_TEST(missing_reader_is_rejected)
{
    struct fake_boot fake = {0};
    struct e87_app_core_event event;
    struct e87_app_target_boot_port target = port(&fake);
    target.read_charge = NULL;
    E87_ASSERT_TRUE(!e87_app_target_build_boot(&target, &event));
    E87_ASSERT_EQ_U32(0u, fake.calls);
}

static const struct e87_test_case cases[] = {
    E87_TEST_CASE(boot_uses_every_authoritative_reader),
    E87_TEST_CASE(any_unavailable_boot_fact_fails_without_output),
    E87_TEST_CASE(missing_reader_is_rejected),
};
const struct e87_test_suite e87_test_suite = {
    "app-target", cases, sizeof(cases) / sizeof(cases[0])
};
