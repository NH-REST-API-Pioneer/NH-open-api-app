import { resolve, spreadShortName } from '../../data/instruments'
import type { ReconcileCount } from '../../data/strategyStore'
import type { AccountMode, VerifyRun } from '../../data/strategyRuns'
import { kstClockSeconds } from '../../lib/kst'
import type { Environment } from '../../data/environment'

/** 확인 얼굴이 고정한 것 — 어느 계좌 갈래로, 어느 환경을 믿고 세우는지.
 *  **「거래 시작」을 누를 때 한 번 정하고** 확인창과 보내는 요청이 이 값 하나를
 *  씁니다. 승인할 때 다시 셈하면 창에 보인 갈래와 나가는 갈래가 갈릴 수
 *  있습니다. 환경 세대(`generation`)는 창이 떠 있는 동안 환경이 바뀌었는지
 *  보려고 함께 적습니다. */
export interface AskFixed {
  mode: AccountMode
  environment: Environment
  generation: number
}

/** 확인 얼굴의 글자. 갈래마다 한 벌이고, 모의 계좌 쪽은 지금까지의 글자
 *  그대로입니다. */
export const ASK_TEXT: Record<AccountMode, { title: string; approve: string; button: string }> = {
  sim: { title: '모의 계좌 거래 시작', approve: '모의 계좌로 실제 주문이 나갑니다.', button: '승인하고 시작' },
  real: { title: '실전 계좌 거래 시작', approve: '실전 계좌로 실제 주문이 나갑니다.', button: '실전 계좌로 승인하고 시작' },
}

/** 접속 환경을 아직 확인하지 못했을 때 거래 추가 폼에 서는 한 줄. */
export const ENV_WAIT = '접속 환경을 확인하는 중입니다 — 잠시 뒤 다시 누르세요'

/** 서버가 준 시각(ms)을 표에 적는 말(한국시각). **받은 값 그대로**입니다 — 한 봉 안에서
 *  여러 번 체결되므로 초까지 적습니다(검증 화면과 같은 꼴). */
export function clockOf(time: number): string {
  if (!time) return '—'
  return kstClockSeconds(time)
}

/** 줄에 세우는 종목 이름. **검증 화면과 같은 규칙**입니다 — 스프레드는 두
 *  만기를 다 적으면 좁은 열에서 잘리므로 짧은 꼴로 적고, 그 밖에는 색인이
 *  지어 준 이름을 그대로 씁니다. 색인에 없으면 코드입니다. */
export function shortInstrument(code: string): string {
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
export const ORDER_NO_FITS = 645
/** 틱으로 평가하는 실행을 볼 때의 값. 시각 칸이 「틱」 표지 자리만큼 넓어집니다
 *  (84 → 112, `run-col-time.is-tick`). */
export const ORDER_NO_FITS_TICK = 673

/* 「조건」은 검증 탭과 같은 표입니다 — 마지막 판정 봉에서 규칙마다 무엇을 기다리는지. */
export const BOTTOM_TABS = ['최근 체결', '미체결', '이벤트', '조건'] as const
export type BottomTab = (typeof BOTTOM_TABS)[number]

/** 아래 표의 한 줄. **체결과 미체결이 한 꼴로 섭니다** — 줄에 어떤 칸이 있나로
 *  가리면, 서버가 체결 줄에 그 칸을 싣기 시작하는 날 표가 조용히 다른 말을
 *  합니다. 무엇을 적을지는 탭이 정해 두고 그리는 자리는 한 곳입니다. */
export interface TableRow {
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
export const ORDER_STATE_WORD: Record<string, string> = { waiting: '체결 전', partial: '일부 체결' }

/* 「계좌와 대조」를 기다리는 동안 머리 까닭 자리에 서는 글. 단추가 잠긴 까닭도 이 글입니다. */
export const RECONCILING = '계좌와 대조하는 중'

/* 대조 결과가 머무는 시간. 알림 토스트의 짧은 머묾과 같은 값입니다. */
export const NOTE_DWELL = 6000

/* 대조 결과 한 줄. 수는 **서버 답의 수**입니다 — 맞춰 본 실행과 그 가운데
   어긋난 실행. 어긋난 실행이 있으면 「일치」 대신 두 수를 함께 적습니다 —
   「n개 일치」만 적으면 확인이 필요한 실행이 있어도 다 맞은 것으로 읽힙니다.
   답에 수가 없으면 맞춰 봤다는 것만 적습니다. */
export function reconciledText(count: ReconcileCount | null): string {
  const head = '계좌와 대조했습니다'
  if (count === null) return head
  if (count.checked === 0) return `${head} — 맞춰 볼 실행 없음`
  const matched = Math.max(0, count.checked - count.mismatched)
  return count.mismatched > 0
    ? `${head} — 일치 ${matched} · 확인 필요 ${count.mismatched}`
    : `${head} — 실행 ${matched}개 일치`
}

export type Confirm = {
  action: string
  runs: VerifyRun[]
  /** 「전체」인데 목록에 안 서는 실행. 이미 멈춘 것은 다시 멈출 일이 없어
   *  대상에서 빠지는데, 창이 그 수를 안 세면 「내 실행 하나는 어디 갔나」를
   *  창 안에서 답할 수 없습니다. */
  alreadyStopped?: number
} | null

/** 한도 한 칸의 머리 글자. 안 걸었으면 「걸지 않음」입니다.
 *  `digits` 는 그 통화의 자릿수로, 모자라면 0 을 채웁니다. 더 긴 값은 자르지 않고
 *  담긴 그대로 적습니다 — 반올림해 적으면 실제로 걸린 한도와 다른 수가 섭니다. */
export function limitShown(value: number | null, unit: string, digits: number | null = 0): string {
  if (value === null) return '걸지 않음'
  const text = value.toLocaleString('ko-KR', {
    minimumFractionDigits: digits ?? 0,
    maximumFractionDigits: 20,
  })
  return `${text}${unit}`
}
