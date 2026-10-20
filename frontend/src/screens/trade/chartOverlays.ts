import { registerOverlay, type Chart, type PaneOptions } from 'klinecharts'
import type { Quote } from '../../lib/types'
import { resolve } from '../../data/instruments'
import type { Bar } from '../../data/quotes'
import type { IndicatorSettings } from './chartIndicators'
import {
  SESSION_GROUP,
  ensureSessionBreakOverlay,
  ensureSessionLabelOverlay,
  sessionBreaksOf,
  sessionName,
  type SessionLabelData,
} from './chartSessions'
import { sessionWindows } from '../../data/session'
import { paneTop, precisionFor } from './ChartLegend'
import { CANDLE_PANE, X_AXIS_PANE } from './chartLayout'

/* 사각형은 라이브러리에 없어 등록합니다. 두 점을 마주 보는 꼭짓점으로 씁니다. */
let rectRegistered = false
export function ensureRectOverlay(): void {
  if (rectRegistered) return
  rectRegistered = true
  registerOverlay({
    name: 'rect',
    totalStep: 3,
    needDefaultPointFigure: true,
    needDefaultXAxisFigure: true,
    needDefaultYAxisFigure: true,
    createPointFigures: ({ coordinates }) => {
      if (coordinates.length < 2) return []
      const [a, b] = coordinates
      return [
        {
          type: 'rect',
          attrs: {
            x: Math.min(a.x, b.x),
            y: Math.min(a.y, b.y),
            width: Math.abs(b.x - a.x),
            height: Math.abs(b.y - a.y),
          },
          styles: { style: 'stroke_fill' },
        },
      ]
    },
  })
}

/* 세션이 갈린 자리마다 구분선을 세웁니다. 봉을 새로 채울 때와 아래 칸이 생기거나
 * 없어질 때 지우고 다시 세우므로 앞 종목·앞 묶음의 선이 남지 않습니다. **칸마다
 * 하나씩**입니다 — 봉 칸에만 서면 거래량 칸에서는 끊겨 차트의 흠으로 읽힙니다.
 * 갈린 자리가 없으면 아무것도 안 세웁니다 — 한 세션뿐인 날과 해외가 그렇습니다. */
export function markSessionBreaks(chart: Chart, code: string, bars: readonly Bar[]): void {
  chart.removeOverlay({ groupId: SESSION_GROUP })
  const item = resolve(code)
  const windows = item ? sessionWindows(item.market, item.product.exchangeNo, item.product.code) : []
  const breaks = sessionBreaksOf(bars, windows)
  if (breaks.length === 0 || !item) return
  ensureSessionBreakOverlay()
  const panes = (chart.getPaneOptions() as PaneOptions[]).filter((pane) => pane.id !== X_AXIS_PANE)
  for (const pane of panes) {
    for (const { timestamp } of breaks) {
      chart.createOverlay({
        name: 'sessionBreak',
        groupId: SESSION_GROUP,
        paneId: pane.id,
        points: [{ timestamp }],
      })
    }
  }
  /* 이름표는 봉 칸에만, 이름이 있는 시장에서만 답니다. */
  ensureSessionLabelOverlay()
  breaks.forEach((at, index) => {
    const label: SessionLabelData = {
      before: sessionName(item.market, at.before),
      after: sessionName(item.market, at.after),
      /* 첫 경계의 앞 세션은 첫 봉에서 시작합니다. 칸 왼쪽 끝을 자리로 치면 봉이
         없는 빈 자리에 이름표가 섭니다. */
      prev: breaks[index - 1]?.timestamp ?? bars[0]?.timestamp ?? null,
      next: breaks[index + 1]?.timestamp ?? null,
    }
    if (!label.before && !label.after) return
    chart.createOverlay({
      name: 'sessionLabel',
      groupId: SESSION_GROUP,
      paneId: CANDLE_PANE,
      points: [{ timestamp: at.timestamp }],
      extendData: label,
    })
  })
}

/** 칸의 첫 선이 마지막 봉에서 갖는 값. 배지가 서는 자리입니다. */
export function lastLineValue(chart: Chart, paneId: string): number | null {
  const indicator = chart.getIndicators({ paneId })[0]
  if (!indicator || !indicator.visible) return null
  const line = indicator.figures.find((figure) => figure.type === 'line')
  const row = indicator.result[indicator.result.length - 1] as Record<string, unknown> | undefined
  const value = line ? row?.[line.key] : undefined
  return typeof value === 'number' ? value : null
}

/* 아래 칸 배지 높이의 절반(글자 11 의 줄 높이 + 위아래 여백 1). */
const MARK_HALF = 9

export interface ValueMark {
  name: string
  top: number
  color: string
  text: string
}

/* 아래 칸마다 마지막 값 배지. 칸의 오른쪽 축 위에, 선 색으로 섭니다.
 * 선이 여럿이면 첫 선(가장 짧은 기간)의 값입니다 — 다 붙이면 서로 겹칩니다. */
export function collectMarks(
  chart: Chart,
  box: HTMLElement,
  quote: Quote,
  settings: IndicatorSettings,
): ValueMark[] {
  const data = chart.getDataList()
  if (data.length === 0) return []
  const last = data.length - 1
  const marks: ValueMark[] = []

  for (const indicator of chart.getIndicators()) {
    if (indicator.paneId === CANDLE_PANE || !indicator.visible) continue
    const setting = settings[indicator.name]
    const line = indicator.figures.find((figure) => figure.type === 'line')
    const color = setting?.lines[0]?.color
    if (!line || !color) continue
    const value = (indicator.result[last] as Record<string, unknown> | undefined)?.[line.key]
    if (typeof value !== 'number') continue
    const top = paneTop(chart, box, indicator.paneId)
    if (top === null) continue
    const y = (chart.convertToPixel({ value }, { paneId: indicator.paneId }) as { y?: number }).y
    if (typeof y !== 'number' || !Number.isFinite(y)) continue
    /* 배지는 제 칸 안에 둡니다. 값이 칸 끝에 붙으면 배지 반쪽이 이웃 칸으로
       넘어가, 이웃 칸의 값처럼 읽힙니다. */
    const height = chart.getSize(indicator.paneId)?.height ?? 0
    const inside = height > MARK_HALF * 2 ? Math.min(Math.max(y, MARK_HALF), height - MARK_HALF) : y
    marks.push({
      name: indicator.name,
      top: top + inside,
      color,
      text: value.toLocaleString('ko-KR', {
        minimumFractionDigits: precisionFor(indicator.series, indicator.name, quote),
        maximumFractionDigits: precisionFor(indicator.series, indicator.name, quote),
      }),
    })
  }
  return marks
}
