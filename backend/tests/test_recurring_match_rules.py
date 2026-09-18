"""Identification rules for recurring bills, and the lifecycle states.

A recurring bill says "Assinatura OpenAI ChatGPT — Meu Plano"; the bank says
"OpenAI", in reais, with IOF on top. These tests pin the sentence a person
can write down instead of a heuristic: patterns identify the charge, amount
and currency are ignored, the window is the occurrence's whole month, and the
closest occurrence wins with the earliest breaking ties. They also pin the
states the projection rows carry (forecast / overdue / missed) and the rule
that a month ending unanswered hides the occurrence from every total while
keeping it visible where a person goes looking.
"""
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.transaction import Transaction
from app.schemas.recurring_transaction import RecurringTransactionCreate
from app.services import recurring_match_rule_service as rule_service
from app.services import recurring_match_service as rms
from app.services.dashboard_service import (
    get_projected_transactions,
    next_business_day,
    projection_state,
)
from app.services.recurring_transaction_service import create_recurring_transaction


@pytest_asyncio.fixture
async def account(session: AsyncSession, test_user, test_workspace) -> Account:
    acc = Account(
        id=uuid.uuid4(),
        user_id=test_user.id,
        workspace_id=test_workspace.id,
        name="RuleAcc",
        type="checking",
        balance=Decimal("10000"),
        currency="BRL",
    )
    session.add(acc)
    await session.commit()
    await session.refresh(acc)
    return acc


async def _make_bill(session, test_workspace, test_user, account, **overrides):
    data = RecurringTransactionCreate(
        description=overrides.pop("description", "Assinatura OpenAI ChatGPT"),
        amount=overrides.pop("amount", Decimal("20.00")),
        currency=overrides.pop("currency", "USD"),
        type=overrides.pop("type", "debit"),
        frequency=overrides.pop("frequency", "monthly"),
        start_date=overrides.pop("start_date", _this_month(23)),
        account_id=account.id,
        **overrides,
    )
    return await create_recurring_transaction(session, test_workspace.id, test_user.id, data)


def _this_month(day: int) -> date:
    return date.today().replace(day=day)


def _last_month(day: int) -> date:
    first = date.today().replace(day=1)
    return (first - timedelta(days=1)).replace(day=day)


async def _add_tx(session, test_user, test_workspace, account, **kw):
    tx = Transaction(
        user_id=test_user.id,
        workspace_id=test_workspace.id,
        account_id=account.id,
        description=kw.get("description", "OPENAI *CHATGPT SUBSCR"),
        amount=kw.get("amount", Decimal("109.45")),
        currency=kw.get("currency", "BRL"),
        date=kw["date"],
        effective_date=kw.get("effective_date", kw["date"]),
        type=kw.get("type", "debit"),
        source=kw.get("source", "sync"),
        status=kw.get("status", "posted"),
        external_id=kw.get("external_id", f"ext-{uuid.uuid4().hex[:8]}"),
        recurring_transaction_id=kw.get("recurring_transaction_id"),
    )
    session.add(tx)
    await session.commit()
    await session.refresh(tx)
    return tx


# ---------------------------------------------------------------------------
# Text and rules
# ---------------------------------------------------------------------------


def test_normalize_folds_case_accents_and_spacing():
    assert rule_service.normalize("TRANSFERÊNCIA  ENVIADA|ANDRÉIA") == (
        "transferencia enviada|andreia"
    )
    assert rule_service.normalize(None) == ""
    assert rule_service.normalize("  OpenAI   ") == "openai"


def test_rule_matches_patterns_and_respects_excludes():
    rule = rule_service.MatchRule(
        id=uuid.uuid4(),
        name="OpenAI",
        patterns=("openai",),
        excludes=("iof",),
        recurring_ids=frozenset(),
    )
    assert rule.matches("openai *chatgpt subscr")
    assert not rule.matches("iof internacional - openai *chatgpt")
    assert not rule.matches("spotify")


@pytest.mark.asyncio
async def test_create_rule_validates(session, test_user, test_workspace, account):
    bill = await _make_bill(session, test_workspace, test_user, account)

    with pytest.raises(rule_service.RuleError):
        await rule_service.create_rule(
            session, test_workspace.id, test_user.id, "Empty", [], None, []
        )
    with pytest.raises(rule_service.RuleError):
        await rule_service.create_rule(
            session,
            test_workspace.id,
            test_user.id,
            "Ghost",
            ["ghost"],
            None,
            [uuid.uuid4()],
        )

    row = await rule_service.create_rule(
        session,
        test_workspace.id,
        test_user.id,
        "OpenAI",
        ["OpenAI", "OpenAI"],
        [" IOF "],
        [bill.id],
    )
    await session.commit()
    rules = await rule_service.load_rules(session, test_workspace.id)
    stored = next(r for r in rules if r.id == row.id)
    assert stored.patterns == ("openai",)
    assert stored.excludes == ("iof",)
    assert stored.recurring_ids == frozenset({bill.id})


# ---------------------------------------------------------------------------
# Matching: amount and currency are not the identification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rule_links_a_charge_the_default_matcher_refuses(
    session, test_user, test_workspace, account
):
    bill = await _make_bill(session, test_workspace, test_user, account)
    charge = await _add_tx(
        session, test_user, test_workspace, account,
        description="OpenAI",
        amount=Decimal("109.45"),
        date=_this_month(23),
    )

    # Without a rule the amount and currency disagree, so nothing links.
    assert await rms.find_bill_for_incoming(
        session, test_user.id, account.id, charge.amount, charge.currency,
        charge.type, charge.date, charge.description,
    ) is None

    await rule_service.create_rule(
        session, test_workspace.id, test_user.id, "OpenAI", ["openai"], None, [bill.id]
    )
    await session.commit()

    found = await rms.find_bill_for_incoming(
        session, test_user.id, account.id, charge.amount, charge.currency,
        charge.type, charge.date, charge.description,
    )
    assert found is not None and found.id == bill.id


@pytest.mark.asyncio
async def test_rule_excludes_iof_charges(session, test_user, test_workspace, account):
    bill = await _make_bill(session, test_workspace, test_user, account)
    await rule_service.create_rule(
        session, test_workspace.id, test_user.id, "OpenAI",
        ["openai"], ["iof"], [bill.id],
    )
    await session.commit()

    found = await rms.find_bill_for_incoming(
        session, test_user.id, account.id, Decimal("3.84"), "BRL", "debit",
        _this_month(23), "IOF INTERNACIONAL - OPENAI *CHATGPT SUBSCR",
    )
    assert found is None


@pytest.mark.asyncio
async def test_rule_only_answers_for_its_own_bills(
    session, test_user, test_workspace, account
):
    other = await _make_bill(
        session, test_workspace, test_user, account,
        description="Assinatura Claude", amount=Decimal("21.30"),
    )
    await rule_service.create_rule(
        session, test_workspace.id, test_user.id, "OpenAI", ["openai"], None, []
    )
    await session.commit()

    found = await rms.find_bill_for_incoming(
        session, test_user.id, account.id, Decimal("116.62"), "BRL", "debit",
        _this_month(11), "Anthropic Claude Sub",
    )
    assert found is None
    assert other.id  # the bill exists; the rule simply never names it


@pytest.mark.asyncio
async def test_best_match_wins_and_earliest_breaks_ties(
    session, test_user, test_workspace, account
):
    early = await _make_bill(
        session, test_workspace, test_user, account,
        description="OpenAI Meu Plano", start_date=_this_month(5), day_of_month=5,
    )
    late = await _make_bill(
        session, test_workspace, test_user, account,
        description="OpenAI Plano Brenda", start_date=_this_month(9), day_of_month=9,
    )
    await rule_service.create_rule(
        session, test_workspace.id, test_user.id, "OpenAI",
        ["openai"], None, [early.id, late.id],
    )
    await session.commit()

    # Distances 3 and 1: the closer occurrence wins.
    found = await rms.find_bill_for_incoming(
        session, test_user.id, account.id, Decimal("109.45"), "BRL", "debit",
        _this_month(8), "OpenAI",
    )
    assert found is not None and found.id == late.id

    # Distances 2 and 2: the earliest occurrence wins.
    found = await rms.find_bill_for_incoming(
        session, test_user.id, account.id, Decimal("106.17"), "BRL", "debit",
        _this_month(7), "OpenAI",
    )
    assert found is not None and found.id == early.id


@pytest.mark.asyncio
async def test_window_is_the_whole_month_and_no_further(
    session, test_user, test_workspace, account
):
    bill = await _make_bill(session, test_workspace, test_user, account)
    await rule_service.create_rule(
        session, test_workspace.id, test_user.id, "OpenAI", ["openai"], None, [bill.id]
    )
    await session.commit()

    # Twenty-one days away, same month: the whole month is the window.
    far = await rms.find_bill_for_incoming(
        session, test_user.id, account.id, Decimal("105.36"), "BRL", "debit",
        _this_month(2), "OpenAI",
    )
    assert far is not None and far.id == bill.id


@pytest.mark.asyncio
async def test_a_month_without_an_occurrence_never_answers(
    session, test_user, test_workspace, account
):
    next_month_first = (
        date.today().replace(day=1) + timedelta(days=32)
    ).replace(day=1)
    ahead = await _make_bill(
        session, test_workspace, test_user, account,
        description="Spotify só mês que vem",
        amount=Decimal("21.90"),
        currency="BRL",
        start_date=next_month_first,
        day_of_month=1,
    )
    await rule_service.create_rule(
        session, test_workspace.id, test_user.id, "Spotify", ["spotify"], None, [ahead.id]
    )
    await session.commit()

    # The bill's only occurrence is next month, so this month's charge has
    # nothing to answer, however close the date looks.
    crossing = await rms.find_bill_for_incoming(
        session, test_user.id, account.id, Decimal("21.90"), "BRL", "debit",
        _this_month(28), "Spotify",
    )
    assert crossing is None


@pytest.mark.asyncio
async def test_placeholder_upgrade_adopts_the_real_numbers(
    session, test_user, test_workspace, account
):
    bill = await _make_bill(session, test_workspace, test_user, account)
    await rule_service.create_rule(
        session, test_workspace.id, test_user.id, "OpenAI", ["openai"], None, [bill.id]
    )
    placeholder = await _add_tx(
        session, test_user, test_workspace, account,
        description=bill.description,
        amount=Decimal("20.00"),
        currency="USD",
        date=_this_month(23),
        source="recurring",
        status="pending",
        external_id=None,
        recurring_transaction_id=bill.id,
    )
    await session.commit()

    found = await rms.find_placeholder_for_incoming(
        session, account.id, Decimal("109.45"), "BRL", "debit",
        _this_month(24), "OpenAI",
    )
    assert found is not None and found.id == placeholder.id
    assert rms.matched_by_rule(found) is True

    incoming = Transaction(
        user_id=test_user.id,
        workspace_id=test_workspace.id,
        account_id=account.id,
        description="OpenAI",
        amount=Decimal("109.45"),
        currency="BRL",
        type="debit",
        date=_this_month(24),
        effective_date=_this_month(24),
        source="sync",
        status="posted",
        external_id="ext-real",
    )
    rms.absorb_real_charge(found, incoming)
    assert found.amount == Decimal("109.45")
    assert found.currency == "BRL"
    assert found.date == _this_month(24)


@pytest.mark.asyncio
async def test_placeholder_lookup_ignores_other_bills(
    session, test_user, test_workspace, account
):
    bill = await _make_bill(session, test_workspace, test_user, account)
    await rule_service.create_rule(
        session, test_workspace.id, test_user.id, "OpenAI", ["openai"], None, [bill.id]
    )
    other_placeholder = await _add_tx(
        session, test_user, test_workspace, account,
        description="Outro previsto",
        amount=Decimal("20.00"),
        currency="USD",
        date=_this_month(23),
        source="recurring",
        status="pending",
        external_id=None,
        recurring_transaction_id=None,
    )
    await session.commit()

    found = await rms.find_placeholder_for_incoming(
        session, account.id, Decimal("109.45"), "BRL", "debit",
        _this_month(23), "OpenAI",
    )
    assert found is None
    assert other_placeholder.id


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------


def test_next_business_day_skips_weekends():
    assert next_business_day(date(2026, 9, 17)) == date(2026, 9, 18)  # Thu → Fri
    assert next_business_day(date(2026, 9, 18)) == date(2026, 9, 21)  # Fri → Mon
    assert next_business_day(date(2026, 9, 19)) == date(2026, 9, 21)  # Sat → Mon


def test_projection_state_boundaries():
    today = date(2026, 9, 17)  # Thursday

    assert projection_state(date(2026, 9, 16), today) == "overdue"
    assert projection_state(date(2026, 9, 17), today) == "forecast"
    assert projection_state(date(2026, 9, 18), today) == "forecast"
    assert projection_state(date(2026, 8, 31), today) == "missed"
    # Before the bill existed, nothing was promised: not ours to mark.
    assert projection_state(
        date(2026, 8, 31), today, created_month=date(2026, 9, 1)
    ) == "forecast"
    assert projection_state(
        date(2026, 9, 10), today, created_month=date(2026, 9, 1)
    ) == "overdue"


@pytest.mark.asyncio
async def test_projected_transactions_carry_state_and_hide_missed(
    session, test_user, test_workspace, account
):
    created_last = _last_month(10)
    missed = await _make_bill(
        session, test_workspace, test_user, account,
        description="Nunca veio", start_date=_last_month(15), day_of_month=15,
    )
    missed.created_at = datetime(created_last.year, created_last.month, 10)
    overdue = await _make_bill(
        session, test_workspace, test_user, account,
        description="Atrasada", amount=Decimal("50.00"), currency="BRL",
        start_date=_this_month(1), day_of_month=1,
    )
    await session.commit()

    past = await get_projected_transactions(
        session, test_workspace.id, test_user.id, month=_last_month(1)
    )
    assert [row.recurring_id for row in past] == []

    past_with_missed = await get_projected_transactions(
        session, test_workspace.id, test_user.id, month=_last_month(1),
        include_missed=True,
    )
    missed_rows = [row for row in past_with_missed if row.recurring_id == str(missed.id)]
    assert len(missed_rows) == 1
    assert missed_rows[0].state == "missed"

    current = await get_projected_transactions(
        session, test_workspace.id, test_user.id, month=_this_month(1)
    )
    row = next(row for row in current if row.recurring_id == str(overdue.id))
    assert row.state == "overdue"


@pytest.mark.asyncio
async def test_transactions_list_hides_missed_placeholders(
    session, test_user, test_workspace, account
):
    from app.services.transaction_service import get_transactions

    bill = await _make_bill(session, test_workspace, test_user, account)
    stale = await _add_tx(
        session, test_user, test_workspace, account,
        description="Previsto antigo",
        amount=Decimal("20.00"),
        currency="USD",
        date=_last_month(5),
        source="recurring",
        status="pending",
        external_id=None,
        recurring_transaction_id=bill.id,
    )
    normal = await _add_tx(
        session, test_user, test_workspace, account,
        description="Compra normal",
        amount=Decimal("10.00"),
        date=_last_month(6),
    )
    await session.commit()

    rows, _, _ = await get_transactions(
        session, test_workspace.id, test_user.id, limit=50
    )
    ids = {row.id for row in rows}
    assert normal.id in ids
    assert stale.id not in ids

    rows, _, _ = await get_transactions(
        session, test_workspace.id, test_user.id, limit=50, include_missed=True
    )
    assert stale.id in {row.id for row in rows}


# ---------------------------------------------------------------------------
# Borrowing a rule from the Rules screen
# ---------------------------------------------------------------------------


async def _make_normal_rule(session, test_user, test_workspace, **overrides):
    from app.models.rule import Rule

    rule = Rule(
        id=uuid.uuid4(),
        user_id=test_user.id,
        workspace_id=test_workspace.id,
        name=overrides.pop("name", "Assinatura ChatGPT / Codex - OpenAI"),
        conditions_op=overrides.pop("conditions_op", "and"),
        conditions=overrides.pop(
            "conditions",
            [
                {"field": "description", "op": "contains", "value": "OPENAI"},
                {"field": "description", "op": "not_contains", "value": "IOF"},
                {"field": "type", "op": "equals", "value": "debit"},
            ],
        ),
        actions=overrides.pop("actions", [{"op": "ignore"}]),
        is_active=overrides.pop("is_active", True),
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return rule


@pytest.mark.asyncio
async def test_borrowed_rule_identifies_without_own_patterns(
    session, test_user, test_workspace, account
):
    bill = await _make_bill(session, test_workspace, test_user, account)
    source = await _make_normal_rule(session, test_user, test_workspace)
    row = await rule_service.create_rule(
        session,
        test_workspace.id,
        test_user.id,
        None,
        [],
        None,
        [bill.id],
        source_rule_id=source.id,
    )
    await session.commit()
    assert row.name == source.name

    found = await rms.find_bill_for_incoming(
        session, test_user.id, account.id, Decimal("109.45"), "BRL", "debit",
        _this_month(23), "OpenAI",
    )
    assert found is not None and found.id == bill.id

    # The borrowed rule's own excludes and type condition are respected.
    assert await rms.find_bill_for_incoming(
        session, test_user.id, account.id, Decimal("3.84"), "BRL", "debit",
        _this_month(23), "IOF INTERNACIONAL - OPENAI *CHATGPT SUBSCR",
    ) is None
    assert await rms.find_bill_for_incoming(
        session, test_user.id, account.id, Decimal("109.45"), "BRL", "credit",
        _this_month(23), "OpenAI",
    ) is None


@pytest.mark.asyncio
async def test_borrowed_rule_follows_the_source_switch(
    session, test_user, test_workspace, account
):
    bill = await _make_bill(session, test_workspace, test_user, account)
    source = await _make_normal_rule(session, test_user, test_workspace)
    await rule_service.create_rule(
        session, test_workspace.id, test_user.id, None, [], None, [bill.id],
        source_rule_id=source.id,
    )
    await session.commit()

    source.is_active = False
    await session.commit()

    # One switch, one meaning: a rule turned off on the Rules screen stops
    # identifying charges here too.
    found = await rms.find_bill_for_incoming(
        session, test_user.id, account.id, Decimal("109.45"), "BRL", "debit",
        _this_month(23), "OpenAI",
    )
    assert found is None


@pytest.mark.asyncio
async def test_borrowed_rule_validates_source(
    session, test_user, test_workspace, account
):
    bill = await _make_bill(session, test_workspace, test_user, account)
    with pytest.raises(rule_service.RuleError):
        await rule_service.create_rule(
            session, test_workspace.id, test_user.id, "Ghost", [], None, [bill.id],
            source_rule_id=uuid.uuid4(),
        )

    empty = await _make_normal_rule(
        session, test_user, test_workspace, name="Sem condições", conditions=[]
    )
    with pytest.raises(rule_service.RuleError):
        await rule_service.create_rule(
            session, test_workspace.id, test_user.id, None, [], None, [bill.id],
            source_rule_id=empty.id,
        )


# ---------------------------------------------------------------------------
# Settling from the other side (the PIX credit on the destination account)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def invest_account(session, test_user, test_workspace) -> Account:
    acc = Account(
        id=uuid.uuid4(),
        user_id=test_user.id,
        workspace_id=test_workspace.id,
        name="Investimentos",
        type="investment",
        balance=Decimal("0"),
        currency="BRL",
    )
    session.add(acc)
    await session.commit()
    await session.refresh(acc)
    return acc


@pytest.mark.asyncio
async def test_destination_rule_settles_the_forecast(
    session, test_user, test_workspace, account, invest_account
):
    """A contribution leaves the checking account but the identifying row —
    the PIX credit — lands on the investment side."""
    aporte = await _make_bill(
        session, test_workspace, test_user, account,
        description="Aporte Mensal",
        amount=Decimal("2000.00"),
        currency="BRL",
        start_date=_this_month(8),
        day_of_month=8,
    )
    await rule_service.create_rule(
        session,
        test_workspace.id,
        test_user.id,
        "Aporte pela chegada",
        ["transferencia a credito via pix"],
        None,
        [aporte.id],
        search_account_id=invest_account.id,
        search_type="credit",
    )
    await session.commit()

    # The credit that lands on the investment account settles it.
    found = await rms.find_bill_for_incoming(
        session, test_user.id, invest_account.id, Decimal("1500.00"), "BRL",
        "credit", _this_month(15), "TRANSFERÊNCIA A CRÉDITO VIA PIX",
    )
    assert found is not None and found.id == aporte.id

    # A debit with the same text, or a credit elsewhere, does not.
    assert await rms.find_bill_for_incoming(
        session, test_user.id, invest_account.id, Decimal("1500.00"), "BRL",
        "debit", _this_month(15), "TRANSFERÊNCIA A CRÉDITO VIA PIX",
    ) is None
    assert await rms.find_bill_for_incoming(
        session, test_user.id, account.id, Decimal("1500.00"), "BRL",
        "credit", _this_month(15), "TRANSFERÊNCIA A CRÉDITO VIA PIX",
    ) is None


@pytest.mark.asyncio
async def test_destination_rule_ignores_other_transfers(
    session, test_user, test_workspace, account, invest_account
):
    aporte = await _make_bill(
        session, test_workspace, test_user, account,
        description="Aporte Mensal", amount=Decimal("2000.00"), currency="BRL",
        start_date=_this_month(8), day_of_month=8,
    )
    await rule_service.create_rule(
        session, test_workspace.id, test_user.id, "Aporte pela chegada",
        ["transferencia a credito via pix"], None, [aporte.id],
        search_account_id=invest_account.id, search_type="credit",
    )
    await session.commit()

    # A self-PIX leaving for another bank keeps its own name and never
    # answers for the contribution: the pattern is the arrival, not the
    # departure.
    source_account, _ = account, invest_account
    found = await rms.find_bill_for_incoming(
        session, test_user.id, source_account.id, Decimal("1222.00"), "BRL",
        "debit", _this_month(30), "Transferência enviada|Pedro Henrique Casarotto Rigon",
    )
    assert found is None


@pytest.mark.asyncio
async def test_destination_rule_validates_account_and_type(
    session, test_user, test_workspace, account
):
    bill = await _make_bill(session, test_workspace, test_user, account)
    with pytest.raises(rule_service.RuleError):
        await rule_service.create_rule(
            session, test_workspace.id, test_user.id, "Conta fantasma",
            ["x"], None, [bill.id], search_account_id=uuid.uuid4(),
        )
    with pytest.raises(rule_service.RuleError):
        await rule_service.create_rule(
            session, test_workspace.id, test_user.id, "Sentido inválido",
            ["x"], None, [bill.id], search_type="both",
        )


# ---------------------------------------------------------------------------
# Accumulating until the month crosses the line
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accumulate_settles_only_when_the_month_crosses(
    session, test_user, test_workspace, account
):
    """A bill paid in pieces: small PIX during the month and a closing one.
    No single charge claims the occurrence; the one that crosses the line
    does."""
    faxina = await _make_bill(
        session, test_workspace, test_user, account,
        description="Faxina — Rose",
        amount=Decimal("230.00"),
        currency="BRL",
        start_date=_this_month(15),
        day_of_month=15,
    )
    await rule_service.create_rule(
        session, test_workspace.id, test_user.id, "Faxina acumulada",
        ["roselaine"], None, [faxina.id],
        accumulate=True,
        accumulate_threshold="200",
    )
    await session.commit()

    # The first small PIX alone does not settle it.
    assert await rms.find_bill_for_incoming(
        session, test_user.id, account.id, Decimal("30.00"), "BRL",
        "debit", _this_month(14), "Transferência enviada|Mara Roselaine Bueno de Lemos",
    ) is None

    await _add_tx(
        session, test_user, test_workspace, account,
        description="Transferência enviada|Mara Roselaine Bueno de Lemos",
        amount=Decimal("30.00"),
        date=_this_month(14),
    )

    # Thirty plus the closing payment cross the line: the closing charge
    # settles the occurrence.
    found = await rms.find_bill_for_incoming(
        session, test_user.id, account.id, Decimal("200.00"), "BRL",
        "debit", _this_month(15), "Transferência enviada|Mara Roselaine Bueno de Lemos",
    )
    assert found is not None and found.id == faxina.id


@pytest.mark.asyncio
async def test_accumulate_ignores_charges_outside_the_rule(
    session, test_user, test_workspace, account
):
    faxina = await _make_bill(
        session, test_workspace, test_user, account,
        description="Faxina — Rose", amount=Decimal("230.00"), currency="BRL",
        start_date=_this_month(15), day_of_month=15,
    )
    await rule_service.create_rule(
        session, test_workspace.id, test_user.id, "Faxina acumulada",
        ["roselaine"], None, [faxina.id], accumulate=True, accumulate_threshold="200",
    )
    await _add_tx(
        session, test_user, test_workspace, account,
        description="Outra coisa qualquer", amount=Decimal("500.00"),
        date=_this_month(14),
    )
    await session.commit()

    # A charge the rule does not identify adds nothing to the month.
    assert await rms.find_bill_for_incoming(
        session, test_user.id, account.id, Decimal("30.00"), "BRL",
        "debit", _this_month(15), "Transferência enviada|Mara Roselaine Bueno de Lemos",
    ) is None


@pytest.mark.asyncio
async def test_accumulate_defaults_to_the_bill_amount(
    session, test_user, test_workspace, account
):
    bill = await _make_bill(
        session, test_workspace, test_user, account,
        description="Faxina — Rose", amount=Decimal("230.00"), currency="BRL",
        start_date=_this_month(15), day_of_month=15,
    )
    await rule_service.create_rule(
        session, test_workspace.id, test_user.id, "Faxina acumulada",
        ["roselaine"], None, [bill.id], accumulate=True,
    )
    await _add_tx(
        session, test_user, test_workspace, account,
        description="Transferência enviada|Mara Roselaine Bueno de Lemos",
        amount=Decimal("30.00"),
        date=_this_month(14),
    )
    await session.commit()

    # 30 + 150 = 180 < 230: still not settled.
    assert await rms.find_bill_for_incoming(
        session, test_user.id, account.id, Decimal("150.00"), "BRL",
        "debit", _this_month(15), "Transferência enviada|Mara Roselaine Bueno de Lemos",
    ) is None
    # 30 + 200 = 230 >= 230: settled.
    found = await rms.find_bill_for_incoming(
        session, test_user.id, account.id, Decimal("200.00"), "BRL",
        "debit", _this_month(15), "Transferência enviada|Mara Roselaine Bueno de Lemos",
    )
    assert found is not None and found.id == bill.id


@pytest.mark.asyncio
async def test_borrowed_rule_matches_by_payee(
    session, test_user, test_workspace, account
):
    """A rule keyed on the payee — the shape most categorization rules take —
    identifies the charge through the same payee the sync resolved."""
    bill = await _make_bill(
        session, test_workspace, test_user, account,
        description="Faxina — Rose", amount=Decimal("230.00"), currency="BRL",
    )
    payee_id = uuid.uuid4()
    source = await _make_normal_rule(
        session, test_user, test_workspace,
        name="Gastos com Faxina",
        conditions=[
            {"field": "payee_id", "op": "equals", "value": str(payee_id)},
            {"field": "type", "op": "equals", "value": "debit"},
        ],
    )
    await rule_service.create_rule(
        session, test_workspace.id, test_user.id, None, [], None, [bill.id],
        source_rule_id=source.id,
    )
    await session.commit()

    found = await rms.find_bill_for_incoming(
        session, test_user.id, account.id, Decimal("200.00"), "BRL", "debit",
        _this_month(15),
        "Transferência enviada|Mara Roselaine Bueno de Lemos",
        payee="031.855.130-61", payee_id=payee_id,
    )
    assert found is not None and found.id == bill.id

    # Without the payee, the same text no longer identifies it.
    assert await rms.find_bill_for_incoming(
        session, test_user.id, account.id, Decimal("200.00"), "BRL", "debit",
        _this_month(15), "Transferência enviada|Mara Roselaine Bueno de Lemos",
    ) is None
