import { useMemo, useState, type ReactNode } from 'react'
import { Modal } from '../../app/Modal'
import { resolve } from '../../data/instruments'
import {
  currencyOf,
  downloadUrl,
  flattenRun,
  isLiveRun,
  isRealtime,
  pnlText,
  stopRun,
  type PyBars,
  type PyJournalRow,
  type PyRunStatus,
  type PyRunView,
  type PyStrategyFile,
} from '../../data/pyrun'
import { MINUS, toneOf } from '../../lib/number'
import { PyRtChart, PyRunChart, type StopLine } from './PyRunChart'
import { KindBadge, ModeBadge, StateBadge, isFinished, shortDate } from './PyRunSide'

/* 팀: 「파이썬 전략」 오른쪽 — ③ 머리줄·상태 막대 ④ 차트 ⑤ 지금 판단 ⑥ 아래 표.
 * 자리와 클래스는 「전략 진행」(`vrf-title` · `run-bar` · `run-attention` · `run-bottom`)과 같습니다. */

export const PY_BOTTOM_TABS = ['신호', '주문·체결', '거래', '이벤트', 'API 로그'] as const
export type PyBottomTab = (typeof PY_BOTTOM_TABS)[number]

/** 한 표에 그리는 줄 상한. 넘으면 최근 것만 그리고 그 사실을 적습니다(전부는 ⬇ 결과). */
const ROW_CAP = 500

/** 신호 줄에서 지표 칸이 아닌 것. `ref`(실시간 신호의 기준가)는 종가 자리에 섭니다. */
const SIGNAL_TAGS = new Set([
  'kind', 'at', 'clock', 'date', 'bar', 'close', 'side', 'reason', 'stop_ticks', 'open', 'high', 'low', 'text',
  'ref', 'act', 'time',
])

const INDICATOR_LABEL: Record<string, string> = {
  upper: '상단',
  middle: '중심',
  lower: '하단',
  rsi: 'RSI',
  atr: 'ATR',
  vwap: 'VWAP',
  sigma: 'σ',
  range_high: '범위 위',
  range_low: '범위 아래',
  krx: 'KRX',
  bid: '매수 호가',
  ask: '매도 호가',
  dk: 'dk',
  rho: 'rho',
}

const SIDE_WORD: Record<string, string> = { buy: '매수', sell: '매도' }

/* ── 글자로 옮기기 ─────────────────────────────────────── */

/** `093000` → `09:30`, 초가 있으면 `09:30:15`. */
export function clockText(time: unknown): string {
  if (typeof time !== 'string' || time.length < 4) return '—'
  const base = `${time.slice(0, 2)}:${time.slice(2, 4)}`
  return time.length >= 6 && time.slice(4, 6) !== '00' ? `${base}:${time.slice(4, 6)}` : base
}

/** 기록의 `at`(`2026-10-30T09:24:33`) → `09:24:33`. */
function atClock(at: unknown): string {
  return typeof at === 'string' && at.length >= 19 ? at.slice(11, 19) : '—'
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/** 가격 — 그 종목 자릿수로. */
export function priceText(value: unknown, decimals: number): string {
  const v = num(value)
  if (v === null) return '—'
  const text = Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
  return v < 0 ? `${MINUS}${text}` : text
}

/** 지표 값 — 서버가 반올림해 준 자릿수(최대 3) 그대로. */
function indicatorText(value: unknown): string {
  const v = num(value)
  if (v === null) return '—'
  const text = Math.abs(v).toLocaleString('en-US', { maximumFractionDigits: 3 })
  return v < 0 ? `${MINUS}${text}` : text
}

/** 신호 줄의 값 칸 중 가격인 것 — 지표 자릿수(최대 3)가 아니라 그 종목 자릿수로 적습니다(MKU 는 5자리).
 *  `krx` 는 신호 종목(KRX) 자릿수, 나머지는 주문 종목 자릿수. */
const PRICE_KEYS = new Set(['bid', 'ask', 'krx', 'mku_last', 'range_high', 'range_low'])

function cellText(key: string, value: unknown, decimals: number, krxDecimals: number): string {
  if (!PRICE_KEYS.has(key)) return indicatorText(value)
  return priceText(value, key === 'krx' ? krxDecimals : decimals)
}

/** 판단 글 — 「매수 신호 · 까닭」, 까닭이 없으면 「매수 신호」. */
function verdictText(side: unknown, reason: unknown): string {
  const why = typeof reason === 'string' && reason ? reason : ''
  return why ? `${sideWord(side)} 신호 · ${why}` : `${sideWord(side)} 신호`
}

/** 받은 시각 — 초까지(`093005` → `09:30:05`). */
function secondsText(time: unknown): string {
  if (typeof time !== 'string' || time.length < 6) return clockText(time)
  return `${time.slice(0, 2)}:${time.slice(2, 4)}:${time.slice(4, 6)}`
}

/** 보유 초 → `45초` · `3분 05초`. */
function heldText(seconds: unknown): string {
  const v = num(seconds)
  if (v === null) return '—'
  const whole = Math.max(0, Math.round(v))
  return whole < 60 ? `${whole}초` : `${Math.floor(whole / 60)}분 ${String(whole % 60).padStart(2, '0')}초`
}

/** 신호 줄의 판단 시각 — 1분봉은 봉(`bar`), 실시간은 그 순간(`time`, 없으면 기록 시각). */
function signalClock(row: PyJournalRow): string {
  return row.bar !== undefined ? clockText(row.bar) : secondsText(row.time ?? row.clock)
}

/** 신호 줄의 가격 — 1분봉은 종가, 실시간은 기준가(`ref`). */
function signalPrice(row: PyJournalRow): unknown {
  return row.close !== undefined ? row.close : row.ref
}

function sideWord(side: unknown): string {
  return typeof side === 'string' ? (SIDE_WORD[side] ?? side) : '—'
}

function sideClass(side: unknown): string | undefined {
  return side === 'buy' ? 'up' : side === 'sell' ? 'down' : undefined
}

function paramText(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string' && /^\d{6}$/.test(value)) return clockText(value)
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

/** 그 종목의 가격 자릿수 — 색인이 답하고, 모르면 기록의 종가에서 읽습니다. */
function decimalsOf(sym: string | null | undefined, closes: number[]): number {
  const known = sym ? resolve(sym)?.product.decimals : undefined
  if (typeof known === 'number') return known
  let most = 0
  for (const close of closes) {
    const frac = String(close).split('.')[1]
    if (frac) most = Math.max(most, Math.min(frac.length, 4))
  }
  return closes.length > 0 ? most : 2
}

/** 차트 줄의 값 하나를 모읍니다(자릿수 어림용). */
function valuesOf(bars: PyBars | null, key: 'close' | 'mku_mid' | 'krx'): number[] {
  if (!bars) return []
  const rows: Record<string, unknown>[] = bars.bars as unknown as Record<string, unknown>[]
  return rows.map((row) => row[key]).filter((v): v is number => num(v) !== null)
}

/* ── 오른쪽 전체 ───────────────────────────────────────── */

export function PyRunMain({ view, files }: { view: PyRunView; files: PyStrategyFile[] }) {
  const { run, journal, apiLog, apiTotal, bars, why } = view
  const [bottom, setBottom] = useState<PyBottomTab>('신호')
  const [ask, setAsk] = useState<'중지' | '청산' | null>(null)
  const [acting, setActing] = useState(false)
  const [actWhy, setActWhy] = useState<string | null>(null)

  const signals = useMemo(() => journal.filter((row) => row.kind === 'signal'), [journal])
  const realtime = run ? isRealtime(run) || bars?.kind === 'realtime' : false
  /* 주문 종목의 자릿수(1분봉은 종가, 실시간은 MKU 중간값)와 실시간의 KRX 자릿수. */
  const decimals = useMemo(
    () => decimalsOf(run?.sym, valuesOf(bars, realtime ? 'mku_mid' : 'close')),
    [run?.sym, bars, realtime],
  )
  const krxDecimals = useMemo(() => decimalsOf(run?.signal_sym, valuesOf(bars, 'krx')), [run?.signal_sym, bars])

  if (!run) {
    return (
      <div className="run-main notice">
        <p className="notice-title">{why ?? '실행을 받는 중입니다'}</p>
      </div>
    )
  }

  const live = isLiveRun(run)
  const finished = isFinished(run)
  const halted = run.halted ? String(run.halted) : null
  /* 멈춘 실행에서는 「중지」만 누를 수 있습니다. 지난 실행·끝난 실행은 둘 다 못 누릅니다. */
  const canStop = live && !finished
  const canFlatten = live && !finished && halted === null
  const offWhy = !live
    ? '이 앱에서 지금 세운 실행이 아니라 중지·청산할 수 없습니다'
    : finished
      ? '끝난 실행입니다'
      : halted !== null
        ? '멈춘 실행에서는 중지만 할 수 있습니다'
        : null

  const lastSignal: PyJournalRow | null = run.last_signal ?? signals[signals.length - 1] ?? null
  const strategyFile = files.find((one) => one.file === run.file)
  const params = run.params ?? strategyFile?.params ?? null
  const paramsFromFile = !run.params && !!strategyFile?.params
  const barMin = run.bar_min ?? num(params?.bar_min) ?? 1
  /* 판정 봉 크기를 그 실행이 아니라 지금 파일에서 읽었는지 — 범례에 단서를 답니다. */
  const barMinFromFile = run.bar_min === undefined && paramsFromFile
  /* RSI 기준선은 그 실행이 쓴 값일 때만 긋습니다 — 지금 파일 값으로 그으면 그때와 다른 선이 그때의 선처럼 보입니다. */
  const rsiGuides = paramsFromFile
    ? []
    : [num(params?.rsi_buy), num(params?.rsi_sell)].filter((v): v is number => v !== null)

  /* 보유 중이면 손절가 선. 진입 시각은 마지막 진입 표시에서 찾습니다. */
  const holding = (run.position ?? 0) !== 0
  const lastEntry = [...(bars?.marks ?? [])].reverse().find((mark) => mark.kind === 'entry')
  const stopLine: StopLine | null =
    holding && num(run.stop) !== null
      ? {
          date: lastEntry?.date ?? null,
          time: lastEntry?.time ?? null,
          price: run.stop as number,
          label: `손절 ${priceText(run.stop, decimals)}`,
        }
      : null

  async function act(kind: '중지' | '청산') {
    if (!run || acting) return
    setActing(true)
    setActWhy(null)
    const got = kind === '중지' ? await stopRun(run.id) : await flattenRun(run.id)
    setActing(false)
    if (got.ok) setAsk(null)
    else setActWhy(got.why)
  }

  const subLine = [
    run.file,
    /* 실시간은 신호 종목(KRX) → 주문 종목(MKU). */
    realtime && run.signal_sym ? `신호 ${run.signal_sym} → 주문 ${run.sym ?? '—'}` : run.sym,
    run.bar_min ? `판정 봉 ${run.bar_min}분` : null,
    run.next_decision_at && !finished ? `다음 판정 ${clockText(run.next_decision_at)}` : null,
    realtime && run.end_at && !finished ? `실행 끝 ${clockText(run.end_at)}` : null,
    finished && run.ended_reason ? `끝 · ${run.ended_reason}` : null,
  ]
    .filter(Boolean)
    .join(' · ')

  return (
    <div className="run-main">
      {/* ③ 머리줄 — 이름 · 방식 · 상태, 오른쪽에 결과 내려받기 · 중지 · 청산. */}
      <div className="pyrun-head">
        <p className="vrf-title">
          <span className="vrf-title-name">{run.title || run.name}</span>
        </p>
        <ModeBadge mode={run.mode} />
        <KindBadge kind={realtime ? 'realtime' : run.kind} />
        <StateBadge state={run.state} />
        <div className="pyrun-head-acts">
          <a className="btn btn-quiet" href={downloadUrl(run.id)} download>
            ⬇ 결과 내려받기 (zip)
          </a>
          <button
            type="button"
            className="btn btn-quiet"
            aria-disabled={!canStop || undefined}
            aria-describedby={offWhy ? 'pyrun-act-why' : undefined}
            onClick={() => canStop && (setActWhy(null), setAsk('중지'))}
          >
            중지
          </button>
          <button
            type="button"
            className="btn btn-quiet"
            aria-disabled={!canFlatten || undefined}
            aria-describedby={offWhy ? 'pyrun-act-why' : undefined}
            onClick={() => canFlatten && (setActWhy(null), setAsk('청산'))}
          >
            청산
          </button>
        </div>
      </div>
      <p className="pyrun-sub" title={run.id}>
        {subLine}
      </p>
      <p className="run-why run-head-why" id="pyrun-act-why">
        {offWhy ?? ''}
      </p>
      {why && <p className="run-store-why">{why}</p>}

      {/* 멈춘 까닭은 상태 막대 위입니다 — 손을 써야 넘어가는 일이 먼저 보여야 합니다. */}
      {halted !== null && (
        <div className="run-attention">
          <span>{halted}</span>
        </div>
      )}
      {run.unresolved_order !== undefined && run.unresolved_order !== null && (
        <p className="pyrun-unresolved">
          결과를 모르는 주문이 남아 있습니다 — 계좌·주문내역을 확인하세요:{' '}
          {typeof run.unresolved_order === 'string' ? run.unresolved_order : JSON.stringify(run.unresolved_order)}
        </p>
      )}

      {realtime ? (
        <RtStatusBar run={run} decimals={decimals} krxDecimals={krxDecimals} />
      ) : (
        <StatusBar run={run} decimals={decimals} />
      )}

      <div className="pyrun-mid">
        {/* ④ 차트 — 실시간은 1분 요약의 MKU 중간값·KRX 선 */}
        <div className="card">
          {realtime ? (
            <PyRtChart bars={bars} mkuDecimals={decimals} krxDecimals={krxDecimals} />
          ) : (
            <PyRunChart
              bars={bars}
              decimals={decimals}
              barMin={barMin}
              barMinFromFile={barMinFromFile}
              stop={stopLine}
              rsiGuides={rsiGuides}
            />
          )}
        </div>
        {/* ⑤ 지금 판단 */}
        <Decision
          signal={lastSignal}
          decimals={decimals}
          krxDecimals={krxDecimals}
          params={params}
          paramsFromFile={paramsFromFile}
          realtime={realtime}
        />
      </div>

      {/* ⑥ 아래 표 */}
      <div className="run-bottom">
        <div className="tabs tabs-inline run-bottom-tabs">
          {PY_BOTTOM_TABS.map((item) => (
            <button key={item} type="button" className="tab" aria-current={item === bottom} onClick={() => setBottom(item)}>
              {item}
            </button>
          ))}
        </div>
        <BottomTable
          tab={bottom}
          run={run}
          journal={journal}
          signals={signals}
          apiLog={apiLog}
          apiTotal={apiTotal}
          decimals={decimals}
          krxDecimals={krxDecimals}
        />
      </div>

      {ask && (
        <Modal
          label={ask}
          dismissable={false}
          onClose={() => !acting && setAsk(null)}
          head={<span className="modal-title">{ask}</span>}
        >
          <p className="pyrun-confirm-text">
            {ask === '중지'
              ? '보유가 있으면 정리하고 실행을 끝냅니다.'
              : '보유만 닫고 실행은 계속합니다.'}
            {run.mode === 'orders' && ' 모의 계좌로 정리 주문이 나갈 수 있습니다.'}
          </p>
          <p className="run-hint">요청은 완료가 아닙니다 — 결과는 아래 표와 상태에서 확인하세요</p>
          <div className="run-add-acts">
            <button type="button" className="btn btn-quiet" aria-disabled={acting || undefined} onClick={() => !acting && setAsk(null)}>
              그만두기
            </button>
            <button type="button" className="btn btn-heavy" aria-disabled={acting || undefined} onClick={() => void act(ask)}>
              {acting ? '보내는 중' : ask}
            </button>
          </div>
          <p className={`run-hint run-start-why${actWhy ? ' is-error' : ''}`}>{actWhy ?? ''}</p>
        </Modal>
      )}
    </div>
  )
}

/* ── ③ 상태 막대 ───────────────────────────────────────── */

function StatusBar({ run, decimals }: { run: PyRunStatus; decimals: number }) {
  /* 지난 실행(`run.json`)에는 지금 상태 칸이 없습니다 — 요약으로 손익·손절 수를 세웁니다. */
  const past = run.position === undefined
  const position = run.position ?? null
  const hold =
    position === null
      ? '—'
      : position === 0
        ? '없음'
        : `${position > 0 ? '매수' : '매도'} ${Math.abs(position)} @ ${priceText(run.entry, decimals)}`
  const pnl = past ? (run.summary?.net_pnl ?? null) : (run.today_pnl ?? null)
  const stops = past ? (run.summary?.by_reason?.['손절'] ?? (run.summary ? 0 : null)) : (run.stops ?? null)
  return (
    <div className="run-bar">
      <span className="run-bar-item">
        보유 <b className={position ? (position > 0 ? 'up' : 'down') : undefined}>{hold}</b>
      </span>
      <span className="run-bar-item">
        손절가{' '}
        <b>
          {priceText(run.stop, decimals)}
          {num(run.stop_ticks) !== null && ` (${run.stop_ticks}틱)`}
        </b>
      </span>
      <span className="run-bar-item">
        익절 목표 <b>{priceText(run.target, decimals)}</b>
      </span>
      <span className="run-bar-item">
        시간 청산 <b>{run.time_exit_at ? clockText(run.time_exit_at) : '—'}</b>
      </span>
      <span className="run-bar-item">
        {past ? '실행 손익' : '오늘 손익'}{' '}
        <b className={num(pnl) !== null ? toneOf(pnl as number) || undefined : undefined}>{pnlText(pnl, currencyOf(run))}</b>
      </span>
      <span className="run-bar-item">
        {past ? '손절 / 한도' : '오늘 손절 / 한도'}{' '}
        <b>
          {stops ?? '—'} / {run.max_stops ?? '—'}
        </b>
      </span>
    </div>
  )
}

/** 실시간 실행의 상태 막대(스펙 6-3) — 보유(방향·진입가·보유 초) · KRX 가격 · MKU 매수/매도 호가 · 최근 dk/rho ·
 *  오늘 손절/한도 · 오늘 손익(USD) · 마지막으로 받은 KRX 체결·MKU 호가 시각. 지난 실행은 요약으로 손익·손절 수만. */
function RtStatusBar({ run, decimals, krxDecimals }: { run: PyRunStatus; decimals: number; krxDecimals: number }) {
  const past = run.position === undefined
  const position = run.position ?? null
  const side = run.side ?? (position ? (position > 0 ? 'buy' : 'sell') : null)
  const hold =
    position === null
      ? '—'
      : position === 0
        ? '없음'
        : `${sideWord(side)} ${Math.abs(position)} @ ${priceText(run.entry, decimals)}`
  const pnl = past ? (run.summary?.net_pnl ?? null) : (run.today_pnl ?? null)
  const stops = past ? (run.summary?.by_reason?.['손절'] ?? (run.summary ? 0 : null)) : (run.stops ?? null)
  return (
    <div className="run-bar">
      <span className="run-bar-item">
        보유 <b className={sideClass(side)}>{hold}</b>
        {position ? <> · <b>{heldText(run.held_s)}</b></> : null}
        {run.pending && <span className="run-note"> 체결 확인 중</span>}
      </span>
      <span className="run-bar-item">
        KRX <b>{priceText(run.krx, krxDecimals)}</b>
      </span>
      <span className="run-bar-item">
        MKU 매수/매도 <b>{priceText(run.bid, decimals)} / {priceText(run.ask, decimals)}</b>
      </span>
      <span className="run-bar-item">
        최근 dk/rho <b>{indicatorText(run.last_dk)} / {indicatorText(run.last_rho)}</b>
      </span>
      <span className="run-bar-item">
        {past ? '손절 / 한도' : '오늘 손절 / 한도'}{' '}
        <b>
          {stops ?? '—'} / {run.max_stops ?? '—'}
        </b>
      </span>
      <span className="run-bar-item">
        {past ? '실행 손익' : '오늘 손익'}{' '}
        <b className={num(pnl) !== null ? toneOf(pnl as number) || undefined : undefined}>{pnlText(pnl, currencyOf(run))}</b>
      </span>
      <span className="run-bar-item">
        받은 시각 <b>KRX {secondsText(run.last_krx_at)} · 호가 {secondsText(run.last_quote_at)}</b>
      </span>
    </div>
  )
}

/* ── ⑤ 지금 판단 ───────────────────────────────────────── */

function Decision({
  signal,
  decimals,
  krxDecimals,
  params,
  paramsFromFile,
  realtime,
}: {
  signal: PyJournalRow | null
  decimals: number
  krxDecimals: number
  params: Record<string, unknown> | null
  paramsFromFile: boolean
  realtime: boolean
}) {
  const indicators = signal ? Object.keys(signal).filter((key) => !SIGNAL_TAGS.has(key) && num(signal[key]) !== null) : []
  /* 밴드 셋은 위에서 아래 차례로 먼저, 나머지는 기록 차례대로. */
  const bands = ['upper', 'middle', 'lower'].filter((key) => indicators.includes(key))
  const rest = indicators.filter((key) => !bands.includes(key))
  return (
    <div className="card">
      <h2 className="run-card-title">지금 판단</h2>
      {signal ? (
        <>
          <p className="pyrun-decide-at">
            {realtime
              ? `${signalClock(signal)} 판단`
              : `${shortDate(typeof signal.date === 'string' ? signal.date : null)} ${clockText(signal.bar)} 봉 · ${clockText(signal.clock)} 마감`}
          </p>
          <p className={`pyrun-decide-why ${sideClass(signal.side) ?? ''}`.trim()}>
            {signal.side
              ? verdictText(signal.side, signal.reason)
              : typeof signal.reason === 'string' && signal.reason
                ? signal.reason
                : '—'}
          </p>
          <dl className="pyrun-kv">
            <div>
              <dt>{realtime ? '기준가' : '종가'}</dt>
              <dd>{priceText(signalPrice(signal), decimals)}</dd>
            </div>
            {[...bands, ...rest].map((key) => (
              <div key={key}>
                <dt>{INDICATOR_LABEL[key] ?? key}</dt>
                <dd>{cellText(key, signal[key], decimals, krxDecimals)}</dd>
              </div>
            ))}
          </dl>
        </>
      ) : (
        <p className="run-why">{realtime ? '아직 진입·청산 판단이 없습니다' : '아직 판정한 봉이 없습니다'}</p>
      )}
      <h2 className="run-card-title pyrun-kv-title">
        파라미터 <span className="pyrun-kv-note">(Params{paramsFromFile ? ' · 지금 파일의 값 — 실행 때와 다를 수 있음' : ''})</span>
      </h2>
      {params ? (
        <dl className="pyrun-kv">
          {Object.entries(params).map(([key, value]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>{paramText(value)}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="run-why">파라미터를 모릅니다</p>
      )}
    </div>
  )
}

/* ── ⑥ 아래 표 ─────────────────────────────────────────── */

function EmptyRow({ span, text }: { span: number; text: string }) {
  return (
    <tr>
      <td className="run-empty-row" colSpan={span}>
        {text}
      </td>
    </tr>
  )
}

/** 최근 것이 위로, 상한까지. */
function newestFirst<T>(rows: T[]): T[] {
  return rows.slice(-ROW_CAP).reverse()
}

function BottomTable({
  tab,
  run,
  journal,
  signals,
  apiLog,
  apiTotal,
  decimals,
  krxDecimals,
}: {
  tab: PyBottomTab
  run: PyRunStatus
  journal: PyJournalRow[]
  signals: PyJournalRow[]
  apiLog: Record<string, unknown>[]
  apiTotal: number
  decimals: number
  krxDecimals: number
}) {
  const multiDay = useMemo(() => new Set(signals.map((row) => row.date)).size > 1, [signals])
  const indicatorKeys = useMemo(() => {
    const keys: string[] = []
    for (const row of signals) {
      for (const key of Object.keys(row)) {
        if (!SIGNAL_TAGS.has(key) && !keys.includes(key) && num(row[key]) !== null) keys.push(key)
      }
    }
    /* 밴드 셋은 위에서 아래 차례로 먼저(지금 판단 칸과 같은 차례). */
    const bands = ['upper', 'middle', 'lower'].filter((key) => keys.includes(key))
    return [...bands, ...keys.filter((key) => !bands.includes(key))]
  }, [signals])
  const paperRun = run.mode !== 'orders'
  const realtime = isRealtime(run)
  const currency = currencyOf(run)

  let note = ''
  let table: ReactNode
  if (tab === '신호') {
    const rows = newestFirst(signals)
    if (signals.length > ROW_CAP) note = `신호 ${signals.length}줄 중 최근 ${ROW_CAP}줄`
    const span = 3 + indicatorKeys.length
    table = (
      <table className="data-table rows-base pyrun-table">
        <thead>
          <tr>
            <th scope="col" className="col-text">{realtime ? '시각' : '봉'}</th>
            <th scope="col">{realtime ? '기준가' : '종가'}</th>
            {indicatorKeys.map((key) => (
              <th scope="col" key={key}>
                {INDICATOR_LABEL[key] ?? key}
              </th>
            ))}
            <th scope="col" className="col-text">판단</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, at) => (
            <tr key={`${row.date}-${row.bar ?? row.time}-${at}`}>
              <td className="col-text">
                {multiDay && `${shortDate(typeof row.date === 'string' ? row.date : null)} `}
                {signalClock(row)}
              </td>
              <td>{priceText(signalPrice(row), decimals)}</td>
              {indicatorKeys.map((key) => (
                <td key={key}>{cellText(key, row[key], decimals, krxDecimals)}</td>
              ))}
              <td className={`col-text pyrun-wrap ${row.side ? (sideClass(row.side) ?? '') : 'pyrun-dim'}`}>
                {row.side ? <b>{verdictText(row.side, row.reason)}</b> : String(row.reason ?? '—')}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <EmptyRow span={span} text={realtime ? '아직 진입·청산 판단이 없습니다' : '아직 판정한 봉이 없습니다'} />
          )}
        </tbody>
      </table>
    )
  } else if (tab === '주문·체결') {
    const all = journal.filter((row) => row.kind === 'order' || row.kind === 'fill')
    const rows = newestFirst(all)
    if (all.length > ROW_CAP) note = `${all.length}줄 중 최근 ${ROW_CAP}줄`
    table = (
      <table className="data-table rows-base pyrun-table">
        <thead>
          <tr>
            <th scope="col" className="col-text">시각</th>
            <th scope="col" className="col-text">구분</th>
            <th scope="col" className="col-text">방향</th>
            <th scope="col">가격</th>
            <th scope="col" className="col-text">주문번호</th>
            <th scope="col" className="col-text">내용</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, at) => {
            /* 종이 체결은 「종이 체결」입니다 — 모의 계좌 체결처럼 보이면 안 됩니다. */
            const paper = row.kind === 'fill' && (row.source === 'paper' || paperRun)
            const failed = row.kind === 'order' && row.ok === false
            return (
              <tr key={`${row.at}-${at}`}>
                <td className="col-text">{row.clock ? clockText(row.clock) : atClock(row.at)}</td>
                <td className="col-text">
                  {row.kind === 'fill' ? (
                    <span className={`badge run-kind ${paper ? 'run-kind-paper' : 'run-kind-sim'}`}>
                      {paper ? '종이 체결' : '모의 계좌 체결'}
                    </span>
                  ) : (
                    <span className={`badge${failed ? (row.unknown ? ' run-alert' : ' pyrun-state-error') : ''}`}>
                      {failed ? (row.unknown ? '결과 모름' : '주문 거부') : '주문'}
                    </span>
                  )}
                </td>
                <td className={`col-text ${sideClass(row.side) ?? ''}`.trim()}>{sideWord(row.side)}</td>
                <td>{priceText(row.price, decimals)}</td>
                <td className="col-text run-no">{typeof row.ord_no === 'string' && row.ord_no ? row.ord_no : '—'}</td>
                <td className="col-text pyrun-wrap">
                  {String(row.text ?? '')}
                  {typeof row.msg_cntn === 'string' && row.msg_cntn && <span className="pyrun-dim"> · {row.msg_cntn}</span>}
                  {row.error && <span className="pyrun-warn"> · {String(row.error)}</span>}
                </td>
              </tr>
            )
          })}
          {rows.length === 0 && <EmptyRow span={6} text="아직 주문·체결이 없습니다" />}
        </tbody>
      </table>
    )
  } else if (tab === '거래') {
    const all = journal.filter((row) => row.kind === 'trade')
    const rows = newestFirst(all)
    table = (
      <table className="data-table rows-base pyrun-table">
        <thead>
          <tr>
            <th scope="col" className="col-text">진입</th>
            <th scope="col" className="col-text">방향</th>
            <th scope="col">진입가</th>
            <th scope="col" className="col-text">청산</th>
            <th scope="col">청산가</th>
            <th scope="col" className="col-text">까닭</th>
            <th scope="col">틱</th>
            <th scope="col">손익</th>
            <th scope="col">수수료 뒤</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, at) => (
            <tr key={`${row.at}-${at}`}>
              <td className="col-text">{clockText(row.entry_time)}</td>
              <td className={`col-text ${sideClass(row.side) ?? ''}`.trim()}>{sideWord(row.side)}</td>
              <td>{priceText(row.entry, decimals)}</td>
              <td className="col-text">{clockText(row.exit_time)}</td>
              <td>{priceText(row.exit, decimals)}</td>
              <td className="col-text">{String(row.reason ?? '—')}</td>
              <td>{num(row.ticks) !== null ? `${(row.ticks as number) > 0 ? '+' : ''}${row.ticks}` : '—'}</td>
              <td className={toneOf(num(row.pnl) ?? 0) || undefined}>{pnlText(row.pnl, currency)}</td>
              {/* 수수료 뒤 — 실시간 거래는 Engine 의 `net_usd` 로 옵니다. */}
              <td className={toneOf(num(row.pnl_after_fee ?? row.net_usd) ?? 0) || undefined}>
                {pnlText(row.pnl_after_fee ?? row.net_usd, currency)}
              </td>
            </tr>
          ))}
          {rows.length === 0 && <EmptyRow span={9} text="아직 거래가 없습니다" />}
        </tbody>
      </table>
    )
  } else if (tab === '이벤트') {
    const all = journal.filter((row) => row.kind === 'event' || row.kind === 'account')
    const rows = newestFirst(all)
    if (all.length > ROW_CAP) note = `${all.length}줄 중 최근 ${ROW_CAP}줄`
    table = (
      <table className="data-table rows-base pyrun-table">
        <thead>
          <tr>
            <th scope="col" className="col-text">시각</th>
            <th scope="col" className="col-text">내용</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, at) => (
            <tr key={`${row.at}-${at}`}>
              <td className="col-text">{row.clock ? clockText(row.clock) : atClock(row.at)}</td>
              <td className="col-text pyrun-wrap">
                {row.kind === 'account' && <span className="badge">계좌</span>}
                {String(row.text ?? '')}
                {row.error && <span className="pyrun-warn"> · {String(row.error)}</span>}
              </td>
            </tr>
          ))}
          {rows.length === 0 && <EmptyRow span={2} text="아직 남은 이벤트가 없습니다" />}
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
          {rows.length === 0 && (
            <EmptyRow span={7} text={run.mode === 'replay' ? '리플레이는 API 를 부르지 않습니다' : '아직 API 호출이 없습니다'} />
          )}
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
