import {
  actOnRun,
  reconcileRuns,
  stopAllRuns,
  useStrategyState,
  type ReconcileCount,
} from '../../data/strategyStore'
import { attentionEndWhy, sendEach, type VerifyRun } from '../../data/strategyRuns'
import type { Dispatch, SetStateAction, RefObject } from 'react'
import type { Confirm } from './strategyRunUtils'

type StoreState = ReturnType<typeof useStrategyState>

/** 실행에 거는 동작 — 고르기·체크, 확인 창, 보내기, 계좌 대조, 줄 배지의 색. */
export function makeRunActions({
  setShownId,
  setChecked,
  checked,
  setConfirm,
  setWhy,
  reconcileBusy,
  setReconciling,
  setReconciled,
}: {
  setShownId: (id: string) => void
  setChecked: (next: string[]) => void
  checked: StoreState['run']['checked']
  setConfirm: Dispatch<SetStateAction<Confirm>>
  setWhy: Dispatch<SetStateAction<{ head?: string; side?: string; ack?: string }>>
  reconcileBusy: RefObject<boolean>
  setReconciling: Dispatch<SetStateAction<boolean>>
  setReconciled: Dispatch<SetStateAction<{ count: ReconcileCount | null } | { failed: string } | null>>
}) {
  function showRun(id: string) {
    setShownId(id)
  }

  function toggle(id: string) {
    setChecked(checked.includes(id) ? checked.filter((x) => x !== id) : [...checked, id])
  }

  /* 확인 창을 누르면 요청이 나갑니다. **화면이 상태를 미리 바꾸지 않습니다** —
     바꿔 두면 아직 안 끝난 일을 끝난 것으로 말하게 되고, 서버가 막았을 때
     되돌릴 자리도 없습니다. 바뀐 상태는 방송이 실어 옵니다.
     막혔으면 **서버 문장을 그대로** 한 줄로 세웁니다 — 「대사 중」인 줄에는
     중지·청산·종료가, 「확인 필요」인 줄에는 중지·청산과 남은 것이 있는 종료가
     막히고, 그 까닭도 서버가 냅니다. */
  async function apply(action: string, targets: VerifyRun[]) {
    setConfirm(null)
    setWhy({})
    if (action === '전체 신규 진입 중지') {
      const said = await stopAllRuns()
      /* 답이 수(멈춘 실행 개수)면 막힌 것이 아닙니다. */
      if (typeof said === 'string') setWhy({ head: said })
      return
    }
    /* **빠지는 줄을 빼고 나머지를 차례로** 보내고, 하나가 거절돼도 나머지는
       보냅니다. 한 실행의 사정이 다른 실행을 막을 까닭이 없습니다. 결과는
       「N건 중 K건 거절 — 첫 서버 문장」 한 줄입니다(검증과 같은 셈). */
    const deed = action === '실행 종료' ? 'end' : action === '선택 전략 청산' ? 'close' : 'stop'
    const sending = targets.filter((run) => skipWhy(action, run) === null)
    const said = await sendEach(sending, (run) => actOnRun(run.id, deed))
    if (said !== null) setWhy({ side: said })
  }

  /* 이 요청이 건드리지 않는 줄. **서버가 400 으로 막는 자리와 같습니다** —
     「확인 필요」와 「대사 중」은 사용자가 손을 써야 넘어가는 상태라, 새 요청을
     보냈다고 사라지면 화면이 「끝난 일」로 말하게 됩니다. 「확인 필요」
     줄의 「실행 종료」만은 예외입니다(`skipWhy`). */
  const blocks = (run: VerifyRun) => run.state === 'attention' || run.state === 'reconciling'

  /* 확인창에서 그 줄이 빠지는 까닭. 빠지지 않으면 `null` 입니다.
     끝난 실행은 **세 동작 모두에서** 뺍니다 — 멈출 신규 진입도, 청산할 보유도
     없어 보내면 서버가 거절합니다. 「실행 종료」는 보유가 남은 실행도 미리
     뺍니다. 까닭 낱말은 검증 화면과 같은 글자입니다. 미체결·취소 확인 대기는
     이 줄이 모르는 값이라 서버가 거절하고, 그 문장이 섭니다. */
  function skipWhy(action: string, run: VerifyRun): string | null {
    /* 「확인 필요」 줄의 종료는 남은 것이 없으면 보냅니다 — 계좌로 나가는 요청이
       없습니다. 남은 것이 보이면 그 까닭으로 뺍니다(`attentionEndWhy`). */
    if (action === '실행 종료' && run.state === 'attention') return attentionEndWhy(run)
    if (blocks(run)) return `${run.stateLabel} — 이번 요청에서 제외`
    if (run.state === 'ended') return '끝난 실행입니다'
    if (action !== '실행 종료') return null
    if (run.position !== 0) return '「선택 전략 청산」을 먼저 하세요'
    return null
  }

  /* 계좌와 대조. 답을 기다리는 동안 단추를 잠급니다 — 그린 값은 다음 그림까지
     옛 값이라, 한 번에 몰려 온 두 번째 누름은 `reconcileBusy` 가 막습니다.
     맞춰 봤으면 그 결과를 잠깐 세우고, 못 보냈으면 서버 글을 남깁니다. 둘 다
     단추 곁 한 줄에 섭니다. */
  async function reconcile() {
    if (reconcileBusy.current) return
    reconcileBusy.current = true
    setReconciling(true)
    setReconciled(null)
    setWhy({})
    const said = await reconcileRuns()
    reconcileBusy.current = false
    setReconciling(false)
    setReconciled(typeof said === 'string' ? { failed: said } : { count: said })
  }

  /* 확인창을 엽니다. 지난 요청의 결과 줄(「N건 중 K건 거절」)은 비웁니다 —
     새 창에서 고른 실행과 상관없는 앞 요청의 말이 남아 있으면 이번 결과로
     읽힙니다. */
  function openConfirm(next: NonNullable<Confirm>) {
    setWhy((now) => ({ ...now, side: undefined }))
    setConfirm(next)
  }

  /* 「확인 필요」를 푸는 자리. 서버가 계좌와 다시 맞춰 보고, 그래도 어긋나면
     **그대로 「확인 필요」로 남습니다** — 화면이 푼 것으로 적지 않습니다. */
  async function acknowledge(id: string) {
    const said = await actOnRun(id, 'acknowledge')
    setWhy(said === null ? {} : { ack: said })
  }

  /* 배지 한 칸의 색. **경고색은 「확인 필요」 하나**가 씁니다 — 손을 써야
     넘어가는 자리는 그것뿐이고, 기다리면 되는 자리(답 대기·대사 중·승인
     없음)까지 경고로 칠하면 정말 손써야 하는 줄이 그 속에 묻힙니다.
     손을 써야 넘어가는 줄은 **방향색을 뺍니다** — 「확인 필요」를 파랑으로
     칠하면 낱말까지 덮여 매도로 읽힙니다. 그 줄의 보유 방향은 글자가
     말합니다. */
  function badgeOf(run: VerifyRun): string {
    if (run.state === 'attention') return 'badge run-alert'
    return directionOf(run) ? 'badge run-holding' : 'badge'
  }
  /* 보유 방향 조각의 색 — 방향색은 **「매수 n계약」·「매도 n계약」 조각에만**
     씁니다. 상태 낱말(「감시 중」)까지 칠하면 상태가 방향처럼 읽힙니다. */
  function directionOf(run: VerifyRun): string | undefined {
    if ((run.position ?? 0) > 0 && !blocks(run)) return run.side === 'buy' ? 'run-dir-buy' : 'run-dir-sell'
    return undefined
  }

  return {
    showRun,
    toggle,
    apply,
    blocks,
    skipWhy,
    reconcile,
    openConfirm,
    acknowledge,
    badgeOf,
    directionOf,
  }
}
