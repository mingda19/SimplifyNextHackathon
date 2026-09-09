"""User-editable procurement settings.

Revision ID: 0003_settings
Revises: 0002_operation_replay
Create Date: 2026-09-10

Previously `monthly_budget_sgd` was a hardcoded constant in
`pantry_common.baselines.BASELINES`, shared as a plain Python dict across
services with no way to change it short of editing source and redeploying.
This table gives it exactly one durable, user-editable home; the enforcement
check in `app/services/vendors.py` reads from here now, and `BASELINES`
remains only as the seed default / fallback if the row is ever missing.

Singleton by construction (`id` fixed to 1 via CHECK) -- there is one
procurement budget for the whole charity, not one per vendor or per SKU.
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_settings"
down_revision = "0002_operation_replay"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("monthly_budget_sgd", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_by", sa.String(length=200), nullable=True),
        sa.CheckConstraint("id = 1", name=op.f("ck_settings_id_singleton")),
        sa.CheckConstraint("monthly_budget_sgd > 0", name=op.f("ck_settings_monthly_budget_sgd_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_settings")),
    )
    op.execute("INSERT INTO settings (id, monthly_budget_sgd) VALUES (1, 5000)")


def downgrade():
    op.drop_table("settings")
