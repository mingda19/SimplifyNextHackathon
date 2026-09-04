"""Load the seed corpus into feedback.feedback_entries.

Run once on day 1 (see README timeline) so extraction has already happened
and is sitting in Postgres before the demo -- the demo itself never depends
on a live LLM call.

    python -m seed.load_seed                # insert raw rows only
    python -m seed.load_seed --with-extraction   # also run extraction now

Requires DATABASE_URL in the repo-root .env. --with-extraction also needs
FAKE_LLM=0 and a live AWS SSO session (`make aws-login`) -- with FAKE_LLM=1
(the default) every row gets the same canned extraction, which is fine for
wiring/DB checks but not for validating extraction quality. Safe to re-run:
skips beneficiary_ids already present.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from app import db
from app.main import extract_and_store

logger = logging.getLogger("feedback.seed")
logging.basicConfig(level=logging.INFO)

SEED_FILE = Path(__file__).parent / "feedback_seed.json"


def load(with_extraction: bool) -> None:
    db.init_pool()
    entries = json.loads(SEED_FILE.read_text(encoding="utf-8"))

    inserted = 0
    with db.get_cursor() as cur:
        cur.execute("SELECT beneficiary_id FROM feedback.feedback_entries")
        already = {row["beneficiary_id"] for row in cur.fetchall()}

    for entry in entries:
        if entry["beneficiary_id"] in already:
            logger.info("skipping %s, already loaded", entry["beneficiary_id"])
            continue

        with db.get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO feedback.feedback_entries (beneficiary_id, text, lang, channel)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (entry["beneficiary_id"], entry["text"], entry["lang"], entry["channel"]),
            )
            feedback_id = cur.fetchone()["id"]
        inserted += 1

        if with_extraction:
            logger.info("extracting %s (feedback_id=%s)", entry["beneficiary_id"], feedback_id)
            extract_and_store(feedback_id, entry["text"], entry["lang"])

    logger.info("done: %d new rows inserted (%d already present)", inserted, len(already))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-extraction", action="store_true")
    args = parser.parse_args()
    load(with_extraction=args.with_extraction)
