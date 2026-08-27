#include "test_support.h"
#include "e87/e87_build_info.h"
#include "e87/e87_state.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

static const uint8_t golden_packet[8] = {
    UINT8_C(0x01), UINT8_C(0x64), UINT8_C(0x00), UINT8_C(0x00),
    UINT8_C(0xBF), UINT8_C(0x06), UINT8_C(0x00), UINT8_C(0x00),
};

static bool bytes_equal(const void *left, const void *right, size_t length)
{
    return memcmp(left, right, length) == 0;
}

static bool metrics_equal(const struct e87_metrics *left,
                          const struct e87_metrics *right)
{
    return left->day == right->day &&
           left->week == right->week &&
           left->credit_cents == right->credit_cents;
}

static bool snapshot_equal(const struct e87_state_snapshot *left,
                           const struct e87_state_snapshot *right)
{
    return left->has_metrics == right->has_metrics &&
           metrics_equal(&left->metrics, &right->metrics) &&
           left->revision == right->revision;
}

static bool packet_is_valid(const uint8_t packet[8])
{
    return packet[0] == UINT8_C(1) &&
           packet[1] <= UINT8_C(100) &&
           packet[2] <= UINT8_C(100) &&
           packet[3] == UINT8_C(0) &&
           packet[4] == UINT8_C(0xBF) &&
           packet[5] == UINT8_C(0x06) &&
           packet[6] == UINT8_C(0x00) &&
           packet[7] == UINT8_C(0x00);
}

static bool decode_rejection_preserves(const uint8_t *packet,
                                       size_t length,
                                       enum e87_state_error expected)
{
    struct e87_metrics actual;
    struct e87_metrics before;

    memset(&actual, 0xA5, sizeof(actual));
    memcpy(&before, &actual, sizeof(before));
    return e87_state_decode(packet, length, &actual) == expected &&
           bytes_equal(&before, &actual, sizeof(actual));
}

struct fake_lock {
    bool held;
    uint32_t enter_count;
    uint32_t leave_count;
    uint32_t faults;
    e87_state_lock_token_t next_token;
    e87_state_lock_token_t active_token;
    e87_state_lock_token_t last_enter_token;
    e87_state_lock_token_t last_leave_token;
};

static e87_state_lock_token_t fake_enter(void *context)
{
    struct fake_lock *lock = (struct fake_lock *)context;

    lock->enter_count += UINT32_C(1);
    if (lock->held) {
        lock->faults += UINT32_C(1);
    }
    lock->held = true;
    lock->next_token += (e87_state_lock_token_t)UINT32_C(0x11);
    if (lock->next_token == (e87_state_lock_token_t)0) {
        lock->next_token = (e87_state_lock_token_t)UINT32_C(1);
    }
    lock->active_token = lock->next_token;
    lock->last_enter_token = lock->active_token;
    return lock->active_token;
}

static void fake_leave(void *context, e87_state_lock_token_t token)
{
    struct fake_lock *lock = (struct fake_lock *)context;

    lock->leave_count += UINT32_C(1);
    if (!lock->held) {
        lock->faults += UINT32_C(1);
    }
    if (token != lock->active_token) {
        lock->faults += UINT32_C(1);
    }
    lock->last_leave_token = token;
    lock->held = false;
}

static struct e87_state_sync fake_sync(struct fake_lock *lock)
{
    const struct e87_state_sync sync = {lock, fake_enter, fake_leave};

    return sync;
}

static bool fake_lock_is_clean(const struct fake_lock *lock)
{
    return !lock->held &&
           lock->faults == UINT32_C(0) &&
           lock->enter_count == lock->leave_count &&
           lock->last_enter_token == lock->last_leave_token;
}

E87_TEST(decode_accepts_golden_little_endian_vector)
{
    struct e87_metrics metrics;

    memset(&metrics, 0, sizeof(metrics));
    E87_ASSERT_EQ_U32(E87_STATE_OK,
                      e87_state_decode(golden_packet, sizeof(golden_packet),
                                       &metrics));
    E87_ASSERT_EQ_U32(UINT32_C(100), metrics.day);
    E87_ASSERT_EQ_U32(UINT32_C(0), metrics.week);
    E87_ASSERT_EQ_U32(UINT32_C(1727), metrics.credit_cents);
}

E87_TEST(decode_accepts_every_day_week_pair)
{
    uint8_t packet[8];
    unsigned int day;
    unsigned int week;

    for (day = 0U; day <= 100U; day += 1U) {
        for (week = 0U; week <= 100U; week += 1U) {
            struct e87_metrics metrics;

            memcpy(packet, golden_packet, sizeof(packet));
            packet[1] = (uint8_t)day;
            packet[2] = (uint8_t)week;
            memset(&metrics, 0xA5, sizeof(metrics));
            E87_ASSERT_EQ_U32(E87_STATE_OK,
                              e87_state_decode(packet, sizeof(packet), &metrics));
            E87_ASSERT_EQ_U32(day, metrics.day);
            E87_ASSERT_EQ_U32(week, metrics.week);
            E87_ASSERT_EQ_U32(UINT32_C(1727), metrics.credit_cents);
        }
    }
}

E87_TEST(decode_rejects_every_single_byte_mutation_atomically)
{
    uint8_t packet[8];
    size_t position;
    unsigned int replacement;

    for (position = 0U; position < sizeof(packet); position += 1U) {
        for (replacement = 0U; replacement <= UINT8_MAX; replacement += 1U) {
            struct e87_metrics actual;
            struct e87_metrics before;
            enum e87_state_error error;

            memcpy(packet, golden_packet, sizeof(packet));
            packet[position] = (uint8_t)replacement;
            memset(&actual, 0xA5, sizeof(actual));
            memcpy(&before, &actual, sizeof(before));
            error = e87_state_decode(packet, sizeof(packet), &actual);

            if (packet_is_valid(packet)) {
                E87_ASSERT_EQ_U32(E87_STATE_OK, error);
                E87_ASSERT_EQ_U32(packet[1], actual.day);
                E87_ASSERT_EQ_U32(packet[2], actual.week);
                E87_ASSERT_EQ_U32(UINT32_C(1727), actual.credit_cents);
            } else {
                E87_ASSERT_TRUE(error != E87_STATE_OK);
                E87_ASSERT_TRUE(bytes_equal(&before, &actual, sizeof(actual)));
            }
        }
    }
}

E87_TEST(decode_rejects_every_nonexact_length_without_reading)
{
    const uint8_t *unreadable = (const uint8_t *)(uintptr_t)UINT32_C(1);
    size_t length;

    for (length = 0U; length <= 64U; length += 1U) {
        if (length != E87_STATE_PACKET_SIZE) {
            E87_ASSERT_TRUE(decode_rejection_preserves(
                unreadable, length, E87_STATE_ERROR_LENGTH));
        }
    }
    E87_ASSERT_TRUE(decode_rejection_preserves(
        unreadable, SIZE_MAX, E87_STATE_ERROR_LENGTH));
}

E87_TEST(decode_rejects_null_arguments_atomically)
{
    struct e87_metrics actual;
    struct e87_metrics before;

    memset(&actual, 0xA5, sizeof(actual));
    memcpy(&before, &actual, sizeof(before));
    E87_ASSERT_EQ_U32(E87_STATE_ERROR_ARGUMENT,
                      e87_state_decode(NULL, E87_STATE_PACKET_SIZE, &actual));
    E87_ASSERT_TRUE(bytes_equal(&before, &actual, sizeof(actual)));
    E87_ASSERT_EQ_U32(E87_STATE_ERROR_ARGUMENT,
                      e87_state_decode(golden_packet,
                                       E87_STATE_PACKET_SIZE, NULL));
    E87_ASSERT_EQ_U32(E87_STATE_ERROR_ARGUMENT,
                      e87_state_decode(NULL, 0U, NULL));
}

E87_TEST(decode_uses_stable_error_precedence)
{
    uint8_t packet[8];

    E87_ASSERT_TRUE(decode_rejection_preserves(
        NULL, 7U, E87_STATE_ERROR_ARGUMENT));
    memset(packet, 0xFF, sizeof(packet));
    E87_ASSERT_TRUE(decode_rejection_preserves(
        packet, 7U, E87_STATE_ERROR_LENGTH));
    E87_ASSERT_TRUE(decode_rejection_preserves(
        packet, sizeof(packet), E87_STATE_ERROR_VERSION));
    packet[0] = UINT8_C(1);
    E87_ASSERT_TRUE(decode_rejection_preserves(
        packet, sizeof(packet), E87_STATE_ERROR_DAY));
    packet[1] = UINT8_C(100);
    E87_ASSERT_TRUE(decode_rejection_preserves(
        packet, sizeof(packet), E87_STATE_ERROR_WEEK));
    packet[2] = UINT8_C(100);
    E87_ASSERT_TRUE(decode_rejection_preserves(
        packet, sizeof(packet), E87_STATE_ERROR_FLAGS));
    packet[3] = UINT8_C(0);
    E87_ASSERT_TRUE(decode_rejection_preserves(
        packet, sizeof(packet), E87_STATE_ERROR_CREDIT));
}

E87_TEST(store_init_rejects_invalid_sync_without_mutation)
{
    struct e87_state_store store;
    struct e87_state_store before;
    struct fake_lock lock = {0};
    struct e87_state_sync sync = fake_sync(&lock);

    memset(&store, 0xA5, sizeof(store));
    memcpy(&before, &store, sizeof(before));
    E87_ASSERT_TRUE(!e87_state_store_init(NULL, &sync));
    E87_ASSERT_TRUE(!e87_state_store_init(&store, NULL));
    E87_ASSERT_TRUE(bytes_equal(&before, &store, sizeof(store)));
    sync.enter = NULL;
    E87_ASSERT_TRUE(!e87_state_store_init(&store, &sync));
    E87_ASSERT_TRUE(bytes_equal(&before, &store, sizeof(store)));
    sync = fake_sync(&lock);
    sync.leave = NULL;
    E87_ASSERT_TRUE(!e87_state_store_init(&store, &sync));
    E87_ASSERT_TRUE(bytes_equal(&before, &store, sizeof(store)));
    E87_ASSERT_EQ_U32(UINT32_C(0), lock.enter_count);
    E87_ASSERT_EQ_U32(UINT32_C(0), lock.leave_count);
    E87_ASSERT_EQ_U32(UINT32_C(0), lock.faults);
}

E87_TEST(store_initial_snapshot_is_empty_and_locked)
{
    struct fake_lock lock = {0};
    const struct e87_state_sync sync = fake_sync(&lock);
    struct e87_state_store store;
    struct e87_state_snapshot snapshot;

    E87_ASSERT_TRUE(e87_state_store_init(&store, &sync));
    E87_ASSERT_EQ_U32(UINT32_C(0), lock.enter_count);
    E87_ASSERT_EQ_U32(UINT32_C(0), lock.leave_count);
    memset(&snapshot, 0xA5, sizeof(snapshot));
    E87_ASSERT_TRUE(e87_state_snapshot(&store, &snapshot));
    E87_ASSERT_TRUE(!snapshot.has_metrics);
    E87_ASSERT_EQ_U32(UINT32_C(0), snapshot.metrics.day);
    E87_ASSERT_EQ_U32(UINT32_C(0), snapshot.metrics.week);
    E87_ASSERT_EQ_U32(UINT32_C(0), snapshot.metrics.credit_cents);
    E87_ASSERT_EQ_U32(UINT32_C(0), snapshot.revision);
    E87_ASSERT_EQ_U32(UINT32_C(1), lock.enter_count);
    E87_ASSERT_EQ_U32(UINT32_C(1), lock.leave_count);
    E87_ASSERT_TRUE(fake_lock_is_clean(&lock));
}

E87_TEST(store_first_commit_is_changed_and_coherent)
{
    struct fake_lock lock = {0};
    const struct e87_state_sync sync = fake_sync(&lock);
    const struct e87_metrics metrics = {
        UINT8_C(100), UINT8_C(0), UINT32_C(1727)
    };
    struct e87_state_store store;
    struct e87_state_snapshot snapshot;

    E87_ASSERT_TRUE(e87_state_store_init(&store, &sync));
    E87_ASSERT_TRUE(e87_state_commit(&store, &metrics));
    E87_ASSERT_TRUE(e87_state_snapshot(&store, &snapshot));
    E87_ASSERT_TRUE(snapshot.has_metrics);
    E87_ASSERT_TRUE(metrics_equal(&metrics, &snapshot.metrics));
    E87_ASSERT_EQ_U32(UINT32_C(1), snapshot.revision);
    E87_ASSERT_EQ_U32(UINT32_C(2), lock.enter_count);
    E87_ASSERT_EQ_U32(UINT32_C(2), lock.leave_count);
    E87_ASSERT_TRUE(fake_lock_is_clean(&lock));
}

E87_TEST(store_duplicate_is_false_without_revision_change)
{
    struct fake_lock lock = {0};
    const struct e87_state_sync sync = fake_sync(&lock);
    struct e87_metrics first;
    struct e87_metrics duplicate;
    struct e87_state_store store;
    struct e87_state_snapshot snapshot;

    memset(&first, 0x11, sizeof(first));
    first.day = UINT8_C(45);
    first.week = UINT8_C(67);
    first.credit_cents = UINT32_C(1727);
    memset(&duplicate, 0xEE, sizeof(duplicate));
    duplicate.day = UINT8_C(45);
    duplicate.week = UINT8_C(67);
    duplicate.credit_cents = UINT32_C(1727);

    E87_ASSERT_TRUE(e87_state_store_init(&store, &sync));
    E87_ASSERT_TRUE(e87_state_commit(&store, &first));
    E87_ASSERT_TRUE(!e87_state_commit(&store, &duplicate));
    E87_ASSERT_TRUE(e87_state_snapshot(&store, &snapshot));
    E87_ASSERT_TRUE(snapshot.has_metrics);
    E87_ASSERT_TRUE(metrics_equal(&duplicate, &snapshot.metrics));
    E87_ASSERT_EQ_U32(UINT32_C(1), snapshot.revision);
    E87_ASSERT_EQ_U32(UINT32_C(3), lock.enter_count);
    E87_ASSERT_EQ_U32(UINT32_C(3), lock.leave_count);
    E87_ASSERT_TRUE(fake_lock_is_clean(&lock));
}

E87_TEST(store_changed_commit_increments_once_and_old_snapshot_is_immutable)
{
    struct fake_lock lock = {0};
    const struct e87_state_sync sync = fake_sync(&lock);
    const struct e87_metrics first = {
        UINT8_C(12), UINT8_C(34), UINT32_C(1727)
    };
    const struct e87_metrics second = {
        UINT8_C(56), UINT8_C(78), UINT32_C(1727)
    };
    struct e87_state_store store;
    struct e87_state_snapshot old_snapshot;
    struct e87_state_snapshot old_copy;
    struct e87_state_snapshot current;

    E87_ASSERT_TRUE(e87_state_store_init(&store, &sync));
    E87_ASSERT_TRUE(e87_state_commit(&store, &first));
    E87_ASSERT_TRUE(e87_state_snapshot(&store, &old_snapshot));
    old_copy = old_snapshot;
    E87_ASSERT_TRUE(e87_state_commit(&store, &second));
    E87_ASSERT_TRUE(e87_state_snapshot(&store, &current));
    E87_ASSERT_TRUE(snapshot_equal(&old_snapshot, &old_copy));
    E87_ASSERT_TRUE(metrics_equal(&first, &old_snapshot.metrics));
    E87_ASSERT_EQ_U32(UINT32_C(1), old_snapshot.revision);
    E87_ASSERT_TRUE(metrics_equal(&second, &current.metrics));
    E87_ASSERT_EQ_U32(UINT32_C(2), current.revision);
    E87_ASSERT_EQ_U32(UINT32_C(4), lock.enter_count);
    E87_ASSERT_EQ_U32(UINT32_C(4), lock.leave_count);
    E87_ASSERT_TRUE(fake_lock_is_clean(&lock));
}

E87_TEST(store_rejects_direct_invalid_metrics_without_lock_or_mutation)
{
    struct fake_lock lock = {0};
    const struct e87_state_sync sync = fake_sync(&lock);
    struct e87_metrics invalid[] = {
        {UINT8_C(101), UINT8_C(0), UINT32_C(1727)},
        {UINT8_C(0), UINT8_C(101), UINT32_C(1727)},
        {UINT8_C(0), UINT8_C(0), UINT32_C(0)},
        {UINT8_C(0), UINT8_C(0), UINT32_C(1726)},
        {UINT8_C(0), UINT8_C(0), UINT32_C(1728)},
        {UINT8_C(0), UINT8_C(0), UINT32_C(0x0000BF06)},
        {UINT8_C(0), UINT8_C(0), UINT32_MAX},
    };
    struct e87_state_store store;
    struct e87_state_store before;
    size_t index;

    E87_ASSERT_TRUE(e87_state_store_init(&store, &sync));
    memcpy(&before, &store, sizeof(before));
    E87_ASSERT_TRUE(!e87_state_commit(NULL, &invalid[0]));
    E87_ASSERT_TRUE(!e87_state_commit(&store, NULL));
    for (index = 0U; index < sizeof(invalid) / sizeof(invalid[0]); index += 1U) {
        E87_ASSERT_TRUE(!e87_state_commit(&store, &invalid[index]));
    }
    E87_ASSERT_TRUE(bytes_equal(&before, &store, sizeof(store)));
    E87_ASSERT_EQ_U32(UINT32_C(0), lock.enter_count);
    E87_ASSERT_EQ_U32(UINT32_C(0), lock.leave_count);
    E87_ASSERT_EQ_U32(UINT32_C(0), lock.faults);
}

E87_TEST(store_pairs_each_enter_with_same_token_once)
{
    struct fake_lock lock = {0};
    const struct e87_state_sync sync = fake_sync(&lock);
    const struct e87_metrics first = {
        UINT8_C(1), UINT8_C(2), UINT32_C(1727)
    };
    const struct e87_metrics second = {
        UINT8_C(3), UINT8_C(4), UINT32_C(1727)
    };
    struct e87_state_store store;
    struct e87_state_snapshot snapshot;

    E87_ASSERT_TRUE(e87_state_store_init(&store, &sync));
    E87_ASSERT_TRUE(e87_state_snapshot(&store, &snapshot));
    E87_ASSERT_TRUE(e87_state_commit(&store, &first));
    E87_ASSERT_TRUE(!e87_state_commit(&store, &first));
    E87_ASSERT_TRUE(e87_state_snapshot(&store, &snapshot));
    E87_ASSERT_TRUE(e87_state_commit(&store, &second));
    E87_ASSERT_TRUE(e87_state_snapshot(&store, &snapshot));
    E87_ASSERT_EQ_U32(UINT32_C(6), lock.enter_count);
    E87_ASSERT_EQ_U32(UINT32_C(6), lock.leave_count);
    E87_ASSERT_TRUE(fake_lock_is_clean(&lock));
}

E87_TEST(snapshot_rejects_null_without_output_mutation)
{
    struct fake_lock lock = {0};
    const struct e87_state_sync sync = fake_sync(&lock);
    struct e87_state_store store;
    struct e87_state_snapshot actual;
    struct e87_state_snapshot before;

    E87_ASSERT_TRUE(e87_state_store_init(&store, &sync));
    memset(&actual, 0xA5, sizeof(actual));
    memcpy(&before, &actual, sizeof(before));
    E87_ASSERT_TRUE(!e87_state_snapshot(NULL, &actual));
    E87_ASSERT_TRUE(bytes_equal(&before, &actual, sizeof(actual)));
    E87_ASSERT_TRUE(!e87_state_snapshot(&store, NULL));
    E87_ASSERT_TRUE(!e87_state_snapshot(NULL, NULL));
    E87_ASSERT_EQ_U32(UINT32_C(0), lock.enter_count);
    E87_ASSERT_EQ_U32(UINT32_C(0), lock.leave_count);
    E87_ASSERT_EQ_U32(UINT32_C(0), lock.faults);
}

E87_TEST(build_info_matches_exact_40_byte_binary_vector)
{
    const struct e87_build_identity identity = {
        UINT8_C(2), UINT8_C(9), UINT8_C(255),
        {
            UINT8_C(0x00), UINT8_C(0x11), UINT8_C(0x22), UINT8_C(0x33),
            UINT8_C(0x44), UINT8_C(0x55), UINT8_C(0x66), UINT8_C(0x77),
            UINT8_C(0x88), UINT8_C(0x99), UINT8_C(0xAA), UINT8_C(0xBB),
            UINT8_C(0xCC), UINT8_C(0xDD), UINT8_C(0xEE), UINT8_C(0xFF),
        },
    };
    const uint8_t expected[40] = {
        UINT8_C(0x01), UINT8_C(0x07), UINT8_C(0x45), UINT8_C(0x38),
        UINT8_C(0x37), UINT8_C(0x2D), UINT8_C(0x4A), UINT8_C(0x44),
        UINT8_C(0x39), UINT8_C(0x38), UINT8_C(0x35), UINT8_C(0x35),
        UINT8_C(0x2D), UINT8_C(0x52), UINT8_C(0x31), UINT8_C(0x00),
        UINT8_C(0x00), UINT8_C(0x00), UINT8_C(0x02), UINT8_C(0x09),
        UINT8_C(0xFF), UINT8_C(0x00), UINT8_C(0x00), UINT8_C(0x11),
        UINT8_C(0x22), UINT8_C(0x33), UINT8_C(0x44), UINT8_C(0x55),
        UINT8_C(0x66), UINT8_C(0x77), UINT8_C(0x88), UINT8_C(0x99),
        UINT8_C(0xAA), UINT8_C(0xBB), UINT8_C(0xCC), UINT8_C(0xDD),
        UINT8_C(0xEE), UINT8_C(0xFF), UINT8_C(0x00), UINT8_C(0x00),
    };
    uint8_t actual[40];

    memset(actual, 0xA5, sizeof(actual));
    E87_ASSERT_TRUE(e87_build_info_encode(&identity, actual, sizeof(actual)));
    E87_ASSERT_TRUE(bytes_equal(expected, actual, sizeof(actual)));
}

E87_TEST(build_info_copies_all_semver_and_build_id_bytes_verbatim)
{
    const struct e87_build_identity identity = {
        UINT8_C(0), UINT8_C(128), UINT8_C(254),
        {
            UINT8_C(0xFF), UINT8_C(0xE0), UINT8_C(0xD1), UINT8_C(0xC2),
            UINT8_C(0xB3), UINT8_C(0xA4), UINT8_C(0x95), UINT8_C(0x86),
            UINT8_C(0x77), UINT8_C(0x68), UINT8_C(0x59), UINT8_C(0x4A),
            UINT8_C(0x3B), UINT8_C(0x2C), UINT8_C(0x1D), UINT8_C(0x0E),
        },
    };
    uint8_t actual[40];
    size_t index;

    E87_ASSERT_TRUE(e87_build_info_encode(&identity, actual, sizeof(actual)));
    E87_ASSERT_EQ_U32(UINT8_C(0), actual[18]);
    E87_ASSERT_EQ_U32(UINT8_C(128), actual[19]);
    E87_ASSERT_EQ_U32(UINT8_C(254), actual[20]);
    for (index = 0U; index < E87_BUILD_ID_BYTES; index += 1U) {
        E87_ASSERT_EQ_U32(identity.build_id[index], actual[22U + index]);
    }
    E87_ASSERT_EQ_U32(UINT8_C(0), actual[21]);
    E87_ASSERT_EQ_U32(UINT8_C(0), actual[38]);
    E87_ASSERT_EQ_U32(UINT8_C(0), actual[39]);
}

E87_TEST(build_info_rejects_every_nonexact_length_atomically)
{
    const struct e87_build_identity *unreadable =
        (const struct e87_build_identity *)(uintptr_t)UINT32_C(1);
    size_t length;

    for (length = 0U; length <= 64U; length += 1U) {
        uint8_t actual[40];
        uint8_t before[40];

        if (length == E87_BUILD_INFO_SIZE) {
            continue;
        }
        memset(actual, 0xA5, sizeof(actual));
        memcpy(before, actual, sizeof(before));
        E87_ASSERT_TRUE(!e87_build_info_encode(unreadable, actual, length));
        E87_ASSERT_TRUE(bytes_equal(before, actual, sizeof(actual)));
    }
    {
        uint8_t actual[40];
        uint8_t before[40];

        memset(actual, 0xA5, sizeof(actual));
        memcpy(before, actual, sizeof(before));
        E87_ASSERT_TRUE(!e87_build_info_encode(unreadable, actual, SIZE_MAX));
        E87_ASSERT_TRUE(bytes_equal(before, actual, sizeof(actual)));
    }
}

E87_TEST(build_info_rejects_null_arguments_atomically)
{
    const struct e87_build_identity identity = {0};
    uint8_t actual[40];
    uint8_t before[40];

    memset(actual, 0xA5, sizeof(actual));
    memcpy(before, actual, sizeof(before));
    E87_ASSERT_TRUE(!e87_build_info_encode(NULL, actual, sizeof(actual)));
    E87_ASSERT_TRUE(bytes_equal(before, actual, sizeof(actual)));
    E87_ASSERT_TRUE(!e87_build_info_encode(&identity, NULL, sizeof(actual)));
    E87_ASSERT_TRUE(!e87_build_info_encode(NULL, NULL, sizeof(actual)));
}

E87_TEST(build_info_is_deterministic_and_does_not_mutate_identity)
{
    struct e87_build_identity identity;
    struct e87_build_identity before;
    uint8_t first[40];
    uint8_t second[40];
    size_t index;

    memset(&identity, 0xA5, sizeof(identity));
    identity.semver_major = UINT8_C(7);
    identity.semver_minor = UINT8_C(8);
    identity.semver_patch = UINT8_C(9);
    for (index = 0U; index < E87_BUILD_ID_BYTES; index += 1U) {
        identity.build_id[index] = (uint8_t)(UINT8_C(0xF0) - (uint8_t)index);
    }
    memcpy(&before, &identity, sizeof(before));
    memset(first, 0x00, sizeof(first));
    memset(second, 0xFF, sizeof(second));
    E87_ASSERT_TRUE(e87_build_info_encode(&identity, first, sizeof(first)));
    E87_ASSERT_TRUE(e87_build_info_encode(&identity, second, sizeof(second)));
    E87_ASSERT_TRUE(bytes_equal(first, second, sizeof(first)));
    E87_ASSERT_TRUE(bytes_equal(&before, &identity, sizeof(identity)));
}

static const struct e87_test_case state_cases[] = {
    E87_TEST_CASE(decode_accepts_golden_little_endian_vector),
    E87_TEST_CASE(decode_accepts_every_day_week_pair),
    E87_TEST_CASE(decode_rejects_every_single_byte_mutation_atomically),
    E87_TEST_CASE(decode_rejects_every_nonexact_length_without_reading),
    E87_TEST_CASE(decode_rejects_null_arguments_atomically),
    E87_TEST_CASE(decode_uses_stable_error_precedence),
    E87_TEST_CASE(store_init_rejects_invalid_sync_without_mutation),
    E87_TEST_CASE(store_initial_snapshot_is_empty_and_locked),
    E87_TEST_CASE(store_first_commit_is_changed_and_coherent),
    E87_TEST_CASE(store_duplicate_is_false_without_revision_change),
    E87_TEST_CASE(store_changed_commit_increments_once_and_old_snapshot_is_immutable),
    E87_TEST_CASE(store_rejects_direct_invalid_metrics_without_lock_or_mutation),
    E87_TEST_CASE(store_pairs_each_enter_with_same_token_once),
    E87_TEST_CASE(snapshot_rejects_null_without_output_mutation),
    E87_TEST_CASE(build_info_matches_exact_40_byte_binary_vector),
    E87_TEST_CASE(build_info_copies_all_semver_and_build_id_bytes_verbatim),
    E87_TEST_CASE(build_info_rejects_every_nonexact_length_atomically),
    E87_TEST_CASE(build_info_rejects_null_arguments_atomically),
    E87_TEST_CASE(build_info_is_deterministic_and_does_not_mutate_identity),
};

const struct e87_test_suite e87_test_suite = {
    "semantic-state-build-info",
    state_cases,
    sizeof(state_cases) / sizeof(state_cases[0]),
};
