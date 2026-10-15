/* 국내와 해외로 갈리는 축. 주문 API와 종목 집합이 여기서 갈립니다.
 *
 * 국내의 주간·야간은 화면에서 고르지 않습니다. 어느 세션인지는 시계가 정하고
 * 백엔드가 그에 맞는 API 를 고릅니다 — 사용자가 시간을 보고 탭을 맞추는 일이
 * 없어야 하고, 맞추지 못하면 주문이 다른 세션으로 나갑니다.
 * 여기 남은 두 값은 자료가 어느 세션에서 나왔는지를 나타냅니다. */
export type MarketContext = 'domestic-day' | 'domestic-night' | 'overseas'

/** 좌상단 페이지 탭. 설정은 탭이 아니라 톱니 아이콘으로 들어갑니다. */
export type Page = 'home' | 'instruments' | 'trade' | 'strategy' | 'account'

export type Theme = 'light' | 'dark'

/** 좌측 내비에 서는 품목. */
/** 종목의 갈래. 마스터 원문 구분(국내 `fo_tp`, 해외 `type`)을 이름만 바꾼 것입니다.
 *  스프레드를 선물에 접지 않습니다 — 만기가 둘이라 목록의 「만기 한 값」 칸에
 *  넣을 값이 없고, 목록에서 고른 것이 그대로 주문 대상이 되는 자리입니다. */
export type ProductKind = 'futures' | 'option' | 'spread'

export interface Product {
  code: string
  name: string
  /** 이 품목에 실제로 상장된 종류. 한 품목이 선물·옵션·스프레드를 함께 가질 수
   *  있어 **하나가 아니라 목록**입니다 — 「품목의 성질」이 아니라 그 품목에
   *  무엇이 실려 있나입니다. */
  kinds: ProductKind[]
  /** 거래소. 해외 마스터가 거래소별 파일로 오므로 그 축이 그대로 남습니다.
   *  국내는 KRX 하나뿐이라 고를 것이 없습니다. */
  exchange: string
  /** 해외 마스터의 거래소 코드 원문(`ExchName`). **거래소와 종류가 붙은 값**이라
   *  선물은 `FCME`, 옵션은 `OCME` 이고, 스프레드만 실린 품목도 선물 쪽 표기를
   *  씁니다(`S_6E` → `FCME`). 시세 조회 길(`data/quotes.ts` 의 `routeOf`)과 옵션
   *  체인 조회가 거래소를 이 값으로 부릅니다 — 화면에 세우는 거래소 이름
   *  (`exchange`)으로 지으면 이름과 코드가 다른 거래소에서 틀린 값이 나갑니다.
   *  국내는 `null` 입니다. */
  exchangeCode: string | null
  /** 해외 마스터의 거래소 번호(`exch` — `01` CME, `06` HKEX …). 거래시간표를 찾는
   *  열쇠의 앞 절반입니다 — 같은 품목코드가 거래소마다 따로 있습니다. 국내는
   *  `null` 입니다. */
  exchangeNo: string | null
  /** 거래소 안에서 묶는 이름 */
  group: string
  /** 만기를 무엇으로 부르는가. 위클리처럼 **한 달에 만기가 여럿인 품목**은
   *  `day` 라 「26년 9월 3일」로 서고, 그 밖에는 `month` 라 「26년 9월물」입니다.
   *
   *  마스터에 주간 표식이 없어 색인이 품목명으로 정해 실어 주고, 이름에 표식이
   *  없는 품목은 **실린 만기 줄이 대신 말합니다** — 어느 달에든 만기가 둘 이상
   *  실린 품목은 `day` 입니다. */
  expiryUnit: 'month' | 'day'
  /** 상품군이 서는 차례. 마스터 규격이 코드를 나열한 순서이고, 규격에 없는
   *  코드는 맨 뒤입니다. 거래소를 빼고 상품군만으로 묶는 자리에서 씁니다. */
  groupOrder: number
  /** 이 품목 종목들의 가격 소수 자릿수. 품목 안에서 종목마다 갈리면 마스터가
   *  품목 줄에 안 싣습니다 — 그때는 `null` 이고, 종목이 정해지지 않은 자리에서는
   *  값을 안 적습니다. */
  decimals: number | null
  /** 거래승수. 국내 마스터에만 오고 해외에는 없습니다. */
  multiplier: number | null
  /** 호가단위. 해외 마스터에만 오고 국내에는 없습니다. */
  tickSize: number | null
  /** 거래대상코드(`trd_code`). 국내 마스터에만 오고, 옵션 체인 조회가 품목을
   *  이 값으로 부릅니다(코스피200 `01`). */
  tradeCode: string | null
  /** 호가단위를 **빠짐없이 적는 데 드는** 소수 자리 수. 값을 적는 자리 수와
   *  따로 둡니다 — 호가단위가 0.0000005 인데 값은 다섯 자리로 적는 상품이 있어,
   *  값 쪽 자리 수로 호가단위를 적으면 「0.00000」, 곧 0이 됩니다. */
  tickDecimals: number | null
  /** 가격을 분수로 적는 품목의 **분모**(해외 `pind` 가 글자인 23품목).
   *  소수로 적는 품목은 `null` 입니다. */
  fraction: number | null
}

/** 종목 목록의 한 행. */
export interface ContractRow {
  code: string
  /** 품목까지 붙인 전체 이름. 미리보기와 최근 본에서 씁니다. */
  name: string
  /** 목록 행에 쓰는 짧은 이름. 품목은 화면 제목에 이미 있습니다. */
  label: string
  /** 선물·옵션·스프레드. 행마다 다는 이유는 한 품목에 세 종류가 함께
   *  실릴 수 있어서입니다. */
  kind: ProductKind
  /** 마스터가 준 만기 문자열. 월까지면 6자리, 날까지면 8자리입니다. */
  expiry: string
  /** 잔존일수. 국내 마스터(`rem_cnt`)에만 있고, 해외에는 없어 `null` 입니다. */
  daysLeft: number | null
  /** 거래승수. 국내 마스터(`ctrt_size`)에만 있습니다. */
  multiplier: number | null
  /** 호가단위. 해외 마스터(`tsiz`)에만 있습니다. */
  tickSize: number | null
  /** 호가단위를 빠짐없이 적는 데 드는 소수 자리 수. */
  tickDecimals: number | null
  /** 만기가 가장 가까운 종목인지. 목록의 「최근 만기」 배지가 이 값입니다. */
  frontMonth: boolean
  /** 마스터가 주력으로 표시한 월물인지(해외 선물 `lmon`). **비워 두고 열 때
   *  세우는 종목**이고, 만기 사실을 말하는 `frontMonth` 와 다른 축입니다. */
  main: boolean
  /** 목록에 서는 값. **조회에서 옵니다**(`data/expiryQuotes.ts`) — 아직 안
   *  받았거나 답에 그 월물이 없으면 `null` 이고, 목록은 그 자리를 비웁니다.
   *  값을 지어내지 않습니다: 이 숫자는 어느 월물로 주문을 낼지 고르는 근거입니다. */
  last: number | null
  change: number | null
  changePct: number | null
  volume: number | null
  openInterest: number | null
  open: number | null
  high: number | null
  low: number | null
  /** 값이 **주간 마감**인 줄인가. 국내 야간에 야간 값을 받지 않은 월물이
   *  그렇습니다 — 목록은 이 줄의 수를 흐리게 세웁니다. 그 밖에는 거짓입니다. */
  closeOnly?: boolean
}

/** 옵션 체인 한쪽(콜 또는 풋)의 값. */
export interface ChainLeg {
  /** 실제 종목코드. 줄을 고르면 이 코드로 조회·구독합니다. */
  code: string
  /** 마스터 이름이 먼저이고, 없으면 응답 이름입니다. */
  name: string
  /** **값이 없는 칸은 `null` 입니다.** 가격 칸의 원문 0 은 거래·호가가 없는 것이라
   *  `null` 로 오고, 대비·미결제·거래량의 0 은 값입니다. 시장마다 안 오는 칸이
   *  다릅니다 — 국내는 잔량, 해외는 미결제·이론가·그릭스가 `null` 입니다. */
  last: number | null
  prevClose: number | null
  change: number | null
  changePct: number | null
  volume: number | null
  openInterest: number | null
  oiChange: number | null
  delta: number | null
  gamma: number | null
  theta: number | null
  vega: number | null
  iv: number | null
  theo: number | null
  theoDiff: number | null
  disparity: number | null
  bid: number | null
  ask: number | null
  bidQty: number | null
  askQty: number | null
  /** 해외 서버가 표시하는 등가격 줄. 체인에 한 줄만 참입니다. */
  atm: boolean
}

/** 옵션 체인의 한 행 — 행사가 하나에 콜과 풋이 붙습니다. */
export interface ChainRow {
  strike: number
  call: ChainLeg
  put: ChainLeg
}

/** 백엔드에 닿는지. **「연결 실패」와 「끊김」을 못 가릅니다** — 우리가 아는
 *  것은 「닿았다 / 못 닿았다 / 확인 중」 셋뿐이라 화면도 그렇게 말합니다. */
export type ConnectionState = 'checking' | 'ok' | 'error'

/** 최근 본 레일에 서는 항목. 시세는 붙이지 않습니다.
 *
 *  시장도 안 담습니다 — 코드가 이미 압니다. 항목마다 시장을 적어 두면 그 값과
 *  코드가 어긋날 수 있고, 어긋나면 해외 종목이 국내로 열립니다. */
export interface RecentItem {
  code: string
  name: string
}

/** 호가 한 단계 — 가격과 잔량. 국내 체인에는 잔량이 오지 않지만 호가창에는 옵니다. */
export interface BookLevel {
  price: number
  quantity: number
}

/** 시세·주문 화면이 한 종목에 대해 쓰는 값. */
/** 옵션에서 아직 안 고른 축. 콜/풋과 행사가가 다 정해져야 종목입니다. */
export type PendingAxis = 'strike' | 'side'

export interface Quote {
  /** 옵션인데 아직 안 고른 축이 있으면 그 축. 종목이 아직 정해지지 않았다는
   *  뜻이고, 화면 셋(헤더·차트 배지·주문 단추)이 이 값으로 같은 말을 냅니다. */
  pendingAxis?: PendingAxis
  /** 그 시장의 인증 정보가 없어 이 종목의 값을 **묻지 않는지**. 참이면 차트·호가
   *  같은 칸도 따로 묻지 않고 「조회 전」으로 섭니다. */
  withheld?: boolean
  /** 이 종목의 시장. 차트 칸에 다른 시장의 종목을 올릴 수 있어 종목이 제 시장을 들고 다닙니다. */
  market?: MarketContext
  code: string
  name: string
  /** 이 종목이 속한 품목 */
  productName: string
  /** 선물·옵션·스프레드. **값이 음수로 설 수 있는지**를 이 칸으로 가립니다 —
   *  스프레드는 두 만기의 차라 음수가 정상이고, 그 종목의 가격 열은 부호 한
   *  칸을 미리 잡습니다. 안 실려 오면 선물로 봅니다. */
  kind?: ProductKind
  decimals: number
  /** 분수로 적는 품목이면 그 분모(해외 `pind` 글자). 값을 그리는 자리가 이
   *  값을 보고 소수 대신 분수로 적습니다. */
  fraction?: number | null
  /** 이 종목의 호가단위(해외 `tsiz`). 호가 사다리의 한 단이 이 값입니다.
   *  마스터가 안 주는 시장(국내)에서는 없습니다. */
  tickSize?: number | null
  /** 잔존일수. 마스터도 시세도 안 주는 종목이 있어 `null` 일 수 있습니다. */
  daysLeft: number | null
  /** 계약 하나가 나타내는 크기. 주문금액과 증거금이 이 값에 걸립니다.
   *  **마스터가 시장마다 다른 것을 주어**(국내만 거래승수) 없으면 `null` 입니다. */
  multiplier: number | null
  /** 결제 통화 표기. 국내는 원, 해외는 품목이 정한 통화입니다. */
  currency: string
  /** 현재가. **아직 아무 값도 못 받은 종목은 `null`** 입니다 — 자리를 채우려고
   *  숫자를 지어내면 사용자가 그것을 이 종목의 값으로 읽고, 주문가격까지 그
   *  숫자에서 나옵니다. 시세가 있는지는 이 칸 하나로 가릅니다. */
  last: number | null
  /** 시세가 있어도 **비어 올 수 있는 칸들**입니다 — 그날 거래가 없는 종목(해외
   *  옵션)은 시가·고가·저가가 없고, 등락·거래량도 응답이 안 실을 수 있습니다.
   *  `null` 이면 화면이 그 칸만 「—」로 그립니다. 0 으로 채우면 「없다」가 「0 에
   *  거래됐다」가 됩니다. 시세가 있는지는 `last` 하나로 가릅니다. */
  change: number | null
  changePct: number | null
  open: number | null
  high: number | null
  low: number | null
  volume: number | null
  /** 거래대금. 백만 단위입니다 — 원 단위로 두면 열두 자리가 되어 지표 칸에 안 들어갑니다.
   *  **해외 현재가에는 없는 값**입니다(미결제도) — 그때 `null` 이고 화면이 「—」로 그립니다. */
  turnover: number | null
  openInterest: number | null
  openInterestChange: number | null
  /** 국내에만 옵니다. 해외에는 상한·하한이 없습니다. */
  upperLimit?: number
  lowerLimit?: number
  /* 이 종목이 상장된 뒤의 최고·최저. 오늘 값이 아니라 계약 한 살이의 값이라
     장중에 거의 안 움직입니다.
     원문 키는 시장마다 다릅니다 — 국내 `max_lst_pric`·`min_lst_pric`,
     해외 `occurs1_life_high_pric`·`occurs1_life_low_pric`. 한 자리에 두 이름을
     담을 수 없어 화면 쪽 이름을 하나 둡니다. */
  lifeHigh?: number
  lifeLow?: number
  settlement?: number
  /** 정산가가 어느 날의 값인지(`YYYY-MM-DD`). 해외 현재가 응답이 함께 냅니다 —
   *  휴장 뒤에는 이틀 전 값일 수 있어 날짜가 붙어야 값이 됩니다. */
  prevSettlementDate?: string
  lastTradingDay?: string
  /** 국내 3층. 해외에는 오지 않습니다. */
  theory?: number
  disparity?: number
  iv?: number
  basisTheory?: number
  basisActual?: number
  spot?: number
  /** 현물가의 전일대비. 선물 등락과 방향이 갈리는 자리가 곧 베이시스입니다. */
  spotChange?: number
}

/** 이 종목의 미체결 한 건. */
export interface OpenOrder {
  id: string
  side: 'buy' | 'sell'
  orderType: string
  /** 이 주문이 지금 어디 있는지. 아직 일하는 중이면 체결 수량과 주문 수량이
   *  함께 서고, 거절·자동취소면 그 말만 섭니다. */
  progress: OrderProgress
  /** 신규인지 정정인지 취소인지. 정정·취소는 **새 주문번호로 한 줄이 더** 서므로,
   *  한 주문을 고쳐 온 자취가 여러 줄로 남습니다. 서버가 안 주면 `undefined`
   *  이고 화면은 아무 표시도 달지 않습니다. */
  orderKind?: string
  /* **비어 올 수 있습니다.** 시장가 주문은 주문가격이 없고, 서버가 안 준 칸은
     `null` 입니다 — 0 으로 채우면 「없다」가 「0 이다」가 됩니다. */
  price: number | null
  /** 스탑가격. 해외 STOP 주문에만 오고, 정정·취소가 원주문의 값으로 싣습니다.
   *  국내 줄에는 없어 비어 있습니다. */
  stopPrice?: number | null
  quantity: number | null
  filled: number | null
  /** 다른 경로로 낸 주문은 우리 폼으로 표현할 수 없어 정정·취소를 잠급니다. */
  source: string
  strategy?: string
  editable: boolean
}

/** 주문이 지금 어디 있는지. **체결이 끝난 주문은 여기 없습니다** — 그 줄은
 *  체결로 섭니다. */
export type OrderProgress =
  | 'working'
  /** **우리가 방금 낸 주문의 접수 답.** `working` 과 가르는 것은 체결 수량
   *  때문입니다 — 접수 답에는 체결이 없어 「미체결 0 / 3」으로 적으면 서버가
   *  말한 적 없는 0 을 적게 됩니다. 조회와 실시간 알림이 그 줄을 덮으면
   *  `working` 이 됩니다. */
  | 'accepted'
  /** **취소가 접수된 것**이고 원주문이 사라진 것을 본 것은 아닙니다. 줄이
   *  없어지는 것이 취소 완료이고, 서버가 스스로 거둔 것은 `auto-cancelled`
   *  입니다 — 셋이 다른 사실입니다. */
  | 'cancelled'
  | 'rejected'
  | 'auto-cancelled'
  /** **더 이상 살아 있지 않은 줄.** 정정하면 원주문이, 취소가 받아들여지면 그
   *  주문이 이 자리로 갑니다 — 둘 다 체결 없이 잔량이 0 이 됩니다.
   *
   *  **왜 따로 두는가.** 국내 주문내역은 정정·취소해도 줄이 사라지지 않고 새
   *  번호로 한 줄이 더 붙어, 한 주문을 고쳐 온 자취가 여러 줄로 남습니다. 그
   *  줄들이 들고 오는 상태는 살아 있는 주문과 같아서, 상태만 보고 적으면 이미
   *  끝난 주문이 「미체결」로 섭니다.
   *
   *  **무엇이 끝냈는지는 이 값이 말하지 않습니다** — 정정에 밀린 것과 취소된
   *  것을 상태 칸으로는 가를 수 없습니다. 그 구분은 줄의 종류(`orderKind`)가
   *  합니다. */
  | 'closed'

/* 다른 화면에서 일반주문을 열 때 함께 넘기는 「무엇을 하러 왔는가」.
 *
 * 종목만 넘기면 주문 폼이 새 주문으로 열립니다. 그런데 잔고에서 누른 사람은
 * 그 포지션을 덜어내러 온 것이고, 미체결에서 누른 사람은 그 주문을 고치러
 * 온 것입니다 — 도착해서 다시 찾게 두면 누른 뜻이 사라집니다. */
export type OpenIntent =
  | { kind: 'close'; position: Position }
  | { kind: 'amend'; order: AccountOrder }

/** 이 종목의 체결 한 건. */
export interface Fill {
  id: string
  time: string
  side: 'buy' | 'sell'
  /* 체결가격과 체결수량도 비어 올 수 있습니다. 없으면 「—」입니다. */
  price: number | null
  quantity: number | null
}

/* ── 계좌 ─────────────────────────────────────────────── */

/* 예수금은 두 축을 가진 값입니다 — 항목 일곱 × 구분 넷.
 * 스물여덟 칸이 한 표에 들어가므로 무엇을 뺄지 고를 필요가 없습니다. */
export interface DepositItem {
  label: string
  /** 총액 · 현금 · 대용 · 외화 순 */
  values: [number, number, number, number]
}

/** 보유 포지션 한 건. 국내는 가격이 종가로, 해외는 현재가로 옵니다. */
export interface Position {
  code: string
  name: string
  /** 종목 마스터에서 그 종목을 못 찾았으면 까닭 한 줄. 이름이 응답 값이나
   *  코드로 대신 서 있고 만기·자릿수도 비어 있다는 뜻입니다. */
  nameNote?: string
  /* 만기일. 해외는 응답에 실려 오고(`occurs1_exp_dt`), 국내는 잔고 응답에
     없어 종목 마스터에서 찾습니다 — 그래서 국내에만 「못 찾음」이 있습니다.
     빈 문자열이면 아직 못 찾은 것입니다. */
  expiry: string
  daysLeft: number | null
  market: MarketContext
  side: 'long' | 'short'
  /* **비어 올 수 있습니다.** 서버가 안 준 칸은 `null` 이고 화면은 「—」로
     세웁니다 — 0 으로 채우면 「없다」가 「0 이다」가 됩니다. 자릿수는 종목
     마스터가 답하는데, 못 찾으면 역시 `null` 입니다. */
  quantity: number | null
  avgPrice: number | null
  lastPrice: number | null
  decimals: number | null
  /** 그 줄 종목이 분수로 불리면 분모(마스터가 답함). 소수로 불리거나 못 찾으면
   *  `null` 입니다 — 표의 가격을 줄마다 그 종목의 꼴로 적는 데 씁니다. */
  fraction: number | null
  pl: number | null
  /** 국내는 서버가 주고 해외는 화면이 평균가와 현재가로 셈합니다.
   *  평균가가 없거나 0 이면 셈할 수 없어 `null` 입니다. */
  plPct: number | null
  currency: string
  /** 선물·옵션·스프레드. **서버가 주는 시장에만 있습니다** — 안 주면 `undefined`
   *  이고 화면은 아무 표시도 달지 않습니다. 이름만 보고 스프레드라고 적으면,
   *  이름 규칙이 바뀌는 날 화면이 없는 사실을 말하게 됩니다. */
  productKind?: string
}

/** 계좌 화면의 미체결 한 건. 시장을 가리지 않고 모아 봅니다. */
export interface AccountOrder {
  id: string
  code: string
  name: string
  /** 종목 마스터에서 그 종목을 못 찾았으면 까닭 한 줄. 이름이 응답 값이나
   *  코드로 대신 서 있고 만기·자릿수도 비어 있다는 뜻입니다. */
  nameNote?: string
  market: MarketContext
  side: 'buy' | 'sell'
  orderType: string
  /* 비어 올 수 있습니다 — 시장가 주문은 주문가격이, 안 체결된 주문은 체결가격이
     없습니다. 자릿수는 마스터가 답하고 못 찾으면 `null` 입니다. */
  price: number | null
  /** 스탑가격. 해외 STOP 주문에만 옵니다. */
  stopPrice?: number | null
  decimals: number | null
  quantity: number | null
  filled: number | null
  time: string
  source: string
  /** 선물·옵션·스프레드. **서버가 주는 줄에만 있습니다** — 안 주면 `undefined`
   *  이고 화면은 아무 표시도 달지 않습니다. */
  productKind?: string
  /** 우리 폼으로 낼 수 없는 주문이면 왜 그런지 */
  locked?: string
}

/** 주문 오류 한 건. 무엇을 하려다 왜 막혔는지만 있습니다. */
export interface OrderError {
  id: string
  time: string
  name: string
  /** 종목 마스터에서 그 종목을 못 찾았으면 까닭 한 줄. 이름이 응답 값이나
   *  코드로 대신 서 있고 만기·자릿수도 비어 있다는 뜻입니다. */
  nameNote?: string
  market: MarketContext
  message: string
}

/** 오늘 체결된 주문 한 건. */
export interface AccountFill {
  id: string
  code: string
  name: string
  market: MarketContext
  side: 'buy' | 'sell'
  price: number
  decimals: number
  quantity: number
  time: string
}
