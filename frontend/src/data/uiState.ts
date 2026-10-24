/** 화면이 기억해 두는 것 — 사용자 홈의 파일에 남깁니다.
 *
 *  **브라우저가 아니라 파일에 남기는 이유**는 그 컴퓨터의 다른 창에서도, 앱을
 *  다시 깔아도 같은 것이 서야 하기 때문입니다. 관심종목과 화면 배치는 사용자가
 *  들인 시간이라 브라우저 저장소가 비워지는 일과 함께 사라지면 안 됩니다.
 *
 *  **여기 담는 것은 여섯뿐입니다.** 밝기·최근 본 종목처럼 그 컴퓨터, 그 창에서만
 *  뜻이 있는 것은 브라우저에 그대로 둡니다(`useStoredState`) — 창 크기에 맞춰
 *  둔 값이 다른 컴퓨터까지 따라오면 오히려 어긋납니다.
 *
 *  **인증 정보는 여기 넣지 마세요.** 이 파일은 설정 폴더 옆의 다른 폴더에
 *  있고, 새어도 곤란할 것 없는 것만 담기로 한 자리입니다.
 */
import { useCallback, useSyncExternalStore } from 'react'

/** 파일에 담는 항목. 서버도 같은 목록을 들고 있어, 여기 없는 이름을 보내면
 *  400 으로 되돌아옵니다. */
export const UI_KEYS = [
  'nh.home.watch',
  'nh.trade.layout',
  'nh.trade.drawings',
  'nh.trade.indicators',
  'nh.trade.split',
  'nh.alerts',
] as const

export type UiKey = (typeof UI_KEYS)[number]

/** 못 남긴 이유. 사용자가 할 일이 있는지로 가릅니다 —
 *  `size` 는 지울 것이 있고, `write` 는 할 일이 없습니다. */
export type UiSaveFailure = 'size' | 'write'

export interface UiState {
  /** `loading` 동안에는 값을 그리지 않습니다. 기본값으로 그렸다가 파일 값이
   *  도착해 바뀌면, 사용자는 자기가 뭘 눌렀는지 알 수 없게 됩니다. */
  status: 'loading' | 'ready' | 'failed'
  values: Partial<Record<UiKey, unknown>>
  /** 마지막 저장이 실패했으면 그 이유. 다음 저장이 성공하면 사라집니다. */
  failure: UiSaveFailure | null
}

let state: UiState = { status: 'loading', values: {}, failure: null }
const listeners = new Set<() => void>()

function announce(next: UiState): void {
  state = next
  for (const listener of listeners) listener()
}

export function uiState(): UiState {
  return state
}

export function subscribeUi(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** 브라우저에 남아 있는 옛 값. 파일로 옮길 것이 있는지 봅니다. */
function fromBrowser(): Partial<Record<UiKey, unknown>> {
  const found: Partial<Record<UiKey, unknown>> = {}
  for (const key of UI_KEYS) {
    try {
      const raw = localStorage.getItem(key)
      if (raw !== null) found[key] = JSON.parse(raw)
    } catch {
      /* 못 읽은 값은 옮기지 않습니다. 옮기다 깨진 값을 파일에 남기면
         브라우저를 비워도 안 없어집니다. */
    }
  }
  return found
}

/** 시동 때 파일을 기다리는 한도.
 *
 *  **거절이 아니라 지연을 막는 값입니다.** 끊긴 요청은 곧바로 되돌아와 기본값
 *  경로로 가지만, 답이 안 오고 끊기지도 않으면 기다림이 안 끝납니다. 그동안
 *  화면은 본문을 안 그리므로, 한도가 없으면 **빈 창이 무기한 남습니다.**
 *
 *  3초는 이 요청에 넉넉합니다 — 사용자 폴더의 작은 파일 하나를 읽어 오는
 *  일이라 정상이면 수십 밀리초입니다. 그러면서도 사람이 빈 화면을 보고 고장을
 *  의심하기 전입니다. 앱으로 실행하면 백엔드가 같은 프로그램 안에서 함께
 *  돌고 처음 켤 때 종목 마스터를 내려받으므로, 그만큼 여유를 둔 값입니다. */
const LOAD_TIMEOUT_MS = 3000

/** 파일에서 읽고, 브라우저에 남은 옛 값을 한 번 옮겨 담습니다.
 *
 *  **옮기기는 「비어 있는 항목만」이고 서버가 지킵니다.** 화면은 무엇을 채웠는지
 *  답으로 듣고, **채워진 항목만** 브라우저에서 지웁니다 — 안 채워진 항목까지
 *  지우면 파일에 이미 있던 값과 다른 값이 조용히 사라집니다.
 *
 *  읽지 못하거나 한도 안에 못 받으면 기본값으로 갑니다. 그 상태에서도 저장은
 *  해 보고, 실패하면 띠로 알립니다.
 *
 *  **기본값으로 섰다고 파일이 덮이지는 않습니다.** 저장은 사용자가 실제로 바꾼
 *  항목만 보내고, 서버는 받은 항목만 고쳐 씁니다. 못 읽은 항목은 파일에 그대로
 *  남습니다.
 *
 *  한도를 넘기면 요청을 **끊습니다.** 그냥 두면 뒤늦게 도착한 답이 이미 기본값으로
 *  선 화면을 되돌려, 사용자가 그새 바꾼 것을 지워 버립니다. */
export async function loadUiState(): Promise<void> {
  announce({ status: 'loading', values: {}, failure: null })
  const deadline = new AbortController()
  const timeout = window.setTimeout(() => deadline.abort(), LOAD_TIMEOUT_MS)
  let values: Partial<Record<UiKey, unknown>>
  try {
    const response = await fetch('/api/ui', { signal: deadline.signal })
    if (!response.ok) {
      window.clearTimeout(timeout)
      announce({ status: 'failed', values: {}, failure: null })
      return
    }
    const body = (await response.json()) as { values?: Partial<Record<UiKey, unknown>> }
    values = body.values ?? {}
  } catch {
    window.clearTimeout(timeout)
    announce({ status: 'failed', values: {}, failure: null })
    return
  }

  const waiting = fromBrowser()
  if (Object.keys(waiting).length > 0) {
    try {
      const response = await fetch('/api/ui/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ values: waiting }),
        /* 옮기기도 같은 한도 안에 끝나야 합니다 — 여기서 멈춰도 본문은
           똑같이 안 그려집니다. */
        signal: deadline.signal,
      })
      if (response.ok) {
        const body = (await response.json()) as {
          values?: Partial<Record<UiKey, unknown>>
          imported?: string[]
        }
        values = body.values ?? values
        for (const key of body.imported ?? []) {
          try {
            localStorage.removeItem(key)
          } catch {
            /* 못 지워도 값은 파일에 있습니다. 다음에 다시 옮겨도 파일에 이미
               있는 항목은 서버가 안 덮습니다. */
          }
        }
      }
    } catch {
      /* 옮기지 못했으면 브라우저 값을 그대로 둡니다 — 다음에 다시 옮깁니다. */
    }
  }

  window.clearTimeout(timeout)
  announce({ status: 'ready', values, failure: null })
}

/** 아직 안 보낸 항목. 여러 화면이 잇달아 바꿔도 한 번에 보냅니다. */
const pending = new Map<UiKey, unknown>()
let timer: number | null = null
/** 보내는 중인 요청 수. 보낸 뒤 답이 오기 전에 창이 닫히면 그 요청은 끊깁니다. */
let inflight = 0

/** 모아서 보내는 시간. 사용자가 도형 하나를 옮기는 동안 요청이 수십 번 나가지
 *  않게 합니다. 그렇다고 길게 두면 창을 닫을 때 못 보낸 것이 늘어납니다. */
const SETTLE_MS = 400

/** 서버가 낸 까닭. `message` 는 사람이 읽는 말, `code` 는 갈래입니다. */
interface SaveProblem {
  message?: unknown
  code?: unknown
}

/** 못 남긴 까닭을 화면의 두 얼굴로 옮깁니다.
 *
 *  **가르는 것은 갈래(`code`)이지 문장이 아닙니다.** 앞서는 서버 문장에 특정
 *  낱말이 들었는지로 갈랐는데, 그 문장은 사람이 읽는 말이라 다듬는 자리입니다 —
 *  다듬는 순간 이 갈림이 소리 없이 어긋나 「크기를 넘었다」가 그냥 「못 남겼다」로
 *  떨어집니다. */
function classify(status: number, problem: SaveProblem): UiSaveFailure {
  if (problem.code === 'size') return 'size'
  if (status === 400 && problem.code === 'key') {
    /* 담지 않기로 한 이름을 보낸 것이라 **고칠 코드가 있습니다.** 사용자에게는
       할 일이 없으니 「못 남겼다」로만 알리고, 여기 남겨 개발 중에 잡습니다. */
    console.error(
      `[화면 상태] 파일에 담지 않는 항목을 보냈습니다 — ${String(problem.message ?? '')}`,
    )
  }
  return 'write'
}

async function flush(): Promise<void> {
  timer = null
  if (pending.size === 0) return
  const sending = Object.fromEntries(pending)
  pending.clear()
  inflight += 1
  try {
    const response = await fetch('/api/ui', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ values: sending }),
    })
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as {
        detail?: SaveProblem
      } | null
      announce({ ...state, failure: classify(response.status, body?.detail ?? {}) })
      return
    }
    if (state.failure !== null) announce({ ...state, failure: null })
  } catch {
    announce({ ...state, failure: 'write' })
  } finally {
    inflight -= 1
  }
}

/** 창을 닫으면 사라지는 것이 있는가 — 마지막 저장이 실패한 채이거나, 아직 안
 *  보낸 것이 있거나, 보내는 중입니다. 저장이 다시 성공하면 셋 다 아닙니다. */
export function hasUnsaved(): boolean {
  return state.failure !== null || pending.size > 0 || inflight > 0
}

/** 창을 닫거나 새로 고칠 때 못 남긴 것이 있으면 한 번 되묻습니다.
 *
 *  못 남겼다는 띠는 며칠이면 눈에 익어 막는 힘이 약해집니다. 실제로 잃는 순간은
 *  종료 때라 그때 한 번 묻습니다 — 이 창에서 바꾼 관심종목·배치·그린 것이 파일에
 *  없는 채로 창이 닫히면 이번에 한 일이 사라집니다. 남길 것이 없으면 아무것도
 *  묻지 않습니다.
 *
 *  확인창의 글은 브라우저 것이라 여기서 정하지 못합니다 — `returnValue` 에 무엇을
 *  적든 보이지 않고, 다만 옛 엔진은 빈 글자가 아닌 값이어야 묻습니다.
 *
 *  돌려주는 함수가 걸어 둔 것을 풉니다. */
export function guardUnload(): () => void {
  const ask = (event: BeforeUnloadEvent) => {
    if (!hasUnsaved()) return
    event.preventDefault()
    event.returnValue = '남기지 못한 것이 있습니다'
  }
  window.addEventListener('beforeunload', ask)
  return () => window.removeEventListener('beforeunload', ask)
}

/** 값 하나를 바꿉니다. 화면에는 바로 서고, 파일에는 모아서 보냅니다.
 *
 *  **보내기가 실패해도 화면은 안 되돌립니다.** 사용자가 한 일을 서버 사정으로
 *  되돌리면 무엇이 남았는지 알 수 없게 됩니다 — 대신 띠로 알립니다. */
export function setUiValue(key: UiKey, value: unknown): void {
  announce({ ...state, values: { ...state.values, [key]: value } })
  pending.set(key, value)
  if (timer !== null) window.clearTimeout(timer)
  timer = window.setTimeout(() => void flush(), SETTLE_MS)
}

/** 지금 담겨 있는 값. 아직 못 받았거나 없으면 기본값입니다. */
export function uiValue<T>(key: UiKey, initial: T): T {
  const value = state.values[key]
  return value === undefined ? initial : (value as T)
}

/** 화면에서 쓰는 꼴. `useStoredState` 와 같은 모양이라 부르는 자리가 안 바뀝니다.
 *
 *  세 번째 값이 **그릴 준비가 됐는지**입니다. 파일 값이 오기 전에 기본값으로
 *  그리면, 도착한 뒤 눈앞에서 배치가 바뀝니다. */
export function useUiState<T>(key: UiKey, initial: T): [T, (value: T) => void, boolean] {
  const snapshot = useSyncExternalStore(subscribeUi, uiState)
  const store = useCallback((next: T) => setUiValue(key, next), [key])
  const value = snapshot.values[key]
  return [value === undefined ? initial : (value as T), store, snapshot.status !== 'loading']
}
