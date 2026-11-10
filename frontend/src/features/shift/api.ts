import type { Draft, DraftInputRow, Forecast, Store, Unit } from '@/features/supply/types'

type ErrorDetail = { path: string; reason: string }

export class ApiError extends Error {
  readonly status: number
  readonly details: ErrorDetail[]

  constructor(message: string, status: number, details: ErrorDetail[] = []) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.details = details
  }
}

type LossEffect = {
  onHandQty: number
  shortageQty: number | null
  recommendedQty: number | null
}

export type LossRequest = {
  eventId: string
  forecastId: string
  ingredientId: string
  quantity: number
}

export type StockEvent = {
  eventId: string
  ingredientId: string
  name: string
  unit: Unit
  quantity: number
  recordedAt: string
  before: LossEffect
  after: LossEffect
  kind: 'loss' | 'consumption'
  recipeSku: string | null
  todayDemandBefore: number | null
  todayDemandAfter: number | null
}

export type ShiftOverview = {
  storeId: string
  shiftDate: string
  forecast: Forecast
  draft: Draft | null
  guardian: { state: 'alert' | 'watch' | 'calm'; title: string; message: string }
  actions: {
    id: 'stockout' | 'order' | 'expiry' | 'data'
    priority: 'urgent' | 'planned' | 'done'
    title: string
    detail: string
  }[]
  recentLosses: StockEvent[]
  recentConsumptions: StockEvent[]
}

export type ConsumptionRequest = LossRequest & { recipeSku: string }

export type RecipePortion = {
  recipeSku: string
  recipeName: string
  ingredientId: string
  ingredientName: string
  recipeQty: number
  availableQty: number | null
}

export type VisionProposal = {
  model: string
  observation: 'possible_pour' | 'ingredient_visible' | 'unclear'
  ingredientId: string | null
  forecastId: string
  options: RecipePortion[]
}

export type CopilotAnswer = {
  kind: 'recipe' | 'stock' | 'purchase' | 'shortage' | 'shift' | 'loss' | 'unsupported'
  answer: string
  source: string
  model?: string | null
  explanation?: string | null
}

async function jsonRequest<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, init)
  } catch (error) {
    if (init?.signal?.aborted) throw error
    throw new ApiError('Не удалось связаться с сервером. Повторите попытку.', 0)
  }
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    throw new ApiError(
      data?.error?.message ?? 'Сервер не смог выполнить запрос. Повторите попытку.',
      response.status,
      data?.error?.details ?? [],
    )
  }
  if (data === null) throw new ApiError('Сервер вернул неожиданный ответ.', response.status)
  return data as T
}

const storePath = (storeId: string) => `/api/stores/${encodeURIComponent(storeId)}`

function withJson(method: 'POST' | 'PUT', body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

export async function loadStores(signal: AbortSignal) {
  const result = await jsonRequest<{ stores: Store[] }>('/api/stores', { signal })
  return result.stores
}

export function loadShift(storeId: string, signal?: AbortSignal) {
  return jsonRequest<ShiftOverview>(`${storePath(storeId)}/shift`, { signal })
}

export function recordLoss(storeId: string, request: LossRequest) {
  return jsonRequest<ShiftOverview>(`${storePath(storeId)}/shift/losses`, withJson('POST', request))
}

export function analyzeVision(storeId: string, frame: Blob, signal: AbortSignal) {
  return jsonRequest<VisionProposal>(`${storePath(storeId)}/shift/vision`, {
    method: 'POST', headers: { 'Content-Type': 'image/jpeg' }, body: frame, signal,
  })
}

export function recordConsumption(storeId: string, request: ConsumptionRequest) {
  return jsonRequest<ShiftOverview>(`${storePath(storeId)}/shift/consumptions`, withJson('POST', request))
}

export function askCopilot(storeId: string, question: string) {
  return jsonRequest<CopilotAnswer>(`${storePath(storeId)}/shift/copilot`, withJson('POST', { question }))
}

export async function saveDraft(storeId: string, forecastId: string, rows: DraftInputRow[]) {
  const result = await jsonRequest<{ storeId: string; draft: Draft | null }>(
    `${storePath(storeId)}/draft`, withJson('PUT', { forecastId, rows }),
  )
  return result.draft
}

export function requestError(error: unknown) {
  return error instanceof Error ? error.message : 'Запрос не удалось выполнить.'
}
