/** 주문을 보내는 자리 — 신규·정정·취소.
 *
 *  **되돌릴 수 없는 한 걸음입니다.** 이 파일이 지키는 것 셋:
 *
 *  1. **보낸 것은 한 번만 보냅니다.** 답을 못 받은 주문에 「다시 보내기」를 세우지
 *     않습니다 — 서버가 받았는지 모르는 상태에서 다시 내면 두 배로 체결됩니다.
 *     그 판단은 답을 받는 쪽(`kind`)이 이미 갈라 두었고, 화면은 그대로 따릅니다.
 *  2. **화면이 믿는 환경을 함께 보냅니다.** 서버의 활성 환경과 다르면 서버가
 *     아무것도 내보내지 않고 돌려보냅니다 — 「모의」 배지를 띄운 채 낸 주문이
 *     실전으로 나가는 길을 그렇게 막습니다.
 *  3. **답을 지어내지 않습니다.** 거절 사유도, 주문번호가 안 온 사정도 서버가
 *     보낸 문장을 그대로 나릅니다.
 *
 *  담아 두는 값이 없습니다 — 보내고 답 한 벌을 돌려주기만 합니다. 접수된 줄을
 *  목록에 얹는 일은 부르는 쪽이 합니다(`data/account.ts` 의 `applyOrderEvents`).
 */
import { environmentState, type Environment } from './environment'
import type { OrderEvent } from './account'
import { OVERSEAS_TYPE_CODE, overseasFormType, priceText } from './orderable'
import type { MarketContext } from '../lib/types'

/** 무엇을 하는 주문인가. 라우트와 확인창 낱말이 이 값으로 갈립니다. */
export type OrderKind = 'new' | 'modify' | 'cancel'

/** 주문유형 이름 → 명세의 주문유형코드. **폼의 낱말이 열쇠입니다** — 코드를
 *  화면 곳곳에 흩어 두면 이름과 코드가 따로 바뀝니다. */
const ORDER_TYPE_CODE: Record<string, string> = {
  지정가: '1',
  시장가: '2',
  조건부지정가: '3',
  최유리지정가: '4',
}

/** 체결조건 이름 → 명세의 체결조건코드. */
const FILL_CONDITION_CODE: Record<string, string> = { FAS: '1', FOK: '2', FAK: '3' }

/** 가격을 안 싣는 주문유형. 서버가 `0` 을 채워 보냅니다. */
const ZERO_PRICE_TYPES = new Set(['2', '4'])

/** 보낼 주문 하나. **폼에 보이는 그대로**입니다 — 값을 여기서 다시 계산하지
 *  않습니다. */
export interface OrderAsk {
  kind: OrderKind
  /** 주간·야간. 국내는 세션마다 부르는 API 가 달라 서버가 이 값으로 고릅니다. */
  context: MarketContext
  code: string
  side: 'buy' | 'sell'
  quantity: number
  /** 폼의 주문유형 낱말. 취소는 고칠 값이 없어 안 씁니다. */
  orderType?: string
  /** 폼의 체결조건 낱말. */
  condition?: string
  /** 주문가격. 값을 안 싣는 유형이면 비워 둡니다. */
  price?: number | null
  /** 스탑가격. 해외 STOP 두 유형에만 씁니다. */
  stopPrice?: number | null
  /** 자릿수 — 가격을 **화면에 보이는 글자 그대로** 보내는 데 씁니다. */
  decimals: number
  /** 정정·취소가 가리키는 원주문번호. */
  originalOrderNo?: string
  /** 확인창을 연 때의 계좌(모의·실전). 보내는 순간의 계좌와 다르면 보내지 않습니다 —
   *  창에서 본 계좌와 다른 계좌로 주문이 나가면 안 됩니다. */
  environment: Environment
}

/** 확인창을 연 뒤 계좌가 바뀌어 보내지 않았을 때의 사유. */
export const ENVIRONMENT_CHANGED = '확인창을 연 뒤 계좌가 바뀌어 주문을 내지 않았습니다'

/** 답 다섯 갈래. **사용자가 할 일이 다릅니다.**
 *
 *  `accepted` 접수됨 — 줄을 목록에 얹습니다. 접수 뒤 주문내역으로 결과까지
 *    확인됐으면 `confirmed` 가 참이고, 확인하지 못했으면 거짓입니다. 거짓이어도
 *    **접수는 접수입니다** — 주문은 나갔을 수 있어 다시 보내면 안 되고,
 *    주문체결상세에서 결과를 확인해야 합니다.
 *  `rejected` 서버가 거절 — 같은 값이면 같은 답이라 다시 보낼 자리가 없습니다.
 *    접수 번호를 받은 뒤에 거절된 것이면 `orderId` 가 있습니다.
 *  `unknown` 주문번호가 안 옴(504) — **냈는지 아닌지 모릅니다.** 다시 보내면 안
 *    되고, 주문내역에서 확인해야 합니다.
 *  `blocked` 서버가 안 보냄(환경 전환·불일치·재생 기록 없음) — 사유 그대로.
 *  `failed` 답을 못 받음(연결·시간 초과) — 이것도 냈는지 모르는 자리입니다.
 *
 *  `action` 은 무엇을 보낸 답인지(신규·정정·취소)입니다 — 같은 거절이라도
 *  「거절」과 「취소 거부」는 사용자가 읽는 뜻이 다릅니다. */
export type OrderResult =
  | { kind: 'accepted'; action: OrderKind; row: OrderEvent; orderId: string; confirmed: boolean }
  | { kind: 'rejected'; action: OrderKind; reason: string; code: string; orderId?: string }
  | { kind: 'unknown'; reason: string }
  | { kind: 'blocked'; reason: string }
  | { kind: 'failed'; reason: string }

/** 접수 뒤 결과 확인의 답(`outcome`). 서버가 접수 답에 함께 싣습니다. */
interface OrderOutcome {
  state?: unknown
  code?: unknown
  message?: unknown
}

/** 칸 값을 글자로. 글자가 아니면 빈 글자입니다. */
function textOf(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value).trim() : ''
}

const ROUTE: Record<OrderKind, string> = {
  new: '/api/domestic/order',
  modify: '/api/domestic/modify',
  cancel: '/api/domestic/cancel',
}

/** 해외는 신규·정정·취소가 한 라우트입니다. */
const OVERSEAS_ROUTE = '/api/overseas/order'

/** 국내 주문 요청 한 벌. 취소는 고칠 값이 없어 다섯 칸뿐입니다.
 *
 *  **보낼 수 없는 값이면 `null` 입니다.** 국내가 모르는 주문유형(해외 전용 STOP)을
 *  아는 유형으로 바꿔 보내지 않습니다 — 「STOP-L 로 냈다」고 생각한 사람에게
 *  지정가가 나가는 것이 이 화면에서 가장 나쁜 일입니다. */
function bodyOf(ask: OrderAsk, environment: string): Record<string, unknown> | null {
  const base = {
    environment,
    context: ask.context === 'domestic-night' ? 'domestic-night' : 'domestic-day',
    sym: ask.code,
    side: ask.side,
    ord_qty: ask.quantity,
  }
  if (ask.kind === 'cancel') return { ...base, org_ord_no: ask.originalOrderNo ?? '' }

  const typeCode = ORDER_TYPE_CODE[ask.orderType ?? '']
  if (!typeCode) return null
  const conditionCode = FILL_CONDITION_CODE[ask.condition ?? '']
  if (!conditionCode) return null
  const made: Record<string, unknown> = {
    ...base,
    ord_tp_cd: typeCode,
    exec_cnd_cd: conditionCode,
    /* 값을 안 싣는 유형은 빈 글자입니다 — 서버가 명세대로 `0` 을 채웁니다.
       화면이 0 을 보내면 「0 원에 내겠다」와 구분되지 않습니다. */
    /* 가격 글자는 가능수량 조회·해외 주문과 같은 자리(`orderable.ts` 의 `priceText`)에서
       만듭니다 — 자릿수대로 적되, 그렇게 적어 값이 달라지면 값을 그대로 보냅니다.
       사용자가 친 값이 조용히 바뀌어 나가는 것보다 서버가 돌려보내는 편이 낫습니다. */
    ord_pric:
      ZERO_PRICE_TYPES.has(typeCode) || ask.price === null || ask.price === undefined
        ? ''
        : priceText(ask.price, ask.decimals),
  }
  if (ask.kind === 'modify') made.org_ord_no = ask.originalOrderNo ?? ''
  return made
}

/** 해외 주문 구분 코드. 해외는 신규·정정·취소가 라우트 하나에 이 값으로 갈립니다. */
const OVERSEAS_KIND_CODE: Record<OrderKind, string> = { new: '1', modify: '2', cancel: '3' }

/** 주문가격을 싣는 해외 주문유형(지정가·STOP지정가). */
const OVERSEAS_PRICED = new Set(['2', '4'])

/** 스탑가격을 싣는 해외 주문유형(STOP시장가·STOP지정가). */
const OVERSEAS_STOPPED = new Set(['3', '4'])

/** 해외 주문 요청 한 벌, 또는 보낼 수 없는 까닭.
 *
 *  **취소에도 주문유형과 가격을 싣습니다.** 서버가 취소에도 주문유형을 요구하고,
 *  지정가 계열은 가격을, STOP 은 스탑가격을 함께 요구합니다. 정정·취소의 값은
 *  원주문의 것이고(부르는 쪽이 미체결 줄에서 폼으로 옮겨 둡니다), 정정이면 가격·
 *  스탑가격·수량이 폼의 새 값입니다. 취소를 시장가로 꾸며 보내지 않습니다.
 *
 *  가격 글자는 가능수량 조회와 같은 자리(`orderable.ts` 의 `priceText`)에서 만듭니다 —
 *  분수 호가 품목은 자릿수가 0 이어도 값에 소수가 있어, 자릿수만 믿고 자르면 화면
 *  값과 다른 값이 나갑니다. */
function overseasBodyOf(
  ask: OrderAsk,
  environment: string,
): { body: Record<string, unknown> } | { why: string } {
  const original = ask.kind !== 'new'
  const form = overseasFormType(ask.orderType ?? '')
  const typeCode = form === null ? undefined : OVERSEAS_TYPE_CODE[form]
  if (!typeCode) {
    return {
      why: original
        ? '원주문의 주문유형을 알 수 없어 보내지 않았습니다'
        : '이 주문유형은 해외 주문으로 낼 수 없습니다',
    }
  }
  const priced = OVERSEAS_PRICED.has(typeCode)
  const stopped = OVERSEAS_STOPPED.has(typeCode)
  const price = ask.price ?? null
  const stop = ask.stopPrice ?? null
  /* 실어야 할 값이 비어 있으면 보내지 않습니다. 빈 값을 서버에 맡기면 서버가
     돌려보내기는 하지만, 원주문의 값을 모르는 채로 취소를 낸 셈이 됩니다. */
  if (priced && price === null) {
    return {
      why: original ? '원주문의 가격을 알 수 없어 보내지 않았습니다' : '주문가격을 넣으세요',
    }
  }
  if (stopped && stop === null) {
    return {
      why: original ? '원주문의 스탑가격을 알 수 없어 보내지 않았습니다' : '스탑가격을 넣으세요',
    }
  }
  const body: Record<string, unknown> = {
    environment,
    sym: ask.code,
    side: ask.side,
    qt_div_cd: OVERSEAS_KIND_CODE[ask.kind],
    glb_ord_tp_cd: typeCode,
    ord_qty: ask.quantity,
    /* 값을 안 싣는 유형은 빈 글자입니다 — 서버가 명세대로 채웁니다. */
    ord_pric: priced && price !== null ? priceText(price, ask.decimals) : '',
    stop_pric: stopped && stop !== null ? priceText(stop, ask.decimals) : '',
  }
  if (original) body.org_ord_no = ask.originalOrderNo ?? ''
  return { body }
}

/** 서버가 낸 문장. 없으면 우리 문장을 쓰지 않고 상태 코드만 말합니다 — 사유를
 *  지어내면 사용자가 그것을 서버의 말로 읽습니다. */
function reasonOf(body: unknown, status: number): string {
  const said = body as { reason?: unknown; detail?: unknown; message?: unknown } | null
  /* **요청 값 검사(422)** 는 검사 목록으로 옵니다. 첫 항목의 문장만 한 줄로 씁니다.
     우리 검사기의 한국어 문장에는 검사 도구가 「Value error, 」를 앞에 붙이므로 떼고,
     한글이 한 자라도 있으면 그대로 둡니다. 영어뿐인 문장(형식 검사)은 서버의 말처럼
     세우지 않고 우리 문장으로 대신합니다. */
  if (status === 422 && Array.isArray(said?.detail)) {
    const first = (said.detail[0] ?? null) as { msg?: unknown } | null
    const msg = typeof first?.msg === 'string' ? first.msg.replace(/^Value error,\s*/, '').trim() : ''
    return /[가-힣]/.test(msg) ? msg : '주문 값이 서버 검사에 걸렸습니다 (422)'
  }
  for (const value of [said?.reason, said?.detail, said?.message]) {
    if (typeof value === 'string' && value.trim() !== '') return value.trim()
  }
  return `주문을 내지 못했습니다 (${status})`
}

/** 한 번 보냅니다. **겹쳐 보내는 것은 부르는 쪽이 막습니다** — 이 자리에서 막으면
 *  무엇을 안 보냈는지 화면이 모르게 됩니다. */
export async function sendOrder(ask: OrderAsk): Promise<OrderResult> {
  const active = environmentState().active
  if (!active) {
    return {
      kind: 'blocked',
      reason: '지금이 모의인지 실전인지 확인되지 않아 주문을 내지 않았습니다',
    }
  }
  if (ask.environment !== active) {
    return { kind: 'blocked', reason: ENVIRONMENT_CHANGED }
  }

  /* **시장이 라우트와 요청 모양을 정합니다.** 해외는 라우트 하나에 세 동작이
     실리고, 국내는 동작마다 라우트가 따로입니다. 답을 읽는 길은 두 시장이 같습니다.
     보낼 수 없는 값이면 **요청이 안 나간 것이 확실한** 얼굴(`blocked`)로 돌려줍니다. */
  let route: string
  let body: Record<string, unknown>
  if (ask.context === 'overseas') {
    const made = overseasBodyOf(ask, ask.environment)
    if ('why' in made) return { kind: 'blocked', reason: made.why }
    route = OVERSEAS_ROUTE
    body = made.body
  } else {
    const made = bodyOf(ask, ask.environment)
    /* 국내가 모르는 주문유형·체결조건입니다. 아는 값으로 바꿔 보내지 않습니다. */
    if (!made) {
      return { kind: 'blocked', reason: '이 주문유형은 국내 주문으로 낼 수 없습니다' }
    }
    route = ROUTE[ask.kind]
    body = made
  }

  let response: Response
  try {
    response = await fetch(route, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    /* **냈는지 모르는 자리입니다.** 요청이 나간 뒤 끊겼을 수도 있어 「안 나갔다」로
       말하지 않습니다. */
    return {
      kind: 'failed',
      reason: '주문을 보냈는지 확인하지 못했습니다. 주문체결상세에서 확인해 주세요',
    }
  }

  const answered = await response.json().catch(() => null)

  if (response.status === 504) return { kind: 'unknown', reason: reasonOf(answered, 504) }
  if (!response.ok) return { kind: 'blocked', reason: reasonOf(answered, response.status) }

  const said = answered as
    | (OrderEvent & { accepted?: boolean; reason?: string; code?: unknown; outcome?: OrderOutcome })
    | null
  if (!said || said.accepted === false) {
    return { kind: 'rejected', action: ask.kind, reason: reasonOf(said, 200), code: textOf(said?.code) }
  }

  const orderId = String(said.id ?? '').trim()
  /* 주문번호가 비어 오면 **접수라고 말하지 않습니다** — 번호 없는 줄은 목록에서
     찾을 수도 거둘 수도 없습니다. 서버가 504 로 가르지만, 200 으로 오는 길도
     같은 얼굴이어야 합니다. */
  if (!orderId) {
    return {
      kind: 'unknown',
      reason: '주문번호가 오지 않았습니다. 주문체결상세에서 확인해 주세요',
    }
  }

  /* **접수 번호를 받은 뒤에 거절되는 주문이 있습니다.** 서버가 접수 뒤 주문내역을
     조회해 그 결과를 `outcome` 에 실어 줍니다. 거절이면 접수 번호가 있어도 거절로
     말합니다 — 「접수됨」으로 두면 계좌에 없는 주문을 있는 줄로 압니다. 코드와
     문구는 서버가 준 그대로입니다(문구가 안 오면 서버가 오류 사전의 예비 문구를
     채웁니다). 결과를 확인하지 못했으면(`unknown`, 칸 없음) 접수를 뒤집지 않고
     「결과 미확인」으로 둡니다. */
  const outcome = said.outcome ?? null
  if (outcome?.state === 'rejected') {
    return {
      kind: 'rejected',
      action: ask.kind,
      reason: textOf(outcome.message),
      code: textOf(outcome.code),
      orderId,
    }
  }
  return { kind: 'accepted', action: ask.kind, row: said, orderId, confirmed: outcome?.state === 'accepted' }
}
