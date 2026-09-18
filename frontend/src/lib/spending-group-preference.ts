export type SpendingGroupBy = 'category' | 'group'

//: Same storage the dashboard uses for its other per-browser preferences
//: (page size, and so on). Kept in one place so the key is never mistyped
//: in two files.
const KEY = 'securo.dashboard.spendingGroupBy'

/** The view the home should open in. Anything unexpected means categories. */
export function readSpendingGroupBy(): SpendingGroupBy {
  try {
    return localStorage.getItem(KEY) === 'group' ? 'group' : 'category'
  } catch {
    // Storage can be unavailable (private mode, hardened browsers); the
    // default is a perfectly good answer.
    return 'category'
  }
}

export function writeSpendingGroupBy(value: SpendingGroupBy): void {
  try {
    localStorage.setItem(KEY, value)
  } catch {
    // Not being able to remember the choice must not break the choice.
  }
}
