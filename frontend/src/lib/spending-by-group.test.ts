import { describe, expect, it } from 'vitest'

import { aggregateSpendingByGroup } from '@/lib/spending-by-group'
import type { SpendingByCategory } from '@/types'

const category = (
  overrides: Partial<SpendingByCategory> = {},
): SpendingByCategory => ({
  category_id: 'cat-1',
  category_name: 'Aluguel',
  category_icon: 'house',
  category_color: '#000',
  total: 100,
  projected_total: 100,
  percentage: 50,
  group_id: 'group-home',
  group_name: 'Moradia',
  group_icon: 'house',
  group_color: '#8b5cf6',
  ...overrides,
})

describe('aggregateSpendingByGroup', () => {
  it('sums categories into their group and keeps the group identity', () => {
    const rows = aggregateSpendingByGroup(
      [
        category({ category_id: 'a', projected_total: 700 }),
        category({
          category_id: 'b',
          projected_total: 300,
          group_id: 'group-home',
          group_name: 'Moradia',
        }),
        category({
          category_id: 'c',
          projected_total: 50,
          group_id: 'group-pets',
          group_name: 'Pets',
          group_icon: 'cat',
          group_color: '#00aaff',
        }),
      ],
      undefined,
      true,
    )

    expect(rows).toHaveLength(2)
    expect(rows[0].group_id).toBe('group-home')
    expect(rows[0].actual).toBeCloseTo(1000)
    expect(rows[0].category_ids).toEqual(['a', 'b'])
    expect(rows[1].group_name).toBe('Pets')
    expect(rows[1].actual).toBeCloseTo(50)
  })

  it('sums the budgets and previous-month amounts of the group', () => {
    const rows = aggregateSpendingByGroup(
      [
        category({ category_id: 'a', projected_total: 700 }),
        category({ category_id: 'b', projected_total: 300 }),
      ],
      [
        { category_id: 'a', budget_amount: '400', projected_prev_month_amount: '500' },
        { category_id: 'b', budget_amount: '100', projected_prev_month_amount: '250' },
      ],
      true,
    )

    expect(rows[0].budget_amount).toBeCloseTo(500)
    expect(rows[0].percentage_used).toBeCloseTo(200)
    // (1000 - 750) / 750 * 100
    expect(rows[0].momPct).toBeCloseTo(33.333, 2)
  })

  it('shows no budget line when nobody in the group has one', () => {
    const rows = aggregateSpendingByGroup(
      [category({ projected_total: 42 })],
      undefined,
      true,
    )
    expect(rows[0].budget_amount).toBeNull()
    expect(rows[0].percentage_used).toBeNull()
    // Same rule the category view applies: no previous reference, spending
    // present, so the badge reports +100%.
    expect(rows[0].momPct).toBeCloseTo(100)
  })

  it('keeps uncategorized rows out and ungrouped categories visible', () => {
    const rows = aggregateSpendingByGroup(
      [
        category({ category_id: null, group_id: null, projected_total: 999 }),
        category({
          category_id: 'loose',
          group_id: null,
          group_name: null,
          group_icon: null,
          group_color: null,
          projected_total: 40,
        }),
      ],
      undefined,
      true,
    )

    expect(rows).toHaveLength(1)
    expect(rows[0].group_id).toBeNull()
    expect(rows[0].actual).toBeCloseTo(40)
  })

  it('unions the group categories from the full category list for the drill-down', () => {
    const rows = aggregateSpendingByGroup(
      [category({ category_id: 'a', projected_total: 10 })],
      undefined,
      true,
      new Map([['group-home', ['a', 'b', 'c']]]),
    )
    expect(rows[0].category_ids).toEqual(['a', 'b', 'c'])
  })

  it('a group budget replaces the summed category budgets', () => {
    const rows = aggregateSpendingByGroup(
      [category({ category_id: 'a', projected_total: 700 })],
      [
        { category_id: 'a', budget_amount: '400', projected_prev_month_amount: '500' },
      ],
      true,
      undefined,
      new Map([['group-home', { budget_amount: 1000, prev: 800 }]]),
    )

    expect(rows[0].budget_amount).toBeCloseTo(1000)
    expect(rows[0].percentage_used).toBeCloseTo(70)
    // (700 - 800) / 800 * 100
    expect(rows[0].momPct).toBeCloseTo(-12.5)
  })

  it('falls back to the summed category budgets when the group has none', () => {
    const rows = aggregateSpendingByGroup(
      [category({ category_id: 'a', projected_total: 700 })],
      [
        { category_id: 'a', budget_amount: '400', projected_prev_month_amount: '500' },
      ],
      true,
      undefined,
      new Map(),
    )

    expect(rows[0].budget_amount).toBeCloseTo(400)
    expect(rows[0].percentage_used).toBeCloseTo(175)
  })

  it('sorts ascending when asked', () => {
    const rows = aggregateSpendingByGroup(
      [
        category({ category_id: 'a', projected_total: 10, group_id: 'g1', group_name: 'G1' }),
        category({ category_id: 'b', projected_total: 90, group_id: 'g2', group_name: 'G2' }),
      ],
      undefined,
      false,
    )
    expect(rows.map((row) => row.group_id)).toEqual(['g1', 'g2'])
  })
})
