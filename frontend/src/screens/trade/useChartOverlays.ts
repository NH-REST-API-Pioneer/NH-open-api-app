import { useEffect, type RefObject } from 'react'
import type { Chart } from 'klinecharts'
import { lastDrawingStyle, overlayStyles, type Drawing } from './chartDrawings'
import { MARK_GROUP, dropStack, ensureMarkOverlay, holdStack, type MarkData, type TradeMark } from './chartMarks'

/** 그리기 도구와 매매 표시를 차트에 올립니다. */
export function useChartOverlays({
  chartRef,
  boxRef,
  drawingRef,
  drawingsRef,
  tool,
  active,
  mount,
  persist,
  onToolDone,
  tradeMarks,
  onMarkPick,
}: {
  chartRef: RefObject<Chart | null>
  boxRef: RefObject<HTMLDivElement | null>
  drawingRef: RefObject<string | null>
  drawingsRef: RefObject<{ id: string; drawing: Drawing }[]>
  tool: string | null
  active: boolean
  mount: (chart: Chart, drawing: Drawing) => string | null
  persist: () => void
  onToolDone: () => void
  tradeMarks: TradeMark[] | undefined
  onMarkPick: ((mark: TradeMark, at: { left: number; top: number }) => void) | undefined
}) {
  /* 그리기 도구. 주문 대상인 칸에만 걸립니다. 도구가 바뀌거나 풀리면 그리던
     것을 지웁니다. */
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    if (drawingRef.current) {
      chart.removeOverlay({ id: drawingRef.current })
      drawingRef.current = null
    }
    if (!tool || !active) return

    const style = lastDrawingStyle()
    const id = chart.createOverlay({
      name: tool,
      styles: overlayStyles(style),
      /* 다 그리면 도구가 풀립니다. 같은 것을 여럿 그리려면 다시 고릅니다 —
         도구가 걸린 채로 두면 차트를 누를 때마다 선이 생깁니다. */
      onDrawEnd: ({ overlay }) => {
        drawingRef.current = null
        const drawing: Drawing = {
          name: overlay.name,
          points: overlay.points.map((p) => ({ timestamp: p.timestamp ?? 0, value: p.value ?? 0 })),
          style,
        }
        /* 완성된 도형은 고른 상태로 남습니다 — 끝점과 축 라벨이 붙어 있어
           아직 그리는 중처럼 보입니다. 같은 점으로 다시 만들어 고름을 풉니다.
           그리기가 끝나는 이 콜백 안에서 지우면 라이브러리가 아직 그 도형을
           들고 있어, 한 틱 뒤에 합니다. */
        const doneId = overlay.id
        window.setTimeout(() => {
          chart.removeOverlay({ id: doneId })
          const newId = mount(chart, drawing)
          if (newId) drawingsRef.current.push({ id: newId, drawing })
          persist()
        }, 0)
        onToolDone()
      },
    })
    drawingRef.current = typeof id === 'string' ? id : null
    // onToolDone·persist 는 이 효과를 다시 돌릴 이유가 아닙니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tool, active])

  /* 매매 표시를 올립니다.
   *
   * 넘어온 목록이 바뀌면 이 무리만 지우고 다시 답니다. 도형과 무리가 달라
   * 서로를 건드리지 않습니다. */
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    chart.removeOverlay({ groupId: MARK_GROUP })
    if (!tradeMarks || tradeMarks.length === 0) return
    ensureMarkOverlay()
    /* 가까운 표끼리 겹치지 않게 층을 나눕니다. 층 셈은 이 목록 하나에 한 벌입니다. */
    const stack = holdStack(tradeMarks)
    for (const mark of tradeMarks) {
      const data: MarkData = { mark, stack }
      chart.createOverlay({
        name: 'tradeMark',
        groupId: MARK_GROUP,
        points: [{ timestamp: mark.time, value: mark.price }],
        extendData: data,
        onClick: (event) => {
          const rect = boxRef.current?.getBoundingClientRect()
          const left = Math.max(
            0,
            Math.min((event.pageX ?? 0) - (rect?.left ?? 0) - window.scrollX, (rect?.width ?? 300) - 240),
          )
          const top = Math.max(0, (event.pageY ?? 0) - (rect?.top ?? 0) - window.scrollY + 12)
          onMarkPick?.(mark, { left, top })
        },
      })
    }
    return () => dropStack(stack)
    // onMarkPick 은 부르는 쪽의 고정 함수라 다시 올릴 이유가 아닙니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tradeMarks])
}
