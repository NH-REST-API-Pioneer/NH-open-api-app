import { resolve, spreadShortName } from '../../data/instruments'
import {
  FUNDS_SHORT,
  FUNDS_UNKNOWN,
  LEGACY_UNSENT_TITLE,
  isRejectedEvent,
  isUnsent,
  legacyUnsentWhy,
  type FeedState,
  type FundsVerdict,
  type VerifyRun,
} from '../../data/strategyRuns'
import { sessionLabelOf } from '../../data/strategyRules'
import { kstClock, kstClockSeconds } from '../../lib/kst'
import { moneyIn } from '../../lib/number'

/** 시세 자리가 모자랄 때 남을 순서. 주문 대상(9)과 홈 관심종목(3) 사이입니다 —
 *  이 값으로 주문을 내지는 않지만, 멈추면 지금 도는 검증의 근거가 낡습니다. */
export const VERIFY_RANK = 5

/** 아래 탭. **「가상」을 안 붙입니다** — 이 목록에는 종이 실행과 모의 계좌 실행이
 *  함께 서고, 모의 계좌 체결은 실제로 계좌에서 난 것이라 「가상」이 거짓말입니다.
 *  탭은 자리 이름이라 고른 실행에 따라 글자가 바뀌면 같은 자리를 다른 이름으로
 *  기억하게 됩니다 — 무엇의 체결인지는 줄과 머리가 말합니다. */
export const BOTTOM_TABS = ['조건', '체결', '미체결', '이벤트'] as const

/** 아래 표의 한 줄. 두 탭이 한 표를 쓰므로 **그리기 전에 한 꼴로 맞춥니다.**
 *  수량 칸에 무엇이 들어가는지는 탭이 정하고(체결은 채워진 수량, 미체결은 남은
 *  수량), 그린 뒤에는 갈래를 다시 보지 않습니다. */
export interface TableRow {
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
export type BottomTab = (typeof BOTTOM_TABS)[number]

/* 시세가 붙어 있을 때는 색을 쓰지 않습니다. 늘 켜져 있는 초록은 이상이 생겨도
 * 눈에 띄지 않고, 이 앱에서 색은 값의 방향이 갖습니다. */
export const FEED_TONE: Record<FeedState, string> = {
  idle: 'vrf-dot',
  live: 'vrf-dot',
  gap: 'vrf-dot is-warn',
}

/** 시세가 어떤 자리인지 적는 말. `idle` 은 아직 안 붙은 것이고 `gap` 은 오다가
 *  끊긴 것이라 서로 다릅니다. */
export const FEED_LABEL: Record<FeedState, string> = {
  idle: '아직 안 붙음',
  live: '정상',
  gap: '끊김',
}

/** 실행에 거는 동작. **모두 확인 창을 지납니다** — 여러 실행을 한 번에 고르므로
 *  무엇에 걸리고 무엇이 빠지는지를 창이 먼저 보입니다. 중지·재개도 그렇습니다. */
export type Deed =
  | '선택 검증 중지'
  | '선택 검증 재개'
  | '선택 전략 청산'
  | '실행 종료'
  | '실행삭제'
  | '검증 신규 진입 중지'

/** 그 동작의 단추에 적는 말. 확인 창의 제목도 이것입니다. */
export const DEED_LABEL: Record<Deed, string> = {
  '선택 검증 중지': '선택 검증 중지',
  '선택 검증 재개': '선택 검증 재개',
  '선택 전략 청산': '선택 전략 청산',
  '실행 종료': '실행 종료',
  실행삭제: '실행 삭제',
  '검증 신규 진입 중지': '검증 신규 진입 중지',
}

/** 중지·재개 한 단추 뒤에 단추가 서는 차례. 못 누르는 까닭 줄도 이 차례로 섭니다. */
export const DEEDS: readonly Deed[] = ['선택 전략 청산', '실행 종료', '실행삭제', '검증 신규 진입 중지']

/** 실행 하나에 보내는 요청의 이름. 삭제와 전체 중지는 다른 길로 갑니다. */
export const DEED_VERB: Partial<Record<Deed, 'stop' | 'resume' | 'close' | 'end'>> = {
  '선택 검증 중지': 'stop',
  '선택 검증 재개': 'resume',
  '선택 전략 청산': 'close',
  '실행 종료': 'end',
}

/** 그 동작을 가리키는 짧은 이름. **화면 글자가 아니라 코드가 읽는 이름**이라
 *  까닭 줄의 `id` 는 이것으로 섭니다 — 화면 글자를 id 로 쓰면 글자를 고칠 때
 *  단추와 까닭 줄을 잇는 줄이 끊깁니다. */
export const DEED_KEY: Record<Deed, string> = {
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
export function EventText({ kind, reason, text }: { kind: string; reason?: string | null; text: string }) {
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
export function runSessionLabel(run: Pick<VerifyRun, 'session' | 'sessionLabel'>): string {
  return run.sessionLabel || sessionLabelOf(run.session)
}

/** 자금 판정 한 줄 — 모자라면 경고와 그 셈, 모르면 흐린 한 줄, 넉넉하면 없음.
 *  검증 추가 창과 상세가 이것 하나로 적습니다. */
export function FundsNote({ verdict, qty, currency }: { verdict: FundsVerdict; qty: number; currency: string }) {
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
export function shortInstrument(code: string): string {
  const held = resolve(code)
  if (!held?.contract) return code
  return held.contract.kind === 'spread' && held.contract.legs
    ? spreadShortName(held.product.name, held.contract.legs)
    : held.name
}

/** 서버가 준 시각(ms)을 표에 적는 말(한국시각). **받은 값 그대로**의 시각입니다 —
 *  「몇 분 전」으로 적으면 같은 체결이 볼 때마다 다른 글자가 됩니다. 한 봉
 *  안에서 여러 번 체결되므로 초까지 적습니다. */
export function clockOf(time: number): string {
  if (!time) return '—'
  return kstClockSeconds(time)
}

/** 줄 한 칸에 적는 시각. **분까지입니다** — 시세가 언제까지 왔는지는 분이면
 *  충분하고, 초까지 적으면 좁은 열에서 줄이 두 줄로 접힙니다. */
export function minuteOf(time: number): string {
  if (!time) return '—'
  return kstClock(time)
}
