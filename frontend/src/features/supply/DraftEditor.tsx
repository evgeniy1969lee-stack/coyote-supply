import { useState, type FormEvent, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import {
  Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger,
} from '@/components/ui/sheet'

import { formatDate, formatKzt, formatQuantity } from './format'
import { OrderCalculation } from './OrderCalculation'
import type { Forecast, IngredientForecast, Store } from './types'

type EligibleItem = IngredientForecast & { recommendedQty: number }

type DraftEdit = {
  counts: Record<string, string>
  message: string
  error: string
}

const draftKey = (storeId: string) => `coyote-supply:demo-draft:${storeId}`

function getDraft(forecast: Forecast, items: EligibleItem[]): DraftEdit {
  const counts = Object.fromEntries(items
    .filter((item) => item.recommendedQty > 0)
    .map((item) => [item.ingredientId, String(item.recommendedQty / item.packQty)]))

  try {
    const value = localStorage.getItem(draftKey(forecast.storeId))
    if (value === null) return { counts, message: '', error: '' }
    const draft: { forecastId?: unknown; rows?: { ingredientId: string; quantity: number }[] } = JSON.parse(value)
    if (draft.forecastId !== forecast.forecastId) {
      return { counts, message: 'Прогноз обновился. Проверьте новый список перед сохранением.', error: '' }
    }
    if (!Array.isArray(draft.rows)) throw new Error('Invalid draft rows')

    const restored = Object.fromEntries(draft.rows.map(({ ingredientId, quantity }) => {
      const item = items.find((entry) => entry.ingredientId === ingredientId)
      if (!item || !Number.isSafeInteger(quantity) || quantity <= 0 || quantity % item.packQty !== 0) {
        throw new Error('Invalid draft quantity')
      }
      return [ingredientId, String(quantity / item.packQty)]
    }))
    return { counts: restored, message: 'Загружен сохранённый черновик', error: '' }
  } catch {
    return { counts, message: '', error: 'Не удалось загрузить локальный черновик. Показаны рекомендации.' }
  }
}

function calculateLine(count: string, item: EligibleItem) {
  const packs = Number(count)
  if (!/^\d+$/.test(count) || !Number.isSafeInteger(packs) || packs <= 0) return null
  const quantity = packs * item.packQty
  const total = packs * item.packPriceKzt
  return Number.isSafeInteger(quantity) && Number.isSafeInteger(total) ? { quantity, total } : null
}

export function DraftEditor({ store, forecast, children }: {
  store: Store
  forecast: Forecast
  children: ReactNode
}) {
  const [edits, setEdits] = useState<Record<string, DraftEdit>>({})
  const eligible = forecast.ingredients.filter(
    (item): item is EligibleItem => item.recommendedQty !== null,
  )
  const edit = edits[forecast.forecastId]
  const counts = edit?.counts ?? {}
  const rows = eligible
    .filter((item) => Object.hasOwn(counts, item.ingredientId))
    .map((item) => ({
      item,
      count: counts[item.ingredientId],
      calculation: calculateLine(counts[item.ingredientId], item),
    }))
  const available = eligible.filter((item) => !Object.hasOwn(counts, item.ingredientId))
  const total = rows.reduce((sum, row) => sum + (row.calculation?.total ?? 0), 0)
  const totalTooLarge = !Number.isSafeInteger(total)
  const valid = !totalTooLarge && rows.every((row) => row.calculation !== null)

  function updateEdit(next: DraftEdit) {
    setEdits((previous) => ({ ...previous, [forecast.forecastId]: next }))
  }

  function changeCount(id: string, value: string) {
    updateEdit({ counts: { ...counts, [id]: value }, message: '', error: '' })
  }

  function removeRow(id: string) {
    const next = { ...counts }
    delete next[id]
    updateEdit({ counts: next, message: '', error: '' })
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!valid) return
    const draft = {
      forecastId: forecast.forecastId,
      rows: rows.flatMap(({ item, calculation }) =>
        calculation ? [{ ingredientId: item.ingredientId, quantity: calculation.quantity }] : [],
      ),
    }

    try {
      localStorage.setItem(draftKey(store.storeId), JSON.stringify(draft))
      updateEdit({ counts, message: 'Черновик сохранён', error: '' })
    } catch {
      updateEdit({ counts, message: '', error: 'Не удалось сохранить черновик. Повторите попытку.' })
    }
  }

  return (
    <Sheet onOpenChange={(open) => {
      if (open && !edit) updateEdit(getDraft(forecast, eligible))
    }}>
      <SheetTrigger asChild>{children}</SheetTrigger>
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

        <form onSubmit={save} noValidate className="flex grow flex-col">
          <div className="grow space-y-4 p-4 sm:p-6">
            {rows.length ? (
              <ul className="divide-y divide-border rounded-lg border border-border bg-white">
                {rows.map(({ item, count, calculation }) => {
                  const id = `draft-count-${item.ingredientId}`
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
                            aria-invalid={!calculation}
                            aria-describedby={calculation ? `${id}-pack` : `${id}-pack ${id}-error`}
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
                      {!calculation && (
                        <p id={`${id}-error`} className="text-xs text-destructive">
                          {/^\d+$/.test(count) && Number(count) > 0
                            ? 'Количество слишком большое.'
                            : 'Введите целое положительное число упаковок.'}
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
          </div>

          <footer className="space-y-3 border-t border-border bg-muted p-4 sm:p-6">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="font-medium">Итого</span>
              <strong className="text-xl tabular-nums">{valid ? formatKzt(total) : '—'}</strong>
            </div>
            {totalTooLarge && <p className="text-sm text-destructive">Сумма заказа слишком большая.</p>}
            {edit?.error && <p role="alert" className="text-sm text-destructive">{edit.error}</p>}
            <p role="status" className="empty:hidden text-sm text-primary">{edit?.message}</p>
            <Button type="submit" disabled={!valid || !edit} className="motion-button h-11 w-full">Сохранить черновик</Button>
            <p className="text-xs text-muted-foreground">Демо · сохранение в этом браузере</p>
          </footer>
        </form>
      </SheetContent>
    </Sheet>
  )
}
