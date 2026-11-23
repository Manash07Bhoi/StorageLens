# V2 Design System — StorageLens Premium Dark

Design language shared by the V1 report and the V2 plan preview. Material-3
principles, dark-first, offline, phone-first.

## Tokens
| Purpose | Value |
|---|---|
| background | `#0A0A0F` |
| background (secondary) | `#0B0D0F` |
| surface | `#15191D` |
| surface-elevated | `#1B2127` |
| border | `#262E36` |
| primary accent | `#F97316` (orange) |
| secondary accent | `#F5B942` (gold) |
| text | `#F5F5F5` |
| text-muted | `#A9B4BD` |
| success | `#34D399` |
| warning | `#FBBF24` |
| danger | `#F87171` |

## Rules honoured in delivered UI (report + plan preview)
- Semantic headings/landmarks; skip is not needed for single-screen preview;
  the V1 report carries skip links.
- Contrast: text on surfaces ≥ 7:1 for body; muted ≥ 4.5:1; accents used for
  emphasis only, never as sole status signal.
- Touch targets ≥ 44 px; focus-visible outlines (gold, 3 px).
- `prefers-reduced-motion` respected (no animations ship in M1).
- Monospace for paths/sizes; word-break for long paths; no hover-only actions.
- Empty/error states are factual ("0 of N operations", "No database yet…").
- No decorative controls. Every button/link in delivered pages performs its
  label (filter, paginate, navigate). Static preview has no fake action buttons.
- Top-N lists are labelled as such ("top 25"); counts come from the DB.

## V2 preview screen inventory
1. Header (plan id, scan id, rule, action, generated-locally note).
2. Metric cards (operations, total size, move ops, conflicts, plan status).
3. Banners (destructive-move warning; skipped-sources; how-to-approve).
4. Filter toolbar (search / status+action filter / rows-per-page).
5. Operations table (seq, action tag, src→dst wrapped, size, status tag).
6. Pager (prev/next, "Page X / Y", live record count).
7. Target root + event log (latest 200).
8. Privacy notice.

## Rejected alternatives
- Light-first theme: worse for a phone-at-night tool, more battery cost on OLED.
- Chart library: any chart that can't be fed by real DB rows is a fake; none
  ship in M1 beyond V1's data-driven charts.
- Inline SVG icon set: limited to status dots/tags; full iconography deferred
  to M3 to avoid decoration that doesn't function.
