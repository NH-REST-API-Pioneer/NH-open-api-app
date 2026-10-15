/* 차트 칸의 상태.
 *
 * 2분할은 칸이 둘이고, 칸마다 종목·봉 종류·지표 구성을 따로 가집니다. 근월은
 * 일봉으로 보고 차월은 분봉으로 보는 식입니다. 첫째 칸의 종목은 이 화면의
 * 종목이라 여기 없고(null), 둘째 칸만 제 종목을 듭니다.
 *
 * 지표 구성이 없는 칸(null)은 한 칸 모드의 구성(nh.trade.indicators)을
 * 그대로 씁니다. 2분할에서 처음 만지는 순간 그 칸의 것으로 갈라집니다.
 */

import type { InstrumentRef } from '../../lib/InstrumentPicker'
import { normalizeSettings, type IndicatorSettings } from './chartIndicators'

export type Span = 'day' | 'minute'

export interface SlotState {
  instrument: InstrumentRef | null
  span: Span
  indicators: IndicatorSettings | null
}

export interface SplitState {
  split: boolean
  active: 0 | 1
  slots: [SlotState, SlotState]
}

export const SPLIT_KEY = 'nh.trade.split'

export const SPAN_LABEL: Record<Span, string> = { day: '일', minute: '분' }

function emptySlot(): SlotState {
  return { instrument: null, span: 'day', indicators: null }
}

export function defaultSplit(): SplitState {
  return { split: false, active: 0, slots: [emptySlot(), emptySlot()] }
}

/* 저장된 종목을 되살립니다. 품목 이름이 빠진 옛 값은 전체 이름에서 월물
 * 꼬리(「26년 9월물」)를 떼어 채웁니다 — 버리면 둘째 칸이 첫째 칸 종목으로
 * 돌아가, 사용자가 고른 것이 사라진 것으로 보입니다. */
function readInstrument(value: unknown): InstrumentRef | null {
  const item = value as Partial<InstrumentRef> | null
  if (
    !item ||
    typeof item.code !== 'string' ||
    typeof item.name !== 'string' ||
    typeof item.market !== 'string' ||
    typeof item.decimals !== 'number' ||
    typeof item.currency !== 'string'
  ) {
    return null
  }
  const productName =
    typeof item.productName === 'string'
      ? item.productName
      : item.name.replace(/\s*\d{2}년\s*\d{1,2}월물$/, '')
  return {
    code: item.code,
    name: item.name,
    productName,
    market: item.market,
    /* **값이 없는 종목도 되살립니다.** 현재가는 그 칸이 무엇을 보고 있는지가
       아니라 배지에 적을 숫자일 뿐이라, 없다고 칸을 통째로 비우면 만기 목록에
       행이 없는 종목(옵션 만기 코드)을 둘째 칸에 두고 저장했다가 다시 읽는
       순간 그 칸이 사라집니다. 숫자가 아닌 값은 없는 것으로 봅니다. */
    lastPrice: typeof item.lastPrice === 'number' ? item.lastPrice : null,
    decimals: item.decimals,
    currency: item.currency,
  }
}

function readSlot(raw: unknown): SlotState {
  const item = raw as Partial<SlotState> | null
  if (!item || typeof item !== 'object') return emptySlot()
  return {
    instrument: readInstrument(item.instrument),
    span: item.span === 'minute' ? 'minute' : 'day',
    indicators: item.indicators ? normalizeSettings(item.indicators) : null,
  }
}

/* 저장된 값은 예전 모양일 수 있습니다. 처음 모양은 둘째 칸 종목 하나만
 * (`second`) 들었으므로 그것을 둘째 칸으로 옮깁니다. */
export function normalizeSplit(raw: unknown): SplitState {
  const base = defaultSplit()
  if (!raw || typeof raw !== 'object') return base
  const input = raw as Partial<SplitState> & { second?: unknown }
  base.split = input.split === true
  base.active = input.active === 1 ? 1 : 0
  if (Array.isArray(input.slots)) {
    base.slots = [readSlot(input.slots[0]), readSlot(input.slots[1])]
  } else {
    base.slots[1].instrument = readInstrument(input.second)
  }
  return base
}
