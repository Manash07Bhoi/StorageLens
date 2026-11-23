"""Central configuration: paths, defaults, constants.

Everything the tool needs that is a value rather than behavior lives here,
so CLI help, docs and tests can be audited against a single source.
"""

import os

APP_DIR_NAME = "android-storage-audit"
DB_FILENAME = "storage_audit.sqlite3"

# Scan artifacts and reports live outside the scanned root by default.
DEFAULT_STATE_DIR = os.path.join(".local", "share", APP_DIR_NAME)

DEFAULT_BATCH_SIZE = 500
MIN_BATCH_SIZE = 50
MAX_BATCH_SIZE = 5000

DEFAULT_PAGE_ROWS = 500            # static rows per paginated HTML page
SEARCH_INLINE_LIMIT = 30000        # entries embedded inline in search.html
SEARCH_CHUNK_SIZE = 4000           # entries per data/inventory_NNN.js chunk
DIRECTORY_EXPLORE_LIMIT = 30000    # directories rendered in explorer tree

TREE_CHUNK_MAX_BYTES = 8 * 1024 * 1024   # split directory_tree.txt above this
TREE_CHUNK_MAX_LINES = 250_000

MAX_SYMLINK_TARGET_LEN = 4096            # stored readlink text is bounded
MAX_ERROR_MESSAGE_LEN = 1000             # stored error messages are bounded
MAX_PROGRESS_PATH_LEN = 96               # terminal progress line budget

REPORT_SUBDIR = "reports"
LOG_SUBDIR = "logs"
