import React, { useMemo, useState } from 'react'
import { getAccountName, sortAccountsByDisplayName } from '@/lib/account-utils'
import { useTranslation } from 'react-i18next'
import { useDisplayLocale, useDateLocale } from '@/hooks/use-display-locale'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { categories as categoriesApi, categoryGroups as categoryGroupsApi, recurring as recurringApi, accounts as accountsApi, currencies as currenciesApi, rules as rulesApi } from '@/lib/api'
import { extractApiError } from '@/lib/api-errors'
import { localDateString } from '@/lib/date-utils'
import { invalidateFinancialQueries } from '@/lib/invalidate-queries'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { DeleteConfirmationDialog } from '@/components/delete-confirmation-dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import type { Category, CategoryGroup, RecurringMatchRule, RecurringTransaction, Rule } from '@/types'
import { Pencil, Trash2, Plus, RefreshCw, Info, ListFilter } from 'lucide-react'
import { cn } from '@/lib/utils'
import { PageHeader } from '@/components/page-header'
import { CategorySelect } from '@/components/category-select'
import { DatePickerInput } from '@/components/ui/date-picker-input'
import { usePrivacyMode } from '@/hooks/use-privacy-mode'
import { useAuth } from '@/contexts/auth-context'
import { useWorkspace } from '@/contexts/workspace-context'
import { formatCurrency } from '@/lib/format'

const TH = 'text-xs font-medium text-muted-foreground py-3'

/**
 * What the recurring form decided about its identification rule. Kept as a
 * value the form hands back alongside the recurring, because the association
 * lives on the rule side (one rule can answer for several bills).
 */
type RuleChoice =
  | { type: 'none' }
  | { type: 'existing'; ruleId: string }
  | { type: 'import'; sourceRuleId: string }
  | {
      type: 'new'
      name: string
      patterns: string[]
      excludes: string[]
      searchAccountId?: string
      searchType?: string
      accumulate?: boolean
      accumulateThreshold?: string
    }

function SectionCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-card rounded-xl border border-border shadow-sm overflow-hidden">
      {children}
    </div>
  )
}

function SectionHeader({ title, action }: { title: string; action?: React.ReactNode }) {
  return (
    <div className="px-4 sm:px-5 py-4 border-b border-border flex flex-wrap items-center justify-between gap-2">
      <p className="text-sm font-semibold text-foreground">{title}</p>
      {action}
    </div>
  )
}

export default function RecurringPage() {
  const { t } = useTranslation()

  return (
    <div>
      <PageHeader section={t('recurring.title')} title={t('recurring.title')} />
      <RecurringTab />
    </div>
  )
}

function RecurringTab() {
  const { t } = useTranslation()
  const locale = useDisplayLocale()
  const dateLocale = useDateLocale()
  const { mask } = usePrivacyMode()
  const { user } = useAuth()
  const { canWrite } = useWorkspace()
  const userCurrency = user?.preferences?.currency_display ?? 'USD'
  const queryClient = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<RecurringTransaction | null>(null)
  const [deletingRecurring, setDeletingRecurring] = useState<RecurringTransaction | null>(null)
  const [rulesOpen, setRulesOpen] = useState(false)

  const { data: recurringList } = useQuery({
    queryKey: ['recurring'],
    queryFn: recurringApi.list,
  })

  const { data: matchRules } = useQuery({
    queryKey: ['recurring', 'match-rules'],
    queryFn: recurringApi.matchRules.list,
  })

  const rulesByRecurring = useMemo(() => {
    const index = new Map<string, RecurringMatchRule[]>()
    for (const rule of matchRules ?? []) {
      for (const recurringId of rule.recurring_ids) {
        const list = index.get(recurringId) ?? []
        list.push(rule)
        index.set(recurringId, list)
      }
    }
    return index
  }, [matchRules])

  const { data: categoriesList } = useQuery({
    queryKey: ['categories'],
    queryFn: categoriesApi.list,
  })

  const { data: allCategoriesList } = useQuery({
    queryKey: ['categories', 'management'],
    queryFn: categoriesApi.listIncludingHidden,
    enabled: Boolean(editing?.category_id),
  })

  const { data: categoryGroupsList } = useQuery({
    queryKey: ['categoryGroups'],
    queryFn: categoryGroupsApi.list,
  })

  const { data: accountsList } = useQuery({
    queryKey: ['accounts'],
    queryFn: () => accountsApi.list(),
  })

  // The Rules screen's own rules: reused as identification by choosing one
  // in the recurring form, so the same sentence never has to be written twice.
  const { data: normalRules } = useQuery({
    queryKey: ['rules'],
    queryFn: rulesApi.list,
  })

  const applyRuleChoice = async (recurringId: string, choice: RuleChoice) => {
    const current = matchRules ?? []
    const attached = current.filter((rule) => rule.recurring_ids.includes(recurringId))

    const detachFromOthers = async (keepIds: Set<string>) => {
      for (const rule of attached) {
        if (keepIds.has(rule.id)) continue
        await recurringApi.matchRules.update(rule.id, {
          recurring_ids: rule.recurring_ids.filter((id) => id !== recurringId),
        })
      }
    }
    const attachTo = async (rule: RecurringMatchRule) => {
      if (!rule.recurring_ids.includes(recurringId)) {
        await recurringApi.matchRules.update(rule.id, {
          recurring_ids: [...rule.recurring_ids, recurringId],
        })
      }
    }

    if (choice.type === 'none') {
      await detachFromOthers(new Set())
      return
    }
    if (choice.type === 'existing') {
      const rule = current.find((candidate) => candidate.id === choice.ruleId)
      if (rule) await attachTo(rule)
      await detachFromOthers(new Set(rule ? [rule.id] : []))
      return
    }
    if (choice.type === 'import') {
      const existing = current.find(
        (candidate) => candidate.source_rule_id === choice.sourceRuleId,
      )
      if (existing) {
        await attachTo(existing)
        await detachFromOthers(new Set([existing.id]))
      } else {
        await recurringApi.matchRules.create({
          source_rule_id: choice.sourceRuleId,
          recurring_ids: [recurringId],
        })
        await detachFromOthers(new Set())
      }
      return
    }
    await recurringApi.matchRules.create({
      name: choice.name,
      patterns: choice.patterns,
      excludes: choice.excludes,
      recurring_ids: [recurringId],
      search_account_id: choice.searchAccountId || null,
      search_type: choice.searchType || null,
      accumulate: choice.accumulate ?? false,
      accumulate_threshold: choice.accumulateThreshold || null,
    })
    await detachFromOthers(new Set())
  }

  const refreshAfterRuleChange = () => {
    queryClient.invalidateQueries({ queryKey: ['recurring', 'match-rules'] })
    queryClient.invalidateQueries({ queryKey: ['recurring'] })
    invalidateFinancialQueries(queryClient)
  }

  const createMutation = useMutation({
    mutationFn: ({ data }: { data: Partial<RecurringTransaction>; ruleChoice: RuleChoice }) =>
      recurringApi.create(data),
    onSuccess: async (created, variables) => {
      invalidateFinancialQueries(queryClient)
      queryClient.invalidateQueries({ queryKey: ['recurring'] })
      setDialogOpen(false)
      toast.success(t('recurring.created'))
      try {
        await applyRuleChoice(created.id, variables.ruleChoice)
        refreshAfterRuleChange()
      } catch {
        toast.error(t('common.error'))
      }
    },
    onError: () => toast.error(t('common.error')),
  })

  const updateMutation = useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string
      data: Partial<RecurringTransaction>
      ruleChoice: RuleChoice
    }) => recurringApi.update(id, data),
    onSuccess: async (_updated, variables) => {
      invalidateFinancialQueries(queryClient)
      queryClient.invalidateQueries({ queryKey: ['recurring'] })
      setDialogOpen(false)
      setEditing(null)
      toast.success(t('recurring.updated'))
      try {
        await applyRuleChoice(variables.id, variables.ruleChoice)
        refreshAfterRuleChange()
      } catch {
        toast.error(t('common.error'))
      }
    },
    onError: () => toast.error(t('common.error')),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => recurringApi.delete(id),
    onSuccess: () => {
      invalidateFinancialQueries(queryClient)
      queryClient.invalidateQueries({ queryKey: ['recurring'] })
      setDeletingRecurring(null)
      toast.success(t('recurring.deleted'))
    },
    onError: (err: unknown) => {
      toast.error(extractApiError(err, t('common.error')))
    },
  })

  const generateMutation = useMutation({
    mutationFn: () => recurringApi.generate(),
    onSuccess: (data) => {
      invalidateFinancialQueries(queryClient)
      queryClient.invalidateQueries({ queryKey: ['recurring'] })
      toast.success(t('recurring.generated', { count: data.generated }))
    },
    onError: () => toast.error(t('common.error')),
  })

  const frequencyLabel = (f: string) => {
    const map: Record<string, string> = {
      monthly: t('recurring.monthly'),
      quarterly: t('recurring.quarterly'),
      semiannual: t('recurring.semiannual'),
      weekly: t('recurring.weekly'),
      biweekly: t('recurring.biweekly'),
      yearly: t('recurring.yearly'),
    }
    return map[f] ?? f
  }

  return (
    <>
      <SectionCard>
        <SectionHeader
          title={t('recurring.title')}
          action={
            canWrite ? (
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-1.5 h-8"
                  onClick={() => setRulesOpen(true)}
                >
                  <ListFilter size={12} />
                  <span>{t('recurring.rules')}</span>
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-1.5 h-8"
                  onClick={() => generateMutation.mutate()}
                  disabled={generateMutation.isPending}
                >
                  <RefreshCw size={12} />
                  <span className="hidden sm:inline">{t('recurring.generatePending')}</span>
                </Button>
                <Button size="sm" className="gap-1.5 h-8" onClick={() => { setEditing(null); setDialogOpen(true) }}>
                  <Plus size={13} /> <span className="hidden sm:inline">{t('recurring.add')}</span>
                </Button>
              </div>
            ) : undefined
          }
        />
        {recurringList && recurringList.length > 0 ? (
          <table className="w-full">
            <thead>
              <tr className="border-b border-border">
                <th className={`${TH} pl-4 sm:pl-5 text-left`}>{t('recurring.description')}</th>
                <th className={`${TH} text-left w-36`}>{t('recurring.amount')}</th>
                <th className={`${TH} text-left w-28 hidden md:table-cell`}>{t('recurring.frequency')}</th>
                <th className={`${TH} text-left w-32 hidden md:table-cell`}>{t('recurring.nextOccurrence')}</th>
                <th className={`${TH} text-left w-24 hidden sm:table-cell`}>{t('recurring.status')}</th>
                {canWrite && <th className={`${TH} pr-4 sm:pr-5 text-right w-24`}>{t('recurring.actions')}</th>}
              </tr>
            </thead>
            <tbody>
              {recurringList.map((rt) => (
                <tr key={rt.id} className="border-b border-border last:border-0 hover:bg-muted transition-colors">
                  <td className="py-3 pl-4 sm:pl-5 text-sm font-medium text-foreground">
                    {rt.description}
                    {(rulesByRecurring.get(rt.id) ?? []).length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1">
                        {(rulesByRecurring.get(rt.id) ?? []).map((rule) => (
                          <button
                            key={rule.id}
                            type="button"
                            onClick={() => setRulesOpen(true)}
                            title={t('recurring.rules')}
                            className="inline-flex items-center gap-1 rounded-full border border-violet-200 bg-violet-50 px-1.5 py-0.5 text-[10px] font-medium text-violet-700 hover:bg-violet-100 transition-colors dark:border-violet-900 dark:bg-violet-950/40 dark:text-violet-300 dark:hover:bg-violet-900/60"
                          >
                            <ListFilter size={9} />
                            {rule.name}
                          </button>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className={`py-3 text-xs sm:text-sm font-bold tabular-nums ${rt.type === 'credit' ? 'text-emerald-600' : 'text-rose-500'}`}>
                    {mask(`${rt.type === 'credit' ? '+' : '−'}${formatCurrency(rt.amount, rt.currency, locale)}`)}
                    {rt.currency !== userCurrency && rt.amount_primary != null && (
                      <div className="flex items-center gap-1 text-[11px] font-normal text-muted-foreground">
                        <span>{mask(formatCurrency(rt.amount_primary, userCurrency, locale))}</span>
                        <span title={t('recurring.fxEstimate', { rate: rt.fx_rate_used?.toFixed(4) ?? '–' })}>
                          <Info size={11} className="inline opacity-60" />
                        </span>
                      </div>
                    )}
                  </td>
                  <td className="py-3 hidden md:table-cell">
                    <span className="text-xs bg-muted text-muted-foreground px-2 py-0.5 rounded-full font-medium">
                      {frequencyLabel(rt.frequency)}
                    </span>
                  </td>
                  <td className="py-3 text-xs text-muted-foreground tabular-nums hidden md:table-cell">
                    {new Date(rt.next_occurrence + 'T00:00:00').toLocaleDateString(dateLocale)}
                  </td>
                  <td className="py-3 hidden sm:table-cell">
                    <span className={cn(
                      'text-[11px] font-semibold px-2 py-0.5 rounded-full border',
                      rt.is_active
                        ? 'bg-emerald-50 text-emerald-600 border-emerald-100'
                        : 'bg-muted text-muted-foreground border-border'
                    )}>
                      {rt.is_active ? t('recurring.active') : t('recurring.inactive')}
                    </span>
                  </td>
                  {canWrite && (
                    <td className="py-3 pr-4 sm:pr-5">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          className="p-1.5 rounded-md text-muted-foreground hover:text-primary hover:bg-primary/5 transition-colors"
                          onClick={() => { setEditing(rt); setDialogOpen(true) }}
                          aria-label={t('common.edit')}
                          title={t('common.edit')}
                        >
                          <Pencil size={13} />
                        </button>
                        <button
                          className="p-1.5 rounded-md text-muted-foreground hover:text-rose-500 hover:bg-rose-50 transition-colors"
                          onClick={() => setDeletingRecurring(rt)}
                          disabled={deleteMutation.isPending}
                          aria-label={t('common.delete')}
                          title={t('common.delete')}
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-sm text-muted-foreground text-center py-10">{t('recurring.empty')}</p>
        )}
      </SectionCard>

      <Dialog open={dialogOpen} onOpenChange={() => { setDialogOpen(false); setEditing(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editing ? t('recurring.edit') : t('recurring.add')}</DialogTitle>
          </DialogHeader>
          <RecurringForm
            key={editing?.id ?? 'new'}
            recurring={editing}
            categories={categoriesList ?? []}
            categoryGroups={categoryGroupsList ?? []}
            currentCategory={allCategoriesList?.find(
              (category) => category.id === editing?.category_id
            )}
            accounts={accountsList ?? []}
            matchRules={matchRules ?? []}
            normalRules={normalRules ?? []}
            onSave={(data, ruleChoice) => {
              if (editing) {
                updateMutation.mutate({ id: editing.id, data, ruleChoice })
              } else {
                createMutation.mutate({ data, ruleChoice })
              }
            }}
            onCancel={() => { setDialogOpen(false); setEditing(null) }}
            loading={createMutation.isPending || updateMutation.isPending}
          />
        </DialogContent>
      </Dialog>

      <DeleteConfirmationDialog
        open={!!deletingRecurring}
        title={t('recurring.confirmDeleteTitle')}
        description={t('recurring.confirmDeleteDescription', { description: deletingRecurring?.description })}
        isPending={deleteMutation.isPending}
        onClose={() => setDeletingRecurring(null)}
        onConfirm={() => deletingRecurring && deleteMutation.mutate(deletingRecurring.id)}
      />

      <MatchRulesDialog
        open={rulesOpen}
        onClose={() => setRulesOpen(false)}
        rules={matchRules ?? []}
        recurringList={recurringList ?? []}
        accounts={accountsList ?? []}
        canWrite={canWrite}
      />
    </>
  )
}

/**
 * The sentence a person writes when the bank's wording never matches the
 * bill's: patterns that identify the charge, terms to exclude, and the bills
 * the rule answers for. Amounts are deliberately absent — a subscription
 * billed in dollars posts in reais with IOF on top.
 */
function MatchRulesDialog({
  open,
  onClose,
  rules,
  recurringList,
  accounts,
  canWrite,
}: {
  open: boolean
  onClose: () => void
  rules: RecurringMatchRule[]
  recurringList: RecurringTransaction[]
  accounts: { id: string; name: string; display_name?: string | null }[]
  canWrite: boolean
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<RecurringMatchRule | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [name, setName] = useState('')
  const [patterns, setPatterns] = useState('')
  const [excludes, setExcludes] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [searchAccountId, setSearchAccountId] = useState('')
  const [searchType, setSearchType] = useState('')
  const [accumulate, setAccumulate] = useState(false)
  const [accumulateThreshold, setAccumulateThreshold] = useState('')
  const [deleting, setDeleting] = useState<RecurringMatchRule | null>(null)

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['recurring', 'match-rules'] })
    queryClient.invalidateQueries({ queryKey: ['recurring'] })
    invalidateFinancialQueries(queryClient)
  }

  const closeForm = () => {
    setFormOpen(false)
    setEditing(null)
  }

  const createMutation = useMutation({
    mutationFn: (payload: {
      name: string
      patterns: string[]
      excludes: string[]
      recurring_ids: string[]
      search_account_id: string | null
      search_type: string | null
      accumulate: boolean
      accumulate_threshold: string | null
    }) => recurringApi.matchRules.create(payload),
    onSuccess: () => {
      refresh()
      closeForm()
      toast.success(t('recurring.ruleCreated'))
    },
    onError: (err: unknown) => toast.error(extractApiError(err, t('common.error'))),
  })

  const updateMutation = useMutation({
    mutationFn: ({
      id,
      ...payload
    }: {
      id: string
      name: string
      patterns: string[]
      excludes: string[]
      recurring_ids: string[]
      search_account_id: string | null
      search_type: string | null
      accumulate: boolean
      accumulate_threshold: string | null
    }) => recurringApi.matchRules.update(id, payload),
    onSuccess: () => {
      refresh()
      closeForm()
      toast.success(t('recurring.ruleUpdated'))
    },
    onError: (err: unknown) => toast.error(extractApiError(err, t('common.error'))),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => recurringApi.matchRules.delete(id),
    onSuccess: () => {
      refresh()
      setDeleting(null)
      toast.success(t('recurring.ruleDeleted'))
    },
    onError: (err: unknown) => toast.error(extractApiError(err, t('common.error'))),
  })

  const splitTerms = (value: string) =>
    value
      .split(',')
      .map((part) => part.trim())
      .filter(Boolean)

  const openCreate = () => {
    setEditing(null)
    setName('')
    setPatterns('')
    setExcludes('')
    setSelected([])
    setSearchAccountId('')
    setSearchType('')
    setAccumulate(false)
    setAccumulateThreshold('')
    setFormOpen(true)
  }

  const openEdit = (rule: RecurringMatchRule) => {
    setEditing(rule)
    setName(rule.name)
    setPatterns(rule.patterns.join(', '))
    setExcludes(rule.excludes.join(', '))
    setSelected(rule.recurring_ids)
    setSearchAccountId(rule.search_account_id ?? '')
    setSearchType(rule.search_type ?? '')
    setAccumulate(rule.accumulate ?? false)
    setAccumulateThreshold(
      rule.accumulate_threshold != null ? String(rule.accumulate_threshold) : '',
    )
    setFormOpen(true)
  }

  const submit = () => {
    const payload = {
      name: name.trim(),
      patterns: splitTerms(patterns),
      excludes: splitTerms(excludes),
      recurring_ids: selected,
      search_account_id: searchAccountId || null,
      search_type: searchType || null,
      accumulate,
      accumulate_threshold: accumulate ? accumulateThreshold || null : null,
    }
    if (!payload.name || payload.patterns.length === 0) {
      toast.error(t('recurring.ruleInvalid'))
      return
    }
    if (editing) {
      updateMutation.mutate({ id: editing.id, ...payload })
    } else {
      createMutation.mutate(payload)
    }
  }

  const descriptionById = new Map(recurringList.map((rt) => [rt.id, rt.description]))
  const accountNameById = new Map(accounts.map((acc) => [acc.id, getAccountName(acc)]))

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(value) => {
          if (!value) {
            onClose()
            closeForm()
          }
        }}
      >
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{t('recurring.rules')}</DialogTitle>
          </DialogHeader>

          <p className="text-xs text-muted-foreground">{t('recurring.rulesHint')}</p>

          {canWrite && !formOpen && (
            <div>
              <Button size="sm" className="gap-1.5 h-8" onClick={openCreate}>
                <Plus size={13} /> {t('recurring.ruleNew')}
              </Button>
            </div>
          )}

          {formOpen && (
            <div className="space-y-3 rounded-lg border border-border p-3">
              <div className="grid gap-1.5">
                <Label htmlFor="rule-name">{t('recurring.ruleName')}</Label>
                <Input
                  id="rule-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="OpenAI"
                />
              </div>
              {editing?.source_rule_id ? (
                <p className="text-xs text-muted-foreground">
                  {t('recurring.ruleBorrowedHint', {
                    name: editing.source_rule_name ?? '',
                  })}
                </p>
              ) : (
                <>
                  <div className="grid gap-1.5">
                    <Label htmlFor="rule-patterns">{t('recurring.rulePatterns')}</Label>
                    <Input
                      id="rule-patterns"
                      value={patterns}
                      onChange={(e) => setPatterns(e.target.value)}
                      placeholder="openai"
                    />
                  </div>
                  <div className="grid gap-1.5">
                    <Label htmlFor="rule-excludes">{t('recurring.ruleExcludes')}</Label>
                    <Input
                      id="rule-excludes"
                      value={excludes}
                      onChange={(e) => setExcludes(e.target.value)}
                      placeholder="iof"
                    />
                  </div>
                </>
              )}
              <div className="grid grid-cols-2 gap-2">
                <div className="grid gap-1.5">
                  <Label htmlFor="rule-search-account">{t('recurring.ruleSearchWhere')}</Label>
                  <select
                    id="rule-search-account"
                    className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-card text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                    value={searchAccountId}
                    onChange={(e) => setSearchAccountId(e.target.value)}
                  >
                    <option value="">{t('recurring.ruleSearchSameAccount')}</option>
                    {accounts.map((acc) => (
                      <option key={acc.id} value={acc.id}>{getAccountName(acc)}</option>
                    ))}
                  </select>
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="rule-search-type">{t('recurring.ruleSearchDirection')}</Label>
                  <select
                    id="rule-search-type"
                    className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-card text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                    value={searchType}
                    onChange={(e) => setSearchType(e.target.value)}
                  >
                    <option value="">{t('recurring.ruleSearchSameType')}</option>
                    <option value="debit">{t('recurring.expense')}</option>
                    <option value="credit">{t('recurring.income')}</option>
                  </select>
                </div>
              </div>
              <p className="text-[11px] text-muted-foreground">{t('recurring.ruleSearchHint')}</p>
              <label className="flex items-start gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={accumulate}
                  onChange={(e) => setAccumulate(e.target.checked)}
                  className="h-4 w-4 mt-0.5 rounded border-border"
                />
                <span className="text-xs text-foreground">
                  {t('recurring.ruleAccumulate')}
                  <span className="block text-[11px] text-muted-foreground">{t('recurring.ruleAccumulateHint')}</span>
                </span>
              </label>
              {accumulate && (
                <div className="grid gap-1.5">
                  <Label htmlFor="rule-threshold">{t('recurring.ruleAccumulateThreshold')}</Label>
                  <Input
                    id="rule-threshold"
                    type="number"
                    step="0.01"
                    value={accumulateThreshold}
                    onChange={(e) => setAccumulateThreshold(e.target.value)}
                    placeholder={t('recurring.ruleAccumulateThresholdPlaceholder')}
                  />
                </div>
              )}
              <div className="grid gap-1.5">
                <Label>{t('recurring.ruleRecurrings')}</Label>
                <div className="max-h-40 overflow-auto rounded-md border border-border p-2 space-y-1">
                  {recurringList.length === 0 ? (
                    <p className="text-xs text-muted-foreground">{t('recurring.empty')}</p>
                  ) : (
                    recurringList.map((rt) => (
                      <label
                        key={rt.id}
                        className="flex items-center gap-2 text-xs text-foreground"
                      >
                        <input
                          type="checkbox"
                          checked={selected.includes(rt.id)}
                          onChange={() =>
                            setSelected((prev) =>
                              prev.includes(rt.id)
                                ? prev.filter((id) => id !== rt.id)
                                : [...prev, rt.id],
                            )
                          }
                        />
                        <span className="truncate">{rt.description}</span>
                      </label>
                    ))
                  )}
                </div>
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="outline" size="sm" onClick={closeForm}>
                  {t('common.cancel')}
                </Button>
                <Button
                  size="sm"
                  onClick={submit}
                  disabled={createMutation.isPending || updateMutation.isPending}
                >
                  {t('common.save')}
                </Button>
              </div>
            </div>
          )}

          <div className="max-h-72 overflow-auto divide-y divide-border rounded-lg border border-border">
            {rules.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">
                {t('recurring.ruleEmpty')}
              </p>
            ) : (
              rules.map((rule) => (
                <div key={rule.id} className="flex items-start gap-3 p-3">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-foreground">{rule.name}</p>
                    {rule.source_rule_id && (
                      <p className="text-[11px] text-violet-600 dark:text-violet-300 mt-0.5">
                        {t('recurring.ruleFromSource', {
                          name: rule.source_rule_name ?? '',
                        })}
                      </p>
                    )}
                    <div className="flex flex-wrap gap-1 mt-1">
                      {rule.patterns.map((pattern) => (
                        <span
                          key={pattern}
                          className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-foreground"
                        >
                          {pattern}
                        </span>
                      ))}
                      {rule.excludes.map((term) => (
                        <span
                          key={term}
                          className="rounded-full bg-rose-50 px-1.5 py-0.5 text-[10px] text-rose-600 dark:bg-rose-950/40 dark:text-rose-300"
                        >
                          {t('recurring.ruleExcept', { term })}
                        </span>
                      ))}
                      {rule.accumulate && (
                        <span className="rounded-full bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
                          {rule.accumulate_threshold != null
                            ? t('recurring.ruleAccumulateChip', {
                                value: rule.accumulate_threshold,
                              })
                            : t('recurring.ruleAccumulateChipDefault')}
                        </span>
                      )}
                      {(rule.search_account_id || rule.search_type) && (
                        <span className="rounded-full bg-sky-50 px-1.5 py-0.5 text-[10px] text-sky-700 dark:bg-sky-950/40 dark:text-sky-300">
                          {t('recurring.ruleSearchChip', {
                            where: rule.search_account_id
                              ? accountNameById.get(rule.search_account_id) ?? '—'
                              : t('recurring.ruleSearchSameAccount'),
                            direction: rule.search_type
                              ? rule.search_type === 'credit'
                                ? t('recurring.income')
                                : t('recurring.expense')
                              : t('recurring.ruleSearchSameType'),
                          })}
                        </span>
                      )}
                    </div>
                    <p className="text-[11px] text-muted-foreground mt-1 truncate">
                      {rule.recurring_ids
                        .map((rid) => descriptionById.get(rid) ?? '—')
                        .join(' · ') || t('recurring.ruleNoRecurrings')}
                    </p>
                  </div>
                  {canWrite && (
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        className="p-1.5 rounded-md text-muted-foreground hover:text-primary hover:bg-primary/5 transition-colors"
                        onClick={() => openEdit(rule)}
                        aria-label={t('common.edit')}
                        title={t('common.edit')}
                      >
                        <Pencil size={13} />
                      </button>
                      <button
                        className="p-1.5 rounded-md text-muted-foreground hover:text-rose-500 hover:bg-rose-50 transition-colors"
                        onClick={() => setDeleting(rule)}
                        aria-label={t('common.delete')}
                        title={t('common.delete')}
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" size="sm" onClick={onClose}>
              {t('common.close')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <DeleteConfirmationDialog
        open={!!deleting}
        title={t('recurring.ruleDeleteTitle')}
        description={t('recurring.ruleDeleteDescription', { name: deleting?.name })}
        isPending={deleteMutation.isPending}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && deleteMutation.mutate(deleting.id)}
      />
    </>
  )
}

function RecurringForm({
  recurring,
  categories,
  categoryGroups,
  currentCategory,
  accounts,
  matchRules,
  normalRules,
  onSave,
  onCancel,
  loading,
}: {
  recurring: RecurringTransaction | null
  categories: Category[]
  categoryGroups: CategoryGroup[]
  currentCategory?: Category
  accounts: { id: string; name: string; display_name?: string | null }[]
  matchRules: RecurringMatchRule[]
  normalRules: Rule[]
  onSave: (data: Partial<RecurringTransaction>, ruleChoice: RuleChoice) => void
  onCancel: () => void
  loading: boolean
}) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const userCurrency = user?.preferences?.currency_display ?? 'USD'
  const sortedAccounts = useMemo(() => sortAccountsByDisplayName(accounts), [accounts])
  const { data: supportedCurrencies } = useQuery({
    queryKey: ['currencies'],
    queryFn: currenciesApi.list,
    staleTime: Infinity,
  })
  const [description, setDescription] = useState(recurring?.description ?? '')
  const [amount, setAmount] = useState(recurring?.amount?.toString() ?? '')
  const [currency, setCurrency] = useState(recurring?.currency ?? userCurrency)
  const [type, setType] = useState<'debit' | 'credit'>(recurring?.type ?? 'debit')
  const [frequency, setFrequency] = useState(recurring?.frequency ?? 'monthly')
  const [weekendAdjustment, setWeekendAdjustment] = useState<RecurringTransaction['weekend_adjustment']>(
    recurring?.weekend_adjustment ?? 'none'
  )
  const [dayOfMonth, setDayOfMonth] = useState(recurring?.day_of_month?.toString() ?? '')
  const [startDate, setStartDate] = useState(recurring?.start_date ?? localDateString())
  const [endDate, setEndDate] = useState(recurring?.end_date ?? '')
  const [categoryId, setCategoryId] = useState(recurring?.category_id ?? '')
  const [accountId, setAccountId] = useState(recurring?.account_id ?? sortedAccounts[0]?.id ?? '')
  const [isActive, setIsActive] = useState(recurring?.is_active ?? true)
  const [autoGenerate, setAutoGenerate] = useState(recurring?.auto_generate ?? true)

  const currentRule = useMemo(
    () =>
      matchRules.find(
        (rule) => recurring && rule.recurring_ids.includes(recurring.id),
      ) ?? null,
    [matchRules, recurring],
  )
  const [ruleSelection, setRuleSelection] = useState<string>(currentRule?.id ?? '')
  const [newRuleName, setNewRuleName] = useState('')
  const [newRulePatterns, setNewRulePatterns] = useState('')
  const [newRuleExcludes, setNewRuleExcludes] = useState('')
  const [newRuleAccount, setNewRuleAccount] = useState('')
  const [newRuleType, setNewRuleType] = useState('')
  const [newRuleAccumulate, setNewRuleAccumulate] = useState(false)
  const [newRuleThreshold, setNewRuleThreshold] = useState('')

  const selectClass = 'w-full border border-border rounded-lg px-3 py-2 text-sm bg-card text-foreground focus:outline-none focus:ring-2 focus:ring-primary'

  const splitTerms = (value: string) =>
    value
      .split(',')
      .map((part) => part.trim())
      .filter(Boolean)

  const ruleChoiceFromState = (): RuleChoice | null => {
    if (ruleSelection === '__new__') {
      const patterns = splitTerms(newRulePatterns)
      if (patterns.length === 0) {
        toast.error(t('recurring.ruleInvalid'))
        return null
      }
      return {
        type: 'new',
        name: newRuleName.trim() || description,
        patterns,
        excludes: splitTerms(newRuleExcludes),
        searchAccountId: newRuleAccount || undefined,
        searchType: newRuleType || undefined,
        accumulate: newRuleAccumulate,
        accumulateThreshold: newRuleAccumulate ? newRuleThreshold : undefined,
      }
    }
    if (ruleSelection.startsWith('src:')) {
      return { type: 'import', sourceRuleId: ruleSelection.slice(4) }
    }
    if (ruleSelection) return { type: 'existing', ruleId: ruleSelection }
    return { type: 'none' }
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        const ruleChoice = ruleChoiceFromState()
        if (ruleChoice === null) return
        onSave(
          {
            description,
            amount: parseFloat(amount),
            currency,
            type,
            frequency,
            weekend_adjustment: weekendAdjustment,
            day_of_month: dayOfMonth ? parseInt(dayOfMonth) : null,
            start_date: startDate,
            end_date: endDate || null,
            category_id: categoryId || null,
            account_id: accountId || null,
            is_active: isActive,
            auto_generate: autoGenerate,
          } as Partial<RecurringTransaction>,
          ruleChoice,
        )
      }}
      className="space-y-4"
    >
      <div className="space-y-2">
        <Label>{t('recurring.description')}</Label>
        <Input value={description} onChange={(e) => setDescription(e.target.value)} required />
      </div>
      <div className="grid grid-cols-3 gap-4">
        <div className="space-y-2">
          <Label>{t('recurring.amount')}</Label>
          <Input type="number" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} required />
        </div>
        <div className="space-y-2">
          <Label>{t('recurring.currency')}</Label>
          <select className={selectClass} value={currency} onChange={(e) => setCurrency(e.target.value)}>
            {(supportedCurrencies ?? [{ code: userCurrency, symbol: userCurrency, name: userCurrency, flag: '' }]).map((c) => (
              <option key={c.code} value={c.code}>{c.flag} {c.name}</option>
            ))}
          </select>
        </div>
        <div className="space-y-2">
          <Label>{t('recurring.type')}</Label>
          <select className={selectClass} value={type} onChange={(e) => setType(e.target.value as 'debit' | 'credit')}>
            <option value="debit">{t('recurring.expense')}</option>
            <option value="credit">{t('recurring.income')}</option>
          </select>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label>{t('recurring.frequency')}</Label>
          <select className={selectClass} value={frequency} onChange={(e) => setFrequency(e.target.value as RecurringTransaction['frequency'])}>
            <option value="monthly">{t('recurring.monthly')}</option>
            <option value="quarterly">{t('recurring.quarterly')}</option>
            <option value="semiannual">{t('recurring.semiannual')}</option>
            <option value="weekly">{t('recurring.weekly')}</option>
            <option value="biweekly">{t('recurring.biweekly')}</option>
            <option value="yearly">{t('recurring.yearly')}</option>
          </select>
        </div>
        {(frequency === 'monthly' || frequency === 'quarterly' || frequency === 'semiannual') && (
          <div className="space-y-2">
            <Label>{t('recurring.dayOfMonth')}</Label>
            <Input type="number" min="1" max="31" value={dayOfMonth} onChange={(e) => setDayOfMonth(e.target.value)} />
          </div>
        )}
      </div>
      <div className="space-y-2">
        <Label>{t('recurring.weekendAdjustment')}</Label>
        <select
          className={selectClass}
          value={weekendAdjustment}
          onChange={(e) => setWeekendAdjustment(e.target.value as RecurringTransaction['weekend_adjustment'])}
        >
          <option value="none">{t('recurring.weekendAdjustmentNone')}</option>
          <option value="previous_friday">{t('recurring.weekendAdjustmentPreviousFriday')}</option>
          <option value="next_monday">{t('recurring.weekendAdjustmentNextMonday')}</option>
        </select>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label>{t('recurring.startDate')}</Label>
          <DatePickerInput value={startDate} onChange={setStartDate} className="w-full justify-start" />
        </div>
        <div className="space-y-2">
          <Label>{t('recurring.endDate')}</Label>
          <DatePickerInput value={endDate} onChange={setEndDate} placeholder={t('recurring.endDate')} className="w-full justify-start" />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label>{t('recurring.category')}</Label>
          <CategorySelect
            value={categoryId}
            onChange={setCategoryId}
            categories={categories}
            groups={categoryGroups}
            currentCategory={currentCategory}
            allowNone={true}
            className={selectClass}
          />
        </div>
        <div className="space-y-2">
          <Label>{t('recurring.account')}</Label>
          <select
            className={selectClass}
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
            required
          >
            {!accountId && <option value="" disabled>{t('recurring.noAccount')}</option>}
            {sortedAccounts.map((acc) => (
              <option key={acc.id} value={acc.id}>{getAccountName(acc)}</option>
            ))}
          </select>
        </div>
      </div>
      <div className="space-y-2">
        <Label>{t('recurring.identificationRule')}</Label>
        <select
          className={selectClass}
          value={ruleSelection}
          onChange={(e) => setRuleSelection(e.target.value)}
        >
          <option value="">{t('recurring.ruleNone')}</option>
          {matchRules.length > 0 && (
            <optgroup label={t('recurring.rules')}>
              {matchRules.map((rule) => (
                <option key={rule.id} value={rule.id}>
                  {rule.name}
                </option>
              ))}
            </optgroup>
          )}
          {normalRules.filter((rule) => rule.is_active).length > 0 && (
            <optgroup label={t('recurring.ruleFromRules')}>
              {normalRules
                .filter((rule) => rule.is_active)
                .map((rule) => (
                  <option key={rule.id} value={`src:${rule.id}`}>
                    {rule.name}
                  </option>
                ))}
            </optgroup>
          )}
          <option value="__new__">{t('recurring.ruleCreateInline')}</option>
        </select>
        <p className="text-[11px] text-muted-foreground">
          {t('recurring.identificationRuleHint')}
        </p>
        {ruleSelection === '__new__' && (
          <div className="space-y-2 rounded-lg border border-border p-3">
            <Input
              value={newRuleName}
              onChange={(e) => setNewRuleName(e.target.value)}
              placeholder={t('recurring.ruleName')}
            />
            <Input
              value={newRulePatterns}
              onChange={(e) => setNewRulePatterns(e.target.value)}
              placeholder={t('recurring.rulePatterns')}
            />
            <Input
              value={newRuleExcludes}
              onChange={(e) => setNewRuleExcludes(e.target.value)}
              placeholder={t('recurring.ruleExcludes')}
            />
            <div className="grid grid-cols-2 gap-2">
              <select
                className={selectClass}
                value={newRuleAccount}
                onChange={(e) => setNewRuleAccount(e.target.value)}
                title={t('recurring.ruleSearchWhere')}
              >
                <option value="">{t('recurring.ruleSearchSameAccount')}</option>
                {sortedAccounts.map((acc) => (
                  <option key={acc.id} value={acc.id}>{getAccountName(acc)}</option>
                ))}
              </select>
              <select
                className={selectClass}
                value={newRuleType}
                onChange={(e) => setNewRuleType(e.target.value)}
                title={t('recurring.ruleSearchDirection')}
              >
                <option value="">{t('recurring.ruleSearchSameType')}</option>
                <option value="debit">{t('recurring.expense')}</option>
                <option value="credit">{t('recurring.income')}</option>
              </select>
            </div>
            <p className="text-[11px] text-muted-foreground">{t('recurring.ruleSearchHint')}</p>
            <label className="flex items-start gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={newRuleAccumulate}
                onChange={(e) => setNewRuleAccumulate(e.target.checked)}
                className="h-4 w-4 mt-0.5 rounded border-border"
              />
              <span className="text-xs text-foreground">
                {t('recurring.ruleAccumulate')}
                <span className="block text-[11px] text-muted-foreground">{t('recurring.ruleAccumulateHint')}</span>
              </span>
            </label>
            {newRuleAccumulate && (
              <Input
                type="number"
                step="0.01"
                value={newRuleThreshold}
                onChange={(e) => setNewRuleThreshold(e.target.value)}
                placeholder={t('recurring.ruleAccumulateThreshold')}
              />
            )}
          </div>
        )}
      </div>
      <label className="flex items-start gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={autoGenerate}
          onChange={(e) => setAutoGenerate(e.target.checked)}
          className="h-4 w-4 mt-0.5 rounded border-border"
        />
        <span className="text-sm text-foreground">
          {t('recurring.autoGenerate')}
          <span className="block text-xs text-muted-foreground">{t('recurring.autoGenerateHelp')}</span>
        </span>
      </label>
      {recurring && (
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={isActive}
            onChange={(e) => setIsActive(e.target.checked)}
            className="h-4 w-4 rounded border-border"
          />
          <span className="text-sm text-foreground">{t('recurring.active')}</span>
        </label>
      )}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel}>{t('common.cancel')}</Button>
        <Button type="submit" disabled={loading}>
          {loading ? t('common.loading') : t('common.save')}
        </Button>
      </DialogFooter>
    </form>
  )
}
