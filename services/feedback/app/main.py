"""Feedback service. Owns POST /feedback, GET /feedback, and /metrics.

GET /feedback/unmet-needs is the aggregation the orchestrator's SENSE phase
consumes; the logic lives in app/unmet_needs.py.

POST /feedback writes the raw row and returns immediately (202); extraction
runs in a Starlette BackgroundTask. An elderly beneficiary must never wait on
an LLM call, and an API outage must never lose their words -- the raw text,
lang, and channel are committed before the background task is even scheduled.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from psycopg2.extras import Json
from pydantic import BaseModel

from app import db
from app.config import settings
from app.extract import resolve_skus, run_extraction, run_sentiment_classifier
from app.unmet_needs import aggregate as aggregate_unmet_needs

logger = logging.getLogger("feedback.main")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Pantry Feedback Service")

# The intake screen (frontend/intake) is a static file served from a
# different origin/port than this API -- no cookies/auth involved, so a
# permissive dev CORS policy is fine here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class FeedbackIn(BaseModel):
    beneficiary_id: str
    text: str
    lang: Optional[str] = None
    channel: str = "web"


@app.on_event("startup")
def on_startup() -> None:
    db.init_pool()


@app.post("/feedback", status_code=202)
def post_feedback(payload: FeedbackIn, background_tasks: BackgroundTasks):
    with db.get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO feedback.feedback_entries (beneficiary_id, text, lang, channel)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (payload.beneficiary_id, payload.text, payload.lang, payload.channel),
        )
        feedback_id = cur.fetchone()["id"]

    logger.info("feedback %s received, raw text logged, extraction queued", feedback_id)
    background_tasks.add_task(extract_and_store, feedback_id, payload.text, payload.lang)
    return {"id": feedback_id, "status": "received"}


def extract_and_store(feedback_id: int, text: str, lang: Optional[str]) -> None:
    logger.info("feedback %s: raw text=%r lang=%r", feedback_id, text, lang)
    try:
        extraction, schema_valid_first_try = run_extraction(text, lang)
        classifier = run_sentiment_classifier(text, extraction.sentiment)
        sku_resolutions = resolve_skus(extraction.mentioned_terms, context=text)
        resolved_skus = sorted({r.matched_sku for r in sku_resolutions if r.matched_sku})

        logger.info(
            "feedback %s: parsed=%s classifier=%s resolved_skus=%s schema_valid_first_try=%s",
            feedback_id,
            extraction.model_dump(),
            classifier,
            resolved_skus,
            schema_valid_first_try,
        )

        with db.get_cursor() as cur:
            cur.execute(
                """
                UPDATE feedback.feedback_entries
                SET extraction_status = 'done',
                    -- now(), not a Python naive utcnow(): received_at is
                    -- TIMESTAMPTZ, so a naive UTC value made every latency
                    -- metric negative by the local UTC offset (-7.9h in SGT).
                    extracted_at = now(),
                    sentiment = %s,
                    urgency = %s,
                    categories = %s,
                    mentioned_skus = %s,
                    mentioned_terms = %s,
                    unmet_needs = %s,
                    detected_lang = %s,
                    summary_en = %s,
                    classifier_label = %s,
                    classifier_score = %s,
                    classifier_agrees = %s,
                    schema_valid_first_try = %s
                WHERE id = %s
                """,
                (
                    extraction.sentiment,
                    extraction.urgency,
                    extraction.categories,
                    resolved_skus,
                    extraction.mentioned_terms,
                    Json([u.model_dump() for u in extraction.unmet_needs]),
                    extraction.detected_lang,
                    extraction.summary_en,
                    classifier.label,
                    classifier.score,
                    classifier.agrees,
                    schema_valid_first_try,
                    feedback_id,
                ),
            )
            for r in sku_resolutions:
                cur.execute(
                    """
                    INSERT INTO feedback.sku_matches
                        (feedback_id, term, matched_sku, confidence, method, near_sku, unmet_qualifier)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        feedback_id,
                        r.term,
                        r.matched_sku,
                        r.confidence,
                        r.method,
                        r.near_sku,
                        r.unmet_qualifier,
                    ),
                )
    except Exception as e:  # noqa: BLE001 -- never let a bad extraction lose the raw row
        logger.exception("feedback %s: extraction failed", feedback_id)
        with db.get_cursor() as cur:
            cur.execute(
                """
                UPDATE feedback.feedback_entries
                SET extraction_status = 'failed', extraction_error = %s
                WHERE id = %s
                """,
                (str(e), feedback_id),
            )


@app.get("/feedback")
def get_feedback(
    since: Optional[datetime] = None,
    urgency: Optional[int] = None,
    category: Optional[str] = None,
):
    clauses = []
    params: list = []
    if since is not None:
        clauses.append("received_at >= %s")
        params.append(since)
    if urgency is not None:
        clauses.append("urgency = %s")
        params.append(urgency)
    if category is not None:
        clauses.append("%s = ANY(categories)")
        params.append(category)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with db.get_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, beneficiary_id, text, lang, channel, received_at,
                   extraction_status, sentiment, urgency, categories,
                   mentioned_skus, mentioned_terms, unmet_needs, detected_lang,
                   summary_en, classifier_label, classifier_agrees,
                   schema_valid_first_try
            FROM feedback.feedback_entries
            {where}
            ORDER BY received_at DESC
            """,
            params,
        )
        return cur.fetchall()


@app.get("/feedback/unmet-needs")
def get_unmet_needs(since: Optional[datetime] = None, min_confidence: float = 0.0):
    """Ranked unmet needs for the agent. `gap: true` = no stocked SKU covers it."""
    return aggregate_unmet_needs(since=since, min_confidence=min_confidence)


@app.get("/health")
def health():
    """Liveness + which catalogue source the matcher resolved against."""
    from app.catalogue import source
    from app.skus import SKU_BY_CODE
    try:
        with db.get_cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM feedback.feedback_entries")
            n = cur.fetchone()["n"]
        return {"status": "ok", "database": "ok", "entries": n,
                "catalogue_source": source(), "catalogue_skus": len(SKU_BY_CODE),
                "fake_llm": settings.fake_llm, "model": settings.model_extract}
    except Exception as exc:  # noqa: BLE001
        return {"status": "degraded", "detail": str(exc)}


@app.get("/metrics")
def get_metrics():
    with db.get_cursor() as cur:
        cur.execute(
            """
            SELECT
                count(*) FILTER (WHERE extraction_status = 'done') AS done_count,
                count(*) FILTER (WHERE extraction_status = 'failed') AS failed_count,
                count(*) FILTER (WHERE extraction_status = 'pending') AS pending_count,
                avg(schema_valid_first_try::int) FILTER (WHERE extraction_status = 'done')
                    AS schema_pass_rate,
                avg(classifier_agrees::int) FILTER (WHERE classifier_agrees IS NOT NULL)
                    AS classifier_agreement_rate,
                avg(extract(epoch FROM (extracted_at - received_at)))
                    FILTER (WHERE extraction_status = 'done') AS avg_latency_seconds
            FROM feedback.feedback_entries
            """
        )
        row = cur.fetchone()

        cur.execute(
            """
            SELECT
                count(*) AS total_terms,
                count(*) FILTER (WHERE matched_sku IS NOT NULL) AS resolved_terms
            FROM feedback.sku_matches
            """
        )
        sku_row = cur.fetchone()

    total_terms = sku_row["total_terms"] or 0
    resolved_terms = sku_row["resolved_terms"] or 0
    sku_resolution_rate = (resolved_terms / total_terms) if total_terms else None

    return {
        "schema_pass_rate": row["schema_pass_rate"],
        "sku_resolution_rate": sku_resolution_rate,
        "classifier_agreement_rate": row["classifier_agreement_rate"],
        "avg_latency_seconds": row["avg_latency_seconds"],
        "extraction_done": row["done_count"],
        "extraction_failed": row["failed_count"],
        "extraction_pending": row["pending_count"],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.feedback_service_port, reload=True)
