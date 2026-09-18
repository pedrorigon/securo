import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.models.reconciliation import ReconciliationRule
from app.services.recurring_match_rule_service import MatchRule

SearchType = Literal["debit", "credit"]


class RecurringMatchRuleCreate(BaseModel):
    #: Optional when borrowing from a Rules-screen rule: the source rule
    #: already has a name, and asking for a second one is asking the person
    #: to name the same thing twice.
    name: Optional[str] = None
    patterns: list[str] = Field(default_factory=list)
    excludes: list[str] = Field(default_factory=list)
    recurring_ids: list[uuid.UUID] = Field(default_factory=list)
    source_rule_id: Optional[uuid.UUID] = None
    #: Where the settling charge actually lands, when it is not the bill's
    #: own account/direction (e.g. the PIX credit on the investment side).
    search_account_id: Optional[uuid.UUID] = None
    search_type: Optional[SearchType] = None
    #: Settle in pieces: the month's matching charges are summed and the
    #: charge that crosses the line settles the occurrence.
    accumulate: bool = False
    accumulate_threshold: Optional[Decimal] = None


class RecurringMatchRuleUpdate(BaseModel):
    name: Optional[str] = None
    patterns: Optional[list[str]] = None
    excludes: Optional[list[str]] = None
    recurring_ids: Optional[list[uuid.UUID]] = None
    #: "" detaches from the borrowed rule; a uuid (re)attaches.
    source_rule_id: Optional[str] = None
    #: "" clears the override.
    search_account_id: Optional[str] = None
    search_type: Optional[str] = None
    accumulate: Optional[bool] = None
    #: "" clears the target and falls back to the bill's own amount.
    accumulate_threshold: Optional[str] = None


class RecurringMatchRuleRead(BaseModel):
    id: uuid.UUID
    name: str
    patterns: list[str]
    excludes: list[str]
    recurring_ids: list[uuid.UUID]
    created_at: Optional[datetime] = None
    source_rule_id: Optional[uuid.UUID] = None
    source_rule_name: Optional[str] = None
    search_account_id: Optional[uuid.UUID] = None
    search_type: Optional[str] = None
    accumulate: bool = False
    accumulate_threshold: Optional[Decimal] = None


def match_rule_read(
    row: ReconciliationRule,
    rule: Optional[MatchRule] = None,
    source_rule_name: Optional[str] = None,
) -> RecurringMatchRuleRead:
    """Serialize a stored rule, preferring the normalized view when given."""
    if rule is None:
        config = row.config or {}
        return RecurringMatchRuleRead(
            id=row.id,
            name=row.name or row.strategy_id,
            patterns=list(config.get("patterns") or []),
            excludes=list(config.get("excludes") or []),
            recurring_ids=[
                uuid.UUID(str(rid)) for rid in (config.get("recurring_ids") or [])
            ],
            created_at=row.created_at,
            source_rule_id=config.get("source_rule_id"),
            source_rule_name=source_rule_name,
            search_account_id=config.get("search_account_id"),
            search_type=config.get("search_type"),
            accumulate=bool(config.get("accumulate")),
            accumulate_threshold=config.get("accumulate_threshold"),
        )
    return RecurringMatchRuleRead(
        id=rule.id,
        name=rule.name,
        patterns=list(rule.patterns),
        excludes=list(rule.excludes),
        recurring_ids=sorted(rule.recurring_ids, key=str),
        created_at=row.created_at,
        source_rule_id=rule.source_rule_id,
        source_rule_name=source_rule_name,
        search_account_id=rule.search_account_id,
        search_type=rule.search_type,
        accumulate=rule.accumulate,
        accumulate_threshold=rule.accumulate_threshold,
    )
