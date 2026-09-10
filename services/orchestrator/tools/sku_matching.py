"""Tool: check whether a term maps to a real SKU.

Wraps the NEW `POST /feedback/match-skus` endpoint (deterministic matcher
layers 1-3 only, no LLM adjudication, no persistence -- see
`services/feedback/app/main.py`). Zero LLM cost. Useful ad hoc when the agent
is reasoning about an unmet need with `gap: true` (from `feedback_extraction`)
and wants to double-check no SKU already covers it before flagging it for a
human, or when a need's `mentioned_skus` came back empty.

`fuzzy` matches carry a real, documented false-positive rate (the matcher's
own layer-3 heuristic is imperfect by design -- see `app/matcher.py`). Treat
a `fuzzy` result as a lead to corroborate, not a fact to act on directly.
"""
from __future__ import annotations

import logging

import httpx
from langchain_core.tools import tool
from pantry_common.security import service_headers

from ..config import settings

log = logging.getLogger(__name__)


@tool
def sku_matching(terms: list[str], context: str | None = None) -> str:
    """Check whether one or more terms map to a real, stocked SKU.

    Returns each term's best match (if any), a confidence score, and the
    method used (`exact_code` / `alias` / `fuzzy` / `qualifier_blocked` /
    `known_gap` / `none`). A `fuzzy` match is a lead, not a fact -- corroborate
    it (e.g. against current inventory) before acting on it; prefer
    `flag_for_human` over guessing when confidence is low or the method is
    `none`/`known_gap`.
    """
    if not terms:
        return "no terms given"
    url = f"{settings.feedback_url.rstrip('/')}/feedback/match-skus"
    try:
        with httpx.Client(timeout=settings.http_timeout) as c:
            r = c.post(url, json={"terms": terms, "context": context},
                      headers=service_headers())
            r.raise_for_status()
            return str(r.json()["matches"])
    except httpx.HTTPError as exc:
        log.info("sku_matching: unavailable: %s", exc)
        return f"SKU matching unavailable: {exc}"
