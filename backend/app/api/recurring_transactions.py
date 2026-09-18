import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.workspace_context import (
    WorkspaceContext,
    current_workspace,
    current_writable_workspace,
)
from app.schemas.recurring_match_rule import (
    RecurringMatchRuleCreate,
    RecurringMatchRuleRead,
    RecurringMatchRuleUpdate,
    match_rule_read,
)
from app.schemas.recurring_transaction import (
    RecurringTransactionCreate,
    RecurringTransactionRead,
    RecurringTransactionUpdate,
)
from app.services import (
    recurring_match_rule_service,
    recurring_transaction_service,
)

router = APIRouter(prefix="/api/recurring-transactions", tags=["recurring-transactions"])


# ---------------------------------------------------------------------------
# Identification rules. Declared before the ``/{recurring_id}`` routes so the
# literal "match-rules" path is never parsed as an id.
# ---------------------------------------------------------------------------


@router.get("/match-rules", response_model=list[RecurringMatchRuleRead])
async def list_match_rules(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    rows = await recurring_match_rule_service.list_rules(session, ctx.workspace.id)
    names = await recurring_match_rule_service.source_rule_names(session, rows)
    return [
        match_rule_read(
            row,
            source_rule_name=names.get(
                str((row.config or {}).get("source_rule_id", ""))
            ),
        )
        for row in rows
    ]


@router.post(
    "/match-rules",
    response_model=RecurringMatchRuleRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_match_rule(
    data: RecurringMatchRuleCreate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    try:
        row = await recurring_match_rule_service.create_rule(
            session,
            ctx.workspace.id,
            ctx.user_id,
            data.name,
            data.patterns,
            data.excludes,
            data.recurring_ids,
            data.source_rule_id,
            data.search_account_id,
            data.search_type,
            data.accumulate,
            data.accumulate_threshold,
        )
    except recurring_match_rule_service.RuleError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.code) from e
    await session.commit()
    names = await recurring_match_rule_service.source_rule_names(session, [row])
    return match_rule_read(
        row, source_rule_name=names.get(str((row.config or {}).get("source_rule_id", "")))
    )


@router.patch("/match-rules/{rule_id}", response_model=RecurringMatchRuleRead)
async def update_match_rule(
    rule_id: uuid.UUID,
    data: RecurringMatchRuleUpdate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    row = await recurring_match_rule_service.get_rule(session, ctx.workspace.id, rule_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    try:
        row = await recurring_match_rule_service.update_rule(
            session,
            ctx.workspace.id,
            row,
            name=data.name,
            patterns=data.patterns,
            excludes=data.excludes,
            recurring_ids=data.recurring_ids,
            source_rule_id=data.source_rule_id,
            search_account_id=data.search_account_id,
            search_type=data.search_type,
            accumulate=data.accumulate,
            accumulate_threshold=data.accumulate_threshold,
        )
    except recurring_match_rule_service.RuleError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.code) from e
    await session.commit()
    names = await recurring_match_rule_service.source_rule_names(session, [row])
    return match_rule_read(
        row, source_rule_name=names.get(str((row.config or {}).get("source_rule_id", "")))
    )


@router.delete("/match-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_match_rule(
    rule_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    row = await recurring_match_rule_service.get_rule(session, ctx.workspace.id, rule_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    row.deleted = True
    await session.commit()


@router.get("", response_model=list[RecurringTransactionRead])
async def list_recurring_transactions(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await recurring_transaction_service.get_recurring_transactions(session, ctx.workspace.id)


@router.post("", response_model=RecurringTransactionRead, status_code=status.HTTP_201_CREATED)
async def create_recurring_transaction(
    data: RecurringTransactionCreate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await recurring_transaction_service.create_recurring_transaction(
            session, ctx.workspace.id, ctx.user_id, data
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/{recurring_id}", response_model=RecurringTransactionRead)
async def update_recurring_transaction(
    recurring_id: uuid.UUID,
    data: RecurringTransactionUpdate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    try:
        recurring = await recurring_transaction_service.update_recurring_transaction(
            session, recurring_id, ctx.workspace.id, data
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not recurring:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recurring transaction not found")
    return recurring


@router.delete("/{recurring_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recurring_transaction(
    recurring_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    deleted = await recurring_transaction_service.delete_recurring_transaction(
        session, recurring_id, ctx.workspace.id
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recurring transaction not found")


@router.post("/generate")
async def generate_recurring_transactions(
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    count = await recurring_transaction_service.generate_pending(session, ctx.user_id)
    return {"generated": count}
