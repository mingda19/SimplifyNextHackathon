"""WS2 Phase 2 Part C: adversarial input pass against a running feedback service.

Each case POSTs something hostile and asserts the stated expectation. Run
against a live service (docker compose up postgres; uvicorn app.main:app).

Usage (from services/feedback/):
    .venv/Scripts/python.exe scripts/adversarial.py
"""

from __future__ import annotations

import concurrent.futures
import json
import sys
import time
import urllib.error
import urllib.request

BASE_URL = "http://127.0.0.1:8002"  # see smoke_real.py comment re: localhost on Windows
POLL_INTERVAL_S = 0.3
POLL_TIMEOUT_S = 15.0


class Failed(Exception):
    pass


def _post(text: str, beneficiary_id: str = "adversarial") -> tuple[int, dict]:
    payload = json.dumps({"beneficiary_id": beneficiary_id, "text": text, "lang": None}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/feedback",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _get_all() -> list[dict]:
    with urllib.request.urlopen(f"{BASE_URL}/feedback", timeout=10) as resp:
        return json.loads(resp.read())


def _wait_for_terminal(feedback_id: int) -> dict | None:
    deadline = time.monotonic() + POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        rows = _get_all()
        for row in rows:
            if row["id"] == feedback_id and row["extraction_status"] in ("done", "failed"):
                return row
        time.sleep(POLL_INTERVAL_S)
    return None


def case_empty_string():
    status, body = _post("")
    if status >= 500:
        raise Failed(f"empty string caused a {status}, expected 202 or 4xx, never 5xx")
    if status == 202:
        row = _wait_for_terminal(body["id"])
        if row is None:
            raise Failed("empty string: never reached a terminal extraction_status")
    print(f"  empty string -> HTTP {status} (no crash)")


def case_huge_input():
    text = "rice " * 2000  # ~10,000 chars
    status, body = _post(text)
    if status >= 500:
        raise Failed(f"10,000-char input caused a {status}")
    status_label = "n/a"
    if status == 202:
        row = _wait_for_terminal(body["id"])
        if row is None:
            raise Failed("10,000-char input: never reached a terminal extraction_status")
        if row["extraction_status"] != "done":
            raise Failed(f"10,000-char input ended in {row['extraction_status']!r}, not 'done'")
        status_label = row["extraction_status"]
    print(f"  10,000 chars -> HTTP {status}, extraction_status={status_label}")


def case_emoji_only():
    status, body = _post("🍚🥚🥛😢")
    if status >= 500:
        raise Failed(f"emoji-only input caused a {status}")
    row = _wait_for_terminal(body["id"]) if status == 202 else None
    if row is None:
        raise Failed("emoji-only input: never reached a terminal extraction_status")
    if row["extraction_status"] != "done":
        raise Failed(f"emoji-only input ended in {row['extraction_status']!r}, not 'done'")
    print(f"  emoji only -> HTTP {status}, extraction_status=done, row stored")


def case_sql_literal():
    injection = "'; DROP TABLE feedback.feedback_entries; --"
    status, body = _post(injection)
    if status >= 500:
        raise Failed(f"SQL-injection-shaped text caused a {status}")
    row = _wait_for_terminal(body["id"]) if status == 202 else None
    if row is None:
        raise Failed("SQL-injection-shaped text: never reached a terminal extraction_status")
    if row["text"] != injection:
        raise Failed(f"stored text was mutated: {row['text']!r} != {injection!r}")
    # If the table had actually been dropped, this next call would 500.
    rows_after = _get_all()
    if not any(r["id"] == body["id"] for r in rows_after):
        raise Failed("row disappeared after the 'injection' -- table may have been affected")
    print(f"  SQL-injection-shaped text -> stored as literal text, table intact ({len(rows_after)} rows readable)")


def case_duplicate_rapid():
    text = "duplicate rapid submission test rice please"
    status1, body1 = _post(text)
    status2, body2 = _post(text)
    if status1 >= 500 or status2 >= 500:
        raise Failed(f"rapid duplicate submission caused a 5xx ({status1}, {status2})")
    if body1["id"] == body2["id"]:
        raise Failed("rapid duplicate submissions collapsed into one row -- expected two independent rows")
    print(f"  rapid duplicate submission -> two independent rows (ids {body1['id']}, {body2['id']}), no crash")


def case_concurrent_posts():
    texts = [f"concurrent post #{i} rice please" for i in range(5)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(_post, texts))
    statuses = [r[0] for r in results]
    if any(s >= 500 for s in statuses):
        raise Failed(f"concurrent POSTs caused a 5xx: {statuses}")
    ids = [r[1]["id"] for r in results]
    if len(set(ids)) != len(ids):
        raise Failed(f"concurrent POSTs did not get distinct ids: {ids}")
    terminal_rows = [_wait_for_terminal(i) for i in ids]
    if any(r is None for r in terminal_rows):
        raise Failed("at least one concurrent POST never reached a terminal extraction_status")
    not_done = [r["id"] for r in terminal_rows if r["extraction_status"] != "done"]
    if not_done:
        raise Failed(f"concurrent POSTs {not_done} did not reach extraction_status='done'")
    print(f"  5 concurrent POSTs -> all {len(ids)} completed with distinct ids, all reached 'done'")


def case_bad_enum_in_fixture():
    # This exercises the closed-vocabulary guarantee (Extraction's Literal
    # fields), not the live retry-against-Bedrock path -- that needs a real
    # Bedrock call returning a bad enum, which FAKE_LLM=1 never produces
    # (FAKE_EXTRACTION is a pre-validated Extraction instance constructed at
    # import time). Documented here rather than silently skipped.
    sys.path.insert(0, ".")
    from pydantic import ValidationError

    from app.extract import Extraction

    try:
        Extraction(
            sentiment="angry",  # not in SENTIMENT_VOCAB
            urgency=3,
            categories=["staples"],
            mentioned_skus=[],
            mentioned_terms=["rice"],
            unmet_needs=[],
            detected_lang="en",
            summary_en="test",
        )
        raise Failed("Extraction accepted sentiment='angry' -- closed vocabulary is not enforced")
    except ValidationError:
        pass
    print(
        "  bad enum ('angry') rejected by Extraction's Pydantic schema at construction time "
        "(closed-vocabulary guarantee holds; live LLM-retry path itself needs FAKE_LLM=0 to test)"
    )


CASES = [
    ("empty string", case_empty_string),
    ("10,000 characters", case_huge_input),
    ("emoji only", case_emoji_only),
    ("SQL-injection-shaped text", case_sql_literal),
    ("same entry twice, rapidly", case_duplicate_rapid),
    ("two POSTs simultaneously", case_concurrent_posts),
    ("bad enum in fixture", case_bad_enum_in_fixture),
]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

    failures = []
    for label, fn in CASES:
        print(f"=== {label} ===")
        try:
            fn()
        except Failed as e:
            print(f"  FAILED: {e}")
            failures.append(label)
        except Exception as e:  # noqa: BLE001 -- adversarial harness, catch-all is the point
            print(f"  FAILED (unexpected exception): {type(e).__name__}: {e}")
            failures.append(label)
        print()

    if failures:
        print(f"FAILED: {len(failures)}/{len(CASES)} cases: {failures}")
        return 1
    print(f"OK: all {len(CASES)} adversarial cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
