/** 계좌 값을 받아 두는 자리.
 *
 *  **시장마다 따로 담습니다.** 국내와 해외는 다른 계좌이고 응답 모양도 다릅니다.
 *
 *  **한 번 받은 값은 화면을 나갔다 와도 그대로 둡니다.** 홈을 떠났다 돌아올
 *  때마다 뼈대로 되돌리면, 값이 이미 있는데도 없는 것처럼 보입니다. 다시 부르되
 *  자리는 채워 둔 채로 채웁니다 — 골격이 안 바뀌는 갱신에서 값을 지우지
 *  않는다는 규칙입니다.
 *
 *  **저절로 부르는 곳과 눌러야 부르는 곳이 갈립니다.** 홈은 훑는 화면이라 열릴
 *  때 저절로 부르고, 계좌 화면은 탭을 연 것만 부릅니다. 계좌 조회에는 초당
 *  한도가 있어(계좌마다 열), 안 보는 자리까지 부르면 보는 자리가 밀립니다.
 *
 *  **손질은 여기서 하지 않습니다.** 백엔드가 이미 화면 모양으로 냈습니다
 *  (`domestic_account.py` · `overseas_account.py`). 여기서 다시 더하거나 고치면
 *  같은 규칙이 두 곳에 생기고, 한쪽만 바뀔 때 조용히 갈립니다.
 *
 *  **환경(모의·실전)이 바뀌면 전부 지웁니다.** 「나갔다 와도 안 지운다」는 같은
 *  계좌의 낡은 값을 지키는 규칙이지, 다른 계좌의 값을 지키는 규칙이 아닙니다 —
 *  두면 실전 배지 밑에 모의 잔고가 섭니다. 값마다 어느 환경의 답인지를 붙여 두고,
 *  환경을 몰랐다가 알게 될 때는 이름이 같은 값은 두고 다른 값만 지웁니다.
 *  환경을 아직 모르는 동안은 조회를 내지 않습니다(`data/environment.ts`).
 */
import { useEffect, useRef, useSyncExternalStore } from 'react'

import {
  accepts,
  environmentOf,
  generation,
  marketConfigured,
  onEnvironmentChange,
  useEnvironment,
  type Environment,
} from './environment'
import { kstClock } from '../lib/kst'
import { MINUS } from '../lib/number'

/** 네 칸(총액·현금·대용·외화)을 가진 줄. 국내는 일곱 줄 모두, 해외는 둘뿐입니다. */
export interface DepositRow {
  key: string
  label: string
  /** 총액·현금·대용·외화 차례. **값은 비어 올 수 있습니다** — 없으면 `null`
   *  이고, 그것은 0 이 아니라 「이 자리에 값이 없다」는 뜻입니다. */
  values: (number | null)[]
}

/** 총액 하나뿐인 줄. 해외에만 있습니다. */
export interface DepositItem {
  key: string
  label: string
  value: number | null
}

export interface DomesticDeposit {
  date: string | null
  /** 일곱 줄 × 네 칸. 차례가 곧 표에 서는 차례입니다. */
  items: DepositRow[]
  fee: number | null
  nightFee: number | null
  futuresSettlement: number | null
  nightSettlement: number | null
  futuresIntradayLoss: number | null
  futuresRealisedPl: number | null
  optionUnrealisedPl: number | null
  optionRealisedPl: number | null
  totalPl: number | null
  nextDaySettlement: number | null
  unpaid: number | null
  /** 추가증거금이 왜 생겼는지. 값이 0 이면 이 자리도 비어 옵니다. */
  marginCallReason: string | null
}

export interface OverseasDeposit {
  date: string | null
  currency: string | null
  /** 그 통화의 소수 자릿수. 없으면 화면이 정하지 않습니다. */
  decimals: number | null
  rate: number | null
  conversionCode: string | null
  /** `by-currency` 면 통화별, `converted` 면 환산입니다. **서버가 환산합니다.** */
  conversion?: string
  /** 네 칸을 다 가진 줄 둘(개시예탁·예탁). */
  groups: DepositRow[]
  /** 총액 하나뿐인 줄 스물일곱. */
  items: DepositItem[]
}

export type DepositMarket = 'domestic' | 'overseas'

/** 해외 금액을 어떤 통화로 볼지. **통화별**이면 고른 통화의 금액 그대로,
 *  **원화 환산**이면 서버가 원화로 합친 금액입니다. 국내에는 이 구분이 없습니다. */
export type OverseasView = { mode: 'by-currency'; currency: string } | { mode: 'converted' }

/** 보기를 담는 칸의 이름. 원화 환산과 보기를 안 준 자리는 **같은 칸**입니다 —
 *  보기를 모르는 자리(홈 카드)는 지금까지처럼 원화 환산을 읽습니다. */
function depositKey(market: DepositMarket, view?: OverseasView): string {
  if (market === 'domestic' || !view || view.mode === 'converted') return market
  return `${market}:${view.currency}`
}

/** 다시 불러 볼 만한 실패인지. 거절은 눌러도 같은 답이 옵니다. */
export type DepositFailure = 'retry' | 'rejected'

export interface DepositEntry {
  /** `idle` 은 **아직 안 불렀다**는 뜻입니다. 값이 없는 것과 다릅니다. */
  status: 'idle' | 'loading' | 'ready' | 'failed'
  value: DomesticDeposit | OverseasDeposit | null
  failure: DepositFailure | null
  /** 이 값이 어느 환경의 답인지. 응답이 말한 것이고, 안 실려 왔으면 `null` 입니다. */
  environment: Environment | null
  /** 이 값을 받은 시각(`HH:MM`). **값이 언제 것인지**를 화면이 적는 데 씁니다 —
   *  계좌 조회는 저절로 다시 받지 않아, 보고 있는 수가 방금 것인지 아침 것인지
   *  화면이 말하지 않으면 알 길이 없습니다. 받은 적이 없으면 `null` 입니다.
   *
   *  **새로 받는 데 실패해도 그대로 둡니다** — 그 시각은 지금 서 있는 값이 언제
   *  것인지를 말하는 것이지 마지막으로 시도한 때가 아닙니다. */
  at: string | null
}

const EMPTY: DepositEntry = {
  status: 'idle',
  value: null,
  failure: null,
  environment: null,
  at: null,
}

/** 지금 한국시각을 `HH:MM` 으로. 값이 언제 것인지를 적는 데만 씁니다 — 초까지 적으면
 *  눈이 그 숫자를 좇습니다(시세 저장소와 같은 꼴입니다). */
function stamp(): string {
  return kstClock(Date.now())
}

/** 받은 예수금. 열쇠는 **(시장, 보기)**입니다(`depositKey`) — 보기를 바꾸면 새 칸을
 *  읽으므로, 앞 보기의 숫자가 새 보기 머리 아래 서지 않습니다. 늦게 온 앞 보기의
 *  답도 제 칸에만 들어갑니다. */
const entries = new Map<string, DepositEntry>()
const listeners = new Set<() => void>()

function announce(key: string, next: DepositEntry): void {
  entries.set(key, next)
  for (const listener of listeners) listener()
}

export function depositEntry(market: DepositMarket, view?: OverseasView): DepositEntry {
  return entries.get(depositKey(market, view)) ?? EMPTY
}

export function subscribeAccount(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** 지금 나가 있는 물음과 그것을 낸 세대. 같은 시장을 두 곳에서 동시에 부르면(홈
 *  카드와 계좌 탭) 한 번만 나가게 합니다.
 *
 *  **세대를 함께 적는 까닭**: 환경이 바뀌면 옛 세대의 물음은 더 이상 이 자리를
 *  막지 않아야 합니다 — 막으면 새 환경의 첫 조회가 「이미 나가 있다」로 건너뛰고,
 *  옛 답은 버려져 그 시장이 「아직 조회하지 않았다」에 갇힙니다. */
const flying = new Map<string, number>()

const PATH: Record<DepositMarket, string> = {
  domestic: '/api/domestic/deposit',
  overseas: '/api/overseas/deposit',
}

/** 예수금을 받아 옵니다.
 *
 *  **영업일자를 안 보냅니다.** 비우면 백엔드가 오늘로 채웁니다 — 「오늘이
 *  며칠인가」는 화면과 백엔드가 서로 다른 시계를 볼 수 있는 자리라, 화면이
 *  정하면 자정 근처에서 둘이 다른 날을 묻게 됩니다.
 *
 *  **해외 원화 환산은 통화와 환산 구분을 안 보냅니다.** 백엔드 기본값(원화·환산)을
 *  그대로 씁니다. 환산은 서버가 합니다. 통화별이면 그 통화와 「개별」(`cvs_div` 1)을
 *  보냅니다 — 구분 값은 라우트가 글자로 받습니다.
 */
export async function loadDeposit(market: DepositMarket, view?: OverseasView): Promise<void> {
  const key = depositKey(market, view)
  /* 어느 환경에서 물었는지 적어 둡니다. 답이 왔을 때 환경이 바뀌어 있으면 그 답은
     다른 계좌의 값이라 버립니다. */
  const since = generation()
  if (flying.get(key) === since) return
  flying.set(key, since)

  const held = entries.get(key) ?? EMPTY
  const hadValue = held.value != null
  /* **값이 있으면 뼈대로 되돌리지 않습니다.** 다시 부르는 동안에도 앞 값이
     서 있어야, 나갔다 돌아온 화면이 「없다」고 말하지 않습니다. */
  announce(key, { ...held, status: hadValue ? 'ready' : 'loading', failure: null })

  const body =
    view?.mode === 'by-currency' && market === 'overseas'
      ? JSON.stringify({ cur_cd: view.currency, cvs_div: '1' })
      : '{}'
  try {
    const response = await fetch(PATH[market], {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
    })
    /* 그 사이 환경이 바뀌었으면 이 자리는 이미 비워졌고 새 물음이 채웁니다 —
       손대지 않습니다. 같은 환경인데 답이 다른 환경의 것이면 버리고 「아직 안
       불렀다」로 되돌립니다. */
    if (since !== generation()) return
    if (!accepts(response, since)) {
      discardDeposit(key)
      return
    }
    if (!response.ok) {
      /* 거절(502)은 다시 눌러도 같은 답이 옵니다. 나머지는 다시 불러 볼
         만합니다 — 어느 쪽인지로 「다시」 단추가 서고 안 서고가 갈립니다. */
      const failure: DepositFailure = response.status === 502 ? 'rejected' : 'retry'
      /* 앞 값이 있으면 지우지 않습니다. 새로 받는 데 실패했다고 이미 받아 둔
         값이 틀린 것은 아닙니다. */
      announce(key, { ...held, status: hadValue ? 'ready' : 'failed', failure })
      return
    }
    const value = depositOf(market, await response.json())
    announce(key, {
      status: 'ready',
      value,
      failure: null,
      environment: environmentOf(response),
      at: stamp(),
    })
  } catch {
    if (since !== generation()) return
    announce(key, { ...held, status: hadValue ? 'ready' : 'failed', failure: 'retry' })
  } finally {
    /* 제 물음일 때만 지웁니다. 옛 세대의 답이 늦게 와서 새 물음의 표시를 지우면
       같은 조회가 한 번 더 나갈 수 있습니다. */
    if (flying.get(key) === since) flying.delete(key)
  }
}

/** 버린 답의 자리. 그 사이 담긴 값이 있으면 그대로 두고, 없으면 「아직 안 불렀다」로
 *  되돌립니다 — 환경이 정리되면 보는 자리가 다시 부릅니다. 새 얼굴은 없습니다. */
function discardDeposit(key: string): void {
  const now = entries.get(key)
  if (now?.value != null) announce(key, { ...now, status: 'ready' })
  else announce(key, EMPTY)
}

export function retryDeposit(market: DepositMarket, view?: OverseasView): void {
  void loadDeposit(market, view)
}

/** 값을 읽기만 합니다. **부르지 않습니다** — 부르는 자리를 화면이 정하게 합니다. */
export function useDeposit(market: DepositMarket, view?: OverseasView): DepositEntry {
  const key = depositKey(market, view)
  return useSyncExternalStore(
    subscribeAccount,
    () => entries.get(key) ?? EMPTY,
    () => EMPTY,
  )
}

/** 화면이 열릴 때 한 번 부르고, 그 뒤로는 읽기만 합니다.
 *
 *  **환경을 아직 모르면 기다립니다.** 알게 되면 그때 한 번 부릅니다 — 모르는 채로
 *  부르고 알게 된 뒤 또 부르면 같은 값을 두 번 받습니다. 담긴 값이 지워져
 *  「안 불렀다」로 돌아가면(환경이 바뀜) 다시 부릅니다. */
export function useDepositOnce(market: DepositMarket, view?: OverseasView): DepositEntry {
  const entry = useDeposit(market, view)
  const settled = useEnvironmentSettled()
  const idle = entry.status === 'idle'
  const key = depositKey(market, view)
  /* 그 시장의 인증 정보가 없으면 부르지 않습니다 — 목록(`useListOnce`)과 같은
     까닭입니다. 자리는 「안 불렀다」로 남습니다. */
  const credentialed = useMarketCredentialed(market)
  useEffect(() => {
    if (settled && credentialed) void loadDeposit(market, view)
    // 보기는 칸 이름(key)으로 봅니다 — 보기 객체는 그릴 때마다 새것입니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, settled, idle, credentialed])
  /* 환경을 기다리는 동안은 이 자리도 「받는 중」입니다 — 환경 읽기가 끝나면 바로
     부르므로 「아직 조회하지 않았다」가 아닙니다. */
  return idle && !settled ? WAITING : entry
}

/** 환경 읽기를 기다리는 자리의 얼굴. 값이 없는 「받는 중」입니다. */
const WAITING: DepositEntry = { ...EMPTY, status: 'loading' }

/** 값을 담는 자리가 조회를 내도 되는 때인지. 환경을 아는 상태와, 서버도 모른다고
 *  답한 상태에서만 냅니다 — 뒤는 서버가 제 환경으로 답하는 참값이고, 배지가
 *  모른다고 말하며 주문은 막혀 있어 값이 서도 거짓이 아닙니다.
 *
 *  **설정도 한 번은 읽고 나서 냅니다.** 환경을 먼저 알고 설정이 늦게 오면, 인증
 *  정보가 빈 시장을 「아직 모름」으로 보고 불러 오류만 남깁니다. */
function useEnvironmentSettled(): boolean {
  const { status, configRead } = useEnvironment()
  return (status === 'ready' || status === 'failed') && configRead
}

/** 그 시장에 인증 정보가 찼는지. 설정이나 접속 환경을 아직 모르면 막지 않습니다
 *  (`true`) — 모르는 것을 「없다」고 하지 않습니다. */
export function useMarketCredentialed(market: DepositMarket): boolean {
  const { config } = useEnvironment()
  const configEnv = config?.active_environment ?? null
  return config === null || configEnv === null || marketConfigured(config, configEnv, market)
}

/** 돈을 글자로. **자릿수와 통화는 서버가 말한 그대로** 씁니다 — 통화마다 다르고,
 *  화면이 정하면 받은 값과 보이는 값이 갈립니다.
 *
 *  원화는 우리말 단위로, 나머지는 받은 코드 그대로 답니다. **코드를 모르면
 *  아무것도 안 답니다** — 무슨 돈인지 지어내지 않습니다. */
export function depositMoney(
  value: number,
  decimals: number,
  currency: string | null,
): string {
  /* 빼기 기호는 앱이 쓰는 것과 같은 글자입니다. 하이픈은 숫자 옆에서 짧고
     높이가 달라, 한 화면에서 두 모양의 음수가 섞입니다. */
  const text = Math.abs(value)
    .toLocaleString('ko-KR', {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    })
  const signed = value < 0 ? `${MINUS}${text}` : text
  if (currency === 'KRW') return `${signed}원`
  return currency ? `${signed} ${currency}` : signed
}

/** 받은 예수금 답을 담을 모양으로 맞춥니다. **줄 목록 칸이 빠져 오면 빈 목록으로**
 *  둡니다 — 화면은 그 칸을 목록으로 믿고 읽어, 칸 하나가 빠지면 화면 전체가
 *  멈춥니다. 여기서 한 번 맞추면 읽는 자리 전부가 함께 안전합니다.
 *
 *  **어느 시장의 답인지는 부른 쪽이 압니다.** 두 시장은 `groups` 칸이 있는지로
 *  갈리므로(`isDomesticDeposit`), 해외 답에서 그 칸이 빠지면 국내 답으로 읽힙니다.
 *  부른 시장에 맞춰 칸을 채워 그 갈림도 지킵니다.
 *
 *  줄 안의 네 칸(`values`)이 빠지거나 모자란 줄은 **빈 값으로 네 칸**을
 *  채웁니다. 빈 목록이면 그 줄만 칸 없이 그려져 표의 열이 어긋납니다 — 빈 값은
 *  「이 자리에 값이 없다」는 뜻 그대로 「—」로 섭니다.
 *
 *  칸이 빠진 답은 실제 서버에서 본 적이 없고 시험용 답에서만 보였습니다. */
function depositOf(market: DepositMarket, raw: unknown): DomesticDeposit | OverseasDeposit {
  const body = (raw ?? {}) as Record<string, unknown>
  const list = <T,>(value: unknown): T[] => (Array.isArray(value) ? (value as T[]) : [])
  /* 네 칸보다 모자라면 뒤를 빈 값으로 채웁니다. 넘치면 그대로 둡니다. */
  const rows = (value: unknown): DepositRow[] =>
    list<DepositRow>(value).map((row) => {
      const values: (number | null)[] = Array.isArray(row.values) ? [...row.values] : []
      while (values.length < 4) values.push(null)
      return { ...row, values }
    })
  if (market === 'domestic') {
    return { ...(body as unknown as DomesticDeposit), items: rows(body.items) }
  }
  return {
    ...(body as unknown as OverseasDeposit),
    groups: rows(body.groups),
    items: list<DepositItem>(body.items),
  }
}

/** 국내 응답인지. 두 시장이 한 자리에 담겨 있어 화면이 이것으로 가릅니다. */
export function isDomesticDeposit(
  value: DomesticDeposit | OverseasDeposit | null,
): value is DomesticDeposit {
  return value !== null && !('groups' in value)
}

/* ── 목록: 잔고 · 주문내역/미체결 · 주문오류 · 누적손익 ──────
 *
 * **서버가 낸 모양 그대로 담습니다.** 이름을 마스터에서 찾거나 손익률을 셈하는
 * 것은 화면이 그릴 때 합니다 — 여기서 미리 채우면 「서버가 준 것」과 「우리가
 * 채운 것」이 한 덩어리가 되어, 값이 이상할 때 어느 쪽인지 못 가립니다.
 */

/** 서버가 낸 보유 포지션 한 줄. **시장마다 오는 칸이 다릅니다** — 국내는
 *  이름과 수익률이 오고 만기가 없으며, 해외는 만기·통화가 오고 이름과
 *  수익률이 없습니다. */
export interface ServerPosition {
  code: string
  /** 국내만 옵니다. 해외는 응답에 칸이 없어 마스터에서 찾습니다. */
  name?: string
  market?: string
  side?: string
  sideCode?: string
  quantity?: number | null
  closableQuantity?: number | null
  avgPrice?: number | null
  /** **국내는 종가, 해외는 현재가입니다.** 장중에 뜻이 다릅니다. */
  lastPrice?: number | null
  pl?: number | null
  /** 국내만 옵니다. 해외는 화면이 평균가와 현재가로 셈합니다. */
  plPct?: number | null
  expiry?: string | null
  currency?: string | null
  rate?: number | null
  multiplier?: number | null
  productKind?: string
}

/** 해외 보유포지션 만기 조회의 한 줄. **체결 단위**라 한 종목이 여러 줄일 수
 *  있습니다. 날짜는 `YYYY-MM-DD` 이고, 없거나 날짜가 아니면 `null` 입니다. */
export interface ServerExpiryPosition {
  code?: string | null
  side?: string | null
  /** 인수도결제구분명 — 서버가 받은 글자 그대로(「현금」 등). */
  delivery?: string | null
  firstNotice?: string | null
  expiry?: string | null
}

/** 서버가 낸 주문 한 줄. **미체결도 같은 모양입니다** — 줄에 진행 상태가 함께
 *  들어 있어, 미체결 표와 주문내역 표가 같은 목록을 다르게 읽습니다. */
export interface ServerOrder {
  id: string
  code: string
  /** 국내만 옵니다. */
  name?: string
  /** 선물·옵션·스프레드. 국내 미체결 조회는 스프레드 줄에 `spread` 를 싣습니다.
   *  주지 않는 시장·조회에서는 없고, 화면이 이름을 뜯어 짐작하지 않습니다. */
  productKind?: string
  market?: string
  side?: string
  status?: string
  statusName?: string
  orderKind?: string
  orderType?: string
  quantity?: number | null
  filled?: number | null
  remaining?: number | null
  price?: number | null
  fillPrice?: number | null
  avgFillPrice?: number | null
  stopPrice?: number | null
  time?: string | null
  source?: string
  sourceCode?: string
  /** **우리 프로그램으로 낸 주문만 참입니다.** 거짓이면 이 화면에서 고칠 수
   *  없습니다 — 다른 매체에서 낸 주문입니다. */
  editable?: boolean
  currency?: string
}

/** 서버가 낸 주문오류 한 줄.
 *
 *  **두 시장이 주는 칸이 다릅니다.** 국내는 종목명이 오고 **주문번호도 시장도
 *  없습니다**(응답에 칸 자체가 없습니다). 해외는 주문번호와 시장이 오고
 *  종목명이 없습니다. */
export interface ServerOrderError {
  code: string
  name?: string
  market?: string
  message: string
  messageCode?: string
  time?: string | null
  orderNo?: string
  originalOrderNo?: string
  side?: string
  quantity?: number | null
  price?: number | null
  /** 해외 줄의 열쇠 둘(주문일자·일련번호). 기간 답에서 겹친 줄을 가르는 데 씁니다. */
  id?: string
  orderDate?: string | null
  /** 그 줄의 날짜(`YYYY-MM-DD`). **기간으로 물었을 때만** 옵니다 — 하루 조회에는
   *  국내 줄에 날짜 칸이 없어, 기간 답은 서버가 물은 날을 붙여 줍니다. */
  date?: string | null
}

/** 주문오류 기간 답에서 못 받은 날 하나. */
export interface FailedDay {
  /** `YYYY-MM-DD`. */
  date: string
  reason: string
}

/** 기간 답이 함께 낸 못 받은 날들. 모양이 틀리면 빈 목록입니다. */
export function failedDaysOf(extra: Record<string, unknown> | null): FailedDay[] {
  const raw = extra?.failedDays
  if (!Array.isArray(raw)) return []
  return raw.flatMap((one) => {
    const row = one as { date?: unknown; reason?: unknown }
    return typeof row.date === 'string' ? [{ date: row.date, reason: typeof row.reason === 'string' ? row.reason : '' }] : []
  })
}

/** 누적손익 한 줄. 줄 하나가 **품목 × 통화**입니다.
 *
 *  **총합은 목록에 안 들어 있습니다** — 서버가 빼서 따로 내므로 화면이 다시
 *  더하지 않습니다. 총합 줄은 `extra.total` 에 같은 모양으로 옵니다. */
export interface ServerRealized {
  market?: string
  productCode?: string | null
  productName?: string | null
  currency?: string | null
  /** 선물은 청산손익입니다. */
  realisedPl?: number | null
  unrealisedPl?: number | null
  fee?: number | null
  netPl?: number | null
}

/** 조회 기간. **서버가 받는 모양 그대로** `YYYYMMDD` 입니다 — 화면 글자를
 *  여기서 다듬으면 보내는 값과 담는 열쇠가 갈립니다. 누적손익만 씁니다. */
export interface Period {
  from: string
  to: string
}

/** 무엇을 담는 자리인지. `expiry` 는 **해외만** 있는 보유포지션 만기 조회입니다 —
 *  잔고에 없는 최초통보일이 여기 옵니다. */
export type ListKind = 'positions' | 'orders' | 'errors' | 'cumulative' | 'expiry'

/** 주문 목록을 어느 쪽으로 물어볼지. **두 시장의 코드 체계가 달라** 화면 낱말로
 *  두고 부를 때 각자의 값으로 바꿉니다. */
export type OrderScope = 'all' | 'open'

/** 국내 `exec_div` — 0 전체 · 1 체결 · 2 미체결 · 3 미접수. */
const DOMESTIC_SCOPE: Record<OrderScope, string> = { all: '0', open: '2' }
/** 해외 `inq_div` — 0 전체 · 1 주문 · 2 체결 · 3 미체결 · 4 미체결(지정청산). */
const OVERSEAS_SCOPE: Record<OrderScope, string> = { all: '0', open: '3' }

export interface ListEntry<T> {
  status: 'idle' | 'loading' | 'ready' | 'failed'
  /** 이 줄들이 어느 환경의 답인지. 응답이 말한 것이고, 안 실려 왔으면 `null` 입니다. */
  environment: Environment | null
  /** **`null` 은 「받은 적 없다」, 빈 배열은 「받았는데 줄이 없다」입니다.**
   *  실패는 `null` 을 그대로 둡니다 — 그래야 빈 목록이 「오늘 낸 주문이
   *  없습니다」가 되지 않습니다. 실패에 「없다」고 말하면 **있는 포지션을
   *  없다고** 말하는 화면이 됩니다. */
  rows: T[] | null
  /** 서버가 함께 낸 값. 누적손익의 총합, 주문오류의 건수가 여기 옵니다.
   *  **첫 쪽의 답**입니다 — 이어 받은 쪽의 값으로 덮지 않습니다. */
  extra: Record<string, unknown> | null
  failure: DepositFailure | null
  /** 다음 쪽을 물을 열쇠. 더 받을 것이 없으면 `null` 입니다. 멈췄을 때 「더
   *  받기」가 이 열쇠로 이어 묻습니다. */
  nextKey: string | null
  /** 다음 쪽을 받고 있나. */
  filling: boolean
  /** 받다가 멈췄나 — 사용자가 멈췄거나, 한 번에 받는 쪽 수를 다 썼거나, 다음
   *  쪽을 못 받았습니다. **더 있을 수도, 마지막 쪽이었을 수도 있습니다** — 그
   *  순간에는 가릴 수 없습니다. */
  capped: boolean
  /** 못 받은 날을 다시 받는 중이면 몇 날 중 몇 날째인가. 주문오류 기간 목록만 씁니다. */
  retrying?: { done: number; total: number } | null
  /** 그 시장의 인증 정보가 없어 **부르지 않은** 자리인지. 받는 중도 못 받은 것도
   *  아니라서 그리는 쪽이 「조회 전」으로 세웁니다. */
  withheld?: boolean
  /** 받아 둔 줄을 그대로 둔 채 **새로 받고 있나.** 줄이 있으면 상태는 `ready`
   *  그대로라, 머리 줄이 「받는 중」을 말하고 「다시 받기」를 잠그는 데 이것을
   *  봅니다. */
  refreshing?: boolean
}

const EMPTY_LIST: ListEntry<never> = {
  status: 'idle',
  environment: null,
  rows: null,
  extra: null,
  failure: null,
  nextKey: null,
  filling: false,
  capped: false,
}

const lists = new Map<string, ListEntry<unknown>>()
/** 나가 있는 목록 물음과 그 세대. 예수금의 `flying` 과 같은 까닭입니다. */
const flyingLists = new Map<string, number>()
/** 물어본 적 있는 자리와 그 물음. 끊겼다 붙은 뒤 다시 부를 자리를 여기서 찾습니다. */
const asked = new Map<string, ListArgs>()
/** 답이 오면 한 번 더 물을 자리. 나가 있는 동안 「다시 불러야 한다」가 된
 *  자리입니다 — 나가 있는 답은 물은 시각의 것이라 그 뒤의 변화를 모릅니다. */
const reask = new Set<string>()
/** 주문 목록 물음이 나가 있는 동안 온 실시간 알림. 답 위에 다시 붙입니다
 *  (`applyOrderEvents`). */
const flownEvents = new Map<string, OrderEvent[]>()

interface ListArgs {
  market: DepositMarket
  kind: ListKind
  scope?: OrderScope
  period?: Period
  /** 누적손익의 환산 통화. 없으면 보내지 않습니다(라우트 기본 원화). */
  conversion?: string
}

/** 담는 열쇠. **조회구분까지 넣습니다** — 안 넣으면 미체결 탭이 받아 둔 것을
 *  주문체결상세가 「이미 물어봤다」로 건너뜁니다. */
function listKey(
  market: DepositMarket,
  kind: ListKind,
  scope?: OrderScope,
  period?: Period,
  conversion?: string,
): string {
  const span = period ? `${period.from}~${period.to}` : ''
  /* 환산 통화가 다르면 다른 금액이라 칸도 다릅니다. 안 보낸 자리는 끝을 안 붙여
     지금까지의 열쇠 그대로입니다. */
  const tail = conversion ? `:${conversion}` : ''
  return `${market}:${kind}:${scope ?? ''}:${span}${tail}`
}

function listEntry<T>(key: string): ListEntry<T> {
  return (lists.get(key) as ListEntry<T> | undefined) ?? (EMPTY_LIST as ListEntry<T>)
}

function announceList(key: string, next: ListEntry<unknown>): void {
  lists.set(key, next)
  for (const listener of listeners) listener()
}

function listPath(market: DepositMarket, kind: ListKind): string {
  const base = `/api/${market}`
  if (kind === 'positions') return `${base}/open-interest`
  if (kind === 'orders') return `${base}/order-history`
  if (kind === 'errors') return `${base}/order-error`
  if (kind === 'expiry') return `${base}/open-interest-expiry`
  return `${base}/cumulative-pl`
}

function listBody(
  market: DepositMarket,
  kind: ListKind,
  scope?: OrderScope,
  period?: Period,
  conversion?: string,
): string {
  if (kind === 'orders') {
    const table = market === 'domestic' ? DOMESTIC_SCOPE : OVERSEAS_SCOPE
    const field = market === 'domestic' ? 'exec_div' : 'inq_div'
    return JSON.stringify({ [field]: table[scope ?? 'all'] })
  }
  /* **조회일자도 기간도 화면이 안 만듭니다.** 「오늘이 며칠인가」는 화면과
     서버가 서로 다른 시계를 볼 수 있는 자리라, 비워 보내고 서버가 정하게
     둡니다. 누적손익만 사용자가 기간을 고르므로 그때는 고른 값을 보냅니다. */
  if (kind === 'cumulative' && period) {
    const span = { inq_strt_dt: period.from, inq_ed_dt: period.to }
    return JSON.stringify(conversion ? { ...span, cvs_cur_cd: conversion } : span)
  }
  /* 주문오류는 기간을 고르면 그 기간을, 안 고르면(「오늘」) 지금처럼 빈 본문입니다 —
     서버가 오늘로 정합니다. */
  if (kind === 'errors' && period) {
    return JSON.stringify({ inq_strt_dt: period.from, inq_ed_dt: period.to })
  }
  return '{}'
}

/** 응답에서 줄을 꺼내는 이름. 라우트마다 다릅니다. */
const ROWS_FIELD: Record<ListKind, string> = {
  positions: 'positions',
  orders: 'orders',
  errors: 'errors',
  cumulative: 'rows',
  expiry: 'positions',
}

export async function loadList(
  market: DepositMarket,
  kind: ListKind,
  scope?: OrderScope,
  period?: Period,
  conversion?: string,
): Promise<void> {
  const key = listKey(market, kind, scope, period, conversion)
  const since = generation()
  if (flyingLists.get(key) === since) return
  flyingLists.set(key, since)
  asked.set(key, { market, kind, scope, period, conversion })
  flownEvents.delete(key)
  /* 첫 쪽부터 다시 받으면 **이어 받던 것은 끊습니다.** 새 첫 쪽 뒤에 옛 목록의
     다음 쪽이 붙으면 같은 줄이 두 번 서거나 사이가 빕니다. */
  cancelFill(key)

  const held = lists.get(key) ?? EMPTY_LIST
  const hadRows = held.rows != null
  announceList(key, {
    ...held,
    status: hadRows ? 'ready' : 'loading',
    failure: null,
    filling: false,
    refreshing: hadRows,
  })

  try {
    const response = await fetch(listPath(market, kind), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: listBody(market, kind, scope, period, conversion),
    })
    if (since !== generation()) return
    if (!accepts(response, since)) {
      discardList(key)
      return
    }
    if (!response.ok) {
      announceList(key, {
        ...held,
        status: hadRows ? 'ready' : 'failed',
        failure: response.status === 502 ? 'rejected' : 'retry',
        refreshing: false,
      })
      return
    }
    const body = (await response.json()) as Record<string, unknown>
    const rows = body[ROWS_FIELD[kind]]
    const answered: unknown[] = Array.isArray(rows) ? rows : []
    /* 물어보고 있는 동안 온 알림은 이 답보다 새 것입니다 — 답은 물은 시각의
       목록이라 그 뒤의 접수·체결을 모릅니다. 답 위에 다시 붙입니다. */
    const flown = flownEvents.get(key)
    /* 우리가 방금 낸 주문의 접수 줄도 답 위에 다시 붙입니다 — 답에 그 주문이
       실려 왔으면 그 줄이 이기고(서버가 아는 값이 낫습니다) 여기서 빠집니다. */
    const mine =
      kind === 'orders' && (scope ?? 'all') === 'all'
        ? settleAccepted(market, answered as ServerOrder[])
        : []
    const layered = [...(flown ?? []), ...mine]
    /* **누적손익은 이어 받지 않습니다.** 그 답의 총합(`extra`)은 첫 쪽의 합계라,
       뒤 쪽의 줄을 붙이면 표와 총합이 어긋납니다. 열쇠도 담지 않아 「더 받기」가
       서지 않게 합니다. */
    const next = kind === 'cumulative' ? null : nextKeyOf(body)
    announceList(key, {
      status: 'ready',
      environment: environmentOf(response),
      rows: layered.length > 0 ? mergeOrderEvents(answered as ServerOrder[], layered) : answered,
      extra: body,
      failure: null,
      nextKey: next,
      filling: next !== null,
      capped: false,
      refreshing: false,
    })
    /* 더 있으면 **표를 먼저 세우고** 다음 쪽을 이어 받습니다. 두세 쪽이면
       끝나는 일이라 사람에게 단추를 미루지 않습니다. */
    if (next !== null) void fillList(key, { market, kind, scope, period, conversion }, next)
  } catch {
    if (since !== generation()) return
    announceList(key, { ...held, status: hadRows ? 'ready' : 'failed', failure: 'retry', refreshing: false })
  } finally {
    if (flyingLists.get(key) === since) {
      flyingLists.delete(key)
      flownEvents.delete(key)
      if (reask.delete(key)) void loadList(market, kind, scope, period, conversion)
    }
  }
}

/* ── 주문오류 기간: 못 받은 날 다시 받기 ─────────────────────
 *
 * 기간 답에 못 받은 날이 있으면 **그 날만** 하루 조회로 다시 묻고, 받은 줄을 같은
 * 기간 목록에 합칩니다. 날짜·겹침·차례는 서버가 기간 답을 지을 때와 같은 규칙입니다
 * — 두 길이 다른 규칙으로 합치면 같은 기간이 부른 길마다 다른 목록이 됩니다. */

/** 한 번 다시 받을 때 한 날에서 넘기는 쪽 수의 상한. */
const RETRY_PAGES = 10

/** 하루의 주문오류를 쪽 끝까지 받습니다. 못 받으면 `null`. */
async function askErrorDay(market: DepositMarket, day: string, since: number): Promise<ServerOrderError[] | null> {
  const rows: ServerOrderError[] = []
  let cursor: string | null = null
  for (let page = 0; page < RETRY_PAGES; page += 1) {
    const body: Record<string, string> = { inq_dt: day.replace(/-/g, '') }
    if (cursor) body.nxt_key = cursor
    const response = await fetch(listPath(market, 'errors'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (since !== generation() || !accepts(response, since) || !response.ok) return null
    const said = (await response.json()) as Record<string, unknown>
    const got = Array.isArray(said.errors) ? (said.errors as ServerOrderError[]) : []
    /* 줄의 날짜는 **해외는 줄의 주문일자, 없으면 물은 날**, 국내는 물은 날입니다
       (서버 기간 답의 `date_of` 와 같습니다). */
    rows.push(...got.map((one) => ({ ...one, date: (market === 'overseas' && one.orderDate) || day })))
    cursor = nextKeyOf(said)
    if (cursor === null) break
    await new Promise((done) => setTimeout(done, FILL_GAP))
  }
  return rows
}

/** 받은 줄을 합칩니다. 해외는 (주문일자, 일련번호)가 같은 줄을 한 번만 둡니다 —
 *  서버 기간 답의 `key_of` 와 같은 열쇠입니다. 국내는 가를 열쇠가 없어 거르지
 *  않습니다. 차례는 (날짜, 시각) 최신 먼저입니다. */
function mergeErrorRows(held: ServerOrderError[], got: ServerOrderError[], market: DepositMarket): ServerOrderError[] {
  const keyOf = (one: ServerOrderError) =>
    market === 'overseas' && one.orderDate && one.id ? `${one.orderDate}|${one.id}` : null
  const seen = new Set(held.map(keyOf).filter((key): key is string => key !== null))
  const added = got.filter((one) => {
    const key = keyOf(one)
    if (key === null) return true
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
  const order = (one: ServerOrderError) => `${one.date ?? ''} ${one.time ?? ''}`
  return [...held, ...added].sort((a, b) => (order(a) < order(b) ? 1 : order(a) > order(b) ? -1 : 0))
}

/** 다시 받기의 세대. 목록 하나에 하나이고, 멈추면 올라갑니다. */
const retryGen = new Map<string, number>()

/** 기간 목록의 못 받은 날을 다시 받습니다. 날마다 받은 줄을 바로 붙이고, 받은
 *  날은 못 받은 날에서 뺍니다. **그 사이 이 목록이 새로 불렸거나, 기간을 바꿔
 *  멈췄거나, 환경이 바뀌면** 남은 일과 늦게 온 답을 버립니다 — 다른 물음의 답
 *  위에 옛 물음의 줄을 붙이게 됩니다. */
export async function retryErrorDays(market: DepositMarket, period: Period): Promise<void> {
  const key = listKey(market, 'errors', undefined, period)
  const start = lists.get(key)
  if (!start || start.rows === null || start.retrying) return
  const failed = failedDaysOf(start.extra)
  if (failed.length === 0) return
  const since = generation()
  const mine = (retryGen.get(key) ?? 0) + 1
  retryGen.set(key, mine)
  const alive = () => lists.get(key) === current && since === generation() && retryGen.get(key) === mine
  let rows = [...start.rows] as ServerOrderError[]
  const still: FailedDay[] = []
  let current: ListEntry<unknown> = { ...start, retrying: { done: 0, total: failed.length } }
  announceList(key, current)
  for (let index = 0; index < failed.length; index += 1) {
    if (index > 0) await new Promise((done) => setTimeout(done, FILL_GAP))
    if (!alive()) return
    let got: ServerOrderError[] | null
    try {
      got = await askErrorDay(market, failed[index].date, since)
    } catch {
      got = null
    }
    if (!alive()) return
    if (got === null) still.push(failed[index])
    else rows = mergeErrorRows(rows, got, market)
    current = {
      ...current,
      rows,
      extra: { ...(current.extra ?? {}), failedDays: [...still, ...failed.slice(index + 1)] },
      retrying: index + 1 < failed.length ? { done: index + 1, total: failed.length } : null,
    }
    announceList(key, current)
  }
}

/** 다시 받기를 멈춥니다. 받아 붙인 날은 그대로 남고, 받는 중 표시는 걷힙니다. */
export function stopErrorDays(market: DepositMarket, period: Period): void {
  const key = listKey(market, 'errors', undefined, period)
  retryGen.set(key, (retryGen.get(key) ?? 0) + 1)
  const held = lists.get(key)
  if (held?.retrying) announceList(key, { ...held, retrying: null })
}

/** 부르되, 같은 물음이 나가 있으면 **답이 온 뒤 한 번 더** 부릅니다. 나가 있는
 *  답은 물은 시각의 것이라, 그 뒤에 생긴 「다시 불러야 할 까닭」을 모릅니다. */
function requestList(args: ListArgs): void {
  const { market, kind, scope, period, conversion } = args
  const key = listKey(market, kind, scope, period, conversion)
  if (flyingLists.get(key) === generation()) {
    reask.add(key)
  } else {
    void loadList(market, kind, scope, period, conversion)
  }
}

/** 버린 답의 자리. 예수금과 같은 규칙입니다. */
function discardList(key: string): void {
  const now = lists.get(key)
  if (now?.rows != null) announceList(key, { ...now, status: 'ready', refreshing: false })
  else announceList(key, EMPTY_LIST)
}

export function retryList(
  market: DepositMarket,
  kind: ListKind,
  scope?: OrderScope,
  period?: Period,
  conversion?: string,
): void {
  void loadList(market, kind, scope, period, conversion)
}

/* ── 이어 받기 ────────────────────────────────────────
 *
 * 서버는 목록을 쪽으로 나눠 주고, 다음 쪽을 물을 열쇠(`nextKey`)를 함께 냅니다.
 * 첫 쪽이 오면 표를 세우고 나머지 쪽을 뒤에서 이어 받습니다.
 *
 * 미확인: 열쇠가 찬 답을 실제 서버에서 본 적이 없고, 한 쪽에 몇 줄이 오는지도
 * 모릅니다. 이어 물을 때 첫 물음의 조회 조건을 함께 보내야 하는지도 모르므로
 * **같은 조건에 열쇠만 더해** 보냅니다. */

/** 뒤에서 이어 묻는 조회의 간격(ms). **초에 두 번**입니다 — 계좌 조회 한도는
 *  초에 열 번인데 잔고·미체결·주문오류·예수금이 같은 한도를 나눠 씁니다. 다
 *  쓰면 보고 있는 탭이 밀립니다. 목록의 다음 쪽과 추이 탭의 빠진 날이 같이
 *  씁니다. */
export const FILL_GAP = 500

/** 한 번에 이어 받는 쪽 수. 다 쓰면 멈추고 「더 받기」를 세웁니다 — 끝없이
 *  받으면 그동안 다른 조회가 한도에 밀립니다. **멈춘 것을 조용히 넘기지 않습니다.**
 *
 *  열 쪽이면 한 표에 대략 열 번 × (조회 + 0.5초)라 수 초 안에 끝납니다. 한 쪽에
 *  몇 줄이 오는지는 아직 모르므로 줄 수가 아니라 쪽 수로 셉니다. */
const FILL_PAGES = 10

/** 목록마다 이어 받기의 세대. **목록 하나에 하나**입니다 — 한 표의 「멈추기」가
 *  다른 표의 이어 받기를 끊으면 안 됩니다. */
const fillGen = new Map<string, number>()

/** 모든 목록의 다음 쪽이 한 줄로 서는 사슬. 여러 표가 한꺼번에 물으면 계좌
 *  조회 한도를 한 번에 다 씁니다. */
let fillChain: Promise<unknown> = Promise.resolve()

function cancelFill(key: string): number {
  const next = (fillGen.get(key) ?? 0) + 1
  fillGen.set(key, next)
  return next
}

/** 답에서 다음 쪽 열쇠를 꺼냅니다. 빈 값이면 마지막 쪽입니다. 끝을 따로 알리는
 *  칸(`hasMore`)이 오는 답은 그 칸이 거짓일 때도 마지막 쪽입니다. */
function nextKeyOf(body: Record<string, unknown>): string | null {
  if (body.hasMore === false) return null
  const raw = typeof body.nextKey === 'string' ? body.nextKey.trim() : ''
  return raw === '' ? null : raw
}

/** 이어 받은 쪽에서 **이미 목록에 선 주문**을 걷어 냅니다.
 *
 *  주문 목록의 첫 쪽에는 실시간 알림과 방금 낸 주문이 얹히고, 이어 받는 동안에도
 *  알림이 줄을 갈아 끼웁니다. 그 주문이 다음 쪽에 다시 실려 오면 한 주문이 두
 *  줄이 되므로, 주문번호가 같은 줄은 먼저 선 것을 둡니다.
 *
 *  잔고와 주문오류에는 얹히는 줄이 없어 서버의 쪽끼리만 이어지므로 걷지
 *  않습니다 — 국내 주문오류에는 가를 번호도 없습니다. */
function unseen(kind: ListKind, held: readonly unknown[], answered: readonly unknown[]): unknown[] {
  if (kind !== 'orders') return [...answered]
  const ids = new Set((held as ServerOrder[]).map((row) => row.id).filter(Boolean))
  return (answered as ServerOrder[]).filter((row) => !row.id || !ids.has(row.id))
}

/** 다음 쪽들을 받아 목록 뒤에 붙입니다. **서버가 준 차례 그대로** 붙이고 다시
 *  정렬하지 않습니다 — 받는 동안 줄이 자리를 옮기면 읽던 자리를 잃습니다. */
async function fillList(key: string, args: ListArgs, start: string): Promise<void> {
  const { market, kind, scope, period, conversion } = args
  const mine = fillGen.get(key) ?? 0
  const since = generation()
  const stale = () => fillGen.get(key) !== mine || generation() !== since
  const stop = (patch: Partial<ListEntry<unknown>>) => {
    if (stale()) return
    const now = lists.get(key)
    if (now) announceList(key, { ...now, filling: false, ...patch })
  }
  let cursor = start
  for (let page = 0; page < FILL_PAGES; page++) {
    const turn = fillChain.then(async () => {
      await new Promise((done) => setTimeout(done, FILL_GAP))
      if (stale()) return null
      const body = { ...JSON.parse(listBody(market, kind, scope, period, conversion)), nxt_key: cursor }
      return fetch(listPath(market, kind), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
    })
    fillChain = turn.catch(() => undefined)
    let answer: Record<string, unknown>
    try {
      const response = await turn
      if (response === null || stale()) return
      /* 다른 환경의 답이면 버리고 받기를 내립니다 — 받는 중 표시만 남으면
         「멈추기」가 할 일 없이 섭니다. */
      if (!accepts(response, since)) return stop({})
      /* 이어 받다 못 받으면 **받은 줄은 두고** 멈춥니다. 남은 열쇠로 「더 받기」가
         이어 묻습니다. */
      if (!response.ok) return stop({ capped: true })
      answer = (await response.json()) as Record<string, unknown>
    } catch {
      return stop({ capped: true })
    }
    if (stale()) return
    const rows = answer[ROWS_FIELD[kind]]
    const answered: unknown[] = Array.isArray(rows) ? rows : []
    const now = lists.get(key)
    if (!now) return
    const held = now.rows ?? []
    const next = nextKeyOf(answer)
    announceList(key, {
      ...now,
      rows: [...held, ...unseen(kind, held, answered)],
      nextKey: next,
      filling: next !== null && next !== cursor,
      /* 서버가 **같은 열쇠를 되풀이하면** 멈춥니다. 그대로 이어 물으면 상한까지
         같은 쪽을 받습니다. 「더 받기」로 사람이 다시 물을 수는 있게 둡니다. */
      capped: next !== null && next === cursor,
    })
    if (next === null || next === cursor) return
    cursor = next
  }
  stop({ capped: true })
}

/** 이어 받기를 멈춥니다. 받은 줄은 그대로 두고, 남은 열쇠로 「더 받기」를 세웁니다. */
export function stopList(
  market: DepositMarket,
  kind: ListKind,
  scope?: OrderScope,
  period?: Period,
  conversion?: string,
): void {
  const key = listKey(market, kind, scope, period, conversion)
  cancelFill(key)
  const now = lists.get(key)
  if (now?.filling) announceList(key, { ...now, filling: false, capped: true })
}

/** 멈춘 자리에서 이어 받습니다. 한 번에 받는 쪽 수는 처음과 같습니다. */
export function moreList(
  market: DepositMarket,
  kind: ListKind,
  scope?: OrderScope,
  period?: Period,
  conversion?: string,
): void {
  const key = listKey(market, kind, scope, period, conversion)
  const now = lists.get(key)
  if (!now?.nextKey || now.filling) return
  cancelFill(key)
  announceList(key, { ...now, filling: true, capped: false })
  void fillList(key, { market, kind, scope, period, conversion }, now.nextKey)
}

/* ── 실시간 주문/체결 알림 ────────────────────────────── */

/** 실시간 주문/체결 알림 한 건. **주문내역 줄과 같은 칸 이름**으로 옵니다 —
 *  그래야 조회로 받은 목록 위에 주문번호로 이어 붙일 수 있습니다. 알림에만 있는
 *  칸이 몇 있고(취소수량·오류코드), 조회에만 있는 칸(종목명·평균체결가)은 알림에
 *  없습니다. */
export interface OrderEvent extends ServerOrder {
  statusCode?: string
  cancelled?: number | null
  date?: string | null
  errorCode?: string | null
}

/** 잔고를 바꾼 알림인지. 접수·확인·거절·자동취소는 포지션을 안 건드립니다. */
function isFill(event: OrderEvent): boolean {
  return event.status === 'filled' || event.status === 'partial'
}

/** 목록 위에 알림을 차례로 붙입니다. **주문번호가 같은 줄은 갈아 끼우고, 없으면
 *  맨 위에 세웁니다.** 접수·확인·체결이 건마다 오므로 한 주문이 몇 번이고 갈아
 *  끼워지고, 새 주문은 위에서 시작합니다. 알림이 안 실은 칸은 줄의 값이 남습니다 —
 *  종목명은 조회만 줍니다. 알림의 시장 칸은 계좌 이름이라 줄의 것을 둡니다.
 *
 *  **체결이면 평균체결가는 지웁니다.** 알림의 평균가 칸은 채워져 오지 않아 줄에
 *  남은 평균은 더 이상 이 주문의 값이 아닙니다 — 두면 옛 평균이 새 체결가 위에
 *  섭니다. 표는 그 자리에 체결가격을 세우고, 뒤따르는 조회가 평균을 다시 채웁니다. */
function mergeOrderEvents(rows: readonly ServerOrder[], events: readonly OrderEvent[]): ServerOrder[] {
  let next = [...rows]
  for (const event of events) {
    if (!event.id) continue
    const { market: _market, ...patch } = event
    const at = next.findIndex((row) => row.id === event.id)
    const merged: ServerOrder = at >= 0 ? { ...next[at], ...patch } : { market: event.market, ...patch }
    if (isFill(event)) delete merged.avgFillPrice
    if (at >= 0) next[at] = merged
    else next = [merged, ...next]
  }
  return next
}

/** 이 시장의 주문 목록 위에 실시간 알림을 이어 붙입니다.
 *
 *  **전체 목록에만** 붙입니다. 미체결만 담은 목록(계좌 화면)은 끝난 주문을 빼야
 *  하는 다른 규칙이라, 그 화면이 설 때 다시 조회하는 것으로 둡니다.
 *
 *  **받은 적 없는 자리에는 안 붙입니다** — 이어 붙일 목록이 없고, 그 자리의 첫
 *  조회가 이 알림까지 담아 옵니다. 조회가 나가 있는 동안 온 알림은 따로 두었다가
 *  답 위에 다시 붙입니다(`loadList`) — 답은 물은 시각의 것이라 그 뒤 알림이 늘
 *  새 값입니다.
 *
 *  **체결이면 미결제약정과 주문 목록을 다시 부릅니다.** 잔고는 알림에 안 실려
 *  오고 화면이 셈하지 않습니다. 주문 목록은 알림으로 이미 갈아 끼웠지만 나눠
 *  체결된 주문의 평균체결가는 조회만 줍니다. 물어본 적 없는 자리와 환경이 바뀌어
 *  비워진 자리는 안 부릅니다 — 보는 자리가 제 규칙으로 부릅니다. */
/* 우리가 방금 낸 주문의 접수 줄.
 *
 * **조회에 안 잡혀도 지우지 않습니다.** 조회 답은 물은 시각의 목록이라 방금
 * 접수된 주문을 모를 수 있는데, 그때 줄을 지우면 사용자가 낸 주문이 화면에서
 * 사라집니다 — 낸 사람은 그것을 「안 나갔다」로 읽고 한 번 더 냅니다.
 *
 * 같은 주문번호가 답에 실려 오면 그때 여기서 빠집니다. 서버가 아는 값이 우리가
 * 적어 둔 값보다 낫습니다. */
const acceptedOwn = new Map<DepositMarket, Map<string, OrderEvent>>()

/** 답에 실려 온 주문을 걷어내고, 아직 안 잡힌 접수 줄만 돌려줍니다. */
function settleAccepted(market: DepositMarket, answered: readonly ServerOrder[]): OrderEvent[] {
  const held = acceptedOwn.get(market)
  if (!held || held.size === 0) return []
  for (const row of answered) if (row.id) held.delete(row.id)
  return [...held.values()]
}

/** 접수 답 한 줄을 목록에 얹고, 조회가 그 주문을 알아볼 때까지 들고 있습니다.
 *  **주문을 보낸 자리가 부릅니다**(`screens/trade/TradeScreen.tsx`). */
export function noteAcceptedOrder(market: DepositMarket, row: OrderEvent): void {
  const id = String(row.id ?? '').trim()
  if (!id) return
  const held = acceptedOwn.get(market) ?? new Map<string, OrderEvent>()
  held.set(id, row)
  acceptedOwn.set(market, held)
  applyOrderEvents(market, [row])
}

export function applyOrderEvents(market: DepositMarket, events: readonly OrderEvent[]): void {
  if (events.length === 0) return
  const key = listKey(market, 'orders', 'all')
  const held = lists.get(key) as ListEntry<ServerOrder> | undefined
  if (held?.rows != null) announceList(key, { ...held, rows: mergeOrderEvents(held.rows, events) })
  if (flyingLists.has(key)) flownEvents.set(key, [...(flownEvents.get(key) ?? []), ...events])

  if (!events.some(isFill)) return
  for (const each of [key, listKey(market, 'positions')]) {
    const args = asked.get(each)
    if (args && lists.has(each)) requestList(args)
  }
}

/** 끊겼다 다시 붙은 뒤 이 시장의 주문·미결제약정 목록을 다시 부릅니다. 끊긴
 *  동안의 알림은 아무도 안 보내 주므로 조회로 메웁니다. **물어본 적 있는 자리만**
 *  부릅니다 — 안 보는 목록까지 부르면 보는 목록이 계좌 조회 한도에 밀립니다.
 *  환경이 바뀌어 비워진 자리도 안 부릅니다 — 보는 자리가 제 규칙으로 부릅니다. */
export function reloadAccountLists(market: DepositMarket): void {
  for (const [key, args] of asked) {
    if (args.market !== market || !lists.has(key)) continue
    /* 해외는 보유포지션 만기 조회도 함께입니다 — 새로 생긴 보유의 최초통보일이
       잔고 탭을 다시 열기 전까지 안 서지 않게 합니다. */
    if (args.kind === 'orders' || args.kind === 'positions' || (args.kind === 'expiry' && market === 'overseas')) {
      requestList(args)
    }
  }
}

/** 창이 **다시 보일 때** 한 번 부릅니다. 저절로 되풀이해 부르지는 않습니다 —
 *  계좌 조회의 초당 한도를 보는 자리들이 나눠 씁니다. 다른 창에 다녀온 사이에
 *  생긴 변화(앱 밖 체결 등)를 그 자리가 한 번 새로 받습니다.
 *
 *  서 있는 자리만 부릅니다 — 화면에 없는 자리는 이 신호를 듣지 않습니다. */
export function useReloadWhenShown(reload: () => void, enabled: boolean): void {
  const latest = useRef(reload)
  latest.current = reload
  useEffect(() => {
    if (!enabled) return
    const onChange = () => {
      if (document.visibilityState === 'visible') latest.current()
    }
    document.addEventListener('visibilitychange', onChange)
    return () => document.removeEventListener('visibilitychange', onChange)
  }, [enabled])
}

/** 목록을 읽고, 이 자리가 화면에 설 때 부릅니다.
 *
 *  **부르는 것은 보는 자리뿐입니다.** 계좌 조회에는 초당 한도가 있어, 안 보는
 *  탭까지 부르면 보는 탭이 밀립니다. 그래서 탭마다 제 자리에서 이것을 부르고,
 *  탭을 안 열면 그 조회도 없습니다. */
export function useListOnce<T>(
  market: DepositMarket,
  kind: ListKind,
  scope?: OrderScope,
  period?: Period,
  conversion?: string,
): ListEntry<T> {
  /* 기간은 글자 둘로 풀어 둡니다. 객체를 그대로 쓰면 그릴 때마다 다른 것이
     되어 같은 기간을 계속 다시 부릅니다.

     **한쪽이 비면 안 준 것과 같게 다룹니다** — 담는 열쇠도 그래야 부르는 쪽과
     읽는 쪽이 같은 자리를 봅니다. 다르면 받아 둔 값을 못 찾아 늘 비어 보입니다. */
  const from = period?.from ?? ''
  const to = period?.to ?? ''
  const span = from && to ? { from, to } : undefined
  const key = listKey(market, kind, scope, span, conversion)
  const entry = useSyncExternalStore(
    subscribeAccount,
    () => listEntry<T>(key),
    () => EMPTY_LIST as ListEntry<T>,
  )
  /* 환경을 아직 모르면 기다렸다가 알게 되면 부릅니다. 담긴 줄이 지워져 「안
     불렀다」로 돌아가면(환경이 바뀜) 다시 부릅니다. 예수금과 같은 규칙입니다. */
  const settled = useEnvironmentSettled()
  const idle = entry.status === 'idle'
  /* 그 시장의 인증 정보가 없으면 부르지 않습니다 — 빈 키로 물으면 토큰 발급부터
     실패해 오류만 남습니다. 목록은 「안 불렀다」로 남고, 인증 정보를 채우면 그때
     부릅니다. 설정이나 접속 환경을 아직 모르면 막지 않습니다. */
  const credentialed = useMarketCredentialed(market)
  /* 만기 조회는 해외에만 있습니다. 국내로 물으면 없는 주소입니다. */
  const usable = credentialed && (kind !== 'expiry' || market === 'overseas')
  /* 이 자리가 설 때(화면에 들어올 때) 부르고, 창이 다시 보일 때 한 번 더 부릅니다
     (기간 조회는 빼고 — `reloadsWhenShown`).
     나가 있는 같은 물음이 있으면 겹쳐 묻지 않습니다(`loadList`). */
  useEffect(() => {
    if (settled && usable) void loadList(market, kind, scope, from && to ? { from, to } : undefined, conversion)
  }, [market, kind, scope, from, to, conversion, settled, idle, usable])
  useReloadWhenShown(
    () => void loadList(market, kind, scope, from && to ? { from, to } : undefined, conversion),
    settled && usable && reloadsWhenShown(kind, span !== undefined),
  )
  if (!usable) return WITHHELD_LIST as ListEntry<T>
  /* 환경을 기다리는 동안은 「받는 중」입니다 — 예수금과 같은 까닭입니다. */
  return idle && !settled ? (WAITING_LIST as ListEntry<T>) : entry
}

/** 창이 다시 보일 때 저절로 다시 받는 목록인지. 앱 밖에서 바뀔 수 있는 지금의
 *  값(주문·잔고·만기·오늘 주문오류)만 받습니다. **기간 조회는 받지 않습니다** — 지난
 *  날의 값은 바뀌지 않는데, 서버가 날마다·쪽마다 NH 를 여러 번 불러 계좌 조회
 *  한도를 오래 차지합니다. 기간 조회는 「다시 받기」로만 다시 받습니다. */
function reloadsWhenShown(kind: ListKind, hasPeriod: boolean): boolean {
  if (hasPeriod) return false
  return kind === 'orders' || kind === 'positions' || kind === 'expiry' || kind === 'errors'
}

const WAITING_LIST: ListEntry<never> = { ...EMPTY_LIST, status: 'loading' }
const WITHHELD_LIST: ListEntry<never> = { ...EMPTY_LIST, withheld: true }

/** 목록을 **읽기만** 합니다. 부르지 않습니다 — 받아 둔 줄이 있으면 쓰고, 없으면
 *  「안 불렀다」입니다. 다른 자리가 부른 목록을 곁에서 참고할 때 씁니다. */
export function useListEntry<T>(
  market: DepositMarket,
  kind: ListKind,
  scope?: OrderScope,
  period?: Period,
  conversion?: string,
): ListEntry<T> {
  const key = listKey(market, kind, scope, period, conversion)
  return useSyncExternalStore(
    subscribeAccount,
    () => listEntry<T>(key),
    () => EMPTY_LIST as ListEntry<T>,
  )
}

/* 환경이 바뀌면 전부 지웁니다 — 다른 계좌의 값입니다. 몰랐다가 알게 된 것이면
   이름이 다른 값만 지웁니다 — 이름을 알게 된 것이지 값이 바뀐 것이 아닙니다.
   받는 중인 자리는 그대로 둡니다. 그 답이 제 이름을 달고 옵니다. */
onEnvironmentChange((change) => {
  if (change.kind === 'switched') {
    entries.clear()
    lists.clear()
    asked.clear()
    flownEvents.clear()
    /* 접수 줄도 비웁니다 — 모의에서 낸 주문이 실전 미체결 표에 남으면, 그 줄은
       조회가 영영 못 알아봐서(다른 계좌입니다) 지워지지도 않습니다. */
    acceptedOwn.clear()
    reask.clear()
  } else {
    for (const [key, entry] of entries) {
      if (entry.status !== 'loading' && entry.environment !== change.active) entries.delete(key)
    }
    for (const [key, entry] of lists) {
      if (entry.status !== 'loading' && entry.environment !== change.active) lists.delete(key)
    }
  }
  for (const listener of listeners) listener()
})
