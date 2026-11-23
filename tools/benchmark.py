#!/usr/bin/env python3
"""Measure Android Storage Audit performance on this host.

Builds a synthetic fixture tree (never the real phone storage), scans it,
and prints wall time, throughput, peak RSS, database size and report size.

Usage:
    python3 tools/benchmark.py [--files N] [--keep]

Numbers are valid ONLY for the machine that runs this script. They are
never extrapolated to phones.
"""

import argparse
import os
import resource
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage_audit import database, scanner  # noqa: E402
from storage_audit.report_builder import build_report  # noqa: E402


def build_fixture(root, count):
    os.makedirs(root, exist_ok=True)
    width = 40  # entries per directory level
    made = 0
    index = 0
    exts = ["jpg", "png", "mp4", "mp3", "pdf", "txt", "zip", "bin", "py", "apk"]
    while made < count:
        d1 = os.path.join(root, "level1_{:02d}".format(index % width))
        d2 = os.path.join(d1, "level2_{:02d}".format((index // width) % width))
        os.makedirs(d2, exist_ok=True)
        name = "file_{:06d}.{}".format(made, exts[made % len(exts)])
        payload = bytes((made * 2654435761) % 251 for _ in range(0))  # tiny content
        with open(os.path.join(d2, name), "wb") as fh:
            fh.write(payload if made % 7 else b"x" * 1024)
        made += 1
        index += 1
    # A handful of empty dirs and one 256 MiB sparse file for realism.
    for n in range(10):
        os.makedirs(os.path.join(root, "empty_{:02d}".format(n)), exist_ok=True)
    sparse = os.path.join(root, "level1_00", "sparse.bin")
    with open(sparse, "wb") as fh:
        fh.truncate(256 * 1024 * 1024)
    return root


def dir_bytes(path):
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for name in files:
            total += os.path.getsize(os.path.join(dirpath, name))
    return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", type=int, default=10000)
    parser.add_argument("--keep", action="store_true", help="keep the fixture and outputs")
    args = parser.parse_args()

    tmp = tempfile.mkdtemp(prefix="audit_bench_")
    fixture = os.path.join(tmp, "phone")
    db = os.path.join(tmp, "bench.sqlite3")
    out = os.path.join(tmp, "out")

    print("Building fixture with {} files under {} ...".format(args.files, fixture))
    t0 = time.time()
    build_fixture(fixture, args.files)
    fixture_build_s = time.time() - t0

    fixture_bytes = dir_bytes(fixture)
    print("Fixture built in {:.1f}s; on-disk bytes: {}".format(
        fixture_build_s, fixture_bytes))

    t0 = time.time()
    result = scanner.run_scan(fixture, db_path=db, output_dir=out, progress=False)
    scan_s = time.time() - t0

    conn = database.connect(db)
    try:
        entries = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE scan_id = ?",
            (result["run_id"],)).fetchone()[0]
        observed_bytes = conn.execute(
            "SELECT COALESCE(SUM(size_bytes), 0) FROM entries"
            " WHERE scan_id = ? AND kind = 'file' AND stat_status = 'ok'",
            (result["run_id"],)).fetchone()[0]
    finally:
        conn.close()
    gib = observed_bytes / (1024**3)

    print("Scan status: {}".format(result["status"]))
    print("Scan wall time: {:.2f}s".format(scan_s))
    print("Entries inventoried: {}".format(entries))
    print("Files: recorded={} seen={}".format(
        result["files_recorded"], result["files_seen"]))
    print("Observed file bytes: {:.3f} GiB".format(gib))
    if scan_s > 0:
        print("Throughput: {:.0f} entries/s, {:.1f} MiB/s (logical bytes)".format(
            entries / scan_s, gib * 1024 / scan_s))

    t0 = time.time()
    conn = database.connect(db)
    try:
        report = build_report(conn, result["run_id"], out, fixture_label=True)
    finally:
        conn.close()
    report_s = time.time() - t0
    report_dir = report["report_dir"]
    report_bytes = sum(
        os.path.getsize(os.path.join(d, f))
        for d, _dirs, files in os.walk(report_dir) for f in files)
    db_bytes = os.path.getsize(db)
    peak_rss_mib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0

    print("Report build time: {:.2f}s".format(report_s))
    print("Database size: {:.2f} MiB".format(db_bytes / 1024**2))
    print("Report size (all pages + exports): {:.2f} MiB".format(report_bytes / 1024**2))
    print("Peak RSS (this process): {:.1f} MiB".format(peak_rss_mib))
    print("Report directory: {}".format(report_dir if args.keep else "(temporary, removed)"))

    if not args.keep:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
