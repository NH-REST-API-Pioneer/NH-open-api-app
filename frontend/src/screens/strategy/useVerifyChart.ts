import { useMemo, useState } from 'react'
import { resolve } from '../../data/instruments'
import { useQuote } from '../../data/instrumentQuote'
import { domesticContextOf } from '../../data/session'
import { useWishes, type Wish } from '../../data/stream'
import type { MarketContext } from '../../lib/types'
import { runCurrencyOf, type VerifyRun } from '../../data/strategyRuns'
import { currencyOf, useStrategyCurrency } from '../../data/strategyList'
import { savedOf, useStrategyState } from '../../data/strategyStore'
import { runNameOf } from './runStats'
import { ruleBottomOrder, ruleIndicators } from './ruleIndicators'
import { ENGINE_MACD } from './engineIndicators'
import type { IndicatorSetting, IndicatorSettings } from '../trade/chartIndicators'
import type { SlotState } from '../trade/chartSlots'
import type { Dispatch, SetStateAction } from 'react'
import type { useVerifyRun } from './useVerifyRun'
import { VERIFY_RANK } from './strategyVerifyUtils'

type RunValues = ReturnType<typeof useVerifyRun>
type StoreState = ReturnType<typeof useStrategyState>

/** 고른 실행의 차트 — 덮는 지표 한 벌, 시세, 봉, 통화와 전략 이름. */
export function useVerifyChart({
  picked,
  layers,
  setLayers,
  store,
  slot,
}: {
  picked: RunValues['picked']
  layers: Record<string, IndicatorSettings>
  setLayers: Dispatch<SetStateAction<Record<string, IndicatorSettings>>>
  store: StoreState
  slot: SlotState
}) {
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
    [pickedLayer, rulePatch, picked, paneCap, pickedOpen, setLayers],
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
     값을 따로 세우면 표가 봉이 없는 허공에 뜹니다 — 체결은 그 시각의 실제 봉에
     앉습니다. */
  const bars = useMemo(
    () => (slot.span === 'minute' ? [...(entry.bars ?? []), ...entry.live] : (entry.daily ?? [])),
    [entry.bars, entry.live, entry.daily, slot.span],
  )

  return {
    indicatorLayer,
    decimals,
    pickedRow,
    currency,
    runCurrency,
    nameOf,
    quote,
    bars,
  }
}
