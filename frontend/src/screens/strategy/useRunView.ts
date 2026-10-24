import { snapshotOf, useStrategyState, type ReconcileCount } from '../../data/strategyStore'
import { accountModeOf, isAccountMode, isTickRun } from '../../data/strategyRuns'
import { useEnvironment } from '../../data/environment'
import { envSplit } from './runKind'
import { targetsOf } from './runStats'
import { ORDER_NO_FITS, ORDER_NO_FITS_TICK, RECONCILING, reconciledText } from './strategyRunUtils'

type StoreState = ReturnType<typeof useStrategyState>

/** 진행 탭이 보는 계좌 실행 — 보는 실행과 그 한 벌, 상태별 셈, 대조 줄, 갈래와 환경. */
export function useRunView({
  runs,
  shownId,
  store,
  tableInner,
  checked,
  reconciling,
  reconciled,
}: {
  runs: StoreState['verify']['runs']
  shownId: StoreState['run']['shownId']
  store: StoreState
  tableInner: number
  checked: StoreState['run']['checked']
  reconciling: boolean
  reconciled: { count: ReconcileCount | null } | { failed: string } | null
}) {
  /* 이 화면이 보는 것은 계좌로 도는 실행입니다(모의 계좌·실전 계좌 한 목록).
     종이 실행은 검증 화면이 봅니다. 목록·중지·청산이 모두 이 목록을 씁니다. */
  const all = runs.filter((run) => isAccountMode(run.mode))
  const shown = all.find((run) => run.id === shownId) ?? all[0] ?? null
  /* 보는 실행의 한 벌. **그 실행의 칸만** 읽습니다 — 검증 탭이 고른 실행과 따로
     담겨 있어, 검증 탭에서 무엇을 골라도 이 표는 보는 실행의 것입니다. */
  const snapshot = snapshotOf(store.verify, shown?.id)
  /* 틱으로 평가하는 실행이면 시각 칸이 「틱」 표지 자리만큼 넓고, 그만큼 주문번호
     열도 일찍 접힙니다. */
  const tickRun = isTickRun(shown)
  const narrow = tableInner > 0 && tableInner < (tickRun ? ORDER_NO_FITS_TICK : ORDER_NO_FITS)
  /* 「신규 진입 중지·선택 전략 청산·실행 종료」의 대상 — **체크한 실행만**
     (`targetsOf`, 검증 화면과 같은 규칙). 체크가 없으면 세 단추가 잠깁니다. */
  const picked = targetsOf(all, checked)
  /* 「거래 중」은 **중지·종료가 아닌 것**입니다. 목록에는 끝난 실행도 서므로
     셋을 각각 셉니다 — 하나를 빼기로 구하면 그 칸이 「나머지 전부」가 되어,
     끝난 실행이 「중지」로 읽힙니다. 중지는 다시 굴릴 수 있고 종료는 끝난
     것이라 다른 말입니다(검증 머리와 같은 조건). */
  const trading = all.filter((run) => run.state !== 'paused' && run.state !== 'ended').length
  const stopped = all.filter((run) => run.state === 'paused').length
  const ended = all.filter((run) => run.state === 'ended').length
  const needCheck = all.filter((run) => run.state === 'attention').length
  /* 「계좌와 대조」 단추 곁에 서는 한 줄 — 기다리는 중, 맞춰 본 결과, 못 보낸 까닭. */
  const reconcileLine = reconciling
    ? RECONCILING
    : reconciled === null
      ? ''
      : 'failed' in reconciled
        ? reconciled.failed
        : reconciledText(reconciled.count)
  const reconcileFailed = !reconciling && reconciled !== null && 'failed' in reconciled
  /* 상한을 먹는 실행 — 갈래를 안 가리고 끝나지 않은 것 전부(서버가 상한을 보는 셈). */
  const standingAll = runs.filter((run) => run.state !== 'ended').length

  /* 계좌 표시는 화면 전체의 맥락입니다. **갈래가 정합니다** — 실행이 없으면
     붙어 있는 계좌도 없어 빈 채로 둡니다. 어느 계좌인지 지어 세우면 그 계좌로
     주문이 나가는 것으로 읽힙니다. */
  const kinds = (['sim', 'real'] as const).filter((kind) => all.some((run) => run.mode === kind))
  /* 상단 환경과 계좌 실행의 환경이 갈렸는지. 갈래 배지 바로 뒤에 한 줄입니다. */
  const environment = useEnvironment()
  const split = envSplit(environment.active, all)

  /* 지금 세울 수 있는 계좌 갈래. **서버 답 하나에서 정합니다** — 접속 환경을
     확인했고(`ready`), 그 환경의 갈래가 서버가 준 목록(`accountModes`)에 있을
     때만입니다. 모르면 `null` 이라 확인 얼굴로 넘어가지 않습니다. */
  const modeNow = environment.status === 'ready' ? accountModeOf(environment.active) : null
  const askable = modeNow !== null && store.verify.accountModes.includes(modeNow) ? modeNow : null

  return {
    environment,
    all,
    shown,
    snapshot,
    tickRun,
    narrow,
    picked,
    trading,
    stopped,
    ended,
    needCheck,
    reconcileLine,
    reconcileFailed,
    standingAll,
    kinds,
    split,
    askable,
  }
}
