#!/usr/bin/env python
"""Partition the feedback corpus into train / test for extraction evaluation.

    python scripts/split_corpus.py

90/10, stratified by `lang` so the 10% test set keeps the corpus's language mix
(en/zh/ms/ta/null) rather than drifting English-heavy by luck. Deterministic
seed, so the split is reproducible and the test set is never silently reshuffled
between runs.

Rows with empty text are pulled into a separate `robustness` bucket: there is
nothing to extract from "" so scoring them as extraction failures would be
misleading, but the API must still not crash on them.

NOTE ON "TRAIN": Claude cannot be fine-tuned on Bedrock — every Claude model on
this account reports customizationsSupported=<none>, and only Amazon Nova/Titan
support FINE_TUNING (which would additionally require Provisioned Throughput to
serve). The train split is therefore a PROMPT-DEVELOPMENT set: mine it for
failure modes and few-shot examples. It is not training data for a weight update.
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SEED_FILE = HERE / "seed" / "feedback_seed.json"
OUT = HERE / "eval"
SEED = 20260907
TEST_FRAC = 0.10


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-frac", type=float, default=TEST_FRAC)
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()

    rows = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    usable, robustness = [], []
    for r in rows:
        (usable if (r.get("text") or "").strip() else robustness).append(r)

    by_lang: dict[str, list] = defaultdict(list)
    for r in usable:
        by_lang[r.get("lang") or "null"].append(r)

    rng = random.Random(args.seed)
    train, test = [], []
    for lang, group in sorted(by_lang.items()):
        rng.shuffle(group)
        k = max(1, round(len(group) * args.test_frac))
        test += group[:k]
        train += group[k:]
    rng.shuffle(train)
    rng.shuffle(test)

    OUT.mkdir(exist_ok=True)
    for name, part in (("train", train), ("test", test), ("robustness", robustness)):
        (OUT / f"{name}.json").write_text(
            json.dumps(part, ensure_ascii=False, indent=2), encoding="utf-8")

    def mix(part):
        c = defaultdict(int)
        for r in part:
            c[r.get("lang") or "null"] += 1
        return dict(sorted(c.items()))

    print(f"  corpus      {len(rows):5}  ({len(usable)} usable, {len(robustness)} empty-text)")
    print(f"  train       {len(train):5}  {mix(train)}")
    print(f"  test        {len(test):5}  {mix(test)}")
    print(f"  robustness  {len(robustness):5}  (empty text — API must not crash)")
    ids = {r["beneficiary_id"] for r in train} & {r["beneficiary_id"] for r in test}
    assert not ids, f"train/test overlap: {ids}"
    print(f"\n  no overlap between splits; seed={args.seed}, written to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
