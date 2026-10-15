import { useCallback, useEffect, useRef, useState } from 'react'

/* 경계선을 잡아 끌어 영역의 폭(또는 높이)을 조절합니다.
 *
 * 끌어놓은 값은 브라우저에 남습니다 — 앱을 다시 열어도 그대로입니다.
 * 설정 파일에 넣을 값이 아니라 화면 상태라 이쪽에 둡니다.
 *
 * 기본값을 `null` 로 주면 「아직 끈 적 없음」을 뜻합니다. 그때는 화면이 원래
 * 배치(비율)대로 서고, 저장소에도 아무것도 남기지 않습니다. 더블클릭이나 Enter 로
 * 기본으로 돌아가면 저장값을 지웁니다.
 */

interface Options<T extends number | null> {
  /** 저장에 쓰는 이름 */
  key: string
  initial: T
  min: number
  max: number
  /** 경계선이 영역의 어느 쪽에 있는지. 왼쪽(위)에 있으면 왼쪽(위)으로 끌수록 커집니다. */
  edge?: 'start' | 'end'
  /** 가로로 끌어 폭을 바꾸면 `x`, 세로로 끌어 높이를 바꾸면 `y` */
  axis?: 'x' | 'y'
  /** 크기를 바꾸는 영역. 아직 끈 적이 없을 때 끌기·키보드가 지금 그려진 크기에서 시작합니다. */
  measure?: () => HTMLElement | null
}

/** 끌기 한 칸. 화살표 키 한 번에 움직이는 양입니다. */
const KEY_STEP = 16

function read<T extends number | null>(key: string, fallback: T): number | T {
  try {
    const saved = window.localStorage.getItem(key)
    const value = saved === null ? Number.NaN : Number(saved)
    // 수가 아니거나 음수인 값은 누가 손으로 고친 것입니다. 기본으로 갑니다.
    return Number.isFinite(value) && value >= 0 ? value : fallback
  } catch {
    // 저장소를 못 쓰는 환경에서도 화면은 기본값으로 떠야 합니다.
    return fallback
  }
}

export function useResizableWidth<T extends number | null>({
  key,
  initial,
  min,
  max,
  edge = 'end',
  axis = 'x',
  measure,
}: Options<T>) {
  const [width, setWidth] = useState<number | T>(() => read(key, initial))
  const [dragging, setDragging] = useState(false)
  // 아직 끈 적이 없을 때 화면에 그려진 크기. 손잡이가 지금 값을 읽어 줄 때 씁니다.
  const [measured, setMeasured] = useState<number | null>(null)
  const measureRef = useRef(measure)
  measureRef.current = measure

  const clamp = useCallback(
    (value: number) => Math.min(Math.max(value, min), Math.max(min, max)),
    [min, max],
  )

  /* 그리는 값. 창이 좁아져 범위가 줄면 **그리는 값만** 범위 안으로 들이고 저장값은
   * 그대로 둡니다 — 창을 다시 넓히면 끌어 둔 크기로 돌아옵니다. */
  const size = width === null ? null : clamp(width)

  const sizeOf = (el: HTMLElement) => (axis === 'x' ? el.offsetWidth : el.offsetHeight)

  // 원래 배치일 때의 크기를 따라 읽습니다. 영역이 나중에 생겨도(받기 전 → 받은 뒤) 잡습니다.
  useEffect(() => {
    const el = measureRef.current?.()
    if (!el) return
    const update = () => setMeasured(sizeOf(el))
    update()
    const watch = new ResizeObserver(update)
    watch.observe(el)
    return () => watch.disconnect()
  })

  /** 지금 화면에 선 크기 — 끌어 둔 값, 없으면 그려진 크기 */
  const current = (): number => {
    if (size !== null) return size
    const el = measureRef.current?.()
    return clamp(el ? sizeOf(el) : (measured ?? min))
  }

  const onHandleDown = useCallback(
    (event: React.MouseEvent) => {
      event.preventDefault()
      const startX = event.clientX
      const startWidth = width ?? min
      setDragging(true)

      const onMove = (move: MouseEvent) => {
        const delta = move.clientX - startX
        setWidth(clamp(edge === 'start' ? startWidth - delta : startWidth + delta))
      }
      const onUp = () => {
        setDragging(false)
        window.removeEventListener('mousemove', onMove)
        window.removeEventListener('mouseup', onUp)
      }

      window.addEventListener('mousemove', onMove)
      window.addEventListener('mouseup', onUp)
    },
    [width, min, clamp, edge],
  )

  /* 포인터를 손잡이에 붙잡아 둡니다. 창 밖에서 놓아도 끌기가 끝나고, 마우스와
   * 터치가 같은 길로 갑니다. */
  const onPointerDown = (event: React.PointerEvent<HTMLElement>) => {
    if (event.button !== 0) return
    event.preventDefault()
    const handle = event.currentTarget
    const start = axis === 'x' ? event.clientX : event.clientY
    const startSize = current()
    handle.setPointerCapture(event.pointerId)
    setDragging(true)

    const onMove = (move: PointerEvent) => {
      const delta = (axis === 'x' ? move.clientX : move.clientY) - start
      setWidth(clamp(edge === 'start' ? startSize - delta : startSize + delta))
    }
    const onEnd = () => {
      setDragging(false)
      handle.removeEventListener('pointermove', onMove)
      handle.removeEventListener('pointerup', onEnd)
      handle.removeEventListener('pointercancel', onEnd)
      handle.removeEventListener('lostpointercapture', onEnd)
    }

    handle.addEventListener('pointermove', onMove)
    handle.addEventListener('pointerup', onEnd)
    handle.addEventListener('pointercancel', onEnd)
    handle.addEventListener('lostpointercapture', onEnd)
  }

  const reset = () => setWidth(initial)

  /* 화살표는 손잡이를 그 쪽으로 한 칸 옮깁니다. Home·End 는 범위의 양 끝,
   * Enter 는 더블클릭과 같이 기본으로 돌아갑니다. */
  const onKeyDown = (event: React.KeyboardEvent<HTMLElement>) => {
    const forward = axis === 'x' ? 'ArrowRight' : 'ArrowDown'
    const back = axis === 'x' ? 'ArrowLeft' : 'ArrowUp'
    const grow = edge === 'start' ? -1 : 1
    let next: number
    if (event.key === forward) next = current() + KEY_STEP * grow
    else if (event.key === back) next = current() - KEY_STEP * grow
    else if (event.key === 'Home') next = min
    else if (event.key === 'End') next = max
    else if (event.key === 'Enter') {
      event.preventDefault()
      reset()
      return
    } else return
    event.preventDefault()
    setWidth(clamp(next))
  }

  /** 손잡이에 그대로 펼쳐 넣는 속성 — 끌기·키보드·더블클릭과 읽어 주는 값 */
  const handleProps = {
    role: 'separator',
    tabIndex: 0,
    'aria-orientation': axis === 'x' ? 'vertical' : 'horizontal',
    'aria-valuenow': Math.round(size ?? measured ?? min),
    'aria-valuemin': min,
    'aria-valuemax': Math.max(min, max),
    'data-dragging': dragging,
    onPointerDown,
    onKeyDown,
    onDoubleClick: reset,
  } as const

  useEffect(() => {
    if (dragging) return
    try {
      if (width === null) window.localStorage.removeItem(key)
      else window.localStorage.setItem(key, String(width))
    } catch {
      // 저장에 실패해도 이번 세션의 폭은 그대로 씁니다.
    }
  }, [dragging, key, width])

  // 끄는 동안에는 커서가 경계선을 벗어나도 모양이 유지되어야 합니다.
  useEffect(() => {
    if (!dragging) return
    document.body.style.cursor = axis === 'x' ? 'col-resize' : 'row-resize'
    document.body.style.userSelect = 'none'
    return () => {
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
  }, [dragging, axis])

  return { width, size, dragging, onHandleDown, handleProps }
}
