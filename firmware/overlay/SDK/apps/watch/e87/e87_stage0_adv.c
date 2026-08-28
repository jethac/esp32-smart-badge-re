#include "e87/e87_stage0_adv.h"

#include <limits.h>
#include <string.h>

static const uint8_t empty_scan_response_storage = UINT8_C(0);

static uint8_t uppercase_hex_digit(unsigned int value)
{
    static const uint8_t digits[] = "0123456789ABCDEF";

    return digits[value & 0x0FU];
}

bool e87_stage0_adv_build(uint64_t build_tag,
                          uint8_t *output,
                          size_t capacity,
                          size_t *output_length)
{
    uint8_t value[E87_STAGE0_ADV_DATA_LENGTH];
    uint32_t tag;
    size_t index;

    if (output == NULL || output_length == NULL ||
        capacity < E87_STAGE0_ADV_DATA_LENGTH || build_tag > UINT32_MAX) {
        return false;
    }

    tag = (uint32_t)build_tag;
    value[0] = UINT8_C(0x02);
    value[1] = UINT8_C(0x01);
    value[2] = UINT8_C(0x06);
    value[3] = UINT8_C(0x10);
    value[4] = UINT8_C(0x09);
    memcpy(&value[5], "E87-S0-", 7U);
    for (index = 0U; index < E87_STAGE0_BUILD_TAG_HEX_DIGITS; index += 1U) {
        const unsigned int shift =
            (unsigned int)((E87_STAGE0_BUILD_TAG_HEX_DIGITS - 1U - index) * 4U);
        value[12U + index] = uppercase_hex_digit((unsigned int)(tag >> shift));
    }
    value[20] = UINT8_C(0x08);
    value[21] = UINT8_C(0xFF);
    value[22] = UINT8_C(0xFF);
    value[23] = UINT8_C(0xFF);
    value[24] = UINT8_C(0x00);
    value[25] = (uint8_t)(tag & UINT32_C(0xFF));
    value[26] = (uint8_t)((tag >> 8) & UINT32_C(0xFF));
    value[27] = (uint8_t)((tag >> 16) & UINT32_C(0xFF));
    value[28] = (uint8_t)((tag >> 24) & UINT32_C(0xFF));

    memcpy(output, value, sizeof(value));
    *output_length = sizeof(value);
    return true;
}

const uint8_t *e87_stage0_scan_response(size_t *output_length)
{
    if (output_length == NULL) {
        return NULL;
    }
    *output_length = 0U;
    return &empty_scan_response_storage;
}

bool e87_stage0_static_random_address_is_valid(
    const uint8_t address[E87_STAGE0_RANDOM_ADDRESS_LENGTH])
{
    bool random_part_all_zero;
    bool random_part_all_one;
    size_t index;

    if (address == NULL || (address[5] & UINT8_C(0xC0)) != UINT8_C(0xC0)) {
        return false;
    }
    random_part_all_zero = (address[5] & UINT8_C(0x3F)) == UINT8_C(0);
    random_part_all_one =
        (address[5] & UINT8_C(0x3F)) == UINT8_C(0x3F);
    for (index = 0U; index < 5U; index += 1U) {
        random_part_all_zero = random_part_all_zero && address[index] == 0U;
        random_part_all_one =
            random_part_all_one && address[index] == UINT8_MAX;
    }
    return !random_part_all_zero && !random_part_all_one;
}

static bool bytes_are_all(const uint8_t *value, size_t length, uint8_t expected)
{
    size_t index;

    for (index = 0U; index < length; index += 1U) {
        if (value[index] != expected) {
            return false;
        }
    }
    return true;
}

bool e87_stage0_derive_static_random_address(
    const uint8_t uuid[E87_STAGE0_FLASH_UUID_LENGTH],
    uint8_t output[E87_STAGE0_RANDOM_ADDRESS_LENGTH])
{
    static const uint8_t domain[] = "E87-S0-ADDR-v1";
    const uint64_t fnv_offset = UINT64_C(14695981039346656037);
    const uint64_t fnv_prime = UINT64_C(1099511628211);
    uint8_t address[E87_STAGE0_RANDOM_ADDRESS_LENGTH];
    uint64_t hash = fnv_offset;
    size_t index;

    if (uuid == NULL || output == NULL ||
        bytes_are_all(uuid, E87_STAGE0_FLASH_UUID_LENGTH, UINT8_C(0)) ||
        bytes_are_all(uuid, E87_STAGE0_FLASH_UUID_LENGTH, UINT8_MAX)) {
        return false;
    }
    for (index = 0U; index < sizeof(domain) - 1U; index += 1U) {
        hash ^= domain[index];
        hash *= fnv_prime;
    }
    for (index = 0U; index < E87_STAGE0_FLASH_UUID_LENGTH; index += 1U) {
        hash ^= uuid[index];
        hash *= fnv_prime;
    }
    for (index = 0U; index < E87_STAGE0_RANDOM_ADDRESS_LENGTH; index += 1U) {
        address[index] = (uint8_t)(hash >> (index * 8U));
    }
    address[5] = (uint8_t)((address[5] & UINT8_C(0x3F)) | UINT8_C(0xC0));
    if (!e87_stage0_static_random_address_is_valid(address)) {
        return false;
    }
    memcpy(output, address, sizeof(address));
    return true;
}
