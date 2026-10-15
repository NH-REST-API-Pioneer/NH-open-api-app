/** 옵션 체인을 받아 두는 자리 — 한 만기의 행사가마다 콜·풋 값 한 줄.
 *
 *  **묻는 인자마다 한 자리입니다.** 국내는 품목·만기·세션, 해외는 거래소·시리즈로
 *  갈립니다. 화면은 체인 탭이 보이는 동안 5초마다 다시 묻고(`useOptionChain`),
 *  답이 오면 줄을 통째로 갈아 끼웁니다 — 행 열쇠가 행사가라 표는 그대로 서고
 *  값만 바뀝니다.
 *
 *  **실패한 답은 받아 둔 표를 지우지 않습니다.** 5초 뒤 다음 답이 오고, 그동안
 *  낡은 표가 없는 표보다 낫습니다. 실패 사실은 상태에 남아 화면이 한 줄로 말합니다.
 *
 *  **손질은 하지 않습니다.** 서버가 값을 화면 모양으로 냅니다 — 가격 칸의 원문
 *  0 은 `null`(거래·호가 없음)이고 대비·미결제·거래량의 0 은 값입니다. 이름만
 *  마스터 것을 먼저 씁니다(응답 이름은 거래소 표기).
 */
import { useEffect, useSyncExternalStore } from 'react'

import { accepts, generation, onEnvironmentChange, paperUnavailable } from './environment'
import { registerChainLegs, resolve } from './instruments'
import { noteQuoteArrival } from './lastQuote'
import { domesticNightRound } from './session'
import type { ChainLeg, ChainRow } from '../lib/types'

/** 무엇을 물을지. 국내와 해외는 인자가 다릅니다. */
export type ChainArgs =
  | {
      market: 'domestic'
      /** 품목의 거래대상코드(마스터 `trd_code`, 코스피200 `01`). */
      prd: string
      /** 만기일 `YYMMDD`. 마스터 만기일(8자리)의 뒤 여섯 자리입니다. */
      expMon: string
      session: 'day' | 'night'
    }
  | {
      market: 'overseas'
      /** 옵션 거래소 코드(마스터 `ExchName`, `OCME`). */
      exchCd: string
      /** 시리즈 코드(`O_ESU26`). */
      sym: string
    }

/** 그 체인이 어느 품목·만기의 것인지. **서버에 보내는 값이 아니라** 답에 실려 온
 *  종목코드를 신원표(`data/instruments.ts`)에 적을 때 쓰는 값이라, 무엇을 물을지
 *  적는 `ChainArgs` 와 갈라 둡니다 — 한 덩어리에 섞으면 인자를 짓는 자리가 어느
 *  칸이 서버로 가는지 알 수 없습니다. */
export interface ChainOwner {
  /** 품목코드(마스터 표기). */
  productCode: string
  /** 만기(마스터 표기). 국내는 8자리, 해외는 6자리입니다. */
  expiry: string
}

export interface ChainFuture {
  code: string
  last: number | null
  change: number | null
  changePct: number | null
  daysLeft: number | null
}

export interface ChainEntry {
  /** `idle` 은 아직 안 물어봤다는 뜻입니다. */
  status: 'idle' | 'loading' | 'ready' | 'failed'
  /** **`null` 은 「받은 적 없다」**, 빈 배열은 「받았는데 그 만기에 줄이 없다」입니다. */
  rows: ChainRow[] | null
  /** 당월 선물. 국내 주간에만 값이 있고, 야간과 해외는 `null` 입니다. */
  future: ChainFuture | null
  /** 이 답이 어느 세션의 것인지(국내). 야간은 시세가 없어 전일종가·미결제만 값입니다. */
  session: 'day' | 'night' | null
  /** 서버가 답을 만든 시각(한국시간 ISO). */
  asOf: string | null
  /** 마지막 물음이 실패했으면 그 까닭. 받아 둔 줄은 그대로입니다. `paper` 는
   *  모의투자에서는 NH선물이 이 조회를 제공하지 않는다는 답입니다(국내 야간). */
  failure: 'retry' | 'rejected' | 'paper' | null
}

const EMPTY: ChainEntry = {
  status: 'idle',
  rows: null,
  future: null,
  session: null,
  asOf: null,
  failure: null,
}

const entries = new Map<string, ChainEntry>()
const listeners = new Set<() => void>()
/** 나가 있는 물음과 그 세대. 같은 인자를 겹쳐 묻지 않습니다. */
const flying = new Map<string, number>()

/** 모의투자라 국내 야간 옵션 시세를 받을 수 없다는 답을 받은 **야간 회차**. 한 번
 *  받으면 그 회차가 끝날 때까지 국내 야간 체인을 더 부르지 않습니다 — 만기를
 *  바꿔도, 5초 주기가 와도 같습니다. 주간 체인은 이 값을 보지 않고, 다음 야간은
 *  새 회차라 다시 한 번 물어봅니다. 환경이 바뀌면 지우고, 메모리에만 둡니다.
 *  현재가의 같은 표시(`quotes.ts`)와는 따로 둡니다 — 조회가 다릅니다. */
let paperNightShut: number | null = null

function nightChain(args: ChainArgs): boolean {
  return args.market === 'domestic' && args.session === 'night'
}

export function chainKey(args: ChainArgs): string {
  return args.market === 'domestic'
    ? `domestic|${args.prd}|${args.expMon}|${args.session}`
    : `overseas|${args.exchCd}|${args.sym}`
}

function announce(key: string, next: ChainEntry): void {
  entries.set(key, next)
  for (const listener of listeners) listener()
}

export function subscribeChain(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function chainEntry(args: ChainArgs | null): ChainEntry {
  return args ? (entries.get(chainKey(args)) ?? EMPTY) : EMPTY
}

/* ── 응답 모양 ───────────────────────────────────────── */

interface LegReply {
  code?: string
  name?: string
  last?: number | null
  prevClose?: number | null
  change?: number | null
  changePct?: number | null
  bid?: number | null
  ask?: number | null
  bidQty?: number | null
  askQty?: number | null
  openInterest?: number | null
  openInterestChange?: number | null
  volume?: number | null
  theory?: number | null
  theoryChange?: number | null
  iv?: number | null
  disparityPct?: number | null
  delta?: number | null
  gamma?: number | null
  theta?: number | null
  vega?: number | null
  atm?: boolean
}

interface ChainReply {
  market?: string
  session?: string
  future?: ChainFuture | null
  rows?: { strike: number; call: LegReply; put: LegReply }[]
  asOf?: string
}

function num(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/** 응답 한쪽을 화면 줄로. **칸 이름만 화면 것으로 바꾸고 값은 그대로**입니다. */
function toLeg(reply: LegReply): ChainLeg {
  const code = String(reply.code ?? '')
  return {
    code,
    /* 이름은 마스터가 먼저입니다 — 응답 이름은 거래소 표기라 화면의 다른 자리와
       다르게 불립니다. 마스터에 없으면 응답 이름을 그대로 둡니다. */
    name: (code && resolve(code)?.name) || String(reply.name ?? ''),
    last: num(reply.last),
    prevClose: num(reply.prevClose),
    change: num(reply.change),
    changePct: num(reply.changePct),
    volume: num(reply.volume),
    openInterest: num(reply.openInterest),
    oiChange: num(reply.openInterestChange),
    delta: num(reply.delta),
    gamma: num(reply.gamma),
    theta: num(reply.theta),
    vega: num(reply.vega),
    iv: num(reply.iv),
    theo: num(reply.theory),
    theoDiff: num(reply.theoryChange),
    disparity: num(reply.disparityPct),
    bid: num(reply.bid),
    ask: num(reply.ask),
    bidQty: num(reply.bidQty),
    askQty: num(reply.askQty),
    atm: reply.atm === true,
  }
}

function bodyOf(args: ChainArgs): Record<string, string> {
  return args.market === 'domestic'
    ? { prd: args.prd, exp_mon: args.expMon, session: args.session }
    : { exch_cd: args.exchCd, sym: args.sym }
}

/** 한 번 묻습니다. 같은 인자가 나가 있으면 겹쳐 묻지 않습니다. */
export async function loadChain(args: ChainArgs, owner: ChainOwner): Promise<void> {
  const key = chainKey(args)
  const since = generation()
  if (flying.get(key) === since) return
  const held = entries.get(key) ?? EMPTY
  if (nightChain(args) && paperNightShut === domesticNightRound()) {
    if (held.failure !== 'paper') announce(key, { ...held, status: held.rows ? 'ready' : 'failed', failure: 'paper' })
    return
  }
  flying.set(key, since)
  announce(key, { ...held, status: held.rows ? 'ready' : 'loading' })

  try {
    const response = await fetch(`/api/${args.market}/option-chain`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(bodyOf(args)),
    })
    if (since !== generation()) return
    if (!accepts(response, since)) return
    if (!response.ok) {
      /* 모의투자라 못 받는다는 답은 까닭이 정해져 있어 따로 둡니다. 502 는 거절이라
         다시 불러도 같은 답이고, 그 밖(시간 초과 등)은 다음 물음이 메울 수
         있습니다. 받아 둔 줄은 그대로입니다. */
      const paper = paperUnavailable(response)
      if (paper && nightChain(args)) paperNightShut = domesticNightRound()
      announce(key, {
        ...held,
        status: held.rows ? 'ready' : 'failed',
        failure: paper ? 'paper' : response.status === 502 ? 'rejected' : 'retry',
      })
      return
    }
    const reply = (await response.json()) as ChainReply
    const rows: ChainRow[] = (Array.isArray(reply.rows) ? reply.rows : []).map((row) => ({
      strike: row.strike,
      call: toLeg(row.call ?? {}),
      put: toLeg(row.put ?? {}),
    }))
    /* 답에 실려 온 종목코드를 신원표에 적습니다. 해외 옵션 종목은 마스터에 없어
       여기 적어야 그 코드로 낸 조회가 해외 길로 나가고, 국내 옵션은 마스터에 행이
       있어도 **행사가 칸이 없어** 여기서만 알 수 있습니다. */
    registerChainLegs(
      owner.productCode,
      owner.expiry,
      rows.flatMap((row) => [
        { code: row.call.code, side: 'call' as const, strike: row.strike },
        { code: row.put.code, side: 'put' as const, strike: row.strike },
      ]),
    )
    announce(key, {
      status: 'ready',
      rows,
      future: reply.future
        ? {
            code: String(reply.future.code ?? ''),
            last: num(reply.future.last),
            change: num(reply.future.change),
            changePct: num(reply.future.changePct),
            daysLeft: num(reply.future.daysLeft),
          }
        : null,
      session: reply.session === 'day' || reply.session === 'night' ? reply.session : null,
      asOf: reply.asOf ?? null,
      failure: null,
    })
    noteQuoteArrival()
  } catch {
    if (since !== generation()) return
    announce(key, { ...held, status: held.rows ? 'ready' : 'failed', failure: 'retry' })
  } finally {
    if (flying.get(key) === since) flying.delete(key)
  }
}

export function retryChain(args: ChainArgs, owner: ChainOwner): void {
  void loadChain(args, owner)
}

/** 체인을 다시 묻는 간격. 값이 5초 안에 바뀌어도 그 사이는 안 보입니다 —
 *  체인은 한 번에 시세 호출이 두세 건이라 더 자주 물으면 다른 조회가 밀립니다. */
export const CHAIN_POLL_MS = 5000

/** 체인을 읽고, **이 자리가 보이는 동안만** 5초마다 다시 묻습니다.
 *
 *  `active` 가 거짓이면(다른 탭을 보는 중) 묻지 않고 받아 둔 것만 돌려줍니다.
 *  문서가 가려진 동안(`document.hidden`)도 쉽니다 — 안 보는 화면에 시세 호출을
 *  쓰지 않습니다. 다시 보이면 곧바로 한 번 묻습니다. */
export function useOptionChain(
  args: ChainArgs | null,
  owner: ChainOwner | null,
  active: boolean,
): ChainEntry {
  const key = args ? chainKey(args) : ''
  const entry = useSyncExternalStore(
    subscribeChain,
    () => chainEntry(args),
    () => EMPTY,
  )
  useEffect(() => {
    if (!args || !owner || !active) return
    let timer: number | undefined
    const ask = () => {
      if (document.hidden) return
      void loadChain(args, owner)
    }
    const onVisible = () => {
      if (!document.hidden) ask()
    }
    ask()
    timer = window.setInterval(ask, CHAIN_POLL_MS)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      if (timer !== undefined) window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
    // 인자는 열쇠로 비교합니다 — 객체를 그대로 두면 그릴 때마다 다시 시작합니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, active, owner?.productCode, owner?.expiry])
  return entry
}

/* 환경(모의·실전)이 바뀌면 전부 지웁니다 — 다른 계좌의 값은 아니지만 다른 서버의
   답이고, 5초 뒤 새 환경의 답이 올 때까지 옛 체인이 새 배지 밑에 서면 안 됩니다.
   다른 저장소(`quotes.ts`·`account.ts`)와 같은 규칙입니다. */
onEnvironmentChange((change) => {
  if (change.kind !== 'switched') return
  entries.clear()
  paperNightShut = null
  for (const listener of listeners) listener()
})
