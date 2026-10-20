import { useCallback, useMemo, useState } from 'react'
import { fillKey, tickBarOf, type VerifyFill, type VerifyOrder } from '../../data/strategyRuns'
import type { useRunView } from './useRunView'
import { type BottomTab, ORDER_STATE_WORD, type TableRow } from './strategyRunUtils'

type ViewValues = ReturnType<typeof useRunView>

/** 아래 표를 담은 칸의 안쪽 폭과 그 칸에 걸 ref. */
export function useTableWidth() {
  /* 아래 표를 담은 칸의 안쪽 폭. 주문번호 열을 접을지는 보는 실행이 정해진 뒤에
     가립니다(`ORDER_NO_FITS`). */
  const [tableInner, setTableInner] = useState(0)
  /* 표 칸이 화면에 붙을 때 재기 시작하고 떨어질 때 멈춥니다. 실행 목록이 늦게 와
     표가 나중에 생겨도 그때부터 폭을 잽니다. */
  const tableBoxRef = useCallback((box: HTMLDivElement | null) => {
    if (!box) return
    const measure = () => {
      const style = getComputedStyle(box)
      setTableInner(box.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight))
    }
    measure()
    const watcher = new ResizeObserver(measure)
    watcher.observe(box)
    return () => watcher.disconnect()
  }, [])

  return {
    tableBoxRef,
    tableInner,
  }
}

/** 아래 표 — 보는 실행의 체결·미체결을 한 꼴로 맞춘 줄과 이벤트. */
export function useRunTables({
  bottom,
  snapshot,
}: {
  bottom: BottomTab
  snapshot: ViewValues['snapshot']
}) {
  /* 아래 표의 행. **한 벌이 들고 온 값 그대로**입니다 — 표가 값을 따로
     세우면 같은 체결에 두 값이 생깁니다. */
  const rows = useMemo<VerifyFill[]>(
    () => (bottom === '최근 체결' ? (snapshot?.fills ?? []) : []),
    [snapshot, bottom],
  )

  /* 아직 안 채워진 주문. **덮어쓰는 값**이라 저장소가 방송이 준 것으로 통째로
     갈아 끼웁니다 — 여기서는 읽기만 합니다.
     줄 머리의 `pending` 과 **다른 수입니다**: 그쪽은 보내고 아직 답을 못 받은
     주문이고, 이 목록은 답을 받아 계좌에 서 있는 주문입니다. */
  const opens = useMemo<VerifyOrder[]>(
    () => (bottom === '미체결' ? (snapshot?.openOrders ?? []) : []),
    [snapshot, bottom],
  )

  /* 두 탭이 한 표를 씁니다. 그리기 전에 한 꼴로 맞춰 두어 칸마다 갈래를 다시
     보지 않습니다. */
  const tableRows = useMemo<TableRow[]>(() => {
    if (bottom === '미체결') {
      return opens.map((one, index) => ({
        key: `${one.orderId}-${one.time}-${index}`,
        time: one.time,
        orderNo: one.orderNo?.trim() || null,
        side: one.side,
        intent: one.intent,
        reason: one.reason,
        state: ORDER_STATE_WORD[one.status] ?? one.status,
        price: one.price,
        amount: one.remaining,
        tick: tickBarOf({ kind: 'order', order: one }),
      }))
    }
    /* 체결 줄을 가리는 열쇠는 **저장소·검증 표와 같은 것**입니다 — 한 주문이
       나뉘어 체결되고, 같은 밀리초에 두 줄이 날 수 있습니다. */
    return rows.map((one) => ({
      key: fillKey(one),
      time: one.time,
      /* **계좌가 준 번호**만 적습니다. `orderId` 는 장부가 매긴 번호라 계좌
         주문내역에서 찾을 수 없습니다. */
      orderNo: one.orderNo?.trim() || null,
      side: one.side,
      intent: one.intent,
      reason: one.reason,
      state: '체결',
      price: one.price,
      amount: one.quantity,
      tick: tickBarOf({ kind: 'fill', fill: one }),
    }))
  }, [bottom, opens, rows])

  const events = useMemo(() => snapshot?.events ?? [], [snapshot])

  return {
    tableRows,
    events,
  }
}
