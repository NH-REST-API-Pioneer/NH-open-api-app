import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import {
  dispose,
  init,
  registerOverlay,
  utils,
  type AxisCreateTicksParams,
  type AxisTick,
  type Chart,
  type Crosshair,
  type PaneOptions,
} from 'klinecharts'
import type { Quote } from '../../lib/types'
import { PENDING_TEXT, needsLeg, resolve } from '../../data/instruments'
import { kstParts } from '../../lib/kst'
import { fractionText, toneOf } from '../../lib/number'
import {
  loadHistory,
  quoteAsked,
  quoteEntry,
  quoteHasValues,
  subscribeQuotes,
  useDailyBars,
  type Bar,
} from '../../data/quotes'
import {
  LINE_SIZES,
  PALETTE,
  lineStyles,
  type IndicatorSetting,
  type IndicatorSettings,
} from './chartIndicators'
import { allIndicatorDefs, extendOfIndicator } from './extraIndicators'
import {
  lastDrawingStyle,
  loadDrawings,
  overlayStyles,
  rememberDrawingStyle,
  saveDrawings,
  type Drawing,
  type DrawingStyle,
} from './chartDrawings'
import {
  DRAW_GROUP,
  MARK_GROUP,
  dropStack,
  ensureMarkOverlay,
  holdStack,
  type MarkData,
  type TradeMark,
} from './chartMarks'
import {
  SESSION_GROUP,
  ensureSessionBreakOverlay,
  ensureSessionLabelOverlay,
  sessionBreaksOf,
  sessionName,
  type SessionLabelData,
} from './chartSessions'
import { sessionWindows, useTimetable } from '../../data/session'
import { InstrumentPicker, type InstrumentRef } from '../../lib/InstrumentPicker'
import { SPAN_LABEL, type Span } from './chartSlots'
import {
  ChartLegend,
  collectLegend,
  type LegendFold,
  paneTop,
  precisionFor,
  type LegendRow,
  type OhlcRow,
} from './ChartLegend'

/* 차트 한 칸.
 *
 * 봉 그리기·십자선·지표는 라이브러리가 하고, **봉은 시세 저장소가 줍니다** —
 * 조회 봉 한 벌에 실시간 체결로 접은 봉이 뒤따르고(`data/quotes.ts`
 * `foldTrades`), 이 칸은 그것을 싣고 마지막 봉을 갈아 끼울 뿐입니다. 같은
 * 종목을 두 칸이 보면 두 칸이 같은 봉을 봅니다.
 *
 * 지표 설정은 밖(ChartPanel)에서 받습니다. 두 칸이 같은 설정을 씁니다 —
 * 칸마다 다르면 같은 이름의 선이 두 칸에서 다른 색으로 그려집니다.
 *
 * 범례와 마지막 값 배지는 이 앱이 그립니다. 라이브러리의 말풍선은 봉 위에
 * 상자를 띄워 봉을 가리고, 마지막 값 표시는 켜면 모든 지표에 붙어 가격축이
 * 이동평균 값으로 덮입니다.
 *
 * 그린 도형은 종목에 붙어 저장됩니다. 도형을 누르면 색·굵기·삭제가 뜹니다.
 *
 * 두 칸이 같은 종목이면 스크롤과 확대가 같이 움직입니다. 다른 종목이면
 * 따로 움직입니다 — 시간축이 달라 같은 거리를 밀어도 같은 자리가 아닙니다.
 */

/* 봉이 서는 칸과 시간 축 칸의 이름. 겹치는 지표는 봉 칸의 이름을 대고 만들어야
 * 봉 위에 얹힙니다 — 이름을 대지 않으면 제 칸을 새로 받습니다. */
const CANDLE_PANE = 'candle_pane'
const X_AXIS_PANE = 'x_axis_pane'

/* 봉 칸 위·아래 여백. 라이브러리는 1 보다 작으면 칸 높이에 대한 몫으로, 1
 * 이상이면 px 로 읽습니다. 위쪽은 범례 높이에 맞춰 재고(`headroomGap`), 못 잴
 * 때는 라이브러리 기본값입니다. */
const DEFAULT_TOP_GAP = 0.2
const BOTTOM_GAP = 0.1
/* 범례 아래 끝과 최고가 글자 윗끝 사이. */
const HEADROOM_MARGIN = 4
/* 최고가 글자는 봉의 고가에서 이만큼 위를 가운데로 섭니다(라이브러리의
 * 최고·최저가 표 그림 — 꺾인 선 2px + 5px). */
const HIGH_MARK_LIFT = 7

/** 최고가 표가 범례(`headBottom`, 봉 칸 위에서 잰 아래 끝) 밑 4px 에 서게 하는
 *  위쪽 여백(px). 못 맞추면 `null`.
 *
 *  고가가 설 높이를 Y 라 하면 글자 윗끝은 Y − 7 − 글자/2 이므로
 *  Y = 범례 아래 끝 + 4 + 7 + 글자/2 입니다. 라이브러리는 값 범위(최고값 M,
 *  폭 R)를 위로 t = G/h, 아래로 b = 0.1 만큼 늘려 칸 높이 h 에 폅니다. 고가 H 가
 *  M 보다 d·R 아래이면(볼린저 윗선처럼 봉보다 높은 지표가 있으면 d > 0) H 는
 *  h·(t + d)/(1 + t + b) 에 섭니다. 지금 여백 `currentTop`(t) 에서 잰 고가 높이
 *  `highY` 로 d 를 구하고, Y 에 서게 하는 t 로 풉니다 —
 *  t = (Y·(1 + b) − h·d) / (h − Y). 여백을 바꿔도 d 는 그대로라 한 번에 맞습니다.
 *  지표가 이미 고가를 Y 아래로 밀어 두었으면(t < 0) 여백을 더 줄 까닭이 없어
 *  가장 작은 여백입니다. */
function headroomGap(
  headBottom: number,
  textSize: number,
  paneHeight: number,
  highY: number,
  currentTop: number,
): number | null {
  const h = paneHeight
  const y = headBottom + HEADROOM_MARGIN + HIGH_MARK_LIFT + textSize / 2
  /* 칸이 범례보다 조금 큰 정도면 봉이 설 자리가 거의 안 남습니다. 그때는
     겹침을 받아들이고 기본 여백으로 둡니다. */
  if (!(y > 0) || !(h > 0) || !Number.isFinite(highY) || y / h >= 0.6) return null
  const t = currentTop >= 1 ? currentTop / h : currentTop
  const d = (highY * (1 + t + BOTTOM_GAP)) / h - t
  const next = (y * (1 + BOTTOM_GAP) - h * d) / (h - y)
  return Math.max(1, next * h)
}

/* 시간 축이 늘 가져가는 높이. 아래 칸에 얼마를 줄지 셀 때 먼저 빼 둡니다. */
const X_AXIS_HEIGHT = 26
/* 아래 칸 하나가 넘지 않는 높이. 넓은 창에서 아래 칸만 계속 커지면 봉이
 * 눌립니다 — 거래량은 모양만 보면 되고 값은 범례에 적힙니다.
 * 확대에서는 세로가 넉넉하므로 칸도 그만큼 키웁니다. */
const SUB_PANE_MAX = 96
const SUB_PANE_MAX_EXPANDED = 180
/* 라이브러리가 칸에 두는 기본 바닥. 칸 높이를 이보다 낮게 주려면 바닥도 같이
 * 내려야 합니다. 안 그러면 칸 셋이 자리를 넘겨 봉 칸이 0 이 됩니다. */
const PANE_FLOOR = 30
/* 아래 칸 전부가 가져갈 수 있는 몫. 나머지는 봉이 갖습니다 — 봉이 이 화면의
 * 주인이라 어떤 크기에서도 절반은 넘게 둡니다. */
const SUB_PANE_SHARE = 0.45
/* 봉 칸이 이보다 낮아지지 않습니다. 낮은 창에서 아래 칸이 먼저 바닥까지 줄고,
 * 그래도 모자라면 카드가 세로로 스크롤합니다 — 봉이 0 높이가 되어 거래량만
 * 남는 차트는 차트가 아닙니다. */
const CANDLE_MIN = 160

/** 아래 칸의 수와 높이 바닥을 정해 둔 차트의 규칙. 자리는 `order` 차례로 먼저
 *  나누고, 남는 자리에 나머지 켜진 지표를 정의 차례로 둡니다. */
export interface BottomCap {
  max: number
  floor: number
  order: string[]
}

/** 정해 둔 아래 칸 규칙대로 켜진 지표를 고릅니다. 칸 높이가 `floor` 를 못 넘으면 칸
 *  수를 하나씩 줄이고(하나까지), 자리를 못 받은 지표는 이 차트에서만 끕니다 —
 *  설정은 그대로라 자리가 나면 다시 섭니다. 높이를 아직 모르면 수만 맞춥니다. */
function capBottom(
  settings: IndicatorSettings,
  cap: BottomCap,
  height: number,
): { settings: IndicatorSettings; overflow: string[] } {
  const bottoms = allIndicatorDefs()
    .filter((def) => def.group === 'bottom' && settings[def.name]?.on)
    .map((def) => def.name)
  const ranked = [...cap.order.filter((name) => bottoms.includes(name)), ...bottoms.filter((name) => !cap.order.includes(name))]
  /* `fitPanes` 와 같은 셈으로 칸 하나의 높이를 냅니다. */
  const fits = (count: number) => {
    const room = height - X_AXIS_HEIGHT - count
    const budget = Math.min(Math.floor(room * SUB_PANE_SHARE), room - CANDLE_MIN)
    return Math.floor(budget / count) >= cap.floor
  }
  let count = Math.min(cap.max, ranked.length)
  while (height > 0 && count > 1 && !fits(count)) count -= 1
  const overflow = ranked.slice(count)
  if (overflow.length === 0) return { settings, overflow }
  const made = { ...settings }
  for (const name of overflow) made[name] = { ...settings[name], on: false }
  return { settings: made, overflow }
}

/* 현재가 표와 눈금 글자가 서로 닿기 시작하는 거리.
 * 표는 높이 20(글자 12 + 위아래 여백 4), 눈금 글자는 12 이고 둘 다 제 값의
 * 자리를 가운데로 삼으므로, 10 + 6 보다 가까우면 겹칩니다. */
const LAST_MARK_HEIGHT = 16

/* 사각형은 라이브러리에 없어 등록합니다. 두 점을 마주 보는 꼭짓점으로 씁니다. */
let rectRegistered = false
function ensureRectOverlay(): void {
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
function markSessionBreaks(chart: Chart, code: string, bars: readonly Bar[]): void {
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

/* 현재가 표에 가리는 눈금 하나를 빼고 돌려줍니다.
 *
 * 라이브러리는 현재가 표를 눈금 위에 덮어 그립니다. 값이 눈금 자리에 가까우면
 * 눈금 글자가 반쯤 잘린 채로 남아, 읽을 수 없는 숫자가 축에 하나 생깁니다.
 * 표가 이미 그 자리의 값을 말하고 있으므로 눈금 쪽을 뺍니다. */
function ticksClearOfLastMark(lastPrice: () => number | null) {
  return ({ defaultTicks }: { defaultTicks: AxisTick[] }): AxisTick[] => {
    const price = lastPrice()
    if (price === null || defaultTicks.length < 2) return defaultTicks

    /* 눈금은 값과 자리가 비례하므로 양 끝 둘이면 현재가의 자리가 나옵니다. */
    const first = defaultTicks[0]
    const last = defaultTicks[defaultTicks.length - 1]
    const from = Number(first.value)
    const to = Number(last.value)
    if (!Number.isFinite(from) || !Number.isFinite(to) || from === to) return defaultTicks

    const at = first.coord + ((price - from) / (to - from)) * (last.coord - first.coord)
    return defaultTicks.filter((tick) => Math.abs(tick.coord - at) >= LAST_MARK_HEIGHT)
  }
}

/* 축 눈금 글자 크기(라이브러리 기본). 글자 폭을 잴 때 씁니다. */
const AXIS_TEXT_SIZE = 12

/* 0~100 사이를 오가는 지표. 축 눈금이 20·40 처럼 서므로 소수를 안 적습니다. */
const OSCILLATORS = new Set(['RSI', 'KDJ', 'WR', 'DMI'])

/* 아래 칸 축 글자의 자릿수. `null` 이면 라이브러리 글자 그대로입니다 — 거래량은
 * 라이브러리가 큰 수를 줄여 적는 것이 읽기 좋습니다. MACD 는 가격의 차이라 종목
 * 자릿수를 따르고, 나머지는 둘입니다. 범례 값의 자릿수(`precisionFor`)와는 따로
 * 둡니다 — 눈금은 대충의 높이를 말하고, 정확한 값은 범례가 말합니다. */
function axisDecimals(name: string, decimals: number): number | null {
  if (name === 'VOL' || name === 'OBV') return null
  if (OSCILLATORS.has(name)) return 0
  if (name === 'MACD') return decimals
  return 2
}

function withDecimals(ticks: AxisTick[], decimals: number | null): AxisTick[] {
  if (decimals === null) return ticks
  return ticks.map((tick) => {
    const value = Number(tick.value)
    if (!Number.isFinite(value)) return tick
    /* 반올림해서 0 이 되는 음수가 「-0」으로 서지 않게 합니다. */
    const rounded = Number(value.toFixed(decimals)) || 0
    return {
      ...tick,
      text: rounded.toLocaleString('ko-KR', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      }),
    }
  })
}

/* 분봉 축은 시각만 적습니다(「23:54」). 그래서 **날이 넘어가는 자리**에서 시각이
 * 뒤로 뛰는 것처럼 보입니다 — 해외 분봉은 밤을 건너 이어지므로 앞으로 받을수록
 * 그 자리가 자주 생깁니다.
 *
 * 그 자리의 **첫 눈금에만** 날짜를 붙입니다. 모든 눈금에 붙이면 축이 날짜로 덮여
 * 시각을 읽기 어렵고, 아무 데도 안 붙이면 지금처럼 뛰어 보입니다. 날짜 꼴은
 * 일봉 축과 같은 것을 씁니다. */
function dayText(at: number): string {
  const { month, day } = kstParts(at)
  return `${month}/${day}`
}

/* 일봉 축은 날짜만 적습니다(「9/30」). 해는 **첫 눈금과 해가 바뀐 뒤 첫 눈금에만**
 * 붙입니다(「2026 1/2」) — 모든 눈금에 붙이면 축이 같은 해로 덮이고, 아무 데도 안
 * 붙이면 1월이 어느 해의 1월인지 모릅니다. 분봉의 날짜 표시는 여기 없습니다 —
 * 일봉 눈금은 이미 날짜라 한 번 더 붙이면 같은 날이 두 번 적힙니다. */
/* 글자는 눈금 자리를 가운데로 섭니다. 칸 양 끝에 붙은 눈금은 글자 한쪽이 잘려
 * 「'30」·「18:3」처럼 다른 값으로 읽히므로, 온전히 안 들어가면 글자를 비웁니다
 * (격자선은 남습니다). */
function fitsAxis(tick: AxisTick, text: string, width: number): boolean {
  const room = Math.min(tick.coord, width - tick.coord) * 2
  return room >= utils.calcTextWidth(text, AXIS_TEXT_SIZE)
}

/* 날짜와 해는 한국 달력으로 짓습니다. 봉의 날은 국내 장의 날이라, 이 PC 의
 * 시간대로 읽으면 하루씩 밀린 날짜가 적힐 수 있습니다. */
function ticksWithYear({ defaultTicks, bounding }: AxisCreateTicksParams): AxisTick[] {
  let year: number | null = null
  return defaultTicks.map((tick) => {
    const at = Number(tick.value)
    if (!Number.isFinite(at)) return tick
    const tickYear = kstParts(at).year
    const text = dayText(at)
    if (!fitsAxis(tick, text, bounding.width)) return { ...tick, text: '' }
    if (tickYear === year) return { ...tick, text }
    const withYear = `${tickYear} ${text}`
    /* 해를 붙이면 안 들어가는 자리면 날짜만 적고 해는 다음 눈금으로 넘깁니다. */
    if (!fitsAxis(tick, withYear, bounding.width)) return { ...tick, text }
    year = tickYear
    return { ...tick, text: withYear }
  })
}

function ticksWithDayMark({ defaultTicks, bounding }: AxisCreateTicksParams): AxisTick[] {
  /* **맨 왼쪽 눈금에는 안 붙입니다.** 거기서 날이 바뀐 것이 아니라 그림이
     시작한 것이고, 축 끝에 붙은 글자는 칸 밖으로 잘립니다. */
  const head = Number(defaultTicks[0]?.value)
  let last = Number.isFinite(head) ? dayText(head) : ''
  return defaultTicks.map((tick) => {
    const at = Number(tick.value)
    if (!Number.isFinite(at)) return tick
    const clock = fitsAxis(tick, tick.text, bounding.width) ? tick.text : ''
    const day = dayText(at)
    if (day === last) return { ...tick, text: clock }
    last = day
    /* 눈금 하나에 날짜와 시각을 **한 줄로** 답니다. 칸 끝이라 날짜까지는 안
       들어가면 시각만, 시각도 안 들어가면 비웁니다. */
    const withDay = `${day} ${tick.text}`
    return { ...tick, text: fitsAxis(tick, withDay, bounding.width) ? withDay : clock }
  })
}

/* 아래 칸(거래량·MACD 등)의 높이를 지금 창에 맞춥니다.
 *
 * 라이브러리는 아래 칸에 100px 씩 고정으로 주고 남는 것을 봉에 줍니다. 그래서
 * 차트 자리가 좁은 창에서는 아래 칸이 자리를 다 먹고 봉 칸이 0 이 됩니다 —
 * 지표를 켰는데 봉이 사라지는 것으로 보입니다. */
function fitPanes(chart: Chart, box: HTMLElement, expanded: boolean): void {
  const panes = chart.getPaneOptions() as PaneOptions[]
  const subs = panes.filter((pane) => pane.id !== CANDLE_PANE && pane.id !== X_AXIS_PANE)
  if (subs.length === 0) return

  const room = box.clientHeight - X_AXIS_HEIGHT - subs.length
  /* 아래 칸 몫은 비율로 정하되, 봉 칸의 바닥을 먹지는 못합니다. */
  const budget = Math.min(Math.floor(room * SUB_PANE_SHARE), room - CANDLE_MIN)
  const cap = expanded ? SUB_PANE_MAX_EXPANDED : SUB_PANE_MAX
  const each = Math.max(PANE_FLOOR, Math.min(cap, Math.floor(budget / subs.length)))

  for (const pane of subs) {
    chart.setPaneOptions({ id: pane.id, height: each, minHeight: Math.min(each, PANE_FLOOR) })
  }
}

/** CSS 토큰을 라이브러리 스타일로 옮깁니다. 색을 두 곳에 적어 두지 않습니다. */
function styleFromTokens(): Record<string, unknown> {
  const css = getComputedStyle(document.documentElement)
  const token = (name: string) => css.getPropertyValue(name).trim()
  const up = token('--up')
  const down = token('--down')
  const upBar = token('--up-bar')
  const downBar = token('--down-bar')
  const label = token('--text-label')
  const dim = token('--text-dim')
  const grid = token('--divider')

  return {
    grid: {
      horizontal: { color: grid },
      vertical: { color: grid },
    },

    /* 국내 관례를 따릅니다 — 오르면 빨강, 내리면 파랑. 라이브러리 기본은
       그 반대(초록·빨강)라 반드시 덮어써야 합니다. 앱의 다른 방향값과 같은
       색이어야 화면을 옮겨도 같은 뜻입니다. */
    candle: {
      bar: {
        upColor: up,
        downColor: down,
        noChangeColor: dim,
        upBorderColor: up,
        downBorderColor: down,
        noChangeBorderColor: dim,
        upWickColor: up,
        downWickColor: down,
        noChangeWickColor: dim,
      },
      priceMark: {
        high: { color: label },
        low: { color: label },
        last: { upColor: up, downColor: down, noChangeColor: dim },
      },
      /* 값은 이 앱의 범례가 말합니다. 라이브러리 말풍선은 봉 위에 상자를 띄워
         봉을 가립니다. */
      tooltip: { showRule: 'none' },
    },

    /* 거래량 막대는 호가 잔량 막대와 같은 옅은 색을 씁니다. 봉과 같은 진한
       색으로 칠하면 아래 칸이 위 칸만큼 눈에 들어와 주가를 가립니다.
       선 색은 지표마다 사용자 설정이 덮어씁니다. */
    indicator: {
      ohlc: { upColor: upBar, downColor: downBar, noChangeColor: dim },
      bars: [{ upColor: upBar, downColor: downBar, noChangeColor: dim }],
      circles: [{ upColor: upBar, downColor: downBar, noChangeColor: dim }],
      tooltip: { showRule: 'none' },
      /* 마지막 값 표시는 켜면 모든 지표에 붙어 가격축이 이동평균 값으로
         덮입니다. 아래 칸의 배지는 이 앱이 따로 그립니다. */
      lastValueMark: { show: false },
    },

    xAxis: { axisLine: { color: grid }, tickLine: { color: grid }, tickText: { color: label } },
    yAxis: { axisLine: { color: grid }, tickLine: { color: grid }, tickText: { color: label } },

    crosshair: {
      horizontal: { line: { color: dim }, text: { backgroundColor: label } },
      vertical: { line: { color: dim }, text: { backgroundColor: label } },
    },

    /* 그린 도형의 기본색. 도형마다 사용자 색이 덮어씁니다. */
    overlay: overlayStyles(lastDrawingStyle()),

    separator: { color: grid },
  }
}

/** 칸의 첫 선이 마지막 봉에서 갖는 값. 배지가 서는 자리입니다. */
function lastLineValue(chart: Chart, paneId: string): number | null {
  const indicator = chart.getIndicators({ paneId })[0]
  if (!indicator || !indicator.visible) return null
  const line = indicator.figures.find((figure) => figure.type === 'line')
  const row = indicator.result[indicator.result.length - 1] as Record<string, unknown> | undefined
  const value = line ? row?.[line.key] : undefined
  return typeof value === 'number' ? value : null
}

/* 아래 칸 배지 높이의 절반(글자 11 의 줄 높이 + 위아래 여백 1). */
const MARK_HALF = 9

interface ValueMark {
  name: string
  top: number
  color: string
  text: string
}

/* 아래 칸마다 마지막 값 배지. 칸의 오른쪽 축 위에, 선 색으로 섭니다.
 * 선이 여럿이면 첫 선(가장 짧은 기간)의 값입니다 — 다 붙이면 서로 겹칩니다. */
function collectMarks(
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

/* ── 두 칸의 스크롤·확대 맞추기 ─────────────────────────── */

interface SyncEntry {
  id: number
  code: string
  chart: Chart
}

/** 같은 종목인 칸끼리 스크롤·확대를 전달합니다. 한 칸이 밀면 나머지가 따라갑니다. */
export class SyncHub {
  private entries: SyncEntry[] = []
  /* 따라가는 중에 나는 액션은 다시 퍼뜨리지 않습니다. 퍼뜨리면 둘이 서로를
     밀며 끝없이 돕니다. */
  private busy = false

  register(id: number, code: string, chart: Chart): void {
    this.entries = this.entries.filter((entry) => entry.id !== id)
    this.entries.push({ id, code, chart })
  }

  unregister(id: number): void {
    this.entries = this.entries.filter((entry) => entry.id !== id)
  }

  /* 한 칸을 다른 칸의 자리에 맞춥니다. 거리(상대값)가 아니라 자리(절대값)로
     맞춥니다 — 거리로 옮기면 처음 어긋난 만큼이 끝까지 남고, 마지막 봉 너머로
     민 자리는 거리로는 전해지지 않습니다.
     보이는 구간의 `realTo` 는 마지막 봉 너머까지 센 오른쪽 끝의 봉 번호라,
     그 번호를 오른쪽 끝에 두면 같은 자리가 됩니다. */
  private static align(source: Chart, target: Chart): void {
    const bar = source.getBarSpace().bar
    const sameBar = target.getBarSpace().bar === bar
    /* 이미 같은 자리면 손대지 않습니다. 봉 번호는 반올림이라 두 칸이 한 봉만큼
       다르게 셀 수 있는데, 그것을 「다르다」로 보고 서로 맞추면 끝이 없습니다. */
    if (sameBar && Math.abs(source.getVisibleRange().realTo - target.getVisibleRange().realTo) <= 1) return
    if (!sameBar) target.setBarSpace(bar)
    target.scrollToDataIndex(source.getVisibleRange().realTo - 1, 0)
  }

  /* 맞추는 동안 상대 칸이 내는 스크롤·확대 액션은 이 코드가 만든 것이라 되받지
     않습니다. 액션이 한 틱 뒤에 올 수도 있어 다음 틱까지 잠급니다. */
  private lock(work: () => void): void {
    if (this.busy) return
    this.busy = true
    try {
      work()
    } finally {
      window.setTimeout(() => {
        this.busy = false
      }, 0)
    }
  }

  /** 다른 같은 종목 칸의 자리를 이 칸에 맞춥니다. 칸이 새로 열리거나 종목이 바뀔 때 씁니다. */
  adopt(id: number): void {
    const target = this.entries.find((entry) => entry.id === id)
    const source = this.entries.find((entry) => entry.id !== id && entry.code === target?.code)
    if (!target || !source) return
    this.lock(() => SyncHub.align(source.chart, target.chart))
  }

  /** 한 칸이 움직였습니다. 같은 종목인 나머지 칸을 그 자리에 맞춥니다. */
  follow(from: number): void {
    const source = this.entries.find((entry) => entry.id === from)
    if (!source) return
    this.lock(() => {
      for (const entry of this.entries) {
        if (entry.id !== from && entry.code === source.code) SyncHub.align(source.chart, entry.chart)
      }
    })
  }
}

/* ── 도형 색·굵기 팝오버 ──────────────────────────────── */

function DrawingStylePopover({
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

/* ── 차트 한 칸 ──────────────────────────────────────── */

interface Props {
  /** 칸 번호. 동기화와 키에 씁니다. */
  slot: number
  quote: Quote
  span: Span
  settings: IndicatorSettings
  onSettingChange: (name: string, next: IndicatorSetting) => void
  expanded: boolean
  /** 두 칸 모드인지. 한 칸이면 주문 대상 표시를 안 합니다 — 고를 것이 없습니다. */
  split: boolean
  /** 이 칸이 주문 대상인지. */
  active: boolean
  onActivate: () => void
  /** 이 칸의 종목을 바꿉니다. **없으면 종목 배지가 누를 수 없는 글자**로 섭니다. */
  onPickInstrument?: (item: InstrumentRef) => void
  /** 고른 그리기 도구. 주문 대상인 칸에만 걸립니다. */
  tool: string | null
  onToolDone: () => void
  /** 올라갈 때마다 이 칸의 도형을 모두 지웁니다. */
  clearSignal: number
  /** 어느 칸에서든 도형이 바뀌면 올라갑니다. 같은 종목을 띄운 다른 칸이 다시 읽습니다. */
  drawVersion: number
  onDrawingsChange: () => void
  /** 차트 위에 얹는 매매 표시. 전략 화면이 묶어서 넘깁니다 — 같은 봉의 여러
   *  체결을 묶는 것도, 어느 실행의 것만 보일지도 여기 오기 전에 정해집니다. */
  tradeMarks?: TradeMark[]
  /** 표를 눌렀을 때. 상세를 띄우는 것은 부르는 쪽이 합니다. */
  onMarkPick?: (mark: TradeMark, at: { left: number; top: number }) => void
  sync: SyncHub
  /** 아래 칸의 수·높이 바닥 규칙. 전략 검증 차트가 넘깁니다 — 없으면 켜진 지표가
   *  모두 섭니다(일반주문 차트). */
  bottomCap?: BottomCap
  /** 규칙 때문에 자리를 못 받은 지표가 바뀔 때. */
  onBottomOverflow?: (names: string[]) => void
  /** 겹친 지표 범례 접기. 전략 검증 차트가 넘깁니다 — 없으면 늘 펼침입니다. */
  legendFold?: LegendFold
}

export function ChartView({
  slot,
  quote,
  span,
  settings: givenSettings,
  onSettingChange,
  expanded,
  split,
  active,
  onActivate,
  onPickInstrument,
  tool,
  onToolDone,
  clearSignal,
  drawVersion,
  onDrawingsChange,
  tradeMarks,
  onMarkPick,
  sync,
  bottomCap,
  legendFold,
  onBottomOverflow,
}: Props) {
  const boxRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<Chart | null>(null)
  /* 아래 칸 규칙이 있는 차트만 상자 높이를 따로 잽니다 — 규칙이 칸 수를 높이로 정합니다. */
  const [boxHeight, setBoxHeight] = useState(0)
  useEffect(() => {
    const box = boxRef.current
    if (!bottomCap || !box) return
    setBoxHeight(box.clientHeight)
    const observer = new ResizeObserver(() => setBoxHeight(box.clientHeight))
    observer.observe(box)
    return () => observer.disconnect()
  }, [bottomCap])
  /* 이 차트에 실제로 세우는 구성. 규칙이 없으면 받은 그대로입니다. */
  const capped = useMemo(
    () => (bottomCap ? capBottom(givenSettings, bottomCap, boxHeight) : { settings: givenSettings, overflow: [] }),
    [givenSettings, bottomCap, boxHeight],
  )
  const settings = capped.settings
  const overflowKey = capped.overflow.join(',')
  useEffect(() => {
    onBottomOverflow?.(overflowKey === '' ? [] : overflowKey.split(','))
    // 넘친 목록이 바뀔 때만 알립니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overflowKey])
  /* 이 종목의 받아 온 분봉. 받는 일은 화면 쪽이 하고 여기서는 읽기만 합니다 —
     같은 종목을 두 칸이 띄워도 요청은 한 번입니다. **조회 때만 바뀌는 참조**라
     체결마다 차트가 다시 서지 않습니다 — 체결로 접은 봉은 아래 구독으로 흐릅니다. */
  const served = useSyncExternalStore(
    subscribeQuotes,
    () => quoteEntry(quote.code).bars,
    () => null,
  )
  /* 일봉은 일봉 탭에서만 받습니다 — 분봉을 보는 자리에서 일봉까지 받으면 종목마다
     조회 하나가 더 나갑니다. 세션과 무관한 주간 일봉이고 체결로 접지 않습니다. */
  const daily = useDailyBars(span === 'day' && !quote.withheld ? quote.code : '')
  /* 물어봤는데 값을 못 세우면 **봉을 안 그립니다.** 임시 봉을 그리면 헤더는
     「받지 못했습니다」인데 차트는 값을 말해, 한 화면이 두 말을 합니다. */
  /* 모의투자라 현재가만 못 받은 것은 봉과 무관합니다 — 받은 봉은 그립니다. */
  const missingAsked = useSyncExternalStore(
    subscribeQuotes,
    () => {
      if (!quoteAsked(quote.code) || quoteHasValues(quote.code)) return false
      const entry = quoteEntry(quote.code)
      return !(entry.failure === 'paper' && entry.bars !== null)
    },
    () => false,
  )
  /* 인증 정보가 없어 안 물은 종목도 봉을 안 그립니다 — 까닭은 헤더가 한 번 말합니다. */
  const missing = quote.withheld === true || missingAsked
  /* 일봉 탭에서 봉을 못 세우는 까닭. 조회가 따로라 사정도 따로입니다 — 못 받았거나,
     받았는데 봉이 없거나(저장해 둔 응답으로 도는 재생에서는 일봉이 0개입니다). */
  const dailyMissing = span === 'day' && (daily.status !== 'ready' || (daily.bars?.length ?? 0) === 0)
  /* **값을 담는 카드라 목적어를 안 붙입니다** — 이 카드가 무엇을 담는 자리인지는
     카드 머리가 이미 말합니다. 불러오는 중에는 아직 할 말이 없어 비워 둡니다. */
  const missingWord = (() => {
    if (quote.withheld) return '조회 전'
    if (span === 'day' && !missing) {
      if (daily.status === 'failed') return '받지 못했습니다'
      return daily.status === 'ready' ? '아직 일봉이 없습니다' : ''
    }
    const entry = quoteEntry(quote.code)
    if (entry.failure) return '받지 못했습니다'
    return entry.status === 'loading' ? '' : '아직 시세가 없습니다'
  })()
  /* 앞으로 이어 받은 날 가운데 **덜 받았을 수 있는 날**이 있었나. 경고가 아니라
     적어 두는 말입니다 — 거래가 드문 먼 월물은 거의 늘 참이라 경고 얼굴로 세우면
     그 종목에서는 늘 서 있게 되고, 그러면 아무도 안 읽습니다. */
  const shortDays = useSyncExternalStore(
    subscribeQuotes,
    () => quoteEntry(quote.code).history.short,
    () => false,
  )

  /* 차트에 실린 마지막 봉. 실시간이 갈아 끼울 때마다 여기도 바뀌고, 현재가 표에
     가리는 눈금을 빼는 데 씁니다. */
  const liveRef = useRef<Bar | null>(null)
  /* 종목 자릿수. 아래 칸 축 글자가 그릴 때마다 읽습니다(MACD). */
  const decimalsRef = useRef(quote.decimals)
  decimalsRef.current = quote.decimals
  /* 지금 차트에 실린 봉 한 벌. 아래 칸이 생기거나 없어질 때 세션 구분선을 그 칸에도
     다시 세우려면 봉이 필요합니다. */
  const shownRef = useRef<readonly Bar[]>([])
  /* 앞 분봉을 못 받아 **이 차트에서는** 더 안 묻기로 한 상태. 저장소가 아니라
     여기 두는 까닭은, 저장소의 「더 없음」은 **사실**이고 이것은 못 받은 것이기
     때문입니다 — 사실 자리에 담으면 종목을 다시 열어도 영영 안 묻습니다.
     로더는 다시 그리지 않으므로 ref 로 읽고, 아래 한 줄을 세우려면 다시 그려야
     해서 상태로도 둡니다. */
  const blockedRef = useRef(false)
  const [historyBlocked, setHistoryBlocked] = useState(false)
  /* 지금 판에 **이미 실린 앞 봉의 수**. 새로 받은 것만 넘기려면 「저장소에 몇
     개가 있나」가 아니라 「이 판이 몇 개를 받았나」를 세어야 합니다 — 판을 다시
     세우는 자리가 앞 봉까지 함께 싣는데, 그 사이에 끝난 물음이 「받은 수」로
     잘라 넘기면 같은 봉이 두 벌 섭니다. */
  const loadedRef = useRef(0)
  /* 종목이 바뀌면 풉니다. 못 받은 것은 **그 종목의 사정**이라, 안 풀면 이 칸에
     다음에 서는 종목이 한 번도 안 물어보고 못 받은 것으로 섭니다.

     **일·분을 오가는 것으로는 안 풉니다.** 같은 종목이라 답도 같은데, 풀어 두면
     탭을 오갈 때마다 같은 거절을 다시 부릅니다. 아래 한 줄이 「종목을 다시
     고르면」이라고 적는 것이 그래서입니다. */
  useEffect(() => {
    blockedRef.current = false
    setHistoryBlocked(false)
  }, [quote.code])
  /* 지금 켜져 있는 지표와 그 칸. 껐다 켤 때 같은 것을 두 번 만들지 않습니다. */
  const madeRef = useRef<Map<string, string>>(new Map())
  /* 십자선이 가리키는 봉. 없으면 마지막 봉입니다. */
  const [cursor, setCursor] = useState<number | null>(null)
  /* 봉이 갱신되거나 칸이 바뀌어 범례를 다시 읽어야 할 때 올립니다. */
  const [version, setVersion] = useState(0)
  const bump = useCallback(() => setVersion((v) => v + 1), [])
  const [legend, setLegend] = useState<{ ohlc: OhlcRow | null; rows: LegendRow[]; bars: number }>({
    ohlc: null,
    rows: [],
    bars: 0,
  })
  const [marks, setMarks] = useState<ValueMark[]>([])
  const [pickerOpen, setPickerOpen] = useState(false)
  /* 크기 관찰자는 처음 한 번만 만들어져, 확대 여부는 이 참조로 읽습니다. */
  const expandedRef = useRef(expanded)
  expandedRef.current = expanded
  /* 그리는 중인 도형의 id. 도구를 풀면 지웁니다. */
  const drawingRef = useRef<string | null>(null)
  /* 이 종목의 도형. 라이브러리 id 와 저장 모양을 함께 듭니다. */
  const drawingsRef = useRef<{ id: string; drawing: Drawing }[]>([])
  /* 누른 도형. 팝오버가 이 도형을 고칩니다. */
  const [picked, setPicked] = useState<{ id: string; left: number; top: number } | null>(null)
  const pickedStyle = drawingsRef.current.find((item) => item.id === picked?.id)?.drawing.style
  /* 도형·동기화의 열쇠. 종목과 봉 종류를 함께 봅니다 — 일봉에 그은 추세선이
     분봉에 뜨면 안 되고, 일봉 칸과 분봉 칸은 같은 거리를 밀어도 같은 자리가
     아닙니다. */
  const drawKey = `${quote.code}:${span}`

  /* 저장이 진실입니다. 저장하고 나면 다른 칸에 알려, 같은 종목을 띄운 칸이
     같은 도형을 보게 합니다 — 한 칸에서 지운 선이 옆 칸에 남으면 안 됩니다. */
  const persist = useCallback(() => {
    saveDrawings(
      drawKey,
      drawingsRef.current.map((item) => item.drawing),
    )
    onDrawingsChange()
    // onDrawingsChange 는 부모의 카운터를 올리는 고정 함수입니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawKey])

  /* 저장소에서 이 종목·봉의 도형을 다시 올립니다. */
  const reloadDrawings = useCallback(
    (chart: Chart) => {
      /* 도형만 지웁니다. 인자 없이 부르면 매매 표시까지 사라집니다 —
         표는 실행이 주는 값이라 종목·봉을 바꿔도 그 실행이 살아 있는 한
         남아야 합니다. */
      chart.removeOverlay({ groupId: DRAW_GROUP })
      drawingRef.current = null
      setPicked(null)
      drawingsRef.current = []
      for (const drawing of loadDrawings(drawKey)) {
        const id = mount(chart, drawing)
        if (id) drawingsRef.current.push({ id, drawing })
      }
    },
    // mount 는 아래에서 정의되지만 고정 함수입니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [drawKey],
  )

  /* 도형을 라이브러리에 올립니다. 누르면 팝오버가 뜹니다. */
  const mount = useCallback(
    (chart: Chart, drawing: Drawing): string | null => {
      const id = chart.createOverlay({
        name: drawing.name,
        groupId: DRAW_GROUP,
        points: drawing.points,
        styles: overlayStyles(drawing.style),
        onClick: (event) => {
          const box = boxRef.current
          const rect = box?.getBoundingClientRect()
          const left = Math.max(0, Math.min((event.pageX ?? 0) - (rect?.left ?? 0) - window.scrollX, (rect?.width ?? 300) - 240))
          const top = Math.max(0, (event.pageY ?? 0) - (rect?.top ?? 0) - window.scrollY + 12)
          setPicked({ id: event.overlay.id, left, top })
        },
      })
      return typeof id === 'string' ? id : null
    },
    [],
  )

  // 만들기와 없애기. 종목·기간이 바뀌어도 차트는 그대로 두고 값만 갈아 끼웁니다.
  useEffect(() => {
    const box = boxRef.current
    if (!box) return
    ensureRectOverlay()
    /* 가로축 시각과 십자선 시각 표는 한국시간으로 적습니다. 봉 시각이 한국 장의
       시각이라, 이 PC 의 시간대로 적으면 날짜(`dayText`)와 시각이 다른 시계가 됩니다. */
    const chart = init(box, { styles: styleFromTokens(), timezone: 'Asia/Seoul' })
    chartRef.current = chart
    if (!chart) return

    /* 마지막 봉과 오른쪽 축 사이에 두는 여백. 라이브러리 기본값은 80px 이라
       좁은 창에서는 그림의 한 뼘이 통째로 비고, 봉이 없는 자리에 날짜 눈금만
       하나 더 찍힙니다. 다음 봉이 들어올 자리만큼만 둡니다. */
    chart.setOffsetRightDistance(16)

    chart.overrideYAxis({
      paneId: CANDLE_PANE,
      createTicks: ticksClearOfLastMark(() => liveRef.current?.close ?? null),
    })

    /* 십자선을 따라 범례 값이 바뀝니다. 액션은 화면 좌표만 주므로 어느 봉인지는
       여기서 되찾습니다. 차트 밖으로 나가면 액션이 오지 않아, 나가는 것은
       따로 듣고 마지막 봉으로 돌아갑니다. */
    const onCross = (data?: unknown) => {
      const cross = (data ?? {}) as Crosshair
      if (typeof cross.x !== 'number') {
        setCursor(null)
        return
      }
      const point = chart.convertFromPixel([{ x: cross.x }], {
        paneId: cross.paneId ?? CANDLE_PANE,
      }) as Array<{ dataIndex?: number }>
      const index = point[0]?.dataIndex
      setCursor(typeof index === 'number' ? index : null)
    }
    chart.subscribeAction('onCrosshairChange', onCross)
    const onLeave = () => setCursor(null)
    box.addEventListener('mouseleave', onLeave)

    /* 칸 경계를 끌면 칸의 위치가 바뀌므로 범례도 따라갑니다. 밀고 당기는
       것은 같은 종목의 다른 칸에도 전합니다. */
    chart.subscribeAction('onPaneDrag', bump)
    chart.subscribeAction('onScroll', () => {
      bump()
      sync.follow(slot)
    })
    chart.subscribeAction('onZoom', () => {
      bump()
      sync.follow(slot)
    })

    /* 창 크기는 라이브러리가 스스로 안 봅니다. 사이드바를 열거나 창을 줄이면
       그때마다 알려줘야 그림이 늘어나거나 잘리지 않습니다. */
    /* 크기가 실제로 바뀌었을 때만 다시 잽니다. 스크롤바가 생기고 없어지는
       것처럼 알림은 오는데 치수는 같은 경우가 있고, 그때마다 칸을 다시 나누면
       그리기가 꼬리를 뭅니다. 한 프레임에 여러 알림이 오면 한 번으로 모읍니다. */
    let lastWidth = box.clientWidth
    let lastHeight = box.clientHeight
    let frame = 0
    const observer = new ResizeObserver(() => {
      if (frame) return
      frame = window.requestAnimationFrame(() => {
        frame = 0
        const width = box.clientWidth
        const height = box.clientHeight
        if (width === 0 || height === 0) return
        if (width === lastWidth && height === lastHeight) return
        const heightChanged = height !== lastHeight
        lastWidth = width
        lastHeight = height
        chart.resize()
        if (heightChanged) fitPanes(chart, box, expandedRef.current)
        bump()
      })
    })
    observer.observe(box)

    /* 창이 가려져 있는 동안 크기가 바뀌면 라이브러리가 그리기를 미루다 놓칩니다.
       다시 보일 때 한 번 더 재서 칸이 어긋난 채 남지 않게 합니다. */
    const onVisible = () => {
      if (document.visibilityState !== 'visible') return
      chart.resize()
      fitPanes(chart, box, expandedRef.current)
      bump()
    }
    document.addEventListener('visibilitychange', onVisible)

    /* 밝기를 바꾸면 색 토큰이 통째로 바뀝니다. 라이브러리는 그것을 모르므로
       바뀐 값을 다시 넣어 줍니다. */
    const theme = new MutationObserver(() => chart.setStyles(styleFromTokens()))
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })

    return () => {
      observer.disconnect()
      if (frame) window.cancelAnimationFrame(frame)
      theme.disconnect()
      box.removeEventListener('mouseleave', onLeave)
      document.removeEventListener('visibilitychange', onVisible)
      sync.unregister(slot)
      chartRef.current = null
      madeRef.current = new Map()
      drawingsRef.current = []
      dispose(box)
    }
  }, [bump, slot, sync])

  // 종목·기간이 바뀌면 봉을 다시 넣고, 그 종목의 도형을 올립니다.
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return

    chart.setSymbol({ ticker: quote.code, pricePrecision: quote.decimals, volumePrecision: 0 })
    chart.setPeriod({ type: span, span: 1 })
    /* 눈금 글자는 봉 종류를 따릅니다. 칸이 선 뒤에 분·일을 오가도 바뀌도록
       봉 종류가 바뀔 때마다 다시 겁니다. */
    chart.overrideXAxis({ createTicks: span === 'minute' ? ticksWithDayMark : ticksWithYear })

    /* 봉을 안 그리기로 한 자리에서는 **눈금도 값을 말하면 안 됩니다.** 봉이
       없으면 라이브러리가 제 기본 범위(0~10)로 눈금을 세우는데, 1,383 짜리
       종목 옆에서 그 눈금은 「이 종목은 0에서 10 사이」라고 말합니다. 값을
       안 말하기로 한 판단의 나머지 절반입니다. */
    chart.setStyles({ yAxis: { tickText: { show: !(missing || dailyMissing) } } })
    liveRef.current = null
    sync.register(slot, drawKey, chart)

    /* 봉을 처음 채우는 것과 실시간으로 잇는 것이 한 자리에 있습니다. `getBars` 는
       저장소의 조회 봉과 그 위에 접힌 봉을 싣고, `subscribeBar` 는 저장소를 구독해
       접힌 마지막 봉을 갈아 끼웁니다. */
    let unsubscribe: (() => void) | undefined

    chart.setDataLoader({
      getBars: ({ type, callback }) => {
        /* 라이브러리는 **왼쪽 끝에 닿으면 `forward`**(더 과거), 오른쪽 끝에 닿으면
           `backward`(더 최근)를 부릅니다. 최근 쪽은 구독으로 흐르므로 여기서는
           빈 응답을 줍니다 — 같은 봉을 또 주면 끝없이 불어납니다. */
        if (type === 'forward') {
          /* 분봉만 이어 받습니다. 못 이어 받는 자리에서는 「없다」로 답해야
             라이브러리가 왼쪽 끝에서 다시 묻지 않습니다. */
          if (span !== 'minute' || missing || blockedRef.current) {
            callback([], { forward: false })
            return
          }
          void loadHistory(quote.code).then(({ failed }) => {
            const held = quoteEntry(quote.code)
            /* 못 받았으면 **이 차트에서는** 닫습니다. 같은 자리에서 또 물어도
               같은 답이 오는데, 왼쪽 끝은 손이 닿을 때마다 부르는 자리입니다. */
            if (failed) {
              blockedRef.current = true
              setHistoryBlocked(true)
              callback([], { forward: false })
              return
            }
            /* **이 판에 아직 안 실린 것만** 넘깁니다 — 라이브러리가 제 목록 앞에
               이어 붙이므로, 이미 실린 것을 또 주면 같은 시각의 봉이 두 벌 섭니다. */
            const all = held.history.bars
            const fresh = all.slice(0, Math.max(0, all.length - loadedRef.current))
            loadedRef.current = all.length
            callback(fresh, { forward: !held.history.done })
            if (fresh.length === 0) return
            shownRef.current = [...held.history.bars, ...(held.bars ?? []), ...held.live]
            markSessionBreaks(chart, quote.code, shownRef.current)
            bump()
          })
          return
        }
        if (type !== 'init') {
          callback([], { backward: false })
          return
        }
        /* 두 시장 다 서버 봉만 씁니다. 분봉은 조회 봉(주간·야간 한 벌) 뒤에 체결로
           접은 봉을 잇고, 일봉은 조회 봉뿐입니다. 아직 안 왔으면 **비워 둡니다** —
           지어낸 봉을 세우면 헤더는 「받는 중」인데 차트만 값을 말합니다. */
        const held = quoteEntry(quote.code)
        const bars = missing
          ? []
          : span === 'minute'
            ? [...held.history.bars, ...(served ?? []), ...held.live]
            : [...(daily.bars ?? []), ...held.dailyLive]
        liveRef.current = bars[bars.length - 1] ?? null
        shownRef.current = bars
        /* 판을 세울 때 **앞 봉도 함께 싣습니다** — 그러니 이 판이 받은 수도 여기서
           맞춰 둡니다. 안 맞추면 다음 한 번이 같은 봉을 또 싣습니다. */
        loadedRef.current = missing || span !== 'minute' ? 0 : held.history.bars.length
        /* **복사해서 넘깁니다.** 라이브러리는 받은 배열을 제 목록으로 그대로 쓰고
           실시간 봉을 거기에 덧붙입니다 — 저장소의 배열을 그대로 주면 저장소가
           든 봉이 차트 손에 늘어나, 같은 종목을 보는 다른 칸까지 그 봉을 읽습니다. */
        /* 왼쪽 끝에서 더 받을 수 있다고 알려 둡니다 — 이 표시가 없으면 라이브러리가
           왼쪽 끝에 닿아도 묻지 않습니다. */
        callback([...bars], {
          forward:
            span === 'minute' &&
            !missing &&
            bars.length > 0 &&
            !held.history.done &&
            !blockedRef.current,
          backward: false,
        })
        markSessionBreaks(chart, quote.code, bars)
        bump()
        /* 같은 종목을 이미 띄운 칸이 있으면 그 칸의 구간으로 맞춥니다 — 한 칸으로
           접었다 다시 두 칸으로 펼 때 두 차트가 다른 자리에서 시작하면 안 됩니다. */
        window.setTimeout(() => sync.adopt(slot), 0)
      },

      subscribeBar: ({ callback }) => {
        if (missing) return
        /* **일봉도 잇습니다.** 오늘 봉이 조회한 순간에 멈춰 있으면 분봉은 흐르는데
           일봉만 낡은 종가를 말합니다. 접는 규칙은 저장소가 정합니다 — 주간 체결만
           접고, 날이 바뀌면 새 봉입니다. */
        const folded = () => {
          const entry = quoteEntry(quote.code)
          return span === 'minute' ? entry.live : entry.dailyLive
        }
        /* 저장소가 접은 봉 중 아직 안 실은 것을 순서대로 넘깁니다. 같은 열쇠면
           라이브러리가 마지막 봉을 갈아 끼우고, 새 열쇠면 덧붙입니다. 새 봉이 서면
           세션 창을 넘었을 수 있어 경계선도 다시 봅니다 — 체결마다는 아닙니다. */
        let pushedKey = liveRef.current?.timestamp ?? 0
        let pushed: Bar | null = liveRef.current
        const push = (): boolean => {
          const entry = quoteEntry(quote.code)
          let changed = false
          for (const bar of folded()) {
            if (bar.timestamp < pushedKey || bar === pushed) continue
            const started = bar.timestamp > pushedKey
            pushedKey = bar.timestamp
            pushed = bar
            liveRef.current = bar
            callback(bar)
            changed = true
            if (started && span === 'minute') {
              shownRef.current = [...entry.history.bars, ...(entry.bars ?? []), ...entry.live]
              markSessionBreaks(chart, quote.code, shownRef.current)
            }
          }
          return changed
        }
        push()
        /* 저장소는 어느 종목이 바뀌어도 알리므로, 이 종목의 봉이 실제로 바뀐 때만
           범례를 다시 읽습니다. */
        unsubscribe = subscribeQuotes(() => {
          if (push()) bump()
        })
      },

      unsubscribeBar: () => {
        unsubscribe?.()
        unsubscribe = undefined
      },
    })

    /* 도형은 종목에 붙습니다. 이전 종목의 도형을 내리고 이 종목의 것을 올립니다. */
    reloadDrawings(chart)

    const box = boxRef.current
    if (box) fitPanes(chart, box, expanded)

    return () => unsubscribe?.()
    // 확대는 아래 효과가 따로 맞춥니다. 여기서 봉을 다시 넣으면 안 됩니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    /* **시세를 통째로 두지 않습니다.** 이 효과가 종목에서 쓰는 것은 신원과
       자릿수뿐입니다. 통째로 두면 값이 바뀔 때마다 봉·도형·구간이 다시 실립니다.
       조회 봉 참조(`served`·`daily.bars`)는 조회 때만 바뀝니다. */
    quote.code,
    quote.decimals,
    span,
    served,
    daily.bars,
    missing,
    dailyMissing,
    bump,
    slot,
    sync,
    reloadDrawings,
    drawKey,
  ])

  /* 다른 칸에서 도형이 바뀌었습니다. 같은 종목이면 여기도 다시 읽습니다. */
  useEffect(() => {
    if (drawVersion === 0) return
    const chart = chartRef.current
    if (chart) reloadDrawings(chart)
  }, [drawVersion, reloadDrawings])

  // 설정대로 지표를 만들고, 고치고, 없앱니다.
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return

    allIndicatorDefs().forEach((def, index) => {
      const setting = settings[def.name]
      const has = madeRef.current.has(def.name)
      /* 설정에 없는 지표는 꺼진 것입니다 — 다른 화면이 등록해 그 화면에서만 켜는
         지표(`extraIndicators`)가 그렇습니다. */
      if (!setting) {
        if (has) {
          chart.removeIndicator({ name: def.name })
          madeRef.current.delete(def.name)
        }
        return
      }
      const overlay = def.group === 'top'
      /* 계산에 종목 정보가 드는 지표는 그 정보를 함께 넘깁니다. */
      const extend = extendOfIndicator(def.name)
      const create = {
        name: def.name,
        calcParams: setting.params,
        visible: !setting.hidden,
        styles: { lines: lineStyles(setting) },
        ...(extend ? { extendData: extend(quote.code) } : {}),
      }

      if (setting.on && !has) {
        /* 봉 위에 겹치는 지표는 봉 칸에 쌓고, 축이 다른 지표는 아래에 제 칸을
           받습니다. 한 칸에 섞으면 값의 범위가 달라 한쪽이 눌립니다.
           아래 칸의 이름은 이 코드가 정합니다 — 만들기의 반환값은 칸이 아니라
           지표의 id 라, 라이브러리가 지어 준 칸은 다시 찾을 수 없습니다. */
        const paneId = overlay ? CANDLE_PANE : `pane_${def.name}`
        const made = chart.createIndicator({ ...create, paneId }, overlay)
        if (made !== null) {
          madeRef.current.set(def.name, paneId)
          if (!overlay) {
            /* 아래 칸의 순서는 목록 순서입니다. 켠 순서로 두면 거래량을 껐다
               켤 때마다 배치가 바뀝니다 — 늘 같은 자리에 있어야 눈이 찾습니다. */
            chart.setPaneOptions({ id: paneId, order: 100 + index })
            /* 아래 칸의 마지막 값 배지도 눈금 하나를 가립니다. 봉 칸의 현재가
               표와 같은 규칙으로 그 눈금을 빼고, 남은 눈금의 자릿수를 맞춥니다. */
            const clear = ticksClearOfLastMark(() => lastLineValue(chart, paneId))
            chart.overrideYAxis({
              paneId,
              createTicks: (params) =>
                withDecimals(clear(params), axisDecimals(def.name, decimalsRef.current)),
            })
          }
        }
      } else if (!setting.on && has) {
        chart.removeIndicator({ name: def.name })
        madeRef.current.delete(def.name)
      } else if (setting.on && has) {
        /* 다시 만들지 않고 값만 갈아 끼웁니다 — 다시 만들면 선이 한 번
           사라졌다 나타나고, 겹쳐 그린 칸이 잠깐 비어 보입니다. */
        chart.overrideIndicator(create)
      }
    })

    /* 칸이 늘거나 줄었으니 높이를 다시 나누고, 세션 구분선도 칸마다 다시 세웁니다. */
    const box = boxRef.current
    if (box) fitPanes(chart, box, expanded)
    markSessionBreaks(chart, quote.code, shownRef.current)
    bump()
    /* 지표 계산은 라이브러리가 뒤에 마칩니다. 한 박자 뒤에 한 번 더 읽어야
       범례가 새 기간의 값을 보입니다. */
    const later = window.setTimeout(bump, 120)
    return () => window.clearTimeout(later)
  }, [settings, expanded, bump])

  /* 시간표가 봉보다 늦게 오면 경계는 그때 압니다. 온 뒤 한 번 다시 세웁니다. */
  const timetable = useTimetable()
  useEffect(() => {
    const chart = chartRef.current
    if (!chart || timetable === 'idle' || timetable === 'loading') return
    markSessionBreaks(chart, quote.code, shownRef.current)
    // 종목이 바뀔 때는 봉을 채우는 효과가 세웁니다. 여기서는 시간표가 온 순간만.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timetable])

  /* 종목 정보를 쓰는 지표(세션 창을 보는 VWAP 등)는 종목이 바뀌거나 시간표가 온
     뒤 그 정보로 다시 셉니다. 그런 지표를 안 켠 차트에서는 하는 일이 없습니다. */
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    for (const name of madeRef.current.keys()) {
      const extend = extendOfIndicator(name)
      if (extend) chart.overrideIndicator({ name, extendData: extend(quote.code) })
    }
  }, [quote.code, timetable])

  /* 확대·복귀·분할 직후 폭을 다시 잽니다. 카드가 커졌는데 라이브러리는 모릅니다. */
  useEffect(() => {
    const chart = chartRef.current
    const box = boxRef.current
    if (!chart || !box) return
    chart.resize()
    fitPanes(chart, box, expanded)
    bump()
  }, [expanded, split, bump])

  /* 봉·칸·십자선이 바뀔 때마다 범례와 배지를 다시 읽습니다. 라이브러리가
     칸을 다 놓은 뒤에 읽어야 자리가 맞으므로 한 틱 미루고, **다음 틀에서 한 번
     더** 읽습니다 — 지표를 켜고 끄거나 칸 높이가 바뀐 직후에는 카드 높이도 함께
     바뀌어, 한 틱 뒤의 칸 자리가 아직 옛 자리일 수 있습니다. */
  useEffect(() => {
    const chart = chartRef.current
    const box = boxRef.current
    if (!chart || !box) return
    const collect = () => {
      setLegend(collectLegend(chart, box, quote, settings, cursor))
      setMarks(collectMarks(chart, box, quote, settings))
    }
    const timer = window.setTimeout(collect, 0)
    const frame = window.requestAnimationFrame(collect)
    return () => {
      window.clearTimeout(timer)
      window.cancelAnimationFrame(frame)
    }
  }, [version, cursor, quote, settings])

  /* 봉 칸 위쪽 여백. 종목 배지와 그 아래 범례(시고저종 줄 + 봉 칸에 겹친 지표 줄)가
     봉 칸 위에 얹혀 있어, 여백이 모자라면 최고가 표가 그 밑에 깔립니다. 범례가
     새 자리에 선 뒤 그 아래 끝을 재서 여백을 맞춥니다 — 줄 수가 지표에 따라
     바뀌므로 값을 못 박지 않습니다. 여백이 바뀌면 끝 값 배지 자리도 바뀌어 한
     번 더 읽습니다. 라이브러리는 축 설정을 덮어쓰지 않고 합치므로, 여백만 넘겨도
     먼저 준 눈금 규칙(`createTicks`)은 그대로 남습니다. */
  const headroomRef = useRef<{ chart: Chart | null; gap: number | null }>({ chart: null, gap: null })
  useLayoutEffect(() => {
    const chart = chartRef.current
    const box = boxRef.current
    const root = box?.parentElement
    if (!chart || !box || !root) return
    const pane = chart.getSize(CANDLE_PANE, 'main')
    const canvasTop = box.getBoundingClientRect().top
    const head = [...root.querySelectorAll<HTMLElement>('.chart-badge, .legend-candle')]
    if (!pane || head.length === 0) return
    const headBottom = Math.max(...head.map((one) => one.getBoundingClientRect().bottom)) - canvasTop - pane.top
    /* 라이브러리가 최고가 표를 다는 봉 — 보이는 봉 가운데 고가가 가장 높은 것. */
    const bars = chart.getDataList()
    const { realFrom, realTo } = chart.getVisibleRange()
    let highest = -1
    for (let index = Math.max(0, realFrom); index < Math.min(bars.length, realTo); index++) {
      if (highest < 0 || bars[index].high > bars[highest].high) highest = index
    }
    if (highest < 0) return
    const point = chart.convertToPixel({ dataIndex: highest, value: bars[highest].high }, { paneId: CANDLE_PANE })
    const highY = (Array.isArray(point) ? point[0]?.y : point.y) ?? Number.NaN
    const held = headroomRef.current
    const current = held.chart === chart && held.gap !== null ? held.gap : DEFAULT_TOP_GAP
    const textSize = chart.getStyles().candle.priceMark.high.textSize
    const gap = headroomGap(headBottom, textSize, pane.height, highY, current)
    if (held.chart === chart && (held.gap === gap || (held.gap !== null && gap !== null && Math.abs(held.gap - gap) < 0.5)))
      return
    headroomRef.current = { chart, gap }
    chart.overrideYAxis({ paneId: CANDLE_PANE, gap: { top: gap ?? DEFAULT_TOP_GAP, bottom: BOTTOM_GAP } })
    bump()
    // 범례를 접고 펴면 머리 높이가 바뀌어 여백을 다시 셉니다.
  }, [legend, bump, legendFold?.open])

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

  /* 모두 지우기. */
  useEffect(() => {
    if (clearSignal === 0) return
    const chart = chartRef.current
    if (!chart) return
    /* 「모두 지우기」는 **내가 그린 도형**을 지우는 것입니다. 매매 표시는
       내가 그린 것이 아니라 실행의 기록이라 여기서 사라지면 안 됩니다. */
    chart.removeOverlay({ groupId: DRAW_GROUP })
    drawingRef.current = null
    drawingsRef.current = []
    setPicked(null)
    persist()
  }, [clearSignal, persist])

  const restyle = (style: DrawingStyle) => {
    const chart = chartRef.current
    const item = drawingsRef.current.find((entry) => entry.id === picked?.id)
    if (!chart || !item) return
    item.drawing = { ...item.drawing, style }
    chart.overrideOverlay({ id: item.id, styles: overlayStyles(style) })
    rememberDrawingStyle(style)
    persist()
    bump()
  }

  const removePicked = () => {
    const chart = chartRef.current
    if (!chart || !picked) return
    chart.removeOverlay({ id: picked.id })
    drawingsRef.current = drawingsRef.current.filter((entry) => entry.id !== picked.id)
    setPicked(null)
    persist()
  }

  /* 숨김도 설정의 일부라 남습니다. 새로고침하면 다시 보이는 것은 「내가 숨긴
     것」이 무시된 상태입니다. */
  const hide = (name: string, hidden: boolean) => onSettingChange(name, { ...settings[name], hidden })

  /* 등락이 안 왔으면 색도 없습니다 — 방향을 모르는 값에 방향색을 입힐 수 없습니다. */
  const changeTone = quote.change === null ? '' : toneOf(quote.change)
  /* 옵션인데 아직 안 고른 축이 있는가. 헤더가 보는 것과 같은 자리에서 보고,
     남은 축의 낱말도 같은 한 벌에서 가져옵니다. */
  const pendingLeg = needsLeg(quote.code)
  const pendingWord = PENDING_TEXT[quote.pendingAxis ?? 'strike'].pick
  /* 칸이 이보다 낮아지면 카드가 세로로 스크롤합니다. 봉 칸의 바닥 + 아래 칸
     바닥들 + 시간 축입니다. */
  const subCount = allIndicatorDefs().filter((def) => def.group === 'bottom' && settings[def.name]?.on).length
  const minHeight = CANDLE_MIN + subCount * (PANE_FLOOR + 1) + X_AXIS_HEIGHT
  /* 분수로 부르는 품목이면 배지도 분수로 적습니다 — 헤더·호가와 같은 말을
     써야 같은 값으로 읽힙니다. */
  const money = (value: number) =>
    quote.fraction
      ? fractionText(value, quote.fraction)
      : value.toLocaleString('ko-KR', {
          minimumFractionDigits: quote.decimals,
          maximumFractionDigits: quote.decimals,
        })

  /* 배지 안의 글자 — 누르는 배지와 글자 배지가 같은 것을 적습니다. */
  const badgeBody = (
    <>
    <b>{quote.name}</b>
    {/* 콜/풋과 행사가가 다 정해지기 전에는 종목이 아직 없습니다.

        그동안 차트가 그리는 것은 **기초 선물**이라, 값과 등락을 옵션 품목
        이름 옆에 세우면 그 이름의 시세로 읽힙니다. 그래서 대기 중에는 값을
        빼고 무엇이 남았는지만 적습니다 — 기초 선물의 현재가는 바로 위
        헤더가 이미 큼직하게 보이고 있습니다.

        낱말은 헤더·카탈로그·최근 본과 같은 한 벌에서 옵니다. */}
    {/* 값을 못 받았으면 여기서도 값을 말하지 않습니다 — 헤더가 「받지
        못했습니다」인데 차트 배지가 가격을 적으면 한 화면이 두 말을 합니다.
        대기 중과 자리는 같고 까닭만 다릅니다. */}
    {pendingLeg || missing || dailyMissing ? (
      <span className="chart-badge-pending">{pendingLeg ? pendingWord : missingWord}</span>
    ) : (
      <>
        <span className={`chart-badge-price ${changeTone}`}>
          {quote.last !== null && money(quote.last)}
        </span>
        {/* 등락이 안 온 칸은 빈 채입니다 — 0 으로 적으면 「안 움직였다」가 되고,
            「—」는 이 시장에 원래 없는 값의 말입니다. */}
        <span className={`chart-badge-change ${changeTone}`}>
          {quote.change !== null && `${quote.change > 0 ? '+' : ''}${money(quote.change)}`}
          {quote.changePct !== null &&
            ` (${quote.changePct > 0 ? '+' : ''}${quote.changePct.toFixed(2)}%)`}
        </span>
      </>
    )}
    {/* 봉 종류. 두 칸이 다른 봉을 볼 수 있어 배지가 말합니다. */}
    <span className="chart-badge-span">· {SPAN_LABEL[span]}</span>
    </>
  )

  return (
    <div
      className={`chart-box${split ? (active ? ' is-target' : ' is-idle') : ''}`}
      style={{ minHeight }}
      /* 칸을 누르면 주문 대상이 됩니다. 도형·범례 단추를 눌러도 같이 됩니다 —
         만지고 있는 차트가 곧 보고 있는 차트입니다. */
      onMouseDown={split && !active ? onActivate : undefined}
    >
      <div className="chart-canvas" ref={boxRef} />

      {/* 종목 배지. 두 칸일 때 어느 칸이 어느 종목인지는 이 배지가 말하고,
          ▾ 로 이 칸의 종목만 바꿉니다. 종목을 바꿀 수 없는 차트(전략 검증의
          차트처럼 실행이 종목을 정하는 곳)에서는 **누르는 것이 아닌 글자**로 섭니다 —
          누를 수 있게 두면 골라도 아무 일이 없는 단추가 됩니다. */}
      {onPickInstrument ? (
        <button
          type="button"
          className="chart-badge"
          style={{ top: legend.ohlc?.top ?? 0 }}
          aria-expanded={pickerOpen}
          aria-label={`${quote.name}${pendingLeg ? ` ${pendingWord}` : ''} — 이 차트의 종목 바꾸기`}
          /* 배지를 누르는 것은 종목을 「보려는」 것이지 주문 대상을 옮기는 것이
             아닙니다. 칸의 활성 전환에 섞이지 않게 합니다. */
          onMouseDown={(event) => event.stopPropagation()}
          onClick={() => setPickerOpen((open) => !open)}
        >
          {badgeBody}
          <span className="chart-badge-chev" aria-hidden="true">
            ▾
          </span>
        </button>
      ) : (
        <span className="chart-badge is-static" style={{ top: legend.ohlc?.top ?? 0 }}>
          {badgeBody}
        </span>
      )}

      {pickerOpen && (
        <InstrumentPicker
          current={quote.code}
          onPick={(item) => {
            setPickerOpen(false)
            if (item.code !== quote.code) onPickInstrument?.(item)
          }}
          onClose={() => setPickerOpen(false)}
        />
      )}

      {/* **조용히 적습니다.** 앞쪽 어느 날은 서버가 다 주지 못했을 수 있다는 말이고,
          할 일이 생기는 말이 아닙니다 — 단추도 색도 없이 한 줄입니다.

          둘이 함께 참일 때는 **못 받은 쪽만** 세웁니다. 조용한 자리가 두 줄이
          되면 조용하지 않고, 덜 받은 것보다 아예 못 받은 것이 먼저입니다. */}
      {span === 'minute' && historyBlocked ? (
        <span className="chart-quiet">
          과거 분봉을 못 받았습니다 — 종목을 다시 고르면 다시 묻습니다
        </span>
      ) : (
        span === 'minute' &&
        shortDays && <span className="chart-quiet">앞쪽 어느 날은 덜 받았을 수 있습니다</span>
      )}

      <ChartLegend
        bars={legend.bars}
        quote={quote}
        ohlc={legend.ohlc}
        rows={legend.rows}
        onHide={hide}
        onRemove={(name) => onSettingChange(name, { ...settings[name], on: false })}
        fold={legendFold}
      />

      {marks.map((mark) => (
        <span
          key={mark.name}
          className="chart-mark"
          style={{ top: mark.top, background: mark.color }}
          aria-hidden="true"
        >
          {mark.text}
        </span>
      ))}

      {picked && pickedStyle && (
        <DrawingStylePopover
          style={pickedStyle}
          left={picked.left}
          top={picked.top}
          onPick={restyle}
          onRemove={removePicked}
          onClose={() => setPicked(null)}
        />
      )}
    </div>
  )
}
