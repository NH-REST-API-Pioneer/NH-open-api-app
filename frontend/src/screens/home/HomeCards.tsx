import {
  depositMoney,
  isDomesticDeposit,
  retryList,
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

/** 만기 관리 카드의 한 줄 — 만기가 다가오는 보유 종목.
 *
 *  현금결제는 만기에 정산되고 끝이지만 실물 인수도는 최초통보일을 넘기면 실제로
 *  물건을 받습니다. 급이 달라서 줄을 가릅니다. **아직 채우는 조회가 없어** 목록은
 *  비어 있고, 이 모양은 잔고 조회가 붙을 때 그 응답에 맞춰 다시 봅니다. */
export interface ExpiryRow {
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
export function AccountCardBody({ entry, onRetry }: { entry: DepositEntry; onRetry: () => void }) {
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
export function OrdersCard({ onGoOrders }: { onGoOrders: () => void }) {
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

/* 카드가 채워지는 동안 자리를 잡아둡니다. 값이 들어올 때 화면이 흔들리지
 * 않도록 줄 수와 폭을 미리 잡습니다. */
export function CardSkeleton({ lines }: { lines: number }) {
  return (
    <div className="home-skeleton" aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className="skeleton" style={{ width: i === 0 ? '60%' : '85%', height: i === 0 ? 24 : 12 }} />
      ))}
    </div>
  )
}
