/* 전략 설정의 값 판정 — 칸이 받을 수 있는 값인지와 그 까닭.
 *
 * **판정은 여기 한 곳입니다.** 설정 화면의 칸 아래 판정 줄·묶음 배지·저장
 * 막음과, 요약 문단(`ruleSummary.ts`)이 문장에서 뺄 값을 고르는 일이 모두 이
 * 함수들을 부릅니다. 자리마다 따로 판정하면 칸 아래는 붉은데 요약은 그 값을
 * 정한 값처럼 말하는 틈이 생깁니다.
 */
import {
  BOOK_PRICE_IDS,
  BOOK_QTY_IDS,
  CLOCK_ID,
  CONTEXT_IDS,
  exitUnitOf,
  INTEGER_IDS,
  needsPriceFor,
  operandOf,
  operatorOf,
  parseClock,
  PRICE_BASES,
  rightKindOf,
  TIME_IDS,
  type Aux,
  type Cond,
  type Rule,
} from './strategyRules'
import {
  CROSS_SIDES_WHY,
  crossPair,
  operandKey,
  resolveOperand,
  SAME_CROSS_WHY,
  SHARED_PARAMS_WHY,
  sharedGroupOf,
  sideParamProblems,
} from './indicatorOperands'

/** 수 칸이 받을 수 없는 값이면 그 까닭. 받을 수 있으면 `null` 입니다.
 *
 *  틱·계약 칸은 1 이상의 정수, 돈 칸은 0 보다 큰 수입니다. 빈 칸·0·음수·글자는
 *  다 못 받습니다 — 0 계약은 안 나가는 주문이고 「abc틱」은 손절이 아닙니다.
 *  까닭은 **어떻게 적어야 하는지**로 말합니다(주문 화면의 가격 칸과 같은 말투).
 *  칸이 왜 틀렸는지 갈래마다 다르게 적으면 읽는 사람이 자기 값이 어느
 *  갈래인지 먼저 따져야 합니다. */
export function numberWhy(value: string, integer: boolean, optional = false): string | null {
  const text = value.trim()
  /* **비워 둘 수 있는 칸**(익절·추적 청산·연속 손실·되돌리기)은 빈 칸이 「쓰지
     않음」입니다. 적었다면 다른 칸과 같은 규칙이라 0 은 받지 않습니다. */
  if (optional && text === '') return null
  const number = Number(text)
  const ok = text !== '' && number > 0 && (!integer || Number.isInteger(number))
  if (ok) return null
  return integer ? '1 이상의 정수로 적습니다' : '0보다 큰 수로 적습니다'
}

/** 계좌 손실 한도 칸의 판정 문장. 서버가 같은 문장으로 거절합니다. */
export const WHY_LIMIT = '하루 손실 한도는 0보다 큰 수로 적거나 비워 둡니다'

/** 계좌 손실 한도 칸 하나. 쉼표를 걷고 **비었으면 통과**(안 걸음)이고, 적었다면
 *  0보다 큰 **유한한 십진수**만 받습니다 — 지수 표기·무한·숫자 아님은 거절합니다. */
export function limitWhy(text: string): string | null {
  const body = text.trim().replace(/,/g, '')
  if (body === '') return null
  return /^\d+(\.\d+)?$/.test(body) && Number(body) > 0 ? null : WHY_LIMIT
}

/** 판정을 지난 칸의 값. 빈 칸은 `null`(안 걸음)입니다. */
export function limitValue(text: string): number | null {
  const body = text.trim().replace(/,/g, '')
  return body === '' ? null : Number(body)
}

/** 실행을 세우는 폼의 세 칸 판정. **진행·검증 두 폼이 이 하나를 씁니다** — 폼마다
 *  따로 판정하면 한쪽에서 통과한 값이 다른 쪽에서 막힙니다.
 *
 *  수량은 1 이상 정수, 실행 자금은 0보다 큰 수입니다(보조 설정 칸과 같은 문장).
 *  수수료는 **0 을 받습니다** — 비용 없이 셈해 보는 것도 쓰임이 있습니다. 틀린
 *  값을 조용히 1·0 으로 바꿔 보내지 않고, 칸 아래 이 문장과 함께 시작을 막습니다. */
export function runAddWhy(input: { qty: string; cash: string; fee: string }): {
  qty: string | null
  cash: string | null
  fee: string | null
} {
  const fee = input.fee.trim()
  const feeNumber = Number(fee)
  return {
    qty: numberWhy(input.qty, true),
    cash: numberWhy(input.cash, false),
    fee: fee !== '' && Number.isFinite(feeNumber) && feeNumber >= 0 ? null : '0 이상으로 적습니다',
  }
}

/** 보조 설정의 수 칸과 그 칸이 받는 값. **칸 아래 판정 줄·접힌 묶음의 배지·
 *  저장 막음·요약 문단이 모두 이 표 하나로 판정합니다**(`auxWhy`) — 자리마다 따로
 *  판정하면 칸 아래는 붉은데 요약은 그 값을 정한 값처럼 말하는 틈이 생깁니다.
 *  `optional` 은 비워 두면 「쓰지 않음」인 칸입니다. */
export const AUX_NUMBERS = {
  stopTicks: { integer: true, optional: false },
  takeTicks: { integer: true, optional: true },
  trailTicks: { integer: true, optional: true },
  perOrder: { integer: true, optional: false },
  maxHold: { integer: true, optional: false },
  dailyLoss: { integer: false, optional: false },
  marginBudget: { integer: false, optional: false },
  lossStreak: { integer: true, optional: true },
} as const

export type AuxNumber = keyof typeof AUX_NUMBERS

/** 손절·익절·추적 청산의 값 칸과 그 단위 칸. */
export const EXIT_FIELDS = {
  stopTicks: 'stopUnit',
  takeTicks: 'takeUnit',
  trailTicks: 'trailUnit',
} as const

export const UNIT_WHY = '단위를 고르세요'

export const FILTER_FIELDS: readonly AuxFilter[] = [
  'sessionEndMinutes',
  'entryStart',
  'entryEnd',
  'reentryWaitBars',
  'maxEntriesPerDay',
]
const TICK_RANGE_WHY = '틱은 1~1000 사이 정수로 적습니다'
const PCT_WHY = '%는 0.1~50 사이, 소수 한 자리까지 적습니다'
const ATR_WHY = 'ATR 배수는 0.5~10 사이, 소수 한 자리까지 적습니다'

/** `low`~`high` 안이고 소수 `places` 자리까지인지. */
function inRange(text: string, low: number, high: number, places: number): boolean {
  const number = Number(text)
  const scale = 10 ** places
  return text !== '' && Number.isFinite(number) && number >= low && number <= high && Math.round(number * scale) / scale === number
}

/** 거리 칸 하나의 판정. **단위마다 받는 수가 다릅니다**(서버와 같은 범위·같은 글자) —
 *  틱은 1~1000 정수, 가격은 0보다 큰 수, % 는 0.1~50 소수 한 자리, ATR 배는 0.5~10
 *  소수 한 자리입니다. 익절·추적 청산은 비워 두면 쓰지 않는 것입니다. */
function exitWhy(aux: Aux, key: keyof typeof EXIT_FIELDS): string | null {
  const unit = exitUnitOf(aux[EXIT_FIELDS[key]])
  const text = (aux[key] ?? '').trim()
  const optional = AUX_NUMBERS[key].optional
  if (optional && text === '') return null
  if (unit === 'tick') {
    const why = numberWhy(text, true, optional)
    if (why) return why
    return Number(text) > 1000 ? TICK_RANGE_WHY : null
  }
  if (unit === 'price') return numberWhy(text, false, optional)
  if (unit === 'pct') return inRange(text, 0.1, 50, 1) ? null : PCT_WHY
  if (unit === 'atr') return inRange(text, 0.5, 10, 1) ? null : ATR_WHY
  return UNIT_WHY
}

/** 보조 수 칸 하나의 판정. 받으면 `null` 입니다. 손절·익절·추적 청산은 그 단위의
 *  범위로 봅니다. */
export function auxWhy(aux: Aux, key: AuxNumber): string | null {
  if (key in EXIT_FIELDS) return exitWhy(aux, key as keyof typeof EXIT_FIELDS)
  const rule = AUX_NUMBERS[key]
  return numberWhy(aux[key] ?? '', rule.integer, rule.optional)
}

/* ── 세션 끝 정리·신규 진입 시간·청산 뒤 대기·하루 최대 진입 ── */

/** 비워 둘 수 있는 실행 조건 칸. **서버와 같은 범위·같은 글자**입니다. */
export type AuxFilter = 'sessionEndMinutes' | 'entryStart' | 'entryEnd' | 'reentryWaitBars' | 'maxEntriesPerDay'

const SESSION_END_WHY = '세션 끝 정리는 1~60분 사이 정수로 적습니다'
const CLOCK_WHY = '시각은 HH:MM(00:00~23:59)으로 적습니다'
const WINDOW_SAME_WHY = '신규 진입 시간의 시작과 끝이 같습니다'
const WAIT_WHY = '청산 뒤 대기는 0~50 사이 정수로 적습니다'
const MAX_ENTRIES_WHY = '하루 최대 진입은 1~20 사이 정수로 적습니다'

/** 정수이고 `low`~`high` 안인지. */
function wholeIn(text: string, low: number, high: number): boolean {
  const number = Number(text)
  return text !== '' && Number.isInteger(number) && number >= low && number <= high
}

/** 실행 조건 칸 하나의 판정. 받으면 `null` 입니다. 세션 끝 정리를 켰는데 분이 비었으면
 *  그 칸이 고칠 자리입니다. */
export function filterWhy(aux: Aux, key: AuxFilter): string | null {
  const text = (aux[key] ?? '').trim()
  if (key === 'sessionEndMinutes') {
    if (text === '') return aux.sessionEndFlat ? SESSION_END_WHY : null
    return wholeIn(text, 1, 60) ? null : SESSION_END_WHY
  }
  if (text === '') return null
  if (key === 'entryStart' || key === 'entryEnd') {
    if (parseClock(text) === null) return CLOCK_WHY
    const other = (key === 'entryEnd' ? aux.entryStart : aux.entryEnd ?? '').trim()
    const same = key === 'entryEnd' && parseClock(other) !== null && clockMinutes(other) === clockMinutes(text)
    return same ? WINDOW_SAME_WHY : null
  }
  if (key === 'reentryWaitBars') return wholeIn(text, 0, 50) ? null : WAIT_WHY
  return wholeIn(text, 1, 20) ? null : MAX_ENTRIES_WHY
}

/** 「HH:MM」의 자정부터 분. 모양이 틀리면 `NaN` 입니다. */
export function clockMinutes(text: string): number {
  const parsed = parseClock(text)
  return parsed ? parsed.hour * 60 + parsed.minute : Number.NaN
}

/** 신규 진입 시간이 **그 세션 밖**인지 — 막지 않는 알림입니다. 서버는 저장을 받고
 *  실행을 세울 때 막습니다. 세션 창을 모르면(`null`) 말하지 않습니다. 창의 끝은 열린
 *  구간이라 끝 시각 정각은 밖입니다. */
export function windowOutsideWhy(
  aux: Aux,
  window: { open: string; close: string; nextDay: boolean } | null,
): string | null {
  if (!window) return null
  const open = clockMinutes(window.open)
  const close = clockMinutes(window.close)
  const inside = (text: string) => {
    const at = clockMinutes(text)
    if (Number.isNaN(at)) return true
    return window.nextDay ? at >= open || at < close : at >= open && at < close
  }
  const bad = [aux.entryStart, aux.entryEnd].some((text) => text.trim() !== '' && !inside(text.trim()))
  if (!bad) return null
  return `세션(${window.open}~${window.nextDay ? '익일 ' : ''}${window.close}) 안의 시각이어야 합니다`
}

/** 주문 가격 기준 세 칸(공용·매수·매도)에서 못 받는 칸과 그 까닭. **서버와 같은
 *  규칙**입니다 — 방향 칸이 비면 그 방향은 공용 기준을 씁니다. 값을 받는
 *  주문유형인데 방향 칸이 둘 다 비고 공용도 비면 공용 칸이, 방향 칸 하나만
 *  적고 공용이 비면 **빈 방향 칸**이 고칠 자리입니다. 값을 안 받는 주문유형은
 *  비어도 되지만, 적었다면 아는 값이어야 합니다. */
export function sideBases(aux: Aux): { field: 'priceBasis' | 'buyPriceBasis' | 'sellPriceBasis'; why: string | null }[] {
  const known = (value: string) => PRICE_BASES.includes(value)
  const shared = aux.priceBasis.trim()
  const sides = [
    { field: 'buyPriceBasis' as const, own: aux.buyPriceBasis.trim(), why: '매수 주문 가격 기준을 고르세요' },
    { field: 'sellPriceBasis' as const, own: aux.sellPriceBasis.trim(), why: '매도 주문 가격 기준을 고르세요' },
  ]
  const needs = needsPriceFor(aux.orderType)
  const sharedBad =
    (shared !== '' && !known(shared)) || (needs && shared === '' && sides.every((one) => one.own === ''))
  return [
    { field: 'priceBasis', why: sharedBad ? '주문 가격 기준을 고르세요' : null },
    ...sides.map((one) => {
      const unknown = one.own !== '' && !known(one.own)
      /* 공용 칸이 모르는 값이면 그 칸 하나에 이미 달았습니다 — 원인이 하나인데
         빈 방향 칸에 또 달면 같은 것을 두 번 고치라는 말이 됩니다. */
      const empty =
        needs && one.own === '' && shared === '' && sides.some((other) => other.own !== '')
      return { field: one.field, why: unknown || empty ? one.why : null }
    }),
  ]
}

/** 그 조건 줄에서 **아직 안 고른 칸**. 다 골랐으면 `null` 입니다.
 *
 *  **한 줄에 하나만 말합니다** — 왼쪽부터 채워 가는 줄이라, 뒤 칸은 앞 칸을
 *  고르기 전에는 고를 수도 없습니다(연산자 목록이 값에 딸려 있습니다).
 *  낱말은 그 칸의 **열 머리 이름**을 그대로 씁니다 — 「값」·「조건」·「견줄 값」이
 *  화면에 서 있는데 다른 말로 부르면 어느 칸인지 다시 찾아야 합니다. */
export function fillWhy(cond: Cond): string | null {
  if (!operandOf(cond.left)) return '값을 고르세요'
  const op = operatorOf(cond.op)
  if (!op) return '조건을 고르세요'
  if (rightKindOf(op, cond) === 'number') {
    return cond.right.trim() === '' ? '견줄 수를 적으세요' : null
  }
  return operandOf(cond.right) ? null : '견줄 값을 고르세요'
}

/** 다 고른 줄이 **서버가 받지 않는 짝**이면 그 까닭. 받으면 `null` 입니다.
 *
 *  **서버와 같은 글자·같은 차례·첫 하나**입니다 — 화면과 서버가 같은 줄에 다른
 *  첫 문장을 세우면 무엇을 고쳐야 하는지 두 말이 됩니다. 차례: 시각 모양 →
 *  시각 아닌 값의 「HH:MM」 → 일봉의 시간 값 → 호가끼리 → 같음의 값 → 같음의 수. */
export function contextWhy(cond: Cond, daily: boolean): string | null {
  const op = operatorOf(cond.op)
  if (!op) return null
  const left = cond.left
  const right = cond.right.trim()
  const byNumber = rightKindOf(op, cond) === 'number'
  if (byNumber) {
    if (left === CLOCK_ID && parseClock(right) === null) return '시각은 HH:MM(00:00~23:59)으로 적습니다'
    if (left !== CLOCK_ID && right.includes(':')) return 'HH:MM 은 시각에만 씁니다'
  }
  if (daily && (TIME_IDS.includes(left) || (!byNumber && TIME_IDS.includes(right)))) {
    return '일봉에서는 시각·봉 순서를 쓸 수 없습니다'
  }
  const cross = op.id === 'crossUp' || op.id === 'crossDown'
  const sameBook =
    (BOOK_PRICE_IDS.includes(left) && BOOK_PRICE_IDS.includes(right)) ||
    (BOOK_QTY_IDS.includes(left) && BOOK_QTY_IDS.includes(right))
  if (!byNumber && !cross && (CONTEXT_IDS.includes(left) || CONTEXT_IDS.includes(right)) && !sameBook) {
    return '호가는 호가끼리만 견줍니다 — 시간·보유는 수와 견줍니다'
  }
  if (op.id === 'eq') {
    if (!INTEGER_IDS.includes(left) || (!byNumber && !INTEGER_IDS.includes(right))) {
      return '같음은 정수 값(잔량·보유 수량·시각·봉 순서)에만 씁니다'
    }
    if (byNumber && left !== CLOCK_ID) {
      const number = Number(right.replace(/,/g, ''))
      if (right === '' || !Number.isFinite(number) || !Number.isInteger(number)) return '같음은 정수와 견줍니다'
    }
  }
  return paramsWhy(cond) ?? crossWhy(cond)
}

/** 조건 줄의 매개변수 칸 가운데 못 받는 칸들 — 칸 테두리를 붉게 하는 데 씁니다.
 *  오른쪽은 값으로 견줄 때만 봅니다. */
export function paramProblems(cond: Cond): { side: 'left' | 'right'; key: string; why: string }[] {
  const op = operatorOf(cond.op)
  const byOperand = op ? rightKindOf(op, cond) === 'operand' : cond.rightKind === 'operand'
  const left = sideParamProblems(cond.left, cond.leftParams).map((one) => ({ side: 'left' as const, ...one }))
  const right = byOperand && cond.right
    ? sideParamProblems(cond.right, cond.rightParams).map((one) => ({ side: 'right' as const, ...one }))
    : []
  return [...left, ...right]
}

/** 매개변수의 판정 — 범위와, 묶음을 함께 쓰는 지표끼리(MACD·스토캐스틱) 같은
 *  설정인지. **서버와 같은 글자·같은 차례**입니다. */
function paramsWhy(cond: Cond): string | null {
  const first = paramProblems(cond)[0]
  if (first) return first.why
  if (cond.rightKind !== 'operand' || !cond.right) return null
  const left = resolveOperand(cond.left, cond.leftParams)
  const right = resolveOperand(cond.right, cond.rightParams)
  const group = sharedGroupOf(left.id)
  if (group && group.includes(right.id) && JSON.stringify(left.params) !== JSON.stringify(right.params)) {
    return SHARED_PARAMS_WHY
  }
  return null
}

/** 교차가 서는 짝인지. 같은 열끼리(EMA(20)×EMA(20))는 늘 거짓이라 막고, 가격 축의
 *  선이 아니거나 같은 지표의 선끼리가 아니면 막습니다 — 서버와 같은 규칙입니다. */
function crossWhy(cond: Cond): string | null {
  if (cond.op !== 'crossUp' && cond.op !== 'crossDown') return null
  if (cond.rightKind !== 'operand') return CROSS_SIDES_WHY
  if (operandKey(cond.left, cond.leftParams) === operandKey(cond.right, cond.rightParams)) return SAME_CROSS_WHY
  return crossPair(cond.left, cond.right) ? null : CROSS_SIDES_WHY
}

/** 그 줄의 판정 한 줄. 아직 안 고른 칸이 먼저이고, 다 골랐으면 서버가 받지 않는
 *  짝의 까닭입니다. */
export function condWhy(cond: Cond, daily: boolean): string | null {
  return fillWhy(cond) ?? contextWhy(cond, daily)
}

/** 그 보조 칸의 값이 **저장을 막는가**. 수 칸은 `auxWhy`, 주문 가격 기준 칸은
 *  `sideBases` 로 — 칸 아래 판정 줄과 같은 판정입니다. 요약 문단이 문장에서 뺄
 *  칸을 고르는 데 씁니다. */
export function auxBad(aux: Aux, field: keyof Aux): boolean {
  if (field in AUX_NUMBERS) return auxWhy(aux, field as AuxNumber) !== null
  if (FILTER_FIELDS.includes(field as AuxFilter)) return filterWhy(aux, field as AuxFilter) !== null
  /* 뒤에 생긴 방향 칸이 없는 옛 설정도 받습니다 — 없는 칸은 빈 칸(공용 기준을 따름)입니다. */
  const filled = { ...aux, buyPriceBasis: aux.buyPriceBasis ?? '', sellPriceBasis: aux.sellPriceBasis ?? '' }
  const base = sideBases(filled).find((one) => one.field === field)
  return base ? base.why !== null : false
}

/** 단계 사이 유효기간이 못 받는 값일 때의 까닭. **서버와 같은 글자**입니다 — 칸
 *  곁 글자(「다음 봉부터 … 봉 이내」)가 조각나 있어 까닭이 제 이름을 말해야
 *  하고, 서버가 거절할 때와 같은 말이라 어느 쪽이 서도 같은 글입니다. */
export const WITHIN_WHY = '다음 단계 유효기간은 1봉 이상으로 적습니다'

/** 그 단계의 「다음 봉부터 N봉 이내」가 못 받는 값이면 그 까닭. 받으면 `null`
 *  입니다. 받는 값은 1 이상의 정수이고 판정은 `numberWhy` 그대로입니다.
 *  **마지막 단계에는 이 칸이 없어** 늘 `null` 입니다 — 단계를 지워 마지막이
 *  바뀌면 판정도 따라 사라집니다. 칸 판정·탭 배지·저장 막음·요약 문단이 모두
 *  이 하나를 부릅니다. */
export function withinWhy(rule: Rule, index: number): string | null {
  if (index >= rule.steps.length - 1) return null
  return numberWhy(String(rule.steps[index].withinBars), true) === null ? null : WITHIN_WHY
}

/* ── 판정 줄의 색 ─────────────────────────────────────── */

/** 판정의 갈래. **색은 이 갈래 하나로 고릅니다**(`whyTone`).
 *  - `wrong`: 적은 값이 틀려 저장이 막힘
 *  - `unfilled`: 아직 채우지 않음(저장은 막지만 틀린 것이 아님)
 *  - `warning`: 저장을 막지 않는 알림
 *  안 채운 칸을 틀린 칸과 같은 색으로 세우면, 새 줄을 넣는 순간마다 편집 중인
 *  줄이 「틀린 줄」로 읽힙니다. */
export type WhyKind = 'wrong' | 'unfilled' | 'warning'

/** 판정 줄·표지에 붙일 색 클래스. 오류색은 틀린 값뿐이고, 나머지는 경고색입니다. */
export function whyTone(kind: WhyKind): 'set-bad-why' | 'set-warn-why' {
  return kind === 'wrong' ? 'set-bad-why' : 'set-warn-why'
}

/** 서버 말의 갈래. 서버는 틀린 값을 오류로, 알림을 경고로 보냅니다. */
export function severityKind(severity: 'error' | 'warning'): WhyKind {
  return severity === 'error' ? 'wrong' : 'warning'
}

/** 판정 문장과 그 갈래. */
export interface Check {
  text: string
  kind: WhyKind
}

/** 조건 줄 판정(`condWhy`)과 갈래 — 안 고른 칸이면 `unfilled`, 서버가 받지 않는
 *  짝이면 `wrong` 입니다. */
export function condCheck(cond: Cond, daily: boolean): Check | null {
  const unfilled = fillWhy(cond)
  if (unfilled) return { text: unfilled, kind: 'unfilled' }
  const wrong = contextWhy(cond, daily)
  return wrong ? { text: wrong, kind: 'wrong' } : null
}

/** 보조 수 칸 판정(`auxWhy`)과 갈래 — 비워 둔 필수 칸이면 `unfilled`, 적은 값이
 *  못 받는 값이면 `wrong` 입니다. */
export function auxCheck(aux: Aux, key: AuxNumber): Check | null {
  const text = auxWhy(aux, key)
  if (!text) return null
  return { text, kind: (aux[key] ?? '').trim() === '' ? 'unfilled' : 'wrong' }
}

/** 가격 기준 칸 판정(`sideBases`)의 갈래 — 비어 있으면 `unfilled`, 모르는 값이면
 *  `wrong` 입니다. */
export function baseKind(aux: Aux, field: 'priceBasis' | 'buyPriceBasis' | 'sellPriceBasis'): WhyKind {
  return (aux[field] ?? '').trim() === '' ? 'unfilled' : 'wrong'
}
