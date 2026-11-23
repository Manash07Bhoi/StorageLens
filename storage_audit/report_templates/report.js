/* Android Storage Audit — offline report behavior.
   Loaded after the inventory data. No network access. */
"use strict";

(function () {
  var inventory = Array.isArray(window.__INVENTORY) ? window.__INVENTORY : [];

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function humanBytes(n) {
    if (n === null || n === undefined || isNaN(n)) return "Unavailable";
    var size = Number(n), units = ["B", "KiB", "MiB", "GiB", "TiB"], i = 0;
    while (size >= 1024 && i < units.length - 1) { size /= 1024; i++; }
    return (i === 0 ? String(size) + " B" : size.toFixed(2) + " " + units[i]);
  }

  function initInventorySearch() {
    var root = document.getElementById("inventory-browser");
    if (!root) return;

    var els = {
      q: document.getElementById("f-search"),
      ext: document.getElementById("f-extension"),
      category: document.getElementById("f-category"),
      kind: document.getElementById("f-kind"),
      hiddenOnly: document.getElementById("f-hidden"),
      errorsOnly: document.getElementById("f-errors"),
      minSize: document.getElementById("f-min-size"),
      maxSize: document.getElementById("f-max-size"),
      sort: document.getElementById("f-sort"),
      pageSize: document.getElementById("f-page-size"),
      prev: document.getElementById("inv-prev"),
      next: document.getElementById("inv-next"),
      pageInfo: document.getElementById("inv-page-info"),
      count: document.getElementById("inv-count"),
      tbody: document.getElementById("inv-tbody"),
      empty: document.getElementById("inv-empty"),
      reset: document.getElementById("inv-reset")
    };

    var state = { page: 1 };

    function filtered() {
      var q = (els.q.value || "").trim().toLowerCase();
      var ext = els.ext.value;
      var category = els.category.value;
      var kind = els.kind.value;
      var hiddenOnly = els.hiddenOnly.checked;
      var errorsOnly = els.errorsOnly.checked;
      var minSize = els.minSize.value === "" ? null : Number(els.minSize.value);
      var maxSize = els.maxSize.value === "" ? null : Number(els.maxSize.value);

      var rows = inventory.filter(function (row) {
        if (q) {
          var hay = ((row.name || "") + " " + (row.relative_path || "")).toLowerCase();
          if (hay.indexOf(q) === -1) return false;
        }
        if (ext && (row.extension || "(none)") !== ext) return false;
        if (category && row.category !== category) return false;
        if (kind && row.kind !== kind) return false;
        if (hiddenOnly && !row.is_hidden) return false;
        if (errorsOnly && row.stat_status === "ok") return false;
        if (minSize !== null && !(row.size_bytes >= minSize)) return false;
        if (maxSize !== null && !(row.size_bytes <= maxSize)) return false;
        return true;
      });

      var sortKey = els.sort.value;
      var cmp = {
        "name-asc": function (a, b) { return String(a.normalized_name || "").localeCompare(String(b.normalized_name || "")); },
        "path-asc": function (a, b) { return String(a.relative_path || "").localeCompare(String(b.relative_path || "")); },
        "size-desc": function (a, b) { return (b.size_bytes || 0) - (a.size_bytes || 0); },
        "size-asc": function (a, b) { return (a.size_bytes || 0) - (b.size_bytes || 0); },
        "mtime-desc": function (a, b) { return (b.mtime_epoch || 0) - (a.mtime_epoch || 0); },
        "mtime-asc": function (a, b) { return (a.mtime_epoch || 0) - (b.mtime_epoch || 0); },
        "category-asc": function (a, b) { return String(a.category).localeCompare(String(b.category)); }
      }[sortKey] || function (a, b) { return 0; };
      rows.sort(cmp);
      return rows;
    }

    function render() {
      var rows = filtered();
      var pageSize = Math.max(1, Number(els.pageSize.value) || 50);
      var total = rows.length;
      var pages = Math.max(1, Math.ceil(total / pageSize));
      if (state.page > pages) state.page = pages;
      var start = (state.page - 1) * pageSize;
      var slice = rows.slice(start, start + pageSize);

      els.count.textContent = total + " record" + (total === 1 ? "" : "s") +
        " (page " + state.page + " of " + pages + ")";
      els.pageInfo.textContent = "Page " + state.page + " of " + pages;

      if (total === 0) {
        els.tbody.innerHTML = "";
        els.empty.hidden = false;
      } else {
        els.empty.hidden = true;
        var html = slice.map(function (row) {
          var kind = row.kind || "unknown";
          var badge = row.is_hidden ? " <span aria-label=\"hidden\">·</span>" : "";
          return "<tr><td class=\"path\">" + escapeHtml(row.relative_path) + badge + "</td>" +
            "<td>" + escapeHtml((row.extension || "(none)")) + "</td>" +
            "<td>" + escapeHtml(row.category) + "</td>" +
            "<td class=\"num\">" + escapeHtml(humanBytes(row.size_bytes)) + "</td>" +
            "<td>" + escapeHtml(row.mtime_iso || "Unavailable") + "</td>" +
            "<td>" + escapeHtml(kind) + (row.stat_status !== "ok" ? " (stat failed)" : "") + "</td></tr>";
        }).join("");
        els.tbody.innerHTML = html;
      }

      els.prev.setAttribute("aria-disabled", state.page <= 1 ? "true" : "false");
      els.next.setAttribute("aria-disabled", state.page >= pages ? "true" : "false");
      els.prev.disabled = state.page <= 1;
      els.next.disabled = state.page >= pages;
    }

    ["input", "change"].forEach(function (eventName) {
      [els.q, els.ext, els.category, els.kind, els.hiddenOnly, els.errorsOnly,
       els.minSize, els.maxSize, els.sort, els.pageSize].forEach(function (el) {
        el.addEventListener(eventName, function () { state.page = 1; render(); });
      });
    });
    els.prev.addEventListener("click", function () { if (state.page > 1) { state.page--; render(); } });
    els.next.addEventListener("click", function () { state.page++; render(); });
    els.reset.addEventListener("click", function () {
      els.q.value = ""; els.ext.value = ""; els.category.value = "";
      els.kind.value = ""; els.hiddenOnly.checked = false; els.errorsOnly.checked = false;
      els.minSize.value = ""; els.maxSize.value = ""; els.sort.value = "path-asc";
      state.page = 1; render();
    });

    render();
  }

  function initSortableTables() {
    var tables = document.querySelectorAll("table[data-sortable]");
    tables.forEach(function (table) {
      var headers = table.querySelectorAll("thead th");
      headers.forEach(function (th, index) {
        var key = th.getAttribute("data-sort-key");
        if (!key) return;
        th.setAttribute("tabindex", "0");
        th.setAttribute("role", "button");
        th.setAttribute("aria-sort", "none");
        function applySort() {
          var dir = th.getAttribute("aria-sort") === "ascending" ? "descending" : "ascending";
          headers.forEach(function (h) { h.setAttribute("aria-sort", "none"); });
          th.setAttribute("aria-sort", dir);
          var tbody = table.querySelector("tbody");
          var rows = Array.prototype.slice.call(tbody.querySelectorAll("tr"));
          var numeric = th.getAttribute("data-sort-numeric") === "true";
          rows.sort(function (a, b) {
            var av = a.cells[index].getAttribute("data-sort-value") || a.cells[index].textContent.trim();
            var bv = b.cells[index].getAttribute("data-sort-value") || b.cells[index].textContent.trim();
            if (numeric) { av = parseFloat(av) || 0; bv = parseFloat(bv) || 0; return dir === "ascending" ? av - bv : bv - av; }
            return dir === "ascending" ? av.localeCompare(bv) : bv.localeCompare(av);
          });
          rows.forEach(function (row) { tbody.appendChild(row); });
        }
        th.addEventListener("click", applySort);
        th.addEventListener("keydown", function (event) {
          if (event.key === "Enter" || event.key === " ") { event.preventDefault(); applySort(); }
        });
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initInventorySearch();
    initSortableTables();
  });
})();
