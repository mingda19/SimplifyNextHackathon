#!/usr/bin/env python
"""Load a committed corpus split into the running feedback service.

    python scripts/load_corpus.py --file eval/test.json --limit 150

Posts rows to /feedback at 127.0.0.1 (not localhost -- Windows resolves that
to IPv6 first and the connection attempt times out before falling back to
IPv4, see AUDIT.md).

Extraction runs as a FastAPI BackgroundTask per request, which fires
IMMEDIATELY when each request returns -- it does not queue or respect any
client-side POST pacing. A first version of this script rate-limited only
the POSTs (4 at a time, 1s between batches) and still triggered heavy
Bedrock 429 throttling, because all ~150 background extractions ended up
racing each other regardless of how gently they were submitted (confirmed:
63/151 failed with "Too many requests" on that run). Real bounded
concurrency requires waiting for a batch's extractions to actually finish
(polling /metrics' extraction_pending back to 0) before posting the next
batch -- not just pacing the POSTs themselves.

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
POLL_INTERVAL_S = 1.0


def _pending_count() -> int:
    req = urllib.request.Request(f"{BASE_URL}/metrics", method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())["extraction_pending"]


def _wait_for_drain(timeout_s: float) -> bool:
    """Block until extraction_pending reaches 0. Returns False on timeout."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _pending_count() == 0:
            return True
        time.sleep(POLL_INTERVAL_S)
    return False


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

    drain_timeout_s = max(30.0, args.concurrency * 15.0)
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
            print(f"\rsubmitted {submitted}/{len(rows)} ({len(failed)} failed), draining...", end="", flush=True)
            if not _wait_for_drain(drain_timeout_s):
                print(f"\nWARNING: batch at row {i} did not drain within {drain_timeout_s:.0f}s "
                      "-- continuing anyway, but this batch may still be extracting")
            print(f"\rsubmitted {submitted}/{len(rows)} ({len(failed)} failed)            ", end="", flush=True)
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
