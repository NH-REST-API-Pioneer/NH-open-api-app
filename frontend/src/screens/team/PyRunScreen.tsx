import { useState } from 'react'
import { Modal } from '../../app/Modal'
import { usePyRun, usePyRuns, usePySchedules, usePyStrategies, type PyRunStatus } from '../../data/pyrun'
import { PyAddForm, PyRunsCard, PySchedulesCard, PyStrategyCard } from './PyRunSide'
import { PyRunMain } from './PyRunMain'
import './pyrun.css'

/* 팀: 전략주문 › 「파이썬 전략」.
 *
 * 전략 폴더(`~/NHFutures/strategies`)의 파이썬 전략 파일을 서버가 돌리고, 이 화면은 그것을 봅니다.
 * 자리는 「전략 진행」과 같습니다 — 왼쪽 250 에 ① 전략 파일 ② 실행 목록, 오른쪽에 ③ 머리줄·상태 막대
 * ④ 차트 ⑤ 지금 판단 ⑥ 아래 표. 클래스와 색은 그 화면의 것을 그대로 씁니다.
 *
 * 2초마다 다시 묻고, 이 탭을 떠나면(화면이 내려가면) 묻기를 멈춥니다. 브라우저를 닫아도 실행은
 * 서버에서 계속 돕니다.
 */

/** 다른 탭에 다녀와도 보던 실행으로 돌아오도록 화면 밖에 둡니다(저장하지는 않습니다). */
let lastShown: string | null = null

export function PyRunScreen() {
  const strategies = usePyStrategies()
  const { runs: polled, why: runsWhy } = usePyRuns()
  const schedules = usePySchedules()
  const [picked, setPicked] = useState<string | null>(lastShown)
  /* 방금 세운 실행. 다음 목록 폴링이 그 실행을 담기 전까지 목록 앞에 끼워 둡니다 — 안 그러면 그 사이
     `shownId` 가 가장 최근 실행으로 떨어져 앞 실행이 잠깐 보이고 폴링됩니다. 목록에 오면 버립니다. */
  const [started, setStarted] = useState<PyRunStatus | null>(null)
  const startedListed = started !== null && (polled?.some((run) => run.id === started.id) ?? false)
  const runs =
    started === null || startedListed ? polled : [started, ...(polled ?? []).filter((run) => run.id !== started.id)]
  /* 고른 실행이 목록에 없으면(처음·지워진 폴더) 가장 최근 실행을 봅니다. */
  const shownId = runs?.some((run) => run.id === picked) ? picked : (runs?.[0]?.id ?? null)
  const view = usePyRun(shownId)

  const [add, setAdd] = useState<{ seed: string | null } | null>(null)
  const [asking, setAsking] = useState(false)

  const show = (id: string) => {
    lastShown = id
    setPicked(id)
  }
  const files = strategies.list?.strategies ?? []

  return (
    <div className="run">
      <div className="run-body">
        <aside className="run-side" aria-label="전략 파일과 실행 목록">
          <div className="run-side-inner">
            <PyStrategyCard
              list={strategies.list}
              why={strategies.why}
              busy={strategies.busy}
              onReload={() => void strategies.reload()}
              onList={strategies.apply}
              onAdd={(file) => {
                setAsking(false)
                setAdd({ seed: file ?? null })
              }}
            />
            <PySchedulesCard
              items={schedules.items}
              why={schedules.why}
              onChanged={schedules.refresh}
              onWhy={schedules.setNote}
            />
            <PyRunsCard runs={runs} why={runsWhy} shownId={shownId} onShow={show} />
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
          <PyRunMain key={shownId ?? ''} view={view} files={files} />
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
          <PyAddForm
            files={files}
            seed={add.seed}
            asking={asking}
            onAsk={() => setAsking(true)}
            onBack={() => setAsking(false)}
            onCancel={() => setAdd(null)}
            onStarted={(run, scheduled, scheduleWhy) => {
              setAsking(false)
              setAdd(null)
              setStarted(run)
              show(run.id)
              if (scheduled) {
                schedules.refresh()
                schedules.setNote(scheduleWhy ? `실행은 섰지만 자동 시작을 만들지 못했습니다 — ${scheduleWhy}` : null)
              }
            }}
          />
        </Modal>
      )}
    </div>
  )
}
