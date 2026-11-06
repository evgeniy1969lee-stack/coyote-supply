import type { ReactNode } from 'react'
import { CircleAlert, CircleCheck } from 'lucide-react'

import { formatCoverage, formatDate, formatQuantity, formatTimestamp } from './format'
import type { Forecast, Risk } from './types'

export function PurchasePlan({ forecast, timeZone, action }: {
  forecast: Forecast
  timeZone: string
  action: ReactNode
}) {
  const { ingredients, schedule } = forecast
  const shortages = ingredients.flatMap((ingredient) =>
    ingredient.risks
      .filter((risk): risk is Extract<Risk, { type: 'stockout' }> => risk.type === 'stockout')
      .map((risk) => ({ ingredient, risk })),
  ).sort((a, b) => a.risk.date.localeCompare(b.risk.date))
  const shortage = shortages[0]
  const firstAtRisk = shortage?.ingredient
  const ingredient = (firstAtRisk?.recommendedQty ?? 0) > 0
    ? firstAtRisk
    : ingredients.find((item) => (item.recommendedQty ?? 0) > 0)
  const recommendation = ingredient?.recommendedQty
  const needsReview = ingredients.some((item) => item.dataStatus === 'needs_review')

  return (
    <section aria-label="План поставки" className="purchase-plan">
      <div className="purchase-hero">
        <div className="purchase-photo" aria-hidden="true">
          <img src="/coffee-counter.webp" alt="" width={1536} height={1024} fetchPriority="high" />
        </div>
        <div className="purchase-copy">
          <h2 className="purchase-title motion-heading">
            {schedule ? <>Поставка <time dateTime={schedule.arrivalDate}>{formatDate(schedule.arrivalDate)}</time></> : 'Следующая поставка'}
          </h2>
          {!schedule ? (
            <p className="mt-3 text-base">Расписание неизвестно</p>
          ) : ingredient && recommendation != null ? (
            <>
              <p className="mt-3 text-base wrap-break-word">
                {ingredient.name} <span aria-hidden="true">·</span>{' '}
                <strong className="text-xl font-extrabold tabular-nums">{formatQuantity(recommendation, ingredient.unit)}</strong> к закупке
              </p>
              <p className="mt-1 text-sm text-[#f4d9d9]">
                Запас на {formatCoverage(schedule.arrivalDate, schedule.nextArrivalDate)}
              </p>
            </>
          ) : (
            <p className="mt-3 text-base">
              {needsReview ? 'Проверьте данные для закупки' : 'Закупка не требуется'}
            </p>
          )}
          <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-3">
            {action}
            {schedule && (
              <p className="text-xs font-semibold text-[#f4d9d9]">
                Заказать до <time dateTime={schedule.orderDeadlineAt}>{formatTimestamp(schedule.orderDeadlineAt, timeZone)}</time>
              </p>
            )}
          </div>
        </div>
      </div>
      <div className="risk-strip">
        {shortage?.ingredient.ingredientId === 'milk' ? (
          <img src="/milk-stock.webp" alt="" width={58} height={58} className="risk-art" />
        ) : (
          <div className={shortage || needsReview ? 'risk-symbol' : 'risk-symbol risk-symbol-clear'} aria-hidden="true">
            {shortage || needsReview ? <CircleAlert size={20} /> : <CircleCheck size={20} />}
          </div>
        )}
        <div className="min-w-0">
          <h3 className="font-extrabold wrap-break-word">
            {shortage
              ? <>Дефицит до поставки · {shortage.ingredient.name}, {formatQuantity(shortage.risk.quantity, shortage.ingredient.unit)}</>
              : needsReview ? 'Проверьте остатки' : 'Дефицит до поставки не выявлен'}
          </h3>
          {shortage && (
            <p className="mt-0.5 text-xs text-muted-foreground">
              Первая нехватка {formatDate(shortage.risk.date)} · {formatQuantity(shortage.risk.firstUnmetQty, shortage.ingredient.unit)}
            </p>
          )}
        </div>
      </div>
    </section>
  )
}
