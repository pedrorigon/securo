import { beforeEach, describe, expect, it } from 'vitest'

import {
  readSpendingGroupBy,
  writeSpendingGroupBy,
} from '@/lib/spending-group-preference'

describe('spending group preference', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('defaults to categories when nothing was chosen', () => {
    expect(readSpendingGroupBy()).toBe('category')
  })

  it('remembers the group choice', () => {
    writeSpendingGroupBy('group')
    expect(readSpendingGroupBy()).toBe('group')
  })

  it('remembers a switch back to categories', () => {
    writeSpendingGroupBy('group')
    writeSpendingGroupBy('category')
    expect(readSpendingGroupBy()).toBe('category')
  })

  it('falls back to categories for anything unexpected in storage', () => {
    localStorage.setItem('securo.dashboard.spendingGroupBy', '{"nope":true}')
    expect(readSpendingGroupBy()).toBe('category')
  })
})
