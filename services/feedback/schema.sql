-- Feedback service schema. Lives in its own `feedback` schema on W's shared
-- Postgres instance -- never touches tables outside it.

CREATE SCHEMA IF NOT EXISTS feedback;

CREATE TABLE IF NOT EXISTS feedback.feedback_entries (
    id                      BIGSERIAL PRIMARY KEY,
    beneficiary_id          TEXT NOT NULL,
    text                    TEXT NOT NULL,
    lang                    TEXT,                    -- as submitted by the intake screen, e.g. 'en'|'zh'|'ms'|'ta'
    channel                 TEXT NOT NULL DEFAULT 'web',
    received_at             TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- extraction lifecycle: POST returns immediately with 'pending'; a
    -- background task fills the rest in. An API outage must never lose the
    -- raw text/lang/channel columns above -- only these can end up null/failed.
    extraction_status       TEXT NOT NULL DEFAULT 'pending'
                             CHECK (extraction_status IN ('pending', 'done', 'failed')),
    extraction_error        TEXT,
    extracted_at            TIMESTAMPTZ,

    -- extraction contract fields (frozen -- field names are load-bearing, M's
    -- queries depend on them)
    sentiment                TEXT CHECK (sentiment IN ('negative', 'neutral', 'positive')),
    urgency                  SMALLINT CHECK (urgency BETWEEN 1 AND 5),
    categories                TEXT[],
    mentioned_skus            TEXT[],   -- matcher-resolved, authoritative join key
    mentioned_terms            TEXT[],  -- literal surface forms, model's job
    unmet_needs               JSONB,    -- [{need, confidence, suggested_category}, ...]
    detected_lang              TEXT,
    summary_en                  TEXT,

    -- second-opinion / judging metrics -- never ground truth, see app/extract.py
    classifier_label            TEXT,     -- raw HF SST-2 label, e.g. 'POSITIVE'/'NEGATIVE'
    classifier_score            REAL,
    classifier_agrees           BOOLEAN,  -- null when not comparable (e.g. LLM said 'neutral')
    schema_valid_first_try       BOOLEAN  -- judging metric: did the first LLM call pass validation?
);

CREATE INDEX IF NOT EXISTS idx_feedback_entries_received_at ON feedback.feedback_entries (received_at);
CREATE INDEX IF NOT EXISTS idx_feedback_entries_urgency ON feedback.feedback_entries (urgency);
CREATE INDEX IF NOT EXISTS idx_feedback_entries_categories ON feedback.feedback_entries USING GIN (categories);
CREATE INDEX IF NOT EXISTS idx_feedback_entries_status ON feedback.feedback_entries (extraction_status);

-- One row per term the matcher was asked to resolve. This is what
-- /metrics reads for SKU resolution rate, and what a future "no matching
-- SKU" gap view (M's /feedback/unmet-needs) can join against for the
-- near-miss detail the bare mentioned_skus array can't carry.
CREATE TABLE IF NOT EXISTS feedback.sku_matches (
    id                  BIGSERIAL PRIMARY KEY,
    feedback_id         BIGINT NOT NULL REFERENCES feedback.feedback_entries(id) ON DELETE CASCADE,
    term                TEXT NOT NULL,
    matched_sku         TEXT,
    confidence          REAL NOT NULL,
    method              TEXT NOT NULL,   -- exact_code | alias | fuzzy | llm | qualifier_blocked | none
    near_sku            TEXT,
    unmet_qualifier     TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sku_matches_feedback_id ON feedback.sku_matches (feedback_id);
