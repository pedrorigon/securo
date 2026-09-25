export type SpendingForecast = {
  spent: number
  received: number
  /** Cash leaving for the person's own other accounts (an investment
      contribution): not spending, but part of what the panel shows. */
  invested: number
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
  projectedInvestments = 0,
): SpendingForecast | null {
  const spent = Math.max(projectedExpenses, 0)
  const received = Math.max(projectedIncome, 0)
  const invested = Math.max(projectedInvestments, 0)
  if (spent === 0 && received === 0 && invested === 0) return null

  // The balance is cash: everything that left — including the investment —
  // subtracted from everything that arrived, which is what the person will
  // actually find in their accounts. The savings rate asks a different
  // question ("how much of the income was not consumed?") and keeps the
  // P&L shape: money put into investments was saved, not spent, so it still
  // counts toward it — the same reading the savings-rate card uses.
  const balance = received - spent - invested
  return {
    spent,
    received,
    invested,
    balance,
    savingsRate: received > 0 ? ((received - spent) / received) * 100 : null,
  }
}
