#include "e87/e87_bond_policy.h"

#include <string.h>

static uint32_t hash_byte(uint32_t hash, uint8_t byte)
{
    return (hash ^ (uint32_t)byte) * UINT32_C(16777619);
}

static uint32_t hash_u16(uint32_t hash, uint16_t value)
{
    hash = hash_byte(hash, (uint8_t)value);
    return hash_byte(hash, (uint8_t)(value >> 8U));
}

static uint32_t hash_u32(uint32_t hash, uint32_t value)
{
    hash = hash_byte(hash, (uint8_t)value);
    hash = hash_byte(hash, (uint8_t)(value >> 8U));
    hash = hash_byte(hash, (uint8_t)(value >> 16U));
    return hash_byte(hash, (uint8_t)(value >> 24U));
}

static uint32_t hash_peer(uint32_t hash,
                          const struct e87_ble_peer *peer)
{
    size_t index;

    hash = hash_byte(hash, peer->address_type);
    for (index = 0U; index < E87_BLE_ADDRESS_SIZE; index += 1U) {
        hash = hash_byte(hash, peer->address[index]);
    }
    return hash;
}

uint32_t
e87_owner_record_checksum(
    const struct e87_owner_record *record)
{
    uint32_t hash = UINT32_C(2166136261);

    if (record == NULL) {
        return UINT32_C(0);
    }
    hash = hash_u32(hash, record->magic);
    hash = hash_u16(hash, record->version);
    hash = hash_u16(hash, record->phase);
    hash = hash_u32(hash, record->generation);
    hash = hash_byte(hash, record->has_owner);
    hash = hash_peer(hash, &record->owner);
    return hash_peer(hash, &record->candidate);
}

static bool peer_equal(const struct e87_ble_peer *left,
                       const struct e87_ble_peer *right)
{
    return left != NULL && right != NULL &&
           left->address_type == right->address_type &&
           memcmp(left->address, right->address,
                  E87_BLE_ADDRESS_SIZE) == 0;
}

static bool peer_is_zero(const struct e87_ble_peer *peer)
{
    size_t index;

    if (peer == NULL || peer->address_type != UINT8_C(0)) {
        return false;
    }
    for (index = 0U; index < E87_BLE_ADDRESS_SIZE; index += 1U) {
        if (peer->address[index] != UINT8_C(0)) {
            return false;
        }
    }
    return true;
}

static bool peer_is_valid(const struct e87_ble_peer *peer)
{
    size_t index;
    bool has_nonzero_address = false;

    if (peer == NULL || peer->address_type > UINT8_C(1)) {
        return false;
    }
    for (index = 0U; index < E87_BLE_ADDRESS_SIZE; index += 1U) {
        has_nonzero_address =
            has_nonzero_address ||
            peer->address[index] != UINT8_C(0);
    }
    return has_nonzero_address;
}

static void seal_record(struct e87_owner_record *record)
{
    record->checksum = e87_owner_record_checksum(record);
}

static void make_empty_stable(struct e87_owner_record *record,
                              uint32_t generation)
{
    memset(record, 0, sizeof(*record));
    record->magic = E87_OWNER_RECORD_MAGIC;
    record->version = E87_OWNER_RECORD_VERSION;
    record->phase = E87_OWNER_RECORD_STABLE;
    record->generation = generation;
    seal_record(record);
}

bool
e87_owner_record_make_stable(
    struct e87_owner_record *record,
    const struct e87_ble_peer *owner,
    uint32_t generation)
{
    if (record == NULL || !peer_is_valid(owner)) {
        return false;
    }
    make_empty_stable(record, generation);
    record->has_owner = UINT8_C(1);
    record->owner = *owner;
    seal_record(record);
    return true;
}

bool
e87_owner_record_is_valid(
    const struct e87_owner_record *record)
{
    if (record == NULL ||
        record->magic != E87_OWNER_RECORD_MAGIC ||
        record->version != E87_OWNER_RECORD_VERSION ||
        record->has_owner > UINT8_C(1) ||
        (record->phase != E87_OWNER_RECORD_STABLE &&
         record->phase != E87_OWNER_RECORD_REPLACING &&
         record->phase != E87_OWNER_RECORD_RETIRING) ||
        record->checksum != e87_owner_record_checksum(record)) {
        return false;
    }

    if (record->phase == E87_OWNER_RECORD_STABLE) {
        return peer_is_zero(&record->candidate) &&
               ((record->has_owner == UINT8_C(1) &&
                 peer_is_valid(&record->owner)) ||
                (record->has_owner == UINT8_C(0) &&
                 peer_is_zero(&record->owner)));
    }
    if (record->phase == E87_OWNER_RECORD_REPLACING) {
        return peer_is_valid(&record->candidate) &&
               ((record->has_owner == UINT8_C(1) &&
                 peer_is_valid(&record->owner) &&
                 !peer_equal(&record->owner,
                             &record->candidate)) ||
                (record->has_owner == UINT8_C(0) &&
                 peer_is_zero(&record->owner)));
    }
    return record->has_owner == UINT8_C(1) &&
           peer_is_valid(&record->owner) &&
           (peer_is_zero(&record->candidate) ||
            (peer_is_valid(&record->candidate) &&
             !peer_equal(&record->owner, &record->candidate)));
}

static bool ops_are_valid(const struct e87_bond_ops *ops)
{
    return ops != NULL && ops->load != NULL &&
           ops->save != NULL && ops->list_config_reset != NULL &&
           ops->pair_accept != NULL &&
           ops->remote_exists != NULL &&
           ops->table_count != NULL &&
           ops->delete_remote != NULL && ops->clear_all != NULL;
}

static bool read_count(struct e87_bond_policy *policy,
                       uint16_t expected)
{
    uint16_t actual = UINT16_MAX;

    return policy->private_ops.table_count(
               policy->private_ops.context, &actual) &&
           actual == expected;
}

static bool verify_empty(struct e87_bond_policy *policy)
{
    return read_count(policy, UINT16_C(0));
}

static bool verify_exact_one(struct e87_bond_policy *policy,
                             const struct e87_ble_peer *peer)
{
    return peer_is_valid(peer) &&
           read_count(policy, UINT16_C(1)) &&
           policy->private_ops.remote_exists(
               policy->private_ops.context, peer);
}

static bool verify_exact_two(struct e87_bond_policy *policy,
                             const struct e87_ble_peer *first,
                             const struct e87_ble_peer *last)
{
    return peer_is_valid(first) && peer_is_valid(last) &&
           !peer_equal(first, last) &&
           read_count(policy, UINT16_C(2)) &&
           policy->private_ops.remote_exists(
               policy->private_ops.context, first) &&
           policy->private_ops.remote_exists(
               policy->private_ops.context, last);
}

static bool verify_prior(struct e87_bond_policy *policy)
{
    if (policy->private_record.has_owner == UINT8_C(1)) {
        return verify_exact_one(policy,
                                &policy->private_record.owner);
    }
    return verify_empty(policy);
}

static void clear_candidate(struct e87_bond_policy *policy)
{
    memset(&policy->private_candidate, 0,
           sizeof(policy->private_candidate));
    memset(&policy->private_candidate_identity, 0,
           sizeof(policy->private_candidate_identity));
    policy->private_candidate_staged = false;
    policy->private_candidate_identity_known = false;
    policy->private_pair_added = false;
    policy->private_encrypted = false;
}

static bool stop_pairing(struct e87_bond_policy *policy)
{
    if (!policy->private_pairing_open &&
        !policy->private_stop_pending) {
        return true;
    }
    policy->private_pairing_open = false;
    policy->private_stop_pending = true;
    if (!policy->private_ops.pair_accept(
            policy->private_ops.context, false)) {
        return false;
    }
    policy->private_stop_pending = false;
    return true;
}

static void finish_abort(struct e87_bond_policy *policy)
{
    policy->private_abort_pending = false;
    policy->private_phase =
        E87_BOND_PHASE_ROLLBACK_DELETE_CANDIDATE;
}

static bool begin_abort(struct e87_bond_policy *policy)
{
    policy->private_abort_pending = true;
    if (!stop_pairing(policy)) {
        return false;
    }
    finish_abort(policy);
    return true;
}

static bool verify_stable_record(struct e87_bond_policy *policy)
{
    uint16_t count = UINT16_MAX;

    if (policy->private_record.has_owner == UINT8_C(1)) {
        if (!verify_exact_one(policy,
                              &policy->private_record.owner)) {
            return false;
        }
        policy->private_owner = policy->private_record.owner;
        policy->private_has_owner = true;
        return true;
    }

    if (!policy->private_ops.table_count(
            policy->private_ops.context, &count)) {
        return false;
    }
    if (count != UINT16_C(0)) {
        if (!policy->private_ops.clear_all(
                policy->private_ops.context) ||
            !verify_empty(policy)) {
            return false;
        }
    }
    return true;
}

bool
e87_bond_policy_boot(
    struct e87_bond_policy *policy,
    const struct e87_bond_ops *ops)
{
    struct e87_bond_policy initialized;
    struct e87_owner_record loaded;

    if (policy != NULL) {
        memset(policy, 0, sizeof(*policy));
    }
    if (policy == NULL || !ops_are_valid(ops)) {
        return false;
    }

    memset(&initialized, 0, sizeof(initialized));
    initialized.private_ops = *ops;
    initialized.private_phase = E87_BOND_PHASE_IDLE;
    make_empty_stable(&initialized.private_record, UINT32_C(0));

    ops->list_config_reset(ops->context, UINT8_C(2), false);
    if (!ops->pair_accept(ops->context, false)) {
        return false;
    }

    memset(&loaded, 0, sizeof(loaded));
    if (!ops->load(ops->context, &loaded) ||
        !e87_owner_record_is_valid(&loaded)) {
        if (!ops->clear_all(ops->context) ||
            !verify_empty(&initialized)) {
            return false;
        }
        *policy = initialized;
        return true;
    }

    initialized.private_record = loaded;
    if (loaded.phase == E87_OWNER_RECORD_STABLE) {
        if (!verify_stable_record(&initialized)) {
            return false;
        }
    } else if (loaded.phase == E87_OWNER_RECORD_REPLACING) {
        initialized.private_owner = loaded.owner;
        initialized.private_candidate = loaded.candidate;
        initialized.private_candidate_staged = true;
        initialized.private_phase =
            E87_BOND_PHASE_ROLLBACK_DELETE_CANDIDATE;
    } else {
        initialized.private_phase =
            E87_BOND_PHASE_BOOT_VERIFY_RETIRING;
    }

    *policy = initialized;
    return true;
}

bool
e87_bond_policy_open_pairing(
    struct e87_bond_policy *policy)
{
    if (policy == NULL ||
        policy->private_phase != E87_BOND_PHASE_IDLE ||
        policy->private_record.phase != E87_OWNER_RECORD_STABLE ||
        policy->private_pairing_open ||
        policy->private_stop_pending ||
        policy->private_abort_pending ||
        policy->private_candidate_staged ||
        policy->private_record.generation == UINT32_MAX) {
        return false;
    }

    if (!policy->private_ops.pair_accept(
            policy->private_ops.context, true)) {
        /* Failure can still leave the SDK's runtime gate open. */
        policy->private_stop_pending = true;
        (void)stop_pairing(policy);
        return false;
    }
    policy->private_pairing_open = true;
    return true;
}

bool
e87_bond_policy_close_pairing(
    struct e87_bond_policy *policy)
{
    if (policy == NULL) {
        return false;
    }
    if (policy->private_abort_pending) {
        if (!stop_pairing(policy)) {
            return false;
        }
        finish_abort(policy);
        return true;
    }
    if (policy->private_candidate_staged &&
        !(policy->private_pair_added &&
          policy->private_encrypted &&
          policy->private_candidate_identity_known) &&
        (policy->private_phase ==
             E87_BOND_PHASE_SAVE_REPLACING ||
         policy->private_phase == E87_BOND_PHASE_VERIFY_PRIOR ||
         policy->private_phase == E87_BOND_PHASE_AWAIT_CANDIDATE)) {
        return begin_abort(policy);
    }
    return stop_pairing(policy);
}

bool
e87_bond_policy_stage_candidate(
    struct e87_bond_policy *policy,
    const struct e87_ble_peer *candidate)
{
    if (policy == NULL || !peer_is_valid(candidate) ||
        !policy->private_pairing_open ||
        policy->private_stop_pending ||
        policy->private_abort_pending ||
        policy->private_phase != E87_BOND_PHASE_IDLE ||
        policy->private_candidate_staged ||
        policy->private_record.generation == UINT32_MAX ||
        (policy->private_has_owner &&
         peer_equal(&policy->private_owner, candidate)) ||
        policy->private_ops.remote_exists(
            policy->private_ops.context, candidate)) {
        return false;
    }

    policy->private_candidate = *candidate;
    policy->private_candidate_staged = true;
    memset(&policy->private_candidate_identity, 0,
           sizeof(policy->private_candidate_identity));
    policy->private_candidate_identity_known = false;
    policy->private_pair_added = false;
    policy->private_encrypted = false;
    policy->private_phase = E87_BOND_PHASE_SAVE_REPLACING;
    return true;
}

bool
e87_bond_policy_allow_just_works(
    const struct e87_bond_policy *policy,
    const struct e87_ble_peer *peer)
{
    return policy != NULL &&
           policy->private_pairing_open &&
           !policy->private_stop_pending &&
           !policy->private_abort_pending &&
           policy->private_phase == E87_BOND_PHASE_AWAIT_CANDIDATE &&
           policy->private_candidate_staged && peer_is_valid(peer) &&
           peer_equal(&policy->private_candidate, peer);
}

static void maybe_finish_candidate(
    struct e87_bond_policy *policy);

bool
e87_bond_policy_on_identity(
    struct e87_bond_policy *policy,
    const struct e87_ble_peer *connection_peer,
    const struct e87_ble_peer *identity_peer)
{
    if (policy == NULL || !policy->private_candidate_staged ||
        policy->private_phase != E87_BOND_PHASE_AWAIT_CANDIDATE ||
        !peer_equal(&policy->private_candidate, connection_peer) ||
        !peer_is_valid(identity_peer) ||
        (policy->private_has_owner &&
         peer_equal(&policy->private_owner, identity_peer))) {
        return false;
    }
    if (policy->private_candidate_identity_known) {
        return peer_equal(&policy->private_candidate_identity,
                          identity_peer);
    }
    policy->private_candidate_identity = *identity_peer;
    policy->private_candidate_identity_known = true;
    maybe_finish_candidate(policy);
    return true;
}

static void maybe_finish_candidate(struct e87_bond_policy *policy)
{
    if (!policy->private_pair_added ||
        !policy->private_encrypted ||
        !policy->private_candidate_identity_known) {
        return;
    }
    policy->private_phase = E87_BOND_PHASE_CLOSE_PAIRING;
    if (stop_pairing(policy)) {
        policy->private_phase =
            E87_BOND_PHASE_VERIFY_CANDIDATE;
    }
}

void
e87_bond_policy_on_pair_added(
    struct e87_bond_policy *policy,
    const struct e87_ble_peer *peer,
    bool success)
{
    if (policy == NULL || !policy->private_candidate_staged ||
        policy->private_phase != E87_BOND_PHASE_AWAIT_CANDIDATE ||
        !peer_equal(&policy->private_candidate, peer)) {
        return;
    }
    if (!success) {
        (void)begin_abort(policy);
        return;
    }
    policy->private_pair_added = true;
    maybe_finish_candidate(policy);
}

void
e87_bond_policy_on_encryption(
    struct e87_bond_policy *policy,
    const struct e87_ble_peer *peer,
    bool success)
{
    if (policy == NULL || !policy->private_candidate_staged ||
        policy->private_phase != E87_BOND_PHASE_AWAIT_CANDIDATE ||
        !peer_equal(&policy->private_candidate, peer)) {
        return;
    }
    if (!success) {
        (void)begin_abort(policy);
        return;
    }
    policy->private_encrypted = true;
    maybe_finish_candidate(policy);
}

static bool make_replacing_record(
    const struct e87_bond_policy *policy,
    struct e87_owner_record *record)
{
    if (policy == NULL || record == NULL ||
        policy->private_record.generation == UINT32_MAX ||
        !peer_is_valid(&policy->private_candidate)) {
        return false;
    }
    memset(record, 0, sizeof(*record));
    record->magic = E87_OWNER_RECORD_MAGIC;
    record->version = E87_OWNER_RECORD_VERSION;
    record->phase = E87_OWNER_RECORD_REPLACING;
    record->generation =
        policy->private_record.generation + UINT32_C(1);
    record->has_owner =
        policy->private_has_owner ? UINT8_C(1) : UINT8_C(0);
    if (policy->private_has_owner) {
        record->owner = policy->private_owner;
    }
    record->candidate = policy->private_candidate;
    seal_record(record);
    return e87_owner_record_is_valid(record);
}

static bool make_retiring_record(
    const struct e87_bond_policy *policy,
    struct e87_owner_record *record)
{
    if (policy == NULL || record == NULL ||
        !peer_is_valid(&policy->private_candidate) ||
        !policy->private_candidate_identity_known ||
        !peer_is_valid(&policy->private_candidate_identity)) {
        return false;
    }
    memset(record, 0, sizeof(*record));
    record->magic = E87_OWNER_RECORD_MAGIC;
    record->version = E87_OWNER_RECORD_VERSION;
    record->phase = E87_OWNER_RECORD_RETIRING;
    record->generation = policy->private_record.generation;
    record->has_owner = UINT8_C(1);
    record->owner = policy->private_candidate_identity;
    if (policy->private_record.has_owner == UINT8_C(1)) {
        record->candidate = policy->private_record.owner;
    }
    seal_record(record);
    return e87_owner_record_is_valid(record);
}

static bool save_current_owner_stable(struct e87_bond_policy *policy)
{
    struct e87_owner_record stable;
    bool made;

    if (policy->private_has_owner) {
        made = e87_owner_record_make_stable(
            &stable, &policy->private_owner,
            policy->private_record.generation);
    } else {
        make_empty_stable(&stable,
                          policy->private_record.generation);
        made = true;
    }
    if (!made || !policy->private_ops.save(
                     policy->private_ops.context, &stable)) {
        return false;
    }
    policy->private_record = stable;
    return true;
}

static bool verify_candidate_identity(
    struct e87_bond_policy *policy)
{
    if (!policy->private_candidate_identity_known ||
        !peer_is_valid(&policy->private_candidate_identity) ||
        !policy->private_ops.remote_exists(
            policy->private_ops.context,
            &policy->private_candidate) ||
        !policy->private_ops.remote_exists(
            policy->private_ops.context,
            &policy->private_candidate_identity)) {
        return false;
    }
    if (policy->private_record.has_owner == UINT8_C(1)) {
        return !peer_equal(&policy->private_record.owner,
                           &policy->private_candidate_identity) &&
               read_count(policy, UINT16_C(2)) &&
               policy->private_ops.remote_exists(
                   policy->private_ops.context,
                   &policy->private_record.owner);
    }
    return read_count(policy, UINT16_C(1));
}

static enum e87_bond_advance_result
advance_boot_retiring(struct e87_bond_policy *policy)
{
    const struct e87_ble_peer *new_owner =
        &policy->private_record.owner;
    const struct e87_ble_peer *retired =
        &policy->private_record.candidate;
    const bool has_retired = peer_is_valid(retired);
    const bool new_exists = policy->private_ops.remote_exists(
        policy->private_ops.context, new_owner);

    if (new_exists) {
        if (has_retired && policy->private_ops.remote_exists(
                               policy->private_ops.context,
                               retired)) {
            if (!verify_exact_two(policy, retired, new_owner)) {
                return E87_BOND_ADVANCE_FAILED;
            }
            policy->private_owner = *new_owner;
            policy->private_has_owner = true;
            policy->private_phase = E87_BOND_PHASE_DELETE_RETIRED;
            return E87_BOND_ADVANCE_PROGRESSED;
        }
        if (!verify_exact_one(policy, new_owner)) {
            return E87_BOND_ADVANCE_FAILED;
        }
        policy->private_owner = *new_owner;
        policy->private_has_owner = true;
        policy->private_phase = E87_BOND_PHASE_BOOT_SAVE_STABLE;
        return E87_BOND_ADVANCE_PROGRESSED;
    }

    if (has_retired && verify_exact_one(policy, retired)) {
        policy->private_owner = *retired;
        policy->private_has_owner = true;
        policy->private_phase = E87_BOND_PHASE_BOOT_SAVE_STABLE;
        return E87_BOND_ADVANCE_PROGRESSED;
    }
    if (!has_retired && verify_empty(policy)) {
        memset(&policy->private_owner, 0,
               sizeof(policy->private_owner));
        policy->private_has_owner = false;
        policy->private_phase = E87_BOND_PHASE_BOOT_SAVE_STABLE;
        return E87_BOND_ADVANCE_PROGRESSED;
    }
    return E87_BOND_ADVANCE_FAILED;
}

enum e87_bond_advance_result
e87_bond_policy_advance(
    struct e87_bond_policy *policy)
{
    if (policy == NULL) {
        return E87_BOND_ADVANCE_FAILED;
    }

    if (policy->private_abort_pending) {
        if (!stop_pairing(policy)) {
            return E87_BOND_ADVANCE_FAILED;
        }
        finish_abort(policy);
        return E87_BOND_ADVANCE_PROGRESSED;
    }
    if (policy->private_phase == E87_BOND_PHASE_IDLE &&
        policy->private_stop_pending) {
        return stop_pairing(policy)
                   ? E87_BOND_ADVANCE_PROGRESSED
                   : E87_BOND_ADVANCE_FAILED;
    }

    switch (policy->private_phase) {
    case E87_BOND_PHASE_IDLE:
    case E87_BOND_PHASE_AWAIT_CANDIDATE:
    case E87_BOND_PHASE_AWAIT_REBOOT:
        return E87_BOND_ADVANCE_NOOP;

    case E87_BOND_PHASE_SAVE_REPLACING: {
        struct e87_owner_record replacing;

        if (!make_replacing_record(policy, &replacing) ||
            !policy->private_ops.save(
                policy->private_ops.context, &replacing)) {
            return E87_BOND_ADVANCE_FAILED;
        }
        policy->private_record = replacing;
        policy->private_phase = E87_BOND_PHASE_VERIFY_PRIOR;
        return E87_BOND_ADVANCE_PROGRESSED;
    }

    case E87_BOND_PHASE_VERIFY_PRIOR:
        if (!verify_prior(policy)) {
            return E87_BOND_ADVANCE_FAILED;
        }
        if (policy->private_record.has_owner == UINT8_C(1)) {
            policy->private_owner = policy->private_record.owner;
            policy->private_has_owner = true;
        }
        policy->private_phase = E87_BOND_PHASE_AWAIT_CANDIDATE;
        return E87_BOND_ADVANCE_PROGRESSED;

    case E87_BOND_PHASE_CLOSE_PAIRING:
        if (!stop_pairing(policy)) {
            return E87_BOND_ADVANCE_FAILED;
        }
        policy->private_phase = E87_BOND_PHASE_VERIFY_CANDIDATE;
        return E87_BOND_ADVANCE_PROGRESSED;

    case E87_BOND_PHASE_VERIFY_CANDIDATE:
        if (!verify_candidate_identity(policy)) {
            (void)begin_abort(policy);
            return E87_BOND_ADVANCE_FAILED;
        }
        policy->private_phase = E87_BOND_PHASE_SAVE_RETIRING;
        return E87_BOND_ADVANCE_PROGRESSED;

    case E87_BOND_PHASE_SAVE_RETIRING: {
        struct e87_owner_record retiring;

        if (!make_retiring_record(policy, &retiring) ||
            !policy->private_ops.save(
                policy->private_ops.context, &retiring)) {
            return E87_BOND_ADVANCE_FAILED;
        }
        policy->private_record = retiring;
        policy->private_owner = retiring.owner;
        policy->private_has_owner = true;
        clear_candidate(policy);
        /*
         * Do not delete the prior key in the SDK initialization that added
         * the candidate. The vendor add path can report success before its
         * list-control metadata is durably rewritten. A reboot must first
         * prove the new key survived initialization repair.
         */
        policy->private_phase = E87_BOND_PHASE_AWAIT_REBOOT;
        return E87_BOND_ADVANCE_PROGRESSED;
    }

    case E87_BOND_PHASE_DELETE_RETIRED:
        if (!peer_is_valid(&policy->private_record.candidate)) {
            policy->private_phase = E87_BOND_PHASE_AWAIT_REBOOT;
            return E87_BOND_ADVANCE_PROGRESSED;
        }
        (void)policy->private_ops.delete_remote(
            policy->private_ops.context,
            &policy->private_record.candidate);
        policy->private_phase =
            E87_BOND_PHASE_VERIFY_RETIRED_ABSENT;
        return E87_BOND_ADVANCE_PROGRESSED;

    case E87_BOND_PHASE_VERIFY_RETIRED_ABSENT:
        if (policy->private_ops.remote_exists(
                policy->private_ops.context,
                &policy->private_record.candidate)) {
            policy->private_phase = E87_BOND_PHASE_DELETE_RETIRED;
            return E87_BOND_ADVANCE_FAILED;
        }
        if (!verify_exact_one(policy, &policy->private_record.owner)) {
            return E87_BOND_ADVANCE_FAILED;
        }
        policy->private_phase = E87_BOND_PHASE_AWAIT_REBOOT;
        return E87_BOND_ADVANCE_PROGRESSED;

    case E87_BOND_PHASE_ROLLBACK_DELETE_CANDIDATE:
        (void)policy->private_ops.delete_remote(
            policy->private_ops.context,
            &policy->private_candidate);
        policy->private_phase =
            E87_BOND_PHASE_ROLLBACK_VERIFY_CANDIDATE_ABSENT;
        return E87_BOND_ADVANCE_PROGRESSED;

    case E87_BOND_PHASE_ROLLBACK_VERIFY_CANDIDATE_ABSENT:
        if (policy->private_ops.remote_exists(
                policy->private_ops.context,
                &policy->private_candidate)) {
            policy->private_phase =
                E87_BOND_PHASE_ROLLBACK_DELETE_CANDIDATE;
            return E87_BOND_ADVANCE_FAILED;
        }
        policy->private_phase =
            E87_BOND_PHASE_ROLLBACK_VERIFY_PRIOR;
        return E87_BOND_ADVANCE_PROGRESSED;

    case E87_BOND_PHASE_ROLLBACK_VERIFY_PRIOR:
        if (!verify_prior(policy)) {
            return E87_BOND_ADVANCE_FAILED;
        }
        policy->private_has_owner =
            policy->private_record.has_owner == UINT8_C(1);
        if (policy->private_has_owner) {
            policy->private_owner = policy->private_record.owner;
        } else {
            memset(&policy->private_owner, 0,
                   sizeof(policy->private_owner));
        }
        policy->private_phase =
            E87_BOND_PHASE_ROLLBACK_SAVE_STABLE;
        return E87_BOND_ADVANCE_PROGRESSED;

    case E87_BOND_PHASE_ROLLBACK_SAVE_STABLE:
        if (!save_current_owner_stable(policy)) {
            return E87_BOND_ADVANCE_FAILED;
        }
        clear_candidate(policy);
        policy->private_phase = E87_BOND_PHASE_IDLE;
        return E87_BOND_ADVANCE_PROGRESSED;

    case E87_BOND_PHASE_BOOT_VERIFY_RETIRING:
        return advance_boot_retiring(policy);

    case E87_BOND_PHASE_BOOT_SAVE_STABLE:
        if (!save_current_owner_stable(policy)) {
            return E87_BOND_ADVANCE_FAILED;
        }
        policy->private_phase = E87_BOND_PHASE_IDLE;
        return E87_BOND_ADVANCE_PROGRESSED;

    default:
        return E87_BOND_ADVANCE_FAILED;
    }
}

enum e87_bond_phase
e87_bond_policy_phase(
    const struct e87_bond_policy *policy)
{
    return policy == NULL ? E87_BOND_PHASE_IDLE
                          : policy->private_phase;
}

bool
e87_bond_policy_pairing_open(
    const struct e87_bond_policy *policy)
{
    return policy != NULL && policy->private_pairing_open;
}

bool
e87_bond_policy_has_owner(
    const struct e87_bond_policy *policy)
{
    return policy != NULL && policy->private_has_owner;
}

bool
e87_bond_policy_owner(
    const struct e87_bond_policy *policy,
    struct e87_ble_peer *out)
{
    if (policy == NULL || out == NULL ||
        !policy->private_has_owner) {
        return false;
    }
    *out = policy->private_owner;
    return true;
}
