import { useEffect, useMemo, useRef } from 'react'
import {
  dispose,
  init,
  registerIndicator,
  registerOverlay,
  type Chart,
  type KLineData,
  type OverlayFigure,
} from 'klinecharts'
import { styleFromTokens } from '../trade/chartStyle'
import { CANDLE_PANE } from '../trade/chartLayout'
import { PALETTE } from '../trade/chartIndicators'
import type { PyBar, PyBars, PyMark } from '../../data/pyrun'

/* 팀: 파이썬 전략 실행의 차트 — 판정 봉 캔들, 전략이 계산한 지표선, 진입 ▲▼·청산 ●, 보유 중 손절가.
 *
 * 앱의 일반 차트(`trade/ChartView`)는 시세 저장소·실시간 체결에 묶여 있어 여기 쓰지 않고,
 * **같은 라이브러리와 같은 스타일(`styleFromTokens`)** 로 따로 그립니다. 봉과 지표 값은
 * 모두 서버가 준 기록(신호 줄)이라 화면이 다시 셈하지 않습니다.
 *
 * 지표 칸은 이름으로 자리를 정합니다(명세 4장): `upper` `middle` `lower` `vwap` → 가격 위 선,
 * `rsi` → 아래 창. 모르는 칸은 표에만 섭니다.
 */

/** 가격 위에 그리는 지표 칸과 선 색(앱 지표 팔레트 — 이동평균에 쓰던 주황·보라·초록·청록). */
export const PRICE_LINES: { key: string; label: string; color: string }[] = [
  { key: 'upper', label: '상단', color: PALETTE[4][2] },
  { key: 'middle', label: '중심', color: PALETTE[2][2] },
  { key: 'lower', label: '하단', color: PALETTE[7][1] },
  { key: 'vwap', label: 'VWAP', color: PALETTE[6][2] },
]
export const RSI_COLOR = PALETTE[5][2]
/** 옛 기록(시가·고가·저가 없음)에서 그리는 종가 선. */
const CLOSE_COLOR = PALETTE[0][1]

const LINES = 'PYRUN_LINES'
const MARK = 'pyrunMark'
const STOP = 'pyrunStop'
const RSI_PANE = 'pane_pyrun_rsi'

let registered = false

function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

function numberOr(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

/** 지표선·표시를 라이브러리에 한 번 등록합니다. */
function ensureRegistered(): void {
  if (registered) return
  registered = true
  /* 봉에 실려 온 칸을 그대로 잇는 선. 어느 칸을 그릴지는 `extendData.keys` 가 정합니다. */
  registerIndicator<Record<string, number | undefined>, number, { keys: string[] }>({
    name: LINES,
    shortName: '',
    calcParams: [],
    figures: [],
    calc: (dataList, indicator) => {
      const keys = indicator.extendData?.keys ?? []
      return dataList.map((bar) => Object.fromEntries(keys.map((key) => [key, numberOr(bar[key])])))
    },
  })
  registerOverlay({
    name: MARK,
    totalStep: 1,
    lock: true,
    needDefaultPointFigure: false,
    needDefaultXAxisFigure: false,
    needDefaultYAxisFigure: false,
    createPointFigures: ({ overlay, coordinates }) => {
      const mark = overlay.extendData as PyMark | undefined
      if (!mark || coordinates.length < 1) return []
      const { x, y } = coordinates[0]
      const buy = mark.side === 'buy'
      const color = token(buy ? '--up' : '--down')
      /* 청산 ● — 체결가 자리에 채운 점, 바탕색 테두리로 봉에서 떼어 냅니다. */
      if (mark.kind !== 'entry') {
        return [
          {
            type: 'circle',
            attrs: { x, y, r: 5 },
            styles: { style: 'stroke_fill', color, borderColor: token('--surface'), borderSize: 2 },
          },
        ]
      }
      /* 진입: 매수 ▲ 는 봉 아래, 매도 ▼ 는 봉 위. */
      const figures: OverlayFigure[] = [
        {
          type: 'text',
          attrs: { x, y: buy ? y + 14 : y - 14, text: buy ? '▲' : '▼', align: 'center', baseline: 'middle' },
          styles: {
            color,
            size: 18,
            backgroundColor: 'transparent',
            borderSize: 0,
            paddingLeft: 0,
            paddingRight: 0,
            paddingTop: 0,
            paddingBottom: 0,
          },
        },
      ]
      return figures
    },
  })
  registerOverlay({
    name: STOP,
    totalStep: 1,
    lock: true,
    needDefaultPointFigure: false,
    needDefaultXAxisFigure: false,
    needDefaultYAxisFigure: false,
    createPointFigures: ({ overlay, coordinates, bounding }) => {
      if (coordinates.length < 1) return []
      const { x, y } = coordinates[0]
      const color = token('--warn')
      const label = String((overlay.extendData as { label?: string } | undefined)?.label ?? '')
      return [
        {
          type: 'line',
          attrs: { coordinates: [{ x, y }, { x: bounding.width, y }] },
          styles: { style: 'dashed', color, size: 1, dashedValue: [4, 3] },
        },
        {
          type: 'text',
          attrs: { x: bounding.width - 4, y: y - 4, text: label, align: 'right', baseline: 'bottom' },
          styles: {
            color,
            size: 11,
            backgroundColor: 'transparent',
            borderSize: 0,
            paddingLeft: 0,
            paddingRight: 0,
            paddingTop: 0,
            paddingBottom: 0,
          },
        },
      ]
    },
  })
}

/** `20261030` + `093000` → 한국시간 그 순간(ms). */
export function kstStamp(date: string | null | undefined, time: string | null | undefined): number | null {
  if (!date || !time || date.length < 8 || time.length < 4) return null
  const y = Number(date.slice(0, 4))
  const m = Number(date.slice(4, 6))
  const d = Number(date.slice(6, 8))
  const hh = Number(time.slice(0, 2))
  const mm = Number(time.slice(2, 4))
  const ss = time.length >= 6 ? Number(time.slice(4, 6)) : 0
  const at = Date.UTC(y, m - 1, d, hh - 9, mm, ss)
  return Number.isFinite(at) ? at : null
}

/** 신호 줄 → 라이브러리 봉. 시가·고가·저가가 없는 옛 기록은 종가 하나로 세웁니다(납작한 점). */
function toKLine(bar: PyBar): KLineData | null {
  const at = kstStamp(bar.date, bar.start)
  const close = numberOr(bar.close)
  if (at === null || close === undefined) return null
  return {
    ...bar,
    timestamp: at,
    open: numberOr(bar.open) ?? close,
    high: numberOr(bar.high) ?? close,
    low: numberOr(bar.low) ?? close,
    close,
    volume: 0,
  }
}

/** 표시가 앉을 봉 — 그 시각을 품은 판정 봉(같은 날, 시작이 그 시각 이하인 마지막 봉). */
function seatOf(data: KLineData[], at: number): KLineData | null {
  let found: KLineData | null = null
  for (const bar of data) {
    if (bar.timestamp <= at) found = bar
    else break
  }
  if (found === null) return null
  /* 다른 날 봉에 앉히지 않습니다. */
  return new Date(found.timestamp + 9 * 3600_000).getUTCDate() === new Date(at + 9 * 3600_000).getUTCDate()
    ? found
    : null
}

export interface StopLine {
  /** 진입 시각(HHMMSS)과 날짜 — 선이 여기서 시작합니다. */
  date: string | null
  time: string | null
  price: number
  label: string
}

export function PyRunChart({
  bars,
  decimals,
  barMin,
  barMinFromFile = false,
  stop,
  rsiGuides,
}: {
  bars: PyBars | null
  decimals: number
  barMin: number
  /** 판정 봉 크기를 그 실행이 아니라 지금 전략 파일에서 읽었으면 true — 범례에 단서를 답니다. */
  barMinFromFile?: boolean
  /** 보유 중이면 손절가 선. */
  stop: StopLine | null
  /** RSI 창의 기준선(전략 Params 의 `rsi_buy`·`rsi_sell` 이 있을 때). */
  rsiGuides: number[]
}) {
  const boxRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<Chart | null>(null)

  const data = useMemo(
    () => (bars?.bars ?? []).map(toKLine).filter((one): one is KLineData => one !== null),
    [bars],
  )
  /* 그 실행의 봉에 있는 칸만 그립니다. */
  const priceKeys = useMemo(
    () => PRICE_LINES.filter((line) => data.some((bar) => numberOr(bar[line.key]) !== undefined)),
    [data],
  )
  const hasRsi = useMemo(() => data.some((bar) => numberOr(bar.rsi) !== undefined), [data])
  /* 옛 기록이면 종가 선을 같이 긋습니다 — 납작한 봉만으로는 흐름이 안 읽힙니다. */
  const closeOnly = useMemo(
    () => (bars?.bars ?? []).some((bar) => bar.open === null || bar.high === null || bar.low === null),
    [bars],
  )

  /* 라이브러리가 봉을 물을 때 줄 값. 판을 다시 세우지 않고 `resetData` 로 다시 묻게 합니다. */
  const dataRef = useRef<KLineData[]>(data)
  const rsiKey = rsiGuides.join('/')

  /* 차트 한 번 세우기 — 크기·밝기 변화를 따라갑니다. */
  useEffect(() => {
    const box = boxRef.current
    if (!box) return
    ensureRegistered()
    const chart = init(box, { styles: styleFromTokens(), timezone: 'Asia/Seoul' })
    if (!chart) return
    chartRef.current = chart
    chart.setOffsetRightDistance(24)
    chart.setDataLoader({
      getBars: ({ type, callback }) => callback(type === 'init' ? dataRef.current : [], false),
    })
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(box)
    const theme = new MutationObserver(() => chart.setStyles(styleFromTokens()))
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => {
      observer.disconnect()
      theme.disconnect()
      chartRef.current = null
      dispose(box)
    }
  }, [])

  /* 자릿수·봉 크기 — 바뀌면 라이브러리가 봉을 다시 묻습니다. */
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    chart.setSymbol({ ticker: 'pyrun', pricePrecision: decimals, volumePrecision: 0 })
    chart.setPeriod({ type: 'minute', span: Math.max(1, barMin) })
  }, [decimals, barMin])

  /* 봉과 지표선. 새 판정 봉·체결이 올 때만 바뀝니다(그 사이 폴링으로는 다시 그리지 않습니다). */
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    dataRef.current = data
    /* 봉이 없으면 눈금도 값을 말하지 않습니다(라이브러리 기본 0~10 눈금을 숨김 — 일반 차트와 같은 규칙). */
    chart.setStyles({ yAxis: { tickText: { show: data.length > 0 } } })
    chart.resetData()
    /* 하루치 판정 봉이 한 화면에 들도록 봉 폭을 맞춥니다(넓히거나 밀어 보는 것은 그대로 됩니다). */
    const width = boxRef.current?.clientWidth ?? 0
    if (width > 0 && data.length > 0) chart.setBarSpace(Math.max(3, Math.min(14, (width - 90) / (data.length + 2))))

    chart.removeIndicator({ name: LINES })
    const lines = [
      ...priceKeys.map((line) => ({ key: line.key, title: `${line.label}: `, color: line.color })),
      ...(closeOnly ? [{ key: 'close', title: '종가: ', color: CLOSE_COLOR }] : []),
    ]
    if (lines.length > 0) {
      chart.createIndicator(
        {
          name: LINES,
          paneId: CANDLE_PANE,
          precision: decimals,
          figures: lines.map((line) => ({ key: line.key, title: line.title, type: 'line' })),
          extendData: { keys: lines.map((line) => line.key) },
          styles: {
            lines: lines.map((line) => ({
              color: line.color,
              size: 1.5,
              style: 'solid' as const,
              smooth: false,
              dashedValue: [2, 2],
            })),
          },
        },
        true,
      )
    }
    if (hasRsi) {
      const guides = rsiKey ? rsiKey.split('/').map(Number) : []
      const keys = guides.map((_, at) => `guide${at}`)
      chart.createIndicator(
        {
          name: LINES,
          shortName: 'RSI',
          paneId: RSI_PANE,
          precision: 1,
          figures: [
            { key: 'rsi', title: 'RSI: ', type: 'line' },
            ...keys.map((key) => ({ key, title: '', type: 'line' })),
          ],
          extendData: { keys: ['rsi'] },
          calc: (list: KLineData[]) =>
            list.map((bar) => ({
              rsi: numberOr(bar.rsi),
              ...Object.fromEntries(keys.map((key, at) => [key, guides[at]])),
            })),
          styles: {
            lines: [
              { color: RSI_COLOR, size: 1.5, style: 'solid' as const, smooth: false, dashedValue: [2, 2] },
              ...keys.map(() => ({
                color: token('--text-dim'),
                size: 1,
                style: 'dashed' as const,
                smooth: false,
                dashedValue: [3, 3],
              })),
            ],
          },
        },
        false,
      )
      chart.setPaneOptions({ id: RSI_PANE, height: 90, minHeight: 60 })
    }
  }, [data, decimals, priceKeys, hasRsi, closeOnly, rsiKey])

  /* 진입·청산 표시와 손절가 선. */
  const stopPrice = stop?.price ?? null
  const stopLabel = stop?.label ?? ''
  const stopDate = stop?.date ?? null
  const stopTime = stop?.time ?? null
  const marks = bars?.marks
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    chart.removeOverlay({ name: MARK })
    chart.removeOverlay({ name: STOP })
    for (const mark of marks ?? []) {
      if (mark.kind === 'trade' || mark.price === null) continue
      const at = kstStamp(mark.date, mark.time)
      const seat = at === null ? null : seatOf(data, at)
      if (!seat) continue
      chart.createOverlay({
        name: MARK,
        paneId: CANDLE_PANE,
        points: [{ timestamp: seat.timestamp, value: mark.price }],
        extendData: mark,
      })
    }
    if (stopPrice !== null) {
      const at = kstStamp(stopDate, stopTime)
      const last = data[data.length - 1] ?? null
      const seat = at === null ? last : (seatOf(data, at) ?? last)
      if (seat) {
        chart.createOverlay({
          name: STOP,
          paneId: CANDLE_PANE,
          points: [{ timestamp: seat.timestamp, value: stopPrice }],
          extendData: { label: stopLabel },
        })
      }
    }
  }, [data, marks, stopPrice, stopLabel, stopDate, stopTime])

  return (
    <div className="pyrun-chart">
      <div className="pyrun-legend">
        <span>
          {barMin}분 판정 봉{barMinFromFile && ' (지금 파일 기준)'}
        </span>
        {priceKeys.map((line) => (
          <span key={line.key}>
            <i className="pyrun-swatch" style={{ background: line.color }} />
            {line.label}
          </span>
        ))}
        {closeOnly && (
          <span title="이 기록에는 시가·고가·저가가 없어 종가만 그립니다">
            <i className="pyrun-swatch" style={{ background: CLOSE_COLOR }} />
            종가(옛 기록)
          </span>
        )}
        {hasRsi && (
          <span>
            <i className="pyrun-swatch" style={{ background: RSI_COLOR }} />
            RSI{rsiGuides.length > 0 && ` · 기준 ${rsiGuides.join(' / ')}`}
          </span>
        )}
        <span className="pyrun-legend-marks">
          <span className="up">▲</span> 매수 진입 · <span className="down">▼</span> 매도 진입 · ● 청산
          {stop && ' · 점선 손절가'}
        </span>
      </div>
      <div className="pyrun-chart-frame">
        <div className="pyrun-chart-box" ref={boxRef} />
        {data.length === 0 && <p className="pyrun-chart-empty">아직 판정 봉이 없습니다</p>}
      </div>
    </div>
  )
}
