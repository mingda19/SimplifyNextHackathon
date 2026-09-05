# WS2 Feedback Service — Master Plan

**Everything in this file runs inside Claude Code, with three exceptions that need you personally.** Those three are marked 🖐 **HUMAN** and there is no way around them — they are the parts where a human being is the point.

Supersedes `WS2_BUILD_PLAN.md` and `WS2_CODE_AUDIT.md`. Use only this file.

---

## How to run this

Save this file as `docs/WS2_MASTER_PLAN.md` in the repo and commit it. Then:

```bash
cd <repo root>
git checkout ws2/feedback-service
claude
```

**One phase per Claude Code session.** At the start of each phase, paste the ► PROMPT block. When the phase ends, run the ✅ GATE yourself, commit, then type `/clear` before starting the next phase.

Why `/clear` matters: by phase 4 the context is full of phase 1 file dumps, and a full context is where Claude Code starts forgetting your constraints and re-editing files you told it to leave alone. A clean context per phase is the single biggest thing you can do to avoid bugs.

**If a gate is red, stop.** Paste the failing output back into the same session and fix it there. Do not start the next phase with something red behind you — that is how one bug becomes ten.

**Every phase is sandwiched by two loops** (defined in full after the table): Loop A critiques the phase prompt before you run it, Loop B hunts for failures after the gate goes green. The sequence for every phase is the same five steps:

```
1. paste Loop A          → it raises up to 3 objections, then waits
2. answer the objections → one line each, no essays
3. paste the ► PROMPT    → it builds
4. run the ✅ GATE       → green or stop
5. paste Loop B          → it tries to break what it just built
   then /clear, next phase
```

### The nine phases

| Phase | What | Runs in Claude Code? |
|---|---|---|
| 0 | Audit what already exists | Yes |
| 1 | Fix what the audit found | Yes |
| 2 | Verify the real Bedrock path | Yes |
| 3 | Build the training corpus | Yes, one approval gate 🖐 |
| 4 | Label the human gold set | 🖐 **HUMAN — 100 min, 3 people** |
| 5 | Train the classifier | Yes, GPU step in Colab 🖐 |
| 6 | Wire the model into the service | Yes |
| 7 | Frontend, translation, README | Yes |
| 8 | Merge and demo prep | Yes |

**Every phase is wrapped by the two loops below.** Loop A runs before the phase prompt, Loop B after the gate. They are what stop this from being a plan that only works when nothing goes wrong.

---

# The Two Loops

The way to get a self-critiquing workflow that doesn't spiral is to make critique **cheap to raise and expensive to act on**. Anyone can say "this might fail." Acting on it costs code, and code you added for an imagined problem is a real problem.

So there is one rule underneath both loops:

> ## The Evidence Rule
> **No fix without a failing test first.**
> If Claude Code claims something will break, it must write a test that reproduces the break and watch it fail. If it cannot make the failure happen, the concern goes in `FAILURE_LOG.md` as SPECULATIVE and **no code changes**.

This is the whole anti-hallucination mechanism. A model asked to find problems will always find problems — that's what you asked for, so it complies, and half of what comes back is plausible fiction. Demanding a reproduction is the filter, because you cannot reproduce a bug that isn't there.

### What overcorrection looks like

These are the tells. All four are forbidden in the prompts below, by name, because they are what a model reaches for when it feels obliged to have found something:

- **Broad `except` that swallows.** Turns a loud bug into a silent one. Strictly worse than the crash.
- **A fallback that returns plausible fake data.** The service now lies confidently instead of failing. This is the single most dangerous one in your project, because a fabricated `mentioned_skus` makes a real stock gap vanish and nothing errors.
- **Retry without a cap or backoff.** Converts one failure into a stampede.
- **A config flag nobody sets.** Two code paths, one of them never tested.

If Claude Code produces any of these, reject it and ask what evidence justified it.

---

## Loop A — critique the prompt, before running it

Runs before every ► PROMPT block in this file. Paste this, then the phase prompt.

► **PROMPT — Loop A**

```
Before executing anything, critique the instruction I am about to give you.

Give me AT MOST 3 objections. Rank them. For each one:
  - quote the exact line of my instruction that is the problem
  - say what you would do under interpretation A versus interpretation B
  - say which you would pick by default

An objection only counts if the two interpretations produce DIFFERENT code or
different files. If both readings lead you to the same place, it is not an
ambiguity and I do not want to hear about it.

Do not suggest scope additions. Do not tell me the task is large. Do not offer
alternative approaches unless my instruction is actually impossible.

If you have fewer than 3 real objections, say "N objections" and stop. Padding
to three is worse than having one.

Then WAIT. Do not start work until I answer.
```

Why capped at 3: an uncapped critique request produces a list where items 4 through 9 are filler, and filler is where the hallucinated constraints hide. Capping forces ranking, and ranking is where the judgment is.

---

## Loop B — hunt failures, after the gate is green

Runs after every ✅ GATE. This is the continuous part — the same prompt, every phase, against whatever was just built.

► **PROMPT — Loop B**

```
The gate for this phase is green. Now try to break what we just built.

Work through these eight categories IN ORDER. For each, name the single most
likely failure in the code we just touched, or write NONE:

1. INPUT      - malformed, empty, enormous, wrong encoding, adversarial
2. CONCURRENCY- two things at once, shared state, connection reuse, races
3. DEPENDENCY - Bedrock down, slow, throttling, expired SSO, Postgres gone
4. STATE      - partial writes, crash mid-operation, orphaned rows, stale cache
5. CONTRACT   - anything that changes a field name, type, or nullability that
                another workstream reads
6. MODEL      - valid JSON with wrong content, drift, confident nonsense,
                a language we did not train on
7. HUMAN      - what does a confused elderly user do that we did not plan for
8. DEMO DAY   - what breaks specifically because it is live, on someone else's
                laptop, on conference wifi, at 3pm

Then rank everything you found by (likelihood x blast radius). Take the TOP 5
ONLY. Ignore the rest - if it did not make the top 5 it is not worth the code.

For each of the top 5, in order:
  a) Write a test that reproduces it. Run it.
  b) IF IT FAILS -> it is real. Fix it. Re-run. One commit.
  c) IF IT PASSES -> the code already handles it. Say "already handled",
     KEEP the test, change NOTHING else.
  d) IF YOU CANNOT WRITE A TEST for it -> log it as SPECULATIVE in
     services/feedback/FAILURE_LOG.md and write NO code.

Show me each test result before moving to the next item.

FORBIDDEN, no matter what you find:
  - a bare or broad except that swallows an error
  - any fallback that returns plausible-looking fake data instead of failing
  - a retry without a cap and a backoff
  - a new config flag to switch between two behaviours
  - changing any field name in the extraction contract
If you think one of these is genuinely needed, stop and ask me first with your
evidence.

Append to services/feedback/FAILURE_LOG.md: date, phase, what you hunted, the
top 5, verdict per item (FIXED / ALREADY HANDLED / SPECULATIVE), commit hashes.
```

**What you do with the output.** Read every "already handled" claim and spot-check one of them by breaking the code on purpose. If the test still passes after you break it, the test is fake and so is the reassurance. This takes two minutes and it is the only way you'll catch a test that asserts nothing.

---

## Where to point Loop B, per phase

Loop B is generic on purpose, but each phase has a place where the bugs actually live. Add the relevant line to the Loop B prompt when you run it:

| After phase | Point it here specifically |
|---|---|
| 0 Audit | Nothing to break yet — skip Loop B, the audit *is* the hunt |
| 1 Fixes | Every fix you just made. Fixes introduce bugs at a higher rate than original code. |
| 2 Bedrock | Category 3. Expired SSO mid-run, throttling, a 30-second response, a truncated one. |
| 3 Corpus | Category 6 and the leak. Assert gold texts appear in no other split. Check the generator did not silently produce 3,000 items in one language. |
| 4 Gold labels | Category 7. Do three labellers agree? Sample 20 items and check. |
| 5 Training | Category 6. Does the model collapse to one class? Check per-class F1, not just macro. A model predicting "negative" always looks fine on an imbalanced set. |
| 6 Wiring | Category 5 and 1. Missing weights, corrupt weights, a language the model never saw. |
| 7 Frontend | Category 7 and 8. Offline, slow 3G, mid-submission refresh, double-tap submit. |
| 8 Merge | Category 8. Clone fresh into a clean directory and follow your own README. |

---

## The loop, end to end

```
Loop A  →  answer its objections  →  ► phase prompt  →  ✅ gate  →  Loop B
   ↑                                                                  │
   └──────────────────  /clear, next phase  ←─────────────────────────┘
```

**Stop condition.** Loop B is not run until nothing is found — it's run once per phase and then you move on. Two consecutive phases where Loop B finds nothing real is a signal the hunt has gone stale, not that the code is perfect: change the category order, or point it somewhere it hasn't looked.

---

# PHASE 0 — Audit

Your progress notes say the service is done and 27/27 golden tests pass. That proves the 27 cases someone thought to write. It does not prove they were the right 27. This phase finds out.

**The rule for this phase: Claude Code reports, it does not fix.** If you let it fix things while auditing, you get a diff you didn't review and an audit you can't trust. Fixing is Phase 1.

► **PROMPT — paste this whole block**

```
You are auditing existing code. DO NOT MODIFY ANY FILE in this phase except
the one report file named at the end. If you find a bug, write it down and
keep going. I will decide what gets fixed.

Read everything under services/feedback/ and frontend/intake/ first.

Then work through these checks IN ORDER. For each one, quote the actual lines
of code you are judging, then give a verdict of PASS, WEAK or FAIL, then one
sentence of reasoning. Do not give a verdict without quoting code - if you
cannot find the relevant code, say NOT FOUND.

--- tests/test_matcher.py ---
A1. Count the GOLDEN cases. How many expect a match, how many expect None?
    Report the ratio. If fewer than a third expect None, verdict WEAK: the set
    only measures the easy direction, and a matcher that matches everything
    would still score 27/27.
A2. Are there qualifier hard-negatives - gluten free bread, halal baby formula,
    low sodium noodles, pureed vegetables, or equivalents? List which exist.
A3. Count cases per language. Is it English with two foreign entries bolted on?
A4. Is any test asserting only "did not crash" or "returned a list"? Name them.

--- app/matcher.py ---
B1. Find the fuzzy threshold. Quote it. Is there a comment justifying the
    number, or is it an unexplained round figure?
B2. Is the qualifier guard a fixed list of words, or does it generalise? Quote
    the list. Then tell me which of these would slip through it: "no MSG",
    "soft texture", "low sugar", "无糖", "tanpa gula".
B3. Does every resolution record WHICH layer produced it, and is that persisted
    to sku_matches? If not, the resolution-rate metric cannot distinguish a
    confident exact match from a lucky fuzzy one.

--- app/skus.py ---
C1. Table: SKU count, total aliases, aliases per language (en/zh/ms/ta).
C2. How many SKUs have zero non-English aliases? If that number is high, the
    Malay and Tamil entries are being carried entirely by fuzzy matching,
    which is exactly where false matches come from.

--- app/extract.py ---
D1. On schema-validation failure, does the retry send the validation error back
    to the model, or blindly re-call the same prompt? Quote the retry block.
D2. Find the urgency rubric in the prompt. Is each level 1-5 anchored to a
    concrete description, or does it just say "rate urgency 1-5"? Quote it.
D3. Read the FAKE_LLM fixture. Does it return natural-language mentioned_terms,
    or does it hand back SKU codes directly? If the latter, every smoke test so
    far has skipped the matcher's hardest layer. This is important - be exact.
D4. Where is the schema-pass-rate metric incremented - before or after the
    retry? It must count FIRST-ATTEMPT successes or the number is inflated.

--- app/main.py ---
E1. In POST /feedback, is the raw row COMMITTED before the BackgroundTask is
    scheduled? Quote the order of operations.
E2. Where is extraction_status='failed' set? Is it in a finally block or a
    broad except, or only in a narrow except that would let an unexpected
    error leave the row stuck in 'pending' forever?
E3. Are the since/urgency/category filters passed as bound query parameters,
    or built with f-strings or string concatenation? An f-string here is SQL
    injection. Quote the exact lines.

--- app/db.py ---
F1. THE BIG ONE. Does the BackgroundTask get its own database connection, or
    does it reuse a connection from the request that has already returned, or
    a module-level global? Quote how connections are created and where.
    A module-level connection passes every single-user smoke test and fails
    the moment two people submit at once - which is what happens during a
    live demo.

--- schema.sql ---
G1. Index on created_at? (GET /feedback?since= range-scans it.)
G2. Is the raw text column NOT NULL?
G3. Is extraction_status constrained to valid values, or free text?

--- frontend/intake/index.html ---
H1. On a failed fetch, is the user's typed text preserved in the box, or lost?
H2. Is there a visible loading state? POST returns 202 and extraction is async.
H3. Does the Web Speech API path degrade silently to typing when unsupported?

--- OUTPUT ---
Write all of this to services/feedback/AUDIT.md with a summary table at the
top: check id, verdict, one-line issue. Then a RED / AMBER / GREEN overall
verdict using this rubric:

RED    - any of: module-level DB connection reused by background tasks,
         f-string SQL, or a FAKE_LLM fixture that bypasses the matcher.
AMBER  - works, but qualifier guard is a short fixed list and the alias table
         is English-heavy.
GREEN  - golden set has real None cases, fuzzy threshold demonstrably
         protects something, background task has its own connection, failure
         path is a finally.

Then STOP. Do not fix anything. Do not create any other file.
```

✅ **GATE** — `services/feedback/AUDIT.md` exists. `git status` shows **only** that file as new. Read the summary table yourself — you need to know what's in it, because M or a judge will ask.

```bash
git add services/feedback/AUDIT.md
git commit -m "WS2: audit of existing feedback service"
```

Then `/clear`.

---

# PHASE 1 — Fix what the audit found

► **PROMPT**

```
Read services/feedback/AUDIT.md.

Fix every FAIL and every WEAK, in this order - highest risk first:
  1. F1 (database connections)
  2. E1, E2, E3 (commit ordering, failure path, SQL parameters)
  3. D3, D4 (fake fixture bypassing the matcher, inflated metric)
  4. B1, B2, B3 (fuzzy threshold, qualifier guard, layer logging)
  5. A1, A2, A3 (golden set gaps)
  6. C1, C2 (alias coverage)
  7. G, H (schema and frontend)

Rules:
- ONE fix per commit. Message format: "WS2 fix <check-id>: <what>".
- After each fix, run `python -m pytest tests/ -v` and paste me the result
  before starting the next fix. If it goes red, fix that before continuing.
- Do NOT change any field name in the extraction contract. sentiment, urgency,
  categories, mentioned_skus, mentioned_terms, unmet_needs, detected_lang,
  summary_en are frozen - another workstream's queries depend on them.
- Do NOT implement GET /feedback/unmet-needs. It stays a 501 stub. It belongs
  to my teammate M. If you think it would be easy, the answer is still no.

For A1-A3 specifically: add the missing golden cases FIRST and watch them fail,
then fix the matcher until they pass. Never write the fix before the test - I
want to see red before green, otherwise we do not know the test works.

For B1: before changing the fuzzy threshold, run an experiment. Lower it by 10
points, run the golden set, and tell me how many false matches appear. If the
answer is zero, the threshold is decorative and we should say so. If it is
many, tell me the number - that is a good thing to quote in the demo.

Update AUDIT.md as you go: mark each check FIXED with the commit hash.
```

✅ **GATE**

```bash
cd services/feedback && python -m pytest tests/ -v
git log --oneline -20
```

All green. Every FAIL in `AUDIT.md` marked FIXED. `/clear`.

---

# PHASE 2 — Verify the real Bedrock path, then break it on purpose

`FAKE_LLM=1` has carried this service the whole way. Until it runs with `FAKE_LLM=0` you do not know it works. This is the most likely thing to be quietly broken, which is why it comes before all the new work.

► **PROMPT**

```
Goal: prove the real Bedrock path works, then prove it fails safely.

PART A - isolate auth from service.
1. Read services/orchestrator/llm.py. Confirm services/feedback/app/extract.py
   builds its client identically - same AnthropicBedrockMantle pattern, same
   SSO profile resolution. Show both side by side. If they diverge, change
   feedback to match orchestrator; orchestrator is the reference.
2. Write services/feedback/scripts/check_bedrock.py: makes ONE minimal call
   through that client, prints the response and the model id. No DB, no
   FastAPI. This separates an auth failure from a service failure.
3. Run it. If it fails on credentials, give me the exact `aws sso login`
   command. Do not retry blindly and do not start editing code.

PART B - end to end.
4. Write services/feedback/scripts/smoke_real.py: POSTs 5 seed entries to a
   running service - one English, one Singlish, one Mandarin, one Malay, one
   that should match NO sku - then polls GET /feedback until each is done or
   failed. Prints per entry: raw text, parsed JSON, matched SKUs, WHICH MATCH
   LAYER fired, and latency in ms.
5. Run the service with FAKE_LLM=0, run smoke_real.py, paste me the full
   output. If anything comes back failed, show me the captured error BEFORE
   attempting a fix.

PART C - the empirical pass. This is where real bugs live.
6. Write services/feedback/scripts/adversarial.py that POSTs each of these and
   asserts the stated expectation:
   - empty string                -> 422 or clean rejection, never a 500
   - 10,000 characters           -> handled or clearly rejected
   - emoji only                  -> row stored, extraction returns valid JSON
   - "'; DROP TABLE feedback_entries; --"  -> stored as literal text, table
                                              still exists afterwards
   - same entry twice, rapidly   -> two rows, no crash
   - TWO POSTs simultaneously    -> both complete. This is the real test of
                                    the db.py fix from Phase 1.
   - fixture returning sentiment:"angry" (temporarily edit the FAKE_LLM
     fixture) -> validation catches the bad enum and retries
7. Run it. Report every failure. Fix them one at a time, test after each.

Record the p50 and p95 latency from step 5 in AUDIT.md. I will quote those.
```

✅ **GATE** — All 5 smoke entries reach `done`. Mandarin entry shows `detected_lang: "zh"`. The unmatchable entry has empty `mentioned_skus` and populated `unmet_needs`. Every adversarial case passes. Commit, `/clear`.

---

# PHASE 3 — Build the training corpus

### Why this phase exists, and how much data you actually need

You asked how big the dataset needs to be. The answer splits three ways and they are very different:

**Evaluating the Claude extraction path** needs no training data at all. It needs a *gold set* — items a human labelled by hand. Size is set by the confidence interval you want to report:

| Gold set | 95% CI on a measured ~90% accuracy | Verdict |
|---|---|---|
| 50 | ±8.3% | Too noisy to claim anything |
| 100 | ±5.9% | Minimum defensible |
| **200** | **±4.2%** | **Target** |
| 400 | ±3.0% | Diminishing returns in a hackathon |

Your 50 seed entries are not a gold set — they were written as demo inputs, not labelled ground truth.

**Fine-tuning a real classifier:**

| Approach | Labelled examples | Trains on | Time |
|---|---|---|---|
| Frozen multilingual encoder + logistic-regression head | **400–800** | your laptop CPU | ~30 sec |
| Fine-tune `distilbert-base-multilingual-cased` | 2,000–3,000 | Colab free T4 | ~10 min |
| Fine-tune `xlm-roberta-base` | **3,000–5,000** | Colab free T4 | ~20 min |
| Train from scratch | 100,000+ | — | Do not |

Rule of thumb for a transformer head: ~300–500 clean examples per class minimum, ~1,000 to be comfortable. Below ~200 per class a fine-tune reliably does *worse* than the frozen-encoder option, because you have enough data to overfit the encoder but not enough to teach it anything.

**The SKU matcher** is not a trained model and should not become one. It needs alias coverage. One good alias beats fifty training rows.

### The three changes that make the model genuinely stronger

**1. Drop DistilBERT SST-2.** English-only, trained on movie reviews. Your inputs are Singlish, Mandarin, Malay, Tamil and code-switched. It isn't weakly matched to your domain, it's the wrong tool — a Mandarin entry tokenises into near-noise and the agreement number it produces is meaningless. A multilingual encoder is the single biggest quality jump available to you.

**2. Fine-tune it on your own data, with Claude as the teacher.** Claude labels ~3,000 generated utterances; you fine-tune a small multilingual model on those labels; the small model then runs locally at ~20ms and $0 per call instead of ~2s and a Bedrock charge. That is a real engineering result with a real number attached, and it's a much better answer to "did you train a model?" than pointing at an off-the-shelf checkpoint.

**3. Your test set must never be labelled by Claude.** If you train on Claude's labels and evaluate against Claude's labels, you are measuring how well the student copies the teacher, not whether either is right. That number is worthless and a sharp judge will find it in one question. So: train and dev are Claude-labelled; the 200-item gold test set is human-labelled, held out, and Claude never sees it. You report two numbers with two different names — *agreement with teacher* and *accuracy against human labels*.

### Target composition — 3,000 train / 300 dev / 200 human gold

| Dimension | Target |
|---|---|
| English + Singlish | 40% |
| Mandarin | 20% |
| Malay | 15% |
| Tamil | 10% |
| Code-switched (2+ languages in one utterance) | 15% |
| Sentiment neg / neu / pos | 40 / 35 / 25 |
| Urgency band routine / elevated / urgent | 45 / 35 / 20 |
| Entries resolving to NO sku (real stock gaps) | 20% |
| Qualifier hard-negatives | 10% |

**Collapse urgency to 3 bands for the classifier.** Keep 1–5 in the Claude output — M's queries need it — but a 5-way ordinal over 3,000 examples leaves fuzzy boundaries and the classifier will thrash on 3-vs-4. Map 1–2 → routine, 3 → elevated, 4–5 → urgent.

**The real risk is diversity collapse, not volume.** 3,000 items from one prompt are effectively 200 items with reworded padding, and a model trained on them looks great on dev and dies on anything real. The prompt below defends against it with rotating generation axes and a near-duplicate filter.

► **PROMPT**

```
Goal: build a training corpus. Work in services/feedback/data/. Follow the
steps in order and STOP where told - do not run ahead.

STEP 1 - seed vocabulary.
Read seed/feedback_seed.json. Extract every distinct item term, complaint
phrase and dietary qualifier, grouped by language. Write data/seed_vocab.json.
Show me counts per language. STOP.

STEP 2 - the generator.
Write data/generate_corpus.py. Generates beneficiary utterances via the same
Bedrock client the service uses. Requirements:
- Batches of 25. Never one giant call.
- Every batch samples INDEPENDENTLY along all of these axes:
    language (per the mix in the plan's composition table)
    persona (elderly alone / single parent / migrant worker / caregiver /
             young adult)
    register (blunt / polite / rambling / terse / indirect)
    length (5-12 words / 13-30 / 31-60)
    directness (need stated outright vs only implied)
- Ground every batch in 5 randomly sampled terms from seed_vocab.json so the
  vocabulary stays real.
- Track running counts against the target table and STEER later batches to hit
  the targets. Do not generate uniformly and hope.
- 20% must resolve to NO sku in app/skus.py.
- 10% must be qualifier hard-negatives - halal / gluten-free / low-sodium /
  pureed / no-sugar variants of things we DO stock.
- Dedup: embed candidates with
  sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2, reject cosine
  > 0.93 against anything already accepted. Log the rejection rate.
- Checkpoint to disk every batch. A crash must lose at most 25 items.
- CLI: --n --out --resume

Generate 100 items as a test. Show me 20, spread across languages. STOP.
I am reading these before we spend money on 3000.

STEP 3 - full run. Only after I say go.
Generate 3300 items to data/corpus_raw.jsonl. Print the final distribution
against EVERY row of the target table. Flag anything more than 5 percentage
points off. If the dedup rejection rate is above 35%, STOP and tell me - the
generator has fallen into a rut and lowering the threshold would hide the
problem instead of fixing it.

STEP 4 - teacher labelling.
Write data/label_corpus.py. For each item call the EXISTING pipeline in
app/extract.py. Do not write a second, different prompt - if the teacher prompt
differs from the service prompt, the student learns a different task than the
service performs. Store the full extraction plus a derived urgency_band
(1-2 routine, 3 elevated, 4-5 urgent). Output data/corpus_labelled.jsonl.
Batched, checkpointed, resumable. Report total cost and failure count.

STEP 5 - splits.
data/make_splits.py: stratified by (language, sentiment, urgency_band).
3000 train / 300 dev. ASSERT no text appears in both, and make the assertion
fatal. Write data/train.jsonl and data/dev.jsonl.

STEP 6 - prepare the human gold set. Read this carefully.
Take the 50 seed entries plus 150 sampled from corpus_raw.jsonl - sampled
BEFORE labelling, so Claude's answer is not in the file. Write
data/gold_unlabelled.jsonl.
Then build data/label_tool.html: a single self-contained page, no server, no
build step, opens from file://. Shows one entry at a time, three buttons for
sentiment, three for urgency band, a text field for expected SKUs, next/back,
progress counter, and an export-to-JSON button. Must survive a page refresh
(keep progress in memory and warn before unload).

DO NOT LABEL THESE WITH CLAUDE. Do not call the model on gold_unlabelled.jsonl
for any reason. The entire evaluation depends on Claude never having seen them.
```

✅ **GATE** — `train.jsonl` 3,000 rows, `dev.jsonl` 300, `gold_unlabelled.jsonl` 200, distribution within 5 points on every row, dedup rejection rate under 35%. Commit, `/clear`.

---

# PHASE 4 🖐 HUMAN — Label the gold set

**This is the one thing Claude Code cannot do for you**, and not because of a tooling limit. The gold set is the only place in the project where a human decides what the right answer is. If a model produces it, you have no ground truth, only a mirror.

Open `data/label_tool.html` in a browser. 200 items, three people, ~70 each, about 100 minutes total. Split it so every item gets exactly one labeller — you don't have time for double-labelling.

Two rules while labelling:
- Label what the text actually says, not what you'd like the model to output. If an utterance is genuinely ambiguous between neutral and negative, that ambiguity is real information and the model should lose points for it.
- If you find yourself unable to decide on more than about 10% of items, your label definitions are too vague. Stop, write down a one-line definition for each of the six classes, agree it with the other two labellers, and start over. Half an hour spent here saves you from a meaningless number later.

Export to `data/gold_labelled.jsonl`, commit it.

---

# PHASE 5 — Train

The GPU step runs in Colab because there's no GPU in your stack. Everything else is Claude Code.

► **PROMPT**

```
Goal: train a multilingual classifier on data/train.jsonl. Two heads -
sentiment (3-class) and urgency_band (3-class). Build BOTH options; the
baseline is the safety net.

OPTION A - baseline. CPU only. Build this FIRST so we always have something.
services/feedback/model/train_baseline.py:
  frozen sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
  embeddings + sklearn LogisticRegression per head. Cache embeddings to disk
  so retraining is instant. Save to model/baseline/. Must train in under
  2 minutes on CPU. Report accuracy and macro-F1 on dev.

OPTION B - fine-tune.
services/feedback/model/train_finetune.py plus model/finetune_colab.ipynb.
I have no local GPU - the notebook must run start to finish on a free Colab
T4, clone the repo or accept an uploaded data folder, and download the trained
weights at the end.
  Base: xlm-roberta-base. If it OOMs at batch 16 on a T4, fall back to
  distilbert-base-multilingual-cased and SAY SO in the output.
  Two heads on a shared encoder, joint loss.
  3 epochs, lr 2e-5, 10% warmup, early stopping on dev macro-F1, seed 42.
  Class weights inverse to frequency - the corpus is deliberately imbalanced.
  Save to model/finetuned/ plus model_card.md recording base model, data size,
  class distribution, hyperparameters, dev metrics and training time.

EVALUATION - services/feedback/model/evaluate.py.
Loads both models and the raw Claude path. Scores all three on:
  (a) data/dev.jsonl           -> label this "agreement with teacher"
  (b) data/gold_labelled.jsonl -> label this "accuracy vs human labels"
Use those exact two labels in the output. NEVER call (a) accuracy - the dev set
is Claude-labelled and calling it accuracy is the mistake that makes the whole
evaluation worthless.
Print: accuracy, macro-F1, per-class F1, per-language breakdown, mean inference
latency in ms, for all three systems.
Also dump the 20 worst gold-set errors with text / predicted / actual. I want
to read them.
Write the comparison table to model/RESULTS.md.
```

✅ **GATE** — Baseline trains on CPU and clears random (>0.33 macro-F1) comfortably. Fine-tune beats baseline on **gold** macro-F1.

**If the fine-tune does not beat the baseline, ship the baseline.** A simple model you can explain is worth more than a fine-tune you can't. That is a legitimate result, not a failure — say it in the demo.

Read the 20 worst errors. If they cluster in one language, that language is under-represented: go back to Phase 3 and generate more of it. Commit, `/clear`.

---

# PHASE 6 — Wire it in without breaking the contract

► **PROMPT**

```
Goal: replace the DistilBERT SST-2 classifier in app/extract.py with our
trained model. The API contract must not change.

1. app/classifier.py: loads model/finetuned/ if present, else model/baseline/,
   else disables itself cleanly. Lazy-load ONCE at module import, never per
   request. Expose predict(text) -> {sentiment, sentiment_confidence,
   urgency_band, urgency_band_confidence}.

2. In extract.py keep the existing framing EXACTLY: Claude's sentiment stays
   AUTHORITATIVE, the classifier is a DISAGREEMENT FLAG. Keep classifier_agrees
   as-is. Add classifier_urgency_agrees the same way. The classifier must never
   overwrite a Claude field.

3. If the model fails to load: log a warning, set classifier_agrees to null,
   service keeps running. The classifier must never be able to take the service
   down.

4. Add to GET /metrics: sentiment agreement rate and urgency agreement rate,
   each split by detected_lang. This is the number that tells us when
   extraction quality drifts.

5. Config flag CLASSIFIER_ENABLED, default 1.

6. Run the full suite - it must stay green. Then add tests/test_classifier.py:
   model loads, returns valid labels, degrades gracefully with weights absent.

Do NOT touch matcher.py, skus.py, or the extraction JSON schema in this phase.
Then show me `git diff --stat` and confirm no contract field name changed.
```

✅ **GATE** — Suite green, `smoke_real.py` green, `/metrics` shows per-language agreement, no contract field renamed. Commit, `/clear`.

---

# PHASE 7 — Frontend, translation, README

► **PROMPT**

```
Three jobs. One at a time, show me each before moving on.

JOB 1 - intake UI against a live backend.
Serve frontend/intake/index.html, submit through it against the running
service, and fix what breaks. It needs:
  - visible loading state (POST returns 202, extraction is async)
  - a success confirmation an elderly user cannot miss
  - a network-failure state that does NOT lose typed text - keep it in the box
    and offer retry
  - Web Speech API degrading silently to typing when unsupported
Do not redesign it. Font, sizes and tap targets stay exactly as they are.

JOB 2 - translation, the README stretch goal.
summary_en already exists in the extraction output - that IS the translation
path. Surface it: add ?lang=en to GET /feedback so it returns summary_en as
the display text. No new model, no new API. This should be about 20 lines.

JOB 3 - documentation.
Update services/feedback/README.md: run instructions from a clean clone, the
pipeline diagram, the frozen contract, the model card summary, the evaluation
table from model/RESULTS.md, and an explicit line saying
GET /feedback/unmet-needs is owned by M and intentionally unimplemented.
Then docs/DEMO_SCRIPT.md: a 3-minute walkthrough with the exact commands and
the exact seed entries to submit, including one that produces a stock gap.
```

✅ **GATE** — Hand the README to a teammate and have them clone and run it without asking you anything. If they ask a question, the README has a hole. Commit, `/clear`.

---

# PHASE 8 — Merge

► **PROMPT**

```
Prepare the merge.
1. git pull origin main, then rebase ws2/feedback-service onto it. Resolve
   conflicts ONE FILE AT A TIME and show me each resolution before continuing.
2. Run the full suite plus scripts/smoke_real.py after the rebase. Both green
   before we push.
3. Write the PR description into docs/PR_BODY.md: what the service does, the
   pipeline diagram, the evaluation table from model/RESULTS.md, the audit
   summary from AUDIT.md showing what was found and fixed, the p50/p95
   latency, and an explicit note that GET /feedback/unmet-needs is left for M.
```

Then push and open a PR — do not merge it yourself.

The evaluation table from Phase 5 is the strongest single artefact in this whole plan. It's the thing that turns "we used an LLM" into "we trained a model and measured it against human labels." Put it near the top of the PR and near the top of the deck.

---

## The four things most likely to go wrong

**Generation cost.** 3,300 generated + 3,300 labelled is ~6,600 Bedrock calls. Run the 100-item test, extrapolate, and tell your team the number *before* you spend it. If it's too high, drop to 1,500 train items and ship the frozen-encoder baseline — it's comfortably within its data range at that size.

**Diversity collapse.** Dedup rejecting more than ~35% means the generator is in a rut. Add axes and restart. Do not lower the threshold; that hides the problem rather than fixing it.

**Gold set leakage.** If any gold text also appears in `train.jsonl`, every number you report is inflated. The Phase 3 assertion exists for exactly this. When it fires, fix the split — never delete the assertion.

**Scope creep into M's endpoint.** Claude Code will notice `unmet-needs` is a stub and offer to implement it. Repeatedly. Say no every time. Taking a teammate's deliverable is a worse outcome than an unimplemented endpoint.
