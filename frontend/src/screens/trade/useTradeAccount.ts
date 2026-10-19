import { useMemo } from 'react'
import type { Fill, OpenOrder, Position, Quote } from '../../lib/types'
import { useListOnce, type DepositMarket, type ServerOrder, type ServerPosition } from '../../data/account'
import { toPosition, toTradeRow } from '../../data/accountRows'
import { mergedPositionList } from './tradeScreenUtils'

/** 주문 대상 시장의 미체결·체결·잔고 목록. */
export function useTradeAccount({
  activeOverseas,
  shownQuote,
}: {
  activeOverseas: boolean
  shownQuote: Quote
}) {
  /* 계좌 조회는 시장마다 다른 계좌입니다. 주문 대상 종목이 속한 쪽을 봅니다 —
     화면의 시장 범위가 아니라 「지금 무엇을 주문하는가」입니다. */
  const accountMarket: DepositMarket = activeOverseas ? 'overseas' : 'domestic'

  /* **주문·체결 목록과 미결제약정은 계좌 조회에서 옵니다.** 두 카드가 늘 서 있는
     화면이라 들어올 때 부릅니다. 계좌 화면의 미체결 탭과는 조회구분이 달라
     (여기는 전체, 거기는 미체결만) 담는 자리도 갈립니다. */
  const orderList = useListOnce<ServerOrder>(accountMarket, 'orders', 'all')
  /* **미결제약정은 계좌 전체입니다** — 인증 정보가 찬 시장 모두의 잔고를 한 표에
     둡니다. 해외 종목을 보다가도 국내 보유를 청산하러 갈 수 있어야 합니다. 시장마다
     계좌 화면과 같은 목록 저장소를 읽고, 인증 정보가 없는 시장은 부르지 않습니다
     (`withheld`). */
  const domesticPositions = useListOnce<ServerPosition>('domestic', 'positions')
  const overseasPositions = useListOnce<ServerPosition>('overseas', 'positions')
  /* 보고 있는 종목의 시장이 먼저입니다. 청산하러 오는 줄은 대개 지금 보는 쪽입니다. */
  const positionSides = (
    accountMarket === 'overseas'
      ? [
          { market: 'overseas' as const, entry: overseasPositions },
          { market: 'domestic' as const, entry: domesticPositions },
        ]
      : [
          { market: 'domestic' as const, entry: domesticPositions },
          { market: 'overseas' as const, entry: overseasPositions },
        ]
  ).filter((side) => !side.entry.withheld)
  const positionList = mergedPositionList(
    positionSides.map((side) => side.entry),
    accountMarket === 'overseas' ? overseasPositions : domesticPositions,
  )
  /* 한 시장의 사정을 **그 시장 이름으로** 말하는 줄들. 다른 시장 줄이 섰을 때만
     섭니다 — 표 전체를 「받지 못했습니다」로 덮으면 받은 줄까지 가리고, 표 전체의
     「지난 값」 문장은 새로 받은 시장의 줄까지 옛것으로 읽히게 합니다.
     `missing` 은 받은 적 없이 못 받은 시장, `stale` 은 받아 둔 줄은 있는데 새로
     받기에 실패한 시장입니다(받은 시장이 모두 그러면 표 전체 문장이 대신합니다). */
  const receivedSides = positionSides.filter((side) => side.entry.rows !== null)
  const allStale = receivedSides.every((side) => side.entry.failure !== null)
  const positionNotes =
    positionList.rows === null
      ? []
      : positionSides.flatMap((side): { side: (typeof positionSides)[number]; kind: 'missing' | 'stale' }[] => {
          if (side.entry.rows === null && side.entry.status === 'failed') {
            return [{ side, kind: 'missing' as const }]
          }
          if (side.entry.rows !== null && side.entry.failure !== null && !allStale) {
            return [{ side, kind: 'stale' as const }]
          }
          return []
        })

  /* **주문체결상세는 보고 있는 종목의 것만** 담습니다. 계좌 전체를 세우면 이
     카드가 무엇에 대한 카드인지 흐려집니다. 미결제약정은 반대로 계좌 전체입니다 —
     계좌 화면과 같은 목록을 봅니다. */
  const { orders, fills } = useMemo(() => {
    const open: OpenOrder[] = []
    const done: Fill[] = []
    for (const row of orderList.rows ?? []) {
      if (row.code !== shownQuote.code) continue
      const made = toTradeRow(row)
      if (made.kind === 'open') open.push(made.order)
      else done.push(made.fill)
    }
    return { orders: open, fills: done }
  }, [orderList.rows, shownQuote.code])

  const domesticRows = domesticPositions.rows
  const overseasRows = overseasPositions.rows
  const positions: Position[] = useMemo(() => {
    const domestic = (domesticRows ?? []).map((row) => toPosition(row, false))
    const overseas = (overseasRows ?? []).map((row) => toPosition(row, true))
    return activeOverseas ? [...overseas, ...domestic] : [...domestic, ...overseas]
  }, [domesticRows, overseasRows, activeOverseas])

  return {
    accountMarket,
    orderList,
    positionSides,
    positionList,
    receivedSides,
    positionNotes,
    orders,
    fills,
    positions,
  }
}
