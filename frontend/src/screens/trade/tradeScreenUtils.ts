import type { MarketContext } from '../../lib/types'
import { contractRows } from '../../data/expiryQuotes'
import { resolve, type Instrument } from '../../data/instruments'
import type { MasterLegs } from '../../data/master'
import type { InstrumentRef } from '../../lib/InstrumentPicker'
import type { ListEntry, ServerPosition } from '../../data/account'
import type { CardKey, SlotKey } from './tradeLayout'

export const FUTURES_TABS = ['차트', '품목정보'] as const
export const OPTION_TABS = ['체인', '차트', '품목정보'] as const
export type Tab = (typeof OPTION_TABS)[number]

/* 슬롯 안에서 몇 번째 카드가 열려 있는지. 슬롯에 하나만 서면 쓰이지 않습니다. */
export type SlotTabs = Partial<Record<SlotKey, CardKey>>


/* 2분할을 처음 켤 때 둘째 칸에 넣는 종목 — 이 화면 종목의 차월물입니다.
 * 같은 차트 둘로 시작하면 「왜 같은 게 둘이지」가 되고, 근월·차월을 나란히
 * 보는 것이 두 칸의 가장 흔한 쓰임입니다. 차월물이 없으면 그 종목 그대로입니다. */
export function nextMonthOf(item: Instrument | null): InstrumentRef | null {
  /* **지금 보고 있는 종목의** 차월물입니다. 시장에서 첫 선물 품목을 집으면
     무엇을 보고 있든 코스피200(해외면 WTI)이 둘째 칸에 서서, 근월·차월을
     견주려던 자리에 남의 종목이 들어옵니다. */
  if (!item || item.kind !== 'futures') return null
  const market: MarketContext = item.market === 'overseas' ? 'overseas' : 'domestic-day'
  const contracts = contractRows(item.product, 'futures')
  const index = contracts.findIndex((row) => row.code === item.contract?.code)
  const row = contracts[index >= 0 ? index + 1 : 1] ?? contracts[0]
  if (!row) return null
  return {
    code: row.code,
    name: row.name,
    productName: item.product.name,
    market,
    lastPrice: row.last,
    decimals: item.product.decimals ?? 2,
    currency: item.market === 'overseas' ? 'USD' : '원',
  }
}

/* 코드 하나를 차트 칸이 들 수 있는 모양으로 바꿉니다.
 *
 * 칸은 신원만이 아니라 배지에 그릴 값까지 들고 있어, 코드만으로는 칸을 채울 수
 * 없습니다. 신원은 해석기에서, 값은 그 품목의 만기 목록에서 받습니다 — 두 곳을
 * 쓰지만 **어느 종목인가는 해석기 하나가 정합니다.** */
export function refFor(code: string): InstrumentRef | null {
  const item = resolve(code)
  if (!item) return null
  const market: MarketContext = item.market === 'overseas' ? 'overseas' : 'domestic-day'
  /* 옵션은 행사가마다 종목이라 만기 목록에 없습니다. 값은 기초 선물의 것을
     쓰고, 행사가를 고르면 체인이 그 칸의 값을 냅니다. */
  const row = contractRows(item.product, item.kind).find((entry) => entry.code === code)
  return {
    code,
    name: item.name,
    productName: item.product.name,
    market,
    /* 배지에 적을 값은 **그 품목의 만기 목록에 실린 행**에서 옵니다(위 `row`).
       그 값은 만기 목록 조회가 받아 둔 것입니다(`data/expiryQuotes.ts`).

       **행이 없거나 그 월물이 답에 없으면 빈 채로 둡니다** — 옵션 만기 코드처럼
       목록에 안 서는 종목이 있고, 조회에 안 실려 온 월물도 있습니다. 그때 다른
       줄의 값이나 대신 지은 숫자를 세우면 그 배지가 이 종목의 현재가로 읽힙니다. */
    lastPrice: row?.last ?? null,
    decimals: item.product.decimals ?? 2,
    currency: item.market === 'overseas' ? 'USD' : '원',
  }
}


/* 자리가 모자랄 때 무엇이 남아야 하나. **주문 대상 종목이 가장 높습니다** —
 * 그 값이 멈추면 지금 내려는 주문의 가격이 낡습니다. 두 칸 모드의 다른 칸은
 * 보고는 있지만 주문 대상이 아니라 한 급 아래이고, 홈의 관심종목은 훑는
 * 자리라 그보다 아래입니다(`HomeScreen`). */
/** 계좌가 바뀌어 주문을 접은 뒤 실행 단추를 멈춰 두는 시간(ms). */
export const SUBMIT_PAUSE_MS = 1500

export const SUBJECT_RANK = 9
export const SECOND_RANK = 7

/** 해외 옵션 시리즈 코드(`O_ESU26`) — 품목코드 + 월물 글자 + 연도 뒤 두 자리.
 *
 *  **색인이 코드를 안 줄 때만 씁니다.** 한 달에 만기가 하나인 품목은 만기년월로
 *  지으면 맞지만, 여럿인 품목은 만기마다 다른 코드라 이 규칙으로는 못 짓습니다. */
export const MONTH_LETTERS = 'FGHJKMNQUVXZ'
export function overseasSeriesCode(productCode: string, expiry: string): string | null {
  if (expiry.length < 6) return null
  const month = Number(expiry.slice(4, 6))
  if (!Number.isInteger(month) || month < 1 || month > 12) return null
  return `${productCode}${MONTH_LETTERS[month - 1]}${expiry.slice(2, 4)}`
}

/** 시장마다 받은 잔고 목록을 **표 하나의 상태**로 합칩니다.
 *
 *  한 시장이라도 줄이 있으면 그 줄들로 표가 섭니다 — 다른 시장이 아직 오지
 *  않았거나 못 받았다고 받은 줄까지 가리지 않습니다(못 받은 시장은 표 위 한 줄이
 *  따로 말합니다). 받은 시장이 **모두** 새로 받기에 실패했을 때만 그 사정을
 *  이어받아 표 전체의 「지난 값」 문장이 섭니다 — 한 시장만 옛값이면 그 시장
 *  이름을 단 한 줄이 따로 말합니다. 줄이 하나도 없으면 받는 중인 시장의 얼굴을,
 *  없으면 첫 시장의 얼굴(못 받음 등)을 씁니다. 찬 시장이 없으면 `fallback`
 *  (인증 정보가 없어 안 부른 자리)입니다. */
export function mergedPositionList(
  entries: ListEntry<ServerPosition>[],
  fallback: ListEntry<ServerPosition>,
): ListEntry<ServerPosition> {
  if (entries.length === 0) return fallback
  const received = entries.filter((entry) => entry.rows !== null)
  if (received.length === 0) {
    return entries.find((entry) => entry.status === 'loading' || entry.status === 'idle') ?? entries[0]
  }
  return {
    ...received[0],
    status: 'ready',
    rows: received.flatMap((entry) => entry.rows ?? []),
    failure: received.every((entry) => entry.failure !== null) ? received[0].failure : null,
    refreshing: entries.some((entry) => entry.refreshing === true || entry.status === 'loading'),
  }
}

/** 그 종목이 스프레드면 두 다리의 만기(마스터 값), 아니면 `null`. */
export function spreadLegsOf(code: string): MasterLegs | null {
  const found = resolve(code)
  return found?.contract?.kind === 'spread' ? (found.contract.legs ?? null) : null
}
