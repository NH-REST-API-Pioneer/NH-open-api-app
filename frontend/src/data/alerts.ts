/** 전략 실행 알림 — 실행에서 일어난 일을 화면 오른쪽 아래의 토스트와 짧은 소리로
 *  알립니다.
 *
 *  **알림의 원천은 한 자리**입니다(`noteRuns`). 실행 목록 조회와 허브 방송이 모두
 *  이곳을 지나고, 같은 체결·이벤트는 열쇠로 가려 **한 번만** 울립니다 — 방송은
 *  델타가 아니라 실행마다 최근 스무 줄이라 같은 줄이 늘 다시 옵니다.
 *
 *  **처음 받은 것은 울리지 않습니다.** 앱을 켜는 순간 실려 오는 스무 줄은 이미
 *  지나간 일이라 「본 것」으로만 둡니다. 끊겼다 다시 붙은 뒤의 첫 묶음은 한 건이면
 *  그대로, 여럿이면 「끊긴 동안 알림 n건」 한 장으로 묶습니다.
 *
 *  알림 설정은 사용자 홈의 화면 상태 파일(`nh.alerts`)에 남습니다 — 창마다
 *  설정이 갈리면 어느 창에서 소리가 날지 알 수 없습니다.
 *
 *  **운영체제 알림**은 같은 사건에 한 번 더 냅니다 — 창이 가려져 있을 때만, 종류마다
 *  5초에 한 번입니다. 데스크톱 앱이면 앱이 띄우는 알림 풍선으로, 브라우저면 브라우저
 *  알림으로 섭니다.
 */
import { useSyncExternalStore } from 'react'

import { kstTradingDay } from '../lib/kst'
import { moneyIn, toneOf } from '../lib/number'
import { uiValue, useUiState } from './uiState'
import {
  eventKey,
  fillKey,
  isDailyLossBlock,
  isPaperRun,
  isRejectedEvent,
  isUnsent,
  runMarketOf,
  unsentText,
  type RunMarket,
  type RunMode,
  type VerifyEvent,
  type VerifyFill,
  type VerifyRun,
} from './strategyRuns'

/* ── 설정 ──────────────────────────────────────────── */

/** 알림의 종류. 설정 표의 여섯 줄입니다. */
export type AlertKind = 'signal' | 'fill' | 'exit' | 'limit' | 'feed' | 'unsent'

export const ALERT_KINDS: readonly AlertKind[] = ['signal', 'fill', 'exit', 'limit', 'feed', 'unsent']

/** 설정 표에 적는 종류 이름. */
export const ALERT_KIND_LABEL: Record<AlertKind, string> = {
  signal: '신호',
  fill: '체결',
  exit: '손절 · 익절 · 추적 청산',
  limit: '한도 정지',
  feed: '시세 끊김',
  unsent: '안 낸 신호',
}

/** 소리가 없는 종류. 신호는 하루에도 여러 번 나는 일이라 소리를 달지 않습니다. */
export const SILENT_KINDS: readonly AlertKind[] = ['signal']

export interface AlertSettings {
  /** 토스트를 띄우는지. */
  toast: boolean
  /** 소리를 내는지. 처음에는 꺼져 있습니다. */
  sound: boolean
  /** 운영체제 알림을 내는지. 처음에는 꺼져 있습니다. */
  os: boolean
  /** 종류마다 토스트·소리·운영체제 알림. */
  kinds: Record<AlertKind, { toast: boolean; sound: boolean; os: boolean }>
  /** 검증(앱 시뮬레이션) 실행도 알리는지. 끄면 그 실행은 한도 정지·시세 끊김만 알립니다. */
  simRuns: boolean
}

export const DEFAULT_ALERTS: AlertSettings = {
  toast: true,
  sound: false,
  os: false,
  kinds: {
    signal: { toast: true, sound: false, os: false },
    fill: { toast: true, sound: true, os: true },
    exit: { toast: true, sound: true, os: true },
    limit: { toast: true, sound: true, os: true },
    feed: { toast: true, sound: true, os: true },
    unsent: { toast: true, sound: false, os: false },
  },
  simRuns: false,
}

/** 담긴 값을 읽습니다. **모양이 틀린 칸은 기본값으로** 읽습니다 — 손으로 고친
 *  파일이나 옛 판의 값 하나 때문에 알림 전체가 꺼지면 안 됩니다. 모르는 종류의
 *  키는 버립니다. */
export function readAlerts(raw: unknown): AlertSettings {
  const box = raw !== null && typeof raw === 'object' ? (raw as Record<string, unknown>) : {}
  const flag = (value: unknown, fallback: boolean) => (typeof value === 'boolean' ? value : fallback)
  const kindsRaw =
    box.kinds !== null && typeof box.kinds === 'object' ? (box.kinds as Record<string, unknown>) : {}
  const kinds = {} as AlertSettings['kinds']
  for (const kind of ALERT_KINDS) {
    const one = kindsRaw[kind]
    const row = one !== null && typeof one === 'object' ? (one as Record<string, unknown>) : {}
    kinds[kind] = {
      toast: flag(row.toast, DEFAULT_ALERTS.kinds[kind].toast),
      sound: flag(row.sound, DEFAULT_ALERTS.kinds[kind].sound),
      os: flag(row.os, DEFAULT_ALERTS.kinds[kind].os),
    }
  }
  return {
    toast: flag(box.toast, DEFAULT_ALERTS.toast),
    sound: flag(box.sound, DEFAULT_ALERTS.sound),
    os: flag(box.os, DEFAULT_ALERTS.os),
    kinds,
    simRuns: flag(box.simRuns, DEFAULT_ALERTS.simRuns),
  }
}

/** 화면이 쓰는 꼴 — 읽은 설정과 바꾸는 함수. */
export function useAlertSettings(): [AlertSettings, (next: AlertSettings) => void] {
  const [raw, store] = useUiState<unknown>('nh.alerts', null)
  return [readAlerts(raw), store]
}

/** 알림을 낼 때 보는 설정. 저장소를 구독하지 않는 자리라 그때그때 읽습니다. */
function settingsNow(): AlertSettings {
  return readAlerts(uiValue('nh.alerts', null))
}

/* ── 운영체제 알림 ─────────────────────────────────── */

/** 데스크톱 앱이 화면에 열어 둔 함수. 앱이 아직 준비되지 않았으면(브라우저이거나
 *  준비 전) 없습니다 — 그 사이의 사건은 쌓지 않고 버립니다. */
interface DesktopBridge {
  notify: (message: {
    title: string
    body: string
    runId: string | null
    kind: string
    test?: boolean
  }) => unknown
}

function desktop(): DesktopBridge | null {
  const api = (window as unknown as { pywebview?: { api?: Partial<DesktopBridge> } }).pywebview?.api
  return api && typeof api.notify === 'function' ? (api as DesktopBridge) : null
}

/** 데스크톱 앱 안인지. 앱이 아직 함수를 열기 전이어도 앱 안이면 참입니다. */
function inDesktop(): boolean {
  return (window as unknown as { pywebview?: unknown }).pywebview !== undefined
}

/** 운영체제 알림을 낼 길 — 데스크톱 앱의 풍선, 브라우저 알림, 또는 없음. */
export function osRoute(): 'desktop' | 'browser' | 'none' {
  if (inDesktop()) return 'desktop'
  return typeof Notification === 'undefined' ? 'none' : 'browser'
}

/** 알림을 눌렀을 때 화면이 여는 실행들. 한 실행의 알림은 그 실행, 묶음 알림은
 *  마지막 묶음의 실행들입니다(데스크톱은 실행을 비워서 부릅니다). */
let summaryTargets: string[] = []
export function notifyTargets(runId: string | null | undefined): string[] {
  return runId ? [runId] : summaryTargets
}

/** 알림 제목에 적는 전략 이름. 이름은 전략 목록이 알아, 화면이 붙을 때 꽂습니다. */
let nameOf: (version: string | null) => string = () => ''
export function bindRunName(read: (version: string | null) => string): void {
  nameOf = read
}

/** 종류마다 마지막으로 운영체제 알림을 낸 시각. 5초에 한 번입니다 — 사건이 몰리는
 *  때 알림 풍선이 줄지어 서지 않게 합니다. */
const lastOs: Partial<Record<AlertKind, number>> = {}
const OS_GAP_MS = 5000

function sendOs(title: string, body: string, runId: string | null, kind: string, test = false): void {
  const api = desktop()
  if (api) {
    try {
      void Promise.resolve(api.notify({ title, body, runId, kind, ...(test ? { test: true } : {}) })).catch(
        () => {},
      )
    } catch {
      /* 풍선을 못 띄워도 토스트는 이미 섰습니다. */
    }
    return
  }
  /* 데스크톱 앱 안인데 알림 함수가 아직 준비되지 않았으면 그 사건은 버립니다 — 브라우저
     알림으로 넘어가면 앱이 준비된 뒤의 풍선과 두 번 섭니다. */
  if (inDesktop()) return
  if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return
  try {
    const shown = new Notification(title, { body })
    shown.onclick = () => {
      window.focus()
      ;(window as unknown as { __nhNotifyClick?: (id: string) => void }).__nhNotifyClick?.(runId ?? '')
      shown.close()
    }
  } catch {
    /* 브라우저가 거절하면 넘어갑니다. */
  }
}

/** 사건 하나의 운영체제 알림. **창이 가려져 있을 때만** 냅니다 — 보고 있는 창에는
 *  토스트가 이미 섭니다. 토스트 설정과는 따로입니다(소리처럼). */
function notifyOs(kind: AlertKind, draft: Draft, settings: AlertSettings, title?: string): void {
  if (!settings.os || !settings.kinds[kind].os || !document.hidden) return
  const now = Date.now()
  if (now - (lastOs[kind] ?? 0) < OS_GAP_MS) return
  lastOs[kind] = now
  const real = draft.mode === 'real' ? '[실전] ' : ''
  const head = title ?? `${draft.label} · ${nameOf(draft.version)}`
  sendOs(`${real}${head}`, draft.body.map((part) => part.text).join(''), draft.runId, kind)
}

/** 「보내 보기」 — 시험 알림 하나. 창이 앞에 있어도 냅니다. */
export function sendTestNotification(): void {
  sendOs('시험 알림 · NH FUTURES API', '운영체제 알림이 이렇게 섭니다', null, 'test', true)
}

/* ── 소리 ──────────────────────────────────────────── */

/** 소리 둘 — 체결음(체결·익절·추적 청산)과 경고음(손절·한도 정지·시세 끊김·안 낸 신호). */
export type AlertTone = 'fill' | 'warn'

let audio: AudioContext | null = null
/** 소리마다 마지막으로 낸 시각. 같은 소리는 2초에 한 번입니다. */
const lastTone: Record<AlertTone, number> = { fill: 0, warn: 0 }
const TONE_GAP_MS = 2000

/** 소리를 냅니다. 브라우저가 아직 소리를 막고 있으면(사용자가 창을 한 번도 안
 *  눌렀으면) **조용히 넘어갑니다** — 토스트는 그대로 섭니다. `force` 는 「들어
 *  보기」처럼 사용자가 누른 자리에서 2초 간격을 건너뛸 때입니다. */
export function playTone(tone: AlertTone, force = false): void {
  const now = Date.now()
  if (!force && now - lastTone[tone] < TONE_GAP_MS) return
  lastTone[tone] = now
  try {
    audio ??= new AudioContext()
    const ctx = audio
    const sound = () => {
      if (ctx.state !== 'running') return
      const notes = tone === 'fill' ? [880, 1320] : [520, 520]
      const wave: OscillatorType = tone === 'fill' ? 'sine' : 'triangle'
      const length = tone === 'fill' ? 0.09 : 0.14
      notes.forEach((freq, index) => {
        const start = ctx.currentTime + index * (length + 0.05)
        const osc = ctx.createOscillator()
        const gain = ctx.createGain()
        osc.type = wave
        osc.frequency.value = freq
        gain.gain.setValueAtTime(0.0001, start)
        gain.gain.exponentialRampToValueAtTime(0.12, start + 0.01)
        gain.gain.exponentialRampToValueAtTime(0.0001, start + length)
        osc.connect(gain).connect(ctx.destination)
        osc.start(start)
        osc.stop(start + length + 0.02)
      })
    }
    if (ctx.state === 'running') sound()
    else void ctx.resume().then(sound, () => {})
  } catch {
    /* 소리를 못 내도 알림은 토스트로 섭니다. */
  }
}

/* ── 토스트 ────────────────────────────────────────── */

/** 본문의 한 조각. 방향 색은 매수·매도와 금액의 부호에만 답니다. */
export interface ToastPart {
  text: string
  tone?: 'up' | 'down'
}

export interface Toast {
  id: string
  /** 「끊긴 동안 알림」처럼 여러 실행을 묶은 토스트가 「이벤트 보기」로 여는 실행들.
   *  한 실행의 토스트는 `runId` 만 씁니다. */
  runIds?: string[]
  /** 5초 안에 거듭되면 합치는 열쇠 — 실행과 종류입니다. */
  mergeKey: string
  /** 그 실행. 「끊긴 동안 알림」처럼 실행이 없는 토스트는 `null` 입니다. */
  runId: string | null
  /** 그 실행의 버전 id — 이름은 화면이 전략 목록에서 찾습니다. */
  version: string | null
  mode: RunMode | null
  /** 첫 줄의 종류 글. */
  label: string
  body: ToastPart[]
  /** 그 일이 난 시각(ms). */
  time: number
  /** 왼쪽 띠를 경고색으로. */
  warn: boolean
  /** 화면 읽기 도구에 바로 읽히는지(`alert`) — 한도 정지·시세 끊김만입니다. */
  urgent: boolean
  /** 남은 시간(ms). `null` 이면 닫을 때까지 머뭅니다. */
  left: number | null
  /** 5초 안에 거듭된 횟수. 1 이면 표시하지 않습니다. */
  count: number
  /** 마지막으로 바뀐 시각 — 합치기 5초를 이것으로 잽니다. */
  touched: number
}

let toasts: Toast[] = []
const listeners = new Set<() => void>()
let serial = 0

function announce(next: Toast[]): void {
  toasts = next
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useToasts(): Toast[] {
  return useSyncExternalStore(subscribe, () => toasts)
}

export function dismissToast(id: string): void {
  announce(toasts.filter((one) => one.id !== id))
}

export function dismissAllToasts(): void {
  announce([])
}

/** 같은 실행·같은 종류가 이 안에 거듭되면 새로 쌓지 않고 본문을 바꿉니다. */
const MERGE_MS = 5000

type Draft = Omit<Toast, 'id' | 'count' | 'touched'>

function push(draft: Draft): string {
  const now = Date.now()
  const same = toasts.find((one) => one.mergeKey === draft.mergeKey && now - one.touched < MERGE_MS)
  if (same) {
    announce(
      toasts.map((one) =>
        one === same ? { ...one, ...draft, id: one.id, count: one.count + 1, touched: now } : one,
      ),
    )
    return same.id
  }
  serial += 1
  const id = `t${serial}`
  announce([...toasts, { ...draft, id, count: 1, touched: now }])
  return id
}

/** 머무는 시간을 줄입니다. 마우스·초점이 묶음 안에 있거나 창이 가려져 있으면
 *  세지 않습니다 — 안 보는 동안 사라진 알림은 없던 일이 됩니다. */
let held = false
export function holdToasts(on: boolean): void {
  held = on
}

const TICK_MS = 250
let ticking: number | null = null
let lastTick = 0

/** 머무는 시간은 **실제로 흐른 시간**으로 줄입니다 — 창이 뒤에 있으면 브라우저가
 *  타이머를 늦추므로 부른 횟수로 세면 시간이 늘어납니다. */
function startTicking(): void {
  if (ticking !== null || typeof window === 'undefined') return
  lastTick = performance.now()
  ticking = window.setInterval(() => {
    const now = performance.now()
    const spent = now - lastTick
    lastTick = now
    if (held || document.hidden || toasts.length === 0) return
    let changed = false
    const next: Toast[] = []
    for (const one of toasts) {
      if (one.left === null) {
        next.push(one)
        continue
      }
      const left = one.left - spent
      changed = true
      if (left > 0) next.push({ ...one, left })
    }
    if (changed) announce(next)
  }, TICK_MS)
}

/* ── 원천 ──────────────────────────────────────────── */

const SECOND = 1000
const DWELL = { short: 6 * SECOND, long: 10 * SECOND }

/** 주문 화면이 띄우는 알림 — 실행에 딸리지 않은 한 줄입니다. 계좌가 바뀌어 주문
 *  확인창을 닫았거나 정정·취소·청산하던 주문을 접었을 때 씁니다. 급한 것(`urgent`)은
 *  화면 읽기 도구가 바로 읽고 오래 머뭅니다. */
export function noteTradeNotice(notice: { label: string; text: string; urgent: boolean; mergeKey: string }): void {
  push({
    mergeKey: notice.mergeKey,
    runId: null,
    version: null,
    mode: null,
    label: notice.label,
    body: [{ text: notice.text }],
    time: Date.now(),
    warn: true,
    urgent: notice.urgent,
    left: notice.urgent ? DWELL.long : DWELL.short,
  })
}

/** 계좌 손실 한도로 실행을 멈춘 상태 이벤트의 코드(`reason`). 토스트 글은 서버 글
 *  그대로입니다. */
const ACCOUNT_LOSS_CODE = 'account-loss'

/** 다시 붙은 뒤 계좌와 맞춰 보고 감시를 이어 간다는 이벤트의 코드(`reason`). 알아보는
 *  것은 이 코드이고, 아래 글은 토스트에 적는 말입니다. */
const RESUME_CODE = 'reconcile-resume'
const WHY_RESUME = '재접속 뒤 대사 일치 — 감시를 이어 갑니다'

const EXIT_LABEL: Record<string, string> = { stop: '손절', take: '익절', trail: '추적 청산' }

/** 묶음 토스트가 세어 적는 경고 갈래와 그 차례. */
const WARN_ORDER = ['손절', '한도 정지', '안 낸 신호'] as const

/** 이미 본 체결·이벤트의 열쇠. 화면 상태 밖 한 자리라 탭을 옮기거나 목록을 다시
 *  받아도 두 번 울리지 않습니다. */
const seen = new Set<string>()
/** 실행마다 마지막으로 본 시세 상태 — 끊김·이어짐은 이 전이로 압니다. */
const feedSeen = new Map<string, string>()
/** 시세 끊김 토스트의 id — 이어지면 같은 토스트를 바꿉니다. */
const feedToast = new Map<string, string>()
/** 하루 손실 한도를 알린 실행·거래일. 실행마다 거래일당 한 번입니다. */
const limitDays = new Set<string>()
/** 마지막으로 본 실행 줄. 이름·갈래·통화를 찾을 때 씁니다. */
const runsSeen = new Map<string, VerifyRun>()
/** 처음 묶음을 받았는지. */
let primed = false
/** 끊겼다 다시 붙은 시장 — 다음 묶음에서 **그 시장 실행의 것만** 모아 말합니다.
 *  다른 시장의 실행은 끊긴 적이 없어, 그 알림은 평소처럼 하나씩 섭니다. */
const refilled = new Set<RunMarket>()

/** 끊겼다 다시 붙었다는 신호(`refillRuns`). */
export function noteRefill(markets: readonly RunMarket[]): void {
  for (const market of markets) refilled.add(market)
}

/** 그 알림이 다시 붙은 시장의 실행 것인지. 실행 줄을 모르면 묶음에 넣습니다 —
 *  끊긴 동안의 것일 수 있습니다. */
function fromRefilled(one: Candidate, markets: ReadonlySet<RunMarket>): boolean {
  const run = one.draft.runId ? runsSeen.get(one.draft.runId) : undefined
  return run === undefined || markets.has(runMarketOf(run))
}

/** 그 실행·시각의 거래일 — 하루 손실 한도를 거래일마다 한 번 알릴 때 씁니다.
 *  국내 야간은 자정을 넘어도 한 거래일입니다(`kstTradingDay`). */
function limitDayKey(runId: string, time: number): string {
  return `${runId}|${kstTradingDay(time, runsSeen.get(runId)?.session)}`
}

/** 체결가 글. 실행이 호가 단위를 알면 그 자릿수로 맞춥니다(0.05 → 둘째 자리). */
function priceText(value: number, tick: number | undefined): string {
  const digits = tick && tick > 0 ? Math.min(6, (String(tick).split('.')[1] ?? '').length) : undefined
  return value.toLocaleString('en-US', {
    minimumFractionDigits: digits ?? 0,
    maximumFractionDigits: digits ?? 6,
  })
}

/** 한 알림의 꼴. 설정을 거치기 전의 것입니다. */
interface Candidate {
  kind: AlertKind
  tone: AlertTone | null
  draft: Draft
}

function base(run: VerifyRun | undefined, runId: string): Pick<Draft, 'runId' | 'version' | 'mode'> {
  return { runId, version: run?.version ?? null, mode: run?.mode ?? null }
}

function fromFill(fill: VerifyFill): Candidate {
  const run = runsSeen.get(fill.runId)
  const side: ToastPart = {
    text: fill.side === 'buy' ? '매수' : '매도',
    tone: fill.side === 'buy' ? 'up' : 'down',
  }
  const exitLabel = fill.intent === 'exit' ? EXIT_LABEL[fill.reason] : undefined
  if (exitLabel !== undefined) {
    const realized = typeof fill.realized === 'number' && Number.isFinite(fill.realized) ? fill.realized : null
    const tail: ToastPart[] =
      realized === null
        ? [{ text: ` · ${priceText(fill.price, run?.tickSize ?? undefined)}` }]
        : [{ text: ' · 실현 ' }, { text: moneyIn(realized, run?.currency), tone: toneOf(realized) || undefined }]
    const stop = fill.reason === 'stop'
    return {
      kind: 'exit',
      tone: stop ? 'warn' : 'fill',
      draft: {
        ...base(run, fill.runId),
        mergeKey: `${fill.runId}|${fill.reason}`,
        label: exitLabel,
        body: [{ text: `${exitLabel} · ` }, side, { text: ` ${fill.quantity}계약 청산` }, ...tail],
        time: fill.time,
        warn: stop,
        urgent: false,
        left: stop ? DWELL.long : DWELL.short,
      },
    }
  }
  const verb = fill.intent === 'exit' ? '청산' : '체결'
  return {
    kind: 'fill',
    tone: 'fill',
    draft: {
      ...base(run, fill.runId),
      mergeKey: `${fill.runId}|fill`,
      label: '체결',
      body: [side, { text: ` ${fill.quantity}계약 ${verb} · ${priceText(fill.price, run?.tickSize ?? undefined)}` }],
      time: fill.time,
      warn: false,
      urgent: false,
      left: DWELL.short,
    },
  }
}

function limitCandidate(run: VerifyRun | undefined, runId: string, time: number, text: string): Candidate {
  return {
    kind: 'limit',
    tone: 'warn',
    draft: {
      ...base(run, runId),
      mergeKey: `${runId}|limit`,
      label: '한도 정지',
      body: [{ text }],
      time,
      warn: true,
      urgent: true,
      left: null,
    },
  }
}

function fromEvent(event: VerifyEvent): Candidate | null {
  const run = runsSeen.get(event.runId)
  if (event.kind === 'signal') {
    return {
      kind: 'signal',
      tone: null,
      draft: {
        ...base(run, event.runId),
        mergeKey: `${event.runId}|signal`,
        label: '신호',
        body: [{ text: event.text }],
        time: event.time,
        warn: false,
        urgent: false,
        left: DWELL.short,
      },
    }
  }
  if (isRejectedEvent(event)) {
    /* 계좌가 주문을 거부해 실행이 멈췄습니다. 「안 낸 신호」가 아니므로 그 이름과
       묶음 열쇠를 쓰지 않고, 서버 글(거부 코드와 문구)을 그대로 적습니다. 실행이
       멈춘 자리라 사용자가 닫을 때까지 남깁니다. 설정 표에서는 「안 낸 신호」
       줄을 따릅니다 — 둘 다 신호가 체결로 이어지지 못한 일입니다. */
    return {
      kind: 'unsent',
      tone: 'warn',
      draft: {
        ...base(run, event.runId),
        mergeKey: `${event.runId}|rejected`,
        label: '주문 거부',
        body: [{ text: event.text }],
        time: event.time,
        warn: true,
        urgent: true,
        left: null,
      },
    }
  }
  if (isUnsent(event)) {
    if (isDailyLossBlock(event)) {
      const day = limitDayKey(event.runId, event.time)
      if (limitDays.has(day)) return null
      limitDays.add(day)
      return limitCandidate(run, event.runId, event.time, '하루 손실 한도에 닿아 오늘 새 진입을 멈췄습니다')
    }
    return {
      kind: 'unsent',
      tone: 'warn',
      draft: {
        ...base(run, event.runId),
        mergeKey: `${event.runId}|unsent`,
        label: '안 낸 신호',
        body: [{ text: unsentText(event) }],
        time: event.time,
        warn: true,
        urgent: false,
        left: DWELL.long,
      },
    }
  }
  if (event.reason === ACCOUNT_LOSS_CODE) {
    return limitCandidate(run, event.runId, event.time, event.text)
  }
  return null
}

/** 그 실행의 알림을 내는지 — 검증(앱 시뮬레이션) 실행은 설정이 꺼져 있으면 한도
 *  정지·시세 끊김만 냅니다. 모의·실전 계좌 실행은 늘 냅니다. */
function wanted(kind: AlertKind, runId: string | null, settings: AlertSettings): boolean {
  if (runId === null) return true
  const run = runsSeen.get(runId)
  if (run && isPaperRun(run) && !settings.simRuns) return kind === 'limit' || kind === 'feed'
  return true
}

/** 알림 하나를 냅니다 — 토스트와 소리는 설정을 따로 봅니다. */
function raise(one: Candidate): void {
  const settings = settingsNow()
  if (!wanted(one.kind, one.draft.runId, settings)) return
  if (settings.toast && settings.kinds[one.kind].toast) {
    const id = push(one.draft)
    if (one.kind === 'feed' && one.draft.runId) feedToast.set(one.draft.runId, id)
    startTicking()
  }
  if (one.tone && settings.sound && settings.kinds[one.kind].sound && !SILENT_KINDS.includes(one.kind)) {
    playTone(one.tone)
  }
  notifyOs(one.kind, one.draft, settings)
}

/** 묶음 알림의 무게 — 운영체제 알림은 묶음 안 가장 무거운 갈래의 설정과 5초 규칙을
 *  따릅니다. 손절 > 한도 정지 > 안 낸 신호 > 체결 차례입니다. */
function weightOf(one: Candidate): number {
  if (one.kind === 'exit' && one.draft.label === '손절') return 4
  if (one.kind === 'limit') return 3
  if (one.kind === 'unsent') return 2
  if (one.kind === 'fill') return 1
  return 0
}

/** 시세 상태의 전이. 끊기면 실행마다 토스트 하나(닫을 때까지), 다시 이어지면 같은
 *  토스트를 「이어졌습니다」로 바꿉니다. 처음 본 실행이 이미 끊겨 있으면 그 판정
 *  하나만 냅니다. */
function noteFeed(run: VerifyRun): void {
  const before = feedSeen.get(run.id)
  feedSeen.set(run.id, run.feed)
  if (run.state === 'ended') return
  if (run.feed === 'gap' && before !== 'gap') {
    const lost = Math.max(0, Math.round((Date.now() - run.feedAt) / SECOND))
    raise({
      kind: 'feed',
      tone: 'warn',
      draft: {
        ...base(run, run.id),
        mergeKey: `${run.id}|feed`,
        label: '시세 끊김',
        body: [{ text: `시세가 ${lost}초 끊겼습니다 — 조건을 판정하지 못합니다` }],
        time: Date.now(),
        warn: true,
        urgent: true,
        left: null,
      },
    })
    return
  }
  if (before === 'gap' && run.feed !== 'gap') {
    const id = feedToast.get(run.id)
    feedToast.delete(run.id)
    if (id === undefined || !toasts.some((one) => one.id === id)) return
    announce(
      toasts.map((one) =>
        one.id === id
          ? {
              ...one,
              label: '시세 이어짐',
              body: [{ text: '시세가 다시 이어졌습니다' }],
              time: Date.now(),
              warn: false,
              urgent: false,
              left: DWELL.short,
              touched: Date.now(),
            }
          : one,
      ),
    )
  }
}

/** 감시를 이어 간다는 알림. 시세 끊김·이어짐과 같은 갈래(`feed`)의 설정을 따르고,
 *  소리와 운영체제 알림은 내지 않습니다 — 알리는 것은 정상으로 돌아왔다는 사실입니다.
 *  한 번에 여러 실행이 이어지면 한 장으로 묶고 「이벤트 보기」가 그 실행들을 엽니다. */
function noteResume(events: readonly VerifyEvent[]): void {
  if (events.length === 0) return
  const settings = settingsNow()
  if (!settings.toast || !settings.kinds.feed.toast) return
  const runIds = [...new Set(events.map((one) => one.runId))].filter((id) => wanted('feed', id, settings))
  if (runIds.length === 0) return
  const common = {
    label: '감시 이어짐',
    time: Date.now(),
    warn: false,
    urgent: false,
    left: DWELL.short,
  }
  if (runIds.length === 1) {
    push({
      ...common,
      ...base(runsSeen.get(runIds[0]), runIds[0]),
      mergeKey: `${runIds[0]}|resume`,
      body: [{ text: WHY_RESUME }],
    })
  } else {
    push({
      ...common,
      runId: null,
      runIds,
      version: null,
      mode: null,
      mergeKey: 'resume',
      body: [{ text: `재접속 뒤 대사 일치 — 실행 ${runIds.length}개의 감시를 이어 갑니다` }],
    })
  }
  startTicking()
}

/** 실행 목록과 체결·이벤트가 들어오는 **한 자리**. 실행 목록 조회(`list`)는 줄만,
 *  허브 방송(`broadcast`)은 줄과 모든 실행의 최근 체결·이벤트를 싣습니다. */
export function noteRuns(
  runs: readonly VerifyRun[],
  fills: readonly VerifyFill[],
  events: readonly VerifyEvent[],
  from: 'list' | 'broadcast',
): void {
  for (const run of runs) runsSeen.set(run.id, run)
  for (const run of runs) noteFeed(run)
  if (from === 'list') return

  const fresh: { time: number; make: () => Candidate | null }[] = []
  for (const fill of fills) {
    const key = `f|${fillKey(fill)}`
    if (seen.has(key)) continue
    seen.add(key)
    fresh.push({ time: fill.time, make: () => fromFill(fill) })
  }
  /* 감시를 이어 간다는 알림은 따로 모읍니다 — 끊긴 동안의 일이 아니라 지금 상태라,
     「끊긴 동안 알림」 묶음에 섞이면 보이지 않습니다. */
  const resumed: VerifyEvent[] = []
  for (const event of events) {
    const key = `e|${eventKey(event)}`
    if (seen.has(key)) continue
    seen.add(key)
    if (event.reason === RESUME_CODE) resumed.push(event)
    else fresh.push({ time: event.time, make: () => fromEvent(event) })
  }
  /* 처음 묶음은 지나간 일입니다. 하루 손실 한도도 그날 이미 알린 것으로 둡니다. */
  if (!primed) {
    primed = true
    for (const event of events) {
      if (isDailyLossBlock(event)) {
        limitDays.add(limitDayKey(event.runId, event.time))
      }
    }
    return
  }
  noteResume(resumed)
  fresh.sort((a, b) => a.time - b.time)
  const made = fresh.map((one) => one.make()).filter((one): one is Candidate => one !== null)

  if (refilled.size > 0) {
    const markets: ReadonlySet<RunMarket> = new Set(refilled)
    refilled.clear()
    const settings = settingsNow()
    const gap = made.filter((one) => fromRefilled(one, markets))
    const shown = gap.filter(
      (one) => wanted(one.kind, one.draft.runId, settings) && settings.toast && settings.kinds[one.kind].toast,
    )
    if (shown.length >= 2) {
      /* 경고 갈래가 섞였으면 경고 띠와 그 수를 답니다 — 묶여 있어도 손절·한도 정지는
         놓치면 안 됩니다. 시세 끊김은 실행 줄의 전이로 따로 서므로 여기서 세지 않습니다. */
      const counts = WARN_ORDER.map((label) => ({
        label,
        n: shown.filter((one) => one.draft.warn && one.draft.label === label).length,
      })).filter((one) => one.n > 0)
      const tail = counts.map((one) => ` · ${one.label} ${one.n}`).join('')
      const runIds = [...new Set(shown.map((one) => one.draft.runId).filter((id): id is string => id !== null))]
      const draft: Draft = {
        runId: null,
        runIds,
        version: null,
        mode: null,
        mergeKey: 'refill',
        label: '알림',
        body: [{ text: `끊긴 동안 알림 ${shown.length}건${tail}` }],
        time: Date.now(),
        warn: counts.length > 0,
        urgent: false,
        left: DWELL.long,
      }
      push(draft)
      startTicking()
      /* 운영체제 알림도 한 번 — 실행이 하나면 그 실행을, 여럿이면 비워 두고 누르면
         「이벤트 보기」와 같은 탭이 열립니다. 실전이 섞였으면 제목 앞에 「[실전] 」. */
      const heaviest = shown.reduce((best, one) => (weightOf(one) > weightOf(best) ? one : best), shown[0])
      summaryTargets = runIds
      notifyOs(
        heaviest.kind,
        { ...draft, runId: runIds.length === 1 ? runIds[0] : null, mode: shown.some((one) => one.draft.mode === 'real') ? 'real' : null },
        settings,
        `끊긴 동안 알림 ${shown.length}건`,
      )
      /* 끊긴 적 없는 시장의 알림은 묶지 않고 평소처럼 하나씩 세웁니다. */
      for (const one of made) {
        if (!fromRefilled(one, markets)) raise(one)
      }
      return
    }
  }
  for (const one of made) raise(one)
}
