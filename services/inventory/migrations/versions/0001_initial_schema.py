"""Create the Inventory Service schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vendors",
        sa.Column("vendor_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("moq_units", sa.Integer(), nullable=False),
        sa.Column("lead_time_days", sa.Integer(), nullable=False),
        sa.Column("reliability", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.CheckConstraint(
            "lead_time_days >= 0",
            name=op.f("ck_vendors_lead_time_days_nonnegative"),
        ),
        sa.CheckConstraint("moq_units > 0", name=op.f("ck_vendors_moq_units_positive")),
        sa.CheckConstraint(
            "reliability >= 0 AND reliability <= 1",
            name=op.f("ck_vendors_reliability_between_zero_and_one"),
        ),
        sa.PrimaryKeyConstraint("vendor_id", name=op.f("pk_vendors")),
        sa.UniqueConstraint("name", name=op.f("uq_vendors_name")),
    )

    op.create_table(
        "items",
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("on_hand", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("reorder_point", sa.Integer(), nullable=False),
        sa.Column("avg_daily_draw", sa.Integer(), nullable=False),
        sa.Column("unit_cost_sgd", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("preferred_vendor_id", sa.String(length=64), nullable=True),
        sa.Column("dspi_series", sa.String(length=255), nullable=True),
        sa.CheckConstraint(
            "avg_daily_draw >= 0",
            name=op.f("ck_items_avg_daily_draw_nonnegative"),
        ),
        sa.CheckConstraint("on_hand >= 0", name=op.f("ck_items_on_hand_nonnegative")),
        sa.CheckConstraint(
            "reorder_point >= 0",
            name=op.f("ck_items_reorder_point_nonnegative"),
        ),
        sa.CheckConstraint(
            "unit_cost_sgd >= 0",
            name=op.f("ck_items_unit_cost_sgd_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["preferred_vendor_id"],
            ["vendors.vendor_id"],
            name=op.f("fk_items_preferred_vendor_id_vendors"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("sku", name=op.f("pk_items")),
    )
    op.create_index("ix_items_category", "items", ["category"], unique=False)
    op.create_index(
        "ix_items_preferred_vendor_id",
        "items",
        ["preferred_vendor_id"],
        unique=False,
    )

    op.create_table(
        "lots",
        sa.Column("lot_id", sa.String(length=64), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum(
                "PURCHASED",
                "DONATED",
                name="lot_source",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.CheckConstraint("qty >= 0", name=op.f("ck_lots_qty_nonnegative")),
        sa.ForeignKeyConstraint(
            ["sku"],
            ["items.sku"],
            name=op.f("fk_lots_sku_items"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("lot_id", name=op.f("pk_lots")),
    )
    op.create_index(
        "ix_lots_sku_expiry_date",
        "lots",
        ["sku", "expiry_date"],
        unique=False,
    )

    op.create_table(
        "orders",
        sa.Column("order_id", sa.String(length=64), nullable=False),
        sa.Column("vendor_id", sa.String(length=64), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PLACED",
                "FULFILLED",
                "CANCELLED",
                name="order_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'PLACED'"),
            nullable=False,
        ),
        sa.Column("unit_price_sgd", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "placed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expected_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "expected_at >= placed_at",
            name=op.f("ck_orders_expected_not_before_placed"),
        ),
        sa.CheckConstraint("qty > 0", name=op.f("ck_orders_qty_positive")),
        sa.CheckConstraint(
            "unit_price_sgd >= 0",
            name=op.f("ck_orders_unit_price_sgd_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["sku"],
            ["items.sku"],
            name=op.f("fk_orders_sku_items"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vendor_id"],
            ["vendors.vendor_id"],
            name=op.f("fk_orders_vendor_id_vendors"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("order_id", name=op.f("pk_orders")),
    )
    op.create_index(
        "ix_orders_sku_status",
        "orders",
        ["sku", "status"],
        unique=False,
    )
    op.create_index(
        "ix_orders_vendor_id_status",
        "orders",
        ["vendor_id", "status"],
        unique=False,
    )

    op.create_table(
        "vendor_offers",
        sa.Column("vendor_id", sa.String(length=64), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column(
            "available_qty",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "price_multiplier",
            sa.Numeric(precision=8, scale=4),
            server_default=sa.text("1.0000"),
            nullable=False,
        ),
        sa.Column("bulk_discount_threshold", sa.Integer(), nullable=True),
        sa.Column(
            "bulk_discount_rate",
            sa.Numeric(precision=5, scale=4),
            server_default=sa.text("0.0000"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "available_qty >= 0",
            name=op.f("ck_vendor_offers_available_qty_nonnegative"),
        ),
        sa.CheckConstraint(
            "bulk_discount_rate >= 0 AND bulk_discount_rate < 1",
            name=op.f("ck_vendor_offers_bulk_discount_rate_valid"),
        ),
        sa.CheckConstraint(
            "bulk_discount_threshold IS NULL OR bulk_discount_threshold > 0",
            name=op.f("ck_vendor_offers_bulk_discount_threshold_positive"),
        ),
        sa.CheckConstraint(
            "price_multiplier > 0",
            name=op.f("ck_vendor_offers_price_multiplier_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["sku"],
            ["items.sku"],
            name=op.f("fk_vendor_offers_sku_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["vendor_id"],
            ["vendors.vendor_id"],
            name=op.f("fk_vendor_offers_vendor_id_vendors"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("vendor_id", "sku", name=op.f("pk_vendor_offers")),
    )
    op.create_index(
        "ix_vendor_offers_sku_available_qty",
        "vendor_offers",
        ["sku", "available_qty"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_vendor_offers_sku_available_qty", table_name="vendor_offers")
    op.drop_table("vendor_offers")
    op.drop_index("ix_orders_vendor_id_status", table_name="orders")
    op.drop_index("ix_orders_sku_status", table_name="orders")
    op.drop_table("orders")
    op.drop_index("ix_lots_sku_expiry_date", table_name="lots")
    op.drop_table("lots")
    op.drop_index("ix_items_preferred_vendor_id", table_name="items")
    op.drop_index("ix_items_category", table_name="items")
    op.drop_table("items")
    op.drop_table("vendors")
