/** 활성 환경(모의·실전)을 아는 자리.
 *
 *  **기준은 서버 하나입니다.** 화면이 「지금 모의」를 따로 들고 있지 않습니다 —
 *  화면이 믿는 것과 서버가 요청을 내보내는 환경이 갈리면, 모의인 줄 알고 낸 주문이
 *  실전 계좌로 갑니다. 배지·설정 창·주문 단추가 전부 여기 값을 읽고, 값은 **서버가
 *  답한 것으로만** 바뀝니다.
 *
 *  **읽기 전에는 실전으로 가정하지 않습니다.** 모르는 것은 모른다고 세웁니다.
 *
 *  전환은 서버에 청하고 응답의 값으로만 바꿉니다. 화면이 먼저 바꿔 두고 나중에
 *  맞추는 순서는, 그 사이에 낸 주문이 어느 환경으로 나갔는지를 화면이 말할 수
 *  없게 합니다. 실패하면 서버에 다시 물어 그 답으로 되돌립니다.
 *
 *  **환경이 바뀌면 계좌·시세·가능수량이 담아 둔 값은 다른 계좌의 값이라 지웁니다.**
 *  「한 번 받은 값은 안 지운다」는 규칙은 같은 계좌의 낡은 값을 지키는 것이지
 *  다른 계좌의 값을 지키는 것이 아닙니다. 지우라는 신호는 세대 번호 하나로 냅니다 —
 *  값을 담는 자리들이 요청 전에 번호를 적어 두고, 답이 왔을 때 번호가 달라졌으면
 *  버립니다. 늦게 온 옛 환경의 답이 새 환경의 값으로 서는 일이 없습니다.
 *
 *  **응답마다 어느 환경에서 나온 값인지가 실려 옵니다**(`x-nh-environment`). 담는
 *  자리는 그 이름을 값에 붙여 두고, 환경을 몰랐다가 알게 될 때 이름이 같은 값은
 *  그대로 두고 다른 값·이름 없는 값만 비웁니다 — 이름을 알게 된 것이지 값이 바뀐
 *  것이 아니기 때문입니다.
 */
import { useSyncExternalStore } from 'react'

export type Environment = 'paper' | 'real'

/** 환경 이름의 우리말. 배지·설정·주문 단추가 같은 낱말을 씁니다. */
export const ENVIRONMENT_LABEL: Record<Environment, string> = { paper: '모의', real: '실전' }

/** 설정 화면이 보는 인증 정보 한 칸. 값 자체는 오지 않습니다 — 채워져 있는지와
 *  가린 표시뿐입니다. */
export interface FieldView {
  set: boolean
  masked: string
}

export type CredentialField = 'app_key' | 'app_secret'

export interface ConfigView {
  /** 설정 파일에 적힌 다음 실행의 기본 환경. 화면 판정에는 안 씁니다 — 실행 중
   *  파일을 손으로 고치면 활성 환경과 갈릴 수 있습니다. */
  default_environment: string
  /** 서버가 지금 요청을 내보내는 환경. 설정을 못 읽어 모르면 `null` 입니다. */
  active_environment: Environment | null
  environments: Record<string, Record<string, Record<CredentialField, FieldView>>>
}

/** 상태 넷.
 *
 *  `loading` 아직 서버에 안 물어봤거나 다시 묻는 중 · `ready` 안다 · `failed` 물었는데
 *  서버도 모른다(설정을 못 읽음) · `switching` 바꿔 달라고 청해 두고 답을 기다리는 중.
 *
 *  **`loading` 과 `switching` 동안에는 값을 담는 자리들이 새 조회를 내지 않습니다.**
 *  어느 계좌의 값이 될지 모르는 채로 부르면, 온 값에 붙일 이름이 없습니다. */
export type EnvironmentStatus = 'loading' | 'ready' | 'failed' | 'switching'

export interface EnvironmentState {
  status: EnvironmentStatus
  /** 서버가 마지막으로 답한 활성 환경. 모르면 `null` 입니다. */
  active: Environment | null
  /** 환경이 다른 환경으로 바뀔 때마다 오릅니다. 값을 담는 자리들이 이 번호로
   *  늦게 온 옛 환경의 답을 버립니다. */
  generation: number
  config: ConfigView | null
  /** 설정 읽기가 한 번이라도 끝났는지(읽었든 못 읽었든). `config` 가 `null` 인
   *  까닭이 「아직 안 읽음」인지 「못 읽음」인지를 가릅니다. */
  configRead: boolean
}

/** 값을 담는 자리들이 듣는 신호. `switched` 는 다른 환경으로 바뀐 것이라 전부
 *  비우고, `resolved` 는 몰랐다가 알게 된 것이라 이름이 다른 값만 비웁니다. */
export type EnvironmentChange =
  | { kind: 'switched'; active: Environment }
  | { kind: 'resolved'; active: Environment }

const INITIAL: EnvironmentState = { status: 'loading', active: null, generation: 0, config: null, configRead: false }

let state: EnvironmentState = INITIAL
/** 마지막으로 알았던 환경. 서버가 잠시 모른다고 답했다가 다시 알게 됐을 때, 그
 *  사이에 환경이 바뀌었는지를 이것과 대 봅니다. */
let lastKnown: Environment | null = null
const listeners = new Set<() => void>()
const changeListeners = new Set<(change: EnvironmentChange) => void>()

function announce(next: EnvironmentState): void {
  state = next
  for (const listener of listeners) listener()
}

export function environmentState(): EnvironmentState {
  return state
}

export function subscribeEnvironment(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** 값을 담는 자리가 「환경이 바뀌면 비우라」는 신호를 듣는 길. */
export function onEnvironmentChange(listener: (change: EnvironmentChange) => void): () => void {
  changeListeners.add(listener)
  return () => changeListeners.delete(listener)
}

export function useEnvironment(): EnvironmentState {
  return useSyncExternalStore(subscribeEnvironment, environmentState, environmentState)
}

/** 지금 세대 번호. 조회를 내기 전에 적어 둡니다. */
export function generation(): number {
  return state.generation
}

/** 값을 담는 자리가 새 조회를 내도 되는지. 환경을 아는 상태(`ready`)와, 서버도
 *  모른다고 답한 상태(`failed`)에서는 냅니다 — 뒤는 서버가 제 환경으로 답하는
 *  참값이고, 배지가 모른다고 말하며 주문은 막혀 있어 값이 서도 거짓이 아닙니다.
 *  안 내면 계좌 자리가 뼈대에 갇혀 「곧 온다」가 거짓이 됩니다. */
export function environmentSettled(): boolean {
  return state.status === 'ready' || state.status === 'failed'
}

/** 응답 헤더의 값을 환경 이름으로. 모르는 값은 없는 것으로 봅니다. */
export function environmentOf(response: Response): Environment | null {
  const value = response.headers.get('x-nh-environment')
  return value === 'paper' || value === 'real' ? value : null
}

/** 모의투자에서는 NH선물이 제공하지 않는 조회라고 서버가 답했는가. **서버가 붙이는
 *  헤더 하나로만** 가립니다 — 오류 문장은 바뀔 수 있어 글자로 가리지 않습니다.
 *  이 답은 다시 불러도 같고, 실전 환경에서는 오지 않습니다. */
export function paperUnavailable(response: Response): boolean {
  return response.headers.get('x-nh-error-kind') === 'paper-unavailable'
}

/** 그 거래소의 시세를 쓰려면 **시세 사용 신청이 먼저**라고 서버가 답했는가.
 *  위와 같이 헤더 하나로만 가립니다. 신청하기 전에는 다시 불러도 같은 답이라
 *  거절로 다루고, 무엇을 하면 되는지는 서버가 준 문장을 그대로 보입니다. */
export function quoteSubscription(response: Response): boolean {
  return response.headers.get('x-nh-error-kind') === 'quote-subscription'
}

/** 온 답을 담아도 되는지. 값을 담는 자리 전부가 같은 물음을 같은 순서로 묻습니다.
 *
 *  ① 요청 뒤에 환경이 바뀌었으면(세대가 다르면) 옛 환경의 답이라 버립니다.
 *  ② 답에 실린 환경이 화면이 믿는 환경과 다르면 버립니다 — 서버가 화면 모르게
 *     바뀐 것이라, 서버에 다시 물어 화면을 맞춥니다. 화면이 아직 모르는 상태면
 *     답에 실린 이름을 그대로 값에 붙입니다.
 *
 *  버린 답에는 화면에 아무 얼굴도 세우지 않습니다 — 사용자가 할 일이 「기다림」과
 *  같고, 맞춘 뒤에는 그 자리가 다시 채워집니다. */
export function accepts(response: Response, since: number): boolean {
  if (since !== state.generation) return false
  const answered = environmentOf(response)
  if (answered !== null && state.active !== null && answered !== state.active) {
    if (import.meta.env.DEV) {
      console.warn(
        `[환경] 화면 ${state.active}, 응답 ${answered}. 다른 환경의 답이라 버리고 다시 묻습니다.`,
      )
    }
    if (state.status === 'ready') void resync()
    return false
  }
  return true
}

/** 서버가 답한 활성 환경을 받아들입니다. 읽기·30초 확인·전환 응답·실시간 알림이
 *  전부 여기로 옵니다.
 *
 *  알던 환경과 다른 환경이면 세대를 올리고 「바뀌었다」를 알립니다. 몰랐다가
 *  알게 된 것이면 「알게 됐다」만 알립니다 — 값은 그대로이고 이름이 붙은 것입니다.
 *  서버가 모른다고 답하면 배지만 모른다고 세우고 값은 둡니다 — 값이 틀린 것이
 *  아니라 지금 이름을 확인할 수 없는 것입니다.
 *
 *  전환 응답을 기다리는 중(`switching`)이면 그 상태는 그대로 둡니다 — 실시간이
 *  먼저 알려 와도 설정 창은 응답까지 기다립니다. */
export function noteActive(active: Environment | null): void {
  const waiting = state.status === 'switching'
  if (active === null) {
    /* 설정 화면이 보는 값은 그대로 둡니다 — 잠깐 못 닿은 것이지 인증 정보가 빈
       것이 아닙니다. 여기서 지우면 계좌 화면이 「인증 정보가 없습니다」라고 거짓을
       말합니다. 서버가 정말 모르는 경우는 설정 읽기 자체가 null 을 실어 옵니다. */
    announce({ ...state, status: waiting ? 'switching' : 'failed', active: null })
    return
  }
  /* 설정 화면이 보는 값에도 같은 환경을 적어 둡니다 — 인증 정보가 다 찼는지는
     그 환경의 칸을 보고 답하므로, 여기가 옛 환경으로 남으면 실전 배지 밑에서
     모의 칸을 묻습니다. */
  const config = state.config ? { ...state.config, active_environment: active } : null
  const previous = state.active ?? lastKnown
  lastKnown = active
  const status: EnvironmentStatus = waiting ? 'switching' : 'ready'
  if (previous !== null && previous !== active) {
    announce({ ...state, status, active, config, generation: state.generation + 1 })
    for (const listener of changeListeners) listener({ kind: 'switched', active })
    return
  }
  const resolved = state.active === null
  announce({ ...state, status, active, config })
  if (resolved) for (const listener of changeListeners) listener({ kind: 'resolved', active })
}

interface HealthReply {
  status: string
  mode: string
  active_environment?: Environment | null
}

/** 서버가 살아 있는지와 활성 환경을 **한 번에** 묻습니다. 상단의 연결 낱말과 배지가
 *  같은 확인에서 나와야, 둘이 서로 다른 시각의 사실을 말하지 않습니다. */
export async function checkHealth(): Promise<'ok' | 'error'> {
  try {
    const response = await fetch('/api/health')
    if (!response.ok) {
      noteActive(null)
      return 'error'
    }
    const data = (await response.json()) as HealthReply
    noteActive(named(data.active_environment))
    return data.status === 'ok' ? 'ok' : 'error'
  } catch {
    /* 서버에 못 닿으면 환경도 모르는 것입니다. 옛 배지를 그대로 두면 서버가
       그 사이 바뀌었어도 화면은 모릅니다. */
    noteActive(null)
    return 'error'
  }
}

function named(value: unknown): Environment | null {
  return value === 'paper' || value === 'real' ? value : null
}

/** 화면이 믿는 환경이 서버와 어긋난 것을 알았을 때 다시 묻습니다. 묻는 동안은
 *  `loading` 이라 값을 담는 자리들이 새 조회를 내지 않습니다. */
async function resync(): Promise<void> {
  announce({ ...state, status: 'loading' })
  await checkHealth()
}

/** 설정(인증 정보 상태 + 활성 환경)을 읽습니다. 앱이 뜰 때와 인증 정보를 저장한
 *  뒤에 부릅니다. 못 읽으면 환경도 모르는 것입니다. */
export async function loadConfig(): Promise<void> {
  try {
    const response = await fetch('/api/config')
    if (!response.ok) {
      unreadable()
      return
    }
    const view = (await response.json()) as ConfigView
    announce({ ...state, config: view, configRead: true })
    noteActive(named(view.active_environment))
  } catch {
    unreadable()
  }
}

/** 설정을 못 읽었을 때. 앞서 읽어 둔 칸 상태도 지웁니다 — 남겨 두면 설정 화면이
 *  지금은 확인할 수 없는 값을 지금 값처럼 보입니다. */
function unreadable(): void {
  announce({ ...state, config: null, configRead: true })
  noteActive(null)
}

/** 전환을 청한 결과. 실패는 던지지 않고 얼굴로 냅니다 — 거절은 다시 눌러도 같은
 *  답이 오고, 못 닿음은 다시 눌러 볼 만합니다. */
export type SwitchResult =
  | { ok: true }
  | { ok: false; kind: 'rejected' | 'retry'; detail: string }

/** 활성 환경을 바꿔 달라고 청합니다. **배지는 서버가 답한 값으로만 바뀝니다.**
 *
 *  200 이 아니면 바뀐 것이 아닙니다 — 그래도 서버가 어느 쪽인지는 다시 읽어
 *  맞춥니다. 응답을 못 받았으면 옛 배지를 믿지 않고 마찬가지로 다시 읽습니다. */
export async function switchEnvironment(target: Environment): Promise<SwitchResult> {
  announce({ ...state, status: 'switching' })
  let result: SwitchResult
  try {
    const response = await fetch('/api/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ default_environment: target }),
    })
    if (response.ok) {
      const data = (await response.json()) as { active_environment?: Environment | null }
      announce({ ...state, status: 'ready' })
      noteActive(named(data.active_environment))
      result = { ok: true }
    } else {
      const body = (await response.json().catch(() => null)) as { detail?: string } | null
      result = {
        ok: false,
        /* 대상에 키가 없음(400)·다른 전환이 진행 중(409)·저장 실패(500)는 다시
           눌러도 같은 답입니다. 그 밖은 서버까지 못 간 것이라 다시 눌러 볼 만합니다. */
        kind: response.status === 400 || response.status === 409 || response.status === 500
          ? 'rejected'
          : 'retry',
        detail: body?.detail ?? '',
      }
    }
  } catch {
    result = { ok: false, kind: 'retry', detail: '' }
  }
  if (!result.ok) {
    /* 바뀌지 않았어도 서버가 어느 쪽인지는 다시 읽습니다 — 응답을 못 받은 경우
       옛 배지가 참이라는 보장이 없습니다. 읽는 동안은 아직 「바꾸는 중」이라
       배지가 흔들리지 않고, 읽은 답으로 정리합니다. */
    await loadConfig()
    announce({ ...state, status: state.active === null ? 'failed' : 'ready' })
  }
  return result
}

const MARKETS = ['domestic', 'overseas'] as const
const FIELDS: CredentialField[] = ['app_key', 'app_secret']

/** 그 환경의 한 시장에 인증 정보가 갖춰졌는지 — 키와 시크릿이 둘 다 있어야 합니다. */
export function marketConfigured(view: ConfigView, env: Environment, market: string): boolean {
  const cells = view.environments?.[env]?.[market]
  return FIELDS.every((field) => cells?.[field]?.set === true)
}

/** 그 환경으로 바꿀 수 있는지 — 국내·해외 중 **하나라도** 인증 정보가 갖춰져 있으면
 *  됩니다. 서버가 전환을 받는 조건과 같습니다. */
export function canSwitchTo(view: ConfigView, env: Environment): boolean {
  return MARKETS.some((market) => marketConfigured(view, env, market))
}
