"""SQLAlchemy models for the Inventory Service.

The public schema is intentionally small and mirrors the frozen Workstream 1
contract. ``vendor_offers`` is an internal support table used to model a
vendor's availability and deterministic local pricing inputs; it has no public
CRUD surface.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by the application and Alembic."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class LotSource(str, Enum):
    PURCHASED = "PURCHASED"
    DONATED = "DONATED"


class OrderStatus(str, Enum):
    PLACED = "PLACED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


lot_source_type = SqlEnum(
    LotSource,
    name="lot_source",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=lambda values: [value.value for value in values],
)

order_status_type = SqlEnum(
    OrderStatus,
    name="order_status",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=lambda values: [value.value for value in values],
)


class Vendor(Base):
    __tablename__ = "vendors"
    __table_args__ = (
        CheckConstraint("moq_units > 0", name="moq_units_positive"),
        CheckConstraint("lead_time_days >= 0", name="lead_time_days_nonnegative"),
        CheckConstraint(
            "reliability >= 0 AND reliability <= 1",
            name="reliability_between_zero_and_one",
        ),
    )

    vendor_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    moq_units: Mapped[int] = mapped_column(Integer, nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    reliability: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)

    preferred_items: Mapped[list[Item]] = relationship(
        back_populates="preferred_vendor",
        foreign_keys="Item.preferred_vendor_id",
    )
    orders: Mapped[list[Order]] = relationship(
        back_populates="vendor",
        passive_deletes=True,
    )
    offers: Mapped[list[VendorOffer]] = relationship(
        back_populates="vendor",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (
        CheckConstraint("on_hand >= 0", name="on_hand_nonnegative"),
        CheckConstraint("reorder_point >= 0", name="reorder_point_nonnegative"),
        CheckConstraint("avg_daily_draw >= 0", name="avg_daily_draw_nonnegative"),
        CheckConstraint("unit_cost_sgd >= 0", name="unit_cost_sgd_nonnegative"),
        Index("ix_items_category", "category"),
        Index("ix_items_preferred_vendor_id", "preferred_vendor_id"),
    )

    sku: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    on_hand: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    reorder_point: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_daily_draw: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost_sgd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    preferred_vendor_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("vendors.vendor_id", ondelete="SET NULL"),
        nullable=True,
    )
    dspi_series: Mapped[str | None] = mapped_column(String(255), nullable=True)

    preferred_vendor: Mapped[Vendor | None] = relationship(
        back_populates="preferred_items",
        foreign_keys=[preferred_vendor_id],
    )
    lots: Mapped[list[Lot]] = relationship(
        back_populates="item",
        passive_deletes=True,
    )
    orders: Mapped[list[Order]] = relationship(
        back_populates="item",
        passive_deletes=True,
    )
    vendor_offers: Mapped[list[VendorOffer]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Lot(Base):
    __tablename__ = "lots"
    __table_args__ = (
        CheckConstraint("qty >= 0", name="qty_nonnegative"),
        CheckConstraint(
            "source IN ('PURCHASED', 'DONATED')",
            name="lot_source",
        ),
        Index("ix_lots_sku_expiry_date", "sku", "expiry_date"),
    )

    lot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sku: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("items.sku", ondelete="RESTRICT"),
        nullable=False,
    )
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    source: Mapped[LotSource] = mapped_column(lot_source_type, nullable=False)

    item: Mapped[Item] = relationship(back_populates="lots")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("qty > 0", name="qty_positive"),
        CheckConstraint("unit_price_sgd >= 0", name="unit_price_sgd_nonnegative"),
        CheckConstraint("expected_at >= placed_at", name="expected_not_before_placed"),
        CheckConstraint(
            "status IN ('PLACED', 'FULFILLED', 'CANCELLED')",
            name="order_status",
        ),
        Index("ix_orders_vendor_id_status", "vendor_id", "status"),
        Index("ix_orders_sku_status", "sku", "status"),
    )

    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    vendor_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("vendors.vendor_id", ondelete="RESTRICT"),
        nullable=False,
    )
    sku: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("items.sku", ondelete="RESTRICT"),
        nullable=False,
    )
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        order_status_type,
        nullable=False,
        default=OrderStatus.PLACED,
        server_default=text("'PLACED'"),
    )
    unit_price_sgd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    placed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    expected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    vendor: Mapped[Vendor] = relationship(back_populates="orders")
    item: Mapped[Item] = relationship(back_populates="orders")


class VendorOffer(Base):
    """Private vendor/SKU availability and deterministic pricing inputs."""

    __tablename__ = "vendor_offers"
    __table_args__ = (
        CheckConstraint("available_qty >= 0", name="available_qty_nonnegative"),
        CheckConstraint("price_multiplier > 0", name="price_multiplier_positive"),
        CheckConstraint(
            "bulk_discount_threshold IS NULL OR bulk_discount_threshold > 0",
            name="bulk_discount_threshold_positive",
        ),
        CheckConstraint(
            "bulk_discount_rate >= 0 AND bulk_discount_rate < 1",
            name="bulk_discount_rate_valid",
        ),
        Index("ix_vendor_offers_sku_available_qty", "sku", "available_qty"),
    )

    vendor_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("vendors.vendor_id", ondelete="CASCADE"),
        primary_key=True,
    )
    sku: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("items.sku", ondelete="CASCADE"),
        primary_key=True,
    )
    available_qty: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    price_multiplier: Mapped[Decimal] = mapped_column(
        Numeric(8, 4),
        nullable=False,
        default=Decimal("1.0000"),
        server_default=text("1.0000"),
    )
    bulk_discount_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bulk_discount_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        nullable=False,
        default=Decimal("0.0000"),
        server_default=text("0.0000"),
    )

    vendor: Mapped[Vendor] = relationship(back_populates="offers")
    item: Mapped[Item] = relationship(back_populates="vendor_offers")


__all__ = [
    "Base",
    "Item",
    "Lot",
    "LotSource",
    "Order",
    "OrderStatus",
    "Vendor",
    "VendorOffer",
]
