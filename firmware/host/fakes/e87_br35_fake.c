#include "e87_br35_fake.h"
#include "e87_br35_sdk.h"

#include <stdarg.h>
#include <string.h>

struct e87_fake_br35_state e87_fake_br35;

static app_ble_att_read_callback_t read_callback;
static app_ble_att_write_callback_t write_callback;
static app_ble_packet_handler_t hci_callback;
static app_ble_sm_event_callback_t sm_callback;
static uint8_t handle_storage;

static bool try_enqueue_state(
    void *context,
    uint32_t authorization_epoch,
    const uint8_t packet[E87_BLE_TARGET_STATE_PACKET_SIZE])
{
    struct e87_fake_br35_state *state = context;
    state->state_enqueue_calls += 1u;
    state->state_authorization_epoch = authorization_epoch;
    memcpy(state->state_packet, packet, sizeof(state->state_packet));
    return state->state_enqueue_accept;
}

static const struct e87_ble_target_ingress target_ingress = {
    &e87_fake_br35, try_enqueue_state
};

static bool record(enum e87_fake_br35_operation operation)
{
    if (e87_fake_br35.operation_count < E87_FAKE_OPERATION_CAPACITY) {
        e87_fake_br35.operations[e87_fake_br35.operation_count] = operation;
        e87_fake_br35.operation_count += 1u;
    }
    if (e87_fake_br35.fail_operation == operation &&
        e87_fake_br35.fail_count > 0) {
        e87_fake_br35.fail_count -= 1;
        return false;
    }
    return true;
}

static bool peer_equal(const struct e87_ble_peer *left,
                       const struct e87_ble_peer *right)
{
    return left->address_type == right->address_type &&
           memcmp(left->address, right->address,
                  E87_BLE_ADDRESS_SIZE) == 0;
}

void e87_fake_br35_reset(void)
{
    memset(&e87_fake_br35, 0, sizeof(e87_fake_br35));
    read_callback = NULL;
    write_callback = NULL;
    hci_callback = NULL;
    sm_callback = NULL;
    e87_fake_br35.allocated_handle = &handle_storage;
    e87_fake_br35.state_enqueue_accept = true;
}

const struct e87_ble_target_ingress *e87_fake_br35_ingress(void)
{
    return &target_ingress;
}

void e87_fake_br35_set_bond(unsigned int index,
                            const struct e87_ble_peer *peer)
{
    if (index >= 2u || peer == NULL) {
        return;
    }
    e87_fake_br35.bonds[index] = *peer;
    if (e87_fake_br35.bond_count <= index) {
        e87_fake_br35.bond_count = (uint16_t)(index + 1u);
    }
}

void e87_fake_br35_set_identity_mapping(
    const struct e87_ble_peer *connection,
    const struct e87_ble_peer *identity)
{
    e87_fake_br35.mapped_connection = *connection;
    e87_fake_br35.mapped_identity = *identity;
    e87_fake_br35.mapping_present = true;
}

static void reverse_address(uint8_t *destination,
                            const struct e87_ble_peer *peer)
{
    unsigned int index;
    for (index = 0u; index < E87_BLE_ADDRESS_SIZE; index += 1u) {
        destination[index] = peer->address[E87_BLE_ADDRESS_SIZE - 1u - index];
    }
}

void e87_fake_br35_emit_connection(const struct e87_ble_peer *peer,
                                   uint16_t connection_handle)
{
    uint8_t packet[20] = {0};
    e87_fake_br35.connection_handle = connection_handle;
    e87_fake_br35.connection_peer = *peer;
    e87_fake_br35.connection_peer_valid = true;
    e87_fake_br35.advertising_enabled = false;
    packet[0] = HCI_EVENT_LE_META;
    packet[1] = 18u;
    packet[2] = HCI_SUBEVENT_LE_CONNECTION_COMPLETE;
    packet[3] = 0u;
    packet[4] = (uint8_t)connection_handle;
    packet[5] = (uint8_t)(connection_handle >> 8u);
    packet[7] = peer->address_type;
    reverse_address(&packet[8], peer);
    if (hci_callback != NULL) {
        hci_callback(e87_fake_br35.allocated_handle, HCI_EVENT_PACKET, 0u,
                     packet, (uint16_t)sizeof(packet));
    }
}

void e87_fake_br35_emit_encryption(uint8_t status, uint8_t enabled)
{
    uint8_t packet[6] = {HCI_EVENT_ENCRYPTION_CHANGE, 4u, 0u, 0u, 0u, 0u};
    packet[2] = status;
    packet[3] = (uint8_t)e87_fake_br35.connection_handle;
    packet[4] = (uint8_t)(e87_fake_br35.connection_handle >> 8u);
    packet[5] = enabled;
    if (hci_callback != NULL) {
        hci_callback(e87_fake_br35.allocated_handle, HCI_EVENT_PACKET, 0u,
                     packet, (uint16_t)sizeof(packet));
    }
}

void e87_fake_br35_emit_pair_process_sized(uint8_t subevent, uint16_t size)
{
    uint8_t packet[16] = {0};
    if (size > (uint16_t)sizeof(packet)) {
        size = (uint16_t)sizeof(packet);
    }
    packet[0] = SM_EVENT_PAIR_PROCESS;
    packet[1] = 14u;
    packet[2] = (uint8_t)e87_fake_br35.connection_handle;
    packet[3] = (uint8_t)(e87_fake_br35.connection_handle >> 8u);
    packet[11] = subevent;
    if (sm_callback != NULL) {
        sm_callback(e87_fake_br35.allocated_handle, HCI_EVENT_PACKET, 0u,
                    packet, size);
    }
}

void e87_fake_br35_emit_pair_process(uint8_t subevent)
{
    e87_fake_br35_emit_pair_process_sized(
        subevent, UINT16_C(16));
}

void e87_fake_br35_emit_just_works(const struct e87_ble_peer *peer)
{
    uint8_t packet[11] = {0};
    /*
     * The pinned app_ble dispatcher confirms JustWorks before it notifies
     * the per-handle callback. The SM emits this event only after the global
     * pair gate admitted the Pairing Request for the current physical link.
     */
    if (!e87_fake_br35.pair_accept ||
        !e87_fake_br35.connection_peer_valid ||
        !peer_equal(peer, &e87_fake_br35.connection_peer)) {
        return;
    }
    packet[0] = SM_EVENT_JUST_WORKS_REQUEST;
    packet[1] = 9u;
    packet[2] = (uint8_t)e87_fake_br35.connection_handle;
    packet[3] = (uint8_t)(e87_fake_br35.connection_handle >> 8u);
    packet[4] = peer->address_type;
    reverse_address(&packet[5], peer);
    sm_just_works_confirm(e87_fake_br35.connection_handle);
    if (sm_callback != NULL) {
        sm_callback(e87_fake_br35.allocated_handle, HCI_EVENT_PACKET, 0u,
                    packet, (uint16_t)sizeof(packet));
    }
}

void e87_fake_br35_emit_identity_resolved(
    const struct e87_ble_peer *connection,
    const struct e87_ble_peer *identity)
{
    uint8_t packet[19] = {0};
    packet[0] = SM_EVENT_IDENTITY_RESOLVING_SUCCEEDED;
    packet[1] = 17u;
    packet[4] = connection->address_type;
    reverse_address(&packet[5], connection);
    packet[11] = identity->address_type;
    reverse_address(&packet[12], identity);
    if (sm_callback != NULL) {
        sm_callback(e87_fake_br35.allocated_handle, HCI_EVENT_PACKET, 0u,
                    packet, (uint16_t)sizeof(packet));
    }
}

void e87_fake_br35_emit_disconnection(uint8_t status, uint8_t reason)
{
    uint8_t packet[6] = {HCI_EVENT_DISCONNECTION_COMPLETE, 4u, 0u, 0u, 0u, 0u};
    packet[2] = status;
    packet[3] = (uint8_t)e87_fake_br35.connection_handle;
    packet[4] = (uint8_t)(e87_fake_br35.connection_handle >> 8u);
    packet[5] = reason;
    if (hci_callback != NULL) {
        hci_callback(e87_fake_br35.allocated_handle, HCI_EVENT_PACKET, 0u,
                     packet, (uint16_t)sizeof(packet));
    }
    e87_fake_br35.connection_handle = 0u;
    memset(&e87_fake_br35.connection_peer, 0,
           sizeof(e87_fake_br35.connection_peer));
    e87_fake_br35.connection_peer_valid = false;
}

uint16_t e87_fake_br35_att_read(uint16_t connection_handle,
                                uint16_t attribute_handle,
                                uint16_t offset,
                                uint8_t *buffer,
                                uint16_t capacity)
{
    return read_callback == NULL
               ? 0u
               : read_callback(e87_fake_br35.allocated_handle,
                               connection_handle, attribute_handle, offset,
                               buffer, capacity);
}

int e87_fake_br35_att_write(uint16_t connection_handle,
                            uint16_t attribute_handle,
                            uint16_t transaction_mode,
                            uint16_t offset,
                            uint8_t *buffer,
                            uint16_t length)
{
    return write_callback == NULL
               ? -1
               : write_callback(e87_fake_br35.allocated_handle,
                                connection_handle, attribute_handle,
                                transaction_mode, offset, buffer, length);
}

void le_device_db_init(void)
{
    (void)record(E87_FAKE_OP_DEVICE_DB_INIT);
}

int app_ble_sm_init(io_capability_t io_type, u8 auth_req,
                    uint8_t min_key_size, u8 security_en)
{
    (void)io_type;
    (void)auth_req;
    (void)min_key_size;
    (void)security_en;
    return record(E87_FAKE_OP_SM_INIT) ? BLE_CMD_RET_SUCESS : BLE_CMD_OPT_FAIL;
}

int app_ble_init(void)
{
    return record(E87_FAKE_OP_APP_BLE_INIT) ? BLE_CMD_RET_SUCESS
                                            : BLE_CMD_OPT_FAIL;
}

ble_cmd_ret_e ble_user_cmd_prepare(int command, int argc, ...)
{
    va_list arguments;
    (void)command;
    (void)argc;
    va_start(arguments, argc);
    va_end(arguments);
    return record(E87_FAKE_OP_ATT_SEND_INIT) ? BLE_CMD_RET_SUCESS
                                             : BLE_CMD_OPT_FAIL;
}

void *app_ble_hdl_alloc(void)
{
    return record(E87_FAKE_OP_HANDLE_ALLOC) ? e87_fake_br35.allocated_handle
                                             : NULL;
}

int app_ble_hdl_free(void *handle)
{
    (void)handle;
    e87_fake_br35.free_calls += 1u;
    return record(E87_FAKE_OP_HANDLE_FREE) ? BLE_CMD_RET_SUCESS
                                           : BLE_CMD_OPT_FAIL;
}

int app_ble_profile_set(void *handle, const uint8_t *database)
{
    (void)handle;
    e87_fake_br35.profile = database;
    return record(E87_FAKE_OP_PROFILE_SET) ? BLE_CMD_RET_SUCESS
                                           : BLE_CMD_OPT_FAIL;
}

int app_ble_att_read_callback_register(void *handle,
                                       app_ble_att_read_callback_t callback)
{
    (void)handle;
    read_callback = callback;
    return record(E87_FAKE_OP_READ_REGISTER) ? BLE_CMD_RET_SUCESS
                                             : BLE_CMD_OPT_FAIL;
}

int app_ble_att_write_callback_register(void *handle,
                                        app_ble_att_write_callback_t callback)
{
    (void)handle;
    write_callback = callback;
    return record(E87_FAKE_OP_WRITE_REGISTER) ? BLE_CMD_RET_SUCESS
                                              : BLE_CMD_OPT_FAIL;
}

int app_ble_hci_event_callback_register(void *handle,
                                        app_ble_packet_handler_t callback)
{
    (void)handle;
    hci_callback = callback;
    return record(E87_FAKE_OP_HCI_REGISTER) ? BLE_CMD_RET_SUCESS
                                            : BLE_CMD_OPT_FAIL;
}

int app_ble_sm_event_callback_register(void *handle,
                                       app_ble_sm_event_callback_t callback)
{
    (void)handle;
    sm_callback = callback;
    return record(E87_FAKE_OP_SM_REGISTER) ? BLE_CMD_RET_SUCESS
                                           : BLE_CMD_OPT_FAIL;
}

int app_ble_set_adv_param(void *handle, u32 interval, u8 type, u8 channels)
{
    (void)handle;
    e87_fake_br35.advertising_interval = interval;
    e87_fake_br35.advertising_type = type;
    e87_fake_br35.advertising_channels = channels;
    return record(E87_FAKE_OP_ADV_PARAM) ? BLE_CMD_RET_SUCESS
                                         : BLE_CMD_OPT_FAIL;
}

int app_ble_adv_data_set(void *handle, u8 *data, u8 length)
{
    (void)handle;
    e87_fake_br35.advertising_data = data;
    e87_fake_br35.advertising_length = length;
    return record(E87_FAKE_OP_ADV_DATA) ? BLE_CMD_RET_SUCESS
                                        : BLE_CMD_OPT_FAIL;
}

int app_ble_adv_enable(void *handle, u8 enabled)
{
    enum e87_fake_br35_operation operation = enabled != 0u
        ? E87_FAKE_OP_ADV_ENABLE : E87_FAKE_OP_ADV_DISABLE;
    (void)handle;
    if (!record(operation)) {
        return BLE_CMD_OPT_FAIL;
    }
    e87_fake_br35.advertising_enabled = enabled != 0u;
    return BLE_CMD_RET_SUCESS;
}

int app_ble_disconnect(void *handle)
{
    (void)handle;
    e87_fake_br35.disconnect_calls += 1u;
    return record(E87_FAKE_OP_DISCONNECT) ? BLE_CMD_RET_SUCESS
                                          : BLE_CMD_OPT_FAIL;
}

u16 app_ble_get_hdl_con_handle(void *handle)
{
    (void)handle;
    return e87_fake_br35.connection_handle;
}

ble_cmd_ret_e app_ble_att_send_data(void *handle, u16 att_handle, u8 *data,
                                    u16 length, att_op_type_e operation)
{
    (void)handle;
    (void)att_handle;
    (void)data;
    (void)length;
    (void)operation;
    return BLE_CMD_RET_SUCESS;
}

void ble_list_config_reset(u8 slots, u8 allow_cover)
{
    e87_fake_br35.configured_slots = slots;
    e87_fake_br35.configured_allow_cover = allow_cover != 0u;
}

bool ble_list_pair_accept(u8 enabled)
{
    enum e87_fake_br35_operation operation = enabled != 0u
        ? E87_FAKE_OP_PAIR_ACCEPT_ENABLE
        : E87_FAKE_OP_PAIR_ACCEPT_DISABLE;
    if (!record(operation)) {
        return false;
    }
    e87_fake_br35.pair_accept = enabled != 0u;
    return true;
}

u16 ble_list_get_count(void)
{
    return e87_fake_br35.bond_count;
}

bool ble_list_clear_all(void)
{
    memset(e87_fake_br35.bonds, 0, sizeof(e87_fake_br35.bonds));
    e87_fake_br35.bond_count = 0u;
    return true;
}

bool ble_list_check_addr_is_exist(u8 *address, u8 address_type)
{
    struct e87_ble_peer peer;
    unsigned int index;
    e87_fake_br35.bond_exists_calls += 1u;
    if (e87_fake_br35.close_writes_on_bond_exists_call != 0u &&
        e87_fake_br35.bond_exists_calls ==
            e87_fake_br35.close_writes_on_bond_exists_call &&
        e87_fake_br35.close_writes != NULL) {
        e87_fake_br35.close_writes_on_bond_exists_call = 0u;
        e87_fake_br35.close_writes_result =
            e87_fake_br35.close_writes(
                &e87_fake_br35.close_writes_epoch);
    }
    peer.address_type = address_type;
    memcpy(peer.address, address, sizeof(peer.address));
    for (index = 0u; index < e87_fake_br35.bond_count; index += 1u) {
        if (peer_equal(&peer, &e87_fake_br35.bonds[index])) {
            return true;
        }
    }
    if (e87_fake_br35.mapping_present &&
        peer_equal(&peer, &e87_fake_br35.mapped_connection)) {
        for (index = 0u; index < e87_fake_br35.bond_count; index += 1u) {
            if (peer_equal(&e87_fake_br35.mapped_identity,
                           &e87_fake_br35.bonds[index])) {
                return true;
            }
        }
    }
    return false;
}

bool ble_list_delete_device(u8 *address, u8 address_type)
{
    unsigned int index;
    struct e87_ble_peer peer;
    peer.address_type = address_type;
    memcpy(peer.address, address, sizeof(peer.address));
    for (index = 0u; index < e87_fake_br35.bond_count; index += 1u) {
        if (peer_equal(&peer, &e87_fake_br35.bonds[index])) {
            if (index + 1u < e87_fake_br35.bond_count) {
                e87_fake_br35.bonds[index] = e87_fake_br35.bonds[index + 1u];
            }
            e87_fake_br35.bond_count -= 1u;
            return true;
        }
    }
    return false;
}

bool ble_list_get_id_addr(u8 *connection_address, u8 connection_address_type,
                          u8 *identity_address)
{
    struct e87_ble_peer connection;
    connection.address_type = connection_address_type;
    memcpy(connection.address, connection_address, sizeof(connection.address));
    if (!e87_fake_br35.mapping_present ||
        !peer_equal(&connection, &e87_fake_br35.mapped_connection)) {
        return false;
    }
    memcpy(identity_address, e87_fake_br35.mapped_identity.address,
           E87_BLE_ADDRESS_SIZE);
    return true;
}

void sm_just_works_confirm(hci_con_handle_t connection_handle)
{
    e87_fake_br35.just_works_confirms += 1u;
    e87_fake_br35.just_works_handle = connection_handle;
    (void)record(E87_FAKE_OP_JUST_WORKS_CONFIRM);
}

static uint8_t *syscfg_slot(u16 item_id, uint16_t **stored_length)
{
    if (item_id == 48u) {
        *stored_length = &e87_fake_br35.syscfg_48_length;
        return e87_fake_br35.syscfg_48;
    }
    if (item_id == 49u) {
        *stored_length = &e87_fake_br35.syscfg_49_length;
        return e87_fake_br35.syscfg_49;
    }
    *stored_length = NULL;
    return NULL;
}

int syscfg_read(u16 item_id, void *buffer, u16 length)
{
    uint16_t *stored_length;
    uint8_t *slot = syscfg_slot(item_id, &stored_length);
    uint16_t copied;
    e87_fake_br35.last_syscfg_read_id = item_id;
    e87_fake_br35.last_syscfg_read_length = length;
    (void)record(E87_FAKE_OP_SYSCFG_READ);
    if (slot == NULL || stored_length == NULL || *stored_length == 0u) {
        return -1;
    }
    copied = *stored_length < length ? *stored_length : length;
    if (e87_fake_br35.short_next_read && copied > 0u) {
        e87_fake_br35.short_next_read = false;
        copied -= 1u;
    }
    memcpy(buffer, slot, copied);
    return (int)copied;
}

int syscfg_write(u16 item_id, const void *buffer, u16 length)
{
    uint16_t *stored_length;
    uint8_t *slot = syscfg_slot(item_id, &stored_length);
    uint16_t copied = length;
    e87_fake_br35.last_syscfg_write_id = item_id;
    e87_fake_br35.last_syscfg_write_length = length;
    (void)record(E87_FAKE_OP_SYSCFG_WRITE);
    if (slot == NULL || stored_length == NULL ||
        length > E87_FAKE_SYSCFG_CAPACITY) {
        return -1;
    }
    if (e87_fake_br35.short_next_write && copied > 0u) {
        e87_fake_br35.short_next_write = false;
        copied -= 1u;
    }
    memcpy(slot, buffer, copied);
    *stored_length = copied;
    return (int)copied;
}

int cpu_irq_disabled(void)
{
    return e87_fake_br35.irq_disabled;
}

void local_irq_disable(void)
{
    e87_fake_br35.irq_disabled = 1;
}

void local_irq_enable(void)
{
    e87_fake_br35.irq_disabled = 0;
}
