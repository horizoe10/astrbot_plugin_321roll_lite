"""World engine access.  vendor/story_engine is the unmodified 321Roll engine package."""
from __future__ import annotations

import sys
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[2] / "vendor"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

from story_engine import default_rules

# Lite's host-context budget applies to both composition and engine validation.
# Keep the vendored distribution byte-for-byte intact for engine synchronization.
HOST_CONTEXT_LIMIT = 12000
default_rules.HOST_CONTEXT_LIMIT = HOST_CONTEXT_LIMIT
