/** 투자자별 매매동향을 받아 두는 자리.
 *
 *  국내 시장자료 탭의 표 하나가 이 값을 봅니다. **서버가 준 무리를 그대로 그립니다** —
 *  「기관」처럼 여럿을 합친 줄은 만들지 않습니다. 합치는 규칙은 우리가 정하는 것이고,
 *  그 줄을 보는 사람은 서버가 그렇게 답한 줄로 읽습니다.
 *
 *  **하루에 몇 번 안 바뀌는 값입니다.** 체결마다 움직이는 시세와 달라 자주 물을
 *  까닭이 없고, 계좌·시세와 같은 호출 한도를 나눠 쓰므로 탭이 보이는 동안 1분에
 *  한 번입니다.
 *
 *  **기록이 없는 품목은 「없음」입니다.** 서버가 빈 목록으로 답하고, 화면은 그것을
 *  「받았는데 줄이 없다」로 그립니다 — 못 받은 것과 다른 상태입니다.
 */
import { useEffect, useSyncExternalStore } from 'react'

import { accepts, generation, onEnvironmentChange } from './environment'

/** 투자자 무리 한 줄. **이름과 차례는 서버가 정합니다.**
 *
 *  **그리는 칸만 담습니다.** 응답에는 전일 매수·매도와 비중도 오지만 표가 안
 *  세우므로 여기서 걷지 않습니다 — 담아 두면 어디선가 쓰는 줄 알고 화면이
 *  그 값을 찾게 됩니다. 세울 날이 오면 그때 함께 늘립니다. */
export interface InvestorRow {
  /** 무리 이름(영문 열쇠). 화면 글자는 `INVESTOR_LABEL` 이 답합니다. */
  group: string
  buy: number | null
  sell: number | null
  netBuy: number | null
}

/** 무리 이름의 우리말. **서버가 주는 열한 무리 그대로**이고, 표에 없는 열쇠는
 *  받은 글자를 그대로 세웁니다 — 새 무리가 생겨도 줄이 사라지지 않습니다. */
/** 센 것의 단위. 표 머리에 괄호로 붙습니다 — 모르는 값이면 안 붙입니다. */
export const UNIT_LABEL: Record<string, string> = { quantity: '계약', amount: '원' }

export const INVESTOR_LABEL: Record<string, string> = {
  individual: '개인',
  foreign: '외국인',
  securitiesFutures: '증권선물',
  insurance: '보험',
  investmentTrust: '투신',
  bank: '은행',
  pensionFund: '연기금',
  nationalFund: '국가기금공제',
  merchantBank: '종금',
  other: '기타',
  total: '합계',
}

export interface TrendEntry {
  status: 'idle' | 'loading' | 'ready' | 'failed'
  rows: InvestorRow[] | null
  /** 어느 날 것인지와 몇 시 것인지. 서버가 준 값입니다. */
  date: string | null
  time: string | null
  /** 수가 **무엇을 센 것인지**. `quantity` 계약 수, `amount` 금액입니다 —
   *  모르면 읽을 수 없는 숫자라 표 머리가 이 값을 함께 답니다. */
  unit: string | null
}

const EMPTY: TrendEntry = { status: 'idle', rows: null, date: null, time: null, unit: null }

const entries = new Map<string, TrendEntry>()
const listeners = new Set<() => void>()
const flying = new Map<string, number>()

/** 담는 열쇠. 품목과 종류가 함께 듭니다 — 선물·콜·풋이 서로 다른 답입니다. */
function keyOf(productCode: string, kind: string): string {
  return `${productCode}|${kind}`
}

function announce(key: string, next: TrendEntry): void {
  entries.set(key, next)
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/** 한 번 묻습니다. 같은 품목이 나가 있으면 겹쳐 묻지 않습니다. */
export async function loadTrend(productCode: string, kind: string): Promise<void> {
  const key = keyOf(productCode, kind)
  const since = generation()
  if (flying.get(key) === since) return
  flying.set(key, since)
  const held = entries.get(key) ?? EMPTY
  announce(key, { ...held, status: held.rows ? 'ready' : 'loading' })

  try {
    const response = await fetch('/api/domestic/trend-investor', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prd: productCode, kind }),
    })
    if (since !== generation()) return
    if (!accepts(response, since)) return
    if (!response.ok) {
      announce(key, { ...held, status: held.rows ? 'ready' : 'failed' })
      return
    }
    const body = (await response.json()) as {
      investors?: unknown
      date?: unknown
      time?: unknown
      unit?: unknown
    }
    const list = Array.isArray(body.investors) ? (body.investors as Record<string, unknown>[]) : []
    announce(key, {
      status: 'ready',
      rows: list.map((row) => ({
        group: String(row.group ?? ''),
        buy: num(row.buy),
        sell: num(row.sell),
        netBuy: num(row.netBuy),
      })),
      date: typeof body.date === 'string' ? body.date : null,
      time: typeof body.time === 'string' ? body.time : null,
      unit: typeof body.unit === 'string' ? body.unit : null,
    })
  } catch {
    if (since !== generation()) return
    announce(key, { ...held, status: held.rows ? 'ready' : 'failed' })
  } finally {
    if (flying.get(key) === since) flying.delete(key)
  }
}

/** 다시 묻는 간격. **시세보다 훨씬 느립니다** — 하루에 몇 번 안 바뀌는 값이라
 *  자주 물으면 같은 답을 받으려고 다른 조회를 밀어냅니다. */
export const TREND_POLL_MS = 60_000

/** **탭이 보이는 동안만** 받습니다. 값 자체는 돌려주는 것으로 읽습니다. */
export function useTrend(productCode: string | null, kind: string, active: boolean): TrendEntry {
  const key = productCode ? keyOf(productCode, kind) : ''
  const entry = useSyncExternalStore(
    subscribe,
    () => (key ? (entries.get(key) ?? EMPTY) : EMPTY),
    () => EMPTY,
  )

  useEffect(() => {
    if (!productCode || !active) return
    let timer: number | undefined
    const ask = () => {
      if (document.hidden) return
      void loadTrend(productCode, kind)
    }
    const onVisible = () => {
      if (!document.hidden) ask()
    }
    ask()
    timer = window.setInterval(ask, TREND_POLL_MS)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      if (timer !== undefined) window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [productCode, kind, active])

  return entry
}

/* 환경이 바뀌면 전부 지웁니다 — 다른 서버의 답입니다. */
onEnvironmentChange((change) => {
  if (change.kind !== 'switched') return
  entries.clear()
  for (const listener of listeners) listener()
})
