import { resolve } from '../../data/instruments'
import {
  domesticHoursAreCommon,
  domesticHoursFor,
  overseasBreakIsLunch,
  overseasHoursOf,
  type SessionEntry,
} from '../../data/session'
import { kstClock, kstDay, kstParts } from '../../lib/kst'
import type { MarketContext } from '../../lib/types'

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

export function sessionLabel(context: MarketContext, code: string, entry: SessionEntry): string {
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
