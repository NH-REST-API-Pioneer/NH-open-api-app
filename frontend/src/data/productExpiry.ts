/** 해외 종목의 만기 정보를 받아 두는 자리 — 최종거래일·최초통보일·최종결제일·결제방법.
 *
 *  **종목마다 한 번 받고 그대로 둡니다.** 만기는 하루 안에 바뀌는 값이 아니라
 *  화면을 나갔다 와도 다시 안 부릅니다. 못 받은 자리만 그 자리가 다시 설 때
 *  한 번 더 부릅니다 — 연결이 잠깐 끊긴 탓에 빈 칸이 세션 내내 남지 않게.
 *
 *  **손질은 하지 않습니다.** 서버가 날짜를 `YYYY-MM-DD` 로, 결제방법을 낱말로
 *  이미 화면 모양으로 냅니다(`overseas_products.py`). 없는 종목은 빈 목록으로
 *  오고, 그때 이 자리는 「받았는데 없다」입니다 — 못 받은 것과 다릅니다.
 */
import { useEffect, useSyncExternalStore } from 'react'

export interface ProductExpiry {
  code: string
  name: string
  productCode: string
  exchange: string
  /** 결제방법 — 「현금」·「실물」 같은 낱말 그대로. */
  settlement: string | null
  /** 최초통보일. 실물인수도 종목에서 인수 의무가 시작되는 날입니다. */
  firstNotice: string | null
  /** 만기일 = 최종거래일. */
  expiry: string | null
  lastSettlement: string | null
  remainingDays: number | null
}

export interface ExpiryEntry {
  /** `idle` 은 아직 안 불렀다는 뜻입니다. */
  status: 'idle' | 'loading' | 'ready' | 'failed'
  /** **`null` 은 「받은 적 없다」또는 「받았는데 없다」** — `status` 가 가릅니다. */
  row: ProductExpiry | null
  /** 거절(502)은 눌러도 같은 답이 오고, 그 밖(시간 초과 등)은 다시 불러 볼 만합니다. */
  failure: 'retry' | 'rejected' | null
}

const EMPTY: ExpiryEntry = { status: 'idle', row: null, failure: null }

const entries = new Map<string, ExpiryEntry>()
const listeners = new Set<() => void>()
/** 나가 있는 물음. 같은 종목을 겹쳐 묻지 않습니다. */
const flying = new Set<string>()

function announce(code: string, next: ExpiryEntry): void {
  entries.set(code, next)
  for (const listener of listeners) listener()
}

export function subscribeProductExpiry(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function productExpiryEntry(code: string): ExpiryEntry {
  return entries.get(code) ?? EMPTY
}

/** 한 종목의 만기 정보를 부릅니다. 종목코드로 물으면 그 월물 한 줄이 옵니다. */
export async function loadProductExpiry(code: string): Promise<void> {
  if (!code || flying.has(code)) return
  flying.add(code)
  const held = entries.get(code) ?? EMPTY
  announce(code, { ...held, status: 'loading', failure: null })
  try {
    const response = await fetch('/api/overseas/product-expiry', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sym: code }),
    })
    if (!response.ok) {
      announce(code, {
        ...held,
        status: held.row ? 'ready' : 'failed',
        failure: response.status === 502 ? 'rejected' : 'retry',
      })
      return
    }
    const body = (await response.json()) as { rows?: ProductExpiry[] }
    const rows = Array.isArray(body.rows) ? body.rows : []
    /* **부른 종목의 줄만 씁니다.** 다른 코드의 줄이 왔으면 없는 것으로 둡니다 —
       만기 날짜는 청산 시점을 정하는 값이라, 다른 월물의 날짜가 이 종목 것으로
       서면 그 값으로 판단하게 됩니다. 현재가가 다른 종목의 답을 버리는 것과 같은
       규칙입니다. */
    const row = rows.find((item) => item.code === code) ?? null
    announce(code, { status: 'ready', row, failure: null })
  } catch {
    announce(code, { ...held, status: held.row ? 'ready' : 'failed', failure: 'retry' })
  } finally {
    flying.delete(code)
  }
}

export function retryProductExpiry(code: string): void {
  void loadProductExpiry(code)
}

/** 한 종목의 만기 정보를 읽고, 아직 안 불렀으면 부릅니다. 빈 코드는 안 부릅니다 —
 *  행사가를 아직 안 고른 옵션 자리처럼 종목이 없는 자리입니다.
 *
 *  **다시 불러 볼 만한 실패는 이 자리가 설 때 한 번 더 부릅니다.** 부르는 것은
 *  자리가 설 때뿐이라 실패가 이어져도 되풀이 부르지 않습니다. 거절(502)은 눌러도
 *  같은 답이라 안 부릅니다. */
export function useProductExpiry(code: string): ExpiryEntry {
  const entry = useSyncExternalStore(
    subscribeProductExpiry,
    () => productExpiryEntry(code),
    () => EMPTY,
  )
  useEffect(() => {
    if (!code) return
    const held = productExpiryEntry(code)
    if (held.status === 'idle' || (held.status === 'failed' && held.failure === 'retry')) {
      void loadProductExpiry(code)
    }
  }, [code])
  return entry
}
