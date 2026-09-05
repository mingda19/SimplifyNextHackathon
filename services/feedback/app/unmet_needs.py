"""GET /feedback/unmet-needs -- the aggregation the orchestrator consumes.

This is the endpoint `services/orchestrator/services.py::get_unmet_needs`
calls during the agent's SENSE phase. Contract matches
`orchestrator/fixtures.UNMET_NEEDS` exactly so the graph needs no changes.

RANKING
-------
score = frequency x max_urgency, per the README ("rank unmet needs by
frequency x urgency"). Frequency is how many distinct beneficiaries raised a
semantically-equivalent need, not how many rows mention it -- one person
submitting five times is one voice, not five.

SKU ATTRIBUTION
---------------
A need's SKUs are resolved from the NEED TEXT itself, not inherited from the
row. A row saying "we need cooking oil and the sugar ran out" produces two
needs; inheriting the row's SKU union would attribute SUGAR-1KG to the
cooking-oil need and make the agent order the wrong thing. The matcher is
re-run per need, with the original message passed as qualifier context.

THE GAP FLAG
------------
`gap: true` means the need resolved to NO stocked SKU. That is the
highest-signal output of the whole feedback loop: something beneficiaries
are asking for that nobody has stocked. The orchestrator turns those into
`flag_for_human` plan steps rather than purchase orders, because an agent
cannot order a SKU that does not exist.

Needs are grouped by a normalised key rather than exact string match, since
the extractor phrases the same need differently across languages and rows.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Optional

from app import db
from app.matcher import match_term

_STOP = {"the", "a", "an", "for", "of", "to", "and", "my", "our", "some",
         "more", "need", "needs", "needed", "want", "wants", "please",
         "cannot", "can", "not", "is", "are", "no", "any"}


def _norm_key(need: str) -> str:
    """Collapse phrasing variants so the same need groups across rows/languages."""
    words = re.findall(r"[a-z0-9]+", (need or "").lower())
    kept = [w for w in words if w not in _STOP]
    return " ".join(sorted(set(kept))) or (need or "").strip().lower()


def aggregate(since: Optional[datetime] = None,
              min_confidence: float = 0.0) -> dict[str, Any]:
    where = ["extraction_status = 'done'", "unmet_needs IS NOT NULL"]
    params: list = []
    if since is not None:
        where.append("received_at >= %s")
        params.append(since)

    with db.get_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, beneficiary_id, urgency, categories, mentioned_skus,
                   unmet_needs, detected_lang, summary_en, received_at,
                   text AS text_ctx
            FROM feedback.feedback_entries
            WHERE {' AND '.join(where)}
            """,
            params,
        )
        rows = cur.fetchall()

        # Near-miss detail the bare mentioned_skus array cannot carry: a term
        # the matcher refused because a dietary/texture qualifier was unmet.
        cur.execute(
            """
            SELECT feedback_id, term, near_sku, unmet_qualifier
            FROM feedback.sku_matches
            WHERE matched_sku IS NULL AND near_sku IS NOT NULL
            """
        )
        near = defaultdict(list)
        for r in cur.fetchall():
            near[r["feedback_id"]].append(
                {"term": r["term"], "near_sku": r["near_sku"],
                 "unmet_qualifier": r["unmet_qualifier"]})

    _need_sku_cache: dict[tuple[str, str], list[str]] = {}

    def _skus_for_need(need_text: str, ctx: str) -> list[str]:
        key = (need_text, ctx)
        if key not in _need_sku_cache:
            r = match_term(need_text, context=ctx)
            _need_sku_cache[key] = [r.matched_sku] if r.matched_sku else []
        return _need_sku_cache[key]

    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        for need in (row["unmet_needs"] or []):
            if float(need.get("confidence", 0)) < min_confidence:
                continue
            key = _norm_key(need.get("need", ""))
            if not key:
                continue
            g = groups.setdefault(key, {
                "need": need.get("need", ""),
                "beneficiaries": set(),
                "urgency": 0,
                "categories": set(),
                "mentioned_skus": set(),
                "near_misses": [],
                "confidences": [],
                "examples": [],
            })
            g["beneficiaries"].add(row["beneficiary_id"])
            g["urgency"] = max(g["urgency"], int(row["urgency"] or 0))
            if need.get("suggested_category"):
                g["categories"].add(need["suggested_category"])
            # Resolve THIS need's own SKUs — see SKU ATTRIBUTION above.
            need_skus = _skus_for_need(need.get("need", ""), row["text_ctx"])
            g["mentioned_skus"].update(need_skus)
            g["confidences"].append(float(need.get("confidence", 0)))
            for nm in near.get(row["id"], []):
                if nm not in g["near_misses"]:
                    g["near_misses"].append(nm)
            if len(g["examples"]) < 3 and row["summary_en"]:
                g["examples"].append(row["summary_en"])

    ranked = []
    for g in groups.values():
        freq = len(g["beneficiaries"])
        urgency = g["urgency"]
        skus = sorted(g["mentioned_skus"])
        ranked.append({
            "need": g["need"],
            "frequency": freq,
            "urgency": urgency,
            "score": freq * urgency,
            "mentioned_skus": skus,
            "suggested_category": sorted(g["categories"])[0] if g["categories"] else None,
            # No stocked SKU covers this need -> a human has to decide.
            "gap": not skus,
            "avg_confidence": round(sum(g["confidences"]) / len(g["confidences"]), 3)
                              if g["confidences"] else None,
            "near_misses": g["near_misses"],
            "examples": g["examples"],
        })

    ranked.sort(key=lambda r: (-r["score"], -r["urgency"], r["need"]))
    return {
        "as_of": date.today().isoformat(),
        "ranked": ranked,
        "totals": {
            "needs": len(ranked),
            "gaps": sum(1 for r in ranked if r["gap"]),
            "entries_considered": len(rows),
        },
    }
