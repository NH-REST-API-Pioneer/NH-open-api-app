/* 검증·진행 화면이 다루는 실행 한 줄의 모양.
 *
 * **이름은 서버가 내는 그대로입니다.** 옮겨 적으면 한 값이 두 이름을 갖고,
 * 어느 쪽이 맞는지 답할 자리가 없어집니다. 한국어로 바꾸는 것은 화면이
 * 그릴 때뿐입니다.
 *
 * 값의 뜻과 단위는 여기서 정해 둡니다 — 종목 이름·자릿수·승수는 **줄에 없고**
 * 종목 코드로 색인에서 찾습니다(`data/instruments.ts`). 줄에 적어 두면 만기가
 * 넘어갈 때 이름과 실제 종목이 갈립니다.
 */
import { currencyCode } from '../lib/number'
import type { Environment } from './environment'
import { ceilWon } from './productInfo'

/* ── 검증(가상 장부) ────────────────────────────────── */

/** 실행이 도는 장부. 서버의 `runs.MODES` 와 같은 셋입니다. 종이(`paper`)는
 *  계좌에 아무것도 안 보내고, 모의 계좌(`sim`)와 실전 계좌(`real`)는 그 계좌로
 *  실제 주문이 나갑니다. */
export type RunMode = 'paper' | 'sim' | 'real'

/** 계좌로 주문이 나가는 갈래. 진행 탭이 세우고 보는 것은 이 둘입니다. */
export type AccountMode = 'sim' | 'real'

/** 실행 자금의 기본값 — 통화마다 비슷한 크기의 돈입니다. **검증 추가와 진행 거래 추가가
 *  이 표 하나를 씁니다.** 표에 없는 통화는 기본값을 짓지 않습니다(환율을 지어내지
 *  않음) — 칸이 비고 사용자가 채웁니다. */
const CASH_DEFAULT: Record<string, string> = {
  KRW: '50000000',
  USD: '50000',
  JPY: '7500000',
  HKD: '400000',
  EUR: '45000',
  SGD: '65000',
}

/** 그 통화의 실행 자금 기본값(숫자 글자). 없으면 `null` 입니다. */
export function cashDefaultOf(code: string): string | null {
  return CASH_DEFAULT[code] ?? null
}

/** 기본값이 없는 통화에서 자금 칸이 비었을 때의 말. */
export const NO_CASH_DEFAULT = '기본값 없음 — 칸을 채우세요'

/** 계좌 갈래인지. 진행 탭의 목록·중지 대상이 이 판정 하나를 씁니다. */
export function isAccountMode(mode: string): mode is AccountMode {
  return mode === 'sim' || mode === 'real'
}

/** 앱 시뮬레이션(종이) 실행인지. 검증 탭의 목록·고른 실행·일괄 대상이 이 판정
 *  하나를 씁니다 — 계좌 실행은 진행 탭에서만 보고 다룹니다. */
export function isPaperRun(run: { mode: string }): boolean {
  return run.mode === 'paper'
}

export type RunMarket = 'domestic' | 'overseas'

/** 실행이 시세를 받는 시장. 국내 세션 키는 `domestic` 으로 시작합니다 — 실시간
 *  연결 상태가 시장마다 따로 오므로, 다시 붙은 시장의 실행만 고를 때 씁니다. */
export function runMarketOf(run: { session: string }): RunMarket {
  return run.session.startsWith('domestic') ? 'domestic' : 'overseas'
}

/** 진행 탭에서 도는 계좌 실행 — 끝나지 않은 모의·실전 계좌 실행의 수, 실전이
 *  있는지, 그리로 건너갈 때 열 첫째(**실전이 먼저**)입니다. 검증 탭이 「거래 중 n
 *  — 진행에서 보기」를 세우는 데 씁니다. */
export function tradingOf(runs: readonly { id: string; mode: string; state: string }[]): {
  count: number
  hasReal: boolean
  firstId: string | null
} {
  const live = runs.filter((run) => isAccountMode(run.mode) && run.state !== 'ended')
  const real = live.find((run) => run.mode === 'real')
  return { count: live.length, hasReal: real !== undefined, firstId: (real ?? live[0])?.id ?? null }
}

/** 접속 환경에서 세울 수 있는 계좌 갈래 — 모의 환경이면 모의 계좌, 실전
 *  환경이면 실전 계좌입니다. 환경을 모르면 `null` 입니다. */
export function accountModeOf(active: Environment | null): AccountMode | null {
  if (active === 'paper') return 'sim'
  if (active === 'real') return 'real'
  return null
}

/** 서버가 준 「지금 세울 수 있는 계좌 갈래」를 읽습니다. **가장 좁게** 읽습니다 —
 *  배열이 아니면 빈 목록이고, 모르는 값은 버립니다. 서버가 이 칸을 안 주면
 *  계좌 실행을 세우는 길이 닫힙니다. */
export function accountModesOf(raw: unknown): AccountMode[] {
  if (!Array.isArray(raw)) return []
  return raw.filter((one): one is AccountMode => typeof one === 'string' && isAccountMode(one))
}

/** 실행이 놓인 자리. **여덟입니다** — 화면 낱말은 서버가 `stateLabel`
 *  로 함께 주므로 화면이 표를 또 두지 않습니다. */
export type RunState =
  | 'armed'
  | 'entering'
  | 'holding'
  | 'exiting'
  | 'paused'
  | 'attention'
  | 'reconciling'
  | 'ended'

/** 시세가 들어오고 있는지. `idle` 은 아직 안 붙은 것이고 `gap` 은 끊긴 것입니다 —
 *  둘은 다른 말입니다. **이상할 때만 색을 씁니다**: 정상이 늘 초록이면 화면에
 *  늘 초록이 켜져 있어 이상이 눈에 띄지 않습니다. */
export type FeedState = 'idle' | 'live' | 'gap'

/** 종이 장부로 도는 실행 한 줄.
 *
 *  **보유·손익·봉 수·증거금 근거·성과 수 같은 칸은 `null` 로 올 수 있습니다.** 서버가
 *  그 실행의 장부를 읽지 못하면 칸은 그대로 두고 값만 비워 보냅니다 — 「모른다」와
 *  「0」은 다른 말입니다. 화면은 그 값을 0 으로 세지 않고 「—」로 적습니다. */
export interface VerifyRun {
  id: string
  /** 어느 버전이 도는가. **전략 이름은 여기 없습니다** — 목록에서 이 id 로
   *  찾습니다. 실행에 적어 두면 전략 이름을 고칠 때 갈립니다. */
  version: string
  /** 이 실행이 붙은 종목. 이름·자릿수·승수는 이 코드로 색인이 답합니다. */
  code: string
  session: string
  /** 그 세션을 화면에 적는 말(「국내 주간」). **서버가 함께 줍니다** — 키를
   *  글자로 옮기는 표를 화면이 또 두면 두 표가 갈립니다. */
  sessionLabel: string
  market: string
  /** 그 실행의 손익 통화(`KRW`·`USD`·`HKD`…). **서버가 품목에서 정해 줄에 싣습니다** —
   *  해외는 품목마다 통화가 다릅니다. 칸이 없으면 시장으로 읽습니다
   *  (`runCurrencyOf`). */
  currency?: string
  /** 어느 장부로 도는가. `paper` 는 종이 장부라 계좌에 아무것도 안 보내고,
   *  `sim`·`real` 은 **그 계좌(모의·실전)로 실제 주문이 나갑니다**. */
  mode: RunMode
  /** 확인창을 지난 시각(ms). **서버 시계입니다.** 계좌 실행은 이 값이 없으면
   *  한 건도 안 냅니다. 종이 실행에는 없고(`null`), 그 칸을 아직 안 내는
   *  서버에서는 아예 안 옵니다 — 셋 다 「안 지났다」입니다. */
  approvedAt?: number | null
  state: RunState
  /** 그 상태를 화면에 적는 말(「감시 중」·「보유 중」…). */
  stateLabel: string
  feed: FeedState
  /** 마지막으로 체결을 받은 시각(ms). 끊겼을 때 「언제까지 받았나」를 답합니다. */
  feedAt: number
  /** 주문당 계약 수. 「검증 추가」에서 정한 값입니다. */
  qty: number
  /** 가상 자금. */
  cash: number
  /** 계약 하나에 드는 돈. **모르면 `null`** 입니다.
   *
   *  **지금 그리는 자리는 없습니다** — 화면은 근거가 함께 오는 `perContract` 를
   *  씁니다. 서버가 내는 칸이라 받는 자리는 남겨 둡니다: 지웠다가 다른 화면이
   *  쓰기 시작하면 그 줄만 조용히 비어 옵니다. */
  margin: number | null
  /** 나가 있는 **진입** 주문의 남은 수량. 서버의 한도 검사가 보는 값과 같은
   *  자리에서 옵니다 — 화면이 세는 사용 증거금이 서버가 막는 셈과 갈리면,
   *  사용자는 막힌 까닭을 화면에서 못 찾습니다. */
  openEntry: number | null
  /** 계약 하나에 드는 돈. `margin` 과 같은 값이지만 **근거가 함께 옵니다.** */
  perContract: number | null
  /** 그 값이 어떻게 나온 것인지. 숫자만 받으면 화면이 어림을 확정값으로
   *  적습니다 — 낱말은 `MARGIN_BASIS` 가 옮깁니다. */
  perContractBasis: string | null
  /** 증거금 예산을 정했는데 계약당 증거금을 몰라 **서버가 예산 검사를 건너뛰는지**.
   *  해외 선물·스프레드처럼 계약당 칸이 없는 품목입니다. 칸이 없으면 거짓입니다. */
  budgetUnchecked?: boolean
  /** 가상 보유. **체결에서 셉니다.** 0 이면 들고 있는 것이 없습니다. */
  position: number | null
  /** 보유 방향. **들고 있는 것이 없으면 `null`** 입니다 — 방향은 보유가 있을
   *  때만 있는 값이라, 0 인 자리에 매수·매도 중 하나를 적어 두면 그것이
   *  「지금 그쪽으로 들고 있다」로 읽힙니다. */
  side: 'buy' | 'sell' | null
  /** 평균가. **절대값입니다** — 들고 있는 것이 없으면 `null` 입니다. */
  avgPrice: number | null
  /** 평가손익. 방향이 부호를 정합니다 — 매도 보유는 값이 내려야 이익입니다. */
  pl: number | null
  /** 그 거래일의 손익. 하루 손실 한도가 보는 값입니다. */
  dayPl: number | null
  /** 그 거래일에 끝에서부터 이어진 손실 거래 수. 연속 손실 한도가 보는 값이고,
   *  거래일이 바뀌면 다시 셉니다. 서버가 안 주면 비어 있습니다. */
  lossStreak?: number | null
  /** 지금까지 물린 수수료. */
  fee: number | null
  /** 마지막 체결가. 아직 하나도 못 받았으면 `null` 입니다. */
  lastPrice: number | null
  /** 받아 둔 봉 수. */
  bars: number | null
  /** 지표가 판정을 시작하려면 필요한 봉 수. **한 벌(`GET /runs/{id}`)에만
   *  있습니다** — 목록 줄에는 없어, 모자란지 아닌지는 고른 실행에서만 압니다. */
  warmup?: number | null
  /** 종이 체결 모형의 이름. 화면이 「체결 가정」에 그대로 적습니다. */
  model: string
  /** 이 실행이 조건을 평가하는 방식(「마감」·「틱」). 실행을 시작할 때의 설정입니다.
   *  칸이 없으면 틱 판정이 아닌 것으로 읽습니다(`isTickRun`). */
  evalMode?: string | null
  /** 아래 넷은 **목록 줄에만** 있습니다(한 벌에는 없습니다). */
  tickSize?: number | null
  multiplier?: number | null
  daysLeft?: number | null
  /** 만기가 가까워 신규 진입을 막는 자리인지. */
  expiring?: boolean | null
  /** 아직 답을 못 받은 주문 수. **계좌로 나간 것만** 셉니다 — 종이 실행에는
   *  없습니다. 0 보다 크면 보낸 것과 받은 것이 아직 안 맞는 중입니다. */
  pending?: number | null
  /** 실행을 세운 접속 환경. 세운 뒤로 안 바뀝니다. 종이 실행은 `null` 입니다. */
  environment?: Environment | null
  /** 규칙이 판정에서 참이 된 횟수(안 낸 신호 포함). 비어 올 수 있습니다. */
  signalCount?: number | null
  /** 이 실행의 체결 수. */
  fillCount?: number | null
  /** 마지막으로 규칙이 참이 된 봉의 시각(ms). 없으면 `null`. */
  lastSignalAt?: number | null
  /** 실현 손익(낸 수수료 포함). `pl` = 실현 + 평가. */
  realizedPl?: number | null
  /** 평가 손익. 보유가 있는데 마지막가를 모르면 `null`. */
  openPl?: number | null
  /** 오늘(한국 날짜) **안 낸 신호** 수 — 규칙이 참이었는데 주문을 내지 않은 봉의
   *  수입니다. 까닭은 막힘 이벤트(`kind` 가 `blocked`)에 있습니다. 비어 올 수 있습니다. */
  unsentToday?: number | null
  /** **값을 못 받는 중.** 앞 박자에 받은 값이 그대로 선 것이라, 줄을 흐리게
   *  두어 「지금 값이 아니다」를 말합니다. 칸이 사라지면 원래대로 돌아옵니다 —
   *  서버가 붙였다 뗐다 하는 표시라 화면이 따로 기억하지 않습니다. */
  stale?: boolean
  /** 마지막으로 받은 매수1·매도1 호가와 잔량. 시세가 끊겼거나 아직 못 받았으면
   *  `null` 이고, 칸이 없을 수도 있습니다. */
  bid1?: number | null
  ask1?: number | null
  bid1Qty?: number | null
  ask1Qty?: number | null
  /** 그 호가를 받은 시각(ms). 호가가 없으면 `null` 입니다. */
  quoteAt?: number | null
  /** 이 실행의 증거금 예산. 예산을 정하지 않았으면 `null` 이고, 화면은 그때 실행
   *  자금(`cash`)을 대신 적습니다. */
  marginBudget?: number | null
  /** 묶인 증거금 — (보유 + 열린 진입 잔량) × 계약당 증거금. 계약당 증거금을 모르면
   *  `null` 이고 까닭은 `perContractBasis` 가 말합니다. */
  marginUsed?: number | null
  /** 예산에서 묶인 증거금을 뺀 값. 둘 중 하나라도 모르면 `null` 입니다. */
  marginLeft?: number | null
  /** 지금 가격으로 신호가 나면 나갈 주문. `buy`·`sell` 은 그 방향의 진입 주문이고,
   *  `exit` 는 보유를 청산 규칙으로 닫는 주문입니다(보유가 없으면 `null`). 가격을
   *  셈하지 못한 칸은 `null` 입니다. 손절·익절·사용자 청산은 시장가 전량이라 `exit`
   *  와 다릅니다. */
  expectedOrder?: {
    buy?: ExpectedOrder | null
    sell?: ExpectedOrder | null
    exit?: (ExpectedOrder & { side: 'buy' | 'sell' }) | null
  } | null
}

/** 신호가 나면 나갈 주문 하나. 시장가·STOP-M 은 주문가격이 `null` 이고, STOP 이
 *  아니면 스탑가격이 `null` 입니다. */
export interface ExpectedOrder {
  orderType: string
  price: number | null
  stopPrice: number | null
}

/** 종이 체결 한 줄. **값도 시각도 절대값입니다** — 「몇 봉 전」으로 두면 봉
 *  종류를 바꿀 때마다 같은 체결이 다른 자리로 옮겨 갑니다. */
export interface VerifyFill {
  orderId: string
  runId: string
  /** 난 시각(ms). 표지가 앉을 봉은 이 시각으로 찾습니다. */
  time: number
  price: number
  quantity: number
  side: 'buy' | 'sell'
  /** 진입인지 청산인지. */
  intent: 'entry' | 'exit'
  /** 그 체결이 난 까닭. **서버가 영어 코드로 줍니다**(`signal`·`stop`·`take`·
   *  `trail`·`exit`·`flatten`) — 화면에 세울 말은 `reasonWord` 가 옮깁니다. */
  reason: string
  /** 체결번호. 계좌가 준 번호이거나, 계좌가 안 줄 때 장부가 매긴 번호
   *  (`주문번호#차례`)입니다. **화면에 세우지 않고 열쇠로만 씁니다**(`fillKey`).
   *
   *  **서버는 이 칸을 반드시 싣습니다.** 비어 오는 것은 그 약속이 깨진
   *  것이고, 그때 열쇠가 시각으로 내려앉습니다. */
  execNo?: string
  /** 계좌가 준 주문번호. **모의 계좌 실행의 체결에만 옵니다** — 가상 장부의
   *  체결에는 계좌가 없어 이 칸이 없습니다. 위 `orderId` 는 장부가 매긴 번호라
   *  계좌의 주문번호와 다릅니다. */
  orderNo?: string
  /** 그 체결 한 건의 수수료. 계약당 설정값으로 센 값이라 계좌가 실제로 물린 값이
   *  아닙니다. 옛 기록에는 칸이 없습니다. */
  fee?: number
  /** 그 주문을 낸 순간의 당시 지표. **셋이 다른 말입니다** — 칸이 없으면 옛 기록,
   *  `null` 이면 전략 엔진이 내지 않은 주문, 값이 있으면 그 봉과 그 버전 규칙이 쓰는
   *  값들입니다(준비 전이면 값이 `null`). */
  snapshot?: FillSnapshot | null
  /** 가상 장부의 체결임. 계좌 체결과 한 표에 섞이지 않게 줄이 들고 다닙니다. */
  virtual: boolean
  /** 그 청산 체결로 확정된 손익(실행의 통화). 진입 체결이거나 서버가 안 주면 없습니다. */
  realized?: number | null
}

/** 체결 한 건의 당시 지표. `barTime` 은 그 봉의 **시작** 시각(ms)이고, 봉이 하나도
 *  없었으면 `null` 입니다. `values` 는 피연산자 id 마다 값이고 준비 전이면 `null`
 *  입니다 — 봉 시작 시각(`clock`)은 분이며 야간에는 하루(1440)를 넘어 이어 셉니다. */
export interface FillSnapshot extends TickMark {
  barTime: number | null
  values: Record<string, number | null>
}

/** 틱 판정에서 난 줄에 서버가 붙이는 표지. 봉 마감 판정이면 칸이
 *  없습니다.
 *  - `partialBar`: 아직 안 끝난 봉으로 판정했는지
 *  - `judgedAt`: 판정한 순간(ms)
 *  - `barTime`: 그때 진행 중이던 봉의 시작 시각(ms) */
export interface TickMark {
  evalMode?: string | null
  partialBar?: boolean
  judgedAt?: number | null
  barTime?: number | null
}

/** 체결 하나를 가리는 열쇠. **저장소·표·차트 표지가 같은 것을 씁니다** — 한
 *  곳만 고치면 같은 체결이 표와 표지에서 다른 것으로 갈립니다.
 *
 *  **주문번호만으로는 겹칩니다** — 한 주문이 여러 번에 나뉘어 체결되고, 한
 *  호가의 여러 단계를 먹으면 **같은 밀리초에** 여러 줄이 납니다. 그래서
 *  체결번호까지 봅니다.
 *
 *  체결번호가 없으면 시각으로 내려앉습니다. **지금 서버에서는 안 닿는
 *  자리입니다** — 그 약속이 깨진 날 같은 밀리초의 두 체결이 다시 한 줄로
 *  뭉치는데, 화면은 멀쩡해 보입니다. 번호와 시각은 접두어로 갈라 두어,
 *  한쪽이 다른 쪽의 값과 같은 글자가 되어도 섞이지 않습니다. */
export function fillKey(fill: VerifyFill): string {
  const one = fill.execNo ? `n${fill.execNo}` : `t${fill.time}`
  return `${fill.runId}|${fill.orderId}|${one}`
}

/** 이벤트 하나를 가리는 열쇠. 같은 순간에 같은 갈래가 둘 날 수 있어 글까지 봅니다.
 *  방송을 이어 붙이는 자리와 알림이 같은 열쇠를 씁니다. */
export function eventKey(one: VerifyEvent): string {
  return `${one.runId}|${one.time}|${one.kind}|${one.text}`
}

/** 계약당 증거금이 **어떻게 나온 값인지**. 서버가 영어 코드로 줍니다.
 *
 *  - `margin` — 거래소가 정한 계약당 개시증거금. 확정값입니다.
 *  - `premium-now` — 옵션 매수라 프리미엄 × 승수로 **지금 값에서 잰 것**입니다.
 *    틱마다 바뀌므로 확정값처럼 적으면 안 됩니다.
 *  - `sell-unknown` — 옵션 매도는 거래소가 셈하는 값이라 이 앱이 셈하지 못합니다.
 *  - `mixed` — 매수·매도가 섞여 하나의 계약당 값을 낼 수 없습니다.
 *
 *  **모르는 코드는 빈 말입니다.** 서버가 새 근거를 내기 시작했을 때 화면이
 *  지어낸 설명을 붙이면, 틀린 설명이 값 옆에 섭니다. */
const MARGIN_BASIS: Record<string, string> = {
  'premium-now': '지금 값 어림',
  'sell-unknown': '매도는 거래소가 셈',
  mixed: '매수·매도 섞임',
  'no-margin-field': '이 품목에는 계약당 증거금 칸이 없음',
}

export function marginBasisWord(basis: string | null): string {
  if (basis === null) return ''
  return MARGIN_BASIS[basis] ?? ''
}

/** 그 근거로 계약당 값을 낼 수 있나. 못 내는 둘은 **「모름」**이고, 셈도 못 합니다.
 *  근거가 비어 왔으면(`null`) 그것도 「모름」입니다. */
export function marginKnown(basis: string | null): boolean {
  return basis !== null && basis !== 'sell-unknown' && basis !== 'mixed' && basis !== 'no-margin-field'
}

/** 실행 자금이 증거금에 못 미칠 때의 말과, 증거금을 몰라 견주지 않았을 때의 말.
 *  검증 추가 창·실행 카드·상세가 같은 글자를 씁니다. */
export const FUNDS_SHORT = '자금이 증거금보다 적어 실제로는 진입할 수 없습니다'
export const FUNDS_UNKNOWN = '계약당 증거금을 몰라 자금과 견주지 않았습니다'

/** 전략 실행의 수수료가 **설정에서 센 값**이라는 설명. 실행 추가 창·분석 화면의
 *  수수료 자리가 같은 글자를 씁니다 — 체결 알림에 수수료 칸이 없어, 계좌가 실제로
 *  물린 수수료가 아니라 실행을 시작할 때 넣은 계약당 값으로 셉니다. */
export const FEE_ASSUMED = '실행을 시작할 때 넣은 계약당 수수료로 셉니다 — 실제 수수료와 다를 수 있습니다'

/** 그 버전 설정의 「주문당」 계약 수. 실행 추가 창과 검증 추가 창의 수량 칸이 이 값으로
 *  시작합니다 — 창이 따로 1 로 시작하면 설정을 고쳐도 실행은 창 값으로 돕니다.
 *  양의 정수가 아니거나 비어 있으면 `null` 이고, 그때 창은 1 로 시작합니다. */
export function perOrderOf(aux: { perOrder?: string } | null | undefined): number | null {
  const text = (aux?.perOrder ?? '').trim()
  return /^[1-9]\d*$/.test(text) ? Number(text) : null
}

/** 수량 칸을 설정과 다르게 고쳤을 때 칸 아래에 서는 한 줄. */
export function perOrderNote(setting: number): string {
  return `설정 주문당 ${setting}계약과 다릅니다 — 이 실행에만 씁니다`
}

/** 자금과 증거금을 견준 결과. `short` 는 계약당 값과 필요액을 함께 싣습니다 —
 *  「얼마가 모자라나」를 문장 곁에 적기 위해서입니다. */
export type FundsVerdict =
  | { kind: 'unknown' }
  | { kind: 'enough' }
  | { kind: 'short'; each: number; need: number }

/** 실행 자금 < 계약당 증거금 × 주문당 수량인지. **셈은 일반주문 폼의 개시증거금
 *  어림과 같습니다** — 원은 곱한 뒤 원 단위로 올려(`ceilWon`) 정수끼리 견줍니다.
 *  계약당 값이 없거나 0 이하면 **모름**입니다: 0 으로 셈하면 어떤 자금도 넉넉해
 *  보여 경고가 거짓으로 사라집니다. */
export function fundsVerdict(
  each: number | null | undefined,
  qty: number,
  cash: number,
  currency: string,
): FundsVerdict {
  if (each == null || !Number.isFinite(each) || each <= 0) return { kind: 'unknown' }
  if (!Number.isFinite(qty) || qty <= 0 || !Number.isFinite(cash)) return { kind: 'unknown' }
  const won = currencyCode(currency) === 'KRW'
  const need = won ? ceilWon(each * qty) : each * qty
  const have = won ? Math.round(cash) : cash
  return have < need ? { kind: 'short', each: won ? ceilWon(each) : each, need } : { kind: 'enough' }
}

/** 선 실행의 자금 판정. **서버가 준 계약당 값**으로 셉니다. 근거가 「모름」이거나
 *  옵션 매수(지금 값 어림)거나 서버가 예산 검사를 건너뛰는 실행이면 모름입니다. */
/** 옵션을 **팔고 들어가는** 전략의 경고 한 줄 — 옵션 품목이고 매도 진입 규칙이 켜져
 *  있으면 그 문장, 아니면 `null` 입니다. 서버는 옵션 매도의 계약당 증거금을 모릅니다
 *  (`perContractBasis` 의 매도 갈래). 해외는 예산과 견주지 않고 매도 주문을 내고, 국내는
 *  증거금 예산이 늘 있어 매도 진입을 막고 청산만 냅니다 — 그래서 **글만 시장으로
 *  가릅니다.** 시작 전에는 실행이 없어 서버 표지를 받을 길이 없어 화면이 이 거울로
 *  경고하고, 실행이 선 뒤의 카드·상세는 서버 표지로만 말합니다. */
export function optionSellWarning(
  market: string,
  productKind: string | undefined,
  rules: { sellEntry?: { on?: boolean } } | null | undefined,
): string | null {
  if (productKind !== 'option' || rules?.sellEntry?.on !== true) return null
  return market === 'overseas'
    ? '증거금을 미리 견주지 않고 매도 주문이 나갑니다 — 손실이 실행 자금을 넘을 수 있습니다'
    : '계약당 증거금을 몰라 매도 진입은 막힙니다 — 청산만 나갑니다'
}

export function runFunds(run: VerifyRun, currency: string): FundsVerdict {
  if (run.budgetUnchecked || !marginKnown(run.perContractBasis) || run.perContractBasis === 'premium-now') {
    return { kind: 'unknown' }
  }
  return fundsVerdict(run.perContract, run.qty, run.cash, currency)
}

/** 체결이 난 까닭을 화면에 적는 말. **표가 여기 하나입니다** — 검증 표와
 *  진행 표가 같은 코드를 다른 말로 적으면 같은 체결이 화면마다 달라집니다.
 *
 *  모르는 코드는 **그대로 세웁니다.** 서버가 새 까닭을 내기 시작했을 때
 *  화면이 그것을 지우면, 왜 팔렸는지가 어디에도 안 남습니다. */
const REASON_WORD: Record<string, string> = {
  signal: '조건 충족',
  stop: '손절',
  take: '익절',
  /* 「추적 청산」이 아니라 「추적」입니다 — 용도 칸은 「청산 · 추적」으로 서서,
     한 칸에 「청산」이 두 번 서지 않습니다. 손절·익절과 같은 짝입니다. */
  trail: '추적',
  exit: '규칙',
  flatten: '사용자 청산',
  /* 세션 끝 몇 분 전에 보유를 닫은 청산입니다. */
  'session-end': '세션 끝 정리',
  /* 보유 중 반대 방향 진입 규칙이 참이 되어 낸 청산입니다. 용도 칸이 「청산 · 반대
     신호」로 서므로 「청산」을 다시 붙이지 않습니다(추적과 같은 짝). */
  opposite: '반대 신호',
}

/** 그 코드가 가리키는 말. **모르는 코드는 빈 글자입니다** — 서버와 화면이
 *  주고받는 열쇠는 화면에 세울 말이 아닙니다. 「청산 · exit」처럼 서면 읽는
 *  사람이 그 낱말의 뜻을 코드에서 찾아야 합니다. 까닭이 안 서면 갈래
 *  낱말(「청산」)만 남고, 그것은 이미 참말입니다. */
export function reasonWord(code: string): string {
  return REASON_WORD[(code ?? '').trim()] ?? ''
}

/** 머리 띠에 적는 연속 손실 「n/한도」. **한도를 정했고 이어진 손실이 1 이상일
 *  때만** 글자가 있고, 아니면 빈 글자입니다. 두 값을 나란히 적을 뿐 「막힘」을
 *  셈해 내지 않습니다 — 한도에 닿아 진입이 막힌 것은 서버가 이벤트로 알립니다.
 *  한도는 그 실행이 도는 버전의 설정 값(`aux.lossStreak`)입니다. */
export function streakText(run: VerifyRun | null, limit: string | undefined): string {
  const cap = Number((limit ?? '').trim())
  const now = run?.lossStreak ?? 0
  if (!Number.isInteger(cap) || cap < 1 || now < 1) return ''
  return `연속 손실 ${now}/${cap}`
}

/** 그 실행의 금액을 적을 통화 — 실행 줄의 통화가 먼저이고(`KRW` 는 「원」), 없으면
 *  부르는 쪽이 넘긴 값(시장·전략으로 셈한 통화)입니다. 카드·상세·체결 표가 모두 이
 *  하나로 적습니다. */
export function runCurrencyOf(run: Pick<VerifyRun, 'currency'>, fallback: string): string {
  const code = (run.currency ?? '').trim().toUpperCase()
  if (code === 'KRW') return '원'
  return /^[A-Z]{3}$/.test(code) ? code : fallback
}

/** 「확인 필요」 실행을 「실행 종료」에서 빼는 까닭. 빼지 않으면 `null` 입니다.
 *
 *  서버는 「확인 필요」 실행도 **그 실행의 장부에 보유·미체결이 없으면** 끝냅니다 —
 *  끝내기는 계좌로 요청을 보내지 않습니다. 줄이 아는 값(보유·진입 미체결·답 대기)으로
 *  남은 것이 보이면 미리 빼고 그 까닭을 적습니다. 청산 주문처럼 줄에 없는 값은 서버가
 *  남은 것을 적어 거절하고, 그 문장이 섭니다. 「확인 필요」에서는 청산도 막히므로
 *  남은 것이 있으면 계좌를 맞춘 뒤 「확인」으로 풀어야 합니다. */
export function attentionEndWhy(run: Pick<VerifyRun, 'position' | 'openEntry' | 'pending'>): string | null {
  if ((run.position ?? 0) !== 0) return '확인 필요 — 보유가 남아 끝낼 수 없습니다'
  if ((run.openEntry ?? 0) > 0 || (run.pending ?? 0) > 0) return '확인 필요 — 미체결 주문이 남아 끝낼 수 없습니다'
  return null
}

/** 실행이 남긴 한 줄. */
export interface VerifyEvent extends TickMark {
  runId: string
  time: number
  /** 어떤 일인지의 갈래(`fill`·`ready`…). 화면은 글로 적습니다. `blocked` 는 조건이
   *  참이었는데 주문을 내지 않은 일(「안 낸 신호」)이고, 까닭이 `rejected` 이면 낸
   *  주문을 계좌가 거부한 일입니다(`isRejectedEvent`). */
  kind: string
  text: string
  /** 사건의 코드. 막힘 이벤트는 까닭(`daily-loss`·`margin-unknown` …), 상태 이벤트는
   *  그 일(`account-loss`·`reconcile-resume`)입니다. 옛 기록에는 없습니다. */
  reason?: string | null
  /** 막힘 이벤트의 까닭 글. 옛 기록에는 없습니다. */
  why?: string | null
}

/** 잔고 곡선의 한 점. */
export interface VerifyPoint {
  time: number
  equity: number
}

/** 끝난 거래 한 건. */
export interface VerifyTrade {
  [field: string]: unknown
}

/** 아직 안 채워진 가상 주문 한 줄. **체결 줄과 이름이 같습니다** — 화면이 두
 *  탭을 한 표로 그리는데 칸 이름이 갈리면 같은 주문이 탭마다 다르게 보입니다.
 *
 *  **쌓이는 값이 아닙니다.** 지금 열려 있는 것 전부라, 받는 쪽은 이 목록을
 *  **덮어씁니다** — 이어 붙이면 채워진 주문이 표에서 안 사라집니다. */
export interface VerifyOrder extends TickMark {
  orderId: string
  runId: string
  /** 낸 시각(ms). 체결 줄의 `time` 은 채워진 시각이고, 이 줄은 낸 시각입니다. */
  time: number
  side: 'buy' | 'sell'
  intent: 'entry' | 'exit'
  reason: string
  /** 낸 수량과 남은 수량. **둘 다 옵니다** — 부분체결이면 「3 중 1 남음」이
   *  되어야 하는데 남은 것만으로는 그 말을 세울 수 없습니다. */
  quantity: number
  remaining: number
  /** 값이 없는 칸은 `null` 입니다 — 시장가에 0 을 적으면 「0원에 걸었다」가 됩니다. */
  price: number | null
  stopPrice: number | null
  orderType: string
  status: string
  virtual: boolean
  /** 계좌가 준 주문번호. 모의 계좌 실행에만 오고, 없으면 `null` 입니다. */
  orderNo?: string | null
}

/** 실행 하나의 한 벌. `GET /api/strategy/runs/{id}` 가 내는 모양입니다. */
export interface VerifySnapshot {
  run: VerifyRun
  fills: VerifyFill[]
  events: VerifyEvent[]
  curve: VerifyPoint[]
  trades: VerifyTrade[]
  /** 지금 열려 있는 가상 주문. **덮어쓰는 값**입니다. */
  openOrders: VerifyOrder[]
  /** 마지막으로 판정한 봉의 조건 표. **서버가 판정에 쓴 값 그대로**이고 화면은
   *  다시 셈하지 않습니다. 첫 판정 전·재시작 뒤에는 `null` 이거나 없습니다.
   *  허브 방송에는 실리지 않아 실행 한 벌을 받을 때만 옵니다. */
  conditions?: RunConditions | null
}

/* ── 조건 표(마지막 판정 봉) ─────────────────────────── */

/** 조건 한 줄 — 전략에 적힌 그대로와 이 봉의 값·참거짓. 모르는 값은 `null`. */
export interface ConditionLine {
  left: string
  op: string
  right: string
  rightKind: string
  /** 왼쪽 값의 풀린 매개변수. 매개변수가 없는 값이면 `null` 이고, 칸이 없을 수도 있습니다. */
  leftParams?: Record<string, number> | null
  /** 오른쪽이 값일 때 그 값의 풀린 매개변수. */
  rightParams?: Record<string, number> | null
  leftValue: number | null
  rightValue: number | null
  /** 이 봉에서 참인지. */
  now: boolean | null
  /** 직전 봉에서 참이었는지. */
  before: boolean | null
}

/** 규칙의 한 단계. 1단계를 기다리는 동안만 단계 수준의 전이 칸이 찹니다. */
export interface ConditionStep {
  join: 'all' | 'any'
  withinBars: number
  /** 단계 전체가 이 봉에서 참인지(1단계 대기 중일 때만). */
  stepNow: boolean | null
  /** 단계 전체가 직전 봉에서 참이었는지(1단계 대기 중일 때만). */
  stepBefore: boolean | null
  /** 직전 봉의 값(호가·보유 등)을 몰라 전이로 치지 않았는지. */
  beforeUnknown: boolean
  conds: ConditionLine[]
}

/** 켜진 규칙 하나의 이 봉 판정. */
export interface ConditionRule {
  rule: 'buyEntry' | 'sellEntry' | 'buyExit' | 'sellExit'
  /** 기다리는 단계(1부터). */
  waitingStep: number
  steps: number
  /** 지금 단계의 창에서 이 봉 뒤에 남은 봉. 1단계 대기면 `null`. */
  barsLeft: number | null
  /** 규칙 전체 시한까지 남은 봉. 없으면 `null`. */
  resetLeft: number | null
  /** 이 봉에서 규칙이 참이 됐는지. **주문이 나갔다는 뜻은 아닙니다.** */
  fired: boolean
  /** 이 봉에 엔진이 이 규칙을 실제로 봤는지. 청산은 보유가 없으면 안 봅니다. */
  judged: boolean
  stepsDetail: ConditionStep[]
}

export interface RunConditions {
  /** 판정한 봉의 시작 시각(ms). */
  barTime: number | null
  /** `warmup` 은 준비 봉이 모자란 것, `gap` 은 시세가 끊긴 것입니다. */
  state: 'ready' | 'warmup' | 'gap'
  need: number
  have: number
  rules: ConditionRule[]
  /** 아직 안 끝난 봉으로 판정한 표인지. 틱 판정 실행이 체결마다 실어 보냅니다. 옛
   *  서버·마감 판정에는 칸이 없습니다. */
  partialBar?: boolean
}

/* ── 안 낸 신호 ─────────────────────────────────────── */

/** 「안 낸 신호」 글의 머리 — 지금 서버가 막힘 이벤트에 적는 꼴입니다. */
export const UNSENT_HEAD = '조건이 참이었지만 주문을 내지 않았습니다 — '

/** 옛 기록의 머리. 이 머리로 적힌 줄은 `legacyUnsentWhy` 한 자리에서만 읽습니다. */
const LEGACY_UNSENT_HEAD = '미발사 — '
/** 옛 기록에서 하루 손실 한도로 안 낸 까닭. */
const LEGACY_DAILY_LOSS = '하루 손실 한도에 닿았습니다'

/** 옛 머리로 적힌 막힘 줄의 까닭. 옛 줄이 아니면 `null` 입니다. **옛 글자 규칙은 이
 *  함수 하나**에만 있습니다 — 지금 서버의 글은 까닭 코드(`reason`)로 가립니다. */
export function legacyUnsentWhy(event: Pick<VerifyEvent, 'kind' | 'text'>): string | null {
  if (event.kind !== 'blocked' || !event.text.startsWith(LEGACY_UNSENT_HEAD)) return null
  return event.text.slice(LEGACY_UNSENT_HEAD.length)
}

/** 계좌가 주문을 받고 거부했다는 까닭 코드. 막힘 이벤트(`blocked`)의 `reason` 에 실립니다. */
const REJECTED_REASON = 'rejected'

/** 계좌가 **거부한** 주문의 이벤트인지. 막힘 이벤트와 같은 갈래로 오지만 뜻이
 *  다릅니다 — 주문은 나갔고 계좌가 받지 않은 것이라 「안 낸 신호」가 아닙니다.
 *  글은 서버가 준 코드와 문구(「주문 거부 5039 — …」)이고, 실행은 멈춥니다. */
export function isRejectedEvent(event: Pick<VerifyEvent, 'kind' | 'reason'>): boolean {
  return event.kind === 'blocked' && event.reason === REJECTED_REASON
}

/** 「안 낸 신호」 이벤트인지 — 갈래(`kind`)로 가르고, 계좌가 거부한 주문은 뺍니다. */
export function isUnsent(event: Pick<VerifyEvent, 'kind' | 'reason'>): boolean {
  return event.kind === 'blocked' && !isRejectedEvent(event)
}

/** 알림에 적는 「안 낸 신호」 글. **서버 글 그대로**이고, 옛 머리로 적힌 줄이면 그
 *  머리만 지금 문장으로 바꿉니다 — 서버가 바뀌는 사이에 같은 일이 두 말로 서지 않게. */
export function unsentText(event: Pick<VerifyEvent, 'kind' | 'text'>): string {
  const legacy = legacyUnsentWhy(event)
  return legacy === null ? event.text : `${UNSENT_HEAD}${legacy}`
}

/** 하루 손실 한도로 안 낸 것인지. 까닭 코드가 있으면 그것(`daily-loss`), 없으면(옛
 *  기록) 옛 글자 규칙입니다. */
export function isDailyLossBlock(event: VerifyEvent): boolean {
  if (!isUnsent(event)) return false
  if (event.reason !== undefined && event.reason !== null) return event.reason === 'daily-loss'
  return legacyUnsentWhy(event) === LEGACY_DAILY_LOSS
}

/** 이벤트 탭의 옛 줄에 다는 말 — 옛 줄은 원문 그대로 두고 이 말을 마우스에 답니다. */
export const LEGACY_UNSENT_TITLE = '옛 기록의 글입니다 — 지금은 「조건이 참이었지만 주문을 내지 않았습니다」로 적습니다'

/** 고른 실행 여럿에 같은 요청을 **차례로** 보냅니다. **하나가 거절돼도 나머지는
 *  보냅니다** — 확인 창이 「적용 범위 N건」을 약속했으니 중간에 멈추면 그 말이
 *  거짓이 됩니다. 빠지는 줄은 부르는 쪽이 미리 걸러 넘깁니다.
 *
 *  답은 결과 줄 한 줄입니다. 거절이 없으면 `null`, 있으면 「N건 중 K건 거절 —
 *  첫 서버 문장」입니다(N 은 실제로 보낸 수). 거절 문장을 줄마다 이어 붙이면 같은
 *  까닭이 되풀이되어 줄이 길어지기만 하고, 몇 건이 안 됐는지는 안 보입니다.
 *  검증과 진행이 이 한 자리를 씁니다. */
export async function sendEach(
  runs: readonly VerifyRun[],
  send: (run: VerifyRun) => Promise<string | null>,
): Promise<string | null> {
  let refused = 0
  let first: string | null = null
  for (const run of runs) {
    const said = await send(run)
    if (said === null) continue
    refused += 1
    if (first === null) first = said
  }
  return refused === 0 ? null : `${runs.length}건 중 ${refused}건 거절 — ${first}`
}

/* ── 확인 창 문구 ───────────────────────────────────── */

/** 되돌릴 수 없는 동작이라 무엇이 일어나는지를 줄여 적지 않습니다 — 「진입
 *  주문」과 「보유분」이 각각 어떻게 되는지. **검증과 진행이 같은 표를 씁니다** —
 *  같은 동작을 두 화면이 다른 말로 설명하면 어느 쪽이 맞는지 알 수 없습니다. */
export const CONFIRM_TEXT: Record<string, { order: string; holding: string }> = {
  '신규 진입 중지': {
    order: '새 진입 차단, 기존 진입 잔량 취소 요청·추적',
    holding: '정상 연결 시 청산 감시 유지',
  },
  '선택 전략 청산': {
    order: '중복 진입 차단, 충돌 주문 처리',
    holding: '귀속·청산가능 수량 확인 후 그 전량을 시장가로 청산',
  },
  /* 서버의 종료는 보유·미체결·취소 확인 대기가 있으면 **거절**하고, 스스로
     주문을 내거나 거두지 않습니다. 「청산 후 종료」처럼 적으면 앱이 청산해
     주는 것으로 읽힙니다. */
  '실행 종료': {
    order: '남은 주문이 있으면 끝내지 않음 — 주문을 내거나 거두지 않음',
    holding: '보유가 있으면 끝내지 않음 — 먼저 「선택 전략 청산」',
  },
  '전체 신규 진입 중지': {
    order: '확인 창에 나열한 계좌·실행 범위에 적용',
    holding: '실행별 청산 정책 유지',
  },
  /* 검증 탭의 전체 중지는 **검증(앱 시뮬레이션) 실행만** 멈춥니다. 계좌 실행은
     진행 탭에서 다룹니다. */
  '검증 신규 진입 중지': {
    order: '검증(앱 시뮬레이션) 실행만 새 진입 차단 — 계좌 실행은 그대로',
    holding: '실행별 청산 정책 유지',
  },
  실행삭제: {
    order: '끝난 실행만 지웁니다',
    holding: '목록에서만 빠지고 기록 파일은 그대로 남습니다',
  },
}

/* ── 틱 판정 표지 ──────────────────────────────────── */

/** 평가 방식 「틱」. 서버가 실행 줄과 표지에 싣는 글자 그대로입니다. */
export const TICK_EVAL = '틱'

/** 규칙이 낸 주문의 까닭 — 진입 신호, 청산 규칙, 반대 방향 진입 규칙으로 낸 청산.
 *  손절·익절·추적 청산·세션 끝 정리·사용자 청산은 규칙 판정이 아니라 표지를 달지
 *  않습니다. */
const RULE_REASONS = ['signal', 'exit', 'opposite']

/** 틱으로 평가하는 실행인지. 칸이 없으면 아닌 것으로 읽습니다. */
export function isTickRun(run: Pick<VerifyRun, 'evalMode'> | null | undefined): boolean {
  return run?.evalMode === TICK_EVAL
}

/** 그 줄이 **봉이 끝나기 전에** 규칙 판정으로 난 것이면 그 봉의 시작 시각(모르면
 *  `null`), 아니면 `undefined` 입니다. 네 표(진행·검증 × 이벤트·체결/미체결)가 이
 *  하나를 씁니다 — 신호 사건, 그리고 진입·청산 규칙의 체결과 미체결만 답니다. */
export function tickBarOf(
  row:
    | { kind: 'event'; event: VerifyEvent }
    | { kind: 'fill'; fill: VerifyFill }
    | { kind: 'order'; order: VerifyOrder },
): number | null | undefined {
  if (row.kind === 'event') {
    return row.event.kind === 'signal' && row.event.partialBar === true ? (row.event.barTime ?? null) : undefined
  }
  if (row.kind === 'fill') {
    const snap = row.fill.snapshot
    return RULE_REASONS.includes(row.fill.reason) && snap?.partialBar === true ? (snap.barTime ?? null) : undefined
  }
  return RULE_REASONS.includes(row.order.reason) && row.order.partialBar === true
    ? (row.order.barTime ?? null)
    : undefined
}
