"""Offline HTML report generation.

Every value shown comes from the scan database. No external assets, no
network access. Partial/cancelled runs are visibly labelled on every page.
All interpolated strings are HTML-escaped; embedded JSON is script-safe.
"""

import html
import json
import os
import shutil
import time
from datetime import datetime

from . import __version__, SCHEMA_VERSION, config
from .analytics import (
    category_breakdown,
    empty_directories,
    extension_breakdown,
    issues_breakdown,
    issue_listing,
    largest_directories,
    largest_files,
    largest_hidden,
    review_candidates,
    run_overview,
    run_record,
    same_size_candidates,
    zero_byte_files,
)
from .exporters import generate_exports, _iso_local

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "report_templates")

NAV_ITEMS = [
    ("index.html", "Overview"),
    ("directory_explorer.html", "Directory Explorer"),
    ("files.html", "All Files"),
    ("file_types.html", "File Types"),
    ("largest_files.html", "Largest Files"),
    ("largest_directories.html", "Largest Directories"),
    ("empty_directories.html", "Empty Directories"),
    ("zero_byte_files.html", "Zero-byte Files"),
    ("hidden.html", "Hidden Entries"),
    ("review_candidates.html", "Review Candidates"),
    ("scan_issues.html", "Scan Issues"),
    ("methodology.html", "Methodology & Limitations"),
    ("exports.html", "Export Center"),
]

_STATUS_BADGES = {
    "completed": ("badge--ok", "Completed"),
    "completed_with_gaps": ("badge--warn", "Completed with gaps"),
    "cancelled": ("badge--bad", "Cancelled — incomplete"),
    "failed": ("badge--bad", "Failed"),
    "interrupted_or_recovered": ("badge--bad", "Interrupted — incomplete"),
    "running": ("badge--warn", "Running"),
}


def _ctrl_escape(text):
    """Make control characters visible so tables/layout never break."""
    out = []
    for ch in text:
        code = ord(ch)
        if ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif code < 32 or code == 0x7F:
            out.append("\\x{:02x}".format(code))
        else:
            out.append(ch)
    return "".join(out)


def esc(value):
    if value is None:
        return ""
    return html.escape(_ctrl_escape(str(value)), quote=True)


def human_bytes(n):
    if n is None:
        return "Unavailable"
    size = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            if unit == "B":
                return "{} B".format(int(size))
            return "{:.2f} {}".format(size, unit)
        size /= 1024.0


def _script_safe_json(records):
    r"""JSON safe for embedding in a <script> block.

    Escapes every HTML-significant character so no filename can break out of
    the script element or the surrounding markup — even with pathological
    names. JSON/JS both decode \uXXXX escapes transparently.
    """
    text = json.dumps(records, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":"))
    return (text.replace("&", "\\u0026")
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))


def _badge(status):
    cls, label = _STATUS_BADGES.get(status, ("badge--warn", esc(status)))
    return '<span class="badge {}">{}</span>'.format(cls, esc(label))


def _shell(title, active, body, run, *, fixture_label=False, extra_head=""):
    status = run["status"] if run else "failed"
    incomplete = bool(run and run.get("coverage_incomplete"))
    nav = []
    for href, label in NAV_ITEMS:
        current = ' aria-current="page"' if href == active else ""
        nav.append('<a href="{}"{}>{}</a>'.format(href, current, esc(label)))
    nav_html = "\n".join(nav)

    fixture_banner = ""
    if fixture_label:
        fixture_banner = (
            '<div class="alert alert--warn" role="note">'
            "<strong>SYNTHETIC TEST DATA — NOT THE USER&rsquo;S PHONE.</strong> "
            "This report was generated from an artificial fixture tree for "
            "development and test purposes.</div>")

    incomplete_banner = ""
    if run and (incomplete or status not in ("completed",)):
        incomplete_banner = (
            '<div class="alert alert--bad" role="alert">'
            "<strong>Partial / incomplete report.</strong> Scan status: "
            "<strong>{}</strong>. Coverage notes: {}. Do not treat this as a "
            "complete inventory.</div>").format(
                esc(status), esc(run.get("coverage_notes") or "n/a"))

    generated = _iso_local(time.time())
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>{title} · Android Storage Audit</title>
<link rel="stylesheet" href="report.css">
{extra_head}
</head>
<body>
<a class="skip-link" href="#main">Skip to main content</a>
<header class="app-header">
  <div class="app-header__inner">
    <div class="brand">
      <svg width="30" height="30" viewBox="0 0 30 30" role="img" aria-label="Android Storage Audit logo">
        <rect x="2" y="2" width="26" height="26" rx="6" fill="#1b1b21" stroke="#f2994a" stroke-width="1.6"/>
        <rect x="8" y="8" width="14" height="5" rx="1.5" fill="#f2994a"/>
        <rect x="8" y="16" width="14" height="2.4" rx="1.2" fill="#ffb25e"/>
        <rect x="8" y="21" width="9" height="2.4" rx="1.2" fill="#6b5a44"/>
      </svg>
      <span>Android Storage Audit<small>V{version} · read-only inventory</small></span>
    </div>
    <div class="header-meta">
      {badge}
      <span title="Report generated">{generated}</span>
    </div>
  </div>
</header>
<div class="layout">
  <aside class="sidebar" aria-label="Report navigation">
    <nav>
{nav}
    </nav>
  </aside>
  <main class="content" id="main">
{fixture_banner}
{incomplete_banner}
{body}
  </main>
</div>
<footer class="footer">
  Android Storage Audit {version} · report generated locally from scan run #{run_id} ·
  no network access, no telemetry · this report contains personal filenames — keep it private.
</footer>
<script src="report.js" defer></script>
</body>
</html>
""".format(
        title=esc(title), version=__version__, badge=_badge(status),
        generated=esc(generated), nav=nav_html, fixture_banner=fixture_banner,
        incomplete_banner=incomplete_banner, body=body, extra_head=extra_head,
        run_id=esc((run or {}).get("id")),
    )


def _panel(title, inner, anchor=None):
    anchor_attr = ' id="{}"'.format(esc(anchor)) if anchor else ""
    return '<section class="panel"{}><h2>{}</h2>{}</section>'.format(
        anchor_attr, esc(title), inner)


def _cards(cards):
    parts = ['<div class="grid grid--cards">']
    for label, value, sub in cards:
        parts.append(
            '<div class="card"><div class="label">{}</div>'
            '<div class="value">{}</div><div class="sub">{}</div></div>'.format(
                esc(label), value, esc(sub)))
    parts.append("</div>")
    return "".join(parts)


def _bar_chart(items, *, width=760, row_height=26, max_items=12,
               value_formatter=human_bytes):
    """Horizontal SVG bar chart with labels and a table alternative."""
    items = list(items)[:max_items]
    if not items:
        return '<div class="empty-state">No data to chart.</div>'
    max_value = max(v for _label, v in items) or 1
    label_w = 190
    bar_max = width - label_w - 110
    height = row_height * len(items) + 8
    parts = [
        '<svg class="barchart" viewBox="0 0 {w} {h}" role="img" '
        'aria-label="Bar chart">'.format(w=width, h=height)]
    for i, (label, value) in enumerate(items):
        y = i * row_height + 4
        bar_w = max(2, int(bar_max * (value / max_value)))
        cls = "bar" if i % 2 == 0 else "bar bar--alt"
        name = esc(str(label)[:34])
        parts.append(
            '<text class="bar-label" x="0" y="{ty}">{name}</text>'
            '<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="16" rx="3"/>'
            '<text x="{tx}" y="{ty}">{val}</text>'.format(
                ty=y + 13, name=name, cls=cls, x=label_w, y=y,
                w=bar_w, tx=label_w + bar_w + 8, val=esc(value_formatter(value))))
    parts.append("</svg>")
    # Text alternative for accessibility / chart failure.
    parts.append('<div class="table-wrap small" style="margin-top:.5rem"><table>'
                 '<thead><tr><th>Label</th><th class="num">Value</th></tr></thead><tbody>')
    for label, value in items:
        parts.append('<tr><td>{}</td><td class="num">{}</td></tr>'.format(
            esc(label), esc(value_formatter(value))))
    parts.append("</tbody></table></div>")
    return "".join(parts)


def _table(headers, rows, *, caption=None, aligns=None):
    parts = ['<div class="table-wrap"><table>']
    if caption:
        parts.append("<caption>{}</caption>".format(esc(caption)))
    parts.append("<thead><tr>")
    for h in headers:
        parts.append("<th>{}</th>".format(esc(h)))
    parts.append("</tr></thead><tbody>")
    if not rows:
        parts.append('<tr><td colspan="{}" class="dim">None recorded.</td></tr>'.format(
            len(headers)))
    for row in rows:
        parts.append("<tr>")
        for i, cell in enumerate(row):
            cls = ' class="num"' if aligns and aligns[i] == "num" else ""
            parts.append("<td{}>{}</td>".format(cls, cell))
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts)


def _path_cell(value):
    return '<span class="path">{}</span>'.format(esc(value))


# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------

def build_index(conn, scan_id, run, overview, categories, extensions,
                largest_files_, largest_dirs, empty_count, zero_count,
                fixture_label=False, review_count=0):
    vol_total = run.get("volume_total_bytes")
    vol_used = run.get("volume_used_bytes")
    vol_free = run.get("volume_free_bytes")
    inv_bytes = overview["inventoried_file_bytes"]

    volume_html = ""
    if vol_total and vol_free is not None and vol_used is not None:
        used_pct = min(100.0, max(0.0, (vol_used / vol_total * 100.0))) \
            if vol_total else 0.0
        inv_share = (inv_bytes / vol_used * 100.0) if vol_used else None
        if inv_share is None:
            share_note = "Cannot compute share: OS-used bytes are zero or unknown."
        elif inv_share > 100.0:
            share_note = ("Inventoried logical bytes exceed the filesystem-used figure "
                          "(e.g. sparse files). The two metrics measure different things "
                          "— see Methodology.")
        else:
            share_note = ("Inventoried file bytes are {:.1f}% of OS-reported used bytes "
                          "(informational; see Methodology).".format(inv_share))
        volume_html = """
<div class="grid grid--cards">
  {cards}
</div>
<div class="volume-bar" role="img" aria-label="Volume used {pct:.1f} percent"><div style="width:{pct:.1f}%"></div></div>
<p class="dim small">{share} Volume figures are filesystem-level observations ({status}); inventoried bytes are logical file sizes. They are not expected to be equal.</p>
""".format(
            cards="".join([
                '<div class="card"><div class="label">Volume capacity</div><div class="value">{}</div><div class="sub">filesystem total</div></div>'.format(esc(human_bytes(vol_total))),
                '<div class="card"><div class="label">Volume used</div><div class="value">{}</div><div class="sub">OS filesystem figure</div></div>'.format(esc(human_bytes(vol_used))),
                '<div class="card"><div class="label">Volume free</div><div class="value">{}</div><div class="sub">OS filesystem figure</div></div>'.format(esc(human_bytes(vol_free))),
            ]),
            pct=used_pct, share=esc(share_note), status=esc(run.get("volume_status")))
    else:
        volume_html = ('<p class="dim">Volume capacity/used/free: <strong>not available</strong> '
                       '({}). The inventory itself is unaffected; sizes shown elsewhere '
                       'are logical file sizes from filesystem metadata.</p>').format(
                           esc(run.get("volume_status") or "unavailable"))

    category_chart = _bar_chart(
        [(c["category"], c["bytes"]) for c in categories],
        max_items=len(categories) or 1, value_formatter=human_bytes)
    top_ext = sorted(extensions, key=lambda e: e["bytes"], reverse=True)[:12]
    extension_chart = _bar_chart(
        [(e["extension"], e["bytes"]) for e in top_ext],
        max_items=12, value_formatter=human_bytes)

    largest_files_table = _table(
        ["#", "Name", "Path", "Size", "Category"],
        [[str(i + 1), esc(os.path.basename(f["name"] or f["relative_path"])),
          _path_cell(f["relative_path"]),
          esc(human_bytes(f["size_bytes"])),
          esc(f["category"])] for i, f in enumerate(largest_files_[:25])],
        aligns=["num", None, None, "num", None],
        caption="Top 25 largest files by logical size (truncated view).")

    largest_dirs_table = _table(
        ["#", "Directory", "Recursive bytes", "Recursive files"],
        [[str(i + 1), _path_cell(d["relative_path"]),
          esc(human_bytes(d["recursive_file_bytes"])),
          esc(d["recursive_files"])] for i, d in enumerate(largest_dirs[:25])],
        aligns=["num", None, "num", "num"],
        caption="Top 25 directories by recursive inventoried file bytes (not directory inode size).")

    body = """
<h1>Storage Overview</h1>
<p class="dim">Scan run <strong>#{run_id}</strong> · root <span class="path">{root}</span> · requested as <span class="path">{req}</span></p>
<p class="dim small">Scope: <strong>accessible shared-storage inventory</strong>. This is not a forensic image and does not cover app-private or protected storage. Hidden entries are included; symlinks are recorded, not followed.</p>

<div class="alert alert--info"><strong>Coverage:</strong> {notes}</div>

{key_cards}

<section class="panel"><h2>Volume capacity (filesystem-level)</h2>{volume}</section>

<section class="panel"><h2>Bytes by category <span class="dim small">(logical bytes of inventoried files)</span></h2>{category_chart}</section>

<section class="panel"><h2>Largest extensions by bytes <span class="dim small">(top 12 of {ext_count}; full table in File Types)</span></h2>{extension_chart}</section>

<section class="panel"><h2>Largest files</h2>{largest_files}<p class="small dim">Truncated to top 25. Complete inventory: <a href="files.html">All Files</a> and <a href="exports.html">Export Center</a>.</p></section>

<section class="panel"><h2>Largest directories</h2>{largest_dirs}<p class="small dim">Truncated to top 25. Recursive totals, not directory inode size.</p></section>

<section class="panel"><h2>Quick links</h2>
<ul>
<li><a href="empty_directories.html">{empty_count} empty directories</a></li>
<li><a href="zero_byte_files.html">{zero_count} zero-byte files</a></li>
<li><a href="hidden.html">Hidden entries overview</a></li>
<li><a href="review_candidates.html">{review_count} review candidates <span class="dim">(neutral observations)</span></a></li>
<li><a href="scan_issues.html">{issues} scan issues / inaccessible paths</a></li>
<li><a href="exports.html">Exports (CSV, JSONL, tree, manifest)</a></li>
</ul></section>
""".format(
        run_id=esc(run["id"]), root=esc(run["root_path"]),
        req=esc(run["requested_root"]), notes=esc(run.get("coverage_notes")),
        key_cards=_cards([
            ("Files inventoried", '<span class="num">{}</span>'.format(overview["files_inventoried"]), "stat ok"),
            ("Directories", '<span class="num">{}</span>'.format(overview["directories"]), "recorded (incl. empty)"),
            ("Inventoried bytes", '<span class="num">{}</span>'.format(esc(human_bytes(inv_bytes))), "logical file sizes"),
            ("Scan issues", '<span class="num">{}</span>'.format(overview["issues"]), "errors / inaccessible"),
            ("Zero-byte files", '<span class="num">{}</span>'.format(overview["zero_byte_files"]), "size observed = 0"),
            ("Hidden entries", '<span class="num">{}</span>'.format(overview["hidden_entries"]), "basename starts with ."),
            ("Symlinks", '<span class="num">{}</span>'.format(overview["symlinks"]), "recorded, not followed"),
            ("Failed entries", '<span class="num">{}</span>'.format(overview["failed_entries"]), "metadata unreadable"),
        ]),
        volume=volume_html, category_chart=category_chart,
        extension_chart=extension_chart, ext_count=len(extensions),
        largest_files=largest_files_table, largest_dirs=largest_dirs_table,
        empty_count=empty_count, zero_count=zero_count, issues=overview["issues"],
        review_count=review_count)

    return _shell("Overview", "index.html", body, run, fixture_label=fixture_label)


def _inventory_records(conn, scan_id):
    records = []
    for row in conn.execute(
            "SELECT relative_path, name, normalized_name, kind, extension,"
            " category, size_bytes, mtime_epoch, mtime_iso, is_hidden, stat_status,"
            " compound_extension"
            " FROM entries WHERE scan_id = ? ORDER BY relative_path", (scan_id,)):
        records.append({
            "relative_path": row["relative_path"],
            "name": row["name"],
            "normalized_name": row["normalized_name"],
            "kind": row["kind"],
            "extension": row["extension"],
            "compound_extension": row["compound_extension"],
            "category": row["category"],
            "size_bytes": row["size_bytes"],
            "mtime_epoch": row["mtime_epoch"],
            "mtime_iso": row["mtime_iso"],
            "is_hidden": int(row["is_hidden"]),
            "stat_status": row["stat_status"],
        })
    return records


def build_files_search_page(conn, scan_id, run, report_dir, fixture_label=False):
    records = _inventory_records(conn, scan_id)
    total = len(records)
    chunked = total > config.SEARCH_INLINE_LIMIT

    extensions = sorted({(r["extension"] or "(none)") for r in records})
    categories = sorted({r["category"] for r in records})

    ext_options = "\n".join(
        '<option value="{}">{}</option>'.format(esc(e), esc(e)) for e in extensions)
    cat_options = "\n".join(
        '<option value="{}">{}</option>'.format(esc(c), esc(c)) for c in categories)

    data_tags = ""
    chunk_files = []
    if chunked:
        data_dir = os.path.join(report_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        for index in range(0, total, config.SEARCH_CHUNK_SIZE):
            chunk = records[index:index + config.SEARCH_CHUNK_SIZE]
            chunk_name = "inventory_{:03d}.js".format(index // config.SEARCH_CHUNK_SIZE + 1)
            payload = _script_safe_json(chunk)
            with open(os.path.join(data_dir, chunk_name), "w",
                      encoding="utf-8", newline="\n") as fh:
                fh.write("window.__INVENTORY=(window.__INVENTORY||[]).concat("
                         + payload + ");\n")
            chunk_files.append("data/" + chunk_name)
            data_tags += '<script src="data/{}"></script>\n'.format(esc(chunk_name))
    else:
        data_tags = "<script>window.__INVENTORY = {};</script>\n".format(
            _script_safe_json(records))

    mode_note = (
        "Inventory embedded inline ({} records).".format(total)
        if not chunked else
        "Inventory split across {} data files loaded below "
        "({} records). Static paginated tables remain available without "
        "JavaScript.".format(len(chunk_files), total))

    body = """
<h1>All Files &amp; Entries</h1>
<p class="dim">Search covers <strong>metadata only</strong> (name, path, extension, category, size, times) — never file contents. Filters compose with AND. Clearing filters restores the full set.</p>
<p class="small dim">{mode_note}</p>
<noscript><p class="alert alert--info">JavaScript is disabled or unavailable. Use the <a href="files_page_1.html">static paginated tables</a>, which need no JavaScript.</p></noscript>

<div id="inventory-browser">
  <div class="controls" role="search">
    <div class="control"><label for="f-search">Name / path search</label>
      <input type="search" id="f-search" placeholder="e.g. WhatsApp, .jpg, report" autocomplete="off"></div>
    <div class="control"><label for="f-extension">Extension</label>
      <select id="f-extension"><option value="">All</option>{ext_options}</select></div>
    <div class="control"><label for="f-category">Category</label>
      <select id="f-category"><option value="">All</option>{cat_options}</select></div>
    <div class="control"><label for="f-kind">Entry type</label>
      <select id="f-kind"><option value="">All</option>
        <option value="file">file</option><option value="directory">directory</option>
        <option value="symlink">symlink</option><option value="other">other</option>
        <option value="unknown">unknown</option></select></div>
    <div class="control"><label for="f-min-size">Min size (bytes)</label>
      <input type="number" id="f-min-size" min="0" inputmode="numeric" placeholder="0"></div>
    <div class="control"><label for="f-max-size">Max size (bytes)</label>
      <input type="number" id="f-max-size" min="0" inputmode="numeric" placeholder=""></div>
    <div class="control"><label for="f-sort">Sort by</label>
      <select id="f-sort">
        <option value="path-asc">Path (A→Z)</option>
        <option value="name-asc">Name (A→Z)</option>
        <option value="size-desc">Size (largest)</option>
        <option value="size-asc">Size (smallest)</option>
        <option value="mtime-desc">Modified (newest)</option>
        <option value="mtime-asc">Modified (oldest)</option>
        <option value="category-asc">Category (A→Z)</option>
      </select></div>
    <div class="control"><label for="f-page-size">Rows per page</label>
      <select id="f-page-size"><option>25</option><option selected>50</option><option>100</option><option>250</option></select></div>
  </div>
  <div class="controls">
    <label class="small"><input type="checkbox" id="f-hidden"> Hidden only</label>
    <label class="small"><input type="checkbox" id="f-errors"> Stat failures only</label>
    <button type="button" class="secondary" id="inv-reset">Reset filters</button>
  </div>
  <p class="result-meta" id="inv-count" role="status"></p>
  <div class="table-wrap">
    <table aria-describedby="inv-count">
      <thead><tr><th>Path</th><th>Ext</th><th>Category</th><th class="num">Size</th><th>Modified (local)</th><th>Type</th></tr></thead>
      <tbody id="inv-tbody"></tbody>
    </table>
  </div>
  <div class="empty-state" id="inv-empty" hidden>No records match these filters. <button type="button" class="secondary" id="inv-reset-2">Clear filters</button></div>
  <div class="pager">
    <button type="button" class="secondary" id="inv-prev">← Previous</button>
    <span id="inv-page-info">Page 1</span>
    <button type="button" class="secondary" id="inv-next">Next →</button>
  </div>
</div>
<p class="small dim">Complete data also lives in <a href="exports/entries.jsonl">entries.jsonl</a>, <a href="exports/files.csv">files.csv</a> and the <a href="files_page_1.html">static pages</a>.</p>
{data_tags}
""".format(mode_note=esc(mode_note), ext_options=ext_options,
            cat_options=cat_options, data_tags=data_tags)

    # Wire the secondary reset button (same behavior as main reset).
    body = body.replace(
        '<button type="button" class="secondary" id="inv-reset-2">Clear filters</button>',
        '<button type="button" class="secondary" onclick="document.getElementById(\'inv-reset\').click()">Clear filters</button>')

    return _shell("All Files", "files.html", body, run,
                  fixture_label=fixture_label), records, chunked


def build_static_file_pages(conn, scan_id, run, report_dir, fixture_label=False,
                            page_rows=None):
    """Static, JS-free paginated tables of regular files. Returns page count."""
    page_rows = page_rows or config.DEFAULT_PAGE_ROWS
    total = conn.execute(
        "SELECT COUNT(*) FROM entries WHERE scan_id = ? AND kind = 'file'",
        (scan_id,)).fetchone()[0]
    page_count = max(1, (total + page_rows - 1) // page_rows)

    offset = 0
    for page in range(1, page_count + 1):
        rows = conn.execute(
            "SELECT relative_path, name, extension, category, size_bytes,"
            " mtime_iso, is_hidden, stat_status FROM entries"
            " WHERE scan_id = ? AND kind = 'file'"
            " ORDER BY relative_path LIMIT ? OFFSET ?",
            (scan_id, page_rows, offset)).fetchall()
        offset += page_rows

        body_rows = []
        for r in rows:
            marker = " <span title=\"hidden\" aria-label=\"hidden\">·</span>" if r["is_hidden"] else ""
            status = "" if r["stat_status"] == "ok" else " (stat failed)"
            body_rows.append(
                "<tr><td>{}{}</td><td>{}</td><td>{}</td><td class=\"num\">{}</td>"
                "<td>{}</td><td>{}{}</td></tr>".format(
                    _path_cell(r["relative_path"]), marker,
                    esc(r["extension"] or "(none)"), esc(r["category"]),
                    esc(human_bytes(r["size_bytes"])) if r["size_bytes"] is not None else "Unavailable",
                    esc(r["mtime_iso"] or "Unavailable"),
                    esc(r["stat_status"]), status))

        prev_link = ('<a href="files_page_{}.html">← Previous</a>'.format(page - 1)
                     if page > 1 else '<span aria-disabled="true">← Previous</span>')
        next_link = ('<a href="files_page_{}.html">Next →</a>'.format(page + 1)
                     if page < page_count else '<span aria-disabled="true">Next →</span>')

        body = """
<h1>All Files — Static Table <span class="dim">(page {page} of {pages})</span></h1>
<p class="dim">{total} regular files inventoried. {page_rows} rows per page. No JavaScript required. Ordering: path ascending.</p>
<div class="pager">{prev} <span>Page {page} of {pages}</span> {next}</div>
<div class="table-wrap"><table>
<thead><tr><th>Path</th><th>Ext</th><th>Category</th><th class="num">Size</th><th>Modified (local)</th><th>Status</th></tr></thead>
<tbody>{rows}</tbody></table></div>
<div class="pager">{prev} <span>Page {page} of {pages}</span> {next}</div>
""".format(page=page, pages=page_count, total=total, page_rows=page_rows,
            prev=prev_link, next=next_link, rows="".join(body_rows))
        out_path = os.path.join(report_dir, "files_page_{}.html".format(page))
        _write_atomic(out_path, _shell("All Files — page {}".format(page),
                                       "files.html", body, run,
                                       fixture_label=fixture_label))
    return page_count


def _write_atomic(path, text):
    tmp = path + ".tmp-{}".format(os.getpid())
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def build_file_types_page(categories, extensions, run, fixture_label=False):
    cat_rows = [[esc(c["category"]), str(c["files"]),
                 "{} ({})".format(esc(human_bytes(c["bytes"])), esc(c["bytes"]))]
                for c in categories]
    ext_rows = [[esc(e["extension"]), str(e["files"]),
                 "{} ({})".format(esc(human_bytes(e["bytes"])), esc(e["bytes"]))]
                for e in extensions]

    cat_table = _table(["Category", "Files", "Bytes"], cat_rows,
                       aligns=[None, "num", "num"],
                       caption="Bytes by category (logical bytes of inventoried files).")
    ext_table = _table(["Extension", "Files", "Bytes"], ext_rows,
                       aligns=[None, "num", "num"],
                       caption="All observed extensions ({}), including unknown/(none).".format(len(extensions)))

    body = """
<h1>File Types</h1>
<p class="dim">Classification is <strong>inferred from the filename extension</strong>, never verified against content. MIME guesses (in exports) are filename-derived too. Unknown or ambiguous extensions remain <code>unknown</code>.</p>
<div class="panel"><h2>By category</h2>{cat}</div>
<div class="panel"><h2>By extension</h2>{ext}</div>
<p class="small dim">Machine-readable: <a href="exports/file_types.csv">file_types.csv</a>. Classification rule version: see Methodology.</p>
""".format(cat=cat_table, ext=ext_table)
    return _shell("File Types", "file_types.html", body, run,
                  fixture_label=fixture_label)


def build_largest_files_page(files, run, fixture_label=False):
    rows = [[str(i + 1), esc(os.path.basename(f["name"] or f["relative_path"])),
             _path_cell(f["relative_path"]), esc(human_bytes(f["size_bytes"])),
             esc(f["category"]), esc(f["mtime_iso"] or "Unavailable")]
            for i, f in enumerate(files[:200])]
    table = _table(["#", "Name", "Path", "Size", "Category", "Modified (local)"],
                   rows, aligns=["num", None, None, "num", None, None],
                   caption="Top {} files shown of {} requested (truncated view).".format(
                       min(200, len(files)), len(files)))
    body = """
<h1>Largest Files</h1>
<p class="dim">Logical sizes of regular files whose metadata was read. Sparse files and compression mean logical ≠ allocated bytes. This is a neutral observation, not a claim that large files are disposable.</p>
{table}
<p class="small dim">Shows up to 200. Complete data: <a href="files.html">All Files</a> (sort by size) or <a href="exports/files.csv">files.csv</a>.</p>
""".format(table=table)
    return _shell("Largest Files", "largest_files.html", body, run,
                  fixture_label=fixture_label)


def build_largest_directories_page(dirs, run, fixture_label=False):
    rows = [[str(i + 1), _path_cell(d["relative_path"]),
             '<span class="num">{} ({})</span>'.format(
                 esc(human_bytes(d["recursive_file_bytes"])),
                 esc(d["recursive_file_bytes"])),
             '<span class="num">{}</span>'.format(esc(d["recursive_files"])),
             '<span class="num">{}</span>'.format(esc(d["recursive_dirs"]))]
            for i, d in enumerate(dirs[:200])]
    table = _table(["#", "Directory", "Recursive bytes", "Recursive files",
                    "Recursive subdirs"], rows,
                   aligns=["num", None, "num", "num", "num"],
                   caption="Top 200 directories by recursive inventoried file bytes.")
    body = """
<h1>Largest Directories</h1>
<p class="dim">Recursive totals of inventoried regular files below each directory — never directory inode sizes, and never summed across directories (no double counting).</p>
{table}
<p class="small dim">Truncated to top 200. Complete per-directory aggregates: <a href="exports/directories.csv">directories.csv</a>.</p>
""".format(table=table)
    return _shell("Largest Directories", "largest_directories.html", body, run,
                  fixture_label=fixture_label)


def build_list_page(title, active, items, headers, row_fn, run,
                    fixture_label=False, note=None, export_hint=None):
    rows = [row_fn(i + 1, item) for i, item in enumerate(items)]
    table = _table(headers, rows)
    note_html = '<p class="dim">{}</p>'.format(esc(note)) if note else ""
    export_html = '<p class="small dim">{}</p>'.format(esc(export_hint)) if export_hint else ""
    body = """
<h1>{title}</h1>
<p class="dim">{count} record(s).</p>
{note}
{table}
{export}
""".format(title=esc(title), count=len(items), note=note_html,
            table=table, export=export_html)
    return _shell(title, active, body, run, fixture_label=fixture_label)


def build_review_candidates_page(candidates, same_size, run, fixture_label=False):
    large = [c for c in candidates if "large file" in c["observation"]]
    old = [c for c in candidates if "5 years" in c["observation"]]

    def candidate_rows(rows):
        return [[str(i + 1), _path_cell(c["relative_path"]),
                 '<span class="num">{}</span>'.format(esc(human_bytes(c["size_bytes"]))),
                 esc(c["observation"])]
                for i, c in enumerate(rows)]

    if large:
        large_table = _table(["#", "Path", "Size", "Observation"],
                             candidate_rows(large),
                             caption="Files ≥ 100 MiB. Neutral observation — not a claim that these are disposable.")
    else:
        large_table = '<div class="empty-state">No files ≥ 100 MiB in this scan.</div>'

    if old:
        old_table = _table(["#", "Path", "Size", "Observation"],
                           candidate_rows(old),
                           caption="Regular files ≥ 10 MiB not modified in over 5 years. Neutral observation.")
    else:
        old_table = '<div class="empty-state">No files ≥ 10 MiB unmodified for over 5 years in this scan.</div>'

    if same_size:
        group_rows = []
        for i, group in enumerate(same_size):
            sample = "<br>".join(
                '<code class="path">{}</code>'.format(esc(p))
                for p in group["sample_paths"][:5])
            more = ("" if len(group["sample_paths"]) <= 5
                    else '<br><span class="dim">… and {} more with the same size</span>'.format(
                        group["count"] - 5))
            group_rows.append(
                [str(i + 1),
                 '<span class="num">{} ({})</span>'.format(
                     esc(human_bytes(group["size_bytes"])), esc(group["size_bytes"])),
                 '<span class="num">{}</span>'.format(esc(group["count"])),
                 sample + more])
        same_size_table = _table(
            ["#", "Size", "Files", "Paths (up to 5 shown)"], group_rows,
            aligns=["num", "num", "num", None],
            caption=("Regular files sharing the same observed size. "
                     "Same size is NOT proof of identical content — "
                     "V1 performs no hashing."))
    else:
        same_size_table = '<div class="empty-state">No same-size candidate groups with more than one file in this scan.</div>'

    body = """
<h1>Review Candidates <span class="dim small">neutral observations</span></h1>
<p class="dim">These are neutral observations to help a human review — <strong>not</strong> a list of junk, duplicates, or files safe to delete. Nothing on this page is deleted, moved or flagged automatically, and V1 never performs those actions. Deciding what to do with any of these files is a human decision, outside this tool.</p>

<section class="panel"><h2>Very large files (≥ 100 MiB)</h2>{large}</section>
<section class="panel"><h2>Large files unmodified for over 5 years (≥ 10 MiB)</h2>{old}</section>
<section class="panel"><h2>Same-size candidate groups (not proof of duplication)</h2>{same}</section>
<p class="small dim">No hashing or content inspection is performed by V1. Same-size groups may contain different files. Decide only after inspecting the files yourself — outside this tool.</p>
""".format(large=large_table, old=old_table, same=same_size_table)
    return _shell("Review Candidates", "review_candidates.html", body, run,
                  fixture_label=fixture_label)


def build_hidden_page(overview, hidden_dirs, hidden_files, run, fixture_label=False):
    dir_rows = [[_path_cell(d["relative_path"]),
                 '<span class="num">{} ({})</span>'.format(
                     esc(human_bytes(d["recursive_file_bytes"])),
                     esc(d["recursive_file_bytes"])),
                 '<span class="num">{}</span>'.format(esc(d["recursive_files"]))]
                for d in hidden_dirs]
    file_rows = [[_path_cell(f["relative_path"]),
                  '<span class="num">{}</span>'.format(esc(human_bytes(f["size_bytes"])))]
                 for f in hidden_files]
    body = """
<h1>Hidden Entries</h1>
<p class="dim">Hidden = basename starts with <code>.</code> (Android has no separate hidden flag exposed through the filesystem API). Hidden does <strong>not</strong> mean suspicious or malicious.</p>
{cards}
<div class="panel"><h2>Largest hidden directories (top 25)</h2>{dirs}</div>
<div class="panel"><h2>Largest hidden files (top 25)</h2>{files}</div>
<p class="small dim">Complete hidden listing: use the <em>Hidden only</em> filter on <a href="files.html">All Files</a>, or filter <a href="exports/entries.jsonl">entries.jsonl</a> for <code>is_hidden = 1</code>.</p>
""".format(
        cards=_cards([
            ("Hidden entries", '<span class="num">{}</span>'.format(overview["hidden_entries"]), "all kinds"),
            ("Hidden files", '<span class="num">{}</span>'.format(overview["hidden_files"]), "regular files"),
            ("Hidden directories", '<span class="num">{}</span>'.format(overview["hidden_directories"]), "incl. .thumbnails etc."),
        ]),
        dirs=_table(["Directory", "Recursive bytes", "Recursive files"], dir_rows),
        files=_table(["File", "Size"], file_rows))
    return _shell("Hidden Entries", "hidden.html", body, run,
                  fixture_label=fixture_label)


def build_directory_explorer(conn, scan_id, run, fixture_label=False):
    dir_rows = conn.execute(
        "SELECT e.relative_path, e.name, d.recursive_files, d.recursive_dirs,"
        " d.recursive_file_bytes, d.is_empty"
        " FROM entries e JOIN directory_stats d"
        "   ON d.scan_id = e.scan_id AND d.relative_path = e.relative_path"
        " WHERE e.scan_id = ? AND e.kind = 'directory'"
        " ORDER BY e.depth, e.normalized_name", (scan_id,)).fetchall()

    total_dirs = len(dir_rows)
    if total_dirs > config.DIRECTORY_EXPLORE_LIMIT:
        body = """
<h1>Directory Explorer</h1>
<div class="alert alert--info">Directory count ({}) exceeds the inline-explorer limit ({}). The complete hierarchy is available in <a href="exports/directory_tree.txt">directory_tree.txt</a> (or its chunks) and per-directory aggregates in <a href="exports/directories.csv">directories.csv</a>.</div>
<p>Browse the paginated directory table: <a href="dirs_page_1.html">dirs_page_1.html</a></p>
""".format(total_dirs, config.DIRECTORY_EXPLORE_LIMIT)
        return _shell("Directory Explorer", "directory_explorer.html", body,
                      run, fixture_label=fixture_label)

    children = {}
    stats = {}
    for row in dir_rows:
        rel = row["relative_path"]
        stats[rel] = row
        parent = "" if rel == "." else (
            "." if os.path.dirname(rel) == "" else os.path.dirname(rel))
        if rel == ".":
            continue
        children.setdefault(parent, []).append(rel)
    for parent in children:
        children[parent].sort(key=lambda p: (stats[p]["name"] or "").casefold())

    lines = []
    lines.append('<h1>Directory Explorer</h1>')
    lines.append('<p class="dim">{} directories. Expand/collapse with the disclosure triangles. '
                 'File-level detail: <a href="files.html">All Files</a>. '
                 'Complete hierarchy: <a href="exports/directory_tree.txt">directory_tree.txt</a>.</p>'.format(total_dirs))

    root_row = stats.get(".")
    if root_row is not None:
        lines.append(_details_dir_html(".", root_row, children, stats, is_root=True))
    return _shell("Directory Explorer", "directory_explorer.html",
                  "".join(lines), run, fixture_label=fixture_label)


def _details_dir_html(rel, row, children, stats, is_root=False):
    """Nested <details> tree, iterative to bound stack depth."""
    parts = []
    stack = [("open", rel, is_root)]
    while stack:
        action, current, root_flag = stack.pop()
        if action == "open":
            kids = children.get(current, [])
            if root_flag:
                label = "Scan root (.)"
            else:
                label = esc(stats[current]["name"] or current) + "/"
            meta = ("{} files · {} subdirs · {} recursive".format(
                stats[current]["recursive_files"],
                stats[current]["recursive_dirs"],
                human_bytes(stats[current]["recursive_file_bytes"])))
            open_attr = "open" if root_flag else ""
            parts.append('<details class="dir" {}><summary><span class="dir-name">{}</span>'
                         '<span class="dir-meta">{}</span></summary>'.format(
                             open_attr, label, esc(meta)))
            stack.append(("close", current, root_flag))
            for child in reversed(kids):
                stack.append(("open", child, False))
        else:
            parts.append("</details>")
    return "".join(parts)


def build_issues_page(conn, scan_id, run, fixture_label=False):
    breakdown = issues_breakdown(conn, scan_id)
    listing = issue_listing(conn, scan_id, limit=1000)
    total = sum(b["count"] for b in breakdown)

    breakdown_rows = [[esc(b["operation"]), esc(b["error_category"]),
                       str(b["count"])] for b in breakdown]
    detail_rows = [[_path_cell(i["path"]), esc(i["operation"]),
                    esc(i["error_category"]),
                    esc(str(i["error_code"]) if i["error_code"] is not None else ""),
                    esc(i["error_message"])] for i in listing]
    note = ""
    if total > len(listing):
        note = ('Showing first {n} of {t} issues. Complete list: '
                '<a href="exports/scan_issues.csv">scan_issues.csv</a>.').format(
                    n=len(listing), t=total)

    body = """
<h1>Scan Issues</h1>
<p class="dim">Every path that could not be enumerated or every stat that failed is recorded here. Permission errors on protected folders (e.g. Android/data, Android/obb on many devices) are expected on Android and do not mean the scan crashed — but they do mean coverage is not total.</p>
<div class="panel"><h2>Issues by operation</h2>{breakdown}</div>
<div class="panel"><h2>Issue detail (first {shown})</h2>{note}{detail}</div>
""".format(
        breakdown=_table(["Operation", "Error category", "Count"],
                         breakdown_rows, aligns=[None, None, "num"]),
        detail=_table(["Path", "Operation", "Category", "Code", "Message"], detail_rows),
        shown=len(listing), note=('<p class="alert alert--info">{}</p>'.format(note) if note else ""))
    return _shell("Scan Issues", "scan_issues.html", body, run,
                  fixture_label=fixture_label)


METRIC_DEFINITIONS = [
    ("Files inventoried", "Regular-file entries whose required identity/path metadata was recorded with stat ok. Size may separately be observed, unavailable or failed."),
    ("Direct files", "Regular-file children directly inside one directory."),
    ("Recursive files", "All regular-file descendants beneath a directory, excluding the directory itself."),
    ("Direct directories", "Directory children directly inside one directory."),
    ("Recursive directories", "All directory descendants beneath a directory (each counted once, at its own path)."),
    ("Logical file bytes", "Sum of successfully observed logical sizes of regular files in the scan scope."),
    ("Directory logical bytes", "Sum of inventoried descendant regular-file logical sizes."),
    ("Volume capacity / used / free", "Filesystem-level values reported by the OS for the scan root (shutil.disk_usage). Not a sum of inventory entries."),
    ("Empty directory", "Successfully enumerated directory with zero child entries. A directory whose enumeration failed is NOT reported as empty."),
    ("Zero-byte file", "Regular file whose size was successfully observed as exactly zero."),
    ("Hidden entry", "Basename begins with a dot (.). No other hidden semantics are assumed."),
    ("Inaccessible directory", "Directory observed but whose contents could not be enumerated."),
    ("Failed entry", "Entry whose required metadata could not be collected."),
    ("Skipped entry", "Entry intentionally omitted under a documented exclusion (output-in-root) or policy (mount boundary)."),
    ("Unknown type", "Entry whose type could not be reliably established."),
    ("Same-size candidate", "Two or more regular files with equal observed sizes — not proof of duplicate content."),
]


def build_methodology_page(run, fixture_label=False):
    mech = "".join(
        "<tr><td>{}</td><td>{}</td></tr>".format(esc(k), esc(v))
        for k, v in METRIC_DEFINITIONS)
    body = """
<h1>Methodology &amp; Limitations</h1>

<div class="panel"><h2>What this tool read — and what it did not</h2>
<ul>
<li><strong>Read:</strong> directory listings and filesystem metadata (names, paths, sizes, timestamps, type bits) under the scan root.</li>
<li><strong>Not read:</strong> file contents. No hashes, no thumbnails, no EXIF, no document parsing, no archive extraction.</li>
<li><strong>Not modified:</strong> the scanned tree. The scanner never writes, renames, moves, deletes, chmods or chowns source files or directories.</li>
<li><strong>Not done:</strong> cleanup, deduplication-by-deletion, backups, synchronization, cloud upload, telemetry, notifications. V1 has none of these.</li>
</ul></div>

<div class="panel"><h2>Coverage — read this before drawing conclusions</h2>
<ul>
<li>This is an <strong>accessible shared-storage inventory</strong>, not a forensic image and not 100% of device data.</li>
<li>Android protects some areas: other apps&rsquo; private internal data, and (depending on Android version/OEM/firmware) parts of <code>Android/data</code> and <code>Android/obb</code>. These may be missing or partially visible. The report records every observed denial with path and reason.</li>
<li>Inventoried file bytes ≠ OS-used storage. Differences come from app-private data, metadata/reserved space, allocation units, sparse files, and inaccessible paths. Volume figures and inventory figures are shown separately and never added.</li>
<li>Hidden entries are included by default. Symlinks are recorded but never followed.</li>
<li>Classification is filename-derived (extension). Types are guesses labelled as such; unknown stays unknown.</li>
<li>No metric is fabricated; unavailable values render as &ldquo;Unavailable&rdquo;, never as 0.</li>
</ul></div>

<div class="panel"><h2>Metric definitions</h2>
<div class="table-wrap"><table>
<thead><tr><th>Metric</th><th>Definition</th></tr></thead>
<tbody>{metrics}</tbody></table></div></div>

<div class="panel"><h2>Scan facts</h2>
<ul>
<li>Tool version: {version} · Schema version: {schema} · Classification rule version: {cls} · JSONL schema version: 1</li>
<li>Scan run ID: {run_id} · Status: {status}</li>
<li>Scan mode: metadata-only (default) · include_hidden: yes · follow_symlinks: no</li>
<li>Root (canonical): <span class="path">{root}</span></li>
<li>Timestamps are stored as raw epoch seconds and displayed in the generating host&rsquo;s local timezone with offset.</li>
<li>Environment (no personal identifiers): {env}</li>
</ul></div>

<div class="panel"><h2>Privacy</h2>
<p>This report and its exports reveal personal filenames, folder names and activity clues. Keep them on the device. Do not upload, commit to Git, or share them publicly. Delete them manually when you no longer need them (the tool never deletes them for you).</p></div>

<div class="panel"><h2>Regenerating / auditing</h2>
<p>Rebuild this report from the existing database without rescanning:</p>
<p><code>python storage_audit.py report --latest</code></p>
<p>Every number in this report reconciles with <code>entries</code>, <code>scan_issues</code> and <code>directory_stats</code> tables in the SQLite database recorded in the report&rsquo;s manifest.</p></div>
""".format(metrics=mech, version=__version__, schema=SCHEMA_VERSION,
            cls=esc(run.get("classification_version")),
            run_id=esc(run["id"]), status=esc(run["status"]),
            root=esc(run["root_path"]),
            env=esc(json.dumps(run.get("environment") or {}, ensure_ascii=False, sort_keys=True)))
    return _shell("Methodology & Limitations", "methodology.html", body, run,
                  fixture_label=fixture_label)


def build_exports_page(report_dir, generated_files, run, fixture_label=False):
    rows = []
    for name in sorted(generated_files):
        info = generated_files[name]
        rows.append(
            '<div class="export-item"><a href="exports/{n}"><code>{n}</code></a>'
            '<div class="small dim">{size} · sha256 <span class="mono">{sha}…</span></div></div>'.format(
                n=esc(name), size=esc(human_bytes(info["bytes"])),
                sha=esc(info["sha256"][:16])))
    body = """
<h1>Export Center</h1>
<p class="dim">All exports are generated locally from scan run <strong>#{run_id}</strong>. Paths are full paths, never truncated. CSV uses UTF-8 with BOM and formula-injection protection; JSONL carries raw values. Byte sizes and SHA-256 were computed from the actual files at build time.</p>
<div class="alert alert--warn"><strong>Privacy:</strong> these exports contain your personal filenames and folder structure. Do not share them publicly or commit them to any repository.</div>
<div class="exports-list">{items}</div>
""".format(items="\n".join(rows), run_id=esc(run["id"]))
    return _shell("Export Center", "exports.html", body, run,
                  fixture_label=fixture_label)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def build_report(conn, scan_id, output_dir, *, page_rows=None,
                 fixture_label=False, logger=None):
    """Build (or rebuild) the report for an existing run. No rescanning.

    Returns dict with report_dir and file stats. Raises on failure; the
    caller (CLI) records report_state accordingly.
    """
    logger = logger or _NullLogger()
    started = time.time()

    run = run_record(conn, scan_id)
    if run is None:
        raise ValueError("Scan run {} not found in database.".format(scan_id))

    started_stamp = datetime.fromtimestamp(
        run["started_at_epoch"] or started).astimezone().strftime("%Y%m%d_%H%M%S")
    report_dir = os.path.join(output_dir, config.REPORT_SUBDIR,
                              "run_{}_{}".format(run["id"], started_stamp))
    exports_dir = os.path.join(report_dir, "exports")
    os.makedirs(exports_dir, exist_ok=True)

    # Static assets.
    for asset in ("report.css", "report.js"):
        shutil.copyfile(os.path.join(TEMPLATE_DIR, asset),
                        os.path.join(report_dir, asset))

    # Exports first (they double as the manifest data source).
    generated_files = generate_exports(conn, scan_id, exports_dir)

    overview = run_overview(conn, scan_id)
    categories = category_breakdown(conn, scan_id)
    extensions = extension_breakdown(conn, scan_id)
    largest_files_ = largest_files(conn, scan_id, limit=200)
    largest_dirs = largest_directories(conn, scan_id, limit=200)
    hidden_dirs, hidden_files = largest_hidden(conn, scan_id, limit=25)
    empties = empty_directories(conn, scan_id)
    zero_bytes = zero_byte_files(conn, scan_id)
    candidates = review_candidates(conn, scan_id)
    same_size = same_size_candidates(conn, scan_id)

    # index.html
    _write_atomic(os.path.join(report_dir, "index.html"),
                  build_index(conn, scan_id, run, overview, categories,
                              extensions, largest_files_, largest_dirs,
                              len(empties), len(zero_bytes),
                              fixture_label=fixture_label,
                              review_count=len(candidates)))

    # files.html + data chunks/inline
    files_html, records, chunked = build_files_search_page(
        conn, scan_id, run, report_dir, fixture_label=fixture_label)
    _write_atomic(os.path.join(report_dir, "files.html"), files_html)

    # Static paginated file tables
    static_pages = build_static_file_pages(conn, scan_id, run, report_dir,
                                           fixture_label=fixture_label,
                                           page_rows=page_rows)

    _write_atomic(os.path.join(report_dir, "file_types.html"),
                  build_file_types_page(categories, extensions, run,
                                        fixture_label=fixture_label))
    _write_atomic(os.path.join(report_dir, "largest_files.html"),
                  build_largest_files_page(largest_files_, run,
                                           fixture_label=fixture_label))
    _write_atomic(os.path.join(report_dir, "largest_directories.html"),
                  build_largest_directories_page(largest_dirs, run,
                                                 fixture_label=fixture_label))
    _write_atomic(os.path.join(report_dir, "empty_directories.html"),
                  build_list_page(
                      "Empty Directories", "empty_directories.html", empties,
                      ["#", "Directory"],
                      lambda i, item: [str(i), _path_cell(item)],
                      run, fixture_label=fixture_label,
                      note="Successfully enumerated directories with zero child entries. "
                           "A directory whose enumeration failed is NOT listed here.",
                      export_hint="Complete aggregates: exports/directories.csv. Full hierarchy: exports/directory_tree.txt."))
    _write_atomic(os.path.join(report_dir, "zero_byte_files.html"),
                  build_list_page(
                      "Zero-byte Files", "zero_byte_files.html", zero_bytes,
                      ["#", "File", "Path"],
                      lambda i, item: [str(i), esc(item["name"]),
                                       _path_cell(item["relative_path"])],
                      run, fixture_label=fixture_label,
                      note="Regular files whose size was successfully observed as exactly 0 bytes. "
                           "Unavailable sizes are NOT counted here.",
                      export_hint="Machine-readable: exports/files.csv."))
    _write_atomic(os.path.join(report_dir, "review_candidates.html"),
                  build_review_candidates_page(candidates, same_size, run,
                                               fixture_label=fixture_label))
    _write_atomic(os.path.join(report_dir, "hidden.html"),
                  build_hidden_page(overview, hidden_dirs, hidden_files, run,
                                    fixture_label=fixture_label))
    _write_atomic(os.path.join(report_dir, "directory_explorer.html"),
                  build_directory_explorer(conn, scan_id, run,
                                           fixture_label=fixture_label))
    _write_atomic(os.path.join(report_dir, "scan_issues.html"),
                  build_issues_page(conn, scan_id, run,
                                    fixture_label=fixture_label))
    _write_atomic(os.path.join(report_dir, "methodology.html"),
                  build_methodology_page(run, fixture_label=fixture_label))
    _write_atomic(os.path.join(report_dir, "exports.html"),
                  build_exports_page(report_dir, generated_files, run,
                                     fixture_label=fixture_label))

    from . import database
    database.set_report_state(conn, scan_id, "built", report_dir)
    database.record_report_build(
        conn, scan_id, started_at=started, finished_at=time.time(),
        status="built", output_dir=report_dir,
        file_count=len(os.listdir(report_dir)), notes=None)

    logger.info("Report built for run %s at %s", scan_id, report_dir)
    return {
        "report_dir": report_dir,
        "exports_dir": exports_dir,
        "static_file_pages": static_pages,
        "inventory_records": len(records),
        "chunked_search_data": chunked,
        "files": generated_files,
    }


class _NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass
