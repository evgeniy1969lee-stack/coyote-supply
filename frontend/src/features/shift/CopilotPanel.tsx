import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ArrowUp, Bot } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { askCopilot, requestError, type CopilotAnswer } from './api'
import { prompts } from './prompts'

export function CopilotPanel({ storeId, initialQuestion }: { storeId: string; initialQuestion: string }) {
  const [question, setQuestion] = useState(initialQuestion)
  const [turns, setTurns] = useState<{ question: string; answer: CopilotAnswer }[]>([])
  const [pending, setPending] = useState('')
  const [error, setError] = useState('')
  const log = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (log.current) log.current.scrollTop = log.current.scrollHeight
  }, [turns, pending])

  async function send(value: string) {
    const text = value.trim()
    if (!text || pending) return
    setPending(text)
    setError('')
    try {
      const answer = await askCopilot(storeId, text)
      setTurns((previous) => [...previous, { question: text, answer }])
      setQuestion('')
    } catch (error) {
      setQuestion(text)
      setError(requestError(error))
    } finally {
      setPending('')
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void send(question)
  }

  return (
    <section className="os-card copilot-chat" aria-label="Чат с помощником" aria-busy={Boolean(pending)}>
      <div className="copilot-heading">
        <div className="os-tile os-tile-violet"><Bot size={22} aria-hidden="true" /></div>
        <div>
          <h2>Диалог смены</h2>
          <p>Ответы по техкартам, остаткам и плану этой точки.</p>
        </div>
      </div>
      <div className="copilot-prompts" aria-label="Примеры вопросов">
        {prompts.map(({ question, icon: Icon }) => (
          <button type="button" key={question} disabled={Boolean(pending)} onClick={() => void send(question)}>
            <Icon size={16} aria-hidden="true" /> {question}
          </button>
        ))}
      </div>
      <div ref={log} className="copilot-log" role="log" aria-label="Ответы помощника" aria-live="polite">
        {turns.length === 0 && !pending && (
          <p className="text-muted-foreground">Выберите вопрос или напишите свой.</p>
        )}
        {turns.map((turn, index) => (
          <div className="copilot-turn" key={index}>
            <p className="copilot-question">{turn.question}</p>
            <div className="copilot-answer">
              {turn.answer.explanation && <p className="mb-2">{turn.answer.explanation}</p>}
              <p>{turn.answer.answer}</p>
              <p className="copilot-source">{turn.answer.source}</p>
            </div>
          </div>
        ))}
        {pending && <p className="text-muted-foreground" role="status">Ищу ответ по данным смены…</p>}
      </div>
      {error && <p role="alert" className="text-destructive">{error}</p>}
      <form onSubmit={submit} className="copilot-form">
        <label className="sr-only" htmlFor="copilot-question">Вопрос для Copilot</label>
        <input id="copilot-question" placeholder="Спросите о смене или рецепте" value={question}
          maxLength={280} disabled={Boolean(pending)} onChange={(event) => setQuestion(event.target.value)} />
        <Button type="submit" className="h-11" disabled={!question.trim() || Boolean(pending)}>
          Отправить <ArrowUp size={17} aria-hidden="true" />
        </Button>
      </form>
    </section>
  )
}
