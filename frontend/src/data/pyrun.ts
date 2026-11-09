import { useCallback, useEffect, useRef, useState } from 'react'
import { MINUS, moneyIn } from '../lib/number'
import { resolve } from './instruments'

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

/* ── 종목 고르기 ──────────────────────────────────────── */

/** 이 실행기가 돌리는 종목코드의 앞부분 — 국내 미국달러선물과 해외 SGX 미니 원달러(MKU).
 *  서버(`markets.market_of`)와 같은 값입니다 — 서버가 다른 종목을 거절하므로, 화면은 미리 못 고르게만 합니다. */
export const USD_PREFIX = 'A75'
export const MKU_PREFIX = 'MKU'
/** 마스터의 품목 코드(국내 미국달러·해외 MKU). 「최근월물」이 어느 코드인지 보여 줄 때 이 품목의 월물을 봅니다. */
export const USD_PRODUCT = 'USD'
export const MKU_PRODUCT = 'MKU'
/** 미국달러선물·MKU 가 아닌 종목 줄에 서는 까닭. */
export const SYM_REFUSED = '이 실행기는 미국달러선물·MKU 만 됩니다'
/** 실시간 전략의 두 칸에서 반대 쪽 종목을 고른 줄의 까닭. */
export const SIGNAL_REFUSED = '신호 종목은 미국달러선물(KRX)만 됩니다'
export const ORDER_REFUSED = '주문 종목은 MKU 만 됩니다'
/** 종목을 안 고른 기본 선택. 서버가 최근월물을 고릅니다(`sym: null`). */
export const SYM_AUTO = '최근월물 (자동)'

export function isUsdFutures(code: string): boolean {
  return code.startsWith(USD_PREFIX)
}

export function isMku(code: string): boolean {
  return code.startsWith(MKU_PREFIX)
}

/** 칸마다 고를 수 있는 종목 — `any` 1분봉(국내·MKU), `usd` 실시간 신호(KRX), `mku` 실시간 주문. */
export type SymAllow = 'any' | 'usd' | 'mku'

/** 국내 품목 표 — 서버(`GET /products`)가 주는 틱 확인 표의 품목 뿌리. 이 표에 든 국내 선물만 고를 수 있습니다. */
export interface PyProducts {
  domestic: { root: string; name: string }[]
  domestic_excluded: string
}

/** 「최근월물 (자동)」을 뿌리로 말할 때의 줄 글 — `HO 최근월물 (자동)`. */
export function rootAutoLabel(root: string): string {
  return `${root} ${SYM_AUTO}`
}

/** 고를 수 있는 코드인지. 못 고르면 줄 오른쪽에 설 까닭이 함께 옵니다.
 *  `any`(1분봉 칸)는 해외 선물이면 OK, 국내 선물은 앞 세 자리가 `products.domestic` 의 뿌리면 OK 입니다.
 *  `products` 를 아직 못 받았으면 국내는 미국달러선물만 됩니다(예전 그대로). `usd`·`mku`(실시간 칸)는 예전 그대로입니다. */
export function symVerdict(
  code: string,
  allow: SymAllow = 'any',
  products?: PyProducts | null,
): { ok: true } | { ok: false; reason: string } {
  const usd = isUsdFutures(code)
  const mku = isMku(code)
  if (allow === 'usd') return usd ? { ok: true } : { ok: false, reason: mku ? SIGNAL_REFUSED : SYM_REFUSED }
  if (allow === 'mku') return mku ? { ok: true } : { ok: false, reason: usd ? ORDER_REFUSED : SYM_REFUSED }

  const inst = resolve(code)
  if (!inst) {
    /* 마스터를 아직 모르면 예전 규칙 — 미국달러선물·MKU 만. */
    return usd || mku ? { ok: true } : { ok: false, reason: SYM_REFUSED }
  }
  if (inst.kind === 'option') return { ok: false, reason: '옵션은 안 됩니다' }
  if (inst.kind === 'spread') return { ok: false, reason: '스프레드 종목은 안 됩니다' }
  if (inst.market === 'overseas') return { ok: true }
  if (inst.name.includes('야간')) return { ok: false, reason: '야간 종목은 안 됩니다' }
  if (!products) return usd ? { ok: true } : { ok: false, reason: '국내 품목 표를 받는 중입니다' }
  if (products.domestic.some((one) => one.root === code.slice(0, 3))) return { ok: true }
  return { ok: false, reason: '틱 확인 표에 없는 품목입니다 (주식선물 등)' }
}

/** 코드의 품목 뿌리 — 국내는 앞 세 자리, 해외는 마스터의 품목 코드. 모르면 null. */
export function rootOf(code: string): string | null {
  const inst = resolve(code)
  if (!inst) return null
  return inst.market === 'domestic' ? code.slice(0, 3) : inst.product.code
}

/** `HHMMSS`(자정을 넘으면 `253000`) → `HH:MM`, 다음 날이면 ` (+1)`. 서버 `tradeday.clock_text` 와 같은 결과입니다. */
export function clockText(hhmmss: string): string {
  const hour = Number(hhmmss.slice(0, 2))
  const text = `${String(hour % 24).padStart(2, '0')}:${hhmmss.slice(2, 4)}`
  return hour >= 24 ? `${text} (+1)` : text
}

/* ── 금액·날짜 ────────────────────────────────────────── */

/** 실행 통화. 이 기능 전 기록에는 없어 종목으로 정합니다(MKU 면 USD). */
export function currencyOf(run: { currency?: string | null; sym?: string | null }): string {
  if (run.currency) return run.currency
  return run.sym && isMku(run.sym) ? 'USD' : 'KRW'
}

/** 손익 글 — 부호를 붙이고, USD 는 `US$` 두 자리, 원은 앱의 원 표기(`moneyIn`)와 같습니다. */
export function pnlText(value: unknown, currency: string): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  if (currency === 'USD') {
    const text = Math.abs(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    const zero = Number(text.replace(/,/g, '')) === 0
    const sign = zero ? '' : value > 0 ? '+' : value < 0 ? MINUS : ''
    return `${sign}US$${text}`
  }
  return `${value > 0 ? '+' : ''}${moneyIn(value, 'KRW')}`
}

/** 기록 날짜를 `YYYYMMDD` 로. 1분봉 체결 표시는 `YYYY-MM-DD`, 실시간은 `YYYYMMDD` 로 오므로 둘 다 받습니다. */
export function dateDigits(date: string | null | undefined): string | null {
  if (!date) return null
  const digits = date.replace(/-/g, '')
  return /^\d{8}$/.test(digits) ? digits : null
}

/** 기본 선택의 글. 최근월물 코드를 마스터에서 알면 옆에 붙이고, 모르면 뺍니다. */
export function autoSymLabel(autoCode: string | null): string {
  return autoCode ? `${SYM_AUTO} · ${autoCode}` : SYM_AUTO
}

/** 기본 선택을 확인 얼굴에 적을 때의 글. 서버가 시작할 때 라이브 조회로 정하므로 코드는 어림입니다. */
export function autoSymGuess(autoCode: string | null): string {
  return autoCode
    ? `${SYM_AUTO} · 지금 기준 ${autoCode} — 시작할 때 서버가 정합니다`
    : `${SYM_AUTO} — 시작할 때 서버가 정합니다`
}

/** 지금 고른 종목의 글. `sym` 이 비면 기본 선택, 아니면 「이름 · 코드」(이름을 모르면 코드만). */
export function symLabel(sym: string, name: string | null, autoCode: string | null): string {
  const code = sym.trim()
  if (code === '') return autoSymLabel(autoCode)
  return name ? `${name} · ${code}` : code
}

export interface PyStrategyFile {
  file: string
  name: string
  title: string
  params: Record<string, unknown> | null
  /** 못 쓰는 파일이면 그 까닭. 이 파일로는 실행을 세울 수 없습니다. */
  error: string | null
  /** 알림(오류 아님) — 예: 익절 목표가 없어 익절 없이 돕니다. 실행은 세울 수 있습니다. */
  notes?: string[]
  /** 실행기 종류 — `realtime` 이면 종목 칸이 둘(신호·주문)입니다. 못 쓰는 파일은 null. */
  kind?: PyKind | null
  /** 종목을 비우면 쓸 시장(전략 TICK) — 「최근월물」 코드를 어림할 때 씁니다. 못 쓰는 파일은 null. */
  market?: 'domestic' | 'overseas' | null
}

/** 실행기 종류 — 1분봉 판정(`minute`) · 초 단위 실시간(`realtime`). */
export type PyKind = 'minute' | 'realtime'

export interface PyStrategies {
  folder: string
  strategies: PyStrategyFile[]
  /** 오류 없이 불러와지지만 전략 파일이 아닌 파일(공용 코드)의 이름, 이름순. 실행은 못 세우고 지울 수는 있습니다. */
  modules: string[]
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
  /* 1분봉 실행의 종목·시계 칸(모든 선물) — 옛 기록에는 없습니다. */
  product?: string | null
  exchange?: string | null
  tick?: number | null
  tick_value?: number | null
  overnight?: boolean | null
  trading_date?: string | null
  end?: string | null
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
  /** 실행기 종류·시장·통화. 이 기능 전 기록에는 없습니다(국내·원·1분봉). */
  kind?: PyKind
  market?: 'domestic' | 'overseas'
  currency?: string
  /* 실시간 실행만 — `sym` 은 주문 종목(MKU), `signal_sym` 은 신호 종목(KRX). */
  signal_sym?: string | null
  /** 실행 끝 시각(HHMMSS). */
  end_at?: string | null
  side?: string | null
  /** 보유 초. 보유가 없으면 null. */
  held_s?: number | null
  krx?: number | null
  bid?: number | null
  ask?: number | null
  mku_last?: number | null
  last_dk?: number | null
  last_rho?: number | null
  /** 마지막 KRX 체결·MKU 호가를 받은 시각(HHMMSS). */
  last_krx_at?: string | null
  last_quote_at?: string | null
  /** 체결 확인을 기다리는 중. */
  pending?: boolean
}

export function isRealtime(run: { kind?: string | null }): boolean {
  return run.kind === 'realtime'
}

/** 이 앱에서 지금 세운 실행인지 — `status()` 에만 판정 봉 칸이 있습니다(실시간은 값이 null 이지만 칸은 있음).
 *  지난 실행 폴더(`run.json`)는 중지·청산할 수 없습니다(서버가 409). */
export function isLiveRun(run: PyRunStatus): boolean {
  return 'bar_min' in run
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
  /** 1분봉은 `YYYY-MM-DD` 로 올 때가 있고 실시간은 `YYYYMMDD` 입니다 — 읽는 쪽은 `dateDigits` 로. */
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

/** 실시간 실행의 차트 줄 = 1분 요약(`minute` 줄). `time` 은 그 분 시작(HHMMSS), 없던 값은 null. */
export interface PyRtBar {
  date: string | null
  time: string | null
  krx: number | null
  mku_mid: number | null
  bid: number | null
  ask: number | null
  spread_ticks: number | null
  mku_last: number | null
  position: number | null
}

/** `/bars` — 1분봉이면 판정 봉, 실시간이면 1분 요약 줄. 표시(`marks`)는 두 종류가 같은 모양입니다.
 *  `kind` 는 이 기능 전 서버에는 없습니다(1분봉). */
export type PyBars =
  | { kind?: 'minute'; bars: PyBar[]; marks: PyMark[] }
  | { kind: 'realtime'; bars: PyRtBar[]; marks: PyMark[] }

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

/** 전략 파일 작성 규칙(마크다운 글 그대로). 화면은 꾸미지 않고 글로 보입니다. */
export async function loadConvention(signal?: AbortSignal): Promise<PyResult<string>> {
  const got = await call<{ markdown: string }>('/convention', undefined, signal)
  return got.ok ? { ok: true, data: got.data.markdown } : got
}

/** 종목 고르기용 국내 품목 표. */
export function loadProducts(signal?: AbortSignal): Promise<PyResult<PyProducts>> {
  return call<PyProducts>('/products', undefined, signal)
}

export async function loadRuns(signal?: AbortSignal): Promise<PyResult<PyRunStatus[]>> {
  const got = await call<{ runs: PyRunStatus[] }>('/runs', undefined, signal)
  return got.ok ? { ok: true, data: got.data.runs } : got
}

/** 실행을 세웁니다. 거부(409)·다른 사이트(403)는 서버 문장이 `why` 에 그대로 옵니다.
 *  `sym` 이 비면 서버가 최근월물을 고릅니다 — 빈 글(`""`)은 서버가 거절하므로 늘 `null` 로 보냅니다.
 *  `signalSym` 은 실시간 전략에만 넣습니다(`undefined` 면 칸을 아예 빼고, 비면 `null` = 국내 최근월물).
 *  서버는 모르는 칸을 422 로 거절하므로 본문은 `{file, mode, sym, signal_sym}` 그대로입니다. */
export function startRun(
  file: string,
  mode: 'orders' | 'paper',
  sym?: string | null,
  signalSym?: string | null,
): Promise<PyResult<PyRunStatus>> {
  const code = sym?.trim()
  const body: { file: string; mode: string; sym: string | null; signal_sym?: string | null } = {
    file,
    mode,
    sym: code ? code : null,
  }
  if (signalSym !== undefined) {
    const signal = signalSym?.trim()
    body.signal_sym = signal ? signal : null
  }
  return post<PyRunStatus>('/runs', body)
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

/* ── 매일 자동 시작 (`backend/team_pyrun/autostart.py`) ─────────────── */

/** 예약 하나 = (전략 파일, 방식). 장이 열리는 날마다 `at`(장 시작 5분 전)에 그날의 최근월물로 새 실행을 세웁니다.
 *  `blocked` 가 있으면 앞선 실행이 「확인 필요」·「오류」로 끝났거나 앱이 세우던 중에 꺼진 것 — 「다시 켜기」 전까지 안 세웁니다. */
export interface PySchedule {
  id: string
  file: string
  mode: 'orders' | 'paper'
  market: 'domestic' | 'overseas'
  at: string
  /** 종목 칸 — 품목 뿌리(`HO`)·종목 코드·비면 자동(옛 예약은 칸이 없음). */
  sym?: string | null
  blocked: string | null
  last_run_id: string | null
  last_result: string | null
  next_start: string | null
}

export async function loadSchedules(signal?: AbortSignal): Promise<PyResult<PySchedule[]>> {
  const got = await call<{ schedules: PySchedule[] }>('/schedules', undefined, signal)
  return got.ok ? { ok: true, data: got.data.schedules } : got
}

/** 자동 시작 만들기. `runId` = 방금 세운 실행 — 그날은 그 실행으로 치고 다음 장 날부터 세웁니다. 거부(409)는 서버 문장 그대로. */
export function createSchedule(
  file: string,
  mode: 'orders' | 'paper',
  runId?: string | null,
  sym?: string | null,
): Promise<PyResult<PySchedule>> {
  const body: { file: string; mode: string; run_id?: string; sym?: string } = { file, mode }
  if (runId) body.run_id = runId
  const code = sym?.trim()
  if (code) body.sym = code
  return post<PySchedule>('/schedules', body)
}

export function deleteSchedule(id: string): Promise<PyResult<void>> {
  return call<void>(`/schedules/${enc(id)}`, { method: 'DELETE' })
}

/** 막힌 자동 시작을 다시 켭니다(계좌·기록을 확인한 뒤). */
export function resumeSchedule(id: string): Promise<PyResult<PySchedule>> {
  return post<PySchedule>(`/schedules/${enc(id)}/resume`)
}

/** `2026-11-05T08:20:00` → `11/05 08:20`. */
export function scheduleTimeText(iso: string | null): string {
  if (!iso) return ''
  const m = /^\d{4}-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso)
  return m ? `${m[1]}/${m[2]} ${m[3]}:${m[4]}` : iso
}

/** 국내 품목 표를 한 번 받아 모든 종목 칸이 나눠 씁니다. 못 받으면 `null` 이고 다음에 다시 시도합니다. */
let productsCache: PyProducts | null = null

export function usePyProducts(): PyProducts | null {
  const [products, setProducts] = useState<PyProducts | null>(productsCache)
  useEffect(() => {
    if (productsCache) return
    const ctrl = new AbortController()
    void loadProducts(ctrl.signal).then((got) => {
      if (!got.ok) return
      productsCache = got.data
      setProducts(got.data)
    })
    return () => ctrl.abort()
  }, [])
  return products
}

/* ── 화면이 쓰는 훅 ─────────────────────────────────────── */

/** `POLL_MS` 마다 `tick` 을 부릅니다. 앞 요청이 끝나기 전에는 다음을 보내지 않고, 화면을
 *  떠나면(언마운트) 멈춥니다. `tick` 이 바뀌면(=보는 대상이 바뀌면) 바로 한 번 부릅니다. */
// 팀: 스프레드 탭(`data/spread.ts`)도 씁니다.
export function usePolling(tick: (signal: AbortSignal) => Promise<void>) {
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

const SCHEDULE_POLL_MS = 10_000

/** 매일 자동 시작 목록(10초마다, 그리고 `refresh()` 때). 「다음 시작」·「막힘」이 서버에서 바뀌므로 다시 묻습니다. */
export function usePySchedules() {
  const [items, setItems] = useState<PySchedule[] | null>(null)
  const [why, setWhy] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)
  useEffect(() => {
    const control = new AbortController()
    let timer = 0
    const loop = async () => {
      const got = await loadSchedules(control.signal)
      if (control.signal.aborted) return
      if (got.ok) {
        setItems(got.data)
        setWhy(null)
      } else setWhy(got.why)
      timer = window.setTimeout(() => void loop(), SCHEDULE_POLL_MS)
    }
    void loop()
    return () => {
      control.abort()
      window.clearTimeout(timer)
    }
  }, [nonce])
  const refresh = useCallback(() => setNonce((n) => n + 1), [])
  /** 화면이 단 알림(만들기·끄기·다시 켜기 거부) — 폴링이 지우지 않습니다. 다음 조작이 성공하면 비웁니다. */
  const [note, setNote] = useState<string | null>(null)
  return { items, why: note ?? why, refresh, setNote }
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
/** 이 갈래의 줄이 새로 오면 차트 봉을 다시 받습니다(봉·표시가 바뀌는 줄). `minute` 은 실시간의 1분 요약 줄입니다. */
const CHART_KINDS = new Set(['signal', 'fill', 'trade', 'minute'])

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
