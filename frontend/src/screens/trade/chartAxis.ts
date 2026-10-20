import { utils, type AxisCreateTicksParams, type AxisTick } from 'klinecharts'
import { kstParts } from '../../lib/kst'

/* 현재가 표와 눈금 글자가 서로 닿기 시작하는 거리.
 * 표는 높이 20(글자 12 + 위아래 여백 4), 눈금 글자는 12 이고 둘 다 제 값의
 * 자리를 가운데로 삼으므로, 10 + 6 보다 가까우면 겹칩니다. */
const LAST_MARK_HEIGHT = 16

/* 현재가 표에 가리는 눈금 하나를 빼고 돌려줍니다.
 *
 * 라이브러리는 현재가 표를 눈금 위에 덮어 그립니다. 값이 눈금 자리에 가까우면
 * 눈금 글자가 반쯤 잘린 채로 남아, 읽을 수 없는 숫자가 축에 하나 생깁니다.
 * 표가 이미 그 자리의 값을 말하고 있으므로 눈금 쪽을 뺍니다. */
export function ticksClearOfLastMark(lastPrice: () => number | null) {
  return ({ defaultTicks }: { defaultTicks: AxisTick[] }): AxisTick[] => {
    const price = lastPrice()
    if (price === null || defaultTicks.length < 2) return defaultTicks

    /* 눈금은 값과 자리가 비례하므로 양 끝 둘이면 현재가의 자리가 나옵니다. */
    const first = defaultTicks[0]
    const last = defaultTicks[defaultTicks.length - 1]
    const from = Number(first.value)
    const to = Number(last.value)
    if (!Number.isFinite(from) || !Number.isFinite(to) || from === to) return defaultTicks

    const at = first.coord + ((price - from) / (to - from)) * (last.coord - first.coord)
    return defaultTicks.filter((tick) => Math.abs(tick.coord - at) >= LAST_MARK_HEIGHT)
  }
}

/* 축 눈금 글자 크기(라이브러리 기본). 글자 폭을 잴 때 씁니다. */
const AXIS_TEXT_SIZE = 12

/* 0~100 사이를 오가는 지표. 축 눈금이 20·40 처럼 서므로 소수를 안 적습니다. */
const OSCILLATORS = new Set(['RSI', 'KDJ', 'WR', 'DMI'])

/* 아래 칸 축 글자의 자릿수. `null` 이면 라이브러리 글자 그대로입니다 — 거래량은
 * 라이브러리가 큰 수를 줄여 적는 것이 읽기 좋습니다. MACD 는 가격의 차이라 종목
 * 자릿수를 따르고, 나머지는 둘입니다. 범례 값의 자릿수(`precisionFor`)와는 따로
 * 둡니다 — 눈금은 대충의 높이를 말하고, 정확한 값은 범례가 말합니다. */
export function axisDecimals(name: string, decimals: number): number | null {
  if (name === 'VOL' || name === 'OBV') return null
  if (OSCILLATORS.has(name)) return 0
  if (name === 'MACD') return decimals
  return 2
}

export function withDecimals(ticks: AxisTick[], decimals: number | null): AxisTick[] {
  if (decimals === null) return ticks
  return ticks.map((tick) => {
    const value = Number(tick.value)
    if (!Number.isFinite(value)) return tick
    /* 반올림해서 0 이 되는 음수가 「-0」으로 서지 않게 합니다. */
    const rounded = Number(value.toFixed(decimals)) || 0
    return {
      ...tick,
      text: rounded.toLocaleString('ko-KR', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      }),
    }
  })
}

/* 분봉 축은 시각만 적습니다(「23:54」). 그래서 **날이 넘어가는 자리**에서 시각이
 * 뒤로 뛰는 것처럼 보입니다 — 해외 분봉은 밤을 건너 이어지므로 앞으로 받을수록
 * 그 자리가 자주 생깁니다.
 *
 * 그 자리의 **첫 눈금에만** 날짜를 붙입니다. 모든 눈금에 붙이면 축이 날짜로 덮여
 * 시각을 읽기 어렵고, 아무 데도 안 붙이면 지금처럼 뛰어 보입니다. 날짜 꼴은
 * 일봉 축과 같은 것을 씁니다. */
function dayText(at: number): string {
  const { month, day } = kstParts(at)
  return `${month}/${day}`
}

/* 일봉 축은 날짜만 적습니다(「9/30」). 해는 **첫 눈금과 해가 바뀐 뒤 첫 눈금에만**
 * 붙입니다(「2026 1/2」) — 모든 눈금에 붙이면 축이 같은 해로 덮이고, 아무 데도 안
 * 붙이면 1월이 어느 해의 1월인지 모릅니다. 분봉의 날짜 표시는 여기 없습니다 —
 * 일봉 눈금은 이미 날짜라 한 번 더 붙이면 같은 날이 두 번 적힙니다. */
/* 글자는 눈금 자리를 가운데로 섭니다. 칸 양 끝에 붙은 눈금은 글자 한쪽이 잘려
 * 「'30」·「18:3」처럼 다른 값으로 읽히므로, 온전히 안 들어가면 글자를 비웁니다
 * (격자선은 남습니다). */
function fitsAxis(tick: AxisTick, text: string, width: number): boolean {
  const room = Math.min(tick.coord, width - tick.coord) * 2
  return room >= utils.calcTextWidth(text, AXIS_TEXT_SIZE)
}

/* 날짜와 해는 한국 달력으로 짓습니다. 봉의 날은 국내 장의 날이라, 이 PC 의
 * 시간대로 읽으면 하루씩 밀린 날짜가 적힐 수 있습니다. */
export function ticksWithYear({ defaultTicks, bounding }: AxisCreateTicksParams): AxisTick[] {
  let year: number | null = null
  return defaultTicks.map((tick) => {
    const at = Number(tick.value)
    if (!Number.isFinite(at)) return tick
    const tickYear = kstParts(at).year
    const text = dayText(at)
    if (!fitsAxis(tick, text, bounding.width)) return { ...tick, text: '' }
    if (tickYear === year) return { ...tick, text }
    const withYear = `${tickYear} ${text}`
    /* 해를 붙이면 안 들어가는 자리면 날짜만 적고 해는 다음 눈금으로 넘깁니다. */
    if (!fitsAxis(tick, withYear, bounding.width)) return { ...tick, text }
    year = tickYear
    return { ...tick, text: withYear }
  })
}

export function ticksWithDayMark({ defaultTicks, bounding }: AxisCreateTicksParams): AxisTick[] {
  /* **맨 왼쪽 눈금에는 안 붙입니다.** 거기서 날이 바뀐 것이 아니라 그림이
     시작한 것이고, 축 끝에 붙은 글자는 칸 밖으로 잘립니다. */
  const head = Number(defaultTicks[0]?.value)
  let last = Number.isFinite(head) ? dayText(head) : ''
  return defaultTicks.map((tick) => {
    const at = Number(tick.value)
    if (!Number.isFinite(at)) return tick
    const clock = fitsAxis(tick, tick.text, bounding.width) ? tick.text : ''
    const day = dayText(at)
    if (day === last) return { ...tick, text: clock }
    last = day
    /* 눈금 하나에 날짜와 시각을 **한 줄로** 답니다. 칸 끝이라 날짜까지는 안
       들어가면 시각만, 시각도 안 들어가면 비웁니다. */
    const withDay = `${day} ${tick.text}`
    return { ...tick, text: fitsAxis(tick, withDay, bounding.width) ? withDay : clock }
  })
}
