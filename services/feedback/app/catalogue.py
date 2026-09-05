"""Live SKU catalogue, sourced from workstream 1's inventory service.

WHY THIS EXISTS
---------------
`app/skus.py` used to hard-code a 20-SKU stub of W/G's `items` table. Its own
docstring said "GET /inventory from W's service is the real source of truth at
runtime; this module is what the matcher runs against until that integration
lands." That integration is this module.

The stub's codes and the real catalogue barely overlapped -- of 20 stub SKUs
only RICE-5KG and SUGAR-1KG exist in the seeded inventory. Everything else
(COOKING-OIL-1L vs OIL-2L, EGGS-DOZEN vs EGGS-TRAY30, CANNED-SARDINE vs
SARDINES-CANNED-155G, ...) resolved to codes that do not exist, so
`mentioned_skus` -- the join key the orchestrator's unmet-needs aggregation
depends on -- was pointing at nothing.

We read over HTTP rather than SQL on purpose: schema.sql states this service
"must never touch tables outside" the `feedback` schema, and `items` lives in
inventory's schema. HTTP respects that boundary.

DEGRADATION
-----------
Inventory being down must not stop feedback intake. On a successful fetch the
catalogue is cached to disk; on failure we fall back to the last good cache,
and only if there is none do we raise.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import urllib.error
import urllib.request

logger = logging.getLogger("feedback.catalogue")

INVENTORY_URL = os.getenv("INVENTORY_URL", "http://localhost:8000")
CACHE_PATH = Path(__file__).resolve().parent.parent / ".catalogue_cache.json"
CACHE_TTL_SECONDS = int(os.getenv("CATALOGUE_TTL", "300"))
HTTP_TIMEOUT = float(os.getenv("CATALOGUE_TIMEOUT", "5"))


@dataclass(frozen=True)
class SKUItem:
    sku: str
    name: str
    category: str
    qualifiers: frozenset = field(default_factory=frozenset)


def _fetch_live() -> list[dict]:
    url = f"{INVENTORY_URL.rstrip('/')}/inventory"
    with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as r:
        payload = json.loads(r.read().decode("utf-8"))
    return payload if isinstance(payload, list) else payload.get("items", [])


def _read_cache() -> Optional[list[dict]]:
    if not CACHE_PATH.exists():
        return None
    try:
        blob = json.loads(CACHE_PATH.read_text())
        return blob.get("items")
    except (OSError, json.JSONDecodeError):
        return None


def _write_cache(items: list[dict]) -> None:
    try:
        CACHE_PATH.write_text(json.dumps({"fetched_at": time.time(), "items": items},
                                         indent=2))
    except OSError:
        pass


_memo: dict = {}


def load_items(force: bool = False) -> list[dict]:
    """Live items, memoised for CATALOGUE_TTL seconds, cache-backed on failure."""
    now = time.time()
    if not force and _memo.get("items") and now - _memo.get("at", 0) < CACHE_TTL_SECONDS:
        return _memo["items"]

    try:
        items = _fetch_live()
        _write_cache(items)
        _memo.update(items=items, at=now, source="live")
        logger.info("catalogue: %d items from %s", len(items), INVENTORY_URL)
        return items
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        cached = _read_cache()
        if cached:
            _memo.update(items=cached, at=now, source="cache")
            logger.warning("catalogue: inventory unreachable (%s), using disk cache "
                           "(%d items)", exc, len(cached))
            return cached
        raise RuntimeError(
            f"inventory service unreachable at {INVENTORY_URL} and no cached "
            f"catalogue on disk — start the inventory service once to seed the cache"
        ) from exc


def source() -> str:
    return _memo.get("source", "none")
