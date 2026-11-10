import { useEffect, useRef, useState } from 'react'
import { Camera, ImagePlus, ScanLine, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'

const examplePath = '/vision-example.jpg'

function jpegFrame(source: CanvasImageSource, width: number, height: number): Promise<Blob> {
  const canvas = document.createElement('canvas')
  const scale = Math.min(1, 640 / Math.max(width, height))
  canvas.width = Math.round(width * scale)
  canvas.height = Math.round(height * scale)
  const context = canvas.getContext('2d', { alpha: false })
  if (!context || Math.min(canvas.width, canvas.height) < 32) {
    return Promise.reject(new Error('Выберите более крупное изображение.'))
  }
  context.fillStyle = '#fff'
  context.fillRect(0, 0, canvas.width, canvas.height)
  context.drawImage(source, 0, 0, canvas.width, canvas.height)
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error('Не удалось подготовить кадр.')), 'image/jpeg', 0.86)
  })
}

export function VisionCapture({ disabled, onCapture }: {
  disabled: boolean
  onCapture: (frame: Blob | null) => void
}) {
  const video = useRef<HTMLVideoElement>(null)
  const file = useRef<HTMLInputElement>(null)
  const stream = useRef<MediaStream | null>(null)
  const active = useRef(false)
  const [camera, setCamera] = useState(false)
  const [ready, setReady] = useState(false)
  const [pending, setPending] = useState(false)
  const [preview, setPreview] = useState<{ url: string; label: string } | null>(null)
  const [error, setError] = useState('')
  const blocked = disabled || pending

  useEffect(() => {
    active.current = true
    return () => {
      active.current = false
      stream.current?.getTracks().forEach((track) => track.stop())
    }
  }, [])

  useEffect(() => {
    const url = preview?.url
    return () => { if (url) URL.revokeObjectURL(url) }
  }, [preview])

  function stopCamera() {
    stream.current?.getTracks().forEach((track) => track.stop())
    stream.current = null
    if (video.current) video.current.srcObject = null
    setReady(false)
    setCamera(false)
  }

  function showFrame(frame: Blob, label: string) {
    stopCamera()
    setPreview({ url: URL.createObjectURL(frame), label })
    onCapture(frame)
  }

  async function startCamera() {
    if (!navigator.mediaDevices?.getUserMedia) {
      setError('Камера недоступна в этом браузере. Загрузите фото или выберите пример.')
      return
    }
    setPending(true)
    setError('')
    setPreview(null)
    onCapture(null)
    try {
      const feed = await navigator.mediaDevices.getUserMedia({
        audio: false, video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 } },
      })
      const player = video.current
      if (!active.current || !player) {
        feed.getTracks().forEach((track) => track.stop())
        return
      }
      stream.current = feed
      player.srcObject = feed
      setCamera(true)
    } catch {
      if (active.current) setError('Нет доступа к камере. Разрешите его в браузере или загрузите фото.')
    } finally {
      if (active.current) setPending(false)
    }
  }

  async function capture() {
    const player = video.current
    if (!player?.videoWidth || !player.videoHeight) return
    setPending(true)
    setError('')
    try {
      const frame = await jpegFrame(player, player.videoWidth, player.videoHeight)
      if (active.current) showFrame(frame, 'Кадр с камеры')
    } catch {
      if (active.current) setError('Не удалось сделать снимок. Попробуйте ещё раз.')
    } finally {
      if (active.current) setPending(false)
    }
  }

  async function loadPhoto(image?: File) {
    setPending(true)
    setError('')
    setPreview(null)
    onCapture(null)
    try {
      let blob: Blob
      if (image) {
        if (image.size > 15_000_000) throw new Error('Выберите фото до 15 МБ.')
        blob = image
      } else {
        const response = await fetch(examplePath)
        if (!response.ok) throw new Error('Пример кадра недоступен.')
        blob = await response.blob()
      }
      const bitmap = await createImageBitmap(blob)
      try {
        const frame = await jpegFrame(bitmap, bitmap.width, bitmap.height)
        if (active.current) showFrame(frame, image ? 'Загруженное фото' : 'Пример кадра')
      } finally {
        bitmap.close()
      }
    } catch (failure) {
      if (active.current) {
        setError(failure instanceof Error && failure.message === 'Выберите фото до 15 МБ.'
          ? failure.message : 'Не удалось открыть фото. Выберите другое изображение.')
      }
    } finally {
      if (active.current) setPending(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="vision-preview">
        <video ref={video} hidden={!camera} muted autoPlay playsInline onLoadedData={() => setReady(true)} />
        {preview && <img src={preview.url} alt={preview.label} />}
        {!camera && !preview && (
          <div className="vision-placeholder">
            <ScanLine size={30} aria-hidden="true" />
            <strong>Ингредиент и чашка в кадре</strong>
            <span>Сделайте снимок или загрузите фото.</span>
          </div>
        )}
        {(camera || preview) && <span className="vision-preview-tag">{camera ? 'Камера включена' : preview?.label}</span>}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {camera ? (
          <>
            <Button type="button" className="h-11" disabled={blocked || !ready} onClick={() => void capture()}>
              <Camera aria-hidden="true" /> Сделать снимок
            </Button>
            <Button type="button" variant="outline" className="h-11" disabled={blocked} onClick={stopCamera}>Выключить</Button>
          </>
        ) : (
          <>
            <Button type="button" variant="outline" className="h-11" disabled={blocked} onClick={() => void startCamera()}>
              <Camera aria-hidden="true" /> Включить камеру
            </Button>
            <input ref={file} type="file" accept="image/*" hidden onChange={(event) => {
              const selected = event.currentTarget.files?.[0]
              event.currentTarget.value = ''
              if (selected) void loadPhoto(selected)
            }} />
            <Button type="button" variant="outline" className="h-11" disabled={blocked} onClick={() => file.current?.click()}>
              <ImagePlus aria-hidden="true" /> Загрузить фото
            </Button>
            <Button type="button" variant="ghost" className="h-11 text-primary" disabled={blocked} onClick={() => void loadPhoto()}>
              <Sparkles aria-hidden="true" /> Пример кадра
            </Button>
          </>
        )}
      </div>
      {pending && <p role="status" className="text-sm text-muted-foreground">Подготавливаем кадр…</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </div>
  )
}
