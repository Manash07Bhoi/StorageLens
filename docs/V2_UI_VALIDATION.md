# V2 UI Validation — Plan Preview & Report Surfaces

Legend: ✔ verified · M manual/checklist · ∅ not tested

## Plan preview (`plan_<id>.html`)
| Check | Result | Evidence |
|---|---|---|
| Renders offline, no network refs | ✔ | regex sweep: 0 external src/href/action |
| Valid UTF-8, single file | ✔ | generated file (11,763 B smoke; scales with ops) |
| Data embedded escaped | ✔ | U+2028/2029 + <>& escaped; fixture with `<script>` name rendered harmlessly |
| Organization-scope panel rendered | ✔ | selected folder, canonical path, policy org-scope-1, eligible/excluded counters, reason histogram, per-check validation table, hard-boundary banner; 0 external refs verified |
| Search filters rows live | ✔ | JS inspection (input listeners wired to OPS array) |
| Pagination correct at boundaries | ✔ | 6 pages @250 for 1500 ops; prev/next disable logic; record count text updates |
| Conflict rows visually distinct | ✔ M | warning tag color; legend via banner |
| Move plans carry red banner | ✔ | move case in preview smoke (move plan fixture) |
| Contrast (text/surface) | ✔ M | ≥7:1 body pairs by token; muted ≥4.5:1 |
| Focus visible | ✔ M | :focus-visible outline gold, 3px |
| Touch targets ≥44px | ✔ M | buttons/inputs 44px min |
| Long paths wrap, no layout break | ✔ M | .path word-break |
| Reduced motion respected | ✔ M | media query present; no animations ship |
| Empty state | ✔ | "0 of N operations shown", reset via filter clear |
| No nonfunctional controls | ✔ M | every button wired (prev/next/filters) |
| Screen-reader landmarks | ∅ | table has aria-describedby; nav landmarks not audited with AT |
| Browser automation | ∅ | none performed (no Playwright/device browser drive) |
| Opening on Android browser | ∅ | file copied to phone not exercised by agent |

## V1 report re-verification (phone-generated artifact)
31 pages parsed OK · 0 external refs · escaping OK · banner present ·
pagination math exact (see REPORT_EXPORT_RECONCILIATION.md) ✔.

## Known UX debt (honest)
- Preview is information-dense at >250 ops/page; M3 wants per-folder grouping.
- No column sort in M1 preview (filter + search only) — deliberate; sort would
  duplicate sort keys already in DB; tracked as M3 enhancement, not a defect.
- No dark/light toggle (dark-first is the product choice).
