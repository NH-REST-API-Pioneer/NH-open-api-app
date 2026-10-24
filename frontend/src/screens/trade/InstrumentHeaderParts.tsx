import type { ReactNode } from 'react'
import { Count, Num } from '../../lib/number'

/* 후보 행을 못 받았을 때 값 칸이 잡는 폭. **가장 넓은 무리에 맞춥니다** —
 * 좁게 잡으면 값이 칸을 넘겨 옆 칸 라벨 위에 얹히는데, 넓게 잡으면 빈 자리만
 * 생깁니다. 둘 중에는 뒤가 낫습니다. */
export const WIDEST_VALUE_CHARS = 12


/* 한 행 — 라벨 왼쪽, 값 오른쪽.
 *
 * 값 자리 폭(`width`)은 그 항목이 낼 수 있는 최대 자릿수입니다. 지금 값
 * 기준으로 두면 값이 커질 때 칸이 넓어지면서 옆 칸이 전부 밀립니다. */
export function Row({ label, width, children }: { label: string; width: string; children: ReactNode }) {
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
export function Cell({ children }: { children: ReactNode }) {
  return <dl className="hd-cell">{children}</dl>
}

/* 양 끝 값 사이에서 지금 어디에 있는지를 점 하나로 보여줍니다.
 *
 * 벽까지 얼마 남았는지는 숫자 둘을 빼서 알 값이 아니라 눈으로 볼 값입니다.
 * 양 끝 숫자를 그대로 두고 그 사이에 위치만 얹는 것이라 잃는 정보가 없습니다.
 *
 * 저가와 고가가 같은 날(장 시작 직후·단일가)에도 트랙을 그리고 점을 가운데
 * 둡니다. 막대를 숨기면 「아직 범위가 없음」이 「값이 없음」으로 읽힙니다. */
export function RangeRow({
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
export function EmptyRangeRow({ label }: { label: string }) {
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
export function Turnover({ value, currency }: { value: number; currency: string }) {
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
export function resnap(scroll: HTMLElement, stops: number[]): void {
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
export function placeStops(scroll: HTMLElement, metrics: HTMLElement, leftWidth: number): number[] {
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
