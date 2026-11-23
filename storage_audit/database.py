"""SQLite persistence: schema, migrations, transactions, run lifecycle.

Parameterized SQL only. Foreign keys enforced. Runs are isolated by scan_id.
A completed run is immutable: the only permitted mutations after a terminal
status involve report-build bookkeeping (report_state / report_built_at_epoch
/ report_dir and report_builds rows), never inventory rows.
"""

import json
import os
import sqlite3
import time

from . import SCHEMA_VERSION, CLASSIFICATION_VERSION

STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_COMPLETED_WITH_GAPS = "completed_with_gaps"
STATUS_CANCELLED = "cancelled"
STATUS_FAILED = "failed"
STATUS_INTERRUPTED = "interrupted_or_recovered"

TERMINAL_STATUSES = {
    STATUS_COMPLETED,
    STATUS_COMPLETED_WITH_GAPS,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_INTERRUPTED,
}

_ALLOWED_TRANSITIONS = {
    STATUS_RUNNING: TERMINAL_STATUSES,
    STATUS_COMPLETED: set(),
    STATUS_COMPLETED_WITH_GAPS: set(),
    STATUS_CANCELLED: set(),
    STATUS_FAILED: set(),
    STATUS_INTERRUPTED: set(),
}


class DatabaseError(Exception):
    pass


class InvalidStateTransition(DatabaseError):
    pass


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS scan_runs (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_version            TEXT NOT NULL,
    schema_version          INTEGER NOT NULL,
    requested_root          TEXT NOT NULL,
    root_path               TEXT NOT NULL,
    scope_label             TEXT NOT NULL DEFAULT 'accessible shared-storage inventory',
    started_at_epoch        INTEGER NOT NULL,
    finished_at_epoch       INTEGER,
    duration_seconds        REAL,
    status                  TEXT NOT NULL
        CHECK (status IN ('running','completed','completed_with_gaps',
                          'cancelled','failed','interrupted_or_recovered')),
    pid                     INTEGER,
    files_seen              INTEGER NOT NULL DEFAULT 0,
    files_recorded          INTEGER NOT NULL DEFAULT 0,
    directories_seen        INTEGER NOT NULL DEFAULT 0,
    directories_recorded    INTEGER NOT NULL DEFAULT 0,
    symlinks_seen           INTEGER NOT NULL DEFAULT 0,
    other_entries_seen      INTEGER NOT NULL DEFAULT 0,
    errors_count            INTEGER NOT NULL DEFAULT 0,
    skipped_count           INTEGER NOT NULL DEFAULT 0,
    excluded_count          INTEGER NOT NULL DEFAULT 0,
    volume_total_bytes      INTEGER,
    volume_used_bytes       INTEGER,
    volume_free_bytes       INTEGER,
    volume_status           TEXT NOT NULL DEFAULT 'unavailable',
    include_hidden          INTEGER NOT NULL DEFAULT 1,
    follow_symlinks         INTEGER NOT NULL DEFAULT 0,
    scan_mode               TEXT NOT NULL DEFAULT 'metadata_only',
    classification_version  TEXT NOT NULL,
    environment_json        TEXT NOT NULL DEFAULT '{}',
    exclusions_json         TEXT NOT NULL DEFAULT '[]',
    coverage_incomplete     INTEGER NOT NULL DEFAULT 0,
    coverage_notes          TEXT NOT NULL DEFAULT '',
    report_state            TEXT NOT NULL DEFAULT 'not_built',
    report_built_at_epoch   INTEGER,
    report_dir              TEXT,
    batch_size              INTEGER NOT NULL DEFAULT 500
);

CREATE TABLE IF NOT EXISTS entries (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id                 INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE RESTRICT,
    relative_path           TEXT NOT NULL,
    absolute_path           TEXT NOT NULL,
    name                    TEXT NOT NULL,
    normalized_name         TEXT NOT NULL,
    parent_relative_path    TEXT NOT NULL,
    depth                   INTEGER NOT NULL,
    kind                    TEXT NOT NULL
        CHECK (kind IN ('directory','file','symlink','other','unknown')),
    entry_subtype           TEXT,
    extension               TEXT,
    extension_original      TEXT,
    compound_extension      TEXT,
    mime_guess              TEXT,
    category                TEXT NOT NULL,
    size_bytes              INTEGER,
    size_status             TEXT NOT NULL DEFAULT 'not_applicable'
        CHECK (size_status IN ('observed','unavailable','failed','not_applicable')),
    mtime_epoch             INTEGER,
    mtime_iso               TEXT,
    timestamp_status        TEXT NOT NULL DEFAULT 'unavailable'
        CHECK (timestamp_status IN ('observed','unavailable','failed','not_applicable')),
    birthtime_epoch         INTEGER,
    birthtime_status        TEXT NOT NULL DEFAULT 'unavailable'
        CHECK (birthtime_status IN ('observed','unavailable','failed','not_applicable')),
    is_hidden               INTEGER NOT NULL DEFAULT 0,
    is_symlink              INTEGER NOT NULL DEFAULT 0,
    symlink_target          TEXT,
    symlink_target_status   TEXT,
    is_readable             INTEGER,
    stat_status             TEXT NOT NULL DEFAULT 'ok',
    observation_epoch       INTEGER NOT NULL,
    classification_version  TEXT NOT NULL,
    device_id               INTEGER,
    skip_reason             TEXT,
    error_category          TEXT,
    error_message           TEXT,
    UNIQUE (scan_id, relative_path)
);

CREATE INDEX IF NOT EXISTS idx_entries_scan        ON entries(scan_id);
CREATE INDEX IF NOT EXISTS idx_entries_scan_kind   ON entries(scan_id, kind);
CREATE INDEX IF NOT EXISTS idx_entries_parent      ON entries(scan_id, parent_relative_path);
CREATE INDEX IF NOT EXISTS idx_entries_name        ON entries(scan_id, normalized_name);
CREATE INDEX IF NOT EXISTS idx_entries_extension   ON entries(scan_id, extension);
CREATE INDEX IF NOT EXISTS idx_entries_category    ON entries(scan_id, category);
CREATE INDEX IF NOT EXISTS idx_entries_size        ON entries(scan_id, size_bytes);

CREATE TABLE IF NOT EXISTS directory_stats (
    scan_id               INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE RESTRICT,
    relative_path         TEXT NOT NULL,
    direct_files          INTEGER NOT NULL,
    direct_dirs           INTEGER NOT NULL,
    recursive_files       INTEGER NOT NULL,
    recursive_dirs        INTEGER NOT NULL,
    recursive_file_bytes  INTEGER NOT NULL,
    is_empty              INTEGER NOT NULL,
    PRIMARY KEY (scan_id, relative_path)
);

CREATE TABLE IF NOT EXISTS scan_issues (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id           INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE RESTRICT,
    path              TEXT NOT NULL,
    operation         TEXT NOT NULL,
    error_category    TEXT NOT NULL,
    error_code        INTEGER,
    error_message     TEXT NOT NULL,
    occurred_at_epoch INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_issues_scan ON scan_issues(scan_id);

CREATE TABLE IF NOT EXISTS report_builds (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id           INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE RESTRICT,
    started_at_epoch  INTEGER NOT NULL,
    finished_at_epoch INTEGER,
    status            TEXT NOT NULL CHECK (status IN ('built','failed')),
    output_dir        TEXT,
    file_count        INTEGER,
    notes             TEXT
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    applied_at  INTEGER NOT NULL
);
"""

SCHEMA_V2_SQL = """
CREATE TABLE IF NOT EXISTS organization_plans (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id             INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE RESTRICT,
    rule_name           TEXT NOT NULL,
    rule_version        TEXT NOT NULL,
    target_root         TEXT NOT NULL,
    action              TEXT NOT NULL DEFAULT 'copy-keep'
        CHECK (action IN ('copy-keep','move')),
    hash_verify         INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft','ready_for_review','approved','executing',
                          'completed','completed_with_errors','cancelled',
                          'failed','recovery_required')),
    created_at_epoch    INTEGER NOT NULL,
    updated_at_epoch    INTEGER NOT NULL,
    approved_at_epoch   INTEGER,
    approval_note       TEXT NOT NULL DEFAULT '',
    total_operations    INTEGER NOT NULL DEFAULT 0,
    total_bytes         INTEGER NOT NULL DEFAULT 0,
    conflicts           INTEGER NOT NULL DEFAULT 0,
    invalid             INTEGER NOT NULL DEFAULT 0,
    notes               TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS organization_operations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id           INTEGER NOT NULL REFERENCES organization_plans(id) ON DELETE CASCADE,
    scan_id           INTEGER NOT NULL,
    seq               INTEGER NOT NULL,
    action            TEXT NOT NULL CHECK (action IN ('copy-keep','move')),
    source_rel        TEXT NOT NULL,
    source_abs        TEXT NOT NULL,
    dest_rel          TEXT NOT NULL,
    dest_abs          TEXT NOT NULL,
    size_bytes        INTEGER,
    dest_size_bytes   INTEGER,
    status            TEXT NOT NULL DEFAULT 'planned'
        CHECK (status IN ('planned','conflict','in_progress','completed',
                          'failed','interrupted','rolled_back','skipped')),
    conflict          TEXT,
    error             TEXT,
    started_at_epoch  INTEGER,
    finished_at_epoch INTEGER,
    UNIQUE (plan_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_operations_plan ON organization_operations(plan_id);
CREATE INDEX IF NOT EXISTS idx_operations_status ON organization_operations(status);

CREATE TABLE IF NOT EXISTS organization_events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id           INTEGER REFERENCES organization_plans(id) ON DELETE CASCADE,
    operation_id      INTEGER REFERENCES organization_operations(id) ON DELETE CASCADE,
    event             TEXT NOT NULL,
    detail            TEXT NOT NULL DEFAULT '',
    occurred_at_epoch INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_org_events_plan ON organization_events(plan_id);
CREATE INDEX IF NOT EXISTS idx_org_events_op ON organization_events(operation_id);
"""

SCHEMA_V3_SQL = """
ALTER TABLE organization_plans ADD COLUMN eligible_files INTEGER NOT NULL DEFAULT 0;
ALTER TABLE organization_plans ADD COLUMN excluded_entries INTEGER NOT NULL DEFAULT 0;
ALTER TABLE organization_plans ADD COLUMN scope_policy_version TEXT NOT NULL DEFAULT '';
ALTER TABLE organization_plans ADD COLUMN scope_canonical TEXT NOT NULL DEFAULT '';
ALTER TABLE organization_plans ADD COLUMN scope_allowed_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE organization_plans ADD COLUMN scope_excluded_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE organization_plans ADD COLUMN scope_validation_json TEXT NOT NULL DEFAULT '{}';
"""


_ENTRY_COLUMNS = [
    "scan_id", "relative_path", "absolute_path", "name", "normalized_name",
    "parent_relative_path", "depth", "kind", "entry_subtype", "extension",
    "extension_original", "compound_extension", "mime_guess", "category",
    "size_bytes", "size_status", "mtime_epoch", "mtime_iso", "timestamp_status",
    "birthtime_epoch", "birthtime_status", "is_hidden", "is_symlink",
    "symlink_target", "symlink_target_status", "is_readable", "stat_status",
    "observation_epoch", "classification_version", "device_id", "skip_reason",
    "error_category", "error_message",
]
_INSERT_ENTRY_SQL = (
    "INSERT INTO entries ({}) VALUES ({})".format(
        ", ".join(_ENTRY_COLUMNS), ", ".join("?" for _ in _ENTRY_COLUMNS))
)


def connect(db_path):
    """Open (creating if needed) the database with conservative pragmas."""
    directory = os.path.dirname(db_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def migrate(conn):
    """Apply forward-only migrations. Idempotent. Preserves existing data."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current > SCHEMA_VERSION:
        raise DatabaseError(
            "Database schema version {} is newer than this tool supports ({}). "
            "Upgrade the tool; do not downgrade the database.".format(
                current, SCHEMA_VERSION))
    applied = {row[0] for row in conn.execute(
        "SELECT version FROM schema_migrations").fetchall()} if _table_exists(
            conn, "schema_migrations") else set()
    if current == 0:
        with conn:
            if 1 not in applied:
                conn.executescript(SCHEMA_SQL)
                conn.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at)"
                    " VALUES (?, ?)", (1, int(time.time())))
            if 2 not in applied:
                conn.executescript(SCHEMA_V2_SQL)
                conn.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at)"
                    " VALUES (?, ?)", (2, int(time.time())))
            if 3 not in applied:
                conn.executescript(SCHEMA_V3_SQL)
                conn.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at)"
                    " VALUES (?, ?)", (3, int(time.time())))
            conn.execute("PRAGMA user_version = {}".format(SCHEMA_VERSION))
    elif current in (1, 2):
        with conn:
            if 2 not in applied:
                conn.executescript(SCHEMA_V2_SQL)
                conn.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at)"
                    " VALUES (?, ?)", (2, int(time.time())))
            if 3 not in applied:
                conn.executescript(SCHEMA_V3_SQL)
                conn.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at)"
                    " VALUES (?, ?)", (3, int(time.time())))
            conn.execute("PRAGMA user_version = {}".format(SCHEMA_VERSION))
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _table_exists(conn, name):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def create_run(conn, *, requested_root, root_path, tool_version, environment,
               exclusions, batch_size, scan_mode="metadata_only"):
    now = int(time.time())
    with conn:
        cur = conn.execute(
            "INSERT INTO scan_runs (tool_version, schema_version, requested_root,"
            " root_path, started_at_epoch, status, pid, classification_version,"
            " environment_json, exclusions_json, batch_size, scan_mode)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (tool_version, SCHEMA_VERSION, requested_root, root_path, now,
             STATUS_RUNNING, os.getpid(), CLASSIFICATION_VERSION,
             json.dumps(environment, ensure_ascii=False, sort_keys=True),
             json.dumps(exclusions, ensure_ascii=False), int(batch_size), scan_mode))
        return int(cur.lastrowid)


# Columns the transition helper may write (defense in depth: names are
# interpolated into SQL, so they must come from this closed whitelist).
_TRANSITION_COLUMNS = frozenset({
    "finished_at_epoch", "duration_seconds", "pid", "volume_total_bytes",
    "volume_used_bytes", "volume_free_bytes", "volume_status",
    "files_seen", "files_recorded", "directories_seen",
    "directories_recorded", "symlinks_seen", "other_entries_seen",
    "errors_count", "skipped_count", "excluded_count",
    "coverage_incomplete", "coverage_notes", "environment_json",
    "exclusions_json", "report_state", "report_built_at_epoch", "report_dir",
})


def transition_run(conn, run_id, new_status, **fields):
    """Validate and apply a status transition. Terminal runs reject changes."""
    row = conn.execute("SELECT status FROM scan_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise DatabaseError("Scan run {} does not exist".format(run_id))
    current = row["status"]
    if new_status != current:
        if new_status not in _ALLOWED_TRANSITIONS.get(current, set()):
            raise InvalidStateTransition(
                "Illegal transition for run {}: {} -> {}".format(
                    run_id, current, new_status))
    if current in TERMINAL_STATUSES and new_status != current:
        raise InvalidStateTransition(
            "Terminal run {} cannot move from {} to {}".format(
                run_id, current, new_status))

    unknown = set(fields) - _TRANSITION_COLUMNS
    if unknown:
        raise DatabaseError("Unknown scan_runs column(s): {}".format(
            ", ".join(sorted(unknown))))

    assignments = ["status = ?"]
    values = [new_status]
    for key, value in fields.items():
        assignments.append("{} = ?".format(key))
        values.append(value)
    values.append(run_id)
    with conn:
        conn.execute(
            "UPDATE scan_runs SET {} WHERE id = ?".format(", ".join(assignments)),
            values)


def set_report_state(conn, run_id, state, report_dir=None):
    """Report bookkeeping on a terminal run (does not touch inventory)."""
    row = conn.execute("SELECT id FROM scan_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise DatabaseError("Scan run {} does not exist".format(run_id))
    with conn:
        conn.execute(
            "UPDATE scan_runs SET report_state = ?, report_built_at_epoch = ?,"
            " report_dir = COALESCE(?, report_dir) WHERE id = ?",
            (state, int(time.time()), report_dir, run_id))


def record_report_build(conn, run_id, *, started_at, finished_at, status,
                        output_dir, file_count, notes=None):
    with conn:
        conn.execute(
            "INSERT INTO report_builds(scan_id, started_at_epoch, finished_at_epoch,"
            " status, output_dir, file_count, notes) VALUES (?,?,?,?,?,?,?)",
            (run_id, int(started_at), int(finished_at), status, output_dir,
             file_count, notes))


def insert_entries(conn, rows):
    if not rows:
        return 0
    with conn:
        conn.executemany(_INSERT_ENTRY_SQL,
                         [[row.get(col) for col in _ENTRY_COLUMNS] for row in rows])
    return len(rows)


def insert_issue(conn, scan_id, *, path, operation, error_category, error_code,
                 error_message):
    with conn:
        conn.execute(
            "INSERT INTO scan_issues(scan_id, path, operation, error_category,"
            " error_code, error_message, occurred_at_epoch) VALUES (?,?,?,?,?,?,?)",
            (scan_id, path, operation, error_category, error_code,
             error_message, int(time.time())))


def update_counters(conn, run_id, counters):
    """Atomically set cumulative counter fields (absolute values, not deltas)."""
    allowed = {
        "files_seen", "files_recorded", "directories_seen", "directories_recorded",
        "symlinks_seen", "other_entries_seen", "errors_count", "skipped_count",
        "excluded_count",
    }
    assignments, values = [], []
    for key, value in counters.items():
        if key not in allowed:
            raise DatabaseError("Unknown counter: {}".format(key))
        assignments.append("{} = ?".format(key))
        values.append(int(value))
    if not assignments:
        return
    values.append(run_id)
    with conn:
        conn.execute(
            "UPDATE scan_runs SET {} WHERE id = ?".format(", ".join(assignments)),
            values)


def get_run(conn, run_id):
    return conn.execute("SELECT * FROM scan_runs WHERE id = ?", (run_id,)).fetchone()


def latest_run(conn, statuses=None):
    if statuses:
        placeholders = ", ".join("?" for _ in statuses)
        return conn.execute(
            "SELECT * FROM scan_runs WHERE status IN ({})"
            " ORDER BY id DESC LIMIT 1".format(placeholders),
            tuple(statuses)).fetchone()
    return conn.execute(
        "SELECT * FROM scan_runs ORDER BY id DESC LIMIT 1").fetchone()


def list_runs(conn, limit=50):
    return conn.execute(
        "SELECT * FROM scan_runs ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()


def integrity_check(conn):
    rows = conn.execute("PRAGMA integrity_check").fetchall()
    results = [row[0] for row in rows]
    return results == ["ok"], results


def mark_interrupted_runs(conn):
    """Stale 'running' detection at launch. Returns list of run ids handled.

    A run is marked interrupted_or_recovered only when its stored PID is
    confirmed dead on this machine. If the PID may be alive (or liveness
    cannot be determined), the run is left untouched and a warning list is
    returned so the caller can surface the uncertainty.
    """
    marked, uncertain = [], []
    for row in conn.execute(
            "SELECT id, pid FROM scan_runs WHERE status = ?", (STATUS_RUNNING,)).fetchall():
        pid = row["pid"]
        if pid is None:
            uncertain.append((row["id"], "no pid recorded"))
            continue
        alive = _pid_alive(pid)
        if alive is False:
            try:
                transition_run(
                    conn, row["id"], STATUS_INTERRUPTED,
                    finished_at_epoch=int(time.time()),
                    coverage_incomplete=1,
                    coverage_notes=("Process terminated unexpectedly; run "
                                    "auto-marked interrupted_or_recovered on next "
                                    "launch. Data collected before termination is "
                                    "retained but MUST be treated as incomplete."))
            except InvalidStateTransition:
                pass
            marked.append(row["id"])
        elif alive is True:
            uncertain.append((row["id"], "pid {} appears alive".format(pid)))
        else:
            uncertain.append((row["id"], "process liveness undeterminable"))
    return marked, uncertain


def _pid_alive(pid):
    if pid <= 0:
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


def entries_cursor(conn, scan_id):
    return conn.execute(
        "SELECT * FROM entries WHERE scan_id = ? ORDER BY relative_path", (scan_id,))


def count_entries(conn, scan_id, kind=None):
    if kind:
        return conn.execute(
            "SELECT COUNT(*) FROM entries WHERE scan_id = ? AND kind = ?",
            (scan_id, kind)).fetchone()[0]
    return conn.execute(
        "SELECT COUNT(*) FROM entries WHERE scan_id = ?", (scan_id,)).fetchone()[0]
