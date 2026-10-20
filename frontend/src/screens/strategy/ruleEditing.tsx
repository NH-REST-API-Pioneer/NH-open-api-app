import { paramProblems } from '../../data/strategyChecks'
import type { StrategyVersion } from '../../data/strategyList'
import {
  blankCond,
  blankStep,
  fillCondFor,
  MAX_CONDS,
  operandOf,
  operatorOf,
  rightKindsOf,
  type Aux,
  type Cond,
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
  type Params,
} from '../../data/indicatorOperands'
import { ParamInput } from './ParamInput'
import { nextSeed, sharesParams } from './strategySettingsUtils'

/** 설정 초안을 고치는 손 — 규칙·단계·조건·보조 설정을 바꿔 `onChange` 로 넘깁니다. */
export function makeRuleEditing({
  onChange,
  draft,
  version,
  ruleKey,
  rule,
  full,
}: {
  onChange: (next: SettingsDraft) => void
  draft: SettingsDraft
  version: StrategyVersion
  ruleKey: RuleKey
  rule: Rule
  full: boolean
}) {
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

  return {
    patch,
    setAux,
    setOrderType,
    setRule,
    toggleRule,
    editStep,
    editCond,
    pickLeft,
    pickRight,
    paramFields,
    pickOp,
    addCond,
    dropCond,
    addStep,
    dropStep,
    limitWhy,
  }
}
