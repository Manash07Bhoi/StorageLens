"""Analytics: aggregates computed from persisted inventory rows.

Grand totals are computed once from regular-file entries — never by summing
directory rollups (that would double-count descendants). Directory recursive
totals are accumulated bottom-up and stored in directory_stats.
"""

import json

from . import database

TOP_N = 25


def compute_directory_stats(conn, scan_id):
    """(Re)build directory_stats for a run. Derived data only; idempotent."""
    with conn:
        conn.execute("DELETE FROM directory_stats WHERE scan_id = ?", (scan_id,))

    rows = conn.execute(
        "SELECT relative_path, parent_relative_path, kind FROM entries"
        " WHERE scan_id = ? AND kind = 'directory'", (scan_id,)).fetchall()

    list_failed = {
        row["path"] for row in conn.execute(
            "SELECT DISTINCT path FROM scan_issues WHERE scan_id = ? AND operation = 'list'",
            (scan_id,)).fetchall()
    }

    direct_files = {}
    direct_dirs = {}
    direct_bytes = {}
    for row in conn.execute(
            "SELECT parent_relative_path, COUNT(*) AS n,"
            " COALESCE(SUM(size_bytes), 0) AS bytes"
            " FROM entries WHERE scan_id = ? AND kind = 'file' AND size_status = 'observed'"
            " GROUP BY parent_relative_path", (scan_id,)):
        direct_files[row["parent_relative_path"]] = int(row["n"])
        direct_bytes[row["parent_relative_path"]] = int(row["bytes"])
    for row in conn.execute(
            "SELECT parent_relative_path, COUNT(*) AS n FROM entries"
            " WHERE scan_id = ? AND kind = 'directory'"
            " GROUP BY parent_relative_path", (scan_id,)):
        direct_dirs[row["parent_relative_path"]] = int(row["n"])

    child_counts = conn.execute(
        "SELECT parent_relative_path, COUNT(*) AS n FROM entries"
        " WHERE scan_id = ? GROUP BY parent_relative_path", (scan_id,)).fetchall()
    child_count = {row["parent_relative_path"]: int(row["n"]) for row in child_counts}

    stats = {}
    depth_by_path = {}
    for row in conn.execute(
            "SELECT relative_path, depth FROM entries WHERE scan_id = ?"
            " AND kind = 'directory'", (scan_id,)):
        depth_by_path[row["relative_path"]] = row["depth"]

    for row in rows:
        rel = row["relative_path"]
        stats[rel] = {
            "direct_files": direct_files.get(rel, 0),
            "direct_dirs": direct_dirs.get(rel, 0),
            "recursive_files": direct_files.get(rel, 0),
            # recursive_dirs counts each descendant directory exactly once:
            # direct children contribute (their own recursive_dirs + 1).
            "recursive_dirs": 0,
            "recursive_file_bytes": direct_bytes.get(rel, 0),
            "is_empty": 1 if (child_count.get(rel, 0) == 0
                              and rel not in list_failed) else 0,
        }

    # Bottom-up accumulation: deepest directories first.
    order = sorted(stats, key=lambda p: depth_by_path[p], reverse=True)
    parent_of = {}
    for row in rows:
        parent_of[row["relative_path"]] = row["parent_relative_path"]

    for rel in order:
        parent = parent_of.get(rel)
        if parent and parent in stats:
            stats[parent]["recursive_files"] += stats[rel]["recursive_files"]
            stats[parent]["recursive_dirs"] += stats[rel]["recursive_dirs"] + 1
            stats[parent]["recursive_file_bytes"] += stats[rel]["recursive_file_bytes"]

    insert_rows = [
        (scan_id, rel, s["direct_files"], s["direct_dirs"], s["recursive_files"],
         s["recursive_dirs"], s["recursive_file_bytes"], s["is_empty"])
        for rel, s in stats.items()
    ]
    if insert_rows:
        with conn:
            conn.executemany(
                "INSERT INTO directory_stats(scan_id, relative_path, direct_files,"
                " direct_dirs, recursive_files, recursive_dirs,"
                " recursive_file_bytes, is_empty) VALUES (?,?,?,?,?,?,?,?)",
                insert_rows)
    return len(insert_rows)


def run_overview(conn, scan_id):
    """Headline metrics for a run. All values come from the database."""
    row = conn.execute(
        "SELECT COUNT(*) AS total_entries,"
        " SUM(CASE WHEN kind='file' AND stat_status='ok' THEN 1 ELSE 0 END) AS files_ok,"
        " SUM(CASE WHEN kind='file' THEN 1 ELSE 0 END) AS files_all,"
        " SUM(CASE WHEN kind='directory' THEN 1 ELSE 0 END) AS directories,"
        " SUM(CASE WHEN kind='symlink' THEN 1 ELSE 0 END) AS symlinks,"
        " SUM(CASE WHEN kind IN ('other','unknown') THEN 1 ELSE 0 END) AS other_entries,"
        " SUM(CASE WHEN is_hidden=1 THEN 1 ELSE 0 END) AS hidden_entries,"
        " SUM(CASE WHEN kind='file' AND stat_status='ok' AND size_bytes=0 THEN 1 ELSE 0 END)"
        "   AS zero_byte_files,"
        " SUM(CASE WHEN stat_status='failed' THEN 1 ELSE 0 END) AS failed_entries,"
        " SUM(CASE WHEN kind='file' AND size_status='observed' THEN size_bytes ELSE 0 END)"
        "   AS inventoried_file_bytes,"
        " SUM(CASE WHEN skip_reason IS NOT NULL THEN 1 ELSE 0 END) AS skipped_entries"
        " FROM entries WHERE scan_id = ?", (scan_id,)).fetchone()

    issues = conn.execute(
        "SELECT COUNT(*) FROM scan_issues WHERE scan_id = ?", (scan_id,)).fetchone()[0]
    hidden_files = conn.execute(
        "SELECT COUNT(*) FROM entries WHERE scan_id = ? AND kind='file' AND is_hidden=1",
        (scan_id,)).fetchone()[0]
    hidden_dirs = conn.execute(
        "SELECT COUNT(*) FROM entries WHERE scan_id = ? AND kind='directory' AND is_hidden=1",
        (scan_id,)).fetchone()[0]
    unavailable_sizes = conn.execute(
        "SELECT COUNT(*) FROM entries WHERE scan_id = ? AND kind='file'"
        " AND size_status IN ('unavailable','failed')", (scan_id,)).fetchone()[0]

    return {
        "total_entries": int(row["total_entries"] or 0),
        "files_inventoried": int(row["files_ok"] or 0),
        "files_including_failed": int(row["files_all"] or 0),
        "directories": int(row["directories"] or 0),
        "symlinks": int(row["symlinks"] or 0),
        "other_entries": int(row["other_entries"] or 0),
        "hidden_entries": int(row["hidden_entries"] or 0),
        "hidden_files": int(hidden_files),
        "hidden_directories": int(hidden_dirs),
        "zero_byte_files": int(row["zero_byte_files"] or 0),
        "failed_entries": int(row["failed_entries"] or 0),
        "skipped_entries": int(row["skipped_entries"] or 0),
        "unavailable_size_files": int(unavailable_sizes),
        "issues": int(issues),
        "inventoried_file_bytes": int(row["inventoried_file_bytes"] or 0),
    }


def category_breakdown(conn, scan_id):
    rows = conn.execute(
        "SELECT category, COUNT(*) AS n,"
        " COALESCE(SUM(CASE WHEN size_status='observed' THEN size_bytes END), 0) AS bytes"
        " FROM entries WHERE scan_id = ? AND kind = 'file' AND stat_status = 'ok'"
        " GROUP BY category ORDER BY bytes DESC, category ASC", (scan_id,)).fetchall()
    return [{"category": r["category"], "files": int(r["n"]),
             "bytes": int(r["bytes"])} for r in rows]


def extension_breakdown(conn, scan_id, limit=None):
    sql = ("SELECT COALESCE(extension, '(none)') AS ext, COUNT(*) AS n,"
           " COALESCE(SUM(CASE WHEN size_status='observed' THEN size_bytes END), 0) AS bytes"
           " FROM entries WHERE scan_id = ? AND kind = 'file' AND stat_status = 'ok'"
           " GROUP BY ext ORDER BY n DESC, ext ASC")
    rows = conn.execute(sql, (scan_id,)).fetchall()
    result = [{"extension": r["ext"], "files": int(r["n"]), "bytes": int(r["bytes"])}
              for r in rows]
    return result[:limit] if limit else result


def largest_files(conn, scan_id, limit=TOP_N):
    rows = conn.execute(
        "SELECT name, relative_path, extension, category, size_bytes, mtime_iso"
        " FROM entries WHERE scan_id = ? AND kind = 'file' AND stat_status = 'ok'"
        " ORDER BY size_bytes DESC, relative_path ASC LIMIT ?",
        (scan_id, int(limit))).fetchall()
    return [dict(r) for r in rows]


def largest_directories(conn, scan_id, limit=TOP_N):
    rows = conn.execute(
        "SELECT d.relative_path, d.recursive_file_bytes, d.recursive_files,"
        " d.recursive_dirs, d.direct_files"
        " FROM directory_stats d JOIN entries e"
        "   ON e.scan_id = d.scan_id AND e.relative_path = d.relative_path"
        " WHERE d.scan_id = ? AND e.kind = 'directory'"
        " ORDER BY d.recursive_file_bytes DESC, d.relative_path ASC LIMIT ?",
        (scan_id, int(limit))).fetchall()
    return [dict(r) for r in rows]


def largest_hidden(conn, scan_id, limit=TOP_N):
    dirs = conn.execute(
        "SELECT d.relative_path, d.recursive_file_bytes, d.recursive_files"
        " FROM directory_stats d JOIN entries e"
        "   ON e.scan_id = d.scan_id AND e.relative_path = d.relative_path"
        " WHERE d.scan_id = ? AND e.kind='directory' AND e.is_hidden=1"
        " ORDER BY d.recursive_file_bytes DESC LIMIT ?",
        (scan_id, int(limit))).fetchall()
    files = conn.execute(
        "SELECT name, relative_path, size_bytes FROM entries"
        " WHERE scan_id = ? AND kind='file' AND is_hidden=1 AND stat_status='ok'"
        " ORDER BY size_bytes DESC LIMIT ?", (scan_id, int(limit))).fetchall()
    return ([dict(r) for r in dirs], [dict(r) for r in files])


def empty_directories(conn, scan_id):
    rows = conn.execute(
        "SELECT e.relative_path FROM entries e JOIN directory_stats d"
        "  ON d.scan_id = e.scan_id AND d.relative_path = e.relative_path"
        " WHERE e.scan_id = ? AND e.kind = 'directory' AND d.is_empty = 1"
        " ORDER BY e.relative_path", (scan_id,)).fetchall()
    return [r["relative_path"] for r in rows]


def zero_byte_files(conn, scan_id):
    rows = conn.execute(
        "SELECT name, relative_path FROM entries"
        " WHERE scan_id = ? AND kind = 'file' AND stat_status = 'ok' AND size_bytes = 0"
        " ORDER BY relative_path", (scan_id,)).fetchall()
    return [dict(r) for r in rows]


def review_candidates(conn, scan_id, limit=50):
    """Neutral observations only — NOT claims that files are junk.

    Buckets: very large files, very old large files, unusual extensions.
    """
    candidates = []
    for r in largest_files(conn, scan_id, limit=limit):
        if r["size_bytes"] and r["size_bytes"] >= 100 * 1024 * 1024:  # >=100 MiB
            candidates.append({
                "relative_path": r["relative_path"],
                "size_bytes": r["size_bytes"],
                "observation": "large file (≥ 100 MiB)",
            })
    old_rows = conn.execute(
        "SELECT relative_path, size_bytes, mtime_epoch FROM entries"
        " WHERE scan_id = ? AND kind='file' AND stat_status='ok'"
        "   AND mtime_epoch IS NOT NULL AND size_bytes >= 10*1024*1024"
        "   AND mtime_epoch < CAST(strftime('%s','now','-5 years') AS INTEGER)"
        " ORDER BY size_bytes DESC LIMIT ?", (scan_id, int(limit))).fetchall()
    for r in old_rows:
        candidates.append({
            "relative_path": r["relative_path"],
            "size_bytes": r["size_bytes"],
            "observation": "not modified in over 5 years (≥ 10 MiB)",
        })
    return candidates


def same_size_candidates(conn, scan_id, limit=100):
    """Files sharing a size: candidates for review, never proof of duplication."""
    rows = conn.execute(
        "SELECT size_bytes, COUNT(*) AS n FROM entries"
        " WHERE scan_id = ? AND kind='file' AND stat_status='ok' AND size_bytes > 0"
        " GROUP BY size_bytes HAVING n > 1"
        " ORDER BY n DESC, size_bytes DESC LIMIT ?", (scan_id, int(limit))).fetchall()
    groups = []
    for r in rows:
        files = conn.execute(
            "SELECT relative_path FROM entries WHERE scan_id = ? AND kind='file'"
            " AND size_status='observed' AND size_bytes = ? ORDER BY relative_path LIMIT 20",
            (scan_id, r["size_bytes"])).fetchall()
        groups.append({
            "size_bytes": int(r["size_bytes"]),
            "count": int(r["n"]),
            "sample_paths": [f["relative_path"] for f in files],
        })
    return groups


def issues_breakdown(conn, scan_id):
    rows = conn.execute(
        "SELECT operation, error_category, COUNT(*) AS n FROM scan_issues"
        " WHERE scan_id = ? GROUP BY operation, error_category"
        " ORDER BY n DESC", (scan_id,)).fetchall()
    return [{"operation": r["operation"], "error_category": r["error_category"],
             "count": int(r["n"])} for r in rows]


def issue_listing(conn, scan_id, limit=1000):
    rows = conn.execute(
        "SELECT path, operation, error_category, error_code, error_message"
        " FROM scan_issues WHERE scan_id = ? ORDER BY id LIMIT ?",
        (scan_id, int(limit))).fetchall()
    return [dict(r) for r in rows]


def run_record(conn, run_id):
    row = database.get_run(conn, run_id)
    if row is None:
        return None
    data = dict(row)
    try:
        data["environment"] = json.loads(data.get("environment_json") or "{}")
    except json.JSONDecodeError:
        data["environment"] = {}
    try:
        data["exclusions"] = json.loads(data.get("exclusions_json") or "[]")
    except json.JSONDecodeError:
        data["exclusions"] = []
    return data
