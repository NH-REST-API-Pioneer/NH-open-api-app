import { useLayoutEffect, useMemo, useRef } from 'react'
import { fillKey, tickBarOf, type VerifyFill, type VerifyOrder } from '../../data/strategyRuns'
import { useStrategyState } from '../../data/strategyStore'
import { type TradeMark } from '../trade/chartMarks'
import { barHolding, mergeMarks } from './markSeat'
import type { SlotState } from '../trade/chartSlots'
import type { useVerifyRun } from './useVerifyRun'
import type { useVerifyChart } from './useVerifyChart'
import { type BottomTab, type TableRow, clockOf } from './strategyVerifyUtils'

type RunValues = ReturnType<typeof useVerifyRun>
type ChartValues = ReturnType<typeof useVerifyChart>
type StoreState = ReturnType<typeof useStrategyState>

/** 고른 실행의 표 — 차트 표지, 체결·미체결 줄, 이벤트와 그 칸의 높이. */
export function useVerifyTables({
  picked,
  snapshot,
  nameOf,
  bars,
  slot,
  decimals,
  currency,
  store,
  bottom,
}: {
  picked: RunValues['picked']
  snapshot: RunValues['snapshot']
  nameOf: ChartValues['nameOf']
  bars: ChartValues['bars']
  slot: SlotState
  decimals: ChartValues['decimals']
  currency: ChartValues['currency']
  store: StoreState
  bottom: BottomTab
}) {
  /* 차트에 얹을 표. **고른 실행의 것만** 세우고, 갈래를 여기서 거릅니다 —
     차트는 이미 묶인 점만 받습니다. 체결은 **시각으로** 봉을 찾습니다
     — 「몇 봉 전」으로 세면 분봉과 일봉이 서로 다른 봉을 가리켜, 봉 종류를
     바꿀 때마다 같은 체결이 다른 자리로 옮겨 갑니다. 그 시각을 덮는 봉이
     없으면 표를 안 세웁니다. */
  const marks = useMemo<TradeMark[]>(() => {
    if (!picked || !snapshot) return []
    const said = nameOf(picked.version)
    const seated: TradeMark[] = []
    for (const fill of snapshot.fills) {
      const bar = barHolding(bars, fill.time, slot.span)
      if (!bar) continue
      seated.push({
        /* 아래 표와 같은 열쇠입니다. **묶이기 전 값입니다** — 바로 아래
           `mergeMarks` 가 같은 봉·같은 방향의 체결을 표지 하나로 묶고, 남는
           열쇠는 그중 앞선 체결의 것입니다. 묶인 표지에서 뒷줄을 되찾을 수는
           없습니다. */
        id: fillKey(fill),
        kind: 'fill',
        time: bar.timestamp,
        price: fill.price,
        /* 묶인 표지의 평균가를 반올림할 자릿수이자 팝오버가 적을 자릿수입니다 —
           표와 같은 값을 씁니다. */
        decimals,
        side: fill.side,
        intent: fill.intent === 'entry' ? '진입' : '청산',
        qty: fill.quantity,
        count: 1,
        strategy: said.name,
        version: said.version,
        /* 체결이 들고 온 갈래 그대로입니다 — 이 목록에는 모의 계좌 실행도 서서,
           고정으로 두면 계좌에서 난 체결이 「가상」으로 섭니다. */
        virtual: fill.virtual,
        at: clockOf(fill.time),
        reasons: fill.reason ? [fill.reason] : [],
        firstAt: fill.time,
        snapshot: fill.snapshot,
        fee: fill.fee,
        currency,
      })
    }
    return mergeMarks(seated)
    // nameOf 는 목록에서 파생됩니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [picked, snapshot, bars, slot.span, store.rows, decimals])

  /* 아래 표의 행. 체결이 들고 온 값 그대로입니다 — 표와 표지가 같은 값을
     말해야 같은 체결로 읽힙니다. */
  const rows = useMemo<VerifyFill[]>(
    () => (bottom === '체결' ? (snapshot?.fills ?? []) : []),
    [snapshot, bottom],
  )

  /* 아직 안 채워진 주문. **덮어쓰는 값**이라 저장소가 방송이 준 것으로 통째로
     갈아 끼웁니다 — 여기서는 읽기만 합니다. */
  const opens = useMemo<VerifyOrder[]>(
    () => (bottom === '미체결' ? (snapshot?.openOrders ?? []) : []),
    [snapshot, bottom],
  )
  /* 두 탭이 **한 표**를 씁니다. 칸 이름이 같아 갈리는 것은 수량 칸 하나인데,
     **무엇을 적을지는 탭이 정합니다** — 줄에 `remaining` 칸이 있나로 가리면
     서버가 체결 줄에 그 칸을 싣기 시작하는 날 체결 표가 조용히 남은 수량을
     적습니다. 그리기 전에 한 꼴로 맞춰 두어 칸마다 갈래를 다시 보지 않습니다. */
  const tableRows = useMemo<TableRow[]>(() => {
    const line = (
      one: VerifyFill | VerifyOrder,
      key: string,
      amount: number,
      tick: number | null | undefined,
    ): TableRow => ({
      key,
      time: one.time,
      side: one.side,
      intent: one.intent,
      reason: one.reason,
      price: one.price,
      amount,
      tick,
    })
    return bottom === '미체결'
      ? opens.map((one, index) =>
          line(one, `${one.orderId}-${one.time}-${index}`, one.remaining, tickBarOf({ kind: 'order', order: one })),
        )
      : /* 체결은 **저장소가 쓰는 열쇠 그대로** 갈립니다 — 표에서 본 줄을
           저장소에서도 같은 이름으로 찾을 수 있어야 합니다. */
        rows.map((one) => line(one, fillKey(one), one.quantity, tickBarOf({ kind: 'fill', fill: one })))
  }, [bottom, opens, rows])

  /* 이벤트는 **최신 위**입니다. 정렬만 바꿉니다 — 서버가 준 차례와 저장은 그대로입니다.
     같은 시각이면 받은 차례의 뒤엣것이 위입니다. */
  const events = useMemo(
    () =>
      (snapshot?.events ?? [])
        .map((item, index) => ({ item, index }))
        .sort((a, b) => b.item.time - a.item.time || b.index - a.index)
        .map(({ item }) => item),
    [snapshot],
  )
  /* 새 줄이 위에 붙을 때 **보던 자리를 지킵니다.** 맨 위를 보고 있었으면 새 줄을
     따라가고, 아래를 보던 중이면 늘어난 높이만큼 내려 같은 줄이 그 자리에 남습니다. */
  const eventBoxRef = useRef<HTMLDivElement>(null)
  const eventHeight = useRef({ id: '', height: 0 })
  useLayoutEffect(() => {
    const box = eventBoxRef.current
    if (!box || bottom !== '이벤트') return
    const id = snapshot?.run.id ?? ''
    const had = eventHeight.current
    const height = box.scrollHeight
    if (had.id === id && box.scrollTop > 0 && height > had.height) box.scrollTop += height - had.height
    eventHeight.current = { id, height }
  }, [events, bottom, snapshot?.run.id])

  return {
    marks,
    tableRows,
    events,
    eventBoxRef,
  }
}
