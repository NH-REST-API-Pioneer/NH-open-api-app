import { useEffect, useMemo, useRef, useState } from 'react'
import { useUiState } from '../../data/uiState'
import type { Quote } from '../../lib/types'
import {
  SETTINGS_KEY,
  normalizeSettings,
  type IndicatorSetting,
  type IndicatorSettings,
} from './chartIndicators'
import { IndicatorSettingsPopover } from './IndicatorSettings'
import { ChartView, SyncHub, type BottomCap } from './ChartView'
import type { LegendFold } from './ChartLegend'
import type { TradeMark } from './chartMarks'
import type { InstrumentRef } from '../../lib/InstrumentPicker'
import { SPAN_LABEL, type SlotState, type Span } from './chartSlots'

/* 차트 패널 — 도구 줄과 차트 칸.
 *
 * 기간은 「일 · 분」 둘뿐입니다. 주·월봉이 오지 않아 탭을 두면 빈 탭이 됩니다.
 *
 * 지표는 설정(⚙)에서 켜고 끕니다. 자주 쓰는 다섯은 도구 줄에 단추로도 있습니다.
 * 설정은 칸 둘이 함께 씁니다 — 칸마다 다르면 같은 이름의 선이 두 칸에서 다른
 * 색으로 그려집니다. 선의 색·굵기·기간은 사용자가 고르고 다음에 열어도
 * 그대로입니다.
 *
 * 「차트 확대」는 이 화면 안에서 차트가 왼쪽 열을 다 차지하는 것입니다.
 * 브라우저 전체화면이 아닙니다 — 호가와 주문 폼은 그대로 있어야 차트를 보다가
 * 바로 주문할 수 있습니다. 확대에서만 그리기 도구와 2분할이 나옵니다.
 * 확대를 켜고 끄는 단추는 이 도구 줄이 아니라 카드 머리 띠에 있습니다 —
 * 「이 카드를 열 전체로」는 보이는 값이 아니라 카드 자체에 대한 동작입니다.
 *
 * 2분할은 두 칸 중 하나가 주문 대상입니다. 축소하면 대상인 칸만 보이고,
 * 다시 확대하면 둘이 돌아옵니다.
 */

const PERIODS: Span[] = ['day', 'minute']

/* 도구 줄에 단추로 나오는 지표. 나머지는 설정에서 켭니다. */
const QUICK_INDICATORS = ['MA', 'BOLL', 'VOL', 'MACD', 'RSI']

/* 그리기 도구. 이름은 라이브러리의 오버레이 이름이고, 사각형만 이 앱이 등록합니다. */
const DRAW_TOOLS = [
  { name: 'segment', label: '추세선', icon: '╱' },
  { name: 'horizontalStraightLine', label: '수평선', icon: '─' },
  { name: 'rect', label: '사각형', icon: '▭' },
  { name: 'fibonacciLine', label: '피보나치', icon: '☰' },
]

interface Props {
  /** 두 칸의 종목. 둘째는 2분할을 켜고 골라야 생깁니다.
   *  시장은 이 종목들이 압니다 — 화면의 시장 범위는 여기까지 안 내려옵니다. */
  quotes: [Quote, Quote | null]
  /** 칸마다의 봉 종류·지표 구성. 종목은 `quotes` 가 이미 풀어 줍니다. */
  slots: [SlotState, SlotState]
  onSlotChange: (slot: 0 | 1, patch: Partial<SlotState>) => void
  expanded: boolean
  onExpandedChange: (expanded: boolean) => void
  split: boolean
  onSplitChange: (split: boolean) => void
  /** 주문 대상인 칸. */
  active: 0 | 1
  onActiveChange: (slot: 0 | 1) => void
  /** 칸의 종목을 바꿉니다. **넘기지 않으면 종목 배지를 누를 수 없습니다** — 실행이
   *  종목을 정하는 차트(전략 검증)가 그렇습니다. */
  onPickInstrument?: (slot: 0 | 1, item: InstrumentRef) => void
  /** 차트 위에 얹는 매매 표시. 전략 검증·진행이 넘깁니다 — 일반주문에서는
   *  비어 있어 차트가 지금과 똑같이 그려집니다. */
  tradeMarks?: TradeMark[]
  onMarkPick?: (mark: TradeMark, at: { left: number; top: number }) => void
  /** 공용 지표 구성 위에 **이 화면에서만** 덮는 지표들. 있으면 지표 단추로 바꾼
   *  것도 여기로만 가고 공용 구성은 저장하지 않습니다 — 전략 검증이 규칙의 지표를
   *  켜도 일반주문 차트의 지표가 그대로이게 하려는 것입니다. */
  indicatorLayer?: {
    patch: IndicatorSettings
    onChange: (name: string, next: IndicatorSetting) => void
    /** 아래 칸의 수·높이 바닥 규칙. 넘친 지표는 이 차트에 안 섭니다. */
    bottom?: BottomCap
    /** 도구줄 단추가 대신 가리킬 지표 — 이 화면에서 같은 이름의 다른 셈을 켤 때
     *  (`MACD` → 엔진 식 MACD). 층에 그 지표가 있을 때만 씁니다. */
    aliases?: Record<string, string>
    /** 겹친 지표 범례를 접을지와 그 기억. */
    legendFold?: LegendFold
  }
}

export function ChartPanel({
  quotes,
  slots,
  onSlotChange,
  expanded,
  onExpandedChange,
  split,
  onSplitChange,
  active,
  onActiveChange,
  onPickInstrument,
  tradeMarks,
  onMarkPick,
  indicatorLayer,
}: Props) {
  /* 지표 설정. 사용자가 고른 것이라 다음에 열어도 그대로입니다. */
  const [storedSettings, storeSettings] = useUiState<unknown>(SETTINGS_KEY, null)
  const [settings, setSettings] = useState<IndicatorSettings>(() => {
    /* 옛 형식의 저장값에는 이동평균 기간만 따로 있습니다. 새 설정이 없을 때만 그 값을
       가져옵니다 — 사용자가 고른 기간이 업데이트로 사라지면 안 됩니다. */
    const base = normalizeSettings(storedSettings)
    if (storedSettings === null) {
      try {
        const legacy = JSON.parse(localStorage.getItem('nh.chart.ma') ?? 'null') as unknown
        if (Array.isArray(legacy) && legacy.length > 0 && legacy.every((v) => typeof v === 'number')) {
          const ma = base.MA
          const lines = legacy.map((_, i) => ma.lines[i] ?? ma.lines[ma.lines.length - 1])
          base.MA = { ...ma, params: legacy, lines }
        }
      } catch {
        // 옛 값을 못 읽으면 기본으로 갑니다.
      }
    }
    return base
  })
  const [settingsOpen, setSettingsOpen] = useState(false)
  /* 아래 칸 규칙 때문에 차트에 못 선 지표. 도구줄 단추가 까닭을 답니다. */
  const [overflow, setOverflow] = useState<string[]>([])
  /* 고른 그리기 도구. 하나를 그리고 나면 풀립니다. */
  const [tool, setTool] = useState<string | null>(null)
  /* 올릴 때마다 대상 칸의 도형이 모두 지워집니다. */
  const [clear, setClear] = useState<[number, number]>([0, 0])
  /* 어느 칸에서든 도형이 바뀌면 올라갑니다. 두 칸이 같은 종목이면 다른 칸도
     저장소에서 다시 읽습니다. */
  const [drawVersion, setDrawVersion] = useState(0)
  /* 같은 종목인 두 칸의 스크롤·확대를 맞추는 허브. 패널이 사는 동안 하나입니다. */
  const syncRef = useRef(new SyncHub())

  const second = quotes[1]
  const showSplit = expanded && split
  const slotQuotes: [Quote, Quote] = [quotes[0], second ?? quotes[0]]
  /* 지금 보이는 칸 중 도구 줄이 다루는 칸. 두 칸이면 주문 대상, 한 칸이면
     그 한 칸입니다. 봉 종류·지표 단추는 이 칸의 것을 보여 주고 이 칸만 바꿉니다. */
  const shownSlot: 0 | 1 = showSplit ? active : split && active === 1 && second ? 1 : 0

  /* 칸의 지표 구성. 2분할에서는 칸마다 따로이고, 아직 갈라지지 않은 칸은 한 칸
     모드의 구성을 그대로 봅니다 — 처음 켤 때 둘째 칸이 첫째와 같게 시작하는
     이유입니다. 한 칸 모드는 늘 공용 구성입니다. */
  /* 덮는 층을 얹은 구성. 같은 참조를 지켜야 차트가 지표를 다시 세우지 않습니다. */
  const layerPatch = indicatorLayer?.patch
  const layered = useMemo(
    () => (layerPatch ? { ...settings, ...layerPatch } : null),
    [settings, layerPatch],
  )
  const settingsFor = (slot: 0 | 1): IndicatorSettings =>
    layered
      ? layered
      : showSplit
        ? (slots[slot].indicators ?? settings)
        : settings
  const spanFor = (slot: 0 | 1): Span => slots[slot].span

  const updateSetting = (slot: 0 | 1, name: string, next: IndicatorSetting) => {
    /* 덮는 층이 있으면 그 층만 고칩니다 — 공용 구성은 안 바뀌고 저장도 안 합니다. */
    if (indicatorLayer) {
      indicatorLayer.onChange(name, next)
      return
    }
    const all = { ...settingsFor(slot), [name]: next }
    if (showSplit) {
      onSlotChange(slot, { indicators: all })
      return
    }
    setSettings(all)
    storeSettings(all)
  }

  const activeSettings = settingsFor(shownSlot)

  /* Esc — 팝오버가 열려 있으면 팝오버가 받습니다. 그다음이 그리기 도구,
     마지막이 확대 복귀입니다. 한 번에 하나만 닫힙니다. */
  useEffect(() => {
    if (settingsOpen) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (tool) {
        setTool(null)
        return
      }
      if (expanded) onExpandedChange(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [settingsOpen, tool, expanded, onExpandedChange])

  /* 그리던 도구는 복귀하면서 풉니다. 일반 모드에는 도구 줄이 없습니다. */
  useEffect(() => {
    if (!expanded) setTool(null)
  }, [expanded])

  const toggle = (name: string) =>
    updateSetting(shownSlot, name, { ...activeSettings[name], on: !activeSettings[name].on })

  const clearDrawings = () => {
    setTool(null)
    setClear((prev) => (active === 0 ? [prev[0] + 1, prev[1]] : [prev[0], prev[1] + 1]))
  }

  const view = (slot: 0 | 1) => (
    <ChartView
      key={slot}
      slot={slot}
      quote={slotQuotes[slot]}
      span={spanFor(slot)}
      settings={settingsFor(slot)}
      onSettingChange={(name, next) => updateSetting(slot, name, next)}
      expanded={expanded}
      split={showSplit}
      active={!showSplit || active === slot}
      onActivate={() => onActiveChange(slot)}
      onPickInstrument={onPickInstrument ? (item) => onPickInstrument(slot, item) : undefined}
      tool={tool}
      onToolDone={() => setTool(null)}
      clearSignal={clear[slot]}
      drawVersion={drawVersion}
      onDrawingsChange={() => setDrawVersion((v) => v + 1)}
      tradeMarks={tradeMarks}
      onMarkPick={onMarkPick}
      sync={syncRef.current}
      bottomCap={indicatorLayer?.bottom}
      legendFold={indicatorLayer?.legendFold}
      onBottomOverflow={slot === shownSlot ? setOverflow : undefined}
    />
  )

  return (
    <div className={`chart-panel${expanded ? ' is-expanded' : ''}`}>
      <div className="chart-controls">
        {/* 봉 종류는 칸마다 따로입니다. 이 토글은 도구 줄이 다루는 칸(주문 대상)의
            것을 보여 주고 그 칸만 바꿉니다. */}
        <div className="seg" role="group" aria-label="기간">
          {PERIODS.map((span) => (
            <button
              key={span}
              type="button"
              className="seg-item"
              aria-pressed={spanFor(shownSlot) === span}
              onClick={() => onSlotChange(shownSlot, { span })}
            >
              {SPAN_LABEL[span]}
            </button>
          ))}
        </div>

        {/* 지표는 켜고 끄는 것이라 알약이 아니라 각자 눌리는 단추입니다 —
            세그먼트는 「여럿 중 하나」이고 이것은 「여럿 중 여럿」입니다. */}
        <div className="chart-indicators" role="group" aria-label="지표">
          {QUICK_INDICATORS.map((name) => {
            /* 이 화면이 같은 이름의 다른 셈을 켰으면(검증 차트의 엔진 식 MACD) 단추는
               그 지표를 가리킵니다 — 켜져 있는데 단추가 꺼진 꼴이면 둘이 다른 말을 합니다. */
            const alias = indicatorLayer?.aliases?.[name]
            const target = alias && activeSettings[alias] ? alias : name
            return (
              <button
                key={name}
                type="button"
                className="btn btn-quiet chart-indicator"
                aria-pressed={activeSettings[target].on}
                title={overflow.includes(target) ? '아래 칸은 셋까지 — 조건 표에서 값을 봅니다' : undefined}
                onClick={() => toggle(target)}
              >
                {name}
              </button>
            )
          })}

          <div className="chart-settings">
            <button
              type="button"
              className="btn btn-quiet chart-indicator"
              aria-label="지표 설정"
              aria-expanded={settingsOpen}
              data-tip="지표 설정"
              onClick={() => setSettingsOpen((open) => !open)}
            >
              ⚙
            </button>
            {settingsOpen && (
              <IndicatorSettingsPopover
                settings={activeSettings}
                onChange={(name, next) => updateSetting(shownSlot, name, next)}
                onClose={() => setSettingsOpen(false)}
              />
            )}
          </div>

          {/* 2분할은 확대에서만. 일반 모드의 차트 카드는 둘을 놓을 폭이 없습니다. */}
          {expanded && (
            <button
              type="button"
              className="btn btn-quiet chart-indicator chart-split"
              aria-pressed={split}
              aria-label={split ? '한 칸으로' : '2분할'}
              data-tip={split ? '한 칸으로' : '2분할'}
              onClick={() => onSplitChange(!split)}
            >
              <span className="chart-split-icon" aria-hidden="true">
                <i />
                <i />
              </span>
              2분할
            </button>
          )}
        </div>
      </div>

      <div className="chart-stage">
        {/* 그리기 도구는 확대에서만 나옵니다. 일반 모드의 차트는 선을 그릴 만큼
            넓지 않고, 도구 줄이 그 자리를 더 먹습니다. 두 칸일 때는 주문 대상인
            칸에 그려집니다. */}
        {expanded && (
          <div className="draw-tools" role="toolbar" aria-label="그리기">
            {DRAW_TOOLS.map((item) => (
              <button
                key={item.name}
                type="button"
                className="draw-tool"
                aria-label={item.label}
                aria-pressed={tool === item.name}
                data-tip={item.label}
                onClick={() => setTool((current) => (current === item.name ? null : item.name))}
              >
                {item.icon}
              </button>
            ))}
            <span className="draw-tools-gap" />
            <button
              type="button"
              className="draw-tool"
              aria-label="그린 것 모두 지우기"
              data-tip="모두 지우기"
              onClick={clearDrawings}
            >
              🗑
            </button>
          </div>
        )}

        <div className={`chart-panes${showSplit ? ' is-split' : ''}`}>
          {/* 축소하면 주문 대상인 칸만 남습니다. 다른 칸은 내려가지만 종목은
              기억되어 다시 확대하면 그대로 돌아옵니다. */}
          {showSplit ? (
            <>
              {view(0)}
              {view(1)}
            </>
          ) : (
            view(split && active === 1 && second ? 1 : 0)
          )}
        </div>
      </div>
    </div>
  )
}
