/** 실시간을 받는 자리 — 연결 하나와, 무엇을 보고 있는지의 목록.
 *
 *  **연결은 앱에 하나입니다.** 화면마다 열면 같은 종목에 구독이 여러 번 걸리고,
 *  서버가 한 번에 유지할 수 있는 자리(스물)가 그만큼 빨리 찹니다. 국내와 해외도
 *  이 하나로 함께 받습니다.
 *
 *  **화면은 「지금 보고 있는 것 전체」를 보냅니다.** 늘리고 줄이는 것이 아닙니다.
 *  줄이는 쪽을 한 번 빠뜨리면 아무도 안 보는 구독이 남고, 그런 자리는 새로
 *  고쳐도 안 없어집니다. 전체를 보내면 빠뜨릴 것이 없습니다.
 *  그래서 **여기가 목록을 모읍니다** — 카드가 각자 보내면 서로의 목록을 지웁니다.
 *
 *  **구독해도 첫 값이 오지 않습니다.** 다음 체결이 일어날 때까지 아무것도 안
 *  옵니다. 그래서 종목을 열 때는 조회로 한 번 채우고 그 위에 실시간을 덮습니다.
 *  끊겼다 다시 붙었을 때도 같아서, 서버가 「조회를 다시 부르라」고 알려 줍니다 —
 *  끊긴 동안의 변화는 실시간이 메워 주지 않습니다.
 */
import { useEffect, useSyncExternalStore } from 'react'

import {
  applyRealtimeBook,
  applyRealtimeQuote,
  quoteAsked,
  loadQuote,
  type BookReply,
} from './quotes'
import { applyOrderEvents, reloadAccountLists, type DepositMarket, type OrderEvent } from './account'
import { environmentSettled, noteActive } from './environment'
import { lastQuoteAt, noteQuoteArrival } from './lastQuote'
import { applySessionBroadcast, sessionEntry, type SessionState } from './session'
import { applyStrategyBroadcast, refillRuns } from './strategyStore'
import type { VerifyEvent, VerifyFill, VerifyOrder, VerifyRun } from './strategyRuns'
import { kstClock } from '../lib/kst'
import type { MarketContext } from '../lib/types'

/** 무엇을 받을 것인가. 셋이 같으면 같은 구독입니다. */
export interface Wish {
  context: MarketContext
  kind: 'quote' | 'book' | 'orders'
  /** 주문·체결 알림은 계좌 단위라 종목이 없습니다. */
  sym: string
  /** 자리가 모자랄 때 남을 순서. 큰 것이 남습니다. */
  priority?: number
}

/** 연결이 지금 어떤가.
 *
 *  `idle` 아직 안 붙음 · `connecting` 붙는 중 · `live` 값이 옴 ·
 *  `reconnecting` 끊겨서 다시 붙는 중 · `stopped` 끊김 ·
 *  `finished` 저장해 둔 자료가 끝남(개발 서버에서만). */
export type StreamState = 'idle' | 'connecting' | 'live' | 'reconnecting' | 'stopped' | 'finished'

/** 한 시장의 실시간 상태. **국내와 해외는 서버 쪽 연결이 따로라** 한쪽이 다시
 *  붙는 동안 다른 쪽은 그대로 받고 있습니다. */
export interface MarketFeed {
  state: StreamState
  /** 서버가 준 문구. 우리가 지어내지 않습니다. */
  detail: string
  /** 그 시장을 언제부터 받고 있는지(`HH:MM`). **구독해도 첫 값이 없어**, 붙은 뒤
   *  처음 체결이 일어날 때까지 화면이 빕니다. 그 빈 자리가 「고장」이 아니라
   *  「그때부터 아직 없음」으로 읽히려면 이 시각이 함께 서야 합니다. 다시 붙은
   *  시장만 새로 섭니다 — 다른 시장의 목록은 끊긴 적이 없습니다. */
  since: string
}

/** 전체가 「연결됨」인데 아직 다 붙지 않은 시장 하나. */
export interface LaggingMarket {
  market: DepositMarket
  state: StreamState
}

export interface StreamStatus {
  /** 앱 전체로 본 상태. 지금 보고 있는 시장 하나라도 받고 있으면 `live` 이고,
   *  보고 있는 시장이 **모두** 끊겨야 `stopped` 입니다. */
  state: StreamState
  /** 전체가 `live` 인데 다시 붙는 중이거나 끊긴 시장. 상단이 「시세 연결됨」 뒤에
   *  그 시장만 덧붙입니다. 전체가 `live` 가 아니면 비어 있습니다. */
  lagging: readonly LaggingMarket[]
  /** 시장마다의 상태. 한 시장의 값을 그리는 자리는 전체가 아니라 이것을 봅니다. */
  markets: Readonly<Record<DepositMarket, MarketFeed>>
  /** 자리가 모자라 밀린 구독. 그 카드가 「실시간이 안 붙었다」를 말합니다. */
  rejected: readonly string[]
}

const MARKETS: readonly DepositMarket[] = ['domestic', 'overseas']

const IDLE_FEED: MarketFeed = { state: 'idle', detail: '', since: '' }

const IDLE: StreamStatus = {
  state: 'idle',
  lagging: [],
  markets: { domestic: IDLE_FEED, overseas: IDLE_FEED },
  rejected: [],
}

/** 지금 한국시각을 `HH:MM` 으로. */
function stamp(): string {
  return kstClock(Date.now())
}

let status: StreamStatus = IDLE
const listeners = new Set<() => void>()

function announce(next: StreamStatus): void {
  status = next
  for (const listener of listeners) listener()
}

/** 앞에 올수록 전체 상태로 섭니다. 하나라도 받고 있으면 「연결됨」이고, 다시 붙는
 *  시장이 있으면 「끊김」보다 그쪽입니다 — 기다리면 되는 일을 눌러야 하는 일로
 *  말하지 않습니다. */
const RANK: readonly StreamState[] = ['live', 'reconnecting', 'connecting', 'finished', 'stopped', 'idle']

/** 전체 상태를 셉니다. **지금 보고 있는 시장만** 셉니다 — 아무것도 안 받는 시장은
 *  서버가 연결을 세우지 않아 상태가 오지 않고, 그 시장을 세면 「붙는 중」이 영영
 *  남습니다. 보고 있는 시장이 없으면 두 시장을 다 셉니다. */
function summarize(
  markets: Readonly<Record<DepositMarket, MarketFeed>>,
): Pick<StreamStatus, 'state' | 'lagging'> {
  const shown = activeMarkets()
  const counted = shown.length > 0 ? shown : MARKETS
  const states = counted.map((market) => markets[market].state)
  const state = RANK.find((one) => states.includes(one)) ?? 'idle'
  /* 저장해 둔 자료가 끝난 것은 실서버에 없는 상태라 덧붙이지 않습니다. */
  const lagging: LaggingMarket[] =
    state === 'live'
      ? counted
          .filter((market) => markets[market].state !== 'live' && markets[market].state !== 'finished')
          .map((market) => ({ market, state: markets[market].state }))
      : []
  return { state, lagging }
}

/** 시장마다의 상태를 바꾸고 전체를 다시 셉니다. `targets` 를 빼면 두 시장 다입니다. */
function announceMarkets(
  change: (feed: MarketFeed) => MarketFeed,
  targets: readonly DepositMarket[] = MARKETS,
): void {
  const markets: Record<DepositMarket, MarketFeed> = { ...status.markets }
  for (const market of targets) markets[market] = change(markets[market])
  announce({ ...status, markets, ...summarize(markets) })
}

export function streamStatus(): StreamStatus {
  return status
}

export function subscribeStream(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** 구독 하나를 가리키는 열쇠. 밀린 구독을 카드가 알아보는 데 씁니다. */
export function wishKey(wish: Pick<Wish, 'context' | 'kind' | 'sym'>): string {
  return `${wish.context}|${wish.kind}|${wish.sym}`
}

/* ── 목록 모으기 ─────────────────────────────────────── */

/* 화면 조각마다 제 몫을 등록합니다. 열쇠는 그 조각의 이름이고, 값은 그 조각이
   지금 보고 있는 것 전부입니다. 조각이 사라지면 제 몫만 빠집니다. */
const wishes = new Map<string, readonly Wish[]>()

function declared(): Wish[] {
  /* 같은 구독을 여러 조각이 원하면 **가장 높은 등급으로 한 번만** 보냅니다.
     서버도 같은 것을 하나로 묶지만, 등급이 낮은 쪽이 나중에 도착하면 그 값이
     이깁니다 — 헤더가 보는 종목이 관심종목 등급으로 내려가면 안 됩니다. */
  const best = new Map<string, Wish>()
  for (const list of wishes.values()) {
    for (const wish of list) {
      const key = wishKey(wish)
      const held = best.get(key)
      if (!held || (wish.priority ?? 0) > (held.priority ?? 0)) best.set(key, wish)
    }
  }
  return [...best.values()]
}

let socket: WebSocket | null = null
let retryTimer: number | undefined
let retryWait = 1000
/** 지금 보고 있는 종목과 그 시장. 다시 채우라는 신호가 오면 **그 시장의** 종목만
 *  다시 부릅니다. */
let watching: { market: DepositMarket; sym: string }[] = []
/** 주문/체결 알림을 듣고 있는 계좌. 다시 채우라는 신호가 오면 그 계좌의 주문·
 *  미결제약정 목록을 다시 부릅니다 — 끊긴 동안의 알림은 아무도 안 보내 줍니다. */
let watchingOrders: DepositMarket[] = []

/** 화면 맥락이 어느 계좌인지. 주간·야간은 같은 계좌입니다. */
function marketOf(context: MarketContext): DepositMarket {
  return context === 'overseas' ? 'overseas' : 'domestic'
}

/** 지금 무엇이든 보고 있는 시장. 전체 상태는 이 시장들로 셉니다. */
function activeMarkets(): DepositMarket[] {
  const feeds = declared()
  return MARKETS.filter((market) => feeds.some((wish) => marketOf(wish.context) === market))
}

function send(): void {
  /* 보는 시장이 바뀌면 전체 상태도 바뀝니다 — 해외 종목을 닫으면 해외의 상태는
     더 이상 상단에 안 섭니다. 연결이 닫혀 있어도 다시 셉니다. */
  const summary = summarize(status.markets)
  if (
    summary.state !== status.state ||
    JSON.stringify(summary.lagging) !== JSON.stringify(status.lagging)
  ) {
    announce({ ...status, ...summary })
  }
  if (socket?.readyState !== WebSocket.OPEN) return
  const feeds = declared()
  watching = feeds
    .filter((wish) => wish.kind !== 'orders' && wish.sym !== '')
    .map((wish) => ({ market: marketOf(wish.context), sym: wish.sym }))
  watchingOrders = [
    ...new Set(feeds.filter((wish) => wish.kind === 'orders').map((wish) => marketOf(wish.context))),
  ]
  socket.send(JSON.stringify({ op: 'declare', feeds }))
}

/** 이 조각이 보고 있는 것을 알립니다. 바뀔 때마다 목록 전체가 다시 나갑니다. */
export function declareWishes(owner: string, list: readonly Wish[]): void {
  wishes.set(owner, list)
  send()
}

export function dropWishes(owner: string): void {
  wishes.delete(owner)
  send()
}

/** 지금 시세를 받고 있는 종목과 그 시장. 주문 알림은 빠집니다 — 머리의 「마지막
 *  시세」가 멈췄는지를 가릴 때, 장이 열린 종목이 하나라도 있는지 보는 데 씁니다. */
export function watchedQuotes(): { market: DepositMarket; sym: string }[] {
  return declared()
    .filter((wish) => wish.kind !== 'orders' && wish.sym !== '')
    .map((wish) => ({ market: marketOf(wish.context), sym: wish.sym }))
}

/** 장이 열려 값이 올 수 있는 세션. 동시호가 전·쉬는 시간·다음 날 넘김은 값이
 *  안 오는 것이 정상이라 넣지 않습니다. */
const TRADING: readonly SessionState[] = ['day', 'closing-auction', 'night', 'open', 'open-2']

/** 새 시세 없이 이만큼 지나면 멈춘 것으로 봅니다. 한산한 원월은 1분 동안 체결이
 *  없는 일이 흔하지만, 받는 종목이 **모두** 2분 동안 조용한 일은 드뭅니다. */
export const QUOTE_STALL_MS = 120_000

/** 시세가 멈췄는가. 셋이 다 맞을 때만 참입니다.
 *
 *  - 실시간이 붙어 있음 — 끊긴 때는 연결 표시가 이미 말합니다.
 *  - 받는 종목 중 하나라도 서버가 장중이라고 답함 — 장이 닫혔거나 세션을 모르면
 *    값이 안 오는 것이 정상이거나 판단할 근거가 없습니다.
 *  - 마지막 시세가 `QUOTE_STALL_MS` 넘게 지남 — 한 번도 안 왔으면 견줄 시각이
 *    없어 참이 아닙니다. */
export function quotesStalled(now: number = Date.now()): boolean {
  if (status.state !== 'live') return false
  const at = lastQuoteAt()
  if (at === null || now - at <= QUOTE_STALL_MS) return false
  /* 다시 붙는 중인 시장의 종목은 세지 않습니다 — 그 시장이 끊긴 것은 상단의
     연결 표시가 이미 말합니다. */
  return watchedQuotes().some(({ market, sym }) => {
    if (status.markets[market].state !== 'live') return false
    const state = sessionEntry(market, sym).state
    return state !== null && TRADING.includes(state)
  })
}

/* ── 연결 ────────────────────────────────────────────── */

function url(): string {
  /* 호스트를 적지 않습니다 — 배포 모드에서는 포트가 매번 다릅니다. 지금 페이지의
     주소에서 규약만 바꿉니다. */
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${location.host}/api/stream`
}

function receive(message: Record<string, unknown>): void {
  switch (message.type) {
    case 'quote': {
      const sym = String(message.sym ?? '')
      const patch = (message.patch ?? {}) as Record<string, number | null>
      const trades = (message.trades ?? []) as never[]
      applyRealtimeQuote(sym, patch, trades)
      noteQuoteArrival()
      return
    }
    case 'book': {
      const sym = String(message.sym ?? '')
      /* 국내 호가에는 예상체결가 칸이 값 또는 `null` 로 늘 실려 옵니다(`null` 이
         지움). 해외에는 칸이 없습니다. */
      const book = {
        asks: message.asks,
        bids: message.bids,
        expectedPrice: message.expectedPrice,
      } as BookReply
      applyRealtimeBook(sym, book)
      noteQuoteArrival()
      return
    }
    case 'orders': {
      /* 이 계좌의 주문/체결 알림. 접수·확인·체결이 건마다 한 줄이고, 한 번에 온
         것은 일어난 차례대로 실려 있습니다. 조회로 받아 둔 주문 목록 위에
         주문번호로 이어 붙입니다(`data/account.ts`). */
      const market = message.market
      if (market !== 'domestic' && market !== 'overseas') return
      applyOrderEvents(market, (message.events ?? []) as OrderEvent[])
      return
    }
    case 'strategy': {
      /* 검증 실행 한 묶음. **실행이 하나라도 있을 때만** 옵니다 — 줄은 지금
         상태 전부이고, 체결·이벤트는 실행마다 최근 스무 줄이라 겹치는 것이
         늘 실려 옵니다(`data/strategyStore.ts` 가 열쇠로 가립니다). */
      applyStrategyBroadcast(
        (message.runs ?? []) as VerifyRun[],
        (message.fills ?? []) as VerifyFill[],
        (message.events ?? []) as VerifyEvent[],
        /* 열린 주문은 **그 순간 전부**라 덮어씁니다(`strategyStore` 가 합니다). */
        (message.openOrders ?? []) as VerifyOrder[],
      )
      return
    }
    case 'subscriptions': {
      const rejected = ((message.rejected ?? []) as Wish[]).map(wishKey)
      announce({ ...status, rejected })
      return
    }
    case 'session': {
      /* 국내 세션 경계를 지났다는 말입니다. 세션은 종목마다 다시 물어 확인합니다
         (최종거래일 같은 종목별 사정은 방송에 안 실립니다). 그 답이 바뀌면 시세
         저장소가 보고 있던 국내 종목을 그 세션의 길로 다시 받습니다
         (`data/quotes.ts`) — 야간이면 야간 현재가입니다. **주문 폼은 그대로입니다**
         — 같은 계좌입니다. */
      void applySessionBroadcast(String(message.market ?? ''))
      return
    }
    case 'environment': {
      /* 서버의 활성 환경이 바뀌었다는 말입니다. 이 연결은 그대로 두고 값만
         갈아 끼웁니다 — 담아 둔 시세·계좌는 다른 환경의 것이라 그 자리에서
         비워지고, 뒤따라 오는 `refill` 과 보는 자리들이 새 환경 값으로 채웁니다. */
      const active = message.active
      noteActive(active === 'paper' || active === 'real' ? active : null)
      return
    }
    case 'status': {
      const state = String(message.state ?? '')
      const detail = String(message.detail ?? '')
      /* **어느 시장의 말인지 봅니다.** 서버는 시장마다 따로 붙고 따로 알립니다 —
         국내가 다시 붙는 신호로 해외 상태를 덮으면 멀쩡한 해외까지 끊긴 것처럼
         서고, 해외 값까지 다시 부르게 됩니다. 시장이 안 적힌 말은 두 시장 다의
         것으로 읽습니다. */
      const market = message.market
      const targets: readonly DepositMarket[] =
        market === 'domestic' || market === 'overseas' ? [market] : MARKETS
      /* 저장해 둔 자료가 끝난 것은 **실서버에 없는 상태**라 화면에 안 세웁니다 —
         없는 것을 그리면 그 코드가 남습니다. 값이 왜 멈췄는지는 상단의
         「마지막 갱신」이 이미 말하고, 개발 중에는 이 한 줄이 답합니다. */
      if (import.meta.env.DEV && (state === 'replay-finished' || state === 'replay-empty')) {
        console.warn(`[실시간] ${detail || '저장해 둔 자료가 끝났습니다.'}`)
      }
      /* 다시 채우라는 신호는 「여기서부터 새로 받는다」는 말이기도 합니다 —
         같은 연결에서 환경이 바뀐 뒤에는 소켓이 다시 열리지 않으므로, 체결
         목록의 「언제부터」가 여기서 다시 섭니다. */
      announceMarkets(
        (feed) => ({
          state:
            state === 'replay-finished' || state === 'replay-empty' ? 'finished' : toState(state, feed.state),
          detail,
          since: message.refill === true ? stamp() : feed.since,
        }),
        targets,
      )
      /* **끊겼다 붙은 것이라 조회를 다시 불러야 합니다.** 끊긴 동안의 변화는
         실시간이 메워 주지 않습니다. 이 신호를 흘리면 화면은 빠진 구간이 있는
         값을 최신인 줄 알고 그대로 보여 줍니다.
         **담긴 값이 있는 종목만** 다시 부릅니다 — 환경이 바뀌어 비워진 종목은
         보는 자리가 제 규칙으로 다시 부르고, 환경을 아직 정리하는 중이면 그때까지
         기다립니다. 여기서도 부르면 같은 조회가 두 번 나갑니다. */
      if (message.refill === true && environmentSettled()) {
        /* **다시 붙은 시장의 것만** 부릅니다. 다른 시장은 끊긴 적이 없어 메울
           구간이 없습니다. */
        for (const one of watching) {
          if (targets.includes(one.market) && quoteAsked(one.sym)) void loadQuote(one.sym, { force: true })
        }
        /* 주문·미결제약정도 같습니다 — 끊긴 동안의 접수·체결은 알림으로 다시
           오지 않으므로 조회로 메웁니다. */
        for (const one of watchingOrders) {
          if (targets.includes(one)) reloadAccountLists(one)
        }
        /* 검증 실행도 같습니다 — 끊긴 동안의 체결은 최근 스무 줄 밖으로 밀려
           나면 방송이 다시 보내 주지 않습니다. */
        void refillRuns(targets)
      }
      return
    }
    default:
      /* 모르는 말이 와도 연결을 끊지 않습니다 — 서버가 늘어나는 쪽으로 바뀔 수
         있습니다. */
      return
  }
}

function toState(state: string, held: StreamState): StreamState {
  return state === 'live' || state === 'connecting' || state === 'reconnecting' || state === 'stopped'
    ? state
    : held
}

/** 연결을 엽니다. 앱이 뜰 때 한 번 부릅니다. */
export function openStream(): void {
  if (socket) return
  announceMarkets((feed) => ({ ...feed, state: 'connecting', detail: '' }))
  const link = new WebSocket(url())
  socket = link

  link.onopen = () => {
    retryWait = 1000
    /* **여기서부터 다시 모읍니다.** 끊긴 동안 일어난 체결은 아무도 안 보내
       주므로, 붙은 시각이 곧 「이 목록이 담고 있는 구간의 시작」입니다. */
    announceMarkets((feed) => ({ ...feed, since: stamp() }))
    /* 붙자마자 지금 보고 있는 것 전체를 보냅니다 — 끊긴 사이에 바뀌었을 수
       있고, 서버는 이 연결이 처음 보는 화면입니다. */
    send()
  }

  link.onmessage = (event) => {
    try {
      receive(JSON.parse(String(event.data)) as Record<string, unknown>)
    } catch {
      /* 읽을 수 없는 말 하나 때문에 연결을 끊지 않습니다. */
    }
  }

  link.onclose = () => {
    socket = null
    /* 이 연결 하나로 두 시장을 다 받으므로 둘 다 끊긴 것입니다. */
    announceMarkets((feed) => ({ ...feed, state: 'reconnecting', detail: '' }))
    /* 기다리는 시간을 늘려 가며 다시 붙습니다. 서버가 내려가 있을 때 쉬지 않고
       두드리면 붙는 순간까지 그 부하가 그대로 갑니다. */
    retryTimer = window.setTimeout(openStream, retryWait)
    retryWait = Math.min(retryWait * 2, 30000)
  }

  link.onerror = () => {
    /* 닫힘이 뒤따라 오므로 여기서는 아무것도 안 합니다. */
  }
}

/** 연결을 놓습니다. 앱이 내려갈 때만 부릅니다. */
export function closeStream(): void {
  if (retryTimer !== undefined) window.clearTimeout(retryTimer)
  const link = socket
  socket = null
  /* 다시 붙지 않도록 닫기 처리를 먼저 떼어 냅니다. */
  if (link) {
    link.onclose = null
    link.close()
  }
  const stopped: MarketFeed = { ...IDLE_FEED, state: 'stopped' }
  const markets = { domestic: stopped, overseas: stopped }
  announce({ ...IDLE, markets, ...summarize(markets) })
}

/* ── 화면에서 쓰는 꼴 ────────────────────────────────── */

/** 이 조각이 보고 있는 것을 알리고, 사라질 때 제 몫만 뺍니다. */
export function useWishes(owner: string, list: readonly Wish[]): void {
  const key = JSON.stringify(list)
  useEffect(() => {
    declareWishes(owner, list)
    return () => dropWishes(owner)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [owner, key])
}

export function useStreamStatus(): StreamStatus {
  return useSyncExternalStore(subscribeStream, streamStatus, () => IDLE)
}
