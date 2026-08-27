#include "e87/e87_build_info.h"

#include <string.h>

bool
e87_build_info_encode(const struct e87_build_identity *identity,
                      uint8_t *out,
                      size_t out_length)
{
    static const char profile[] = E87_BUILD_INFO_PROFILE_ID;
    uint8_t record[E87_BUILD_INFO_SIZE] = {0};

    if (identity == NULL || out == NULL ||
        out_length != E87_BUILD_INFO_SIZE) {
        return false;
    }

    record[0] = E87_BUILD_INFO_SCHEMA_V1;
    record[1] = (uint8_t)E87_BUILD_INFO_CAPABILITIES_V1;
    memcpy(&record[2], profile, sizeof(profile) - 1U);
    record[18] = identity->semver_major;
    record[19] = identity->semver_minor;
    record[20] = identity->semver_patch;
    memcpy(&record[22], identity->build_id, E87_BUILD_ID_BYTES);
    memcpy(out, record, sizeof(record));
    return true;
}
