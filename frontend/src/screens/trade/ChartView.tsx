import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { dispose, init, type Chart, type Crosshair } from 'klinecharts'
import type { Quote } from '../../lib/types'
import { PENDING_TEXT, needsLeg } from '../../data/instruments'
import { fractionText, toneOf } from '../../lib/number'
import type { Bar } from '../../data/quotes'
import { lineStyles, type IndicatorSetting, type IndicatorSettings } from './chartIndicators'
import { allIndicatorDefs, extendOfIndicator } from './extraIndicators'
import {
  loadDrawings,
  overlayStyles,
  rememberDrawingStyle,
  saveDrawings,
  type Drawing,
  type DrawingStyle,
} from './chartDrawings'
import { DRAW_GROUP, type TradeMark } from './chartMarks'
import { useTimetable } from '../../data/session'
import { InstrumentPicker, type InstrumentRef } from '../../lib/InstrumentPicker'
import { SPAN_LABEL, type Span } from './chartSlots'
import { ChartLegend, collectLegend, type LegendFold, type LegendRow, type OhlcRow } from './ChartLegend'
import {
  CANDLE_PANE,
  DEFAULT_TOP_GAP,
  BOTTOM_GAP,
  headroomGap,
  X_AXIS_HEIGHT,
  PANE_FLOOR,
  CANDLE_MIN,
  type BottomCap,
  capBottom,
  fitPanes,
} from './chartLayout'
import { ticksClearOfLastMark, axisDecimals, withDecimals } from './chartAxis'
import {
  ensureRectOverlay,
  markSessionBreaks,
  lastLineValue,
  type ValueMark,
  collectMarks,
} from './chartOverlays'
import { styleFromTokens } from './chartStyle'
import { SyncHub } from './SyncHub'
import { DrawingStylePopover } from './DrawingStylePopover'
import { useChartQuote } from './useChartQuote'
import { useChartData } from './useChartData'
import { useChartOverlays } from './useChartOverlays'

/* 차트 한 칸.
 *
 * 봉 그리기·십자선·지표는 라이브러리가 하고, **봉은 시세 저장소가 줍니다** —
 * 조회 봉 한 벌에 실시간 체결로 접은 봉이 뒤따르고(`data/quotes.ts`
 * `foldTrades`), 이 칸은 그것을 싣고 마지막 봉을 갈아 끼울 뿐입니다. 같은
 * 종목을 두 칸이 보면 두 칸이 같은 봉을 봅니다.
 *
 * 지표 설정은 밖(ChartPanel)에서 받습니다. 두 칸이 같은 설정을 씁니다 —
 * 칸마다 다르면 같은 이름의 선이 두 칸에서 다른 색으로 그려집니다.
 *
 * 범례와 마지막 값 배지는 이 앱이 그립니다. 라이브러리의 말풍선은 봉 위에
 * 상자를 띄워 봉을 가리고, 마지막 값 표시는 켜면 모든 지표에 붙어 가격축이
 * 이동평균 값으로 덮입니다.
 *
 * 그린 도형은 종목에 붙어 저장됩니다. 도형을 누르면 색·굵기·삭제가 뜹니다.
 *
 * 두 칸이 같은 종목이면 스크롤과 확대가 같이 움직입니다. 다른 종목이면
 * 따로 움직입니다 — 시간축이 달라 같은 거리를 밀어도 같은 자리가 아닙니다.
 */

/* ── 차트 한 칸 ──────────────────────────────────────── */

interface Props {
  /** 칸 번호. 동기화와 키에 씁니다. */
  slot: number
  quote: Quote
  span: Span
  settings: IndicatorSettings
  onSettingChange: (name: string, next: IndicatorSetting) => void
  expanded: boolean
  /** 두 칸 모드인지. 한 칸이면 주문 대상 표시를 안 합니다 — 고를 것이 없습니다. */
  split: boolean
  /** 이 칸이 주문 대상인지. */
  active: boolean
  onActivate: () => void
  /** 이 칸의 종목을 바꿉니다. **없으면 종목 배지가 누를 수 없는 글자**로 섭니다. */
  onPickInstrument?: (item: InstrumentRef) => void
  /** 고른 그리기 도구. 주문 대상인 칸에만 걸립니다. */
  tool: string | null
  onToolDone: () => void
  /** 올라갈 때마다 이 칸의 도형을 모두 지웁니다. */
  clearSignal: number
  /** 어느 칸에서든 도형이 바뀌면 올라갑니다. 같은 종목을 띄운 다른 칸이 다시 읽습니다. */
  drawVersion: number
  onDrawingsChange: () => void
  /** 차트 위에 얹는 매매 표시. 전략 화면이 묶어서 넘깁니다 — 같은 봉의 여러
   *  체결을 묶는 것도, 어느 실행의 것만 보일지도 여기 오기 전에 정해집니다. */
  tradeMarks?: TradeMark[]
  /** 표를 눌렀을 때. 상세를 띄우는 것은 부르는 쪽이 합니다. */
  onMarkPick?: (mark: TradeMark, at: { left: number; top: number }) => void
  sync: SyncHub
  /** 아래 칸의 수·높이 바닥 규칙. 전략 검증 차트가 넘깁니다 — 없으면 켜진 지표가
   *  모두 섭니다(일반주문 차트). */
  bottomCap?: BottomCap
  /** 규칙 때문에 자리를 못 받은 지표가 바뀔 때. */
  onBottomOverflow?: (names: string[]) => void
  /** 겹친 지표 범례 접기. 전략 검증 차트가 넘깁니다 — 없으면 늘 펼침입니다. */
  legendFold?: LegendFold
}

export function ChartView({
  slot,
  quote,
  span,
  settings: givenSettings,
  onSettingChange,
  expanded,
  split,
  active,
  onActivate,
  onPickInstrument,
  tool,
  onToolDone,
  clearSignal,
  drawVersion,
  onDrawingsChange,
  tradeMarks,
  onMarkPick,
  sync,
  bottomCap,
  legendFold,
  onBottomOverflow,
}: Props) {
  const boxRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<Chart | null>(null)
  /* 아래 칸 규칙이 있는 차트만 상자 높이를 따로 잽니다 — 규칙이 칸 수를 높이로 정합니다. */
  const [boxHeight, setBoxHeight] = useState(0)
  useEffect(() => {
    const box = boxRef.current
    if (!bottomCap || !box) return
    setBoxHeight(box.clientHeight)
    const observer = new ResizeObserver(() => setBoxHeight(box.clientHeight))
    observer.observe(box)
    return () => observer.disconnect()
  }, [bottomCap])
  /* 이 차트에 실제로 세우는 구성. 규칙이 없으면 받은 그대로입니다. */
  const capped = useMemo(
    () => (bottomCap ? capBottom(givenSettings, bottomCap, boxHeight) : { settings: givenSettings, overflow: [] }),
    [givenSettings, bottomCap, boxHeight],
  )
  const settings = capped.settings
  const overflowKey = capped.overflow.join(',')
  useEffect(() => {
    onBottomOverflow?.(overflowKey === '' ? [] : overflowKey.split(','))
    // 넘친 목록이 바뀔 때만 알립니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overflowKey])
  const { served, daily, missing, dailyMissing, missingWord, shortDays } = useChartQuote({ quote, span })

  /* 차트에 실린 마지막 봉. 실시간이 갈아 끼울 때마다 여기도 바뀌고, 현재가 표에
     가리는 눈금을 빼는 데 씁니다. */
  const liveRef = useRef<Bar | null>(null)
  /* 종목 자릿수. 아래 칸 축 글자가 그릴 때마다 읽습니다(MACD). */
  const decimalsRef = useRef(quote.decimals)
  decimalsRef.current = quote.decimals
  /* 지금 차트에 실린 봉 한 벌. 아래 칸이 생기거나 없어질 때 세션 구분선을 그 칸에도
     다시 세우려면 봉이 필요합니다. */
  const shownRef = useRef<readonly Bar[]>([])
  /* 앞 분봉을 못 받아 **이 차트에서는** 더 안 묻기로 한 상태. 저장소가 아니라
     여기 두는 까닭은, 저장소의 「더 없음」은 **사실**이고 이것은 못 받은 것이기
     때문입니다 — 사실 자리에 담으면 종목을 다시 열어도 영영 안 묻습니다.
     로더는 다시 그리지 않으므로 ref 로 읽고, 아래 한 줄을 세우려면 다시 그려야
     해서 상태로도 둡니다. */
  const blockedRef = useRef(false)
  const [historyBlocked, setHistoryBlocked] = useState(false)
  /* 지금 판에 **이미 실린 앞 봉의 수**. 새로 받은 것만 넘기려면 「저장소에 몇
     개가 있나」가 아니라 「이 판이 몇 개를 받았나」를 세어야 합니다 — 판을 다시
     세우는 자리가 앞 봉까지 함께 싣는데, 그 사이에 끝난 물음이 「받은 수」로
     잘라 넘기면 같은 봉이 두 벌 섭니다. */
  const loadedRef = useRef(0)
  /* 종목이 바뀌면 풉니다. 못 받은 것은 **그 종목의 사정**이라, 안 풀면 이 칸에
     다음에 서는 종목이 한 번도 안 물어보고 못 받은 것으로 섭니다.

     **일·분을 오가는 것으로는 안 풉니다.** 같은 종목이라 답도 같은데, 풀어 두면
     탭을 오갈 때마다 같은 거절을 다시 부릅니다. 아래 한 줄이 「종목을 다시
     고르면」이라고 적는 것이 그래서입니다. */
  useEffect(() => {
    blockedRef.current = false
    setHistoryBlocked(false)
  }, [quote.code])
  /* 지금 켜져 있는 지표와 그 칸. 껐다 켤 때 같은 것을 두 번 만들지 않습니다. */
  const madeRef = useRef<Map<string, string>>(new Map())
  /* 십자선이 가리키는 봉. 없으면 마지막 봉입니다. */
  const [cursor, setCursor] = useState<number | null>(null)
  /* 봉이 갱신되거나 칸이 바뀌어 범례를 다시 읽어야 할 때 올립니다. */
  const [version, setVersion] = useState(0)
  const bump = useCallback(() => setVersion((v) => v + 1), [])
  const [legend, setLegend] = useState<{ ohlc: OhlcRow | null; rows: LegendRow[]; bars: number }>({
    ohlc: null,
    rows: [],
    bars: 0,
  })
  const [marks, setMarks] = useState<ValueMark[]>([])
  const [pickerOpen, setPickerOpen] = useState(false)
  /* 크기 관찰자는 처음 한 번만 만들어져, 확대 여부는 이 참조로 읽습니다. */
  const expandedRef = useRef(expanded)
  expandedRef.current = expanded
  /* 그리는 중인 도형의 id. 도구를 풀면 지웁니다. */
  const drawingRef = useRef<string | null>(null)
  /* 이 종목의 도형. 라이브러리 id 와 저장 모양을 함께 듭니다. */
  const drawingsRef = useRef<{ id: string; drawing: Drawing }[]>([])
  /* 누른 도형. 팝오버가 이 도형을 고칩니다. */
  const [picked, setPicked] = useState<{ id: string; left: number; top: number } | null>(null)
  const pickedStyle = drawingsRef.current.find((item) => item.id === picked?.id)?.drawing.style
  /* 도형·동기화의 열쇠. 종목과 봉 종류를 함께 봅니다 — 일봉에 그은 추세선이
     분봉에 뜨면 안 되고, 일봉 칸과 분봉 칸은 같은 거리를 밀어도 같은 자리가
     아닙니다. */
  const drawKey = `${quote.code}:${span}`

  /* 저장이 진실입니다. 저장하고 나면 다른 칸에 알려, 같은 종목을 띄운 칸이
     같은 도형을 보게 합니다 — 한 칸에서 지운 선이 옆 칸에 남으면 안 됩니다. */
  const persist = useCallback(() => {
    saveDrawings(
      drawKey,
      drawingsRef.current.map((item) => item.drawing),
    )
    onDrawingsChange()
    // onDrawingsChange 는 부모의 카운터를 올리는 고정 함수입니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawKey])

  /* 저장소에서 이 종목·봉의 도형을 다시 올립니다. */
  const reloadDrawings = useCallback(
    (chart: Chart) => {
      /* 도형만 지웁니다. 인자 없이 부르면 매매 표시까지 사라집니다 —
         표는 실행이 주는 값이라 종목·봉을 바꿔도 그 실행이 살아 있는 한
         남아야 합니다. */
      chart.removeOverlay({ groupId: DRAW_GROUP })
      drawingRef.current = null
      setPicked(null)
      drawingsRef.current = []
      for (const drawing of loadDrawings(drawKey)) {
        const id = mount(chart, drawing)
        if (id) drawingsRef.current.push({ id, drawing })
      }
    },
    // mount 는 아래에서 정의되지만 고정 함수입니다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [drawKey],
  )

  /* 도형을 라이브러리에 올립니다. 누르면 팝오버가 뜹니다. */
  const mount = useCallback(
    (chart: Chart, drawing: Drawing): string | null => {
      const id = chart.createOverlay({
        name: drawing.name,
        groupId: DRAW_GROUP,
        points: drawing.points,
        styles: overlayStyles(drawing.style),
        onClick: (event) => {
          const box = boxRef.current
          const rect = box?.getBoundingClientRect()
          const left = Math.max(0, Math.min((event.pageX ?? 0) - (rect?.left ?? 0) - window.scrollX, (rect?.width ?? 300) - 240))
          const top = Math.max(0, (event.pageY ?? 0) - (rect?.top ?? 0) - window.scrollY + 12)
          setPicked({ id: event.overlay.id, left, top })
        },
      })
      return typeof id === 'string' ? id : null
    },
    [],
  )

  // 만들기와 없애기. 종목·기간이 바뀌어도 차트는 그대로 두고 값만 갈아 끼웁니다.
  useEffect(() => {
    const box = boxRef.current
    if (!box) return
    ensureRectOverlay()
    /* 가로축 시각과 십자선 시각 표는 한국시간으로 적습니다. 봉 시각이 한국 장의
       시각이라, 이 PC 의 시간대로 적으면 날짜(`dayText`)와 시각이 다른 시계가 됩니다. */
    const chart = init(box, { styles: styleFromTokens(), timezone: 'Asia/Seoul' })
    chartRef.current = chart
    if (!chart) return

    /* 마지막 봉과 오른쪽 축 사이에 두는 여백. 라이브러리 기본값은 80px 이라
       좁은 창에서는 그림의 한 뼘이 통째로 비고, 봉이 없는 자리에 날짜 눈금만
       하나 더 찍힙니다. 다음 봉이 들어올 자리만큼만 둡니다. */
    chart.setOffsetRightDistance(16)

    chart.overrideYAxis({
      paneId: CANDLE_PANE,
      createTicks: ticksClearOfLastMark(() => liveRef.current?.close ?? null),
    })

    /* 십자선을 따라 범례 값이 바뀝니다. 액션은 화면 좌표만 주므로 어느 봉인지는
       여기서 되찾습니다. 차트 밖으로 나가면 액션이 오지 않아, 나가는 것은
       따로 듣고 마지막 봉으로 돌아갑니다. */
    const onCross = (data?: unknown) => {
      const cross = (data ?? {}) as Crosshair
      if (typeof cross.x !== 'number') {
        setCursor(null)
        return
      }
      const point = chart.convertFromPixel([{ x: cross.x }], {
        paneId: cross.paneId ?? CANDLE_PANE,
      }) as Array<{ dataIndex?: number }>
      const index = point[0]?.dataIndex
      setCursor(typeof index === 'number' ? index : null)
    }
    chart.subscribeAction('onCrosshairChange', onCross)
    const onLeave = () => setCursor(null)
    box.addEventListener('mouseleave', onLeave)

    /* 칸 경계를 끌면 칸의 위치가 바뀌므로 범례도 따라갑니다. 밀고 당기는
       것은 같은 종목의 다른 칸에도 전합니다. */
    chart.subscribeAction('onPaneDrag', bump)
    chart.subscribeAction('onScroll', () => {
      bump()
      sync.follow(slot)
    })
    chart.subscribeAction('onZoom', () => {
      bump()
      sync.follow(slot)
    })

    /* 창 크기는 라이브러리가 스스로 안 봅니다. 사이드바를 열거나 창을 줄이면
       그때마다 알려줘야 그림이 늘어나거나 잘리지 않습니다. */
    /* 크기가 실제로 바뀌었을 때만 다시 잽니다. 스크롤바가 생기고 없어지는
       것처럼 알림은 오는데 치수는 같은 경우가 있고, 그때마다 칸을 다시 나누면
       그리기가 꼬리를 뭅니다. 한 프레임에 여러 알림이 오면 한 번으로 모읍니다. */
    let lastWidth = box.clientWidth
    let lastHeight = box.clientHeight
    let frame = 0
    const observer = new ResizeObserver(() => {
      if (frame) return
      frame = window.requestAnimationFrame(() => {
        frame = 0
        const width = box.clientWidth
        const height = box.clientHeight
        if (width === 0 || height === 0) return
        if (width === lastWidth && height === lastHeight) return
        const heightChanged = height !== lastHeight
        lastWidth = width
        lastHeight = height
        chart.resize()
        if (heightChanged) fitPanes(chart, box, expandedRef.current)
        bump()
      })
    })
    observer.observe(box)

    /* 창이 가려져 있는 동안 크기가 바뀌면 라이브러리가 그리기를 미루다 놓칩니다.
       다시 보일 때 한 번 더 재서 칸이 어긋난 채 남지 않게 합니다. */
    const onVisible = () => {
      if (document.visibilityState !== 'visible') return
      chart.resize()
      fitPanes(chart, box, expandedRef.current)
      bump()
    }
    document.addEventListener('visibilitychange', onVisible)

    /* 밝기를 바꾸면 색 토큰이 통째로 바뀝니다. 라이브러리는 그것을 모르므로
       바뀐 값을 다시 넣어 줍니다. */
    const theme = new MutationObserver(() => chart.setStyles(styleFromTokens()))
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })

    return () => {
      observer.disconnect()
      if (frame) window.cancelAnimationFrame(frame)
      theme.disconnect()
      box.removeEventListener('mouseleave', onLeave)
      document.removeEventListener('visibilitychange', onVisible)
      sync.unregister(slot)
      chartRef.current = null
      madeRef.current = new Map()
      drawingsRef.current = []
      dispose(box)
    }
  }, [bump, slot, sync])

  useChartData({
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
  })

  /* 다른 칸에서 도형이 바뀌었습니다. 같은 종목이면 여기도 다시 읽습니다. */
  useEffect(() => {
    if (drawVersion === 0) return
    const chart = chartRef.current
    if (chart) reloadDrawings(chart)
  }, [drawVersion, reloadDrawings])

  // 설정대로 지표를 만들고, 고치고, 없앱니다.
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return

    allIndicatorDefs().forEach((def, index) => {
      const setting = settings[def.name]
      const has = madeRef.current.has(def.name)
      /* 설정에 없는 지표는 꺼진 것입니다 — 다른 화면이 등록해 그 화면에서만 켜는
         지표(`extraIndicators`)가 그렇습니다. */
      if (!setting) {
        if (has) {
          chart.removeIndicator({ name: def.name })
          madeRef.current.delete(def.name)
        }
        return
      }
      const overlay = def.group === 'top'
      /* 계산에 종목 정보가 드는 지표는 그 정보를 함께 넘깁니다. */
      const extend = extendOfIndicator(def.name)
      const create = {
        name: def.name,
        calcParams: setting.params,
        visible: !setting.hidden,
        styles: { lines: lineStyles(setting) },
        ...(extend ? { extendData: extend(quote.code) } : {}),
      }

      if (setting.on && !has) {
        /* 봉 위에 겹치는 지표는 봉 칸에 쌓고, 축이 다른 지표는 아래에 제 칸을
           받습니다. 한 칸에 섞으면 값의 범위가 달라 한쪽이 눌립니다.
           아래 칸의 이름은 이 코드가 정합니다 — 만들기의 반환값은 칸이 아니라
           지표의 id 라, 라이브러리가 지어 준 칸은 다시 찾을 수 없습니다. */
        const paneId = overlay ? CANDLE_PANE : `pane_${def.name}`
        const made = chart.createIndicator({ ...create, paneId }, overlay)
        if (made !== null) {
          madeRef.current.set(def.name, paneId)
          if (!overlay) {
            /* 아래 칸의 순서는 목록 순서입니다. 켠 순서로 두면 거래량을 껐다
               켤 때마다 배치가 바뀝니다 — 늘 같은 자리에 있어야 눈이 찾습니다. */
            chart.setPaneOptions({ id: paneId, order: 100 + index })
            /* 아래 칸의 마지막 값 배지도 눈금 하나를 가립니다. 봉 칸의 현재가
               표와 같은 규칙으로 그 눈금을 빼고, 남은 눈금의 자릿수를 맞춥니다. */
            const clear = ticksClearOfLastMark(() => lastLineValue(chart, paneId))
            chart.overrideYAxis({
              paneId,
              createTicks: (params) =>
                withDecimals(clear(params), axisDecimals(def.name, decimalsRef.current)),
            })
          }
        }
      } else if (!setting.on && has) {
        chart.removeIndicator({ name: def.name })
        madeRef.current.delete(def.name)
      } else if (setting.on && has) {
        /* 다시 만들지 않고 값만 갈아 끼웁니다 — 다시 만들면 선이 한 번
           사라졌다 나타나고, 겹쳐 그린 칸이 잠깐 비어 보입니다. */
        chart.overrideIndicator(create)
      }
    })

    /* 칸이 늘거나 줄었으니 높이를 다시 나누고, 세션 구분선도 칸마다 다시 세웁니다. */
    const box = boxRef.current
    if (box) fitPanes(chart, box, expanded)
    markSessionBreaks(chart, quote.code, shownRef.current)
    bump()
    /* 지표 계산은 라이브러리가 뒤에 마칩니다. 한 박자 뒤에 한 번 더 읽어야
       범례가 새 기간의 값을 보입니다. */
    const later = window.setTimeout(bump, 120)
    return () => window.clearTimeout(later)
  }, [settings, expanded, bump])

  /* 시간표가 봉보다 늦게 오면 경계는 그때 압니다. 온 뒤 한 번 다시 세웁니다. */
  const timetable = useTimetable()
  useEffect(() => {
    const chart = chartRef.current
    if (!chart || timetable === 'idle' || timetable === 'loading') return
    markSessionBreaks(chart, quote.code, shownRef.current)
    // 종목이 바뀔 때는 봉을 채우는 효과가 세웁니다. 여기서는 시간표가 온 순간만.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timetable])

  /* 종목 정보를 쓰는 지표(세션 창을 보는 VWAP 등)는 종목이 바뀌거나 시간표가 온
     뒤 그 정보로 다시 셉니다. 그런 지표를 안 켠 차트에서는 하는 일이 없습니다. */
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    for (const name of madeRef.current.keys()) {
      const extend = extendOfIndicator(name)
      if (extend) chart.overrideIndicator({ name, extendData: extend(quote.code) })
    }
  }, [quote.code, timetable])

  /* 확대·복귀·분할 직후 폭을 다시 잽니다. 카드가 커졌는데 라이브러리는 모릅니다. */
  useEffect(() => {
    const chart = chartRef.current
    const box = boxRef.current
    if (!chart || !box) return
    chart.resize()
    fitPanes(chart, box, expanded)
    bump()
  }, [expanded, split, bump])

  /* 봉·칸·십자선이 바뀔 때마다 범례와 배지를 다시 읽습니다. 라이브러리가
     칸을 다 놓은 뒤에 읽어야 자리가 맞으므로 한 틱 미루고, **다음 틀에서 한 번
     더** 읽습니다 — 지표를 켜고 끄거나 칸 높이가 바뀐 직후에는 카드 높이도 함께
     바뀌어, 한 틱 뒤의 칸 자리가 아직 옛 자리일 수 있습니다. */
  useEffect(() => {
    const chart = chartRef.current
    const box = boxRef.current
    if (!chart || !box) return
    const collect = () => {
      setLegend(collectLegend(chart, box, quote, settings, cursor))
      setMarks(collectMarks(chart, box, quote, settings))
    }
    const timer = window.setTimeout(collect, 0)
    const frame = window.requestAnimationFrame(collect)
    return () => {
      window.clearTimeout(timer)
      window.cancelAnimationFrame(frame)
    }
  }, [version, cursor, quote, settings])

  /* 봉 칸 위쪽 여백. 종목 배지와 그 아래 범례(시고저종 줄 + 봉 칸에 겹친 지표 줄)가
     봉 칸 위에 얹혀 있어, 여백이 모자라면 최고가 표가 그 밑에 깔립니다. 범례가
     새 자리에 선 뒤 그 아래 끝을 재서 여백을 맞춥니다 — 줄 수가 지표에 따라
     바뀌므로 값을 못 박지 않습니다. 여백이 바뀌면 끝 값 배지 자리도 바뀌어 한
     번 더 읽습니다. 라이브러리는 축 설정을 덮어쓰지 않고 합치므로, 여백만 넘겨도
     먼저 준 눈금 규칙(`createTicks`)은 그대로 남습니다. */
  const headroomRef = useRef<{ chart: Chart | null; gap: number | null }>({ chart: null, gap: null })
  useLayoutEffect(() => {
    const chart = chartRef.current
    const box = boxRef.current
    const root = box?.parentElement
    if (!chart || !box || !root) return
    const pane = chart.getSize(CANDLE_PANE, 'main')
    const canvasTop = box.getBoundingClientRect().top
    const head = [...root.querySelectorAll<HTMLElement>('.chart-badge, .legend-candle')]
    if (!pane || head.length === 0) return
    const headBottom = Math.max(...head.map((one) => one.getBoundingClientRect().bottom)) - canvasTop - pane.top
    /* 라이브러리가 최고가 표를 다는 봉 — 보이는 봉 가운데 고가가 가장 높은 것. */
    const bars = chart.getDataList()
    const { realFrom, realTo } = chart.getVisibleRange()
    let highest = -1
    for (let index = Math.max(0, realFrom); index < Math.min(bars.length, realTo); index++) {
      if (highest < 0 || bars[index].high > bars[highest].high) highest = index
    }
    if (highest < 0) return
    const point = chart.convertToPixel({ dataIndex: highest, value: bars[highest].high }, { paneId: CANDLE_PANE })
    const highY = (Array.isArray(point) ? point[0]?.y : point.y) ?? Number.NaN
    const held = headroomRef.current
    const current = held.chart === chart && held.gap !== null ? held.gap : DEFAULT_TOP_GAP
    const textSize = chart.getStyles().candle.priceMark.high.textSize
    const gap = headroomGap(headBottom, textSize, pane.height, highY, current)
    if (held.chart === chart && (held.gap === gap || (held.gap !== null && gap !== null && Math.abs(held.gap - gap) < 0.5)))
      return
    headroomRef.current = { chart, gap }
    chart.overrideYAxis({ paneId: CANDLE_PANE, gap: { top: gap ?? DEFAULT_TOP_GAP, bottom: BOTTOM_GAP } })
    bump()
    // 범례를 접고 펴면 머리 높이가 바뀌어 여백을 다시 셉니다.
  }, [legend, bump, legendFold?.open])

  useChartOverlays({
    chartRef,
    boxRef,
    drawingRef,
    drawingsRef,
    tool,
    active,
    mount,
    persist,
    onToolDone,
    tradeMarks,
    onMarkPick,
  })

  /* 모두 지우기. */
  useEffect(() => {
    if (clearSignal === 0) return
    const chart = chartRef.current
    if (!chart) return
    /* 「모두 지우기」는 **내가 그린 도형**을 지우는 것입니다. 매매 표시는
       내가 그린 것이 아니라 실행의 기록이라 여기서 사라지면 안 됩니다. */
    chart.removeOverlay({ groupId: DRAW_GROUP })
    drawingRef.current = null
    drawingsRef.current = []
    setPicked(null)
    persist()
  }, [clearSignal, persist])

  const restyle = (style: DrawingStyle) => {
    const chart = chartRef.current
    const item = drawingsRef.current.find((entry) => entry.id === picked?.id)
    if (!chart || !item) return
    item.drawing = { ...item.drawing, style }
    chart.overrideOverlay({ id: item.id, styles: overlayStyles(style) })
    rememberDrawingStyle(style)
    persist()
    bump()
  }

  const removePicked = () => {
    const chart = chartRef.current
    if (!chart || !picked) return
    chart.removeOverlay({ id: picked.id })
    drawingsRef.current = drawingsRef.current.filter((entry) => entry.id !== picked.id)
    setPicked(null)
    persist()
  }

  /* 숨김도 설정의 일부라 남습니다. 새로고침하면 다시 보이는 것은 「내가 숨긴
     것」이 무시된 상태입니다. */
  const hide = (name: string, hidden: boolean) => onSettingChange(name, { ...settings[name], hidden })

  /* 등락이 안 왔으면 색도 없습니다 — 방향을 모르는 값에 방향색을 입힐 수 없습니다. */
  const changeTone = quote.change === null ? '' : toneOf(quote.change)
  /* 옵션인데 아직 안 고른 축이 있는가. 헤더가 보는 것과 같은 자리에서 보고,
     남은 축의 낱말도 같은 한 벌에서 가져옵니다. */
  const pendingLeg = needsLeg(quote.code)
  const pendingWord = PENDING_TEXT[quote.pendingAxis ?? 'strike'].pick
  /* 칸이 이보다 낮아지면 카드가 세로로 스크롤합니다. 봉 칸의 바닥 + 아래 칸
     바닥들 + 시간 축입니다. */
  const subCount = allIndicatorDefs().filter((def) => def.group === 'bottom' && settings[def.name]?.on).length
  const minHeight = CANDLE_MIN + subCount * (PANE_FLOOR + 1) + X_AXIS_HEIGHT
  /* 분수로 부르는 품목이면 배지도 분수로 적습니다 — 헤더·호가와 같은 말을
     써야 같은 값으로 읽힙니다. */
  const money = (value: number) =>
    quote.fraction
      ? fractionText(value, quote.fraction)
      : value.toLocaleString('ko-KR', {
          minimumFractionDigits: quote.decimals,
          maximumFractionDigits: quote.decimals,
        })

  /* 배지 안의 글자 — 누르는 배지와 글자 배지가 같은 것을 적습니다. */
  const badgeBody = (
    <>
    <b>{quote.name}</b>
    {/* 콜/풋과 행사가가 다 정해지기 전에는 종목이 아직 없습니다.

        그동안 차트가 그리는 것은 **기초 선물**이라, 값과 등락을 옵션 품목
        이름 옆에 세우면 그 이름의 시세로 읽힙니다. 그래서 대기 중에는 값을
        빼고 무엇이 남았는지만 적습니다 — 기초 선물의 현재가는 바로 위
        헤더가 이미 큼직하게 보이고 있습니다.

        낱말은 헤더·카탈로그·최근 본과 같은 한 벌에서 옵니다. */}
    {/* 값을 못 받았으면 여기서도 값을 말하지 않습니다 — 헤더가 「받지
        못했습니다」인데 차트 배지가 가격을 적으면 한 화면이 두 말을 합니다.
        대기 중과 자리는 같고 까닭만 다릅니다. */}
    {pendingLeg || missing || dailyMissing ? (
      <span className="chart-badge-pending">{pendingLeg ? pendingWord : missingWord}</span>
    ) : (
      <>
        <span className={`chart-badge-price ${changeTone}`}>
          {quote.last !== null && money(quote.last)}
        </span>
        {/* 등락이 안 온 칸은 빈 채입니다 — 0 으로 적으면 「안 움직였다」가 되고,
            「—」는 이 시장에 원래 없는 값의 말입니다. */}
        <span className={`chart-badge-change ${changeTone}`}>
          {quote.change !== null && `${quote.change > 0 ? '+' : ''}${money(quote.change)}`}
          {quote.changePct !== null &&
            ` (${quote.changePct > 0 ? '+' : ''}${quote.changePct.toFixed(2)}%)`}
        </span>
      </>
    )}
    {/* 봉 종류. 두 칸이 다른 봉을 볼 수 있어 배지가 말합니다. */}
    <span className="chart-badge-span">· {SPAN_LABEL[span]}</span>
    </>
  )

  return (
    <div
      className={`chart-box${split ? (active ? ' is-target' : ' is-idle') : ''}`}
      style={{ minHeight }}
      /* 칸을 누르면 주문 대상이 됩니다. 도형·범례 단추를 눌러도 같이 됩니다 —
         만지고 있는 차트가 곧 보고 있는 차트입니다. */
      onMouseDown={split && !active ? onActivate : undefined}
    >
      <div className="chart-canvas" ref={boxRef} />

      {/* 종목 배지. 두 칸일 때 어느 칸이 어느 종목인지는 이 배지가 말하고,
          ▾ 로 이 칸의 종목만 바꿉니다. 종목을 바꿀 수 없는 차트(전략 검증의
          차트처럼 실행이 종목을 정하는 곳)에서는 **누르는 것이 아닌 글자**로 섭니다 —
          누를 수 있게 두면 골라도 아무 일이 없는 단추가 됩니다. */}
      {onPickInstrument ? (
        <button
          type="button"
          className="chart-badge"
          style={{ top: legend.ohlc?.top ?? 0 }}
          aria-expanded={pickerOpen}
          aria-label={`${quote.name}${pendingLeg ? ` ${pendingWord}` : ''} — 이 차트의 종목 바꾸기`}
          /* 배지를 누르는 것은 종목을 「보려는」 것이지 주문 대상을 옮기는 것이
             아닙니다. 칸의 활성 전환에 섞이지 않게 합니다. */
          onMouseDown={(event) => event.stopPropagation()}
          onClick={() => setPickerOpen((open) => !open)}
        >
          {badgeBody}
          <span className="chart-badge-chev" aria-hidden="true">
            ▾
          </span>
        </button>
      ) : (
        <span className="chart-badge is-static" style={{ top: legend.ohlc?.top ?? 0 }}>
          {badgeBody}
        </span>
      )}

      {pickerOpen && (
        <InstrumentPicker
          current={quote.code}
          onPick={(item) => {
            setPickerOpen(false)
            if (item.code !== quote.code) onPickInstrument?.(item)
          }}
          onClose={() => setPickerOpen(false)}
        />
      )}

      {/* **조용히 적습니다.** 앞쪽 어느 날은 서버가 다 주지 못했을 수 있다는 말이고,
          할 일이 생기는 말이 아닙니다 — 단추도 색도 없이 한 줄입니다.

          둘이 함께 참일 때는 **못 받은 쪽만** 세웁니다. 조용한 자리가 두 줄이
          되면 조용하지 않고, 덜 받은 것보다 아예 못 받은 것이 먼저입니다. */}
      {span === 'minute' && historyBlocked ? (
        <span className="chart-quiet">
          과거 분봉을 못 받았습니다 — 종목을 다시 고르면 다시 묻습니다
        </span>
      ) : (
        span === 'minute' &&
        shortDays && <span className="chart-quiet">앞쪽 어느 날은 덜 받았을 수 있습니다</span>
      )}

      <ChartLegend
        bars={legend.bars}
        quote={quote}
        ohlc={legend.ohlc}
        rows={legend.rows}
        onHide={hide}
        onRemove={(name) => onSettingChange(name, { ...settings[name], on: false })}
        fold={legendFold}
      />

      {marks.map((mark) => (
        <span
          key={mark.name}
          className="chart-mark"
          style={{ top: mark.top, background: mark.color }}
          aria-hidden="true"
        >
          {mark.text}
        </span>
      ))}

      {picked && pickedStyle && (
        <DrawingStylePopover
          style={pickedStyle}
          left={picked.left}
          top={picked.top}
          onPick={restyle}
          onRemove={removePicked}
          onClose={() => setPicked(null)}
        />
      )}
    </div>
  )
}
