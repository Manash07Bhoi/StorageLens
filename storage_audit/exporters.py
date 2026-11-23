"""Export generation: CSV, JSONL, tree, summary, manifest. Atomic writes.

All exports are generated from one scan run and reconcile to it. CSV cells
that could trigger spreadsheet formula evaluation are prefixed with a single
quote (documented; the database keeps raw values; JSONL always carries raw
values). CSV files are written as UTF-8 with a BOM for spreadsheet
compatibility; JSON/JSONL/Markdown/tree are plain UTF-8 without BOM.
"""

import csv
import hashlib
import io
import json
import os
import time
from datetime import datetime

from . import __version__, SCHEMA_VERSION, JSONL_SCHEMA_VERSION, config
from .analytics import (
    category_breakdown,
    compute_directory_stats,
    extension_breakdown,
    run_overview,
    run_record,
)

CSV_BOM = "utf-8-sig"
CSV_PLAIN = "utf-8"

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe_cell(value):
    """Return a spreadsheet-safe representation of one cell.

    - Non-strings pass through (numbers/None stay typed).
    - Cells whose first character is a formula trigger are prefixed with '.
    The stored/raw value is preserved in the database and in JSONL.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        return value
    if value and value[0] in _FORMULA_PREFIXES:
        return "'" + value
    return value


def _write_text_atomic(path, text, encoding=CSV_PLAIN):
    tmp = path + ".tmp-{}".format(os.getpid())
    with open(tmp, "w", encoding=encoding, newline="") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _iso_local(epoch):
    if epoch is None:
        return ""
    return datetime.fromtimestamp(int(epoch)).astimezone().isoformat(
        sep=" ", timespec="seconds")


def export_files_csv(conn, scan_id):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["relative_path", "absolute_path", "name",
                     "extension", "compound_extension", "mime_guess",
                     "category", "size_bytes", "size_status",
                     "mtime_epoch", "mtime_iso", "is_hidden", "is_symlink",
                     "stat_status", "error_category"])
    for row in conn.execute(
            "SELECT relative_path, absolute_path, name, extension,"
            " compound_extension, mime_guess, category, size_bytes, size_status,"
            " mtime_epoch, mtime_iso, is_hidden, is_symlink, stat_status,"
            " error_category FROM entries"
            " WHERE scan_id = ? AND kind = 'file' ORDER BY relative_path",
            (scan_id,)):
        writer.writerow([csv_safe_cell(v) for v in (
            row["relative_path"], row["absolute_path"], row["name"],
            row["extension"], row["compound_extension"], row["mime_guess"],
            row["category"], row["size_bytes"], row["size_status"],
            row["mtime_epoch"], row["mtime_iso"], bool(row["is_hidden"]),
            bool(row["is_symlink"]), row["stat_status"], row["error_category"])])
    return out.getvalue()


def export_directories_csv(conn, scan_id):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["relative_path", "absolute_path", "name",
                     "direct_files", "direct_dirs",
                     "recursive_files", "recursive_dirs",
                     "recursive_file_bytes",
                     "is_empty", "is_hidden", "mtime_iso"])
    for row in conn.execute(
            "SELECT e.relative_path, e.absolute_path, e.name, e.is_hidden,"
            " e.mtime_iso, d.direct_files, d.direct_dirs, d.recursive_files,"
            " d.recursive_dirs, d.recursive_file_bytes, d.is_empty"
            " FROM entries e JOIN directory_stats d"
            "   ON d.scan_id = e.scan_id AND d.relative_path = e.relative_path"
            " WHERE e.scan_id = ? AND e.kind = 'directory'"
            " ORDER BY e.relative_path", (scan_id,)):
        writer.writerow([csv_safe_cell(v) for v in (
            row["relative_path"], row["absolute_path"], row["name"],
            row["direct_files"], row["direct_dirs"],
            row["recursive_files"], row["recursive_dirs"],
            row["recursive_file_bytes"], bool(row["is_empty"]),
            bool(row["is_hidden"]), row["mtime_iso"])])
    return out.getvalue()


def export_scan_issues_csv(conn, scan_id):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["id", "path", "operation", "error_category", "error_code",
                     "error_message", "occurred_at_epoch", "occurred_at_local"])
    for row in conn.execute(
            "SELECT id, path, operation, error_category, error_code,"
            " error_message, occurred_at_epoch FROM scan_issues"
            " WHERE scan_id = ? ORDER BY id", (scan_id,)):
        writer.writerow([csv_safe_cell(v) for v in (
            row["id"], row["path"], row["operation"], row["error_category"],
            row["error_code"], row["error_message"], row["occurred_at_epoch"],
            _iso_local(row["occurred_at_epoch"]))])
    return out.getvalue()


def export_file_types_csv(conn, scan_id):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["record_type", "value", "files", "bytes"])
    for row in category_breakdown(conn, scan_id):
        writer.writerow(["category", csv_safe_cell(row["category"]),
                         row["files"], row["bytes"]])
    for row in extension_breakdown(conn, scan_id):
        writer.writerow(["extension", csv_safe_cell(row["extension"]),
                         row["files"], row["bytes"]])
    return out.getvalue()


def export_entries_jsonl(conn, scan_id):
    out = io.StringIO()
    for row in conn.execute(
            "SELECT * FROM entries WHERE scan_id = ? ORDER BY relative_path",
            (scan_id,)):
        record = dict(row)
        record.pop("id", None)  # internal row id; scan_id kept for reconciliation
        out.write(json.dumps(record, ensure_ascii=False, allow_nan=False,
                             sort_keys=True))
        out.write("\n")
    return out.getvalue()


def export_manifest(conn, scan_id, *, generated_files):
    run = run_record(conn, scan_id)
    overview = run_overview(conn, scan_id)
    manifest = {
        "tool": "android-storage-audit",
        "tool_version": __version__,
        "schema_version": SCHEMA_VERSION,
        "jsonl_schema_version": JSONL_SCHEMA_VERSION,
        "classification_version": run.get("classification_version"),
        "generated_at_epoch": int(time.time()),
        "generated_at_local": _iso_local(time.time()),
        "scan": {
            "id": run["id"],
            "status": run["status"],
            "scope_label": run["scope_label"],
            "requested_root": run["requested_root"],
            "canonical_root": run["root_path"],
            "started_at_epoch": run["started_at_epoch"],
            "finished_at_epoch": run["finished_at_epoch"],
            "duration_seconds": run["duration_seconds"],
            "coverage_incomplete": bool(run["coverage_incomplete"]),
            "coverage_notes": run["coverage_notes"],
            "scan_mode": run["scan_mode"],
            "include_hidden": bool(run["include_hidden"]),
            "follow_symlinks": bool(run["follow_symlinks"]),
            "exclusions": run["exclusions"],
            "volume_total_bytes": run["volume_total_bytes"],
            "volume_used_bytes": run["volume_used_bytes"],
            "volume_free_bytes": run["volume_free_bytes"],
            "volume_status": run["volume_status"],
            "environment": run["environment"],
        },
        "counters": overview,
        "exports": generated_files,
    }
    return json.dumps(manifest, ensure_ascii=False, allow_nan=False,
                      indent=2, sort_keys=True) + "\n"


def build_tree_lines(conn, scan_id):
    """Yield the complete text tree for the run (deterministic ordering)."""
    entries = conn.execute(
        "SELECT relative_path, name, kind, size_bytes"
        " FROM entries WHERE scan_id = ?", (scan_id,)).fetchall()

    children = {}
    meta = {}
    for row in entries:
        rel = row["relative_path"]
        meta[rel] = row
        parent = "" if rel == "." else (
            "." if os.path.dirname(rel) == "" else os.path.dirname(rel))
        children.setdefault(parent if rel != "." else None, []).append(rel)

    def sort_key(rel):
        row = meta[rel]
        norm = (row["name"] or "").casefold()
        return (0 if row["kind"] == "directory" else 1, norm, row["name"] or "", rel)

    for parent in children:
        children[parent].sort(key=sort_key)

    def display_name(row):
        name = row["name"] or "?"
        name = _escape_tree_name(name)
        if row["kind"] == "directory":
            return name + "/"
        if row["kind"] == "file" and row["size_bytes"] is not None:
            return "{} ({} bytes)".format(name, row["size_bytes"])
        if row["kind"] == "symlink":
            return name + "@ (symlink)"
        return name

    lines = []

    lines.append("./  (scan root)")

    # Iterative depth-first walk (deep nesting must not exhaust the stack).
    stack = []
    root_kids = children.get(".", [])
    for i in range(len(root_kids) - 1, -1, -1):
        stack.append((root_kids[i], "", i == len(root_kids) - 1))
    while stack:
        rel, prefix, is_last = stack.pop()
        row = meta[rel]
        connector = "└── " if is_last else "├── "
        lines.append(prefix + connector + display_name(row))
        if row["kind"] == "directory":
            extension = "    " if is_last else "│   "
            kids = children.get(rel, [])
            for i in range(len(kids) - 1, -1, -1):
                stack.append((kids[i], prefix + extension,
                              i == len(kids) - 1))
    return lines


def _escape_tree_name(name):
    def repl(ch):
        code = ord(ch)
        if ch == "\n":
            return "\\n"
        if ch == "\r":
            return "\\r"
        if ch == "\t":
            return "\\t"
        if code < 32 or code == 0x7F:
            return "\\x{:02x}".format(code)
        return ch
    return "".join(repl(c) for c in name)


def write_tree(lines, dest_dir, *, max_bytes=config.TREE_CHUNK_MAX_BYTES,
               max_lines=config.TREE_CHUNK_MAX_LINES):
    """Write directory_tree.txt, or chunked parts + an index. Returns file list."""
    single_path = os.path.join(dest_dir, "directory_tree.txt")
    buffer = io.StringIO()
    line_count = 0
    byte_count = 0
    for line in lines:
        encoded_len = len((line + "\n").encode("utf-8"))
        if (byte_count + encoded_len > max_bytes or line_count + 1 > max_lines) \
                and buffer.tell() > 0:
            return _write_chunked(lines, dest_dir, single_path,
                                  max_bytes, max_lines)
        buffer.write(line + "\n")
        line_count += 1
        byte_count += encoded_len
    _write_text_atomic(single_path, buffer.getvalue())
    return ["directory_tree.txt"]


def _write_chunked(lines, dest_dir, single_path, max_bytes, max_lines):
    if os.path.exists(single_path):
        os.remove(single_path)
    part_index = 0
    chunks = []
    buffer = io.StringIO()
    byte_count = 0
    lines_count = 0
    start_line = 1
    line_number = 0
    for line in lines:
        encoded_len = len((line + "\n").encode("utf-8"))
        if (byte_count + encoded_len > max_bytes or lines_count + 1 > max_lines) \
                and buffer.tell() > 0:
            part_index += 1
            part_name = "directory_tree_part_{:03d}.txt".format(part_index)
            _write_text_atomic(os.path.join(dest_dir, part_name),
                               buffer.getvalue())
            chunks.append((part_name, start_line, line_number, lines_count))
            buffer = io.StringIO()
            byte_count = 0
            lines_count = 0
            start_line = line_number + 1
        buffer.write(line + "\n")
        byte_count += encoded_len
        lines_count += 1
        line_number += 1
    if buffer.tell() > 0:
        part_index += 1
        part_name = "directory_tree_part_{:03d}.txt".format(part_index)
        _write_text_atomic(os.path.join(dest_dir, part_name), buffer.getvalue())
        chunks.append((part_name, start_line, line_number, lines_count))

    index_lines = [
        "directory_tree index — the complete directory tree was split into "
        "deterministic chunks.",
        "Total chunks: {}".format(len(chunks)),
        "Total lines: {}".format(line_number),
        "",
        "chunk | first_line | last_line | lines",
    ]
    for name, first, last, count in chunks:
        index_lines.append("{} | {} | {} | {}".format(name, first, last, count))
    _write_text_atomic(os.path.join(dest_dir, "directory_tree_index.txt"),
                       "\n".join(index_lines) + "\n")
    return [name for name, _f, _l, _c in chunks] + ["directory_tree_index.txt"]


def summary_markdown(conn, scan_id):
    run = run_record(conn, scan_id)
    overview = run_overview(conn, scan_id)
    categories = category_breakdown(conn, scan_id)

    def md_escape(text):
        # For inline/table text: escape Markdown metacharacters and make
        # control characters visible (a filename containing a newline must
        # not break the document structure).
        s = str(text)
        s = s.replace("\\", "\\\\")
        s = "".join("\\u{0:04x}".format(ord(c)) if (ord(c) < 0x20 or ord(c) == 0x7f) else c
                   for c in s)
        return s.replace("`", "\\`").replace("|", "\\|") \
                .replace("*", "\\*").replace("_", "\\_")

    def md_code(text):
        # For inline code spans: backslashes are literal inside code spans,
        # so only backticks need handling (double-fence) and control chars
        # are made visible.
        s = str(text)
        s = "".join("\\u{0:04x}".format(ord(c)) if (ord(c) < 0x20 or ord(c) == 0x7f) else c
                   for c in s)
        if "`" in s:
            return "`` {} ``".format(s)
        return "`{}`".format(s)

    def human(n):
        if n is None:
            return "Unavailable"
        size = float(n)
        for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
            if size < 1024 or unit == "TiB":
                return "{:.2f} {}".format(size, unit) if unit != "B" else "{} B".format(int(size))
            size /= 1024.0

    lines = [
        "# Android Storage Audit — Scan Summary",
        "",
        "> **Scope:** accessible shared-storage inventory. This is **not** a "
        "forensic image and does **not** cover app-private or protected "
        "storage.",
        "",
        "- Tool version: {}".format(__version__),
        "- Scan run ID: {}".format(run["id"]),
        "- Status: **{}**{}".format(run["status"],
            "  (INCOMPLETE/PARTIAL — do not treat as full coverage)" if run["coverage_incomplete"] else ""),
        "- Requested root: {}".format(md_code(run["requested_root"])),
        "- Canonical root: {}".format(md_code(run["root_path"])),
        "- Started (local): {}".format(_iso_local(run["started_at_epoch"])),
        "- Finished (local): {}".format(_iso_local(run["finished_at_epoch"])),
        "- Duration: {:.2f} s".format(run["duration_seconds"] or 0.0),
        "- Coverage incomplete: {}".format("yes" if run["coverage_incomplete"] else "no"),
        "- Coverage notes: {}".format(md_escape(run["coverage_notes"])),
        "",
        "## Headline counters",
        "",
        "| Metric | Value |",
        "|---|---|",
        "| Files inventoried (stat ok) | {} |".format(overview["files_inventoried"]),
        "| Directories | {} |".format(overview["directories"]),
        "| Symlinks (not followed) | {} |".format(overview["symlinks"]),
        "| Other/unknown entries | {} |".format(overview["other_entries"]),
        "| Hidden entries | {} |".format(overview["hidden_entries"]),
        "| Zero-byte files | {} |".format(overview["zero_byte_files"]),
        "| Failed entries | {} |".format(overview["failed_entries"]),
        "| Skipped entries | {} |".format(overview["skipped_entries"]),
        "| Scan issues | {} |".format(overview["issues"]),
        "| **Inventoried file bytes (logical)** | **{} ({})** |".format(
            overview["inventoried_file_bytes"], human(overview["inventoried_file_bytes"])),
        "",
        "## Bytes by category (logical bytes of inventoried files)",
        "",
        "| Category | Files | Bytes |",
        "|---|---|---|",
    ]
    for row in categories:
        lines.append("| {} | {} | {} ({}) |".format(
            md_escape(row["category"]), row["files"], row["bytes"], human(row["bytes"])))
    lines += [
        "",
        "## Methodology (what was and was not done)",
        "",
        "- File contents were **not** read and no hashes were calculated.",
        "- File types are **inferred from filenames** only (extension), never "
        "verified against content.",
        "- Sizes are logical sizes of regular files whose metadata was read "
        "successfully; directories and symlinks contribute no file bytes.",
        "- Inventoried bytes are **not** OS-reported volume usage. Differences "
        "arise from app-private data, filesystem metadata, reserved space, "
        "allocation units, sparse files and inaccessible paths.",
        "- Hidden entries (basename begins with `.`) are included.",
        "- Symlinks are recorded, never followed.",
        "- This report reveals personal filenames and folder structure. Keep it "
        "private; do not share it publicly.",
        "",
        "*Generated by android-storage-audit {} from scan run {}.*".format(
            __version__, run["id"]),
    ]
    return "\n".join(lines) + "\n"


def exports_readme(scan_id, run):
    size_unit = "bytes (logical file sizes; binary units KiB/MiB/GiB are used in the UI)"
    return """# Export metadata — Android Storage Audit

- **Scan run ID:** {scan_id}
- **Status:** {status}
- **Scope:** accessible shared-storage inventory (NOT a forensic image)
- **Canonical root:** {root}
- **Started (local):** {started}
- **Finished (local):** {finished}
- **Size unit:** {unit}
- **CSV encoding:** UTF-8 with BOM; paths are never truncated; field order is stable and documented per file.
- **Formula-injection safety:** cells whose first character is one of `= + - @ <TAB> <CR>` are prefixed with a single quote `'`. Raw values are preserved in `entries.jsonl` and in the SQLite database.
- **JSONL schema version:** {jsonl}; one JSON object per line; `null` means unavailable; failures carry `stat_status`/`error_*` fields.
- **Tree:** `directory_tree.txt` is the complete tree; unusual control characters in names are escaped as `\\n`, `\\t`, `\\xNN`. If chunked, `directory_tree_index.txt` lists every chunk with line ranges.
- **manifest.json:** machine-readable envelope for this export set (scan metadata, counters, file hashes).
- Fields may be unavailable; absence means "not available", never a fabricated value.
- These exports are private personal data. Do not share publicly.
""".format(scan_id=scan_id, status=run["status"], root=run["root_path"],
           started=_iso_local(run["started_at_epoch"]),
           finished=_iso_local(run["finished_at_epoch"]),
           unit=size_unit, jsonl=JSONL_SCHEMA_VERSION)


def generate_exports(conn, scan_id, exports_dir):
    """Generate all exports into exports_dir (created if needed).

    Returns {filename: {"sha256": ..., "bytes": ...}} for the manifest.
    """
    os.makedirs(exports_dir, exist_ok=True)
    compute_directory_stats(conn, scan_id)  # ensure fresh derived stats

    written = {}

    def _emit(name, content, encoding=CSV_PLAIN):
        path = os.path.join(exports_dir, name)
        _write_text_atomic(path, content, encoding=encoding)
        written[name] = path

    run = run_record(conn, scan_id)

    _emit("files.csv", export_files_csv(conn, scan_id), encoding=CSV_BOM)
    _emit("directories.csv", export_directories_csv(conn, scan_id), encoding=CSV_BOM)
    _emit("scan_issues.csv", export_scan_issues_csv(conn, scan_id), encoding=CSV_BOM)
    _emit("file_types.csv", export_file_types_csv(conn, scan_id), encoding=CSV_BOM)
    _emit("entries.jsonl", export_entries_jsonl(conn, scan_id))

    # Tree (possibly chunked).
    lines = build_tree_lines(conn, scan_id)
    tree_files = write_tree(lines, exports_dir)

    _emit("summary.md", summary_markdown(conn, scan_id))
    _emit("README.md", exports_readme(scan_id, run))

    hashed = {}
    for name in sorted(os.listdir(exports_dir)):
        path = os.path.join(exports_dir, name)
        if not os.path.isfile(path) or name == "manifest.json":
            continue
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(65536), b""):
                digest.update(block)
        hashed[name] = {"sha256": digest.hexdigest(),
                        "bytes": os.path.getsize(path)}

    manifest = export_manifest(conn, scan_id, generated_files=hashed)
    _emit("manifest.json", manifest)
    hashed["manifest.json"] = {
        "sha256": hashlib.sha256(manifest.encode("utf-8")).hexdigest(),
        "bytes": len(manifest.encode("utf-8")),
    }
    return hashed
