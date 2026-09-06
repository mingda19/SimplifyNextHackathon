"""Password hashing, policy, and JWT issuing.

Hashing is stdlib pbkdf2_hmac rather than bcrypt: no wheel to build (this repo
already lost time to Python 3.13 build failures), 480k iterations, per-user
salt. Format: pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from pantry_common.security import decode_token, signing_secret
from fastapi import HTTPException

ITERATIONS = 480_000
ALGO = "pbkdf2_sha256"

JWT_ALGO = "HS256"
TOKEN_TTL_HOURS = int(os.getenv("AUTH_TOKEN_TTL_HOURS", "12"))

# Deliberately stated as rules a human can read back, because the signup screen
# shows them live and the wording must match exactly what is enforced here.
PASSWORD_RULES = [
    ("at least 10 characters", lambda p: len(p) >= 10),
    ("an uppercase letter", lambda p: bool(re.search(r"[A-Z]", p))),
    ("a lowercase letter", lambda p: bool(re.search(r"[a-z]", p))),
    ("a number", lambda p: bool(re.search(r"\d", p))),
]
COMMON = {"password", "password123", "12345678", "qwertyuiop", "letmein123",
          "charity123", "admin12345"}


def password_problems(password: str) -> list[str]:
    """Empty list means acceptable. Returned verbatim to the client."""
    problems = [label for label, ok in PASSWORD_RULES if not ok(password)]
    if password.lower() in COMMON:
        problems.append("something less guessable — that password is very common")
    return problems


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"{ALGO}${ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != ALGO:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                 bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


def make_token(user: dict) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user["id"]),
        "email": user["email"],
        "role": user["role"],
        "name": user["display_name"],
        "beneficiary_id": user.get("beneficiary_id"),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=TOKEN_TTL_HOURS)).timestamp()),
    }
    return jwt.encode(payload, signing_secret(), algorithm=JWT_ALGO)


def read_token(token: str) -> dict | None:
    try:
        return decode_token(token)
    except HTTPException:
        return None
