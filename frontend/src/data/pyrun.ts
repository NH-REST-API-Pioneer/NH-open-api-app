import { useCallback, useEffect, useRef, useState } from 'react'

/* 팀: 파이썬 전략 실행(`/api/team/pyrun/...`)을 부르는 자리.
 *
 * 서버가 전략 파일을 읽고 실행을 돌립니다. 화면은 **읽고 청할 뿐**입니다 — 시작이
 * 막히면 서버가 준 문장을 그대로 세우고, 상태 낱말(`대기` `진행 중` `확인 필요`
 * `끝` `오류`)도 서버가 준 그대로 씁니다. 화면이 같은 검사를 다시 하면 둘이 갈립니다.
 *
 * **쓰는 요청은 모두 JSON 본문입니다.** 서버는 `application/json` 이 아닌 쓰기 요청을
 * 415 로 거절합니다(다른 사이트가 보낸 요청을 막는 장치). 본문이 없는 요청도 `{}` 를
 * 보냅니다. (본문이 아예 없는 `DELETE` 는 예외 — 서버도 본문을 읽지 않습니다.)
 */

const BASE = '/api/team/pyrun'
/** 화면이 다시 묻는 간격. 서버 쪽 실행은 화면과 상관없이 돕니다. */
export const POLL_MS = 2000
/** API 로그를 처음 열 때 받는 꼬리 줄 수. 하루 실행이면 수만 줄이라 앞쪽은 내려받기로 봅니다. */
export const API_LOG_TAIL = 1000

/** 실행 방식. `replay` 는 받아 둔 1분봉으로 다시 돌린 기록입니다(목록에만 섭니다). */
export type PyMode = 'orders' | 'paper' | 'replay'
/** 상태 낱말 — 서버가 준 그대로. */
export type PyState = '대기' | '진행 중' | '확인 필요' | '끝' | '오류'
export const PY_FINISHED: readonly string[] = ['끝', '오류']

export const PY_MODE_LABEL: Record<PyMode, string> = {
  orders: '모의 계좌',
  paper: '종이',
  replay: '리플레이',
}

/** 실행 방식 낱말. 모르는 값은 받은 그대로입니다. */
export function modeLabel(mode: string | null | undefined): string {
  return mode && mode in PY_MODE_LABEL ? PY_MODE_LABEL[mode as PyMode] : (mode ?? '—')
}

/** `orders` 시작 확인창의 문장. 바꾸지 않습니다. */
export const ORDERS_CONFIRM_TEXT =
  '모의 계좌로 실제 주문이 나갑니다. 실행 중엔 이 종목을 다른 곳(일반주문·조건식 전략)에서 주문하지 마세요.'

export interface PyStrategyFile {
  file: string
  name: string
  title: string
  params: Record<string, unknown> | null
  /** 못 쓰는 파일이면 그 까닭. 이 파일로는 실행을 세울 수 없습니다. */
  error: string | null
}

export interface PyStrategies {
  folder: string
  strategies: PyStrategyFile[]
}

/** 실행 요약(`summary.json` 의 `summary`). */
export interface PySummary {
  trades?: number
  wins?: number
  win_rate?: number | null
  net_pnl?: number
  by_reason?: Record<string, number>
  fee_total?: number | null
  net_pnl_after_fee?: number | null
  [key: string]: unknown
}

/** 기록 한 줄(`journal.jsonl`). `kind`: `signal` `order` `fill` `trade` `event` `account`. */
export interface PyJournalRow {
  kind: string
  at: string
  clock?: string
  text?: string
  error?: string | null
  [key: string]: unknown
}

/** 실행 하나. 이 앱에서 세운 실행이면 `status()` 칸이 다 있고, 지난 실행은 `run.json` 칸에
 *  `summary` 가 붙습니다(보유·손절 같은 지금 상태 칸이 없습니다). */
export interface PyRunStatus {
  id: string
  file: string
  name: string
  title: string
  mode: string
  sym: string | null
  state: string
  started_at: string | null
  ended_at: string | null
  ended_reason: string | null
  bar_min?: number
  next_decision_at?: string | null
  /** 실행기가 아는 보유: 0 · +1(매수) · −1(매도). */
  position?: number | null
  entry?: number | null
  stop?: number | null
  stop_ticks?: number | null
  target?: number | null
  time_exit_at?: string | null
  today_pnl?: number | null
  stops?: number | null
  max_stops?: number | null
  /** 멈춘 까닭. 서 있으면 주문을 내지 않습니다(확인 필요). */
  halted?: string | null
  /** 끝날 때 결과를 모르는 주문이 남았으면 그 내용. */
  unresolved_order?: unknown
  last_signal?: PyJournalRow | null
  /** 그 실행이 쓴 Params. 지난 실행은 요약 파일의 `strategy.params` 이고, 옛 기록이면 null 입니다. */
  params?: Record<string, unknown> | null
  summary?: PySummary | null
  sha256?: string
}

/** 이 앱에서 지금 세운 실행인지 — `status()` 에만 판정 봉 칸이 있습니다. 지난 실행 폴더는
 *  중지·청산할 수 없습니다(서버가 409). */
export function isLiveRun(run: PyRunStatus): boolean {
  return typeof run.bar_min === 'number'
}

/** 차트 봉 하나 = 판정 봉 하나(신호 줄). 지표 칸은 이름 그대로 붙어 옵니다. */
export interface PyBar {
  date: string | null
  /** 판정 봉 시작(HHMMSS). */
  start: string | null
  /** 그 봉의 마지막 1분봉 시작(HHMMSS). */
  end: string | null
  /** 이 기능 전에 남긴 기록에는 없습니다(null). */
  open: number | null
  high: number | null
  low: number | null
  close: number | null
  side?: string | null
  reason?: string | null
  stop_ticks?: number | null
  [key: string]: unknown
}

export interface PyMark {
  /** `entry`·`exit` 는 체결 줄, `trade` 는 거래 줄(손익 라벨용). */
  kind: 'entry' | 'exit' | 'trade'
  date: string
  time: string | null
  side: string | null
  price: number | null
  reason?: string | null
  pnl?: number | null
  ticks?: number | null
  entry?: number | null
  entry_time?: string | null
}

export interface PyBars {
  bars: PyBar[]
  marks: PyMark[]
}

interface Tail<T> {
  rows: T[]
  next: number
}

/** 이 앱 화면이 읽는 결과. 실패면 서버가 준 문장(없으면 짧은 까닭)입니다. */
export type PyResult<T> = { ok: true; data: T } | { ok: false; status: number; why: string }

const JSON_HEADERS = { 'content-type': 'application/json' }

/** 실패 응답의 문장 — 서버의 `detail` 이 문자열이면 그것, 아니면 상태 번호. */
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

/** 쓰는 요청 — 본문이 없어도 JSON `{}` 입니다. */
function post<T>(path: string, body: unknown = {}): Promise<PyResult<T>> {
  return call<T>(path, { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(body) })
}

const enc = encodeURIComponent

export function loadStrategies(signal?: AbortSignal): Promise<PyResult<PyStrategies>> {
  return call<PyStrategies>('/strategies', undefined, signal)
}

export function reloadStrategies(): Promise<PyResult<PyStrategies>> {
  return post<PyStrategies>('/strategies/reload')
}

/** 전략 파일 올리기. 파일 내용(글)을 JSON 에 담아 보냅니다. 같은 이름이 있고 `overwrite` 가 아니면
 *  서버가 409(`같은 이름의 파일이 있습니다`)로 답합니다 — 화면은 그때 덮어쓸지 묻고 `overwrite: true` 로 다시 보냅니다.
 *  성공(201)이면 갱신된 파일 목록이 옵니다. 이름·크기 오류(400)·다른 사이트(403)는 서버 문장이 `why` 에 그대로 옵니다. */
export function uploadStrategy(file: string, content: string, overwrite: boolean): Promise<PyResult<PyStrategies>> {
  return post<PyStrategies>('/strategies', { file, content, overwrite })
}

/** 전략 파일 지우기. 성공이면 갱신된 파일 목록이 옵니다(없는 파일은 404). 돌고 있는 실행은 처음 불러온 코드로 계속 갑니다. */
export function deleteStrategy(file: string): Promise<PyResult<PyStrategies>> {
  return call<PyStrategies>(`/strategies/${enc(file)}`, { method: 'DELETE' })
}

export async function loadRuns(signal?: AbortSignal): Promise<PyResult<PyRunStatus[]>> {
  const got = await call<{ runs: PyRunStatus[] }>('/runs', undefined, signal)
  return got.ok ? { ok: true, data: got.data.runs } : got
}

/** 실행을 세웁니다. 거부(409)·다른 사이트(403)는 서버 문장이 `why` 에 그대로 옵니다.
 *  `sym` 이 비면 서버가 최근월물을 고릅니다. */
export function startRun(file: string, mode: 'orders' | 'paper', sym?: string | null): Promise<PyResult<PyRunStatus>> {
  const code = sym?.trim()
  return post<PyRunStatus>('/runs', { file, mode, sym: code ? code : null })
}

export function loadRun(id: string, signal?: AbortSignal): Promise<PyResult<PyRunStatus>> {
  return call<PyRunStatus>(`/runs/${enc(id)}`, undefined, signal)
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

export function loadBars(id: string, signal?: AbortSignal): Promise<PyResult<PyBars>> {
  return call<PyBars>(`/runs/${enc(id)}/bars`, undefined, signal)
}

/** 중지 = 보유가 있으면 정리하고 끝냅니다. */
export function stopRun(id: string): Promise<PyResult<void>> {
  return post<void>(`/runs/${enc(id)}/stop`)
}

/** 청산 = 보유만 닫고 실행은 계속합니다. */
export function flattenRun(id: string): Promise<PyResult<void>> {
  return post<void>(`/runs/${enc(id)}/flatten`)
}

export const downloadUrl = (id: string) => `/api/team/pyrun/runs/${id}/download`

/* ── 화면이 쓰는 훅 ─────────────────────────────────────── */

/** `POLL_MS` 마다 `tick` 을 부릅니다. 앞 요청이 끝나기 전에는 다음을 보내지 않고, 화면을
 *  떠나면(언마운트) 멈춥니다. `tick` 이 바뀌면(=보는 대상이 바뀌면) 바로 한 번 부릅니다. */
function usePolling(tick: (signal: AbortSignal) => Promise<void>) {
  useEffect(() => {
    const control = new AbortController()
    let timer = 0
    let stopped = false
    const loop = async () => {
      try {
        await tick(control.signal)
      } finally {
        if (!stopped) timer = window.setTimeout(() => void loop(), POLL_MS)
      }
    }
    void loop()
    return () => {
      stopped = true
      control.abort()
      window.clearTimeout(timer)
    }
  }, [tick])
}

/** 실행 목록(2초마다). 못 받으면 앞 목록을 두고 까닭을 답니다. */
export function usePyRuns() {
  const [runs, setRuns] = useState<PyRunStatus[] | null>(null)
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

/** 전략 파일 목록. 처음 한 번과 「폴더 다시 읽기」 때 받고, 올리기·지우기 응답으로도 바뀝니다. */
export function usePyStrategies() {
  const [list, setList] = useState<PyStrategies | null>(null)
  const [why, setWhy] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const control = new AbortController()
    void loadStrategies(control.signal).then((got) => {
      if (control.signal.aborted) return
      if (got.ok) setList(got.data)
      else setWhy(got.why)
    })
    return () => control.abort()
  }, [])
  const reload = useCallback(async () => {
    setBusy(true)
    const got = await reloadStrategies()
    setBusy(false)
    if (got.ok) {
      setList(got.data)
      setWhy(null)
    } else setWhy(got.why)
  }, [])
  /** 올리기·지우기 응답(갱신된 목록)을 그대로 받아 씁니다. */
  const apply = useCallback((next: PyStrategies) => {
    setList(next)
    setWhy(null)
  }, [])
  return { list, why, busy, reload, apply }
}

/** 실행 하나를 보는 데 드는 것 — 상태, 기록(이어 읽기), API 로그(이어 읽기), 차트 봉. */
export interface PyRunView {
  run: PyRunStatus | null
  journal: PyJournalRow[]
  apiLog: Record<string, unknown>[]
  /** API 로그 전체 줄 수(화면에는 꼬리만 있습니다). */
  apiTotal: number
  bars: PyBars | null
  why: string | null
}

const EMPTY: PyRunView = { run: null, journal: [], apiLog: [], apiTotal: 0, bars: null, why: null }

interface Held extends PyRunView {
  /** 이 값이 어느 실행의 것인지. 보는 실행이 바뀐 직후 앞 실행의 값을 보이지 않게 합니다. */
  forId: string | null
}
/** 이 갈래의 줄이 새로 오면 차트 봉을 다시 받습니다(봉·표시가 바뀌는 줄). */
const CHART_KINDS = new Set(['signal', 'fill', 'trade'])

/** 실행 하나를 2초마다 봅니다. 기록·API 로그는 `after=<next>` 로 이어 받고, 차트 봉은 봉·체결·거래
 *  줄이 새로 왔을 때만 다시 받습니다. 화면을 떠나면 멈추고, `id` 가 바뀌면 처음부터 받습니다. */
export function usePyRun(id: string | null): PyRunView {
  const [view, setView] = useState<Held>({ ...EMPTY, forId: null })
  /* 이어 읽기 자리. 보는 실행이 바뀌면 처음으로 돌립니다. */
  const cursor = useRef({ id: null as string | null, journal: 0, api: -1 })

  const tick = useCallback(
    async (signal: AbortSignal) => {
      if (id === null) return
      const at = cursor.current
      if (at.id !== id) {
        cursor.current = { id, journal: 0, api: -1 }
        setView({ ...EMPTY, forId: id })
      }
      const here = cursor.current
      const [run, journal] = await Promise.all([loadRun(id, signal), loadJournal(id, here.journal, signal)])
      if (signal.aborted || cursor.current !== here) return
      /* API 로그는 처음엔 줄 수만 묻고(아주 큰 `after` 는 빈 줄과 줄 수를 줍니다) 꼬리부터 읽습니다. */
      if (here.api < 0) {
        const probe = await loadApiLog(id, Number.MAX_SAFE_INTEGER, signal)
        if (signal.aborted || cursor.current !== here) return
        if (probe.ok) here.api = Math.max(0, probe.data.next - API_LOG_TAIL)
      }
      const api = here.api >= 0 ? await loadApiLog(id, here.api, signal) : null
      if (signal.aborted || cursor.current !== here) return

      const fresh = journal.ok ? journal.data.rows : []
      const firstTime = here.journal === 0
      const needBars = (journal.ok && firstTime) || fresh.some((row) => CHART_KINDS.has(row.kind))
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
