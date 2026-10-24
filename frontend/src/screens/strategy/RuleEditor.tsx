import { condCheck, numberWhy, severityKind, whyTone, withinWhy } from '../../data/strategyChecks'
import {
  CLOCK_ID,
  LEVEL_OPS,
  MOMENT_TITLE,
  NO_PREVIOUS_IDS,
  rightIdsOf,
  TIME_IDS,
  MAX_CONDS,
  fullLabelOf,
  operandOf,
  operatorOf,
  OPERANDS,
  OPERATORS,
  PICK_OPERANDS,
  rightKindOf,
  rightKindsOf,
  RULE_KEYS,
  RULE_LABEL,
  type Cond,
  type RuleKey,
  type SettingsDraft,
  type Step,
} from '../../data/strategyRules'
import { KIND_LABEL, condProblems, operandGroups, ruleLine } from './strategySettingsUtils'
import type { Dispatch, SetStateAction, JSX } from 'react'
import type { useSettingsChecks } from './useSettingsChecks'
import type { makeRuleEditing } from './ruleEditing'

type CheckValues = ReturnType<typeof useSettingsChecks>
type EditingValues = ReturnType<typeof makeRuleEditing>
type RuleParts = ReturnType<typeof ruleEditorParts>

type RuleEditorArgs = Pick<CheckValues, 'daily' | 'condSaid' | 'nightSession' | 'rule' | 'full'> &
  Pick<
    EditingValues,
    'pickLeft' | 'pickOp' | 'editCond' | 'pickRight' | 'dropCond' | 'paramFields'
    | 'editStep' | 'dropStep' | 'addCond'
  > &
  {
    ruleKey: RuleKey
    problemOf: (field: string) => JSX.Element | null
  }

/** 규칙 편집기의 단계 카드와 조건 줄을 그리는 함수. */
export function ruleEditorParts({
  daily,
  condSaid,
  ruleKey,
  nightSession,
  pickLeft,
  pickOp,
  editCond,
  pickRight,
  dropCond,
  paramFields,
  rule,
  problemOf,
  editStep,
  dropStep,
  full,
  addCond,
}: RuleEditorArgs) {
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
       받으므로 조건 줄이 그 갈래를 들고 다닙니다. */
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

  return {
    stepCard,
  }
}

type RuleMainArgs = Pick<CheckValues, 'tabBadge' | 'used' | 'rule' | 'ruleSaid' | 'full'> &
  Pick<EditingValues, 'toggleRule' | 'setRule' | 'addStep' | 'limitWhy'> &
  Pick<RuleParts, 'stepCard'> &
  {
    ruleKey: RuleKey
    setRuleKey: Dispatch<SetStateAction<RuleKey>>
    draft: SettingsDraft
    problemOf: (field: string) => JSX.Element | null
  }

/** 규칙 편집기 — 규칙 탭, 규칙 막대, 서버가 단 말, 단계와 단계 꼬리. */
export function renderRuleMain({
  ruleKey,
  setRuleKey,
  tabBadge,
  draft,
  toggleRule,
  used,
  rule,
  ruleSaid,
  stepCard,
  problemOf,
  setRule,
  full,
  addStep,
  limitWhy,
}: RuleMainArgs) {
  return (
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
              맡습니다(같은 일을 두 자리에 두면 어느 쪽이 참인지 묻게 됩니다). */}
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
  )
}
