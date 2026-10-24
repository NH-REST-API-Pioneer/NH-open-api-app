import { useLayoutEffect, useRef, useState } from 'react'
import { useResizableWidth } from '../../lib/useResizableWidth'
import { MAIN_MIN, SIDE_MIN, SPLIT_GUTTER } from './strategySettingsUtils'

/** 설정 화면의 두 칸 — 본문 폭을 재고, 오른쪽 칸 폭을 끌어 바꾸는 값. */
export function useSettingsLayout() {
  /* 오른쪽 칸 폭. 끌어 둔 적이 없으면 원래 비율(2:1)대로 섭니다. 왼쪽 편집기는
     MAIN_MIN 아래로 줄지 않으므로, 오른쪽이 넓어질 수 있는 끝은 본문 폭에서
     편집기와 손잡이 자리를 뺀 값입니다. */
  const bodyRef = useRef<HTMLDivElement>(null)
  const asideRef = useRef<HTMLElement>(null)
  const [bodyWidth, setBodyWidth] = useState<number | null>(null)
  useLayoutEffect(() => {
    const body = bodyRef.current
    if (!body) return
    const update = () => setBodyWidth(body.clientWidth)
    update()
    const watch = new ResizeObserver(update)
    watch.observe(body)
    return () => watch.disconnect()
  }, [])
  const side = useResizableWidth({
    key: 'nh.setSideWidth',
    initial: null,
    min: SIDE_MIN,
    max: bodyWidth === null ? SIDE_MIN : bodyWidth - MAIN_MIN - SPLIT_GUTTER,
    edge: 'start',
    measure: () => asideRef.current,
  })

  return {
    bodyRef,
    asideRef,
    side,
  }
}
