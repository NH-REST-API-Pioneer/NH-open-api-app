import { instrumentNameOf, type StrategyVersion } from '../../data/strategyList'
import { NAMELESS } from './runStats'
import type { Environment } from '../../data/environment'
import type { useListView } from './useListView'

/** 버전마다의 실행 셈과 이름 한 줄. */
export function makeListStats({ verify }: { verify: ReturnType<typeof useListView>['verify'] }) {
  /* 그 버전의 끝나지 않은 실행 수 — 종이(검증 중)와 계좌(거래 중)는 **중지를 뺀**
     수이고, 중지는 따로 셉니다(갈래를 안 가림). 계좌 실행 가운데 실전이 있는지와,
     중지 실행이 계좌 쪽에 있는지도 함께 냅니다. 상태 칸 배지와 삭제 잠금이 이 하나를
     씁니다 — 삭제는 중지까지 포함한 끝나지 않은 실행 전부(`total`)로 막습니다. */
  const liveOf = (versionId: string) => {
    const mine = verify.runs.filter((run) => run.version === versionId && run.state !== 'ended')
    const going = mine.filter((run) => run.state !== 'paused')
    const paused = mine.filter((run) => run.state === 'paused')
    const isAccount = (run: { mode: string }) => run.mode === 'sim' || run.mode === 'real'
    const account = going.filter(isAccount)
    return {
      paper: going.filter((run) => run.mode === 'paper').length,
      account: account.length,
      real: account.some((run) => run.mode === 'real'),
      paused: paused.length,
      pausedAccount: paused.some(isAccount),
      total: mine.length,
    }
  }
  /* 이름이 비어 있는 전략은 **「이름 없는 초안 · 종목」**으로 섭니다 — id 를 이름
     자리에 세우지 않습니다. */
  const nameText = (row: StrategyVersion) => row.name.trim() || `${NAMELESS} · ${instrumentNameOf(row)}`
  const accountEnvironments = (versionId: string): Environment[] => {
    const seen = new Set<Environment>()
    for (const run of verify.runs) {
      if (run.version !== versionId || run.state === 'ended') continue
      if (run.mode !== 'sim' && run.mode !== 'real') continue
      seen.add(run.environment === 'real' || (run.environment == null && run.mode === 'real') ? 'real' : 'paper')
    }
    return (['paper', 'real'] as const).filter((one) => seen.has(one))
  }

  return { liveOf, nameText, accountEnvironments }
}
