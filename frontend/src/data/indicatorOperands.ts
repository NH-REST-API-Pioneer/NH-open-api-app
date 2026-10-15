import { indicatorDef } from '../screens/trade/chartIndicators'

/* 매개변수를 받는 지표 피연산자 — 이름·기본값·받는 범위·열 이름·옛 이름 옮기기.
 *
 * **조건 편집기·요약 문장·조건 표·체결 당시 값·검증 차트가 모두 이 한 벌을
 * 씁니다.** 자리마다 따로 두면 같은 조건이 화면마다 다른 이름이나 다른 기간으로
 * 섭니다.
 *
 * 매개변수 이름과 기본값은 서버 규칙 모듈(`PARAM_SPECS`)과 같은 글자이고, 기본값과
 * 칸 이름은 차트 지표 정의(`trade/chartIndicators.ts`)에서 가져옵니다 — 조건의
 * EMA(20)과 차트의 EMA(20)이 같은 선이어야 합니다. 차트가 선마다 기간을 받는
 * 지표(EMA·MA·RSI)와 차트에 없는 ATR 은 칸 이름이 「기간」입니다.
 */

/** 매개변수 하나. `key` 는 서버가 받는 이름입니다. */
export interface ParamSpec {
  key: string
  /** 칸 앞에 서는 짧은 이름. */
  label: string
  value: number
}

/** 차트 정의의 n번째 수치(이름·기본값). 정의가 없으면 받은 값을 씁니다. */
function chartParam(name: string, index: number, key: string, fallback: ParamSpec): ParamSpec {
  const found = indicatorDef(name)?.params[index]
  return found ? { key, label: found.label, value: found.value } : fallback
}

const PERIOD = (value: number): ParamSpec[] => [{ key: 'period', label: '기간', value }]
const BOLLINGER: ParamSpec[] = [
  chartParam('BOLL', 0, 'period', { key: 'period', label: '기간', value: 20 }),
  chartParam('BOLL', 1, 'multiplier', { key: 'multiplier', label: '배수', value: 2 }),
]
const MACD: ParamSpec[] = [
  chartParam('MACD', 0, 'fast', { key: 'fast', label: '단기', value: 12 }),
  chartParam('MACD', 1, 'slow', { key: 'slow', label: '장기', value: 26 }),
  chartParam('MACD', 2, 'signal', { key: 'signal', label: '신호', value: 9 }),
]
const STOCH: ParamSpec[] = [
  chartParam('KDJ', 0, 'period', { key: 'period', label: '기간', value: 9 }),
  chartParam('KDJ', 1, 'k', { key: 'k', label: 'K', value: 3 }),
  chartParam('KDJ', 2, 'd', { key: 'd', label: 'D', value: 3 }),
]

export const MACD_IDS = ['macdLine', 'macdSignal', 'macdHist']
export const STOCH_IDS = ['stochK', 'stochD']
export const BOLLINGER_IDS = ['bbUpper', 'bbMiddle', 'bbLower']

/** 매개변수를 받는 지표와 그 매개변수. 차례가 열 이름(「macdLine(12,26,9)」)의 차례입니다. */
export const PARAM_SPECS: Record<string, ParamSpec[]> = {
  ema: PERIOD(20),
  ma: PERIOD(20),
  rsi: PERIOD(14),
  atr: PERIOD(14),
  ...Object.fromEntries(BOLLINGER_IDS.map((id) => [id, BOLLINGER])),
  ...Object.fromEntries(MACD_IDS.map((id) => [id, MACD])),
  ...Object.fromEntries(STOCH_IDS.map((id) => [id, STOCH])),
}

/** 소수를 받는 매개변수. 나머지는 정수입니다. */
const FLOAT_PARAMS = new Set(['multiplier'])

/** 매개변수마다 받는 범위와 틀렸을 때의 문장. **서버 판정과 같은 범위·같은 글자**입니다. */
const RANGES: Record<string, { low: number; high: number; whole: boolean; why: string }> = {
  period: { low: 2, high: 200, whole: true, why: '기간은 2~200 사이 정수로 적습니다' },
  fast: { low: 2, high: 200, whole: true, why: '기간은 2~200 사이 정수로 적습니다' },
  slow: { low: 2, high: 200, whole: true, why: '기간은 2~200 사이 정수로 적습니다' },
  signal: { low: 2, high: 200, whole: true, why: '기간은 2~200 사이 정수로 적습니다' },
  multiplier: { low: 0.5, high: 5, whole: false, why: '배수는 0.5~5 사이, 소수 한 자리까지 적습니다' },
  k: { low: 1, high: 50, whole: true, why: '평활은 1~50 사이 정수로 적습니다' },
  d: { low: 1, high: 50, whole: true, why: '평활은 1~50 사이 정수로 적습니다' },
}

export const FAST_SLOW_WHY = '단기는 장기보다 짧게 적습니다'
export const SHARED_PARAMS_WHY = 'MACD·스토캐스틱끼리 견줄 때는 같은 설정이어야 합니다'
export const SAME_CROSS_WHY = '같은 값끼리는 교차할 수 없습니다'
export const CROSS_SIDES_WHY = '교차는 가격이나 선이 선을 지날 때 씁니다'

/** 조건에 적히는 매개변수. 치는 중인 글자(「0.」)는 수가 아니라 글자로 남습니다. */
export type Params = Record<string, number | string>

export function hasParams(id: string): boolean {
  return id in PARAM_SPECS
}

/** 매개변수 묶음을 함께 쓰는 지표들(MACD 셋·스토캐스틱 둘). 아니면 `null`. */
export function sharedGroupOf(id: string): string[] | null {
  if (MACD_IDS.includes(id)) return MACD_IDS
  if (STOCH_IDS.includes(id)) return STOCH_IDS
  return null
}

/** 기본 매개변수. 매개변수가 없는 값이면 `undefined` 입니다. */
export function defaultParams(id: string): Record<string, number> | undefined {
  const spec = PARAM_SPECS[id]
  return spec ? Object.fromEntries(spec.map((one) => [one.key, one.value])) : undefined
}

/* ── 옛 이름 ─────────────────────────────────────────── */

/** 매개변수가 생기기 전의 이름(`ema20` 등) → `{id, params}`. **서버가 목록 답에
 *  실어 보내는 표 하나**(`legacyOperands`)이고 화면은 따로 두지 않습니다. 목록을
 *  받기 전에는 비어 있습니다. */
let legacy: Record<string, { id: string; params: Record<string, number> }> = {}

export function setLegacyOperands(table: unknown): void {
  if (!table || typeof table !== 'object') return
  const made: typeof legacy = {}
  for (const [old, value] of Object.entries(table as Record<string, unknown>)) {
    const item = value as { id?: unknown; params?: unknown }
    if (typeof item?.id !== 'string' || !item.params || typeof item.params !== 'object') continue
    const params: Record<string, number> = {}
    for (const [key, number] of Object.entries(item.params as Record<string, unknown>)) {
      if (typeof number === 'number' && Number.isFinite(number)) params[key] = number
    }
    made[old] = { id: item.id, params }
  }
  legacy = made
}

export function isLegacyOperand(id: string): boolean {
  return id in legacy
}

/** 피연산자 하나를 `(지표 id, 매개변수)` 로 풉니다 — 서버 `resolve` 와 같은 규칙.
 *  옛 이름은 늘 옮기고, 함께 적힌 매개변수가 있으면 그 값이 덮습니다. 매개변수를
 *  받는 지표는 안 적은 매개변수를 기본값으로 채웁니다. */
export function resolveOperand(
  id: string,
  params?: Params | null,
): { id: string; params: Params | undefined } {
  const found = legacy[id]
  const name = found ? found.id : id
  const given = { ...(found?.params ?? {}), ...(params ?? {}) }
  const spec = PARAM_SPECS[name]
  if (!spec) return { id: name, params: undefined }
  const made: Params = {}
  for (const one of spec) made[one.key] = given[one.key] ?? one.value
  return { id: name, params: made }
}

/** 매개변수를 열 이름·화면에 적는 글자. `2.0` 은 `2`, `2.5` 는 `2.5` 입니다. */
function numberText(value: number | string): string {
  return String(value)
}

/** 값 열의 이름 — 서버 `operand_key` 와 같은 글자(「ema(20)」·「bbUpper(20,2)」).
 *  체결 줄의 당시 값이 이 이름으로 옵니다. */
export function operandKey(id: string, params?: Params | null): string {
  const resolved = resolveOperand(id, params)
  const spec = PARAM_SPECS[resolved.id]
  if (!spec || !resolved.params) return resolved.id
  return `${resolved.id}(${spec.map((one) => numberText(resolved.params![one.key])).join(',')})`
}

/** 열 이름을 `{id, params}` 로 되읽습니다. 옛 이름(`ema20`)도 받습니다. */
export function parseOperandKey(key: string): { id: string; params: Params | undefined } {
  const found = /^([A-Za-z0-9]+)\(([^)]*)\)$/.exec(key)
  if (!found) return resolveOperand(key)
  const spec = PARAM_SPECS[found[1]]
  if (!spec) return { id: key, params: undefined }
  const parts = found[2].split(',')
  const params: Params = {}
  spec.forEach((one, index) => {
    const number = Number(parts[index])
    params[one.key] = Number.isFinite(number) ? number : one.value
  })
  return { id: found[1], params }
}

/* ── 이름 ────────────────────────────────────────────── */

/** 지표의 이름(매개변수 없이). 셀렉트에 서는 말이고, 매개변수는 뒤 칸이 받습니다. */
export const INDICATOR_NAMES: Record<string, string> = {
  ema: 'EMA',
  ma: 'MA',
  rsi: 'RSI',
  atr: 'ATR',
  bbUpper: '볼린저 상단',
  bbMiddle: '볼린저 중심',
  bbLower: '볼린저 하단',
  vwap: 'VWAP(세션)',
  macdLine: 'MACD 선(DIF)',
  macdSignal: 'MACD 신호(DEA)',
  macdHist: 'MACD 막대(DIF − DEA)',
  stochK: '스토캐스틱 %K',
  stochD: '스토캐스틱 %D',
}

/** 매개변수까지 적은 이름 — 「EMA(20)」·「볼린저 상단(20, 2)」·「스토캐스틱 %K(9, 3, 3)」.
 *  **기본값이어도 적습니다.** 이름 끝이 이미 괄호인 지표(「MACD 선(DIF)」)는 그
 *  괄호 안에 매개변수를 잇습니다 — 「MACD 선(DIF, 12, 26, 9)」. */
export function indicatorWord(id: string, params?: Params | null): string | null {
  const resolved = resolveOperand(id, params)
  const name = INDICATOR_NAMES[resolved.id]
  if (!name) return null
  const spec = PARAM_SPECS[resolved.id]
  if (!spec || !resolved.params) return name
  const list = spec.map((one) => numberText(resolved.params![one.key])).join(', ')
  return name.endsWith(')') ? `${name.slice(0, -1)}, ${list})` : `${name}(${list})`
}

/* ── 판정 ────────────────────────────────────────────── */

/** 매개변수 한 칸이 못 받는 값이면 그 까닭. 받으면 `null` 입니다. */
export function paramWhy(key: string, value: number | string | undefined): string | null {
  const range = RANGES[key]
  if (!range) return null
  const number = typeof value === 'number' ? value : Number(String(value ?? '').trim())
  const text = typeof value === 'string' ? value.trim() : ''
  if ((typeof value === 'string' && text === '') || !Number.isFinite(number)) return range.why
  if (number < range.low || number > range.high) return range.why
  if (range.whole && !Number.isInteger(number)) return range.why
  if (!range.whole && Math.round(number * 10) / 10 !== number) return range.why
  return null
}

/** 그 쪽(왼쪽·오른쪽) 매개변수 가운데 못 받는 칸들. 단기 ≥ 장기면 단기 칸입니다. */
export function sideParamProblems(id: string, params?: Params | null): { key: string; why: string }[] {
  const resolved = resolveOperand(id, params)
  const spec = PARAM_SPECS[resolved.id]
  if (!spec || !resolved.params) return []
  const found = spec.flatMap((one) => {
    const why = paramWhy(one.key, resolved.params![one.key])
    return why ? [{ key: one.key, why }] : []
  })
  if (found.length === 0 && MACD_IDS.includes(resolved.id)) {
    if (Number(resolved.params.fast) >= Number(resolved.params.slow)) return [{ key: 'fast', why: FAST_SLOW_WHY }]
  }
  return found
}

/** 소수 칸인지. 칸의 입력 모드를 고르는 데 씁니다. */
export function isFloatParam(key: string): boolean {
  return FLOAT_PARAMS.has(key)
}

/* ── 교차 ────────────────────────────────────────────── */

/** 가격과 같은 축의 선. **가격 묶음 교차의 오른쪽은 이 선들뿐입니다.** 앞의 다섯은
 *  매개변수가 생기기 전의 이름입니다. 서버 `CROSS_LINE_IDS` 와 같습니다. */
export const CROSS_LINE_IDS = ['ema20', 'ema50', 'ma20', 'bbUpper', 'bbLower', 'ema', 'ma', 'bbMiddle', 'vwap']
/** 가격 묶음 교차의 왼쪽. 선에 가격 넷을 더합니다. */
export const CROSS_LEFT_IDS = [...CROSS_LINE_IDS, 'close', 'open', 'high', 'low']
/** 가격 축이 아닌 지표끼리 교차할 수 있는 짝. 같은 묶음 안에서만 교차가 섭니다. */
export const OSCILLATOR_CROSSES: string[][] = [['rsi'], STOCH_IDS, ['macdLine', 'macdSignal']]

/** 교차의 왼쪽이 이것일 때 오른쪽에 세울 수 있는 값들. 서지 않는 왼쪽이면 빈 목록입니다. */
export function crossRightIds(left: string): string[] {
  if (CROSS_LEFT_IDS.includes(left)) return CROSS_LINE_IDS
  const name = resolveOperand(left).id
  const group = OSCILLATOR_CROSSES.find((one) => one.includes(name))
  return group ?? []
}

/** 교차가 서는 짝인지 — 서버 `_cross_pair` 와 같은 규칙. */
export function crossPair(left: string, right: string): boolean {
  if (CROSS_LEFT_IDS.includes(left) && CROSS_LINE_IDS.includes(right)) return true
  const names = [resolveOperand(left).id, resolveOperand(right).id]
  return OSCILLATOR_CROSSES.some((group) => names.every((name) => group.includes(name)))
}
