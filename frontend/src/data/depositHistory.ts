/** 날짜별 예탁자산·손익 — 추이 탭이 그리는 재료.
 *
 *  **NH선물에는 날짜별 줄을 주는 계좌 조회가 없습니다.** 예수금은 하루치만
 *  오므로, 추이는 **하루씩 물어 이어 붙인 값**입니다. 서버가 받은 날을 쌓아
 *  두므로 다음부터는 빠진 날만 물으면 됩니다(`backend/deposit_history.py`).
 *
 *  **걷기는 이 자리에서 돕니다.** 화면 안에서 돌리면 탭을 떠나는 순간 멈추는데,
 *  스물두 날을 받는 데 십여 초가 걸려 그동안 다른 탭을 볼 수 없게 됩니다.
 *
 *  **한 번에 한 시장만 걷습니다.** 계좌 조회에는 초당 한도가 있고 잔고·미체결이
 *  같은 한도를 나눠 쓰므로, 두 시장을 함께 걸으면 보고 있는 탭이 밀립니다.
 */
import { useEffect, useSyncExternalStore } from 'react'
import type { DepositMarket, DomesticDeposit, OverseasDeposit } from './account'
import { FILL_GAP, isDomesticDeposit } from './account'
import { accepts, environmentOf, generation } from './environment'
import { addDays, daysBetween, kstDate, weekdayOf } from '../lib/kst'

/** 하루치. `value` 는 그날 받은 **화면용 예수금 한 벌** 그대로입니다 — 오늘 값과
 *  추이가 같은 칸을 읽게 하려는 것입니다. */
export interface HistoryDay {
  day: string
  value: DomesticDeposit | OverseasDeposit
}

export interface HistoryState {
  status: 'idle' | 'loading' | 'ready' | 'failed'
  /** 지금 담긴 값이 어느 기간의 것인가. `YYYYMMDD` 둘입니다. */
  period: { from: string; to: string } | null
  days: HistoryDay[]
  /** 아직 안 받은 날. 주말과 「받았는데 값이 없던 날」은 서버가 빼고 줍니다. */
  missing: string[]
  /** 받아 두었어도 **다시 물을 날**(기간 안 최근 두 영업일, 오늘 포함). 그 무렵
   *  값은 정산 전이었을 수 있어, 쌓인 값을 그대로 두면 틀린 값이 남습니다. */
  refresh: string[]
  /** 지금 빠진 날을 받고 있나. */
  filling: boolean
  /** 이번 걷기에서 **받은 날 수**와 **받을 날 수**. 「18 / 22일」의 두 수입니다. */
  filled: number
  target: number
  /** 서버가 쌓아 둔 파일을 읽었나. 못 읽으면 지난 값이 통째로 비어 보입니다. */
  stored: boolean
}

const EMPTY: HistoryState = {
  status: 'idle',
  period: null,
  days: [],
  missing: [],
  refresh: [],
  filling: false,
  filled: 0,
  target: 0,
  stored: true,
}

/** 하루치를 받는 데 걸리는 시간(ms). 화면이 「약 M초」를 적을 때 씁니다.
 *
 *  **잰 값으로 시작해 받을 때마다 고칩니다** — 망이 느린 곳에서는 안내도 그만큼
 *  길어져야 합니다. 처음 값은 재생 서버에서 잰 것(조회 + 간격)입니다. */
let dayCost = 700

function noteCost(spent: number): void {
  if (spent <= 0 || spent > 20_000) return
  dayCost = Math.round((dayCost + spent + FILL_GAP) / 2)
}

/** 그만큼 받는 데 걸릴 시간(초). 0 이면 0 입니다. */
export function askSeconds(days: number): number {
  return Math.max(Math.round((days * dayCost) / 1000), days > 0 ? 1 : 0)
}

/** 그 기간의 영업일 전부. **서버가 묻는 날과 같은 셈**입니다(주말 제외) —
 *  가로축을 이 날들로 깔아야 양 끝의 빠진 구간이 그림에 남습니다. */
export function periodDays(from: string, to: string): string[] {
  const made: string[] = []
  const count = daysBetween(from, to)
  for (let step = 0; step <= count && made.length < 400; step += 1) {
    const day = addDays(from, step)
    const week = weekdayOf(day)
    if (week !== 0 && week !== 6) made.push(day)
  }
  return made
}

const states = new Map<DepositMarket, HistoryState>()
const listeners = new Set<() => void>()
/** 걷는 중인 시장과 그 걸음의 번호. 번호가 달라지면 앞 걷기는 스스로 멈춥니다. */
let walking: DepositMarket | null = null
let walk = 0

function announce(market: DepositMarket, next: HistoryState): void {
  states.set(market, next)
  for (const listener of listeners) listener()
}

function patch(market: DepositMarket, next: Partial<HistoryState>): void {
  announce(market, { ...(states.get(market) ?? EMPTY), ...next })
}

export function historyState(market: DepositMarket): HistoryState {
  return states.get(market) ?? EMPTY
}

export function subscribeHistory(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useDepositHistory(market: DepositMarket): HistoryState {
  return useSyncExternalStore(
    subscribeHistory,
    () => historyState(market),
    () => EMPTY,
  )
}

/** 그날 그릴 값 둘. **머리 띠와 같은 칸을 읽습니다** — 그래프의 마지막 점과
 *  머리의 숫자가 다르면 어느 쪽을 믿어야 할지 알 수 없습니다. */
export function assetsOf(value: DomesticDeposit | OverseasDeposit): number | null {
  const rows = isDomesticDeposit(value) ? value.items : value.groups
  return rows.find((row) => row.key === 'assets')?.values[0] ?? null
}

/** 손익 칸 하나. **서버가 준 칸 이름 그대로** 적습니다 — 시장마다 주는 칸이
 *  달라, 같은 낱말로 묶으면 다른 값을 같은 것으로 부르게 됩니다. */
export interface ProfitRow {
  label: string
  value: number | null
}

/** 그날 **닫혀서 정해진** 손익. 누적 곡선과 달력이 이 값을 씁니다.
 *
 *  **국내는 정산차금에서 수수료를 뺀 순손익입니다** — 주간·야간 정산차금을 더하고
 *  주간·야간 수수료를 뺍니다. 그날 계좌에 들고 나는 돈(익일결제금액)과 같은 셈입니다.
 *  주간 정산차금이나 주간 수수료가 비면 그날은 값 없는 날이고, 야간 두 칸이 비면
 *  야간 거래가 없던 날이라 0 으로 봅니다.
 *
 *  **해외는 실현손익에서 수수료를 뺀 순손익입니다.** 실현손익 칸은 수수료를 빼기
 *  전 값이라, 그대로 더하면 수수료만큼 손실이 난 날도 이익으로 보입니다. 두 칸
 *  가운데 하나라도 비면 그날은 값 없는 날입니다 — 빠진 수수료를 0 으로 세면 같은
 *  잘못이 다시 생깁니다. */
export function realisedOf(value: DomesticDeposit | OverseasDeposit): ProfitRow {
  if (isDomesticDeposit(value)) {
    const settled = value.futuresSettlement ?? null
    const fee = value.fee ?? null
    if (settled === null || fee === null) return { label: '순손익', value: null }
    return {
      label: '순손익',
      value: settled + (value.nightSettlement ?? 0) - fee - (value.nightFee ?? 0),
    }
  }
  const realised = value.items.find((r) => r.key === 'realisedPl')?.value ?? null
  const fee = value.items.find((r) => r.key === 'fee')?.value ?? null
  return { label: '순손익', value: realised === null || fee === null ? null : realised - fee }
}

/** 그날 값이 **정산 전 잠정 값**인가 — 오늘(한국 달력) 받은 값입니다. 장중에는
 *  계속 바뀌고, 다음 영업일에 다시 받으면 정산된 값으로 바뀝니다. */
export function isProvisional(day: string): boolean {
  return day === kstDate()
}

/** 선으로 잇는 손익. **아직 안 닫힌 값**이라 날마다 다시 세는 값이 아닙니다 —
 *  그래서 막대가 아니라 선입니다.
 *
 *  **국내에는 이 칸이 없습니다**(옵션평가손익뿐이라 선물이 빠집니다). 없는
 *  시장에서는 선을 안 긋습니다 — 반쪽짜리 값을 「평가손익」이라 부르지 않습니다. */
export function unrealisedOf(value: DomesticDeposit | OverseasDeposit): ProfitRow | null {
  if (isDomesticDeposit(value)) return null
  return {
    label: '평가손익',
    value: value.items.find((r) => r.key === 'unrealisedPl')?.value ?? null,
  }
}

/* ── 추이 요약 — 카드·누적 곡선·달력이 함께 쓰는 셈 ─────────────
 *
 * **셈은 여기 한 자리입니다.** 카드의 기간 손익과 곡선의 끝 값, 달력의 칸이 서로
 * 다른 셈을 하면 한 화면이 같은 기간을 두고 다른 수를 말합니다. */

/** 달력 칸 짙기의 문턱. 기간 안 |손익| 최대에 견준 몫이 이 값 이하면 그 단입니다
 *  (마지막 단은 나머지 전부). 이익과 손실이 같은 최대를 씁니다 — 따로 재면 작은
 *  손실이 큰 이익과 같은 짙기로 섭니다. */
export const SHADE_STEPS = [1 / 3, 2 / 3] as const

/** 누적 곡선의 한 점. `slot` 은 기간 안 몇 번째 영업일인가, `value` 는 그날까지의
 *  누적, `daily` 는 그날 하루치입니다. */
export interface CumulativePoint {
  slot: number
  value: number
  daily: number
}

export interface TrendSummary {
  /** 받은 첫날·끝날의 예탁자산. 예탁자산 칸이 있는 날 가운데 처음과 끝입니다. */
  first: { day: string; assets: number } | null
  last: { day: string; assets: number } | null
  /** 기간 손익 = 받은 날 손익의 합(= 누적 곡선의 끝 값). 손익이 선 날이 없으면 `null`. */
  total: number | null
  /** 기간 손익 ÷ 받은 첫날 예탁자산. 첫날 예탁이 없거나 0 이하면 `null`. */
  ratio: number | null
  gainDays: number
  lossDays: number
  /** 손익이 0 인 날. 이익일·손실일 어디에도 세지 않습니다. */
  zeroDays: number
  /** 기간 영업일 가운데 손익 값이 서지 않은 날(안 받았거나 칸이 비었음). 누적에 안 더합니다. */
  blankDays: number
  /** 가장 큰 이익날·손실날. 그런 날이 없으면 `null`. */
  best: { day: string; value: number } | null
  worst: { day: string; value: number } | null
  cumulative: CumulativePoint[]
  /** 기간 안 |손익| 최대. 달력 짙기의 기준입니다. 0 이면 짙기가 없습니다. */
  widest: number
}

/** 기간의 요약을 셉니다.
 *
 *  **날마다의 손익은 그날 하루치로 보고 더합니다.** 국내 정산차금은 그날 하루의
 *  정산입니다. 해외 실현손익이 그날 하루치인지 이미 쌓인 값인지는 명세에 적혀 있지
 *  않습니다 — 같은 답의 수수료가 하루치라 손익도 하루치로 봅니다. 쌓인 값으로
 *  읽어야 하면 이 함수의 더하기만 바꾸면 됩니다.
 *
 *  평가손익은 그 시점의 크기라 더하지 않습니다(여기서 다루지 않습니다). 손익 값이
 *  없는 날은 0 으로 더하지 않고 건너뜁니다 — 0 으로 더하면 「그날 손익이 0 이었다」가
 *  됩니다. */
export function trendSummary(days: HistoryDay[], slots: string[]): TrendSummary {
  const at = new Map(slots.map((day, index) => [day, index]))
  let first: TrendSummary['first'] = null
  let last: TrendSummary['last'] = null
  let running = 0
  let counted = 0
  let gainDays = 0
  let lossDays = 0
  let zeroDays = 0
  let best: TrendSummary['best'] = null
  let worst: TrendSummary['worst'] = null
  let widest = 0
  const cumulative: CumulativePoint[] = []
  for (const one of [...days].sort((a, b) => (a.day < b.day ? -1 : a.day > b.day ? 1 : 0))) {
    const slot = at.get(one.day)
    if (slot === undefined) continue
    const assets = assetsOf(one.value)
    if (assets !== null && Number.isFinite(assets)) {
      if (first === null) first = { day: one.day, assets }
      last = { day: one.day, assets }
    }
    const daily = realisedOf(one.value).value
    if (daily === null || !Number.isFinite(daily)) continue
    counted += 1
    running += daily
    cumulative.push({ slot, value: running, daily })
    widest = Math.max(widest, Math.abs(daily))
    if (daily > 0) {
      gainDays += 1
      if (best === null || daily > best.value) best = { day: one.day, value: daily }
    } else if (daily < 0) {
      lossDays += 1
      if (worst === null || daily < worst.value) worst = { day: one.day, value: daily }
    } else {
      zeroDays += 1
    }
  }
  const total = counted > 0 ? running : null
  return {
    first,
    last,
    total,
    ratio: total !== null && first !== null && first.assets > 0 ? total / first.assets : null,
    gainDays,
    lossDays,
    zeroDays,
    blankDays: slots.length - counted,
    best,
    worst,
    cumulative,
    widest,
  }
}

/** 달력 칸의 짙기 단. 0 이면 색이 없습니다(값 0, 또는 기간 최대가 0). */
export function shadeOf(value: number, widest: number): 0 | 1 | 2 | 3 {
  if (value === 0 || !(widest > 0) || !Number.isFinite(value)) return 0
  const share = Math.abs(value) / widest
  if (share <= SHADE_STEPS[0]) return 1
  if (share <= SHADE_STEPS[1]) return 2
  return 3
}

/** 그릴 것이 하나도 없는 날인가. 그런 날은 **점을 안 찍습니다** — 0 으로 찍으면
 *  없는 값이 값으로 보입니다. */
function drawable(value: DomesticDeposit | OverseasDeposit): boolean {
  return (
    assetsOf(value) !== null ||
    realisedOf(value).value !== null ||
    (unrealisedOf(value)?.value ?? null) !== null
  )
}

interface HistoryReply {
  days?: (Record<string, unknown> & { day?: string })[]
  missing?: string[]
  refresh?: string[]
  store?: { status?: string }
}

/** 다시 물을 날. 서버가 `refresh` 를 주지 않으면 **오늘이 기간 안일 때 오늘 하루**를
 *  씁니다 — 오늘 값은 장중 내내 바뀌어, 쌓인 값을 그대로 두면 머리의 「오늘
 *  예탁자산」과 그래프의 마지막 점이 서로 다른 값이 됩니다. */
function refreshOf(reply: HistoryReply, from: string, to: string): string[] {
  if (Array.isArray(reply.refresh)) {
    return reply.refresh.filter((day) => typeof day === 'string' && from <= day && day <= to).sort()
  }
  const today = todayText()
  return from <= today && today <= to ? [today] : []
}

/** 그 기간의 쌓아 둔 값을 받아 옵니다. **받아 오기만 합니다** — 빠진 날을 채우는
 *  것은 `fillMissing` 입니다. */
export async function loadDepositHistory(
  market: DepositMarket,
  from: string,
  to: string,
): Promise<void> {
  patch(market, { status: 'loading', period: { from, to } })
  const since = generation()
  let reply: HistoryReply
  try {
    const response = await fetch(`/api/${market}/deposit-history?from=${from}&to=${to}`)
    if (!accepts(response, since)) return
    if (!response.ok) {
      patch(market, { status: 'failed', filling: false })
      return
    }
    environmentOf(response)
    reply = (await response.json()) as HistoryReply
  } catch {
    patch(market, { status: 'failed', filling: false })
    return
  }
  if (since !== generation()) return

  const days: HistoryDay[] = []
  for (const row of reply.days ?? []) {
    const day = String(row.day ?? '')
    const value = row as unknown as DomesticDeposit | OverseasDeposit
    if (day !== '' && drawable(value)) days.push({ day, value })
  }
  /* **걷는 중이면 그 상태는 건드리지 않습니다.** 조회를 시작할 때의 값으로
     되돌리면, 받고 있는 중인데 「받는 중」 표시만 사라집니다. */
  patch(market, {
    status: 'ready',
    period: { from, to },
    days,
    missing: reply.missing ?? [],
    refresh: refreshOf(reply, from, to),
    stored: (reply.store?.status ?? 'ok') === 'ok',
  })
}

/** 오늘 날짜(`YYYYMMDD`, 한국 달력). */
function todayText(): string {
  return kstDate()
}

/** 빠진 날 걷기가 물을 날들. **다시 물을 날은 뺍니다** — 그 날들은
 *  `refreshRecent` 가 따로 물어, 여기서도 물으면 같은 날을 두 번 묻습니다.
 *  「받기 — 빠진 N일치」의 N 도 이 수입니다. */
export function daysToFill(state: HistoryState): string[] {
  return state.missing.filter((day) => !state.refresh.includes(day)).sort()
}

/** 빠진 날을 하루씩 받아 채웁니다. 받은 날은 바로 그림에 붙습니다 — 다 받을
 *  때까지 기다리면 스물두 날 동안 빈 화면을 봅니다. */
export async function fillMissing(market: DepositMarket): Promise<void> {
  const state = historyState(market)
  if (state.filling || walking !== null) return
  const wanted = daysToFill(state)
  if (wanted.length === 0) return

  walk += 1
  const mine = walk
  walking = market
  patch(market, { filling: true, filled: 0, target: wanted.length })
  const since = generation()
  /* **제 걸음은 제가 셉니다.** 저장소의 수를 읽어 올리면, 멈춘 걷기의 늦게 온
     답이 새 걷기의 수를 함께 올려 「9 / 3일」 같은 수가 섭니다. */
  let got = 0

  for (const day of wanted) {
    if (mine !== walk || since !== generation()) break
    const began = Date.now()
    try {
      const response = await fetch(`/api/${market}/deposit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ biz_dt: day }),
      })
      /* **기다리는 동안 멈췄을 수 있습니다.** 그때는 담지도 세지도 않습니다 —
         멈춘 걷기가 새 걷기의 그림에 끼어들면 안 됩니다. */
      if (mine !== walk) break
      if (!accepts(response, since)) break
      if (response.ok) {
        const value = (await response.json()) as DomesticDeposit | OverseasDeposit
        if (mine !== walk) break
        keep(market, day, value)
        /* **받은 것만 셉니다.** 못 받은 날까지 세면 「22 / 22일」로 끝나 놓고
           그림에는 열다섯 날만 서게 됩니다. */
        got += 1
        patch(market, { filled: got, target: wanted.length })
      }
    } catch {
      /* 한 날을 못 받았다고 나머지를 버리지 않습니다. 못 받은 날은 `missing` 에
         그대로 남아 다음에 다시 묻습니다. */
    }
    if (mine !== walk) break
    noteCost(Date.now() - began)
    await new Promise((done) => setTimeout(done, FILL_GAP))
  }

  if (mine === walk) {
    walking = null
    patch(market, { filling: false })
  }
}

/** 걷기를 멈춥니다. 받아 둔 날은 그대로 남습니다. */
export function stopFilling(): void {
  walk += 1
  const market = walking
  walking = null
  if (market) patch(market, { filling: false })
}

/** 다시 묻기의 번호. 번호가 달라지면 앞 다시 묻기는 스스로 멈춥니다. */
let recheck = 0

/** 최근 두 영업일을 **받아 두었어도 다시 물어** 덮어씁니다.
 *
 *  **빠진 날 걷기와 따로 돕니다.** 기간이 길어 걷기를 눌러야 받는 때에도 이 두
 *  날은 저절로 고쳐져야 하고, 걷기를 멈춰도 멈추지 않습니다. 두 날뿐이라 진행
 *  표시는 띄우지 않습니다. 기간이나 시장이 바뀌면 `stopRefresh` 로 멈춥니다. */
export async function refreshRecent(market: DepositMarket): Promise<void> {
  recheck += 1
  const mine = recheck
  const since = generation()
  const wanted = [...historyState(market).refresh]
  for (const day of wanted) {
    if (mine !== recheck || since !== generation()) return
    const began = Date.now()
    try {
      const response = await fetch(`/api/${market}/deposit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ biz_dt: day }),
      })
      if (mine !== recheck) return
      if (!accepts(response, since)) return
      if (response.ok) {
        const value = (await response.json()) as DomesticDeposit | OverseasDeposit
        if (mine !== recheck) return
        keep(market, day, value)
      }
    } catch {
      /* 못 받은 날은 쌓인 값을 그대로 둡니다. 다음에 탭을 열 때 다시 묻습니다. */
    }
    if (mine !== recheck) return
    noteCost(Date.now() - began)
    await new Promise((done) => setTimeout(done, FILL_GAP))
  }
}

/** 다시 묻기를 멈춥니다. 이미 고친 날은 그대로 남습니다. */
export function stopRefresh(): void {
  recheck += 1
}

/** 받은 하루를 그림에 붙입니다. **값이 하나도 없는 날은 점을 안 찍고** 빠진 날
 *  목록에서만 뺍니다 — 서버도 그런 날을 「받았지만 값 없음」으로 쌓아 두어 다시
 *  묻지 않습니다. */
function keep(market: DepositMarket, day: string, value: DomesticDeposit | OverseasDeposit): void {
  const state = historyState(market)
  /* **지금 보는 기간 밖이면 안 붙입니다.** 기간을 바꾸는 순간에도 앞 기간의
     답이 오는 중일 수 있는데, 그 날을 그대로 붙이면 고른 적 없는 날이 그림에
     섭니다. */
  const period = state.period
  if (period && (day < period.from || day > period.to)) return
  const missing = state.missing.filter((one) => one !== day)
  const days = state.days.filter((one) => one.day !== day)
  if (drawable(value)) days.push({ day, value })
  days.sort((a, b) => (a.day < b.day ? -1 : 1))
  patch(market, { days, missing })
}

/** 탭이 서면 그 기간을 받아 오고, 빠진 날이 있으면 **바로 채우기 시작합니다.**
 *  누르지 않아도 되는 것은 누르게 하지 않습니다 — 이 탭에 들어온 까닭이 그
 *  값을 보려는 것입니다. */
export function useTrendPeriod(
  market: DepositMarket,
  from: string,
  to: string,
  auto: boolean,
): HistoryState {
  const state = useDepositHistory(market)
  useEffect(() => {
    /* **기간이나 시장이 바뀌면 앞 걷기를 멈춥니다.** 안 멈추면 그 걷기가 계속
       물으면서 「N / M일」이 새 기간의 수와 어긋나고, 앞 기간의 답이 새 그림에
       다른 날로 섞입니다. 멈춰야 새 걷기도 시작할 수 있습니다. */
    stopFilling()
    stopRefresh()
    /* 이 기간을 떠난 뒤에 도착한 답으로는 아무것도 시작하지 않습니다 — 시작하면
       새 기간이 시작한 다시 묻기를 밀어내고 같은 날을 한 번 더 묻습니다. */
    let current = true
    void loadDepositHistory(market, from, to).then(() => {
      if (!current) return
      /* 최근 두 영업일은 기간 길이와 상관없이 늘 다시 묻습니다. */
      void refreshRecent(market)
      /* **빠진 날은 짧은 기간만 저절로 받습니다.** 긴 기간은 한 번에 수십·수백
         번을 묻게 되어, 세그를 누른 것만으로 그만큼 나가면 안 됩니다. */
      if (auto) void fillMissing(market)
    })
    return () => {
      current = false
    }
  }, [market, from, to, auto])
  return state
}
