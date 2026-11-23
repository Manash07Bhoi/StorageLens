# Comprehensive Gap Register (V1 + V2 M1)

Severity: Critical/High/Medium/Low. Status: PASS (closed+verified) · PARTIAL ·
OPEN · BLOCKED · NOT TESTED. Original 1.0.0 register items are carried over with
current state. Newly discovered items are suffixed V2.

| ID | Module | Requirement / Gap | Severity | Root cause | Impact | Correction / status |
|---|---|---|---|---|---|---|
| G-001 | Device | On-device Android validation of V1/V2 | High | No device access from agent | Unproven on target platform | BLOCKED — user-run retest plan in ANDROID_TERMUX_GUIDE; execution evidence still pending |
| G-002 | Report | Charts/metrics render without data sanity warnings in all viewports | Medium | visual only | cosmetic | PASS (fixture + static checks); phone manual check pending |
| G-005 | Report | No browser-automation viewport/a11y tests | Medium | no automation | UX risk small | PARTIAL — manual checklist (V2_UI_VALIDATION.md); AT not audited |
| G-006 | Android | `Android/data`, `Android/obb` untraversable | Medium | scoped storage (platform) | inventory ends at those two dirs | OPEN — documented; by design; report labels boundary |
| G-007 | Report | files.html inline dataset not machine-verifiable without running JS | Low | design (perf choice) | audit friction | PARTIAL — exports.xlsx-free JSONL is the machine-readable path; verified |
| G-101 | V1 scan | Issue taxonomy: mount boundary labelled "containment" | Medium | wrong operation string | misread coverage note | **FIXED v1.0.1** (operation=mount_boundary; precise coverage notes); on-device revalidation NOT TESTED |
| G-102 | V1 docs | Docs claimed "110 tests" (actual grew) | Low | test additions | stale docs | FIXED — all docs reference 157 (v2.1.0) |
| G-V2-001 | V2 engine | Free-space precheck over-reserved (1 MiB × N files) | Medium | wrong model | false refusal on small trees | FIXED (payload + 64 MiB); test added; caught by benchmark |
| G-V2-002 | V2 engine | Dest vanish/appear races remain path-based (no dirfd API) | Low | platform limits | theoretical overwrite window | MITIGATED — execution-time lexists re-check + verify; documented in PATH_SECURITY_VALIDATION.md |
| G-V2-003 | V2 preview | No column sorting; AT not audited; large-plan density | Low | M1 scope | usability | OPEN — M3 enhancement; not a defect for M1 |
| G-V2-004 | V2 | Move across mounts is copy+remove; no fs journaling (ext4/F2FS) | Low | no fsync-dir on all ROMs | crash mid-move loses copy record | MITIGATED — per-op fsync of file; dst preserved on failure; undo fallback copy-verify-delete |
| G-V2-005 | V2 | v1→v2 migration not run on the real phone DB yet | Medium | no access | unknown device migration behavior | NOT TESTED — migration tested on synthetic v1 fixture only; device backup advice in guide |
| G-V2-006 | Publication | Private ZIP uploaded to public repo (user action) | **Critical** | manual web upload by owner | private inventory exposed ~1h | **CLOSED 2026-11-23** — removed from tree + history rewritten (owner-authorized); GitHub CDN cache may persist (see PUBLICATION_PRIVACY_AUDIT.md); backup retained privately |
| G-V2-007 | Publication | Repo history contained ZIP until rewrite | High | same incident | exposure in unreachable-but-cached objects | CLOSED — filter-branch prune, force-push, verified unreachable; cache caveat documented |
| G-V2-008 | Publication | Local agent backup holds the ZIP (by design) | Low | recovery backup requirement | private artifact on agent host | OPEN — retained at /home/user/private_storagelens_report/ by owner's explicit instruction; owner to decide deletion |
| G-V2-009 | V2 perf | No on-device V2 timings | Medium | no device | unknown real-world apply time | NOT TESTED |
| G-V2-010 | V1 scan | Coverage note wording before v1.0.1 on old runs stays | Low | immutable history | old reports say "2 containment" | ACCEPTED — documentation; new scans precise; report regeneration does not relabel immutable rows |
| G-V2-011 | SECURITY.md | Security policy lacked V2 engine invariants | Low | doc drift | incomplete guidance | FIXED — SECURITY.md updated for V2 invariants |
| G-V2-012 | CI | No automated CI running tests | Low | no CI in repo | regressions rely on manual runs | OPEN — documented; tests run locally pre-push; CI optional for M2 |
| G-V2-013 | V2 scope | **BLOCKER CLASS: planner used whole-scan sources; entire shared-storage root organizable** (would organize Android/media and all other accessible content) | High | candidates came from the V1 scan, not an approved selection | Android/ + ordinary content could be planned | **CLOSED v2.1.0** — org-scope-1: explicitly selected, validated user-owned folder only; fresh lstat walk; default-deny recursion; execution-time revalidation; 20 mandatory security tests; ORGANIZATION_SCOPE_SECURITY_TESTS.md |

**Counts:** Critical 1 (G-V2-006, closed) · High 2 (1 closed, G-001 open/blocked) ·
Medium 7 (2 fixed, rest open/NOT TESTED) · Low 9 (mixed fixed/open/accepted).

**Release posture v2.1.0:** no open Critical/High code defects. org-scope-1 enforcement added (v2.1.0) closing G-V2-013.
G-001 (device validation) blocks any claim of Android-readiness; V2 remains a
host-validated release with device steps documented.
