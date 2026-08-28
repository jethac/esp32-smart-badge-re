#include "e87/e87_ble_target_sdk.h"

#include "e87/e87_ble_target.h"
#include "e87/e87_ble_control.h"
#include "e87/e87_ble_target_internal.h"

#include <string.h>

#define E87_BLE_ADV_INTERVAL_UNITS UINT32_C(160)
#define E87_BLE_ATT_PAYLOAD_SIZE 64u
#define E87_BLE_ATT_SEND_BUFFER_SIZE 128u
#define E87_BLE_ATT_RAM_SIZE \
    (ATT_CTRL_BLOCK_SIZE + E87_BLE_ATT_PAYLOAD_SIZE + \
     E87_BLE_ATT_SEND_BUFFER_SIZE)

/* Emitted by the pinned SM object but omitted from its public event macros. */
#ifndef SM_EVENT_IDENTITY_RESOLVING_FAILED
#define SM_EVENT_IDENTITY_RESOLVING_FAILED 0xd9u
#endif
#ifndef SM_EVENT_IDENTITY_RESOLVING_SUCCEEDED
#define SM_EVENT_IDENTITY_RESOLVING_SUCCEEDED 0xdau
#endif
#ifndef SM_EVENT_IDENTITY_CREATED
#define SM_EVENT_IDENTITY_CREATED 0xdeu
#endif

struct e87_ble_target_state {
    void *handle;
    struct e87_ble_target_ingress ingress;
    struct e87_bond_policy bond_policy;
    struct e87_ble_peer connection_peer;
    struct e87_ble_peer connection_identity;
    struct e87_ble_peer pending_identity;
    uint16_t connection_handle;
    uint16_t build_read_covered;
    uint16_t battery_cccd;
    uint8_t build_info[E87_BUILD_INFO_SIZE];
    uint8_t battery_percent;
    bool initialized;
    bool cleanup_pending;
    bool policy_ready;
    bool connected;
    bool connection_is_owner;
    bool connection_identity_known;
    bool advertising_enabled;
    bool disconnect_required;
    bool disconnect_pending;
    bool build_read_complete;
    volatile bool writes_enabled;
    bool authorization_was_active;
    bool release_epoch_invalidated;
    bool candidate_abort_pending;
    bool pair_result_pending;
    bool pair_result_success;
    bool encryption_pending;
    bool encryption_success;
    bool identity_pending;
    bool owner_resolution_pending;
    bool link_encrypted;
};

static struct e87_ble_target_state target;
static volatile uint32_t authorization_epoch;
static volatile bool authorization_epoch_exhausted;
static uint8_t att_ram[E87_BLE_ATT_RAM_SIZE] __attribute__((aligned(4)));

static const struct e87_build_identity build_identity = {
    0u, 1u, 0u,
    {0x1eu, 0x79u, 0x3du, 0xd7u, 0x6du, 0x2eu, 0xe1u, 0x94u,
     0xf8u, 0x9eu, 0x4du, 0x9du, 0xb3u, 0x4bu, 0x93u, 0x3cu}
};

bool e87_ble_target_epoch_advance(uint32_t *epoch, bool *exhausted)
{
    if (epoch == NULL || exhausted == NULL || *exhausted) {
        return false;
    }
    if (*epoch == UINT32_MAX) {
        *exhausted = true;
        return false;
    }
    *epoch += 1u;
    return true;
}

static bool advance_authorization_epoch(void)
{
    uint32_t next = authorization_epoch;
    bool exhausted = authorization_epoch_exhausted;
    const bool advanced =
        e87_ble_target_epoch_advance(&next, &exhausted);
    authorization_epoch_exhausted = exhausted;
    if (advanced) {
        authorization_epoch = next;
    } else {
        authorization_epoch_exhausted = true;
        target.writes_enabled = false;
    }
    return advanced;
}

static bool invalidate_authorization(void)
{
    target.authorization_was_active = false;
    return advance_authorization_epoch();
}

static void require_disconnect(void)
{
    if (!target.disconnect_required) {
        (void)invalidate_authorization();
    }
    target.disconnect_required = true;
}

static bool peer_equal(const struct e87_ble_peer *left,
                       const struct e87_ble_peer *right)
{
    return left != NULL && right != NULL &&
           left->address_type == right->address_type &&
           memcmp(left->address, right->address,
                  E87_BLE_ADDRESS_SIZE) == 0;
}

static bool peer_valid(const struct e87_ble_peer *peer)
{
    size_t index;
    bool nonzero = false;
    if (peer == NULL || peer->address_type > 1u) {
        return false;
    }
    for (index = 0u; index < E87_BLE_ADDRESS_SIZE; index += 1u) {
        nonzero = nonzero || peer->address[index] != 0u;
    }
    return nonzero;
}

static bool peer_is_rpa(const struct e87_ble_peer *peer)
{
    return peer_valid(peer) && peer->address_type == 1u &&
           (peer->address[0] & 0xc0u) == 0x40u;
}

static bool journal_load(void *context, struct e87_owner_record *out)
{
    (void)context;
    return e87_ble_target_journal_load(out);
}

static bool journal_save(void *context,
                         const struct e87_owner_record *record)
{
    (void)context;
    return e87_ble_target_journal_save(record);
}

static void list_config_reset(void *context, uint8_t slots, bool allow_cover)
{
    (void)context;
    ble_list_config_reset(slots, allow_cover ? 1u : 0u);
}

static bool pair_accept(void *context, bool accept)
{
    (void)context;
    return ble_list_pair_accept(accept ? 1u : 0u);
}

static bool remote_exists(void *context, const struct e87_ble_peer *peer)
{
    uint8_t address[E87_BLE_ADDRESS_SIZE];
    (void)context;
    if (!peer_valid(peer)) {
        return false;
    }
    memcpy(address, peer->address, sizeof(address));
    return ble_list_check_addr_is_exist(address, peer->address_type);
}

static bool table_count(void *context, uint16_t *out_count)
{
    (void)context;
    if (out_count == NULL) {
        return false;
    }
    *out_count = ble_list_get_count();
    return *out_count <= 2u;
}

static bool delete_remote(void *context, const struct e87_ble_peer *peer)
{
    uint8_t address[E87_BLE_ADDRESS_SIZE];
    (void)context;
    if (!peer_valid(peer)) {
        return false;
    }
    memcpy(address, peer->address, sizeof(address));
    return ble_list_delete_device(address, peer->address_type);
}

static bool clear_all(void *context)
{
    (void)context;
    return ble_list_clear_all();
}

static const struct e87_bond_ops bond_ops = {
    &target,
    journal_load,
    journal_save,
    list_config_reset,
    pair_accept,
    remote_exists,
    table_count,
    delete_remote,
    clear_all
};

static bool canonical_identity(const struct e87_ble_peer *connection,
                               struct e87_ble_peer *identity)
{
    uint8_t connection_address[E87_BLE_ADDRESS_SIZE];
    uint8_t identity_address[E87_BLE_ADDRESS_SIZE];
    bool public_exists;
    bool random_exists;

    if (!peer_valid(connection) || identity == NULL) {
        return false;
    }
    memcpy(connection_address, connection->address,
           sizeof(connection_address));
    memset(identity_address, 0, sizeof(identity_address));
    if (!ble_list_get_id_addr(connection_address, connection->address_type,
                              identity_address)) {
        /* Never promote a transient resolvable-private address as owner. */
        if (peer_is_rpa(connection)) {
            return false;
        }
        memcpy(identity_address, connection->address,
               sizeof(identity_address));
    }
    public_exists = ble_list_check_addr_is_exist(identity_address, 0u);
    random_exists = ble_list_check_addr_is_exist(identity_address, 1u);
    if (public_exists == random_exists) {
        return false;
    }
    identity->address_type = random_exists ? 1u : 0u;
    memcpy(identity->address, identity_address, sizeof(identity->address));
    return true;
}

static bool logical_owner_for_connection(
    const struct e87_ble_peer *connection,
    struct e87_ble_peer *out_identity)
{
    struct e87_ble_peer owner;
    struct e87_ble_peer identity;
    if (!e87_bond_policy_owner(&target.bond_policy, &owner) ||
        !canonical_identity(connection, &identity) ||
        !peer_equal(&identity, &owner)) {
        return false;
    }
    if (out_identity != NULL) {
        *out_identity = identity;
    }
    return true;
}

static bool current_owner_is_durable(void)
{
    struct e87_ble_peer owner;
    return target.policy_ready && target.connection_is_owner &&
           target.connection_identity_known &&
           e87_bond_policy_owner(&target.bond_policy, &owner) &&
           peer_equal(&target.connection_identity, &owner) &&
           remote_exists(NULL, &owner);
}

static enum e87_bond_advance_result advance_bond_policy(void)
{
    const enum e87_bond_phase phase =
        e87_bond_policy_phase(&target.bond_policy);
    /*
     * A policy step can publish a new durable logical owner. Invalidate
     * before the mutation so an ATT interrupt cannot observe the new owner
     * under an epoch issued for the prior owner.
     */
    if ((phase == E87_BOND_PHASE_VERIFY_PRIOR ||
         phase == E87_BOND_PHASE_SAVE_RETIRING ||
         phase == E87_BOND_PHASE_ROLLBACK_VERIFY_PRIOR ||
         phase == E87_BOND_PHASE_BOOT_VERIFY_RETIRING) &&
        !invalidate_authorization()) {
        if (target.connected) {
            require_disconnect();
        }
        return E87_BOND_ADVANCE_FAILED;
    }
    return e87_bond_policy_advance(&target.bond_policy);
}

static bool policy_safe_for_advertising(void)
{
    const enum e87_bond_phase phase =
        e87_bond_policy_phase(&target.bond_policy);
    return target.policy_ready &&
           (phase == E87_BOND_PHASE_IDLE ||
            phase == E87_BOND_PHASE_AWAIT_CANDIDATE ||
            phase == E87_BOND_PHASE_AWAIT_REBOOT);
}

static bool enable_advertising(void)
{
    if (target.advertising_enabled) {
        return true;
    }
    if (app_ble_adv_enable(target.handle, 1u) != BLE_CMD_RET_SUCESS) {
        return false;
    }
    target.advertising_enabled = true;
    return true;
}

static bool advance_candidate_to_authorizable(void)
{
    unsigned int steps;
    for (steps = 0u; steps < 3u; steps += 1u) {
        const enum e87_bond_phase phase =
            e87_bond_policy_phase(&target.bond_policy);
        enum e87_bond_advance_result result;
        if (phase == E87_BOND_PHASE_AWAIT_CANDIDATE) {
            return true;
        }
        result = advance_bond_policy();
        if (result == E87_BOND_ADVANCE_FAILED ||
            result == E87_BOND_ADVANCE_NOOP) {
            return false;
        }
    }
    return e87_bond_policy_phase(&target.bond_policy) ==
           E87_BOND_PHASE_AWAIT_CANDIDATE;
}

static bool current_link(void *handle, uint16_t connection_handle)
{
    return target.connected && handle == target.handle &&
           connection_handle == target.connection_handle &&
           app_ble_get_hdl_con_handle(handle) == connection_handle;
}

static bool authorization_gates_open(void)
{
    return target.initialized && !authorization_epoch_exhausted &&
           target.writes_enabled && target.connected &&
           !target.disconnect_required && !target.disconnect_pending &&
           target.link_encrypted && target.build_read_complete &&
           current_owner_is_durable() &&
           current_link(target.handle, target.connection_handle);
}

static uint16_t target_read_error(uint8_t error)
{
    /* Pinned BTstack encodes a dynamic-read ATT error above 0xfe00. */
    return (uint16_t)(UINT16_C(0xfe00) | (uint16_t)error);
}

static uint16_t target_read_value(const uint8_t *value,
                                  uint16_t value_length, uint16_t offset,
                                  uint8_t *buffer, uint16_t capacity,
                                  bool advances_build_gate)
{
    uint16_t copied;
    uint16_t remaining;

    if (offset > value_length) {
        return target_read_error(E87_ATT_ERROR_INVALID_OFFSET);
    }
    if (buffer == NULL) {
        return value_length;
    }
    if (capacity == 0u || offset == value_length) {
        return 0u;
    }
    remaining = (uint16_t)(value_length - offset);
    copied = capacity < remaining ? capacity : remaining;
    memcpy(buffer, &value[offset], copied);
    if (advances_build_gate && offset <= target.build_read_covered) {
        const uint16_t end = (uint16_t)(offset + copied);
        if (end > target.build_read_covered) {
            target.build_read_covered = end;
        }
        if (target.build_read_covered == value_length) {
            target.build_read_complete = true;
        }
    }
    return copied;
}

static uint16_t target_att_read(void *handle, uint16_t connection_handle,
                                uint16_t attribute_handle, uint16_t offset,
                                uint8_t *buffer, uint16_t capacity)
{
    static const uint8_t device_name[] = {'E', '8', '7'};
    uint8_t cccd[2];

    if (!current_link(handle, connection_handle)) {
        return target_read_error(E87_ATT_ERROR_UNLIKELY);
    }
    switch (attribute_handle) {
    case E87_ATT_HANDLE_DEVICE_NAME_VALUE:
        return target_read_value(device_name, (uint16_t)sizeof(device_name),
                                 offset, buffer, capacity, false);
    case E87_ATT_HANDLE_BUILD_VALUE:
        if (!target.link_encrypted) {
            return target_read_error(E87_ATT_ERROR_INSUFFICIENT_ENCRYPTION);
        }
        return target_read_value(target.build_info,
                                 (uint16_t)sizeof(target.build_info), offset,
                                 buffer, capacity, true);
    case E87_ATT_HANDLE_BATTERY_LEVEL_VALUE:
        return target_read_value(&target.battery_percent, 1u, offset, buffer,
                                 capacity, false);
    case E87_ATT_HANDLE_BATTERY_CCCD:
        cccd[0] = (uint8_t)target.battery_cccd;
        cccd[1] = (uint8_t)(target.battery_cccd >> 8u);
        return target_read_value(cccd, (uint16_t)sizeof(cccd), offset, buffer,
                                 capacity, false);
    default:
        return target_read_error(E87_ATT_ERROR_ATTRIBUTE_NOT_FOUND);
    }
}

static int target_write_cccd(uint16_t offset, const uint8_t *buffer,
                             uint16_t length)
{
    uint16_t value;
    if (offset != 0u) {
        return E87_ATT_ERROR_INVALID_OFFSET;
    }
    if (length != 2u) {
        return E87_ATT_ERROR_INVALID_ATTRIBUTE_VALUE_LENGTH;
    }
    if (buffer == NULL) {
        return E87_ATT_ERROR_CCCD_VALUE;
    }
    value = (uint16_t)buffer[0] |
            (uint16_t)((uint16_t)buffer[1] << 8u);
    if (value != 0u && value != 1u) {
        return E87_ATT_ERROR_CCCD_VALUE;
    }
    target.battery_cccd = value;
    return E87_ATT_ERROR_NONE;
}

static int target_att_write(void *handle, uint16_t connection_handle,
                            uint16_t attribute_handle,
                            uint16_t transaction_mode, uint16_t offset,
                            uint8_t *buffer, uint16_t length)
{
    uint8_t packet[E87_BLE_TARGET_STATE_PACKET_SIZE];
    struct e87_metrics validated;
    uint32_t ingress_authorization_epoch;

    if (transaction_mode != ATT_TRANSACTION_MODE_NONE) {
        return E87_ATT_ERROR_REQUEST_NOT_SUPPORTED;
    }
    if (!current_link(handle, connection_handle)) {
        return E87_ATT_ERROR_UNLIKELY;
    }
    if (attribute_handle == E87_ATT_HANDLE_BATTERY_CCCD) {
        return target_write_cccd(offset, buffer, length);
    }
    if (attribute_handle != E87_ATT_HANDLE_STATE_VALUE) {
        return E87_ATT_ERROR_ATTRIBUTE_NOT_FOUND;
    }
    if (!target.writes_enabled || target.disconnect_required ||
        target.disconnect_pending || authorization_epoch_exhausted) {
        return E87_ATT_ERROR_UNLIKELY;
    }
    if (!target.link_encrypted) {
        return E87_ATT_ERROR_INSUFFICIENT_ENCRYPTION;
    }
    if (offset != 0u) {
        return E87_ATT_ERROR_INVALID_OFFSET;
    }
    if (length != E87_BLE_TARGET_STATE_PACKET_SIZE) {
        return E87_ATT_ERROR_INVALID_ATTRIBUTE_VALUE_LENGTH;
    }
    if (!current_owner_is_durable() || !target.build_read_complete) {
        return E87_ATT_ERROR_INSUFFICIENT_AUTHORIZATION;
    }
    if (buffer == NULL) {
        return E87_ATT_ERROR_UNLIKELY;
    }

    /* Transport-only: app core owns all decoding, state, and publication. */
    memcpy(packet, buffer, sizeof(packet));
    if (e87_state_decode(packet, sizeof(packet), &validated) != E87_STATE_OK) {
        return E87_ATT_ERROR_SEMANTIC_STATE;
    }
    /* Validation output is intentionally discarded; app core decodes again. */
    (void)validated;
    ingress_authorization_epoch = authorization_epoch;
    if (!e87_ble_target_authorization_epoch_is_active(
            ingress_authorization_epoch)) {
        return E87_ATT_ERROR_UNLIKELY;
    }
    if (!target.ingress.try_enqueue_state(target.ingress.context,
                                          ingress_authorization_epoch,
                                          packet)) {
        return E87_ATT_ERROR_UNLIKELY;
    }
    return E87_ATT_ERROR_NONE;
}

static void handle_connection(void *handle, const uint8_t *packet,
                              uint16_t size)
{
    struct e87_ble_peer peer;
    struct e87_ble_peer identity;
    uint16_t connection_handle;
    bool authorization_advanced;
    bool is_owner;

    if (size < 14u || handle != target.handle ||
        hci_subevent_le_connection_complete_get_status(packet) != 0u) {
        return;
    }
    connection_handle =
        hci_subevent_le_connection_complete_get_connection_handle(packet);
    if (connection_handle == 0u ||
        connection_handle == HCI_CON_HANDLE_INVALID ||
        app_ble_get_hdl_con_handle(handle) != connection_handle) {
        return;
    }
    peer.address_type =
        hci_subevent_le_connection_complete_get_peer_address_type(packet);
    hci_subevent_le_connection_complete_get_peer_address(packet,
                                                         peer.address);
    if (!peer_valid(&peer)) {
        return;
    }
    if (target.connected) {
        /*
         * The target profile is configured for one physical LE link. If the
         * SDK ever reports a distinct second link, close the global pairing
         * gate synchronously before its SM Pairing Request can be admitted.
         */
        if (connection_handle != target.connection_handle ||
            !peer_equal(&peer, &target.connection_peer)) {
            (void)e87_bond_policy_close_pairing(&target.bond_policy);
            require_disconnect();
        }
        return;
    }
    memset(&identity, 0, sizeof(identity));
    is_owner = logical_owner_for_connection(&peer, &identity);
    authorization_advanced = invalidate_authorization();
    target.connected = true;
    target.advertising_enabled = false;
    target.connection_handle = connection_handle;
    target.connection_peer = peer;
    target.connection_is_owner = is_owner;
    target.connection_identity_known = is_owner;
    target.link_encrypted = false;
    target.build_read_complete = false;
    target.build_read_covered = 0u;
    target.battery_cccd = 0u;
    if (is_owner) {
        target.connection_identity = identity;
    } else if (e87_bond_policy_has_owner(&target.bond_policy) &&
               peer_is_rpa(&peer)) {
        /* Wait fail-closed for the authoritative SM identity event. */
        target.owner_resolution_pending = true;
    } else if (e87_bond_policy_pairing_open(&target.bond_policy)) {
        /* Staging is RAM-only; journal and vendor-gate work runs in poll. */
        if (!e87_bond_policy_stage_candidate(&target.bond_policy, &peer)) {
            require_disconnect();
        }
    } else {
        require_disconnect();
    }
    if (!authorization_advanced) {
        require_disconnect();
    }
}

static void handle_encryption(void *handle, const uint8_t *packet,
                              uint16_t size)
{
    uint16_t connection_handle;
    bool encrypted;
    bool was_encrypted;
    if (size < 6u || handle != target.handle || !target.connected) {
        return;
    }
    connection_handle =
        hci_event_encryption_change_get_connection_handle(packet);
    if (connection_handle != target.connection_handle ||
        app_ble_get_hdl_con_handle(handle) != connection_handle) {
        return;
    }
    was_encrypted = target.link_encrypted;
    encrypted = hci_event_encryption_change_get_status(packet) == 0u &&
        hci_event_encryption_change_get_encryption_enabled(packet) != 0u;
    target.link_encrypted = encrypted;
    if (!encrypted) {
        target.build_read_complete = false;
        target.build_read_covered = 0u;
        if (was_encrypted) {
            (void)invalidate_authorization();
        }
    }
    if (!target.connection_is_owner) {
        if (target.encryption_pending &&
            target.encryption_success != encrypted) {
            target.candidate_abort_pending = true;
            require_disconnect();
        } else {
            target.encryption_pending = true;
            target.encryption_success = encrypted;
        }
    }
}

static void handle_disconnection(void *handle, const uint8_t *packet,
                                 uint16_t size)
{
    uint16_t connection_handle;
    bool abort_candidate;
    if (size < 6u || handle != target.handle || !target.connected) {
        return;
    }
    connection_handle =
        hci_event_disconnection_complete_get_connection_handle(packet);
    if (connection_handle != target.connection_handle) {
        return;
    }
    (void)invalidate_authorization();
    abort_candidate = !target.connection_is_owner &&
        e87_bond_policy_pairing_open(&target.bond_policy);
    if (abort_candidate) {
        target.candidate_abort_pending = true;
    }
    target.connected = false;
    target.connection_handle = 0u;
    target.connection_is_owner = false;
    target.connection_identity_known = false;
    target.owner_resolution_pending = false;
    target.identity_pending = false;
    target.link_encrypted = false;
    target.build_read_complete = false;
    target.build_read_covered = 0u;
    target.battery_cccd = 0u;
    target.disconnect_required = false;
    target.disconnect_pending = false;
    memset(&target.connection_peer, 0, sizeof(target.connection_peer));
    memset(&target.connection_identity, 0,
           sizeof(target.connection_identity));
}

static void target_hci_event(void *handle, uint8_t packet_type,
                             uint16_t channel, uint8_t *packet, uint16_t size)
{
    uint8_t event_type;
    (void)channel;
    if (packet_type != HCI_EVENT_PACKET || packet == NULL || size < 2u) {
        return;
    }
    event_type = hci_event_packet_get_type(packet);
    if (event_type == HCI_EVENT_LE_META && size >= 3u &&
        hci_event_le_meta_get_subevent_code(packet) ==
            HCI_SUBEVENT_LE_CONNECTION_COMPLETE) {
        handle_connection(handle, packet, size);
    } else if (event_type == HCI_EVENT_ENCRYPTION_CHANGE) {
        handle_encryption(handle, packet, size);
    } else if (event_type == HCI_EVENT_DISCONNECTION_COMPLETE) {
        handle_disconnection(handle, packet, size);
    }
}

static void target_sm_event(void *handle, uint8_t packet_type,
                            uint16_t channel, uint8_t *packet, uint16_t size)
{
    const uint8_t event_type =
        packet != NULL && size > 0u ? hci_event_packet_get_type(packet) : 0u;
    (void)channel;
    if (packet_type != HCI_EVENT_PACKET || handle != target.handle ||
        !target.connected || packet == NULL) {
        return;
    }
    if (event_type == SM_EVENT_JUST_WORKS_REQUEST && size >= 11u) {
        struct e87_ble_peer peer;
        const uint16_t connection_handle =
            sm_event_just_works_request_get_handle(packet);
        peer.address_type =
            sm_event_just_works_request_get_addr_type(packet);
        sm_event_just_works_request_get_address(packet, peer.address);
        /*
         * app_ble has already called sm_just_works_confirm before invoking
         * this callback. This notification can only detect an invariant
         * violation; admission itself is controlled by pair_accept.
         */
        if (connection_handle != target.connection_handle ||
            target.disconnect_required || target.disconnect_pending ||
            !peer_equal(&peer, &target.connection_peer) ||
            !e87_bond_policy_allow_just_works(&target.bond_policy, &peer)) {
            (void)e87_bond_policy_close_pairing(&target.bond_policy);
            require_disconnect();
        }
        return;
    }
    if ((event_type == SM_EVENT_IDENTITY_RESOLVING_SUCCEEDED ||
         event_type == SM_EVENT_IDENTITY_CREATED) && size >= 18u) {
        struct e87_ble_peer connection;
        struct e87_ble_peer identity;
        if (event_type == SM_EVENT_IDENTITY_RESOLVING_SUCCEEDED) {
            connection.address_type =
                sm_event_identity_resolving_succeeded_get_addr_type(packet);
            sm_event_identity_resolving_succeeded_get_address(
                packet, connection.address);
            identity.address_type =
                sm_event_identity_resolving_succeeded_get_identity_addr_type(
                    packet);
            sm_event_identity_resolving_succeeded_get_identity_address(
                packet, identity.address);
        } else {
            connection.address_type =
                sm_event_identity_created_get_addr_type(packet);
            sm_event_identity_created_get_address(packet,
                                                  connection.address);
            identity.address_type =
                sm_event_identity_created_get_identity_addr_type(packet);
            sm_event_identity_created_get_identity_address(packet,
                                                           identity.address);
        }
        if (!peer_valid(&connection) || !peer_valid(&identity) ||
            !peer_equal(&connection, &target.connection_peer) ||
            (target.identity_pending &&
             !peer_equal(&identity, &target.pending_identity))) {
            target.candidate_abort_pending = true;
            require_disconnect();
        } else {
            target.pending_identity = identity;
            target.identity_pending = true;
        }
        return;
    }
    if (event_type == SM_EVENT_IDENTITY_RESOLVING_FAILED &&
        target.owner_resolution_pending) {
        target.owner_resolution_pending = false;
        require_disconnect();
        return;
    }
    if (event_type == SM_EVENT_PAIR_PROCESS && size >= 16u &&
        ((uint16_t)packet[2] | (uint16_t)((uint16_t)packet[3] << 8u)) ==
            target.connection_handle) {
        const uint8_t subevent = packet[11];
        if (subevent == SM_EVENT_PAIR_SUB_ADD_LIST_SUCCESS ||
            subevent == SM_EVENT_PAIR_SUB_ADD_LIST_FAILED) {
            const bool success =
                subevent == SM_EVENT_PAIR_SUB_ADD_LIST_SUCCESS;
            if (target.pair_result_pending &&
                target.pair_result_success != success) {
                target.candidate_abort_pending = true;
                require_disconnect();
            } else {
                target.pair_result_pending = true;
                target.pair_result_success = success;
            }
        }
    }
}

static bool release_failed_profile(void)
{
    const uint16_t connection_handle =
        target.handle == NULL ? 0u
                              : app_ble_get_hdl_con_handle(target.handle);
    if (target.handle == NULL) {
        target.cleanup_pending = false;
        return true;
    }
    if (!target.release_epoch_invalidated) {
        target.writes_enabled = false;
        if (!invalidate_authorization()) {
            return false;
        }
        target.release_epoch_invalidated = true;
    }
    if (connection_handle != 0u &&
        connection_handle != HCI_CON_HANDLE_INVALID) {
        return false;
    }
    if (app_ble_adv_enable(target.handle, 0u) != BLE_CMD_RET_SUCESS ||
        app_ble_hdl_free(target.handle) != BLE_CMD_RET_SUCESS) {
        target.cleanup_pending = true;
        return false;
    }
    memset(&target, 0, sizeof(target));
    return true;
}

static bool profile_setup(void)
{
    target.handle = app_ble_hdl_alloc();
    if (target.handle == NULL ||
        app_ble_profile_set(target.handle, e87_normal_gatt_profile) !=
            BLE_CMD_RET_SUCESS ||
        app_ble_att_read_callback_register(target.handle, target_att_read) !=
            BLE_CMD_RET_SUCESS ||
        app_ble_att_write_callback_register(target.handle, target_att_write) !=
            BLE_CMD_RET_SUCESS ||
        app_ble_hci_event_callback_register(target.handle, target_hci_event) !=
            BLE_CMD_RET_SUCESS ||
        app_ble_sm_event_callback_register(target.handle, target_sm_event) !=
            BLE_CMD_RET_SUCESS ||
        app_ble_set_adv_param(target.handle, E87_BLE_ADV_INTERVAL_UNITS,
                              APP_ADV_IND, APP_ADV_CHANNEL_ALL) !=
            BLE_CMD_RET_SUCESS ||
        app_ble_adv_data_set(target.handle,
                             (uint8_t *)e87_normal_advertising_data,
                             (uint8_t)E87_NORMAL_ADVERTISING_DATA_SIZE) !=
            BLE_CMD_RET_SUCESS) {
        target.cleanup_pending = target.handle != NULL;
        (void)release_failed_profile();
        return false;
    }
    return true;
}

bool e87_ble_target_init(const struct e87_ble_target_ingress *ingress)
{
    if (ingress == NULL || ingress->try_enqueue_state == NULL) {
        return false;
    }
    if (target.initialized) {
        return target.ingress.context == ingress->context &&
               target.ingress.try_enqueue_state == ingress->try_enqueue_state;
    }
    if (target.cleanup_pending && !release_failed_profile()) {
        return false;
    }
    memset(&target, 0, sizeof(target));
    target.ingress = *ingress;
    if (!invalidate_authorization()) {
        return false;
    }
    if (!e87_build_info_encode(&build_identity, target.build_info,
                               sizeof(target.build_info))) {
        return false;
    }
    le_device_db_init();
    if (app_ble_sm_init(IO_CAPABILITY_NO_INPUT_NO_OUTPUT,
                        SM_AUTHREQ_BONDING | SM_AUTHREQ_SECURE_CONNECTION,
                        16u, 0u) != BLE_CMD_RET_SUCESS ||
        app_ble_init() != BLE_CMD_RET_SUCESS ||
        ble_op_multi_att_send_init(att_ram, sizeof(att_ram),
                                   E87_BLE_ATT_PAYLOAD_SIZE) !=
            BLE_CMD_RET_SUCESS ||
        !profile_setup()) {
        return false;
    }
    target.initialized = true;
    target.policy_ready =
        e87_bond_policy_boot(&target.bond_policy, &bond_ops);
    if (target.policy_ready) {
        (void)e87_ble_target_poll();
    }
    return true;
}

bool e87_ble_target_set_writes_enabled(
    bool enabled, uint32_t *out_authorization_epoch)
{
    if (!target.initialized || out_authorization_epoch == NULL ||
        authorization_epoch_exhausted) {
        return false;
    }
    if (enabled && target.writes_enabled) {
        *out_authorization_epoch = authorization_epoch;
        return true;
    }
    if (!enabled) {
        target.writes_enabled = false;
        if (!invalidate_authorization()) {
            *out_authorization_epoch = authorization_epoch;
            return false;
        }
    } else {
        if (!invalidate_authorization()) {
            *out_authorization_epoch = authorization_epoch;
            return false;
        }
        target.writes_enabled = true;
    }
    *out_authorization_epoch = authorization_epoch;
    return true;
}

bool e87_ble_target_authorization_epoch_is_active(
    uint32_t candidate_authorization_epoch)
{
    if (candidate_authorization_epoch == 0u ||
        candidate_authorization_epoch != authorization_epoch) {
        return false;
    }
    /* Re-read the epoch after all mutable gates (seqlock-style). */
    if (authorization_gates_open() &&
        candidate_authorization_epoch == authorization_epoch) {
        target.authorization_was_active = true;
        return true;
    }
    if (target.authorization_was_active) {
        (void)invalidate_authorization();
    }
    return false;
}

static bool ensure_policy_ready(void)
{
    if (target.policy_ready) {
        return true;
    }
    target.policy_ready =
        e87_bond_policy_boot(&target.bond_policy, &bond_ops);
    return target.policy_ready;
}

static bool progress_policy(void)
{
    const enum e87_bond_phase phase =
        e87_bond_policy_phase(&target.bond_policy);
    enum e87_bond_advance_result result;
    if (phase == E87_BOND_PHASE_SAVE_REPLACING ||
        phase == E87_BOND_PHASE_VERIFY_PRIOR) {
        if (advance_candidate_to_authorizable()) {
            return true;
        }
        target.candidate_abort_pending = true;
        if (target.connected) {
            require_disconnect();
        }
        return false;
    }
    if (phase == E87_BOND_PHASE_IDLE ||
        phase == E87_BOND_PHASE_AWAIT_CANDIDATE ||
        phase == E87_BOND_PHASE_AWAIT_REBOOT) {
        return true;
    }
    result = advance_bond_policy();
    return result != E87_BOND_ADVANCE_FAILED;
}

static bool process_pending_bond_events(void)
{
    if (target.owner_resolution_pending && target.identity_pending) {
        struct e87_ble_peer owner;
        const bool resolved_owner =
            e87_bond_policy_owner(&target.bond_policy, &owner) &&
            peer_equal(&owner, &target.pending_identity);
        target.owner_resolution_pending = false;
        target.identity_pending = false;
        if (!resolved_owner) {
            require_disconnect();
            return false;
        }
        if (!invalidate_authorization()) {
            require_disconnect();
            return false;
        }
        target.connection_identity = owner;
        target.connection_identity_known = true;
        target.connection_is_owner = true;
        target.encryption_pending = false;
    }
    if (target.candidate_abort_pending) {
        if (!e87_bond_policy_close_pairing(&target.bond_policy)) {
            return false;
        }
        target.candidate_abort_pending = false;
        target.pair_result_pending = false;
        target.encryption_pending = false;
        target.identity_pending = false;
    }
    if (target.pair_result_pending) {
        const bool success = target.pair_result_success;
        target.pair_result_pending = false;
        if (success) {
            struct e87_ble_peer identity;
            const bool identity_known = target.identity_pending
                ? (identity = target.pending_identity, true)
                : canonical_identity(&target.connection_peer, &identity);
            target.identity_pending = false;
            if (identity_known &&
                e87_bond_policy_on_identity(&target.bond_policy,
                                             &target.connection_peer,
                                             &identity)) {
                target.connection_identity = identity;
                target.connection_identity_known = true;
                e87_bond_policy_on_pair_added(&target.bond_policy,
                                              &target.connection_peer, true);
            } else {
                e87_bond_policy_on_pair_added(&target.bond_policy,
                                              &target.connection_peer, false);
                require_disconnect();
            }
        } else {
            e87_bond_policy_on_pair_added(&target.bond_policy,
                                          &target.connection_peer, false);
            require_disconnect();
        }
    }
    if (target.encryption_pending) {
        const bool success = target.encryption_success;
        target.encryption_pending = false;
        e87_bond_policy_on_encryption(&target.bond_policy,
                                      &target.connection_peer, success);
        if (!success) {
            require_disconnect();
        }
    }
    return true;
}

static void update_disconnect_requirement(void)
{
    struct e87_ble_peer owner;
    const enum e87_bond_phase phase =
        e87_bond_policy_phase(&target.bond_policy);
    if (!target.connected || target.connection_is_owner ||
        target.owner_resolution_pending) {
        return;
    }
    if (target.connection_identity_known &&
        e87_bond_policy_owner(&target.bond_policy, &owner) &&
        peer_equal(&owner, &target.connection_identity)) {
        require_disconnect();
    } else if (phase == E87_BOND_PHASE_IDLE &&
               !e87_bond_policy_pairing_open(&target.bond_policy)) {
        require_disconnect();
    }
}

bool e87_ble_target_poll(void)
{
    if (!target.initialized || !ensure_policy_ready()) {
        return false;
    }
    /*
     * Once a link is marked for teardown, never advance VERIFY_PRIOR into
     * the global pair-gate enable. Drain the link first; policy rollback can
     * resume after its disconnection event.
     */
    if (target.connected && target.disconnect_required) {
        if (target.disconnect_pending) {
            return true;
        }
        if (app_ble_get_hdl_con_handle(target.handle) !=
                target.connection_handle ||
            app_ble_disconnect(target.handle) != BLE_CMD_RET_SUCESS) {
            return false;
        }
        target.disconnect_pending = true;
        return true;
    }
    if (!process_pending_bond_events()) {
        return false;
    }
    if (!progress_policy()) {
        return false;
    }
    if (e87_bond_policy_phase(&target.bond_policy) == E87_BOND_PHASE_IDLE &&
        !e87_bond_policy_has_owner(&target.bond_policy) &&
        !e87_bond_policy_pairing_open(&target.bond_policy) &&
        !e87_bond_policy_open_pairing(&target.bond_policy)) {
        return false;
    }
    update_disconnect_requirement();
    if (target.connected && target.disconnect_required) {
        if (target.disconnect_pending) {
            return true;
        }
        if (app_ble_get_hdl_con_handle(target.handle) !=
                target.connection_handle ||
            app_ble_disconnect(target.handle) != BLE_CMD_RET_SUCESS) {
            return false;
        }
        target.disconnect_pending = true;
        return true;
    }
    if (!target.connected && policy_safe_for_advertising()) {
        return enable_advertising();
    }
    return true;
}
