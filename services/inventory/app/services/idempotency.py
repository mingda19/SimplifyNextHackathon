"""Database-backed idempotency for ambiguous network responses and restarts."""
import hashlib
import json

from sqlalchemy import text

from app.errors import DomainError
from app.models import Operation


def conflict(code: str, message: str) -> DomainError:
    return DomainError(status_code=409, code=code, message=message,
                       remedy_hint="Review the current state and submit a new approved request.",
                       alternatives=[{"action": "review"}])


def lock(db, key: str) -> None:
    if db.get_bind().dialect.name == "postgresql":
        number = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big", signed=True)
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": number})


def replay(db, key: str | None, request: dict) -> dict | None:
    if not key:
        return None
    lock(db, "idempotency:" + key)
    previous = db.get(Operation, key)
    if previous:
        if previous.request_hash != fingerprint(request):
            raise conflict("IDEMPOTENCY_CONFLICT", "This idempotency key was used for a different request.")
        return previous.result
    return None


def fingerprint(request: dict) -> str:
    return hashlib.sha256(json.dumps(request, sort_keys=True, default=str).encode()).hexdigest()


def record(db, key: str | None, request: dict, result: dict) -> None:
    if key:
        db.add(Operation(key=key, request_hash=fingerprint(request), result=result))
