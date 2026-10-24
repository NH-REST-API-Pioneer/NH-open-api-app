/* 종목 마스터 색인 — 앱이 켜질 때 한 번 받아 두는 종목 목록.
 *
 * 화면에 서는 품목과 종목은 **여기 실린 것뿐**입니다. 실제로 상장되어 있어도
 * 마스터에 없으면 이 앱에는 없는 종목입니다 — 화면이 시장·상품군·품목을 미리
 * 정해 두지 않고, 색인이 주는 것을 그대로 셉니다.
 *
 * **한 번만 받습니다.** 코드 하나마다 물어보면 화면을 그리는 도중에 기다리게
 * 되고 호출도 많아집니다. 받아 둔 뒤로는 찾기만 합니다.
 *
 * **시세는 여기 없습니다.** 마스터는 어떤 종목이 상장되어 있는지만 알려 줍니다.
 * 현재가·호가는 따로 조회합니다.
 */

/** 품목 한 줄. 시장마다 실려 오는 값이 다릅니다 — 없는 칸은 그 시장에 없는 것입니다. */
export interface MasterProduct {
  market: 'domestic' | 'overseas'
  product_code: string
  product_name: string
  /** 이 품목에 실린 종목 수를 종류별로. 0이면 그 종류는 이 품목에 없습니다. */
  contract_counts: { futures: number; option: number; spread: number }
  /** 만기를 무엇으로 부르는가. `month` 면 「26년 9월물」, `day` 면 「26년 9월 3일」.
   *  위클리처럼 한 달에 만기가 여럿인 품목이 `day` 입니다. */
  expiry_unit: 'month' | 'day'

  /* 국내에만 오는 값 */
  trd_code?: string
  /** 상품 분류 코드. 뜻은 마스터가 안 주고 코드만 옵니다. */
  mrkt_code?: string
  /** 표시할 소수 자리 수. 파일 값의 자리 수가 아니라 **적을 자리 수**입니다. */
  p_dec?: string
  ctrt_size?: string

  /* 해외에만 오는 값 */
  ExchName?: string
  exch?: string
  /** 상품군 코드. 국내의 `mrkt_code` 자리이지만 값 체계가 다릅니다. */
  sect?: string
  /** 가격 표시 방법 코드. 소수 자리 수가 아닙니다. */
  pind?: string
  /** 호가단위. 해외에는 자리 수 필드가 없어 이 값에서 자리 수를 셉니다. */
  tsiz?: string
}

/** 종목 한 줄. 마스터 원문 컬럼이 그대로 실려 옵니다. */
export interface MasterContract {
  market: 'domestic' | 'overseas'
  product_code: string
  product_name: string
  kind: 'futures' | 'option' | 'spread'
  /** 만기년월 6자리 (`202609`) */
  expiry: string
  /** 스프레드 두 다리의 만기. **화면이 종목 이름을 뜯어 만기를 찾지 않도록**
   *  색인이 두 칸으로 실어 줍니다. 선물·옵션 줄에는 없습니다. */
  legs?: MasterLegs | null
  [field: string]: unknown
}

/** 스프레드 두 다리. 가까운 쪽이 `near`, 먼 쪽이 `far` 입니다.
 *  날짜(`nearDate`·`farDate`)는 주는 시장에만 있습니다. */
export interface MasterLegs {
  near: string
  far: string
  nearDate: string | null
  farDate: string | null
}

/** 옵션 품목의 만기 하나. 옵션은 종목이 행사가만큼 늘어나 여기에는 만기만 옵니다.
 *
 *  **만기를 가르는 것은 `expiry_date` 입니다.** 위클리는 한 달에 만기가 여럿이라
 *  `expiry`(월)로는 서로 다른 만기가 한 칸으로 뭉칩니다. 해외 마스터는 만기년월
 *  까지만 주므로 그 시장에서는 `expiry_date` 가 없습니다. */
export interface MasterOptionExpiry {
  market: 'domestic' | 'overseas'
  product_code: string
  /** 만기년월 6자리 (`202609`) */
  expiry: string
  /** 만기일 8자리 (`20260903`). 해외는 마스터가 날짜를 안 줘서 `null` 입니다. */
  expiry_date: string | null
  /** 잔존일수. **0 은 「오늘 만기」이고 `null` 은 답이 없는 것**이라 서로 다릅니다.
   *  국내 마스터가 줄마다 실어 주는 값입니다. */
  rem_cnt: number | null
  /** 마스터가 잔존일수를 안 주는 시장에서 서버가 만기일로 셀 값.
   *  둘 중 있는 쪽을 쓰면 됩니다. */
  days_left?: number | null
  /** 그 만기의 시리즈 코드. **체인을 부를 때 보내는 값**입니다 — 한
   *  달에 만기가 여러인 품목은 만기년월로는 질 수 없어 마스터가 답합니다. */
  series_code?: string | null
  contract_count: number
}

/** 값 칸 폭을 잡으려고 색인이 골라 보내는 행 하나. **원문 그대로**이고,
 *  그리는 것은 화면의 일입니다. */
export interface WidthCandidate {
  value: string
  sign: 'positive' | 'negative'
  /** 어느 열에서 골랐는지. 국내는 상·하한가, 해외는 전일종가입니다. */
  field: string
  /** 어느 종목에서 골랐는지. 분수로 부르는 무리는 이 종목으로 분모를 찾습니다. */
  code: string
}

/** 자릿수와 표기가 같은 종목 묶음. 이 묶음이 값 칸 하나의 폭을 정합니다. */
export interface WidthGroup {
  market: string
  decimals: number
  notation: 'decimal' | 'fraction'
  rows: number
  candidates: WidthCandidate[]
}

export interface MasterIndex {
  products: MasterProduct[]
  contracts: MasterContract[]
  option_expiries: MasterOptionExpiry[]
  /** 국내 옵션 종목의 신원표. 코드 규칙으로 안 풀리는 위클리 때문에 따로 옵니다. */
  domestic_option_index: { fields: string[]; rows: string[][] }
  folding_conflicts: { market: string; code: string; fields: string[] }[]
  /** 값 칸 폭 후보. **색인에 없을 수 있습니다** — 없으면 화면이 「가장 넓은
   *  것」으로 둡니다. */
  width_candidates?: { groups: WidthGroup[]; checks: Record<string, unknown> }
}

/** 마스터를 손에 넣기까지의 단계. **「없다」와 「못 받았다」는 다른 상태입니다.** */
export type MasterStatus = 'loading' | 'ready' | 'failed'

export interface MasterState {
  status: MasterStatus
  index: MasterIndex | null
  /** 실패했을 때 화면에 그대로 보여줄 수 있는 이유. */
  detail: string
}

let state: MasterState = { status: 'loading', index: null, detail: '' }
const listeners = new Set<() => void>()

function announce(next: MasterState): void {
  state = next
  for (const listener of listeners) listener()
}

/** 지금 상태. 화면이 그리는 도중에 부르므로 **기다리지 않습니다.** */
export function masterState(): MasterState {
  return state
}

/** 색인. 아직 못 받았으면 `null` 입니다 — 「없는 종목」과 「아직 모름」이 갈립니다. */
export function masterIndex(): MasterIndex | null {
  return state.index
}

/** 상태가 바뀌면 알려 줍니다. 화면이 「받는 중」에서 목록으로 넘어가는 자리입니다. */
export function subscribeMaster(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** 마스터를 받습니다. 앱을 켤 때 한 번, 「다시 받기」를 누를 때 다시 부릅니다.
 *
 *  받는 데 실패해도 예외를 던지지 않습니다 — 화면이 그 사실을 상태로 읽고
 *  「받지 못했습니다」와 다시 받는 길을 보여줍니다. */
export async function loadMaster(): Promise<void> {
  announce({ status: 'loading', index: null, detail: '' })
  try {
    const response = await fetch('/api/master/index')
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as { detail?: string } | null
      announce({ status: 'failed', index: null, detail: body?.detail ?? '' })
      return
    }
    announce({ status: 'ready', index: (await response.json()) as MasterIndex, detail: '' })
  } catch {
    /* 서버가 아직 안 떴거나 연결이 끊긴 경우입니다. 이유를 지어내지 않고
       「못 받았다」까지만 말합니다. */
    announce({ status: 'failed', index: null, detail: '' })
  }
}

/** 다시 받으라고 서버에 이릅니다. 받기가 끝나면 색인을 다시 읽어 옵니다.
 *
 *  서버가 받는 동안 기다리지 않고 바로 답하므로, 여기서도 기다리지 않고
 *  잠시 뒤 색인을 다시 물어봅니다. */
export async function refreshMaster(): Promise<void> {
  announce({ status: 'loading', index: null, detail: '' })
  try {
    await fetch('/api/master/refresh', { method: 'POST' })
  } catch {
    /* 다시 받기 요청 자체가 실패해도 아래에서 색인을 물어봅니다 —
       예전에 받아 둔 것이 있으면 그것으로 화면이 섭니다. */
  }
  await loadMaster()
}

/* 상품 분류 코드의 이름. **마스터 레이아웃 문서의 원문 이름**이고 화면이 묶거나
 * 줄이지 않습니다 — 「유가증권(주식)」과 「코스닥(주식)」을 「주식」으로 묶으면
 * 마스터가 가른 것을 화면이 도로 붙이는 셈입니다.
 *
 * **표에 없는 코드는 코드 그대로 섭니다.** 새 코드가 생겼을 때 이름을 지어
 * 붙이면 틀린 이름이 서지만, 코드가 서면 「이름을 아직 모른다」가 보입니다. */
const DOMESTIC_GROUP: Record<string, string> = {
  '01': '유가증권(주식)',
  '02': '코스닥증권(주식)',
  '03': '유가증권(지수)',
  '04': '코스닥증권(지수)',
  '05': '금리',
  '06': '통화',
  '07': '상품',
  '08': '축산물',
}

/* 해외 상품군. 이름이 규격에 있는 것만 적고 나머지는 코드 그대로입니다. */
const OVERSEAS_GROUP: Record<string, string> = {
  '10': '통화',
  '20': '금리',
  '30': '지수',
  '40': '농산물',
  '50': '금속',
  '60': '에너지',
  '70': 'Soft',
}

/** 품목이 선 상품군의 이름. 마스터가 코드만 주므로 표로 옮기고, **표에 없으면
 *  코드를 그대로** 씁니다. 코드도 없으면 빈 문자열이고 화면이 맨 아래 이름 없는
 *  묶음으로 세웁니다 — **마스터에 실린 품목은 하나도 빠지지 않습니다.** */
export function groupOfProduct(product: MasterProduct): string {
  if (product.market === 'domestic') {
    const code = product.mrkt_code ?? ''
    return DOMESTIC_GROUP[code] ?? code
  }
  const code = product.sect ?? ''
  return OVERSEAS_GROUP[code] ?? code
}

/* 거래소 코드의 이름. **마스터 레이아웃 문서의 표 그대로**입니다.
 *
 * **거래소 줄을 세울 때는** `ExchName` 을 쓰지 않습니다 — 그 값은 거래소와 종류가
 * 붙어 있어(선물과 옵션이 따로 옵니다) 그대로 세우면 같은 거래소가 두 줄이 되고,
 * 앞 글자를 떼는 파생은 문서 목록에 없는 거래소를 놓칩니다.
 *
 * **조회에 보내는 거래소 코드는 반대로 `ExchName` 그대로입니다**(`data/quotes.ts`
 * 의 `routeOf`, 옵션 체인). 여기 이름으로 지으면 이름과 코드가 다른 거래소에서
 * 틀린 값이 나갑니다 — 이 표는 사람이 읽는 이름이고 그 자리는 서버가 읽는
 * 코드입니다. */
const OVERSEAS_EXCHANGE: Record<string, string> = {
  '01': 'CME',
  '04': 'EUREX',
  '05': 'SGX',
  '06': 'HKE',
  '11': 'ICE',
  '15': 'CBOE',
}

/** 거래소 줄의 이름. 표에 없는 코드는 코드 그대로 섭니다. */
export function exchangeOfProduct(product: MasterProduct): string {
  if (product.market !== 'overseas') return ''
  const code = product.exch ?? ''
  return OVERSEAS_EXCHANGE[code] ?? code
}

/* 축의 줄 순서. **문서가 값을 나열한 순서**를 따릅니다 — 배포하는 쪽이 적은
 * 순서에 뜻이 있어서, 이름순으로 다시 세우면 짝지어 적은 것이 갈라집니다
 * (유가증권(주식)과 유가증권(지수) 사이에 코스닥증권이 끼는 식).
 * 문서에 없는 값은 맨 뒤입니다. */
const DOMESTIC_GROUP_ORDER = ['01', '02', '03', '04', '05', '06', '07', '08']
const OVERSEAS_GROUP_ORDER = ['10', '20', '30', '40', '50', '60', '70']
const OVERSEAS_EXCHANGE_ORDER = ['01', '04', '05', '06', '11', '15']

/** 그 축에서 이 값이 몇 번째로 서는지. 문서에 없으면 맨 뒤입니다. */
export function axisOrder(kind: 'group' | 'exchange', market: string, code: string): number {
  const order =
    kind === 'exchange'
      ? OVERSEAS_EXCHANGE_ORDER
      : market === 'overseas'
        ? OVERSEAS_GROUP_ORDER
        : DOMESTIC_GROUP_ORDER
  const at = order.indexOf(code)
  return at === -1 ? order.length : at
}

/** 한 품목에 실린 종류. 수가 0인 종류는 그 품목에 없습니다. */
export function kindsOfProduct(product: MasterProduct): ('futures' | 'option' | 'spread')[] {
  const counts = product.contract_counts
  const out: ('futures' | 'option' | 'spread')[] = []
  if (counts.futures > 0) out.push('futures')
  if (counts.option > 0) out.push('option')
  if (counts.spread > 0) out.push('spread')
  return out
}

/** 값을 적는 데 필요한 소수 자리 수.
 *
 *  **국내는 `p_dec` 하나입니다.** 마스터가 「적을 자리 수」를 직접 줍니다.
 *  들어온 값에서 세지 않습니다 — 국내 파일은 개별주식선물도 값을 소수 두
 *  자리로 싣는데(`18290.00`) `p_dec` 가 0이라 정수로 적어야 합니다.
 *
 *  **해외는 가격표시방법(`pind`)과 호가단위(`tsiz`) 중 큰 쪽입니다.** 둘이
 *  대개 같은 자리 수를 말하는데, 여섯 품목에서 호가단위가 더 잘게 옵니다
 *  (일본 엔화·엔화 스프레드·엔화 옵션·미니 일본 엔화·돈육·원당). 표시 쪽만
 *  쓰면 그 여섯은 **한 틱 올려도 화면 숫자가 안 바뀝니다** — 주문을 판단하는
 *  자리에서 값이 틀리는 것이라, 안 움직이는 0이 한두 자리 붙는 쪽을 택합니다.
 *
 *  `pind` 가 글자면 분수로 적는 상품입니다(1/32 꼴). 여기서는 소수로 두고,
 *  자리 수는 호가단위에서 셉니다.
 *
 *  품목 안에서 종목마다 갈리는 값은 품목 줄에 안 실려 옵니다. 그때는 `null`
 *  이고, 종목이 정해지지 않은 자리에서는 값을 안 적습니다. */
export function decimalsOfProduct(product: MasterProduct): number | null {
  if (product.market === 'domestic') {
    const value = Number(product.p_dec)
    return product.p_dec != null && Number.isFinite(value) ? value : null
  }
  const shown = priceDecimals(product.pind)
  const tick = tickDecimals(product.tsiz)
  if (shown === null) return tick
  if (tick === null) return shown
  return Math.max(shown, tick)
}

/** 가격표시방법이 말하는 **분수의 분모**. 글자 갈래만 답하고 숫자 갈래는
 *  `null` 입니다.
 *
 *  코드표(마스터 레이아웃 문서)가 정한 값을 그대로 옮깁니다 — A.1/2 B.1/4
 *  C.1/8 D.1/16 E.1/32 F.1/64 G.1/128 H.1/256 I.0.5/32 J.0.5/64 K.0.25/32
 *  L.0.125/32. **분모는 이 표가 정하고 호가단위(`tsiz`)는 그 분모 위의 눈금**
 *  입니다 — 같은 K 안에서도 한 눈금이 1/128 인 품목과 2/128 인 품목이 있습니다. */
export function fractionOfProduct(pind: string | undefined): number | null {
  if (pind == null) return null
  return FRACTION[pind] ?? null
}

const FRACTION: Record<string, number> = {
  A: 2,
  B: 4,
  C: 8,
  D: 16,
  E: 32,
  F: 64,
  G: 128,
  H: 256,
  /* 0.5/32 = 1/64 처럼 「32분의 몇」을 다시 나눈 갈래입니다. 분모로 펴서 적으면
     같은 축에서 셀 수 있습니다. */
  I: 64,
  J: 128,
  K: 128,
  L: 256,
}

/** 가격표시방법이 말하는 소수 자리 수. **숫자 갈래만** 답합니다 —
 *  `1` 이 0자리이고 `9` 가 8자리라 값에서 하나를 뺍니다.
 *  글자 갈래(분수)는 소수 자리로 답할 수 없어 `null` 입니다. */
export function priceDecimals(pind: string | undefined): number | null {
  if (pind == null || !/^[1-9]$/.test(pind)) return null
  return Number(pind) - 1
}

/** 호가단위를 정확히 적는 데 드는 소수 자리 수. 꼬리 0은 자리가 아닙니다. */
export function tickDecimals(tick: string | undefined): number | null {
  if (tick == null || tick === '') return null
  const dot = tick.indexOf('.')
  if (dot < 0) return 0
  const fraction = tick.slice(dot + 1).replace(/0+$/, '')
  return fraction.length
}
