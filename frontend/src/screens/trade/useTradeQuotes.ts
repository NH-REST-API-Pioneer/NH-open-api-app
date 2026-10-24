import { useMemo } from 'react'
import type { MarketContext, PendingAxis, ChainLeg } from '../../lib/types'
import {
  contractsOf,
  expiryOption,
  needsLeg,
  resolve,
  spreadLegsLine,
  type Instrument,
} from '../../data/instruments'
import type { SplitState } from './chartSlots'
import { TRADE_KEEP } from '../../data/quotes'
import { useQuote } from '../../data/instrumentQuote'
import { useStreamStatus, useWishes, wishKey, type Wish } from '../../data/stream'
import { domesticProductDetail, useSession, useTimetable } from '../../data/session'
import type { EnvironmentState } from '../../data/environment'
import { earlierClock, kstMinutes } from '../../lib/kst'
import { SECOND_RANK, SUBJECT_RANK } from './tradeScreenUtils'

/** 주문 대상 종목의 시세·호가·체결과, 그 값을 믿을 수 있는지에 대한 판단. */
export function useTradeQuotes({
  selected,
  secondSelected,
  secondIsSubject,
  subject,
  splitState,
  contextOf,
  credentialsMissing,
  environment,
  activeContext,
  pickedLeg,
  pickedLabel,
  pendingAxis,
}: {
  selected: Instrument | null
  secondSelected: Instrument | null
  secondIsSubject: boolean
  subject: Instrument | null
  splitState: SplitState
  contextOf: (item: Instrument | null) => MarketContext
  credentialsMissing: (item: Instrument | null) => boolean
  environment: EnvironmentState
  activeContext: MarketContext
  pickedLeg: ChainLeg | null
  pickedLabel: string
  pendingAxis: PendingAxis | null
}) {
  /* 두 칸의 시세. **고른 축은 주문 대상인 칸에만 싣습니다** — 양쪽에 실으면
     대상이 아닌 칸까지 그 행사가의 값을 그리고, 그 칸이 든 종목과 갈립니다.
     신원과 시세를 한 자리에서 함께 고르므로 둘이 어긋날 수 없습니다. */
  const first = useQuote(
    selected,
    contextOf(selected),
    secondIsSubject ? null : pickedLeg,
    secondIsSubject ? '' : pickedLabel,
    secondIsSubject ? null : pendingAxis,
    credentialsMissing(selected),
  )
  const second = useQuote(
    secondSelected,
    contextOf(secondSelected),
    secondIsSubject ? pickedLeg : null,
    secondIsSubject ? pickedLabel : '',
    secondIsSubject ? pendingAxis : null,
    credentialsMissing(secondSelected),
  )
  const quote = first.quote
  const secondQuote = second.quote
  const shownEntry = secondIsSubject ? second.entry : first.entry
  const shownAsked = secondIsSubject ? second.asked : first.asked
  const shownBuilt = secondIsSubject ? second.built : first.built
  const shownUnasked = secondIsSubject ? second.unasked : first.unasked

  /* **이 화면이 지금 보고 있는 것**을 실시간 쪽에 알립니다. 등급은 「자리가
     모자라면 무엇이 남아야 하나」입니다 — 주문 대상 종목이 가장 높고, 두 칸
     모드의 다른 칸이 그다음입니다. 홈의 관심종목은 그보다 낮게 겁니다.
     목록을 통째로 넘기는 것은 계약이 「지금 보고 있는 것 전체」를 받기 때문입니다. */
  const wishes = useMemo(() => {
    const want: Wish[] = []
    const add = (code: string, context: MarketContext, priority: number) => {
      if (!code) return
      want.push({ context, kind: 'quote', sym: code, priority })
      want.push({ context, kind: 'book', sym: code, priority })
    }
    /* 인증 정보가 없는 시장의 종목은 걸지 않습니다 — 조회와 같은 까닭입니다. */
    if (!credentialsMissing(selected)) {
      add(quote.code, contextOf(selected), secondIsSubject ? SECOND_RANK : SUBJECT_RANK)
    }
    if (splitState.split && !credentialsMissing(secondSelected)) {
      add(secondQuote.code, contextOf(secondSelected), secondIsSubject ? SUBJECT_RANK : SECOND_RANK)
    }
    /* 계좌의 주문/체결 알림은 이 화면이 걸지 않습니다 — 앱이 찬 시장마다 한 번 겁니다
       (`App.tsx` 의 `account-orders`). 같은 구독을 두 자리가 걸지 않게 합니다. */
    return want
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    quote.code,
    secondQuote.code,
    secondIsSubject,
    splitState.split,
    selected,
    secondSelected,
    /* 세션이 바뀌면 같은 종목이라도 맥락(주간/야간)이 바뀌어 다시 선언합니다. */
    contextOf(selected),
    contextOf(secondSelected),
    /* 인증 정보를 채우면 그 시장의 종목을 다시 겁니다. */
    environment.config,
  ])
  useWishes('trade', wishes)

  /* 값이 안 서는 까닭은 둘이고 **사용자가 할 일이 다릅니다.**
     못 받은 것은 다시 불러 볼 만하고(연결·시간 초과), 거절은 눌러도 같은 답이며,
     **받았는데 값이 안 찬 것은 아직 거래가 없는 것**이라 다시 부를 일이
     아닙니다. 셋을 한 얼굴로 두면 사용자가 될 때까지 단추를 누릅니다. */
  const shownFailure: {
    kind: 'retry' | 'rejected' | 'paper' | 'empty' | 'unasked'
    withValues: boolean
    text?: string
  } | null = shownUnasked
    ? /* **이 시장은 묻지 않습니다.** 값이 없는 것이 실패가 아니라, 앱이
         그 시장을 조회하지 않는 것입니다. 사용자가 할 일이 없으므로 다시
         받는 단추도 안 세웁니다. */
      { kind: 'unasked', withValues: false }
    : shownEntry.failure
      ? { kind: shownEntry.failure, withValues: shownBuilt, text: shownEntry.failureText }
      : shownAsked && shownEntry.status === 'ready' && !shownBuilt
        ? { kind: 'empty', withValues: false }
        : null

  /* 호가는 따로 실패합니다 — 현재가가 와도 호가만 못 받을 수 있습니다. 그때
     빈 사다리를 세우면 「호가가 없다」로 읽히므로 그 카드가 제 말을 합니다.
     **까닭도 그 호출의 것을 씁니다** — 호가가 거절당했으면 다시 부를 일이
     아니라 단추를 안 세웁니다. 값이 안 찬 것(`empty`)은 호가와 무관하니
     호가는 받은 대로 그립니다. **모의투자라 현재가만 못 받은 것(`paper`)도
     호가와 무관합니다** — 호가는 제 조회의 답대로 섭니다. */
  const bookFailure: {
    kind: 'retry' | 'rejected' | 'empty' | 'unasked'
    withValues: boolean
  } | null = shownUnasked
    ? { kind: 'unasked', withValues: false }
    : shownEntry.failure && shownEntry.failure !== 'paper'
      ? { kind: shownEntry.failure, withValues: shownBuilt }
      : shownAsked && shownEntry.status === 'ready' && shownEntry.book === null
        ? { kind: shownEntry.bookFailure ?? 'retry', withValues: false }
        : null

  /* 이 종목의 값을 실제로 아는지 — **받아서 세운 값이 있을 때만** 참입니다.
     「아직 안 물어봤다」(종목 색인이 오기 전의 창, 축을 안 고른 옵션)는 모르는
     것입니다. 그 자리에 서는 기초 선물의 값은 「무엇을 고르는 중인가」를 보이는
     것이지 이 종목의 값이 아니라, 그 값으로 주문을 낼 수 없습니다. */
  const priceKnown = !shownUnasked && shownAsked && shownBuilt

  /* **값을 모르는 것과 주문을 막는 것은 다릅니다.**
     못 받음·거절은 화면이 이 종목의 값을 모르는 상태라, 낼 값을 지어낼 수 없어
     막습니다. **아직 거래가 없는 것(`empty`)은 화면이 아는 상태**입니다 — 응답이
     왔고 「값이 아직 없다」가 그 답입니다. 상장되어 호가가 서 있으면 그 종목에
     첫 거래를 만드는 것이 지정가 주문이므로, 값 자리는 비워 두되 사용자가
     적어 넣으면 낼 수 있어야 합니다. 아는 것을 모른다고 다루면 멀쩡한 종목에
     주문을 못 냅니다. */
  const orderBlocked = !priceKnown && shownFailure?.kind !== 'empty'
  /* **모의인지 실전인지 모르면 주문을 낼 수 없습니다.** 어느 계좌로 나가는지를
     화면이 말하지 못하는 상태라, 값을 알아도 막습니다. 까닭은 행사가·시세보다
     앞에 섭니다 — 그것들을 고쳐도 이것이 풀리지 않으면 낼 수 없습니다. 가능수량
     조회도 같은 까닭으로 못 묻습니다(그 수는 계좌의 것입니다).
     바꾸는 중은 「모름」이 아닙니다 — 서버가 답하기 전까지 옛 환경이 참이고, 그동안
     이 화면은 잠긴 설정 창 뒤에 있어 여기서 또 문장을 세우지 않습니다. */
  const environmentKnown =
    environment.active !== null &&
    (environment.status === 'ready' || environment.status === 'switching')
  const environmentWhy = environmentKnown
    ? undefined
    : environment.status === 'failed'
      ? '모의인지 실전인지 확인하지 못해 주문을 낼 수 없습니다'
      : '모의인지 실전인지 확인하는 중입니다'
  const shownQuote = secondIsSubject ? secondQuote : quote
  /* **국내 주문은 주간인지 야간인지 알아야 나갑니다** — 주문 요청이 그 세션의 길을
     싣습니다. 그래서 야간 창이 있는 품목은 그 종목의 세션 답이 올 때까지 잠급니다.
     **야간 창이 없는 품목은 세션을 안 기다립니다** — 주간뿐이라 물을 것이 없고, 그
     품목은 세션을 묻지 않는 자리도 있어 기다리면 늘 잠깁니다. 시간표를 아직 모르면
     야간 창을 가릴 수 없어 세션 답으로 가립니다. 해외 주문은 세션과 무관합니다.
     세션은 헤더가 이 종목으로 묻습니다(`InstrumentHeader` 의 `useSession`). */
  const timetable = useTimetable()
  const sessionCode =
    subject?.market === 'domestic' && !needsLeg(shownQuote.code) && !credentialsMissing(subject)
      ? shownQuote.code
      : ''
  /* 그 시장의 인증 정보가 없어 못 내는 까닭. 주문 폼의 까닭 가운데 맨 앞입니다. */
  const credentialsWhy =
    subject !== null && credentialsMissing(subject)
      ? `${subject.market === 'overseas' ? '해외' : '국내'} 인증 정보가 없어 주문을 낼 수 없습니다`
      : undefined
  const sessionHeld = useSession('domestic', sessionCode)
  const nightWindow =
    subject !== null &&
    domesticProductDetail(
      subject.product.tradeCode,
      subject.kind === 'option' ? 'option' : 'futures',
      'night',
    ) !== null
  const sessionWhy =
    !sessionCode || sessionHeld.status === 'ready' || (timetable === 'ready' && !nightWindow)
      ? undefined
      : sessionHeld.status === 'failed'
        ? '주간인지 야간인지 확인하지 못해 주문을 낼 수 없습니다'
        : '주간인지 야간인지 확인하는 중입니다'
  /* 헤더 제목 아래 서는 다리 한 줄. **헤더가 보고 있는 종목**에서 나옵니다 —
     화면을 둘로 나눠 둘째 칸이 주문 대상이면 그 칸의 종목입니다. 스프레드가
     아니거나 다리 만기가 안 실려 오면 `null` 이고 줄을 만들지 않습니다. */
  const legsLine = useMemo(() => {
    const shown = resolve(shownQuote.code)
    return shown?.contract?.kind === 'spread' && shown.contract.legs
      ? spreadLegsLine(shown.contract.legs)
      : null
  }, [shownQuote.code])

  /* 받아 온 호가가 있으면 그것을 씁니다. **지어낸 사다리는 세우지 않습니다** —
     사용자가 그 가격을 눌러 주문가격에 넣습니다. 아직 축을 안 고른 옵션 자리도
     같습니다 — 거기는 종목이 없어 물을 호가가 없고, 카드가 틀만 남깁니다. */
  const book = useMemo(() => {
    if (shownUnasked || !shownAsked) return { asks: [], bids: [] }
    if (shownEntry.status === 'ready') return shownEntry.book ?? { asks: [], bids: [] }
    return { asks: [], bids: [] }
  }, [shownUnasked, shownAsked, shownEntry])
  /* 아직 축(행사가)을 안 고른 옵션 자리 — 종목이 없어 아무것도 안 물었습니다.
     호가·시세체결 카드가 이 값으로 틀만 남깁니다. */
  const axisPending = !shownUnasked && !shownAsked
  /* **이 카드에 서는 것은 실시간이 준 체결뿐입니다.** 지어낸 체결을 세우면,
     같은 카드가 실시간이 붙을 때는 진짜이고 안 붙을 때는 지어낸 값인데
     **화면에서 둘이 안 갈립니다.** 그러면 사용자는 지어낸 시각·가격을 최근
     체결로 읽습니다.
     안 부른 자리(해외·종목 미정)도 같습니다 — 거기는 아직 실시간을 걸지
     않아서 빈 채로 「시세가 연결되면 체결이 쌓입니다」가 섭니다. */
  const live = shownEntry.trades
  const ticks = live
  /* 매수·매도 버튼에 그 방향의 최우선 호가가 함께 섭니다. **한 단계도 없이 올 수
     있습니다** — 그 종목에 걸린 호가가 없으면 서버가 빈 배열을 냅니다. */
  const bestBid = book.bids.length > 0 ? book.bids[0].price : null
  const bestAsk = book.asks.length > 0 ? book.asks[book.asks.length - 1].price : null

  /* **자리가 모자라 실시간이 안 붙은 칸**은 값이 언제 것인지를 적습니다.
     「실시간 아님」처럼 없는 것의 이름을 붙이지 않습니다 — 사용자에게 필요한
     것은 이 값이 언제 것인가이고, 그것을 말하면 「안 바뀐다」는 저절로
     읽힙니다. 값이 아예 없는 칸에는 안 답니다 — 그때는 「없다」가 먼저입니다. */
  const stream = useStreamStatus()
  /* 이 종목이 속한 시장의 실시간. **국내와 해외는 따로 끊기고 따로 붙습니다** —
     다른 시장이 다시 붙는 동안에도 이 카드의 「언제부터」는 그대로여야 합니다. */
  const feedHere = stream.markets[activeContext === 'overseas' ? 'overseas' : 'domestic']
  const staleAt =
    priceKnown &&
    stream.rejected.includes(
      wishKey({ context: activeContext, kind: 'book', sym: shownQuote.code }),
    )
      ? shownEntry.at
      : ''
  /* 현재가 쪽은 호가와 **따로 밀립니다** — 자리는 구독 하나씩 세므로 한쪽만
     남을 수 있습니다. 그때 헤더의 값이 언제 것인지는 호가 카드가 대신 말해
     주지 못하므로, 그 줄에 제 시각을 답니다. */
  const quoteStaleAt =
    priceKnown &&
    stream.rejected.includes(
      wishKey({ context: activeContext, kind: 'quote', sym: shownQuote.code }),
    )
      ? shownEntry.at
      : ''
  /* **서버가 실시간 등록을 거절한 구독.** 시세 사용 신청을 하지 않은 거래소의
     종목이 그렇습니다. 그때 호가·시세체결 카드 머리는 시각 꼬리표 대신 「실시간
     신청 필요」를 세우고 까닭은 말풍선에 둡니다. 거래소 이름은 해외 종목에만
     적습니다. */
  const bookFailed = stream.failed[wishKey({ context: activeContext, kind: 'book', sym: shownQuote.code })]
  const ticksFailed = stream.failed[wishKey({ context: activeContext, kind: 'quote', sym: shownQuote.code })]
  const failedExchange =
    activeContext === 'overseas' ? resolve(shownQuote.code)?.product.exchange || undefined : undefined

  /* 시세체결 카드 머리의 「언제부터」. 이 이름표가 참으로 만들어야 하는 문장은
     하나입니다 — **「이 카드는 그 시각부터의 체결을 담고 있다」.**

     그래서 담은 수가 상한(`TRADE_KEEP`)에 못 미치면 **실시간이 붙은 시각**입니다.
     그때는 붙은 뒤의 체결을 하나도 안 버렸습니다. 가장 오래된 줄을 쓰면
     「15:19부터 보고 있었는데 첫 체결은 15:21이었다」는 사실이 사라져, 세 줄만
     있을 때 「15:21부터 셋」으로 읽힙니다.

     상한까지 차면 앞쪽을 버린 뒤라 붙은 시각은 더 이상 참이 아닙니다. 그때는
     담고 있는 가장 오래된 체결의 시각입니다.

     **임시 체결값이 서는 자리는 그 목록의 가장 오래된 줄을 씁니다** — 실시간을
     안 건 자리라 붙은 시각이 그 값들과 아무 상관이 없고, 머리와 바로 아래 줄이
     어긋나 보입니다.

     체결 시각은 `HH:MM:SS` 로 오는데 분까지만 씁니다 — 카드가 말하는 것은
     구간의 시작이지 특정 체결이 아닙니다. */
  /* **지금 이 종목의 체결을 실제로 듣고 있는지.** 빈 카드에 「아직 체결이
     없습니다」를 세울 수 있는 것은 듣고 있을 때뿐입니다 — 안 듣는 동안 그
     문구가 서면 「그때부터 듣는데 아무것도 안 왔다」가 되는데, 사실은 안 듣고
     있어서 모르는 것입니다. 끊겼다는 것은 상단이 이미 말하므로 카드는 잠자코
     있으면 됩니다. */
  const listening =
    shownAsked &&
    feedHere.state === 'live' &&
    !stream.rejected.includes(
      wishKey({ context: activeContext, kind: 'quote', sym: shownQuote.code }),
    )

  const oldestTick = ticks.length > 0 ? ticks[ticks.length - 1].time.slice(0, 5) : ''
  const tapeSince =
    ticks.length === 0
      ? /* 담은 것이 없을 때 「그때부터」를 적을 수 있는 것은 **듣고 있을 때뿐**
           입니다. 안 듣는 중에는 그 시각이 「그때부터 듣는데 안 온다」로 읽혀,
           카드가 하지 않기로 한 말을 머리가 대신 하게 됩니다. */
        (listening ? feedHere.since : '')
      : live.length === 0
        ? /* 임시 값이 서는 자리 — 붙은 시각과 아무 상관이 없습니다. */
          oldestTick
        : live.length >= TRADE_KEEP
          ? /* 다 차서 앞을 버린 뒤라 붙은 시각은 더 이상 참이 아닙니다. */
            oldestTick
          : /* **둘 중 이른 쪽입니다.** 끊겼다 다시 붙으면 붙은 시각만 새로
               갱신되고 받아 둔 체결은 그대로 남아, **머리보다 오래된 줄이 그
               아래 서는** 일이 생깁니다. 이른 쪽을 적으면 「이 카드는 그
               시각부터의 체결을 담고 있다」가 되붙기 뒤에도 참입니다. */
            earlierClock(oldestTick, feedHere.since, kstMinutes(Date.now()))
  /* 주문체결상세 머리의 「언제부터」. 시세체결과 같은 문장을 참으로 만듭니다 —
     **「이 표는 그 시각부터의 접수·체결을 담고 있다」.** 표는 조회로 채우고 그 위에
     실시간 알림을 이어 붙입니다. 조회가 그 앞을 다 담아 오므로, 빠짐이 없는 구간의
     시작은 **알림을 듣기 시작한 시각**입니다. 시세체결과 달리 가장 이른 줄의 시각을
     견주지 않습니다 — 그 줄보다 앞도 조회가 채웠습니다.

     끊겼다 붙으면 목록을 다시 불러 빈 구간을 메우고(`data/stream.ts`) 그 시각이
     다시 섭니다 — 과정은 머리에 안 적습니다. **듣고 있을 때만** 섭니다 — 안 듣는
     동안 서면 「그때부터 듣는데 안 온다」로 읽힙니다. 끊겼다는 것은 상단이 이미
     말합니다. */
  /* 알림 구독은 앱이 겁니다. 국내는 주간 맥락 하나로 걸려 있어, 야간에도 그 열쇠로
     물립니다. */
  const ordersSince =
    feedHere.state === 'live' &&
    !stream.rejected.includes(
      wishKey({ context: activeContext === 'overseas' ? 'overseas' : 'domestic-day', kind: 'orders', sym: '' }),
    )
      ? feedHere.since
      : ''
  /* 헤더의 만기 목록은 **주문 대상 종목의 품목과 종류**에서 나옵니다 —
     코스닥150 옵션을 보고 있으면 코스닥150 옵션의 만기가 서야 합니다. 시장에서
     뽑으면 어느 종목을 보든 같은 목록이 서고, 종류를 안 주면 한 품목의 선물과
     옵션 만기가 한 목록에 섞여 보고 있는 것이 어느 줄인지 못 가릅니다. */
  const months = useMemo(
    () => (subject ? contractsOf(subject.product, subject.kind).map(expiryOption) : []),
    [subject],
  )

  return {
    quote,
    secondQuote,
    shownEntry,
    shownBuilt,
    shownUnasked,
    shownFailure,
    bookFailure,
    priceKnown,
    orderBlocked,
    environmentKnown,
    environmentWhy,
    shownQuote,
    sessionCode,
    credentialsWhy,
    sessionHeld,
    sessionWhy,
    legsLine,
    book,
    axisPending,
    ticks,
    bestBid,
    bestAsk,
    staleAt,
    quoteStaleAt,
    bookFailed,
    ticksFailed,
    failedExchange,
    listening,
    tapeSince,
    ordersSince,
    months,
  }
}
