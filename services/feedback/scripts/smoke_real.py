"""WS2 Phase 2 Part B: end-to-end smoke test against a running feedback service.

POSTs 5 seed entries (English, Singlish, Mandarin, Malay, one that should
resolve to no SKU), polls GET /feedback until each reaches a terminal
extraction_status, and reports per entry: raw text, parsed extraction,
matched SKUs, which matcher layer resolved each term, and latency.

Meaningful language-specific verification requires FAKE_LLM=0 (a real
Bedrock call) -- under FAKE_LLM=1 every entry gets the same canned
extraction regardless of input text, so this only proves the DB/API wiring
handles concurrent submissions across different raw-text payloads, not that
extraction quality is correct per language. Run with FAKE_LLM=0 once AWS SSO
is set up to get the real signal this script is for.

Usage (from services/feedback/):
    .venv/Scripts/python.exe scripts/smoke_real.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

import psycopg2
import psycopg2.extras

BASE_URL = os.environ.get("FEEDBACK_URL", "http://127.0.0.1:8002")
# "localhost" resolves to IPv6 first on Windows and falls back to IPv4 only
# after that connection attempt times out (~2s/request, confirmed empirically
# on this machine) -- 127.0.0.1 skips that. Anyone overriding FEEDBACK_URL
# with "localhost" will see inflated, misleading latency numbers.
POLL_INTERVAL_S = 0.5
POLL_TIMEOUT_S = 20.0

SEED_ENTRIES = [
    ("English", "I need rice and cooking oil for my family, running low"),
    ("Singlish", "aiyo no more milk powder for baby leh, can help or not"),
    ("Mandarin", "我需要大米和鸡蛋，家里没有了"),
    ("Malay", "saya perlukan beras dan ayam untuk keluarga saya"),
    ("no matching SKU", "does anyone have a spare birthday cake for my kid's party"),
]


def _post_feedback(text: str) -> int:
    payload = json.dumps({"beneficiary_id": "smoke-test", "text": text, "lang": None}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/feedback",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read())
        return body["id"]


def _get_entry(feedback_id: int) -> dict | None:
    req = urllib.request.Request(f"{BASE_URL}/feedback", method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        rows = json.loads(resp.read())
    for row in rows:
        if row["id"] == feedback_id:
            return row
    return None


def _sku_match_layers(conn, feedback_id: int) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT term, matched_sku, method, near_sku, unmet_qualifier "
            "FROM feedback.sku_matches WHERE feedback_id = %s ORDER BY id",
            (feedback_id,),
        )
        return cur.fetchall()


@dataclass
class Result:
    label: str
    feedback_id: int
    status: str
    latency_ms: float | None
    entry: dict | None
    matches: list[dict]


def run() -> list[Result]:
    database_url = os.environ.get(
        "DATABASE_URL", "postgresql://simplifynext:simplifynext@localhost:5432/simplifynext"
    )
    conn = psycopg2.connect(database_url.replace("postgresql+psycopg://", "postgresql://"))

    results: list[Result] = []
    started = {}
    for label, text in SEED_ENTRIES:
        t0 = time.monotonic()
        try:
            fid = _post_feedback(text)
        except urllib.error.URLError as e:
            print(f"[{label}] POST FAILED: {e}")
            continue
        started[fid] = (label, t0)

    for fid, (label, t0) in started.items():
        deadline = time.monotonic() + POLL_TIMEOUT_S
        entry = None
        while time.monotonic() < deadline:
            entry = _get_entry(fid)
            if entry and entry["extraction_status"] in ("done", "failed"):
                break
            time.sleep(POLL_INTERVAL_S)
        latency_ms = (time.monotonic() - t0) * 1000 if entry else None
        matches = _sku_match_layers(conn, fid) if entry else []
        results.append(Result(label, fid, entry["extraction_status"] if entry else "timeout", latency_ms, entry, matches))

    conn.close()
    return results


def main() -> int:
    # Beneficiary text is Mandarin/Tamil/etc -- a narrow-codepage Windows
    # console (the default outside Windows Terminal's UTF-8 mode) otherwise
    # crashes on the first non-ASCII print, same failure mode checked (and
    # found already-handled for *logging*, not *printing*) in Phase 1's
    # Loop B -- print() has no such built-in protection, so this script
    # needs its own.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

    fake_llm = os.environ.get("FAKE_LLM", "1")
    if fake_llm not in ("0", "false", "False"):
        print(
            "WARNING: FAKE_LLM is not disabled -- every entry will get the same "
            "canned extraction regardless of language. This only exercises the "
            "DB/API wiring, not real per-language extraction quality.\n"
        )

    results = run()
    all_done = True
    for r in results:
        print(f"=== {r.label} (feedback_id={r.feedback_id}) ===")
        print(f"  status: {r.status}   latency: {r.latency_ms:.0f}ms" if r.latency_ms else f"  status: {r.status}")
        if r.entry:
            print(f"  raw text: {r.entry['text']!r}")
            print(f"  detected_lang: {r.entry['detected_lang']}")
            print(f"  sentiment: {r.entry['sentiment']}  urgency: {r.entry['urgency']}")
            print(f"  mentioned_terms: {r.entry['mentioned_terms']}")
            print(f"  mentioned_skus (resolved): {r.entry['mentioned_skus']}")
            print(f"  unmet_needs: {r.entry['unmet_needs']}")
        for m in r.matches:
            print(
                f"  match layer: term={m['term']!r} -> matched_sku={m['matched_sku']} "
                f"method={m['method']} near_sku={m['near_sku']} unmet_qualifier={m['unmet_qualifier']}"
            )
        if r.status != "done":
            all_done = False
        print()

    if not all_done:
        print("FAILED: not every entry reached extraction_status='done'")
        return 1
    print("OK: all entries reached extraction_status='done'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
