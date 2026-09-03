#!/usr/bin/env python3
"""Repository-level entry point for the Inventory Service seed command."""

from __future__ import annotations

import sys
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "inventory"
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.seed import main  # noqa: E402  (path bootstrap must run first)


if __name__ == "__main__":
    raise SystemExit(main())
