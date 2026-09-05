#!/usr/bin/env python
"""Score extraction quality on the held-out test split.

    python scripts/eval_extraction.py                 # mechanical metrics only
    python scripts/eval_extraction.py --judge          # + LLM-as-judge on topics/SKUs
    python scripts/eval_extraction.py --limit 40       # cheap smoke run

WHAT IS MEASURED, AND HOW IT IS GROUNDED
----------------------------------------
The corpus ships no extraction labels, so the metrics fall into three tiers by
how trustworthy they are — stated explicitly rather than blended into one score:

  LABEL-BACKED   language detection, scored against the corpus's own `lang`
                 field. This is real ground truth.
  MECHANICAL     schema validity, SKU resolution rate, qualifier-block rate,
                 catalogue-membership of every resolved SKU. No judgement
                 needed — a resolved SKU either exists in inventory or doesn't.
  JUDGED         topic faithfulness and SKU correctness, rated by a STRONGER
                 model (Sonnet) than the one doing extraction (Haiku). An
                 estimate, not ground truth; a judge shares blind spots with
                 the thing it judges.

COST
----
Every row is a live Bedrock call. Spend is tracked and the run aborts at
--max-spend rather than quietly draining the hackathon budget.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings                      # noqa: E402
from app.extract import resolve_skus, run_extraction  # noqa: E402
from app.skus import SKU_BY_CODE                      # noqa: E402

HERE = Path(__file__).resolve().parent.parent
EVAL = HERE / "eval"

# first-party planning rates, USD per 1M tokens
RATES = {"haiku": (1.0, 5.0), "sonnet": (2.0, 10.0)}
# Sonnet 5 is NOT enabled on this account (403 "not available for this
# account"); 4.6 is, and is still a stronger model than the Haiku doing the
# extraction, which is what matters for a judge.
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "us.anthropic.claude-sonnet-4-6")

JUDGE_SYSTEM = """You audit an information-extraction system for a food charity.

You get: the beneficiary's original message, what the extractor pulled out, and
which catalogue SKU (if any) the matcher resolved it to.

Rate three things. Be strict; this audit exists to find failures.

topic_faithful: does `unmet_needs` + `categories` reflect what the message
    actually says? false if it invents a need, misses the main one, or
    mischaracterises it.
sku_verdict: one of
    "correct"           a sensible SKU was picked for the need
    "wrong"             a SKU was picked but it is the wrong item
    "correct_refusal"   no SKU picked, and that is right (nothing suitable is
                        stocked, or a dietary/texture qualifier is unmet)
    "missed"            no SKU picked, but a listed SKU would have served
urgency_reasonable: is the 1-5 urgency defensible for this message?"""


class Spend:
    def __init__(self, cap: float):
        self.cap, self.usd, self.calls = cap, 0.0, 0
        self.tokens = Counter()

    def add(self, usage, kind: str) -> None:
        i = int(getattr(usage, "input_tokens", 0) or 0)
        o = int(getattr(usage, "output_tokens", 0) or 0)
        r_in, r_out = RATES[kind]
        self.usd += (i * r_in + o * r_out) / 1_000_000
        self.calls += 1
        self.tokens[f"{kind}_in"] += i
        self.tokens[f"{kind}_out"] += o

    def check(self) -> None:
        if self.usd >= self.cap:
            raise SystemExit(
                f"\n  ABORTED at ${self.usd:.4f} (cap ${self.cap:.2f}). "
                f"Raise --max-spend deliberately to continue.")


def judge(client, row, ex, resolutions, spend: Spend) -> dict:
    catalogue = ", ".join(sorted(SKU_BY_CODE))
    payload = {
        "message": row["text"],
        "extracted": {
            "categories": ex.categories,
            "unmet_needs": [u.model_dump() for u in ex.unmet_needs],
            "mentioned_terms": ex.mentioned_terms,
            "urgency": ex.urgency,
        },
        "matcher_result": [
            {"term": r.term, "matched_sku": r.matched_sku, "method": r.method,
             "near_sku": r.near_sku, "unmet_qualifier": r.unmet_qualifier}
            for r in resolutions
        ],
        "catalogue": catalogue,
    }
    from pydantic import BaseModel
    from typing import Literal

    class Verdict(BaseModel):
        topic_faithful: bool
        sku_verdict: Literal["correct", "wrong", "correct_refusal", "missed"]
        urgency_reasonable: bool
        note: str

    resp = client.messages.parse(
        model=JUDGE_MODEL, max_tokens=512, system=JUDGE_SYSTEM,
        messages=[{"role": "user",
                   "content": json.dumps(payload, ensure_ascii=False)}],
        output_format=Verdict,
    )
    spend.add(resp.usage, "sonnet")
    return resp.parsed_output.model_dump()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--max-spend", type=float, default=1.50)
    ap.add_argument("--out", type=Path, default=EVAL / "results.json")
    args = ap.parse_args()

    if settings.fake_llm:
        raise SystemExit("  FAKE_LLM=1 — set FAKE_LLM=0 to evaluate the real model.")

    rows = json.loads((EVAL / f"{args.split}.json").read_text(encoding="utf-8"))
    if args.limit:
        rows = rows[: args.limit]

    spend = Spend(args.max_spend)
    client = None
    if args.judge:
        from anthropic import AnthropicBedrock
        client = AnthropicBedrock(aws_profile=settings.aws_profile,
                                  aws_region=settings.bedrock_region)
        # Preflight: fail in 1 call, not after 192 extractions.
        try:
            client.messages.create(model=JUDGE_MODEL, max_tokens=4,
                                   messages=[{"role": "user", "content": "hi"}])
            print(f"  judge model OK: {JUDGE_MODEL}")
        except Exception as exc:                      # noqa: BLE001
            raise SystemExit(f"  judge model {JUDGE_MODEL} unusable: "
                             f"{type(exc).__name__}: {str(exc)[:160]}\n"
                             f"  Set JUDGE_MODEL to an enabled model, or drop --judge.")

    results, t0 = [], time.time()
    for n, row in enumerate(rows, 1):
        spend.check()
        rec: dict = {"beneficiary_id": row["beneficiary_id"], "lang": row.get("lang"),
                     "text": row["text"]}
        try:
            ex, first_try = run_extraction(row["text"], row.get("lang"))
            # usage isn't returned by run_extraction; approximate from the call
            res = resolve_skus(ex.mentioned_terms, context=row["text"])
            rec.update(
                ok=True, schema_valid_first_try=first_try,
                detected_lang=ex.detected_lang, urgency=ex.urgency,
                sentiment=ex.sentiment, categories=ex.categories,
                terms=ex.mentioned_terms,
                needs=[u.model_dump() for u in ex.unmet_needs],
                matches=[{"term": r.term, "sku": r.matched_sku, "method": r.method,
                          "near_sku": r.near_sku, "unmet": r.unmet_qualifier}
                         for r in res],
            )
        except Exception as exc:                      # noqa: BLE001
            rec.update(ok=False, error=f"{type(exc).__name__}: {exc}")

        # Judged SEPARATELY: a judge outage must not invalidate an extraction
        # that actually succeeded. (It did exactly that on the first run and
        # threw away 192 good rows.)
        if args.judge and rec.get("ok"):
            try:
                rec["judge"] = judge(client, row, ex, res, spend)
            except Exception as exc:                  # noqa: BLE001
                rec["judge_error"] = f"{type(exc).__name__}: {exc}"
        results.append(rec)
        if n % 25 == 0:
            print(f"    {n}/{len(rows)}  {time.time()-t0:.0f}s  ~${spend.usd:.3f}")

    args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    report(results, spend, time.time() - t0, args.out)
    return 0


def report(results, spend, elapsed, out_path) -> None:
    n = len(results)
    ok = [r for r in results if r.get("ok")]
    print(f"\n\033[1m  EXTRACTION EVAL — {n} rows, {elapsed:.0f}s\033[0m\n")

    print("  \033[1mLABEL-BACKED\033[0m (scored against the corpus's own `lang`)")
    lang_rows = [r for r in ok if r.get("lang")]
    hit = sum(1 for r in lang_rows if r["detected_lang"] == r["lang"])
    print(f"    language detection      {hit}/{len(lang_rows)} = "
          f"{hit/len(lang_rows):.1%}" if lang_rows else "    (no lang labels)")
    conf = defaultdict(Counter)
    for r in lang_rows:
        conf[r["lang"]][r["detected_lang"]] += 1
    for src in sorted(conf):
        got = ", ".join(f"{k}:{v}" for k, v in conf[src].most_common(3))
        print(f"      {src:5} -> {got}")

    print("\n  \033[1mMECHANICAL\033[0m (no judgement needed)")
    print(f"    extraction succeeded    {len(ok)}/{n} = {len(ok)/n:.1%}")
    if ok:
        sv = sum(1 for r in ok if r["schema_valid_first_try"])
        print(f"    schema valid 1st try    {sv}/{len(ok)} = {sv/len(ok):.1%}")
    terms = [m for r in ok for m in r["matches"]]
    if terms:
        res = sum(1 for m in terms if m["sku"])
        blocked = sum(1 for m in terms if m["method"] == "qualifier_blocked")
        bad = [m["sku"] for m in terms if m["sku"] and m["sku"] not in SKU_BY_CODE]
        print(f"    terms seen              {len(terms)}")
        print(f"    resolved to a SKU       {res}/{len(terms)} = {res/len(terms):.1%}")
        print(f"    qualifier-blocked       {blocked} ({blocked/len(terms):.1%})")
        print(f"    resolved SKU NOT in     {len(bad)}   <- must be 0")
        print(f"      the live catalogue")
        meth = Counter(m["method"] for m in terms)
        print(f"    methods                 {dict(meth.most_common())}")
    if ok:
        gaps = sum(1 for r in ok
                   if r["needs"] and not any(m["sku"] for m in r["matches"]))
        print(f"    rows whose need maps to {gaps}/{len(ok)} = {gaps/len(ok):.1%}")
        print(f"      NO stocked SKU (gap)")
    else:
        print("\n  every row failed — see `error` in the results file")
        for r in results[:1]:
            print(f"    {r.get('error','')[:160]}")

    jerr = [r for r in ok if r.get("judge_error")]
    if jerr:
        print(f"\n  \033[33m{len(jerr)} row(s) extracted fine but the judge failed: "
              f"{jerr[0]['judge_error'][:90]}\033[0m")
    judged = [r for r in ok if r.get("judge")]
    if judged:
        print(f"\n  \033[1mJUDGED\033[0m by {JUDGE_MODEL.split('.')[-1]} "
              f"— estimate, not ground truth")
        tf = sum(1 for r in judged if r["judge"]["topic_faithful"])
        ur = sum(1 for r in judged if r["judge"]["urgency_reasonable"])
        print(f"    topic faithful          {tf}/{len(judged)} = {tf/len(judged):.1%}")
        print(f"    urgency reasonable      {ur}/{len(judged)} = {ur/len(judged):.1%}")
        v = Counter(r["judge"]["sku_verdict"] for r in judged)
        print(f"    SKU verdicts:")
        for k in ("correct", "correct_refusal", "missed", "wrong"):
            c = v.get(k, 0)
            colour = "\033[31m" if k == "wrong" and c else ""
            print(f"      {colour}{k:18} {c:4}  {c/len(judged):.1%}\033[0m")
        good = v.get("correct", 0) + v.get("correct_refusal", 0)
        print(f"    SKU decision correct    {good}/{len(judged)} = {good/len(judged):.1%}"
              f"   (correct + correct_refusal)")
        print("\n    sample 'wrong' verdicts:")
        for r in [r for r in judged if r["judge"]["sku_verdict"] == "wrong"][:4]:
            print(f"      {r['text'][:58]}")
            print(f"        -> {[m['sku'] for m in r['matches']]}  {r['judge']['note'][:70]}")

    print(f"\n  spend ${spend.usd:.4f} / ${spend.cap:.2f} cap  ·  {spend.calls} judge calls")
    print(f"  detail written to {out_path}")


if __name__ == "__main__":
    raise SystemExit(main())
