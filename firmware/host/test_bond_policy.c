#include "test_support.h"
#include "e87/e87_bond_policy.h"

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

static const struct e87_ble_peer owner = {
    UINT8_C(0), {UINT8_C(1), UINT8_C(2), UINT8_C(3),
                 UINT8_C(4), UINT8_C(5), UINT8_C(6)}
};
static const struct e87_ble_peer candidate = {
    UINT8_C(1), {UINT8_C(6), UINT8_C(5), UINT8_C(4),
                 UINT8_C(3), UINT8_C(2), UINT8_C(1)}
};
static const struct e87_ble_peer candidate_identity = {
    UINT8_C(1), {UINT8_C(7), UINT8_C(8), UINT8_C(9),
                 UINT8_C(10), UINT8_C(11), UINT8_C(12)}
};
static const struct e87_ble_peer stranger = {
    UINT8_C(0), {UINT8_C(9), UINT8_C(9), UINT8_C(9),
                 UINT8_C(9), UINT8_C(9), UINT8_C(9)}
};

#define FAKE_VENDOR_SLOTS 2u

struct fake_platform {
    struct e87_owner_record record;
    bool has_record;
    uint32_t saves;
    uint32_t fail_save_on;
    uint32_t resets;
    uint8_t slots;
    bool allow_cover;
    bool pair_accept;
    uint32_t pair_accept_calls;
    bool fail_pair_accept_enable;
    bool fail_pair_accept_disable;
    bool pair_accept_enable_side_effect_on_failure;
    bool vendor_used[FAKE_VENDOR_SLOTS];
    struct e87_ble_peer vendor_peer[FAKE_VENDOR_SLOTS];
    bool resolve_candidate_alias;
    bool resolve_candidate_to_owner;
    uint32_t exists_calls;
    uint32_t count_calls;
    uint32_t delete_calls;
    bool delete_no_effect;
    bool delete_false_after_effect;
    struct e87_ble_peer deleted;
    uint32_t clear_calls;
    bool fail_clear;
    bool clear_no_effect;
};

static bool peer_equal(const struct e87_ble_peer *left,
                       const struct e87_ble_peer *right)
{
    return left != NULL && right != NULL &&
           left->address_type == right->address_type &&
           memcmp(left->address, right->address,
                  E87_BLE_ADDRESS_SIZE) == 0;
}

static int vendor_find(const struct fake_platform *fake,
                       const struct e87_ble_peer *peer)
{
    unsigned int index;
    const struct e87_ble_peer *resolved = peer;

    if (fake->resolve_candidate_to_owner &&
        peer_equal(peer, &candidate)) {
        resolved = &owner;
    } else if (fake->resolve_candidate_alias &&
        peer_equal(peer, &candidate)) {
        resolved = &candidate_identity;
    }

    for (index = 0U; index < FAKE_VENDOR_SLOTS; index += 1U) {
        if (fake->vendor_used[index] &&
            peer_equal(&fake->vendor_peer[index], resolved)) {
            return (int)index;
        }
    }
    return -1;
}

static uint16_t vendor_count_value(const struct fake_platform *fake)
{
    uint16_t count = UINT16_C(0);
    unsigned int index;

    for (index = 0U; index < FAKE_VENDOR_SLOTS; index += 1U) {
        count += fake->vendor_used[index] ? UINT16_C(1) : UINT16_C(0);
    }
    return count;
}

static bool vendor_add(struct fake_platform *fake,
                       const struct e87_ble_peer *peer)
{
    unsigned int index;
    const struct e87_ble_peer *stored = peer;

    if (fake->resolve_candidate_to_owner &&
        peer_equal(peer, &candidate)) {
        stored = &owner;
    } else if (fake->resolve_candidate_alias &&
        peer_equal(peer, &candidate)) {
        stored = &candidate_identity;
    }

    if (vendor_find(fake, peer) >= 0) {
        return true;
    }
    for (index = 0U; index < FAKE_VENDOR_SLOTS; index += 1U) {
        if (!fake->vendor_used[index]) {
            fake->vendor_used[index] = true;
            fake->vendor_peer[index] = *stored;
            return true;
        }
    }
    return false;
}

static bool vendor_remove(struct fake_platform *fake,
                          const struct e87_ble_peer *peer)
{
    const int index = vendor_find(fake, peer);

    if (index < 0) {
        return false;
    }
    fake->vendor_used[index] = false;
    memset(&fake->vendor_peer[index], 0,
           sizeof(fake->vendor_peer[index]));
    return true;
}

static bool load_record(void *context, struct e87_owner_record *out)
{
    struct fake_platform *fake = (struct fake_platform *)context;

    if (!fake->has_record) {
        return false;
    }
    *out = fake->record;
    return true;
}

static bool save_record(void *context,
                        const struct e87_owner_record *record)
{
    struct fake_platform *fake = (struct fake_platform *)context;

    fake->saves += UINT32_C(1);
    if (fake->fail_save_on != UINT32_C(0) &&
        fake->saves == fake->fail_save_on) {
        return false;
    }
    fake->record = *record;
    fake->has_record = true;
    return true;
}

static void config_reset(void *context, uint8_t slots, bool allow_cover)
{
    struct fake_platform *fake = (struct fake_platform *)context;

    fake->resets += UINT32_C(1);
    fake->slots = slots;
    fake->allow_cover = allow_cover;
}

static bool pair_accept(void *context, bool accept)
{
    struct fake_platform *fake = (struct fake_platform *)context;

    fake->pair_accept_calls += UINT32_C(1);
    if ((accept && fake->fail_pair_accept_enable) ||
        (!accept && fake->fail_pair_accept_disable)) {
        if (accept &&
            fake->pair_accept_enable_side_effect_on_failure) {
            fake->pair_accept = true;
        }
        return false;
    }
    fake->pair_accept = accept;
    return true;
}

static bool remote_exists(void *context,
                          const struct e87_ble_peer *peer)
{
    struct fake_platform *fake = (struct fake_platform *)context;

    fake->exists_calls += UINT32_C(1);
    return vendor_find(fake, peer) >= 0;
}

static bool table_count(void *context, uint16_t *out_count)
{
    struct fake_platform *fake = (struct fake_platform *)context;

    fake->count_calls += UINT32_C(1);
    if (out_count == NULL) {
        return false;
    }
    *out_count = vendor_count_value(fake);
    return true;
}

static bool delete_remote(void *context,
                          const struct e87_ble_peer *peer)
{
    struct fake_platform *fake = (struct fake_platform *)context;
    bool removed;

    fake->delete_calls += UINT32_C(1);
    fake->deleted = *peer;
    if (fake->delete_no_effect) {
        return false;
    }
    removed = vendor_remove(fake, peer);
    return fake->delete_false_after_effect ? false : removed;
}

static bool clear_all(void *context)
{
    struct fake_platform *fake = (struct fake_platform *)context;

    fake->clear_calls += UINT32_C(1);
    if (fake->fail_clear) {
        return false;
    }
    if (fake->clear_no_effect) {
        return true;
    }
    memset(fake->vendor_used, 0, sizeof(fake->vendor_used));
    memset(fake->vendor_peer, 0, sizeof(fake->vendor_peer));
    return true;
}

static struct e87_bond_ops ops_for(struct fake_platform *fake)
{
    const struct e87_bond_ops ops = {
        fake, load_record, save_record, config_reset, pair_accept,
        remote_exists, table_count, delete_remote, clear_all,
    };

    return ops;
}

static bool seed_owner(struct fake_platform *fake, uint32_t generation)
{
    fake->has_record = true;
    return e87_owner_record_make_stable(
               &fake->record, &owner, generation) &&
           vendor_add(fake, &owner);
}

static bool boot_owner(struct fake_platform *fake,
                       struct e87_bond_policy *policy,
                       struct e87_bond_ops *ops)
{
    if (!seed_owner(fake, UINT32_C(41))) {
        return false;
    }
    *ops = ops_for(fake);
    return e87_bond_policy_boot(policy, ops);
}

static bool prepare_pairing(struct e87_bond_policy *policy)
{
    return e87_bond_policy_open_pairing(policy) &&
           e87_bond_policy_stage_candidate(policy, &candidate) &&
           e87_bond_policy_phase(policy) ==
               E87_BOND_PHASE_SAVE_REPLACING &&
           e87_bond_policy_advance(policy) ==
               E87_BOND_ADVANCE_PROGRESSED &&
           e87_bond_policy_phase(policy) ==
               E87_BOND_PHASE_VERIFY_PRIOR &&
           e87_bond_policy_advance(policy) ==
               E87_BOND_ADVANCE_PROGRESSED &&
           e87_bond_policy_phase(policy) ==
               E87_BOND_PHASE_AWAIT_CANDIDATE;
}

static bool pair_candidate(struct fake_platform *fake,
                           struct e87_bond_policy *policy,
                           bool encryption_first)
{
    if (!vendor_add(fake, &candidate)) {
        return false;
    }
    if (!e87_bond_policy_on_identity(
            policy, &candidate,
            fake->resolve_candidate_alias
                ? &candidate_identity : &candidate)) {
        return false;
    }
    if (encryption_first) {
        e87_bond_policy_on_encryption(policy, &candidate, true);
        e87_bond_policy_on_pair_added(policy, &candidate, true);
    } else {
        e87_bond_policy_on_pair_added(policy, &candidate, true);
        e87_bond_policy_on_encryption(policy, &candidate, true);
    }
    return e87_bond_policy_phase(policy) ==
           E87_BOND_PHASE_VERIFY_CANDIDATE;
}

static void drain(struct e87_bond_policy *policy)
{
    unsigned int guard;

    for (guard = 0U;
         guard < 32U &&
         e87_bond_policy_phase(policy) != E87_BOND_PHASE_IDLE &&
         e87_bond_policy_phase(policy) != E87_BOND_PHASE_AWAIT_REBOOT;
         guard += 1U) {
        (void)e87_bond_policy_advance(policy);
    }
}

E87_TEST(record_validation_covers_stable_replacing_and_retiring)
{
    struct e87_owner_record record;

    E87_ASSERT_TRUE(e87_owner_record_make_stable(
        &record, &owner, UINT32_C(7)));
    E87_ASSERT_TRUE(e87_owner_record_is_valid(&record));
    record.phase = E87_OWNER_RECORD_REPLACING;
    record.candidate = candidate;
    record.checksum = e87_owner_record_checksum(&record);
    E87_ASSERT_TRUE(e87_owner_record_is_valid(&record));
    record.phase = E87_OWNER_RECORD_RETIRING;
    record.owner = candidate;
    record.candidate = owner;
    record.checksum = e87_owner_record_checksum(&record);
    E87_ASSERT_TRUE(e87_owner_record_is_valid(&record));
    memset(&record.candidate, 0, sizeof(record.candidate));
    record.checksum = e87_owner_record_checksum(&record);
    E87_ASSERT_TRUE(e87_owner_record_is_valid(&record));
    record.has_owner = UINT8_C(0);
    record.checksum = e87_owner_record_checksum(&record);
    E87_ASSERT_TRUE(!e87_owner_record_is_valid(&record));
}

E87_TEST(stable_boot_only_verifies_the_single_logical_owner)
{
    struct fake_platform fake;
    struct e87_bond_policy policy;
    struct e87_bond_ops ops;
    struct e87_ble_peer actual;

    memset(&fake, 0, sizeof(fake));
    E87_ASSERT_TRUE(boot_owner(&fake, &policy, &ops));
    E87_ASSERT_EQ_U32(1U, fake.resets);
    E87_ASSERT_EQ_U32(2U, fake.slots);
    E87_ASSERT_TRUE(!fake.allow_cover);
    E87_ASSERT_TRUE(!fake.pair_accept);
    E87_ASSERT_EQ_U32(1U, fake.exists_calls);
    E87_ASSERT_EQ_U32(1U, fake.count_calls);
    E87_ASSERT_EQ_U32(0U, fake.delete_calls);
    E87_ASSERT_EQ_U32(0U, fake.clear_calls);
    E87_ASSERT_TRUE(e87_bond_policy_owner(&policy, &actual));
    E87_ASSERT_TRUE(peer_equal(&owner, &actual));
    E87_ASSERT_TRUE(vendor_remove(&fake, &owner));
    E87_ASSERT_TRUE(!e87_bond_policy_boot(&policy, &ops));
}

E87_TEST(missing_or_corrupt_record_clears_untrusted_vendor_bonds)
{
    struct fake_platform fake;
    struct e87_bond_policy policy;
    struct e87_bond_ops ops;

    memset(&fake, 0, sizeof(fake));
    E87_ASSERT_TRUE(vendor_add(&fake, &stranger));
    ops = ops_for(&fake);
    E87_ASSERT_TRUE(e87_bond_policy_boot(&policy, &ops));
    E87_ASSERT_EQ_U32(1U, fake.clear_calls);
    E87_ASSERT_EQ_U32(0U, vendor_count_value(&fake));
    E87_ASSERT_TRUE(!e87_bond_policy_has_owner(&policy));
    memset(&fake, 0, sizeof(fake));
    E87_ASSERT_TRUE(seed_owner(&fake, UINT32_C(7)));
    fake.record.checksum ^= UINT32_C(1);
    ops = ops_for(&fake);
    E87_ASSERT_TRUE(e87_bond_policy_boot(&policy, &ops));
    E87_ASSERT_EQ_U32(1U, fake.clear_calls);
    E87_ASSERT_EQ_U32(0U, vendor_count_value(&fake));

    memset(&fake, 0, sizeof(fake));
    E87_ASSERT_TRUE(vendor_add(&fake, &stranger));
    fake.clear_no_effect = true;
    ops = ops_for(&fake);
    E87_ASSERT_TRUE(!e87_bond_policy_boot(&policy, &ops));
    E87_ASSERT_TRUE(vendor_find(&fake, &stranger) >= 0);
}

E87_TEST(pair_accept_failures_are_fail_closed_and_retryable)
{
    struct fake_platform fake;
    struct e87_bond_policy policy;
    struct e87_bond_ops ops;

    memset(&fake, 0, sizeof(fake));
    fake.fail_pair_accept_disable = true;
    ops = ops_for(&fake);
    E87_ASSERT_TRUE(!e87_bond_policy_boot(&policy, &ops));
    E87_ASSERT_EQ_U32(1U, fake.pair_accept_calls);
    fake.fail_pair_accept_disable = false;
    E87_ASSERT_TRUE(e87_bond_policy_boot(&policy, &ops));
    E87_ASSERT_TRUE(e87_bond_policy_open_pairing(&policy));
    E87_ASSERT_TRUE(!fake.pair_accept);
    E87_ASSERT_TRUE(e87_bond_policy_stage_candidate(
        &policy, &candidate));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&policy));
    fake.fail_pair_accept_enable = true;
    fake.fail_pair_accept_disable = true;
    fake.pair_accept_enable_side_effect_on_failure = true;
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_FAILED,
                      e87_bond_policy_advance(&policy));
    E87_ASSERT_TRUE(!e87_bond_policy_pairing_open(&policy));
    E87_ASSERT_TRUE(fake.pair_accept);
    E87_ASSERT_TRUE(!e87_bond_policy_allow_just_works(
        &policy, &candidate));
    fake.fail_pair_accept_enable = false;
    fake.fail_pair_accept_disable = false;
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&policy));
    E87_ASSERT_TRUE(!fake.pair_accept);
}

E87_TEST(replacing_record_precedes_exact_candidate_authorization)
{
    struct fake_platform fake;
    struct e87_bond_policy policy;
    struct e87_bond_ops ops;

    memset(&fake, 0, sizeof(fake));
    E87_ASSERT_TRUE(boot_owner(&fake, &policy, &ops));
    E87_ASSERT_TRUE(e87_bond_policy_open_pairing(&policy));
    E87_ASSERT_TRUE(!fake.pair_accept);
    E87_ASSERT_TRUE(e87_bond_policy_stage_candidate(
        &policy, &candidate));
    E87_ASSERT_TRUE(!fake.pair_accept);
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_SAVE_REPLACING,
                      e87_bond_policy_phase(&policy));
    E87_ASSERT_TRUE(!e87_bond_policy_allow_just_works(
        &policy, &candidate));
    E87_ASSERT_TRUE(!e87_bond_policy_stage_candidate(
        &policy, &stranger));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&policy));
    E87_ASSERT_EQ_U32(E87_OWNER_RECORD_REPLACING, fake.record.phase);
    E87_ASSERT_TRUE(!fake.pair_accept);
    E87_ASSERT_TRUE(peer_equal(&owner, &fake.record.owner));
    E87_ASSERT_TRUE(peer_equal(&candidate, &fake.record.candidate));
    E87_ASSERT_TRUE(!e87_bond_policy_allow_just_works(
        &policy, &candidate));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&policy));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_AWAIT_CANDIDATE,
                      e87_bond_policy_phase(&policy));
    E87_ASSERT_TRUE(fake.pair_accept);
    E87_ASSERT_TRUE(e87_bond_policy_allow_just_works(
        &policy, &candidate));
    E87_ASSERT_TRUE(!e87_bond_policy_allow_just_works(
        &policy, &owner));
    E87_ASSERT_TRUE(!e87_bond_policy_allow_just_works(
        &policy, &stranger));
    e87_bond_policy_on_pair_added(&policy, &stranger, true);
    e87_bond_policy_on_encryption(&policy, &stranger, true);
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_AWAIT_CANDIDATE,
                      e87_bond_policy_phase(&policy));
    E87_ASSERT_EQ_U32(1U, fake.saves);
}

E87_TEST(pair_close_failure_blocks_commit_until_retry)
{
    struct fake_platform fake;
    struct e87_bond_policy policy;
    struct e87_bond_ops ops;

    memset(&fake, 0, sizeof(fake));
    E87_ASSERT_TRUE(boot_owner(&fake, &policy, &ops));
    E87_ASSERT_TRUE(prepare_pairing(&policy));
    E87_ASSERT_TRUE(vendor_add(&fake, &candidate));
    E87_ASSERT_TRUE(e87_bond_policy_on_identity(
        &policy, &candidate, &candidate));
    e87_bond_policy_on_pair_added(&policy, &candidate, true);
    fake.fail_pair_accept_disable = true;
    e87_bond_policy_on_encryption(&policy, &candidate, true);
    E87_ASSERT_TRUE(!e87_bond_policy_pairing_open(&policy));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_CLOSE_PAIRING,
                      e87_bond_policy_phase(&policy));
    E87_ASSERT_EQ_U32(1U, fake.saves);
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_FAILED,
                      e87_bond_policy_advance(&policy));
    fake.fail_pair_accept_disable = false;
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&policy));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_VERIFY_CANDIDATE,
                      e87_bond_policy_phase(&policy));
}

E87_TEST(connection_peer_is_canonicalized_before_owner_publication)
{
    struct fake_platform fake;
    struct e87_bond_policy policy;
    struct e87_bond_ops ops;
    struct e87_ble_peer actual;

    memset(&fake, 0, sizeof(fake));
    fake.resolve_candidate_alias = true;
    E87_ASSERT_TRUE(boot_owner(&fake, &policy, &ops));
    E87_ASSERT_TRUE(prepare_pairing(&policy));
    E87_ASSERT_TRUE(!e87_bond_policy_on_identity(
        &policy, &stranger, &candidate_identity));
    E87_ASSERT_TRUE(!e87_bond_policy_on_identity(
        &policy, &candidate, &owner));
    E87_ASSERT_TRUE(pair_candidate(&fake, &policy, false));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&policy));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_SAVE_RETIRING,
                      e87_bond_policy_phase(&policy));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&policy));
    E87_ASSERT_TRUE(peer_equal(
        &candidate_identity, &fake.record.owner));
    E87_ASSERT_TRUE(peer_equal(&owner, &fake.record.candidate));
    E87_ASSERT_TRUE(e87_bond_policy_owner(&policy, &actual));
    E87_ASSERT_TRUE(peer_equal(&candidate_identity, &actual));
}

E87_TEST(existing_owner_rpa_is_rejected_before_journal_or_delete)
{
    struct fake_platform fake;
    struct e87_bond_policy policy;
    struct e87_bond_ops ops;
    struct e87_ble_peer actual;

    memset(&fake, 0, sizeof(fake));
    E87_ASSERT_TRUE(boot_owner(&fake, &policy, &ops));
    fake.resolve_candidate_to_owner = true;
    E87_ASSERT_TRUE(e87_bond_policy_open_pairing(&policy));
    E87_ASSERT_TRUE(!e87_bond_policy_stage_candidate(
        &policy, &candidate));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_IDLE,
                      e87_bond_policy_phase(&policy));
    E87_ASSERT_EQ_U32(0U, fake.saves);
    E87_ASSERT_TRUE(e87_bond_policy_close_pairing(&policy));
    E87_ASSERT_EQ_U32(0U, fake.delete_calls);
    E87_ASSERT_EQ_U32(E87_OWNER_RECORD_STABLE, fake.record.phase);
    E87_ASSERT_TRUE(vendor_find(&fake, &owner) >= 0);
    E87_ASSERT_TRUE(e87_bond_policy_owner(&policy, &actual));
    E87_ASSERT_TRUE(peer_equal(&owner, &actual));
}

E87_TEST(close_after_only_pair_add_rolls_back_instead_of_stalling)
{
    struct fake_platform fake;
    struct e87_bond_policy policy;
    struct e87_bond_ops ops;
    struct e87_ble_peer actual;

    memset(&fake, 0, sizeof(fake));
    E87_ASSERT_TRUE(boot_owner(&fake, &policy, &ops));
    E87_ASSERT_TRUE(prepare_pairing(&policy));
    E87_ASSERT_TRUE(vendor_add(&fake, &candidate));
    e87_bond_policy_on_pair_added(&policy, &candidate, true);
    E87_ASSERT_TRUE(e87_bond_policy_close_pairing(&policy));
    E87_ASSERT_TRUE(!e87_bond_policy_pairing_open(&policy));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_ROLLBACK_DELETE_CANDIDATE,
                      e87_bond_policy_phase(&policy));
    drain(&policy);
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_IDLE,
                      e87_bond_policy_phase(&policy));
    E87_ASSERT_TRUE(e87_bond_policy_owner(&policy, &actual));
    E87_ASSERT_TRUE(peer_equal(&owner, &actual));
    E87_ASSERT_TRUE(vendor_find(&fake, &candidate) < 0);
}

E87_TEST(commit_publishes_after_retiring_save_and_defers_cleanup_to_reboot)
{
    struct fake_platform fake;
    struct e87_bond_policy policy;
    struct e87_bond_ops ops;
    struct e87_ble_peer actual;

    memset(&fake, 0, sizeof(fake));
    E87_ASSERT_TRUE(boot_owner(&fake, &policy, &ops));
    E87_ASSERT_TRUE(prepare_pairing(&policy));
    E87_ASSERT_TRUE(pair_candidate(&fake, &policy, true));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&policy));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_SAVE_RETIRING,
                      e87_bond_policy_phase(&policy));
    fake.fail_save_on = fake.saves + UINT32_C(1);
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_FAILED,
                      e87_bond_policy_advance(&policy));
    E87_ASSERT_TRUE(e87_bond_policy_owner(&policy, &actual));
    E87_ASSERT_TRUE(peer_equal(&owner, &actual));
    E87_ASSERT_EQ_U32(E87_OWNER_RECORD_REPLACING, fake.record.phase);
    fake.fail_save_on = UINT32_C(0);
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&policy));
    E87_ASSERT_EQ_U32(E87_OWNER_RECORD_RETIRING, fake.record.phase);
    E87_ASSERT_TRUE(peer_equal(&candidate, &fake.record.owner));
    E87_ASSERT_TRUE(peer_equal(&owner, &fake.record.candidate));
    E87_ASSERT_TRUE(e87_bond_policy_owner(&policy, &actual));
    E87_ASSERT_TRUE(peer_equal(&candidate, &actual));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_AWAIT_REBOOT,
                      e87_bond_policy_phase(&policy));
    E87_ASSERT_EQ_U32(E87_OWNER_RECORD_RETIRING, fake.record.phase);
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_NOOP,
                      e87_bond_policy_advance(&policy));
    E87_ASSERT_EQ_U32(0U, fake.delete_calls);
    E87_ASSERT_TRUE(vendor_find(&fake, &candidate) >= 0);
    E87_ASSERT_TRUE(vendor_find(&fake, &owner) >= 0);
}

E87_TEST(candidate_rollback_delete_and_verification_are_retryable)
{
    struct fake_platform fake;
    struct e87_bond_policy policy;
    struct e87_bond_ops ops;
    struct e87_ble_peer actual;

    memset(&fake, 0, sizeof(fake));
    E87_ASSERT_TRUE(boot_owner(&fake, &policy, &ops));
    E87_ASSERT_TRUE(prepare_pairing(&policy));
    E87_ASSERT_TRUE(vendor_add(&fake, &candidate));
    e87_bond_policy_on_pair_added(&policy, &candidate, false);
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_ROLLBACK_DELETE_CANDIDATE,
                      e87_bond_policy_phase(&policy));
    fake.delete_no_effect = true;
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&policy));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_FAILED,
                      e87_bond_policy_advance(&policy));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_ROLLBACK_DELETE_CANDIDATE,
                      e87_bond_policy_phase(&policy));
    fake.delete_no_effect = false;
    fake.delete_false_after_effect = true;
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&policy));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&policy));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_ROLLBACK_VERIFY_PRIOR,
                      e87_bond_policy_phase(&policy));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&policy));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_ROLLBACK_SAVE_STABLE,
                      e87_bond_policy_phase(&policy));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&policy));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_IDLE,
                      e87_bond_policy_phase(&policy));
    E87_ASSERT_TRUE(e87_bond_policy_owner(&policy, &actual));
    E87_ASSERT_TRUE(peer_equal(&owner, &actual));
    E87_ASSERT_TRUE(vendor_find(&fake, &owner) >= 0);
    E87_ASSERT_TRUE(vendor_find(&fake, &candidate) < 0);
}

E87_TEST(rollback_missing_prior_never_declares_idle)
{
    struct fake_platform fake;
    struct e87_bond_policy policy;
    struct e87_bond_ops ops;

    memset(&fake, 0, sizeof(fake));
    E87_ASSERT_TRUE(boot_owner(&fake, &policy, &ops));
    E87_ASSERT_TRUE(prepare_pairing(&policy));
    E87_ASSERT_TRUE(vendor_add(&fake, &candidate));
    e87_bond_policy_on_encryption(&policy, &candidate, false);
    E87_ASSERT_TRUE(vendor_remove(&fake, &owner));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&policy));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&policy));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_ROLLBACK_VERIFY_PRIOR,
                      e87_bond_policy_phase(&policy));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_FAILED,
                      e87_bond_policy_advance(&policy));
    E87_ASSERT_EQ_U32(E87_OWNER_RECORD_REPLACING, fake.record.phase);
}

E87_TEST(replacing_boot_rolls_back_candidate_and_restores_stable)
{
    struct fake_platform fake;
    struct e87_bond_policy first;
    struct e87_bond_policy rebooted;
    struct e87_bond_ops ops;
    struct e87_ble_peer actual;

    memset(&fake, 0, sizeof(fake));
    E87_ASSERT_TRUE(boot_owner(&fake, &first, &ops));
    E87_ASSERT_TRUE(prepare_pairing(&first));
    E87_ASSERT_TRUE(vendor_add(&fake, &candidate));
    E87_ASSERT_TRUE(e87_bond_policy_boot(&rebooted, &ops));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_ROLLBACK_DELETE_CANDIDATE,
                      e87_bond_policy_phase(&rebooted));
    drain(&rebooted);
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_IDLE,
                      e87_bond_policy_phase(&rebooted));
    E87_ASSERT_EQ_U32(E87_OWNER_RECORD_STABLE, fake.record.phase);
    E87_ASSERT_TRUE(e87_bond_policy_owner(&rebooted, &actual));
    E87_ASSERT_TRUE(peer_equal(&owner, &actual));
    E87_ASSERT_TRUE(vendor_find(&fake, &owner) >= 0);
    E87_ASSERT_TRUE(vendor_find(&fake, &candidate) < 0);
}

E87_TEST(replacing_journal_crash_boundaries_restore_prior_owner)
{
    struct fake_platform fake;
    struct e87_bond_policy first;
    struct e87_bond_policy rebooted;
    struct e87_bond_ops ops;

    memset(&fake, 0, sizeof(fake));
    E87_ASSERT_TRUE(boot_owner(&fake, &first, &ops));
    E87_ASSERT_TRUE(e87_bond_policy_open_pairing(&first));
    E87_ASSERT_TRUE(e87_bond_policy_stage_candidate(
        &first, &candidate));
    fake.fail_save_on = fake.saves + UINT32_C(1);
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_FAILED,
                      e87_bond_policy_advance(&first));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_SAVE_REPLACING,
                      e87_bond_policy_phase(&first));
    E87_ASSERT_TRUE(!e87_bond_policy_allow_just_works(
        &first, &candidate));
    fake.fail_save_on = UINT32_C(0);
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&first));

    /* Power loss after REPLACING, before the vendor inserted candidate. */
    E87_ASSERT_TRUE(e87_bond_policy_boot(&rebooted, &ops));
    drain(&rebooted);
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_IDLE,
                      e87_bond_policy_phase(&rebooted));
    E87_ASSERT_EQ_U32(E87_OWNER_RECORD_STABLE, fake.record.phase);
    E87_ASSERT_TRUE(vendor_find(&fake, &owner) >= 0);
    E87_ASSERT_TRUE(vendor_find(&fake, &candidate) < 0);

    /* Power loss after both candidate proofs but before RETIRING save. */
    E87_ASSERT_TRUE(e87_bond_policy_open_pairing(&rebooted));
    E87_ASSERT_TRUE(e87_bond_policy_stage_candidate(
        &rebooted, &candidate));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&rebooted));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&rebooted));
    E87_ASSERT_TRUE(pair_candidate(&fake, &rebooted, false));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&rebooted));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_SAVE_RETIRING,
                      e87_bond_policy_phase(&rebooted));
    E87_ASSERT_TRUE(e87_bond_policy_boot(&first, &ops));
    drain(&first);
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_IDLE,
                      e87_bond_policy_phase(&first));
    E87_ASSERT_TRUE(vendor_find(&fake, &owner) >= 0);
    E87_ASSERT_TRUE(vendor_find(&fake, &candidate) < 0);
}

E87_TEST(retiring_cleanup_requires_a_later_boot_to_seal_stable)
{
    struct fake_platform fake;
    struct e87_bond_policy first;
    struct e87_bond_policy rebooted;
    struct e87_bond_policy confirmed;
    struct e87_bond_ops ops;
    struct e87_ble_peer actual;

    memset(&fake, 0, sizeof(fake));
    E87_ASSERT_TRUE(boot_owner(&fake, &first, &ops));
    E87_ASSERT_TRUE(prepare_pairing(&first));
    E87_ASSERT_TRUE(pair_candidate(&fake, &first, false));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&first));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&first));
    E87_ASSERT_EQ_U32(E87_OWNER_RECORD_RETIRING, fake.record.phase);
    E87_ASSERT_TRUE(e87_bond_policy_boot(&rebooted, &ops));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_BOOT_VERIFY_RETIRING,
                      e87_bond_policy_phase(&rebooted));
    drain(&rebooted);
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_AWAIT_REBOOT,
                      e87_bond_policy_phase(&rebooted));
    E87_ASSERT_EQ_U32(E87_OWNER_RECORD_RETIRING, fake.record.phase);
    E87_ASSERT_TRUE(vendor_find(&fake, &owner) < 0);

    E87_ASSERT_TRUE(e87_bond_policy_boot(&confirmed, &ops));
    drain(&confirmed);
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_IDLE,
                      e87_bond_policy_phase(&confirmed));
    E87_ASSERT_EQ_U32(E87_OWNER_RECORD_STABLE, fake.record.phase);
    E87_ASSERT_TRUE(e87_bond_policy_owner(&confirmed, &actual));
    E87_ASSERT_TRUE(peer_equal(&candidate, &actual));
}

E87_TEST(retiring_delete_crash_and_stable_save_failure_are_retryable)
{
    struct fake_platform fake;
    struct e87_bond_policy first;
    struct e87_bond_policy rebooted;
    struct e87_bond_ops ops;

    memset(&fake, 0, sizeof(fake));
    E87_ASSERT_TRUE(boot_owner(&fake, &first, &ops));
    E87_ASSERT_TRUE(prepare_pairing(&first));
    E87_ASSERT_TRUE(pair_candidate(&fake, &first, false));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&first));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&first));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_AWAIT_REBOOT,
                      e87_bond_policy_phase(&first));

    E87_ASSERT_TRUE(e87_bond_policy_boot(&rebooted, &ops));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&rebooted));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_DELETE_RETIRED,
                      e87_bond_policy_phase(&rebooted));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&rebooted));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_VERIFY_RETIRED_ABSENT,
                      e87_bond_policy_phase(&rebooted));

    /* Power loss after delete but before the absence check. */
    E87_ASSERT_TRUE(e87_bond_policy_boot(&first, &ops));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&first));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_BOOT_SAVE_STABLE,
                      e87_bond_policy_phase(&first));
    fake.fail_save_on = fake.saves + UINT32_C(1);
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_FAILED,
                      e87_bond_policy_advance(&first));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_BOOT_SAVE_STABLE,
                      e87_bond_policy_phase(&first));
    E87_ASSERT_EQ_U32(E87_OWNER_RECORD_RETIRING, fake.record.phase);
    fake.fail_save_on = UINT32_C(0);
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&first));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_IDLE,
                      e87_bond_policy_phase(&first));
    E87_ASSERT_EQ_U32(E87_OWNER_RECORD_STABLE, fake.record.phase);
}

E87_TEST(retiring_boot_missing_new_owner_reverts_to_intact_prior)
{
    struct fake_platform fake;
    struct e87_bond_policy first;
    struct e87_bond_policy rebooted;
    struct e87_bond_ops ops;
    struct e87_ble_peer actual;

    memset(&fake, 0, sizeof(fake));
    E87_ASSERT_TRUE(boot_owner(&fake, &first, &ops));
    E87_ASSERT_TRUE(prepare_pairing(&first));
    E87_ASSERT_TRUE(pair_candidate(&fake, &first, false));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&first));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&first));
    E87_ASSERT_TRUE(vendor_remove(&fake, &candidate));
    E87_ASSERT_TRUE(e87_bond_policy_boot(&rebooted, &ops));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&rebooted));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_BOOT_SAVE_STABLE,
                      e87_bond_policy_phase(&rebooted));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&rebooted));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_IDLE,
                      e87_bond_policy_phase(&rebooted));
    E87_ASSERT_TRUE(e87_bond_policy_owner(&rebooted, &actual));
    E87_ASSERT_TRUE(peer_equal(&owner, &actual));
    E87_ASSERT_EQ_U32(E87_OWNER_RECORD_STABLE, fake.record.phase);
}

E87_TEST(initial_unowned_pairing_is_confirmed_on_next_boot)
{
    struct fake_platform fake;
    struct e87_bond_policy first;
    struct e87_bond_policy rebooted;
    struct e87_bond_ops ops;
    struct e87_ble_peer actual;

    memset(&fake, 0, sizeof(fake));
    ops = ops_for(&fake);
    E87_ASSERT_TRUE(e87_bond_policy_boot(&first, &ops));
    E87_ASSERT_TRUE(prepare_pairing(&first));
    E87_ASSERT_TRUE(pair_candidate(&fake, &first, false));
    drain(&first);
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_AWAIT_REBOOT,
                      e87_bond_policy_phase(&first));
    E87_ASSERT_EQ_U32(E87_OWNER_RECORD_RETIRING, fake.record.phase);
    E87_ASSERT_EQ_U32(0U, fake.delete_calls);
    E87_ASSERT_TRUE(e87_bond_policy_boot(&rebooted, &ops));
    drain(&rebooted);
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_IDLE,
                      e87_bond_policy_phase(&rebooted));
    E87_ASSERT_TRUE(e87_bond_policy_owner(&rebooted, &actual));
    E87_ASSERT_TRUE(peer_equal(&candidate, &actual));
}

E87_TEST(initial_owner_loss_reverts_to_empty_stable_for_repairing)
{
    struct fake_platform fake;
    struct e87_bond_policy first;
    struct e87_bond_policy rebooted;
    struct e87_bond_ops ops;

    memset(&fake, 0, sizeof(fake));
    ops = ops_for(&fake);
    E87_ASSERT_TRUE(e87_bond_policy_boot(&first, &ops));
    E87_ASSERT_TRUE(prepare_pairing(&first));
    E87_ASSERT_TRUE(pair_candidate(&fake, &first, false));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&first));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&first));
    E87_ASSERT_EQ_U32(E87_OWNER_RECORD_RETIRING, fake.record.phase);
    E87_ASSERT_TRUE(vendor_remove(&fake, &candidate));

    E87_ASSERT_TRUE(e87_bond_policy_boot(&rebooted, &ops));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&rebooted));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_BOOT_SAVE_STABLE,
                      e87_bond_policy_phase(&rebooted));
    E87_ASSERT_TRUE(!e87_bond_policy_has_owner(&rebooted));
    E87_ASSERT_EQ_U32(E87_BOND_ADVANCE_PROGRESSED,
                      e87_bond_policy_advance(&rebooted));
    E87_ASSERT_EQ_U32(E87_BOND_PHASE_IDLE,
                      e87_bond_policy_phase(&rebooted));
    E87_ASSERT_EQ_U32(E87_OWNER_RECORD_STABLE, fake.record.phase);
    E87_ASSERT_EQ_U32(0U, fake.record.has_owner);
    E87_ASSERT_TRUE(e87_bond_policy_open_pairing(&rebooted));
}

E87_TEST(generation_overflow_and_invalid_or_existing_candidate_fail_closed)
{
    struct fake_platform fake;
    struct e87_bond_policy policy;
    struct e87_bond_ops ops;
    struct e87_ble_peer bad = candidate;

    memset(&fake, 0, sizeof(fake));
    E87_ASSERT_TRUE(seed_owner(&fake, UINT32_MAX));
    ops = ops_for(&fake);
    E87_ASSERT_TRUE(e87_bond_policy_boot(&policy, &ops));
    E87_ASSERT_TRUE(!e87_bond_policy_open_pairing(&policy));
    memset(&fake, 0, sizeof(fake));
    E87_ASSERT_TRUE(boot_owner(&fake, &policy, &ops));
    E87_ASSERT_TRUE(e87_bond_policy_open_pairing(&policy));
    bad.address_type = UINT8_C(2);
    E87_ASSERT_TRUE(!e87_bond_policy_stage_candidate(&policy, &bad));
    E87_ASSERT_TRUE(!e87_bond_policy_stage_candidate(&policy, &owner));
}

static const struct e87_test_case cases[] = {
    E87_TEST_CASE(record_validation_covers_stable_replacing_and_retiring),
    E87_TEST_CASE(stable_boot_only_verifies_the_single_logical_owner),
    E87_TEST_CASE(missing_or_corrupt_record_clears_untrusted_vendor_bonds),
    E87_TEST_CASE(pair_accept_failures_are_fail_closed_and_retryable),
    E87_TEST_CASE(replacing_record_precedes_exact_candidate_authorization),
    E87_TEST_CASE(pair_close_failure_blocks_commit_until_retry),
    E87_TEST_CASE(connection_peer_is_canonicalized_before_owner_publication),
    E87_TEST_CASE(existing_owner_rpa_is_rejected_before_journal_or_delete),
    E87_TEST_CASE(close_after_only_pair_add_rolls_back_instead_of_stalling),
    E87_TEST_CASE(commit_publishes_after_retiring_save_and_defers_cleanup_to_reboot),
    E87_TEST_CASE(candidate_rollback_delete_and_verification_are_retryable),
    E87_TEST_CASE(rollback_missing_prior_never_declares_idle),
    E87_TEST_CASE(replacing_boot_rolls_back_candidate_and_restores_stable),
    E87_TEST_CASE(replacing_journal_crash_boundaries_restore_prior_owner),
    E87_TEST_CASE(retiring_cleanup_requires_a_later_boot_to_seal_stable),
    E87_TEST_CASE(retiring_delete_crash_and_stable_save_failure_are_retryable),
    E87_TEST_CASE(retiring_boot_missing_new_owner_reverts_to_intact_prior),
    E87_TEST_CASE(initial_unowned_pairing_is_confirmed_on_next_boot),
    E87_TEST_CASE(initial_owner_loss_reverts_to_empty_stable_for_repairing),
    E87_TEST_CASE(generation_overflow_and_invalid_or_existing_candidate_fail_closed),
};

const struct e87_test_suite e87_test_suite = {
    "bond-policy", cases, sizeof(cases) / sizeof(cases[0]),
};
