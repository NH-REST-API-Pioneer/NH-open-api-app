import { useStrategyState } from '../../data/strategyStore'
import { loadLimits, useLimits, type LimitAxis } from '../../data/strategyLimits'
import { EnvSplitNote, RunKindBadge } from './runKind'
import type { Dispatch, SetStateAction } from 'react'
import type { useRunView } from './useRunView'
import type { useRunLimits } from './useRunLimits'
import type { makeRunActions } from './runActions'

type ViewValues = ReturnType<typeof useRunView>
type LimitValues = ReturnType<typeof useRunLimits>
type ActionValues = ReturnType<typeof makeRunActions>
type StoreState = ReturnType<typeof useStrategyState>

type RunHeadLineArgs = Pick<
    ViewValues,
    'kinds' | 'split' | 'trading' | 'stopped' | 'ended' | 'standingAll' | 'needCheck'
    | 'reconcileLine' | 'reconcileFailed' | 'all'
  > &
  Pick<ActionValues, 'reconcile' | 'openConfirm'> &
  {
    max: StoreState['verify']['max']
    status: StoreState['verify']['status']
    failure: StoreState['verify']['failure']
    reconciling: boolean
    why: { head?: string; side?: string; ack?: string }
  }

/** 머리 첫 줄 — 계좌 갈래, 실행 수, 확인 필요, 계좌와 대조, 전체 신규 진입 중지. */
export function renderRunHeadLine({
  kinds,
  split,
  max,
  trading,
  stopped,
  ended,
  standingAll,
  status,
  failure,
  needCheck,
  reconciling,
  reconcileLine,
  reconcile,
  reconcileFailed,
  why,
  openConfirm,
  all,
}: RunHeadLineArgs) {
  return (
        <div className="run-head-line">
          {/* 이 배지는 접속 환경이 아니라 **실행 갈래**입니다. 목록에 선 갈래마다
              하나씩 섭니다 — 실행이 없으면 붙은 계좌도 없어 비워 둡니다. */}
          {kinds.map((kind) => (
            <RunKindBadge key={kind} kind={kind} />
          ))}
          {split && <EnvSplitNote text={split} />}
          {/* 실행 중·중지·종료는 이 화면의 계좌 실행 수입니다. 셋은 따로 셉니다 —
              실행 중은 중지·종료가 아닌 것입니다.
              상한은 **갈래를 안 가립니다** — 종이 실행 하나도 그 자리를 먹습니다.
              그래서 분자는 검증·계좌의 끝나지 않은 실행 전부이고(서버가 한도를 볼
              때와 같은 셈), 그 범위는 `title` 이 말합니다. 끝난 실행은 자리를 안
              먹으므로 상한의 분자에 들지 않습니다. */}
          <span className="run-counts" title={max > 0 ? '상한은 검증 실행과 함께 셉니다' : undefined}>
            {`실행 중 ${trading} · 중지 ${stopped} · 종료 ${ended} · 상한 ${standingAll}`}
            {max > 0 && ` / ${max}`}
          </span>
          {status === 'failed' && <span className="run-need">{failure}</span>}
          {needCheck > 0 && <span className="run-need">확인 필요 {needCheck}</span>}
          {/* 계좌와 다시 맞춰 보라고 청합니다. **값을 화면이 고치는 것이
              아닙니다** — 서버가 계좌를 다시 읽어 제 장부와 견줍니다.
              그 답은 **단추 바로 곁**에 섭니다 — 누른 자리에서 눈을 옮기지 않고
              읽을 수 있어야 잠깐 섰다 걷히는 결과를 놓치지 않습니다. */}
          <span className="run-reconcile">
            <button
              type="button"
              className="btn btn-quiet"
              aria-disabled={reconciling || undefined}
              aria-describedby={reconcileLine ? 'run-reconcile-why' : undefined}
              onClick={() => void reconcile()}
            >
              계좌와 대조
            </button>
            <span
              className={`run-reconcile-why${reconcileFailed ? '' : ' is-note'}`}
              id="run-reconcile-why"
              aria-live="polite"
              title={reconcileLine || undefined}
            >
              {reconcileLine}
            </span>
          </span>
          <button
            type="button"
            className="btn btn-quiet run-stopall"
            aria-disabled={trading === 0}
            aria-describedby={trading === 0 || why.head ? 'run-head-why' : undefined}
            onClick={() =>
              trading > 0 &&
              openConfirm({
                action: '전체 신규 진입 중지',
                runs: all.filter((r) => r.state !== 'paused' && r.state !== 'ended'),
                alreadyStopped: stopped,
              })
            }
          >
            전체 신규 진입 중지
          </button>
        </div>
  )
}

type RunLimitsArgs = Pick<LimitValues, 'axisLimits' | 'limitLine' | 'axis'> &
  {
    limits: ReturnType<typeof useLimits>
    setLimitsAxis: Dispatch<SetStateAction<LimitAxis | null>>
    setLimitsOpen: Dispatch<SetStateAction<boolean>>
  }

/** 머리의 계좌 손실 한도 줄과 바꾸기 단추. */
export function renderRunLimits({
  axisLimits,
  limitLine,
  axis,
  limits,
  setLimitsAxis,
  setLimitsOpen,
}: RunLimitsArgs) {
  return (
        <div className="run-limits">
          <span className="run-limits-text" title={axisLimits ? `계좌 손실 한도 · ${limitLine}` : undefined}>
            계좌 손실 한도
            {/* 어느 계좌의 한도인지는 **갈래 배지**가 말합니다(접속 환경의 계좌).
                환경을 모르면 배지 자리를 비우고 값은 「—」입니다. */}
            {axis !== null && <RunKindBadge kind={axis === 'real' ? 'real' : 'sim'} short />}
            {' · '}
            {axis === null
              ? '—'
              : axisLimits
                ? limitLine
                : limits.status === 'failed' || limits.status === 'ready'
                  ? '한도를 받지 못했습니다'
                  : '받는 중'}
          </span>
          {axis !== null && axisLimits === null && limits.status === 'failed' ? (
            <button type="button" className="btn btn-quiet" onClick={() => void loadLimits()}>
              다시
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-quiet"
              aria-disabled={axisLimits === null}
              onClick={() => {
                if (axisLimits === null || axis === null) return
                setLimitsAxis(axis)
                setLimitsOpen(true)
              }}
            >
              바꾸기
            </button>
          )}
          {axis === null && <span className="run-limits-wait">환경을 확인하는 중</span>}
        </div>
  )
}
