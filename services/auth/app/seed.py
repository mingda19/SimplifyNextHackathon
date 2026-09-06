"""Idempotently seed the default charity account for the local demo."""

from __future__ import annotations

import os

from app import db
from app.security import hash_password

DEFAULT_EMAIL = "Example@gmail.com"
DEFAULT_PASSWORD = "Example123"
DEFAULT_DISPLAY_NAME = "Example"


def seed_default_user() -> bool:
    """Create the default charity account if it does not already exist.

    The values can be overridden for local deployments with environment
    variables. Existing accounts are never modified.
    """
    email = os.getenv("SEED_USER_EMAIL", DEFAULT_EMAIL).strip().lower()
    password = os.getenv("SEED_USER_PASSWORD", DEFAULT_PASSWORD)
    display_name = os.getenv("SEED_USER_ORG_NAME", DEFAULT_DISPLAY_NAME).strip()

    with db.get_cursor() as cur:
        cur.execute(
            "SELECT 1 FROM auth.users WHERE lower(email) = lower(%s)",
            (email,),
        )
        if cur.fetchone():
            return False

        cur.execute(
            """INSERT INTO auth.users
                   (email, password_hash, role, display_name)
               VALUES (%s, %s, 'charity', %s)""",
            (email, hash_password(password), display_name),
        )
    return True


def main() -> int:
    created = seed_default_user()
    print(
        f"Default auth user {'created' if created else 'already exists'}: "
        f"{os.getenv('SEED_USER_EMAIL', DEFAULT_EMAIL).strip().lower()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["seed_default_user", "main"]
