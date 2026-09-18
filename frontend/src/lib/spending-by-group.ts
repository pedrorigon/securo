import type { SpendingByCategory } from '@/types'

/**
 * A budget row, reduced to what the group rollup needs. Kept structural so
 * the aggregation can be tested without the budgets API.
 */
export type BudgetLike = {
  /** Null on a group-scope row, which the category budget map ignores. */
  category_id: string | null
  budget_amount: number | string | null
  projected_prev_month_amount?: number | string | null
}

/**
 * A group that has a budget of its own. When present it replaces the sum of
 * the group's category budgets — never both at once — and its previous-month
 * reference is used for the badge.
 */
export type GroupBudgetOverride = {
  budget_amount: number
  prev: number | null
}

export type GroupSpendingRow = {
  group_id: string | null
  group_name: string | null
  group_icon: string | null
  group_color: string | null
  actual: number
  budget_amount: number | null
  percentage_used: number | null
  momPct: number | null
  category_ids: string[]
}

/**
 * Roll the per-category spending rows up to their groups.
 *
 * The exact same arithmetic the category view shows, applied to a group:
 * `actual` is the sum of each category's all-in amount (settled plus forecast,
 * which is what the widget and its drill-down display), the budget line is
 * the sum of the budgets the group's categories have (no budget anywhere
 * means no line, exactly like a category without one), and the month-over-month
 * badge sums the same previous-month amounts the category view reads.
 *
 * "Sem categoria" rows stay out — they are in neither a category nor a group
 * on this widget today, and this function must not change what the block
 * totals. A real category without a group lands in the null-group bucket so
 * its money stays visible.
 */
export function aggregateSpendingByGroup(
  spending: SpendingByCategory[],
  budgets: BudgetLike[] | undefined,
  sortDesc: boolean,
  categoryIdsByGroup?: Map<string, string[]>,
  groupBudgets?: Map<string, GroupBudgetOverride>,
): GroupSpendingRow[] {
  const budgetByCategory = new Map(
    (budgets ?? [])
      .filter((budget) => budget.category_id !== null)
      .map((budget) => [budget.category_id as string, budget]),
  )
  const rows = new Map<string, GroupSpendingRow & { prev: number; hasBudget: boolean }>()

  for (const item of spending) {
    if (item.category_id === null) continue

    const key = item.group_id ?? '__none__'
    let row = rows.get(key)
    if (!row) {
      row = {
        group_id: item.group_id,
        group_name: item.group_name,
        group_icon: item.group_icon,
        group_color: item.group_color,
        actual: 0,
        budget_amount: null,
        percentage_used: null,
        momPct: null,
        category_ids: [],
        prev: 0,
        hasBudget: false,
      }
      rows.set(key, row)
    }

    row.actual += item.projected_total
    row.category_ids.push(item.category_id)

    const budget = budgetByCategory.get(item.category_id)
    if (budget) {
      row.hasBudget = true
      row.budget_amount = (row.budget_amount ?? 0) + Number(budget.budget_amount ?? 0)
      row.prev += Number(budget.projected_prev_month_amount ?? 0)
    }
  }

  const result: GroupSpendingRow[] = []
  for (const row of rows.values()) {
    let momPct: number | null = null
    if (row.prev > 0) {
      momPct = ((row.actual - row.prev) / row.prev) * 100
    } else if (row.actual > 0) {
      momPct = 100
    }

    let categoryIds = row.category_ids
    if (row.group_id && categoryIdsByGroup) {
      const extra = categoryIdsByGroup.get(row.group_id) ?? []
      categoryIds = [...new Set([...categoryIds, ...extra])]
    }

    result.push({
      group_id: row.group_id,
      group_name: row.group_name,
      group_icon: row.group_icon,
      group_color: row.group_color,
      actual: row.actual,
      budget_amount: row.hasBudget ? row.budget_amount : null,
      percentage_used:
        row.hasBudget && row.budget_amount
          ? (row.actual / row.budget_amount) * 100
          : null,
      momPct,
      category_ids: categoryIds,
    })
  }

  if (groupBudgets) {
    for (const row of result) {
      if (!row.group_id) continue
      const override = groupBudgets.get(row.group_id)
      if (!override) continue
      row.budget_amount = override.budget_amount
      row.percentage_used =
        override.budget_amount > 0
          ? (row.actual / override.budget_amount) * 100
          : null
      row.momPct =
        override.prev != null && override.prev > 0
          ? ((row.actual - override.prev) / override.prev) * 100
          : row.actual > 0
            ? 100
            : null
    }
  }

  return result.sort((a, b) =>
    sortDesc ? b.actual - a.actual : a.actual - b.actual,
  )
}
