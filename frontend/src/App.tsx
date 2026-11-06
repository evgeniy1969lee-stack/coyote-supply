import { useState } from 'react'
import { ArrowUpRight, CalendarDays, Database, GitBranch, MapPin } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'

import { DraftEditor } from '@/features/supply/DraftEditor'
import { Inventory } from '@/features/supply/Inventory'
import { PurchasePlan } from '@/features/supply/PurchasePlan'
import { getFixtureForecast, stores } from '@/features/supply/fixtures'
import { formatTimestamp } from '@/features/supply/format'

export default function App() {
  const [storeId, setStoreId] = useState(stores[0]?.storeId ?? '')
  const [risksOnly, setRisksOnly] = useState(false)
  const store = stores.find((item) => item.storeId === storeId)
  const forecast = getFixtureForecast(storeId)

  return (
    <>
      <Button
        asChild
        className="fixed start-4 top-4 z-10 h-11 -translate-y-24 focus:translate-y-0"
      >
        <a href="#workspace">Перейти к закупкам</a>
      </Button>

      <header className="brand-header">
        <div className="page-shell flex min-h-[68px] flex-wrap items-center justify-between gap-x-5 gap-y-2 py-3">
          <div className="flex items-center gap-3 sm:gap-4">
            <div className="flex items-center gap-2.5">
              <img src="/global-coffee.svg" alt="" width="46" height="46" />
              <span className="wordmark">GLOBAL<br />COFFEE</span>
            </div>
            <div className="brand-product border-s border-white/25 ps-3 text-sm font-semibold sm:ps-4">Coyote Supply</div>
          </div>
          <Badge className="gap-2 border-white/25 bg-transparent px-2.5 py-1 text-white">
            <span className="size-1.5 rounded-full bg-[#e0aeb5]" aria-hidden="true" /> Демо
          </Badge>
        </div>
      </header>

      <main
        id="workspace"
        tabIndex={-1}
        className="page-shell space-y-7 py-7 sm:space-y-9 lg:py-10"
      >
        <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-5">
          <div>
            <h1 className="page-title motion-heading">
              План закупок
            </h1>
            {store && forecast && (
              <p className="mt-2 flex items-center gap-2 text-sm text-muted-foreground">
                <CalendarDays size={16} aria-hidden="true" /> Расчёт от {formatTimestamp(forecast.asOf, store.timeZone)}
              </p>
            )}
          </div>

          <div className="flex flex-wrap items-end gap-2 sm:gap-3">
            <div className="min-w-0 space-y-1">
              <label htmlFor="store-select" className="block text-xs font-semibold text-muted-foreground">Точка Global Coffee</label>
              <Select value={storeId} onValueChange={setStoreId} disabled={!stores.length}>
                <SelectTrigger id="store-select" className="min-w-44 border-input bg-card font-semibold data-[size=default]:h-11">
                  <MapPin size={16} className="text-primary" aria-hidden="true" />
                  <SelectValue placeholder="Выбрать точку" />
                </SelectTrigger>
                <SelectContent>
                  {stores.map((item) => (
                    <SelectItem key={item.storeId} value={item.storeId}>{item.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>

        {store && forecast ? (
          <>
            <PurchasePlan forecast={forecast} timeZone={store.timeZone} action={
              <DraftEditor store={store} forecast={forecast}>
                <Button type="button" className="motion-button h-11 w-fit bg-white px-4 text-primary hover:bg-accent focus-visible:outline-white">
                    Открыть черновик <ArrowUpRight aria-hidden="true" />
                </Button>
              </DraftEditor>
            } />
            <Inventory key={storeId} forecast={forecast} risksOnly={risksOnly} onFilterChange={setRisksOnly} />
          </>
        ) : (
          <p role="status" className="rounded-lg border border-border bg-card p-5">
            Для выбранной точки пока нет прогноза.
          </p>
        )}

        <section aria-labelledby="source-heading" className="source-note">
          <div className="source-symbol" aria-hidden="true"><GitBranch size={21} /></div>
          <div>
            <h2 id="source-heading" className="font-bold">Как подключается Coyote Manager</h2>
            <p className="mt-1 text-sm text-muted-foreground">Продажи, техкарты и остатки → прогноз расхода → черновик закупки.</p>
          </div>
          <div className="source-status">
            <Database size={15} aria-hidden="true" /> Сейчас используются тестовые данные
          </div>
        </section>
      </main>
    </>
  )
}
