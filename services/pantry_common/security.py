"""Fail-closed bearer validation and a separate internal service credential.

Service credentials authorize infrastructure calls, never human decisions.
The deployment is a single charity workspace; roles are not tenant isolation.
"""
import hmac
import os
from pathlib import Path
from dotenv import load_dotenv

import jwt
from fastapi import Depends, Header, HTTPException

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def signing_secret() -> str:
    secret = os.getenv("AUTH_JWT_SECRET", "")
    if len(secret) < 32 or secret == "dev-only-change-me":
        raise RuntimeError("Set AUTH_JWT_SECRET to a random secret of at least 32 characters")
    return secret


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, signing_secret(), algorithms=["HS256"],
                          options={"require": ["sub", "exp", "iat", "role"]})
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "invalid or expired token") from exc
    except RuntimeError as exc:
        raise HTTPException(503, "authentication is not configured") from exc


def current_user(authorization: str | None = Header(None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    return decode_token(authorization.split(" ", 1)[1])


def require_charity(user: dict = Depends(current_user)) -> dict:
    if user.get("role") != "charity":
        raise HTTPException(403, "this action is for charity accounts only")
    return user


def require_operator(authorization: str | None = Header(None),
                     x_service_token: str | None = Header(None)) -> dict:
    expected = os.getenv("SERVICE_AUTH_TOKEN", "")
    if x_service_token and len(expected) >= 32 and hmac.compare_digest(x_service_token, expected):
        return {"sub": "internal-service", "role": "service"}
    return require_charity(current_user(authorization))


def service_headers() -> dict[str, str]:
    token = os.getenv("SERVICE_AUTH_TOKEN", "")
    return {"X-Service-Token": token} if token else {}
