#ifndef E87_BR35_FAKE_H
#define E87_BR35_FAKE_H

#include "e87/e87_bond_policy.h"
#include "e87/e87_ble_target.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

enum e87_fake_br35_operation {
    E87_FAKE_OP_DEVICE_DB_INIT = 1,
    E87_FAKE_OP_SM_INIT,
    E87_FAKE_OP_APP_BLE_INIT,
    E87_FAKE_OP_ATT_SEND_INIT,
    E87_FAKE_OP_HANDLE_ALLOC,
    E87_FAKE_OP_PROFILE_SET,
    E87_FAKE_OP_READ_REGISTER,
    E87_FAKE_OP_WRITE_REGISTER,
    E87_FAKE_OP_HCI_REGISTER,
    E87_FAKE_OP_SM_REGISTER,
    E87_FAKE_OP_ADV_PARAM,
    E87_FAKE_OP_ADV_DATA,
    E87_FAKE_OP_ADV_DISABLE,
    E87_FAKE_OP_ADV_ENABLE,
    E87_FAKE_OP_DISCONNECT,
    E87_FAKE_OP_HANDLE_FREE,
    E87_FAKE_OP_PAIR_ACCEPT_DISABLE,
    E87_FAKE_OP_PAIR_ACCEPT_ENABLE,
    E87_FAKE_OP_JUST_WORKS_CONFIRM,
    E87_FAKE_OP_SYSCFG_READ,
    E87_FAKE_OP_SYSCFG_WRITE
};

#define E87_FAKE_OPERATION_CAPACITY 128u
#define E87_FAKE_SYSCFG_CAPACITY 64u

typedef bool (*e87_fake_close_writes_fn)(uint32_t *out_epoch);

struct e87_fake_br35_state {
    enum e87_fake_br35_operation operations[E87_FAKE_OPERATION_CAPACITY];
    size_t operation_count;
    enum e87_fake_br35_operation fail_operation;
    int fail_count;
    int irq_disabled;
    uint8_t configured_slots;
    bool configured_allow_cover;
    bool pair_accept;
    bool short_next_read;
    bool short_next_write;
    uint16_t last_syscfg_read_id;
    uint16_t last_syscfg_read_length;
    uint16_t last_syscfg_write_id;
    uint16_t last_syscfg_write_length;
    uint8_t syscfg_48[E87_FAKE_SYSCFG_CAPACITY];
    uint8_t syscfg_49[E87_FAKE_SYSCFG_CAPACITY];
    uint16_t syscfg_48_length;
    uint16_t syscfg_49_length;
    struct e87_ble_peer bonds[2];
    uint16_t bond_count;
    unsigned int bond_exists_calls;
    unsigned int close_writes_on_bond_exists_call;
    bool close_writes_result;
    uint32_t close_writes_epoch;
    e87_fake_close_writes_fn close_writes;
    struct e87_ble_peer mapped_connection;
    struct e87_ble_peer mapped_identity;
    bool mapping_present;
    void *allocated_handle;
    const uint8_t *profile;
    const uint8_t *advertising_data;
    uint8_t advertising_length;
    uint32_t advertising_interval;
    uint8_t advertising_type;
    uint8_t advertising_channels;
    bool advertising_enabled;
    uint16_t connection_handle;
    struct e87_ble_peer connection_peer;
    bool connection_peer_valid;
    unsigned int disconnect_calls;
    unsigned int free_calls;
    unsigned int just_works_confirms;
    uint16_t just_works_handle;
    unsigned int state_enqueue_calls;
    bool state_enqueue_accept;
    uint32_t state_authorization_epoch;
    uint8_t state_packet[E87_BLE_TARGET_STATE_PACKET_SIZE];
};

extern struct e87_fake_br35_state e87_fake_br35;

void e87_fake_br35_reset(void);
const struct e87_ble_target_ingress *e87_fake_br35_ingress(void);
void e87_fake_br35_set_bond(unsigned int index,
                           const struct e87_ble_peer *peer);
void e87_fake_br35_set_identity_mapping(
    const struct e87_ble_peer *connection,
    const struct e87_ble_peer *identity);
void e87_fake_br35_emit_connection(const struct e87_ble_peer *peer,
                                   uint16_t connection_handle);
void e87_fake_br35_emit_encryption(uint8_t status, uint8_t enabled);
void e87_fake_br35_emit_pair_process(uint8_t subevent);
void e87_fake_br35_emit_pair_process_sized(uint8_t subevent,
                                           uint16_t size);
void e87_fake_br35_emit_just_works(const struct e87_ble_peer *peer);
void e87_fake_br35_emit_identity_resolved(
    const struct e87_ble_peer *connection,
    const struct e87_ble_peer *identity);
void e87_fake_br35_emit_disconnection(uint8_t status, uint8_t reason);
uint16_t e87_fake_br35_att_read(uint16_t connection_handle,
                               uint16_t attribute_handle,
                               uint16_t offset,
                               uint8_t *buffer,
                               uint16_t capacity);
int e87_fake_br35_att_write(uint16_t connection_handle,
                            uint16_t attribute_handle,
                            uint16_t transaction_mode,
                            uint16_t offset,
                            uint8_t *buffer,
                            uint16_t length);

#endif
