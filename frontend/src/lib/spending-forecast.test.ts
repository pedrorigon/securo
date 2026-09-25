import { describe, expect, it } from 'vitest'

import { spendingForecast } from '@/lib/spending-forecast'

describe('spendingForecast', () => {
  it('closes the month with the real numbers from September', () => {
    const forecast = spendingForecast(6869.78, 5359.78)
    expect(forecast).not.toBeNull()
    expect(forecast!.spent).toBeCloseTo(5359.78)
    expect(forecast!.received).toBeCloseTo(6869.78)
    expect(forecast!.invested).toBe(0)
    expect(forecast!.balance).toBeCloseTo(1510)
    expect(forecast!.savingsRate).toBeCloseTo(21.98, 1)
  })

  it('names investments separately without calling them spending', () => {
    // October: received 6.430,02, spent 4.393,85, invested 2.000,00.
    const forecast = spendingForecast(6430.02, 4393.85, 2000)
    expect(forecast!.invested).toBeCloseTo(2000)
    // Spending plus investments is what the movements panel shows...
    expect(forecast!.spent + forecast!.invested).toBeCloseTo(6393.85)
    // ...and the balance is what actually stays in the accounts, so the
    // investment comes out of it like any other money that left.
    expect(forecast!.balance).toBeCloseTo(36.17)
    // The rate still answers "how much of the income was not consumed":
    // investing is saving, so it is not charged against it.
    expect(forecast!.savingsRate).toBeCloseTo(31.67, 1)
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

  it('still speaks when the month only has an investment planned', () => {
    const forecast = spendingForecast(0, 0, 2000)
    expect(forecast).not.toBeNull()
    expect(forecast!.invested).toBeCloseTo(2000)
    // Cash leaving with nothing arriving leaves the balance negative.
    expect(forecast!.balance).toBeCloseTo(-2000)
    expect(forecast!.savingsRate).toBeNull()
  })
})
