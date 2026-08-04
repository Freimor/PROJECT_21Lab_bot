from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class StaffRole(StrEnum):
    MAGISTER = "magister"
    TECH_PRIEST = "tech_priest"
    WATCHER = "watcher"


class CommunityRank(StrEnum):
    NOVICE = "novice"
    ADEPT = "adept"


class ContentStatus(StrEnum):
    DRAFT = "draft"
    MODERATION = "moderation"
    NEEDS_INFO = "needs_info"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"


class ContentKind(StrEnum):
    STAFF_NOTE = "staff_note"
    STORY = "story"
    MEME = "meme"


class LedgerType(StrEnum):
    GRANT = "grant"
    WITHDRAW = "withdraw"
    TRANSFER_OUT = "transfer_out"
    TRANSFER_IN = "transfer_in"
    PURCHASE_RESERVE = "purchase_reserve"
    PURCHASE_REFUND = "purchase_refund"
    ADJUSTMENT = "adjustment"


class OrderStatus(StrEnum):
    PENDING = "pending"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"


class ProductKind(StrEnum):
    PHYSICAL = "physical"
    SERVICE = "service"
    RANK = "rank"


class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(64))
    full_name: Mapped[str] = mapped_column(String(255))
    staff_role: Mapped[StaffRole | None] = mapped_column(
        Enum(StaffRole, native_enum=False), nullable=True
    )
    rank: Mapped[CommunityRank] = mapped_column(
        Enum(CommunityRank, native_enum=False), default=CommunityRank.NOVICE
    )
    balance: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    ledger_entries: Mapped[list[LedgerEntry]] = relationship(
        back_populates="account_user", foreign_keys="LedgerEntry.account_user_id"
    )


class AdminAction(Base):
    __tablename__ = "admin_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id"))
    action: Mapped[str] = mapped_column(String(80))
    target_id: Mapped[int | None] = mapped_column(BigInteger)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContentItem(Base):
    __tablename__ = "content_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id"))
    kind: Mapped[ContentKind] = mapped_column(Enum(ContentKind, native_enum=False))
    status: Mapped[ContentStatus] = mapped_column(
        Enum(ContentStatus, native_enum=False), default=ContentStatus.DRAFT
    )
    source_text: Mapped[str] = mapped_column(Text)
    draft_text: Mapped[str | None] = mapped_column(Text)
    media: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.telegram_id"))
    moderation_note: Mapped[str | None] = mapped_column(Text)
    published_message_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Interview(Base):
    __tablename__ = "interviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id"))
    state: Mapped[str] = mapped_column(String(32), default="prompted")
    answers: Mapped[list[str]] = mapped_column(JSON, default=list)
    content_item_id: Mapped[int | None] = mapped_column(ForeignKey("content_items.id"))
    prompted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_ledger_idempotency_key"),
        Index("ix_ledger_account_created", "account_user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_group: Mapped[str] = mapped_column(String(36), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120))
    initiator_id: Mapped[int | None] = mapped_column(ForeignKey("users.telegram_id"))
    account_user_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id"))
    counterparty_id: Mapped[int | None] = mapped_column(ForeignKey("users.telegram_id"))
    delta: Mapped[int] = mapped_column(Integer)
    balance_after: Mapped[int] = mapped_column(Integer)
    entry_type: Mapped[LedgerType] = mapped_column(Enum(LedgerType, native_enum=False))
    reason: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    account_user: Mapped[User] = relationship(
        back_populates="ledger_entries", foreign_keys=[account_user_id]
    )


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    price: Mapped[int] = mapped_column(Integer)
    stock: Mapped[int | None] = mapped_column(Integer)
    min_rank: Mapped[CommunityRank] = mapped_column(
        Enum(CommunityRank, native_enum=False), default=CommunityRank.NOVICE
    )
    kind: Mapped[ProductKind] = mapped_column(
        Enum(ProductKind, native_enum=False), default=ProductKind.PHYSICAL
    )
    grants_rank: Mapped[CommunityRank | None] = mapped_column(
        Enum(CommunityRank, native_enum=False)
    )
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    buyer_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    total_price: Mapped[int] = mapped_column(Integer)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, native_enum=False), default=OrderStatus.PENDING
    )
    handled_by: Mapped[int | None] = mapped_column(ForeignKey("users.telegram_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    product: Mapped[Product] = relationship()


class BotSetting(Base):
    __tablename__ = "bot_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.telegram_id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ChannelActivity(Base):
    __tablename__ = "channel_activity"

    channel_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    last_post_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_message_id: Mapped[int | None] = mapped_column(BigInteger)
    last_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_interviewee_id: Mapped[int | None] = mapped_column(ForeignKey("users.telegram_id"))
