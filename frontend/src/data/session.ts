/** 거래 세션(주간·야간·마감)과 거래시간표를 아는 자리.
 *
 *  **세션은 서버가 답한 값입니다.** 화면이 시계를 보고 「지금 야간이다」라고
 *  정하지 않습니다 — 사용자 PC 의 시계가 서버와 갈리면 야간에 주간으로 읽는
 *  화면이 서고, 그 판단 위에서 낸 주문은 다른 세션으로 나갑니다. 헤더의
 *  거래시간 자리 한 곳이 여기 값을 읽습니다.
 *
 *  **종목마다 다릅니다.** 야간이 없는 품목, 오늘이 최종거래일인 종목, 거래소마다
 *  다른 해외 시간이 있어 종목을 볼 때 그 종목의 세션을 묻습니다. 국내는 세션
 *  경계마다 서버가 실시간으로 알려 오고(`data/stream.ts`), 해외는 방송이 없어
 *  구간이 끝나는 시각에 다시 묻습니다.
 *
 *  **휴장일은 모릅니다**(`holidayAware: false`). 서버가 휴장일에도 개장으로 답하면
 *  화면도 그대로 믿습니다 — 안 오는 값은 상단의 마지막 갱신 시각이 말합니다.
 *  휴장 얼굴을 지어내지 않습니다.
 *
 *  **세션이 바뀌어도 주문 폼을 비우지 않습니다.** 주간과 야간은 같은 계좌입니다
 *  (환경이 바뀌면 다른 계좌라 비웁니다 — `data/environment.ts`).
 */
import { kstClock, kstDay, kstParts } from '../lib/kst'
import { useEffect, useSyncExternalStore } from 'react'

import type { Market } from './instruments'
import type { ProductKind } from '../lib/types'

/** 국내 상태 여섯 · 해외 상태 다섯. 서버 낱말 그대로입니다. */
export type SessionState =
  | 'closed'
  | 'pre-open'
  | 'day'
  | 'closing-auction'
  | 'pre-night'
  | 'night'
  | 'open'
  | 'break'
  | 'open-2'
  | 'next-day'

/** 국내 실시간 맥락으로 쓸 값. 단일가는 그 앞뒤 세션에 속합니다. 마감·해외는 없습니다. */
export type SessionName = 'day' | 'night'

export interface SessionEntry {
  /** `idle` 은 아직 안 물어봤다는 뜻입니다. */
  status: 'idle' | 'loading' | 'ready' | 'failed'
  state: SessionState | null
  session: SessionName | null
  /** ISO 시각(한국시간). 마감이면 `until` 은 다음 상태(단일가 포함)의 시작이고
   *  `nextOpen` 은 다음 **거래** 시작입니다 — 둘이 다를 수 있습니다. */
  since: string | null
  until: string | null
  nextOpen: string | null
  hasNight: boolean
  /** 오늘이 이 종목의 최종거래일이면 그 마감 시각. 그날은 다음 개장이 없습니다. */
  lastTradingDay: { closeAt: string } | null
  /** `api` 오늘 받은 시간표(서버의 `api:real`·`api:paper` 둘 다) · `table` 시간표를 못 받아 내장 표 · `unknown` 종목을 마스터에서
   *  못 찾았거나 해외 시간표에 그 품목이 없음(마감처럼 답하지만 모르는 것입니다). */
  source: 'api' | 'table' | 'unknown' | null
}

const EMPTY: SessionEntry = {
  status: 'idle',
  state: null,
  session: null,
  since: null,
  until: null,
  nextOpen: null,
  hasNight: false,
  lastTradingDay: null,
  source: null,
}

/** 서버의 `source` 를 화면의 세 갈래로. 받은 시간표는 어느 서버에서 받았는지가
 *  붙어 오지만(`api:real`·`api:paper`) 화면은 「받은 표인가」만 가립니다. */
function toSource(value: unknown): SessionEntry['source'] {
  if (typeof value !== 'string') return null
  if (value === 'api' || value.startsWith('api:')) return 'api'
  return value === 'table' || value === 'unknown' ? value : null
}

interface SessionReply {
  market: string
  sym: string
  state: string
  session: string | null
  since: string | null
  until: string | null
  nextOpen: string | null
  hasNight: boolean
  lastTradingDay: { closeAt: string } | null
  source: string
}

const entries = new Map<string, SessionEntry>()
const listeners = new Set<() => void>()
/** 구간이 끝나는 시각에 다시 묻는 시계. 종목마다 하나입니다. */
const timers = new Map<string, number>()
/** 종목마다 지금 보고 있는 자리 수. 0 이면 경계에 다시 묻지 않습니다. */
const watchers = new Map<string, number>()
const flying = new Set<string>()

function keyOf(market: Market, sym: string): string {
  return `${market}|${sym}`
}

function announce(key: string, next: SessionEntry): void {
  entries.set(key, next)
  for (const listener of listeners) listener()
}

export function subscribeSession(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function sessionEntry(market: Market, sym: string): SessionEntry {
  return entries.get(keyOf(market, sym)) ?? EMPTY
}

/** 국내 종목의 실시간 맥락. 세션을 모르면(아직 안 물었거나 마감) 주간입니다 —
 *  마감 중에 구독해 두는 것은 해가 없고, 야간이 열리면 방송이 와서 바꿉니다. */
export function domesticContextOf(sym: string): 'domestic-day' | 'domestic-night' {
  return sessionEntry('domestic', sym).session === 'night' ? 'domestic-night' : 'domestic-day'
}

/** 국내 야간이 여는 시각(한국시간 시). **회차를 가르는 데만** 쓰므로 시간표에서
 *  읽지 않고 상수로 둡니다 — 시간표가 늦게 오거나 어긋나도 회차 열쇠가 흔들리지
 *  않습니다. 야간이 실제로 열렸는지는 서버의 세션 답이 정합니다. */
const NIGHT_OPENS_HOUR = 18

/** 국내 야간 **회차**. 그 야간이 열린 한국 날짜의 날 번호입니다 — 야간은 자정을
 *  넘겨 새벽까지 이어지므로, 야간이 여는 시각 전은 전날 회차로 묶습니다. 그래서
 *  새벽도 저녁과 같은 회차이고, 다음 저녁이 되면 새 회차입니다. */
export function domesticNightRound(at: number = Date.now()): number {
  return kstDay(at) - (kstParts(at).hour < NIGHT_OPENS_HOUR ? 1 : 0)
}

function toState(value: string): SessionState | null {
  const known: SessionState[] = [
    'closed',
    'pre-open',
    'day',
    'closing-auction',
    'pre-night',
    'night',
    'open',
    'break',
    'open-2',
    'next-day',
  ]
  return (known as string[]).includes(value) ? (value as SessionState) : null
}

/** 한 종목의 세션을 묻습니다. 답이 오면 구간 끝(`until`)에 다시 묻도록 시계를
 *  겁니다 — 국내는 방송이 먼저 오지만 겹쳐도 같은 답이고, 해외는 이 시계가 전부입니다. */
export async function loadSession(market: Market, sym: string): Promise<void> {
  if (!sym) return
  const key = keyOf(market, sym)
  if (flying.has(key)) return
  flying.add(key)
  const held = entries.get(key) ?? EMPTY
  announce(key, { ...held, status: held.state ? 'ready' : 'loading' })

  try {
    const query = new URLSearchParams({ market, sym })
    const response = await fetch(`/api/session?${query.toString()}`)
    if (!response.ok) {
      announce(key, { ...held, status: held.state ? 'ready' : 'failed' })
      return
    }
    const reply = (await response.json()) as SessionReply
    const next: SessionEntry = {
      status: 'ready',
      state: toState(reply.state),
      session: reply.session === 'day' || reply.session === 'night' ? reply.session : null,
      since: reply.since ?? null,
      until: reply.until ?? null,
      nextOpen: reply.nextOpen ?? null,
      hasNight: reply.hasNight === true,
      lastTradingDay: reply.lastTradingDay ?? null,
      source: toSource(reply.source),
    }
    announce(key, next)
    /* 같은 `until` 이 또 오면 시계가 서버보다 앞서 경계 직전 값을 다시 받은 것입니다.
       1초마다 되풀이하지 않게 그때는 한 번에 1분 뒤로 겁니다. */
    schedule(market, sym, next.until, held.until === next.until)
  } catch {
    announce(key, { ...held, status: held.state ? 'ready' : 'failed' })
  } finally {
    flying.delete(key)
  }
}

/** 구간이 끝나는 시각 직후에 한 번 더 묻습니다. 시각을 모르면 걸지 않습니다.
 *  **주기적으로 묻는 것이 아닙니다** — 다음 경계 한 번뿐이고, 답이 오면 그 답의
 *  경계에 또 한 번입니다. */
function schedule(market: Market, sym: string, until: string | null, repeated = false): void {
  const key = keyOf(market, sym)
  const held = timers.get(key)
  if (held !== undefined) window.clearTimeout(held)
  timers.delete(key)
  if (!until) return
  /* 보는 자리가 하나도 없는 종목은 다시 안 묻습니다 — 시계가 종목마다 남아 쌓이면
     경계마다 물음이 본 종목 수만큼 나갑니다. 다시 열면 그때 묻습니다. */
  if (!(watchers.get(key) ?? 0)) return
  const wait = new Date(until).getTime() - Date.now() + 1000
  if (!Number.isFinite(wait)) return
  /* 지난 시각이면 곧바로가 아니라 1초 뒤 — 서버 시계와 어긋난 채로 되풀이하지
     않게 최소 간격을 둡니다. 같은 답이 되풀이되면 1분입니다. 브라우저 타이머
     상한(약 24.8일)을 넘는 시각은 안 겁니다 — 그전에 화면이 다시 열립니다. */
  const floor = repeated ? 60_000 : 1000
  const delay = Math.min(Math.max(wait, floor), 2_000_000_000)
  timers.set(
    key,
    window.setTimeout(() => {
      timers.delete(key)
      void loadSession(market, sym)
    }, delay),
  )
}

/** 실시간이 알려 온 국내 세션 경계. 종목마다 다른 것(최종거래일)은 방송에 안
 *  실리므로, **보고 있는** 국내 종목을 다시 묻습니다 — 값을 방송에서 옮겨 적지
 *  않습니다. 보는 자리가 없는 종목은 다시 열 때 묻습니다. */
export async function applySessionBroadcast(market: string): Promise<void> {
  if (market !== 'domestic') return
  const asks: Promise<void>[] = []
  for (const key of entries.keys()) {
    const [held, sym] = key.split('|')
    if (held === 'domestic' && (watchers.get(key) ?? 0) > 0) asks.push(loadSession('domestic', sym))
  }
  await Promise.all(asks)
}

/** 이 종목의 세션을 구독합니다. 빈 코드는 안 묻습니다.
 *  **이미 들은 종목은 다시 안 묻습니다** — 같은 종목을 보는 자리가 여럿이고
 *  (헤더·차트), 구간이 끝나면 위 시계가 알아서 다시 묻습니다. 못 받은 것은
 *  다시 봅니다. */
export function useSession(market: Market, sym: string): SessionEntry {
  const entry = useSyncExternalStore(
    subscribeSession,
    () => (sym ? sessionEntry(market, sym) : EMPTY),
    () => EMPTY,
  )
  useEffect(() => {
    if (!sym) return
    const key = keyOf(market, sym)
    watchers.set(key, (watchers.get(key) ?? 0) + 1)
    const held = sessionEntry(market, sym)
    if (held.status === 'idle' || held.status === 'failed') void loadSession(market, sym)
    /* 답은 있는데 시계가 없으면(보는 자리가 한동안 없었음) 다시 겁니다. */
    else if (!timers.has(key)) schedule(market, sym, held.until)
    return () => {
      const left = (watchers.get(key) ?? 1) - 1
      watchers.set(key, left)
      if (left <= 0) {
        watchers.delete(key)
        const timer = timers.get(key)
        if (timer !== undefined) window.clearTimeout(timer)
        timers.delete(key)
      }
    }
  }, [market, sym])
  return entry
}

/* ── 거래시간표 ─────────────────────────────────────────
 *
 * 헤더의 「주간 08:45~15:45」 같은 문자열이 여기서 나옵니다. 하루 한 번 서버가
 * 받아 두는 표라 앱이 뜰 때 한 번 읽습니다. **국내도 해외도 품목마다 다릅니다** —
 * 같은 주간이라도 개장이 08:45 인 품목과 09:00 인 품목이 함께 옵니다. 그래서 한
 * 종목의 시각은 그 종목 품목 줄에서 읽습니다.
 *
 * 세션별 공통값(`sessions`)도 함께 오지만 그것은 품목 줄들의 최다값이라, 소수
 * 쪽 품목에는 늘 틀립니다. 품목 줄이 없는 종목에만 씁니다.
 */

/** 시각 구간. `nextDay` 면 `close` 가 다음 날입니다. */
export interface Window {
  open: string
  close: string
  nextDay: boolean
}

interface DomesticSessions {
  day: DomesticSession
  night: DomesticSession
}

interface DomesticSession {
  trading: Window
  /** 접속매매가 끝난 뒤 종가를 정하는 단일가 구간. 시간표가 세션마다 함께 줍니다.
   *  **접속매매 창과 겹쳐 옵니다**(주간 거래 08:45~15:45, 단일가 15:35~15:45) —
   *  끝나는 시각이 같고 그 앞 몇 분이 단일가입니다. */
  closingAuction?: Window
}

/** 국내 품목 한 줄의 규격. **품목별세부정보 응답이 주는 그대로**입니다 — 증거금률은
 *  `21.75%` 처럼 글자로 오므로 숫자로 바꾸지 않습니다(단위가 사라집니다).
 *
 *  **옵션 품목에는 증거금 셋이 안 옵니다.** 그 자리는 빈 글자·`null` 로 오고 화면은
 *  비워 둡니다 — 선물 줄의 값을 옮겨 오면 없는 값을 지어내는 것입니다. */
export interface DomesticProductDetail {
  name: string
  /** 품목코드 두 자리. 백엔드가 품목 이름으로 찾아 붙입니다 — 응답에는 없습니다.
   *  못 찾은 줄은 `null` 이고, 그 줄은 화면이 못 씁니다. */
  productCode: string | null
  session: SessionName
  /** 이 품목이 그 세션에 실제로 거래되는 시각. **세션 공통값이 아니라 이 줄의
   *  값**이고, 종목 화면의 시각은 전부 여기서 옵니다. */
  trading?: Window
  /** 접속매매가 끝난 뒤 종가를 정하는 단일가 구간. 품목마다 다릅니다. */
  closingAuction?: Window
  settlement: string
  tick: number | null
  tickValue: number | null
  multiplier: number | null
  initialMarginRate: string
  maintenanceMarginRate: string
  contractInitialMargin: number | null
}

export interface OverseasProductHours {
  productCode: string
  exchange: string
  kind: string
  /** 그 품목의 통화 코드(`USD` 등). 마스터에는 없고 시간표가 줍니다. */
  currency: string | null
  trading: Window | null
  second: Window | null
  nextDayTrading: Window | null
  /** 정산가를 산정하는 시각 구간. 시작과 끝이 같은 품목도 있습니다. */
  settlementWindow: Window | null
}

let domesticSessions: DomesticSessions | null = null
/** 국내 품목 규격 줄. 거래시간표와 **같은 응답**에서 옵니다 — 한 번 받은 것을
 *  품목정보 탭이 함께 씁니다. */
let domesticProducts: DomesticProductDetail[] = []
/** 해외 시간표 줄. 열쇠는 **(거래소, 품목코드)** 입니다 — 품목코드만으로 담으면
 *  거래소가 다른 같은 코드가 서로를 덮습니다. */
const overseasHours = new Map<string, OverseasProductHours>()

const hoursKey = (exchange: string, productCode: string) => `${exchange}|${productCode}`

/** 마스터 거래소 번호 → 시간표가 쓰는 거래소 이름. 서버 판정이 쓰는 표와 같은
 *  값입니다(두 자리가 다른 이름으로 찾으면 머리 시간과 판정이 다른 줄을 봅니다). */
const TIMETABLE_EXCHANGE: Record<string, string> = {
  '01': 'CME',
  '04': 'EUREX',
  '05': 'SGX',
  '06': 'HKEX',
  '11': 'ICE',
  '15': 'CBOE',
}

/** 마스터와 시간표가 **거래소를 다르게 적는** 품목. 서버 판정과 같은 확인된 짝만
 *  둡니다 — 마스터의 거래소로 찾는 것이 먼저이고, 없을 때만 이 짝으로 찾습니다. */
const SAME_PRODUCT: Record<string, string> = {
  [hoursKey('ICE', 'MEM')]: hoursKey('LIFFE', 'MEM'),
}

/** 해외 품목의 거래 창 셋(1차·2차·익일). 시간표에 그 품목이 없으면 `null` 입니다 —
 *  창이 비어 있는 것(그 구간이 없음)과 품목을 모르는 것을 가릅니다. */
export function overseasTradingWindows(
  exchangeNo: string | null,
  productCode: string,
): { trading: Window | null; second: Window | null; nextDayTrading: Window | null } | null {
  const row = hoursRow(exchangeNo, productCode)
  return row ? { trading: row.trading, second: row.second, nextDayTrading: row.nextDayTrading } : null
}

/** 시간표에 있는 해외 품목들의 통화 코드(세 글자), 가나다 차례. 계좌 손실 한도의
 *  「통화 더하기」가 고르는 목록입니다. 시간표를 아직 못 받았으면 비어 있습니다. */
export function overseasCurrencies(): string[] {
  const made = new Set<string>()
  for (const row of overseasHours.values()) {
    const code = (row.currency ?? '').trim().toUpperCase()
    if (/^[A-Z]{3}$/.test(code)) made.add(code)
  }
  return [...made].sort()
}

/** 그 종목의 시간표 줄. 거래소나 품목을 모르거나 표에 없으면 `null` 입니다. */
function hoursRow(exchangeNo: string | null, productCode: string): OverseasProductHours | null {
  const exchange = exchangeNo ? TIMETABLE_EXCHANGE[exchangeNo] : undefined
  if (!exchange || !productCode) return null
  const key = hoursKey(exchange, productCode)
  const found = overseasHours.get(key)
  if (found) return found
  const pair = SAME_PRODUCT[key]
  return pair ? (overseasHours.get(pair) ?? null) : null
}
/** `idle` 은 아직 안 물어봤다는 뜻입니다. 둘 중 하나라도 못 받으면 `failed` 입니다. */
let timetableStatus: 'idle' | 'loading' | 'ready' | 'failed' = 'idle'

/** 시간표 둘을 읽습니다. 한 번만 부르고, 실패하면 시간 문자열이 비어 있을 뿐
 *  세션 판정(`/api/session`)은 서버가 따로 답하므로 화면이 멈추지 않습니다. */
export async function loadTimetable(): Promise<void> {
  if (timetableStatus !== 'idle') return
  timetableStatus = 'loading'
  const post = (path: string) =>
    fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
  let whole = true
  try {
    const [domestic, overseas] = await Promise.all([
      post('/api/domestic/product-detail'),
      post('/api/overseas/market-operations'),
    ])
    if (domestic.ok) {
      const body = (await domestic.json()) as {
        sessions?: DomesticSessions
        products?: DomesticProductDetail[]
      }
      domesticSessions = body.sessions ?? null
      domesticProducts = Array.isArray(body.products) ? body.products : []
    } else whole = false
    if (overseas.ok) {
      const body = (await overseas.json()) as { products?: OverseasProductHours[] }
      for (const item of body.products ?? []) {
        overseasHours.set(hoursKey(item.exchange, item.productCode), item)
      }
    } else whole = false
  } catch {
    /* 못 받으면 비어 있는 채로 둡니다. 다음 실행에 다시 받습니다. */
    whole = false
  }
  timetableStatus = whole ? 'ready' : 'failed'
  for (const listener of listeners) listener()
}

/** 시간표를 구독합니다. 값 자체는 아래 함수들로 읽고, 이 훅은 시간표가 오거나
 *  못 왔을 때 다시 그리게만 합니다. */
export function useTimetable(): 'idle' | 'loading' | 'ready' | 'failed' {
  return useSyncExternalStore(
    subscribeSession,
    () => timetableStatus,
    () => 'idle',
  )
}

/** 홈의 장 시간 줄과 전략 세션 이름이 함께 쓰는 세 줄. **이름을 한 곳에 둡니다** —
 *  같은 시간대를 화면마다 다른 말로 부르면 둘이 같은 것인지 읽는 사람이 맞춰
 *  봐야 합니다. 시간은 시간표에서 옵니다(`marketLineHours`). */
export const MARKET_LINES = [
  { key: 'domestic-day', label: '국내 주간' },
  { key: 'domestic-night', label: '국내 야간' },
  { key: 'overseas-cme', label: '해외 CME' },
] as const

export type MarketLineKey = (typeof MARKET_LINES)[number]['key']

/** 한 줄의 거래시간(한국시간). **그 시장이 열려 있는 폭**입니다 — 품목마다 시간이
 *  달라 한 줄에 한 시간만 세우려면 무엇으로든 줄여야 하는데, 최다값을 적으면 소수
 *  쪽 품목에게는 그 줄이 그냥 틀린 값입니다. 가장 이른 개장부터 가장 늦은 마감까지로
 *  두면 어느 품목도 그 밖으로 나가지 않습니다.
 *
 *  **폭 안이 내내 열려 있다는 뜻은 아닙니다.** 그 사실은 띠가 한 마디로 말하고,
 *  종목 하나의 시각은 그 종목 화면이 말합니다. 시간표를 못 받았으면 빈 문자열입니다. */
export function marketLineHours(key: MarketLineKey): string {
  if (key === 'overseas-cme') return windowText(exchangeSpan('CME'))
  return windowText(domesticSpan(key === 'domestic-night' ? 'night' : 'day'))
}

/** 그 세션 품목 줄들이 덮는 폭. **선물·옵션을 가리지 않습니다** — 한쪽만 세면 다른
 *  한쪽이 더 일찍 열거나 늦게 닫는 날 그 줄이 시장을 덜 말합니다. */
function domesticSpan(session: SessionName): Window | null {
  return spanOf(domesticProducts.filter((row) => row.session === session).map((row) => row.trading))
}

/** 그 거래소 선물 품목들이 덮는 폭. 옵션을 빼 둔 것은 지금 줄이 선물 줄이기
 *  때문입니다 — 넓히려면 줄 이름부터 바뀌어야 합니다. */
function exchangeSpan(exchange: string): Window | null {
  const windows: (Window | null | undefined)[] = []
  for (const item of overseasHours.values()) {
    if (item.exchange === exchange && item.kind === 'futures') windows.push(item.trading)
  }
  return spanOf(windows)
}

/** 창 여럿이 덮는 폭 — 가장 이른 개장 ~ 가장 늦은 마감. **익일 마감이 더 늦습니다**
 *  (야간의 05:00 은 주간의 15:45 보다 뒤입니다). 창이 하나도 없으면 `null` 입니다. */
function spanOf(windows: (Window | null | undefined)[]): Window | null {
  let open: string | null = null
  let close: Window | null = null
  const rank = (one: Window) => `${one.nextDay ? 1 : 0}${one.close}`
  for (const one of windows) {
    if (!one) continue
    if (open === null || one.open < open) open = one.open
    if (close === null || rank(one) > rank(close)) close = one
  }
  if (open === null || close === null) return null
  return { open, close: close.close, nextDay: close.nextDay }
}

/** 구간을 「08:45~15:45」·「18:00~익일 06:00」 꼴로. */
export function windowText(window: Window | null): string {
  if (!window) return ''
  return `${window.open}~${window.nextDay ? '익일 ' : ''}${window.close}`
}

/** 국내 세션의 **시장 공통** 거래시간. 품목 줄들의 최다값이라 소수 쪽 품목에는
 *  틀린 값이고, 그래서 **품목 줄이 없는 종목의 대체값으로만** 씁니다 — 밖으로
 *  내보내지 않는 것은 그 자리를 이 파일 안에 묶어 두기 위해서입니다.
 *  화면이 부르는 것은 아래 `domesticHoursFor` 하나입니다. */
function domesticHours(session: SessionName): string {
  return windowText(domesticSessions?.[session]?.trading ?? null)
}

/** 이 순간이 국내 **주간** 거래시간 안인가. 시간표를 아직 못 받았으면 `null` 입니다.
 *
 *  일봉을 체결로 잇는 자리가 씁니다. 그 일봉은 주간 일봉이고 야간은 다음 영업일의
 *  다른 세션이라, 야간 체결을 주간 봉에 더하면 그날 고가·저가가 거래소가 내는
 *  일봉과 갈립니다. **모르면 안 접습니다** — 틀리게 접어도 화면에서는 표가 안 나고,
 *  그 값으로 주문이 나갑니다. */
export function inDomesticDay(at: number): boolean | null {
  const window = domesticSessions?.day?.trading
  if (!window) return null
  /* 시간표는 한국시간이라 지금도 한국시간으로 읽습니다. */
  const now = kstClock(at)
  /* 주간은 날을 안 넘습니다 — 넘는 것은 야간뿐입니다. */
  return now >= window.open && now <= window.close
}

/** 국내 품목의 규격 줄. **세션까지 받습니다** — 규격(틱·증거금)은 세션이 같아도
 *  같지만 **시간은 세션마다 다릅니다**. 규격만 보던 때는 주간 줄로 충분했으나,
 *  시각을 이 줄에서 읽게 되면서 어느 세션의 줄인지가 뜻을 갖습니다.
 *
 *  **품목코드만으로는 못 가립니다.** 코스피200 선물과 옵션이 같은 코드(`01`)로
 *  오므로 종류까지 맞춰야 합니다 — 응답이 종류 칸을 안 주어 이름의 「옵션」으로
 *  가릅니다. 표에 없는 품목(주식선물옵션)은 줄이 아예 없어 `null` 입니다. */
export function domesticProductDetail(
  productCode: string | null,
  kind: ProductKind,
  session: SessionName = 'day',
): DomesticProductDetail | null {
  if (!productCode) return null
  const option = kind === 'option'
  return (
    domesticProducts.find(
      (row) =>
        row.productCode === productCode &&
        row.session === session &&
        row.name.includes('옵션') === option,
    ) ?? null
  )
}

/** 국내 거래시간 한 벌 — 글자와 **그 값이 어디서 왔는가**.
 *
 *  시간표에 품목 줄이 있는 종목은 열에 하나꼴이라, 없는 종목의 시각을 비우면
 *  대부분의 화면에서 시각이 사라집니다. 그래서 없을 때는 시장 공통값을 세우되
 *  **그 사실을 화면이 말할 수 있게** 출처를 함께 냅니다. */
export interface DomesticHours {
  /** 「08:45~15:45」. 품목 줄에도 공통 표에도 없으면 빈 문자열입니다. */
  text: string
  /** 그 종목 품목 줄이 아니라 **시장 공통 표**에서 온 값인가. 빈 문자열이면
   *  거짓입니다 — 없는 값에는 출처가 없습니다. */
  common: boolean
}

/** 국내 품목의 거래시간(그 세션). **해외의 `overseasHoursOf` 와 짝입니다** —
 *  종목 화면이 시각을 읽는 자리는 이 둘뿐입니다. 품목 줄이 없으면 시장 공통값을
 *  내고 `common` 이 참입니다. */
export function domesticHoursFor(
  productCode: string | null,
  kind: ProductKind,
  session: SessionName,
): DomesticHours {
  const own = windowText(domesticProductDetail(productCode, kind, session)?.trading ?? null)
  if (own) return { text: own, common: false }
  const shared = domesticHours(session)
  return { text: shared, common: shared !== '' }
}

/** 국내 품목의 종가 단일가 구간(그 세션). 갈래는 위와 같습니다. */
export function domesticAuctionHoursFor(
  productCode: string | null,
  kind: ProductKind,
  session: SessionName,
): DomesticHours {
  const own = windowText(
    domesticProductDetail(productCode, kind, session)?.closingAuction ?? null,
  )
  if (own) return { text: own, common: false }
  const shared = domesticAuctionHours(session)
  return { text: shared, common: shared !== '' }
}

/** 이 종목의 그 세션 시각이 **시장 공통 표**에서 오는가 — 그 세션의 품목 줄이
 *  없는 종목입니다. 머리 띠가 판정이 함께 준 시각(다음 개장·재개)에도 같은 꼬리를
 *  달 때 씁니다: 품목 줄이 없으면 서버 판정도 공통 표로 내려가므로 그 시각 역시
 *  시장 값입니다. */
export function domesticHoursAreCommon(
  productCode: string | null,
  kind: ProductKind,
  session: SessionName,
): boolean {
  return domesticProductDetail(productCode, kind, session) === null
}

/** 국내 세션의 **시장 공통** 종가 단일가 구간. 위와 같은 까닭으로 품목 줄이 없는
 *  종목의 대체값이고, 밖에서는 `domesticAuctionHoursFor` 로만 닿습니다. */
function domesticAuctionHours(session: SessionName): string {
  return windowText(domesticSessions?.[session]?.closingAuction ?? null)
}

/** 해외 품목의 거래시간(한국시간). 시간표에 없는 품목은 빈 문자열입니다.
 *  **거래소를 늘 함께 받습니다** — 같은 품목코드가 거래소마다 따로 있습니다. */
export function overseasHoursOf(exchangeNo: string | null, productCode: string): string {
  return windowText(hoursRow(exchangeNo, productCode)?.trading ?? null)
}

/** 해외 품목의 시간표 줄 전부 — 품목정보 탭이 거래소·통화·창들을 읽습니다.
 *  시간표를 못 받았거나 없는 품목이면 `null` 입니다. */
export function overseasProductHours(
  exchangeNo: string | null,
  productCode: string,
): OverseasProductHours | null {
  return hoursRow(exchangeNo, productCode)
}

/** 그 품목의 장중 쉼이 **점심 휴장**인가 — 1차 끝과 2차 시작 사이(같은 날)가
 *  11:00~15:00 안에 들면 그렇습니다(홍콩 등). 그 밖의 쉼은 정비 시간으로 봅니다. */
export function overseasBreakIsLunch(exchangeNo: string | null, productCode: string): boolean {
  const row = hoursRow(exchangeNo, productCode)
  const first = row?.trading
  const second = row?.second
  if (!first || !second || first.nextDay || second.nextDay) return false
  return first.close >= '11:00' && second.open <= '15:00' && first.close < second.open
}

/** 한 종목의 세션 창들 — 차트가 봉을 세션으로 가르는 데 씁니다. 국내는 주간·야간,
 *  해외는 그 품목의 1차·2차·익일 창. 시간표를 못 받았거나 품목이 없으면 빈 배열이고,
 *  그때 차트는 경계를 모르는 것으로 둡니다. */
export function sessionWindows(market: Market, exchangeNo: string | null, productCode: string): Window[] {
  if (market === 'domestic') {
    if (!domesticSessions) return []
    return [domesticSessions.day.trading, domesticSessions.night.trading]
  }
  const item = hoursRow(exchangeNo, productCode)
  if (!item) return []
  return [item.trading, item.second, item.nextDayTrading].filter(
    (window): window is Window => window !== null && window !== undefined,
  )
}
