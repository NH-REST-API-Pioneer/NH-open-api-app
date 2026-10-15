/* 차트 지표의 목록과 설정.
 *
 * 계산은 라이브러리가 합니다. 여기에는 「무엇을 보여 줄지」만 있습니다 —
 * 어떤 지표가 있고, 어느 칸에 서고, 어떤 수치를 받고, 선이 몇 개인지.
 *
 * 설정은 지표마다 「켜짐 · 수치 · 선 스타일」 셋입니다. 선 스타일은 색과
 * 굵기뿐이고, 색은 정해진 팔레트에서만 고릅니다 — 자유 색을 열면 봉 색과
 * 같은 빨강·파랑을 골라 선이 봉에 묻히는 일이 생깁니다.
 */

export type IndicatorGroup = 'top' | 'bottom'

export interface ParamSpec {
  label: string
  value: number
  /** 정수만 받는지. 볼린저 배수처럼 소수가 되는 값만 false 입니다. */
  integer?: boolean
}

export interface IndicatorDef {
  /** 라이브러리의 지표 이름. 이 이름으로 만들고 고칩니다. */
  name: string
  label: string
  description: string
  group: IndicatorGroup
  /** 고정 수치. 선마다 기간을 받는 지표(`linePeriods`)는 비어 있습니다. */
  params: ParamSpec[]
  /** 수치가 곧 선의 기간이라 선을 더하고 뺄 수 있는 지표. */
  linePeriods?: { defaults: number[]; max: number }
  /** 고정 선의 이름. 선마다 기간을 받는 지표는 기간이 이름입니다. */
  lines: string[]
  /** 선이 아닌 그림(막대·점)의 이름. 범례에 값만 적습니다. */
  extras?: string[]
}

/* 위 칸(봉 위에 겹침) 지표. 라이브러리가 `series: 'price'` 로 두는 것들입니다. */
const TOP: IndicatorDef[] = [
  {
    name: 'MA',
    label: '이동평균선',
    description: '지난 n봉 종가의 평균을 이은 선',
    group: 'top',
    params: [],
    linePeriods: { defaults: [5, 20, 60, 120], max: 8 },
    lines: [],
  },
  {
    name: 'EMA',
    label: '지수이동평균',
    description: '최근 봉에 무게를 더 둔 이동평균',
    group: 'top',
    params: [],
    linePeriods: { defaults: [6, 12, 20], max: 8 },
    lines: [],
  },
  {
    name: 'BOLL',
    label: '볼린저 밴드',
    description: '이동평균에서 표준편차의 n배만큼 떨어진 위아래 띠',
    group: 'top',
    params: [
      { label: '기간', value: 20 },
      { label: '배수', value: 2, integer: false },
    ],
    lines: ['상단', '중심', '하단'],
  },
  {
    name: 'SAR',
    label: '파라볼릭 SAR',
    description: '추세가 뒤집히는 자리를 점으로 찍는 지표',
    group: 'top',
    params: [
      { label: '시작 가속', value: 2 },
      { label: '가속 증분', value: 2 },
      { label: '최대 가속', value: 20 },
    ],
    lines: [],
    extras: ['SAR'],
  },
  {
    name: 'BBI',
    label: 'BBI',
    description: '기간이 다른 이동평균 넷의 평균',
    group: 'top',
    params: [
      { label: '기간1', value: 3 },
      { label: '기간2', value: 6 },
      { label: '기간3', value: 12 },
      { label: '기간4', value: 24 },
    ],
    lines: ['BBI'],
  },
]

/* 아래 칸(제 축을 가짐) 지표. */
const BOTTOM: IndicatorDef[] = [
  {
    name: 'VOL',
    label: '거래량',
    description: '봉마다의 거래량 막대와 그 이동평균',
    group: 'bottom',
    params: [],
    linePeriods: { defaults: [5, 10, 20], max: 4 },
    lines: [],
    extras: ['거래량'],
  },
  {
    name: 'MACD',
    label: 'MACD',
    description: '단기·장기 지수이동평균의 차이와 그 신호선',
    group: 'bottom',
    params: [
      { label: '단기', value: 12 },
      { label: '장기', value: 26 },
      { label: '신호', value: 9 },
    ],
    lines: ['DIF', 'DEA'],
    extras: ['MACD'],
  },
  {
    name: 'RSI',
    label: 'RSI',
    description: '지난 n봉 동안 오른 힘과 내린 힘의 비율',
    group: 'bottom',
    params: [],
    linePeriods: { defaults: [6, 12, 24], max: 4 },
    lines: [],
  },
  {
    name: 'KDJ',
    label: '스토캐스틱',
    description: '지난 n봉의 고저 범위 안에서 종가가 어디쯤인지',
    group: 'bottom',
    params: [
      { label: '기간', value: 9 },
      { label: 'K', value: 3 },
      { label: 'D', value: 3 },
    ],
    lines: ['K', 'D', 'J'],
  },
  {
    name: 'CCI',
    label: 'CCI',
    description: '평균 가격에서 얼마나 벗어났는지',
    group: 'bottom',
    params: [{ label: '기간', value: 20 }],
    lines: ['CCI'],
  },
  {
    name: 'WR',
    label: '윌리엄스 %R',
    description: '지난 n봉의 고점에서 종가까지의 거리',
    group: 'bottom',
    params: [],
    linePeriods: { defaults: [6, 10, 14], max: 4 },
    lines: [],
  },
  {
    name: 'DMI',
    label: 'DMI',
    description: '오르는 힘과 내리는 힘, 그리고 추세의 세기',
    group: 'bottom',
    params: [
      { label: '기간', value: 14 },
      { label: 'ADX 기간', value: 6 },
    ],
    lines: ['+DI', '−DI', 'ADX', 'ADXR'],
  },
  {
    name: 'OBV',
    label: 'OBV',
    description: '오른 날의 거래량은 더하고 내린 날은 빼서 쌓은 값',
    group: 'bottom',
    params: [{ label: '기간', value: 30 }],
    lines: ['OBV', '이동평균'],
  },
]

export const INDICATOR_DEFS: IndicatorDef[] = [...TOP, ...BOTTOM]

export function indicatorDef(name: string): IndicatorDef | undefined {
  return INDICATOR_DEFS.find((def) => def.name === name)
}

/* ── 팔레트 ───────────────────────────────────────────── */

/* 색상 8 × 명도 4. 한 줄이 한 색상이고 왼쪽이 진합니다.
 *
 * 빨강과 파랑은 없습니다 — 봉과 매수·매도 상태색이 그 둘이라, 선에 쓰면
 * 얇은 선이 봉과 구분되지 않습니다. 장미색과 코발트는 있어도 그 값과는
 * 다릅니다.
 *
 * 세 번째 열은 이 앱이 처음부터 이동평균에 쓰던 네 색(주황·보라·초록·회색)을
 * 그대로 품습니다. 설정을 한 번도 안 만진 사용자에게 선 색이 바뀌어 보이면
 * 안 됩니다. */
export const PALETTE: string[][] = [
  ['#3b4250', '#5b6472', '#7a828c', '#a9b0ba'],
  ['#1b4f9e', '#2b6fc4', '#4c8fe0', '#8ab8ee'],
  ['#4b2fa0', '#6a48c4', '#7b5cd6', '#a99bea'],
  ['#9c1f3c', '#c72d55', '#e2557a', '#f0a0b6'],
  ['#a35b0a', '#c9741a', '#e8901a', '#f4bd6e'],
  ['#8c7a10', '#b39b17', '#d9bd2a', '#ecd97f'],
  ['#0f6b6b', '#148c8c', '#2aa9a9', '#82cfcf'],
  ['#0b6b34', '#12a150', '#3dbb70', '#8fd9ab'],
]

/* 새 선이 색을 받는 순서. 앞쪽일수록 눈에 띕니다 — 이동평균은 짧은 기간이
 * 앞에 오므로 자주 보는 선이 제일 튀는 색을 받습니다. */
const COLOR_ORDER = [
  PALETTE[4][2],
  PALETTE[2][2],
  PALETTE[7][1],
  PALETTE[0][2],
  PALETTE[1][2],
  PALETTE[6][2],
  PALETTE[3][2],
  PALETTE[5][2],
]

export const LINE_SIZES = [1, 2, 3, 4]
export const DEFAULT_LINE_SIZE = 2

/** 이미 쓰고 있는 색과 겹치지 않는 다음 색. 다 썼으면 같은 색상의 옅은 칸으로 갑니다. */
export function nextColor(used: string[]): string {
  const free = COLOR_ORDER.find((color) => !used.includes(color))
  if (free) return free
  for (const shade of [1, 3, 0]) {
    const alt = PALETTE.map((row) => row[shade]).find((color) => !used.includes(color))
    if (alt) return alt
  }
  return COLOR_ORDER[used.length % COLOR_ORDER.length]
}

/* ── 설정 ─────────────────────────────────────────────── */

export interface LineStyle {
  color: string
  size: number
}

export interface IndicatorSetting {
  on: boolean
  /** 켜 두되 잠시 안 보이게 한 상태. 범례의 눈 단추가 바꿉니다. */
  hidden?: boolean
  params: number[]
  lines: LineStyle[]
}

export type IndicatorSettings = Record<string, IndicatorSetting>

export const SETTINGS_KEY = 'nh.trade.indicators'

/** 처음 켜는 지표의 기본 설정. */
export function defaultSetting(def: IndicatorDef, on = false): IndicatorSetting {
  const params = def.linePeriods ? [...def.linePeriods.defaults] : def.params.map((p) => p.value)
  const count = def.linePeriods ? params.length : def.lines.length
  const lines: LineStyle[] = []
  for (let i = 0; i < count; i += 1) {
    lines.push({ color: nextColor(lines.map((line) => line.color)), size: DEFAULT_LINE_SIZE })
  }
  return { on, params, lines }
}

/** 지표별 기본 설정 전체. 처음 열면 이동평균과 거래량만 켜져 있습니다. */
export function defaultSettings(): IndicatorSettings {
  const out: IndicatorSettings = {}
  for (const def of INDICATOR_DEFS) out[def.name] = defaultSetting(def, def.name === 'MA' || def.name === 'VOL')
  return out
}

/* 저장된 값은 예전 버전이 남긴 것일 수 있습니다. 지표가 늘거나 선 수가
 * 어긋나 있으면 그 지표만 기본으로 되돌립니다 — 하나가 깨졌다고 전부를
 * 버리면 사용자가 고른 색이 다 날아갑니다. */
export function normalizeSettings(raw: unknown): IndicatorSettings {
  const base = defaultSettings()
  if (!raw || typeof raw !== 'object') return base
  const input = raw as Record<string, Partial<IndicatorSetting>>
  for (const def of INDICATOR_DEFS) {
    const item = input[def.name]
    if (!item || typeof item !== 'object') continue
    const params = Array.isArray(item.params) ? item.params.filter(validParam) : null
    const lines = Array.isArray(item.lines)
      ? item.lines.filter(
          (line): line is LineStyle =>
            typeof line?.color === 'string' && LINE_SIZES.includes(Number(line?.size)),
        )
      : null
    if (!params || !lines) continue
    const expectedLines = def.linePeriods ? params.length : def.lines.length
    if (def.linePeriods) {
      if (params.length < 1 || params.length > def.linePeriods.max) continue
    } else if (params.length !== def.params.length) continue
    if (lines.length !== expectedLines) continue
    base[def.name] = { on: item.on === true, hidden: item.hidden === true, params, lines }
  }
  return base
}

/** 수치 하나가 받아들여지는지. 0·음수·숫자가 아닌 것은 거부합니다. */
export function validParam(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0
}

/* ── 라이브러리에 넘길 모양 ───────────────────────────── */

/** 설정을 라이브러리의 지표 스타일로 옮깁니다. */
export function lineStyles(setting: IndicatorSetting) {
  return setting.lines.map((line) => ({
    color: line.color,
    size: line.size,
    style: 'solid' as const,
    smooth: false,
    dashedValue: [2, 2],
  }))
}
