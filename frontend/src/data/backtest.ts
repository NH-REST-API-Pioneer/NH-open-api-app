/** 지난 봉으로 돌려 보기 — 설정 화면에서 지금 규칙(저장 전이어도)을 받아 둔 지난
 *  봉에 대 보고 「그때 돌렸으면 어땠을까」를 서버에게 셈하게 합니다.
 *
 *  **셈은 서버가 합니다.** 판정은 실행과 같은 코드이고, 체결은 지난 봉에 호가가
 *  없어 봉 체결 모형(`bar-v1`)으로 채웁니다. 그 가정은 답의 `assumptions` 에 실려
 *  오고 화면은 그것을 그대로 적습니다 — 화면이 다시 셈하면 서버와 갈립니다.
 *
 *  **아무것도 남기지 않습니다.** 저장·실행·기록·한도 어디에도 쓰지 않는 읽기
 *  요청 하나입니다. */
import { codeOfVersion, type StrategyVersion } from './strategyList'
import { sessionKeyOf, type SettingsDraft } from './strategyRules'
import { saveBodyOf, whyOf } from './strategyStore'

const ROUTE = '/api/strategy/backtest'

/** 범위 — 마지막 1·3 세션, 또는 받은 만큼. */
export type BacktestRange = '1d' | '3d' | 'all'

export interface BacktestTrade {
  openedAt: number
  closedAt: number
  side: 'buy' | 'sell'
  quantity: number
  entryPrice: number | null
  exitPrice: number | null
  /** 거래를 닫은 체결의 까닭 코드(`stop`·`take`·`signal`·`session-end`…). */
  reason: string | null
  grossPl: number
  fee: number
  /** 수수료를 뺀 손익. */
  pl: number
}

/** 판정하지 못한 조건 한 줄. */
export interface UnjudgedCondition {
  rule: string
  step: number
  cond: number
  operand: string
  /** `ruleNeverFires` · `stepBlocked` · `condFalse`. */
  effect: string
}

export interface BacktestAnswer {
  model: string
  assumptions: {
    delay?: number
    slippageTicks?: number
    limitFill?: string
    sameBarStopFirst?: boolean
    path?: string
    sessionEnd?: string
    /** 일봉 신호의 주문이 나가는 자리. 일봉 전략에서만 뜻이 있습니다. */
    dailyOrders?: string
    /** 만기일 진입 막기의 만기일(YYYY-MM-DD). 모르면 비어 있고 막지 않습니다. */
    expiryBlock?: string | null
    feePerContract?: number
    /** 판정에 쓴 값. `bar-close` 면 틱 판정 전략도 봉이 끝난 값으로 셈한 것입니다.
     *  칸이 없으면 화면은 아무것도 덧붙이지 않습니다. */
    evalBasis?: string
    /** 지난 봉에 값이 없어 판정하지 못한 조건들(호가처럼 실행이 그 순간 적는 값).
     *  조건 하나가 한 줄이고 단계·조건 번호는 1부터입니다. `effect` 는 그 조건이 결과에
     *  미치는 것입니다. 칸이 없으면 화면은 아무것도 덧붙이지 않습니다. */
    unjudged?: UnjudgedCondition[]
    /** 일봉 + 신규 진입 시간인 전략에서 진입을 어디에 냈는지. `next-session-open` 이면
     *  시간이 그 세션 안에서 열린다고 보고 다음 봉 시가에 낸 것입니다. 해당 없으면 비어
     *  있습니다. */
    dailyEntryWindow?: string | null
    /** 증거금 예산 검사를 건너뛰었는지와 그 까닭(실행과 같은 판정·같은 글). */
    budgetUnchecked?: boolean
    budgetUncheckedWhy?: string | null
    /** 세션 끝 정리를 켠 전략에서 그 정리를 어디까지 셈했는지. `followed-sessions-only`
     *  는 뒤에 다른 세션이 이어지는 세션만, `not-applied-daily` 는 일봉이라 셈하지 않음.
     *  끈 전략은 비어 있습니다. */
    sessionEndFlat?: string | null
  }
  bars: {
    from: number | null
    to: number | null
    /** 이 범위에서 셈한 봉 수. */
    count: number
    /** 받아 둔 봉 수와, 지표가 서는 데 드는 봉 수. */
    have: number
    need: number
    /** 받아 둔 봉에 든 세션 수. */
    sessions: number
  }
  /** 지표가 설 만큼 봉이 있는지. */
  enough: boolean
  signals: number
  fills: number
  trades: BacktestTrade[]
  pl: number
  fee: number
  wins: number
  losses: number
  winRate: number | null
  maxDrawdown: number
  /** 자료의 마지막 세션에서 정리하지 않은 보유. 손익에는 안 들어갑니다. */
  openPosition: {
    side: 'buy' | 'sell'
    quantity: number
    avgPrice: number | null
    lastPrice: number | null
    openPl: number | null
  } | null
  currency: string | null
}

/** 셈 요청의 몸. **저장 요청과 같은 몸**(`saveBodyOf`)에 셈할 것을 더합니다.
 *  수량·슬리피지는 비워 서버 기본(설정의 주문당 수량, 1틱)을 씁니다. 수수료는
 *  카드의 「계약당 수수료」 칸 값이고, 설정에 저장하지 않는 셈만의 값입니다.
 *  음수도 그대로 보내 서버가 받지 않는 까닭을 답하게 합니다. */
export function backtestAsk(
  version: StrategyVersion,
  draft: SettingsDraft,
  range: BacktestRange,
  feePerContract = 0,
): Record<string, unknown> {
  return {
    ...saveBodyOf(version, draft),
    code: codeOfVersion(version),
    session: sessionKeyOf(version.market, draft.aux.session),
    range,
    feePerContract,
  }
}

export type BacktestReply =
  | { kind: 'done'; answer: BacktestAnswer }
  /** 다른 셈이 돌고 있습니다(409). 부르는 쪽이 조금 뒤 다시 보냅니다. */
  | { kind: 'busy'; why: string }
  | { kind: 'failed'; why: string }

/** 셈 하나를 청합니다. 끊긴 요청(`signal`)은 `null` 입니다. */
export async function postBacktest(
  ask: Record<string, unknown>,
  signal: AbortSignal,
): Promise<BacktestReply | null> {
  try {
    const answer = await fetch(ROUTE, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(ask),
      signal,
    })
    if (answer.status === 409) return { kind: 'busy', why: await whyOf(answer) }
    if (!answer.ok) return { kind: 'failed', why: await whyOf(answer) }
    return { kind: 'done', answer: (await answer.json()) as BacktestAnswer }
  } catch {
    if (signal.aborted) return null
    return { kind: 'failed', why: '서버에 닿지 않습니다' }
  }
}
