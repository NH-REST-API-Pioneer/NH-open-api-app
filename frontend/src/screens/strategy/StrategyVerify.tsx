import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { contractsOf, resolve, spreadShortName } from '../../data/instruments'
import { useQuote } from '../../data/instrumentQuote'
import { domesticContextOf } from '../../data/session'
import { useWishes, type Wish } from '../../data/stream'
import type { MarketContext } from '../../lib/types'
import {
  runCurrencyOf,
  NO_CASH_DEFAULT,
  cashDefaultOf,
  isPaperRun,
  tradingOf,
  CONFIRM_TEXT,
  FUNDS_SHORT,
  FUNDS_UNKNOWN,
  perOrderNote,
  perOrderOf,
  LEGACY_UNSENT_TITLE,
  isRejectedEvent,
  isUnsent,
  legacyUnsentWhy,
  fillKey,
  isTickRun,
  tickBarOf,
  fundsVerdict,
  marginBasisWord,
  marginKnown,
  reasonWord,
  attentionEndWhy,
  runFunds,
  sendEach,
  streakText,
  type FeedState,
  type FundsVerdict,
  type VerifyFill,
  type VerifyOrder,
  type VerifyRun,
} from '../../data/strategyRuns'
import {
  codeOfVersion,
  currencyOf,
  productOfVersion,
  useStrategyCurrency,
  type StrategyVersion,
} from '../../data/strategyList'
import { sessionKeyOf, sessionLabelOf, sessionLinesFor } from '../../data/strategyRules'
import { watchLine } from '../../data/ruleSummary'
import { useProductInfo } from '../../data/productInfo'
import {
  actOnRun,
  addRun,
  deleteRun,
  loadRunSnapshot,
  refreshConditions,
  loadRuns,
  patchVerify,
  savedOf,
  seedFromSelection,
  snapshotOf,
  stopAllRuns,
  storeNote,
  useStrategyState,
  type OpenRequest,
} from '../../data/strategyStore'
import { kstClock, kstClockSeconds } from '../../lib/kst'
import { TickBadge } from './TickBadge'
import { Num, NumOrDash, currencyCode, moneyDigits, moneyIn, moneyText, toneOf } from '../../lib/number'
import { Modal } from '../../app/Modal'
import { runAddWhy } from '../../data/strategyChecks'
import { ChartPanel } from '../trade/ChartPanel'
import { type TradeMark } from '../trade/chartMarks'
import { MarkPopover, type MarkPick } from './MarkPopover'
import { ConditionTable } from './ConditionTable'
import { PICK_HINT, RunStats, runNameOf, targetLine, targetsOf } from './runStats'
import { ruleBottomOrder, ruleIndicators } from './ruleIndicators'
import { ENGINE_MACD } from './engineIndicators'
import type { IndicatorSetting, IndicatorSettings } from '../trade/chartIndicators'
import { barHolding, mergeMarks } from './markSeat'
import { RUN_KIND_LABEL, RunKindBadge } from './runKind'
import type { SlotState } from '../trade/chartSlots'

/* 전략 검증 — 왼쪽 실행 목록, 가운데 큰 차트, 아래 표.
 *
 * **여기 서는 실행이 종이 하나는 아닙니다.** 모의 계좌로 도는 실행도 이 목록에
 * 함께 섭니다 — 진행 화면에는 차트가 없어, 모의 실행의 봉과 체결을 보는 자리가
 * 여기뿐입니다. 그래서 「앱 시뮬레이션」이라고 못 박지 않고 **고른 실행의 갈래가**
 * 머리 배지와 낱말을 정합니다(모의면 진행 화면과 같은 「모의 계좌」 배지).
 *
 * 모드를 고르는 자리는 여기 없습니다 — 실행을 세울 때 정해집니다. **이 화면에
 * 주문 단추는 없지만, 여기 선 모의 실행은 계좌로 주문을 냅니다** — 그 실행을
 * 세우고 승인하는 자리가 진행 화면일 뿐입니다.
 *
 * 오른쪽에 계산 카드를 늘어놓지 않습니다. 이 화면에서 읽는 것은 「어디서
 * 사고팔았는가」이고 그것은 차트 폭이 넓을수록 잘 읽힙니다 — 상세는 필요할
 * 때 열고 닫습니다.
 */

/** 시세 자리가 모자랄 때 남을 순서. 주문 대상(9)과 홈 관심종목(3) 사이입니다 —
 *  이 값으로 주문을 내지는 않지만, 멈추면 지금 도는 검증의 근거가 낡습니다. */
const VERIFY_RANK = 5

/** 아래 탭. **「가상」을 안 붙입니다** — 이 목록에는 종이 실행과 모의 계좌 실행이
 *  함께 서고, 모의 계좌 체결은 실제로 계좌에서 난 것이라 「가상」이 거짓말입니다.
 *  탭은 자리 이름이라 고른 실행에 따라 글자가 바뀌면 같은 자리를 다른 이름으로
 *  기억하게 됩니다 — 무엇의 체결인지는 줄과 머리가 말합니다. */
const BOTTOM_TABS = ['조건', '체결', '미체결', '이벤트'] as const

/** 아래 표의 한 줄. 두 탭이 한 표를 쓰므로 **그리기 전에 한 꼴로 맞춥니다.**
 *  수량 칸에 무엇이 들어가는지는 탭이 정하고(체결은 채워진 수량, 미체결은 남은
 *  수량), 그린 뒤에는 갈래를 다시 보지 않습니다. */
interface TableRow {
  key: string
  time: number
  side: 'buy' | 'sell'
  intent: 'entry' | 'exit'
  reason: string
  price: number | null
  amount: number
  /** 봉이 끝나기 전에 규칙 판정으로 난 줄이면 그 봉의 시작 시각(모르면 `null`),
   *  아니면 `undefined` 입니다(`tickBarOf`). */
  tick: number | null | undefined
}
type BottomTab = (typeof BOTTOM_TABS)[number]

/* 시세가 붙어 있을 때는 색을 쓰지 않습니다. 늘 켜져 있는 초록은 이상이 생겨도
 * 눈에 띄지 않고, 이 앱에서 색은 값의 방향이 갖습니다. */
const FEED_TONE: Record<FeedState, string> = {
  idle: 'vrf-dot',
  live: 'vrf-dot',
  gap: 'vrf-dot is-warn',
}

/** 시세가 어떤 자리인지 적는 말. `idle` 은 아직 안 붙은 것이고 `gap` 은 오다가
 *  끊긴 것이라 서로 다릅니다. */
const FEED_LABEL: Record<FeedState, string> = {
  idle: '아직 안 붙음',
  live: '정상',
  gap: '끊김',
}

/** 실행에 거는 동작. **모두 확인 창을 지납니다** — 여러 실행을 한 번에 고르므로
 *  무엇에 걸리고 무엇이 빠지는지를 창이 먼저 보입니다. 중지·재개도 그렇습니다. */
type Deed =
  | '선택 검증 중지'
  | '선택 검증 재개'
  | '선택 전략 청산'
  | '실행 종료'
  | '실행삭제'
  | '검증 신규 진입 중지'

/** 그 동작의 단추에 적는 말. 확인 창의 제목도 이것입니다. */
const DEED_LABEL: Record<Deed, string> = {
  '선택 검증 중지': '선택 검증 중지',
  '선택 검증 재개': '선택 검증 재개',
  '선택 전략 청산': '선택 전략 청산',
  '실행 종료': '실행 종료',
  실행삭제: '실행 삭제',
  '검증 신규 진입 중지': '검증 신규 진입 중지',
}

/** 중지·재개 한 단추 뒤에 단추가 서는 차례. 못 누르는 까닭 줄도 이 차례로 섭니다. */
const DEEDS: readonly Deed[] = ['선택 전략 청산', '실행 종료', '실행삭제', '검증 신규 진입 중지']

/** 실행 하나에 보내는 요청의 이름. 삭제와 전체 중지는 다른 길로 갑니다. */
const DEED_VERB: Partial<Record<Deed, 'stop' | 'resume' | 'close' | 'end'>> = {
  '선택 검증 중지': 'stop',
  '선택 검증 재개': 'resume',
  '선택 전략 청산': 'close',
  '실행 종료': 'end',
}

/** 그 동작을 가리키는 짧은 이름. **화면 글자가 아니라 코드가 읽는 이름**이라
 *  까닭 줄의 `id` 는 이것으로 섭니다 — 화면 글자를 id 로 쓰면 글자를 고칠 때
 *  단추와 까닭 줄을 잇는 줄이 끊깁니다. */
const DEED_KEY: Record<Deed, string> = {
  '선택 검증 중지': 'toggle',
  '선택 검증 재개': 'toggle',
  '선택 전략 청산': 'close',
  '실행 종료': 'end',
  실행삭제: 'drop',
  '검증 신규 진입 중지': 'stop-all',
}

/** 이벤트 한 줄의 글.
 *
 *  - 계좌가 거부한 주문(막힘 이벤트 가운데 까닭이 `rejected` 인 것): 앞에 오류색 배지
 *    「거부」를 달고 **서버 글 그대로**(거부 코드와 문구) 적습니다. 주문은 나갔고 계좌가
 *    받지 않은 것이라 「안 냄」이 아닙니다.
 *  - 「안 낸 신호」(그 밖의 막힘 이벤트): 앞에 경고 배지 「안 냄」을 달고
 *    **서버 글 그대로** 적습니다. 옛 기록의 글(옛 머리)도 원문 그대로 두고, 그 줄에만
 *    지금은 어떻게 적는지를 마우스에 답니다.
 *  - 「시작할 때 이미 참」: 중립 한 줄 — 이상이 아니라, 거짓이 됐다가 다시 참이 될
 *    때까지 기다린다는 알림입니다. 서버 글자는 규칙 이름입니다.
 *  - 그 밖은 서버 글자 그대로입니다. */
function EventText({ kind, reason, text }: { kind: string; reason?: string | null; text: string }) {
  if (isRejectedEvent({ kind, reason })) {
    return (
      <>
        <span className="badge vrf-event-badge vrf-event-badge-rejected">거부</span>
        <span>{text}</span>
      </>
    )
  }
  if (isUnsent({ kind, reason })) {
    const legacy = legacyUnsentWhy({ kind, text }) !== null
    return (
      <>
        <span className="badge badge-warn vrf-event-badge">안 냄</span>
        <span title={legacy ? LEGACY_UNSENT_TITLE : undefined}>{text}</span>
      </>
    )
  }
  if (kind === 'already-true') {
    return <>시작할 때 이미 참 — 다시 참으로 바뀔 때 냅니다 · {text}</>
  }
  return <>{text}</>
}

/** 실행 줄이 붙은 세션의 이름. **서버가 함께 준 글자가 먼저**이고, 없을 때만
 *  키에서 짓습니다 — 두 벌을 두면 서버 글자와 화면 글자가 갈립니다. */
function runSessionLabel(run: Pick<VerifyRun, 'session' | 'sessionLabel'>): string {
  return run.sessionLabel || sessionLabelOf(run.session)
}

/** 자금 판정 한 줄 — 모자라면 경고와 그 셈, 모르면 흐린 한 줄, 넉넉하면 없음.
 *  검증 추가 창과 상세가 이것 하나로 적습니다. */
function FundsNote({ verdict, qty, currency }: { verdict: FundsVerdict; qty: number; currency: string }) {
  if (verdict.kind === 'enough') return null
  if (verdict.kind === 'unknown') return <p className="vrf-funds-dim">{FUNDS_UNKNOWN}</p>
  return (
    <>
      <p className="vrf-funds-warn">{FUNDS_SHORT}</p>
      <p className="vrf-funds-dim">
        (계약당 {moneyIn(verdict.each, currency)} × {qty}계약 = {moneyIn(verdict.need, currency)})
      </p>
    </>
  )
}

/** 줄에 세우는 종목 이름. **홈 타일과 같은 규칙**입니다 — 스프레드는 두 만기를
 *  다 적으면 좁은 열에서 잘리므로 짧은 꼴로 적고, 그 밖에는 색인이 지어 준
 *  이름을 그대로 씁니다(`data/homeWatch.ts`). 색인에 없으면 코드입니다. */
function shortInstrument(code: string): string {
  const held = resolve(code)
  if (!held?.contract) return code
  return held.contract.kind === 'spread' && held.contract.legs
    ? spreadShortName(held.product.name, held.contract.legs)
    : held.name
}

/** 서버가 준 시각(ms)을 표에 적는 말(한국시각). **받은 값 그대로**의 시각입니다 —
 *  「몇 분 전」으로 적으면 같은 체결이 볼 때마다 다른 글자가 됩니다. 한 봉
 *  안에서 여러 번 체결되므로 초까지 적습니다. */
function clockOf(time: number): string {
  if (!time) return '—'
  return kstClockSeconds(time)
}

/** 줄 한 칸에 적는 시각. **분까지입니다** — 시세가 언제까지 왔는지는 분이면
 *  충분하고, 초까지 적으면 좁은 열에서 줄이 두 줄로 접힙니다. */
function minuteOf(time: number): string {
  if (!time) return '—'
  return kstClock(time)
}

export function StrategyVerify({ onOpenRun }: {
  /** 「거래 중 n — 진행에서 보기」를 눌렀을 때 — 진행 탭으로 건너가 그 계좌
   *  실행을 엽니다. 목록의 「거래 중 n」 배지와 같은 이동 길입니다. */
  onOpenRun: (runId: string) => void
}) {
  /* 실행 목록·고른 실행·「신호 · 주문도 표시」는 **화면 밖**에 있습니다. 탭을
     옮겼다 와도, 상단에서 다른 페이지에 갔다 와도 검증은 계속 도는 것이어야
     합니다(원본 §2). 임시 자료로 시작한 실행과 「검증 추가」로 더한 실행을
     한 벌로 두는 것도 같은 이유입니다 — 따로 들면 중지·시작이 한쪽에만
     먹습니다. */
  const store = useStrategyState()
  const { runs, pickedId, checked, showDetail, add, pending, status, failure, acting, max } =
    store.verify
  /* 실행을 담아 둔 파일을 서버가 못 읽었을 때 실행 카드에 세울 한 줄. */
  const storeWhy = storeNote('runs', store.runStore)
  /* 그중 **못 읽은** 경우. 빈 목록이 「없다」고 말해도 되는지가 여기서 갈립니다. */
  const storeBroken = store.runStore?.status === 'broken'
  const setPickedId = (id: string) => patchVerify({ pickedId: id })
  const setShowDetail = (on: boolean) => patchVerify({ showDetail: on })
  const openPanel = add !== null
  const closePanel = () => patchVerify({ add: null })

  /* 화면에만 남는 것들입니다 — 어느 하단 탭을 보고 있었는지, 상세를 폈는지는
     다시 들어오면 처음 자리에서 시작해도 잃는 것이 없습니다. */
  /* 아래 탭. **조건이 첫 탭·기본**입니다 — 「왜 안 걸리나」가 이 화면에서 가장 먼저
     묻는 것이라서입니다. 실행을 바꿀 때 그 실행에 체결이 있으면 「체결」로 엽니다. */
  const [bottom, setBottom] = useState<BottomTab>('조건')
  /* 카드의 「안 낸 신호」를 눌러 고른 실행이면, 그 실행의 한 벌이 와도 탭을 바꾸지
     않고 이벤트에 둡니다. */
  const tabAsked = useRef<BottomTab | null>(null)
  const [markPick, setMarkPick] = useState<MarkPick | null>(null)
  const [open, setOpen] = useState({ fund: true, fill: true })
  const boxRef = useRef<HTMLDivElement>(null)
  /* 확인 창이 열려 있는 동작과, 마지막 요청이 막힌 까닭. 까닭은 **서버 문장
     그대로**입니다 — 화면이 다시 판정하면 서버와 갈립니다. */
  const [deed, setDeed] = useState<Deed | null>(null)
  const [why, setWhy] = useState<string | null>(null)
  /* 그 한 줄이 **경고**인지 — 검증 탭의 전체 중지가 계좌 실행까지 멈춘 경우입니다.
     막혀서 못 한 일과 달리 이미 일어난 일이라 흐린 글자로 두면 놓칩니다. */
  const [whyWarn, setWhyWarn] = useState(false)

  /* 돌고 있는 실행을 받아 옵니다. **화면이 태어날 때 한 번**입니다 — 그 뒤로는
     허브가 보내 주는 것으로 채웁니다(회차 ③-b). */
  useEffect(() => {
    void loadRuns()
  }, [])

  /* 목록에서 「검증 화면으로」로 들고 온 전략. **이미 도는 실행이 있으면 그것을
     고르고**, 없을 때만 추가 패널이 그 값으로 채워진 채 섭니다(원본 §2). */
  useEffect(() => {
    if (!pending) return
    const wanted = store.rows.find(
      (row) => row.name === pending.strategy && row.version === pending.version,
    )
    /* 찾는 것은 **그 버전의 종이 실행**입니다 — 계좌 실행은 이 탭이 보지 않습니다. */
    const found = wanted
      ? runs.find((run) => isPaperRun(run) && run.version === wanted.id)
      : undefined
    if (found) patchVerify({ pickedId: found.id, pending: null })
    else patchVerify({ add: pending, pending: null })
  }, [pending, runs, store.rows])

  /* 낮은 창에서는 상세 아코디언을 접은 채로 엽니다(규격 §2). 펴 둔 채로
     시작하면 왼쪽이 길어져 처음 보는 화면이 이미 굴러 있습니다. */
  useLayoutEffect(() => {
    const height = boxRef.current?.clientHeight ?? 0
    if (height > 0 && height < 600) setOpen({ fund: false, fill: false })
  }, [])
  const [slot, setSlot] = useState<SlotState>({ instrument: null, span: 'minute', indicators: null })
  /* 검증 차트에만 덮는 지표 — 실행마다 한 벌입니다. 처음은 **그 실행이 도는 규칙의
     지표**(`ruleIndicators`)이고, 보는 동안 끄고 켠 것은 그 실행에 한해 기억합니다.
     저장하지 않아 창을 닫으면 잊고, 일반주문 차트의 지표 구성은 그대로입니다. */
  const [layers, setLayers] = useState<Record<string, IndicatorSettings>>({})

  /* 이 탭이 보는 것은 **앱 시뮬레이션(종이) 실행**입니다. 계좌 실행(모의·실전)은
     주문이 계좌로 나가는 실행이라 진행 탭에서만 보고 다룹니다 — 「여기서 나가는
     주문은 없다」는 이 탭의 약속이 그래야 지켜집니다. 목록·고른 실행·셈·일괄
     대상이 모두 이 목록을 씁니다. */
  const all = runs.filter(isPaperRun)
  const picked = all.find((run) => run.id === pickedId) ?? all[0] ?? null
  /* 고른 실행의 한 벌. **그 실행의 칸만** 읽습니다 — 진행 탭이 다른 실행을 보고
     있어도 이 표는 고른 실행의 것입니다. */
  const snapshot = snapshotOf(store.verify, picked?.id)
  /* 「도는 중」은 **중지·종료가 아닌 것**입니다. 진입 주문 중·보유 중·청산
     요청은 다 도는 중입니다 — 상태 여덟을 접어 세는 자리라 접는 기준을 여기
     한 번만 둡니다.

     **중지와 종료를 가릅니다.** 중지는 다시 굴릴 수 있고 종료는 끝난 것이라,
     한 칸에 묶으면 「중지 3」을 보고 셋을 다시 굴릴 수 있다고 읽습니다.
     셋을 각각 세는 것도 그래서입니다 — 하나를 빼기로 구하면 그 칸이 「나머지
     전부」가 되어, 상태가 하나 늘어나는 날 그 실행들이 조용히 섞여 듭니다. */
  const running = all.filter((run) => run.state !== 'paused' && run.state !== 'ended').length
  const stopped = all.filter((run) => run.state === 'paused').length
  const ended = all.filter((run) => run.state === 'ended').length
  /* 동시 실행 상한은 **검증과 진행이 함께** 먹습니다. 그래서 머리의 「동시 실행」은
     서버 목록 전체에서 끝나지 않은 것을 세고, 이 탭의 것은 따로 적습니다. */
  const standing = runs.filter((run) => run.state !== 'ended').length
  const full = max > 0 && standing >= max
  const fullWhy = `동시 실행이 ${max}개라 더 세울 수 없습니다 — 진행 탭의 실행도 셉니다`
  /* 진행 탭에서 도는 계좌 실행. 링크가 여는 것은 그 첫째이고 **실전이 먼저**입니다 —
     계좌로 실제 돈이 걸린 쪽을 먼저 봐야 합니다. */
  const trading = tradingOf(runs)
  const tradingLink =
    trading.firstId === null ? null : (
      <button type="button" className="vrf-trading" onClick={() => onOpenRun(trading.firstId as string)}>
        {trading.hasReal && <RunKindBadge kind="real" short />}
        <span>
          거래 중 <span className="vrf-trading-n">{trading.count}</span> — 진행에서 보기
        </span>
      </button>
    )
  const openAdd = () => {
    if (!full) patchVerify({ add: seedFromSelection() })
  }

  /* 고른 실행의 한 벌. 목록과 따로 받습니다 — 체결·이벤트는 그 실행에만
     있습니다. 고른 줄이 바뀌면 그 줄의 것으로 다시 받습니다. */
  useEffect(() => {
    void loadRunSnapshot(picked?.id ?? '')
  }, [picked?.id])

  /* 실행을 바꾼 뒤 **그 실행의 한 벌이 처음 올 때** 탭을 정합니다 — 체결이 있으면
     「체결」, 없으면 「조건」입니다. 카드에서 이벤트를 청했으면 그대로 둡니다. */
  const openedFor = useRef('')
  useEffect(() => {
    const id = snapshot?.run.id ?? ''
    if (!id || openedFor.current === id) return
    openedFor.current = id
    const asked = tabAsked.current
    tabAsked.current = null
    setBottom(asked ?? ((snapshot?.fills.length ?? 0) > 0 ? '체결' : '조건'))
  }, [snapshot])

  /* 조건 표는 **허브 방송에 없습니다** — 고른 실행의 판정 봉이 바뀌면 그 실행의 표만
     한 번 다시 받습니다(봉당 한 번). 받는 중이면 겹쳐 내지 않고 다음 봉에 받습니다. */
  const conditionsFlying = useRef(false)
  const seenBar = useRef<{ id: string; bars: number | null } | null>(null)
  useEffect(() => {
    if (!picked) return
    const seen = seenBar.current
    seenBar.current = { id: picked.id, bars: picked.bars }
    if (!seen || seen.id !== picked.id || seen.bars === picked.bars) return
    if (conditionsFlying.current) return
    conditionsFlying.current = true
    void refreshConditions(picked.id).finally(() => {
      conditionsFlying.current = false
    })
  }, [picked?.id, picked?.bars])

  /* 검증 차트에 덮는 지표 한 벌. 그리는 쪽이 같은 참조면 다시 안 그리도록
     규칙·층이 바뀔 때만 새로 짓습니다. */
  const pickedRules = picked ? savedOf(picked.version)?.rules : undefined
  const rulePatch = useMemo(() => ruleIndicators(pickedRules), [pickedRules])
  /* 아래 칸은 **셋까지, 칸 높이 바닥 60** 입니다 — 조건이 쓰는 지표가 규칙 차례로
     먼저 자리를 받고, 남는 자리에 사용자가 켜 둔 지표가 섭니다. 자리를 못 받은 지표의
     값은 조건 표가 말합니다. */
  const ruleOrder = useMemo(() => ruleBottomOrder(pickedRules), [pickedRules])
  const paneCap = useMemo(() => ({ max: 3, floor: 60, order: ruleOrder }), [ruleOrder])
  const pickedLayer = picked ? layers[picked.id] : undefined
  /* 겹친 지표 범례를 펴 두었는지 — 실행마다 기억하고 저장하지 않습니다(지표 층과 같은 자리). */
  const [legendOpen, setLegendOpen] = useState<Record<string, boolean>>({})
  const pickedOpen = picked ? (legendOpen[picked.id] ?? false) : false
  const indicatorLayer = useMemo(
    () => ({
      bottom: paneCap,
      legendFold: {
        open: pickedOpen,
        onToggle: (open: boolean) => {
          if (picked) setLegendOpen((had) => ({ ...had, [picked.id]: open }))
        },
      },
      /* 도구줄 「MACD」는 이 차트에서 엔진 식 MACD 를 가리킵니다. */
      aliases: { MACD: ENGINE_MACD },
      patch: pickedLayer ?? rulePatch,
      onChange: (name: string, next: IndicatorSetting) => {
        if (!picked) return
        setLayers((had) => ({ ...had, [picked.id]: { ...(had[picked.id] ?? rulePatch), [name]: next } }))
      },
    }),
    [pickedLayer, rulePatch, picked, paneCap, pickedOpen],
  )

  /* 실행이 붙잡은 종목. **이름·자릿수는 색인이 답합니다** — 줄에 적어 두면
     만기가 넘어갈 때 이름과 실제 종목이 갈립니다. */
  const held = picked ? resolve(picked.code) : null
  const decimals = held?.product.decimals ?? 2
  /* 금액의 통화 — **그 실행이 도는 전략의 것**입니다. 해외인데 담긴 코드가 없으면
     품목정보의 통화이고, 전략을 목록에서 못 찾으면 실행의 시장이 정합니다. */
  const pickedRow = picked ? (store.rows.find((one) => one.id === picked.version) ?? null) : null
  const rowCurrency = useStrategyCurrency(pickedRow)
  const currency = pickedRow ? rowCurrency : picked ? currencyOf(picked.market, '') : ''
  /* 실행 줄의 통화. 줄마다 부르는 자리라 품목정보를 묻지 않습니다 — 해외는
     계약당 증거금을 몰라 자금 판정이 늘 「모름」이라 통화가 셈을 바꾸지 않습니다. */
  const runCurrency = (run: VerifyRun) =>
    runCurrencyOf(run, currencyOf(run.market, store.rows.find((one) => one.id === run.version)?.currency))
  /* 그 실행이 어느 전략의 것인가. **목록에서 찾습니다** — 실행 줄에 이름을
     적어 두면 전략 이름을 고칠 때 갈립니다. */
  const nameOf = (versionId: string) => runNameOf(store.rows, versionId, store.status === 'ready')

  /* 차트가 보는 종목은 **고른 실행의 종목**입니다. **화면 기본 종목의 값을
     빌려다 세우지 않습니다** — 그 숫자는 이 전략이 본 값이 아닌데 차트 머리에
     서면 이 전략의 값으로 읽힙니다. 고른 실행이 없으면 종목도 없어 차트를
     안 세웁니다.

     세우는 함수는 **일반주문과 같은 것**입니다(`data/instrumentQuote.ts`) —
     화면마다 제 나름으로 지으면 같은 종목이 화면에 따라 다른 이름·자릿수로
     섭니다. */
  const context: MarketContext =
    held?.market === 'overseas' ? 'overseas' : domesticContextOf(picked?.code ?? '')
  const { quote, entry } = useQuote(held, context, null, '')

  /* 이 화면이 보고 있는 것. **고른 실행의 종목 하나**입니다 — 목록의 다른
     실행은 줄만 서고 차트를 그리지 않습니다. 이 선언이 없으면 조회로 받은
     봉만 서고 실시간으로 자라지 않아, 체결이 나도 그 봉이 차트에 없습니다. */
  const wishes = useMemo<Wish[]>(() => {
    const code = picked?.code ?? ''
    if (!code) return []
    return [
      { context, kind: 'quote', sym: code, priority: VERIFY_RANK },
      { context, kind: 'book', sym: code, priority: VERIFY_RANK },
    ]
  }, [picked?.code, context])
  useWishes('strategy-verify', wishes)

  /* 체결이 앉을 봉. **차트가 실제로 그리는 봉**입니다 — 분봉은 조회 봉 뒤에
     체결로 접은 봉을 잇고, 일봉은 조회 봉뿐입니다(`ChartView` 와 같은 벌).
     값을 따로 세우면 표가 봉이 없는 허공에 뜹니다(원본 §8: 체결 시간을 실제
     봉에 매핑한다). */
  const bars = useMemo(
    () => (slot.span === 'minute' ? [...(entry.bars ?? []), ...entry.live] : (entry.daily ?? [])),
    [entry.bars, entry.live, entry.daily, slot.span],
  )

  /* 차트에 얹을 표. **고른 실행의 것만** 세우고, 갈래를 여기서 거릅니다 —
     차트는 이미 묶인 점만 받습니다(원본 §8). 체결은 **시각으로** 봉을 찾습니다
     — 「몇 봉 전」으로 세면 분봉과 일봉이 서로 다른 봉을 가리켜, 봉 종류를
     바꿀 때마다 같은 체결이 다른 자리로 옮겨 갑니다. 그 시각을 덮는 봉이
     없으면 표를 안 세웁니다. */
  const marks = useMemo<TradeMark[]>(() => {
    if (!picked || !snapshot) return []
    const said = nameOf(picked.version)
    const seated: TradeMark[] = []
    for (const fill of snapshot.fills) {
      const bar = barHolding(bars, fill.time, slot.span)
      if (!bar) continue
      seated.push({
        /* 아래 표와 같은 열쇠입니다. **묶이기 전 값입니다** — 바로 아래
           `mergeMarks` 가 같은 봉·같은 방향의 체결을 표지 하나로 묶고, 남는
           열쇠는 그중 앞선 체결의 것입니다. 묶인 표지에서 뒷줄을 되찾을 수는
           없습니다. */
        id: fillKey(fill),
        kind: 'fill',
        time: bar.timestamp,
        price: fill.price,
        /* 묶인 표지의 평균가를 반올림할 자릿수이자 팝오버가 적을 자릿수입니다 —
           표와 같은 값을 씁니다. */
        decimals,
        side: fill.side,
        intent: fill.intent === 'entry' ? '진입' : '청산',
        qty: fill.quantity,
        count: 1,
        strategy: said.name,
        version: said.version,
        /* 체결이 들고 온 갈래 그대로입니다 — 이 목록에는 모의 계좌 실행도 서서,
           고정으로 두면 계좌에서 난 체결이 「가상」으로 섭니다. */
        virtual: fill.virtual,
        at: clockOf(fill.time),
        reasons: fill.reason ? [fill.reason] : [],
        firstAt: fill.time,
        snapshot: fill.snapshot,
        fee: fill.fee,
        currency,
      })
    }
    return mergeMarks(seated)
    // nameOf 는 목록에서 파생됩니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [picked, snapshot, bars, slot.span, store.rows, decimals])

  /* 아래 표의 행. 체결이 들고 온 값 그대로입니다 — 표와 표지가 같은 값을
     말해야 같은 체결로 읽힙니다. */
  const rows = useMemo<VerifyFill[]>(
    () => (bottom === '체결' ? (snapshot?.fills ?? []) : []),
    [snapshot, bottom],
  )

  /* 아직 안 채워진 주문. **덮어쓰는 값**이라 저장소가 방송이 준 것으로 통째로
     갈아 끼웁니다 — 여기서는 읽기만 합니다. */
  const opens = useMemo<VerifyOrder[]>(
    () => (bottom === '미체결' ? (snapshot?.openOrders ?? []) : []),
    [snapshot, bottom],
  )
  /* 두 탭이 **한 표**를 씁니다. 칸 이름이 같아 갈리는 것은 수량 칸 하나인데,
     **무엇을 적을지는 탭이 정합니다** — 줄에 `remaining` 칸이 있나로 가리면
     서버가 체결 줄에 그 칸을 싣기 시작하는 날 체결 표가 조용히 남은 수량을
     적습니다. 그리기 전에 한 꼴로 맞춰 두어 칸마다 갈래를 다시 보지 않습니다. */
  const tableRows = useMemo<TableRow[]>(() => {
    const line = (
      one: VerifyFill | VerifyOrder,
      key: string,
      amount: number,
      tick: number | null | undefined,
    ): TableRow => ({
      key,
      time: one.time,
      side: one.side,
      intent: one.intent,
      reason: one.reason,
      price: one.price,
      amount,
      tick,
    })
    return bottom === '미체결'
      ? opens.map((one, index) =>
          line(one, `${one.orderId}-${one.time}-${index}`, one.remaining, tickBarOf({ kind: 'order', order: one })),
        )
      : /* 체결은 **저장소가 쓰는 열쇠 그대로** 갈립니다 — 표에서 본 줄을
           저장소에서도 같은 이름으로 찾을 수 있어야 합니다. */
        rows.map((one) => line(one, fillKey(one), one.quantity, tickBarOf({ kind: 'fill', fill: one })))
  }, [bottom, opens, rows])

  /* 이벤트는 **최신 위**입니다. 정렬만 바꿉니다 — 서버가 준 차례와 저장은 그대로입니다.
     같은 시각이면 받은 차례의 뒤엣것이 위입니다. */
  const events = useMemo(
    () =>
      (snapshot?.events ?? [])
        .map((item, index) => ({ item, index }))
        .sort((a, b) => b.item.time - a.item.time || b.index - a.index)
        .map(({ item }) => item),
    [snapshot],
  )
  /* 새 줄이 위에 붙을 때 **보던 자리를 지킵니다.** 맨 위를 보고 있었으면 새 줄을
     따라가고, 아래를 보던 중이면 늘어난 높이만큼 내려 같은 줄이 그 자리에 남습니다. */
  const eventBoxRef = useRef<HTMLDivElement>(null)
  const eventHeight = useRef({ id: '', height: 0 })
  useLayoutEffect(() => {
    const box = eventBoxRef.current
    if (!box || bottom !== '이벤트') return
    const id = snapshot?.run.id ?? ''
    const had = eventHeight.current
    const height = box.scrollHeight
    if (had.id === id && box.scrollTop > 0 && height > had.height) box.scrollTop += height - had.height
    eventHeight.current = { id, height }
  }, [events, bottom, snapshot?.run.id])


  /* 「선택 …」 단추의 대상 — **체크한 실행만**(`targetsOf`). 차트에 띄운 실행은
     대상이 아닙니다: 클릭 한 번에 바뀌는 것이라 청산·종료의 대상으로 삼지
     않습니다. 체크는 보는 실행을 바꾸지 않습니다 — 여럿을 고른 채 하나를 차트에
     띄워 볼 수 있어야 합니다. 대상 문장과 확인 창이 이 하나를 씁니다. */
  const chosen = targetsOf(all, checked)
  const toggleCheck = (id: string) =>
    patchVerify({ checked: checked.includes(id) ? checked.filter((x) => x !== id) : [...checked, id] })

  /* 중지·재개는 한 단추입니다. 고른 것이 **전부 중지**면 「재개」, 아니면
     「중지」이고 그때 이미 중지된 줄은 빠집니다. */
  const toggleDeed: Deed =
    chosen.length > 0 && chosen.every((run) => run.state === 'paused')
      ? '선택 검증 재개'
      : '선택 검증 중지'

  /* 그 동작에서 한 줄이 빠지는 까닭. 빠지지 않으면 `null` 입니다.
     **서버 판정을 화면이 다시 하는 것이 아니라, 서버가 준 줄의 값으로 가립니다** —
     상태와 보유는 방송이 실어 주는 사실이고, 그 사실로 이미 아는 것을 요청해
     400 을 받아 보게 하지 않습니다. 그래도 막는 최종 판정은 서버이고, 거절
     문장은 그대로 화면에 섭니다.
     「확인 필요」 줄에는 「실행 종료」 말고는 어떤 요청도 보내지 않습니다(규격 §7) —
     사용자가 먼저 풀어야 하는 자리입니다. 종료는 계좌로 나가는 요청이 없어, 남은
     것이 없으면 보냅니다(`attentionEndWhy`). 끝난 실행에는 지우는 것 말고는 걸
     것이 없습니다. */
  function skipWhy(action: Deed, run: VerifyRun): string | null {
    if (run.state === 'attention') {
      if (action !== '실행 종료') return '확인이 필요한 실행에는 요청을 보내지 않습니다'
      return acting === run.id ? '보낸 요청을 기다리는 중입니다' : attentionEndWhy(run)
    }
    if (acting === run.id) return '보낸 요청을 기다리는 중입니다'
    if (action === '실행삭제') return run.state === 'ended' ? null : '끝난 실행만 지웁니다'
    if (run.state === 'ended') return '끝난 실행입니다'
    if (action === '선택 검증 중지') {
      return run.state === 'paused' ? `${run.stateLabel} — 이번 요청에서 제외` : null
    }
    if (action === '선택 검증 재개') return null
    if (action === '실행 종료') {
      return run.position !== 0 ? '「선택 전략 청산」을 먼저 하세요' : null
    }
    return run.position === 0 ? '보유가 없습니다' : null
  }

  /* 단추를 못 누르는 까닭. **나갈 줄이 하나라도 있으면 누를 수 있습니다** —
     빠지는 줄은 확인 창이 까닭과 함께 보입니다. 전부 빠지면 빠진 까닭을
     단추 아래에 적습니다. */
  function whyFor(action: Deed): string | null {
    /* 도는 실행이 아예 없으면 단추 전부가 **같은 사실 하나** 때문에 막힙니다.
       「고른 실행이 없습니다」로 적으면 「검증 신규 진입 중지」만 다른 말을
       해서, 같은 사실이 까닭 두 줄로 갈립니다. */
    if (all.length === 0) return '도는 검증이 없습니다'
    if (action === '검증 신규 진입 중지') return null
    if (chosen.length === 0) return PICK_HINT
    const skips = chosen.map((run) => skipWhy(action, run))
    if (skips.some((one) => one === null)) return null
    return [...new Set(skips as string[])].join(' · ')
  }

  /* 단추 다섯과 못 누르는 까닭. **단추와 까닭 줄이 한 목록에서 나옵니다** —
     따로 두면 `aria-describedby` 가 없는 줄을 가리키게 됩니다. */
  const acts = [toggleDeed, ...DEEDS].map((deed) => ({
    id: DEED_KEY[deed],
    label: DEED_LABEL[deed],
    why: whyFor(deed),
    deed,
  }))
  const stops = acts.filter((one) => one.why !== null)
  /* 막힌 단추를 **까닭으로 묶습니다** — 다섯이 같은 말을 되풀이하면 목록보다
     까닭이 깁니다. 한 까닭이 막힌 단추 전부를 덮으면 어느 단추의 말인지 적을
     것이 없어 까닭만 세우고, 까닭이 갈리면 그 까닭이 덮는 단추 이름을 앞에
     답니다. 줄의 `id` 는 그 묶음의 첫 단추 이름으로 섭니다. */
  const groups = [...new Set(stops.map((one) => one.why as string))].map((why) => {
    const held = stops.filter((one) => one.why === why)
    return { why, ids: held.map((one) => one.id), names: held.map((one) => one.label) }
  })
  const whyIdOf = (id: string) =>
    `vrf-why-${groups.find((group) => group.ids.includes(id))?.ids[0] ?? id}`

  /** 확인 창에서 단추를 누른 뒤. 고른 것 가운데 **빠지지 않는 줄에 차례로**
   *  보내고, 하나가 거절돼도 나머지는 보냅니다. 결과는 「N건 중 K건 거절 — 첫
   *  서버 문장」 한 줄입니다(진행 화면과 같은 셈, `sendEach`). */
  async function commit(action: Deed) {
    setDeed(null)
    if (action === '검증 신규 진입 중지') {
      /* 이 탭의 전체 중지는 **종이 실행만** 멈춥니다 — 계좌 실행은 진행 탭의 것입니다. */
      const said = await stopAllRuns(['paper'])
      const warned = typeof said === 'object' && 'warn' in said
      setWhy(typeof said === 'string' ? said : warned ? said.warn : null)
      setWhyWarn(warned)
      return
    }
    const verb = DEED_VERB[action]
    const sending = chosen.filter((run) => skipWhy(action, run) === null)
    setWhyWarn(false)
    setWhy(
      await sendEach(sending, (run) =>
        verb === undefined ? deleteRun(run.id) : actOnRun(run.id, verb),
      ),
    )
  }

  /* 줄 몸을 누르면 그 실행을 봅니다. 열려 있던 마커 상세는 닫습니다 — 그
     상세는 앞 실행의 체결이라, 남겨 두면 다른 실행 위에 남의 체결이 떠 있게
     됩니다. */
  function pickRun(id: string) {
    setPickedId(id)
    setMarkPick(null)
  }

  function runRow(run: VerifyRun) {
    /* 끝난 실행. 앞으로 일어날 일을 말하는 줄들이 여기서는 빠집니다. */
    const done = run.state === 'ended'
    return (
      /* 값을 못 받는 중인 줄은 **흐리게**. 앞 박자에 받은 값이 그대로 선 것이라
         「지금 값이 아니다」를 말해야 하는데, 값마다 표시를 달면 줄이 표시로
         덮입니다. 단추는 안 흐려집니다 — 그때도 눌러야 하는 것들입니다. */
      /* 체크는 「이 실행에 동작을 건다」, 줄 몸 누름은 「이 실행을 본다」입니다.
         보는 실행 표시는 줄 바탕(`is-picked`)이 맡습니다. */
      <label
        className={`vrf-run${run.id === picked?.id ? ' is-picked' : ''}${run.stale ? ' is-stale' : ''}`}
        key={run.id}
      >
        <input
          type="checkbox"
          checked={checked.includes(run.id)}
          onChange={() => toggleCheck(run.id)}
        />
        <button
          type="button"
          className="vrf-run-body"
          aria-current={run.id === picked?.id ? 'true' : undefined}
          onClick={(event) => {
            /* 「안 낸 신호」 배지를 누르면 그 실행을 고르고 이벤트 탭으로 갑니다 —
               까닭은 이벤트 줄에 있습니다. */
            const toEvents = (event.target as HTMLElement).closest('.vrf-unsent-badge') !== null
            if (toEvents) {
              if (run.id === picked?.id) setBottom('이벤트')
              else tabAsked.current = '이벤트'
            }
            pickRun(run.id)
          }}
        >
          {/* 버전과 종목을 **줄을 나눠** 적습니다. 한 줄에 붙이면 좁은 열에서
              종목이 만기부터 잘리는데, 하필 잘리는 자리가 만기입니다. */}
          <span className="vrf-run-name">
            <span className="vrf-run-name-text">{nameOf(run.version).name}</span>
          </span>
          <span className="vrf-run-sub">{nameOf(run.version).version}</span>
          <span className="vrf-run-sub">{shortInstrument(run.code)}</span>
          {/* 세션은 제 줄에 — 같은 전략을 주간·야간으로 따로 돌리면 둘을 가르는
              것이 세션뿐입니다. */}
          <span className="vrf-run-sub">{runSessionLabel(run)}</span>
          {/* 상태와 가상 보유는 값이라 본문색입니다. 색으로 상태를 말하면
              읽는 사람이 색표를 외워야 합니다. 낱말은 **서버가 함께 줍니다** —
              화면이 상태 표를 또 두면 두 표가 갈립니다. */}
          <span className="vrf-run-state">
            {run.stateLabel}
            {(run.position ?? 0) > 0 && ` · ${run.side === 'buy' ? '매수' : '매도'} ${run.position}계약`}
            {/* 자금이 증거금에 못 미치면 이 실행은 진입이 막힙니다(서버가 막음).
                끝난 실행에는 앞이 없어 안 답니다. */}
            {!done && runFunds(run, runCurrency(run)).kind === 'short' && (
              <span className="badge badge-warn vrf-funds-badge" title={FUNDS_SHORT}>
                자금 부족
              </span>
            )}
            {/* 오늘 규칙이 참이었는데 주문을 내지 않은 봉의 수. 까닭은 이벤트에
                있습니다(누르면 그 탭). 없으면 안 섭니다. */}
            {(run.unsentToday ?? 0) > 0 && (
              <span className="badge badge-warn vrf-unsent-badge" title={`오늘 안 낸 신호 ${run.unsentToday}건`}>
                안 낸 신호 {run.unsentToday}
              </span>
            )}
          </span>
          {/* 성과 한 줄 — 서버가 센 신호·체결 수와 손익, 마지막 신호 시각. */}
          <RunStats run={run} currency={runCurrency(run)} />
          {/* 봉이 모자라 아직 판정을 못 하는 동안은 그 사실이 상태보다 먼저
              알아야 하는 것입니다 — 「감시 중」인데 아무 일도 안 나는 까닭입니다. */}
          {/* 준비 중은 **중립**입니다 — 이상이 아니라 아직 봉이 모자란 것입니다.
              경고색은 끊김 하나가 씁니다(머리의 점과 같은 규칙).

              **끝난 실행에는 안 세웁니다.** 준비도 시세도 「앞으로 올 것」을
              말하는 줄인데, 끝난 실행에는 앞이 없습니다. */}
          {/* 봉 수를 모르면(`null`) 준비 줄을 세우지 않습니다 — 「확보 —」는 준비 중인지
              아닌지를 말하지 못합니다. */}
          {!done && run.warmup != null && run.bars != null && run.bars < run.warmup && (
            <span className="vrf-run-feed">
              준비 중 — 필요 {run.warmup} · 확보 {run.bars}
            </span>
          )}
          {!done && run.feed !== 'live' && (
            <span className={`vrf-run-feed${run.feed === 'gap' ? ' is-warn' : ''}`}>
              시세 {FEED_LABEL[run.feed]}
              {/* 「마지막」은 **끊긴 줄에만** 답니다. 아직 안 붙은 줄에 마지막
                  시각이 서면 「온 적 없다」와 「여기까지 왔다」가 한 줄에 함께
                  섭니다. */}
              {run.feed === 'gap' && run.feedAt > 0 && ` · 마지막 ${minuteOf(run.feedAt)}`}
            </span>
          )}
        </button>
      </label>
    )
  }

  function accordion(
    id: keyof typeof open,
    title: string,
    summary: string,
    body: React.ReactNode,
    warn: string = '',
  ) {
    return (
      <section className="card vrf-acc">
        <button
          type="button"
          className="vrf-acc-head"
          aria-expanded={open[id]}
          aria-label={`${title} ${open[id] ? '접기' : '펼치기'}`}
          /* 직전 값에서 뒤집습니다 — 바깥의 `open` 을 그대로 쓰면 같은 순간에
             두 아코디언을 누를 때 앞의 것이 묻힙니다. */
          onClick={() => setOpen((prev) => ({ ...prev, [id]: !prev[id] }))}
        >
          <span className="vrf-acc-title">{title}</span>
          {!open[id] && (
            <span className="vrf-acc-sum" title={summary}>
              {summary}
            </span>
          )}
          {/* 경고는 요약 밖에 따로 둡니다 — 좁은 칸에서 요약이 말줄임으로 잘려도
              이 말은 남습니다. */}
          {!open[id] && warn && <span className="vrf-acc-warn">{warn}</span>}
          <span className="vrf-acc-mark">{open[id] ? '⌃' : '⌄'}</span>
        </button>
        {open[id] && <div className="vrf-acc-body">{body}</div>}
      </section>
    )
  }

  /** 돈을 적는 말. **통화는 그 실행의 것**입니다 — 해외 전략을 검증하면
   *  실행 자금도 그 통화로 셉니다. */
  const money = (value: number | null, unit = currency) => moneyIn(value, unit)

  /* 사용 증거금 = (보유 + 진입 미체결 + 이번 주문) × 계약당. **서버의 한도
     검사와 같은 셈**입니다. 계약당을 못 내는 근거에서는 이 값도 못 냅니다. */
  const usedOf = (row: VerifyRun): number | null =>
    /* 보유나 나가 있는 진입 수량을 모르면 사용액도 모릅니다 — 0 으로 더하면 실제보다
       적게 셉니다. */
    row.perContract === null || row.position === null || row.openEntry === null
      ? null
      : (row.position + row.openEntry + row.qty) * row.perContract

  /* 「—」와 「아직 못 받음」은 다릅니다 — 앞은 그 갈래에서 **원래 없는 값**이고,
     뒤는 낼 수 있는데 재료가 아직 안 온 것입니다. 한 말로 뭉뚱그리면 기다리면
     되는 자리와 기다려도 안 되는 자리가 같아 보입니다. */
  const usedText = (row: VerifyRun): string => {
    if (!marginKnown(row.perContractBasis)) return '—'
    const used = usedOf(row)
    if (used === null) return '아직 못 받음'
    return row.perContractBasis === 'premium-now' ? `${money(used)}(어림)` : money(used)
  }

  /* 증거금 줄의 조각들. **글자 하나로 안 냅니다** — 좁은 판에서 줄이 접힐 때
     「· 사용」과 그 값이 갈리면 사용액이 계약당 값의 꼬리처럼 읽힙니다. 조각마다
     안 끊기게 두고 조각 사이에서만 접습니다. */
  /* 증거금 줄에 설 것 — **값 조각들과 까닭을 한 번에** 냅니다. 둘을 따로 세면
     같은 갈래 판정을 두 번 하게 되고, 한쪽만 고쳐지는 날 값과 까닭이 어긋납니다.
     - `parts` 는 **글자 하나로 안 냅니다**: 좁은 판에서 줄이 접힐 때 「· 사용」과
       그 값이 갈리면 사용액이 계약당 값의 꼬리처럼 읽힙니다.
     - `why` 는 **값이 아니라 설명**이라 값들과 「·」로 잇지 않고 흐린 꼬리로 답니다. */
  const marginLine = (row: VerifyRun): { parts: string[]; why: string } => {
    const word = marginBasisWord(row.perContractBasis)
    if (!marginKnown(row.perContractBasis)) return { parts: ['계약당 —', '사용 —'], why: word }
    if (row.perContract === null) {
      return { parts: ['계약당 아직 못 받음', '사용 아직 못 받음'], why: '' }
    }
    const each = word ? `계약당 ${money(row.perContract)}(${word})` : `계약당 ${money(row.perContract)}`
    return { parts: [each, `사용 ${usedText(row)}`], why: '' }
  }

  return (
    <div className="vrf" ref={boxRef}>
      <div className="card vrf-head">
        <div className="vrf-head-left">
          {/* **화면 전체의 구독**을 말하는 자리라 그 범위를 낱말로 밝힙니다 —
              줄의 「시세 …」는 그 실행 하나의 것입니다. */}
          <span className="vrf-feed">
            <span className={FEED_TONE[picked?.feed ?? 'idle']} />
            시세 구독 — {FEED_LABEL[picked?.feed ?? 'idle']}
          </span>
          {/* 「동시 실행 n / 상한」 — n 은 **상한을 먹는 실행**(끝나지 않은 것, 중지 포함)을
              진행 탭의 것까지 센 수이고 상한은 서버 값입니다. 「이 탭」과 중지·종료는
              이 탭의 종이 실행만 셉니다. 끝난 실행은 상한을 안 먹어 따로 셉니다.
              진행 탭에 계좌 실행이 돌면 그 수와 그리로 가는 길을 바로 뒤에 답니다. */}
          <span className="vrf-counts-line">
            <span className="vrf-counts">
              동시 실행 {standing}
              {max > 0 && ` / ${max}`}
              {` · 이 탭 ${running + stopped} · 중지 ${stopped} · 종료 ${ended}`}
            </span>
            {tradingLink}
          </span>
          {/* 못 한 일은 **한 자리에 한 줄**입니다. 차트 위에 따로 띠를 두면
              그만큼 차트가 낮아지는데, 이 화면의 세로는 차트와 아래 표가
              다투는 자리입니다. */}
          {status === 'failed' && (
            <span className="vrf-pending" title={failure ?? undefined}>
              {failure}
            </span>
          )}
          {why !== null && (
            <span className={whyWarn ? 'vrf-pending is-warn' : 'vrf-pending'} title={why}>
              {why}
            </span>
          )}
        </div>
        {/* 그냥 누르면 목록에서 고른 전략으로 채워 엽니다. 목록에서 들고 온
            경우에는 그 전략·버전이 이미 담겨 있습니다. */}
        {/* 동시 실행이 상한이면 잠그고 까닭을 `title` 에 둡니다. */}
        <button
          type="button"
          className="btn btn-primary"
          aria-disabled={full}
          title={full ? fullWhy : undefined}
          onClick={openAdd}
        >
          검증 추가
        </button>
      </div>

      <div className="vrf-body">
        {/* 왼쪽은 제 안에서 구릅니다. 이 열이 길어질 때 화면 전체를 늘리면
            차트와 아래 표까지 밀려 내려갑니다 — 상세는 필요할 때 열고 닫는
            자리이고, 화면의 높이를 정하는 것은 차트와 표입니다. */}
        <aside className="vrf-side" aria-label="검증 실행 목록">
          <div className="vrf-side-inner">
          <div className="card vrf-runs">
            <h2 className="vrf-card-title">실행</h2>
            {/* 담아 둔 실행을 서버가 못 읽었으면 **목록이 빈 까닭**을 이 카드
                안에 한 줄로 답니다. 카드는 단추가 서 있어 통째로 비지 않으므로
                블록이 아니라 줄입니다. 위의 「못 받았다」와도 다른 말입니다 —
                그쪽은 서버에 못 닿은 것이고 이쪽은 서버가 파일을 못 읽은 것이라
                다시 받아도 같습니다.
                파일 이름은 **마우스를 올렸을 때만** 보입니다 — 사용자가 할 일을
                바꾸는 말이 아니라 나중에 찾을 때 쓰는 말이고, 좁은 카드에서
                여러 줄로 접히면 실행 목록이 밀려납니다. */}
            {storeWhy !== null && (
              <p className="vrf-store-why" title={storeWhy.reason ?? undefined}>
                {storeWhy.title}
              </p>
            )}
            <div className="vrf-run-list">
              {status === 'loading' && <p className="vrf-why">실행 목록을 받는 중입니다</p>}
              {/* 비었다는 말은 가운데 빈 화면이 합니다 — 여기 또 적으면 같은 말이 두 번 섭니다.
                  담아 둔 파일을 **못 읽었으면 그 빈 화면도 안 섭니다** — 바로 위 한 줄이 이미
                  무슨 일인지 말했고, 「없다」고 하면 그 말과 반대가 됩니다. 이 앱 파일이 아닌
                  경우는 읽기는 읽었고 그 실행들이 안 도는 것이 사실이라 빈 화면이 섭니다. */}
              {all.map(runRow)}
            </div>
            {/* 단추는 모두 확인 창을 지납니다 — 여러 실행을 고르므로 무엇에 걸리고
                무엇이 빠지는지를 창이 먼저 보입니다. **「확인 필요」 줄에는 어떤
                요청도 보내지 않습니다**(규격 §7) — 사용자가 먼저 풀어야 합니다. */}
            {all.length > 0 && <p className="vrf-target">{targetLine(chosen.length)}</p>}
            {acts.map((one) => (
              <button
                key={one.id}
                type="button"
                className="btn btn-quiet vrf-stop"
                aria-disabled={one.why !== null}
                aria-describedby={one.why === null ? undefined : whyIdOf(one.id)}
                title={one.why === PICK_HINT ? PICK_HINT : undefined}
                onClick={() => {
                  if (one.why === null) setDeed(one.deed)
                }}
              >
                {one.label}
              </button>
            ))}
            {/* 못 누르는 까닭은 눌리지 않는 단추 아래에 답니다. 막힌 것이
                없어도 빈 줄 하나를 두어 목록이 오르내리지 않습니다. */}
            <div className="vrf-whys">
              {groups.length === 0 ? (
                <p className="vrf-why" />
              ) : (
                groups.map((group) => (
                  <p className="vrf-why" id={`vrf-why-${group.ids[0]}`} key={group.ids[0]}>
                    {groups.length > 1 && `${group.names.join(' · ')}: `}
                    {group.why}
                  </p>
                ))
              )}
            </div>
          </div>

          {/* 실행이 하나도 없으면 자금·체결 가정 카드를 그리지 않습니다 — 고른 실행이
              없어 칸이 다 「—」라, 선 카드가 빈 값을 값처럼 보입니다. */}
          {all.length > 0 && (
          <>
          {accordion(
            'fund',
            /* 이름에서 「실행」을 뺐습니다 — 이 화면이 통째로 실행 하나를 보는
               자리라 없어도 같은 말이고, 그 두 글자가 접힘 머리의 값을 잘랐습니다
               (잰 값: 값에 쓸 수 있는 폭 84px, 필요한 폭 90px). */
            '자금 · 증거금',
            /* 접힘 머리에는 **사용액 하나만** 적습니다. 실행 자금은 사용자가 정해
               둔 값이라 접힌 채로 다시 볼 까닭이 없고, 둘을 다 세우면 좁은 판에서
               값이 잘립니다 — 접힘 머리는 「지금 어떤가」 하나를 답하는 자리입니다. */
            picked ? `사용 ${usedText(picked)}` : '—',
            <>
              {/* 증거금을 정하는 값이라 자금 옆에 둡니다. 위 상태 줄은 지금
                  들고 있는 것만 싣습니다.

                  **맨 위입니다.** 아래 안내는 두 자금 줄을 가리키는 말이라,
                  자금 밑에 두면 사용자가 정한 수량을 가리키는 것으로 읽힙니다. */}
              <div className="vrf-row">
                <span>주문당 수량</span>
                <b>{picked ? `${picked.qty}계약` : '—'}</b>
              </div>
              <div className="vrf-row">
                <span>실행 자금</span>
                <b>{picked ? money(picked.cash) : '—'}</b>
              </div>
              {/* **계약당과 사용액은 다른 값입니다.** 줄에 실려 오는 것은 계약
                  하나에 드는 돈인데, 「묶인 증거금」으로 적으면 지금 묶여 있는
                  금액으로 읽힙니다. 둘을 한 줄에 나란히 적어 무엇이 무엇인지
                  글자로 가릅니다.

                  사용액은 **서버의 한도 검사와 같은 셈**입니다 — 보유에 나가 있는
                  진입 주문과 이번 주문 수량까지 더해 계약당을 곱합니다. 셈이
                  갈리면 사용자는 막힌 까닭을 화면에서 못 찾습니다. */}
              <div className="vrf-row is-long">
                <span>증거금</span>
                <b>
                  {picked
                    ? (() => {
                        const { parts, why } = marginLine(picked)
                        return (
                          <>
                            {parts.map((part, index) => (
                              /* 조각 **사이에만** 빈칸을 둡니다 — 줄은 여기서만
                                 바뀌고, 가운뎃점은 뒤 조각에 붙어 함께 내려갑니다. */
                              <Fragment key={part}>
                                {index > 0 && ' '}
                                <span>
                                  {index > 0 && '· '}
                                  {part}
                                </span>
                              </Fragment>
                            ))}
                            {why && (
                              <>
                                {' '}
                                <span className="vrf-row-why">{why}</span>
                              </>
                            )}
                          </>
                        )
                      })()
                    : '—'}
                </b>
              </div>
              {/* 자금과 증거금을 견준 결과. 셈은 실행 카드의 배지와 같습니다. */}
              {picked && picked.state !== 'ended' && (
                <FundsNote verdict={runFunds(picked, currency)} qty={picked.qty} currency={currency} />
              )}
              <p className="vrf-hint">가상 장부라 실제 주문가능수량과 다릅니다</p>
            </>,
            picked && picked.state !== 'ended' && runFunds(picked, currency).kind === 'short' ? '자금 부족' : '',
          )}

          {accordion(
            'fill',
            '체결 가정',
            picked ? `${sessionLabelOf(picked.session)} · 지연 0.3초` : '—',
            <>
              <div className="vrf-row">
                <span>세션</span>
                {/* 줄이 실어 오는 것은 키(`domestic-day`)입니다. **사람이 읽는
                    자리에는 글자로** 세웁니다 — 키는 서버와 주고받는 이름이지
                    화면에 적는 말이 아닙니다. */}
                <b>{picked ? sessionLabelOf(picked.session) : '—'}</b>
              </div>
              <div className="vrf-row">
                <span>대기 지정가</span>
                <b>보수적 대기열</b>
              </div>
              <div className="vrf-row">
                <span>처리 지연</span>
                <b>0.3초</b>
              </div>
              <p className="vrf-hint">거래소와 같은 결과를 보장하지 않습니다</p>
            </>,
          )}
          </>
          )}
          </div>
        </aside>

        {/* 도는 검증이 하나도 없으면 오른쪽 상세(차트·표)를 그리지 않습니다 — 빈 차트와
            빈 표는 「고장」과 구별되지 않습니다. 가운데에 그 사실과 할 일 하나입니다. */}
        {status === 'ready' && all.length === 0 && !storeBroken ? (
          <div className="vrf-main notice">
            <p className="notice-title">도는 검증이 없습니다</p>
            {/* 진행 탭에 계좌 실행만 돌고 있으면 「없다」만으로는 그 실행들이 사라진
                것처럼 읽힙니다 — 어디서 보는지 한 줄로 잇습니다. */}
            {tradingLink}
            <button
              type="button"
              className="btn btn-primary notice-action"
              aria-disabled={full}
              title={full ? fullWhy : undefined}
              onClick={openAdd}
            >
              검증 추가
            </button>
          </div>
        ) : (
        <div className="vrf-main">
          {/* 지금 보는 실행이 무엇인지 — 전략 · 버전 · 종목 · 세션. 차트·표가 이 실행의
              것입니다. */}
          {picked && (
            <p className="vrf-title">
              <span className="vrf-title-name">{nameOf(picked.version).name || '—'}</span>
              <span className="vrf-title-sub">
                {' · '}
                {[nameOf(picked.version).version, shortInstrument(picked.code), runSessionLabel(picked)]
                  .filter(Boolean)
                  .join(' · ')}
              </span>
            </p>
          )}
          <div className="vrf-bar">
            {/* 이 실행이 붙은 세션. 같은 전략을 두 세션으로 돌릴 때 지금 보는 것이
                어느 쪽인지 여기서 읽힙니다. */}
            <span className="vrf-bar-item">
              세션 <b>{picked ? runSessionLabel(picked) : '—'}</b>
            </span>
            <span className="vrf-bar-item">
              가상 보유{' '}
              <b>
                {picked && (picked.position ?? 0) > 0
                  ? `${picked.side === 'buy' ? '매수' : '매도'} ${picked.position}계약`
                  : picked && picked.position === null
                    ? '—'
                    : '없음'}
              </b>
            </span>
            <span className="vrf-bar-item">
              평균가{' '}
              <b>
                {picked && picked.avgPrice !== null ? (
                  <Num value={picked.avgPrice} decimals={decimals} />
                ) : (
                  '—'
                )}
              </b>
            </span>
            <span className="vrf-bar-item">
              {/* 실행이 없으면 값도 없습니다 — 0 은 「본전」이고, 본전은 들고
                  있는 것이 있을 때 하는 말입니다. */}
              평가손익{' '}
              <b className={picked ? toneOf(picked.pl ?? 0) || undefined : undefined}>
                {picked ? `${(picked.pl ?? 0) > 0 && currency ? '+' : ''}${moneyIn(picked.pl, currency)}` : '—'}
              </b>
            </span>
            {/* 이어진 손실과 그 한도(진행 띠와 같은 글자). 한도를 정했고 1 이상일
                때만 섭니다. */}
            {streakText(picked, picked ? savedOf(picked.version)?.aux.lossStreak : undefined) && (
              <span className="vrf-bar-item">
                {streakText(picked, picked ? savedOf(picked.version)?.aux.lossStreak : undefined)}
              </span>
            )}
            {/* 체결만 기본으로 켜 두고, 신호·주문은 여기서 켭니다. */}
            <label className="vrf-check">
              <input
                type="checkbox"
                checked={showDetail}
                onChange={(event) => setShowDetail(event.target.checked)}
              />
              신호 · 주문도 표시
            </label>
          </div>

          <div className="vrf-chart">
            {picked && (
            <ChartPanel
              quotes={[quote, null]}
              slots={[slot, { instrument: null, span: 'minute', indicators: null }]}
              onSlotChange={(_, patch) => setSlot({ ...slot, ...patch })}
              expanded={false}
              onExpandedChange={() => {}}
              split={false}
              onSplitChange={() => {}}
              active={0}
              onActiveChange={() => {}}
              tradeMarks={marks}
              onMarkPick={(mark, at) => setMarkPick({ mark, ...at })}
              indicatorLayer={indicatorLayer}
            />
            )}
            {markPick && <MarkPopover pick={markPick} onClose={() => setMarkPick(null)} />}
          </div>

          <div className="vrf-bottom">
            <div className="tabs tabs-inline vrf-bottom-tabs">
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

            <div className="table-scroll vrf-table" ref={eventBoxRef}>
              {bottom === '조건' ? (
                <ConditionTable
                  conditions={snapshot?.conditions}
                  decimals={decimals}
                  tick={pickedRow ? savedOf(pickedRow.id)?.evalMode === '틱' : false}
                />
              ) : bottom === '이벤트' ? (
                <table className="data-table rows-base">
                  <colgroup>
                    <col className={`vrf-col-time${isTickRun(picked) ? ' is-tick' : ''}`} />
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
                    {events.map((item, index) => {
                      const tick = tickBarOf({ kind: 'event', event: item })
                      return (
                        <tr key={`${item.time}-${index}`}>
                          <td className="col-text">
                            {clockOf(item.time)}
                            {tick !== undefined && <TickBadge barTime={tick} />}
                          </td>
                          <td className="col-text">
                            <EventText kind={item.kind} reason={item.reason} text={item.text} />
                          </td>
                        </tr>
                      )
                    })}
                    {/* 머리만 있는 빈 표는 「고장」과 구별되지 않습니다. */}
                    {events.length === 0 && (
                      <tr>
                        <td className="vrf-empty-row" colSpan={2}>
                          아직 남은 이벤트가 없습니다
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              ) : (
                <table className="data-table rows-base">
                  <colgroup>
                    <col className={`vrf-col-time${isTickRun(picked) ? ' is-tick' : ''}`} />
                    <col className="vrf-col-side" />
                    {/* 용도가 남는 폭을 가져갑니다 — 까닭까지 적는 칸이라
                        못 박으면 「청산 · 손절」의 까닭이 잘립니다. */}
                    <col />
                    <col className="vrf-col-price" />
                    <col className="vrf-col-qty" />
                  </colgroup>
                  <thead>
                    <tr>
                      <th scope="col" className="col-text">
                        시각
                      </th>
                      <th scope="col" className="col-text">
                        구분
                      </th>
                      <th scope="col" className="col-text">
                        용도
                      </th>
                      <th scope="col">가격</th>
                      <th scope="col">{bottom === '미체결' ? '미체결' : '수량'}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tableRows.map((one) => (
                      <tr key={one.key}>
                        <td className="col-text">
                          {clockOf(one.time)}
                          {one.tick !== undefined && <TickBadge barTime={one.tick} />}
                        </td>
                        {/* 표의 매수·매도는 방향값이라 색을 씁니다 — 문장 속
                            낱말이 아니라 값이 서는 칸입니다. */}
                        <td className={`col-text ${one.side === 'buy' ? 'up' : 'down'}`}>
                          {one.side === 'buy' ? '매수' : '매도'}
                        </td>
                        <td className="col-text">
                          {one.intent === 'entry' ? '진입' : '청산'}
                          {reasonWord(one.reason) && ` · ${reasonWord(one.reason)}`}
                        </td>
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
                        <td className="vrf-empty-row" colSpan={5}>
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

      {openPanel && (
        <Modal
          label="검증 추가"
          onClose={() => closePanel()}
          head={<span className="modal-title">검증 추가</span>}
        >
          <VerifyAddForm
            rows={store.rows}
            savingId={store.saving}
            seed={add}
            why={store.verify.addWhy}
            onCancel={() => closePanel()}
            onStarted={() => closePanel()}
          />
        </Modal>
      )}

      {/* 되돌릴 수 없는 동작의 확인 창. **무엇이 일어나는지를 줄여 적지
          않습니다** — 진입 주문과 보유분이 각각 어떻게 되는지 두 줄로 적고,
          그 표는 진행 화면과 같은 한 벌입니다. */}
      {deed !== null && (() => {
        /* 창의 두 줄. 중지는 진행 화면의 「신규 진입 중지」와 같은 일이라 그
           설명을 씁니다. 재개는 막는 것을 푸는 일이라 설명할 되돌릴 수 없는
           결과가 없어 두 줄을 안 세웁니다. */
        const text =
          deed === '선택 검증 중지'
            ? CONFIRM_TEXT['신규 진입 중지']
            : deed === '선택 검증 재개'
              ? null
              : CONFIRM_TEXT[deed]
        /* 요청이 실제로 나가는 줄과 빠지는 줄. 창의 셈·목록·단추가 모두 이
           갈래를 씁니다(진행 화면의 창과 같은 꼴). */
        const everyone = deed === '검증 신규 진입 중지'
        const applied = chosen.filter((run) => skipWhy(deed, run) === null)
        const excluded = chosen.filter((run) => skipWhy(deed, run) !== null)
        /* 창이 떠 있는 동안에도 실행 상태는 방송으로 바뀝니다 — 나갈 요청이 없어지면
           단추를 잠그고 그 까닭을 단추 곁에 적습니다. 대상이 아예 없으면 그렇게
           말하고, 있는데 다 빠졌으면 빠진 까닭(목록 줄마다 단 말)을 모아 적습니다. */
        const none = everyone ? running === 0 : applied.length === 0
        const noneWhy = !none
          ? ''
          : everyone || chosen.length === 0
            ? '대상 실행이 없습니다'
            : [...new Set(excluded.map((run) => skipWhy(deed, run) as string))].join(' · ')
        return (
        <Modal
          label={DEED_LABEL[deed]}
          onClose={() => setDeed(null)}
          head={<span className="modal-title">{DEED_LABEL[deed]}</span>}
          /* 답을 받아야 하는 창이라 바깥을 눌러도 안 닫고 머리의 ✕ 도 안
             둡니다 — ✕ 는 아래 「그만두기」와 같은 일인데, 첫 초점이 ✕ 로
             가면 창이 물은 것에 답하는 자리가 초점 밖에 남습니다. 뜬 순간
             Enter 를 눌러도 아무 일이 안 나야 합니다(주문 확인창과 한 벌). */
          dismissable={false}
          closable={false}
        >
          {text !== null && (
            <dl className="run-confirm">
              <div className="run-confirm-row">
                <dt>주문</dt>
                <dd>{text.order}</dd>
              </div>
              <div className="run-confirm-row">
                <dt>보유분</dt>
                <dd>{text.holding}</dd>
              </div>
            </dl>
          )}
          {everyone ? (
            <p className="run-confirm-title">{`도는 검증 ${running}개에 겁니다`}</p>
          ) : (
            <>
              {/* 세는 것은 **요청이 실제로 나가는 건수**이고, 빠지는 줄은 목록에
                  두되 왜 빠지는지를 그 줄에 답니다. */}
              <p className="run-confirm-title">
                적용 범위 {applied.length}건
                {excluded.length > 0 && ` (제외 ${excluded.length}건)`}
              </p>
              <ul className="run-confirm-list">
                {chosen.map((run) => {
                  const skip = skipWhy(deed, run)
                  const said = nameOf(run.version)
                  return (
                    <li key={run.id} className={skip !== null ? 'run-confirm-skip' : undefined}>
                      {RUN_KIND_LABEL[run.mode]} · {said.name} {said.version} ·{' '}
                      {shortInstrument(run.code)}
                      {skip !== null && <span className="run-confirm-skip-why"> · {skip}</span>}
                    </li>
                  )
                })}
              </ul>
            </>
          )}
          <p className="run-confirm-why" id="vrf-confirm-why">
            {noneWhy}
          </p>
          <div className="run-confirm-acts">
            <button type="button" className="btn btn-quiet" onClick={() => setDeed(null)}>
              그만두기
            </button>
            {/* 창을 연 뒤 상태가 바뀌어 나갈 줄이 없어졌으면 누를 것이 없습니다. */}
            <button
              type="button"
              className="btn btn-heavy"
              aria-disabled={none}
              aria-describedby={none ? 'vrf-confirm-why' : undefined}
              onClick={() => !none && void commit(deed)}
            >
              {DEED_LABEL[deed]}
            </button>
          </div>
        </Modal>
        )
      })()}
    </div>
  )
}

/* 검증 추가 — 전략·버전 → 종목·월물·세션 → 수량·한도 → 실행 자금·체결 가정
 * 순서입니다(원본 §6). 추가한다고 이미 도는 검증을 건드리지 않습니다. */
/** 고른 버전을 저장하는 중일 때의 까닭. 목록의 저장 잠금과 같은 말입니다. */
const SAVING_WHY = '저장하는 중입니다'

function VerifyAddForm({
  rows,
  savingId,
  seed,
  why,
  onStarted,
  onCancel,
}: {
  /** 고를 수 있는 전략. **목록과 같은 것**을 씁니다 — 새로 만든 전략이 여기
   *  안 보이면 만든 것을 검증할 길이 없습니다. */
  rows: StrategyVersion[]
  /** 지금 서버에 저장하는 중인 버전 id. 고른 버전이 이것이면 시작을 잠급니다 — 그
   *  몇 초 동안 시작하면 서버가 아직 담지 않은 버전으로 실행을 세우게 됩니다. */
  savingId: string | null
  /** 목록에서 들고 온 전략·버전. 없으면 첫 줄로 시작합니다. */
  seed: OpenRequest | null
  /** 서버가 시작을 막은 까닭. **서버 문장 그대로**입니다 — 화면이 같은 검사를
   *  다시 하면 둘이 갈립니다. */
  why: string | null
  onCancel: () => void
  onStarted: () => void
}) {
  const names = [...new Set(rows.map((row) => row.name))]
  const [strategy, setStrategy] = useState(seed?.strategy || (names[0] ?? ''))
  const versions = rows.filter((row) => row.name === strategy).map((row) => row.version)
  const [version, setVersion] = useState(seed?.version || (versions[0] ?? ''))
  /* 창이 새로 열리면 앞 창에서 서버가 막은 까닭을 지웁니다 — 남겨 두면 아직
     누르지도 않은 이번 시작이 막힌 것으로 읽힙니다. 그리기 전에 지워 옛 글이
     한 번도 비치지 않게 합니다. */
  useLayoutEffect(() => {
    patchVerify({ addWhy: null })
  }, [])
  /* 세션과 통화는 **고른 전략의 시장**을 따릅니다 — 해외 전략에 국내 세션을
     세우면 고를 수 없는 조합이 만들어집니다. */
  const row = rows.find((item) => item.name === strategy && item.version === version)
    ?? rows.find((item) => item.name === strategy)
  const market = row?.market ?? 'domestic'
  /* 금액의 통화. 해외인데 담긴 코드가 없으면 품목정보의 통화입니다. */
  const currency = useStrategyCurrency(row ?? null)
  /* 세션은 **키로 다룹니다** — 서버에 보내는 것이 키이고, 화면에 세우는 것은
     글자입니다. 둘을 한 값으로 두면 보낼 때 글자에서 키를 되찾아야 합니다. */
  const sessions = sessionLinesFor(market)
  const [qty, setQty] = useState('1')
  const [cash, setCash] = useState('50000000')
  /* 사용자가 자금 칸을 고쳤는지. 고친 값은 통화가 바뀌어도 덮지 않습니다. */
  const [cashTouched, setCashTouched] = useState(false)
  /* 실행 자금의 기본값은 **그 전략의 통화로** 섭니다(`cashDefaultOf`) — 원 기본값이
     달러 칸에 그대로 서면 5천만 달러로 읽힙니다. 표에 없는 통화는 칸을 비웁니다. 통화를
     아직 모르면(해외 품목정보를 받는 중) 두고, 사용자가 고친 값은 덮지 않습니다. */
  useEffect(() => {
    if (cashTouched) return
    const code = currencyCode(currency)
    if (code) setCash(cashDefaultOf(code) ?? '')
  }, [currency, cashTouched])
  const cashCode = currencyCode(currency)
  const noCashDefault = cash === '' && cashCode !== '' && cashDefaultOf(cashCode) === null
  const [fee, setFee] = useState('0')
  const [sending, setSending] = useState(false)

  /* 이 실행이 붙을 종목. **품목은 전략이 정합니다** — 그것을 바꾸면 다른
     전략입니다. 바꿀 수 있는 것은 **월물**뿐이고, 비워 두면 전략이 정한
     것(「근월 자동」이면 오늘의 근월)입니다: 같은 전략을 다른 달로 돌려 보는
     자리입니다. */
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
  /* 시작할 때 물고 가는 설정은 **담긴 것**입니다 — 안 담긴 초안으로 시작하면
     새로고침 뒤 실행과 버전의 설정이 갈립니다. */
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
  /* 세션 기본값은 **그 전략·버전에 담긴 세션**입니다. 창을 열 때, 전략·버전을
     바꿀 때, 담긴 설정이 늦게 도착했을 때 다시 정합니다 — 그 사이 사용자가 고른
     값은 그대로 둡니다. 담긴 세션이 그 시장 목록에 없으면 시장의 첫째입니다. */
  const savedSession = draft?.aux.session ?? ''
  const savedKey = sessionKeyOf(market, savedSession)
  const [session, setSession] = useState<string>(savedKey)
  useEffect(() => {
    setSession(savedKey)
  }, [row?.id, savedKey])
  /* 전략과 다른 세션으로 돌리는 것은 막지 않고 한 줄로 알립니다. 담긴 세션이 없는
     버전에는 견줄 것이 없어 안 섭니다. */
  const savedLabel = sessions.find((item) => item.label === savedSession)?.label ?? ''
  const sessionNote =
    savedLabel && session !== savedKey
      ? `전략은 ${savedLabel} — 이 실행만 ${sessionLabelOf(session)}으로 돕니다`
      : ''

  async function start() {
    if (!row || !draft || sending || rowSaving) return
    setSending(true)
    const ok = await addRun({
      id: `run-${Date.now()}`,
      versionId: row.id,
      draft,
      market,
      code,
      /* **허브 맥락 키를 보냅니다**(`domestic-day`). 서버가 실행을 그 키로
         담고 방송의 줄도 그 키로 옵니다 — 화면이 문구로 보내면 서버가 한 번
         더 옮겨야 하고, 그 옮기는 자리가 곧 어긋나는 자리입니다. */
      session,
      /* 판정을 지난 값만 여기 옵니다(`runAddWhy`) — 그대로 수로 바꿉니다. */
      qty: Number(qty),
      cash: Number(cash),
      feePerContract: Number(fee),
      /* **이 화면은 종이 장부뿐입니다.** 계좌로 나가는 실행은 진행 화면이
         세우고, 그쪽은 확인창을 지나야 합니다. 여기서 고를 수 있는 자리를
         두지 않는 것이 「여기서 나가는 주문은 없다」를 지키는 길입니다. */
      mode: 'paper',
      approved: false,
    })
    setSending(false)
    if (ok) onStarted()
  }

  /* 시장이 바뀌면 세션도 그 시장의 것으로. 남겨 두면 해외 전략에 「국내 주간」이
     붙은 채 검증이 시작됩니다. */
  const pickStrategy = (name: string) => {
    setStrategy(name)
    const first = rows.find((item) => item.name === name)
    setVersion(first?.version ?? '')
    /* 전략을 바꾸면 골라 둔 월물은 앞 품목의 것입니다 — 남겨 두면 없는
       조합이 섭니다. */
    setMonth('')
  }

  /* 세 칸의 판정 — 진행 화면의 폼과 같은 함수입니다. */
  const bad = runAddWhy({ qty, cash, fee })
  const inputBad = bad.qty !== null || bad.cash !== null || bad.fee !== null
  /* 고른 버전을 저장하는 중인지. 고른 것은 바꾸지 않고 시작만 잠급니다 — 말없이
     다른 버전으로 바꾸면 고른 적 없는 전략이 시작됩니다. */
  const rowSaving = row !== undefined && row.id === savingId
  /* 칸 이름의 단위. 통화를 모르면 괄호를 달지 않습니다. */
  const unitCode = currencyCode(currency)
  const unitTail = unitCode ? `(${unitCode === 'KRW' ? '원' : unitCode})` : ''

  /* 자금과 증거금. **계약당 값은 일반주문 폼의 개시증거금과 같은 곳**(품목정보)에서
     받습니다. 국내 선물만 그 값이 있고, 해외·옵션·스프레드와 품목정보를 아직 못
     받은 때는 「모름」입니다. 칸 값이 틀리면 견주지 않습니다. */
  const futuresHere = market === 'domestic' && row?.productKind === 'futures'
  const info = useProductInfo(futuresHere ? code : '')
  const funds: FundsVerdict | null =
    bad.qty !== null || bad.cash !== null
      ? null
      : futuresHere && info.status === 'ready' && info.row
        ? fundsVerdict(info.row.contractInitialMargin, Number(qty), Number(cash), currency)
        : { kind: 'unknown' }

  const field = (label: string, node: React.ReactNode, why: string | null = null) => (
    <div key={label}>
      <label className="vrf-add-row">
        <span className="vrf-add-label">{label}</span>
        {node}
      </label>
      {/* 안 채운 칸(기본값 없는 통화의 자금)은 경고색, 틀린 값은 오류색입니다. */}
      {why !== null && <p className={`add-field-why${why === NO_CASH_DEFAULT ? ' is-missing' : ''}`}>{why}</p>}
    </div>
  )

  return (
    <div className="vrf-add">
      {field(
        '전략',
        <select
          className="control"
          value={strategy}
          /* 전략을 바꾸면 버전·세션도 그 전략의 것으로 갈아 끼웁니다 — 안 그러면
             없는 조합(다른 전략의 버전, 다른 시장의 세션)이 남습니다. */
          onChange={(e) => pickStrategy(e.target.value)}
        >
          {names.map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>,
      )}
      {field(
        '버전',
        <select
          className="control"
          value={version}
          onChange={(e) => {
            setVersion(e.target.value)
            /* 버전이 바뀌면 월물은 「전략이 정한 것」으로 — 버전마다 품목이 다를 수
               있습니다. */
            setMonth('')
          }}
        >
          {versions.map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>,
      )}
      {/* 종목은 **품목이 정하고 월물만 고릅니다.** 품목 칸을 여기 두면 전략이
          말하는 종목과 다른 종목으로 도는 실행이 생깁니다(규격 §1-1). */}
      {field('종목', <span className="vrf-add-fixed">{instrument || '—'}</span>)}
      {field(
        '월물',
        <select
          className="control"
          value={month}
          aria-label="월물"
          onChange={(e) => setMonth(e.target.value)}
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
          /* 고른 줄에서 키를 되찾습니다. `e.target.value` 는 그냥 글자라 그대로
             담으면 목록에 없는 값도 들어가고, 그 값은 서버가 못 읽습니다. */
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
      {sessionNote && <p className="vrf-session-note">{sessionNote}</p>}
      {field(
        '주문당 수량',
        <input
          className={`control vrf-num${bad.qty !== null ? ' is-bad' : ''}`}
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
          className={`control vrf-num${noCashDefault ? ' is-missing' : bad.cash !== null ? ' is-bad' : ''}`}
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
      {/* 수수료를 0 으로 두면 체결 품질과 순손익이 비용 없는 수가 됩니다
          (규격 §6-6). 기본은 0 이고, 아는 값이 있으면 여기 적습니다. */}
      {field(
        `계약당 수수료${unitTail}`,
        <input
          className={`control vrf-num${bad.fee !== null ? ' is-bad' : ''}`}
          value={moneyText(fee)}
          inputMode="numeric"
          aria-invalid={bad.fee !== null}
          onChange={(e) => setFee(moneyDigits(e.target.value))}
        />,
        bad.fee,
      )}

      {/* 시작하면 무엇이 서는지. 되돌릴 수 없는 자리는 아니지만, 무엇으로
          도는지는 누르기 전에 보여야 합니다(규격 §8 확인창). */}
      <div className="run-final">
        <p className="run-final-title">시작하면 이렇게 돕니다</p>
        {/* 계좌 칸은 **진행의 승인창과 같은 갈래 배지**입니다 — 같은 구조의 두
            시작 확인창이 갈래를 다른 얼굴로 보이면 다른 것을 묻는 것으로
            읽힙니다. 「(가상 장부)」는 이 실행이 무엇으로 도는지 밝히는 말이라
            배지 뒤에 한 급 낮춰 남깁니다. */}
        <div className="run-confirm-row">
          <span>계좌</span>
          <div className="run-kind-value">
            <RunKindBadge kind="paper" short />
            <span className="run-kind-note">(가상 장부)</span>
          </div>
        </div>
        <div className="run-confirm-row">
          <span>실제 계약</span>
          <b>{instrument || '—'}</b>
        </div>
        <div className="run-confirm-row">
          <span>세션</span>
          <b>{sessionLabelOf(session)}</b>
        </div>
        <div className="run-confirm-row">
          <span>수량</span>
          <b>{bad.qty === null ? `주문당 ${qty}계약` : '—'}</b>
        </div>
        {/* 이 실행의 장부가 얼마로 시작하는지. **손익과 증거금이 전부 이
            값에서 나옵니다** — 적어 놓고 안 보여 주면 무엇으로 도는지 모르는
            채 시작하게 됩니다. */}
        <div className="run-confirm-row">
          <span>실행 자금</span>
          <b>{bad.cash === null ? moneyIn(Number(cash), currency) : '—'}</b>
        </div>
        {funds && <FundsNote verdict={funds} qty={Number(qty)} currency={currency} />}
        <div className="run-confirm-row">
          <span>청산 감시</span>
          <b>
            {watchLine(draft?.aux)} · 앱 감시
          </b>
        </div>
        <div className="run-confirm-row">
          <span>수수료</span>
          <b>{bad.fee === null ? `계약당 ${moneyIn(Number(fee), currency)}` : '—'}</b>
        </div>
      </div>
      <p className="vrf-hint">
        실행마다 장부가 따로입니다 — 같은 종목을 여러 전략이 검증해도 서로의 체결을 쓰지 않습니다
      </p>
      <div className="vrf-add-acts">
        {/* 「취소」는 주문 취소와 겹칩니다. 창을 물러나는 낱말은 앱 전체에서
            「그만두기」입니다. */}
        <button type="button" className="btn btn-quiet" onClick={onCancel}>
          그만두기
        </button>
        <button
          type="button"
          className="btn btn-primary"
          aria-disabled={!row || sending || inputBad || rowSaving}
          aria-describedby="vrf-start-why"
          onClick={() => !inputBad && !rowSaving && void start()}
        >
          검증 시작
        </button>
      </div>
      {/* 서버가 막은 까닭이 여기 섭니다 — 시작 검사는 서버가 하고(규격 §9),
          화면은 그 문장을 옮기지 않고 그대로 세웁니다. */}
      <p id="vrf-start-why" className="vrf-hint vrf-start-why">
        {rowSaving ? SAVING_WHY : (why ?? (row ? '' : '고를 전략이 없습니다'))}
      </p>
    </div>
  )
}
