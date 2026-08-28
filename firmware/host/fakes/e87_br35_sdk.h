#ifndef E87_BR35_SDK_H
#define E87_BR35_SDK_H

#include <stdbool.h>
#include <stdint.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint16_t hci_con_handle_t;
typedef uint8_t bd_addr_t[6];

typedef enum {
    IO_CAPABILITY_DISPLAY_ONLY = 0,
    IO_CAPABILITY_DISPLAY_YES_NO,
    IO_CAPABILITY_KEYBOARD_ONLY,
    IO_CAPABILITY_NO_INPUT_NO_OUTPUT,
    IO_CAPABILITY_KEYBOARD_DISPLAY
} io_capability_t;

typedef enum {
    BLE_CMD_RET_SUCESS = 0,
    BLE_CMD_RET_BUSY = -100,
    BLE_CMD_OPT_FAIL = -98
} ble_cmd_ret_e;

typedef enum {
    ATT_OP_AUTO_READ_CCC = 0,
    ATT_OP_NOTIFY = 1,
    ATT_OP_INDICATE = 2
} att_op_type_e;

#define APP_ADV_IND 0u
#define APP_ADV_CHANNEL_ALL 7u
#define SM_AUTHREQ_BONDING 0x01u
#define SM_AUTHREQ_SECURE_CONNECTION 0x08u
#define ATT_CTRL_BLOCK_SIZE 188u
#define ATT_TRANSACTION_MODE_NONE 0u
#define HCI_CON_HANDLE_INVALID 0xffffu
#define HCI_EVENT_PACKET 0x04u
#define HCI_EVENT_DISCONNECTION_COMPLETE 0x05u
#define HCI_EVENT_ENCRYPTION_CHANGE 0x08u
#define HCI_EVENT_LE_META 0x3eu
#define HCI_SUBEVENT_LE_CONNECTION_COMPLETE 0x01u
#define SM_EVENT_JUST_WORKS_REQUEST 0xd0u
#define SM_EVENT_IDENTITY_RESOLVING_FAILED 0xd9u
#define SM_EVENT_IDENTITY_RESOLVING_SUCCEEDED 0xdau
#define SM_EVENT_IDENTITY_CREATED 0xdeu
#define SM_EVENT_PAIR_PROCESS 0xdfu
#define SM_EVENT_PAIR_SUB_ADD_LIST_SUCCESS 0x10u
#define SM_EVENT_PAIR_SUB_ADD_LIST_FAILED 0x11u

typedef void (*app_ble_packet_handler_t)(void *, uint8_t, uint16_t,
                                         uint8_t *, uint16_t);
typedef uint16_t (*app_ble_att_read_callback_t)(void *, uint16_t, uint16_t,
                                                uint16_t, uint8_t *, uint16_t);
typedef int (*app_ble_att_write_callback_t)(void *, uint16_t, uint16_t,
                                            uint16_t, uint16_t, uint8_t *,
                                            uint16_t);
typedef void (*app_ble_sm_event_callback_t)(void *, uint8_t, uint16_t,
                                            uint8_t *, uint16_t);

int app_ble_init(void);
void *app_ble_hdl_alloc(void);
int app_ble_hdl_free(void *handle);
int app_ble_sm_init(io_capability_t io_type, u8 auth_req,
                    uint8_t min_key_size, u8 security_en);
int app_ble_profile_set(void *handle, const uint8_t *database);
int app_ble_att_read_callback_register(void *handle,
                                       app_ble_att_read_callback_t callback);
int app_ble_att_write_callback_register(void *handle,
                                         app_ble_att_write_callback_t callback);
int app_ble_hci_event_callback_register(void *handle,
                                         app_ble_packet_handler_t callback);
int app_ble_sm_event_callback_register(void *handle,
                                        app_ble_sm_event_callback_t callback);
int app_ble_set_adv_param(void *handle, u32 interval, u8 type, u8 channels);
int app_ble_adv_data_set(void *handle, u8 *data, u8 length);
int app_ble_adv_enable(void *handle, u8 enabled);
int app_ble_disconnect(void *handle);
u16 app_ble_get_hdl_con_handle(void *handle);
ble_cmd_ret_e app_ble_att_send_data(void *handle, u16 att_handle, u8 *data,
                                    u16 length, att_op_type_e operation);
ble_cmd_ret_e ble_user_cmd_prepare(int command, int argc, ...);

#define BLE_CMD_MULTI_ATT_SEND_INIT 1
#define ble_op_multi_att_send_init(address, size, payload) \
    ble_user_cmd_prepare(BLE_CMD_MULTI_ATT_SEND_INIT, 3, address, size, payload)

void le_device_db_init(void);
void ble_list_config_reset(u8 slots, u8 allow_cover);
bool ble_list_pair_accept(u8 enabled);
u16 ble_list_get_count(void);
bool ble_list_clear_all(void);
bool ble_list_check_addr_is_exist(u8 *address, u8 address_type);
bool ble_list_delete_device(u8 *address, u8 address_type);
bool ble_list_get_id_addr(u8 *connection_address, u8 connection_address_type,
                          u8 *identity_address);
void sm_just_works_confirm(hci_con_handle_t connection_handle);

int syscfg_read(u16 item_id, void *buffer, u16 length);
int syscfg_write(u16 item_id, const void *buffer, u16 length);
int cpu_irq_disabled(void);
void local_irq_disable(void);
void local_irq_enable(void);

static inline uint16_t e87_fake_le16(const uint8_t *packet, unsigned int offset)
{
    return (uint16_t)packet[offset] |
           (uint16_t)((uint16_t)packet[offset + 1u] << 8u);
}

static inline uint8_t hci_event_packet_get_type(const uint8_t *event)
{
    return event[0];
}

static inline uint8_t hci_event_le_meta_get_subevent_code(const uint8_t *event)
{
    return event[2];
}

static inline uint8_t
hci_subevent_le_connection_complete_get_status(const uint8_t *event)
{
    return event[3];
}

static inline hci_con_handle_t
hci_subevent_le_connection_complete_get_connection_handle(const uint8_t *event)
{
    return e87_fake_le16(event, 4u);
}

static inline uint8_t
hci_subevent_le_connection_complete_get_peer_address_type(const uint8_t *event)
{
    return event[7];
}

static inline void
hci_subevent_le_connection_complete_get_peer_address(const uint8_t *event,
                                                      bd_addr_t address)
{
    unsigned int index;
    for (index = 0u; index < 6u; index += 1u) {
        address[index] = event[13u - index];
    }
}

static inline uint8_t hci_event_encryption_change_get_status(
    const uint8_t *event)
{
    return event[2];
}

static inline uint16_t hci_event_encryption_change_get_connection_handle(
    const uint8_t *event)
{
    return e87_fake_le16(event, 3u);
}

static inline uint8_t hci_event_encryption_change_get_encryption_enabled(
    const uint8_t *event)
{
    return event[5];
}

static inline uint16_t hci_event_disconnection_complete_get_connection_handle(
    const uint8_t *event)
{
    return e87_fake_le16(event, 3u);
}

static inline hci_con_handle_t sm_event_just_works_request_get_handle(
    const uint8_t *event)
{
    return e87_fake_le16(event, 2u);
}

static inline uint8_t sm_event_just_works_request_get_addr_type(
    const uint8_t *event)
{
    return event[4];
}

static inline void sm_event_just_works_request_get_address(
    const uint8_t *event, bd_addr_t address)
{
    unsigned int index;
    for (index = 0u; index < 6u; index += 1u) {
        address[index] = event[10u - index];
    }
}

static inline uint8_t
sm_event_identity_resolving_succeeded_get_addr_type(const uint8_t *event)
{
    return event[4];
}

static inline void
sm_event_identity_resolving_succeeded_get_address(const uint8_t *event,
                                                   bd_addr_t address)
{
    unsigned int index;
    for (index = 0u; index < 6u; index += 1u) {
        address[index] = event[10u - index];
    }
}

static inline uint8_t
sm_event_identity_resolving_succeeded_get_identity_addr_type(
    const uint8_t *event)
{
    return event[11];
}

static inline void
sm_event_identity_resolving_succeeded_get_identity_address(
    const uint8_t *event, bd_addr_t address)
{
    unsigned int index;
    for (index = 0u; index < 6u; index += 1u) {
        address[index] = event[17u - index];
    }
}

#define sm_event_identity_created_get_addr_type(event) \
    sm_event_identity_resolving_succeeded_get_addr_type(event)
#define sm_event_identity_created_get_address(event, address) \
    sm_event_identity_resolving_succeeded_get_address(event, address)
#define sm_event_identity_created_get_identity_addr_type(event) \
    sm_event_identity_resolving_succeeded_get_identity_addr_type(event)
#define sm_event_identity_created_get_identity_address(event, address) \
    sm_event_identity_resolving_succeeded_get_identity_address(event, address)

#endif
