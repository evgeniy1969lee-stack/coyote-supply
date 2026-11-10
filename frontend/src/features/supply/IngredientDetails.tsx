import type { ReactNode } from 'react'
import { ArrowUpRight } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'

import { formatCoverage, formatDate, formatKzt, formatQuantity } from './format'
import { OrderCalculation } from './OrderCalculation'
import { IngredientPhoto } from './IngredientPhoto'
import type { Forecast, IngredientForecast } from './types'

export function IngredientDetails({ item, schedule, risks }: {
  item: IngredientForecast
  schedule: Forecast['schedule']
  risks: ReactNode
}) {
  const { name, unit, recommendedQty, onHandQty, daily, explanation, packQty, packPriceKzt } = item
  const maxDemand = Math.max(1, ...daily.map((day) => day.demandQty))
  const quantity = (value: number) => formatQuantity(value, unit)

  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button variant="ghost" aria-label={`Детали: ${name}`} className="h-11 px-2 text-primary">
          Детали <ArrowUpRight aria-hidden="true" />
        </Button>
      </SheetTrigger>
      <SheetContent showCloseButton={false} className="w-full gap-0 overflow-y-auto bg-card sm:max-w-[480px]">
        <SheetHeader className="sheet-masthead flex-row items-start justify-between gap-3 border-b border-border p-4 sm:p-6">
          <div className="flex min-w-0 items-center gap-3">
            <IngredientPhoto ingredientId={item.ingredientId} />
            <div className="min-w-0 space-y-1">
              <SheetTitle className="text-2xl font-extrabold tracking-tight wrap-break-word">{name}</SheetTitle>
              <SheetDescription>Прогноз и расчёт закупки</SheetDescription>
            </div>
          </div>
          <SheetClose asChild><Button variant="outline" className="h-11">Закрыть</Button></SheetClose>
        </SheetHeader>

        <div className="space-y-6 p-4 sm:p-6">
          <section aria-label="Рекомендация" className="space-y-2 rounded-lg bg-accent p-4 text-accent-foreground">
            <p className="text-xs font-medium">
              {schedule ? `К закупке на ${formatCoverage(schedule.arrivalDate, schedule.nextArrivalDate)}` : 'К закупке'}
            </p>
            <p className="text-4xl leading-none font-extrabold tracking-tight tabular-nums">
              {recommendedQty === null ? 'Нет данных' : quantity(recommendedQty)}
            </p>
            <div className="text-sm"><OrderCalculation item={item} /></div>
            {recommendedQty !== null && recommendedQty > 0 && (
              <p className="border-t border-primary/20 pt-2 text-xs">
                {recommendedQty / packQty} уп. × {quantity(packQty)} · {formatKzt(recommendedQty / packQty * packPriceKzt)}
              </p>
            )}
          </section>

          <section aria-label="Остаток и риски" className="space-y-2">
            <h3 className="font-semibold">Остаток и риски</h3>
            <p>На складе · {onHandQty === null ? 'нет данных' : quantity(onHandQty)}</p>
            {explanation && (
              <p className="text-muted-foreground">
                Потребность до поставки · {quantity(explanation.demandBeforeArrivalQty)}
                {explanation.shortageBeforeArrivalQty > 0 && (
                  <span className="block text-destructive">Не хватит до поставки · {quantity(explanation.shortageBeforeArrivalQty)}</span>
                )}
              </p>
            )}
            {risks}
          </section>

          <section aria-label="Прогноз" className="space-y-2">
            <h3 className="font-semibold">Прогноз по дням</h3>
            {daily.length > 0 ? (
              <>
                <p className="text-xs text-muted-foreground">Сценарий без новой закупки. Остаток на конец дня.</p>
                <table aria-label="Прогноз по дням" className="w-full border-collapse text-xs tabular-nums">
                  <thead className="bg-muted text-muted-foreground">
                    <tr>
                      <th scope="col" className="px-1.5 py-2 text-start font-medium">Дата</th>
                      <th scope="col" className="px-1 py-2 text-end font-medium">Расход</th>
                      <th scope="col" className="px-1 py-2 text-end font-medium">Остаток</th>
                      <th scope="col" className="px-1 py-2 text-end font-medium">Нехватка</th>
                    </tr>
                  </thead>
                  <tbody>
                    {daily.map((day) => (
                      <tr key={day.date} className="border-b border-border align-top">
                        <th scope="row" className="px-1.5 py-2 text-start font-medium">
                          <time dateTime={day.date}>{formatDate(day.date)}</time>
                          {day.date === schedule?.arrivalDate && <span className="block text-primary">Дата поставки</span>}
                          {day.incomingQty > 0 && <span className="block text-muted-foreground">Приход {quantity(day.incomingQty)}</span>}
                        </th>
                        <td className="px-1 py-2 text-end">
                          {quantity(day.demandQty)}
                          <div aria-hidden="true" className="mt-1 ms-auto h-1 w-full max-w-14 rounded-full bg-accent">
                            <div className="h-full rounded-full bg-primary" style={{ width: `${day.demandQty / maxDemand * 100}%` }} />
                          </div>
                        </td>
                        <td className="px-1 py-2 text-end">{quantity(day.closingQty)}</td>
                        <td className={`px-1 py-2 text-end ${day.unmetQty > 0 ? 'font-semibold text-destructive' : 'text-muted-foreground'}`}>
                          {quantity(day.unmetQty)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            ) : <p className="text-muted-foreground">Недостаточно данных для расчёта по дням.</p>}
          </section>
        </div>
      </SheetContent>
    </Sheet>
  )
}
