#!/usr/bin/env python
"""Load a committed corpus split into the running feedback service.

    python scripts/load_corpus.py --file eval/test.json --limit 150

Posts rows to /feedback at 127.0.0.1 (not localhost -- Windows resolves that
to IPv6 first and the connection attempt times out before falling back to
IPv4, see AUDIT.md). Extraction runs as a FastAPI BackgroundTask per request,
so posting rows unboundedly-fast would queue that many concurrent Bedrock
calls and throttle -- this posts in small batches with a delay between them,
at a bounded concurrency within each batch.

--limit has a default specifically so this can never be run unbounded by
omitting a flag. Ctrl-C prints how many rows were actually submitted before
exiting, rather than a bare traceback.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "http://127.0.0.1:8002"
BATCH_DELAY_S = 1.0


def _post(row: dict) -> tuple[bool, str]:
    payload = json.dumps({
        "beneficiary_id": row["beneficiary_id"],
        "text": row["text"],
        "lang": row.get("lang"),
        "channel": row.get("channel", "web"),
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/feedback", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
            return True, row["beneficiary_id"]
    except urllib.error.HTTPError as e:
        return False, f"{row['beneficiary_id']}: HTTP {e.code}"
    except urllib.error.URLError as e:
        return False, f"{row['beneficiary_id']}: {e.reason}"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="path to a corpus JSON file")
    ap.add_argument("--limit", type=int, default=100,
                     help="max rows to load (default 100, never unbounded)")
    ap.add_argument("--concurrency", type=int, default=4,
                     help="POSTs in flight at once within a batch (default 4)")
    ap.add_argument("--dry-run", action="store_true",
                     help="validate and count only, POST nothing")
    args = ap.parse_args()

    if args.limit <= 0:
        print("--limit must be a positive integer -- refusing an unbounded load")
        return 1

    rows = json.loads(Path(args.file).read_text(encoding="utf-8"))
    rows = rows[: args.limit]
    print(f"loaded {len(rows)} rows from {args.file} (limit={args.limit})")

    if args.dry_run:
        print("--dry-run: not posting anything")
        for r in rows[:5]:
            print(f"  would POST: {r['beneficiary_id']!r} lang={r.get('lang')!r} "
                  f"text={r['text'][:60]!r}")
        if len(rows) > 5:
            print(f"  ... and {len(rows) - 5} more")
        return 0

    submitted, failed = 0, []
    try:
        for i in range(0, len(rows), args.concurrency):
            batch = rows[i : i + args.concurrency]
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                results = list(pool.map(_post, batch))
            for ok, detail in results:
                if ok:
                    submitted += 1
                else:
                    failed.append(detail)
            print(f"\rsubmitted {submitted}/{len(rows)} ({len(failed)} failed)", end="", flush=True)
            if i + args.concurrency < len(rows):
                time.sleep(BATCH_DELAY_S)
    except KeyboardInterrupt:
        print(f"\ninterrupted -- {submitted}/{len(rows)} rows submitted before stopping")
        return 130

    print(f"\ndone: {submitted} submitted, {len(failed)} failed")
    if failed:
        print("failures:")
        for f in failed[:20]:
            print(f"  {f}")
        if len(failed) > 20:
            print(f"  ... and {len(failed) - 20} more")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
