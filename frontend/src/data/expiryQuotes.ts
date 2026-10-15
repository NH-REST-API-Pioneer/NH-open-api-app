/** 만기 목록의 값을 받아 두는 자리.
 *
 *  만기 드롭다운·차트 칸 배지·종목 화면의 월물 줄이 같은 목록을 봅니다. 신원(어떤
 *  월물이 상장되어 있는지)은 종목 마스터가 주고, **값은 여기가 받아 옵니다.**
 *
 *  **시장마다 부르는 길이 다릅니다.**
 *  국내 선물은 품목 하나의 월물이 한 번에 오는 조회가 있습니다(`/api/domestic/price-all`).
 *  해외는 그런 조회가 없어 월물 코드를 목록으로 실어 보내면 서버가 나눠 부르고
 *  합칩니다(`/api/overseas/price`) — 그래서 월물이 많으면 답이 그만큼 늦습니다.
 *
 *  **옵션 품목은 안 부릅니다.** 만기마다 전체 옵션 시세를 받아야 해서 목록 하나를
 *  채우자고 낼 조회가 아닙니다 — 그 자리는 빈 채로 둡니다. 스프레드도 부르는 길이
 *  없어 같습니다.
 *
 *  **값이 없는 월물은 빈 채입니다.** 조회에 안 실려 온 월물(해외의 기록 없는 월물)을
 *  지어내지 않습니다 — 목록의 숫자는 그 월물로 주문을 낼지 고르는 근거입니다.
 *
 *  **동기로 읽습니다.** 목록을 그리는 도중에 불리므로 기다리게 만들 수 없습니다.
 *  받아 둔 것을 얹기만 하고, 부르는 일은 목록이 열려 있는 동안만 훅이 합니다.
 *
 *  **국내 야간에는 근월부터 넷을 야간 값으로 받습니다.** 월물 줄의 수는 그 월물을
 *  열었을 때 머리에 서는 값과 같은 출처라야 합니다 — 야간에 머리는 야간 값을
 *  보이는데 목록이 주간 마감을 보이면 한 화면이 두 말을 합니다. 야간 선물을 한
 *  번에 주는 조회가 없어 월물마다 묻고, 그래서 근월 넷까지만 묻습니다. 나머지는
 *  주간 마감 그대로 두고 **흐리게** 세웁니다(`closeOnly`).
 */
import { useEffect, useSyncExternalStore } from 'react'

import { accepts, environmentState, generation, onEnvironmentChange } from './environment'
import { contractsOf, marketOf } from './instruments'
import { noteQuoteArrival } from './lastQuote'
import { domesticProductDetail, sessionEntry, useSession, type SessionName } from './session'
import type { ContractRow, Product, ProductKind } from '../lib/types'

/** 한 월물의 값. **없는 칸은 `null`** 입니다 — 0 은 값이고 없음이 아닙니다. */
export interface ExpiryQuote {
  last: number | null
  change: number | null
  changePct: number | null
  open: number | null
  high: number | null
  low: number | null
  volume: number | null
  openInterest: number | null
}

interface Entry {
  status: 'idle' | 'loading' | 'ready' | 'failed'
  /** 종목코드 → 값. 아직 안 받았으면 `null` 입니다. */
  rows: Map<string, ExpiryQuote> | null
}

const EMPTY: Entry = { status: 'idle', rows: null }

const entries = new Map<string, Entry>()
const listeners = new Set<() => void>()
/* 값이 몇 번 바뀌었는지. **담는 자리가 Map 하나라** 그 참조로는 바뀐 것을 알 수
   없어, 세어 둔 수로 화면에 알립니다. */
let version = 0
/** 지금 나가 있는 물음과 그것을 낸 세대. 겹쳐 묻지 않는 데 씁니다. */
const flying = new Map<string, number>()

/** 담는 열쇠. 같은 품목 코드가 두 시장에 있을 수 있어 시장이 함께 들고, **주간
 *  값과 야간 값은 따로** 담습니다 — 한 자리에 담으면 서로를 덮어, 낮으로 돌아온
 *  목록에 야간 값이 남습니다. */
function keyOf(product: Product, market: string, session: SessionName = 'day'): string {
  return `${market}|${product.code}|${session}`
}

function announce(key: string, next: Entry): void {
  entries.set(key, next)
  version += 1
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** 값을 부를 수 있는 자리인지. **선물뿐입니다** — 옵션은 만기마다 전체 시세를
 *  받아야 하고, 스프레드는 부르는 길이 없습니다. */
function askable(kind: ProductKind): boolean {
  return kind === 'futures'
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function quoteOf(row: Record<string, unknown>): ExpiryQuote {
  return {
    last: num(row.last),
    change: num(row.change),
    changePct: num(row.changePct),
    open: num(row.open),
    high: num(row.high),
    low: num(row.low),
    volume: num(row.volume),
    openInterest: num(row.openInterest),
  }
}

/* ── 부르기 ────────────────────────────────────────────── */

/** 한 번 묻습니다. 같은 품목이 나가 있으면 겹쳐 묻지 않습니다. */
export async function loadExpiryQuotes(product: Product, kind: ProductKind): Promise<void> {
  if (!askable(kind)) return
  const market = marketOf(product)
  const key = keyOf(product, market)
  const since = generation()
  if (flying.get(key) === since) return

  /* 부를 인자가 없으면 묻지 않습니다 — 국내는 품목의 거래대상코드, 해외는
     거래소 코드가 있어야 합니다. 지어낸 인자로 다른 품목을 받아 오지 않습니다. */
  const refs = contractsOf(product, kind)
  if (refs.length === 0) return
  const path = market === 'overseas' ? '/api/overseas/price' : '/api/domestic/price-all'
  let body: Record<string, unknown>
  if (market === 'overseas') {
    if (!product.exchangeCode) return
    /* **근월 열두 개까지만 묻습니다.** 해외는 월물마다 따로 부르는 길뿐이라
       서버가 나눠 부르는데, 월물이 서른여섯인 품목(원유)에서는 한 번 묻는 데
       시세 호출을 그만큼 써서 헤더·호가·체인이 같은 한도 안에서 밀립니다.
       뒤쪽 월물은 값이 빈 채로 섭니다 — 목록에서 고르는 것은 앞쪽 몇 개이고,
       없는 값을 지어내지 않는다는 규칙은 그대로입니다. */
    const near = [...refs]
      .sort((a, b) => (a.expiry < b.expiry ? -1 : a.expiry > b.expiry ? 1 : 0))
      .slice(0, OVERSEAS_ASK_LIMIT)
    body = { syms: near.map((row) => ({ exch_cd: product.exchangeCode, sym: row.code })) }
  } else {
    if (!product.tradeCode) return
    body = { prd: product.tradeCode }
  }

  flying.set(key, since)
  const held = entries.get(key) ?? EMPTY
  announce(key, { ...held, status: held.rows ? 'ready' : 'loading' })

  try {
    const response = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (since !== generation()) return
    if (!accepts(response, since)) return
    if (!response.ok) {
      announce(key, { ...held, status: held.rows ? 'ready' : 'failed' })
      return
    }
    const reply = (await response.json()) as { rows?: unknown; quotes?: unknown }
    const list = Array.isArray(reply.rows)
      ? reply.rows
      : Array.isArray(reply.quotes)
        ? reply.quotes
        : []
    /* **값은 종목코드로 맞춥니다.** 답의 만기 표기(`expiryMonth` 「26/09」)는
       마스터의 만기(`202609`)와 모양이 달라 짝을 지을 수 없고, 차례로 맞추면
       한 월물이 빠진 답에서 줄이 통째로 밀립니다. */
    const made = new Map<string, ExpiryQuote>()
    for (const row of list as Record<string, unknown>[]) {
      const code = String(row.code ?? '').trim()
      if (code) made.set(code, quoteOf(row))
    }
    announce(key, { status: 'ready', rows: made })
    noteQuoteArrival()
  } catch {
    if (since !== generation()) return
    announce(key, { ...held, status: held.rows ? 'ready' : 'failed' })
  } finally {
    if (flying.get(key) === since) flying.delete(key)
  }
}

/* ── 국내 야간 ─────────────────────────────────────────── */

/** 야간에 야간 값으로 묻는 월물 수. **근월부터 이만큼**입니다 — 월물마다 따로
 *  묻는 길뿐이라 이 수가 곧 한 번의 시세 호출 수입니다(해외 근월 제한과 같은 장치). */
const NIGHT_ASK_LIMIT = 4

/** 야간 월물을 차례로 물을 때 사이에 두는 간격(ms). 몰아서 내면 머리·호가가 같은
 *  한도 안에서 끼어들 틈이 없습니다. */
const NIGHT_GAP_MS = 100

/** 야간 창이 있는 품목인가. **시간표의 품목 줄**로 가릅니다 — 그 줄이 없는 품목은
 *  세션을 묻지 않고 주간 얼굴로 둡니다. */
function hasNightHours(product: Product, kind: ProductKind): boolean {
  return (
    askable(kind) &&
    marketOf(product) === 'domestic' &&
    domesticProductDetail(product.tradeCode ?? null, kind, 'night') !== null
  )
}

/** 만기가 가까운 차례의 월물 코드. */
function nearCodes(product: Product, kind: ProductKind): string[] {
  return [...contractsOf(product, kind)]
    .sort((a, b) => (a.expiry < b.expiry ? -1 : a.expiry > b.expiry ? 1 : 0))
    .map((row) => row.code)
}

/** 이 목록이 지금 야간 얼굴인가. **판정 기준 종목은 근월 하나**입니다 — 세션은
 *  종목마다의 답이라, 목록 전체를 한 종목의 답으로 가릅니다. 근월 세션을 아직 안
 *  물었으면 주간입니다(훅이 목록을 열 때 묻습니다). */
function nightNow(product: Product, kind: ProductKind): boolean {
  if (!hasNightHours(product, kind)) return false
  const near = nearCodes(product, kind)[0]
  return !!near && sessionEntry('domestic', near).session === 'night'
}

/** 이 목록이 모의투자의 국내 야간인가. **모의투자에서는 NH선물이 야간 현재가를
 *  제공하지 않아** 월물의 수는 모두 비우고, 그 동안은 목록 값을 아예 묻지 않습니다
 *  — 주간 마감으로 채우면 야간 값으로 읽힙니다. 한 번 물어보고 멈추는 종목 머리와 달리
 *  목록은 처음부터 묻지 않습니다. 월물마다 한 건씩 나가는 조회라, 안 되는 것을
 *  아는 채로 묻지 않습니다. */
export function expiryPaperNight(product: Product, kind: ProductKind): boolean {
  return environmentState().active === 'paper' && nightNow(product, kind)
}

/** 야간 목록의 세대. 목록이 닫히거나 주·야가 바뀌면 올려, 그 뒤에 온 답을
 *  버립니다 — 주간에 연 목록에 야간 답이 붙거나 그 반대가 되지 않게 합니다. */
const nightGen = new Map<string, number>()
/** 나가 있는 야간 물음의 세대. **겹침 막기를 세대로** 합니다 — 환경 세대로 막으면
 *  세션 답이 와서 목록이 다시 도는 순간, 낡은 물음이 아직 간격을 기다리는 동안
 *  새 물음이 막히고 낡은 물음은 스스로 그만두어, 다음 주기까지 아무것도 안 나갑니다. */
const nightFlying = new Map<string, number>()

function bumpNight(key: string): void {
  nightGen.set(key, (nightGen.get(key) ?? 0) + 1)
}

/** 근월부터 넷의 야간 값을 **차례로** 묻습니다. 앞 물음이 나가 있으면 겹쳐 묻지
 *  않습니다. 못 받은 월물은 빈 채입니다 — 주간 마감으로 메우면 야간으로 물은 것의
 *  답처럼 읽힙니다. */
async function loadNightQuotes(product: Product, kind: ProductKind): Promise<void> {
  if (!nightNow(product, kind)) return
  const key = keyOf(product, 'domestic', 'night')
  const since = generation()
  const mine = nightGen.get(key) ?? 0
  if (nightFlying.get(key) === mine) return
  const stale = () => generation() !== since || (nightGen.get(key) ?? 0) !== mine

  nightFlying.set(key, mine)
  const held = entries.get(key) ?? EMPTY
  const made = new Map(held.rows ?? [])
  announce(key, { ...held, status: held.rows ? 'ready' : 'loading' })
  try {
    for (const code of nearCodes(product, kind).slice(0, NIGHT_ASK_LIMIT)) {
      await new Promise((done) => setTimeout(done, NIGHT_GAP_MS))
      if (stale()) return
      let quote: ExpiryQuote | null = null
      try {
        const response = await fetch('/api/domestic/price-night', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sym: code }),
        })
        if (stale() || !accepts(response, since)) return
        if (response.ok) {
          const got = quoteOf((await response.json()) as Record<string, unknown>)
          quote = got.last === null ? null : got
        }
      } catch {
        quote = null
      }
      if (stale()) return
      if (quote) {
        made.set(code, quote)
        noteQuoteArrival()
      } else made.delete(code)
      announce(key, { status: 'ready', rows: new Map(made) })
    }
  } finally {
    if (nightFlying.get(key) === mine) nightFlying.delete(key)
  }
}

/** 한 번에 물어보는 해외 월물 수. **근월부터 이만큼**입니다 — 해외는 월물마다
 *  따로 부르는 길뿐이라 이 수가 곧 한 번의 시세 호출 수입니다. */
const OVERSEAS_ASK_LIMIT = 12

/** 만기 목록을 다시 묻는 간격. **체인(5초)보다 느립니다** — 이 목록의 값은 어느
 *  월물을 고를지 판단하는 값이지 그 값으로 주문을 내는 자리가 아닙니다. 헤더·호가·
 *  체인과 같은 호출 한도를 나눠 쓰므로, 고르는 데 쓰는 값이 보는 값을 밀지 않게
 *  두 시장 모두 이 간격입니다. */
export const EXPIRY_POLL_MS = 10_000

/** **목록이 열려 있는 동안만** 값을 받습니다.
 *
 *  `active` 가 거짓이면(드롭다운이 닫혀 있거나 다른 화면) 묻지 않고, 문서가 가려진
 *  동안에도 쉽니다 — 안 보는 목록에 시세 호출을 쓰지 않습니다. 다시 열리면 곧바로
 *  한 번 묻습니다. */
export function useExpiryQuotes(
  product: Product | null,
  kind: ProductKind,
  active: boolean,
): void {
  const market = product ? marketOf(product) : ''
  const key = product ? keyOf(product, market) : ''
  const askKind = askable(kind) ? kind : ''
  /* 야간 창이 있는 품목이면 **근월 하나의 세션**을 묻습니다 — 목록이 열려 있을
     때만입니다. 세션이 바뀌면 아래 효과가 다시 돌아 새 세션의 값을 받습니다. */
  const nearCode =
    product && active && hasNightHours(product, kind) ? (nearCodes(product, kind)[0] ?? '') : ''
  const session = useSession('domestic', nearCode).session

  useEffect(() => {
    if (!product || !active || !askable(kind)) return
    const nightKey = keyOf(product, market, 'night')
    let timer: number | undefined
    const ask = () => {
      /* 모의투자의 국내 야간이면 주간·야간 어느 쪽도 묻지 않습니다 — 수를 모두
         비워 세우는 자리라 받은 값을 쓸 데가 없습니다(`expiryPaperNight`). */
      if (document.hidden || expiryPaperNight(product, kind)) return
      void loadExpiryQuotes(product, kind)
      void loadNightQuotes(product, kind)
    }
    const onVisible = () => {
      if (!document.hidden) ask()
    }
    ask()
    timer = window.setInterval(ask, EXPIRY_POLL_MS)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      if (timer !== undefined) window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
      /* 목록이 닫히거나 세션이 바뀌면 나가 있던 야간 물음의 답을 버립니다. */
      bumpNight(nightKey)
    }
    // 품목은 열쇠로 비교합니다 — 객체를 그대로 두면 그릴 때마다 다시 시작합니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, askKind, active, session])
}

/** 받아 둔 값이 바뀌면 다시 그리게 합니다. 값 자체는 `contractRows` 로 읽습니다.
 *  돌려주는 수는 **바뀐 횟수**입니다 — 목록을 다시 셈하는 자리가 이 수를 함께
 *  보면 값이 올 때마다 다시 그립니다. */
export function useExpiryQuoteUpdates(): number {
  return useSyncExternalStore(
    subscribe,
    () => version,
    () => version,
  )
}

/* ── 읽기 ──────────────────────────────────────────────── */

/** 그 품목의 만기 목록 한 벌. **신원은 마스터, 값은 조회**입니다.
 *
 *  아직 안 받았거나 답에 없는 월물은 값 자리가 `null` 입니다 — 목록은 그 자리를
 *  비워 그립니다. */
export function contractRows(product: Product, kind: ProductKind): ContractRow[] {
  const refs = contractsOf(product, kind)
  if (refs.length === 0) return []
  const market = marketOf(product)
  const held = entries.get(keyOf(product, market))?.rows ?? null
  /* 야간이면 근월부터 넷은 야간 값(못 받았으면 빈 채), 나머지는 주간 마감을
     흐리게 세웁니다. 야간이 아니면 지금 그대로입니다. */
  const night = nightNow(product, kind)
  const nightHeld = night ? (entries.get(keyOf(product, market, 'night'))?.rows ?? null) : null
  const asked = new Set(night ? nearCodes(product, kind).slice(0, NIGHT_ASK_LIMIT) : [])
  /* 모의투자의 야간이면 월물 모두 빈 채입니다 — 흐린 주간 마감도 안 세웁니다. */
  const blank = night && expiryPaperNight(product, kind)

  const rows: ContractRow[] = refs.map((ref) => {
    const byNight = asked.has(ref.code)
    const quote = blank
      ? null
      : byNight
        ? (nightHeld?.get(ref.code) ?? null)
        : (held?.get(ref.code) ?? null)
    return {
      code: ref.code,
      name: `${product.name} ${ref.label}`,
      label: ref.label,
      kind: ref.kind,
      expiry: ref.expiry,
      /* **없는 값을 0으로 채우지 않습니다.** 해외 마스터에는 잔존일수가 안
         오는데 0으로 두면 화면이 「D-0」, 곧 오늘 만기라고 말합니다. */
      daysLeft: ref.daysLeft,
      /* 마스터에서 오는 종목의 성질입니다. 시세가 아니라 카탈로그에서도 씁니다.
         국내는 거래승수만, 해외는 호가단위만 옵니다 — 응답에 있는 것이 다릅니다. */
      multiplier: product.multiplier,
      tickSize: product.tickSize,
      tickDecimals: product.tickDecimals,
      frontMonth: false,
      /* 색인이 계약 행에 실어 준 주력 표시입니다. 조회 값이 아니라 마스터 값이라
         여기서 만들지 않고 그대로 옮깁니다. */
      main: ref.main,
      last: quote?.last ?? null,
      change: quote?.change ?? null,
      changePct: quote?.changePct ?? null,
      volume: quote?.volume ?? null,
      openInterest: quote?.openInterest ?? null,
      open: quote?.open ?? null,
      high: quote?.high ?? null,
      low: quote?.low ?? null,
      closeOnly: night && !byNight && !blank,
    }
  })

  /* 「최근 만기」 — **두 시장 다 만기가 가장 가까운 종목**입니다.
     거래량이 가장 많은 종목으로 고르는 방법도 있지만, **국내 마스터에 거래량
     기준 표시가 없어** 두 시장을 같은 축으로 세울 수 없습니다. 시장마다 축이
     다르면 같은 자리의 표시가 시장마다 다른 것을 뜻하게 됩니다.

     **이 표시는 값이 아니라 지시입니다.** 값이 틀리면 사용자가 잘못 읽고 끝나지만,
     이 표시가 틀리면 앱이 **틀린 종목을 열어 줍니다** — 주력 표시가 없는 시장
     (국내)에서는 비워 두고 열 때 서는 종목이 곧 이 종목입니다. 그래서 조회로
     오는 수(거래량)로는 정하지 않습니다.

     **스프레드에는 안 답니다** — 만기가 둘이라 「가장 가까운 것」이 한 값으로
     안 정해집니다. **행이 하나뿐일 때도 안 답니다** — 견줄 것이 없으면
     「가장 가깝다」가 아무것도 말하지 않습니다. */
  if (kind !== 'spread' && rows.length > 1) {
    rows.reduce((a, b) => (b.expiry < a.expiry ? b : a)).frontMonth = true
  }

  return rows
}

/* 환경(모의·실전)이 바뀌면 전부 지웁니다 — 다른 서버의 답입니다. 다른 저장소
   (`quotes.ts`·`optionChain.ts`)와 같은 규칙입니다. */
onEnvironmentChange((change) => {
  if (change.kind !== 'switched') return
  entries.clear()
  version += 1
  for (const listener of listeners) listener()
})
