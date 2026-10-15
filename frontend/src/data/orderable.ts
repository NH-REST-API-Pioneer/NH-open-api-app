/** 주문가능수량을 물어보는 자리.
 *
 *  **저절로 부르지 않습니다.** 계좌에 묻는 값이라 값이 도착하려면 사용자가
 *  단추를 눌러야 합니다. 시세처럼 화면이 열릴 때 채우면, 주문 화면을 지나기만
 *  해도 계좌 조회가 나갑니다.
 *
 *  **받은 값을 수량 칸에 넣지 않습니다.** 증거금 한도까지 채우는 것은 이
 *  화면에서 가장 위험한 선택이라, 한 번 눌러 들어가면 안 됩니다.
 *
 *  두 시장이 부르는 법이 다릅니다 — 국내는 방향을 함께 물어 **한 방향의 답**을
 *  받고, 해외는 주문유형과 스탑가격까지 함께 물어봅니다. 대신 **돌아오는
 *  낱말은 같습니다.** 화면이 시장마다 다른 자리를 만들지 않게 하려는 것이라,
 *  이 파일도 두 갈래를 한 모양으로 냅니다.
 */
import type { MarketContext } from '../lib/types'
import { accepts, generation } from './environment'
import { ORDER_TYPES, needsPriceFor, needsStopFor } from './strategyRules'

/** 서버가 내는 주문가능수량. **값은 비어 올 수 있습니다** — 없으면 `null` 이고,
 *  그것은 0 이 아니라 「이 자리에 값이 없다」는 뜻입니다.
 *
 *  `quantity` 는 신규와 청산을 합한 수이고 `newQuantity`(신규)·`closeQuantity`(청산)
 *  가 따로 옵니다. 셋의 관계(합 = 신규 + 청산인지, 청산가능이 보유와 같은지)는
 *  포지션을 든 채 실서버에 물어 확인하기 전이라, 화면은 합을 그 이름으로 보이고
 *  둘은 상태에만 담아 둡니다. */
export interface OrderableReply {
  code: string
  market: 'domestic' | 'overseas'
  side: string
  quantity?: number | null
  newQuantity?: number | null
  closeQuantity?: number | null
  amount?: number | null
  currency?: string | null
  productCode?: string | null
}

/** 다시 불러 볼 만한 실패인지. 거절은 눌러도 같은 답이 옵니다. */
export type OrderableFailure = 'retry' | 'rejected'

/** 값 자리가 지금 무엇을 말하고 있는지.
 *
 *  `idle` 은 **아직 안 눌렀다**는 뜻이고, 그때 값 자리에는 아무것도 안 섭니다 —
 *  어느 시장이든 누르기 전에는 비어 있는 자리라, 여기에만 표지를 세우면 덜
 *  아는 쪽이 더 많이 말하는 화면이 됩니다. */
export type OrderableState =
  | { status: 'idle' }
  | { status: 'loading' }
  | {
      status: 'ready'
      /** 신규·청산 합. 화면에 서는 값입니다. */
      quantity: number | null
      /** 신규 가능·청산 가능. 관계가 확인되면 폼 모드에 맞는 쪽이 섭니다. */
      newQuantity: number | null
      closeQuantity: number | null
    }
  | { status: 'failed'; failure: OrderableFailure }

export const ORDERABLE_IDLE: OrderableState = { status: 'idle' }

/** 화면이 들고 있는 값 그대로. 무엇을 보낼지는 아래 `askOrderable` 이 정합니다. */
export interface OrderableAsk {
  context: MarketContext
  code: string
  side: 'buy' | 'sell'
  orderType: string
  /** 주문가격 칸의 값. 시장가·STOP-M 이면 비어 있습니다. */
  price: number | null
  /** 스탑가격 칸의 값. 해외 STOP 두 유형에만 있습니다. */
  stopPrice: number | null
  /** 그 종목의 값이 지금 얼마인지. 시장가로 물어볼 때 대신 실어 보냅니다. */
  last: number | null
  decimals: number
}

/** 해외 주문유형 코드.
 *
 *  **목록의 차례로 만들지 않고 하나씩 적습니다.** 차례에서 뽑으면 화면에 보이는
 *  줄 순서를 바꾸는 것만으로 증권사에 나가는 코드가 조용히 바뀝니다. */
export const OVERSEAS_TYPE_CODE: Record<string, string> = {
  시장가: '1',
  지정가: '2',
  'STOP-M': '3',
  'STOP-L': '4',
}

/** 미체결 줄이 쓰는 해외 주문유형 낱말 → 폼 낱말.
 *
 *  서버의 주문 줄은 STOP 두 유형을 풀어 쓴 이름으로 적어 오고, 폼과 코드표는
 *  짧은 이름을 씁니다. 두 이름의 짝은 이 자리 하나에만 둡니다 — 정정·취소가
 *  원주문의 유형을 코드로 옮길 때 이 짝을 거쳐 위 코드표 하나로 갑니다. */
const OVERSEAS_ROW_TYPE: Record<string, string> = {
  STOP시장가: 'STOP-M',
  STOP지정가: 'STOP-L',
}

/** 해외 주문유형 낱말(폼 또는 미체결 줄)을 폼 낱말로. 모르는 낱말이면 `null`
 *  입니다 — 아는 유형으로 바꿔 두지 않습니다. */
export function overseasFormType(word: string): string | null {
  const form = OVERSEAS_ROW_TYPE[word] ?? word
  return form in OVERSEAS_TYPE_CODE ? form : null
}

if (import.meta.env.DEV) {
  const missing = ORDER_TYPES.overseas.filter((type) => !(type in OVERSEAS_TYPE_CODE))
  if (missing.length > 0) {
    console.warn('[orderable] 코드가 없는 해외 주문유형:', missing.join(', '))
  }
}

/** 숫자를 서버가 받는 글자로 바꿉니다.
 *
 *  자릿수대로 적되, **그렇게 적어 값이 달라지면 적지 않습니다.** 분수로 값을
 *  받는 품목은 자릿수가 0 인데 실제 값에 소수가 있어, 자릿수만 믿고 자르면
 *  **보낸 값과 화면 값이 어긋납니다.** 되돌릴 수 없는 자리로 가는 값이라
 *  어긋나느니 길게 보냅니다. */
export function priceText(value: number, decimals: number): string {
  const digits = Math.min(8, Math.max(0, Math.trunc(decimals) || 0))
  const fitted = value.toFixed(digits)
  const text =
    Number(fitted) === value ? fitted : value.toFixed(8).replace(/0+$/, '').replace(/\.$/, '')
  /* 0 에 아주 가까운 음수는 「-0.00」으로 적힙니다(스프레드는 음수 가격을 씁니다).
     0 은 부호 없이 보냅니다. */
  return /^-0(\.0+)?$/.test(text) ? text.slice(1) : text
}

/** 지금 물어볼 수 있는지.
 *
 *  **가격을 모르면 못 물어봅니다.** 두 시장 모두 주문가격이 있어야 답이 나오고
 *  (명세상 시장가에도 필수), 시장가로 물을 때는 그 종목의 지금 값을 대신
 *  싣습니다. 그 값마저 없으면 부를 수 없습니다. */
export function canAskOrderable(ask: OrderableAsk): boolean {
  if (!ask.code) return false
  if (priceFor(ask) === null) return false
  if (ask.context === 'overseas') {
    if (!(ask.orderType in OVERSEAS_TYPE_CODE)) return false
    if (needsStopFor(ask.orderType) && ask.stopPrice === null) return false
  }
  return true
}

function priceFor(ask: OrderableAsk): number | null {
  return needsPriceFor(ask.orderType) ? ask.price : ask.last
}

/** 물어보고 값 자리가 말할 것을 돌려줍니다. **던지지 않습니다** — 실패도 화면이
 *  세워야 하는 얼굴이라 상태로 냅니다. */
export async function askOrderable(ask: OrderableAsk): Promise<OrderableState> {
  const price = priceFor(ask)
  if (price === null) return { status: 'failed', failure: 'rejected' }

  const overseas = ask.context === 'overseas'
  const path = overseas ? '/api/overseas/orderable-quantity' : '/api/domestic/orderable-quantity'
  const body = overseas
    ? {
        sym: ask.code,
        side: ask.side,
        glb_ord_tp_cd: OVERSEAS_TYPE_CODE[ask.orderType],
        ord_pric: priceText(price, ask.decimals),
        stop_pric: ask.stopPrice === null ? '' : priceText(ask.stopPrice, ask.decimals),
      }
    : {
        sym: ask.code,
        side: ask.side,
        ord_pric: priceText(price, ask.decimals),
        context: ask.context,
      }

  /* 어느 환경에서 물었는지 적어 둡니다. 답이 왔을 때 환경이 바뀌어 있거나 답이
     다른 환경의 것이면 그 수는 다른 계좌의 수라 세우지 않습니다 — 「다른 종목의
     답」과 같은 자리로 되돌립니다. */
  const since = generation()
  try {
    const response = await fetch(path, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!accepts(response, since)) return { status: 'idle' }
    if (!response.ok) {
      /* 거절(502)은 다시 눌러도 같은 답이 옵니다. 나머지는 다시 불러 볼
         만합니다 — 어느 쪽인지로 「다시」 단추가 서고 안 서고가 갈립니다. */
      return { status: 'failed', failure: response.status === 502 ? 'rejected' : 'retry' }
    }
    const reply = (await response.json()) as OrderableReply
    /* **다른 종목의 답이면 버립니다.** 누르고 나서 종목을 바꾸면 앞 종목의
       답이 뒤늦게 도착하는데, 그것이 새 종목의 값으로 서면 안 됩니다. */
    if (reply.code && reply.code !== ask.code) return { status: 'idle' }
    return {
      status: 'ready',
      quantity: reply.quantity ?? null,
      newQuantity: reply.newQuantity ?? null,
      closeQuantity: reply.closeQuantity ?? null,
    }
  } catch {
    if (since !== generation()) return { status: 'idle' }
    return { status: 'failed', failure: 'retry' }
  }
}
