import { useEffect, useRef, useState, type DragEvent } from 'react'
import { Modal } from '../../../app/Modal'
import { pnlText } from '../../../data/pyrun'
import {
  DEFAULT_MAX_QTY,
  DEFAULT_ORDERS_PER_MIN,
  SPREAD_ORDERS_CONFIRM_TEXT,
  deleteRunner,
  downloadUrl,
  isFinishedRun,
  loadConvention,
  pnlLine,
  pnlOf,
  startRun,
  uploadRunner,
  type SpreadMode,
  type SpreadRunStatus,
  type SpreadRunnerFile,
  type SpreadRunners,
} from '../../../data/spread'
import { ModeBadge, StateBadge } from '../PyRunSide'

/* 팀: 「스프레드」 왼쪽 열 — ① 실행기 파일 ② 실행 목록, 그리고 「+ 실행 세우기」 폼.
 * 파이썬 전략 탭(`PyRunSide`)의 카드·줄·모달 클래스를 그대로 씁니다. */

/** `2026-11-09T09:24:33` → `11/09 09:24`. */
export function startedText(at: string | null): string {
  if (!at || at.length < 16) return ''
  return `${at.slice(5, 7)}/${at.slice(8, 10)} ${at.slice(11, 16)}`
}

type Ask = { kind: 'overwrite'; file: string; resolve: (yes: boolean) => void } | { kind: 'delete'; file: string; module?: boolean }
interface Note {
  text: string
  error: boolean
}
const BUSY_TEXT = '올리는 중입니다 — 끝난 뒤 다시 올려 주세요'

/** 「작성 규칙」 창 — 서버의 규칙 문서(마크다운)를 글 그대로. 문서가 아직 없으면 서버 문장이 선다. */
function ConventionModal({ onClose }: { onClose: () => void }) {
  const [text, setText] = useState<string | null>(null)
  const [why, setWhy] = useState<string | null>(null)
  useEffect(() => {
    const control = new AbortController()
    void loadConvention(control.signal).then((got) => {
      if (control.signal.aborted) return
      if (got.ok) setText(got.data)
      else setWhy(got.why)
    })
    return () => control.abort()
  }, [])
  return (
    <Modal label="스프레드 실행기 작성 규칙" tall onClose={onClose} head={<span className="modal-title">스프레드 실행기 작성 규칙</span>}>
      {why ? <p className="run-store-why">{why}</p> : <pre className="pyrun-convention">{text ?? '읽는 중입니다'}</pre>}
    </Modal>
  )
}

/* ── ① 실행기 파일 ─────────────────────────────────────── */

export function SpreadRunnerCard({
  list,
  why,
  busy,
  onReload,
  onList,
  onAdd,
}: {
  list: SpreadRunners | null
  why: string | null
  busy: boolean
  onReload: () => void
  onList: (next: SpreadRunners) => void
  onAdd: (file?: string) => void
}) {
  const files = list?.runners ?? []
  const modules = list?.modules ?? []
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const [working, setWorking] = useState(false)
  const [note, setNote] = useState<Note | null>(null)
  const [ask, setAsk] = useState<Ask | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteWhy, setDeleteWhy] = useState<string | null>(null)
  const [rules, setRules] = useState(false)

  async function upload(picked: File[]) {
    if (picked.length === 0) return
    if (working) {
      setNote({ text: BUSY_TEXT, error: false })
      return
    }
    const py = picked.filter((one) => one.name.toLowerCase().endsWith('.py'))
    const skipped = picked.length - py.length
    if (py.length === 0) {
      setNote({ text: `.py 파일만 올릴 수 있습니다 (건너뜀 ${skipped})`, error: true })
      return
    }
    setWorking(true)
    setNote(null)
    const done: string[] = []
    const declined: string[] = []
    const failed: string[] = []
    for (const one of py) {
      let content: string
      try {
        /* 엄격하게 풀어 UTF-8 이 아니면 올리지 않습니다(`File.text()` 는 깨진 바이트를 조용히 바꿉니다). */
        content = new TextDecoder('utf-8', { fatal: true }).decode(await one.arrayBuffer())
      } catch {
        failed.push(`${one.name}: 읽지 못했거나 UTF-8 이 아닌 파일입니다`)
        continue
      }
      let got = await uploadRunner(one.name, content, false)
      if (!got.ok && got.status === 409) {
        const yes = await new Promise<boolean>((resolve) => setAsk({ kind: 'overwrite', file: one.name, resolve }))
        setAsk(null)
        if (!yes) {
          declined.push(one.name)
          continue
        }
        got = await uploadRunner(one.name, content, true)
      }
      if (got.ok) {
        onList(got.data)
        done.push(one.name)
      } else failed.push(`${one.name}: ${got.why}`)
    }
    setWorking(false)
    const parts: string[] = []
    if (done.length) parts.push(`올렸습니다: ${done.join(', ')}`)
    if (declined.length) parts.push(`덮어쓰지 않음: ${declined.join(', ')}`)
    if (skipped) parts.push(`.py 가 아니라 건너뜀: ${skipped}`)
    parts.push(...failed)
    setNote({ text: parts.join(' · '), error: failed.length > 0 })
  }

  async function remove(file: string) {
    if (deleting) return
    setDeleting(true)
    setDeleteWhy(null)
    const got = await deleteRunner(file)
    setDeleting(false)
    if (got.ok) {
      onList(got.data)
      setAsk(null)
      setNote({ text: `지웠습니다: ${file}`, error: false })
    } else setDeleteWhy(got.why)
  }

  const hasFiles = (event: DragEvent) => event.dataTransfer.types.includes('Files')
  const closed = ask !== null || working
  const drop = {
    onDragEnter: (event: DragEvent) => {
      if (!hasFiles(event)) return
      event.preventDefault()
      if (!closed) setOver(true)
    },
    onDragOver: (event: DragEvent) => {
      if (!hasFiles(event)) return
      event.preventDefault()
      event.dataTransfer.dropEffect = closed ? 'none' : 'copy'
    },
    onDragLeave: (event: DragEvent) => {
      if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOver(false)
    },
    onDrop: (event: DragEvent) => {
      if (!hasFiles(event)) return
      event.preventDefault()
      setOver(false)
      if (closed) {
        if (working) setNote({ text: BUSY_TEXT, error: false })
        return
      }
      void upload(Array.from(event.dataTransfer.files))
    },
  }

  return (
    <div className={`card run-runs${over ? ' pyrun-drop-over' : ''}`} {...drop}>
      <div className="run-runs-head">
        <h2 className="run-card-title">실행기 파일</h2>
        <button type="button" className="btn btn-quiet" onClick={() => setRules(true)}>
          작성 규칙
        </button>
      </div>
      <p className="pyrun-folder">
        {list ? (
          <>
            .py 를 이 카드에 끌어다 놓거나 「파일 올리기」를 누르세요.{' '}
            <span className="pyrun-folder-or">
              또는 이 폴더에 직접 넣어도 됩니다: <code>{list.folder}</code>
            </span>
          </>
        ) : (
          '실행기 폴더를 읽는 중입니다'
        )}
      </p>
      {why && <p className="run-store-why">{why}</p>}
      {note && (
        <p className={`pyrun-upload-note${note.error ? ' is-error' : ''}`} role="status">
          {note.text}
        </p>
      )}
      <div className="run-list">
        {files.map((one: SpreadRunnerFile) => (
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
              <span className="run-sub">{[one.file, ...Object.keys(one.legs)].join(' · ')}</span>
              {one.error && <span className="pyrun-file-why">{one.error}</span>}
            </button>
            <button
              type="button"
              className="btn btn-quiet pyrun-row-dl"
              aria-disabled={working || undefined}
              title={`${one.file} 지우기`}
              onClick={() => {
                if (working) return
                setDeleteWhy(null)
                setAsk({ kind: 'delete', file: one.file })
              }}
            >
              지우기
            </button>
          </div>
        ))}
        {list && files.length === 0 && <p className="run-why">실행기 파일이 없습니다</p>}
      </div>
      {modules.length > 0 && (
        <div className="pyrun-modules">
          <h3 className="pyrun-modules-title">공용 모듈</h3>
          {modules.map((file) => (
            <div className="run-row pyrun-file" key={file}>
              <span className="run-row-body">
                <span className="run-sub">{file}</span>
              </span>
              <button
                type="button"
                className="btn btn-quiet pyrun-row-dl"
                aria-disabled={working || undefined}
                title={`${file} 지우기`}
                onClick={() => {
                  if (working) return
                  setDeleteWhy(null)
                  setAsk({ kind: 'delete', file, module: true })
                }}
              >
                지우기
              </button>
            </div>
          ))}
        </div>
      )}
      <div className="pyrun-side-acts">
        <button type="button" className="btn btn-quiet" aria-disabled={busy || undefined} onClick={() => !busy && onReload()}>
          폴더 다시 읽기
        </button>
        <button type="button" className="btn btn-quiet" aria-disabled={working || undefined} onClick={() => !working && input.current?.click()}>
          {working ? '올리는 중' : '파일 올리기'}
        </button>
        <button type="button" className="btn btn-primary" onClick={() => onAdd()}>
          + 실행 세우기
        </button>
      </div>
      <input
        ref={input}
        type="file"
        accept=".py"
        multiple
        hidden
        onChange={(event) => {
          const picked = Array.from(event.target.files ?? [])
          event.target.value = ''
          void upload(picked)
        }}
      />

      {rules && <ConventionModal onClose={() => setRules(false)} />}
      {ask?.kind === 'overwrite' && (
        <Modal label="덮어쓰기" closable={false} dismissable={false} onClose={() => ask.resolve(false)} head={<span className="modal-title">덮어쓰기</span>}>
          <p className="pyrun-confirm-text">
            {ask.file} 이(가) 이미 있습니다. 덮어쓸까요? 돌고 있는 실행은 처음 불러온 코드로 계속 갑니다.
          </p>
          <div className="run-add-acts">
            <button type="button" className="btn btn-quiet" onClick={() => ask.resolve(false)}>
              건너뛰기
            </button>
            <button type="button" className="btn btn-heavy" onClick={() => ask.resolve(true)}>
              덮어쓰기
            </button>
          </div>
        </Modal>
      )}
      {ask?.kind === 'delete' && (
        <Modal label="파일 지우기" closable={false} dismissable={false} onClose={() => !deleting && setAsk(null)} head={<span className="modal-title">파일 지우기</span>}>
          <p className="pyrun-confirm-text">{ask.file} 을(를) 지울까요?</p>
          {ask.module && <p className="run-hint">다른 실행기가 이 파일을 불러 쓰면 그 실행기들도 목록에서 오류로 바뀝니다.</p>}
          <p className="run-hint">돌고 있는 실행은 처음 불러온 코드로 계속 갑니다.</p>
          <div className="run-add-acts">
            <button type="button" className="btn btn-quiet" aria-disabled={deleting || undefined} onClick={() => !deleting && setAsk(null)}>
              그만두기
            </button>
            <button type="button" className="btn btn-heavy" aria-disabled={deleting || undefined} onClick={() => void remove(ask.file)}>
              {deleting ? '지우는 중' : '지우기'}
            </button>
          </div>
          <p className={`run-hint run-start-why${deleteWhy ? ' is-error' : ''}`}>{deleteWhy ?? ''}</p>
        </Modal>
      )}
    </div>
  )
}

/* ── ② 실행 목록 ─────────────────────────────────────── */

export function SpreadRunsCard({
  runs,
  why,
  shownId,
  onShow,
}: {
  runs: SpreadRunStatus[] | null
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
          const total = pnlLine(pnlOf(run).total, (value, currency) => pnlText(value, currency))
          return (
            <div className={`run-row${shown ? ' is-shown' : ''}`} key={run.id}>
              <button type="button" className="run-row-body" aria-current={shown ? 'true' : undefined} onClick={() => onShow(run.id)}>
                <span className="run-name">
                  <span className="run-name-text">{run.title || run.name || run.file}</span>
                  <ModeBadge mode={run.mode} />
                </span>
                <span className="run-sub">
                  {[run.file, ...(run.legs ?? []).map((leg) => leg.sym)].filter(Boolean).join(' · ')}
                </span>
                <span className="run-sub" title={run.id}>
                  {[startedText(run.started_at), ...total.map((one) => `누적 ${one.text}${one.estimated ? ' (추정)' : ''}`)]
                    .filter(Boolean)
                    .join(' · ')}
                </span>
                <span className="run-state">
                  <StateBadge state={run.state} />
                  {run.state === '정리 대기' && <span className="run-note">{(run.waiting_for ?? []).join(' · ')}</span>}
                  {run.halted && <span className="run-note">멈춤</span>}
                </span>
              </button>
              {isFinishedRun(run) && (
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

/** 실행 세우기 폼. 모의 계좌는 확인 얼굴을 한 번 지납니다. 거부 문장은 서버가 준 그대로 섭니다.
 *  다리별 종목은 글로 적습니다 — 비우면 실행기의 `LEGS` 표기대로 서버가 찾고(안내 글에 그 표기를 보임), 코드를 적으면 그 종목을 씁니다.
 *  (「파이썬 전략」의 종목 고르기 창은 미국달러선물·MKU 만 고르게 막혀 있어 스프레드의 어떤 선물에도 쓸 수 없습니다.) */
export function SpreadAddForm({
  files,
  seed,
  asking,
  onAsk,
  onBack,
  onCancel,
  onStarted,
}: {
  files: SpreadRunnerFile[]
  seed: string | null
  asking: boolean
  onAsk: () => void
  onBack: () => void
  onCancel: () => void
  onStarted: (run: SpreadRunStatus) => void
}) {
  const usable = files.filter((one) => !one.error)
  const [chosen, setFile] = useState<string>(seed && usable.some((one) => one.file === seed) ? seed : (usable[0]?.file ?? ''))
  const file = usable.some((one) => one.file === chosen) ? chosen : ''
  const [mode, setMode] = useState<SpreadMode>('paper')
  /** 적은 종목코드(다리 이름 → 글). 파일이 바뀌면 비웁니다. */
  const [syms, setSyms] = useState<Record<string, string>>({})
  /** 적은 값. `null` = 손대지 않음(실행기의 기본). */
  const [qty, setQty] = useState<string | null>(null)
  const [perMin, setPerMin] = useState(String(DEFAULT_ORDERS_PER_MIN))
  const [sending, setSending] = useState(false)
  const [why, setWhy] = useState<string | null>(null)

  const picked = usable.find((one) => one.file === file)
  const legs = Object.entries(picked?.legs ?? {})
  const qtyText = qty ?? String(picked?.max_qty ?? DEFAULT_MAX_QTY)
  const qtyNum = Number(qtyText)
  const perMinNum = Number(perMin)
  const qtyOk = /^\d+$/.test(qtyText.trim()) && qtyNum >= 1
  const perMinOk = /^\d+$/.test(perMin.trim()) && perMinNum >= 1
  const inputWhy = !file ? '실행기 파일을 고르세요' : !qtyOk ? '최대 보유는 1 이상의 정수입니다' : !perMinOk ? '분당 주문은 1 이상의 정수입니다' : null

  async function send() {
    if (sending || !file || inputWhy) return
    setSending(true)
    setWhy(null)
    const got = await startRun({ file, mode, syms, maxQty: qtyNum, ordersPerMin: perMinNum })
    setSending(false)
    if (got.ok) onStarted(got.data)
    else {
      setWhy(got.why)
      onBack()
    }
  }

  if (asking) {
    return (
      <div className="run-add">
        <dl className="run-confirm">
          <div className="run-confirm-row">
            <dt>실행기</dt>
            <dd>{picked ? `${picked.title || picked.name || picked.file} · ${picked.file}` : file}</dd>
          </div>
          <div className="run-confirm-row">
            <dt>방식</dt>
            <dd>
              <ModeBadge mode={mode} />
            </dd>
          </div>
          {legs.map(([name, spec]) => (
            <div className="run-confirm-row" key={name}>
              <dt>다리 {name}</dt>
              <dd>{syms[name]?.trim() ? syms[name].trim() : `${spec} (실행기 표기 — 시작할 때 서버가 정합니다)`}</dd>
            </div>
          ))}
          <div className="run-confirm-row">
            <dt>다리별 최대 보유</dt>
            <dd>{qtyNum}계약</dd>
          </div>
          <div className="run-confirm-row">
            <dt>분당 주문 상한</dt>
            <dd>{perMinNum}건</dd>
          </div>
        </dl>
        <p className="run-approve">{SPREAD_ORDERS_CONFIRM_TEXT}</p>
        <div className="run-add-acts">
          <button type="button" className="btn btn-quiet" aria-disabled={sending || undefined} onClick={() => !sending && onBack()}>
            돌아가기
          </button>
          <button type="button" className="btn btn-heavy" aria-disabled={sending || undefined} onClick={() => void send()}>
            {sending ? '세우는 중' : '모의 계좌로 시작'}
          </button>
        </div>
        <p className="run-hint run-start-why">{sending ? '다리별 시세와 잔고를 읽는 동안 기다립니다' : ''}</p>
      </div>
    )
  }

  return (
    <div className="run-add">
      <label className="run-add-row">
        <span className="run-add-label">실행기 파일</span>
        <select
          className="control"
          value={file}
          onChange={(e) => {
            setFile(e.target.value)
            setSyms({})
            setQty(null)
          }}
        >
          {files.length === 0 && <option value="">실행기 파일이 없습니다</option>}
          {files.length > 0 && file === '' && <option value="">파일을 고르세요</option>}
          {files.map((one) => (
            <option key={one.file} value={one.file} disabled={!!one.error}>
              {one.file}
              {one.error ? ' (오류)' : ''}
            </option>
          ))}
        </select>
      </label>
      <label className="run-add-row">
        <span className="run-add-label">방식</span>
        <select className="control" value={mode} onChange={(e) => setMode(e.target.value as SpreadMode)}>
          <option value="paper">종이 (주문 없음)</option>
          <option value="orders">모의 계좌</option>
        </select>
      </label>
      {legs.map(([name, spec]) => (
        <label className="run-add-row" key={name}>
          <span className="run-add-label">다리 {name} 종목</span>
          <input
            className="control spread-sym-input"
            value={syms[name] ?? ''}
            placeholder={spec}
            spellCheck={false}
            autoComplete="off"
            onChange={(e) => setSyms((had) => ({ ...had, [name]: e.target.value }))}
          />
        </label>
      ))}
      {legs.length > 0 && <p className="run-hint">비워 두면 실행기가 적은 표기(회색 글)대로 서버가 월물을 고릅니다. 특정 월물은 종목코드를 적으세요.</p>}
      <label className="run-add-row">
        <span className="run-add-label">다리별 최대 보유</span>
        <input
          className="control spread-num-input"
          inputMode="numeric"
          value={qtyText}
          aria-invalid={!qtyOk || undefined}
          onChange={(e) => setQty(e.target.value)}
        />
      </label>
      <label className="run-add-row">
        <span className="run-add-label">분당 주문 상한</span>
        <input
          className="control spread-num-input"
          inputMode="numeric"
          value={perMin}
          aria-invalid={!perMinOk || undefined}
          onChange={(e) => setPerMin(e.target.value)}
        />
      </label>
      <div className="run-add-acts">
        <button type="button" className="btn btn-quiet" aria-disabled={sending || undefined} onClick={() => !sending && onCancel()}>
          그만두기
        </button>
        <button
          type="button"
          className="btn btn-primary"
          aria-disabled={!!inputWhy || sending || undefined}
          onClick={() => {
            if (inputWhy || sending) return
            setWhy(null)
            if (mode === 'orders') onAsk()
            else void send()
          }}
        >
          {sending ? '세우는 중' : mode === 'orders' ? '다음' : '시작'}
        </button>
      </div>
      <p className={`run-hint run-start-why${why ? ' is-error' : ''}`}>
        {why ?? (sending ? '다리별 시세와 잔고를 읽는 동안 기다립니다' : (inputWhy ?? ''))}
      </p>
    </div>
  )
}
