import { useTranslation } from 'react-i18next'

import type { RecurringProjectionState } from '@/types'

const STYLES: Record<RecurringProjectionState, string> = {
  // Violet: an ordinary forecast, ahead or due today.
  forecast:
    'border-violet-200 bg-violet-50 text-violet-700 dark:border-violet-900 dark:bg-violet-950/40 dark:text-violet-300',
  // Red: the expected charge is late and the month is still open.
  overdue:
    'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300',
  // Black: the month ended without the charge. Shown only where a person
  // went looking (the drill-down), never inside a total.
  missed:
    'border-neutral-300 bg-neutral-100 text-neutral-800 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-200',
}

const LABEL_KEYS: Record<RecurringProjectionState, string> = {
  forecast: 'transactions.projected',
  overdue: 'transactions.overdue',
  missed: 'transactions.missed',
}

/** Canonical badge for a virtual transaction projection, per state. */
export function ProjectedTransactionBadge({
  state = 'forecast',
}: {
  state?: RecurringProjectionState
}) {
  const { t } = useTranslation()

  return (
    <span
      className={`inline-flex items-center rounded-full border px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wide shrink-0 ${STYLES[state]}`}
    >
      {t(LABEL_KEYS[state])}
    </span>
  )
}
