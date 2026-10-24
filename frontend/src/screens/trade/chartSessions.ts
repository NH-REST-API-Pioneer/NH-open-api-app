/** 차트에서 세션이 갈리는 자리에 서는 구분선.
 *
 *  국내 분봉은 주간·야간 한 벌로 받아 이어 그립니다. 차트는 봉을 시간이 아니라
 *  차례로 놓으므로 앞 세션의 마지막 봉과 다음 세션의 첫 봉이 나란히 붙습니다 —
 *  그 사이를 아무 표 없이 두면 두 시간 넘게 비었던 자리가 1분처럼 읽힙니다.
 *  봉이 붙어 그려지는 자리에 세로선 하나를 세웁니다. 바탕은 칠하지 않습니다.
 *
 *  **국내는 선 양옆에 세션 이름을 답니다** — 왼쪽에 끝난 세션, 오른쪽에 시작한
 *  세션(「주간」·「야간」). 선만으로는 어느 쪽이 밤인지 봉의 시각을 짚어 봐야
 *  압니다. 이름표는 봉 칸 아래쪽에만 섭니다. 위쪽은 범례 자리이고, 아래 칸마다
 *  달면 같은 말이 칸 수만큼 반복됩니다. 해외(1차·2차·익일)는 선만 세웁니다 —
 *  거래소가 부르는 이름이 따로 없어, 지어 붙이면 없는 말이 됩니다.
 *  두 경계 사이가 이름표보다 좁거나 최고·최저가 표를 덮으면 그쪽 이름표만
 *  뺍니다 — 이름표는 꾸밈이고 그 표는 값입니다. 선은 늘 섭니다.
 *
 *  **어디가 경계인지는 시간표가 정합니다** — 봉 사이가 비었다고 세션이 갈린 것이
 *  아닙니다. 체결이 뜸한 종목은 한 세션 안에서도 한 시간 넘게 봉이 비고, 거기에
 *  선을 세우면 없는 경계를 지어내는 것입니다. 봉의 시각이 어느 세션 창에 드는지로
 *  갈라, 앞 봉과 다른 창의 첫 봉 앞에만 세웁니다. 창을 모르면(시간표 없음) 안
 *  세웁니다.
 *
 *  **격자선과 같은 색을 쓰지 않습니다.** 세로 격자선이 이미 잔선색(점선)이라
 *  같은 색이면 격자선 하나로 읽혀 갈린 자리를 못 찾습니다. 옅은 글자색
 *  (`--text-dim`)의 실선 하나 — 같은 카드에서 「· 분」 같은 조용한 글자가 쓰는
 *  잉크라, 눈에 띄되 봉보다 앞서지 않습니다.
 */
import { registerOverlay, utils, type Chart } from 'klinecharts'

import type { Bar } from '../../data/quotes'
import type { Market } from '../../data/instruments'
import type { Window } from '../../data/session'
import { kstMinutes } from '../../lib/kst'

/** 구분선이 속한 무리. 봉을 다시 채울 때 이 무리만 지우고 다시 세웁니다. */
export const SESSION_GROUP = 'session'

/** 세션이 갈린 자리 하나. `before`·`after` 는 앞뒤 세션이 몇 번째 창인지입니다. */
export interface SessionBreak {
  /** 새 세션의 첫 봉 시각. 구분선은 그 봉 바로 앞에 섭니다. */
  timestamp: number
  before: number
  after: number
}

/** 세션이 갈린 뒤 처음 서는 봉들. `windows` 는 이 종목의 세션 창들(국내 주간·야간,
 *  해외 1차·2차·익일)이고, 비어 있으면 갈린 자리를 모르는 것이라 아무것도 안
 *  돌려줍니다. 어느 창에도 안 드는 봉(개장 전 단일가 등)은 앞 세션에 붙여 봅니다 —
 *  그 봉 때문에 선을 세우지도, 세션을 바꾸지도 않습니다. */
export function sessionBreaksOf(bars: readonly Bar[], windows: readonly Window[]): SessionBreak[] {
  if (windows.length === 0) return []
  const breaks: SessionBreak[] = []
  let previous = -1
  for (const bar of bars) {
    const current = sessionOf(bar.timestamp, windows)
    if (current === -1) continue
    if (previous !== -1 && current !== previous) {
      breaks.push({ timestamp: bar.timestamp, before: previous, after: current })
    }
    previous = current
  }
  return breaks
}

/** 세션 창의 이름. 국내만 있습니다 — 창의 차례가 주간·야간입니다
 *  (`sessionWindows`). 해외는 `null` 이라 선만 섭니다. */
export function sessionName(market: Market, index: number): string | null {
  if (market !== 'domestic') return null
  return (['주간', '야간'] as const)[index] ?? null
}

/** 봉의 시각이 몇 번째 창에 드는지. 어디에도 안 들면 -1 입니다. 창의 끝은 열린
 *  구간이라 끝 시각 정각의 봉은 밖입니다. */
export function sessionOf(timestamp: number, windows: readonly Window[]): number {
  /* 창은 한국시간이라 봉의 시각도 한국시간으로 읽습니다. */
  const minute = kstMinutes(timestamp)
  return windows.findIndex((window) => {
    const open = minuteOf(window.open)
    const close = minuteOf(window.close)
    return window.nextDay ? minute >= open || minute < close : minute >= open && minute < close
  })
}

function minuteOf(clock: string): number {
  const [hour, minute] = clock.split(':').map(Number)
  return hour * 60 + minute
}

/* 차트는 캔버스에 그리므로 CSS 이름이 아니라 색 값이 필요합니다. 그릴 때마다
 * 읽어야 밝은·어두운 화면을 오갈 때 선도 따라 바뀝니다. */
function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

let registered = false

/** 구분선을 라이브러리에 등록합니다. 한 번만 돕니다. */
export function ensureSessionBreakOverlay(): void {
  if (registered) return
  registered = true
  registerOverlay({
    name: 'sessionBreak',
    totalStep: 1,
    /* 손으로 옮기거나 고를 것이 아닙니다. 자료가 정한 자리입니다. */
    lock: true,
    needDefaultPointFigure: false,
    needDefaultXAxisFigure: false,
    needDefaultYAxisFigure: false,
    createPointFigures: ({ chart, coordinates, bounding }) => {
      if (coordinates.length < 1) return []
      /* 점은 새 세션의 첫 봉입니다. 선은 그 봉과 앞 봉 사이 — 봉 한 칸의 절반
         앞에 섭니다. 칸 너비는 확대·축소로 바뀌므로 그릴 때마다 읽습니다. */
      const x = coordinates[0].x - chart.getBarSpace().bar / 2
      return [
        {
          type: 'line',
          attrs: { coordinates: [{ x, y: 0 }, { x, y: bounding.height }] },
          styles: { style: 'solid', size: 1, color: token('--text-dim') },
          ignoreEvent: true,
        },
      ]
    },
  })
}

/** 경계 하나의 이름표에 넘기는 값. `prev` 는 앞 세션이 시작한 봉(앞 경계, 없으면
 *  첫 봉), `next` 는 다음 경계의 봉입니다. 이름표가 들어갈 자리를 재는 데 쓰고,
 *  없으면 칸 끝까지가 자리입니다. */
export interface SessionLabelData {
  before: string | null
  after: string | null
  prev: number | null
  next: number | null
}

interface Box {
  left: number
  right: number
  top: number
  bottom: number
}

const overlaps = (a: Box, b: Box) =>
  a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom

/* 라이브러리가 보이는 구간의 최고가·최저가를 적는 글자 자리. 값이라 이름표보다
 * 앞섭니다 — 이름표가 이 자리를 덮으면 그 이름표를 뺍니다.
 *
 * 자리는 라이브러리가 그리는 방식 그대로 셉니다: 보이는 봉 가운데 처음 나온
 * 최고(최저) 봉에서, 값 자리 7px 바깥에 글자 가운데가 서고(글자 10), 봉에서
 * 10px 떨어져 칸의 가까운 쪽 반대로 뻗습니다. 봉에서 글자까지 이어진 꺾은선도
 * 덮지 않도록 봉 자리부터 칩니다. */
function priceMarkBoxes(chart: Chart, paneId: string, width: number): Box[] {
  const data = chart.getDataList()
  const range = chart.getVisibleRange()
  let high = -1
  let low = -1
  for (let i = Math.max(0, range.realFrom); i < Math.min(data.length, range.realTo); i += 1) {
    if (high === -1 || data[i].high > data[high].high) high = i
    if (low === -1 || data[i].low < data[low].low) low = i
  }
  if (high === -1 || low === -1) return []
  const precision = chart.getSymbol()?.pricePrecision ?? 2
  const at = (index: number, value: number) =>
    chart.convertToPixel({ timestamp: data[index].timestamp, value }, { paneId }) as {
      x?: number
      y?: number
    }
  const top = at(high, data[high].high)
  const bottom = at(low, data[low].low)
  if (top.y === undefined || bottom.y === undefined) return []
  /* 축이 뒤집혀 있으면 바깥 방향도 뒤집힙니다. */
  const upright = top.y < bottom.y
  const box = (x: number | undefined, y: number, value: number, outward: number): Box | null => {
    if (x === undefined || !Number.isFinite(x) || !Number.isFinite(y)) return null
    const text = utils.formatThousands(utils.formatPrecision(value, precision), ',')
    const textWidth = utils.calcTextWidth(text, PRICE_MARK_SIZE)
    const middle = y + outward * PRICE_MARK_OFFSET
    const toLeft = x > width / 2
    const far = toLeft ? x - PRICE_MARK_GAP - textWidth : x + PRICE_MARK_GAP + textWidth
    return {
      left: Math.min(x, far),
      right: Math.max(x, far),
      top: Math.min(y, middle - PRICE_MARK_SIZE / 2),
      bottom: Math.max(y, middle + PRICE_MARK_SIZE / 2),
    }
  }
  return [
    box(top.x, top.y, data[high].high, upright ? -1 : 1),
    box(bottom.x, bottom.y, data[low].low, upright ? 1 : -1),
  ].filter((found): found is Box => found !== null)
}

/* 최고·최저가 표의 모양(라이브러리 기본). 글자 10, 값 자리에서 글자 가운데까지
 * 7, 봉에서 글자까지 10. */
const PRICE_MARK_SIZE = 10
const PRICE_MARK_OFFSET = 7
const PRICE_MARK_GAP = 10

/* 이름표의 모양. 글자 10, 여백 위아래 2·좌우 6, 모서리 4. */
const LABEL_SIZE = 10
const LABEL_PAD_X = 6
const LABEL_PAD_Y = 2
/* 선과 이름표 사이, 봉 칸 아래 끝과 이름표 사이. */
const LABEL_GAP = 4
const LABEL_BOTTOM = 6

let labelRegistered = false

/** 경계 이름표를 라이브러리에 등록합니다. 한 번만 돕니다. 봉 칸에만 답니다. */
export function ensureSessionLabelOverlay(): void {
  if (labelRegistered) return
  labelRegistered = true
  registerOverlay({
    name: 'sessionLabel',
    totalStep: 1,
    lock: true,
    needDefaultPointFigure: false,
    needDefaultXAxisFigure: false,
    needDefaultYAxisFigure: false,
    createPointFigures: ({ chart, overlay, coordinates, bounding }) => {
      if (coordinates.length < 1) return []
      const data = overlay.extendData as SessionLabelData | undefined
      if (!data) return []
      /* 선과 같은 자리 셈입니다. 확대·이동 때마다 다시 그려지므로 이웃 경계의
         자리도 그때마다 다시 잽니다. */
      const half = chart.getBarSpace().bar / 2
      const x = coordinates[0].x - half
      const xOf = (timestamp: number | null, fallback: number): number => {
        if (timestamp === null) return fallback
        const at = (chart.convertToPixel({ timestamp }, { paneId: overlay.paneId }) as { x?: number }).x
        return typeof at === 'number' && Number.isFinite(at) ? at - half : fallback
      }
      const left = Math.max(0, xOf(data.prev, 0))
      /* 다음 경계가 화면 오른쪽 밖이면 자리는 칸 끝까지입니다. */
      const right = Math.min(bounding.width, xOf(data.next, bounding.width))
      const marks = priceMarkBoxes(chart, overlay.paneId, bounding.width)
      const y = bounding.height - LABEL_BOTTOM
      const height = LABEL_SIZE + LABEL_PAD_Y * 2
      /* 최고·최저가 표를 덮으면 그 이름표만 뺍니다. 옮기지 않습니다 — 그 표는 늘
         가장 높거나 낮은 봉 곁이라, 옮긴 이름표가 봉을 덮기 쉽습니다. 현재가
         점선은 선이라 덮어도 값이 읽힙니다. */
      const clear = (from: number, to: number) =>
        !marks.some((mark) => overlaps({ left: from, right: to, top: y - height, bottom: y }, mark))
      const styles = {
        color: token('--text-label'),
        size: LABEL_SIZE,
        backgroundColor: token('--surface-muted'),
        paddingLeft: LABEL_PAD_X,
        paddingRight: LABEL_PAD_X,
        paddingTop: LABEL_PAD_Y,
        paddingBottom: LABEL_PAD_Y,
        borderRadius: 4,
        borderSize: 0,
      }
      const widthOf = (text: string) => utils.calcTextWidth(text, LABEL_SIZE) + LABEL_PAD_X * 2
      const figures = []
      /* 자리가 이름표 폭 + 선과의 틈보다 좁으면 그쪽만 뺍니다 — 이웃 경계를
         넘어가면 이름표가 다른 세션 위에 앉습니다. */
      if (
        data.before &&
        x - left >= widthOf(data.before) + LABEL_GAP &&
        clear(x - LABEL_GAP - widthOf(data.before), x - LABEL_GAP)
      ) {
        figures.push({
          type: 'text',
          attrs: { x: x - LABEL_GAP, y, text: data.before, align: 'right', baseline: 'bottom' },
          styles,
          ignoreEvent: true,
        })
      }
      if (
        data.after &&
        right - x >= widthOf(data.after) + LABEL_GAP &&
        clear(x + LABEL_GAP, x + LABEL_GAP + widthOf(data.after))
      ) {
        figures.push({
          type: 'text',
          attrs: { x: x + LABEL_GAP, y, text: data.after, align: 'left', baseline: 'bottom' },
          styles,
          ignoreEvent: true,
        })
      }
      return figures
    },
  })
}
