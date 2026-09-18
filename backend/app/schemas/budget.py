import uuid
from datetime import date as _Date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, model_validator


class BudgetCreate(BaseModel):
    #: Exactly one of the two: a budget measures a category or a group.
    category_id: Optional[uuid.UUID] = None
    group_id: Optional[uuid.UUID] = None
    amount: Decimal
    month: _Date  # First day of month
    is_recurring: bool = False

    @model_validator(mode="after")
    def _one_scope(self) -> "BudgetCreate":
        if (self.category_id is None) == (self.group_id is None):
            raise ValueError("A budget is for a category or for a group, not both")
        return self


class BudgetUpdate(BaseModel):
    amount: Optional[Decimal] = None
    effective_month: Optional[_Date] = None


class BudgetRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    category_id: Optional[uuid.UUID] = None
    group_id: Optional[uuid.UUID] = None
    amount: Decimal
    month: _Date
    is_recurring: bool

    model_config = ConfigDict(from_attributes=True)


class BudgetVsActual(BaseModel):
    #: Null on a group row: the fields below describe the group instead.
    category_id: Optional[uuid.UUID] = None
    category_name: str
    category_icon: str
    category_color: str
    group_id: Optional[uuid.UUID] = None
    group_name: Optional[str] = None
    budget_amount: Optional[Decimal] = None
    actual_amount: Decimal
    projected_amount: Decimal = Decimal("0")
    prev_month_amount: Decimal = Decimal("0")
    projected_prev_month_amount: Decimal = Decimal("0")
    percentage_used: Optional[float] = None
    is_recurring: bool = False
