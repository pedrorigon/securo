import type { RecurringProjectionState, Transaction } from '@/types'

function parseLocalDate(value: string): Date {
  return new Date(`${value}T00:00:00`)
}

/** The next weekday after `when`. Weekends skipped, holidays not. */
export function nextBusinessDay(when: Date): Date {
  const next = new Date(when)
  do {
    next.setDate(next.getDate() + 1)
  } while (next.getDay() === 0 || next.getDay() === 6)
  return next
}

/**
 * Where a materialized placeholder stands, for a row that came back from the
 * transactions endpoint.
 *
 * An unmatched placeholder is a generated recurring row that never received a
 * real charge: it still carries `source === 'recurring'`, has no external id
 * and is pending. Past months are "missed" — the backend only lets those rows
 * through when asked (`include_missed`), which is why the drill-down can show
 * them at all. Returns null for everything else: a matched charge, a real
 * pending bank row, or anything already posted.
 */
export function stateForPlaceholder(
  tx: Transaction,
  today: Date = new Date(),
): RecurringProjectionState | null {
  const unmatched =
    tx.source === 'recurring' && !tx.external_id && tx.status === 'pending'
  if (!unmatched) return null

  const date = parseLocalDate(tx.date)
  const todayStart = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  const monthStart = new Date(todayStart.getFullYear(), todayStart.getMonth(), 1)

  if (date < monthStart) return 'missed'
  if (nextBusinessDay(date) <= todayStart) return 'overdue'
  return 'forecast'
}
