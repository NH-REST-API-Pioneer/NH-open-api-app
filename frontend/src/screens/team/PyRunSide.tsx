import { useState } from 'react'
import {
  ORDERS_CONFIRM_TEXT,
  PY_FINISHED,
  downloadUrl,
  modeLabel,
  startRun,
  type PyRunStatus,
  type PyStrategies,
  type PyStrategyFile,
} from '../../data/pyrun'
import { moneyIn } from '../../lib/number'

/* 팀: 「파이썬 전략」 왼쪽 열 — ① 전략 파일 ② 실행 목록, 그리고 「+ 실행 세우기」 폼.
 * 얼굴은 「전략 진행」의 실행 카드(`.run-runs` · `.run-row`)를 그대로 씁니다. */

/** 실행 방식 배지. 주문이 실제로 나가는 모의 계좌가 무거운 쪽(`run-kind-sim`)이고,
 *  종이·리플레이는 흐린 점선입니다 — 종이 실행이 계좌 실행처럼 보이면 안 됩니다. */
export function ModeBadge({ mode }: { mode: string }) {
  return (
    <span className={`badge run-kind ${mode === 'orders' ? 'run-kind-sim' : 'run-kind-paper'}`}>{modeLabel(mode)}</span>
  )
}

/** 상태 배지. 낱말은 서버가 준 그대로입니다. 손을 써야 하는 「확인 필요」만 경고색입니다. */
export function StateBadge({ state }: { state: string }) {
  const tone =
    state === '확인 필요'
      ? ' run-alert'
      : state === '오류'
        ? ' pyrun-state-error'
        : state === '진행 중'
          ? ' badge-brand'
          : ''
  return <span className={`badge${tone}`}>{state}</span>
}

/** `20261030` → `10/30`. */
export function shortDate(date: string | null | undefined): string {
  if (!date || date.length < 8) return ''
  return `${date.slice(4, 6)}/${date.slice(6, 8)}`
}

/** `2026-11-03T09:24:33` → `11/03 09:24`. */
function startedText(at: string | null): string {
  if (!at || at.length < 16) return ''
  return `${at.slice(5, 7)}/${at.slice(8, 10)} ${at.slice(11, 16)}`
}

export function isFinished(run: PyRunStatus): boolean {
  return PY_FINISHED.includes(run.state)
}

/* ── ① 전략 파일 ─────────────────────────────────────── */

export function PyStrategyCard({
  list,
  why,
  busy,
  onReload,
  onAdd,
}: {
  list: PyStrategies | null
  why: string | null
  busy: boolean
  onReload: () => void
  /** 「+ 실행 세우기」. 파일 줄을 누르면 그 파일로 채워 엽니다. */
  onAdd: (file?: string) => void
}) {
  const files = list?.strategies ?? []
  return (
    <div className="card run-runs">
      <div className="run-runs-head">
        <h2 className="run-card-title">전략 파일</h2>
      </div>
      <p className="pyrun-folder">
        {list ? (
          <>
            <code>{list.folder}</code> 에 .py 를 넣으면 여기 나타납니다
          </>
        ) : (
          '전략 폴더를 읽는 중입니다'
        )}
      </p>
      {why && <p className="run-store-why">{why}</p>}
      <div className="run-list">
        {files.map((one: PyStrategyFile) => (
          <div className={`run-row pyrun-file${one.error ? ' is-broken' : ''}`} key={one.file}>
            <button
              type="button"
              className="run-row-body"
              aria-disabled={one.error ? true : undefined}
              title={one.error ? '오류가 있는 파일로는 실행을 세울 수 없습니다' : '이 파일로 실행 세우기'}
              onClick={() => !one.error && onAdd(one.file)}
            >
              <span className="run-name">
                <span className="run-name-text">{one.title || one.name || one.file}</span>
              </span>
              <span className="run-sub">{one.file}</span>
              {one.error && <span className="pyrun-file-why">{one.error}</span>}
            </button>
          </div>
        ))}
        {list && files.length === 0 && <p className="run-why">전략 파일이 없습니다</p>}
      </div>
      <div className="pyrun-side-acts">
        <button type="button" className="btn btn-quiet" aria-disabled={busy || undefined} onClick={() => !busy && onReload()}>
          폴더 다시 읽기
        </button>
        <button type="button" className="btn btn-primary" onClick={() => onAdd()}>
          + 실행 세우기
        </button>
      </div>
    </div>
  )
}

/* ── ② 실행 목록 ─────────────────────────────────────── */

export function PyRunsCard({
  runs,
  why,
  shownId,
  onShow,
}: {
  runs: PyRunStatus[] | null
  why: string | null
  shownId: string | null
  onShow: (id: string) => void
}) {
  return (
    <div className="card run-runs">
      <div className="run-runs-head">
        <h2 className="run-card-title">실행</h2>
      </div>
      {why && <p className="run-store-why">{why}</p>}
      <div className="run-list">
        {runs === null && !why && <p className="run-why">실행 목록을 받는 중입니다</p>}
        {runs?.map((run) => {
          const shown = run.id === shownId
          const pnl = run.today_pnl ?? run.summary?.net_pnl ?? null
          return (
            <div className={`run-row${shown ? ' is-shown' : ''}`} key={run.id}>
              <button
                type="button"
                className="run-row-body"
                aria-current={shown ? 'true' : undefined}
                onClick={() => onShow(run.id)}
              >
                <span className="run-name">
                  <span className="run-name-text">{run.title || run.name || run.file}</span>
                  <ModeBadge mode={run.mode} />
                </span>
                <span className="run-sub">
                  {[run.file, run.sym].filter(Boolean).join(' · ')}
                </span>
                <span className="run-sub" title={run.id}>
                  {[startedText(run.started_at), pnl !== null ? `${pnl > 0 ? '+' : ''}${moneyIn(pnl, 'KRW')}` : '']
                    .filter(Boolean)
                    .join(' · ')}
                </span>
                <span className="run-state">
                  <StateBadge state={run.state} />
                  {run.halted && <span className="run-note">멈춤</span>}
                </span>
              </button>
              {/* 끝난 실행의 결과(zip). 단추 안에 링크를 두지 않고 줄 오른쪽에 따로 섭니다. */}
              {isFinished(run) && (
                <a className="btn btn-quiet pyrun-row-dl" href={downloadUrl(run.id)} download>
                  ⬇ 결과
                </a>
              )}
            </div>
          )
        })}
        {runs !== null && runs.length === 0 && <p className="run-why">아직 실행이 없습니다</p>}
      </div>
    </div>
  )
}

/* ── + 실행 세우기 ────────────────────────────────────── */

type StartMode = 'orders' | 'paper'

/** 실행 세우기 폼. `orders` 는 확인 얼굴을 한 번 지납니다. 거부 문장은 서버가 준 그대로 섭니다. */
export function PyAddForm({
  files,
  seed,
  asking,
  onAsk,
  onBack,
  onCancel,
  onStarted,
}: {
  files: PyStrategyFile[]
  seed: string | null
  /** 확인 얼굴이 떠 있는지(모달 머리·닫기를 부르는 쪽이 정합니다). */
  asking: boolean
  onAsk: () => void
  onBack: () => void
  onCancel: () => void
  onStarted: (run: PyRunStatus) => void
}) {
  const usable = files.filter((one) => !one.error)
  const [file, setFile] = useState<string>(
    seed && usable.some((one) => one.file === seed) ? seed : (usable[0]?.file ?? ''),
  )
  const [mode, setMode] = useState<StartMode>('paper')
  const [sym, setSym] = useState('')
  const [sending, setSending] = useState(false)
  const [why, setWhy] = useState<string | null>(null)

  async function send() {
    if (sending || !file) return
    setSending(true)
    setWhy(null)
    const got = await startRun(file, mode, sym)
    setSending(false)
    if (got.ok) onStarted(got.data)
    else {
      setWhy(got.why)
      onBack()
    }
  }

  const picked = files.find((one) => one.file === file)

  if (asking) {
    return (
      <div className="run-add">
        <dl className="run-confirm">
          <div className="run-confirm-row">
            <dt>전략</dt>
            <dd>{picked ? `${picked.title || picked.name} · ${picked.file}` : file}</dd>
          </div>
          <div className="run-confirm-row">
            <dt>방식</dt>
            <dd>
              <ModeBadge mode={mode} />
            </dd>
          </div>
          <div className="run-confirm-row">
            <dt>종목</dt>
            <dd>{sym.trim() || '최근월물'}</dd>
          </div>
        </dl>
        <p className="run-approve">{ORDERS_CONFIRM_TEXT}</p>
        <div className="run-add-acts">
          <button type="button" className="btn btn-quiet" aria-disabled={sending || undefined} onClick={() => !sending && onBack()}>
            돌아가기
          </button>
          <button
            type="button"
            className="btn btn-heavy"
            aria-disabled={sending || undefined}
            onClick={() => void send()}
          >
            {sending ? '세우는 중' : '모의 계좌로 시작'}
          </button>
        </div>
        <p className="run-hint run-start-why">{sending ? '준비 봉을 받는 동안 기다립니다' : ''}</p>
      </div>
    )
  }

  return (
    <div className="run-add">
      <label className="run-add-row">
        <span className="run-add-label">전략 파일</span>
        <select className="control" value={file} onChange={(e) => setFile(e.target.value)}>
          {files.length === 0 && <option value="">전략 파일이 없습니다</option>}
          {files.map((one) => (
            /* 오류가 있는 파일은 고를 수 없습니다 — 까닭은 왼쪽 목록에 섭니다. */
            <option key={one.file} value={one.file} disabled={!!one.error}>
              {one.file}
              {one.error ? ' (오류)' : ''}
            </option>
          ))}
        </select>
      </label>
      <label className="run-add-row">
        <span className="run-add-label">방식</span>
        <select className="control" value={mode} onChange={(e) => setMode(e.target.value as StartMode)}>
          <option value="paper">종이 (주문 없음)</option>
          <option value="orders">모의 계좌</option>
        </select>
      </label>
      <label className="run-add-row">
        <span className="run-add-label">종목</span>
        <input
          className="control"
          value={sym}
          placeholder="빈칸 = 최근월물"
          spellCheck={false}
          onChange={(e) => setSym(e.target.value)}
        />
      </label>
      <div className="run-add-acts">
        <button type="button" className="btn btn-quiet" aria-disabled={sending || undefined} onClick={() => !sending && onCancel()}>
          그만두기
        </button>
        <button
          type="button"
          className="btn btn-primary"
          aria-disabled={!file || sending || undefined}
          onClick={() => {
            if (!file || sending) return
            setWhy(null)
            if (mode === 'orders') onAsk()
            else void send()
          }}
        >
          {sending ? '세우는 중' : mode === 'orders' ? '다음' : '시작'}
        </button>
      </div>
      {/* 서버가 막은 문장(409)·다른 사이트(403)는 그대로 섭니다. */}
      <p className={`run-hint run-start-why${why ? ' is-error' : ''}`}>
        {why ?? (sending ? '준비 봉을 받는 동안 기다립니다' : '')}
      </p>
    </div>
  )
}
