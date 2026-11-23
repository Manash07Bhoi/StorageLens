# Report / Export Reconciliation — Evidence

Three independent verification passes were executed and reconciled.

## Pass 1 — Synthetic fixture (dev host, fresh HOME), run 1
Manifest hashes 8/8 PASS · files.csv 5 rows = DB · directories 5 = DB ·
entries.jsonl 11 rows, scan_id={1} · byte sum 3,110 = DB · issues 0 = DB ·
static pages correct · 0 external URLs in report. (V1 acceptance smoke)

## Pass 2 — Real device artifact (Android 15 zip, extracted privately, counts only)
See V1_ANDROID_FORENSIC_AUDIT.md for the full table:
manifest 8/8 · files.csv 8584 · directories.csv 165 · entries.jsonl 8749
scan_id={1} · bytes 45,482,162,920 · file_types Σ both views = 8584/45,482,162,920 ·
tree 8749 lines · 18 static pages reconcile to 8584 file rows · INCOMPLETE
banner present · 0 external URLs · exports README + manifest legend present ·
issues rows = 2 = skipped entries = 2 (same two FUSE mounts). **All PASS.**

## Pass 3 — V2 plan preview (synthetic)
1500 operations embedded; page count = ceil(1500/250)=6; zero external refs;
escaped JSON; status tags render planned/conflict correctly; INCOMPLETE-style
privacy footer present. Manual open on Android: NOT TESTED.

## Pagination & row-exactness math (static pages)
`17 pages × 501 <tr> + 1 page × 85 = 8,602`; each page carries exactly one
`<thead>` row ⇒ 8,584 file rows total = inventory files. Consistent with the
8,749-row inline inventory (files + directories + symlinks/other). Verified
programmatically from the extracted phone artifact.

## Consistency across terminal / DB / exports / report
Verified identical numbers in: terminal output (screenshots), exports summary.md,
manifest.json, CSV/JSONL row counts, index.html banner, list-runs output shape.
`list-runs` and `show-run` format counters from the same DB queries.

## Formula-injection & encoding
- CSV: UTF-8 with BOM; leading `= + - @ TAB CR` cells prefixed with `'`;
  formula-prefixed names in fixtures verified to neutralize.
- JSONL: raw values preserved unmodified (spec-compliant).
- HTML: entity-escaped; script-unsafe JSON chars escaped (U+2028/2029 too).
- Tree: control chars escaped (`\n`, `\t`, `\xNN`); chunking + index for >8 MiB.

## Non-verified / not executed
- Byte-level hash check of the phone's own rerun after v1.0.1 (device task).
- files.html inline dataset parse by a real browser (manual; NOT TESTED).
