# Performance Measurement Report

**These numbers were measured on the development host only — never on an
Android device.** They are not extrapolated to phones. Your phone will be
slower or faster depending on flash storage, chipset, Android version, and
the size of your shared storage. Treat the method (`tools/benchmark.py`),
not the absolute figures, as the reusable artifact.

## Environment (measurement host)

| | |
|---|---|
| Date | 2026-11-23 |
| OS | Linux x86_64 development container (not Android, not Termux) |
| CPU | Intel Xeon Processor @ 2.60GHz, 2 cores |
| Memory | 1,982 MiB total |
| Python | 3.13.18 |
| Storage | host filesystem (ext4/overlay, warm cache) |

## Benchmark fixture (synthetic — never the real phone)

Built by `tools/benchmark.py`: a nested directory hierarchy containing
**10,000 files**, 10 empty directories, and one 256 MiB sparse file. The
fixture totals ~270 MB on disk (~0.25 GiB logical file bytes). Fixture
generation and scanning happen in a temporary directory, deleted
afterwards.

## Measured results (this host)

| Metric | Measured |
|---|---|
| Fixture build time | 0.2 s |
| Scan status | `completed` |
| **Scan wall time** | **0.65 s** |
| Entries inventoried (files + dirs + symlinks) | 11,652 |
| Files recorded / seen | 10,001 / 10,001 |
| Observed file bytes (logical) | 0.251 GiB (~269.9 MB, dominated by the 256 MiB sparse file) |
| **Scan throughput** | **~18,000 entries/s**, ~399 MiB/s logical (warm cache) |
| Report build time | 1.15 s |
| SQLite database size after scan + stats | 6.01 MiB |
| Report size (all HTML pages + exports) | 19.58 MiB |
| **Peak RSS (benchmark process)** | **69.6 MiB** |

## What this shows and what it does not

**Shows:** on this host, 11k entries are inventoried in under a second,
memory use stays modest regardless of file count (batched commits, streaming
traversal), and report generation is roughly the same order of magnitude as
the scan itself.

**Does not show:** anything about a physical Android phone. Flash I/O
latency on phones (especially with scoped-storage indirection) is typically
the dominant cost, and this host's page cache made file opens nearly free.
A 100,000-file shared storage on a mid-range phone could take minutes, not
milliseconds. **Do not quote the 18k entries/s figure as an Android
expectation.**

## Known performance characteristics (by design)

- Traversal is iterative (`os.scandir` stack), constant-ish memory; no
  recursion, no pathological nesting blowups.
- DB inserts are batched (default 500; configurable 50–5000) inside
  transactions with WAL mode and `synchronous=FULL`.
- Full-inventory search data is embedded inline only up to 30,000 entries;
  beyond that, `data/inventory_NNN.js` chunks (4,000 entries/chunk) keep the
  main page small. Static paginated tables are always generated.
- `directory_stats` are recomputed from scratch per export/report — fine at
  V1 scale, O(entries).
- The report HTML embeds all inventory metadata (names!) inline in JSON;
  large phones produce large pages but no per-file network requests (there
  is no network at all).

## How to reproduce

```sh
python3 tools/benchmark.py --files 10000
# or keep outputs for inspection:
python3 tools/benchmark.py --files 20000 --keep
```

## On-device measurement procedure (to be run on the phone; NOT DONE YET)

1. `termux-setup-storage`, confirm `~/storage/shared` is listable.
2. `bash run_audit.sh check` — note free space and volume values it prints.
3. `time bash run_audit.sh scan` — record wall time.
4. `bash run_audit.sh show-run 1` — record counters.
5. Record: database size (`ls -lh` on the `.sqlite3`), report directory size
   (`du -sh`), and the phone model/Android version/Termux version.
6. Add the numbers to this file under an "Android device results" heading —
   do not average them with this host's numbers.

**Until step 1–6 happen, treat all performance claims as development-host
measurements only.**
