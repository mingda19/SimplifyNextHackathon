# Feedback Service — Progress Summary

Branch: `ws2/feedback-service` · Status: working end-to-end, smoke-testable at $0 via `FAKE_LLM=1`

## What it does

A beneficiary intake pipeline: raw feedback text goes in, and structured,
queryable signal (sentiment, urgency, categories, resolved SKUs, unmet needs)
comes out — without ever risking the raw submission.

```
frontend/intake  →  POST /feedback (202, writes raw row immediately)
                        ↓ BackgroundTask
                     run_extraction (Claude, structured output)
                        ↓
                     resolve_skus (5-layer matcher)
                        ↓
                     run_sentiment_classifier (HF, non-authoritative)
                        ↓
                     UPDATE feedback_entries + INSERT sku_matches
```

`GET /feedback` (filterable by `since`/`urgency`/`category`) and `GET /metrics`
(schema pass rate, SKU resolution rate, classifier agreement rate, avg
extraction latency) read the results back out.

## Key design decisions

- **Raw text is never at risk.** `POST /feedback` inserts `beneficiary_id`,
  `text`, `lang`, `channel` synchronously and returns `202` before any LLM
  call happens. Extraction runs in a Starlette `BackgroundTask`; if it throws,
  the row is marked `extraction_status = 'failed'` with the error captured —
  the beneficiary's words are never lost and never blocked on an API outage.
- **SKU matcher is 5 layers**, in order: exact code → alias table → fuzzy →
  optional LLM adjudication (off by default, `MATCHER_LLM_ADJUDICATION`) →
  none. A qualifier guard (dietary/texture mismatch, e.g. "halal" vs a
  non-halal SKU) reports a near-miss (`near_sku`, `unmet_qualifier`) instead
  of a false match — every term resolution is logged to `sku_matches` for
  audit and for the resolution-rate metric.
- **HF sentiment classifier is a disagreement flag, not ground truth.** The
  LLM's `sentiment` field is authoritative; `classifier_agrees` just flags
  where they diverge, for judging the extraction quality over time.
- **Schema is frozen on purpose.** `mentioned_skus`, `mentioned_terms`,
  `sentiment`, `urgency`, `categories`, `unmet_needs` field names are
  load-bearing — another workstream's aggregation queries depend on them.
  `GET /feedback/unmet-needs` is deliberately left unimplemented (reserved
  for that other workstream) so a future merge won't clobber it.
- **Own Postgres schema** (`feedback.*`), never touches tables outside it.

## Integration with the rest of the repo

- Switched from a direct Anthropic API key to `AnthropicBedrockMantle` via
  shared AWS SSO, mirroring `services/orchestrator/llm.py`'s client
  construction so the whole team resolves one SSO profile
  (`aws/config`, `AWS_PROFILE`).
- Moved off a per-service `.env` onto the repo's single global `.env`
  convention (`.env.example` updated accordingly).
- Fixed the service port from 8001 → 8002 to match what
  `services/orchestrator/config.py` already expects it to be.
- `db.py` normalizes `DATABASE_URL` for psycopg2 compatibility (the shared
  URL uses SQLAlchemy's `+psycopg` dialect suffix, which raw psycopg2 can't
  parse).
- `FAKE_LLM=1` (repo-wide default) short-circuits extraction with a canned
  fixture that still exercises the matcher's real alias/qualifier-guard
  paths — lets anyone smoke-test the service before AWS SSO is set up.

## Files added

- `services/feedback/app/` — `main.py` (FastAPI app, routes), `extract.py`
  (LLM extraction + HF classifier), `matcher.py` (5-layer SKU matcher),
  `skus.py`, `db.py`, `config.py`
- `services/feedback/schema.sql` — `feedback.feedback_entries` +
  `feedback.sku_matches` tables
- `services/feedback/seed/` — 50-entry multilingual seed corpus + loader
- `services/feedback/tests/test_matcher.py` — matcher unit tests
- `frontend/intake/index.html` — beneficiary-facing intake screen

## Open / not done

- `GET /feedback/unmet-needs` (aggregation endpoint) — intentionally left for
  another workstream to add.
- Not yet merged into `main` (`main` currently only has the initial commit +
  README; this branch also carries the already-merged inventory/orchestrator/
  price-forecaster workstreams on top of it from a rebase).
- Real Bedrock path (`FAKE_LLM=0`) not yet verified against live AWS SSO in
  this session — only the fake-LLM smoke path has been exercised.
