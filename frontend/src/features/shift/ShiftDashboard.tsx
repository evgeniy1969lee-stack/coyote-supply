import type { ReactNode } from 'react'
import { ArrowRight, Bot, Check, CircleAlert, ClipboardList, Droplets, Package, Sparkles, Timer } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { formatDate, formatQuantity } from '@/features/supply/format'
import type { Risk, Unit } from '@/features/supply/types'
import { prompts } from './prompts'
import { LossSheet } from './LossSheet'
import { buttonPointerMotion, heroPointerMotion } from './pointerMotion'
import type { LossEvent, ShiftOverview } from './api'

const guardianLabels = { alert: 'Требует внимания', watch: 'Под наблюдением', calm: 'По плану' }
const priorities = { urgent: 'Приоритет', planned: 'К проверке', done: 'Готово' }

function quantity(value: number | null, unit: Unit) {
  return value === null ? 'Нет данных' : formatQuantity(value, unit)
}

function LossImpact({ event, onAsk }: { event: LossEvent; onAsk: (question: string) => void }) {
  const metrics = [
    { label: 'Остаток', before: event.before.onHandQty, after: event.after.onHandQty },
    { label: 'Дефицит до поставки', before: event.before.shortageQty, after: event.after.shortageQty },
    { label: 'Рекомендация к закупке', before: event.before.recommendedQty, after: event.after.recommendedQty },
  ]
  return (
    <section className="os-card loss-impact" aria-labelledby="loss-impact-title">
      <div className="loss-impact-head">
        <div className="os-tile os-tile-green"><Check size={22} aria-hidden="true" /></div>
        <div>
          <h2 id="loss-impact-title">Потеря записана</h2>
          <p>{event.name} · {formatQuantity(event.quantity, event.unit)}. Прогноз пересчитан на сервере.</p>
        </div>
        <Button type="button" variant="outline" className="h-11" onClick={() => onAsk('Что изменилось после списания?')}>
          Объяснить пересчёт <ArrowRight aria-hidden="true" />
        </Button>
      </div>
      <dl className="impact-metrics">
        {metrics.map((metric) => (
          <div key={metric.label}>
            <dt>{metric.label}</dt>
            <dd>
              {metric.before === metric.after ? (
                <>{quantity(metric.after, event.unit)} <small>без изменений</small></>
              ) : (
                <><span>{quantity(metric.before, event.unit)}</span><ArrowRight size={15} aria-hidden="true" />{quantity(metric.after, event.unit)}</>
              )}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

export function ShiftDashboard({ shift, onLoss, onRefresh, onSupply, onAsk, draftAction }: {
  shift: ShiftOverview
  onLoss: (data: ShiftOverview) => void
  onRefresh: () => Promise<void>
  onSupply: () => void
  onAsk: (question: string) => void
  draftAction: ReactNode
}) {
  const { guardian, forecast, recentLosses } = shift
  const shortages = forecast.ingredients.flatMap((item) =>
    item.risks.filter((risk): risk is Extract<Risk, { type: 'stockout' }> => risk.type === 'stockout')
      .map((risk) => ({ item, risk })),
  ).sort((a, b) => a.risk.date.localeCompare(b.risk.date) || a.item.ingredientId.localeCompare(b.item.ingredientId))
  const primary = shortages[0]
  const product = primary?.item ?? forecast.ingredients.find((item) => (item.recommendedQty ?? 0) > 0)
  const recent = recentLosses[0]
  const metrics = [
    {
      title: 'Текущий запас', icon: Droplets, tone: 'rose',
      value: product ? quantity(product.onHandQty, product.unit) : '—', note: product?.name ?? 'Склад точки',
    },
    {
      title: 'До прихода поставки', icon: Timer, tone: primary ? 'amber' : 'green',
      value: primary ? formatQuantity(primary.risk.quantity, primary.item.unit) : 'Без дефицита',
      note: primary ? `Первая нехватка ${formatDate(primary.risk.date)}` : 'По позициям с прогнозом',
    },
    {
      title: 'К закупке', icon: Package, tone: 'violet',
      value: product ? quantity(product.recommendedQty, product.unit) : '—',
      note: forecast.schedule ? `Поставка ${formatDate(forecast.schedule.arrivalDate)}` : 'Расписание требует проверки',
    },
  ]
  const hasStock = forecast.ingredients.some((item) => (item.onHandQty ?? 0) > 0)

  return (
    <>
      <section className="guardian-hero" {...heroPointerMotion} data-state={guardian.state} aria-labelledby="guardian-title">
        <div className="guardian-art" aria-hidden="true">
          <div className="guardian-orbit" />
          <img key={`${guardian.state}-${recent?.eventId ?? ''}`} src="/coyote-barista.webp" alt="" width={720} height={670} />
        </div>
        <div className="guardian-copy">
          <div className="guardian-kicker"><Sparkles size={17} aria-hidden="true" /> Shift Guardian</div>
          <h2 id="guardian-title">{guardian.title}</h2>
          <p aria-live="polite">{guardian.message}</p>
          <div className="guardian-actions">
            <LossSheet shift={shift} onChange={onLoss} onRefresh={onRefresh}>
              <Button {...buttonPointerMotion} className="guardian-primary h-11 px-3" disabled={!hasStock}>
                <span className="pointer-button-label"><Droplets aria-hidden="true" /> Записать потерю</span>
              </Button>
            </LossSheet>
            {draftAction}
          </div>
        </div>
        <div className="guardian-mood">
          <span className="guardian-mood-dot" aria-hidden="true" />
          <span>Койот · {guardianLabels[guardian.state]}</span>
        </div>
      </section>

      <div className="sr-only" role="status">
        {recent && `Последняя потеря: ${recent.name}, ${formatQuantity(recent.quantity, recent.unit)}. Прогноз пересчитан.`}
      </div>
      {recent && <LossImpact event={recent} onAsk={onAsk} />}

      <section className="shift-metrics" aria-label="Показатели смены">
        {metrics.map(({ title, icon: Icon, tone, value, note }) => (
          <article className="os-card shift-metric" key={title}>
            <div className={`os-tile os-tile-${tone}`}><Icon size={21} aria-hidden="true" /></div>
            <div>
              <h3>{title}</h3>
              <p className="metric-value">{value}</p>
              <p className="metric-note">{note}</p>
            </div>
          </article>
        ))}
      </section>

      <div className="shift-lower">
        <section className="os-card action-panel" aria-labelledby="shift-plan-title">
          <div className="action-heading">
            <div className="os-tile os-tile-rose"><ClipboardList size={21} aria-hidden="true" /></div>
            <div>
              <h2 id="shift-plan-title">План смены</h2>
              <p>Действия по текущему прогнозу</p>
            </div>
          </div>
          {shift.actions.length === 0 ? <p className="text-muted-foreground">Срочных действий нет.</p> : (
            <ul className="shift-actions">
              {shift.actions.map((action) => (
                <li key={action.id}>
                  <div className="shift-action-line">
                    <div>
                      <div className="shift-action-title">
                        <h3>{action.title}</h3>
                        <span className={`action-status action-${action.priority}`}>{priorities[action.priority]}</span>
                      </div>
                      <p>{action.detail}</p>
                    </div>
                    <Button type="button" variant="ghost" className="h-11 w-11" onClick={onSupply} aria-label={`Открыть закупки · ${action.title}`}>
                      <ArrowRight aria-hidden="true" />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="os-card action-panel copilot-preview" aria-labelledby="copilot-preview-title">
          <div className="action-heading">
            <div className="os-tile os-tile-violet"><Bot size={21} aria-hidden="true" /></div>
            <div>
              <h2 id="copilot-preview-title">Бариста Copilot</h2>
              <p>Техкарты и состояние вашей точки</p>
            </div>
          </div>
          <div className="quick-prompts">
            {prompts.slice(0, recent ? 4 : 3).map(({ question, icon: Icon }) => (
              <button type="button" key={question} onClick={() => onAsk(question)}>
                <Icon size={17} aria-hidden="true" /><span>{question}</span><ArrowRight size={16} aria-hidden="true" />
              </button>
            ))}
          </div>
          {recent && <p className="copilot-hint"><CircleAlert size={16} aria-hidden="true" /> Может объяснить последнее списание.</p>}
        </section>
      </div>
    </>
  )
}
