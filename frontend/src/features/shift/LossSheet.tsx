import { useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { formatQuantity } from '@/features/supply/format'
import type { Unit } from '@/features/supply/types'
import { ApiError, recordLoss, requestError, type LossRequest, type ShiftOverview } from './api'

const unitLabels: Record<Unit, string> = { ml: 'л', g: 'кг', pcs: 'шт.' }
const lossReasons: Record<string, string> = {
  insufficient_stock: 'Списание превышает доступный запас.',
  unknown_on_hand: 'Сначала подтвердите остаток на складе.',
  stale_on_hand: 'Остаток устарел. Сначала сверяйте склад.',
}

function parseQuantity(value: string, unit: Unit) {
  const amount = value.trim().replace(',', '.')
  if (unit === 'pcs' ? !/^\d+$/.test(amount) : !/^\d+(\.\d{1,3})?$/.test(amount)) return null
  const [whole, fraction = ''] = amount.split('.')
  const quantity = unit === 'pcs' ? Number(whole) : Number(whole) * 1000 + Number(fraction.padEnd(3, '0'))
  return Number.isSafeInteger(quantity) && quantity > 0 ? quantity : null
}

export function LossSheet({ shift, onChange, onRefresh, children }: {
  shift: ShiftOverview
  onChange: (shift: ShiftOverview) => void
  onRefresh: () => Promise<void>
  children: ReactNode
}) {
  const items = shift.forecast.ingredients.filter((item) =>
    (item.onHandQty ?? 0) > 0 && !item.risks.some(
      (risk) => risk.type === 'insufficient_data' && risk.reason === 'stale_on_hand',
    ),
  )
  const preferred = items.find((item) => item.ingredientId === 'milk') ?? items[0]
  const [ingredientId, setIngredientId] = useState(preferred?.ingredientId ?? '')
  const [amount, setAmount] = useState(preferred?.ingredientId === 'milk' ? '2' : '1')
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const retry = useRef<LossRequest | null>(null)
  const item = items.find((entry) => entry.ingredientId === ingredientId) ?? preferred
  const quantity = item && parseQuantity(amount, item.unit)
  const exceedsStock = Boolean(item && quantity && quantity > (item.onHandQty ?? 0))

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!item || !quantity || exceedsStock || busy) return
    const request = retry.current ?? {
      eventId: crypto.randomUUID(), forecastId: shift.forecast.forecastId,
      ingredientId: item.ingredientId, quantity,
    }
    retry.current = request
    setBusy(true)
    setError('')
    try {
      const updated = await recordLoss(shift.storeId, request)
      retry.current = null
      onChange(updated)
      setOpen(false)
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        retry.current = null
        try {
          await onRefresh()
          setError('Прогноз обновлён. Сверьте остаток и повторите запись.')
        } catch (refreshError) {
          setError(requestError(refreshError))
        }
      } else if (error instanceof ApiError && error.status === 422) {
        retry.current = null
        setError(lossReasons[error.details[0]?.reason] ?? error.message)
      } else {
        setError(requestError(error))
      }
    } finally {
      setBusy(false)
    }
  }

  function updateInput() {
    retry.current = null
    setError('')
  }

  return (
    <Sheet open={open} onOpenChange={(next) => { if (!busy) setOpen(next) }}>
      <SheetTrigger asChild>{children}</SheetTrigger>
      <SheetContent showCloseButton={false} className="w-full gap-0 overflow-y-auto bg-card sm:max-w-[480px]">
        <SheetHeader className="sheet-masthead flex-row items-start justify-between gap-3 border-b border-border p-4 sm:p-6">
          <div>
            <SheetTitle className="text-2xl font-extrabold tracking-tight">Записать потерю</SheetTitle>
            <SheetDescription className="mt-1">Остаток уменьшится, а план закупок пересчитается.</SheetDescription>
          </div>
          <SheetClose asChild><Button type="button" variant="outline" className="h-11" disabled={busy}>Закрыть</Button></SheetClose>
        </SheetHeader>
        <form onSubmit={submit} aria-busy={busy} className="space-y-5 p-4 sm:p-6">
          <label className="block space-y-2 font-semibold">
            <span>Ингредиент</span>
            <select
              className="block h-11 w-full rounded-md border border-input bg-card px-3 text-base"
              value={item?.ingredientId ?? ''}
              disabled={busy || !items.length}
              onChange={(event) => {
                updateInput()
                setIngredientId(event.target.value)
                setAmount('1')
              }}
            >
              {!items.length && <option value="">Нет доступных ингредиентов</option>}
              {items.map((entry) => <option key={entry.ingredientId} value={entry.ingredientId}>{entry.name}</option>)}
            </select>
          </label>
          <label className="block space-y-2 font-semibold">
            <span>Объём потери{item && `, ${unitLabels[item.unit]}`}</span>
            <input
              type="text" inputMode={item?.unit === 'pcs' ? 'numeric' : 'decimal'}
              value={amount} disabled={busy || !item}
              onChange={(event) => { updateInput(); setAmount(event.target.value) }}
              aria-invalid={exceedsStock || (amount.length > 0 && !quantity)}
              aria-describedby="loss-available"
              className="block h-11 w-full rounded-md border border-input bg-card px-3 text-base tabular-nums aria-invalid:border-destructive"
            />
          </label>
          <p id="loss-available" className={exceedsStock ? 'text-destructive' : 'text-muted-foreground'}>
            {exceedsStock ? 'Объём больше текущего остатка.' : item && `На складе ${formatQuantity(item.onHandQty ?? 0, item.unit)}.`}
          </p>
          {error && <p role="alert" className="text-destructive">{error}</p>}
          <Button type="submit" className="h-11 w-full" disabled={!item || !quantity || exceedsStock || busy}>
            {busy ? 'Пересчитываем…' : 'Списать и пересчитать'}
          </Button>
        </form>
      </SheetContent>
    </Sheet>
  )
}
