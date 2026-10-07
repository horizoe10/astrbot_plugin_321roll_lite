"""World engine access.  vendor/story_engine is the unmodified 321Roll engine package."""
from __future__ import annotations

import sys
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[2] / "vendor"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))
