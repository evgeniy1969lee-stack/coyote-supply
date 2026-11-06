import { formatQuantity } from './format'
import type { IngredientForecast } from './types'

export function OrderCalculation({ item }: { item: IngredientForecast }) {
  const { explanation, recommendedQty, unit } = item
  if (!explanation || recommendedQty === null) return null
  const missingReserve = Math.max(0, explanation.safetyStockQty - explanation.endStockWithoutOrderQty)

  return (
    <p>
      {formatQuantity(explanation.uncoveredWindowDemandQty, unit)} непокрытого расхода
      {' + '}{formatQuantity(missingReserve, unit)} резерва
      {recommendedQty > explanation.unroundedOrderQty && ' · округлено до упаковки'}
    </p>
  )
}
