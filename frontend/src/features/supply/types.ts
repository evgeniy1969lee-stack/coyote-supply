export type Unit = 'ml' | 'g' | 'pcs'

export type Store = {
  storeId: string
  name: string
  timeZone: string
  asOf: string
}

export type DraftInputRow = { ingredientId: string; quantity: number }

export type Draft = {
  forecastId: string
  rows: (DraftInputRow & { packCount: number; packPriceKzt: number; lineTotalKzt: number })[]
  totalKzt: number
  savedAt: string
}

export type DataIssue =
  | 'missing_on_hand'
  | 'stale_on_hand'
  | 'insufficient_history'
  | 'missing_recipe'
  | 'missing_schedule'
  | 'unknown_lot_expiry'

export type Risk =
  | { type: 'stockout'; date: string; firstUnmetQty: number; quantity: number }
  | { type: 'excess'; date: string; quantity: number }
  | { type: 'expiry'; date: string; quantity: number; lotId: string }
  | { type: 'insufficient_data'; reason: DataIssue }

export type IngredientForecast = {
  ingredientId: string
  name: string
  unit: Unit
  onHandQty: number | null
  daily: {
    date: string
    demandQty: number
    incomingQty: number
    closingQty: number
    unmetQty: number
    expiringQty: number | null
  }[]
  risks: Risk[]
  recommendedQty: number | null
  packQty: number
  packPriceKzt: number
  explanation: {
    demandBeforeArrivalQty: number
    shortageBeforeArrivalQty: number
    uncoveredWindowDemandQty: number
    safetyStockQty: number
    endStockWithoutOrderQty: number
    unroundedOrderQty: number
  } | null
  dataStatus: 'ok' | 'needs_review'
}

export type Forecast = {
  storeId: string
  forecastId: string
  dataMode: 'synthetic' | 'imported'
  asOf: string
  schedule: {
    orderDeadlineAt: string
    arrivalDate: string
    nextArrivalDate: string
  } | null
  ingredients: IngredientForecast[]
}
