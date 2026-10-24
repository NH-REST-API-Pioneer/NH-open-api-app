/* 종목코드를 종목으로 푸는 곳.
 *
 * 화면 곳곳이 「지금 무엇을 보고 있나」를 알아야 합니다 — 헤더의 이름, 만기
 * 목록, 주문유형 목록, 차트, 호가, 주문 단추. 그 모두가 **코드 하나**에서
 * 나오게 하려면 코드를 품목·만기·종류·시장으로 푸는 자리가 하나 있어야 합니다.
 * 여기가 그 자리입니다.
 *
 * **재료는 둘입니다.** 종목 마스터 색인이 첫째이고, 화면에 서는 품목과 종목은
 * 거의 다 거기 실린 것입니다. 둘째는 **해외 옵션의 행사가 종목**인데, 마스터가
 * 품목과 만기까지만 주고 행사가마다 있는 종목코드는 안 실어 줍니다 — 그 코드는
 * 옵션 체인 응답이 알려 주므로, 체인을 받으면 여기에 적어 두고 그 뒤로는 마스터
 * 행처럼 풉니다. 그래서 그 종목들은 **이 세션에서 그 품목의 체인을 한 번 연
 * 뒤에만** 풀립니다. 어느 쪽이든 여기서 지어내는 종목은 없습니다.
 *
 * **시세는 돌려주지 않습니다.** 품목·만기·종류·시장은 하루 동안 안 바뀌는
 * 신원이고, 시세는 초당 여러 번 바뀝니다. 한 함수가 둘을 같이 돌려주면 값이
 * 한 번 바뀔 때마다 만기 목록과 주문유형 목록까지 다시 계산됩니다.
 *
 * **동기입니다.** 화면을 그리는 도중에 불리므로 기다리게 만들 수 없습니다.
 * 색인은 앱을 켤 때 한 번 받아 두고, 여기서는 그 위를 찾기만 합니다. 색인이
 * 아직 없으면 **모르는 코드와 같게 `null`** 이고, 「받는 중」인지 「없는
 * 종목」인지는 마스터 상태가 답합니다.
 *
 * **주간과 야간을 가르지 않습니다.** 같은 종목을 낮에 보든 밤에 보든 품목과
 * 만기는 같습니다 — 세션은 시계가 정하는 것이지 종목의 성질이 아닙니다.
 */

import type { Product, ProductKind } from '../lib/types'
import {
  axisOrder,
  decimalsOfProduct,
  fractionOfProduct,
  exchangeOfProduct,
  groupOfProduct,
  kindsOfProduct,
  masterIndex,
  tickDecimals,
  type MasterContract,
  type MasterIndex,
  type MasterLegs,
  type MasterProduct,
} from './master'

export type Market = 'domestic' | 'overseas'

/** 종목 하나의 신원. 값(현재가·등락)은 담지 않습니다. */
export interface ContractRef {
  code: string
  /** 목록과 만기 선택에 서는 이름. **종류마다 다릅니다** — 만기가 하나인
   *  선물·옵션은 「26년 9월물」이고, 만기가 둘인 스프레드는 두 만기를 다
   *  적습니다. */
  label: string
  /** 마스터가 실어 준 이름 원문. 화면에는 안 세우고 **검색이 봅니다** —
   *  사용자가 마스터에 적힌 대로 쳐도 찾히게 하려는 것입니다. */
  masterName: string
  /** 선물·옵션·스프레드. 한 품목에 세 종류가 다 있을 수 있어 종목마다 답니다. */
  kind: ProductKind
  /** 마스터가 준 만기 문자열. 월까지면 6자리, 날까지면 8자리입니다.
   *  **스프레드는 두 다리 중 앞의 것**입니다. */
  expiry: string
  /** 만기일 8자리(`20261210`). **`expiry` 와 따로 둡니다** — 국내 마스터는 월과
   *  날을 다른 칸으로 주고, 화면이 「최종거래일」로 적는 것은 날입니다. 해외
   *  마스터에는 날이 없어 `null` 입니다. */
  expiryDate: string | null
  /** 마스터가 주력으로 표시한 월물인가. **해외 선물에만 있습니다**(`lmon` —
   *  거래량 기준 최다월물). 국내 마스터에는 그 축이 없어 늘 `false` 입니다.
   *
   *  「최근 만기」와 **다른 축**입니다. 배지는 만기 사실을 말하고, 이 값은
   *  「비워 두면 여기부터 보는 것이 낫다」를 말합니다 — 근월이 한산하고 분기물에
   *  거래가 실리는 상품(금·SOFR·곡물 등)에서 둘이 갈립니다. */
  main: boolean
  /** 잔존일수. **없으면 없는 대로 둡니다** — 휴장일을 모르고 만기에서
   *  세면 거래소 값과 어긋나는데, 그건 주문 판단에 쓰는 숫자가 틀린 것입니다.
   *  국내 마스터는 행마다 실어 주고, 안 주는 시장은 색인이 만기일로 센 값을
   *  옵션 만기 줄에 실어 줍니다. 그것도 없으면 `null` 입니다. */
  daysLeft: number | null
  /** 옵션 체인을 부를 때 보내는 시리즈 코드. **마스터가 만기마다 다르게
   *  짓는 값**이라 만기년월로 지어 부르면 한 달에 만기가 여럿인 품목에서
   *  없는 코드가 됩니다. 색인이 안 주면 `null` 이고, 그때는 부르는 쪽이
   *  만기년월로 짓습니다. */
  seriesCode: string | null
  /** 스프레드 두 다리의 만기. **색인이 두 칸으로 줍니다** — 종목 이름에서
   *  만기를 뜯어내면 시장마다 다른 이름 규칙을 화면이 떠안게 됩니다.
   *  선물·옵션에는 없어 `null` 입니다. */
  legs: MasterLegs | null
  /** 한 틱의 값(그 종목 통화). **해외 마스터가 종목 행마다 줍니다**(`tval`) —
   *  호가단위 × 계약단위를 마스터가 이미 곱해 둔 값이라 화면이 셈하지 않습니다.
   *  국내 마스터에는 없어 `null` 입니다. */
  tickValue: number | null
}

/** 옵션에서 콜풋과 행사가. 선물에는 없습니다. */
export interface OptionLeg {
  side: 'call' | 'put'
  strike: number
}

export interface Instrument {
  product: Product
  market: Market
  kind: ProductKind
  /** 어느 만기인가. 품목만 알고 만기가 안 정해진 경우에는 없습니다. */
  contract: ContractRef | null
  /** 옵션일 때만. 행사가를 아직 안 골랐으면 `null` 입니다. */
  leg: OptionLeg | null
  /** **코드가 콜/풋까지는 말해 주는 경우** 그 값입니다. 국내 옵션 종목코드가
   *  그렇습니다 — 신원표가 콜풋(`opt_tp`)은 주고 행사가는 안 줍니다. 코드에 든
   *  것을 버리지 않도록, 축 하나가 정해진 채로 화면을 엽니다. */
  side?: 'call' | 'put' | null
  /** 화면에 그대로 쓰는 이름 — 「코스피200 선물 26년 9월물」 */
  name: string
}

/* 국내 옵션의 콜풋 코드. **원문 값이고 뜻은 마스터가 정합니다** — 체인 응답의
 * 종목명에서 3 은 「… C …」, 4 는 「… P …」입니다. */
const PUT = '4'

/* ── 만기 표기 ─────────────────────────────────────────── */

/** 만기를 **그 단위대로** 적습니다.
 *
 *  마스터가 월까지 주면 「26년 9월물」, 날까지 주면 「26년 9월 3일」입니다.
 *  월 단위로 뭉쳐 적으면 한 달에 만기가 여럿인 상품에서 여러 종목이 같은
 *  이름으로 서서, 어느 것을 고르는지 화면이 못 말합니다. */
export function expiryLabel(expiry: string): string {
  const digits = expiry.replace(/\D/g, '')
  const year = digits.slice(2, 4)
  const month = Number(digits.slice(4, 6))
  if (digits.length >= 8) {
    const day = Number(digits.slice(6, 8))
    return `${year}년 ${month}월 ${day}일`
  }
  return `${year}년 ${month}월물`
}

/** 만기를 표에 적는 모양. 라벨과 달리 **자릿수를 그대로 보이는 자리**입니다 —
 *  같은 열에서 위아래를 견주는 값이라 「26년 9월물」보다 「2026-09」가 낫습니다. */
export function expiryText(expiry: string): string {
  const digits = expiry.replace(/\D/g, '')
  if (digits.length >= 8) return `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6, 8)}`
  return `${digits.slice(0, 4)}-${digits.slice(4, 6)}`
}

/** 만기 셀렉트에 서는 한 줄. **부르는 쪽이 완성해서 넘깁니다.**
 *
 *  잔존일수가 있는 시장과 없는 시장이 있습니다. 여기서 문장을 끝내 두면 헤더가
 *  「값이 없으면 어떻게 할지」를 몰라도 되고 시장도 몰라도 됩니다 —
 *  **자리를 만들지 않는 것과 자리를 비우는 것은 다릅니다.** */
export function expiryOption(item: ContractRef): { code: string; label: string } {
  return {
    code: item.code,
    label: item.daysLeft === null ? item.label : `${item.label} · D-${item.daysLeft}`,
  }
}

/** 행사가를 적는 소수 자리 수. **행사가 축이 답합니다** — 체인 표의 행사가 열,
 *  헤더의 행사가 선택, 종목 이름이 같은 자리 수로 서야 세 자리가 같은 종목을
 *  가리키는 것이 보입니다.
 *
 *  품목의 값 자리 수로 어림하지 않습니다. 어림하면 반 칸씩 놓인 행사가(1.1525)가
 *  「1.2」로 적히고, **그 글자가 다시 숫자로 읽히는 자리에서는 아예 다른 계약이
 *  열립니다.** 자리 수는 그 체인이 실제로 쓰는 행사가들에서 셉니다.
 *
 *  자리 수를 여섯에서 끊는 것은, 거래소가 그보다 잘게 나눈 행사가를 쓰지 않는데
 *  소수 계산에서 떨어져 나온 꼬리(0.30000000000000004)는 끝없이 길어지기 때문입니다. */
const STRIKE_DECIMALS_MAX = 6

export function strikeDecimalsOf(strikes: readonly number[]): number {
  let most = 0
  for (const strike of strikes) {
    if (!Number.isFinite(strike)) continue
    const text = String(strike)
    const dot = text.indexOf('.')
    /* 지수 표기(1e-7)는 행사가에 안 나오는 모양이라 세지 않습니다. */
    if (dot < 0 || text.includes('e')) continue
    most = Math.max(most, Math.min(text.length - dot - 1, STRIKE_DECIMALS_MAX))
  }
  return most
}

/* ── 색인 ──────────────────────────────────────────────── */

interface Built {
  source: MasterIndex
  products: Map<string, Product>
  byMarket: Record<Market, Product[]>
  instruments: Map<string, Instrument>
  contracts: Map<string, ContractRef[]>
  /** 품목 → 검색이 보는 글자. 색인이 올 때 한 번 지어 둡니다. */
  search: Map<Product, string>
  /** 국내 옵션 종목코드 → 품목·만기·콜풋. 코드 규칙으로 안 풀리는 위클리 때문에
   *  마스터가 따로 주는 표입니다. */
  domesticOptions: Map<string, { product: string; expiry: string; side: 'call' | 'put' }>
}

let built: Built | null = null

/** 옵션 체인이 알려 준 옵션 종목코드 → 품목·만기·콜풋·행사가.
 *
 *  **행사가는 체인만 압니다.** 해외 옵션은 마스터에 종목 행 자체가 없고, 국내 옵션은
 *  행이 있어도 품목·만기·콜풋까지라 행사가 칸이 없습니다. 그 코드를 `resolve` 가 못
 *  풀면 조회 길이 시장을 모르는 채로 나가(국내 길로) 값이 안 오고, 행사가를 모르면
 *  이미 고른 종목을 화면이 다시 물어봅니다. 체인이 오면 여기에 적어 두어 그 뒤로는
 *  마스터 행처럼 풉니다. 환경이 바뀌어도 지우지 않습니다 — 종목의 신원이지 값이
 *  아닙니다.
 *
 *  **칸마다 자리가 하나씩입니다** — 국내에서 품목·만기·콜풋은 마스터 신원표가 답하고
 *  여기서는 행사가만 가져다 씁니다. 두 표가 같은 칸을 답하면 어긋날 때 어느 쪽이
 *  맞는지 알 수 없습니다. */
const chainLegs = new Map<
  string,
  {
    productCode: string
    expiry: string
    side: 'call' | 'put'
    strike: number
    /** 그 체인의 행사가 축이 쓰는 소수 자리 수. 이름을 지을 때 씁니다 — 줄마다
     *  다시 세면 같은 체인의 종목들이 저마다 다른 자리 수로 적힙니다. */
    decimals: number
  }
>()

/** 체인 답의 종목들을 신원표에 적습니다. 체인을 받은 자리(`data/optionChain.ts`)가
 *  부릅니다. */
export function registerChainLegs(
  productCode: string,
  expiry: string,
  legs: readonly { code: string; side: 'call' | 'put'; strike: number }[],
): void {
  /* 자리 수는 **체인 하나에 한 번** 셉니다. */
  const decimals = strikeDecimalsOf(legs.map((leg) => leg.strike))
  for (const leg of legs) {
    if (!leg.code) continue
    chainLegs.set(leg.code, {
      productCode,
      expiry,
      side: leg.side,
      strike: leg.strike,
      decimals,
    })
  }
}

/** 품목 줄을 화면이 쓰는 모양으로. **축 이름은 마스터가 안 주므로 코드 그대로**
 *  둡니다 — 뜻을 지어 붙이면 마스터가 바뀔 때 화면만 옛 이름을 답니다. */
function toProduct(row: MasterProduct): Product {
  return {
    code: row.product_code,
    name: row.product_name,
    kinds: kindsOfProduct(row),
    /* 국내에는 거래소 축이 없습니다 — 마스터가 안 주므로 줄을 안 세웁니다. */
    exchange: exchangeOfProduct(row),
    exchangeCode: row.market === 'overseas' && row.ExchName ? String(row.ExchName) : null,
    exchangeNo: row.market === 'overseas' && row.exch ? String(row.exch) : null,
    group: groupOfProduct(row),
    /* 색인이 정해 실어 줍니다. 색인에 이 칸이 없으면 월물로
       봅니다 — 날짜를 못 받은 채 날 단위로 부르면 빈 자리가 생깁니다. */
    expiryUnit: row.expiry_unit === 'day' ? 'day' : 'month',
    groupOrder: axisOrder(
      'group',
      row.market,
      (row.market === 'overseas' ? row.sect : row.mrkt_code) ?? '',
    ),
    decimals: decimalsOfProduct(row),
    /* 마스터가 시장마다 다른 것을 줍니다 — 국내는 거래승수, 해외는 호가단위.
       없는 쪽을 지어내지 않습니다. */
    multiplier: numberOrNull(row.ctrt_size),
    tickSize: numberOrNull(row.tsiz),
    tickDecimals: tickDecimals(row.tsiz),
    /* 국내 거래대상코드. 옵션 체인 조회가 품목을 이 값으로 부릅니다. */
    tradeCode: row.trd_code ? String(row.trd_code) : null,
    /* 가격표시방법이 글자면 분수로 적는 품목입니다. 값은 같고 적는 방식만
       다릅니다 — 국채·곡물이 거래소에서 그렇게 불립니다. */
    fraction: fractionOfProduct(row.pind as string | undefined),
  }
}

function numberOrNull(value: string | undefined): number | null {
  if (value == null || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

/* 스프레드 한 줄에 서는 이름.
 *
 * 스프레드는 만기가 둘이라 「26년 9월물」로는 어느 종목인지 못 말합니다.
 * 두 만기를 다 적어야 하는데, **어디서 가져오는지가 시장마다 다릅니다.**
 *
 * 국내 마스터는 이름 칸에 두 만기를 이미 적어 주므로(「코스피200 SP
 * 2609-2612」) 그 원문을 그대로 씁니다. 해외 마스터는 이름 칸에 만기가 없고
 * (「유로화 스프레드」) 두 만기가 따로 오므로 여기서 붙입니다.
 *
 * **가까운 만기를 앞에 둡니다.** 국내 원문이 가까운 쪽부터 적혀 있어, 해외를
 * 마스터 필드 순서대로 붙이면 두 시장이 반대 차례가 됩니다 — 오가는 사람이
 * 어느 쪽이 근월인지 매번 다시 봐야 합니다. 국내 이름은 원문이라 못 바꾸고
 * **해외 이름은 이 앱이 짓는 것**이라, 고칠 수 있는 쪽을 고칩니다. 어느 필드가
 * 가까운 쪽인지는 재지 않고 **두 값을 견줘서** 정합니다. */
function spreadLabel(row: MasterContract, market: Market): string {
  const legs = legsOf(row)
  if (legs) return `${expiryLabel(legs.near)} – ${expiryLabel(legs.far)}`
  /* 색인이 다리를 안 주면 원문 이름과 만기 칸으로 짓습니다. */
  if (market === 'domestic') return String(row.name_kor ?? '')
  const far = String(row.yymm1 ?? '')
  if (far === '') return expiryLabel(row.expiry)
  const [near, later] = row.expiry <= far ? [row.expiry, far] : [far, row.expiry]
  return `${expiryLabel(near)} – ${expiryLabel(later)}`
}

/** 색인 줄에 실린 다리 만기. **두 칸이 다 있어야 씁니다** — 한쪽만으로는
 *  스프레드를 말할 수 없습니다. */
function legsOf(row: MasterContract): MasterLegs | null {
  const legs = row.legs as MasterLegs | null | undefined
  if (!legs || typeof legs !== 'object') return null
  const near = String(legs.near ?? '')
  const far = String(legs.far ?? '')
  if (near === '' || far === '') return null
  const dateOf = (value: unknown) => (typeof value === 'string' && value ? value : null)
  return { near, far, nearDate: dateOf(legs.nearDate), farDate: dateOf(legs.farDate) }
}

/** 스프레드를 세우는 차례 — 근월이 먼저이고, 근월이 같으면 원월이 가릅니다. */
function legsOrder(ref: ContractRef): number {
  const near = Number(ref.legs?.near ?? ref.expiry) || 0
  const far = Number(ref.legs?.far ?? ref.expiry) || 0
  return near * 1_000_000 + far
}

/** 한 품목의 종목 목록에서 **스프레드만** 근월·원월 순으로 다시 세웁니다.
 *  자리에서 고칩니다.
 *
 *  색인이 실어 준 차례가 품목마다 제각각이라(지금 색인에서 해외 13 품목이
 *  뒤섞여 옵니다) 그대로 두면 목록 첫 줄이 가장 가까운 만기가 아니고, 비워 두고
 *  열 때 서는 줄도 품목마다 달라집니다.
 *
 *  **다른 종류는 자리가 그대로입니다.** 뽑아서 정렬한 뒤 뽑아 온 자리에 도로
 *  넣으므로, 스프레드가 목록 어디에 흩어져 있어도 나머지 줄은 안 움직입니다 —
 *  비교자 하나로 「종류가 다르면 0」을 답하면 그 답이 한결같지 않아(추이성이
 *  깨져) 결과가 정렬 구현과 들어온 차례에 달립니다.
 *
 *  **목록 차례를 정하는 자리가 여기 하나**라 밖에서도 그대로 불러 볼 수 있게
 *  열어 둡니다 — 쓰는 곳은 아래 색인 만들기 한 군데이고, 공개는 시험용입니다. */
export function sortSpreads(list: ContractRef[]): void {
  const seats: number[] = []
  const spreads: ContractRef[] = []
  list.forEach((ref, index) => {
    if (ref.kind !== 'spread') return
    seats.push(index)
    spreads.push(ref)
  })
  if (spreads.length < 2) return
  spreads.sort((a, b) => legsOrder(a) - legsOrder(b))
  seats.forEach((seat, at) => {
    list[seat] = spreads[at]
  })
}

/** 헤더 제목 아래 서는 다리 한 줄 — 「26년 12월물 ↔ 27년 3월물」.
 *
 *  **목록의 「–」와 다른 글자를 씁니다.** 목록은 한 줄에 여럿이 서는 자리라
 *  줄표가 조용하고, 제목 아래는 두 다리가 맞물린 하나임을 말하는 자리입니다. */
export function spreadLegsLine(legs: MasterLegs): string {
  return `${expiryLabel(legs.near)} ↔ ${expiryLabel(legs.far)}`
}

/** 홈 타일처럼 **글자 폭이 정해진 자리**에 서는 짧은 이름 —
 *  「코스피200 SP 12월↔3월」. 타일은 한 줄이라 연도까지 적으면 이름이 잘립니다.
 *
 *  **품목 이름이 이미 스프레드라고 말하면 「SP」를 안 붙입니다** — 지금 색인의
 *  해외 스프레드 품목은 이름 끝이 전부 「스프레드」라 붙이면 한 줄이 같은 것을
 *  두 번 말합니다(「유로화 스프레드 SP 12월↔3월」). 이름에 그 말이 없는 품목이
 *  실려 오면 「SP」가 그 자리를 대신합니다. */
export function spreadShortName(productName: string, legs: MasterLegs): string {
  const month = (expiry: string) => `${Number(expiry.slice(4, 6))}월`
  const mark = productName.includes('스프레드') ? '' : 'SP '
  return `${productName} ${mark}${month(legs.near)}↔${month(legs.far)}`
}

function refOf(row: MasterContract, market: Market): ContractRef {
  const code = String(row.code ?? row.series ?? '')
  /* 잔존일수는 국내 마스터가 종목마다 실어 줍니다. **스프레드 줄에도 값이
     들어 있고 그대로 세웁니다** — 두 다리 중 어느 쪽 기준인지는 마스터가
     말해 주지 않지만, 마스터가 준 값을 화면이 고쳐 적지는 않습니다. */
  const days = market === 'domestic' ? Number(row.rem_cnt) : Number.NaN
  return {
    code,
    /* **색인이 준 만기를 그 단위대로** 적습니다. 지금 색인은 월까지 주므로
       「26년 9월물」이 서고, 날까지 주게 되면 같은 함수가 「26년 9월 3일」을
       냅니다 — 원문 행에는 날짜가 있지만 색인이 고른 단위를 화면이 앞질러
       가지 않습니다. */
    label: row.kind === 'spread' ? spreadLabel(row, market) : expiryLabel(row.expiry),
    masterName: String(row.name_kor ?? row.name ?? ''),
    kind: row.kind,
    expiry: row.expiry,
    /* 해외 선물 계약 행에 실려 오는 `lmon`(1 = 거래량 최다월물)입니다. 옵션·
       스프레드 행과 국내 행에는 없으므로 그 자리는 `false` 가 됩니다. */
    main: String(row.lmon ?? '') === '1',
    expiryDate: typeof row.expiry_date === 'string' && row.expiry_date ? row.expiry_date : null,
    daysLeft: Number.isFinite(days) ? days : null,
    /* 시리즈 코드는 옵션 만기 줄에만 있습니다 — 선물·스프레드는 종목
       코드가 곧 그 자리입니다. */
    seriesCode: null,
    legs: row.kind === 'spread' ? legsOf(row) : null,
    tickValue: market === 'overseas' ? numberOrNull(row.tval as string | undefined) : null,
  }
}

function build(source: MasterIndex): Built {
  const products = new Map<string, Product>()
  const byMarket: Record<Market, Product[]> = { domestic: [], overseas: [] }
  const instruments = new Map<string, Instrument>()
  const contracts = new Map<string, ContractRef[]>()
  const domesticOptions = new Map<string, { product: string; expiry: string; side: 'call' | 'put' }>()

/* 축을 세우는 순서는 셋 다 같습니다 — **마스터 규격이 값을 나열한 순서**,
   나열이 없는 자리(품목 이름)는 이름순, 규격에 없는 값은 맨 뒤.
   색인에 실린 순서(마스터 파일 순서)에는 뜻이 없습니다.

   이름 안의 숫자는 숫자로 셉니다 — 글자로만 세우면 「3년국채」가 「10년국채」
   뒤로 갑니다. */
  /* 어느 달이든 만기를 둘 이상 가진 옵션 품목. **만기 이름을 날까지 적어야
     하는 품목**입니다 — 같은 달에 여럿이면 월물 이름으로는 어느 것을 고르는지
     화면이 못 말합니다.

     **달이 아니라 품목으로 재는 이유**는, 달로 재면 그 달에 한 줄만 남는 날
     같은 종목이 어제와 다른 이름으로 불리기 때문입니다. 이름은 종목의 성질이지
     그날 몇 줄이 서 있느냐가 아닙니다. */
  const crowdedProducts = new Set<string>()
  const seenMonths = new Set<string>()
  for (const row of source.option_expiries) {
    const at = row.market + '|' + row.product_code
    const month = at + '|' + row.expiry
    if (seenMonths.has(month)) crowdedProducts.add(at)
    else seenMonths.add(month)
  }

  const byName = new Intl.Collator('ko', { numeric: true })
  const ordered = [...source.products].sort(
    (a, b) =>
      axisOrder('exchange', a.market, a.exch ?? '') -
        axisOrder('exchange', b.market, b.exch ?? '') ||
      axisOrder('group', a.market, (a.market === 'overseas' ? a.sect : a.mrkt_code) ?? '') -
        axisOrder('group', b.market, (b.market === 'overseas' ? b.sect : b.mrkt_code) ?? '') ||
      byName.compare(a.product_name, b.product_name),
  )
  for (const row of ordered) {
    const product = toProduct(row)
    /* 색인은 품목 이름으로 단위를 정합니다. 이름에 주간 표식이 없는 품목은
       실린 만기 줄이 대신 말해 줍니다 — 이름보다 줄이 먼저입니다. */
    if (crowdedProducts.has(row.market + '|' + row.product_code)) product.expiryUnit = 'day'
    products.set(row.market + '|' + row.product_code, product)
    byMarket[row.market].push(product)
  }

  /* 선물·스프레드는 종목 행이 다 실려 오므로 미리 펼쳐 둡니다. 옵션은 행사가
     만큼 종목이 늘어나 색인에 안 실리고, 만기까지만 옵니다. */
  for (const row of source.contracts) {
    const product = products.get(row.market + '|' + row.product_code)
    if (!product) continue
    const ref = refOf(row, row.market)
    const list = contracts.get(row.market + '|' + row.product_code)
    if (list) list.push(ref)
    else contracts.set(row.market + '|' + row.product_code, [ref])
    /* 화면에 세우는 이름은 **품목 이름 + 종목 이름**으로 짓습니다. 마스터
       원문은 코드에 가까운 표기라(「코스피200 F 202609」) 사람이 읽는 자리에
       그대로 세우지 않습니다 — 원문은 `masterName` 에 남아 검색이 보고,
       헤더 제목이 스프레드에서 그것을 그대로 세웁니다. */
    instruments.set(ref.code, {
      product,
      market: row.market,
      kind: row.kind,
      contract: ref,
      leg: null,
      /* 이름이 이미 마스터 원문이면(색인이 다리를 안 준 국내 스프레드) 품목
         이름을 앞에 또 붙이지 않습니다 — 원문에 품목 이름이 들어 있어
         「코스피200 코스피200 SP 2612-2703」이 됩니다. */
      name:
        ref.kind === 'spread' && ref.label === ref.masterName
          ? ref.label
          : `${product.name} ${ref.label}`,
    })
  }

  for (const row of source.option_expiries) {
    const key = row.market + '|' + row.product_code
    const product = products.get(key)
    if (!product) continue
    /* **만기를 가르는 것은 날짜이고, 부르는 이름은 품목의 단위가 정합니다.**
       둘을 같은 값에서 뽑으면 한쪽이 틀립니다 — 날짜로 이름을 지으면 월물이
       「26년 9월 10일」이 되고, 월로 가르면 한 달에 여럿인 만기가 한 칸으로
       뭉칩니다. */
    const identity = row.expiry_date ?? row.expiry
    const shown = product.expiryUnit === 'day' ? identity : row.expiry
    const ref: ContractRef = {
      code: optionExpiryCode(row.product_code, identity),
      label: expiryLabel(shown),
      /* 옵션 만기 줄에는 이름이 없습니다 — 종목 이름은 행사가까지 정해져야
         생기고, 그건 체인이 답합니다. */
      masterName: '',
      kind: 'option',
      expiry: identity,
      /* 옵션 만기 줄은 색인이 날짜를 만기로 줍니다 — 여덟 자리면 그것이
         곧 최종거래일이고, 월까지만 아는 품목에서는 없습니다. */
      expiryDate: identity.length >= 8 ? identity : null,
      /* 옵션 만기 줄에는 주력 표시가 없습니다 — 마스터가 선물·스프레드에만
         답니다. */
      main: false,
      tickValue: null,
      /* 잔존일수는 색인이 만기마다 실어 줍니다. **0 과 없음은 다릅니다** — 0 은
         「오늘 만기」라 「D-0」이 서야 하고, 없음은 답이 없어 그 자리를 만들지
         않습니다. 없는 것을 0 으로 바꾸면 화면이 오늘 만기라고 거짓말합니다.
         마스터가 줄마다 주는 시장이 먼저고, 안 주는 시장은 색인이 만기일로 센
         값입니다. */
      daysLeft: row.rem_cnt ?? row.days_left ?? null,
      /* 체인을 부를 때 보낼 시리즈 코드. 색인이 안 주면 비워 두고, 부르는
         쪽이 만기년월로 짓습니다. */
      seriesCode: typeof row.series_code === 'string' && row.series_code ? row.series_code : null,
      legs: null,
    }
    const list = contracts.get(key)
    if (list) list.push(ref)
    else contracts.set(key, [ref])
  }

  for (const list of contracts.values()) sortSpreads(list)

  const fields = source.domestic_option_index.fields
  const at = {
    series: fields.indexOf('series'),
    product: fields.indexOf('product_code'),
    /* **신원표의 만기는 8자리입니다.** 이 표가 답하는 것은 「이 코드가 무엇인가」
       이고, 위클리는 한 달에 만기가 여럿이라 월로는 서로 다른 종목이 같은 신원을
       갖습니다. 만기 목록의 `expiry` 와 같은 값이라 그대로 맞물립니다.
       **8자리 칸이 없으면 월 칸을 씁니다** — 색인이 화면보다 오래된 판본이면 칸을
       못 찾아 `-1` 로 읽고, 그러면 만기가 통째로 빈 값이 되어 이름을 짓다 멈춥니다.
       그때는 위클리를 못 가를 뿐 나머지는 그대로 섭니다. */
    expiry:
      fields.indexOf('expiry_date') >= 0
        ? fields.indexOf('expiry_date')
        : fields.indexOf('expiry'),
    side: fields.indexOf('opt_tp'),
  }
  for (const row of source.domestic_option_index.rows) {
    domesticOptions.set(row[at.series], {
      product: row[at.product],
      expiry: row[at.expiry],
      side: row[at.side] === PUT ? 'put' : 'call',
    })
  }

  /* 검색이 보는 글자를 미리 이어 둡니다. 품목 이름과 코드에 더해 **마스터가
     실어 준 종목 이름 원문**까지 넣습니다 — 화면에는 이 앱이 지은 이름이 서지만,
     마스터에 적힌 대로 친 사람도 찾을 수 있어야 합니다. */
  const search = new Map<Product, string>()
  for (const [key, product] of products) {
    const names = (contracts.get(key) ?? []).map((item) => item.masterName)
    search.set(product, [product.name, product.code, ...names].join(' ').toLowerCase())
  }

  return { source, products, byMarket, instruments, contracts, search, domesticOptions }
}

/** 색인 위에 지어 둔 것. 색인이 새로 오면 다시 짓습니다. */
function maps(): Built | null {
  const source = masterIndex()
  if (!source) return null
  if (!built || built.source !== source) built = build(source)
  return built
}

/* ── 찾기 ──────────────────────────────────────────────── */

/** 그 시장의 품목 전부. **색인에 실린 것뿐입니다.** */
export function productsOf(market: Market): Product[] {
  return maps()?.byMarket[market] ?? []
}

/** 검색이 훑을 글자. 품목 이름·코드에 마스터의 종목 이름 원문까지 들어 있고,
 *  **모두 소문자**입니다 — 부르는 쪽도 소문자로 맞춰 견줍니다. */
export function searchTextOf(product: Product): string {
  return maps()?.search.get(product) ?? ''
}

/** 품목 코드로 품목을 찾습니다. 같은 코드가 두 시장에 있을 수 있어 시장이 함께 듭니다. */
export function productOf(market: Market, code: string): Product | null {
  return maps()?.products.get(market + '|' + code) ?? null
}

/* 행사가를 아직 안 고른 옵션. 품목과 만기까지는 정해졌고 행사가만 남은 상태인데,
 * 그걸 코드 하나로 적어 두어야 화면이 「무엇을 보고 있나」를 코드에서만 읽습니다.
 * 이 상태로 열면 체인이 서고, 거기서 고른 칸이 진짜 종목코드가 됩니다.
 *
 * **사용자에게 보이는 값이 아닙니다.** 화면에는 「행사가 선택」이 섭니다. */
const OPTION_EXPIRY_CODE = /^([0-9A-Z_]+):(\d{6,8})$/

export function optionExpiryCode(productCode: string, expiry: string): string {
  return `${productCode}:${expiry}`
}

/** 종목 코드를 종목으로 풉니다. 모르는 코드는 `null` 입니다.
 *
 *  `null` 이 되는 경우 — 색인에 없는 코드, 그리고 **색인을 아직 못 받은 때**.
 *  둘을 화면에서 갈라야 하면 마스터 상태를 함께 보세요. */
export function resolve(code: string): Instrument | null {
  const found = maps()
  if (!found) return null

  const known = found.instruments.get(code)
  if (known) return known

  /* 만기 하나를 그 품목의 만기 목록에서 되찾습니다. 목록이 이미 단위대로 이름을
     짓고 잔존일수를 달아 두었으므로, 여기서 다시 짓지 않고 그 줄을 씁니다 —
     두 곳에서 지으면 한 곳만 고쳐지는 자리가 생깁니다. */
  const expiryRef = (market: Market, product: Product, expiry: string) =>
    (found.contracts.get(market + '|' + product.code) ?? []).find(
      (item) => item.kind === 'option' && item.expiry === expiry,
    ) ?? null

  const waiting = OPTION_EXPIRY_CODE.exec(code)
  if (waiting) {
    for (const market of ['domestic', 'overseas'] as const) {
      const product = found.products.get(market + '|' + waiting[1])
      if (!product || !product.kinds.includes('option')) continue
      return {
        product,
        market,
        kind: 'option',
        contract: {
          code,
          label: expiryRef(market, product, waiting[2])?.label ?? expiryLabel(waiting[2]),
          masterName: '',
          kind: 'option',
          /* 코드에 든 만기가 날까지면 그것이 곧 최종거래일입니다(국내). 월까지만
             아는 시장에서는 없습니다. */
          expiryDate: waiting[2].length >= 8 ? waiting[2] : null,
          /* 주력 표시는 선물·스프레드에만 옵니다. */
          main: false,
          expiry: waiting[2],
          daysLeft: expiryRef(market, product, waiting[2])?.daysLeft ?? null,
          seriesCode: expiryRef(market, product, waiting[2])?.seriesCode ?? null,
          legs: null,
          tickValue: null,
        },
        leg: null,
        name: product.name,
      }
    }
    return null
  }

  /* 국내 옵션 종목코드. 코드 규칙으로는 안 풀리고(위클리가 주차 표기라 만기월
     규칙을 안 따릅니다) 마스터가 주는 신원표로 찾습니다.
     **행사가와 종목명은 이 표에 없습니다** — 체인을 열면 따라옵니다. */
  const option = found.domesticOptions.get(code)
  if (option) {
    const product = found.products.get('domestic|' + option.product)
    if (!product) return null
    /* **행사가만** 체인 신원표에서 가져옵니다. 품목·만기·콜풋은 마스터 신원표가
       답하는 칸이라 여기서 다시 읽지 않습니다 — 한 칸을 두 표가 답하면 어긋날 때
       어느 쪽이 맞는지 알 수 없습니다. 체인을 아직 안 연 코드는 행사가를 알 길이
       없어 `leg` 가 비지만, **코드는 그대로 거래소에 상장된 계약**이라 조회도
       주문도 막히지 않습니다(`needsLeg`). */
    const fromChain = chainLegs.get(code)
    return {
      product,
      market: 'domestic',
      kind: 'option',
      contract: {
        code,
        /* 이름과 잔존일수는 그 품목의 만기 목록이 이미 짓습니다 — 신원표는
           만기를 8자리로만 주므로, 여기서 지으면 월물이 「26년 9월 10일」이 됩니다. */
        label: expiryRef('domestic', product, option.expiry)?.label ?? expiryLabel(option.expiry),
        masterName: '',
        kind: 'option',
        main: false,
        expiry: option.expiry,
        /* 신원표의 만기는 여덟 자리(날짜)라 그것이 곧 최종거래일입니다. */
        expiryDate: option.expiry.length >= 8 ? option.expiry : null,
        daysLeft: expiryRef('domestic', product, option.expiry)?.daysLeft ?? null,
        seriesCode: expiryRef('domestic', product, option.expiry)?.seriesCode ?? null,
        legs: null,
        tickValue: null,
      },
      leg: fromChain ? { side: option.side, strike: fromChain.strike } : null,
      side: option.side,
      /* 행사가를 알면 이름에도 답니다 — 같은 만기의 콜이 행사가마다 여럿이라,
         품목 이름만으로는 잔고·주문 내역에서 어느 줄인지 못 가립니다. */
      name: fromChain
        ? `${product.name} ${option.side === 'call' ? '콜' : '풋'} ${fromChain.strike.toFixed(fromChain.decimals)}`
        : product.name,
    }
  }

  /* 체인이 알려 준 옵션 종목. 마스터에 행이 없는 해외 옵션이 이 길로 풀립니다 —
     시장과 품목을 알아야 조회가 그 시장의 길로 나갑니다. 콜풋·행사가까지 코드가
     말하므로 축이 다 정해진 채로 섭니다. */
  const chainLeg = chainLegs.get(code)
  if (chainLeg) {
    const product = found.products.get('overseas|' + chainLeg.productCode)
    if (product) {
      const ref = expiryRef('overseas', product, chainLeg.expiry)
      return {
        product,
        market: 'overseas',
        kind: 'option',
        contract: {
          code,
          label: ref?.label ?? expiryLabel(chainLeg.expiry),
          masterName: '',
          kind: 'option',
          /* 만기 줄이 날짜까지 알면 그것이 곧 최종거래일입니다. */
          expiryDate: ref?.expiryDate ?? null,
          main: false,
          expiry: chainLeg.expiry,
          daysLeft: ref?.daysLeft ?? null,
          seriesCode: ref?.seriesCode ?? null,
          legs: null,
          tickValue: null,
        },
        leg: { side: chainLeg.side, strike: chainLeg.strike },
        side: chainLeg.side,
        /* **콜풋과 행사가까지 붙입니다.** 이 코드는 다리 하나를 통째로 가리키는데
           이름이 품목까지면 같은 행사가의 콜과 풋이 한 이름으로 서서, 잔고·주문
           내역·관심종목에서 어느 쪽인지 이름으로 못 가립니다. */
        name: `${product.name} ${chainLeg.side === 'call' ? '콜' : '풋'} ${chainLeg.strike.toFixed(chainLeg.decimals)}`,
      }
    }
  }

  return null
}

/** 아직 안 고른 축을 가리키는 말. **한 벌만 둡니다** — 헤더·차트 배지·주문
 *  단추가 같은 상태를 다른 낱말로 부르면 사용자가 서로 다른 일로 읽습니다. */
export const PENDING_TEXT = {
  strike: { pick: '행사가 선택', ask: '행사가를 고르세요' },
  side: { pick: '콜/풋 선택', ask: '콜/풋을 고르세요' },
} as const

/** 축이 덜 정해진 옵션인가 — **아직 계약이 아닌 코드**인가입니다.
 *
 *  이 상태의 코드(`품목:만기`)는 **이 앱의 자료구조이지 거래소의 것이 아닙니다.** 코드가
 *  서는 자리(최근 본·검색·카탈로그)는 코드 대신 「행사가 선택」을 보이고, 헤더는 값
 *  칸이라 「—」를 세웁니다 — 둘 다 정해지면 진짜 종목코드가 생깁니다. **이 코드로는
 *  조회를 내지 않습니다**: 서버가 모르는 종목이라 거절로 돌아옵니다.
 *
 *  **「행사가를 아직 모른다」와는 다릅니다.** 국내 옵션 종목코드는 거래소에 상장된
 *  계약인데 마스터 신원표에 행사가 칸이 없어, 체인을 열기 전에는 행사가를 모른 채로
 *  섭니다. 그것까지 여기서 참으로 답하면 사용자가 이미 고른 종목을 화면이 다시
 *  물어보고, 조회·담기·주문이 함께 막힙니다. */
export function needsLeg(code: string): boolean {
  return OPTION_EXPIRY_CODE.test(code)
}

/** 이 품목에 상장된 종류. 「품목의 성질」이 아니라 **무엇이 실려 있나**입니다.
 *
 *  한 품목이 선물·옵션·스프레드를 함께 갖는 경우가 있어, 종류는 품목에서
 *  파생되는 값이 아니라 품목이 가진 **목록**입니다. */
export function kindsOf(product: Product): ProductKind[] {
  return product.kinds
}

/** 품목에 상장된 종목. **종류를 함께 받습니다.**
 *
 *  한 품목이 선물·옵션·스프레드를 함께 갖는 경우가 흔해서(국내는 대부분이
 *  그렇습니다) 종류를 안 받으면 세 종류가 한 목록에 섞여 나옵니다 — 선물을
 *  보고 있는데 표에 스프레드가 끼는 식입니다. */
export function contractsOf(product: Product, kind: ProductKind): ContractRef[] {
  const found = maps()
  if (!found) return []
  for (const market of ['domestic', 'overseas'] as const) {
    const list = found.contracts.get(market + '|' + product.code)
    if (list) return list.filter((item) => item.kind === kind)
  }
  return []
}

/** 화면에 적는 단위로 맞춘 호가단위.
 *
 *  **분수로 부르는 품목에서 단위가 갈립니다.** 곡물은 값을 센트로 부르는데
 *  (`437'5`) 호가단위는 달러로 실려 옵니다(`0.0025` = 0.25센트). 실린 값을 그대로
 *  쓰면 한 단이 화면의 가장 잔 눈금(1/8)보다도 잘아, 호가 사다리 열 줄이 전부
 *  같은 값으로 보입니다. 분모로 세어 한 눈금도 안 되면 센트로 환산합니다.
 *
 *  **국채처럼 단위가 이미 맞는 품목은 실린 값 그대로입니다** — 미국 30년 국채는
 *  `0.03125` 가 곧 1/32 입니다. */
export function displayTickOf(product: Product): number | null {
  const tick = product.tickSize
  if (tick == null || tick <= 0) return null
  const denominator = product.fraction
  if (!denominator || Math.round(tick * denominator) >= 1) return tick
  const cents = tick * 100
  return Math.round(cents * denominator) >= 1 ? cents : tick
}

/** 품목이 선 시장. */
export function marketOf(product: Product): Market {
  const found = maps()
  if (found?.byMarket.overseas.includes(product)) return 'overseas'
  return 'domestic'
}

/** 그 품목을 **비워 두고 열 때** 세울 종목. 마스터가 주력으로 표시한 월물이
 *  있으면 그것이고, 없으면 만기가 가장 가까운 것입니다.
 *
 *  **「최근 만기」 배지와 다른 축입니다.** 배지는 만기 사실을 말하고 이 함수는
 *  「무엇부터 보여 줄까」를 답합니다 — 근월이 한산하고 분기물에 거래가 실리는
 *  해외 상품에서는 둘이 갈리고, 그때 거래가 실린 쪽을 엽니다. 국내 마스터에는
 *  그 축이 없어 두 값이 늘 같습니다. */
export function defaultContractOf(product: Product, kind: ProductKind): ContractRef | null {
  const list = contractsOf(product, kind)
  return list.find((item) => item.main) ?? list[0] ?? null
}

/** 만기 당일로 보는 남은 날. **서버와 같은 기준입니다**(`service.py` 의
 *  `EXPIRY_DAY`) — 엔진이 이 날 진입을 막으므로 화면도 같은 날을 피합니다. */
export const EXPIRY_DAY = 1

/** 「근월 자동」이 가리키는 월물. **만기가 가장 가까운 것**이고, 그것이 만기
 *  당일이면 다음 것입니다.
 *
 *  만기 당일을 건너뛰는 까닭: 그날은 엔진이 진입을 막습니다. 그 월물로 실행을
 *  세우면 도는 듯 보이는데 한 건도 안 나갑니다.
 *
 *  **「무엇부터 보여 줄까」와 다른 축입니다**(`defaultContractOf`). 그쪽은
 *  거래가 실린 월물을 열고, 여기는 전략이 **실제로 거래할** 월물이라 만기
 *  순입니다. 스프레드는 색인이 이미 근월-차월 차례로 세워 두어(`sortSpreads`)
 *  첫 줄이 곧 근월-차월 짝입니다.
 *
 *  **남은 날을 모르는 줄은 안 건너뜁니다** — 모른다고 못 쓰게 할 수는 없습니다.
 *  건너뛸 다음 월물이 없으면 첫 줄 그대로입니다: 없는 것을 가리키느니 서버가
 *  답하게 둡니다. */
export function frontContractOf(product: Product, kind: ProductKind): ContractRef | null {
  const list = contractsOf(product, kind)
  return list.find((item) => item.daysLeft === null || item.daysLeft > EXPIRY_DAY) ?? list[0] ?? null
}

/** 위 함수가 고른 종목의 코드. */
export function defaultContractCode(
  market: Market,
  productCode: string,
  kind: ProductKind,
): string | null {
  const product = productOf(market, productCode)
  if (!product) return null
  return defaultContractOf(product, kind)?.code ?? null
}

/* 종목을 고르지 않고 시세 화면에 들어왔을 때 세울 품목.
 *
 * **품목 하나를 적어 둡니다.** 색인의 차례로 첫 줄을 고르면 상품군 순서 때문에
 * 개별 주식 선물이나 교차 환율이 먼저 서서, 처음 여는 화면이 그 시장을 대표하지
 * 못합니다. 종목 코드가 아니라 품목 코드라 만기가 넘어가도 낡지 않고, 어느
 * 월물인지는 아래에서 마스터가 정합니다. */
const DEFAULT_PRODUCT: Record<Market, string> = {
  domestic: 'KOSPI',
  overseas: 'CL',
}

/** 그 시장을 비워 두고 열 때 세울 종목. 위 품목의 주력 월물 선물이고, 마스터에
 *  그 품목이 없으면 빈 문자열입니다 — 그때는 종목을 못 찾은 것과 같은 얼굴이
 *  섭니다. */
export function defaultInstrumentCode(market: Market): string {
  return defaultContractCode(market, DEFAULT_PRODUCT[market], 'futures') ?? ''
}

/** 그 품목의 국내 옵션 하나. 만기가 가장 가까운 것 중 고른 쪽(콜/풋) 하나입니다.
 *
 *  **행사가를 고르지 않습니다** — 색인의 옵션 대응표가 주는 첫 줄을 그대로
 *  씁니다. 어느 행사가인지는 이 자리에서 뜻이 없고, 필요한 것은 「색인에 실제로
 *  있는 옵션 종목 하나」입니다. */
/** 국내 옵션 종목의 콜·풋. 색인의 옵션 대응표가 답하고, 옵션이 아닌 코드는
 *  null 입니다. 대응표에 행사가는 없어 여기서도 나오지 않습니다. */
export function domesticOptionSide(code: string): 'call' | 'put' | null {
  return maps()?.domesticOptions.get(code)?.side ?? null
}

export function anyDomesticOptionCode(productCode: string, side: 'call' | 'put'): string | null {
  const found = maps()
  if (!found) return null
  let best: { code: string; expiry: string } | null = null
  for (const [code, row] of found.domesticOptions) {
    if (row.product !== productCode || row.side !== side) continue
    if (!best || row.expiry < best.expiry) best = { code, expiry: row.expiry }
  }
  return best?.code ?? null
}
