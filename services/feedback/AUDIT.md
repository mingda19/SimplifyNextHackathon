# Phase 0 Audit — Feedback Service

Read-only audit. No source files were modified while producing this report.

## Summary

| Check | Verdict | One-line issue |
|---|---|---|
| A1 | ~~WEAK~~ **FIXED** (`ab1cfb0`, `b9dc4e8`) | Was 25 cases / 7 None (28%). Now 40 cases / 19 None (47.5%) — resolved as a side effect of the B1/B2 regression cases, no separate fix needed |
| A2 | PASS | 4 qualifier hard-negatives present (gluten-free, halal, low-sodium, pureed) + 1 Singlish texture case |
| A3 | ~~WEAK~~ **FIXED** (`58d25ba`) | Was 1 Tamil case (romanized only). Now 4 Tamil cases, 3 in native script, exercising the alias-matching bug fix |
| A4 | PASS | No test asserts only "didn't crash" — every case checks exact `matched_sku`/`near_sku`/`unmet_qualifier` |
| B1 | ~~WEAK~~ **FIXED** (`ab1cfb0`) | Experiment run (see detail below): threshold value itself wasn't the real problem — no single ratio cutoff separates real typos from unrelated same-length words. Fixed with a first-character gate instead; threshold left at 0.72 |
| B2 | ~~FAIL~~ **FIXED** (`b9dc4e8`) | Was a fixed English-only phrase list; all 5 probe phrases slipped through. Added `MSG_FREE` qualifier tag + paraphrase/Mandarin/Malay patterns; regression cases now pass |
| B3 | PASS | Every resolution records `method` and is persisted to `sku_matches.method` |
| C1 | — | See table below: 20 SKUs, 18 zh aliases, 14 ms aliases, now **12** ta aliases (was 1) |
| C2 | ~~FAIL~~ **FIXED** (`58d25ba`) | Was 19/20 SKUs with zero Tamil aliases, plus a silent `\b`-regex bug that would have broken any Tamil-script alias added anyway. Both fixed; fuzzy/typo tolerance for Tamil remains unsupported (disclosed, not fixed) |
| D1 | PASS | Retry sends the validation error back into the conversation (`previous_error` param, `_extract_once`) |
| D2 | PASS | Urgency rubric is concretely anchored per level 1-5, not "rate 1-5" |
| D3 | PASS | `FAKE_EXTRACTION.mentioned_terms = ["rice", "gluten free bread"]` — natural language, exercises the real matcher including the qualifier guard |
| D4 | PASS | `schema_valid_first_try` is set from the first `_extract_once` call only, before any retry |
| E1 | PASS | Raw row INSERT + commit happens inside `with db.get_cursor()`, which exits (and commits) before `background_tasks.add_task(...)` is called |
| E2 | PASS (broad-but-intentional) | Broad `except Exception` in `extract_and_store`, but it logs full traceback (`logger.exception`) and always sets `extraction_status='failed'` — never leaves a row stuck in `pending` |
| E3 | PASS | `since`/`urgency`/`category` filters are bound `%s` params; the f-string only assembles static clause *fragments* (column names), never a value |
| F1 | PASS | `db.get_cursor()` calls `get_conn()` which does `_pool.getconn()` fresh every call and `_pool.putconn(conn)` in `finally` — no module-level connection reuse across requests/background tasks |
| G1 | PASS | `idx_feedback_entries_received_at` index exists |
| G2 | PASS | `text TEXT NOT NULL` |
| G3 | PASS | `extraction_status TEXT NOT NULL CHECK (... IN ('pending','done','failed'))` |
| H1 | PASS | On fetch failure, `.catch()` doesn't navigate away from `screen-review`; `state.text` and the textarea both still hold the typed text, submit re-enabled for retry |
| H2 | PASS | `statusEl.textContent = t("submitting")` + `submitBtn.disabled = true` while the POST is in flight |
| H3 | PASS | No `SpeechRecognitionCtor` → mic button disabled, hint text swapped, typing still works |

## Overall verdict: **AMBER** as of Phase 0 (this audit). Superseded by Phase 1 fixes below.

No RED trigger fired (no module-level DB connection reuse, no f-string SQL injection, `FAKE_LLM` fixture does exercise the real matcher). But it landed squarely on the AMBER definition: **the qualifier guard was a short fixed list (B2 FAIL) and the alias table was heavily English/Mandarin/Malay-weighted with Tamil essentially unsupported (C2 FAIL)**.

### Phase 1 update

B1, B2, A1, A3, and C2 are now fixed (commits `ab1cfb0`, `b9dc4e8`, `58d25ba` — see per-check notes above and each commit message for the red-then-green evidence). Two issues were found *while* fixing these and are logged here rather than fixed, per the Evidence Rule (real evidence, but out of scope for the fix that surfaced them):

- **Alias longest-match tiebreak picks dict order, not context.** When a sentence contains two different items' aliases at equal length (e.g. Mandarin "糖" for sugar and another 1-char alias, or Malay "gula" tying with a same-length alias), `_match_alias`'s "prefer longest" rule breaks ties by whichever appears first in `ALIASES`' definition order, not by which one is the actual subject of the sentence. Found while designing B2's Mandarin/Malay test cases (a naive test picked the wrong item); worked around by choosing test items whose alias is unambiguously longer, not by fixing the underlying tiebreak. Needs its own audit/fix cycle — it's an architecture question (how to disambiguate multi-item utterances), not a one-line change.
- **Fuzzy layer (layer 3) still doesn't work for Tamil script.** `_match_fuzzy` tokenizes with `re.findall(r"[a-z]+", ...)`, which never matches Tamil Unicode. C2's fix closes the alias (layer 2) gap but typo/voice-noise tolerance for Tamil remains unsupported. Would need script-aware edit distance; not attempted here.

---

## Detail

### tests/test_matcher.py

**A1.** Counted 25 `GOLDEN_CASES` tuples (not 27 — `services/feedback/PROGRESS.md` states "27/27 golden tests pass"; the file as it exists today has 25). Of those, cases with `expected_sku=None`:
```python
("gluten free bread -> refuse, not BREAD-LOAF", ..., None, "BREAD-LOAF", "gluten_free"),
("halal baby formula -> refuse, not MILK-POWDER", ..., None, "MILK-POWDER", "halal"),
("low sodium noodles -> refuse, not NOODLE-INST", ..., None, "NOODLE-INST", "low_sodium"),
("pureed vegetables -> refuse, not VEG-LEAFY", ..., None, "VEG-LEAFY", "soft_texture"),
("Singlish texture complaint -> refuse, not RICE-5KG", ..., None, "RICE-5KG", "soft_texture"),
("no matching SKU #1", "fresh durian please", None, None, None),
("no matching SKU #2", "can you get birthday cake", None, None, None),
```
7 of 25 = 28%. Verdict WEAK per the stated bar (under a third).

**A2.** Present: gluten-free bread, halal baby formula, low-sodium noodles, pureed vegetables, plus a fifth real-beneficiary-language case ("aiyo the rice damn hard leh, my mother no more teeth" → `soft_texture`). PASS — this is a real, non-trivial set.

**A3.** Per-language tally of the 25 cases: exact-code(1, n/a), English/Singlish(~14: plain English, longest-alias, typo, voice-noise, plural/typo, all 5 qualifier-refuse cases, all 3 qualifier-satisfied cases, both no-match cases), Mandarin(4: 白米/咖啡/尿布/粥), Malay(4: beras/gula/ayam/ikan), **Tamil(1: arisi)**. Not "two foreign entries bolted on" — Mandarin and Malay both get real coverage — but Tamil is a single case, and it's the easy layer-2 exact-alias case, not a fuzzy/typo/qualifier stress case. WEAK.

**A4.** None found — every case in the loop asserts exact equality on `matched_sku`, and conditionally on `near_sku`/`unmet_qualifier`. PASS.

### app/matcher.py

**B1.**
```python
FUZZY_ACCEPT_THRESHOLD = 0.72
LLM_ACCEPT_THRESHOLD = 0.60
```
No comment justifying `0.72` specifically (module docstring just restates it as "accept at >=0.72"). Not proven against a false-match rate. WEAK — this is exactly what Phase 1's B1 experiment (lower by 10 points, measure false matches) is for.

**B2.** The guard is `QUALIFIER_PATTERNS`, a fixed `dict[str, list[str]]` of literal substrings (quoted in full above, lines 49-70 of matcher.py). Checking the five probe phrases against it:
- `"no MSG"` — no `NO_MSG` qualifier tag exists in `ALL_QUALIFIERS` at all → **slips through**, unconditionally, for any SKU.
- `"soft texture"` — `SOFT_TEXTURE` patterns are `"pureed"`, `"puree"`, `"soft food"`, `"softer food"`, `"cannot chew"`, `"can't chew"`, `"hard to chew"`, `"no teeth"`, `"no more teeth"`, `"damn hard"`, `"too hard"` — `"soft texture"` is not a substring of any of them → **slips through**.
- `"low sugar"` — `SUGAR_FREE` patterns are `"sugar free"`, `"sugar-free"`, `"no sugar"`, `"diabetic"` — `"low sugar"` isn't a substring of any → **slips through**.
- `"无糖"` (Mandarin "no sugar") — every `QUALIFIER_PATTERNS` phrase is English-only → **slips through**.
- `"tanpa gula"` (Malay "no sugar") — same → **slips through**.

All 5 probes slip the guard. FAIL — this is a fixed list that doesn't generalise across phrasing or language, exactly the AMBER-defining weakness.

**B3.**
```python
@dataclass
class MatchResult:
    ...
    method: str  # "exact_code" | "alias" | "fuzzy" | "llm" | "qualifier_blocked" | "none"
```
and in `app/main.py`:
```python
cur.execute(
    """INSERT INTO feedback.sku_matches
        (feedback_id, term, matched_sku, confidence, method, near_sku, unmet_qualifier)
       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
    (feedback_id, r.term, r.matched_sku, r.confidence, r.method, r.near_sku, r.unmet_qualifier),
)
```
Every resolution's producing layer is persisted. PASS — the resolution-rate metric in `/metrics` can in principle be broken down by `method`, though `/metrics` itself doesn't currently do that breakdown (not part of this check).

### app/skus.py

**C1.** SKU count and alias table:

| Metric | Count |
|---|---|
| SKUs in catalogue | 20 |
| Total alias entries | 61 |
| Mandarin (zh) aliases | 18 |
| Malay (ms) aliases | 14 |
| Tamil (ta) aliases | **1** ("arisi" → RICE-5KG) |
| English/other aliases | 28 |

**C2.** SKUs with **zero non-English aliases**: `RICE-10KG` (zero aliases of *any* kind — only reachable via exact SKU code), `CANNED-BEANS`, `VEG-FROZEN-MIX`, `SOFT-FOOD-PACK`. Separately, SKUs with zero **Tamil** aliases specifically: **19 of 20** — every SKU except `RICE-5KG`.

This compounds with a mechanism gap in `_match_fuzzy`:
```python
def _match_fuzzy(normalized_text: str) -> Optional[tuple[str, float]]:
    tokens = re.findall(r"[a-z]+", normalized_text)
    ...
```
`[a-z]+` never matches Tamil script. So for any Tamil beneficiary text other than the literal transliterated word `"arisi"`, there is no alias hit *and* no fuzzy fallback — layers 2 and 3 are both structurally unable to resolve it, leaving only the (off-by-default) layer-4 LLM adjudication. FAIL — Tamil is carried by exactly one hardcoded string, not a matching strategy.

### app/extract.py

**D1.**
```python
def _extract_once(text, lang, previous_error):
    ...
    if previous_error:
        messages.append({"role": "user", "content": (
            "Your previous output failed validation with this error. "
            f"Fix it and re-emit the full extraction:\n\n{previous_error}"
        )})
    ...

def run_extraction(text, lang):
    ...
    try:
        extraction = _extract_once(text, lang, previous_error=None)
        return extraction, True
    except Exception as first_error:
        extraction = _extract_once(text, lang, previous_error=str(first_error))
        return extraction, False
```
The retry feeds the actual validation error back to the model rather than blindly re-calling. PASS.

**D2.** `URGENCY_RUBRIC` (quoted in full in extract.py lines 53-66) anchors each of 1-5 to a concrete description (e.g. "5 = a safety- or health-critical gap... infant formula completely unavailable"), not a bare "rate urgency 1-5". PASS.

**D3.**
```python
FAKE_EXTRACTION = Extraction(
    sentiment="negative",
    urgency=3,
    categories=["staples", "dietary_accessibility"],
    mentioned_skus=[],
    mentioned_terms=["rice", "gluten free bread"],
    unmet_needs=[UnmetNeed(need="gluten-free bread", confidence=0.7, suggested_category="dietary_accessibility")],
    detected_lang="en",
    summary_en="FAKE_LLM=1 canned extraction -- not a real Bedrock call.",
)
```
`mentioned_terms` is natural-language surface forms ("rice", "gluten free bread"), not pre-resolved SKU codes, and `mentioned_skus` is left empty — exactly as the real pipeline is supposed to produce it. This means `FAKE_LLM=1` smoke tests **do** exercise `resolve_skus` → `match_term`, including hitting the qualifier guard on "gluten free bread". PASS — this is a real strength, worth calling out since it's the opposite of the risk the plan warned about.

**D4.**
```python
try:
    extraction = _extract_once(text, lang, previous_error=None)
    return extraction, True          # first-try success
except Exception as first_error:
    extraction = _extract_once(text, lang, previous_error=str(first_error))
    return extraction, False         # only reached after a retry was needed
```
`schema_valid_first_try` is `True` only when the *first* call succeeds, `False` whenever a retry was required. `/metrics` computes `avg(schema_valid_first_try::int)`. PASS — not inflated by counting post-retry successes as passes.

### app/main.py

**E1.**
```python
@app.post("/feedback", status_code=202)
def post_feedback(payload: FeedbackIn, background_tasks: BackgroundTasks):
    with db.get_cursor() as cur:
        cur.execute("INSERT INTO feedback.feedback_entries (...) VALUES (...) RETURNING id", (...))
        feedback_id = cur.fetchone()["id"]
    logger.info(...)
    background_tasks.add_task(extract_and_store, feedback_id, payload.text, payload.lang)
    return {"id": feedback_id, "status": "received"}
```
The `with db.get_cursor()` block (which commits on clean exit, see F1) closes *before* `background_tasks.add_task` is even called. PASS.

**E2.**
```python
except Exception as e:  # noqa: BLE001 -- never let a bad extraction lose the raw row
    logger.exception("feedback %s: extraction failed", feedback_id)
    with db.get_cursor() as cur:
        cur.execute("UPDATE feedback.feedback_entries SET extraction_status = 'failed', extraction_error = %s WHERE id = %s", (str(e), feedback_id))
```
This is a broad `except Exception`, but it is not a silent swallow: it logs the full traceback via `logger.exception` and unconditionally writes `extraction_status='failed'` with the error text captured. There's no narrower except elsewhere that would let an unexpected error type skip this and leave a row stuck in `pending`. PASS, with the caveat that this is a deliberately broad except used as a last-resort safety net — appropriate here since the whole point is "nothing must be able to strand a row," but flagging it explicitly because Loop B's forbidden-list calls out broad excepts by default.

**E3.**
```python
clauses = []
params: list = []
if since is not None:
    clauses.append("received_at >= %s"); params.append(since)
if urgency is not None:
    clauses.append("urgency = %s"); params.append(urgency)
if category is not None:
    clauses.append("%s = ANY(categories)"); params.append(category)
where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
cur.execute(f"""SELECT ... FROM feedback.feedback_entries {where} ORDER BY received_at DESC""", params)
```
The f-string only ever interpolates static SQL fragments (`"received_at >= %s"`, etc.) that contain no user input — every actual value flows through `params` as a bound `%s`. PASS, not injectable.

### app/db.py

**F1.**
```python
def init_pool(minconn=1, maxconn=10):
    global _pool
    if _pool is not None:
        return
    _pool = psycopg2.pool.SimpleConnectionPool(minconn, maxconn, dsn=dsn)

@contextmanager
def get_conn():
    if _pool is None:
        init_pool()
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)
```
`get_conn()`/`get_cursor()` pulls a fresh connection from the pool on every call (request handler and background task alike) and always returns it via `finally: _pool.putconn(conn)`. There is no module-level single connection held across calls. PASS — this is the GREEN condition for F1; two concurrent submissions each get their own pooled connection, not a shared one.

### schema.sql

**G1.** `CREATE INDEX IF NOT EXISTS idx_feedback_entries_received_at ON feedback.feedback_entries (received_at);` — PASS.
**G2.** `text TEXT NOT NULL` — PASS.
**G3.** `extraction_status TEXT NOT NULL DEFAULT 'pending' CHECK (extraction_status IN ('pending', 'done', 'failed'))` — PASS, constrained not free text.

### frontend/intake/index.html

**H1.** The submit `.catch()` handler doesn't call `showScreen(...)`, so the UI stays on `screen-review`; `state.text` and `textarea.value` are never cleared on failure, and `submitBtn.disabled` is reset to `false` so the user can retry without retyping. PASS.

**H2.** `statusEl.textContent = t("submitting"); submitBtn.disabled = true;` set synchronously before the `fetch` call. PASS.

**H3.**
```javascript
if (!SpeechRecognitionCtor) {
    micBtn.disabled = true;
    micHint.textContent = t("micUnsupported");
}
```
Feature-detected up front; the textarea itself is always present and functional regardless, so typing is never blocked. PASS.
