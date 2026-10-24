import { useSyncExternalStore } from 'react'

import { draftSeedOf, withMarketMeta, type StrategyVersion } from './strategyList'
import { RULE_KEYS, seedDraft, withNewFields, type SettingsDraft } from './strategyRules'
import { setLegacyOperands } from './indicatorOperands'
import { anyConditions, summaryOf } from './ruleSummary'
import {
  accountModesOf,
  eventKey,
  fillKey,
  isAccountMode,
  isPaperRun,
  runMarketOf,
  type AccountMode,
  type RunMarket,
} from './strategyRuns'
import { noteRefill, noteRuns } from './alerts'
import type { Environment } from './environment'
import type {
  RunMode,
  VerifyEvent,
  VerifyFill,
  VerifyOrder,
  VerifyRun,
  VerifySnapshot,
} from './strategyRuns'

/* 전략주문 탭의 상태를 화면 밖에 둡니다.
 *
 * **화면이 사라져도 상태는 남아야 합니다.** 앱은 페이지마다 화면을 통째로
 * 갈아 끼우므로, 상단에서 「종목」에 갔다 돌아오면 전략주문 화면은 새로
 * 태어납니다. 상태를 화면 안에 두면 그때 검증 실행도, 보낸 요청도, 고치던
 * 설정도 함께 사라집니다.
 *
 * 그래서 마스터 색인과 같은 방식(모듈 저장소 + `useSyncExternalStore`)으로
 * 한 벌만 두고 화면이 그것을 읽습니다.
 *
 * **전략 목록과 설정은 서버에 남습니다.** 새로고침하면 서버에서 다시 받아
 * 오므로 고쳐 둔 것이 그대로 섭니다. 검증·진행 실행은 빈 목록으로 시작해 서버의
 * 답으로 채웁니다 — 지어낸 실행을 세우지 않습니다.
 */

export const STRATEGY_TABS = ['전략 목록', '전략 설정', '전략 검증', '전략 진행', '전략 분석'] as const
export type StrategyTab = (typeof STRATEGY_TABS)[number]

/** 목록에서 「검증 화면으로」·「진행 화면으로」를 누를 때 함께 건너가는 것.
 *
 *  그 전략의 실행이 이미 있으면 그것을 고르고, 없으면 추가 패널을 그 전략·
 *  버전으로 채워 엽니다. 화면이 다 받은 뒤에는 지웁니다 — 남겨 두면 다음에
 *  그 탭에 들를 때 패널이 또 열립니다. */
export interface OpenRequest {
  strategy: string
  version: string
}

/** 저장 요청에 서버가 답한 한 줄. **오류와 경고를 갈라 둡니다** — 오류는 저장을
 *  막고, 경고는 받은 뒤 화면이 알려만 줍니다. */
export interface SaveProblem {
  /** 어느 칸의 말인지. 칸 옆에 붙일 때 씁니다. */
  field: string
  severity: 'error' | 'warning'
  message: string
}

/** 저장을 한 번 시도한 결과. */
export interface SaveResult {
  /** 저장됐는지. 경고만 있으면 참입니다. */
  ok: boolean
  /** 서버가 준 한 줄. 못 보냈으면 화면이 지은 한 줄입니다. */
  message: string
  problems: SaveProblem[]
  /** 막힌 일의 이름(「저장」 대신 설 말). 없으면 「저장」입니다. */
  head?: string
}

/** 막힌 일의 한 줄 — 「{무엇을} 하지 못했습니다 — {까닭}」. 답의 글이 이미
 *  「…하지 못했습니다」로 시작하면 그 머리를 떼고 까닭만 잇습니다 — 「보관하지
 *  못했습니다 — 저장하지 못했습니다 — …」처럼 같은 말이 두 번 서지 않게. 까닭이
 *  없으면 머리 한 문장입니다. 복제·보관·새 버전 저장이 이 하나를 씁니다. */
export function failLine(head: string, message: string): string {
  const reason = message.replace(/^[^—]*하지 못했습니다\s*(—\s*)?/, '').trim()
  return reason ? `${head} — ${reason}` : head
}

/** 목록을 받아 오는 중인지. **받는 중과 못 받음은 얼굴이 다릅니다** — 앞은
 *  기다리면 되고 뒤는 아닙니다. */
export type ListStatus = 'loading' | 'ready' | 'failed'

export interface VerifyState {
  runs: VerifyRun[]
  /** 실행 목록을 받아 온 상태. 받는 중·못 받음·있음이 서로 다른 얼굴입니다. */
  status: ListStatus
  failure: string | null
  /** 한 번에 둘 수 있는 실행 수. **서버가 정합니다**(실시간 구독 자리). */
  max: number
  /** 지금 세울 수 있는 계좌 갈래. **서버가 정합니다** — 못 받았으면 빈 목록이라
   *  계좌 실행을 세우는 길이 닫힙니다(`accountModesOf`). */
  accountModes: AccountMode[]
  /** 실행 목록을 답할 때 서버의 활성 환경. 못 읽었거나 전환 중이면 `null` 입니다. */
  activeEnvironment: Environment | null
  /** 실행마다의 한 벌 — 체결·이벤트·곡선. 목록과 따로 받습니다.
   *
   *  **실행 id 로 나눠 둡니다.** 검증 탭과 진행 탭은 서로 다른 실행을 볼 수 있어,
   *  한 칸을 같이 쓰면 한쪽이 고른 실행의 표가 다른 쪽에 섭니다. 각 탭은 제가
   *  보는 실행의 칸만 읽습니다(`snapshotOf`). */
  snapshots: Record<string, VerifySnapshot>
  /** 추가 패널이 마지막으로 받은 거절 까닭. 패널 안 한 줄로 섭니다. */
  addWhy: string | null
  /** 지금 요청이 나가 있는 실행. 그 줄의 단추를 잠급니다 — 같은 동작을 두 번
   *  보내면 두 번째가 무엇을 하는지 화면이 말할 수 없습니다. */
  acting: string | null
  /** **보는 실행.** 차트·카드·마커가 그리는 것은 이 하나입니다. */
  pickedId: string
  /** **고른 실행들.** 「선택 …」 단추가 거는 대상입니다. 보는 실행과 따로
   *  둡니다 — 여럿을 고른 채 하나를 보아야 하고, 둘을 한 값에 담으면 무엇을
   *  고르느냐에 따라 차트가 그리는 실행이 흔들립니다(진행 화면과 같은 짝). */
  checked: string[]
  /** 「신호 · 주문도 표시」. 체결만 기본이라 켠 것은 기억합니다. */
  showDetail: boolean
  /** 추가 패널이 열려 있는지, 열렸다면 무엇으로 채워져 있는지. */
  add: OpenRequest | null
  /** **목록에서 들고 온 요청.** 아직 안 풀린 상태입니다 — 화면이 받아서
   *  「그 실행을 고를지, 추가 패널을 열지」를 정하고 지웁니다. */
  pending: OpenRequest | null
}

export interface RunState {
  /** 실행 목록은 **검증과 한 벌**이라 여기 없습니다(`verify.runs`) — 서버가
   *  한 목록을 내고 화면이 갈래로 가릅니다. 여기 남는 것은 진행 화면만의
   *  것입니다: 고른 것들, 보는 것, 열린 패널. */
  checked: string[]
  shownId: string
  add: OpenRequest | null
  /** 목록에서 들고 온 요청. 검증 쪽과 같은 뜻입니다. */
  pending: OpenRequest | null
}

export interface StrategyState {
  tab: StrategyTab
  rows: StrategyVersion[]
  /** 목록을 받아 온 상태. 못 받았으면 까닭이 `failure` 에 있습니다. */
  status: ListStatus
  failure: string | null
  selectedId: string | null
  /** 아직 저장되지 않아 **목록에 없는** 새 버전. 「새 전략」은 이 자리에 줄을
   *  하나 세우고 설정 탭을 엽니다 — 저장이 통과해야 목록에 섭니다. 목록에만
   *  있고 서버에 없는 줄을 두면 새로고침 한 번에 사라지는데, 사용자는 만든
   *  것이 남았다고 읽습니다. */
  draftVersion: StrategyVersion | null
  /** 고치는 중인 설정과 마지막으로 저장을 누른 값. 버전마다 한 벌씩입니다. */
  drafts: Record<string, SettingsDraft>
  saved: Record<string, SettingsDraft>
  /** 고치는 중인 **줄의 칸**(이름·종목). 설정 초안과 자리를 나눠 두는 것은
   *  담기는 곳이 달라서입니다 — 설정은 `drafts` 로, 줄은 목록으로 갑니다.
   *  **목록은 저장된 이름을 그대로 보여 줍니다**: 여기 있는 동안은 아직
   *  서버가 모르는 값이라, 목록까지 바꾸면 저장하지 않고 떠났을 때 목록에만
   *  남은 이름이 생깁니다. */
  edits: Record<string, Partial<StrategyVersion>>
  /** 지금 저장 요청이 나가 있는 버전. 한 번에 하나입니다. */
  saving: string | null
  /** 마지막 저장 시도에 서버가 답한 것. 버전마다 한 벌입니다. */
  results: Record<string, SaveResult>
  /** 전략을 담아 둔 파일을 **마지막으로 읽었을 때 어땠는지.** */
  store: StoreState | null
  /** 실행을 담아 둔 파일의 같은 값. 파일이 달라 따로 옵니다. */
  runStore: StoreState | null
  verify: VerifyState
  run: RunState
}

/** 서버가 상태 파일을 마지막으로 읽었을 때의 모습. **답마다 실려 옵니다.**
 *
 *  `missing` 은 아직 한 번도 안 쓴 것이라 **정상**입니다 — 처음 켠 앱이 그렇고,
 *  그때는 화면이 아무 말도 하지 않습니다. `broken` 은 있었는데 못 읽은 것이고,
 *  `otherApp` 은 다른 앱이 쓴 파일이라 담긴 것을 **안 쓴** 것입니다.
 *
 *  **다음에 제대로 담길 때까지 그대로 옵니다** — 서버가 들고 있다가 놓습니다.
 *  화면이 그 사이에 잊으면, 목록이 왜 비었는지 말할 수 있는 자리가 없습니다. */
export interface StoreState {
  status: 'missing' | 'ok' | 'broken'
  /** 담긴 것을 실제로 쓴 상태인지(`ok` 이고 다른 앱 것이 아닐 때만 참).
   *  **화면은 이 칸을 안 읽습니다** — 할 말은 `status` 와 `otherApp` 이 가르고,
   *  이 칸은 그 둘에서 나오는 값이라 같은 말을 두 번 하게 됩니다. 서버가 주는
   *  모양을 그대로 들고 있습니다. */
  stored: boolean
  /** 못 읽은 파일을 치운 자리. **이름만** 옵니다(폴더는 화면이 말합니다).
   *  못 치웠거나 담긴 것이 인증 자료라 지운 경우에는 `null` 입니다. */
  movedTo: string | null
  /** 그 파일을 쓴 다른 앱. 값이 있으면 담긴 것을 안 썼다는 뜻입니다. */
  otherApp: string | null
}

/** 답에 실려 온 상태 값. 모르는 모양이면 `null` — 지어내지 않습니다. */
export function tookStore(body: unknown): StoreState | null {
  const said = (body as { store?: unknown })?.store
  if (!said || typeof said !== 'object') return null
  const row = said as Record<string, unknown>
  const status = row.status
  if (status !== 'missing' && status !== 'ok' && status !== 'broken') return null
  return {
    status,
    stored: row.stored === true,
    movedTo: typeof row.movedTo === 'string' && row.movedTo !== '' ? row.movedTo : null,
    otherApp: typeof row.otherApp === 'string' && row.otherApp !== '' ? row.otherApp : null,
  }
}

/** 상태 파일 때문에 화면이 해야 할 말. **무슨 일이 있었나**(`title`)와 **왜·다음**
 *  (`reason`)으로 갈라 둡니다 — 자리가 통째로 빈 화면은 둘을 제목과 이유 줄로
 *  세우고, 값이 선 자리 곁에서는 한 줄로 잇습니다. */
export interface StoreNote {
  title: string
  /** 덧붙일 말이 없으면 `null` 입니다. */
  reason: string | null
  /** `reason` 이 **자리가 통째로 빈 때만** 참인 말인가. 줄이 선 표 위에서
   *  「목록이 비어 있어도」라고 하면 틀린 말이 됩니다. */
  emptyOnly: boolean
}

/** 상태 파일 때문에 화면이 해야 할 말. 할 말이 없으면 `null` 입니다.
 *
 *  담아 둔 것이 안 왔는데 아무 말이 없으면, 사용자는 「내가 만든 것이
 *  사라졌다」로 읽습니다.
 *
 *  `missing`(아직 안 담음)과 `ok` 에는 할 말이 없습니다. 옮긴 자리는 **서버가
 *  줄 때만** 적습니다 — 못 치운 경우와 지운 경우에는 자리가 없고, 없는 자리를
 *  지어내면 사용자가 없는 파일을 찾습니다. */
export function storeNote(kind: 'versions' | 'runs', state: StoreState | null): StoreNote | null {
  if (!state) return null
  const versions = kind === 'versions'
  if (state.otherApp) {
    /* **전략 파일에는 아직 이 판정이 없습니다** — 서버가 그 파일에는 쓴 앱을
       적지 않습니다. 그 칸을 내기 시작하면 이 말이 그대로 섭니다.
       「덮어씁니다」는 실제 동작입니다: 담을 때 같은 자리의 파일을 통째로 바꿔
       놓고 사본을 두지 않습니다. */
    return versions
      ? {
          title: '담긴 전략을 쓰지 않았습니다',
          reason: '이 앱이 만든 파일이 아닙니다 — 여기서 저장하면 그 파일을 덮어씁니다',
          emptyOnly: false,
        }
      : {
          title: '이 앱이 만든 파일이 아니라서 담긴 실행을 쓰지 않았습니다',
          reason: null,
          emptyOnly: false,
        }
  }
  if (state.status !== 'broken') return null
  /* **전략과 실행이 다른 말을 합니다.** 전략은 파일을 못 읽었을 뿐 사용자가
     잃은 것이 없지만, 실행은 못 읽은 순간 **실제로 돌지 않습니다** — 그 말을
     안 하면 세워 둔 실행이 살아 있는 것으로 읽혀 다시 세우지 않습니다. */
  const title = versions
    ? '저장해 둔 전략을 읽지 못했습니다'
    : '담아 두었던 실행을 읽지 못했습니다 — 그 실행들은 지금 돌지 않습니다'
  if (!state.movedTo) {
    /* **옮긴 자리가 없으면 파일의 행방을 말하지 않습니다.** 치우지 못한 경우와
       치우려는 사이 사라진 경우가 같은 모습으로 오고, 답에는 둘을 가를 칸이
       없습니다. 어느 쪽이든 참인 말만 남깁니다 — 전략은 달리 안심시킬 말이
       없어 「지운 것이 아니다」를 둡니다. */
    return versions
      ? { title, reason: '목록이 비어 있어도 이 앱이 지운 것이 아닙니다', emptyOnly: true }
      : { title, reason: null, emptyOnly: false }
  }
  /* 파일 이름은 **괄호로 떼어** 답니다 — 「{이름}으로/로」는 이름 끝소리마다
     조사가 갈리고, 떼어 두면 줄이 좁아 접힐 때도 마디 차례(무슨 일 → 파일
     자리)가 지켜집니다. */
  const moved = `상태 폴더에 옮겨 두었습니다(파일 이름 ${state.movedTo})`
  return { title, reason: versions ? `그 파일은 ${moved}` : `파일은 ${moved}`, emptyOnly: false }
}

function initial(): StrategyState {
  return {
    tab: '전략 목록',
    rows: [],
    status: 'loading',
    failure: null,
    selectedId: null,
    draftVersion: null,
    drafts: {},
    saved: {},
    edits: {},
    saving: null,
    results: {},
    store: null,
    runStore: null,
    verify: {
      runs: [],
      status: 'loading',
      failure: null,
      max: 0,
      accountModes: [],
      activeEnvironment: null,
      snapshots: {},
      addWhy: null,
      acting: null,
      pickedId: '',
      checked: [],
      showDetail: false,
      add: null,
      pending: null,
    },
    run: {
      checked: [],
      shownId: '',
      add: null,
      pending: null,
    },
  }
}

let state: StrategyState = initial()
const listeners = new Set<() => void>()

function announce(next: StrategyState): void {
  state = next
  for (const listener of listeners) listener()
}

/** 지금 상태. 그리는 도중에 부르므로 기다리지 않습니다. */
export function strategyState(): StrategyState {
  return state
}

export function subscribeStrategy(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** 화면이 상태를 읽는 자리. 바뀌면 다시 그립니다. */
export function useStrategyState(): StrategyState {
  return useSyncExternalStore(subscribeStrategy, strategyState, strategyState)
}

/* ── 서버와 주고받기 ────────────────────────────────── */

const ROUTE = '/api/strategy/versions'

/** 서버가 내는 목록. **줄과 설정이 따로 옵니다** — 설정을 아직 안 고친
 *  버전은 `drafts` 에 없습니다. */
interface StoredList {
  versions: StrategyVersion[]
  drafts: Record<string, SettingsDraft>
  /** 옛 지표 이름 → `{id, params}`. 서버 규칙 모듈의 옮김표입니다. */
  legacyOperands?: unknown
}

/** 저장소에 보내지 않는 칸들. **성과는 분석 자료가 답합니다** — 여기서 보내면
 *  저장소가 모르는 이름이라 400 으로 되돌아옵니다. 기록 유형별 성과
 *  (`performance`)도 같은 까닭으로 뺍니다. */
const PERFORMANCE = ['pl', 'winRate', 'trades', 'maxDrawdown', 'performance'] as const

function withoutPerformance(row: StrategyVersion): Record<string, unknown> {
  const out: Record<string, unknown> = { ...row }
  for (const field of PERFORMANCE) delete out[field]
  return out
}

/** 답의 알맹이. **막힌 답은 한 겹 안에 들어 있습니다**(`detail`) — 두 자리를
 *  다 보지 않으면 막혔을 때만 문제 목록이 사라집니다. */
function bodyOf(body: unknown): unknown {
  const inner = (body as { detail?: unknown })?.detail
  return inner && typeof inner === 'object' ? inner : body
}

/** 서버가 준 문제 목록을 읽습니다. 모양이 다르면 빈 목록입니다 — 못 읽은 것을
 *  지어내면 칸 옆에 없는 말이 섭니다. */
function problemsOf(body: unknown): SaveProblem[] {
  const list = (bodyOf(body) as { problems?: unknown })?.problems
  if (!Array.isArray(list)) return []
  return list.flatMap((one) => {
    const item = one as { field?: unknown; severity?: unknown; message?: unknown }
    if (typeof item?.message !== 'string') return []
    return [
      {
        field: typeof item.field === 'string' ? item.field : '',
        severity: item.severity === 'error' ? 'error' : 'warning',
        message: item.message,
      },
    ]
  })
}

function messageOf(body: unknown, fallback: string): string {
  /* **까닭이 글자 하나로 오는 답도 있습니다**(본문 불일치·저장소 오류·500·404).
     그때는 `detail` 이 곧 문장이라 그것을 씁니다 — 안 보면 화면이 「저장하지
     못했습니다」만 말하고 왜인지는 어디에도 안 섭니다. */
  const detail = (body as { detail?: unknown })?.detail
  if (typeof detail === 'string' && detail) return detail
  const said = (bodyOf(body) as { message?: unknown })?.message
  return typeof said === 'string' && said ? said : fallback
}

/** 저장해 둔 전략을 받아 옵니다. 화면이 열릴 때 한 번 부릅니다.
 *
 *  **못 받으면 빈 목록이 아니라 「못 받았다」입니다** — 빈 목록으로 두면
 *  사용자가 만들어 둔 전략이 사라진 것으로 읽힙니다. */
export async function loadStrategies(options?: { quiet?: boolean }): Promise<void> {
  /* **조용히 받는 길이 있습니다.** 저장 직후처럼 화면에 이미 목록이 서 있는
     자리에서 「받는 중」 얼굴을 다시 세우면, 방금 저장한 사람에게 표가 한 번
     비었다 돌아옵니다. */
  if (!options?.quiet) announce({ ...state, status: 'loading', failure: null })
  try {
    const answer = await fetch(ROUTE)
    if (!answer.ok) {
      announce({ ...state, status: 'failed', failure: `목록을 받지 못했습니다 (${answer.status})` })
      return
    }
    const body = (await answer.json()) as StoredList
    /* 매개변수가 생기기 전의 지표 이름을 옮기는 표. **설정을 읽기 전에** 받아 둡니다 —
       아래 `withNewFields` 가 이 표로 옛 조건을 옮깁니다. */
    setLegacyOperands(body?.legacyOperands)
    const stored = Array.isArray(body?.versions) ? body.versions : []
    /* 성과 넷은 저장소가 안 돌려줍니다 — 보낼 때도 빼고 분석 자료가 답할
       값입니다. **없음으로 채워 둡니다**: 칸이 아예 없으면 화면이 「값이
       없다」와 「칸이 없다」를 못 갈라 빈자리에 NaN 을 그립니다. */
    const rows = stored.map((row) => ({
      ...withMarketMeta(row),
      pl: row.pl ?? null,
      winRate: row.winRate ?? null,
      trades: row.trades ?? null,
      maxDrawdown: row.maxDrawdown ?? null,
    }))
    /* 뒤에 생긴 칸이 없는 옛 설정은 **여기서 한 번** 빈 칸으로 채웁니다
       (`withNewFields`). 고치는 초안도 이 값에서 출발하므로, 안 고친 버전은
       안 고친 것으로 남습니다. */
    const received: Record<string, SettingsDraft> =
      body?.drafts && typeof body.drafts === 'object' ? body.drafts : {}
    const saved = Object.fromEntries(
      Object.entries(received).map(([id, draft]) => [id, withNewFields(draft)]),
    )
    announce({
      ...state,
      rows,
      saved,
      /* 담아 둔 파일을 서버가 어떻게 읽었는지. **목록이 빈 까닭이 여기 있습니다.** */
      store: tookStore(body),
      /* 고치던 초안은 그대로 둡니다 — 다시 받아 왔다고 사용자가 치던 값을
         지우면, 목록을 새로 고친 순간 고치던 설정이 사라집니다. */
      status: 'ready',
      failure: null,
      selectedId: state.selectedId ?? rows[0]?.id ?? null,
    })
  } catch {
    announce({ ...state, status: 'failed', failure: '목록을 받지 못했습니다' })
  }
}

/** 한 버전의 신원과 설정을 저장합니다.
 *
 *  **답을 그대로 돌려줍니다** — 400 이면 오류가 있어 저장이 안 된 것이고,
 *  200 이면 저장된 것입니다(경고만 있을 수 있습니다). 화면은 이 답으로 칸 옆과
 *  저장 단추 위를 채웁니다. */
export async function saveVersion(id: string): Promise<SaveResult> {
  const held = versionOf(id)
  if (!held) return { ok: false, message: '저장할 전략을 찾지 못했습니다', problems: [] }
  const settings = draftOf(id)
  /* 목록에 넣는 줄도 요약을 다시 지은 것입니다(`saveBodyOf` 와 같은 문장). */
  const row = { ...held, summary: summaryFor(settings, held.currency) }
  announce({ ...state, saving: id })
  let result: SaveResult
  /* 서버가 담은 설정. 서버는 보낸 설정을 **정리해서** 담습니다(해외 전략의 체결조건을
     비우는 것처럼) — 보낸 사본을 저장값으로 두면 화면의 저장값이 서버와 갈립니다.
     답에 없으면 보낸 것입니다. */
  let stored: SettingsDraft = settings
  try {
    const answer = await fetch(`${ROUTE}/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(saveBodyOf(held, settings)),
    })
    const body = await answer.json().catch(() => null)
    const answered = (body as { drafts?: Record<string, unknown> } | null)?.drafts?.[id]
    if (answer.ok && answered && typeof answered === 'object') stored = withNewFields(answered as SettingsDraft)
    result = {
      ok: answer.ok,
      message: messageOf(body, answer.ok ? '저장했습니다' : '저장하지 못했습니다'),
      problems: problemsOf(body),
    }
  } catch {
    result = { ok: false, message: '저장하지 못했습니다 — 서버에 닿지 않습니다', problems: [] }
  }
  /* 저장이 통과한 새 버전은 그때 목록에 섭니다 — 서버가 받은 것만 목록입니다. */
  const arrived = result.ok && state.draftVersion?.id === id
  /* 통과했으면 겹쳐 둔 칸을 목록 줄에 넣고 걷습니다 — 서버가 받은 값이라
     이제 목록의 값입니다. 막혔으면 그대로 두어 고친 것을 잃지 않습니다. */
  const edits = { ...state.edits }
  if (result.ok) delete edits[id]
  /* 저장하는 사이 고친 것이 없으면 **고치는 초안도 서버가 담은 값으로** 둡니다 —
     저장값만 바꾸면 방금 저장한 버전이 「고친 것 있음」으로 남습니다. 그 사이
     고쳤으면 고친 것을 그대로 둡니다. */
  const untouched = JSON.stringify(state.drafts[id] ?? settings) === JSON.stringify(settings)
  const drafts = result.ok && untouched ? { ...state.drafts, [id]: stored } : state.drafts
  announce({
    ...state,
    saving: null,
    edits,
    drafts,
    /* 새 버전도 **다시 지은 줄**로 넣습니다 — 담아 두었던 초안을 그대로 밀면
       방금 지은 요약이 버려져, 새로 만든 전략만 목록과 상세가 옛말을 합니다. */
    rows: arrived
      ? [row, ...state.rows]
      : result.ok
        ? state.rows.map((item) => (item.id === id ? row : item))
        : state.rows,
    draftVersion: arrived ? null : state.draftVersion,
    results: { ...state.results, [id]: result },
    /* 저장된 때만 「마지막으로 저장한 값」이 바뀝니다 — 막힌 저장까지 반영하면
       되돌리기가 흐려지고 고친 것이 저장된 것으로 읽힙니다. */
    saved: result.ok ? { ...state.saved, [id]: stored } : state.saved,
  })
  /* **담긴 뒤에는 상태 파일 알림을 서버에게 다시 물어봅니다.** 서버는 제대로
     담은 그 순간 「못 읽었다」를 놓는데(`storage.wrote`), 저장 응답에는 그 값이
     없어 화면만 옛말을 들고 있게 됩니다. 알림이 서 있을 때만 묻습니다 — 아무
     말도 없는 평소에는 저장마다 조회가 하나씩 늘 까닭이 없습니다. */
  if (result.ok && storeNote('versions', state.store) !== null) {
    await loadStrategies({ quiet: true })
  }
  return result
}

/** 조건이 하나도 없는 버전의 요약. **말이 여기 하나입니다** — 목록이 새 버전에
 *  박아 두는 말과 저장이 다시 짓는 말이 갈리면, 조건을 지운 전략만 옛말로 섭니다. */
export const NO_CONDITIONS = '조건을 아직 안 넣었습니다'

/** 적어 둔 조건은 있는데 **이 설정으로는 주문이 안 나가는** 버전의 요약.
 *
 *  **까닭이 아니라 결과를 적습니다.** 까닭은 하나가 아닙니다 — 진입 규칙이 꺼져
 *  있을 수도, 켜져 있는데 조건이 덜 찼을 수도, 청산에만 적어 두었을 수도 있습니다.
 *  그 가운데 하나를 골라 적으면 나머지 경우에 화면이 거짓말을 합니다. 어느 경우든
 *  참인 말은 「주문이 안 나간다」 하나뿐이고, 무엇이 모자란지는 설정 화면이
 *  칸마다 말합니다. */
export const NO_ORDERS = '지금 설정으로는 주문을 내지 않습니다'

/** 담긴 설정으로 지은 한 줄 요약. 설정 화면의 문장 규칙 그대로입니다.
 *
 *  문장이 안 나오면 **적어 둔 조건이 어디든 있는지**로 갈립니다 — 네 규칙을 다
 *  봅니다. 청산에만 적어 두었어도 「아직 안 넣었다」는 거짓입니다. */
/** 저장 요청의 몸 — 버전 줄과 설정 한 벌. 저장과 「지난 봉으로 돌려 보기」가 **같은
 *  몸**을 보냅니다: 같은 설정을 두 자리가 다르게 실으면 저장한 것과 셈한 것이 갈립니다.
 *
 *  **요약 문장을 여기서 다시 짓습니다.** 버전을 만들 때 박아 둔 말(「조건을 아직
 *  안 넣었습니다」)은 그때의 사실이라, 조건을 넣고 저장해도 목록이 옛말을 합니다.
 *  설정 화면이 세우는 문장과 같은 자리에서 지어, 두 화면이 같은 말을 합니다. */
export function saveBodyOf(
  row: StrategyVersion,
  settings: SettingsDraft,
): { version: Record<string, unknown>; draft: SettingsDraft } {
  const version = withoutPerformance({ ...row, summary: summaryFor(settings, row.currency) })
  return { version, draft: settings }
}

function summaryFor(draft: SettingsDraft, currency?: string): string {
  const ctx = { baseBar: draft.baseBar, evalMode: draft.evalMode, currency }
  const line = summaryOf(draft.rules, ctx, RULE_KEYS)
  if (line) return line
  return anyConditions(draft.rules, ctx, RULE_KEYS) ? NO_ORDERS : NO_CONDITIONS
}

/** 버전 하나를 **설정까지** 베껴 새 줄로 저장합니다. 베끼는 설정은 원본의 저장된
 *  값입니다 — 줄만 새로 만들고 설정을 안 옮기면 사본이 빈 씨앗 설정으로 저장됩니다.
 *  사본 줄은 원본 바로 뒤에 서고 화면도 사본으로 옮겨 갑니다.
 *
 *  **저장이 막히면 사본 줄을 걷고 원본으로 돌아갑니다** — 서버에 없는 줄을 목록에
 *  남겨 두면 새로고침 한 번에 사라지는데, 그때까지는 저장된 것처럼 보입니다. */
export async function duplicateVersion(source: StrategyVersion, copy: StrategyVersion): Promise<SaveResult> {
  const carried = savedOf(source.id)
  const at = state.rows.findIndex((row) => row.id === source.id)
  announce({
    ...state,
    rows: [...state.rows.slice(0, at + 1), copy, ...state.rows.slice(at + 1)],
    drafts: { ...state.drafts, [copy.id]: carried },
    saved: { ...state.saved, [copy.id]: carried },
    selectedId: copy.id,
  })
  const result = await saveVersion(copy.id)
  if (!result.ok) {
    const drafts = { ...state.drafts }
    const saved = { ...state.saved }
    const results = { ...state.results }
    const edits = { ...state.edits }
    delete drafts[copy.id]
    delete saved[copy.id]
    delete results[copy.id]
    delete edits[copy.id]
    announce({
      ...state,
      rows: state.rows.filter((row) => row.id !== copy.id),
      drafts,
      saved,
      results,
      edits,
      selectedId: state.selectedId === copy.id ? source.id : state.selectedId,
    })
  }
  return result
}

/** 그 버전을 보관합니다. 보내는 것은 **서버에 있는 줄과 저장된 설정에 상태만
 *  「보관」으로 바꾼 것**입니다 — 고치는 중인 이름·월물·설정은 함께 저장하지 않고
 *  그대로 남깁니다. 목록 상태는 **서버가 받은 뒤에만** 「보관」이 됩니다 — 먼저
 *  바꿔 두면 막혔을 때 보관되지 않은 버전이 보관된 것처럼 섭니다. */
export async function archiveVersion(id: string): Promise<SaveResult> {
  const stored = storedOf(id)
  if (!stored) return { ok: false, message: '보관할 전략을 찾지 못했습니다', problems: [] }
  const settings = savedOf(id)
  const row: StrategyVersion = { ...stored, status: '보관' }
  announce({ ...state, saving: id })
  let result: SaveResult
  try {
    const answer = await fetch(`${ROUTE}/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(saveBodyOf(row, settings)),
    })
    const body = await answer.json().catch(() => null)
    result = {
      ok: answer.ok,
      message: messageOf(body, answer.ok ? '보관했습니다' : '보관하지 못했습니다'),
      problems: problemsOf(body),
    }
  } catch {
    result = { ok: false, message: '보관하지 못했습니다 — 서버에 닿지 않습니다', problems: [] }
  }
  announce({
    ...state,
    saving: null,
    rows: result.ok
      ? state.rows.map((item) => (item.id === id ? { ...item, status: '보관', summary: summaryFor(settings, item.currency) } : item))
      : state.rows,
  })
  if (result.ok && storeNote('versions', state.store) !== null) {
    await loadStrategies({ quiet: true })
  }
  return result
}

/** 「새 버전 저장」 — 고르고 있는 버전 뒤에 다음 버전 줄을 세우고 **고치던 값을 그
 *  줄이 들고 가** 저장합니다. 옛 버전의 설정은 저장값으로 돌아갑니다.
 *
 *  **저장이 막히면 모두 되돌립니다** — 새 줄을 걷고, 고치던 값을 옛 버전에 돌려놓고,
 *  화면도 옛 버전으로 돌아옵니다. 막힌 까닭은 옛 버전의 저장 글 자리에 섭니다. */
export async function saveNewVersion(source: StrategyVersion, row: StrategyVersion): Promise<SaveResult> {
  const carried = draftOf(source.id)
  const last = state.rows.map((item) => item.groupId).lastIndexOf(source.groupId)
  announce({
    ...state,
    rows: [...state.rows.slice(0, last + 1), row, ...state.rows.slice(last + 1)],
    drafts: { ...state.drafts, [source.id]: savedOf(source.id), [row.id]: carried },
    saved: { ...state.saved, [row.id]: carried },
    selectedId: row.id,
  })
  const result = await saveVersion(row.id)
  if (!result.ok) {
    const drafts = { ...state.drafts, [source.id]: carried }
    const saved = { ...state.saved }
    const results = {
      ...state.results,
      [source.id]: { ...result, head: failLine('새 버전을 저장하지 못했습니다', result.message), message: '' },
    }
    const edits = { ...state.edits }
    delete drafts[row.id]
    delete saved[row.id]
    delete results[row.id]
    delete edits[row.id]
    announce({
      ...state,
      rows: state.rows.filter((item) => item.id !== row.id),
      drafts,
      saved,
      results,
      edits,
      selectedId: state.selectedId === row.id ? source.id : state.selectedId,
    })
  }
  return result
}

/** 한 버전을 지웁니다. 지운 뒤 목록에서도 뺍니다. */
export async function deleteVersion(id: string): Promise<boolean> {
  try {
    const answer = await fetch(`${ROUTE}/${encodeURIComponent(id)}`, { method: 'DELETE' })
    if (!answer.ok) return false
  } catch {
    return false
  }
  const rows = state.rows.filter((item) => item.id !== id)
  const drafts = { ...state.drafts }
  const saved = { ...state.saved }
  const results = { ...state.results }
  delete drafts[id]
  delete saved[id]
  delete results[id]
  announce({
    ...state,
    rows,
    drafts,
    saved,
    results,
    selectedId: state.selectedId === id ? (rows[0]?.id ?? null) : state.selectedId,
  })
  return true
}

/* ── 검증 실행 ──────────────────────────────────────── */

const RUNS = '/api/strategy/runs'

/** 검증 실행 하나를 세우는 요청. 서버의 `AddRunRequest` 와 같은 칸입니다. */
export interface AddRunAsk {
  id: string
  versionId: string
  /** **담긴 설정**을 그대로 보냅니다 — 실행은 시작할 때의 설정으로 계속 돕니다.
   *  안 담긴 초안으로 시작하면 새로고침 뒤 실행과 버전의 설정이 갈립니다. */
  draft: SettingsDraft
  market: string
  code: string
  session: string
  qty: number
  cash: number
  feePerContract: number
  /** 어느 장부로 돌릴지. 계좌 갈래(`sim`·`real`)는 서버의 활성 환경이 그
   *  갈래의 환경일 때만 섭니다(모의 계좌는 모의, 실전 계좌는 실전). */
  mode: RunMode
  /** 화면이 믿는 활성 환경. 계좌 갈래에서는 **확인창을 열 때 고정한 값**을
   *  보냅니다 — 서버는 이것과 갈래의 환경, 제 활성 환경이 모두 같아야 세웁니다.
   *  종이 실행은 안 보냅니다. */
  environment?: Environment
  /** 확인창을 지났다는 표지. **`sim` 은 이것이 참이라야 한 건이라도 냅니다.**
   *  시각은 안 보냅니다 — 서버가 제 시계로 찍습니다(보낸 시각을 그대로 담으면
   *  승인한 적 없는 실행에 시각만 실어 보낼 수 있습니다). */
  approved: boolean
}

/** 서버가 낸 거절 까닭 한 줄.
 *
 *  **두 모양으로 옵니다.** 짚을 칸이 있는 거절은 저장할 때와 같은 덩이
 *  (`{message, problems}`)이고, 그 밖에는 글자 하나(`detail`)입니다. 한
 *  모양만 읽으면 다른 모양의 거절이 숫자만 남은 「요청이 막혔습니다 (400)」로
 *  떨어집니다 — 같은 패널에서 한도 초과는 말이 뜨고 검사 실패는 숫자만 뜨게
 *  됩니다. 저장 쪽과 **같은 읽기 함수**를 씁니다.
 *
 *  짚은 칸이 있으면 **그 문장이 먼저**입니다 — 머리말(「검증 실행을 시작하지
 *  못했습니다」)은 무엇이 막았는지 말하지 않습니다. 실행 라우트는 첫 까닭
 *  하나만 세웁니다(「화면에는 첫 까닭 하나만」 규칙). */
export async function whyOf(answer: Response): Promise<string> {
  const body = await answer.json().catch(() => null)
  const found = problemsOf(body)
  if (found.length > 0) return found[0].message
  return messageOf(body, `요청이 막혔습니다 (${answer.status})`)
}

function tookRuns(body: unknown): Partial<VerifyState> {
  const list = (body as { runs?: unknown })?.runs
  const max = (body as { max?: unknown })?.max
  const active = (body as { activeEnvironment?: unknown })?.activeEnvironment
  return {
    runs: Array.isArray(list) ? (list as VerifyRun[]) : [],
    ...(typeof max === 'number' ? { max } : {}),
    accountModes: accountModesOf((body as { accountModes?: unknown })?.accountModes),
    activeEnvironment: active === 'paper' || active === 'real' ? active : null,
    status: 'ready' as ListStatus,
    failure: null,
  }
}

/** 돌고 있는 실행을 받아 옵니다. **처음 열 때와 다시 붙을 때만** 부릅니다 —
 *  그 뒤로는 허브가 보내 주는 것으로 채웁니다. */
export async function loadRuns(): Promise<void> {
  patchVerify({ status: 'loading', failure: null })
  try {
    const answer = await fetch(RUNS)
    if (!answer.ok) {
      patchVerify({ status: 'failed', failure: `실행 목록을 받지 못했습니다 (${answer.status})` })
      return
    }
    const body = await answer.json()
    const took = tookRuns(body)
    const runs = took.runs ?? []
    /* 알림은 이 줄들의 시세 상태도 봅니다(끊김·이어짐). */
    noteRuns(runs, [], [], 'list')
    /* 실행 파일의 상태는 **이 조회에만** 실려 옵니다 — 허브 방송에는 없습니다. */
    announce({ ...state, runStore: tookStore(body) })
    patchVerify({
      ...took,
      /* 고른 줄이 없어졌으면 첫 종이 실행으로 옮깁니다 — 없는 줄을 가리킨 채로
         두면 아래 표가 무엇의 것인지 말하지 못합니다. 검증 탭은 종이 실행만
         보므로 계좌 실행은 고른 줄이 되지 않습니다(`verifyPickOf`). */
      pickedId: verifyPickOf(runs),
      /* 없어진 줄은 고른 것에서도 뺍니다 — 남겨 두면 확인창이 없는 실행을 셉니다.
         계좌 실행도 뺍니다 — 검증 탭의 일괄 대상이 아닙니다. */
      checked: state.verify.checked.filter((id) =>
        runs.some((one) => one.id === id && isPaperRun(one)),
      ),
    })
  } catch {
    patchVerify({ status: 'failed', failure: '실행 목록을 받지 못했습니다' })
  }
}

/** 그 실행의 한 벌. **그 실행의 칸이 있고 줄이 그 실행일 때만** 돌려줍니다 —
 *  없으면 `null` 이라 표는 비고, 남의 실행 값을 대신 그리지 않습니다. */
export function snapshotOf(verify: VerifyState, id: string | null | undefined): VerifySnapshot | null {
  if (!id) return null
  const held = verify.snapshots[id]
  return held && held.run.id === id ? held : null
}

/** 한 실행의 칸을 바꿉니다(`null` 이면 지웁니다). 다른 실행의 칸은 그대로입니다. */
function putSnapshot(id: string, next: VerifySnapshot | null): void {
  const snapshots = { ...state.verify.snapshots }
  if (next === null) delete snapshots[id]
  else snapshots[id] = next
  patchVerify({ snapshots })
}

/** 그 실행의 한 벌. 목록과 따로 받습니다 — 체결·이벤트는 그 실행에만 있습니다.
 *  받은 것은 **그 실행의 칸에만** 담습니다. */
export async function loadRunSnapshot(id: string): Promise<void> {
  if (!id) return
  try {
    const answer = await fetch(`${RUNS}/${encodeURIComponent(id)}`)
    if (!answer.ok) {
      putSnapshot(id, null)
      return
    }
    const came = (await answer.json()) as VerifySnapshot
    /* 다른 실행의 답이면 담지 않습니다 — 그 칸에 남의 줄이 서게 됩니다. */
    if (came?.run?.id !== id) return
    /* 받아 온 것으로 **덮지 않고 이어 붙입니다.** 줄·잔고 곡선·거래는 지금
       상태를 통째로 말하는 값이라 새것이 맞지만, 체결·이벤트는 쌓이는
       값이라 들고 있던 것이 이 답보다 앞설 수 있습니다 — 조회가 나가 있는
       동안 방송이 실어 온 줄이 그렇습니다. 덮으면 화면에 이미 섰던 체결이
       도로 사라지고, 그 줄은 **방송이 다시 실어 줄 때만** 돌아옵니다(최근
       스무 줄 밖으로 밀렸으면 영영 안 돌아옵니다). */
    const mine = snapshotOf(state.verify, id)
    putSnapshot(id, {
      ...came,
      fills: merged(mine?.fills ?? [], came.fills, fillKey, (one) => one.time),
      events: merged(mine?.events ?? [], came.events, eventKey, (one) => one.time),
      /* **열린 주문은 덮어씁니다.** 쌓이는 값이 아니라 그 순간 열려 있는 것
         전부라, 이어 붙이면 이미 채워진 주문이 표에서 안 사라집니다. */
      openOrders: came.openOrders ?? [],
    })
  } catch {
    putSnapshot(id, null)
  }
}

/** 들고 있는 칸 전부와 검증 탭이 고른 실행을 다시 받습니다. 동작 하나가 다른
 *  실행의 상태까지 바꿀 수 있어, 한 탭의 것만 받으면 다른 탭의 표가 옛 값으로
 *  남습니다. 칸은 이번에 열어 본 실행마다 하나라, 많아야 실행 한도만큼입니다. */
async function reloadSnapshots(only?: (run: VerifyRun) => boolean): Promise<void> {
  const ids = new Set(Object.keys(state.verify.snapshots))
  if (state.verify.pickedId) ids.add(state.verify.pickedId)
  /* 가릴 때는 **목록에서 다른 시장으로 확인된 실행만** 뺍니다. 목록에 없는 칸은
     어느 시장인지 모르므로 전처럼 다시 받습니다. */
  const picked = only
    ? [...ids].filter((id) => {
        const run = state.verify.runs.find((one) => one.id === id)
        return run === undefined || only(run)
      })
    : [...ids]
  await Promise.all(picked.map((id) => loadRunSnapshot(id)))
}

/** 검증 실행 하나를 세웁니다. **막히면 까닭을 그대로 돌려줍니다** — 서버가
 *  시작 검사를 하고, 화면은 그 문장을 패널에 세웁니다. */
export async function addRun(ask: AddRunAsk): Promise<boolean> {
  patchVerify({ addWhy: null })
  try {
    const answer = await fetch(RUNS, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(ask),
    })
    if (!answer.ok) {
      patchVerify({ addWhy: await whyOf(answer) })
      return false
    }
    await loadRuns()
    patchVerify({ pickedId: ask.id, addWhy: null })
    await loadRunSnapshot(ask.id)
    return true
  } catch {
    patchVerify({ addWhy: '실행을 세우지 못했습니다 — 서버에 닿지 않습니다' })
    return false
  }
}

/** 계좌와 맞춰 본 결과의 수. 맞춰 본 실행 수와 그 가운데 어긋난 실행 수입니다. */
export type ReconcileCount = { checked: number; mismatched: number }

/* 목록·사전·수 가운데 하나로 온 칸의 크기. 셀 수 없는 값이면 `null` 입니다. */
function sizeOf(value: unknown): number | null {
  if (Array.isArray(value)) return value.length
  if (typeof value === 'number' && Number.isInteger(value) && value >= 0) return value
  if (value !== null && typeof value === 'object') return Object.keys(value).length
  return null
}

/** 계좌와 다시 맞춰 보라고 청합니다. **화면이 값을 고치는 것이 아니라**
 *  서버가 계좌를 다시 읽어 제 장부와 견주는 일입니다 — 답으로 줄이 바뀌면
 *  방송이 실어 옵니다.
 *
 *  못 보냈으면 까닭 한 줄(부르는 쪽이 같은 자리에 세웁니다), 맞춰 봤으면
 *  그 수입니다. 답에 수가 없으면 `null` 입니다 — 맞춰 본 것은 같고, 몇 개를
 *  봤는지만 모릅니다. */
export async function reconcileRuns(): Promise<string | ReconcileCount | null> {
  let count: ReconcileCount | null = null
  try {
    const answer = await fetch('/api/strategy/reconcile', { method: 'POST' })
    if (!answer.ok) return await whyOf(answer)
    const body = (await answer.json().catch(() => null)) as {
      checked?: unknown
      mismatched?: unknown
    } | null
    /* 서버는 맞춰 본 실행을 id 목록으로, 어긋난 실행을 id 별 까닭으로 줍니다.
       맞춰 본 칸이 없으면 수를 모르는 것으로 둡니다. */
    const checked = sizeOf(body?.checked)
    if (checked !== null) count = { checked, mismatched: sizeOf(body?.mismatched) ?? 0 }
  } catch {
    return '대사를 청하지 못했습니다 — 서버에 닿지 않습니다'
  }
  await loadRuns()
  return count
}

/** 실행 하나에 거는 동작. **답이 오면 목록을 다시 받습니다** — 한 동작이
 *  다른 실행의 상태까지 바꿀 수 있어, 바뀐 줄만 갈아 끼우면 화면이 옛 상태를
 *  들고 있게 됩니다. */
export async function actOnRun(
  id: string,
  action: 'stop' | 'resume' | 'close' | 'end' | 'acknowledge',
): Promise<string | null> {
  patchVerify({ acting: id })
  try {
    const answer = await fetch(`${RUNS}/${encodeURIComponent(id)}/${action}`, { method: 'POST' })
    if (!answer.ok) {
      const why = await whyOf(answer)
      patchVerify({ acting: null })
      return why
    }
  } catch {
    patchVerify({ acting: null })
    return '요청을 보내지 못했습니다 — 서버에 닿지 않습니다'
  }
  await loadRuns()
  await reloadSnapshots()
  patchVerify({ acting: null })
  return null
}

/** 끝난 실행을 목록에서 지웁니다. 기록 파일은 그대로 남습니다. */
export async function deleteRun(id: string): Promise<string | null> {
  patchVerify({ acting: id })
  try {
    const answer = await fetch(`${RUNS}/${encodeURIComponent(id)}`, { method: 'DELETE' })
    if (!answer.ok) {
      const why = await whyOf(answer)
      patchVerify({ acting: null })
      return why
    }
  } catch {
    patchVerify({ acting: null })
    return '요청을 보내지 못했습니다 — 서버에 닿지 않습니다'
  }
  await loadRuns()
  await reloadSnapshots()
  patchVerify({ acting: null })
  return null
}

/** 전체 신규 진입 중지. 답의 `paused` 가 실제로 멈춘 수입니다. */
/** 검증 탭이 고른 실행. 지금 고른 것이 아직 있고 종이 실행이면 그대로, 아니면
 *  첫 종이 실행입니다 — 검증 탭이 보는 실행(과 그 한 벌)이 계좌 실행이 되는 길을
 *  여기 한 자리에서 막습니다. 종이 실행이 없으면 빈 글자입니다. */
function verifyPickOf(runs: readonly VerifyRun[]): string {
  const kept = runs.find((one) => one.id === state.verify.pickedId)
  if (kept && isPaperRun(kept)) return kept.id
  return runs.find(isPaperRun)?.id ?? ''
}

/** 전체 신규 진입 중지. `modes` 를 주면 그 갈래의 실행만 멈춥니다(검증 탭은
 *  `['paper']`). 서버는 답에 적용한 갈래(`modes`)와 이번에 멈춘 실행(`pausedIds`)을
 *  돌려줍니다. 적용한 갈래가 없거나 청하지 않은 갈래가 섞였으면 갈래를 가리지 않은
 *  것입니다. 그때 멈춘 실행 가운데 계좌 실행이 있으면 그 수를 확정해 말하고,
 *  멈춘 실행을 모르면 「멈췄을 수 있다」로 말합니다 — 둘 다 **경고**(`warn`)로
 *  돌려줍니다. 막혀서 못 한 것은 서버 문장 그대로의 글자입니다. */
export async function stopAllRuns(
  modes?: string[],
): Promise<{ paused: number } | { warn: string } | string> {
  try {
    const answer = await fetch(
      '/api/strategy/stop-all',
      modes === undefined
        ? { method: 'POST' }
        : {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ modes }),
          },
    )
    if (!answer.ok) return await whyOf(answer)
    const body = (await answer.json()) as { paused?: number; modes?: unknown; pausedIds?: unknown }
    await loadRuns()
    await reloadSnapshots()
    const applied = body?.modes
    if (
      modes !== undefined &&
      (!Array.isArray(applied) || applied.some((one) => !modes.includes(String(one))))
    ) {
      const ids = body?.pausedIds
      if (!Array.isArray(ids)) {
        return { warn: '서버가 갈래를 가리지 않아 계좌 실행도 멈췄을 수 있습니다 — 진행 탭에서 확인하세요' }
      }
      const accounts = state.verify.runs.filter(
        (run) => ids.includes(run.id) && isAccountMode(run.mode),
      ).length
      if (accounts > 0) return { warn: `계좌 실행 ${accounts}개도 멈췄습니다 — 진행 탭에서 확인하세요` }
    }
    return { paused: typeof body?.paused === 'number' ? body.paused : 0 }
  } catch {
    return '요청을 보내지 못했습니다 — 서버에 닿지 않습니다'
  }
}

/* ── 허브 방송 ──────────────────────────────────────── */

/** 이미 들고 있는 것에 새로 온 것을 이어 붙입니다. **방송은 델타가 아니라
 *  실행마다 최근 스무 줄**이라 겹치는 것이 늘 옵니다 — 열쇠로 가려 한 번만
 *  남기고, 난 차례대로 세웁니다. */
function merged<T>(had: T[], came: T[], keyOf: (one: T) => string, timeOf: (one: T) => number): T[] {
  const seen = new Map<string, T>()
  for (const one of had) seen.set(keyOf(one), one)
  for (const one of came) seen.set(keyOf(one), one)
  return [...seen.values()].sort((a, b) => timeOf(a) - timeOf(b))
}

/** 허브가 보낸 실행 한 묶음.
 *
 *  **줄은 통째로 갈아 끼우고 체결·이벤트는 이어 붙입니다** — 줄은 지금 상태를
 *  통째로 말하는 값이고, 체결·이벤트는 쌓이는 값입니다. 칸마다 **그 실행의
 *  것만** 담습니다: 아래 표와 차트 표지가 제가 보는 실행의 것만 봅니다.
 *
 *  갈아 끼우는 칸은 들고 있는 칸들입니다. 검증 탭이 고른 실행은 칸이 없어도 새로
 *  세웁니다. 다른 실행의 칸은 탭이 그 실행을 열 때 따로 받습니다. */
export function applyStrategyBroadcast(
  runs: VerifyRun[],
  fills: VerifyFill[],
  events: VerifyEvent[],
  openOrders: VerifyOrder[],
): void {
  /* 알림의 원천 — 모든 실행의 최근 체결·이벤트가 오는 길은 이 방송뿐입니다. */
  noteRuns(runs, fills, events, 'broadcast')
  const pickedId = verifyPickOf(runs)
  const ids = new Set(Object.keys(state.verify.snapshots))
  if (pickedId) ids.add(pickedId)
  const snapshots: Record<string, VerifySnapshot> = {}
  for (const id of ids) {
    const run = runs.find((one) => one.id === id)
    /* 방송에 없는 실행은 없어진 것입니다. 담아 둔 체결·이벤트도 함께 버립니다. */
    if (!run) continue
    const had = snapshotOf(state.verify, id)
    snapshots[id] = {
      /* 줄은 방송의 것이 최신입니다. 다만 한 벌에만 있는 칸(`warmup`)은
         방송이 안 실어 주므로, 들고 있던 값을 밑에 깔고 덮습니다. */
      run: had ? { ...had.run, ...run } : run,
      fills: merged(had?.fills ?? [], fills.filter((one) => one.runId === id), fillKey, (one) => one.time),
      events: merged(had?.events ?? [], events.filter((one) => one.runId === id), eventKey, (one) => one.time),
      curve: had?.curve ?? [],
      trades: had?.trades ?? [],
      /* **덮어씁니다.** 방송에 이 실행의 줄이 하나도 없으면 열린 주문이
         없다는 뜻이라 비웁니다 — 들고 있던 것을 남기면 이미 채워진
         주문이 표에 남습니다. */
      openOrders: openOrders.filter((one) => one.runId === id),
      /* 조건 표는 방송에 없습니다 — 들고 있던 것을 그대로 둡니다. 새 봉의
         표는 화면이 그 봉을 볼 때 따로 받습니다(`refreshConditions`). */
      conditions: had?.conditions ?? null,
    }
  }
  patchVerify({ runs, status: 'ready', failure: null, pickedId, snapshots })
}

/** 그 실행의 **조건 표만** 새로 받습니다. 방송이 표를 안 실어 주므로 화면이
 *  판정 봉이 바뀐 것을 보고 부릅니다. 체결·이벤트는 방송이 이어 붙이고 있으니
 *  손대지 않고 `conditions` 하나만 덮어씁니다. 답이 왔을 때 그 실행의 칸이
 *  없어졌으면 버립니다. */
export async function refreshConditions(id: string): Promise<void> {
  if (!id) return
  try {
    const answer = await fetch(`${RUNS}/${encodeURIComponent(id)}`)
    if (!answer.ok) return
    const came = (await answer.json()) as Partial<VerifySnapshot>
    const had = snapshotOf(state.verify, id)
    if (!had) return
    putSnapshot(id, { ...had, conditions: came.conditions ?? null })
  } catch {
    /* 못 받으면 앞 표가 그대로 섭니다 — 머리의 봉 시각이 어느 봉의 표인지 말합니다. */
  }
}

/** 끊겼다 붙은 뒤 메우기. **끊긴 동안의 체결은 방송이 다시 보내 주지
 *  않습니다** — 최근 스무 줄 밖으로 밀려난 것은 조회로만 받습니다.
 *
 *  아직 한 번도 안 받아 본 화면에서는 아무것도 안 합니다 — 열 때 받습니다.
 *
 *  **다시 붙은 시장의 실행만** 메웁니다. 다른 시장의 실행은 끊긴 적이 없습니다. */
export async function refillRuns(markets: readonly RunMarket[]): Promise<void> {
  /* 끊긴 동안 쌓인 체결·이벤트는 다음 방송에 한꺼번에 옵니다 — 알림이 묶어 말합니다. */
  noteRefill(markets)
  if (state.verify.status === 'loading') return
  /* 그 시장에 실행이 없으면 부르지 않습니다. 목록을 못 받은 때는 무엇이 도는지
     모르므로 부릅니다. */
  const touched = (run: VerifyRun) => markets.includes(runMarketOf(run))
  if (state.verify.status === 'ready' && !state.verify.runs.some(touched)) return
  await loadRuns()
  await reloadSnapshots(touched)
}

/* ── 바꾸기 ─────────────────────────────────────────── */

export function patchStrategy(patch: Partial<StrategyState>): void {
  announce({ ...state, ...patch })
}

export function patchVerify(patch: Partial<VerifyState>): void {
  announce({ ...state, verify: { ...state.verify, ...patch } })
}

export function patchRun(patch: Partial<RunState>): void {
  announce({ ...state, run: { ...state.run, ...patch } })
}

export function setTab(tab: StrategyTab): void {
  patchStrategy({ tab })
}

/** 실행을 그 실행이 도는 탭에서 엽니다 — 검증(앱 시뮬레이션) 실행은 검증 탭,
 *  계좌 실행은 진행 탭입니다. 알림의 「보기」·「이벤트 보기」가 부릅니다.
 *
 *  실행이 하나면 그 실행을 고르고, 여럿이면 **전부 검증 실행일 때 검증 탭, 그 밖은
 *  진행 탭**만 엽니다(어느 것을 고를지 정할 수 없습니다). **체크는 하지 않습니다** —
 *  일괄 조작의 대상은 사용자가 체크한 것뿐입니다. 열 실행이 하나도 없으면 아무것도
 *  안 하고 `false` 입니다. */
export function openRunTab(runIds: readonly string[]): boolean {
  const found = state.verify.runs.filter((one) => runIds.includes(one.id))
  if (found.length === 0) return false
  if (found.length > 1) {
    patchStrategy({ tab: found.every(isPaperRun) ? '전략 검증' : '전략 진행' })
    return true
  }
  const run = found[0]
  if (isPaperRun(run)) {
    patchStrategy({ tab: '전략 검증' })
    patchVerify({ pickedId: run.id })
  } else {
    patchStrategy({ tab: '전략 진행' })
    patchRun({ shownId: run.id })
  }
  return true
}

export function setRows(rows: StrategyVersion[]): void {
  patchStrategy({ rows })
}

export function selectStrategy(id: string | null): void {
  patchStrategy({ selectedId: id })
}

/** 「새 전략」이 부르는 자리. **목록이 아니라 설정 탭에 세웁니다** — 저장이
 *  통과해야 목록에 서므로, 만든 직후에 보여야 하는 것은 채울 칸입니다. */
export function startDraftVersion(row: StrategyVersion): void {
  patchStrategy({ draftVersion: row, selectedId: row.id, tab: '전략 설정' })
}

/** 목록에 선 버전과 아직 안 선 새 버전을 **함께** 찾습니다. 저장·설정은 둘을
 *  가리지 않습니다 — 가리면 새 버전에서 저장이 안 눌립니다. */
/** 서버가 알고 있는 줄. 고치는 중인 칸은 안 겹칩니다. */
function storedOf(id: string): StrategyVersion | null {
  return (
    state.rows.find((item) => item.id === id) ??
    (state.draftVersion?.id === id ? state.draftVersion : null)
  )
}

/** 화면이 보는 줄 — **고치는 중인 칸을 겹쳐** 냅니다. 저장도 이것을 보냅니다.
 *  고친 이름으로 저장 단추를 눌렀는데 옛 이름이 나가면 안 됩니다. */
export function versionOf(id: string): StrategyVersion | null {
  const row = storedOf(id)
  if (!row) return null
  const edit = state.edits[id]
  return edit ? { ...row, ...edit } : row
}

/** 줄의 칸 하나를 고칩니다 — 이름·종목처럼 **설정이 아니라 줄에 있는** 값.
 *  저장을 눌러야 서버로 갑니다(설정 초안과 같은 규칙). */
export function setVersionEdit(id: string, patch: Partial<StrategyVersion>): void {
  /* 값을 고치면 지난 저장 답은 더는 이 값의 것이 아닙니다 — 남겨 두면 고친
     뒤에도 옛 오류가 칸 옆에 서 있습니다(`setDraft` 와 같은 규칙). */
  const results = { ...state.results }
  delete results[id]
  patchStrategy({ edits: { ...state.edits, [id]: { ...state.edits[id], ...patch } }, results })
}

export function setDraft(id: string, draft: SettingsDraft): void {
  /* 값을 고치면 지난 저장 답은 더는 이 값의 것이 아닙니다 — 남겨 두면 고친
     뒤에도 옛 오류가 칸 옆에 서 있습니다. */
  const results = { ...state.results }
  delete results[id]
  patchStrategy({ drafts: { ...state.drafts, [id]: draft }, results })
}

export function markSaved(id: string, draft: SettingsDraft): void {
  patchStrategy({ saved: { ...state.saved, [id]: draft } })
}

/* ── 읽기 도우미 ────────────────────────────────────── */

/** 아직 손대지 않은 버전이 여는 설정. **그 버전의 행에서 냅니다** — 하나로
 *  두면 새로 만든 전략이 남의 조건과 남의 예산을 단 채로 열립니다. */
function seedFor(id: string): SettingsDraft {
  const row = versionOf(id)
  return row ? seedDraft(draftSeedOf(row)) : seedDraft()
}

export function draftOf(id: string): SettingsDraft {
  return state.drafts[id] ?? savedOf(id)
}

export function savedOf(id: string): SettingsDraft {
  return state.saved[id] ?? seedFor(id)
}

/** 이 버전에 저장 안 한 변경이 있는지. **설정과 줄을 둘 다** 봅니다 — 이름만
 *  고치고 저장 단추가 안 살아나면 고친 것이 사라지는 길이 생깁니다. */
export function dirtyOf(id: string): boolean {
  if (JSON.stringify(draftOf(id)) !== JSON.stringify(savedOf(id))) return true
  return JSON.stringify(versionOf(id)) !== JSON.stringify(storedOf(id))
}

/** **어느 버전에든** 저장 안 한 변경이 있는지.
 *
 *  상단 페이지를 떠날 때 붙잡을지 여기서 정합니다 — 지금 보고 있는 버전만
 *  보면, 다른 버전에서 고치다 목록으로 옮겨 둔 변경이 말없이 사라집니다. */
export function hasUnsaved(): boolean {
  const ids = new Set([...Object.keys(state.drafts), ...Object.keys(state.edits)])
  return [...ids].some((id) => dirtyOf(id))
}

/** 저장 안 한 설정 초안을 **마지막으로 저장한 값으로** 되돌립니다.
 *  「버리고 이동」이 부르는 자리입니다 — 하위 탭과 상단 페이지가 같은 창을
 *  쓰므로 되돌리는 길도 하나여야 합니다.
 *
 *  초안을 비우지 않고 저장값을 덮는 이유: 비우면 화면은 저장한 값이 아니라
 *  새 전략의 기본값으로 섭니다. 「고친 것이 사라집니다」라고 물어 놓고
 *  저장해 둔 것까지 지우는 셈입니다.
 *
 *  되돌리는 것은 **설정 초안뿐**입니다 — 검증·진행 실행은 그대로 둡니다. */
export function revertDrafts(): void {
  const drafts: Record<string, SettingsDraft> = {}
  for (const id of Object.keys(state.drafts)) drafts[id] = storedSettingsOf(id)
  for (const id of new Set([...Object.keys(state.drafts), ...Object.keys(state.edits)])) bumpRevert(id)
  /* 줄의 칸은 **비웁니다.** 설정 초안과 달리 되돌릴 자리가 목록에 그대로
     있어(서버가 준 줄), 겹쳐 둔 것만 걷으면 저장된 값이 섭니다. */
  patchStrategy({ drafts, edits: {} })
}

/** 한 버전의 저장 안 한 변경을 **모두** 마지막으로 저장한 값으로 되돌립니다 —
 *  설정 초안과 줄의 칸(이름·품목·월물·통화 등)을 한 번에. 설정의 「되돌리기」
 *  단추가 부르는 자리입니다. 설정만 되돌리면 고친 이름·품목이 남아 「고친 것
 *  있음」이 꺼지지 않습니다. 다른 버전의 변경은 그대로 둡니다.
 *
 *  아직 목록에 없는 새 버전은 **설정 초안만** 되돌립니다 — 그 버전의 줄은
 *  저장된 적이 없어, 걷으면 이름과 품목이 돌아갈 자리가 없습니다. */
export function revertVersion(id: string): void {
  const results = { ...state.results }
  delete results[id]
  if (state.draftVersion?.id === id) {
    patchStrategy({ drafts: { ...state.drafts, [id]: savedOf(id) }, results })
    return
  }
  const edits = { ...state.edits }
  delete edits[id]
  bumpRevert(id)
  patchStrategy({ drafts: { ...state.drafts, [id]: storedSettingsOf(id) }, edits, results })
}

/** 저장된 설정 — 줄의 고친 칸을 **겹치지 않고** 냅니다. 저장한 설정이 없는
 *  버전은 줄에서 처음 값을 만드는데, 고친 시장·품목으로 만들면 되돌린 뒤에도
 *  고친 품목의 설정이 섭니다. */
function storedSettingsOf(id: string): SettingsDraft {
  const saved = state.saved[id]
  if (saved) return saved
  const row = storedOf(id)
  return row ? seedDraft(draftSeedOf(row)) : seedDraft()
}

/* 버전마다 되돌린 횟수. 품목을 바꾸면 해외 품목정보를 물어 그 답으로 통화를
   채우는데, 답이 오기 전에 되돌렸으면 그 답은 버린 변경의 것입니다 — 묻기 전
   횟수와 답이 온 때 횟수가 다르면 쓰지 않습니다. 화면에 그리는 값이 아니라
   상태에 두지 않습니다. */
const reverts: Record<string, number> = {}

function bumpRevert(id: string): void {
  reverts[id] = (reverts[id] ?? 0) + 1
}

/** 이 버전을 지금까지 되돌린 횟수 — 늦게 온 답이 되돌리기 전의 것인지 가릅니다. */
export function revertCountOf(id: string): number {
  return reverts[id] ?? 0
}

/** 「검증 추가」·「거래 추가」를 그냥 눌렀을 때 패널을 채울 전략.
 *  **목록에서 고른 것**으로 채웁니다 — 늘 첫 줄로 채우면 사용자가 골라 둔
 *  전략을 두고 엉뚱한 전략이 선 채로 패널이 열립니다. */
export function seedFromSelection(): OpenRequest {
  const row = state.rows.find((item) => item.id === state.selectedId) ?? state.rows[0]
  return { strategy: row?.name ?? '', version: row?.version ?? '' }
}
