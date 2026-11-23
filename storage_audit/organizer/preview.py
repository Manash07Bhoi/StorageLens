"""Offline HTML preview of an organization plan (approval artifact).

Self-contained, no network, no frameworks. Dark-first design system shared
with the V1 report (obsidian background, orange/gold accents). Everything
rendered here is escaped; long paths wrap. Data is embedded as JSON with
HTM/JS-significant characters escaped.
"""

import html
import json
import os

_ACCENT = "#F97316"
_GOLD = "#F5B942"


def _esc_json(obj):
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return (raw.replace("&", "\\u0026").replace("<", "\\u003c")
            .replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def render_plan_preview(conn, plan_id):
    plan = conn.execute("SELECT * FROM organization_plans WHERE id = ?",
                        (plan_id,)).fetchone()
    if plan is None:
        raise ValueError("plan {} does not exist".format(plan_id))
    ops = conn.execute(
        "SELECT seq, action, source_rel, dest_rel, size_bytes, status, conflict"
        " FROM organization_operations WHERE plan_id = ? ORDER BY seq",
        (plan_id,)).fetchall()
    events = conn.execute(
        "SELECT event, detail, occurred_at_epoch FROM organization_events"
        " WHERE plan_id = ? ORDER BY id", (plan_id,)).fetchall()

    move_count = sum(1 for o in ops if o["action"] == "move")
    conflict_count = sum(1 for o in ops if o["status"] == "conflict")
    total_bytes = int(plan["total_bytes"] or 0)

    rows_json = _esc_json([{
        "seq": o["seq"], "action": o["action"], "src": o["source_rel"],
        "dst": o["dest_rel"], "size": int(o["size_bytes"] or 0),
        "status": o["status"], "conflict": o["conflict"] or "",
    } for o in ops])

    e = html.escape
    move_banner = ""
    if move_count:
        move_banner = (
            '<div class="banner danger"><strong>DESTRUCTIVE PLAN.</strong> '
            '{} move operation(s). Applying with <code>--acknowledge-source-removal</code> '
            'will DELETE each source file after its destination copy is verified. '
            'Prefer <code>--action copy-keep</code> (default) if unsure.</div>'
        ).format(move_count)
    skipped_note = ""
    skipped_events = [ev for ev in events if ev["event"] == "skipped_source"]
    if skipped_events:
        skipped_note = ('<div class="banner warn">{} entr{} skipped at plan time '
                        '(see event log below).</div>').format(
                            len(skipped_events),
                            "y was" if len(skipped_events) == 1 else "ies were")

    events_rows = "\n".join(
        '<tr><td class="mono">{}</td><td>{}</td><td>{}</td></tr>'.format(
            e(ev["event"]),
            e((ev["detail"] or "")[:400]),
            time_str(ev["occurred_at_epoch"]))
        for ev in events[:200])

    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>StorageLens — Organization Plan #{plan_id}</title>
<style>
:root {{ --bg:#0A0A0F; --panel:#15191D; --panel2:#1B2127; --line:#262E36;
        --text:#F5F5F5; --muted:#A9B4BD; --accent:{accent}; --gold:{gold};
        --danger:#F87171; --ok:#34D399; --warn:#FBBF24; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text);
       font:15px/1.55 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif; }}
header {{ padding:20px 16px 14px; border-bottom:1px solid var(--line);
         background:linear-gradient(180deg,#10141A,#0A0A0F); position:sticky; top:0; }}
h1 {{ margin:0 0 4px; font-size:20px; letter-spacing:.2px; }}
h1 .logo {{ color:var(--accent); }}
.sub {{ color:var(--muted); font-size:13px; }}
main {{ padding:16px; max-width:1180px; margin:0 auto; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
         gap:10px; margin:14px 0 18px; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:14px;
        padding:12px 14px; }}
.card .k {{ color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.8px; }}
.card .v {{ font-size:22px; font-weight:700; margin-top:2px; }}
.card .v small {{ font-size:12px; color:var(--muted); font-weight:400; }}
.danger-t {{ color:var(--danger); }} .warn-t {{ color:var(--warn); }} .ok-t {{ color:var(--ok); }}
.banner {{ border-radius:12px; padding:12px 14px; margin:12px 0; border:1px solid; }}
.banner.danger {{ background:#2A1215; border-color:#7F1D1D; color:#FECACA; }}
.banner.warn {{ background:#241A08; border-color:#713F12; color:#FDE68A; }}
.toolbar {{ display:flex; gap:8px; flex-wrap:wrap; margin:14px 0; }}
input,select {{ background:var(--panel); color:var(--text); border:1px solid var(--line);
       border-radius:10px; padding:10px 12px; font-size:14px; min-height:44px; }}
input {{ flex:1 1 240px; }}
table {{ width:100%; border-collapse:collapse; background:var(--panel);
        border:1px solid var(--line); border-radius:14px; overflow:hidden; }}
th,td {{ text-align:left; padding:9px 12px; border-bottom:1px solid var(--line);
        font-size:13px; vertical-align:top; }}
th {{ background:var(--panel2); color:var(--muted); font-size:11px;
     text-transform:uppercase; letter-spacing:.8px; position:sticky; top:0; }}
tr:last-child td {{ border-bottom:none; }}
.mono {{ font-family:ui-monospace,Menlo,Consolas,monospace; font-size:12px; }}
.path {{ word-break:break-all; }}
.tag {{ display:inline-block; border-radius:999px; padding:2px 9px; font-size:11px;
       border:1px solid var(--line); color:var(--muted); white-space:nowrap; }}
.tag.move {{ color:#FDBA74; border-color:#7C2D12; }}
.tag.copy-keep {{ color:#93C5FD; border-color:#1E3A5F; }}
.tag.conflict {{ color:var(--warn); border-color:#713F12; }}
.tag.planned {{ color:var(--ok); border-color:#064E3B; }}
.pager {{ display:flex; justify-content:space-between; align-items:center; margin:12px 2px;
         color:var(--muted); font-size:13px; gap:10px; flex-wrap:wrap; }}
button {{ background:var(--accent); color:#111; border:none; border-radius:10px;
        min-height:44px; min-width:44px; padding:10px 16px; font-weight:700; cursor:pointer; }}
button.secondary {{ background:var(--panel2); color:var(--text); border:1px solid var(--line); }}
button:disabled {{ opacity:.35; cursor:not-allowed; }}
button:focus-visible,input:focus-visible,select:focus-visible {{ outline:3px solid var(--gold); outline-offset:2px; }}
code {{ background:#0E1216; border:1px solid var(--line); border-radius:6px; padding:1px 6px; }}
h2 {{ font-size:15px; margin:22px 0 8px; color:var(--gold); letter-spacing:.4px; }}
.small {{ color:var(--muted); font-size:12px; }}
@media (prefers-reduced-motion: reduce) {{ * {{ animation:none!important; transition:none!important; }} }}
@media (max-width:560px) {{ .cards {{ grid-template-columns:repeat(2,1fr); }} body {{ font-size:14px; }} }}
</style></head>
<body>
<header>
  <h1><span class="logo">StorageLens</span> — Organization Plan #{plan_id}</h1>
  <div class="sub">Preview only. Nothing has been modified. Generated locally · no network ·
  based on scan run #{scan_id} · rule <code>{rule}</code> v{rule_ver} · action <code>{action}</code></div>
</header>
<main>
  <div class="cards">
    <div class="card"><div class="k">Operations</div><div class="v">{n_ops}</div></div>
    <div class="card"><div class="k">Total size</div><div class="v">{total_h} <small></small></div></div>
    <div class="card"><div class="k">Move ops</div><div class="v {move_cls}">{move_n}</div></div>
    <div class="card"><div class="k">Conflicts</div><div class="v {conf_cls}">{conflict_n}</div></div>
    <div class="card"><div class="k">Plan status</div><div class="v" style="font-size:16px;padding-top:5px">{status}</div></div>
  </div>
  {move_banner}
  {skipped_note}
  <div class="banner warn" style="background:#0F1B24;border-color:#164E63;color:#BAE6FD">
    <strong>How to approve:</strong> review every row. Conflicts are excluded automatically.
    Copy-keep (default) never deletes anything. Removal of sources happens only with
    <code>move</code> + <code>--acknowledge-source-removal</code>, and only after each copy is verified.
    To apply: <code>python storage_audit.py organize-approve --plan-id {plan_id}</code> then
    <code>organize-apply --plan-id {plan_id}</code>.
  </div>

  <div class="toolbar" role="search">
    <input id="q" type="search" placeholder="Filter paths (metadata search — not file contents)…" aria-label="Filter operations">
    <select id="f" aria-label="Filter by status">
      <option value="">All rows</option><option value="planned">Planned only</option>
      <option value="conflict">Conflicts</option><option value="move">Moves</option>
      <option value="copy-keep">Copies</option>
    </select>
    <select id="per" aria-label="Rows per page">
      <option>100</option><option selected>250</option><option>500</option>
    </select>
  </div>
  <div class="small" id="count"></div>
  <div id="tablewrap"><table aria-describedby="count">
    <thead><tr><th>#</th><th>Action</th><th>Source → destination</th><th>Size</th><th>Status</th></tr></thead>
    <tbody id="rows"></tbody>
  </table></div>
  <div class="pager"><button class="secondary" id="prev">← Previous</button>
    <span id="pageinfo" class="mono"></span>
    <button class="secondary" id="next">Next →</button></div>

  <h2>Target root</h2><div class="mono path">{target_root}</div>

  <h2>Event log (latest 200)</h2>
  <div class="table-wrap"><table><thead><tr><th>Event</th><th>Detail</th><th>When (local)</th></tr></thead>
  <tbody>{events_rows}</tbody></table></div>

  <p class="small">Private data notice: this file lists personal paths. Keep it local; do not share it.
  StorageLens never uploads it. Undo: <code>organize-undo --operation-id N</code> (move) restores the source location;
  for copy-keep it deletes only the created copy, with <code>--approve-delete</code>.</p>
</main>
<script>
const OPS = {rows_json};
let filtered = OPS.slice(), page = 0;
const q = document.getElementById('q'), f = document.getElementById('f'),
      per = document.getElementById('per'), tbody = document.getElementById('rows'),
      count = document.getElementById('count'), pageinfo = document.getElementById('pageinfo');
function fmtSize(n) {{ const u=['B','KiB','MiB','GiB','TiB']; let i=0,v=n; while(v>=1024&&i<u.length-1){{v/=1024;i++;}} return (i?v.toFixed(1):v)+' '+u[i]; }}
function esc(s) {{ return String(s).replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c])); }}
function applyFilters() {{
  const term = q.value.trim().toLowerCase(), mode = f.value;
  filtered = OPS.filter(o =>
    (!mode || (mode==='move'||mode==='copy-keep' ? o.action===mode : o.status===mode)) &&
    (!term || o.src.toLowerCase().includes(term) || o.dst.toLowerCase().includes(term)));
  page = 0; render();
}}
function render() {{
  const perPage = parseInt(per.value, 10), pages = Math.max(1, Math.ceil(filtered.length / perPage));
  if (page >= pages) page = pages - 1;
  const slice = filtered.slice(page * perPage, (page + 1) * perPage);
  tbody.innerHTML = slice.map(o =>
    '<tr><td class="mono">'+o.seq+'</td>' +
    '<td><span class="tag '+esc(o.action)+'">'+esc(o.action)+'</span></td>' +
    '<td class="path mono">'+esc(o.src)+'<br>→ '+esc(o.dst)+'</td>' +
    '<td class="mono">'+fmtSize(o.size)+'</td>' +
    '<td><span class="tag '+esc(o.status==='planned'&&!o.conflict?'planned':'conflict')+'">'+esc(o.conflict||o.status)+'</span></td></tr>'
  ).join('');
  count.textContent = filtered.length.toLocaleString()+' of '+OPS.length.toLocaleString()+' operations shown';
  pageinfo.textContent = 'Page '+(page+1)+' / '+pages;
  document.getElementById('prev').disabled = page===0;
  document.getElementById('next').disabled = page>=pages-1;
}}
q.addEventListener('input', applyFilters); f.addEventListener('change', applyFilters); per.addEventListener('change', applyFilters);
document.getElementById('prev').addEventListener('click', () => {{ if(page>0){{page--;render();}} }});
document.getElementById('next').addEventListener('click', () => {{ page++; render(); }});
render();
</script>
</body></html>""".format(
        plan_id=plan["id"], scan_id=plan["scan_id"], rule=e(plan["rule_name"]),
        rule_ver=e(plan["rule_version"]), action=e(plan["action"]),
        n_ops=len(ops), total_h=fmt_bytes(total_bytes),
        move_n=move_count, move_cls="danger-t" if move_count else "ok-t",
        conflict_n=conflict_count, conf_cls="warn-t" if conflict_count else "ok-t",
        status=e(plan["status"]), move_banner=move_banner,
        skipped_note=skipped_note, events_rows=events_rows,
        target_root=e(plan["target_root"]), rows_json=rows_json,
        accent=_ACCENT, gold=_GOLD)


def fmt_bytes(n):
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    v = float(n); i = 0
    while v >= 1024 and i < len(units) - 1:
        v /= 1024; i += 1
    return ("{:.1f} {}".format(v, units[i]) if i else "{} B".format(int(v)))


def time_str(epoch):
    import datetime
    try:
        return datetime.datetime.fromtimestamp(int(epoch)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "n/a"


def write_plan_preview(conn, plan_id, output_path):
    html_doc = render_plan_preview(conn, plan_id)
    directory = os.path.dirname(output_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = output_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(html_doc)
    os.replace(tmp, output_path)
    return output_path
