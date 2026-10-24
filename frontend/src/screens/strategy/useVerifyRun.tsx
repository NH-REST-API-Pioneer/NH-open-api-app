import { useEffect, useRef } from 'react'
import { isPaperRun, tradingOf, type VerifyRun } from '../../data/strategyRuns'
import {
  loadRunSnapshot,
  refreshConditions,
  patchVerify,
  seedFromSelection,
  snapshotOf,
  useStrategyState,
} from '../../data/strategyStore'
import { RunKindBadge } from './runKind'
import type { Dispatch, SetStateAction, RefObject } from 'react'
import type { BottomTab } from './strategyVerifyUtils'

type StoreState = ReturnType<typeof useStrategyState>

/** 검증 탭이 보는 실행 — 고른 실행과 그 한 벌, 상태별 셈, 진행 탭으로 가는 링크. */
export function useVerifyRun({
  runs,
  pickedId,
  store,
  max,
  onOpenRun,
  tabAsked,
  setBottom,
}: {
  runs: VerifyRun[]
  pickedId: string
  store: StoreState
  max: number
  onOpenRun: (runId: string) => void
  tabAsked: RefObject<BottomTab | null>
  setBottom: Dispatch<SetStateAction<BottomTab>>
}) {
  /* 이 탭이 보는 것은 **앱 시뮬레이션(종이) 실행**입니다. 계좌 실행(모의·실전)은
     주문이 계좌로 나가는 실행이라 진행 탭에서만 보고 다룹니다 — 「여기서 나가는
     주문은 없다」는 이 탭의 약속이 그래야 지켜집니다. 목록·고른 실행·셈·일괄
     대상이 모두 이 목록을 씁니다. */
  const all = runs.filter(isPaperRun)
  const picked = all.find((run) => run.id === pickedId) ?? all[0] ?? null
  /* 고른 실행의 한 벌. **그 실행의 칸만** 읽습니다 — 진행 탭이 다른 실행을 보고
     있어도 이 표는 고른 실행의 것입니다. */
  const snapshot = snapshotOf(store.verify, picked?.id)
  /* 「도는 중」은 **중지·종료가 아닌 것**입니다. 진입 주문 중·보유 중·청산
     요청은 다 도는 중입니다 — 상태 여덟을 접어 세는 자리라 접는 기준을 여기
     한 번만 둡니다.

     **중지와 종료를 가릅니다.** 중지는 다시 굴릴 수 있고 종료는 끝난 것이라,
     한 칸에 묶으면 「중지 3」을 보고 셋을 다시 굴릴 수 있다고 읽습니다.
     셋을 각각 세는 것도 그래서입니다 — 하나를 빼기로 구하면 그 칸이 「나머지
     전부」가 되어, 상태가 하나 늘어나는 날 그 실행들이 조용히 섞여 듭니다. */
  const running = all.filter((run) => run.state !== 'paused' && run.state !== 'ended').length
  const stopped = all.filter((run) => run.state === 'paused').length
  const ended = all.filter((run) => run.state === 'ended').length
  /* 동시 실행 상한은 **검증과 진행이 함께** 먹습니다. 그래서 머리의 「동시 실행」은
     서버 목록 전체에서 끝나지 않은 것을 세고, 이 탭의 것은 따로 적습니다. */
  const standing = runs.filter((run) => run.state !== 'ended').length
  const full = max > 0 && standing >= max
  const fullWhy = `동시 실행이 ${max}개라 더 세울 수 없습니다 — 진행 탭의 실행도 셉니다`
  /* 진행 탭에서 도는 계좌 실행. 링크가 여는 것은 그 첫째이고 **실전이 먼저**입니다 —
     계좌로 실제 돈이 걸린 쪽을 먼저 봐야 합니다. */
  const trading = tradingOf(runs)
  const tradingLink =
    trading.firstId === null ? null : (
      <button type="button" className="vrf-trading" onClick={() => onOpenRun(trading.firstId as string)}>
        {trading.hasReal && <RunKindBadge kind="real" short />}
        <span>
          거래 중 <span className="vrf-trading-n">{trading.count}</span> — 진행에서 보기
        </span>
      </button>
    )
  const openAdd = () => {
    if (!full) patchVerify({ add: seedFromSelection() })
  }

  /* 고른 실행의 한 벌. 목록과 따로 받습니다 — 체결·이벤트는 그 실행에만
     있습니다. 고른 줄이 바뀌면 그 줄의 것으로 다시 받습니다. */
  useEffect(() => {
    void loadRunSnapshot(picked?.id ?? '')
  }, [picked?.id])

  /* 실행을 바꾼 뒤 **그 실행의 한 벌이 처음 올 때** 탭을 정합니다 — 체결이 있으면
     「체결」, 없으면 「조건」입니다. 카드에서 이벤트를 청했으면 그대로 둡니다. */
  const openedFor = useRef('')
  useEffect(() => {
    const id = snapshot?.run.id ?? ''
    if (!id || openedFor.current === id) return
    openedFor.current = id
    const asked = tabAsked.current
    tabAsked.current = null
    setBottom(asked ?? ((snapshot?.fills.length ?? 0) > 0 ? '체결' : '조건'))
  }, [snapshot, setBottom, tabAsked])

  /* 조건 표는 **허브 방송에 없습니다** — 고른 실행의 판정 봉이 바뀌면 그 실행의 표만
     한 번 다시 받습니다(봉당 한 번). 받는 중이면 겹쳐 내지 않고 다음 봉에 받습니다. */
  const conditionsFlying = useRef(false)
  const seenBar = useRef<{ id: string; bars: number | null } | null>(null)
  useEffect(() => {
    if (!picked) return
    const seen = seenBar.current
    seenBar.current = { id: picked.id, bars: picked.bars }
    if (!seen || seen.id !== picked.id || seen.bars === picked.bars) return
    if (conditionsFlying.current) return
    conditionsFlying.current = true
    void refreshConditions(picked.id).finally(() => {
      conditionsFlying.current = false
    })
  }, [picked?.id, picked?.bars])

  return {
    all,
    picked,
    snapshot,
    running,
    stopped,
    ended,
    standing,
    full,
    fullWhy,
    tradingLink,
    openAdd,
  }
}
