import { useState } from 'react'
import { Modal } from '../../../app/Modal'
import { useSpreadRun, useSpreadRunners, useSpreadRuns, type SpreadRunStatus } from '../../../data/spread'
import { SpreadAddForm, SpreadRunnerCard, SpreadRunsCard } from './SpreadSide'
import { SpreadMain } from './SpreadMain'
import '../pyrun.css'
import './spread.css'

/* 팀: 전략주문 › 「스프레드」.
 *
 * 실행기 폴더(`~/NHFutures/spreads`)의 파일이 두 종목 이상(다리)을 한 번에 거래하는 실행을 서버가 돌리고,
 * 이 화면은 그것을 봅니다. 자리는 「파이썬 전략」과 같습니다 — 왼쪽 250 에 ① 실행기 파일 ② 실행 목록,
 * 오른쪽에 머리줄·상태 막대·차트·날짜별 요약·아래 표. 클래스와 색은 그 화면의 것을 그대로 씁니다.
 *
 * 2초마다 다시 묻고, 이 탭을 떠나면(화면이 내려가면) 묻기를 멈춥니다. 브라우저를 닫아도 실행은 서버에서 계속 돕니다.
 */

/** 다른 탭에 다녀와도 보던 실행으로 돌아오도록 화면 밖에 둡니다(저장하지는 않습니다). */
let lastShown: string | null = null

export function SpreadScreen() {
  const runners = useSpreadRunners()
  const { runs: polled, why: runsWhy } = useSpreadRuns()
  const [picked, setPicked] = useState<string | null>(lastShown)
  /* 방금 세운 실행. 다음 목록 폴링이 그 실행을 담기 전까지 목록 앞에 끼워 둡니다. */
  const [started, setStarted] = useState<SpreadRunStatus | null>(null)
  const startedListed = started !== null && (polled?.some((run) => run.id === started.id) ?? false)
  const runs = started === null || startedListed ? polled : [started, ...(polled ?? []).filter((run) => run.id !== started.id)]
  const shownId = runs?.some((run) => run.id === picked) ? picked : (runs?.[0]?.id ?? null)
  const view = useSpreadRun(shownId)

  const [add, setAdd] = useState<{ seed: string | null } | null>(null)
  const [asking, setAsking] = useState(false)

  const show = (id: string) => {
    lastShown = id
    setPicked(id)
  }
  const files = runners.list?.runners ?? []

  return (
    <div className="run">
      <div className="run-body">
        <aside className="run-side" aria-label="실행기 파일과 실행 목록">
          <div className="run-side-inner">
            <SpreadRunnerCard
              list={runners.list}
              why={runners.why}
              busy={runners.busy}
              onReload={() => void runners.reload()}
              onList={runners.apply}
              onAdd={(file) => {
                setAsking(false)
                setAdd({ seed: file ?? null })
              }}
            />
            <SpreadRunsCard runs={runs} why={runsWhy} shownId={shownId} onShow={show} />
          </div>
        </aside>

        {runs !== null && runs.length === 0 ? (
          <div className="run-main notice">
            <p className="notice-title">아직 실행이 없습니다</p>
            <button type="button" className="btn btn-primary notice-action" onClick={() => setAdd({ seed: null })}>
              + 실행 세우기
            </button>
          </div>
        ) : (
          <SpreadMain
            key={shownId ?? ''}
            view={view}
            onStarted={(run) => {
              setStarted(run)
              show(run.id)
            }}
          />
        )}
      </div>

      {add && (
        <Modal
          label={asking ? '모의 계좌로 시작' : '실행 세우기'}
          closable={!asking}
          dismissable={!asking}
          onClose={() => (asking ? setAsking(false) : setAdd(null))}
          head={<span className="modal-title">{asking ? '모의 계좌로 시작' : '실행 세우기'}</span>}
        >
          <SpreadAddForm
            files={files}
            seed={add.seed}
            asking={asking}
            onAsk={() => setAsking(true)}
            onBack={() => setAsking(false)}
            onCancel={() => setAdd(null)}
            onStarted={(run) => {
              setAsking(false)
              setAdd(null)
              setStarted(run)
              show(run.id)
            }}
          />
        </Modal>
      )}
    </div>
  )
}
