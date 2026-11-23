#!/usr/bin/env python3
"""Android Storage Audit — entry point.

Importing this module does nothing. The scan runs only via the CLI.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from storage_audit.cli import main

if __name__ == "__main__":
    sys.exit(main())
