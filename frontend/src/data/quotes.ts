/** 시세를 받아 두는 자리 — 국내와 해외를 한 곳에서.
 *
 *  화면이 직접 부르지 않고 여기를 거칩니다. 한 종목을 헤더·호가·차트가 함께
 *  보므로, 각자 부르면 같은 요청이 세 번 나가고 셋이 서로 다른 시각의 값을
 *  들게 됩니다. 여기서 한 번 받아 나눠 줍니다.
 *
 *  **종목마다 따로 담습니다.** 화면이 칸을 둘로 나누면 두 종목이 동시에 서고,
 *  둘을 오가는 동안 앞 종목 값이 뒷 종목 자리에 들어가면 안 됩니다.
 *
 *  **부호·순서·빈 단계 같은 손질은 여기서 하지 않습니다.** 백엔드가 이미
 *  합니다(`backend/domestic_futureoption/domestic_quotes.py` ·
 *  `backend/overseas_futureoption/overseas_quotes.py`). 여기서 다시 손대면 같은
 *  규칙이 두 곳에 생기고, 한쪽만 고쳐질 때 조용히 갈립니다.
 *
 *  **어느 시장의 어느 길로 부를지는 종목이 정합니다.** 마스터가 시장·거래소·종류를
 *  알고 있어 해외는 거래소코드(`F`/`O` + 거래소)를 화면이 붙여 보내고, 국내는
 *  서버가 답한 세션(`data/session.ts`)이 야간이면 야간 현재가와 야간 호가를
 *  부릅니다. 분봉은 주간·야간 한 벌(`session: both`)로 받아 차트가 이어 그립니다.
 *
 *  **실시간 체결로 봉을 잇는 것도 여기서 합니다**(`foldTrades`). 차트 칸이 아니라
 *  저장소가 접어야 같은 종목을 보는 두 칸이 같은 봉을 보고, 재조회·환경 정리와
 *  한자리에 있습니다. 조회 봉(`bars`)은 조회 때만 바뀌고, 체결로 접은 봉은 `live`
 *  로 따로 흐릅니다 — 차트는 조회 봉이 바뀔 때만 다시 세우고 체결은 마지막 봉만
 *  갈아 끼웁니다.
 *
 *  **이름·자릿수·호가단위는 시세에 없습니다.** 종목 마스터가 들고 있고 화면이
 *  이미 받아 두었으므로, 시세는 숫자만 채웁니다.
 *
 *  **환경(모의·실전)이 바뀌면 전부 지웁니다.** 모의 서버의 시세와 그 연결로 쌓인
 *  체결은 실전의 값이 아닙니다. 값마다 어느 환경의 답인지를 붙여 두고, 환경을
 *  몰랐다가 알게 될 때는 이름이 같은 값은 두고 다른 값만 지웁니다. 환경을 아직
 *  모르는 동안은 조회를 내지 않습니다(`data/environment.ts`).
 */
import { useEffect, useSyncExternalStore } from 'react'

import {
  accepts,
  environmentOf,
  environmentSettled,
  generation,
  onEnvironmentChange,
  paperUnavailable,
  quoteSubscription,
  useEnvironment,
  type Environment,
} from './environment'
import { needsLeg, resolve, type Market } from './instruments'
import { noteQuoteArrival } from './lastQuote'
import {
  domesticNightRound,
  inDomesticDay,
  sessionEntry,
  subscribeSession,
  type SessionName,
} from './session'
import { kstClock, kstDate, kstDay, kstDayStart, kstParts, subtractYears } from '../lib/kst'
import type { BookLevel, Quote } from '../lib/types'

/** 서버가 내는 현재가. **모든 값이 비어 올 수 있습니다** — 값이 없으면 `null`
 *  이고, 그것은 0 이 아니라 「이 자리에 값이 없다」는 뜻입니다. */
export interface PriceReply {
  code: string
  name: string
  last: number | null
  change: number | null
  changePct: number | null
  open: number | null
  high: number | null
  low: number | null
  volume: number | null
  turnover: number | null
  openInterest: number | null
  openInterestChange: number | null
  upperLimit: number | null
  lowerLimit: number | null
  spot: number | null
  spotChange: number | null
  lifeHigh: number | null
  lifeLow: number | null
  theory: number | null
  disparity: number | null
  iv: number | null
  basisTheory: number | null
  basisActual: number | null
  lastTradingDay: string | null
  daysLeft: number | null
  multiplier: number | null
  /** 해외에만 오는 값. 국내 응답에는 칸 자체가 없습니다. */
  settlement?: number | null
  /** 정산가의 기준일. 해외에만 옵니다. */
  prevSettlementDate?: string | null
  /** 실시간 구독에 쓰는 코드. 조회 코드와 다를 수 있어 서버가 함께 냅니다. */
  realCode?: string | null
}

/** 서버가 내는 호가. `asks` 는 먼 값부터, `bids` 는 가까운 값부터입니다.
 *  **값이 안 채워진 단계는 빠지므로 둘 다 빈 배열일 수 있습니다.** */
export interface BookReply {
  /** 이 호가가 어느 종목의 것인지. 오면 부른 종목과 대 보고, 없으면 대 볼
   *  것이 없어 그대로 씁니다. */
  code?: string
  asks: BookLevel[]
  bids: BookLevel[]
  /** 국내 예상체결가. **단일가(개장·마감 동시호가) 때만 값이고 접속매매 중엔
   *  `null`** 입니다 — 국내 호가는 조회·실시간 모두 이 칸을 늘 싣습니다. 해외
   *  호가에는 칸이 없습니다. */
  expectedPrice?: number | null
}

/** 서버가 내는 봉. 오래된 것부터입니다. `timestamp` 는 봉이 시작하는 분입니다. */
export type BarReply = {
  timestamp: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

/** 화면이 그리는 봉 — 서버 봉과 같은 모양입니다. 체결로 접은 봉도 이 모양입니다. */
export type Bar = BarReply

/** 앞으로 이어 받은 분봉과 그 걸음. 차트가 왼쪽 끝에 닿을 때마다 한 영업일씩
 *  앞으로 갑니다. */
export interface History {
  /** 이어 받은 봉. 조회 봉보다 앞이고 오래된 것부터입니다. */
  bars: Bar[]
  /** 다음에 물을 자리 — **이 영업일보다 앞**을 달라는 뜻입니다. 비어 있으면
   *  지금이 속한 영업일부터입니다. 서버가 답에 실어 주는 값을 그대로 씁니다. */
  before: string
  /** 더 갈 곳이 없다고 정해졌나. */
  done: boolean
  /** 받아 온 날 가운데 **덜 받았을 수 있는 날**이 있었나. 조용히 적는 값이고
   *  멈춤 판단에는 안 씁니다 — 거래가 드문 먼 월물은 거의 늘 참이라, 이것으로
   *  멈추면 그런 종목은 한 걸음도 못 갑니다. */
  short: boolean
  loading: boolean
}

/** 빈 답이 이만큼 **잇따라** 오면 멈춥니다. 한 번 비었다고 멈추지 않는 것은
 *  **휴장일이 빈 영업일로 오기** 때문입니다 — 휴장일 달력이 없어 연휴 앞에서
 *  멈춰 버립니다. */
const HISTORY_EMPTY_DAYS = 5

/** 한 번 당길 때 물어볼 **영업일 수**의 한도. 빈 날 다섯에 **이미 아는 날**이 몇 번
 *  섞일 수 있어 빈 날 수보다 넉넉합니다 — 없으면 아는 날만 돌려주는 서버에서
 *  끝없이 뒤로 갑니다. */
const HISTORY_MAX_DAYS = HISTORY_EMPTY_DAYS + 3

/** 한 번 당길 때 **물음 수**의 한도.
 *
 *  한도가 둘인 것은 **한 영업일이 여러 번에 나뉘어 올 수 있기** 때문입니다 —
 *  해외는 한 응답에 담기는 줄 수가 정해져 있어, 거래가 잦은 날은 같은 영업일이
 *  다음 장으로 이어집니다. 그 장은 앞으로 간 것이 아니라 같은 날을 마저 받는
 *  것이라 날 수로 세지 않고, 그래도 제자리를 돌지 않도록 물음 수에 뚜껑을
 *  씌웁니다. 국내는 한 장이 곧 한 영업일이라 이 뚜껑에 닿지 않습니다. */
const HISTORY_MAX_CALLS = 20

/** 분봉 한 칸. 체결의 봉 열쇠는 이 배수로 내림한 시각입니다. */
export const MINUTE_MS = 60_000

/** 못 받은 까닭. 사용자가 할 일이 갈려 따로 둡니다 —
 *  `retry` 는 다시 눌러 볼 만하고, `rejected` 는 눌러도 같은 답입니다.
 *  `paper` 는 **모의투자에서는 NH선물이 이 조회를 제공하지 않는다**는 답입니다 —
 *  거절처럼 다시 불러도 같고, 까닭이 정해져 있어 화면이 그 까닭을 그대로 말합니다. */
export type QuoteFailure = 'retry' | 'rejected' | 'paper'

/** 모의투자라 국내 야간 현재가를 못 받을 때 세우는 문장. 종목 머리와 주문 단추의
 *  까닭이 **같은 글자**를 씁니다 — 한 화면에서 같은 사실을 두 말로 부르면 다른
 *  일이 일어난 것으로 읽힙니다. */
export const PAPER_NIGHT_PRICE_TEXT = '모의투자에서는 야간 현재가를 받을 수 없습니다'

/** 실시간이 보내는 체결 한 건.
 *
 *  **매수·매도가 없습니다.** 체결구분으로 오는 글자(국내 `1`·`2`, 해외 `+`·`-`)의
 *  뜻이 명세에 없어 백엔드가 방향을 만들지 않고 받은 글자를 그대로 올립니다.
 *  같은 이름이 다른 조회에서 전혀 다른 뜻으로 쓰인 전례가 있어, 짐작으로
 *  방향을 정하면 **틀려도 화면에서 표가 안 납니다.** 그래서 화면도 이 값으로
 *  방향을 말하지 않습니다. */
export interface TradeTick {
  price: number
  quantity: number
  time: string
  sideCode: string
  /** 한국시간 기준 순간(밀리초). 조회 봉의 `timestamp` 와 같은 시계라 봉에
   *  접을 수 있습니다. 시각이 없는 체결(해외에서 한국시각 칸이 빈 것)은 칸이
   *  없고, 그때는 목록에만 들어가고 봉에는 안 들어갑니다. */
  timestamp?: number
}

/** 시세체결 카드가 담아 두는 체결 수. 넘치면 오래된 것부터 버립니다 —
 *  카드가 보이는 것보다 넉넉하되, 하루 종일 쌓아 둘 값은 아닙니다.
 *
 *  **이 수가 카드 머리의 「언제부터」를 가릅니다.** 여기까지 안 찼으면 붙은
 *  뒤의 체결을 하나도 안 버렸다는 뜻이라 「붙은 시각부터」가 참이고, 다 차면
 *  앞쪽을 버린 뒤라 담고 있는 가장 오래된 체결의 시각만 참입니다. */
export const TRADE_KEEP = 60

export interface QuoteEntry {
  /** `loading` 동안에는 값을 그리지 않습니다. 앞 종목 값을 그대로 두면
   *  사용자는 새 종목의 값으로 읽습니다. */
  status: 'loading' | 'ready' | 'failed'
  /** **어디까지 물어봤는지.** 값 몇 자리만 보이는 자리(홈 관심종목)는 현재가만
   *  부르고, 주문 화면은 호가·분봉까지 셋을 부릅니다. 이 표시가 없으면 홈이
   *  받아 둔 종목을 주문 화면에서 열 때 「이미 물어봤다」로 건너뛰어 **호가와
   *  분봉이 영영 안 옵니다.** */
  full: boolean
  price: PriceReply | null
  book: BookReply | null
  /** 조회로 받은 분봉(주간·야간 한 벌). 조회 때만 바뀝니다 — 차트가 이 참조의
   *  변화에만 다시 섭니다. */
  bars: BarReply[] | null
  /** 조회 봉 뒤에 실시간 체결로 접은 봉. 조회 봉의 마지막 분과 같은 열쇠면 그
   *  봉을 늘린 사본이 첫 봉으로 서고, 차트는 같은 열쇠를 덮어 그립니다. 조회 봉을
   *  새로 받으면 비웁니다. */
  live: Bar[]
  /** 일봉(주간). 조회 때만 바뀝니다. */
  daily: BarReply[] | null
  /** 조회 일봉 뒤에 체결로 접은 일봉. 분봉의 `live` 와 같은 꼴이고 같은 까닭으로
   *  따로 둡니다 — 조회 봉 참조가 바뀌면 차트가 판을 다시 세웁니다. */
  dailyLive: Bar[]
  /** 앞으로 이어 받은 분봉과 그 걸음. **`bars` 를 안 건드립니다** — 차트가 그
   *  참조의 변화로 판을 다시 세우므로, 이어 받을 때마다 보던 자리를 잃습니다. */
  history: History
  dailyStatus: 'idle' | 'loading' | 'ready' | 'failed'
  failure: QuoteFailure | null
  /** 거절에 서버가 실어 준 안내 문장(시세 사용 신청이 필요한 거래소). 없으면 빈
   *  글자이고, 그때 화면은 제 문장(「시세를 받지 못했습니다」)을 씁니다. */
  failureText?: string
  /** 호가만 따로 못 받았을 때 그 까닭. 현재가는 왔는데 호가만 실패할 수 있고,
   *  그때 거절이면 다시 부를 일이 아니라 단추를 안 세웁니다. 모의투자라 못 받는
   *  답도 다시 불러도 같은 답이라 거절로 적습니다. */
  bookFailure: Exclude<QuoteFailure, 'paper'> | null
  /** 국내 예상체결가. 단일가 동안만 값이고, 그 밖에는 `null` 입니다. 호가 조회
   *  답, 실시간 호가, 실시간 시세 셋이 이 한 자리를 씁니다 — **`null` 이 「지워라」
   *  입니다**(동시호가 값이 접속매매 뒤에 남지 않게). 화면은 이 값의 유무만 보고
   *  세션을 따로 판단하지 않습니다. */
  expectedPrice: number | null
  /** 실시간으로 온 체결. **구독해도 첫 값이 없어** 붙은 뒤 처음 체결이
   *  일어날 때까지 비어 있습니다. */
  trades: TradeTick[]
  /** 이 값이 언제 것인가(`HH:MM`). 조회로 채운 때와 실시간이 덮은 때에 갱신됩니다.
   *  **자리가 모자라 실시간이 안 붙은 칸**은 이 시각에서 멈추고, 카드가 그
   *  시각을 적어 「값이 언제 것인지」를 말합니다. */
  at: string
  /** 이 값이 어느 환경의 답인지. 응답이 말한 것이고, 안 실려 왔으면 `null` 입니다. */
  environment: Environment | null
  /** 국내 현재가를 **어느 세션의 길로** 받았는지. 세션 답이 조회보다 늦게 오거나
   *  보는 중에 세션이 바뀌면 이 값이 지금 세션과 어긋나고, 그때 다시 받습니다.
   *  해외·아직 못 받음은 `null` 입니다. */
  session: SessionName | null
}

const EMPTY: QuoteEntry = {
  status: 'loading',
  full: false,
  price: null,
  book: null,
  bars: null,
  live: [],
  daily: null,
  dailyLive: [],
  history: { bars: [], before: '', done: false, short: false, loading: false },
  dailyStatus: 'idle',
  failure: null,
  bookFailure: null,
  expectedPrice: null,
  trades: [],
  at: '',
  environment: null,
  session: null,
}

/** 지금 한국시각을 `HH:MM` 으로. 값이 언제 것인지를 적는 데만 씁니다 — 초까지 적으면
 *  눈이 그 숫자를 좇습니다. */
function stamp(): string {
  return kstClock(Date.now())
}

/** 화면이 빈칸으로 못 두는 자리 — **현재가 하나**입니다. 이것이 비면 이 응답으로는
 *  화면을 못 세우고 「아직 시세가 없습니다」가 섭니다. 나머지 칸은 시세가 있어도 비어
 *  올 수 있어(그날 거래 없는 해외 옵션의 시가·고가·저가, 야간의 현물가, 해외에 없는
 *  거래대금·미결제) 그 칸만 「—」로 그립니다. 시장마다 다르게 요구하지 않습니다 —
 *  0 은 값이고 `null` 만 없음입니다. */
const REQUIRED = ['last'] as const

function requiredOf(_code: string): readonly (keyof PriceReply)[] {
  return REQUIRED
}

/** 종목의 시장. 마스터가 아직 없어 못 풀면 국내로 봅니다 — 국내 길이 먼저 있었고,
 *  마스터 없이 부르는 자리는 없습니다. */
function marketOf(code: string): Market {
  return resolve(code)?.market ?? 'domestic'
}

/** 종목마다 부르는 길. 해외는 거래소코드를 화면이 함께 보냅니다 — 마스터가 품목
 *  줄에 그 값을 이미 싣고 있어서이고, 서버가 종목코드로 마스터를 뒤지면 시세가
 *  마스터 적재 상태에 묶입니다. 국내 야간은 야간 현재가 조회입니다. */
interface Route {
  market: Market
  /** 국내는 어느 세션의 길인지. 해외는 세션이 갈리지 않아 `null` 입니다. */
  session: SessionName | null
  price: { path: string; body: Record<string, unknown> }
  book: { path: string; body: Record<string, unknown> }
  bars: { path: string; body: Record<string, unknown> }
  daily: { path: string; body: Record<string, unknown> }
  /** 앞으로 이어 받는 분봉. **어디까지 받았는지(`before`)는 여기 없습니다** —
   *  걸음마다 달라지는 값이라 부르는 자리가 실어 보냅니다. */
  history: { path: string; body: Record<string, unknown> }
}

/** 이 코드로 조회를 낼 수 있나. **계약이 확정된 코드만** 나갑니다 — 옵션에서 콜풋·
 *  행사가를 아직 안 고른 자리의 코드(`품목:만기`)는 이 앱의 자료구조이지 거래소의
 *  종목이 아니라, 그대로 부르면 시세·호가·분봉·일봉 네 건이 나란히 거절로 돌아옵니다.
 *
 *  네 받아오기가 모두 이 문을 지납니다 — 부르는 화면마다 막으면 새로 생기는 화면이
 *  그 자리를 빠뜨립니다. */
function askable(code: string): boolean {
  return code !== '' && !needsLeg(code)
}

function routeOf(code: string, day: string): Route {
  const item = resolve(code)
  if (item?.market === 'overseas') {
    /* **마스터가 실어 준 거래소 코드 그대로**입니다(`ExchName`). 선물·옵션 접두어가
       이미 붙어 있고, 품목 하나에 선물과 옵션이 함께 실리지 않아 종류로 다시 가를
       것이 없습니다.

       화면에 서는 거래소 이름으로 지으면 안 됩니다 — 이름과 코드가 다른 거래소가
       있어(`EUREX` ↔ `FERX`·`OERX`, `CBOE` ↔ `FCBO`·`OCBO`) 그 품목들만 조용히
       없는 거래소를 묻게 됩니다.

       **마스터가 코드를 안 주면 묻지 않습니다.** 지어낸 값은 다른 거래소의 답을
       물어 오고, 빈 값으로 물으면 서버가 되돌려 보낸 것이 「다시 받기」 얼굴로
       서는데 눌러도 될 리가 없는 자리입니다. 길을 비워 두면 조회가 나가지 않고
       거절로 답합니다. */
    const exchange = item.product.exchangeCode
    const at = { exch_cd: exchange ?? '', sym: code }
    const to = (path: string) => (exchange ? path : '')
    return {
      market: 'overseas',
      session: null,
      price: { path: to('/api/overseas/price'), body: { syms: [at] } },
      book: { path: to('/api/overseas/bid-price'), body: at },
      bars: {
        path: to('/api/overseas/chart-minute'),
        body: { ...at, inq_strt_dt: day, inq_ed_dt: day },
      },
      daily: {
        path: to('/api/overseas/chart-daily'),
        body: { ...at, inq_strt_dt: yearBefore(day), inq_ed_dt: day },
      },
      /* 해외 분봉은 **날짜로 과거를 못 부릅니다** — 늘 가장 최근 쪽이 옵니다.
         그래서 날짜 대신 서버가 준 이어받기 값을 되돌려 보내며 뒤로 걷습니다. */
      history: { path: to('/api/overseas/chart-history'), body: { ...at, dcnt: '1' } },
    }
  }
  const session = domesticSessionOf(code)
  const night = session === 'night'
  return {
    market: 'domestic',
    session,
    price: { path: night ? '/api/domestic/price-night' : '/api/domestic/price', body: { sym: code } },
    /* 야간 호가는 현재가와 달리 별도 조회가 아니라 **같은 조회에 시장 구분**으로
       가릅니다 — 주간 `KSP`, 야간 `NDV`. 기본값을 적어 두어 세션이 바뀌면 본문이
       바뀌는 것이 보입니다. */
    book: { path: '/api/domestic/price-bid', body: { sym: code, exch_cd: night ? 'NDV' : 'KSP' } },
    /* 주간·야간 한 벌. 세션이 바뀌어도 앞 세션의 봉이 남아 차트가 이어집니다. */
    bars: {
      path: '/api/domestic/chart-minute',
      body: { sym: code, inq_strt_dt: day, inq_ed_dt: day, session: 'both' },
    },
    /* 일봉은 세션과 무관하게 **주간 일봉**입니다. 야간 일봉은 다른 세션의 봉이라
       한 봉으로 합칠 수 없고, 야간에 보는 일봉 차트도 주간 일봉을 보입니다. */
    daily: {
      path: '/api/domestic/chart-daily',
      body: { sym: code, inq_strt_dt: yearBefore(day), inq_ed_dt: day, night: false },
    },
    history: { path: '/api/domestic/chart-history', body: { sym: code, dcnt: '1' } },
  }
}

/** 일봉을 부를 시작 날짜 — 그날로부터 1년 전. 오는 만큼 그립니다. */
function yearBefore(day: string): string {
  return subtractYears(day, 1)
}

/** 한국시간을 `HHMMSS` 로 — 분봉 재조회의 시작 시각에 씁니다. 서버는 이 시각을
 *  한국시간으로 읽습니다. */
function clock6(timestamp: number): string {
  const { hour, minute, second } = kstParts(timestamp)
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${pad(hour)}${pad(minute)}${pad(second)}`
}

/** 국내 종목이 지금 어느 세션의 길로 가야 하는지. 세션을 모르면(아직 안 물었거나
 *  마감) 주간입니다 — 마감 중 주간 현재가는 마지막 값이고, 야간이 열리면 세션
 *  답이 바뀌어 다시 받습니다. */
function domesticSessionOf(code: string): SessionName {
  return sessionEntry('domestic', code).session === 'night' ? 'night' : 'day'
}

/** 받아 둔 국내 값이 지금 세션의 길로 받은 것인지 보고, 아니면 다시 받습니다.
 *
 *  **세션 답과 조회는 따로 옵니다.** 종목을 열면 둘을 같이 묻는데 세션 답이 늦으면
 *  현재가는 주간 길로 이미 나간 뒤라, 야간에 연 화면이 주간 마감값을 들고
 *  섭니다. 보는 중에 세션이 바뀔 때(실시간 방송 → `/api/session` 재확인)도 같은
 *  자리입니다. 셋을 받아 둔 종목은 셋을, 현재가만 받아 둔 종목은 현재가만
 *  다시 받습니다. 받는 중이면 겹쳐 내지 않고, 그 답이 온 뒤 여기서 다시 봅니다. */
function reconcileSession(code: string): void {
  const held = entries.get(code)
  /* 모의투자라 야간 현재가를 못 받은 종목은 값이 없어도 다시 봅니다 — 주간이 되면
     주간 길로 받아야 합니다. */
  if (!held || (held.price == null && held.failure !== 'paper') || marketOf(code) !== 'domestic') return
  if (held.session === domesticSessionOf(code)) return
  if (!environmentSettled()) return
  if (held.full) void loadQuote(code, { force: true })
  else void loadPrice(code, { force: true })
}

subscribeSession(() => {
  for (const code of entries.keys()) reconcileSession(code)
})

/** 해외 현재가는 여러 종목을 한 번에 답합니다 — 부른 종목의 줄을 고릅니다.
 *  **다른 종목의 줄로 대신하지 않습니다** — 그 줄의 코드가 비어 있으면 뒤의 대조가
 *  못 잡아 다른 종목의 값이 이 종목 이름 옆에 섭니다. 없으면 못 받은 것입니다.
 *  국내는 한 종목이 그대로 옵니다. */
function priceOf(reply: PriceReply | { quotes?: PriceReply[] }, code: string): PriceReply | QuoteFailure {
  if ('quotes' in reply && Array.isArray(reply.quotes)) {
    return reply.quotes.find((row) => (row.code ?? '').trim() === code) ?? 'retry'
  }
  return reply as PriceReply
}

const entries = new Map<string, QuoteEntry>()
const listeners = new Set<() => void>()
/** 셋(현재가·호가·분봉)을 함께 받는 중인 종목과 그 물음을 낸 세대.
 *
 *  **세대를 함께 적는 까닭**: 환경이 바뀌면 옛 세대의 물음은 더 이상 이 자리를
 *  막지 않아야 합니다 — 막으면 새 환경의 첫 조회가 「이미 나가 있다」로 건너뛰고,
 *  옛 답은 버려져 그 종목이 빈 채로 남습니다. */
const flyingFull = new Map<string, number>()
/** 현재가만 받는 중인 종목과 그 세대. */
const flyingPrice = new Map<string, number>()
/** 분봉만 받는 중인 종목과 그 세대. */
const flyingBars = new Map<string, number>()
/** 일봉만 받는 중인 종목과 그 세대. */
const flyingDaily = new Map<string, number>()
/** 지금 조회 봉 한 벌에 대해 꼬리 재조회를 이미 낸 종목. 조회 봉을 새로 받으면
 *  지워져 다음 첫 체결에 또 한 번 냅니다. */
const tailPatched = new Set<string>()
/** 꼬리 재조회가 나가 있는 동안 온 체결과 낸 시각. 답이 오면 그 뒤 체결만 다시 접습니다. */
const tailFlying = new Map<string, { issuedAt: number; trades: TradeTick[] }>()

/** 모의투자라 국내 야간 현재가를 받을 수 없다는 답을 받은 **야간 회차**.
 *
 *  그 답은 종목과 무관하게 같고 다시 불러도 같습니다. 한 번 받으면 그 회차가 끝날
 *  때까지 국내 야간 현재가를 더 부르지 않습니다 — 종목을 바꾸거나 다시 열어도
 *  같습니다. 주간에는 주간 길로 부르므로 이 값을 보지 않고, 다음 야간은 새
 *  회차라 다시 한 번 물어봅니다. 환경이 바뀌면 지웁니다. 메모리에만 두어 앱을
 *  다시 켜면 처음부터 묻습니다. */
let paperNightShut: number | null = null

/** 이 길의 현재가를 지금 부르지 않아도 되는가 — 국내 야간이고, 이 회차에 이미
 *  모의투자라 못 받는다는 답을 받았습니다. */
function priceShut(route: Route): boolean {
  return route.market === 'domestic' && route.session === 'night' && paperNightShut === domesticNightRound()
}

/** 모의투자라 못 받는다는 답을 받았으면 이 회차를 적어 둡니다. 국내 야간 현재가만입니다. */
function notePaper(route: Route, reply: unknown): void {
  if (reply === 'paper' && route.market === 'domestic' && route.session === 'night') {
    paperNightShut = domesticNightRound()
  }
}

/** 곧 부를 자리를 미리 「받는 중」으로 세워 둡니다.
 *
 *  환경(모의·실전)을 아직 몰라 조회를 못 내는 동안에도, 값을 그리는 자리들은
 *  「물어봤다」를 보고 임시 값을 안 세웁니다 — 이 표시가 없으면 그 사이 차트가
 *  지어낸 봉을 그립니다. 환경이 정리되면 같은 자리가 실제로 부릅니다. */
function markLoading(code: string): void {
  if (!code || entries.has(code)) return
  announce(code, { ...EMPTY })
}

function announce(code: string, next: QuoteEntry): void {
  entries.set(code, next)
  for (const listener of listeners) listener()
}

/** 지금 담겨 있는 것. 화면이 그리는 도중에 부르므로 **기다리지 않습니다.** */
export function quoteEntry(code: string): QuoteEntry {
  return entries.get(code) ?? EMPTY
}

/** 이 종목을 서버에 물어보는 자리인지. **임시 값이 서는 자리와 가릅니다** —
 *  아직 안 고른 자리는 물어본 적이 없어, 값이 없는 것이 실패가 아닙니다. */
export function quoteAsked(code: string): boolean {
  return entries.has(code)
}

/** 이 종목의 값을 화면에 세울 수 있는지. 받았어도 **현재가가 비어 있으면
 *  못 세웁니다** — 상장 뒤 한 번도 거래가 없는 종목이 그렇습니다. 값을 그리는
 *  자리들이 같은 답을 보도록 한 곳에서 답합니다. */
export function quoteHasValues(code: string): boolean {
  const price = quoteEntry(code).price
  return price !== null && !requiredOf(code).some((field) => price[field] === null)
}

export function subscribeQuotes(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** 한 조회의 답과, 그 답이 어느 환경에서 나왔는지. */
interface Posted<T> {
  reply: T | QuoteFailure
  environment: Environment | null
  /** 거절에 서버가 실어 준 안내 문장. 시세 사용 신청이 필요한 답에만 씁니다. */
  detail?: string
}

/** 물어보고 답을 돌려줍니다. **요청 뒤에 환경이 바뀌었거나 답이 다른 환경의
 *  것이면 `'stale'`** — 그 답은 담지 않습니다. */
async function post<T>(path: string, body: unknown, since: number): Promise<Posted<T> | 'stale'> {
  /* **길이 비어 있으면 묻지 않습니다.** 인자를 채울 값이 마스터에 없어 조회를
     낼 수 없는 자리입니다(`routeOf`). 다시 눌러도 같은 자리라 거절로 답합니다 —
     그 얼굴에는 「다시 받기」가 안 섭니다. */
  if (!path) return { reply: 'rejected', environment: null }
  try {
    const response = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!accepts(response, since)) return 'stale'
    const environment = environmentOf(response)
    if (response.ok) {
      /* 저장해 둔 응답으로 도는 개발 서버는 부른 종목의 기록이 없으면 다른
         종목의 기록으로 답합니다. 그 사실을 헤더로 알려 주므로 개발 중에만
         한 줄 남깁니다 — **화면에는 아무것도 안 세웁니다.** 값이 이 종목의
         것인지는 응답에 실린 종목코드로 따로 가리고, 여기 남기는 것은
         「왜 값이 안 서지」를 콘솔에서 바로 알게 하려는 것뿐입니다. */
      if (import.meta.env.DEV && response.headers.get('x-nh-replay-symbol') === 'other') {
        console.warn(`[시세] ${path} — 저장해 둔 다른 종목의 응답입니다.`)
      }
      return { reply: (await response.json()) as T, environment }
    }
    /* 모의투자에서는 제공하지 않는 조회라는 답은 까닭이 정해져 있어 따로 둡니다.
       502 는 NH선물이 거절한 것이라 다시 불러도 같은 답이 옵니다. 그 밖은
       연결이나 시간 초과라 다시 불러 볼 만합니다. */
    if (paperUnavailable(response)) return { reply: 'paper', environment }
    /* 시세 사용 신청이 필요한 거래소라는 답입니다. 다시 불러도 같은 답이라
       거절이고, 할 일을 말하는 서버 문장을 함께 돌려줍니다. */
    if (quoteSubscription(response)) {
      const said = (await response.json().catch(() => null)) as { detail?: unknown } | null
      const detail = typeof said?.detail === 'string' ? said.detail : ''
      return { reply: 'rejected', environment, detail }
    }
    return { reply: response.status === 502 ? 'rejected' : 'retry', environment }
  } catch {
    if (since !== generation()) return 'stale'
    /* 서버가 아직 안 떴거나 연결이 끊긴 경우입니다. 까닭을 지어내지 않고
       「못 받았다」까지만 말합니다. */
    return { reply: 'retry', environment: null }
  }
}

/** 버린 답의 자리. 그 사이 담긴 값이 있으면 그대로 두고, 없으면 「안 물어봤다」로
 *  되돌립니다 — 환경이 정리되면 보는 자리가 다시 부릅니다. 새 얼굴은 없습니다. */
function discard(code: string): void {
  const now = entries.get(code)
  if (now?.price != null) announce(code, { ...now, status: 'ready' })
  else {
    entries.delete(code)
    for (const listener of listeners) listener()
  }
}

function failed(reply: unknown): reply is QuoteFailure {
  return reply === 'retry' || reply === 'rejected' || reply === 'paper'
}

/** 이 회차에 이미 받은 「모의투자라 못 받는다」를 부르지 않고 그대로 세웁니다. */
function paperShut<T>(): Posted<T> {
  return { reply: 'paper', environment: null }
}

/** 분봉을 부를 날짜(한국 달력의 오늘). 하루치를 봅니다. */
function today(): string {
  return kstDate()
}

/** 한 종목의 시세를 받습니다. 이미 받아 둔 종목은 다시 부르지 않습니다.
 *
 *  셋을 함께 부르고 함께 답합니다 — 헤더만 새 종목이고 호가는 앞 종목인
 *  화면이 한 프레임이라도 서면, 그 사이에 누른 호가가 다른 종목 가격입니다.
 */
export async function loadQuote(code: string, options?: { force?: boolean }): Promise<void> {
  if (!askable(code)) return
  /* 종목을 오갈 때 같은 요청을 다시 내지 않습니다. **현재가만 받아 둔 종목은
     건너뛰지 않습니다** — 홈에서 값이 선 종목을 주문 화면에서 열면 호가와
     분봉이 아직 없습니다. */
  if (!options?.force && entries.get(code)?.full) return
  /* 어느 환경에서 물었는지 적어 둡니다. 답이 왔을 때 환경이 바뀌어 있으면 그 답은
     다른 환경의 값이라 버립니다. */
  const since = generation()
  /* 셋을 받는 중이면 같은 요청을 겹쳐 내지 않습니다. 보는 자리가 그리는 도중에
     한 번 더 부를 수 있는데, 그때마다 세 조회가 또 나가면 예산이 두 배로 듭니다. */
  if (flyingFull.get(code) === since) return
  flyingFull.set(code, since)

  /* 같은 종목을 다시 받는 동안에는 **받아 둔 값을 그대로 둡니다.** 종목이 그대로면
     지금 있는 값은 틀린 값이 아니라 낡은 값이고, 주문 화면에서 보던 가격이
     잠깐 사라지는 쪽이 더 나쁩니다. 값을 지우는 것은 종목이 바뀔 때뿐이고,
     그때는 이 자리에 담긴 것이 아예 없습니다. */
  const held = entries.get(code)
  announce(code, { ...(held ?? EMPTY), status: 'loading', failure: null, failureText: '' })

  const route = routeOf(code, today())
  const posted = await Promise.all([
    priceShut(route)
      ? paperShut<PriceReply | { quotes?: PriceReply[] }>()
      : post<PriceReply | { quotes?: PriceReply[] }>(route.price.path, route.price.body, since),
    post<BookReply>(route.book.path, route.book.body, since),
    post<{ code?: string; bars: BarReply[] }>(route.bars.path, route.bars.body, since),
  ])
  if (flyingFull.get(code) === since) flyingFull.delete(code)
  /* 그 사이 환경이 바뀌었으면 이 자리는 이미 비워졌고 새 물음이 채웁니다 —
     손대지 않습니다. 같은 환경인데 답이 다른 환경의 것이면 버리고 「안 물어봤다」로
     되돌립니다. */
  if (since !== generation()) return
  if (posted[0] === 'stale' || posted[1] === 'stale' || posted[2] === 'stale') {
    discard(code)
    return
  }
  const price = failed(posted[0].reply) ? posted[0].reply : priceOf(posted[0].reply, code)
  const [book, bars] = [posted[1].reply, posted[2].reply]
  const environment = posted[0].environment ?? posted[1].environment ?? posted[2].environment
  notePaper(route, price)
  /* **모의투자라 현재가를 못 받는 것은 호가·분봉과 무관합니다.** 호가와 분봉은 제
     조회의 답대로 세우고 현재가 자리만 비웁니다 — 주간 값이나 마감값으로 채우면
     지금 값으로 읽힙니다. */
  const paper = price === 'paper'

  /* **현재가를 못 받으면 나머지가 와도 실패입니다.** 값이 서는 자리 대부분이
     현재가에서 나오고, 호가만 있는 헤더는 무엇을 보는 화면인지 말하지
     못합니다. 셋 중 하나라도 거절이면 거절로 적습니다 — 다시 눌러도 같은
     답이 오는 쪽이 사용자가 할 일을 정합니다. */
  const replies = [price, book, bars]
  const rejected = replies.some((reply) => reply === 'rejected' || reply === 'paper')

  /* **온 값이 부른 종목의 것인지 봅니다.** 응답에 종목코드가 실려 오므로 부른
     것과 대 봅니다. 다르면 그 값은 다른 종목의 값이고, 이름과 숫자가 어긋난
     화면에서 주문 단추가 서면 **다른 종목을 주문합니다.** 그런 응답은 버리고
     못 받은 것으로 둡니다 — 화면이 값을 안 그리는 쪽이 안전합니다.
     **세 응답을 따로 봅니다** — 카드마다 제 호출이 있으니 카드마다 제 상태를
     가집니다. 현재가가 와도 호가만 다른 종목이면 호가만 버립니다. 종목코드를
     안 싣는 응답은 대 볼 것이 없어 그대로 씁니다. */
  const wrongSymbol = (reply: { code?: string } | QuoteFailure, what: string): boolean => {
    if (failed(reply)) return false
    const answered = (reply.code ?? '').trim()
    if (answered === '' || answered === code) return false
    if (import.meta.env.DEV) {
      console.warn(`[시세] ${what} — 요청 ${code}, 응답 ${answered}. 다른 종목이라 버립니다.`)
    }
    return true
  }

  const mismatched = wrongSymbol(price, '현재가')
  const wrongBook = wrongSymbol(book, '호가')
  const wrongBars = wrongSymbol(bars, '분봉')

  if ((failed(price) && !paper) || mismatched) {
    /* 받아 둔 값이 있으면 남깁니다 — 낡은 값이지 틀린 값이 아닙니다. 그 경우
       화면은 값과 함께 「받지 못했습니다」를 세웁니다. 처음부터 못 받았으면
       세울 값이 없으므로 실패입니다. */
    const held = entries.get(code)
    const hadValues = held?.price != null
    announce(code, {
      ...(hadValues ? held : EMPTY),
      status: hadValues ? 'ready' : 'failed',
      /* 셋을 다 불러 본 뒤라, 실패했어도 「물어봤다」입니다 — 화면을 다시
         열었다고 자동으로 또 부르지 않습니다. 다시 부르는 것은 「다시」뿐입니다. */
      full: true,
      failure: rejected ? 'rejected' : 'retry',
      failureText: posted.map((one) => (one === 'stale' ? '' : (one.detail ?? ''))).find((text) => text !== '') ?? '',
      bookFailure: null,
    } as QuoteEntry)
    return
  }

  announce(code, {
    status: 'ready',
    full: true,
    price: paper ? null : price,
    /* 일봉은 따로 받는 값이라 지금 담긴 것을 그대로 둡니다(이 조회가 나가 있는
       동안 왔을 수 있습니다). */
    daily: entries.get(code)?.daily ?? null,
    dailyStatus: entries.get(code)?.dailyStatus ?? 'idle',
    /* 일봉에 접힌 봉도 일봉과 함께 둡니다 — 이 조회가 바꾸는 것은 분봉입니다. */
    dailyLive: entries.get(code)?.dailyLive ?? [],
    /* **카드마다 제 호출이 있으니 카드마다 제 상태를 가집니다.** 현재가가
       왔는데 호가가 다른 종목이면 호가만 버립니다 — 받은 것은 보이고 안 온
       것만 빕니다. 버린 자리에 「확인 못 함」 같은 표시는 안 답니다. */
    book: failed(book) || wrongBook ? null : ladderOf(book),
    bars: failed(bars) || wrongBars ? null : bars.bars,
    /* 조회 봉을 새로 받았으니 그 위에 접었던 봉은 비웁니다 — 새 조회 봉이 그
       분까지 담고 있고, 겹침은 첫 체결 뒤 꼬리 재조회가 맞춥니다. */
    live: [],
    /* 이어 받아 둔 앞쪽도 비웁니다 — 새 조회 봉이 어디서 시작하는지 모르는 채로
       앞에 붙이면 사이가 비거나 겹칩니다. 왼쪽 끝에 닿으면 다시 받습니다. */
    history: { bars: [], before: '', done: false, short: false, loading: false },
    failure: paper ? 'paper' : null,
    /* 호가가 모의투자라 못 받는다는 답이면 호가 카드는 거절과 같은 얼굴입니다 —
       다시 불러도 같은 답입니다. */
    bookFailure: failed(book) ? (book === 'paper' ? 'rejected' : book) : wrongBook ? 'retry' : null,
    /* 예상체결가는 호가 답이 싣습니다. 호가를 못 받았으면 없는 것으로 둡니다 —
       낡은 동시호가 값이 남는 쪽이 더 나쁩니다. */
    expectedPrice: failed(book) || wrongBook ? null : (book.expectedPrice ?? null),
    /* 조회를 다시 받아도 실시간으로 쌓인 체결은 지우지 않습니다 — 그것은
       조회가 준 값이 아니라 그 사이에 실제로 일어난 일입니다. */
    trades: held?.trades ?? [],
    at: stamp(),
    environment,
    session: route.session,
  })
  tailPatched.delete(code)
  tailFlying.delete(code)
  if (!paper || !failed(book)) noteQuoteArrival()
  reconcileSession(code)
}

/** **현재가만** 받습니다. 값 몇 자리만 보이는 자리가 씁니다.
 *
 *  홈 관심종목은 이름·현재가·전일대비만 보이는데, 여기서 셋(현재가·호가·분봉)을
 *  다 부르면 여섯 종목에 **열여덟 번**이라 시세 예산(초당 열)을 한 번에
 *  넘깁니다. 여섯 번이면 그 안에 듭니다.
 *
 *  **이미 셋을 받아 둔 종목은 그 값을 그대로 씁니다** — 주문 화면에서 보던
 *  종목을 홈에서 다시 부를 일이 없습니다.
 */
export async function loadPrice(code: string, options?: { force?: boolean }): Promise<void> {
  if (!askable(code)) return
  const held = entries.get(code)
  if (!options?.force && (held?.full || held?.price != null)) return
  const since = generation()
  /* 이미 받는 중이면 같은 요청을 겹쳐 내지 않습니다. */
  if (flyingPrice.get(code) === since || flyingFull.get(code) === since) return
  flyingPrice.set(code, since)

  announce(code, { ...(held ?? EMPTY), status: 'loading', failure: null, failureText: '' })

  const route = routeOf(code, today())
  const posted = priceShut(route)
    ? paperShut<PriceReply | { quotes?: PriceReply[] }>()
    : await post<PriceReply | { quotes?: PriceReply[] }>(route.price.path, route.price.body, since)
  if (flyingPrice.get(code) === since) flyingPrice.delete(code)
  if (since !== generation()) return
  if (posted === 'stale') {
    discard(code)
    return
  }
  const price = failed(posted.reply) ? posted.reply : priceOf(posted.reply, code)
  notePaper(route, price)

  /* 모의투자라 못 받는다는 답이면 값 자리를 비웁니다 — 받아 둔 주간 값을 남기면
     지금 값으로 읽힙니다. 함께 받아 둔 호가·분봉은 그대로 둡니다. */
  if (price === 'paper') {
    announce(code, {
      ...(entries.get(code) ?? EMPTY),
      status: 'ready',
      price: null,
      failure: 'paper',
      session: route.session,
    })
    return
  }

  /* **온 값이 부른 종목의 것인지 봅니다.** 저장해 둔 응답으로 도는 개발
     서버에서는 다른 종목의 기록이 올 수 있고, 그 값이 타일에 서면 이름과
     숫자가 어긋난 채로 눌려 다른 종목이 열립니다. */
  const answered = failed(price) ? '' : (price.code ?? '').trim()
  const mismatched = answered !== '' && answered !== code
  if (import.meta.env.DEV && mismatched) {
    console.warn(`[시세] 현재가 — 요청 ${code}, 응답 ${answered}. 다른 종목이라 버립니다.`)
  }

  if (failed(price) || mismatched) {
    const kept = entries.get(code)
    const hadValues = kept?.price != null
    announce(code, {
      ...(hadValues ? kept : EMPTY),
      status: hadValues ? 'ready' : 'failed',
      failure: price === 'rejected' ? 'rejected' : 'retry',
      failureText: posted.detail ?? '',
    } as QuoteEntry)
    return
  }

  announce(code, {
    ...(entries.get(code) ?? EMPTY),
    status: 'ready',
    price,
    failure: null,
    failureText: '',
    at: stamp(),
    environment: posted.environment,
    session: route.session,
  })
  noteQuoteArrival()
  reconcileSession(code)
}

/** **분봉만** 받습니다. 곡선 하나를 그리는 자리가 씁니다.
 *
 *  값 하나에 조회 하나입니다 — 곡선을 쓰는 자리가 현재가까지 다시 부르면 같은
 *  값을 두 번 받습니다. 이미 받아 둔 봉이 있으면 그대로 씁니다 — **다시 받는 것은
 *  `force` 뿐입니다**(홈을 다시 열거나 새로고침할 때). 받아 둔 봉이 있으면
 *  새 봉이 올 때까지 그대로 서 있고, 같은 종목을 겹쳐 부르지 않습니다.
 */
export async function loadBars(code: string, options?: { force?: boolean }): Promise<void> {
  if (!askable(code)) return
  const held = entries.get(code)
  if (!options?.force && held?.bars != null) return
  const since = generation()
  if (flyingBars.get(code) === since) return
  flyingBars.set(code, since)

  const route = routeOf(code, today())
  const posted = await post<{ code?: string; bars: BarReply[] }>(
    route.bars.path,
    route.bars.body,
    since,
  )
  if (flyingBars.get(code) === since) flyingBars.delete(code)
  if (posted === 'stale') return
  const reply = posted.reply

  if (failed(reply)) return

  /* 다른 종목의 봉이면 버립니다 — 곡선은 이름 옆에 서므로, 다른 종목의 모양이
     그 이름의 흐름으로 읽힙니다. */
  const answered = (reply.code ?? '').trim()
  if (answered !== '' && answered !== code) {
    if (import.meta.env.DEV) {
      console.warn(`[시세] 분봉 — 요청 ${code}, 응답 ${answered}. 다른 종목이라 버립니다.`)
    }
    return
  }

  announce(code, {
    ...(entries.get(code) ?? EMPTY),
    bars: reply.bars,
    live: [],
    history: { bars: [], before: '', done: false, short: false, loading: false },
  })
  tailPatched.delete(code)
  tailFlying.delete(code)
}

/** 한 번 당긴 결과. **「새 봉이 없다」와 「못 받았다」는 다릅니다** — 앞엣것은 더
 *  당겨 볼 만하고 뒤엣것은 같은 자리에서 또 물어도 같은 답이 옵니다. 그 갈래를
 *  안 내면 차트가 둘을 못 가려, 못 받는 종목에서 왼쪽 끝에 닿을 때마다 같은
 *  거절을 부릅니다.
 *
 *  **몇 개가 붙었는지는 안 냅니다.** 차트에 넘길 봉은 「이 판에 아직 안 실린
 *  것」이라 저장소를 보고 세는 것이지, 이 함수가 센 수로 자를 것이 아닙니다. */
export interface HistoryStep {
  /** 서버가 거절했거나 연결이 끊겼나. */
  failed: boolean
}

/** 분봉을 **한 영업일씩 앞으로** 이어 받습니다. 차트가 왼쪽 끝에 닿을 때마다
 *  한 번 부릅니다.
 *
 *  **한 번 불러도 여러 영업일을 물을 수 있습니다.** 휴장일이 빈 영업일로 오고
 *  (휴장일 달력이 없습니다) 이미 아는 날이 섞일 수도 있어, 봉이 실제로 붙을
 *  때까지 뒤로 갑니다 — 빈 날이 잇따라 다섯이면 더 없는 것으로 보고 멈춥니다.
 *
 *  **어디까지 받았는지는 서버가 답한 값(`before`)을 그대로 되돌려 보냅니다.**
 *  국내는 그 값이 영업일이고 해외는 서버가 적어 둔 이어받기 값인데, 화면은
 *  어느 쪽이든 속을 안 보고 그대로 실어 보냅니다.
 *
 *  받은 봉은 `history` 에 담고 **`bars` 는 안 건드립니다** — 차트가 조회 봉
 *  참조의 변화로 판을 다시 세워, 이어 받을 때마다 보던 자리를 잃습니다. */
export async function loadHistory(code: string): Promise<HistoryStep> {
  const none = { failed: false }
  if (!askable(code)) return none
  const route = routeOf(code, today()).history
  /* 길이 비어 있으면 부를 수 없는 자리입니다(`routeOf`) — 거래소 코드를 못
     받은 해외 품목이 그렇습니다. 지어낸 길로 물으면 남의 거래소 답이 옵니다. */
  if (!route.path) return { failed: true }
  const first = entries.get(code)
  /* 이을 바탕이 없으면 이을 자리도 없습니다. */
  if (!first?.bars) return none
  const walk = first.history
  if (walk.loading || walk.done) return none

  const since = generation()
  announce(code, { ...first, history: { ...walk, loading: true } })
  const stop = (next: Partial<History>) => {
    const held = entries.get(code)
    if (held) announce(code, { ...held, history: { ...held.history, ...next, loading: false } })
  }

  let before = walk.before
  let short = walk.short
  let done = false
  let empty = 0
  let fresh: Bar[] = []
  /* 이번에 물어 본 영업일 수와, 바로 앞 답이 말한 영업일. 같은 영업일이 이어
     오면 앞으로 간 것이 아니라 그 날을 마저 받는 것이라 날 수로 안 셉니다. */
  let days = 0
  let lastDay = ''

  for (
    let call = 0;
    call < HISTORY_MAX_CALLS && days < HISTORY_MAX_DAYS && fresh.length === 0 && !done;
    call += 1
  ) {
    const posted = await post<HistoryReply>(route.path, { ...route.body, before }, since)
    /* 그 사이 환경이 바뀌었으면 이 자리는 이미 비워졌고 새 물음이 채웁니다.
       그래도 **받는 중 표시는 여기서 내립니다** — 다른 자리의 뒷정리에 기대면,
       그 자리가 안 도는 경우에 이어 받기가 영영 안 열립니다. */
    if (posted === 'stale' || since !== generation()) {
      stop({})
      return none
    }
    const reply = posted.reply
    if (failed(reply)) {
      stop({})
      return { failed: true }
    }
    const answered = String(reply.code ?? '').trim()
    if (answered !== '' && answered !== code) {
      if (import.meta.env.DEV) {
        console.warn(`[시세] 앞 분봉 — 요청 ${code}, 응답 ${answered}. 다른 종목이라 버립니다.`)
      }
      stop({})
      return { failed: true }
    }
    /* 덜 받았을 수 있다는 표시는 **적어만 둡니다** — 멈출지는 빈 날 수가 정합니다. */
    if (reply.partial) short = true

    /* 어느 영업일의 답인가. **안 실어 주는 서버에서는 새 날로 셉니다** — 그래야
       한 장이 곧 한 영업일인 자리에서 지금까지와 똑같이 움직입니다. */
    const day = String(reply.businessDay ?? '')
    if (day === '' || day !== lastDay) days += 1
    lastDay = day

    /* 더 갈 자리를 안 주면 여기까지입니다. **그래도 이 답의 봉은 받습니다** —
       창의 아래끝은 「마지막 한 벌과 함께」 옵니다. 멈출 자리라고 그 봉을
       버리면 가장 오랜 하루가 영영 안 서고, 다시 당겨도 같은 자리입니다. */
    const answeredBefore = String(reply.before ?? '')
    if (answeredBefore === '' || answeredBefore === before) done = true
    else before = answeredBefore

    const came = Array.isArray(reply.bars) ? reply.bars : []
    if (came.length === 0) {
      empty += 1
      if (empty >= HISTORY_EMPTY_DAYS) done = true
      continue
    }
    /* 봉이 온 날은 **빈 날이 아닙니다** — 이미 아는 날이어도 그렇습니다. */
    empty = 0
    const held = entries.get(code)
    const known = new Set([...(held?.history.bars ?? []), ...(held?.bars ?? [])].map((bar) => bar.timestamp))
    fresh = came.filter((bar) => !known.has(bar.timestamp)).sort((a, b) => a.timestamp - b.timestamp)
  }

  const held = entries.get(code)
  if (!held) return none
  announce(code, {
    ...held,
    history: {
      bars: [...fresh, ...held.history.bars],
      before,
      done,
      short,
      loading: false,
    },
  })
  return { failed: false }
}

/** 앞 분봉 답. `nextKey` 는 늘 빈 값이라 안 읽습니다 — 더 과거는 `before` 로 갑니다. */
interface HistoryReply {
  code?: string
  bars?: BarReply[]
  /** 다음 물음에 **그대로 실어 보낼 값**입니다. 속을 안 봅니다 — 국내는
   *  영업일이고 해외는 서버가 어디까지 냈는지 적어 둔 값입니다. */
  before?: string
  /** 이 답이 어느 영업일의 것인가. 같은 영업일이 이어 오는지 보는 데 씁니다. */
  businessDay?: string
  /** 이 영업일을 다 받았다고 보증하지 못함. */
  partial?: boolean
}

/** **일봉만** 받습니다. 세션과 무관한 주간 일봉입니다. 이미
 *  받아 둔 것은 그대로 씁니다 — 하루에 한 번 넘어가는 값이라 다시 볼 일이 없고,
 *  `force` 는 사용자의 「다시」뿐입니다. */
export async function loadDailyBars(code: string, options?: { force?: boolean }): Promise<void> {
  if (!askable(code)) return
  const held = entries.get(code)
  if (!options?.force && held?.daily != null) return
  const since = generation()
  if (flyingDaily.get(code) === since) return
  flyingDaily.set(code, since)
  announce(code, { ...(held ?? EMPTY), dailyStatus: 'loading' })

  const route = routeOf(code, today())
  const posted = await post<{ code?: string; bars: BarReply[] }>(
    route.daily.path,
    route.daily.body,
    since,
  )
  if (flyingDaily.get(code) === since) flyingDaily.delete(code)
  if (posted === 'stale' || since !== generation()) return
  const reply = posted.reply
  const kept = entries.get(code) ?? EMPTY

  if (failed(reply)) {
    announce(code, { ...kept, dailyStatus: 'failed' })
    return
  }
  const answered = (reply.code ?? '').trim()
  if (answered !== '' && answered !== code) {
    if (import.meta.env.DEV) {
      console.warn(`[시세] 일봉 — 요청 ${code}, 응답 ${answered}. 다른 종목이라 버립니다.`)
    }
    announce(code, { ...kept, dailyStatus: 'failed' })
    return
  }
  /* 조회 일봉을 새로 받았으니 그 위에 접었던 봉은 비웁니다 — 새 조회 봉이 그
     날까지 담고 있습니다. */
  announce(code, { ...kept, daily: reply.bars, dailyLive: [], dailyStatus: 'ready' })
}

/** 일봉 차트가 구독합니다. 아직 없으면 받습니다. */
export function useDailyBars(code: string): { bars: BarReply[] | null; status: QuoteEntry['dailyStatus'] } {
  const entry = useSyncExternalStore(
    subscribeQuotes,
    () => (code ? quoteEntry(code) : EMPTY),
    () => EMPTY,
  )
  const settled = useEnvironmentSettled()
  const missing = entry === EMPTY
  useEffect(() => {
    if (settled) void loadDailyBars(code)
  }, [code, settled, missing])
  return { bars: entry.daily, status: entry.dailyStatus }
}

/** 일봉을 다시 받습니다. 못 받은 차트의 「다시」가 부릅니다. */
export function retryDailyBars(code: string): void {
  void loadDailyBars(code, { force: true })
}

/** 곡선이 있는 자리가 분봉을 구독합니다. 값과 따로 오므로 곡선만 늦게 섭니다 —
 *  숫자가 먼저 서고 모양이 뒤따르는 것은 괜찮습니다. */
export function useBars(code: string): BarReply[] | null {
  const entry = useSyncExternalStore(
    subscribeQuotes,
    () => (code ? quoteEntry(code) : EMPTY),
    () => EMPTY,
  )

  const settled = useEnvironmentSettled()
  const missing = entry === EMPTY
  useEffect(() => {
    if (settled) void loadBars(code)
  }, [code, settled, missing])

  return entry.bars
}

/** 값을 담는 자리가 조회를 내도 되는 때인지. 환경을 아는 상태와, 서버도 모른다고
 *  답한 상태에서만 냅니다 — 뒤는 서버가 제 환경으로 답하는 참값이고, 배지가
 *  모른다고 말하며 주문은 막혀 있어 값이 서도 거짓이 아닙니다. 모르는 채로 부르고
 *  알게 된 뒤 또 부르면 같은 값을 두 번 받습니다. */
function useEnvironmentSettled(): boolean {
  const { status } = useEnvironment()
  return status === 'ready' || status === 'failed'
}

/** 현재가만 다시 받습니다. 타일의 「다시」가 부릅니다. */
export function retryPrice(code: string): void {
  void loadPrice(code, { force: true })
}

/** 값 몇 자리만 보이는 자리가 한 종목을 구독합니다.
 *
 *  **빈 코드를 주면 아무것도 안 부릅니다** — 아직 종목을 안 고른 자리가
 *  그렇습니다. 부르는 쪽에서 조건을 따지느라 훅을 건너뛰면 훅 순서가
 *  바뀌므로, 조건은 코드로 넘깁니다.
 */
export function usePrice(code: string): QuoteEntry {
  const entry = useSyncExternalStore(
    subscribeQuotes,
    () => (code ? quoteEntry(code) : EMPTY),
    () => EMPTY,
  )

  /* 담긴 값이 지워져 「안 물어봤다」로 돌아가면(환경이 바뀜) 다시 부릅니다. */
  const settled = useEnvironmentSettled()
  const missing = entry === EMPTY
  useEffect(() => {
    if (settled) void loadPrice(code)
    else markLoading(code)
  }, [code, settled, missing])

  return entry
}

/** 한 종목의 시세를 구독합니다. 코드가 바뀌면 새 종목을 받습니다.
 *
 *  **빈 코드를 주면 아무것도 안 부릅니다.** 아직 종목을 안 고른 자리(행사가를
 *  안 고른 옵션)가 그렇습니다 — 부르는 쪽에서 조건을 따지느라 훅을 건너뛰면
 *  훅 순서가 바뀌므로, 조건은 코드로 넘깁니다.
 */
export function useQuoteEntry(code: string): QuoteEntry {
  const entry = useSyncExternalStore(
    subscribeQuotes,
    () => (code ? quoteEntry(code) : EMPTY),
    () => EMPTY,
  )

  /* 담긴 값이 지워져 「안 물어봤다」로 돌아가면(환경이 바뀜) 다시 부릅니다. */
  const settled = useEnvironmentSettled()
  const missing = entry === EMPTY
  useEffect(() => {
    if (settled) void loadQuote(code)
    else markLoading(code)
  }, [code, settled, missing])

  return entry
}

/* 환경이 바뀌면 전부 지웁니다 — 다른 환경의 값이고, 실시간으로 쌓인 체결도 그
   연결의 것입니다. 몰랐다가 알게 된 것이면 이름이 다른 값만 지웁니다 — 이름을
   알게 된 것이지 값이 바뀐 것이 아닙니다. 받는 중인 자리는 그대로 둡니다. */
onEnvironmentChange((change) => {
  if (change.kind === 'switched') {
    entries.clear()
    paperNightShut = null
  } else {
    for (const [code, entry] of entries) {
      if (entry.status !== 'loading' && entry.environment !== change.active) entries.delete(code)
    }
  }
  for (const code of [...tailPatched, ...tailFlying.keys()]) {
    if (!entries.has(code)) {
      tailPatched.delete(code)
      tailFlying.delete(code)
    }
  }
  for (const listener of listeners) listener()
})

/** 값이 하나도 없는 현재가. 조회로 현재가를 못 받은 종목에 실시간 체결이 첫 값을
 *  세울 때의 바탕입니다 — 체결이 말하지 않는 칸은 빈 채로 두어 「—」로 섭니다. */
function blankPrice(code: string): PriceReply {
  return {
    code,
    name: '',
    last: null,
    change: null,
    changePct: null,
    open: null,
    high: null,
    low: null,
    volume: null,
    turnover: null,
    openInterest: null,
    openInterestChange: null,
    upperLimit: null,
    lowerLimit: null,
    spot: null,
    spotChange: null,
    lifeHigh: null,
    lifeLow: null,
    theory: null,
    disparity: null,
    iv: null,
    basisTheory: null,
    basisActual: null,
    lastTradingDay: null,
    daysLeft: null,
    multiplier: null,
  }
}

/** 실시간으로 온 값을 얹습니다.
 *
 *  **받은 항목만 갈아 끼웁니다.** 실시간이 보내는 것은 `Quote` 전체가 아니라
 *  실시간이 말할 수 있는 항목뿐이라, 전체를 보내는 것처럼 덮으면 조회와
 *  마스터가 준 이름·계약 크기·잔존일수가 지워집니다.
 *
 *  **아직 조회로 채우지 않은 종목에는 안 얹습니다.** 얹을 바탕이 없어 반쪽
 *  값이 서고, 그 화면은 무엇이 빠졌는지 말할 수 없습니다.
 */
export function applyRealtimeQuote(
  code: string,
  patch: Partial<PriceReply> & { expectedPrice?: number | null },
  trades: TradeTick[],
): void {
  const held = entries.get(code)
  if (!held) return
  /* 모의투자라 현재가를 조회로 못 받은 종목은 **실시간 체결이 바탕이 됩니다** —
     체결가가 오면 그 값이 서고 「받을 수 없습니다」는 걷힙니다. 체결가가 없는
     알림으로는 세우지 않습니다. */
  const fromTick = !held.price && held.failure === 'paper' && typeof patch.last === 'number'
  if (!held.price && !fromTick) return
  const base = held.price ?? blankPrice(code)

  const next = trades.length > 0 ? [...trades, ...held.trades].slice(0, TRADE_KEEP) : held.trades
  /* 조회 봉이 있는 종목만 봉을 잇습니다 — 현재가만 받아 둔 자리(홈)는 봉이 없어
     접을 바탕이 없습니다. */
  const live = held.bars ? foldTrades(held.bars, held.live, trades) : held.live
  /* 일봉도 같은 체결로 잇습니다 — 오늘 봉이 조회한 순간에 멈춰 있으면, 분봉은
     흐르는데 일봉만 낡은 종가를 말합니다. */
  const dailyLive = held.daily ? foldDaily(held.daily, held.dailyLive, trades) : held.dailyLive
  /* 예상체결가는 다른 항목과 규칙이 다릅니다 — 다른 칸은 「없으면 손대지 말 것」
     이지만 이 칸은 **`null` 이 「지워라」** 입니다(동시호가 값이 접속매매 뒤에
     남지 않게). 칸이 아예 없을 때만 그대로 둡니다. 현재가 값들에는 섞지 않습니다. */
  const { expectedPrice, ...pricePatch } = patch
  const expected = 'expectedPrice' in patch ? (expectedPrice ?? null) : held.expectedPrice
  announce(code, {
    ...held,
    price: { ...base, ...pricePatch },
    failure: fromTick ? null : held.failure,
    expectedPrice: expected,
    trades: next,
    live,
    dailyLive,
    at: stamp(),
  })

  if (!held.bars || !trades.some((trade) => trade.timestamp !== undefined)) return
  const flying = tailFlying.get(code)
  if (flying) flying.trades.push(...trades)
  else if (!tailPatched.has(code)) void patchTail(code)
}

/** 체결을 **일봉**에 접습니다. `foldTrades` 와 같은 꼴입니다 — 조회 일봉은 안
 *  바꾸고 새 `dailyLive` 를 돌려줍니다. 마지막 일봉과 같은 날이면 그 봉을 늘린
 *  사본을 세우고, 날이 바뀌었으면 새 봉을 세웁니다.
 *
 *  **주간 체결만 접습니다.** 이 일봉은 주간 일봉이고 야간은 다음 영업일의 다른
 *  세션이라, 야간 체결을 여기 더하면 그날 고가·저가가 거래소가 내는 일봉과
 *  갈립니다. 시간표를 아직 못 받아 주간인지 모르는 체결도 안 접습니다 — 틀리게
 *  접어도 화면에서는 표가 안 납니다.
 *
 *  **바탕이 없으면 안 세웁니다.** 조회 일봉이 한 봉도 없으면 접을 자리가 없고,
 *  체결 하나로 지어낸 봉 하나가 그 종목의 일봉 전부로 섭니다. */
export function foldDaily(
  daily: readonly Bar[],
  live: readonly Bar[],
  trades: readonly TradeTick[],
): Bar[] {
  const next = [...live]
  /* 날 가름은 한국 달력입니다. 국내 주간장의 봉이라, 이 PC 의 시간대로 가르면
     한국의 하루가 두 날로 쪼개집니다. */
  const dayOf = kstDay
  const dayStart = kstDayStart
  for (const trade of trades) {
    if (trade.timestamp === undefined) continue
    if (inDomesticDay(trade.timestamp) !== true) continue
    const tail = next[next.length - 1] ?? daily[daily.length - 1] ?? null
    if (!tail) continue
    const day = dayOf(trade.timestamp)
    const tailDay = dayOf(tail.timestamp)
    if (day < tailDay) continue
    if (day === tailDay) {
      const grown: Bar = {
        ...tail,
        high: Math.max(tail.high, trade.price),
        low: Math.min(tail.low, trade.price),
        close: trade.price,
        volume: tail.volume + trade.quantity,
      }
      if (next.length > 0) next[next.length - 1] = grown
      else next.push(grown)
      continue
    }
    next.push({
      timestamp: dayStart(trade.timestamp),
      open: trade.price,
      high: trade.price,
      low: trade.price,
      close: trade.price,
      volume: trade.quantity,
    })
  }
  return next
}

/** 체결을 봉에 접습니다. **순수 함수**입니다 — 조회 봉은 안 바꾸고 새 `live` 를
 *  돌려줍니다.
 *
 *  봉 열쇠는 체결 시각을 분으로 내린 것입니다. 마지막 봉(접은 봉이 있으면 그 끝,
 *  없으면 조회 봉의 끝)과 견주어 **앞이면 버리고, 같으면 그 봉을 늘리고(고가·저가·
 *  종가 갱신, 거래량 더함), 뒤면 새 봉**(시가 = 그 체결)입니다. 조회 봉의 마지막
 *  분과 같은 열쇠면 조회 봉은 그대로 두고 늘린 사본을 `live` 의 첫 봉으로 세웁니다
 *  — 차트는 같은 열쇠를 덮어 그립니다. 시각 없는 체결은 건너뜁니다. 체결 없는
 *  분에 빈 봉을 세우지 않습니다 — 조회 봉에도 빈 분은 없습니다. `patch.volume`
 *  은 당일 누적이라 봉에 더하지 않습니다. */
export function foldTrades(bars: readonly Bar[], live: readonly Bar[], trades: readonly TradeTick[]): Bar[] {
  const next = [...live]
  const last = (): Bar | null => next[next.length - 1] ?? bars[bars.length - 1] ?? null
  for (const trade of trades) {
    if (trade.timestamp === undefined) continue
    const key = Math.floor(trade.timestamp / MINUTE_MS) * MINUTE_MS
    const tail = last()
    if (tail && key < tail.timestamp) continue
    if (tail && key === tail.timestamp) {
      const grown: Bar = {
        ...tail,
        high: Math.max(tail.high, trade.price),
        low: Math.min(tail.low, trade.price),
        close: trade.price,
        volume: tail.volume + trade.quantity,
      }
      if (next.length > 0) next[next.length - 1] = grown
      else next.push(grown)
      continue
    }
    next.push({
      timestamp: key,
      open: trade.price,
      high: trade.price,
      low: trade.price,
      close: trade.price,
      volume: trade.quantity,
    })
  }
  return next
}

/** 첫 체결이 온 뒤 **조회 봉의 마지막 두 분을 한 번 다시 받아 덮습니다.**
 *
 *  조회 응답은 진행 중인 분까지 담는데, 그 분의 체결이 실시간으로도 오면 같은
 *  체결이 두 번 더해질 수 있습니다. 서버 봉으로 그 구간을 덮고, 재조회를 낸 뒤에
 *  온 체결만 그 위에 다시 접습니다. 조회 봉 한 벌에 한 번뿐이고, 못 받으면 그대로
 *  둡니다 — 다음 조회(끊겼다 붙을 때 등)가 다시 맞춥니다. */
async function patchTail(code: string): Promise<void> {
  const held = entries.get(code)
  if (!held?.bars?.length) return
  tailPatched.add(code)
  const issuedAt = Date.now()
  tailFlying.set(code, { issuedAt, trades: [] })
  const since = generation()
  const startKey = held.bars[held.bars.length - 1].timestamp - MINUTE_MS
  const route = routeOf(code, today())
  const posted = await post<{ code?: string; bars: BarReply[] }>(
    route.bars.path,
    { ...route.bars.body, strt_tm: clock6(startKey), ed_tm: '235959' },
    since,
  )
  const flown = tailFlying.get(code)
  tailFlying.delete(code)
  if (posted === 'stale' || since !== generation() || !flown) return
  const reply = posted.reply
  if (failed(reply)) return
  const answered = (reply.code ?? '').trim()
  if (answered !== '' && answered !== code) return

  const kept = entries.get(code)
  if (!kept?.bars) return
  const merged = mergeTail(kept.bars, kept.live, reply.bars, startKey, flown.trades, issuedAt)
  if (merged) announce(code, { ...kept, ...merged })
}

/** 꼬리 재조회의 답을 조회 봉·접은 봉에 덮습니다. **순수 함수**입니다.
 *
 *  서버가 요청 구간보다 넓게 답해도(저장해 둔 응답으로 도는 재생) 시작 열쇠부터만
 *  덮습니다. 덮인 구간(≤ 서버 마지막 봉)의 접은 봉은 버리고 서버 봉으로 갈아 끼우되,
 *  재조회를 낸 뒤에 온 체결 중 **그 구간에 드는 것만** 서버 봉 위에 다시 접습니다 —
 *  낸 뒤 체결은 서버 봉에 없고, 뒤 열쇠의 접은 봉은 재조회가 나가 있는 동안에도
 *  이미 접혀 있어 또 접으면 거래량이 두 배가 됩니다. 그 봉들은 그대로 뒤에 잇습니다.
 *  낸 뒤~서버가 봉을 만든 순간 사이의 체결은 서버 봉에도 있을 수 있어 그 창만큼은
 *  겹칠 수 있습니다(왕복 한 번 길이). 서버가 그 구간 봉을 안 주면 `null` 입니다. */
export function mergeTail(
  bars: readonly Bar[],
  live: readonly Bar[],
  answered: readonly Bar[],
  startKey: number,
  flown: readonly TradeTick[],
  issuedAt: number,
): { bars: Bar[]; live: Bar[] } | null {
  const fresh = answered.filter((bar) => bar.timestamp >= startKey)
  if (fresh.length === 0) return null
  const next = [...bars.filter((bar) => bar.timestamp < startKey), ...fresh]
  const lastFresh = next[next.length - 1].timestamp
  const later = flown.filter(
    (trade) =>
      trade.timestamp !== undefined &&
      trade.timestamp > issuedAt &&
      Math.floor(trade.timestamp / MINUTE_MS) * MINUTE_MS <= lastFresh,
  )
  const grown = foldTrades(next, [], later)
  return { bars: next, live: [...grown, ...live.filter((bar) => bar.timestamp > lastFresh)] }
}

/** 받은 호가를 담을 모양으로 맞춥니다. **매수·매도 칸이 빠져 오면 빈 목록으로**
 *  둡니다 — 화면은 두 칸을 목록으로 믿고 읽어, 칸 하나가 빠지면 화면 전체가
 *  멈춥니다. 조회로 온 것과 실시간으로 온 것을 다 여기서 맞추므로 읽는 자리
 *  전부가 함께 안전합니다. */
function ladderOf(book: BookReply): BookReply {
  return {
    ...book,
    asks: Array.isArray(book.asks) ? book.asks : [],
    bids: Array.isArray(book.bids) ? book.bids : [],
  }
}

/** 실시간으로 온 호가. 사다리는 마지막 것만 있으면 되므로 통째로 바꿉니다. */
export function applyRealtimeBook(code: string, book: BookReply): void {
  const held = entries.get(code)
  /* 모의투자라 현재가만 못 받은 종목도 호가는 제 답대로 받습니다. */
  if (!held || (!held.price && held.failure !== 'paper')) return
  /* 국내 호가는 예상체결가 칸을 늘 싣습니다 — 값이면 세우고 `null` 이면 지웁니다.
     칸이 없는 해외 호가에서는 세울 것이 없어 빈 채입니다. */
  announce(code, {
    ...held,
    book: ladderOf(book),
    bookFailure: null,
    expectedPrice: book.expectedPrice ?? null,
    at: stamp(),
  })
}

/** 다시 받습니다. 실패한 카드의 「다시 시도」가 부릅니다. */
export function retryQuote(code: string): void {
  void loadQuote(code, { force: true })
}

/** 마스터가 지은 종목에 받아 온 숫자를 얹습니다. 못 얹으면 `null` 입니다.
 *
 *  **신원은 마스터가, 숫자는 시세가 냅니다.** 응답에도 이름과 코드가 오지만
 *  거래소가 부르는 이름이라 화면이 쓰는 이름(만기가 붙은 것)과 다르고,
 *  자릿수·호가단위·통화는 아예 오지 않습니다.
 *
 *  **값이 없는 자리는 지웁니다.** 앞 종목 값이나 임시 값이 남으면 사용자는
 *  그것을 이 종목의 값으로 읽습니다.
 *
 *  **현재가가 비면 아무것도 안 세웁니다.** 나머지 칸은 비어도 세우고, 그 칸은
 *  `null` 로 넘겨 화면이 「—」로 그립니다 — 0 으로 채우면 「없다」가 「0 에
 *  거래됐다」로 읽힙니다. 그래서 아직 한 번도 안 거래된 종목도 시세가 섭니다.
 */
export function applyPrice(base: Quote, price: PriceReply): Quote | null {
  if (requiredOf(base.code).some((field) => price[field] === null)) return null

  return {
    ...base,
    last: price.last as number,
    /* 나머지는 비어 올 수 있고, 비면 화면이 그 칸만 「—」로 그립니다. */
    change: price.change,
    changePct: price.changePct,
    open: price.open,
    high: price.high,
    low: price.low,
    volume: price.volume,
    /* 해외에는 없는 셋 — 응답에 칸이 없어 `null` 로 오고, 화면이 「—」로 그립니다. */
    turnover: price.turnover,
    openInterest: price.openInterest,
    openInterestChange: price.openInterestChange,
    /* 만기와 계약 크기는 마스터도 압니다. 시세가 안 주면 마스터 값이 섭니다 —
       이 둘은 시세가 아니라 종목의 성질이라 「오늘 값이 없다」가 성립하지
       않습니다. */
    daysLeft: price.daysLeft ?? base.daysLeft,
    multiplier: price.multiplier ?? base.multiplier,
    upperLimit: price.upperLimit ?? undefined,
    lowerLimit: price.lowerLimit ?? undefined,
    spot: price.spot ?? undefined,
    spotChange: price.spotChange ?? undefined,
    lifeHigh: price.lifeHigh ?? undefined,
    lifeLow: price.lifeLow ?? undefined,
    theory: price.theory ?? undefined,
    disparity: price.disparity ?? undefined,
    iv: price.iv ?? undefined,
    basisTheory: price.basisTheory ?? undefined,
    basisActual: price.basisActual ?? undefined,
    lastTradingDay: price.lastTradingDay ?? undefined,
    /* 해외의 정산가. 안 오면 비워 둡니다 — 임시 값이 남으면 헤더가 지어낸
       정산가를 말합니다. 기준일도 같습니다. */
    settlement: price.settlement ?? undefined,
    prevSettlementDate: price.prevSettlementDate ?? undefined,
  }
}
