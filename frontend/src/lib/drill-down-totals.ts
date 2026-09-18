/**
 * A drill-down row, reduced to what the footer totals need. Kept structural
 * rather than importing the panel's DisplayItem so the arithmetic can be
 * tested without standing up the panel.
 */
export type DrillDownTotalsItem = {
  amount: number
  amountPrimary: number | null
  currency: string
  isPending: boolean
  isProjected: boolean
  /**
   * An occurrence from a month that ended without the charge. Listed so a
   * person can see and dismiss it, but excluded from every total: it is not
   * money that was spent, and counting it would answer a different question
   * than the one the footer asks.
   */
  isMissed?: boolean
}

export type DrillDownTotals = {
  absTotal: number
  postedTotal: number
  pendingTotal: number
  projectedTotal: number
  missedTotal: number
}

/**
 * Split the rows the panel is showing into the buckets the footer reports.
 *
 * Every counted row lands in exactly one of posted, pending or projected, so
 * the three always add back up to `absTotal`: a row the user can see in the
 * list has to be inside it, and one the panel shows only to be dismissed
 * (`isMissed`) is reported separately instead. Bucketing on the row's own
 * `isPending` and `isProjected` flags, rather than on a persisted status, is
 * what keeps projections from falling through the gaps: they have no
 * transaction behind them, so a status test can never place them.
 *
 * Foreign-currency rows are converted through `amountPrimary`; when that is
 * missing the row is skipped rather than added as if its raw amount were
 * already in the user's currency. This matches how `get_summary` computes
 * `monthly_*_primary` on the backend.
 */
export function sumDrillDownTotals(
  items: DrillDownTotalsItem[],
  userCurrency: string,
): DrillDownTotals {
  return items.reduce<DrillDownTotals>(
    (totals, item) => {
      const amount = item.currency === userCurrency
        ? Math.abs(item.amount)
        : item.amountPrimary != null
          ? Math.abs(item.amountPrimary)
          : 0

      if (item.isMissed) {
        totals.missedTotal += amount
        return totals
      }

      totals.absTotal += amount
      if (item.isProjected) totals.projectedTotal += amount
      else if (item.isPending) totals.pendingTotal += amount
      else totals.postedTotal += amount
      return totals
    },
    { absTotal: 0, postedTotal: 0, pendingTotal: 0, projectedTotal: 0, missedTotal: 0 },
  )
}
