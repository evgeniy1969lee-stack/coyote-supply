import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { Camera, MapPin, QrCode, Radio, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { formatStoreName, formatTimestamp } from '@/features/supply/format'
import type { Store } from '@/features/supply/types'
import { analyzeLiveFrame, loadLiveVision, recordLiveCode, requestError, type LiveEvent } from './api'

const SCAN_MS = 440
const MODEL_MS = 15_000
const stationKey = 'coyote-vision-station'

function stationId() {
  try {
    const saved = localStorage.getItem(stationKey)
    if (saved && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(saved)) return saved
    const id = crypto.randomUUID()
    localStorage.setItem(stationKey, id)
    return id
  } catch {
    return crypto.randomUUID()
  }
}

type Detection = { name: string; source: LiveEvent['source']; box?: CSSProperties }
type CameraSession = { controller: AbortController; stream?: MediaStream; timer?: number }
type LiveCatalog = Awaited<ReturnType<typeof loadLiveVision>>['products']

function closeCamera(session: CameraSession | null) {
  if (!session) return
  session.controller.abort()
  window.clearInterval(session.timer)
  session.stream?.getTracks().forEach((track) => track.stop())
}

function cropForModel(video: HTMLVideoElement, canvas: HTMLCanvasElement) {
  const width = Math.floor(video.videoWidth * 0.7)
  const height = Math.floor(video.videoHeight * 0.7)
  const scale = Math.min(1, 640 / Math.max(width, height))
  canvas.width = Math.round(width * scale)
  canvas.height = Math.round(height * scale)
  canvas.getContext('2d')?.drawImage(video, (video.videoWidth - width) / 2,
    (video.videoHeight - height) / 2, width, height, 0, 0, canvas.width, canvas.height)
  return new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.78))
}

function LiveSession({ store }: { store: Store }) {
  const [catalog, setCatalog] = useState<LiveCatalog | null>(null)
  const [events, setEvents] = useState<LiveEvent[]>([])
  const [journalError, setJournalError] = useState('')
  const [cameraError, setCameraError] = useState('')
  const [modelError, setModelError] = useState('')
  const [models, setModels] = useState(false)
  const [phase, setPhase] = useState<'off' | 'starting' | 'live'>('off')
  const [detection, setDetection] = useState<Detection | null>(null)
  const [notice, setNotice] = useState('')
  const [aspect, setAspect] = useState(16 / 9)
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([])
  const [deviceId, setDeviceId] = useState('')
  const video = useRef<HTMLVideoElement>(null)
  const camera = useRef<CameraSession | null>(null)
  const modelsEnabled = useRef(false)

  function mergeEvents(next: LiveEvent[]) {
    setEvents((previous) => {
      const seen = new Map([...previous, ...next].map((event) => [event.eventId, event]))
      return [...seen.values()].sort((a, b) => Date.parse(b.observedAt) - Date.parse(a.observedAt)).slice(0, 40)
    })
  }

  useEffect(() => {
    const controller = new AbortController()
    const refresh = async () => {
      try {
        const data = await loadLiveVision(store.storeId, controller.signal)
        if (!controller.signal.aborted) {
          setCatalog(data.products)
          mergeEvents(data.events)
          setJournalError('')
        }
      } catch (error) {
        if (!controller.signal.aborted) setJournalError(requestError(error))
      }
    }
    void refresh()
    const timer = window.setInterval(() => { if (!document.hidden) void refresh() }, 10_000)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [store.storeId])

  useEffect(() => () => closeCamera(camera.current), [])

  function stop() {
    closeCamera(camera.current)
    camera.current = null
    if (video.current) video.current.srcObject = null
    setPhase('off')
    setDetection(null)
    setModelError('')
  }

  async function start() {
    if (camera.current || !video.current || !catalog) return
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraError('Камера доступна по HTTPS или через localhost.')
      return
    }
    setCameraError('')
    setPhase('starting')
    const session: CameraSession = { controller: new AbortController() }
    camera.current = session
    const { signal } = session.controller
    const player = video.current
    try {
      session.stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: { ideal: 'environment' },
          ...(deviceId ? { deviceId: { exact: deviceId } } : {}) },
      })
      if (signal.aborted) { closeCamera(session); return }
      const track = session.stream.getVideoTracks()[0]
      track.addEventListener('ended', () => {
        if (!signal.aborted) { stop(); setCameraError('Камера отключилась. Проверьте подключение.') }
      }, { once: true, signal })
      player.srcObject = session.stream
      await player.play()
      const { default: jsQR } = await import('jsqr')
      if (signal.aborted) return
      setAspect(player.videoWidth && player.videoHeight ? player.videoWidth / player.videoHeight : 16 / 9)
      setPhase('live')
      void navigator.mediaDevices.enumerateDevices().then((list) => {
        if (!signal.aborted) {
          setDevices(list.filter((device) => device.kind === 'videoinput'))
          setDeviceId(track.getSettings().deviceId ?? '')
        }
      }).catch(() => {})

      const station = stationId()
      const productNames = new Map(catalog.map((product) => [product.code, product.name]))
      const scanCanvas = document.createElement('canvas')
      const pixels = scanCanvas.getContext('2d', { willReadFrequently: true })
      if (!pixels) throw new Error('Не удалось начать обработку видео.')
      const modelCanvas = document.createElement('canvas')
      let candidate = ''
      let matches = 0
      let lastSeen = 0
      let modelNext = performance.now() + MODEL_MS
      let modelBusy = false
      let codeBusy = false
      let pending: { code: string; eventId: string; saved: boolean; retryAt: number } | null = null

      async function inspectFrame() {
        modelBusy = true
        try {
          const blob = await cropForModel(player, modelCanvas)
          if (!blob || signal.aborted || !modelsEnabled.current || document.hidden) return
          const result = await analyzeLiveFrame(store.storeId, station, blob, signal)
          if (signal.aborted) return
          if (result.event) {
            mergeEvents([result.event])
            setNotice(`${result.event.ingredientName} · подсказка записана`)
          }
          if (modelsEnabled.current && !candidate && !document.hidden) {
            setDetection(result.ingredientName ? { name: result.ingredientName, source: 'model' } : null)
            setModelError('')
          }
        } catch (error) {
          if (!signal.aborted && modelsEnabled.current) setModelError(requestError(error))
        } finally {
          modelBusy = false
          modelNext = performance.now() + MODEL_MS
        }
      }

      async function saveCode(observation: NonNullable<typeof pending>) {
        codeBusy = true
        try {
          const event = await recordLiveCode(store.storeId, {
            code: observation.code, eventId: observation.eventId, stationId: station,
          }, signal)
          if (signal.aborted) return
          observation.saved = true
          mergeEvents([event])
          setNotice(`${event.ingredientName} · наблюдение записано`)
          setCameraError('')
        } catch (error) {
          if (!signal.aborted) { observation.retryAt = performance.now() + 2500; setCameraError(requestError(error)) }
        } finally {
          codeBusy = false
        }
      }

      session.timer = window.setInterval(() => {
        if (document.hidden || player.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || !player.videoWidth || !player.videoHeight) return
        const now = performance.now()
        const scale = Math.min(1, 960 / Math.max(player.videoWidth, player.videoHeight))
        const width = Math.round(player.videoWidth * scale)
        const height = Math.round(player.videoHeight * scale)
        if (scanCanvas.width !== width || scanCanvas.height !== height) {
          scanCanvas.width = width
          scanCanvas.height = height
          setAspect(width / height)
        }
        pixels.drawImage(player, 0, 0, width, height)
        const qr = jsQR(pixels.getImageData(0, 0, width, height).data, width, height, { inversionAttempts: 'dontInvert' })
        const name = qr && productNames.get(qr.data)
        if (qr && name) {
          matches = candidate === qr.data ? matches + 1 : 1
          candidate = qr.data
          lastSeen = now
          const { topLeftCorner, topRightCorner, bottomLeftCorner, bottomRightCorner } = qr.location
          const points = [topLeftCorner, topRightCorner, bottomLeftCorner, bottomRightCorner]
          const xs = points.map((point) => point.x / width * 100)
          const ys = points.map((point) => point.y / height * 100)
          setDetection({ name, source: 'code', box: {
            left: `${Math.min(...xs)}%`, top: `${Math.min(...ys)}%`,
            width: `${Math.max(...xs) - Math.min(...xs)}%`, height: `${Math.max(...ys) - Math.min(...ys)}%`,
          } })
          if (matches >= 2 && pending?.code !== qr.data) {
            pending = { code: qr.data, eventId: crypto.randomUUID(), saved: false, retryAt: 0 }
          }
          if (pending?.code === qr.data && !pending.saved && !codeBusy && now >= pending.retryAt) void saveCode(pending)
          return
        }
        candidate = ''
        matches = 0
        setDetection((previous) => previous?.source === 'code' ? null : previous)
        if (now - lastSeen >= 2_000 && !codeBusy) pending = null
        if (modelsEnabled.current && !modelBusy && now >= modelNext) void inspectFrame()
      }, SCAN_MS)
    } catch (error) {
      if (!signal.aborted) {
        stop()
        setCameraError(error instanceof DOMException && error.name === 'NotAllowedError'
          ? 'Разрешите камеру для этого сайта в настройках браузера.'
          : 'Не удалось открыть камеру. Проверьте подключение и выбранный источник.')
      }
    }
  }

  return (
    <div className="vision-session">
      <div className="vision-preview vision-live-preview" style={{ aspectRatio: aspect }}>
        <video ref={video} autoPlay muted playsInline aria-label="Прямой эфир камеры" />
        {phase === 'live' ? (
          <>
            <span className="vision-preview-tag vision-live-tag"><i aria-hidden="true" /> В эфире</span>
            {detection?.box && <span className="vision-live-box" style={detection.box} aria-hidden="true" />}
            <span className="vision-live-reading">
              {detection ? `${detection.name} · ${detection.source === 'code' ? 'метка' : 'подсказка'}` : 'Камера ждёт продукт'}
            </span>
          </>
        ) : (
          <div className="vision-placeholder">
            <Camera aria-hidden="true" />
            <strong>{phase === 'starting' ? 'Подключаем камеру…' : 'Камера выключена'}</strong>
            <span>Направьте камеру на рабочую поверхность.</span>
          </div>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" className="min-h-11" disabled={!catalog && phase === 'off'}
          onClick={() => { if (phase === 'off') void start(); else stop() }}>
          {phase === 'off' ? 'Запустить камеру' : phase === 'starting' ? 'Отменить' : 'Остановить камеру'}
        </Button>
        <Button asChild variant="outline" className="min-h-11">
          <a href="/vision-labels.html" target="_blank" rel="noreferrer"><QrCode aria-hidden="true" /> Метки для продуктов</a>
        </Button>
      </div>
      {devices.length > 1 && (
        <label className="vision-field text-sm">Источник камеры
          <select className="min-h-11 rounded-lg border border-border bg-card px-3" value={deviceId}
            disabled={phase !== 'off'} onChange={(event) => setDeviceId(event.target.value)}>
            {devices.map((device, index) => <option key={device.deviceId} value={device.deviceId}>{device.label || `Камера ${index + 1}`}</option>)}
          </select>
        </label>
      )}
      <label className="flex items-start gap-3 rounded-xl border border-border p-3 text-sm">
        <input className="mt-1 size-4 shrink-0 accent-primary" type="checkbox" checked={models} onChange={(event) => {
          modelsEnabled.current = event.target.checked
          setModels(event.target.checked)
          if (!event.target.checked) { setModelError(''); setDetection((previous) => previous?.source === 'model' ? null : previous) }
        }} />
        <span><strong>Подсказки модели по внешнему виду</strong><br />
          <span className="text-muted-foreground">Без метки в модель отправляется центральная часть кадра примерно раз в 15 секунд. Кадры не сохраняются.</span>
        </span>
      </label>
      {cameraError && <p role="alert" className="text-sm text-primary">{cameraError}</p>}
      {modelError && <p role="status" className="text-sm text-muted-foreground">{modelError}</p>}
      <p role="status" className="sr-only">{notice}</p>
      <section className="vision-journal" aria-labelledby="vision-journal-title">
        <h3 id="vision-journal-title" className="font-extrabold">Журнал наблюдений</h3>
        <p className="mt-1 text-sm text-muted-foreground">Продукт, источник и время. Записи не меняют остатки.</p>
        {journalError && <p role="alert" className="mt-3 text-sm text-primary">{journalError}</p>}
        {!journalError && !catalog && <p className="mt-3 text-sm text-muted-foreground">Загружаем журнал…</p>}
        {catalog && events.length === 0 && <p className="mt-3 text-sm text-muted-foreground">Пока пусто. Поместите продукт с меткой перед камерой.</p>}
        <ul className="mt-3 divide-y divide-border">
          {events.map((event) => {
            const Icon = event.source === 'code' ? QrCode : Sparkles
            return (
              <li className="vision-journal-row" key={event.eventId}>
                <Icon size={18} aria-hidden="true" />
                <div className="min-w-0">
                  <strong>{event.ingredientName}</strong>
                  <span>{event.source === 'code' ? 'Метка упаковки' : 'Подсказка модели'} · камера {event.stationId.slice(0, 4).toUpperCase()}</span>
                </div>
                <time dateTime={event.observedAt}>{formatTimestamp(event.observedAt, store.timeZone)}</time>
              </li>
            )
          })}
        </ul>
      </section>
    </div>
  )
}

export function VisionLive({ store }: { store: Store }) {
  const [open, setOpen] = useState(false)
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild><Button type="button" className="h-11"><Radio aria-hidden="true" /> Открыть Live</Button></SheetTrigger>
      <SheetContent showCloseButton={false} className="w-full gap-0 overflow-y-auto bg-card sm:max-w-[584px]">
        <SheetHeader className="sheet-masthead flex-row items-start justify-between gap-3 border-b border-border p-4 sm:p-6">
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-primary">
              <MapPin size={14} aria-hidden="true" /> {formatStoreName(store.name)}
            </div>
            <SheetTitle className="text-2xl font-extrabold tracking-tight">Coyote Vision Live</SheetTitle>
            <SheetDescription className="mt-1">Рабочая камера и журнал этой кофейни.</SheetDescription>
          </div>
          <SheetClose asChild><Button type="button" variant="outline" className="h-11">Закрыть</Button></SheetClose>
        </SheetHeader>
        {open && <LiveSession key={store.storeId} store={store} />}
      </SheetContent>
    </Sheet>
  )
}
