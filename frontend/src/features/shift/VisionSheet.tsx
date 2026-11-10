import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ArrowRight, Camera, Check, ScanLine, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { formatQuantity } from '@/features/supply/format'
import {
  analyzeVision, ApiError, recordConsumption, requestError,
  type ConsumptionRequest, type RecipePortion, type ShiftOverview, type VisionProposal,
} from './api'
import { VisionCapture } from './VisionCapture'

const hintTitles = {
  possible_pour: 'Похоже на наливание',
  ingredient_visible: 'Виден возможный ингредиент',
  unclear: 'Кадр неоднозначен',
}

const ingredientLabels: Record<string, string> = {
  milk: 'молоко', 'oat-milk': 'овсяное молоко', cream: 'сливки',
}

const optionKey = (option: RecipePortion) => `${option.recipeSku}:${option.ingredientId}`

function VisionSession({ storeId, onChange, onRefresh, onClose, onSaving, saving }: {
  storeId: string
  onChange: (shift: ShiftOverview) => void
  onRefresh: () => Promise<void>
  onClose: () => void
  onSaving: (saving: boolean) => void
  saving: boolean
}) {
  const [frame, setFrame] = useState<Blob | null>(null)
  const [proposal, setProposal] = useState<VisionProposal | null>(null)
  const [selected, setSelected] = useState('')
  const [quantity, setQuantity] = useState('')
  const [analyzing, setAnalyzing] = useState(false)
  const [error, setError] = useState('')
  const analysis = useRef<AbortController | null>(null)
  const retry = useRef<ConsumptionRequest | null>(null)
  const confirming = useRef(false)
  const option = proposal?.options.find((entry) => optionKey(entry) === selected)
  const amount = /^\d+$/.test(quantity.trim()) ? Number(quantity) : 0
  const valid = option && Number.isSafeInteger(amount) && amount > 0 && amount <= (option.availableQty ?? 0)

  useEffect(() => () => analysis.current?.abort(), [])

  function pick(entry?: RecipePortion) {
    setSelected(entry ? optionKey(entry) : '')
    setQuantity(entry ? String(entry.recipeQty) : '')
    setError('')
    retry.current = null
  }

  function updateFrame(next: Blob | null) {
    setFrame(next)
    setProposal(null)
    pick()
  }

  async function inspect() {
    if (!frame || analysis.current || saving) return
    const controller = new AbortController()
    analysis.current = controller
    setAnalyzing(true)
    setError('')
    try {
      const result = await analyzeVision(storeId, frame, controller.signal)
      if (controller.signal.aborted) return
      setProposal(result)
      const matches = result.options.filter((entry) => (
        entry.ingredientId === result.ingredientId && (entry.availableQty ?? 0) > 0
      ))
      pick(matches.length === 1 ? matches[0] : undefined)
    } catch (failure) {
      if (!controller.signal.aborted) setError(requestError(failure))
    } finally {
      analysis.current = null
      if (!controller.signal.aborted) setAnalyzing(false)
    }
  }

  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!proposal || !option || !valid || confirming.current) return
    confirming.current = true
    const request = retry.current ?? {
      eventId: crypto.randomUUID(), forecastId: proposal.forecastId, recipeSku: option.recipeSku,
      ingredientId: option.ingredientId, quantity: amount,
    }
    retry.current = request
    onSaving(true)
    setError('')
    try {
      const next = await recordConsumption(storeId, request)
      onChange(next)
      onClose()
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 409) {
        setProposal(null)
        pick()
        await onRefresh().catch(() => {})
        setError('Запас изменился. Запустите анализ ещё раз и сверьте количество.')
      } else if (failure instanceof ApiError && failure.details.some((detail) => detail.reason === 'insufficient_stock')) {
        setError('Доступного остатка недостаточно. Проверьте объём и партии.')
      } else {
        setError(requestError(failure))
      }
    } finally {
      confirming.current = false
      onSaving(false)
    }
  }

  return (
    <div className="vision-session">
      <VisionCapture disabled={analyzing || saving} onCapture={updateFrame} />
      {proposal ? (
        <form onSubmit={confirm} aria-busy={saving} className="vision-review">
          <div className="vision-observation">
            <ScanLine size={20} aria-hidden="true" />
            <div>
              <h3>{hintTitles[proposal.observation]}{proposal.ingredientId && ingredientLabels[proposal.ingredientId]
                ? ` · ${ingredientLabels[proposal.ingredientId]}` : ''}</h3>
              <p>{proposal.model} · Сверьте ингредиент и выберите техкарту.</p>
            </div>
          </div>
          <label className="vision-field">
            <span>Техкарта и ингредиент</span>
            <select value={selected} disabled={saving} onChange={(event) => {
              pick(proposal.options.find((entry) => optionKey(entry) === event.target.value))
            }}>
              <option value="">Выберите техкарту</option>
              {proposal.options.map((entry) => (
                <option key={optionKey(entry)} value={optionKey(entry)} disabled={(entry.availableQty ?? 0) <= 0}>
                  {entry.recipeName} · {entry.ingredientName}{(entry.availableQty ?? 0) <= 0 ? ' · сверьте остаток' : ''}
                </option>
              ))}
            </select>
          </label>
          {option && (
            <label className="vision-field">
              <span>Подтверждённый расход, мл</span>
              <input type="text" inputMode="numeric" value={quantity} maxLength={16}
                disabled={saving} aria-invalid={!valid} aria-describedby="vision-portion"
                onChange={(event) => {
                  setQuantity(event.target.value)
                  retry.current = null
                  setError('')
                }} />
              <small id="vision-portion">
                По техкарте {option.recipeQty} мл. Доступно {formatQuantity(option.availableQty ?? 0, 'ml')}.
                {amount > (option.availableQty ?? 0) && ' Введите объём в пределах остатка.'}
              </small>
            </label>
          )}
          <Button type="submit" className="h-11" disabled={!valid || saving}>
            <Check aria-hidden="true" /> {saving ? 'Сохраняем расход…' : 'Подтвердить расход'}
          </Button>
        </form>
      ) : (
        <Button type="button" className="h-11 w-full" disabled={!frame || analyzing} onClick={() => void inspect()}>
          <ScanLine aria-hidden="true" /> {analyzing ? 'Анализируем кадр…' : 'Анализировать кадр'}
        </Button>
      )}
      {analyzing && <p role="status" className="text-sm text-muted-foreground">Модель определяет, что видно на фото.</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <p className="text-xs text-muted-foreground">
        Отправляется один выбранный кадр. Объём берётся из техкарты и сохраняется после подтверждения.
      </p>
    </div>
  )
}

export function VisionSheet({ storeId, onChange, onRefresh }: {
  storeId: string
  onChange: (shift: ShiftOverview) => void
  onRefresh: () => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)

  return (
    <Sheet open={open} onOpenChange={(next) => { if (!saving) setOpen(next) }}>
      <section className="os-card vision-launch" aria-labelledby="vision-title">
        <div className="vision-launch-copy">
          <div className="os-tile os-tile-violet"><Camera size={22} aria-hidden="true" /></div>
          <div>
            <h2 id="vision-title">Coyote Vision</h2>
            <p>Кадр приготовления → норма по техкарте → расход в прогнозе</p>
          </div>
        </div>
        <SheetTrigger asChild>
          <Button type="button" variant="outline" className="h-11 text-primary">
            Открыть Vision <ArrowRight aria-hidden="true" />
          </Button>
        </SheetTrigger>
      </section>
      <SheetContent showCloseButton={false} className="w-full gap-0 overflow-y-auto bg-card sm:max-w-[540px]">
        <SheetHeader className="sheet-masthead flex-row items-start justify-between gap-3 border-b border-border p-4 sm:p-6">
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-primary">
              <Sparkles size={14} aria-hidden="true" /> Анализ кадра
            </div>
            <SheetTitle className="text-2xl font-extrabold tracking-tight">Coyote Vision</SheetTitle>
            <SheetDescription className="mt-1">Снимите приготовление напитка и сверьте расход.</SheetDescription>
          </div>
          <SheetClose asChild><Button type="button" variant="outline" className="h-11" disabled={saving}>Закрыть</Button></SheetClose>
        </SheetHeader>
        {open && <VisionSession storeId={storeId} onChange={onChange} onRefresh={onRefresh}
          onClose={() => setOpen(false)} saving={saving} onSaving={setSaving} />}
      </SheetContent>
    </Sheet>
  )
}
