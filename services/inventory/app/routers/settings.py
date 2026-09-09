"""User-editable procurement settings -- currently just the monthly budget.

`GET /settings` is unauthenticated (read-only, and other services -- the
orchestrator's guardrail display -- need it too). `PATCH /settings` requires
a charity account: this changes what the agent is allowed to spend, so it
gets the same server-side fence as anything else that moves money.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pantry_common.security import require_charity
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Settings

router = APIRouter(tags=["settings"])
DatabaseSession = Annotated[Session, Depends(get_db)]


class SettingsResponse(BaseModel):
    monthly_budget_sgd: Decimal
    updated_at: datetime
    updated_by: str | None = None


class SettingsUpdate(BaseModel):
    # Upper bound is a sanity rail, not a business rule -- catches a stray
    # extra zero in the input before it becomes "the agent may now spend
    # 5 million dollars a month" with no further confirmation anywhere.
    monthly_budget_sgd: Decimal = Field(gt=0, le=1_000_000)


def _get_or_seed(db: Session) -> Settings:
    row = db.get(Settings, 1)
    if row is None:
        # Should only happen if a deployment skipped the migration's seed
        # insert -- self-heals rather than 500ing on every read.
        row = Settings(id=1, monthly_budget_sgd=Decimal("5000"),
                       updated_at=datetime.now(timezone.utc))
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


@router.get("/settings", response_model=SettingsResponse)
def get_settings(db: DatabaseSession) -> Settings:
    return _get_or_seed(db)


@router.patch("/settings", response_model=SettingsResponse)
def update_settings(payload: SettingsUpdate, db: DatabaseSession,
                    user: dict = Depends(require_charity)) -> Settings:
    row = _get_or_seed(db)
    row.monthly_budget_sgd = payload.monthly_budget_sgd
    row.updated_at = datetime.now(timezone.utc)
    row.updated_by = user.get("email")
    db.commit()
    db.refresh(row)
    return row
