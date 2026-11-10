import type { Unit } from './types'

const numberFormat = new Intl.NumberFormat('ru-KZ', { maximumFractionDigits: 3 })
const calendarFormat = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'long',
  timeZone: 'UTC',
})
const dayFormat = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', timeZone: 'UTC' })
const units: Record<Unit, string> = { ml: 'л', g: 'кг', pcs: 'шт.' }

function calendarDate(value: string) {
  return new Date(`${value}T00:00:00Z`)
}

export function formatQuantity(value: number, unit: Unit) {
  const quantity = unit === 'pcs' ? value : value / 1000
  return `${numberFormat.format(quantity)} ${units[unit]}`
}

export function formatStoreName(name: string) {
  return name.replace(/ · демо$/u, '')
}

export function formatKzt(value: number) {
  return `${numberFormat.format(value)} ₸`
}

export function formatDate(value: string) {
  return calendarFormat.format(calendarDate(value))
}

export function formatTimestamp(value: string, timeZone: string) {
  return new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric',
    month: 'long',
    hour: '2-digit',
    minute: '2-digit',
    timeZone,
  }).format(new Date(value))
}

export function localCalendarDate(value: string, timeZone: string) {
  const parts = new Intl.DateTimeFormat('en', {
    year: 'numeric', month: '2-digit', day: '2-digit', timeZone,
  }).formatToParts(new Date(value))
  return ['year', 'month', 'day'].map((part) => parts.find((entry) => entry.type === part)?.value).join('-')
}

export function formatCoverage(arrival: string, nextArrival: string) {
  const start = calendarDate(arrival)
  const end = calendarDate(nextArrival)
  end.setUTCDate(end.getUTCDate() - 1)
  if (start.getTime() === end.getTime()) return calendarFormat.format(end)
  const sameMonth = start.getUTCFullYear() === end.getUTCFullYear() &&
    start.getUTCMonth() === end.getUTCMonth()
  return `${sameMonth ? dayFormat.format(start) : calendarFormat.format(start)}–${calendarFormat.format(end)}`
}
