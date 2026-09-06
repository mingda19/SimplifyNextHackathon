"""Unit tests for password hashing, JWT issuing, and the shared auth
dependencies (`require_charity`, `require_operator`) — no database, no
network. This is the layer the P0 "backend permissions are missing" finding
lived in; `tests/readiness/test_system.py` covers the same behavior again at
the real-HTTP/Postgres level, deliberately overlapping this suite rather than
replacing it.
"""
from __future__ import annotations

import os
import time

import jwt
import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

os.environ.setdefault("AUTH_JWT_SECRET", "unit-test-secret-at-least-32-chars-long")
os.environ.setdefault("SERVICE_AUTH_TOKEN", "unit-test-service-token-at-least-32-chars")

from app import security  # noqa: E402


# ------------------------------------------------------------- passwords ----
def test_password_problems_empty_for_a_compliant_password():
    assert security.password_problems("Correct-Horse9") == []


@pytest.mark.parametrize("password,expected_hint", [
    ("short1A", "at least 10 characters"),
    ("alllowercase1", "an uppercase letter"),
    ("ALLUPPERCASE1", "a lowercase letter"),
    ("NoDigitsHere", "a number"),
    ("Password123", "something less guessable — that password is very common"),
])
def test_password_problems_flags_each_rule(password, expected_hint):
    assert expected_hint in security.password_problems(password)


def test_hash_and_verify_roundtrip():
    stored = security.hash_password("Correct-Horse9")
    assert security.verify_password("Correct-Horse9", stored)
    assert not security.verify_password("wrong-password", stored)


def test_verify_rejects_tampered_or_malformed_hash():
    stored = security.hash_password("Correct-Horse9")
    assert not security.verify_password("Correct-Horse9", stored + "x")
    assert not security.verify_password("Correct-Horse9", "not-a-valid-format")
    assert not security.verify_password("Correct-Horse9", "")


def test_two_hashes_of_the_same_password_differ():
    # Per-user salt: identical passwords must not produce identical hashes.
    assert security.hash_password("Correct-Horse9") != security.hash_password("Correct-Horse9")


# ------------------------------------------------------------------ tokens --
def test_make_token_roundtrips_through_read_token():
    user = {"id": 7, "email": "charity@example.org", "role": "charity",
            "display_name": "Example Charity", "beneficiary_id": None}
    token = security.make_token(user)
    claims = security.read_token(token)
    assert claims["sub"] == "7"
    assert claims["email"] == "charity@example.org"
    assert claims["role"] == "charity"
    assert claims["name"] == "Example Charity"


def test_read_token_returns_none_for_garbage():
    assert security.read_token("not-a-jwt") is None


def test_read_token_returns_none_for_expired_token():
    from pantry_common.security import signing_secret
    now = int(time.time())
    payload = {"sub": "1", "role": "charity", "iat": now - 100, "exp": now - 1}
    expired = jwt.encode(payload, signing_secret(), algorithm="HS256")
    assert security.read_token(expired) is None


def test_read_token_returns_none_for_wrong_signature():
    payload = {"sub": "1", "role": "charity", "iat": int(time.time()),
               "exp": int(time.time()) + 3600}
    forged = jwt.encode(payload, "a-completely-different-secret-value-here", algorithm="HS256")
    assert security.read_token(forged) is None


# --------------------------------------------------------- shared deps ------
def _build_app():
    from pantry_common.security import current_user, require_charity, require_operator

    app = FastAPI()

    @app.get("/whoami")
    def whoami(user: dict = Depends(current_user)):
        return user

    @app.get("/charity-only")
    def charity_only(user: dict = Depends(require_charity)):
        return user

    @app.get("/operator-only")
    def operator_only(user: dict = Depends(require_operator)):
        return user

    return app


@pytest.fixture
def client():
    return TestClient(_build_app())


def _token_for(role: str) -> str:
    user = {"id": 1, "email": "u@example.org", "role": role,
            "display_name": "U", "beneficiary_id": None}
    return security.make_token(user)


def test_missing_bearer_token_is_rejected(client):
    assert client.get("/whoami").status_code == 401


def test_malformed_authorization_header_is_rejected(client):
    r = client.get("/whoami", headers={"Authorization": "NotBearer abc"})
    assert r.status_code == 401


def test_valid_charity_token_is_accepted(client):
    r = client.get("/whoami", headers={"Authorization": f"Bearer {_token_for('charity')}"})
    assert r.status_code == 200
    assert r.json()["role"] == "charity"


def test_require_charity_rejects_recipient_role(client):
    r = client.get("/charity-only", headers={"Authorization": f"Bearer {_token_for('recipient')}"})
    assert r.status_code == 403


def test_require_charity_accepts_charity_role(client):
    r = client.get("/charity-only", headers={"Authorization": f"Bearer {_token_for('charity')}"})
    assert r.status_code == 200


def test_require_operator_accepts_a_human_charity_token(client):
    r = client.get("/operator-only", headers={"Authorization": f"Bearer {_token_for('charity')}"})
    assert r.status_code == 200


def test_require_operator_rejects_a_human_recipient_token(client):
    r = client.get("/operator-only", headers={"Authorization": f"Bearer {_token_for('recipient')}"})
    assert r.status_code == 403


def test_require_operator_accepts_the_service_credential_with_no_bearer_token(client):
    r = client.get("/operator-only", headers={"X-Service-Token": os.environ["SERVICE_AUTH_TOKEN"]})
    assert r.status_code == 200
    assert r.json()["role"] == "service"


def test_require_operator_rejects_a_wrong_service_token(client):
    r = client.get("/operator-only", headers={"X-Service-Token": "not-the-real-token"})
    assert r.status_code == 401


def test_require_operator_rejects_a_short_service_token_even_if_it_matches_a_prefix(client):
    # Guards against a misconfigured, near-empty SERVICE_AUTH_TOKEN being
    # treated as "set" just because the header happens to equal it.
    r = client.get("/operator-only", headers={"X-Service-Token": ""})
    assert r.status_code == 401
