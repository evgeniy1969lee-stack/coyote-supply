import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'

import { formatDate, formatQuantity } from './format'
import { IngredientDetails } from './IngredientDetails'
import type { DataIssue, Forecast, IngredientForecast, Risk, Unit } from './types'

const reasonLabels: Record<DataIssue, string> = {
  missing_on_hand: 'Остаток неизвестен',
  stale_on_hand: 'Остаток устарел',
  insufficient_history: 'Мало истории продаж',
  missing_recipe: 'Нет техкарты',
  missing_schedule: 'Нет расписания поставок',
  unknown_lot_expiry: 'Срок годности неизвестен',
}

const riskStyles = {
  stockout: 'bg-destructive-surface text-destructive',
  expiry: 'bg-warning-surface text-warning',
  excess: 'bg-warning-surface text-warning',
  insufficient_data: 'bg-muted text-muted-foreground',
} satisfies Record<Risk['type'], string>

function RiskLabel({ risk, unit }: { risk: Risk; unit: Unit }) {
  const label = risk.type === 'stockout' ? 'Дефицит'
    : risk.type === 'expiry' ? `Риск списания · ${formatQuantity(risk.quantity, unit)}`
    : risk.type === 'excess' ? `Излишек · ${formatQuantity(risk.quantity, unit)}`
    : 'Нет данных'
  const note = risk.type === 'stockout' ? `С ${formatDate(risk.date)}`
    : risk.type === 'expiry' ? `Срок · ${formatDate(risk.date)}`
    : risk.type === 'insufficient_data' ? reasonLabels[risk.reason]
    : null

  return (
    <div className="space-y-0.5">
      <Badge className={`rounded-md border-transparent ${riskStyles[risk.type]}`}>{label}</Badge>
      {note && <p className="text-xs text-muted-foreground">{note}</p>}
    </div>
  )
}

function RiskList({ item }: { item: IngredientForecast }) {
  if (!item.risks.length) return <span className="text-muted-foreground">Без рисков</span>
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-2">
      {item.risks.map((risk) => (
        <RiskLabel
          key={risk.type === 'expiry' ? `expiry:${risk.lotId}` : risk.type}
          risk={risk}
          unit={item.unit}
        />
      ))}
    </div>
  )
}

function shownQuantity(quantity: number | null, unit: Unit, fallback: string) {
  return quantity === null ? fallback : formatQuantity(quantity, unit)
}

export function Inventory({ forecast, risksOnly, onFilterChange }: {
  forecast: Forecast
  risksOnly: boolean
  onFilterChange: (value: boolean) => void
}) {
  const { ingredients: items, schedule } = forecast
  const riskCount = items.filter((item) => item.risks.length > 0).length
  const visible = risksOnly ? items.filter((item) => item.risks.length > 0) : items

  return (
    <section aria-labelledby="inventory-heading" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="inventory-heading" className="text-[27px] leading-tight font-extrabold tracking-tight">Запасы точки</h2>
          <p className="mt-1 text-xs text-muted-foreground">Всего {items.length} · Требуют внимания {riskCount}</p>
        </div>
        <div role="group" aria-label="Фильтр запасов" className="flex gap-1 rounded-md border border-border bg-muted p-1">
          {([false, true] as const).map((value) => (
            <Button
              key={String(value)}
              type="button"
              variant="ghost"
              aria-pressed={risksOnly === value}
              className={risksOnly === value ? 'h-11 bg-card text-primary hover:bg-card' : 'h-11 text-muted-foreground'}
              onClick={() => onFilterChange(value)}
            >
              {value ? 'С риском' : 'Все'}
            </Button>
          ))}
        </div>
      </div>

      <p className="sr-only" role="status">Показано позиций: {visible.length}</p>
      {visible.length === 0 ? (
        <p className="rounded-lg border border-border bg-card px-4 py-7 text-muted-foreground sm:px-5">
          {risksOnly ? 'Нет позиций с риском.' : 'В прогнозе нет позиций.'}
        </p>
      ) : (
        <>
          <div className="hidden overflow-hidden rounded-lg border border-border bg-card md:block">
            <Table aria-label="Ингредиенты и рекомендации">
              <TableHeader>
                <TableRow className="border-b border-border bg-muted hover:bg-muted">
                  <TableHead scope="col" className="w-[25%] ps-5">Ингредиент</TableHead>
                  <TableHead scope="col" className="w-[15%] text-end">Остаток</TableHead>
                  <TableHead scope="col" className="w-[30%] ps-5">Риск</TableHead>
                  <TableHead scope="col" className="pe-5 text-end">К закупке</TableHead>
                  <TableHead scope="col" className="w-24"><span className="sr-only">Действия</span></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visible.map((item) => (
                  <TableRow key={item.ingredientId} className="border-border">
                    <TableCell className="h-15 ps-5 font-bold whitespace-normal wrap-break-word">{item.name}</TableCell>
                    <TableCell className="text-end tabular-nums">{shownQuantity(item.onHandQty, item.unit, 'Неизвестен')}</TableCell>
                    <TableCell className="ps-5 whitespace-normal"><RiskList item={item} /></TableCell>
                    <TableCell className="pe-5 text-end font-semibold tabular-nums">{shownQuantity(item.recommendedQty, item.unit, 'Нет данных')}</TableCell>
                    <TableCell className="pe-5 text-end">
                      <IngredientDetails item={item} schedule={schedule} risks={<RiskList item={item} />} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-card md:hidden">
            {visible.map((item) => (
              <li key={item.ingredientId} className="space-y-2 px-4 py-3">
                <div className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-2">
                  <h3 className="font-semibold wrap-break-word">{item.name}</h3>
                  <p className="text-xs text-muted-foreground">Остаток · {shownQuantity(item.onHandQty, item.unit, 'неизвестен')}</p>
                </div>
                <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
                  <RiskList item={item} />
                  <div className="ms-auto text-end">
                    <p className="text-xs text-muted-foreground">
                      К закупке · <strong className="text-sm text-foreground tabular-nums">{shownQuantity(item.recommendedQty, item.unit, 'Нет данных')}</strong>
                    </p>
                    <IngredientDetails item={item} schedule={schedule} risks={<RiskList item={item} />} />
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
