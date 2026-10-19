import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { needsLeg, resolve } from '../../data/instruments'
import { masterIndex } from '../../data/master'
import { PAPER_NIGHT_PRICE_TEXT } from '../../data/quotes'
import {
  domesticHoursAreCommon,
  domesticHoursFor,
  overseasBreakIsLunch,
  overseasHoursOf,
  useSession,
  type SessionEntry,
} from '../../data/session'
import { useFlash } from '../../lib/flash'
import { kstClock, kstDay, kstParts } from '../../lib/kst'
import { marketOf, valueWidthOf } from '../../lib/valueWidth'
import { Count, Num, fracWidth, signSpace, toneOf } from '../../lib/number'
import type { MarketContext, ProductKind, Quote } from '../../lib/types'

/* 종목 헤더 — 왼쪽에 종목과 현재가, 오른쪽에 지표 칸들.
 *
 * 「무엇을 보고 있나」와 「얼마인가」는 이어서 읽는 두 마디라 위아래로 붙입니다.
 * 화면 양 끝으로 갈라 두면 그 사이를 눈이 가로질러야 합니다.
 *
 * 지표는 칸마다 두 행이고, 한 행 안에서 라벨이 왼쪽 값이 오른쪽입니다.
 * 라벨을 값 위에 쌓으면 한 항목이 한 줄을 통째로 쓰는데, 좌우로 놓으면 같은
 * 세로에 두 항목이 들어갑니다. 그 차이가 범위 막대를 놓을 자리를 만듭니다.
 *
 * 칸은 균등 폭이 아니라 내용 폭입니다. 항목마다 값의 자릿수가 달라서,
 * 균등하게 나누면 짧은 값 옆이 비고 긴 값이 눌립니다. 대신 값 자리는 그
 * 항목이 낼 수 있는 최대 자릿수로 못 박습니다 — 거래량이 자릿수를 하나
 * 늘리는 순간 오른쪽 칸이 전부 밀리면 안 됩니다.
 *
 * 항목은 시장마다 다릅니다. 해외에는 현물가와 실시간 상·하한가가 오지 않는데,
 * **대체할 값이 있으면 바꾸고(현물가 → 정산가) 없으면 라벨을 남기고 「—」**
 * 입니다(실시간 상하한). 칸째 없애면 같은 자리가 시장마다 다른 값을 가리켜
 * 무엇을 보고 있는지 매번 확인해야 하고, 라벨 없이 비우면 「모른다」가 됩니다.
 *
 * 값마다 거리가 다릅니다 — 장중에 움직이는 것(현재가·거래량), 어제 정해진 것
 * (정산가·해외 미결제), 계약 한 살이의 것(상장 후 최고·최저). 앞의 둘은 여기 있고
 * **계약 한 살이의 값은 품목정보에 있습니다** — 하루 동안 거의 그대로라 장중에
 * 눈이 갈 일이 없는데 자리는 그대로 씁니다.
 */

interface Props {
  quote: Quote
  context: MarketContext
  /** 값이 안 서는 까닭. `withValues` 는 **받아 둔 값이 남아 있는지**입니다 —
   *  남아 있으면 값은 그대로 두고 문구만 덧붙입니다(종목이 그대로면 틀린 값이
   *  아니라 낡은 값입니다). 잘 받았으면 `null` 입니다.
   *
   *  `retry` 못 받음 — 다시 불러 볼 만함 · `rejected` 거절 — 눌러도 같은 답 ·
   *  `empty` 받았는데 값이 아직 없음 — 거래가 없어서라 부를 일이 아님. */
  /** `retry` 못 받음 — 다시 불러 볼 만함 · `rejected` 거절 — 눌러도 같은 답 ·
   *  `empty` 받았는데 값이 아직 없음 · `unasked` **그 시장의 인증 정보가 없어
   *  묻지 않음** — 못 받은 것이 아니라 물을 수 없는 것이라, 다시 받는 단추 대신
   *  설정을 여는 단추가 섭니다. */
  /** `text` 는 거절에 서버가 실어 준 안내 문장입니다(시세 사용 신청이 필요한 거래소).
   *  있으면 그 문장이 「시세를 받지 못했습니다」 자리에 섭니다. */
  failure?: {
    kind: 'retry' | 'rejected' | 'paper' | 'empty' | 'unasked'
    withValues: boolean
    text?: string
  } | null
  /** 다시 받기. 다시 불러 볼 만한 실패(`retry`)에서만 단추가 섭니다. */
  onRetry?: () => void
  /** 설정 창 열기. 인증 정보가 없어 안 물은 때(`unasked`)만 단추가 섭니다. */
  onOpenSettings?: () => void
  /** 이 종목의 값을 아직 못 세웠으면 참. **불러오는 중에도 참입니다** — 그동안
   *  다른 출처의 숫자가 서면 사용자는 그것을 이 종목의 값으로 읽고, 그 값으로
   *  주문을 냅니다. 값 자리를 비우고 라벨과 자리는 그대로 둡니다. */
  valuesHidden?: boolean
  /** 값을 **기다리는 중**인지. 같은 빈 자리라도 기다리는 중에는 「여기 값이 올
   *  자리」를 옅은 블록으로 보이고, 안 올 것이 정해지면 걷습니다 — 실패한 뒤에도
   *  블록이 남으면 「받는 중」으로 읽혀 기다리게 됩니다. */
  valuesLoading?: boolean
  /** 이 값이 언제 것인가(`HH:MM`). **자리가 모자라 실시간이 안 붙은 동안에만**
   *  채워 넘깁니다 — 실시간이 붙어 있으면 값은 방금 것이라 적을 것이 없습니다.
   *  「실시간 아님」처럼 없는 것의 이름을 붙이는 대신, 있는 것(값의 시각)을
   *  적습니다. */
  since?: string
  /** 만기 셀렉트에 설 줄. **부르는 쪽이 문장을 완성해서 넘깁니다** — 잔존일수가
   *  오는 시장과 안 오는 시장이 있어, 헤더가 그것을 알면 시장을 알아야 합니다. */
  months: { code: string; label: string }[]
  /** 제목 아래 서는 회색 한 줄. **스프레드에만 있습니다** — 제목이 마스터 원문
   *  이라 두 다리를 한국어로 한 번 더 적는 자리입니다. 그 밖에는 `null` 이고
   *  줄을 만들지 않습니다. */
  legsLine?: string | null
  /** 주문 대상 종목의 종류. 옵션일 때만 콜풋·행사가 축이 섭니다. 스프레드는
   *  축이 만기 하나라 선물과 같은 얼굴이고, 두 다리는 `legsLine` 이 말합니다. */
  kind: ProductKind
  /* 옵션은 종목을 정하는 축이 셋입니다 — 만기·콜풋·행사가. 셋 다 컨트롤이어야
     합니다. 하나만 글자로 두면 그 축은 헤더에서 바꿀 수 없습니다. */
  /** 고른 콜/풋. 아직 안 골랐으면 `null` 입니다 — 「콜」과 「안 골랐음」은
   *  다른 상태라 기본값으로 뭉개지 않습니다. */
  optionSide: 'call' | 'put' | null
  strike: number | null
  strikes: number[]
  strikeDecimals: number
  onMonthChange: (code: string) => void
  onOptionSideChange: (side: 'call' | 'put') => void
  onStrikeChange: (strike: number) => void
  /** 이 화면 전체에 걸리는 동작. 카드 하나가 아니라 화면 구성에 대한 것이라
   *  카드 머리 띠가 아니라 여기 섭니다 — 띠는 「무슨 카드인가」만 답합니다. */
  actions?: ReactNode
}

/* 후보 행을 못 받았을 때 값 칸이 잡는 폭. **가장 넓은 무리에 맞춥니다** —
 * 좁게 잡으면 값이 칸을 넘겨 옆 칸 라벨 위에 얹히는데, 넓게 잡으면 빈 자리만
 * 생깁니다. 둘 중에는 뒤가 낫습니다. */
const WIDEST_VALUE_CHARS = 12


/* 한 행 — 라벨 왼쪽, 값 오른쪽.
 *
 * 값 자리 폭(`width`)은 그 항목이 낼 수 있는 최대 자릿수입니다. 지금 값
 * 기준으로 두면 값이 커질 때 칸이 넓어지면서 옆 칸이 전부 밀립니다. */
function Row({ label, width, children }: { label: string; width: string; children: ReactNode }) {
  return (
    <div className="hd-metric">
      <dt>{label}</dt>
      <dd style={{ minWidth: width }}>{children}</dd>
    </div>
  )
}

/* 한 칸 — 두 행과 왼쪽 구분선.
 *
 * 행이 하나뿐인 칸은 위 행에 붙입니다. 가운데 두면 두 줄로 나란한 다른 칸
 * 사이에서 어느 줄도 아닌 자리에 떠서 세 번째 줄처럼 보입니다. */
function Cell({ children }: { children: ReactNode }) {
  return <dl className="hd-cell">{children}</dl>
}

/* 양 끝 값 사이에서 지금 어디에 있는지를 점 하나로 보여줍니다.
 *
 * 벽까지 얼마 남았는지는 숫자 둘을 빼서 알 값이 아니라 눈으로 볼 값입니다.
 * 양 끝 숫자를 그대로 두고 그 사이에 위치만 얹는 것이라 잃는 정보가 없습니다.
 *
 * 저가와 고가가 같은 날(장 시작 직후·단일가)에도 트랙을 그리고 점을 가운데
 * 둡니다. 막대를 숨기면 「아직 범위가 없음」이 「값이 없음」으로 읽힙니다. */
function RangeRow({
  label,
  low,
  high,
  at,
  decimals,
  fraction,
}: {
  label: string
  low: number | null
  high: number | null
  /** 트랙 위에 점을 찍을 자리(현재가). 아직 값이 없으면 `null` 이고 점을 안 찍습니다. */
  at: number | null
  decimals: number
  fraction?: number | null
}) {
  /* 양 끝 중 하나라도 없으면 **아직 범위가 안 생긴 것**입니다 — 그날 거래가 없는
     종목은 고가·저가가 안 옵니다. 틀(라벨·트랙)과 높이는 그대로 두고 값 자리만
     비웁니다. 「—」를 세우지 않습니다 — 「—」는 이 시장에 원래 없는 값의 것이고,
     이 값은 거래가 생기면 옵니다. 점은 놓을 자리가 없어 안 그립니다. */
  const known = low !== null && high !== null && at !== null
  const span = known ? (high as number) - (low as number) : 0
  const ratio = span > 0 ? Math.min(1, Math.max(0, ((at as number) - (low as number)) / span)) : 0.5

  return (
    <div className="hd-range">
      <dt>{label}</dt>
      <dd className="hd-range-end">
        {low !== null && <Num value={low} decimals={decimals} fraction={fraction} />}
      </dd>
      {/* 점은 방향색을 쓰지 않습니다. 말하는 것이 방향이 아니라 위치라,
          빨강·파랑을 입히면 옆의 전일대비와 뜻이 겹칩니다. */}
      <span className="hd-range-track" aria-hidden="true">
        {known && <span className="hd-range-dot" style={{ left: `${ratio * 100}%` }} />}
      </span>
      <dd className="hd-range-end">
        {high !== null && <Num value={high} decimals={decimals} fraction={fraction} />}
      </dd>
    </div>
  )
}

/* 이 시장에 원래 없는 범위 행(해외의 실시간 상하한). 줄을 지우지 않고 「—」로
 * 둡니다 — 줄이 사라지면 같은 자리가 시장마다 다른 값을 가리켜, 무엇을 보고
 * 있는지 매번 확인해야 합니다. 「—」는 「아직 안 왔다」가 아니라 「이 시장에는
 * 없다」입니다 — 오늘 아직 안 생긴 값은 위 `RangeRow` 가 빈 채로 둡니다. */
function EmptyRangeRow({ label }: { label: string }) {
  return (
    <div className="hd-range">
      <dt>{label}</dt>
      <dd className="hd-range-none">—</dd>
    </div>
  )
}

/* 거래대금 단위는 시장이 정합니다. 국내는 하루 거래대금이 조 단위까지 가서
 * 백만으로 적으면 여섯 자리가 되고, 억이면 세 자리에 들어갑니다.
 * 단위는 값에 붙여 쓰되 한 급 낮춥니다 — 값과 같은 무게면 자릿수처럼 읽힙니다. */
function Turnover({ value, currency }: { value: number; currency: string }) {
  return currency === '원' ? (
    <>
      <Count value={Math.round(value / 100)} />
      <span className="hd-unit">억원</span>
    </>
  ) : (
    <>
      <Count value={value} />
      <span className="hd-unit">백만 {currency}</span>
    </>
  )
}

/* 지표 띠를 가장 가까운 멈춤 자리에 다시 세웁니다. */
function resnap(scroll: HTMLElement, stops: number[]): void {
  const current = scroll.scrollLeft
  let best = 0
  for (const stop of stops) {
    if (Math.abs(stop - current) < Math.abs(best - current)) best = stop
  }
  /* 반올림하지 않습니다 — 멈춤 자리는 소수라, 반올림하면 칸이 덩어리 밑으로 조금
     들어간 자리로 보냅니다. */
  scroll.scrollLeft = Math.max(0, best)
}

/** 지표 칸마다 멈출지를 정해 칸에 달고, 멈춤 자리들을 돌려줍니다.
 *
 *  칸의 멈춤 자리는 「칸 왼쪽 − 고정 덩어리 폭」입니다. **어느 멈춤에서도 칸이
 *  고정 덩어리 밑에 반쯤 들어가지 않아야 합니다** — 그래서 멈춤은 칸 경계에만
 *  둡니다.
 *
 *  마지막 멈춤은 **그 자리에서 마지막 칸까지 다 보이는 첫 칸**입니다. 그 뒤의
 *  칸에는 멈춤을 달지 않습니다 — 거기까지 밀 까닭이 없습니다. 그 자리가 밀 수
 *  있는 끝보다 뒤면, 모자란 만큼만 트랙 끝에 꼬리를 붙여 닿게 합니다. 꼬리는
 *  **넘칠 때만** 붙습니다 — 값이 다 들어가는 창에서는 밀리지 않아야 합니다.
 *
 *  첫 칸은 고정 덩어리와의 간격(`gap`)만큼 떨어져 있어, 그 간격을 칸 앞에 붙여
 *  **밀기 0 을 첫 자리로** 둡니다. 안 붙이면 처음 열 때 띠가 그 간격만큼 밀린
 *  채로 섭니다.
 *
 *  **한 번에 셈합니다.** 붙여 둔 꼬리까지 다시 재서 셈하면 답이 서로 물려
 *  흔들립니다 — 꼬리를 뺀 폭으로만 셉니다. */
function placeStops(scroll: HTMLElement, metrics: HTMLElement, leftWidth: number): number[] {
  const cells = [...scroll.querySelectorAll<HTMLElement>('.hd-cell')]
  const tail = Number.parseFloat(metrics.style.getPropertyValue('--hd-tail-w')) || 0
  const end = scroll.scrollWidth - tail - scroll.clientWidth
  const overflows = end > 0.5
  const boxes = cells.map((cell) => cell.getBoundingClientRect())
  const begins = boxes.map((box) => trackLeft(scroll, box) - leftWidth)
  const total = boxes.length > 0 ? begins[begins.length - 1] + boxes[boxes.length - 1].width : 0
  const track = scroll.clientWidth - leftWidth
  const last = begins.find((at) => at + track >= total - 0.5) ?? 0
  const stops: number[] = []
  cells.forEach((cell, at) => {
    const begin = begins[at]
    cell.style.scrollMarginLeft = at === 0 && begin > 0 ? `${begin}px` : ''
    const here = overflows && (at === 0 || begin <= last + 0.5)
    cell.style.scrollSnapAlign = here ? 'start' : ''
    if (here) stops.push(at === 0 ? 0 : begin)
  })
  /* 밀기 한도는 정수로 잘리므로 한 자리 넉넉히 둡니다. */
  const need = overflows ? last - end : 0
  metrics.style.setProperty('--hd-tail-w', `${need > 0 ? Math.ceil(need) + 1 : 0}px`)
  return stops
}

/** 띠 안 요소의 왼쪽 자리를 **밀기 0 기준**으로. 스크롤 값과 같은 단위입니다.
 *  `offsetLeft` 는 정수로 잘려 소수 픽셀 배율에서 멈춤 자리가 칸 경계와 어긋나,
 *  칸이 덩어리 밑으로 조금씩 들어갑니다 — 그래서 소수까지 나오는 상자 좌표로 잽니다. */
function trackLeft(scroll: HTMLElement, box: DOMRect): number {
  return box.left - scroll.getBoundingClientRect().left - scroll.clientLeft + scroll.scrollLeft
}

/* 헤더의 거래시간 자리에 서는 한 마디 — **세션은 서버가 답한 값**입니다.
 *
 * 시계를 보고 「지금 야간이다」라고 주장하지 않습니다. 서버의 판정(`/api/session`)
 * 이 상태를 주고, 시각은 그 판정이 준 구간(국내는 시간표의 세션 창)에서 옵니다.
 * 색은 없습니다 — 정상에는 색을 쓰지 않습니다.
 *
 * 꼴은 셋뿐입니다 — 열려 있으면 「{세션} {시작~끝}」, 열리기 전이면 「개장 전 ·
 * {세션} 개장 HH:MM」, 닫혔으면 「장 마감 · 다음 개장 {때}」. 단일가는 체결 방식이
 * 다른 유일한 구간이라 「주간 단일가 · 마감 HH:MM」으로 적습니다. 해외는 세션이
 * 하나라 세션 낱말 대신 「개장」이 서고(1차·2차·거래일 넘김을 가르지 않습니다 —
 * 사용자가 할 일이 같습니다), 정비 시간은 「정비 중 · 재개 HH:MM」입니다.
 *
 * 마감은 **시세 상태가 아닙니다.** 값이 있고 안 바뀌는 것이 정상이라 마지막 값을
 * 그대로 두고, 이 자리가 다음 개장을 말합니다. 다음 개장 시각은 서버가 준 것이고
 * 화면이 계산하지 않습니다 — 휴장일은 모릅니다. 오늘이 최종거래일이면 장중에는
 * 꼬리 「· 최종거래일」이 붙고(끝 시각만으로는 지나치기 쉽습니다), 마감 뒤에는 다음
 * 개장이 없어 「최종거래일 마감」입니다.
 *
 * 세션을 아직 못 들었거나(묻는 중·못 받음) 서버도 모르면(`unknown`) 시간표의
 * 거래시간만 접두어 없이 적습니다 — 「마감」이라 하면 모르는 것을 아는 척하는
 * 것이고, 「모름」을 세우면 정상 화면에 상시 배지가 됩니다. */
/** 해외 품목이 거래시간표에 없을 때 시간 자리에 서는 말. */
const NO_HOURS = '거래시간 정보 없음'

function sessionLabel(context: MarketContext, code: string, entry: SessionEntry): string {
  const said = sessionWords(context, code, entry)
  /* 시각이 그 종목 품목 줄이 아니라 **시장 공통 표**에서 온 것이면 그 사실을 한
     마디로 답니다. 비우지 않는 것은 시간표에 줄이 있는 종목이 열에 하나꼴이기
     때문입니다 — 없는 쪽을 비우면 시각이 대부분의 화면에서 사라지는데, 15분
     어긋난 참고값의 손해는 한 번이고 시각이 없는 손해는 매번입니다.
     판정이 함께 준 시각(다음 개장·재개)에도 같은 꼬리가 걸립니다: 품목 줄이
     없으면 서버 판정도 그 표로 내려가 결국 같은 출처입니다.
     **시각이 없는 줄에는 안 답니다** — 「최종거래일 마감」에는 가리킬 값이
     없습니다. */
  if (!/\d{1,2}:\d{2}/.test(said)) return said
  const item = resolve(code)
  /* 판정이 없으면 몸통은 주간 창이고, 있으면 그 판정의 세션 창입니다. 야간 개장
     전의 시각은 야간 개장 시각이라 야간으로 봅니다. */
  const usable = entry.status === 'ready' && entry.source !== 'unknown' && entry.state !== null
  const session =
    usable && entry.state === 'pre-night' ? 'night' : usable && entry.session ? entry.session : 'day'
  const common =
    context !== 'overseas' &&
    domesticHoursAreCommon(item?.product.tradeCode ?? null, item?.kind ?? 'futures', session)
  return common ? `${said} · 시장 공통` : said
}

/** 위 띠가 세울 말. 출처 꼬리를 뺀 몸통입니다. */
function sessionWords(context: MarketContext, code: string, entry: SessionEntry): string {
  const usable = entry.status === 'ready' && entry.source !== 'unknown' && entry.state !== null
  /* 해외 품목이 시간표에 없으면 **그렇다고 적습니다** — 시장 공통 시각으로 채우면
     그 품목의 시간이 아닌 것을 그 품목의 시간으로 읽습니다. */
  if (!usable) return staticHours(context, code) || (context === 'overseas' ? NO_HOURS : '')
  const tail = entry.lastTradingDay ? ' · 최종거래일' : ''
  const at = (iso: string | null, text: (clock: string) => string, none: string) => {
    const clock = clockOf(iso)
    return clock ? text(clock) : none
  }
  switch (entry.state) {
    case 'closed': {
      if (entry.lastTradingDay && entry.nextOpen === null) return '최종거래일 마감'
      return at(entry.nextOpen, (next) => `장 마감 · 다음 개장 ${next}`, '장 마감')
    }
    case 'break': {
      /* 한낮의 쉼은 점심 휴장입니다(홍콩 13:00~14:00 등). 「정비」라 하면 거래소
         설비를 손보는 시간처럼 읽힙니다. 쉼 구간은 그 품목 시간표에서 읽습니다. */
      const item = resolve(code)
      const lunch =
        context === 'overseas' && overseasBreakIsLunch(item?.product.exchangeNo ?? null, item?.product.code ?? '')
      const word = lunch ? '점심 휴장' : '정비 중'
      return at(entry.until, (resume) => `${word} · 재개 ${resume}`, word) + tail
    }
    case 'pre-open':
      return at(entry.until, (open) => `개장 전 · 주간 개장 ${open}`, '개장 전 · 주간') + tail
    case 'pre-night':
      return at(entry.until, (open) => `개장 전 · 야간 개장 ${open}`, '개장 전 · 야간') + tail
    case 'closing-auction':
      return at(entry.until, (close) => `주간 단일가 · 마감 ${close}`, '주간 단일가') + tail
    case 'day':
      return `주간 ${domesticWindow('day', code, entry)}`.trimEnd() + tail
    case 'night':
      return `야간 ${domesticWindow('night', code, entry)}`.trimEnd() + tail
    default:
      /* open · open-2 · next-day — 그 구간의 시작~끝. 서버가 구간을 안 주면 시간표. */
      {
        const span = segmentText(entry) || staticHours(context, code)
        if (!span && context === 'overseas') return `장중 · ${NO_HOURS}` + tail
        return `개장 ${span}`.trimEnd() + tail
      }
  }
}

/** 판정이 없을 때 서는 시간 — 시간표의 정적 거래시간입니다. **그 품목의 창**이
 *  먼저이고, 국내는 품목 줄이 없으면 시장 공통 창입니다(꼬리가 그 사실을
 *  말합니다). 해외는 표에 그 품목이 없으면 빈 문자열이라 자리가 빕니다. */
function staticHours(context: MarketContext, code: string): string {
  const item = resolve(code)
  if (context === 'overseas') return overseasHoursOf(item?.product.exchangeNo ?? null, item?.product.code ?? '')
  return domesticHoursFor(item?.product.tradeCode ?? null, item?.kind ?? 'futures', 'day').text
}

/** 국내 세션의 창. **그 품목 줄의 창**을 쓰되, 오늘이 최종거래일이면 끝을 그날의
 *  마감 시각으로 바꿉니다 — 품목 줄은 보통 날의 창이고, 최종거래일의 마감은
 *  서버가 종목별로 줍니다. 품목 줄이 없는 종목은 시장 공통 창입니다. */
function domesticWindow(session: 'day' | 'night', code: string, entry: SessionEntry): string {
  const item = resolve(code)
  const window = domesticHoursFor(
    item?.product.tradeCode ?? null,
    item?.kind ?? 'futures',
    session,
  ).text
  const close = clockOf(entry.lastTradingDay?.closeAt ?? null)
  if (!window || !close) return window
  const start = window.split('~')[0]
  return `${start}~${close}`
}

/** 서버가 준 구간의 시작~끝. 끝이 다음 날이면 「익일」을 붙입니다. */
function segmentText(entry: SessionEntry): string {
  if (!entry.since || !entry.until) return ''
  const since = new Date(entry.since)
  const until = new Date(entry.until)
  if (Number.isNaN(since.getTime()) || Number.isNaN(until.getTime())) return ''
  const nextDay = kstDay(until) !== kstDay(since)
  return `${clockOnly(since)}~${nextDay ? '익일 ' : ''}${clockOnly(until)}`
}

/** 한국시간 「HH:MM」. 거래시간은 한국시간이라 PC 시간대와 무관하게 읽습니다. */
function clockOnly(at: Date): string {
  return kstClock(at)
}

/** ISO 시각을 「HH:MM」으로. **오늘이 아니면 날을 앞에 붙입니다** — 주말의
 *  「다음 개장 08:45」는 내일이 아니라 월요일이라, 시각만 적으면 거짓이 됩니다.
 *  내일은 「내일」, 그 뒤는 「M/D」(요일 이름은 「월」이 월물의 「월」과 겹칩니다). */
function clockOf(iso: string | null): string {
  if (!iso) return ''
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return ''
  const clock = clockOnly(at)
  /* 「오늘·내일」도 한국 달력으로 셉니다. */
  const days = kstDay(at) - kstDay(Date.now())
  if (days === 0) return clock
  if (days === 1) return `내일 ${clock}`
  const { month, day } = kstParts(at)
  return `${month}/${day} ${clock}`
}

export function InstrumentHeader({
  quote,
  context,
  failure,
  onRetry,
  onOpenSettings,
  valuesHidden = false,
  valuesLoading = false,
  since = '',
  months,
  legsLine = null,
  kind,
  optionSide,
  strike,
  strikes,
  strikeDecimals,
  onMonthChange,
  onOptionSideChange,
  onStrikeChange,
  actions,
}: Props) {
  const d = quote.decimals
  /* 스프레드는 값이 음수로 섭니다. **부호 한 칸을 미리 잡습니다** — 값이 오는
     순간 열이 한 글자 넓어지면 옆의 지표가 통째로 밀립니다. */
  const price = fracWidth(d, signSpace(quote.kind), quote.fraction)
  const overseas = context === 'overseas'
  /* 세션은 종목마다 서버에 묻습니다. 행사가를 아직 안 고른 옵션 자리는 부를 코드가
     아니라 안 묻고 거래시간만 적습니다. */
  const session = useSession(overseas ? 'overseas' : 'domestic', needsLeg(quote.code) ? '' : quote.code)
  const hours = sessionLabel(context, quote.code, session)
  const pending = needsLeg(quote.code)
  /* 분수로 부르는 품목이면 값 그리는 자리가 소수 대신 분수로 적습니다
     (해외 `pind` 가 글자인 23품목 — 국채·곡물). 값은 같습니다. */
  const fraction = quote.fraction

  /* 실시간이 현재가를 갈아 끼우면 그 자리를 잠깐 비춥니다. 헤더에서 가장 큰
     값이라 화면 어디를 보고 있어도 여기서 움직임이 잡힙니다.
     **값이 안 서는 동안에는 안 비춥니다** — 그때 자리를 지키는 것은 이 종목의
     값이 아니라 빈칸입니다. */
  const flash = useFlash(valuesHidden ? null : quote.last, quote.code)

  /* 값이 서는 칸의 폭. **색인이 보낸 후보 행을 이 자리에 그려 보고 잽니다** —
     자릿수만으로는 못 정합니다. 소수를 많이 쓰는 상품은 값 자체가 작아서
     (국채 110.03125) 네 자리짜리 곡물(1,288.0000)보다 오히려 짧습니다.

     그리기 전에 재야 하므로 `useLayoutEffect` 입니다. 칠하기 전에 폭이
     정해져, 넓었다 좁아지는 것이 눈에 안 띕니다. */
  const metricsRef = useRef<HTMLDivElement>(null)
  const [priceWidth, setPriceWidth] = useState(`${WIDEST_VALUE_CHARS}ch`)
  useLayoutEffect(() => {
    const width = valueWidthOf(
      metricsRef.current,
      /* 값이 실제로 서는 칸 하나를 본으로 줍니다 — 재는 자리(띠)와 글꼴이
         다릅니다(띠 15/400, 값 칸 14/600). */
      metricsRef.current?.querySelector('.hd-metric dd') ?? null,
      'header',
      masterIndex(),
      marketOf(context),
      d,
      fraction ? 'fraction' : 'decimal',
    )
    setPriceWidth(width === null ? `${WIDEST_VALUE_CHARS}ch` : `${width}px`)
  }, [context, d, fraction])

  /* 미는 자리를 **칸 단위**로 만듭니다.
   *
   * 고정된 왼쪽 덩어리 밑으로 칸이 반쯤 들어가면 라벨의 앞 글자가 잘려
   * 「미결제」가 「결제」로 읽힙니다 — 둘 다 있는 말이라 잘린 줄도 모릅니다.
   * 그래서 칸마다 멈추게 하고(`scroll-snap`), 멈출 자리를 고정 덩어리의
   * **오른쪽 모서리**로 잡습니다(`scroll-padding-left`).
   *
   * 트랙 끝의 여백은 **넘칠 때만, 마지막 멈춤 자리에 닿는 데 모자란 만큼만**
   * 붙입니다. 값이 다 들어가는 창에서는 밀리지 않아야 하고, 여백을 늘 두면 그
   * 폭만큼 늘 넘칩니다.
   *
   * 고정 덩어리의 폭은 종목마다 다릅니다(선물·옵션·해외가 다 다름). CSS 안에서
   * 알 수 없어 여기서 재어 변수로 넘깁니다. */
  const scrollRef = useRef<HTMLDivElement>(null)

  /* **종목이 바뀌면 지표 띠를 처음으로 되돌립니다.**
   *
   * 이 띠는 같은 요소라 종목이 바뀌어도 밀어 둔 자리가 그대로 남습니다. 앞
   * 종목에서 오른쪽 끝까지 밀어 두었으면 새 종목의 헤더가 **가운데부터**
   * 열리고, 그 종목의 첫 칸(당일범위)이 안 보입니다 — 칸 구성이 시장마다
   * 달라서, 앞 종목에서 멀쩡하던 자리가 새 종목에서는 트랙 끝일 수 있습니다.
   * 새 종목은 처음부터 보는 것이 맞습니다. 그리기 전에 되돌려, 앞 종목의 자리가
   * 한 번이라도 칠해지지 않게 합니다.
   */
  useLayoutEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollLeft = 0
  }, [quote.code])
  const leftRef = useRef<HTMLDivElement>(null)
  /* 마지막으로 잰 덩어리 폭. 폭이 달라진 것을 알아야 띠를 다시 멈춰 세웁니다. */
  const leftWidthRef = useRef<number | null>(null)
  /* 멈춤 자리를 다시 세는 일. 크기 관찰자 밖에서도 부릅니다(아래). */
  const applyRef = useRef<(() => void) | null>(null)
  /* 폭을 재고 멈춤 자리를 다는 일은 **그리기 전에** 합니다. 첫 칠이 멈춤 자리
     없이 나가면, 그 순간의 자리가 처음 자리로 남습니다.
     세 요소는 헤더가 사는 동안 그대로라 한 번만 붙이고, 크기가 바뀔 때마다
     크기 관찰자가 다시 잽니다 — 값이 길어져 지표 칸이 넓어지는 것도 봅니다. */
  useLayoutEffect(() => {
    const scroll = scrollRef.current
    const left = leftRef.current
    const metrics = metricsRef.current
    if (!scroll || !left || !metrics) return
    const apply = () => {
      const leftWidth = left.getBoundingClientRect().width
      /* **신원 덩어리와 첫 칸 사이 여백은 그 덩어리 안에 둡니다**(`trade.css` 의
         `.hd-left` 오른쪽 안쪽 여백). 여백을 덩어리 밖에 두면 민 화면에서 그
         띠에 앞 칸의 꼬리가 비쳐 부분 칸이 생깁니다 — 덩어리는 불투명하고
         고정이라, 안에 두면 밑으로 지나가는 것을 가립니다. 여기서 재는 폭에
         그 여백이 이미 들어 있으므로 멈춤 자리도 저절로 맞습니다. */
      /* 반올림하지 않습니다 — 멈춤 자리는 잰 폭 그대로 셈하므로, 여기만 반올림하면
         모든 멈춤이 그 차이만큼 덩어리 밑으로 들어갑니다. */
      scroll.style.setProperty('--hd-left-w', `${leftWidth}px`)
      const stops = placeStops(scroll, metrics, leftWidth)
      /* **설 자리가 하나뿐이면 칸 단위 밀기를 끕니다.** 반드시 어느 자리에는
         서게 해 둔 채 설 자리가 하나면, 밀어도 매번 그 자리로 되돌아와 띠가
         잠깁니다. */
      scroll.toggleAttribute('data-snaps', stops.length > 1)
      /* **덩어리 폭이 바뀌면 띠를 다시 멈춰 세웁니다.** 거래시간 문장이 길어지면
         (「주간」→「장 마감 · 다음 개장 18:00」) 덩어리가 넓어지는데, 멈춤 자리
         (`scroll-padding-left`)만 바뀌고 브라우저는 밀린 자리를 다시 맞추지 않아
         첫 칸이 덩어리 밑에 반쯤 들어간 채 남습니다 — 좁은 창에서 그렇습니다.
         가장 가까운 칸 경계로 옮겨, 보던 칸은 그대로 두고 부분 칸만 없앱니다. */
      const previous = leftWidthRef.current
      leftWidthRef.current = leftWidth
      if (previous !== null && Math.abs(previous - leftWidth) >= 1) {
        /* 브라우저는 폭이 바뀌면 보던 칸을 그 자리에 붙들어 두려고 밀린 자리를
           제 나름으로 옮깁니다 — 그래서 칸이 덩어리 밑에 들어갑니다. 멈춤 자리를
           새로 준 지금 한 번, 그리고 다음 그리기가 또 옮겼을 때를 위해 한 번 더. */
        resnap(scroll, stops)
        window.requestAnimationFrame(() => {
          window.requestAnimationFrame(() => resnap(scroll, stops))
        })
      }
    }
    apply()
    applyRef.current = apply
    const watch = new ResizeObserver(apply)
    watch.observe(scroll)
    watch.observe(left)
    watch.observe(metrics)
    return () => {
      watch.disconnect()
      applyRef.current = null
    }
  }, [])
  /* **종목이 바뀌면 크기와 상관없이 다시 셉니다** — 시장마다 칸 구성이 달라,
     띠 전체 폭이 우연히 같으면 크기 관찰자는 돌지 않고 앞 종목의 칸 경계가
     멈춤 자리로 남습니다. */
  useLayoutEffect(() => {
    applyRef.current?.()
  }, [quote.code, context])


  /* 거래대금·미결제는 **해외 현재가에 없는 값**입니다 — 그때 「—」입니다. 「아직 안
     왔다」가 아니라 「이 시장에는 없다」이고, 줄은 지우지 않습니다(줄이 사라지면 같은
     자리가 시장마다 다른 값을 가리킵니다). */
  const volumeCell = (
    <Cell>
      {/* 거래량이 안 왔으면 빈 채입니다 — 거래가 생기면 오는 값이라 「—」(원래 없음)가
          아닙니다. */}
      <Row label="거래량" width="9ch">
        {quote.volume !== null && <Count value={quote.volume} />}
      </Row>
      <Row label="거래대금" width="9ch">
        {quote.turnover === null ? (
          <span className="hd-none">—</span>
        ) : (
          <Turnover value={quote.turnover} currency={quote.currency} />
        )}
      </Row>
    </Cell>
  )

  const openInterestCell = (
    <Cell>
      <Row label="미결제" width="9ch">
        {quote.openInterest === null ? (
          <span className="hd-none">—</span>
        ) : (
          <Count value={quote.openInterest} />
        )}
      </Row>
      {/* 부호만 쓰고 색은 쓰지 않습니다. 미결제가 늘어난 것은 값이 오른
          것이 아니라 계약이 쌓인 것이라, 상승색을 입히면 다른 뜻이 됩니다. */}
      <Row label="미결제대비" width="8ch">
        {quote.openInterestChange === null ? (
          <span className="hd-none">—</span>
        ) : (
          <Count value={quote.openInterestChange} signed />
        )}
      </Row>
    </Cell>
  )

  /* 해외에는 정산가가 있고 짝이 없습니다. 아래를 비우고 위에 붙입니다. */
  const priceCell = overseas ? (
    <Cell>
      <Row label="정산가" width={priceWidth}>
        {quote.settlement === undefined ? (
          <span className="hd-none">—</span>
        ) : (
          <Num value={quote.settlement} decimals={d} fraction={fraction} />
        )}
      </Row>
    </Cell>
  ) : (
    <Cell>
      {/* 야간에는 현물이 없어 값이 안 옵니다 — 그때 「—」입니다. 0 으로 그리면 현물이
          0 이라는 거짓이 됩니다. */}
      <Row label="현물가" width={priceWidth}>
        {quote.spot === undefined ? (
          <span className="hd-none">—</span>
        ) : (
          <Num value={quote.spot} decimals={d} fraction={fraction} />
        )}
      </Row>
      {/* 대비는 차이라 값 자체보다 작지만 부호가 한 자리를 더 씁니다.
          같은 폭으로 두면 두 값의 소수점이 세로로 맞습니다. */}
      <Row label="현물가대비" width={priceWidth}>
        {quote.spotChange === undefined ? (
          <span className="hd-none">—</span>
        ) : (
          <Num value={quote.spotChange} decimals={d} fraction={fraction} signed toned />
        )}
      </Row>
    </Cell>
  )

  /* 좁은 범위 위에 그것을 품는 넓은 범위. 점 둘이 같은 현재가를 두 자로
     잽니다 — 위는 「오늘 움직인 폭 안에서 지금 어디」, 아래는 「거래가 멈추는
     벽까지 얼마나 남았나」입니다. */
  const rangeCell = (
    <Cell>
      <RangeRow
        label="당일범위"
        low={quote.low}
        high={quote.high}
        at={quote.last}
        decimals={d}
        fraction={fraction}
      />
      {overseas ? (
        /* 해외에는 실시간 상하한이 오지 않습니다. */
        <EmptyRangeRow label="실시간 상하한" />
      ) : (
        /* 상하한 단계가 넓어지면 트랙 양 끝이 바깥으로 뛰고 점이 가운데로
           돌아옵니다. 사건이라 부드럽게 넘기지 않습니다 — 값이 서서히
           변한 것처럼 보이면 안 됩니다.
           상하한이 안 왔으면 값 자리를 비웁니다 — 저가·고가로 대신 그리면 한
           자리가 두 뜻을 갖습니다. */
        <RangeRow
          label="실시간 상하한"
          low={quote.lowerLimit ?? null}
          high={quote.upperLimit ?? null}
          at={quote.last}
          decimals={d}
          fraction={fraction}
        />
      )}
    </Cell>
  )

  /* 헤더는 접지 않습니다. 폭이 모자라면 배치를 바꾸는 대신 화면이 가로로
     밀립니다 — 창을 줄였다고 종목코드가 사라지거나 지표가 아랫줄로 내려가면,
     같은 값을 창 크기마다 다른 자리에서 찾게 됩니다. */

  return (
    <header className="instrument-header">
      {/* 밀리는 것은 값이 든 이 안쪽뿐입니다. 화면 전체에 걸리는 동작(오른쪽
          `hd-actions`)은 밖에 두어 어느 창에서도 제자리에 섭니다 — 되돌리는
          길과 패널 편집이 가장 필요한 것은 좁은 창인데, 그 창에서 옆으로
          굴려야 나오면 없는 것과 같습니다. */}
      <div className="hd-scroll" ref={scrollRef}>
      <div className="hd-left" ref={leftRef}>
        {/* 줄 A — 무엇을 보고 있나. */}
        <div className="hd-name">
          {/* 제목과 부제는 한 칸입니다. 부제가 없는 종목에서는 제목 한 줄이라
              지금까지와 같은 높이로 섭니다. */}
          <div className="hd-title">
            <h1 className="t-screen" title={quote.productName}>
              {quote.productName}
            </h1>
            {/* 두 다리를 한국어로 적는 자리. 제목이 마스터 원문(「코스피200 SP
                2612-2703」)이라 만기가 코드에 가까운 표기로만 서는데, 그 표기를
                읽을 수 있는 사람만 어느 두 달인지 알게 됩니다. */}
            {legsLine !== null && <p className="hd-legs">{legsLine}</p>}
          </div>

          {/* 만기를 바꾸면 다른 종목이라 주문 폼이 리셋됩니다.
              잔존일을 목록 안에 둡니다. 닫힌 셀렉터가 고른 만기의 잔존일을
              그대로 보여주므로 늘 보이고, 목록을 열면 만기끼리 견줄 수도
              있습니다 — 옆에 또 적으면 같은 값이 한 줄에 두 번 섭니다. */}
          <select
            className="hd-month"
            value={quote.code}
            aria-label="만기"
            onChange={(event) => onMonthChange(event.target.value)}
          >
            {months.map((item) => (
              <option key={item.code} value={item.code}>
                {item.label}
              </option>
            ))}
          </select>

          {kind === 'option' && (
            <>
              {/* 아직 안 고른 축은 **안 골랐다고 말합니다.** 목록의 첫 값을
                  그리면 고른 적 없는 콜과 행사가가 골라진 것처럼 보이고, 그
                  종목이 주문 폼에 실립니다. 고르고 나면 이 항목은 사라집니다 —
                  되돌아갈 자리가 아니라 아직 안 지난 자리입니다. */}
              <select
                className="hd-month"
                value={optionSide ?? ''}
                aria-label="콜 / 풋"
                onChange={(event) => onOptionSideChange(event.target.value as 'call' | 'put')}
              >
                {optionSide === null && (
                  <option value="" disabled>
                    콜/풋 선택
                  </option>
                )}
                <option value="call">콜</option>
                <option value="put">풋</option>
              </select>

              <select
                className="hd-month"
                value={strike ?? ''}
                aria-label="행사가"
                onChange={(event) => onStrikeChange(Number(event.target.value))}
              >
                {strike === null && (
                  <option value="" disabled>
                    행사가 선택
                  </option>
                )}
                {strikes.map((value) => (
                  <option key={value} value={value}>
                    {value.toFixed(strikeDecimals)}
                  </option>
                ))}
              </select>
            </>
          )}

          {/* 콜/풋과 행사가가 다 정해지기 전에는 종목코드가 아직 없습니다.
              **값 칸이라 값이 없을 때의 표시(「—」)를 씁니다** — 무엇이 남았는지는
              바로 왼쪽 두 셀렉트가 「콜/풋 선택」·「행사가 선택」으로 이미 말하고
              있어, 여기에 같은 말을 또 세우면 한 줄에 같은 글자가 나란히 섭니다.
              값이 아니라 빈자리라 한 급 낮추고 흐림색을 씁니다. */}
          <span className="hd-code">
            {pending ? <span className="hd-code-pending">—</span> : quote.code}
          </span>

        </div>

        {/* 줄 B — 얼마인가. 한 문장으로 읽힙니다.
            「며칠보다」라고 날짜를 적지 않습니다. 국내가 주간·야간으로 갈려
            기준일을 단정할 수 없고, 화면이 아는 것은 「전일」까지입니다. */}
        <div className="hd-quote">
          {/* 못 받았으면 값이 서던 자리가 그 사실을 말합니다. 헤더에서 가장 큰
              값이 현재가라, 없어진 것이 여기서 가장 먼저 보입니다. 값을 아직
              한 번도 못 받았으면 값 자리를 이 문구가 대신하고, 받아 둔 값이
              있으면 값 뒤에 붙습니다 — 그때 값은 틀린 값이 아니라 낡은
              값입니다. */}
          {valuesHidden ? (
            valuesLoading ? <span className="hd-price-wait" aria-hidden="true" /> : null
          ) : (
            <>
              <span className={`hd-price t-price${flash ? ` is-${flash}` : ''}`} style={price}>
                {quote.last !== null && <Num value={quote.last} decimals={d} fraction={fraction} />}
              </span>
              <span className="hd-dot">·</span>
              {/* 국내 야간의 등락은 **그 야간이 딸린 거래일의 주간 정산가**에서 잽니다.
                  「전일보다」로 적으면 어제 값에서 잰 것으로 읽힙니다. 세션은 서버
                  답(`context`)입니다. */}
              <span className="hd-since">
                {context === 'domestic-night' ? '주간 정산가보다' : '전일보다'}
              </span>
              {/* 등락이 안 온 칸은 빈 채입니다 — 0 으로 적으면 「안 움직였다」가 되고,
                  「—」는 이 시장에 원래 없는 값의 말입니다. 「전일보다」 라벨만 남습니다. */}
              <span className="hd-change" style={price}>
                {quote.change !== null && (
                  <Num value={quote.change} decimals={d} fraction={fraction} signed toned />
                )}
              </span>
              <span className={`hd-pct ${quote.change === null ? '' : toneOf(quote.change)}`}>
                {quote.changePct !== null &&
                  `(${quote.changePct > 0 ? '+' : quote.changePct < 0 ? '−' : ''}${Math.abs(quote.changePct).toFixed(2)}%)`}
              </span>
              <span className="hd-dot">·</span>
            </>
          )}
          {/* 값이 언제 것인가. 값 바로 뒤에 붙습니다 — 이 시각이 말하는 것은
              화면이 아니라 그 숫자입니다. 값이 아예 없는 자리에는 안 답니다.
              그때는 「없다」가 먼저입니다. */}
          {!valuesHidden && since && (
            <>
              <span className="hd-at">{since} 기준</span>
              <span className="hd-dot">·</span>
            </>
          )}
          {failure && (
            <span className="hd-failed">
              {/* 「못 받았다」와 「아직 없다」는 사용자가 할 일이 다릅니다 —
                  앞은 다시 불러 볼 만하고 뒤는 거래가 생겨야 값이 섭니다. */}
              <span className="hd-failed-text">
                {failure.kind === 'unasked'
                  ? /* **이 문장은 화면에 한 번만 섭니다.** 화면 전체가 같은 사정일 때는
                       카드마다 제 문장을 세우면 다른 일이 여럿 난 줄로 읽힙니다 —
                       한 번 말하고 나머지 카드는 짧은 표지만 답니다. */
                    `${context === 'overseas' ? '해외' : '국내'} 인증 정보가 없어 시세를 받지 않습니다`
                  : failure.kind === 'empty'
                    ? '아직 시세가 없습니다'
                    : failure.kind === 'paper'
                      ? /* 까닭이 정해진 답이라 그대로 말합니다. 다시 받는 단추도
                           경고색도 없습니다 — 사용자가 고칠 일이 아닙니다. */
                        PAPER_NIGHT_PRICE_TEXT
                      : failure.text || '시세를 받지 못했습니다'}
              </span>
              {/* 거절은 눌러도 같은 답이 옵니다. 그때 다시 받는 길은 이 줄의
                  만기·콜풋·행사가를 바꾸는 것이고, 그 컨트롤이 바로 옆에
                  있습니다. */}
              {failure.kind === 'retry' && (
                <button type="button" className="btn btn-quiet" onClick={onRetry}>
                  다시
                </button>
              )}
              {failure.kind === 'unasked' && onOpenSettings && (
                <button type="button" className="btn btn-quiet" onClick={onOpenSettings}>
                  설정 열기
                </button>
              )}
            </span>
          )}
          {failure && <span className="hd-dot">·</span>}
          {/* 상자에 넣지 않습니다. 이 줄의 상자는 만기와 선물·옵션 둘 다
              누르는 것이라, 안 눌리는 상자를 하나 더 놓으면 눌러 보게 됩니다. */}
          <span className="hd-hours">{hours}</span>
        </div>
      </div>

      {/* 지표 칸 넷. 오른쪽으로 갈수록 「가려져도 다른 곳에서 답을 찾는 값」이
          섭니다 — 창이 좁아 이 띠가 밀리면 오른쪽 끝부터 가려지기 때문입니다.
          범위는 지정가를 어디에 둘지에 곧바로 걸려 가장 먼저 서고, 거래량은 옆
          호가의 잔량 막대가 이미 답하고 있어 마지막입니다. 정산가는 품목정보에도
          있어 여기서 가려져도 찾을 곳이 남습니다. */}
      {/* 소수부 칸 너비를 여기서 한 번 줍니다. 안 주면 `--frac-w` 가 기본값
          3ch 이라, 소수 세 자리가 넘는 품목의 소수부가 제 칸을 넘겨 칠해져
          **옆 칸 라벨 위에 얹힙니다**(호주달러 다섯 자리에서 19px). 값이 서는
          자리는 이 띠 전체가 한 종목이라 띠에 한 번 주면 아래로 다 갑니다. */}
      {/* 값을 못 받았으면 지표 칸을 **빈 채로** 둡니다. 임시 값이 남아 있으면
          그것이 이 종목의 값으로 읽히고, 칸마다 「—」를 넣으면 「이 종목엔 원래
          없는 값」이 됩니다. 자리는 그대로 지킵니다 — 칸이 사라지면 헤더 높이가
          바뀌어 그 아래 화면이 통째로 밀립니다. */}
      <div
        className={`hd-metrics${valuesHidden ? (valuesLoading ? ' is-waiting' : ' is-blank') : ''}`}
        style={price}
        ref={metricsRef}
      >
        {rangeCell}
        {priceCell}
        {openInterestCell}
        {volumeCell}
      </div>

      </div>

      {actions && <div className="hd-actions">{actions}</div>}
    </header>
  )
}
