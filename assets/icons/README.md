# Devin mark

This repository intentionally carries a one-file mark subset: `devin.svg`. The
firmware asset pipeline compiles it into the 96x96 alpha asset used by the E87
face. It contains no provider or machine-mark set copied from Factory.

## Provenance and integrity

`devin.svg` is the correct Devin mark. It was traced from the `app.devin.ai`
PWA icon in `jethac/factory` commit
`2720aaf58a9d86a5142fd86dfb05ecb39d31364d`. It is byte-identical to
`assets/icons/devin.svg` at `jethac/factory-smartscreen` commit
`3feec00b8a9aa8c6874ca92477e4ed43098e3b84`.

- SHA-256: `0B77AF4A730199892F15D99E9B812A39452554089811E46D925E62C09E09A4A9`
- Git blob: `0a11af513a7d208c2c49f33ab2d2d38fd4aefe90`

Keep the asset content and this provenance together. Any replacement must come
from a verified official source and update the asset lock in the same change.
