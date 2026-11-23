#!/usr/bin/env bash
# Android Storage Audit — Termux launcher.
# Usage: ./run_audit.sh [arguments passed to storage_audit.py]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "ERROR: Python 3 is not installed." >&2
    echo "In Termux run:  pkg install python" >&2
    exit 2
fi

if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 8) else 1)'; then
    echo "ERROR: Python 3.8 or newer is required." >&2
    "$PY" --version >&2
    exit 2
fi

exec "$PY" "$HERE/storage_audit.py" "$@"
