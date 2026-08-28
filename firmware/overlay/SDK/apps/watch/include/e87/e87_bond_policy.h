#ifndef E87_BOND_POLICY_H
#define E87_BOND_POLICY_H

#include <stdbool.h>
#include <stdint.h>

#define E87_BLE_ADDRESS_SIZE 6u
#define E87_OWNER_RECORD_MAGIC UINT32_C(0x4538374F)
#define E87_OWNER_RECORD_VERSION 1u

struct e87_ble_peer {
    uint8_t address_type;
    uint8_t address[E87_BLE_ADDRESS_SIZE];
};

enum e87_owner_record_phase {
    E87_OWNER_RECORD_STABLE = 1,
    E87_OWNER_RECORD_REPLACING = 2,
    E87_OWNER_RECORD_RETIRING = 3
};

/*
 * REPLACING stores owner=the still-authorized peer and candidate=the peer
 * being enrolled. RETIRING stores owner=the newly-authorized peer and
 * candidate=the retired peer whose vendor key still needs verified removal.
 * A zero RETIRING candidate denotes first-owner enrollment.
 */
struct e87_owner_record {
    uint32_t magic;
    uint16_t version;
    uint16_t phase;
    uint32_t generation;
    uint8_t has_owner;
    struct e87_ble_peer owner;
    struct e87_ble_peer candidate;
    uint32_t checksum;
};

typedef bool
    (*e87_bond_load_fn)(
        void *context,
        struct e87_owner_record *out);
typedef bool
    (*e87_bond_save_fn)(
        void *context,
        const struct e87_owner_record *record);
typedef void
    (*e87_bond_list_config_reset_fn)(
        void *context,
        uint8_t slots,
        bool allow_cover);
typedef bool
    (*e87_bond_pair_accept_fn)(
        void *context,
        bool accept);
typedef bool
    (*e87_bond_remote_fn)(
        void *context,
        const struct e87_ble_peer *peer);
typedef bool
    (*e87_bond_count_fn)(
        void *context,
        uint16_t *out_count);
typedef bool
    (*e87_bond_clear_all_fn)(void *context);

struct e87_bond_ops {
    void *context;
    e87_bond_load_fn load;
    e87_bond_save_fn save;
    e87_bond_list_config_reset_fn list_config_reset;
    e87_bond_pair_accept_fn pair_accept;
    e87_bond_remote_fn remote_exists;
    e87_bond_count_fn table_count;
    e87_bond_remote_fn delete_remote;
    e87_bond_clear_all_fn clear_all;
};

enum e87_bond_phase {
    E87_BOND_PHASE_IDLE = 0,
    E87_BOND_PHASE_SAVE_REPLACING = 1,
    E87_BOND_PHASE_VERIFY_PRIOR = 2,
    E87_BOND_PHASE_AWAIT_CANDIDATE = 3,
    E87_BOND_PHASE_CLOSE_PAIRING = 4,
    E87_BOND_PHASE_VERIFY_CANDIDATE = 5,
    E87_BOND_PHASE_SAVE_RETIRING = 6,
    E87_BOND_PHASE_DELETE_RETIRED = 7,
    E87_BOND_PHASE_VERIFY_RETIRED_ABSENT = 8,
    E87_BOND_PHASE_AWAIT_REBOOT = 9,
    E87_BOND_PHASE_ROLLBACK_DELETE_CANDIDATE = 10,
    E87_BOND_PHASE_ROLLBACK_VERIFY_CANDIDATE_ABSENT = 11,
    E87_BOND_PHASE_ROLLBACK_VERIFY_PRIOR = 12,
    E87_BOND_PHASE_ROLLBACK_SAVE_STABLE = 13,
    E87_BOND_PHASE_BOOT_VERIFY_RETIRING = 14,
    E87_BOND_PHASE_BOOT_SAVE_STABLE = 15
};

enum e87_bond_advance_result {
    E87_BOND_ADVANCE_NOOP = 0,
    E87_BOND_ADVANCE_PROGRESSED = 1,
    E87_BOND_ADVANCE_FAILED = 2
};

struct e87_bond_policy {
    struct e87_bond_ops private_ops;
    struct e87_owner_record private_record;
    struct e87_ble_peer private_owner;
    struct e87_ble_peer private_candidate;
    struct e87_ble_peer private_candidate_identity;
    enum e87_bond_phase private_phase;
    bool private_has_owner;
    bool private_pairing_open;
    bool private_stop_pending;
    bool private_abort_pending;
    bool private_candidate_staged;
    bool private_candidate_identity_known;
    bool private_pair_added;
    bool private_encrypted;
};

uint32_t
e87_owner_record_checksum(
    const struct e87_owner_record *record);

bool
e87_owner_record_make_stable(
    struct e87_owner_record *record,
    const struct e87_ble_peer *owner,
    uint32_t generation);

bool
e87_owner_record_is_valid(
    const struct e87_owner_record *record);

bool
e87_bond_policy_boot(
    struct e87_bond_policy *policy,
    const struct e87_bond_ops *ops);

bool
e87_bond_policy_open_pairing(
    struct e87_bond_policy *policy);

bool
e87_bond_policy_close_pairing(
    struct e87_bond_policy *policy);

bool
e87_bond_policy_stage_candidate(
    struct e87_bond_policy *policy,
    const struct e87_ble_peer *candidate);

bool
e87_bond_policy_allow_just_works(
    const struct e87_bond_policy *policy,
    const struct e87_ble_peer *peer);

/*
 * Associates the exact staged connection peer with the canonical identity
 * reported by the stack's identity-created/resolved event. Ownership is never
 * persisted from a potentially rotating connection address.
 */
bool
e87_bond_policy_on_identity(
    struct e87_bond_policy *policy,
    const struct e87_ble_peer *connection_peer,
    const struct e87_ble_peer *identity_peer);

void
e87_bond_policy_on_pair_added(
    struct e87_bond_policy *policy,
    const struct e87_ble_peer *peer,
    bool success);

void
e87_bond_policy_on_encryption(
    struct e87_bond_policy *policy,
    const struct e87_ble_peer *peer,
    bool success);

enum e87_bond_advance_result
e87_bond_policy_advance(
    struct e87_bond_policy *policy);

enum e87_bond_phase
e87_bond_policy_phase(
    const struct e87_bond_policy *policy);

bool
e87_bond_policy_pairing_open(
    const struct e87_bond_policy *policy);

bool
e87_bond_policy_has_owner(
    const struct e87_bond_policy *policy);

bool
e87_bond_policy_owner(
    const struct e87_bond_policy *policy,
    struct e87_ble_peer *out);

#endif
