/** 서버가 낸 계좌 줄을 화면이 그리는 줄로.
 *
 *  **서버 값과 우리가 채운 값을 가르는 자리입니다.** 자료층은 서버 모양 그대로
 *  담고, 여기서만 마스터를 얹습니다. 한 곳에 모아 두면 값이 이상할 때 「서버가
 *  그랬나 우리가 그랬나」를 한 자리에서 봅니다.
 *
 *  **마스터에서 채우는 것은 시장마다 다릅니다.**
 *
 *      국내 잔고   만기·잔존일수·자릿수가 없어 마스터에서 (이름은 옵니다)
 *      해외 잔고   이름이 없어 마스터에서 (만기·통화는 옵니다)
 *
 *  **못 찾으면 대신 세울 것이 있으면 그것을, 없으면 「—」입니다.** 해외 종목명을
 *  못 찾으면 **코드**를 세웁니다 — 코드는 받았으니 그 줄이 무엇인지는 말할 수
 *  있습니다. 국내 만기는 대신 세울 것이 없어 비웁니다.
 */
import { resolve } from './instruments'
import type {
  AccountOrder,
  Fill,
  MarketContext,
  OpenOrder,
  OrderError,
  OrderProgress,
  Position,
} from '../lib/types'
import type { ServerOrder, ServerOrderError, ServerPosition } from './account'

/** 그 종목의 소수 자릿수. 마스터가 답하고, 못 찾으면 `null` 입니다 —
 *  **자릿수를 지어내면 보이는 값이 받은 값과 달라집니다.** */
function decimalsOf(code: string): number | null {
  return resolve(code)?.product.decimals ?? null
}

/** 종목 목록에서 그 종목을 못 찾았을 때 다는 한 줄. 이름만이 아니라
 *  만기·자릿수도 함께 없어, 그 줄이 왜 반쯤 비어 있는지를 이것이 답합니다.
 *
 *  **낱말은 「종목 목록」입니다** — 받아 오는 자료의 이름(「종목 마스터」)이 아니라
 *  화면이 부르는 이름으로 적습니다. 서버가 내는 같은 뜻의 문장도 같은 말을 씁니다. */
export const NO_MASTER_NOTE = '종목 목록에서 찾지 못했습니다'

/** 줄의 종류를 나르는 낱말. 지금 쓰는 곳은 **주문체결상세 한 곳**입니다.
 *
 *  **계좌 미체결 표에는 안 답니다.** 그 표는 살아 있는 주문만 담아 「정정으로
 *  낸 주문」이라는 사실이 설명할 것이 없고, 같은 줄의 동작 칸에 「정정」 단추가
 *  서 있어 한 낱말이 한 줄에서 두 뜻이 됩니다. 한 번 달았다가 걷은 자리라
 *  까닭을 적어 둡니다.
 *
 *  **신규에는 안 답니다.** 거의 모든 줄이 신규라 배지를 달면 표가 그 말로
 *  덮이고, 눈에 띄어야 할 정정·취소가 도리어 묻힙니다.
 *
 *  **요청의 이름이지 결과가 아닙니다.** 「정정」은 정정으로 낸 주문이라는 뜻이고,
 *  그 주문이 아직 살아 있는지 끝났는지는 말하지 않습니다 — 그것은 상태 칸이
 *  답합니다. 그래서 「정정됨」처럼 지난 일로 적지 않습니다. */
export function orderKindWord(kind: string | undefined): string | null {
  if (kind === 'modify') return '정정'
  if (kind === 'cancel') return '취소'
  return null
}

/** 화면에 세울 이름. **마스터가 정합니다.**
 *
 *  잔고와 국내 주문 응답은 제 이름을 함께 줍니다(「미국달러 F 202609」). 그런데
 *  나머지 화면은 전부 마스터 이름(「미국달러 26년 9월물」)을 쓰므로, 그대로 두면
 *  **한 앱 안에서 같은 종목이 화면마다 다르게 불립니다.** 주문을 내는 앱에서 그건
 *  다른 종목으로 읽힙니다.
 *
 *  **「받은 것은 그대로」와 부딪히지 않습니다** — 그 규칙은 값에 대한 것이고,
 *  이름은 값이 아니라 가리킴입니다. 두 표기가 같은 종목을 가리키므로 어느 쪽을
 *  세워도 사실이 안 바뀌고, 그러면 하나로 부르는 편이 낫습니다.
 *
 *  마스터에 없으면 응답이 준 이름을, 그것도 없으면 코드를 세웁니다 — 받은 것은
 *  보입니다. 뒤 둘에는 [[NO_MASTER_NOTE]] 가 함께 섭니다. */
function nameOf(code: string, given: string | undefined): string {
  const master = resolve(code)?.name
  if (master) return master
  const own = given?.trim()
  if (own) return own
  return code
}

/** 그 줄의 이름이 마스터에서 온 것이 아니면 까닭 한 줄. */
function noteOf(code: string): string | undefined {
  return resolve(code) ? undefined : NO_MASTER_NOTE
}

/** 만기와 잔존일수. 해외는 응답이 만기를 주고 잔존일수는 없습니다.
 *  국내는 둘 다 마스터가 답합니다. */
function expiryOf(code: string, given: string | null | undefined) {
  const contract = resolve(code)?.contract ?? null
  return {
    expiry: given ?? contract?.expiry ?? '',
    daysLeft: contract?.daysLeft ?? null,
  }
}

/** 해외 손익률.
 *
 *  **응답에 없어 화면이 셈합니다.** 국내는 서버가 줍니다 — 해외만 이 길입니다.
 *  **화면이 값을 만드는 자리를 하나만 두기로 하고 남겨 둔 예외**이고, 백엔드도
 *  「화면이 평균가와 현재가로 셈한다」고 응답 설명에 적어 두었습니다
 *  (`overseas_account.py` 의 `positions()`).
 *
 *  셈해도 되는 까닭은 **답이 하나로 정해지기 때문**입니다 — 평균가와 현재가가
 *  있으면 우리가 고를 여지가 없습니다. 환율처럼 우리가 고르는 값이 끼면 그건
 *  셈이 아니라 지어내는 것이라, 그 자리는 서버가 답할 때까지 비워 둡니다.
 *
 *  **평균가가 없거나 0 이면 셈하지 않습니다** — 나눌 수 없는 자리라 「—」입니다.
 *  값이 0 인 것과 「셈할 수 없다」는 다른 말입니다.
 *
 *  국내 서버 값과 셈법이 같은지는 **아직 못 견줬습니다** — 기록에 든 유일한
 *  줄이 평균가와 현재가가 같아 어느 셈법으로도 0 이 나옵니다. 평가손익이 0 이
 *  아닌 기록이 들어오는 날 **국내 종가로 셈한 값과 국내 서버 값**을 견줍니다
 *  (해외 현재가와 견주면 차이가 셈법 탓인지 기준 시점 탓인지 안 갈립니다).
 */
function percentOf(row: ServerPosition): number | null {
  if (row.plPct !== null && row.plPct !== undefined) return row.plPct
  const avg = row.avgPrice
  const last = row.lastPrice
  if (avg === null || avg === undefined || avg === 0) return null
  if (last === null || last === undefined) return null
  /* 분모는 평균가의 **크기**입니다. 스프레드는 평균가가 음수일 수 있는데, 그대로
     나누면 이익이 손실 %로 섭니다. */
  const move = ((last - avg) / Math.abs(avg)) * 100
  return row.side === 'short' ? -move : move
}

export function toPosition(row: ServerPosition, overseas: boolean): Position {
  const { expiry, daysLeft } = expiryOf(row.code, row.expiry)
  return {
    code: row.code,
    name: nameOf(row.code, row.name),
    nameNote: noteOf(row.code),
    expiry,
    daysLeft,
    market: (row.market as MarketContext) ?? (overseas ? 'overseas' : 'domestic-day'),
    side: row.side === 'short' ? 'short' : 'long',
    quantity: row.quantity ?? null,
    avgPrice: row.avgPrice ?? null,
    lastPrice: row.lastPrice ?? null,
    decimals: decimalsOf(row.code),
    /* 분수 꼴도 자릿수처럼 **그 줄 종목**이 정합니다 — 표는 계좌 전체 줄이라
       화면이 보고 있는 종목의 꼴을 쓰면 다른 종목의 가격이 틀린 꼴로 섭니다. */
    fraction: resolve(row.code)?.product.fraction ?? null,
    pl: row.pl ?? null,
    plPct: percentOf(row),
    /** 해외는 응답이 통화를 줍니다. 국내는 원화뿐이라 안 옵니다. */
    currency: row.currency ?? (overseas ? '' : 'KRW'),
    /** 서버가 준 대로 옮깁니다. 안 주는 시장에서는 `undefined` 로 남습니다. */
    productKind: row.productKind,
  }
}

export function toOrder(row: ServerOrder, overseas: boolean): AccountOrder {
  return {
    id: row.id,
    code: row.code,
    name: nameOf(row.code, row.name),
    nameNote: noteOf(row.code),
    market: (row.market as MarketContext) ?? (overseas ? 'overseas' : 'domestic-day'),
    side: row.side === 'sell' ? 'sell' : 'buy',
    orderType: row.orderType ?? '',
    price: row.price ?? null,
    stopPrice: row.stopPrice ?? null,
    decimals: decimalsOf(row.code),
    quantity: row.quantity ?? null,
    filled: row.filled ?? null,
    time: row.time ?? '',
    source: row.source ?? '',
    /** 서버가 준 대로 옮깁니다. 안 주는 동안에는 `undefined` 로 남습니다. */
    productKind: row.productKind,
    /** **우리 프로그램으로 낸 주문만 고칠 수 있습니다.** 아니면 정정 단추 자리에
     *  이것이 섭니다 — 못 고치는 주문에 폼을 열어 주면 값을 다 채운 뒤에야 못
     *  낸다는 것을 알게 됩니다.
     *
     *  **낱말은 결과입니다.** 이 표에는 출처 열이 따로 있어, 동작 칸에 매체
     *  이름을 또 쓰면 한 줄이 같은 것을 두 번 말합니다. 출처 열이 접히는
     *  주문체결상세에서만 동작 칸이 출처를 겸합니다.
     *
     *  **서버가 이 칸을 안 주면 못 고치는 쪽으로 둡니다.** 모르는 것을 「고칠 수
     *  있다」로 읽으면, 남의 매체로 낸 주문에 폼이 열립니다. */
    locked: row.editable === true ? undefined : '잠김',
  }
}

export function toOrderError(row: ServerOrderError, overseas: boolean): OrderError {
  return {
    /** **국내 응답에는 주문번호가 없습니다.** 해외만 옵니다. */
    id: row.orderNo ?? '',
    time: row.time ?? '',
    name: nameOf(row.code, row.name),
    nameNote: noteOf(row.code),
    market: (row.market as MarketContext) ?? (overseas ? 'overseas' : 'domestic-day'),
    message: row.message,
  }
}

/* ── 주문 화면의 주문체결상세 ────────────────────────────────
 *
 * **한 목록을 두 얼굴로 읽습니다.** 서버가 주는 주문 줄에는 진행 상태가 함께
 * 들어 있어, 체결이 끝난 줄은 체결로 서고 나머지는 주문으로 섭니다. 목록을
 * 둘로 나눠 받지 않는 까닭은 두 표가 같은 주문을 말하기 때문입니다 — 따로
 * 받으면 한쪽만 새 값일 때 같은 주문이 두 표에 다르게 섭니다.
 */

/** 주문체결상세 표에 서는 한 줄. */
export type TradeRow = { kind: 'open'; order: OpenOrder } | { kind: 'fill'; fill: Fill }

/** 체결이 끝난 줄인지.
 *
 *  **상태가 오면 그것이 답합니다.** 안 오는 줄은 남은 수량으로 봅니다 — 남은
 *  것이 없고 체결된 것이 있으면 끝난 주문입니다. 남은 수량도 안 오면 아직
 *  일하는 중으로 둡니다: 끝났다고 잘못 보면 정정·취소 자리가 사라져 **아직
 *  살아 있는 주문을 거둘 방법이 없어집니다.** */
function isFilled(row: ServerOrder): boolean {
  if (row.status) return row.status === 'filled'
  if (row.remaining === null || row.remaining === undefined) return false
  return row.remaining === 0 && (row.filled ?? 0) > 0
}

/** 주문 줄이 지금 어디 있는지. 모르면 「일하는 중」입니다 — 거절이라고 잘못
 *  적으면 살아 있는 주문을 끝난 것으로 읽게 됩니다. */
function progressOf(row: ServerOrder): OrderProgress {
  if (row.status === 'rejected') return 'rejected'
  if (row.status === 'auto-cancelled') return 'auto-cancelled'
  /* 우리가 방금 낸 주문의 접수 답입니다. 조회·알림이 덮으면 그때 상태가
     바뀝니다 — 그때까지는 체결 수량을 모르는 줄입니다. */
  if (row.status === 'accepted') return 'accepted'
  if (row.status === 'cancelled') return 'cancelled'
  /* **체결도 없고 남은 것도 없으면 끝난 줄입니다.** 정정하면 원주문이, 취소가
     받아들여지면 그 주문이 이 모습으로 남습니다 — 줄이 사라지지 않고 상태는
     살아 있는 주문과 같은 값이 와서, 이 두 수 말고는 가릴 것이 없습니다.
     (체결이 있고 남은 것이 없는 줄은 이 함수에 오지 않습니다 — [[isFilled]] 가
     먼저 체결로 보냅니다.)

     **둘 중 하나라도 안 오면 일하는 중으로 둡니다.** 모르는 것을 끝난 것으로
     읽으면 정정·취소 자리가 사라져 아직 살아 있는 주문을 거둘 수 없게 됩니다. */
  const filled = row.filled
  const remaining = row.remaining
  if (filled === 0 && remaining === 0) return 'closed'
  return 'working'
}

export function toTradeRow(row: ServerOrder): TradeRow {
  const side = row.side === 'sell' ? 'sell' : 'buy'
  if (isFilled(row)) {
    return {
      kind: 'fill',
      fill: {
        id: row.id,
        time: row.time ?? '',
        side,
        /* 나눠 체결된 주문은 **평균 체결가**가 그 주문이 받은 값입니다.
           마지막 한 조각의 가격을 적으면 주문 전체가 그 값에 된 것처럼
           읽힙니다. 평균이 안 오면 체결가격을, 둘 다 없으면 「—」입니다. */
        price: row.avgFillPrice ?? row.fillPrice ?? null,
        quantity: row.filled ?? null,
      },
    }
  }
  return {
    kind: 'open',
    order: {
      id: row.id,
      side,
      orderType: row.orderType ?? '',
      progress: progressOf(row),
      /** 서버가 준 대로 옮깁니다. 안 주는 줄에서는 `undefined` 로 남습니다. */
      orderKind: row.orderKind,
      price: row.price ?? null,
      stopPrice: row.stopPrice ?? null,
      quantity: row.quantity ?? null,
      filled: row.filled ?? null,
      source: row.source ?? '',
      /* **우리 프로그램으로 낸 주문만 참입니다.** 서버가 이 칸을 안 주면
         거짓으로 둡니다 — 못 고치는 주문에 폼을 열어 주는 쪽이 더 나쁩니다. */
      editable: row.editable === true,
    },
  }
}
