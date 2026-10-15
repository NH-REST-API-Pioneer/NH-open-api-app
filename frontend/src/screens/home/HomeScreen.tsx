import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { Num, fracWidth } from '../../lib/number'
import { Spark } from '../../lib/Spark'
import { kstClock, kstMinutes } from '../../lib/kst'
import { useWishes } from '../../data/stream'
import { resolve } from '../../data/instruments'
import {
  quoteEntry,
  loadBars,
  loadPrice,
  subscribeQuotes,
  useBars,
  usePrice,
} from '../../data/quotes'
import {
  depositMoney,
  isDomesticDeposit,
  retryDeposit,
  retryList,
  useDepositOnce,
  useListOnce,
  useMarketCredentialed,
  type DepositEntry,
  type DepositMarket,
  type DepositRow,
  type ListEntry,
  type ServerOrder,
  type ServerOrderError,
} from '../../data/account'
import { toOrder, toOrderError } from '../../data/accountRows'
import type { MarketContext, RecentItem } from '../../lib/types'
import {
  MARKET_LINES,
  domesticContextOf,
  marketLineHours,
  subscribeSession,
  useSession,
  useTimetable,
} from '../../data/session'
import { WATCH_SLOTS, defaultWatch, tileOf, type Tile } from '../../data/homeWatch'
import { WatchPicker } from './WatchPicker'
import { refreshMaster } from '../../data/master'
import { useEnvironment } from '../../data/environment'
import { useMasterStatus } from '../../lib/useMaster'
import { useUiState } from '../../data/uiState'
import './home.css'

/* 홈 — 앱을 켜면 처음 보는 화면.
 *
 * 계좌가 붙어 있으니 내 돈이 지수보다 먼저입니다. 그리고 미결제는 방치가 곧
 * 손실이라, 「걸어둔 것」이 「볼 것」보다 위에 섭니다.
 *
 * 들어올 때마다 다시 부릅니다. 자동 갱신은 없고 새로고침 버튼이 있습니다 —
 * 훑는 화면에 값을 계속 끌어오면 호출 제한이 정작 필요할 때 모자랍니다.
 */

/* 기준 종목 하나만 큰 타일입니다. 스파크라인이 길수록·높을수록 형태가
 * 읽히므로, 홈에서 세로로 늘어나는 것은 이 하나뿐입니다. */
/** 여러 시각 중 **가장 최근**. 둘 다 오늘 안에서 이미 지난 시각이라는 것을
 *  써서 「지금으로부터 얼마나 지났나」로 견줍니다 — 국내 야간장은 자정을 넘겨
 *  이어지므로 글자로 견주면 00:10 이 23:55 보다 최근이라고 나옵니다. */
function latest(times: string[]): string {
  if (times.length === 0) return ''
  /* 줄의 시각은 한국시간이라 지금도 한국시간으로 셉니다. */
  const nowMinutes = kstMinutes(Date.now())
  const ago = (text: string) => {
    const [hour, minute] = text.split(':').map(Number)
    return (nowMinutes - (hour * 60 + minute) + 1440) % 1440
  }
  return times.reduce((best, one) => (ago(one) < ago(best) ? one : best))
}

/* 타일 한 칸이 지금 무엇을 보일 수 있는가.
 *
 * **다섯 갈래를 가릅니다.** 값이 없는 까닭마다 사용자가 할 일이 다릅니다 —
 * 받는 중이면 기다리고, 못 받았으면 다시 받고, 거절이면 눌러도 같은 답이며,
 * 「받았는데 값이 아직 없다」는 그 종목에 오늘 거래가 없다는 뜻이고,
 * **아직 안 물어본 자리**는 우리가 그 시장의 조회를 아직 안 붙인 것입니다.
 * 다섯을 한 얼굴로 두면 사용자가 될 때까지 새로고침을 누릅니다.
 *
 * 값 갈래를 가르는 칸은 **현재가 하나**입니다. 전일대비·등락률은 시세가 있어도
 * 안 올 수 있는 칸이라 그때는 그 칸만 「—」로 섭니다 — 셋을 다 요구하면 멀쩡히
 * 그릴 수 있는 타일이 「거래 없음」으로 섭니다. */
type TileFace =
  | { kind: 'values'; last: number; change: number | null; changePct: number | null }
  | { kind: 'loading' }
  | { kind: 'failed'; retry: boolean }
  | { kind: 'empty' }

function useTileFace(tile: Tile): TileFace {
  /* 두 시장 다 부릅니다 — 어느 길로 갈지는 시세 저장소가 종목으로 정합니다
     (`data/quotes.ts`). 국내는 세션도 같이 묻습니다 — 야간이면 현재가가 야간
     조회로 나가야 하고, 그 판단은 세션 답이 합니다. 해외는 길이 하나라 안 묻습니다. */
  useSession('domestic', tile.market === 'domestic' ? tile.code : '')
  const entry = usePrice(tile.code)

  /* **값이 있으면 값이 먼저입니다.** 다시 받다 실패해도 앞서 받은 값은 틀린 값이
     아니라 낡은 값이고, 낡았다는 사실은 카드 위 한 줄이 말합니다. 값을 「못 받음」
     으로 갈아 끼우면 새로고침 한 번에 멀쩡한 값이 사라집니다. */
  const price = entry.price
  if (price && price.last !== null) {
    return { kind: 'values', last: price.last, change: price.change, changePct: price.changePct }
  }
  if (entry.failure) return { kind: 'failed', retry: entry.failure === 'retry' }
  return entry.status === 'ready' ? { kind: 'empty' } : { kind: 'loading' }
}

/** 값이 안 서는 칸에 서는 한 마디. **까닭마다 다릅니다** — 「없음」 하나로
 *  뭉치면 기다릴 자리와 다시 받을 자리가 같은 얼굴이 됩니다. */
function faceWord(face: TileFace): string {
  if (face.kind === 'loading') return '받는 중'
  if (face.kind === 'failed') return face.retry ? '못 받음' : '받지 못했습니다'
  return '거래 없음'
}

function LeadTile({ tile }: { tile: Tile }) {
  const price = fracWidth(tile.decimals)
  const face = useTileFace(tile)
  /* 곡선은 **큰 타일에만** 있습니다. 작은 줄에서 56×24 곡선이 주는 것은
     오르내림 모양 하나인데, 그것은 바로 옆 숫자와 등락률이 이미 말합니다.
     큰 타일은 원래 더 보여 주는 자리라 값 하나를 더 부를 만합니다. */
  const bars = useBars(face.kind === 'values' ? tile.code : '')

  return (
    <>
      <span className="tile-name">
        {tile.name}
        {/* 이 누름이 화면을 나간다는 표시입니다. 오른쪽 화살표는 「다른 곳으로」,
            작은 줄의 위쪽 화살표는 「여기 안에서」를 뜻합니다. */}
        <span className="tile-hint" aria-hidden="true">
          주문으로 →
        </span>
      </span>
      {face.kind === 'values' ? (
        <>
          <span className="tile-price" style={price}>
            <Num value={face.last} decimals={tile.decimals} />
          </span>
          {/* 안 온 칸은 빈 채입니다 — 0 으로 적으면 「안 움직였다」가 되고, 「—」는 이
              시장에 원래 없는 값의 말입니다. */}
          <span className="tile-change">
            <span style={price}>
              {face.change !== null && <Num value={face.change} decimals={tile.decimals} signed toned />}
            </span>
            <span style={fracWidth(2, 1)}>
              {face.changePct !== null && (
                <Num value={face.changePct} decimals={2} signed toned suffix="%" />
              )}
            </span>
          </span>
        </>
      ) : (
        /* 값이 없으면 **까닭만** 그 자리에 섭니다. 숫자 자리를 뼈대나 「—」로
           채우지 않습니다 — 뼈대는 「곧 온다」는 말이고, 「—」는 「이 종목엔
           원래 없는 값」이라는 말입니다. */
        <span className="tile-word">{faceWord(face)}</span>
      )}
      {/* 선은 이름·값 아래에 카드 폭을 다 씁니다. 흐름이 형태로 읽히려면 길게
          깔려야 합니다 — 짧게 자르면 같은 자료가 잔물결이 됩니다.
          **값이 없으면 선 자리도 없습니다.** 자리만 잡아 두면 회색 블록이
          「곧 온다」로 읽히는데, 조회가 아직 없는 자리에는 안 옵니다. */}
      {face.kind === 'values' && (
      <Spark
        points={bars ? bars.map((bar) => bar.close) : null}
        loaded={bars !== null}
        stretch
        width={1120}
        height={160}
        /* 기준선은 **전일 종가**입니다 — 이 타일이 적는 현재가와 전일대비에서
           셉니다. 봉의 끝 값으로 짓지 않습니다(오늘 봉이 없거나 늦게 올 수 있고,
           그러면 기준이 어제가 아니게 됩니다). 전일대비가 안 온 종목은 모릅니다. */
        base={
          face.kind === 'values' && face.change !== null && Number.isFinite(face.last - face.change)
            ? face.last - face.change
            : null
        }
        times={bars ? bars.map((bar) => barTime(bar.timestamp)) : undefined}
        decimals={tile.decimals}
      />
      )}
    </>
  )
}

/* 나머지 다섯은 가로 한 줄짜리 목록입니다. 세로로 쌓으면 이름·값·등락이
 * 타일 높이에 안 들어가고, 다섯은 고르기 전에 훑는 대상이라 목록이 맞습니다. */
function QuoteRow({ tile }: { tile: Tile }) {
  const price = fracWidth(tile.decimals)
  const face = useTileFace(tile)

  return (
    <>
      {/* 목록의 이름은 잘려도 됩니다 — 여럿 중 하나를 찾는 자리라 앞부분이면
          알아봅니다. 다만 전체는 물어볼 수 있어야 합니다. */}
      <span className="quote-name" title={tile.name}>
        {tile.name}
        <span className="quote-hint" aria-hidden="true">
          ↑ 크게 보기
        </span>
      </span>
      {face.kind === 'values' ? (
        <>
          <span className="quote-price" style={price}>
            <Num value={face.last} decimals={tile.decimals} />
          </span>
          <span className="quote-change" style={price}>
            {face.change !== null && <Num value={face.change} decimals={tile.decimals} signed toned />}
          </span>
          {/* 등락률만 알약에 담습니다. 이 목록은 「무엇이 움직였나」를 찾으며
              훑는 곳이라 등락률이 표적이고, 바탕은 표적에만 깝니다.
              알약 폭은 열 폭 전부입니다 — 값에 맞춰 줄이면 「−13.36%」가
              「−0.88%」보다 긴 알약이 되어 길이가 크기를 말하게 됩니다. */}
          <span className={`quote-pct${face.change !== null && face.change > 0 ? ' up' : face.change !== null && face.change < 0 ? ' down' : ''}`}>
            <span style={fracWidth(2, 1)}>
              {face.changePct !== null && (
                <Num value={face.changePct} decimals={2} signed toned suffix="%" />
              )}
            </span>
          </span>
        </>
      ) : (
        /* 값 세 칸을 한 마디가 대신합니다. 칸마다 같은 말을 세우면 한 줄에
           같은 글자가 셋 섭니다. */
        <span className="quote-word">{faceWord(face)}</span>
      )}
    </>
  )
}

/** 봉 하나의 시각을 한국시각 `HH:MM` 으로. 곡선에 마우스를 올렸을 때 값과 함께 뜹니다. */
function barTime(timestamp: number): string {
  return kstClock(timestamp)
}

/** 한 칸에 담긴 것. 색인이 푸는 종목이거나, 담아 둔 코드가 색인에서 사라진
 *  **낡은 칸**이거나, 빈 칸입니다. */
type Slot = { kind: 'tile'; tile: Tile } | { kind: 'stale'; code: string } | null

/* 색인에 없는 코드가 담긴 칸 — 담아 둔 월물이 만기를 지나 마스터에서 빠진 경우가
 * 대부분입니다. **못 찾았을 때 대신 세울 것이 있으면 그것을 세웁니다** — 저장한
 * 것이 코드뿐이라 이름 자리에 코드(흐림), 값 자리에 한 마디. 숫자 자리를 뼈대나
 * 「—」로 채우지 않습니다(앞은 「곧 온다」, 뒤는 「원래 없다」라 둘 다 거짓이고,
 * 할 일이 있습니다 — 빼거나 바꿉니다). 큰 타일이면 곡선 자리도 없습니다 —
 * 자리를 남기고 비우면 「아직 안 받음」으로 읽힙니다. */
function StaleTile({ code, lead }: { code: string; lead: boolean }) {
  /* 큰 타일과 목록 줄은 다른 격자라 같은 칸 이름을 씁니다 — 목록 줄에서는
     한 마디가 값 세 칸을 대신합니다(값이 없는 종목 줄과 같은 자리). */
  return (
    <>
      <span className={`${lead ? 'tile-name' : 'quote-name'} home-stale-code`} title={code}>
        {code}
      </span>
      {/* 큰 타일은 문장, 목록 줄은 한 마디 — 자리 폭이 다릅니다. 까닭(만기 지남
          등)은 우리가 모르니 적지 않습니다. 낱말은 못 연 종목 줄(`app-missing`)과
          같습니다. */}
      <span className={lead ? 'tile-word' : 'quote-word'}>
        {lead ? '종목 목록에 없는 종목입니다' : '목록에 없음'}
      </span>
    </>
  )
}

function RemoveButton({ name, onRemove }: { name: string; onRemove: () => void }) {
  return (
    <button
      type="button"
      className="home-remove"
      aria-label={`${name} 빼기`}
      title="빼기"
      onClick={onRemove}
    >
      ✕
    </button>
  )
}

/* 숫자와 단위는 한 덩어리입니다. 묶지 않으면 카드가 좁아질 때 「+495,000」과
 * 「원」이 다른 줄에 놓여, 금액이 아니라 두 개의 글자로 읽힙니다. */
interface Props {
  context: MarketContext
  /** 홈에 온 횟수. 오를 때마다 관심종목을 다시 받습니다 — 처음 열 때, 다른
   *  화면에서 돌아올 때, 이미 홈인데 홈을 또 눌렀을 때 모두 「지금 값이
   *  궁금하다」입니다. */
  visit: number
  /** 최근 본 종목. 담기 창이 입력 전 첫 덩어리로 세웁니다. */
  recent: RecentItem[]
  onOpenInstrument: (code: string) => void
  onGoOrders: () => void
  /** 계좌 카드의 「더 보기」 — 그 시장의 잔고를 엽니다. */
  onGoBalance: (overseas: boolean) => void
}

/* 관심종목의 구독 등급. 시세·주문 화면의 주문 대상(9)·둘째 칸(7)보다 낮습니다 —
 * 자리가 스물뿐이라, 모자라면 훑는 자리부터 밀리는 것이 맞습니다. */
const WATCH_RANK = 3

/** 만기 관리 카드의 한 줄 — 만기가 다가오는 보유 종목.
 *
 *  현금결제는 만기에 정산되고 끝이지만 실물 인수도는 최초통보일을 넘기면 실제로
 *  물건을 받습니다. 급이 달라서 줄을 가릅니다. **아직 채우는 조회가 없어** 목록은
 *  비어 있고, 이 모양은 잔고 조회가 붙을 때 그 응답에 맞춰 다시 봅니다. */
interface ExpiryRow {
  code: string
  name: string
  settlement: '실물 인수도' | '현금 결제'
  /** 실물 인수도에만 뜻이 있습니다. */
  noticeDate?: string
  lastTradingDay: string
  daysLeft: number
  quantity: number
}

/** 예수금 답에서 카드가 쓰는 두 줄만 꺼냅니다.
 *
 *  **총액만 씁니다.** 카드는 훑는 자리라 현금·대용·외화까지 가르지 않습니다 —
 *  그 갈래는 계좌 화면이 답합니다. */
function cardTotals(entry: DepositEntry) {
  const value = entry.value
  if (value === null) return null
  const domestic = isDomesticDeposit(value)
  const rows: DepositRow[] = domestic ? value.items : value.groups
  const find = (key: string) => rows.find((row) => row.key === key)?.values[0] ?? null
  return {
    start: find('start'),
    asset: find('assets'),
    currency: domestic ? 'KRW' : value.currency,
    decimals: domestic ? 0 : (value.decimals ?? 2),
  }
}

/** 계좌 카드의 값 두 줄. 얼굴이 여기서 갈립니다. */
function AccountCardBody({ entry, onRetry }: { entry: DepositEntry; onRetry: () => void }) {
  const totals = cardTotals(entry)

  /* **값이 있으면 값이 먼저입니다.** 다시 부르는 중에도, 다시 부르다 실패해도
     앞서 받은 값은 그대로 섭니다 — 골격이 안 바뀌는 갱신에서 값을 지우면
     나갔다 돌아온 화면이 「없다」고 말합니다. */
  if (totals !== null) {
    /* **받았는데 기록이 없는 계좌.** 아직 예탁한 적이 없는 계좌는 답이 오되 줄이
       비어, 예탁자산 총액이 없습니다. 그것은 「못 받음」이 아니고 「0원」도 아니라
       라벨은 남기고 값 자리는 비운 채 한 줄로 말합니다 — 「—」를 세우면 값을
       못 채운 칸으로 읽히고, 「다시」를 세우면 눌러도 같은 답입니다. 국내·해외
       같은 규칙입니다. */
    if (totals.asset === null) {
      return (
        <>
          <p className="home-lead">
            <span className="home-lead-label">오늘</span>
          </p>
          <p className="home-sub">예탁자산</p>
          <p className="home-unasked">예탁자산 기록이 아직 없습니다</p>
        </>
      )
    }
    const today = totals.start !== null ? totals.asset - totals.start : null
    return (
      <>
        <p className="home-lead">
          <span className="home-lead-label">오늘</span>
          {today === null ? (
            <span className="home-amount">—</span>
          ) : (
            <span className={`home-amount${today > 0 ? ' up' : today < 0 ? ' down' : ''}`}>
              {today > 0 ? '+' : ''}
              {depositMoney(today, totals.decimals, totals.currency)}
            </span>
          )}
        </p>
        <p className="home-sub">
          예탁자산{' '}
          <span className="home-amount">
            {depositMoney(totals.asset, totals.decimals, totals.currency)}
          </span>
        </p>
      </>
    )
  }

  /* 아직 값이 없습니다. **뼈대는 「곧 온다」는 말이라 부르는 중에만** 세웁니다. */
  if (entry.status === 'loading') {
    return (
      <>
        <p className="home-lead">
          <span className="home-lead-label">오늘</span>
          <span className="skeleton" style={{ minWidth: '7ch', height: '18px' }} />
        </p>
        <p className="home-sub">
          예탁자산 <span className="skeleton" style={{ minWidth: '8ch' }} />
        </p>
      </>
    )
  }

  return (
    <>
      {/* 값을 못 세워도 **라벨은 남깁니다** — 칸이 사라지면 이 카드가 무엇을
          담는 자리인지까지 없어집니다. */}
      <p className="home-lead">
        <span className="home-lead-label">오늘</span>
      </p>
      <p className="home-sub">예탁자산</p>
      {entry.status === 'failed' ? (
        <p className="home-unasked">
          계좌를 받지 못했습니다
          {/* 거절은 눌러도 같은 답이 옵니다. */}
          {entry.failure === 'retry' && (
            <button type="button" className="btn btn-quiet home-retry" onClick={onRetry}>
              다시
            </button>
          )}
        </p>
      ) : (
        <p className="home-unasked">계좌를 아직 조회하지 않았습니다</p>
      )}
    </>
  )
}

/** 한 시장의 주문 카드 몫 — 미체결·주문내역(전체)·주문오류 세 목록. **계좌·일반주문
 *  화면과 같은 목록 저장소**라, 그 화면에 들어가도 다시 묻지 않습니다. 인증 정보가
 *  없는 시장은 부르지 않습니다(`useListOnce`). */
function useOrderLists(market: DepositMarket) {
  return {
    open: useListOnce<ServerOrder>(market, 'orders', 'open'),
    all: useListOnce<ServerOrder>(market, 'orders', 'all'),
    errors: useListOnce<ServerOrderError>(market, 'errors'),
  }
}

/** 이름 하나와 나머지 개수. 같은 종목이 여러 줄이면 한 번만 셉니다. */
function namesLine(names: readonly string[]): string | null {
  const unique = [...new Set(names.filter(Boolean))]
  if (unique.length === 0) return null
  return unique.length === 1 ? unique[0] : `${unique[0]} 외 ${unique.length - 1}`
}

/** 홈 「주문 내역」 카드 — 미체결·체결·오류 건수. **홈이 스스로 받습니다** — 들어올
 *  때와 창이 다시 보일 때 찬 시장의 세 목록을 한 번씩 받습니다.
 *
 *  **두 시장은 더해 적습니다.** 건수에는 통화가 없어 더해도 되고, 시장별로 가르면
 *  칸이 여섯이 되어 훑는 카드가 아닙니다. 시장별 내역은 「더 보기」가 맡습니다. 한
 *  시장만 찼으면 제목 곁에 그렇다고 적습니다 — 합계처럼 읽히지 않게 합니다.
 *
 *  **셋이 한 문장입니다.** 하나라도 못 받으면 세 칸을 다 「—」로 둡니다 — 일부만
 *  더한 합계는 틀린 수입니다. */
function OrdersCard({ onGoOrders }: { onGoOrders: () => void }) {
  const domesticOn = useMarketCredentialed('domestic')
  const overseasOn = useMarketCredentialed('overseas')
  const domestic = useOrderLists('domestic')
  const overseas = useOrderLists('overseas')
  const sides = [
    ...(domesticOn ? [{ market: 'domestic' as const, lists: domestic }] : []),
    ...(overseasOn ? [{ market: 'overseas' as const, lists: overseas }] : []),
  ]
  const entries: ListEntry<unknown>[] = sides.flatMap(({ lists }) => [lists.open, lists.all, lists.errors])
  const busy = entries.some((entry) => entry.status === 'loading' || entry.refreshing === true || entry.filling)
  const missing = entries.some((entry) => entry.rows === null)
  const failed = entries.some((entry) => entry.rows === null && entry.status === 'failed')
  const stale = !missing && entries.some((entry) => entry.failure !== null)
  const reload = () => {
    for (const { market } of sides) {
      retryList(market, 'orders', 'open')
      retryList(market, 'orders', 'all')
      retryList(market, 'errors')
    }
  }

  /* 건수와 그 줄들의 종목 이름. 부분 체결은 미체결에도 체결에도 셉니다 — 둘 다
     사실이라 어느 한쪽에서 빼면 틀립니다. */
  const openRows = sides.flatMap(({ market, lists }) =>
    (lists.open.rows ?? []).map((row) => toOrder(row, market === 'overseas')),
  )
  const filledRows = sides.flatMap(({ market, lists }) =>
    (lists.all.rows ?? []).filter((row) => (row.filled ?? 0) > 0).map((row) => toOrder(row, market === 'overseas')),
  )
  const errorRows = sides.flatMap(({ market, lists }) =>
    (lists.errors.rows ?? []).map((row) => toOrderError(row, market === 'overseas')),
  )
  const counts = [
    { label: '미체결', count: openRows.length, names: namesLine(openRows.map((row) => row.name)), rule: undefined },
    {
      label: '체결',
      count: filledRows.length,
      names: namesLine(filledRows.map((row) => row.name)),
      rule: '체결 수량이 있는 주문 수 — 부분 체결 포함',
    },
    { label: '오류', count: errorRows.length, names: namesLine(errorRows.map((row) => row.name)), rule: undefined },
  ]
  const only = domesticOn && !overseasOn ? '국내만' : overseasOn && !domesticOn ? '해외만' : null

  return (
    <section className="card home-orders" aria-label="주문 내역">
      <div className="home-card-head">
        <h2 className="home-card-title">주문 내역</h2>
        {only && <span className="home-card-note">{only}</span>}
        {sides.length > 0 && (
          /* 저절로 되풀이해 부르지 않습니다. 다른 창에서 낸 주문을 바로 보고 싶을
             때 누르는 자리입니다. 화면을 옮기는 「더 보기」가 맨 끝입니다. */
          <button
            type="button"
            className="btn btn-quiet home-reload"
            aria-disabled={busy || undefined}
            onClick={() => {
              if (!busy) reload()
            }}
          >
            다시 받기
          </button>
        )}
        <button type="button" className="btn home-more" onClick={onGoOrders}>
          더 보기
        </button>
      </div>
      {sides.length === 0 ? (
        <p className="home-unasked">주문 내역을 아직 조회하지 않았습니다</p>
      ) : (
        <>
          <dl className="home-counts">
            {counts.map((one) => (
              <div key={one.label}>
                <dt title={one.rule}>{one.label}</dt>
                <dd>
                  {missing && !failed ? (
                    /* 받는 중에는 뼈대입니다 — 「곧 온다」는 말입니다. */
                    <span className="skeleton" style={{ minWidth: '3ch' }} />
                  ) : failed ? (
                    <span className="dead">—</span>
                  ) : (
                    one.count.toLocaleString('ko-KR')
                  )}
                </dd>
                {!missing && one.names && <p className="home-count-names">{one.names}</p>}
              </div>
            ))}
          </dl>
          {failed && <p className="home-unasked">주문 내역을 받지 못했습니다</p>}
          {stale && <p className="list-stale">위는 마지막으로 받은 값입니다. 다시 받지 못했습니다</p>}
        </>
      )}
    </section>
  )
}

export function HomeScreen({
  context,
  visit,
  recent,
  onOpenInstrument,
  onGoOrders,
  onGoBalance,
}: Props) {
  /* 관심종목 여섯. 칸 수가 곧 상한이라 「몇 개까지」를 따로 정하지 않습니다.
     사용자 홈의 파일에 남습니다 — 브라우저 저장소가 비워져도, 앱을 다시 깔아도
     그대로입니다. */
  /* 처음 채우는 여섯은 **색인이 도착한 뒤에** 정해집니다 — 종목 코드를 색인에서
     고르기 때문입니다. 그전에는 담긴 것이 없는 상태이고, 저장된 목록이 있으면
     그것이 이깁니다. */
  const [watch, setWatch, watchReady] = useUiState<string[]>('nh.home.watch', [])
  /* 관심종목이 서려면 **색인이 있어야 합니다** — 담긴 코드를 색인이 풀어야
     이름도 값도 나옵니다. 그래서 이 카드만은 **진짜 색인 상태**를 봅니다.
     받는 중과 못 받음과 「받았는데 비어 있음」이 화면에서 갈려야 합니다 —
     셋 다 「칸이 비었다」로 보이면 사용자는 기다릴지 다시 받을지 담을지를
     못 정합니다. 실제로 **받는 동안 빈 칸에 「+」가 서서 「담으라」로 읽혔습니다.** */
  const master = useMasterStatus()
  /* 저장된 목록에 **지금 색인에 없는 종목이 있으면 그 칸은 남기되 이유를
     보입니다.** 담아 둔 코드는 마스터 판본이 바뀌면(월물 만기) 아무것도 안
     가리키게 되는데, 조용히 버리면 사용자는 자기가 담은 것이 왜 사라졌는지
     모릅니다 — 칸에 코드와 까닭이 서고, 빼는 것은 사용자가 합니다.
     **빈 문자열과 못 푸는 코드는 다릅니다** — 빈 문자열은 사용자가 그 칸을
     일부러 비운 것입니다.
     **색인이 오기 전에는 판단하지 않습니다** — 그때는 무엇도 안 풀려서, 멀쩡한
     목록까지 낡은 것으로 보게 됩니다. 담긴 것이 하나도 없으면 기본 목록입니다.
     다만 **사용자가 일부러 다 비운 목록**(칸은 있고 전부 빈 문자열)은 그대로
     빈 채로 둡니다 — 비워 둔 것을 저장했는데 열 때마다 다시 차면 뺀 것이 무시된
     것입니다. */
  const emptiedOnPurpose = watch.length > 0 && watch.every((code) => code === '')
  const shown = useMemo(
    () => (watch.some((code) => code !== '') || emptiedOnPurpose ? watch : defaultWatch()),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [watch, emptiedOnPurpose, master.status],
  )

  /* 관심종목도 실시간을 겁니다. **등급은 가장 낮습니다** — 여기는 훑는 자리이고,
     자리가 모자라면 보고 있는 종목과 주문 대상이 먼저 남아야 합니다.
     **종목의 시장으로 겁니다** — 해외 종목을 국내 길로 걸면 값이 오지 않습니다.
     국내는 지금 세션(주간·야간)의 길입니다. 색인에서 못 푸는 코드는 시장을 몰라
     걸지 않습니다.
     **세션이 바뀌면 다시 짓습니다** — 낮에 지은 목록이 밤에도(또는 그 반대로)
     남으면 그 세션의 값이 안 옵니다. 세션 저장소를 구독해 관심 종목들의 세션이
     바뀐 것을 압니다. */
  const sessions = useSyncExternalStore(
    subscribeSession,
    () => shown.map((code) => (code ? domesticContextOf(code) : '')).join('|'),
    () => '',
  )
  const wishes = useMemo(
    () =>
      shown
        .filter((code) => code !== '' && !code.startsWith('O_'))
        .flatMap((code) => {
          const market = resolve(code)?.market
          if (!market) return []
          return [
            {
              context: market === 'overseas' ? ('overseas' as const) : domesticContextOf(code),
              kind: 'quote' as const,
              sym: code,
              priority: WATCH_RANK,
            },
          ]
        }),
    /* 시장은 색인이 답하므로 색인이 온 뒤 다시 짓습니다. */
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [shown.join('|'), master.status, sessions],
  )
  useWishes('home-watch', wishes)

  /* 어느 빈 칸에서 고르는 중인지. null 이면 고르는 중이 아닙니다. */
  const [picking, setPicking] = useState<number | null>(null)

  /* 칸은 늘 여섯입니다. 뺀 자리는 사라지지 않고 빈 칸으로 남습니다.
     색인이 못 푸는 코드는 **낡은 칸**으로 섭니다 — 무엇을 담아 뒀는지(코드)와
     왜 값이 없는지가 그 자리에 서고, 빼기 단추만 살아 있습니다. */
  const slots: Slot[] = Array.from({ length: WATCH_SLOTS }, (_, i) => {
    const code = shown[i]
    if (!code) return null
    const tile = tileOf(code)
    if (tile) return { kind: 'tile', tile }
    return { kind: 'stale', code }
  })
  const lead = slots[0]
  const rest = slots.slice(1)
  /* 목록 열 이름. 국내 야간의 등락은 **그 거래일의 주간 정산가**에서 잽니다. 열
     이름은 줄 모두에 한 번 서므로, 값이 서는 줄이 **전부** 국내 야간일 때만
     「정산가대비」라 적습니다 — 해외나 주간이 한 줄이라도 섞이면 그 줄에는 틀린
     말이 되어 「전일대비」 그대로 둡니다. 빈 칸과 색인에 없는 칸은 등락을 안
     적으므로 셈에 안 넣습니다. 세션은 서버 답이고, 바뀌면 위 구독이 다시
     그립니다. */
  const valued = rest.flatMap((slot) => (slot?.kind === 'tile' ? [slot.tile] : []))
  const settleBased =
    valued.length > 0 &&
    valued.every((tile) => tile.market === 'domestic' && domesticContextOf(tile.code) === 'domestic-night')

  const add = (slot: number, code: string) => {
    const next = [...watch]
    while (next.length < WATCH_SLOTS) next.push('')
    next[slot] = code
    setWatch(next)
    setPicking(null)
  }

  /* 뺀 자리는 그대로 빈 칸입니다. 뒤를 당겨 채우면 다른 종목이 자리를 옮겨,
     자기가 안 건드린 칸이 움직인 것으로 보입니다. */
  const remove = (slot: number) => {
    const next = [...watch]
    while (next.length < WATCH_SLOTS) next.push('')
    next[slot] = ''
    setWatch(next)
  }

  /* 방금 맞바꾼 줄. 들어오는 쪽만 잠깐 움직입니다 — 나가는 것까지 흐리면
     같은 자리에서 두 글자가 겹쳐 그동안 둘 다 안 읽힙니다. */
  const [swapped, setSwapped] = useState<number | null>(null)

  /* 작은 줄을 누르면 큰 타일과 자리를 바꿉니다. 큰 타일로 올라온 뒤에 다시
     누르면 그때 주문 화면으로 갑니다 — 「크게 보기」와 「주문하러 가기」는
     다른 일이라, 한 번의 누름에 둘을 담지 않습니다.
     순서는 그대로 저장되므로 다시 열어도 고른 대로 있습니다. */
  const swapToLead = (slot: number) => {
    const next = [...watch]
    while (next.length < WATCH_SLOTS) next.push('')
    const head = next[0]
    next[0] = next[slot]
    next[slot] = head
    setWatch(next)
    setSwapped(slot)
    window.setTimeout(() => setSwapped(null), 200)
  }
  /* **계좌·주문 카드는 아직 조회가 없습니다.** 예전에는 타이머로 채워지는
     흉내를 냈는데, 그러면 화면이 「받는 중 → 받았음」을 연기하게 되어 진짜
     조회가 붙는 날까지 **없는 값이 있는 것처럼** 보입니다. 지금은 그 자리가
     제 상태를 말합니다 — 라벨은 남기고 값만 비웁니다.

     **뼈대(skeleton)를 세우지 않습니다.** 뼈대는 「곧 온다」는 말인데 이 자리는
     부르는 곳이 아직 없어 안 옵니다. 앱을 켠 직후나 설정에 키가 없을 때도
     같은 얼굴이라, 조회가 붙은 뒤에도 그대로 쓰는 상태입니다. */
  /* 이 화면에서 실제로 부르는 것은 **관심종목**뿐입니다. 주문 카드는 아직 부를
     곳이 없습니다. 마스터에 없는 코드(낡은 칸)는 부를 길이 없어 뺍니다. */
  const watched = shown.filter((code) => code !== '' && resolve(code) !== null)
  /* 큰 타일의 곡선은 분봉 한 건입니다. */
  const leadCode = lead?.kind === 'tile' ? lead.tile.code : ''

  /* 타일들의 상태를 한 줄로 모아 봅니다. 타일마다 제 값을 구독하지만, 위쪽
     단추와 「갱신」은 **모두를 합쳐** 말해야 하기 때문입니다. */
  const snapshot = useSyncExternalStore(
    subscribeQuotes,
    () =>
      watched
        .map((code) => {
          const entry = quoteEntry(code)
          const stale = entry.price !== null && entry.failure !== null
          return `${entry.at}|${stale ? 'stale' : entry.status}`
        })
        .join(','),
    () => '',
  )
  const rows = snapshot === '' ? [] : snapshot.split(',')
  const loading = rows.some((row) => row.endsWith('|loading'))
  const updatedAt = latest(rows.map((row) => row.split('|')[0]).filter(Boolean))
  /* 값이 있는데 이번에 다시 받지 못한 칸 수. 그 칸의 값은 그대로 서 있으니(낡은
     값이지 틀린 값이 아닙니다) 카드 위 한 줄로만 말합니다. */
  const staleCount = rows.filter((row) => row.endsWith('|stale')).length
  /* 장 시간 줄의 시간표. 앱이 뜰 때 한 번 받아 두는 것이라 여기서는 구독만 합니다 —
     값은 그리는 자리에서 읽고, 이 구독은 시간표가 온 뒤 다시 그리게만 합니다. */
  useTimetable()

  /* 다시 받습니다. **이미 받아 둔 값이 있어도 다시 부릅니다** — 사용자가 이
     단추를 누르는 것은 「지금 값이 궁금하다」이고, 그때 옛 값을 그대로 두면
     누른 보람이 없습니다. 현재가는 칸마다 한 건, 곡선은 큰 타일 한 건입니다 —
     여섯 칸이 다 차도 일곱 건이라 시세 예산(초당 열) 안입니다.
     **받는 동안 값은 그대로 섭니다** — 갱신은 골격이 안 바뀌는 일이라 뼈대로
     되돌리지 않습니다. 같은 종목이 이미 받는 중이면 겹쳐 내지 않습니다. */
  const load = () => {
    watched.forEach((code) => void loadPrice(code, { force: true }))
    if (leadCode) void loadBars(leadCode, { force: true })
  }

  /* **홈에 올 때마다 한 번 받습니다** — 처음 열 때, 돌아올 때, 홈에서 홈을 또
     눌렀을 때. 주기적으로 다시 받거나 실시간으로 곡선을 고치는 일은 없습니다 —
     현재가 실시간은 칸이 따로 받고, 곡선은 이 한 번의 조회가 전부입니다.
     받아 둔 값이 있어도 다시 부릅니다(완료된 옛 조회가 새 방문을 막지 않게).
     **색인과 담긴 목록이 온 뒤, 그리고 모의인지 실전인지 안 뒤의 방문만 셉니다** —
     그전에는 부를 코드가 없거나 온 값에 붙일 이름이 없고, 갖춰지면 그때 한 번
     부릅니다. */
  const environment = useEnvironment()
  const environmentSettled = environment.status === 'ready' || environment.status === 'failed'
  const visitedRef = useRef(-1)
  useEffect(() => {
    if (master.status !== 'ready' || !watchReady || !environmentSettled) return
    if (visitedRef.current === visit) return
    visitedRef.current = visit
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visit, master.status, watchReady, environmentSettled])

  /* 상단 시장 띠가 고른 시장의 묶음을 앞에 둡니다. 화면을 바꾸지 않고
     보는 순서만 바꿉니다 — 지금 보려는 시장이 맨 앞에 오면 됩니다. */
  const overseasFirst = context === 'overseas'

  /* **홈은 저절로 부릅니다.** 훑는 화면이라 눌러야 보이면 훑는 자리가 아니고,
     같은 화면의 관심종목이 이미 저절로 오므로 규칙이 둘이면 안 됩니다.
     두 시장이 다른 계좌라 각자 한 건씩, 화면당 둘입니다. */
  const domesticDeposit = useDepositOnce('domestic')
  const overseasDeposit = useDepositOnce('overseas')

  const domesticCard = (
    <section key="domestic" className="card home-account" aria-label="국내 계좌">
      <div className="home-card-head">
        <h2 className="home-card-title">국내</h2>
        <button type="button" className="btn home-more" onClick={() => onGoBalance(false)}>
          더 보기
        </button>
      </div>

      <AccountCardBody entry={domesticDeposit} onRetry={() => retryDeposit('domestic')} />
    </section>
  )

  const overseasCard = (
    <section key="overseas" className="card home-account" aria-label="해외 계좌">
      <div className="home-card-head">
        <h2 className="home-card-title">해외</h2>
        <button type="button" className="btn home-more" onClick={() => onGoBalance(true)}>
          더 보기
        </button>
      </div>

      <AccountCardBody entry={overseasDeposit} onRetry={() => retryDeposit('overseas')} />
    </section>
  )

  /* 만기가 걸린 포지션이 없으면 카드를 안 그립니다 —
     「임박한 만기 없음」을 매일 보여줄 이유가 없습니다. */
  /* **보유 종목을 아직 모릅니다.** 만기가 걸린 포지션은 잔고에서 나오는데 그
     조회가 아직 없어, 걸린 만기도 빈 목록입니다. 이 카드는 원래 「걸린 것이
     없으면 안 그린다」라 저절로 사라집니다 — 「임박한 만기 없음」을 매일 세워
     둘 이유가 없고, **모르는 것을 없다고 적는 것도 아닙니다**(카드가 아예 안
     섭니다). */
  const expiries: ExpiryRow[] = []
  const expiryCard =
    expiries.length > 0 ? (
      <section key="expiry" className="card home-expiry" aria-label="보유 종목 만기 관리">
        <div className="home-card-head">
          <h2 className="home-card-title">보유 종목 만기 관리</h2>
        </div>
        {
          <ul className="home-expiry-list">
            {[...expiries]
              .sort((a, b) =>
                a.settlement === b.settlement
                  ? a.daysLeft - b.daysLeft
                  : a.settlement === '실물 인수도'
                    ? -1
                    : 1,
              )
              .map((row) => (
                <li key={row.code} className={row.settlement === '실물 인수도' ? 'home-expiry-hard' : undefined}>
                  <span className="home-expiry-name">{row.name}</span>
                  {/* 남은 날이 먼저입니다. 이 카드에서 읽는 것은 「며칠 남았나」이고
                      날짜는 그것을 확인하는 자리입니다. */}
                  <span className="home-expiry-sub">
                    <span className={`badge${row.settlement === '실물 인수도' ? ' badge-warn' : ''}`}>
                      {row.settlement}
                    </span>
                    <span>
                      {`D-${row.daysLeft} · ${row.quantity}계약 · `}
                      {row.noticeDate ? `최초통보일 ${row.noticeDate}` : `만기 ${row.lastTradingDay}`}
                    </span>
                  </span>
                </li>
              ))}
          </ul>
        }
      </section>
    ) : null

  const ordersCard = <OrdersCard key="orders" onGoOrders={onGoOrders} />

  /* 카드가 배열로 서므로 각 카드가 제 이름표를 답니다. 이름표가 없으면 React 가
     순서로 짝을 맞추는데, 국내·해외 카드는 설정에 따라 자리를 맞바꿉니다 —
     순서로만 맞추면 맞바꾼 뒤 한 카드의 내용이 다른 카드 자리에 남을 수 있습니다. */
  const row = [
    overseasFirst ? overseasCard : domesticCard,
    overseasFirst ? domesticCard : overseasCard,
    expiryCard,
    ordersCard,
  ].filter(Boolean)

  return (
    <div className="home">
      {/* 거래시간은 서버가 받아 둔 시간표(`data/session.ts`)입니다. 「지금 열려
          있는가」는 여기 안 적습니다 — 세션은 종목마다 달라 그 종목의 헤더가
          말하고, 휴장 정보는 없어 지어내지 않습니다. 시간표를 못 받았으면 라벨만
          남고 시간 자리가 빕니다 — 「—」는 「원래 없음」이라 여기 안 씁니다. 점에도
          색을 쓰지 않습니다 — 정상에 색을 쓰면 이상할 때 쓸 색이 없습니다. */}
      <section className="home-hours" aria-label="장 시간">
        {/* 띠를 **미는 자리와 안 미는 자리**로 가릅니다. 좁아지면 이 트랙만
            줄어들고, 오른쪽 덩어리는 제자리에 섭니다 — 띠가 좁아질 때 양보하는
            것은 보조 설명이고, 길을 여는 조작과 값은 양보하지 않습니다. */}
        <div className="home-hours-track">
          {MARKET_LINES.map((item) => (
            <span key={item.key} className="home-hour">
              <span className="conn-dot" aria-hidden="true" />
              <span className="home-hour-name">{item.label}</span>
              <span className="home-hour-time">{marketLineHours(item.key)}</span>
            </span>
          ))}
          {/* 세 줄이 적는 것은 **그 시장이 열려 있는 폭**이고, 그 안이 내내 열려
              있는 것은 아닙니다. 그 사실을 띠에 **한 번만** 답니다 — 줄마다 달면
              같은 말이 셋이 되고, 한 종목의 시각을 더 말해 주지도 않습니다.
              자리는 설명하는 대상 바로 뒤이고, 트랙에서 줄어드는 몫은 이 마디가
              집니다 — 줄 셋은 줄면 시각이 잘립니다. */}
          <span className="home-hours-note" title="종목 시간은 그 종목 화면에">
            종목 시간은 그 종목 화면에
          </span>
        </div>

        {/* 안 미는 덩어리. 다시 받는 길과 그 값이 언제 것인지는 창이 좁다고
            사라지면 안 됩니다 — 옆으로 굴려야 나오는 단추는 없는 것과 같습니다. */}
        <div className="home-hours-fixed">
          {/* 받는 동안 잠급니다 — 먼저 나간 요청은 취소되지 않아, 연달아 누르면
              호출 예산만 먹습니다. 잠긴 동안 무엇을 기다리는지도 단추가 말합니다.
              **이 단추가 부르는 것은 관심종목뿐입니다** — 계좌·주문 카드는 아직
              부를 곳이 없어 이 누름이 바꿀 것이 없습니다. */}
          <button
            type="button"
            className={`btn home-refresh ${loading ? '' : 'btn-outline'}`.trim()}
            disabled={loading}
            onClick={load}
          >
            {loading ? '불러오는 중' : '새로고침'}
          </button>
          <span className="as-of">{updatedAt && `갱신 ${updatedAt}`}</span>
        </div>
      </section>

      {/* 넷을 한 줄로 폅니다. 오른쪽에 세로로 쌓으면 그 열이 행 높이를 정하고
          왼쪽 카드 아래가 배경으로 드러나 구멍처럼 보입니다. 한 줄이면 카드가
          모두 행 높이로 늘어나 그 자리가 안 생깁니다.
          열의 바닥은 카드 내용이 한 줄로 들어가는 폭입니다 — 그보다 좁아지면
          접는 대신 이 줄이 가로로 밉니다. */}
      <div
        className="home-row"
        style={{ gridTemplateColumns: `repeat(${row.length}, minmax(max-content, 1fr))` }}
      >
        {row}
      </div>

      {/* 여섯 칸. 첫 칸이 큰 타일이고 나머지 다섯이 목록입니다.
          빈 칸은 「+ 눌러서 추가」로 남습니다 — 칸을 없애면 여섯이라는 상한이
          화면에서 사라지고, 다시 넣을 자리도 없어집니다. */}
      <section className="card home-quotes" aria-label="주요 시세">
        {/* **받는 중에는 담을 자리를 안 엽니다.** 「+」를 세우면 「비어 있으니
            담으라」로 읽히는데, 그때는 담을 목록도 아직 없습니다 — 색인이 와야
            고를 종목이 생깁니다. 뼈대만 두고 기다리게 합니다.
            낱말은 종목 검색이 쓰는 것과 같습니다 — 같은 일(색인을 못 받음)에
            화면마다 다른 말을 하면 사용자가 다른 일로 읽습니다. */}
        {master.status === 'loading' || !watchReady ? (
          /* 담아 둔 목록이 오기 전에는 안 그립니다 — 기본 목록으로 그렸다가
             파일 값이 도착해 갈아 치우면, 사용자는 자기가 뺀 종목이 왜 돌아왔다
             다시 사라지는지 알 수 없습니다. */
          <CardSkeleton lines={4} />
        ) : master.status === 'failed' ? (
          <p className="home-quotes-note">
            종목 목록을 못 받았습니다
            <button type="button" className="home-quotes-retry" onClick={() => void refreshMaster()}>
              다시 받기
            </button>
          </p>
        ) : (
          <>
        {staleCount > 0 && (
          <p className="list-stale">{staleCount}종목은 다시 받지 못해 이전 값입니다</p>
        )}
        {lead?.kind === 'tile' ? (
          <div className="home-tile-slot">
            <button
              type="button"
              className={`home-tile home-tile-lead${swapped !== null ? ' home-swap-up' : ''}`}
              aria-label={`${lead.tile.name} 주문으로`}
              onClick={() => onOpenInstrument(lead.tile.code)}
            >
              <LeadTile tile={lead.tile} />
            </button>
            <RemoveButton name={lead.tile.name} onRemove={() => remove(0)} />
          </div>
        ) : lead?.kind === 'stale' ? (
          <div className="home-tile-slot">
            {/* 마스터에 돌아오면 다시 눌리는 자리라 없애지 않고 **비활성**입니다 —
                까닭은 그 안의 한 마디가 말합니다. */}
            <button type="button" className="home-tile home-tile-lead" disabled>
              <StaleTile code={lead.code} lead />
            </button>
            <RemoveButton name={lead.code} onRemove={() => remove(0)} />
          </div>
        ) : (
          <button type="button" className="home-tile home-slot-empty" onClick={() => setPicking(0)}>
            + 눌러서 추가
          </button>
        )}

        {/* 열 이름은 목록 바로 위에 둡니다. 큰 타일은 이름·값·등락을 세로로
            쌓은 다른 배치라 이 열들이 없습니다 — 그 위에 두면 있지도 않은
            열을 가리키게 됩니다. */}
        {/* 머리글과 다섯 줄이 한 격자입니다. 줄마다 격자를 따로 잡으면 종목 열이
            줄마다 제 이름 폭이 되어 값 열이 줄 사이에서 어긋납니다. */}
        <div className="quote-table">
        <div className="quote-head">
          <span>종목</span>
          <span>현재가</span>
          {settleBased ? (
            <span title="그 거래일 주간 정산가 대비">정산가대비</span>
          ) : (
            <span>전일대비</span>
          )}
          <span>등락률</span>
        </div>

        <ul className="home-quote-list">
          {rest.map((item, index) => (
            <li key={item ? (item.kind === 'tile' ? item.tile.code : item.code) : `empty-${index}`}>
              {item?.kind === 'tile' ? (
                <>
                  <button
                    type="button"
                    className={`quote-row${swapped === index + 1 ? ' home-swap-down' : ''}`}
                    aria-label={`${item.tile.name} 크게 보기`}
                    onClick={() => swapToLead(index + 1)}
                  >
                    <QuoteRow tile={item.tile} />
                  </button>
                  <RemoveButton name={item.tile.name} onRemove={() => remove(index + 1)} />
                </>
              ) : item?.kind === 'stale' ? (
                <>
                  <button type="button" className="quote-row" disabled>
                    <StaleTile code={item.code} lead={false} />
                  </button>
                  <RemoveButton name={item.code} onRemove={() => remove(index + 1)} />
                </>
              ) : (
                <button
                  type="button"
                  className="quote-row home-slot-empty"
                  onClick={() => setPicking(index + 1)}
                >
                  + 눌러서 추가
                </button>
              )}
            </li>
          ))}
        </ul>
        </div>
          </>
        )}

        {/* 담을 종목은 마스터 전체에서 고릅니다 — 찾는 규칙은 상단 검색과
            같고, 담기는 것은 시세를 부를 수 있는 계약 하나입니다. */}
        {picking !== null && (
          <WatchPicker
            taken={shown.filter(Boolean)}
            recent={recent}
            onPick={(code) => add(picking, code)}
            onClose={() => setPicking(null)}
          />
        )}
      </section>
    </div>
  )
}

/* 카드가 채워지는 동안 자리를 잡아둡니다. 값이 들어올 때 화면이 흔들리지
 * 않도록 줄 수와 폭을 미리 잡습니다. */
function CardSkeleton({ lines }: { lines: number }) {
  return (
    <div className="home-skeleton" aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className="skeleton" style={{ width: i === 0 ? '60%' : '85%', height: i === 0 ? 24 : 12 }} />
      ))}
    </div>
  )
}
