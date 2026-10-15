import { kstClock } from '../../lib/kst'
import { MINUS } from '../../lib/number'
import { PRICE_AXIS_IDS, RULE_LABEL, operandWord, operatorOf } from '../../data/strategyRules'
import { resolveOperand } from '../../data/indicatorOperands'
import type { ConditionLine, ConditionRule, ConditionStep, RunConditions } from '../../data/strategyRuns'

/* 조건 지금 표 — 마지막으로 판정한 봉에서 켜진 규칙의 단계·조건이 어디에 와
 * 있는지.
 *
 * **값과 참거짓은 서버가 판정에 쓴 그대로입니다.** 화면이 지표를 다시 셈하면
 * 공식·시드가 달라 판정과 다른 수가 서고, 1단계 「바뀌는 순간」이나 2단계 창은
 * 값만으로 정할 수 없습니다(직전 봉·남은 봉이 필요). 그래서 표는 받은 값을 적기만
 * 합니다. 색은 쓰지 않습니다 — 참·발사는 글자와 굵기로 가릅니다. */

/** 값의 자릿수 갈래. 가격과 같은 축(가격·이동평균·밴드·호가·평가손익)은 종목
 *  자릿수, 오실레이터·변동폭은 둘, 수량·순서는 정수, 시각은 시:분입니다. */
const PRICE_LIKE = new Set([...PRICE_AXIS_IDS, 'openPl'])
const WHOLE = new Set(['volume', 'bid1Qty', 'ask1Qty', 'positionQty', 'barOrder'])

function valueText(id: string, value: number | null, decimals: number): string {
  if (value === null || !Number.isFinite(value)) return '—'
  if (id === 'clock') {
    /* 야간은 자정을 넘어 이어 셉니다(+1440) — 적을 때는 하루 안으로 접습니다. */
    const minutes = ((Math.round(value) % 1440) + 1440) % 1440
    return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`
  }
  const base = resolveOperand(id).id
  const digits = WHOLE.has(base) ? 0 : PRICE_LIKE.has(base) ? decimals : 2
  const text = Math.abs(value).toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
  return value < 0 && Number(text.replace(/,/g, '')) !== 0 ? `${MINUS}${text}` : text
}

/** 조건 한 줄의 글(「RSI(14) 이상 30」). 지표는 매개변수까지 적습니다 — 편집기·요약
 *  문장과 같은 이름(`operandWord`)입니다. 오른쪽이 수·시각이면 적힌 글자 그대로입니다. */
function condText(line: ConditionLine): string {
  const left = operandWord(line.left, line.leftParams) ?? line.left
  const op = operatorOf(line.op)?.label ?? line.op
  const right =
    line.rightKind === 'operand' ? (operandWord(line.right, line.rightParams) ?? line.right) : line.right
  return `${left} ${op} ${right}`
}

/** 기준 칸. 오른쪽이 다른 값이면 그 값의 이 봉 수치, 수·시각이면 적힌 글자입니다. */
function baseText(line: ConditionLine, decimals: number): string {
  if (line.rightKind === 'operand') return valueText(line.right, line.rightValue, decimals)
  return line.right
}

type CondState = '안 봄' | '—' | '아님' | '참'

/** 조건 줄의 상태 — **그 조건 하나가 이 봉에 참인지**만 말합니다.
 *
 *  - 엔진이 이 봉에 그 규칙을 안 봤으면 「안 봄」(청산 규칙은 보유가 없으면 안 봄).
 *  - 값을 모르면 「—」.
 *  - 그 밖은 「참」·「아님」입니다.
 *
 *  「이미 참」·「발사」는 **단계 전체의 전이**라 조건 한 줄의 상태가 아닙니다 —
 *  단계 줄 끝의 판정이 말합니다(`stepVerdict`). */
function condState(rule: ConditionRule, line: ConditionLine): CondState {
  if (!rule.judged) return '안 봄'
  if (line.now === null) return '—'
  return line.now ? '참' : '아님'
}

const STATE_CLASS: Record<CondState, string> = {
  '안 봄': 'cond-dim',
  '—': 'cond-dim',
  아님: 'cond-dim',
  참: 'cond-true',
}

/** 단계 줄 끝의 판정. 지난 단계·기다리는 단계·아직 안 온 단계를 가르고, 기다리는
 *  단계의 전이(「참 · 이미」 — 이미 참이라 거짓이 됐다가 참이 될 때까지 기다림,
 *  「참 · 발사」 — 이 봉에 걸림)도 여기서만 말합니다. 「발사」는 규칙이 참이 됐다는
 *  뜻이지 주문이 나갔다는 뜻은 아닙니다 — 안 낸 까닭은 이벤트에 섭니다. */
const FIRED = '참 · 발사'

function stepVerdict(rule: ConditionRule, step: ConditionStep, index: number): string {
  const number = index + 1
  if (!rule.judged) return '안 봄'
  if (number < rule.waitingStep) return '지남'
  if (number > rule.waitingStep) return '차례 전'
  if (rule.fired) return FIRED
  if (number === 1) {
    if (step.stepNow === true && step.beforeUnknown) return '참 · 직전 모름'
    if (step.stepNow === true && step.stepBefore === true) return '참 · 이미'
    if (step.stepNow === false) return '기다림'
    return '—'
  }
  return rule.barsLeft === null ? '기다림' : `${rule.barsLeft}봉 남음`
}

/** 단계 줄의 글. 1단계는 **바뀌는 순간**에만 걸리고, 2단계부터는 창 안의 첫 참입니다. */
function stepTitle(step: ConditionStep, index: number): string {
  const join = step.join === 'all' ? '모두 충족' : '하나라도 충족'
  if (index === 0) return `1단계 · ${join} · 직전 거짓 → 지금 참이면 냄`
  return `${index + 1}단계 · ${join} · ${step.withinBars}봉 안에 처음 참`
}

export function ConditionTable({
  conditions,
  decimals,
  tick,
}: {
  /** 마지막 판정 봉의 표. 아직 없으면 `null`. */
  conditions: RunConditions | null | undefined
  /** 종목 가격 자릿수. */
  decimals: number
  /** 틱 판정 실행인지. 아직 표가 없을 때의 안내가 달라집니다 — 틱은 봉이 끝나기
   *  전에도 체결마다 판정합니다. */
  tick: boolean
}) {
  if (!conditions) {
    return (
      <p className="cond-empty">
        {tick
          ? '아직 판정한 체결이 없습니다 — 첫 체결이 오면 섭니다'
          : '아직 판정한 봉이 없습니다 — 첫 봉이 마감되면 섭니다'}
      </p>
    )
  }
  /* 머리 시각은 **판정한 봉의 시작 시각**입니다. 틱 판정은 아직 안 끝난 봉으로도
     판정하고, 그 표에는 서버가 `partialBar` 를 붙입니다 — 그때는 「진행 중」이라
     적습니다. 봉이 닫히면 닫힌 봉의 표로 바뀌어 마감 실행과 같은 말이 됩니다. */
  const at = conditions.barTime
  const clock = at === null ? '—' : kstClock(at)
  /* 준비 봉이 모자라거나 시세가 끊긴 봉은 값이 없습니다 — 값·상태 칸을 「—」로 둡니다. */
  const waiting = conditions.state !== 'ready'
  return (
    <div className="cond">
      <p className="cond-head">
        {clock} {conditions.partialBar ? '봉 진행 중 기준' : '봉 마감 기준'}
        {conditions.state === 'warmup' && ` · 준비 중 — 필요 ${conditions.need} · 확보 ${conditions.have}`}
        {conditions.state === 'gap' && ' · 시세가 끊겨 이 봉은 판정하지 않았습니다'}
      </p>
      {conditions.rules.length === 0 ? (
        <p className="cond-empty">켜진 규칙이 없습니다</p>
      ) : (
        <table className="data-table cond-table">
          <colgroup>
            <col />
            <col className="cond-col-num" />
            <col className="cond-col-num" />
            <col className="cond-col-state" />
          </colgroup>
          <thead>
            <tr>
              <th scope="col" className="col-text">
                조건
              </th>
              <th scope="col">지금</th>
              <th scope="col">기준</th>
              <th scope="col">상태</th>
            </tr>
          </thead>
          {conditions.rules.map((rule) => (
            <tbody key={rule.rule}>
              <tr className="cond-rule">
                <th scope="rowgroup" colSpan={4} className="col-text">
                  {RULE_LABEL[rule.rule] ?? rule.rule}
                  {/* 이 봉에 걸린 규칙은 「기다림」이 아니라 낸 것입니다 — 머리와 단계 줄이
                      서로 다른 말을 하지 않게 머리가 먼저 그렇게 말합니다. */}
                  {rule.fired ? ' · 이 봉에서 냄' : ` · ${rule.waitingStep}/${rule.steps}단계 기다림`}
                  {!rule.fired && rule.resetLeft !== null && ` · 시한 ${rule.resetLeft}봉`}
                </th>
              </tr>
              {rule.stepsDetail.map((step, index) => (
                <StepRows key={index} rule={rule} step={step} index={index} decimals={decimals} waiting={waiting} />
              ))}
            </tbody>
          ))}
        </table>
      )}
    </div>
  )
}

function StepRows({
  rule,
  step,
  index,
  decimals,
  waiting,
}: {
  rule: ConditionRule
  step: ConditionStep
  index: number
  decimals: number
  waiting: boolean
}) {
  const verdict = waiting ? '—' : stepVerdict(rule, step, index)
  return (
    <>
      <tr className="cond-step">
        <td className="col-text" colSpan={3}>
          {stepTitle(step, index)}
        </td>
        <td className={`cond-verdict${verdict === FIRED ? ' cond-fired' : ''}`}>{verdict}</td>
      </tr>
      {step.conds.map((line, at) => {
        const state: CondState = waiting ? '—' : condState(rule, line)
        return (
          <tr key={at} className="cond-line">
            <td className="col-text">{condText(line)}</td>
            <td className="num">{waiting ? '—' : valueText(line.left, line.leftValue, decimals)}</td>
            <td className="num">{baseText(line, decimals)}</td>
            <td className={`cond-state ${STATE_CLASS[state]}`}>{state}</td>
          </tr>
        )
      })}
    </>
  )
}
