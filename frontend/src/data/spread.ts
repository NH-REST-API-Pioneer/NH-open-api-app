import { useCallback, useEffect, useRef, useState } from 'react'
import { API_LOG_TAIL, usePolling, type PyJournalRow, type PyResult } from './pyrun'

/* 팀: 스프레드 실행(`/api/team/spread/...`)을 부르는 자리. 파이썬 전략(`data/pyrun.ts`)과 같은 규칙입니다.
 *
 * 화면은 **읽고 청할 뿐**입니다 — 시작·이어받기가 막히면 서버가 준 문장(409 `detail`)을 그대로 세우고,
 * 상태 낱말(`준비` `진행 중` `장 쉼` `정리 대기` `확인 필요` `끝` `오류`)도 서버가 준 그대로 씁니다.
 * 쓰는 요청은 모두 JSON 본문입니다(서버가 JSON 이 아닌 쓰기 요청을 415 로 거절합니다).
 */

const BASE = '/api/team/spread'

/** 실행 방식. 스프레드는 종이와 모의 계좌뿐입니다(재생은 터미널에서). */
export type SpreadMode = 'orders' | 'paper'
export const SPREAD_FINISHED: readonly string[] = ['끝', '오류']

/** 모의 계좌로 시작할 때 확인 얼굴에 적는 문장. 바꾸지 않습니다. */
export const SPREAD_ORDERS_CONFIRM_TEXT =
  '모의 계좌로 실제 주문이 나갑니다. 시작하면 중지할 때까지 매일 이 확인 없이 주문이 나갑니다. ' +
  '실행 중엔 이 종목들을 다른 곳(일반주문·조건식 전략)에서 주문하지 마세요.'

/** 기본 분당 주문 상한·다리별 최대 보유 — 서버 기본과 같은 값입니다(실행기가 `MAX_QTY` 를 적었으면 그것). */
export const DEFAULT_ORDERS_PER_MIN = 10
export const DEFAULT_MAX_QTY = 5

export interface SpreadRunnerFile {
  file: string
  name: string | null
  title: string | null
  /** 다리 이름 → 다리 표기(`LEGS`). 못 쓰는 파일은 비어 있을 수 있습니다. */
  legs: Record<string, string>
  max_qty: number | null
  /** 못 쓰는 파일이면 그 까닭. */
  error: string | null
  sha256: string | null
}

export interface SpreadRunners {
  folder: string
  runners: SpreadRunnerFile[]
  /** 옆 모듈(실행기가 불러 쓰는 공용 코드)의 파일 이름. */
  modules: string[]
}

/** 손익 한 칸(통화별). `estimated` = 체결가를 모르는 체결이 들어간 값, `fee_unknown` = 수수료를 모르는 체결 수. */
export interface SpreadPnl {
  pnl: number
  fee: number
  net: number
  fills: number
  fee_unknown?: number
  estimated?: boolean
}
/** 통화 → 손익. */
export type SpreadPnlByCur = Record<string, SpreadPnl>

export interface SpreadLegNow {
  name: string
  sym: string
  market?: string
  currency: string
  position?: number | null
  avg_price?: number | null
  last?: number | null
}

export interface SpreadSummary {
  days?: Record<string, SpreadPnlByCur>
  total?: SpreadPnlByCur
  legs?: SpreadLegNow[]
  ended_reason?: string | null
  halted?: string | null
  [key: string]: unknown
}

/** 실행 하나 — 도는 실행은 `status()`, 끝난 실행은 `run.json` + `summary`. 칸이 없을 수 있습니다. */
export interface SpreadRunStatus {
  id: string
  file: string
  name: string
  title: string
  mode: string
  state: string
  started_at: string | null
  ended_at: string | null
  ended_reason: string | null
  halted?: string | null
  legs?: SpreadLegNow[]
  pnl_today?: SpreadPnlByCur
  pnl_total?: SpreadPnlByCur
  waiting_for?: string[]
  inherited_from?: string | null
  handed_to?: string | null
  holding_left?: Record<string, number> | null
  inheritable?: boolean
  logs_tail?: unknown[]
  unresolved_order?: unknown
  summary?: SpreadSummary | null
}

export function isFinishedRun(run: { state: string }): boolean {
  return SPREAD_FINISHED.includes(run.state)
}

/** 「이어받기」를 보일 실행인가 — 끝났고, 모의 계좌였고, 보유가 남았고, 아직 아무도 이어받지 않았다. */
export function canInherit(run: SpreadRunStatus): boolean {
  return isFinishedRun(run) && run.mode === 'orders' && run.inheritable === true && !run.handed_to
}

/** 한 다리의 지금 값. 끝난 실행(`run.json`)에는 보유·평균가가 없어 요약(`summary.legs`)에서 채웁니다. */
export function legsOf(run: SpreadRunStatus): SpreadLegNow[] {
  const legs = run.legs ?? []
  const fromSummary = run.summary?.legs ?? []
  return legs.map((leg) => {
    if (leg.position !== undefined) return leg
    const found = fromSummary.find((one) => one.name === leg.name)
    return found ? { ...leg, position: found.position, avg_price: found.avg_price, last: found.last } : leg
  })
}

/** 오늘 손익·누적 손익. 도는 실행은 상태의 칸, 끝난 실행은 요약의 마지막 날·`total`. */
export function pnlOf(run: SpreadRunStatus): { today: SpreadPnlByCur | null; total: SpreadPnlByCur | null; todayLabel: string } {
  if (run.pnl_total !== undefined || run.pnl_today !== undefined) {
    return { today: run.pnl_today ?? null, total: run.pnl_total ?? null, todayLabel: '오늘' }
  }
  const days = run.summary?.days
  const last = days ? Object.keys(days).sort().pop() : undefined
  return {
    today: last && days ? days[last] : null,
    total: run.summary?.total ?? null,
    todayLabel: last ? `마지막 거래일 ${last.slice(4, 6)}/${last.slice(6, 8)}` : '오늘',
  }
}

/** 통화별 손익 칸을 글로 — 「+1,200원」·「+US$3.50」, 값이 추정이면 뒤에 「(추정)」. 비었으면 null. */
export function pnlLine(
  by: SpreadPnlByCur | null | undefined,
  text: (value: number, currency: string) => string,
): { currency: string; text: string; value: number; estimated: boolean; feeUnknown: number }[] {
  return Object.entries(by ?? {}).map(([currency, one]) => ({
    currency,
    text: text(one.net, currency),
    value: one.net,
    estimated: one.estimated === true,
    feeUnknown: one.fee_unknown ?? 0,
  }))
}

/** 체결 줄의 가격이 체결가가 아니라 기준가인가(체결가를 읽지 못함). */
export function priceIsGuess(row: PyJournalRow): boolean {
  return row.price_known === false
}

/** `/bars` — 차트에 쓰는 점들. 시각 `at` 은 `YYYY-MM-DDTHH:MM:SS`(한국 시간, 시간대 없음). */
export interface SpreadBars {
  legs: Record<string, { at: string; close: number }[]>
  logs: Record<string, { at: string; value: number }[]>
  fills: { at: string | null; clock: string | null; leg: string | null; sym: string | null; qty: number | null; price: number | null; fee: number | null }[]
}

export interface InheritLeg {
  sym: string
  qty: number
  avg_price: number | null
}
/** 이어받기 미리 보기 — 지금 계좌 잔고. 확인 얼굴이 이 `qty` 를 그대로 `expect` 로 보냅니다. */
export interface InheritPreview {
  id: string
  file: string | null
  ended_reason: string
  warning: string | null
  syms: Record<string, string>
  legs: Record<string, InheritLeg>
}

interface Tail<T> {
  rows: T[]
  next: number
}

const JSON_HEADERS = { 'content-type': 'application/json' }

async function whyOf(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === 'string' && body.detail) return body.detail
  } catch {
    /* 본문이 JSON 이 아니면 아래 */
  }
  return `요청이 실패했습니다 (${response.status})`
}

async function call<T>(path: string, init?: RequestInit, signal?: AbortSignal): Promise<PyResult<T>> {
  try {
    const response = await fetch(`${BASE}${path}`, { ...init, signal })
    if (!response.ok) return { ok: false, status: response.status, why: await whyOf(response) }
    if (response.status === 204) return { ok: true, data: undefined as T }
    return { ok: true, data: (await response.json()) as T }
  } catch {
    return { ok: false, status: 0, why: signal?.aborted ? '요청을 그만두었습니다' : '서버에 닿지 않습니다' }
  }
}

function post<T>(path: string, body: unknown = {}): Promise<PyResult<T>> {
  return call<T>(path, { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(body) })
}

const enc = encodeURIComponent

export function loadRunners(signal?: AbortSignal): Promise<PyResult<SpreadRunners>> {
  return call<SpreadRunners>('/runners', undefined, signal)
}

export function reloadRunners(): Promise<PyResult<SpreadRunners>> {
  return post<SpreadRunners>('/runners/reload')
}

/** 실행기 파일 올리기. 같은 이름이 있고 `overwrite` 가 아니면 409 — 화면이 묻고 `overwrite: true` 로 다시 보냅니다. */
export function uploadRunner(file: string, content: string, overwrite: boolean): Promise<PyResult<SpreadRunners>> {
  return post<SpreadRunners>('/runners', { file, content, overwrite })
}

export function deleteRunner(file: string): Promise<PyResult<SpreadRunners>> {
  return call<SpreadRunners>(`/runners/${enc(file)}`, { method: 'DELETE' })
}

/** 작성 규칙(마크다운 글 그대로). 문서가 아직 없으면 서버가 404 문장을 줍니다. */
export async function loadConvention(signal?: AbortSignal): Promise<PyResult<string>> {
  const got = await call<{ markdown: string }>('/convention', undefined, signal)
  return got.ok ? { ok: true, data: got.data.markdown } : got
}

export async function loadRuns(signal?: AbortSignal): Promise<PyResult<SpreadRunStatus[]>> {
  const got = await call<{ runs: SpreadRunStatus[] }>('/runs', undefined, signal)
  return got.ok ? { ok: true, data: got.data.runs } : got
}

export interface StartOptions {
  file: string
  mode: SpreadMode
  /** 다리 이름 → 종목코드. 비운 다리는 빼서 보냅니다(서버가 `LEGS` 대로 찾음). 모두 비면 칸을 아예 뺍니다. */
  syms: Record<string, string>
  maxQty: number
  ordersPerMin: number
}

/** 실행을 세웁니다. 거부(409)는 서버 문장이 `why` 에 그대로 옵니다. 서버는 모르는 칸을 422 로 거절하므로 본문은 이 칸들뿐입니다. */
export function startRun(options: StartOptions): Promise<PyResult<SpreadRunStatus>> {
  const syms: Record<string, string> = {}
  for (const [leg, code] of Object.entries(options.syms)) {
    const trimmed = code.trim()
    if (trimmed) syms[leg] = trimmed
  }
  const body: Record<string, unknown> = {
    file: options.file,
    mode: options.mode,
    max_qty: options.maxQty,
    orders_per_min: options.ordersPerMin,
  }
  if (Object.keys(syms).length > 0) body.syms = syms
  return post<SpreadRunStatus>('/runs', body)
}

export function loadRun(id: string, signal?: AbortSignal): Promise<PyResult<SpreadRunStatus>> {
  return call<SpreadRunStatus>(`/runs/${enc(id)}`, undefined, signal)
}

export function loadJournal(id: string, after: number, signal?: AbortSignal): Promise<PyResult<Tail<PyJournalRow>>> {
  return call<Tail<PyJournalRow>>(`/runs/${enc(id)}/journal?after=${after}`, undefined, signal)
}

export function loadApiLog(
  id: string,
  after: number,
  signal?: AbortSignal,
): Promise<PyResult<Tail<Record<string, unknown>>>> {
  return call<Tail<Record<string, unknown>>>(`/runs/${enc(id)}/api-log?after=${after}`, undefined, signal)
}

export function loadBars(id: string, signal?: AbortSignal): Promise<PyResult<SpreadBars>> {
  return call<SpreadBars>(`/runs/${enc(id)}/bars`, undefined, signal)
}

/** 중지 = 정리하고 끝냅니다. 요청이 완료는 아닙니다 — 「정리 대기」일 수 있습니다. */
export function stopRun(id: string): Promise<PyResult<void>> {
  return post<void>(`/runs/${enc(id)}/stop`)
}

export const downloadUrl = (id: string) => `${BASE}/runs/${id}/download`

export function previewInherit(id: string): Promise<PyResult<InheritPreview>> {
  return call<InheritPreview>(`/runs/${enc(id)}/inherit`)
}

/** 이어받기 시작. `expect` = 확인 얼굴에 보인 다리별 수량 — 시작 순간 잔고가 다르면 서버가 409 로 거절합니다. */
export function startInherit(id: string, file: string, expect: Record<string, number>): Promise<PyResult<SpreadRunStatus>> {
  return post<SpreadRunStatus>(`/runs/${enc(id)}/inherit`, { file, expect })
}

/* ── 화면이 쓰는 훅 ─────────────────────────────────────── */

/** 실행 목록(2초마다). 못 받으면 앞 목록을 두고 까닭을 답니다. */
export function useSpreadRuns() {
  const [runs, setRuns] = useState<SpreadRunStatus[] | null>(null)
  const [why, setWhy] = useState<string | null>(null)
  const tick = useCallback(async (signal: AbortSignal) => {
    const got = await loadRuns(signal)
    if (signal.aborted) return
    if (got.ok) {
      setRuns(got.data)
      setWhy(null)
    } else setWhy(got.why)
  }, [])
  usePolling(tick)
  return { runs, why }
}

/** 실행기 파일 목록. 처음 한 번과 「폴더 다시 읽기」 때 받고, 올리기·지우기 응답으로도 바뀝니다. */
export function useSpreadRunners() {
  const [list, setList] = useState<SpreadRunners | null>(null)
  const [why, setWhy] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const control = new AbortController()
    void loadRunners(control.signal).then((got) => {
      if (control.signal.aborted) return
      if (got.ok) setList(got.data)
      else setWhy(got.why)
    })
    return () => control.abort()
  }, [])
  const reload = useCallback(async () => {
    setBusy(true)
    const got = await reloadRunners()
    setBusy(false)
    if (got.ok) {
      setList(got.data)
      setWhy(null)
    } else setWhy(got.why)
  }, [])
  const apply = useCallback((next: SpreadRunners) => {
    setList(next)
    setWhy(null)
  }, [])
  return { list, why, busy, reload, apply }
}

export interface SpreadRunView {
  run: SpreadRunStatus | null
  journal: PyJournalRow[]
  apiLog: Record<string, unknown>[]
  apiTotal: number
  bars: SpreadBars | null
  why: string | null
}

const EMPTY: SpreadRunView = { run: null, journal: [], apiLog: [], apiTotal: 0, bars: null, why: null }

interface Held extends SpreadRunView {
  forId: string | null
}
/** 이 갈래의 줄이 새로 오면 차트 점을 다시 받습니다. */
const CHART_KINDS = new Set(['minute', 'fill', 'log'])

/** 실행 하나를 2초마다 봅니다(파이썬 전략의 `usePyRun` 과 같은 방식). 화면을 떠나면 멈추고, `id` 가 바뀌면 처음부터 받습니다. */
export function useSpreadRun(id: string | null): SpreadRunView {
  const [view, setView] = useState<Held>({ ...EMPTY, forId: null })
  const cursor = useRef({ id: null as string | null, journal: 0, api: -1 })

  const tick = useCallback(
    async (signal: AbortSignal) => {
      if (id === null) return
      if (cursor.current.id !== id) {
        cursor.current = { id, journal: 0, api: -1 }
        setView({ ...EMPTY, forId: id })
      }
      const here = cursor.current
      const [run, journal] = await Promise.all([loadRun(id, signal), loadJournal(id, here.journal, signal)])
      if (signal.aborted || cursor.current !== here) return
      if (here.api < 0) {
        const probe = await loadApiLog(id, Number.MAX_SAFE_INTEGER, signal)
        if (signal.aborted || cursor.current !== here) return
        if (probe.ok) here.api = Math.max(0, probe.data.next - API_LOG_TAIL)
      }
      const api = here.api >= 0 ? await loadApiLog(id, here.api, signal) : null
      if (signal.aborted || cursor.current !== here) return

      const fresh = journal.ok ? journal.data.rows : []
      const needBars = (journal.ok && here.journal === 0) || fresh.some((row) => CHART_KINDS.has(row.kind))
      if (journal.ok) here.journal = journal.data.next
      const apiFresh = api?.ok ? api.data.rows : []
      const apiTotal = api?.ok ? api.data.next : null
      if (api?.ok) here.api = api.data.next

      const bars = needBars ? await loadBars(id, signal) : null
      if (signal.aborted || cursor.current !== here) return

      const failed = !run.ok ? run.why : !journal.ok ? journal.why : bars && !bars.ok ? bars.why : null
      setView((had) => ({
        forId: id,
        run: run.ok ? run.data : had.run,
        journal: fresh.length > 0 ? [...had.journal, ...fresh] : had.journal,
        apiLog: apiFresh.length > 0 ? [...had.apiLog, ...apiFresh].slice(-API_LOG_TAIL * 2) : had.apiLog,
        apiTotal: apiTotal ?? had.apiTotal,
        bars: bars?.ok ? bars.data : had.bars,
        why: failed,
      }))
    },
    [id],
  )
  usePolling(tick)
  return id !== null && view.forId === id ? view : EMPTY
}
