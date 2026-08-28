# E87 Stage 0-H Link-Closure Implementation Plan

> **For Codex:** Execute each task in order. Keep the pinned-SDK link loop evidence-driven: never add a source before tracing a live undefined symbol to its real owner and reviewing that owner's retained closure.

**Goal:** Produce a pinned-SDK Stage 0-H heartbeat image with an exact source closure and a map-level proof that only the approved boot seam and non-connectable BLE heartbeat are reachable.

**Architecture:** Remove the stock generated linker roots only for the Stage 0 board by conditioning the include inside `sdk_ld.c`'s existing `EXTERN`. Retain the vendor linker layout. Add real platform sources one undefined frontier at a time and keep target-policy data in a Stage 0-owned data-only translation unit. Freeze both the source lists and live-map policy in tests.

**Tooling:** Python `unittest`, pinned JieLi BR35 SDK/toolchain on `stadia-testbed`, ordinary `git apply`, linker map inspection.

---

## Task 1: Freeze the linker-root regression as RED

**Files:**

- Modify: `firmware/tests_py/test_stage0_static.py`

1. Expand `PATCH_TARGETS` from five to six entries by adding `SDK/cpu/br35/sdk_ld.c`.
2. Add a test that extracts the `sdk_ld.c` patch section and requires:
   - `_start` remains inside `EXTERN`;
   - only `#include "sdk_used_list.c"` is guarded for `CONFIG_BOARD_E87_1542_STAGE0_H`;
   - the Stage 0 branch does not emit that include;
   - the patch does not replace or remove `ENTRY(_start)`, `MEMORY`, or `SECTIONS`.
3. Add a regression assertion documenting that removing the Makefile used-symbol option alone is insufficient.
4. Run:

   ```sh
   python3 -m unittest firmware.tests_py.test_stage0_static -v
   ```

   Expected: intentional failures for the six-target set and missing `sdk_ld.c` conditional; existing tests remain green.
5. Commit only the RED test bytes.

## Task 2: Remove only the artificial linker roots

**Files:**

- Modify: `firmware/patches/stage0/0001-e87-stage0-hooks.patch`

1. In a detached clean checkout of SDK commit `d0167685d032d745d88fe50233302edd46941622`, apply the current overlay and five-target patch.
2. Edit `SDK/cpu/br35/sdk_ld.c` so `EXTERN` always contains `_start`, while `#include "sdk_used_list.c"` is excluded only when `CONFIG_BOARD_E87_1542_STAGE0_H` is defined.
3. Regenerate the repository patch with normal three-line context and only the six approved paths.
4. Verify ordinary application into a second clean pinned SDK checkout:

   ```sh
   git apply --check firmware/patches/stage0/0001-e87-stage0-hooks.patch
   ```

5. Re-run Task 1. Expected: all static tests green before source-closure expansion.
6. Commit the minimal production patch delta separately.

## Task 3: Capture the first genuine link frontier

**Files:**

- Evidence only; no repository source changes until the link output is reviewed.

1. Copy the exact repository overlays into a fresh pinned SDK checkout and apply the six-target patch.
2. Build with the externally supplied eight-hex build tag derived from the immutable repository source commit.
3. Save the complete log and partial map outside the repository.
4. Confirm that forbidden media/audio/VFS roots from `sdk_used_list.c` disappear.
5. Sort the remaining undefined symbols by source owner and classify each as:
   - real startup/platform dependency;
   - target-policy data ABI;
   - forbidden subsystem leak;
   - archive/library configuration issue.
6. Report this first frontier before adding sources.

## Task 4: Add the real startup closure under TDD

**Files:**

- Modify: `firmware/tests_py/test_stage0_static.py`
- Modify: `firmware/patches/stage0/0001-e87-stage0-hooks.patch`

For each frontier iteration:

1. Add the exact expected source to `REQUIRED_TARGET_SOURCES` first and run the focused test to see the intended RED.
2. Add the source to `E87_STAGE0_REQUIRED_SOURCES` in the patched Makefile.
3. Review the source's active preprocessor branch and retained call/data graph.
4. Rebuild from a fresh pinned SDK tree.
5. Record the new frontier and stop if it introduces a forbidden route.

Initial proven candidates are `cpu/br35/setup.c`, `cpu/power/msg.c`, pinned disabled-debug implementations as actually required, and `apps/common/update/update.c` solely for its `TCFG_UPDATE_ENABLE == 0` `update_result_get` implementation. Do not import `apps/watch/user_cfg.c` or `apps/watch/log_config/lib_jlui_config.c`.

## Task 5: Add Stage 0 platform-policy data ABI

**Files:**

- Create: `firmware/overlay/SDK/apps/watch/e87/e87_stage0_platform_config.c`
- Modify: `SDK/build/genFileList.c` section of the Stage 0 patch
- Modify: `SDK/build/Makefile.mk` section of the Stage 0 patch
- Modify: `firmware/tests_py/test_stage0_static.py`

1. Write failing tests requiring the new overlay source and restricting it to approved constant/table definitions.
2. Define only data ABI proven by the linker frontier: interrupt-mask policy, VM alignment values, and minimal BTIF item table as required by pinned SDK types.
3. Assert the source contains no function definition, initcall registration, filesystem operation, classic-BT accessor, writable config parser, or device pin assignment.
4. Add the source to the generated overlay list and exact C allowlist.
5. Rebuild and inspect the live map.

## Task 6: Implement and test the live-map oracle

**Files:**

- Create: `firmware/tools/validate-stage0-map.py`
- Create: `firmware/tests_py/test_stage0_map.py`
- Create: minimal synthetic map fixtures only if inline fixtures become unreadable

1. Write unit tests first for a valid live-symbol map, each forbidden family, missing required symbols, malformed input, duplicate policy entries, and discarded-section false positives.
2. Parse the pinned linker map's live output only; do not treat archive listing or discarded sections as reachability.
3. Require heartbeat and boot symbols.
4. Allow only the exact documented boot exceptions: `setup_arch` closure, `sdfile_init`, `syscfg_tools_init`, disabled-update `update_result_get`, and minimal VM/BTIF configuration.
5. Reject live audio/media, application-VFS, UI/display, ATT/GATT/SM/profile, update-engine, and RCSP symbols.
6. Run the validator against the real target map after every link iteration.

## Task 7: Freeze the final source and language closure

**Files:**

- Modify: `firmware/tests_py/test_stage0_static.py`
- Modify: `firmware/tests_py/test_stage0_target.py`
- Modify: `firmware/board-profiles/E87-1542-STAGE0-H.json`

1. Replace provisional source expectations with the final exact C source set.
2. Assert `S_SRC_FILES`, `s_SRC_FILES`, `cpp_SRC_FILES`, `cc_SRC_FILES`, and `cxx_SRC_FILES` are exactly empty unless a real pinned startup source proves otherwise.
3. Record the linker-root policy and exact allowed boot-seam exceptions in the board profile without weakening the externally non-connectable behavior claim.
4. Add a target test that pins those evidence fields exactly.

## Task 8: Final verification and handoff

Run, from a clean repository branch:

```sh
python3 -m unittest firmware.tests_py.test_stage0_static -v
python3 -m unittest firmware.tests_py.test_stage0_target -v
python3 -m unittest firmware.tests_py.test_stage0_map -v
python3 firmware/tools/test-host.py --suite stage0
python3 firmware/tools/test-host.py --suite all
git diff --check 3405832efd15cb46e8cb4ff8993a0c0efa9f6056..HEAD
```

Then, in two independent clean SDK checkouts:

1. ordinary patch apply-check at the pinned SDK commit;
2. full target build with an exact externally supplied build tag;
3. live-map validation;
4. output hash comparison for reproducibility if the build path is deterministic.

Commit the verified implementation. Report repository commit, patch/source/profile hashes, exact test commands and results, target ELF/map hashes, clean status, and any remaining hardware-only gap. Do not label the image deployable if the target link or map oracle remains RED.
