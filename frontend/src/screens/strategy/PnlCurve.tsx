import { useEffect, useId, useRef, useState } from 'react'

import { amountText } from '../../data/strategyRecords'
import { MINUS } from '../../lib/number'

/* 누적 순손익 곡선.
 *
 * **색은 합계의 방향(0 위/아래)이고, 두 선의 정체는 굵기·흐림·선 끝 이름표입니다.**
 * 합계 선은 0 보다 위에 있는 구간을 상승색, 아래 구간을 하락색으로 칠하고, 선과
 * 0 선 사이를 같은 색으로 옅게 깝니다. 고른 전략 하나는 가늘고 흐린 무채 실선입니다 —
 * 이 앱에서 색에는 임자가 있어(빨강 매수·상승, 파랑 매도·하락, 초록 선택), 남는
 * 색으로 계열을 만들면 색각 이상에서 서로 무너집니다. 그래서 곡선은 **합계와 고른
 * 전략 하나**만 그립니다.
 *
 * 여럿을 비교할 때는 곡선을 겹치지 않고 바로 아래 비교표가 답합니다.
 */

interface Props {
  dates: string[]
  total: number[]
  totalLabel: string
  /** 고른 전략 하나. 없으면 합계만 그립니다. */
  pick: number[] | null
  pickLabel: string
  /** 금액의 통화(`KRW`·`USD`). 이름표와 세로축 글자가 이 통화로 섭니다. */
  currency: string
}

/** 선 끝 이름표가 앉을 자리. 오른쪽 여백은 가장 긴 이름표(전략 이름 + 금액)가
 *  들어갈 만큼 미리 비웁니다 — 좁으면 이름이 잘리는 것이 아니라 금액이
 *  잘리는데, 잘린 금액은 다른 수로 읽힙니다. */
const PAD = { top: 14, right: 176, bottom: 22, left: 62 }

/** 날짜 글자 하나가 차지하는 가로 폭(여백 포함). 이보다 촘촘하면 글자끼리
 *  겹쳐 어느 것도 못 읽습니다. */
const DATE_SLOT = 84

/** 왼쪽 최고·최저 글자가 「0」과 이보다 가까우면 뺍니다 — 0 선 곁에 다른 수가
 *  서면 0 선을 그 값으로 읽습니다. */
const ZERO_GAP = 16

/** 선 끝 이름표 두 개(두 줄짜리)가 이보다 가까우면 겹칩니다. */
const TIP_GAP = 32

/** 세로축 끝 값. 원은 만 단위로 줄이고, 그 밖의 통화는 정수로 적습니다 —
 *  「만」은 원에만 쓰는 줄임입니다. 빼기 기호는 앱이 쓰는 것(−)과 같습니다. */
function axisText(value: number, currency: string): string {
  const sign = value < 0 ? MINUS : ''
  if (currency === 'KRW' || currency === '') {
    return `${sign}${Math.round(Math.abs(value) / 10000).toLocaleString('ko-KR')}만`
  }
  return `${sign}${Math.round(Math.abs(value)).toLocaleString('en-US')}`
}

/** 적을 날짜들. **글자 자리가 고른 간격**입니다 — 폭이 허락하는 개수(m)를 정해
 *  가로를 m−1 등분한 자리에 글자를 두고, 그 자리에 가장 가까운 날을 적습니다.
 *  날의 자리에 그대로 두면 거래일 수가 등분과 맞지 않을 때 간격이 하루 폭만큼
 *  들쭉날쭉합니다. 첫날과 끝날은 늘 들어갑니다. `ratio` 는 가로 비율(0~1)입니다. */
function dateMarks(count: number, plotW: number): { i: number; ratio: number }[] {
  if (count === 0) return []
  if (count === 1) return [{ i: 0, ratio: 0 }]
  const m = Math.min(count, Math.max(2, Math.floor(plotW / DATE_SLOT) + 1))
  return Array.from({ length: m }, (_, k) => ({
    i: Math.round((k * (count - 1)) / (m - 1)),
    ratio: k / (m - 1),
  }))
}

/** 날짜 글자에서 해·달·날을 읽습니다(`YYYY-MM-DD`·`YYYYMMDD`). 못 읽으면 `null`
 *  이고, 그때는 받은 글자를 그대로 적습니다. */
function dateParts(text: string): { year: number; month: number; day: number } | null {
  const found = /^(\d{4})-?(\d{2})-?(\d{2})/.exec(text)
  if (!found) return null
  return { year: Number(found[1]), month: Number(found[2]), day: Number(found[3]) }
}

/** 날짜 글자들. 「M/D」이고, **첫 글자와 해가 바뀐 뒤 첫 글자만** 해를 붙입니다 —
 *  해를 늘 붙이면 글자가 길어 적을 수 있는 개수가 줄고, 안 붙이면 기간이 해를
 *  넘을 때 어느 해의 1/5 인지 모릅니다. */
function dateLabels(dates: string[], marks: { i: number }[]): string[] {
  let lastYear: number | null = null
  return marks.map(({ i }) => {
    const parts = dateParts(dates[i] ?? '')
    if (!parts) return dates[i] ?? ''
    const short = `${parts.month}/${parts.day}`
    const withYear = lastYear === null || parts.year !== lastYear
    lastYear = parts.year
    return withYear ? `${parts.year} ${short}` : short
  })
}

export function PnlCurve({ dates, total, totalLabel, pick, pickLabel, currency }: Props) {
  const boxRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState<[number, number]>([0, 0])
  /* 한 화면에 곡선이 다시 설 수 있어 잘라 내기·그라데이션 이름이 겹치면 안 됩니다. */
  const id = useId()

  /* 상자가 정해 준 크기에 맞춰 그립니다. `viewBox` 를 늘려 맞추면 글자까지
     같이 늘어나 이름표와 날짜가 찌그러집니다. */
  useEffect(() => {
    const box = boxRef.current
    if (!box) return
    const watch = new ResizeObserver(([entry]) => {
      const rect = entry.contentRect
      setSize([Math.round(rect.width), Math.round(rect.height)])
    })
    watch.observe(box)
    return () => watch.disconnect()
  }, [])

  const [width, height] = size
  /* 거래일이 하루뿐이어도 그립니다 — 선은 못 되지만 점 하나가 그날의 값입니다.
     안 그리면 거래가 있는데 곡선 자리가 비어 고장으로 읽힙니다. */
  const ready = width > 0 && height > 0 && total.length > 0
  const single = total.length === 1

  /* **가로 자리는 합계의 길이를 믿습니다.** 날짜·고른 전략의 길이가 합계와 다르게
     오면 날짜는 있는 차례만 글자로 적고, 전략 선은 합계 길이 안쪽만 그립니다 —
     합계가 이 그림의 몸통이라, 다른 쪽에 맞추면 합계가 잘리거나 늘어납니다. */
  const picked = pick ? pick.slice(0, total.length) : null

  /* 두 선과 0 을 함께 넣습니다. 0 이 화면에 없으면 이익 구간인지 손실
     구간인지를 눈이 판단할 기준선이 사라집니다. */
  const values = [...total, ...(picked ?? []), 0]
  const high = Math.max(...values)
  const low = Math.min(...values)
  const span = high - low || 1

  const plotW = Math.max(1, width - PAD.left - PAD.right)
  const plotH = Math.max(1, height - PAD.top - PAD.bottom)
  const xAt = (i: number) => PAD.left + (i / Math.max(1, total.length - 1)) * plotW
  /* 값 범위가 0 이면(전부 0) 세로 가운데에 섭니다 — 바닥에 붙이면 위가 통째로 비고
     「가장 낮다」로 읽힙니다. 0 선·끝 이름표도 이 높이를 따릅니다. */
  const yAt = (value: number) =>
    high === low ? PAD.top + plotH / 2 : PAD.top + (1 - (value - low) / span) * plotH
  const path = (points: number[]) =>
    points.map((v, i) => `${i === 0 ? 'M' : 'L'}${xAt(i).toFixed(1)},${yAt(v).toFixed(1)}`).join(' ')

  const zeroY = yAt(0)
  const topY = PAD.top
  const bottomY = PAD.top + plotH
  /* 합계가 전부 0 이면 방향이 없습니다 — 무채 한 줄이고 칠하지 않습니다. */
  const flat = total.every((value) => value === 0)
  /* 선과 0 선 사이 면. 합계 선을 따라가다 0 선 높이로 내려와 닫습니다. */
  const area = !single && !flat
    ? `${path(total)} L${xAt(total.length - 1).toFixed(1)},${zeroY.toFixed(1)} L${xAt(0).toFixed(1)},${zeroY.toFixed(1)} Z`
    : null
  const up = `url(#${id}-up)`
  const down = `url(#${id}-down)`

  const lastTotal = total[total.length - 1] ?? 0
  const lastPick = picked ? (picked[picked.length - 1] ?? 0) : 0
  const toneOf = (value: number) => (value > 0 ? 'is-up' : value < 0 ? 'is-down' : '')

  /* 왼쪽 글자: 「0」은 늘, 최고·최저는 0 과 닿지 않을 때만. 0 이 이깁니다 — 0 에서
     떠난 거리를 읽는 그림이라, 0 선 곁에 다른 수가 서면 0 선을 그 값으로 읽습니다.
     계좌 추이의 같은 규칙(`Edges`)은 HTML 글자로 그리는 부품이라, SVG 로 그리는
     여기와 공용으로 빼지 않습니다. */
  const edgeKept = (value: number) => value !== 0 && Math.abs(yAt(value) - zeroY) >= ZERO_GAP
  /* 최고·최저 높이의 가는 가로선. 0 과 같은 높이면 0 선이 대신합니다. */
  const guides = [high, low].filter((value, i, all) => value !== 0 && all.indexOf(value) === i)

  /* 선 끝 이름표 자리. 둘이 겹치면 합계는 제자리이고 전략이 멀어지는 쪽으로
     밀립니다(같은 높이면 아래). 그림 안쪽을 벗어나지 않게 막습니다. 아래쪽은
     이름표 칸 바닥의 「곡선 읽는 법」 단추 자리를 비워 두고 멈춥니다. 아래쪽
     14 는 그 단추의 높이(20)·바닥 여백(6)에서 나온 값이라, 단추 CSS 의 높이나
     위치를 바꾸면 함께 바꿉니다. */
  const tipMin = PAD.top + 6
  const tipMax = height - PAD.bottom - 14
  const totalTipY = Math.min(Math.max(yAt(lastTotal), tipMin), tipMax)
  let pickTipY = picked ? Math.min(Math.max(yAt(lastPick), tipMin), tipMax) : 0
  if (picked && Math.abs(pickTipY - totalTipY) < TIP_GAP) {
    const downward = pickTipY >= totalTipY
    pickTipY = downward ? totalTipY + TIP_GAP : totalTipY - TIP_GAP
    /* 밀어서 그림 밖으로 나가면 반대쪽으로 갑니다. */
    if (pickTipY > tipMax) pickTipY = totalTipY - TIP_GAP
    if (pickTipY < tipMin) pickTipY = totalTipY + TIP_GAP
  }

  const marks = dateMarks(Math.min(dates.length, total.length), plotW)
  const markLabels = dateLabels(dates, marks)

  return (
    <div className="ana-curve" ref={boxRef}>
      {ready && (
        <svg
          className="ana-curve-svg"
          width={width}
          height={height}
          role="img"
          aria-label={`누적 순손익 곡선 — ${totalLabel}${picked ? ` · ${pickLabel}` : ''}`}
        >
          <defs>
            {/* 0 선에서 위아래로 나누는 두 칸. 같은 선·면을 두 번 그리고 칸마다
                제 색만 보이게 합니다. */}
            <clipPath id={`${id}-up`}>
              <rect x={0} y={0} width={width} height={Math.max(zeroY, 0)} />
            </clipPath>
            <clipPath id={`${id}-down`}>
              <rect x={0} y={zeroY} width={width} height={Math.max(height - zeroY, 0)} />
            </clipPath>
            {/* 채움은 0 선에서 멀수록 짙고 0 선으로 갈수록 옅어집니다(계좌 추이의
                누적 곡선과 같은 정의). */}
            <linearGradient id={`${id}-fill-up`} gradientUnits="userSpaceOnUse" x1={0} y1={topY} x2={0} y2={zeroY}>
              <stop offset={0} className="ana-stop-up" stopOpacity={0.3} />
              <stop offset={1} className="ana-stop-up" stopOpacity={0} />
            </linearGradient>
            <linearGradient id={`${id}-fill-down`} gradientUnits="userSpaceOnUse" x1={0} y1={zeroY} x2={0} y2={bottomY}>
              <stop offset={0} className="ana-stop-down" stopOpacity={0} />
              <stop offset={1} className="ana-stop-down" stopOpacity={0.3} />
            </linearGradient>
          </defs>

          {area !== null && (
            <>
              <path d={area} fill={`url(#${id}-fill-up)`} clipPath={up} />
              <path d={area} fill={`url(#${id}-fill-down)`} clipPath={down} />
            </>
          )}

          {/* 0 선. 기준이라 늘 긋습니다. */}
          <line className="ana-zero" x1={PAD.left} x2={PAD.left + plotW} y1={zeroY} y2={zeroY} />
          {/* 최고·최저 높이. 선이 거기까지 갔다는 것을 가로로 이어 줍니다. */}
          {guides.map((value) => (
            <line
              key={`guide-${value}`}
              className="ana-guide"
              x1={PAD.left}
              x2={PAD.left + plotW}
              y1={yAt(value)}
              y2={yAt(value)}
            />
          ))}

          <text className="ana-axis" x={PAD.left - 8} y={zeroY} textAnchor="end" dominantBaseline="middle">
            0
          </text>
          {[high, low]
            .filter((value, i, all) => all.indexOf(value) === i && edgeKept(value))
            .map((value) => (
              <text
                key={`edge-${value}`}
                className="ana-axis"
                x={PAD.left - 8}
                y={yAt(value)}
                textAnchor="end"
                dominantBaseline="middle"
              >
                {axisText(value, currency)}
              </text>
            ))}

          {marks.map(({ i, ratio }, k) => (
            <text
              key={`date-${i}`}
              className="ana-axis"
              x={single ? xAt(0) : PAD.left + ratio * plotW}
              y={height - 6}
              textAnchor={k === 0 ? 'start' : k === marks.length - 1 ? 'end' : 'middle'}
            >
              {markLabels[k]}
            </text>
          ))}

          {/* 고른 전략이 먼저 깔리고 합계가 위에 섭니다 — 겹치는 자리에서
              합계가 가려지면 「전체가 어떻게 됐나」를 못 읽습니다. */}
          {picked && !single && picked.length > 1 && <path className="ana-line ana-line-pick" d={path(picked)} />}
          {!single &&
            (flat ? (
              <path className="ana-line ana-line-total" d={path(total)} />
            ) : (
              <>
                <path className="ana-line ana-line-total is-up" d={path(total)} clipPath={up} />
                <path className="ana-line ana-line-total is-down" d={path(total)} clipPath={down} />
              </>
            ))}
          {single && picked && picked.length > 0 && (
            <circle className="ana-dot ana-dot-pick" cx={xAt(0)} cy={yAt(picked[0])} r={3} />
          )}
          {single && (
            <circle className={`ana-dot ana-dot-total ${toneOf(total[0])}`.trim()} cx={xAt(0)} cy={yAt(total[0])} r={3.5} />
          )}

          {/* 선 끝 이름표. 범례를 따로 두지 않는 이유는, 범례가 선에서 멀수록
              색·모양을 기억해서 옮겨야 하기 때문입니다.
              오른쪽 끝에 붙여 두 줄(이름 / 금액)로 세웁니다 — 선 끝에서 시작하게
              하면 이름이 긴 전략에서 금액이 상자 밖으로 나가고, 잘린 금액은 다른
              수로 읽힙니다. 이름이 길면 이름만 말줄임합니다. */}
          <TipLabel
            x={width - 6}
            y={totalTipY}
            width={PAD.right - 12}
            name={totalLabel}
            amount={amountText(lastTotal, currency)}
            kind="total"
            tone={toneOf(lastTotal)}
          />
          {picked && (
            <TipLabel
              x={width - 6}
              y={pickTipY}
              width={PAD.right - 12}
              name={pickLabel}
              amount={amountText(lastPick, currency)}
              kind="pick"
              tone=""
            />
          )}
        </svg>
      )}
    </div>
  )
}

/** 선 끝 이름표 한 벌 — 이름 한 줄, 금액 한 줄. 이름은 폭을 넘으면 말줄임하고
 *  금액은 자르지 않습니다. */
function TipLabel({
  x,
  y,
  width,
  name,
  amount,
  kind,
  tone,
}: {
  x: number
  y: number
  width: number
  name: string
  amount: string
  kind: 'total' | 'pick'
  tone: string
}) {
  /* 글자 폭을 재는 대신 한 글자 폭(11px 글꼴, 한글 기준 약 11)으로 어림해 자릅니다.
     금액 줄이 기준이 아니라 이름 줄만 줄이므로 금액은 늘 온전합니다. */
  const room = Math.max(1, Math.floor(width / 11))
  const shown = name.length > room ? `${name.slice(0, Math.max(1, room - 1))}…` : name
  return (
    <g className={`ana-tip ana-tip-${kind}`}>
      <text className="ana-tip-name" x={x} y={y - 2} textAnchor="end">
        {shown}
        {shown !== name && <title>{name}</title>}
      </text>
      <text className={`ana-tip-amount ${tone}`.trim()} x={x} y={y + 13} textAnchor="end">
        {amount}
      </text>
    </g>
  )
}
