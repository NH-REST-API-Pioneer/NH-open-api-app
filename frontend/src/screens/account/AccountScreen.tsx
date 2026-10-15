import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { addDays, daysBetween, kstDateDash } from '../../lib/kst'
import { ListHead, listFace, staleNote } from '../../lib/listFace'
import { Count, MINUS, Num, NumOrDash, currencyDigits, fracWidth, numberParts, signSpace, toneOf } from '../../lib/number'
import type {
  AccountOrder,
  OpenIntent,
  Position,
} from '../../lib/types'
import { expiryText } from '../../data/instruments'
import { MARKET_BADGE, NO_CODE_REASON } from '../../lib/labels'
import { useStoredState } from '../../lib/useStoredState'
import {
  depositMoney,
  isDomesticDeposit,
  retryDeposit,
  failedDaysOf,
  moreList,
  retryErrorDays,
  retryList,
  stopErrorDays,
  stopList,
  useDepositOnce,
  useListEntry,
  useListOnce,
  useMarketCredentialed,
  useReloadWhenShown,
  type DepositMarket,
  type OverseasView,
  type Period,
  type ServerOrder,
  type ServerExpiryPosition,
  type ServerOrderError,
  type ServerPosition,
  type ServerRealized,
} from '../../data/account'
import { assetsOf, realisedOf } from '../../data/depositHistory'
import { toOrder, toOrderError, toPosition } from '../../data/accountRows'
import { DepositPanel } from './DepositPanel'
import { TrendPanel } from './TrendPanel'
import { marketConfigured, useEnvironment } from '../../data/environment'
import './account.css'

/* 계좌 — 걸어둔 것과 들고 있는 것을 모아 보는 곳.
 *
 * 예탁자산·주문오류·누적손익·잔고는 종목에 매달 수 없는 계좌 단위 값이라
 * 다른 화면에 자리가 없습니다.
 *
 * 국내와 해외로 갈고, 그 안을 탭으로 나눕니다. 항목이 성격도 조회도 서로
 * 달라 한 화면에 쌓으면 무엇이 무엇인지 흐려집니다.
 *
 * 국내·해외 세그먼트는 상단 시장 띠와 같은 값입니다. 둘이 갈리면 주문한
 * 시장과 확인하는 잔고가 달라질 수 있습니다 — 상태는 하나이고 컨트롤이 둘입니다.
 *
 * 국내 탭 안에서는 주간과 야간을 갈지 않습니다. 갈면 야간에 낸 주문이 주간
 * 화면에서 안 보여, 사용자가 주문이 사라진 줄 알고 다시 냅니다 — 미체결이
 * 두 배가 됩니다. 그래서 한 표에 모으고 행에 배지를 답니다.
 *
 * 밀도는 넉넉한 쪽입니다. 계좌 숫자는 오래 들여다보는 값이 아니라
 * 확인하는 값이라, 행 간격을 벌리고 색은 손익에만 씁니다.
 */

type Market = 'domestic' | 'overseas'

/* 「예수금」이 아니라 「예탁자산」입니다. 조회 이름은 예수금이지만 화면에
 * 서는 값의 머리는 당일예탁자산금액이고, 예수금은 그중 현금 한 조각입니다.
 * 탭 이름이 부분을 가리키면 나머지가 안 보이는 것처럼 됩니다. */
const TABS: Record<Market, string[]> = {
  domestic: ['잔고', '예탁자산', '추이', '미체결', '주문오류'],
  overseas: ['잔고', '예탁자산', '추이', '미체결', '주문오류', '누적손익'],
}

/** 통화가 섞이므로 금액에는 늘 단위가 붙습니다. **코드를 모르면 아무것도 안
 *  답니다** — 무슨 돈인지 지어내지 않습니다.
 *
 *  소수 자릿수는 **줄의 통화**로 정합니다(`currencyDigits` — 엔은 0, 달러는 2).
 *  잔고 답에는 자릿수 칸이 없습니다. 코드를 모르면 값을 받은 그대로 적습니다. */
function Money({
  value,
  currency,
  signed,
}: {
  value: number
  currency: string
  signed?: boolean
}) {
  if (currency === 'KRW') {
    return (
      <>
        <Count value={value} signed={signed} />원
      </>
    )
  }
  if (!currency) return <Count value={value} signed={signed} />
  return (
    <>
      <Num value={value} decimals={currencyDigits(currency) ?? 2} signed={signed} /> {currency}
    </>
  )
}

/** `Money` 가 그리는 것과 같은 글자 — 칸이 좁아 말줄임될 때 마우스를 올리면
 *  보이는 전체 값입니다. */
function moneyLabel(value: number, currency: string, signed = false): string {
  if (currency === 'KRW') return `${numberParts(value, 0, null, signed)[0]}원`
  /* 통화를 모르면 `Count` 처럼 값을 반올림하지 않고 그대로 적습니다. */
  if (!currency) {
    const sign = value < 0 ? MINUS : signed && value > 0 ? '+' : ''
    return `${sign}${Math.abs(value).toLocaleString('ko-KR')}`
  }
  const [int, frac] = numberParts(value, currencyDigits(currency) ?? 2, null, signed)
  return `${int}${frac} ${currency}`
}

/** 손익은 이 화면에서 색을 쓰는 유일한 값입니다. */
function Tone({
  value,
  children,
}: {
  value: number
  children: React.ReactNode
}) {
  /* 0 은 본문색입니다 — 손익 0 은 본전이라 값이고, 흐림은 값이 없는 「—」의
     것입니다(`toneOf`). */
  return <span className={toneOf(value) || undefined}>{children}</span>
}

/** 계좌 요약 띠 — 어느 탭에 있든 답이 필요한 여섯.
 *
 *  **예수금 한 건에서 다 나옵니다.** 여섯을 각자 부르면 같은 값이 여러 번 오고,
 *  그중 하나만 실패하면 같은 화면의 숫자가 서로 안 맞습니다.
 *
 *  **탭과 상관없이 늘 서 있어야 하는 줄이라 화면에 들어올 때 부릅니다.** 다른
 *  탭들은 그 탭을 열 때만 부릅니다.
 */
function AccountBand({ market, view }: { market: DepositMarket; view?: OverseasView }) {
  const entry = useDepositOnce(market, view)
  /* 창이 다시 보일 때 예수금을 한 번 새로 받습니다 — 다른 창에 다녀온 사이의 변화가
     「마지막 갱신」 옛 시각 그대로 남지 않게 합니다. 화면에 들어올 때는 위 자리가
     이미 부릅니다. */
  useReloadWhenShown(() => retryDeposit(market, view), useMarketCredentialed(market))
  const value = entry.value
  const converted = market === 'overseas' && view?.mode !== 'by-currency'
  /* 시장·보기가 바뀌면 굴림을 처음으로 되돌립니다 — 칸 구성과 자릿수가 달라,
     앞 보기에서 밀어 둔 자리가 새 보기의 첫 칸을 가립니다. */
  const resetKey = `${market}.${JSON.stringify(view ?? null)}`

  if (value === null) {
    return (
      <div className="acct-band">
        <BandScroll resetKey={resetKey}>
          <dl className="acct-band-list" aria-label="계좌 요약">
            {entry.status === 'loading' ? (
              SUMMARY_LABELS[market].map((label) => (
                <div key={label} className="acct-band-cell">
                  <dt>{label}</dt>
                  <dd>
                    <span className="skeleton" style={{ minWidth: '8ch' }} />
                  </dd>
                </div>
              ))
            ) : (
              /* **문장은 한 번입니다.** 여섯 칸이 같은 사정이라 칸마다 같은 말을
                 세우면 그 길이가 그대로 소음이 됩니다. */
              <div className="acct-band-word">
                <span>
                  {entry.status === 'failed'
                    ? '예탁자산을 받지 못했습니다'
                    : '계좌를 아직 조회하지 않았습니다'}
                </span>
                {entry.failure === 'retry' && (
                  <button
                    type="button"
                    className="btn btn-quiet"
                    onClick={() => retryDeposit(market, view)}
                  >
                    다시
                  </button>
                )}
              </div>
            )}
          </dl>
        </BandScroll>
      </div>
    )
  }

  const domestic = isDomesticDeposit(value)
  const rows = domestic ? value.items : value.groups
  const singles = domestic ? null : new Map(value.items.map((row) => [row.key, row.value]))
  /* 해외 자릿수는 답이 실어 준 통화 자릿수가 먼저이고, 없으면 통화 코드로
     정합니다 — 원화 환산이면 원이라 0 입니다. */
  const decimals = domestic ? 0 : (value.decimals ?? currencyDigits(value.currency) ?? 2)
  const currency = domestic ? 'KRW' : value.currency

  const at = (key: string): number | null => {
    const row = rows.find((one) => one.key === key)
    if (row) return row.values[0] ?? null
    if (domestic) {
      const items = value.items.find((one) => one.key === key)
      return items?.values[0] ?? null
    }
    return singles?.get(key) ?? null
  }

  /* 칸 이름은 받는 중 뼈대와 같은 표(`SUMMARY_LABELS`)에서 읽습니다. */
  const labels = SUMMARY_LABELS[market]
  const values: { value: number | null; toned?: boolean; hint?: string }[] = [
    /* **추이 탭과 같은 접근자**입니다 — 그래프의 마지막 점과 이 숫자가 다르면
       어느 쪽을 믿어야 할지 알 수 없습니다. */
    { value: assetsOf(value) },
    { value: at('orderable') },
    { value: at('withdrawable') },
    { value: at('initialMargin') },
    { value: at('maintenanceMargin') },
    /* 국내는 **추이와 같은 순손익**입니다(`realisedOf`) — 서버의 손익총액 칸은 늘 0 으로
       와서 그날 손익을 말하지 못합니다. 무엇을 셈한 값인지는 이름에 마우스를 올리면
       나옵니다. */
    domestic
      ? {
          value: realisedOf(value).value,
          toned: true,
          hint: '선물정산차금 + 야간정산차금 − 수수료 − 야간수수료 · 정산 전에는 바뀔 수 있습니다',
        }
      : { value: singles?.get('unrealisedPl') ?? null, toned: true },
  ]
  const cells = values.map((cell, index) => ({ ...cell, label: labels[index] }))

  return (
    <div className="acct-band">
      <BandScroll resetKey={resetKey}>
        <dl className="acct-band-list" aria-label="계좌 요약">
          {cells.map((cell) => (
            <div key={cell.label} className="acct-band-cell">
              <dt title={cell.hint}>{cell.label}</dt>
              <dd>
                {cell.value === null ? (
                  <span className="dep-none">—</span>
                ) : cell.toned ? (
                  <Tone value={cell.value}>
                    {cell.value > 0 ? '+' : ''}
                    {depositMoney(cell.value, decimals, currency)}
                  </Tone>
                ) : (
                  depositMoney(cell.value, decimals, currency)
                )}
              </dd>
            </div>
          ))}
        </dl>
      </BandScroll>
      {/* **값이 언제 것인지.** 계좌 조회는 저절로 다시 받지 않아, 이 줄이 없으면
          보고 있는 수가 방금 것인지 아침 것인지 화면이 말하지 않습니다. 돈이
          아니라 시각이라 색도 부호도 없습니다. 모든 값의 시각이라 **굴림 밖에
          붙박이로** 둡니다 — 금액을 옆으로 밀어도 사라지지 않습니다. */}
      <dl className="acct-band-at">
        <div className="acct-band-cell">
          <dt>마지막 갱신</dt>
          <dd>
            {entry.at ?? <span className="dep-none">—</span>}
            {/* 원화로 합친 값이면 그렇다고 적습니다. 통화별 값과 숫자 모양이 같아,
                적지 않으면 어느 돈인지 띠만 보고는 모릅니다. */}
            {converted && <span className="acct-band-conv">원화 환산</span>}
          </dd>
        </div>
      </dl>
    </div>
  )
}

/** 요약 띠의 금액 칸들이 앉는 가로 굴림 영역.
 *
 *  **칸은 제 글자 폭 아래로 줄지 않습니다.** 창이 좁아 여섯이 다 들어가지 않으면
 *  칸을 겹치게 두는 대신 이 영역이 옆으로 굴러갑니다. 다 들어가면 굴림도,
 *  가장자리 흐림도, 초점 멈춤도 없습니다.
 *
 *  - 가려진 쪽 가장자리를 흐립니다 — 잘린 칸이 「값이 없는 칸」으로 보이지 않게
 *    합니다.
 *  - 세로 휠은 넘칠 때만 가로로 굴립니다. 이미 그쪽 끝이면 가로채지 않고 화면의
 *    세로 굴림으로 넘깁니다 — 끝에서 휠이 먹혀 버리지 않게 합니다.
 *  - 넘칠 때만 Tab 으로 닿고, 초점이 있으면 ←/→ 로 굴립니다. */
function BandScroll({ resetKey, children }: { resetKey: string; children: React.ReactNode }) {
  const [node, setNode] = useState<HTMLDivElement | null>(null)
  const [edge, setEdge] = useState({ over: false, start: true, end: true, bar: 0 })
  const measure = useRef(() => {})
  measure.current = () => {
    if (!node) return
    const room = node.scrollWidth - node.clientWidth
    const over = room > BAND_SLACK
    const start = node.scrollLeft <= BAND_SLACK
    const end = node.scrollLeft >= room - BAND_SLACK
    /* 막대 두께. 막대가 서면 이 영역 아래를 먹어, 칸이 그만큼 위로 올라가
       붙박이 「마지막 갱신」과 줄이 어긋납니다. 같은 두께를 위에도 비워 칸의
       높이를 막대가 없을 때와 같게 둡니다. */
    const bar = over ? node.offsetHeight - node.clientHeight : 0
    setEdge((held) =>
      held.over === over && held.start === start && held.end === end && held.bar === bar
        ? held
        : { over, start, end, bar },
    )
  }
  /* 값이 들어와 칸이 넓어지는 것은 이 영역의 크기를 바꾸지 않을 수 있어, 그릴
     때마다 한 번 잽니다. */
  useLayoutEffect(() => {
    measure.current()
  })
  useLayoutEffect(() => {
    if (node) node.scrollLeft = 0
    measure.current()
  }, [node, resetKey])
  useEffect(() => {
    if (!node) return
    const onScroll = () => measure.current()
    const onWheel = (event: WheelEvent) => {
      if (event.deltaX !== 0 || event.deltaY === 0 || event.ctrlKey) return
      const room = node.scrollWidth - node.clientWidth
      if (room <= BAND_SLACK) return
      if (event.deltaY < 0 && node.scrollLeft <= BAND_SLACK) return
      if (event.deltaY > 0 && node.scrollLeft >= room - BAND_SLACK) return
      event.preventDefault()
      /* 줄 단위 휠(deltaMode 1)은 줄 수로 옵니다. 한 줄을 16px 로 셉니다. */
      node.scrollLeft += event.deltaMode === 1 ? event.deltaY * 16 : event.deltaY
    }
    const sizes = new ResizeObserver(() => measure.current())
    sizes.observe(node)
    if (node.firstElementChild) sizes.observe(node.firstElementChild)
    node.addEventListener('scroll', onScroll, { passive: true })
    node.addEventListener('wheel', onWheel, { passive: false })
    return () => {
      sizes.disconnect()
      node.removeEventListener('scroll', onScroll)
      node.removeEventListener('wheel', onWheel)
    }
  }, [node])
  const face = [
    'acct-band-scroll',
    edge.over && !edge.start ? 'is-fade-start' : '',
    edge.over && !edge.end ? 'is-fade-end' : '',
  ]
    .filter(Boolean)
    .join(' ')
  return (
    <div
      ref={setNode}
      className={face}
      style={edge.bar > 0 ? { paddingTop: edge.bar } : undefined}
      tabIndex={edge.over ? 0 : undefined}
      role={edge.over ? 'region' : undefined}
      aria-label={edge.over ? '계좌 요약 — 좌우로 굴립니다' : undefined}
    >
      {children}
    </div>
  )
}

/* 굴림 끝 판정의 여유(px). 칸 폭이 소수라 끝까지 굴려도 한 끝이 1 안쪽에
   남습니다. */
const BAND_SLACK = 1

/* 요약 띠 여섯 칸의 이름. 받는 중 뼈대와 받은 뒤 칸이 **이 표 하나**에서 읽어,
   받기 전후로 칸 이름이 바뀌지 않습니다. 여섯째가 시장마다 다릅니다 — 국내는 그날의
   순손익(정산차금 − 수수료, 추이와 같은 셈)이고 해외는 응답의 평가손익이라, 같은
   이름으로 묶으면 다른 값을 같은 것으로 부르게 됩니다. */
const SUMMARY_LABELS: Record<DepositMarket, readonly string[]> = {
  domestic: ['예탁자산', '주문가능', '인출가능', '위탁증거금', '유지증거금', '오늘 순손익'],
  overseas: ['예탁자산', '주문가능', '인출가능', '위탁증거금', '유지증거금', '평가손익'],
}

/* 만기 — 종목 바로 다음입니다. 종목을 읽고 이어서 「언제까지 것인가」를
 * 읽는 순서라, 숫자 열 사이에 끼우면 값 훑는 흐름을 끊습니다.
 *
 * 강조하지 않습니다. 남은 날이 적어도 굵게·색으로 바꾸지 않습니다 —
 * 「만기가 가깝다」는 우리가 내리는 판정이고, 날짜와 남은 일수를 적는
 * 데까지가 우리 일입니다. */
function Expiry({ row, firstNotice = null }: { row: Position; firstNotice?: string | null }) {
  if (!row.expiry) {
    return (
      <span className="dead" title="종목 목록에서 만기를 찾지 못했습니다">
        —
      </span>
    )
  }
  /* **두 자리가 다른 모양으로 옵니다** — 해외는 응답이 `2026-09-10` 으로 주고,
     국내는 종목 마스터가 숫자만(`202609` 또는 `20260910`) 줍니다. 표에 적는
     모양은 한 곳에서 정합니다. */
  /* 둘째 줄은 **최초통보일**입니다(해외만, 만기 조회가 답했을 때). 매수 보유는 이
     날부터 인수도 통보를 받을 수 있어, 사흘 안으로 들어오면 그 줄만 경고색입니다.
     매도 보유는 통보를 받는 쪽이 아니라 칠하지 않습니다. 만기일보다 늦은 날은
     이 종목의 날로 읽을 수 없어 세우지 않습니다. */
  const notice = firstNotice !== null && firstNotice <= row.expiry ? firstNotice : null
  const days = notice === null ? null : calendarDaysUntil(notice)
  return (
    <>
      <span className="num">{expiryText(row.expiry)}</span>
      {row.daysLeft !== null && (
        <span className="acct-dday"> · D-{row.daysLeft}</span>
      )}
      {/* 두 날짜의 전체 글자는 이 줄에 마우스를 올렸을 때만 섭니다. 이 줄이 없는
          칸(국내·통보일 없음)은 전과 같은 모양 그대로입니다. */}
      {notice !== null && days !== null && (
        <span
          className={`acct-notice${row.side === 'long' && days <= 3 ? ' is-near' : ''}`}
          title={`만기일 ${row.expiry} · 최초통보일 ${notice}`}
        >
          최초통보 {notice.slice(5)} · {days >= 0 ? `D-${days}` : `D+${-days}`}
        </span>
      )}
    </>
  )
}

/** 오늘(한국 달력일)부터 그 날(`YYYY-MM-DD`)까지 남은 날. 오늘이면 0, 지났으면
 *  음수입니다. 시각은 보지 않습니다 — 통보일은 날 단위로 정해집니다. */
function calendarDaysUntil(date: string): number | null {
  if (!Number.isFinite(Date.parse(`${date}T00:00:00Z`))) return null
  return daysBetween(kstDateDash(), date)
}

/** 종목코드마다 만기 칸 둘째 줄에 적을 최초통보일. **둘째 줄을 세울지는 여기
 *  한 자리에서 정합니다** — `null` 이면 그 종목은 둘째 줄이 없습니다.
 *
 *  - **현금결제 종목은 세우지 않습니다.** 최초통보일은 실물을 인수할 의무가
 *    시작되는 날이라, 만기에 정산되고 끝나는 종목에는 경고할 일이 없습니다.
 *  - **최초통보일이 그 줄의 만기일과 같으면 세우지 않습니다.** 현금결제 종목의
 *    답에서 두 날이 같게 오는 것을 보았습니다 — 만기일과 같은 날은 따로 알릴
 *    날이 아닙니다.
 *  - 만기 조회는 체결 단위라 한 종목이 여러 줄입니다. **줄마다 날이나 결제 구분이
 *    다르거나 날이 빠진 줄이 섞이면 세우지 않습니다** — 어느 줄을 골라도 다른
 *    줄에는 틀린 말이 됩니다. */
function firstNoticeByCode(rows: readonly ServerExpiryPosition[]): Map<string, string | null> {
  const seen = new Map<string, { date: string | null; delivery: string; mixed: boolean }>()
  for (const row of rows) {
    const code = row.code?.trim() ?? ''
    if (!code) continue
    const date = row.firstNotice ?? null
    const delivery = row.delivery?.trim() ?? ''
    /* 만기일과 같은 날은 통보일로 읽지 않습니다. 둘 다 서버가 `YYYY-MM-DD` 로
       내는 글자라 글자로 견줍니다. */
    const notice = date !== null && date === (row.expiry ?? null) ? null : date
    const held = seen.get(code)
    seen.set(code, {
      date: notice,
      delivery,
      mixed: held !== undefined && (held.mixed || held.date !== notice || held.delivery !== delivery),
    })
  }
  const found = new Map<string, string | null>()
  for (const [code, one] of seen) {
    found.set(code, one.mixed || isCashSettled(one.delivery) ? null : one.date)
  }
  return found
}

/** 현금결제인지. NH 는 「현금」·「현금결제」 두 꼴을 씁니다. **모르는 글자와 빈
 *  값은 현금이 아닌 것으로 봅니다** — 실물 인수 경고를 잘못 숨기는 쪽이 경고가
 *  하나 더 서는 쪽보다 위험합니다.
 *
 *  만기 조회에서 실물 품목의 결제 구분 글자는 아직 표본으로 보지 못했습니다.
 *  같은 뜻의 상품 만기 조회 칸이 실물 품목에 「인수도」를 주는 것을 근거로 합니다. */
function isCashSettled(delivery: string): boolean {
  return delivery.startsWith('현금')
}

function PositionRow({
  row,
  firstNotice = null,
  onOpen,
}: {
  row: Position
  firstNotice?: string | null
  onOpen: (row: Position) => void
}) {
  /* 자릿수를 못 찾으면 폭을 잡아 둘 기준이 없습니다 — 그 줄의 값은 「—」라
     자리를 안 씁니다. */
  const price = fracWidth(row.decimals ?? 0, signSpace(row.productKind))
  /* 종목 마스터에서 코드를 못 찾은 줄은 **열 종목이 없습니다.** 줄은 그대로
     보이되 누르는 자리에서 빠집니다 — 보이는 것과 누를 수 있는 것은 다른
     물음이고, 눌러서 아무 일도 안 일어나는 줄은 조작이 안 먹은 것으로 읽힙니다. */
  const openable = row.code !== ''
  return (
    <tr
      className={openable ? 'row-click' : undefined}
      aria-disabled={openable ? undefined : true}
      onClick={openable ? () => onOpen(row) : undefined}
    >
      {/* 이 표에서 좁아지면 줄어드는 것은 이름입니다. 말줄임된 이름은 마우스를
          올리면 전체가 보이고, 바로 아래 코드 줄은 줄지 않습니다. */}
      <td className="col-text" title={row.name}>
        <span className="acct-name">{row.name}</span>
        <span className="acct-sub">
          {/* 모르는 시장 값이면 배지를 안 답니다 — 글자 없는 배지는 빈 조각입니다. */}
          {MARKET_BADGE[row.market] && <span className="badge">{MARKET_BADGE[row.market]}</span>}
          {/* **서버가 종류를 준 줄에만** 답니다. 두 만기가 걸린 줄은 수량·평가손익을
              한 다리의 것으로 읽으면 안 되어, 이름 아래에서 먼저 말해 줍니다. */}
          {row.productKind === 'spread' && <span className="badge">스프레드</span>}
          {/* 코드 자리를 비워 두지 않습니다. 빈 칸은 「값이 없다」가 아니라
              「아직 안 그렸다」로 읽히고, 이름 아래 시장 배지만 남으면 줄이
              반쯤 그려진 것처럼 보입니다. 왜 못 누르는지도 여기 붙습니다. */}
          {row.code || (
            <span className="dead" title={NO_CODE_REASON}>
              —<span className="hidden-note">{NO_CODE_REASON}</span>
            </span>
          )}
          {/* 이름이 마스터에서 온 것이 아니면 까닭 한 줄. 그 줄은 만기·자릿수도
              함께 비어 있습니다. */}
          {row.nameNote && <span className="hidden-note">{row.nameNote}</span>}
        </span>
      </td>
      <td className="col-text acct-expiry">
        <Expiry row={row} firstNotice={firstNotice} />
      </td>
      {/* 방향은 글자가 나르고 색은 거듭니다. 색만으로 구분하지 않습니다. */}
      <td className={`col-text ${row.side === 'long' ? 'up' : 'down'}`}>
        {row.side === 'long' ? '매수' : '매도'}
      </td>
      {/* **줄마다 오는 칸이 다릅니다.** 서버가 안 준 칸은 「—」입니다 — 0 으로
          채우면 「없다」가 「0 이다」가 됩니다. */}
      <td>{row.quantity === null ? <span className="dead">—</span> : <Count value={row.quantity} />}</td>
      <td style={price}>
        <NumOrDash value={row.avgPrice} decimals={row.decimals} />
      </td>
      <td style={price}>
        <NumOrDash value={row.lastPrice} decimals={row.decimals} />
      </td>
      {/* 열 폭을 넘는 한계 값(엔화 열 자리)은 말줄임되므로 전체 값을 곁에 둡니다. */}
      <td title={row.pl === null ? undefined : moneyLabel(row.pl, row.currency, true)}>
        {row.pl === null ? (
          <span className="dead">—</span>
        ) : (
          <Tone value={row.pl}>
            <Money value={row.pl} currency={row.currency} signed />
          </Tone>
        )}
      </td>
      <td style={fracWidth(2, 1)}>
        <NumOrDash value={row.plPct} decimals={2} signed toned suffix="%" />
      </td>
    </tr>
  )
}

function OrderRow({
  row,
  onOpen,
}: {
  row: AccountOrder
  onOpen: (row: AccountOrder) => void
}) {
  return (
    <tr>
      <td className="col-text num">{row.time}</td>
      <td className="col-text">
        <span className="acct-name">{row.name}</span>
        <span className="acct-sub">
          {MARKET_BADGE[row.market] && <span className="badge">{MARKET_BADGE[row.market]}</span>}
          {/* 주문 줄의 종류는 **서버가 그 칸을 준 줄에만** 섭니다(국내 미체결은
              스프레드 줄에 싣습니다). 안 주는 줄은 이름을 뜯어 짐작하지 않습니다. */}
          {row.productKind === 'spread' && <span className="badge">스프레드</span>}
          {/* **줄의 종류(정정·취소)는 이 표에 안 답니다.** 이 표는 살아 있는
              주문만 담아 「정정으로 낸 주문」이라는 사실이 설명할 것이 없고,
              같은 줄의 동작 칸에 「정정」 단추가 서 있어 한 낱말이 한 줄에서 두
              뜻이 됩니다. 그 표지가 일하는 자리는 원·정정·취소가 함께 남는
              주문체결상세(전체 조회)입니다. */}
          {row.orderType}
          {row.nameNote && <span className="hidden-note">{row.nameNote}</span>}
        </span>
      </td>
      {/* 이 화면의 색은 손익 몫입니다. 방향은 포지션 표와 같이 글자가 나릅니다. */}
      <td className="col-text">{row.side === 'buy' ? '매수' : '매도'}</td>
      <td style={fracWidth(row.decimals ?? 0, signSpace(row.productKind))}>
        {/* 시장가 주문은 주문가격이 없습니다. 0 으로 적으면 「0 원에 냈다」가
            됩니다. */}
        <NumOrDash value={row.price} decimals={row.decimals} />
      </td>
      <td title="체결 / 주문">
        <span className="num">
          {row.filled ?? '—'} / {row.quantity ?? '—'}
        </span>
      </td>
      <td className="col-text">
        <span className="badge">{row.source}</span>
      </td>
      <td className="col-text">
        <span className="acct-actions">
          {/* **이 칸은 까닭이 아니라 결과를 말합니다.** 어디서 낸 주문인지는 바로
              옆 출처 열이 이미 말했으므로, 여기에 매체 이름을 또 세우면 한 줄이
              같은 것을 두 번 말합니다. 출처 열이 접히는 주문체결상세에서만 이
              칸이 출처를 겸합니다 — 같은 규칙의 두 결과입니다.

              **낱말은 「잠김」입니다.** 이 표에 선 단추는 하나지만 **그 단추가 여는
              자리에서 정정도 취소도** 하므로, 「못 고침」은 절반만 말합니다. 우리가
              낼 수 없는 주문은 여기서 거둘 수도 없습니다.

              **출처 열과 이 칸은 붙여 읽는 짝입니다.** 「잠김」은 스스로 까닭을 말
              하지 않으므로 둘이 늘 함께 보여야 합니다. 가로로 미는 배치가 생겨
              출처 열이 밀려 나가면 이 칸이 매체 이름을 말해야 합니다.

              **수량을 모르는 주문도 같은 낱말입니다.** 까닭이 다르지만 이 칸이
              답할 것은 「여기서 무엇을 할 수 있나」 하나이고, 까닭은 그 까닭이 사는
              열이 말합니다 — 매체 탓이면 출처 열이, 수량을 모르면 체결 칸의 「—」가.
              낱말을 늘리면 이 칸이 다시 까닭을 말하기 시작합니다. */}
          {row.locked || row.quantity === null ? (
            <span className="badge">잠김</span>
          ) : (
            /* **초록을 안 씁니다.** 색이 붙으면 그 선택이 권장으로 읽히는데,
               정정은 권장할 동작이 아닙니다. 주문 화면의 같은 단추와 같은
               무게입니다 — 한 동작이 표마다 다른 무게로 서면 안 됩니다. */
            <button
              type="button"
              className="btn btn-quiet"
              onClick={() => onOpen(row)}
            >
              정정
            </button>
          )}
        </span>
      </td>
    </tr>
  )
}

/* ── 탭 하나가 조회 하나 ──────────────────────────────────
 *
 * **탭마다 제 자리에서 부릅니다.** 계좌 조회에는 초당 한도가 있어, 안 보는
 * 탭까지 미리 부르면 보는 탭이 밀립니다. 탭을 열면 그 탭이 서면서 부르고,
 * 안 열면 그 조회도 없습니다.
 */

function PositionsPanel({
  market,
  onOpen,
}: {
  market: DepositMarket
  onOpen: (row: Position) => void
}) {
  const overseas = market === 'overseas'
  const entry = useListOnce<ServerPosition>(market, 'positions')
  /* 최초통보일을 받는 만기 조회. **해외 잔고에서만** 부릅니다(국내는 목록 쪽에서
     막힙니다). 못 받았거나 늦게 오면 만기 칸의 첫 줄만 섭니다 — 표를 막지 않고,
     와도 줄 차례는 그대로입니다. */
  const expiries = useListOnce<ServerExpiryPosition>(market, 'expiry')
  const notices = overseas ? firstNoticeByCode(expiries.rows ?? []) : null
  const again = () => retryList(market, 'positions')
  const face = listFace(entry, '보유 중인 포지션이 없습니다', again, true)
  if (face) return face

  const rows = (entry.rows ?? []).map((row) => toPosition(row, overseas))
  return (
    <>
      {staleNote(entry)}
      {/* 잔고는 **물은 순간의** 값입니다. */}
      <ListHead
        label="지금 시점"
        entry={entry}
        onStop={() => stopList(market, 'positions')}
        onMore={() => moreList(market, 'positions')}
        onReload={again}
      />
      {/* **합계 줄을 걷었습니다.** 잔고 응답은 포지션 줄과 이어받기 열쇠
          뿐이라, 여기 서 있던 평가손익·매매손익·수수료·순손익은 **서버가
          주지 않는 값**이었습니다. 응답이 안 주면 우리가 말할 수 없습니다.

          **그 물음에 답하는 자리는 있습니다** — 손익과 수수료는 위 요약 띠의
          여섯째 칸과 예탁자산 탭이 예수금에서 받아 말합니다. 여기서 다시
          세우면 한 화면이 같은 값을 두 이름으로 말하게 됩니다. */}
      <div className="table-scroll">
        <table className="data-table rows-stacked acct-positions">
          {/* 종목 이름이 이 표에서 가장 긴 값입니다. 열을 고르게 나누면
              이름만 잘려서 무슨 종목인지 알 수 없게 됩니다. */}
          <colgroup>
            {/* 앞 여섯 열은 **합이 100%** 입니다. 붙박이 두 열을 뺀 나머지 폭을 이
                비율로 나눕니다 — 합이 100 보다 작으면 남는 폭이 붙박이 열에도
                나뉘어, 그 폭이 붙박이 자리와 어긋납니다. */}
            <col style={{ width: '33%' }} />
            <col style={{ width: '17%' }} />
            <col style={{ width: '9%' }} />
            <col style={{ width: '9%' }} />
            <col style={{ width: '16%' }} />
            <col style={{ width: '16%' }} />
            {/* 오른쪽에 붙박이는 두 열(평가손익·수익률)은 **px 로 못 박습니다.**
                붙박이 자리(`right`)가 뒤 열의 폭을 알아야 해서, 폭과 자리가 같은
                값(account.css 의 변수)을 읽습니다. */}
            <col style={{ width: 'var(--acct-pl-w)' }} />
            <col style={{ width: 'var(--acct-rate-w)' }} />
          </colgroup>
          <thead>
            <tr>
              <th className="col-text">종목</th>
              <th className="col-text">만기</th>
              <th className="col-text">방향</th>
              <th>수량</th>
              <th>평균가</th>
              {/* 국내·해외 모두 줄에 장중 현재가가 실려 옵니다(국내는 응답의
                  「종가」 칸이 장중에 현재가를 따라 움직입니다). 일반주문 화면의
                  미결제 표와 같은 이름입니다. */}
              <th>현재가</th>
              <th>평가손익</th>
              <th>수익률</th>
            </tr>
          </thead>
          <tbody>
            {/* **열쇠는 값이 아니라 자리입니다.** 종목 마스터에서 그 품목을 못
                찾으면 코드가 빈 문자열이라, 값으로 열쇠를 만들면 줄마다 같은
                열쇠가 되어 줄이 뒤섞입니다. */}
            {rows.map((row, index) => (
              <PositionRow
                key={`position-${index}`}
                row={row}
                firstNotice={notices?.get(row.code) ?? null}
                /* 잔고에서 종목을 누르는 것은 「이걸 어떻게 할까」입니다.
                   가장 흔한 답이 덜어내는 것이라 청산 모드로 엽니다. */
                onOpen={onOpen}
              />
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

function OpenOrdersPanel({
  market,
  onOpen,
}: {
  market: DepositMarket
  onOpen: (row: AccountOrder) => void
}) {
  const overseas = market === 'overseas'
  /* 미체결만 골라 받습니다. 주문내역 전체와 같은 주소인데 조회구분이 달라,
     담는 자리도 갈라 둡니다 — 안 갈면 주문 화면이 받아 둔 전체 목록을 이
     탭이 「이미 물어봤다」로 건너뜁니다. */
  const entry = useListOnce<ServerOrder>(market, 'orders', 'open')
  const again = () => retryList(market, 'orders', 'open')
  const face = listFace(entry, '미체결 주문이 없습니다', again, true)
  if (face) return face

  const rows = (entry.rows ?? []).map((row) => toOrder(row, overseas))
  return (
    <>
      {staleNote(entry)}
      <ListHead
        label="오늘 낸 주문"
        entry={entry}
        onStop={() => stopList(market, 'orders', 'open')}
        onMore={() => moreList(market, 'orders', 'open')}
        onReload={again}
      />
      {!overseas && <p className="acct-note">주간과 야간을 모아 봅니다</p>}
      <div className="table-scroll">
        <table className="data-table rows-stacked acct-orders">
          <colgroup>
            <col style={{ width: '9%' }} />
            <col style={{ width: '28%' }} />
            <col style={{ width: '8%' }} />
            <col style={{ width: '12%' }} />
            <col style={{ width: '10%' }} />
            <col style={{ width: '11%' }} />
            <col style={{ width: '22%' }} />
          </colgroup>
          <thead>
            <tr>
              <th className="col-text">시각</th>
              <th className="col-text">종목</th>
              <th className="col-text">구분</th>
              <th>가격</th>
              <th>체결</th>
              <th className="col-text">출처</th>
              <th className="col-text">동작</th>
            </tr>
          </thead>
          <tbody>
            {/* **주문번호는 열쇠가 못 됩니다** — 한 주문이 나눠 체결되면
                줄마다 같은 번호가 옵니다. 받은 자리로 셉니다. */}
            {rows.map((row, index) => (
              <OrderRow
                key={`order-${index}`}
                row={row}
                /* 미체결에서 누르는 것은 그 주문을 고치러 가는 것입니다.
                   대개 값을 다시 매기는 일이라 정정 모드로 엽니다. */
                onOpen={onOpen}
              />
            ))}
          </tbody>
        </table>
      </div>
      <p className="acct-footnote">
        우리 폼으로 낼 수 없는 주문은 여기서 정정·취소할 수 없습니다. 낸 곳에서
        거두세요
      </p>
    </>
  )
}

/* ── 주문오류 기간 ──────────────────────────────────────── */

type ErrorPreset = '오늘' | '5일' | '1개월' | '직접'

const ERROR_PRESETS: ErrorPreset[] = ['오늘', '5일', '1개월', '직접']

/** 한 번에 물을 수 있는 날 수(양끝 포함). 서버의 상한과 같습니다. */
const ERROR_MAX_DAYS = 31

/** 시장마다 고른 기간. **메모리에만 둡니다** — 탭이나 화면을 오가도 남고, 앱을
 *  다시 켜면 오늘로 돌아갑니다. 지난 기간을 보는 일은 그때그때의 물음이라 남겨
 *  둘 값이 아닙니다. */
const errorChoice = new Map<DepositMarket, { preset: ErrorPreset; from: string; to: string }>()

/** 두 날 사이의 날 수(양끝 포함). 순서가 뒤집혔으면 0 이하입니다. */
function spanDays(from: string, to: string): number {
  return daysBetween(from, to) + 1
}

/** 주문오류. 기간을 고르면 그 기간의 날을 서버가 하루씩 불러 합쳐 줍니다.
 *
 *  **날은 달력일입니다** — 서버가 주말·휴일을 건너뛰지 않습니다(해외는 한국시간
 *  토요일 새벽에도 체결이 있습니다). 「5일」은 오늘 포함 다섯 날, 「1개월」은 오늘
 *  포함 서른한 날입니다(달로 세면 한 번에 물을 수 있는 날을 넘는 달이 있습니다). */
function OrderErrorsPanel({ market }: { market: DepositMarket }) {
  /* 서버가 오늘을 한국시간으로 정합니다. */
  const today = kstDateDash()
  const [choice, setChoiceState] = useState(
    () => errorChoice.get(market) ?? { preset: '오늘' as ErrorPreset, from: today, to: today },
  )
  const setChoice = (next: { preset: ErrorPreset; from: string; to: string }) => {
    errorChoice.set(market, next)
    setChoiceState(next)
  }

  const from =
    choice.preset === '5일'
      ? addDays(today, -4)
      : choice.preset === '1개월'
        ? addDays(today, -(ERROR_MAX_DAYS - 1))
        : choice.from
  const to = choice.preset === '직접' ? choice.to : today
  const days = spanDays(from, to)
  /* 직접 고른 기간이 뒤집혔거나 너무 길면 **묻지 않습니다** — 서버가 거절할 물음을
     보내고 실패를 세우는 것보다, 칸 곁에서 바로 말하는 편이 할 일을 알려 줍니다. */
  const tooLong = choice.preset === '직접' && (days < 1 || days > ERROR_MAX_DAYS)
  const period = choice.preset === '오늘' ? undefined : { from: from.replace(/-/g, ''), to: to.replace(/-/g, '') }

  return (
    <>
      <div className="dep-head">
        <div className="seg">
          {ERROR_PRESETS.map((one) => (
            <button
              key={one}
              type="button"
              className="seg-item"
              aria-pressed={choice.preset === one}
              onClick={() => setChoice({ ...choice, preset: one })}
            >
              {one}
            </button>
          ))}
        </div>
        {choice.preset === '직접' && (
          <>
            <input
              className="control acct-date"
              type="date"
              value={choice.from}
              max={choice.to}
              aria-invalid={tooLong || undefined}
              aria-describedby={tooLong ? 'acct-errors-why' : undefined}
              onChange={(event) => setChoice({ ...choice, from: event.target.value })}
            />
            <span className="t-label">~</span>
            <input
              className="control acct-date"
              type="date"
              value={choice.to}
              min={choice.from}
              max={today}
              aria-invalid={tooLong || undefined}
              aria-describedby={tooLong ? 'acct-errors-why' : undefined}
              onChange={(event) => setChoice({ ...choice, to: event.target.value })}
            />
          </>
        )}
      </div>
      {tooLong ? (
        <p className="acct-errors-why" id="acct-errors-why">
          한 번에 {ERROR_MAX_DAYS}일까지 봅니다
        </p>
      ) : (
        <OrderErrorsList
          key={period ? `${period.from}~${period.to}` : 'today'}
          market={market}
          period={period}
          days={days}
        />
      )}
    </>
  )
}

/** 고른 기간의 막힌 주문 목록. 기간마다 따로 부르고 따로 담습니다. */
function OrderErrorsList({
  market,
  period,
  days,
}: {
  market: DepositMarket
  period: Period | undefined
  days: number
}) {
  const overseas = market === 'overseas'
  const entry = useListOnce<ServerOrderError>(market, 'errors', undefined, period)
  const again = () => retryList(market, 'errors', undefined, period)
  /* 기간을 바꾸거나 탭을 떠나면(이 목록이 내려가면) 다시 받기를 멈춥니다 — 안 보는
     기간의 날을 계속 묻지 않습니다. */
  useEffect(() => {
    return () => {
      if (period) stopErrorDays(market, period)
    }
    // 열쇠(기간)마다 새로 서는 목록이라 처음 값으로 충분합니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const mmdd = (text: string) => `${text.slice(4, 6)}-${text.slice(6, 8)}`
  const label = period ? `${mmdd(period.from)}~${mmdd(period.to)} 막힌 주문` : '오늘 막힌 주문'

  /* 기간은 **한 번의 물음**으로 오기 때문에 몇 날째인지 알 수 없습니다. 받는 동안은
     몇 날을 묻는지만 말합니다 — 길수록 오래 걸린다는 뜻이 전해집니다. */
  if (period && entry.rows === null && entry.status === 'loading') {
    return (
      <ListHead
        label={label}
        entry={entry}
        onStop={() => stopList(market, 'errors', undefined, period)}
        onMore={() => moreList(market, 'errors', undefined, period)}
        onReload={again}
        state={`받는 중 · ${days}일`}
      />
    )
  }
  const face = listFace(entry, period ? '이 기간에 막힌 주문이 없습니다' : '오늘 막힌 주문이 없습니다', again, true)
  if (face) return face

  const raw = entry.rows ?? []
  const rows = raw.map((row) => toOrderError(row, overseas))
  const failed = period ? failedDaysOf(entry.extra) : []
  const truncated = period !== undefined && entry.extra?.truncated === true
  const retrying = entry.retrying ?? null
  return (
    <>
      {staleNote(entry)}
      <ListHead
        label={label}
        entry={entry}
        onStop={() => stopList(market, 'errors', undefined, period)}
        onMore={() => moreList(market, 'errors', undefined, period)}
        onReload={again}
        state={retrying ? `${rows.length.toLocaleString('ko-KR')}줄 · 받는 중 ${retrying.done}/${retrying.total}일` : undefined}
      />
      {/* 기간 답이 못 받은 날·잘린 앞 날을 말합니다. **빈 날은 말하지 않습니다** —
          주문이 없던 날은 막힌 주문도 없는 것이 맞습니다. */}
      {(failed.length > 0 || truncated) && (
        <p className="acct-errors-note">
          {failed.length > 0 && (
            <>
              {failed.length}일은 받지 못했습니다
              <button
                type="button"
                className="btn btn-quiet"
                aria-disabled={retrying !== null || undefined}
                title={failed.map((one) => `${one.date} ${one.reason}`).join('\n')}
                onClick={() => period && retrying === null && void retryErrorDays(market, period)}
              >
                {retrying ? '받는 중' : '다시 받기'}
              </button>
            </>
          )}
          {truncated && <span>앞 날은 다 받지 못했습니다</span>}
        </p>
      )}
      {/* 표가 아니라 목록입니다. 열을 맞춰 비교할 값이 아니라
          「무엇을 하려다 왜 막혔나」를 한 줄로 읽는 자료입니다. */}
      <ul className={`acct-errors${period ? ' is-dated' : ''}`}>
        {/* **국내 응답에는 주문번호가 없습니다.** 열쇠는 받은 자리로 셉니다. */}
        {rows.map((row, index) => (
          <li key={`error-${index}`}>
            <span className="acct-error-time num">
              {/* 기간이면 날짜를 앞에 붙입니다 — 여러 날의 줄이 섞여 시각만으로는
                  어느 날인지 모릅니다. */}
              {period && raw[index]?.date ? `${String(raw[index].date).slice(5)} ` : ''}
              {row.time || <span className="dead">—</span>}
            </span>
            <span>
              <span className="acct-name">
                {row.name}
                {row.nameNote && <span className="hidden-note">{row.nameNote}</span>}
              </span>
              {/* **주문번호는 해외에만 옵니다.** 국내 응답에는 칸 자체가 없어
                  그 줄은 이 자리가 비어 있습니다 — 받은 것은 보이고 안 온 것만
                  빕니다. 목록이라 열 머리가 없어, 한쪽 줄이 더 아는 것이 됩니다.

                  **누르는 자리는 아닙니다.** 번호를 안다고 갈 곳이 있는 것은
                  아니어서 — 그 번호로 여는 화면이 아직 없습니다. 거부된 주문은
                  체결도 미체결도 아닐 수 있어 주문 목록으로 보내도 없을 수
                  있습니다. 그 화면이 생기면 그때 누르는 자리가 됩니다. */}
              {row.id && (
                <span className="acct-sub">
                  <span>주문번호</span>
                  <span className="num">{row.id}</span>
                </span>
              )}
            </span>
            <span className="acct-error-message">{row.message}</span>
          </li>
        ))}
      </ul>
    </>
  )
}

/** 해외 누적손익. 줄 하나가 **품목 × 품목 통화**이고, 품목 줄의 금액은 **그
 *  품목의 통화**로 옵니다. 환산 통화(`cvs_cur_cd`)로 바뀌어 오는 것은 합계 줄
 *  뿐입니다. 줄마다 돈이 다르므로 금액 열 머리에는 단위를 적지 않고, 어느 돈인지는
 *  「통화」 열이 줄마다 말합니다.
 *
 *  **총합은 우리가 더하지 않습니다.** 서버가 목록에서 빼서 따로 냅니다. */
function RealizedPanel({
  period,
  from,
  to,
  onFrom,
  onTo,
  view,
}: {
  period: Period
  from: string
  to: string
  onFrom: (value: string) => void
  onTo: (value: string) => void
  view: OverseasView
}) {
  /* 통화별이면 **USD 로** 묻습니다 — 이 조회가 받는 환산 통화는 USD·원화 둘뿐입니다.
     원화 환산이면 아무것도 안 보내 서버 기본(원화)을 씁니다. */
  const byCurrency = view.mode === 'by-currency'
  const conversion = byCurrency ? 'USD' : undefined
  const entry = useListOnce<ServerRealized>('overseas', 'cumulative', undefined, period, conversion)
  const again = () => retryList('overseas', 'cumulative', undefined, period, conversion)
  const total = (entry.extra?.total ?? null) as ServerRealized | null
  /* 금액의 통화는 **답이 말한 환산 통화**를 먼저 씁니다. 답에 없으면 우리가 보낸
     값입니다(안 보냈으면 서버 기본 원화). */
  const said = entry.extra?.conversionCurrency
  const amountCurrency = typeof said === 'string' && said !== '' ? said : (conversion ?? 'KRW')

  const head = (
    /* 조회 입력에 시작·종료가 있습니다. 기본은 이번 달 — 사용자가 고르지 않은
       기간의 값을 「전체」라고 부르면, 실제로 무엇이 들어 있는지 화면이 말하지
       않게 됩니다. */
    <div className="dep-head">
      <label className="dep-convert">
        <span className="control-label">기간</span>
        <input
          className="control acct-date"
          type="date"
          value={from}
          max={to}
          onChange={(event) => onFrom(event.target.value)}
        />
      </label>
      <span className="t-label">~</span>
      <input
        className="control acct-date"
        type="date"
        value={to}
        min={from}
        onChange={(event) => onTo(event.target.value)}
      />
      <span className="as-of">조회일 기준</span>
      {/* 고른 통화로는 물을 수 없는 자리라, 무엇으로 보이는지 적습니다. */}
      {byCurrency && view.currency !== 'USD' && (
        <span className="acct-view-note">누적손익은 USD·원화로만 조회됩니다</span>
      )}
    </div>
  )

  const face = listFace(entry, '이 기간에 쌓인 손익이 없습니다', again)
  if (face) {
    /* 기간 입력은 값이 없을 때도 서 있어야 합니다 — 없으면 다른 기간을 물어볼
       길이 사라져, 「없습니다」가 마지막 말이 됩니다. */
    return (
      <>
        {head}
        {face}
      </>
    )
  }

  const rows = entry.rows ?? []
  return (
    <>
      {head}
      {staleNote(entry, again)}
      <div className="table-scroll">
        <table className="data-table rows-base acct-realized">
          <thead>
            <tr>
              <th className="col-text">품목</th>
              <th className="col-text">통화</th>
              <th>실현손익</th>
              <th>평가손익</th>
              <th>수수료</th>
              <th>순손익</th>
            </tr>
          </thead>
          <tbody>
            {/* 열쇠는 값이 아니라 자리입니다 — 같은 품목이 통화만 달리해 두 줄로
                올 수 있어, 값으로 만든 열쇠가 겹칩니다. */}
            {rows.map((row, index) => (
              <RealizedRow key={`realized-${index}`} row={row} currency={row.currency ?? null} />
            ))}
          </tbody>
          {total !== null && !byCurrency && (
            /* **합계는 서버가 낸 줄입니다.** 우리가 더하지 않습니다 — 통화가
               섞여 오므로 그냥 더하면 다른 돈을 한 숫자로 만듭니다.
               합계 줄은 **원화 환산으로 볼 때만** 세웁니다. 통화별로 보는 중에
               여러 통화를 합친 한 숫자가 서면 보기의 약속과 어긋납니다.
               합계의 통화는 **우리가 물은 환산 통화**입니다 — 답의 합계 줄에 적힌
               통화 칸은 환산 전 통화로 와서 금액과 맞지 않습니다. */
            <tfoot>
              <RealizedRow row={total} label="원화 환산 합계" currency={amountCurrency} />
            </tfoot>
          )}
        </table>
      </div>
    </>
  )
}

/** 누적손익 한 줄. 합계 줄도 같은 모양이라 같은 것이 그립니다. `currency` 는
 *  **그 줄 금액의 통화**입니다 — 「통화」 칸에 적고, 금액의 소수 자릿수도 이것으로
 *  정합니다. 품목 줄은 품목의 통화, 합계 줄은 환산 통화입니다. */
function RealizedRow({
  row,
  label,
  currency,
}: {
  row: ServerRealized
  label?: string
  currency: string | null
}) {
  const name = label ?? row.productName ?? row.productCode ?? ''
  return (
    <tr>
      <td className="col-text">{name || <span className="dead">—</span>}</td>
      <td className="col-text">{currency || <span className="dead">—</span>}</td>
      <td>
        <Toned value={row.realisedPl ?? null} currency={currency} />
      </td>
      <td>
        <Toned value={row.unrealisedPl ?? null} currency={currency} />
      </td>
      <td>
        <Plain value={row.fee ?? null} currency={currency} />
      </td>
      <td>
        <Toned value={row.netPl ?? null} currency={currency} />
      </td>
    </tr>
  )
}

/** 누적손익 표의 금액 한 칸. 없으면 「—」입니다. 소수 자릿수는 **금액의 통화**로
 *  정하고(`currencyDigits`), 통화를 모르면 값을 받은 그대로 적습니다. */
function Plain({
  value,
  currency,
  signed,
}: {
  value: number | null
  currency?: string | null
  signed?: boolean
}) {
  if (value === null) return <span className="dead">—</span>
  const digits = currencyDigits(currency)
  if (digits === null) return <Count value={value} signed={signed} />
  return <Num value={value} decimals={digits} signed={signed} />
}

/** 손익 한 칸. 없으면 「—」이고, 있으면 방향색이 붙습니다. */
function Toned({ value, currency }: { value: number | null; currency?: string | null }) {
  if (value === null) return <span className="dead">—</span>
  return (
    <Tone value={value}>
      <Plain value={value} currency={currency} signed />
    </Tone>
  )
}

/* ── 해외 통화 보기 ────────────────────────────────────── */

/** 남기는 모양. 원화 환산으로 볼 때도 고른 통화를 들고 있어, 통화별로 돌아오면
 *  그 통화가 그대로 섭니다. */
interface StoredView {
  mode: 'by-currency' | 'converted'
  currency: string
}

const VIEW_KEY = 'nh.account.overseas.view'
const DEFAULT_VIEW: StoredView = { mode: 'by-currency', currency: 'USD' }

/** 남긴 값을 읽습니다. 모양이 틀리면(모르는 보기, 세 글자 대문자가 아닌 통화)
 *  기본값입니다 — 틀린 값으로 물으면 서버가 거절하고 화면이 빕니다. */
function readView(raw: unknown): StoredView {
  const value = (raw ?? {}) as Partial<StoredView>
  const mode = value.mode === 'by-currency' || value.mode === 'converted' ? value.mode : null
  const currency = typeof value.currency === 'string' && /^[A-Z]{3}$/.test(value.currency) ? value.currency : null
  if (mode === null || currency === null) return DEFAULT_VIEW
  return { mode, currency }
}

/** 고를 수 있는 통화. USD 가 늘 맨 앞이고 나머지는 글자 차례입니다. */
function currencyChoices(codes: (string | null | undefined)[]): string[] {
  const rest = new Set<string>()
  for (const code of codes) {
    const one = (code ?? '').trim().toUpperCase()
    if (/^[A-Z]{3}$/.test(one) && one !== 'USD') rest.add(one)
  }
  return ['USD', ...[...rest].sort()]
}

/** 계좌 머리의 통화 보기 전환. 시장 전환과 같은 꼴(둘 중 하나)이고, 통화별이면
 *  곁에 통화를 고르는 칸이 섭니다. 고를 통화가 하나뿐이면 칸 대신 글자입니다.
 *
 *  **고를 통화를 알려고 해외 잔고를 부릅니다** — 잔고 탭과 같은 자리라 두 번
 *  나가지 않습니다. */
function OverseasViewPicker({
  saved,
  shown,
  currencies,
  onChange,
}: {
  saved: StoredView
  shown: OverseasView
  currencies: string[]
  onChange: (next: StoredView) => void
}) {
  useListOnce<ServerPosition>('overseas', 'positions')
  const byCurrency = shown.mode === 'by-currency'
  const current = shown.mode === 'by-currency' ? shown.currency : saved.currency
  /* 잔고를 받기 전에는 남긴 통화가 목록에 없을 수 있습니다. 보이는 통화는 늘
     고를 수 있게 넣어 둡니다. */
  const options = currencies.includes(current) ? currencies : [...currencies, current]
  return (
    <div className="acct-view">
      <div className="seg seg-even acct-view-mode">
        <button
          type="button"
          className="seg-item"
          aria-pressed={byCurrency}
          onClick={() => onChange({ ...saved, mode: 'by-currency' })}
        >
          통화별
        </button>
        <button
          type="button"
          className="seg-item"
          aria-pressed={!byCurrency}
          onClick={() => onChange({ ...saved, mode: 'converted' })}
        >
          원화 환산
        </button>
      </div>
      {byCurrency &&
        (options.length > 1 ? (
          <select
            className="control acct-view-currency"
            aria-label="통화"
            value={current}
            onChange={(event) => onChange({ mode: 'by-currency', currency: event.target.value })}
          >
            {options.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </select>
        ) : (
          <span className="acct-view-code">{current}</span>
        ))}
    </div>
  )
}

interface Props {
  /** 계좌가 보는 시장. 앱이 따로 기억합니다 — 일반주문·종목 화면의 시장을 따라가지
   *  않고, 여기서 바꿔도 그 화면들은 그대로입니다. */
  market: Market
  onMarketChange: (market: Market) => void
  onOpenInstrument: (
    code: string,
    intent?: OpenIntent,
  ) => void
  /* 탭을 화면 밖에서 들고 있습니다. 다른 화면에서 「미체결을 보러」 들어오는
     길이 있어, 계좌가 탭을 혼자 쥐고 있으면 늘 첫 탭으로만 열립니다. */
  tab: string
  onTabChange: (tab: string) => void
  onOpenSettings: () => void
}

export function AccountScreen({
  market,
  onMarketChange,
  onOpenInstrument,
  onOpenSettings,
  tab,
  onTabChange,
}: Props) {
  /* 보고 있는 시장에 인증 정보가 없는지. 그러면 조회가 성립하지 않습니다 —
     「잠시 뒤 다시」가 아니라 「설정에서 넣으세요」가 맞는 말입니다. **시장마다
     따로 가릅니다** — 한 시장만 쓰는 사람의 찬 시장까지 막으면 쓸 수 있는 계좌를
     못 봅니다. 설정이나 접속 환경을 아직 모르면 「없다」고 하지 않습니다. */
  const { config } = useEnvironment()
  const configEnv = config?.active_environment ?? null
  const needsCredentials =
    config !== null && configEnv !== null && !marketConfigured(config, configEnv, market)
  /* 누적손익 조회 기간(`inq_strt_dt` · `inq_ed_dt`). 기본은 이번 달입니다 —
     「전체」로 두면 화면이 무엇을 담고 있는지 말하지 않게 됩니다. 달과 오늘은
     한국 달력입니다. */
  const [from, setFrom] = useState(() => `${kstDateDash().slice(0, 8)}01`)
  const [to, setTo] = useState(() => kstDateDash())
  /* 서버가 받는 모양은 구분 기호 없는 여덟 자리입니다. 칸이 쓰는 모양과 달라
     보내기 직전에 한 번만 바꿉니다. */
  const period: Period = { from: from.replace(/-/g, ''), to: to.replace(/-/g, '') }

  const overseas = market === 'overseas'
  const tabs = TABS[market]
  const active = tabs.includes(tab) ? tab : tabs[0]

  /* 해외 금액을 보는 통화. 고른 것을 남깁니다(이 열쇠는 새로 생긴 것이라 옮겨 올
     옛 값이 없습니다). 모양이 틀린 값은 기본(통화별 USD)으로 읽습니다. */
  const [storedView, setStoredView] = useStoredState<unknown>(VIEW_KEY, DEFAULT_VIEW)
  const saved = readView(storedView)
  /* 고를 수 있는 통화 — 해외 잔고 줄의 통화와 받아 둔 누적손익 줄의 통화, 그리고
     USD. **읽기만 합니다**: 잔고는 머리의 전환이 부르고, 누적손익은 그 탭이 부릅니다. */
  const heldPositions = useListEntry<ServerPosition>('overseas', 'positions')
  const heldUsd = useListEntry<ServerRealized>('overseas', 'cumulative', undefined, period, 'USD')
  const heldKrw = useListEntry<ServerRealized>('overseas', 'cumulative', undefined, period)
  const currencies = currencyChoices([
    ...(heldPositions.rows ?? []).map((row) => row.currency),
    ...(heldUsd.rows ?? []).map((row) => row.currency),
    ...(heldKrw.rows ?? []).map((row) => row.currency),
  ])
  /* 남긴 통화가 목록에 없으면 **화면만** 첫 통화로 봅니다. 남긴 값은 덮지 않습니다 —
     그 통화의 줄이 다시 생기면 사용자가 고른 대로 돌아가야 합니다. 잔고를 아직
     못 받았으면 목록을 모르므로 남긴 통화로 먼저 묻습니다. */
  const shownCurrency =
    heldPositions.rows === null || currencies.includes(saved.currency) ? saved.currency : currencies[0]
  const view: OverseasView =
    saved.mode === 'converted' ? { mode: 'converted' } : { mode: 'by-currency', currency: shownCurrency }

  const open = (code: string, intent?: OpenIntent) => onOpenInstrument(code, intent)

  const pickMarket = (next: Market) => {
    onMarketChange(next)
    if (!TABS[next].includes(tab)) onTabChange(TABS[next][0])
  }

  /* 탭 이름 옆 건수를 위해 **들어올 때 둘을 미리 부릅니다.**
     배지는 훑는 장치라, 열어야 아는 배지는 제 일을 못 합니다 — 「열기 전에
     안다」가 배지가 있는 까닭입니다. 예수금까지 셋이라 계좌의 초당 한도(열) 안
     입니다. 열어 둔 탭이 제 자리에서 한 번 더 부르는 것은 「탭을 열면 새 값」이
     라 그대로 둡니다. */
  const openOrders = useListOnce<ServerOrder>(market, 'orders', 'open')
  const orderErrors = useListOnce<ServerOrderError>(market, 'errors')

  const badgeFor = (name: string): string | null => {
    /* 인증 정보가 없으면 건수도 없습니다. 조회가 성립하지 않는데 「미체결 2」가
       서 있으면, 탭을 열기 전에 이미 틀린 것을 읽은 셈입니다. */
    if (needsCredentials) return null
    const entry =
      name === '미체결' ? openOrders : name === '주문오류' ? orderErrors : null
    if (entry === null) return null
    /* **배지는 건수만 말합니다.** 못 받았으면 안 답니다 — 건수를 모르는데 「0」을
       세우면 없다고 말하는 것이 되고, 배지 하나가 규모와 상태 두 뜻을 갖게
       됩니다. 못 받았다는 말은 그 탭을 열었을 때 그 안이 합니다.
       **저절로 다시 부르지 않습니다** — 되풀이하면 사용자 모르게 호출 예산을
       먹으면서 배지는 여전히 비어 있어, 아무것도 달라진 것이 없어 보입니다. */
    if (entry.rows === null) return null
    return String(entry.rows.length)
  }

  const panel = () => {
    /* 인증 정보가 없으면 「못 가져왔다」가 아닙니다. 다시 눌러도 같은 자리에
       머물게 되므로, 무엇이 없는지와 어디서 넣는지를 말합니다. 조회 자체가
       성립하지 않으니 아래 탭들도 세우지 않습니다 — 세우면 그 자리에서
       부릅니다. */
    if (needsCredentials) {
      return (
        <div className="notice">
          <p className="notice-title">인증 정보가 없습니다</p>
          <p className="notice-reason">설정에서 인증 정보를 입력하세요</p>
          <button
            type="button"
            className="btn btn-primary notice-action"
            onClick={onOpenSettings}
          >
            설정 열기
          </button>
        </div>
      )
    }

    if (active === '잔고') {
      return (
        <PositionsPanel
          market={market}
          onOpen={(row) => open(row.code, { kind: 'close', position: row })}
        />
      )
    }

    if (active === '예탁자산') {
      /* **통화별 보기를 이번에 걷었습니다.** 그 화면이 그리던 통화마다의 잔고는
         서버에 물어본 값이 아니라 화면이 들고 있던 값이었습니다. 서버에 환산
         구분을 바꿔 다시 물어야 나오는 자리라, 물어볼 길을 붙이기 전에는
         지어낸 값을 세우지 않습니다. 환산은 서버가 합니다. */
      return <DepositPanel market={market} view={overseas ? view : undefined} />
    }

    /* 「추이」는 **날마다 물어 모은 값**입니다 — 다른 탭이 「지금 시점」이나
       「하루치」를 보이는 것과 다릅니다. 그 사실은 탭 안이 줄로 말합니다. */
    if (active === '추이') {
      return <TrendPanel market={market} byCurrency={overseas && view.mode === 'by-currency'} />
    }

    if (active === '미체결') {
      return (
        <OpenOrdersPanel
          market={market}
          onOpen={(row) => open(row.code, { kind: 'amend', order: row })}
        />
      )
    }

    if (active === '주문오류') return <OrderErrorsPanel key={market} market={market} />

    if (active === '누적손익') {
      return (
        <RealizedPanel
          period={period}
          from={from}
          to={to}
          onFrom={setFrom}
          onTo={setTo}
          view={view}
        />
      )
    }

    return null
  }

  return (
    <div className="account">
      <div className="acct-bar">
        <h1 className="t-screen">계좌</h1>
        {/* 「둘 중 하나」라 균등 폭입니다. 아래 탭은 「여럿 중 하나」라 내용 폭이고,
            모양이 갈려서 어느 쪽이 바깥 선택인지 보입니다. */}
        <div className="seg seg-even acct-market">
          <button
            type="button"
            className="seg-item"
            aria-pressed={!overseas}
            onClick={() => pickMarket('domestic')}
          >
            국내
          </button>
          <button
            type="button"
            className="seg-item"
            aria-pressed={overseas}
            onClick={() => pickMarket('overseas')}
          >
            해외
          </button>
        </div>
        {/* **해외일 때만 그립니다**(국내에는 통화 구분이 없습니다). 인증 정보가
            없으면 물을 수 없으니 세우지 않습니다. */}
        {overseas && !needsCredentials && (
          <OverseasViewPicker
            saved={saved}
            shown={view}
            currencies={currencies}
            onChange={setStoredView}
          />
        )}
      </div>

      {/* 탭을 옮겨도 그대로 남습니다. 어느 탭에 있든 답이 필요한 여섯이라,
          탭을 옮겨서 확인해야 한다면 그건 늘 참인 값이 아니라 숨겨 둔 값입니다.

          인증 정보가 없으면 이 줄도 없습니다 — 아래에서는 「조회할 수 없다」고
          말하는데 위에 예탁자산이 서 있으면, 둘 중 하나는 거짓말입니다. */}
      {!needsCredentials && (
        <AccountBand market={overseas ? 'overseas' : 'domestic'} view={overseas ? view : undefined} />
      )}

      <div className="tabs tabs-inline acct-tabs">
        {tabs.map((item) => (
          <button
            key={item}
            type="button"
            className="tab"
            aria-current={item === active}
            onClick={() => onTabChange(item)}
          >
            {item}
            {badgeFor(item) && (
              <span className="badge tab-badge">{badgeFor(item)}</span>
            )}
          </button>
        ))}
      </div>

      <section className="acct-panel" aria-label={active}>
        {panel()}
      </section>
    </div>
  )
}
