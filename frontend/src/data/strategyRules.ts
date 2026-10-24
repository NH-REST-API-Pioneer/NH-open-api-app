import { MARKET_LINES, type MarketLineKey } from './session'
import type { MarketContext } from '../lib/types'
import {
  crossRightIds,
  defaultParams,
  hasParams,
  indicatorWord,
  resolveOperand,
  type Params,
} from './indicatorOperands'

/* 전략 규칙 — 조건 편집기가 다루는 값과 그 값을 문장으로 옮기는 규칙.
 *
 * 규칙 하나는 **단계**로 나뉘고, 단계 하나는 **조건 행**을 여럿 답니다.
 * 단계는 차례로 평가합니다 — 앞 단계가 채워진 뒤부터 다음 단계를 봅니다.
 *
 * 편집한 조건은 버전을 저장할 때 서버에 함께 남습니다(`data/strategyStore.ts` 의
 * `saveVersion`).
 */

/** 규칙 넷. 진입과 청산, 매수와 매도를 따로 켭니다 — 「ON/OFF」 하나로 묶으면
 *  보유분을 어떻게 할지까지 짐작하게 됩니다. */
export type RuleKey = 'buyEntry' | 'sellEntry' | 'buyExit' | 'sellExit'

export const RULE_LABEL: Record<RuleKey, string> = {
  buyEntry: '매수 진입',
  sellEntry: '매도 진입',
  buyExit: '매수 청산',
  sellExit: '매도 청산',
}

export const RULE_KEYS: RuleKey[] = ['buyEntry', 'sellEntry', 'buyExit', 'sellExit']

/* ── 피연산자 ────────────────────────────────────────── */

/** 조건이 견주는 값의 갈래. 왼쪽 칸의 이름표가 여기서 나옵니다 — 지표를
 *  고르면 「지표」, 가격을 고르면 「가격」입니다. */
export type Category =
  | '가격'
  | '추세'
  | '모멘텀'
  | '변동성'
  | '거래량'
  | '호가'
  | '시간'
  | '보유'

export interface Operand {
  id: string
  category: Category
  /** 셀렉트에 서는 말. */
  label: string
  /** 문장에 서는 말. 셀렉트의 「EMA(20)」이 문장에서는 「EMA20」입니다. */
  word: string
  /** 이 값이 받을 수 있는 연산자. */
  ops: string[]
  /** 매개변수가 생기기 전의 이름(`ema20` 등). **고르는 목록에는 서지 않습니다** —
   *  저장된 옛 조건은 읽을 때 `{지표, 매개변수}`로 옮겨지고(`indicatorOperands`),
   *  옮김표를 못 받은 때만 이 이름으로 그려집니다. */
  legacy?: boolean
}

/* 값 넷은 **교차도 받습니다** — 「종가가 밴드 하단을 하향 돌파」처럼 값과 지표가
   엇갈리는 조건이 실제로 쓰이고, 엔진도 그 짝을 받습니다. 목록에서 빼 두면
   저장된 조건을 화면이 못 그리거나 고치는 순간 다른 조건이 됩니다. */
const PRICE_OPS = ['crossUp', 'crossDown', 'gt', 'lt', 'gte', 'lte']
/** 호가 가격·평가손익이 받는 넷. */
const BOOK_PRICE_OPS = ['gte', 'lte', 'gt', 'lt']
/** 정수 값이 받는 다섯 — 넷에 「같음」을 더합니다. */
const WHOLE_OPS = ['gte', 'lte', 'gt', 'lt', 'eq']
/** 오실레이터(RSI·MACD 선·신호·스토캐스틱)가 받는 여섯 — 넷에 같은 지표끼리의 교차를 더합니다. */
const OSCILLATOR_OPS = ['crossUp', 'crossDown', 'gte', 'lte', 'gt', 'lt']

/** 편집기가 고를 수 있는 값들. 셀렉트에 서는 목록과 차례는 `PICK_ORDER`·
 *  `PICK_OPERANDS` 가 정합니다. */
export const OPERANDS: Operand[] = [
  { id: 'close', category: '가격', label: '종가', word: '종가', ops: PRICE_OPS },
  { id: 'open', category: '가격', label: '시가', word: '시가', ops: PRICE_OPS },
  { id: 'high', category: '가격', label: '고가', word: '고가', ops: PRICE_OPS },
  { id: 'low', category: '가격', label: '저가', word: '저가', ops: PRICE_OPS },
  /* 매개변수가 생기기 전의 이름. 고르는 목록에는 서지 않습니다(`legacy`). */
  { id: 'ema20', category: '추세', label: 'EMA(20)', word: 'EMA(20)', ops: PRICE_OPS, legacy: true },
  { id: 'ema50', category: '추세', label: 'EMA(50)', word: 'EMA(50)', ops: PRICE_OPS, legacy: true },
  { id: 'ma20', category: '추세', label: 'MA(20)', word: 'MA(20)', ops: PRICE_OPS, legacy: true },
  { id: 'rsi14', category: '모멘텀', label: 'RSI(14)', word: 'RSI(14)', ops: OSCILLATOR_OPS, legacy: true },
  { id: 'atr14', category: '변동성', label: 'ATR(14)', word: 'ATR(14)', ops: ['gte', 'lte'], legacy: true },
  /* 밴드는 폭이 아니라 **선**이라 값도 선마다입니다 — 하나로 두면 「상단을 넘었나
     하단을 깼나」를 조건이 못 가립니다. 이름은 그대로이고 매개변수(기간·배수)를
     받습니다. */
  { id: 'bbUpper', category: '추세', label: '볼린저 상단', word: '볼린저 상단', ops: PRICE_OPS },
  { id: 'bbLower', category: '추세', label: '볼린저 하단', word: '볼린저 하단', ops: PRICE_OPS },
  { id: 'volume', category: '거래량', label: '거래량', word: '거래량', ops: ['gte', 'lte'] },
  { id: 'prevHigh', category: '가격', label: '이전 1봉 고가', word: '이전 1봉의 고가', ops: [] },
  { id: 'prevLow', category: '가격', label: '이전 1봉 저가', word: '이전 1봉의 저가', ops: [] },
  /* 호가·보유·시간. **서버 규칙 모듈과 같은 id·같은 차례로 목록 끝에** 붙입니다 —
     앞 차례는 체결 줄의 당시 지표 차례이기도 해서 바꾸지 않습니다. 교차는 받지
     않습니다(호가끼리 스쳐 지나는 것은 뜻이 없습니다). 「같음」은 정수로만 서는
     값(잔량·보유 수량·시각·봉 순서)에만 둡니다 — 가격을 같음으로 견주면 소수
     끝자리 때문에 영영 안 걸립니다. */
  { id: 'bid1', category: '호가', label: '매수 1호가', word: '매수 1호가', ops: BOOK_PRICE_OPS },
  { id: 'ask1', category: '호가', label: '매도 1호가', word: '매도 1호가', ops: BOOK_PRICE_OPS },
  { id: 'bid1Qty', category: '호가', label: '매수 1호가 잔량', word: '매수 1호가 잔량', ops: WHOLE_OPS },
  { id: 'ask1Qty', category: '호가', label: '매도 1호가 잔량', word: '매도 1호가 잔량', ops: WHOLE_OPS },
  { id: 'positionQty', category: '보유', label: '보유 수량', word: '보유 수량', ops: WHOLE_OPS },
  { id: 'openPl', category: '보유', label: '평가손익', word: '평가손익', ops: BOOK_PRICE_OPS },
  /* 「봉 시각」만 두면 닫히는 시각으로 읽힙니다 — 15분봉의 09:30 봉은 09:30~09:45 입니다. */
  { id: 'clock', category: '시간', label: '봉 시작 시각', word: '봉 시작 시각', ops: WHOLE_OPS },
  { id: 'barOrder', category: '시간', label: '세션 안 봉 순서', word: '세션 안 봉 순서', ops: WHOLE_OPS },
  /* 매개변수를 받는 지표. **서버 규칙 모듈과 같은 차례로 끝에** 붙입니다. 이름(`word`)은
     매개변수 없는 이름이고, 문장·표에는 매개변수까지 적은 이름이 섭니다
     (`indicatorOperands.indicatorWord`). 추세 값은 가격과 같은 연산자(교차 포함)를,
     RSI·MACD 선·신호·스토캐스틱은 같은 지표끼리의 교차와 넷을 받습니다. MACD 막대는
     교차할 짝이 없어 넷입니다. */
  { id: 'ema', category: '추세', label: 'EMA', word: 'EMA', ops: PRICE_OPS },
  { id: 'ma', category: '추세', label: 'MA', word: 'MA', ops: PRICE_OPS },
  { id: 'rsi', category: '모멘텀', label: 'RSI', word: 'RSI', ops: OSCILLATOR_OPS },
  { id: 'atr', category: '변동성', label: 'ATR', word: 'ATR', ops: ['gte', 'lte'] },
  { id: 'bbMiddle', category: '추세', label: '볼린저 중심', word: '볼린저 중심', ops: PRICE_OPS },
  { id: 'vwap', category: '추세', label: 'VWAP(세션)', word: 'VWAP(세션)', ops: PRICE_OPS },
  /* 셀렉트에는 짧은 이름만 섭니다 — 괄호 글(DIF·DEA·DIF − DEA)까지 세우면 좁은 칸에서
     끝이 잘립니다. 괄호 글은 문장·조건 표·마우스 글에 섭니다(`word`·`fullLabelOf`). */
  { id: 'macdLine', category: '모멘텀', label: 'MACD 선', word: 'MACD 선(DIF)', ops: OSCILLATOR_OPS },
  { id: 'macdSignal', category: '모멘텀', label: 'MACD 신호', word: 'MACD 신호(DEA)', ops: OSCILLATOR_OPS },
  {
    id: 'macdHist',
    category: '모멘텀',
    label: 'MACD 막대',
    word: 'MACD 막대(DIF − DEA)',
    ops: ['gte', 'lte', 'gt', 'lt'],
  },
  { id: 'stochK', category: '모멘텀', label: '스토캐스틱 %K', word: '스토캐스틱 %K', ops: OSCILLATOR_OPS },
  { id: 'stochD', category: '모멘텀', label: '스토캐스틱 %D', word: '스토캐스틱 %D', ops: OSCILLATOR_OPS },
]

/** 고르는 목록의 차례. 묶음(추세·모멘텀·변동성) 안에서 이 차례로 섭니다 — 서버와
 *  맞춘 `OPERANDS` 의 차례는 체결 줄 당시 값의 차례라 바꿀 수 없어 따로 둡니다.
 *  옛 이름은 목록에 없습니다. */
const PICK_ORDER = [
  'close',
  'open',
  'high',
  'low',
  'prevHigh',
  'prevLow',
  'ema',
  'ma',
  'bbUpper',
  'bbMiddle',
  'bbLower',
  'vwap',
  'rsi',
  'macdLine',
  'macdSignal',
  'macdHist',
  'stochK',
  'stochD',
  'atr',
  'volume',
  'bid1',
  'ask1',
  'bid1Qty',
  'ask1Qty',
  'positionQty',
  'openPl',
  'clock',
  'barOrder',
]

/** 고르는 목록에 세우는 값들(옛 이름 빼고)을 고르는 차례로. */
export const PICK_OPERANDS: Operand[] = PICK_ORDER.flatMap((id) => {
  const found = OPERANDS.find((item) => item.id === id)
  return found ? [found] : []
})

/** 호가 가격 둘과 잔량 둘. **호가는 호가끼리만** 견줍니다 — 가격은 가격끼리,
 *  잔량은 잔량끼리입니다(서버와 같은 규칙). */
export const BOOK_PRICE_IDS = ['bid1', 'ask1']
export const BOOK_QTY_IDS = ['bid1Qty', 'ask1Qty']
/** 시간 둘. 일봉에서는 쓸 수 없습니다. */
export const TIME_IDS = ['clock', 'barOrder']
/** 보유 둘. */
export const POSITION_IDS = ['positionQty', 'openPl']
/** 봉 시각. 오른쪽이 수가 아니라 「HH:MM」 글자입니다. */
export const CLOCK_ID = 'clock'
/** 호가·시간·보유 — 기존 값과 견줄 수 없는 여덟입니다. */
export const CONTEXT_IDS = [...BOOK_PRICE_IDS, ...BOOK_QTY_IDS, ...POSITION_IDS, ...TIME_IDS]
/** 정수로만 서는 값. 「같음」은 이 값들에만 섭니다. */
export const INTEGER_IDS = [...BOOK_QTY_IDS, 'positionQty', ...TIME_IDS]

/** 「HH:MM」(00:00~23:59)을 읽습니다. 모양이 다르면 `null` 입니다 — 서버의
 *  `parse_clock` 과 같은 판정입니다(두 자리:두 자리). */
export function parseClock(text: string): { hour: number; minute: number } | null {
  const found = /^(\d{2}):(\d{2})$/.exec(text.trim())
  if (!found) return null
  const hour = Number(found[1])
  const minute = Number(found[2])
  if (hour > 23 || minute > 59) return null
  return { hour, minute }
}

export function operandOf(id: string): Operand | null {
  return OPERANDS.find((item) => item.id === id) ?? null
}

/** 가격과 같은 축에 서는 값 — 종목 자릿수로 적습니다(가격·가격에서 나온 선·호가
 *  가격). 옛 이름도 넣어 둡니다. 조건 표와 체결 당시 값이 같은 목록을 씁니다. */
export const PRICE_AXIS_IDS = [
  'close',
  'open',
  'high',
  'low',
  'prevHigh',
  'prevLow',
  'ema20',
  'ema50',
  'ma20',
  'ema',
  'ma',
  'bbUpper',
  'bbMiddle',
  'bbLower',
  'vwap',
  'bid1',
  'ask1',
]

/** 값 하나를 문장·표에 적는 이름. 매개변수를 받는 지표는 **매개변수까지**
 *  적습니다(「EMA(5)」·「스토캐스틱 %K(9, 3, 3)」) — 기본값이어도 적습니다. 옛
 *  이름(`ema20`)은 옮김표로 옮겨 같은 꼴로 섭니다. 모르는 값이면 `null` 입니다. */
export function operandWord(id: string, params?: Params | null): string | null {
  return indicatorWord(id, params) ?? operandOf(id)?.word ?? null
}

/** 셀렉트의 마우스 글 — 짧게 줄인 이름의 온 이름(「MACD 선(DIF)」). */
export function fullLabelOf(id: string): string | undefined {
  return operandOf(id)?.word
}

/* ── 연산자 ──────────────────────────────────────────── */

/** 값 칸이 무엇을 받는가. **연산자가 정하고, 넷은 둘 다 받습니다** —
 *  「종가가 이전 봉 고가를 초과」도, 「종가가 430 초과」도 조건이 됩니다.
 *  교차는 견줄 선이 있어야 뜻이 서서 수를 안 받습니다. */
export type RightKind = 'operand' | 'number'

/** 오른쪽 갈래 하나가 어떻게 읽히는가.
 *
 *  갈래마다 조사가 갈립니다 — 값을 견주면 「고가**를** 초과하고」, 수를 견주면
 *  「430 초과**이고**」입니다. 그래서 문장 틀과 꼬리를 갈래마다 둡니다. */
export interface RightForm {
  /** 문장 틀. `{L}`·`{R}` 자리에 말이 들어가고, 그 뒤의 `+조사` 는 앞말
   *  받침을 보고 골라 붙입니다. */
  phrase: string
  /** 문장이 이어질 때 붙는 꼬리. 끝말이 움직임인지 상태인지에 따라 갈립니다. */
  ending: 'verb' | 'state'
  /** 값 칸에 세울 수 있는 피연산자. 비면 전부입니다(값 갈래에만 뜻이 있습니다). */
  ids?: string[]
}

export interface Operator {
  id: string
  label: string
  /** 값(다른 지표·가격)으로 견줄 때. 없으면 값은 못 받습니다. */
  operand?: RightForm
  /** 수로 견줄 때. 없으면 수는 못 받습니다. */
  number?: RightForm
}

/** 그 연산자가 받는 갈래들. 값 칸이 이 목록으로 서고, 하나뿐이면 고르는 자리를
 *  안 세웁니다 — 고를 것이 없는 셀렉트는 자리만 먹습니다.
 *
 *  **왼쪽 값도 봅니다.** 시간·보유는 견줄 값이 없어 수만 받습니다(서버와 같은
 *  규칙). 왼쪽을 안 넘기면 연산자만 봅니다. */
export function rightKindsOf(op: Operator, left = ''): RightKind[] {
  const out: RightKind[] = []
  const numberOnly = TIME_IDS.includes(left) || POSITION_IDS.includes(left)
  if (op.operand && !numberOnly) out.push('operand')
  if (op.number) out.push('number')
  return out
}

/** 이 조건이 지금 쓰는 갈래. 적어 둔 값이 그 연산자에 없으면 첫 갈래입니다 —
 *  연산자를 바꿔 「수」가 사라진 자리에서 화면이 빈 칸을 그리지 않도록. */
export function rightKindOf(op: Operator, cond: Cond): RightKind {
  const kinds = rightKindsOf(op, cond.left)
  return kinds.includes(cond.rightKind) ? cond.rightKind : (kinds[0] ?? 'operand')
}

/** 값 갈래에서 오른쪽에 세울 수 있는 피연산자 id. **왼쪽이 정합니다** — 호가
 *  가격은 다른 쪽 호가 가격, 잔량은 다른 쪽 잔량뿐이고, 그 밖의 값은 호가·시간·
 *  보유를 받지 않습니다. 연산자가 정한 목록(교차의 선들)이 있으면 그 안에서
 *  고릅니다. */
export function rightIdsOf(op: Operator, left: string): string[] {
  const same = BOOK_PRICE_IDS.includes(left)
    ? BOOK_PRICE_IDS
    : BOOK_QTY_IDS.includes(left)
      ? BOOK_QTY_IDS
      : null
  /* 교차의 오른쪽은 **왼쪽이 정합니다** — 가격·선이면 가격 축의 선들, 오실레이터면
     같은 지표의 선끼리입니다(서버와 같은 짝). */
  const cross = op.id === 'crossUp' || op.id === 'crossDown'
  const lines = cross ? crossRightIds(left) : null
  const base = PICK_OPERANDS.map((item) => item.id).filter(
    (id) => (!op.operand?.ids || op.operand.ids.includes(id)) && (!lines || lines.includes(id)),
  )
  if (same) return base.filter((id) => same.includes(id) && id !== left)
  return base.filter((id) => !CONTEXT_IDS.includes(id))
}

export function rightFormOf(op: Operator, kind: RightKind): RightForm | null {
  return (kind === 'number' ? op.number : op.operand) ?? null
}

export const OPERATORS: Operator[] = [
  {
    id: 'crossUp',
    label: '상향 교차',
    operand: { phrase: '{L}+이 {R}+을 상향 교차', ending: 'verb' },
  },
  {
    id: 'crossDown',
    label: '하향 교차',
    operand: { phrase: '{L}+이 {R}+을 하향 교차', ending: 'verb' },
  },
  {
    id: 'gte',
    label: '이상',
    operand: { phrase: '{L}+이 {R} 이상', ending: 'state' },
    number: { phrase: '{L}+이 {R} 이상', ending: 'state' },
  },
  {
    id: 'lte',
    label: '이하',
    operand: { phrase: '{L}+이 {R} 이하', ending: 'state' },
    number: { phrase: '{L}+이 {R} 이하', ending: 'state' },
  },
  {
    id: 'gt',
    label: '초과',
    operand: { phrase: '{L}+이 {R}+을 초과', ending: 'verb' },
    number: { phrase: '{L}+이 {R} 초과', ending: 'state' },
  },
  {
    id: 'lt',
    label: '미만',
    operand: { phrase: '{L}+이 {R}+에 미달', ending: 'verb' },
    number: { phrase: '{L}+이 {R} 미만', ending: 'state' },
  },
  /* 정수 값(잔량·보유 수량·시각·봉 순서)에만 섭니다. 수로만 견줍니다. */
  {
    id: 'eq',
    label: '같음',
    number: { phrase: '{L}+이 {R}', ending: 'state' },
  },
]

/** 「바뀌는 순간」에만 걸리는 연산자 — 이상·이하·초과·미만·같음. 1단계에서는
 *  직전 봉에 거짓이고 이 봉에 참일 때만 냅니다(교차는 그 자체가 바뀌는 순간입니다). */
export const LEVEL_OPS = ['gte', 'lte', 'gt', 'lt', 'eq']

/** 직전 봉의 값이 없을 수 있는 값 — 호가·보유·시각. 직전 값이 없으면 바뀐 것으로
 *  치지 않습니다(서버 규칙과 같습니다). */
export const NO_PREVIOUS_IDS = ['bid1', 'ask1', 'bid1Qty', 'ask1Qty', 'positionQty', 'openPl', 'clock', 'barOrder']

/** 「바뀌는 순간」 표기에 마우스를 올리면 서는 말. */
export const MOMENT_TITLE =
  '직전 봉에 거짓이고 이 봉에 참일 때만 냅니다. 시작할 때 이미 참이면 다시 거짓이 됐다가 참이 될 때까지 기다립니다'

/** 이어 붙이는 꼬리. 문장을 잇는 자리마다 끝말에 맞는 것을 씁니다. */
export const TAIL: Record<RightForm['ending'], { all: string; any: string; then: string }> = {
  verb: { all: '하고', any: '하거나', then: '하면' },
  state: { all: '이고', any: '이거나', then: '이면' },
}

export function operatorOf(id: string): Operator | null {
  return OPERATORS.find((item) => item.id === id) ?? null
}

/* ── 규칙 ────────────────────────────────────────────── */

export interface Cond {
  id: string
  left: string
  op: string
  /** 오른쪽을 **값으로 견주는지 수로 견주는지**. 연산자 넷은 둘 다 받으므로
   *  적어 둔 값(`right`)이 피연산자 id 인지 수인지를 이 칸이 가릅니다 —
   *  글자만 보고 가르면 「55」라는 이름의 지표가 생기는 날 깨집니다. */
  rightKind: RightKind
  /** 오른쪽이 값이면 피연산자 id, 수이면 적은 그대로의 글자입니다.
   *  숫자로 바꾸지 않는 것은 「55.」처럼 치는 중인 상태를 지우지 않기 위해서입니다. */
  right: string
  /** 왼쪽 값의 매개변수(기간·배수…). 매개변수를 받는 지표에만 있습니다. */
  leftParams?: Params
  /** 오른쪽이 값일 때 그 값의 매개변수. */
  rightParams?: Params
}

export interface Step {
  id: string
  /** 이 단계 안의 조건을 잇는 방법. **단계마다 하나**입니다 — 행마다 AND/OR
   *  토글을 또 두면 같은 뜻을 두 곳에서 정하게 됩니다. */
  join: 'all' | 'any'
  /** 다음 단계가 몇 봉 안에 채워져야 하는가. **마지막 단계에는 뜻이 없어**
   *  화면에도 그리지 않습니다. */
  withinBars: number
  conds: Cond[]
}

export interface Rule {
  on: boolean
  steps: Step[]
  /** 1단계가 채워진 뒤 이 봉 수 안에 규칙이 끝나지 않으면 처음으로 되돌립니다.
   *  **비어 있으면 쓰지 않습니다.** 적은 그대로의 글자이고 1 이상의 정수여야
   *  합니다 — 서버가 같은 규칙으로 봅니다. */
  resetBars: string
}

export type RuleSet = Record<RuleKey, Rule>

/** 규칙 하나가 가질 수 있는 조건 수. **모든 단계를 더해서** 셉니다.
 *  API 한도가 아니라 편집기 규격입니다 — 규칙이 길어지면 사람이 읽지 못합니다. */
export const MAX_CONDS = 5

export function condCount(rule: Rule): number {
  return rule.steps.reduce((sum, step) => sum + step.conds.length, 0)
}

/* ── 조사 ────────────────────────────────────────────── */

/* 앞말 받침에 따라 갈리는 조사. 「EMA20이」와 「종가가」가 갈립니다.
 *
 * 끝 글자가 숫자·영문이면 읽는 소리로 판단합니다 — 「EMA20」은 「이십」이
 * 아니라 화면에 적힌 대로 「이엠에이이십」으로 읽히지만, 조사를 정하는 것은
 * 마지막 소리 하나(「십」)라 받침이 있습니다. */
const DIGIT_HAS_FINAL: Record<string, boolean> = {
  '0': true, // 영
  '1': true, // 일
  '2': false, // 이
  '3': true, // 삼
  '4': false, // 사
  '5': false, // 오
  '6': true, // 육
  '7': true, // 칠
  '8': true, // 팔
  '9': false, // 구
}

/* 영문 한 글자의 이름 끝소리. 「RSI」는 「아이」로 끝나 받침이 없습니다. */
const LETTER_HAS_FINAL: Record<string, boolean> = {
  a: false, b: false, c: false, d: false, e: false, f: true, g: false, h: false,
  i: false, j: false, k: false, l: true, m: true, n: true, o: false, p: false,
  q: false, r: true, s: true, t: false, u: false, v: false, w: false, x: true,
  y: false, z: false,
}

/** 소리가 나는 마지막 글자. 끝의 닫는 괄호와 빈칸은 건너뜁니다. */
function soundEnd(word: string): string {
  return word.trim().replace(/[)\s]+$/, '').slice(-1)
}

/** 앞말에 받침이 있는가. 조사를 고르는 데만 씁니다. */
export function hasFinal(word: string): boolean {
  /* 끝의 닫는 괄호는 소리가 없습니다 — 「EMA(20)」은 「이십」으로 끝납니다. */
  const last = soundEnd(word)
  if (!last) return false
  if (last >= '0' && last <= '9') return DIGIT_HAS_FINAL[last]
  const lower = last.toLowerCase()
  if (lower >= 'a' && lower <= 'z') return LETTER_HAS_FINAL[lower]
  const code = last.charCodeAt(0)
  /* 한글 음절은 초성·중성·종성이 한 글자에 담깁니다. 종성 자리가 0이면
     받침이 없습니다. */
  if (code >= 0xac00 && code <= 0xd7a3) return (code - 0xac00) % 28 !== 0
  return false
}

/* ㄹ 로 끝나는 소리들. 「으로/로」만 이 갈래를 따로 봅니다 — 다른 조사는
   받침이 있으면 한쪽, 없으면 다른 쪽인데 이 조사만 ㄹ 이 받침 없는 쪽을 씁니다. */
const DIGIT_RIEUL = new Set(['1', '7', '8'])
const LETTER_RIEUL = new Set(['l', 'r'])
/** 한글 종성 자리에서 ㄹ 의 번호. */
const JONG_RIEUL = 8

/** 「으로」와 「로」를 가릅니다. **받침이 없거나 ㄹ 받침이면 「로」**입니다 —
 *  「지정가로」·「STOP-L로」·「시장가로」가 그렇고, 「STOP-M으로」는 아닙니다.
 *  붙여 쓰면 한쪽이 늘 어색합니다. */
export function ro(word: string): string {
  const last = soundEnd(word)
  if (!last || !hasFinal(word)) return '로'
  if (DIGIT_RIEUL.has(last)) return '로'
  if (LETTER_RIEUL.has(last.toLowerCase())) return '로'
  const code = last.charCodeAt(0)
  if (code >= 0xac00 && code <= 0xd7a3 && (code - 0xac00) % 28 === JONG_RIEUL) return '로'
  return '으로'
}

/** 앞말에 맞는 조사. `pair` 는 「이/가」처럼 받침 있는 쪽을 앞에 적습니다. */
export function particle(word: string, pair: string): string {
  const [withFinal, withoutFinal] = pair.split('/')
  return hasFinal(word) ? withFinal : withoutFinal
}

const PARTICLES: Record<string, string> = {
  이: '이/가',
  을: '을/를',
  에: '에/에',
  와: '과/와',
}

/** 문장 틀을 채웁니다. `{L}+이` 는 왼쪽 말 뒤에 받침에 맞는 조사를 붙입니다. */
export function fill(phrase: string, left: string, right: string): string {
  return phrase.replace(/\{([LR])\}(?:\+(.))?/g, (_, slot: string, mark?: string) => {
    const word = slot === 'L' ? left : right
    if (!mark) return word
    const pair = PARTICLES[mark]
    return pair ? word + particle(word, pair) : word + mark
  })
}

/** 조건 한 줄의 값들을 `{지표, 매개변수}` 꼴로. 매개변수가 생기기 전의 이름
 *  (`ema20`)은 서버가 준 옮김표로 옮기고(`resolveOperand`), 매개변수를 받는 지표는
 *  매개변수를 다 적어 둡니다 — 칸이 기본값을 보이는데 조건에는 비어 있으면, 칸을
 *  한 번 건드린 것만으로 조건이 바뀐 것으로 읽힙니다.
 *
 *  **읽을 때만** 옮깁니다. 저장된 파일은 사용자가 고쳐 저장할 때까지 그대로이고,
 *  저장 기준과 고치는 초안이 같은 값에서 출발해 열고 닫아도 「바뀜」이 서지
 *  않습니다. */
function withOperandParams(cond: Cond): Cond {
  const made: Cond = { ...cond }
  const left = resolveOperand(cond.left, cond.leftParams)
  if (hasParams(left.id)) {
    made.left = left.id
    made.leftParams = left.params
  } else if (left.id !== cond.left) made.left = left.id
  if (cond.rightKind === 'operand' && cond.right) {
    const right = resolveOperand(cond.right, cond.rightParams)
    if (hasParams(right.id)) {
      made.right = right.id
      made.rightParams = right.params
    } else if (right.id !== cond.right) made.right = right.id
  }
  return made
}

/* ── 새 조건·단계 ────────────────────────────────────── */

/** 새 조건 한 줄. 값이 비어 있어 오류로 셉니다 — 고르라는 뜻입니다. */
export function blankCond(seed: number): Cond {
  return { id: `c${seed}`, left: '', op: '', rightKind: 'operand', right: '' }
}

export function blankStep(seed: number): Step {
  return { id: `s${seed}`, join: 'all', withinBars: 3, conds: [blankCond(seed)] }
}

function emptyRule(): Rule {
  return { on: false, steps: [], resetBars: '' }
}

/* ── 보조 설정 ───────────────────────────────────────── */

/** 조건 밖의 설정. 규칙이 신호를 내면 그 다음을 정하는 값들입니다. */
export interface Aux {
  orderType: string
  priceBasis: string
  /** 방향마다의 주문 가격 기준. **비어 있으면 위 공용 기준을 씁니다.** */
  buyPriceBasis: string
  sellPriceBasis: string
  /** 스탑 주문의 스탑 가격 기준. **STOP 주문에만 뜻이 있습니다** — 다른
   *  주문유형에서는 화면이 이 칸을 세우지 않습니다. */
  stopBasis: string
  fillCond: string
  /** 손절·익절·추적 청산의 거리. **칸 이름은 옛 것이고 뜻은 단위 칸이 정합니다** —
   *  `stopUnit` 이 `pct` 면 `stopTicks` 의 값은 % 입니다. */
  stopTicks: string
  takeTicks: string
  /** 추적 청산 — 보유 뒤 가장 유리했던 체결가에서 이만큼 되돌면 닫습니다.
   *  **비어 있으면 쓰지 않습니다.** */
  trailTicks: string
  /** 거리 단위(`ExitUnit`). **비어 있으면 틱**입니다 — 단위가 생기기 전의 설정이 그렇게
   *  읽힙니다. */
  stopUnit: string
  takeUnit: string
  trailUnit: string
  /** 세션 끝 정리 — 세션 끝 `sessionEndMinutes` 분 전에 보유를 모두 닫고 새 진입을 막습니다. */
  sessionEndFlat: boolean
  sessionEndMinutes: string
  /** 신규 진입 시간(한국시간 「HH:MM」). **비어 있으면 세션 시작·끝**입니다. 끝이 시작보다
   *  이르면 다음 날입니다. 청산은 이 시간 밖에서도 합니다. */
  entryStart: string
  entryEnd: string
  /** 청산 뒤 다시 들어가기까지 기다리는 판정 봉 수. 비어 있으면 0(기다리지 않음). */
  reentryWaitBars: string
  /** 그 거래일에 낼 수 있는 진입 주문 수. **비어 있으면 제한 없음**입니다. */
  maxEntriesPerDay: string
  perOrder: string
  maxHold: string
  session: string
  addWhileOpen: boolean
  /** 보유 중에 반대 방향 진입 규칙이 참이 되면 어떻게 하는지(`OppositeSignal`). 칸이 없거나
   *  모르는 값이면 서버가 「무시」로 읽습니다. */
  oppositeSignal: OppositeSignal
  dailyLoss: string
  marginBudget: string
  /** 연속 손실 한도 — 그 거래일에 손실 거래가 이만큼 이어지면 새 진입을 막습니다.
   *  **비어 있으면 쓰지 않습니다.** */
  lossStreak: string
}

/** 보유 중 반대 방향 진입 신호를 다루는 방법. 서버가 받는 값과 같은 id 입니다.
 *  - 무시: 반대 방향 진입 규칙이 참이어도 주문을 내지 않습니다
 *  - 청산: 보유를 청산 규칙의 주문 유형으로 닫고 새로 들어가지 않습니다
 *  - 반전: 보유를 닫고, 전량 체결되면 반대 방향으로 들어갑니다 */
export type OppositeSignal = 'ignore' | 'exit' | 'reverse'

export const OPPOSITE_SIGNALS: { id: OppositeSignal; label: string; note: string }[] = [
  { id: 'ignore', label: '무시', note: '반대 방향 진입 규칙이 참이어도 주문을 내지 않습니다' },
  {
    id: 'exit',
    label: '청산',
    note: '반대 방향 진입 규칙이 참이면 보유를 청산 규칙의 주문 유형으로 닫습니다. 새로 들어가지 않습니다',
  },
  { id: 'reverse', label: '반전', note: '보유를 닫고 전량 체결되면 반대 방향으로 들어갑니다' },
]

/** 저장된 값을 고를 수 있는 값으로. 모르는 값이나 빈 값은 서버와 같이 「무시」입니다. */
export function oppositeSignalOf(value: unknown): OppositeSignal {
  return OPPOSITE_SIGNALS.find((one) => one.id === value)?.id ?? 'ignore'
}

/** 그 값의 이름(무시·청산·반전). */
export function oppositeSignalLabel(value: unknown): string {
  const id = oppositeSignalOf(value)
  return OPPOSITE_SIGNALS.find((one) => one.id === id)?.label ?? ''
}

/** 그 값의 뜻 한 문장. 설정 줄 아래에 섭니다. */
export function oppositeSignalNote(value: unknown): string {
  const id = oppositeSignalOf(value)
  return OPPOSITE_SIGNALS.find((one) => one.id === id)?.note ?? ''
}

/** 주문유형은 시장이 정합니다. **주문 화면과 같은 목록**입니다 — 전략이 내는
 *  주문도 결국 그 화면이 내는 주문과 같은 자리로 갑니다. */
export const ORDER_TYPES: Record<'domestic' | 'overseas', string[]> = {
  domestic: ['지정가', '시장가', '조건부지정가', '최유리지정가'],
  overseas: ['시장가', '지정가', 'STOP-M', 'STOP-L'],
}

/** 전략 주문에 쓰지 않는 주문유형. 국내 조건부지정가·최유리지정가는 거래소가
 *  장 상황을 보고 값을 정하는 유형이라, 전략 실행이 시작할 때 받지 않습니다.
 *  주문 화면에서는 그대로 고를 수 있습니다. */
export const STRATEGY_EXCLUDED_ORDER_TYPES = ['조건부지정가', '최유리지정가']

/** 전략 설정에서 고를 수 있는 주문유형 — 주문 화면의 목록에서 전략 주문에 쓰지
 *  않는 유형을 뺀 것입니다. */
export function orderTypesFor(market: 'domestic' | 'overseas'): string[] {
  return ORDER_TYPES[market].filter((type) => !STRATEGY_EXCLUDED_ORDER_TYPES.includes(type))
}

/** 저장된 주문유형이 전략 주문에 쓰지 않는 유형인가. 예전에 저장한 설정에 남아
 *  있을 수 있어, 값을 바꾸지 않고 설정 화면이 알리고 저장을 막습니다. */
export function excludedOrderType(orderType: string): boolean {
  return STRATEGY_EXCLUDED_ORDER_TYPES.includes(orderType.trim())
}

/** 전략 주문에 쓰지 않는 유형일 때 칸 아래에 서는 말. */
export function excludedOrderTypeWhy(orderType: string): string {
  return `${orderType.trim()}는 전략 주문에 쓰지 않습니다 — 다른 유형을 고르세요`
}

export const PRICE_BASES = ['신호가', '신호가 + 1틱', '신호가 − 1틱']

/** 손절·익절·추적 청산의 거리 단위. 서버가 받는 값과 같은 id 입니다.
 *  - 틱: 틱 수
 *  - 포인트: 평균가(추적은 가장 유리했던 가격)에서의 가격 거리
 *  - %: 평균가(추적은 가장 유리했던 가격) 대비 백분율
 *  - ATR 배: 마지막 닫힌 판정 봉의 ATR(14) × 배수 */
export type ExitUnit = 'tick' | 'price' | 'pct' | 'atr'

export const EXIT_UNITS: { id: ExitUnit; label: string }[] = [
  { id: 'tick', label: '틱' },
  { id: 'price', label: '포인트' },
  { id: 'pct', label: '%' },
  { id: 'atr', label: 'ATR 배' },
]

/** 적힌 단위 — 비었으면 틱입니다. 모르는 글자는 그대로 돌려 판정이 막게 합니다. */
export function exitUnitOf(value: string | undefined): string {
  const text = (value ?? '').trim()
  return text === '' ? 'tick' : text
}

/** 값 칸이 쓰이지 않는 주문유형. **주문 화면과 같은 규칙**입니다 — 시장가와
 *  STOP-M 은 값을 안 받고 시장가로 나갑니다. */
export function needsPriceFor(orderType: string): boolean {
  return orderType !== '시장가' && orderType !== 'STOP-M'
}

/** 스탑 가격을 함께 받는 주문유형(해외 STOP 둘). */
export function needsStopFor(orderType: string): boolean {
  return orderType.startsWith('STOP')
}
/** 국내 체결조건. 해외 주문에는 붙이지 않습니다. */
export const FILL_CONDS = ['FAS', 'FOK', 'FAK']

/** 그 주문유형이 받는 국내 체결조건. **서버의 규칙**입니다 — 국내 서버는 시장가
 *  주문의 FOK·FAK 를 거부하므로 시장가에는 FAS 만 둡니다. 주문 화면과 전략 설정이
 *  같은 목록을 씁니다(백엔드 `validate.py` 의 `MARKET_FILL_CONDS` 와 같은 규칙). */
export function fillCondsFor(orderType: string): string[] {
  return orderType === '시장가' ? ['FAS'] : FILL_CONDS
}

/** 체결조건이 그 주문유형에 맞지 않을 때 하는 말. 백엔드 저장 검사와 같은 문장입니다. */
export const MARKET_FILL_COND_WHY = '시장가는 체결조건을 FAS 로 두어야 합니다'

/** 주문유형을 바꿨을 때 이어 쓸 체결조건 — 새 유형이 받으면 그대로, 아니면 그 유형의
 *  첫 값. 비어 있으면 비운 채 둡니다(고르지 않은 값을 고른 것처럼 채우지 않습니다). */
export function fillCondFor(orderType: string, current: string): string {
  const allowed = fillCondsFor(orderType)
  return current === '' || allowed.includes(current) ? current : allowed[0]
}

/** 아는 체결조건인데 그 주문유형이 받지 않는지 — 이 규칙 전에 담아 둔 설정이 그렇습니다. */
export function fillCondMismatch(aux: { orderType: string; fillCond: string }): boolean {
  return FILL_CONDS.includes(aux.fillCond) && !fillCondsFor(aux.orderType).includes(aux.fillCond)
}

/** 전략이 도는 세션. **앱이 이미 쓰는 시장 시간 이름을 그대로** 씁니다 —
 *  같은 시간대를 화면마다 다른 말로 부르면 둘이 같은 것인지 읽는 사람이
 *  맞춰 봐야 합니다. 국내 전략에 해외 세션을 세우지 않습니다. */
export function sessionsFor(market: 'domestic' | 'overseas'): string[] {
  const want = market === 'overseas' ? '해외' : '국내'
  return MARKET_LINES.filter((item) => item.label.startsWith(want)).map((item) => item.label)
}

/** 장 시간 줄의 키를 **실시간 맥락 키**로. 홈의 장 시간 줄은 거래소까지 갈라
 *  `overseas-cme` 로 적는데, 전략이 붙는 창은 거래소가 아니라 **세션**이라
 *  해외는 하나입니다. 두 이름이 만나는 자리를 여기 하나로 둡니다 — 화면마다
 *  옮겨 적으면 한쪽만 고쳐지는 날 실행이 붙을 창을 잃습니다. */
function contextOf(key: MarketLineKey): MarketContext {
  return key === 'overseas-cme' ? 'overseas' : key
}

/** 그 시장이 도는 세션 — **키와 글자를 함께** 돌려줍니다. 서버에 보내고 시세를
 *  구독하는 것은 키(`domestic-day`)이고 화면에 세우는 것은 글자(「국내 주간」)
 *  입니다. 둘을 따로 두면 화면이 글자에서 키를 되찾아야 하고, 그 자리가 곧
 *  어긋나는 자리입니다. */
export function sessionLinesFor(
  market: 'domestic' | 'overseas',
): readonly { key: MarketContext; label: string }[] {
  const want = market === 'overseas' ? '해외' : '국내'
  return MARKET_LINES.filter((item) => item.label.startsWith(want)).map((item) => ({
    key: contextOf(item.key),
    label: item.label,
  }))
}

/** 전략에 담긴 세션 글자(「국내 야간」)가 가리키는 맥락 키. 그 시장 목록에 없거나
 *  비었으면 **시장의 첫째**입니다 — 담긴 세션이 없는 버전도 붙을 창은 있어야
 *  합니다. 검증 추가 창과 설정 화면이 이 하나를 부릅니다. */
export function sessionKeyOf(
  market: 'domestic' | 'overseas',
  saved: string | null | undefined,
): MarketContext | '' {
  const lines = sessionLinesFor(market)
  return lines.find((line) => line.label === saved)?.key ?? lines[0]?.key ?? ''
}

/** 키가 가리키는 글자. 맥락 키와 장 시간 줄의 키를 **둘 다** 받습니다 — 담아 둔
 *  설정에는 옛 꼴이 남아 있을 수 있습니다. 모르는 키면 키를 그대로 돌려줍니다. */
export function sessionLabelOf(key: string): string {
  const found = MARKET_LINES.find((item) => item.key === key || contextOf(item.key) === key)
  return found?.label ?? key
}

/** 편집 중인 설정 한 벌. 버전 하나가 이것을 하나 가집니다. */
export interface SettingsDraft {
  memo: string
  baseBar: string
  evalMode: string
  rules: RuleSet
  aux: Aux
}

export const BASE_BARS = ['1분봉', '5분봉', '15분봉', '30분봉', '60분봉', '일봉']
export const EVAL_MODES = ['마감', '틱']

/** 버전 하나가 처음 여는 조건의 갈래.
 *
 *  **설정이 아직 저장되지 않은 버전은 이 갈래로 조건을 엽니다.** 저장된 설정이
 *  있으면 그 조건이 섭니다. 목록의 요약 한 줄과 설정 화면이 서로 다른 전략을
 *  말하지 않도록 여기서 맞춥니다. */
export type SeedKind = 'empty' | 'trend' | 'revert' | 'gap'

/** 화면이 처음 세우는 규칙. **갈래마다 다릅니다** — 새로 만든 전략은 빈 채로
 *  열려야 「조건을 아직 안 넣었습니다」라는 목록의 말과 맞습니다.
 *
 *  채워진 갈래는 매수 진입만 씁니다. 조건 다섯 한도 안에서 두 자리를 남겨,
 *  더할 수 있다는 것과 나머지 규칙이 비었을 때의 모습이 함께 보입니다. */
export function seedRules(kind: SeedKind = 'trend'): RuleSet {
  const base: RuleSet = {
    buyEntry: emptyRule(),
    sellEntry: emptyRule(),
    buyExit: { on: true, steps: [], resetBars: '' },
    sellExit: { on: true, steps: [], resetBars: '' },
  }
  /* 새 전략은 **매수 진입·매수 청산을 켜 둔 채** 엽니다 — 무엇을 채워야 하는지가
     처음부터 보입니다(조건이 비어 시작은 못 한다는 판정도 함께 섭니다). 매도 쪽은
     쓰는 사람이 켭니다. */
  if (kind === 'empty') {
    return {
      ...base,
      buyEntry: { on: true, steps: [], resetBars: '' },
      sellExit: { on: false, steps: [], resetBars: '' },
    }
  }

  if (kind === 'revert') {
    /* 평균회귀 — 밴드 하단을 깨고 내려간 뒤 되돌아오는 자리에서 삽니다. */
    return {
      ...base,
      buyEntry: {
        on: true,
        resetBars: '',
        steps: [
          {
            id: 's1',
            join: 'all',
            withinBars: 3,
            conds: [
              {
                id: 'c1',
                left: 'close',
                op: 'crossDown',
                rightKind: 'operand',
                right: 'bbLower',
                rightParams: defaultParams('bbLower'),
              },
            ],
          },
          {
            id: 's2',
            join: 'all',
            withinBars: 3,
            conds: [
              {
                id: 'c2',
                left: 'close',
                op: 'crossUp',
                rightKind: 'operand',
                right: 'bbLower',
                rightParams: defaultParams('bbLower'),
              },
            ],
          },
        ],
      },
    }
  }

  if (kind === 'gap') {
    /* 갭 되돌림 — 전날 아래로 벌어져 열린 뒤 그날 안에서 되돌아오는 자리입니다. */
    return {
      ...base,
      buyEntry: {
        on: true,
        resetBars: '',
        steps: [
          {
            id: 's1',
            join: 'all',
            withinBars: 3,
            conds: [{ id: 'c1', left: 'open', op: 'lt', rightKind: 'operand', right: 'prevLow' }],
          },
          {
            id: 's2',
            join: 'all',
            withinBars: 3,
            conds: [{ id: 'c2', left: 'close', op: 'gt', rightKind: 'operand', right: 'open' }],
          },
        ],
      },
    }
  }

  return {
    ...base,
    buyEntry: {
      on: true,
      resetBars: '',
      steps: [
        {
          id: 's1',
          join: 'all',
          withinBars: 3,
          conds: [
            {
              id: 'c1',
              left: 'ema',
              leftParams: { period: 20 },
              op: 'crossUp',
              rightKind: 'operand',
              right: 'ema',
              rightParams: { period: 50 },
            },
            { id: 'c2', left: 'rsi', leftParams: { period: 14 }, op: 'gte', rightKind: 'number', right: '55' },
          ],
        },
        {
          id: 's2',
          join: 'all',
          withinBars: 3,
          conds: [{ id: 'c3', left: 'close', op: 'gt', rightKind: 'operand', right: 'prevHigh' }],
        },
      ],
    },
  }
}

/** 설정 초안을 세울 때 그 버전에서 읽는 것. 목록 행이 이 모양을 채웁니다 —
 *  화면이 목록의 수와 다른 수로 열리지 않도록 예산·수량·통화가 여기서 옵니다. */
export interface DraftSeed {
  kind: SeedKind
  market: 'domestic' | 'overseas'
  /** 증거금 예산. 새 전략은 0 입니다. */
  marginBudget: number
  /** 하루 손실 한도. **행이 적어 둔 값을 그대로 씁니다** — 예산에서 비율로
   *  내면 규격에 없는 규칙이 하나 생기고, 실제 값이 들어올 때 그 규칙이
   *  먼저 걸립니다. */
  dailyLoss: number
  /** 주문당 계약 수. */
  orderQty: number
}

/** 버전 하나가 처음 여는 설정.
 *
 *  **버전마다 갈립니다.** 하나로 두면 새로 만든 전략이 남의 조건과 남의 예산을
 *  단 채로 열립니다. 값은 그 버전의 목록 행에서 오고, 조건은 갈래가 정합니다. */
export function seedDraft(
  seed: DraftSeed = { kind: 'trend', market: 'domestic', marginBudget: 35000000, dailyLoss: 500000, orderQty: 1 },
): SettingsDraft {
  const overseas = seed.market === 'overseas'
  return {
    memo: '',
    baseBar: '15분봉',
    evalMode: '마감',
    rules: seedRules(seed.kind),
    aux: {
      orderType: orderTypesFor(seed.market)[0],
      priceBasis: '신호가 + 1틱',
      /* 방향마다의 기준·추적 청산·연속 손실은 **비어 있는 채로** 엽니다 —
         공용 기준 하나로 내고, 둘은 쓰지 않는 것이 지금까지의 동작입니다. */
      buyPriceBasis: '',
      sellPriceBasis: '',
      stopBasis: '신호가',
      /* 체결조건은 국내 주문에만 있습니다. 해외는 빈 값이고 화면도 그 칸을
         세우지 않습니다 — 없는 선택지를 비활성으로 세워 두면 언젠가 켜지는
         것처럼 읽힙니다. */
      fillCond: overseas ? '' : FILL_CONDS[0],
      stopTicks: '10',
      takeTicks: '20',
      trailTicks: '',
      perOrder: String(seed.orderQty),
      maxHold: '1',
      session: sessionsFor(seed.market)[0],
      addWhileOpen: false,
      /* 새 전략은 반대 신호에 보유를 닫습니다. 저장된 옛 전략은 칸이 없어 「무시」로
         읽습니다(`withNewFields`) — 그 전략이 하던 동작 그대로입니다. */
      oppositeSignal: 'exit',
      dailyLoss: String(seed.dailyLoss),
      marginBudget: String(seed.marginBudget),
      lossStreak: '',
      /* 거리 단위는 틱으로 엽니다(지금까지의 동작). 세션 끝 정리는 **새 전략에만** 켜 둡니다
         — 저장된 옛 전략을 읽을 때는 끈 채로 둡니다(`withNewFields`). */
      stopUnit: 'tick',
      takeUnit: 'tick',
      trailUnit: 'tick',
      sessionEndFlat: true,
      sessionEndMinutes: '10',
      entryStart: '',
      entryEnd: '',
      reentryWaitBars: '0',
      maxEntriesPerDay: '',
    },
  }
}

/** 저장해 둔 설정을 화면이 쓰는 꼴로. **뒤에 생긴 칸이 없는 설정**(방향별 기준·
 *  추적 청산·연속 손실·규칙의 되돌리기)은 그 칸을 빈 글자로 채웁니다 — 빈 칸은
 *  「쓰지 않음」이라, 채워도 그 설정이 하는 일은 그대로입니다.
 *
 *  **읽을 때 한 번** 채웁니다. 칸마다 따로 채우면 저장한 값과 고치는 값이 다른
 *  꼴이 되어, 아무것도 안 고친 버전이 고친 것으로 읽힙니다. */
export function withNewFields(draft: SettingsDraft): SettingsDraft {
  const aux = draft.aux ?? ({} as Aux)
  const rules = { ...draft.rules } as RuleSet
  for (const key of Object.keys(rules) as RuleKey[]) {
    const rule = rules[key]
    if (rule) {
      rules[key] = {
        ...rule,
        resetBars: rule.resetBars ?? '',
        steps: (rule.steps ?? []).map((step) => ({ ...step, conds: (step.conds ?? []).map(withOperandParams) })),
      }
    }
  }
  return {
    ...draft,
    rules,
    aux: {
      ...aux,
      buyPriceBasis: aux.buyPriceBasis ?? '',
      sellPriceBasis: aux.sellPriceBasis ?? '',
      trailTicks: aux.trailTicks ?? '',
      lossStreak: aux.lossStreak ?? '',
      /* 뒤에 생긴 칸이 없는 옛 설정은 **지금까지의 동작**으로 읽습니다 — 단위 빈칸은 틱,
         세션 끝 정리 끔, 시간창·대기·하루 최대 없음. 새 전략의 기본값을 여기서 끼우면
         저장된 전략의 동작이 바뀝니다. */
      stopUnit: aux.stopUnit ?? '',
      takeUnit: aux.takeUnit ?? '',
      trailUnit: aux.trailUnit ?? '',
      sessionEndFlat: aux.sessionEndFlat ?? false,
      sessionEndMinutes: aux.sessionEndMinutes ?? '',
      entryStart: aux.entryStart ?? '',
      entryEnd: aux.entryEnd ?? '',
      reentryWaitBars: aux.reentryWaitBars ?? '',
      maxEntriesPerDay: aux.maxEntriesPerDay ?? '',
      /* 칸이 없거나 모르는 값이면 「무시」 — 서버가 읽는 뜻과 같습니다. */
      oppositeSignal: oppositeSignalOf(aux.oppositeSignal),
    },
  }
}
