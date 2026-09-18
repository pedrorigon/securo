"""Identification rules for recurring bills.

A recurring bill's placeholder says "Assinatura OpenAI ChatGPT — Meu Plano";
the bank says "OpenAI". The default matcher asks for the same amount, a date
close to the occurrence and a description that overlaps, which is the right
default when nobody has said anything and is exactly wrong when the charge
arrives converted to reais, with IOF, under a name the recurring never used.

This service stores the sentence the person *did* say: a set of text patterns
that identify the charge, scoped to the recurrings it belongs to. A matching
charge ignores amount and currency altogether (a subscription billed in
dollars posts in reais) and may land anywhere in the occurrence's month, by
design: the pattern is the identification, the date only ranks candidates.

Rows live in ``reconciliation_rules`` under their own node, which keeps them
out of the invoice/recurring policy documents in every direction: the policy
engine never reads this node, and the reconciliation screens never list it
(``EDITABLE_NODES`` does not contain it).

The config is the workspace's own document, not a sparse patch: these are
rules people write, never shipped defaults.

Shape::

    {
        "patterns": ["openai"],          # any one present in the description
        "excludes": ["iof"],             # none of these may be present
        "recurring_ids": ["<uuid>", ...] # the bills this rule answers for
    }
"""
from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.reconciliation import ReconciliationRule
from app.models.recurring_transaction import RecurringTransaction
from app.models.rule import Rule
from app.models.transaction import Transaction
from app.services.rule_engine import evaluate_conditions

#: The node these rows live under. Deliberately absent from
#: ``reconciliation_rule_service.EDITABLE_NODES_BY_MODULE``: the policy
#: engine and the reconciliation screens have no business reading it.
NODE = "recurring.identification"

#: One pattern, one exclude. Long enough for a bank's whole line, short
#: enough that the config stays a sentence rather than a document.
_MAX_TERM = 120
_MAX_TERMS = 20


class RuleError(ValueError):
    """A rule the caller asked for that cannot be stored."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def normalize(text: Optional[str]) -> str:
    """Lowercase, accent-folded, whitespace-collapsed text.

    Banks shout ("TRANSFERÊNCIA ENVIADA|ANDRÉIA"), people type ("Andreia"),
    and neither should have to match the other character for character.
    """
    if not text:
        return ""
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", folded).strip().casefold()


@dataclass(frozen=True)
class MatchRule:
    """One stored rule, ready to be matched against a charge.

    A rule is either written here (``patterns``/``excludes``, matched against
    the description) or **borrowed from the Rules screen** (``source_rule``,
    matched by running that rule's own conditions against the charge). The
    second kind exists because a person who already wrote "description
    contains OPENAI and not IOF" should not have to write it twice, and a
    rule that keeps two copies of the same sentence drifts.
    """

    id: uuid.UUID
    name: str
    patterns: tuple[str, ...]
    excludes: tuple[str, ...]
    recurring_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    source_rule: Optional[Rule] = None
    source_rule_id: Optional[uuid.UUID] = None
    #: Where the charge that settles this bill actually happens, when it is
    #: not the bill's own account and direction. A contribution leaves the
    #: checking account but the *identifying* row — the PIX credit — lands in
    #: the investment account; the person writes "any transfer to
    #: Investimentos settles the aporte", and this is how that sentence is
    #: stored. ``None`` means "the bill's own account/direction", which keeps
    #: every existing rule's meaning untouched.
    search_account_id: Optional[uuid.UUID] = None
    search_type: Optional[str] = None
    #: Some bills are settled in pieces: a few small PIX during the month and
    #: a closing payment. With ``accumulate`` the month's matching charges are
    #: summed and the occurrence is settled by the charge that crosses the
    #: line, instead of any single charge claiming it. ``accumulate_threshold``
    #: overrides "the bill's own amount" as that line.
    accumulate: bool = False
    accumulate_threshold: Optional[Decimal] = None

    def search_location(
        self, fallback_account_id: Optional[uuid.UUID], fallback_type: Optional[str]
    ) -> tuple[Optional[uuid.UUID], Optional[str]]:
        """The (account, direction) a settling charge must have."""
        return (
            self.search_account_id or fallback_account_id,
            self.search_type or fallback_type,
        )

    def matches(self, normalized_description: str) -> bool:
        if not normalized_description:
            return False
        if any(bad in normalized_description for bad in self.excludes):
            return False
        return any(good in normalized_description for good in self.patterns)

    def matches_transaction(self, tx: Transaction) -> bool:
        """Whether this rule identifies ``tx`` as one of its bills' charges."""
        if self.source_rule is not None:
            if not self.source_rule.is_active:
                # A rule turned off on the Rules screen stops identifying
                # charges too: one switch, one meaning.
                return False
            return evaluate_conditions(
                self.source_rule.conditions_op,
                self.source_rule.conditions or [],
                tx,
            )
        return self.matches(normalize(getattr(tx, "description", None)))


def _as_rule(row: ReconciliationRule, source: Optional[Rule] = None) -> MatchRule:
    config = row.config or {}
    source_id = config.get("source_rule_id")
    search_account_id = config.get("search_account_id")
    threshold = config.get("accumulate_threshold")
    return MatchRule(
        id=row.id,
        name=row.name or row.strategy_id,
        patterns=tuple(config.get("patterns") or ()),
        excludes=tuple(config.get("excludes") or ()),
        recurring_ids=frozenset(
            uuid.UUID(str(rid)) for rid in (config.get("recurring_ids") or ())
        ),
        source_rule=source,
        source_rule_id=uuid.UUID(str(source_id)) if source_id else None,
        search_account_id=(
            uuid.UUID(str(search_account_id)) if search_account_id else None
        ),
        search_type=config.get("search_type") or None,
        accumulate=bool(config.get("accumulate")),
        accumulate_threshold=(
            Decimal(str(threshold)) if threshold is not None else None
        ),
    )


async def list_rules(
    session: AsyncSession, workspace_id: uuid.UUID
) -> list[ReconciliationRule]:
    """Every live rule in one workspace, oldest first."""
    result = await session.execute(
        select(ReconciliationRule)
        .where(
            ReconciliationRule.workspace_id == workspace_id,
            ReconciliationRule.node == NODE,
            ReconciliationRule.deleted.is_(False),
        )
        .order_by(ReconciliationRule.created_at.asc())
    )
    return list(result.scalars())


async def load_rules(
    session: AsyncSession, workspace_id: uuid.UUID
) -> list[MatchRule]:
    """Every live rule in one workspace, ready to be matched against.

    Rules borrowed from the Rules screen are resolved in one batch, not one
    query per rule: a sync that walks many candidates must not pay the cost
    of a sentence somebody wrote once.
    """
    rows = await list_rules(session, workspace_id)
    source_ids = {
        uuid.UUID(str((row.config or {}).get("source_rule_id")))
        for row in rows
        if (row.config or {}).get("source_rule_id")
    }
    sources: dict[uuid.UUID, Rule] = {}
    if source_ids:
        result = await session.execute(select(Rule).where(Rule.id.in_(source_ids)))
        sources = {rule.id: rule for rule in result.scalars()}
    loaded: list[MatchRule] = []
    for row in rows:
        source_id = (row.config or {}).get("source_rule_id")
        source = sources.get(uuid.UUID(str(source_id))) if source_id else None
        loaded.append(_as_rule(row, source))
    return loaded


def matching_rule(
    rules: Iterable[MatchRule], description: Optional[str]
) -> Optional[MatchRule]:
    """The first rule whose patterns identify this description.

    Kept for callers that only hold the text; a rule borrowed from the Rules
    screen can never match here (it has no patterns of its own), so those
    call sites should build the charge and use ``matching_rule_for_tx``.
    """
    normalized = normalize(description)
    if not normalized:
        return None
    for rule in rules:
        if rule.source_rule is None and rule.matches(normalized):
            return rule
    return None


def matching_rule_for_tx(
    rules: Iterable[MatchRule], tx: Transaction
) -> Optional[MatchRule]:
    """The first rule that identifies this charge, borrowed or written."""
    for rule in rules:
        if rule.matches_transaction(tx):
            return rule
    return None


def rules_for_recurring(
    rules: Iterable[MatchRule], recurring_id: uuid.UUID
) -> list[MatchRule]:
    return [rule for rule in rules if recurring_id in rule.recurring_ids]


def rule_for_recurring(
    rules: Iterable[MatchRule], recurring_id: uuid.UUID
) -> Optional[MatchRule]:
    for rule in rules:
        if recurring_id in rule.recurring_ids:
            return rule
    return None


def rule_ids_by_recurring(rules: Iterable[MatchRule]) -> dict[uuid.UUID, list[uuid.UUID]]:
    """Reverse index for the recurrings screen: which rules touch each bill."""
    index: dict[uuid.UUID, list[uuid.UUID]] = {}
    for rule in rules:
        for recurring_id in rule.recurring_ids:
            index.setdefault(recurring_id, []).append(rule.id)
    return index


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _validate_terms(raw: Any, *, required: bool, code: str, message: str) -> list[str]:
    if raw is None:
        terms: list[str] = []
    elif isinstance(raw, str):
        terms = [part for part in re.split(r"[,\n;]", raw)]
    elif isinstance(raw, (list, tuple)):
        terms = [str(part) for part in raw]
    else:
        raise RuleError(code, message)

    cleaned: list[str] = []
    for term in terms:
        value = normalize(term)
        if not value:
            continue
        if len(value) > _MAX_TERM:
            raise RuleError(code, message)
        if value not in cleaned:
            cleaned.append(value)

    if required and not cleaned:
        raise RuleError(code, message)
    if len(cleaned) > _MAX_TERMS:
        raise RuleError(code, message)
    return cleaned


async def _validate_recurring_ids(
    session: AsyncSession, workspace_id: uuid.UUID, raw: Any
) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise RuleError("invalid_recurring_ids", "recurring_ids must be a list")
    ids: list[str] = []
    for value in raw:
        try:
            parsed = uuid.UUID(str(value))
        except (TypeError, ValueError) as exc:
            raise RuleError("invalid_recurring_ids", "recurring_ids must be UUIDs") from exc
        if parsed not in {uuid.UUID(uid) for uid in ids}:
            ids.append(str(parsed))
    if not ids:
        return []
    found = await session.execute(
        select(RecurringTransaction.id).where(
            RecurringTransaction.workspace_id == workspace_id,
            RecurringTransaction.id.in_([uuid.UUID(uid) for uid in ids]),
        )
    )
    known = {str(row[0]) for row in found.all()}
    missing = [uid for uid in ids if uid not in known]
    if missing:
        raise RuleError("unknown_recurring", "One of the recurrings no longer exists")
    return ids


def _build_config(
    patterns: list[str],
    excludes: list[str],
    recurring_ids: list[str],
    source_rule_id: Optional[str] = None,
    search_account_id: Optional[str] = None,
    search_type: Optional[str] = None,
    accumulate: bool = False,
    accumulate_threshold: Optional[str] = None,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "patterns": patterns,
        "excludes": excludes,
        "recurring_ids": recurring_ids,
    }
    if source_rule_id:
        config["source_rule_id"] = source_rule_id
    if search_account_id:
        config["search_account_id"] = search_account_id
    if search_type:
        config["search_type"] = search_type
    if accumulate:
        config["accumulate"] = True
    if accumulate_threshold:
        config["accumulate_threshold"] = accumulate_threshold
    return config


def _validate_accumulate_threshold(raw: Any) -> Optional[str]:
    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RuleError(
            "invalid_threshold", "The target amount must be a number"
        ) from exc
    if value <= 0:
        raise RuleError("invalid_threshold", "The target amount must be positive")
    return str(value)


_SEARCH_TYPES = ("debit", "credit")


async def _validate_search_account(
    session: AsyncSession, workspace_id: uuid.UUID, raw: Any
) -> Optional[str]:
    if raw in (None, ""):
        return None
    try:
        parsed = uuid.UUID(str(raw))
    except (TypeError, ValueError) as exc:
        raise RuleError("unknown_account", "That account does not exist") from exc
    found = await session.scalar(
        select(Account.id).where(
            Account.id == parsed, Account.workspace_id == workspace_id
        )
    )
    if found is None:
        raise RuleError("unknown_account", "That account does not exist")
    return str(found)


def _validate_search_type(raw: Any) -> Optional[str]:
    if raw in (None, ""):
        return None
    if raw not in _SEARCH_TYPES:
        raise RuleError("invalid_search_type", "Direction must be debit or credit")
    return str(raw)


async def _load_source_rule(
    session: AsyncSession, workspace_id: uuid.UUID, source_rule_id: Any
) -> Rule:
    """The Rules-screen rule this identification rule borrows, or an error."""
    try:
        parsed = uuid.UUID(str(source_rule_id))
    except (TypeError, ValueError) as exc:
        raise RuleError("unknown_rule", "That rule does not exist") from exc
    result = await session.execute(
        select(Rule).where(Rule.id == parsed, Rule.workspace_id == workspace_id)
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise RuleError("unknown_rule", "That rule does not exist")
    if not source.conditions:
        raise RuleError(
            "rule_without_conditions", "That rule has no conditions to reuse"
        )
    return source


async def source_rule_names(
    session: AsyncSession, rows: Iterable[ReconciliationRule]
) -> dict[str, str]:
    """Map source-rule ids to names, for the screen that lists these rules."""
    source_ids = {
        uuid.UUID(str((row.config or {}).get("source_rule_id")))
        for row in rows
        if (row.config or {}).get("source_rule_id")
    }
    if not source_ids:
        return {}
    result = await session.execute(
        select(Rule.id, Rule.name).where(Rule.id.in_(source_ids))
    )
    return {str(rule_id): name for rule_id, name in result.all()}


async def create_rule(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    name: Optional[str],
    patterns: Any,
    excludes: Any = None,
    recurring_ids: Any = None,
    source_rule_id: Any = None,
    search_account_id: Any = None,
    search_type: Any = None,
    accumulate: bool = False,
    accumulate_threshold: Any = None,
) -> ReconciliationRule:
    source = (
        await _load_source_rule(session, workspace_id, source_rule_id)
        if source_rule_id is not None
        else None
    )
    cleaned_name = (name or "").strip() or (source.name if source else "")
    if not cleaned_name:
        raise RuleError("name_required", "Give the rule a name")
    # A borrowed rule needs no texts of its own: its identification is the
    # source rule's own conditions, evaluated live.
    clean_patterns = _validate_terms(
        patterns,
        required=source is None,
        code="patterns_required",
        message="A rule needs at least one identifying text",
    )
    clean_excludes = _validate_terms(
        excludes,
        required=False,
        code="invalid_excludes",
        message="Exclude terms must be short texts",
    )
    clean_ids = await _validate_recurring_ids(session, workspace_id, recurring_ids)
    clean_account = await _validate_search_account(
        session, workspace_id, search_account_id
    )
    clean_type = _validate_search_type(search_type)
    clean_threshold = _validate_accumulate_threshold(accumulate_threshold)

    row = ReconciliationRule(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        user_id=user_id,
        node=NODE,
        strategy_id=f"user_{uuid.uuid4().hex[:8]}",
        origin="custom",
        name=cleaned_name,
        config=_build_config(
            clean_patterns,
            clean_excludes,
            clean_ids,
            str(source.id) if source else None,
            clean_account,
            clean_type,
            bool(accumulate),
            clean_threshold,
        ),
        policy_version=1,
    )
    session.add(row)
    await session.flush()
    return row


async def update_rule(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    row: ReconciliationRule,
    name: Optional[str] = None,
    patterns: Any = None,
    excludes: Any = None,
    recurring_ids: Any = None,
    source_rule_id: Any = None,
    search_account_id: Any = None,
    search_type: Any = None,
    accumulate: Any = None,
    accumulate_threshold: Any = None,
) -> ReconciliationRule:
    if name is not None:
        if not name.strip():
            raise RuleError("name_required", "Give the rule a name")
        row.name = name.strip()

    config = dict(row.config or {})
    borrowed = bool(config.get("source_rule_id"))
    if source_rule_id is not None:
        if source_rule_id == "":
            config.pop("source_rule_id", None)
            borrowed = False
        else:
            source = await _load_source_rule(session, workspace_id, source_rule_id)
            config["source_rule_id"] = str(source.id)
            borrowed = True
    if patterns is not None:
        config["patterns"] = _validate_terms(
            patterns,
            required=not borrowed,
            code="patterns_required",
            message="A rule needs at least one identifying text",
        )
    if excludes is not None:
        config["excludes"] = _validate_terms(
            excludes,
            required=False,
            code="invalid_excludes",
            message="Exclude terms must be short texts",
        )
    if recurring_ids is not None:
        config["recurring_ids"] = await _validate_recurring_ids(
            session, workspace_id, recurring_ids
        )
    if search_account_id is not None:
        clean_account = await _validate_search_account(
            session, workspace_id, search_account_id
        )
        if clean_account:
            config["search_account_id"] = clean_account
        else:
            config.pop("search_account_id", None)
    if search_type is not None:
        clean_type = _validate_search_type(search_type)
        if clean_type:
            config["search_type"] = clean_type
        else:
            config.pop("search_type", None)
    if accumulate is not None:
        if accumulate:
            config["accumulate"] = True
        else:
            config.pop("accumulate", None)
    if accumulate_threshold is not None:
        clean_threshold = _validate_accumulate_threshold(accumulate_threshold)
        if clean_threshold:
            config["accumulate_threshold"] = clean_threshold
        else:
            config.pop("accumulate_threshold", None)
    row.config = config
    await session.flush()
    return row


async def get_rule(
    session: AsyncSession, workspace_id: uuid.UUID, rule_id: uuid.UUID
) -> Optional[ReconciliationRule]:
    result = await session.execute(
        select(ReconciliationRule).where(
            ReconciliationRule.id == rule_id,
            ReconciliationRule.workspace_id == workspace_id,
            ReconciliationRule.node == NODE,
        )
    )
    return result.scalar_one_or_none()
