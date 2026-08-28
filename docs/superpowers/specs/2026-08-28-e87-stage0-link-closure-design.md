# E87 Stage 0-H Link-Closure Design

Date: 2026-08-28

## Goal

Make the existing panel-off Stage 0 heartbeat image link from an exact, reviewable source and reachability closure. Preserve its frozen non-connectable BLE advertisement behavior while proving that stock audio, application-filesystem, UI, ATT/GATT/SM/profile, update-engine, and RCSP paths are not reachable.

This design starts from repository commit `3405832efd15cb46e8cb4ff8993a0c0efa9f6056` and pinned SDK commit `d0167685d032d745d88fe50233302edd46941622`.

## Root cause

The Stage 0 Makefile already replaces the normal source lists and removes `--plugin-opt=-used-symbol-file=apps/watch/sdk_used_list.used`. That is insufficient because `SDK/cpu/br35/sdk_ld.c` independently emits this linker root:

```c
EXTERN(
_start
#include "sdk_used_list.c"
);
```

The generated include roots stock decoder, resampler, audio, ADC, tone, WDRC, G729, FAT/sdfile VFS, SOF-EQ, and A2DP symbols before ordinary section garbage collection can remove them. The exact-ten-C-source diagnostic therefore fails with forbidden archive members and only later exposes genuine startup dependencies.

## Chosen architecture

Add `SDK/cpu/br35/sdk_ld.c` to the frozen patch-target set. Under `CONFIG_BOARD_E87_1542_STAGE0_H`, guard only the `sdk_used_list.c` include inside `EXTERN`; retain `_start`, `ENTRY`, `MEMORY`, and every vendor linker section unchanged.

After removing that artificial root set, derive the source closure from the real linker frontier. Each added translation unit must satisfy an unresolved symbol with the pinned SDK's implementation and must pass source- and map-level policy checks. The expected first real dependencies are:

- `SDK/cpu/br35/setup.c` for `setup_arch` and `cache_ram_init`;
- `SDK/cpu/power/msg.c` for the P11 message transport used by platform startup;
- the pinned disabled-debug implementation where startup or archive code needs debug ABI;
- `SDK/apps/common/update/update.c` only for its `TCFG_UPDATE_ENABLE == 0` startup ABI implementation of `update_result_get`;
- a Stage 0-owned platform-policy translation unit containing data ABI only, such as IRQ policy, VM alignment constants, and the minimal BTIF table.

The platform-policy translation unit must not define function stubs. It records target configuration values that stock watch builds otherwise obtain from broad `lib_jlui_config.c` and `user_cfg.c` files. Those stock files are intentionally excluded because they own UI, classic-BT, media, storage, and runtime configuration routes beyond Stage 0.

All C and non-C language lists remain exact assignments after `fileList.mk`. No source is added merely to silence a linker error: an undefined frontier is traced to its real owner, its retained dependency graph is reviewed, and the source plus required map assertion is added together.

## Allowed boot-seam exceptions

The reachability contract distinguishes the immutable vendor boot seam from application routes. The map may retain exactly:

- `setup_arch` and its real platform initialization closure;
- `sdfile_init` and `syscfg_tools_init`, which `setup_arch` calls before `app_main`;
- `update_result_get`, using only the disabled-update branch returning zero;
- the minimal VM/BTIF configuration data required by the platform ABI.

These names do not authorize an application filesystem route, update engine, UI, classic profile, or writable configuration flow. Tests must reject such reachable routes even when similarly named boot-seam symbols are allowed.

## Test strategy

Write structural tests before changing production bytes. They will initially fail because the patch still has five targets and `sdk_ld.c` remains unconditional. The tests will require:

1. exactly one Stage 0 conditional around only `#include "sdk_used_list.c"`, with `_start`, `ENTRY`, `MEMORY`, and linker sections retained;
2. an exact source allowlist and empty `S`, `s`, `cpp`, `cc`, and `cxx` lists;
3. exclusion of broad stock configuration and subsystem translation units;
4. a map/reachability validator with explicit required, allowed-exception, and forbidden symbol families;
5. ordinary patch application against the exact pinned SDK;
6. a real pinned-SDK build whose undefined-symbol frontier is recorded at every closure iteration.

The map validator must inspect live/reachable output, not merely archive names or discarded sections. It will require the Stage 0 heartbeat entry points and boot seam, and reject live audio/media, application VFS, display/UI, ATT/GATT/SM/profile, update-engine, and RCSP symbols.

## Rejected alternatives

Importing stock `apps/watch/user_cfg.c` and `apps/watch/log_config/lib_jlui_config.c` is rejected. Although they define some required data ABI, they also own broad classic-BT, media, filesystem, UI, and runtime configuration policy that cannot support a minimal-source claim.

Adding one-off function stubs is rejected because it can produce a linked image without the real platform behavior. Broad stock source imports followed by reliance on section garbage collection are also rejected because they expand the trust boundary and make reachability dependent on fragile incidental roots.

## Completion criteria

The redesign is complete only when the exact pinned SDK builds, the resulting map satisfies the required/allowed/forbidden reachability oracle, all host/static/patch tests pass, the worktree is clean, and the final patch and source hashes are recorded. Until then it remains an architecture or link-closure RED, not a deployable high-assurance image.
