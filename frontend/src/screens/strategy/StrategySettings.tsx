import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { contractsOf, frontContractOf } from '../../data/instruments'
import { accountOf, codeOfVersion, currencyOf, productOfVersion, useStrategyCurrency } from '../../data/strategyList'
import { loadOverseasProductInfo, overseasProductInfoEntry } from '../../data/productInfo'
import { caretAfter, currencyCode, currencyDigits, limitTyped, moneyIn } from '../../lib/number'
import { InstrumentPicker } from '../../lib/InstrumentPicker'
import { distanceText, entryWindowText, resetLine, ruleGaps, summarize, summarizeAux } from '../../data/ruleSummary'
import { BacktestCard } from './BacktestCard'
import { useResizableWidth } from '../../lib/useResizableWidth'
import { sessionWindows, useTimetable } from '../../data/session'
import {
  auxCheck,
  auxWhy,
  baseKind,
  clockMinutes,
  EXIT_FIELDS,
  filterWhy,
  windowOutsideWhy,
  type AuxFilter,
  condCheck,
  contextWhy,
  fillWhy,
  numberWhy,
  paramProblems,
  severityKind,
  sideBases,
  whyTone,
  withinWhy,
  type AuxNumber,
  type WhyKind,
} from '../../data/strategyChecks'
import {
  revertCountOf,
  setVersionEdit,
  useStrategyState,
  versionOf,
  type SaveProblem,
  type SaveResult,
} from '../../data/strategyStore'
import type { StrategyVersion } from '../../data/strategyList'
import {
  BASE_BARS,
  CLOCK_ID,
  LEVEL_OPS,
  MOMENT_TITLE,
  NO_PREVIOUS_IDS,
  rightIdsOf,
  TIME_IDS,
  blankCond,
  blankStep,
  condCount,
  EVAL_MODES,
  EXIT_UNITS,
  exitUnitOf,
  FILL_CONDS,
  fillCondFor,
  fillCondMismatch,
  fillCondsFor,
  MARKET_FILL_COND_WHY,
  MAX_CONDS,
  fullLabelOf,
  operandOf,
  operatorOf,
  OPERANDS,
  OPERATORS,
  PICK_OPERANDS,
  needsPriceFor,
  needsStopFor,
  orderTypesFor,
  excludedOrderType,
  excludedOrderTypeWhy,
  PRICE_BASES,
  rightKindOf,
  rightKindsOf,
  RULE_KEYS,
  RULE_LABEL,
  sessionKeyOf,
  sessionsFor,
  type Aux,
  type Cond,
  type Operand,
  type RightKind,
  type Rule,
  type RuleKey,
  type SettingsDraft,
  type Step,
} from '../../data/strategyRules'
import {
  defaultParams,
  isFloatParam,
  PARAM_SPECS,
  resolveOperand,
  sharedGroupOf,
  type Params,
} from '../../data/indicatorOperands'

/* 전략 설정 — 조건 본문 2/3, 보조 1/3.
 *
 * 규칙 넷을 탭으로 나눕니다. 넷을 한 화면에 펼치면 어느 조건이 어느 규칙의
 * 것인지 읽는 데 화면 절반이 듭니다.
 */

interface Props {
  version: StrategyVersion
  draft: SettingsDraft
  onChange: (next: SettingsDraft) => void
  dirty: boolean
  /** 마지막 저장 시도에 서버가 답한 것. **경고와 오류를 갈라 그립니다** —
   *  경고는 저장을 막지 않고 알려만 주고, 오류는 막습니다. 아직 저장을 안
   *  눌렀으면 `null` 입니다. */
  result: SaveResult | null
  /** 아직 목록에 없는 새 버전인가. **저장이 통과해야 목록에 섭니다** — 그
   *  사실을 상단 한 줄이 먼저 말합니다. */
  unsaved: boolean
  onSave: () => void
  /** 「새 버전 저장」. 목록에 다음 버전 초안 행을 만듭니다. */
  onSaveAsNew: () => void
  /** 어느 버전이든 저장하는 중인지. 그동안 「새 버전 저장」을 잠급니다. */
  busy: boolean
  onRevert: () => void
}

/** 견줄 값의 갈래 이름. 「항목」은 첫 칸과 **같은 목록에서 고른다**는 뜻이고,
 *  「숫자」는 직접 친다는 뜻입니다. 「값」·「수」로 두면 열 머리의 「견줄 값」과
 *  「값」이 한 줄에서 두 뜻이 됩니다. */
const KIND_LABEL: Record<RightKind, string> = { operand: '항목', number: '숫자' }

/** 쉼표를 달아 보이는 금액 칸. 담는 값은 쉼표를 뗀 숫자 글자입니다. */
const MONEY_KEYS: readonly AuxNumber[] = ['dailyLoss', 'marginBudget']

/** 서버 말이 **칸 곁에** 서는 보조 설정 칸. 이 칸들의 말은 저장 단추 위 줄에
 *  다시 세우지 않습니다 — 한 말이 두 자리에 서면 고칠 것이 둘로 읽힙니다. 그
 *  밖의 `aux.*` 말은 칸 곁 자리가 없어 저장 단추 위에 섭니다. */
const FIELD_SAID: readonly string[] = [
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
const CONDITION_PATH = /^rules\.[A-Za-z]+\.steps\.\d+\.conds\.\d+(\.left)?$/

/** 단계 사이 유효기간 칸을 가리키는 서버 경로(`rules.{k}.steps.{s}.withinBars`).
 *  이 말은 그 칸 바로 아래 한 자리에 서고 탭 줄 아래 목록에는 서지 않습니다. */
const WITHIN_PATH = /^rules\.[A-Za-z]+\.steps\.\d+\.withinBars$/

/** 그 규칙에서 유효기간이 못 받는 값인 단계의 차례(0부터). */
function withinBadSteps(rule: Rule): number[] {
  return rule.steps.flatMap((_, index) => (withinWhy(rule, index) !== null ? [index] : []))
}

/** 방향마다의 가격 기준 칸. 화면 차례(매수 → 매도)입니다. */
const SIDE_BASES = [
  { key: 'buyPriceBasis', label: '매수 가격', side: '매수' },
  { key: 'sellPriceBasis', label: '매도 가격', side: '매도' },
] as const

/** 「주문 방식」 절의 접힌 줄. **실제로 쓰이는 것만** 적습니다 — 시장가인데 값
 *  기준을 함께 적으면 그 기준이 주문에 실리는 것처럼 읽힙니다. 방향마다 기준을
 *  정했으면 두 방향의 **실제 값**을 적습니다(공통을 따르는 쪽도 그 값으로). */
function orderLine(aux: Aux): string {
  if (!needsPriceFor(aux.orderType)) return aux.orderType
  if (aux.buyPriceBasis === '' && aux.sellPriceBasis === '') return `${aux.orderType} · ${aux.priceBasis}`
  const buy = aux.buyPriceBasis || aux.priceBasis
  const sell = aux.sellPriceBasis || aux.priceBasis
  return `${aux.orderType} · 매수 ${buy} · 매도 ${sell}`
}

/* 못 받은 값이 몇인가. 접힌 아코디언이 이 수를 답니다 — 펴 보지 않고도 손볼
   곳이 남았는지 알 수 있어야 합니다. **저장도 이 수로 막습니다** — 배지만
   달고 저장을 받으면 손절 「abc」가 저장된 값이 됩니다. */
function auxProblems(aux: Aux) {
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
function operandGroups(items: readonly Operand[]): [string, Operand[]][] {
  const made: [string, Operand[]][] = []
  for (const item of items) {
    const held = made.find(([category]) => category === item.category)
    if (held) held[1].push(item)
    else made.push([item.category, [item]])
  }
  return made
}

/** 켜 둔 규칙들을 한 문장으로 — 「매수 진입·매수 청산을 씁니다」. 없으면 그 말. */
function usesLine(rules: Record<RuleKey, { on: boolean }>): string {
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
function saveWhy(problems: ReturnType<typeof auxProblems>, conds: number): string | null {
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
function ruleOf(field: string): RuleKey | null {
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
function problemsForRule(problems: SaveProblem[], key: RuleKey): SaveProblem[] {
  return problems.filter((one) => ruleOf(one.field) === key)
}

/** 그 문제를 탭 줄 아래에 적는 한 줄. **어느 규칙의 어디**인지를 앞에 답니다 —
 *  같은 문구가 규칙마다 서면 어느 것을 고쳐야 하는지 줄에서 갈리지 않습니다. */
function ruleLine(one: SaveProblem): string {
  const key = ruleOf(one.field)
  const place = placeOf(one.field)
  const head = [key ? RULE_LABEL[key] : '', place].filter(Boolean).join(' ')
  return head ? `${head} — ${one.message}` : one.message
}

/** 다 골랐지만 서버가 받지 않는 줄의 수. 저장을 막는 데 씁니다. */
function contextProblems(rule: Rule, daily: boolean): number {
  let count = 0
  for (const step of rule.steps) {
    for (const cond of step.conds) {
      if (fillWhy(cond) === null && contextWhy(cond, daily) !== null) count += 1
    }
  }
  return count
}

/** 다 고르지 않은 조건 행. 규칙 탭 아래 한 줄로 셉니다. */
function condProblems(rule: Rule): number {
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
const nextSeed = () => (seed += 1)

/** 오른쪽 값이 왼쪽과 **매개변수 묶음을 함께 쓰는지**(MACD 선 × 신호, 스토캐스틱
 *  %K × %D). 그러면 오른쪽 칸은 왼쪽 설정을 따르고 잠깁니다 — 서버도 두 쪽이
 *  다르면 받지 않습니다. */
function sharesParams(left: string, right: string): boolean {
  const group = sharedGroupOf(resolveOperand(left).id)
  return group !== null && group.includes(resolveOperand(right).id)
}

/** 잠긴 오른쪽 칸에 마우스를 올리면 서는 말. */
const LOCKED_TITLE = '왼쪽 값의 설정을 따릅니다 — MACD·스토캐스틱끼리는 같은 설정이어야 합니다'

/** 매개변수 칸 하나. **친 글자는 칸이 들고 있고**, 수로 읽히면 수로, 아니면 글자로
 *  조건에 넘깁니다 — 「2.0」을 치는 중에 「2」로 바꿔 쓰지 않으면서, 저장된 값(수)과
 *  같은 수를 치면 조건도 그대로입니다. 밖에서 값이 바뀌면(잠긴 칸이 왼쪽을 따름)
 *  칸 글자도 따라갑니다. */
function ParamInput({
  label,
  value,
  float,
  bad,
  locked,
  name,
  onChange,
}: {
  label: string
  value: number | string | undefined
  float: boolean
  bad: boolean
  locked: boolean
  name: string
  onChange: (next: number | string) => void
}) {
  const shownValue = value === undefined ? '' : String(value)
  const [text, setText] = useState(shownValue)
  useEffect(() => {
    if (text.trim() === '' || Number(text) !== Number(shownValue)) setText(shownValue)
    // 칸 글자는 값이 밖에서 바뀔 때만 맞춥니다. 치는 중의 글자는 그대로 둡니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shownValue])
  return (
    <label className="set-param" title={locked ? LOCKED_TITLE : undefined}>
      <span className="set-param-label">{label}</span>
      <input
        className={`control set-param-input${bad ? ' is-bad' : ''}${locked ? ' is-locked' : ''}`}
        inputMode={float ? 'decimal' : 'numeric'}
        value={locked ? shownValue : text}
        readOnly={locked}
        aria-readonly={locked || undefined}
        aria-invalid={bad || undefined}
        aria-label={name}
        onChange={(event) => {
          if (locked) return
          const next = event.target.value
          setText(next)
          const number = Number(next)
          onChange(next.trim() !== '' && Number.isFinite(number) ? number : next)
        }}
      />
    </label>
  )
}

/** 한도·예산을 적는 말. **통화는 그 전략의 것**입니다 — 해외 전략의 한도를
 *  원으로 적으면 목록 상세(20,000 USD)와 설정이 다른 돈을 말합니다. */
function money(value: string, currency: string): string {
  const text = value.trim()
  if (text === '' || Number.isNaN(Number(text))) return '—'
  return moneyIn(Number(text), currency)
}

/* 본문 두 칸의 크기 규칙. 값을 바꾸면 `strategy.css` 의 `.set-body` 열 정의와
   맞춰야 합니다. */
/** 왼쪽 편집기의 가장 좁은 폭 */
const MAIN_MIN = 620
/** 오른쪽 칸의 가장 좁은 폭 */
const SIDE_MIN = 300
/** 두 칸 사이 — 손잡이 8 과 양옆 틈 2 씩 */
const SPLIT_GUTTER = 12

export function StrategySettings({
  version,
  draft,
  onChange,
  dirty,
  result,
  unsaved,
  onSave,
  onSaveAsNew,
  busy,
  onRevert,
}: Props) {
  const [ruleKey, setRuleKey] = useState<RuleKey>('buyEntry')
  /* 종목 고르개가 열려 있는지. 화면에만 남는 값입니다. */
  const [picking, setPicking] = useState(false)

  /* 이 줄이 가리키는 품목과, 지금 그것이 푸는 월물. **색인이 답합니다** —
     줄에 이름을 적어 두면 만기가 넘어갈 때 이름과 실제 종목이 갈립니다. */
  const product = productOfVersion(version)
  /* 금액의 통화. 해외인데 담긴 코드가 없으면 품목정보의 통화입니다. */
  const currency = useStrategyCurrency(version)
  const months = useMemo(
    () => (product ? contractsOf(product, version.productKind) : []),
    [product, version.productKind],
  )
  /* 「근월 자동」이 지금 무엇을 가리키는지. 자동을 골라 둔 사람도 오늘 어느
     달로 도는지는 알아야 합니다 — 고르개에는 「근월 · 12월물」처럼 짧게 적고,
     연도까지 붙은 이름은 마우스를 올리면 나옵니다(`title`). */
  const frontName = product
    ? (frontContractOf(product, version.productKind)?.label ?? '')
    : ''

  /* 서버가 그 칸에 짚은 말. **칸 옆에 답니다** — 종목은 고르는 자리라 꼬리줄에
     두면 무엇을 고쳐야 하는지가 화면 반대쪽에 섭니다. */
  const problemOf = (field: string) => {
    const one = said.find((item) => item.field === field)
    if (!one) return null
    return (
      <span className={whyTone(severityKind(one.severity))}>
        {one.message}
      </span>
    )
  }
  /* 이 전략이 도는 세션의 창 — 신규 진입 시간이 그 안인지 알리는 데 씁니다. 시간표가
     늦게 오면 그때 다시 셉니다. 국내는 주간·야간, 해외는 1차 거래 창입니다. */
  const timetable = useTimetable()
  const sessionWindow = useMemo(() => {
    if (!product) return null
    const windows = sessionWindows(version.market, product.exchangeNo ?? null, product.code)
    if (windows.length === 0) return null
    if (version.market === 'domestic') return draft.aux.session.includes('야간') ? (windows[1] ?? null) : windows[0]
    return windows[0]
    // 시간표가 오면 다시 셉니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [product, version.market, draft.aux.session, timetable])
  const needsPrice = needsPriceFor(draft.aux.orderType)
  /* 가격 기준 세 칸의 판정 — 칸 아래 줄과 접힌 절의 「고칠 것」이 같은 셈입니다. */
  const bases = useMemo(() => sideBases(draft.aux), [draft.aux])
  const basisWhy = (name: 'priceBasis' | 'buyPriceBasis' | 'sellPriceBasis') =>
    bases.find((one) => one.field === name)?.why ?? null
  /* 쉼표를 다시 단 금액 칸의 커서 자리. 새 글자가 그려진 뒤에 둡니다. */
  const caretAfterRender = useRef<{ input: HTMLInputElement; at: number } | null>(null)
  useLayoutEffect(() => {
    const pending = caretAfterRender.current
    if (!pending) return
    caretAfterRender.current = null
    if (document.activeElement === pending.input) pending.input.setSelectionRange(pending.at, pending.at)
  })
  /* 오른쪽 칸 폭. 끌어 둔 적이 없으면 원래 비율(2:1)대로 섭니다. 왼쪽 편집기는
     MAIN_MIN 아래로 줄지 않으므로, 오른쪽이 넓어질 수 있는 끝은 본문 폭에서
     편집기와 손잡이 자리를 뺀 값입니다. */
  const bodyRef = useRef<HTMLDivElement>(null)
  const asideRef = useRef<HTMLElement>(null)
  const [bodyWidth, setBodyWidth] = useState<number | null>(null)
  useLayoutEffect(() => {
    const body = bodyRef.current
    if (!body) return
    const update = () => setBodyWidth(body.clientWidth)
    update()
    const watch = new ResizeObserver(update)
    watch.observe(body)
    return () => watch.disconnect()
  }, [])
  const side = useResizableWidth({
    key: 'nh.setSideWidth',
    initial: null,
    min: SIDE_MIN,
    max: bodyWidth === null ? SIDE_MIN : bodyWidth - MAIN_MIN - SPLIT_GUTTER,
    edge: 'start',
    measure: () => asideRef.current,
  })
  const [open, setOpen] = useState({
    evaluate: false,
    order: true,
    exit: true,
    filter: false,
    risk: false,
    memo: false,
  })

  const rule = draft.rules[ruleKey]
  const used = condCount(rule)
  const full = used >= MAX_CONDS
  const problems = useMemo(() => auxProblems(draft.aux), [draft.aux])
  /* 일봉이면 시간 값(봉 시작 시각·세션 안 봉 순서)을 쓸 수 없습니다. */
  const daily = draft.baseBar === '일봉'
  /* 다 안 고른 조건은 **네 규칙을 통틀어** 셉니다 — 지금 보고 있는 규칙만
     보면 다른 탭의 빈 줄이 저장까지 갔다가 답으로 되돌아옵니다. */
  const condBad = useMemo(
    /* 되돌리기 칸·단계 유효기간 칸의 못 받는 값과 서버가 받지 않는 짝도 「조건」
       몫으로 셉니다 — 규칙 편집기 안의 칸입니다. */
    () =>
      RULE_KEYS.reduce(
        (sum, key) =>
          sum +
          condProblems(draft.rules[key]) +
          contextProblems(draft.rules[key], daily) +
          (numberWhy(draft.rules[key].resetBars, true, true) === null ? 0 : 1) +
          withinBadSteps(draft.rules[key]).length,
        0,
      ),
    [draft.rules, daily],
  )
  /* 못 받은 값이 하나라도 있으면 저장을 안 받습니다. */
  const blockedWhy = saveWhy(problems, condBad)
  const blocked = blockedWhy !== null
  /* 마지막으로 저장한 것과 같아 「저장」으로 보낼 것이 없는지. 「되돌리기」가
     보는 것과 같은 비교입니다. */
  const nothingToSave = !dirty && !unsaved
  /* 저장을 막는 묶음과 그 수 — 단추 아래 「저장하려면 — 조건 1줄 · 위험 한도 2칸」.
     항목을 누르면 그 묶음으로 갑니다(접혀 있으면 펴고 첫 틀린 칸에 초점). */
  const saveParts: { id: 'cond' | 'order' | 'exit' | 'filter' | 'risk'; text: string }[] = [
    ...(condBad > 0 ? [{ id: 'cond' as const, text: `조건 ${condBad}줄` }] : []),
    ...(problems.order > 0 ? [{ id: 'order' as const, text: `주문 방식 ${problems.order}칸` }] : []),
    ...(problems.exit > 0 ? [{ id: 'exit' as const, text: `청산·수량 ${problems.exit}칸` }] : []),
    ...(problems.filter > 0 ? [{ id: 'filter' as const, text: `실행 필터 ${problems.filter}칸` }] : []),
    ...(problems.risk > 0 ? [{ id: 'risk' as const, text: `위험 한도 ${problems.risk}칸` }] : []),
  ]
  /* 그 묶음으로 갑니다. 조건이면 틀린 줄이 있는 규칙 탭을 열고 그 줄의 첫 칸에,
     보조 설정이면 그 묶음을 펴고 첫 틀린 칸에 초점을 줍니다 — 펴거나 탭을 바꾼
     화면이 선 다음에 찾습니다(그 전에는 칸이 없습니다). */
  function goToProblem(id: 'cond' | 'order' | 'exit' | 'filter' | 'risk') {
    if (id === 'cond') {
      const key =
        RULE_KEYS.find(
          (one) =>
            condProblems(draft.rules[one]) +
              contextProblems(draft.rules[one], daily) +
              (numberWhy(draft.rules[one].resetBars, true, true) === null ? 0 : 1) +
              withinBadSteps(draft.rules[one]).length >
            0,
        ) ?? ruleKey
      setRuleKey(key)
      setTimeout(() => {
        const row = document.querySelector('.set-cond-why')?.closest('.set-cond') ?? document.querySelector('.set-within-why')?.closest('.set-step')
        const target = row?.querySelector<HTMLElement>('select, input')
        target?.scrollIntoView({ block: 'center' })
        target?.focus()
      }, 0)
      return
    }
    setOpen((had) => ({ ...had, [id]: true }))
    setTimeout(() => {
      const target = document.querySelector<HTMLElement>(`[data-acc="${id}"] [aria-invalid="true"]`)
      target?.scrollIntoView({ block: 'center' })
      target?.focus()
    }, 0)
  }
  /* 이 버전으로 **끝나지 않은 실행**(검증·진행 한 목록). 실행은 시작할 때의 설정을
     들고 돌아, 여기서 저장해도 그 실행은 바뀌지 않습니다 — 그 사실을 저장 전에
     말합니다. */
  const liveRuns = useStrategyState().verify.runs.filter(
    (run) => run.version === version.id && run.state !== 'ended',
  ).length
  /* 요약 문단은 **저장될 수 있는 값만** 문장으로 말합니다. 저장을 막는 값은 칸
     아래 판정 줄과 같은 판정(`strategyChecks.ts`)으로 문장에서 빠지고, 그 자리가
     「아직 정하지 않음」에 섭니다(`ruleGaps`·`summarizeAux`). */
  const lines = useMemo(
    () =>
      summarize(rule, ruleKey, {
        baseBar: draft.baseBar,
        evalMode: draft.evalMode,
        currency: currency,
      }),
    [rule, ruleKey, draft.baseBar, draft.evalMode, currency],
  )
  const gaps = useMemo(
    () => ruleGaps(rule, ruleKey, { baseBar: draft.baseBar, evalMode: draft.evalMode, currency: currency }),
    [rule, ruleKey, draft.baseBar, draft.evalMode, currency],
  )
  /* 서버가 마지막 저장에 답한 것. 값이 바뀌면 저장소가 지우므로, 여기 남아
     있는 동안에는 지금 화면의 값에 대한 답입니다. */
  const said = result?.problems ?? []
  /* 규칙에 걸린 말은 **탭에 붙습니다** — 배지로 세고 탭 줄 아래에 규칙 이름과
     자리를 붙여 한 줄씩. 요약 끝에는 전략 전체의 말만 섭니다. */
  /* 규칙의 되돌리기 칸(`rules.{key}.resetBars`)에 단 말은 **그 칸 바로 아래
     한 자리**에만 섭니다 — 칸을 비우면 풀리는 말이라 칸 곁이 할 일과 붙어
     있습니다. 탭 배지의 셈은 위 `tabBadge` 가 정합니다. */
  /* 규칙 탭 배지의 수. 서버가 그 규칙에 단 말을 세되, **되돌리기 칸의 경고는
     빼고**(저장을 막지 않는 말이라 칸 아래 한 자리로 충분합니다), 되돌리기 칸의
     못 받는 값은 화면 판정으로도 셉니다 — 서버 말과 같은 칸이면 한 번만. */
  const tabBadge = (key: RuleKey) => {
    /* 조건 줄 하나에 단 서버 말은 **그 줄 아래**에 서고 탭 목록에도 없어, 배지에서도
       뺍니다 — 목록과 배지가 같은 것을 셉니다. */
    const server = problemsForRule(said, key).filter(
      (one) =>
        !(one.field.endsWith('.resetBars') && one.severity === 'warning') &&
        !CONDITION_PATH.test(one.field),
    )
    const resetBad =
      numberWhy(draft.rules[key].resetBars, true, true) !== null &&
      !server.some((one) => one.field.endsWith('.resetBars'))
    /* 유효기간 칸도 되돌리기 칸과 같습니다 — 화면 판정을 세되, 같은 칸에 서버
       말이 이미 있으면 한 번만 셉니다. */
    const withinBad = withinBadSteps(draft.rules[key]).filter(
      (index) => !server.some((one) => one.field === `rules.${key}.steps.${index}.withinBars`),
    ).length
    return {
      count: server.length + (resetBad ? 1 : 0) + withinBad,
      bad: resetBad || withinBad > 0 || server.some((one) => one.severity === 'error'),
    }
  }
  const ruleSaid = useMemo(
    () =>
      said.filter(
        (one) =>
          ruleOf(one.field) !== null &&
          !one.field.endsWith('.resetBars') &&
          !CONDITION_PATH.test(one.field) &&
          !WITHIN_PATH.test(one.field),
      ),
    [said],
  )
  /* 서버가 **조건 줄 하나**에 단 말. 그 줄 아래 판정 자리에 섭니다 — 탭 줄 아래
     목록에 「매수 진입 단계 1 조건 2 — …」로 세우면 고칠 줄을 한 번 더 찾아야
     합니다. 일봉의 시간 값은 서버가 왼쪽 칸(`….left`)에 달아도 같은 줄입니다. */
  const condSaid = (key: RuleKey, step: number, cond: number) => {
    const base = `rules.${key}.steps.${step}.conds.${cond}`
    const one = said.find((item) => item.field === base || item.field === `${base}.left`)
    return one ?? null
  }
  /* 전략이 도는 세션이 국내 야간인지. 봉 시작 시각은 야간에 자정을 넘어 이어 셉니다. */
  const nightSession = sessionKeyOf(version.market, draft.aux.session) === 'domestic-night'
  /* 칸에도 규칙에도 안 붙는 말. **갈래는 severity 가 정합니다** — 오류는 막는
     말이라 꼬리줄에, 경고는 알려 주는 말이라 요약 끝에 섭니다.
     보조 설정(`aux.*`)에 달린 말도 여기 섭니다. 칸 옆의 판정은 화면이 서버와 같은
     규칙으로 먼저 하지만, 그래도 서버가 막았다면 그 말이 **어디에도 안 서고
     사라지면 안 됩니다.** */
  const loose = useMemo(
    () =>
      said.filter(
        (one) =>
          one.field !== 'rules' && ruleOf(one.field) === null && !FIELD_SAID.includes(one.field),
      ),
    [said],
  )
  const warnings = useMemo(
    () => [
      /* 전략 전체에 걸린 말. 어느 규칙 하나의 문제가 아니라 규칙이 통째로
         없다는 말이라 규칙 탭이 아니라 요약 끝이 그 자리입니다. */
      ...said.filter((one) => one.field === 'rules'),
      ...loose.filter((one) => one.severity === 'warning'),
    ],
    [said, loose],
  )
  const looseErrors = useMemo(() => loose.filter((one) => one.severity === 'error'), [loose])

  /* 규칙 뒤에 이어 붙는 보조 설정 문장. **한 상자 이어지는 글**이라 규칙과 같은
     자리에 섭니다 — 라벨로 가르지 않고 주어(「이 전략은」)가 범위를 말합니다. */
  const aux = useMemo(
    () =>
      summarizeAux(draft.aux, version.market, (value) => money(value, currency)),
    [draft.aux, version.market, currency],
  )
  /* 「아직 정하지 않음」의 차례: 이 규칙의 조건 줄(단계 → 줄) → 되돌리기 → 보조 설정. */
  const missing = [...gaps, ...aux.missing]

  const patch = (part: Partial<SettingsDraft>) => onChange({ ...draft, ...part })
  const setAux = (part: Partial<Aux>) => patch({ aux: { ...draft.aux, ...part } })
  /* 주문유형을 바꾸면 체결조건도 그 유형이 받는 값으로 맞춥니다 — 시장가로 바꿨는데
     FAK 가 남아 있으면 저장이 막힙니다. 체결조건은 국내 주문에만 있습니다. */
  const setOrderType = (orderType: string) =>
    setAux(
      version.market === 'domestic'
        ? { orderType, fillCond: fillCondFor(orderType, draft.aux.fillCond) }
        : { orderType },
    )
  const setRule = (next: Rule) => patch({ rules: { ...draft.rules, [ruleKey]: next } })
  /* 켜고 끄는 것은 **보고 있지 않은 탭에도** 겁니다 — 배지가 네 탭에 다 서
     있어, 누르려면 먼저 그 탭으로 옮겨야 한다면 배지를 거기 둘 까닭이 없습니다. */
  const toggleRule = (key: RuleKey) =>
    patch({ rules: { ...draft.rules, [key]: { ...draft.rules[key], on: !draft.rules[key].on } } })
  const setSteps = (steps: Step[]) => setRule({ ...rule, steps })

  const editStep = (stepId: string, part: Partial<Step>) =>
    setSteps(rule.steps.map((step) => (step.id === stepId ? { ...step, ...part } : step)))

  const editCond = (stepId: string, condId: string, part: Partial<Cond>) =>
    setSteps(
      rule.steps.map((step) =>
        step.id === stepId
          ? {
              ...step,
              conds: step.conds.map((cond) => (cond.id === condId ? { ...cond, ...part } : cond)),
            }
          : step,
      ),
    )

  /* 왼쪽 값을 바꾸면 연산자와 값 칸이 그 값이 받을 수 있는 것으로 갈립니다.
     남겨 두면 「거래량 상향 교차」처럼 뜻이 없는 줄이 남습니다. */
  function pickLeft(stepId: string, condId: string, left: string) {
    const ops = operandOf(left)?.ops ?? []
    const found = operatorOf(ops[0] ?? '')
    const kind = found ? (rightKindsOf(found, left)[0] ?? 'operand') : 'operand'
    editCond(stepId, condId, {
      left,
      leftParams: defaultParams(left),
      op: ops[0] ?? '',
      rightKind: kind,
      right: '',
      rightParams: undefined,
    })
  }

  /* 오른쪽 값을 고르면 그 값의 매개변수가 기본값으로 섭니다. 왼쪽과 묶음을 함께
     쓰는 값이면 왼쪽 설정을 그대로 받습니다. */
  function pickRight(stepId: string, condId: string, cond: Cond, right: string) {
    const params = sharesParams(cond.left, right)
      ? { ...(resolveOperand(cond.left, cond.leftParams).params ?? {}) }
      : defaultParams(right)
    editCond(stepId, condId, { right, rightParams: params })
  }

  /* 매개변수 한 칸을 고칩니다. 오른쪽이 왼쪽을 따르는 짝이면 오른쪽도 같이 바뀝니다. */
  function setParam(stepId: string, cond: Cond, side: 'left' | 'right', key: string, value: number | string) {
    const own: Params = { ...((side === 'left' ? cond.leftParams : cond.rightParams) ?? {}), [key]: value }
    if (side === 'right') {
      editCond(stepId, cond.id, { rightParams: own })
      return
    }
    const follows = cond.rightKind === 'operand' && cond.right !== '' && sharesParams(cond.left, cond.right)
    editCond(stepId, cond.id, follows ? { leftParams: own, rightParams: { ...own } } : { leftParams: own })
  }

  /* 값 칸 아래의 매개변수 칸들. 매개변수가 없는 값이면 아무것도 안 그립니다. */
  function paramFields(stepId: string, cond: Cond, side: 'left' | 'right', index: number) {
    const id = side === 'left' ? cond.left : cond.right
    const resolved = resolveOperand(id, side === 'left' ? cond.leftParams : cond.rightParams)
    const spec = PARAM_SPECS[resolved.id]
    if (!spec || !resolved.params) return null
    const locked = side === 'right' && sharesParams(cond.left, cond.right)
    const bad = new Set(paramProblems(cond).filter((one) => one.side === side).map((one) => one.key))
    const where = side === 'left' ? '값' : '견줄 값'
    return (
      <span className={`set-params set-params-${side}`}>
        {spec.map((one) => (
          <ParamInput
            key={one.key}
            label={one.label}
            name={`조건 ${index + 1} ${where} ${one.label}`}
            value={resolved.params![one.key]}
            float={isFloatParam(one.key)}
            bad={bad.has(one.key)}
            locked={locked}
            onChange={(next) => setParam(stepId, cond, side, one.key, next)}
          />
        ))}
      </span>
    )
  }

  /* 연산자를 바꾸면 값 칸도 그 연산자가 받는 첫 갈래로 돌아갑니다 —
     「숫자」 갈래로 둔 채 교차로 바꾸면 견줄 선이 없는 줄이 남습니다. */
  function pickOp(stepId: string, condId: string, op: string, left: string) {
    const found = operatorOf(op)
    const kind = found ? (rightKindsOf(found, left)[0] ?? 'operand') : 'operand'
    editCond(stepId, condId, { op, rightKind: kind, right: '', rightParams: undefined })
  }

  function addCond(stepId: string) {
    if (full) return
    setSteps(
      rule.steps.map((step) =>
        step.id === stepId ? { ...step, conds: [...step.conds, blankCond(nextSeed())] } : step,
      ),
    )
  }

  function dropCond(stepId: string, condId: string) {
    setSteps(
      rule.steps
        .map((step) =>
          step.id === stepId
            ? { ...step, conds: step.conds.filter((cond) => cond.id !== condId) }
            : step,
        )
        /* 조건이 하나도 없는 단계는 남겨 두지 않습니다 — 빈 관문은 늘
           통과하므로 없는 것과 같습니다. */
        .filter((step) => step.conds.length > 0),
    )
  }

  function addStep() {
    if (full) return
    setSteps([...rule.steps, blankStep(nextSeed())])
  }

  function dropStep(stepId: string) {
    setSteps(rule.steps.filter((step) => step.id !== stepId))
  }

  const limitWhy = full ? `조건은 규칙마다 ${MAX_CONDS}개까지입니다` : ''

  function condRow(step: Step, cond: Cond, index: number, stepIndex: number) {
    const left = operandOf(cond.left)
    const op = operatorOf(cond.op)
    /* 저장된 줄이 이 값에 없는 연산자·값을 들고 있으면(다른 곳에서 만든 설정)
       그 값을 **그대로 한 줄 더** 세웁니다 — 목록 첫 줄이 대신 서면 판정 줄이
       말하는 줄과 칸이 보여 주는 줄이 달라집니다. 다시 고르는 선택지는 아닙니다. */
    const ops = left
      ? OPERATORS.filter((item) => left.ops.includes(item.id) || (item.id === cond.op && !!op))
      : []
    /* 값 칸이 지금 무엇을 받고 있는가. 넷(초과·미만·이상·이하)은 값과 수를 다
       받으므로 조건 줄이 그 갈래를 들고 다닙니다(규격 §9 ⑥). */
    const kind = op ? rightKindOf(op, cond) : 'operand'
    const kinds = op ? rightKindsOf(op, cond.left) : []
    /* 값 갈래의 오른쪽 목록은 **왼쪽이 정합니다** — 호가는 다른 쪽 호가만,
       그 밖의 값은 호가·시간·보유를 받지 않습니다(`rightIdsOf`). */
    const rightIds = op?.operand ? rightIdsOf(op, cond.left) : []
    const rights = [
      ...PICK_OPERANDS.filter((item) => rightIds.includes(item.id) || item.id === cond.right),
      ...OPERANDS.filter((item) => item.legacy && item.id === cond.right),
    ]
    /* 봉 시작 시각의 오른쪽은 수가 아니라 「HH:MM」 글자입니다. */
    const clock = cond.left === CLOCK_ID
    /* 아직 안 고른 칸이 있으면 **그 줄에서** 말합니다 — 규칙 바의 수는 몇 줄이
       남았는지만 알려 주고 어느 줄인지는 말하지 않습니다.
       줄을 물들이거나 테두리를 두르지 않습니다: 아직 안 채운 것은 틀린 것이
       아니라 **하다 만 것**이고, 그 무게는 번호 칸과 한 줄이면 충분합니다.
       다 골랐는데 서버가 받지 않는 짝이면 그 까닭이 같은 자리에 섭니다. 화면
       판정이 없을 때만 서버가 그 줄에 단 말이 섭니다 — 한 자리에 두 말이
       서지 않습니다. */
    const check = condCheck(cond, daily)
    const why = check?.text ?? null
    const said = why ? null : condSaid(ruleKey, stepIndex, index)
    /* 야간 세션 전략의 시각 줄에는 셈법 한 줄. 판정 줄이 서면 그것이 먼저입니다. */
    const nightHelp = clock && !why && !said && nightSession
    /* 1단계의 상태 조건(이상·이하·초과·미만·같음)은 **바뀌는 순간**에만 걸립니다 —
       모드를 고르는 칸이 아니라 지금 판정이 그렇다는 표기입니다. 호가·보유·시각은
       직전 값이 없을 수 있어 그 말을 함께 적습니다. */
    const moment = stepIndex === 0 && LEVEL_OPS.includes(cond.op)
    return (
      <div className="set-cond" key={cond.id}>
        <span className={`set-cond-no${check ? ` ${whyTone(check.kind)}` : ''}`}>{index + 1}</span>

        {/* 줄에는 이름표가 없습니다 — 표 위의 열 머리가 세 칸의 이름을 한 번만
            말합니다. 고른 값이 어느 범주인지는 목록의 묶음이 말합니다. */}
        <label className="set-field">
          {/* 셀렉트에는 짧은 이름이 서고, 온 이름(「MACD 신호(DEA)」)은 마우스 글입니다. */}
          <select
            className="control"
            value={cond.left}
            title={fullLabelOf(cond.left)}
            onChange={(event) => pickLeft(step.id, cond.id, event.target.value)}
          >
            <option value="">고르기</option>
            {operandGroups([
              ...PICK_OPERANDS.filter((item) => item.ops.length > 0),
              ...OPERANDS.filter((item) => item.legacy && item.id === cond.left),
            ]).map(
              ([category, items]) => (
                <optgroup key={category} label={category}>
                  {/* 일봉이면 시간 값은 보이되 못 고릅니다 — 이미 골라 둔 줄은
                      판정 줄이 말합니다. */}
                  {items.map((item) => (
                    <option key={item.id} value={item.id} disabled={daily && TIME_IDS.includes(item.id)}>
                      {item.label}
                    </option>
                  ))}
                </optgroup>
              ),
            )}
          </select>
        </label>

        <label className="set-field">
          <select
            className="control"
            value={cond.op}
            disabled={!left}
            onChange={(event) => pickOp(step.id, cond.id, event.target.value, cond.left)}
          >
            <option value="">고르기</option>
            {ops.map((item) => (
              <option key={item.id} value={item.id} disabled={!left?.ops.includes(item.id)}>
                {item.label}
              </option>
            ))}
          </select>
        </label>

        {/* **견줄 값의 갈래는 제 열입니다.** 값 칸 안에 끼워 두면 같은 자리가 줄마다
            다른 구성이 되고, 값을 치다가 갈래를 바꾸려면 칸 안을 다시 봐야 합니다.
            - 조건을 아직 안 골랐으면 빈 칸입니다 — 무엇을 받을지는 조건이 정합니다.
            - 갈래가 둘이면 고르는 칸, 하나뿐이면 그 이름을 **같은 폭의 글자**로
              세웁니다. 못 쓰는 셀렉트를 세우지 않으면서 칸 구성은 줄마다 같게
              둡니다.
            갈래를 바꾸면 값은 비웁니다 — 앞 갈래의 값은 새 갈래에서 뜻이 없습니다. */}
        {!op ? (
          <span className="set-kind-one" aria-hidden="true" />
        ) : kinds.length > 1 ? (
          <select
            className="control set-kind"
            aria-label={`조건 ${index + 1} 견줄 값 갈래`}
            value={kind}
            onChange={(event) =>
              editCond(step.id, cond.id, {
                rightKind: event.target.value === 'number' ? 'number' : 'operand',
                right: '',
                rightParams: undefined,
              })
            }
          >
            <option value="operand">{KIND_LABEL.operand}</option>
            <option value="number">{KIND_LABEL.number}</option>
          </select>
        ) : (
          /* 봉 시작 시각은 「HH:MM」 글자로 견주어 갈래 이름이 「시각」입니다. */
          <span className="set-kind-one">{clock ? '시각' : KIND_LABEL[kind]}</span>
        )}

        <label className="set-field">
          {kind === 'number' ? (
            /* 시각은 글자 칸입니다 — 치는 중인 「9:」 같은 상태를 지우지 않고, 저장도
               적은 그대로(「09:30」) 나갑니다. */
            <input
              className="control set-num"
              inputMode={clock ? 'text' : 'decimal'}
              placeholder={clock ? '09:30' : undefined}
              value={cond.right}
              aria-label={clock ? `조건 ${index + 1} 견줄 시각` : `조건 ${index + 1} 견줄 숫자`}
              onChange={(event) => editCond(step.id, cond.id, { right: event.target.value })}
            />
          ) : (
            <select
              className="control"
              value={cond.right}
              title={fullLabelOf(cond.right)}
              disabled={!op}
              onChange={(event) => pickRight(step.id, cond.id, cond, event.target.value)}
            >
              <option value="">고르기</option>
              {operandGroups(rights).map(([category, items]) => (
                <optgroup key={category} label={category}>
                  {items.map((item) => (
                    <option key={item.id} value={item.id} disabled={!rightIds.includes(item.id)}>
                      {item.label}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          )}
        </label>

        <button
          type="button"
          className="btn btn-quiet set-drop"
          aria-label={`조건 ${index + 1} 지우기`}
          onClick={() => dropCond(step.id, cond.id)}
        >
          ✕
        </button>

        {/* 지표의 매개변수 칸은 **셀렉트 줄 바로 아래 한 줄**입니다 — 값 칸 폭 안에
            넣으면 칸이 하나씩 세로로 쌓입니다. 왼쪽 값의 칸은 값·조건 열 아래,
            견줄 값의 칸은 견줄 값 열 아래에 섭니다. */}
        {paramFields(step.id, cond, 'left', index)}
        {kind === 'operand' && cond.right !== '' && paramFields(step.id, cond, 'right', index)}

        {check && <p className={`set-cond-why ${whyTone(check.kind)}`}>{check.text}</p>}
        {said && <p className={`set-cond-why ${whyTone(severityKind(said.severity))}`}>{said.message}</p>}
        {nightHelp && (
          <p className="set-cond-why set-cond-help">야간은 자정을 넘어 이어 셉니다 — 01:00 은 23:00 뒤</p>
        )}
        {moment && (
          <p className="set-cond-why set-cond-help set-cond-moment" title={MOMENT_TITLE}>
            바뀌는 순간
            {NO_PREVIOUS_IDS.includes(cond.left) && ' · 직전 값이 없으면 바뀐 것으로 치지 않습니다'}
          </p>
        )}
      </div>
    )
  }

  function stepCard(step: Step, index: number) {
    const last = index === rule.steps.length - 1
    /* 유효기간 칸의 판정. 화면 판정이 먼저이고, 없으면 서버가 이 칸에 단 말입니다 —
       같은 말이 칸 아래 두 번 서지 않습니다. */
    const withinSaid = (() => {
      const why = withinWhy(rule, index)
      return {
        why,
        server: why ? null : problemOf(`rules.${ruleKey}.steps.${index}.withinBars`),
        id: `set-within-why-${step.id}`,
      }
    })()
    return (
      <section className="set-step" key={step.id}>
        <div className="set-step-head">
          <span className="set-step-no">{index + 1}</span>
          <div className="set-step-titles">
            <h3 className="set-step-title">{index + 1}단계</h3>
            {/* 선택기는 **단계마다 하나**입니다. 행마다 AND/OR 를 또 두면
                같은 뜻을 두 곳에서 정하게 됩니다. */}
            <select
              className="control set-join"
              value={step.join}
              aria-label={`${index + 1}단계 조건 잇는 방법`}
              onChange={(event) => editStep(step.id, { join: event.target.value as Step['join'] })}
            >
              <option value="all">모두 충족</option>
              <option value="any">하나 이상</option>
            </select>
            {/* 2단계부터는 앞 단계가 정한 창 안에서 **처음 참**이 되면 넘어갑니다. */}
            {index > 0 && (
              <span className="set-step-moment">{rule.steps[index - 1].withinBars}봉 안에 처음 참</span>
            )}
          </div>

          {/* 유효기간은 **다음 단계까지**의 값이라 마지막 단계에는 없습니다. */}
          {!last && (
            <label className="set-within">
              다음 봉부터
              <input
                className={`control set-num${withinSaid.why ? ' is-bad' : ''}`}
                inputMode="numeric"
                value={String(step.withinBars)}
                aria-label={`${index + 1}단계 다음 단계 유효기간(봉)`}
                aria-invalid={withinSaid.why ? true : undefined}
                aria-describedby={withinSaid.why || withinSaid.server ? withinSaid.id : undefined}
                onChange={(event) =>
                  editStep(step.id, { withinBars: Number(event.target.value) || 0 })
                }
              />
              봉 이내
            </label>
          )}

          <button
            type="button"
            className="btn btn-quiet set-drop"
            aria-label={`${index + 1}단계 지우기`}
            onClick={() => dropStep(step.id)}
          >
            ✕
          </button>

          {/* 유효기간 칸의 판정 줄. 머리 줄 바로 아래 한 줄이고 오른쪽 끝을 칸에
              맞춥니다 — 머리가 굴러도 붙어 있는 자리라 칸과 까닭이 갈라지지 않습니다. */}
          {withinSaid.why && (
            <p id={withinSaid.id} className={`set-within-why ${whyTone('wrong')}`}>
              {withinSaid.why}
            </p>
          )}
          {withinSaid.server && (
            <p id={withinSaid.id} className="set-within-why">
              {withinSaid.server}
            </p>
          )}
        </div>

        {/* 열 머리 한 줄 — **줄마다 붙던 이름표를 여기로 모읍니다.** 조건이
            늘어날수록 같은 이름표가 줄 수만큼 되풀이되어, 읽을 것은 값인데
            눈에 먼저 들어오는 것이 이름표가 됩니다. 머리와 조건 줄은 스타일의
            **같은 격자 변수 하나**를 읽습니다 — 따로 적으면 한쪽만 고쳤을 때
            머리와 칸이 어긋나 이름이 옆 칸을 가리킵니다.
            줄이 하나도 없으면 세우지 않습니다: 머리만 선 표는 빈 표와 다릅니다. */}
        {step.conds.length > 0 && (
          <div className="set-cond-head" aria-hidden="true">
            <span />
            <span>값</span>
            <span>조건</span>
            {/* 「견줄 값」은 갈래 열과 값 열 **둘을 덮습니다** — 갈래는 그 값의
                모양이지 따로 이름을 붙일 값이 아닙니다. */}
            <span className="set-cond-head-wide">견줄 값</span>
            <span />
          </div>
        )}
        <div className="set-conds">{step.conds.map((cond, i) => condRow(step, cond, i, index))}</div>

        <button
          type="button"
          className="btn btn-quiet set-add"
          aria-disabled={full}
          aria-describedby={full ? 'set-limit' : undefined}
          onClick={() => addCond(step.id)}
        >
          + 조건 추가
        </button>
      </section>
    )
  }

  function accordion(
    id: keyof typeof open,
    title: string,
    summary: string,
    count: number,
    body: React.ReactNode,
  ) {
    return (
      <section className="card set-acc" data-acc={id}>
        <button
          type="button"
          className="set-acc-head"
          aria-expanded={open[id]}
          aria-label={`${title} ${open[id] ? '접기' : '펼치기'}`}
          onClick={() => setOpen({ ...open, [id]: !open[id] })}
        >
          <span className="set-acc-title">{title}</span>
          {/* 접혀 있어도 무엇으로 정해졌는지와 손볼 곳이 몇인지 보입니다. 펴면
              칸 아래 줄이 어느 칸인지 가리키므로 배지는 접혔을 때만 섭니다. */}
          {!open[id] && (
            <span className="set-acc-sum" title={summary}>
              {summary}
            </span>
          )}
          {!open[id] && count > 0 && <span className="badge badge-warn set-acc-bad">고칠 것 {count}</span>}
          <span className="set-acc-mark">{open[id] ? '⌃' : '⌄'}</span>
        </button>
        {open[id] && <div className="set-acc-body">{body}</div>}
      </section>
    )
  }

  const field = (label: string, node: React.ReactNode) => (
    <label className="set-row" key={label}>
      <span className="set-row-label">{label}</span>
      {node}
    </label>
  )
  /* 이름을 위에 두는 줄 — 칸이 여럿이라 한 줄에 이름과 함께 못 서는 자리(신규 진입 시간). */
  const stacked = (label: string, node: React.ReactNode) => (
    <div className="set-row set-row-stack" key={label}>
      <span className="set-row-label">{label}</span>
      {node}
    </div>
  )

  const select = (value: string, list: string[], set: (v: string) => void, label: string) => (
    <select className="control" value={value} aria-label={label} onChange={(e) => set(e.target.value)}>
      {/* 저장된 값이 비어 있으면 **빈 채로** 보입니다 — 목록 첫 값이 대신 서면
          고르지 않은 값이 고른 것처럼 읽힙니다. 다시 비우는 선택지는 아닙니다. */}
      {value === '' && !list.includes('') && (
        <option value="" disabled>
          —
        </option>
      )}
      {list.map((item) => (
        <option key={item} value={item}>
          {item}
        </option>
      ))}
    </select>
  )

  /* 수 칸. 못 받는 값이면 테두리가 그 칸을 가리키고 까닭은 칸 아래 한 줄이
     말합니다(주문 화면의 가격 칸과 같은 규칙). 값을 조용히 되돌리지 않습니다 —
     되돌리면 틀린 값이 정상인 얼굴로 남습니다. */
  const unit = (
    name: string,
    key: AuxNumber,
    suffix: string,
    label: string,
    /* 비워 둘 수 있는 칸(추적 청산·연속 손실)의 빈칸 글자. `field` 는 서버가 이
       칸에 단 말을 찾는 이름입니다 — 화면 판정이 없을 때만 그 말이 칸 아래 섭니다.
       받는 값의 규칙(정수·비움)은 `AUX_NUMBERS` 가 정합니다. */
    extra?: { placeholder?: string; field?: string },
  ) => {
    const raw = draft.aux[key] ?? ''
    /* 금액 칸(하루 손실 한도·증거금 예산)은 **보이기만** 쉼표를 답니다 — 설정에 담는
       값은 쉼표를 뗀 숫자 글자라 판정·저장은 그대로입니다. */
    const money = MONEY_KEYS.includes(key)
    const digits = currencyDigits(currencyCode(currency)) ?? 2
    const value = money ? limitTyped(raw, digits) : raw
    const set = (v: string) => setAux({ [key]: v })
    const check = auxCheck(draft.aux, key)
    const why = check?.text ?? null
    const server = !why && extra?.field ? problemOf(extra.field) : null
    const whyId = `set-why-${name}`
    return (
      <span className="set-bad">
        <span className="set-unit">
          {/* 붉은 테는 **틀린 값**에만 둡니다. 비워 둔 필수 칸은 아래 줄(경고색)이
              할 일을 말하고, 칸은 틀린 것이 아니라 테를 두르지 않습니다. */}
          <input
            className={`control set-num${check?.kind === 'wrong' ? ' is-bad' : ''}`}
            inputMode="numeric"
            value={value}
            placeholder={extra?.placeholder}
            aria-label={label}
            aria-invalid={why ? true : undefined}
            aria-describedby={why || server ? whyId : undefined}
            onChange={(e) => {
              if (!money) {
                set(e.target.value)
                return
              }
              /* 쉼표를 다시 달아도 커서는 고치던 자리에 머뭅니다 — 커서 앞의 숫자 수를
                 세어 두었다가 새 글자에서 같은 수만큼 지난 곳에 둡니다. */
              const input = e.target
              const before = input.value.slice(0, input.selectionStart ?? input.value.length)
              const count = (before.match(/[0-9.]/g) ?? []).length
              const shown = limitTyped(input.value, digits)
              caretAfterRender.current = { input, at: caretAfter(shown, count) }
              set(shown.replace(/,/g, ''))
            }}
          />
          <span className="set-unit-mark">{suffix}</span>
        </span>
        {check && (
          <span id={whyId} className={whyTone(check.kind)}>
            {check.text}
          </span>
        )}
        {server && <span id={whyId}>{server}</span>}
      </span>
    )
  }

  /* 거리 칸(손절·익절·추적 청산) — 수 칸 뒤에 단위 셀렉트입니다. 단위를 바꾸면 그
     단위의 범위로 곧바로 판정합니다(`auxWhy`). ATR 배를 고르면 칸 옆에 무엇의 배수인지
     적습니다. 서버 말은 값 칸·단위 칸 어느 쪽에 달려도 그 칸 아래 섭니다. */
  const distance = (
    name: string,
    key: 'stopTicks' | 'takeTicks' | 'trailTicks',
    unitKey: 'stopUnit' | 'takeUnit' | 'trailUnit',
    label: string,
    extra?: { placeholder?: string },
  ) => {
    const value = draft.aux[key] ?? ''
    const chosen = exitUnitOf(draft.aux[unitKey])
    const check = auxCheck(draft.aux, key)
    const why = check?.text ?? null
    const server = !why ? (problemOf(`aux.${key}`) ?? problemOf(`aux.${unitKey}`)) : null
    const whyId = `set-why-${name}`
    return (
      <span className="set-bad">
        <span className="set-unit">
          <input
            className={`control set-num set-distance${check?.kind === 'wrong' ? ' is-bad' : ''}`}
            inputMode={chosen === 'tick' ? 'numeric' : 'decimal'}
            value={value}
            placeholder={extra?.placeholder}
            aria-label={label}
            title={chosen === 'price' ? '평균가에서 떨어진 가격 거리(포인트)' : undefined}
            aria-invalid={why ? true : undefined}
            aria-describedby={why || server ? whyId : undefined}
            onChange={(e) => setAux({ [key]: e.target.value })}
          />
          <select
            className="control set-distance-unit"
            value={chosen}
            aria-label={`${label} 단위`}
            onChange={(e) => setAux({ [unitKey]: e.target.value })}
          >
            {EXIT_UNITS.map((one) => (
              <option key={one.id} value={one.id}>
                {one.label}
              </option>
            ))}
          </select>
          {/* 자리는 늘 잡아 둡니다 — ATR 배를 고른 줄만 칸이 밀리면 세 줄의 칸이 어긋납니다.
              값이 빈 칸은 그 청산을 쓰지 않으므로 ATR 도 쓰지 않습니다. 그때는 꼬리표를
              흐리게 둡니다. */}
          <span
            className={`set-unit-note${chosen === 'atr' ? '' : ' is-off'}${value.trim() === '' ? ' is-idle' : ''}`}
            aria-hidden={chosen !== 'atr'}
          >
            ATR(14)
          </span>
        </span>
        {check && (
          <span id={whyId} className={whyTone(check.kind)}>
            {check.text}
          </span>
        )}
        {server && <span id={whyId}>{server}</span>}
      </span>
    )
  }

  /* 실행 조건 칸(분·시각·봉·번). 판정은 `filterWhy` 하나이고, 화면 판정이 없을 때만 서버
     말이 칸 아래 섭니다. 비워 둘 수 있는 칸은 자리표시가 그 뜻을 말합니다. */
  const filterInput = (
    key: AuxFilter,
    label: string,
    options: { placeholder?: string; clock?: boolean; className?: string; disabled?: boolean },
  ) => {
    const why = filterWhy(draft.aux, key)
    return (
      <input
        className={`control ${options.className ?? 'set-filter-num'}${why ? ' is-bad' : ''}`}
        inputMode={options.clock ? 'text' : 'numeric'}
        value={draft.aux[key] ?? ''}
        placeholder={options.placeholder}
        aria-label={label}
        aria-invalid={why ? true : undefined}
        disabled={options.disabled}
        onChange={(e) => setAux({ [key]: e.target.value })}
      />
    )
  }
  /* 실행 조건 칸 아래 판정 줄 — 화면 판정, 없으면 서버 말. */
  const filterSaid = (keys: AuxFilter[]) => {
    for (const key of keys) {
      const why = filterWhy(draft.aux, key)
      if (why) return <span className="set-bad-why">{why}</span>
    }
    for (const key of keys) {
      const server = problemOf(`aux.${key}`)
      if (server) return server
    }
    return null
  }

  /* 고르는 칸 + 그 칸 아래 판정 줄. 화면 판정(`why`)이 먼저이고, 없으면 서버가
     그 칸에 단 말입니다 — 같은 말이 한 칸 아래 두 번 서지 않습니다. */
  const picked = (node: React.ReactNode, name: string, why: string | null, field: string, kind: WhyKind) => {
    const server = why ? null : problemOf(field)
    return (
      <span className="set-bad" key={name}>
        {node}
        {why && <span className={whyTone(kind)}>{why}</span>}
        {server}
      </span>
    )
  }

  return (
    <div className="set">
      <div className={`card set-head${liveRuns > 0 ? ' has-runs' : ''}`}>
        <div className="set-head-main">
          <label className="set-field set-name">
            <span className="set-field-label">전략명</span>
            {/* **이름을 고치는 자리는 여기 하나**입니다. 목록은 고르는 자리라
                거기서도 고쳐지면 잘못 눌러 이름이 바뀝니다. 고친 이름은 저장을
                눌러야 목록에 섭니다 — 그때까지 목록은 저장된 이름 그대로입니다. */}
            <input
              className="control set-name-value"
              value={version.name}
              aria-label="전략명"
              /* 칸보다 긴 이름은 말줄임으로 서므로 전체를 여기 둡니다. */
              title={version.name}
              onChange={(event) => setVersionEdit(version.id, { name: event.target.value })}
            />
          </label>

          <label className="set-field set-version">
            <span className="set-field-label">버전</span>
            {/* `disabled` 를 안 씁니다 — 초점이 건너뛰면 옆에 달아 둔 이유를
                읽을 길이 없습니다(규격 §5). 고를 것이 하나라 값은 안 바뀝니다. */}
            <select
              className="control"
              value={version.version}
              aria-label="버전"
              aria-disabled
              title="버전은 목록에서 고릅니다"
              onChange={(event) => event.preventDefault()}
            >
              <option>{version.version}</option>
            </select>
          </label>

          {/* **품목과 월물을 나눠 둡니다.** 품목은 이 전략이 무엇을 거래하나이고,
              월물은 그 가운데 어느 달인가입니다 — 한 칸에 담으면 만기가 넘어갈
              때마다 전략이 없는 종목을 가리킵니다. 기본이 「근월 자동」인 것도
              그 때문입니다. */}
          <div className="set-field set-instrument">
            <span className="set-field-label" id="set-product-label">
              품목
            </span>
            <button
              type="button"
              className="control set-pick"
              aria-label={`품목 바꾸기 — ${product ? product.name : version.instrumentFallback || '고르지 않음'}`}
              aria-expanded={picking}
              onClick={() => setPicking((open) => !open)}
            >
              <span className="set-pick-name">
                {product ? product.name : (version.instrumentFallback || '품목을 고르세요')}
              </span>
              {/* **여는 칸이라는 표시**입니다. 옆의 월물은 셀렉트라 브라우저가
                  꺾쇠를 그려 주는데, 이 칸은 단추라 아무 표시가 없으면 적어 둔
                  값으로만 보입니다 — 누를 수 있다는 것이 안 읽힙니다. */}
              <span className="set-pick-mark" aria-hidden="true" />
            </button>
            {picking && (
              /* **품목 모드**로 엽니다. 여기서 정하는 것은 「무엇을 거래하나」
                 하나이고 어느 달인가는 옆 칸이 맡으므로, 월물이 늘어선 판을
                 세우면 누른 월물이 버려진 것처럼 읽힙니다. */
              <InstrumentPicker
                mode="product"
                market={version.market}
                current={
                  product
                    ? {
                        productCode: product.code,
                        productKind: version.productKind,
                        market: version.market,
                        productName: product.name,
                      }
                    : null
                }
                onClose={() => setPicking(false)}
                /* 품목을 바꾸면 월물은 「근월 자동」으로 돌아갑니다 — 앞 품목의
                   월물은 새 품목에서 가리킬 것이 없습니다. */
                onPick={(item) => {
                  /* 계좌·통화는 **시장이 정합니다.** 해외 통화는 품목정보가 답하므로
                     그 답이 오면 채웁니다 — 원으로 남겨 두면 달러 한도가 원으로
                     읽힙니다. */
                  setVersionEdit(version.id, {
                    market: item.market,
                    productCode: item.productCode,
                    productKind: item.productKind,
                    contractCode: '',
                    instrumentFallback: item.productName,
                    account: accountOf(item.market),
                    currency: currencyOf(item.market, ''),
                  })
                  /* 시장이 바뀌면 그 시장에 없는 값을 그 시장의 값으로 — 국내 세션이 남은
                     해외 전략은 저장이 막히고, 해외의 STOP 주문유형이 남은 국내 전략은
                     주문 유형 칸이 다른 값을 보이며 그 값으로 저장됩니다. 주문유형은 새
                     시장에도 있으면 그대로 둡니다. 체결조건은 국내 주문에만 붙습니다. */
                  if (item.market !== version.market) {
                    const types = orderTypesFor(item.market)
                    const orderType = types.includes(draft.aux.orderType) ? draft.aux.orderType : types[0]
                    setAux({
                      session: sessionsFor(item.market)[0] ?? '',
                      orderType,
                      fillCond:
                        item.market === 'domestic'
                          ? fillCondFor(
                              orderType,
                              FILL_CONDS.includes(draft.aux.fillCond) ? draft.aux.fillCond : FILL_CONDS[0],
                            )
                          : '',
                    })
                  }
                  if (item.market === 'overseas') {
                    const code = codeOfVersion({ ...item, contractCode: '' })
                    const asked = revertCountOf(version.id)
                    void loadOverseasProductInfo(code).then(() => {
                      /* 답이 오는 사이 품목을 또 바꿨으면 이 답은 앞 품목의 것이라 안 씁니다.
                         되돌렸어도 같습니다 — 버린 변경의 통화를 다시 세우면 되돌린
                         버전이 「고친 것 있음」으로 돌아갑니다. */
                      if (revertCountOf(version.id) !== asked) return
                      const now = versionOf(version.id)
                      if (now?.market !== 'overseas' || now.productCode !== item.productCode) return
                      const found = currencyOf('overseas', overseasProductInfoEntry(code).row?.currency)
                      if (found) setVersionEdit(version.id, { currency: found })
                    })
                  }
                  setPicking(false)
                }}
              />
            )}
            {problemOf('productCode')}
            {problemOf('market')}
          </div>

          <label className="set-field set-month">
            <span className="set-field-label">월물</span>
            {/* 「근월 자동」이 기본입니다 — 만기가 넘어가도 살아 있고, 만기
                당일은 건너뜁니다(엔진이 그날 진입을 막습니다). 특정 월물을
                고르면 그 달로 못 박히고, 그 달이 지나면 고쳐야 합니다.
                칸에는 짧은 꼴(「근월 · 10월물」)로 **지금 가리키는 달**을 남기고,
                전체 문장은 칸의 `title` 에 둡니다 — 전체를 칸에 세우면 이 폭에서
                음절 가운데가 잘립니다. 「근월」이 앞에 서서 못 박은 월물과
                갈립니다. */}
            <select
              className="control"
              value={version.contractCode ?? ''}
              aria-label="월물"
              title={
                version.contractCode
                  ? (months.find((item) => item.code === version.contractCode)?.label ?? '')
                  : `근월 자동${frontName && ` — 지금 ${frontName}`}`
              }
              onChange={(event) =>
                setVersionEdit(version.id, { contractCode: event.target.value })
              }
            >
              <option value="">
                {frontName ? `근월 · ${frontName.replace(/^\d+년\s*/, '')}` : '근월 자동'}
              </option>
              {months.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.label}
                </option>
              ))}
            </select>
            {problemOf('contractCode')}
          </label>
          {/* 기준 봉·평가 봉·메모는 **오른쪽 보조 설정**(「조건 평가」·「메모」)에
              있습니다. 머리는 「이 전략이 무엇인가」 넷만 둡니다 — 일곱 칸이 한 줄에
              서면 칸이 서로를 밀어 글자가 잘립니다. 셋은 훑는 값이 아니라 정하는
              값입니다. */}
        </div>

        <div className="set-head-acts">
          <button
            type="button"
            className="btn btn-quiet"
            aria-disabled={!dirty}
            /* 막힌 이유는 「고친 것이 없음」입니다 — 단추에 마우스를 올리면 섭니다.
               단추 아래 줄은 저장을 막는 까닭만 둡니다. */
            title={dirty ? undefined : '고친 것이 없습니다'}
            onClick={onRevert}
          >
            되돌리기
          </button>
          {/* 화면의 초록은 이 하나입니다. 「새 버전 저장」은 같은 일의 갈래라
              한 급 낮춰 무채색 테두리로 둡니다.
              못 받은 값이 있으면 둘 다 안 눌립니다 — `disabled` 가 아니라
              `aria-disabled` 인 것은 초점이 닿아야 아래 줄의 까닭을 읽을 수
              있어서입니다(되돌리기와 같은 규칙).
              마지막으로 저장한 것에서 고친 것이 없으면 「저장」도 잠급니다 — 이유는
              되돌리기와 같은 말이 마우스를 올리면 섭니다. 아직 목록에 없는 새 버전은
              고치지 않았어도 저장해야 목록에 서므로 잠그지 않습니다. */}
          <button
            type="button"
            className="btn btn-primary"
            aria-disabled={blocked || nothingToSave || undefined}
            aria-describedby={blocked ? 'set-save-why' : undefined}
            title={
              nothingToSave
                ? '고친 것이 없습니다'
                : unsaved
                  ? '저장 전 초안 — 목록에는 저장 뒤에 섭니다'
                  : undefined
            }
            onClick={() => !blocked && !nothingToSave && onSave()}
          >
            저장
          </button>
          {/* 「저장」과 다른 일입니다 — 목록에 **다음 버전 초안 행**을 만듭니다.
              못 받은 값은 새 버전에도 실을 수 없어 같은 까닭으로 막습니다. */}
          <button
            type="button"
            className="btn btn-quiet"
            aria-disabled={blocked || busy || undefined}
            aria-describedby={blocked ? 'set-save-why' : undefined}
            title={!blocked && busy ? '저장하는 중입니다' : undefined}
            onClick={() => !blocked && !busy && onSaveAsNew()}
          >
            새 버전 저장
          </button>
          {/* 못 고치는 칸·못 누르는 단추의 이유가 여기 한 줄에 모입니다.
              이유를 칸 밑에 달면 그 칸만 키가 커져 머리줄의 다른 칸들이
              눌립니다 — 머리는 폭이 좁고 칸이 여섯입니다.
              **이유가 둘 이상이면 앞에 그 칸·단추의 이름을 답니다** — 이름이
              없으면 어느 것이 왜 막혔는지 줄에서 갈리지 않습니다. 하나뿐일
              때는 이름 없이 그 이유만 섭니다.
              **없는 이유는 자리도 안 만듭니다** — 가운뎃점만 남으면 뒤에 무언가
              더 있었던 것처럼 읽힙니다. */}
          {/* 단추 아래에는 **저장을 막는 까닭만** 둡니다 — 묶음마다 그 수와 함께, 누르면
              그 자리로 갑니다. 되돌리기·버전·저장 전 초안의 까닭은 그 단추·칸에
              마우스를 올리면 섭니다. 막는 것이 없으면 이 줄은 자리도 안 만듭니다. */}
          {saveParts.length > 0 && (
            <p className="set-note" id="set-save-why">
              저장하려면 —{' '}
              {saveParts.map((part, index) => (
                <Fragment key={part.id}>
                  {index > 0 && <span aria-hidden="true"> · </span>}
                  <button type="button" className="set-note-link" onClick={() => goToProblem(part.id)}>
                    {part.text}
                  </button>
                </Fragment>
              ))}
            </p>
          )}

          {/* 서버가 저장을 안 받은 까닭. **막는 말이라 저장 단추 위**에 오류색
              한 줄로 섭니다 — 자리를 못 찾은 오류(본문 불일치·저장소 오류)는
              칸 옆에 붙을 데가 없어 여기가 유일한 자리입니다. */}
          {result !== null && !result.ok && (
            <p className="set-fail" id="set-fail-why">
              {/* 머리가 따로 온 실패(새 버전 저장)는 머리가 이미 까닭까지 담은 한 줄입니다. */}
              {[result.head ?? '저장', [result.message, ...looseErrors.map((one) => one.message)].filter(Boolean).join(' · ')]
                .filter(Boolean)
                .join(' — ')}
            </p>
          )}
        </div>
        {/* 도는 실행이 있으면 저장이 그 실행에 안 닿는다는 말. 단추가 왜 잠겼나를
            말하는 오른쪽 줄과 뜻이 달라 **머리 맨 아래 따로** 한 줄로 섭니다. */}
        {liveRuns > 0 && (
          <p className="set-runs-note" id="set-runs-why">
            도는 실행 {liveRuns}개는 시작할 때의 설정으로 돕니다 — 저장은 새로 세우는 실행부터
          </p>
        )}
      </div>

      <div
        className="set-body"
        ref={bodyRef}
        style={
          side.size === null
            ? undefined
            : { gridTemplateColumns: `minmax(${MAIN_MIN}px, 1fr) 8px ${side.size}px` }
        }
      >
        <div className="set-main">
          <div className="tabs tabs-inline set-rules">
            {RULE_KEYS.map((key) => (
              /* 탭과 ON/OFF 는 **다른 일**이라 단추가 둘입니다 — 단추 안에 단추를
                 넣을 수 없어 감싸개로 나란히 둡니다. 보는 눈에는 한 덩어리이고,
                 누를 때만 갈립니다. */
              <div className="set-rule-slot" key={key}>
                <button
                  type="button"
                  className="tab set-rule-tab"
                  aria-current={key === ruleKey}
                  onClick={() => setRuleKey(key)}
                >
                  {RULE_LABEL[key]}
                  {/* 서버가 그 규칙에 단 말이 있으면 수를 답니다 — 다른 탭에 걸린
                      것도 여기서 보여야 어디를 펴야 하는지 알 수 있습니다. */}
                  {tabBadge(key).count > 0 && (
                    <span className={`badge ${tabBadge(key).bad ? 'set-rule-bad' : 'set-rule-warn'}`}>
                      {tabBadge(key).count}
                    </span>
                  )}
                </button>
                {/* 켜짐은 상태이지 주요 작업이 아니라 색을 쓰지 않습니다.
                    **누르는 단추**가 되었어도 무게는 그대로입니다 — 잘못 눌러도
                    저장 전 초안이라 되돌릴 값이 없습니다. */}
                <button
                  type="button"
                  className="badge set-onoff"
                  aria-pressed={draft.rules[key].on}
                  aria-label={`${RULE_LABEL[key]} 사용`}
                  onClick={() => toggleRule(key)}
                >
                  {draft.rules[key].on ? 'ON' : 'OFF'}
                </button>
              </div>
            ))}
          </div>

          {/* 이 줄은 이제 **세는 말만** 답니다 — 켜고 끄는 것은 탭의 배지가
              맡았습니다(같은 일을 두 자리에 두면 어느 쪽이 참인지 묻게 됩니다). */}
          <div className="set-rule-bar">
            <span className="set-count">
              조건 {used} / {MAX_CONDS}
              {condProblems(rule) > 0 && (
                <span className="set-count-bad"> · 안 채운 줄 {condProblems(rule)}</span>
              )}
            </span>
          </div>

          {/* 서버가 규칙에 단 말. **네 규칙의 것이 다 섭니다** — 지금 보고 있는
              탭의 것만 적으면 다른 탭에 걸린 까닭을 찾으러 탭을 돌아야 합니다. */}
          {ruleSaid.length > 0 && (
            <ul className="set-rule-said">
              {ruleSaid.map((one, index) => (
                <li
                  className={one.severity === 'error' ? 'is-bad' : undefined}
                  key={`rule-said-${index}`}
                >
                  {ruleLine(one)}
                </li>
              ))}
            </ul>
          )}

          <div className="set-steps">
            {rule.steps.length === 0 ? (
              <div className="notice">
                <p className="notice-title">조건이 아직 없습니다</p>
                <p className="notice-reason">단계를 더하면 여기에 섭니다</p>
              </div>
            ) : (
              rule.steps.map((step, index) => stepCard(step, index))
            )}
          </div>

          {/* 단계 추가와 그 이유는 **구르는 자리 밖**에 둡니다. 단계가 쌓이면
              이 단추가 아래로 밀려나, 더 넣으려면 먼저 끝까지 굴려야 합니다.
              5 에 닿았을 때의 이유도 같은 이유로 늘 보이는 자리에 둡니다. */}
          <div className="set-step-foot">
            {/* 규칙 **전체의** 시한. 어느 한 단계의 값이 아니라 단계 안에 두지
                않습니다. 단계가 하나뿐이면 되돌릴 자리가 없어 세우지 않되, 값이
                적혀 있으면 지울 수 있게 섭니다. */}
            {(rule.steps.length >= 2 || rule.resetBars.trim() !== '') && (() => {
              const why = numberWhy(rule.resetBars, true, true)
              const server = why ? null : problemOf(`rules.${ruleKey}.resetBars`)
              return (
                <div className="set-reset">
                  <label className="set-within">
                    1단계부터
                    <input
                      className={`control set-num${why ? ' is-bad' : ''}`}
                      inputMode="numeric"
                      value={rule.resetBars}
                      placeholder="—"
                      aria-label={`${RULE_LABEL[ruleKey]} 1단계부터 다 채워지지 않으면 처음으로 되돌리는 봉 수`}
                      aria-invalid={why ? true : undefined}
                      aria-describedby={why || server ? 'set-reset-why' : undefined}
                      onChange={(event) => setRule({ ...rule, resetBars: event.target.value })}
                    />
                    봉 안에 못 끝내면 처음으로
                  </label>
                  {why && (
                    <p id="set-reset-why" className={`set-reset-why ${whyTone('wrong')}`}>
                      {why}
                    </p>
                  )}
                  {server && (
                    <p id="set-reset-why" className="set-reset-why">
                      {server}
                    </p>
                  )}
                </div>
              )
            })()}
            <button
              type="button"
              className="btn btn-quiet set-add-step"
              aria-disabled={full}
              aria-describedby={full ? 'set-limit' : undefined}
              onClick={addStep}
            >
              + 단계 추가
            </button>
            <p id="set-limit" className="set-limit">
              {limitWhy}
            </p>
          </div>
        </div>

        {/* 끌거나 화살표 키로 오른쪽 칸 폭을 바꿉니다. 더블클릭·Enter 는 원래 비율로. */}
        <div
          className="split-handle split-handle-x"
          aria-label="오른쪽 칸 폭"
          title="끌어서 오른쪽 칸 폭 조절 · 더블클릭하면 원래대로"
          {...side.handleProps}
        />

        <aside className="set-aux" aria-label="보조 설정" ref={asideRef}>
          {/* 요약은 **읽는 것**이라 고치는 자리(왼쪽 편집기)에서 떼어 오른쪽
              열 맨 위에 둡니다 — 왼쪽 맨 아래에 붙박이로 두면 조건이 구르는
              칸의 세로를 그만큼 먹습니다. 이 열은 제 안에서 굴러, 요약과 보조
              설정이 둘 다 닿습니다. */}
          <div className="set-summary">
            {/* 요약 첫머리 — 이 전략이 **어느 규칙을 쓰는지**. 탭마다의 문장은 지금 연
                규칙 하나의 것이라, 켜 둔 규칙 전체는 여기서만 보입니다. */}
            <p className="set-summary-line set-summary-uses">
              {usesLine(draft.rules)}
            </p>
            {lines.length === 0 ? (
              /* 빈 상태 문구는 **첫 문단 자리에만** 섭니다 — 조건이 없어도 보조
                 설정은 정해져 있어, 아래 문장까지 없는 것처럼 말하면 안 됩니다. */
              <p className="set-summary-empty">조건을 채우면 여기에 문장이 섭니다</p>
            ) : (
              lines.map((line, index) => {
                /* 무엇을 하는 규칙인지만 굵게 세웁니다. 색을 쓰면 「매수」의
                   빨강이 값의 방향색과 겹쳐, 문장 속 한 낱말이 값처럼 읽힙니다. */
                const mark = `${RULE_LABEL[ruleKey]}.`
                const at = line.endsWith(mark) ? line.length - mark.length : -1
                return (
                  <p className="set-summary-line" key={index}>
                    {at < 0 ? (
                      line
                    ) : (
                      <>
                        {line.slice(0, at)}
                        <strong>{RULE_LABEL[ruleKey]}</strong>.
                      </>
                    )}
                  </p>
                )
              })
            )}

            {/* 그 규칙의 시한. 규칙 문장 바로 다음 줄이고, 비었으면 안 섭니다. */}
            {resetLine(rule, lines) !== '' && (
              <p className="set-summary-line">{resetLine(rule, lines)}</p>
            )}

            {/* 이 전략이 주문을 어떻게 내는가. 규칙 문장 뒤에 그대로 이어집니다 —
                차례는 주문이 나가는 차례(주문 방식 → 청산·수량 → 실행 필터 →
                위험 한도)이고, 오른쪽 아코디언의 차례와 같습니다. */}
            {aux.lines.map((line, index) => (
              <p className="set-summary-line" key={`aux-${index}`}>
                {line}
              </p>
            ))}

            {/* 아직 안 정한 값은 **문장에서 빼고 여기 한 줄로** 모읍니다. 값 없는
                문장을 세우면 정하지 않은 것이 정한 것처럼 읽힙니다. */}
            {missing.length > 0 && (
              <p className="set-summary-missing">아직 정하지 않음 — {missing.join('·')}.</p>
            )}

            {/* 저장은 됐지만 **이대로는 안 도는** 설정. 경고색으로 문단 끝에
                섭니다 — 막는 말이 아니라 알려 주는 말이라 저장 단추 위에는
                두지 않습니다. */}
            {warnings.map((one, index) => (
              <p className="set-summary-warn" key={`warn-${index}`}>
                {one.message}
              </p>
            ))}
          </div>
          {/* 요약 바로 아래 — 이 규칙으로 지난 봉을 돌려 본 답. 저장이 막힌 상태면
              셈을 부르지 않습니다(저장 단추와 같은 판정). */}
          <BacktestCard version={version} draft={draft} dirty={dirty} blocked={blocked} currency={currency} />
          {/* 조건을 **어느 봉으로 재는가.** 조건을 재는 것이 주문보다 앞서므로 맨
              위입니다. 접힌 줄은 낱말과 값을 함께 적습니다 — 「마감」만 두면 무엇의
              값인지 안 읽힙니다. */}
          {accordion(
            'evaluate',
            '조건 평가',
            `기준 ${draft.baseBar} · 평가 ${draft.evalMode}`,
            0,
            <>
              {field('기준 봉', select(draft.baseBar, BASE_BARS, (v) => patch({ baseBar: v }), '기준 봉'))}
              {field('평가 봉', select(draft.evalMode, EVAL_MODES, (v) => patch({ evalMode: v }), '평가 봉'))}
              {/* 고른 값이 언제 판정하는지 한 줄로 — 「틱」은 봉이 끝나기 전에도 신호를
                  낼 수 있다는 것이 고르는 사람에게 가장 큰 차이입니다. */}
              <p className="set-hint">
                {draft.evalMode === '틱'
                  ? '체결이 올 때마다 아직 안 끝난 봉까지 넣어 판정합니다 — 봉이 끝나기 전에 신호가 날 수 있습니다'
                  : '봉이 끝날 때 한 번 판정합니다'}
              </p>
            </>,
          )}

          {accordion(
            'order',
            '주문 방식',
            /* 접힌 줄에도 **실제로 쓰이는 것**만 적습니다 — 시장가인데 값 기준을
               함께 적으면 그 기준이 주문에 실리는 것처럼 읽힙니다. */
            orderLine(draft.aux),
            problems.order,
            <>
              {/* 예전에 저장한 설정에 전략 주문에 쓰지 않는 유형이 남아 있으면 **그 값을
                  그대로** 보입니다 — 목록에 없는 값을 두면 첫 선택지가 대신 서서 고른
                  적 없는 값이 고른 것처럼 읽힙니다. 다른 유형을 고르면 사라집니다. */}
              {field(
                '주문 유형',
                excludedOrderType(draft.aux.orderType) ? (
                  <span className="set-bad">
                    <select
                      className="control is-bad"
                      value={draft.aux.orderType}
                      aria-label="주문 유형"
                      aria-invalid
                      aria-describedby="set-why-order-type"
                      onChange={(e) => setOrderType(e.target.value)}
                    >
                      <option value={draft.aux.orderType} disabled>
                        {draft.aux.orderType}
                      </option>
                      {orderTypesFor(version.market).map((item) => (
                        <option key={item} value={item}>
                          {item}
                        </option>
                      ))}
                    </select>
                    <span id="set-why-order-type" className={whyTone('wrong')}>
                      {excludedOrderTypeWhy(draft.aux.orderType)}
                    </span>
                  </span>
                ) : (
                  select(draft.aux.orderType, orderTypesFor(version.market), setOrderType, '주문 유형')
                ),
              )}
              {/* **시장가·STOP-M 은 값을 안 받습니다**(주문 화면과 같은 규칙).
                  칸을 지우지 않고 막아 두는 것은, 다시 지정가로 바꾸면 그 자리에
                  무엇이 있었는지 보여야 하기 때문입니다. 막은 이유는 옆에 적습니다. */}
              {field(
                '주문 가격',
                needsPrice ? (
                  picked(
                    select(draft.aux.priceBasis, PRICE_BASES, (v) => setAux({ priceBasis: v }), '주문 가격'),
                    'price-basis',
                    basisWhy('priceBasis'),
                    'aux.priceBasis',
                    baseKind(draft.aux, 'priceBasis'),
                  )
                ) : (
                  <span className="set-off">
                    <select
                      className="control"
                      value={draft.aux.priceBasis}
                      aria-label="주문 가격"
                      disabled
                      aria-describedby="set-price-off"
                      onChange={() => undefined}
                    >
                      <option value={draft.aux.priceBasis}>{draft.aux.priceBasis}</option>
                    </select>
                    <span id="set-price-off" className="set-off-why">
                      시장가로 나갑니다
                    </span>
                  </span>
                ),
              )}
              {/* 방향마다의 가격 기준. **값을 받는 주문유형일 때만** 섭니다 — 위
                  공용 칸과 같은 조건입니다. 첫 선택지 「공통 기준」(빈 값)이 비우면
                  위 칸을 따른다는 것을 말해, 곁 문장을 따로 두지 않습니다. */}
              {needsPrice &&
                SIDE_BASES.map((one) =>
                  field(
                    one.label,
                    picked(
                      <select
                        className="control"
                        value={draft.aux[one.key]}
                        aria-label={one.label}
                        onChange={(event) => setAux({ [one.key]: event.target.value })}
                      >
                        <option value="">공통 기준</option>
                        {PRICE_BASES.map((item) => (
                          <option key={item} value={item}>
                            {item}
                          </option>
                        ))}
                      </select>,
                      one.key,
                      basisWhy(one.key),
                      `aux.${one.key}`,
                      baseKind(draft.aux, one.key),
                    ),
                  ),
                )}
              {/* 스탑 주문은 스탑 가격을 함께 받습니다 — 그 주문유형일 때만 섭니다. */}
              {needsStopFor(draft.aux.orderType) &&
                field(
                  '스탑 가격',
                  select(draft.aux.stopBasis, PRICE_BASES, (v) => setAux({ stopBasis: v }), '스탑 가격'),
                )}
              {/* **체결조건은 국내 주문에만 있습니다.** 해외 주문에는 그런 칸이
                  없어 세우지 않습니다 — 비활성으로 두면 언젠가 켜지는 것처럼
                  읽히고, 값이 남아 있으면 주문에 실릴 것처럼 보입니다. */}
              {/* 선택지는 주문유형이 받는 것만 둡니다(시장가는 FAS 만). 이 규칙 전에 담아 둔
                  설정이 맞지 않는 값을 들고 있으면 **그 값을 그대로** 보이고 까닭을 답니다 —
                  첫 선택지가 대신 서면 고른 적 없는 값이 고른 것처럼 읽힙니다. */}
              {version.market === 'domestic' &&
                field(
                  '체결조건',
                  fillCondMismatch(draft.aux) ? (
                    <span className="set-bad">
                      <select
                        className="control is-bad"
                        value={draft.aux.fillCond}
                        aria-label="체결조건"
                        aria-invalid
                        aria-describedby="set-why-fill-cond"
                        onChange={(e) => setAux({ fillCond: e.target.value })}
                      >
                        <option value={draft.aux.fillCond} disabled>
                          {draft.aux.fillCond}
                        </option>
                        {fillCondsFor(draft.aux.orderType).map((item) => (
                          <option key={item} value={item}>
                            {item}
                          </option>
                        ))}
                      </select>
                      <span id="set-why-fill-cond" className={whyTone('wrong')}>
                        {MARKET_FILL_COND_WHY}
                      </span>
                    </span>
                  ) : (
                    select(draft.aux.fillCond, fillCondsFor(draft.aux.orderType), (v) => setAux({ fillCond: v }), '체결조건')
                  ),
                )}
            </>,
          )}

          {accordion(
            'exit',
            '청산 · 수량',
            /* 추적 청산은 **정했을 때만** 접힌 줄에 섭니다 — 비어 있으면 쓰지 않는
               것이라 적을 값이 없습니다. */
            [
              `손절 ${draft.aux.stopTicks.trim() ? distanceText(draft.aux.stopTicks, draft.aux.stopUnit) : '—'}`,
              `익절 ${draft.aux.takeTicks.trim() ? distanceText(draft.aux.takeTicks, draft.aux.takeUnit) : '—'}`,
              ...(draft.aux.trailTicks.trim()
                ? [`추적 ${distanceText(draft.aux.trailTicks, draft.aux.trailUnit)}`]
                : []),
              ...(draft.aux.sessionEndFlat && draft.aux.sessionEndMinutes.trim()
                ? [`끝 ${draft.aux.sessionEndMinutes.trim()}분 전 정리`]
                : []),
            ].join(' · '),
            problems.exit,
            <>
              {field('손절', distance('stop', 'stopTicks', 'stopUnit', '손절'))}
              {field('익절', distance('take', 'takeTicks', 'takeUnit', '익절', { placeholder: '쓰지 않음' }))}
              {field('추적 청산', distance('trail', 'trailTicks', 'trailUnit', '추적 청산', { placeholder: '쓰지 않음' }))}
              {field('주문당', unit('per-order', 'perOrder', '계약', '주문당 수량'))}
              {field('최대보유', unit('max-hold', 'maxHold', '계약', '최대 보유'))}
              {/* 세션 끝 정리 — 끝 시각은 서버 시간표가 정합니다(조기 마감·야간 자정 넘김). */}
              <div className="set-bad set-session-end">
                <label className="set-check">
                  <input
                    type="checkbox"
                    checked={draft.aux.sessionEndFlat}
                    onChange={(event) => setAux({ sessionEndFlat: event.target.checked })}
                  />
                  세션 끝
                </label>
                {filterInput('sessionEndMinutes', '세션 끝 정리 분', {
                  className: 'set-filter-num',
                  disabled: !draft.aux.sessionEndFlat,
                })}
                <span className="set-filter-text">분 전</span>
                <span className="set-filter-text set-session-end-text">모두 청산하고 새 진입 막기</span>
                {draft.aux.sessionEndFlat && filterSaid(['sessionEndMinutes'])}
              </div>
              {/* 값을 적은 거리 칸이 ATR 단위면, ATR 이 아직 없을 때 그 거리를 셀 수 없어
                  진입하지 않습니다(서버 판정). 값이 빈 칸은 쓰지 않는 칸이라 단위가 ATR 이어도
                  세지 않습니다 — 「비었다」는 앞뒤 공백을 걷고 빈 글자인 것으로, 칸 판정과 같습니다. */}
              {(Object.keys(EXIT_FIELDS) as (keyof typeof EXIT_FIELDS)[]).some(
                (key) => exitUnitOf(draft.aux[EXIT_FIELDS[key]]) === 'atr' && (draft.aux[key] ?? '').trim() !== '',
              ) && (
                <p className="set-hint">ATR(14)이 준비될 때까지 새로 진입하지 않습니다</p>
              )}
              {/* 청산 규칙만 위 주문 유형으로 나갑니다. 나머지는 「지금 닫는다」는 뜻이라
                  지정가로 걸면 값이 지나가 보유가 남을 수 있어 시장가로 나갑니다. */}
              <p className="set-hint">
                손절 · 익절 · 추적 청산 · 세션 끝 정리는 앱 실행 중 감시하며, 주문 유형과 상관없이 시장가로 보유 전량을 청산합니다
              </p>
            </>,
          )}

          {accordion(
            'filter',
            '실행 필터',
            [
              draft.aux.session,
              entryWindowText(draft.aux.entryStart, draft.aux.entryEnd),
              Number(draft.aux.reentryWaitBars.trim()) > 0 ? `대기 ${draft.aux.reentryWaitBars.trim()}봉` : '',
              draft.aux.addWhileOpen ? '추가 진입 함' : '보유/미체결 중 추가 진입 안 함',
            ]
              .filter((one) => one !== '')
              .join(' · '),
            problems.filter,
            <>
              {field(
                '세션',
                select(draft.aux.session, sessionsFor(version.market), (v) => setAux({ session: v }), '세션'),
              )}
              {/* 신규 진입 시간 — 한국시간이고, 비우면 세션 시작·끝입니다. 끝이 시작보다
                  이르면 다음 날입니다. 세션 밖 시각은 저장은 되지만 실행을 세울 때 서버가
                  막아 경고색으로 미리 알립니다. */}
              {stacked(
                '신규 진입 시간',
                <span className="set-bad set-bad-start">
                  <span className="set-window">
                    {filterInput('entryStart', '신규 진입 시작', { clock: true, placeholder: '세션 시작', className: 'set-clock' })}
                    <span className="set-filter-text">~</span>
                    {filterInput('entryEnd', '신규 진입 끝', { clock: true, placeholder: '세션 끝', className: 'set-clock' })}
                    {draft.aux.entryStart.trim() !== '' &&
                      draft.aux.entryEnd.trim() !== '' &&
                      clockMinutes(draft.aux.entryEnd) < clockMinutes(draft.aux.entryStart) && (
                        <span className="set-filter-text">익일</span>
                      )}
                    <span className="set-filter-text set-filter-dim">한국시간</span>
                  </span>
                  {filterSaid(['entryStart', 'entryEnd']) ??
                    (windowOutsideWhy(draft.aux, sessionWindow) && (
                      <span className="set-warn-why">{windowOutsideWhy(draft.aux, sessionWindow)}</span>
                    ))}
                  <span className="set-filter-note">청산은 이 시간 밖에서도 합니다</span>
                </span>,
              )}
              {stacked(
                '청산 뒤 대기',
                <span className="set-bad set-bad-start">
                  <span className="set-window">
                    {filterInput('reentryWaitBars', '청산 뒤 대기', { placeholder: '0' })}
                    <span className="set-filter-text">봉</span>
                    <span className="set-filter-text set-filter-dim">기준 {draft.baseBar}</span>
                  </span>
                  {filterSaid(['reentryWaitBars'])}
                </span>,
              )}
              <label className="set-check">
                <input
                  type="checkbox"
                  checked={draft.aux.addWhileOpen}
                  onChange={(event) => setAux({ addWhileOpen: event.target.checked })}
                />
                보유 · 미체결 중에도 추가 진입
              </label>
            </>,
          )}

          {accordion(
            'risk',
            '위험 한도',
            `하루 ${money(draft.aux.dailyLoss, currency)} · 예산 ${money(draft.aux.marginBudget, currency)}` +
              (draft.aux.lossStreak.trim() ? ` · 연속 손실 ${draft.aux.lossStreak.trim()}번` : '') +
              (draft.aux.maxEntriesPerDay.trim() ? ` · 최대 ${draft.aux.maxEntriesPerDay.trim()}번` : ''),
            problems.risk,
            <>
              {field(
                '하루 손실',
                unit('daily-loss', 'dailyLoss', currency, '하루 손실 한도'),
              )}
              {field(
                '증거금 예산',
                unit('margin-budget', 'marginBudget', currency, '증거금 예산'),
              )}
              {field(
                '연속 손실',
                unit('loss-streak', 'lossStreak', '번', '연속 손실 한도', {
                  placeholder: '쓰지 않음',
                  field: 'aux.lossStreak',
                }),
              )}
              <p className="set-hint">손실 거래가 이만큼 이어지면 그날은 새 진입을 멈춥니다</p>
              {field(
                '하루 최대 진입',
                <span className="set-bad">
                  <span className="set-window">
                    {filterInput('maxEntriesPerDay', '하루 최대 진입', { placeholder: '제한 없음' })}
                    <span className="set-filter-text">번</span>
                  </span>
                  {filterSaid(['maxEntriesPerDay'])}
                </span>,
              )}
            </>,
          )}

          {/* 이 버전에 남긴 말. **실행에는 안 쓰이는 값**이라 맨 끝이고, 위 요약
              문단에도 넣지 않습니다(요약은 실제로 쓰이는 것만). 접힌 줄은 첫 줄만
              적고, 비었으면 「—」입니다. */}
          {accordion(
            'memo',
            '메모',
            draft.memo.split('\n')[0] || '—',
            0,
            field(
              '메모',
              <input
                className="control set-text"
                value={draft.memo}
                placeholder="이 버전에 남길 말"
                aria-label="메모"
                onChange={(event) => patch({ memo: event.target.value })}
              />,
            ),
          )}
        </aside>
      </div>
    </div>
  )
}
