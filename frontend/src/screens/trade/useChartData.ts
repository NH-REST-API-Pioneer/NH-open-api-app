import { useEffect, type Dispatch, type RefObject, type SetStateAction } from 'react'
import type { Chart } from 'klinecharts'
import type { Quote } from '../../lib/types'
import { loadHistory, quoteEntry, subscribeQuotes, type Bar } from '../../data/quotes'
import type { Span } from './chartSlots'
import { fitPanes } from './chartLayout'
import { ticksWithYear, ticksWithDayMark } from './chartAxis'
import { markSessionBreaks } from './chartOverlays'
import type { SyncHub } from './SyncHub'
import type { useChartQuote } from './useChartQuote'

type QuoteValues = ReturnType<typeof useChartQuote>

/** 봉 싣기 — 종목·기간이 바뀌면 봉을 다시 넣고 실시간으로 잇습니다. */
export function useChartData({
  chartRef,
  boxRef,
  liveRef,
  shownRef,
  blockedRef,
  loadedRef,
  setHistoryBlocked,
  quote,
  span,
  served,
  daily,
  missing,
  dailyMissing,
  bump,
  slot,
  sync,
  reloadDrawings,
  drawKey,
  expanded,
}: {
  chartRef: RefObject<Chart | null>
  boxRef: RefObject<HTMLDivElement | null>
  liveRef: RefObject<Bar | null>
  shownRef: RefObject<readonly Bar[]>
  blockedRef: RefObject<boolean>
  loadedRef: RefObject<number>
  setHistoryBlocked: Dispatch<SetStateAction<boolean>>
  quote: Quote
  span: Span
  served: QuoteValues['served']
  daily: QuoteValues['daily']
  missing: boolean
  dailyMissing: boolean
  bump: () => void
  slot: number
  sync: SyncHub
  reloadDrawings: (chart: Chart) => void
  drawKey: string
  expanded: boolean
}) {
  // 종목·기간이 바뀌면 봉을 다시 넣고, 그 종목의 도형을 올립니다.
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return

    chart.setSymbol({ ticker: quote.code, pricePrecision: quote.decimals, volumePrecision: 0 })
    chart.setPeriod({ type: span, span: 1 })
    /* 눈금 글자는 봉 종류를 따릅니다. 칸이 선 뒤에 분·일을 오가도 바뀌도록
       봉 종류가 바뀔 때마다 다시 겁니다. */
    chart.overrideXAxis({ createTicks: span === 'minute' ? ticksWithDayMark : ticksWithYear })

    /* 봉을 안 그리기로 한 자리에서는 **눈금도 값을 말하면 안 됩니다.** 봉이
       없으면 라이브러리가 제 기본 범위(0~10)로 눈금을 세우는데, 1,383 짜리
       종목 옆에서 그 눈금은 「이 종목은 0에서 10 사이」라고 말합니다. 값을
       안 말하기로 한 판단의 나머지 절반입니다. */
    chart.setStyles({ yAxis: { tickText: { show: !(missing || dailyMissing) } } })
    liveRef.current = null
    sync.register(slot, drawKey, chart)

    /* 봉을 처음 채우는 것과 실시간으로 잇는 것이 한 자리에 있습니다. `getBars` 는
       저장소의 조회 봉과 그 위에 접힌 봉을 싣고, `subscribeBar` 는 저장소를 구독해
       접힌 마지막 봉을 갈아 끼웁니다. */
    let unsubscribe: (() => void) | undefined

    chart.setDataLoader({
      getBars: ({ type, callback }) => {
        /* 라이브러리는 **왼쪽 끝에 닿으면 `forward`**(더 과거), 오른쪽 끝에 닿으면
           `backward`(더 최근)를 부릅니다. 최근 쪽은 구독으로 흐르므로 여기서는
           빈 응답을 줍니다 — 같은 봉을 또 주면 끝없이 불어납니다. */
        if (type === 'forward') {
          /* 분봉만 이어 받습니다. 못 이어 받는 자리에서는 「없다」로 답해야
             라이브러리가 왼쪽 끝에서 다시 묻지 않습니다. */
          if (span !== 'minute' || missing || blockedRef.current) {
            callback([], { forward: false })
            return
          }
          void loadHistory(quote.code).then(({ failed }) => {
            const held = quoteEntry(quote.code)
            /* 못 받았으면 **이 차트에서는** 닫습니다. 같은 자리에서 또 물어도
               같은 답이 오는데, 왼쪽 끝은 손이 닿을 때마다 부르는 자리입니다. */
            if (failed) {
              blockedRef.current = true
              setHistoryBlocked(true)
              callback([], { forward: false })
              return
            }
            /* **이 판에 아직 안 실린 것만** 넘깁니다 — 라이브러리가 제 목록 앞에
               이어 붙이므로, 이미 실린 것을 또 주면 같은 시각의 봉이 두 벌 섭니다. */
            const all = held.history.bars
            const fresh = all.slice(0, Math.max(0, all.length - loadedRef.current))
            loadedRef.current = all.length
            callback(fresh, { forward: !held.history.done })
            if (fresh.length === 0) return
            shownRef.current = [...held.history.bars, ...(held.bars ?? []), ...held.live]
            markSessionBreaks(chart, quote.code, shownRef.current)
            bump()
          })
          return
        }
        if (type !== 'init') {
          callback([], { backward: false })
          return
        }
        /* 두 시장 다 서버 봉만 씁니다. 분봉은 조회 봉(주간·야간 한 벌) 뒤에 체결로
           접은 봉을 잇고, 일봉은 조회 봉뿐입니다. 아직 안 왔으면 **비워 둡니다** —
           지어낸 봉을 세우면 헤더는 「받는 중」인데 차트만 값을 말합니다. */
        const held = quoteEntry(quote.code)
        const bars = missing
          ? []
          : span === 'minute'
            ? [...held.history.bars, ...(served ?? []), ...held.live]
            : [...(daily.bars ?? []), ...held.dailyLive]
        liveRef.current = bars[bars.length - 1] ?? null
        shownRef.current = bars
        /* 판을 세울 때 **앞 봉도 함께 싣습니다** — 그러니 이 판이 받은 수도 여기서
           맞춰 둡니다. 안 맞추면 다음 한 번이 같은 봉을 또 싣습니다. */
        loadedRef.current = missing || span !== 'minute' ? 0 : held.history.bars.length
        /* **복사해서 넘깁니다.** 라이브러리는 받은 배열을 제 목록으로 그대로 쓰고
           실시간 봉을 거기에 덧붙입니다 — 저장소의 배열을 그대로 주면 저장소가
           든 봉이 차트 손에 늘어나, 같은 종목을 보는 다른 칸까지 그 봉을 읽습니다. */
        /* 왼쪽 끝에서 더 받을 수 있다고 알려 둡니다 — 이 표시가 없으면 라이브러리가
           왼쪽 끝에 닿아도 묻지 않습니다. */
        callback([...bars], {
          forward:
            span === 'minute' &&
            !missing &&
            bars.length > 0 &&
            !held.history.done &&
            !blockedRef.current,
          backward: false,
        })
        markSessionBreaks(chart, quote.code, bars)
        bump()
        /* 같은 종목을 이미 띄운 칸이 있으면 그 칸의 구간으로 맞춥니다 — 한 칸으로
           접었다 다시 두 칸으로 펼 때 두 차트가 다른 자리에서 시작하면 안 됩니다. */
        window.setTimeout(() => sync.adopt(slot), 0)
      },

      subscribeBar: ({ callback }) => {
        if (missing) return
        /* **일봉도 잇습니다.** 오늘 봉이 조회한 순간에 멈춰 있으면 분봉은 흐르는데
           일봉만 낡은 종가를 말합니다. 접는 규칙은 저장소가 정합니다 — 주간 체결만
           접고, 날이 바뀌면 새 봉입니다. */
        const folded = () => {
          const entry = quoteEntry(quote.code)
          return span === 'minute' ? entry.live : entry.dailyLive
        }
        /* 저장소가 접은 봉 중 아직 안 실은 것을 순서대로 넘깁니다. 같은 열쇠면
           라이브러리가 마지막 봉을 갈아 끼우고, 새 열쇠면 덧붙입니다. 새 봉이 서면
           세션 창을 넘었을 수 있어 경계선도 다시 봅니다 — 체결마다는 아닙니다. */
        let pushedKey = liveRef.current?.timestamp ?? 0
        let pushed: Bar | null = liveRef.current
        const push = (): boolean => {
          const entry = quoteEntry(quote.code)
          let changed = false
          for (const bar of folded()) {
            if (bar.timestamp < pushedKey || bar === pushed) continue
            const started = bar.timestamp > pushedKey
            pushedKey = bar.timestamp
            pushed = bar
            liveRef.current = bar
            callback(bar)
            changed = true
            if (started && span === 'minute') {
              shownRef.current = [...entry.history.bars, ...(entry.bars ?? []), ...entry.live]
              markSessionBreaks(chart, quote.code, shownRef.current)
            }
          }
          return changed
        }
        push()
        /* 저장소는 어느 종목이 바뀌어도 알리므로, 이 종목의 봉이 실제로 바뀐 때만
           범례를 다시 읽습니다. */
        unsubscribe = subscribeQuotes(() => {
          if (push()) bump()
        })
      },

      unsubscribeBar: () => {
        unsubscribe?.()
        unsubscribe = undefined
      },
    })

    /* 도형은 종목에 붙습니다. 이전 종목의 도형을 내리고 이 종목의 것을 올립니다. */
    reloadDrawings(chart)

    const box = boxRef.current
    if (box) fitPanes(chart, box, expanded)

    return () => unsubscribe?.()
    // 확대는 아래 효과가 따로 맞춥니다. 여기서 봉을 다시 넣으면 안 됩니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    /* **시세를 통째로 두지 않습니다.** 이 효과가 종목에서 쓰는 것은 신원과
       자릿수뿐입니다. 통째로 두면 값이 바뀔 때마다 봉·도형·구간이 다시 실립니다.
       조회 봉 참조(`served`·`daily.bars`)는 조회 때만 바뀝니다. */
    quote.code,
    quote.decimals,
    span,
    served,
    daily.bars,
    missing,
    dailyMissing,
    bump,
    slot,
    sync,
    reloadDrawings,
    drawKey,
  ])
}
