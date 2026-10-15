import { RULE_KEYS, type RuleSet } from '../../data/strategyRules'
import { MACD_IDS, STOCH_IDS, BOLLINGER_IDS, resolveOperand, type Params } from '../../data/indicatorOperands'
import { defaultSetting, indicatorDef, nextColor, DEFAULT_LINE_SIZE, type IndicatorSetting } from '../trade/chartIndicators'
import { ENGINE_ATR, ENGINE_MACD, ENGINE_STOCH, ENGINE_VWAP } from './engineIndicators'

/* 전략 규칙이 쓰는 지표를 검증 차트에 켜는 표.
 *
 * **매개변수는 조건의 매개변수입니다** — 조건이 EMA(5)면 차트도 EMA(5)입니다. 차트
 * 기본(RSI 6·12·24, MA 5·20·60·120)과 다르면 차트의 선과 조건 표의 값이 다른 것을
 * 말합니다.
 *
 * **차트가 서버 엔진과 같은 값을 내는 지표만** 켭니다. 이동평균(SMA)·EMA(SMA 로
 * 시작)·RSI(Wilder 평활)·볼린저 밴드(모집단 표준편차, 창 = 기간)는 차트 라이브러리의
 * 기본 지표가 같은 식이라 그대로 쓰고, MACD(막대 ×1)·스토캐스틱(단순 이동평균
 * 평활)·VWAP(세션마다 다시 셈)·ATR 은 엔진과 같은 식으로 등록한 지표를 씁니다
 * (`engineIndicators.ts`). 그때 같은 이름의 기본 지표(막대 ×2 의 MACD, 다른 평활의
 * KDJ)는 이 차트에서 끕니다 — 둘이 함께 서면 같은 이름의 다른 값이 나란히 섭니다.
 * 같은 식이어도 차트가 받은 봉의 시작이 엔진과 다르면 EMA·RSI 끝자리가 조금 다를 수
 * 있습니다(값은 조건 표가 기준).
 *
 * 켠 것은 **검증 차트에만** 겹쳐 쓰고 저장하지 않습니다 — 일반주문 차트의 지표
 * 구성은 사용자가 거기서 고른 그대로입니다. */

/** 켜진 규칙들이 쓰는 값과 매개변수. 왼쪽과, 오른쪽이 값이면 오른쪽입니다. */
function operandsOf(rules: RuleSet): { id: string; params: Params | undefined }[] {
  const seen: { id: string; params: Params | undefined }[] = []
  for (const key of RULE_KEYS) {
    const rule = rules[key]
    if (!rule?.on) continue
    for (const step of rule.steps) {
      for (const cond of step.conds) {
        if (cond.left) seen.push(resolveOperand(cond.left, cond.leftParams))
        if (cond.rightKind === 'operand' && cond.right) seen.push(resolveOperand(cond.right, cond.rightParams))
      }
    }
  }
  return seen
}

/** 선 수에 맞춘 선 꼴. 색은 겹치지 않게 차례로 고릅니다. */
function linesFor(count: number) {
  const lines: { color: string; size: number }[] = []
  for (let i = 0; i < count; i += 1) lines.push({ color: nextColor(lines.map((line) => line.color)), size: DEFAULT_LINE_SIZE })
  return lines
}

/** 수로 읽히는 매개변수만 씁니다 — 치는 중인 글자나 범위 밖 값으로 차트를 그리지
 *  않습니다(그 조건은 저장도 안 됩니다). */
function numbers(params: Params | undefined, keys: string[]): number[] | null {
  if (!params) return null
  const made = keys.map((key) => Number(params[key]))
  return made.every((value) => Number.isFinite(value) && value > 0) ? made : null
}

/** 조건이 쓰는 지표 가운데 **아래 칸에 서는 것**의 차트 이름 — 규칙 차례(진입 → 청산,
 *  단계·줄 차례)로 처음 나온 차례입니다. 검증 차트의 아래 칸 자리를 이 차례로 먼저
 *  나눕니다. */
export function ruleBottomOrder(rules: RuleSet | null | undefined): string[] {
  if (!rules) return []
  const made: string[] = []
  for (const { id } of operandsOf(rules)) {
    const name =
      id === 'rsi'
        ? 'RSI'
        : id === 'volume'
          ? 'VOL'
          : MACD_IDS.includes(id)
            ? ENGINE_MACD
            : STOCH_IDS.includes(id)
              ? ENGINE_STOCH
              : id === 'atr'
                ? ENGINE_ATR
                : null
    if (name && !made.includes(name)) made.push(name)
  }
  return made
}

/** 그 규칙들이 켜야 할 지표 설정. 규칙에 없는 지표는 돌려주지 않습니다 —
 *  부르는 쪽이 사용자가 켜 둔 지표 위에 이것만 덮습니다. */
export function ruleIndicators(rules: RuleSet | null | undefined): Record<string, IndicatorSetting> {
  if (!rules) return {}
  const periods = new Map<string, number[]>()
  const fixed = new Map<string, number[]>()
  for (const { id, params } of operandsOf(rules)) {
    if (id === 'ema' || id === 'ma' || id === 'rsi') {
      const name = id.toUpperCase()
      const period = numbers(params, ['period'])?.[0]
      const list = periods.get(name) ?? []
      if (period !== undefined && !list.includes(period)) list.push(period)
      periods.set(name, list)
    } else if (id === 'volume') {
      periods.set('VOL', periods.get('VOL') ?? [])
    } else {
      /* 매개변수가 한 벌인 지표는 **처음 만난 조건의 것**을 그립니다 — 차트에는
         그 지표가 하나만 섭니다. */
      const wanted: [string, string[]] | null = BOLLINGER_IDS.includes(id)
        ? ['BOLL', ['period', 'multiplier']]
        : MACD_IDS.includes(id)
          ? [ENGINE_MACD, ['fast', 'slow', 'signal']]
          : STOCH_IDS.includes(id)
            ? [ENGINE_STOCH, ['period', 'k', 'd']]
            : id === 'atr'
              ? [ENGINE_ATR, ['period']]
              : id === 'vwap'
                ? [ENGINE_VWAP, []]
                : null
      if (!wanted || fixed.has(wanted[0])) continue
      const values = wanted[1].length === 0 ? [] : numbers(params, wanted[1])
      if (values) fixed.set(wanted[0], values)
    }
  }

  const out: Record<string, IndicatorSetting> = {}
  for (const [name, list] of periods) {
    const def = indicatorDef(name)
    if (!def) continue
    if (name === 'VOL') {
      out[name] = defaultSetting(def, true)
    } else if (list.length > 0) {
      const params = [...list].sort((a, b) => a - b)
      out[name] = { on: true, params, lines: linesFor(params.length) }
    }
  }
  const LINE_COUNT: Record<string, number> = { BOLL: 3, [ENGINE_MACD]: 2, [ENGINE_STOCH]: 2, [ENGINE_ATR]: 1, [ENGINE_VWAP]: 1 }
  for (const [name, params] of fixed) {
    out[name] = { on: true, params, lines: linesFor(LINE_COUNT[name] ?? 1) }
  }
  /* 엔진 식 지표를 켰으면 같은 이름의 기본 지표는 이 차트에서 끕니다. */
  const OFF: [string, string][] = [
    [ENGINE_MACD, 'MACD'],
    [ENGINE_STOCH, 'KDJ'],
  ]
  for (const [engine, builtIn] of OFF) {
    const def = indicatorDef(builtIn)
    if (out[engine] && def) out[builtIn] = defaultSetting(def, false)
  }
  return out
}
