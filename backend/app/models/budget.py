import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.category import Category
    from app.models.category_group import CategoryGroup
    from app.models.user import User


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("user_id", "category_id", "month", "is_recurring", name="uq_budget_per_category_month_type"),
        UniqueConstraint("user_id", "group_id", "month", "is_recurring", name="uq_budget_per_group_month_type"),
        # A budget is for a category or for a group, never both and never
        # neither: the two scopes share one table so the month resolution
        # (override beats recurring) keeps working for both.
        CheckConstraint(
            "(category_id IS NULL) <> (group_id IS NULL)",
            name="ck_budget_single_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True
    )
    group_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("category_groups.id", ondelete="CASCADE"), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(precision=15, scale=2))
    month: Mapped[date] = mapped_column(Date)  # First day of month
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    currency: Mapped[Optional[str]] = mapped_column(String(3), server_default="USD", nullable=True)
    amount_primary: Mapped[Optional[Decimal]] = mapped_column(Numeric(precision=15, scale=2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship()
    category: Mapped[Optional["Category"]] = relationship()
    group: Mapped[Optional["CategoryGroup"]] = relationship()
