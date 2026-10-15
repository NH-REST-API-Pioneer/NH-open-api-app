import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { contractsOf, resolve, spreadShortName } from '../../data/instruments'
import {
  codeOfVersion,
  currencyOf,
  productOfVersion,
  useStrategyCurrency,
  type StrategyVersion,
} from '../../data/strategyList'
import { sessionKeyOf, sessionLabelOf, sessionLinesFor, type Aux } from '../../data/strategyRules'
import { watchLine } from '../../data/ruleSummary'
import {
  patchVerify,
  actOnRun,
  addRun,
  loadRunSnapshot,
  loadRuns,
  patchRun,
  reconcileRuns,
  savedOf,
  seedFromSelection,
  snapshotOf,
  stopAllRuns,
  storeNote,
  useStrategyState,
  type OpenRequest,
  type ReconcileCount,
} from '../../data/strategyStore'
import {
  FEE_ASSUMED,
  FUNDS_UNKNOWN,
  perOrderNote,
  perOrderOf,
  NO_CASH_DEFAULT,
  cashDefaultOf,
  runCurrencyOf,
  optionSellWarning,
  CONFIRM_TEXT,
  accountModeOf,
  fillKey,
  isAccountMode,
  isRejectedEvent,
  isTickRun,
  attentionEndWhy,
  reasonWord,
  tickBarOf,
  sendEach,
  streakText,
  type AccountMode,
  type VerifyFill,
  type VerifyOrder,
  type VerifyRun,
} from '../../data/strategyRuns'
import { kstClockSeconds } from '../../lib/kst'
import { TickBadge } from './TickBadge'
import {
  Num,
  NumOrDash,
  currencyCode,
  currencyDigits,
  limitTyped,
  moneyDigits,
  moneyIn,
  moneyText,
  toneOf,
} from '../../lib/number'
import { Modal } from '../../app/Modal'
import { limitValue, limitWhy, runAddWhy } from '../../data/strategyChecks'
import { loadLimits, saveLimits, useLimits, type LimitAxis, type Limits } from '../../data/strategyLimits'
import { overseasCurrencies, useTimetable } from '../../data/session'
import { useEnvironment, type Environment } from '../../data/environment'
import { EnvSplitNote, RUN_KIND_LABEL, RunKindBadge, envSplit } from './runKind'
import { PICK_HINT, RunStats, runNameOf, targetLine, targetsOf } from './runStats'

/* 전략 진행 — 연결 계좌로 거래하는 화면.
 *
 * 검증과 공간 구조는 같지만 다루는 것이 다릅니다. 여기 나가는 것은 실제
 * 주문이고, 그래서 되돌릴 수 없는 동작마다 확인 창이 섭니다.
 *
 * **여기서 세우는 실행은 계좌로 실제 주문을 냅니다** — 접속 환경이 모의면 모의
 * 계좌(`mode: 'sim'`), 실전이면 실전 계좌(`mode: 'real'`)입니다. 그래서 시작 전에
 * 확인창을 한 번 지나고, 그 창을 지난 표지(`approvedAt`)가 없으면 서버가 한 건도
 * 내지 않습니다.
 *
 * 종이 장부로 도는 실행은 검증 화면이 봅니다. **목록은 한 벌**이고(서버가 한
 * 목록을 냅니다) 화면이 갈래로 가릅니다 — 둘로 들면 한도 일곱이 어느 쪽
 * 것인지 말할 수 없습니다.
 *
 * **차트는 두지 않습니다.** 같은 종목을 검증 화면이 이미 그리고, 이 화면이
 * 답할 것은 「지금 계좌에서 무슨 일이 일어났나」라 표가 먼저입니다.
 */

/** 확인 얼굴이 고정한 것 — 어느 계좌 갈래로, 어느 환경을 믿고 세우는지.
 *  **「거래 시작」을 누를 때 한 번 정하고** 확인창과 보내는 요청이 이 값 하나를
 *  씁니다. 승인할 때 다시 셈하면 창에 보인 갈래와 나가는 갈래가 갈릴 수
 *  있습니다. 환경 세대(`generation`)는 창이 떠 있는 동안 환경이 바뀌었는지
 *  보려고 함께 적습니다. */
interface AskFixed {
  mode: AccountMode
  environment: Environment
  generation: number
}

/** 확인 얼굴의 글자. 갈래마다 한 벌이고, 모의 계좌 쪽은 지금까지의 글자
 *  그대로입니다. */
const ASK_TEXT: Record<AccountMode, { title: string; approve: string; button: string }> = {
  sim: { title: '모의 계좌 거래 시작', approve: '모의 계좌로 실제 주문이 나갑니다.', button: '승인하고 시작' },
  real: { title: '실전 계좌 거래 시작', approve: '실전 계좌로 실제 주문이 나갑니다.', button: '실전 계좌로 승인하고 시작' },
}

/** 접속 환경을 아직 확인하지 못했을 때 거래 추가 폼에 서는 한 줄. */
const ENV_WAIT = '접속 환경을 확인하는 중입니다 — 잠시 뒤 다시 누르세요'

/** 서버가 준 시각(ms)을 표에 적는 말(한국시각). **받은 값 그대로**입니다 — 한 봉 안에서
 *  여러 번 체결되므로 초까지 적습니다(검증 화면과 같은 꼴). */
function clockOf(time: number): string {
  if (!time) return '—'
  return kstClockSeconds(time)
}

/** 줄에 세우는 종목 이름. **검증 화면과 같은 규칙**입니다 — 스프레드는 두
 *  만기를 다 적으면 좁은 열에서 잘리므로 짧은 꼴로 적고, 그 밖에는 색인이
 *  지어 준 이름을 그대로 씁니다. 색인에 없으면 코드입니다. */
function shortInstrument(code: string): string {
  const held = resolve(code)
  if (!held?.contract) return code
  return held.contract.kind === 'spread' && held.contract.legs
    ? spreadShortName(held.product.name, held.contract.legs)
    : held.name
}

/** 아래 표가 주문번호 열까지 세울 수 있는 가장 좁은 폭(px).
 *
 *  **이유는 읽는 값이고 주문번호는 찾을 때 쓰는 열쇠**라, 표가 좁아 용도 칸이
 *  가장 긴 까닭 문구보다 좁아지면 주문번호 열을 접고 번호는 그 줄 시각 칸에
 *  마우스를 올렸을 때 보입니다. 값은 고정 열 여섯의 폭(`strategy.css` 의
 *  `run-col-*`: 84 + 82 + 66 + 86 + 110 + 80 = 508)에 가장 긴 까닭 「청산 · 사용자
 *  청산」(121)과 칸 좌우 여백(16)을 더한 것입니다. 열 폭을 바꾸면 이 수도 함께
 *  바꿉니다. */
const ORDER_NO_FITS = 645
/** 틱으로 평가하는 실행을 볼 때의 값. 시각 칸이 「틱」 표지 자리만큼 넓어집니다
 *  (84 → 112, `run-col-time.is-tick`). */
const ORDER_NO_FITS_TICK = 673

const BOTTOM_TABS = ['최근 체결', '미체결', '이벤트'] as const
type BottomTab = (typeof BOTTOM_TABS)[number]

/** 아래 표의 한 줄. **체결과 미체결이 한 꼴로 섭니다** — 줄에 어떤 칸이 있나로
 *  가리면, 서버가 체결 줄에 그 칸을 싣기 시작하는 날 표가 조용히 다른 말을
 *  합니다. 무엇을 적을지는 탭이 정해 두고 그리는 자리는 한 곳입니다. */
interface TableRow {
  key: string
  time: number
  /** 계좌 주문번호. 모르면 `null` 이고 「—」로 섭니다 — 가상 장부의 줄에는 계좌가
   *  없어 번호도 없습니다. */
  orderNo: string | null
  side: 'buy' | 'sell'
  intent: 'entry' | 'exit'
  reason: string
  /** 상태 칸에 적을 말. */
  state: string
  price: number | null
  /** 체결은 채워진 수량, 미체결은 남은 수량입니다. */
  amount: number
  /** 봉이 끝나기 전에 규칙 판정으로 난 줄이면 그 봉의 시작 시각(모르면 `null`),
   *  아니면 `undefined` 입니다(`tickBarOf`). */
  tick: number | null | undefined
}

/** 아직 안 채워진 주문의 상태를 적는 말. **서버가 내는 값 둘**입니다.
 *
 *  모르는 값은 **받은 그대로 세웁니다** — 「—」로 적으면 이 앱에서는 「원래
 *  없는 값」으로 읽혀, 서버가 새 상태를 내기 시작한 것을 화면이 덮습니다. */
const ORDER_STATE_WORD: Record<string, string> = { waiting: '체결 전', partial: '일부 체결' }

/* 「계좌와 대조」를 기다리는 동안 머리 까닭 자리에 서는 글. 단추가 잠긴 까닭도 이 글입니다. */
const RECONCILING = '계좌와 대조하는 중'

/* 대조 결과가 머무는 시간. 알림 토스트의 짧은 머묾과 같은 값입니다. */
const NOTE_DWELL = 6000

/* 대조 결과 한 줄. 수는 **서버 답의 수**입니다 — 맞춰 본 실행과 그 가운데
   어긋난 실행. 어긋난 실행이 있으면 「일치」 대신 두 수를 함께 적습니다 —
   「n개 일치」만 적으면 확인이 필요한 실행이 있어도 다 맞은 것으로 읽힙니다.
   답에 수가 없으면(옛 서버) 맞춰 봤다는 것만 적습니다. */
function reconciledText(count: ReconcileCount | null): string {
  const head = '계좌와 대조했습니다'
  if (count === null) return head
  if (count.checked === 0) return `${head} — 맞춰 볼 실행 없음`
  const matched = Math.max(0, count.checked - count.mismatched)
  return count.mismatched > 0
    ? `${head} — 일치 ${matched} · 확인 필요 ${count.mismatched}`
    : `${head} — 실행 ${matched}개 일치`
}

type Confirm = {
  action: string
  runs: VerifyRun[]
  /** 「전체」인데 목록에 안 서는 실행. 이미 멈춘 것은 다시 멈출 일이 없어
   *  대상에서 빠지는데, 창이 그 수를 안 세면 「내 실행 하나는 어디 갔나」를
   *  창 안에서 답할 수 없습니다. */
  alreadyStopped?: number
} | null

export function StrategyRun() {
  /* 실행·체크·보는 실행은 **화면 밖**에 있습니다. 보낸 요청(「취소 요청」·
     「확인 필요」)이 탭을 옮겼다는 이유로 사라지면, 화면이 아직 안 끝난 일을
     없던 일로 말하게 됩니다(원본 §2·§7).
     여러 실행에 한 번에 거는 동작이 있어 **다중 선택**입니다. 고르는 것(체크)과
     보는 것(줄 몸 누름)을 따로 둡니다 — 검증 화면도 같은 두 겹입니다. */
  const store = useStrategyState()
  /* **실행 목록은 검증과 한 벌입니다.** 서버가 한 목록을 내고 화면이 갈래로
     가릅니다 — 따로 들면 방송 한 묶음을 두 번 쪼개야 하고, 한도 일곱이 어느
     쪽 것인지 말할 수 없습니다. */
  const { runs, status, failure, max, acting } = store.verify
  /* 실행을 담아 둔 파일을 서버가 못 읽었을 때 실행 카드에 세울 한 줄. */
  const storeWhy = storeNote('runs', store.runStore)
  /* 그중 **못 읽은** 경우. 빈 목록이 「없다」고 말해도 되는지가 여기서 갈립니다. */
  const storeBroken = store.runStore?.status === 'broken'
  const { checked, shownId, add, pending } = store.run
  const setChecked = (next: string[]) => patchRun({ checked: next })
  const setShownId = (id: string) => patchRun({ shownId: id })
  const openAdd = add !== null
  const closeAdd = () => patchRun({ add: null })

  /* 화면에만 남는 것들입니다. */
  const [bottom, setBottom] = useState<BottomTab>('최근 체결')
  const [confirm, setConfirm] = useState<Confirm>(null)
  /* 아래 표를 담은 칸의 안쪽 폭. 주문번호 열을 접을지는 보는 실행이 정해진 뒤에
     가립니다(`ORDER_NO_FITS`). */
  const tableBoxRef = useRef<HTMLDivElement>(null)
  const [tableInner, setTableInner] = useState(0)
  useLayoutEffect(() => {
    const box = tableBoxRef.current
    if (!box) return
    const measure = () => {
      const style = getComputedStyle(box)
      setTableInner(box.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight))
    }
    measure()
    const watcher = new ResizeObserver(measure)
    watcher.observe(box)
    return () => watcher.disconnect()
  }, [])
  /* 거래 추가 창이 **확인 얼굴**로 넘어갔는지. 창을 둘 겹치지 않고 한 창의
     얼굴을 바꿉니다 — 겹치면 뒤 카드의 칸이 앞 카드 둘레로 비어져 나오고,
     「그만두기」가 둘 보입니다. */
  const [ask, setAsk] = useState<AskFixed | null>(null)
  const asking = ask !== null
  /* 보낸 요청이 막혔을 때 서버가 준 문장. **그대로 세웁니다** — 화면이 같은
     검사를 다시 하면 둘이 갈립니다.
     **누른 단추 곁에 답니다.** 단추가 세 자리에 나뉘어 있어(머리 띠·목록
     아래·확인 띠) 한 자리에 모아 두면 누른 사람이 답을 다른 데서 찾습니다.
     새 답이 오면 앞의 답은 지웁니다 — 물음이 바뀌었는데 앞 답이 남아 있으면
     그것이 지금 답으로 읽힙니다. */
  const [why, setWhy] = useState<{ head?: string; side?: string; ack?: string }>({})
  /* 계좌와 대조를 기다리는 중인지와, 그 답(맞춰 본 수 또는 못 보낸 까닭).
     맞춰 본 결과는 잠깐 섰다가 걷힙니다 — 정상 결과라 남겨 둘 까닭이 없고,
     남으면 다음 대조의 답과 헷갈립니다. 매번 새 값이라 같은 결과가 다시 와도
     머무는 시간이 새로 셉니다. 못 보낸 까닭은 다음 대조까지 남습니다. */
  const [reconciling, setReconciling] = useState(false)
  const reconcileBusy = useRef(false)
  const [reconciled, setReconciled] = useState<
    { count: ReconcileCount | null } | { failed: string } | null
  >(null)
  useEffect(() => {
    if (reconciled === null || 'failed' in reconciled) return
    const timer = window.setTimeout(() => setReconciled(null), NOTE_DWELL)
    return () => window.clearTimeout(timer)
  }, [reconciled])

  /* 계좌 손실 한도. 창이 열려 있는지와, 저장을 보낸 사이인지. 보낸 사이에는
     창을 닫을 수 없습니다 — 닫고 나면 답이 어느 값으로 섰는지 볼 자리가 없습니다. */
  const limits = useLimits()
  const [limitsOpen, setLimitsOpen] = useState(false)
  const [limitsSaving, setLimitsSaving] = useState(false)
  /* 창을 열 때의 축. 창이 떠 있는 동안 접속 환경이 바뀌면 이 값과 갈리고, 그때
     창을 닫습니다(아래). */
  const [limitsAxis, setLimitsAxis] = useState<LimitAxis | null>(null)
  useEffect(() => {
    void loadLimits()
  }, [])

  /* 이 화면이 보는 것은 계좌로 도는 실행입니다(모의 계좌·실전 계좌 한 목록).
     종이 실행은 검증 화면이 봅니다. 목록·중지·청산이 모두 이 목록을 씁니다. */
  const all = runs.filter((run) => isAccountMode(run.mode))
  const shown = all.find((run) => run.id === shownId) ?? all[0] ?? null
  /* 보는 실행의 한 벌. **그 실행의 칸만** 읽습니다 — 검증 탭이 고른 실행과 따로
     담겨 있어, 검증 탭에서 무엇을 골라도 이 표는 보는 실행의 것입니다. */
  const snapshot = snapshotOf(store.verify, shown?.id)
  /* 틱으로 평가하는 실행이면 시각 칸이 「틱」 표지 자리만큼 넓고, 그만큼 주문번호
     열도 일찍 접힙니다. */
  const tickRun = isTickRun(shown)
  const narrow = tableInner > 0 && tableInner < (tickRun ? ORDER_NO_FITS_TICK : ORDER_NO_FITS)
  /* 「신규 진입 중지·선택 전략 청산·실행 종료」의 대상 — **체크한 실행만**
     (`targetsOf`, 검증 화면과 같은 규칙). 체크가 없으면 세 단추가 잠깁니다. */
  const picked = targetsOf(all, checked)
  /* 「거래 중」은 **중지·종료가 아닌 것**입니다. 목록에는 끝난 실행도 서므로
     셋을 각각 셉니다 — 하나를 빼기로 구하면 그 칸이 「나머지 전부」가 되어,
     끝난 실행이 「중지」로 읽힙니다. 중지는 다시 굴릴 수 있고 종료는 끝난
     것이라 다른 말입니다(검증 머리와 같은 조건). */
  const trading = all.filter((run) => run.state !== 'paused' && run.state !== 'ended').length
  const stopped = all.filter((run) => run.state === 'paused').length
  const ended = all.filter((run) => run.state === 'ended').length
  const needCheck = all.filter((run) => run.state === 'attention').length
  /* 「계좌와 대조」 단추 곁에 서는 한 줄 — 기다리는 중, 맞춰 본 결과, 못 보낸 까닭. */
  const reconcileLine = reconciling
    ? RECONCILING
    : reconciled === null
      ? ''
      : 'failed' in reconciled
        ? reconciled.failed
        : reconciledText(reconciled.count)
  const reconcileFailed = !reconciling && reconciled !== null && 'failed' in reconciled
  /* 상한을 먹는 실행 — 갈래를 안 가리고 끝나지 않은 것 전부(서버가 상한을 보는 셈). */
  const standingAll = runs.filter((run) => run.state !== 'ended').length

  /* 계좌 표시는 화면 전체의 맥락입니다. **갈래가 정합니다** — 실행이 없으면
     붙어 있는 계좌도 없어 빈 채로 둡니다. 어느 계좌인지 지어 세우면 그 계좌로
     주문이 나가는 것으로 읽힙니다. */
  const kinds = (['sim', 'real'] as const).filter((kind) => all.some((run) => run.mode === kind))
  /* 상단 환경과 계좌 실행의 환경이 갈렸는지. 갈래 배지 바로 뒤에 한 줄입니다. */
  const environment = useEnvironment()
  const split = envSplit(environment.active, all)

  /* 지금 세울 수 있는 계좌 갈래. **서버 답 하나에서 정합니다** — 접속 환경을
     확인했고(`ready`), 그 환경의 갈래가 서버가 준 목록(`accountModes`)에 있을
     때만입니다. 모르면 `null` 이라 확인 얼굴로 넘어가지 않습니다. */
  const modeNow = environment.status === 'ready' ? accountModeOf(environment.active) : null
  const askable = modeNow !== null && store.verify.accountModes.includes(modeNow) ? modeNow : null

  /* 머리 한도 줄이 보이고 고치는 축. **접속 환경이 정합니다** — 실전이면 실전
     계좌 쪽, 모의면 모의 쪽입니다. 환경을 모르면 `null` 이라 값을 세우지 않고
     「바꾸기」를 잠급니다: 다른 축의 값을 이 계좌의 것처럼 보이게 됩니다. */
  const axis: LimitAxis | null =
    environment.status === 'ready' && environment.active !== null
      ? environment.active === 'real'
        ? 'real'
        : 'paper'
      : null
  const axisLimits = axis === 'real' ? limits.real : axis === 'paper' ? limits.limits : null
  /* 이 축의 해외 통화 — 달러(늘)와, 한도를 걸었거나 이 축에 그 통화로 셈하는 실행이 있는
     통화. 걸지 않았고 실행도 없는 통화는 줄에 세우지 않습니다. */
  const axisCurrencies = useMemo(() => {
    const made = new Set<string>(['USD'])
    for (const [code, value] of Object.entries(axisLimits ?? {})) if (code !== 'KRW' && value !== null) made.add(code)
    for (const run of all) {
      if (run.mode === 'paper' || (axis === 'real') !== (run.mode === 'real')) continue
      const code = currencyCode(
        runCurrencyOf(run, currencyOf(run.market, store.rows.find((one) => one.id === run.version)?.currency)),
      )
      if (code && code !== 'KRW') made.add(code)
    }
    return ['USD', ...[...made].filter((code) => code !== 'USD').sort()]
    // 실행 목록·한도가 바뀔 때 다시 셉니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [axisLimits, all, axis, store.rows])
  /* 머리의 한도 줄 — 「국내 1,000,000원 · 해외 USD 1,500.00 · HKD 걸지 않음」. 「해외」는
     첫 통화 앞에만 붙습니다. */
  const limitLine = axisLimits
    ? [
        `국내 ${limitShown(axisLimits.KRW ?? null, '원', currencyDigits('KRW'))}`,
        ...axisCurrencies.map(
          (code, index) =>
            `${index === 0 ? '해외 ' : ''}${code} ${limitShown(axisLimits[code] ?? null, '', currencyDigits(code))}`,
        ),
      ].join(' · ')
    : ''
  /* 한도 창이 떠 있는 동안 축이 바뀌면 닫습니다 — 열 때의 계좌가 아닌 값을 고치게
     됩니다. 저장을 보낸 사이에는 답을 기다립니다. */
  useEffect(() => {
    if (limitsOpen && !limitsSaving && limitsAxis !== axis) setLimitsOpen(false)
  }, [axis, limitsAxis, limitsOpen, limitsSaving])

  /* 확인 얼굴이 떠 있는 동안 환경이 바뀌면 **닫고 폼으로 돌아갑니다.** 창에 보인
     갈래가 더는 지금 환경의 것이 아니라, 그대로 승인하면 서버가 거절하거나
     다른 계좌를 말하는 창이 남습니다. */
  useEffect(() => {
    if (ask === null) return
    const moved =
      environment.generation !== ask.generation ||
      environment.status !== 'ready' ||
      environment.active !== ask.environment ||
      !store.verify.accountModes.includes(ask.mode)
    if (moved) setAsk(null)
  }, [ask, environment.generation, environment.status, environment.active, store.verify.accountModes])

  /* 그 실행이 어느 전략의 것인가. **목록에서 찾습니다** — 실행 줄에 이름을
     적어 두면 전략 이름을 고칠 때 갈립니다(검증 화면과 같은 규칙). */
  const nameOf = (versionId: string) => runNameOf(store.rows, versionId, store.status === 'ready')
  /* 실행 줄의 통화 — 그 실행이 도는 전략의 것(검증 화면과 같은 셈). */
  const runCurrency = (run: VerifyRun) =>
    runCurrencyOf(run, currencyOf(run.market, store.rows.find((one) => one.id === run.version)?.currency))

  /* 앱이 보고 있는 청산 기준. **담긴 설정이 답합니다** — 줄에는 없는 값이고,
     서버가 받은 STOP 과도 다릅니다(앱이 꺼지면 이쪽은 멈춥니다). */
  const watch = shown ? savedOf(shown.version)?.aux : null
  /* 값의 자릿수는 **색인이 답합니다** — 줄에 적어 두면 만기가 넘어갈 때
     자릿수와 실제 종목이 갈립니다. */
  const decimals = (shown ? resolve(shown.code)?.product.decimals : null) ?? 2

  /* 화면이 열릴 때 목록을 받아 옵니다. 그 뒤로는 허브가 보내 주는 것으로
     채웁니다 — 검증 화면과 같은 자리를 씁니다. */
  useEffect(() => {
    void loadRuns()
  }, [])
  /* 접속 환경이 바뀌면 목록을 다시 받습니다. **세울 수 있는 갈래(`accountModes`)는
     이 조회에만 실려 옵니다** — 안 받으면 환경을 바꾼 뒤에도 앞 환경의 갈래가
     남아, 확인 얼굴이 계속 「확인하는 중」에 머뭅니다. 처음 연 때는 위가 받습니다. */
  const seenGeneration = useRef(environment.generation)
  useEffect(() => {
    if (seenGeneration.current === environment.generation) return
    seenGeneration.current = environment.generation
    void loadRuns()
  }, [environment.generation])

  /* 보는 실행이 바뀌면 그 실행의 한 벌을 받습니다. 체결·이벤트는 목록 줄에
     없습니다. */
  useEffect(() => {
    void loadRunSnapshot(shown?.id ?? '')
  }, [shown?.id])

  /* 아래 표의 행. **한 벌이 들고 온 값 그대로**입니다 — 표가 값을 따로
     세우면 같은 체결에 두 값이 생깁니다. */
  const rows = useMemo<VerifyFill[]>(
    () => (bottom === '최근 체결' ? (snapshot?.fills ?? []) : []),
    [snapshot, bottom],
  )

  /* 아직 안 채워진 주문. **덮어쓰는 값**이라 저장소가 방송이 준 것으로 통째로
     갈아 끼웁니다 — 여기서는 읽기만 합니다.
     줄 머리의 `pending` 과 **다른 수입니다**: 그쪽은 보내고 아직 답을 못 받은
     주문이고, 이 목록은 답을 받아 계좌에 서 있는 주문입니다. */
  const opens = useMemo<VerifyOrder[]>(
    () => (bottom === '미체결' ? (snapshot?.openOrders ?? []) : []),
    [snapshot, bottom],
  )

  /* 두 탭이 한 표를 씁니다. 그리기 전에 한 꼴로 맞춰 두어 칸마다 갈래를 다시
     보지 않습니다. */
  const tableRows = useMemo<TableRow[]>(() => {
    if (bottom === '미체결') {
      return opens.map((one, index) => ({
        key: `${one.orderId}-${one.time}-${index}`,
        time: one.time,
        orderNo: one.orderNo?.trim() || null,
        side: one.side,
        intent: one.intent,
        reason: one.reason,
        state: ORDER_STATE_WORD[one.status] ?? one.status,
        price: one.price,
        amount: one.remaining,
        tick: tickBarOf({ kind: 'order', order: one }),
      }))
    }
    /* 체결 줄을 가리는 열쇠는 **저장소·검증 표와 같은 것**입니다 — 한 주문이
       나뉘어 체결되고, 같은 밀리초에 두 줄이 날 수 있습니다. */
    return rows.map((one) => ({
      key: fillKey(one),
      time: one.time,
      /* **계좌가 준 번호**만 적습니다. `orderId` 는 장부가 매긴 번호라 계좌
         주문내역에서 찾을 수 없습니다. */
      orderNo: one.orderNo?.trim() || null,
      side: one.side,
      intent: one.intent,
      reason: one.reason,
      state: '체결',
      price: one.price,
      amount: one.quantity,
      tick: tickBarOf({ kind: 'fill', fill: one }),
    }))
  }, [bottom, opens, rows])

  const events = useMemo(() => snapshot?.events ?? [], [snapshot])

  /* 목록에서 「진행 화면으로」로 들고 온 전략. 이미 거래 중인 실행이 있으면
     그것을 보여 주고, 없을 때만 거래 추가 패널이 그 값으로 채워집니다. */
  useEffect(() => {
    if (!pending) return
    /* 줄은 버전 id 만 들고 있습니다 — 전략 이름은 목록에서 옵니다. */
    const wanted = store.rows.find(
      (row) => row.name === pending.strategy && row.version === pending.version,
    )
    const found = wanted ? all.find((run) => run.version === wanted.id) : undefined
    if (found) patchRun({ shownId: found.id, checked: [found.id], pending: null })
    else patchRun({ add: pending, pending: null })
    // 목록과 실행이 둘 다 있어야 고를 수 있어 둘을 함께 봅니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending, runs, store.rows])

  function showRun(id: string) {
    setShownId(id)
  }

  function toggle(id: string) {
    setChecked(checked.includes(id) ? checked.filter((x) => x !== id) : [...checked, id])
  }

  /* 확인 창을 누르면 요청이 나갑니다. **화면이 상태를 미리 바꾸지 않습니다** —
     바꿔 두면 아직 안 끝난 일을 끝난 것으로 말하게 되고, 서버가 막았을 때
     되돌릴 자리도 없습니다. 바뀐 상태는 방송이 실어 옵니다.
     막혔으면 **서버 문장을 그대로** 한 줄로 세웁니다 — 「대사 중」인 줄에는
     중지·청산·종료가, 「확인 필요」인 줄에는 중지·청산과 남은 것이 있는 종료가
     막히고, 그 까닭도 서버가 냅니다. */
  async function apply(action: string, targets: VerifyRun[]) {
    setConfirm(null)
    setWhy({})
    if (action === '전체 신규 진입 중지') {
      const said = await stopAllRuns()
      /* 답이 수(멈춘 실행 개수)면 막힌 것이 아닙니다. */
      if (typeof said === 'string') setWhy({ head: said })
      return
    }
    /* **빠지는 줄을 빼고 나머지를 차례로** 보내고, 하나가 거절돼도 나머지는
       보냅니다. 한 실행의 사정이 다른 실행을 막을 까닭이 없습니다. 결과는
       「N건 중 K건 거절 — 첫 서버 문장」 한 줄입니다(검증과 같은 셈). */
    const deed = action === '실행 종료' ? 'end' : action === '선택 전략 청산' ? 'close' : 'stop'
    const sending = targets.filter((run) => skipWhy(action, run) === null)
    const said = await sendEach(sending, (run) => actOnRun(run.id, deed))
    if (said !== null) setWhy({ side: said })
  }

  /* 이 요청이 건드리지 않는 줄. **서버가 400 으로 막는 자리와 같습니다** —
     「확인 필요」와 「대사 중」은 사용자가 손을 써야 넘어가는 상태라, 새 요청을
     보냈다고 사라지면 화면이 「끝난 일」로 말하게 됩니다(규격 §7). 「확인 필요」
     줄의 「실행 종료」만은 예외입니다(`skipWhy`). */
  const blocks = (run: VerifyRun) => run.state === 'attention' || run.state === 'reconciling'

  /* 확인창에서 그 줄이 빠지는 까닭. 빠지지 않으면 `null` 입니다.
     끝난 실행은 **세 동작 모두에서** 뺍니다 — 멈출 신규 진입도, 청산할 보유도
     없어 보내면 서버가 거절합니다. 「실행 종료」는 보유가 남은 실행도 미리
     뺍니다. 까닭 낱말은 검증 화면과 같은 글자입니다. 미체결·취소 확인 대기는
     이 줄이 모르는 값이라 서버가 거절하고, 그 문장이 섭니다. */
  function skipWhy(action: string, run: VerifyRun): string | null {
    /* 「확인 필요」 줄의 종료는 남은 것이 없으면 보냅니다 — 계좌로 나가는 요청이
       없습니다. 남은 것이 보이면 그 까닭으로 뺍니다(`attentionEndWhy`). */
    if (action === '실행 종료' && run.state === 'attention') return attentionEndWhy(run)
    if (blocks(run)) return `${run.stateLabel} — 이번 요청에서 제외`
    if (run.state === 'ended') return '끝난 실행입니다'
    if (action !== '실행 종료') return null
    if (run.position !== 0) return '「선택 전략 청산」을 먼저 하세요'
    return null
  }

  /* 계좌와 대조. 답을 기다리는 동안 단추를 잠급니다 — 그린 값은 다음 그림까지
     옛 값이라, 한 번에 몰려 온 두 번째 누름은 `reconcileBusy` 가 막습니다.
     맞춰 봤으면 그 결과를 잠깐 세우고, 못 보냈으면 서버 글을 남깁니다. 둘 다
     단추 곁 한 줄에 섭니다. */
  async function reconcile() {
    if (reconcileBusy.current) return
    reconcileBusy.current = true
    setReconciling(true)
    setReconciled(null)
    setWhy({})
    const said = await reconcileRuns()
    reconcileBusy.current = false
    setReconciling(false)
    setReconciled(typeof said === 'string' ? { failed: said } : { count: said })
  }

  /* 확인창을 엽니다. 지난 요청의 결과 줄(「N건 중 K건 거절」)은 비웁니다 —
     새 창에서 고른 실행과 상관없는 앞 요청의 말이 남아 있으면 이번 결과로
     읽힙니다. */
  function openConfirm(next: NonNullable<Confirm>) {
    setWhy((now) => ({ ...now, side: undefined }))
    setConfirm(next)
  }

  /* 「확인 필요」를 푸는 자리. 서버가 계좌와 다시 맞춰 보고, 그래도 어긋나면
     **그대로 「확인 필요」로 남습니다** — 화면이 푼 것으로 적지 않습니다. */
  async function acknowledge(id: string) {
    const said = await actOnRun(id, 'acknowledge')
    setWhy(said === null ? {} : { ack: said })
  }

  /* 배지 한 칸의 색. **경고색은 「확인 필요」 하나**가 씁니다 — 손을 써야
     넘어가는 자리는 그것뿐이고, 기다리면 되는 자리(답 대기·대사 중·승인
     없음)까지 경고로 칠하면 정말 손써야 하는 줄이 그 속에 묻힙니다.
     손을 써야 넘어가는 줄은 **방향색을 뺍니다** — 「확인 필요」를 파랑으로
     칠하면 낱말까지 덮여 매도로 읽힙니다. 그 줄의 보유 방향은 글자가
     말합니다. */
  function badgeOf(run: VerifyRun): string {
    if (run.state === 'attention') return 'badge run-alert'
    return directionOf(run) ? 'badge run-holding' : 'badge'
  }
  /* 보유 방향 조각의 색 — 방향색은 **「매수 n계약」·「매도 n계약」 조각에만**
     씁니다. 상태 낱말(「감시 중」)까지 칠하면 상태가 방향처럼 읽힙니다. */
  function directionOf(run: VerifyRun): string | undefined {
    if ((run.position ?? 0) > 0 && !blocks(run)) return run.side === 'buy' ? 'run-dir-buy' : 'run-dir-sell'
    return undefined
  }

  function runRow(run: VerifyRun) {
    const holding = (run.position ?? 0) > 0
    const said = nameOf(run.version)
    return (
      <label className={`run-row${run.id === shown?.id ? ' is-shown' : ''}`} key={run.id}>
        <input type="checkbox" checked={checked.includes(run.id)} onChange={() => toggle(run.id)} />
        <button
          type="button"
          className="run-row-body"
          aria-current={run.id === shown?.id ? 'true' : undefined}
          onClick={() => showRun(run.id)}
        >
          {/* 전략 이름 · 버전 · 종목을 줄을 나눠 적습니다 — 한 줄에 붙이면
              좁은 열에서 종목이 만기부터 잘립니다(검증 화면과 같은 규칙). */}
          {/* 이름 줄 끝에 그 실행의 갈래 — 모의 계좌와 실전 계좌 실행이 한 목록에
              섭니다. */}
          <span className="run-name">
            <span className="run-name-text">{said.name}</span>
            <RunKindBadge kind={run.mode} short />
          </span>
          <span className="run-sub">{said.version}</span>
          <span className="run-sub">{shortInstrument(run.code)}</span>
          <span className="run-state">
            {/* 상태 낱말은 **서버가 함께 줍니다** — 화면이 상태 표를 또 두면
                두 표가 갈립니다. */}
            <span className={badgeOf(run)}>
              {run.stateLabel}
              {holding && ' · '}
              {holding && (
                <span className={directionOf(run)}>
                  {run.side === 'buy' ? '매수' : '매도'} {run.position}계약
                </span>
              )}
              {/* 보유를 모르면(`null`) 0 이라 적지 않고 「—」입니다. */}
              {!holding && (run.position === null ? ' · 보유 —' : ' · 보유 0')}
            </span>
            {/* 보낸 주문 가운데 아직 답을 못 받은 수입니다. **기다리면 되는
                자리**라 중립입니다 — 손쓸 것이 없습니다. */}
            {(run.pending ?? 0) > 0 && <span className="run-note">답 대기 {run.pending}</span>}
          </span>
          {/* 성과 한 줄 — 서버가 센 신호·체결 수와 손익, 마지막 신호 시각. */}
          <RunStats run={run} currency={runCurrency(run)} />
          {/* 아래 줄에는 **배지가 말하지 않는 것만** 답니다. 「확인 필요」·
              「대사 중」은 이미 배지에 있어 여기 또 적으면 같은 사실이 한 줄에
              두 번 섭니다.

              승인을 안 지난 모의 실행은 **한 건도 안 냅니다.** 도는 것처럼
              보이는데 주문이 안 나가는 까닭이라 줄에 적습니다. **값이 아예
              없는 것도 「안 지났다」입니다** — 서버가 그 칸을 안 실어 줄 수도
              있고, 그때 「지났다」로 읽으면 안 나가는 주문을 나간다고 말하게
              됩니다. */}
          {!run.approvedAt && <span className="run-note">승인 없음 — 주문 안 나감</span>}
        </button>
      </label>
    )
  }

  return (
    <div className="run">
      <div className="card run-head">
        <div className="run-head-line">
          {/* 이 배지는 접속 환경이 아니라 **실행 갈래**입니다. 목록에 선 갈래마다
              하나씩 섭니다 — 실행이 없으면 붙은 계좌도 없어 비워 둡니다. */}
          {kinds.map((kind) => (
            <RunKindBadge key={kind} kind={kind} />
          ))}
          {split && <EnvSplitNote text={split} />}
          {/* 실행 중·중지·종료는 이 화면의 계좌 실행 수입니다. 셋은 따로 셉니다 —
              실행 중은 중지·종료가 아닌 것입니다.
              상한은 **갈래를 안 가립니다** — 종이 실행 하나도 그 자리를 먹습니다.
              그래서 분자는 검증·계좌의 끝나지 않은 실행 전부이고(서버가 한도를 볼
              때와 같은 셈), 그 범위는 `title` 이 말합니다. 끝난 실행은 자리를 안
              먹으므로 상한의 분자에 들지 않습니다. */}
          <span className="run-counts" title={max > 0 ? '상한은 검증 실행과 함께 셉니다' : undefined}>
            {`실행 중 ${trading} · 중지 ${stopped} · 종료 ${ended} · 상한 ${standingAll}`}
            {max > 0 && ` / ${max}`}
          </span>
          {status === 'failed' && <span className="run-need">{failure}</span>}
          {needCheck > 0 && <span className="run-need">확인 필요 {needCheck}</span>}
          {/* 계좌와 다시 맞춰 보라고 청합니다. **값을 화면이 고치는 것이
              아닙니다** — 서버가 계좌를 다시 읽어 제 장부와 견줍니다.
              그 답은 **단추 바로 곁**에 섭니다 — 누른 자리에서 눈을 옮기지 않고
              읽을 수 있어야 잠깐 섰다 걷히는 결과를 놓치지 않습니다. */}
          <span className="run-reconcile">
            <button
              type="button"
              className="btn btn-quiet"
              aria-disabled={reconciling || undefined}
              aria-describedby={reconcileLine ? 'run-reconcile-why' : undefined}
              onClick={() => void reconcile()}
            >
              계좌와 대조
            </button>
            <span
              className={`run-reconcile-why${reconcileFailed ? '' : ' is-note'}`}
              id="run-reconcile-why"
              aria-live="polite"
              title={reconcileLine || undefined}
            >
              {reconcileLine}
            </span>
          </span>
          <button
            type="button"
            className="btn btn-quiet run-stopall"
            aria-disabled={trading === 0}
            aria-describedby={trading === 0 || why.head ? 'run-head-why' : undefined}
            onClick={() =>
              trading > 0 &&
              openConfirm({
                action: '전체 신규 진입 중지',
                runs: all.filter((r) => r.state !== 'paused' && r.state !== 'ended'),
                alreadyStopped: stopped,
              })
            }
          >
            전체 신규 진입 중지
          </button>
        </div>

        {/* 머리 단추 둘의 까닭. **그 단추 곁**입니다 — 목록 아래 줄에 함께
            두면 머리에서 누른 사람이 답을 화면 반대쪽에서 찾게 됩니다. 자리는
            늘 비워 두어 아래가 오르내리지 않습니다. */}
        <p className="run-why run-head-why" id="run-head-why">
          {why.head ?? (trading === 0 ? '도는 실행이 없습니다' : '')}
        </p>

        {/* 계좌 전체의 하루 손실 한도. 실행 하나가 아니라 **그 축·그 시장의 계좌
            실행 전부**에 걸리므로 실행 카드가 아닌 머리에 둡니다. 어느 계좌의 한도인지
            낱말로 먼저 말합니다 — 접속 환경이 정한 축입니다.
            값을 모르는 동안에는 「바꾸기」를 잠급니다 — 저장은 한 축의 두 시장을
            함께 보내므로, 모르는 값을 빈 칸으로 보내면 걸려 있던 한도가 풀립니다. */}
        <div className="run-limits">
          <span className="run-limits-text" title={axisLimits ? `계좌 손실 한도 · ${limitLine}` : undefined}>
            계좌 손실 한도
            {/* 어느 계좌의 한도인지는 **갈래 배지**가 말합니다(접속 환경의 계좌).
                환경을 모르면 배지 자리를 비우고 값은 「—」입니다. */}
            {axis !== null && <RunKindBadge kind={axis === 'real' ? 'real' : 'sim'} short />}
            {' · '}
            {axis === null
              ? '—'
              : axisLimits
                ? limitLine
                : limits.status === 'failed' || limits.status === 'ready'
                  ? '한도를 받지 못했습니다'
                  : '받는 중'}
          </span>
          {axis !== null && axisLimits === null && limits.status === 'failed' ? (
            <button type="button" className="btn btn-quiet" onClick={() => void loadLimits()}>
              다시
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-quiet"
              aria-disabled={axisLimits === null}
              onClick={() => {
                if (axisLimits === null || axis === null) return
                setLimitsAxis(axis)
                setLimitsOpen(true)
              }}
            >
              바꾸기
            </button>
          )}
          {axis === null && <span className="run-limits-wait">환경을 확인하는 중</span>}
        </div>
        {/* 한도를 담아 둔 파일을 못 읽었거나 이 앱의 파일이 아니면, 서버는 한도를
            걸지 않은 채로 돕니다. 「걸지 않음」이 사용자가 고른 값으로 읽히지 않게
            까닭을 적습니다. 새로 저장하면 걷힙니다. */}
        {limits.store !== null && (limits.store.status === 'broken' || limits.store.otherApp !== null) && (
          <p className="run-store-why">한도 파일을 읽지 못해 풀렸습니다 — 다시 걸어 주세요</p>
        )}
      </div>

      <div className="run-body">
        <aside className="run-side" aria-label="실행 목록">
          <div className="run-side-inner">
            <div className="card run-runs">
              <div className="run-runs-head">
                <h2 className="run-card-title">실행</h2>
                <button
                  type="button"
                  className="btn btn-primary"
                  /* 목록에서 고른 전략으로 채워 엽니다 — 첫 줄로 채우면
                     골라 둔 전략을 두고 다른 전략이 섭니다. */
                  onClick={() => patchRun({ add: seedFromSelection() })}
                >
                  거래 추가
                </button>
              </div>
              {/* 담아 둔 실행을 서버가 못 읽었으면 **목록이 빈 까닭**을 이 카드
                  안에 한 줄로 답니다. 카드는 단추가 서 있어 통째로 비지 않으므로
                  블록이 아니라 줄입니다. 머리 아래의 줄과 겹치지 않습니다 — 그
                  줄은 누른 단추의 답이고, 이 줄은 목록이 왜 비었는지입니다.
                  파일 이름은 **마우스를 올렸을 때만** 보입니다 — 사용자가 할 일을
                  바꾸는 말이 아니라 나중에 찾을 때 쓰는 말이고, 좁은 카드에서
                  여러 줄로 접히면 실행 목록이 밀려납니다. */}
              {storeWhy !== null && (
                <p className="run-store-why" title={storeWhy.reason ?? undefined}>
                  {storeWhy.title}
                </p>
              )}
              <div className="run-list">
                {status === 'loading' && <p className="run-why">실행 목록을 받는 중입니다</p>}
                {/* 비었다는 말은 가운데 빈 화면이 합니다 — 여기 또 적으면 같은 말이 두 번 섭니다.
                    담아 둔 파일을 **못 읽었으면 그 빈 화면도 안 섭니다** — 바로 위 한 줄이 이미
                    무슨 일인지 말했고, 「없다」고 하면 그 말과 반대가 됩니다. 이 앱 파일이 아닌
                    경우는 읽기는 읽었고 그 실행들이 안 도는 것이 사실이라 빈 화면이 섭니다. */}
                {all.map(runRow)}
              </div>
              {/* 일괄 단추가 무엇에 걸리는지 — 단추 묶음 바로 위입니다(검증 화면과 같은 자리). */}
              {all.length > 0 && <p className="run-target">{targetLine(picked.length)}</p>}
              <div className="run-acts">
                <button
                  type="button"
                  className="btn btn-quiet"
                  aria-disabled={picked.length === 0}
                  aria-describedby={picked.length === 0 ? 'run-pick-why' : undefined}
                  title={picked.length === 0 ? PICK_HINT : undefined}
                  onClick={() => picked.length > 0 && openConfirm({ action: '신규 진입 중지', runs: picked })}
                >
                  신규 진입 중지
                </button>
                <button
                  type="button"
                  className="btn btn-quiet"
                  aria-disabled={picked.length === 0}
                  aria-describedby={picked.length === 0 ? 'run-pick-why' : undefined}
                  title={picked.length === 0 ? PICK_HINT : undefined}
                  onClick={() => picked.length > 0 && openConfirm({ action: '선택 전략 청산', runs: picked })}
                >
                  선택 전략 청산
                </button>
                {/* 검증 화면과 같은 낱말·같은 차례(중지 → 청산 → 종료)입니다. */}
                <button
                  type="button"
                  className="btn btn-quiet"
                  aria-disabled={picked.length === 0}
                  aria-describedby={picked.length === 0 ? 'run-pick-why' : undefined}
                  title={picked.length === 0 ? PICK_HINT : undefined}
                  onClick={() => picked.length > 0 && openConfirm({ action: '실행 종료', runs: picked })}
                >
                  실행 종료
                </button>
                {/* 단추 아래는 **서버가 막은 까닭**과 못 누르는 까닭의 자리입니다 — 단추에서
                    먼 머리 띠에 두면 누른 사람이 답을 다른 데서 찾아야 합니다. 서버 문장이
                    먼저입니다: 방금 보낸 것에 대한 답이라 지금 알아야 할 것이 그쪽입니다.
                    자리는 늘 비워 두어 목록이 오르내리지 않습니다. */}
                <p className="run-why" id="run-pick-why">
                  {why.side ?? (all.length > 0 && picked.length === 0 ? PICK_HINT : '')}
                </p>
              </div>
            </div>
          </div>
        </aside>

        {/* 거래 중인 실행이 하나도 없으면 오른쪽 상세(표)를 그리지 않습니다 — 빈 표는
            「고장」과 구별되지 않습니다. 가운데에 그 사실과 할 일 하나입니다. */}
        {status === 'ready' && all.length === 0 && !storeBroken ? (
          <div className="run-main notice">
            <p className="notice-title">거래 중인 실행이 없습니다</p>
            <button
              type="button"
              className="btn btn-primary notice-action"
              onClick={() => patchRun({ add: seedFromSelection() })}
            >
              거래 추가
            </button>
          </div>
        ) : (
        <div className="run-main">
          {/* 지금 보는 실행 — 전략 · 버전 · 종목 · 세션. 아래 표가 이 실행의 것입니다. */}
          {shown && (
            <p className="vrf-title">
              <span className="vrf-title-name">{nameOf(shown.version).name || '—'}</span>
              <span className="vrf-title-sub">
                {' · '}
                {[nameOf(shown.version).version, shortInstrument(shown.code), shown.sessionLabel]
                  .filter(Boolean)
                  .join(' · ')}
              </span>
            </p>
          )}
          <div className="run-bar">
            <span className="run-bar-item">
              보유{' '}
              <b>
                {shown && (shown.position ?? 0) > 0
                  ? `${shown.side === 'buy' ? '매수' : '매도'} ${shown.position}계약`
                  : shown && shown.position === null
                    ? '—'
                    : '없음'}
              </b>
            </span>
            <span className="run-bar-item">
              평균가{' '}
              <b>
                {shown && shown.avgPrice !== null ? (
                  <Num value={shown.avgPrice} decimals={decimals} />
                ) : (
                  '—'
                )}
              </b>
            </span>
            <span className="run-bar-item">
              {/* 실행이 없으면 **값도 없습니다**. 0 으로 적으면 「본전」이 되는데
                  본전은 들고 있는 것이 있을 때 하는 말입니다(평균가와 같은 얼굴). */}
              평가손익{' '}
              <b className={shown ? toneOf(shown.pl ?? 0) || undefined : undefined}>
                {/* 실행의 통화로 적습니다 — 해외 실행은 품목 통화입니다. */}
                {shown ? `${(shown.pl ?? 0) > 0 ? '+' : ''}${moneyIn(shown.pl, runCurrency(shown))}` : '—'}
              </b>
            </span>
            {/* 서버가 받은 STOP 과 앱이 보고 있는 손절은 다릅니다 — 앱이 꺼지면
                뒤엣것은 멈춥니다(원본 §7). 그래서 「앱 감시」를 함께 적습니다. */}
            <span className="run-bar-item run-watch">
              <b>{watchLine(watch)}</b> · 앱 감시
              {/* 이어진 손실과 그 한도. 규칙대로 도는 중이라 중립 글자입니다. */}
              {streakText(shown, watch?.lossStreak) && ` · ${streakText(shown, watch?.lossStreak)}`}
            </span>
          </div>

          {/* 「확인 필요」는 사용자가 손을 써야 넘어가는 자리라, 목록 줄이 아니라
              **보는 실행 위**에 한 줄로 섭니다 — 줄 안에 두면 다른 실행을 보는
              동안 그 사실이 화면에서 사라집니다. */}
          {shown?.state === 'attention' && (
            <div className="run-attention">
              <span>
                계좌와 우리 장부가 어긋나 멈춰 있습니다. 확인해야 다시 움직입니다. 이 실행에 남은 보유·주문이
                없으면 「실행 종료」로 끝낼 수 있습니다.
              </span>
              <button
                type="button"
                className="btn btn-quiet"
                aria-disabled={acting === shown.id}
                aria-describedby={why.ack ? 'run-ack-why' : undefined}
                onClick={() => acting !== shown.id && void acknowledge(shown.id)}
              >
                확인
              </button>
            </div>
          )}
          {/* 「확인」이 막힌 까닭도 그 단추 곁입니다. 띠가 서 있을 때만
              나오므로 자리를 늘 비워 두지는 않습니다. */}
          {why.ack && (
            <p className="run-why" id="run-ack-why">
              {why.ack}
            </p>
          )}

          <div className="run-bottom">
            <div className="tabs tabs-inline run-bottom-tabs">
              {BOTTOM_TABS.map((item) => (
                <button
                  key={item}
                  type="button"
                  className="tab"
                  aria-current={item === bottom}
                  onClick={() => setBottom(item)}
                >
                  {item}
                </button>
              ))}
            </div>

            <div className="table-scroll run-table" ref={tableBoxRef}>
              {bottom === '이벤트' ? (
                <table className="data-table rows-base">
                  <colgroup>
                    <col className={`run-col-time${tickRun ? ' is-tick' : ''}`} />
                    <col />
                  </colgroup>
                  <thead>
                    <tr>
                      <th scope="col" className="col-text">
                        시각
                      </th>
                      <th scope="col" className="col-text">
                        내용
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.map((item) => {
                      const tick = tickBarOf({ kind: 'event', event: item })
                      return (
                        <tr key={`${item.time}-${item.kind}-${item.text}`}>
                          <td className="col-text">
                            {clockOf(item.time)}
                            {tick !== undefined && <TickBadge barTime={tick} />}
                          </td>
                          <td className="col-text">
                            {/* 계좌가 주문을 거부한 줄은 검증 탭과 같은 「거부」 배지를 앞에
                                답니다. 글은 서버가 준 거부 코드와 문구 그대로입니다. */}
                            {isRejectedEvent(item) && (
                              <span className="badge vrf-event-badge vrf-event-badge-rejected">거부</span>
                            )}
                            {item.text}
                          </td>
                        </tr>
                      )
                    })}
                    {/* 머리만 있는 빈 표는 「고장」과 구별되지 않습니다. */}
                    {events.length === 0 && (
                      <tr>
                        <td className="run-empty-row" colSpan={2}>
                          아직 남은 이벤트가 없습니다
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              ) : (
                <table className="data-table rows-base">
                  <colgroup>
                    <col className={`run-col-time${tickRun ? ' is-tick' : ''}`} />
                    {!narrow && <col className="run-col-no" />}
                    <col className="run-col-side" />
                    {/* 용도가 남는 폭을 가져갑니다 — 까닭까지 적는 칸이라
                        못 박으면 「청산 · 손절」의 까닭이 잘립니다. */}
                    <col />
                    <col className="run-col-state" />
                    <col className="run-col-price" />
                    <col className="run-col-qty" />
                  </colgroup>
                  <thead>
                    <tr>
                      <th scope="col" className="col-text">
                        시각
                      </th>
                      {!narrow && (
                        <th scope="col" className="col-text">
                          주문번호
                        </th>
                      )}
                      <th scope="col" className="col-text">
                        구분
                      </th>
                      <th scope="col" className="col-text">
                        용도
                      </th>
                      <th scope="col" className="col-text">
                        상태
                      </th>
                      <th scope="col">가격</th>
                      <th scope="col">{bottom === '미체결' ? '미체결' : '수량'}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tableRows.map((one) => (
                      <tr key={one.key}>
                        {/* 주문번호 열을 접은 폭에서는 번호가 시각 칸에 마우스를
                            올렸을 때 보입니다(`ORDER_NO_FITS`). */}
                        <td
                          className="col-text"
                          title={narrow && one.orderNo ? `주문번호 ${one.orderNo}` : undefined}
                        >
                          {clockOf(one.time)}
                          {one.tick !== undefined && <TickBadge barTime={one.tick} />}
                        </td>
                        {/* 값이 아니라 주문내역에서 찾아 맞출 때 쓰는 열쇠라 한 급
                            낮게 적습니다. */}
                        {!narrow && <td className="col-text run-no">{one.orderNo ?? '—'}</td>}
                        <td className={`col-text ${one.side === 'buy' ? 'up' : 'down'}`}>
                          {one.side === 'buy' ? '매수' : '매도'}
                        </td>
                        <td className="col-text">
                          {one.intent === 'entry' ? '진입' : '청산'}
                          {reasonWord(one.reason) && ` · ${reasonWord(one.reason)}`}
                        </td>
                        <td className="col-text">{one.state}</td>
                        {/* 시장가에는 가격이 없습니다 — 0 을 적으면 「0원에
                            걸었다」로 읽히므로 「—」를 세웁니다. */}
                        <td>
                          <NumOrDash value={one.price} decimals={decimals} />
                        </td>
                        {/* 체결은 채워진 수량, 미체결은 **남은 수량**입니다 —
                            낸 수량을 적으면 부분체결이 안 줄어든 것처럼 보입니다.
                            어느 쪽인지는 위에서 탭이 정해 두었습니다. */}
                        <td>{one.amount}</td>
                      </tr>
                    ))}
                    {tableRows.length === 0 && (
                      <tr>
                        <td className="run-empty-row" colSpan={narrow ? 6 : 7}>
                          {bottom === '미체결' ? '남은 주문이 없습니다' : '아직 체결이 없습니다'}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
        )}
      </div>

      {confirm && (() => {
        /* 요청이 실제로 나가는 줄과 빠지는 줄. 창의 셈·목록·단추가 모두 이
           갈래를 씁니다. */
        const applied = confirm.runs.filter((run) => skipWhy(confirm.action, run) === null)
        const excluded = confirm.runs.filter((run) => skipWhy(confirm.action, run) !== null)
        const stopped = confirm.alreadyStopped ?? 0
        /* 나갈 줄이 없을 때 단추 곁에 세우는 까닭. 빠진 까닭이 하나면 그 말이고,
           갈리면 갈린 말들을 잇습니다 — 줄마다의 까닭은 목록에 이미 있습니다.
           중지·청산에서 빠진 줄이 모두 「확인 필요」·「대사 중」이면 그 둘을 한
           말로 묶습니다. 목록 자체가 비었으면 빠진 까닭이 아니라 대상이 없다고
           적습니다. */
        const noneWhy =
          confirm.runs.length === 0
            ? '대상 실행이 없습니다'
            : confirm.action !== '실행 종료' && excluded.every(blocks)
              ? '대상 실행이 모두 확인 필요 상태입니다'
              : [...new Set(excluded.map((run) => skipWhy(confirm.action, run) as string))].join(' · ')
        return (
        <Modal
          label={confirm.action}
          dismissable={false}
          onClose={() => setConfirm(null)}
          head={<span className="modal-title">{confirm.action}</span>}
        >
          <dl className="run-confirm">
            <div className="run-confirm-row">
              <dt>진입 주문</dt>
              <dd>{CONFIRM_TEXT[confirm.action].order}</dd>
            </div>
            <div className="run-confirm-row">
              <dt>보유분</dt>
              <dd>{CONFIRM_TEXT[confirm.action].holding}</dd>
            </div>
          </dl>

          {/* 「나열한 계좌·실행 범위에 적용」이라 적어 놓고 나열하지 않으면 그
              문장이 거짓이 됩니다 — 반대로 **나열해 놓고 안 나가는 것**이 섞여
              있어도 거짓입니다. 그래서 세는 것은 **요청이 실제로 나가는 건수**
              이고, 빠지는 줄은 목록에 두되 왜 빠지는지를 그 줄에 답니다.
              「확인 필요」는 사용자가 손을 써야 넘어가는 상태라 이 요청이
              건드리지 않습니다(원본 §7). */}
          {/* 괄호는 둘입니다 — **목록에 선 것 중 안 나가는 수**(제외)와 **이미
              중지되어 목록에 서지도 않은 수**. 둘 다 0 이면 적지 않고, 뒤엣것은
              「전체」에서만 생깁니다.
              뒤엣것에는 「목록에 없음」을 붙입니다. 수와 목록 줄 수가 어긋나는
              까닭을 창이 말하지 않으면, 목록의 어느 줄이 이미 중지된 것인지
              찾게 됩니다. 한 괄호에 둘을 이어 적으면 「목록에 없음」이 목록에
              선 제외 줄까지 걸려 읽혀, 괄호를 나눕니다.
              「전체」에서 끝난 실행은 어느 쪽에도 안 셉니다. 이 요청이 하려는
              일이 이미 끝난 것이라, 「안 나갔다」고 알릴 것이 없습니다. 골라서
              연 창에서는 고른 줄이 목록에 서므로 끝난 실행도 제외로 셉니다. */}
          <p className="run-confirm-title">
            적용 범위 {applied.length}건
            {excluded.length > 0 && ` (제외 ${excluded.length}건)`}
            {stopped > 0 && ` (이미 중지 ${stopped}건 — 목록에 없음)`}
          </p>
          <ul className="run-confirm-list">
            {confirm.runs.map((run) => {
              const skip = skipWhy(confirm.action, run)
              const said = nameOf(run.version)
              return (
                <li key={run.id} className={skip !== null ? 'run-confirm-skip' : undefined}>
                  {RUN_KIND_LABEL[run.mode]} · {said.name} {said.version} · {shortInstrument(run.code)}
                  {skip !== null && (
                    <span className="run-confirm-skip-why">
                      {' '}
                      · {skip}
                    </span>
                  )}
                </li>
              )
            })}
          </ul>
          {/* 종료는 취소도 청산도 내지 않습니다 — 그 창에서 이 안내는 틀린 말입니다. */}
          {confirm.action !== '실행 종료' && (
            <p className="run-hint">
              취소 요청은 취소 완료가 아니고 청산 요청은 체결 완료가 아닙니다 — 처리 결과를 확인해야 합니다
            </p>
          )}

          <p className="run-confirm-why" id="run-confirm-why">
            {/* 「고른」이라 하지 않습니다 — 「전체 신규 진입 중지」에는 고르는
                절차가 없고, 세 동작이 이 창 하나를 같이 씁니다. */}
            {applied.length === 0 ? noneWhy : ''}
          </p>

          <div className="run-confirm-acts">
            <button type="button" className="btn btn-quiet" onClick={() => setConfirm(null)}>
              그만두기
            </button>
            {/* 나갈 요청이 하나도 없으면 누를 것이 없습니다 — 눌러서 아무 일도
                안 나는 단추를 두지 않습니다(규격 §3). */}
            <button
              type="button"
              className="btn btn-heavy"
              aria-disabled={applied.length === 0}
              aria-describedby={applied.length === 0 ? 'run-confirm-why' : undefined}
              onClick={() => applied.length > 0 && apply(confirm.action, confirm.runs)}
            >
              {confirm.action}
            </button>
          </div>
        </Modal>
        )
      })()}

      {openAdd && (
        <Modal
          label={ask ? ASK_TEXT[ask.mode].title : '거래 추가'}
          /* 확인 얼굴에서는 ✕ 도 바깥 누르기도 없습니다 — ✕ 는 아래
             「그만두기」와 같은 일인데, 첫 초점이 ✕ 로 가면 창이 물은 것에
             답하는 자리가 초점 밖에 남습니다(주문 확인창과 한 벌). */
          closable={!asking}
          dismissable={!asking}
          onClose={() => (asking ? setAsk(null) : closeAdd())}
          head={<span className="modal-title">{ask ? ASK_TEXT[ask.mode].title : '거래 추가'}</span>}
        >
          <RunAddForm
            rows={store.rows}
            savingId={store.saving}
            seed={add}
            why={store.verify.addWhy}
            ask={ask}
            askable={askable}
            onAsk={() => {
              /* 누른 순간의 갈래와 환경을 고정합니다. */
              if (askable === null || environment.active === null) return
              setAsk({ mode: askable, environment: environment.active, generation: environment.generation })
            }}
            onBack={() => setAsk(null)}
            onCancel={() => closeAdd()}
            onStarted={() => {
              setAsk(null)
              closeAdd()
            }}
          />
        </Modal>
      )}

      {limitsOpen && limitsAxis !== null && (limitsAxis === 'real' ? limits.real : limits.limits) !== null && (
        <Modal
          label={`계좌 손실 한도 · ${limitsAxis === 'real' ? '실전' : '모의'}`}
          closable={!limitsSaving}
          dismissable={!limitsSaving}
          onClose={() => !limitsSaving && setLimitsOpen(false)}
          head={
            <span className="modal-title">계좌 손실 한도 · {limitsAxis === 'real' ? '실전' : '모의'}</span>
          }
        >
          <LimitsForm
            axis={limitsAxis}
            currencies={axisCurrencies}
            start={(limitsAxis === 'real' ? limits.real : limits.limits)!}
            saving={limitsSaving}
            onSaving={setLimitsSaving}
            onClose={() => setLimitsOpen(false)}
          />
        </Modal>
      )}
    </div>
  )
}

/** 한도 한 칸의 머리 글자. 안 걸었으면 「걸지 않음」입니다.
 *  `digits` 는 그 통화의 자릿수로, 모자라면 0 을 채웁니다. 더 긴 값은 자르지 않고
 *  담긴 그대로 적습니다 — 반올림해 적으면 실제로 걸린 한도와 다른 수가 섭니다. */
function limitShown(value: number | null, unit: string, digits: number | null = 0): string {
  if (value === null) return '걸지 않음'
  const text = value.toLocaleString('ko-KR', {
    minimumFractionDigits: digits ?? 0,
    maximumFractionDigits: 20,
  })
  return `${text}${unit}`
}

/* 계좌 손실 한도를 바꾸는 창.
 *
 * 칸은 **머리에 선 값**으로 채워 엽니다. 저장은 그 축의 두 시장을 함께 보내므로,
 * 손대지 않은 칸도 지금 값 그대로 실려 갑니다. 비운 칸은 「걸지 않음」입니다. 다른
 * 축은 보내지 않아 그대로입니다. */
function LimitsForm({
  axis,
  currencies,
  start,
  saving,
  onSaving,
  onClose,
}: {
  /** 고치는 계좌 축. 창을 열 때 정해 두고 바꾸지 않습니다. */
  axis: LimitAxis
  /** 머리 줄에 선 해외 통화(달러와, 한도·실행이 있는 통화). 창의 줄도 이것으로 엽니다. */
  currencies: string[]
  start: Limits
  saving: boolean
  onSaving: (saving: boolean) => void
  onClose: () => void
}) {
  /* 줄의 통화 — 국내(원) 다음 해외 통화들. 「통화 더하기」로 늘고, 늘린 줄은 저장 전까지
     이 창에만 있습니다. */
  const [codes, setCodes] = useState<string[]>(() => ['KRW', ...currencies])
  const [text, setText] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      ['KRW', ...currencies].map((code) => {
        const value = start[code] ?? null
        return [code, value === null ? '' : limitShown(value, '', currencyDigits(code))]
      }),
    ),
  )
  const [adding, setAdding] = useState(false)
  const timetable = useTimetable()
  /* 더할 수 있는 통화 — 시간표 품목의 통화 가운데 아직 줄이 없는 것. */
  const addable = useMemo(
    () => overseasCurrencies().filter((code) => !codes.includes(code)),
    // 시간표가 오면 다시 셉니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [codes, timetable],
  )
  /* 서버가 거절한 까닭. 칸을 짚은 말은 그 칸 아래, 나머지는 창 아래입니다.
     칸을 고치면 그 칸의 서버 말은 걷습니다 — 고친 값에 대한 답이 아닙니다. */
  const [said, setSaid] = useState<{ fields: Partial<Record<string, string>>; message: string | null }>({
    fields: {},
    message: null,
  })
  const bad = Object.fromEntries(codes.map((code) => [code, limitWhy(text[code] ?? '')]))
  const invalid = codes.some((code) => bad[code] !== null)

  async function save() {
    if (invalid || saving) return
    onSaving(true)
    setSaid({ fields: {}, message: null })
    /* 그 축의 통화 전부를 보냅니다 — 안 보낸 통화는 서버가 「안 건 것」으로 지웁니다.
       창에 줄이 없는 통화도 걸려 있던 값 그대로 실어 풀리지 않게 합니다. */
    const values: Limits = { ...start }
    for (const code of codes) values[code] = limitValue(text[code] ?? '')
    const result = await saveLimits(values, axis)
    onSaving(false)
    if (result.ok) onClose()
    else setSaid({ fields: result.fields, message: result.message })
  }

  return (
    <form
      className="run-add"
      onSubmit={(e) => {
        e.preventDefault()
        void save()
      }}
    >
      {codes.map((code) => {
        const why = bad[code] ?? said.fields[code] ?? null
        const whyId = `run-limits-why-${code}`
        const won = code === 'KRW'
        return (
          <div key={code}>
            <label className="run-add-row">
              <span className="run-add-label">{won ? '국내' : `해외 ${code}`}</span>
              <span className="run-limits-unit">
                <input
                  className={`control run-num${why !== null ? ' is-bad' : ''}`}
                  value={text[code] ?? ''}
                  inputMode="decimal"
                  placeholder="걸지 않음"
                  disabled={saving}
                  aria-label={won ? '국내 하루 손실 한도' : `해외 ${code} 하루 손실 한도`}
                  aria-invalid={why !== null || undefined}
                  aria-describedby={why !== null ? whyId : undefined}
                  onChange={(e) => {
                    const next = limitTyped(e.target.value, currencyDigits(code) ?? 2)
                    setText((now) => ({ ...now, [code]: next }))
                    setSaid((now) => ({ ...now, fields: { ...now.fields, [code]: undefined } }))
                  }}
                />
                <span className="set-unit-mark">{won ? '원' : code}</span>
              </span>
            </label>
            {why !== null && (
              <p className="add-field-why" id={whyId}>
                {why}
              </p>
            )}
          </div>
        )
      })}
      {/* 통화 더하기 — 시간표 품목의 통화 가운데 고릅니다. 고르면 그 줄이 섭니다. */}
      {addable.length > 0 &&
        (adding ? (
          <label className="run-add-row">
            <span className="run-add-label">통화</span>
            <select
              className="control"
              value=""
              aria-label="더할 통화"
              disabled={saving}
              onChange={(e) => {
                const code = e.target.value
                if (!code) return
                setCodes((now) => [...now, code])
                setText((now) => ({ ...now, [code]: '' }))
                setAdding(false)
              }}
            >
              <option value="">고르기</option>
              {addable.map((code) => (
                <option key={code} value={code}>
                  {code}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <button type="button" className="run-limits-add" disabled={saving} onClick={() => setAdding(true)}>
            통화 더하기
          </button>
        ))}
      <p className="run-limits-hint">
        하루 손실이 이만큼에 닿으면 그 통화로 셈하는 {axis === 'real' ? '실전' : '모의'} 계좌 실행이 모두 멈춥니다.
        비우면 걸지 않습니다
      </p>
      {said.message !== null && <p className="run-limits-fail">{said.message}</p>}
      <div className="run-add-acts">
        <button type="button" className="btn btn-quiet" aria-disabled={saving} onClick={() => !saving && onClose()}>
          그만두기
        </button>
        <button type="submit" className="btn btn-primary" aria-disabled={invalid || saving}>
          {saving ? '저장하는 중' : '저장'}
        </button>
      </div>
    </form>
  )
}

/* 거래 추가 — 마지막에 **모의/실전 계좌·실제 계약·수량·청산 감시 방식**을
 * 다시 보여 주고 시작합니다(원본 §7).
 *
 * 계좌는 읽기만 합니다. 계좌번호·비밀번호를 새로 받는 자리를 만들지 않고
 * 설정에 있는 것을 씁니다. */
/** 고른 버전을 저장하는 중일 때의 까닭. 목록의 저장 잠금과 같은 말입니다. */
const SAVING_WHY = '저장하는 중입니다'

function RunAddForm({
  rows,
  savingId,
  seed,
  why,
  ask,
  askable,
  onAsk,
  onBack,
  onCancel,
  onStarted,
}: {
  /** 고를 수 있는 전략. 목록과 같은 것을 씁니다. */
  rows: StrategyVersion[]
  /** 지금 서버에 저장하는 중인 버전 id. 고른 버전이 이것이면 시작을 잠급니다 — 그
   *  몇 초 동안 시작하면 서버가 아직 담지 않은 버전으로 실행을 세우게 됩니다. */
  savingId: string | null
  /** 목록에서 들고 온 전략·버전. */
  seed: OpenRequest | null
  /** 서버가 시작을 막은 까닭. **서버 문장 그대로**입니다 — 화면이 같은 검사를
   *  다시 하면 둘이 갈립니다. */
  why: string | null
  /** 확인 얼굴이 고정한 갈래·환경. `null` 이면 폼 얼굴입니다. **창은 하나**이고
   *  얼굴만 바뀝니다. */
  ask: AskFixed | null
  /** 지금 세울 수 있는 계좌 갈래. 모르면 `null` 이고 확인 얼굴로 안 넘어갑니다. */
  askable: AccountMode | null
  onAsk: () => void
  onBack: () => void
  onCancel: () => void
  onStarted: () => void
}) {
  const names = [...new Set(rows.map((row) => row.name))]
  const [strategy, setStrategy] = useState(seed?.strategy || (names[0] ?? ''))
  const versions = rows.filter((row) => row.name === strategy).map((row) => row.version)
  const [version, setVersion] = useState(seed?.version || (versions[0] ?? ''))
  /* 창이 새로 열리면 앞 창에서 서버가 막은 까닭을 지웁니다 — 남겨 두면 아직
     누르지도 않은 이번 시작이 막힌 것으로 읽힙니다. 그리기 전에 지워 옛 글이
     한 번도 비치지 않게 합니다. 폼과 확인 얼굴은 한 창이라 얼굴을 오갈 때는
     지우지 않습니다. */
  useLayoutEffect(() => {
    patchVerify({ addWhy: null })
  }, [])
  const [qty, setQty] = useState('1')
  const [fee, setFee] = useState('0')
  /* 실행 자금. **계좌의 돈이 아닙니다** — 이 실행의 손익과 묶인 증거금을 세는
     기준이고, 서버가 0 보다 큰 수를 요구합니다. 검증 탭과 **같은 서버 칸**
     (`cash`)이라 낱말도 같습니다 — 한 사실에 두 낱말을 두면 둘이 다른 값으로
     읽힙니다. */
  const [cash, setCash] = useState('50000000')
  /* 사용자가 자금 칸을 고쳤는지. 고친 값은 통화가 바뀌어도 덮지 않습니다. */
  const [cashTouched, setCashTouched] = useState(false)
  const [sending, setSending] = useState(false)
  /* 확인 얼굴의 첫 초점. **창이 이미 떠 있는 채로 얼굴만 바뀌므로** 창이
     잡아 주는 초점이 다시 돌지 않습니다 — 직접 옮기지 않으면 눌렸던 단추가
     사라진 자리에 초점이 남아 문서 맨 앞으로 튑니다. */
  const backRef = useRef<HTMLButtonElement>(null)
  const asking = ask !== null
  useEffect(() => {
    if (asking) backRef.current?.focus()
  }, [asking])

  const row = rows.find((item) => item.name === strategy && item.version === version)
    ?? rows.find((item) => item.name === strategy)
  /* 이 실행이 붙을 종목. **품목은 전략이 정합니다** — 그것을 바꾸면 다른
     전략입니다. 바꿀 수 있는 것은 **월물**뿐이고, 비워 두면 전략이 정한
     것(「근월 자동」이면 오늘의 근월)입니다. */
  const [month, setMonth] = useState('')
  const product = row ? productOfVersion(row) : null
  const months = useMemo(
    () => (product && row ? contractsOf(product, row.productKind) : []),
    [product, row],
  )
  /* 고른 월물이 지금 품목의 월물 목록에 없으면 비웁니다 — 다른 품목의 월물이 남으면
     그 달의 다른 종목으로 시작 요청이 나갑니다. 목록에 있는 값은 그대로 둡니다. */
  useEffect(() => {
    if (month && !months.some((item) => item.code === month)) setMonth('')
  }, [month, months])
  const code = month || (row ? codeOfVersion(row) : '')
  const instrument = code ? (resolve(code)?.name ?? code) : ''
  /* 세션도 그 전략의 시장을 따릅니다 — 해외 전략에 국내 세션을 세우면 고를 수
     없는 조합이 만들어집니다. */
  const market = row?.market ?? 'domestic'
  const sessions = sessionLinesFor(market)
  /* 이 실행의 통화 — 전략의 품목이 정합니다(해외는 품목마다 다릅니다). 자금·수수료 칸과
     확인창 금액이 이 통화이고, 자금 기본값도 이 통화로 섭니다(`cashDefaultOf`, 검증 추가
     창과 같은 표). 표에 없는 통화는 칸을 비우고, 사용자가 고친 값은 덮지 않습니다. */
  const currency = useStrategyCurrency(row ?? null)
  useEffect(() => {
    if (cashTouched) return
    const unit = currencyCode(currency)
    if (unit) setCash(cashDefaultOf(unit) ?? '')
  }, [currency, cashTouched])
  const unitCode = currencyCode(currency)
  const noCashDefault = cash === '' && unitCode !== '' && cashDefaultOf(unitCode) === null
  const unitTail = unitCode ? `(${unitCode === 'KRW' ? '원' : unitCode})` : ''
  /* 해외는 계약당 증거금을 미리 알 수 없어(거래소가 셈함) 자금과 견주지 않습니다 —
     그 사실을 실행 자금 줄 아래 한 줄로 말합니다. */
  const marginUnknown = market === 'overseas'
  /* 옵션을 **팔고 들어가는** 전략(국내·해외) — 손실이 실행 자금을 넘을 수 있어 승인 문장
     바로 위에 따로 알립니다(막지는 않음).
     판정과 글은 서버 규칙의 거울 하나입니다(`optionSellWarning` — 시장으로 글만 가름). */
  const optionSell = row ? optionSellWarning(market, row.productKind, savedOf(row.id)?.rules) : null
  /* 앱이 보는 청산 기준입니다. **담긴 설정이 답합니다** — 못 박아 두면 설정을
     고쳐도 확인창이 옛 값을 설명합니다. */
  const draft = row ? savedOf(row.id) : null
  /* 수량 기본값은 **그 버전 설정의 주문당**입니다. 창을 열 때, 전략·버전을 바꿀 때,
     담긴 설정이 늦게 도착했을 때 다시 정합니다. 같은 버전에서 사용자가 고친 값은
     그대로 둡니다 — 버전을 바꾸면 그 버전의 값으로 갑니다. */
  const perOrder = perOrderOf(draft?.aux)
  const qtyFor = useRef<string | null>(null)
  const qtyTouched = useRef(false)
  useEffect(() => {
    const id = row?.id ?? null
    if (qtyFor.current === id && qtyTouched.current) return
    qtyFor.current = id
    qtyTouched.current = false
    setQty(String(perOrder ?? 1))
  }, [row?.id, perOrder])
  /* 세션 기본값은 **그 전략·버전에 담긴 세션**입니다(검증 추가 창과 같은 규칙).
     창을 열 때, 전략·버전을 바꿀 때, 담긴 설정이 늦게 도착했을 때 다시 정하고, 그
     사이 사용자가 고른 값은 그대로 둡니다. */
  const savedKey = sessionKeyOf(market, draft?.aux.session)
  const [session, setSession] = useState<string>(savedKey)
  useEffect(() => {
    setSession(savedKey)
  }, [row?.id, savedKey])
  const watch = draft?.aux

  /* 해외 품목도 계좌 실행을 엽니다. 막는 거래소(서버가 정함)는 미리 막지 않고 시작한
     뒤 서버 문장을 그대로 적습니다 — 화면이 같은 표를 또 두면 둘이 갈립니다. 접속
     환경을 아직 확인하지 못했으면 어느 계좌로 나갈지 말할 수 없어 확인 얼굴로 넘어가지
     않습니다. */
  /* 세 칸의 판정. 틀린 칸은 붉은 테와 칸 아래 문장이 서고 시작이 막힙니다. */
  const bad = runAddWhy({ qty, cash, fee })
  const inputBad = bad.qty !== null || bad.cash !== null || bad.fee !== null
  /* 고른 버전을 저장하는 중인지. 고른 것은 바꾸지 않고 시작만 잠급니다 — 말없이
     다른 버전으로 바꾸면 고른 적 없는 전략이 시작됩니다. */
  const rowSaving = row !== undefined && row.id === savingId
  const blocked =
    !row || !draft
      ? '담긴 설정이 없어 시작할 수 없습니다'
      : rowSaving
        ? SAVING_WHY
        : code === ''
        ? '이 전략의 종목을 종목 목록에서 찾지 못했습니다'
        : askable === null
          ? ENV_WAIT
          : null

  async function start() {
    if (!row || !draft || sending || ask === null || rowSaving) return
    setSending(true)
    const ok = await addRun({
      id: `run-${Date.now()}`,
      versionId: row.id,
      draft,
      market,
      code,
      session,
      /* 판정을 지난 값만 여기 옵니다(`runAddWhy`) — 그대로 수로 바꿉니다. */
      qty: Number(qty),
      cash: Number(cash),
      feePerContract: Number(fee),
      /* 확인 얼굴이 고정한 갈래와 환경 — 창에 보인 그대로 보냅니다. */
      mode: ask.mode,
      environment: ask.environment,
      /* **확인창을 지났다는 표지.** 서버는 이것이 없으면 한 건도 안 냅니다.
         시각은 안 보냅니다 — 서버가 제 시계로 찍습니다. */
      approved: true,
    })
    setSending(false)
    if (ok) onStarted()
  }

  const pickStrategy = (name: string) => {
    /* 고른 것이 바뀌면 앞 시작 요청에 서버가 단 말은 이 고른 것의 답이 아닙니다. */
    patchVerify({ addWhy: null })
    setStrategy(name)
    const first = rows.find((item) => item.name === name)
    setVersion(first?.version ?? '')
    /* 전략을 바꾸면 골라 둔 월물은 앞 품목의 것입니다. */
    setMonth('')
  }

  const field = (label: string, node: React.ReactNode, why: string | null = null) => (
    <div key={label}>
      <label className="run-add-row">
        <span className="run-add-label">{label}</span>
        {node}
      </label>
      {/* 안 채운 칸(기본값 없는 통화의 자금)은 경고색, 틀린 값은 오류색입니다. */}
      {why !== null && <p className={`add-field-why${why === NO_CASH_DEFAULT ? ' is-missing' : ''}`}>{why}</p>}
    </div>
  )

  /* 확인 얼굴. **패널과 같은 줄들**을 쓰고 계좌 한 줄을 앞에 답니다 —
     둘이 갈리면 확인창이 패널과 다른 주문을 설명하게 됩니다. */
  if (ask !== null) {
    const text = ASK_TEXT[ask.mode]
    return (
      <div className="run-add">
        <div className="run-final">
          {/* 계좌 칸은 **배지**입니다. 굵은 글자로 두면 아래 문장의 굵은 글자와
              한 창에서 두 뜻이 됩니다 — 굵은 글자는 「실제 주문이 나간다」 한
              곳에만 씁니다. 검증의 시작 확인창과 같은 얼굴입니다. */}
          <div className="run-confirm-row">
            <span>계좌</span>
            <RunKindBadge kind={ask.mode} short />
          </div>
          {finalRows({ session, instrument, qty, cash, fee, watch, bad, currency, marginUnknown })}
        </div>
        {/* 해외 옵션 매도 — 승인 문장 바로 위 한 줄입니다. 막지 않고 알립니다. */}
        {optionSell && (
          <p className="run-option-sell">
            <span className="badge badge-warn">옵션 매도</span>
            {optionSell}
          </p>
        )}
        {/* **한 줄입니다.** 뒤에 한 문장을 더 달면 무거운 쪽이 둘로 갈려,
            읽는 사람이 어느 쪽이 이 창의 말인지 고르게 됩니다. */}
        {/* 실전 계좌 갈래에서는 굵은 조각만 경고색입니다 — 이 창에서 경고색은
            이 한 조각뿐입니다. */}
        <p className="run-approve">
          승인하면 <b className={ask.mode === 'real' ? 'run-approve-real' : undefined}>{text.approve}</b>
        </p>
        <div className="run-add-acts">
          <button ref={backRef} type="button" className="btn btn-quiet" onClick={onBack}>
            그만두기
          </button>
          {/* 서버가 시작을 막았으면(막는 거래소 등) 같은 것을 다시 보내도 같은 답이라
              승인 단추를 잠급니다. 그만두기로 돌아가 전략·월물을 바꾸면 풀립니다. */}
          <button
            type="button"
            className="btn btn-heavy"
            aria-disabled={sending || why !== null || rowSaving}
            title={why ?? (rowSaving ? SAVING_WHY : undefined)}
            onClick={() => !sending && why === null && !rowSaving && void start()}
          >
            {text.button}
          </button>
        </div>
        {/* 서버가 시작을 막은 문장(막는 거래소 등)은 오류색입니다. */}
        <p className={`run-hint run-start-why${why ? ' is-error' : ''}`}>{why ?? (rowSaving ? SAVING_WHY : '')}</p>
      </div>
    )
  }

  return (
    <div className="run-add">
      {field(
        '전략',
        <select
          className="control"
          value={strategy}
          onChange={(e) => pickStrategy(e.target.value)}
        >
          {names.map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>,
      )}
      {field(
        '버전',
        <select className="control" value={version} onChange={(e) => {
            patchVerify({ addWhy: null })
            setVersion(e.target.value)
            /* 버전이 바뀌면 월물은 「전략이 정한 것」으로 — 버전마다 품목이 다를 수
               있습니다. */
            setMonth('')
          }}>
          {versions.map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>,
      )}
      {/* 종목은 **품목이 정하고 월물만 고릅니다.** 품목 칸을 여기 두면 전략이
          말하는 종목과 다른 종목으로 도는 실행이 생깁니다(규격 §1-1). */}
      {field('종목', <span className="run-add-fixed">{instrument || '—'}</span>)}
      {field(
        '월물',
        <select
          className="control"
          value={month}
          aria-label="월물"
          onChange={(e) => {
            patchVerify({ addWhy: null })
            setMonth(e.target.value)
          }}
        >
          {/* 여기에 풀린 종목을 덧붙이지 않습니다 — 윈 줄의 「종목」이 지금 고른
              것이 무엇으로 풀리는지를 이미 보여 줍니다. 덧붙이면 특정 월물을 골랐을 때
              이 줄이 그 월물 이름을 달아, 「전략이 정한 것」이 아닌 것을 그렇게 말합니다. */}
          <option value="">전략이 정한 것</option>
          {months.map((item) => (
            <option key={item.code} value={item.code}>
              {item.label}
            </option>
          ))}
        </select>,
      )}
      {field(
        '세션',
        <select
          className="control"
          value={session}
          /* 고른 줄에서 키를 되찾습니다 — `e.target.value` 는 그냥 글자라
             그대로 담으면 서버가 못 읽는 값도 들어갑니다. */
          onChange={(e) => {
            const found = sessions.find((item) => item.key === e.target.value)
            if (found) setSession(found.key)
          }}
        >
          {sessions.map((item) => (
            <option key={item.key} value={item.key}>
              {item.label}
            </option>
          ))}
        </select>,
      )}
      {field(
        '주문당 수량',
        <input
          className={`control run-num${bad.qty !== null ? ' is-bad' : ''}`}
          value={qty}
          inputMode="numeric"
          aria-invalid={bad.qty !== null}
          onChange={(e) => {
            qtyTouched.current = true
            setQty(e.target.value)
          }}
        />,
        bad.qty,
      )}
      {/* 설정과 다르게 고쳤을 때만 — 틀린 값이면 위 오류 줄이 말합니다. */}
      {perOrder !== null && bad.qty === null && Number(qty) !== perOrder && (
        <p className="vrf-funds-dim">{perOrderNote(perOrder)}</p>
      )}
      {field(
        `실행 자금${unitTail}`,
        <input
          className={`control run-num${noCashDefault ? ' is-missing' : bad.cash !== null ? ' is-bad' : ''}`}
          value={moneyText(cash)}
          inputMode="numeric"
          aria-invalid={bad.cash !== null}
          onChange={(e) => {
            setCashTouched(true)
            setCash(moneyDigits(e.target.value))
          }}
        />,
        noCashDefault ? NO_CASH_DEFAULT : bad.cash,
      )}
      {field(
        `계약당 수수료${unitTail}`,
        <input
          className={`control run-num${bad.fee !== null ? ' is-bad' : ''}`}
          value={moneyText(fee)}
          inputMode="numeric"
          aria-invalid={bad.fee !== null}
          onChange={(e) => setFee(moneyDigits(e.target.value))}
        />,
        bad.fee,
      )}

      <div className="run-final">
        <p className="run-final-title">시작하면 이렇게 나갑니다</p>
        {finalRows({ session, instrument, qty, cash, fee, watch, bad, currency, marginUnknown })}
      </div>

      <div className="run-add-acts">
        <button type="button" className="btn btn-quiet" onClick={onCancel}>
          그만두기
        </button>
        {/* 누르면 곧바로 나가지 않고 **확인 얼굴이 한 번 섭니다.** 그 얼굴을
            지난 표지가 없으면 서버가 한 건도 내지 않습니다. */}
        <button
          type="button"
          className="btn btn-primary"
          aria-disabled={blocked !== null || inputBad}
          aria-describedby={blocked === null ? undefined : 'run-start-why'}
          onClick={() => blocked === null && !inputBad && onAsk()}
        >
          거래 시작
        </button>
      </div>
      <p id="run-start-why" className={`run-hint run-start-why${blocked === null && why ? ' is-error' : ''}`}>
        {blocked ?? why ?? ''}
      </p>
    </div>
  )
}

/** 「이렇게 나갑니다」의 줄들. **패널과 확인창이 같은 것을 씁니다** — 둘이
 *  갈리면 확인창이 패널과 다른 주문을 설명하게 됩니다. */
function finalRows({
  session,
  instrument,
  qty,
  cash,
  fee,
  watch,
  bad,
  currency,
  marginUnknown,
}: {
  session: string
  instrument: string
  qty: string
  cash: string
  fee: string
  watch: Partial<Aux> | undefined
  /** 금액의 통화. 그 전략 품목의 것입니다. */
  currency: string
  /** 계약당 증거금을 몰라 자금과 견주지 않는 실행(해외)인지. */
  marginUnknown: boolean
  /** 칸 판정(`runAddWhy`). 틀린 칸의 값은 「—」로 섭니다 — 틀린 값을 되묻지 않습니다. */
  bad: ReturnType<typeof runAddWhy>
}) {
  return (
    <>
      <div className="run-confirm-row">
        <span>실제 계약</span>
        <b>{instrument || <span className="dead">—</span>}</b>
      </div>
      <div className="run-confirm-row">
        <span>세션</span>
        <b>{sessionLabelOf(session)}</b>
      </div>
      <div className="run-confirm-row">
        <span>수량</span>
        <b>{bad.qty === null ? `주문당 ${qty}계약` : '—'}</b>
      </div>
      {/* 손절·익절은 **담긴 설정**입니다. 못 박아 두면 설정을 고쳐도 확인창이
          옛 값을 설명합니다. **한 줄입니다** — 셋은 「이 실행이 어떻게 빠져
          나오나」 하나를 말하는 값이라, 줄로 나누면 나란히 선 다른 칸들과
          같은 무게가 됩니다. 앱이 보는 값이라 「앱 감시」를 함께 적습니다:
          앱이 꺼지면 이쪽은 멈춥니다. */}
      <div className="run-confirm-row">
        <span>청산 감시</span>
        <b>
          {watchLine(watch)} · 앱 감시
        </b>
      </div>
      {/* 계좌의 돈이 아니라 **이 실행의 장부 기준**입니다. 손익과 묶인
          증거금을 이 값으로 셉니다 — 적어 놓고 안 보여 주면 무엇으로 세는지
          모르는 채 시작하게 됩니다. */}
      <div className="run-confirm-row">
        <span>실행 자금</span>
        <b>{bad.cash === null ? moneyIn(Number(cash), currency) : '—'}</b>
      </div>
      {marginUnknown && <p className="vrf-funds-dim">{FUNDS_UNKNOWN}</p>}
      <div className="run-confirm-row">
        <span title={FEE_ASSUMED}>
          수수료<span className="fee-assumed"> (가정)</span>
        </span>
        <b>{bad.fee === null ? `계약당 ${moneyIn(Number(fee), currency)}` : '—'}</b>
      </div>
    </>
  )
}
