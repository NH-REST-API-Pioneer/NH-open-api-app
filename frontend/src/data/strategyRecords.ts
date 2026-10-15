/* 성과분석이 보는 기록 한 벌의 모양과, 받아 오는 길과, 그 위에서 내는 값들.
 *
 * 기록은 서버의 `GET /api/strategy/records` 가 답합니다. **한 답은 한 기록
 * 유형·한 시장(한 통화)입니다** — 앱 시뮬레이션과 모의 계좌를 한 성적으로
 * 섞으면 어느 쪽 성적인지 말할 수 없고, 원과 달러는 더할 수 없습니다.
 *
 * 전략별 합계와 곡선은 **서버가 센 값을 그대로** 씁니다. 화면이 거래 목록에서
 * 다시 세지 않습니다 — 두 곳에서 세면 같은 이름 아래 다른 수가 섭니다. 화면이
 * 거래 목록에서 내는 것은 서버가 주지 않는 값(승률·방향별·손익비·평균 보유
 * 시간)뿐입니다.
 */
import { useSyncExternalStore } from 'react'

import { addDays, kstDateDash } from '../lib/kst'
import { moneyIn } from '../lib/number'
import type { RunMode } from './strategyRuns'

/** 분석이 고를 수 있는 기록 유형. 서버의 갈래 셋과 같습니다. 조회 한 번은
 *  갈래 하나라 서로 다른 장부의 수를 한 칸에 더하지 않습니다. */
export const ANALYSIS_KINDS = ['모의 계좌 거래', '실전 계좌 거래', '앱 시뮬레이션'] as const
export type AnalysisKind = (typeof ANALYSIS_KINDS)[number]

/** 기록 유형 낱말 → 요청의 `record` 값. 기록 줄의 같은 이름 칸의 값이고, 실행
 *  갈래(`RunMode`)와 같은 값입니다. */
export const RECORD_PARAM: Record<AnalysisKind, RunMode> = {
  '앱 시뮬레이션': 'paper',
  '모의 계좌 거래': 'sim',
  '실전 계좌 거래': 'real',
}

export type RecordMarket = 'domestic' | 'overseas'

/** 기간 고르개. 「30일」은 서버의 기본 기간과 같은 말입니다. */
export const SPANS = ['30일', '90일', '1년', '직접'] as const
export type Span = (typeof SPANS)[number]

/** 거슬러 세는 달력일. 오늘을 포함해 셉니다(서버의 30일과 같은 셈). */
const SPAN_DAYS: Record<Exclude<Span, '직접'>, number> = { '30일': 30, '90일': 90, '1년': 365 }

/** 종료된 거래 하나. 「포지션 0 → 진입 → 다시 0」이 한 건이며, 부분체결
 *  여럿을 여러 건으로 세지 않습니다. */
export interface Trade {
  id: string
  /** 전략 줄을 찾는 열쇠. **버전 id** 입니다(`versionId` 와 같은 값). */
  strategyId: string
  versionId: string
  /** 버전을 묶는 전략. 버전이 지워져 찾지 못하면 `null` 입니다. */
  groupId: string | null
  /** 종료 시각(ISO). */
  at: string | null
  /** 진입 시각(ISO). 평균 보유시간을 여기서 셉니다. */
  openedAt: string | null
  /** 들고 있던 방향입니다. 마지막 주문의 방향이 아닙니다. */
  side: 'buy' | 'sell'
  qty: number
  /** 수수료를 뺀 뒤의 손익. 이익·손실을 가르는 것도 이 값입니다. */
  net: number
  /** 수수료 전 손익과 수수료. 답에 없으면 `null` 입니다(0 과 다름). */
  gross: number | null
  fee: number | null
  code: string
  market: string
  session: string
}

/** 답에 실려 온 그대로의 거래 한 건. **순손익이나 수량이 빠져 올 수 있습니다** —
 *  그 값은 `null` 이고, 0 으로 채우지 않습니다(0 은 「본전」이라는 값입니다).
 *  거래 내역 표는 이것을 그대로 세우고, 셈은 둘 다 아는 거래(`Trade`)만 합니다. */
export interface ListedTrade extends Omit<Trade, 'qty' | 'net'> {
  qty: number | null
  net: number | null
}

export interface StrategyPerf {
  /** 버전 id. */
  id: string
  /** 버전이 지워졌으면 서버가 「알 수 없음」을 적어 보냅니다. */
  name: string
  version: string
  groupId: string | null
  /** 체결가 기준 총실현손익. 여기에 이미 반영된 슬리피지를 다시 빼지 않습니다. */
  gross: number
  /** 수수료. */
  fee: number
  /** 누적 곡선. 가로축은 답의 `dates` 이고, 무엇을 쌓았는지는 답의
   *  `curveBasis` 가 말합니다. */
  curve: number[]
  /** 그 버전의 최대 낙폭. 서버가 셉니다(답의 `drawdownBasis` 기준). 모르거나
   *  싣지 않는 서버면 `null` 입니다. */
  maxDrawdown: number | null
}

/** 묶음(같은 전략의 여러 버전) 하나의 낙폭. 그 묶음 버전들의 거래를 합쳐 셉니다
 *  (답의 `drawdownBasis` 기준). 그 기간에 순손익을 아는 종료 거래가 없으면
 *  `maxDrawdown` 이 `null` 입니다 — 묶음이 목록에 없는 것(묶음 낙폭을 싣지 않는
 *  서버)과는 다른 말입니다. */
export interface GroupDrawdown {
  groupId: string
  maxDrawdown: number | null
}

export interface Dataset {
  /** 기록 유형 글자(「앱 시뮬레이션」·「모의 계좌 거래」). */
  kind: string
  record: string
  market: string
  /** 곡선의 가로축(거래일). 전략마다 같은 날짜를 씁니다. */
  dates: string[]
  strategies: StrategyPerf[]
  /** **셈에 드는 거래** — 순손익과 수량을 둘 다 아는 것뿐입니다. 합계·승률·방향별·
   *  손익비·연속손실·보유시간이 모두 이것으로 셉니다. 종료 시각 차례(오래된 것부터). */
  trades: Trade[]
  /** 답에 실려 온 거래 전부(같은 차례). 거래 내역 표가 이것을 세웁니다. */
  listed: ListedTrade[]
  /** 순손익이나 수량을 몰라 셈에서 뺀 거래 수. */
  uncounted: number
  /** 지금 도는 실행의 평가손익. `openPlKnown` 이 거짓이면 모르는 값이라 0 을
   *  적지 않습니다 — 「값이 0」과 「모른다」는 다른 말입니다. */
  openPl: number
  openPlKnown: boolean
  /** 합계 줄의 이름. 가상 자금은 계좌 합계와 같은 말로 부르지 않습니다. */
  totalLabel: string
  /** 조회 기간 글자. 화면이 그대로 적습니다. */
  period: string
  from: string
  to: string
  currency: string
  /** 그 기간·시장·기록 유형의 기록에 있는 통화들(통화 거름과 상관없이). 해외 기록의
   *  「통화」 고르개가 이것으로 섭니다. 이 칸을 안 싣는 서버면 빈 목록입니다. */
  currencies: string[]
  /** 곡선에 무엇을 쌓았는지. `realized` 는 닫힌 거래의 순손익 누적이고,
   *  `equity` 는 거래일 끝의 실현 − 수수료 + 평가손익(기간 앞 값에서 달라진
   *  만큼)입니다. 한 답은 한 기준입니다. */
  curveBasis: 'realized' | 'equity' | string
  /** 그 조건 전체의 최대 낙폭과 그 셈의 기준. 서버가 셉니다 — `trades-realized` 는
   *  청산 시각 차례로 쌓은 실현 손익 곡선의 고점 대비 최대 감소입니다. 낙폭을 싣지
   *  않는 서버면 `null`·빈 글자입니다. */
  maxDrawdown: number | null
  drawdownBasis: string
  /** 묶음마다의 낙폭. 이 칸을 안 싣는 서버면 빈 목록입니다. */
  groups: GroupDrawdown[]
  /** 체결 품질. 기간 안에 주문 결과 기록이 하나도 없으면 `null` 입니다. */
  quality: QualityReply | null
  /** 거래가 상한을 넘어 최근 것만 남겼는지. 합계·곡선도 남은 거래의 것입니다. */
  truncated: boolean
  /** 남은 거래 중 가장 이른 종료 시각(ISO). */
  earliestAt: string | null
  /** 읽는 사이 기록 파일이 바뀌어 일부가 빠졌을 수 있는지. */
  incomplete: boolean
}

/** 체결 품질. **값은 서버가 적은 글자 그대로 씁니다** — 퍼센트와 분자·분모가
 *  한 글자 안에 함께 오고(「92.0% (23/25건)」), 화면이 `counts` 로 다시 세면
 *  같은 값의 출처가 둘이 됩니다. 셀 것이 없으면(분모 0) 글자가 「—」입니다. */
export interface QualityReply {
  /** 평균 보유시간(「1시간 4분」). 거래가 없으면 「—」. */
  holding: string
  /** 체결 ÷ 접수되어 끝난 주문. */
  fillRate: string
  /** (거절 + 접수 전 막힘) ÷ 낸 시도. */
  rejectRate: string
  /** 기간 안 잔고 기록의 최대 증거금 사용률. */
  marginPeak: string
  counts: {
    filled: number
    ended: number
    rejected: number
    attempts: number
    /** 0~1. 기간 안에 잔고 기록이 없으면 `null` 입니다. */
    marginPeak: number | null
    holdingMs: number | null
  }
}

/* ── 받은 답 읽기 ───────────────────────────────────── */

const text = (value: unknown): string => (typeof value === 'string' ? value : '')
const orNull = (value: unknown): string | null => (typeof value === 'string' && value !== '' ? value : null)
const number = (value: unknown): number => (typeof value === 'number' && Number.isFinite(value) ? value : 0)
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : [])
const numberOrNull = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null

function tradeOf(raw: unknown): ListedTrade | null {
  const row = raw as Record<string, unknown> | null
  if (!row || typeof row !== 'object') return null
  const side = row.side === 'buy' || row.side === 'sell' ? row.side : null
  if (!side) return null
  return {
    id: text(row.id),
    strategyId: text(row.strategyId),
    versionId: text(row.versionId),
    groupId: orNull(row.groupId),
    at: orNull(row.at),
    openedAt: orNull(row.openedAt),
    side,
    qty: numberOrNull(row.qty),
    net: numberOrNull(row.net),
    gross: numberOrNull(row.gross),
    fee: numberOrNull(row.fee),
    code: text(row.code),
    market: text(row.market),
    session: text(row.session),
  }
}


/** 체결 품질 칸. 글자 넷이 다 오지 않으면 `null`(모르는 값)로 읽습니다 — 반쯤
 *  읽은 값을 세우면 빈 칸이 「셀 것이 없다」로 읽힙니다. */
function qualityOf(raw: unknown): QualityReply | null {
  const row = raw as Record<string, unknown> | null
  if (!row || typeof row !== 'object') return null
  const words = [row.holding, row.fillRate, row.rejectRate, row.marginPeak]
  if (!words.every((word) => typeof word === 'string')) return null
  const counts = (row.counts ?? {}) as Record<string, unknown>
  return {
    holding: text(row.holding),
    fillRate: text(row.fillRate),
    rejectRate: text(row.rejectRate),
    marginPeak: text(row.marginPeak),
    counts: {
      filled: number(counts.filled),
      ended: number(counts.ended),
      rejected: number(counts.rejected),
      attempts: number(counts.attempts),
      marginPeak: numberOrNull(counts.marginPeak),
      holdingMs: numberOrNull(counts.holdingMs),
    },
  }
}

function perfOf(raw: unknown): StrategyPerf | null {
  const row = raw as Record<string, unknown> | null
  if (!row || typeof row !== 'object') return null
  return {
    id: text(row.id),
    name: text(row.name),
    version: text(row.version),
    groupId: orNull(row.groupId),
    gross: number(row.gross),
    fee: number(row.fee),
    curve: list(row.curve).map(number),
    maxDrawdown: numberOrNull(row.maxDrawdown),
  }
}

/** 묶음 낙폭 하나. 묶음 id 가 없으면 버립니다 — 어느 묶음의 값인지 모르는 수를
 *  세우지 않습니다. */
function groupOf(raw: unknown): GroupDrawdown | null {
  const row = raw as Record<string, unknown> | null
  if (!row || typeof row !== 'object') return null
  const groupId = orNull(row.groupId)
  if (groupId === null) return null
  return { groupId, maxDrawdown: numberOrNull(row.maxDrawdown) }
}

/** 받은 답을 화면의 모양으로. 알맹이가 아니면 `null` 입니다 — 모양이 다른 답을
 *  빈 기록으로 읽으면 「거래가 없다」는 거짓말이 섭니다. */
export function datasetOf(body: unknown): Dataset | null {
  const row = body as Record<string, unknown> | null
  if (!row || typeof row !== 'object' || !Array.isArray(row.trades) || !Array.isArray(row.strategies)) {
    return null
  }
  const listed = list(row.trades).flatMap((one) => tradeOf(one) ?? [])
  /* 순손익·수량을 둘 다 아는 거래만 셉니다. 모르는 값을 0 으로 더하면 합계와
     승률이 받은 적 없는 값을 말합니다. */
  const trades = listed.filter(
    (trade): trade is Trade => trade.net !== null && trade.qty !== null,
  )
  return {
    kind: text(row.kind),
    record: text(row.record),
    market: text(row.market),
    dates: list(row.dates).map(text),
    strategies: list(row.strategies).flatMap((one) => perfOf(one) ?? []),
    trades,
    listed,
    uncounted: listed.length - trades.length,
    openPl: number(row.openPl),
    openPlKnown: row.openPlKnown === true,
    totalLabel: text(row.totalLabel) || '합계',
    period: text(row.period),
    from: text(row.from),
    to: text(row.to),
    currency: text(row.currency),
    currencies: list(row.currencies)
      .map(text)
      .filter((code) => /^[A-Z]{3}$/.test(code)),
    curveBasis: text(row.curveBasis),
    maxDrawdown: numberOrNull(row.maxDrawdown),
    drawdownBasis: text(row.drawdownBasis),
    groups: list(row.groups).flatMap((one) => groupOf(one) ?? []),
    quality: qualityOf(row.quality),
    truncated: row.truncated === true,
    earliestAt: orNull(row.earliestAt),
    incomplete: row.incomplete === true,
  }
}

/* ── 고른 조건과 받은 답 ─────────────────────────────── */

export interface RecordFilters {
  kind: AnalysisKind
  market: RecordMarket
  span: Span
  /** 「직접」일 때의 양 끝(YYYY-MM-DD). 비우면 그쪽은 서버가 채웁니다. */
  from: string
  to: string
  /** 전략 묶음. 빈 글자는 「전체 전략」입니다. */
  group: string
  /** 그 묶음의 버전들. 요청에 쉼표로 이어 보냅니다. */
  versions: string[]
  /** 종목 코드. 빈 글자는 「전체 종목」입니다. */
  code: string
  /** 해외 기록의 통화. 빈 글자는 「전체」입니다 — 통화가 여럿이면 통화마다 따로 받아
   *  금액을 통화별 줄로 세웁니다(합산하지 않습니다). 국내는 쓰지 않습니다. */
  currency: string
}

export interface RecordsState {
  filters: RecordFilters
  /** 마지막으로 받은 답. 다시 받는 동안에도 그대로 둡니다. */
  data: Dataset | null
  status: 'loading' | 'ready' | 'failed'
  /** 서버가 요청 모양을 물린 문장(422). 앞 답은 그대로 둡니다. */
  refused: string | null
  /** 종목 고르개에 설 코드들 — 종목을 거르기 전 마지막 답에 나온 것입니다.
   *  고른 동안 목록이 하나로 줄면 다른 종목으로 옮겨 갈 수 없습니다. */
  codes: string[]
  /** 해외 「전체」에서 통화가 여럿일 때 **통화마다 받은 답**(답의 통화 차례). 하나뿐이거나
   *  통화를 골랐거나 국내면 `null` 입니다. */
  perCurrency: Dataset[] | null
}

let records: RecordsState = {
  filters: {
    kind: '모의 계좌 거래',
    market: 'domestic',
    span: '30일',
    from: '',
    to: '',
    group: '',
    versions: [],
    code: '',
    currency: '',
  },
  data: null,
  status: 'loading',
  refused: null,
  codes: [],
  perCurrency: null,
}
const watchers = new Set<() => void>()

function announceRecords(next: RecordsState): void {
  records = next
  for (const watcher of watchers) watcher()
}

export function recordsState(): RecordsState {
  return records
}

function subscribeRecords(watcher: () => void): () => void {
  watchers.add(watcher)
  return () => watchers.delete(watcher)
}

/** 화면이 기록을 읽는 자리. 탭을 오가도 고른 조건과 받은 답이 남습니다. */
export function useRecordsState(): RecordsState {
  return useSyncExternalStore(subscribeRecords, recordsState, recordsState)
}

/** 오늘에서 거슬러 센 날짜(YYYY-MM-DD, 한국 달력). */
function daysBack(days: number): string {
  return addDays(kstDateDash(), -days)
}

/** 요청 주소. **30일은 기간을 비워 보냅니다** — 서버의 기본 기간이 곧 30일이고,
 *  화면은 답의 `period` 를 적습니다. 90일·1년은 시작만 보내 끝이 오늘로
 *  채워집니다. */
export function recordsPath(filters: RecordFilters): string {
  const ask = new URLSearchParams({ record: RECORD_PARAM[filters.kind], market: filters.market })
  if (filters.span === '직접') {
    if (filters.from) ask.set('from', filters.from)
    if (filters.to) ask.set('to', filters.to)
  } else if (filters.span !== '30일') {
    ask.set('from', daysBack(SPAN_DAYS[filters.span] - 1))
  }
  if (filters.versions.length > 0) ask.set('versions', filters.versions.join(','))
  if (filters.code) ask.set('code', filters.code)
  if (filters.market === 'overseas' && filters.currency) ask.set('currency', filters.currency)
  return `/api/strategy/records?${ask.toString()}`
}

/** 서버가 조회 조건을 받지 않았을 때(400·422) 세울 글. 서버 글을 이 차례로
 *  찾습니다 — `detail` 이 글이면 그 글, `detail.message`, 몸 맨 위 `message`.
 *  어느 것도 글이 아니면 고정 글입니다. 글이 아닌 값을 그대로 세우면
 *  「[object Object]」 같은 글자가 섭니다. */
function refusedWhy(body: unknown): string {
  const said = body !== null && typeof body === 'object' ? (body as Record<string, unknown>) : {}
  const detail = said.detail
  const nested =
    detail !== null && typeof detail === 'object' ? (detail as Record<string, unknown>).message : undefined
  for (const one of [detail, nested, said.message]) {
    if (typeof one === 'string' && one.trim()) return one
  }
  return '조회 조건을 받지 않았습니다'
}

/* 요청마다 하나씩 올라가는 번호. **늦게 온 앞 답은 버립니다** — 조건을 빠르게
   바꾸면 앞 요청의 답이 뒤에 도착할 수 있고, 그 답을 쓰면 고른 조건과 다른
   기록이 섭니다. */
let generation = 0

/** 지금 조건으로 기록을 다시 받습니다. 받는 동안 앞 답을 그대로 둡니다. */
export async function loadRecords(): Promise<void> {
  const mine = ++generation
  const filters = records.filters
  announceRecords({ ...records, status: 'loading' })
  try {
    const answer = await fetch(recordsPath(filters))
    const body: unknown = await answer.json().catch(() => null)
    if (mine !== generation) return
    if (answer.status === 400 || answer.status === 422) {
      announceRecords({ ...records, status: 'ready', refused: refusedWhy(body) })
      return
    }
    const data = answer.ok ? datasetOf(body) : null
    if (!data) {
      announceRecords({ ...records, data: null, status: 'failed', refused: null, perCurrency: null })
      return
    }
    /* 해외 「전체」에서 통화가 여럿이면 통화마다의 답으로 통화별 줄을 세웁니다 — 통화가
       다른 금액은 더하지 않습니다. 서버가 그 답들을 **같은 답에 실어 주면**(`byCurrency`)
       그것을 쓰고 더 묻지 않습니다. 안 실어 주는 서버거나 하나라도 못 읽으면 통화마다
       한 번씩 더 받습니다. 그래도 하나라도 못 받으면 통화마다의 줄은 세우지 않고 실패로
       둡니다(반만 세우면 빠진 통화가 없는 것으로 읽힙니다). */
    let perCurrency: Dataset[] | null = null
    const carried = (body as { byCurrency?: unknown } | null)?.byCurrency
    if (filters.market === 'overseas' && !filters.currency && data.currencies.length > 1 && carried && typeof carried === 'object') {
      const sets = data.currencies.map((code) => datasetOf((carried as Record<string, unknown>)[code]))
      if (sets.every((one) => one !== null)) perCurrency = sets as Dataset[]
    }
    if (perCurrency === null && filters.market === 'overseas' && !filters.currency && data.currencies.length > 1) {
      const answers = await Promise.all(
        data.currencies.map(async (code) => {
          const one = await fetch(recordsPath({ ...filters, currency: code }))
          return one.ok ? datasetOf(await one.json().catch(() => null)) : null
        }),
      )
      if (mine !== generation) return
      if (answers.some((one) => one === null)) {
        announceRecords({ ...records, data: null, status: 'failed', refused: null, perCurrency: null })
        return
      }
      perCurrency = answers as Dataset[]
    }
    announceRecords({
      ...records,
      data,
      status: 'ready',
      refused: null,
      codes: filters.code ? records.codes : codesOf(data.listed),
      perCurrency,
    })
  } catch {
    if (mine !== generation) return
    announceRecords({ ...records, data: null, status: 'failed', refused: null })
  }
}

/** 사용자가 시장을 직접 골랐는지. 고른 뒤로는 화면이 기본 시장을 다시 정하지
 *  않습니다 — 고른 값을 덮으면 보던 시장이 탭을 오갈 때마다 바뀝니다. 앱을 켜 있는
 *  동안만 기억합니다. */
let marketPicked = false

/** 사용자가 시장 단추를 눌렀을 때. */
export function pickRecordMarket(market: RecordMarket): void {
  marketPicked = true
  setRecordFilters({ market })
}

/** 분석 탭이 열릴 때의 기본 시장. **끝나지 않은 실행이 한 시장에서만 돌면 그 시장**
 *  이고, 두 시장에서 돌거나 없으면 지금 시장 그대로입니다. 사용자가 고른 적이 있으면
 *  손대지 않습니다. 시장이 바뀌면 다시 받고, 아니면 지금 조건으로 받습니다. */
export function openRecords(runMarkets: readonly string[]): void {
  const markets = [...new Set(runMarkets)].filter(
    (one): one is RecordMarket => one === 'domestic' || one === 'overseas',
  )
  if (!marketPicked && markets.length === 1 && markets[0] !== records.filters.market) {
    setRecordFilters({ market: markets[0] })
    return
  }
  void loadRecords()
}

/** 조건을 바꾸고 곧바로 다시 받습니다. */
export function setRecordFilters(patch: Partial<RecordFilters>): void {
  const next = { ...records.filters, ...patch }
  /* 시장이나 기록 유형이 바뀌면 앞 답의 종목 목록은 다른 장부의 것이라 종목을
     「전체」로 돌립니다. 전략 묶음은 시장이 바뀔 때만 돌립니다 — 전략은 한
     시장에 속하고, 기록 유형은 같은 전략을 다른 장부로 볼 뿐입니다. */
  const marketMoved = patch.market !== undefined && patch.market !== records.filters.market
  const ledgerMoved = marketMoved || (patch.kind !== undefined && patch.kind !== records.filters.kind)
  /* 시장이 바뀌면 통화도 「전체」로 돌립니다 — 통화는 해외 기록에만 있습니다. */
  const filters = marketMoved ? { ...next, group: '', versions: [], currency: '' } : next
  announceRecords({
    ...records,
    filters: ledgerMoved ? { ...filters, code: '' } : filters,
    codes: ledgerMoved ? [] : records.codes,
  })
  void loadRecords()
}

function codesOf(trades: readonly { code: string }[]): string[] {
  return [...new Set(trades.map((trade) => trade.code).filter(Boolean))].sort()
}

/* ── 받은 값 위에서 내는 것 ──────────────────────────── */

/** 답의 통화로 적는 금액. 전략 화면의 다른 금액과 같은 규칙입니다(`moneyIn` —
 *  원은 정수에 「원」, 그 밖은 그 통화의 자릿수에 코드, 모르면 「—」). */
export function amountText(value: number, currency: string): string {
  return moneyIn(value, currency)
}

export function netOf(perf: StrategyPerf): number {
  return perf.gross - perf.fee
}

export function tradesOf(data: Dataset, id: string): Trade[] {
  return data.trades.filter((trade) => trade.strategyId === id)
}

/** 승률 = 이익으로 끝난 거래 ÷ 전체 종료 거래.
 *
 * **종료 거래가 없으면 승률이 없습니다.** 0% 로 적으면 「모두 졌다」로
 * 읽히는데 그것은 진 거래가 있을 때 하는 말입니다 — 분모가 0 이면 `null` 을
 * 돌려주고 화면이 「—」와 「거래 없음」으로 답합니다. */
export function winRate(trades: Trade[]): number | null {
  if (trades.length === 0) return null
  const won = trades.filter((trade) => trade.net > 0).length
  return Math.round((won / trades.length) * 1000) / 10
}

export function wins(trades: Trade[]): number {
  return trades.filter((trade) => trade.net > 0).length
}

/** 합계 곡선. 고른 범위의 전략을 같은 시점끼리 더합니다. */
export function totalCurve(perfs: StrategyPerf[], points: number): number[] {
  return Array.from({ length: points }, (_, i) =>
    perfs.reduce((sum, perf) => sum + (perf.curve[i] ?? 0), 0),
  )
}

/** 방향별 집계. 거래 목록에서 그때그때 냅니다. */
export function bySide(trades: Trade[], side: 'buy' | 'sell') {
  const picked = trades.filter((trade) => trade.side === side)
  return {
    closed: picked.length,
    wins: wins(picked),
    net: picked.reduce((sum, trade) => sum + trade.net, 0),
  }
}

/** 거래일별 손익. 누적 곡선의 차이라 곡선과 같은 기준의 값입니다. */
export function segments(dates: string[], curve: number[]) {
  return curve.map((value, i) => ({
    label: dates[i] ?? '',
    delta: i === 0 ? value : value - (curve[i - 1] ?? 0),
  }))
}

/** 평균 보유시간(분). 진입·종료 시각이 둘 다 있는 거래만 셉니다. 셀 거래가
 *  없으면 `null` 입니다. */
export function averageHolding(trades: Trade[]): number | null {
  let sum = 0
  let counted = 0
  for (const trade of trades) {
    if (!trade.at || !trade.openedAt) continue
    const span = Date.parse(trade.at) - Date.parse(trade.openedAt)
    if (!Number.isFinite(span) || span < 0) continue
    sum += span
    counted += 1
  }
  return counted === 0 ? null : sum / counted / 60_000
}

/** 보유시간 글자. 「38분」·「1시간 12분」·「2일 3시간」. */
export function holdingText(minutes: number): string {
  if (minutes < 1) return '1분 미만'
  const whole = Math.round(minutes)
  const day = Math.floor(whole / 1440)
  const hour = Math.floor((whole % 1440) / 60)
  const minute = whole % 60
  if (day > 0) return hour > 0 ? `${day}일 ${hour}시간` : `${day}일`
  if (hour > 0) return minute > 0 ? `${hour}시간 ${minute}분` : `${hour}시간`
  return `${minute}분`
}

/** ISO 시각을 「YYYY-MM-DD HH:MM」로. 읽지 못하면 받은 글자 그대로입니다. */
export function minuteText(iso: string | null): string {
  if (!iso) return '—'
  const found = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(iso)
  return found ? `${found[1]} ${found[2]}` : iso
}
