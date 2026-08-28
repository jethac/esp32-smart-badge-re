#include "e87/e87_ble_target_sdk.h"
#include "e87/e87_ble_target_internal.h"

#include <string.h>

#define E87_JOURNAL_MAGIC UINT32_C(0x4A373845)
#define E87_JOURNAL_VERSION UINT16_C(1)
#define E87_JOURNAL_RECORD_OFFSET 12u
#define E87_JOURNAL_RESERVED_OFFSET 43u
#define E87_JOURNAL_CRC_OFFSET 44u

struct journal_slot {
    bool valid;
    uint32_t sequence;
    uint8_t wire[E87_BLE_OWNER_JOURNAL_WIRE_SIZE];
    struct e87_owner_record record;
};

static void put_u16(uint8_t *wire, size_t offset, uint16_t value)
{
    wire[offset] = (uint8_t)value;
    wire[offset + 1u] = (uint8_t)(value >> 8u);
}

static void put_u32(uint8_t *wire, size_t offset, uint32_t value)
{
    wire[offset] = (uint8_t)value;
    wire[offset + 1u] = (uint8_t)(value >> 8u);
    wire[offset + 2u] = (uint8_t)(value >> 16u);
    wire[offset + 3u] = (uint8_t)(value >> 24u);
}

static uint16_t get_u16(const uint8_t *wire, size_t offset)
{
    return (uint16_t)wire[offset] |
           (uint16_t)((uint16_t)wire[offset + 1u] << 8u);
}

static uint32_t get_u32(const uint8_t *wire, size_t offset)
{
    return (uint32_t)wire[offset] |
           ((uint32_t)wire[offset + 1u] << 8u) |
           ((uint32_t)wire[offset + 2u] << 16u) |
           ((uint32_t)wire[offset + 3u] << 24u);
}

static uint32_t crc32(const uint8_t *data, size_t length)
{
    uint32_t crc = UINT32_MAX;
    size_t index;
    unsigned int bit;

    for (index = 0u; index < length; index += 1u) {
        crc ^= data[index];
        for (bit = 0u; bit < 8u; bit += 1u) {
            const uint32_t mask = (uint32_t)-(int32_t)(crc & UINT32_C(1));
            crc = (crc >> 1u) ^ (UINT32_C(0xEDB88320) & mask);
        }
    }
    return ~crc;
}

static void encode_record(uint8_t *wire,
                          const struct e87_owner_record *record)
{
    const size_t base = E87_JOURNAL_RECORD_OFFSET;
    put_u32(wire, base + 0u, record->magic);
    put_u16(wire, base + 4u, record->version);
    put_u16(wire, base + 6u, record->phase);
    put_u32(wire, base + 8u, record->generation);
    wire[base + 12u] = record->has_owner;
    wire[base + 13u] = record->owner.address_type;
    memcpy(&wire[base + 14u], record->owner.address,
           E87_BLE_ADDRESS_SIZE);
    wire[base + 20u] = record->candidate.address_type;
    memcpy(&wire[base + 21u], record->candidate.address,
           E87_BLE_ADDRESS_SIZE);
    put_u32(wire, base + 27u, record->checksum);
}

static void decode_record(const uint8_t *wire,
                          struct e87_owner_record *record)
{
    const size_t base = E87_JOURNAL_RECORD_OFFSET;
    memset(record, 0, sizeof(*record));
    record->magic = get_u32(wire, base + 0u);
    record->version = get_u16(wire, base + 4u);
    record->phase = get_u16(wire, base + 6u);
    record->generation = get_u32(wire, base + 8u);
    record->has_owner = wire[base + 12u];
    record->owner.address_type = wire[base + 13u];
    memcpy(record->owner.address, &wire[base + 14u],
           E87_BLE_ADDRESS_SIZE);
    record->candidate.address_type = wire[base + 20u];
    memcpy(record->candidate.address, &wire[base + 21u],
           E87_BLE_ADDRESS_SIZE);
    record->checksum = get_u32(wire, base + 27u);
}

static bool decode_slot(struct journal_slot *slot)
{
    if (get_u32(slot->wire, 0u) != E87_JOURNAL_MAGIC ||
        get_u16(slot->wire, 4u) != E87_JOURNAL_VERSION ||
        get_u16(slot->wire, 6u) != E87_BLE_OWNER_JOURNAL_WIRE_SIZE ||
        slot->wire[E87_JOURNAL_RESERVED_OFFSET] != 0u ||
        get_u32(slot->wire, E87_JOURNAL_CRC_OFFSET) !=
            crc32(slot->wire, E87_JOURNAL_CRC_OFFSET)) {
        return false;
    }
    slot->sequence = get_u32(slot->wire, 8u);
    if (slot->sequence == 0u) {
        return false;
    }
    decode_record(slot->wire, &slot->record);
    return e87_owner_record_is_valid(&slot->record);
}

static void read_slot(uint16_t item_id, struct journal_slot *slot)
{
    memset(slot, 0, sizeof(*slot));
    if (syscfg_read(item_id, slot->wire,
                    E87_BLE_OWNER_JOURNAL_WIRE_SIZE) !=
        (int)E87_BLE_OWNER_JOURNAL_WIRE_SIZE) {
        return;
    }
    slot->valid = decode_slot(slot);
}

static bool records_equal(const struct e87_owner_record *left,
                          const struct e87_owner_record *right)
{
    return left->magic == right->magic &&
           left->version == right->version &&
           left->phase == right->phase &&
           left->generation == right->generation &&
           left->has_owner == right->has_owner &&
           memcmp(&left->owner, &right->owner, sizeof(left->owner)) == 0 &&
           memcmp(&left->candidate, &right->candidate,
                  sizeof(left->candidate)) == 0 &&
           left->checksum == right->checksum;
}

static const struct journal_slot *latest_slot(
    const struct journal_slot *slot_a,
    const struct journal_slot *slot_b)
{
    if (!slot_a->valid) {
        return slot_b->valid ? slot_b : NULL;
    }
    if (!slot_b->valid) {
        return slot_a;
    }
    if (slot_a->sequence == slot_b->sequence) {
        return records_equal(&slot_a->record, &slot_b->record) ? slot_a : NULL;
    }
    return slot_a->sequence > slot_b->sequence ? slot_a : slot_b;
}

bool e87_ble_target_journal_load(struct e87_owner_record *out)
{
    struct journal_slot slot_a;
    struct journal_slot slot_b;
    const struct journal_slot *latest;

    if (out == NULL) {
        return false;
    }
    read_slot(E87_BLE_OWNER_JOURNAL_SLOT_A_ID, &slot_a);
    read_slot(E87_BLE_OWNER_JOURNAL_SLOT_B_ID, &slot_b);
    latest = latest_slot(&slot_a, &slot_b);
    if (latest == NULL) {
        return false;
    }
    *out = latest->record;
    return true;
}

static void encode_slot(uint8_t *wire, uint32_t sequence,
                        const struct e87_owner_record *record)
{
    memset(wire, 0, E87_BLE_OWNER_JOURNAL_WIRE_SIZE);
    put_u32(wire, 0u, E87_JOURNAL_MAGIC);
    put_u16(wire, 4u, E87_JOURNAL_VERSION);
    put_u16(wire, 6u, E87_BLE_OWNER_JOURNAL_WIRE_SIZE);
    put_u32(wire, 8u, sequence);
    encode_record(wire, record);
    put_u32(wire, E87_JOURNAL_CRC_OFFSET,
            crc32(wire, E87_JOURNAL_CRC_OFFSET));
}

bool e87_ble_target_journal_save(const struct e87_owner_record *record)
{
    struct journal_slot slot_a;
    struct journal_slot slot_b;
    struct journal_slot verified;
    const struct journal_slot *latest;
    uint16_t target_id;
    uint32_t next_sequence;
    uint8_t wire[E87_BLE_OWNER_JOURNAL_WIRE_SIZE];

    if (!e87_owner_record_is_valid(record)) {
        return false;
    }
    read_slot(E87_BLE_OWNER_JOURNAL_SLOT_A_ID, &slot_a);
    read_slot(E87_BLE_OWNER_JOURNAL_SLOT_B_ID, &slot_b);
    latest = latest_slot(&slot_a, &slot_b);
    if (slot_a.valid && slot_b.valid && latest == NULL) {
        return false;
    }
    if (latest != NULL && latest->sequence == UINT32_MAX) {
        return false;
    }
    next_sequence = latest == NULL ? UINT32_C(1)
                                   : latest->sequence + UINT32_C(1);
    target_id = latest == &slot_a ? E87_BLE_OWNER_JOURNAL_SLOT_B_ID
                                  : E87_BLE_OWNER_JOURNAL_SLOT_A_ID;
    encode_slot(wire, next_sequence, record);
    if (syscfg_write(target_id, wire, E87_BLE_OWNER_JOURNAL_WIRE_SIZE) !=
        (int)E87_BLE_OWNER_JOURNAL_WIRE_SIZE) {
        return false;
    }
    read_slot(target_id, &verified);
    return verified.valid && verified.sequence == next_sequence &&
           memcmp(verified.wire, wire, sizeof(wire)) == 0 &&
           records_equal(&verified.record, record);
}
