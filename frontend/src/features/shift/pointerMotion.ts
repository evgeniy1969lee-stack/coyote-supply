import type { PointerEventHandler } from 'react'

const motionQuery = '(hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)'

function followPointer(selector: string, distance: number) {
  const onPointerMove: PointerEventHandler<HTMLElement> = (event) => {
    if (event.pointerType !== 'mouse' || !window.matchMedia(motionQuery).matches) return
    if (!event.currentTarget.contains(event.target as Node)) return
    const { left, top, width, height } = event.currentTarget.getBoundingClientRect()
    if (!width || !height) return

    const clamp = (value: number) => Math.max(-1, Math.min(1, value))
    const x = clamp((event.clientX - left) / width * 2 - 1) * distance
    const y = clamp((event.clientY - top) / height * 2 - 1) * distance
    for (const target of event.currentTarget.querySelectorAll<HTMLElement>(selector)) {
      target.style.setProperty('--cursor-translate', `${x.toFixed(2)}px ${y.toFixed(2)}px`)
    }
  }

  const reset: PointerEventHandler<HTMLElement> = (event) => {
    for (const target of event.currentTarget.querySelectorAll<HTMLElement>(selector)) {
      target.style.removeProperty('--cursor-translate')
    }
  }

  return { onPointerMove, onPointerLeave: reset, onPointerCancel: reset }
}

export const buttonPointerMotion = followPointer('.pointer-button-label', 4)
export const heroPointerMotion = followPointer('.guardian-art, .guardian-kicker, #guardian-title', 8)
