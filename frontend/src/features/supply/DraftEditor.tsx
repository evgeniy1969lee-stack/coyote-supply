import { useState, type FormEvent, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import {
  Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle,
} from '@/components/ui/sheet'
import { ApiError, requestError, saveDraft } from '@/features/shift/api'

import { formatDate, formatKzt, formatQuantity } from './format'
import { OrderCalculation } from './OrderCalculation'
import type { Draft, Forecast, IngredientForecast, Store } from './types'

type EligibleItem = IngredientForecast & { recommendedQty: number }

type DraftEdit = {
  counts: Record<string, string>
  reviewedForecastId: string
  message: string
  error: string
  fieldErrors: Record<string, string>
  savedTotal: number | null
}

function getDraft(forecast: Forecast, items: EligibleItem[], saved: Draft | null): DraftEdit {
  const counts = saved
    ? Object.fromEntries(saved.rows.map((row) => {
      const currentPack = items.find((item) => item.ingredientId === row.ingredientId)?.packQty
      return [row.ingredientId, String(currentPack ? row.quantity / currentPack : row.packCount)]
    }))
    : Object.fromEntries(items
      .filter((item) => item.recommendedQty > 0)
      .map((item) => [item.ingredientId, String(item.recommendedQty / item.packQty)]))
  return {
    counts, reviewedForecastId: saved?.forecastId ?? forecast.forecastId, fieldErrors: {},
    savedTotal: saved?.totalKzt ?? null,
    message: saved ? 'Загружен сохранённый черновик' : '', error: '',
  }
}

function calculateLine(count: string, item: EligibleItem) {
  const packs = Number(count)
  if (!/^\d+$/.test(count) || !Number.isSafeInteger(packs) || packs <= 0) return null
  const quantity = packs * item.packQty
  const total = packs * item.packPriceKzt
  return Number.isSafeInteger(quantity) && Number.isSafeInteger(total) ? { quantity, total } : null
}

const draftReasons: Record<string, string> = {
  not_multiple_of_pack: 'Количество должно быть кратно размеру упаковки.',
  recommendation_unavailable: 'По этой позиции нужно сверить данные склада.',
  amount_out_of_range: 'Сумма или количество слишком велики.',
}

export function DraftEditor({ store, forecast, savedDraft, onSaved, onRefresh, children }: {
  store: Store
  forecast: Forecast
  savedDraft: Draft | null
  onSaved: (draft: Draft | null) => void
  onRefresh: () => Promise<void>
  children: ReactNode
}) {
  const [edit, setEdit] = useState<DraftEdit | null>(null)
  const [saving, setSaving] = useState(false)
  const [refreshRequired, setRefreshRequired] = useState(false)
  const eligible = forecast.ingredients.filter(
    (item): item is EligibleItem => item.recommendedQty !== null,
  )
  const counts = edit?.counts ?? {}
  const reviewRequired = edit !== null && edit.reviewedForecastId !== forecast.forecastId
  const rows = eligible
    .filter((item) => Object.hasOwn(counts, item.ingredientId))
    .map((item) => ({
      item,
      count: counts[item.ingredientId],
      calculation: calculateLine(counts[item.ingredientId], item),
    }))
  const available = eligible.filter((item) => !Object.hasOwn(counts, item.ingredientId))
  const unavailable = Object.keys(counts).filter((id) => !eligible.some((item) => item.ingredientId === id))
  const total = rows.reduce((sum, row) => sum + (row.calculation?.total ?? 0), 0)
  const totalTooLarge = !Number.isSafeInteger(total)
  const valid = !totalTooLarge && !unavailable.length && rows.every((row) => row.calculation !== null)

  function changeCount(id: string, value: string) {
    setEdit((previous) => previous && {
      ...previous, counts: { ...previous.counts, [id]: value },
      message: '', error: '', fieldErrors: {}, savedTotal: null,
    })
  }

  function removeRow(id: string) {
    const next = { ...counts }
    delete next[id]
    setEdit((previous) => previous && {
      ...previous, counts: next, message: '', error: '', fieldErrors: {}, savedTotal: null,
    })
  }

  async function reloadForecast() {
    try {
      await onRefresh()
      setRefreshRequired(false)
      setEdit((previous) => previous && { ...previous, error: '', message: '' })
    } catch (error) {
      setRefreshRequired(true)
      setEdit((previous) => previous && { ...previous, error: requestError(error) })
    }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!edit || !valid || reviewRequired || refreshRequired || saving) return
    setSaving(true)
    const input = rows.flatMap(({ item, calculation }) =>
      calculation ? [{ ingredientId: item.ingredientId, quantity: calculation.quantity }] : [],
    )
    try {
      const draft = await saveDraft(store.storeId, forecast.forecastId, input)
      setEdit({
        ...edit, savedTotal: draft?.totalKzt ?? 0, fieldErrors: {}, error: '',
        message: draft ? 'Черновик сохранён на сервере' : 'Черновик очищен на сервере',
      })
      onSaved(draft)
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        await reloadForecast()
      } else {
        const fieldErrors: Record<string, string> = {}
        if (error instanceof ApiError && error.status === 422) {
          for (const detail of error.details) {
            const index = /^rows\.(\d+)\./.exec(detail.path)?.[1]
            const row = index === undefined ? undefined : input[Number(index)]
            if (row) fieldErrors[row.ingredientId] = draftReasons[detail.reason] ?? 'Проверьте эту позицию.'
          }
        }
        setEdit({ ...edit, message: '', error: requestError(error), fieldErrors })
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet onOpenChange={(open) => {
      if (open && !edit) setEdit(getDraft(forecast, eligible, savedDraft))
    }}>
      {children}
      <SheetContent showCloseButton={false} className="w-full gap-0 overflow-y-auto bg-card sm:max-w-[480px]">
        <SheetHeader className="sheet-masthead flex-row items-start justify-between gap-3 border-b border-border p-4 sm:p-6">
          <div className="space-y-1">
            <SheetTitle className="text-2xl leading-tight font-extrabold tracking-tight">Черновик закупки</SheetTitle>
            <SheetDescription>
              {store.name}{forecast.schedule && ` · поставка ${formatDate(forecast.schedule.arrivalDate)}`}
            </SheetDescription>
          </div>
          <SheetClose asChild><Button variant="outline" className="h-11">Закрыть</Button></SheetClose>
        </SheetHeader>

        <form onSubmit={save} noValidate className="flex grow flex-col" aria-busy={saving}>
          <fieldset disabled={saving} className="min-w-0 grow space-y-4 p-4 sm:p-6">
            {reviewRequired && (
              <div className="space-y-2 rounded-lg bg-warning-surface p-3 text-warning">
                <p>Прогноз обновился. Проверьте сохранённые количества по новым рекомендациям.</p>
                <Button type="button" variant="outline" onClick={() => setEdit((previous) => previous && {
                  ...previous, reviewedForecastId: forecast.forecastId, savedTotal: null, message: '', error: '',
                })}>Количество сверено</Button>
              </div>
            )}
            {unavailable.map((id) => (
              <div key={id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border p-3">
                <span>{forecast.ingredients.find((item) => item.ingredientId === id)?.name ?? id} · закупка недоступна</span>
                <Button type="button" variant="outline" onClick={() => removeRow(id)}>Убрать позицию</Button>
              </div>
            ))}
            {rows.length ? (
              <ul className="divide-y divide-border rounded-lg border border-border bg-white">
                {rows.map(({ item, count, calculation }) => {
                  const id = `draft-count-${item.ingredientId}`
                  const fieldError = edit?.fieldErrors[item.ingredientId]
                  return (
                    <li key={item.ingredientId} className="space-y-3 p-3 sm:p-4">
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <p className="font-semibold wrap-break-word">{item.name}</p>
                        <p className="text-xs text-muted-foreground">
                          Рекомендовано {formatQuantity(item.recommendedQty, item.unit)}
                        </p>
                      </div>
                      <p id={`${id}-pack`} className="text-xs text-muted-foreground">
                        Упаковка · {formatQuantity(item.packQty, item.unit)} · {formatKzt(item.packPriceKzt)}
                      </p>
                      <div className="flex flex-wrap items-end justify-between gap-2">
                        <div className="space-y-1">
                          <label htmlFor={id} className="block text-xs font-medium">
                            Упаковки<span className="sr-only">: {item.name}</span>
                          </label>
                          <input
                            id={id}
                            type="text"
                            inputMode="numeric"
                            value={count}
                            onChange={(event) => changeCount(item.ingredientId, event.target.value)}
                            aria-invalid={!calculation || Boolean(fieldError)}
                            aria-describedby={calculation && !fieldError ? `${id}-pack` : `${id}-pack ${id}-error`}
                            className="h-11 w-24 rounded-md border border-input bg-card px-3 text-base tabular-nums aria-invalid:border-destructive"
                          />
                        </div>
                        {calculation && (
                          <div className="pb-1 text-end tabular-nums">
                            <p className="font-semibold">{formatQuantity(calculation.quantity, item.unit)}</p>
                            <p className="text-xs text-muted-foreground">{formatKzt(calculation.total)}</p>
                          </div>
                        )}
                      </div>
                      {(!calculation || fieldError) && (
                        <p id={`${id}-error`} className="text-xs text-destructive">
                          {fieldError ?? (/^\d+$/.test(count) && Number(count) > 0
                            ? 'Количество слишком большое.'
                            : 'Введите целое положительное число упаковок.')}
                        </p>
                      )}
                      <div className="flex flex-wrap items-start justify-between gap-x-3">
                        {item.explanation && (
                          <details className="grow text-xs text-muted-foreground">
                            <summary className="flex min-h-11 w-fit cursor-pointer items-center gap-1 font-medium text-primary before:content-['+']">
                              Расчёт объёма
                            </summary>
                            <OrderCalculation item={item} />
                          </details>
                        )}
                        <Button type="button" variant="ghost" aria-label={`Убрать: ${item.name}`} className="h-11 px-2 text-muted-foreground" onClick={() => removeRow(item.ingredientId)}>
                          Убрать
                        </Button>
                      </div>
                    </li>
                  )
                })}
              </ul>
            ) : (
              <p className="rounded-lg bg-muted p-4 text-muted-foreground">
                Черновик пуст. {available.length > 0 && 'Выберите ингредиент ниже, чтобы добавить позицию.'}
              </p>
            )}
            {available.length > 0 && (
              <label className="block space-y-1 text-xs font-medium">
                <span>Добавить ингредиент</span>
                <select
                  value=""
                  onChange={(event) => {
                    if (event.target.value) changeCount(event.target.value, '1')
                  }}
                  className="block h-11 w-full rounded-md border border-input bg-card px-2 text-base"
                >
                  <option value="" disabled>Выберите ингредиент</option>
                  {available.map((item) => <option key={item.ingredientId} value={item.ingredientId}>{item.name}</option>)}
                </select>
              </label>
            )}
          </fieldset>

          <footer className="space-y-3 border-t border-border bg-muted p-4 sm:p-6">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="font-medium">{edit?.savedTotal != null && !reviewRequired ? 'Итого по серверу' : 'Итого'}</span>
              <strong className="text-xl tabular-nums">{valid ? formatKzt(!reviewRequired ? edit?.savedTotal ?? total : total) : '—'}</strong>
            </div>
            {totalTooLarge && <p className="text-sm text-destructive">Сумма заказа слишком большая.</p>}
            {edit?.error && <p role="alert" className="text-sm text-destructive">{edit.error}</p>}
            <p role="status" className="empty:hidden text-sm text-primary">{edit?.message}</p>
            {refreshRequired && <Button type="button" variant="outline" disabled={saving} onClick={() => void reloadForecast()}>Обновить прогноз</Button>}
            <Button type="submit" disabled={!valid || !edit || reviewRequired || refreshRequired || saving} className="motion-button h-11 w-full">
              {saving ? 'Сохраняем…' : 'Сохранить черновик'}
            </Button>
            <p className="text-xs text-muted-foreground">Черновик хранится на сервере</p>
          </footer>
        </form>
      </SheetContent>
    </Sheet>
  )
}
