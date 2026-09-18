export type SpendingForecast = {
  spent: number
  received: number
  balance: number
  savingsRate: number | null
}

/**
 * The month's closing picture: what is expected to be spent and received
 * (settled so far plus pending and planned entries), the balance between
 * them and the share of the income that survives it.
 *
 * Null when there is nothing to say — no spending and no income — so the
 * caller can stay quiet instead of announcing a zero. The rate is null when
 * there is no income to take a share of; dividing by it would invent one.
 */
export function spendingForecast(
  projectedIncome: number,
  projectedExpenses: number,
): SpendingForecast | null {
  const spent = Math.max(projectedExpenses, 0)
  const received = Math.max(projectedIncome, 0)
  if (spent === 0 && received === 0) return null

  const balance = received - spent
  return {
    spent,
    received,
    balance,
    savingsRate: received > 0 ? (balance / received) * 100 : null,
  }
}
