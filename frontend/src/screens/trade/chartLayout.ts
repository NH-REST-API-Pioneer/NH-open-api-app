import type { Chart, PaneOptions } from 'klinecharts'
import type { IndicatorSettings } from './chartIndicators'
import { allIndicatorDefs } from './extraIndicators'

/* 봉이 서는 칸과 시간 축 칸의 이름. 겹치는 지표는 봉 칸의 이름을 대고 만들어야
 * 봉 위에 얹힙니다 — 이름을 대지 않으면 제 칸을 새로 받습니다. */
export const CANDLE_PANE = 'candle_pane'
export const X_AXIS_PANE = 'x_axis_pane'

/* 봉 칸 위·아래 여백. 라이브러리는 1 보다 작으면 칸 높이에 대한 몫으로, 1
 * 이상이면 px 로 읽습니다. 위쪽은 범례 높이에 맞춰 재고(`headroomGap`), 못 잴
 * 때는 라이브러리 기본값입니다. */
export const DEFAULT_TOP_GAP = 0.2
export const BOTTOM_GAP = 0.1
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
export function headroomGap(
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
export const X_AXIS_HEIGHT = 26
/* 아래 칸 하나가 넘지 않는 높이. 넓은 창에서 아래 칸만 계속 커지면 봉이
 * 눌립니다 — 거래량은 모양만 보면 되고 값은 범례에 적힙니다.
 * 확대에서는 세로가 넉넉하므로 칸도 그만큼 키웁니다. */
const SUB_PANE_MAX = 96
const SUB_PANE_MAX_EXPANDED = 180
/* 라이브러리가 칸에 두는 기본 바닥. 칸 높이를 이보다 낮게 주려면 바닥도 같이
 * 내려야 합니다. 안 그러면 칸 셋이 자리를 넘겨 봉 칸이 0 이 됩니다. */
export const PANE_FLOOR = 30
/* 아래 칸 전부가 가져갈 수 있는 몫. 나머지는 봉이 갖습니다 — 봉이 이 화면의
 * 주인이라 어떤 크기에서도 절반은 넘게 둡니다. */
const SUB_PANE_SHARE = 0.45
/* 봉 칸이 이보다 낮아지지 않습니다. 낮은 창에서 아래 칸이 먼저 바닥까지 줄고,
 * 그래도 모자라면 카드가 세로로 스크롤합니다 — 봉이 0 높이가 되어 거래량만
 * 남는 차트는 차트가 아닙니다. */
export const CANDLE_MIN = 160

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
export function capBottom(
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

/* 아래 칸(거래량·MACD 등)의 높이를 지금 창에 맞춥니다.
 *
 * 라이브러리는 아래 칸에 100px 씩 고정으로 주고 남는 것을 봉에 줍니다. 그래서
 * 차트 자리가 좁은 창에서는 아래 칸이 자리를 다 먹고 봉 칸이 0 이 됩니다 —
 * 지표를 켰는데 봉이 사라지는 것으로 보입니다. */
export function fitPanes(chart: Chart, box: HTMLElement, expanded: boolean): void {
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
