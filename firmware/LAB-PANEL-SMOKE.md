# E87 LAB_ONLY panel smoke

This artifact is a deliberately narrow display/link milestone, not the final
badge firmware. It initializes the inferred JD9855 path with the backlight
dark, renders `PAIR ME NOW` through one serial `0x5460` strip buffer, enables
the backlight only after all 12 strips finish, and changes once after three
seconds to fixed Devin rings (`day=67`, `week=42`, `$17.27`).

Bluetooth, RCSP, charging, update, buttons, sleep, and semantic writes remain
disabled. In particular, this LAB_ONLY image does not claim a recovery route.
It is intended only for a sacrificial, externally recoverable badge.

The package transport version is `11.1.0.4`, monotonically after the accepted
Stage0 `11.1.0.3`. The firmware build-info semantic version is independently
versioned as `0.1.0`; it is not the Qix transport version. A final full image
must use transport version `11.1.0.5` or later.

The recovered model-1552 descriptor says two `0x5460` buffers. That remains an
evidence fact. This smoke image uses a separately named LAB_ONLY runtime DBI
parameter with one buffer because the application renders serially and waits
for completion before every reuse. This is neither confirmation of the
model-1542 wiring nor a revision of the recovered descriptor.

The LAB task has a 4096-byte stack. The pi32 linker measured the deepest local
renderer frame at 2724 bytes, so the inherited 768-byte substrate task is not
used. The target closure adds only the vendor BR35 DBI archive and the vendor
power-gate source needed by the panel seam.

Generated asset sources are not normal SDK-overlay files. The profile records
four exact source-to-destination mappings and SHA-256 digests for both asset C
files and both headers. A build intake must verify those digests before copying
the C files into `SDK/apps/watch/e87` and the un-namespaced generated headers
into the SDK include root `SDK/apps/watch/include`.

## Closed build and package intake

`package-lab-panel-smoke.py` is the only package facade for this milestone. It
does not accept an existing generated SDK, ELF, map, object list, caller-picked
epoch, or build receipt. The source checkout must be clean at the requested
HEAD, including untracked files. The facade then creates standalone fresh
source and SDK clones inside the owned run directory, checks out the exact
source commit and SDK commit/tree, materializes the SDK with the full-substrate
patch and every exact overlay mapping, applies the three-file LAB delta as a
separate hashed tree transition, runs the pinned toolchain, and validates the
resulting ELF/map/object/resolution projection before packaging.

The SDK clone consumes only Git object `d0167685d032d745d88fe50233302edd46941622`;
ambient changes in an installed SDK worktree are never copied into the build.
Receipts bind the source commit/tree/commit-object/epoch, SDK commit/tree/archive,
full and LAB patch bytes and paths, every overlay source/destination/hash, the
pre-build tree, toolchain lock and tools, exact verbose make/link output, ELF,
map, object list, resolution, extraction commands, native package commands,
and final artifacts.

From a clean committed checkout, with a new empty run directory outside every
input tree:

```sh
/usr/bin/python3.11 firmware/tools/package-lab-panel-smoke.py \
  --reference-root /home/jethac/.local/share/e87-dev/references/model1552-e87-11.1.0.2 \
  --run-root /home/jethac/.local/share/e87-dev/lab/e87-panel-smoke-11.1.0.4 \
  --expected-source-commit 0123456789abcdef0123456789abcdef01234567
```

Replace the example commit with the exact lowercase 40-hex clean HEAD. The run
root must already exist and be empty.

The pinned vendor `isd_download` creates `jl_isd.bin`, `jl_isd.fw`, and
`update.ufw`, then, on this device-free build host, truthfully returns 245 with
the exact final stdout line `Device Offline`. The LAB facade does not rewrite
that status. It accepts it only after proving the exact three nonempty outputs,
no input mutation, no other interactive diagnostic, and no extra file. It then
runs the pinned `ufw_maker` normally and requires its independently made UFW to
be byte-identical and semantically valid before Qix wrapping. This narrow
`DISCONNECTED_AFTER_ALL_OUTPUTS` exception belongs only to the LAB receipt
schema and is not Stage0 success or a recovery/flash claim.
