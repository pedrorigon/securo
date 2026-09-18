import { describe, expect, it } from 'vitest'

import { nextBusinessDay, stateForPlaceholder } from '@/lib/recurring-state'
import type { Transaction } from '@/types'

const placeholder = (overrides: Partial<Transaction> = {}): Transaction =>
  ({
    id: 'tx',
    description: 'Assinatura',
    amount: 20,
    currency: 'USD',
    date: '2026-09-15',
    type: 'debit',
    source: 'recurring',
    status: 'pending',
    external_id: null,
    ...overrides,
  }) as Transaction

// Thursday, 2026-09-17.
const TODAY = new Date(2026, 8, 17, 15, 0, 0)

describe('nextBusinessDay', () => {
  it('skips the weekend', () => {
    expect(nextBusinessDay(new Date(2026, 8, 17))).toEqual(new Date(2026, 8, 18))
    expect(nextBusinessDay(new Date(2026, 8, 18))).toEqual(new Date(2026, 8, 21))
    expect(nextBusinessDay(new Date(2026, 8, 19))).toEqual(new Date(2026, 8, 21))
  })
})

describe('stateForPlaceholder', () => {
  it('marks yesterday overdue and today not yet', () => {
    expect(stateForPlaceholder(placeholder({ date: '2026-09-16' }), TODAY)).toBe('overdue')
    expect(stateForPlaceholder(placeholder({ date: '2026-09-17' }), TODAY)).toBe('forecast')
    expect(stateForPlaceholder(placeholder({ date: '2026-09-18' }), TODAY)).toBe('forecast')
  })

  it('marks a month that ended without the charge as missed', () => {
    expect(stateForPlaceholder(placeholder({ date: '2026-08-31' }), TODAY)).toBe('missed')
  })

  it('ignores rows that are not unmatched placeholders', () => {
    expect(
      stateForPlaceholder(placeholder({ external_id: 'ext-1' }), TODAY),
    ).toBeNull()
    expect(stateForPlaceholder(placeholder({ status: 'posted' }), TODAY)).toBeNull()
    expect(stateForPlaceholder(placeholder({ source: 'sync' }), TODAY)).toBeNull()
    expect(stateForPlaceholder(placeholder({ date: '2026-08-31', source: 'manual' }), TODAY)).toBeNull()
  })
})
