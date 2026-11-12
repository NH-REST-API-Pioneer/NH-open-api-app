import { useMemo, useRef, useState, type ReactNode } from 'react'
import { Modal } from '../../../app/Modal'
import { pnlText, type PyJournalRow } from '../../../data/pyrun'
import {
  canInherit,
  downloadUrl,
  isFinishedRun,
  legsOf,
  pnlLine,
  pnlOf,
  previewInherit,
  priceIsGuess,
  startInherit,
  stopRun,
  type InheritPreview,
  type SpreadPnlByCur,
  type SpreadRunStatus,
  type SpreadRunView,
} from '../../../data/spread'
import { MINUS, toneOf } from '../../../lib/number'
import { ModeBadge, StateBadge } from '../PyRunSide'
import { SpreadChart } from './SpreadChart'
import { startedText } from './SpreadSide'

/* 팀: 「스프레드」 오른쪽 — 머리줄 · 상태 막대 · 차트 · 아래 표 · 날짜별 요약.
 * 자리와 클래스는 「파이썬 전략」(`PyRunMain`)과 같습니다. */

export const SPREAD_BOTTOM_TABS = ['체결', '사건', '값 기록', 'API 로그'] as const
type BottomTab = (typeof SPREAD_BOTTOM_TABS)[number]

const ROW_CAP = 500
/** 사건 표에서 뺄 줄 — `minute` 은 분마다 한 줄이라 차트에만 쓰고, 나머지는 각자 표가 있습니다. */
const NOT_EVENT = new Set(['minute', 'fill', 'order', 'log'])

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/** 사건 표의 「내용」. `leg`(다리 확인·월물 교체)와 `gap`(빠진 분)은 `text` 가 없어 칸에서 글을 만듭니다. */
function eventText(row: PyJournalRow): string {
  if (row.kind === 'leg') {
    const sym = row.old ? `${String(row.old)} → ${String(row.sym ?? '')}` : String(row.sym ?? '')
    const tick = num(row.tick)
    const value = num(row.tick_value)
    const parts = [
      `${String(row.leg ?? '')} ${sym}`.trim(),
      row.exchange ? String(row.exchange) : '',
      tick !== null && value !== null ? `틱 ${tick} = ${value} ${String(row.currency ?? '')}`.trim() : '',
      row.expiry ? `만기 ${String(row.expiry)}` : '',
      row.why ? String(row.why) : '',
    ]
    return parts.filter(Boolean).join(' · ')
  }
  if (row.kind === 'gap') {
    // `first`·`last` 는 「YYYYMMDD HHMMSS」(분 시작) — 시:분만 보입니다.
    const hm = (v: unknown) => {
      const t = String(v ?? '').trim().split(' ').pop() ?? ''
      return t.length >= 4 ? `${t.slice(0, 2)}:${t.slice(2, 4)}` : t
    }
    const first = hm(row.first)
    const last = hm(row.last)
    const span = first && last && first !== last ? `${first}~${last}` : first
    return [span ? `${span} 봉 빠짐` : '', String(row.cause ?? '')].filter(Boolean).join(' · ')
  }
  return String(row.text ?? row.reason ?? row.cause ?? '')
}

/** 가격 — 받은 자릿수 그대로(최대 6), 천 단위 구분. */
function priceText(value: unknown): string {
  const v = num(value)
  if (v === null) return '—'
  const text = Math.abs(v).toLocaleString('en-US', { maximumFractionDigits: 6 })
  return v < 0 ? `${MINUS}${text}` : text
}

function qtyText(value: unknown): string {
  const v = num(value)
  if (v === null) return '—'
  return v > 0 ? `+${v}` : v < 0 ? `${MINUS}${Math.abs(v)}` : '0'
}

function atClock(at: unknown): string {
  return typeof at === 'string' && at.length >= 19 ? at.slice(11, 19) : '—'
}

/** `093000` → `09:30:00`. */
function clockText(time: unknown): string {
  if (typeof time !== 'string' || time.length < 4) return '—'
  return `${time.slice(0, 2)}:${time.slice(2, 4)}${time.length >= 6 ? `:${time.slice(4, 6)}` : ''}`
}

function rowClock(row: PyJournalRow): string {
  return row.clock ? clockText(row.clock) : atClock(row.at)
}

function dayText(day: string): string {
  return /^\d{8}$/.test(day) ? `${day.slice(0, 4)}-${day.slice(4, 6)}-${day.slice(6, 8)}` : day
}

function EmptyRow({ span, text }: { span: number; text: string }) {
  return (
    <tr>
      <td className="run-empty-row" colSpan={span}>
        {text}
      </td>
    </tr>
  )
}

function newestFirst<T>(rows: T[]): T[] {
  return rows.slice(-ROW_CAP).reverse()
}

/** 손익 글 + 추정 표지. 체결가를 모르는 체결이 들어간 값은 「추정」, 수수료를 모르는 체결이 있으면 그 수를 적습니다. */
function PnlText({ value, currency, estimated, feeUnknown }: { value: number; currency: string; estimated: boolean; feeUnknown: number }) {
  return (
    <>
      <b className={toneOf(value) || undefined}>{pnlText(value, currency)}</b>
      {estimated && <span className="badge spread-est" title="체결가를 읽지 못한 체결이 들어 있어 기준가로 센 값입니다">추정</span>}
      {feeUnknown > 0 && <span className="run-note"> 수수료 모름 {feeUnknown}건</span>}
    </>
  )
}

/* ── 오른쪽 전체 ───────────────────────────────────────── */

export function SpreadMain({
  view,
  onStarted,
}: {
  view: SpreadRunView
  /** 이어받기로 새 실행이 섰을 때. */
  onStarted: (run: SpreadRunStatus) => void
}) {
  const { run, journal, apiLog, apiTotal, bars, why } = view
  const [bottom, setBottom] = useState<BottomTab>('체결')
  const [askStop, setAskStop] = useState(false)
  const [acting, setActing] = useState(false)
  const [actWhy, setActWhy] = useState<string | null>(null)
  /** 이어받기 시작 요청이 나가 있는지(동기) — 상태 갱신 전의 두 번 누름을 막습니다. */
  const inheritInFlight = useRef(false)
  const [inherit, setInherit] = useState<{ preview: InheritPreview | null; why: string | null; sending: boolean } | null>(null)

  if (!run) {
    return (
      <div className="run-main notice">
        <p className="notice-title">{why ?? '실행을 받는 중입니다'}</p>
      </div>
    )
  }

  const finished = isFinishedRun(run)
  const legs = legsOf(run)
  const halted = run.halted ? String(run.halted) : null
  const waiting = run.state === '정리 대기'
  const { today, total, todayLabel } = pnlOf(run)
  /* 이 앱에서 지금 도는 실행만 중지할 수 있습니다(서버가 아니면 409). 끝난 실행은 누를 수 없습니다. */
  const canStop = !finished
  const inheritable = canInherit(run)

  async function doStop() {
    if (!run || acting) return
    setActing(true)
    setActWhy(null)
    const got = await stopRun(run.id)
    setActing(false)
    if (got.ok) setAskStop(false)
    else setActWhy(got.why)
  }

  async function openInherit() {
    if (!run) return
    setInherit({ preview: null, why: null, sending: false })
    const got = await previewInherit(run.id)
    setInherit({ preview: got.ok ? got.data : null, why: got.ok ? null : got.why, sending: false })
  }

  async function sendInherit() {
    if (inheritInFlight.current || !run || !inherit?.preview || inherit.sending) return
    inheritInFlight.current = true
    const preview = inherit.preview
    setInherit({ ...inherit, sending: true, why: null })
    /* 확인 얼굴에 보인 수량 그대로 보냅니다 — 그 사이 잔고가 달라졌으면 서버가 409 로 거절합니다. */
    const expect: Record<string, number> = {}
    for (const [name, leg] of Object.entries(preview.legs)) expect[name] = leg.qty
    const got = await startInherit(run.id, preview.file ?? run.file, expect)
    inheritInFlight.current = false
    if (got.ok) {
      setInherit(null)
      onStarted(got.data)
    } else setInherit({ preview, why: got.why, sending: false })
  }

  const subLine = [
    run.file,
    startedText(run.started_at) ? `시작 ${startedText(run.started_at)}` : null,
    finished && run.ended_reason ? `끝 · ${run.ended_reason}` : null,
    run.inherited_from ? `이어받음 ← ${run.inherited_from}` : null,
    run.handed_to ? `이어받은 실행 → ${run.handed_to}` : null,
  ]
    .filter(Boolean)
    .join(' · ')

  return (
    <div className="run-main">
      <div className="pyrun-head">
        <p className="vrf-title">
          <span className="vrf-title-name">{run.title || run.name}</span>
        </p>
        <ModeBadge mode={run.mode} />
        <StateBadge state={run.state} />
        <div className="pyrun-head-acts">
          {inheritable && (
            <button type="button" className="btn btn-primary" onClick={() => void openInherit()}>
              이어받기
            </button>
          )}
          <a className="btn btn-quiet" href={downloadUrl(run.id)} download>
            ⬇ 결과 내려받기 (zip)
          </a>
          <button
            type="button"
            className="btn btn-quiet"
            aria-disabled={!canStop || undefined}
            aria-describedby={!canStop ? 'spread-act-why' : undefined}
            onClick={() => canStop && (setActWhy(null), setAskStop(true))}
          >
            중지
          </button>
        </div>
      </div>
      <p className="pyrun-sub" title={run.id}>
        {subLine}
      </p>
      <p className="run-why run-head-why" id="spread-act-why">
        {finished ? '끝난 실행입니다' : ''}
      </p>
      {why && <p className="run-store-why">{why}</p>}

      {/* 기다림·멈춤은 상태 막대 위입니다 — 손을 써야 넘어가는 일이 먼저 보여야 합니다. */}
      {halted !== null && (
        <div className="run-attention">
          <span>멈춤 — {halted}</span>
        </div>
      )}
      {waiting && (
        <div className="run-attention">
          <span>
            정리 대기 — 장이 열리길 기다리는 다리: <b>{(run.waiting_for ?? []).join(' · ') || '—'}</b>. 열리면 보유를 정리하고 끝냅니다.
          </span>
        </div>
      )}
      {run.unresolved_order !== undefined && run.unresolved_order !== null && (
        <p className="pyrun-unresolved">
          결과를 모르는 주문이 남아 있습니다 — 계좌·주문내역을 확인하세요:{' '}
          {typeof run.unresolved_order === 'string' ? run.unresolved_order : JSON.stringify(run.unresolved_order)}
        </p>
      )}
      {finished && run.holding_left && Object.values(run.holding_left).some((q) => q !== 0) && (
        <p className="pyrun-unresolved">
          끝날 때 남은 보유: {Object.entries(run.holding_left).filter(([, q]) => q !== 0).map(([name, q]) => `${name} ${qtyText(q)}`).join(' · ')}
          {run.handed_to ? ' (이미 이어받았습니다)' : ''}
        </p>
      )}

      <div className="run-bar">
        {legs.map((leg) => {
          const position = leg.position ?? null
          return (
            <span className="run-bar-item" key={leg.name}>
              {leg.name} <span className="pyrun-dim">{leg.sym}</span>{' '}
              <b className={position ? (position > 0 ? 'up' : 'down') : undefined}>
                {position === null ? '—' : position === 0 ? '보유 없음' : `${position > 0 ? '매수' : '매도'} ${Math.abs(position)}`}
                {position ? ` @ ${priceText(leg.avg_price)}` : ''}
              </b>
              {' · 현재 '}
              <b>{priceText(leg.last)}</b>
            </span>
          )
        })}
        <PnlItem label={`${todayLabel} 손익`} by={today} />
        <PnlItem label="누적 손익" by={total} />
      </div>

      <div className="pyrun-mid spread-mid">
        <div className="card">
          <SpreadChart bars={bars} legNames={legs.map((leg) => leg.name)} />
        </div>
        <DaySummary run={run} today={today} total={total} todayLabel={todayLabel} />
      </div>

      <div className="run-bottom">
        <div className="tabs tabs-inline run-bottom-tabs">
          {SPREAD_BOTTOM_TABS.map((item) => (
            <button key={item} type="button" className="tab" aria-current={item === bottom} onClick={() => setBottom(item)}>
              {item}
            </button>
          ))}
        </div>
        <BottomTable tab={bottom} run={run} journal={journal} apiLog={apiLog} apiTotal={apiTotal} />
      </div>

      {askStop && (
        <Modal label="중지" dismissable={false} onClose={() => !acting && setAskStop(false)} head={<span className="modal-title">중지</span>}>
          <p className="pyrun-confirm-text">
            보유가 있으면 정리하고 실행을 끝냅니다. 한쪽 장이 닫혀 있으면 「정리 대기」로 기다렸다가 장이 열리면 함께 정리합니다.
            {run.mode === 'orders' && ' 모의 계좌로 정리 주문이 나갈 수 있습니다.'}
          </p>
          <p className="run-hint">요청은 완료가 아닙니다 — 결과는 아래 표와 상태에서 확인하세요</p>
          <div className="run-add-acts">
            <button type="button" className="btn btn-quiet" aria-disabled={acting || undefined} onClick={() => !acting && setAskStop(false)}>
              그만두기
            </button>
            <button type="button" className="btn btn-heavy" aria-disabled={acting || undefined} onClick={() => void doStop()}>
              {acting ? '보내는 중' : '중지'}
            </button>
          </div>
          <p className={`run-hint run-start-why${actWhy ? ' is-error' : ''}`}>{actWhy ?? ''}</p>
        </Modal>
      )}

      {inherit && (
        <Modal
          label="이어받기"
          dismissable={false}
          onClose={() => !inherit.sending && setInherit(null)}
          head={<span className="modal-title">이어받기</span>}
        >
          {inherit.preview === null ? (
            <>
              <p className={inherit.why ? 'run-store-why' : 'pyrun-confirm-text'}>{inherit.why ?? '지금 계좌 잔고를 읽는 중입니다'}</p>
              <div className="run-add-acts">
                <button type="button" className="btn btn-quiet" onClick={() => setInherit(null)}>
                  닫기
                </button>
              </div>
            </>
          ) : (
            <div className="run-add">
              <dl className="run-confirm">
                <div className="run-confirm-row">
                  <dt>앞선 실행</dt>
                  <dd>{run.title || run.name} · {run.id}</dd>
                </div>
                <div className="run-confirm-row">
                  <dt>앞선 끝 까닭</dt>
                  <dd>{inherit.preview.ended_reason || '—'}</dd>
                </div>
                {Object.entries(inherit.preview.legs).map(([name, leg]) => (
                  <div className="run-confirm-row" key={name}>
                    <dt>다리 {name}</dt>
                    <dd>
                      {leg.sym} · 계좌 잔고 <b>{qtyText(leg.qty)}</b>계약 · 평균가 {priceText(leg.avg_price)}
                    </dd>
                  </div>
                ))}
              </dl>
              {inherit.preview.warning && (
                <div className="run-attention">
                  <span>{inherit.preview.warning}</span>
                </div>
              )}
              <p className="run-approve">
                위 잔고를 이어받아 새 모의 계좌 실행을 세웁니다. 시작하는 순간 잔고가 위와 다르면 거절됩니다.
              </p>
              <div className="run-add-acts">
                <button type="button" className="btn btn-quiet" aria-disabled={inherit.sending || undefined} onClick={() => !inherit.sending && setInherit(null)}>
                  그만두기
                </button>
                <button type="button" className="btn btn-heavy" aria-disabled={inherit.sending || undefined} onClick={() => void sendInherit()}>
                  {inherit.sending ? '세우는 중' : '이어받아 시작'}
                </button>
              </div>
              <p className={`run-hint run-start-why${inherit.why ? ' is-error' : ''}`}>{inherit.why ?? ''}</p>
            </div>
          )}
        </Modal>
      )}
    </div>
  )
}

function PnlItem({ label, by }: { label: string; by: SpreadPnlByCur | null }) {
  const lines = pnlLine(by, (value, currency) => pnlText(value, currency))
  return (
    <span className="run-bar-item">
      {label}{' '}
      {lines.length === 0 ? (
        <b>—</b>
      ) : (
        lines.map((one) => (
          <span key={one.currency} className="spread-cur">
            <PnlText value={one.value} currency={one.currency} estimated={one.estimated} feeUnknown={one.feeUnknown} />
          </span>
        ))
      )}
    </span>
  )
}

/* ── 날짜별 요약 ───────────────────────────────────────── */

/** 거래일(한국 07:00 경계)·통화별 손익. 끝난 실행은 요약 파일의 모든 날, 도는 실행은 오늘과 누적만 상태에서 옵니다. */
function DaySummary({
  run,
  today,
  total,
  todayLabel,
}: {
  run: SpreadRunStatus
  today: SpreadPnlByCur | null
  total: SpreadPnlByCur | null
  todayLabel: string
}) {
  const days = run.summary?.days
  const rows: { key: string; label: string; cur: string; one: SpreadPnlByCur[string] }[] = []
  if (days && Object.keys(days).length > 0) {
    for (const day of Object.keys(days).sort()) {
      for (const [cur, one] of Object.entries(days[day])) rows.push({ key: `${day}-${cur}`, label: dayText(day), cur, one })
    }
  } else if (today) {
    for (const [cur, one] of Object.entries(today)) rows.push({ key: `today-${cur}`, label: todayLabel, cur, one })
  }
  for (const [cur, one] of Object.entries(total ?? {})) rows.push({ key: `total-${cur}`, label: '누적', cur, one })
  return (
    <div className="card">
      <h2 className="run-card-title">날짜별 요약</h2>
      {rows.length === 0 ? (
        <p className="run-why">아직 체결이 없습니다</p>
      ) : (
        <div className="table-scroll">
          <table className="data-table rows-base pyrun-table">
            <thead>
              <tr>
                <th scope="col" className="col-text">날</th>
                <th scope="col" className="col-text">통화</th>
                <th scope="col">손익</th>
                <th scope="col">수수료</th>
                <th scope="col">순손익</th>
                <th scope="col">체결</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ key, label, cur, one }) => (
                <tr key={key}>
                  <td className="col-text">{label}</td>
                  <td className="col-text">{cur}</td>
                  <td className={toneOf(one.pnl) || undefined}>{pnlText(one.pnl, cur)}</td>
                  <td>{pnlText(one.fee, cur)}{(one.fee_unknown ?? 0) > 0 && <span className="run-note"> +모름 {one.fee_unknown}</span>}</td>
                  <td>
                    <PnlText value={one.net} currency={cur} estimated={one.estimated === true} feeUnknown={0} />
                  </td>
                  <td>{one.fills}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/* ── 아래 표 ───────────────────────────────────────────── */

function BottomTable({
  tab,
  run,
  journal,
  apiLog,
  apiTotal,
}: {
  tab: BottomTab
  run: SpreadRunStatus
  journal: PyJournalRow[]
  apiLog: Record<string, unknown>[]
  apiTotal: number
}) {
  const paperRun = run.mode !== 'orders'
  const fills = useMemo(() => journal.filter((row) => row.kind === 'fill' || row.kind === 'order'), [journal])
  const events = useMemo(() => journal.filter((row) => !NOT_EVENT.has(row.kind)), [journal])
  const logs = useMemo(() => journal.filter((row) => row.kind === 'log'), [journal])

  let note = ''
  let table: ReactNode
  if (tab === '체결') {
    const rows = newestFirst(fills)
    if (fills.length > ROW_CAP) note = `${fills.length}줄 중 최근 ${ROW_CAP}줄`
    table = (
      <table className="data-table rows-base pyrun-table">
        <thead>
          <tr>
            <th scope="col" className="col-text">시각</th>
            <th scope="col" className="col-text">구분</th>
            <th scope="col" className="col-text">다리</th>
            <th scope="col">수량</th>
            <th scope="col">가격</th>
            <th scope="col">수수료</th>
            <th scope="col" className="col-text">내용</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, at) => {
            const paper = row.kind === 'fill' && (row.source === 'paper' || paperRun)
            const failed = row.kind === 'order' && row.ok === false
            const guess = priceIsGuess(row)
            const qty = num(row.qty)
            return (
              <tr key={`${row.at}-${at}`}>
                <td className="col-text">{rowClock(row)}</td>
                <td className="col-text">
                  {row.kind === 'fill' ? (
                    <span className={`badge run-kind ${paper ? 'run-kind-paper' : 'run-kind-sim'}`}>{paper ? '종이 체결' : '모의 계좌 체결'}</span>
                  ) : (
                    <span className={`badge${failed ? (row.unknown ? ' run-alert' : ' pyrun-state-error') : ''}`}>
                      {failed ? (row.unknown ? '결과 모름' : '주문 거부') : '주문'}
                    </span>
                  )}
                </td>
                <td className="col-text">{String(row.leg ?? '—')}</td>
                <td className={qty === null ? undefined : qty > 0 ? 'up' : qty < 0 ? 'down' : undefined}>{qtyText(row.qty)}</td>
                <td>
                  {priceText(row.price)}
                  {guess && <span className="badge spread-est" title="체결가를 읽지 못해 기준가로 적었습니다">추정</span>}
                </td>
                <td>{priceText(row.fee)}</td>
                <td className="col-text pyrun-wrap">
                  {String(row.text ?? '')}
                  {row.error && <span className="pyrun-warn"> · {String(row.error)}</span>}
                </td>
              </tr>
            )
          })}
          {rows.length === 0 && <EmptyRow span={7} text="아직 주문·체결이 없습니다" />}
        </tbody>
      </table>
    )
  } else if (tab === '사건') {
    const rows = newestFirst(events)
    if (events.length > ROW_CAP) note = `${events.length}줄 중 최근 ${ROW_CAP}줄`
    table = (
      <table className="data-table rows-base pyrun-table">
        <thead>
          <tr>
            <th scope="col" className="col-text">시각</th>
            <th scope="col" className="col-text">구분</th>
            <th scope="col" className="col-text">내용</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, at) => (
            <tr key={`${row.at}-${at}`}>
              <td className="col-text">{rowClock(row)}</td>
              <td className="col-text">{row.kind === 'event' ? '' : <span className="badge">{row.kind}</span>}</td>
              <td className="col-text pyrun-wrap">
                {eventText(row)}
                {row.error && <span className="pyrun-warn"> · {String(row.error)}</span>}
              </td>
            </tr>
          ))}
          {rows.length === 0 && <EmptyRow span={3} text="아직 남은 사건이 없습니다" />}
        </tbody>
      </table>
    )
  } else if (tab === '값 기록') {
    const rows = newestFirst(logs)
    if (logs.length > ROW_CAP) note = `${logs.length}줄 중 최근 ${ROW_CAP}줄`
    table = (
      <table className="data-table rows-base pyrun-table">
        <thead>
          <tr>
            <th scope="col" className="col-text">시각</th>
            <th scope="col" className="col-text">이름</th>
            <th scope="col">값</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, at) => (
            <tr key={`${row.at}-${at}`}>
              <td className="col-text">{atClock(row.at)}</td>
              <td className="col-text">{String(row.name ?? '—')}</td>
              <td>{priceText(row.value)}</td>
            </tr>
          ))}
          {rows.length === 0 && <EmptyRow span={3} text="실행기가 남긴 값이 아직 없습니다" />}
        </tbody>
      </table>
    )
  } else {
    const rows = [...apiLog].reverse()
    if (apiTotal > apiLog.length) note = `API 호출 ${apiTotal}줄 중 최근 ${apiLog.length}줄 — 전체는 ⬇ 결과`
    table = (
      <table className="data-table rows-base pyrun-table">
        <thead>
          <tr>
            <th scope="col" className="col-text">시각</th>
            <th scope="col" className="col-text">용도</th>
            <th scope="col" className="col-text">API</th>
            <th scope="col">HTTP</th>
            <th scope="col" className="col-text">코드</th>
            <th scope="col">ms</th>
            <th scope="col" className="col-text">결과</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, at) => (
            <tr key={`${String(row.at)}-${at}`}>
              <td className="col-text">{atClock(row.at)}</td>
              <td className="col-text">{String(row.purpose ?? '—')}</td>
              <td className="col-text">{String(row.api_id ?? '—')}</td>
              <td>{row.http === null || row.http === undefined ? '—' : String(row.http)}</td>
              <td className="col-text">{row.code ? String(row.code) : '—'}</td>
              <td>{num(row.ms) !== null ? Math.round(row.ms as number) : '—'}</td>
              <td className={`col-text pyrun-wrap ${row.ok ? '' : 'pyrun-warn'}`.trim()}>
                {row.ok ? String(row.message ?? '정상') : String(row.error ?? row.message ?? '실패')}
                {row.reissued === true && <span className="pyrun-dim"> · 토큰 재발급</span>}
                {num(row.waited_ms) !== null && (row.waited_ms as number) > 0 && (
                  <span className="pyrun-dim"> · 호출 제한 대기 {Math.round(row.waited_ms as number)}ms</span>
                )}
              </td>
            </tr>
          ))}
          {rows.length === 0 && <EmptyRow span={7} text="아직 API 호출이 없습니다" />}
        </tbody>
      </table>
    )
  }

  return (
    <>
      {note && <p className="pyrun-table-note">{note}</p>}
      <div className="table-scroll run-table">{table}</div>
    </>
  )
}
