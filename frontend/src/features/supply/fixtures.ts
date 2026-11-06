import almaty from '../../../../docs/fixtures/almaty-demo/forecast.json'
import shymkent from '../../../../docs/fixtures/shymkent-demo/forecast.json'
import storesFixture from '../../../../docs/fixtures/stores.json'

import type { Forecast, Store } from './types'

export const stores: readonly Store[] = storesFixture.stores

// S01 checks these JSON files against the API schema. JSON imports widen enum strings.
const forecasts = new Map<string, Forecast>(
  [shymkent as Forecast, almaty as Forecast].map((forecast) => [forecast.storeId, forecast]),
)

export function getFixtureForecast(storeId: string): Forecast | undefined {
  return forecasts.get(storeId)
}
