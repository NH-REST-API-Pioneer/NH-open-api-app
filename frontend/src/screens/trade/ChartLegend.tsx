import type { Chart } from 'klinecharts'
import type { Quote } from '../../lib/types'
import type { IndicatorSettings } from './chartIndicators'
import { anyIndicatorDef } from './extraIndicators'

/* 차트 범례.
 *
 * 라이브러리의 말풍선 대신 우리가 그립니다. 라이브러리 것은 봉 위에 상자를
 * 띄워 봉을 가리고, 글자 크기·색이 앱과 다릅니다. 여기서는 칸의 왼쪽 위에
 * 글줄로 붙이고, 십자선을 따라 값만 바뀝니다.
 *
 * 위 칸은 두 줄입니다 — 시가·고가·저가·종가, 그 아래 겹친 지표. 아래 칸은
 * 칸마다 한 줄입니다. 지표 줄에는 숨기기(눈)와 끄기(✕)가 붙어, 설정을 열지
 * 않고도 선 하나를 치울 수 있습니다.
 */

export interface LegendEntry {
  label: string
  value: string
  /** 선의 색. 위 칸은 이름에, 아래 칸은 값에 칠합니다. */
  color?: string
}

export interface LegendRow {
  name: string
  label: string
  /** 칸의 위쪽 좌표(캔버스 기준). 줄을 그 칸에 붙입니다. */
  top: number
  /** 라이브러리에서 지표가 숨김 상태인지. */
  hidden: boolean
  entries: LegendEntry[]
  /** **아직 값이 하나도 안 선 지표인가.** 봉이 모자라 못 셈한 것이라, 값 자리를
   *  「—」로 채우지 않고 그 까닭을 한 줄로 대신 적습니다 — 「—」는 「원래 없는 값」의
   *  말이라 「조금 더 기다리면 선다」를 말할 수 없습니다. */
  warmingUp: boolean
}

export interface OhlcRow {
  top: number
  open: number
  high: number
  low: number
  close: number
  /** 전봉 종가. 등락 색의 기준입니다. */
  prevClose: number
}

const CANDLE_PANE = 'candle_pane'
/* 위 칸 범례는 종목 배지 아래에 섭니다. 배지 한 줄의 높이입니다. */
export const BADGE_HEIGHT = 26

function formatNumber(value: number, decimals: number): string {
  return value.toLocaleString('ko-KR', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

/** 지표 값의 자릿수. 가격을 따르는 지표는 종목 자릿수, 나머지는 둘입니다.
 *  범례와 배지가 같은 규칙을 씁니다 — 같은 값이 두 자릿수로 보이면 다른 값처럼 읽힙니다. */
export function precisionFor(series: string, name: string, quote: Quote): number {
  if (series === 'price') return quote.decimals
  if (name === 'VOL' || name === 'OBV') return 0
  return 2
}

/** 캔버스 안에서 칸이 시작하는 높이. 칸이 없으면 null 입니다. */
export function paneTop(chart: Chart, box: HTMLElement, paneId: string): number | null {
  const dom = chart.getDom(paneId, 'main')
  if (!dom) return null
  return dom.getBoundingClientRect().top - box.getBoundingClientRect().top
}

/** 십자선이 가리키는(없으면 마지막) 봉의 값들을 모읍니다. */
export function collectLegend(
  chart: Chart,
  box: HTMLElement,
  quote: Quote,
  settings: IndicatorSettings,
  cursor: number | null,
): { ohlc: OhlcRow | null; rows: LegendRow[]; bars: number } {
  const data = chart.getDataList()
  if (data.length === 0) return { ohlc: null, rows: [], bars: 0 }
  const index = cursor !== null && cursor >= 0 && cursor < data.length ? cursor : data.length - 1
  const bar = data[index]
  const prev = data[index - 1] ?? bar

  const candleTop = paneTop(chart, box, CANDLE_PANE) ?? 0
  const ohlc: OhlcRow = {
    top: candleTop,
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
    prevClose: prev.close,
  }

  const rows: LegendRow[] = []
  for (const indicator of chart.getIndicators()) {
    const def = anyIndicatorDef(indicator.name)
    const setting = settings[indicator.name]
    if (!def || !setting) continue
    const top = paneTop(chart, box, indicator.paneId)
    if (top === null) continue

    const result = (indicator.result[index] ?? {}) as Record<string, unknown>
    const decimals = precisionFor(indicator.series, indicator.name, quote)
    const entries: LegendEntry[] = []
    let lineIndex = 0
    let extraIndex = 0
    let shown = false

    for (const figure of indicator.figures) {
      const raw = result[figure.key]
      const value = typeof raw === 'number' ? formatNumber(raw, decimals) : '—'
      if (typeof raw === 'number') shown = true
      if (figure.type === 'line') {
        const line = setting.lines[lineIndex]
        const label = def.linePeriods ? String(setting.params[lineIndex]) : def.lines[lineIndex]
        entries.push({ label: label ?? figure.key, value, color: line?.color })
        lineIndex += 1
      } else {
        entries.push({ label: def.extras?.[extraIndex] ?? figure.key, value })
        extraIndex += 1
      }
    }

    rows.push({
      name: indicator.name,
      label: def.label,
      top,
      hidden: !indicator.visible,
      entries,
      /* 하나라도 값이 섰으면 준비가 끝난 것입니다 — 그 지표의 그림 가운데 한둘이
         늦게 서는 경우가 있어, **전부 비었을 때만** 준비 중입니다. */
      warmingUp: !shown,
    })
  }

  return { ohlc, rows, bars: data.length }
}

interface Props {
  /** 차트에 실린 봉 수. 아직 값이 안 선 지표가 「얼마나 모였나」를 적습니다. */
  bars: number
  quote: Quote
  ohlc: OhlcRow | null
  rows: LegendRow[]
  onHide: (name: string, hidden: boolean) => void
  onRemove: (name: string) => void
  /** 봉 칸 위 겹친 지표가 많을 때 한 줄로 접을지. 넘기는 차트(전략 검증)만 접히고,
   *  안 넘기면 늘 펼친 그대로입니다. */
  fold?: LegendFold
}

/** 겹친 지표 범례 접기 — 펼쳤는지와 바꾸는 함수. 기억은 넘기는 쪽이 합니다. */
export interface LegendFold {
  open: boolean
  onToggle: (open: boolean) => void
}

/** 겹친 지표가 이만큼 넘으면 접습니다(시고저종 줄은 세지 않음). */
const FOLD_AT = 4

function tone(value: number, base: number): string {
  return value > base ? 'up' : value < base ? 'down' : ''
}

export function ChartLegend({ bars, quote, ohlc, rows, onHide, onRemove, fold }: Props) {
  const d = quote.decimals
  const topRows = rows.filter((row) => row.top === ohlc?.top)
  const subRows = rows.filter((row) => row.top !== ohlc?.top)
  /* 접을 수 있는지와 지금 접혔는지. 십자선을 올려도 바뀌지 않습니다 — 펴고 접는 것은
     사용자가 줄을 누를 때뿐입니다. */
  const foldable = fold !== undefined && topRows.length >= FOLD_AT
  const folded = foldable && !fold.open

  const indicatorLine = (row: LegendRow, valueColored: boolean) => (
    <div key={row.name} className={`legend-line${row.hidden ? ' is-hidden' : ''}`}>
      <button
        type="button"
        className="legend-tool"
        aria-label={`${row.label} ${row.hidden ? '보이기' : '숨기기'}`}
        aria-pressed={row.hidden}
        onClick={() => onHide(row.name, !row.hidden)}
      >
        {row.hidden ? '◌' : '◉'}
      </button>
      <button
        type="button"
        className="legend-tool"
        aria-label={`${row.label} 끄기`}
        onClick={() => onRemove(row.name)}
      >
        ✕
      </button>
      <span className="legend-name">{row.label}</span>
      {/* **값 자리를 「—」로 채우지 않습니다.** 「—」는 「원래 없는 값」의 말이라,
          봉이 더 모이면 선다는 것을 말할 수 없습니다. 이상이 아니라 아직 못 셈한
          것이므로 중립으로 적습니다 — 검증 화면의 「준비 중」과 같은 말입니다.
          **몇 봉이 필요한지는 안 적습니다**: 지표마다 다르고 우리가 그 수를 갖고
          있지 않아, 지어낸 수를 적으면 「—」보다 나쁩니다. */}
      {row.warmingUp ? (
        <span className="legend-entry legend-warmup">준비 중 — 확보 {bars}</span>
      ) : (
        row.entries.map((entry, i) => (
          <span key={i} className="legend-entry">
            <span className="legend-key" style={valueColored ? undefined : { color: entry.color }}>
              {entry.label}
            </span>
            <span className="legend-value" style={valueColored ? { color: entry.color } : undefined}>
              {entry.value}
            </span>
          </span>
        ))
      )}
    </div>
  )

  return (
    <>
      {ohlc && (
        <div className="legend legend-candle" style={{ top: ohlc.top + BADGE_HEIGHT }}>
          {/* 칸이 좁아지면 이 줄은 두 단계로 물러납니다. 고르는 것은 `trade.css`
              의 칸 폭 조건이고, 여기서는 그 조건이 짚을 이름만 답니다.

              1. 표지가 한 글자가 됩니다 — 「시가」가 「시」로. 값은 그대로입니다
              2. 그래도 모자라면 **시가부터** 접고, 다음이 고가·저가 한 짝입니다.
                 종가는 마지막까지 남습니다

              시가를 먼저 접는 것은 넷 중 유일하게 다른 표시가 대신 말해 주기
              때문입니다 — 봉의 몸통 색이 이미 「종가가 시가보다 위인가」를
              말합니다. 고가·저가는 방향만 다른 한 짝이라 갈라 접지 않습니다:
              한쪽만 남기면 화면이 오르는 쪽이나 내리는 쪽을 편들게 됩니다.

              접힌 개수는 줄 끝에 「+n」으로 섭니다. 없으면 「이 차트는 원래
              그 값을 안 보여준다」로 읽혀, 칸을 넓히면 나온다는 것을 모릅니다. */}
          <div className="legend-line legend-ohlc">
            {(
              [
                ['시가', '시', ohlc.open, 'open'],
                ['고가', '고', ohlc.high, 'high'],
                ['저가', '저', ohlc.low, 'low'],
                ['종가', '종', ohlc.close, 'close'],
              ] as const
            ).map(([label, short, value, key]) => (
              <span key={label} className={`legend-entry legend-ohlc-${key}`}>
                <span className="legend-key">
                  <span className="legend-key-long">{label}</span>
                  <span className="legend-key-short">{short}</span>
                </span>
                <span className={`legend-value ${tone(value, ohlc.prevClose)}`}>
                  {formatNumber(value, d)}
                </span>
              </span>
            ))}
          </div>
          {folded ? (
            /* 접힌 한 줄 — 지표 이름만, 앞에 그 지표 첫 선의 색 점. 값은 펼쳐야 섭니다. */
            <button
              type="button"
              className="legend-line legend-fold"
              aria-expanded={false}
              onClick={() => fold.onToggle(true)}
            >
              {topRows.map((row, index) => (
                <span key={row.name} className="legend-fold-item">
                  {index > 0 && <span className="legend-fold-sep"> · </span>}
                  <span
                    className="legend-fold-dot"
                    style={{ background: row.entries[0]?.color || 'var(--text-dim)' }}
                    aria-hidden="true"
                  />
                  {row.label}
                </span>
              ))}
              <span className="legend-fold-mark" aria-hidden="true">
                {' '}▾
              </span>
            </button>
          ) : (
            <>
              {topRows.map((row) => indicatorLine(row, false))}
              {foldable && (
                <button
                  type="button"
                  className="legend-line legend-fold legend-unfold"
                  aria-expanded={true}
                  onClick={() => fold.onToggle(false)}
                >
                  ▴ 접기
                </button>
              )}
            </>
          )}
        </div>
      )}
      {subRows.map((row) => (
        <div key={row.name} className="legend legend-sub" style={{ top: row.top }}>
          {indicatorLine(row, true)}
        </div>
      ))}
    </>
  )
}
