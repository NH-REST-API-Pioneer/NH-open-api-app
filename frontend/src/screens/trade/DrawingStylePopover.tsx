import { useEffect, useRef } from 'react'
import { LINE_SIZES, PALETTE } from './chartIndicators'
import type { DrawingStyle } from './chartDrawings'

/* ── 도형 색·굵기 팝오버 ──────────────────────────────── */

export function DrawingStylePopover({
  style,
  left,
  top,
  onPick,
  onRemove,
  onClose,
}: {
  style: DrawingStyle
  left: number
  top: number
  onPick: (style: DrawingStyle) => void
  onRemove: () => void
  onClose: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onDown = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) onClose()
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
      }
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey, true)
    }
  }, [onClose])

  return (
    <div
      className="ind-picker draw-picker"
      style={{ left, top }}
      role="dialog"
      aria-label="도형 색과 굵기"
      ref={ref}
      onMouseDown={(event) => event.stopPropagation()}
    >
      <p className="ind-picker-title">색</p>
      <div className="ind-swatches">
        {PALETTE[0].map((_, shade) =>
          PALETTE.map((row, hue) => {
            const hex = row[shade]
            return (
              <button
                key={`${hue}-${shade}`}
                type="button"
                className="ind-swatch"
                aria-label={`색 ${hue + 1}-${shade + 1}`}
                aria-pressed={hex === style.color}
                style={{ background: hex }}
                onClick={() => onPick({ ...style, color: hex })}
              />
            )
          }),
        )}
      </div>
      <p className="ind-picker-title">굵기</p>
      <div className="ind-sizes">
        {LINE_SIZES.map((px) => (
          <button
            key={px}
            type="button"
            className="ind-size"
            aria-pressed={px === style.size}
            onClick={() => onPick({ ...style, size: px })}
          >
            <span className="ind-size-line" style={{ height: px, background: style.color }} />
            {px}px
          </button>
        ))}
      </div>
      <button type="button" className="btn btn-quiet draw-picker-remove" onClick={onRemove}>
        삭제
      </button>
    </div>
  )
}
