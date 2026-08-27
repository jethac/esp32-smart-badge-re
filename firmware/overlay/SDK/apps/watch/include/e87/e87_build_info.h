#ifndef E87_BUILD_INFO_H
#define E87_BUILD_INFO_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define E87_BUILD_INFO_SIZE 40u
#define E87_BUILD_INFO_SCHEMA_V1 1u
#define E87_BUILD_INFO_PROFILE_BYTES 16u
#define E87_BUILD_ID_BYTES 16u
#define E87_BUILD_INFO_PROFILE_ID "E87-JD9855-R1"

enum e87_build_capability {
    E87_BUILD_CAP_SEMANTIC_METRICS = 1u << 0,
    E87_BUILD_CAP_BATTERY_SERVICE = 1u << 1,
    E87_BUILD_CAP_PHYSICAL_RCSP_REWRITE = 1u << 2
};

#define E87_BUILD_INFO_CAPABILITIES_V1                                  \
    (E87_BUILD_CAP_SEMANTIC_METRICS |                                   \
     E87_BUILD_CAP_BATTERY_SERVICE |                                    \
     E87_BUILD_CAP_PHYSICAL_RCSP_REWRITE)

struct e87_build_identity {
    uint8_t semver_major;
    uint8_t semver_minor;
    uint8_t semver_patch;
    uint8_t build_id[E87_BUILD_ID_BYTES];
};

bool
e87_build_info_encode(const struct e87_build_identity *identity,
                      uint8_t *out,
                      size_t out_length);

#endif
