import type { Environment } from '../../data/environment'
import type { RunMode, VerifyRun } from '../../data/strategyRuns'

/* 실행 갈래 — 실행이 **어느 장부로 도는지**를 말하는 낱말과 배지.
 *
 * 접속 환경(상단의 「모의」·「실전」)과 다른 사실입니다. 환경은 이 앱이 지금
 * 붙은 계좌이고, 갈래는 실행 하나가 주문을 어느 계좌로 내는지(모의 계좌·실전
 * 계좌) 앱 안에서만 셈하는지(앱 시뮬레이션)입니다. 그래서 환경 배지의 꼴(`env-*`)을 빌리지 않고
 * 제 꼴을 둡니다 — 같은 꼴이면 환경 배지를 바꿀 때 갈래 배지가 따라오고,
 * 「지금 접속 환경이 모의」로 읽힙니다.
 *
 * 낱말도 여기 한 자리입니다. 한 갈래를 화면마다 다른 말로 부르면 같은 실행인지
 * 알 수 없습니다. */

export const RUN_KIND_LABEL: Record<RunMode, string> = {
  paper: '앱 시뮬레이션',
  sim: '모의 계좌',
  real: '실전 계좌',
}

/** 확인창의 「계좌」 칸에 서는 짧은 꼴. **일반주문 확인창과 같은 낱말**입니다 —
 *  「계좌 · 모의 계좌」처럼 칸 이름과 값이 같은 말을 되풀이하면, 두 창이 같은
 *  것을 다른 말로 묻는 것으로 읽힙니다. 앱 시뮬레이션은 되풀이가 없어 그대로입니다. */
export const RUN_KIND_SHORT: Record<RunMode, string> = {
  paper: '앱 시뮬레이션',
  sim: '모의',
  real: '실전',
}

/** 상단 접속 환경과 계좌 실행이 갈렸을 때의 한 줄. **무엇이 갈렸는지와 지금
 *  일어나는 일만** 적습니다 — 그대로 두는 것도 맞는 선택이라 할 일을 시키지
 *  않습니다. 양쪽이 같은 꼴입니다. */
export const ENV_SPLIT_NOTE: Record<Environment, string> = {
  real: '상단은 실전 — 이 실행들은 모의 계좌에서 돕니다',
  paper: '상단은 모의 — 이 실행들은 실전 계좌에서 돕니다',
}

/** 세울 한 줄. 상단이 실전인데 끝나지 않은 모의 계좌 실행이 있거나, 상단이
 *  모의인데 끝나지 않은 실전 계좌 실행이 있을 때입니다. 환경을 아직 모르면
 *  (`null`) 세우지 않습니다 — 모르는 것을 어느 한쪽이라고 적게 됩니다. 앱
 *  시뮬레이션 실행은 계좌에 안 붙어 해당이 없습니다. 세울 것이 없으면 `null`. */
export function envSplit(active: Environment | null, runs: readonly VerifyRun[]): string | null {
  if (active === null) return null
  const other = active === 'real' ? 'sim' : 'real'
  return runs.some((run) => run.mode === other && run.state !== 'ended') ? ENV_SPLIT_NOTE[active] : null
}

/** 머리 줄의 갈래 배지 바로 뒤에 서는 경고 한 줄. 좁으면 말줄임이고 전체는
 *  `title` 에 있습니다. 환경 배지의 꼴을 빌리지 않습니다 — 글자 한 줄입니다. */
export function EnvSplitNote({ text }: { text: string }) {
  return (
    <span className="env-split" title={text}>
      {text}
    </span>
  )
}

/** 갈래 배지. 확인창의 계좌 칸에서는 `short` 로 짧은 꼴을 씁니다. */
export function RunKindBadge({ kind, short = false }: { kind: RunMode; short?: boolean }) {
  return (
    <span className={`badge run-kind run-kind-${kind}`}>
      {(short ? RUN_KIND_SHORT : RUN_KIND_LABEL)[kind]}
    </span>
  )
}
