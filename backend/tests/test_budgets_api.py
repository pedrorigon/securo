"""Tests for recurring budgets API."""
from datetime import date, timedelta

import pytest


def _current_month_str() -> str:
    return date.today().replace(day=1).isoformat()


def _prev_month_str() -> str:
    first = date.today().replace(day=1)
    prev = (first - timedelta(days=1)).replace(day=1)
    return prev.isoformat()


def _next_month_str() -> str:
    first = date.today().replace(day=1)
    if first.month == 12:
        return first.replace(year=first.year + 1, month=1).isoformat()
    return first.replace(month=first.month + 1).isoformat()


def _month_str(months_offset: int) -> str:
    """Return 1st of month N months from now (negative = past)."""
    d = date.today().replace(day=1)
    for _ in range(abs(months_offset)):
        if months_offset > 0:
            if d.month == 12:
                d = d.replace(year=d.year + 1, month=1)
            else:
                d = d.replace(month=d.month + 1)
        else:
            if d.month == 1:
                d = d.replace(year=d.year - 1, month=12)
            else:
                d = d.replace(month=d.month - 1)
    return d.isoformat()


@pytest.mark.asyncio
async def test_create_budget_defaults_non_recurring(client, auth_headers, test_categories):
    """Creating a budget without is_recurring defaults to false (backward compat)."""
    cat = test_categories[0]
    response = await client.post(
        "/api/budgets",
        json={"category_id": str(cat.id), "amount": 500, "month": _current_month_str()},
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["is_recurring"] is False
    assert float(data["amount"]) == 500.0


@pytest.mark.asyncio
async def test_create_recurring_budget(client, auth_headers, test_categories):
    """Creating a recurring budget sets is_recurring=true."""
    cat = test_categories[1]
    response = await client.post(
        "/api/budgets",
        json={
            "category_id": str(cat.id),
            "amount": 300,
            "month": _current_month_str(),
            "is_recurring": True,
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["is_recurring"] is True


@pytest.mark.asyncio
async def test_recurring_budget_appears_in_future_months(client, auth_headers, test_categories):
    """A recurring budget effective from current month should appear in future month listings."""
    cat = test_categories[0]
    # Create recurring budget for current month
    create_resp = await client.post(
        "/api/budgets",
        json={
            "category_id": str(cat.id),
            "amount": 1000,
            "month": _current_month_str(),
            "is_recurring": True,
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == 201

    # Check it appears for next month
    list_resp = await client.get(
        "/api/budgets",
        params={"month": _next_month_str()},
        headers=auth_headers,
    )
    assert list_resp.status_code == 200
    budgets = list_resp.json()
    cat_budgets = [b for b in budgets if b["category_id"] == str(cat.id)]
    assert len(cat_budgets) == 1
    assert float(cat_budgets[0]["amount"]) == 1000.0
    assert cat_budgets[0]["is_recurring"] is True


@pytest.mark.asyncio
async def test_override_wins_over_recurring(client, auth_headers, test_categories):
    """A month-specific override should take priority over a recurring budget."""
    cat = test_categories[1]
    # Create recurring
    await client.post(
        "/api/budgets",
        json={
            "category_id": str(cat.id),
            "amount": 500,
            "month": _current_month_str(),
            "is_recurring": True,
        },
        headers=auth_headers,
    )

    next_month = _next_month_str()

    # Create override for next month
    await client.post(
        "/api/budgets",
        json={
            "category_id": str(cat.id),
            "amount": 750,
            "month": next_month,
            "is_recurring": False,
        },
        headers=auth_headers,
    )

    # List for next month — override should win
    list_resp = await client.get(
        "/api/budgets",
        params={"month": next_month},
        headers=auth_headers,
    )
    budgets = list_resp.json()
    cat_budgets = [b for b in budgets if b["category_id"] == str(cat.id)]
    assert len(cat_budgets) == 1
    assert float(cat_budgets[0]["amount"]) == 750.0
    assert cat_budgets[0]["is_recurring"] is False


@pytest.mark.asyncio
async def test_recurring_not_visible_before_effective_month(client, auth_headers, test_categories):
    """A recurring budget should NOT appear for months before its effective-from month."""
    cat = test_categories[0]
    # Create recurring budget effective from next month
    await client.post(
        "/api/budgets",
        json={
            "category_id": str(cat.id),
            "amount": 800,
            "month": _next_month_str(),
            "is_recurring": True,
        },
        headers=auth_headers,
    )

    # Should not appear for current month
    list_resp = await client.get(
        "/api/budgets",
        params={"month": _current_month_str()},
        headers=auth_headers,
    )
    budgets = list_resp.json()
    cat_budgets = [b for b in budgets if b["category_id"] == str(cat.id)]
    assert len(cat_budgets) == 0


@pytest.mark.asyncio
async def test_budget_comparison_resolves_recurring(client, auth_headers, test_categories, test_transactions):
    """Budget comparison endpoint should resolve recurring budgets correctly."""
    cat = test_categories[0]  # Alimentação — has spending in test_transactions

    # Create recurring budget
    await client.post(
        "/api/budgets",
        json={
            "category_id": str(cat.id),
            "amount": 200,
            "month": _current_month_str(),
            "is_recurring": True,
        },
        headers=auth_headers,
    )

    # Check comparison
    comp_resp = await client.get(
        "/api/budgets/comparison",
        params={"month": _current_month_str()},
        headers=auth_headers,
    )
    assert comp_resp.status_code == 200
    comparisons = comp_resp.json()
    cat_comp = [c for c in comparisons if c["category_id"] == str(cat.id)]
    assert len(cat_comp) == 1
    assert float(cat_comp[0]["budget_amount"]) == 200.0
    assert cat_comp[0]["is_recurring"] is True


@pytest.mark.asyncio
async def test_update_recurring_creates_new_record(client, auth_headers, test_categories):
    """Editing a recurring budget from a later month creates a new record; old one stays."""
    cat = test_categories[0]

    # Create recurring budget for current month
    create_resp = await client.post(
        "/api/budgets",
        json={
            "category_id": str(cat.id),
            "amount": 400,
            "month": _current_month_str(),
            "is_recurring": True,
        },
        headers=auth_headers,
    )
    original_id = create_resp.json()["id"]

    next_month = _next_month_str()

    # Update with a new effective month
    update_resp = await client.patch(
        f"/api/budgets/{original_id}",
        json={"amount": 600, "effective_month": next_month},
        headers=auth_headers,
    )
    assert update_resp.status_code == 200
    new_data = update_resp.json()
    assert new_data["id"] != original_id  # New record created
    assert float(new_data["amount"]) == 600.0
    assert new_data["is_recurring"] is True

    # Current month should still show original amount
    list_resp = await client.get(
        "/api/budgets",
        params={"month": _current_month_str()},
        headers=auth_headers,
    )
    cat_budgets = [b for b in list_resp.json() if b["category_id"] == str(cat.id)]
    assert len(cat_budgets) == 1
    assert float(cat_budgets[0]["amount"]) == 400.0

    # Next month should show new amount
    list_resp2 = await client.get(
        "/api/budgets",
        params={"month": next_month},
        headers=auth_headers,
    )
    cat_budgets2 = [b for b in list_resp2.json() if b["category_id"] == str(cat.id)]
    assert len(cat_budgets2) == 1
    assert float(cat_budgets2[0]["amount"]) == 600.0


@pytest.mark.asyncio
async def test_delete_recurring_previous_takes_effect(client, auth_headers, test_categories):
    """Deleting a newer recurring budget makes an older one take effect again."""
    cat = test_categories[1]

    # Create recurring budget for current month
    await client.post(
        "/api/budgets",
        json={
            "category_id": str(cat.id),
            "amount": 100,
            "month": _current_month_str(),
            "is_recurring": True,
        },
        headers=auth_headers,
    )

    next_month = _next_month_str()

    # Create newer recurring for next month
    create_resp = await client.post(
        "/api/budgets",
        json={
            "category_id": str(cat.id),
            "amount": 200,
            "month": next_month,
            "is_recurring": True,
        },
        headers=auth_headers,
    )
    newer_id = create_resp.json()["id"]

    # Next month should show 200
    list_resp = await client.get(
        "/api/budgets",
        params={"month": next_month},
        headers=auth_headers,
    )
    cat_budgets = [b for b in list_resp.json() if b["category_id"] == str(cat.id)]
    assert float(cat_budgets[0]["amount"]) == 200.0

    # Delete the newer one
    del_resp = await client.delete(f"/api/budgets/{newer_id}", headers=auth_headers)
    assert del_resp.status_code == 204

    # Next month should now fall back to 100
    list_resp2 = await client.get(
        "/api/budgets",
        params={"month": next_month},
        headers=auth_headers,
    )
    cat_budgets2 = [b for b in list_resp2.json() if b["category_id"] == str(cat.id)]
    assert len(cat_budgets2) == 1
    assert float(cat_budgets2[0]["amount"]) == 100.0


@pytest.mark.asyncio
async def test_group_budgets_api(client, auth_headers, test_categories):
    """A budget is for a category or a group; the scope picks the list, and
    the two never mix."""
    group_resp = await client.post(
        "/api/category-groups",
        json={"name": "Moradia", "icon": "house", "color": "#8b5cf6"},
        headers=auth_headers,
    )
    assert group_resp.status_code == 201
    group_id = group_resp.json()["id"]

    group_budget = await client.post(
        "/api/budgets",
        json={"group_id": group_id, "amount": 2000.0, "month": _current_month_str()},
        headers=auth_headers,
    )
    assert group_budget.status_code == 201
    assert group_budget.json()["group_id"] == group_id
    assert group_budget.json()["category_id"] is None

    await client.post(
        "/api/budgets",
        json={"category_id": str(test_categories[0].id), "amount": 500.0, "month": _current_month_str()},
        headers=auth_headers,
    )

    group_list = await client.get(
        f"/api/budgets?month={_current_month_str()}&scope=group", headers=auth_headers
    )
    assert [b["group_id"] for b in group_list.json()] == [group_id]
    assert all(b["category_id"] is None for b in group_list.json())

    category_list = await client.get(
        f"/api/budgets?month={_current_month_str()}&scope=category", headers=auth_headers
    )
    assert all(b["category_id"] is not None for b in category_list.json())
    assert group_id not in {b.get("group_id") for b in category_list.json()}

    both = await client.post(
        "/api/budgets",
        json={
            "group_id": group_id,
            "category_id": str(test_categories[0].id),
            "amount": 1.0,
            "month": _current_month_str(),
        },
        headers=auth_headers,
    )
    assert both.status_code == 422

    comparison = await client.get(
        f"/api/budgets/comparison?month={_current_month_str()}&scope=group",
        headers=auth_headers,
    )
    assert comparison.status_code == 200
    row = next((r for r in comparison.json() if r.get("group_id") == group_id), None)
    if row is not None:
        assert float(row["budget_amount"]) == 2000.0
