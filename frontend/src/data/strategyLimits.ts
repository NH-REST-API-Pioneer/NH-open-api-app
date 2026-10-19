/* 계좌 전체 손실 한도 — 계좌 축마다, 통화마다 하루 손실 한도 하나.
 *
 * 축은 둘입니다. 모의 쪽(`paper` — 모의 계좌·앱 시뮬레이션 실행)과 실전 계좌
 * 쪽(`real`)이고, 서버가 따로 담고 따로 셉니다. 화면은 **접속 환경의 축**을 보고
 * 고칩니다.
 *
 * 한도는 **통화마다**입니다(`KRW`·`USD`·`HKD`…). 국내는 원이고, 해외는 품목마다
 * 통화가 다릅니다 — 통화가 다른 손익은 더하지 않습니다. **`null` 은 「안 걸었음」**
 * 이고 0 과 다릅니다(0 은 서버가 받지 않습니다). 한도에 닿으면 서버가 그 축·그
 * 통화로 셈하는 실행을 모두 멈춥니다.
 *
 * 답이 시장 이름(`domestic` = 원, `overseas` = 달러)으로 오면 원·달러 칸으로
 * 읽습니다. 저장은 **그 축의 통화 전부를 함께** 보냅니다 —
 * 서버는 그 축에서 안 보낸 통화를 「안 건 것」으로 지웁니다. 다른 축은 안 보내면
 * 그대로 둡니다.
 */
import { useSyncExternalStore } from 'react'
import { tookStore, type StoreState } from './strategyStore'

/** 늘 칸이 있는 통화 — 국내(원)와 해외 기본(달러). */
export const BASE_CURRENCIES = ['KRW', 'USD'] as const

/** 시장 이름으로 온 한도 → 그 통화. */
const LEGACY: Record<string, string> = { domestic: 'KRW', overseas: 'USD' }

/** 통화마다의 하루 손실 한도. `null` 은 안 걸었음입니다. */
export type Limits = Record<string, number | null>

/** 한도의 계좌 축. 모의 쪽(모의 계좌·앱 시뮬레이션)과 실전 계좌 쪽입니다. */
export type LimitAxis = 'paper' | 'real'

export interface LimitsState {
  /** `idle` 은 아직 안 불렀음입니다. */
  status: 'idle' | 'loading' | 'ready' | 'failed'
  limits: Limits | null
  /** 실전 계좌 쪽 한도. 이 축을 안 싣는 서버면 `null` 입니다. */
  real: Limits | null
  /** 한도 파일을 읽은 상태. 못 읽었거나 다른 앱의 파일이면 담긴 한도가 풀린
   *  것이라 화면이 그렇다고 말합니다. */
  store: StoreState | null
}

const ROUTE = '/api/strategy/limits'

/** 통화 코드 모양 — 세 글자 영문 대문자. */
export const CURRENCY_CODE = /^[A-Z]{3}$/

let state: LimitsState = { status: 'idle', limits: null, real: null, store: null }
const listeners = new Set<() => void>()

function announce(next: LimitsState): void {
  state = next
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useLimits(): LimitsState {
  return useSyncExternalStore(subscribe, () => state, () => state)
}

/** 한 칸의 값 — 수가 아니거나 0 이하면 안 건 것입니다. */
function amountOf(row: unknown): number | null {
  const value = (row as { dailyLoss?: unknown } | undefined)?.dailyLoss
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null
}

/** 답의 한도를 읽습니다. **통화 열쇠가 먼저**이고, 통화 열쇠가 하나도 없는 옛 답은
 *  시장 이름을 원·달러 칸으로 읽습니다. 원·달러 칸은 늘 있습니다. */
function limitsOf(raw: unknown): Limits | null {
  if (!raw || typeof raw !== 'object') return null
  const rows = raw as Record<string, unknown>
  const made: Limits = { KRW: null, USD: null }
  const codes = Object.keys(rows).filter((key) => CURRENCY_CODE.test(key))
  if (codes.length > 0) {
    for (const code of codes) made[code] = amountOf(rows[code])
  } else {
    for (const [market, code] of Object.entries(LEGACY)) {
      if (market in rows) made[code] = amountOf(rows[market])
    }
  }
  return made
}

let flying = false

/** 한도를 읽습니다. 읽는 중에 또 부르면 겹쳐 묻지 않습니다. 앞 값이 있으면 읽는
 *  동안에도 그대로 둡니다. */
export async function loadLimits(): Promise<void> {
  if (flying) return
  flying = true
  announce({ ...state, status: state.limits ? 'ready' : 'loading' })
  try {
    const response = await fetch(ROUTE)
    if (!response.ok) {
      announce({ ...state, status: state.limits ? 'ready' : 'failed' })
      return
    }
    const body = (await response.json()) as { limits?: unknown; real?: unknown }
    const limits = limitsOf(body.limits)
    if (!limits) {
      announce({ ...state, status: state.limits ? 'ready' : 'failed' })
      return
    }
    announce({ status: 'ready', limits, real: limitsOf(body.real), store: tookStore(body) })
  } catch {
    announce({ ...state, status: state.limits ? 'ready' : 'failed' })
  } finally {
    flying = false
  }
}

/** 저장의 답. 실패면 칸(통화)마다의 까닭(서버가 그 칸을 짚었을 때)과 창 아래에 설 문장. */
export type SaveLimitsResult =
  | { ok: true }
  | { ok: false; fields: Partial<Record<string, string>>; message: string | null }

/** 한 축의 통화 전부를 함께 담습니다. **그 축만 보냅니다** — 모의 쪽은 몸 맨 위에
 *  통화 열쇠로(`{"KRW": {dailyLoss}, "USD": …}`), 실전 쪽은 `real` 안에 같은 꼴로
 *  실리고, 안 보낸 축은 서버가 그대로 둡니다. 성공이면 **서버가 담았다고 답한
 *  값**으로 두 축을 갈아 끼웁니다 — 다시 읽지 않습니다. 파일을 다시 썼으므로
 *  「풀렸습니다」 알림도 걷힙니다. */
export async function saveLimits(values: Limits, axis: LimitAxis): Promise<SaveLimitsResult> {
  const rows: Record<string, { dailyLoss: number | null }> = {}
  for (const [code, value] of Object.entries(values)) {
    if (CURRENCY_CODE.test(code)) rows[code] = { dailyLoss: value }
  }
  const body = JSON.stringify(axis === 'real' ? { real: rows } : rows)
  let response: Response
  try {
    response = await fetch(ROUTE, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body,
    })
  } catch {
    return { ok: false, fields: {}, message: '저장하지 못했습니다 — 서버에 닿지 않습니다' }
  }
  const said = (await response.json().catch(() => null)) as {
    limits?: unknown
    real?: unknown
    detail?: unknown
  } | null
  if (response.ok) {
    const limits = limitsOf(said?.limits)
    const real = limitsOf(said?.real)
    announce({
      status: 'ready',
      limits: limits ?? (axis === 'paper' ? values : state.limits),
      real: real ?? (axis === 'real' ? values : state.real),
      store: null,
    })
    return { ok: true }
  }
  /* 서버가 칸을 짚은 거절(400)은 **그 통화 칸 아래**에 섭니다. 짚은 칸이 한도 칸이
     아니면 창 아래 한 줄입니다. 그 밖 실패는 서버 문장 그대로, 없으면 상태 코드만
     적습니다 — 까닭을 지어 서버의 말처럼 세우지 않습니다. */
  const detail = said?.detail
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const shaped = detail as { message?: unknown; problems?: unknown }
    const fields: Partial<Record<string, string>> = {}
    let loose: string | null = null
    for (const one of Array.isArray(shaped.problems) ? shaped.problems : []) {
      const row = one as { field?: unknown; message?: unknown }
      const text = typeof row.message === 'string' ? row.message : ''
      /* 실전 축의 칸은 서버가 `real.` 을 앞에 붙여 짚습니다. 칸은 `{통화}.dailyLoss` 이거나
         통화 열쇠 자체(모르는 통화·두 번 보냄)입니다. */
      const prefix = axis === 'real' ? 'real.' : ''
      const field = typeof row.field === 'string' ? row.field : ''
      const rest = field.startsWith(prefix) ? field.slice(prefix.length) : ''
      const code = rest.replace(/\.dailyLoss$/, '')
      if (CURRENCY_CODE.test(code) && text) fields[code] = text
      else if (text) loose ??= text
    }
    const message =
      Object.keys(fields).length > 0 && loose === null
        ? null
        : loose ?? (typeof shaped.message === 'string' ? shaped.message : null)
    return {
      ok: false,
      fields,
      message: message ?? (Object.keys(fields).length > 0 ? null : `저장하지 못했습니다 (${response.status})`),
    }
  }
  return {
    ok: false,
    fields: {},
    message:
      typeof detail === 'string' && detail.trim() !== ''
        ? detail.trim()
        : `저장하지 못했습니다 (${response.status})`,
  }
}
