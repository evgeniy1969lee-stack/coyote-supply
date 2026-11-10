import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowUpRight, Bot, CalendarDays, ClipboardList, MapPin, Package, Wifi } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { SheetTrigger } from '@/components/ui/sheet'
import { CopilotPanel } from '@/features/shift/CopilotPanel'
import { ShiftDashboard } from '@/features/shift/ShiftDashboard'
import { loadShift, loadStores, requestError, type ShiftOverview } from '@/features/shift/api'
import { DraftEditor } from '@/features/supply/DraftEditor'
import { Inventory } from '@/features/supply/Inventory'
import { PurchasePlan } from '@/features/supply/PurchasePlan'
import { formatTimestamp } from '@/features/supply/format'
import type { Draft, Store } from '@/features/supply/types'
import '@/features/shift/shift.css'

const navigation = [
  { id: 'shift', label: 'Моя смена', icon: ClipboardList },
  { id: 'supply', label: 'Закупки', icon: Package },
  { id: 'copilot', label: 'Copilot', icon: Bot },
] as const
type View = typeof navigation[number]['id']

const pageCopy: Record<View, { title: string; subtitle: string }> = {
  shift: { title: 'Моя смена', subtitle: 'Что требует внимания и какие действия помогут сегодня.' },
  supply: { title: 'План закупок', subtitle: 'Прогноз расхода, риски по ингредиентам и черновик заказа.' },
  copilot: { title: 'Бариста Copilot', subtitle: 'Спросите о рецепте, остатках или следующем действии.' },
}

function RetryPanel({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="os-card flex flex-wrap items-center justify-between gap-4 p-5">
      <p role="alert">{message}</p>
      <Button type="button" variant="outline" onClick={onRetry}>Повторить</Button>
    </div>
  )
}

function StoreWorkspace({ store, view, navigate }: {
  store: Store
  view: View
  navigate: (view: View) => void
}) {
  const [shift, setShift] = useState<ShiftOverview | null>(null)
  const [error, setError] = useState('')
  const [risksOnly, setRisksOnly] = useState(false)
  const [initialQuestion, setInitialQuestion] = useState('')
  const latest = useRef(0)

  const reload = useCallback(async (signal?: AbortSignal) => {
    const request = ++latest.current
    const next = await loadShift(store.storeId, signal)
    if (!signal?.aborted && request === latest.current) {
      setShift(next)
      setError('')
    }
  }, [store.storeId])

  useEffect(() => {
    const controller = new AbortController()
    void reload(controller.signal).catch((failure) => {
      if (!controller.signal.aborted) setError(requestError(failure))
    })
    return () => controller.abort()
  }, [reload])

  function retry() {
    setError('')
    void reload().catch((failure) => setError(requestError(failure)))
  }

  function acceptLoss(next: ShiftOverview) {
    latest.current += 1
    setShift(next)
    setError('')
  }

  function acceptDraft(draft: Draft | null) {
    setShift((previous) => previous && { ...previous, draft })
    void reload().catch((failure) => setError(requestError(failure)))
  }

  function openCopilot(question: string) {
    setInitialQuestion(question)
    navigate('copilot')
  }

  if (!shift) {
    return error ? <RetryPanel message={error} onRetry={retry} /> : (
      <div className="os-card p-6 text-muted-foreground" role="status">Загружаем данные смены…</div>
    )
  }

  const draftAction = (
    <SheetTrigger asChild>
      <Button type="button" className={view === 'shift' ? 'guardian-secondary h-11' : 'h-11 bg-white text-primary hover:bg-accent focus-visible:outline-white'}>
        Открыть черновик <ArrowUpRight aria-hidden="true" />
      </Button>
    </SheetTrigger>
  )

  return (
    <DraftEditor store={store} forecast={shift.forecast} savedDraft={shift.draft} onSaved={acceptDraft} onRefresh={reload}>
      {error && <RetryPanel message={error} onRetry={retry} />}
      {view === 'shift' && (
        <ShiftDashboard
          shift={shift} onLoss={acceptLoss} onRefresh={reload}
          onSupply={() => navigate('supply')} onAsk={openCopilot} draftAction={draftAction}
        />
      )}
      {view === 'supply' && (
        <>
          <p className="text-sm text-muted-foreground">Расчёт от {formatTimestamp(shift.forecast.asOf, store.timeZone)}</p>
          <PurchasePlan forecast={shift.forecast} timeZone={store.timeZone} action={draftAction} />
          <Inventory forecast={shift.forecast} risksOnly={risksOnly} onFilterChange={setRisksOnly} />
        </>
      )}
      {view === 'copilot' && <CopilotPanel storeId={store.storeId} initialQuestion={initialQuestion} />}
    </DraftEditor>
  )
}

export default function App() {
  const [stores, setStores] = useState<Store[] | null>(null)
  const [storeId, setStoreId] = useState('')
  const [view, setView] = useState<View>('shift')
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const store = stores?.find((entry) => entry.storeId === storeId) ?? stores?.[0]

  useEffect(() => {
    const controller = new AbortController()
    void loadStores(controller.signal).then((result) => {
      if (!controller.signal.aborted) setStores(result)
    }).catch((failure) => {
      if (!controller.signal.aborted) setError(requestError(failure))
    })
    return () => controller.abort()
  }, [attempt])

  function navigate(next: View) {
    setView(next)
  }

  return (
    <>
      <Button asChild className="fixed start-4 top-4 z-10 h-11 -translate-y-24 focus:translate-y-0">
        <a href="#workspace">Перейти к рабочей области</a>
      </Button>
      <header className="os-header">
        <div className="page-shell os-topbar">
          <div className="os-brand">
            <img src="/global-coffee.svg" width="44" height="44" alt="Global Coffee" />
            <div><strong>Coyote<span> OS</span></strong><p>Операции кофейни</p></div>
          </div>
          <nav aria-label="Разделы Coyote OS" className="os-nav">
            {navigation.map(({ id, label, icon: Icon }) => (
              <button key={id} type="button" aria-current={view === id ? 'page' : undefined} onClick={() => navigate(id)}>
                <Icon size={18} aria-hidden="true" /> {label}
              </button>
            ))}
          </nav>
          <span className="os-demo"><Wifi size={15} aria-hidden="true" /> Демо-данные</span>
        </div>
      </header>
      <main id="workspace" tabIndex={-1} className="page-shell os-workspace">
        <div className="os-page-heading">
          <div>
            <h1 className="page-title motion-heading">{pageCopy[view].title}</h1>
            <p>{pageCopy[view].subtitle}</p>
          </div>
          <div className="os-context">
            {store && <p className="os-shift-date"><CalendarDays size={17} aria-hidden="true" /> Срез {formatTimestamp(store.asOf, store.timeZone)}</p>}
            <label className="os-store">
              <MapPin size={17} aria-hidden="true" />
              <span className="sr-only">Точка Global Coffee</span>
              <select value={store?.storeId ?? ''} disabled={!store} onChange={(event) => setStoreId(event.target.value)}>
                {!store && <option value="">Точка Global Coffee</option>}
                {stores?.map((item) => <option key={item.storeId} value={item.storeId}>{item.name}</option>)}
              </select>
            </label>
          </div>
        </div>
        {store ? <StoreWorkspace key={store.storeId} store={store} view={view} navigate={navigate} /> : error ? (
          <RetryPanel message={error} onRetry={() => { setError(''); setAttempt((value) => value + 1) }} />
        ) : (
          <p role="status" className="os-card p-6 text-muted-foreground">
            {stores ? 'Демонстрационные точки отсутствуют.' : 'Подключаемся к сервису…'}
          </p>
        )}
      </main>
    </>
  )
}
