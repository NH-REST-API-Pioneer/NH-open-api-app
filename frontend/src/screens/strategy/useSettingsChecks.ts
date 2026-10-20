import { useMemo } from 'react'
import { ruleGaps, summarize, summarizeAux } from '../../data/ruleSummary'
import { numberWhy } from '../../data/strategyChecks'
import { useStrategyState, type SaveResult } from '../../data/strategyStore'
import type { StrategyVersion } from '../../data/strategyList'
import {
  condCount,
  MAX_CONDS,
  RULE_KEYS,
  sessionKeyOf,
  type RuleKey,
  type SettingsDraft,
} from '../../data/strategyRules'
import type { Dispatch, SetStateAction } from 'react'
import {
  CONDITION_PATH,
  FIELD_SAID,
  WITHIN_PATH,
  auxProblems,
  condProblems,
  contextProblems,
  money,
  problemsForRule,
  ruleOf,
  saveWhy,
  withinBadSteps,
} from './strategySettingsUtils'
import type { OpenSections } from './strategySettingsUtils'

/** 저장을 막는 값의 판정과 요약 문장 — 고친 값이 바뀔 때마다 다시 셉니다. */
export function useSettingsChecks({
  draft,
  ruleKey,
  setRuleKey,
  setOpen,
  dirty,
  unsaved,
  version,
  currency,
  result,
}: {
  draft: SettingsDraft
  ruleKey: RuleKey
  setRuleKey: Dispatch<SetStateAction<RuleKey>>
  setOpen: Dispatch<SetStateAction<OpenSections>>
  dirty: boolean
  unsaved: boolean
  version: StrategyVersion
  currency: string
  result: SaveResult | null
}) {
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

  return {
    rule,
    used,
    full,
    problems,
    daily,
    blocked,
    nothingToSave,
    saveParts,
    goToProblem,
    liveRuns,
    lines,
    said,
    tabBadge,
    ruleSaid,
    condSaid,
    nightSession,
    warnings,
    looseErrors,
    aux,
    missing,
  }
}
