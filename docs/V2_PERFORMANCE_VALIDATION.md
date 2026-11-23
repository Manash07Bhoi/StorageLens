# V2 Performance Validation

Host under test: Linux x86_64 agent container (Intel Xeon 2.60 GHz, 2 cores,
1,982 MiB), Python 3.13.18, ext4/overlayfs, warm cache. **No Android numbers
exist yet.** Synthetic 1,500-file tree (13 categories, files 200 B–20 KB,
fixture generator seed 42). Wall = subprocess end-to-end including interpreter
startup; RSS via getrusage(RUSAGE_CHILDREN) peak.

| Step | Wall | Result |
|---|---|---|
| scan 1,500 files | 0.23 s | 8,586 entries inventoried (fixture incl. dirs) |
| organize-plan | 0.14 s | 1,500 ops, 15.28 MB planned, 0 conflicts |
| organize-preview | 0.15 s | ~12–40 KB HTML |
| organize-approve | 0.12 s | gate only |
| organize-apply (copy-keep) | 0.67 s | 1,500/1,500 done, 0 failed, payload 15.28 MB ≈ 23 MB/s incl. fsync |
| peak child RSS (any step) | 24,212 KiB | bounded (no whole-tree model) |

V1 reference (same session family): 10,000-file fixture scan 0.65 s (~18k
entries/s), report build 1.15 s, peak RSS 69.6 MiB, DB 6.01 MiB (see
docs/PERFORMANCE.md).

## Android 15 / Termux deltas expected (NOT measured)
- Flash speed & FUSE layer will dominate; expect 2–10× slower metadata, plus
  seccomp/permission checks. Do not quote any host number as a device number.
- battery/termux-wake-lock considerations for >100k-file trees.

## Budgets (targets for M2 on-device validation)
scan ≤ 1 h/TB-ish on mid-range hardware is not asserted yet; to be measured.
Apply ≤ copied-bytes / flash-bandwidth + fsync overhead; no claim made.

## Methodology honesty
- No phone was touched by these measurements.
- Sparse/large files intentionally excluded from V2 copy timings (they would
  dominate I/O; V1 sparse-read benchmark covers metadata only).
- First `organize-apply` measurement failed with a false "insufficient space"
  refusal (1 MiB/file slack bug). Root-caused, fixed (payload + fixed 64 MiB
  headroom), re-measured, and now covered by `test_insufficient_space_*`.
  Recorded here as an example of measurement-before-claims working.
