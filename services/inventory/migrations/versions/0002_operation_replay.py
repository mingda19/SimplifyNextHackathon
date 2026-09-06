"""Durable idempotency results for inventory mutations."""
from alembic import op
import sqlalchemy as sa

revision = "0002_operation_replay"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("operations",
        sa.Column("key", sa.String(200), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False))


def downgrade():
    op.drop_table("operations")
