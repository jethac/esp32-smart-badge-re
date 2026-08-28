#ifndef E87_BLE_TARGET_INTERNAL_H
#define E87_BLE_TARGET_INTERNAL_H

#include "e87/e87_bond_policy.h"

#include <stdbool.h>
#include <stdint.h>

#define E87_BLE_OWNER_JOURNAL_SLOT_A_ID UINT16_C(48)
#define E87_BLE_OWNER_JOURNAL_SLOT_B_ID UINT16_C(49)
#define E87_BLE_OWNER_JOURNAL_WIRE_SIZE UINT16_C(48)

bool e87_ble_target_journal_load(struct e87_owner_record *out);
bool e87_ble_target_journal_save(const struct e87_owner_record *record);
bool e87_ble_target_epoch_advance(uint32_t *epoch, bool *exhausted);

#endif
