#include "test_support.h"
#include "e87/e87_app_runtime.h"

#include <string.h>

struct fake { uint32_t now; unsigned enters; unsigned exits; };
static int enter(void *p) { ((struct fake *)p)->enters++; return 7; }
static void leave(void *p, int saved) { struct fake *f = p; E87_ASSERT_TRUE(saved == 7); f->exits++; }
static uint32_t now_ms(void *p) { return ((struct fake *)p)->now; }
static bool emit(void *p, struct e87_app_core_effect *e) { (void)p; (void)e; return true; }
static bool epoch(void *p, uint32_t e) { (void)p; return e == 9u; }

static struct e87_app_core_config config(void)
{
    const struct e87_app_core_config c = {{100u, 10u, 20000u, 1u, 1u,
        {10u, 19u}, {30u, 39u}, {50u, 59u}, {70u, 79u}}};
    return c;
}

static bool init(struct e87_app_runtime *r, struct fake *f)
{
    const struct e87_app_core_config c = config();
    const struct e87_app_runtime_port p = {f, enter, leave, now_ms, NULL, NULL, emit, epoch};
    memset(f, 0, sizeof(*f));
    return e87_app_runtime_init(r, &c, &p);
}

E87_TEST(semantic_ingress_copies_packet_and_epoch)
{
    struct e87_app_runtime r; struct fake f; uint8_t packet[E87_STATE_PACKET_SIZE] = {1,2,3,4,5,6,7,8};
    E87_ASSERT_TRUE(init(&r, &f)); f.now = 123u;
    E87_ASSERT_TRUE(e87_app_runtime_try_enqueue_semantic(&r, 9u, packet));
    memset(packet, 0, sizeof(packet));
    E87_ASSERT_EQ_U32(1u, r.count);
    E87_ASSERT_EQ_U32(E87_APP_CORE_EVENT_SEMANTIC_PACKET, r.queue[0].type);
    E87_ASSERT_EQ_U32(123u, r.queue[0].now_ms);
    E87_ASSERT_EQ_U32(9u, r.queue[0].data.semantic.authorization_epoch);
    E87_ASSERT_EQ_U32(8u, r.queue[0].data.semantic.packet[7]);
    E87_ASSERT_EQ_U32(f.enters, f.exits);
}

E87_TEST(queue_overflow_is_terminal_and_rejects_later_ingress)
{
    struct e87_app_runtime r; struct fake f; struct e87_app_core_event e;
    unsigned i; memset(&e, 0, sizeof(e)); e.type = E87_APP_CORE_EVENT_POLL;
    E87_ASSERT_TRUE(init(&r, &f));
    for (i = 0; i < E87_APP_RUNTIME_QUEUE_CAPACITY; ++i) E87_ASSERT_TRUE(e87_app_runtime_try_enqueue(&r, &e));
    E87_ASSERT_TRUE(!e87_app_runtime_try_enqueue(&r, &e));
    E87_ASSERT_TRUE(e87_app_runtime_is_terminal(&r));
    E87_ASSERT_TRUE(!e87_app_runtime_try_enqueue(&r, &e));
}

static const struct e87_test_case cases[] = {
    E87_TEST_CASE(semantic_ingress_copies_packet_and_epoch),
    E87_TEST_CASE(queue_overflow_is_terminal_and_rejects_later_ingress),
};
const struct e87_test_suite e87_test_suite = {"app-runtime", cases, sizeof(cases)/sizeof(cases[0])};
