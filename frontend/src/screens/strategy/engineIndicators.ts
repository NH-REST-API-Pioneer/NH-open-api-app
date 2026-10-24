import { registerIndicator, type KLineData } from 'klinecharts'

import { resolve } from '../../data/instruments'
import { overseasTradingWindows, sessionWindows, type Window } from '../../data/session'
import { kstDay, kstParts } from '../../lib/kst'
import { sessionOf } from '../trade/chartSessions'
import { addExtraIndicator, type ExtraIndicatorDef } from '../trade/extraIndicators'

/* 검증 차트에만 켜는 지표 넷 — **서버 엔진과 같은 식**으로 셉니다.
 *
 * 판정은 늘 서버가 하고, 기준 식은 서버의 지표 모듈(`backend/strategy/indicators.py`)
 * 첫머리에 적혀 있습니다. 차트 라이브러리의 기본 지표 가운데 그 식과 값이 같은
 * 것(이동평균·EMA·볼린저 밴드·RSI)은 기본 지표를 그대로 쓰고, 값이 다른 것과
 * 라이브러리에 없는 것을 여기서 같은 식으로 셉니다. 조건 표의 값과 차트 범례의
 * 값이 같은 봉에서 같아야, 「차트에서는 교차했는데 왜 안 샀나」에 답할 수 있습니다.
 *
 *   MACD        막대 = DIF − DEA 입니다. 라이브러리 기본 MACD 는 막대에 2 를 곱합니다.
 *   스토캐스틱  %K = 원값의 단순 이동평균(K), %D = %K 의 단순 이동평균(D)이고,
 *               n봉 최고와 최저가 같으면 원값은 50 입니다. 라이브러리 기본 KDJ 는
 *               1/K 가중으로 이어 세고 시작값이 50 입니다.
 *   VWAP        세션마다 처음부터 다시 셉니다. 세션은 봉의 **거래일과 세션 창**이 같은
 *               봉들입니다. 국내 야간은 다음 거래일이고, 해외는 그 봉이 든 거래소
 *               거래 창이 시작한 날이 거래일입니다(한국 시각 자정을 넘는 세션도 한
 *               거래일). 누적 거래량이 0 이면 값이 없습니다.
 *   ATR         Wilder 평활한 참 범위입니다. 라이브러리에 없습니다.
 *
 * 일반주문 차트의 지표는 그대로입니다 — 여기 지표는 그 차트의 설정에 없습니다.
 */

/* ── 식 ──────────────────────────────────────────────── */

type Column = (number | null)[]

/** 단순 이동평균. 봉이 모자라는 앞쪽은 `null` 입니다. */
function sma(values: number[], period: number): Column {
  const made: Column = values.map(() => null)
  let total = 0
  values.forEach((value, at) => {
    total += value
    if (at >= period) total -= values[at - period]
    if (at >= period - 1) made[at] = total / period
  })
  return made
}

/** 지수 이동평균. 첫 값은 단순 평균으로 시작하고 그 뒤로 2/(n+1) 로 이어 갑니다. */
function ema(values: number[], period: number): Column {
  const made: Column = values.map(() => null)
  if (values.length < period) return made
  const weight = 2 / (period + 1)
  let previous = values.slice(0, period).reduce((sum, value) => sum + value, 0) / period
  made[period - 1] = previous
  for (let at = period; at < values.length; at += 1) {
    previous = (values[at] - previous) * weight + previous
    made[at] = previous
  }
  return made
}

/** 앞쪽이 `null` 인 열에 셈을 걸 때 — 값이 처음 선 자리부터 셉니다. */
function fromFirst(values: Column, count: (part: number[]) => Column): Column {
  const start = values.findIndex((value) => value !== null)
  const made: Column = values.map(() => null)
  if (start === -1) return made
  const tail = count(values.slice(start).map((value) => value as number))
  tail.forEach((value, at) => {
    made[start + at] = value
  })
  return made
}

/** MACD — 선(DIF), 신호(DEA), 막대(DIF − DEA). */
export function macdOf(closes: number[], fast: number, slow: number, signal: number) {
  const short = ema(closes, fast)
  const long = ema(closes, slow)
  const line: Column = short.map((a, at) => (a === null || long[at] === null ? null : a - (long[at] as number)))
  const sig = fromFirst(line, (part) => ema(part, signal))
  const hist: Column = line.map((a, at) => (a === null || sig[at] === null ? null : a - (sig[at] as number)))
  return { line, sig, hist }
}

/** 스토캐스틱 — %K, %D. */
export function stochasticOf(bars: KLineData[], period: number, k: number, d: number) {
  const raw: Column = bars.map(() => null)
  for (let at = period - 1; at < bars.length; at += 1) {
    const window = bars.slice(at - period + 1, at + 1)
    const high = Math.max(...window.map((bar) => bar.high))
    const low = Math.min(...window.map((bar) => bar.low))
    raw[at] = high === low ? 50 : ((bars[at].close - low) / (high - low)) * 100
  }
  const kLine = fromFirst(raw, (part) => sma(part, Math.max(k, 1)))
  const dLine = fromFirst(kLine, (part) => sma(part, Math.max(d, 1)))
  return { kLine, dLine }
}

/** 평균 참 범위 — Wilder 평활. 첫 봉의 참 범위는 고−저입니다. */
export function atrOf(bars: KLineData[], period: number): Column {
  const ranges = bars.map((bar, at) => {
    if (at === 0) return bar.high - bar.low
    const close = bars[at - 1].close
    return Math.max(bar.high - bar.low, Math.abs(bar.high - close), Math.abs(bar.low - close))
  })
  const made: Column = bars.map(() => null)
  if (ranges.length < period) return made
  let previous = ranges.slice(0, period).reduce((sum, value) => sum + value, 0) / period
  made[period - 1] = previous
  for (let at = period; at < ranges.length; at += 1) {
    previous = (previous * (period - 1) + ranges[at]) / period
    made[at] = previous
  }
  return made
}

/** VWAP 의 세션 경계를 정하는 데 드는 것 — 시장과 그 종목의 세션 창. 해외는 거래
 *  창 셋(1차·2차·익일)이고, 시간표에 그 품목이 없으면 `null` 입니다. */
export interface VwapContext {
  market: 'domestic' | 'overseas'
  windows: Window[]
  overseas?: { trading: Window | null; second: Window | null; nextDayTrading: Window | null } | null
}

const minuteOf = (clock: string) => {
  const [hour, minute] = clock.split(':').map(Number)
  return hour * 60 + minute
}

/** 해외 봉이 든 거래 창의 거래일(1970-01-01 부터 센 한국 날). 창 밖이면 `null` 입니다.
 *  서버 세션 판정과 같은 규칙입니다 — 거래일마다(주말 빼고) 창을 세우고, 자정을
 *  넘지 않고 1차보다 일찍 여는 익일 구간은 그 거래일의 다음 날 새벽에 둡니다. */
function overseasDay(timestamp: number, hours: NonNullable<VwapContext['overseas']>): number | null {
  const { hour, minute } = kstParts(timestamp)
  const today = kstDay(timestamp)
  const at = today * 1440 + hour * 60 + minute
  const first = hours.trading
  const next = hours.nextDayTrading
  const nextMorning = next !== null && first !== null && !next.nextDay && minuteOf(next.open) < minuteOf(first.open)
  const slots: [Window | null, boolean][] = [
    [first, false],
    [hours.second, false],
    [next, nextMorning],
  ]
  for (let day = today - 2; day <= today + 1; day += 1) {
    /* 1970-01-01 은 목요일입니다 — (날 + 4) % 7 이 0 이면 일요일, 6 이면 토요일. */
    const weekday = (((day + 4) % 7) + 7) % 7
    if (weekday === 0 || weekday === 6) continue
    for (const [window, shifted] of slots) {
      if (!window) continue
      const start = day * 1440 + minuteOf(window.open) + (shifted ? 1440 : 0)
      const end = day * 1440 + minuteOf(window.close) + (window.nextDay ? 1440 : 0) + (shifted ? 1440 : 0)
      if (start <= at && at < end) return day
    }
  }
  return null
}

/** 봉 하나가 드는 세션의 표지(거래일·세션 창). 서버와 같은 규칙입니다.
 *  - 국내: 주간·야간 창으로 가르고 야간의 정오 뒤 봉은 다음 거래일입니다. 어느 창에도
 *    안 드는 봉은 앞 봉의 창에 붙입니다.
 *  - 해외: 그 봉이 든 거래 창의 거래일이고, 창 밖이면 앞 봉의 거래일을 잇습니다(첫
 *    봉이면 한국 날짜). 시간표에 그 품목이 없으면 한국 날짜입니다. */
function sessionMarks(bars: KLineData[], context: VwapContext): string[] {
  let held = 'domestic-day'
  let before: number | null = null
  return bars.map((bar) => {
    if (context.market === 'overseas') {
      const hours = context.overseas ?? null
      let day = hours ? overseasDay(bar.timestamp, hours) : kstDay(bar.timestamp)
      if (day === null) day = before ?? kstDay(bar.timestamp)
      before = day
      return `${day}|overseas`
    }
    const index = sessionOf(bar.timestamp, context.windows)
    if (index !== -1) held = index === 1 ? 'domestic-night' : 'domestic-day'
    const night = held === 'domestic-night' && kstParts(bar.timestamp).hour >= 12
    return `${kstDay(bar.timestamp) + (night ? 1 : 0)}|${held}`
  })
}

/** 세션 VWAP. 전형가 (고+저+종)/3 × 거래량의 누적 ÷ 누적 거래량이고, 세션 표지가
 *  바뀌는 봉에서 새로 셉니다. */
export function vwapOf(bars: KLineData[], context: VwapContext): Column {
  const marks = sessionMarks(bars, context)
  let total = 0
  let volume = 0
  return bars.map((bar, at) => {
    if (at === 0 || marks[at] !== marks[at - 1]) {
      total = 0
      volume = 0
    }
    const amount = bar.volume ?? 0
    total += ((bar.high + bar.low + bar.close) / 3) * amount
    volume += amount
    return volume > 0 ? total / volume : null
  })
}

/* ── 차트에 등록 ─────────────────────────────────────── */

/** 값이 없으면 그 칸을 비웁니다 — 0 으로 채우면 선이 0 까지 내려갑니다. */
function cell(value: number | null): number | undefined {
  return value === null ? undefined : value
}

export const ENGINE_MACD = 'NH_MACD'
export const ENGINE_STOCH = 'NH_STOCH'
export const ENGINE_VWAP = 'NH_VWAP'
export const ENGINE_ATR = 'NH_ATR'

registerIndicator<Record<string, number | undefined>, number>({
  name: ENGINE_MACD,
  shortName: 'MACD',
  calcParams: [12, 26, 9],
  figures: [
    { key: 'dif', title: 'DIF: ', type: 'line' },
    { key: 'dea', title: 'DEA: ', type: 'line' },
    {
      key: 'macd',
      title: 'MACD: ',
      type: 'bar',
      baseValue: 0,
      styles: ({ data, defaultStyles }) => {
        const value = data.current?.macd ?? 0
        const bars = defaultStyles?.bars?.[0]
        const color = value > 0 ? bars?.upColor : value < 0 ? bars?.downColor : bars?.noChangeColor
        return { style: 'fill', color, borderColor: color }
      },
    },
  ],
  calc: (dataList, indicator) => {
    const [fast, slow, signal] = indicator.calcParams
    const { line, sig, hist } = macdOf(dataList.map((bar) => bar.close), fast, slow, signal)
    return dataList.map((_, at) => ({ dif: cell(line[at]), dea: cell(sig[at]), macd: cell(hist[at]) }))
  },
})

registerIndicator<Record<string, number | undefined>, number>({
  name: ENGINE_STOCH,
  shortName: '스토캐스틱',
  calcParams: [9, 3, 3],
  figures: [
    { key: 'k', title: '%K: ', type: 'line' },
    { key: 'd', title: '%D: ', type: 'line' },
  ],
  calc: (dataList, indicator) => {
    const [period, k, d] = indicator.calcParams
    const { kLine, dLine } = stochasticOf(dataList, period, k, d)
    return dataList.map((_, at) => ({ k: cell(kLine[at]), d: cell(dLine[at]) }))
  },
})

registerIndicator<Record<string, number | undefined>, number, VwapContext | null>({
  name: ENGINE_VWAP,
  shortName: 'VWAP',
  series: 'price',
  precision: 2,
  shouldOhlc: true,
  calcParams: [],
  figures: [{ key: 'vwap', title: 'VWAP: ', type: 'line' }],
  calc: (dataList, indicator) => {
    const context = indicator.extendData ?? { market: 'overseas', windows: [] }
    const made = vwapOf(dataList, context)
    return dataList.map((_, at) => ({ vwap: cell(made[at]) }))
  },
})

registerIndicator<Record<string, number | undefined>, number>({
  name: ENGINE_ATR,
  shortName: 'ATR',
  calcParams: [14],
  figures: [{ key: 'atr', title: 'ATR: ', type: 'line' }],
  calc: (dataList, indicator) => {
    const made = atrOf(dataList, indicator.calcParams[0])
    return dataList.map((_, at) => ({ atr: cell(made[at]) }))
  },
})

/** 종목의 VWAP 세션 정보. 종목을 모르면 해외처럼 거래일만 봅니다. */
function vwapContextOf(code: string): VwapContext {
  const item = resolve(code)
  if (!item) return { market: 'overseas', windows: [] }
  return {
    market: item.market,
    windows: sessionWindows(item.market, item.product.exchangeNo, item.product.code),
    overseas: item.market === 'overseas' ? overseasTradingWindows(item.product.exchangeNo, item.product.code) : null,
  }
}

const DEFS: ExtraIndicatorDef[] = [
  {
    name: ENGINE_MACD,
    label: 'MACD',
    description: '단기·장기 지수이동평균의 차이와 그 신호선 — 막대는 DIF − DEA',
    group: 'bottom',
    params: [
      { label: '단기', value: 12 },
      { label: '장기', value: 26 },
      { label: '신호', value: 9 },
    ],
    lines: ['DIF', 'DEA'],
    extras: ['막대'],
  },
  {
    name: ENGINE_STOCH,
    label: '스토캐스틱',
    description: '지난 n봉의 고저 범위 안에서 종가가 어디쯤인지',
    group: 'bottom',
    params: [
      { label: '기간', value: 9 },
      { label: 'K', value: 3 },
      { label: 'D', value: 3 },
    ],
    lines: ['%K', '%D'],
  },
  {
    name: ENGINE_VWAP,
    label: 'VWAP(세션)',
    description: '세션마다 처음부터 다시 센 거래량 가중 평균가',
    group: 'top',
    params: [],
    lines: ['VWAP'],
    extendOf: vwapContextOf,
  },
  {
    name: ENGINE_ATR,
    label: 'ATR',
    description: '참 범위의 Wilder 평활',
    group: 'bottom',
    params: [{ label: '기간', value: 14 }],
    lines: ['ATR'],
  },
]

DEFS.forEach(addExtraIndicator)
