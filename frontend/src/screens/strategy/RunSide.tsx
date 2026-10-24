import { patchRun, seedFromSelection, storeNote, useStrategyState } from '../../data/strategyStore'
import type { VerifyRun } from '../../data/strategyRuns'
import { RunKindBadge } from './runKind'
import { PICK_HINT, RunStats, runNameOf, targetLine } from './runStats'
import { shortInstrument } from './strategyRunUtils'
import type { useRunView } from './useRunView'
import type { makeRunActions } from './runActions'

type ViewValues = ReturnType<typeof useRunView>
type ActionValues = ReturnType<typeof makeRunActions>
type SideParts = ReturnType<typeof runSideParts>
type StoreState = ReturnType<typeof useStrategyState>

type RunSideArgs = Pick<ViewValues, 'shown'> &
  Pick<ActionValues, 'toggle' | 'showRun' | 'badgeOf' | 'directionOf'> &
  {
    nameOf: (versionId: string) => ReturnType<typeof runNameOf>
    checked: StoreState['run']['checked']
    runCurrency: (run: VerifyRun) => string
  }

/** 실행 목록의 줄 하나를 그리는 함수. */
export function runSideParts({
  nameOf,
  shown,
  checked,
  toggle,
  showRun,
  badgeOf,
  directionOf,
  runCurrency,
}: RunSideArgs) {
  function runRow(run: VerifyRun) {
    const holding = (run.position ?? 0) > 0
    const said = nameOf(run.version)
    return (
      <label className={`run-row${run.id === shown?.id ? ' is-shown' : ''}`} key={run.id}>
        <input type="checkbox" checked={checked.includes(run.id)} onChange={() => toggle(run.id)} />
        <button
          type="button"
          className="run-row-body"
          aria-current={run.id === shown?.id ? 'true' : undefined}
          onClick={() => showRun(run.id)}
        >
          {/* 전략 이름 · 버전 · 종목을 줄을 나눠 적습니다 — 한 줄에 붙이면
              좁은 열에서 종목이 만기부터 잘립니다(검증 화면과 같은 규칙). */}
          {/* 이름 줄 끝에 그 실행의 갈래 — 모의 계좌와 실전 계좌 실행이 한 목록에
              섭니다. */}
          <span className="run-name">
            <span className="run-name-text">{said.name}</span>
            <RunKindBadge kind={run.mode} short />
          </span>
          <span className="run-sub">{said.version}</span>
          <span className="run-sub">{shortInstrument(run.code)}</span>
          <span className="run-state">
            {/* 상태 낱말은 **서버가 함께 줍니다** — 화면이 상태 표를 또 두면
                두 표가 갈립니다. */}
            <span className={badgeOf(run)}>
              {run.stateLabel}
              {holding && ' · '}
              {holding && (
                <span className={directionOf(run)}>
                  {run.side === 'buy' ? '매수' : '매도'} {run.position}계약
                </span>
              )}
              {/* 보유를 모르면(`null`) 0 이라 적지 않고 「—」입니다. */}
              {!holding && (run.position === null ? ' · 보유 —' : ' · 보유 0')}
            </span>
            {/* 보낸 주문 가운데 아직 답을 못 받은 수입니다. **기다리면 되는
                자리**라 중립입니다 — 손쓸 것이 없습니다. */}
            {(run.pending ?? 0) > 0 && <span className="run-note">답 대기 {run.pending}</span>}
          </span>
          {/* 성과 한 줄 — 서버가 센 신호·체결 수와 손익, 마지막 신호 시각. */}
          <RunStats run={run} currency={runCurrency(run)} />
          {/* 아래 줄에는 **배지가 말하지 않는 것만** 답니다. 「확인 필요」·
              「대사 중」은 이미 배지에 있어 여기 또 적으면 같은 사실이 한 줄에
              두 번 섭니다.

              승인을 안 지난 모의 실행은 **한 건도 안 냅니다.** 도는 것처럼
              보이는데 주문이 안 나가는 까닭이라 줄에 적습니다. **값이 아예
              없는 것도 「안 지났다」입니다** — 서버가 그 칸을 안 실어 줄 수도
              있고, 그때 「지났다」로 읽으면 안 나가는 주문을 나간다고 말하게
              됩니다. */}
          {!run.approvedAt && <span className="run-note">승인 없음 — 주문 안 나감</span>}
        </button>
      </label>
    )
  }

  return {
    runRow,
  }
}

type RunsCardArgs = Pick<ViewValues, 'all' | 'picked'> &
  Pick<ActionValues, 'openConfirm'> &
  Pick<SideParts, 'runRow'> &
  {
    storeWhy: ReturnType<typeof storeNote>
    status: StoreState['verify']['status']
    why: { head?: string; side?: string; ack?: string }
  }

/** 실행 카드 — 거래 추가, 실행 목록, 고른 실행에 거는 단추와 못 누르는 까닭. */
export function renderRunsCard({
  storeWhy,
  status,
  all,
  runRow,
  picked,
  openConfirm,
  why,
}: RunsCardArgs) {
  return (
            <div className="card run-runs">
              <div className="run-runs-head">
                <h2 className="run-card-title">실행</h2>
                <button
                  type="button"
                  className="btn btn-primary"
                  /* 목록에서 고른 전략으로 채워 엽니다 — 첫 줄로 채우면
                     골라 둔 전략을 두고 다른 전략이 섭니다. */
                  onClick={() => patchRun({ add: seedFromSelection() })}
                >
                  거래 추가
                </button>
              </div>
              {/* 담아 둔 실행을 서버가 못 읽었으면 **목록이 빈 까닭**을 이 카드
                  안에 한 줄로 답니다. 카드는 단추가 서 있어 통째로 비지 않으므로
                  블록이 아니라 줄입니다. 머리 아래의 줄과 겹치지 않습니다 — 그
                  줄은 누른 단추의 답이고, 이 줄은 목록이 왜 비었는지입니다.
                  파일 이름은 **마우스를 올렸을 때만** 보입니다 — 사용자가 할 일을
                  바꾸는 말이 아니라 나중에 찾을 때 쓰는 말이고, 좁은 카드에서
                  여러 줄로 접히면 실행 목록이 밀려납니다. */}
              {storeWhy !== null && (
                <p className="run-store-why" title={storeWhy.reason ?? undefined}>
                  {storeWhy.title}
                </p>
              )}
              <div className="run-list">
                {status === 'loading' && <p className="run-why">실행 목록을 받는 중입니다</p>}
                {/* 비었다는 말은 가운데 빈 화면이 합니다 — 여기 또 적으면 같은 말이 두 번 섭니다.
                    담아 둔 파일을 **못 읽었으면 그 빈 화면도 안 섭니다** — 바로 위 한 줄이 이미
                    무슨 일인지 말했고, 「없다」고 하면 그 말과 반대가 됩니다. 이 앱 파일이 아닌
                    경우는 읽기는 읽었고 그 실행들이 안 도는 것이 사실이라 빈 화면이 섭니다. */}
                {all.map(runRow)}
              </div>
              {/* 일괄 단추가 무엇에 걸리는지 — 단추 묶음 바로 위입니다(검증 화면과 같은 자리). */}
              {all.length > 0 && <p className="run-target">{targetLine(picked.length)}</p>}
              <div className="run-acts">
                <button
                  type="button"
                  className="btn btn-quiet"
                  aria-disabled={picked.length === 0}
                  aria-describedby={picked.length === 0 ? 'run-pick-why' : undefined}
                  title={picked.length === 0 ? PICK_HINT : undefined}
                  onClick={() => picked.length > 0 && openConfirm({ action: '신규 진입 중지', runs: picked })}
                >
                  신규 진입 중지
                </button>
                <button
                  type="button"
                  className="btn btn-quiet"
                  aria-disabled={picked.length === 0}
                  aria-describedby={picked.length === 0 ? 'run-pick-why' : undefined}
                  title={picked.length === 0 ? PICK_HINT : undefined}
                  onClick={() => picked.length > 0 && openConfirm({ action: '선택 전략 청산', runs: picked })}
                >
                  선택 전략 청산
                </button>
                {/* 검증 화면과 같은 낱말·같은 차례(중지 → 청산 → 종료)입니다. */}
                <button
                  type="button"
                  className="btn btn-quiet"
                  aria-disabled={picked.length === 0}
                  aria-describedby={picked.length === 0 ? 'run-pick-why' : undefined}
                  title={picked.length === 0 ? PICK_HINT : undefined}
                  onClick={() => picked.length > 0 && openConfirm({ action: '실행 종료', runs: picked })}
                >
                  실행 종료
                </button>
                {/* 단추 아래는 **서버가 막은 까닭**과 못 누르는 까닭의 자리입니다 — 단추에서
                    먼 머리 띠에 두면 누른 사람이 답을 다른 데서 찾아야 합니다. 서버 문장이
                    먼저입니다: 방금 보낸 것에 대한 답이라 지금 알아야 할 것이 그쪽입니다.
                    자리는 늘 비워 두어 목록이 오르내리지 않습니다. */}
                <p className="run-why" id="run-pick-why">
                  {why.side ?? (all.length > 0 && picked.length === 0 ? PICK_HINT : '')}
                </p>
              </div>
            </div>
  )
}
