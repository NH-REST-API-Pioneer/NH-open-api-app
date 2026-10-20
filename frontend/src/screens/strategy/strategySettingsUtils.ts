import { moneyIn } from '../../lib/number'
import {
  auxWhy,
  filterWhy,
  type AuxFilter,
  contextWhy,
  fillWhy,
  sideBases,
  withinWhy,
  type AuxNumber,
} from '../../data/strategyChecks'
import type { SaveProblem } from '../../data/strategyStore'
import {
  fillCondMismatch,
  operandOf,
  operatorOf,
  needsPriceFor,
  excludedOrderType,
  rightKindOf,
  RULE_KEYS,
  RULE_LABEL,
  type Aux,
  type Operand,
  type RightKind,
  type Rule,
  type RuleKey,
} from '../../data/strategyRules'
import { resolveOperand, sharedGroupOf } from '../../data/indicatorOperands'

/** 접는 절이 열려 있는지. */
export type OpenSections = { evaluate: boolean; order: boolean; exit: boolean; filter: boolean; risk: boolean; memo: boolean }

/** 견줄 값의 갈래 이름. 「항목」은 첫 칸과 **같은 목록에서 고른다**는 뜻이고,
 *  「숫자」는 직접 친다는 뜻입니다. 「값」·「수」로 두면 열 머리의 「견줄 값」과
 *  「값」이 한 줄에서 두 뜻이 됩니다. */
export const KIND_LABEL: Record<RightKind, string> = { operand: '항목', number: '숫자' }

/** 쉼표를 달아 보이는 금액 칸. 담는 값은 쉼표를 뗀 숫자 글자입니다. */
export const MONEY_KEYS: readonly AuxNumber[] = ['dailyLoss', 'marginBudget']

/** 서버 말이 **칸 곁에** 서는 보조 설정 칸. 이 칸들의 말은 저장 단추 위 줄에
 *  다시 세우지 않습니다 — 한 말이 두 자리에 서면 고칠 것이 둘로 읽힙니다. 그
 *  밖의 `aux.*` 말은 칸 곁 자리가 없어 저장 단추 위에 섭니다. */
export const FIELD_SAID: readonly string[] = [
  'aux.priceBasis',
  'aux.buyPriceBasis',
  'aux.sellPriceBasis',
  'aux.stopTicks',
  'aux.takeTicks',
  'aux.trailTicks',
  'aux.stopUnit',
  'aux.takeUnit',
  'aux.trailUnit',
  'aux.lossStreak',
  'aux.sessionEndMinutes',
  'aux.entryStart',
  'aux.entryEnd',
  'aux.reentryWaitBars',
  'aux.maxEntriesPerDay',
]

/** 조건 줄 하나를 가리키는 서버 경로(`rules.{k}.steps.{s}.conds.{c}` 와 그 `.left`). */
export const CONDITION_PATH = /^rules\.[A-Za-z]+\.steps\.\d+\.conds\.\d+(\.left)?$/

/** 단계 사이 유효기간 칸을 가리키는 서버 경로(`rules.{k}.steps.{s}.withinBars`).
 *  이 말은 그 칸 바로 아래 한 자리에 서고 탭 줄 아래 목록에는 서지 않습니다. */
export const WITHIN_PATH = /^rules\.[A-Za-z]+\.steps\.\d+\.withinBars$/

/** 그 규칙에서 유효기간이 못 받는 값인 단계의 차례(0부터). */
export function withinBadSteps(rule: Rule): number[] {
  return rule.steps.flatMap((_, index) => (withinWhy(rule, index) !== null ? [index] : []))
}

/** 방향마다의 가격 기준 칸. 화면 차례(매수 → 매도)입니다. */
export const SIDE_BASES = [
  { key: 'buyPriceBasis', label: '매수 가격', side: '매수' },
  { key: 'sellPriceBasis', label: '매도 가격', side: '매도' },
] as const

/** 「주문 방식」 절의 접힌 줄. **실제로 쓰이는 것만** 적습니다 — 시장가인데 값
 *  기준을 함께 적으면 그 기준이 주문에 실리는 것처럼 읽힙니다. 방향마다 기준을
 *  정했으면 두 방향의 **실제 값**을 적습니다(공통을 따르는 쪽도 그 값으로). */
export function orderLine(aux: Aux): string {
  if (!needsPriceFor(aux.orderType)) return aux.orderType
  if (aux.buyPriceBasis === '' && aux.sellPriceBasis === '') return `${aux.orderType} · ${aux.priceBasis}`
  const buy = aux.buyPriceBasis || aux.priceBasis
  const sell = aux.sellPriceBasis || aux.priceBasis
  return `${aux.orderType} · 매수 ${buy} · 매도 ${sell}`
}

/* 못 받은 값이 몇인가. 접힌 아코디언이 이 수를 답니다 — 펴 보지 않고도 손볼
   곳이 남았는지 알 수 있어야 합니다. **저장도 이 수로 막습니다** — 배지만
   달고 저장을 받으면 손절 「abc」가 저장된 값이 됩니다. */
export function auxProblems(aux: Aux) {
  const bad = (keys: AuxNumber[]) => keys.filter((key) => auxWhy(aux, key) !== null).length
  const badFilter = (keys: AuxFilter[]) => keys.filter((key) => filterWhy(aux, key) !== null).length
  return {
    order:
      sideBases(aux).filter((one) => one.why !== null).length +
      (excludedOrderType(aux.orderType) ? 1 : 0) +
      (fillCondMismatch(aux) ? 1 : 0),
    exit: bad(['stopTicks', 'takeTicks', 'perOrder', 'maxHold', 'trailTicks']) + badFilter(['sessionEndMinutes']),
    filter: badFilter(['entryStart', 'entryEnd', 'reentryWaitBars']),
    risk: bad(['dailyLoss', 'marginBudget', 'lossStreak']) + badFilter(['maxEntriesPerDay']),
  }
}



/** 고를 값들을 **범주로 묶습니다** — 목록이 길어 묶음 없이는 찾는 값이 어디쯤
 *  있는지 짐작이 안 섭니다. 묶음 이름은 읽어 주는 쪽에도 묶음으로 닿는
 *  `<optgroup>` 이라, 고를 수 없는 항목으로 흉내 내지 않습니다.
 *
 *  **범주 하나에 묶음 하나**입니다. 목록에서 떨어져 적힌 같은 범주(가격의 이전
 *  봉 값처럼 뒤에 붙인 것)도 그 범주의 묶음으로 모읍니다 — 같은 이름의 묶음이
 *  둘 서면 어느 쪽에 무엇이 있는지 두 번 찾게 됩니다.
 *
 *  **묶음 차례와 묶음 안의 차례는 목록에 처음 나온 차례**입니다 — 가나다로 다시
 *  세우면 같은 화면이 판마다 다른 차례로 섭니다. */
export function operandGroups(items: readonly Operand[]): [string, Operand[]][] {
  const made: [string, Operand[]][] = []
  for (const item of items) {
    const held = made.find(([category]) => category === item.category)
    if (held) held[1].push(item)
    else made.push([item.category, [item]])
  }
  return made
}

/** 켜 둔 규칙들을 한 문장으로 — 「매수 진입·매수 청산을 씁니다」. 없으면 그 말. */
export function usesLine(rules: Record<RuleKey, { on: boolean }>): string {
  const on = RULE_KEYS.filter((key) => rules[key]?.on).map((key) => RULE_LABEL[key])
  if (on.length === 0) return '쓰는 규칙이 없습니다'
  const last = on[on.length - 1]
  return `${on.join('·')}${hasFinal(last) ? '을' : '를'} 씁니다`
}

/** 한글 낱말 끝에 받침이 있는가. 토씨(을/를·과/와)를 고르는 데 씁니다. */
function hasFinal(word: string): boolean {
  const code = word.charCodeAt(word.length - 1) - 0xac00
  return code >= 0 && code < 11172 && code % 28 !== 0
}

/** 저장을 못 하는 까닭 — 어느 묶음을 고쳐야 하는지. 묶음은 접혀 있을 수 있어,
 *  「값이 틀렸다」만으로는 어디를 펴야 하는지 모릅니다. 어투는 주문 화면의
 *  「주문가격을 고치세요」와 같고, 수는 접힌 묶음의 배지가 이미 말하므로 여기서
 *  되풀이하지 않습니다. 문장 속 이름은 가운뎃점을 붙여 한 덩어리로 적습니다 —
 *  꼬리줄의 항목 구분자가 「 · 」라 띄우면 「청산」과 「수량과 …」로 끊겨 읽힙니다. */
export function saveWhy(problems: ReturnType<typeof auxProblems>, conds: number): string | null {
  const parts: string[] = []
  /* **다 안 고른 조건도 저장을 막습니다.** 서버가 어차피 막는 값이라, 요청을
     보내 놓고 답으로 알려 주면 고칠 자리를 한 번 더 찾아야 합니다. */
  if (conds > 0) parts.push('조건')
  if (problems.order > 0) parts.push('주문 방식')
  if (problems.exit > 0) parts.push('청산·수량')
  if (problems.filter > 0) parts.push('실행 필터')
  if (problems.risk > 0) parts.push('위험 한도')
  if (parts.length === 0) return null
  const joined = parts.reduce((left, right) => `${left}${hasFinal(left) ? '과' : '와'} ${right}`)
  return `${joined}${hasFinal(joined) ? '을' : '를'} 고치세요`
}

/** 문제가 가리키는 규칙. **`rules.buyEntry` 도 `rules.buyEntry.steps.0.conds.1`
 *  도 같은 규칙의 말입니다** — 정확히 맞는 것만 세면 깊은 경로가 어느 자리에도
 *  안 붙어, 서버가 막은 까닭이 화면에서 사라집니다. */
export function ruleOf(field: string): RuleKey | null {
  return (
    RULE_KEYS.find((one) => field === `rules.${one}` || field.startsWith(`rules.${one}.`)) ?? null
  )
}

/** 경로가 가리키는 자리를 사람 말로 — 「단계 2 조건 1」. **서버는 0부터, 화면은
 *  1부터** 세므로 여기서 맞춥니다. 자리를 모르면 빈 글자입니다. */
function placeOf(field: string): string {
  const step = /\.steps\.(\d+)/.exec(field)
  const cond = /\.conds\.(\d+)/.exec(field)
  const parts: string[] = []
  if (step) parts.push(`단계 ${Number(step[1]) + 1}`)
  if (cond) parts.push(`조건 ${Number(cond[1]) + 1}`)
  return parts.join(' ')
}

/** 그 규칙에 걸린 문제. 탭 배지와 탭 줄 아래가 같은 것을 셉니다. */
export function problemsForRule(problems: SaveProblem[], key: RuleKey): SaveProblem[] {
  return problems.filter((one) => ruleOf(one.field) === key)
}

/** 그 문제를 탭 줄 아래에 적는 한 줄. **어느 규칙의 어디**인지를 앞에 답니다 —
 *  같은 문구가 규칙마다 서면 어느 것을 고쳐야 하는지 줄에서 갈리지 않습니다. */
export function ruleLine(one: SaveProblem): string {
  const key = ruleOf(one.field)
  const place = placeOf(one.field)
  const head = [key ? RULE_LABEL[key] : '', place].filter(Boolean).join(' ')
  return head ? `${head} — ${one.message}` : one.message
}

/** 다 골랐지만 서버가 받지 않는 줄의 수. 저장을 막는 데 씁니다. */
export function contextProblems(rule: Rule, daily: boolean): number {
  let count = 0
  for (const step of rule.steps) {
    for (const cond of step.conds) {
      if (fillWhy(cond) === null && contextWhy(cond, daily) !== null) count += 1
    }
  }
  return count
}

/** 다 고르지 않은 조건 행. 규칙 탭 아래 한 줄로 셉니다. */
export function condProblems(rule: Rule): number {
  let count = 0
  for (const step of rule.steps) {
    for (const cond of step.conds) {
      const op = operatorOf(cond.op)
      if (!operandOf(cond.left) || !op) count += 1
      else if (
        rightKindOf(op, cond) === 'number' ? cond.right.trim() === '' : !operandOf(cond.right)
      )
        count += 1
    }
  }
  return count
}

let seed = 100
export const nextSeed = () => (seed += 1)

/** 오른쪽 값이 왼쪽과 **매개변수 묶음을 함께 쓰는지**(MACD 선 × 신호, 스토캐스틱
 *  %K × %D). 그러면 오른쪽 칸은 왼쪽 설정을 따르고 잠깁니다 — 서버도 두 쪽이
 *  다르면 받지 않습니다. */
export function sharesParams(left: string, right: string): boolean {
  const group = sharedGroupOf(resolveOperand(left).id)
  return group !== null && group.includes(resolveOperand(right).id)
}

/** 잠긴 오른쪽 칸에 마우스를 올리면 서는 말. */
export const LOCKED_TITLE = '왼쪽 값의 설정을 따릅니다 — MACD·스토캐스틱끼리는 같은 설정이어야 합니다'

/** 한도·예산을 적는 말. **통화는 그 전략의 것**입니다 — 해외 전략의 한도를
 *  원으로 적으면 목록 상세(20,000 USD)와 설정이 다른 돈을 말합니다. */
export function money(value: string, currency: string): string {
  const text = value.trim()
  if (text === '' || Number.isNaN(Number(text))) return '—'
  return moneyIn(Number(text), currency)
}

/* 본문 두 칸의 크기 규칙. 값을 바꾸면 `strategy.css` 의 `.set-body` 열 정의와
   맞춰야 합니다. */
/** 왼쪽 편집기의 가장 좁은 폭 */
export const MAIN_MIN = 620
/** 오른쪽 칸의 가장 좁은 폭 */
export const SIDE_MIN = 300
/** 두 칸 사이 — 손잡이 8 과 양옆 틈 2 씩 */
export const SPLIT_GUTTER = 12
