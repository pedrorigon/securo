import { describe, expect, it } from 'vitest'

import { spendingForecast } from '@/lib/spending-forecast'

describe('spendingForecast', () => {
  it('closes the month with the real numbers from September', () => {
    const forecast = spendingForecast(6869.78, 5359.78)
    expect(forecast).not.toBeNull()
    expect(forecast!.spent).toBeCloseTo(5359.78)
    expect(forecast!.received).toBeCloseTo(6869.78)
    expect(forecast!.balance).toBeCloseTo(1510)
    expect(forecast!.savingsRate).toBeCloseTo(21.98, 1)
  })

  it('reports a negative balance and rate when spending wins', () => {
    const forecast = spendingForecast(1000, 1300)
    expect(forecast!.balance).toBeCloseTo(-300)
    expect(forecast!.savingsRate).toBeCloseTo(-30)
  })

  it('has no rate when there is no income to take a share of', () => {
    const forecast = spendingForecast(0, 200)
    expect(forecast!.balance).toBeCloseTo(-200)
    expect(forecast!.savingsRate).toBeNull()
  })

  it('stays quiet when there is nothing to say', () => {
    expect(spendingForecast(0, 0)).toBeNull()
  })

  it('never announces negative amounts as totals', () => {
    const forecast = spendingForecast(-50, -20)
    expect(forecast).toBeNull()
  })
})
