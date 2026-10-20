import { useSyncExternalStore } from 'react'
import type { Quote } from '../../lib/types'
import { quoteAsked, quoteEntry, quoteHasValues, subscribeQuotes, useDailyBars } from '../../data/quotes'
import type { Span } from './chartSlots'

/** 이 칸 종목의 받아 온 봉과, 봉을 못 세울 때 그 까닭. */
export function useChartQuote({ quote, span }: { quote: Quote; span: Span }) {
  /* 이 종목의 받아 온 분봉. 받는 일은 화면 쪽이 하고 여기서는 읽기만 합니다 —
     같은 종목을 두 칸이 띄워도 요청은 한 번입니다. **조회 때만 바뀌는 참조**라
     체결마다 차트가 다시 서지 않습니다 — 체결로 접은 봉은 아래 구독으로 흐릅니다. */
  const served = useSyncExternalStore(
    subscribeQuotes,
    () => quoteEntry(quote.code).bars,
    () => null,
  )
  /* 일봉은 일봉 탭에서만 받습니다 — 분봉을 보는 자리에서 일봉까지 받으면 종목마다
     조회 하나가 더 나갑니다. 세션과 무관한 주간 일봉이고 체결로 접지 않습니다. */
  const daily = useDailyBars(span === 'day' && !quote.withheld ? quote.code : '')
  /* 물어봤는데 값을 못 세우면 **봉을 안 그립니다.** 임시 봉을 그리면 헤더는
     「받지 못했습니다」인데 차트는 값을 말해, 한 화면이 두 말을 합니다. */
  /* 모의투자라 현재가만 못 받은 것은 봉과 무관합니다 — 받은 봉은 그립니다. */
  const missingAsked = useSyncExternalStore(
    subscribeQuotes,
    () => {
      if (!quoteAsked(quote.code) || quoteHasValues(quote.code)) return false
      const entry = quoteEntry(quote.code)
      return !(entry.failure === 'paper' && entry.bars !== null)
    },
    () => false,
  )
  /* 인증 정보가 없어 안 물은 종목도 봉을 안 그립니다 — 까닭은 헤더가 한 번 말합니다. */
  const missing = quote.withheld === true || missingAsked
  /* 일봉 탭에서 봉을 못 세우는 까닭. 조회가 따로라 사정도 따로입니다 — 못 받았거나,
     받았는데 봉이 없거나(저장해 둔 응답으로 도는 재생에서는 일봉이 0개입니다). */
  const dailyMissing = span === 'day' && (daily.status !== 'ready' || (daily.bars?.length ?? 0) === 0)
  /* **값을 담는 카드라 목적어를 안 붙입니다** — 이 카드가 무엇을 담는 자리인지는
     카드 머리가 이미 말합니다. 불러오는 중에는 아직 할 말이 없어 비워 둡니다. */
  const missingWord = (() => {
    if (quote.withheld) return '조회 전'
    if (span === 'day' && !missing) {
      if (daily.status === 'failed') return '받지 못했습니다'
      return daily.status === 'ready' ? '아직 일봉이 없습니다' : ''
    }
    const entry = quoteEntry(quote.code)
    if (entry.failure) return '받지 못했습니다'
    return entry.status === 'loading' ? '' : '아직 시세가 없습니다'
  })()
  /* 앞으로 이어 받은 날 가운데 **덜 받았을 수 있는 날**이 있었나. 경고가 아니라
     적어 두는 말입니다 — 거래가 드문 먼 월물은 거의 늘 참이라 경고 얼굴로 세우면
     그 종목에서는 늘 서 있게 되고, 그러면 아무도 안 읽습니다. */
  const shortDays = useSyncExternalStore(
    subscribeQuotes,
    () => quoteEntry(quote.code).history.short,
    () => false,
  )

  return { served, daily, missing, dailyMissing, missingWord, shortDays }
}
