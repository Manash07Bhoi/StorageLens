# Final Acceptance Matrix (v2.2.0, 2026-11-23 — supersedes v2.0.0/v2.1.0)

Gate keys: PASS = evidence exists · PARTIAL = delivered with caveats ·
BLOCKED = needs device/owner · NOT TESTED = never executed · FAIL = broken.

| Gate | Requirement | Status | Evidence |
|---|---|---|---|
| A | Original V1 requirements satisfied or accurately blocked | PARTIAL | matrices TRACEABILITY_*; phone gate blocked (A-device) — everything else evidenced |
| B | Android scan defects investigated and corrected | PASS | forensic audit; v1.0.1 taxonomy fix; revalidation NOT TESTED (device) |
| C | Conditional logic / branch validation | PASS (host) / NOT TESTED (device) | 201 tests; cancel/vanish/permission/mount/scope branches incl. alias/registry/boundary audit (v2.2.0) |
| D | Filesystem & path security | PASS (host) | PATH_SECURITY_VALIDATION.md; containment/TOCTOU/symlink suites; device NOT TESTED |
| E | Database & export integrity | PASS | DATABASE_INTEGRITY_AUDIT.md; migration fresh+v1→v2; exports reconciled (3 passes) |
| F | V1 regression suite | PASS | 201/201 tests incl. frozen V1 suite on release commits |
| G | V2 architecture & state machines | PASS | V2_* design docs; machines implemented & tested on synthetic fixtures |
| H | Organization safety invariants | PASS (host) / NOT TESTED (device) | 85 organization tests (23 organizer + 21 scope-security + 41 scope-hardening) + 3 CLI registration tests; failure matrix; org-scope-2 (v2.2.0); v2.1.0 NOT accepted → corrected in v2.2.0; device NOT TESTED |
| I | UI functionality & accessibility | PARTIAL | offline-verified preview/report; browser automation & AT NOT TESTED; manual checklists done |
| J | Android performance & stability | NOT TESTED | host benchmarks only (V2_PERFORMANCE_VALIDATION.md) |
| K | Privacy & public repository audit | PASS | PUBLICATION_PRIVACY_AUDIT.md; incident closed (cache caveat disclosed) |
| L | Documentation & release evidence | PASS | this set + README/CHANGELOG/FINAL_AUDIT synced; claims bounded to evidence |

**Release decision:** v2.2.0 is a **public source release**, explicitly
labelled *host-validated; on-device validation pending*. v2.1.0 was NOT
accepted and is superseded. No claim of Android-ready, no claim of
production-ready-for-phone until Gate J and device-side Gates B/C/D/H are
executed on the Android 15 device with documented output. Critical defects
open: 0. Open High: 1 (G-001, blocked device validation — not a code
defect). Open Medium: recorded in COMPREHENSIVE_GAP_REGISTER.md with
impacts; none are silent.

**Fresh evidence index:** pulled at release time — 201 tests OK; fresh
public-clone verification recorded in FINAL_AUDIT.md v2.2.0 addendum (as was
done for v2.1.0) after the release push.
