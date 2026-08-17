from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def str_enum(enum_cls: type[StrEnum]) -> Enum:
    """Store/load StrEnum by `.value` (DB has `flood_teaser`, not `FLOOD_TEASER`)."""
    return Enum(
        enum_cls,
        native_enum=False,
        values_callable=lambda members: [item.value for item in members],
    )


class OpenStrEnum(TypeDecorator):
    """Store free-form catalog codes; coerce known values back to ``enum_cls``."""

    impl = String
    cache_ok = True

    def __init__(self, enum_cls: type[StrEnum], length: int = 64):
        super().__init__(length=length)
        self.enum_cls = enum_cls
        self._by_value = {item.value.lower(): item for item in enum_cls}
        self._by_name = {item.name.lower(): item for item in enum_cls}

    def process_bind_param(self, value: object, dialect: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, self.enum_cls):
            return value.value
        text = str(value).strip()
        known = self._by_value.get(text.lower()) or self._by_name.get(text.lower())
        return known.value if known is not None else text

    def process_result_value(self, value: object, dialect: object) -> StrEnum | str | None:
        if value is None:
            return None
        text = str(value).strip()
        known = self._by_value.get(text.lower()) or self._by_name.get(text.lower())
        if known is not None:
            return known
        return text


class Base(DeclarativeBase):
    pass


class StaffRole(StrEnum):
    LORD = "lord"
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
    SCHEDULED = "scheduled"
    REJECTED = "rejected"
    PUBLISHED = "published"


class ContentKind(StrEnum):
    STAFF_NOTE = "staff_note"
    IMPORTANT = "important"
    STORY = "story"
    MEME = "meme"


class TemplateKind(StrEnum):
    MEME = "meme"
    FLOOD_TEASER = "flood_teaser"


class LedgerType(StrEnum):
    GRANT = "grant"
    WITHDRAW = "withdraw"
    TRANSFER_OUT = "transfer_out"
    TRANSFER_IN = "transfer_in"
    PURCHASE_RESERVE = "purchase_reserve"
    PURCHASE_REFUND = "purchase_refund"
    JOB_RESERVE = "job_reserve"
    JOB_REFUND = "job_refund"
    ADJUSTMENT = "adjustment"
    RESPECT_GRANT = "respect_grant"
    RESPECT_WITHDRAW = "respect_withdraw"
    POST_REWARD = "post_reward"
    MEME_REWARD = "meme_reward"


class OrderStatus(StrEnum):
    PENDING = "pending"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"


class ProductKind(StrEnum):
    MERCH = "merch"
    DEVICE = "device"
    SERVICE = "service"


class JoinKind(StrEnum):
    COMMUNITY = "community"
    STAFF = "staff"


class JoinStatus(StrEnum):
    PENDING = "pending"
    SKILL_VALIDATION = "skill_validation"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class FeedbackKind(StrEnum):
    BUG = "bug"
    UPGRADE = "upgrade"


class FeedbackStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ServiceJobStatus(StrEnum):
    OPEN = "open"
    CLAIMED = "claimed"
    REVIEW = "review"
    DONE = "done"
    CANCELLED = "cancelled"


class RemovalReason(StrEnum):
    NONE = "none"
    RULES = "rules"


class CommunityQuestStatus(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(64))
    full_name: Mapped[str] = mapped_column(String(255))
    avatar_file_id: Mapped[str | None] = mapped_column(String(255))
    bio: Mapped[str | None] = mapped_column(Text)
    staff_role: Mapped[StaffRole | str | None] = mapped_column(
        OpenStrEnum(StaffRole), nullable=True
    )
    rank: Mapped[CommunityRank | str] = mapped_column(
        OpenStrEnum(CommunityRank), default=CommunityRank.NOVICE
    )
    balance: Mapped[int] = mapped_column(Integer, default=0)
    respect: Mapped[int] = mapped_column(Integer, default=0)
    approved_meme_count: Mapped[int] = mapped_column(Integer, default=0)
    skill_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    # «Открыт к новым заказам» — ЛС при публикации подходящей заявки.
    job_notify_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    ritual_streak: Mapped[int] = mapped_column(Integer, default=0)
    ritual_last_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    status_message_id: Mapped[int | None] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    removal_reason: Mapped[RemovalReason | None] = mapped_column(
        Enum(RemovalReason, native_enum=False), nullable=True
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by: Mapped[int | None] = mapped_column(ForeignKey("users.telegram_id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    ledger_entries: Mapped[list[LedgerEntry]] = relationship(
        back_populates="account_user", foreign_keys="LedgerEntry.account_user_id"
    )


class JoinApplication(Base):
    __tablename__ = "join_applications"
    __table_args__ = (
        Index("ix_join_apps_status_kind", "status", "kind"),
        Index("ix_join_apps_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id"))
    kind: Mapped[JoinKind] = mapped_column(OpenStrEnum(JoinKind, length=32))
    status: Mapped[JoinStatus] = mapped_column(
        OpenStrEnum(JoinStatus, length=32), default=JoinStatus.PENDING
    )
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.telegram_id"))
    decision_note: Mapped[str | None] = mapped_column(Text)
    bio: Mapped[str | None] = mapped_column(Text)
    skills_text: Mapped[str | None] = mapped_column(Text)
    skill_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(foreign_keys=[user_id])


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
    __table_args__ = (
        Index("ix_content_published_chat_message", "published_channel_id", "published_message_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id"))
    kind: Mapped[ContentKind] = mapped_column(Enum(ContentKind, native_enum=False))
    status: Mapped[ContentStatus] = mapped_column(
        Enum(ContentStatus, native_enum=False), default=ContentStatus.DRAFT
    )
    source_text: Mapped[str] = mapped_column(Text)
    draft_text: Mapped[str | None] = mapped_column(Text)
    media: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    llm_processed: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.telegram_id"))
    moderation_note: Mapped[str | None] = mapped_column(Text)
    published_message_id: Mapped[int | None] = mapped_column(BigInteger)
    published_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    reaction_count: Mapped[int] = mapped_column(Integer, default=0)
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("content_templates.id", ondelete="SET NULL")
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    author: Mapped[User] = relationship(foreign_keys=[author_id])
    template: Mapped[ContentTemplate | None] = relationship(
        foreign_keys=[template_id], lazy="selectin"
    )


class ContentTemplate(Base):
    __tablename__ = "content_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[TemplateKind] = mapped_column(str_enum(TemplateKind))
    title: Mapped[str] = mapped_column(String(160), default="Мем")
    body: Mapped[str] = mapped_column(Text)
    media: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    collection_key: Mapped[str] = mapped_column(String(64), default="default")
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.telegram_id"))
    reaction_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    author: Mapped[User | None] = relationship(foreign_keys=[author_id])


class MemeCollection(Base):
    """Named meme pool used by auto-posting and seasons."""

    __tablename__ = "meme_collections"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    entry_type: Mapped[LedgerType] = mapped_column(OpenStrEnum(LedgerType, length=32))
    reason: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    account_user: Mapped[User] = relationship(
        back_populates="ledger_entries", foreign_keys=[account_user_id]
    )


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    price: Mapped[int] = mapped_column(Integer)
    stock: Mapped[int | None] = mapped_column(Integer)
    min_rank: Mapped[CommunityRank | str] = mapped_column(
        OpenStrEnum(CommunityRank), default=CommunityRank.NOVICE
    )
    kind: Mapped[ProductKind] = mapped_column(
        Enum(ProductKind, native_enum=False), default=ProductKind.MERCH
    )
    grants_rank: Mapped[CommunityRank | str | None] = mapped_column(OpenStrEnum(CommunityRank))
    image_path: Mapped[str | None] = mapped_column(String(255))
    skill_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    respect_reward: Mapped[int | None] = mapped_column(Integer)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    shop_message_id: Mapped[int | None] = mapped_column(BigInteger)
    shop_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    shop_file_id: Mapped[str | None] = mapped_column(String(255))
    max_per_user: Mapped[int | None] = mapped_column(Integer)
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


class ServiceJob(Base):
    __tablename__ = "service_jobs"
    __table_args__ = (
        Index("ix_service_jobs_status", "status"),
        Index("ix_service_jobs_chat_message", "job_chat_id", "job_message_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id"))
    skill_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text)
    assignee_note: Mapped[str] = mapped_column(Text, default="")
    media: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    result_text: Mapped[str] = mapped_column(Text, default="")
    result_media: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    content_item_id: Mapped[int | None] = mapped_column(ForeignKey("content_items.id"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    price: Mapped[int] = mapped_column(Integer, default=0)
    respect_reward: Mapped[int] = mapped_column(Integer, default=0)
    reserved: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[ServiceJobStatus] = mapped_column(
        str_enum(ServiceJobStatus), default=ServiceJobStatus.OPEN
    )
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.telegram_id"))
    job_message_id: Mapped[int | None] = mapped_column(BigInteger)
    job_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    customer: Mapped[User] = relationship(foreign_keys=[customer_id])
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id])
    product: Mapped[Product | None] = relationship(foreign_keys=[product_id])
    content_item: Mapped[ContentItem | None] = relationship(foreign_keys=[content_item_id])


class BotSetting(Base):
    __tablename__ = "bot_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.telegram_id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AdminNotifyEvent(Base):
    __tablename__ = "admin_notify_events"
    __table_args__ = (Index("ix_admin_notify_events_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FeedbackReport(Base):
    __tablename__ = "feedback_reports"
    __table_args__ = (
        Index("ix_feedback_reports_status_kind", "status", "kind"),
        UniqueConstraint("chat_id", "message_id", name="uq_feedback_chat_message"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[FeedbackKind] = mapped_column(str_enum(FeedbackKind))
    status: Mapped[FeedbackStatus] = mapped_column(
        str_enum(FeedbackStatus), default=FeedbackStatus.PENDING
    )
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.telegram_id"))
    author_name: Mapped[str] = mapped_column(String(200), default="")
    author_username: Mapped[str | None] = mapped_column(String(100))
    chat_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger)
    message_thread_id: Mapped[int | None] = mapped_column(BigInteger)
    text: Mapped[str] = mapped_column(Text, default="")
    media: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.telegram_id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    author: Mapped[User | None] = relationship(foreign_keys=[author_id])
    decider: Mapped[User | None] = relationship(foreign_keys=[decided_by])


class ChannelActivity(Base):
    __tablename__ = "channel_activity"

    channel_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    last_post_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_message_id: Mapped[int | None] = mapped_column(BigInteger)
    last_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_interviewee_id: Mapped[int | None] = mapped_column(ForeignKey("users.telegram_id"))


class Blessing(Base):
    __tablename__ = "blessings"
    __table_args__ = (Index("ix_blessings_from_created", "from_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id"))
    to_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CommunityQuest(Base):
    __tablename__ = "community_quests"
    __table_args__ = (
        Index("ix_community_quests_status", "status"),
        Index("ix_community_quests_chat_message", "chat_id", "message_id"),
        UniqueConstraint("number", name="uq_community_quests_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    media: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    skill_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    required_participants: Mapped[int] = mapped_column(Integer, default=1)
    grace_reward: Mapped[int] = mapped_column(Integer, default=0)
    respect_reward: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[CommunityQuestStatus] = mapped_column(
        str_enum(CommunityQuestStatus), default=CommunityQuestStatus.OPEN
    )
    chat_id: Mapped[int | None] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.telegram_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quest_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    quest_ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    creator: Mapped[User] = relationship(foreign_keys=[created_by])
    members: Mapped[list[CommunityQuestMember]] = relationship(
        back_populates="quest", cascade="all, delete-orphan"
    )


class CommunityQuestMember(Base):
    __tablename__ = "community_quest_members"
    __table_args__ = (
        UniqueConstraint("quest_id", "user_id", name="uq_quest_member"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quest_id: Mapped[int] = mapped_column(ForeignKey("community_quests.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id"))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reward_grace: Mapped[int | None] = mapped_column(Integer)
    reward_respect: Mapped[int | None] = mapped_column(Integer)

    quest: Mapped[CommunityQuest] = relationship(back_populates="members")
    user: Mapped[User] = relationship(foreign_keys=[user_id])


class SeasonEvent(Base):
    __tablename__ = "season_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    meme_collection: Mapped[str] = mapped_column(String(64), default="default")
    phrases_key: Mapped[str] = mapped_column(String(64), default="")
    start_message: Mapped[str] = mapped_column(Text, default="")
    end_message: Mapped[str] = mapped_column(Text, default="")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    start_announced: Mapped[bool] = mapped_column(Boolean, default=False)
    end_announced: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SkillDef(Base):
    """Editable skill catalog (seeded from data/skills.json)."""

    __tablename__ = "skill_defs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    requires_validation: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_description: Mapped[str] = mapped_column(Text, default="")
    level: Mapped[int] = mapped_column(Integer, default=1)
    grace_price: Mapped[int] = mapped_column(Integer, default=0)
    respect_reward: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RoleDef(Base):
    """Editable staff role catalog (seeded from data/ranks.json)."""

    __tablename__ = "role_defs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(200))
    badge: Mapped[str] = mapped_column(String(64), default="сотрудник")
    color: Mapped[str] = mapped_column(String(32), default="#6b7c93")
    description: Mapped[str] = mapped_column(Text, default="")
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_unique: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RankDef(Base):
    """Editable community rank catalog (seeded from data/ranks.json)."""

    __tablename__ = "rank_defs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(200))
    level: Mapped[int] = mapped_column(Integer, default=0)
    color: Mapped[str] = mapped_column(String(32), default="#a89878")
    base_grace: Mapped[int] = mapped_column(Integer, default=0)
    cap_grace: Mapped[int] = mapped_column(Integer, default=0)
    can_transfer_grace: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
