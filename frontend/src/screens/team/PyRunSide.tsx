import { useEffect, useRef, useState, type DragEvent } from 'react'
import { Modal } from '../../app/Modal'
import {
  ORDERS_CONFIRM_TEXT,
  PY_FINISHED,
  createSchedule,
  currencyOf,
  dateDigits,
  deleteSchedule,
  deleteStrategy,
  downloadUrl,
  isRealtime,
  loadConvention,
  modeLabel,
  pnlText,
  resumeSchedule,
  scheduleTimeText,
  startRun,
  uploadStrategy,
  type PyRunStatus,
  type PySchedule,
  type PyStrategies,
  type PyStrategyFile,
} from '../../data/pyrun'
import { useMasterStatus } from '../../lib/useMaster'
import { PySymbolPicker, symConfirmText } from './PySymbolPicker'

/* 팀: 「파이썬 전략」 왼쪽 열 — ① 전략 파일 ② 실행 목록, 그리고 「+ 실행 세우기」 폼.
 * 얼굴은 「전략 진행」의 실행 카드(`.run-runs` · `.run-row`)를 그대로 씁니다. */

/** 실행 방식 배지. 주문이 실제로 나가는 모의 계좌가 무거운 쪽(`run-kind-sim`)이고,
 *  종이·리플레이는 흐린 점선입니다 — 종이 실행이 계좌 실행처럼 보이면 안 됩니다. */
export function ModeBadge({ mode }: { mode: string }) {
  return (
    <span className={`badge run-kind ${mode === 'orders' ? 'run-kind-sim' : 'run-kind-paper'}`}>{modeLabel(mode)}</span>
  )
}

/** 실행기 종류 배지 — 초 단위로 도는 실시간 실행에만 「실시간」을 답니다(1분봉은 배지 없음, 지금과 같음). */
export function KindBadge({ kind }: { kind: string | null | undefined }) {
  return kind === 'realtime' ? <span className="badge">실시간</span> : null
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

/** `20261030`(또는 `2026-10-30`) → `10/30`. */
export function shortDate(date: string | null | undefined): string {
  const digits = dateDigits(date)
  if (!digits) return ''
  return `${digits.slice(4, 6)}/${digits.slice(6, 8)}`
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

/** 카드가 띄우는 확인창. 덮어쓰기는 `resolve` 로 올리기 순서에 답을 돌려줍니다(여러 파일은 하나씩 차례로 묻습니다). */
type Ask = { kind: 'overwrite'; file: string; resolve: (yes: boolean) => void } | { kind: 'delete'; file: string; module?: boolean }

/** 올리기가 끝난 뒤 카드에 남는 한 줄. */
interface Note {
  text: string
  error: boolean
}

/** 올리는 중에 또 파일이 오면 알리는 문장. */
const BUSY_TEXT = '올리는 중입니다 — 끝난 뒤 다시 올려 주세요'

/** 「작성 규칙」 창 — 서버의 규칙 문서(마크다운)를 꾸미지 않고 글 그대로 보입니다. 열 때마다 새로 받습니다. */
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
    <Modal label="전략 파일 작성 규칙" tall onClose={onClose} head={<span className="modal-title">전략 파일 작성 규칙</span>}>
      {why ? (
        <p className="run-store-why">{why}</p>
      ) : (
        <pre className="pyrun-convention">{text ?? '읽는 중입니다'}</pre>
      )}
    </Modal>
  )
}

export function PyStrategyCard({
  list,
  why,
  busy,
  onReload,
  onList,
  onAdd,
}: {
  list: PyStrategies | null
  why: string | null
  busy: boolean
  onReload: () => void
  /** 올리기·지우기 응답(갱신된 목록)을 화면에 반영합니다. */
  onList: (next: PyStrategies) => void
  /** 「+ 실행 세우기」. 파일 줄을 누르면 그 파일로 채워 엽니다. */
  onAdd: (file?: string) => void
}) {
  const files = list?.strategies ?? []
  const modules = list?.modules ?? []
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const [working, setWorking] = useState(false)
  const [note, setNote] = useState<Note | null>(null)
  const [ask, setAsk] = useState<Ask | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteWhy, setDeleteWhy] = useState<string | null>(null)
  const [rules, setRules] = useState(false)

  /** 고른 파일들을 하나씩 올립니다. 같은 이름이 있으면(409) 그 자리에서 덮어쓸지 묻고 답을 기다립니다. */
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
      let bytes: ArrayBuffer
      try {
        bytes = await one.arrayBuffer()
      } catch {
        failed.push(`${one.name}: 파일을 읽지 못했습니다`)
        continue
      }
      /* `File.text()` 는 깨진 바이트를 조용히 바꿔 버립니다 — 엄격하게 풀어 UTF-8 이 아니면 올리지 않습니다.
         BOM 은 풀면서 떼어집니다(파이썬은 BOM 이 없어도 읽습니다). */
      let content: string
      try {
        content = new TextDecoder('utf-8', { fatal: true }).decode(bytes)
      } catch {
        failed.push(`${one.name}: UTF-8 이 아닌 파일은 올릴 수 없습니다`)
        continue
      }
      let got = await uploadStrategy(one.name, content, false)
      if (!got.ok && got.status === 409) {
        const yes = await new Promise<boolean>((resolve) => setAsk({ kind: 'overwrite', file: one.name, resolve }))
        setAsk(null)
        if (!yes) {
          declined.push(one.name)
          continue
        }
        got = await uploadStrategy(one.name, content, true)
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
    const got = await deleteStrategy(file)
    setDeleting(false)
    if (got.ok) {
      onList(got.data)
      setAsk(null)
      setNote({ text: `지웠습니다: ${file}`, error: false })
    } else setDeleteWhy(got.why)
  }

  const hasFiles = (event: DragEvent) => event.dataTransfer.types.includes('Files')
  /* 확인창이 떠 있거나 올리는 중에는 끌어다 놓기를 받지 않습니다. 확인창은 이 카드 안에 그려져 놓기가
     여기까지 올라오는데, 그때 올리기를 또 시작하면 묻던 지우기 확인이 덮어쓰기 확인으로 바뀌어 사라집니다.
     그래도 `preventDefault` 는 해야 합니다 — 안 그러면 브라우저가 놓은 파일을 열어 앱을 떠납니다. */
  const closed = ask !== null || working
  const drop = {
    onDragEnter: (event: DragEvent) => {
      if (!hasFiles(event)) return
      event.preventDefault()
      if (closed) return
      setOver(true)
    },
    onDragOver: (event: DragEvent) => {
      if (!hasFiles(event)) return
      event.preventDefault() // 이게 있어야 놓을 수 있습니다
      event.dataTransfer.dropEffect = closed ? 'none' : 'copy'
    },
    onDragLeave: (event: DragEvent) => {
      // 카드 안의 자식 사이를 오갈 때는 켜 둡니다.
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
        <h2 className="run-card-title">전략 파일</h2>
        <button type="button" className="btn btn-quiet" onClick={() => setRules(true)}>
          작성 규칙
        </button>
      </div>
      <p className="pyrun-folder">
        {list ? (
          <>
            .py 를 이 카드에 끌어다 놓거나 「파일 올리기」를 누르세요. <span className="pyrun-folder-or">또는 이 폴더에 직접 넣어도 됩니다: <code>{list.folder}</code></span>
          </>
        ) : (
          '전략 폴더를 읽는 중입니다'
        )}
      </p>
      {why && <p className="run-store-why">{why}</p>}
      {note && (
        <p className={`pyrun-upload-note${note.error ? ' is-error' : ''}`} role="status">
          {note.text}
        </p>
      )}
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
              {!one.error &&
                (one.notes ?? []).map((text) => (
                  <span className="pyrun-file-note" key={text}>
                    {text}
                  </span>
                ))}
            </button>
            {/* 지우기는 줄 몸(실행 세우기) 옆에 따로 섭니다 — 단추 안에 단추를 두지 않습니다. */}
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
        {list && files.length === 0 && <p className="run-why">전략 파일이 없습니다</p>}
      </div>
      {/* 공용 모듈 — 전략 파일이 불러 쓰는 코드(전략 클래스 없음). 실행은 못 세우고 이름만 서며 지울 수는 있습니다. */}
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
        <button
          type="button"
          className="btn btn-quiet"
          aria-disabled={working || undefined}
          onClick={() => !working && input.current?.click()}
        >
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
          event.target.value = '' // 같은 파일을 다시 골라도 change 가 오게
          void upload(picked)
        }}
      />

      {rules && <ConventionModal onClose={() => setRules(false)} />}
      {ask?.kind === 'overwrite' && (
        <Modal
          label="덮어쓰기"
          closable={false}
          dismissable={false}
          onClose={() => ask.resolve(false)}
          head={<span className="modal-title">덮어쓰기</span>}
        >
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
        <Modal
          label="파일 지우기"
          closable={false}
          dismissable={false}
          onClose={() => !deleting && setAsk(null)}
          head={<span className="modal-title">파일 지우기</span>}
        >
          <p className="pyrun-confirm-text">{ask.file} 을(를) 지울까요?</p>
          {ask.module && (
            <p className="run-hint">다른 전략이 이 파일을 불러 쓰면 그 전략들도 목록에서 오류로 바뀝니다.</p>
          )}
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
                  <KindBadge kind={run.kind} />
                </span>
                <span className="run-sub">
                  {/* 실시간은 신호 종목(KRX) → 주문 종목(MKU). */}
                  {[run.file, isRealtime(run) && run.signal_sym ? `${run.signal_sym} → ${run.sym ?? ''}` : run.sym]
                    .filter(Boolean)
                    .join(' · ')}
                </span>
                <span className="run-sub" title={run.id}>
                  {[startedText(run.started_at), pnl !== null ? pnlText(pnl, currencyOf(run)) : '']
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

/* ── 매일 자동 시작 ─────────────────────────────────────── */

/** 자동 시작 목록. 없으면(그리고 알릴 까닭도 없으면) 카드를 그리지 않습니다. */
export function PySchedulesCard({
  items,
  why,
  onChanged,
  onWhy,
}: {
  items: PySchedule[] | null
  why: string | null
  onChanged: () => void
  onWhy: (why: string | null) => void
}) {
  const [busy, setBusy] = useState<string | null>(null)
  if (!why && (items === null || items.length === 0)) return null

  async function act(id: string, run: () => Promise<{ ok: boolean; why?: string }>) {
    if (busy) return
    setBusy(id)
    const got = await run()
    setBusy(null)
    onWhy(got.ok ? null : (got.why ?? '요청이 실패했습니다'))
    onChanged()
  }

  return (
    <div className="card run-runs pyrun-schedules">
      <div className="run-runs-head">
        <h2 className="run-card-title">매일 자동 시작</h2>
      </div>
      {why && <p className="run-store-why">{why}</p>}
      <div className="run-list">
        {items?.map((one) => (
          <div className="run-row" key={one.id}>
            <div className="run-row-body">
              <span className="run-name">
                <span className="run-name-text">{one.file}</span>
                <ModeBadge mode={one.mode} />
              </span>
              {one.blocked ? (
                <span className="run-sub is-error">멈춤 — {one.blocked}</span>
              ) : (
                <span className="run-sub">다음 시작 {scheduleTimeText(one.next_start) || '—'}</span>
              )}
              {one.last_result && <span className="run-sub">{one.last_result}</span>}
            </div>
            <span className="pyrun-schedule-acts">
              {one.blocked && (
                <button
                  type="button"
                  className="btn btn-quiet"
                  aria-disabled={busy !== null || undefined}
                  onClick={() => void act(one.id, () => resumeSchedule(one.id))}
                >
                  다시 켜기
                </button>
              )}
              <button
                type="button"
                className="btn btn-quiet"
                aria-disabled={busy !== null || undefined}
                onClick={() => void act(one.id, () => deleteSchedule(one.id))}
              >
                끄기
              </button>
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── + 실행 세우기 ────────────────────────────────────── */

type StartMode = 'orders' | 'paper'

const DAILY_TEXT =
  '다음 장 날부터 장 시작 5분 전(MKU 08:20 · 국내 08:55)에 같은 파일·방식으로 새 실행을 세웁니다. 종목은 그날의 최근월물입니다. ' +
  '앞선 실행이 「확인 필요」·「오류」로 끝나면 세우지 않고 멈춰 둡니다.'

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
  /** `scheduleWhy` = 「매일 자동 시작」을 골랐는데 예약을 못 만든 까닭(실행은 이미 섰음). 골랐다면 `scheduled` 가 참. */
  onStarted: (run: PyRunStatus, scheduled: boolean, scheduleWhy: string | null) => void
}) {
  const usable = files.filter((one) => !one.error)
  const [chosen, setFile] = useState<string>(
    seed && usable.some((one) => one.file === seed) ? seed : (usable[0]?.file ?? ''),
  )
  /* 고른 파일이 그 사이 지워졌거나(전략 파일 카드의 「지우기」) 못 쓰게 됐으면 선택을 비웁니다 — 없는 파일로 시작을 청하지 않게. */
  const file = usable.some((one) => one.file === chosen) ? chosen : ''
  const [mode, setMode] = useState<StartMode>('paper')
  const [sym, setSym] = useState('')
  /** 실시간 전략의 신호 종목(KRX). 빈 글 = 국내 최근월물. */
  const [signalSym, setSignalSym] = useState('')
  /** 매일 자동 시작 — 지금 세운 실행 뒤로 장이 열리는 날마다 같은 파일·방식으로(그날의 최근월물). */
  const [daily, setDaily] = useState(false)
  const [sending, setSending] = useState(false)
  const [why, setWhy] = useState<string | null>(null)
  // 확인 얼굴의 종목 글이 마스터를 읽으므로, 마스터가 도착하면 다시 그립니다.
  useMasterStatus()

  const picked = files.find((one) => one.file === file)
  const realtime = picked?.kind === 'realtime'
  /* 비워 둘 때 서버가 고를 시장 — 실시간은 주문이 늘 MKU, 1분봉은 전략 TICK 으로 정해집니다(모르면 국내). */
  const orderMarket = realtime ? 'overseas' : (picked?.market ?? 'domestic')

  async function send() {
    if (sending || !file) return
    setSending(true)
    setWhy(null)
    /* 실시간 전략만 `signal_sym` 을 보냅니다 — 1분봉 전략에 주면 서버가 409 로 거절합니다. */
    const got = await startRun(file, mode, sym, realtime ? signalSym : undefined)
    if (got.ok) {
      /* 실행은 섰습니다. 예약이 거부돼도 실행은 그대로 두고 까닭만 알립니다. */
      const made = daily ? await createSchedule(file, mode, got.data.id) : null
      setSending(false)
      onStarted(got.data, daily, made && !made.ok ? made.why : null)
    } else {
      setSending(false)
      setWhy(got.why)
      onBack()
    }
  }

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
          {realtime && (
            <div className="run-confirm-row">
              <dt>신호 종목(KRX)</dt>
              <dd>{symConfirmText(signalSym, 'domestic')}</dd>
            </div>
          )}
          <div className="run-confirm-row">
            <dt>{realtime ? '주문 종목(MKU)' : '종목'}</dt>
            <dd>{symConfirmText(sym, orderMarket)}</dd>
          </div>
          {daily && (
            <div className="run-confirm-row">
              <dt>매일 자동 시작</dt>
              <dd>{DAILY_TEXT}</dd>
            </div>
          )}
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
        <select
          className="control"
          value={file}
          onChange={(e) => {
            setFile(e.target.value)
            /* 파일이 바뀌면 고른 종목을 비웁니다 — 실시간·1분봉은 칸 수와 고를 수 있는 종목이 달라 앞 선택이 새 칸에 맞지 않을 수 있습니다. */
            setSym('')
            setSignalSym('')
          }}
        >
          {files.length === 0 && <option value="">전략 파일이 없습니다</option>}
          {files.length > 0 && file === '' && <option value="">파일을 고르세요</option>}
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
      {/* 종목은 검색해서 고릅니다 — 미국달러선물·MKU 만 고를 수 있고, 안 고르면 서버가 최근월물을 정합니다.
          실시간 전략은 칸이 둘입니다: 신호를 보는 KRX 종목과 주문이 나가는 MKU 종목. */}
      {realtime ? (
        <>
          <PySymbolPicker sym={signalSym} onChange={setSignalSym} label="신호 종목(KRX)" allow="usd" market="domestic" />
          <PySymbolPicker sym={sym} onChange={setSym} label="주문 종목(MKU)" allow="mku" market="overseas" />
        </>
      ) : (
        <PySymbolPicker sym={sym} onChange={setSym} market={orderMarket} />
      )}
      <label className="run-add-row pyrun-daily">
        <input type="checkbox" checked={daily} onChange={(e) => setDaily(e.target.checked)} />
        <span>매일 자동 시작</span>
      </label>
      {daily && <p className="run-hint">{DAILY_TEXT}</p>}
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
