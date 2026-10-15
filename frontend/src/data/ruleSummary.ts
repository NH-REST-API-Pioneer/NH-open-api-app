import {
  excludedOrderType,
  exitUnitOf,
  fill,
  needsPriceFor,
  needsStopFor,
  operandOf,
  operandWord,
  operatorOf,
  rightFormOf,
  rightKindOf,
  particle,
  ro,
  RULE_LABEL,
  LEVEL_OPS,
  TAIL,
  type Aux,
  type RightForm,
  type Cond,
  type Rule,
  type RuleKey,
  type Step,
} from './strategyRules'
import { auxBad, clockMinutes, condWhy, numberWhy, withinWhy } from './strategyChecks'
import { moneyIn } from '../lib/number'

/* 규칙을 사람 말로 옮깁니다.
 *
 * **단계마다 한 문장**입니다. 단계는 차례로 평가하는 별개의 관문이라, 하나로
 * 이어 붙이면 어디까지가 첫 관문이고 어디부터가 다음인지 문장 안에서 흐려집니다.
 * 마지막 문장이 「…면 매수 진입」으로 닫아 그 규칙이 무엇을 하는지 말합니다.
 *
 * 이 글은 조건을 다시 쓴 것이지 요약이 아닙니다 — 값을 하나라도 빠뜨리면
 * 화면에 적힌 것과 문장이 갈리고, 사람은 읽기 쉬운 쪽을 믿습니다.
 */

/** 아직 다 고르지 않은 줄은 문장에 세우지 않습니다. */
function ready(cond: Cond): boolean {
  const op = operatorOf(cond.op)
  if (!operandOf(cond.left) || !op) return false
  return rightKindOf(op, cond) === 'number'
    ? cond.right.trim() !== ''
    : operandOf(cond.right) !== null
}

/** 그 조건이 지금 쓰는 갈래의 문장 틀. 값으로 견주는지 수로 견주는지에 따라
 *  조사가 갈립니다 — 「고가를 초과」와 「430 초과」. */
function formOf(cond: Cond): RightForm {
  const op = operatorOf(cond.op)!
  return rightFormOf(op, rightKindOf(op, cond))!
}

/** 평가손익의 수를 돈 꼴로 — 「−50,000원」·「−120.00 USD」. 전략 화면의 다른
 *  금액과 같은 규칙입니다(`moneyIn`). 수가 아닌 글자는 적은 그대로입니다. */
function moneyOf(text: string, currency: string | undefined): string {
  const number = Number(text.replace(/,/g, ''))
  if (text === '' || !Number.isFinite(number)) return text
  return moneyIn(number, currency)
}

function phraseOf(cond: Cond, currency?: string): string {
  const op = operatorOf(cond.op)!
  const left = operandWord(cond.left, cond.leftParams)!
  const kind = rightKindOf(op, cond)
  /* 수는 적은 그대로입니다(봉 시작 시각의 「09:30」도). 평가손익만 돈 꼴입니다. */
  const right =
    kind === 'number'
      ? cond.left === 'openPl'
        ? moneyOf(cond.right.trim(), currency)
        : cond.right.trim()
      : operandWord(cond.right, cond.rightParams)!
  return fill(rightFormOf(op, kind)!.phrase, left, right)
}

/** 다 골랐지만 **저장을 막는 줄**인가. 칸 아래 판정 줄과 같은 판정(`condWhy`)
 *  이고, 일봉인지도 화면 판정과 같은 조건으로 봅니다. */
function blocked(cond: Cond, baseBar: string): boolean {
  return ready(cond) && condWhy(cond, baseBar === '일봉') !== null
}

/** 문장에 세우는 줄 — 다 골랐고, 저장을 막는 줄이 아닌 것. 저장을 막는 줄을
 *  문장에 세우면 저장될 수 없는 조건을 정한 조건처럼 말합니다. */
function usable(cond: Cond, ctx: SummaryContext): boolean {
  return ready(cond) && !blocked(cond, ctx.baseBar)
}

/** 그 단계를 여는 「다음 봉부터 N봉 이내」(앞 단계의 칸)가 저장을 막는 값인가.
 *  그러면 그 단계 문장은 세우지 않습니다. 첫 단계는 여는 칸이 없습니다. */
function withinBad(rule: Rule, index: number): boolean {
  return index > 0 && withinWhy(rule, index - 1) !== null
}

/** 조건 여럿을 한 문장으로 잇습니다. 잇는 꼬리는 **앞 조건**의 끝말이 정합니다. */
function joinConds(conds: Cond[], join: Step['join'], tail: string, ctx: SummaryContext): string {
  const currency = ctx.currency
  const done = conds.filter((cond) => usable(cond, ctx))
  if (done.length === 0) return ''
  const parts = done.map((cond, index) => {
    const text = phraseOf(cond, currency)
    if (index < done.length - 1) {
      return text + TAIL[formOf(cond).ending][join === 'all' ? 'all' : 'any']
    }
    return text + tail
  })
  return parts.join(' ')
}

export interface SummaryContext {
  /** 「15분봉」처럼 조건을 재는 봉. */
  baseBar: string
  /** 봉 마감에서 보는지 틱마다 보는지. */
  evalMode: string
  /** 그 전략의 통화. 평가손익의 수를 돈 꼴로 적는 데 씁니다. */
  currency?: string
}

/** 문장을 내는 단계들 — 저장될 수 있는 줄이 하나라도 있고, 그 단계를 여는 앞
 *  단계의 유효기간이 저장을 막지 않는 단계입니다. */
function stepsSaid(rule: Rule, ctx: SummaryContext) {
  return rule.steps
    .map((step, index) => ({ step, index, done: step.conds.filter((cond) => usable(cond, ctx)) }))
    .filter((item) => item.done.length > 0 && !withinBad(rule, item.index))
}

/** 규칙 하나를 단계마다 한 문장으로. 아직 채우지 않은 규칙은 빈 배열입니다. */
export function summarize(rule: Rule, key: RuleKey, ctx: SummaryContext): string[] {
  /* 문장을 내는 단계만 먼저 고릅니다. 「…면 매수 진입」으로 닫는 것은 **규칙의
     실제 마지막 단계가 문장을 낼 때만**입니다. 마지막 단계가 비었거나 저장을
     막는 값으로 빠졌으면 앞 단계들은 관문 문장(「… 55 이상.」)으로 두고 동작을
     붙이지 않습니다 — 앞 단계만으로 매수한다고 적으면, 저장될 수도 없는 규칙을
     있는 주문처럼 말하게 됩니다. 빠진 마지막 단계는 `ruleGaps` 가 「아직 정하지
     않음」에 올립니다. 중간 단계는 관문이지 행동이 아니라 거기에는 늘 동작을
     붙이지 않습니다. */
  const filled = stepsSaid(rule, ctx)
  const last = rule.steps.length - 1

  return filled.map(({ step, index, done }) => {
    const closes = index === last
    const tail = closes ? TAIL[formOf(done[done.length - 1]).ending].then : ''
    const body = joinConds(step.conds, step.join, tail, ctx)
    const act = closes ? ` ${RULE_LABEL[key]}` : ''

    if (index === 0) {
      const when = ctx.evalMode === '마감' ? `${ctx.baseBar} 마감에서` : `${ctx.baseBar} 틱마다`
      /* 1단계의 이상·이하·초과·미만·같음은 **그 상태가 된 순간**에만 냅니다 — 이미
         그 상태로 있는 동안 봉마다 내지 않습니다. 교차만 있는 단계는 그 자체가
         순간이라 덧붙이지 않습니다. */
      const level = done.some((cond) => LEVEL_OPS.includes(cond.op))
      /* 다음 단계가 있으면 주문이 아니라 그 단계가 걸리는 것이라 낱말이 다릅니다. */
      const moment = !level ? '' : closes ? ' — 참으로 바뀌는 순간에 냅니다' : ' — 참으로 바뀌는 순간에 걸립니다'
      return `${when} ${body}${act}${moment}.`
    }
    /* 앞 단계가 정한 유효기간입니다 — 「다음 단계까지 몇 봉」이라 앞에서 읽습니다. */
    const within = rule.steps[index - 1].withinBars
    return `다음 봉부터 ${within}봉 이내에 ${body}${act}.`
  })
}

/** 규칙 하나에서 **문장에서 뺀 자리**의 이름들. 「아직 정하지 않음」 줄에
 *  섭니다. 차례는 단계마다 그 단계의 조건 줄 → 그 단계의 유효기간, 그 뒤 빠진
 *  마지막 단계, 끝에 되돌리기입니다.
 *
 *  - 조건 줄: 「매수 진입 1단계 3번 조건」. 저장을 막는 줄입니다. 단계와 줄은
 *    화면처럼 1부터 셉니다. 아직 다 고르지 않은 줄은 넣지 않습니다 — 규칙 카드의
 *    「안 채운 줄」이 이미 말합니다.
 *  - 유효기간: 「매수 진입 1단계 유효기간」(그 칸이 있는 단계). 마지막 단계의
 *    칸은 쓰이지 않아 보지 않습니다.
 *  - 마지막 단계: 「매수 진입 2단계」. 앞 단계는 문장을 냈는데 마지막 단계가
 *    문장을 못 내면(비었음·줄이 다 걸림·유효기간이 걸림) 규칙이 동작으로 닫히지
 *    않습니다. 그 까닭을 여기서 말합니다.
 *  - 되돌리기: 「매수 진입 처음으로 되돌리기」. */
export function ruleGaps(rule: Rule, key: RuleKey, ctx: SummaryContext): string[] {
  const label = RULE_LABEL[key]
  const steps = rule.steps.flatMap((step, stepIndex) => [
    ...step.conds.flatMap((cond, condIndex) =>
      blocked(cond, ctx.baseBar) ? [`${label} ${stepIndex + 1}단계 ${condIndex + 1}번 조건`] : [],
    ),
    ...(withinWhy(rule, stepIndex) !== null ? [`${label} ${stepIndex + 1}단계 유효기간`] : []),
  ])
  const said = stepsSaid(rule, ctx)
  const last = rule.steps.length - 1
  const open = said.length > 0 && said[said.length - 1].index !== last ? [`${label} ${last + 1}단계`] : []
  return [...steps, ...open, ...(resetBad(rule) ? [`${label} 처음으로 되돌리기`] : [])]
}

/** 목록·상세에 서는 **한 줄 요약**. 설정 화면이 세우는 문장과 **같은 자리에서**
 *  나옵니다 — 두 곳이 따로 지으면 같은 전략이 화면마다 다른 말을 합니다.
 *
 *  **켜져 있고 문장이 나오는 첫 규칙의 마지막 문장**입니다. 마지막 문장이 곧
 *  「그래서 무엇을 하는가」로 닫는 문장이고, 중간 단계는 관문이라 그것만 떼면
 *  행동이 빠진 글이 됩니다. 마지막 단계가 빠진 규칙이면 동작 없는 관문 문장이
 *  섭니다 — 없는 동작을 지어 붙이지 않습니다. 규칙이 여럿이어도 한 줄 자리라 첫 규칙만 적습니다 —
 *  넷을 다 보는 자리는 설정 화면입니다.
 *
 *  조건이 하나도 없으면 **빈 문자열**입니다. 무엇을 적을지는 부르는 쪽이 정합니다
 *  — 목록의 빈 말과 여기의 규칙이 갈리면 한쪽만 고쳐지는 자리가 생깁니다. */
export function summaryOf(
  rules: Record<RuleKey, Rule>,
  ctx: SummaryContext,
  order: readonly RuleKey[],
): string {
  for (const key of order) {
    const rule = rules[key]
    if (!rule?.on) continue
    const lines = summarize(rule, key, ctx)
    if (lines.length > 0) return lines[lines.length - 1]
  }
  return ''
}

/** 어느 규칙에든 **적어 둔 조건이 있나**. 켜짐·꺼짐은 안 봅니다.
 *
 *  문장이 안 나올 때 「조건이 없는 것」과 「적어 두고 꺼 둔 것」을 가르는 자리입니다 —
 *  사용자가 할 일이 다릅니다: 앞은 채우는 일이고 뒤는 켜는 일입니다. 한 말로
 *  뭉뚱그리면 조건을 다 적어 둔 사람이 「아직 안 넣었다」를 보고 설정을 다시 뒤집니다.
 *
 *  **네 규칙을 다 봅니다.** 청산에만 적어 두었어도 「아직 안 넣었다」는 거짓입니다 —
 *  적어 둔 것이 화면 어딘가에 있으니까요. 그때 무엇이 모자란지는 문장이 말합니다. */
export function anyConditions(
  rules: Record<RuleKey, Rule>,
  ctx: SummaryContext,
  order: readonly RuleKey[],
): boolean {
  return order.some((key) => {
    const rule = rules[key]
    return rule ? summarize(rule, key, ctx).length > 0 : false
  })
}

/* ── 보조 설정 ──────────────────────────────────────── */

/** 손절·익절·추적 청산의 거리를 단위와 함께 — 「10틱」·「3.5포인트」·「2%」·「1.5 ATR 배」.
 *  **거리를 적는 자리는 모두 이것 하나를 씁니다**(요약·접힌 줄·진행 머리 띠·확인창) —
 *  자리마다 따로 적으면 단위를 바꿨을 때 한 곳만 「틱」으로 남습니다. */
export function distanceText(value: string, unit: string | undefined): string {
  const text = value.trim()
  switch (exitUnitOf(unit)) {
    case 'price':
      return `${text}포인트`
    case 'pct':
      return `${text}%`
    case 'atr':
      return `${text} ATR 배`
    default:
      return `${text}틱`
  }
}

/** 앱이 보는 청산의 한 줄 — 「손절 10틱 · 익절 2% · 끝 10분 전 정리」. 진행 머리 띠와
 *  실행 확인창이 씁니다. 값이 없으면 「—」입니다. 익절은 비워 두면 쓰지 않는 것이라
 *  「익절 안 씀」입니다 — 설정을 모를 때(`aux` 없음)만 「—」입니다. */
export function watchLine(aux: Partial<Aux> | null | undefined): string {
  const stop = (aux?.stopTicks ?? '').trim()
  const take = (aux?.takeTicks ?? '').trim()
  const parts = [
    `손절 ${stop ? distanceText(stop, aux?.stopUnit) : '—'}`,
    take ? `익절 ${distanceText(take, aux?.takeUnit)}` : aux ? '익절 안 씀' : '익절 —',
  ]
  const minutes = (aux?.sessionEndMinutes ?? '').trim()
  if (aux?.sessionEndFlat && minutes) parts.push(`끝 ${minutes}분 전 정리`)
  return parts.join(' · ')
}

/** 신규 진입 시간의 글 — 「09:00~14:30」. 빈 쪽은 「세션 시작」·「세션 끝」이고, 끝이
 *  시작보다 이르면 다음 날이라 「익일」을 답니다. 둘 다 비면 빈 글자입니다. */
export function entryWindowText(start: string, end: string): string {
  const from = start.trim()
  const to = end.trim()
  if (from === '' && to === '') return ''
  const nextDay = from !== '' && to !== '' && clockMinutes(to) < clockMinutes(from)
  return `${from || '세션 시작'}~${nextDay ? '익일 ' : ''}${to || '세션 끝'}`
}

/** 규칙 뒤에 이어 붙는 글. **주문이 나가는 차례**로 적습니다 — 주문 방식,
 *  청산·수량, 실행 필터, 위험 한도. 오른쪽 아코디언과 같은 차례입니다.
 *
 *  범위는 라벨이 아니라 **주어**로 가릅니다. 규칙 문장은 주어 없이 조건으로
 *  시작하므로, 「이 전략은」으로 시작하는 문장부터가 전략 전체의 이야기입니다. */
export interface AuxSummary {
  lines: string[]
  /** 아직 안 정한 값의 이름들. **빈 값과 저장을 막는 값은 문장에서 빼고 여기로
   *  모읍니다** — 「손절 틱에 끊습니다」나 「손절 0틱」처럼 저장될 수 없는 문장을
   *  세우면 화면이 정하지 않은 것을 정한 것처럼 말합니다. */
  missing: string[]
}

function blank(value: string): boolean {
  return value.trim() === ''
}

export function summarizeAux(
  aux: Aux,
  market: 'domestic' | 'overseas',
  /** 돈을 적는 방법. 통화가 전략마다 달라 부르는 쪽이 넘깁니다. */
  money: (value: string) => string,
): AuxSummary {
  /* 저장을 막는 값인가 — 칸 아래 판정 줄과 같은 판정입니다(`strategyChecks.ts`). */
  const bad = (field: keyof Aux) => auxBad(aux, field)
  const lines: string[] = []
  const missing: string[] = []

  /* 주문 방식. 값 칸을 안 쓰는 유형(시장가·STOP-M)은 가격 기준을 적지
     않습니다 — 고를 수는 있지만 그 주문에는 실리지 않는 값입니다.
     방향마다 기준을 정했으면 **두 방향의 실제 값**을 적습니다(비운 쪽은 공통
     기준). 두 값이 같으면 가를 것이 없어 한 기준 문장 그대로입니다. */
  const buy = (aux.buyPriceBasis ?? '') || aux.priceBasis
  const sell = (aux.sellPriceBasis ?? '') || aux.priceBasis
  /* 기준을 모르는 방향이 있으면(공통 기준도 비고 그 방향 칸도 빔) **문장을 세우지
     않고** 아직 안 정한 값으로 모읍니다 — 빈 자리가 든 문장은 정하지 않은 것을
     정한 것처럼 말합니다. 그 방향이 쓰는 칸(제 칸, 비었으면 공통 칸)이 저장을
     막는 값이어도 같습니다. */
  const buyBad = buy === '' || bad(aux.buyPriceBasis ? 'buyPriceBasis' : 'priceBasis')
  const sellBad = sell === '' || bad(aux.sellPriceBasis ? 'sellPriceBasis' : 'priceBasis')
  const lacking = !needsPriceFor(aux.orderType)
    ? []
    : buyBad && sellBad
      ? ['주문 가격']
      : [...(buyBad ? ['매수 주문 가격'] : []), ...(sellBad ? ['매도 주문 가격'] : [])]
  const how = !needsPriceFor(aux.orderType)
    ? `이 전략은 ${aux.orderType}${ro(aux.orderType)} 냅니다.`
    : buy !== sell
      ? `이 전략은 매수는 ${buy}에, 매도는 ${sell}에 ${aux.orderType}${ro(aux.orderType)} 냅니다.`
      : `이 전략은 ${buy}에 ${aux.orderType}${ro(aux.orderType)} 냅니다.`
  /* 전략 주문에 쓰지 않는 유형이 남은 옛 설정이면 그 유형으로 낸다고 말하지
     않습니다 — 다른 유형을 골라야 저장되는 값이라 아직 정하지 않은 값입니다. */
  if (excludedOrderType(aux.orderType)) missing.push('주문 유형')
  else if (lacking.length > 0) missing.push(...lacking)
  else lines.push(how)
  /* 체결조건은 국내 주문에만 있습니다. 비어 있으면 문장을 세우지 않고 아직 정하지
     않은 값으로 모읍니다 — 빈 자리가 든 문장은 「체결조건은 입니다」가 됩니다. */
  if (market === 'domestic') {
    if (aux.fillCond.trim()) lines.push(`체결조건은 ${aux.fillCond}입니다.`)
    else missing.push('체결조건')
  }
  else if (needsStopFor(aux.orderType)) lines.push(`스탑은 ${aux.stopBasis}입니다.`)

  /* 청산·수량. 한 문장이라 하나라도 비거나 저장을 막으면 문장을 안 세웁니다
     — 반만 적으면 나머지를 정했는지 안 정했는지 문장이 말하지 못합니다.
     익절은 **비어 있으면 쓰지 않는 것**이라 문장에서 그 자리만 빠집니다. 적었는데
     저장을 막는 값이면 다른 칸처럼 문장을 빼고 이름을 모읍니다. */
  const take = (aux.takeTicks ?? '').trim()
  const exit = [
    { name: '주문당 수량', value: aux.perOrder, field: 'perOrder' as const },
    { name: '최대 보유', value: aux.maxHold, field: 'maxHold' as const },
    { name: '손절', value: aux.stopTicks, field: 'stopTicks' as const },
    ...(take !== '' ? [{ name: '익절', value: aux.takeTicks, field: 'takeTicks' as const }] : []),
  ]
  const exitBlank = exit.filter((one) => blank(one.value) || bad(one.field))
  if (exitBlank.length === 0) {
    /* 거리는 그 단위로 적습니다(「손절 1.5 ATR 배·익절 2%」). */
    const cut =
      `손절 ${distanceText(aux.stopTicks, aux.stopUnit)}` +
      (take !== '' ? `·익절 ${distanceText(take, aux.takeUnit)}` : '')
    lines.push(`한 번에 ${aux.perOrder}계약씩, 최대 ${aux.maxHold}계약까지 들고, ${cut}에 시장가로 전량 끊습니다.`)
  } else missing.push(...exitBlank.map((one) => one.name))
  /* 추적 청산. **비어 있으면 쓰지 않는 것**이라 문장도 없고 「아직 정하지 않음」
     에도 넣지 않습니다 — 끄는 것도 정한 값입니다. 적었는데 저장을 막는 값이면
     문장을 빼고 이름을 모읍니다. */
  const trail = (aux.trailTicks ?? '').trim()
  if (trail !== '') {
    if (bad('trailTicks')) missing.push('추적 청산')
    else lines.push(`가장 유리했던 가격에서 ${distanceText(trail, aux.trailUnit)} 되돌면 시장가로 전량 끊습니다.`)
  }
  /* 세션 끝 정리. 켰을 때만 섭니다 — 끈 것은 지금까지의 동작이라 적을 말이 없습니다. */
  if (aux.sessionEndFlat) {
    if (bad('sessionEndMinutes')) missing.push('세션 끝 정리')
    else lines.push(`세션 끝 ${aux.sessionEndMinutes.trim()}분 전에 모두 청산하고 새로 들어가지 않습니다.`)
  }

  /* 실행 필터. 고르는 값뿐이라 빌 일이 없습니다. */
  lines.push(
    `${aux.session}에만 돌고, 보유·미체결이 있으면 추가로 진입` +
      `${aux.addWhileOpen ? '합니다' : '하지 않습니다'}.`,
  )
  /* 신규 진입 시간. 비어 있으면 세션 전체라 적지 않습니다. 못 받는 시각이면 문장을 빼고
     이름을 모읍니다. */
  const windowText = entryWindowText(aux.entryStart ?? '', aux.entryEnd ?? '')
  if (windowText !== '') {
    if (bad('entryStart') || bad('entryEnd')) missing.push('신규 진입 시간')
    else lines.push(`신규 진입은 ${windowText}(한국시간)에만 합니다.`)
  }
  /* 청산 뒤 대기와 하루 최대 진입 — 둘 다 정했으면 한 문장입니다. 0봉 대기는 기다리지
     않는 것이라 적지 않습니다. */
  const wait = (aux.reentryWaitBars ?? '').trim()
  const most = (aux.maxEntriesPerDay ?? '').trim()
  const waitBad = wait !== '' && bad('reentryWaitBars')
  const mostBad = most !== '' && bad('maxEntriesPerDay')
  if (waitBad) missing.push('청산 뒤 대기')
  if (mostBad) missing.push('하루 최대 진입')
  const waitPart = !waitBad && wait !== '' && Number(wait) > 0 ? `청산 뒤 ${wait}봉 동안 다시 들어가지 않` : ''
  const mostPart = !mostBad && most !== '' ? `하루 최대 ${most}번 진입합니다` : ''
  if (waitPart && mostPart) lines.push(`${waitPart}고, ${mostPart}.`)
  else if (waitPart) lines.push(`${waitPart}습니다.`)
  else if (mostPart) lines.push(`${mostPart}.`)

  /* 위험 한도. 둘이 한 문장이라 청산·수량과 같은 규칙입니다(빈 값·저장을 막는 값). */
  const risk = [
    { name: '하루 손실 한도', value: aux.dailyLoss, field: 'dailyLoss' as const },
    { name: '증거금 예산', value: aux.marginBudget, field: 'marginBudget' as const },
  ]
  const riskBlank = risk.filter((one) => blank(one.value) || bad(one.field))
  if (riskBlank.length === 0) {
    const budget = money(aux.marginBudget)
    lines.push(
      `하루 ${money(aux.dailyLoss)} 잃거나 증거금 ${budget}` +
        `${particle(budget, '을/를')} 다 쓰면 멈춥니다.`,
    )
  } else missing.push(...riskBlank.map((one) => one.name))
  /* 연속 손실. 추적 청산과 같은 규칙입니다. */
  const streak = (aux.lossStreak ?? '').trim()
  if (streak !== '') {
    if (bad('lossStreak')) missing.push('연속 손실')
    else lines.push(`손실 거래가 ${streak}번 이어지면 그날은 새로 진입하지 않습니다.`)
  }

  return { lines, missing }
}

/** 되돌리기 칸이 저장을 막는 값인가. 비워 두면 「쓰지 않음」이라 막지 않습니다. */
function resetBad(rule: Rule): boolean {
  return numberWhy(rule.resetBars ?? '', true, true) !== null
}

/** 규칙 하나의 시한 문장. **규칙 문장 바로 다음 줄**에 섭니다 — 규칙 문장 끝의
 *  「…면 매수 진입.」을 건드리지 않고 따로 한 줄입니다. 시한이 비었거나 규칙
 *  문장이 하나도 없으면 빈 글자입니다(무엇을 되돌리는지 말할 문장이 없습니다).
 *  시한이 저장을 막는 값이어도 빈 글자이고, 그 자리는 `ruleGaps` 가 올립니다. */
export function resetLine(rule: Rule, ruleLines: readonly string[]): string {
  const bars = (rule.resetBars ?? '').trim()
  if (bars === '' || ruleLines.length === 0 || resetBad(rule)) return ''
  return `1단계부터 ${bars}봉 안에 다 채워지지 않으면 처음부터 다시 봅니다.`
}
