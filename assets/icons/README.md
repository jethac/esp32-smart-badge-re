# Marks

Copied from factory's `src/ui/static/icons`, plus three machine marks that
factory has no use for. Kept as files, not traced into Dart, so the wall and the
console cannot drift apart.

Rendering differs in one way from the web: `provider_marks.dart` gives a mark
its published brand colour where its brand has one, and draws it in the
foreground colour where the mark is black in its own guidelines. A colour is
never guessed.

# Provider marks

Vendored so factory serves no third-party asset at page load. Factory runs on a
private host behind Cloudflare Access; hotlinking a vendor's logo would leak a
page view to that vendor on every render and break the UI offline.

## Where these came from

All nine were copied from CodexBar, a macOS menu bar app by Peter Steinberger
(https://github.com/steipete/CodexBar), from
`Sources/CodexBar/Resources/ProviderIcon-<name>.svg`. CodexBar's changelog
credits the SVG set to a community contribution (`@vandamd`, "switch provider
brand icons to SVGs"); it does not name an upstream source beyond that, so the
marks are presumed to be redrawn from each vendor's own published logo.

| file             | CodexBar resource            |
| ---------------- | ---------------------------- |
| `aiand.svg`      | `ProviderIcon-aiand.svg`     |
| `claude.svg`     | `ProviderIcon-claude.svg`    |
| `codex.svg`      | `ProviderIcon-codex.svg`     |
| `cursor.svg`     | `ProviderIcon-cursor.svg`    |
| `devin.svg`      | `ProviderIcon-devin.svg`     |
| `gemini.svg`     | `ProviderIcon-gemini.svg`    |
| `grok.svg`       | `ProviderIcon-grok.svg`      |
| `moonshot.svg`   | `ProviderIcon-kimi.svg`      |
| `openrouter.svg` | `ProviderIcon-openrouter.svg` |

Moonshot ships under its consumer product name Kimi. CodexBar's Moonshot
descriptor points at `ProviderIcon-kimi` for the same reason.

## What was changed

Only the wrapper, never the path data:

- hardcoded `fill="white"` / `fill="#FFFFFF"` replaced by `currentColor` on the
  root, so one file serves both the light and the dark theme;
- fixed `width`/`height` dropped so the call site picks the size;
- `<?xml?>` declarations, `<title>` elements and inline `style` removed;
- for `openrouter.svg`, the wrapping `<clipPath>` removed — its rect was the
  full viewBox, so it clipped nothing, and a repeated `id` on a page with
  several marks is a hazard for no benefit.

## Providers with no mark

`runpod` and `vast` are not in CodexBar's set. They stay on two-letter initials.
Do not substitute a drawing or fetch one from the web.

## Licensing

These are third-party trademarks, reproduced here nominatively: they identify
which provider a row belongs to and nothing more. Factory claims no ownership,
implies no affiliation, endorsement or sponsorship, and does not present them as
official brand assets. Each mark remains the property of its owner. If an owner
objects, delete the file — `providerIcon()` returns null for a missing file and
the affected rows fall back to initials on their own.

## Removed

- `aiand.svg` — the mark vendored from CodexBar was not ai&'s logo, and is
  wrong in CodexBar too. Removed rather than shipped wrong; aiand falls back to
  initials until a correct mark exists upstream.


## Machine marks

`jethas-mac-mini`, `stadia-testbed` and `thinkstationpgx-00b4` are marked by
what they run. Which host runs what is a local fact, not something the payload
reports, so the mapping lives in `provider_marks.dart` alongside the LAN
address. A host that is not listed gets a blank of the same width, never
initials — "TH" next to `thinkstationpgx-00b4` repeats the name and says
nothing.

| file          | source                                                          |
| ------------- | --------------------------------------------------------------- |
| `apple.svg`   | simple-icons, via `CodexBar/docs/images/apple.svg` already on disk |
| `debian.svg`  | simple-icons `icons/debian.svg`                                  |
| `nvidia.svg`  | simple-icons `icons/nvidia.svg`                                  |

simple-icons is CC0. All three were normalised the same way as the marks above:
`<title>` and root `fill`/`role` dropped, `fill="currentColor"` put on the root.

Brand colours come from simple-icons' published `data/simple-icons.json` — never
sampled from a screenshot or chosen by eye.

## Removed

- `devin.svg` — the file vendored from CodexBar is a generic cog-and-circle, not
  Cognition's mark for Devin. Devin falls back to `DE` until a correct mark
  exists. The same wrong file is still in CodexBar upstream; this is the second
  mark in that set found to be wrong, after `aiand`.
