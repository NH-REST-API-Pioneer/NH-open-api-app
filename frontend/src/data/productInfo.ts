/** 국내 종목 하나의 품목 값을 받아 두는 자리 — 호가단위·틱값·거래승수.
 *
 *  **국내 종목 마스터에는 호가단위 칸이 없습니다.** 해외 마스터는 종목마다
 *  호가단위(`tsiz`)와 틱값(`tval`)을 실어 주지만 국내는 그렇지 않아, 화면이
 *  「이 종목이 한 번에 얼마씩 움직이나」를 알 길이 품목 표뿐입니다. 그 표를
 *  종목코드로 골라 주는 자리가 `/api/domestic/product-info` 입니다.
 *
 *  **그래서 국내만 부릅니다.** 해외에도 같은 이름의 라우트가 있지만 호가단위를
 *  안 냅니다 — 같은 값을 두 자리에서 내면 화면이 둘 중 하나를 고르게 됩니다.
 *
 *  **종목마다 한 번 받고 그대로 둡니다.** 호가단위는 하루 안에 바뀌는 값이
 *  아닙니다. 값이 낡는 것은 서버가 봅니다 — 거래일 경계를 넘기면 서버가 표를
 *  다시 받아 냅니다(`domestic_routes.read_product_info`). 못 받은 자리만 그
 *  자리가 다시 설 때 한 번 더 부릅니다.
 *
 *  **못 받은 것과 없는 것을 가릅니다.** 서버가 값을 못 채우면 까닭(`why`)을
 *  함께 냅니다 — 마스터를 아직 못 받았을 때와 그 종목을 못 찾았을 때가 사용자
 *  입장에서 다른 일입니다. 가격 칸의 안내가 그 문장을 **마우스를 올리면
 *  보이는 자리**에 답니다 — 칸이 좁아 보이는 글자로는 못 세웁니다.
 *
 *  **「아직 안 왔다」와 「못 받았다」도 다릅니다.** 종목을 고를 때마다 답이 오기
 *  전 한 박자가 있어, 그 사이를 못 받은 것으로 읽으면 화면이 거짓을 말합니다 —
 *  `status` 가 그 둘을 가릅니다.
 */
import { useEffect, useSyncExternalStore } from 'react'

export interface ProductInfo {
  code: string
  productCode: string | null
  productName: string | null
  productKind: string | null
  /** 호가단위. 가격을 한 칸 올리고 내리는 눈금입니다. */
  tickSize: number | null
  /** 한 칸 움직일 때의 금액. */
  tickValue: number | null
  /** 거래승수. */
  multiplier: number | null
  /** 계약 하나의 개시증거금(원). 받은 값 그대로라 소수가 붙어 올 수 있습니다.
   *  옵션은 품목정보에 증거금이 없어 늘 `null` 입니다. */
  contractInitialMargin: number | null
  /** 개시증거금률. **글자 그대로**(`4.83%`) 옵니다 — 단위까지 서버가 붙입니다. */
  initialMarginRate: string | null
  /** 유지증거금률. 위와 같습니다. */
  maintenanceMarginRate: string | null
  /** 계약당 유지증거금이 없는 까닭. 품목을 찾았을 때만 오는 고객용 문장입니다. */
  maintenanceMarginWhy: string | null
  /** 값을 못 채운 까닭. 채웠으면 빈 글자입니다. */
  why: string
  /** `why` 의 갈래(`no_margin`·`no_product` 등). 다 채웠으면 `null` 입니다.
   *  **갈래는 이것으로 가릅니다** — `why` 는 다듬을 수 있는 문장이라 그 글자로
   *  가르면 문장을 고칠 때 화면의 갈림이 소리 없이 어긋납니다. */
  whyCode: string | null
}

/** 이 앱이 서버에서 품목 값을 받지 못했을 때 그 자리에 다는 까닭. */
export const PRODUCT_INFO_FAILED = '품목정보를 받지 못했습니다'

/** 원 단위 올림. **곱셈의 부동소수 찌꺼기를 먼저 걷어 냅니다** — 649,924.8 × 5 는
 *  3,249,624 이어야 하는데, 곱이 3,249,624.0000000005 로 나오면 그대로 올려 1원이
 *  커집니다. 받는 값이 소수 셋째 자리까지라 여섯째 자리에서 끊어도 셈이 바뀌지
 *  않습니다. */
export function ceilWon(value: number): number {
  return Math.ceil(Number(value.toFixed(6)))
}

export interface ProductInfoEntry {
  /** `idle` 은 아직 안 불렀다는 뜻입니다. */
  status: 'idle' | 'loading' | 'ready' | 'failed'
  /** **`null` 은 「받은 적 없다」입니다.** 받았는데 값이 비어 있는 것은 줄이
   *  서 있고 `row.why` 가 까닭을 말하는 쪽입니다. */
  row: ProductInfo | null
  /** 거절(502)은 눌러도 같은 답이 오고, 그 밖은 다시 불러 볼 만합니다. */
  failure: 'retry' | 'rejected' | null
}

const EMPTY: ProductInfoEntry = { status: 'idle', row: null, failure: null }

const entries = new Map<string, ProductInfoEntry>()
const listeners = new Set<() => void>()
/** 나가 있는 물음. 같은 종목을 겹쳐 묻지 않습니다. */
const flying = new Set<string>()

function announce(code: string, next: ProductInfoEntry): void {
  entries.set(code, next)
  for (const listener of listeners) listener()
}

export function subscribeProductInfo(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function productInfoEntry(code: string): ProductInfoEntry {
  return entries.get(code) ?? EMPTY
}

export async function loadProductInfo(code: string): Promise<void> {
  if (!code || flying.has(code)) return
  flying.add(code)
  const held = entries.get(code) ?? EMPTY
  announce(code, { ...held, status: 'loading', failure: null })
  try {
    const response = await fetch('/api/domestic/product-info', {
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
    const row = (await response.json()) as ProductInfo
    /* **부른 종목의 답만 씁니다.** 다른 코드의 줄이 왔으면 없는 것으로 둡니다 —
       호가단위는 주문가격을 정하는 값이라, 다른 종목의 눈금이 이 종목 것으로
       서면 그 눈금으로 주문을 냅니다. */
    if (row && row.code === code) announce(code, { status: 'ready', row, failure: null })
    else announce(code, { ...held, status: held.row ? 'ready' : 'failed', failure: 'retry' })
  } catch {
    announce(code, { ...held, status: held.row ? 'ready' : 'failed', failure: 'retry' })
  } finally {
    flying.delete(code)
  }
}

/** 한 종목의 품목 값을 읽고, 아직 안 불렀으면 부릅니다.
 *
 *  **빈 코드는 안 부릅니다** — 행사가를 아직 안 고른 옵션 자리처럼 종목이 없는
 *  자리입니다. 해외 종목도 부르는 쪽이 빈 글자를 넘겨 막습니다.
 *
 *  다시 불러 볼 만한 실패는 이 자리가 설 때 한 번 더 부릅니다. 거절(502)은
 *  눌러도 같은 답이라 안 부릅니다. */
export function useProductInfo(code: string): ProductInfoEntry {
  const entry = useSyncExternalStore(
    subscribeProductInfo,
    () => productInfoEntry(code),
    () => EMPTY,
  )
  useEffect(() => {
    if (!code) return
    const held = productInfoEntry(code)
    if (held.status === 'idle' || (held.status === 'failed' && held.failure === 'retry')) {
      void loadProductInfo(code)
    }
  }, [code])
  return entry
}

/* ── 해외 ─────────────────────────────────────────────
 *
 * 해외는 **다른 칸**이 없어서 부르는 것이 아니라, 종목 마스터가 안 주는 칸이
 * 있어서 부릅니다 — 계약단위·인수도구분·적용일자입니다. 호가단위와 틱값은
 * 마스터가 주므로 이 라우트가 아예 내지 않습니다(같은 값을 두 곳에서 내면
 * 어긋나는 날 어느 쪽이 맞는지 못 가립니다).
 */

/** 해외 종목 하나의 품목 값. 서버가 채우지 못한 칸은 `null` 이고 `why` 가
 *  까닭을 말합니다. */
export interface OverseasProductInfo {
  code: string
  productCode: string | null
  productName: string | null
  productKind: string | null
  /** 계약단위 — 한 계약이 몇 단위인가. */
  contractUnit: number | null
  currency: string | null
  /** 인수도구분. **서버가 영어 코드로 줍니다**(`cash`·`physical`). */
  delivery: string | null
  /** 그 품목 값이 적용된 날짜. */
  appliedDate: string | null
  /** 품목 표가 방금 받은 것(`api`)인지 받아 둔 것(`cache`)인지. **화면에는 안
   *  세웁니다** — 사용자가 할 일이 달라지지 않는 값입니다. */
  source: string | null
  /** 값을 못 채운 까닭. 채웠으면 빈 글자입니다. */
  why: string
}

export interface OverseasProductInfoEntry {
  status: 'idle' | 'loading' | 'ready' | 'failed'
  row: OverseasProductInfo | null
  failure: 'retry' | 'rejected' | null
}

const OVERSEAS_EMPTY: OverseasProductInfoEntry = { status: 'idle', row: null, failure: null }

const overseasEntries = new Map<string, OverseasProductInfoEntry>()
const overseasFlying = new Set<string>()

function announceOverseas(code: string, next: OverseasProductInfoEntry): void {
  overseasEntries.set(code, next)
  for (const listener of listeners) listener()
}

export function overseasProductInfoEntry(code: string): OverseasProductInfoEntry {
  return overseasEntries.get(code) ?? OVERSEAS_EMPTY
}

export async function loadOverseasProductInfo(code: string): Promise<void> {
  if (!code || overseasFlying.has(code)) return
  overseasFlying.add(code)
  const held = overseasEntries.get(code) ?? OVERSEAS_EMPTY
  announceOverseas(code, { ...held, status: 'loading', failure: null })
  try {
    const response = await fetch('/api/overseas/product-info', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sym: code }),
    })
    if (!response.ok) {
      announceOverseas(code, {
        ...held,
        status: held.row ? 'ready' : 'failed',
        failure: response.status === 502 ? 'rejected' : 'retry',
      })
      return
    }
    const row = (await response.json()) as OverseasProductInfo
    /* **부른 종목의 답만 씁니다** — 국내와 같은 규칙입니다. */
    if (row && row.code === code) announceOverseas(code, { status: 'ready', row, failure: null })
    else announceOverseas(code, { ...held, status: held.row ? 'ready' : 'failed', failure: 'retry' })
  } catch {
    announceOverseas(code, { ...held, status: held.row ? 'ready' : 'failed', failure: 'retry' })
  } finally {
    overseasFlying.delete(code)
  }
}

/** 해외 종목 하나의 품목 값을 읽고, 아직 안 불렀으면 부릅니다. 규칙은 국내와
 *  같습니다 — 빈 코드는 안 묻고, 다시 불러 볼 만한 실패만 한 번 더 묻습니다. */
export function useOverseasProductInfo(code: string): OverseasProductInfoEntry {
  const entry = useSyncExternalStore(
    subscribeProductInfo,
    () => overseasProductInfoEntry(code),
    () => OVERSEAS_EMPTY,
  )
  useEffect(() => {
    if (!code) return
    const held = overseasProductInfoEntry(code)
    if (held.status === 'idle' || (held.status === 'failed' && held.failure === 'retry')) {
      void loadOverseasProductInfo(code)
    }
  }, [code])
  return entry
}
