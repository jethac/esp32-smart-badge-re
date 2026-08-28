#ifndef E87_STAGE0_ADV_H
#define E87_STAGE0_ADV_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define E87_STAGE0_BUILD_TAG_HEX_DIGITS 8U
#define E87_STAGE0_LOCAL_NAME_LENGTH 15U
#define E87_STAGE0_ADV_DATA_LENGTH 29U
#define E87_STAGE0_ADV_INTERVAL_UNITS 1600U
#define E87_STAGE0_ADV_TYPE_NONCONN_IND 3U
#define E87_STAGE0_ADV_CHANNEL_MAP 0x07U
#define E87_STAGE0_OWN_ADDRESS_TYPE_RANDOM 1U
#define E87_STAGE0_FLASH_UUID_LENGTH 16U
#define E87_STAGE0_RANDOM_ADDRESS_LENGTH 6U

bool e87_stage0_adv_build(uint64_t build_tag,
                          uint8_t *output,
                          size_t capacity,
                          size_t *output_length);

const uint8_t *e87_stage0_scan_response(size_t *output_length);

bool e87_stage0_static_random_address_is_valid(
    const uint8_t address[E87_STAGE0_RANDOM_ADDRESS_LENGTH]);

bool e87_stage0_derive_static_random_address(
    const uint8_t uuid[E87_STAGE0_FLASH_UUID_LENGTH],
    uint8_t output[E87_STAGE0_RANDOM_ADDRESS_LENGTH]);

#endif
